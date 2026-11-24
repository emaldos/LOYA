import base64,json,os,sqlite3,unittest
from contextlib import closing
from _isolate import IsolatedData
from Cores import common_db,recycle_bin
from Cores.Services import evidence_service as evidence
PNG_1X1=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PRIVATE_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\nQyNTUxOQAAACDxSECRETSECRETSECRETSECRETSECRETSECRETSECRETAAAA\n-----END OPENSSH PRIVATE KEY-----\n"
class EvidenceBase(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.data_dir=self.isolated.start()
        evidence._streams.clear()
    def tearDown(self):
        evidence._streams.clear()
        self.isolated.stop()
    def settings(self,reports):
        with open(os.path.join(self.data_dir,"settings.json"),"w",encoding="utf-8") as handle:json.dump({"reports":reports},handle)
    def job(self,**extra):
        info={"session_id":"s1","job_key":"j1","command":"id","output":"uid=1000(kali) gid=1000(kali)\n","exit_code":0,"cwd":"/home/kali","started_at":"2026-11-23T10:00:00Z","ended_at":"2026-11-23T10:00:01Z"}
        info.update(extra)
        return evidence.save_job(info)
class CleaningTests(EvidenceBase):
    def test_ansi_sequences_and_control_bytes_are_stripped(self):
        raw="\x1b[1;31mred\x1b[0m plain \x1b]0;window title\x07tail\x00\x08\r\nnext"
        self.assertEqual("red plain tail\nnext",evidence.strip_ansi(raw))
    def test_carriage_return_redraw_keeps_the_last_state(self):
        self.assertEqual("100% done\nok",evidence.strip_ansi("10%\r50%\r100% done\nok"))
    def test_cap_marks_truncation_and_reports_the_dropped_size(self):
        text,truncated=evidence.cap_text("a"*100,40)
        self.assertTrue(truncated)
        self.assertIn(evidence.TRUNCATED_MARK,text)
        self.assertIn("60 more characters",text)
        self.assertTrue(text.startswith("a"*40))
    def test_cap_leaves_short_text_alone(self):
        self.assertEqual(("short",False),evidence.cap_text("short",40))
    def test_iso_accepts_js_epoch_iso_text_and_rejects_junk(self):
        self.assertEqual("2023-11-14T22:13:20+00:00",evidence._iso(1700000000000))
        self.assertEqual("2026-11-23T10:00:00+00:00",evidence._iso("2026-11-23T10:00:00Z"))
        self.assertEqual("2026-11-23T09:00:00+00:00",evidence._iso("2026-11-23T10:00:00+01:00"))
        self.assertEqual("",evidence._iso("yesterday"))
        self.assertEqual("",evidence._iso(None))
class SaveTests(EvidenceBase):
    def test_save_job_stores_a_command_item_with_the_contract_shape(self):
        item=self.job()
        for key in ("id","uid","kind","title","source","session_id","profile_id","target","command","exit_code","cwd","started_at","ended_at","content","meta","created_at"):self.assertIn(key,item)
        self.assertEqual("command",item["kind"])
        self.assertEqual("terminal",item["source"])
        self.assertEqual("id",item["title"])
        self.assertEqual(0,item["exit_code"])
        self.assertEqual("j1",item["meta"]["job_key"])
        self.assertEqual("default",item["profile_id"])
        self.assertEqual("2026-11-23T10:00:00+00:00",item["started_at"])
    def test_save_job_redacts_output_and_command_and_counts(self):
        item=self.job(command="curl -H 'Authorization: Bearer abc.def.ghi' http://x",output="api_key=SUPERSECRET1\nfine line\nmysql://app:dbpass99@db/x\n")
        self.assertNotIn("SUPERSECRET1",item["content"])
        self.assertNotIn("dbpass99",item["content"])
        self.assertNotIn("abc.def.ghi",item["command"])
        self.assertIn("fine line",item["content"])
        self.assertGreaterEqual(item["meta"]["redacted"],3)
    def test_redaction_can_be_switched_off_in_the_reports_defaults(self):
        self.settings({"redact_evidence":False})
        self.assertFalse(evidence.redact_enabled())
        item=self.job(output="api_key=SUPERSECRET1\n")
        self.assertIn("SUPERSECRET1",item["content"])
        self.assertEqual(0,item["meta"]["redacted"])
    def test_redaction_defaults_to_on_without_settings(self):
        self.assertTrue(evidence.redact_enabled())
        self.settings({"page_size":"A4"})
        self.assertTrue(evidence.redact_enabled())
    def test_save_job_strips_ansi_and_the_echoed_command_line(self):
        item=self.job(command="ls -la",output="\x1b[32mkali@kali\x1b[0m:~$ ls -la\r\ntotal 0\r\n\x1b[34mdir\x1b[0m\r\n")
        self.assertEqual("total 0\ndir\n",item["content"])
    def test_save_job_drops_the_trailing_prompt_but_not_real_output(self):
        kali=self.job(command="id",output="\u2514\u2500$ id\n\nuid=1000(kali)\n\n\u250c\u2500\u2500(kali\u327fkali)-[~]\n\u2514\u2500$ ")
        self.assertEqual("uid=1000(kali)\n",kali["content"])
        bash=self.job(job_key="b",command="pwd",output="kali@kali:~$ pwd\n/home/kali\nkali@kali:~$ ")
        self.assertEqual("/home/kali\n",bash["content"])
        windows=self.job(job_key="w",command="whoami",output="PS C:\\Users\\bob> whoami\ncorp\\bob\nPS C:\\Users\\bob> ")
        self.assertEqual("corp\\bob\n",windows["content"])
        for index,tail in enumerate(("progress 100%","price in $","<html>","a > b","# heading")):
            kept=self.job(job_key="k"+str(index),command="x",output="line one\n"+tail)
            self.assertEqual("line one\n"+tail+"\n",kept["content"],tail)
    def test_save_job_caps_content_at_two_megabytes(self):
        item=self.job(output=("line of output\n"*200000))
        self.assertLess(len(item["content"]),evidence.MAX_CONTENT+400)
        self.assertIn(evidence.TRUNCATED_MARK,item["content"])
        self.assertTrue(item["meta"]["truncated"])
    def test_saving_the_same_job_twice_updates_instead_of_duplicating(self):
        first=self.job(output="partial\n",exit_code=None)
        second=self.job(output="partial\ncomplete\n",exit_code=0)
        self.assertEqual(first["id"],second["id"])
        self.assertEqual("partial\ncomplete\n",second["content"])
        self.assertEqual(1,len(evidence.list_evidence()))
    def test_save_job_needs_a_command_or_output(self):
        with self.assertRaises(ValueError):evidence.save_job({"session_id":"s1","command":"","output":"  "})
    def test_save_job_stamps_profile_and_live_target(self):
        with open(os.path.join(self.data_dir,"Targets.json"),"w",encoding="utf-8") as handle:json.dump([{"id":"t1","name":"web01","status":"not_used"},{"id":"t2","name":"dc01","status":"live"}],handle)
        item=self.job()
        self.assertEqual("dc01",item["target"])
        self.assertEqual("default",item["profile_id"])
    def test_save_text_is_text_kind_and_command_kind_with_a_command(self):
        text=evidence.save_text({"title":"Notes from the call","content":"Scope confirmed.\n"})
        self.assertEqual("text",text["kind"]);self.assertEqual("manual",text["source"])
        pasted=evidence.save_text({"content":"80/tcp open http\n","command":"nmap 10.0.0.1"})
        self.assertEqual("command",pasted["kind"]);self.assertEqual("nmap 10.0.0.1",pasted["title"])
        with self.assertRaises(ValueError):evidence.save_text({"title":"x","content":""})
    def test_save_image_stores_an_asset_and_dedupes_it(self):
        data="data:image/png;base64,"+base64.b64encode(PNG_1X1).decode("ascii")
        first=evidence.save_image("C:\\shots\\login page.png",data,"Login page")
        self.assertEqual("image",first["kind"]);self.assertEqual("",first["content"])
        self.assertEqual("Login page",first["title"]);self.assertEqual("login page.png",first["meta"]["file_name"])
        self.assertTrue(first["meta"]["asset_uid"])
        second=evidence.save_image("again.png",base64.b64encode(PNG_1X1).decode("ascii"))
        self.assertEqual(first["meta"]["asset_uid"],second["meta"]["asset_uid"])
        self.assertTrue(evidence.asset_data_url(first["id"]).startswith("data:image/png;base64,"))
        with closing(sqlite3.connect(common_db.db_path())) as con:self.assertEqual(1,con.execute("SELECT COUNT(*) FROM ReportAssets").fetchone()[0])
    def test_save_image_rejects_non_images_and_oversize(self):
        with self.assertRaises(ValueError):evidence.save_image("x.png",base64.b64encode(b"<svg onload=alert(1)>").decode("ascii"))
        with self.assertRaises(ValueError):evidence.save_image("x.png","")
        big=base64.b64encode(b"\x89PNG\r\n\x1a\n"+b"0"*(evidence.MAX_IMAGE_BYTES+1)).decode("ascii")
        with self.assertRaises(ValueError):evidence.save_image("big.png",big)
class ListGetUpdateTests(EvidenceBase):
    def seed(self):
        self.a=self.job(job_key="a",command="nmap -sV 10.0.0.5",output="22/tcp open ssh\n"+"x"*600)
        self.b=self.job(job_key="b",session_id="s2",command="id")
        self.c=evidence.save_text({"title":"Scope note","content":"Only 10.0.0.0/24 is in scope."})
    def test_list_returns_previews_not_content_newest_first(self):
        self.seed()
        rows=evidence.list_evidence()
        self.assertEqual([self.c["id"],self.b["id"],self.a["id"]],[row["id"] for row in rows])
        first=rows[-1]
        self.assertNotIn("content",first)
        self.assertEqual(evidence.PREVIEW_CHARS,len(first["preview"]))
        self.assertEqual(len(self.a["content"]),first["size"])
        self.assertEqual(0,first["event_count"])
    def test_list_filters_by_kind_session_profile_query_and_limit(self):
        self.seed()
        self.assertEqual([self.c["id"]],[row["id"] for row in evidence.list_evidence({"kind":"text"})])
        self.assertEqual(2,len(evidence.list_evidence({"kinds":["command"]})))
        self.assertEqual([self.b["id"]],[row["id"] for row in evidence.list_evidence({"session_id":"s2"})])
        self.assertEqual(3,len(evidence.list_evidence({"profile_id":"default"})))
        self.assertEqual(0,len(evidence.list_evidence({"profile_id":"other"})))
        self.assertEqual([self.a["id"]],[row["id"] for row in evidence.list_evidence({"query":"nmap"})])
        self.assertEqual([self.c["id"]],[row["id"] for row in evidence.list_evidence({"query":"in scope"})])
        self.assertEqual(0,len(evidence.list_evidence({"query":"100%_"})))
        self.assertEqual(1,len(evidence.list_evidence({"limit":1})))
    def test_get_by_id_and_uid_and_missing(self):
        self.seed()
        self.assertEqual(self.a["uid"],evidence.get(self.a["id"])["uid"])
        self.assertEqual(self.a["id"],evidence.get(self.a["uid"])["id"])
        self.assertEqual(self.a["id"],evidence.get(str(self.a["id"]))["id"])
        with self.assertRaises(ValueError):evidence.get(9999)
        with self.assertRaises(ValueError):evidence.get("no-such-uid")
    def test_update_title_notes_tags(self):
        self.seed()
        updated=evidence.update(self.a["id"],{"title":"  Service scan  ","notes":"Run from the jump host","tags":["recon","recon","  ","nmap"]})
        self.assertEqual("Service scan",updated["title"])
        self.assertEqual("Run from the jump host",updated["meta"]["notes"])
        self.assertEqual(["recon","nmap"],updated["meta"]["tags"])
        self.assertEqual("a",updated["meta"]["job_key"])
        with self.assertRaises(ValueError):evidence.update(self.a["id"],{"title":"   "})
    def test_database_lock_is_respected(self):
        common_db.set_locked(True)
        try:
            with self.assertRaises(common_db.DatabaseLocked):evidence.list_evidence()
        finally:
            common_db.set_locked(False)
class RecycleTests(EvidenceBase):
    def test_delete_moves_to_recycle_bin_and_restore_brings_it_back_with_the_same_uid(self):
        item=self.job()
        self.assertTrue(evidence.delete(item["id"]))
        self.assertEqual([],evidence.list_evidence())
        entries=recycle_bin.list_entries(entity_type=evidence.RECYCLE_TYPE)
        self.assertEqual(1,len(entries))
        self.assertEqual("id",entries[0]["label"]);self.assertEqual(item["uid"],entries[0]["entity_key"])
        new_id=evidence.restore_entry(entries[0]["payload"])
        restored=evidence.get(new_id)
        self.assertEqual(item["uid"],restored["uid"])
        self.assertEqual(item["content"],restored["content"])
        self.assertEqual(item["created_at"],restored["created_at"])
        with self.assertRaises(ValueError):evidence.restore_entry(entries[0]["payload"])
    def test_recording_delete_and_restore_keeps_events(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.recording_append(rec["id"],[{"kind":"cmd","data":"id"},{"kind":"out","data":"uid=1000\n"},{"kind":"exit","data":{"code":0}}])
        evidence.delete(rec["id"])
        with closing(sqlite3.connect(common_db.db_path())) as con:self.assertEqual(0,con.execute("SELECT COUNT(*) FROM ReportEvidenceEvents").fetchone()[0])
        entry=recycle_bin.list_entries(entity_type=evidence.RECYCLE_TYPE)[0]
        restored=evidence.get(evidence.restore_entry(entry["payload"]))
        self.assertEqual("stopped",restored["meta"]["state"])
        self.assertEqual(["cmd","out","exit"],[event["kind"] for event in restored["events"]])
        self.assertIn("$ id",restored["content"])
    def test_restore_inside_a_callers_transaction(self):
        item=self.job()
        evidence.delete(item["id"])
        entry=recycle_bin.list_entries(entity_type=evidence.RECYCLE_TYPE)[0]
        with closing(sqlite3.connect(common_db.db_path())) as con:
            cur=con.cursor()
            evidence.restore_entry(entry["payload"],cur)
            con.rollback()
        self.assertEqual([],evidence.list_evidence())
    def test_restore_rejects_a_bad_payload(self):
        with self.assertRaises(ValueError):evidence.restore_entry({"evidence":{"kind":"virus"}})
        with self.assertRaises(ValueError):evidence.restore_entry({})
    def test_delete_many_counts_only_existing_items(self):
        a=self.job(job_key="a");b=self.job(job_key="b")
        self.assertEqual(2,evidence.delete_many([a["id"],b["id"],9999]))
class RedactStreamTests(unittest.TestCase):
    def feed_all(self,chunks,do_redact=True):
        stream=evidence._RedactStream(do_redact)
        out="";count=0
        for chunk in chunks:
            text,found=stream.feed(chunk)
            out+=text;count+=found
        text,found=stream.flush()
        return out+text,count+found
    def test_secret_split_across_chunks_is_redacted(self):
        out,count=self.feed_all(["user=bob pass","word=hun","ter2\nnext line\n"])
        self.assertNotIn("hunter2",out);self.assertNotIn("hun",out.replace("hunter2",""))
        self.assertIn("password=[redacted]",out)
        self.assertIn("next line",out)
        self.assertEqual(1,count)
    def test_incomplete_line_is_held_until_its_newline(self):
        stream=evidence._RedactStream(True)
        self.assertEqual(("",0),stream.feed("token=abc"))
        text,count=stream.feed("def\n")
        self.assertEqual("token=[redacted]\n",text);self.assertEqual(1,count)
    def test_flush_redacts_the_unterminated_tail(self):
        out,count=self.feed_all(["api_key=TOPSECRET"])
        self.assertEqual("api_key=[redacted]",out);self.assertEqual(1,count)
    def test_private_key_split_across_chunks_is_redacted(self):
        half=len(PRIVATE_KEY)//2
        out,count=self.feed_all(["cat id_ed25519\n"+PRIVATE_KEY[:half],PRIVATE_KEY[half:]+"done\n"])
        self.assertNotIn("SECRETSECRET",out)
        self.assertIn("cat id_ed25519",out);self.assertIn("done",out)
        self.assertIn("-----BEGIN OPENSSH PRIVATE KEY-----[redacted]-----END OPENSSH PRIVATE KEY-----",out)
        self.assertEqual(1,count)
    def test_private_key_that_never_ends_is_dropped(self):
        out,count=self.feed_all(["before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow"+"A"*100+"\n"])
        self.assertEqual("before\n[redacted private key]\n",out);self.assertEqual(1,count)
    def test_oversized_private_key_block_is_cut_and_later_output_resumes(self):
        stream=evidence._RedactStream(True)
        out,_count=stream.feed("-----BEGIN RSA PRIVATE KEY-----\n"+("QUJD"*20+"\n")*1000)
        self.assertEqual("[redacted private key]\n",out)
        self.assertEqual(("",0),stream.feed("QUJDQUJD\n"))
        text,_count=stream.feed("-----END RSA PRIVATE KEY-----\nafter\n")
        self.assertEqual("\nafter\n",text)
    def test_without_redaction_text_is_only_cleaned(self):
        out,count=self.feed_all(["\x1b[31mtoken=abc\x1b[0m\n"],False)
        self.assertEqual("token=abc\n",out);self.assertEqual(0,count)
    def test_long_line_without_newline_is_flushed_rather_than_held_forever(self):
        stream=evidence._RedactStream(True)
        text,_count=stream.feed("x"*(evidence._CARRY_MAX+10))
        self.assertEqual(evidence._CARRY_MAX+10,len(text))
class RecordingTests(EvidenceBase):
    def events(self):
        return [{"ts":"2026-11-23T10:12:03.000Z","kind":"cmd","data":"nmap -sV 10.0.0.5"},{"ts":"2026-11-23T10:12:04Z","kind":"out","data":"kali$ nmap -sV 10.0.0.5\nStarting Nmap\n22/tcp open ssh\n"},{"ts":"2026-11-23T10:12:06Z","kind":"exit","data":{"code":0,"duration":3.24,"cwd":"/home/kali"}},{"ts":"2026-11-23T10:12:10Z","kind":"mark","data":"moving on to the web server"},{"ts":"2026-11-23T10:12:20Z","kind":"cmd","data":"false"},{"ts":"2026-11-23T10:12:20Z","kind":"exit","data":"{\"code\":1,\"duration\":75}"}]
    def test_lifecycle_start_append_stop_renders_a_transcript(self):
        rec=evidence.recording_start({"session_id":"s1","label":"bash 1","shell":"bash"})
        self.assertEqual("recording",rec["kind"]);self.assertEqual("recording",rec["meta"]["state"])
        self.assertIn("bash 1",rec["title"])
        result=evidence.recording_append(rec["id"],self.events())
        self.assertEqual(6,result["seq"]);self.assertFalse(result["capped"])
        self.assertEqual([rec["id"]],[row["id"] for row in evidence.recordings_active()])
        live=evidence.get(rec["id"])
        self.assertIn("[10:12:03] $ nmap -sV 10.0.0.5",live["content"])
        stopped=evidence.recording_stop(rec["id"])
        self.assertEqual("stopped",stopped["meta"]["state"]);self.assertTrue(stopped["ended_at"])
        self.assertEqual(2,stopped["meta"]["commands"])
        text=stopped["content"]
        self.assertIn("[10:12:03] $ nmap -sV 10.0.0.5\nStarting Nmap\n22/tcp open ssh\n[exit 0, 3.2s]\n",text)
        self.assertNotIn("kali$ nmap",text)
        self.assertIn("[10:12:10] -- moving on to the web server --",text)
        self.assertIn("[10:12:20] $ false\n[exit 1, 1m 15s]",text)
        self.assertEqual(["cmd","out","exit","mark","cmd","exit"],[event["kind"] for event in stopped["events"]])
        self.assertEqual([1,2,3,4,5,6],[event["seq"] for event in stopped["events"]])
        self.assertEqual([],evidence.recordings_active())
        row=[r for r in evidence.list_evidence({"kind":"recording"})][0]
        self.assertEqual(6,row["event_count"])
    def test_start_is_idempotent_per_session_and_needs_a_session(self):
        first=evidence.recording_start({"session_id":"s1"})
        again=evidence.recording_start({"session_id":"s1"})
        other=evidence.recording_start({"session_id":"s2"})
        self.assertEqual(first["id"],again["id"]);self.assertNotEqual(first["id"],other["id"])
        self.assertEqual(2,len(evidence.recordings_active()))
        with self.assertRaises(ValueError):evidence.recording_start({})
    def test_append_to_a_stopped_recording_is_refused_and_stop_is_idempotent(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.recording_append(rec["id"],[{"kind":"mark","data":"start"}])
        evidence.recording_stop(rec["id"])
        with self.assertRaises(ValueError):evidence.recording_append(rec["id"],[{"kind":"out","data":"late\n"}])
        self.assertEqual("stopped",evidence.recording_stop(rec["id"])["meta"]["state"])
        with self.assertRaises(ValueError):evidence.recording_stop(self.job()["id"])
    def test_appended_chunks_are_redacted_across_boundaries_and_ansi_stripped(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.recording_append(rec["id"],[{"kind":"cmd","data":"cat .env"},{"kind":"out","data":"\x1b[32mDB_HOST=db\x1b[0m\nDB_PASS"}])
        evidence.recording_append(rec["id"],[{"kind":"out","data":"WORD=s3cr"}])
        evidence.recording_append(rec["id"],[{"kind":"out","data":"3tvalue\nlast line without newline"}])
        stopped=evidence.recording_stop(rec["id"])
        blob=json.dumps(stopped)
        self.assertNotIn("s3cr",blob);self.assertNotIn("3tvalue",blob);self.assertNotIn("\\u001b",blob)
        self.assertIn("DB_HOST=db\nDB_PASSWORD=[redacted]\nlast line without newline",stopped["content"])
        self.assertEqual(1,stopped["meta"]["redacted"])
    def test_stopping_an_empty_recording_discards_it(self):
        rec=evidence.recording_start({"session_id":"s1"})
        stopped=evidence.recording_stop(rec["id"])
        self.assertTrue(stopped["meta"]["discarded"]);self.assertEqual("stopped",stopped["meta"]["state"])
        self.assertEqual([],evidence.list_evidence())
        self.assertEqual([],recycle_bin.list_entries(entity_type=evidence.RECYCLE_TYPE))
    def test_commands_are_redacted_too(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.recording_append(rec["id"],[{"kind":"cmd","data":"curl -H 'Authorization: Bearer tok.en.value' http://x"}])
        stopped=evidence.recording_stop(rec["id"])
        self.assertNotIn("tok.en.value",json.dumps(stopped))
        self.assertGreaterEqual(stopped["meta"]["redacted"],1)
    def test_output_split_before_a_command_keeps_event_order(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.recording_append(rec["id"],[{"kind":"out","data":"prompt$ "},{"kind":"cmd","data":"id"},{"kind":"out","data":"uid=1000\n"}])
        events=evidence.get(rec["id"])["events"]
        self.assertEqual([("out","prompt$ "),("cmd","id"),("out","uid=1000\n")],[(event["kind"],event["data"]) for event in events])
    def test_recording_size_is_capped_with_a_marker_event(self):
        original=evidence.MAX_RECORDING
        evidence.MAX_RECORDING=1000
        try:
            rec=evidence.recording_start({"session_id":"s1"})
            first=evidence.recording_append(rec["id"],[{"kind":"out","data":("y"*99+"\n")*8}])
            self.assertFalse(first["capped"])
            second=evidence.recording_append(rec["id"],[{"kind":"out","data":("z"*99+"\n")*8}])
            self.assertTrue(second["capped"])
            third=evidence.recording_append(rec["id"],[{"kind":"out","data":"dropped\n"},{"kind":"cmd","data":"still recorded"}])
            self.assertTrue(third["capped"])
            stopped=evidence.recording_stop(rec["id"])
            marks=[event for event in stopped["events"] if event["kind"]=="mark"]
            self.assertEqual(1,len(marks));self.assertEqual(evidence.RECORDING_LIMIT_MARK,marks[0]["data"])
            self.assertEqual(1000,sum(len(event["data"]) for event in stopped["events"] if event["kind"]=="out"))
            self.assertNotIn("dropped",stopped["content"])
            self.assertIn("$ still recorded",stopped["content"])
            self.assertTrue(stopped["meta"]["capped"])
        finally:
            evidence.MAX_RECORDING=original
    def test_unknown_event_kinds_and_bad_timestamps_are_tolerated(self):
        rec=evidence.recording_start({"session_id":"s1"})
        result=evidence.recording_append(rec["id"],[{"kind":"evil","data":"x"},"junk",{"kind":"mark","data":"note","ts":"not a time"},{"kind":"cmd","data":"   "}])
        self.assertEqual(1,result["seq"])
        self.assertTrue(evidence.get(rec["id"])["events"][0]["ts"])
    def test_recording_left_open_by_a_previous_run_is_closed_on_the_next_list(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.recording_append(rec["id"],[{"ts":"2026-11-23T10:12:03Z","kind":"cmd","data":"id"},{"ts":"2026-11-23T10:12:04Z","kind":"out","data":"uid=1000\n"}])
        original=evidence._BOOT
        evidence._BOOT="a-new-process"
        evidence._streams.clear()
        try:
            rows=evidence.list_evidence({"kind":"recording"})
            self.assertEqual("stopped",rows[0]["meta"]["state"])
            self.assertEqual("interrupted",rows[0]["meta"]["stopped_reason"])
            self.assertEqual("2026-11-23T10:12:04+00:00",rows[0]["ended_at"])
            self.assertIn("$ id\nuid=1000",evidence.get(rec["id"])["content"])
            self.assertEqual([],evidence.recordings_active())
            fresh=evidence.recording_start({"session_id":"s1"})
            self.assertNotEqual(rec["id"],fresh["id"])
        finally:
            evidence._BOOT=original
    def test_recording_of_this_run_survives_a_list(self):
        rec=evidence.recording_start({"session_id":"s1"})
        evidence.list_evidence()
        self.assertEqual("recording",evidence.get(rec["id"])["meta"]["state"])
    def test_recording_whose_live_terminal_session_ended_is_closed(self):
        rec=evidence.recording_start({"session_id":"s1"})
        with closing(sqlite3.connect(common_db.db_path())) as con:
            evidence.recording_append(rec["id"],[{"kind":"mark","data":"start"}])
            meta=evidence.get(rec["id"])["meta"];meta["live_session"]=True
            con.execute("UPDATE ReportEvidence SET meta=? WHERE id=?",(json.dumps(meta),rec["id"]));con.commit()
        self.assertEqual(1,evidence.sweep_recordings())
        self.assertEqual("stopped",evidence.get(rec["id"])["meta"]["state"])
class BridgeTests(EvidenceBase):
    def test_bridge_exposes_the_contract_methods(self):
        from Cores.Bridge.evidence_api import EvidenceAPI
        api=EvidenceAPI()
        for name in ("list","get","save_job","save_text","save_image","update","delete","delete_many","recording_start","recording_append","recording_stop","recordings_active","autogen_preview","autogen_create"):self.assertTrue(callable(getattr(api,name)),name)
        item=api.save_job({"session_id":"s1","job_key":"j","command":"id","output":"uid=1000\n"})
        self.assertEqual(item["id"],api.get(item["uid"])["id"])
        self.assertEqual(1,len(api.list({"kind":"command"})))
        self.assertTrue(api.delete(item["id"]))
if __name__=="__main__":
    unittest.main()
