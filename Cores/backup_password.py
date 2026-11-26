"""The backup password: what protects a full backup (.loyabak) when encryption at rest is off.

A backup is always encrypted (Cores/loyabak.py). With encryption at rest on, the PIN-wrapped data key protects it; otherwise a
fresh data key is wrapped under this password (Argon2id + AES-256-GCM, crypto_store.wrap_dek). The password can be remembered
for automatic and update backups, but only in the OS keyring (Windows Credential Locker, macOS Keychain, Secret Service /
KWallet): never in Data/, settings.json or the DB. Without a remembered password, automatic backups are skipped (with a notice)
instead of being written unencrypted.
"""
import hashlib
import os

MIN_LEN = 8
_SERVICE = "LOYA NG backup"


class PasswordRequired(ValueError):
    pass


def _user():
    """A per-install keyring user name: two installs on one machine keep separate passwords."""
    try:
        from Cores import common_db as _cdb
        d = os.path.normcase(os.path.abspath(_cdb.data_dir()))
    except Exception:
        d = ""
    return "backup-" + hashlib.sha256(d.encode("utf-8", "replace")).hexdigest()[:16]


def _keyring():
    """The keyring module when a real OS store is available (the same rule as external agent API keys), else None."""
    try:
        from Cores.Services import ext_agents_service as _ea
        return _ea._keyring()
    except Exception:
        return None


def available():
    return _keyring() is not None


def get():
    kr = _keyring()
    if kr is None:
        return None
    try:
        v = kr.get_password(_SERVICE, _user())
        return v or None
    except Exception:
        return None


def has():
    return bool(get())


def remember(password):
    """Store the password in the OS keyring. False when no keyring is available (nothing is written anywhere else)."""
    kr = _keyring()
    if kr is None or not password:
        return False
    try:
        kr.set_password(_SERVICE, _user(), str(password))
        return True
    except Exception:
        return False


def forget():
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(_SERVICE, _user())
    except Exception:
        pass
    return True


def strength(password):
    """A rough hint, not a policy: {"score": 0..4, "label": ...}."""
    p = str(password or "")
    score = 0
    if len(p) >= MIN_LEN:
        score += 1
    if len(p) >= 12:
        score += 1
    classes = sum(1 for f in (str.islower, str.isupper, str.isdigit) if any(f(c) for c in p)) + (1 if any(not c.isalnum() for c in p) else 0)
    if classes >= 3:
        score += 1
    if len(p) >= 16 and classes >= 2:
        score += 1
    if len(set(p)) <= 2:
        score = 0
    return {"score": score, "label": ("Too weak", "Weak", "Fair", "Good", "Strong")[score]}


def check(password, confirm=None):
    """Error text for a new backup password, or "" when it can be used."""
    p = str(password or "")
    if len(p) < MIN_LEN:
        return f"The backup password should be at least {MIN_LEN} characters."
    if confirm is not None and str(confirm) != p:
        return "The passwords do not match."
    return ""
