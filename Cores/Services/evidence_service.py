"""Evidence store for Reporting: saved command output, pasted text, screenshots and terminal session recordings.
Everything lives in the SQLite DB (ReportEvidence, ReportEvidenceEvents, ReportAssets) so the at-rest encryption covers it."""
import base64,hashlib,json,os,re,threading,uuid
from datetime import datetime,timezone
from Cores import common_db
from Cores import db_driver as _db_driver
from Cores import recycle_bin as _recycle_bin
from Cores import target_profiles as _target_profiles
from Cores import doc_store as _doc_store
KINDS=("command","recording","text","image")
EVENT_KINDS=("cmd","out","exit","mark")
RECYCLE_TYPE="report_evidence"
MAX_CONTENT=2*1024*1024
MAX_RECORDING=8*1024*1024
MAX_IMAGE_BYTES=10*1024*1024
MAX_EVENT_COMMAND=8192
TRUNCATED_MARK="[truncated]"
RECORDING_LIMIT_MARK="Recording size limit reached - further output was not stored."
PREVIEW_CHARS=300
_LIST_LIMIT=2000
_CARRY_MAX=64*1024
_KEY_HOLD_MAX=64*1024
_COLS="id,uid,kind,title,source,session_id,profile_id,target,command,exit_code,cwd,started_at,ended_at,content,meta,created_at"
# A recording belongs to the process that started it: after an app restart the token differs and the row is closed on the next list.
_BOOT=uuid.uuid4().hex
_rec_lock=threading.RLock()
_streams={}
_KEY_BEGIN_RE=re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEY_END_RE=re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_ANSI_FALLBACK_RE=re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[PX^_][\s\S]*?\x1b\\|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()*+][0-9A-Za-z]|\x1b[=>NOM78c]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
def _terminal():
    from Cores.Services import terminal_service
    return terminal_service
def _now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _norm(v):return str(v if v is not None else "").strip()
def _iso(value,default=""):
    """ISO-8601 UTC text from an ISO string or a JS epoch in milliseconds; `default` when it cannot be read."""
    if value is None or value=="" or isinstance(value,bool):return default
    try:
        if isinstance(value,(int,float)):
            return datetime.fromtimestamp(float(value)/1000.0,timezone.utc).isoformat(timespec="seconds")
        text=_norm(value)
        if re.fullmatch(r"\d{11,}(?:\.\d+)?",text):
            return datetime.fromtimestamp(float(text)/1000.0,timezone.utc).isoformat(timespec="seconds")
        parsed=datetime.fromisoformat(text.replace("Z","+00:00"))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return default
def _con():
    con=common_db.connect(common_db.db_path(),timeout=10)
    common_db.ensure_schema(con)
    return con
def _meta(text):
    try:
        data=json.loads(text or "{}")
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def redact_enabled():
    """The reports default `redact_evidence` (settings.json key "reports"); on unless it was switched off."""
    try:
        from Cores.Services import reports_service as _reports
        value=_reports.defaults_get().get("redact_evidence",True)
        return bool(value)
    except Exception:pass
    try:
        with open(_settings_path(),"r",encoding="utf-8") as handle:data=json.load(handle)
        reports=data.get("reports",{}) if isinstance(data,dict) else {}
        if isinstance(reports,dict) and "redact_evidence" in reports:return bool(reports.get("redact_evidence"))
    except Exception:pass
    return True
def strip_ansi(text):
    """Plain text: escape sequences and control bytes removed, CRLF folded, and carriage-return redraws collapsed to the last state of each line."""
    if not text:return ""
    try:pattern=_terminal()._ANSI_STRIP_RE
    except Exception:pattern=_ANSI_FALLBACK_RE
    plain=pattern.sub("",str(text).replace("\r\n","\n"))
    if "\r" in plain:plain="\n".join(line[line.rfind("\r")+1:] if "\r" in line else line for line in plain.split("\n"))
    return plain
def redact(text):
    """(text,count) with secrets replaced by terminal_service's redactor."""
    if not text:return "",0
    safe,found=_terminal().redact_secrets(text)
    return safe,sum(int(item.get("count",0) or 0) for item in found)
