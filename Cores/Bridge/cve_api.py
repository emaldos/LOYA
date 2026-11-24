"""Bridge for CVE Intel (the CVE Intel page, Settings > CVE Intel, the note editor's CVE callout and Reporting's "From CVE").
Every method is refused while the app is locked (api._guard_while_locked). The NVD API key only goes in, never out."""
from Cores.Services import cve_service as _cve
from Cores.Services import cve_index_updater as _index_upd
class CveAPI:
    def status(self):
        return _cve.status()
    def get_settings(self):
        return _cve.get_settings()
    def set_settings(self,patch,consent=False):
        return _cve.set_settings(patch or {},consent is True)
    def privacy_info(self):
        return _cve.privacy_info()
    def request_log(self):
        return _cve.request_log()
    def set_api_key(self,key):
        return _cve.set_api_key(key)
    def clear_api_key(self):
        return _cve.clear_api_key()
    def test_api_key(self):
        return _cve.test_api_key()
    def clear_cache(self):
        return _cve.clear_cache()
    def extract_ids(self,text):
        return _cve.extract_ids(text)
    def search(self,query="",limit=20,filters=None):
        return _cve.search(query,limit,filters)
    def index_get(self,cve_id):
        return _cve.index_get(cve_id)
    def index_status(self):
        return _index_upd.status()
    def index_update(self):
        return _index_upd.start()
    def index_cancel(self):
        return _index_upd.cancel()
    def lookup(self,cve_id,refresh=False):
        return _cve.lookup(cve_id,refresh is True)
    def lookup_many(self,ids,refresh=False):
        return _cve.lookup_many(ids,refresh is True)
    def to_finding(self,cve_id,opts=None):
        return _cve.to_finding(cve_id,opts)
    def feed(self,filters=None):
        return _cve.feed(filters)
    def refresh_feed(self):
        return _cve.refresh_feed()
    def mark_read(self,ids,read=True):
        return _cve.mark_read(ids,bool(read))
    def mark_all_read(self):
        return _cve.mark_all_read()
    def tick(self):
        return _cve.tick()
