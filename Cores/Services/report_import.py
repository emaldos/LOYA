"""Report import: full-fidelity report JSON (single or bundle), findings CSV (generic and scanner exports), report templates
and the findings library. Nothing in a file is trusted: ids are dropped, rich text is sanitised, images are checked by magic bytes."""
import os,re,io,csv,json,html,base64,uuid
from Cores.Services import report_export as rx
KINDS=("report_json","findings_csv","templates","library")
KIND_LABELS={"report_json":"Report (JSON)","findings_csv":"Findings (CSV)","templates":"Report templates (JSON)","library":"Findings library (JSON)"}
MAX_JSON_BYTES=120*1024*1024
MAX_CSV_BYTES=30*1024*1024
MAX_REPORTS=200
MAX_SECTIONS=300
MAX_FINDINGS=5000
MAX_ASSETS=2000
MAX_EVIDENCE=5000
MAX_EVENTS=20000
MAX_CSV_ROWS=200000
MAX_TEMPLATES=500
MAX_LIBRARY=5000
EVIDENCE_KINDS=("command","recording","text","image")
_UID_RX=re.compile(r"^[A-Za-z0-9_-]{1,64}$")
def _s(v):return "" if v is None else str(v)
def _svc():
    svc=rx._svc("reports_service")
    if svc is None:raise ValueError("Reporting is not available.")
    return svc
def _san(svc,markup):
    try:return svc.sanitize_html(_s(markup))
    except Exception:return html.escape(rx.rich_text(markup))
# ---- reading / sniffing ----
def _read_json(path):
    try:size=os.path.getsize(path)
    except OSError:raise ValueError("The file could not be read.")
    if size>MAX_JSON_BYTES:raise ValueError(f"The file is larger than {MAX_JSON_BYTES//(1024*1024)} MB.")
    if size==0:raise ValueError("The file is empty.")
    try:
        with open(path,"r",encoding="utf-8-sig") as f:return json.load(f)
    except (UnicodeDecodeError,ValueError,RecursionError):raise ValueError("This file is not valid JSON.")
    except OSError:raise ValueError("The file could not be read.")
def classify(obj):
    """Which import a parsed JSON document is, or "" when it is not one of ours."""
    if isinstance(obj,dict):
        fmt=_s(obj.get("format")).lower()
        if fmt in (rx.JSON_FORMAT,rx.BUNDLE_FORMAT):return "report_json"
        if fmt==rx.TEMPLATES_FORMAT:return "templates"
        if fmt==rx.LIBRARY_FORMAT:return "library"
        if isinstance(obj.get("report"),dict) or isinstance(obj.get("reports"),list):return "report_json"
        if isinstance(obj.get("templates"),list):return "templates"
        if isinstance(obj.get("entries"),list):return "library"
        if isinstance(obj.get("sections"),list) and isinstance(obj.get("findings"),list):return "report_json"
        if isinstance(obj.get("sections"),list) and obj.get("name"):return "templates"
    return ""
def sniff(path):
    """Best guess of the import kind for a file ("" when it is not a reporting file)."""
    low=_s(path).lower()
    if low.endswith((".csv",".tsv")):return "findings_csv"
    try:
        with open(path,"rb") as f:head=f.read(4096)
    except OSError:return ""
    text=head.decode("utf-8","ignore").lstrip("﻿ \t\r\n")
    if not text.startswith(("{","[")):
        return "findings_csv" if low.endswith(".txt") and "," in text else ""
    m=re.search(r'"format"\s*:\s*"([a-z\-]+)"',text)
    if m:
        k=classify({"format":m.group(1)})
        if k:return k
    try:return classify(_read_json(path))
    except ValueError:return ""
# ---- report JSON ----
def _check_report(r):
    if not isinstance(r,dict):raise ValueError("This file does not contain a valid report.")
    if not isinstance(r.get("title"),str) or not isinstance(r.get("sections",[]),list) or not isinstance(r.get("findings",[]),list):raise ValueError("This file does not contain a valid report.")
    if r.get("meta") is not None and not isinstance(r.get("meta"),dict):raise ValueError("This file does not contain a valid report.")
    if len(r.get("sections") or [])>MAX_SECTIONS:raise ValueError(f"A report may have at most {MAX_SECTIONS} sections.")
    if len(r.get("findings") or [])>MAX_FINDINGS:raise ValueError(f"A report may have at most {MAX_FINDINGS} findings.")
    return r
