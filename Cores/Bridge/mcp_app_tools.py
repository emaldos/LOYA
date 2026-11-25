"""App-wide MCP tools, resources and prompts: what a user can see and do in LOYA, for the in-app AI, MCP clients and the
External Agents (Claude Agent, OpenAI Codex). Registered from mcp_server.build_server() with register(server, check).

Rules for every tool here:
- it calls check(name, args) first: the lock, then AI Roles (ai_service.authorize). A tool not registered below with
  register_permission is denied.
- it goes through the same bridge/service code as the UI, so validation, note history, the Recycle Bin and the audit
  log apply. Nothing here opens the database itself.
- lists are paged (offset/limit, at most MAX_PAGE) and long text is capped.
- target values that look like secrets are masked unless the separate Targets > Secrets permission is granted
  (targets_secret_values). Results sent to an external agent are also passed through the secret redactor.
- after a successful change, the open page is told to reload (notify_ui).
"""
import json,re,threading
from Cores.Services import ai_service as _ai
from Cores.Services import ai_element_rules as _element_rules
MAX_PAGE=200
MAX_TEXT=40_000
# ---------------------------------------------------------------- permissions (new keys; existing keys are reused where the tool fits)
_NEW_PERMISSIONS=(
    # key, entity, action, tools, kwargs
    ("app_read","App","Read",["app_context","app_search","dashboard_stats"],{}),
    ("audit_read","Audit Log","Read",["audit_log_read"],{"sensitive":True}),
    ("targets_secrets","Targets","Secrets",["targets_secret_values"],{"sensitive":True}),
    ("quickrun_edit","Quick Run","Edit",["quickrun_favorite_set"],{"default":"ask"}),
)
_EXTRA_TOOLS={  # tools added to permission keys that already exist
    "notes_read":["notes_search","notes_groups","notes_versions","notes_version_diff"],
    "notes_add":["notes_group_create"],
    "notes_edit":["notes_move","notes_pin","notes_group_rename","notes_restore_version","notes_attachment_add"],
    "commands_read":["commands_history","command_runs"],
    "targets_read":["targets_live_get","target_profiles_list"],
    "targets_add":["target_profile_create"],
    "targets_edit":["targets_set_live","targets_set_engagement_status","target_profile_switch"],
    "reports_read":["reports_stats","reports_deadlines","report_versions_list","report_schedule_get","report_template_get","report_targets_available","report_targets_list"],
    "reports_add":["report_evidence_add_text","report_evidence_add_image","findings_library_add","findings_add_from_library","findings_add_from_cve","report_target_link"],
    "reports_edit":["report_version_create","report_version_restore","report_schedule_set","report_target_unlink","report_target_update","report_targets_reorder","finding_targets_set"],
    "cve_read":["cve_search","cve_feed"],
    "quickrun_read":["quickrun_favorites"],
    "terminal_read":["terminal_jobs_list","terminal_job_get"],
}
def register_permissions():
    for key,entity,action,tools,kw in _NEW_PERMISSIONS:
        if key not in _ai.PERMISSION_TOOL_MAP:_ai.register_permission(key,entity,action,tools,**kw)
    for key,tools in _EXTRA_TOOLS.items():
        if key not in _ai.PERMISSION_TOOL_MAP:continue
        for t in tools:
            if _ai.permission_key(t) is None:_ai.PERMISSION_TOOL_MAP[key].append(t)
def all_tool_names():
    names=[t for _k,_e,_a,tools,_kw in _NEW_PERMISSIONS for t in tools]
    for tools in _EXTRA_TOOLS.values():names+=tools
    return names
register_permissions()
# ---------------------------------------------------------------- helpers
_SECRET_KEY_RX=re.compile(r"pass|pwd|secret|token|hash|ntlm|cookie|cred|api[ _-]?key|private[ _-]?key|ssh[ _-]?key|session[ _-]?(id|key)|bearer",re.I)
MASK="[hidden - needs AI Roles > Targets > Secrets]"
def is_secret_key(key):return bool(_SECRET_KEY_RX.search(str(key or "")))
def mask_values(values):
    if not isinstance(values,dict):return values
    return {k:(MASK if is_secret_key(k) and str(v or "").strip() else v) for k,v in values.items()}
