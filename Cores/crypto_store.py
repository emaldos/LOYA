"""Key management and file encryption for LOYA NG (storage rebuild, phase 1).

Envelope model
--------------
* One random 256-bit data key (DEK) protects everything at rest.
* The DEK is wrapped (AES-256-GCM) by a key-encryption key (KEK) derived from the PIN with
  Argon2id (m=64 MiB, t=3, p=4 by default). When argon2-cffi is missing we fall back to scrypt
  (N=2^17, r=8, p=1) and flag that in the key file so the wrap can be upgraded later.
* Changing the PIN, or raising the KDF cost, re-wraps the DEK only. No data is re-encrypted.
* Purpose keys are derived from the DEK with HKDF-SHA256, so the same bytes are never used by
  two algorithms:  SQLCipher raw key = HKDF(DEK, "loya-note/sqlcipher/v1"),
  file key = HKDF(DEK, salt=<random per file>, "loya-note/file/v1").

Key file (JSON, UTF-8, LF)
--------------------------
    {"format": "loya-keyfile", "v": 1,
     "kdf": {"name": "argon2id", "m_kib": 65536, "t": 3, "p": 4, "salt": "<b64>"},
     "kdf_fallback": false,
     "wrap": {"alg": "AES-256-GCM", "nonce": "<b64 12 bytes>", "ct": "<b64 32+16 bytes>"},
     "key_id": "<16 hex>", "created_at": "...", "updated_at": "..."}
The GCM AAD is the canonical JSON of format, v, kdf (salt included), kdf_fallback, wrap.alg
and key_id, so none of them can be edited without the unwrap failing. A wrong PIN and a
tampered key file are indistinguishable by design: both raise WrongPin.

Encrypted file / blob format (version 1)
----------------------------------------
    header (56 bytes): magic b"LOYAENC\\0" | version u8 = 1 | alg u8 = 1 (AES-256-GCM)
                       | flags u8 = 0 | reserved u8 = 0 | chunk_size u32 BE
                       | key_id 8 bytes | salt 32 bytes
    then chunks: AES-GCM(ciphertext || 16-byte tag); every chunk but the last holds exactly
    chunk_size plaintext bytes; the last holds 0..chunk_size bytes (an empty input is one
    empty final chunk).
Per-file key = HKDF(DEK, salt, "loya-note/file/v1"), so each file has its own key and the
nonces cannot collide across files. Chunk nonce = 3 zero bytes | chunk index u64 BE |
last-chunk flag u8 (the STREAM construction). AAD = the whole header. This detects header
edits, flipped bytes, reordered or duplicated chunks, truncation (the remaining last chunk
was sealed with flag 0) and appended data (the real last chunk is then opened with flag 0).

Memory hygiene, honestly
------------------------
Python cannot guarantee that secrets leave memory. We keep the DEK, the KEK and purpose keys
in bytearrays and zero them with wipe() as soon as we are done. But: the PIN arrives as an
immutable str; argon2/scrypt/cryptography take bytes and make their own copies; the SQLCipher
key has to be passed as a hex str inside a PRAGMA; and the GC may have moved or copied
buffers. wipe() narrows the window, it does not close it. Keep the process unswapped (OS-level)
if that matters to you.
"""
import base64
import ctypes
import hashlib
import hmac
import io
import json
import os
import struct
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

try:
    from argon2.low_level import Type as _Argon2Type
    from argon2.low_level import hash_secret_raw as _argon2_raw
    _HAS_ARGON2 = True
except Exception:  # pragma: no cover - depends on the environment
    _Argon2Type = None
    _argon2_raw = None
    _HAS_ARGON2 = False

KEYFILE_FORMAT = "loya-keyfile"
KEYFILE_VERSION = 1
WRAP_ALG = "AES-256-GCM"
KEY_LEN = 32
SALT_LEN = 16
DEFAULT_ARGON2 = {"name": "argon2id", "m_kib": 65536, "t": 3, "p": 4}
DEFAULT_SCRYPT = {"name": "scrypt", "n": 2 ** 17, "r": 8, "p": 1}
# Bounds on what a key file may ask for: the floor stops silly-weak wraps, the ceiling stops a
# crafted key file from making unlock allocate gigabytes or spin for minutes.
ARGON2_BOUNDS = {"m_kib": (8192, 2 * 1024 * 1024), "t": (1, 64), "p": (1, 64)}
SCRYPT_BOUNDS = {"n": (2 ** 14, 2 ** 22), "r": (1, 32), "p": (1, 16)}
SCRYPT_MAX_MEM = 1024 * 1024 * 1024

