import unittest
from unittest import mock
from _isolate import IsolatedData
from Cores.Services import ai_service as ai
from Cores.Services import ext_agents_service as ext_agents
def agent_status(ready=False,installed=False,reason=""):
    def status(provider):
        return {"label":ext_agents.PROVIDER_LABELS[provider],"ready":ready,"installed":installed,"reason":reason}
    return status
class ProviderCatalogTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        patcher=mock.patch.object(ai,"_local_installed",lambda kind:False)
        patcher.start()
        self.addCleanup(patcher.stop)
    def tearDown(self):
        self.isolated.stop()
    def catalog(self,status=None):
        with mock.patch.object(ext_agents,"provider_status",status or agent_status()):
            return {entry["kind"]:entry for entry in ai.provider_catalog()}
    def test_every_chat_option_is_listed_even_when_nothing_is_set_up(self):
        entries=self.catalog()
        self.assertEqual(["api","ollama","lmstudio","ext:claude","ext:codex"],list(entries))
        self.assertTrue(all(entry["state"]=="setup" for entry in entries.values()))
        self.assertNotIn("mcp",entries)
    def test_api_states_follow_enabled_and_key(self):
        ai.set_provider("api",{"enabled":True,"provider_kind":"anthropic","api_key":"k-0123456789"})
        self.assertEqual(("ready","Anthropic API"),(self.catalog()["api"]["state"],self.catalog()["api"]["label"]))
        ai.set_provider("api",{"enabled":False})
        self.assertEqual(("available","off"),(self.catalog()["api"]["state"],self.catalog()["api"]["reason"]))
        ai.set_provider("api",{"enabled":True,"api_key":"","provider_kind":"openai"})
        entry=self.catalog()["api"]
        self.assertEqual(("available","no API key","OpenAI-compatible API"),(entry["state"],entry["reason"],entry["label"]))
    def test_local_providers_are_available_when_installed_and_ready_when_enabled(self):
        with mock.patch.object(ai,"_local_installed",lambda kind:kind=="ollama"):
            entries=self.catalog()
        self.assertEqual(("available","off"),(entries["ollama"]["state"],entries["ollama"]["reason"]))
        self.assertEqual(("setup","not installed"),(entries["lmstudio"]["state"],entries["lmstudio"]["reason"]))
        ai.set_provider("lmstudio",{"enabled":True})
        self.assertEqual("ready",self.catalog()["lmstudio"]["state"])
    def test_agent_states_come_from_their_status(self):
        self.assertEqual("ready",self.catalog(agent_status(ready=True,installed=True))["ext:codex"]["state"])
        entry=self.catalog(agent_status(installed=True,reason="no_key"))["ext:claude"]
        self.assertEqual(("available","no API key","agent","Claude Agent"),(entry["state"],entry["reason"],entry["category"],entry["label"]))
    def test_a_broken_agent_status_does_not_hide_the_other_providers(self):
        def broken(provider):raise RuntimeError("no runtime")
        entries=self.catalog(broken)
        self.assertEqual(["api","ollama","lmstudio"],list(entries))
if __name__=="__main__":
    unittest.main()
