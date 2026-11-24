"""Bridge module api.evidence - evidence store, session recording, auto-generate (see the reporting contract)."""
from Cores.Services import evidence_service as _evidence
class EvidenceAPI:
    def __init__(self):self._window=None
    def bind(self,window):self._window=window
    def list(self,filter=None):
        return _evidence.list_evidence(filter)
    def get(self,evidence_id):
        return _evidence.get(evidence_id)
    def save_job(self,info):
        return _evidence.save_job(info)
    def save_text(self,info):
        return _evidence.save_text(info)
    def save_image(self,name,data_b64,title=""):
        return _evidence.save_image(name,data_b64,title)
    def image_data(self,evidence_id):
        return _evidence.asset_data_url(evidence_id)
    def update(self,evidence_id,patch):
        return _evidence.update(evidence_id,patch)
    def delete(self,evidence_id):
        return _evidence.delete(evidence_id)
    def delete_many(self,ids):
        return _evidence.delete_many(ids)
    def recording_start(self,info):
        return _evidence.recording_start(info)
    def recording_append(self,evidence_id,events):
        return _evidence.recording_append(evidence_id,events)
    def recording_stop(self,evidence_id):
        return _evidence.recording_stop(evidence_id)
    def recordings_active(self):
        return _evidence.recordings_active()
    def redaction_enabled(self):
        return _evidence.redact_enabled()
    def autogen_preview(self,params):
        from Cores.Services import report_autogen as _autogen
        return _autogen.preview(params)
    def autogen_create(self,params):
        from Cores.Services import report_autogen as _autogen
        return _autogen.create(params)