def unpack_reports(obj):
    """-> (reports, assets{uid:entry}, evidence[rows]) from a single-report file, a bundle, or a bare report object."""
    if not isinstance(obj,dict):raise ValueError("This file does not contain a valid report.")
    if isinstance(obj.get("reports"),list):reports=obj["reports"]
    elif isinstance(obj.get("report"),dict):reports=[obj["report"]]
    elif isinstance(obj.get("sections"),list) and isinstance(obj.get("findings"),list):reports=[obj]
    else:raise ValueError("This file does not contain a valid report.")
    try:ver=int(obj.get("version",1) or 1)
    except (TypeError,ValueError):ver=1
    if ver>1:raise ValueError("This report file was made by a newer version of LOYA NG.")
    if not reports:raise ValueError("This file does not contain any reports.")
    if len(reports)>MAX_REPORTS:raise ValueError(f"A bundle may hold at most {MAX_REPORTS} reports.")
    reports=[_check_report(r) for r in reports]
    assets=obj.get("assets") if isinstance(obj.get("assets"),dict) else {}
    evidence=[e for e in (obj.get("evidence") if isinstance(obj.get("evidence"),list) else []) if isinstance(e,dict) and _UID_RX.match(_s(e.get("uid"))) and _s(e.get("kind")) in EVIDENCE_KINDS]
    if len(assets)>MAX_ASSETS:raise ValueError(f"A report file may hold at most {MAX_ASSETS} images.")
    if len(evidence)>MAX_EVIDENCE:raise ValueError(f"A report file may hold at most {MAX_EVIDENCE} evidence items.")
    return reports,assets,evidence
def _asset_bytes(entry):
    """Decoded, magic-byte-checked image bytes of one payload asset, or None."""
    if not isinstance(entry,dict):return None
    raw=entry.get("data_b64")
    if not isinstance(raw,str) or not raw or len(raw)>rx.MAX_IMAGE_BYTES*4//3+1024:return None
    try:data=base64.b64decode(raw.split(",",1)[-1] if raw.startswith("data:") else raw,validate=True)
    except Exception:return None
    if not rx.sniff_image(data) or len(data)>rx.MAX_IMAGE_BYTES:return None
    return data
def _import_assets(svc,assets,wanted):
    """Store the referenced images; returns {old uid: new uid} (the store de-duplicates by content)."""
    amap={}
    for uid in wanted:
        if uid in amap or uid not in assets:continue
        data=_asset_bytes(assets[uid])
        if data is None:continue
        try:amap[uid]=svc.add_asset(_s(assets[uid].get("name"))[:200] or "image",data)["uid"]
        except ValueError:pass
    return amap
def _import_evidence(cur,evidence,wanted,amap):
    """Recreate the referenced evidence rows; an identical existing row is reused, a different one with the same uid gets a new uid."""
    ev=rx._svc("evidence_service");emap={}
    if ev is None or not hasattr(ev,"restore_entry"):return emap,0
    made=0
    for row in evidence:
        uid=_s(row.get("uid"))
        if uid not in wanted or uid in emap:continue
        meta=dict(row.get("meta")) if isinstance(row.get("meta"),dict) else {}
        if meta.get("asset_uid"):meta["asset_uid"]=amap.get(_s(meta["asset_uid"]),_s(meta["asset_uid"]))
        data={k:row.get(k) for k in ("kind","title","source","command","exit_code","cwd","started_at","ended_at","content","created_at","target")}
        data["session_id"]="";data["profile_id"]="";data["meta"]=meta
        # Stored as captured (escape codes included): the exporter cleans on the way out, and an unchanged row must compare equal.
        data["content"]=_s(data.get("content")).replace("\x00","")[:4*1024*1024];data["command"]=_s(data.get("command")).replace("\x00","")[:20000]
        new_uid=uid
        cur.execute("SELECT kind,command,content FROM ReportEvidence WHERE uid=?",(uid,))
        old=cur.fetchone()
        if old:
            if (old[0] or "")==_s(data["kind"]) and (old[1] or "")==data["command"] and (old[2] or "")==data["content"]:
                emap[uid]=uid;continue
            new_uid=uuid.uuid4().hex
        data["uid"]=new_uid
        events=[e for e in (row.get("events") if isinstance(row.get("events"),list) else []) if isinstance(e,dict)][:MAX_EVENTS]
        try:
            ev.restore_entry({"evidence":data,"events":events},cur)
            emap[uid]=new_uid;made+=1
        except ValueError:pass
    return emap,made
def _rewrite(markup,amap,emap):
    markup=_s(markup)
    if amap:markup=rx._ASSET_RX.sub(lambda m:"rptasset:"+amap.get(m.group(1),m.group(1)),markup)
    if emap:markup=rx._EVID_RX.sub(lambda m:'data-evidence="'+emap.get(m.group(1),m.group(1))+'"',markup)
    return markup
