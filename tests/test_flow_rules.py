import ast,json,os,re,shlex,shutil,subprocess,sys,tempfile,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import flow_rules as rules
from Cores.Services.flow_rules import RuleError
NMAP="""Starting Nmap 7.94 ( https://nmap.org )
Nmap scan report for web.lab (10.0.0.5)
Host is up (0.0010s latency).
Not shown: 996 closed tcp ports (reset)
PORT     STATE    SERVICE VERSION
22/tcp   open     ssh     OpenSSH 8.9p1 Ubuntu
80/tcp   open     http    nginx 1.18.0
443/tcp  filtered https
3306/tcp closed   mysql

Nmap scan report for 10.0.0.9
Host is up.
PORT    STATE SERVICE
445/tcp open  microsoft-ds

Nmap done: 2 IP addresses (2 hosts up) scanned in 7.11 seconds
"""
PING_UP="""PING 10.0.0.5 (10.0.0.5) 56(84) bytes of data.
64 bytes from 10.0.0.5: icmp_seq=1 ttl=63 time=0.412 ms
64 bytes from 10.0.0.5: icmp_seq=2 ttl=63 time=0.380 ms

--- 10.0.0.5 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1001ms
"""
PING_DOWN="""PING 10.0.0.77 (10.0.0.77) 56(84) bytes of data.
From 10.0.0.1 icmp_seq=1 Destination Host Unreachable

--- 10.0.0.77 ping statistics ---
2 packets transmitted, 0 received, +2 errors, 100% packet loss, time 1010ms
"""
PING_WIN_UP="""Pinging 10.0.0.5 with 32 bytes of data:
Reply from 10.0.0.5: bytes=32 time<1ms TTL=128
Reply from 10.0.0.5: bytes=32 time<1ms TTL=128

Ping statistics for 10.0.0.5:
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
"""
PING_WIN_UNREACHABLE="""Pinging 10.0.0.77 with 32 bytes of data:
Reply from 10.0.0.1: Destination host unreachable.
Reply from 10.0.0.1: Destination host unreachable.

Ping statistics for 10.0.0.77:
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
"""
PING_WIN_DOWN="""Pinging 10.0.0.77 with 32 bytes of data:
Request timed out.
Request timed out.

Ping statistics for 10.0.0.77:
    Packets: Sent = 2, Received = 0, Lost = 2 (100% loss),
"""
def env(stdout="",stderr="",exit_code=0,parsed=None):
    return {"node":"n2","type":"command","ok":exit_code==0,"exit_code":exit_code,"stdout":stdout,"stderr":stderr,"branch":"success","parsed":parsed,"duration_ms":1,"commands":[]}
def cond(source,op,value="",field="",ci=True):
    return {"source":source,"field":field,"op":op,"value":value,"ci":ci}
