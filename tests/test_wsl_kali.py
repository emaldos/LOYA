"""Kali Linux on WSL: edition/build gating, .wslconfig merge, network validation, the wizard state machine (including resume after a
restart), the argv each step builds, no injection, rollback and lock refusal. subprocess is never really run."""
import os,sys,json,base64,types,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import wsl_kali_service as wsl
from Cores.Services import terminal_service
WIN_PRO={"name":"Windows 11 Pro","edition":"Pro","is_home":False,"build":22631,"ubr":4000}
WIN_HOME={"name":"Windows 11 Home","edition":"Home","is_home":True,"build":22631,"ubr":4000}
WSL_OK={"ok":True,"version":"2.6.1.0","distros":["kali-linux"]}
HV_SW={"module":True,"switches":["LAN"],"needs_admin":False}
def decode_ps(argv):
    return base64.b64decode(argv[argv.index("-EncodedCommand")+1]).decode("utf-16-le")
class EditionAndBuildTests(unittest.TestCase):
    def fake_winreg(self,values):
        mod=types.ModuleType("winreg")
        mod.HKEY_LOCAL_MACHINE=1
        class Key:
            def __enter__(s):return s
            def __exit__(s,*a):return False
        mod.OpenKey=lambda *a:Key()
        def query(key,name):
            if name in values:return (values[name],1)
            raise OSError(name)
        mod.QueryValueEx=query
        return mod
    def info(self,values):
        with mock.patch.object(wsl,"_IS_WINDOWS",True),mock.patch.dict(sys.modules,{"winreg":self.fake_winreg(values)}):
            return wsl.windows_info()
    def test_registry_detection(self):
        home=self.info({"EditionID":"Core","CurrentBuild":"22631","UBR":4317,"DisplayVersion":"23H2"})
        self.assertTrue(home["is_home"]);self.assertEqual("Windows 11 Home",home["name"]);self.assertEqual(22631,home["build"]);self.assertEqual(4317,home["ubr"])
        self.assertEqual("Home",self.info({"EditionID":"CoreSingleLanguage","CurrentBuild":"22631"})["edition"])
        pro=self.info({"EditionID":"Professional","CurrentBuild":"26100"})
        self.assertFalse(pro["is_home"]);self.assertEqual("Windows 11 Pro",pro["name"])
        self.assertEqual("Education",self.info({"EditionID":"Education","CurrentBuild":"22631"})["edition"])
        self.assertEqual("Enterprise",self.info({"EditionID":"EnterpriseS","CurrentBuild":"22631"})["edition"])
        old=self.info({"EditionID":"Professional","CurrentBuild":"19045"})
        self.assertEqual("Windows 10 Pro",old["name"])
    def test_home_greys_out_bridged_and_custom_with_the_reason(self):
        a=wsl.mode_availability(WIN_HOME,WSL_OK,HV_SW)
        self.assertTrue(a["nat"]["available"]);self.assertTrue(a["mirrored"]["available"])
        for mode in ("bridged","custom"):
            self.assertFalse(a[mode]["available"])
            self.assertIn("Windows 11 Home because it needs Hyper-V, which Home doesn't include",a[mode]["reason"])
        self.assertTrue(a["bridged"]["reason"].startswith("Separate device on the network won't work"))
    def test_old_build_greys_out_mirrored(self):
        a=wsl.mode_availability(dict(WIN_PRO,build=19045,name="Windows 10 Pro"),WSL_OK,HV_SW)
        self.assertFalse(a["mirrored"]["available"])
        self.assertIn("build 19045",a["mirrored"]["reason"]);self.assertIn("22H2",a["mirrored"]["reason"])
        self.assertFalse(a["bridged"]["available"])
    def test_unpatched_22h2_greys_out_mirrored_only(self):
        a=wsl.mode_availability(dict(WIN_PRO,build=22621,ubr=1000),WSL_OK,HV_SW)
        self.assertFalse(a["mirrored"]["available"]);self.assertIn("22621.2359",a["mirrored"]["reason"])
        self.assertTrue(a["bridged"]["available"])
        self.assertTrue(wsl.mode_availability(dict(WIN_PRO,build=22621,ubr=2359),WSL_OK,HV_SW)["mirrored"]["available"])
    def test_pro_without_hyperv_or_switch_explains_and_never_offers_to_create(self):
        a=wsl.mode_availability(WIN_PRO,WSL_OK,{"module":False,"switches":[]})
        self.assertFalse(a["bridged"]["available"]);self.assertIn("Hyper-V",a["bridged"]["reason"])
        a=wsl.mode_availability(WIN_PRO,WSL_OK,{"module":True,"switches":[]})
        self.assertFalse(a["custom"]["available"])
        self.assertIn("LOYA does not create switches",a["custom"]["reason"])
        a=wsl.mode_availability(WIN_PRO,WSL_OK,{"module":True,"switches":[],"needs_admin":True})
        self.assertTrue(a["bridged"].get("needs_lookup"))
        self.assertTrue(wsl.mode_availability(WIN_PRO,WSL_OK,HV_SW)["custom"]["available"])
    def test_deprecated_bridged_versions_warn(self):
        a=wsl.mode_availability(WIN_PRO,dict(WSL_OK,version="2.4.8.0"),HV_SW)
        self.assertTrue(a["bridged"]["available"]);self.assertIn("deprecated",a["bridged"]["warning"])
        self.assertNotIn("warning",wsl.mode_availability(WIN_PRO,dict(WSL_OK,version="2.5.6.0"),HV_SW)["bridged"])
    def test_without_wsl_only_nat(self):
        a=wsl.mode_availability(WIN_PRO,{"ok":False,"version":""},HV_SW)
        self.assertEqual(["nat"],[m for m in wsl.MODES if a[m]["available"]])
    def test_wsl_version_parse(self):
        self.assertEqual("2.6.1.0",wsl.parse_wsl_version("WSL version: 2.6.1.0\nKernel version: 6.6.87.2-1"))
        self.assertEqual("",wsl.parse_wsl_version("bad"))
    def test_switch_output_parse(self):
        self.assertEqual((["LAN"],False,""),wsl.parse_switch_output('"LAN"'))
        self.assertEqual((["A","B"],False,""),wsl.parse_switch_output('["A","B"]'))
        names,admin,_=wsl.parse_switch_output("LOYA_ERR:You do not have the required permission to complete this task.")
        self.assertIsNone(names);self.assertTrue(admin)
        self.assertEqual([],wsl.parse_switch_output('["bad\\"name"]')[0])
