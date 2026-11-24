import json,sqlite3,unittest
from datetime import date,datetime,timedelta
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import reports_service as reports
from Cores.Services import report_schedule as schedule
from Cores.Services import report_sections as sections
from Cores.Bridge.reports_api import ReportsAPI
TODAY=date(2026,11,23)
def d(n):return (TODAY+timedelta(days=n)).strftime("%Y-%m-%d")
class Base(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.dir=self.isolated.start()
        self.api=ReportsAPI()
    def tearDown(self):
        common_db.set_locked(False)
        self.isolated.stop()
    def report(self,title="ACME External Pentest",milestones=(),**kw):
        rep=self.api.create(dict({"title":title,"template_id":"blank"},**kw))
        if milestones:self.api.schedule_set(rep["id"],{"milestones":list(milestones)})
        return self.api.get(rep["id"])
    def meta(self,rid):
        con=sqlite3.connect(common_db.db_path())
        try:return json.loads(con.execute("SELECT meta FROM Reports WHERE id=?",(rid,)).fetchone()[0])
        finally:con.close()
class NormaliseTests(Base):
    def test_shape_and_defaults(self):
        out=schedule.normalize({"milestones":[{"key":"handover","date":"2026-11-30","time":"17:00","done":1,"remind":[{"days_before":1},{"days_before":7},{"days_before":1},{"days_before":-2},{"days_before":"x"},3],"notes":" call first "}]})
        m=out["milestones"][0]
        self.assertEqual({"id","key","label","date","time","done","remind","notes"},set(m))
        self.assertEqual(("handover","Hand-over","2026-11-30","17:00",True,"call first"),(m["key"],m["label"],m["date"],m["time"],m["done"],m["notes"]))
        self.assertEqual([{"days_before":7},{"days_before":3},{"days_before":1}],m["remind"])
        self.assertRegex(m["id"],r"^[A-Za-z0-9_-]{1,40}$")
    def test_bad_values_are_cleaned(self):
        out=schedule.normalize({"milestones":[{"id":"keep_me","key":"nonsense","label":"x"*300,"date":"2026-02-30","time":"25:00","done":"false","remind":"soon"},{"id":"keep_me","key":"review","date":"2026-11-25T10:00:00"},"junk",None,{"id":"<script>","key":"KICKOFF"}]})
        a,b,c=out["milestones"]
        self.assertEqual(("keep_me","custom","","",False,[]),(a["id"],a["key"],a["date"],a["time"],a["done"],a["remind"]))
        self.assertEqual(120,len(a["label"]))
        self.assertNotEqual("keep_me",b["id"]);self.assertEqual(("review","QA / review","2026-11-25"),(b["key"],b["label"],b["date"]))
        self.assertEqual("kickoff",c["key"]);self.assertNotIn("<",c["id"])
    def test_garbage_and_limits(self):
        for junk in (None,"x",5,[],{"milestones":"no"}):self.assertEqual({"milestones":[]},schedule.normalize(junk))
        self.assertEqual(schedule.MAX_MILESTONES,len(schedule.normalize([{"key":"custom"}]*200)["milestones"]))
        self.assertEqual(schedule.MAX_REMINDERS,len(schedule.normalize([{"remind":list(range(40))}])["milestones"][0]["remind"]))
    def test_every_builtin_key_has_a_label(self):
        for k in ("kickoff","testing_start","testing_end","draft_due","review","handover","retest_start","retest_end","custom"):
            self.assertIn(k,schedule.MILESTONE_KEYS);self.assertTrue(schedule.MILESTONE_LABELS[k])
    def test_stored_through_the_report_and_ids_are_stable(self):
        rep=self.report(milestones=[{"key":"handover","date":d(5),"remind":[{"days_before":1}]}])
        ms=rep["meta"]["schedule"]["milestones"]
        self.assertEqual(ms,self.api.get(rep["id"])["meta"]["schedule"]["milestones"])
        self.assertEqual({"milestones":ms},self.api.schedule_get(rep["id"]))
        # an ordinary meta patch from the page is normalised too, and unknown meta keys beside it survive
        self.api.update(rep["id"],{"meta":{"schedule":{"milestones":[{"id":ms[0]["id"],"key":"handover","date":"garbage","remind":[{"days_before":999}]}]},"my_extra":{"a":1}}})
        got=self.api.get(rep["id"])["meta"]
        self.assertEqual(("",[]),(got["schedule"]["milestones"][0]["date"],got["schedule"]["milestones"][0]["remind"]))
        self.assertEqual({"a":1},got["my_extra"])
    def test_schedule_get_of_a_report_without_one(self):
        self.assertEqual({"milestones":[]},self.api.schedule_get(self.report()["id"]))
        with self.assertRaises(ValueError):self.api.schedule_get(99999)
class DeadlineTests(Base):
    def test_next_deadline_is_the_earliest_open_milestone(self):
        rep=self.report(milestones=[{"key":"kickoff","date":d(-9),"done":True},{"key":"handover","date":d(3),"time":"17:00"},{"key":"draft_due","date":d(1)},{"key":"review","date":""}])
        nd=schedule.next_deadline(rep,TODAY)
        self.assertEqual(("draft_due","Draft report",d(1),1,False,rep["id"],rep["title"]),(nd["key"],nd["label"],nd["date"],nd["days_left"],nd["overdue"],nd["report_id"],nd["title"]))
    def test_an_overdue_milestone_comes_first(self):
        rep=self.report(milestones=[{"key":"handover","date":d(3)},{"key":"draft_due","date":d(-2)}])
        nd=schedule.next_deadline(rep,datetime(2026,11,23,9,0))
        self.assertEqual(("draft_due",-2,True),(nd["key"],nd["days_left"],nd["overdue"]))
    def test_none_when_nothing_is_pending_or_the_report_is_final(self):
        self.assertIsNone(schedule.next_deadline(self.report(),TODAY))
        self.assertIsNone(schedule.next_deadline(self.report(milestones=[{"key":"handover","date":d(1),"done":True},{"key":"review"}]),TODAY))
        rep=self.report(milestones=[{"key":"handover","date":d(1)}])
        self.api.update(rep["id"],{"status":"final"})
        self.assertIsNone(schedule.next_deadline(self.api.get(rep["id"]),TODAY))
        self.assertIsNone(schedule.next_deadline(None,TODAY))
    def test_upcoming_and_deadlines_across_reports(self):
        a=self.report("A",[{"key":"handover","date":d(4)},{"key":"draft_due","date":d(2)}])
        b=self.report("B",[{"key":"handover","date":d(-1)}])
        c=self.report("C",[{"key":"handover","date":d(1)}]);self.api.update(c["id"],{"status":"final"})
        rows=schedule.upcoming(10,TODAY)
        self.assertEqual([("B",-1),("A",2),("A",4)],[(r["title"],r["days_left"]) for r in rows])
        self.assertEqual(1,len(schedule.upcoming(1,TODAY)))
        dl=schedule.deadlines(TODAY)
        self.assertEqual({str(a["id"]),str(b["id"])},set(dl))
        self.assertEqual(("Draft report",2),(dl[str(a["id"])]["label"],dl[str(a["id"])]["days_left"]))
        self.assertTrue(dl[str(b["id"])]["overdue"])
        self.assertIsInstance(self.api.upcoming(5),list);self.assertIsInstance(self.api.deadlines(),dict)
    def test_stats_fields(self):
        st=self.api.stats()
        self.assertIsNone(st["next_deadline"]);self.assertEqual(0,st["overdue"])
        today=datetime.now().date()
        day=lambda n:(today+timedelta(days=n)).strftime("%Y-%m-%d")
        a=self.report("A",[{"key":"handover","date":day(3)},{"key":"draft_due","date":day(-2)},{"key":"review","date":day(-1)}])
        self.report("B",[{"key":"handover","date":day(1)},{"key":"kickoff","date":day(-30),"done":True}])
        f=self.report("F",[{"key":"handover","date":day(-10)}]);self.api.update(f["id"],{"status":"final"})
        st=self.api.stats()
        self.assertEqual({"report_id":a["id"],"title":"A","label":"Draft report","date":day(-2),"days_left":-2,"overdue":True},st["next_deadline"])
        self.assertEqual(2,st["overdue"])
        for k in ("reports","by_status","findings","open_findings","recent"):self.assertIn(k,st)
class ReminderTests(Base):
    def test_message_text(self):
        self.assertEqual("Hand-over for 'ACME External Pentest' is due tomorrow (2026-11-30)",schedule.reminder_message("ACME External Pentest","Hand-over","2026-11-30",1))
        self.assertEqual("Hand-over for 'X' is due today (2026-11-30 17:00)",schedule.reminder_message("X","Hand-over","2026-11-30",0,"17:00"))
        self.assertEqual("Draft report for 'X' is due in 3 days (2026-11-30)",schedule.reminder_message("X","Draft report","2026-11-30",3))
        self.assertEqual("Draft report for 'X' was due yesterday (2026-11-30)",schedule.reminder_message("X","Draft report","2026-11-30",-1))
        self.assertEqual("Milestone for 'Untitled report' was due 4 days ago (2026-11-30)",schedule.reminder_message("","","2026-11-30",-4))
    def test_fires_once_per_channel(self):
        rep=self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        due=schedule.due_reminders(TODAY,"app")
        self.assertEqual(1,len(due))
        r=due[0]
        self.assertEqual({"report_id","title","milestone","label","date","days_left","message","key","time","overdue"},set(r))
        self.assertEqual((rep["id"],"ACME External Pentest","Hand-over",d(1),1),(r["report_id"],r["title"],r["label"],r["date"],r["days_left"]))
        self.assertEqual(f"Hand-over for 'ACME External Pentest' is due tomorrow ({d(1)})",r["message"])
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        # the desktop notification is its own channel: it still fires once, and only once
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"os")))
        self.assertEqual([],schedule.due_reminders(TODAY,"os"))
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
    def test_not_due_yet_done_undated_or_without_reminders(self):
        self.report(milestones=[{"key":"handover","date":d(5),"remind":[{"days_before":3}]},{"key":"draft_due","date":d(0),"remind":[{"days_before":1}],"done":True},{"key":"review","date":"","remind":[{"days_before":1}]},{"key":"retest_start","date":d(0)}])
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        self.assertEqual(["Hand-over"],[r["label"] for r in schedule.due_reminders(TODAY+timedelta(days=2),"app")])
    def test_several_reminders_due_at_once_make_one_notification(self):
        self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":7},{"days_before":3},{"days_before":1}]}])
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app")))
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        self.assertEqual([],schedule.due_reminders(TODAY+timedelta(days=1),"app"))
    def test_each_reminder_of_a_milestone_fires_on_its_own_day(self):
        self.report(milestones=[{"key":"handover","date":d(7),"remind":[{"days_before":7},{"days_before":1}]}])
        self.assertEqual([7],[r["days_left"] for r in schedule.due_reminders(TODAY,"app")])
        self.assertEqual([],schedule.due_reminders(TODAY+timedelta(days=3),"app"))
        self.assertEqual([1],[r["days_left"] for r in schedule.due_reminders(TODAY+timedelta(days=6),"app")])
        self.assertEqual([],schedule.due_reminders(TODAY+timedelta(days=7),"app"))
        late=schedule.due_reminders(TODAY+timedelta(days=9),"app")
        self.assertEqual([-2],[r["days_left"] for r in late]);self.assertIn("was due 2 days ago",late[0]["message"])
        self.assertEqual([],schedule.due_reminders(TODAY+timedelta(days=12),"app"))
    def test_survives_a_restart_because_the_marker_is_in_the_database(self):
        rep=self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app")))
        fired=self.meta(rep["id"])["schedule_fired"]
        mid=rep["meta"]["schedule"]["milestones"][0]["id"]
        self.assertEqual([f"{mid}|{d(1)}|1"],list(fired))
        self.assertIn("app",fired[f"{mid}|{d(1)}|1"])
        # nothing is cached in the module: a fresh connection (as after a restart) reads the same state
        import importlib
        fresh=importlib.reload(schedule)
        self.assertEqual([],fresh.due_reminders(TODAY,"app"))
        self.assertFalse(any("schedule" in k for k in self._settings()))
    def _settings(self):
        import os
        p=os.path.join(common_db.data_dir(),"settings.json")
        if not os.path.isfile(p):return {}
        with open(p,encoding="utf-8") as f:return json.load(f)
    def test_skipped_quietly_while_locked(self):
        rep=self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        common_db.set_locked(True)
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        self.assertEqual([],schedule.due_reminders(TODAY,"os"))
        sent=[]
        self.assertEqual(0,schedule.notify_os(lambda t,m:sent.append(m),True,TODAY))
        self.assertEqual([],sent)
        common_db.set_locked(False)
        self.assertNotIn("schedule_fired",self.meta(rep["id"]))
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app")))
    def test_final_reports_do_not_remind(self):
        rep=self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        self.api.update(rep["id"],{"status":"final"})
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        self.api.update(rep["id"],{"status":"review"})
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app")))
    def test_page_saves_keep_the_markers_and_a_new_date_rearms(self):
        rep=self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        ms=rep["meta"]["schedule"]["milestones"]
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app")))
        # the page saves the schedule again (a note was typed): still delivered
        ms[0]["notes"]="bring the laptop"
        self.api.update(rep["id"],{"meta":{"schedule":{"milestones":ms}},"title":"Renamed"})
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        # moving the deadline is a new deadline
        ms[0]["date"]=d(2)
        self.api.update(rep["id"],{"meta":{"schedule":{"milestones":ms}}})
        self.assertEqual([],schedule.due_reminders(TODAY,"app"))
        again=schedule.due_reminders(TODAY+timedelta(days=1),"app")
        self.assertEqual(["Renamed"],[r["title"] for r in again])
        self.assertEqual(1,len(self.meta(rep["id"])["schedule_fired"]))
    def test_peek_does_not_mark(self):
        self.report(milestones=[{"key":"handover","date":d(0),"remind":[{"days_before":0}]}])
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app",mark=False)))
        self.assertEqual(1,len(schedule.due_reminders(TODAY,"app")))
    def test_duplicate_starts_with_fresh_reminders(self):
        rep=self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        schedule.due_reminders(TODAY,"app")
        copy=self.api.duplicate(rep["id"])
        self.assertNotIn("schedule_fired",self.meta(copy["id"]))
        self.assertEqual([copy["id"]],[r["report_id"] for r in schedule.due_reminders(TODAY,"app")])
    def test_notify_os_honours_the_setting_and_never_raises(self):
        self.report(milestones=[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        sent=[]
        self.assertEqual(0,schedule.notify_os(lambda t,m:sent.append((t,m)),False,TODAY))
        self.assertEqual([],sent)
        self.assertEqual(1,schedule.notify_os(lambda t,m:sent.append((t,m)),True,TODAY))
        self.assertEqual([("LOYA NG",f"Hand-over for 'ACME External Pentest' is due tomorrow ({d(1)})")],sent)
        self.assertEqual(0,schedule.notify_os(lambda t,m:sent.append((t,m)),True,TODAY))
        def boom(t,m):raise RuntimeError("no daemon")
        self.report("Other",[{"key":"handover","date":d(1),"remind":[{"days_before":1}]}])
        self.assertEqual(0,schedule.notify_os(boom,True,TODAY))
        # the in-app channel is independent of the desktop one
        self.assertEqual(2,len(schedule.due_reminders(TODAY,"app")))
    def test_bridge_reminders_due(self):
        today=datetime.now().date()
        self.report(milestones=[{"key":"handover","date":(today+timedelta(days=1)).strftime("%Y-%m-%d"),"remind":[{"days_before":1}]}])
        rows=self.api.reminders_due()
        self.assertEqual(1,len(rows));self.assertIn("is due tomorrow",rows[0]["message"])
        self.assertEqual([],self.api.reminders_due())
    def test_scheduler_hook(self):
        import LOYA_Note
        today=datetime.now().date()
        self.report(milestones=[{"key":"handover","date":(today+timedelta(days=1)).strftime("%Y-%m-%d"),"remind":[{"days_before":1}]}])
        sent=[];orig_send=LOYA_Note._os_toast.send;orig_get=LOYA_Note._get_notification_settings
        try:
            LOYA_Note._os_toast.send=lambda t,m,*a:sent.append(m) or True
            LOYA_Note._get_notification_settings=lambda:{"os_enabled":False}
            self.assertEqual(0,LOYA_Note._scheduled_report_reminders())
            LOYA_Note._get_notification_settings=lambda:{"os_enabled":True}
            common_db.set_locked(True)
            self.assertEqual(0,LOYA_Note._scheduled_report_reminders())
            common_db.set_locked(False)
            self.assertEqual(1,LOYA_Note._scheduled_report_reminders())
            self.assertEqual(0,LOYA_Note._scheduled_report_reminders())
        finally:
            LOYA_Note._os_toast.send=orig_send;LOYA_Note._get_notification_settings=orig_get
        self.assertEqual(1,len(sent));self.assertIn("Hand-over for 'ACME External Pentest' is due tomorrow",sent[0])
class SectionKindTests(Base):
    def test_new_kinds_are_registered(self):
        for k in ("risk_matrix","attack_narrative","project_timeline"):self.assertIn(k,reports.SECTION_KINDS)
        rep=self.report()
        got={k:self.api.section_add(rep["id"],{"kind":k}) for k in ("risk_matrix","attack_narrative","project_timeline")}
        self.assertEqual(("risk_matrix","Risk Matrix"),(got["risk_matrix"]["kind"],got["risk_matrix"]["title"]))
        self.assertEqual("Attack Narrative",got["attack_narrative"]["title"]);self.assertEqual("Project Timeline",got["project_timeline"]["title"])
        self.assertEqual(["risk_matrix","attack_narrative","project_timeline"],[s["kind"] for s in self.api.get(rep["id"])["sections"]][-3:])
    def test_attack_narrative_boilerplate_follows_the_kill_chain(self):
        text=self.api.section_boilerplate("attack_narrative")["content"]
        heads=["Initial access","Execution","Privilege escalation","Lateral movement","Objectives"]
        at=[text.index(f"<h3>{i+1}. {h}</h3>") for i,h in enumerate(heads)]
        self.assertEqual(sorted(at),at)
        self.assertIn("{{client}}",text);self.assertIn("MITRE ATT&amp;CK",text)
    def test_boilerplate_for_every_kind_is_clean_rich_html(self):
        for k in reports.SECTION_KINDS:
            bp=self.api.section_boilerplate(k)
            self.assertEqual({"kind","title","content","auto"},set(bp))
            self.assertEqual(k,bp["kind"]);self.assertTrue(bp["title"])
            self.assertEqual(bp["content"],reports.sanitize_html(bp["content"]),k)
            if k!="custom":self.assertTrue(bp["content"],k)
        self.assertEqual("",self.api.section_boilerplate("custom")["content"])
        self.assertEqual("custom",self.api.section_boilerplate("no_such_kind")["kind"])
    def test_auto_flags(self):
        auto={k for k in reports.SECTION_KINDS if self.api.section_boilerplate(k)["auto"]}
        self.assertEqual({"findings_summary","findings","remediation_roadmap","risk_matrix","project_timeline","document_control","appendix_commands","appendix_evidence","appendix_timeline"},auto)
        self.assertEqual(set(sections.AUTO_KINDS),auto)
    def test_section_add_without_content_uses_the_boilerplate(self):
        rep=self.report()
        sec=self.api.section_add(rep["id"],{"kind":"executive_summary","title":"Executive summary"})
        self.assertEqual(self.api.section_boilerplate("executive_summary")["content"],sec["content"])
        self.assertIn("Key findings",sec["content"])
        self.assertEqual("",self.api.section_add(rep["id"],{"kind":"executive_summary","content":""})["content"])
        self.assertEqual("<p>mine</p>",self.api.section_add(rep["id"],{"kind":"scope","content":"<p>mine</p>"})["content"])
        self.assertEqual("",self.api.section_add(rep["id"],{"kind":"custom","title":"Notes"})["content"])
    def test_methodology_boilerplate_follows_the_report_template(self):
        from Cores.Services import report_templates as tpl
        rep=self.api.create({"title":"Net","template_id":"internal_network"})
        self.assertEqual(tpl.METHODOLOGY["internal_network"],self.api.section_boilerplate("methodology",rep["id"])["content"])
        self.assertEqual(tpl.METHODOLOGY["internal_network"],self.api.section_add(rep["id"],{"kind":"methodology"})["content"])
        self.assertEqual(tpl.METHODOLOGY["web_app"],self.api.section_boilerplate("methodology")["content"])
        with self.assertRaises(ValueError):self.api.section_boilerplate("methodology",99999)
    def test_restoring_a_section_keeps_its_state(self):
        # what undo does after a delete: add again with the same content, hidden flag and place
        rep=self.api.create({"title":"T","template_id":"web_app"})
        secs=rep["sections"];victim=secs[2]
        self.api.section_update(victim["id"],{"hidden":True,"content":"<p>kept text</p>"})
        self.api.section_delete(victim["id"])
        back=self.api.section_add(rep["id"],{"kind":victim["kind"],"title":victim["title"],"content":"<p>kept text</p>","hidden":True,"options":{},"after_id":secs[1]["id"]})
        now=self.api.get(rep["id"])["sections"]
        self.assertEqual(2,[s["id"] for s in now].index(back["id"]))
        self.assertEqual(("<p>kept text</p>",True,victim["title"]),(back["content"],back["hidden"],back["title"]))
        first=self.api.section_add(rep["id"],{"kind":"custom","title":"First","after_id":0})
        self.assertEqual(first["id"],self.api.get(rep["id"])["sections"][0]["id"])
    def test_restoring_a_finding_keeps_its_content(self):
        rep=self.report()
        a=self.api.finding_add(rep["id"],{"title":"A"})
        b=self.api.finding_add(rep["id"],{"title":"B","severity":"high","status":"retest","cvss_vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","description":"<p>d</p>","affected":[{"target_id":"","name":"web","value":"10.0.0.5"}],"tags":["x"],"retest_notes":"again","references":["https://example.com/a"]})
        c=self.api.finding_add(rep["id"],{"title":"C"})
        self.api.finding_delete(b["id"])
        fields={k:v for k,v in b.items() if k not in ("id","uid","report_id","position","created_at","updated_at","cvss_score")}
        back=self.api.finding_add(rep["id"],fields)
        self.api.findings_reorder(rep["id"],[a["id"],back["id"],c["id"]])
        now=self.api.get(rep["id"])["findings"]
        self.assertEqual(["A","B","C"],[f["title"] for f in now])
        for k in fields:self.assertEqual(b[k],now[1][k],k)
        self.assertEqual(b["cvss_score"],now[1]["cvss_score"])
class ToastTextTests(unittest.TestCase):
    def test_titles_are_cleaned_for_os_notifications(self):
        from Cores.Services import report_schedule as rs
        msg=rs.reminder_message("ACME\x00\x1b[31m\r\n‮gnp.exe⁦ "+"A"*300,"Hand\x07over‏","2026-11-30",1)
        for ch in msg:self.assertFalse(ord(ch)<32 or 0x7f<=ord(ch)<=0x9f or ch in "‮⁦‏",repr(ch))
        self.assertLess(len(msg),220)
        self.assertIn("…",msg)
if __name__=="__main__":unittest.main()