class RulesBase(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def result(self,condition,data=None,scope=None):
        return rules.evaluate_condition(condition,data if data is not None else env(),scope or {})["result"]
class NoCodeEvaluationTests(unittest.TestCase):
    def test_modules_never_call_eval_exec_or_compile(self):
        root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in("flow_rules.py","flow_schema.py","flow_scripts.py"):
            with open(os.path.join(root,"Cores","Services",name),encoding="utf-8") as handle:tree=ast.parse(handle.read())
            for found in ast.walk(tree):
                if isinstance(found,ast.Call) and isinstance(found.func,ast.Name):
                    self.assertNotIn(found.func.id,("eval","exec","compile","__import__","getattr" if False else "execfile"),"%s line %d"%(name,found.lineno))
                if isinstance(found,ast.Attribute):self.assertNotIn(found.attr,("system","popen","__subclasses__","__globals__"),"%s line %d"%(name,found.lineno))
    def test_matcher_source_is_a_fixed_constant(self):
        argv=rules._matcher_argv()
        self.assertEqual([sys.executable,"-I","-S","-c"],argv[:4])
        self.assertIs(argv[4],rules._MATCHER_SOURCE)
        self.assertNotIn("%s",rules._MATCHER_SOURCE);self.assertNotIn("{0}",rules._MATCHER_SOURCE)
        ast.parse(rules._MATCHER_SOURCE)
    def test_pattern_and_text_travel_on_stdin_only(self):
        seen={}
        real=subprocess.run
        def spy(argv,**options):
            seen["argv"]=argv;seen["input"]=options.get("input");seen["shell"]=options.get("shell",False)
            return real(argv,**options)
        rules.subprocess.run=spy
        try:found=rules.regex_search(r"(\w+=\d+;)+SECRETPATTERN","a=1;b=2;SECRETPATTERN and SECRETTEXT")
        finally:rules.subprocess.run=real
        self.assertTrue(found["matched"])
        self.assertEqual(rules._matcher_argv(),seen["argv"])
        self.assertFalse(seen["shell"])
        self.assertNotIn("SECRETPATTERN"," ".join(seen["argv"]))
        request=json.loads(seen["input"].decode("ascii"))
        self.assertEqual((r"(\w+=\d+;)+SECRETPATTERN","search"),(request["pattern"],request["op"]))
        self.assertIn("SECRETTEXT",request["text"])
class CheckRegexTests(unittest.TestCase):
    def test_accepts_ordinary_patterns(self):
        for pattern in(r"ttl=(\d+)",r"^(\d{1,3}\.){3}\d{1,3}$",r"(\d+\.)+\d+",r"(?P<port>\d+)/tcp\s+open",r"(foo|bar)*",r"(.|\n)*end",r"(ab?)*c",r"Sharename|Disk|IPC\$",r"\bhttps?://\S+",r"[a-z]+@[a-z]+\.[a-z]{2,}",r"(?i)host is up"):
            self.assertIsNone(rules.check_regex(pattern),pattern)
        self.assertIsNone(rules.check_regex("a.b","imsx"))
    def test_rejects_nested_unbounded_quantifiers(self):
        for pattern in(r"(a+)+$",r"(a*)*",r"(.*)*",r"(a|aa)*$",r"(\w+\s?)+$",r"([a-z]+)*",r"(?:a+)+",r"((a+)b?)+",r"(a+){10,}",r"(\s*\w+\s*)*=",r"(\w\w|\w)+$",r"(a|a?)+",r"(x|)+"):
            with self.assertRaises(RuleError,msg=pattern) as caught:rules.check_regex(pattern)
            self.assertIn("forever",str(caught.exception),pattern)
    def test_rejects_bad_syntax_length_flags_and_counts(self):
        cases=[("(unclosed","Invalid regex"),("[z-a]","Invalid regex"),("a"*501,"longer than"),("","empty"),("a\x00b","NUL"),("(a)"*41,"too many groups"),
               ("|".join("w%d"%i for i in range(90)),"too many alternatives"),("a?"*61,"too many quantifiers"),(5,"must be text")]
        for pattern,fragment in cases:
            with self.assertRaises(RuleError) as caught:rules.check_regex(pattern)
            self.assertIn(fragment,str(caught.exception))
        with self.assertRaises(RuleError):rules.check_regex("a","q")
        self.assertIsNone(rules.check_regex("a"*500))
    def test_rule_error_is_a_value_error(self):
        self.assertTrue(issubclass(RuleError,ValueError))
class RegexRunTests(unittest.TestCase):
    def test_search_result_shape(self):
        found=rules.regex_search(r"(?P<port>\d+)/(tcp|udp)","PORT 443/tcp open")
        self.assertEqual({"matched":True,"groups":["443/tcp","443","tcp"],"named":{"port":"443"},"span":[5,12]},found)
        self.assertEqual({"matched":False,"groups":[],"named":{},"span":[-1,-1]},rules.regex_search("zzz","abc"))
        self.assertEqual(["x",""],rules.regex_search(r"x(y)?","x")["groups"])
    def test_flags(self):
        self.assertFalse(rules.regex_search("TTL","ttl=1")["matched"])
        self.assertTrue(rules.regex_search("TTL","ttl=1","i")["matched"])
        self.assertTrue(rules.regex_search("^b$","a\nb\nc","m")["matched"])
        self.assertTrue(rules.regex_search("a.b","a\nb","s")["matched"])
        self.assertTrue(rules.regex_search("a  b # comment","ab","x")["matched"])
    def test_findall_and_count(self):
        self.assertEqual(["22","80"],rules.regex_findall(r"(\d+)/tcp","22/tcp 80/tcp"))
        self.assertEqual(["22/tcp","80/tcp"],rules.regex_findall(r"\d+/tcp","22/tcp 80/tcp"))
        self.assertEqual([["22","tcp"],["53","udp"]],rules.regex_findall(r"(\d+)/(\w+)","22/tcp 53/udp"))
        self.assertEqual(3,len(rules.regex_findall("a","a"*50,limit=3)))
        self.assertEqual(50,rules.regex_count("a","a"*50))
        self.assertEqual([],rules.regex_findall("z","aaa"))
    def test_text_is_capped(self):
        self.assertFalse(rules.regex_search("needle","x"*100+"needle",max_text=50)["matched"])
        self.assertTrue(rules.regex_search("needle","x"*100+"needle")["matched"])
        self.assertFalse(rules.regex_search("needle","x"*rules.MAX_TEXT+"needle")["matched"])
    def test_catastrophic_pattern_is_rejected_up_front(self):
        started=time.monotonic()
        with self.assertRaises(RuleError):rules.regex_search(r"(a+)+$","a"*40+"!")
        self.assertLess(time.monotonic()-started,1.0)
    def test_catastrophic_pattern_that_passes_the_screen_is_killed_by_the_timeout(self):
        rules.check_regex(r"(x+x+)+y")   # the static screen cannot see this one
        started=time.monotonic()
        with self.assertRaises(RuleError) as caught:rules.regex_search(r"(x+x+)+y","x"*40,timeout=0.5)
        elapsed=time.monotonic()-started
        self.assertEqual("regex timed out",str(caught.exception))
        self.assertLess(elapsed,4.0)
        started=time.monotonic()
        with self.assertRaises(RuleError):rules.regex_findall(r"(.*,)*$",","*40+"x",timeout=0.5)
        self.assertLess(time.monotonic()-started,4.0)
    def test_non_trivial_pattern_runs_in_the_helper_process(self):
        calls=[]
        real=rules._run_isolated
        def spy(*args):
            calls.append(args[0]);return real(*args)
        local=rules._run_local
        rules._run_isolated=spy
        rules._run_local=lambda *a:self.fail("a nested quantifier must not run in-process")
        try:
            found=rules.regex_search(r"(?P<ip>(\d{1,3}\.){3}\d{1,3}):(\d+)","target 10.20.30.40:8443 \u00e9\u4e2d ok")
            many=rules.regex_findall(r"((?:\d+\.)+\d+)","1.2.3 and 10.0.0.1")
            count=rules.regex_count(r"(a+b)+","ab aabab ab")
        finally:
            rules._run_isolated=real;rules._run_local=local
        self.assertEqual(["search","findall","count"],calls)
        self.assertEqual(("10.20.30.40","8443"),(found["named"]["ip"],found["groups"][3]))
        self.assertEqual(["1.2.3","10.0.0.1"],many)
        self.assertEqual(3,count)
    def test_limit_is_enforced_inside_the_helper(self):
        replies=[]
        real=subprocess.run
        def spy(argv,**options):
            done=real(argv,**options);replies.append((json.loads(options["input"].decode("ascii")),done.stdout));return done
        text=" ".join("k%d=%d.%d"%(i,i,i) for i in range(20000))
        rules.subprocess.run=spy
        try:
            found=rules.regex_findall(r"(\w+)=((?:\d+\.)+\d+)",text,limit=7)
            counted=rules.regex_count(r"(?:\d+\.)+\d+",text,limit=11)
            capped=rules.regex_findall(r"(?:\d+\.)+\d+",text,limit=10**9)
        finally:rules.subprocess.run=real
        self.assertEqual(3,len(replies))
        self.assertEqual([7,11,100000],[request["limit"] for request,_ in replies])
        self.assertEqual(7,len(json.loads(replies[0][1].decode("ascii"))["result"]))   # the helper itself stopped at the limit
        self.assertLess(len(replies[0][1]),400)
        self.assertEqual(7,len(found));self.assertEqual(["k0","0.0"],found[0]);self.assertEqual(11,counted)
        self.assertEqual(len(re.findall(r"(?:\d+\.)+\d+",text[:rules.MAX_TEXT])),len(capped));self.assertGreater(len(capped),10000)
        self.assertIn("if len(out)>=limit:break",rules._MATCHER_SOURCE)
        self.assertEqual(1,len(rules.regex_findall("a","aaa",limit=0)));self.assertEqual(2,len(rules.regex_findall("a","aaa",limit=2)))
    def test_simple_pattern_stays_in_process(self):
        real=rules._run_isolated
        rules._run_isolated=lambda *a:self.fail("a literal must run in-process")
        try:
            self.assertTrue(rules.regex_search("ttl=","x"*200000+"ttl=64")["matched"])
            self.assertTrue(rules.regex_search(r"ttl=(\d+)","reply ttl=64")["matched"])
        finally:rules._run_isolated=real
    def test_one_unbounded_quantifier_on_a_large_text_goes_to_the_helper(self):
        calls=[]
        real=rules._run_isolated
        def spy(*args):
            calls.append(1);return real(*args)
        rules._run_isolated=spy
        try:self.assertTrue(rules.regex_search(r"open\s+http","\n".join("line %d"%i for i in range(5000))+"\n80/tcp open  http")["matched"])
        finally:rules._run_isolated=real
        self.assertEqual([1],calls)
    def test_backreference_goes_to_the_helper(self):
        self.assertFalse(rules._cheap(rules._checked(r"(a)\1","")[1],10))
        self.assertTrue(rules.regex_search(r"(\w)\1","hello")["matched"])
    def test_helper_failure_is_a_rule_error(self):
        real=rules._matcher_argv
        rules._matcher_argv=lambda:["/nonexistent/python-for-loya-tests"]
        try:
            with self.assertRaises(RuleError):rules.regex_search(r"(\d+\.)+\d+","1.2.3")
        finally:rules._matcher_argv=real
class LookupTests(unittest.TestCase):
    DATA={"a":{"b":[{"c":1},{"c":2},{"d":3}]},"ports":[{"port":22,"state":"open"},{"port":80,"state":"open"}],"name":"x","Mixed":{"Key":5},"dotted.key":7,"n":None,"m":[[1,2],[3]]}
    def test_paths(self):
        look=lambda path:rules.lookup(self.DATA,path)
        self.assertEqual(1,look("a.b[0].c"));self.assertEqual(2,look("a.b.1.c"));self.assertEqual(3,look("a.b[-1].d"))
        self.assertEqual([22,80],look("ports[*].port"));self.assertEqual([1,2],look("a.b[*].c"))
        self.assertEqual("x",look("name"));self.assertEqual("x",look("$.name"));self.assertEqual(5,look("mixed.key"))
        self.assertEqual(7,look('["dotted.key"]'));self.assertEqual(self.DATA,look(""));self.assertEqual(self.DATA,look("$"))
        self.assertEqual([[1,2],[3]],look("m[*]"));self.assertEqual([1,3],look("m[*][0]"))
        self.assertEqual(["open","open"],look("ports[*].state"))
    def test_missing_paths_give_none(self):
        for path in("nope","a.b[9]","a.b.c","name.x","ports.port","a..b","a[","a]b","[x]","n.x",None,5,"a."+"b."*40):
            self.assertIsNone(rules.lookup(self.DATA,path),path)
        self.assertEqual([],rules.lookup(self.DATA,"ports[*].nope"))
        self.assertIsNone(rules.lookup(None,"a"));self.assertIsNone(rules.lookup("text","a"))
    def test_no_attribute_access(self):
        class Thing:
            secret="s3cret"
            def __getitem__(self,key):raise AssertionError("objects are never indexed")
        scope={"obj":Thing(),"text":"abc","fn":len,"d":{}}
        for path in("obj.secret","obj.__class__","text.__class__","text.upper","fn.__name__","d.__class__","d.keys","text[0]","obj[0]","d.__class__.__mro__"):
            self.assertIsNone(rules.lookup(scope,path),path)
    def test_resolve_roots_then_variables(self):
        scope={"vars":{"ip":"10.0.0.5","last":"shadow","parsed":{"ports":[1,2]}},"last":{"stdout":"out","exit_code":0},"nodes":{"n2":{"exit_code":3}},
               "target":{"ipv4":"10.9.9.9"},"item":{"port":443},"index":2}
        self.assertEqual("10.0.0.5",rules.resolve(scope,"ip"));self.assertEqual("out",rules.resolve(scope,"last.stdout"))
        self.assertEqual(0,rules.resolve(scope,"last.exit_code"));self.assertEqual(3,rules.resolve(scope,"nodes.n2.exit_code"))
        self.assertEqual("10.9.9.9",rules.resolve(scope,"target.IPv4"));self.assertEqual(443,rules.resolve(scope,"item.port"))
        self.assertEqual(2,rules.resolve(scope,"index"));self.assertEqual([1,2],rules.resolve(scope,"parsed.ports"))
        self.assertEqual("10.0.0.5",rules.resolve(scope,"vars.ip"))
        self.assertIsNone(rules.resolve(scope,"missing"));self.assertIsNone(rules.resolve(scope,""));self.assertIsNone(rules.resolve(None,"x"))
        self.assertEqual("v",rules.resolve({"vars":{"item":"v"}},"item"))
class TemplateTests(unittest.TestCase):
    SCOPE={"vars":{"ip":"10.0.0.5","ports":[22,80],"flag":True,"n":3.0,"obj":{"a":1},"rows":[{"p":1}],"evil":"${ip}","empty":""},"last":{"stdout":"hello\n","exit_code":0},
           "nodes":{"n2":{"exit_code":7}},"target":{"ipv4":"192.168.1.1"},"item":{"port":443}}
    def test_plain_expansion(self):
        text,warnings=rules.expand_template("ip=${ip} out=${last.stdout} rc=${nodes.n2.exit_code} t=${target.ipv4} p=${item.port} ${ ip }",self.SCOPE)
        self.assertEqual("ip=10.0.0.5 out=hello\n rc=7 t=192.168.1.1 p=443 10.0.0.5",text)
        self.assertEqual([],warnings)
    def test_value_formats(self):
        text,_=rules.expand_template("${ports}|${flag}|${n}|${obj}|${rows}|${last.exit_code}|${empty}|",self.SCOPE)
        self.assertEqual('22,80|true|3|{"a":1}|[{"p":1}]|0||',text)
    def test_unknown_names_warn(self):
        text,warnings=rules.expand_template("a${nope}b${last.nope}c",self.SCOPE)
        self.assertEqual("abc",text)
        self.assertEqual(2,len(warnings));self.assertIn("${nope}",warnings[0])
    def test_single_pass_and_escape(self):
        self.assertEqual(("${ip}",[]),rules.expand_template("${evil}",self.SCOPE))
        self.assertEqual(("${ip} $HOME ${} $ { x }",[]),rules.expand_template("$${ip} $HOME ${} $ { x }",self.SCOPE))
        self.assertEqual(("",[]),rules.expand_template(None,self.SCOPE));self.assertEqual(("5",[]),rules.expand_template(5,self.SCOPE))
    def test_raw_is_not_quoted(self):
        scope={"vars":{"v":"a b; id"}}
        self.assertEqual("x 'a b; id' a b; id",rules.expand_template("x ${v} ${raw:v}",scope,rules.shell_quoter("bash",windows=False))[0])
        self.assertEqual("x a b; id a b; id",rules.expand_template("x ${v} ${raw:v}",scope)[0])
        self.assertEqual([("v",False),("v",True)],rules.template_names("x ${v} ${raw:v} $${v}"))
    def test_raw_ok_gates_raw_values(self):
        scope={"vars":{"lit":"-sV -p 80","tainted":"; id","obj":{"k":"v"}}}
        q=rules.shell_quoter("bash",windows=False)
        self.assertEqual("nmap -sV -p 80 x",rules.expand_template("nmap ${raw:lit} x",scope,q,raw_ok={"lit"})[0])
        self.assertEqual("nmap -sV -p 80",rules.expand_template("nmap ${raw: lit }",scope,q,raw_ok=lambda name:name=="lit")[0])
        self.assertEqual("v",rules.expand_template("${raw:obj.k}",scope,None,raw_ok=["obj.k"])[0])
        for approved in(set(),{"lit"},lambda name:False,[],lambda name:1/0,5):
            with self.assertRaises(RuleError) as caught:rules.expand_template("echo ${raw:tainted}",scope,q,raw_ok=approved)
            self.assertEqual("raw value not allowed: tainted",str(caught.exception))
        with self.assertRaises(RuleError):rules.expand_template("${raw:tainted}",scope,raw_ok=set())          # also without a quoter
        self.assertEqual("echo ; id",rules.expand_template("echo ${raw:tainted}",scope,q)[0])                 # None: unchanged behaviour
        self.assertEqual("echo ; id",rules.expand_template("echo ${raw:tainted}",scope,q,raw_ok=None)[0])
        self.assertEqual("echo '; id' ${raw:tainted}",rules.expand_template("echo ${tainted} $${raw:tainted}",scope,q,raw_ok=set())[0])   # quoted and escaped forms are not raw
    def test_plain_callable_quoter(self):
        self.assertEqual("<10.0.0.5>",rules.expand_template("${ip}",self.SCOPE,lambda value:"<"+value+">")[0])
    def test_resolve_value_keeps_lists(self):
        self.assertEqual(([22,80],[]),rules.resolve_value(" ${ports} ",self.SCOPE))
        self.assertEqual(("p 22,80",[]),rules.resolve_value("p ${ports}",self.SCOPE))
        value,warnings=rules.resolve_value("${nope}",self.SCOPE)
        self.assertIsNone(value);self.assertEqual(1,len(warnings))
HOSTILE=["; rm -rf /","$(id)","`id`","a b","it's","\"dq\"","x && id","| nc evil 1","$HOME","back\\slash","new\nline","*","~root","-rf","'; id; '","\"; id; \"","$(touch pwned)","a'b\"c`d$e\\f","=cmd","!!","#c","\u2019; id; \u2019","",">out","%PATH%","&calc"]
DQ_ESCAPE=re.compile(r'\\[\\"$`]')   # the escapes a POSIX shell honours inside double quotes
class PosixQuoterTests(unittest.TestCase):
    def setUp(self):
        self.q=rules.shell_quoter("bash",windows=False)
    def test_plain_position_is_one_literal_word(self):
        for value in HOSTILE:
            words=shlex.split("echo "+self.q(value,"echo ")+" tail")
            self.assertEqual(["echo",value.replace("\n",""),"tail"],words,value)   # line breaks never reach a command line
    def test_inside_the_users_quotes(self):
        for hostile in HOSTILE:
            value=hostile.replace("\n","")
            inside=self.q(hostile,'echo "<')
            self.assertEqual(value,DQ_ESCAPE.sub(lambda m:m.group(0)[1],inside),value)   # what the shell gives back
            self.assertFalse(set(DQ_ESCAPE.sub("",inside))&set('"$`\\'),value)             # nothing active is left unescaped
            self.assertEqual(["echo","<"+value+">"],shlex.split("echo '<"+self.q(hostile,"echo '<")+">'"),value)
    def test_control_characters_are_stripped_and_length_is_capped(self):
        dirty="a\x00b\rc\nd\te\x1b[31mf\x7fg\x85h i\u009bj"
        for quoter in(self.q,rules.shell_quoter("pwsh",windows=True)):
            for prefix in("echo ",'echo "',"echo '"):
                cleaned=quoter(dirty,prefix)
                self.assertEqual("abcd e[31mfghij",cleaned.strip("'"),(quoter.kind,prefix))
                self.assertFalse([ch for ch in cleaned if ord(ch)<32 or 127<=ord(ch)<160],(quoter.kind,prefix))
        self.assertEqual("'a; id'",self.q("a\n; id","echo "))
        self.assertEqual("x"*4096,self.q("x"*4096,"echo "))
        for quoter in(self.q,rules.shell_quoter("pwsh",windows=True),rules.shell_quoter("cmd",windows=True)):
            for prefix in("echo ",'echo "'):
                with self.assertRaises(RuleError,msg=quoter.kind):quoter("x"*4097,prefix)
                with self.assertRaises(RuleError,msg=quoter.kind):quoter("x"*100000,prefix)
        for fn in(rules.quote_posix,rules.quote_powershell,rules.quote_cmd):
            self.assertEqual("ab",fn("a\x00\x07b"))
            with self.assertRaises(RuleError):fn("y"*5000)
        self.assertEqual("a b",rules.shell_quoter("cmd",windows=True)("a\tb",'echo "'))
        with self.assertRaises(RuleError):rules.expand_template("echo ${v}",{"vars":{"v":"z"*5000}},self.q)
        self.assertEqual("echo "+"z"*5000,rules.expand_template("echo ${v}",{"vars":{"v":"z"*5000}})[0])   # plain text is not capped
    def test_safe_values_stay_bare(self):
        for value in("10.0.0.5","80","example.com","a/b-c_d:1","22,80,443"):self.assertEqual(value,self.q(value,"nmap -p "))
        self.assertEqual("''",self.q("","echo "))
    def test_context_detection(self):
        context=rules._posix_context
        self.assertEqual("plain",context("echo "));self.assertEqual("double",context('echo "a'));self.assertEqual("single",context("echo 'a"))
        self.assertEqual("plain",context('echo "a" '));self.assertEqual("plain",context("echo it\\'s "));self.assertEqual("double",context('echo "a\\"b'))
        self.assertEqual("plain",context('echo "$(cat '));self.assertEqual("double",context('echo "$(cat "'));self.assertEqual("double",context('echo "$(cat x) '))
        self.assertEqual("plain",context("x=$(cat a) "));self.assertEqual("plain",context("(cd /tmp; ls) "));self.assertEqual("plain",context("# it's a comment\necho "))
        for prefix in("echo `cat ","cat <<EOF\n","echo $'a","echo \\","echo \"a\\","echo # trailing "):self.assertEqual("complex",context(prefix),prefix)
    def test_complex_positions_refuse_unsafe_values(self):
        for prefix in("echo `cat ","cat <<EOF\n","echo $'a","echo \\"):
            self.assertEqual("10.0.0.5",self.q("10.0.0.5",prefix))
            with self.assertRaises(RuleError):self.q("a; id",prefix)
            with self.assertRaises(RuleError):self.q("",prefix)
    def test_expand_template_uses_the_position(self):
        scope={"vars":{"v":"a\"b $(id) 'c'"}}
        text,_=rules.expand_template("printf '%s|%s|%s' ${v} \"${v}\" '${v}'",scope,self.q)
        self.assertEqual(r"""printf '%s|%s|%s' 'a"b $(id) '\''c'\''' "a\"b \$(id) 'c'" 'a"b $(id) '\''c'\'''""",text)
    @unittest.skipUnless(os.name=="posix" and shutil.which("bash"),"needs bash")
    def test_real_shell_never_runs_an_injected_command(self):
        folder=tempfile.mkdtemp(prefix="loya-quote-")
        try:
            canary=os.path.join(folder,"pwned")
            values=["; touch pwned","$(touch pwned)","`touch pwned`","x' ; touch pwned ; '","x\" ; touch pwned ; \"","a\nb; touch pwned","| touch pwned","&& touch pwned","$(touch pwned)'\"`touch pwned`","\\'; touch pwned #"]
            for value in values:
                scope={"vars":{"v":value}}
                for template in("printf '%s' ${v}","printf '%s' \"${v}\"","printf '%s' '${v}'","printf '%s' \"$(printf '%s' ${v})\"","printf '%s' \"$(printf '%s' \"${v}\")\"","(printf '%s' ${v})"):
                    command,_=rules.expand_template(template,scope,self.q)
                    done=subprocess.run(["bash","--noprofile","--norc","-c",command],cwd=folder,capture_output=True,timeout=20,env={"PATH":os.environ.get("PATH",os.defpath)})
                    self.assertFalse(os.path.exists(canary),"injected through %r with %r -> %r"%(template,value,command))
                    expected=value.replace("\n","")
                    self.assertEqual(expected,done.stdout.decode(),(template,value,command))
        finally:shutil.rmtree(folder,ignore_errors=True)
class PowerShellQuoterTests(unittest.TestCase):
    def setUp(self):
        self.q=rules.shell_quoter("pwsh",windows=True)
    def test_kinds(self):
        self.assertEqual("powershell",rules.shell_kind("pwsh",windows=True));self.assertEqual("powershell",rules.shell_kind("powershell",windows=True))
        self.assertEqual("powershell",rules.shell_kind("pwsh",windows=False));self.assertEqual("cmd",rules.shell_kind("cmd",windows=True))
        self.assertEqual("cmd",rules.shell_kind("wsl:kali-linux",windows=True))
        for shell in("shell","bash","zsh","anything"):self.assertEqual("posix",rules.shell_kind(shell,windows=False))
        self.assertIs(rules.shell_quoter("zsh",windows=False),rules.shell_quoter("bash",windows=False))
        self.assertTrue(rules.shell_quoter("cmd",windows=True).context_aware)
    def test_single_quote_doubling(self):
        self.assertEqual("'; rm -rf /'",self.q("; rm -rf /","echo "))
        self.assertEqual("'$(id)'",self.q("$(id)","echo "))
        self.assertEqual("'it''s'",self.q("it's","echo "))
        self.assertEqual("'a\u2019\u2019; calc; \u2018\u2018b'",self.q("a\u2019; calc; \u2018b","echo "))
        self.assertEqual("''",self.q("","echo "));self.assertEqual("10.0.0.5",self.q("10.0.0.5","ping "))
        self.assertEqual("'-Recurse'",self.q("-Recurse","rm "))
    def test_inside_quotes(self):
        self.assertEqual("it''s",self.q("it's","echo 'x "))
        self.assertEqual("a`\"b`$(id)``c",self.q("a\"b$(id)`c",'echo "x '))
        self.assertEqual("`\u201d; calc",self.q("\u201d; calc",'echo "x '))
        self.assertEqual("plain",rules._powershell_context("echo 'it''s' "));self.assertEqual("single",rules._powershell_context("echo 'it''s"))
        self.assertEqual("plain",rules._powershell_context('echo "a""b" '));self.assertEqual("double",rules._powershell_context('echo "a`"b'))
    def test_only_single_quoted_literals_are_produced(self):
        for value in HOSTILE+["“; calc; ”","„$(calc)“","‘’‚‛","a\"b","$env:PATH","@(1,2)","{calc}","`n"]:
            quoted=self.q(value,"echo ")
            if quoted[:1]!="'":
                self.assertRegex(quoted,r"^[A-Za-z0-9_][A-Za-z0-9_./:-]*$",value);continue
            body=quoted[1:-1]
            self.assertEqual("'",quoted[-1],value);self.assertNotEqual('"',quoted[0])
            index=0;undoubled=[]
            while index<len(body):     # every quote character inside the literal must be doubled
                undoubled.append(body[index])
                if body[index] in "'‘’‚‛":
                    self.assertEqual(body[index],body[index+1:index+2],value);index+=1
                index+=1
            self.assertEqual(value.replace("\n",""),"".join(undoubled),value)
    def test_complex_positions(self):
        for prefix in("echo @'\n","echo \"$(","echo `","<# note ","echo # c "):
            self.assertEqual("abc",self.q("abc",prefix))
            with self.assertRaises(RuleError):self.q("a; calc",prefix)
    @unittest.skipUnless(shutil.which("pwsh"),"needs pwsh")
    def test_real_powershell_never_runs_an_injected_command(self):
        folder=tempfile.mkdtemp(prefix="loya-quote-")
        try:
            values=["; New-Item pwned","$(New-Item pwned)","x'; New-Item pwned; '","x\"; New-Item pwned; \"","x\u2019; New-Item pwned; \u2018","`$(New-Item pwned)","a b|New-Item pwned"]
            script=[];expected=[]
            for value in values:
                for template in("[Console]::Out.Write(${v});[Console]::Out.Write([char]0)","[Console]::Out.Write(\"${v}\");[Console]::Out.Write([char]0)","[Console]::Out.Write('${v}');[Console]::Out.Write([char]0)"):
                    script.append(rules.expand_template(template,{"vars":{"v":value}},self.q)[0]);expected.append(value)
            done=subprocess.run([shutil.which("pwsh"),"-NoLogo","-NoProfile","-NonInteractive","-Command","\n".join(script)],cwd=folder,capture_output=True,timeout=120)
            self.assertEqual([],os.listdir(folder),done.stderr.decode(errors="replace"))
            self.assertEqual(expected,done.stdout.decode("utf-8").split("\x00")[:-1])
        finally:shutil.rmtree(folder,ignore_errors=True)
class CmdQuoterTests(unittest.TestCase):
    def setUp(self):
        self.q=rules.shell_quoter("cmd",windows=True)
    def test_rejects_metacharacters(self):
        for value in("a&b","a|b","a<b","a>b","a^b","%PATH%","say \"hi\"","line\nbreak","cr\rhere","!x!","; rm -rf / & calc","$(id) | x","$(id)","a(b","a)b","(","x) & calc & (y"):
            with self.assertRaises(RuleError,msg=value):self.q(value,"echo ")
            with self.assertRaises(RuleError,msg=value):self.q(value,'echo "')
            with self.assertRaises(RuleError,msg=value):rules.quote_cmd(value)
    def test_quotes_what_needs_quoting(self):
        self.assertEqual("10.0.0.5",self.q("10.0.0.5","ping "));self.assertEqual('"a b"',self.q("a b","echo "));self.assertEqual('""',self.q("","echo "))
        self.assertEqual('"; rm -rf /"',self.q("; rm -rf /","echo "));self.assertEqual('"$HOME `id`"',self.q("$HOME `id`","echo "))
        self.assertEqual(set('&|<>^%"!()\r\n'),set(rules._CMD_FORBIDDEN))
        self.assertEqual('"C:\\my dir\\\\"',self.q("C:\\my dir\\","dir "));self.assertEqual("C:\\dir\\x",self.q("C:\\dir\\x","dir "))
        self.assertEqual("a b",self.q("a b",'echo "x '));self.assertEqual('"a,b"',self.q("a,b","echo "))
    def test_expand_template_passes_the_error_on(self):
        with self.assertRaises(RuleError):rules.expand_template("ping ${v}",{"vars":{"v":"1.1.1.1 & calc"}},self.q)
        self.assertEqual("ping 1.1.1.1",rules.expand_template("ping ${v}",{"vars":{"v":"1.1.1.1"}},self.q)[0])
class ConditionTests(RulesBase):
    def test_exit_code(self):
        self.assertTrue(self.result(cond("exit_code","eq","0")));self.assertFalse(self.result(cond("exit_code","ne","0")))
        data=env(exit_code=2)
        for op,value,expected in(("eq","2",True),("ne","2",False),("gt","1",True),("gt","2",False),("ge","2",True),("lt","3",True),("lt","2",False),("le","2",True),("eq"," 2.0 ",True),("equals","2",True)):
            self.assertEqual(expected,self.result(cond("exit_code",op,value),data),(op,value))
        self.assertFalse(self.result(cond("exit_code","eq","0"),env(exit_code=None) | {"exit_code":None}))
    def test_text_sources(self):
        data=env(stdout="Hello World\n",stderr="Warning: boom")
        self.assertTrue(self.result(cond("stdout","contains","hello"),data));self.assertFalse(self.result(cond("stdout","contains","hello",ci=False),data))
        self.assertFalse(self.result(cond("stdout","contains","boom"),data));self.assertTrue(self.result(cond("stderr","contains","boom"),data))
        self.assertTrue(self.result(cond("output","contains","boom"),data));self.assertTrue(self.result(cond("output","contains","World\nWarning"),data | {"stdout":"Hello World"}))
        self.assertTrue(self.result(cond("stdout","not_contains","boom"),data));self.assertFalse(self.result(cond("stdout","not_contains","WORLD"),data))
        self.assertTrue(self.result(cond("stdout","equals","hello world"),data));self.assertFalse(self.result(cond("stdout","equals","hello"),data))
        self.assertTrue(self.result(cond("stdout","not_equals","hello"),data));self.assertFalse(self.result(cond("stdout","not_equals","HELLO WORLD"),data))
        self.assertTrue(self.result(cond("stdout","starts_with","hello"),data));self.assertFalse(self.result(cond("stdout","starts_with","world"),data))
        self.assertTrue(self.result(cond("stderr","ends_with","BOOM"),data));self.assertFalse(self.result(cond("stderr","ends_with","BOOM",ci=False),data))
    def test_regex_ops(self):
        data=env(stdout="80/tcp open http\n")
        self.assertTrue(self.result(cond("stdout","regex",r"^\d+/tcp\s+OPEN"),data));self.assertFalse(self.result(cond("stdout","regex",r"^\d+/tcp\s+OPEN",ci=False),data))
        self.assertTrue(self.result(cond("stdout","not_regex",r"udp"),data));self.assertFalse(self.result(cond("stdout","not_regex",r"tcp"),data))
        bad=rules.evaluate_condition(cond("stdout","regex","(a+)+$"),data,{})
        self.assertFalse(bad["result"]);self.assertIn("forever",bad["error"])
        self.assertFalse(rules.evaluate_condition(cond("stdout","not_regex","(a+)+$"),data,{})["result"])
    def test_emptiness_and_truth(self):
        self.assertTrue(self.result(cond("stdout","is_empty"),env(stdout="  \n")));self.assertTrue(self.result(cond("stdout","not_empty"),env(stdout="x")))
        self.assertFalse(self.result(cond("stderr","not_empty"),env()))
        scope={"vars":{"yes":True,"no":False,"text":"Yes","zero":0,"list":[],"word":"nope"}}
        for name,expected in(("yes",True),("no",False),("text",True),("zero",False),("list",False),("word",False),("missing",False)):
            self.assertEqual(expected,self.result(cond("var","is_true",field=name),scope=scope),name)
            self.assertEqual(not expected,self.result(cond("var","is_false",field=name),scope=scope),name)
        self.assertTrue(self.result(cond("var","is_empty",field="missing"),scope=scope));self.assertTrue(self.result(cond("var","is_empty",field="list"),scope=scope))
        self.assertTrue(self.result(cond("var","not_empty",field="zero"),scope=scope))
    def test_var_and_template_value(self):
        scope={"vars":{"ip":"10.0.0.5","count":"12","want":"10.0.0.5"},"last":{"exit_code":3},"item":{"port":443}}
        self.assertTrue(self.result(cond("var","equals","10.0.0.5",field="ip"),scope=scope));self.assertTrue(self.result(cond("var","gt","10",field="count"),scope=scope))
        self.assertTrue(self.result(cond("var","equals","${want}",field="ip"),scope=scope));self.assertTrue(self.result(cond("var","eq","443",field="item.port"),scope=scope))
        self.assertTrue(self.result(cond("var","eq","3",field="last.exit_code"),scope=scope));self.assertFalse(self.result(cond("var","gt","1",field="ip"),scope=scope))
    def test_parsed_lists_test_any_element(self):
        data=env(parsed={"ports":[{"port":22,"service":"ssh"},{"port":80,"service":"http"}],"open_ports":[22,80],"alive":True,"name":"web"})
        self.assertTrue(self.result(cond("parsed","equals","80",field="ports[*].port"),data));self.assertFalse(self.result(cond("parsed","equals","8",field="ports[*].port"),data))
        self.assertTrue(self.result(cond("parsed","contains","HTT",field="ports[*].service"),data));self.assertTrue(self.result(cond("parsed","not_contains","smb",field="ports[*].service"),data))
        self.assertFalse(self.result(cond("parsed","not_equals","22",field="open_ports"),data));self.assertTrue(self.result(cond("parsed","gt","79",field="open_ports"),data))
        self.assertFalse(self.result(cond("parsed","gt","80",field="open_ports"),data));self.assertTrue(self.result(cond("parsed","regex","^s+h$",field="ports[*].service"),data))
        self.assertTrue(self.result(cond("parsed","is_true",field="alive"),data));self.assertTrue(self.result(cond("parsed","equals","web",field="name"),data))
        self.assertTrue(self.result(cond("parsed","not_empty"),data));self.assertTrue(self.result(cond("parsed","is_empty",field="nothing"),data))
        self.assertTrue(self.result(cond("parsed","is_empty"),env()))
    def test_line_and_match_count(self):
        data=env(stdout="a\n\nb\n",stderr="c")
        self.assertTrue(self.result(cond("line_count","eq","3"),data));self.assertTrue(self.result(cond("line_count","lt","4"),data))
        scan=env(stdout=NMAP)
        self.assertTrue(self.result(cond("match_count","eq","3",field=r"/tcp\s+open"),scan));self.assertTrue(self.result(cond("match_count","ge","1",field="HOST IS UP"),scan))
        self.assertFalse(self.result(cond("match_count","ge","1",field="HOST IS UP",ci=False),scan))
        self.assertFalse(rules.evaluate_condition(cond("match_count","ge","1",field=""),scan,{})["result"])
    def test_port_open(self):
        text=env(stdout=NMAP)
        for port,expected in(("22",True),("80",True),("445",True),("443",False),("3306",False),("8080",False)):
            self.assertEqual(expected,self.result(cond("port_open","is_true",port),text),port)
            self.assertEqual(not expected,self.result(cond("port_open","is_false",port),text),port)
        parsed=env(parsed=rules.parse_tool_output("nmap",NMAP))
        self.assertTrue(self.result(cond("port_open","is_true","445"),parsed));self.assertFalse(self.result(cond("port_open","is_true","443"),parsed))
        self.assertTrue(self.result(cond("port_open","is_true","${p}"),parsed,{"vars":{"p":80}}))
        self.assertTrue(self.result(cond("port_open","is_true","8443"),env(stdout="Discovered open port 8443/tcp on 10.0.0.5")))
        self.assertTrue(self.result(cond("port_open","is_true","21"),env(parsed={"ports":[{"port":21,"state":"open"},{"port":25,"state":"closed"}]})))
        self.assertFalse(self.result(cond("port_open","is_true","25"),env(parsed={"ports":[{"port":21,"state":"open"},{"port":25,"state":"closed"}]})))
        bad=rules.evaluate_condition(cond("port_open","is_true","http"),text,{})
        self.assertFalse(bad["result"]);self.assertIn("port number",bad["error"])
        self.assertEqual([22,80,445],rules.open_ports(text))
    def test_host_up(self):
        cases=[(PING_UP,True),(PING_DOWN,False),(PING_WIN_UP,True),(PING_WIN_UNREACHABLE,False),(PING_WIN_DOWN,False),(NMAP,True),("",False),
               ("Note: Host seems down. If it is really up, but blocking our ping probes, try -Pn",False),("Nmap done: 1 IP address (0 hosts up) scanned",False),
               ("3 packets transmitted, 1 received, 66% packet loss",True),("connect: Network is unreachable",False),("random words",False)]
        for text,expected in cases:
            self.assertEqual(expected,self.result(cond("host_up","is_true"),env(stdout=text)),text[:50])
            self.assertEqual(not expected,self.result(cond("host_up","is_false"),env(stdout=text)),text[:50])
        self.assertTrue(self.result(cond("host_up","is_true"),env(parsed={"alive":True})));self.assertFalse(self.result(cond("host_up","is_true"),env(stdout=PING_UP,parsed={"alive":False})))
        self.assertTrue(self.result(cond("host_up","is_true"),env(stderr="64 bytes from 1.1.1.1")))
    def test_result_shape_and_never_raises(self):
        found=rules.evaluate_condition(cond("stdout","contains","ttl="),env(stdout="x ttl=64"),{})
        self.assertEqual({"result":True,"actual":"x ttl=64","text":"stdout contains 'ttl='","error":""},found)
        self.assertLessEqual(len(rules.evaluate_condition(cond("stdout","contains","x"),env(stdout="x"*5000),{})["actual"]),210)
        for junk in(None,5,"x",{},{"source":"moon"},{"source":"stdout","op":"resembles"},{"source":"exit_code","op":"gt","value":"abc"},{"source":[],"op":{}}):
            for data in(None,5,env()):
                found=rules.evaluate_condition(junk,data,None)
                self.assertEqual({"result","actual","text","error"},set(found))
                self.assertIsInstance(found["result"],bool)
        self.assertTrue(rules.evaluate_condition({"source":"moon"},env(),{})["error"])
    def test_describe(self):
        cases=[(cond("output","contains","ttl="),"output contains 'ttl='"),(cond("exit_code","eq","0"),"exit code = 0"),(cond("port_open","is_true","80"),"port 80 is open"),
               (cond("port_open","is_false","80"),"port 80 is not open"),(cond("host_up","is_true"),"host is up"),(cond("host_up","is_false"),"host is down"),
               (cond("var","not_empty",field="ip"),"variable ip is not empty"),(cond("parsed","contains","80",field="ports[*].port"),"parsed ports[*].port contains '80'"),
               (cond("line_count","gt","3"),"number of output lines > 3"),(cond("match_count","ge","2",field="open"),"matches of /open/ >= 2"),
               (cond("stderr","not_regex","err\\d"),"stderr does not match /err\\d/"),(cond("stdout","not_equals","x"),"stdout is not 'x'"),(cond("stdout","is_empty"),"stdout is empty")]
        for condition,text in cases:self.assertEqual(text,rules.describe_condition(condition))
        self.assertEqual("invalid condition",rules.describe_condition(None))
        for source in rules.SOURCES:
            for op in rules.OPS:self.assertTrue(rules.describe_condition(cond(source,op,"1","f")))
    def test_source_and_op_lists_match_the_schema(self):
        from Cores.Services import flow_schema
        self.assertEqual(flow_schema.SOURCES,rules.SOURCES);self.assertEqual(flow_schema.OPS,rules.OPS)
        self.assertEqual(set(flow_schema.PARSE_TOOLS),set(rules.PARSERS));self.assertEqual(flow_schema.LIMITS["regex_chars"],rules.MAX_REGEX_CHARS)
class DecisionTests(RulesBase):
    CONFIG={"branches":[{"name":"web","match":"any","conditions":[cond("port_open","is_true","80"),cond("port_open","is_true","443")]},
                        {"name":"ssh-only","match":"all","conditions":[cond("port_open","is_true","22"),cond("output","not_contains","http")]},
                        {"name":"empty","match":"all","conditions":[]}],"else":"nothing"}
    def test_first_matching_branch_wins(self):
        found=rules.evaluate_decision(self.CONFIG,env(stdout=NMAP),{})
        self.assertEqual("web",found["branch"])
        self.assertEqual([{"branch":"web","matched":True}],[{"branch":t["branch"],"matched":t["matched"]} for t in found["trace"]])
        self.assertEqual([True,False],[c["result"] for c in found["trace"][0]["conditions"]])
    def test_all_needs_every_condition(self):
        self.assertEqual("ssh-only",rules.evaluate_decision(self.CONFIG,env(stdout="22/tcp open ssh"),{})["branch"])
        found=rules.evaluate_decision(self.CONFIG,env(stdout="22/tcp open ssh\n8080/tcp open http-proxy"),{})
        self.assertEqual("nothing",found["branch"])
        self.assertEqual(["web","ssh-only","empty"],[t["branch"] for t in found["trace"]])
        self.assertEqual([False,False,False],[t["matched"] for t in found["trace"]])
    def test_else_defaults_and_garbage(self):
        self.assertEqual("else",rules.evaluate_decision({"branches":[]},env(),{})["branch"])
        for junk in(None,5,{},{"branches":"x"},{"branches":[None,5,{"name":"a"}],"else":7}):
            found=rules.evaluate_decision(junk,None,None)
            self.assertEqual("else",found["branch"]);self.assertIsInstance(found["trace"],list)
    def test_template_host_alive_decision(self):
        from Cores.Services import flow_schema
        by={n["title"]:n for n in flow_schema.template("host-alive-portscan-web")["nodes"]}
        alive=by["Host alive?"]["config"];web=by["Web port open?"]["config"]
        self.assertEqual("alive",rules.evaluate_decision(alive,env(stdout=PING_UP),{})["branch"]);self.assertEqual("down",rules.evaluate_decision(alive,env(stdout=PING_DOWN,exit_code=1),{})["branch"])
        parsed=rules.run_parse(by["Read nmap ports"]["config"],env(stdout=NMAP),{})
        self.assertEqual([22,80,445],parsed["vars"]["open_ports"])
        self.assertEqual("web",rules.evaluate_decision(web,env(parsed=parsed["parsed"]),{})["branch"])
        self.assertEqual("no-web",rules.evaluate_decision(web,env(stdout="22/tcp open ssh"),{})["branch"])
        smb=[n for n in flow_schema.template("smb-null-session")["nodes"] if n["type"]=="decision"][0]["config"]
        self.assertEqual("open",rules.evaluate_decision(smb,env(stdout="\tSharename       Type      Comment\n\tIPC$            IPC       IPC Service"),{})["branch"])
        self.assertEqual("denied",rules.evaluate_decision(smb,env(stdout="session setup failed: NT_STATUS_ACCESS_DENIED",exit_code=1),{})["branch"])
class ParserTests(RulesBase):
    def test_nmap(self):
        parsed=rules.parse_tool_output("nmap",NMAP)
        self.assertEqual({"hosts","ports","open_ports"},set(parsed))
        self.assertEqual(["10.0.0.5","10.0.0.9"],[h["host"] for h in parsed["hosts"]])
        self.assertEqual([22,80,445],parsed["open_ports"])
        self.assertEqual([("10.0.0.5",22,"tcp","ssh"),("10.0.0.5",80,"tcp","http"),("10.0.0.9",445,"tcp","microsoft-ds")],[(p["host"],p["port"],p["proto"],p["service"]) for p in parsed["ports"]])
        self.assertIn("OpenSSH",parsed["ports"][0]["version"])
        self.assertEqual(4,len(parsed["hosts"][0]["ports"]))
        self.assertEqual({"hosts":[],"ports":[],"open_ports":[]},rules.parse_tool_output("nmap","nothing here"))
        json.dumps(parsed)
    def test_nmap_fallback_parser(self):
        hosts=rules._parse_nmap_basic(NMAP)
        self.assertEqual([22,80,445],[p["port"] for p in hosts[0]["ports"] if p["state"]=="open"])
    def test_ping(self):
        self.assertEqual({"alive":True,"sent":2,"received":2,"loss":0,"ttl":63},rules.parse_tool_output("ping",PING_UP))
        self.assertEqual({"alive":False,"sent":2,"received":0,"loss":100,"ttl":None},rules.parse_tool_output("ping",PING_DOWN))
        self.assertEqual({"alive":True,"sent":2,"received":2,"loss":0,"ttl":128},rules.parse_tool_output("ping",PING_WIN_UP.replace("\n","\r\n")))
        self.assertFalse(rules.parse_tool_output("ping",PING_WIN_UNREACHABLE)["alive"])
        self.assertEqual({"alive":False,"sent":2,"received":0,"loss":100,"ttl":None},rules.parse_tool_output("ping",PING_WIN_DOWN))
        self.assertEqual({"alive":False,"sent":0,"received":0,"loss":None,"ttl":None},rules.parse_tool_output("ping",""))
    def test_simple_parsers(self):
        self.assertEqual({"lines":["a","b"],"count":2},rules.parse_tool_output("lines"," a \n\n b\n"))
        self.assertEqual({"a":1},rules.parse_tool_output("json",'{"a":1}'));self.assertEqual({"items":[1,2],"count":2},rules.parse_tool_output("json","[1,2]"))
        self.assertEqual({"value":5},rules.parse_tool_output("json","5"));self.assertEqual({"ok":True},rules.parse_tool_output("json",'log line\n{"ok":true}\n'))
        self.assertEqual({"Host":"web","os":"Linux 5.x","url":"http://x/?a=b"},rules.parse_tool_output("keyvalue","Host: web\n# note: no\nos=Linux 5.x\nHost: second\nnothing\nurl: http://x/?a=b"))
        self.assertEqual({"ips":["10.0.0.5","192.168.1.10","8.8.8.8"],"count":3},rules.parse_tool_output("ips","10.0.0.5 and 192.168.1.10, 10.0.0.5 again; 999.1.1.1 no; 1.2.3.4.5 no; v1.2.3 no; 8.8.8.8."))
        self.assertEqual({"urls":["http://a.example/x?y=1","https://b.example"],"count":2},rules.parse_tool_output("urls",'see http://a.example/x?y=1, and "https://b.example". http://a.example/x?y=1'))
    def test_errors(self):
        with self.assertRaises(RuleError):rules.parse_tool_output("nessus","x")
        with self.assertRaises(RuleError):rules.parse_tool_output("json","not json")
        with self.assertRaises(RuleError):rules.parse_tool_output("json","  ")
        self.assertEqual({"nmap","ping","lines","json","keyvalue","ips","urls"},set(rules.PARSERS))
class RunParseTests(RulesBase):
    def test_regex_mode(self):
        config={"mode":"regex","source":"stdout","pattern":r"(?P<port>\d+)/(tcp|udp)\s+open","flags":"i","var":"parsed",
                "assign":[{"var":"port","from":"group:1"},{"var":"proto","from":"group:2"},{"var":"named","from":"group:port"},{"var":"whole","from":"match"},
                          {"var":"every","from":"all"},{"var":"n","from":"count"},{"var":"none","from":"group:9"},{"var":"bad name","from":"match"}]}
        found=rules.run_parse(config,env(stdout=NMAP),{})
        self.assertTrue(found["matched"]);self.assertEqual("",found["error"])
        self.assertEqual({"match":"22/tcp   open","groups":["22/tcp   open","22","tcp"],"named":{"port":"22"}},found["parsed"])
        self.assertEqual(("22","tcp","22","22/tcp   open",3,""),tuple(found["vars"][k] for k in("port","proto","named","whole","n","none")))
        self.assertEqual([["22","tcp"],["80","tcp"],["445","tcp"]],found["vars"]["every"])
        self.assertEqual(found["parsed"],found["vars"]["parsed"]);self.assertNotIn("bad name",found["vars"])
    def test_regex_no_match_and_errors(self):
        self.assertEqual({"matched":False,"vars":{},"parsed":None,"error":""},rules.run_parse({"mode":"regex","pattern":"zzz"},env(stdout="abc"),{}))
        bad=rules.run_parse({"mode":"regex","pattern":"(a+)+$"},env(stdout="aaa"),{})
        self.assertFalse(bad["matched"]);self.assertIn("forever",bad["error"])
        self.assertTrue(rules.run_parse({"mode":"regex","pattern":""},env(),{})["error"])
        self.assertTrue(rules.run_parse({"mode":"xml"},env(),{})["error"])
        for junk in(None,5,{},{"mode":"tool","tool":"nope"},{"mode":"jsonpath"}):
            found=rules.run_parse(junk,None,None)
            self.assertEqual({"matched","vars","parsed","error"},set(found));self.assertFalse(found["matched"])
    def test_sources(self):
        data=env(stdout="out 1",stderr="err 2")
        scope={"vars":{"blob":"var 3"},"nodes":{"n2":{"stdout":"node 4"}}}
        for source,expected in(("stdout","1"),("stderr","2"),("output","1"),("blob","3"),("var:blob","3"),("nodes.n2.stdout","4")):
            self.assertEqual(expected,rules.run_parse({"mode":"regex","source":source,"pattern":r"(\d)","assign":[{"var":"d","from":"group:1"}]},data,scope)["vars"]["d"],source)
        self.assertFalse(rules.run_parse({"mode":"regex","source":"missing","pattern":"."},data,scope)["matched"])
    def test_tool_mode(self):
        found=rules.run_parse({"mode":"tool","tool":"nmap","var":"scan","assign":[{"var":"ports","from":"open_ports"},{"var":"first","from":"ports[0].service"},{"var":"hosts","from":"path:hosts[*].host"}]},env(stdout=NMAP),{})
        self.assertTrue(found["matched"])
        self.assertEqual(([22,80,445],"ssh",["10.0.0.5","10.0.0.9"]),(found["vars"]["ports"],found["vars"]["first"],found["vars"]["hosts"]))
        self.assertEqual(found["parsed"],found["vars"]["scan"])
        self.assertFalse(rules.run_parse({"mode":"tool","tool":"nmap"},env(stdout="no ports"),{})["matched"])
        down=rules.run_parse({"mode":"tool","tool":"ping","assign":[{"var":"alive","from":"alive"}]},env(stdout=PING_DOWN),{})
        self.assertTrue(down["matched"]);self.assertIs(False,down["vars"]["alive"])
        self.assertFalse(rules.run_parse({"mode":"tool","tool":"ping"},env(stdout=""),{})["matched"])
        self.assertFalse(rules.run_parse({"mode":"tool","tool":"ips"},env(stdout="none"),{})["matched"])
    def test_jsonpath_mode(self):
        text=json.dumps({"results":[{"url":"http://a","status":200},{"url":"http://b","status":403}],"meta":{"total":2}})
        found=rules.run_parse({"mode":"jsonpath","path":"$.results[*].url","var":"urls","assign":[{"var":"first","from":"[0]"},{"var":"all","from":"value"}]},env(stdout=text),{})
        self.assertEqual((True,["http://a","http://b"],"http://a",["http://a","http://b"]),(found["matched"],found["vars"]["urls"],found["vars"]["first"],found["vars"]["all"]))
        self.assertEqual(2,rules.run_parse({"mode":"jsonpath","path":"meta.total","var":"t"},env(stdout=text),{})["vars"]["t"])
        self.assertFalse(rules.run_parse({"mode":"jsonpath","path":"meta.nope"},env(stdout=text),{})["matched"])
        self.assertEqual({"a":1},rules.run_parse({"mode":"jsonpath","path":"[1]","var":"v"},env(stdout='[{"a":0},{"a":1}]'),{})["vars"]["v"])
        bad=rules.run_parse({"mode":"jsonpath","path":"a"},env(stdout="not json"),{})
        self.assertFalse(bad["matched"]);self.assertIn("JSON",bad["error"])
class SplitItemsTests(unittest.TestCase):
    def test_modes(self):
        split=rules.split_items
        self.assertEqual(["a","b","c"],split("a\n\n b \r\nc\n","lines",50));self.assertEqual(["22","80","443"],split("22, 80,,443 ","comma",50))
        self.assertEqual([1,{"a":2}],split('[1,{"a":2}]',"json",50));self.assertEqual([{"a":1}],split('{"a":1}',"json",50));self.assertEqual([],split("not json","json",50))
        self.assertEqual([1,2],split("[1,2]","auto",50));self.assertEqual(["a","b"],split("a\nb","auto",50));self.assertEqual(["a","b"],split("a,b","auto",50))
        self.assertEqual(["one item"],split("one item","auto",50));self.assertEqual(["[broken"],split("[broken","auto",50));self.assertEqual(["a,b","c"],split("a,b\nc","auto",50))
    def test_lists_and_limits(self):
        split=rules.split_items
        self.assertEqual([1,2,3],split([1,2,3,4,5],"auto",3));self.assertEqual(["0","1"],split("0\n1\n2\n3","lines",2));self.assertEqual([0,1],split("[0,1,2]","json",2))
        self.assertEqual([],split(None,"auto",5));self.assertEqual([],split("  ","lines",5));self.assertEqual([{"a":1}],split({"a":1},"auto",5));self.assertEqual([7],split(7,"auto",5))
        self.assertEqual(1000,len(split(list(range(5000)),"auto",10**9)));self.assertEqual(1,len(split([1,2],"auto",0)));self.assertEqual(50,len(split(list(range(99)),"auto","x")))
        self.assertEqual((1,2),tuple(split((1,2),"auto",5)))
    def test_with_resolve_value(self):
        scope={"vars":{"parsed":rules.parse_tool_output("nmap",NMAP)}}
        value,_=rules.resolve_value("${parsed.ports}",scope)
        self.assertEqual([22,80,445],[item["port"] for item in rules.split_items(value,"auto",50)])
        text,_=rules.expand_template("${parsed.open_ports}",scope)
        self.assertEqual(["22","80","445"],rules.split_items(text,"auto",50))
        text,_=rules.expand_template("${parsed.ports}",scope)
        self.assertEqual([22,80,445],[item["port"] for item in rules.split_items(text,"auto",50)])
if __name__=="__main__":unittest.main()