def mask_targets(targets):
    out=[]
    for t in targets or []:
        if isinstance(t,dict):
            t=dict(t)
            for f in ("values","map"):
                if isinstance(t.get(f),dict):t[f]=mask_values(t[f])
        out.append(t)
    return out
class _MaskedCtx:
    def __init__(self,ctx):self.name=getattr(ctx,"name","");self.map=mask_values(getattr(ctx,"map",{}) or {})
def masked_resolver():
    """Like the live-target placeholder resolver, but {Password}-style placeholders resolve to the mask. Use it for any
    text an AI reads; the real resolver is only for the command that is actually queued for the operator's approval."""
    from Cores.Services import search_service as _search_svc
    return _search_svc.CommandReplacer(_MaskedCtx(_search_svc.LiveTargetContext()))
def mask_report_links(links):
    """Report scope links: a value the operator explicitly copied in for a secret key (allowed_secret_keys) is never shown
    to an AI. target_allow_secret is not exposed at all - only the operator can put a secret into a report."""
    out=[]
    for l in links or []:
        if isinstance(l,dict):
            l=dict(l);snap=dict(l.get("snapshot") or {})
            vals=dict(snap.get("values") or {})
            for k in l.get("allowed_secret_keys") or []:
                if k in vals:vals[k]=MASK
            snap["values"]=mask_values(vals);l["snapshot"]=snap
        out.append(l)
    return out
def mask_report(rep):
    if isinstance(rep,dict) and isinstance(rep.get("targets"),list):rep=dict(rep,targets=mask_report_links(rep["targets"]))
    return rep
def _cap(v,n=MAX_TEXT):
    if isinstance(v,str) and len(v)>n:return v[:n]+f"\n… [{len(v)-n} more characters cut]"
    if isinstance(v,list):return [_cap(x,n) for x in v]
    if isinstance(v,dict):return {k:_cap(x,n) for k,x in v.items()}
    return v
def page(items,offset=0,limit=50):
    items=list(items or [])
    try:offset=max(0,int(offset))
    except Exception:offset=0
    try:limit=max(1,min(MAX_PAGE,int(limit)))
    except Exception:limit=50
    chunk=items[offset:offset+limit]
    return {"items":_cap(chunk),"total":len(items),"offset":offset,"limit":limit,"more":offset+limit<len(items)}
_PAGE_FOR_KIND={"notes":"notes","commands":"commands","targets":"targets","reports":"reporting","quickrun":"snippets","dashboard":"dashboard","cve":"cve"}
ui_events=[]
_last_notify={}
_ENTITY_KIND={"Notes":"notes","Commands":"commands","Targets":"targets","Parameter":"targets","Reports":"reports","Quick Run":"quickrun","Action Chains":"chains","Tags":"notes","Recycle Bin":"dashboard","CVE Intel":"cve"}
def notify_after(tool_name):
    """Any successful change made by an AI tool (not only the ones in this file) refreshes the matching page."""
    key=_ai.permission_key(tool_name)
    if not key:return
    entity,action=_ai.PERMISSION_LABELS.get(key,("",""))
    if action in ("Read","Secrets"):return
    kind=_ENTITY_KIND.get(entity)
    if kind:notify_ui(kind)
def install_ui_refresh(server):
    orig=server.call_tool
    if getattr(orig,"_loya_ui_refresh",False):return server
    async def call_tool(name,arguments,context=None,*a,**k):
        result=await orig(name,arguments,context,*a,**k)
        try:
            if not getattr(result,"is_error",False) and not getattr(result,"isError",False):notify_after(name)
        except Exception:pass
        return result
    call_tool._loya_ui_refresh=True
    server.call_tool=call_tool
    return server
def _notify_js(kind,page_name):
    return ("(function(k,p){try{document.dispatchEvent(new CustomEvent('loya:ai-data-changed',{detail:{kind:k}}));"
        "const a=document.querySelector('.page.active');const cur=a&&a.dataset.page;"
        "if(cur&&(cur===p||cur==='dashboard'))document.dispatchEvent(new CustomEvent('loya:page-shown',{detail:{page:cur,first:false,ai:true}}))}catch(e){}})"
        f"('{kind}','{page_name}');0")
