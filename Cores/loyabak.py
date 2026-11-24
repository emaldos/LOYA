"""`.loyabak`: an encrypted backup container (storage rebuild, phase 2).

    magic b"LOYABAK\\0" (8) | header length u32 BE | header JSON (UTF-8) | crypto_store stream of the backup zip

The header is public but safe: {"v":1, "kind":"data", "created_at":..., "app":..., "keyfile": <crypto_store key file>}.
The key file is the PIN-wrapped data key that was current when the backup was taken, so a backup can be restored with the
PIN of that time on any machine; the zip itself (DB, stores, attachments) is AES-256-GCM under that data key. The header is
bound to the stream: the stream's key id must match the key file's, and the stream authenticates every chunk.
"""
import io
import json
import os
import struct

from Cores import crypto_store as _cs

MAGIC = b"LOYABAK\x00"
VERSION = 1
MAX_HEADER = 64 * 1024
EXT = ".loyabak"


class BackupError(Exception):
    pass


def is_loyabak(path):
    try:
        with open(path, "rb") as f:
            return f.read(8) == MAGIC
    except OSError:
        return False


def _read_header_from(f):
    if f.read(8) != MAGIC:
        raise BackupError("Not a LOYA encrypted backup.")
    raw = f.read(4)
    if len(raw) != 4:
        raise BackupError("The backup is cut short.")
    n = struct.unpack(">I", raw)[0]
    if not 2 <= n <= MAX_HEADER:
        raise BackupError("The backup header is invalid.")
    try:
        header = json.loads(f.read(n).decode("utf-8"))
    except Exception:
        raise BackupError("The backup header is invalid.")
    if not isinstance(header, dict) or header.get("v") != VERSION or not isinstance(header.get("keyfile"), dict):
        raise BackupError("Unsupported backup version.")
    try:
        _cs.validate_keyfile(header["keyfile"])
    except _cs.KeyFileError as e:
        raise BackupError(f"The backup key is invalid: {e}")
    return header


def read_header(path):
    with open(path, "rb") as f:
        return _read_header_from(f)


def write(zip_path, dst_path, dek, keyfile, meta=None):
    """Encrypt the zip at zip_path into dst_path (atomic). keyfile: the key-file dict that wraps dek."""
    if not _cs.verify_dek(dek, keyfile):
        raise BackupError("The key file does not match the data key.")
    header = dict(meta or {})
    header.update({"v": VERSION, "keyfile": keyfile})
    hb = json.dumps(header, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with open(zip_path, "rb") as src, _cs.atomic_write(dst_path) as out:
        out.write(MAGIC + struct.pack(">I", len(hb)) + hb)
        _cs.encrypt_stream(src, out, dek)
    return dst_path


def unwrap(path, pin):
    """The backup's data key from the PIN that was current when it was made (raises crypto_store.WrongPin)."""
    return _cs.unwrap(pin, read_header(path)["keyfile"])


def decrypt_to(path, dst_zip, dek):
    """Decrypt the backup's zip into dst_zip (atomic; nothing is left on failure)."""
    with open(path, "rb") as f:
        header = _read_header_from(f)
        if not _cs.verify_dek(dek, header["keyfile"]):
            raise BackupError("This key does not open the backup.")
        with _cs.atomic_write(dst_zip) as out:
            for chunk in _cs.decrypt_stream(f, dek):
                out.write(chunk)
    return dst_zip


def verify(path, dek):
    """Authenticate every chunk without writing anything. Returns the plaintext size."""
    n = 0
    with open(path, "rb") as f:
        header = _read_header_from(f)
        if not _cs.verify_dek(dek, header["keyfile"]):
            raise BackupError("This key does not open the backup.")
        for chunk in _cs.decrypt_stream(f, dek):
            n += len(chunk)
    return n
