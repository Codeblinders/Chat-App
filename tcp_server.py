# tcp_server.py — AES-only non-blocking TCP server with auth, roster, chat, file streaming
import socket, select, sys, time, os, json, base64
from typing import Optional
from common import (
    pack, unpack, SMALL_INLINE_LIMIT, now_ts, OFFER_TTL_SEC, CHUNK_SIZE,
    ensure_cache_dir, PROGRESS_THROTTLE_CHUNKS, b64decode_str, b64encode_bytes,
    pbkdf2, derive_session_key, aes_available, aes_encrypt, aes_decrypt,
    udp_keys_set  # <-- use persistent key store
)

HOST = "0.0.0.0"
PORT = 5000
UDP_PORT = 20001

# --- server socket (non-blocking) ---
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(64)
server.setblocking(False)
print(f"🔐 AES TCP server on {HOST}:{PORT} (non-blocking)")

# --- runtime state ---
sockets = [server]
buffers = {}         # sock -> bytes
users = {}           # sock -> username
sessions = {}        # sock -> {"session_key": bytes}
roster = set()
users_db_path = os.path.join(os.getcwd(), "users.json")

# offers / streaming (unchanged from your working version)
offers = {}
next_offer_id = 1
active_streams = {}  # offer_id -> {"receivers": set(), "bytes": int, "chunks": int, "cache_fh": file, ...}

