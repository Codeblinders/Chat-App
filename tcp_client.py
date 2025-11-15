# tcp_client.py — AES-only TCP client (auth, chat, file sharing/streaming)
import socket, threading, time, os, json, base64
from datetime import datetime
from common import (
    pack,
    unpack,
    b64encode_bytes,
    b64decode_str,
    ensure_downloads_dir,
    temp_file_path,
    open_with_default,
    MAX_FILE_BYTES,
    SMALL_INLINE_LIMIT,
    CHUNK_SIZE,
    gen_nonce,
    pbkdf2,
    derive_session_key,
    aes_available,
    aes_encrypt,
    aes_decrypt,
)

def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class TCPClient:
    def __init__(self, host, port, username, on_event, password="password"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.on_event = on_event

        self.sock = None
        self.buf = b""
        self.running = False
        self.session_key = None
        self._last_pw_hash = None

        # Upload helpers
        self._nonce_path = {}    # nonce -> local path (for our outgoing big offers)
        self._offer_path = {}    # offer_id -> local path (set after offer_ack for uploads)

        # Download helpers
        self._rx = {}            # offer_id -> (fh, out_path, mode)
        self._rx_modes = {}      # offer_id -> "download" | "preview"
        self._rx_filenames = {}  # offer_id -> original filename (persist for offer lifetime)

        self.hist_path = os.path.join(os.getcwd(), f"history_{self.username}.jsonl")

    # ---------- connection ----------
    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self.sock.setblocking(False)
        self.running = True
        threading.Thread(target=self._recv_loop, daemon=True).start()
        self._send_plain({"type": "auth_begin", "username": self.username})

    # ---------- send helpers ----------
    def _send_plain(self, obj):
        try:
            self.sock.sendall(pack(obj))
        except Exception as e:
            self.on_event({"type": "system", "text": f"Send error: {e}"})

    def _send_enc(self, inner_obj):
        if self.session_key is None or not aes_available():
            self._send_plain(inner_obj)
            return
        try:
            data = json.dumps(inner_obj, ensure_ascii=False).encode("utf-8")
            n, c, t = aes_encrypt(data, self.session_key)
            obj = {
                "enc": True,
                "n": base64.b64encode(n).decode("ascii"),
                "t": base64.b64encode(t).decode("ascii"),
                "c": base64.b64encode(c).decode("ascii"),
            }
            self.sock.sendall(pack(obj))
        except Exception as e:
            self.on_event({"type": "system", "text": f"Encrypt/send error: {e}"})

    def send(self, obj):
        self._send_enc(obj)

    # ---------- public API ----------
    def send_chat(self, text):
        self.send({"type": "chat", "text": text})

    def share_file(self, path, thumb_b64=None):
        try:
            size = os.path.getsize(path)
        except Exception as e:
            self.on_event({"type": "system", "text": f"File access error: {e}"})
            return
        if size > MAX_FILE_BYTES:
            self.on_event({"type": "system", "text": "File too large (limit exceeded)."})
            return

        if size <= SMALL_INLINE_LIMIT:
            try:
                with open(path, "rb") as f:
                    inline_b64 = b64encode_bytes(f.read())
                self.send({
                    "type": "file_offer",
                    "filename": os.path.basename(path),
                    "size": size,
                    "inline_b64": inline_b64,
                    "thumb_b64": thumb_b64,
                })
            except Exception as e:
                self.on_event({"type": "system", "text": f"File read/send error: {e}"})
        else:
            nonce = gen_nonce()
            self._nonce_path[nonce] = path
            self.send({
                "type": "file_offer",
                "filename": os.path.basename(path),
                "size": size,
                "thumb_b64": thumb_b64,
                "nonce": nonce,
            })

    def request_file(self, offer_id: str, mode: str = "download"):
        if mode not in ("download", "preview"):
            mode = "download"
        self._rx_modes[offer_id] = mode
        self.send({"type": "file_get", "offer_id": offer_id, "mode": mode})

    # ---------- history ----------
    def _hist_write(self, obj):
        try:
            with open(self.hist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------- receiver ----------
    def _recv_loop(self):
        while self.running:
            try:
                chunk = self.sock.recv(65536)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except Exception as e:
                self.on_event({"type": "system", "text": f"Receive error: {e}"})
                time.sleep(0.2)
                continue

            if not chunk:
                self.on_event({"type": "system", "text": "Disconnected"})
                break

            self.buf += chunk
            while True:
                obj, rest = unpack(self.buf)
                if obj is None:
                    break
                self.buf = rest

                # Decrypt if needed
                if obj.get("enc") and self.session_key is not None and aes_available():
                    try:
                        n = base64.b64decode(obj["n"])
                        t = base64.b64decode(obj["t"])
                        c = base64.b64decode(obj["c"])
                        plain = aes_decrypt(n, c, t, self.session_key)
                        obj = json.loads(plain.decode("utf-8", "ignore"))
                    except Exception as e:
                        self.on_event({"type": "system", "text": f"Decrypt error: {e}"})
                        continue

                t = obj.get("type")

                # -------- AUTH --------
                if t == "auth_salt":
                    salt_b64 = obj.get("salt")
                    try:
                        salt = base64.b64decode(salt_b64.encode("ascii"))
                    except Exception:
                        salt = b""
                    try:
                        pw_hash = pbkdf2(self.password, salt)
                        self._last_pw_hash = pw_hash
                        self._send_plain({
                            "type": "auth_proof",
                            "username": self.username,
                            "pw_hash": base64.b64encode(pw_hash).decode("ascii"),
                        })
                    except Exception as e:
                        self.on_event({"type": "system", "text": f"Auth derivation error: {e}"})

                elif t == "auth_ok":
                    try:
                        ssalt = base64.b64decode(obj["session_salt"].encode("ascii"))
                        udp_key_b64 = obj.get("udp_key")
                        udp_port = obj.get("udp_port", 20001)
                    except Exception:
                        self.on_event({"type": "system", "text": "Auth parse error"})
                        continue

                    base_key = self._last_pw_hash or pbkdf2(self.password, b"fallback")
                    try:
                        self.session_key = derive_session_key(base_key, ssalt)
                        if udp_key_b64:
                            self.on_event({"type": "udp_key", "key": udp_key_b64, "port": udp_port})
                        self.on_event({"type": "system", "text": "Authentication success. Encryption ready."})
                        self._send_enc({"type": "hello"})
                    except Exception as e:
                        self.on_event({"type": "system", "text": f"Key derivation error: {e}"})

                # -------- NORMAL --------
                elif t == "system":
                    self.on_event(obj)
                elif t == "roster":
                    self.on_event(obj)
                elif t == "chat":
                    obj["received_at"] = now_iso()
                    self._hist_write(obj)
                    self.on_event(obj)

                # -------- FILE FLOW --------
                elif t == "file_offer":
                    # Persist original filename for the lifetime of this offer
                    offer_id = obj.get("offer_id")
                    filename = obj.get("filename")
                    if offer_id and filename:
                        self._rx_filenames[offer_id] = filename  # keep; do not delete on EOF
                    self.on_event(obj)

                elif t == "offer_ack":
                    offer_id = obj.get("offer_id")
                    nonce = obj.get("nonce")
                    path = self._nonce_path.pop(nonce, None) if nonce else None
                    if path:
                        self._offer_path[offer_id] = path
                    self.on_event({"type": "system", "text": f"Offer acknowledged: {offer_id}"})

                elif t == "file_fetch":
                    offer_id = obj.get("offer_id")
                    path = self._offer_path.get(offer_id)
                    if not path:
                        self.on_event({"type": "system", "text": f"Stream request for unknown offer {offer_id}"})
                        continue
                    threading.Thread(
                        target=self._stream_file_thread, args=(offer_id, path, 0), daemon=True
                    ).start()

                elif t == "file_push":
                    filename = obj.get("filename")
                    data_b64 = obj.get("data_b64", "")
                    mode = obj.get("mode", "download")
                    try:
                        data = b64decode_str(data_b64)
                    except Exception:
                        data = b""
                    out = temp_file_path(filename) if mode == "preview" else os.path.join(
                        ensure_downloads_dir(self.username), filename
                    )
                    try:
                        with open(out, "wb") as fh:
                            fh.write(data)
                        if mode == "preview":
                            ok = open_with_default(out)
                            self.on_event({"type": "system", "text": f"Preview {'opened' if ok else 'saved'}: {out}"})
                        else:
                            self.on_event({"type": "system", "text": f"Downloaded: {out}"})
                    except Exception as e:
                        self.on_event({"type": "system", "text": f"File write error: {e}"})

                elif t == "file_chunk":
                    offer_id = obj.get("offer_id")
                    data_b64 = obj.get("data_b64", "")
                    eof = obj.get("eof", False)

                    if offer_id not in self._rx:
                        mode = self._rx_modes.get(offer_id, "download")
                        # Use persisted original filename; fallback if missing
                        fname = self._rx_filenames.get(offer_id, f"{offer_id}.bin")
                        out = temp_file_path(fname) if mode == "preview" else os.path.join(
                            ensure_downloads_dir(self.username), fname
                        )
                        try:
                            fh = open(out, "wb")
                        except Exception as e:
                            self.on_event({"type": "system", "text": f"Open file error: {e}"})
                            continue
                        self._rx[offer_id] = (fh, out, mode)

                    fh, out, mode = self._rx[offer_id]
                    if data_b64:
                        try:
                            fh.write(b64decode_str(data_b64))
                        except Exception as e:
                            self.on_event({"type": "system", "text": f"Chunk write error: {e}"})
                    if eof:
                        try:
                            fh.close()
                        except Exception:
                            pass
                        if mode == "preview":
                            ok = open_with_default(out)
                            self.on_event({"type": "system", "text": f"Preview {'opened' if ok else 'saved'}: {out}"})
                        else:
                            self.on_event({"type": "system", "text": f"Downloaded: {out}"})
                        # Clear only per-transfer state; DO NOT remove filename map
                        self._rx.pop(offer_id, None)

                elif t == "progress":
                    oid = obj.get("offer_id")
                    bso = obj.get("bytes", 0)
                    size = obj.get("size", 0)
                    pct = 0.0 if not size else (bso * 100.0 / size)
                    self.on_event({"type": "system", "text": f"Downloading {oid}: {bso}/{size} bytes ({pct:.1f}%)"})

                else:
                    self.on_event({"type": "system", "text": f"Unknown msg: {obj}"})

    # ---------- helpers ----------
    def _stream_file_thread(self, offer_id, path, offset=0):
        try:
            with open(path, "rb") as fh:
                if offset:
                    fh.seek(offset)
                while True:
                    c = fh.read(CHUNK_SIZE)
                    if not c:
                        self._send_enc({"type": "file_chunk", "offer_id": offer_id, "data_b64": "", "eof": True})
                        break
                    self._send_enc({
                        "type": "file_chunk",
                        "offer_id": offer_id,
                        "data_b64": b64encode_bytes(c),
                        "eof": False,
                    })
                    time.sleep(0.001)
        except Exception as e:
            self.on_event({"type": "system", "text": f"Stream error: {e}"})

    def close(self):
        self.running = False
        try:
            self._send_enc({"type": "bye"})
        except:
            pass
        try:
            self.sock.close()
        except:
            pass
        # Optional: clear filename map on full disconnect
        self._rx_filenames.clear()