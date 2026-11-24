"""Chain Run History (Cores/Services/chain_history.py): listing with filters, run detail, delete, and the versioned
chain/run bundle export and import (validation, review flags, collisions, sub-chain links, history-only imported runs)."""
import json,os,sys,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import chain_history as hist
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import flow_engine as engine
from Cores.Services import playbooks_service as chains
GRAPH={"schema":1,"settings":{},"nodes":[{"id":"n1","type":"start","title":"Start","x":0,"y":0,"config":{}},
       {"id":"n2","type":"command","title":"Ping it","x":200,"y":0,"config":{"commands":[{"text":"ping -c 1 {IPv4}"}]}},
       {"id":"n3","type":"end","title":"End","x":400,"y":0,"config":{}}],
       "edges":[{"id":"e1","from":"n1","port":"out","to":"n2"},{"id":"e2","from":"n2","port":"success","to":"n3"}]}
SCRIPT_GRAPH={"schema":1,"settings":{"script_isolation":"allow"},"nodes":[{"id":"n1","type":"start","title":"Start","x":0,"y":0,"config":{}},
       {"id":"s1","type":"script","title":"Decide","x":200,"y":0,"config":{"language":"python","code":"print('{\"branch\":\"ok\"}')","branches":["ok"]}}],
       "edges":[{"id":"e1","from":"n1","port":"out","to":"s1"}]}
def status(run_id,playbook_id,name="Recon",state="done",started="2026-11-20T10:00:00+00:00",ended="2026-11-20T10:00:05+00:00",source="manual",mode="run",target="web01"):
    return {"run_id":run_id,"playbook_id":playbook_id,"name":name,"mode":mode,"state":state,"reason":"","source":source,"target":target,"started_at":started,"ended_at":ended,
            "nodes":{"n1":{"state":"success","started_at":started,"ended_at":started,"duration_ms":1,"output":{}},
                     "n2":{"state":"fail" if state=="failed" else "success","visits":1,"started_at":started,"ended_at":ended,"duration_ms":5000,"error":"exit 1" if state=="failed" else "","output":{"exit_code":1 if state=="failed" else 0,"stdout":"64 bytes from 10.0.0.5","stderr":"","resolved":["ping -c 1 10.0.0.5"]}},
                     "n3":{"state":"pending"}},
            "edges_taken":["e1"],"events":[],"vars":{"secret":"x"},"seq":3}
def add_log(run_id):
    store.append_run_log(run_id,[{"seq":1,"ts":"2026-11-20T10:00:00+00:00","node":None,"level":"info","kind":"run_start","text":"Run started"},
                                 {"seq":2,"ts":"2026-11-20T10:00:01+00:00","node":"n2","title":"Ping it","level":"warn","kind":"stderr","text":"slow answer"},
                                 {"seq":3,"ts":"2026-11-20T10:00:05+00:00","node":"n2","title":"Ping it","level":"error","kind":"node_end","text":"Exit code 1"}])
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.a=flows.create("Recon",GRAPH,"recon")["playbook_id"]
        self.b=flows.create("Web sweep",GRAPH,"web")["playbook_id"]
        store.save_run(status("runA1",self.a,started="2026-11-20T10:00:00+00:00",ended="2026-11-20T10:00:05+00:00"));add_log("runA1")
        store.save_run(status("runA2",self.a,state="failed",started="2026-11-21T09:00:00+00:00",ended="2026-11-21T09:01:00+00:00",source="caller"))
        store.save_run(status("runB1",self.b,name="Web sweep",started="2026-11-22T08:00:00+00:00",ended="2026-11-22T08:00:02+00:00",source="ai",target="db01"))
    def tearDown(self):
        common_db.set_locked(False)
        self.iso.stop()