# Built once from the fixed kind table: no tool name, argument or result ever reaches run_js.
_NOTIFY_SCRIPTS={k:_notify_js(k,_PAGE_FOR_KIND.get(k,"")) for k in ("notes","commands","targets","reports","quickrun","dashboard","cve","chains")}
def notify_ui(kind):
    """Tell the main window that the AI changed data: fires loya:ai-data-changed, and re-fires loya:page-shown for the
    visible page when it shows that kind of data (dashboard always), so it reloads like after any other change."""
    import time as _t
    ui_events.append(kind)
    del ui_events[:-50]
    now=_t.time()
    if now-_last_notify.get(kind,0)<0.25:return False  # one refresh for a burst of changes
    _last_notify[kind]=now
    js=_NOTIFY_SCRIPTS.get(kind)
    if js is None:return False
    try:
        from Cores.Bridge import api as _api
        main=_api._windows.get("main")
        if main is None:return False
        threading.Thread(target=lambda:(main.run_js(js) if hasattr(main,"run_js") else main.evaluate_js(js)),daemon=True).start()
        return True
    except Exception:
        return False
_CONTEXT_JS=("(function(){try{const a=document.querySelector('.page.active');const o={page:a?a.dataset.page:''};"
    "if(typeof notesState!=='undefined'&&notesState.selectedId){const n=notesState.selectedNote||{};o.note={id:notesState.selectedId,name:n.name||n.title||''};o.note_editing=!!notesState.editId}"
    "if(typeof rpgS!=='undefined'&&rpgS.report){o.report={id:rpgS.report.id,title:rpgS.report.title||'',section:rpgS.entry||''}}"
    "return JSON.stringify(o)}catch(e){return '{}'}})()")
def ui_state(timeout=2.0):
    """What the user is looking at, read from the main window (empty when there is no window, e.g. in tests)."""
    try:
        from Cores.Bridge import api as _api
        main=_api._windows.get("main")
    except Exception:
        main=None
    if main is None:return {}
    box={}
    def run():
        try:box["v"]=main.evaluate_js(_CONTEXT_JS)
        except Exception:box["v"]=None
    t=threading.Thread(target=run,daemon=True);t.start();t.join(timeout)
    try:return json.loads(box.get("v") or "{}")
    except Exception:return {}
def _api():
    from Cores.Bridge import api as a
    return a
def _reports():
    from Cores.Bridge.reports_api import ReportsAPI
    return ReportsAPI()
def _evidence():
    from Cores.Bridge.evidence_api import EvidenceAPI
    return EvidenceAPI()
