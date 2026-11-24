import os,re,json,time,threading,html
from datetime import datetime,timezone
from Cores import common_db,recycle_bin,target_profiles
from Cores.Update import get_app_version as _get_app_version
from Cores import doc_store as _doc_store
_settings_lock=threading.Lock()
def _root(*p):return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p))
def _backups_dir():return common_db.backups_dir()
def _targets_path():return target_profiles.profile_targets_json_path()
# kind = the card type that renders the widget (card.js). group/description feed the Add Card picker.
WIDGET_CATALOG=[
    {"id":"quick_actions","label":"Quick Actions","icon":"play","kind":"actions","default_size":"1x1","group":"Overview","description":"One-click buttons: new note, command or target, terminal, action chains, search."},
    {"id":"live_target","label":"Live Target","icon":"target","kind":"live","default_size":"1x1","group":"Targets","description":"The target in use, its values with copy buttons, and a quick switch."},
    {"id":"notes_count","label":"Notes","icon":"edit","kind":"kpi","default_size":"0.25x1.5","group":"Overview","description":"Total notes, new this week and a 14-day trend."},
    {"id":"commands_count","label":"Commands","icon":"commands","kind":"kpi","default_size":"0.25x1.5","group":"Overview","description":"Total commands, new this week and a 14-day trend."},
    {"id":"targets_count","label":"Targets","icon":"target","kind":"kpi","default_size":"0.25x1.5","group":"Overview","description":"Saved targets in the active profile, new this week."},
    {"id":"terminal_jobs","label":"Running Jobs","icon":"command-line","kind":"kpi","default_size":"0.25x1.5","group":"Terminal","description":"Terminal jobs running now and jobs started per day."},
    {"id":"activity_heat","label":"Activity (30 days)","icon":"clock","kind":"heat","default_size":"2x0.5","group":"Overview","description":"Notes, commands and jobs per day over the last 30 days."},
    {"id":"recent_activity","label":"Recent Activity","icon":"list","kind":"feed","default_size":"1x1.5","group":"Overview","description":"Notes and commands edited, targets changed, jobs finished."},
    {"id":"recent_jobs","label":"Recent Jobs","icon":"command-line","kind":"list","default_size":"1x1.5","group":"Terminal","description":"Last terminal jobs with exit status and duration; re-run or view output."},
    {"id":"engagements","label":"Engagements","icon":"table","kind":"bars","default_size":"1x1","group":"Targets","description":"Targets by engagement status."},
    {"id":"notes_by_group","label":"Notes by Group","icon":"table","kind":"wheel","default_size":"1x1","group":"Notes","description":"How your notes are spread across groups."},
    {"id":"most_used_commands","label":"Most-Used Commands","icon":"commands","kind":"list","default_size":"1x1.5","group":"Commands","description":"Commands you run most, ready to run, insert or copy with the live target filled in."},
    {"id":"favorite_snippets","label":"Quick Run Favourites","icon":"star-filled","kind":"list","default_size":"1x1.5","group":"Commands","description":"Commands you starred on Quick Run, ready to run, insert or copy."},
    {"id":"missing_placeholders","label":"Missing Elements","icon":"info","kind":"chips","default_size":"1x1.5","group":"Targets","description":"{KEYS} your commands use that the live target has no value for."},
    {"id":"reports","label":"Reports","icon":"report","kind":"reports","default_size":"1x1.5","group":"Reporting","description":"Reports by status, open findings by severity, the next deadline and your latest reports."},
    {"id":"recent_notes","label":"Recently Edited Notes","icon":"edit","kind":"list","default_size":"1x1","group":"Notes","description":"Notes you changed most recently."},
    {"id":"pinned_notes","label":"Pinned Notes","icon":"pin","kind":"list","default_size":"1x1","group":"Notes","description":"Your pinned notes, one click away."},
    {"id":"security_health","label":"Security & Backup","icon":"settings","kind":"status","default_size":"1x1","group":"System","description":"Last backup, app lock, encryption and audit-log expiry at a glance."},
    {"id":"recycle_bin_count","label":"Recycle Bin","icon":"trash","kind":"stat","default_size":"0.25x1","group":"System","description":"Items waiting in the Recycle Bin."},
    {"id":"backup_status","label":"Backup Status","icon":"save","kind":"stat","default_size":"0.25x1","group":"System","description":"When the last backup was made."},
    {"id":"storage_usage","label":"Storage Usage","icon":"info","kind":"stat","default_size":"0.25x1","group":"System","description":"Database size on disk."},
    {"id":"time_since_activity","label":"Last Activity","icon":"clock","kind":"stat","default_size":"1x1","group":"Overview","description":"Time since the last change."},
    {"id":"active_engagement","label":"Active Profile","icon":"target","kind":"stat","default_size":"1x1","group":"Targets","description":"The active target profile."},
    {"id":"update_status","label":"Update Status","icon":"info","kind":"stat","default_size":"1x1","group":"System","description":"Whether a newer version is available."},
]
# Removed widgets: dropped from loaded layouts (in memory only) so old saved layouts still load cleanly.
RETIRED_WIDGETS={"app_version"}
SIZE_PRESETS=["0.25x1","0.25x1.5","1x1","1x1.5","1x2","2x0.5","2x1","2x2","full"]
def _card(widget,size):return {"id":widget,"widget":widget,"size":size}
DEFAULT_LAYOUT=[
    _card("quick_actions","1x1"),_card("live_target","1x1"),
    _card("notes_count","0.25x1.5"),_card("commands_count","0.25x1.5"),_card("targets_count","0.25x1.5"),_card("terminal_jobs","0.25x1.5"),
    _card("activity_heat","2x0.5"),
    _card("recent_activity","1x1.5"),_card("recent_jobs","1x1.5"),
    _card("engagements","1x1"),_card("notes_by_group","1x1"),
    _card("most_used_commands","1x1.5"),_card("missing_placeholders","1x1.5"),
    _card("recent_notes","1x1"),_card("security_health","1x1"),
]
CLASSIC_LAYOUT=[
    _card("notes_by_group","1x2"),_card("notes_count","1x1"),_card("commands_count","1x1"),_card("targets_count","1x1"),
    _card("recycle_bin_count","1x1"),_card("backup_status","0.25x1"),_card("storage_usage","0.25x1"),
]
OPERATOR_LAYOUT=[
    _card("live_target","1x1.5"),_card("missing_placeholders","1x1.5"),
    _card("terminal_jobs","0.25x1.5"),_card("targets_count","0.25x1.5"),_card("commands_count","0.25x1.5"),_card("notes_count","0.25x1.5"),
    _card("most_used_commands","1x1.5"),_card("favorite_snippets","1x1.5"),
    _card("recent_jobs","1x1.5"),_card("engagements","1x1.5"),
]
PRESETS=[
    {"id":"default","name":"Organized (default)","description":"Quick actions and live target first, then KPIs, activity, jobs and targets.","cards":DEFAULT_LAYOUT},
    {"id":"operator","name":"Operator","description":"Live target, missing elements, commands and jobs for hands-on testing.","cards":OPERATOR_LAYOUT},
    {"id":"classic","name":"Classic","description":"The original dashboard: counts and notes by group.","cards":CLASSIC_LAYOUT},
]
def _db_counts():
    counts={"notes":0,"commands_standalone":0,"commands_linked":0,"groups":{}}
    try:
        with _connect() as con:
            cur=con.cursor()
            cur.execute("SELECT COUNT(*) FROM Notes");counts["notes"]=int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM CommandsNotes");counts["commands_standalone"]=int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM Commands");counts["commands_linked"]=int(cur.fetchone()[0])
            cur.execute("SELECT COALESCE(NULLIF(TRIM(group_name),''),'Ungrouped') g,COUNT(*) FROM Notes GROUP BY g ORDER BY COUNT(*) DESC")
            counts["groups"]={row[0]:int(row[1]) for row in cur.fetchall()}
    except Exception:
        pass
    return counts
