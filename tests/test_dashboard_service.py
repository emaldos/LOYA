import json,os,sqlite3,time,unittest
from datetime import datetime,timezone,timedelta
from unittest import mock
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import dashboard_service as dash
from Cores.Services import search_service,notes_service
def _iso(days_ago=0,hours=0):
    return (datetime.now(timezone.utc)-timedelta(days=days_ago,hours=hours)).isoformat()
class DashboardStatsTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData()
        self.dir=self.iso.start()
        # These two services keep their files under the app folder rather than common_db.data_dir().
        self.patches=[mock.patch.object(search_service,"_settings_path",lambda:os.path.join(self.dir,"settings.json")),mock.patch.object(notes_service,"_notes_meta_path",lambda:os.path.join(self.dir,"notes_meta.json"))]
        for p in self.patches:p.start()
        self.con=sqlite3.connect(common_db.db_path())
        common_db.ensure_schema(self.con)
    def tearDown(self):
        self.con.close()
        for p in self.patches:p.stop()
        self.iso.stop()
    def _targets(self,targets):
        with open(dash._targets_path(),"w",encoding="utf-8") as f:json.dump(targets,f)
    def _note(self,name,group="",created=None,updated=None):
        cur=self.con.execute("INSERT INTO Notes(note_name,group_name,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?)",(name,group,"","",created or _iso(),updated or _iso()))
        self.con.commit()
        return cur.lastrowid
    def _cmd(self,title,command,noise="normal",created=None):
        cur=self.con.execute("INSERT INTO CommandsNotes(note_name,category,sub_category,command,tags,description,noise_level,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(title,"Cat","Sub",command,"","",noise,created or _iso(),_iso()))
        self.con.commit()
        return cur.lastrowid
    def test_day_series_and_week_count(self):
        now=time.time()
        ts=[now,now-3600,now-2*86400,now-20*86400,None]
        series=dash._day_series(ts,14,now)
        self.assertEqual(14,len(series))
        self.assertEqual(3,sum(series))
        self.assertEqual(series[-1]+series[-2]+series[-3],3)
        self.assertEqual(3,dash._week_count(ts,now))
    def test_kpis_count_and_this_week(self):
        self._note("a",created=_iso(0));self._note("b",created=_iso(2));self._note("old",created=_iso(40))
        self._cmd("c1","whoami",created=_iso(1))
        self._targets([{"id":"t1","name":"A","status":"live","created":_iso(1),"values":{}},{"id":"t2","name":"B","created":_iso(30),"values":{}}])
        k=dash.get_stats()["kpi"]
        self.assertEqual((3,2),(k["notes"]["value"],k["notes"]["week"]))
        self.assertEqual((1,1),(k["commands"]["value"],k["commands"]["week"]))
        self.assertEqual((2,1),(k["targets"]["value"],k["targets"]["week"]))
        self.assertEqual(14,len(k["notes"]["series"]))
    def test_activity_feed_merges_sources_dedupes_and_flags_deleted(self):
        nid=self._note("Recon <b>x</b>")
        self.con.executemany("INSERT INTO NotesHistory(note_id,note_name,group_name,content,action,action_at) VALUES(?,?,?,?,?,?)",[(nid,"Recon <b>x</b>","","","insert",_iso(0,3)),(nid,"Recon <b>x</b>","","","update",_iso(0,1)),(99,"Gone","","","delete",_iso(0,2))])
        self.con.execute("INSERT INTO CommandsNotesHistory(cmd_id,note_name,category,sub_category,command,tags,description,action,action_at) VALUES(5,'Nmap','c','s','nmap','','','insert',?)",(_iso(0,4),))
        self.con.execute("INSERT INTO TerminalJobs(job_key,session_id,label,command,source,state,exit_code,started_at,ended_at) VALUES('k1','s','ls','ls -la','terminal','failed',2,?,?)",(_iso(0,6),_iso(0,5)))
        self.con.commit()
        self._targets([{"id":"t1","name":"DC","created":_iso(0,8),"updated":_iso(0,8),"values":{}}])
        feed=dash.get_stats()["activity_feed"]
        self.assertEqual(["note","note","command","job","target"],[e["kind"] for e in feed])
        self.assertEqual("edited",feed[0]["action"])
        self.assertEqual("Recon <b>x</b>",feed[0]["title"])
        self.assertTrue(feed[1]["deleted"])
        self.assertEqual("failed (exit 2)",feed[3]["action"])
        self.assertEqual("created",feed[4]["action"])
        legacy=dash.get_stats()["recent_activity"]
        self.assertTrue(legacy[0]["label"].startswith("Note: "))
    def test_recent_jobs_running_count_and_duration(self):
        self.con.execute("INSERT INTO TerminalJobs(job_key,session_id,label,command,source,state,exit_code,started_at,ended_at) VALUES('a','s','nmap','nmap x','snippet','done',0,?,?)",((datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat(),(datetime.now(timezone.utc)-timedelta(seconds=30)).isoformat()))
        self.con.execute("INSERT INTO TerminalJobs(job_key,session_id,label,command,source,state,started_at) VALUES('b','s','sleep','sleep 9','terminal','running',?)",(_iso(),))
        self.con.commit()
        j=dash.get_stats()["recent_jobs"]
        self.assertEqual((1,2),(j["running"],j["total"]))
        self.assertEqual("b",j["items"][0]["job_key"])
        self.assertEqual(60,j["items"][1]["duration_s"])
    def test_engagements_counts_unknown_as_not_started(self):
        self._targets([{"name":"a","engagement_status":"in_progress"},{"name":"b","engagement_status":"bogus"},{"name":"c"},{"name":"d","engagement_status":"Reported"},{"name":""}])
        e=dash.get_stats()["engagements"]
        self.assertEqual(4,e["total"])
        self.assertEqual({"not_started":2,"in_progress":1,"compromised":0,"reported":1},{s["id"]:s["count"] for s in e["statuses"]})
    def test_missing_placeholders_against_live_target(self):
        self._cmd("a","nmap {IPv4} -p {Port}")
        self._cmd("b","curl {URL} {IPv4}")
        self._cmd("c","echo ${HOME} {Port}")
        self._targets([{"id":"t1","name":"Live <one>","status":"live","values":{"ipv4":"10.0.0.1","URL":""}}])
        m=dash.get_stats()["missing_placeholders"]
        self.assertTrue(m["live"])
        self.assertEqual("Live <one>",m["live_name"])
        self.assertEqual(3,m["used_keys"])
        self.assertEqual([("Port",2),("URL",1)],[(x["key"],x["commands"]) for x in m["missing"]])
    def test_missing_placeholders_without_live_target_lists_everything(self):
        self._cmd("a","nmap {IPv4}")
        m=dash.get_stats()["missing_placeholders"]
        self.assertFalse(m["live"])
        self.assertEqual(["IPv4"],[x["key"] for x in m["missing"]])
    def test_live_target_values_ordered_and_listing(self):
        with open(os.path.join(self.dir,"target_values.json"),"w") as f:json.dump({"Domain":{"priority":1},"IPv4":{"priority":0}},f)
        self._targets([{"id":"t1","name":"B","status":"live","engagement_status":"compromised","values":{"Domain":"corp","IPv4":"10.0.0.5","Empty":""}},{"id":"t2","name":"a"}])
        lt=dash.get_stats()["live_target"]
        self.assertEqual(["a","B"],[t["name"] for t in lt["targets"]])
        self.assertEqual("t1",lt["target"]["id"])
        self.assertEqual(["IPv4","Domain"],[v["key"] for v in lt["target"]["values"]])
        self.assertEqual("Compromised",lt["target"]["engagement_label"])
    def test_most_used_commands_resolves_live_values_and_skips_deleted(self):
        a=self._cmd("Nmap","nmap {IPv4}","noisy")
        b=self._cmd("Who","whoami")
        rows=[(a,"CommandsNotes")]*3+[(b,"CommandsNotes")]+[(777,"CommandsNotes")]*5
        self.con.executemany("INSERT INTO CommandRuns(command_id,src,text,target_snapshot,ran_at) VALUES(?,?,'x','',?)",[(cid,src,_iso()) for cid,src in rows])
        self.con.commit()
        self._targets([{"id":"t","name":"L","status":"live","values":{"IPv4":"10.1.1.1"}}])
        mu=dash.get_stats()["most_used_commands"]
        self.assertEqual([("Nmap",3),("Who",1)],[(c["title"],c["runs"]) for c in mu])
        self.assertEqual("nmap 10.1.1.1",mu[0]["resolved"])
        self.assertEqual("noisy",mu[0]["noise_level"])
    def test_favorite_snippets_from_favourites(self):
        a=self._cmd("Zed","ls")
        b=self._cmd("Alpha","id")
        search_service.save_favorites([f"CommandsNotes:{a}",f"CommandsNotes:{b}","CommandsNotes:999","garbage"],False)
        self.assertEqual(["Alpha","Zed"],[c["title"] for c in dash.get_stats()["favorite_snippets"]])
    def test_recent_and_pinned_notes(self):
        old=self._note("Old",updated=_iso(3))
        new=self._note("New","G",updated=_iso(0))
        notes_service.set_pinned(old,"Old",True)
        s=dash.get_stats()
        self.assertEqual(["New","Old"],[n["name"] for n in s["recent_notes"]])
        self.assertEqual("G",s["recent_notes"][0]["group"])
        self.assertEqual(["Old"],[n["name"] for n in s["pinned_notes"]])
        self.assertTrue(s["pinned_notes"][0]["pinned"])
    def test_activity_heat_buckets_last_30_days(self):
        self.con.execute("INSERT INTO NotesHistory(note_id,note_name,group_name,content,action,action_at) VALUES(1,'n','','','update',?)",(_iso(0),))
        self.con.execute("INSERT INTO NotesHistory(note_id,note_name,group_name,content,action,action_at) VALUES(1,'n','','','delete',?)",(_iso(0),))
        self.con.execute("INSERT INTO CommandRuns(command_id,src,text,target_snapshot,ran_at) VALUES(1,'CommandsNotes','x','',?)",(_iso(5),))
        self.con.execute("INSERT INTO TerminalJobs(job_key,session_id,label,command,source,state,started_at) VALUES('j','s','l','c','t','done',?)",(_iso(45),))
        self.con.commit()
        h=dash.get_stats()["activity_heat"]
        self.assertEqual(30,len(h["days"]))
        self.assertEqual(1,h["days"][-1]["notes"])
        self.assertEqual(2,h["total"])
        self.assertEqual(2,h["active_days"])
    def test_security_health_levels(self):
        from Cores.Services import security_service,settings_service
        cfg={"app_lock_enabled":True,"auto_lock_minutes":5,"enc_enabled":False,"audit_expiry":{"enabled":True,"amount":1,"unit":"months"}}
        class B:
            def list(self):return [("x.zip",time.time()-3600,10)]
        with mock.patch.object(security_service,"get_security_settings",lambda:cfg),mock.patch.object(security_service,"pin_is_set",lambda c=None:True),mock.patch.object(settings_service,"_get_backup_settings",lambda:{"auto_enabled":True,"interval_hours":24}),mock.patch.object(settings_service,"Backup",B):
            h=dash._security_health()
        items={i["id"]:i for i in h["items"]}
        self.assertEqual("ok",items["backup"]["level"])
        self.assertEqual("On",items["app_lock"]["value"])
        self.assertEqual("1 month",items["audit_expiry"]["value"])
        self.assertEqual("info",items["encryption"]["level"])
        self.assertEqual("ok",h["overall"])
    def test_failing_section_is_reported_not_raised(self):
        with mock.patch.object(dash,"_engagements",side_effect=RuntimeError("boom")):
            s=dash.get_stats()
        self.assertIn("engagements",s["errors"])
        self.assertEqual(0,s["engagements"]["total"])
        self.assertIn("kpi",s)
    def test_reports_card_stats(self):
        from Cores.Services import reports_service
        s=dash.get_stats()
        self.assertEqual(0,s["reports"]["reports"])
        self.assertNotIn("reports",s["errors"])
        rep=reports_service.create_report({"title":"Card report","template_id":"blank"})
        reports_service.add_finding(rep["id"],{"title":"SQLi","severity":"critical"})
        reports_service.add_finding(rep["id"],{"title":"Fixed XSS","severity":"high","status":"fixed"})
        r=dash.get_stats()["reports"]
        self.assertEqual(1,r["reports"])
        self.assertEqual(1,r["by_status"]["draft"])
        self.assertEqual({"critical":1,"high":1},{k:v for k,v in r["findings"].items() if v})
        self.assertEqual({"critical":1},{k:v for k,v in r["open_by_severity"].items() if v})
        self.assertEqual(1,r["open_findings"])
        self.assertEqual("Card report",r["recent"][0]["title"])
        self.assertIn("reports",{w["id"] for w in dash.WIDGET_CATALOG})
    def test_reports_failure_does_not_break_the_dashboard(self):
        with mock.patch.object(dash,"_reports",side_effect=RuntimeError("boom")):
            s=dash.get_stats()
        self.assertIn("reports",s["errors"])
        self.assertEqual(0,s["reports"]["reports"])
        self.assertIsNone(s["reports"]["next_deadline"])
        self.assertIn("kpi",s)
class DashboardLayoutTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData()
        self.dir=self.iso.start()
    def tearDown(self):
        self.iso.stop()
    def _settings(self,d):
        with open(os.path.join(self.dir,"settings.json"),"w") as f:json.dump(d,f)
    def test_targets_read_through_doc_store(self):
        # Encryption at rest moves Targets.json into the encrypted DB; the KPI and live-target cards must still see them.
        rows=[{"id":"t1","name":"A","status":"live","created":_iso(0),"values":{}}]
        with mock.patch.object(dash._doc_store,"read_json",lambda p,d=None:rows if p==dash._targets_path() else d):
            self.assertFalse(os.path.exists(dash._targets_path()))
            self.assertEqual(1,dash.get_stats()["kpi"]["targets"]["value"])
    def test_app_version_is_retired(self):
        self.assertNotIn("app_version",{w["id"] for w in dash.WIDGET_CATALOG})
        for p in dash.PRESETS:self.assertNotIn("app_version",[c["widget"] for c in p["cards"]])
    def test_presets_only_use_known_widgets_and_sizes(self):
        ids={w["id"] for w in dash.WIDGET_CATALOG}
        for w in dash.WIDGET_CATALOG:self.assertIn(w["default_size"],dash.SIZE_PRESETS)
        for p in dash.PRESETS:
            self.assertEqual(p["cards"],dash._validate_cards(p["cards"]))
            self.assertTrue(all(c["widget"] in ids for c in p["cards"]))
        self.assertEqual("default",dash.PRESETS[0]["id"])
        self.assertIs(dash.PRESETS[0]["cards"],dash.DEFAULT_LAYOUT)
    def test_fresh_install_gets_new_default(self):
        self.assertEqual(dash.DEFAULT_LAYOUT,dash.get_layout())
        self.assertEqual("quick_actions",dash.get_layout()[0]["widget"])
    def test_saved_layout_kept_and_retired_cards_dropped_without_rewriting(self):
        saved=[{"id":"x","widget":"notes_by_group","size":"1x2"},{"id":"v","widget":"app_version","size":"0.25x1"},{"id":"y","widget":"notes_count","size":"weird"},"junk"]
        self._settings({"dashboard":{"cards":saved},"other":1})
        self.assertEqual([{"id":"x","widget":"notes_by_group","size":"1x2"},{"id":"y","widget":"notes_count","size":"1x1"}],dash.get_layout())
        with open(os.path.join(self.dir,"settings.json")) as f:self.assertEqual(saved,json.load(f)["dashboard"]["cards"])
    def test_named_layout_with_retired_card_applies_cleanly(self):
        self._settings({"dashboard_layouts":{"Old":[{"id":"a","widget":"app_version","size":"0.25x1"},{"id":"b","widget":"targets_count","size":"1x1"}]}})
        self.assertEqual(["targets_count"],[c["widget"] for c in dash.apply_layout("Old")])
        self.assertEqual(["targets_count"],[c["widget"] for c in dash.get_layout()])
    def test_save_rejects_retired_widget(self):
        with self.assertRaises(ValueError):dash.save_layout([{"id":"v","widget":"app_version","size":"0.25x1"}])
    def test_apply_preset_and_restore_default_keep_saved_layouts(self):
        self._settings({"dashboard_layouts":{"Mine":[{"id":"a","widget":"notes_count","size":"1x1"}]}})
        cards=dash.apply_preset("classic")
        self.assertEqual(dash.CLASSIC_LAYOUT,cards)
        self.assertEqual(dash.CLASSIC_LAYOUT,dash.get_layout())
        self.assertEqual(dash.DEFAULT_LAYOUT,dash.restore_default())
        self.assertEqual(["Mine"],dash.list_layouts())
        with self.assertRaises(ValueError):dash.apply_preset("nope")
        self.assertEqual(["default","operator","classic"],[p["id"] for p in dash.list_presets()])
if __name__=="__main__":
    unittest.main()
