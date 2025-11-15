# udp_server.py – Enhanced AES-encrypted UDP server with better broadcasting
import socket, json, base64, time, os
from common import aes_available, aes_encrypt, aes_decrypt, now_ts, udp_keys_get

HOST = "0.0.0.0"
UDP_PORT = 20001

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp.bind((HOST, UDP_PORT))
udp.setblocking(False)
print(f"🔷 AES UDP server running on {HOST}:{UDP_PORT}")

# Track active sessions: username -> (address, session_key)
sessions = {}  # username -> {"addr": (ip, port), "key": bytes, "last_seen": float}

def decrypt_for_user(username, outer):
    """Decrypt message using user's session key."""
    sess = sessions.get(username)
    if not sess or not sess.get("key"):
        print(f"[UDP] ⚠️  No session key for {username}")
        return None
    
    key = sess["key"]
    
    # Check if message has required fields
    if not all(k in outer for k in ("n", "t", "c")):
        print(f"[UDP] ⚠️  Missing encryption fields from {username}")
        return None
    
    try:
        n = base64.b64decode(outer["n"])
        t = base64.b64decode(outer["t"])
        c = base64.b64decode(outer["c"])
        plain = aes_decrypt(n, c, t, key)
        decrypted = json.loads(plain.decode('utf-8'))
        print(f"[UDP] ✅ Decrypted message from {username}: {decrypted.get('type', '?')}")
        return decrypted
    except Exception as e:
        print(f"[UDP] ❌ Decrypt error for {username}: {e}")
        return None

def encrypt_for_user(username, obj):
    """Encrypt message for specific user."""
    sess = sessions.get(username)
    if not sess or not sess.get("key"):
        print(f"[UDP] ⚠️  Cannot encrypt for {username}: no session")
        return None
    
    key = sess["key"]
    try:
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        n, c, t = aes_encrypt(data, key)
        encrypted = json.dumps({
            "u": username,
            "n": base64.b64encode(n).decode('ascii'),
            "t": base64.b64encode(t).decode('ascii'),
            "c": base64.b64encode(c).decode('ascii')
        }).encode('utf-8')
        return encrypted
    except Exception as e:
        print(f"[UDP] ❌ Encrypt error for {username}: {e}")
        return None

def broadcast_to_all(inner_obj, exclude_user=None):
    """
    Broadcast message to all connected users except sender.
    ✅ FIXED: Properly relays messages to all other users
    """
    count = 0
    failed = []
    
    msg_type = inner_obj.get('type', '?')
    sender = inner_obj.get('sender', '?')
    print(f"[UDP] 📢 Broadcasting '{msg_type}' from {sender} to {len(sessions)} users (exclude: {exclude_user})")
    
    for username, sess in list(sessions.items()):
        # Skip the sender (they already see their own message)
        if username == exclude_user:
            print(f"[UDP]   ⏭️  Skipping {username} (sender)")
            continue
        
        addr = sess.get("addr")
        if not addr:
            print(f"[UDP] ⚠️  No address for {username}")
            continue
        
        encrypted = encrypt_for_user(username, inner_obj)
        if encrypted:
            try:
                udp.sendto(encrypted, addr)
                count += 1
                print(f"[UDP]   ✅ Sent to {username} at {addr}")
            except Exception as e:
                print(f"[UDP]   ❌ Send error to {username}: {e}")
                failed.append(username)
        else:
            print(f"[UDP]   ⚠️  Failed to encrypt for {username}")
    
    # Clean up failed sessions
    for u in failed:
        sessions.pop(u, None)
    
    print(f"[UDP] 📊 Broadcast complete: {count} successful, {len(failed)} failed")
    return count

def cleanup_stale_sessions():
    """Remove sessions inactive for >5 minutes."""
    now = now_ts()
    stale = [u for u, s in sessions.items() if now - s.get("last_seen", 0) > 300]
    for u in stale:
        print(f"[UDP] 🧹 Removing stale session: {u}")
        del sessions[u]