def _size_text(count):
    return str(count//(1024*1024))+" MB" if count>=1024*1024 else str(max(1,count//1024))+" KB"
def cap_text(text,limit=MAX_CONTENT):
    """(text,truncated): at most `limit` characters, cut on a line where one is near, with a clear marker line."""
    body=str(text or "")
    if len(body)<=limit:return body,False
    head=body[:limit]
    cut=head.rfind("\n")
    if cut>=0 and cut>limit-4096:head=head[:cut]
    dropped=len(body)-len(head)
    return head+"\n"+TRUNCATED_MARK+" "+str(dropped)+" more characters were not stored (the limit is "+_size_text(limit)+" per evidence item).\n",True
def _clean_capture(text,do_redact):
    plain=strip_ansi(text)
    count=0
    if do_redact:plain,count=redact(plain)
    plain,truncated=cap_text(plain)
    return plain,count,truncated
def _strip_echo(output,command):
    """Drop the shell's echo of the command (prompt + command) when it is the first line of the captured output."""
    cmd=_norm(command)
    if not cmd or not output:return output
    lines=output.split("\n")
    for index,line in enumerate(lines[:3]):
        if not line.strip():continue
        if line.rstrip().endswith(cmd):return "\n".join(lines[index+1:])
        break
    return output
_PROMPT_BOX_RE=re.compile(r"^[\u250c\u256d\u250f][\u2500\u2501]*[\(\[].*$")
_PROMPT_TAIL_RE=re.compile(r"^(?:[\u2514\u2570\u2517][\u2500\u2501]*.{0,40}[$#%>]|\S+@\S+[: ]\S*[$#%]|PS [A-Za-z]:\\.*>|[A-Za-z]:\\[^>\n]*>)\s?$")
def _strip_prompt_tail(output):
    """Drop the next shell prompt a terminal capture ends with (an unfinished last line shaped like a prompt, and the box line some
    two-line prompts print above it), plus blank lines around the output. Anything else is left alone."""
    if not output:return output
    lines=output.split("\n")
    if lines[-1] and _PROMPT_TAIL_RE.match(lines[-1]):lines[-1]=""
    while lines and not lines[-1].strip():lines.pop()
    if lines and _PROMPT_BOX_RE.match(lines[-1]):
        lines.pop()
        while lines and not lines[-1].strip():lines.pop()
    while lines and not lines[0].strip():lines.pop(0)
    return "\n".join(lines)+"\n" if lines else ""
def live_target_name(profile_id=None):
    try:
        path=_target_profiles.profile_targets_json_path(profile_id or None)
        targets=_doc_store.read_json(path,None)
        if targets is None:return ""
        for target in targets if isinstance(targets,list) else []:
            if isinstance(target,dict) and _norm(target.get("status","")).lower()=="live":return _norm(target.get("name",""))
    except Exception:pass
    return ""
def _stamp():
    try:profile_id=_norm(_target_profiles.active_profile_id())
    except Exception:profile_id=""
    return profile_id,live_target_name(profile_id)
def _row(row,full=True):
    data=dict(zip(_COLS.split(","),row))
    data["meta"]=_meta(data.get("meta"))
    for key in ("title","source","session_id","profile_id","target","command","cwd","started_at","ended_at"):data[key]=data.get(key) or ""
    data["content"]=data.get("content") or ""
    if not full:
        data["preview"]=data.pop("content")
        data["size"]=int(row[len(_COLS.split(","))] or 0)
        data["event_count"]=int(row[len(_COLS.split(","))+1] or 0)
        if data["kind"]=="recording" and data["meta"].get("state")=="recording":data["size"]=int(data["meta"].get("bytes",0) or 0)
    return data
def _find(cur,ident):
    text=_norm(ident)
    if not text:return None
    if isinstance(ident,int) or text.isdigit():cur.execute("SELECT "+_COLS+" FROM ReportEvidence WHERE id=?",(int(text),))
    else:cur.execute("SELECT "+_COLS+" FROM ReportEvidence WHERE uid=?",(text,))
    return cur.fetchone()
def _events(cur,evidence_id):
    cur.execute("SELECT seq,ts,kind,data FROM ReportEvidenceEvents WHERE evidence_id=? ORDER BY seq",(int(evidence_id),))
    return [{"seq":int(r[0]),"ts":r[1] or "","kind":r[2] or "","data":r[3] or ""} for r in cur.fetchall()]
def _insert(cur,kind,title,source,session_id,command,exit_code,cwd,started_at,ended_at,content,meta):
    profile_id,target=_stamp()
    uid=uuid.uuid4().hex
    cur.execute("INSERT INTO ReportEvidence(uid,kind,title,source,session_id,profile_id,target,command,exit_code,cwd,started_at,ended_at,content,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(uid,kind,_norm(title)[:300],_norm(source)[:40],_norm(session_id)[:80],profile_id,target,command or "",exit_code,_norm(cwd)[:1000],started_at or "",ended_at or "",content or "",json.dumps(meta or {},ensure_ascii=False),_now()))
    return int(cur.lastrowid)
def _exit_code(value):
    if value is None or value=="" or isinstance(value,bool):return None
    try:return int(value)
    except Exception:return None
def _tags(value):
    if isinstance(value,str):value=value.split(",")
    out=[]
    for tag in value if isinstance(value,(list,tuple)) else []:
        tag=_norm(tag)[:40]
        if tag and tag not in out:out.append(tag)
    return out[:20]
def get(ident,con=None):
    own=con is None
    con=con or _con()
    try:
        cur=con.cursor()
        row=_find(cur,ident)
        if not row:raise ValueError("Evidence not found.")
        data=_row(row)
        if data["kind"]=="recording":
            data["events"]=_events(cur,data["id"])
            if data["meta"].get("state")=="recording":data["content"]=render_transcript(data,data["events"])
        return data
    finally:
        if own:con.close()
def save_job(info):
    info=info if isinstance(info,dict) else {}
    command=str(info.get("command") or "").strip()
    output=str(info.get("output") or "")
    if not command and not output.strip():raise ValueError("There is no command or output to save.")
    do_redact=redact_enabled()
    content,count,truncated=_clean_capture(_strip_prompt_tail(_strip_echo(strip_ansi(output),command)),do_redact)
    if do_redact and command:
        command,cmd_count=redact(command)
        count+=cmd_count
    job_key=_norm(info.get("job_key"))[:64]
    session_id=_norm(info.get("session_id"))[:80]
    meta={"redacted":count,"job_key":job_key,"shell":_norm(info.get("shell"))[:40],"notes":"","tags":[]}
    label=_norm(info.get("session_label"))[:120]
    if label:meta["session_label"]=label
    if truncated:meta["truncated"]=True
    title=_norm(info.get("title")) or (command.splitlines()[0][:200] if command else "Terminal output")
    started=_iso(info.get("started_at"));ended=_iso(info.get("ended_at"))
    con=_con()
    try:
        cur=con.cursor()
        existing=None
        if job_key:
            cur.execute("SELECT id,meta FROM ReportEvidence WHERE kind='command' AND session_id=? AND meta LIKE ?",(session_id,'%"job_key": "'+job_key+'"%'))
            for row in cur.fetchall():
                if _meta(row[1]).get("job_key")==job_key:existing=row;break
        if existing:
            # Saving the same job again (it was still running the first time) refreshes the capture instead of adding a duplicate.
            old=_meta(existing[1])
            meta["notes"]=old.get("notes","");meta["tags"]=old.get("tags",[])
            cur.execute("UPDATE ReportEvidence SET command=?,exit_code=?,cwd=?,started_at=?,ended_at=?,content=?,meta=? WHERE id=?",(command,_exit_code(info.get("exit_code")),_norm(info.get("cwd"))[:1000],started,ended,content,json.dumps(meta,ensure_ascii=False),int(existing[0])))
            evidence_id=int(existing[0])
        else:
            evidence_id=_insert(cur,"command",title,_norm(info.get("source")) or "terminal",session_id,command,_exit_code(info.get("exit_code")),info.get("cwd"),started,ended,content,meta)
        con.commit()
        return get(evidence_id,con)
    finally:
        con.close()
def save_text(info):
    info=info if isinstance(info,dict) else {}
    body=str(info.get("content") or "")
    command=str(info.get("command") or "").strip()
    if not body.strip():raise ValueError("The evidence text is empty.")
    do_redact=redact_enabled()
    content,count,truncated=_clean_capture(body,do_redact)
    if do_redact and command:
        command,cmd_count=redact(command)
        count+=cmd_count
    meta={"redacted":count,"notes":_norm(info.get("notes"))[:4000],"tags":_tags(info.get("tags"))}
    if truncated:meta["truncated"]=True
    title=_norm(info.get("title")) or (command[:200] if command else (content.strip().splitlines() or ["Text evidence"])[0][:120])
    con=_con()
    try:
        cur=con.cursor()
        evidence_id=_insert(cur,"command" if command else "text",title,_norm(info.get("source")) or "manual","",command,_exit_code(info.get("exit_code")),"",_iso(info.get("started_at")),"",content,meta)
        con.commit()
        return get(evidence_id,con)
    finally:
        con.close()
_IMAGE_MAGIC=((b"\x89PNG\r\n\x1a\n","image/png"),(b"\xff\xd8\xff","image/jpeg"),(b"GIF87a","image/gif"),(b"GIF89a","image/gif"))
def image_mime(raw):
    for magic,mime in _IMAGE_MAGIC:
        if raw.startswith(magic):return mime
    if raw[:4]==b"RIFF" and raw[8:12]==b"WEBP":return "image/webp"
    return ""
def _decode_image(data_b64):
    text=str(data_b64 or "").strip()
    if text.startswith("data:"):
        head,_sep,text=text.partition(",")
        if ";base64" not in head:raise ValueError("The image data is not base64 encoded.")
    try:raw=base64.b64decode(text,validate=False)
    except Exception:raise ValueError("The image data could not be decoded.")
    if not raw:raise ValueError("The image is empty.")
    if len(raw)>MAX_IMAGE_BYTES:raise ValueError("The image is larger than 10 MB.")
    if not image_mime(raw):raise ValueError("Only PNG, JPEG, GIF and WebP images can be saved as evidence.")
    return raw
def _image_size(raw):
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:return int(image.width),int(image.height)
    except Exception:
        return 0,0
def _store_asset(name,raw):
    """The asset record for an image: through reports_service when it is there, otherwise straight into ReportAssets (same shape, dedupe by sha256)."""
    try:
        from Cores.Services import reports_service as _reports
        asset=_reports.add_asset(name,raw)
        if isinstance(asset,dict) and asset.get("uid"):return asset
    except (ImportError,AttributeError):pass
    digest=hashlib.sha256(raw).hexdigest()
    con=_con()
    try:
        cur=con.cursor()
        cur.execute("SELECT uid,mime,name,width,height FROM ReportAssets WHERE sha256=?",(digest,))
        row=cur.fetchone()
        if row:return {"uid":row[0],"mime":row[1],"name":row[2] or "","width":int(row[3] or 0),"height":int(row[4] or 0)}
        uid=uuid.uuid4().hex
        width,height=_image_size(raw)
        mime=image_mime(raw)
        cur.execute("INSERT INTO ReportAssets(uid,name,mime,data,width,height,sha256,created_at) VALUES(?,?,?,?,?,?,?,?)",(uid,_norm(name)[:200],mime,_db_driver.Binary(raw),width,height,digest,_now()))
        con.commit()
        return {"uid":uid,"mime":mime,"name":_norm(name)[:200],"width":width,"height":height}
    finally:
        con.close()
def save_image(name,data_b64,title=""):
    raw=_decode_image(data_b64)
    clean_name=os.path.basename(_norm(name).replace("\\","/"))[:200] or "screenshot"
    asset=_store_asset(clean_name,raw)
    meta={"redacted":0,"asset_uid":asset["uid"],"mime":asset.get("mime",""),"width":int(asset.get("width",0) or 0),"height":int(asset.get("height",0) or 0),"file_name":clean_name,"bytes":len(raw),"notes":"","tags":[]}
    con=_con()
    try:
        cur=con.cursor()
        evidence_id=_insert(cur,"image",_norm(title) or clean_name,"manual","","",None,"","","","",meta)
        con.commit()
        return get(evidence_id,con)
    finally:
        con.close()
def asset_data_url(ident):
    """data: URL of an image evidence item's asset (for previews), or "" when it has none."""
    item=get(ident)
    uid=_norm(item["meta"].get("asset_uid"))
    if not uid:return ""
    con=_con()
    try:
        row=con.execute("SELECT mime,data FROM ReportAssets WHERE uid=?",(uid,)).fetchone()
    finally:
        con.close()
    if not row or not row[1]:return ""
    return "data:"+str(row[0])+";base64,"+base64.b64encode(bytes(row[1])).decode("ascii")
def list_evidence(flt=None):
    flt=flt if isinstance(flt,dict) else {}
    sweep_recordings()
    where=[];args=[]
    kinds=flt.get("kinds") if isinstance(flt.get("kinds"),(list,tuple)) else ([flt.get("kind")] if flt.get("kind") else [])
    kinds=[k for k in (_norm(k) for k in kinds) if k in KINDS]
    if kinds:
        where.append("kind IN ("+",".join("?"*len(kinds))+")");args+=kinds
    for key in ("profile_id","session_id"):
        value=_norm(flt.get(key))
        if value:
            where.append(key+"=?");args.append(value)
    query=_norm(flt.get("query"))
    if query:
        like="%"+query.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
        where.append("(title LIKE ? ESCAPE '\\' OR command LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR meta LIKE ? ESCAPE '\\')");args+=[like]*5
    try:limit=max(1,min(_LIST_LIMIT,int(flt.get("limit") or 500)))
    except Exception:limit=500
    cols=_COLS.replace(",content,",",substr(content,1,"+str(PREVIEW_CHARS)+"),")
    sql="SELECT "+cols+",length(content),(SELECT COUNT(*) FROM ReportEvidenceEvents e WHERE e.evidence_id=ReportEvidence.id) FROM ReportEvidence"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY created_at DESC,id DESC LIMIT ?"
    con=_con()
    try:
        return [_row(row,False) for row in con.execute(sql,args+[limit]).fetchall()]
    finally:
        con.close()
def update(ident,patch):
    patch=patch if isinstance(patch,dict) else {}
    con=_con()
    try:
        cur=con.cursor()
        row=_find(cur,ident)
        if not row:raise ValueError("Evidence not found.")
        data=_row(row)
        title=data["title"]
        if "title" in patch:
            title=_norm(patch.get("title"))[:300]
            if not title:raise ValueError("The evidence title cannot be empty.")
        meta=data["meta"]
        if "notes" in patch:meta["notes"]=str(patch.get("notes") or "")[:4000]
        if "tags" in patch:meta["tags"]=_tags(patch.get("tags"))
        cur.execute("UPDATE ReportEvidence SET title=?,meta=? WHERE id=?",(title,json.dumps(meta,ensure_ascii=False),data["id"]))
        con.commit()
        return get(data["id"],con)
    finally:
        con.close()
def delete(ident):
    """Move one evidence item (and a recording's events) to the Recycle Bin."""
    with _rec_lock:
        con=_con()
        try:
            cur=con.cursor()
            row=_find(cur,ident)
            if not row:raise ValueError("Evidence not found.")
            data=_row(row)
            events=_events(cur,data["id"]) if data["kind"]=="recording" else []
            if data["kind"]=="recording" and data["meta"].get("state")=="recording":
                data["meta"]["state"]="stopped";data["meta"]["stopped_reason"]="deleted"
                data["ended_at"]=data["ended_at"] or _now()
                data["content"]=render_transcript(data,events)
            _streams.pop(data["id"],None)
            payload={"evidence":{key:data[key] for key in _COLS.split(",") if key!="id"},"events":events}
            _recycle_bin.put_entry_cur(cur,RECYCLE_TYPE,data["title"] or data["command"] or "Evidence",payload,source=data["kind"],entity_key=data["uid"])
            cur.execute("DELETE FROM ReportEvidenceEvents WHERE evidence_id=?",(data["id"],))
            cur.execute("DELETE FROM ReportEvidence WHERE id=?",(data["id"],))
            con.commit()
            return True
        finally:
            con.close()
def delete_many(idents):
    done=0
    for ident in idents if isinstance(idents,(list,tuple)) else []:
        try:
            if delete(ident):done+=1
        except ValueError:pass
    return done
def restore_entry(payload,cur=None):
    """Recycle Bin restore for entity type "report_evidence". With `cur` the rows join the caller's transaction; returns the new row id."""
    data=payload.get("evidence") if isinstance(payload,dict) else None
    if not isinstance(data,dict) or _norm(data.get("kind")) not in KINDS:raise ValueError("Recycle Bin evidence payload is invalid.")
    events=payload.get("events") if isinstance(payload.get("events"),list) else []
    own=None
    if cur is None:
        own=_con();cur=own.cursor()
    try:
        uid=_norm(data.get("uid")) or uuid.uuid4().hex
        cur.execute("SELECT 1 FROM ReportEvidence WHERE uid=?",(uid,))
        if cur.fetchone():raise ValueError("This evidence item already exists.")
        meta=data.get("meta") if isinstance(data.get("meta"),dict) else {}
        if meta.get("state")=="recording":meta["state"]="stopped"
        cur.execute("INSERT INTO ReportEvidence(uid,kind,title,source,session_id,profile_id,target,command,exit_code,cwd,started_at,ended_at,content,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(uid,_norm(data.get("kind")),_norm(data.get("title")),_norm(data.get("source")),_norm(data.get("session_id")),_norm(data.get("profile_id")),_norm(data.get("target")),str(data.get("command") or ""),_exit_code(data.get("exit_code")),_norm(data.get("cwd")),_norm(data.get("started_at")),_norm(data.get("ended_at")),str(data.get("content") or ""),json.dumps(meta,ensure_ascii=False),_norm(data.get("created_at")) or _now()))
        evidence_id=int(cur.lastrowid)
        seq=0
        for event in events:
            if not isinstance(event,dict) or event.get("kind") not in EVENT_KINDS:continue
            seq+=1
            cur.execute("INSERT INTO ReportEvidenceEvents(evidence_id,seq,ts,kind,data) VALUES(?,?,?,?,?)",(evidence_id,seq,_norm(event.get("ts")) or _now(),event.get("kind"),str(event.get("data") or "")))
        if own:own.commit()
        return evidence_id
    finally:
        if own:own.close()
class _RedactStream:
    """Cleans and redacts recorded output line by line, so a secret cut in half by a chunk boundary is still seen whole.
    An unfinished private key block is held back until its END line arrives (or dropped when it never does)."""
    def __init__(self,do_redact):
        self.do_redact=bool(do_redact)
        self.carry=""
        self.in_key=False
    def _finish(self,text):
        plain=strip_ansi(text)
        if not self.do_redact:return plain,0
        return redact(plain)
    def feed(self,text):
        buf=self.carry+str(text or "")
        self.carry=""
        count=0
        if self.in_key:
            end=_KEY_END_RE.search(buf)
            if not end:
                # Keep only a tail long enough to still recognise an END line that arrives in two pieces.
                self.carry=buf[-64:]
                return "",0
            self.in_key=False
            buf=buf[end.end():]
        cut=buf.rfind("\n")
        if cut<0:
            if len(buf)<=_CARRY_MAX:
                self.carry=buf
                return "",0
            cut=len(buf)-1
        ready,rest=buf[:cut+1],buf[cut+1:]
        if self.do_redact:
            begin=None
            for match in _KEY_BEGIN_RE.finditer(ready):
                if not _KEY_END_RE.search(ready,match.end()):
                    begin=match.start();break
            if begin is not None:
                held=ready[begin:]
                ready=ready[:begin]
                if len(held)+len(rest)<=_KEY_HOLD_MAX:rest=held+rest
                else:
                    ready+="[redacted private key]\n";count+=1
                    self.in_key=True
                    rest=(held+rest)[-64:]
        out,found=self._finish(ready)
        self.carry=rest
        return out,count+found
    def flush(self):
        buf,self.carry=self.carry,""
        if self.in_key:
            self.in_key=False
            return "",0
        if not buf:return "",0
        if self.do_redact and _KEY_BEGIN_RE.search(buf) and not _KEY_END_RE.search(buf):
            begin=_KEY_BEGIN_RE.search(buf).start()
            out,found=self._finish(buf[:begin])
            return out+"[redacted private key]\n",found+1
        return self._finish(buf)
def _session_alive(session_id):
    try:return bool(session_id) and bool(_terminal().session_alive(session_id))
    except Exception:return False
def recording_start(info):
    info=info if isinstance(info,dict) else {}
    session_id=_norm(info.get("session_id"))[:80]
    if not session_id:raise ValueError("A terminal session is required to start a recording.")
    with _rec_lock:
        sweep_recordings()
        con=_con()
        try:
            cur=con.cursor()
            cur.execute("SELECT id,meta FROM ReportEvidence WHERE kind='recording' AND session_id=? ORDER BY id DESC",(session_id,))
            for row in cur.fetchall():
                if _meta(row[1]).get("state")=="recording":return get(int(row[0]),con)
            label=_norm(info.get("label"))[:120]
            started=_now()
            title=_norm(info.get("title")) or ("Session recording - "+(label or "terminal")+" - "+started[:16].replace("T"," ")+" UTC")
            meta={"redacted":0,"state":"recording","shell":_norm(info.get("shell"))[:40],"session_label":label,"bytes":0,"boot":_BOOT,"live_session":_session_alive(session_id),"redact":redact_enabled(),"notes":"","tags":[]}
            evidence_id=_insert(cur,"recording",title,"terminal",session_id,"",None,info.get("cwd"),started,"","",meta)
            con.commit()
            _streams[evidence_id]=_RedactStream(meta["redact"])
            return get(evidence_id,con)
        finally:
            con.close()
def _next_seq(cur,evidence_id):
    cur.execute("SELECT COALESCE(MAX(seq),0) FROM ReportEvidenceEvents WHERE evidence_id=?",(evidence_id,))
    return int(cur.fetchone()[0] or 0)+1
def _exit_data(data):
    """An exit event's data as compact JSON {code,duration,cwd}; accepts a dict, JSON text or a bare exit code."""
    value=data
    if isinstance(value,str):
        try:value=json.loads(value)
        except Exception:value={"code":value}
    if not isinstance(value,dict):value={"code":value}
    out={"code":_exit_code(value.get("code"))}
    try:
        if value.get("duration") is not None:out["duration"]=round(max(0.0,float(value.get("duration"))),1)
    except Exception:pass
    if _norm(value.get("cwd")):out["cwd"]=_norm(value.get("cwd"))[:1000]
    return json.dumps(out,ensure_ascii=False)
def recording_append(ident,events):
    events=events if isinstance(events,list) else []
    with _rec_lock:
        con=_con()
        try:
            cur=con.cursor()
            row=_find(cur,ident)
            if not row:raise ValueError("Evidence not found.")
            data=_row(row)
            meta=data["meta"]
            if data["kind"]!="recording" or meta.get("state")!="recording":raise ValueError("This recording is not active.")
            evidence_id=data["id"]
            stream=_streams.get(evidence_id)
            if stream is None:stream=_streams[evidence_id]=_RedactStream(meta.get("redact",True))
            seq=_next_seq(cur,evidence_id)-1
            size=int(meta.get("bytes",0) or 0)
            redacted=int(meta.get("redacted",0) or 0)
            capped=bool(meta.get("capped"))
            def add(ts,kind,text):
                nonlocal seq,size
                seq+=1
                size+=len(text)
                cur.execute("INSERT INTO ReportEvidenceEvents(evidence_id,seq,ts,kind,data) VALUES(?,?,?,?,?)",(evidence_id,seq,ts,kind,text))
            def add_out(ts,text):
                nonlocal capped
                if not text or capped:return
                room=MAX_RECORDING-size
                if len(text)>room:
                    if room>0:add(ts,"out",text[:room])
                    add(ts,"mark",RECORDING_LIMIT_MARK)
                    capped=True
                    return
                add(ts,"out",text)
            for event in events:
                if not isinstance(event,dict):continue
                kind=_norm(event.get("kind"))
                if kind not in EVENT_KINDS:continue
                ts=_iso(event.get("ts"),_now())
                raw=event.get("data")
                if kind=="out":
                    text,found=stream.feed(str(raw or ""))
                    redacted+=found
                    add_out(ts,text)
                    continue
                # A command, exit or marker ends the line in progress, so the transcript keeps its order.
                text,found=stream.flush()
                redacted+=found
                add_out(ts,text)
                if kind=="cmd":
                    command=strip_ansi(str(raw or "")).strip()[:MAX_EVENT_COMMAND]
                    if not command:continue
                    if stream.do_redact:
                        command,found=redact(command)
                        redacted+=found
                    add(ts,"cmd",command)
                elif kind=="exit":add(ts,"exit",_exit_data(raw))
                else:
                    note=strip_ansi(str(raw or "")).strip()[:2000]
                    if note:add(ts,"mark",note)
            meta["bytes"]=size;meta["redacted"]=redacted
            if capped:meta["capped"]=True
            cur.execute("UPDATE ReportEvidence SET meta=? WHERE id=?",(json.dumps(meta,ensure_ascii=False),evidence_id))
            con.commit()
            return {"seq":seq,"capped":capped,"bytes":size}
        finally:
            con.close()
def _clock(ts):
    return ts[11:19] if len(ts)>=19 and ts[10:11]=="T" else ts
def _duration_text(seconds):
    try:value=float(seconds)
    except Exception:return ""
    if value<60:return ("%.1f"%value)+"s"
    return str(int(value//60))+"m "+str(int(value%60))+"s"
def render_transcript(evidence,events):
    """Readable plain text of a recording: "[10:12:03] $ nmap ..." then the output, then "[exit 0, 3.2s]". Times are UTC."""
    lines=[]
    meta=evidence.get("meta") or {}
    head="# "+(evidence.get("title") or "Session recording")
    lines.append(head)
    info=["started "+(evidence.get("started_at") or "")[:19].replace("T"," ")+" UTC"]
    if meta.get("shell") and meta.get("shell")!="shell":info.append("shell "+str(meta.get("shell")))
    if evidence.get("target"):info.append("target "+str(evidence.get("target")))
    lines.append("# "+", ".join(info))
    lines.append("")
    pending_command=None
    for event in events:
        kind=event.get("kind");data=event.get("data") or ""
        if kind=="cmd":
            lines.append("["+_clock(event.get("ts",""))+"] $ "+data)
            pending_command=data
        elif kind=="out":
            text=data
            if pending_command:
                text=_strip_echo(text,pending_command)
                pending_command=None
            text=_strip_prompt_tail(text).rstrip("\n")
            if text:lines.append(text)
        elif kind=="exit":
            pending_command=None
            try:value=json.loads(data)
            except Exception:value={}
            code=value.get("code") if isinstance(value,dict) else None
            took=_duration_text(value.get("duration")) if isinstance(value,dict) and value.get("duration") is not None else ""
            lines.append("["+("exit "+str(code) if code is not None else "no exit code")+(", "+took if took else "")+"]")
            lines.append("")
        elif kind=="mark":
            lines.append("["+_clock(event.get("ts",""))+"] -- "+data+" --")
    text="\n".join(lines).rstrip("\n")+"\n"
    return text
def _stop(cur,data,reason=""):
    evidence_id=data["id"]
    meta=data["meta"]
    stream=_streams.pop(evidence_id,None)
    if stream is not None:
        text,found=stream.flush()
        if text and not meta.get("capped"):
            cur.execute("INSERT INTO ReportEvidenceEvents(evidence_id,seq,ts,kind,data) VALUES(?,?,?,?,?)",(evidence_id,_next_seq(cur,evidence_id),_now(),"out",text))
            meta["bytes"]=int(meta.get("bytes",0) or 0)+len(text)
        meta["redacted"]=int(meta.get("redacted",0) or 0)+found
    events=_events(cur,evidence_id)
    if not events:
        # Nothing was captured: an empty recording is only noise in the evidence list.
        cur.execute("DELETE FROM ReportEvidence WHERE id=?",(evidence_id,))
        meta["state"]="stopped";meta["discarded"]=True
        return False
    meta["state"]="stopped"
    if reason:meta["stopped_reason"]=reason
    meta.pop("boot",None);meta.pop("live_session",None)
    ended=_now()
    if reason=="interrupted":ended=events[-1]["ts"] if events else (data.get("started_at") or ended)
    data["ended_at"]=ended
    content,truncated=cap_text(render_transcript(data,events),MAX_RECORDING+64*1024)
    if truncated:meta["truncated"]=True
    meta["commands"]=sum(1 for event in events if event["kind"]=="cmd")
    cur.execute("UPDATE ReportEvidence SET ended_at=?,content=?,meta=? WHERE id=?",(ended,content,json.dumps(meta,ensure_ascii=False),evidence_id))
    return True
def recording_stop(ident):
    with _rec_lock:
        con=_con()
        try:
            cur=con.cursor()
            row=_find(cur,ident)
            if not row:raise ValueError("Evidence not found.")
            data=_row(row)
            if data["kind"]!="recording":raise ValueError("This evidence item is not a recording.")
            if data["meta"].get("state")=="recording":
                kept=_stop(cur,data)
                con.commit()
                if not kept:
                    data["events"]=[]
                    return data
            return get(data["id"],con)
        finally:
            con.close()
def sweep_recordings():
    """Close recordings left open by a previous run of the app, or whose terminal session has ended. Returns how many were closed."""
    closed=0
    with _rec_lock:
        con=_con()
        try:
            cur=con.cursor()
            cur.execute("SELECT "+_COLS+" FROM ReportEvidence WHERE kind='recording' AND meta LIKE '%\"state\": \"recording\"%'")
            for row in cur.fetchall():
                data=_row(row)
                meta=data["meta"]
                if meta.get("state")!="recording":continue
                if meta.get("boot")==_BOOT and not (meta.get("live_session") and not _session_alive(data["session_id"])):continue
                _stop(cur,data,"interrupted")
                closed+=1
            if closed:con.commit()
        finally:
            con.close()
    return closed
def recordings_active():
    sweep_recordings()
    con=_con()
    try:
        cur=con.cursor()
        cur.execute("SELECT "+_COLS+" FROM ReportEvidence WHERE kind='recording' AND meta LIKE '%\"state\": \"recording\"%' ORDER BY id")
        out=[]
        for row in cur.fetchall():
            data=_row(row)
            if data["meta"].get("state")!="recording":continue
            data["content"]=""
            out.append(data)
        return out
    finally:
        con.close()