# --- users db ---
def load_users_db():
    if not os.path.exists(users_db_path):
        return {}
    with open(users_db_path, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return {}

def save_users_db(db):
    with open(users_db_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)

users_db = load_users_db()  # { username: {"salt": b64, "pw_hash": b64} }

# --- utils ---
def cleanup_socket(s):
    try: s.close()
    except: pass
    uname = users.pop(s, None)
    if uname and uname in roster:
        roster.discard(uname)
        broadcast({"type":"system","text":f"{uname} left."})
        send_roster()
    sessions.pop(s, None)
    buffers.pop(s, None)
    if s in sockets:
        try: sockets.remove(s)
        except ValueError: pass
    # remove from receivers
    for st in active_streams.values():
        st.get("receivers", set()).discard(s)
    # nullify sender_socket where needed
    for info in offers.values():
        if info.get("sender_socket") is s:
            info["sender_socket"] = None

def encrypt_for(sock, inner_obj):
    sess = sessions.get(sock)
    if not sess:
        return pack(inner_obj)
    try:
        data = json.dumps(inner_obj, ensure_ascii=False).encode("utf-8")
        nonce, ct, tag = aes_encrypt(data, sess["session_key"])
        obj = {"enc": True,
               "n": base64.b64encode(nonce).decode("ascii"),
               "t": base64.b64encode(tag).decode("ascii"),
               "c": base64.b64encode(ct).decode("ascii")}
        return pack(obj)
    except Exception:
        return pack(inner_obj)

def decrypt_payload_if_any(sock, obj):
    if not obj or not obj.get("enc"):
        return obj
    sess = sessions.get(sock)
    if not sess:
        return {"type":"system","text":"No session for encrypted payload"}
    try:
        nonce = base64.b64decode(obj["n"])
        tag   = base64.b64decode(obj["t"])
        ct    = base64.b64decode(obj["c"])
        plain = aes_decrypt(nonce, ct, tag, sess["session_key"])
        return json.loads(plain.decode("utf-8","ignore"))
    except Exception:
        return {"type":"system","text":"Decryption failed"}

def broadcast(obj, exclude: Optional[socket.socket]=None):
    for s in list(sockets):
        if s is server or s is exclude: continue
        try:
            s.sendall(encrypt_for(s, obj))
        except Exception:
            cleanup_socket(s)

def send_roster():
    broadcast({"type":"roster","users": sorted(list(roster))})

def cleanup_offers():
    now = now_ts()
    expired = [oid for oid, info in offers.items() if now - info.get('created', now) > OFFER_TTL_SEC]
    for oid in expired:
        offers.pop(oid, None)
        st = active_streams.pop(oid, None)
        if st and st.get("cache_fh"):
            try: st["cache_fh"].close()
            except: pass

def send_progress(offer_id, size):
    st = active_streams.get(offer_id)
    if not st: return
    msg = {"type":"progress","offer_id":offer_id,"bytes":st["bytes"],"size":size}
    for r in list(st["receivers"]):
        try:
            r.sendall(encrypt_for(r, msg))
        except Exception:
            st["receivers"].discard(r)
            cleanup_socket(r)

# --- auth helpers (also persists per-user UDP key) ---
def auth_begin(sock, username: str):
    entry = users_db.get(username)
    if entry:
        salt_b64 = entry["salt"]; mode = "login"
    else:
        salt = os.urandom(16); salt_b64 = base64.b64encode(salt).decode("ascii"); mode = "register"
        users_db[username] = {"salt": salt_b64, "pw_hash": None}
        save_users_db(users_db)
    try: sock.sendall(pack({"type":"auth_salt","mode":mode,"salt":salt_b64}))
    except: cleanup_socket(sock)

def auth_proof(sock, username: str, pw_hash_b64: str):
    """
    Validate user credentials, derive AES session keys for both TCP and UDP,
    and send 'auth_ok' back to the client. Keeps TCP alive after authentication.
    """

    entry = users_db.get(username)

    # --- Basic user validation ---
    if not entry:
        try:
            sock.sendall(pack({
                "type": "auth_error",
                "text": "User record missing; please register or retry."
            }))
        except Exception:
            pass
        print(f"[Auth] ❌ Missing user entry for {username}")
        return

    # --- Register new user or verify existing password hash ---
    if entry.get("pw_hash") is None:
        entry["pw_hash"] = pw_hash_b64
        save_users_db(users_db)
        ok = True
        print(f"[Auth] Registered new user {username}")
    else:
        ok = (pw_hash_b64 == entry["pw_hash"])

    if not ok:
        try:
            sock.sendall(pack({
                "type": "auth_error",
                "text": "Invalid credentials — please try again."
            }))
        except Exception:
            pass
        print(f"[Auth] ❌ Invalid password for {username}")
        return

    # --- Derive session keys ---
    try:
        # TCP AES session key
        session_salt = os.urandom(16)
        pw_hash = base64.b64decode(pw_hash_b64.encode("ascii"))
        tcp_key = derive_session_key(pw_hash, session_salt)

        # UDP AES key (independent 256-bit key)
        udp_key = os.urandom(32)
        udp_key_b64 = base64.b64encode(udp_key).decode("ascii")

        # Store for runtime and cross-module use (udp_server will read this)
        sessions[sock] = {"session_key": tcp_key}
        udp_keys_set(username, udp_key_b64)

        # Send auth confirmation to the client
        sock.sendall(pack({
            "type": "auth_ok",
            "session_salt": base64.b64encode(session_salt).decode("ascii"),
            "udp_key": udp_key_b64,
            "udp_port": UDP_PORT
        }))
        print(f"[Auth] ✅ Sent udp_key for {username}")

    except Exception as e:
        print(f"[Auth] ❌ Key derivation/send failed for {username}: {e}")
        try:
            sock.sendall(pack({
                "type": "auth_error",
                "text": "Server key generation error."
            }))
        except Exception:
            pass
        return

    # --- Register connection state ---
    users[sock] = username
    roster.add(username)

    # --- Broadcast join event to all connected clients ---
    broadcast({"type": "system", "text": f"{username} joined the chat."})
    send_roster()

    # ✅ Keep TCP socket open for continuous chat and file transfer
    # (Do NOT close or return prematurely — connection stays alive)




# --- main loop ---
last_cleanup = now_ts()
try:
    while True:
        if now_ts() - last_cleanup > 30:
            cleanup_offers(); last_cleanup = now_ts()

        try:
            rlist, _, xlist = select.select(sockets, [], sockets, 0.1)
        except Exception:
            rlist, xlist = [], []

        for s in rlist:
            if s is server:
                try:
                    cs, addr = server.accept()
                    cs.setblocking(False)
                    sockets.append(cs)
                    buffers[cs] = b""
                    print(f"TCP connect from {addr}")
                except Exception as e:
                    print("Accept error:", e)
                    continue
            else:
                try:
                    chunk = s.recv(65536)
                except BlockingIOError:
                    chunk = b""
                except (ConnectionResetError, OSError):
                    chunk = b""

                if not chunk:
                    uname = users.get(s, "anon")
                    if uname in roster:
                        roster.discard(uname)
                        broadcast({"type":"system","text":f"{uname} left."})
                        send_roster()
                    cleanup_socket(s)
                    continue

                buffers[s] += chunk
                while True:
                    if s not in buffers:
                        break  # socket was cleaned up
                    obj, rest = unpack(buffers[s])
                    if obj is None: break
                    buffers[s] = rest

                    obj = decrypt_payload_if_any(s, obj)
                    t = obj.get("type")

                    # --- auth ---
                    if t == "auth_begin":
                        auth_begin(s, obj.get("username","anon"))
                    elif t == "auth_proof":
                        auth_proof(s, obj.get("username","anon"), obj.get("pw_hash",""))

                    # --- chat ---
                    elif t == "chat":
                        sender = users.get(s,"anon")
                        broadcast({"type":"chat","text":obj.get("text",""),"sender":sender,"ts":now_ts()})

                    # --- file offering / sharing (unchanged logic) ---
                    elif t in ("file_share","file_offer"):
                        filename = obj.get("filename")
                        size = int(obj.get("size",0))
                        thumb_b64 = obj.get("thumb_b64")
                        inline_b64 = obj.get("inline_b64")
                        sender = users.get(s,"anon")
                        # global next_offer_id
                        offer_id = str(next_offer_id); next_offer_id += 1
                        cache_dir = ensure_cache_dir(); cache_path = None

                        if inline_b64 and size <= SMALL_INLINE_LIMIT:
                            try:
                                cache_path = os.path.join(cache_dir, f"{offer_id}_{filename}")
                                with open(cache_path,"wb") as fh:
                                    fh.write(b64decode_str(inline_b64))
                            except Exception:
                                cache_path = None

                        offers[offer_id] = {
                            "filename": filename, "size": size, "sender": sender,
                            "thumb_b64": thumb_b64,
                            "inline_b64": inline_b64 if inline_b64 and size <= SMALL_INLINE_LIMIT else None,
                            "sender_socket": s if (not inline_b64 or size > SMALL_INLINE_LIMIT) else None,
                            "created": now_ts(), "cache_path": cache_path
                        }

                        nonce = obj.get("nonce")
                        if nonce:
                            try: s.sendall(pack({"type":"offer_ack","offer_id":offer_id,"nonce":nonce}))
                            except: pass

                        broadcast({"type":"file_offer","offer_id":offer_id,"filename":filename,
                                   "size":size,"sender":sender,"thumb_b64":thumb_b64})

                    elif t == "file_get":
                        offer_id = obj.get("offer_id"); mode = obj.get("mode","download")
                        info = offers.get(offer_id)
                        if not info:
                            try: s.sendall(pack({"type":"system","text":f"Offer {offer_id} not found."}))
                            except: pass
                            continue
                        filename = info["filename"]; size = info["size"]; cache_path = info.get("cache_path")

                        if cache_path and os.path.exists(cache_path):
                            try:
                                with open(cache_path, "rb") as fh:
                                    sent = 0
                                    while True:
                                        cdata = fh.read(CHUNK_SIZE)
                                        if not cdata:
                                            try:
                                                s.sendall(pack({
                                                    "type": "file_chunk",
                                                    "offer_id": offer_id,
                                                    "data_b64": "",
                                                    "eof": True
                                                }))
                                            except Exception as e:
                                                print(f"[TCP] EOF send error: {e}")
                                            break
                                        
                                        try:
                                            s.sendall(pack({
                                                "type": "file_chunk",
                                                "offer_id": offer_id,
                                                "data_b64": b64encode_bytes(cdata),
                                                "eof": False
                                            }))
                                            sent += len(cdata)
                                            if sent // CHUNK_SIZE % PROGRESS_THROTTLE_CHUNKS == 0:
                                                try:
                                                    s.sendall(pack({
                                                        "type": "progress",
                                                        "offer_id": offer_id,
                                                        "bytes": sent,
                                                        "size": size
                                                    }))
                                                except Exception:
                                                    pass
                                        except BlockingIOError:
                                            time.sleep(0.02)
                                            continue
                                        except Exception as e:
                                            print(f"[TCP] Chunk send error: {e}")
                                            break
                                    print(f"[TCP] Finished sending {offer_id}, {sent}/{size} bytes")
                            except Exception as e:
                                try: s.sendall(pack({"type":"system","text":f"Cache read error: {e}"}))
                                except: pass
                            continue

                        if info.get("inline_b64"):
                            try:
                                s.sendall(pack({"type":"file_push","offer_id":offer_id,"filename":filename,"size":size,
                                                "mode":mode,"sender":info["sender"],"data_b64":info["inline_b64"]}))
                            except: pass
                            if not info.get("cache_path"):
                                try:
                                    cache_dir = ensure_cache_dir()
                                    cache_path = os.path.join(cache_dir, f"{offer_id}_{filename}")
                                    with open(cache_path,"wb") as fh:
                                        fh.write(b64decode_str(info["inline_b64"]))
                                    info["cache_path"] = cache_path
                                except Exception: pass
                            continue

                        st = active_streams.get(offer_id)
                        if not st:
                            st = {"receivers": set(), "bytes":0, "chunks":0, "cache_fh":None,
                                  "filename":filename, "size":size}
                            active_streams[offer_id] = st
                            try:
                                cache_dir = ensure_cache_dir()
                                cache_path = os.path.join(cache_dir, f"{offer_id}_{filename}")
                                st["cache_fh"] = open(cache_path,"wb")
                                info["cache_path"] = cache_path
                            except Exception:
                                st["cache_fh"] = None
                            sender_sock = info.get("sender_socket")
                            if sender_sock:
                                try: sender_sock.sendall(pack({"type":"file_fetch","offer_id":offer_id,"mode":mode}))
                                except Exception:
                                    try: s.sendall(pack({"type":"system","text":"Failed to reach sender for streaming."}))
                                    except: pass
                                    active_streams.pop(offer_id, None)
                                    continue
                        st["receivers"].add(s)

                    elif t == "file_chunk":
                        offer_id = obj.get("offer_id")
                        data_b64 = obj.get("data_b64","")
                        eof = obj.get("eof", False)
                        st = active_streams.get(offer_id); info = offers.get(offer_id)
                        if not st or not info: continue
                        if data_b64:
                            try: data = b64decode_str(data_b64)
                            except Exception: data = b""
                            if st.get("cache_fh"):
                                try: st["cache_fh"].write(data)
                                except: pass
                            pkt = pack({"type":"file_chunk","offer_id":offer_id,"data_b64":data_b64,"eof":False})
                            dead = []
                            for r in list(st["receivers"]):
                                try: r.sendall(pkt)
                                except Exception: dead.append(r)
                            for r in dead:
                                st["receivers"].discard(r); cleanup_socket(r)
                            st["bytes"] += len(data); st["chunks"] += 1
                            if st["chunks"] % PROGRESS_THROTTLE_CHUNKS == 0:
                                send_progress(offer_id, info["size"])
                        if eof:
                            pkt = pack({"type":"file_chunk","offer_id":offer_id,"data_b64":"","eof":True})
                            for r in list(st["receivers"]):
                                try: r.sendall(pkt)
                                except Exception: cleanup_socket(r)
                            if st.get("cache_fh"):
                                try: st["cache_fh"].close()
                                except: pass
                            active_streams.pop(offer_id, None)

                    elif t == "bye":
                        name = users.get(s,"anon")
                        if name in roster: roster.discard(name)
                        broadcast({"type":"system","text":f"{name} left."})
                        send_roster(); cleanup_socket(s)

        for s in xlist:
            cleanup_socket(s)

except KeyboardInterrupt:
    print("\n🛑 TCP server shutting down")
    for s in list(sockets):
        try: s.close()
        except: pass
    sys.exit(0)
