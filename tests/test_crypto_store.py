import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import ROOT  # noqa: F401  (puts the repo on sys.path)

try:
    from Cores import crypto_store as cs
    _IMPORT_ERR = None
except Exception as e:  # cryptography missing
    cs = None
    _IMPORT_ERR = e

# Cheap parameters keep the suite fast; the defaults are exercised once in DefaultParamsTests.
FAST_ARGON2 = {"name": "argon2id", "m_kib": 8192, "t": 1, "p": 1}
FAST_SCRYPT = {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1}


def _need_argon2():
    return cs is not None and cs.has_argon2()


@unittest.skipIf(cs is None, "cryptography not installed: %s" % (_IMPORT_ERR,))
class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="loya_crypto_")
        self.key = cs.DataKey.generate()

    def tearDown(self):
        self.key.wipe()
        shutil.rmtree(self.dir, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.dir, name)

    def read(self, name):
        with open(self.p(name), "rb") as f:
            return f.read()


@unittest.skipUnless(_need_argon2(), "argon2-cffi not installed")
class KeyFileArgon2Tests(_Base):
    def test_create_unwrap_round_trip(self):
        dek, kf = cs.create_keyfile("1234", self.p("key.json"), kdf=FAST_ARGON2)
        with dek:
            with cs.unwrap("1234", self.p("key.json")) as again:
                self.assertTrue(again.matches(dek))
            self.assertEqual(kf["kdf"]["name"], "argon2id")
            self.assertFalse(kf["kdf_fallback"])
            on_disk = json.loads(self.read("key.json"))
            self.assertEqual(on_disk["key_id"], dek.key_id.hex())
            self.assertNotIn(dek._buf.hex(), self.read("key.json").decode("utf-8"))

    def test_wrong_pin(self):
        dek, kf = cs.create_keyfile("1234", kdf=FAST_ARGON2)
        dek.wipe()
        with self.assertRaises(cs.WrongPin):
            cs.unwrap("1235", kf)
        self.assertFalse(cs.verify_pin("", kf))
        self.assertTrue(cs.verify_pin("1234", kf))

    def test_pin_is_unicode_normalised(self):
        dek, kf = cs.create_keyfile("café", kdf=FAST_ARGON2)
        dek.wipe()
        self.assertTrue(cs.verify_pin("café", kf), "NFD input must open an NFC-wrapped key")

    def test_tampered_keyfile_fields_fail(self):
        dek, kf = cs.create_keyfile("1234", kdf=FAST_ARGON2)
        dek.wipe()
        for mutate in (
            lambda k: k["kdf"].__setitem__("t", 2),
            lambda k: k.__setitem__("kdf_fallback", True),
            lambda k: k.__setitem__("key_id", "00" * 8),
            lambda k: k["wrap"].__setitem__("nonce", cs._b64(os.urandom(12))),
            lambda k: k["wrap"].__setitem__("ct", cs._b64(os.urandom(48))),
            lambda k: k["kdf"].__setitem__("salt", cs._b64(os.urandom(16))),
        ):
            bad = json.loads(json.dumps(kf))
            mutate(bad)
            with self.assertRaises(cs.WrongPin):
                cs.unwrap("1234", bad)

    def test_malformed_keyfiles(self):
        dek, kf = cs.create_keyfile("1234", kdf=FAST_ARGON2)
        dek.wipe()
        cases = [
            {},
            dict(kf, v=2),
            dict(kf, format="other"),
            dict(kf, kdf=dict(kf["kdf"], m_kib=1024)),             # below the floor
            dict(kf, kdf=dict(kf["kdf"], m_kib=64 * 1024 * 1024)),  # DoS ceiling
            dict(kf, kdf=dict(kf["kdf"], name="pbkdf2")),
            dict(kf, wrap=dict(kf["wrap"], alg="AES-128-CBC")),
            dict(kf, wrap=dict(kf["wrap"], ct="AAAA")),
        ]
        for bad in cases:
            with self.assertRaises(cs.KeyFileError):
                cs.unwrap("1234", bad)
        with open(self.p("junk.json"), "w") as f:
            f.write("{nope")
        with self.assertRaises(cs.KeyFileError):
            cs.load_keyfile(self.p("junk.json"))
        with self.assertRaises(cs.KeyFileError):
            cs.load_keyfile(self.p("missing.json"))

    def test_pin_change_rewraps_same_dek(self):
        path = self.p("key.json")
        dek, kf = cs.create_keyfile("1234", path, kdf=FAST_ARGON2)
        blob = cs.encrypt_bytes(b"secret notes", dek)
        new = cs.rewrap("1234", "9876", path, kdf=FAST_ARGON2)
        self.assertEqual(new["key_id"], kf["key_id"])
        self.assertNotEqual(new["kdf"]["salt"], kf["kdf"]["salt"])
        self.assertNotEqual(new["wrap"]["nonce"], kf["wrap"]["nonce"])
        self.assertEqual(new["created_at"], kf["created_at"])
        self.assertFalse(cs.verify_pin("1234", path))
        with cs.unwrap("9876", path) as again:
            self.assertEqual(cs.decrypt_bytes(blob, again), b"secret notes", "data needs no re-encryption")
        with self.assertRaises(cs.WrongPin):
            cs.rewrap("1234", "5555", path)
        self.assertTrue(cs.verify_pin("9876", path), "a failed rewrap leaves the file alone")
        self.assertTrue(cs.verify_dek(dek, path))
        dek.wipe()

    def test_parameter_upgrade(self):
        path = self.p("key.json")
        dek, kf = cs.create_keyfile("1234", path, kdf=FAST_ARGON2)
        self.assertTrue(cs.needs_upgrade(path))
        self.assertFalse(cs.needs_upgrade(path, FAST_ARGON2))
        stronger = dict(FAST_ARGON2, m_kib=16384, t=2)
        cs.rewrap("1234", None, path, kdf=stronger)
        loaded = cs.load_keyfile(path)
        self.assertEqual((loaded["kdf"]["m_kib"], loaded["kdf"]["t"]), (16384, 2))
        self.assertFalse(cs.needs_upgrade(path, stronger))
        with cs.unwrap("1234", path) as again:
            self.assertTrue(again.matches(dek))
        dek.wipe()

    def test_scrypt_fallback_flag_and_upgrade_to_argon2(self):
        path = self.p("key.json")
        dek, kf = cs.create_keyfile("1234", path, kdf=FAST_SCRYPT)
        self.assertTrue(kf["kdf_fallback"])
        self.assertTrue(cs.needs_upgrade(path, FAST_ARGON2), "argon2 available -> leave the fallback")
        cs.rewrap("1234", None, path, kdf=FAST_ARGON2)
        loaded = cs.load_keyfile(path)
        self.assertEqual(loaded["kdf"]["name"], "argon2id")
        self.assertFalse(loaded["kdf_fallback"])
        with cs.unwrap("1234", path) as again:
            self.assertTrue(again.matches(dek))
        dek.wipe()

    def test_argon2_missing_uses_scrypt_and_refuses_argon2_files(self):
        dek, kf = cs.create_keyfile("1234", kdf=FAST_ARGON2)
        dek.wipe()
        with mock.patch.object(cs, "_HAS_ARGON2", False):
            self.assertEqual(cs.default_kdf()["name"], "scrypt")
            with self.assertRaises(cs.KeyFileError):
                cs.unwrap("1234", kf)