class ListTest(Base):
    def test_lists_every_run_newest_first_with_counts_duration_trigger_and_target(self):
        page=hist.list_runs({})
        self.assertEqual(["runB1","runA2","runA1"],[r["run_id"] for r in page["items"]])
        self.assertEqual(3,page["total"])
        a1=page["items"][2]
        self.assertEqual(("Recon","done","manual","web01",5000),(a1["chain_name"],a1["state"],a1["source"],a1["target"],a1["duration_ms"]))
        self.assertEqual({"total":3,"success":2,"pending":1},{k:v for k,v in a1["nodes"].items() if v})
        self.assertTrue(a1["chain_exists"])
        self.assertEqual(1,page["items"][1]["nodes"]["fail"])
    def test_filters_by_chain_status_date_trigger_and_words(self):
        self.assertEqual(["runA2","runA1"],[r["run_id"] for r in hist.list_runs({"playbook_id":self.a})["items"]])
        self.assertEqual(["runA2"],[r["run_id"] for r in hist.list_runs({"state":"failed"})["items"]])
        self.assertEqual(["runB1","runA2"],[r["run_id"] for r in hist.list_runs({"date_from":"2026-11-21T00:00:00Z"})["items"]])
        self.assertEqual(["runA1"],[r["run_id"] for r in hist.list_runs({"date_to":"2026-11-20T23:59:59Z"})["items"]])
        self.assertEqual(["runB1"],[r["run_id"] for r in hist.list_runs({"source":"ai"})["items"]])
        self.assertEqual(["runB1"],[r["run_id"] for r in hist.list_runs({"query":"db01"})["items"]])
        self.assertEqual(["runA2","runA1"],[r["run_id"] for r in hist.list_runs({"query":"recon"})["items"]])
        self.assertEqual([],hist.list_runs({"query":"100%_"})["items"])   # LIKE wildcards are literal
    def test_paging(self):
        page=hist.list_runs({"limit":2,"offset":2})
        self.assertEqual((["runA1"],3),([r["run_id"] for r in page["items"]],page["total"]))
    def test_facets(self):
        f=hist.facets()
        self.assertEqual(3,f["total"])
        self.assertEqual({"Recon":2,"Web sweep":1},{c["name"]:c["count"] for c in f["chains"]})
        self.assertEqual({"done":2,"failed":1},f["states"])
        self.assertEqual({"Recon","Web sweep"},{c["name"] for c in f["all_chains"]})
    def test_refused_while_locked(self):
        common_db.set_locked(True)
        with self.assertRaises(ValueError):hist.list_runs({})
        with self.assertRaises(ValueError):hist.delete_runs(["runA1"])
        with self.assertRaises(ValueError):hist.export_bundle()
class DetailTest(Base):
    def test_detail_has_per_node_results_in_run_order_with_titles(self):
        d=hist.run_detail("runA2")
        self.assertEqual(("failed",60000,"caller"),(d["state"],d["duration_ms"],d["source"]))
        self.assertEqual(["n1","n2","n3"],[n["node"] for n in d["timeline"]])
        n2=d["timeline"][1]
        self.assertEqual(("Ping it","command","fail",1,"exit 1"),(n2["title"],n2["type"],n2["state"],n2["exit_code"],n2["error"]))
        self.assertEqual("",d["timeline"][2]["started_at"])
    def test_detail_of_a_deleted_chain_uses_the_log_titles(self):
        flows.chain_deleted(self.a);chains.delete_playbook(self.a)
        d=hist.run_detail("runA1")
        self.assertFalse(d["chain_exists"])
        self.assertEqual("Ping it",d["titles"].get("n2"))
        self.assertFalse(hist.list_runs({"playbook_id":self.a})["items"][0]["chain_exists"])
