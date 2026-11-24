"""API keys kept inside the encrypted DB (storage rebuild, phase 2).

Replaces the PIN-derived Fernet (`ext_agents_service._pin_fernet`): when a key cannot go to the OS keyring it is stored here,
in the Secrets table of the SQLCipher database, so it is protected by the same envelope data key as everything else and never
appears in settings.json - not even as ciphertext. Available only while encryption at rest is on and the app is unlocked;
otherwise callers fall back to keeping the key for the session only.

Names in use: "ext_agent:<provider>", "cve:nvd".
"""
from datetime import datetime, timezone

from Cores import common_db as _common_db


def available():
    # The session key exists only while unlocked (lock_now wipes it); the DB-lock flag is not consulted because it is still set
    # during unlock itself, when legacy keys are adopted.
    return _common_db.encryption_configured() and _common_db.session_key() is not None


def _con():
    con = _common_db.connect(timeout=10)
    _common_db._create_storage_tables(con.cursor())
    return con


def put(name, value, hint=""):
    if not available():
        return False
    con = _con()
    try:
        con.execute("INSERT INTO Secrets(name,value,hint,updated_at) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,hint=excluded.hint,updated_at=excluded.updated_at",
                    (str(name), str(value), str(hint or ""), datetime.now(timezone.utc).isoformat()))
        con.commit()
        return True
    finally:
        con.close()


def get(name):
    if not available():
        return None
    try:
        con = _con()
        try:
            row = con.execute("SELECT value FROM Secrets WHERE name=?", (str(name),)).fetchone()
        finally:
            con.close()
        return row[0] if row else None
    except Exception:
        return None


def delete(name):
    if not available():
        return False
    try:
        con = _con()
        try:
            con.execute("DELETE FROM Secrets WHERE name=?", (str(name),))
            con.commit()
        finally:
            con.close()
        return True
    except Exception:
        return False
