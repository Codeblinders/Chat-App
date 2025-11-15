# client.py – Wires UI to TCP/UDP with a Qt signal (thread-safe)
# FIXED: Sender now sees their own UDP messages
import sys, os, base64, time
from datetime import datetime

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QObject, pyqtSignal

from tcp_client import TCPClient
from udp_client import UDPClient
from ui import ChatUI

def time_ts() -> int:
    return int(datetime.now().timestamp())


class ChatController(QObject):
    # Worker threads emit events through this signal -> handled on GUI thread
    net_event = pyqtSignal(dict)

    def __init__(self, ui: ChatUI):
        super().__init__()
        self.ui = ui
        self.tcp_client = None
        self.udp_client = None
        self.is_connected = False
        self.current_protocol = None  # "tcp" or "udp"
        self.server_host = None
        self.username = None

        # UI -> controller
        self.ui.connectRequested.connect(self._on_connect_requested)
        self.ui.disconnectRequested.connect(self._on_disconnect_requested)
        self.ui.sendMessageRequested.connect(self._on_send_message)
        self.ui.shareFileRequested.connect(self._on_share_file)
        self.ui.fileActionRequested.connect(self._on_file_action)

        # Net -> controller (GUI thread)
        self.net_event.connect(self._on_net_event)

    # ---------- Connection flow ----------
    def _on_connect_requested(self, req: dict):
        if self.is_connected:
            QMessageBox.warning(self.ui, "Already Connected", "Please disconnect first before reconnecting.")
            return

        self.username = req["username"]
        password = req["password"]
        self.server_host = req["host"]
        self.current_protocol = req["protocol"]  # 'tcp' or 'udp'

        try:
            if self.current_protocol == "tcp":
                self.ui.add_system(f"🔌 Connecting via TCP as {self.username}…", mine=True)
                self.tcp_client = TCPClient(self.server_host, 5000, self.username, self.net_event.emit, password=password)
                self.tcp_client.connect()
            else:  # udp
                self.ui.add_system(f"🔌 Authenticating via TCP for UDP session…", mine=True)
                self.tcp_client = TCPClient(self.server_host, 5000, self.username, self.net_event.emit, password=password)
                self.tcp_client.connect()

            self.is_connected = True
            self.ui.lock_connected()
            print(f"[CLIENT] Connecting via {self.current_protocol.upper()}…")

        except Exception as e:
            QMessageBox.critical(self.ui, "Connection Error", str(e))
            print(f"[CLIENT] Connection error: {e}")
            self.is_connected = False
            self.current_protocol = None

    def _on_disconnect_requested(self):
        if not self.is_connected:
            return

        try:
            if self.tcp_client:
                try:
                    self.tcp_client.close()
                    print("[CLIENT] TCP connection closed.")
                except Exception as e:
                    print(f"[CLIENT] TCP close error: {e}")
                self.tcp_client = None

            if self.udp_client:
                try:
                    self.udp_client.close()
                    print("[CLIENT] UDP connection closed.")
                except Exception as e:
                    print(f"[CLIENT] UDP close error: {e}")
                self.udp_client = None

            self.is_connected = False
            self.current_protocol = None
            self.ui.unlock_disconnected()
            self.ui.add_system("✅ Disconnected safely.", mine=True)
            print("[CLIENT] Disconnected cleanly.")

        except Exception as e:
            self.ui.add_system(f"⚠️ Disconnect error: {e}", mine=True)
            print(f"[CLIENT] Disconnect exception: {e}")
            self.is_connected = False
            self.current_protocol = None
            self.ui.unlock_disconnected()

    # ---------- Events from network (GUI thread via net_event) ----------
    def _on_net_event(self, obj: dict):
        t = obj.get("type")

        if t == "system":
            self.ui.add_system(obj.get("text", ""), mine=False)

        elif t == "roster":
            self.ui.update_roster(obj.get("users", []))

        elif t == "chat":
            sender = obj.get("sender", "anon")
            text = obj.get("text", "")
            ts = obj.get("ts", time_ts())
            mine = (sender == (self.username or ""))
            self.ui.add_chat(sender, text, mine, ts)

        elif t == "file_offer":
            self.ui.add_file_offer(
                obj.get("sender", "anon"),
                obj.get("filename"), obj.get("size"),
                obj.get("offer_id"), obj.get("thumb_b64")
            )

        elif t == "progress":
            self.ui.update_progress(
                obj.get("offer_id"),
                obj.get("bytes", 0),
                obj.get("size", 1)
            )

        elif t == "udp_key":
            # Only honor UDP key if the user chose UDP
            if self.current_protocol != "udp":
                print("[CLIENT] Ignoring UDP key because current protocol is TCP.")
                return
            try:
                key_b64 = obj.get("key")
                port = obj.get("port", 20001)
                if not key_b64:
                    raise ValueError("No UDP key received")

                key_bytes = base64.b64decode(key_b64.encode("ascii"))
                print(f"[CLIENT] Received UDP key: {len(key_bytes)} bytes")

                # Initialize UDP client
                self.udp_client = UDPClient(self.server_host, port, self.username, self.net_event.emit)
                self.udp_client.set_session_key(key_bytes)

                if self.udp_client.connect():
                    self.ui.add_system("✅ UDP encrypted connection established", mine=True)
                    print("[CLIENT] UDP session active")
                else:
                    raise Exception("UDP connection failed")

            except Exception as e:
                self.ui.add_system(f"❌ UDP setup error: {e}", mine=True)
                print(f"[CLIENT] UDP setup error: {e}")

        else:
            print(f"[CLIENT] Unknown message type: {t}")

    # ---------- UI -> Actions ----------
    def _on_send_message(self, msg: str):
        if not self.is_connected:
            QMessageBox.warning(self.ui, "Not Connected", "Please connect first.")
            return

        try:
            if self.current_protocol == "udp":
                if not self.udp_client:
                    QMessageBox.warning(self.ui, "UDP not ready", "UDP session not established yet.")
                    return
                
                # ✅ FIX: Show sender's own message immediately in UDP mode
                self.ui.add_chat(self.username, msg, mine=True, ts=time_ts())
                self.udp_client.send_chat(msg)
                print(f"[CLIENT] Sent via UDP: {msg[:50]}…")
            else:
                if not self.tcp_client:
                    QMessageBox.warning(self.ui, "No TCP Client", "TCP client not available.")
                    return
                self.tcp_client.send_chat(msg)
                print(f"[CLIENT] Sent via TCP: {msg[:50]}…")

        except Exception as e:
            QMessageBox.critical(self.ui, "Send Error", f"Failed to send message: {e}")
            print(f"[CLIENT] Send error: {e}")

    def _on_share_file(self, path: str, thumb_b64: str):
        if not self.is_connected:
            QMessageBox.warning(self.ui, "Not Connected", "Please connect first.")
            return

        try:
            fname = os.path.basename(path)
            if self.current_protocol == "udp":
                size = os.path.getsize(path)
                if size > 48 * 1024:
                    reply = QMessageBox.question(
                        self.ui,
                        "File Too Large",
                        "UDP supports files up to ~50KB. Use TCP for larger files?\n\n(This will use TCP temporarily)",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        return
                    if not self.tcp_client:
                        QMessageBox.warning(self.ui, "No TCP Client", "TCP client not available.")
                        return
                    self.tcp_client.share_file(path, thumb_b64)
                else:
                    if not self.udp_client:
                        QMessageBox.warning(self.ui, "UDP not ready", "UDP session not established yet.")
                        return
                    self.udp_client.share_file(path, thumb_b64)
            else:
                if not self.tcp_client:
                    QMessageBox.warning(self.ui, "No TCP Client", "TCP client not available.")
                    return
                self.tcp_client.share_file(path, thumb_b64)

            self.ui.add_system(f"📤 Shared file: {fname}", mine=True)

        except Exception as e:
            QMessageBox.critical(self.ui, "File Share Error", f"Failed to share file: {e}")
            print(f"[CLIENT] File share error: {e}")

    def _on_file_action(self, action: str, offer_id: str):
        if not self.tcp_client:
            QMessageBox.warning(self.ui, "Not Connected", "TCP required for file transfer")
            return
        self.tcp_client.request_file(offer_id, action)


# ---------- Entrypoint ----------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon.fromTheme("chat"))

    ui = ChatUI()
    controller = ChatController(ui)

    ui.show()
    sys.exit(app.exec_())