class WslconfigMergeTests(unittest.TestCase):
    SAMPLE="# my settings\n[wsl2]\nmemory=8GB  \n; keep me\nNetworkingMode = nat\nswap=0\nnetworkingMode=mirrored\nkernelCommandLine = quiet\n\n[experimental]\nautoMemoryReclaim=gradual\n"
    def test_merge_keeps_unknown_keys_comments_and_sections(self):
        out=wsl.ini_merge(self.SAMPLE,"wsl2",{"networkingMode":"bridged","vmSwitch":"LAN","dhcp":None})
        for kept in ("# my settings","memory=8GB  ","; keep me","swap=0","kernelCommandLine = quiet","[experimental]","autoMemoryReclaim=gradual"):self.assertIn(kept,out)
        self.assertEqual(1,out.lower().count("networkingmode"))
        self.assertIn("NetworkingMode=bridged",out)
        self.assertLess(out.index("vmSwitch=LAN"),out.index("[experimental]"))
        self.assertEqual("bridged",wsl.ini_get(out,"wsl2","networkingMode"))
    def test_remove_and_create_section(self):
        out=wsl.ini_merge("[experimental]\nx=1\n","wsl2",{"networkingMode":"mirrored","vmSwitch":None})
        self.assertIn("[experimental]\nx=1\n\n[wsl2]\nnetworkingMode=mirrored\n",out)
        self.assertEqual("[wsl2]\nnetworkingMode=nat\n",wsl.ini_merge("","wsl2",{"networkingMode":"nat","dhcp":None}))
        out=wsl.ini_merge("[wsl2]\nvmSwitch=LAN\nmemory=1GB\n","wsl2",{"vmSwitch":None})
        self.assertEqual("[wsl2]\nmemory=1GB\n",out)
    def test_crlf_is_kept(self):
        out=wsl.ini_merge("[wsl2]\r\nmemory=1GB\r\n","wsl2",{"networkingMode":"nat"})
        self.assertEqual("[wsl2]\r\nmemory=1GB\r\nnetworkingMode=nat\r\n",out)
    def test_updates_per_mode(self):
        self.assertEqual({"networkingMode":"mirrored","vmSwitch":None,"dhcp":None,"macAddress":None},wsl.wslconfig_updates({"mode":"mirrored"}))
        self.assertEqual({"networkingMode":"bridged","vmSwitch":"LAN","dhcp":"false","macAddress":"00:15:5d:01:02:03"},wsl.wslconfig_updates({"mode":"custom","switch":"LAN","mac":"00:15:5d:01:02:03"}))
        self.assertEqual("nat",wsl.wslconfig_updates({"mode":"nat"})["networkingMode"])
    def test_write_backs_up_and_restores(self):
        iso=IsolatedData();d=iso.start()
        try:
            path=os.path.join(d,".wslconfig")
            with open(path,"w",encoding="utf-8",newline="") as f:f.write(self.SAMPLE)
            backup,prior=wsl.write_wslconfig({"networkingMode":"mirrored","vmSwitch":None},path)
            self.assertTrue(os.path.isfile(backup))
            self.assertEqual("mirrored",prior["networkingMode"]);self.assertIsNone(prior["vmSwitch"])
            with open(backup,encoding="utf-8") as f:self.assertEqual(self.SAMPLE,f.read())
            text,_,_=wsl.read_wslconfig(path)
            self.assertIn("kernelCommandLine = quiet",text)
            self.assertTrue(wsl.restore_wslconfig(backup,path))
            with open(path,encoding="utf-8") as f:self.assertEqual(self.SAMPLE,f.read())
            fresh=os.path.join(d,"new.wslconfig")
            backup,_=wsl.write_wslconfig({"networkingMode":"nat"},fresh)
            self.assertEqual("absent",backup);self.assertTrue(os.path.isfile(fresh))
            wsl.restore_wslconfig(backup,fresh);self.assertFalse(os.path.exists(fresh))
            u16=os.path.join(d,"u16.wslconfig")
            with open(u16,"w",encoding="utf-16") as f:f.write("[wsl2]\nmemory=2GB\n")
            wsl.write_wslconfig({"networkingMode":"nat"},u16)
            with open(u16,"rb") as f:self.assertEqual(b"\xff\xfe",f.read(2))
            self.assertEqual("nat",wsl.ini_get(wsl.read_wslconfig(u16)[0],"wsl2","networkingMode"))
        finally:iso.stop()
