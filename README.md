# Reach Chat — Secure AES Chat (TCP + UDP)

**A lightweight secure chat / file-sharing demo with:**

* AES-GCM encryption for TCP (session) and UDP (per-user) traffic. 
* A polished PyQt5 GUI client. 
* Non-blocking TCP server (auth, roster, streaming file transfer) and an AES UDP relay that uses per-user keys issued at auth time.

---

## Quick overview

This repository contains:

* `main_server.py` — helper that launches both servers (TCP + UDP). 
* `tcp_server.py` — AES-session TCP server: authentication, chat broadcasting, file offers/streaming. 
* `udp_server.py` — AES UDP relay that reads per-user UDP keys produced at TCP auth. 
* `tcp_client.py` — AES TCP client (auth, encrypted chat, file transfer/streaming). 
* `udp_client.py` — AES UDP client (encrypts messages using per-user UDP key). 
* `client.py` — wires GUI (PyQt5) to the TCP/UDP client logic; starts the GUI. 
* `ui.py` — the PyQt5-based chat UI (theme, controls, message/file cards). 
* `common.py` — shared helpers: framing, KDF (PBKDF2), AES wrappers, constants (file size limits, chunk size), persistent UDP key store. 

---

## Requirements

* **Python 3.10+** (the code uses modern union type syntax like `bytes | None`).
* `PyCryptodome` — required for AES-GCM encryption. 
* `PyQt5` — for the GUI. 

Recommended (example) `pip` install:

```bash
python -m pip install --upgrade pip
python -m pip install pycryptodome pyqt5
```

You can also create a `requirements.txt`:

```
pycryptodome
pyqt5
```

---

## Installation & setup

1. Clone the repository to your machine:

```bash
git clone <your-repo-url>
cd <repo-folder>
```

2. Install dependencies:

```bash
python -m pip install -r requirements.txt
# or
python -m pip install pycryptodome pyqt5
```

3. No DB server is required — user data is stored in `users.json` (created on first registration) and UDP keys are persisted to `udp_keys.json`. Those files are created automatically by the server code.

---

## Run the servers

To start both servers (recommended for local dev), run:

```bash
python main_server.py
```

`main_server.py` spawns `tcp_server.py` and `udp_server.py` as subprocesses. 

You can also start them separately (useful for debugging):

```bash
# Start TCP server (default binds 0.0.0.0:5000)
python tcp_server.py

# Start UDP server (default binds 0.0.0.0:20001)
python udp_server.py
```

Default ports: **TCP 5000**, **UDP 20001** (see `tcp_server.py` / `udp_server.py`).

---

## Run the client (GUI)

Start the GUI client (Qt):

```bash
python client.py
```

This opens the PyQt5 application (login fields + TCP/UDP toggle). The client authenticates to the TCP server first; if you choose UDP it will request and use the UDP key returned by the TCP auth flow.

---

## How authentication & encryption work (brief)

* Client requests auth salt (`auth_begin`) over TCP. Server replies with salt (register/login mode). Client derives a password hash using PBKDF2 and proves it (`auth_proof`). On first registration the server stores the derived password hash in `users.json`. 
* On successful proof the server:

  * derives a **TCP session AES key** (PBKDF2 + random session salt) and keeps the session alive for encrypted TCP traffic; and
  * generates a separate **32-byte UDP key** (random) for the user and writes it to `udp_keys.json` (so `udp_server.py` can read it). The TCP server responds with `auth_ok` including `session_salt` and the `udp_key`.
* TCP payloads are optionally encrypted using AES-GCM with the session key (helper functions live in `common.py`). UDP messages are encrypted with AES-GCM using the per-user key.

---

## File transfer / limits / streaming

* **TCP**: Supports inline small files and chunked streaming for larger files. The maximum allowed file size is **50 MB** (`MAX_FILE_BYTES` in `common.py`). Chunk size is `64 KB`.
* **UDP**: Only intended for very small payloads (~50 KB). If a user attempts to send larger files over UDP the GUI will prompt to use TCP instead.

Saved/read directories used at runtime:

* `users.json` — users DB (created automatically). 
* `udp_keys.json` — persistent per-user UDP keys. 
* `downloads/<username>/` — downloaded files. 
* `cache/` — temporary cached streaming files. 

---

## Typical workflow (GUI)

1. Start servers (`main_server.py`).
2. Run `python client.py`. In the GUI:

   * Enter **Username**, **Password**, **Server IP** (default `127.0.0.1`), and select **TCP** or **UDP** protocol. 
   * Click `Connect`. The client will perform the TCP auth flow. If choosing UDP, the client still authenticates via TCP first to obtain the UDP key, then establishes an AES-encrypted UDP session.
3. Chat, send/preview/download files, view active roster, etc.

---

## Troubleshooting & tips

* **Missing PyCryptodome** → the UDP client immediately aborts. Install with `pip install pycryptodome`. The code checks AES availability at startup.
* **PyQt5 errors** → ensure `pyqt5` is installed and matches your Python version. On some Linux distributions you may need system packages (or use a virtualenv). 
* **Port bind errors** → default ports `5000` (TCP) and `20001` (UDP) might be occupied. Edit `tcp_server.py` / `udp_server.py` variables if needed.
* **Files not appearing / permission errors** → check file system permissions for repo directory; `downloads/` and `cache/` are created automatically.

---

## Development notes

* The code intentionally keeps TCP open after authentication to support long-lived encrypted sessions and streaming file transfers. The UDP server reads per-user keys persisted by the TCP server to permit encrypted UDP relaying.
* For debugging you can run the TCP and UDP servers independently and use `tcp_client.py` / `udp_client.py` directly (they have CLI-friendly classes).

---

## Contributing

PRs and issues welcome. Things you might work on next:

* Add user presence persistence and reconnection handling.
* Add TLS to TCP control channel in addition to AES payloads (currently AES-GCM is used at the application level).
* Improve UDP NAT traversal (STUN) for cross-network usage.

---

## License

Add your preferred license file (e.g., `LICENSE`) to the repo. This README does not include a license by default.

---

## References (source files used to create this README)

Key source files referenced while writing this README:

* `common.py` — helpers, AES wrappers, KDF, limits. 
* `main_server.py` — server launcher. 
* `tcp_server.py` — authentication, TCP session handling, file streaming. 
* `udp_server.py` — UDP relay and per-user sessions. 
* `tcp_client.py` / `udp_client.py` — client-side behavior, file transfer, AES usage.
* `client.py` / `ui.py` — GUI wiring and UI implementation.

---