class DeleteTest(Base):
    def test_delete_one_and_many_with_logs(self):
        self.assertEqual(1,hist.delete_runs("runA1")["deleted"])
        self.assertEqual(([],0),store.get_run_log("runA1"))
        out=hist.delete_runs(["runA2","runB1","nope"])
        self.assertEqual((2,1),(out["deleted"],out["missing"]))
        self.assertEqual(0,hist.list_runs({})["total"])
    def test_clear_one_chain_or_all(self):
        self.assertEqual(2,hist.clear_runs(self.a)["deleted"])
        self.assertEqual(["runB1"],[r["run_id"] for r in hist.list_runs({})["items"]])
        self.assertEqual(1,hist.clear_runs()["deleted"])
        self.assertEqual(0,hist.list_runs({})["total"])
    def test_clear_an_orphaned_chain_by_name(self):
        store.save_run(dict(status("runX",None,name="Gone chain"),playbook_id=None))
        self.assertEqual(1,hist.clear_runs(None,"gone chain")["deleted"])
        self.assertEqual(3,hist.list_runs({})["total"])
    def test_running_runs_are_never_deleted(self):
        class Live:
            def active(self):return True
        real=(engine.active_runs,engine.get_run)
        engine.active_runs=lambda:[{"run_id":"runA1","playbook_id":self.a,"name":"Recon","mode":"run","state":"running","source":"manual","target":"","started_at":"2026-11-24T00:00:00+00:00","ended_at":"","current":None}]
        engine.get_run=lambda rid:None
        try:
            out=hist.delete_runs(["runA1","runA2"])
            self.assertEqual((1,["runA1"]),(out["deleted"],out["skipped"]))
            self.assertEqual(1,hist.clear_runs()["deleted"])   # runB1; runA1 is still going
            self.assertIsNotNone(store.get_run("runA1"))
            page=hist.list_runs({})
            self.assertTrue(page["items"][0]["live"])
        finally:
            engine.active_runs,engine.get_run=real