class ValidationTests(unittest.TestCase):
    GOOD={"mode":"custom","switch":"LAN","ip":"192.168.1.50","prefix":"24","gateway":"192.168.1.1","dns":"1.1.1.1, 9.9.9.9","mac":"00-15-5D-AA-BB-CC"}
    def test_good_custom(self):
        net=wsl.validate_network(self.GOOD,["LAN"])
        self.assertEqual({"mode":"custom","switch":"LAN","mac":"00:15:5d:aa:bb:cc","ip":"192.168.1.50","prefix":24,"mask":"255.255.255.0","gateway":"192.168.1.1","dns":["1.1.1.1","9.9.9.9"]},net)
    def test_mask_and_slash_forms(self):
        self.assertEqual(16,wsl.validate_network(dict(self.GOOD,prefix="255.255.0.0"),["LAN"])["prefix"])
        self.assertEqual(24,wsl.validate_network(dict(self.GOOD,prefix="/24"),["LAN"])["prefix"])
        self.assertEqual(24,wsl.validate_network(dict(self.GOOD,prefix="",mask="255.255.255.0"),["LAN"])["prefix"])
    def bad(self,**change):
        with self.assertRaises(ValueError):wsl.validate_network(dict(self.GOOD,**change),["LAN"])
    def test_rejections(self):
        self.bad(gateway="10.0.0.1")
        self.bad(ip="192.168.1.0");self.bad(ip="192.168.1.255")
        self.bad(gateway="192.168.1.50")
        self.bad(ip="192.168.1.300");self.bad(ip="192.168.001.5");self.bad(ip="127.0.0.1");self.bad(ip="224.0.0.1")
        self.bad(prefix="255.0.255.0");self.bad(prefix="33");self.bad(prefix="31");self.bad(prefix="abc")
        self.bad(dns="");self.bad(dns="1.1.1.1,8.8.8.8,9.9.9.9,8.8.4.4");self.bad(dns="dns.google")
        self.bad(mac="01:15:5d:aa:bb:cc");self.bad(mac="00:15:5d:aa:bb");self.bad(mac="00:15-5d:aa:bb:cc");self.bad(mac="00:00:00:00:00:00")
        self.bad(switch="Other");self.bad(mode="hacker")
    def test_injection_attempts_are_rejected(self):
        for field in ("ip","gateway","prefix","dns","mac","switch"):
            for payload in ("1.2.3.4; rm -rf /","$(reboot)","1.2.3.4\nnameserver 6.6.6.6","LAN' ; Remove-Item C:\\ -Recurse ; '","`calc`"):
                with self.assertRaises(ValueError,msg=field+" "+payload):wsl.validate_network(dict(self.GOOD,**{field:payload}),None if field=="switch" else ["LAN"])
        with self.assertRaises(ValueError):wsl.validate_network(dict(self.GOOD,ip=["1.2.3.4"]),["LAN"])
        with self.assertRaises(ValueError):wsl.validate_network("mode=nat")
    def test_simple_modes_drop_extra_fields(self):
        self.assertEqual({"mode":"mirrored"},wsl.validate_network({"mode":"Mirrored","ip":"$(x)"}))
        self.assertEqual({"mode":"bridged","switch":"LAN","mac":""},wsl.validate_network({"mode":"bridged","switch":"LAN"},["LAN"]))
    def test_usernames(self):
        self.assertEqual("kali_1",wsl.parse_username("kali_1"))
        for bad in ("root","Kali","1abc","a;b","bob rm","-rf","a"*33,"bob\n",""):
            with self.assertRaises(ValueError,msg=bad):wsl.parse_username(bad)
