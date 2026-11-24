"""Chain Diagrams executor: branching, loops, limits, timeouts, stop/pause/approval, dry runs, sub-chains and the lock."""
import os,sys,subprocess,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from _flow_helpers import WINDOWS,PY,slow,node,cmd,graph,set_live_target,wait_until
from Cores import common_db
from Cores.Services import flow_engine as engine
from Cores.Services import flow_rules as rules
from Cores.Services import flow_store as store
from Cores.Services import terminal_service as terminal
from Cores.Services import security_service as security
def jobs_of(run_id):
    status=terminal.chain_status(run_id)
    return status["steps"] if status else []
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.started=[]
    def tearDown(self):
        common_db.set_locked(False)
        for run in self.started:
            run.stop("test teardown")
            run.finished.wait(10)
        engine._runs.clear();del engine._unsaved[:]
        terminal.clear_batch_output()
        self.iso.stop()
    def start(self,g,**kw):
        kw.setdefault("name","Test chain")
        run=engine.start_run(g,**kw)
        self.started.append(run)
        return run
    def run_graph(self,g,timeout=40,**kw):
        run=self.start(g,**kw)
        self.assertTrue(run.finished.wait(timeout),"the run did not finish: %r"%run.status()["state"])
        return run.status()
    def states(self,status):
        return {k:v["state"] for k,v in status["nodes"].items()}
    def audit(self,event):
        return [e for e in security.list_audit_events(500) if e["event"]==event]
class CommandTests(Base):
    def test_commands_run_in_order_through_the_job_system(self):
        status=self.run_graph(graph([cmd("a","echo one"),cmd("b","echo two")],["start.out>a","a.success>b"]),playbook_id=7)
        self.assertEqual("done",status["state"])
        self.assertEqual({"start":"success","a":"success","b":"success"},self.states(status))
        self.assertEqual("one",status["nodes"]["a"]["output"]["stdout"].strip())
        self.assertEqual(["e1","e2"],status["edges_taken"])
        jobs=jobs_of(status["run_id"])
        self.assertEqual(["echo one","echo two"],[j["command"] for j in jobs])
        self.assertEqual(["done","done"],[j["state"] for j in jobs])
        self.assertEqual({"flow"},{j["source"] for j in jobs})
        self.assertEqual({"Test chain"},{j["chain_name"] for j in jobs})
        self.assertEqual([jobs[0]["job_key"]],status["nodes"]["a"]["job_keys"])
        self.assertIn("one",terminal.batch_output(jobs[0]["job_key"]))
        self.assertLessEqual(jobs[0]["ended_at"],jobs[1]["started_at"])
    def test_stderr_is_captured_apart_from_stdout(self):
        status=self.run_graph(graph([cmd("a","echo good; echo bad 1>&2")],["start.out>a"]))
        out=status["nodes"]["a"]["output"]
        self.assertEqual(("good","bad",0),(out["stdout"].strip(),out["stderr"].strip(),out["exit_code"]))
        text=terminal.batch_output(status["nodes"]["a"]["job_keys"][0])
        self.assertIn("good",text);self.assertIn("[stderr]",text);self.assertIn("bad",text)
    def test_every_command_and_the_run_are_audited(self):
        status=self.run_graph(graph([cmd("a","echo audited-line")],["start.out>a"]),playbook_id=3)
        commands=[e["detail"] for e in self.audit("terminal_command")]
        self.assertTrue(any(d.startswith("flow:chain:") and "echo audited-line" in d for d in commands),commands)
        starts=[e["detail"] for e in self.audit("chain_run_start")]
        ends=self.audit("chain_run_end")
        self.assertTrue(any(status["run_id"] in d and "chain 3" in d for d in starts))
        self.assertTrue(any(status["run_id"] in e["detail"] and e["detail"].endswith("done") and e["success"] for e in ends))
    def test_secrets_are_redacted_in_the_audit_log_for_every_kind_of_command(self):
        child=graph([cmd("c1","echo child --password=Ch1ldSecret99")],["start.out>c1"])
        parent=graph([cmd("a","echo one --password=Sup3rSecret99"),cmd("p","echo p1 --password=ParaSecret11","echo p2 --password=ParaSecret22",mode="parallel"),node("sub","subchain",playbook_id=2)],["start.out>a","a.success>p","p.success>sub"])
        status=self.run_graph(parent,playbook_id=1,loader=lambda pid:{"name":"child","graph":child})
        self.assertEqual("done",status["state"],status["nodes"])
        details=[e["detail"] for e in self.audit("terminal_command")]
        self.assertEqual(4,len(details))
        text="\n".join(details)
        for word in ("echo one","echo p1","echo p2","echo child"):self.assertIn(word,text)
        for secret in ("Sup3rSecret99","ParaSecret11","ParaSecret22","Ch1ldSecret99"):self.assertNotIn(secret,text)
        self.assertEqual(4,text.count("[redacted]"))
    def test_the_source_names_the_caller(self):
        status=self.run_graph(graph([cmd("a","echo hi")],["start.out>a"]),source="caller")
        self.assertEqual({"flow-caller"},{j["source"] for j in jobs_of(status["run_id"])})
        status=self.run_graph(graph([cmd("a","echo hi")],["start.out>a"]),source="ai")
        self.assertEqual({"flow-ai"},{j["source"] for j in jobs_of(status["run_id"])})
        self.assertEqual("ai",status["source"])
    def test_a_failing_command_takes_the_fail_port(self):
        status=self.run_graph(graph([cmd("a","exit 3"),cmd("ok","echo ok"),cmd("bad","echo handled")],["start.out>a","a.success>ok","a.fail>bad"]))
        self.assertEqual("done",status["state"])
        self.assertEqual({"start":"success","a":"fail","ok":"skipped","bad":"success"},self.states(status))
        self.assertEqual(3,status["nodes"]["a"]["output"]["exit_code"])
        self.assertEqual("fail",status["nodes"]["a"]["branch"])
    def test_an_unhandled_failure_stops_the_run(self):
        status=self.run_graph(graph([cmd("a","exit 1"),cmd("b","echo never")],["start.out>a","a.success>b"]))
        self.assertEqual("failed",status["state"])
        self.assertIn("failed",status["reason"])
        self.assertEqual("skipped",status["nodes"]["b"]["state"])
        self.assertFalse(self.audit("chain_run_end")[0]["success"])
    def test_on_error_continue_keeps_going(self):
        g=graph([cmd("a","exit 1"),cmd("b","echo second")],["start.out>a","start.out>b"],on_error="continue")
        status=self.run_graph(g)
        self.assertEqual("done",status["state"])
        self.assertIn("1 node(s) failed",status["reason"])
        self.assertEqual({"a":"fail","b":"success"},{k:self.states(status)[k] for k in ("a","b")})
    def test_sequence_stops_at_the_first_failure_unless_told_otherwise(self):
        status=self.run_graph(graph([cmd("a","echo one","exit 2","echo three"),cmd("h","echo handled")],["start.out>a","a.fail>h"]))
        self.assertEqual(["echo one","exit 2"],status["nodes"]["a"]["output"]["resolved"][:2])
        self.assertEqual(2,len(status["nodes"]["a"]["job_keys"]))
        status=self.run_graph(graph([cmd("a","echo one","exit 2","echo three",stop_on_fail=False),cmd("h","echo handled")],["start.out>a","a.fail>h"]))
        self.assertEqual(3,len(status["nodes"]["a"]["job_keys"]))
        self.assertIn("three",status["nodes"]["a"]["output"]["stdout"])
        self.assertEqual("fail",status["nodes"]["a"]["state"])
    def test_parallel_commands_all_run(self):
        started=time.time()
        status=self.run_graph(graph([cmd("a","sleep 1; echo p1","sleep 1; echo p2","sleep 1; echo p3",mode="parallel")],["start.out>a"]))
        self.assertEqual("done",status["state"])
        self.assertLess(time.time()-started,2.8)
        for word in ("p1","p2","p3"):self.assertIn(word,status["nodes"]["a"]["output"]["stdout"])
        self.assertEqual(3,len(status["nodes"]["a"]["job_keys"]))
    def test_several_edges_from_one_port_run_in_edge_order(self):
        status=self.run_graph(graph([cmd("a","echo first"),cmd("b","echo second")],["start.out>a","start.out>b"]))
        self.assertEqual(["echo first","echo second"],[j["command"] for j in jobs_of(status["run_id"])])