class ExportImportTest(Base):
    def test_bundle_is_versioned_and_round_trips_chains_and_runs(self):
        bundle=hist.export_bundle("all",None,include_chains=True,include_runs=True)
        self.assertEqual(("loya-chain-bundle",1,["chains","runs"]),(bundle["format"],bundle["version"],bundle["contents"]))
        self.assertEqual({"Recon","Web sweep"},{c["name"] for c in bundle["chains"]})
        a1=next(r for r in bundle["runs"] if r["run_id"]=="runA1")
        self.assertEqual(3,len(a1["log"]));self.assertEqual("Ping it",a1["node_titles"]["n2"])
        text=hist.bundle_text(bundle)
        # Into a fresh install.
        self.iso.stop();self.iso=IsolatedData();self.iso.start()
        pre=hist.preview(text)
        self.assertEqual((2,3,0,0),(len(pre["chains"]),len(pre["runs"]),pre["chain_conflicts"],pre["run_conflicts"]))
        out=hist.import_bundle(text)
        self.assertEqual(2,len(out["chains"]["created"]));self.assertEqual(3,out["runs"]["imported"])
        by_name={c["name"]:c["playbook_id"] for c in out["chains"]["created"]}
        for pid in by_name.values():
            got=flows.get(pid)
            self.assertFalse(got["ai_reviewed"],"an imported chain must be reviewed before it runs")
        page=hist.list_runs({"playbook_id":by_name["Recon"]})
        self.assertEqual(["runA2","runA1"],[r["run_id"] for r in page["items"]])
        self.assertTrue(all(r["imported"] for r in page["items"]))
        self.assertEqual("run",page["items"][0]["mode"])
        log=flows.run_log("runA1")
        self.assertEqual(["info","warn","error"],[e["level"] for e in log["entries"]])
        self.assertEqual("Ping it",log["entries"][1]["title"])
        d=hist.run_detail("runA1")
        self.assertEqual("Ping it",d["timeline"][1]["title"])
        self.assertEqual({},store.get_run("runA1")["vars"],"variables never come in with an imported run")
    def test_imported_runs_never_seed_a_rerun(self):
        text=hist.bundle_text(hist.export_bundle([self.a],None,include_chains=True,include_runs=True,runs_of_chain=self.a))
        hist.clear_runs()
        out=hist.import_bundle(text,{"chains":"skip"})
        self.assertEqual(self.a,out["chains"]["skipped"][0]["playbook_id"])
        self.assertEqual(2,out["runs"]["imported"])
        self.assertTrue(all(r["mode"]==hist.IMPORTED_MODE for r in store.list_runs(self.a)))
        self.assertIsNone(flows._last_status(self.a))
    def test_chain_name_collisions_rename_skip_replace(self):
        text=hist.bundle_text(hist.export_bundle([self.a]))
        self.assertEqual(1,hist.preview(text)["chain_conflicts"])
        renamed=hist.import_bundle(text,{"chains":"rename"})["chains"]["created"][0]
        self.assertEqual("Recon (imported)",renamed["name"])
        self.assertEqual("Recon (imported 2)",hist.import_bundle(text)["chains"]["created"][0]["name"])
        before=len(chains.list_playbooks())
        self.assertEqual(1,len(hist.import_bundle(text,{"chains":"skip"})["chains"]["skipped"]))
        self.assertEqual(before,len(chains.list_playbooks()))
        flows.mark_reviewed(self.a)
        replaced=hist.import_bundle(text,{"chains":"replace"})["chains"]["replaced"][0]
        self.assertEqual(self.a,replaced["playbook_id"])
        self.assertFalse(flows.get(self.a)["ai_reviewed"],"a replaced diagram needs a review again")
        self.assertEqual(before,len(chains.list_playbooks()))
    def test_run_id_collisions_skip_replace_rename(self):
        text=hist.bundle_text(hist.export_bundle(None,["runA1"],include_chains=False,include_runs=True))
        self.assertEqual(1,hist.preview(text)["run_conflicts"])
        self.assertEqual(1,hist.import_bundle(text)["runs"]["skipped"])
        self.assertEqual(1,hist.import_bundle(text,{"runs":"replace"})["runs"]["replaced"])
        self.assertEqual(hist.IMPORTED_MODE,store.list_runs(self.a,50)[0]["mode"])
        out=hist.import_bundle(text,{"runs":"rename"})
        self.assertEqual(1,out["runs"]["renamed"])
        self.assertIsNotNone(store.get_run("runA1-imp1"))
    def test_scripts_are_flagged_and_cannot_loosen_isolation(self):
        bundle={"format":"loya-chain-bundle","version":1,"chains":[{"ref":"c9","source_id":9,"name":"Scripted","origin":{"ai_made":True},"graph":SCRIPT_GRAPH}],"runs":[]}
        pre=hist.preview(json.dumps(bundle))
        self.assertEqual(1,pre["scripts"])
        out=hist.import_bundle(json.dumps(bundle))
        pid=out["chains"]["created"][0]["playbook_id"]
        got=flows.get(pid)
        self.assertTrue(got["ai_made"]);self.assertFalse(got["ai_reviewed"])
        self.assertEqual("inherit",got["graph"]["settings"].get("script_isolation","inherit"))
        codes={w["code"] for w in out["warnings"]}
        self.assertIn("imported_scripts",codes);self.assertIn("script_isolation_reset",codes)
    def test_subchain_links_follow_only_chains_in_the_same_bundle(self):
        parent=dict(GRAPH,nodes=GRAPH["nodes"][:2]+[{"id":"sc","type":"subchain","title":"Child","x":400,"y":0,"config":{"playbook_id":77}}],
                    edges=[GRAPH["edges"][0],{"id":"e2","from":"n2","port":"success","to":"sc"}])
        bundle={"format":"loya-chain-bundle","version":1,"chains":[{"ref":"c77","source_id":77,"name":"Child","graph":GRAPH},{"ref":"c78","source_id":78,"name":"Parent","graph":parent}],"runs":[]}
        out=hist.import_bundle(json.dumps(bundle))
        ids={c["name"]:c["playbook_id"] for c in out["chains"]["created"]}
        sub=next(n for n in flows.get(ids["Parent"])["graph"]["nodes"] if n["type"]=="subchain")
        self.assertEqual(ids["Child"],sub["config"]["playbook_id"])
        alone={"format":"loya-chain-bundle","version":1,"chains":[{"ref":"c78","source_id":78,"name":"Parent","graph":parent}]}
        out=hist.import_bundle(json.dumps(alone))
        sub=next(n for n in flows.get(out["chains"]["created"][0]["playbook_id"])["graph"]["nodes"] if n["type"]=="subchain")
        self.assertIsNone(sub["config"]["playbook_id"])
        self.assertIn("subchain_cleared",{w["code"] for w in out["warnings"]})
    def test_bad_files_are_refused_with_readable_errors(self):
        for raw,needle in ((b"\xff\xfe",'UTF-8'),("{nope","valid JSON"),("[]","not a chain bundle"),('{"a":1}',"format"),
                           ('{"format":"loya-chain-bundle","version":99}',"newer version"),('{"format":"loya-chain-bundle","version":"1"}',"valid version"),
                           ('{"format":"loya-chain-bundle","version":1,"chains":{}}',"must be lists")):
            with self.assertRaises(hist.BundleError) as ctx:hist.import_bundle(raw)
            self.assertIn(needle,str(ctx.exception))
        bad={"format":"loya-chain-bundle","version":1,"chains":[{"name":"Broken","graph":{"nodes":"x"}},"junk"],"runs":[{"run_id":"bad id!"},{"run_id":"ok1","started_at":"never"}]}
        out=hist.import_bundle(json.dumps(bad))
        self.assertEqual(([],0),(out["chains"]["created"],out["runs"]["imported"]))
        self.assertEqual(4,len(out["problems"]))
    def test_unfinished_imported_runs_become_cancelled_and_logs_are_clamped(self):
        bundle={"format":"loya-chain-bundle","version":1,"runs":[{"run_id":"r1","chain_name":"Recon","state":"running","started_at":"2026-11-23T00:00:00Z",
                 "status":{"nodes":{"n2":{"state":"success","output":{"exit_code":True,"stdout":"x"*100000}}}},"log":[{"seq":1,"level":"FATAL","text":"boom"},{"seq":2,"level":"warning","text":"hm"}]}]}
        out=hist.import_bundle(json.dumps(bundle))
        self.assertEqual(1,out["runs"]["imported"])
        row=hist.list_runs({"query":"r1"})["items"][0]
        self.assertEqual(("cancelled",self.a),(row["state"],row["playbook_id"]),"attached to the same-named chain")
        stored=store.get_run("r1")
        self.assertIsNone(stored["nodes"]["n2"]["output"]["exit_code"])
        self.assertLessEqual(len(stored["nodes"]["n2"]["output"]["stdout"]),65536)
        self.assertEqual(["info","warn"],[e["level"] for e in flows.run_log("r1")["entries"]])
    def test_legacy_single_chain_export_is_accepted(self):
        text=flows.export_json(self.b)
        out=hist.import_bundle(text)
        self.assertEqual("Web sweep (imported)",out["chains"]["created"][0]["name"])
    def test_history_stays_bounded_after_an_import(self):
        keep=store.RUNS_KEEP
        store.RUNS_KEEP=4
        try:
            runs=[{"run_id":"old%d"%i,"chain_name":"Recon","state":"done","started_at":"2020-01-0%dT00:00:00Z"%(i+1)} for i in range(3)]
            out=hist.import_bundle(json.dumps({"format":"loya-chain-bundle","version":1,"runs":runs}))
            self.assertEqual(2,out["runs"]["evicted"])
            self.assertEqual(["runB1","runA2","runA1","old2"],[r["run_id"] for r in hist.list_runs({})["items"]])
        finally:
            store.RUNS_KEEP=keep
    def test_file_name(self):
        self.assertEqual("Recon.loya-chains.json",hist.export_file_name(hist.export_bundle([self.a])))
        self.assertTrue(hist.export_file_name(hist.export_bundle(None,None,False,True)).startswith("chain-runs-"))