class ArgvTests(unittest.TestCase):
    def test_step_argvs(self):
        self.assertEqual(["wsl.exe","--install","-d","kali-linux"],wsl.distro_install_argv())
        self.assertEqual(["wsl.exe","--install","-d","kali-linux","--web-download"],wsl.distro_install_argv(True))
        self.assertEqual(["wsl.exe","-d","kali-linux"],wsl.first_run_argv())
        self.assertEqual(["wsl.exe","--shutdown"],wsl.restart_argv())
        argv=wsl.feature_install_argv()
        self.assertEqual("powershell.exe",argv[0]);self.assertIn("-EncodedCommand",argv)
        script=decode_ps(argv)
        self.assertIn("Start-Process -FilePath 'wsl.exe' -Verb RunAs",script)
        self.assertIn("-ArgumentList @('--install','--no-distribution')",script)
    def test_adduser_passes_the_name_as_an_argument_not_in_the_script(self):
        argv=wsl.adduser_argv("pentester")
        self.assertEqual(["wsl.exe","-d","kali-linux","-u","root","--","sh","-c",'adduser -- "$1" && usermod -aG sudo -- "$1"',"sh","pentester"],argv)
        with self.assertRaises(ValueError):wsl.adduser_argv("x; rm -rf /")
    def test_file_content_goes_on_stdin(self):
        calls=[]
        with mock.patch.object(wsl,"_run",side_effect=lambda argv,timeout=30,input_text=None:calls.append((argv,input_text)) or (0,"")):
            wsl.distro_write(wsl.RESOLV_CONF,"nameserver 1.1.1.1\n")
        argv,stdin=calls[0]
        self.assertEqual("nameserver 1.1.1.1\n",stdin)
        self.assertFalse(any("nameserver" in a for a in argv))
        self.assertEqual(["wsl.exe","-d","kali-linux","-u","root","--","sh","-c"],argv[:8])
        self.assertEqual(["sh",wsl.RESOLV_CONF,"0644"],argv[9:])
    def test_ps_literal_doubles_every_quote(self):
        self.assertEqual("'it''s'",wsl.ps_literal("it's"))
        self.assertEqual("'a\u2019\u2019b'",wsl.ps_literal("a\u2019b"))
        with self.assertRaises(ValueError):wsl.ps_literal("a\nb")
    def test_static_files_come_from_validated_values(self):
        net=wsl.validate_network(ValidationTests.GOOD,["LAN"])
        script=wsl.static_ip_script(net)
        self.assertIn("ip -4 addr add 192.168.1.50/24 dev eth0\n",script)
        self.assertIn("ip -4 route replace default via 192.168.1.1 dev eth0\n",script)
        self.assertEqual("# Written by LOYA NG (Kali Linux on WSL, Custom IP)\nnameserver 1.1.1.1\nnameserver 9.9.9.9\n",wsl.resolv_conf(net))
        with self.assertRaises(ValueError):wsl.static_ip_script(dict(net,ip="1.2.3.4; reboot"))
    def test_distro_static_plan_and_revert(self):
        conf,prior=wsl.plan_distro_static("[boot]\nsystemd=true\n[user]\ndefault=kali\n")
        self.assertEqual(wsl.STATIC_SCRIPT,wsl.ini_get(conf,"boot","command"))
        self.assertEqual("false",wsl.ini_get(conf,"network","generateResolvConf"))
        self.assertIn("systemd=true",conf);self.assertIn("default=kali",conf)
        self.assertEqual({"boot_command":None,"generateResolvConf":None},prior)
        back=wsl.plan_distro_revert(conf,prior)
        self.assertIsNone(wsl.ini_get(back,"boot","command"));self.assertIsNone(wsl.ini_get(back,"network","generateResolvConf"))
        self.assertIn("default=kali",back)
        with self.assertRaises(ValueError):wsl.plan_distro_static("[boot]\ncommand=service ssh start\n")
    def test_ip_parsing(self):
        out=wsl.parse_addresses("2: eth0    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0\\       valid_lft forever")
        self.assertEqual([{"interface":"eth0","ip":"192.168.1.50","prefix":24}],out)
        self.assertEqual("192.168.1.1",wsl.parse_default_gateway("default via 192.168.1.1 dev eth0 proto kernel"))
        self.assertEqual("",wsl.parse_default_gateway("default via 999.1.1.1 dev eth0"))
