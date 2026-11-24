"""Report timeline and schedule: milestone normalisation, next deadline, and reminders that fire once per channel.
The schedule lives in report.meta.schedule = {milestones:[{id,key,label,date,time,done,remind:[{days_before}],notes}]}.
Fired markers live beside it in report.meta.schedule_fired (inside the database, so they follow the report and survive restarts)."""
import json,re,uuid
from datetime import date,datetime,timedelta
from Cores import common_db
from Cores import db_driver as _db_driver
MILESTONE_KEYS=("kickoff","testing_start","testing_end","draft_due","review","handover","retest_start","retest_end","custom")
MILESTONE_LABELS={"kickoff":"Kick-off","testing_start":"Testing start","testing_end":"Testing end","draft_due":"Draft report","review":"QA / review","handover":"Hand-over","retest_start":"Retest start","retest_end":"Retest end","custom":"Milestone"}
PHASES=(("testing","Testing","testing_start","testing_end"),("retest","Retest","retest_start","retest_end"))
CHANNELS=("app","os")
MAX_MILESTONES=60
MAX_REMINDERS=8
MAX_DAYS_BEFORE=365
_ID_RX=re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_TIME_RX=re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
def _s(v,n=0):
    t="" if v is None else str(v).strip()
    return t[:n] if n else t