class TemplateTests(Base):
    def test_placeholders_come_from_the_live_target(self):
        set_live_target({"IPv4":"127.0.0.1","Port":"8080"},"web01")
        status=self.run_graph(graph([cmd("a","echo host={IPv4} port={Port}")],["start.out>a"]))
        self.assertEqual("web01",status["target"])
        self.assertEqual(["echo host=127.0.0.1 port=8080"],status["nodes"]["a"]["output"]["resolved"])
        self.assertIn("host=127.0.0.1 port=8080",status["nodes"]["a"]["output"]["stdout"])
    def test_an_unfilled_placeholder_fails_the_node_and_runs_nothing(self):
        status=self.run_graph(graph([cmd("a","echo {NoSuchValue}")],["start.out>a"]))
        self.assertEqual("failed",status["state"])
        self.assertIn("{NoSuchValue}",status["nodes"]["a"]["error"])
        self.assertEqual([],jobs_of(status["run_id"]))
    @unittest.skipIf(WINDOWS,"POSIX quoting")
    def test_flow_values_are_shell_quoted_in_commands(self):
        g=graph([node("v","set",assign=[{"var":"x","value":"a; echo INJECTED $(id) `id`"}]),cmd("a","echo ${x}"),cmd("b",'echo "${x}"')],["start.out>v","v.out>a","a.success>b"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["nodes"]["a"])
        self.assertEqual("a; echo INJECTED $(id) `id`",status["nodes"]["a"]["output"]["stdout"].strip())
        self.assertEqual("a; echo INJECTED $(id) `id`",status["nodes"]["b"]["output"]["stdout"].strip())
        self.assertEqual(2,len(jobs_of(status["run_id"])))
    @unittest.skipIf(WINDOWS,"POSIX quoting")
    def test_a_target_value_cannot_smuggle_in_a_flow_token_and_a_flow_value_is_not_a_placeholder(self):
        set_live_target({"IPv4":"${secret}","Name":"filled"})
        g=graph([node("v","set",assign=[{"var":"secret","value":"TOPSECRET"},{"var":"x","value":"{Name}"}]),cmd("a","echo {IPv4} ${x}")],["start.out>v","v.out>a"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["nodes"]["a"])
        out=status["nodes"]["a"]["output"]["stdout"]
        self.assertNotIn("TOPSECRET",out)
        self.assertIn("{Name}",out);self.assertNotIn("filled",out)
    def test_resolve_command_reports_missing_and_keeps_tokens_for_plans(self):
        set_live_target({"IPv4":"10.0.0.5"})
        _name,_values,replacer=engine.live_target()
        resolved,missing,_w=engine.resolve_command("nmap {IPv4} -p ${port} {Domain}",replacer,keep_tokens=True)
        self.assertEqual(("nmap 10.0.0.5 -p ${port} {Domain}",["Domain"]),(resolved,missing))
        resolved,missing,warns=engine.resolve_command("nmap {IPv4} -p ${port}",replacer,{"vars":{"port":"80"}},rules.shell_quoter("shell"))
        self.assertEqual(("nmap 10.0.0.5 -p 80",[],[]),(resolved,missing,warns))
        resolved,_m,warns=engine.resolve_command("echo ${nope}",replacer,{"vars":{}},rules.shell_quoter("shell"))
        self.assertTrue(warns)
    @unittest.skipIf(WINDOWS,"POSIX quoting")
    def test_raw_is_only_allowed_for_literal_set_variables(self):
        g=graph([node("v","set",assign=[{"var":"flags","value":"-n  two words"}]),cmd("a","echo ${raw:flags}")],["start.out>v","v.out>a"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["nodes"]["a"])
        self.assertEqual(["echo -n  two words"],status["nodes"]["a"]["output"]["resolved"])
    def test_raw_is_refused_for_values_that_came_from_output_scripts_or_loops(self):
        derived=graph([cmd("a","echo '; echo INJECTED'"),node("v","set",assign=[{"var":"x","value":"${last.stdout}"}]),cmd("b","echo ${raw:x}")],["start.out>a","a.success>v","v.out>b"])
        scripted=graph([node("s","script",language="python",code='print(\'{"vars":{"x":"; echo INJECTED"}}\')\n',branches=["out"]),cmd("b","echo ${raw:x}")],["start.out>s","s.out>b"])
        looped=graph([node("v","set",assign=[{"var":"list","value":"a,b"}]),node("f","foreach",items="${list}",split="comma",item_var="x"),cmd("b","echo ${raw:x}")],["start.out>v","v.out>f","f.item>b"])
        parsed=graph([cmd("a","echo port=80"),node("p","parse",mode="regex",source="stdout",pattern=r"port=(\d+)",assign=[{"var":"x","from":"group:1"}]),cmd("b","echo ${raw:x}")],["start.out>a","a.success>p","p.out>b"])
        direct=graph([cmd("a","echo hi"),cmd("b","echo ${raw:last.stdout}")],["start.out>a","a.success>b"])
        for name,g in (("derived",derived),("scripted",scripted),("looped",looped),("parsed",parsed),("direct",direct)):
            status=self.run_graph(g,variables={"x":"seeded"})
            self.assertEqual("failed",status["state"],name)
            self.assertEqual("fail",status["nodes"]["b"]["state"],name)
            self.assertIn("${raw:",status["nodes"]["b"]["error"],name)
            self.assertEqual([],status["nodes"]["b"]["job_keys"],name)
    def test_a_literal_variable_loses_its_trust_when_it_is_overwritten(self):
        g=graph([node("v","set",assign=[{"var":"x","value":"safe"}]),node("w","set",assign=[{"var":"x","value":"${target.ipv4}"}]),cmd("b","echo ${raw:x}")],["start.out>v","v.out>w","w.out>b"])
        self.assertEqual("failed",self.run_graph(g)["state"])
    def test_resolve_command_refuses_raw_without_an_approver(self):
        with self.assertRaises(rules.RuleError):engine.resolve_command("echo ${raw:x}",None,{"vars":{"x":"1"}},rules.shell_quoter("shell"))
        self.assertEqual("echo 1",engine.resolve_command("echo ${raw:x}",None,{"vars":{"x":"1"}},rules.shell_quoter("shell"),raw_ok=lambda name:name=="x")[0])
        self.assertEqual(["x"],engine.raw_names("a ${raw:x} $${raw:y} ${z}"))
    def test_last_and_nodes_are_usable_in_templates(self):
        g=graph([cmd("a","echo alpha"),node("v","set",assign=[{"var":"seen","value":"${last.stdout}"},{"var":"code","value":"${nodes.a.exit_code}"}])],["start.out>a","a.success>v"])
        status=self.run_graph(g)
        self.assertEqual("alpha",status["vars"]["seen"].strip())
        self.assertEqual("0",status["vars"]["code"])
        self.assertEqual({"seen","code"},set(status["nodes"]["v"]["output"]["vars_set"]))
class BranchingTests(Base):
    def decision_graph(self,first):
        alive=node("d","decision",branches=[{"name":"alive","match":"all","conditions":[{"source":"output","op":"contains","value":"ttl="}]}],**{"else":"down"})
        return graph([cmd("ping",first),alive,cmd("up","echo is-up"),cmd("dn","echo is-down")],["start.out>ping","ping.success>d","d.alive>up","d.down>dn"])
    def test_a_decision_picks_the_matching_branch(self):
        status=self.run_graph(self.decision_graph("echo 64 bytes from host ttl=63"))
        self.assertEqual("alive",status["nodes"]["d"]["branch"])
        self.assertEqual(("success","skipped"),(status["nodes"]["up"]["state"],status["nodes"]["dn"]["state"]))
        self.assertIn("e3",status["edges_taken"]);self.assertNotIn("e4",status["edges_taken"])
        trace=status["nodes"]["d"]["output"]["trace"]
        self.assertTrue(trace[0]["matched"])
    def test_a_decision_falls_through_to_else(self):
        status=self.run_graph(self.decision_graph("echo request timed out"))
        self.assertEqual("down",status["nodes"]["d"]["branch"])
        self.assertEqual(("skipped","success"),(status["nodes"]["up"]["state"],status["nodes"]["dn"]["state"]))
    def test_a_decision_on_the_exit_code(self):
        d=node("d","decision",branches=[{"name":"zero","match":"all","conditions":[{"source":"exit_code","op":"eq","value":"0"}]}],**{"else":"nonzero"})
        g=graph([cmd("a","exit 4"),d,cmd("z","echo zero"),cmd("n","echo nonzero")],["start.out>a","a.fail>d","d.zero>z","d.nonzero>n"])
        status=self.run_graph(g)
        self.assertEqual("nonzero",status["nodes"]["d"]["branch"])
    def test_parse_feeds_variables_and_a_decision(self):
        p=node("p","parse",mode="regex",source="stdout",pattern=r"port=(\d+)",flags="i",assign=[{"var":"port","from":"group:1"}],var="m")
        d=node("d","decision",branches=[{"name":"web","match":"all","conditions":[{"source":"var","field":"port","op":"eq","value":"8080"}]}],**{"else":"other"})
        g=graph([cmd("a","echo service port=8080"),p,d,cmd("w","echo web ${port}"),cmd("o","echo other")],["start.out>a","a.success>p","p.out>d","d.web>w","d.other>o"])
        status=self.run_graph(g)
        self.assertEqual("8080",status["vars"]["port"])
        self.assertEqual("web",status["nodes"]["d"]["branch"])
        self.assertEqual("web 8080",status["nodes"]["w"]["output"]["stdout"].strip())
    def test_parse_without_a_match_takes_nomatch(self):
        p=node("p","parse",mode="regex",source="stdout",pattern=r"port=(\d+)")
        g=graph([cmd("a","echo nothing here"),p,cmd("y","echo yes"),cmd("n","echo no")],["start.out>a","a.success>p","p.out>y","p.nomatch>n"])
        status=self.run_graph(g)
        self.assertEqual(("nomatch","skipped","success"),(status["nodes"]["p"]["branch"],status["nodes"]["y"]["state"],status["nodes"]["n"]["state"]))
    def test_end_node_stops_the_run_with_its_status(self):
        g=graph([cmd("a","echo one"),node("e","end",status="fail",message="gave up"),cmd("b","echo never")],["start.out>a","a.success>e","start.out>b"])
        status=self.run_graph(g)
        self.assertEqual(("failed","gave up"),(status["state"],status["reason"]))
        self.assertEqual("skipped",status["nodes"]["b"]["state"])
        g=graph([node("e","end",status="success")],["start.out>e"])
        self.assertEqual("done",self.run_graph(g)["state"])
class ScriptTests(Base):
    CHOOSE='import json,sys\ndata=json.load(sys.stdin)\nout=data["input"].get("stdout","")\nprint(json.dumps({"branch":"big" if "42" in out else "small","vars":{"seen":out.strip(),"n":7}}))\n'
    def script_graph(self,first,code=None,**config):
        s=node("s","script",language="python",code=code or self.CHOOSE,branches=["big","small"],**config)
        return graph([cmd("a",first),s,cmd("b","echo took-big ${n}"),cmd("c","echo took-small"),cmd("e","echo script-error")],["start.out>a","a.success>s","s.big>b","s.small>c","s.error>e"])
    def test_a_script_chooses_the_branch_and_sets_variables(self):
        status=self.run_graph(self.script_graph("echo 42"))
        self.assertEqual("done",status["state"],status["nodes"]["s"])
        self.assertEqual("big",status["nodes"]["s"]["branch"])
        self.assertEqual({"seen":"42","n":7},status["nodes"]["s"]["output"]["vars_set"])
        self.assertEqual("took-big 7",status["nodes"]["b"]["output"]["stdout"].strip())
        self.assertEqual("skipped",status["nodes"]["c"]["state"])
        status=self.run_graph(self.script_graph("echo 7"))
        self.assertEqual("small",status["nodes"]["s"]["branch"])
    def test_a_failing_script_takes_the_error_port(self):
        status=self.run_graph(self.script_graph("echo 1","import sys\nsys.stderr.write('boom')\nsys.exit(5)\n"))
        self.assertEqual(("fail","error"),(status["nodes"]["s"]["state"],status["nodes"]["s"]["branch"]))
        self.assertEqual("success",status["nodes"]["e"]["state"])
        self.assertIn("boom",status["nodes"]["s"]["output"]["stderr"])
    def test_an_unknown_branch_falls_back_to_the_first(self):
        status=self.run_graph(self.script_graph("echo 1",'print(\'{"branch":"nowhere"}\')\n'))
        self.assertEqual("big",status["nodes"]["s"]["branch"])
        self.assertTrue(any(e["level"]=="warn" and "nowhere" in e["text"] for e in status["events"]))
    def test_a_script_times_out(self):
        started=time.time()
        status=self.run_graph(self.script_graph("echo 1","import time\ntime.sleep(30)\n",timeout=1))
        self.assertLess(time.time()-started,15)
        self.assertEqual("error",status["nodes"]["s"]["branch"])
        self.assertIn("timed out",status["nodes"]["s"]["error"])
    def test_script_output_says_how_it_was_contained(self):
        status=self.run_graph(self.script_graph("echo 42"))
        out=status["nodes"]["s"]["output"]
        self.assertIn(out["sandbox"],("bwrap","none"))
        self.assertIn("network",out)
    def test_a_script_run_is_audited(self):
        self.run_graph(self.script_graph("echo 42"))
        self.assertTrue(any("[script:python]" in e["detail"] for e in self.audit("terminal_command")))
class LoopTests(Base):
    def test_for_each_runs_the_body_once_per_item_then_done(self):
        f=node("f","foreach",items="${list}",split="comma",max_items=50)
        g=graph([node("v","set",assign=[{"var":"list","value":"a,b,c"}]),f,cmd("body","echo item=${item} index=${index}"),cmd("after","echo finished")],["start.out>v","v.out>f","f.item>body","f.done>after"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"])
        self.assertEqual(3,status["nodes"]["body"]["visits"])
        self.assertEqual(1,status["nodes"]["after"]["visits"])
        commands=[j["command"] for j in jobs_of(status["run_id"])]
        self.assertEqual(["echo item=a index=0","echo item=b index=1","echo item=c index=2","echo finished"],commands)
    def test_for_each_respects_max_items(self):
        f=node("f","foreach",items="${list}",split="comma",max_items=2)
        g=graph([node("v","set",assign=[{"var":"list","value":"a,b,c,d,e"}]),f,cmd("body","echo ${item}")],["start.out>v","v.out>f","f.item>body"])
        status=self.run_graph(g)
        self.assertEqual(2,status["nodes"]["body"]["visits"])
        self.assertTrue(any(e["level"]=="warn" and "only the first 2" in e["text"] for e in status["events"]))
    def test_for_each_over_parsed_lines_and_an_empty_list(self):
        p=node("p","parse",mode="tool",tool="lines",source="stdout",var="rows")
        f=node("f","foreach",items="${last.stdout}",split="lines")
        g=graph([cmd("a","echo x; echo y"),f,cmd("body","echo got-${item}"),cmd("after","echo end")],["start.out>a","a.success>f","f.item>body","f.done>after"])
        status=self.run_graph(g)
        self.assertEqual(2,status["nodes"]["body"]["visits"])
        f=node("f","foreach",items="${nothing}",split="lines")
        g=graph([f,cmd("body","echo never"),cmd("after","echo end")],["start.out>f","f.item>body","f.done>after"])
        status=self.run_graph(g)
        self.assertEqual(("skipped","success"),(status["nodes"]["body"]["state"],status["nodes"]["after"]["state"]))
    def test_a_cycle_is_cut_by_the_visit_limit(self):
        g=graph([node("a","set",assign=[{"var":"x","value":"1"}]),node("b","set",assign=[{"var":"y","value":"2"}])],["start.out>a","a.out>b","b.out>a"],max_visits=9)
        status=self.run_graph(g)
        self.assertEqual("failed",status["state"])
        self.assertIn("Visit limit reached (9",status["reason"])
        self.assertEqual(9,sum(v["visits"] for v in status["nodes"].values()))
    def test_one_node_cannot_run_more_than_fifty_times(self):
        g=graph([node("a","set",assign=[{"var":"x","value":"1"}]),node("b","set",assign=[{"var":"y","value":"2"}])],["start.out>a","a.out>b","b.out>a"],max_visits=2000)
        status=self.run_graph(g)
        self.assertEqual("failed",status["state"])
        self.assertIn("50 times",status["reason"])
        self.assertEqual(engine.MAX_NODE_VISITS,status["nodes"]["a"]["visits"])
class TimeoutTests(Base):
    def test_a_node_timeout_kills_the_command_and_takes_the_fail_port(self):
        started=time.time()
        g=graph([cmd("a",slow(30),timeout=1),cmd("h","echo handled")],["start.out>a","a.fail>h"])
        status=self.run_graph(g)
        self.assertLess(time.time()-started,12)
        self.assertEqual("done",status["state"])
        self.assertEqual("fail",status["nodes"]["a"]["state"])
        self.assertIn("Timed out",status["nodes"]["a"]["error"])
        self.assertEqual("success",status["nodes"]["h"]["state"])
        self.assertEqual("killed",jobs_of(status["run_id"])[0]["state"])
        self.assertNotIn("never",status["nodes"]["a"]["output"]["stdout"])
    def test_the_run_timeout_ends_the_run(self):
        g=graph([cmd("a",slow(30)),cmd("b","echo never")],["start.out>a","a.success>b"])
        g["settings"]["run_timeout"]=1
        started=time.time()
        status=self.run_graph(g)
        self.assertLess(time.time()-started,12)
        self.assertEqual("timeout",status["state"])
        self.assertEqual("skipped",status["nodes"]["b"]["state"])
        self.assertEqual("killed",jobs_of(status["run_id"])[0]["state"])
    def test_time_spent_waiting_for_an_approval_does_not_count(self):
        g=graph([node("ask","approval",message="ok?"),cmd("a","echo after")],["start.out>ask","ask.approved>a"])
        g["settings"]["run_timeout"]=1
        run=self.start(g)
        self.assertTrue(wait_until(lambda:run.status()["state"]=="waiting_approval"))
        time.sleep(1.6)
        self.assertEqual("waiting_approval",run.status()["state"])
        run.approve("ask",True)
        self.assertTrue(run.finished.wait(10))
        self.assertEqual("done",run.status()["state"])
    def test_wait_node_waits_and_can_be_stopped(self):
        g=graph([node("w","wait",seconds=1),cmd("a","echo after")],["start.out>w","w.out>a"])
        started=time.time()
        status=self.run_graph(g)
        self.assertGreaterEqual(time.time()-started,0.9)
        self.assertEqual("done",status["state"])
        run=self.start(graph([node("w","wait",seconds=600),cmd("a","echo after")],["start.out>w","w.out>a"]))
        self.assertTrue(wait_until(lambda:run.status()["nodes"]["w"]["state"]=="running"))
        run.stop()
        self.assertTrue(run.finished.wait(5))
        self.assertEqual("cancelled",run.status()["state"])
class ControlTests(Base):
    def test_stop_kills_the_whole_process_tree(self):
        marker="317.%d"%(os.getpid()%1000)
        text=slow(30) if WINDOWS else "sleep %s; echo never"%marker
        run=self.start(graph([cmd("a",text),cmd("b","echo never")],["start.out>a","a.success>b"]))
        self.assertTrue(wait_until(lambda:bool(run.status()["nodes"]["a"]["job_keys"])))
        if not WINDOWS:self.assertTrue(wait_until(lambda:subprocess.run(["pgrep","-f","sleep "+marker],stdout=subprocess.DEVNULL).returncode==0))
        started=time.time()
        self.assertTrue(run.stop("stopped by the operator"))
        self.assertTrue(run.finished.wait(10))
        self.assertLess(time.time()-started,8)
        status=run.status()
        self.assertEqual(("cancelled","stopped by the operator"),(status["state"],status["reason"]))
        self.assertEqual("skipped",status["nodes"]["b"]["state"])
        self.assertEqual("killed",jobs_of(status["run_id"])[0]["state"])
        if not WINDOWS:self.assertTrue(wait_until(lambda:subprocess.run(["pgrep","-f","sleep "+marker],stdout=subprocess.DEVNULL).returncode!=0,5),"the sleeping child survived the stop")
        self.assertFalse(run.stop())
        self.assertEqual("cancelled",store.get_run(status["run_id"])["state"])
    def test_stop_all(self):
        run=self.start(graph([cmd("a",slow(30))],["start.out>a"]))
        self.assertTrue(wait_until(lambda:bool(run.status()["nodes"]["a"]["job_keys"])))
        self.assertEqual(1,len(engine.active_runs()))
        self.assertEqual(1,engine.stop_all("app closing"))
        self.assertTrue(run.finished.wait(10))
        self.assertEqual([],engine.active_runs())
    def test_pause_holds_between_nodes_and_resume_continues(self):
        run=self.start(graph([cmd("a","sleep 1; echo one"),cmd("b","echo two")],["start.out>a","a.success>b"]))
        self.assertTrue(wait_until(lambda:run.status()["nodes"]["a"]["state"]=="running"))
        self.assertFalse(run.status()["pausing"])
        self.assertTrue(run.pause())
        self.assertFalse(run.pause())
        early=run.status()
        self.assertEqual(("running",True,"running"),(early["state"],early["pausing"],early["nodes"]["a"]["state"]))
        self.assertTrue(wait_until(lambda:run.status()["nodes"]["a"]["state"]=="success"))
        self.assertTrue(wait_until(lambda:run.status()["state"]=="paused"))
        time.sleep(0.4)
        status=run.status()
        self.assertEqual(("paused",False),(status["state"],status["pausing"]))
        self.assertEqual("pending",status["nodes"]["b"]["state"])
        self.assertTrue(run.resume())
        self.assertTrue(run.finished.wait(10))
        self.assertEqual(("done","success",False),(run.status()["state"],run.status()["nodes"]["b"]["state"],run.status()["pausing"]))
        self.assertFalse(run.resume())
    def test_a_pause_can_be_taken_back_before_the_node_ends(self):
        run=self.start(graph([cmd("a","sleep 1; echo one"),cmd("b","echo two")],["start.out>a","a.success>b"]))
        self.assertTrue(wait_until(lambda:run.status()["nodes"]["a"]["state"]=="running"))
        self.assertTrue(run.pause())
        self.assertTrue(run.resume())
        self.assertEqual(("running",False),(run.status()["state"],run.status()["pausing"]))
        self.assertTrue(run.finished.wait(10))
        self.assertEqual("done",run.status()["state"])
    def test_a_paused_run_can_be_stopped(self):
        run=self.start(graph([cmd("a","echo one"),node("w","wait",seconds=1),cmd("b","echo two")],["start.out>a","a.success>w","w.out>b"]))
        run.pause()
        time.sleep(0.5)
        run.stop()
        self.assertTrue(run.finished.wait(10))
        self.assertEqual("cancelled",run.status()["state"])
    def approval_graph(self,**config):
        return graph([node("ask","approval",message="Launch ${what}?",**config),cmd("y","echo approved"),cmd("n","echo rejected")],["start.out>ask","ask.approved>y","ask.rejected>n"])
    def test_approval_blocks_until_approved(self):
        run=self.start(self.approval_graph(),variables={"what":"the exploit"})
        self.assertTrue(wait_until(lambda:run.status()["state"]=="waiting_approval"))
        status=run.status()
        self.assertEqual({"node":"ask","message":"Launch the exploit?"},status["approval"])
        self.assertEqual("waiting",status["nodes"]["ask"]["state"])
        time.sleep(0.4)
        self.assertEqual("pending",run.status()["nodes"]["y"]["state"])
        self.assertFalse(run.approve("someone-else",True))
        self.assertTrue(run.approve("ask",True))
        self.assertTrue(run.finished.wait(10))
        status=run.status()
        self.assertIsNone(status["approval"])
        self.assertEqual(("approved","success","skipped"),(status["nodes"]["ask"]["branch"],status["nodes"]["y"]["state"],status["nodes"]["n"]["state"]))
        events=self.audit("chain_run_approval")
        self.assertTrue(events and "approved" in events[0]["detail"] and events[0]["success"])
    def test_approval_rejected(self):
        run=self.start(self.approval_graph())
        self.assertTrue(wait_until(lambda:run.status()["state"]=="waiting_approval"))
        self.assertTrue(run.approve("ask",False))
        self.assertTrue(run.finished.wait(10))
        status=run.status()
        self.assertEqual("done",status["state"])
        self.assertEqual(("rejected","skipped","success"),(status["nodes"]["ask"]["branch"],status["nodes"]["y"]["state"],status["nodes"]["n"]["state"]))
        self.assertFalse(self.audit("chain_run_approval")[0]["success"])
    def test_approval_times_out_as_rejected(self):
        status=self.run_graph(self.approval_graph(timeout=1))
        self.assertEqual("rejected",status["nodes"]["ask"]["branch"])
    def test_a_waiting_approval_can_be_stopped(self):
        run=self.start(self.approval_graph())
        self.assertTrue(wait_until(lambda:run.status()["state"]=="waiting_approval"))
        run.stop()
        self.assertTrue(run.finished.wait(5))
        self.assertEqual("cancelled",run.status()["state"])
        self.assertEqual([],self.audit("chain_run_approval"))
    def test_status_since_only_sends_the_output_of_nodes_that_changed(self):
        run=self.start(graph([cmd("a","echo first"),node("ask","approval",message="go?"),cmd("b","echo second")],["start.out>a","a.success>ask","ask.approved>b"]))
        self.assertTrue(wait_until(lambda:run.status()["state"]=="waiting_approval"))
        full=run.status()
        self.assertEqual({"start","a","ask","b"},set(full["nodes"]))
        self.assertTrue(all("output" in rec and "seq" in rec for rec in full["nodes"].values()))
        self.assertIn("first",full["nodes"]["a"]["output"]["stdout"])
        self.assertEqual(0,full["nodes"]["b"]["seq"])
        self.assertGreaterEqual(full["seq"],full["nodes"]["ask"]["seq"])
        quiet=run.status(since=full["seq"])
        self.assertTrue(all("output" not in rec for rec in quiet["nodes"].values()))
        self.assertEqual(("success","waiting","pending"),tuple(quiet["nodes"][k]["state"] for k in ("a","ask","b")))
        run.approve("ask",True)
        self.assertTrue(run.finished.wait(10))
        later=run.status(since=full["seq"])
        self.assertNotIn("output",later["nodes"]["a"])
        self.assertIn("second",later["nodes"]["b"]["output"]["stdout"])
        self.assertIn("output",later["nodes"]["ask"])
        self.assertGreater(later["nodes"]["b"]["seq"],full["seq"])
    def test_status_since_only_returns_newer_events(self):
        status=self.run_graph(graph([cmd("a","echo one"),cmd("b","echo two")],["start.out>a","a.success>b"]))
        self.assertEqual(status["seq"],status["events"][-1]["seq"])
        run=self.started[-1]
        later=run.status(since=status["events"][1]["seq"])
        self.assertEqual([e["seq"] for e in status["events"][2:]],[e["seq"] for e in later["events"]])
        self.assertEqual([],run.status(since=status["seq"])["events"])
class DryRunTests(Base):
    def test_a_dry_run_executes_nothing_and_plans_every_branch(self):
        set_live_target({"IPv4":"10.9.8.7"})
        marker=os.path.join(self.iso.dir,"marker.txt")
        d=node("d","decision",branches=[{"name":"yes","match":"all","conditions":[{"source":"output","op":"contains","value":"x"}]}],**{"else":"no"})
        s=node("s","script",language="python",code="open(%r,'w').write('ran')\n"%marker,branches=["out"])
        g=graph([cmd("a","%s -c \"open(r'%s','w').write('ran')\""%(PY,marker),"echo {IPv4} {Missing} ${later}"),d,cmd("y","echo yes"),cmd("n","echo no"),s,node("ask","approval",message="ok?"),cmd("z","echo after")],
                ["start.out>a","a.success>d","d.yes>y","d.no>n","y.success>s","s.out>ask","ask.approved>z"])
        status=self.run_graph(g,mode="dry",playbook_id=5)
        self.assertEqual(("dry","done"),(status["mode"],status["state"]))
        self.assertFalse(os.path.exists(marker))
        self.assertEqual([],jobs_of(status["run_id"]))
        self.assertEqual([],self.audit("terminal_command"))
        self.assertEqual({"planned"},set(self.states(status).values()))
        self.assertEqual("echo 10.9.8.7 {Missing} ${later}",status["nodes"]["a"]["output"]["resolved"][1])
        self.assertTrue(any("unfilled: {Missing}" in e["text"] for e in status["events"]))
        self.assertEqual(7,len(status["edges_taken"]))
        self.assertIsNone(status["approval"])
        self.assertEqual("dry",store.list_runs(5)[0]["mode"])
    def test_a_dry_run_marks_unreachable_nodes_as_not_planned(self):
        g=graph([cmd("a","echo one"),cmd("island","echo alone")],["start.out>a"])
        status=self.run_graph(g,mode="dry")
        self.assertEqual("pending",status["nodes"]["island"]["state"])
    def test_a_dry_run_ends_on_a_cycle(self):
        g=graph([cmd("a","echo one"),cmd("b","echo two")],["start.out>a","a.success>b","b.success>a"])
        status=self.run_graph(g,mode="dry")
        self.assertEqual("done",status["state"])
        self.assertEqual(1,status["nodes"]["a"]["visits"])
class RerunTests(Base):
    def test_re_run_from_a_node_reuses_the_earlier_output_and_variables(self):
        g=graph([cmd("a","echo first-output"),node("v","set",assign=[{"var":"kept","value":"yes"}]),cmd("b","echo again ${kept}"),node("x","set",assign=[{"var":"seen","value":"${last.stdout}"}])],["start.out>a","a.success>v","v.out>b","b.success>x"])
        first=self.run_graph(g,playbook_id=9)
        seed=engine.seed_from_status(g,first,"b")
        self.assertEqual("yes",seed["vars"]["kept"])
        self.assertEqual("v",seed["last"]["node"])
        second=self.run_graph(g,playbook_id=9,from_node="b",seed=seed)
        self.assertEqual("done",second["state"])
        self.assertEqual({"start":"skipped","a":"skipped","v":"skipped","b":"success","x":"success"},self.states(second))
        self.assertEqual(["echo again yes"],[j["command"] for j in jobs_of(second["run_id"])])
        self.assertEqual("again yes",second["vars"]["seen"].strip())
    def test_re_run_from_a_missing_node_fails_cleanly(self):
        g=graph([cmd("a","echo one")],["start.out>a"])
        status=self.run_graph(g,from_node="ghost")
        self.assertEqual("failed",status["state"])
        self.assertEqual([],jobs_of(status["run_id"]))
class SubchainTests(Base):
    def loader(self,graphs):
        def load(playbook_id):
            g=graphs.get(playbook_id)
            return {"name":"child %d"%playbook_id,"graph":g} if g else None
        return load
    def test_a_sub_chain_runs_inline_and_reports_success(self):
        child=graph([cmd("c1","echo child ${who}")],["start.out>c1"])
        parent=graph([node("v","set",assign=[{"var":"who","value":"from-parent"}]),node("sub","subchain",playbook_id=2),cmd("after","echo parent-after")],["start.out>v","v.out>sub","sub.success>after"])
        status=self.run_graph(parent,playbook_id=1,loader=self.loader({2:child}))
        self.assertEqual("done",status["state"],status["nodes"]["sub"])
        sub=status["nodes"]["sub"]
        self.assertEqual("success",sub["branch"])
        self.assertEqual("done",sub["output"]["sub_run"]["state"])
        self.assertEqual("success",sub["output"]["sub_run"]["nodes"]["c1"]["state"])
        self.assertEqual(["echo child from-parent","echo parent-after"],[j["command"] for j in jobs_of(status["run_id"])])
        self.assertEqual(1,len(sub["job_keys"]))
        self.assertTrue(any(e["node"]=="sub" and "[child 2]" in e["text"] for e in status["events"]))
        self.assertEqual(1,len(store.list_runs()))
    def test_a_failing_sub_chain_takes_the_fail_port(self):
        child=graph([cmd("c1","exit 1")],["start.out>c1"])
        parent=graph([node("sub","subchain",playbook_id=2),cmd("ok","echo ok"),cmd("bad","echo handled")],["start.out>sub","sub.success>ok","sub.fail>bad"])
        status=self.run_graph(parent,playbook_id=1,loader=self.loader({2:child}))
        self.assertEqual(("fail","skipped","success"),(status["nodes"]["sub"]["branch"],status["nodes"]["ok"]["state"],status["nodes"]["bad"]["state"]))
    def test_a_chain_cannot_run_itself(self):
        parent=graph([node("sub","subchain",playbook_id=1),cmd("bad","echo handled")],["start.out>sub","sub.fail>bad"])
        status=self.run_graph(parent,playbook_id=1,loader=self.loader({1:parent}))
        self.assertIn("cannot run itself",status["nodes"]["sub"]["error"])
        self.assertEqual("success",status["nodes"]["bad"]["state"])
    def test_nesting_is_capped(self):
        def chain_to(target):
            return graph([node("sub","subchain",playbook_id=target)],["start.out>sub"])
        graphs={2:chain_to(3),3:chain_to(4),4:chain_to(5),5:graph([cmd("deep","echo too-deep")],["start.out>deep"])}
        status=self.run_graph(chain_to(2),playbook_id=1,loader=self.loader(graphs))
        self.assertEqual("failed",status["state"])
        self.assertEqual([],jobs_of(status["run_id"]))
        graphs={2:chain_to(3),3:chain_to(4),4:graph([cmd("deep","echo deep-enough")],["start.out>deep"])}
        status=self.run_graph(chain_to(2),playbook_id=1,loader=self.loader(graphs))
        self.assertEqual("done",status["state"])
        self.assertEqual(["echo deep-enough"],[j["command"] for j in jobs_of(status["run_id"])])
    def test_stopping_the_parent_stops_the_child(self):
        child=graph([cmd("c1",slow(30))],["start.out>c1"])
        parent=graph([node("sub","subchain",playbook_id=2)],["start.out>sub"])
        run=self.start(parent,playbook_id=1,loader=self.loader({2:child}))
        self.assertTrue(wait_until(lambda:len(jobs_of(run.run_id))==1 and jobs_of(run.run_id)[0]["state"]=="running"))
        run.stop()
        self.assertTrue(run.finished.wait(10))
        self.assertEqual("cancelled",run.status()["state"])
        self.assertEqual("killed",jobs_of(run.run_id)[0]["state"])
    def test_an_approval_inside_a_sub_chain_is_answered_through_the_parent(self):
        child=graph([node("ask","approval",message="child asks"),cmd("c1","echo child-approved")],["start.out>ask","ask.approved>c1"])
        parent=graph([node("sub","subchain",playbook_id=2)],["start.out>sub"])
        run=self.start(parent,playbook_id=1,loader=self.loader({2:child}))
        self.assertTrue(wait_until(lambda:run.status()["state"]=="waiting_approval"))
        self.assertEqual({"node":"sub","message":"child asks"},run.status()["approval"])
        self.assertTrue(run.approve("sub",True))
        self.assertTrue(run.finished.wait(10))
        self.assertEqual(["echo child-approved"],[j["command"] for j in jobs_of(run.run_id)])
class LockTests(Base):
    def test_locking_the_app_stops_a_run_and_the_history_is_written_after_unlock(self):
        run=self.start(graph([cmd("a",slow(30)),cmd("b","echo never")],["start.out>a","a.success>b"]),playbook_id=4)
        self.assertTrue(wait_until(lambda:bool(run.status()["nodes"]["a"]["job_keys"])))
        common_db.set_locked(True)
        self.assertTrue(run.finished.wait(10))
        status=run.status()
        self.assertEqual(("cancelled","locked"),(status["state"],status["reason"]))
        self.assertEqual("skipped",status["nodes"]["b"]["state"])
        self.assertEqual(1,len(engine.pending_snapshots()))
        self.assertEqual(1,engine.flush_pending())
        common_db.set_locked(False)
        self.assertEqual(0,engine.flush_pending())
        self.assertEqual(["cancelled"],[r["state"] for r in store.list_runs(4)])
        self.assertTrue(any("locked" in e["detail"] for e in self.audit("chain_run_end")))
    def test_the_lock_path_stops_runs_at_once(self):
        run=self.start(graph([cmd("a",slow(30))],["start.out>a"]))
        self.assertTrue(wait_until(lambda:bool(run.status()["nodes"]["a"]["job_keys"])))
        security._suspend_agents()
        self.assertTrue(run.finished.wait(10))
        self.assertEqual(("cancelled","locked"),(run.status()["state"],run.status()["reason"]))
    def test_nothing_touches_the_database_or_job_output_after_the_lock(self):
        run=self.start(graph([cmd("a","echo before-lock; "+slow(30)),cmd("b","echo never")],["start.out>a","a.success>b"]),playbook_id=4)
        self.assertTrue(wait_until(lambda:bool(run.status()["nodes"]["a"]["job_keys"])))
        job_key=run.status()["nodes"]["a"]["job_keys"][0]
        calls=[]
        real_job_con,real_store_con,real_store_output=terminal._job_con,store._con,terminal._batch_store_output
        terminal._job_con=lambda:calls.append("job") or real_job_con()
        store._con=lambda:calls.append("store") or real_store_con()
        terminal._batch_store_output=lambda *a:calls.append("output") or real_store_output(*a)
        try:
            common_db.set_locked(True)
            security._suspend_agents()
            self.assertTrue(run.finished.wait(10))
            time.sleep(0.3)
            self.assertEqual(1,engine.flush_pending())
            self.assertEqual([],calls)
        finally:
            terminal._job_con,store._con,terminal._batch_store_output=real_job_con,real_store_con,real_store_output
        self.assertEqual("",terminal.batch_output(job_key))
        self.assertEqual(1,len(engine.pending_snapshots()))
        common_db.set_locked(False)
        self.assertEqual("running",terminal.get_job(job_key)["state"])
        self.assertEqual(0,engine.flush_pending())
        self.assertEqual(["cancelled"],[r["state"] for r in store.list_runs(4)])
    def test_a_run_started_while_locked_executes_nothing(self):
        marker=os.path.join(self.iso.dir,"locked-marker.txt")
        g=graph([cmd("a","%s -c \"open(r'%s','w').write('ran')\""%(PY,marker))],["start.out>a"])
        common_db.set_locked(True)
        run=self.start(g)
        self.assertTrue(run.finished.wait(10))
        self.assertEqual(("cancelled","locked"),(run.status()["state"],run.status()["reason"]))
        self.assertFalse(os.path.exists(marker))
class RegistryTests(Base):
    def test_the_number_of_active_runs_is_capped(self):
        g=graph([node("w","wait",seconds=600)],["start.out>w"])
        for _ in range(engine.MAX_ACTIVE_RUNS):self.start(g)
        with self.assertRaises(ValueError):engine.start_run(g)
    def test_get_run_and_forget(self):
        status=self.run_graph(graph([cmd("a","echo one")],["start.out>a"]))
        self.assertIsNotNone(engine.get_run(status["run_id"]))
        engine.forget_run(status["run_id"])
        self.assertIsNone(engine.get_run(status["run_id"]))
class OutputNodeTests(Base):
    def test_notify_adds_a_notice(self):
        g=graph([cmd("a","echo finding-text"),node("o","output",action="notify",title="Scan of ${what}",content="${last.stdout}")],["start.out>a","a.success>o"])
        status=self.run_graph(g,variables={"what":"web01"})
        self.assertEqual("done",status["state"],status["nodes"]["o"])
        self.assertEqual("Scan of web01",status["notices"][0]["title"])
        self.assertIn("finding-text",status["notices"][0]["text"])
    def test_target_placeholders_are_filled_in_title_content_and_note_name(self):
        from Cores.Services import notes_service
        set_live_target({"IPv4":"10.4.4.4","Domain":"corp.local"},"dc01")
        g=graph([cmd("a","echo scan-result"),node("o","output",action="notify",title="Scan of {IPv4}",content="{Domain} ${last.stdout} {NoValue} ${who}"),
                 node("n","output",action="note_append",note_name="Loot {Domain}",title="From {IPv4}",content="${last.stdout}")],["start.out>a","a.success>o","o.out>n"])
        status=self.run_graph(g,variables={"who":"{IPv4}"})
        self.assertEqual("done",status["state"],status["nodes"])
        notice=status["notices"][0]
        self.assertEqual("Scan of 10.4.4.4",notice["title"])
        self.assertEqual("corp.local scan-result {NoValue} {IPv4}",notice["text"])
        names=[n["note_name"] for n in notes_service._load_notes(notes_service._db_path())]
        self.assertEqual(["Loot corp.local"],names)
    def test_evidence_is_saved(self):
        from Cores.Services import evidence_service
        g=graph([cmd("a","echo proof-of-access"),node("o","output",action="evidence",title="Proof",content="${last.stdout}")],["start.out>a","a.success>o"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["nodes"]["o"])
        saved=evidence_service.get(status["nodes"]["o"]["output"]["result"]["evidence_id"])
        self.assertEqual("Proof",saved["title"])
        self.assertIn("proof-of-access",saved["content"])
    def test_a_finding_draft_is_added_to_a_report(self):
        from Cores.Services import reports_service
        report=reports_service.create_report({"name":"Engagement"})
        g=graph([cmd("a","echo anonymous login allowed"),node("o","output",action="finding_draft",report_id=report["id"],title="Anonymous SMB",severity="high",content="${last.stdout}")],["start.out>a","a.success>o"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["nodes"]["o"])
        finding=reports_service.get_finding(status["nodes"]["o"]["output"]["result"]["finding_id"])
        self.assertEqual(("Anonymous SMB","high"),(finding["title"],finding["severity"]))
        self.assertIn("anonymous login allowed",finding["description"])
    def test_a_note_is_created_then_appended_to(self):
        from Cores.Services import notes_service
        g=graph([cmd("a","echo 'line-<b>one</b>'"),node("o","output",action="note_append",note_name="Chain log",title="Result",content="${last.stdout}")],["start.out>a","a.success>o"])
        first=self.run_graph(g)
        self.assertEqual("done",first["state"],first["nodes"]["o"])
        second=self.run_graph(g)
        self.assertEqual("done",second["state"],second["nodes"]["o"])
        notes=[n for n in notes_service._load_notes(notes_service._db_path()) if n["note_name"]=="Chain log"]
        self.assertEqual(1,len(notes))
        self.assertEqual(2,notes[0]["content"].count("line-&lt;b&gt;one&lt;/b&gt;"))
        self.assertEqual(first["nodes"]["o"]["output"]["result"]["note_id"],second["nodes"]["o"]["output"]["result"]["note_id"])
    def test_a_failing_output_node_fails_the_run(self):
        g=graph([node("o","output",action="finding_draft",report_id=987654,title="x",content="y")],["start.out>o"])
        status=self.run_graph(g)
        self.assertEqual(("failed","fail"),(status["state"],status["nodes"]["o"]["state"]))
if __name__=="__main__":unittest.main()