class WizardTests(unittest.TestCase):
    def step(self,configured=False,**wiz):
        return {"configured":configured,"wizard":dict({"active":True},**wiz)}
    def test_state_machine(self):
        facts={"wsl_ok":False,"kali_installed":False,"user_ready":False,"boot_id":100}
        self.assertEqual("idle",wsl.compute_step({"configured":False,"wizard":{}},facts))
        self.assertEqual("prereq",wsl.compute_step(self.step(),facts))
        self.assertEqual("reboot",wsl.compute_step(self.step(reboot_pending=True,boot_id=100),facts))
        self.assertEqual("reboot",wsl.compute_step(self.step(reboot_pending=True,boot_id=101),facts))
        self.assertEqual("prereq",wsl.compute_step(self.step(reboot_pending=True,boot_id=50),facts),"restarted but WSL still missing")
        facts["wsl_ok"]=True
        self.assertEqual("install",wsl.compute_step(self.step(reboot_pending=True,boot_id=50),facts),"resumes after the restart")
        facts["kali_installed"]=True
        self.assertEqual("user",wsl.compute_step(self.step(),facts))
        facts["user_ready"]=True
        self.assertEqual("network",wsl.compute_step(self.step(),facts))
        self.assertEqual("verify",wsl.compute_step(self.step(network_applied=True),facts))
        self.assertEqual("done",wsl.compute_step(self.step(network_applied=True,verified=True),facts))
        self.assertEqual("done",wsl.compute_step(self.step(configured=True),facts))
class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        common_db.set_locked(False)
        self.home=os.path.join(self.dir,"home");os.makedirs(self.home)
        self.patches=[mock.patch.object(wsl,"_IS_WINDOWS",True),mock.patch.dict(os.environ,{"USERPROFILE":self.home}),mock.patch.object(wsl,"_SHUTDOWN_SETTLE_SECONDS",0),
                      mock.patch.object(wsl,"_run_job",side_effect=self.sync_job),mock.patch.object(wsl,"_audit",side_effect=lambda e,d="",s=True:self.audit.append((e,s))),
                      mock.patch.object(wsl,"windows_info",return_value=WIN_PRO),mock.patch.object(wsl,"hyperv_info",return_value=HV_SW),mock.patch.object(wsl,"boot_id",return_value=100),
                      mock.patch.object(terminal_service,"close_wsl_sessions",return_value=[]),mock.patch.object(wsl.shutil,"which",side_effect=lambda n:"C:\\Windows\\System32\\"+n if n=="wsl.exe" else None)]
        for p in self.patches:p.start()
        self.audit=[];self.calls=[];self.kali_starts=True;self.wsl_ok=True;self.distros=["kali-linux"];self.files={"/etc/wsl.conf":"[user]\ndefault=kali\n"}
        mock.patch.object(wsl,"_run",side_effect=self.fake_run).start()
        self.addCleanup(mock.patch.stopall)
    def tearDown(self):
        common_db.set_locked(False)
        self.iso.stop()
    def sync_job(self,job,fn):
        try:job["result"]=fn(job);job["state"]="done"
        except Exception as e:job["state"]="failed";job["error"]=str(e)
        return {"job_id":job["id"]}
    def fake_run(self,argv,timeout=30,input_text=None):
        self.calls.append((list(argv),input_text))
        a=list(argv)
        if a[:2]==["wsl.exe","--status"]:return (0,"Default Version: 2") if self.wsl_ok else (1,"not installed")
        if a[:2]==["wsl.exe","--version"]:return 0,"WSL version: 2.6.1.0"
        if a[:3]==["wsl.exe","--list","--quiet"]:return 0,"\n".join(self.distros)
        if a[:3]==["wsl.exe","--list","--running"]:return 0,""
        if a[:2]==["wsl.exe","--shutdown"]:return 0,""
        if a[:4]==["wsl.exe","-d","kali-linux","--"] and a[4:]==["true"]:return (0,"") if self.kali_starts else (1,"boom")
        if a[:4]==["wsl.exe","-d","kali-linux","--"] and a[4:6]==["id","-u"]:return 0,"1000"
        if a[:4]==["wsl.exe","-d","kali-linux","--"] and a[4]=="ip":return 0,"2: eth0    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0"
        if a[:6]==["wsl.exe","-d","kali-linux","-u","root","--"]:
            rest=a[6:]
            if rest[:2]==["ip","-4"]:return 0,"default via 192.168.1.1 dev eth0"
            if rest[0] in ("ping","getent","rm"):return 0,"104.18.4.159 kali.org"
            if rest[:2]==["sh","-c"]:
                script=rest[2];path=rest[4] if len(rest)>4 else ""
                if "cat > " in script:self.files[path]=input_text;return 0,""
                if "cat --" in script:return 0,self.files.get(path,"")
                return 0,""
        if a[:2]==["wsl.exe","--unregister"]:return 0,""
        return 0,""
    def wslconfig(self):
        with open(os.path.join(self.home,".wslconfig"),encoding="utf-8") as f:return f.read()
    def enable(self):
        wsl.set_enabled(True,True)