_FINDING_KEYS=("title","severity","cvss_vector","cvss_score","status","cwe","owasp","references","affected","likelihood","tags","retest_notes","source","cves","targets")
def _finding_payload(svc,f,amap,emap):
    out={k:f[k] for k in _FINDING_KEYS if k in f}
    out["title"]=_s(f.get("title"))[:300]
    for k in ("description","impact","steps","remediation"):out[k]=_san(svc,_rewrite(f.get(k),amap,emap))
    ev=[]
    for e in f.get("evidence") if isinstance(f.get("evidence"),list) else []:
        if not isinstance(e,dict):continue
        a,u=_s(e.get("asset_uid")),_s(e.get("evidence_uid"))
        if a:ev.append({"asset_uid":amap.get(a,a),"evidence_uid":"","caption":_s(e.get("caption"))})
        elif u:ev.append({"asset_uid":"","evidence_uid":emap.get(u,u),"caption":_s(e.get("caption"))})
    out["evidence"]=ev
    if _UID_RX.match(_s(f.get("uid"))):out["uid"]=_s(f.get("uid"))
    return out
def _report_payload(svc,r,amap,emap,builtin_ids):
    sections=[s for s in r.get("sections") or [] if isinstance(s,dict)]
    findings=[f for f in r.get("findings") or [] if isinstance(f,dict)]
    pos=lambda x:rx._int(x.get("position"),0,-10**9,10**9)
    sections.sort(key=pos);findings.sort(key=pos)
    branding=dict(r.get("branding")) if isinstance(r.get("branding"),dict) else {}
    if branding.get("logo_asset"):branding["logo_asset"]=amap.get(_s(branding["logo_asset"]),_s(branding["logo_asset"]))
    tid=_s(r.get("template_id"))
    return {"title":_s(r.get("title")).strip()[:300] or "Imported report","status":_s(r.get("status")),"template_id":tid if tid in builtin_ids else "blank","profile_id":"","uid":_s(r.get("uid")),
        "meta":dict(r.get("meta")) if isinstance(r.get("meta"),dict) else {},"branding":branding,"options":dict(r.get("options")) if isinstance(r.get("options"),dict) else {},
        "sections":[{"kind":_s(s.get("kind")),"title":_s(s.get("title"))[:300],"content":_san(svc,_rewrite(s.get("content"),amap,emap)),"hidden":bool(s.get("hidden")),"options":s.get("options") if isinstance(s.get("options"),dict) else {}} for s in sections],
        "findings":[_finding_payload(svc,f,amap,emap) for f in findings],
        # Linked targets travel as snapshots; on another machine the target itself is unknown, so the link shows as "target removed" and keeps its data.
        "targets":[{k:l.get(k) for k in ("uid","target_id","profile_id","name","snapshot","allowed_secret_keys","linked_at","updated_at")} for l in (r.get("targets") if isinstance(r.get("targets"),list) else []) if isinstance(l,dict)][:500]}
def _builtin_template_ids(svc):
    try:return {t["id"] for t in svc.templates() if t.get("builtin")}
    except Exception:return {"blank"}
def _transaction(svc):
    """One transaction for the whole import when the report service exposes its connection helper; otherwise per-call commits."""
    db=getattr(svc,"_db",None)
    if callable(db):return db()
    import contextlib
    return contextlib.nullcontext(None)
def import_reports(obj):
    svc=_svc()
    reports,assets,evidence=unpack_reports(obj)
    wanted_a=[];wanted_e=[]
    for r in reports:
        a,e=rx.referenced(r)
        wanted_a+=[x for x in a if x not in wanted_a];wanted_e+=[x for x in e if x not in wanted_e]
    for row in evidence:
        au=_s((row.get("meta") or {}).get("asset_uid")) if isinstance(row.get("meta"),dict) else ""
        if au and _s(row.get("uid")) in wanted_e and au not in wanted_a:wanted_a.append(au)
    builtin=_builtin_template_ids(svc);ids=[];n_find=0
    with _transaction(svc) as con:
        amap=_import_assets(svc,assets,wanted_a)
        emap={}
        if con is not None:emap,_made=_import_evidence(con.cursor(),evidence,set(wanted_e),amap)
        for r in reports:
            payload=_report_payload(svc,r,amap,emap,builtin)
            uid=payload["uid"]
            if _UID_RX.match(uid):
                try:
                    svc.get_report(uid)
                    if not payload["title"].endswith("(imported)"):payload["title"]=payload["title"][:289]+" (imported)"
                except ValueError:pass
            rep=svc.create_report(payload)
            ids.append(rep["id"]);n_find+=len(rep.get("findings") or [])
    return {"reports":len(ids),"findings":n_find,"templates":0,"library":0,"report_ids":ids,"message":f"Imported {len(ids)} report{'' if len(ids)==1 else 's'} with {n_find} finding{'' if n_find==1 else 's'}."}