@unittest.skipUnless(_need_argon2(), "argon2-cffi not installed")
class DefaultParamsTests(_Base):
    def test_defaults_are_the_approved_ones(self):
        self.assertEqual(cs.default_kdf(), {"name": "argon2id", "m_kib": 65536, "t": 3, "p": 4})
        dek, kf = cs.create_keyfile("1234")
        dek.wipe()
        self.assertEqual(len(cs.base64.b64decode(kf["kdf"]["salt"])), 16)
        self.assertTrue(cs.verify_pin("1234", kf))
        self.assertFalse(cs.needs_upgrade(kf))


class ScryptOnlyTests(_Base):
    def test_scrypt_round_trip(self):
        dek, kf = cs.create_keyfile("pin!", kdf=FAST_SCRYPT)
        with dek, cs.unwrap("pin!", kf) as again:
            self.assertTrue(again.matches(dek))
        with self.assertRaises(cs.WrongPin):
            cs.unwrap("pin?", kf)
        with self.assertRaises(cs.KeyFileError):
            cs.validate_kdf(dict(FAST_SCRYPT, n=3 * 2 ** 14, salt=cs._b64(b"x" * 16)))


class DataKeyTests(_Base):
    def test_wipe_zeroes_and_blocks_use(self):
        k = cs.DataKey.generate()
        buf = k._buf
        k.wipe()
        self.assertEqual(bytes(buf), b"\x00" * 32)
        self.assertTrue(k.wiped)
        with self.assertRaises(cs.CryptoStoreError):
            k.sqlcipher_key()
        self.assertEqual(repr(k), "<DataKey wiped>")

    def test_wipe_helper(self):
        b = bytearray(b"abc")
        cs.wipe(b)
        self.assertEqual(b, bytearray(3))
        cs.wipe(b"immutable")  # ignored, not an error
        cs.wipe(None)

    def test_purpose_keys_differ_from_dek(self):
        sk = self.key.sqlcipher_key()
        self.assertEqual(len(sk), 32)
        self.assertNotEqual(bytes(sk), bytes(self.key._buf))
        self.assertEqual(self.key.sqlcipher_hex(), sk.hex())
        self.assertNotIn(self.key._buf.hex(), repr(self.key))

    def test_not_picklable(self):
        import pickle
        with self.assertRaises(TypeError):
            pickle.dumps(self.key)


