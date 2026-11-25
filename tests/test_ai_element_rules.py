import os,re,unittest
from _isolate import IsolatedData,ROOT
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import ai_element_rules as rules
from Cores.Services import ext_agents_service as ext
from Cores.Services import templates_service as templates
from Cores.Services import targets_service as targets
from Cores.Bridge import mcp_server
def call(tool_name,**arguments):
    ok,result=chat._call_tool(tool_name,arguments)
    if not ok:raise AssertionError(f"{tool_name} failed: {result}")
    return result
class MeaningMatchTests(unittest.TestCase):
    def test_existing_element_is_reused_by_meaning(self):
        keys=["RHOST","PORT","wordlists","Target URL","LHOST"]
        self.assertEqual("{RHOST}",rules.match_element("IP",keys)["element"])
        self.assertEqual("{RHOST}",rules.match_element("IPv4",keys)["element"])
        self.assertEqual("{RHOST}",rules.match_element("Target_IPv4_Address",keys)["element"])
        self.assertEqual("{PORT}",rules.match_element("{Ports}",keys)["element"])
        self.assertEqual("{wordlists}",rules.match_element("Wordlist",keys)["element"])
        self.assertEqual("{Target URL}",rules.match_element("url",keys)["element"])
        self.assertTrue(rules.match_element("IP",keys)["exists"])
    def test_exact_name_wins_over_meaning(self):
        self.assertEqual("{IP}",rules.match_element("ip",["RHOST","IP"])["element"])
    def test_missing_element_gets_a_clean_new_name(self):
        for name,expected in (("IP","{IPv4}"),("ports","{Ports}"),("wordlist","{Wordlist}"),("lport","{LPORT}"),("iface","{Interface}"),("Some odd thing","{Some_odd_thing}")):
            match=rules.match_element(name,["Domain"])
            self.assertEqual(expected,match["element"],name)
            self.assertFalse(match["exists"],name)
    def test_listener_and_target_values_are_not_mixed(self):
        self.assertEqual("{LHOST}",rules.match_element("attacker ip",["RHOST","LHOST"])["element"])
        self.assertEqual("{RHOST}",rules.match_element("IP",["LHOST","RHOST"])["element"])
    def test_hardcoded_values_are_found_with_the_element_to_use(self):
        found=rules.hardcoded_values("ffuf -u http://10.10.11.5/FUZZ -w /usr/share/wordlists/dirb/common.txt -o out.json; nmap -p 22,80,443 10.10.11.5",["RHOST"])
        by_value={item["value"]:item["use"] for item in found}
        self.assertEqual("{URL}",by_value["http://10.10.11.5/FUZZ"])
        self.assertEqual("{RHOST}",by_value["10.10.11.5"])
        self.assertEqual("{Wordlist}",by_value["/usr/share/wordlists/dirb/common.txt"])
        self.assertEqual("{Ports}",by_value["22,80,443"])
        self.assertEqual("{Output}",by_value["out.json"])
    def test_commands_written_with_elements_are_clean(self):
        for command in ("ffuf -u {URL}/FUZZ -w {Wordlist} -o {Output}","nmap -p {Ports} -oA {Output} {IPv4}","curl http://{IPv4}:{Ports}/","ssh -o StrictHostKeyChecking=no {Username}@{IPv4}","nc -lvnp {LPORT} -s 0.0.0.0"):
            self.assertEqual([],rules.hardcoded_values(command,[]),command)