def _reports_summary(obj):
    reports,assets,evidence=unpack_reports(obj)
    counts={s:0 for s in rx.SEVERITIES};items=[];nf=0;ns=0;warn=[]
    wanted_a=set();bad=0
    for r in reports:
        fs=[f for f in r.get("findings") or [] if isinstance(f,dict)]
        for f in fs:counts[rx.sev(f.get("severity"))]+=1
        nf+=len(fs);ns+=len(r.get("sections") or [])
        meta=r.get("meta") if isinstance(r.get("meta"),dict) else {}
        if len(items)<30:items.append({"title":_s(r.get("title"))[:200] or "Untitled report","detail":", ".join(x for x in (_s(meta.get("client"))[:80],f"{len(fs)} finding{'' if len(fs)==1 else 's'}") if x)})
        wanted_a.update(rx.referenced(r)[0])
    for uid in wanted_a:
        if uid in assets and _asset_bytes(assets[uid]) is None:bad+=1
    missing=len([u for u in wanted_a if u not in assets])
    if bad:warn.append(f"{bad} image{'' if bad==1 else 's'} in the file are not valid PNG, JPEG, GIF or WebP data and will be skipped.")
    if missing:warn.append(f"{missing} referenced image{'' if missing==1 else 's'} are not in the file.")
    if evidence and rx._svc("evidence_service") is None:warn.append("Evidence in the file cannot be restored on this installation.")
    return {"reports":len(reports),"findings":nf,"sections":ns,"assets":len([u for u in wanted_a if u in assets])-bad,"evidence":len(evidence),"templates":0,"library":0,"severity":counts,"items":items,"warnings":warn}
# ---- templates / library ----
def _template_list(obj):
    if isinstance(obj,dict) and isinstance(obj.get("templates"),list):items=obj["templates"]
    elif isinstance(obj,list):items=obj
    elif isinstance(obj,dict) and isinstance(obj.get("sections"),list):items=[obj]
    else:raise ValueError("This file does not contain report templates.")
    out=[t for t in items if isinstance(t,dict) and _s(t.get("name")).strip() and isinstance(t.get("sections"),list)]
    if not out:raise ValueError("This file does not contain report templates.")
    if len(out)>MAX_TEMPLATES:raise ValueError(f"A file may hold at most {MAX_TEMPLATES} templates.")
    for t in out:
        if len(t["sections"])>MAX_SECTIONS:raise ValueError(f"A template may have at most {MAX_SECTIONS} sections.")
    return out
def _free_name(name,taken):
    name=name.strip()[:110] or "Imported template"
    if name.lower() not in taken:return name
    base=name+" (imported)";n=base;i=2
    while n.lower() in taken:n=f"{base} {i}";i+=1
    return n
def import_templates(obj):
    svc=_svc();items=_template_list(obj)
    assets=obj.get("assets") if isinstance(obj,dict) and isinstance(obj.get("assets"),dict) else {}
    made=0
    with _transaction(svc):
        taken={_s(t.get("name")).lower() for t in svc.templates()}
        for t in items:
            wanted=[]
            for s in t["sections"]:
                if isinstance(s,dict):wanted+=[m.group(1) for m in rx._ASSET_RX.finditer(_s(s.get("content")))]
            amap=_import_assets(svc,assets,wanted)
            name=_free_name(_s(t.get("name")),taken);taken.add(name.lower())
            svc.template_save({"name":name,"description":_s(t.get("description"))[:500],"meta":t.get("meta") if isinstance(t.get("meta"),dict) else {},"options":t.get("options") if isinstance(t.get("options"),dict) else {},
                "sections":[{"kind":_s(s.get("kind")),"title":_s(s.get("title"))[:300],"content":_san(svc,_rewrite(s.get("content"),amap,{})),"hidden":bool(s.get("hidden"))} for s in t["sections"] if isinstance(s,dict)]})
            made+=1
    return {"reports":0,"findings":0,"templates":made,"library":0,"report_ids":[],"message":f"Imported {made} template{'' if made==1 else 's'}."}
def _library_list(obj):
    if isinstance(obj,dict) and isinstance(obj.get("entries"),list):items=obj["entries"]
    elif isinstance(obj,list):items=obj
    else:raise ValueError("This file does not contain a findings library.")
    out=[e for e in items if isinstance(e,dict) and _s(e.get("title")).strip()]
    if not out:raise ValueError("This file does not contain a findings library.")
    if len(out)>MAX_LIBRARY:raise ValueError(f"A file may hold at most {MAX_LIBRARY} library entries.")
    return out
def _library_existing(svc):
    try:return {_s(e.get("title")).strip().lower() for e in svc.library_list()}
    except Exception:return set()