MAGIC = b"LOYAENC\x00"
FILE_VERSION = 1
ALG_AES256GCM = 1
_HEADER = struct.Struct(">8sBBBBI8s32s")
HEADER_LEN = _HEADER.size  # 56
FILE_SALT_LEN = 32
TAG_LEN = 16
DEFAULT_CHUNK = 64 * 1024
MIN_CHUNK = 4 * 1024
MAX_CHUNK = 16 * 1024 * 1024

_INFO_SQLCIPHER = b"loya-note/sqlcipher/v1"
_INFO_FILE = b"loya-note/file/v1"
_INFO_KEY_ID = b"loya-note/key-id/v1"


class CryptoStoreError(Exception):
    """Base class for every error raised here."""


class KeyFileError(CryptoStoreError):
    """The key file is missing, malformed, or uses an unsupported version/KDF/parameters."""


class WrongPin(CryptoStoreError):
    """The PIN does not unwrap the DEK (or the key file was tampered with)."""


class FormatError(CryptoStoreError):
    """Not a LOYA encrypted blob, or an unsupported version/algorithm/chunk size."""


class WrongKey(CryptoStoreError):
    """The blob was encrypted under a different DEK (key id mismatch)."""


class TamperError(CryptoStoreError):
    """A chunk failed authentication: tampered, reordered, truncated or extended."""


class TruncatedError(TamperError):
    """The stream ended before its final chunk."""


# ---------------------------------------------------------------- memory helpers

def wipe(buf):
    """Zero a bytearray (or writable memoryview) in place. Best effort, see the module docstring.
    Immutable bytes/str cannot be wiped and are ignored."""
    if buf is None:
        return
    try:
        if isinstance(buf, memoryview):
            if buf.readonly:
                return
            buf = buf.cast("B")
            n = len(buf)
            if n:
                ctypes.memset((ctypes.c_char * n).from_buffer(buf), 0, n)
            return
        if isinstance(buf, bytearray):
            n = len(buf)
            if n:
                ctypes.memset((ctypes.c_char * n).from_buffer(buf), 0, n)
    except Exception:
        try:
            for i in range(len(buf)):
                buf[i] = 0
        except Exception:
            pass


def _pin_bytes(pin):
    """NFC-normalise the PIN (the same PIN typed on Windows and Linux must give the same key)."""
    if isinstance(pin, (bytes, bytearray)):
        return bytearray(pin)
    if not isinstance(pin, str):
        raise TypeError("PIN must be str or bytes")
    return bytearray(unicodedata.normalize("NFC", pin).encode("utf-8"))


def _hkdf(ikm, info, salt=None, length=KEY_LEN):
    return bytearray(HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(bytes(ikm)))


def _raw_key(key):
    """Accept a DataKey or 32 raw bytes; return a bytes-like view of the DEK."""
    if isinstance(key, DataKey):
        return key._buf
    if isinstance(key, (bytes, bytearray, memoryview)) and len(key) == KEY_LEN:
        return key
    raise TypeError("key must be a DataKey or 32 raw bytes")


def _key_id(dek):
    return hmac.new(bytes(dek), _INFO_KEY_ID, hashlib.sha256).digest()[:8]