class StreamTests(_Base):
    CS = cs.MIN_CHUNK if cs else 4096

    def enc(self, data, chunk=None):
        return cs.encrypt_bytes(data, self.key, chunk or self.CS)

    def test_round_trips_all_sizes(self):
        for n in (0, 1, self.CS - 1, self.CS, self.CS + 1, 3 * self.CS, 3 * self.CS + 7):
            data = os.urandom(n)
            blob = self.enc(data)
            self.assertTrue(cs.is_encrypted_blob(blob))
            self.assertEqual(cs.decrypt_bytes(blob, self.key), data, n)
            chunks = max(1, -(-n // self.CS))
            self.assertEqual(len(blob), cs.HEADER_LEN + n + chunks * cs.TAG_LEN)

    def test_same_plaintext_encrypts_differently(self):
        self.assertNotEqual(self.enc(b"x" * 100), self.enc(b"x" * 100))

    def test_wrong_key(self):
        blob = self.enc(b"hello")
        with cs.DataKey.generate() as other, self.assertRaises(cs.WrongKey):
            cs.decrypt_bytes(blob, other)

    def test_header_tamper(self):
        blob = bytearray(self.enc(os.urandom(2 * self.CS + 5)))
        for off in range(8, cs.HEADER_LEN):  # every non-magic header byte
            bad = bytearray(blob)
            bad[off] ^= 0x01
            with self.assertRaises(cs.CryptoStoreError, msg="header byte %d" % off):
                cs.decrypt_bytes(bad, self.key)
        bad = bytearray(blob)
        bad[0] ^= 1
        with self.assertRaises(cs.FormatError):
            cs.decrypt_bytes(bad, self.key)

    def test_chunk_tamper(self):
        blob = bytearray(self.enc(os.urandom(2 * self.CS + 5)))
        for off in (cs.HEADER_LEN, cs.HEADER_LEN + self.CS + 3, len(blob) - 1):
            bad = bytearray(blob)
            bad[off] ^= 0x80
            with self.assertRaises(cs.TamperError):
                cs.decrypt_bytes(bad, self.key)

    def test_truncation(self):
        block = self.CS + cs.TAG_LEN
        blob = self.enc(os.urandom(3 * self.CS))  # exactly three full chunks
        for cut in (cs.HEADER_LEN, cs.HEADER_LEN + block, cs.HEADER_LEN + 2 * block, len(blob) - 1, cs.HEADER_LEN + 5):
            with self.assertRaises(cs.TamperError, msg="cut at %d" % cut):
                cs.decrypt_bytes(blob[:cut], self.key)
        with self.assertRaises(cs.FormatError):
            cs.decrypt_bytes(blob[:20], self.key)

    def test_reorder_duplicate_and_append(self):
        block = self.CS + cs.TAG_LEN
        blob = self.enc(os.urandom(3 * self.CS + 9))
        h = blob[:cs.HEADER_LEN]
        c = [blob[cs.HEADER_LEN + i * block:cs.HEADER_LEN + (i + 1) * block] for i in range(4)]
        for bad in (h + c[1] + c[0] + c[2] + c[3], h + c[0] + c[0] + c[2] + c[3], h + c[0] + c[1] + c[3],
                    blob + b"\x00" * 20, blob + c[3]):
            with self.assertRaises(cs.TamperError):
                cs.decrypt_bytes(bad, self.key)

    def test_header_swap_between_files(self):
        a = self.enc(b"a" * 10)
        b = self.enc(b"b" * 10)
        with self.assertRaises(cs.TamperError):
            cs.decrypt_bytes(a[:cs.HEADER_LEN] + b[cs.HEADER_LEN:], self.key)

    def test_partial_generator_output_is_authentic_but_raises(self):
        blob = bytearray(self.enc(os.urandom(2 * self.CS + 1)))
        blob[-1] ^= 1
        got = []
        with self.assertRaises(cs.TamperError):
            for chunk in cs.decrypt_stream(io.BytesIO(bytes(blob)), self.key):
                got.append(chunk)
        self.assertEqual(len(got), 2)

    def test_chunk_size_bounds(self):
        with self.assertRaises(ValueError):
            cs.encrypt_bytes(b"x", self.key, 100)


class FileTests(_Base):
    def test_file_round_trip_and_in_place(self):
        data = os.urandom(200 * 1024 + 3)
        with open(self.p("a.bin"), "wb") as f:
            f.write(data)
        cs.encrypt_file(self.p("a.bin"), self.p("a.enc"), self.key)
        self.assertTrue(cs.is_encrypted_file(self.p("a.enc")))
        self.assertFalse(cs.is_encrypted_file(self.p("a.bin")))
        self.assertFalse(cs.is_encrypted_file(self.p("nope")))
        cs.decrypt_file(self.p("a.enc"), self.p("a.out"), self.key)
        self.assertEqual(self.read("a.out"), data)
        cs.encrypt_file(self.p("a.bin"), self.p("a.bin"), self.key)  # in place
        self.assertTrue(cs.is_encrypted_file(self.p("a.bin")))
        self.assertEqual(sorted(os.listdir(self.dir)), ["a.bin", "a.enc", "a.out"], "no temp files left")

    def test_failed_decrypt_leaves_destination_and_no_plaintext(self):
        with open(self.p("a.bin"), "wb") as f:
            f.write(os.urandom(100 * 1024))
        cs.encrypt_file(self.p("a.bin"), self.p("a.enc"), self.key)
        raw = bytearray(self.read("a.enc"))
        raw[-1] ^= 1
        with open(self.p("a.enc"), "wb") as f:
            f.write(raw)
        with open(self.p("out"), "wb") as f:
            f.write(b"previous")
        with self.assertRaises(cs.TamperError):
            cs.decrypt_file(self.p("a.enc"), self.p("out"), self.key)
        self.assertEqual(self.read("out"), b"previous")
        self.assertEqual(sorted(os.listdir(self.dir)), ["a.bin", "a.enc", "out"])

    def test_atomic_write_failure_keeps_original(self):
        with open(self.p("t.json"), "wb") as f:
            f.write(b"old")
        with self.assertRaises(RuntimeError):
            with cs.atomic_write(self.p("t.json")) as f:
                f.write(b"half-written")
                raise RuntimeError("crash mid-write")
        self.assertEqual(self.read("t.json"), b"old")
        with mock.patch.object(cs.os, "replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                cs.write_json(self.p("t.json"), {"a": 1}, self.key)
        self.assertEqual(self.read("t.json"), b"old")
        self.assertEqual(os.listdir(self.dir), ["t.json"])

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_atomic_write_is_private(self):
        cs.write_json(self.p("s.json"), {"x": 1}, self.key)
        self.assertEqual(os.stat(self.p("s.json")).st_mode & 0o777, 0o600)


class JsonTests(_Base):
    def test_json_round_trip(self):
        obj = {"targets": [{"ip": "10.0.0.1", "password": "Winter2026!"}], "uni": "é中"}
        blob = cs.encrypt_json(obj, self.key)
        self.assertNotIn(b"Winter2026", blob)
        self.assertEqual(cs.decrypt_json(blob, self.key), obj)
        cs.write_json(self.p("t.json"), obj, self.key)
        self.assertEqual(cs.read_json(self.p("t.json"), self.key), obj)
        self.assertNotIn(b"Winter2026", self.read("t.json"))

    def test_read_json_default_only_for_missing(self):
        self.assertEqual(cs.read_json(self.p("missing"), self.key, default={}), {})
        with self.assertRaises(FileNotFoundError):
            cs.read_json(self.p("missing"), self.key)
        with open(self.p("plain.json"), "w") as f:
            f.write("{}")
        with self.assertRaises(cs.FormatError):
            cs.read_json(self.p("plain.json"), self.key, default={})


if __name__ == "__main__":
    unittest.main()
