"""Bridge for External Agents (Settings > AI > Agents and the AI panel). API keys only go in, never out.
The connection_* methods are the Connections cards: the operator's own Claude Code / Codex CLI (ext_connections_service)."""
from Cores.Services import ext_agents_service as _ext
from Cores.Services import ai_sessions_service as _ai_sessions_svc
from Cores.Services import ai_index_service as _ai_index_svc
from Cores.Services import mcp_local_service as _mcp_local_svc
from Cores.Services import ext_connections_service as _conn
from Cores.Services import ext_cli_launch as _cli_launch
def _provider(kind):
    kind=str(kind or "")
    if kind.startswith("ext:"):kind=kind[4:]
    if kind not in _ext.PROVIDERS:raise ValueError(f"Unknown external agent: {kind}")
    return kind
class ExternalAgentsAPI:
    def overview(self):
        return {"providers":{p:{"status":_ext.provider_status(p),"config":_ext.public_config(p)} for p in _ext.PROVIDERS},"redact":_ext.redaction_enabled(),"key_storage":_ext.key_storage_options(),"install":_ext.install_status(),
                "claude_models":_ext.CLAUDE_MODELS,"efforts":_ext.EFFORTS,"claude_tools":_ext.CLAUDE_OPTIONAL_TOOLS,"codex_sandboxes":list(_ext.CODEX_SANDBOXES),"sdk":{"package":_ext.CLAUDE_SDK_PACKAGE,"version":_ext.CLAUDE_SDK_VERSION}}
    def status(self,kind):
        return _ext.provider_status(_provider(kind))
    def enabled(self):
        return _ext.enabled_agents()
    def consent_info(self,kind):
        return _ext.consent_info(_provider(kind))
    def grant_consent(self,kind,accepted):
        return _ext.grant_consent(_provider(kind),accepted is True)
    def set_enabled(self,kind,enabled):
        return _ext.set_enabled(_provider(kind),bool(enabled))
    def set_config(self,kind,cfg):
        return _ext.set_config(_provider(kind),cfg or {})
    def set_api_key(self,kind,key):
        return _ext.set_api_key(_provider(kind),key)
    def clear_api_key(self,kind):
        return _ext.clear_api_key(_provider(kind))
    def set_redaction(self,enabled):
        return _ext.set_redaction(bool(enabled))
    def install(self,kind):
        return _ext.install_runtime(_provider(kind))
    def install_status(self):
        return _ext.install_status()
    def test_connection(self,kind):
        return _ext.test_connection(_provider(kind))
    def skills(self,kind):
        return _ext.list_skills(_provider(kind))
    def refresh_skills(self,kind):
        return _ext.discover_commands(_provider(kind))
    def permission_summary(self,kind):
        return _ext.permission_summary(_provider(kind))
    def mcp_token(self,reveal=False):
        return _mcp_local_svc.token_info(bool(reveal))
    def run_start(self,session_id,kind,text,attachments=None,display=None,skill=None):
        provider=_provider(kind)
        if not session_id or _ai_sessions_svc.load_session(session_id) is None:
            session_id=_ai_sessions_svc.create_session("ext:"+provider)["id"]
        session=_ai_sessions_svc.load_session(session_id) or {}
        history=session.get("messages") or []
        refs=[a for a in (attachments or []) if isinstance(a,dict)]
        meta=None
        prompt=text
        if isinstance(skill,dict) and skill.get("name"):
            prompt=_ext.skill_prompt(provider,str(skill.get("name")),str(skill.get("args") or ""))
            meta={"display":str(display or text or "").strip(),"attachments":[]}
        if refs or display:
            meta={"display":str(display if display else text or "").strip(),"attachments":[{"kind":str(a.get("kind","")),"label":str(a.get("label",""))} for a in refs]}
            if refs:prompt=_ai_index_svc.with_context(prompt,refs)
        run_id=_ext.start_run(provider,session_id,prompt,history,meta)
        return {"run_id":run_id,"stream_id":run_id,"session_id":session_id}
    def run_poll(self,session_id,kind,run_id):
        r=_ext.poll_run(run_id)
        if r.get("done") and r.get("history") is not None:
            _ai_sessions_svc.save_session_messages(session_id,r["history"],"ext:"+_provider(kind))
        return r
    def stop(self,run_id):
        return _ext.stop_run(run_id)
    def stop_all(self):
        return _ext.suspend_all("stopped by the operator")
    def active(self):
        return _ext.active_runs()
    # ---- Connections: the operator's own official CLI (never its credentials)
    def connections(self):
        return _conn.overview()
    def connection_status(self,tool):
        return _conn.status(tool)
    def connection_connect(self,tool):
        return _conn.connect(tool)
    def connection_disconnect(self,tool):
        return _conn.disconnect(tool)
    def connection_test(self,tool):
        return _conn.test_connection(tool)
    def connection_sign_in_command(self,tool,shell_id=""):
        return _conn.sign_in_command(tool,shell_id)
    def connection_sign_in_os(self,tool):
        return _conn.sign_in_os_terminal(tool)
    def connection_detect(self,tool):
        return _conn.detect(tool)
    def connection_install_methods(self,tool):
        return _conn.install_methods(tool)
    def connection_install_plan(self,tool,method_id,shell_id=""):
        return _conn.install_plan(tool,method_id,shell_id)
    def connection_install_command(self,tool,method_id,shell_id,token):
        return _conn.install_command(tool,method_id,shell_id,token)
    def connection_install_os(self,tool,method_id,token):
        return _conn.install_os_terminal(tool,method_id,token)
    def connection_connect_preview(self,tool):
        return _conn.connect_preview(tool)
    # Background steps: start returns at once; the UI polls and can cancel (a slow or hung CLI never holds a bridge call).
    def connection_job_start(self,kind,tool=None):
        return _conn.job_start(kind,tool)
    def connection_job_poll(self,job_id):
        return _conn.job_poll(job_id)
    def connection_job_cancel(self,job_id):
        return _conn.job_cancel(job_id)
    # ---- AI panel "Claude Code (your CLI)" / "Codex CLI (your CLI)": open the operator's own CLI interactively in a terminal
    # (ext_cli_launch). Nothing here sends chat-panel text to the CLI.
    def cli_launch_command(self,tool,shell_id=""):
        return _cli_launch.launch_command(tool,shell_id)
    def cli_launch_os(self,tool):
        return _cli_launch.launch_os_terminal(tool)