def _esc(s):return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
# ---------------------------------------------------------------- tools
def register(server,check):
    install_ui_refresh(server)
    a=_api()
    notes_api=a.NotesAPI();commands_api=a.CommandsAPI();targets_api=a.TargetsAPI();search_api=a.SearchAPI()
    # ---- App
    @server.tool(description="What the operator is looking at right now: the visible page, the selected note (id, name) and report (id, title), and the live target (name and values; secret-looking values are hidden). Call this first when a request says 'this note', 'this report' or 'the target'.")
    def app_context() -> dict:
        check("app_context",{})
        out=ui_state()
        try:
            lt=search_api.live_target()
            out["live_target"]={"name":lt.get("name") or "","values":mask_values(lt.get("map") or {})}
        except Exception:out["live_target"]=None
        return out
    @server.tool(description="Search the whole app at once (notes, commands, targets and the other things the search bar covers) and return the grouped results.")
    def app_search(query: str,limit: int=30) -> dict:
        check("app_search",{"query":query})
        q=str(query or "").strip()
        if not q:raise ValueError("query is required.")
        from Cores.Services import search_service as _search_svc
        res=_search_svc.global_search(q[:200],hide_secret_values=True)  # target secrets are neither matched nor shown
        return _cap(res if not isinstance(res,list) else page(res,0,limit))
    @server.tool(description="The dashboard numbers: counts of notes, commands, targets, reports and findings, and recent activity.")
    def dashboard_stats() -> dict:
        check("dashboard_stats",{})
        return _cap(a.DashboardAPI().stats())
    @server.tool(description="Read the security audit log (newest first): logins/locks, AI tool calls and approvals, terminal commands. Secrets are redacted. event filters by event name (e.g. ai_tool, terminal_command). Off unless the operator allows AI Roles > Audit Log > Read.")
    def audit_log_read(limit: int=50,offset: int=0,event: str="") -> dict:
        check("audit_log_read",{"limit":limit,"event":event})
        from Cores.Services import security_service as _sec
        from Cores.Services import terminal_service as _term
        rows=_sec.list_audit_events(1000)
        if event:rows=[r for r in rows if r.get("event")==event]
        rows=[dict(r,detail=_term.redact_secrets(str(r.get("detail") or ""))[0]) for r in rows]
        return page(rows,offset,limit)
    # ---- Notes
    @server.tool(description="Full-text search inside note contents. Returns matching notes with a snippet.")
    def notes_search(query: str,limit: int=50,offset: int=0) -> dict:
        check("notes_search",{"query":query})
        return page(notes_api.search_content(str(query or "")[:200],MAX_PAGE*2),offset,limit)
    @server.tool(description="List note groups (folders) with their note counts and pinned notes.")
    def notes_groups() -> list:
        check("notes_groups",{})
        return _cap(notes_api.groups())
    @server.tool(description="Create an empty note group (folder).")
    def notes_group_create(name: str) -> dict:
        check("notes_group_create",{"name":name})
        r=notes_api.create_group(name);notify_ui("notes");return r if isinstance(r,dict) else {"ok":bool(r),"group":name}
    @server.tool(description="Rename a note group; its notes move with it.")
    def notes_group_rename(old_name: str,new_name: str) -> dict:
        check("notes_group_rename",{"old_name":old_name,"new_name":new_name})
        r=notes_api.rename_group(old_name,new_name);notify_ui("notes");return {"changed":r}
    @server.tool(description="Move a note into a group (an empty group name moves it out of every group).")
    def notes_move(note_id: int,group: str) -> dict:
        check("notes_move",{"note_id":note_id,"group":group})
        r=notes_api.move_note(note_id,group);notify_ui("notes");return {"ok":bool(r) if not isinstance(r,dict) else True,"result":r}
    @server.tool(description="Pin or unpin a note in the sidebar.")
    def notes_pin(note_id: int,pinned: bool=True) -> dict:
        check("notes_pin",{"note_id":note_id,"pinned":pinned})
        note=notes_api.get(note_id)
        r=notes_api.set_pinned(note_id,note.get("name",""),bool(pinned));notify_ui("notes");return {"ok":True,"result":r}
    @server.tool(description="List the saved versions (history) of a note: version id, time and size. Every save keeps one.")
    def notes_versions(note_id: int) -> list:
        check("notes_versions",{"note_id":note_id})
        return _cap(notes_api.versions(note_id))[:MAX_PAGE]
    @server.tool(description="Show what changed between a saved version of a note and the current note.")
    def notes_version_diff(note_id: int,version_id: int) -> dict:
        check("notes_version_diff",{"note_id":note_id,"version_id":version_id})
        r=notes_api.version_diff(note_id,version_id)
        return _cap(r if isinstance(r,dict) else {"diff":r})
    @server.tool(description="Restore a note to one of its saved versions (the current text is kept as a version first, so this can be undone).")
    def notes_restore_version(note_id: int,version_id: int) -> dict:
        check("notes_restore_version",{"note_id":note_id,"version_id":version_id})
        r=notes_api.restore_version(note_id,version_id);notify_ui("notes")
        return r if isinstance(r,dict) else {"ok":bool(r)}
    @server.tool(description="Attach a file or image to the END of a note. data_base64 is the file content in base64 (max 5 MB); nothing is read from disk paths. Images show inline, other files as a download chip.")
    def notes_attachment_add(note_id: int,filename: str,data_base64: str) -> dict:
        check("notes_attachment_add",{"note_id":note_id,"filename":filename,"size":len(data_base64 or "")})
        if len(data_base64 or "")>7_000_000:raise ValueError("The attachment is larger than 5 MB.")
        att=notes_api.insert_attachment(filename,data_base64)
        inner=f'<img src="{_esc(att["url"])}" alt="{_esc(att["filename"])}">' if att.get("kind")=="image" else f'<div class="note-embed-file"><i class="icon icon-save"></i><span class="note-embed-filename">{_esc(att["filename"])}</span></div>'
        html=f'<figure class="note-embed note-embed-inline" contenteditable="false" data-attachment-id="{_esc(att["id"])}" data-attachment-url="{_esc(att["url"])}" data-kind="{_esc(att.get("kind",""))}">{inner}</figure>'
        notes_api.append(note_id,html);notify_ui("notes")
        return {"id":att["id"],"filename":att["filename"],"kind":att.get("kind"),"size":att.get("size")}
    # ---- Commands and terminal history
    @server.tool(description="The command history: commands recently copied, inserted or run from LOYA, newest first.")
    def commands_history(limit: int=50,offset: int=0) -> dict:
        check("commands_history",{"limit":limit})
        return page(commands_api.history(),offset,limit)
    @server.tool(description="Past runs of one saved command (source is 'CommandsNotes' for standalone commands or 'Notes' for command blocks in notes): time, target and the text that ran.")
    def command_runs(command_id: int,source: str="CommandsNotes",limit: int=50) -> dict:
        check("command_runs",{"command_id":command_id,"source":source})
        return page(commands_api.runs(command_id,source),0,limit)
    @server.tool(description="List terminal jobs (commands run in the operator's terminal sessions) with state, exit code and timing. Needs AI Roles > Terminal > Read.")
    def terminal_jobs_list(limit: int=50,session_id: str="") -> dict:
        check("terminal_jobs_list",{"limit":limit,"session_id":session_id})
        from Cores.Services import terminal_service as _term
        return page(_term.list_jobs(session_id or None,MAX_PAGE),0,limit)
    @server.tool(description="One terminal job with its captured output (secrets redacted, long output cut). Needs AI Roles > Terminal > Read.")
    def terminal_job_get(job_id: str) -> dict:
        check("terminal_job_get",{"job_id":job_id})
        from Cores.Services import terminal_service as _term
        job=_term.get_job(job_id)
        if not job:raise ValueError("No such job.")
        def red(v):
            if isinstance(v,str):return _term.redact_secrets(v)[0]
            if isinstance(v,dict):return {k:red(x) for k,x in v.items()}
            if isinstance(v,list):return [red(x) for x in v]
            return v
        return _cap(red(job),20_000)
    # ---- Targets
    @server.tool(description="The live target (the one placeholders are filled from): name and values. Values that look like secrets (passwords, hashes, tokens, keys) are hidden; targets_secret_values shows them if the operator allows it.")
    def targets_live_get() -> dict:
        check("targets_live_get",{})
        lt=search_api.live_target()
        return {"name":lt.get("name") or "","values":mask_values(lt.get("map") or {})}
    @server.tool(description="Make a target the live target (by id from targets_list). Commands and Quick Run fill their {placeholders} from it.")
    def targets_set_live(target_id: str) -> dict:
        check("targets_set_live",{"target_id":target_id})
        targets_api.set_live_target(target_id);notify_ui("targets")
        return {"ok":True,"live":target_id}
    @server.tool(description="Set a target's engagement status, e.g. not_started, in_progress, done (the values the Targets page offers).")
    def targets_set_engagement_status(target_id: str,status: str) -> dict:
        check("targets_set_engagement_status",{"target_id":target_id,"status":status})
        targets_api.set_engagement_status(target_id,status);notify_ui("targets")
        return {"ok":True}
    @server.tool(description="Unmasked values of one target, including passwords, hashes and tokens. Deny by default: needs AI Roles > Targets > Secrets.")
    def targets_secret_values(target_id: str) -> dict:
        check("targets_secret_values",{"target_id":target_id})
        for t in targets_api.targets():
            if str(t.get("id"))==str(target_id):return {"id":t.get("id"),"name":t.get("name"),"values":t.get("values") or {}}
        raise ValueError("No such target.")
    @server.tool(description="List target profiles (separate sets of targets, e.g. one per engagement) and which one is active.")
    def target_profiles_list() -> object:
        check("target_profiles_list",{})
        return targets_api.list_profiles()
    @server.tool(description="Create a new, empty target profile.")
    def target_profile_create(name: str) -> object:
        check("target_profile_create",{"name":name})
        r=targets_api.create_profile(name);notify_ui("targets");return r
    @server.tool(description="Switch the active target profile (by id from target_profiles_list).")
    def target_profile_switch(profile_id: str) -> object:
        check("target_profile_switch",{"profile_id":profile_id})
        r=targets_api.switch_profile(profile_id);notify_ui("targets");return r
    # ---- Reports
    @server.tool(description="Report statistics: reports by status and findings by severity.")
    def reports_stats() -> dict:
        check("reports_stats",{})
        return _cap(_reports().stats())
    @server.tool(description="Upcoming report deadlines and milestones across all reports.")
    def reports_deadlines() -> object:
        check("reports_deadlines",{})
        return _cap(_reports().deadlines())
    @server.tool(description="List the saved versions (snapshots) of a report.")
    def report_versions_list(report_id: int) -> object:
        check("report_versions_list",{"report_id":report_id})
        return _cap(_reports().versions(report_id))
    @server.tool(description="Save a snapshot (version) of a report now, with an optional label. Do this before large edits.")
    def report_version_create(report_id: int,label: str="") -> object:
        check("report_version_create",{"report_id":report_id,"label":label})
        r=_reports().version_create(report_id,label[:200]);notify_ui("reports");return r
    @server.tool(description="Restore a report to a saved version (by id from report_versions_list).")
    def report_version_restore(report_id: int,version_id: int) -> object:
        check("report_version_restore",{"report_id":report_id,"version_id":version_id})
        r=_reports().version_restore(report_id,version_id);notify_ui("reports");return _cap(r)
    @server.tool(description="A report's schedule: milestones such as kickoff, testing window, draft and final delivery dates.")
    def report_schedule_get(report_id: int) -> dict:
        check("report_schedule_get",{"report_id":report_id})
        return _reports().schedule_get(report_id)
    @server.tool(description="Replace a report's schedule. schedule is {\"milestones\":[{\"label\":\"Final report\",\"date\":\"2026-12-01\",\"done\":false}]} - the same shape report_schedule_get returns; the app validates it.")
    def report_schedule_set(report_id: int,schedule: dict) -> dict:
        check("report_schedule_set",{"report_id":report_id,"schedule":schedule})
        r=_reports().schedule_set(report_id,schedule);notify_ui("reports");return r
    @server.tool(description="Get one report template (sections and placeholder text) by id from report_templates_list.")
    def report_template_get(template_id: str) -> object:
        check("report_template_get",{"template_id":template_id})
        return _cap(_reports().template_get(template_id))
    @server.tool(description="Save text as evidence (e.g. a command and its output) so it can be attached to findings. Secrets are redacted by the evidence store when its redaction setting is on.")
    def report_evidence_add_text(content: str,title: str="",command: str="",notes: str="",tags: str="") -> dict:
        check("report_evidence_add_text",{"title":title,"command":command,"size":len(content or "")})
        r=_evidence().save_text({"content":content,"title":title,"command":command,"notes":notes,"tags":tags});notify_ui("reports")
        return _cap(r,2000) if isinstance(r,dict) else {"result":r}
    @server.tool(description="Save an image (base64 PNG/JPEG, max 5 MB) as screenshot evidence.")
    def report_evidence_add_image(name: str,data_base64: str,title: str="") -> dict:
        check("report_evidence_add_image",{"name":name,"title":title,"size":len(data_base64 or "")})
        if len(data_base64 or "")>7_000_000:raise ValueError("The image is larger than 5 MB.")
        r=_evidence().save_image(name,data_base64,title);notify_ui("reports")
        return {k:v for k,v in (r or {}).items() if k not in ("data","data_url")} if isinstance(r,dict) else {"result":r}
    @server.tool(description="Add a reusable write-up to the Findings Library. entry has title (required), severity, cvss_vector, cwe, owasp, description, impact, remediation, references (list of URLs) and tags.")
    def findings_library_add(entry: dict) -> object:
        check("findings_library_add",{"entry":entry})
        if not isinstance(entry,dict) or not str(entry.get("title") or "").strip():raise ValueError("entry.title is required.")
        r=_reports().library_save(entry);notify_ui("reports");return _cap(r)
    @server.tool(description="Add a finding to a report from a Findings Library entry (library_id from findings_library_search).")
    def findings_add_from_library(report_id: int,library_id: int) -> object:
        check("findings_add_from_library",{"report_id":report_id,"library_id":library_id})
        r=_reports().finding_from_library(report_id,library_id);notify_ui("reports");return _cap(r)
    @server.tool(description="Add a finding to a report from a CVE: title, severity and CVSS, CWE, description, impact, remediation and references come from LOYA's CVE data (cve_id like CVE-2024-3400). Review and adjust it with findings_update.")
    def findings_add_from_cve(report_id: int,cve_id: str) -> object:
        check("findings_add_from_cve",{"report_id":report_id,"cve_id":cve_id})
        from Cores.Services import cve_service as _cve
        f=_cve.to_finding(str(cve_id or "").strip().upper())
        fields={"title":f.get("title") or cve_id,"description":_esc(f.get("description") or ""),"impact":_esc(f.get("impact") or ""),"remediation":_esc(f.get("remediation") or ""),
                "cwe":f.get("cwe") or "","references":[u for u in (f.get("reference_urls") or []) if isinstance(u,str)][:40],"cves":[f.get("cve_id") or cve_id],"source":{"kind":"cve","ref":f.get("cve_id") or cve_id}}
        if f.get("cvss_vector"):fields["cvss_vector"]=f["cvss_vector"]
        elif f.get("severity"):fields["severity"]=str(f["severity"]).lower()
        affected=[x for x in (f.get("affected") or []) if isinstance(x,str)][:30]
        if affected:fields["affected"]=affected
        r=_reports().finding_add(report_id,fields);notify_ui("reports")
        r=_cap(r)
        if isinstance(r,dict) and (f.get("stale") or f.get("origin")=="index"):
            r["note"]="Only the offline CVE index had this CVE (online lookups are off), so description, impact and references are minimal. Fill them in with findings_update."
        return r
    # ---- report scope from Targets (target_allow_secret and targets_restore are deliberately not exposed)
    @server.tool(description="Targets that can be linked to a report as its scope, across all target profiles: target_id, profile_id, name, engagement status and non-secret values (secret values are never included). query filters by name or value.")
    def report_targets_available(query: str="",limit: int=100) -> dict:
        check("report_targets_available",{"query":query})
        return page(_reports().targets_available(query or None),0,limit)
    @server.tool(description="The targets linked to a report (its scope): link uid, target, profile, a snapshot of the values at link time and whether the target has changed since (state ok/changed/removed).")
    def report_targets_list(report_id: int) -> list:
        check("report_targets_list",{"report_id":report_id})
        return _cap(mask_report_links(_reports().targets_list(report_id)))
    @server.tool(description="Link targets to a report's scope. items is a list of {\"target_id\":..., \"profile_id\":...} from report_targets_available. Only non-secret values are copied; already-linked targets are skipped.")
    def report_target_link(report_id: int,items: list) -> list:
        check("report_target_link",{"report_id":report_id,"items":items})
        clean=[{"target_id":str(i.get("target_id") or ""),"profile_id":str(i.get("profile_id") or "")} for i in (items or []) if isinstance(i,dict)][:200]
        if not clean:raise ValueError("items needs at least one {target_id, profile_id}.")
        r=_reports().target_link(report_id,clean);notify_ui("reports");return _cap(mask_report_links(r))
    @server.tool(description="Remove a target (by link uid) from a report's scope; it is also removed from the report's findings.")
    def report_target_unlink(report_id: int,uid: str) -> list:
        check("report_target_unlink",{"report_id":report_id,"uid":uid})
        r=_reports().target_unlink(report_id,uid);notify_ui("reports");return _cap(mask_report_links(r))
    @server.tool(description="Refresh a linked target's snapshot from the Targets page ('Update from target'): one link by uid, or every link when uid is empty.")
    def report_target_update(report_id: int,uid: str="") -> list:
        check("report_target_update",{"report_id":report_id,"uid":uid})
        r=_reports().target_update(report_id,uid or None);notify_ui("reports");return _cap(mask_report_links(r))
    @server.tool(description="Reorder a report's scope targets: uids is the full list of link uids in the new order.")
    def report_targets_reorder(report_id: int,uids: list) -> list:
        check("report_targets_reorder",{"report_id":report_id,"uids":uids})
        r=_reports().targets_reorder(report_id,[str(u) for u in (uids or [])][:500]);notify_ui("reports");return _cap(mask_report_links(r))
    @server.tool(description="Set which scope targets a finding affects: targets is [{\"uid\": link uid, \"keys\": [value keys to show, e.g. \"IP\", \"@name\"]}]. Unknown uids are dropped.")
    def finding_targets_set(finding_id: int,targets: list) -> dict:
        check("finding_targets_set",{"finding_id":finding_id,"targets":targets})
        clean=[{"uid":str(t.get("uid") or ""),"keys":[str(k) for k in (t.get("keys") or [])][:50]} for t in (targets or []) if isinstance(t,dict)][:200]
        r=_reports().finding_targets_set(finding_id,clean);notify_ui("reports");return _cap(r)
    # ---- CVE intelligence
    @server.tool(description="Search LOYA's local CVE index by keyword or product (e.g. 'fortinet ssl vpn'). Returns CVE ids with title, severity and score.")
    def cve_search(query: str,limit: int=20) -> object:
        check("cve_search",{"query":query})
        from Cores.Services import cve_service as _cve
        return _cap(_cve.search(str(query or "")[:200],max(1,min(50,int(limit))),None))
    @server.tool(description="The CVE news feed / watchlist LOYA shows on the CVE page: recent and known-exploited CVEs matching the operator's watch terms.")
    def cve_feed(limit: int=30,offset: int=0) -> dict:
        check("cve_feed",{"limit":limit})
        from Cores.Services import cve_service as _cve
        f=_cve.feed(None)
        out=page(f.get("items") or [],offset,limit)
        out["feed_total"]=f.get("total");out["unread"]=f.get("unread")
        return out
    # ---- Quick Run
    @server.tool(description="The Quick Run favourites (pinned commands), as keys 'source:id' matching quickrun_list.")
    def quickrun_favorites() -> dict:
        check("quickrun_favorites",{})
        return search_api.favorites()
    @server.tool(description="Pin or unpin a Quick Run command as a favourite. key is 'source:id' (source and id from quickrun_list).")
    def quickrun_favorite_set(key: str,favorite: bool=True) -> dict:
        check("quickrun_favorite_set",{"key":key,"favorite":favorite})
        if not re.match(r"^[A-Za-z0-9_]{1,40}:\d{1,12}$",str(key or "")):raise ValueError("key must look like 'CommandsNotes:12'.")
        cur=search_api.favorites()
        favs=[f for f in cur["favorites"] if f!=key]+([key] if favorite else [])
        search_api.set_favorites(favs,cur["favorites_only"]);notify_ui("quickrun")
        return search_api.favorites()
    # ---- resources and prompts (read-only; resources go through the same permission checks)
    @server.resource("loya://app/context",name="app-context",description="What the operator is looking at: page, selected note/report, live target (secrets hidden).",mime_type="application/json")
    def res_app_context() -> str:
        return json.dumps(app_context(),default=str)
    @server.resource("loya://targets/live",name="live-target",description="The live target's name and values (secrets hidden).",mime_type="application/json")
    def res_live_target() -> str:
        return json.dumps(targets_live_get(),default=str)
    @server.resource("loya://reports/{report_id}/outline",name="report-outline",description="A report's outline: title, status, sections and findings (title, severity, score).",mime_type="application/json")
    def res_report_outline(report_id: str) -> str:
        check("reports_get",{"report_id":report_id})
        r=_reports().get(int(report_id))
        out={"id":r.get("id"),"title":r.get("title"),"status":r.get("status"),"sections":[{"id":s.get("id"),"kind":s.get("kind"),"title":s.get("title")} for s in r.get("sections") or []],
             "findings":[{"id":f.get("id"),"title":f.get("title"),"severity":f.get("severity"),"cvss_score":f.get("cvss_score"),"status":f.get("status")} for f in r.get("findings") or []]}
        return json.dumps(out,default=str)
    @server.prompt(name="loya-note-from-output",description="Turn pasted tool output into a structured LOYA note (summary, findings callouts, command blocks).")
    def prompt_note_from_output(output: str,title: str="") -> str:
        return ("Create a LOYA note"+(f" titled '{title}'" if title else "")+" from this output. Use notes_create; put each command that was run in a command block "
                "(get the HTML from notes_command_block_html), summarise what was found, and mark anything sensitive as a credential callout instead of copying secrets. "
                +_element_rules.ELEMENT_RULE_SHORT+"\n\n"+str(output or "")[:MAX_TEXT])
    @server.prompt(name="loya-finding-from-cve",description="Add a report finding from a CVE and tailor it to the engagement.")
    def prompt_finding_from_cve(report_id: str,cve_id: str) -> str:
        return (f"In report {report_id}, call findings_add_from_cve for {cve_id}. Then read the live target (targets_live_get) and the report (reports_get), "
                "and use findings_update to make the affected hosts, impact and steps specific to this engagement. Keep the CVSS vector unless you have evidence it differs.")
    return server