class DataKey:
    """The unwrapped DEK. Use as a context manager (or call wipe()) so the buffer is zeroed."""

    __slots__ = ("_buf",)

    def __init__(self, raw):
        if len(raw) != KEY_LEN:
            raise ValueError("DEK must be 32 bytes")
        self._buf = bytearray(raw)

    @classmethod
    def generate(cls):
        return cls(os.urandom(KEY_LEN))

    @property
    def key_id(self):
        """8-byte public identifier (HMAC of the DEK). Safe to store next to ciphertext."""
        self._check()
        return _key_id(self._buf)

    def sqlcipher_key(self):
        """The 32-byte raw SQLCipher key (HKDF purpose key). Caller should wipe() it."""
        self._check()
        return _hkdf(self._buf, _INFO_SQLCIPHER)

    def sqlcipher_hex(self):
        """Hex form for PRAGMA key="x'...'" (an immutable str; cannot be wiped)."""
        k = self.sqlcipher_key()
        try:
            return k.hex()
        finally:
            wipe(k)

    def copy(self):
        self._check()
        return DataKey(self._buf)

    def matches(self, other):
        return hmac.compare_digest(bytes(self._buf), bytes(_raw_key(other)))

    def wipe(self):
        wipe(self._buf)
        self._buf = bytearray()

    @property
    def wiped(self):
        return len(self._buf) != KEY_LEN

    def _check(self):
        if self.wiped:
            raise CryptoStoreError("data key was wiped")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.wipe()
        return False

    def __repr__(self):
        return "<DataKey wiped>" if self.wiped else "<DataKey id=%s>" % self.key_id.hex()

    def __reduce__(self):
        raise TypeError("DataKey cannot be pickled")


# ---------------------------------------------------------------- KDF

def has_argon2():
    return _HAS_ARGON2


def default_kdf():
    """The KDF a new wrap should use on this machine (without salt)."""
    return dict(DEFAULT_ARGON2) if _HAS_ARGON2 else dict(DEFAULT_SCRYPT)


def _int_param(params, name, bounds):
    v = params.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise KeyFileError("KDF parameter %s must be an integer" % name)
    lo, hi = bounds[name]
    if not lo <= v <= hi:
        raise KeyFileError("KDF parameter %s=%d is outside %d..%d" % (name, v, lo, hi))
    return v


def validate_kdf(kdf, need_salt=True):
    """Return a cleaned copy of kdf, or raise KeyFileError."""
    if not isinstance(kdf, dict):
        raise KeyFileError("kdf must be an object")
    name = kdf.get("name")
    if name == "argon2id":
        out = {"name": name}
        for k in ("m_kib", "t", "p"):
            out[k] = _int_param(kdf, k, ARGON2_BOUNDS)
    elif name == "scrypt":
        out = {"name": name}
        for k in ("n", "r", "p"):
            out[k] = _int_param(kdf, k, SCRYPT_BOUNDS)
        if out["n"] & (out["n"] - 1):
            raise KeyFileError("scrypt n must be a power of two")
        if 128 * out["n"] * out["r"] * out["p"] > SCRYPT_MAX_MEM:
            raise KeyFileError("scrypt parameters need too much memory")
    else:
        raise KeyFileError("unsupported KDF: %r" % (name,))
    if need_salt:
        try:
            salt = base64.b64decode(kdf.get("salt", ""), validate=True)
        except Exception:
            raise KeyFileError("kdf salt is not valid base64")
        if not 16 <= len(salt) <= 64:
            raise KeyFileError("kdf salt must be 16..64 bytes")
        out["salt"] = kdf["salt"]
    return out


