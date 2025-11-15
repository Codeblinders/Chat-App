# main_server.py — run both AES-only servers
import subprocess, sys, time

print("🚀 Launching Reach Chat AES Servers (TCP+UDP)")
tcp = subprocess.Popen([sys.executable, "tcp_server.py"])
time.sleep(0.5)
udp = subprocess.Popen([sys.executable, "udp_server.py"])
time.sleep(0.5)
print("✅ Both servers running. Press Ctrl+C to stop.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n🛑 Shutting down...")
    tcp.terminate(); udp.terminate()
    tcp.wait(); udp.wait()