print("✅ UDP relay ready (uses keys from TCP auth)")
last_cleanup = now_ts()
packet_count = 0

while True:
    # Periodic cleanup
    if now_ts() - last_cleanup > 60:
        cleanup_stale_sessions()
        last_cleanup = now_ts()
        print(f"[UDP] 📊 Active sessions: {len(sessions)}, Packets processed: {packet_count}")

    try:
        data, addr = udp.recvfrom(65536)
        packet_count += 1
    except BlockingIOError:
        time.sleep(0.01)
        continue
    except Exception as e:
        print(f"[UDP] ❌ Receive error: {e}")
        time.sleep(0.1)
        continue

    # Parse outer envelope
    try:
        outer = json.loads(data.decode('utf-8'))
    except Exception as e:
        print(f"[UDP] ❌ JSON parse error from {addr}: {e}")
        continue

    username = outer.get("u")
    if not username:
        print(f"[UDP] ⚠️  Missing username in packet from {addr}")
        continue

    # Check if this is first contact from this user
    if username not in sessions:
        # Load session key from persistent storage (set by TCP server)
        key = udp_keys_get(username)
        if not key:
            print(f"[UDP] ❌ No key found for {username} (must auth via TCP first)")
            # Send error response
            try:
                error_msg = json.dumps({
                    "type": "system",
                    "text": "❌ Please authenticate via TCP first"
                }).encode('utf-8')
                udp.sendto(error_msg, addr)
            except Exception:
                pass
            continue
        
        # Create session
        sessions[username] = {
            "addr": addr,
            "key": key,
            "last_seen": now_ts()
        }
        print(f"[UDP] ✅ New session for {username} from {addr}")
        
        # Send welcome message back to confirm connection
        welcome = encrypt_for_user(username, {
            "type": "system",
            "text": f"✅ UDP server received your connection",
            "ts": now_ts()
        })
        if welcome:
            try:
                udp.sendto(welcome, addr)
            except Exception as e:
                print(f"[UDP] ❌ Failed to send welcome: {e}")
    else:
        # Update address and timestamp
        old_addr = sessions[username]["addr"]
        if old_addr != addr:
            print(f"[UDP] 🔄 Address changed for {username}: {old_addr} -> {addr}")
        sessions[username]["addr"] = addr
        sessions[username]["last_seen"] = now_ts()

    # Decrypt message
    inner = decrypt_for_user(username, outer)
    if not inner:
        print(f"[UDP] ❌ Failed to decrypt message from {username}")
        continue

    msg_type = inner.get("type", "unknown")
    print(f"[UDP] 📨 {username} -> {msg_type}: {str(inner)[:100]}")

    # Add timestamp if missing
    if "ts" not in inner:
        inner["ts"] = now_ts()

    # Ensure sender field is set
    if "sender" not in inner:
        inner["sender"] = username

    # Handle different message types
    if msg_type == "ping":
        # Just update last_seen (already done above)
        print(f"[UDP] 💓 Keepalive from {username}")
        continue
    
    elif msg_type == "bye":
        # Remove session
        if username in sessions:
            del sessions[username]
            print(f"[UDP] 👋 {username} disconnected")
        
        # Notify others
        broadcast_to_all({
            "type": "system",
            "text": f"👋 {username} left UDP chat",
            "ts": now_ts()
        }, exclude_user=username)
        continue

    # ✅ KEY FIX: Broadcast chat messages to all other users
    # The sender already sees their message (shown immediately in client.py)
    if msg_type == "chat":
        count = broadcast_to_all(inner, exclude_user=username)
        print(f"[UDP] ✅ Chat message relayed to {count} users")
    elif msg_type == "file_offer":
        count = broadcast_to_all(inner, exclude_user=username)
        print(f"[UDP] ✅ File offer relayed to {count} users")
    else:
        # Broadcast other message types too
        count = broadcast_to_all(inner, exclude_user=username)
        print(f"[UDP] ✅ Message relayed to {count} users")