def derive_kek(pin, kdf):
    """Derive the 32-byte KEK (bytearray) from the PIN and a validated kdf dict with salt."""
    kdf = validate_kdf(kdf)
    salt = base64.b64decode(kdf["salt"])
    secret = _pin_bytes(pin)
    try:
        if kdf["name"] == "argon2id":
            if not _HAS_ARGON2:
                raise KeyFileError("this key file needs Argon2id but argon2-cffi is not installed")
            out = _argon2_raw(bytes(secret), salt, time_cost=kdf["t"], memory_cost=kdf["m_kib"],
                              parallelism=kdf["p"], hash_len=KEY_LEN, type=_Argon2Type.ID)
        else:
            out = Scrypt(salt=salt, length=KEY_LEN, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(bytes(secret))
        return bytearray(out)
    finally:
        wipe(secret)


# ---------------------------------------------------------------- key file

def _now():
    return datetime.now(timezone.utc).isoformat()


def _b64(b):
    return base64.b64encode(bytes(b)).decode("ascii")


def _aad(kf):
    bound = {"format": kf["format"], "v": kf["v"], "kdf": kf["kdf"], "kdf_fallback": bool(kf["kdf_fallback"]),
             "alg": kf["wrap"]["alg"], "key_id": kf["key_id"]}
    return json.dumps(bound, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _new_kdf(kdf=None):
    base = dict(kdf) if kdf else default_kdf()
    base.pop("salt", None)
    base["salt"] = _b64(os.urandom(SALT_LEN))
    return validate_kdf(base)


def wrap_dek(dek, pin, kdf=None):
    """Wrap an existing DEK under a PIN. Returns the key-file dict (not written)."""
    raw = _raw_key(dek)
    kdf = _new_kdf(kdf)
    kf = {"format": KEYFILE_FORMAT, "v": KEYFILE_VERSION, "kdf": kdf, "kdf_fallback": kdf["name"] != "argon2id",
          "wrap": {"alg": WRAP_ALG, "nonce": "", "ct": ""}, "key_id": _key_id(raw).hex(),
          "created_at": _now(), "updated_at": _now()}
    kek = derive_kek(pin, kdf)
    try:
        nonce = os.urandom(12)
        ct = AESGCM(bytes(kek)).encrypt(nonce, bytes(raw), _aad(kf))
    finally:
        wipe(kek)
    kf["wrap"]["nonce"] = _b64(nonce)
    kf["wrap"]["ct"] = _b64(ct)
    return kf


def validate_keyfile(kf):
    if not isinstance(kf, dict) or kf.get("format") != KEYFILE_FORMAT:
        raise KeyFileError("not a LOYA key file")
    if kf.get("v") != KEYFILE_VERSION:
        raise KeyFileError("unsupported key file version: %r" % (kf.get("v"),))
    validate_kdf(kf.get("kdf"))
    w = kf.get("wrap")
    if not isinstance(w, dict) or w.get("alg") != WRAP_ALG:
        raise KeyFileError("unsupported wrap algorithm")
    try:
        nonce = base64.b64decode(w.get("nonce", ""), validate=True)
        ct = base64.b64decode(w.get("ct", ""), validate=True)
        kid = bytes.fromhex(kf.get("key_id", ""))
    except Exception:
        raise KeyFileError("key file has malformed fields")
    if len(nonce) != 12 or len(ct) != KEY_LEN + TAG_LEN or len(kid) != 8:
        raise KeyFileError("key file has fields of the wrong size")
    if not isinstance(kf.get("kdf_fallback"), bool):
        raise KeyFileError("kdf_fallback must be a boolean")
    return kf


def load_keyfile(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            kf = json.load(f)
    except FileNotFoundError:
        raise KeyFileError("key file not found: %s" % path)
    except ValueError:
        raise KeyFileError("key file is not valid JSON")
    return validate_keyfile(kf)


def save_keyfile(path, kf):
    validate_keyfile(kf)
    data = (json.dumps(kf, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with atomic_write(path) as f:
        f.write(data)


def _as_keyfile(kf_or_path):
    if isinstance(kf_or_path, dict):
        return validate_keyfile(kf_or_path)
    return load_keyfile(kf_or_path)


def create_keyfile(pin, path=None, kdf=None):
    """Generate a fresh DEK and wrap it. Returns (DataKey, keyfile dict); writes path atomically if given."""
    dek = DataKey.generate()
    try:
        kf = wrap_dek(dek, pin, kdf)
        if path:
            save_keyfile(path, kf)
    except BaseException:
        dek.wipe()
        raise
    return dek, kf


def unwrap(pin, kf_or_path):
    """Return the DataKey, or raise WrongPin. KeyFileError for malformed/unsupported files."""
    kf = _as_keyfile(kf_or_path)
    kek = derive_kek(pin, kf["kdf"])
    try:
        raw = AESGCM(bytes(kek)).decrypt(base64.b64decode(kf["wrap"]["nonce"]), base64.b64decode(kf["wrap"]["ct"]), _aad(kf))
    except InvalidTag:
        raise WrongPin("wrong PIN")
    finally:
        wipe(kek)
    dek = DataKey(raw)
    if not hmac.compare_digest(dek.key_id, bytes.fromhex(kf["key_id"])):
        dek.wipe()
        raise WrongPin("wrong PIN")
    return dek


def verify_pin(pin, kf_or_path):
    """True when the PIN unwraps the key file. Never raises for a wrong PIN."""
    try:
        unwrap(pin, kf_or_path).wipe()
        return True
    except WrongPin:
        return False


def verify_dek(dek, kf_or_path):
    """Constant-time check that dek is the key this key file wraps (by key id)."""
    kf = _as_keyfile(kf_or_path)
    return hmac.compare_digest(_key_id(_raw_key(dek)), bytes.fromhex(kf["key_id"]))


def rewrap(old_pin, new_pin, kf_or_path, kdf=None, path=None):
    """PIN change and/or KDF upgrade: unwrap with old_pin, wrap the same DEK with new_pin and a
    new salt/nonce (and kdf, default: this machine's default). Writes `path` (or the source path)
    atomically. Returns the new key-file dict. new_pin=None keeps the PIN (parameter upgrade)."""
    src_path = None if isinstance(kf_or_path, dict) else kf_or_path
    kf = _as_keyfile(kf_or_path)
    with unwrap(old_pin, kf) as dek:
        new = wrap_dek(dek, old_pin if new_pin is None else new_pin, kdf)
    new["created_at"] = kf.get("created_at", new["created_at"])
    target = path or src_path
    if target:
        save_keyfile(target, new)
    return new


def needs_upgrade(kf_or_path, target=None):
    """True when the wrap is weaker than `target` (default: default_kdf()) or uses the fallback KDF
    while Argon2id is now available."""
    kf = _as_keyfile(kf_or_path)
    cur = kf["kdf"]
    want = dict(target) if target else default_kdf()
    if cur["name"] != want["name"]:
        return cur["name"] == "scrypt" and want["name"] == "argon2id"
    keys = ("m_kib", "t", "p") if cur["name"] == "argon2id" else ("n", "r", "p")
    return any(cur[k] < want.get(k, cur[k]) for k in keys)


# ---------------------------------------------------------------- atomic write

def _fsync_dir(d):
    if os.name == "nt":
        return  # Windows cannot open a directory for fsync; NTFS journals the rename itself.
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace(src, dst, attempts=20):
    """os.replace with a short retry: on Windows an antivirus/indexer briefly holding dst gives PermissionError."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


@contextmanager
def atomic_write(path):
    """Yield a binary file; on clean exit it is fsynced and atomically moved over `path`.
    On any exception the temp file is removed and `path` is untouched. The temp file is created
    with mode 0600 on POSIX (mkstemp)."""
    path = os.path.abspath(path)
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(d)


# ---------------------------------------------------------------- streaming AES-GCM

def _nonce(idx, last):
    return b"\x00\x00\x00" + struct.pack(">Q", idx) + (b"\x01" if last else b"\x00")


def _read_full(f, n):
    parts = []
    while n > 0:
        b = f.read(n)
        if not b:
            break
        parts.append(b)
        n -= len(b)
    return b"".join(parts)


def _file_cipher(key, salt):
    fk = _hkdf(_raw_key(key), _INFO_FILE, salt=salt)
    try:
        return AESGCM(bytes(fk))
    finally:
        wipe(fk)


def encrypt_stream(src, dst, key, chunk_size=DEFAULT_CHUNK):
    """Read plaintext from file-like src, write the encrypted format to file-like dst. Returns bytes written."""
    if not MIN_CHUNK <= chunk_size <= MAX_CHUNK:
        raise ValueError("chunk_size must be %d..%d" % (MIN_CHUNK, MAX_CHUNK))
    raw = _raw_key(key)
    salt = os.urandom(FILE_SALT_LEN)
    header = _HEADER.pack(MAGIC, FILE_VERSION, ALG_AES256GCM, 0, 0, chunk_size, _key_id(raw), salt)
    aes = _file_cipher(raw, salt)
    dst.write(header)
    total = len(header)
    buf = _read_full(src, chunk_size)
    idx = 0
    while True:
        nxt = _read_full(src, chunk_size) if len(buf) == chunk_size else b""
        last = not nxt
        ct = aes.encrypt(_nonce(idx, last), buf, header)
        dst.write(ct)
        total += len(ct)
        if last:
            return total
        buf = nxt
        idx += 1


def read_header(f):
    """Parse and validate the header. Returns (header_bytes, chunk_size, key_id, salt)."""
    header = _read_full(f, HEADER_LEN)
    if len(header) < HEADER_LEN or header[:8] != MAGIC:
        raise FormatError("not a LOYA encrypted file")
    magic, ver, alg, flags, _res, chunk_size, kid, salt = _HEADER.unpack(header)
    if ver != FILE_VERSION:
        raise FormatError("unsupported encrypted file version %d" % ver)
    if alg != ALG_AES256GCM or flags != 0:
        raise FormatError("unsupported algorithm or flags")
    if not MIN_CHUNK <= chunk_size <= MAX_CHUNK:
        raise FormatError("invalid chunk size")
    return header, chunk_size, kid, salt


def decrypt_stream(src, key):
    """Generator of authenticated plaintext chunks from file-like src. Every yielded chunk is
    authentic, but the stream is only complete when the generator finishes without raising:
    callers must discard what they got if it raises."""
    raw = _raw_key(key)
    header, chunk_size, kid, salt = read_header(src)
    if not hmac.compare_digest(kid, _key_id(raw)):
        raise WrongKey("encrypted with a different data key")
    aes = _file_cipher(raw, salt)
    block = chunk_size + TAG_LEN
    buf = _read_full(src, block)
    idx = 0
    while True:
        if not buf:
            raise TruncatedError("encrypted stream ended before its final chunk")
        nxt = _read_full(src, block) if len(buf) == block else b""
        last = not nxt
        if len(buf) < TAG_LEN:
            raise TruncatedError("encrypted chunk %d is cut short" % idx)
        try:
            pt = aes.decrypt(_nonce(idx, last), buf, header)
        except InvalidTag:
            raise TamperError("chunk %d failed authentication (tampered, reordered or truncated)" % idx)
        yield pt
        if last:
            return
        buf = nxt
        idx += 1


def encrypt_bytes(data, key, chunk_size=DEFAULT_CHUNK):
    out = io.BytesIO()
    encrypt_stream(io.BytesIO(bytes(data)), out, key, chunk_size)
    return out.getvalue()


def decrypt_bytes(blob, key):
    return b"".join(decrypt_stream(io.BytesIO(bytes(blob)), key))


def encrypt_file(src_path, dst_path, key, chunk_size=DEFAULT_CHUNK):
    """Encrypt src_path into dst_path atomically (dst_path may equal src_path)."""
    with open(src_path, "rb") as src, atomic_write(dst_path) as dst:
        return encrypt_stream(src, dst, key, chunk_size)


def decrypt_file(src_path, dst_path, key):
    """Decrypt src_path into dst_path atomically. On any error dst_path is untouched and no
    partial plaintext is left behind."""
    with open(src_path, "rb") as src, atomic_write(dst_path) as dst:
        for chunk in decrypt_stream(src, key):
            dst.write(chunk)


def is_encrypted_blob(data):
    return bytes(data[:8]) == MAGIC


def is_encrypted_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(8) == MAGIC
    except OSError:
        return False


# ---------------------------------------------------------------- JSON helpers

def encrypt_json(obj, key):
    return encrypt_bytes(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), key)


def decrypt_json(blob, key):
    return json.loads(decrypt_bytes(blob, key).decode("utf-8"))


def write_json(path, obj, key):
    """Atomically write obj as an encrypted JSON file."""
    data = encrypt_json(obj, key)
    with atomic_write(path) as f:
        f.write(data)


_MISSING = object()


def read_json(path, key, default=_MISSING):
    """Read an encrypted JSON file. A missing file returns `default` when given; tampering,
    a wrong key and malformed files always raise (silently returning the default there would
    let a corrupted store be overwritten with an empty one)."""
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except FileNotFoundError:
        if default is _MISSING:
            raise
        return default
    return decrypt_json(blob, key)

