# udp_client.py – Fixed AES-encrypted UDP chat client
import socket, threading, json, base64, time, os
from common import aes_available, aes_encrypt, aes_decrypt, now_ts

if not aes_available():
    raise SystemExit("PyCryptodome required (pip install pycryptodome)")

class UDPClient:
    def __init__(self, host, port, username, on_event):
        """Initialize UDP client. Session key will be set externally."""
        self.host = host
        self.port = port
        self.username = username
        self.on_event = on_event
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.sock.bind(("", 0))
            print(f"[UDP] Bound to local port {self.sock.getsockname()[1]}")
        except Exception as e:
            print(f"[UDP] Bind error: {e}")

        self.sock.setblocking(False)
        self.sock.settimeout(0.1)
        self.running = False
        self.session_key = None
        self._connected_notified = False

    def set_session_key(self, key_bytes):
        """Set the AES session key (provided by TCP server after auth)."""
        if len(key_bytes) != 32:
            raise ValueError(f"UDP key must be 32 bytes, got {len(key_bytes)}")
        self.session_key = key_bytes
        print(f"[UDP] 🔑 Session key set ({len(key_bytes)} bytes)")

    def _send_plain(self, obj):
        """Send unencrypted message (only for initial handshake)."""
        try:
            data = json.dumps(obj).encode('utf-8')
            self.sock.sendto(data, (self.host, self.port))
        except Exception as e:
            print(f"[UDP] Send error: {e}")
            self.on_event({"type": "system", "text": f"UDP send error: {e}"})

    def _enc_outer(self, inner_obj):
        """Encrypt message with session key."""
        if not self.session_key:
            print("[UDP] ⚠️ No session key available for encryption")
            return json.dumps({"u": self.username, "plain": inner_obj}).encode()
        
        try:
            data = json.dumps(inner_obj, ensure_ascii=False).encode('utf-8')
            n, c, t = aes_encrypt(data, self.session_key)
            
            outer = {
                "u": self.username,
                "n": base64.b64encode(n).decode('ascii'),
                "t": base64.b64encode(t).decode('ascii'),
                "c": base64.b64encode(c).decode('ascii')
            }
            return json.dumps(outer).encode('utf-8')
        except Exception as e:
            print(f"[UDP] Encryption error: {e}")
            return None

    def _dec_outer(self, data):
        """Decrypt received message."""
        try:
            outer = json.loads(data.decode('utf-8'))
        except Exception as e:
            print(f"[UDP] JSON decode error: {e}")
            return None

        # Handle plain messages (fallback)
        if "plain" in outer:
            return outer.get("plain")

        # Decrypt encrypted messages
        if not all(k in outer for k in ("n", "t", "c")):
            print(f"[UDP] Missing encryption fields in message")
            return None

        if not self.session_key:
            print("[UDP] ⚠️ No session key for decryption")
            return None

        try:
            n = base64.b64decode(outer["n"])
            t = base64.b64decode(outer["t"])
            c = base64.b64decode(outer["c"])
            plain = aes_decrypt(n, c, t, self.session_key)
            return json.loads(plain.decode('utf-8'))
        except Exception as e:
            print(f"[UDP] Decrypt error: {e}")
            return None

    def connect(self):
        """Start UDP connection (assumes session key already set)."""
        if not self.session_key:
            self.on_event({"type": "system", "text": "❌ UDP: No session key available"})
            print("[UDP] ❌ Cannot connect without session key")
            return False

        print(f"[UDP] Starting encrypted session to {self.host}:{self.port}")
        self.running = True
        
        # Start receiver thread
        threading.Thread(target=self._recv_loop, daemon=True).start()
        
        # Start keepalive thread
        threading.Thread(target=self._keepalive, daemon=True).start()
        
        # ✅ FIX: Send a simple handshake ping instead of a chat message
        # This establishes the connection without creating duplicate UI messages
        time.sleep(0.2)
        obj = {
            "type": "handshake",
            "sender": self.username,
            "ts": now_ts()
        }
        encrypted = self._enc_outer(obj)
        if encrypted:
            try:
                self.sock.sendto(encrypted, (self.host, self.port))
                print(f"[UDP] ✅ Handshake sent to server")
            except Exception as e:
                print(f"[UDP] ⚠️ Handshake send error: {e}")
        
        return True

    def send_chat(self, text):
        """Send chat message via UDP."""
        if not self.running or not self.session_key:
            print("[UDP] ❌ Cannot send: not connected or no key")
            self.on_event({"type": "system", "text": "❌ Not connected to UDP"})
            return

        obj = {
            "type": "chat",
            "sender": self.username,
            "text": text,
            "ts": now_ts()
        }
        
        print(f"[UDP] 📤 Preparing to send: {obj}")
        encrypted = self._enc_outer(obj)
        
        if not encrypted:
            print("[UDP] ❌ Encryption failed")
            self.on_event({"type": "system", "text": "❌ Message encryption failed"})
            return
            
        try:
            sent_bytes = self.sock.sendto(encrypted, (self.host, self.port))
            print(f"[UDP] ✅ Sent {sent_bytes} bytes: {text[:50]}...")
        except Exception as e:
            print(f"[UDP] ❌ Send error: {e}")
            self.on_event({"type": "system", "text": f"❌ UDP send error: {e}"})

    def share_file(self, path, thumb_b64=None):
        """Share file via UDP (small files only, <50KB)."""
        try:
            size = os.path.getsize(path)
        except Exception as e:
            self.on_event({"type": "system", "text": f"File access error: {e}"})
            return

        if size > 48 * 1024:
            self.on_event({"type": "system", "text": "UDP limit ≈50KB; use TCP for larger files"})
            return

        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
        except Exception as e:
            self.on_event({"type": "system", "text": f"File read error: {e}"})
            return

        obj = {
            "type": "file_offer",
            "sender": self.username,
            "filename": os.path.basename(path),
            "size": size,
            "data_b64": b64,
            "thumb_b64": thumb_b64,
            "ts": now_ts()
        }
        
        encrypted = self._enc_outer(obj)
        if encrypted:
            try:
                self.sock.sendto(encrypted, (self.host, self.port))
                print(f"[UDP] ✅ File sent: {os.path.basename(path)}")
            except Exception as e:
                self.on_event({"type": "system", "text": f"UDP file send error: {e}"})

    def _keepalive(self):
        """Send periodic keepalive pings."""
        while self.running:
            time.sleep(20)
            if not self.running:
                break
            
            obj = {"type": "ping", "sender": self.username, "ts": now_ts()}
            encrypted = self._enc_outer(obj)
            if encrypted:
                try:
                    self.sock.sendto(encrypted, (self.host, self.port))
                    print("[UDP] 💓 Keepalive sent")
                except Exception as e:
                    print(f"[UDP] ⚠️ Keepalive error: {e}")

    def _recv_loop(self):
        """Receive and process UDP messages."""
        print("[UDP] 🎧 Receiver thread started")
        
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
                print(f"[UDP] 📥 Received {len(data)} bytes from {addr}")
            except socket.timeout:
                continue
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except Exception as e:
                if self.running:
                    print(f"[UDP] ❌ Receive error: {e}")
                    time.sleep(0.1)
                continue

            msg = self._dec_outer(data)
            if not msg:
                print("[UDP] ⚠️ Failed to decrypt message")
                continue

            print(f"[UDP] ✅ Decrypted message: {msg}")

            # Notify connection on first message
            if not self._connected_notified:
                self._connected_notified = True
                self.on_event({"type": "system", "text": f"✅ UDP connected to {self.host}:{self.port}"})
                print(f"[UDP] ✅ Connected to {self.host}:{self.port}")

            # ✅ FIX: Skip our own messages (they're already shown locally by client.py)
            msg_type = msg.get("type", "")
            sender = msg.get("sender", "")
            
            # Filter out messages from ourselves to prevent duplicates
            if sender == self.username and msg_type == "chat":
                print(f"[UDP] ⏭️  Skipping own message (already shown locally)")
                continue
            
            # Forward message to UI
            if isinstance(msg, dict) and "type" in msg:
                print(f"[UDP] 📨 Forwarding to UI: {msg_type} from {sender}")
                self.on_event(msg)
            else:
                print(f"[UDP] ⚠️ Invalid message format: {msg}")

        print("[UDP] 🛑 Receiver thread stopped")

    def close(self):
        """Close UDP connection."""
        print("[UDP] Closing connection...")
        self.running = False
        
        # Send goodbye message
        if self.session_key:
            try:
                obj = {"type": "bye", "sender": self.username}
                encrypted = self._enc_outer(obj)
                if encrypted:
                    self.sock.sendto(encrypted, (self.host, self.port))
                    print("[UDP] 👋 Goodbye message sent")
            except Exception as e:
                print(f"[UDP] ⚠️ Goodbye send error: {e}")
        
        try:
            self.sock.close()
        except Exception:
            pass
        
        print("[UDP] Socket closed")