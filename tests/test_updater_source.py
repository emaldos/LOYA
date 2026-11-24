import unittest
from _isolate import ROOT
from Cores.Update import update_helpers as h
from Cores.Update import update_service as us
from Cores.Update import apply_update as ap
class UpdaterSourceTests(unittest.TestCase):
    # NG updates only from github.com/emaldos/LOYA (it moved there from emaldos/LOYA-Note-NG); the match must be exact so a
    # look-alike repository, the old name or the original LOYA-Note can't pass.
    def test_official_source_is_the_loya_repository(self):
        self.assertEqual("LOYA NG",h.APP_NAME)
        self.assertEqual("https://github.com/emaldos/LOYA",h.OFFICIAL_SOURCE_REPO)
        self.assertEqual(("emaldos","LOYA"),(h.OFFICIAL_SOURCE_OWNER,h.OFFICIAL_SOURCE_NAME))
        self.assertEqual("https://api.github.com/repos/emaldos/LOYA/releases/latest",h.GITHUB_RELEASES_API_URL)
        self.assertEqual(h.OFFICIAL_SOURCE_REPO,h.canonical_repo_url(h.OFFICIAL_SOURCE_REPO+".git"))
    def test_release_asset_names_use_the_new_prefix(self):
        self.assertEqual("LOYA-NG-",h.PACKAGE_ASSET_PREFIX)
        self.assertEqual("LOYA-NG-v1.0.1.zip",h.expected_package_asset_name("1.0.1"))
    def test_the_apply_helper_names_the_same_repository(self):
        # apply_update.py runs standalone (no app imports), so it carries its own copy of the repository URL.
        self.assertEqual(h.OFFICIAL_SOURCE_REPO,ap._OFFICIAL_REPO)
        self.assertTrue(ap._is_official_repo("https://github.com/emaldos/LOYA/"))
        self.assertFalse(ap._is_official_repo("https://github.com/emaldos/LOYA-Note-NG"))
        self.assertTrue(ap._is_official_package_url("https://github.com/emaldos/LOYA/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip"))
        self.assertTrue(ap._is_official_package_url("https://api.github.com/repos/emaldos/LOYA/releases/assets/7"))
        for bad in ("https://github.com/emaldos/LOYA-Note-NG/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip","https://github.com/emaldos/LOYA-x/releases/download/v1.0.1/x.zip","https://api.github.com/repos/emaldos/LOYA-Note-NG/releases/assets/7"):
            self.assertFalse(ap._is_official_package_url(bad),bad)
    def test_only_the_exact_repository_is_official(self):
        for url in ("https://github.com/emaldos/LOYA","https://github.com/emaldos/LOYA.git","https://github.com/EMALDOS/loya","https://github.com/emaldos/LOYA/"):
            self.assertTrue(h.is_official_repo(repo_url=url),url)
        for url in ("https://github.com/emaldos/LOYA-Note","https://github.com/emaldos/LOYA-Note-NG","https://github.com/emaldos/LOYA-evil","https://github.com/attacker/LOYA","https://gitlab.com/emaldos/LOYA"):
            self.assertFalse(h.is_official_repo(repo_url=url),url)
    def test_packages_must_come_from_the_official_repository(self):
        ok="https://github.com/emaldos/LOYA/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip"
        self.assertTrue(h.is_official_package_url(ok,"emaldos","LOYA"))
        self.assertTrue(h.is_official_package_url(ok))
        for bad in ("https://github.com/emaldos/LOYA-evil/releases/download/v1.0.1/x.zip","https://github.com/emaldos/LOYA-Note/releases/download/v1.0.1/x.zip","https://github.com/emaldos/LOYA-Note-NG/releases/download/v1.0.1/x.zip","https://evil.example/emaldos/LOYA/x.zip"):
            self.assertFalse(h.is_official_package_url(bad,"emaldos","LOYA"),bad)
        self.assertFalse(h.is_official_package_url(ok,"emaldos","LOYA-Note-NG"))
        self.assertTrue(h.is_official_release_page("https://github.com/emaldos/LOYA/releases/tag/v1.0.1"))
        self.assertFalse(h.is_official_release_page("https://github.com/emaldos/LOYA-Note-NG/releases/tag/v1.0.1"))
    def test_a_manifest_from_another_repository_is_rejected(self):
        for repo in ("https://github.com/emaldos/LOYA-Note","https://github.com/emaldos/LOYA-Note-NG"):
            with self.assertRaises(ValueError):
                h.validate_remote_manifest({"source_repo":repo,"version":"1.0.1","release_id":"1"})
        m=h.validate_remote_manifest({"source_repo":"https://github.com/emaldos/LOYA","version":"1.0.1","release_id":"1"})
        self.assertEqual(h.OFFICIAL_SOURCE_REPO,m["source_repo"])
    def test_a_stored_state_naming_the_old_repository_is_migrated(self):
        # An install made before the move stored the old repository and API URL in Cores/Update/state.json: it must not keep using it.
        old={"current_version":"1.0.0","source_repo":"https://github.com/emaldos/LOYA-Note-NG","source_owner":"emaldos","source_name":"LOYA-Note-NG",
             "remote_manifest_url":"https://api.github.com/repos/emaldos/LOYA-Note-NG/releases/latest","last_good_version":"1.0.0"}
        st,changed=us.normalize_update_state(old,"1.0.0")
        self.assertTrue(changed)
        self.assertEqual((h.OFFICIAL_SOURCE_REPO,"emaldos","LOYA",h.GITHUB_RELEASES_API_URL),(st["source_repo"],st["source_owner"],st["source_name"],st["remote_manifest_url"]))
    def test_the_windows_app_id_is_unchanged_by_the_move(self):
        # Internal id kept for compatibility: taskbar pins and toast settings on Windows are tied to it.
        self.assertEqual("emaldos.LOYA.Note.NG.1.0.0",h.build_windows_app_id("1.0.0"))
if __name__=="__main__":unittest.main()
