"""The vendored xterm.js bundles in UI/vendor/xterm: every file is present, matches the SHA-256 recorded in VENDOR.md,
is listed there, carries its MIT license, and nothing pulls scripts from a CDN at runtime."""
import hashlib,os,re,unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR=os.path.join(ROOT,"UI","vendor","xterm")
VENDOR_MD=os.path.join(VENDOR_DIR,"VENDOR.md")
PACKAGES=("@xterm/xterm","@xterm/addon-fit","@xterm/addon-web-links","@xterm/addon-search","@xterm/addon-unicode11")
JS_FILES=("xterm.js","addon-fit.js","addon-web-links.js","addon-search.js","addon-unicode11.js")
LICENSE_FILES=("LICENSE-xterm.txt","LICENSE-addon-fit.txt","LICENSE-addon-web-links.txt","LICENSE-addon-search.txt","LICENSE-addon-unicode11.txt")
EXPECTED=JS_FILES+("xterm.css",)+LICENSE_FILES
UMD_GLOBALS={"xterm.js":"Terminal","addon-fit.js":"FitAddon","addon-web-links.js":"WebLinksAddon","addon-search.js":"SearchAddon","addon-unicode11.js":"Unicode11Addon"}
HASH_ROW=re.compile(r"^\|\s*([A-Za-z0-9._-]+)\s*\|\s*([0-9a-f]{64})\s*\|\s*$")
def _sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(65536),b""):h.update(chunk)
    return h.hexdigest()
def _vendor_text():
    with open(VENDOR_MD,encoding="utf-8") as f:return f.read()
def _hash_table():
    rows={}
    for line in _vendor_text().splitlines():
        m=HASH_ROW.match(line.strip())
        if m:rows[m.group(1)]=m.group(2)
    return rows
class XtermVendorTests(unittest.TestCase):
    def test_expected_files_exist(self):
        for name in EXPECTED+("VENDOR.md",):
            self.assertTrue(os.path.isfile(os.path.join(VENDOR_DIR,name)),name)
    def test_no_source_maps_or_extra_builds(self):
        for name in os.listdir(VENDOR_DIR):
            self.assertFalse(name.endswith((".map",".mjs",".ts")),name)
    def test_listed_files_exist_and_hashes_match(self):
        rows=_hash_table()
        self.assertTrue(rows,"no File | SHA-256 rows found in VENDOR.md")
        for name,digest in rows.items():
            path=os.path.join(VENDOR_DIR,name)
            self.assertTrue(os.path.isfile(path),f"{name} listed in VENDOR.md but missing")
            self.assertEqual(_sha256(path),digest,f"{name} does not match its recorded SHA-256")
    def test_every_vendored_file_is_listed(self):
        rows=_hash_table()
        for name in os.listdir(VENDOR_DIR):
            if name=="VENDOR.md":continue
            self.assertIn(name,rows,f"{name} is vendored but has no SHA-256 row in VENDOR.md")
        for name in EXPECTED:self.assertIn(name,rows,name)
    def test_licenses_are_mit(self):
        for name in LICENSE_FILES:
            with open(os.path.join(VENDOR_DIR,name),encoding="utf-8") as f:text=f.read()
            self.assertIn("MIT",text,name)
            self.assertIn("xterm.js authors",text,name)
    def test_packages_recorded_with_version_and_integrity(self):
        text=_vendor_text()
        for pkg in PACKAGES:
            row=[l for l in text.splitlines() if l.strip().startswith(f"| {pkg} |")]
            self.assertEqual(len(row),1,f"expected one package row for {pkg}")
            cells=[c.strip() for c in row[0].strip().strip("|").split("|")]
            self.assertRegex(cells[1],r"^\d+\.\d+\.\d+$",pkg)
            self.assertTrue(cells[2].startswith("https://registry.npmjs.org/"),pkg)
            self.assertIn(cells[1],cells[2],pkg)
            self.assertRegex(cells[3],r"^sha512-[A-Za-z0-9+/]{86}==$",pkg)
    def test_js_files_are_umd_bundles(self):
        for name,glob in UMD_GLOBALS.items():
            with open(os.path.join(VENDOR_DIR,name),encoding="utf-8") as f:head=f.read(600)
            self.assertIn('"function"==typeof define&&define.amd',head,name)
            if name=="xterm.js":self.assertIn("for(var s in i)",head,name)
            else:self.assertIn(f"e.{glob}=t()",head,name)
    def test_js_does_not_load_remote_scripts(self):
        remote=re.compile(r"""(<script[^>]*src\s*=\s*["']?https?://|importScripts\(\s*["'`]https?://|import\(\s*["'`]https?://)""",re.I)
        for name in JS_FILES:
            with open(os.path.join(VENDOR_DIR,name),encoding="utf-8") as f:src=f.read()
            self.assertIsNone(remote.search(src),f"{name} loads a script from a remote URL")
if __name__=="__main__":
    unittest.main()
