"""Export my work from one isolated install, import it into a fresh one: every content item arrives, no secret does."""
import json,os,shutil,sys,tempfile,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db,doc_store
from Cores.Services import notes_service as ns,work_export as we,work_import as wi
from test_work_export import seed,SECRETS,CONTENT,FAST_KDF
from test_chain_history import GRAPH
class _Install:
    def __init__(self):
        self.iso=IsolatedData();self.dir=self.iso.start();common_db.set_locked(False)
        self._abs=ns._abs;d=self.dir
        ns._abs=lambda *p:os.path.join(d,*(p[1:] if p and p[0]=="Data" else p))
    def stop(self):
        ns._abs=self._abs;self.iso.stop()
def _tree_bytes(d):
    out=b""
    for b,_,names in os.walk(d):
        for n in names:
            with open(os.path.join(b,n),"rb") as f:out+=f.read()+b"\n"
    return out
class WorkRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.out=tempfile.mkdtemp(prefix="loya_rt_out_")
        self._kdf=we._KDF;we._KDF=FAST_KDF
    def tearDown(self):
        we._KDF=self._kdf;shutil.rmtree(self.out,ignore_errors=True)
    def _export(self,**kw):
        a=_Install()
        try:
            seed(a.dir)
            # A diagram the chain import accepts (the export seed's graph is minimal), with a marked node title.
            g=json.loads(json.dumps(GRAPH));g["nodes"][-1]["title"]="MARK-CHAIN-GRAPH"
            with open(os.path.join(a.dir,"QuicSpace.json"),"w",encoding="utf-8") as f:json.dump({"html":"<p>MARK-QUICKSPACE</p>","text":"MARK-QUICKSPACE","wrap":True},f)
            # Notes refer to their attachments by file:// URL of this install's Data/Attachments/<note id>/ (machine specific).
            url=ns._file_url(os.path.join(a.dir,"Attachments","7","a.png"))
            with common_db.connection() as con:
                con.execute("UPDATE ChainGraphs SET graph=? WHERE playbook_id=1",(json.dumps(g),))
                con.execute("UPDATE Notes SET content=? WHERE id=7",(f'<p>MARK-NOTE-BODY</p><img src="{url}">',))
            ext=".loyawork" if kw.get("password") else ".zip"
            res=we.export_work_zip(os.path.join(self.out,"work"+ext),**kw)
        finally:a.stop()
        return res
    def _import_fresh(self,path,**kw):
        b=_Install()
        try:
            pv=wi.preview(path,password=kw.get("password"))
            res=wi.apply(path,mode="merge",**kw)
            blob=_tree_bytes(b.dir)
            with common_db.connection() as con:
                chains=con.execute("SELECT ai_reviewed FROM ChainGraphs").fetchall()
                notes=con.execute("SELECT id,content FROM Notes").fetchall()
            sp=os.path.join(b.dir,"settings.json");settings={}
            if os.path.isfile(sp):
                with open(sp,encoding="utf-8") as f:settings=json.load(f)
            att=os.listdir(os.path.join(b.dir,"Attachments"))
        finally:b.stop()
        return pv,res,blob,chains,notes,settings,att
    def _check(self,pv,res,blob,chains,notes,att):
        for m in CONTENT:self.assertTrue(m.encode() in blob,m)
        for m in SECRETS:self.assertFalse(m.encode() in blob,m)
        self.assertTrue(chains and all(r[0]==0 for r in chains),"imported chains are unreviewed")
        self.assertEqual(1,len(notes))
        nid=str(notes[0][0]);self.assertIn(nid,att);self.assertIn(f"Attachments/{nid}/a.png",notes[0][1].replace("\\","/"))
        for k in ("notes","commands","chains","reports","targets","attachments","chain_files"):self.assertTrue(pv["counts"].get(k),k)
    def test_plain_round_trip_brings_every_content_item(self):
        res=self._export(include_settings=True)
        pv,r,blob,chains,notes,settings,att=self._import_fresh(res["path"])
        self._check(pv,r,blob,chains,notes,att)
        self.assertNotIn("appearance",settings,"settings only with apply_settings")
    def test_password_round_trip_and_apply_settings(self):
        res=self._export(include_settings=True,password="correct horse battery")
        self.assertTrue(res["protected"])
        with open(res["path"],"rb") as f:raw=f.read()
        for m in CONTENT+SECRETS:self.assertFalse(m.encode() in raw,m)
        with self.assertRaises(wi.PasswordRequired):self._import_fresh(res["path"])
        with self.assertRaises(wi.WrongPassword):self._import_fresh(res["path"],password="wrong password!")
        pv,r,blob,chains,notes,settings,att=self._import_fresh(res["path"],password="correct horse battery",apply_settings=True)
        self._check(pv,r,blob,chains,notes,att)
        self.assertEqual("dark",settings["appearance"]["theme"])
        self.assertNotIn("security",settings)
if __name__=="__main__":unittest.main()