def import_library(obj):
    svc=_svc();items=_library_list(obj)
    assets=obj.get("assets") if isinstance(obj,dict) and isinstance(obj.get("assets"),dict) else {}
    made=0;skipped=0
    with _transaction(svc):
        have=_library_existing(svc)
        for e in items:
            title=_s(e.get("title")).strip()[:300]
            if title.lower() in have:skipped+=1;continue
            wanted=[]
            for k in ("description","impact","steps","remediation"):wanted+=[m.group(1) for m in rx._ASSET_RX.finditer(_s(e.get(k)))]
            amap=_import_assets(svc,assets,wanted)
            entry={k:e[k] for k in ("severity","cvss_vector","cvss_score","cwe","owasp","references","likelihood","tags","cves") if k in e}
            entry["title"]=title;entry["category"]=_s(e.get("category"))[:80];entry["source"]={"kind":"import","ref":""}
            for k in ("description","impact","steps","remediation"):entry[k]=_san(svc,_rewrite(e.get(k),amap,{}))
            try:
                svc.library_save(entry);made+=1;have.add(title.lower())
            except ValueError:skipped+=1
    msg=f"Imported {made} library entr{'y' if made==1 else 'ies'}."+(f" Skipped {skipped} that already exist or are invalid." if skipped else "")
    return {"reports":0,"findings":0,"templates":0,"library":made,"skipped":skipped,"report_ids":[],"message":msg}
# ---- findings CSV ----
_COLS=(
    ("title",("title","name","finding","finding title","finding name","vulnerability","vulnerability name","vulnerability title","issue","issue name","issue title","plugin name","alert","summary","check","rule")),
    ("severity",("severity","risk","risk level","risk rating","risk factor","rating","criticality","priority","threat","severity level")),
    ("cvss_score",("cvss score","cvss","cvss v3 1 base score","cvss v3 0 base score","cvss v3 base score","cvss3 base score","cvss base score","cvssv3","cvss v3","cvss3","cvss v4 0 base score","cvss v2 0 base score","cvss v2 base score","cvss2 base score","base score","score")),
    ("cvss_vector",("cvss vector","vector","cvss v3 vector","cvss3 vector","cvss v3 1 vector","cvss v3 0 vector","vector string","cvss vector string")),
    ("status",("status","state","finding status")),
    ("cwe",("cwe","cwe id","cweid","cwe ids")),
    ("owasp",("owasp","owasp category","owasp top 10")),
    ("affected",("affected","affected assets","affected hosts","affected host","affected asset","affected systems","host","hosts","hostname","asset","assets","target","targets","ip","ip address","url","endpoint","location","dns name","netbios name","fqdn")),
    ("port",("port","ports")),
    ("protocol",("protocol","proto")),
    ("synopsis",("synopsis","short description","abstract")),
    ("description",("description","details","detail","finding description","issue description","vulnerability description","issue detail","issue background")),
    ("impact",("impact","business impact","risk description","consequence")),
    ("steps",("steps to reproduce","steps","reproduction","reproduction steps","proof of concept","poc","plugin output","evidence","proof","output")),
    ("remediation",("remediation","recommendation","recommendations","solution","fix","mitigation","remediation background","how to fix","recommended action")),
    ("references",("references","reference","see also","links","refs","urls","external references")),
    ("cve",("cve","cves","cve id","cve ids")),
    ("tags",("tags","category","labels")),
    ("likelihood",("likelihood","probability","exploitability")),
    ("plugin_id",("plugin id","pluginid","plugin")),
)
_SEV_WORDS={"critical":"critical","crit":"critical","severe":"critical","urgent":"critical","high":"high","serious":"high","medium":"medium","moderate":"medium","med":"medium","warning":"medium","low":"low","minor":"low","info":"info","informational":"info","information":"info","none":"info","log":"info","note":"info","false positive":"info"}
_SEV_NUM={"0":"info","1":"low","2":"medium","3":"high","4":"critical"}
_STATUS_WORDS={"open":"open","new":"open","active":"open","confirmed":"open","retest":"retest","in retest":"retest","to retest":"retest","fixed":"fixed","closed":"fixed","resolved":"fixed","remediated":"fixed","accepted":"accepted","risk accepted":"accepted","accepted risk":"accepted","wontfix":"accepted","won't fix":"accepted"}
def _hkey(h):return re.sub(r"[^a-z0-9]+"," ",_s(h).lower()).strip()
def map_headers(headers):
    """{field: column index} for the columns we understand; the first matching header wins, in the order the aliases are listed."""
    keys=[_hkey(h) for h in headers];out={}
    for field,aliases in _COLS:
        for a in aliases:
            if a in keys:out[field]=keys.index(a);break
    return out
def sev_from_score(score):
    if score is None:return "info"
    return "critical" if score>=9 else "high" if score>=7 else "medium" if score>=4 else "low" if score>0 else "info"
def _score(v):
    m=re.search(r"\d+(?:[.,]\d+)?",_s(v))
    if not m:return None
    try:x=float(m.group(0).replace(",","."))
    except ValueError:return None
    return round(x,1) if 0<=x<=10 else None
def _unsafe(v):
    """Undo the apostrophe our own CSV export puts in front of formula-looking cells."""
    v=_s(v).strip()
    return v[1:] if len(v)>1 and v[0]=="'" and v[1] in "=+-@|" else v
