# common.py — shared helpers for AES-only transport (TCP+UDP), framing, files
import struct, json, os, sys, tempfile, subprocess, base64, time, mimetypes, hashlib

# ---------- Limits / settings ----------
MAX_FILE_BYTES = 50 * 1024 * 1024
SMALL_INLINE_LIMIT = 1 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
OFFER_TTL_SEC = 15 * 60
PROGRESS_THROTTLE_CHUNKS = 4

UDP_KEYS_FILE = "udp_keys.json"   # username -> b64 key (derived per-login)

# ---------- Length-prefixed JSON (for TCP) ----------
def pack(obj: dict) -> bytes:
    data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    return struct.pack('!I', len(data)) + data

def unpack(stream: bytes):
    if len(stream) < 4:
        return None, stream
    length = struct.unpack('!I', stream[:4])[0]
    if len(stream) < 4 + length:
        return None, stream
    body = stream[4:4+length]
    rest = stream[4+length:]
    obj = json.loads(body.decode('utf-8', errors='ignore'))
    return obj, rest

# ---------- Small helpers ----------
def b64encode_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode('ascii')

def b64decode_str(s: str) -> bytes:
    return base64.b64decode(s.encode('ascii'))

def open_with_default(path: str):
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)  # type: ignore
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except Exception:
        return False

def ensure_downloads_dir(subdir=''):
    base = os.path.join(os.getcwd(), 'downloads')
    if subdir:
        base = os.path.join(base, subdir)
    os.makedirs(base, exist_ok=True)
    return base

def ensure_cache_dir():
    base = os.path.join(os.getcwd(), 'cache')
    os.makedirs(base, exist_ok=True)
    return base

def temp_file_path(filename: str) -> str:
    d = tempfile.gettempdir()
    return os.path.join(d, f'preview_{filename}')

def gen_nonce(n=10) -> str:
    import random, string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

def is_image_filename(name: str) -> bool:
    typ, _ = mimetypes.guess_type(name)
    return typ is not None and typ.startswith('image/')

def now_ts() -> float:
    return time.time()

# ---------- Password hashing / KDF ----------
def pbkdf2(password: str, salt: bytes, rounds: int = 200_000, dklen: int = 32) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds, dklen)

def derive_session_key(base_key: bytes, session_salt: bytes) -> bytes:
    # derive 32-byte key from base_key (e.g., pw_hash) and a salt
    return hashlib.pbkdf2_hmac('sha256', base_key, session_salt, 100_000, 32)

# ---------- AES-GCM (PyCryptodome) ----------
try:
    from Cryptodome.Cipher import AES
    from Cryptodome.Random import get_random_bytes
except Exception:
    AES = None
    get_random_bytes = None

def aes_available() -> bool:
    return AES is not None and get_random_bytes is not None

def aes_encrypt(plain: bytes, key: bytes):
    cipher = AES.new(key, AES.MODE_GCM)
    ct, tag = cipher.encrypt_and_digest(plain)
    return cipher.nonce, ct, tag

def aes_decrypt(nonce: bytes, ciphertext: bytes, tag: bytes, key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)

# ---------- UDP per-user keys store ----------
def _load_udp_keys():
    if not os.path.exists(UDP_KEYS_FILE):
        return {}
    try:
        with open(UDP_KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_udp_keys(d):
    tmp = UDP_KEYS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, UDP_KEYS_FILE)

def udp_keys_set(username: str, key_b64: str):
    d = _load_udp_keys()
    d[username] = key_b64
    _save_udp_keys(d)

def udp_keys_get(username: str) -> bytes | None:
    d = _load_udp_keys()
    k = d.get(username)
    if not k:
        return None
    try:
        return base64.b64decode(k.encode("ascii"))
    except Exception:
        return None

# ----------------------------------------------------------------------
# 🧠 User database helpers (shared between TCP + UDP)
# ----------------------------------------------------------------------
import json, os, base64, hashlib

USERS_DB_PATH = os.path.join(os.getcwd(), "users.json")

def load_users_db():
    """Load users.json, return {} if not found or invalid."""
    if not os.path.exists(USERS_DB_PATH):
        return {}
    try:
        with open(USERS_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users_db(db):
    """Safely save users.json."""
    try:
        with open(USERS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        print(f"[UsersDB] Save error: {e}")

def ensure_user(username: str, password: str):
    """Register new user if not exists (TCP or UDP can use)."""
    db = load_users_db()
    if username in db:
        return False  # already exists
    salt = os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    db[username] = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "pw_hash": base64.b64encode(pw_hash).decode("ascii")
    }
    save_users_db(db)
    print(f"[UsersDB] ✅ Registered new user: {username}")
    return True

def verify_user(username: str, password: str):
    """Return True if username+password valid, else False."""
    db = load_users_db()
    entry = db.get(username)
    if not entry:
        return False
    try:
        salt = base64.b64decode(entry["salt"])
        pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return base64.b64encode(pw_hash).decode("ascii") == entry["pw_hash"]
    except Exception:
        return False