class RuleTextTests(unittest.TestCase):
    def test_rule_text_has_no_long_dashes(self):
        for text in (rules.element_rule_text(),rules.element_rule_markdown(),rules.ELEMENT_RULE_SHORT,rules.ELEMENT_RULE_TEMPLATE):
            self.assertNotIn("—",text);self.assertNotIn("–",text)
    def test_in_app_prompt_uses_the_shared_rule_and_lists_elements(self):
        self.assertIn(rules.element_rule_text(),chat.BASE_SYSTEM_PROMPT)
        original=rules.current_element_names
        rules.current_element_names=lambda:["RHOST","Wordlist"]
        try:
            prompt=chat.base_system_prompt()
            self.assertIn("{RHOST} (IP address)",prompt)
            self.assertIn("{Wordlist} (wordlist)",prompt)
            self.assertIn(rules.element_rule_text(),ext.system_prompt("claude"))
            self.assertIn("{RHOST} (IP address)",ext.system_prompt("codex"))
        finally:rules.current_element_names=original
    def test_bundled_skills_carry_the_rule(self):
        sources={source["name"]:source["data"].decode("utf-8") for source in ext.bundled_skill_sources()}
        for name in ("loya-basics","loya-notes"):
            self.assertIn(rules.element_rule_markdown(),sources[name],name)
        for name,text in sources.items():
            self.assertNotIn(rules.SKILL_MARKER,text,name)
            self.assertNotIn("—",text,name);self.assertNotIn("–",text,name)
            if "{IPv4}" in text or "command block" in text:self.assertIn("parameter_list",text,name)
    def test_mcp_server_instructions_and_write_tools_state_the_rule(self):
        server=mcp_server.build_server()
        self.assertIn(rules.element_rule_text(),server.instructions)
        tools={tool.name:tool.description for tool in chat._list_tools()}
        for name in ("notes_create","notes_update","notes_append","notes_command_block_html","commands_create","commands_update"):
            self.assertIn(rules.ELEMENT_RULE_SHORT,tools[name],name)
        self.assertIn("before writing any command",tools["parameter_list"])
        self.assertIn("parameter_match",tools)
        self.assertEqual("parameter_read",ai.permission_key("parameter_match"))
class ElementToolTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
        ai.revoke_session_grant()
    def tearDown(self):
        ai.revoke_session_grant()
        self.isolated.stop()
    def test_parameter_list_and_match_work_by_meaning(self):
        call("parameter_add",key="RHOST")
        listed={row["key"]:row for row in call("parameter_list")}
        self.assertEqual("IP address",listed["RHOST"]["meaning"])
        matched={row["name"]:row for row in call("parameter_match",names=["IP","Ports"])}
        self.assertEqual({"element":"{RHOST}","exists":True},{k:matched["IP"][k] for k in ("element","exists")})
        self.assertEqual({"element":"{Ports}","exists":False},{k:matched["Ports"][k] for k in ("element","exists")})
        self.assertEqual(["{RHOST}","{Wordlist}"],[row["element"] for row in call("parameter_match",names="ip, wordlist")])
    def test_note_save_registers_new_elements_and_reports_literals(self):
        call("parameter_add",key="RHOST")
        block=call("notes_command_block_html",command="ffuf -u http://{RHOST}/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200 -p {Ports}",cmd_note_title="ffuf dirs",category="Web",sub_category="Fuzzing")
        note=call("notes_create",name="ffuf",content="<p>Directory fuzzing</p>"+block,group="Web")
        self.assertEqual(["RHOST","Ports"],note["elements"]["used"])
        self.assertEqual(["Ports"],note["elements"]["new"])
        self.assertEqual([{"value":"/usr/share/wordlists/dirb/common.txt","use":"{Wordlist}"}],note["elements"]["hardcoded"])
        self.assertIn("Ports",targets.Store().ordered_keys())
    def test_note_append_registers_new_elements(self):
        note=call("notes_create",name="smb",content="<p>start</p>",group="Recon")
        block=call("notes_command_block_html",command="smbclient -L //{IPv4} -U {Username}",cmd_note_title="list shares",category="SMB",sub_category="Enum")
        appended=call("notes_append",note_id=note["id"],content=block)
        self.assertEqual(["IPv4","Username"],appended["elements"]["new"])
        self.assertNotIn("hardcoded",appended["elements"])
        values=targets._read_json(targets._paths()[0],{})
        self.assertIn("IPv4",values);self.assertIn("Username",values)
    def test_command_save_reports_elements(self):
        call("parameter_add",key="IP")
        saved=call("commands_create",note_name="nmap full",category="Recon",sub_category="Ports",command="nmap -p 22,80 10.0.0.7 -oN {Output}")
        self.assertEqual(["Output"],saved["elements"]["new"])
        self.assertEqual({"22,80":"{Ports}","10.0.0.7":"{IP}"},{item["value"]:item["use"] for item in saved["elements"]["hardcoded"]})
    def test_exported_ai_templates_carry_the_rule(self):
        call("parameter_add",key="RHOST")
        for kind in ("notes","commands"):
            text=templates.ai_template_text(kind)
            self.assertIn(rules.ELEMENT_RULE_TEMPLATE,text,kind)
            self.assertIn("{RHOST} (IP address)",text,kind)
if __name__=="__main__":unittest.main()