class ServiceTests(ServiceCase):
    def test_enable_needs_the_notes_acknowledged(self):
        with self.assertRaises(ValueError):wsl.set_enabled(True,False)
        self.assertTrue(wsl.set_enabled(True,True)["enabled"])
        self.assertIn(("wsl_kali_enabled",True),self.audit)
    def test_everything_refuses_while_locked(self):
        self.enable()
        common_db.set_locked(True)
        for fn in (lambda:wsl.set_enabled(True,True),wsl.wizard_start,wsl.enable_feature,lambda:wsl.apply_network({"mode":"nat"},True),wsl.restart,lambda:wsl.remove_setup(False,"",True),lambda:wsl.task_command("wsl_install_kali",{}),lambda:wsl.set_default_user("kali"),wsl.lookup_switches_elevated):
            with self.assertRaises(ValueError) as ctx:fn()
            self.assertIn("locked",str(ctx.exception))
        self.assertEqual([],[c for c in self.calls if c[0][:2]!=["wsl.exe","--status"]])
    def test_nothing_runs_before_the_option_is_on(self):
        with self.assertRaises(ValueError):wsl.wizard_start()
        with self.assertRaises(ValueError):wsl.task_command("wsl_install_kali",{})
        with self.assertRaises(ValueError):wsl.apply_network({"mode":"nat"},True)
        self.assertEqual([],self.calls)
    def test_linux_refuses(self):
        with mock.patch.object(wsl,"_IS_WINDOWS",False):
            self.assertFalse(wsl.status()["supported"])
            with self.assertRaises(ValueError):wsl.set_enabled(True,True)
    def test_task_sessions(self):
        self.enable()
        spec=wsl.task_command("wsl_install_kali",{"web_download":True})
        self.assertEqual(["wsl.exe","--install","-d","kali-linux","--web-download"],spec["argv"]);self.assertTrue(spec["conpty"])
        self.assertEqual("1",spec["env"]["WSL_UTF8"])
        self.assertEqual(["wsl.exe","--install","-d","kali-linux"],wsl.task_command("wsl_install_kali",{"web_download":"yes"})["argv"])
        with self.assertRaises(ValueError):wsl.task_command("wsl_kali_session",{})
        with self.assertRaises(ValueError):wsl.task_command("whoami",{})
    def test_wizard_resumes_after_reboot(self):
        self.enable();wsl.wizard_start()
        self.wsl_ok=False;self.distros=[]
        self.assertEqual("prereq",wsl.status()["step"])
        with mock.patch.object(wsl,"wsl_info",return_value={"ok":False,"present":True,"version":"","status":"","distros":[]}):
            job=wsl.enable_feature()
        self.assertTrue(wsl.get_state()["wizard"]["reboot_pending"])
        self.assertEqual("reboot",wsl.status()["step"])
        argv=[c[0] for c in self.calls if c[0][0]=="powershell.exe"][0]
        self.assertIn("'--install','--no-distribution'",decode_ps(argv))
        # Windows restarted: a new boot id, WSL now answers.
        self.wsl_ok=True
        with mock.patch.object(wsl,"boot_id",return_value=900):
            st=wsl.status()
        self.assertEqual("install",st["step"]);self.assertFalse(wsl.get_state()["wizard"]["reboot_pending"])
        self.distros=["kali-linux"]
        self.assertEqual("network",wsl.status()["step"])
    def test_cancelled_uac_is_reported(self):
        self.enable()
        with mock.patch.object(wsl,"_run",return_value=(1223,"")):
            res=wsl.enable_feature()
        self.assertEqual("failed",wsl.job_status(res["job_id"])["state"])
        self.assertIn(("wsl_feature_install",False),self.audit)
    def test_apply_custom_writes_backups_files_and_restarts(self):
        with open(os.path.join(self.home,".wslconfig"),"w",encoding="utf-8") as f:f.write("[wsl2]\nmemory=6GB\n# mine\n")
        self.enable();wsl.wizard_start()
        with self.assertRaises(ValueError):wsl.apply_network(ValidationTests.GOOD,False)
        res=wsl.apply_network(ValidationTests.GOOD,True)
        job=wsl.job_status(res["job_id"])
        self.assertEqual("done",job["state"],job["error"])
        text=self.wslconfig()
        self.assertIn("memory=6GB",text);self.assertIn("# mine",text)
        self.assertEqual("bridged",wsl.ini_get(text,"wsl2","networkingMode"));self.assertEqual("LAN",wsl.ini_get(text,"wsl2","vmSwitch"));self.assertEqual("false",wsl.ini_get(text,"wsl2","dhcp"))
        self.assertTrue(any(n.startswith(".wslconfig.loya-backup-") for n in os.listdir(self.home)))
        self.assertIn("ip -4 addr add 192.168.1.50/24",self.files[wsl.STATIC_SCRIPT])
        self.assertIn("nameserver 9.9.9.9",self.files[wsl.RESOLV_CONF])
        self.assertEqual(wsl.STATIC_SCRIPT,wsl.ini_get(self.files[wsl.WSL_CONF],"boot","command"))
        self.assertIn("default=kali",self.files[wsl.WSL_CONF])
        self.assertIn(["wsl.exe","--shutdown"],[c[0] for c in self.calls])
        self.assertTrue(any(c[0][-2:]==["ping","-c"] or c[0][6:8]==["ping","-c"] for c in self.calls))
        for argv,_ in self.calls:
            self.assertFalse(any("nameserver" in a or "ip -4 addr add" in a for a in argv),argv)
        state=wsl.get_state()
        self.assertTrue(state["configured"]);self.assertEqual("custom",state["network"]["mode"])
        self.assertEqual({"networkingMode":None,"vmSwitch":None,"dhcp":None,"macAddress":None},state["wslconfig_prior"])
        self.assertTrue(job["result"]["verify"]["gateway_ok"]);self.assertTrue(job["result"]["verify"]["dns_ok"])
        self.assertIn(("wsl_network_mode",True),self.audit)
        self.assertTrue(wsl.is_ready_for_sessions())
        # Later: switch to mirrored with the Update button; the custom IP inside Kali is undone.
        res=wsl.apply_network({"mode":"mirrored"},True)
        self.assertEqual("done",wsl.job_status(res["job_id"])["state"])
        text=self.wslconfig()
        self.assertEqual("mirrored",wsl.ini_get(text,"wsl2","networkingMode"));self.assertIsNone(wsl.ini_get(text,"wsl2","vmSwitch"));self.assertIsNone(wsl.ini_get(text,"wsl2","dhcp"))
        self.assertIsNone(wsl.ini_get(self.files[wsl.WSL_CONF],"boot","command"))
        self.assertEqual({"networkingMode":None,"vmSwitch":None,"dhcp":None,"macAddress":None},wsl.get_state()["wslconfig_prior"],"the pre-LOYA values are kept")
    def test_unavailable_modes_and_unknown_switches_are_refused(self):
        self.enable()
        with mock.patch.object(wsl,"windows_info",return_value=WIN_HOME):
            with self.assertRaises(ValueError) as ctx:wsl.apply_network({"mode":"bridged","switch":"LAN"},True)
        self.assertIn("Home",str(ctx.exception))
        with self.assertRaises(ValueError):wsl.apply_network({"mode":"bridged","switch":"NotThere"},True)
        self.assertFalse(os.path.exists(os.path.join(self.home,".wslconfig")))
    def test_rollback_when_kali_does_not_start(self):
        original="[wsl2]\nnetworkingMode=nat\nmemory=4GB\n"
        with open(os.path.join(self.home,".wslconfig"),"w",encoding="utf-8") as f:f.write(original)
        self.enable()
        self.kali_starts=False
        res=wsl.apply_network({"mode":"mirrored"},True)
        job=wsl.job_status(res["job_id"])
        self.assertEqual("failed",job["state"]);self.assertIn("restored",job["error"])
        self.assertEqual(original,self.wslconfig())
        self.assertIn(("wsl_network_mode",False),self.audit)
        self.assertFalse(wsl.get_state()["configured"])
    def test_remove_restores_prior_values_and_keeps_the_distro(self):
        with open(os.path.join(self.home,".wslconfig"),"w",encoding="utf-8") as f:f.write("[wsl2]\nnetworkingMode=nat\nmemory=4GB\n")
        self.enable();wsl.wizard_start()
        wsl.apply_network({"mode":"mirrored"},True)
        with self.assertRaises(ValueError):wsl.remove_setup(False,"",False)
        with self.assertRaises(ValueError):wsl.remove_setup(True,"kali",True)
        wsl.remove_setup(False,"",True)
        text=self.wslconfig()
        self.assertEqual("nat",wsl.ini_get(text,"wsl2","networkingMode"));self.assertIn("memory=4GB",text)
        self.assertNotIn(["wsl.exe","--unregister","kali-linux"],[c[0] for c in self.calls])
        self.assertFalse(wsl.get_state()["configured"])
        self.assertIn(("wsl_kali_remove_setup",True),self.audit)
        wsl.remove_setup(True,"kali-linux",True)
        self.assertIn(["wsl.exe","--unregister","kali-linux"],[c[0] for c in self.calls])
    def test_describe_shows_what_will_run(self):
        self.enable()
        plan=wsl.describe("network",ValidationTests.GOOD)
        joined="\n".join(plan["commands"])
        self.assertIn("networkingMode=bridged",joined);self.assertIn("vmSwitch=LAN",joined);self.assertIn("wsl.exe --shutdown",joined)
        self.assertEqual([wsl.NOTE_A,wsl.NOTE_B],plan["notes"])
        self.assertEqual(["wsl.exe --install --no-distribution"],wsl.describe("feature")["commands"])
        self.assertTrue(wsl.describe("feature")["elevated"])
        self.assertIn("--web-download",wsl.describe("install",{"web_download":True})["commands"][0])
        with self.assertRaises(ValueError):wsl.describe("adduser",{"username":"a b"})
        self.assertEqual([],[c for c in self.calls if "--shutdown" in c[0]],"describe never runs anything")
    def test_default_user(self):
        self.enable()
        wsl.set_default_user("pentester")
        self.assertEqual("pentester",wsl.ini_get(self.files[wsl.WSL_CONF],"user","default"))
        self.assertIn(["wsl.exe","--terminate","kali-linux"],[c[0] for c in self.calls])
