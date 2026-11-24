import unittest
from _isolate import IsolatedData
from Cores.Services import ai_index_service as idx
from Cores.Services import ai_chat_service as chat
from Cores.Services import ai_service as ai
ITEMS=[
    {"kind":"command","id":1,"label":"Nmap","detail":"nmap -sV {IPv4}","keys":["nmap -sV {IPv4}","Network","Scan","recon"]},
    {"kind":"command","id":2,"label":"Nmap UDP top ports","detail":"nmap -sU --top-ports 100 {IPv4}","keys":["Network"]},
    {"kind":"command","id":3,"label":"Gobuster dir","detail":"gobuster dir -u {URL}","keys":["Web","recon"]},
    {"kind":"note","id":10,"label":"NMAP","detail":"Network","keys":["Network","nmap"]},
    {"kind":"note","id":11,"label":"Web enumeration notes","detail":"Web","keys":["Web"]},
    {"kind":"target","id":"t1","label":"Acme DC","detail":"live","keys":["10.0.0.5"]},
    {"kind":"tag","id":"recon","label":"recon","detail":"tag"},
]
class RankTests(unittest.TestCase):
    def labels(self,query,**kw):
        return [(r["kind"],r["label"]) for r in idx.rank(ITEMS,query,**kw)]
    def test_exact_then_prefix_then_word_prefix(self):
        out=self.labels("nmap")
        self.assertEqual(out[:3],[("command","Nmap"),("note","NMAP"),("command","Nmap UDP top ports")])
    def test_word_prefix_beats_key_match(self):
        self.assertEqual(self.labels("enum")[0],("note","Web enumeration notes"))
    def test_matches_on_keys_such_as_target_values(self):
        self.assertEqual(self.labels("10.0.0"),[("target","Acme DC")])
    def test_multi_word_query_needs_every_word(self):
        self.assertEqual(self.labels("nmap udp"),[("command","Nmap UDP top ports")])
        self.assertEqual(self.labels("nmap zzz"),[])
    def test_fuzzy_subsequence_is_last_resort(self):
        self.assertEqual(self.labels("gbstr"),[("command","Gobuster dir")])
    def test_kind_filter_and_limit(self):
        self.assertEqual(self.labels("nmap",kinds=["note"]),[("note","NMAP")])
        self.assertEqual(len(idx.rank(ITEMS,"",limit=3)),3)
        self.assertEqual(len(idx.rank(ITEMS,"",limit=999)),len(ITEMS))
    def test_empty_query_lists_commands_first(self):
        self.assertEqual(idx.rank(ITEMS,"")[0]["kind"],"command")
    def test_results_do_not_leak_search_keys(self):
        self.assertNotIn("keys",idx.rank(ITEMS,"nmap")[0])
class ContextTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
        self._orig=idx._context_block
        idx._context_block=lambda kind,i:{("note","10"):"[Note: NMAP]\nscan notes",("target","t1"):"[Target: Acme DC]\nIP: 10.0.0.5"}.get((kind,str(i)))
    def tearDown(self):
        idx._context_block=self._orig
        self.isolated.stop()
    def test_context_is_appended_and_unknown_refs_are_skipped(self):
        out=idx.with_context("summarise it",[{"kind":"note","id":10},{"kind":"note","id":999},{"kind":"target","id":"t1"}])
        self.assertTrue(out.startswith("summarise it\n\n---\n"))
        self.assertIn("[Note: NMAP]",out);self.assertIn("IP: 10.0.0.5",out)
    def test_no_refs_leaves_text_alone(self):
        self.assertEqual(idx.with_context("hi",[]),"hi")
    def test_total_context_is_capped(self):
        idx._context_block=lambda kind,i:"x"*idx.CONTEXT_ITEM_CHARS
        out=idx.context_for([{"kind":"note","id":n} for n in range(10)])
        self.assertLessEqual(len(out),idx.CONTEXT_TOTAL_CHARS+200)
    def test_build_items_on_an_empty_database(self):
        self.assertEqual([i for i in idx.build_items() if i["kind"] in ("note","command")],[])
    def test_user_turn_keeps_what_the_user_typed(self):
        ai.set_provider("ollama",{"enabled":True,"host":"127.0.0.1","port":9,"model":"m"})
        captured={}
        orig=chat.chat_openai_compatible
        chat.chat_openai_compatible=lambda base,model,history,**kw:captured.setdefault("h",history)
        try:chat.send_message("ollama",[],"full prompt with context",user_meta={"display":"short","attachments":[{"kind":"note","label":"NMAP"}],"evil":1})
        finally:chat.chat_openai_compatible=orig
        turn=captured["h"][-1]
        self.assertEqual((turn["content"],turn["display"],turn["attachments"][0]["label"]),("full prompt with context","short","NMAP"))
        self.assertNotIn("evil",turn)
        self.assertEqual(chat._to_openai_messages([turn]),[{"role":"user","content":"full prompt with context"}])
if __name__=="__main__":unittest.main()