class BridgeTest(Base):
    def test_preview_then_apply_with_a_token_and_lock_guard(self):
        from Cores.Bridge.chain_history_api import ChainHistoryAPI
        from Cores.Bridge import api
        self.assertNotIn("chainHistory",api._LOCK_OPEN)
        bridge=ChainHistoryAPI()
        text=hist.bundle_text(hist.export_bundle([self.b]))
        pre=bridge.import_preview_text(text)
        self.assertEqual((True,1),(pre["ok"],pre["chain_conflicts"]))
        out=bridge.import_apply(pre["token"],{"chains":"rename"})
        self.assertEqual("Web sweep (imported)",out["chains"]["created"][0]["name"])
        with self.assertRaises(ValueError):bridge.import_apply(pre["token"],{})   # a token is used once
        tokens=[bridge.import_preview_text(text)["token"] for _ in range(5)]
        self.assertFalse(bridge.import_cancel(tokens[0]),"only the newest few previews are kept")
        self.assertTrue(bridge.import_cancel(tokens[-1]))
        with self.assertRaises(ValueError):bridge.export_file({})
        guarded=type("Holder",(),{})();guarded.chainHistory=ChainHistoryAPI()
        api._guard_while_locked(guarded)
        common_db.set_locked(True)
        with self.assertRaises(Exception):guarded.chainHistory.list({})
if __name__=="__main__":
    unittest.main()