class BridgeLockTests(unittest.TestCase):
    def test_wsl_bridge_is_guarded(self):
        from Cores.Bridge import api
        from Cores.Bridge.wsl_api import WslAPI
        self.assertNotIn("wsl",api._LOCK_OPEN)
        class Holder:
            def __init__(self):
                self.wsl=WslAPI();self.terminal=api.TerminalAPI()
                api._guard_while_locked(self)
        h=Holder()
        common_db.set_locked(True)
        try:
            for call in (lambda:h.wsl.status(),lambda:h.wsl.apply_network({"mode":"nat"},True),lambda:h.wsl.set_enabled(True,True),lambda:h.terminal.create_task("pwsh_install"),lambda:h.terminal.set_default_shell("auto")):
                with self.assertRaises(ValueError):call()
        finally:common_db.set_locked(False)
    def test_terminal_output_is_not_readable_while_locked(self):
        # H-03 / SA-13: terminal.read (and poll) refuse while locked; only harmless status calls stay open.
        from Cores.Bridge import api
        self.assertNotIn("read",api._LOCK_OPEN["terminal"])
        self.assertNotIn("poll",api._LOCK_OPEN["terminal"])
        class Holder:
            def __init__(self):
                self.terminal=api.TerminalAPI()
                api._guard_while_locked(self)
        h=Holder()
        with mock.patch.object(api._terminal_svc,"read_output",return_value="secret output"),mock.patch.object(api._terminal_svc,"poll_sessions",return_value={"out":{"s":"secret"}}):
            self.assertEqual("secret output",h.terminal.read("s"))
            common_db.set_locked(True)
            try:
                with self.assertRaises(ValueError):h.terminal.read("s")
                with self.assertRaises(ValueError):h.terminal.poll(["s"])
            finally:common_db.set_locked(False)
            self.assertEqual("secret output",h.terminal.read("s"))
if __name__=="__main__":unittest.main()