def _targets_count():
    try:
        d=_doc_store.read_json(_targets_path(),[])
        return len(d) if isinstance(d,list) else 0
    except Exception:
        return 0
def _recycle_bin_count():
    try:
        return len(recycle_bin.list_entries())
    except Exception:
        return 0
def _backup_status():
    d=_backups_dir()
    if not os.path.isdir(d):return {"count":0,"latest_days_ago":None}
    files=[os.path.join(d,n) for n in os.listdir(d) if os.path.isfile(os.path.join(d,n))]
    if not files:return {"count":0,"latest_days_ago":None}
    latest=max(os.path.getmtime(p) for p in files)
    days=max(0,int((time.time()-latest)//86400))
    return {"count":len(files),"latest_days_ago":days}
def _storage_usage():
    try:
        return os.path.getsize(common_db.db_path())
    except Exception:
        return 0
def _parse_iso_ts(raw):
    raw=(raw or "").strip()
    if not raw:return None
    try:
        dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None
def _relative_time(ts):
    delta=max(0,time.time()-ts)
    if delta<60:return "Just now"
    if delta<3600:return f"{int(delta//60)}m ago"
    if delta<86400:return f"{int(delta//3600)}h ago"
    if delta<604800:return f"{int(delta//86400)}d ago"
    if delta<2592000:return f"{int(delta//604800)}w ago"
    return f"{int(delta//2592000)}mo ago"
def _time_since_activity():
    latest_ts=None;what=""
    try:
        with _connect() as con:
            cur=con.cursor()
            cur.execute("SELECT note_name,updated_at FROM Notes WHERE updated_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1")
            row=cur.fetchone()
            if row:
                ts=_parse_iso_ts(row[1])
                if ts is not None:
                    latest_ts=ts;what=f"Note: {row[0]}"
    except Exception:
        pass
    try:
        tp=_targets_path()
        if _doc_store.exists(tp):
            mtime=_doc_store.mtime(tp) or 0
            if latest_ts is None or mtime>latest_ts:
                latest_ts=mtime;what="Targets updated"
    except Exception:
        pass
    if latest_ts is None:return {"label":"No activity yet","what":""}
    return {"label":_relative_time(latest_ts),"what":what}
def _active_engagement():
    try:
        pid=target_profiles.active_profile_id()
        name=next((p.get("name") for p in target_profiles.list_profiles() if p.get("id")==pid),"Default")
    except Exception:
        name="Default"
    return {"name":name or "Default","targets_count":_targets_count()}
def _recent_activity(limit=6):
    items=[]
    try:
        with _connect() as con:
            cur=con.cursor()
            cur.execute("SELECT note_name,updated_at FROM Notes WHERE updated_at IS NOT NULL ORDER BY updated_at DESC LIMIT ?",(int(limit),))
            for name,ts in cur.fetchall():
                t=_parse_iso_ts(ts)
                if t is not None:
                    items.append({"label":f"Note: {name}","ts":t})
    except Exception:
        pass
    try:
        tp=_targets_path()
        if _doc_store.exists(tp):
            items.append({"label":"Targets updated","ts":_doc_store.mtime(tp) or 0})
    except Exception:
        pass
    items.sort(key=lambda x:x["ts"],reverse=True)
    items=items[:limit]
    return [{"label":it["label"],"relative":_relative_time(it["ts"])} for it in items]
def _update_status():
    try:
        from Cores.Update import update_service as _update_svc,update_helpers as _update_helpers
        state=_update_svc.get_update_state()
        cur=state.get("current_version","")
        latest=state.get("last_available_version","")
        if latest and cur:
            try:
                if _update_helpers.compare_semver(latest,cur)>0:
                    return {"label":"Update available","sub":f"{cur} -> {latest}"}
            except Exception:
                pass
        return {"label":"Up to date","sub":f"v{cur}" if cur else ""}
    except Exception:
        return {"label":"Unknown","sub":""}
def _terminal_jobs():
    try:
        from Cores.Services import terminal_service as _terminal_svc
        jobs=_terminal_svc.list_jobs(None,200)
    except Exception:
        return {"running":0,"failed":0,"total":0}
    running=sum(1 for j in jobs if j.get("state")=="running")
    failed=sum(1 for j in jobs if j.get("state") in ("failed","killed"))
    return {"running":running,"failed":failed,"total":len(jobs)}
import contextlib
@contextlib.contextmanager
def _connect():
    # sqlite3's own context manager only commits; it never closes, which leaves the DB file locked on Windows.
    con=common_db.connect(common_db.db_path(),timeout=5)
    try:
        common_db.ensure_schema(con)
        yield con
    finally:
        con.close()
def _local_day(ts):return datetime.fromtimestamp(ts).date()
def _day_series(timestamps,days,now=None):
    """Counts per local calendar day for the last `days` days, oldest first."""
    now=now if now is not None else time.time()
    today=_local_day(now)
    out=[0]*days
    for ts in timestamps:
        if ts is None:continue
        diff=(today-_local_day(ts)).days
        if 0<=diff<days:out[days-1-diff]+=1
    return out
def _week_count(timestamps,now=None):
    now=now if now is not None else time.time()
    return sum(1 for ts in timestamps if ts is not None and 0<=now-ts<7*86400)
def _read_targets():
    try:
        # Through doc_store: with encryption at rest the targets live in the encrypted DB, not in the JSON file.
        d=_doc_store.read_json(_targets_path(),[])
        return [t for t in d if isinstance(t,dict) and str(t.get("name") or "").strip()] if isinstance(d,list) else []
    except Exception:
        return []
def _kpis(now=None):
    notes_ts=[];cmd_ts=[];job_ts=[];running=0
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT created_at FROM Notes")
        notes_ts=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
        for table in ("CommandsNotes","Commands"):
            cur.execute(f"SELECT created_at FROM {table}")
            cmd_ts+=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT started_at FROM TerminalJobs WHERE started_at>=?",(datetime.fromtimestamp((now or time.time())-15*86400,timezone.utc).isoformat(),))
        job_ts=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM TerminalJobs WHERE state IN ('running','pending')")
        running=int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM TerminalJobs WHERE state IN ('failed','killed') AND started_at>=?",(datetime.fromtimestamp((now or time.time())-86400,timezone.utc).isoformat(),))
        failed_day=int(cur.fetchone()[0])
    targets=_read_targets()
    tgt_ts=[_parse_iso_ts(t.get("created")) for t in targets]
    return {
        "notes":{"value":len(notes_ts),"week":_week_count(notes_ts,now),"series":_day_series(notes_ts,14,now)},
        "commands":{"value":len(cmd_ts),"week":_week_count(cmd_ts,now),"series":_day_series(cmd_ts,14,now)},
        "targets":{"value":len(targets),"week":_week_count(tgt_ts,now),"series":_day_series(tgt_ts,14,now)},
        "jobs":{"value":running,"week":_week_count(job_ts,now),"series":_day_series(job_ts,14,now),"failed_day":failed_day},
    }
_ACTION_WORDS={"insert":"created","update":"edited","delete":"deleted","restore":"restored"}
def _activity_feed(limit=12,now=None):
    events=[]
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT note_id,note_name,action,action_at FROM NotesHistory ORDER BY id DESC LIMIT 200")
        for nid,name,action,at in cur.fetchall():
            ts=_parse_iso_ts(at)
            if ts is None:continue
            events.append({"kind":"note","ref_id":nid,"ref_src":"","title":name or "Untitled note","action":_ACTION_WORDS.get(action or "",action or "changed"),"ts":ts})
        cur.execute("SELECT cmd_id,note_name,category,action,action_at FROM CommandsNotesHistory ORDER BY id DESC LIMIT 100")
        for cid,name,cat,action,at in cur.fetchall():
            ts=_parse_iso_ts(at)
            if ts is None:continue
            events.append({"kind":"command","ref_id":cid,"ref_src":"CommandsNotes","title":name or cat or "Command","action":_ACTION_WORDS.get(action or "",action or "changed"),"ts":ts})
        cur.execute("SELECT job_key,label,command,state,exit_code,ended_at FROM TerminalJobs WHERE ended_at IS NOT NULL ORDER BY id DESC LIMIT 40")
        for key,label,command,state,code,at in cur.fetchall():
            ts=_parse_iso_ts(at)
            if ts is None:continue
            word={"done":"finished","failed":"failed","killed":"interrupted","skipped":"skipped","orphaned":"lost"}.get(state or "",state or "ended")
            if state=="failed" and code is not None:word=f"failed (exit {code})"
            events.append({"kind":"job","ref_id":key,"ref_src":"","title":(command or label or "command").strip().splitlines()[0][:120] if (command or label) else "command","action":word,"ts":ts})
    for t in _read_targets():
        created=_parse_iso_ts(t.get("created"));updated=_parse_iso_ts(t.get("updated"))
        ts=updated or created
        if ts is None:continue
        events.append({"kind":"target","ref_id":t.get("id") or "","ref_src":"","title":str(t.get("name")),"action":"created" if created and abs(ts-created)<2 else "updated","ts":ts})
    events.sort(key=lambda e:e["ts"],reverse=True)
    seen=set();out=[]
    for e in events:
        k=(e["kind"],str(e["ref_id"]))
        if k in seen:continue
        seen.add(k)
        e["deleted"]=e["action"]=="deleted"
        e["relative"]=_relative_time(e["ts"])
        out.append(e)
        if len(out)>=limit:break
    return out
_KIND_WORDS={"note":"Note","command":"Command","job":"Job","target":"Target"}
def _legacy_activity(feed):
    return [{"label":f"{_KIND_WORDS.get(e['kind'],'Item')}: {e['title']}","relative":e["relative"]} for e in feed[:6]]
def _duration_s(start,end,now=None):
    a=_parse_iso_ts(start);b=_parse_iso_ts(end) if end else (now if now is not None else time.time())
    if a is None or b is None or b<a:return None
    return int(round(b-a))
def _recent_jobs(limit=8,now=None):
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT COUNT(*) FROM TerminalJobs WHERE state IN ('running','pending')")
        running=int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM TerminalJobs")
        total=int(cur.fetchone()[0])
        cur.execute("SELECT job_key,session_id,label,command,source,state,exit_code,started_at,ended_at FROM TerminalJobs ORDER BY id DESC LIMIT ?",(int(limit),))
        rows=cur.fetchall()
    items=[]
    for key,sid,label,command,source,state,code,started,ended in rows:
        ts=_parse_iso_ts(started)
        items.append({"job_key":key,"session_id":sid or "","label":label or "","command":command or "","source":source or "","state":state or "","exit_code":code,"started_at":started or "","ended_at":ended or "","duration_s":_duration_s(started,ended,now),"relative":_relative_time(ts) if ts else ""})
    return {"running":running,"total":total,"items":items}
ENGAGEMENT_STATUSES=[("not_started","Not Started"),("in_progress","In Progress"),("compromised","Compromised"),("reported","Reported")]
def _engagements():
    counts={k:0 for k,_ in ENGAGEMENT_STATUSES}
    targets=_read_targets()
    for t in targets:
        st=str(t.get("engagement_status") or "").strip().lower()
        counts[st if st in counts else "not_started"]+=1
    return {"total":len(targets),"statuses":[{"id":k,"label":lbl,"count":counts[k]} for k,lbl in ENGAGEMENT_STATUSES]}
def _live_context():
    from Cores.Services import search_service as _search
    return _search.LiveTargetContext()
def _resolver():
    from Cores.Services import search_service as _search
    return _search.CommandReplacer(_live_context())
def _clean_cmd(text):
    from Cores.Services import search_service as _search
    return _search._clean_cmd(text)
def _command_rows(cur,keys):
    """Title/command/noise for (src,id) pairs that still exist."""
    out={}
    ids={"CommandsNotes":[],"Commands":[]}
    for src,cid in keys:
        if src in ids and cid is not None:ids[src].append(int(cid))
    for src,lst in ids.items():
        if not lst:continue
        marks=",".join("?"*len(lst))
        if src=="CommandsNotes":
            cur.execute(f"SELECT id,note_name,category,sub_category,command,noise_level FROM CommandsNotes WHERE id IN ({marks})",lst)
            for cid,name,cat,sub,cmd,noise in cur.fetchall():
                out[(src,int(cid))]={"title":(name or "").strip() or "Untitled","meta":" / ".join(x for x in ((cat or "").strip(),(sub or "").strip()) if x),"command":_clean_cmd(cmd),"noise_level":noise or "normal","note_id":None}
        else:
            cur.execute(f"SELECT id,note_id,note_name,cmd_note_title,category,sub_category,command,noise_level FROM Commands WHERE id IN ({marks})",lst)
            for cid,nid,nname,ttl,cat,sub,cmd,noise in cur.fetchall():
                out[(src,int(cid))]={"title":(ttl or "").strip() or (nname or "").strip() or "Untitled","meta":(nname or "").strip(),"command":_clean_cmd(cmd),"noise_level":noise or "normal","note_id":nid}
    return out
def _most_used_commands(limit=8):
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT command_id,src,COUNT(*),MAX(ran_at) FROM CommandRuns WHERE command_id IS NOT NULL GROUP BY command_id,src ORDER BY COUNT(*) DESC,MAX(ran_at) DESC LIMIT ?",(int(limit)*3,))
        runs=cur.fetchall()
        rows=_command_rows(cur,[(src,cid) for cid,src,_,_ in runs])
    rep=_resolver()
    out=[]
    for cid,src,count,last in runs:
        r=rows.get((src,int(cid)))
        if not r:continue
        ts=_parse_iso_ts(last)
        out.append(dict(r,id=int(cid),src=src,runs=int(count),relative=_relative_time(ts) if ts else "",resolved=rep.apply(r["command"])))
        if len(out)>=limit:break
    return out
def _favorite_snippets(limit=8):
    from Cores.Services import search_service as _search
    favs,_only=_search.load_favorites()
    keys=[]
    for f in favs:
        src,_,cid=str(f).partition(":")
        if src in ("CommandsNotes","Commands") and cid.isdigit():keys.append((src,int(cid)))
    if not keys:return []
    with _connect() as con:
        rows=_command_rows(con.cursor(),keys)
    rep=_resolver()
    out=[]
    for src,cid in keys:
        r=rows.get((src,cid))
        if not r:continue
        out.append(dict(r,id=cid,src=src,resolved=rep.apply(r["command"])))
    out.sort(key=lambda x:x["title"].lower())
    return out[:limit]
def _notes_lists(limit=8):
    from Cores.Services import notes_service as _notes
    try:pinned=_notes.pinned_note_ids()
    except Exception:pinned=set()
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT id,note_name,group_name,updated_at FROM Notes ORDER BY updated_at DESC,id DESC LIMIT ?",(int(limit),))
        recent=cur.fetchall()
        pinned_rows=[]
        if pinned:
            lst=sorted(int(x) for x in pinned)
            cur.execute(f"SELECT id,note_name,group_name,updated_at FROM Notes WHERE id IN ({','.join('?'*len(lst))}) ORDER BY note_name COLLATE NOCASE",lst)
            pinned_rows=cur.fetchall()
    def row(r):
        ts=_parse_iso_ts(r[3])
        return {"id":int(r[0]),"name":(r[1] or "").strip() or "Untitled","group":(r[2] or "").strip() or "Ungrouped","relative":_relative_time(ts) if ts else "","pinned":int(r[0]) in pinned}
    return [row(r) for r in recent],[row(r) for r in pinned_rows][:limit]
def _placeholder_spans(text):
    from Cores.Services import search_service as _search
    t=str(text or "")
    for start,_end,key in _search._iter_placeholders(t):
        if start>0 and t[start-1]=="$":continue
        yield key
def _live_target_record(targets):
    return next((t for t in targets if str(t.get("status") or "").lower()=="live"),None)
def _missing_placeholders(limit=12):
    targets=_read_targets()
    live=_live_target_record(targets)
    have={str(k).strip().lower() for k,v in ((live or {}).get("values") or {}).items() if str(v or "").strip()}
    usage={}
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT id,command FROM CommandsNotes WHERE command LIKE '%{%}%'")
        rows=[("s",cid,None,cmd) for cid,cmd in cur.fetchall()]
        cur.execute("SELECT id,note_id,command FROM Commands WHERE command LIKE '%{%}%'")
        rows+=[("l",cid,nid,cmd) for cid,nid,cmd in cur.fetchall()]
    for kind,cid,nid,cmd in rows:
        for key in set(_placeholder_spans(_clean_cmd(cmd))):
            lk=key.lower()
            u=usage.setdefault(lk,{"key":key,"commands":set(),"notes":set()})
            u["commands"].add((kind,cid))
            if nid is not None:u["notes"].add(nid)
    missing=[{"key":u["key"],"commands":len(u["commands"]),"notes":len(u["notes"])} for lk,u in usage.items() if lk not in have]
    missing.sort(key=lambda m:(-m["commands"],m["key"].lower()))
    return {"live":bool(live),"live_id":(live or {}).get("id") or "","live_name":str((live or {}).get("name") or ""),"used_keys":len(usage),"missing_count":len(missing),"missing":missing[:limit]}
def _key_order():
    try:
        d=_doc_store.read_json(target_profiles.profile_target_values_path(),None)
        if d is None:return {}
    except Exception:
        return {}
    out={}
    if isinstance(d,dict):
        for k,v in d.items():
            p=v.get("priority",0) if isinstance(v,dict) else (v if isinstance(v,int) else 0)
            out[str(k).lower()]=p if isinstance(p,int) else 0
    return out
# The dashboard's live-target picker searches by name and by values (IP, domain...). Values under secret-looking keys
# are never shown as a hint nor made searchable, so credentials stay off the dashboard.
_IDENT_KEY_RX=re.compile(r"ip|host|domain|url|fqdn|dns|addr|cidr|subnet",re.I)
_SECRET_KEY_RX=re.compile(r"pass|secret|token|hash|key|cred|cookie|session|private|otp|pin",re.I)
def _target_search_fields(t,order):
    vals=[(str(k),str(v).strip()) for k,v in (t.get("values") or {}).items() if str(v or "").strip() and not _SECRET_KEY_RX.search(str(k))]
    vals.sort(key=lambda kv:(order.get(kv[0].lower(),65535),kv[0].lower()))
    # The hint should identify the target: address-like values (IP, host, domain, URL) first, then the rest.
    ident=[v for k,v in vals if _IDENT_KEY_RX.search(k)]
    rest=[v for k,v in vals if not _IDENT_KEY_RX.search(k)]
    return {"hint":" · ".join((ident+rest)[:2])[:120],"search":" ".join(v for _k,v in vals)[:600]}
def _live_target(max_values=12):
    targets=_read_targets()
    live=_live_target_record(targets)
    order=_key_order()
    profile=_active_engagement().get("name","Default")
    listing=sorted(({"id":t.get("id") or "","name":str(t.get("name")),"live":t is live,**_target_search_fields(t,order)} for t in targets),key=lambda x:x["name"].lower())[:300]
    if not live:return {"profile":profile,"target":None,"targets":listing}
    vals=[(str(k),str(v).strip()) for k,v in (live.get("values") or {}).items() if str(v or "").strip()]
    vals.sort(key=lambda kv:(order.get(kv[0].lower(),65535),kv[0].lower()))
    st=str(live.get("engagement_status") or "not_started").lower()
    labels=dict(ENGAGEMENT_STATUSES)
    return {"profile":profile,"targets":listing,"target":{"id":live.get("id") or "","name":str(live.get("name")),"engagement_status":st if st in labels else "not_started","engagement_label":labels.get(st,"Not Started"),"values":[{"key":k,"value":v} for k,v in vals[:max_values]],"value_count":len(vals)}}
def _activity_heat(days=30,now=None):
    notes=[];cmds=[];jobs=[]
    now=now if now is not None else time.time()
    since=datetime.fromtimestamp(now-(days+1)*86400,timezone.utc).isoformat()
    with _connect() as con:
        cur=con.cursor()
        cur.execute("SELECT action_at FROM NotesHistory WHERE action IN ('insert','update') AND action_at>=?",(since,))
        notes=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT action_at FROM CommandsNotesHistory WHERE action IN ('insert','update') AND action_at>=?",(since,))
        cmds=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT ran_at FROM CommandRuns WHERE ran_at>=?",(since,))
        cmds+=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT started_at FROM TerminalJobs WHERE started_at>=?",(since,))
        jobs=[_parse_iso_ts(r[0]) for r in cur.fetchall()]
    n=_day_series(notes,days,now);c=_day_series(cmds,days,now);j=_day_series(jobs,days,now)
    today=_local_day(now)
    from datetime import timedelta
    out=[]
    for i in range(days):
        d=today-timedelta(days=days-1-i)
        out.append({"date":d.isoformat(),"label":d.strftime("%a %d %b"),"notes":n[i],"commands":c[i],"jobs":j[i],"total":n[i]+c[i]+j[i]})
    total=sum(x["total"] for x in out)
    return {"days":out,"total":total,"max":max([x["total"] for x in out] or [0]),"active_days":sum(1 for x in out if x["total"])}
def _security_health(now=None):
    from Cores.Services import security_service as _sec,settings_service as _set
    now=now if now is not None else time.time()
    items=[]
    try:
        bcfg=_set._get_backup_settings()
    except Exception:
        bcfg={"auto_enabled":False,"interval_hours":24}
    latest=None
    try:
        rows=_set.Backup().list()
        latest=rows[0][1] if rows else None
    except Exception:
        latest=None
    if latest is None:
        items.append({"id":"backup","label":"Last backup","value":"Never","level":"bad","tab":"backup"})
    else:
        age_h=(now-latest)/3600
        limit_h=max(1,int(bcfg.get("interval_hours") or 24))*2 if bcfg.get("auto_enabled") else 24*7
        items.append({"id":"backup","label":"Last backup","value":_relative_time(latest),"level":"ok" if age_h<=limit_h else "warn","tab":"backup"})
    items.append({"id":"auto_backup","label":"Auto backup","value":(f"Every {int(bcfg.get('interval_hours') or 24)}h" if bcfg.get("auto_enabled") else "Off"),"level":"ok" if bcfg.get("auto_enabled") else "warn","tab":"backup"})
    cfg=_sec.get_security_settings()
    lock_on=bool(cfg.get("app_lock_enabled")) and _sec.pin_is_set(cfg)
    items.append({"id":"app_lock","label":"App lock","value":"On" if lock_on else "Off","level":"ok" if lock_on else "warn","tab":"security"})
    mins=int(cfg.get("auto_lock_minutes") or 0)
    items.append({"id":"auto_lock","label":"Auto-lock","value":f"After {mins} min" if mins else "Off","level":"ok" if mins and lock_on else "info","tab":"security"})
    items.append({"id":"encryption","label":"Database encryption","value":"On" if cfg.get("enc_enabled") else "Off","level":"ok" if cfg.get("enc_enabled") else "info","tab":"security"})
    exp=cfg.get("audit_expiry") or {}
    if exp.get("enabled"):
        amt=int(exp.get("amount") or 0);unit=str(exp.get("unit") or "")
        val=f"{amt} {unit[:-1] if amt==1 and unit.endswith('s') else unit}".strip()
    else:
        val="Kept forever"
    items.append({"id":"audit_expiry","label":"Audit log expiry","value":val,"level":"ok" if exp.get("enabled") else "info","tab":"security"})
    worst="bad" if any(i["level"]=="bad" for i in items) else ("warn" if any(i["level"]=="warn" for i in items) else "ok")
    return {"items":items,"overall":worst}
def _safe(errors,key,fn,default):
    try:
        return fn()
    except Exception as e:
        errors.append(key)
        try:
            import logging
            logging.getLogger("loya.dashboard").warning("dashboard %s failed: %s",key,e)
        except Exception:
            pass
        return default
_REPORTS_EMPTY={"reports":0,"by_status":{"draft":0,"review":0,"final":0},"findings":{"critical":0,"high":0,"medium":0,"low":0,"info":0},"open_by_severity":{"critical":0,"high":0,"medium":0,"low":0,"info":0},"open_findings":0,"recent":[],"next_deadline":None,"overdue":0}
def _reports():
    # Imported here so a broken reporting module costs this one card, not the dashboard.
    from Cores.Services import reports_service
    return reports_service.stats()
def get_stats():
    errors=[]
    counts=_db_counts()
    feed=_safe(errors,"recent_activity",_activity_feed,[])
    recent_notes,pinned_notes=_safe(errors,"notes_lists",_notes_lists,([],[]))
    if "notes_lists" in errors:errors+=["recent_notes","pinned_notes"]
    return {
        "notes_count":counts["notes"],
        "commands_count":counts["commands_standalone"]+counts["commands_linked"],
        "commands_standalone":counts["commands_standalone"],
        "commands_linked":counts["commands_linked"],
        "targets_count":_targets_count(),
        "recycle_bin_count":_recycle_bin_count(),
        "notes_by_group":counts["groups"],
        "backup_status":_backup_status(),
        "storage_usage_bytes":_storage_usage(),
        "app_version":_get_app_version(),
        "time_since_activity":_time_since_activity(),
        "active_engagement":_active_engagement(),
        "recent_activity":_legacy_activity(feed) if feed else _recent_activity(),
        "update_status":_update_status(),
        "terminal_jobs":_terminal_jobs(),
        "kpi":_safe(errors,"kpi",_kpis,{}),
        "activity_feed":feed,
        "recent_jobs":_safe(errors,"recent_jobs",_recent_jobs,{"running":0,"total":0,"items":[]}),
        "engagements":_safe(errors,"engagements",_engagements,{"total":0,"statuses":[]}),
        "live_target":_safe(errors,"live_target",_live_target,{"profile":"","target":None,"targets":[]}),
        "most_used_commands":_safe(errors,"most_used_commands",_most_used_commands,[]),
        "favorite_snippets":_safe(errors,"favorite_snippets",_favorite_snippets,[]),
        "recent_notes":recent_notes,
        "pinned_notes":pinned_notes,
        "missing_placeholders":_safe(errors,"missing_placeholders",_missing_placeholders,{"live":False,"live_id":"","live_name":"","used_keys":0,"missing_count":0,"missing":[]}),
        "activity_heat":_safe(errors,"activity_heat",_activity_heat,{"days":[],"total":0,"max":0,"active_days":0}),
        "security_health":_safe(errors,"security_health",_security_health,{"items":[],"overall":"ok"}),
        "reports":_safe(errors,"reports",_reports,dict(_REPORTS_EMPTY)),
        "errors":errors,
    }
def _fmt_bytes(n):
    units=["B","KB","MB","GB"]
    v=float(n or 0);i=0
    while v>=1024 and i<len(units)-1:
        v/=1024;i+=1
    return f"{v:.1f} {units[i]}" if i>0 else f"{int(v)} {units[i]}"
def _stat_display(widget,stats):
    if widget=="notes_count":return str(stats.get("notes_count",0)),"total notes"
    if widget=="commands_count":return str(stats.get("commands_count",0)),f"{stats.get('commands_standalone',0)} standalone / {stats.get('commands_linked',0)} linked"
    if widget=="targets_count":return str(stats.get("targets_count",0)),"saved targets"
    if widget=="recycle_bin_count":return str(stats.get("recycle_bin_count",0)),"items in recycle bin"
    if widget=="terminal_jobs":
        info=stats.get("terminal_jobs",{}) or {}
        running=int(info.get("running",0))
        detail=f"{info.get('failed',0)} failed of {info.get('total',0)} recorded" if info.get("total") else "no jobs recorded yet"
        return str(running),detail
    if widget=="backup_status":
        b=stats.get("backup_status") or {}
        days=b.get("latest_days_ago")
        val="Never" if days is None else ("Today" if days==0 else f"{days}d ago")
        return val,f"{b.get('count',0)} backups"
    if widget=="storage_usage":return _fmt_bytes(stats.get("storage_usage_bytes",0)),"database size"
    if widget=="app_version":return "v"+str(stats.get("app_version","?")),"installed version"
    if widget=="time_since_activity":
        t=stats.get("time_since_activity") or {}
        return t.get("label","-"),t.get("what","")
    if widget=="active_engagement":
        e=stats.get("active_engagement") or {}
        return e.get("name","Default"),f"{e.get('targets_count',0)} targets"
    if widget=="notes_by_group":
        groups=stats.get("notes_by_group") or {}
        total=sum(groups.values())
        return f"{total} notes",f"across {len(groups)} group(s)"
    if widget=="update_status":
        u=stats.get("update_status") or {}
        return u.get("label","-"),u.get("sub","")
    if widget=="recent_activity":
        items=stats.get("recent_activity") or []
        if not items:return "No recent activity",""
        return items[0].get("label","-"),items[0].get("relative","")
    return "-",""
_STATS_HTML_STYLE="""
body{margin:0;padding:32px;background:#0d1117;color:#e8eef7;font-family:Segoe UI,Arial,sans-serif;line-height:1.6}
.stats-title{font-size:26px;font-weight:700;color:#ffffff;margin:0 0 4px}
.stats-meta{font-size:12px;color:#9fb3c8;margin:0 0 28px}
.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}
.stats-card{background:#141b24;border:1px solid #263446;border-radius:10px;padding:16px 18px}
.stats-card-value{font-size:24px;font-weight:700;color:#ffffff}
.stats-card-label{font-size:11px;color:#9fb3c8;margin-top:2px}
.stats-card-sub{font-size:11px;color:#8ab5ff;margin-top:6px}
.stats-section{background:#141b24;border:1px solid #263446;border-radius:10px;padding:18px 20px;margin-bottom:16px}
.stats-section h2{margin:0 0 12px;font-size:15px;color:#ffffff}
.stat-bar-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12px}
.stat-bar-label{flex:0 0 140px;color:#9fb3c8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat-bar-track{flex:1;height:8px;background:#08111d;border-radius:4px;overflow:hidden}
.stat-bar-fill{height:100%;border-radius:4px}
.stat-bar-value{flex:0 0 32px;text-align:right;color:#e8eef7}
.stats-list-row{display:flex;justify-content:space-between;font-size:12px;padding:6px 0;border-bottom:1px solid #263446}
.stats-list-row:last-child{border-bottom:none}
.stats-list-time{color:#9fb3c8}
"""
_STATS_BAR_PALETTE=["#3b82f6","#8ab5ff","#8cecff","#5eead4","#a78bfa","#f472b6"]
def build_stats_report_html(stats):
    gen=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    backup=stats.get("backup_status") or {}
    days=backup.get("latest_days_ago")
    backup_val="Never" if days is None else ("Today" if days==0 else f"{days}d ago")
    activity=stats.get("time_since_activity") or {}
    engagement=stats.get("active_engagement") or {}
    update=stats.get("update_status") or {}
    cards=[
        ("Notes",str(stats.get("notes_count",0)),"total notes"),
        ("Commands",str(stats.get("commands_count",0)),f"{stats.get('commands_standalone',0)} standalone / {stats.get('commands_linked',0)} linked"),
        ("Targets",str(stats.get("targets_count",0)),"saved targets"),
        ("Recycle Bin",str(stats.get("recycle_bin_count",0)),"items"),
        ("Storage Usage",_fmt_bytes(stats.get("storage_usage_bytes",0)),"database size"),
        ("App Version","v"+str(stats.get("app_version","?")),"installed version"),
        ("Last Backup",backup_val,f"{backup.get('count',0)} backups"),
        ("Last Activity",activity.get("label","-"),activity.get("what","")),
        ("Active Engagement",engagement.get("name","Default"),f"{engagement.get('targets_count',0)} targets"),
        ("Update Status",update.get("label","-"),update.get("sub","")),
    ]
    parts=[f'<!doctype html><html><head><meta charset="utf-8"><title>LOYA NG - Report Statistics</title><style>{_STATS_HTML_STYLE}</style></head><body>']
    parts.append('<div class="stats-title">LOYA NG - Report Statistics</div>')
    parts.append(f'<div class="stats-meta">Generated {gen}</div>')
    parts.append('<div class="stats-grid">')
    for label,value,sub in cards:
        parts.append(f'<div class="stats-card"><div class="stats-card-value">{html.escape(str(value))}</div><div class="stats-card-label">{html.escape(label)}</div><div class="stats-card-sub">{html.escape(str(sub))}</div></div>')
    parts.append('</div>')
    groups=stats.get("notes_by_group") or {}
    if groups:
        total=sum(groups.values()) or 1
        parts.append('<div class="stats-section"><h2>Notes by Group</h2>')
        for i,(name,count) in enumerate(sorted(groups.items(),key=lambda x:x[1],reverse=True)):
            pct=round(100*count/total)
            color=_STATS_BAR_PALETTE[i%len(_STATS_BAR_PALETTE)]
            parts.append(f'<div class="stat-bar-row"><span class="stat-bar-label">{html.escape(name)}</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width:{pct}%;background:{color}"></div></div><span class="stat-bar-value">{count}</span></div>')
        parts.append('</div>')
    recent=stats.get("recent_activity") or []
    if recent:
        parts.append('<div class="stats-section"><h2>Recent Activity</h2>')
        for item in recent:
            parts.append(f'<div class="stats-list-row"><span>{html.escape(item.get("label","-"))}</span><span class="stats-list-time">{html.escape(item.get("relative",""))}</span></div>')
        parts.append('</div>')
    parts.append('</body></html>')
    return "".join(parts)
def build_stats_report_pdf(out_path,stats):
    from fpdf import FPDF
    pdf=FPDF(format="A4")
    pdf.set_auto_page_break(True,margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica","B",20)
    pdf.multi_cell(0,10,"LOYA NG - Report Statistics",new_x="LMARGIN",new_y="NEXT")
    pdf.set_font("Helvetica","",9)
    pdf.set_text_color(120,120,120)
    pdf.cell(0,6,f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",new_x="LMARGIN",new_y="NEXT")
    pdf.set_text_color(0,0,0)
    pdf.ln(4)
    backup=stats.get("backup_status") or {}
    days=backup.get("latest_days_ago")
    backup_val="Never" if days is None else ("Today" if days==0 else f"{days}d ago")
    cards=[
        ("Notes",str(stats.get("notes_count",0))),
        ("Commands",str(stats.get("commands_count",0))),
        ("Targets",str(stats.get("targets_count",0))),
        ("Recycle Bin",str(stats.get("recycle_bin_count",0))),
        ("Storage",_fmt_bytes(stats.get("storage_usage_bytes",0))),
        ("Version","v"+str(stats.get("app_version","?"))),
        ("Last Backup",backup_val),
        ("Backups",str(backup.get("count",0))),
        ("Recycle Bin Items",str(stats.get("recycle_bin_count",0))),
    ]
    col_w=(pdf.w-pdf.l_margin-pdf.r_margin)/3
    pdf.set_draw_color(200,200,200)
    for i in range(0,len(cards),3):
        row=cards[i:i+3]
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica","B",15)
        for label,value in row:
            pdf.cell(col_w-4,10,value,border=1,align="C")
        pdf.ln(10)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica","",8)
        pdf.set_text_color(110,110,110)
        for label,value in row:
            pdf.cell(col_w-4,6,label,align="C")
        pdf.set_text_color(0,0,0)
        pdf.ln(10)
    pdf.ln(2)
    groups=stats.get("notes_by_group") or {}
    if groups:
        pdf.set_font("Helvetica","B",13)
        pdf.multi_cell(0,8,"Notes by Group",new_x="LMARGIN",new_y="NEXT")
        pdf.ln(1)
        total=sum(groups.values()) or 1
        label_w=45
        value_w=15
        bar_max=pdf.w-pdf.l_margin-pdf.r_margin-label_w-value_w-4
        for i,(name,count) in enumerate(sorted(groups.items(),key=lambda x:x[1],reverse=True)):
            pdf.set_font("Helvetica","",10)
            y=pdf.get_y()
            pdf.set_x(pdf.l_margin)
            pdf.cell(label_w,6,name[:26])
            bar_w=max(2,round(bar_max*count/total))
            r,g,b=tuple(int(_STATS_BAR_PALETTE[i%len(_STATS_BAR_PALETTE)].lstrip("#")[j:j+2],16) for j in (0,2,4))
            pdf.set_fill_color(r,g,b)
            pdf.rect(pdf.get_x(),y+1,bar_w,4,style="F")
            pdf.set_xy(pdf.l_margin+label_w+bar_max+4,y)
            pdf.cell(value_w,6,str(count))
            pdf.ln(7)
        pdf.ln(3)
    recent=stats.get("recent_activity") or []
    if recent:
        pdf.set_font("Helvetica","B",13)
        pdf.multi_cell(0,8,"Recent Activity",new_x="LMARGIN",new_y="NEXT")
        pdf.set_font("Helvetica","",10)
        for item in recent:
            pdf.multi_cell(0,6,f"{item.get('label','-')}  -  {item.get('relative','')}",new_x="LMARGIN",new_y="NEXT")
    pdf.output(out_path)
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def _read_settings():
    try:
        with open(_settings_path(),"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _write_settings(d):
    p=_settings_path()
    os.makedirs(os.path.dirname(p),exist_ok=True)
    tmp=p+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:json.dump(d,f,ensure_ascii=False,indent=2)
    os.replace(tmp,p)
def _validate_cards(cards):
    if not isinstance(cards,list):raise ValueError("cards must be a list")
    widget_ids={w["id"] for w in WIDGET_CATALOG}
    clean=[]
    for c in cards:
        if not isinstance(c,dict):raise ValueError("each card must be an object")
        cid=str(c.get("id") or "").strip()
        widget=str(c.get("widget") or "").strip()
        size=str(c.get("size") or "").strip()
        if not cid or widget not in widget_ids or size not in SIZE_PRESETS:raise ValueError(f"invalid card entry: {c}")
        clean.append({"id":cid,"widget":widget,"size":size})
    return clean
def _catalog_ids():return {w["id"] for w in WIDGET_CATALOG}
def _clean_loaded(cards):
    """Drop retired/unknown widgets and malformed entries from a stored layout (read side only, the file is left alone)."""
    ids=_catalog_ids()
    out=[]
    for c in cards if isinstance(cards,list) else []:
        if not isinstance(c,dict):continue
        if str(c.get("widget") or "") not in ids:continue
        size=str(c.get("size") or "")
        out.append({"id":str(c.get("id") or c.get("widget")),"widget":str(c.get("widget")),"size":size if size in SIZE_PRESETS else "1x1"})
    return out
def get_layout():
    d=_read_settings()
    dash=d.get("dashboard",{}) if isinstance(d.get("dashboard"),dict) else {}
    cards=dash.get("cards")
    if isinstance(cards,list) and cards:return _clean_loaded(cards)
    return [dict(c) for c in DEFAULT_LAYOUT]
def list_presets():
    return [{"id":p["id"],"name":p["name"],"description":p["description"],"count":len(p["cards"])} for p in PRESETS]
def apply_preset(preset_id):
    p=next((x for x in PRESETS if x["id"]==preset_id),None)
    if p is None:raise ValueError("Preset not found.")
    return save_layout([dict(c) for c in p["cards"]])
def save_layout(cards):
    clean=_validate_cards(cards)
    with _settings_lock:
        d=_read_settings()
        d["dashboard"]={"cards":clean}
        _write_settings(d)
    return clean
def list_layouts():
    d=_read_settings()
    layouts=d.get("dashboard_layouts",{})
    return sorted(layouts.keys()) if isinstance(layouts,dict) else []
def save_layout_as(name):
    name=(name or "").strip()
    if not name:raise ValueError("Layout name is required.")
    with _settings_lock:
        d=_read_settings()
        dash=d.get("dashboard",{}) if isinstance(d.get("dashboard"),dict) else {}
        cards=_clean_loaded(dash.get("cards")) or [dict(c) for c in DEFAULT_LAYOUT]
        layouts=d.get("dashboard_layouts",{})
        if not isinstance(layouts,dict):layouts={}
        layouts[name]=[dict(c) for c in cards]
        d["dashboard_layouts"]=layouts
        _write_settings(d)
    return sorted(layouts.keys())
def apply_layout(name):
    with _settings_lock:
        d=_read_settings()
        layouts=d.get("dashboard_layouts",{}) if isinstance(d.get("dashboard_layouts"),dict) else {}
        cards=layouts.get(name)
        if cards is None:raise ValueError("Layout not found.")
        clean=_clean_loaded(cards)
        d["dashboard"]={"cards":clean}
        _write_settings(d)
    return clean
def delete_layout(name):
    with _settings_lock:
        d=_read_settings()
        layouts=d.get("dashboard_layouts",{}) if isinstance(d.get("dashboard_layouts"),dict) else {}
        layouts.pop(name,None)
        d["dashboard_layouts"]=layouts
        _write_settings(d)
    return sorted(layouts.keys())
def restore_default():
    clean=[dict(c) for c in DEFAULT_LAYOUT]
    with _settings_lock:
        d=_read_settings()
        d["dashboard"]={"cards":clean}
        _write_settings(d)
    return clean