def plain_html(text):
    text=rx.clean_text(_s(text)).strip()
    if not text:return ""
    return "".join("<p>"+html.escape(p.strip(),quote=False).replace("\n","<br>")+"</p>" for p in re.split(r"\n\s*\n",text) if p.strip())
def _split_list(v):return [x.strip() for x in re.split(r"[\n;]+|,\s+|\s{2,}",_s(v)) if x.strip()]
def _split_affected(v):
    """Affected cell -> assets, split like _split_list but never at a comma inside parentheses (our own export writes a linked
    target as "name (value, value)")."""
    v=_s(v)
    out,cur,depth=[],"",0
    for part in re.split(r"([\n;]+|,\s+|\s{2,}|[()])",v):
        if part=="(":depth+=1
        elif part==")":depth=max(0,depth-1)
        elif depth==0 and part and re.fullmatch(r"[\n;]+|,\s+|\s{2,}",part):
            if cur.strip():out.append(cur.strip())
            cur="";continue
        cur+=part
    if cur.strip():out.append(cur.strip())
    return out
def _decode(raw):
    for enc in ("utf-8-sig","utf-16") if raw[:2] in (b"\xff\xfe",b"\xfe\xff") else ("utf-8-sig",):
        try:return raw.decode(enc)
        except UnicodeDecodeError:pass
    try:return raw.decode("utf-16") if raw[:2] in (b"\xff\xfe",b"\xfe\xff") else raw.decode("cp1252")
    except UnicodeDecodeError:return raw.decode("latin-1")
def read_csv(path):
    try:size=os.path.getsize(path)
    except OSError:raise ValueError("The file could not be read.")
    if size>MAX_CSV_BYTES:raise ValueError(f"The CSV file is larger than {MAX_CSV_BYTES//(1024*1024)} MB.")
    try:
        with open(path,"rb") as f:raw=f.read()
    except OSError:raise ValueError("The file could not be read.")
    if b"\x00" in raw[:4096] and raw[:2] not in (b"\xff\xfe",b"\xfe\xff"):raise ValueError("This file is not a CSV text file.")
    text=_decode(raw)
    if not text.strip():raise ValueError("The file is empty.")
    first=text.split("\n",1)[0]
    delim=max(",;\t|",key=lambda d:first.count(d))
    if first.count(delim)==0:delim=","
    try:csv.field_size_limit(16*1024*1024)
    except OverflowError:pass
    try:rows=[r for r in csv.reader(io.StringIO(text,newline=""),delimiter=delim) if any(c.strip() for c in r)]
    except csv.Error:raise ValueError("This file is not a valid CSV file.")
    if len(rows)<2:raise ValueError("The CSV file has no data rows.")
    if len(rows)>MAX_CSV_ROWS:raise ValueError(f"The CSV file has more than {MAX_CSV_ROWS} rows.")
    return rows[0],rows[1:]
def parse_findings_csv(path,name=""):
    """-> {findings:[finding fields], columns:{field: header}, scanner:bool, rows:int}. Rows that share a title are merged into one
    finding whose affected list collects every host (the shape of Nessus/OpenVAS/Qualys exports)."""
    headers,rows=read_csv(path)
    cols=map_headers(headers)
    if "title" not in cols:raise ValueError("No title column found. The CSV needs a header such as Title, Name or Finding.")
    scanner="plugin_id" in cols or ("affected" in cols and "port" in cols)
    def get(row,field):
        i=cols.get(field)
        return _unsafe(row[i]) if i is not None and i<len(row) else ""
    groups={};order=[]
    for row in rows:
        title=rx.clean_text(get(row,"title"))[:300]
        if not title:continue
        key=title.lower()
        g=groups.get(key)
        if g is None:
            if len(order)>=MAX_FINDINGS:continue
            score=_score(get(row,"cvss_score"));raw_sev=get(row,"severity").strip().lower()
            sev=_SEV_WORDS.get(raw_sev) or _SEV_NUM.get(raw_sev) or (sev_from_score(score) if score is not None else "info")
            desc=plain_html(get(row,"synopsis"))+plain_html(get(row,"description"))
            steps=get(row,"steps")
            vector=get(row,"cvss_vector").strip()
            if vector and not vector.upper().startswith("CVSS:") and re.match(r"(?i)^AV:[NALP]/AC:[LH]/PR:",vector):vector="CVSS:3.1/"+vector
            if not re.match(r"(?i)^CVSS:3\.[01]/",vector):vector=""
            cwe=get(row,"cwe").strip();m=re.search(r"\d+",cwe)
            g={"title":title,"severity":sev,"cvss_score":score,"cvss_vector":vector,"status":_STATUS_WORDS.get(get(row,"status").strip().lower(),"open"),"cwe":f"CWE-{m.group(0)}" if m else "","owasp":get(row,"owasp")[:160],
                "description":desc,"impact":plain_html(get(row,"impact")),"steps":("<pre>"+html.escape(rx.clean_output(steps)[:20000],quote=False)+"</pre>") if (steps and scanner) else plain_html(steps),"remediation":plain_html(get(row,"remediation")),
                "references":[],"affected":[],"tags":[],"cves":[],"likelihood":get(row,"likelihood").strip().lower() if get(row,"likelihood").strip().lower() in ("low","medium","high") else "","source":{"kind":"import","ref":_s(name)[:200]},"_seen":set()}
            groups[key]=g;order.append(key)
        for ref in _split_list(get(row,"references")):
            if ref not in g["references"] and len(g["references"])<50:g["references"].append(ref[:1000])
        for cve in re.findall(r"CVE-\d{4}-\d{4,7}",get(row,"cve"),re.I):
            ref="https://nvd.nist.gov/vuln/detail/"+cve.upper()
            if cve.upper() not in g["cves"] and len(g["cves"])<50:g["cves"].append(cve.upper())
            if ref not in g["references"] and len(g["references"])<50:g["references"].append(ref)
        for tag in _split_list(get(row,"tags")):
            if tag not in g["tags"] and len(g["tags"])<20:g["tags"].append(tag[:40])
        host=get(row,"affected")
        if host:
            port=get(row,"port").strip();proto=get(row,"protocol").strip().lower()
            hosts=[host] if scanner else _split_affected(host)
            for h in hosts:
                value=h+(f":{port}" if port and port!="0" else "")+(f"/{proto}" if proto and port and port!="0" else "")
                if value not in g["_seen"] and len(g["affected"])<500:
                    g["_seen"].add(value);g["affected"].append({"target_id":"","name":"","value":value[:500]})
    findings=[]
    for key in order:
        g=groups[key];g.pop("_seen",None);findings.append(g)
    if not findings:raise ValueError("No findings were found in the CSV file.")
    return {"findings":findings,"columns":{f:_s(headers[i]).strip() for f,i in cols.items()},"scanner":scanner,"rows":len(rows)}