def _date(v):
    t=_s(v)[:10]
    try:return datetime.strptime(t,"%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:return ""
def _to_date(v):
    try:return datetime.strptime(str(v)[:10],"%Y-%m-%d").date()
    except (TypeError,ValueError):return None
def _today(now=None):
    if isinstance(now,datetime):return now.date()
    if isinstance(now,date):return now
    return datetime.now().date()
def _remind(v):
    out=[]
    for r in v if isinstance(v,(list,tuple)) else []:
        n=r.get("days_before") if isinstance(r,dict) else r
        if isinstance(n,bool):continue
        try:n=int(n)
        except (TypeError,ValueError):continue
        if 0<=n<=MAX_DAYS_BEFORE and n not in out:out.append(n)
    return [{"days_before":n} for n in sorted(out,reverse=True)[:MAX_REMINDERS]]
def normalize(schedule):
    """Any input -> {milestones:[...]} with every field present and valid. Unknown keys become "custom"; ids are kept when sane and unique."""
    src=schedule.get("milestones") if isinstance(schedule,dict) else schedule
    out=[];seen=set()
    for m in src if isinstance(src,(list,tuple)) else []:
        if not isinstance(m,dict) or len(out)>=MAX_MILESTONES:continue
        key=_s(m.get("key")).lower()
        if key not in MILESTONE_KEYS:key="custom"
        mid=_s(m.get("id"))
        if not _ID_RX.match(mid) or mid in seen:mid=uuid.uuid4().hex[:12]
        seen.add(mid)
        t=_s(m.get("time"))
        done=m.get("done")
        out.append({"id":mid,"key":key,"label":_s(m.get("label"),120) or MILESTONE_LABELS[key],"date":_date(m.get("date")),"time":t if _TIME_RX.match(t) else "",
            "done":done.strip().lower() in ("1","true","yes","on") if isinstance(done,str) else bool(done),"remind":_remind(m.get("remind")),"notes":_s(m.get("notes"),2000)})
    return {"milestones":out}
def days_text(days_left):
    if days_left==0:return "today"
    if days_left==1:return "tomorrow"
    if days_left==-1:return "yesterday"
    return f"in {days_left} days" if days_left>0 else f"{-days_left} days ago"
_TOAST_UNSAFE_RX=re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
def _toast_text(value,limit):
    """Titles reach OS notifications: no control or bidi-override characters, one line, bounded length."""
    t=" ".join(_TOAST_UNSAFE_RX.sub(" ",str(value or "")).split())
    return t if len(t)<=limit else t[:limit-1].rstrip()+"\u2026"
def reminder_message(title,label,when,days_left,time=""):
    """Hand-over for 'ACME External Pentest' is due tomorrow (2026-11-30)"""
    stamp=when+(" "+time if time else "")
    title,label=_toast_text(title,80),_toast_text(label,60)
    return f"{label or 'Milestone'} for '{title or 'Untitled report'}' {'was' if days_left<0 else 'is'} due {days_text(days_left)} ({stamp})"
def _pending(meta):
    """Dated milestones that are not done, earliest first."""
    rows=[m for m in normalize((meta or {}).get("schedule"))["milestones"] if m["date"] and not m["done"]]
    rows.sort(key=lambda m:(m["date"],m["time"] or "99:99"))
    return rows
def _row(report_id,title,m,today):
    left=(_to_date(m["date"])-today).days
    return {"report_id":int(report_id),"title":title or "","milestone":m["id"],"key":m["key"],"label":m["label"],"date":m["date"],"time":m["time"],"days_left":left,"overdue":left<0}
def next_deadline(report,now=None):
    """The earliest milestone that is not done (an overdue one comes first), or None. Final reports have no deadline."""
    if not isinstance(report,dict) or report.get("status")=="final":return None
    rows=_pending(report.get("meta"))
    return _row(report.get("id") or 0,report.get("title"),rows[0],_today(now)) if rows else None
def _json(text):
    try:
        o=json.loads(text or "{}")
        return o if isinstance(o,dict) else {}
    except (TypeError,ValueError):return {}
def _open_reports(cur):
    return [{"id":int(r[0]),"title":r[1] or "","status":r[2] or "draft","meta":_json(r[3])} for r in cur.execute("SELECT id,title,status,meta FROM Reports WHERE status IS NULL OR status<>'final' ORDER BY id")]
def overview(cur,now=None):
    """(next_deadline|None, overdue milestone count) across every report that is not final - for the dashboard card."""
    today=_today(now);best=None;overdue=0
    for rep in _open_reports(cur):
        rows=[_row(rep["id"],rep["title"],m,today) for m in _pending(rep["meta"])]
        overdue+=sum(1 for r in rows if r["overdue"])
        if rows and (best is None or (rows[0]["date"],rows[0]["time"] or "99:99")<(best["date"],best["time"] or "99:99")):best=rows[0]
    if best:best={k:best[k] for k in ("report_id","title","label","date","days_left","overdue")}
    return best,overdue
class _Conn:
    def __enter__(self):
        self.con=common_db.connect(common_db.db_path(),timeout=5)
        try:common_db.ensure_schema(self.con)
        except BaseException:
            self.con.close()
            raise
        return self.con
    def __exit__(self,et,ev,tb):
        try:
            if et is None:self.con.commit()
            else:self.con.rollback()
        finally:self.con.close()
        return False
def upcoming(limit=20,now=None):
    """Every pending milestone of the reports that are not final, earliest first."""
    try:limit=max(1,min(500,int(limit)))
    except (TypeError,ValueError):limit=20
    today=_today(now);out=[]
    with _Conn() as con:
        for rep in _open_reports(con.cursor()):out+=[_row(rep["id"],rep["title"],m,today) for m in _pending(rep["meta"])]
    out.sort(key=lambda r:(r["date"],r["time"] or "99:99",r["report_id"]))
    return out[:limit]
def deadlines(now=None):
    """{report_id (as text): next deadline} for the report list."""
    today=_today(now);out={}
    with _Conn() as con:
        for rep in _open_reports(con.cursor()):
            rows=_pending(rep["meta"])
            if rows:out[str(rep["id"])]=_row(rep["id"],rep["title"],rows[0],today)
    return out
def _fire_key(m,what):return f"{m['id']}|{m['date']}|{what}"
def _due_for(m,today,fired,channel):
    """The reminders of one milestone that are due and not yet delivered on this channel: [fire key]. An overdue notice is added once
    for a milestone that has reminders configured, so a deadline missed while the app was closed is still mentioned."""
    if not m["remind"]:return []
    left=(_to_date(m["date"])-today).days
    keys=[_fire_key(m,"overdue")] if left<0 else [_fire_key(m,r["days_before"]) for r in m["remind"] if left<=r["days_before"]]
    return [k for k in keys if channel not in (fired.get(k) or {})]
def due_reminders(now=None,channel="app",mark=True):
    """Reminders that are due now, one row per milestone: [{report_id,title,milestone,label,date,days_left,message}].
    With mark=True they are recorded as delivered on that channel, so each fires once per channel even across restarts.
    While the app or the database is locked nothing is read and nothing fires."""
    if channel not in CHANNELS:channel="app"
    try:
        if common_db.db_locked():return []
        today=_today(now);stamp=datetime.now().isoformat(timespec="seconds");out=[]
        with _Conn() as con:
            cur=con.cursor()
            for rep in _open_reports(cur):
                meta=rep["meta"]
                fired=meta.get("schedule_fired") if isinstance(meta.get("schedule_fired"),dict) else {}
                rows=_pending(meta);changed=False
                for m in rows:
                    keys=_due_for(m,today,fired,channel)
                    if not keys:continue
                    row=_row(rep["id"],rep["title"],m,today)
                    row["message"]=reminder_message(rep["title"],m["label"],m["date"],row["days_left"],m["time"])
                    out.append(row)
                    for k in keys:
                        entry=fired.get(k) if isinstance(fired.get(k),dict) else {}
                        entry[channel]=stamp
                        fired[k]=entry
                    changed=True
                if changed and mark:
                    # Markers of milestones that were removed or re-dated are dropped here, so the map cannot grow without bound.
                    live={m["id"]+"|"+m["date"] for m in rows}
                    fired={k:v for k,v in fired.items() if k.rsplit("|",1)[0] in live}
                    fresh=_json((cur.execute("SELECT meta FROM Reports WHERE id=?",(rep["id"],)).fetchone() or ("",))[0])
                    fresh["schedule_fired"]=fired
                    cur.execute("UPDATE Reports SET meta=? WHERE id=?",(json.dumps(fresh,ensure_ascii=False),rep["id"]))
        out.sort(key=lambda r:(r["date"],r["report_id"]))
        return out
    except (common_db.DatabaseLocked,_db_driver.Error):
        return []
def notify_os(send,enabled,now=None):
    """Scheduler hook: deliver the due reminders as OS notifications. Returns how many were sent. Never raises."""
    try:
        if not enabled or common_db.db_locked():return 0
        n=0
        for r in due_reminders(now,"os"):
            try:
                send("LOYA NG",r["message"])
                n+=1
            except Exception:pass
        return n
    except Exception:
        return 0