def _csv_selection(parsed,options):
    opts=options if isinstance(options,dict) else {}
    include_info=opts.get("include_info")
    if include_info is None:include_info=not parsed["scanner"]
    return [f for f in parsed["findings"] if include_info or f["severity"]!="info"]
def import_findings_csv(path,options=None,name=""):
    svc=_svc();opts=options if isinstance(options,dict) else {}
    parsed=parse_findings_csv(path,name or os.path.basename(path))
    findings=_csv_selection(parsed,opts)
    if not findings:raise ValueError("Only informational rows were found. Enable \"Include informational findings\" to import them.")
    order={s:i for i,s in enumerate(rx.SEVERITIES)}
    findings.sort(key=lambda f:(order[f["severity"]],-(f["cvss_score"] or 0)))
    for f in findings:
        for k in ("description","impact","steps","remediation"):f[k]=_san(svc,f[k])
    rid=opts.get("report_id")
    with _transaction(svc):
        if rid not in (None,"",0):
            rep=svc.get_report(rid)
            for f in findings:svc.add_finding(rep["id"],f)
            ids=[rep["id"]]
        else:
            base=re.sub(r"\.[A-Za-z0-9]{1,5}$","",_s(name or os.path.basename(path))).strip() or "findings"
            rep=svc.create_report({"title":("Imported findings - "+base)[:300],"template_id":"blank","findings":findings,
                "sections":[{"kind":"executive_summary","title":"Executive Summary","content":""},{"kind":"findings_summary","title":"Findings Summary","content":""},{"kind":"findings","title":"Detailed Findings","content":""},{"kind":"remediation_roadmap","title":"Remediation Roadmap","content":""}]})
            ids=[rep["id"]]
    n=len(findings)
    return {"reports":0 if rid not in (None,"",0) else 1,"findings":n,"templates":0,"library":0,"report_ids":ids,"message":f"Imported {n} finding{'' if n==1 else 's'}"+(" into the report." if rid not in (None,"",0) else " into a new report.")}
def _csv_summary(path,name):
    parsed=parse_findings_csv(path,name)
    counts={s:0 for s in rx.SEVERITIES}
    for f in parsed["findings"]:counts[f["severity"]]+=1
    items=[{"title":f["title"][:200],"detail":rx.SEV_LABELS[f["severity"]]+(f", {len(f['affected'])} affected" if f["affected"] else "")} for f in sorted(parsed["findings"],key=lambda f:rx.SEV_RANK[f["severity"]])[:30]]
    warn=[]
    if "severity" not in parsed["columns"] and "cvss_score" not in parsed["columns"]:warn.append("No severity or CVSS column was found: every finding will be imported as Informational.")
    if parsed["scanner"] and counts["info"]:warn.append(f"{counts['info']} informational scanner result{'' if counts['info']==1 else 's'} are left out unless you include them.")
    return {"reports":0,"findings":len(parsed["findings"]),"sections":0,"assets":0,"evidence":0,"templates":0,"library":0,"severity":counts,"items":items,"warnings":warn,"columns":parsed["columns"],"rows":parsed["rows"],"scanner":parsed["scanner"],"needs_report":True}
# ---- entry points ----
def summarize(path,kind="auto"):
    """What an import would do, for the confirmation step: {kind, label, summary}. Raises ValueError on anything unusable."""
    if kind in ("auto","",None):
        kind=sniff(path)
        if not kind:raise ValueError("This file is not a report, findings CSV, template or findings library export.")
    if kind not in KINDS:raise ValueError("Unsupported import type.")
    name=os.path.basename(path)
    if kind=="findings_csv":summary=_csv_summary(path,name)
    else:
        obj=_read_json(path)
        found=classify(obj)
        if kind=="report_json":
            if found not in ("report_json",""):raise ValueError(f"This file holds {KIND_LABELS[found].lower()}, not a report.")
            summary=_reports_summary(obj)
        elif kind=="templates":
            if found not in ("templates","") and not isinstance(obj,list):raise ValueError(f"This file holds {KIND_LABELS[found].lower()}, not report templates.")
            items=_template_list(obj)
            summary={"reports":0,"findings":0,"sections":sum(len(t["sections"]) for t in items),"assets":0,"evidence":0,"templates":len(items),"library":0,"severity":None,"warnings":[],
                "items":[{"title":_s(t.get("name"))[:200],"detail":f"{len(t['sections'])} section{'' if len(t['sections'])==1 else 's'}"} for t in items[:30]]}
        else:
            if found not in ("library","") and not isinstance(obj,list):raise ValueError(f"This file holds {KIND_LABELS[found].lower()}, not a findings library.")
            items=_library_list(obj);counts={s:0 for s in rx.SEVERITIES}
            for e in items:counts[rx.sev(e.get("severity"))]+=1
            have=_library_existing(rx._svc("reports_service")) if rx._svc("reports_service") else set()
            dup=len([e for e in items if _s(e.get("title")).strip().lower() in have])
            summary={"reports":0,"findings":0,"sections":0,"assets":0,"evidence":0,"templates":0,"library":len(items),"severity":counts,"warnings":[f"{dup} entr{'y' if dup==1 else 'ies'} already exist in your library and will be skipped."] if dup else [],
                "items":[{"title":_s(e.get("title"))[:200],"detail":", ".join(x for x in (_s(e.get("category"))[:60],rx.SEV_LABELS[rx.sev(e.get("severity"))]) if x)} for e in items[:30]]}
    return {"kind":kind,"label":KIND_LABELS[kind],"summary":summary}
def apply(path,kind,options=None):
    if kind in ("auto","",None):kind=sniff(path)
    if kind not in KINDS:raise ValueError("Unsupported import type.")
    if kind=="findings_csv":return import_findings_csv(path,options,os.path.basename(path))
    obj=_read_json(path)
    if kind=="report_json":return import_reports(obj)
    if kind=="templates":return import_templates(obj)
    return import_library(obj)
# ---- export side of templates / library (kept here so the two file formats live next to their readers) ----
def _assets_for(texts):
    ctx=rx._Ctx({},False);out={}
    for t in texts:
        for m in rx._ASSET_RX.finditer(_s(t)):
            uid=m.group(1)
            if uid in out:continue
            a=ctx.asset(uid)
            if a:out[uid]={"mime":a["mime"],"name":a["name"],"width":a["width"],"height":a["height"],"data_b64":base64.b64encode(a["data"]).decode("ascii")}
    return out
def build_templates_export(ids=None):
    svc=_svc()
    listing=svc.templates()
    wanted=[_s(i) for i in ids] if ids else [t["id"] for t in listing if not t.get("builtin")]
    out=[]
    for tid in wanted:
        try:t=svc.template_get(tid)
        except ValueError:continue
        out.append({"name":t["name"],"description":t.get("description",""),"sections":t.get("sections",[]),"meta":t.get("meta",{}),"options":t.get("options",{})})
    if not out:raise ValueError("There are no saved templates to export yet. Save a report as a template first.")
    return {"format":rx.TEMPLATES_FORMAT,"version":1,"app":"LOYA NG","templates":out,"assets":_assets_for(s.get("content") for t in out for s in t["sections"])}
def build_library_export():
    svc=_svc();out=[]
    for row in svc.library_list():
        try:e=svc.library_get(row["id"])
        except ValueError:continue
        out.append({k:e.get(k) for k in ("title","category","severity","cvss_vector","cvss_score","cwe","owasp","references","description","impact","likelihood","steps","remediation","tags","cves")})
    if not out:raise ValueError("The findings library is empty.")
    return {"format":rx.LIBRARY_FORMAT,"version":1,"app":"LOYA NG","entries":out,"assets":_assets_for(e.get(k) for e in out for k in ("description","impact","steps","remediation"))}
