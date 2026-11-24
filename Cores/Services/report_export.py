"""Report export: the shared render model plus the HTML, Markdown, JSON, CSV and SARIF writers.
PDF, DOCX and XLSX live in report_export_pdf.py, report_export_docx.py and report_xlsx.py and consume the same model."""
import os,re,io,json,html,base64,csv,zipfile,importlib,uuid
from datetime import datetime,timezone
from html.parser import HTMLParser
from Cores.Services import report_design as design
from Cores.Services.report_design import SEVERITIES,SEV_LABELS,SEV_COLORS,SEV_TINTS,SEV_ON,SEV_INK
SEV_RANK={s:i for i,s in enumerate(SEVERITIES)}
STATUSES=("open","retest","fixed","accepted")
STATUS_LABELS={"open":"Open","retest":"Retest","fixed":"Fixed","accepted":"Risk Accepted"}
REPORT_STATUS_LABELS={"draft":"Draft","review":"In Review","final":"Final"}
DEFAULT_ACCENT="#1f4e79"
DEFAULT_SECONDARY="#475569"
FORMATS=[
    {"id":"pdf","label":"PDF","ext":"pdf","description":"The report design printed to PDF: cover, contents with page numbers, running headers, bookmarks."},
    {"id":"docx","label":"Word","ext":"docx","description":"Editable Word document in the report's theme: heading styles, a real table of contents, headers and footers."},
    {"id":"html","label":"HTML","ext":"html","description":"One self-contained web page (no scripts) with the same design as the PDF."},
    {"id":"markdown","label":"Markdown","ext":"zip","description":"ZIP with report.md and an assets folder - for wikis, Git and ticket systems."},
    {"id":"json","label":"JSON","ext":"json","description":"Full-fidelity backup with images and evidence. Can be imported again."},
    {"id":"csv","label":"CSV","ext":"csv","description":"Findings table for spreadsheets and ticket imports."},
    {"id":"xlsx","label":"Excel","ext":"xlsx","description":"Findings workbook with severity colours, filters and a summary sheet."},
    {"id":"sarif","label":"SARIF","ext":"sarif","description":"SARIF 2.1.0 findings for code-scanning dashboards and CI pipelines."},
]
FORMAT_BY_ID={f["id"]:f for f in FORMATS}
AUTO_KINDS=("findings_summary","findings","remediation_roadmap","document_control","risk_matrix","project_timeline","appendix_tools","appendix_commands","appendix_evidence","appendix_timeline")
CALLOUT_LABELS={"finding":"Finding","vuln":"Vulnerability","info":"Info","warning":"Warning","credential":"Credential","evidence":"Evidence"}
WIDGETS=("risk_matrix","severity_summary","findings_table","commands_run","scope_targets")
FIGURE_LINES=40
APPENDIX_LINES=1500
LINE_CHARS=2000
MAX_IMAGE_BYTES=10*1024*1024
JSON_FORMAT="loya-report"
BUNDLE_FORMAT="loya-report-bundle"
TEMPLATES_FORMAT="loya-report-templates"
LIBRARY_FORMAT="loya-report-library"
def _svc(name):
    try:return importlib.import_module("Cores.Services."+name)
    except Exception:return None
def _s(v):return "" if v is None else str(v)
def _hex(v,default):
    v=_s(v).strip()
    return v.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}",v) else default
def hex_rgb(v):
    v=_hex(v,"#000000")
    return int(v[1:3],16),int(v[3:5],16),int(v[5:7],16)
def mix(a,b,t):
    ra,rb=hex_rgb(a),hex_rgb(b)
    return "#%02x%02x%02x"%tuple(int(round(ra[i]+(rb[i]-ra[i])*t)) for i in range(3))
def on_color(fill):
    """Readable text colour for a solid fill: white, or near-black when the brand colour is a light one."""
    r,g,b=[(c/255.0/12.92) if c/255.0<=0.03928 else ((c/255.0+0.055)/1.055)**2.4 for c in hex_rgb(fill)]
    return "#111827" if 0.2126*r+0.7152*g+0.0722*b>0.36 else "#ffffff"
def sev(v):
    v=_s(v).strip().lower()
    return v if v in SEV_RANK else ("info" if v in ("informational","information","none","") else "info")
_ANSI_RX=re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[\[\(][0-9;?]*[ -/]*[@-~]|\x1b.")
_CTRL_RX=re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff￾￿]")
def clean_text(s):
    """Text every writer can hold: XML (docx/xlsx) rejects control characters and lone surrogates outright."""
    if not isinstance(s,str):return s
    if "\x1b" in s:s=_ANSI_RX.sub("",s)
    return _CTRL_RX.sub("",s.replace("\r\n","\n").replace("\r","\n"))
def clean_output(s):
    return clean_text(_s(s)).replace("\t","    ")
def _clean_obj(o):
    if isinstance(o,str):return clean_text(o)
    if isinstance(o,list):return [_clean_obj(x) for x in o]
    if isinstance(o,dict):return {k:_clean_obj(v) for k,v in o.items()}
    return o
def sniff_image(data):
    if not data:return ""
    if data[:8]==b"\x89PNG\r\n\x1a\n":return "image/png"
    if data[:3]==b"\xff\xd8\xff":return "image/jpeg"
    if data[:6] in (b"GIF87a",b"GIF89a"):return "image/gif"
    if data[:4]==b"RIFF" and data[8:12]==b"WEBP":return "image/webp"
    return ""
IMAGE_EXT={"image/png":"png","image/jpeg":"jpg","image/gif":"gif","image/webp":"webp"}
def image_size(data):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:return int(im.width),int(im.height)
    except Exception:return 0,0
def image_as(asset,allowed=("image/png","image/jpeg")):
    """Asset bytes in a format the target writer understands (Word and core PDF paths do not take WebP/GIF reliably)."""
    data,mime=asset.get("data") or b"",asset.get("mime") or ""
    if mime in allowed:return data,mime
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            buf=io.BytesIO();im.convert("RGBA").save(buf,"PNG")
            return buf.getvalue(),"image/png"
    except Exception:return b"",""
def _asset_norm(uid,a):
    if not isinstance(a,dict):return None
    data=a.get("data")
    if not isinstance(data,(bytes,bytearray)):
        raw=a.get("data_b64") or a.get("data_url") or ""
        if isinstance(raw,str) and raw:
            try:data=base64.b64decode(raw.split(",",1)[-1] if raw.startswith("data:") else raw)
            except Exception:data=b""
        else:data=b""
    data=bytes(data)
    mime=sniff_image(data)
    if not mime or len(data)>MAX_IMAGE_BYTES:return None
    w,h=a.get("width") or 0,a.get("height") or 0
    if not w or not h:w,h=image_size(data)
    return {"uid":_s(uid),"mime":mime,"name":_s(a.get("name")),"data":data,"width":int(w or 0),"height":int(h or 0)}
def _ev_time(row):return _s(row.get("started_at") or row.get("created_at") or row.get("ended_at"))
def nice_ts(iso):
    iso=_s(iso).strip()
    if not iso:return ""
    try:
        d=datetime.fromisoformat(iso.replace("Z","+00:00"))
        if d.tzinfo is not None:d=d.astimezone(timezone.utc)
        return d.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:return iso[:19]
def nice_date(v):
    v=_s(v).strip()
    try:
        d=datetime.strptime(v[:10],"%Y-%m-%d")
        return f"{d.day} {d.strftime('%B %Y')}"
    except Exception:return v
def today():return datetime.now().strftime("%Y-%m-%d")
class _Ctx:
    """Resolves assets and evidence for one render: embedded copies first (imports, tests, previews), then the services."""
    def __init__(self,report,redact,raw=False):
        self.redact=bool(redact);self.raw=raw
        self._assets={};self._embedded_assets=report.get("_assets") or {}
        self._ev={}
        for row in report.get("_evidence") or []:
            if isinstance(row,dict) and row.get("uid"):self._ev[_s(row["uid"])]=row
        self._ev_loaded=set(self._ev)
        self.used=[];self._used_idx={}
        self._redactor=None
    def asset(self,uid):
        uid=_s(uid).strip()
        if not uid:return None
        if uid in self._assets:return self._assets[uid]
        a=_asset_norm(uid,self._embedded_assets.get(uid))
        if a is None:
            svc=_svc("reports_service")
            if svc is not None and hasattr(svc,"get_asset"):
                try:a=_asset_norm(uid,svc.get_asset(uid))
                except Exception:a=None
        self._assets[uid]=a
        return a
    def evidence(self,uid):
        uid=_s(uid).strip()
        if not uid:return None
        if uid in self._ev_loaded:return self._ev.get(uid)
        self._ev_loaded.add(uid)
        row=load_evidence(uid)
        # Rendering needs text every writer accepts; the JSON backup (raw) keeps the row exactly as stored.
        if row and not self.raw:row=_clean_obj(row)
        if row:self._ev[uid]=row
        return row
    def red(self,text):
        text=_s(text)
        if not self.redact or not text:return text
        if self._redactor is None:
            svc=_svc("terminal_service")
            self._redactor=getattr(svc,"redact_secrets",None) or False
        if not self._redactor:return text
        try:return self._redactor(text)[0]
        except Exception:return text
    def use(self,uid,snapshot=None):
        """Remember that the report references this evidence (for the appendices), keeping the first snapshot as a fallback."""
        uid=_s(uid).strip()
        if not uid:return None
        e=self._used_idx.get(uid)
        if e is None:
            e={"uid":uid,"row":self.evidence(uid),"snapshot":snapshot}
            self._used_idx[uid]=e;self.used.append(e)
        elif snapshot and not e["snapshot"]:e["snapshot"]=snapshot
        return e
def load_evidence(uid):
    svc=_svc("evidence_service")
    if svc is None:return None
    for name in ("get_evidence","get"):
        fn=getattr(svc,name,None)
        if not callable(fn):continue
        try:
            row=fn(uid)
            if isinstance(row,dict) and row.get("uid"):return row
        except Exception:pass
    return None
# ---- rich HTML subset -> neutral blocks ----
_INLINE={"strong":"b","b":"b","em":"i","i":"i","u":"u","s":"s","strike":"s","del":"s","code":"code","kbd":"code","samp":"code"}
_DROP=("script","style","iframe","object","embed","svg","form","head","title","noscript","template","math","select","textarea","button","audio","video","canvas")
_VOID=("br","hr","img","input","meta","link","wbr","col","source","area","base")
_BLOCK=("p","div","h1","h2","h3","h4","h5","h6","pre","blockquote","ul","ol","table","hr","img","figure","figcaption","li","section","article","dl","dt","dd")
_MAX_DEPTH=40
class _Node:
    __slots__=("tag","attrs","kids")
    def __init__(self,tag,attrs=None):self.tag=tag;self.attrs=attrs or {};self.kids=[]
class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root=_Node("#root");self.stack=[self.root];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in _DROP:self.skip+=1;return
        if self.skip:return
        n=_Node(tag,{k:(v or "") for k,v in attrs})
        self.stack[-1].kids.append(n)
        if tag not in _VOID and len(self.stack)<_MAX_DEPTH:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):
        if self.skip or tag in _DROP:return
        self.stack[-1].kids.append(_Node(tag,{k:(v or "") for k,v in attrs}))
    def handle_endtag(self,tag):
        if tag in _DROP:
            if self.skip:self.skip-=1
            return
        if self.skip:return
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:del self.stack[i:];break
    def handle_data(self,data):
        if not self.skip and data:self.stack[-1].kids.append(data)
def _safe_href(href):
    href=_s(href).strip()
    return href if re.match(r"(?i)^(https?://|mailto:)",href) and not re.search(r"[\x00-\x20\"<>]",href) else ""
def _cls(n):return n.attrs.get("class","").split()
def _is_redact(n):
    # A masked secret of the Notes editor is never meant for the deliverable: it prints as a redaction bar, like rpt-redact.
    return n.tag=="span" and any(c in ("rpt-redact","note-secret") for c in _cls(n))
_ALIGN={"center":"C","right":"R","justify":"J"}
def _align(n):return _ALIGN.get(n.attrs.get("data-align","").strip().lower(),"")
def _span_style(n,st):
    """Colour spans (data-color / data-bg / data-size): only pattern-checked values reach a writer."""
    a=n.attrs;out=None
    for key,attr in (("color","data-color"),("bg","data-bg")):
        v=a.get(attr,"").strip().lower()
        if re.fullmatch(r"#[0-9a-f]{6}",v):
            out=out or dict(st);out[key]=v
    v=a.get("data-size","").strip()
    if v.isdigit() and 8<=int(v)<=72:
        out=out or dict(st);out["size"]=int(v)
    return out or st
def _ws(s):return re.sub(r"[ \t\r\n\f ]+"," ",s)
def _inline(nodes,st,out):
    for n in nodes:
        if isinstance(n,str):
            t=_ws(n)
            if t:out.append(dict(st,text=t))
            continue
        tag=n.tag
        if tag=="br":out.append(dict(st,text="\n"))
        elif tag=="img":
            alt=_ws(n.attrs.get("alt","")).strip()
            out.append(dict(st,text=f"[{alt or 'image'}]"))
        elif tag=="hr":out.append(dict(st,text="\n"))
        elif _is_redact(n):out.append({"text":"","redact":True})
        elif tag=="span":
            cls=_cls(n)
            if "rpt-fref" in cls and re.fullmatch(r"[A-Za-z0-9_\-]{1,64}",n.attrs.get("data-finding","")):_inline(n.kids,dict(st,fref=n.attrs["data-finding"]),out)
            elif "note-ts" in cls:_inline(n.kids,dict(st,muted=True),out)
            else:_inline(n.kids,_span_style(n,st),out)
        elif tag in _INLINE:_inline(n.kids,dict(st,**{_INLINE[tag]:True}),out)
        elif tag=="a":
            href=_safe_href(n.attrs.get("href",""))
            _inline(n.kids,dict(st,href=href) if href else st,out)
        elif tag in _BLOCK or tag in ("tr","td","th"):
            if out and not out[-1].get("text","").endswith("\n"):out.append({"text":"\n"})
            _inline(n.kids,st,out)
            if out and not out[-1].get("text","").endswith("\n"):out.append({"text":"\n"})
        else:_inline(n.kids,st,out)
def _same_style(a,b):
    return not a.get("redact") and not b.get("redact") and all(a.get(k)==b.get(k) for k in ("b","i","u","s","code","href","color","bg","size","fref","muted"))
def _tidy(runs):
    out=[];space=True
    for r in runs:
        if r.get("redact"):out.append({"text":"","redact":True});space=False;continue
        t=r.get("text","")
        if space:t=t.lstrip(" ")
        t=re.sub(r" *\n *","\n",t)
        if not t:continue
        space=t.endswith((" ","\n"))
        if out and _same_style(out[-1],r):
            if out[-1]["text"].endswith("\n"):t=t.lstrip(" ")
            out[-1]["text"]+=t
        else:
            nr={k:v for k,v in r.items() if v and k!="text"};nr["text"]=t
            out.append(nr)
    while out and not out[0].get("redact") and not out[0]["text"].lstrip("\n "):out.pop(0)
    if out and not out[0].get("redact"):out[0]["text"]=out[0]["text"].lstrip("\n ")
    while out and not out[-1].get("redact") and not out[-1]["text"].rstrip("\n "):out.pop()
    if out and not out[-1].get("redact"):out[-1]["text"]=out[-1]["text"].rstrip("\n ")
    return out
def _pre_text(n):
    parts=[]
    def walk(x):
        for k in x.kids:
            if isinstance(k,str):parts.append(k)
            elif k.tag=="br":parts.append("\n")
            elif _is_redact(k):parts.append("[REDACTED]")
            else:walk(k)
    walk(n)
    t=clean_output("".join(parts))
    if t.startswith("\n"):t=t[1:]
    return t.rstrip()
_LANG_RX=re.compile(r"[A-Za-z0-9_+#.\-]{1,32}")
def pre_lang(n):
    """Language of a code block (pre[data-lang]); anything that is not a plain language token is ignored."""
    lang=n.attrs.get("data-lang","").strip()
    return lang.lower() if _LANG_RX.fullmatch(lang) else ""
def _find(n,tag):
    for k in n.kids:
        if isinstance(k,str):continue
        if k.tag==tag:return k
        r=_find(k,tag)
        if r is not None:return r
    return None
def _int(v,default,lo,hi):
    try:return max(lo,min(hi,int(float(v))))
    except Exception:return default
def _image_block(n,ctx):
    src=n.attrs.get("src","").strip();uid="";asset=None
    if src.startswith("rptasset:"):
        uid=src[9:].strip()
        asset=ctx.asset(uid) if ctx else None
    elif src.startswith("data:image/") and len(src)<MAX_IMAGE_BYTES*2:
        asset=_asset_norm("",{"data_url":src})
    width=n.attrs.get("data-width","").strip().lower();pct=0;px=0
    m=re.fullmatch(r"(\d{1,4})(%|px)?",width)
    if m:
        # A bare number up to 100 is a percentage of the text width (v1); anything else is CSS pixels.
        if m.group(2)=="px" or (not m.group(2) and int(m.group(1))>100):px=max(24,min(2000,int(m.group(1))))
        else:pct=max(10,min(100,int(m.group(1))))
    return {"t":"image","uid":uid,"alt":_ws(n.attrs.get("alt","")).strip(),"width":pct,"px":px,"asset":asset,"caption":"","align":""}
def _table_block(n):
    trs=[]
    def walk(x,head):
        for k in x.kids:
            if isinstance(k,str):continue
            if k.tag=="tr":trs.append((k,head))
            elif k.tag in ("thead","tbody","tfoot"):walk(k,head or k.tag=="thead")
    walk(n,False)
    raw=[]
    for tr,head in trs[:500]:
        cells=[]
        for k in tr.kids:
            if isinstance(k,str) or k.tag not in ("td","th"):continue
            runs=[];_inline(k.kids,{},runs);runs=_tidy(runs)
            cell={"runs":runs,"text":runs_text(runs),"header":bool(head or k.tag=="th"),"colspan":_int(k.attrs.get("colspan"),1,1,12),"rowspan":_int(k.attrs.get("rowspan"),1,1,50)}
            if _align(k) in ("C","R"):cell["align"]=_align(k)
            w=k.attrs.get("data-width","").strip()
            if w.isdigit() and 20<=int(w)<=2000:cell["_w"]=int(w)
            cells.append(cell)
        if cells:raw.append(cells)
    if not raw:return None
    # Lay the cells out on a rectangular grid; None marks a slot covered by a neighbour's colspan/rowspan.
    grid=[];carry={}
    for cells in raw:
        row=[];c=0;it=iter(cells)
        while True:
            if carry.get(c,0)>0:
                carry[c]-=1;row.append(None);c+=1;continue
            cell=next(it,None)
            if cell is None:break
            if c>=12:break
            cell["colspan"]=min(cell["colspan"],12-c)
            row.append(cell)
            for j in range(cell["colspan"]):
                if cell["rowspan"]>1:carry[c+j]=cell["rowspan"]-1
                if j:row.append(None)
            c+=cell["colspan"]
        grid.append(row)
    ncols=max(len(r) for r in grid)
    for i,row in enumerate(grid):
        while len(row)<ncols:
            row.append(None if carry_covers(grid,i,len(row)) else {"runs":[],"text":"","header":False,"colspan":1,"rowspan":1})
    for i,row in enumerate(grid):
        for cell in row:
            if cell:cell["rowspan"]=min(cell["rowspan"],len(grid)-i)
    header=all(c is None or c["header"] for c in grid[0]) and len(grid)>1
    kv=not header and len(grid)>0 and ncols>1 and all(r[0] is not None and r[0]["header"] for r in grid)
    # Column widths are a hint from the editor (CSS px): kept as proportions when every column of one row has one.
    widths=None
    for row in grid:
        ws=[c.get("_w") if c and c["colspan"]==1 else None for c in row]
        if all(ws):
            tot=float(sum(ws));widths=[max(0.06,w/tot) for w in ws];break
    for row in grid:
        for c in row:
            if c:c.pop("_w",None)
    blk={"t":"table","rows":grid,"header":header,"widths":widths}
    if kv:blk["kv"]=True
    return blk
def carry_covers(grid,i,c):
    for r in range(i-1,-1,-1):
        if c<len(grid[r]) and grid[r][c] is not None:return grid[r][c]["rowspan"]>i-r
    return False
def _figure_block(n,ctx):
    uid=n.attrs.get("data-evidence","").strip()
    cap=_find(n,"figcaption");pre=_find(n,"pre");img=_find(n,"img")
    caption=""
    if cap is not None:
        runs=[];_inline(cap.kids,{},runs);caption=runs_text(_tidy(runs)).replace("\n"," ")
    blk={"t":"figure","evidence":uid,"caption":caption,"pre":_pre_text(pre) if pre is not None else "","image":_image_block(img,ctx) if img is not None else None,"truncated":0}
    if ctx:
        blk["caption"]=ctx.red(blk["caption"]);blk["pre"]=ctx.red(blk["pre"])
        ctx.use(uid,{"caption":blk["caption"],"pre":blk["pre"],"image":blk["image"]})
    return blk
def _mixed(nodes,ctx):
    out=[];runs=[]
    def flush():
        r=_tidy(runs);del runs[:]
        if r:out.append({"t":"p","runs":r})
    for n in nodes:
        if isinstance(n,str) or n.tag not in _BLOCK:
            _inline([n],{},runs);continue
        tag=n.tag
        if tag=="img":
            # An image in the middle of a sentence still becomes its own block: no writer can flow text around it reliably.
            flush();out.append(_image_block(n,ctx));continue
        flush()
        cls=_cls(n)
        if tag in ("div","aside","blockquote") and ("note-callout" in cls or (tag!="blockquote" and n.attrs.get("data-callout"))):
            out.append(_callout_block(n,ctx));continue
        if tag=="div" and "rpt-widget" in cls:
            w=n.attrs.get("data-widget","").strip().lower()
            if w in WIDGETS:out.append({"t":"widget","name":w})
            continue
        if tag=="figure" and "rpt-cmd" in cls:
            b=_cmd_block(n,ctx)
            if b:out.append(b)
            continue
        if tag=="div" and "cmd-card" in cls:
            b=_cmd_card_block(n,ctx)
            if b:out.append(b)
            continue
        if tag in ("h1","h2","h3","h4","h5","h6"):
            r=[];_inline(n.kids,{},r);r=_tidy(r)
            if r:out.append(_aligned({"t":"h","level":3 if tag in ("h1","h2","h3") else 4,"runs":r},n))
        elif tag=="pre":
            t=_pre_text(n)
            if t.strip():out.append({"t":"pre","text":ctx.red(t) if ctx else t,"lang":pre_lang(n)})
        elif tag=="blockquote":
            b=_mixed(n.kids,ctx)
            if b:out.append(_aligned({"t":"quote","blocks":b},n))
        elif tag in ("ul","ol"):
            items=[];check=tag=="ul" and "note-checklist" in cls
            for k in n.kids:
                if isinstance(k,str):
                    if k.strip():items.append({"runs":[{"text":_ws(k).strip()}],"blocks":[]})
                    continue
                b=_mixed(k.kids if k.tag=="li" else [k],ctx)
                if not b:continue
                if k.tag in ("ul","ol") and items:items[-1]["blocks"].extend(b);continue
                if b[0]["t"]=="p":it={"runs":b[0]["runs"],"blocks":b[1:]}
                else:it={"runs":[],"blocks":b}
                if check:it["checked"]=k.attrs.get("data-checked","").strip().lower() in ("1","true","checked","yes")
                items.append(it)
            if items and tag=="ul" and not check:check=_text_checklist(items)
            if items:
                blk={"t":"list","ordered":tag=="ol","items":items}
                if check:blk["check"]=True
                start=n.attrs.get("start","").strip()
                if tag=="ol" and start.isdigit() and 1<int(start)<=9999:blk["start"]=int(start)
                out.append(blk)
        elif tag=="table":
            t=_table_block(n)
            if t:
                if "note-table-head" in cls and not t.get("header"):t["kv"]=True
                out.append(t)
        elif tag=="hr":out.append({"t":"hr"})
        elif tag=="figure" and ("rpt-ev" in cls or n.attrs.get("data-evidence")):
            out.append(_figure_block(n,ctx))
        elif tag=="figure" and _find(n,"img") is not None and _find(n,"pre") is None:
            # Pictures and flattened drawings of the Notes editor: the <img>, its caption and where it sits.
            img=_image_block(_find(n,"img"),ctx);cap=_find(n,"figcaption")
            if cap is not None:
                r=[];_inline(cap.kids,{},r);img["caption"]=runs_text(_tidy(r)).replace("\n"," ")
            img["align"]="C" if "note-align-center" in cls else "R" if ("note-align-right" in cls or "note-embed-float-right" in cls) else ""
            out.append(img)
        elif tag=="p":
            b=_mixed_p(n,ctx)
            for x in b:out.append(_aligned(x,n) if x["t"]=="p" else x)
        elif tag=="figcaption":
            r=[];_inline(n.kids,{"i":True},r);r=_tidy(r)
            if r:out.append({"t":"p","runs":r})
        else:out.extend(_mixed(n.kids,ctx))
    flush()
    return out
def _aligned(b,n):
    a=_align(n)
    if a:b["align"]=a
    return b
def _mixed_p(n,ctx):
    """A paragraph element: its runs, with any image inside lifted out as a block of its own."""
    return _mixed(n.kids,ctx)
_BOX_RX=re.compile(r"^\s*(?:([\u2610])|([\u2611\u2612\u2713\u2714])|\[( |x|X)\])\s+")
def _text_checklist(items):
    """A plain list whose every item starts with a box character or [ ] / [x] is a checklist too (pasted Markdown, old notes)."""
    hits=[]
    for it in items:
        t=it["runs"][0].get("text","") if it["runs"] and not it["runs"][0].get("redact") else ""
        m=_BOX_RX.match(t)
        if not m:return False
        hits.append((it,m))
    for it,m in hits:
        it["checked"]=bool(m.group(2) or (m.group(3) or "").lower()=="x")
        it["runs"][0]=dict(it["runs"][0],text=it["runs"][0]["text"][m.end():])
    return True
def _mask_runs(runs):
    """Credential lines: the bold label stays, the value becomes one redaction bar."""
    out=[];masked=False
    for r in runs:
        if r.get("redact"):
            if not masked:out.append({"text":"","redact":True});masked=True
        elif r.get("b") and not masked:out.append(r)
        elif r.get("text","").strip():
            if not masked:out.append({"text":"","redact":True});masked=True
    return out
def _mask_blocks(blocks):
    out=[]
    for b in blocks:
        if b["t"] in ("p","h"):out.append(dict(b,runs=_mask_runs(b["runs"])))
        elif b["t"]=="list":out.append(dict(b,items=[dict(it,runs=_mask_runs(it["runs"]),blocks=_mask_blocks(it["blocks"])) for it in b["items"]]))
        elif b["t"]=="quote":out.append(dict(b,blocks=_mask_blocks(b["blocks"])))
        elif b["t"] in ("pre","table","figure","cmd"):out.append({"t":"p","runs":[{"text":"","redact":True}]})
        else:out.append(b)
    return out
def _callout_block(n,ctx):
    kind=n.attrs.get("data-callout","").strip().lower()
    if kind=="vulnerability":kind="vuln"
    if kind not in CALLOUT_LABELS:kind="info"
    blk={"t":"callout","kind":kind,"label":CALLOUT_LABELS[kind],"sev":"","cvss":"","title":"","blocks":_mixed(n.kids,ctx)}
    if kind in ("finding","vuln"):
        s=n.attrs.get("data-sev","").strip().lower()
        if s in SEV_RANK:blk["sev"]=s
        c=n.attrs.get("data-cvss","").strip()
        if re.fullmatch(r"(?:10(?:\.0)?|\d(?:\.\d)?)",c):blk["cvss"]=f"{float(c):.1f}"
    if blk["blocks"] and blk["blocks"][0]["t"]=="h":
        blk["title"]=runs_text(blk["blocks"][0]["runs"]).replace("\n"," ");blk["blocks"]=blk["blocks"][1:]
    # Credentials are masked whenever the export masks secrets (the default): the label stays, the value does not.
    if kind=="credential" and (ctx is None or ctx.redact):blk["blocks"]=_mask_blocks(blk["blocks"]);blk["masked"]=True
    return blk
_CMD_ATTR_RX=re.compile(r"[A-Za-z0-9 ._+#/(),\-]{1,200}")
def _cmd_block(n,ctx):
    """figure.rpt-cmd - a saved command: title, optional description, the command itself."""
    cap=_find(n,"figcaption");pre=_find(n,"pre");title=""
    if cap is not None:
        r=[];_inline(cap.kids,{},r);title=runs_text(_tidy(r)).replace("\n"," ")
    text=_pre_text(pre) if pre is not None else ""
    desc=_mixed([k for k in n.kids if isinstance(k,str) or k.tag not in ("figcaption","pre")],ctx)
    if not text.strip() and not title and not desc:return None
    def attr(name,limit):
        v=n.attrs.get(name,"").strip()
        return v[:limit] if _CMD_ATTR_RX.fullmatch(v) else ""
    kind=attr("data-type",40);cat=" / ".join(x for x in (attr("data-cat",80),attr("data-sub",80)) if x)
    return {"t":"cmd","title":title or "Command","kind":kind,"category":cat,"desc":desc,"text":ctx.red(text) if ctx else text}
def _find_cls(n,name):
    for k in n.kids:
        if isinstance(k,str):continue
        if name in _cls(k):return k
        r=_find_cls(k,name)
        if r is not None:return r
    return None
def _node_text(n):
    r=[];_inline(n.kids,{},r)
    return runs_text(_tidy(r))
def _cmd_card_block(n,ctx):
    """The Notes editor's own command card markup (div.cmd-card), should it ever reach an exporter unconverted."""
    title=_find_cls(n,"cmd-card-title");code=_find_cls(n,"cmd-card-code");kind=_find_cls(n,"cmd-card-type")
    text=_pre_text(code) if code is not None else ""
    if not text.strip():return None
    return {"t":"cmd","title":(_node_text(title).replace("\n"," ") if title is not None else "") or "Command","kind":_node_text(kind)[:40] if kind is not None else "","category":"","desc":[],"text":ctx.red(text) if ctx else text}
def parse_rich(markup,ctx=None):
    """Sanitised rich HTML -> block list. Never raises: unparseable input degrades to plain paragraphs."""
    markup=clean_text(_s(markup))
    if not markup.strip():return []
    try:
        t=_Tree();t.feed(markup);t.close()
        return _mixed(t.root.kids,ctx)
    except Exception:
        text=html.unescape(re.sub(r"<[^>]*>"," ",markup))
        return [{"t":"p","runs":[{"text":p.strip()}]} for p in re.split(r"\n\s*\n",text) if p.strip()]
def runs_text(runs):
    return "".join("[REDACTED]" if r.get("redact") else r.get("text","") for r in runs or [])
def blocks_text(blocks,indent=""):
    out=[]
    for b in blocks or []:
        t=b["t"]
        if t in ("p","h"):out.append(indent+runs_text(b["runs"]))
        elif t=="label":out.append(indent+b["text"])
        elif t=="pre":out.append(b["text"])
        elif t=="quote":out.append(blocks_text(b["blocks"],indent+"> "))
        elif t=="list":
            for i,it in enumerate(b["items"]):
                out.append(f"{indent}{str(i+1)+'.' if b['ordered'] else '-'} {runs_text(it['runs'])}")
                if it["blocks"]:out.append(blocks_text(it["blocks"],indent+"  "))
        elif t=="table":
            for row in b["rows"]:out.append(indent+" | ".join(c["text"] for c in row if c))
        elif t=="image":out.append(indent+f"[Image: {b.get('caption') or b.get('alt') or 'screenshot'}]")
        elif t=="callout":
            out.append(indent+callout_head(b));out.append(blocks_text(b["blocks"],indent))
        elif t=="cmd":
            out.append(indent+b["title"]);out.append(blocks_text(b.get("desc"),indent));out.append(b["text"])
        elif t in ("dashboard","charts","matrix","timeline"):out.append(blocks_text(legacy_blocks([b]),indent))
        elif t=="figure":
            out.append(indent+f"[Evidence: {b.get('caption') or b.get('evidence')}]")
            if b.get("pre"):out.append(b["pre"])
    return "\n".join(x for x in out if x)
def rich_text(markup):return blocks_text(parse_rich(markup))
def callout_head(b):
    """Label line of a callout: kind, then severity and CVSS for findings and vulnerabilities, then its title."""
    parts=[b["label"]]
    if b.get("sev"):parts.append(SEV_LABELS[b["sev"]])
    if b.get("cvss"):parts.append("CVSS "+b["cvss"])
    head=" · ".join(parts)
    return f"{head}: {b['title']}" if b.get("title") else head
# ---- render model ----
def effective_options(report,options=None):
    ro=report.get("options") if isinstance(report.get("options"),dict) else {}
    br=report.get("branding") if isinstance(report.get("branding"),dict) else {}
    o={"page_size":"A4","include_toc":True,"include_appendices":True,"number_sections":True,"finding_id_prefix":"F-","include_cover":br.get("show_cover",True) is not False,"redact":True,"findings_status":None,
        "theme":"","font":"","cover_style":"","embed_fonts":False,"findings_new_page":False,"pdf_engine":"fallback"}
    for src in (ro,options or {}):
        for k,v in src.items():
            if v is not None:o[k]=v
    o["page_size"]="Letter" if _s(o.get("page_size")).strip().lower()=="letter" else "A4"
    for k in ("include_toc","include_appendices","number_sections","include_cover","redact","embed_fonts","findings_new_page"):o[k]=bool(o[k])
    for k in ("theme","font","cover_style"):o[k]=_s(o.get(k)).strip().lower()[:24]
    o["pdf_engine"]=o["pdf_engine"] if o.get("pdf_engine") in ("auto","native","fallback") else "fallback"
    o["finding_id_prefix"]=_s(o.get("finding_id_prefix"))[:12]
    fs=o.get("findings_status")
    fs=[s for s in fs if s in STATUSES] if isinstance(fs,(list,tuple)) else None
    o["findings_status"]=fs if fs and len(fs)<len(STATUSES) else None
    return o
def finding_number(prefix,index,total):
    # Same shape as ReportCore.findingNumber in the UI, so the exported IDs match what the author sees.
    return f"{prefix}{index:02d}"
def _c(text="",**kw):
    c={"text":_s(text),"runs":None,"header":False,"colspan":1,"rowspan":1}
    c.update(kw)
    return c
def _hc(text,**kw):return _c(text,header=True,**kw)
def _sev_cell(s,align="C",**kw):return _c(SEV_LABELS[s],fill=SEV_COLORS[s],color=SEV_ON[s],bold=True,align=align,sev=s,**kw)
def _table(rows,widths=None,header=True,**kw):
    t={"t":"table","rows":rows,"widths":widths,"header":header}
    t.update(kw)
    return t
def _p(text,**st):return {"t":"p","runs":[dict(st,text=_s(text))]}
def _affected_text(f,sep=", "):
    out=[]
    for a in f.get("affected") or []:
        if isinstance(a,str):
            if a.strip():out.append(a.strip())
            continue
        if not isinstance(a,dict):continue
        name,value=_s(a.get("name")).strip(),_s(a.get("value")).strip()
        out.append(f"{name} ({value})" if name and value and name!=value else (value or name))
    return sep.join(x for x in out if x)
def _affected_names(f):
    """Short form for overview tables: the asset's name where it has one, its value otherwise."""
    out=[]
    for a in f.get("affected") or []:
        if isinstance(a,str):t=a.strip()
        elif isinstance(a,dict):t=_s(a.get("name")).strip() or _s(a.get("value")).strip()
        else:t=""
        if t and t not in out:out.append(t)
    return out
# ---- report scope from Targets: linked targets (snapshots), value references in rich text, the generated scope table ----
ENGAGEMENT_LABELS={"not_started":"Not started","in_progress":"In progress","compromised":"Compromised","reported":"Reported"}
_SECRET_KEY_RX=re.compile(r"pass|pwd|secret|token|hash|key|cred|cookie|session|private|otp|pin|user|login",re.I)
_ADDRESS_KEY_RX=re.compile(r"ip|url|uri|domain|host|fqdn|address|cidr|subnet|network|range",re.I)
_TV_RX=re.compile(r'<span class="rpt-tv" data-target="([A-Za-z0-9_-]{1,64})" data-key="([^"<>]{1,480})">([^<]*)</span>')
TV_WITHHELD="[withheld]"
def is_secret_key(key):return bool(_SECRET_KEY_RX.search(_s(key)))
def report_links(report):
    """The report's linked targets as the writers may show them: a protected value only where its key was explicitly allowed on that link."""
    out=[]
    for l in report.get("targets") or []:
        if not isinstance(l,dict) or not _s(l.get("uid")).strip():continue
        snap=l.get("snapshot") if isinstance(l.get("snapshot"),dict) else {}
        allow={_s(k).lower() for k in l.get("allowed_secret_keys") or [] if isinstance(k,str)}
        vals={}
        for k,v in (snap.get("values").items() if isinstance(snap.get("values"),dict) else ()):
            k=_s(k).strip();v=_s(v).strip()
            if k and v and (not is_secret_key(k) or k.lower() in allow):vals[k]=v
        eng=_s(snap.get("engagement_status")).strip().lower()
        out.append({"uid":_s(l["uid"]).strip(),"name":_s(l.get("name")).strip() or "Target","values":vals,"status":eng if eng in ENGAGEMENT_LABELS else "not_started","state":_s(l.get("state"))})
    return out
def link_value(link,key):
    key=_s(key)
    if key=="@name":return link["name"]
    if key=="@status":return ENGAGEMENT_LABELS[link["status"]]
    for k,v in link["values"].items():
        if k==key or k.lower()==key.lower():return v
    return None
def resolve_target_values(markup,by_uid):
    """Give every target-value reference its current text from the link snapshot. One that no longer resolves keeps its last text,
    unless its key is a protected one: that is never exported from stale text."""
    markup=_s(markup)
    if "rpt-tv" not in markup:return markup
    def one(m):
        key=html.unescape(m.group(2));l=by_uid.get(m.group(1))
        v=link_value(l,key) if l else None
        if v is None:return html.escape(TV_WITHHELD) if is_secret_key(key) else m.group(3)
        return html.escape(v,quote=False)
    return _TV_RX.sub(one,markup)
def scope_columns(links,chosen=None):
    """Value keys shown as columns of the scope table: the user's choice, else the address-like keys the linked targets have (plus the status)."""
    if isinstance(chosen,(list,tuple)):
        cols=[]
        for k in chosen:
            k=_s(k).strip()
            if k and k!="@name" and k not in cols:cols.append(k)
        return cols[:12]
    keys=[]
    for l in links:
        for k in l["values"]:
            if k not in keys and not is_secret_key(k):keys.append(k)
    addr=[k for k in keys if _ADDRESS_KEY_RX.search(k)]
    return (addr or keys)[:3]+["@status"]
def _scope_table(links,chosen=None):
    if not links:return []
    cols=scope_columns(links,chosen)
    # A column nobody has a value for would only be a row of dashes.
    cols=[k for k in cols if k=="@status" or any(link_value(l,k) for l in links)]
    rows=[[_hc("#"),_hc("Target")]+[_hc("Status" if k=="@status" else k) for k in cols]]
    for i,l in enumerate(links):
        rows.append([_c(i+1,align="C"),_c(l["name"],bold=True)]+[_c(link_value(l,k) or "-",mono=k!="@status") for k in cols])
    # The status is a short word; the value columns share what the name leaves.
    n=len(cols);st=0.18 if "@status" in cols else 0;nv=n-(1 if st else 0);name_w=0.92-st if not nv else (0.3 if nv<=2 else 0.22)
    return [_table(rows,[0.06,name_w+0.02]+[st if k=="@status" else (0.92-name_w-st)/nv for k in cols],scope=True)]
def _finding_links(f,by_uid):
    """[(link, [values to show])] for the targets a finding affects, in the finding's order."""
    out=[]
    for e in f.get("targets") or []:
        if not isinstance(e,dict):continue
        l=by_uid.get(_s(e.get("uid")))
        if not l:continue
        vals=[]
        for k in e.get("keys") or []:
            v=link_value(l,k) if _s(k) not in ("@name",) else None
            if v and v not in vals:vals.append(v)
        out.append((l,vals))
    return out
def _placeholders(report,meta,branding,findings):
    counts=severity_counts(findings)
    vals={k:_s(meta.get(k)) for k in ("client","client_contact","engagement","project_code","report_type","start_date","end_date","report_date","classification","version","authors","reviewers","methodology")}
    vals.update({"company":_s(branding.get("company")),"title":_s(report.get("title")),"report_title":_s(report.get("title")),"total_findings":str(len(findings)),"findings_total":str(len(findings)),
        "testers":", ".join(_s(t.get("name")) for t in meta.get("testers") or [] if isinstance(t,dict) and t.get("name")),"today":today()})
    for s in SEVERITIES:vals[s+"_count"]=str(counts[s])
    return vals
_PH_RX=re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
def substitute(text,vals,escape=False):
    """Replace {{token}} from the report's own meta; unknown tokens are left visible so the author notices them."""
    def rep(m):
        k=m.group(1).lower()
        if k not in vals or vals[k]=="":return m.group(0)
        return html.escape(vals[k]) if escape else vals[k]
    return _PH_RX.sub(rep,_s(text))
def severity_counts(findings):
    counts={s:0 for s in SEVERITIES}
    for f in findings or []:counts[sev(f.get("severity"))]+=1
    return counts
def _cvss_text(f):
    sc=f.get("cvss_score")
    try:return "" if sc is None or sc=="" else f"{float(sc):.1f}"
    except Exception:return ""
def cvss_rating(f,cves):
    """(version, vector) of the finding's score. The finding's own calculator is CVSS 3.1; a score without a vector that equals a CVE's
    4.0 (or 2.0/3.0) rating is that CVE's rating and is labelled with its version, with the CVE's vector."""
    vector=_s(f.get("cvss_vector")).strip();score=_cvss_text(f)
    if vector:
        m=re.match(r"(?i)^CVSS:(\d\.\d)/",vector)
        return (m.group(1) if m else "3.1"),vector
    if not score:return "3.1",""
    for c in cves:
        if c["cvss"]==score and c["cvss_version"] and c["cvss_version"]!="3.1":return c["cvss_version"],c["cvss_vector"]
    return "",""
def _ev_caption(row):
    parts=[]
    if row.get("command"):parts.append("$ "+_s(row["command"]))
    if row.get("exit_code") is not None and _s(row.get("exit_code"))!="":parts.append(f"exit {row['exit_code']}")
    ts=nice_ts(_ev_time(row))
    if ts:parts.append(ts)
    return " — ".join(parts)
def _cut(text,limit):
    lines=text.split("\n");extra=0
    if len(lines)>limit:extra=len(lines)-limit;lines=lines[:limit]
    lines=[l if len(l)<=LINE_CHARS else l[:LINE_CHARS]+" [...]" for l in lines]
    return "\n".join(lines),extra
def _evidence_figure(ctx,entry,caption="",limit=FIGURE_LINES):
    """Figure/image block for one referenced evidence item, from the live row when it exists, else from its snapshot."""
    row,snap=entry.get("row"),entry.get("snapshot") or {}
    if row:
        meta=row.get("meta") if isinstance(row.get("meta"),dict) else {}
        title=_s(row.get("title")).strip()
        if row.get("kind")=="image":
            a=ctx.asset(meta.get("asset_uid"))
            return {"t":"image","uid":_s(meta.get("asset_uid")),"alt":caption or title,"width":0,"asset":a,"caption":caption or title,"evidence":entry["uid"]}
        text=clean_output(row.get("content"))
        if not text.strip() and isinstance(row.get("events"),list):
            text=clean_output("".join(("$ "+_s(e.get("data"))+"\n") if e.get("kind")=="cmd" else _s(e.get("data")) for e in row["events"] if isinstance(e,dict) and e.get("kind") in ("cmd","out")))
        cmd=_s(row.get("command")).strip()
        if cmd and row.get("kind")!="recording":text="$ "+cmd+"\n"+text
        text,extra=_cut(ctx.red(text).rstrip(),limit)
        info=[]
        if row.get("exit_code") is not None and _s(row.get("exit_code"))!="":info.append(f"exit {row['exit_code']}")
        if row.get("target"):info.append(_s(row["target"]))
        ts=nice_ts(_ev_time(row))
        if ts:info.append(ts)
        cap=ctx.red(caption or title or cmd) or "Evidence"
        if not caption and cmd and len(cap)>96 and title in ("",cmd,cmd.splitlines()[0][:200]):cap=cap[:92].rstrip()+" ..."
        return {"t":"figure","evidence":entry["uid"],"caption":cap,"info":" · ".join(info),"pre":text,"image":None,"truncated":extra}
    if snap.get("image") and not snap.get("pre"):
        img=dict(snap["image"]);img["caption"]=caption or snap.get("caption") or img.get("alt") or "";img["evidence"]=entry["uid"]
        return img
    text,extra=_cut(_s(snap.get("pre")),limit)
    return {"t":"figure","evidence":entry["uid"],"caption":caption or snap.get("caption") or "Evidence","info":"","pre":text,"image":snap.get("image"),"truncated":extra}
def _commands_of(ctx):
    """Every command the referenced evidence shows, oldest first: one per command capture, one per 'cmd' event of a recording."""
    out=[]
    for e in ctx.used:
        row=e.get("row")
        if not row:
            cap=_s((e.get("snapshot") or {}).get("caption"))
            m=re.match(r"\$\s+(.+?)(?:\s+—\s+exit\s+(-?\d+))?(?:\s+—\s+(.+))?$",cap)
            if m:out.append({"ts":_s(m.group(3)),"command":m.group(1),"exit_code":m.group(2) if m.group(2) is not None else "","target":"","uid":e["uid"]})
            continue
        if row.get("kind")=="recording" and isinstance(row.get("events"),list):
            cur=None
            for ev in row["events"]:
                if not isinstance(ev,dict):continue
                if ev.get("kind")=="cmd" and _s(ev.get("data")).strip():
                    cur={"ts":_s(ev.get("ts")),"command":ctx.red(clean_output(ev.get("data")).strip()),"exit_code":"","target":_s(row.get("target")),"uid":e["uid"],"source":"recording"}
                    out.append(cur)
                elif ev.get("kind")=="exit" and cur is not None:cur["exit_code"]=_s(ev.get("data")).strip()
        elif _s(row.get("command")).strip():
            ec=row.get("exit_code")
            out.append({"ts":_ev_time(row),"command":ctx.red(clean_output(row["command"]).strip()),"exit_code":"" if ec is None else _s(ec),"target":_s(row.get("target")),"uid":e["uid"],"source":_s(row.get("source")).strip().lower()})
    out.sort(key=lambda c:c["ts"] or "￿")
    return out
_TOOL_SKIP=("sudo","time","proxychains","proxychains4","nohup","env","stdbuf","timeout","watch","doas","command","exec","torsocks","unbuffer")
def tool_of(command):
    for tok in re.split(r"\s+",_s(command).strip()):
        if not tok or "=" in tok and not tok.startswith(("/",".")) or tok.startswith("-") or tok.isdigit():continue
        base=re.split(r"[\\/]",tok)[-1].lower()
        base=re.sub(r"\.(exe|py|sh|ps1|pl|rb|bat|cmd)$","",base)
        if base in _TOOL_SKIP or not base:continue
        return base if re.fullmatch(r"[a-z0-9_.+\-]{1,40}",base) else ""
    return ""
def _has_generated(blocks):return any(b["t"] in ("table","pre","figure") for b in blocks)
def _auto_on(section,blocks,always):
    opt=(section.get("options") or {}).get("auto") if isinstance(section.get("options"),dict) else None
    if isinstance(opt,bool):return opt
    return True if always else not _has_generated(blocks)
_CVE_ID_RX=re.compile(r"^CVE-\d{4}-\d{4,19}$")
CVE_URL="https://nvd.nist.gov/vuln/detail/"
KEV_LABEL="Known exploited"
def cve_list(v):
    """The CVEs of a finding as every writer shows them: valid ids only, each once, with the NVD link and its own CVSS text."""
    out=[];seen=set()
    for e in v if isinstance(v,(list,tuple)) else []:
        if isinstance(e,str):e={"id":e}
        if not isinstance(e,dict):continue
        cid=_s(e.get("id")).strip().upper()
        if not _CVE_ID_RX.match(cid) or cid in seen:continue
        seen.add(cid)
        version=_s(e.get("cvss_version")).strip()
        out.append({"id":cid,"url":CVE_URL+cid,"title":_s(e.get("title")).strip(),"cvss":_cvss_text(e),"cvss_version":version if version in ("2.0","3.0","3.1","4.0") else "","cvss_vector":_s(e.get("cvss_vector")).strip(),"kev":e.get("kev") is True})
    return out
def _cve_runs(cves):
    runs=[]
    for i,c in enumerate(cves):
        if i:runs.append({"text":", "})
        runs.append({"text":c["id"],"href":c["url"]})
        if c["kev"]:runs.append({"text":f" ({KEV_LABEL})","b":True})
    return runs
def _cve_details(f):
    """A CVE's own rating is listed only where it says something the finding's rating does not."""
    cves=f["cves"]
    if not any((c["cvss"] and c["cvss"]!=f["cvss"]) or (c["cvss_vector"] and c["cvss_vector"]!=f["cvss_vector"]) for c in cves):return []
    rows=[[_hc("CVE"),_hc("CVSS"),_hc("Title")]]
    for c in cves:
        rating=(c["cvss"]+(f" (v{c['cvss_version']})" if c["cvss_version"] else "")) if c["cvss"] else "-"
        rows.append([_c(c["id"],runs=[{"text":c["id"],"href":c["url"]}]),_c(rating+("\n"+c["cvss_vector"] if c["cvss_vector"] else "")),_c((c["title"] or "-")+(f" ({KEV_LABEL})" if c["kev"] else ""))])
    return [{"t":"label","text":"CVE Details"},_table(rows,[0.18,0.46,0.36])]
def _finding_blocks(ctx,f,vals):
    s=f["severity"]
    out=[{"t":"finding","id":f["number"],"title":f["title"],"severity":s,"anchor":f["anchor"],"cvss":f["cvss"],"status":f["status"],"f":f}]
    rows=[[_hc("Severity"),_sev_cell(s,align="L"),_hc("Status"),_c(STATUS_LABELS.get(f["status"],f["status"].title()))],
          [_hc(f["cvss_label"]),_c(f["cvss"] or "Not scored",bold=bool(f["cvss"])),_hc("Likelihood"),_c(f["likelihood"].title() or "-")]]
    if f["cvss_vector_any"]:rows.append([_hc("CVSS vector"),_c(f["cvss_vector_any"],mono=True,colspan=3),None,None])
    if f["cwe"] or f["owasp"]:rows.append([_hc("CWE"),_c(f["cwe"] or "-"),_hc("OWASP"),_c(f["owasp"] or "-")])
    if f["cves"]:rows.append([_hc("CVE"),_c(runs_text(_cve_runs(f["cves"])),runs=_cve_runs(f["cves"]),colspan=3),None,None])
    if f["affected_text"]:rows.append([_hc("Affected"),_c(f["affected_text"],colspan=3),None,None])
    out.append(_table(rows,[0.17,0.33,0.17,0.33],header=False,kv=True,fmeta=True))
    out.extend(_cve_details(f))
    for key,label in (("description","Description"),("impact","Impact"),("steps","Steps to Reproduce"),("remediation","Remediation")):
        if f[key]:
            out.append({"t":"label","text":label});out.extend(f[key])
    if f["evidence_blocks"]:
        out.append({"t":"label","text":"Evidence"});out.extend(f["evidence_blocks"])
    if f["references"]:
        out.append({"t":"label","text":"References"})
        out.append({"t":"list","ordered":False,"items":[{"runs":[{"text":r,"href":r} if _safe_href(r) else {"text":r}],"blocks":[]} for r in f["references"]]})
    if f["retest_notes"]:
        out.append({"t":"label","text":"Retest Notes"})
        out.extend(_p(p) for p in f["retest_notes"].split("\n") if p.strip())
    out.append({"t":"finding_end"})
    return out
def prepare(report,options=None):
    """Report dict (contract shape) -> ordered document every writer consumes. Pure apart from asset/evidence lookups."""
    if not isinstance(report,dict):raise ValueError("Report not found.")
    embedded_assets=report.get("_assets")
    report=_clean_obj({k:v for k,v in report.items() if k!="_assets"})
    report["_assets"]=embedded_assets or {}
    opts=effective_options(report,options)
    ctx=_Ctx(report,opts["redact"])
    links=report_links(report);by_link={l["uid"]:l for l in links}
    tv=lambda markup:resolve_target_values(markup,by_link)
    meta=dict(report.get("meta") or {}) if isinstance(report.get("meta"),dict) else {}
    branding=dict(report.get("branding") or {}) if isinstance(report.get("branding"),dict) else {}
    for k in ("client","client_contact","engagement","project_code","report_type","start_date","end_date","report_date","rules_of_engagement","methodology","classification","version","authors","reviewers"):meta[k]=_s(meta.get(k)).strip()
    for k in ("testers","scope_in","scope_out","distribution"):meta[k]=meta.get(k) if isinstance(meta.get(k),list) else []
    for k in ("company","banner","footer","cover_subtitle","logo_asset"):branding[k]=_s(branding.get(k)).strip()
    dz=design.resolve(branding,opts)
    accent=dz["accent"];secondary=dz["secondary"]
    title=_s(report.get("title")).strip() or "Penetration Test Report"
    if not meta["report_date"]:meta["report_date"]=today()
    # Finding numbers come from the full list so an export filtered to "open" keeps the IDs the client already knows.
    raw=[f for f in report.get("findings") or [] if isinstance(f,dict)]
    raw.sort(key=lambda f:(_int(f.get("position"),0,-10**9,10**9),_int(f.get("id"),0,0,10**12)))
    vals=_placeholders(report,meta,branding,raw)
    title=substitute(title,vals)
    findings=[]
    for i,f in enumerate(raw):
        status=_s(f.get("status")).strip().lower() or "open"
        if opts["findings_status"] and status not in opts["findings_status"]:continue
        number=finding_number(opts["finding_id_prefix"],i+1,len(raw))
        # Linked targets come first in "Affected": the target's name with the values chosen for this finding.
        flinks=_finding_links(f,by_link)
        typed=[a for a in f.get("affected") or [] if isinstance(a,(dict,str))]
        f=dict(f,affected=[{"target_id":"","name":l["name"],"value":", ".join(vals)} for l,vals in flinks]+typed)
        aff_items=[{"name":l["name"],"value":v} for l,vals in flinks for v in (vals or [""])]+[a for a in typed if isinstance(a,dict)]
        pf={"number":number,"index":i+1,"uid":_s(f.get("uid")),"title":substitute(_s(f.get("title")).strip() or "Untitled finding",vals),"severity":sev(f.get("severity")),"status":status,
            "cvss":_cvss_text(f),"cvss_vector":_s(f.get("cvss_vector")).strip(),"cwe":_s(f.get("cwe")).strip(),"owasp":_s(f.get("owasp")).strip(),"likelihood":_s(f.get("likelihood")).strip().lower(),
            "references":[_s(r).strip() for r in f.get("references") or [] if _s(r).strip()],"affected_text":_affected_text(f),"affected_list":[x for x in _affected_text(f,"\n").split("\n") if x],"affected_names":_affected_names(f),
            "tags":[_s(t) for t in f.get("tags") or [] if _s(t).strip()],"retest_notes":_s(f.get("retest_notes")).strip(),"anchor":f"finding-{i+1}","raw":f,"cves":cve_list(f.get("cves")),"affected_items":aff_items,"targets":[l["name"] for l,_v in flinks]}
        ver,vec=cvss_rating(f,pf["cves"])
        pf["cvss_version"]=ver;pf["cvss_vector_any"]=vec;pf["cvss_label"]="CVSS v"+ver if ver else "CVSS"
        for key in ("description","impact","steps","remediation"):pf[key]=parse_rich(tv(substitute(f.get(key),vals,True)),ctx)
        ev=[]
        for e in f.get("evidence") or []:
            if not isinstance(e,dict):continue
            cap=_s(e.get("caption")).strip()
            if e.get("asset_uid"):
                ev.append({"t":"image","uid":_s(e["asset_uid"]),"alt":cap,"width":0,"asset":ctx.asset(e["asset_uid"]),"caption":cap})
            elif e.get("evidence_uid"):
                ent=ctx.use(e["evidence_uid"])
                if ent and (ent["row"] or ent["snapshot"]):ev.append(_evidence_figure(ctx,ent,cap))
                else:ev.append(_p(f"[Evidence {cap or e['evidence_uid']} is no longer available]",i=True))
        pf["evidence_blocks"]=ev
        findings.append(pf)
    counts=severity_counts(findings)
    by_status={s:{x:0 for x in SEVERITIES} for s in STATUSES}
    for f in findings:
        if f["status"] in by_status:by_status[f["status"]][f["severity"]]+=1
    sections=[]
    raw_sections=[s for s in report.get("sections") or [] if isinstance(s,dict) and not s.get("hidden")]
    raw_sections.sort(key=lambda s:(_int(s.get("position"),0,-10**9,10**9),_int(s.get("id"),0,0,10**12)))
    # Parse every visible section first: the appendices list evidence referenced anywhere, including later sections.
    parsed=[]
    for s in raw_sections:
        kind=_s(s.get("kind")).strip() or "custom"
        if kind.startswith("appendix") and not opts["include_appendices"]:continue
        parsed.append((s,kind,parse_rich(tv(substitute(s.get("content"),vals,True)),ctx)))
    num=0;app=0
    has_matrix=any(k=="risk_matrix" for _s0,k,_i in parsed) or any(_has_widget(i,"risk_matrix") for _s0,_k,i in parsed)
    for s,kind,intro in parsed:
        stitle=substitute(_s(s.get("title")).strip() or kind.replace("_"," ").title(),vals)
        appendix=kind.startswith("appendix")
        number=""
        if appendix:
            app+=1;letter=chr(64+app) if app<=26 else str(app)
            if not re.match(r"(?i)appendix\b",stitle):stitle=f"Appendix {letter}: {stitle}"
        elif opts["number_sections"]:
            num+=1;number=str(num)
        blocks=list(intro)
        if kind=="executive_summary" and findings and _opt(s,"dashboard",True):blocks.insert(0,_dashboard_block(findings,counts,by_status))
        elif kind=="findings_summary":blocks.extend(_summary_blocks(findings,counts,by_status,matrix=not has_matrix))
        elif kind=="risk_matrix" and _auto_on(s,intro,True):blocks.extend(_matrix_blocks(findings))
        elif kind=="project_timeline" and _auto_on(s,intro,True):blocks.extend(_timeline_blocks(meta))
        elif kind=="findings":
            if not findings:blocks.append(_p("No findings are included in this report.",i=True))
            for f in findings:blocks.extend(_finding_blocks(ctx,f,vals))
        elif kind=="remediation_roadmap":blocks.extend(_roadmap_blocks(findings))
        elif kind=="document_control":blocks.extend(_control_blocks(report,meta,branding,title))
        elif kind=="appendix_commands" and _auto_on(s,intro,False):blocks.extend(_appendix_commands(ctx))
        elif kind=="appendix_timeline" and _auto_on(s,intro,False):blocks.extend(_appendix_timeline(ctx))
        elif kind=="appendix_tools":
            tools=_appendix_tools(ctx)
            # The built-in templates ship a "[Tool name and version]" placeholder table; generated data replaces it.
            if tools:blocks=[b for b in blocks if not (b["t"]=="table" and "[Tool name" in blocks_text([b]))]
            if tools and _auto_on(s,blocks,False):blocks.extend(tools)
        elif kind=="appendix_evidence" and _auto_on(s,intro,True):blocks.extend(_appendix_evidence(ctx))
        if kind=="scope" and _auto_on(s,intro,True):
            # The generated table of linked targets sits under the text, unless it is switched off or the text places it itself (widget).
            if links and opts.get("scope_table") is not False and not _has_widget(intro,"scope_targets"):
                blocks.append({"t":"label","text":"Targets in scope"});blocks.extend(_scope_table(links,opts.get("scope_columns")))
            blocks.extend(_scope_blocks(meta))
        ctx.links=links;ctx.scope_columns=opts.get("scope_columns")
        blocks=_resolve_blocks(blocks,ctx,findings,counts,by_status)
        sections.append({"anchor":f"sec-{len(sections)+1}","number":number,"letter":letter if appendix else "","title":stitle,"heading":f"{number}. {stitle}" if number else stitle,"kind":kind,"appendix":appendix,"blocks":blocks})
    by_uid={f["uid"]:f for f in findings if f["uid"]}
    fig=[0]
    for sec in sections:_finish_blocks(sec["blocks"],by_uid,fig,sec["kind"]!="appendix_evidence")
    toc=[]
    for sec in sections:
        toc.append({"level":1,"text":sec["heading"],"anchor":sec["anchor"]})
        if sec["kind"]=="findings":
            for f in findings:toc.append({"level":2,"text":f"{f['number']}  {f['title']}","anchor":f["anchor"],"severity":f["severity"]})
    logo=ctx.asset(branding["logo_asset"]) if branding["logo_asset"] else None
    status=_s(report.get("status")).strip().lower() or "draft"
    period=" – ".join(nice_date(x) for x in (meta["start_date"],meta["end_date"]) if x)
    cover={"title":title,"subtitle":substitute(branding["cover_subtitle"] or meta["report_type"],vals),"client":meta["client"],"engagement":meta["engagement"],"date":nice_date(meta["report_date"]),"version":meta["version"],
        "classification":meta["classification"],"company":branding["company"],"project_code":meta["project_code"],"period":period,"status":status,"status_label":REPORT_STATUS_LABELS.get(status,status.title()),"logo":logo,
        "authors":meta["authors"] or ", ".join(_s(t.get("name")) for t in meta["testers"] if isinstance(t,dict) and t.get("name"))}
    cover["facts"]=[(k,v) for k,v in (("Client",cover["client"]),("Engagement",cover["engagement"]),("Testing period",period),("Report date",cover["date"]),("Version",cover["version"]+(f" ({cover['status_label']})" if cover["version"] and status!="final" else "")),("Project code",cover["project_code"]),("Prepared by",cover["authors"])) if v]
    risk=overall_risk(findings)
    return {"title":title,"meta":meta,"branding":branding,"options":opts,"design":dz,"overall":risk,"figures":fig[0],"accent":accent,"secondary":secondary,"on_accent":dz["on_accent"],"ink":dz["ink"],"classification":meta["classification"],"banner":substitute(branding["banner"],vals),"footer":substitute(branding["footer"],vals),
        "company":branding["company"],"cover":cover,"toc":toc,"sections":sections,"findings":findings,"counts":counts,"total":len(findings),"by_status":by_status,"status":status,"uid":_s(report.get("uid")),"evidence_used":ctx.used,"ctx":ctx}
def _scope_blocks(meta):
    out=[]
    si=[_s(x).strip() for x in meta["scope_in"] if _s(x).strip()];so=[_s(x).strip() for x in meta["scope_out"] if _s(x).strip()]
    if si:
        out.append({"t":"label","text":"In scope"})
        out.append(_table([[_hc("#"),_hc("Target")]]+[[_c(i+1,align="C"),_c(x,mono=True)] for i,x in enumerate(si)],[0.08,0.92]))
    if so:
        out.append({"t":"label","text":"Out of scope"})
        out.append(_table([[_hc("#"),_hc("Target")]]+[[_c(i+1,align="C"),_c(x,mono=True)] for i,x in enumerate(so)],[0.08,0.92]))
    if meta["rules_of_engagement"]:
        out.append({"t":"label","text":"Rules of engagement"})
        out.extend(_p(p.strip()) for p in meta["rules_of_engagement"].split("\n") if p.strip())
    return out
def _risk_key(f):
    """Most severe first, then highest CVSS, then report order - the order of the findings overview table."""
    try:sc=float(f["cvss"] or 0)
    except Exception:sc=0.0
    return (SEV_RANK[f["severity"]],-sc,f["index"])
def _opt(section,key,default):
    o=section.get("options") if isinstance(section.get("options"),dict) else {}
    v=o.get(key)
    return v if isinstance(v,bool) else default
def _has_widget(blocks,name):
    for b in blocks or []:
        if b["t"]=="widget" and b["name"]==name:return True
        for key in ("blocks",):
            if _has_widget(b.get(key),name):return True
        if b["t"]=="list" and any(_has_widget(it["blocks"],name) for it in b["items"]):return True
    return False
def overall_risk(findings):
    """Highest severity among the findings that are still a risk (open or awaiting retest); "" when none is."""
    live=[f["severity"] for f in findings if f["status"] not in ("fixed","accepted")]
    return min(live,key=lambda s:SEV_RANK[s]) if live else ""
def _dashboard_block(findings,counts,by_status):
    tot={st:sum(by_status[st].values()) for st in STATUSES}
    risk=overall_risk(findings)
    return {"t":"dashboard","counts":counts,"total":len(findings),"by_status":tot,"open":tot["open"]+tot["retest"],"overall":risk,
        "overall_label":SEV_LABELS[risk] if risk else "No open risk"}
_LEVELS=("low","medium","high")
LEVEL_LABELS={"low":"Low","medium":"Medium","high":"High"}
def risk_levels(f):
    """(likelihood, impact, estimated) on a low/medium/high scale. The author's likelihood wins; without one it is read from the CVSS
    exploitability metrics. Impact follows an explicit impact level when the finding has one, else its severity."""
    raw=f.get("raw") or {};est=False
    like=f["likelihood"] if f["likelihood"] in _LEVELS else ""
    if not like:
        est=True;v=f["cvss_vector"].upper()
        if "AV:N" in v and "AC:L" in v and "PR:N" in v:like="high"
        elif "AV:P" in v or "AV:L" in v or "AC:H" in v or "PR:H" in v:like="low"
        else:like="medium" if v else {"critical":"high","high":"medium"}.get(f["severity"],"low" if f["severity"] in ("low","info") else "medium")
    imp=""
    for key in ("impact_level","impact_rating"):
        v=_s(raw.get(key)).strip().lower()
        if v in _LEVELS:imp=v
    if not imp:imp={"critical":"high","high":"high","medium":"medium"}.get(f["severity"],"low")
    return like,imp,est
# Likelihood x impact -> rating of a matrix cell (index 0 = low).
_CELL_RISK=(("low","low","medium"),("low","medium","high"),("medium","high","critical"))
def cell_risk(like,imp):return _CELL_RISK[_LEVELS.index(like)][_LEVELS.index(imp)]
def _matrix_block(findings):
    cells={l:{i:[] for i in _LEVELS} for l in _LEVELS};est=0
    for f in sorted(findings,key=_risk_key):
        if f["status"]=="fixed":continue
        l,i,e=risk_levels(f);est+=1 if e else 0
        cells[l][i].append({"number":f["number"],"anchor":f["anchor"],"severity":f["severity"],"title":f["title"]})
    return {"t":"matrix","cells":cells,"estimated":est,"count":sum(len(cells[l][i]) for l in _LEVELS for i in _LEVELS)}
def _matrix_blocks(findings):
    if not findings:return [_p("No findings are included in this report.",i=True)]
    return [_matrix_block(findings)]
def _timeline_blocks(meta):
    sched=meta.get("schedule") if isinstance(meta.get("schedule"),dict) else {}
    items=[]
    for m in sched.get("milestones") or []:
        if not isinstance(m,dict):continue
        key=_s(m.get("key")).strip().lower()
        label=_s(m.get("label")).strip() or ("" if key=="custom" else key.replace("_"," ").capitalize()) or "Milestone"
        iso=_s(m.get("date")).strip()[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",iso):iso=""
        items.append({"label":label,"iso":iso,"date":nice_date(iso) if iso else "To be agreed","done":bool(m.get("done")),"key":_s(m.get("key")),"notes":_s(m.get("notes")).strip()})
    if not items:return [_p("No milestones have been scheduled for this engagement.",i=True)]
    order={id(x):n for n,x in enumerate(items)}
    items.sort(key=lambda x:(x["iso"] or "9999-99-99",order[id(x)]))
    return [{"t":"timeline","items":items[:60]}]
def _resolve_blocks(blocks,ctx,findings,counts,by_status):
    """Replace widget markers by their generated block (an unknown widget renders nothing)."""
    out=[]
    for b in blocks:
        t=b["t"]
        if t=="widget":
            if b["name"]=="risk_matrix":out.extend(_matrix_blocks(findings))
            elif b["name"]=="severity_summary":out.append(_severity_table(findings,counts,by_status))
            elif b["name"]=="findings_table":out.extend(_overview_table(findings) or [_p("No findings are included in this report.",i=True)])
            elif b["name"]=="commands_run":out.extend(_appendix_commands(ctx))
            elif b["name"]=="scope_targets":out.extend(_scope_table(getattr(ctx,"links",[]),getattr(ctx,"scope_columns",None)) or [_p("No targets are linked to this report.",i=True)])
            continue
        if t in ("quote","callout"):b=dict(b,blocks=_resolve_blocks(b["blocks"],ctx,findings,counts,by_status))
        elif t=="list":b=dict(b,items=[dict(it,blocks=_resolve_blocks(it["blocks"],ctx,findings,counts,by_status)) for it in b["items"]])
        out.append(b)
    return out
def _finish_runs(runs,by_uid):
    for r in runs or []:
        uid=r.get("fref")
        if uid and uid in by_uid:
            f=by_uid[uid];r["text"]=f"{f['number']} {f['title']}";r["link"]="#"+f["anchor"]
def _finish_blocks(blocks,by_uid,fig,number):
    """Last pass over a section: finding references take the finding's current number, pictures and evidence get their figure number."""
    for b in blocks or []:
        t=b["t"]
        if t in ("p","h"):_finish_runs(b["runs"],by_uid)
        elif t=="list":
            for it in b["items"]:
                _finish_runs(it["runs"],by_uid);_finish_blocks(it["blocks"],by_uid,fig,number)
        elif t in ("quote","callout"):_finish_blocks(b["blocks"],by_uid,fig,number)
        elif t=="table":
            for row in b["rows"]:
                for c in row:
                    if c and c.get("runs"):_finish_runs(c["runs"],by_uid)
        elif t in ("image","figure") and number and (t=="figure" or b.get("asset")):
            fig[0]+=1;b["fig"]=fig[0]
            # A picture without a caption is captioned by its description, unless that is just a file name.
            if t=="image" and not b.get("caption") and b.get("alt") and not re.search(r"(?i)\.(png|jpe?g|gif|webp|bmp)$",b["alt"]) and b["alt"].lower() not in ("image","drawing","screenshot"):b["caption"]=b["alt"]
        elif t=="cmd":_finish_blocks(b.get("desc"),by_uid,fig,number)
def figure_caption(b,sep=" - "):
    """"Figure N - caption" for numbered pictures and evidence, the bare caption otherwise."""
    cap=_s(b.get("caption")).strip()
    if not b.get("fig"):return cap
    return f"Figure {b['fig']}{sep}{cap}" if cap else f"Figure {b['fig']}"
def legacy_blocks(blocks):
    """The newer block kinds expressed with the basic ones (paragraph, label, table, quote, figure, chart), for writers that
    have no layout of their own for them."""
    out=[]
    for b in blocks or []:
        t=b["t"]
        if t=="callout":
            out.append({"t":"label","text":callout_head(b)})
            inner=legacy_blocks(b["blocks"])
            if inner:out.append({"t":"quote","blocks":inner})
        elif t=="cmd":
            out.extend(legacy_blocks(b.get("desc")))
            out.append({"t":"figure","evidence":"","caption":b["title"],"info":" · ".join(x for x in (b.get("kind"),b.get("category")) if x),"pre":b["text"],"image":None,"truncated":0})
        elif t=="dashboard":
            out.append({"t":"label","text":"Overall risk: "+b["overall_label"]})
            out.append(_table([[_hc(SEV_LABELS[x],align="C") for x in SEVERITIES]+[_hc("Open",align="C"),_hc("Total",align="C")],
                [_c(b["counts"][x],align="C",bold=True,fill=SEV_TINTS[x],color=SEV_INK[x]) for x in SEVERITIES]+[_c(b["open"],align="C",bold=True),_c(b["total"],align="C",bold=True)]],None,nozebra=True))
        elif t=="charts":out.append({"t":"chart","counts":b["counts"],"total":b["total"]})
        elif t=="matrix":
            rows=[[_hc("Likelihood / Impact")]+[_hc(LEVEL_LABELS[i]+" impact",align="C") for i in _LEVELS]]
            for l in reversed(_LEVELS):
                rows.append([_hc(LEVEL_LABELS[l]+" likelihood")]+[_c(", ".join(x["number"] for x in b["cells"][l][i]) or "-",align="C",fill=SEV_TINTS[cell_risk(l,i)],color=SEV_INK[cell_risk(l,i)],bold=bool(b["cells"][l][i])) for i in _LEVELS])
            out.append(_table(rows,[0.28,0.24,0.24,0.24],nozebra=True))
            if b.get("estimated"):out.append(_p("Likelihood is estimated from the CVSS exploitability metrics where the finding does not state one.",i=True))
        elif t=="timeline":
            rows=[[_hc("Milestone"),_hc("Date"),_hc("Status"),_hc("Notes")]]
            for m in b["items"]:rows.append([_c(m["label"],bold=True),_c(m["date"]),_c("Completed" if m["done"] else "Planned"),_c(m["notes"] or "-")])
            out.append(_table(rows,[0.3,0.2,0.15,0.35]))
        elif t=="finding_end" or t=="widget":continue
        elif t=="quote":out.append(dict(b,blocks=legacy_blocks(b["blocks"])))
        elif t=="list":
            box=(lambda it:[{"text":"\u2611 " if it.get("checked") else "\u2610 "}]) if b.get("check") else (lambda it:[])
            out.append(dict(b,items=[dict(it,runs=box(it)+list(it["runs"]),blocks=legacy_blocks(it["blocks"])) for it in b["items"]]))
        elif t in ("image","figure") and b.get("fig") and b.get("caption"):out.append(dict(b,alt=b.get("alt") or b["caption"],caption=figure_caption(b)))
        else:out.append(b)
    return out
def _severity_table(findings,counts,by_status):
    rows=[[_hc("Severity"),_hc("Findings",align="C"),_hc("Open",align="C"),_hc("Retest",align="C"),_hc("Fixed",align="C"),_hc("Accepted",align="C")]]
    for s in SEVERITIES:
        rows.append([_sev_cell(s,align="L"),_c(counts[s],align="C",bold=True)]+[_c(by_status[st][s] or "-",align="C") for st in STATUSES])
    rows.append([_c("Total",bold=True,fill="#eef1f5"),_c(len(findings),align="C",bold=True,fill="#eef1f5")]+[_c(sum(by_status[st].values()) or "-",align="C",bold=True,fill="#eef1f5") for st in STATUSES])
    return _table(rows,[0.3,0.14,0.14,0.14,0.14,0.14],nozebra=True,sevtable=True)
def _overview_table(findings):
    if not findings:return []
    rows=[[_hc("ID"),_hc("Finding"),_hc("Severity"),_hc("CVSS",align="C"),_hc("Status"),_hc("Affected")]]
    for f in sorted(findings,key=_risk_key):
        aff=f["affected_names"]
        rows.append([_c(f["number"],bold=True,link="#"+f["anchor"]),_c(f["title"]),_sev_cell(f["severity"]),_c(f["cvss"] or "-",align="C"),_c(STATUS_LABELS.get(f["status"],f["status"].title()),status=f["status"]),_c(", ".join(aff[:3])+(f" (+{len(aff)-3} more)" if len(aff)>3 else ""))])
    return [_table(rows,[0.09,0.36,0.11,0.08,0.14,0.22],overview=True)]
def _summary_blocks(findings,counts,by_status,matrix=True):
    out=[{"t":"label","text":"Findings by severity"},_severity_table(findings,counts,by_status),
        {"t":"charts","counts":counts,"total":len(findings),"by_status":{st:dict(by_status[st]) for st in STATUSES}}]
    if findings and matrix:out+=[{"t":"label","text":"Risk matrix"},_matrix_block(findings)]
    if findings:out+=[{"t":"label","text":"Findings overview"}]+_overview_table(findings)
    return out
def _flat_text(blocks):
    """Paragraphs and list items as one line of prose (list items joined with semicolons) for table cells."""
    out=[]
    for b in blocks or []:
        if b["t"]=="p":out.append(runs_text(b["runs"]))
        elif b["t"]=="quote":out.append(_flat_text(b["blocks"]))
        elif b["t"]=="list":
            items=[]
            for it in b["items"]:
                t=" ".join(x for x in (runs_text(it["runs"]).strip(),_flat_text([x for x in it["blocks"] if x["t"]!="list"])) if x).rstrip(" .;")
                sub="; ".join(x for x in (_flat_text([x]).rstrip(" .") for x in it["blocks"] if x["t"]=="list") if x)
                if sub:t=f"{t} ({sub})" if t else sub
                if t:items.append(t)
            if items:out.append("; ".join(items)+".")
    return re.sub(r"\s+"," "," ".join(x for x in out if x)).strip()
def _first_sentences(blocks,limit=320):
    text=_flat_text(blocks)
    if len(text)<=limit:return text
    cut=text[:limit];dot=max(cut.rfind(". "),cut.rfind("; "))
    return (cut[:dot+1] if dot>limit*0.4 else cut.rsplit(" ",1)[0]+" ...")
def _roadmap_blocks(findings):
    if not findings:return []
    key=lambda f:(1 if f["status"] in ("fixed","accepted") else 0,)+_risk_key(f)
    rows=[[_hc("Priority",align="C"),_hc("ID"),_hc("Finding"),_hc("Severity"),_hc("Recommended action"),_hc("Target"),_hc("Status")]]
    for f in sorted(findings,key=key):
        closed=f["status"] in ("fixed","accepted")
        pr,target=("-","Closed") if closed else ROADMAP_PRIORITY[f["severity"]]
        rows.append([_c(pr,align="C",bold=True),_c(f["number"],bold=True,link="#"+f["anchor"]),_c(f["title"]),_sev_cell(f["severity"]),_c(_first_sentences(f["remediation"]) or "See finding details."),_c(target),_c(STATUS_LABELS.get(f["status"],f["status"].title()),status=f["status"])])
    return [_table(rows,[0.11,0.09,0.18,0.11,0.26,0.12,0.13],roadmap=True)]
# Suggested order of work: a priority and a target window per severity (closed findings are listed last without one).
ROADMAP_PRIORITY={"critical":("P1","Immediate"),"high":("P2","30 days"),"medium":("P3","90 days"),"low":("P4","Next release"),"info":("P5","Backlog")}
def _control_blocks(report,meta,branding,title):
    out=[{"t":"label","text":"Document information"}]
    info=[("Title",title),("Client",meta["client"]),("Engagement",meta["engagement"]),("Project code",meta["project_code"]),("Document version",meta["version"]),("Report date",nice_date(meta["report_date"])),
        ("Status",REPORT_STATUS_LABELS.get(_s(report.get("status")).lower(),_s(report.get("status")).title())),("Classification",meta["classification"]),("Prepared by",branding["company"]),("Authors",meta["authors"]),("Reviewers",meta["reviewers"]),("Client contact",meta["client_contact"])]
    out.append(_table([[_hc(k),_c(v)] for k,v in info if v],[0.28,0.72],header=False,kv=True))
    versions=[v for v in report.get("versions") or [] if isinstance(v,dict)]
    if versions:
        out.append({"t":"label","text":"Version history"})
        rows=[[_hc("Version"),_hc("Date"),_hc("Author")]]
        for v in sorted(versions,key=lambda v:_s(v.get("created_at"))):rows.append([_c(_s(v.get("label")) or "-"),_c(nice_ts(v.get("created_at"))),_c(meta["authors"] or branding["company"])])
        out.append(_table(rows,[0.45,0.25,0.3]))
    testers=[t for t in meta["testers"] if isinstance(t,dict) and (t.get("name") or t.get("email"))]
    if testers:
        out.append({"t":"label","text":"Assessment team"})
        out.append(_table([[_hc("Name"),_hc("Role"),_hc("Contact")]]+[[_c(_s(t.get("name"))),_c(_s(t.get("role"))),_c(_s(t.get("email")))] for t in testers],[0.34,0.33,0.33]))
    dist=[_s(d).strip() for d in meta["distribution"] if _s(d).strip()]
    if dist:
        out.append({"t":"label","text":"Distribution list"})
        out.append(_table([[_hc("#",align="C"),_hc("Recipient")]]+[[_c(i+1,align="C"),_c(d)] for i,d in enumerate(dist)],[0.08,0.92]))
    return out
# Where a captured command was started from, in the words the app's own UI uses (terminal job sources).
SOURCE_LABELS={"terminal":"Terminal","snippet":"Quick Run","command":"Commands","playbook":"Action chain","chain":"Action chain","ai":"AI","batch":"Fan-out run","manual":"Manual","note":"Note","recording":"Recording","import":"Import"}
def source_label(source):
    source=_s(source).strip().lower()
    return SOURCE_LABELS.get(source) or (source.replace("_"," ").capitalize() if source else "-")
def _appendix_commands(ctx):
    cmds=_commands_of(ctx)
    if not cmds:return [_p("No command evidence is referenced by this report.",i=True)]
    groups={};order=[]
    for c in cmds:
        lab=source_label(c.get("source"))
        if lab=="-":lab="Other"
        if lab not in groups:groups[lab]=[];order.append(lab)
        groups[lab].append(c)
    out=[];n=0
    for lab in order:
        if len(order)>1 or lab!="Other":out.append({"t":"label","text":f"{lab} ({len(groups[lab])})"})
        rows=[[_hc("#",align="C"),_hc("Time (UTC)"),_hc("Command"),_hc("Exit",align="C"),_hc("Target")]]
        for c in groups[lab]:
            n+=1
            rows.append([_c(n,align="C"),_c(nice_ts(c["ts"]).replace(" UTC","")),_c(c["command"],mono=True),_c(c["exit_code"] if c["exit_code"]!="" else "-",align="C"),_c(c["target"] or "-")])
        out.append(_table(rows,[0.06,0.17,0.5,0.07,0.2]))
    return out
def _appendix_timeline(ctx):
    events=[]
    for c in _commands_of(ctx):events.append((c["ts"],"Command",c["command"],c["target"]))
    for e in ctx.used:
        row=e.get("row")
        if not row or _s(row.get("command")).strip() or row.get("kind")=="recording":continue
        events.append((_ev_time(row),{"image":"Screenshot","text":"Note"}.get(row.get("kind"),"Evidence"),_s(row.get("title")) or "Evidence",_s(row.get("target"))))
    events=[e for e in events if e[0]]
    if not events:return [_p("No timestamped evidence is referenced by this report.",i=True)]
    events.sort(key=lambda e:e[0])
    rows=[[_hc("Time (UTC)"),_hc("Type"),_hc("Activity"),_hc("Target")]]
    for ts,kind,text,target in events:rows.append([_c(nice_ts(ts).replace(" UTC","")),_c(kind),_c(text,mono=kind=="Command"),_c(target or "-")])
    return [_table(rows,[0.2,0.13,0.49,0.18])]
def _appendix_tools(ctx):
    tools={}
    for c in _commands_of(ctx):
        t=tool_of(c["command"])
        if t:tools[t]=tools.get(t,0)+1
    if not tools:return []
    rows=[[_hc("Tool"),_hc("Invocations",align="C")]]
    for name,n in sorted(tools.items(),key=lambda kv:(-kv[1],kv[0])):rows.append([_c(name,mono=True),_c(n,align="C")])
    return [_table(rows,[0.7,0.3])]
def _appendix_evidence(ctx):
    if not ctx.used:return [_p("No evidence is referenced by this report.",i=True)]
    out=[];index=[[_hc("ID"),_hc("Evidence"),_hc("Type"),_hc("Captured (UTC)"),_hc("Target")]]
    kinds={"command":"Command output","recording":"Session recording","text":"Note","image":"Screenshot"}
    for i,e in enumerate(ctx.used):
        if not e.get("row") and not e.get("snapshot"):continue
        blk=_evidence_figure(ctx,e,"",APPENDIX_LINES)
        blk=dict(blk);eid=f"E-{i+1:02d}";row=e.get("row") or {}
        index.append([_c(eid,bold=True),_c(blk.get("caption") or "Evidence"),_c(kinds.get(row.get("kind"),"Snapshot" if not row else "Evidence")),_c(nice_ts(_ev_time(row)).replace(" UTC","") or "-"),_c(_s(row.get("target")) or "-")])
        blk["caption"]=f"{eid}  {blk.get('caption') or 'Evidence'}"
        out.append(blk)
    if not out:return [_p("No evidence is referenced by this report.",i=True)]
    return [{"t":"label","text":"Evidence index"},_table(index,[0.09,0.45,0.16,0.16,0.14]),{"t":"label","text":"Evidence detail"}]+out
# ---- chart (raster fallback for writers without vector drawing) ----
def chart_png(counts,total,font_path=None,scale=2):
    """Severity bar chart as PNG bytes for Word and Markdown; returns b"" when Pillow cannot draw it."""
    try:
        from PIL import Image,ImageDraw,ImageFont
        W,H=640*scale,(34*len(SEVERITIES)+24)*scale
        im=Image.new("RGB",(W,H),"#ffffff");d=ImageDraw.Draw(im)
        def font(sz):
            try:
                if font_path:return ImageFont.truetype(font_path,sz*scale)
            except Exception:pass
            try:return ImageFont.load_default(sz*scale)
            except Exception:return ImageFont.load_default()
        f,fb=font(13),font(13)
        mx=max([counts[s] for s in SEVERITIES]+[1]);x0=150*scale;x1=W-70*scale
        for i,s in enumerate(SEVERITIES):
            y=(12+i*34)*scale
            d.text((8*scale,y+4*scale),SEV_LABELS[s],fill="#1f2937",font=f)
            d.rectangle([x0,y,x1,y+22*scale],fill="#f1f3f6")
            if counts[s]:d.rectangle([x0,y,x0+max(3*scale,int((x1-x0)*counts[s]/mx)),y+22*scale],fill=SEV_COLORS[s])
            d.text((x1+12*scale,y+4*scale),str(counts[s]),fill="#111827",font=fb)
        buf=io.BytesIO();im.save(buf,"PNG",dpi=(96*scale,96*scale))
        return buf.getvalue()
    except Exception:return b""
# ---- HTML (the one report design: preview, HTML export and the print engine's source) ----
def _e(s):return html.escape(_s(s),quote=True)
def data_uri(asset):return "data:%s;base64,%s"%(asset["mime"],base64.b64encode(asset["data"]).decode("ascii"))
CSP="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:"
def html_from_doc(doc,mode=None):
    from Cores.Services import report_export_html as _h
    return _h.render(doc,mode)[0]
def build_html(report,options=None):
    """The self-contained HTML export; also the in-app preview (shown in a sandboxed iframe, so it carries no scripts)."""
    return html_from_doc(prepare(report,options))
# ---- Markdown ----
def _md_esc(t):return re.sub(r"([\\`*_\[\]<>|#~])",r"\\\1",t)
def _md_code(t):
    t=t.replace("\n"," ")
    fence="`"
    while fence in t:fence+="`"
    pad=" " if t.startswith("`") or t.endswith("`") else ""
    return f"{fence}{pad}{t}{pad}{fence}"
def _md_runs(runs,br="  \n"):
    out=[]
    for r in runs or []:
        if r.get("redact"):out.append("**[REDACTED]**");continue
        raw=r.get("text","")
        if r.get("code"):t=_md_code(raw)
        else:
            t=_md_esc(raw).replace("\n",br)
            lead=len(t)-len(t.lstrip());trail=len(t)-len(t.rstrip());core=t.strip()
            if core:
                if r.get("b"):core=f"**{core}**"
                if r.get("i"):core=f"*{core}*"
                if r.get("s"):core=f"~~{core}~~"
                t=t[:lead]+core+(t[len(t)-trail:] if trail else "")
        href=_safe_href(r.get("href"))
        if href:t=f"[{t}](<{href}>)"
        out.append(t)
    return "".join(out)
def _md_fence(text,lang=""):
    fence="```"
    while fence in text:fence+="`"
    return f"{fence}{lang}\n{text}\n{fence}"
def _md_cell(c):
    if c is None:return ""
    t=_md_runs(c["runs"],"<br>") if c.get("runs") is not None else _md_esc(c.get("text","")).replace("\n","<br>")
    if c.get("mono") and c.get("text"):t=_md_code(c["text"]).replace("|","\\|")
    link=_s(c.get("link"))
    if link.startswith("#"):t=f"[{t}]({link})"
    return t or " "
def _md_blocks(blocks,files,indent=""):
    out=[]
    def add(text):out.append("\n".join((indent+l) if l else l for l in text.split("\n")))
    for b in _md_legacy(blocks):
        t=b["t"]
        if t=="callout":
            # GitHub alert syntax, the form the editor's Markdown view reads back as a callout.
            kind=b["kind"].upper()+(f" severity={b['sev']}" if b.get("sev") else "")+(f" cvss={b['cvss']}" if b.get("cvss") else "")
            body=_md_blocks(([{"t":"p","runs":[{"text":b["title"],"b":True}]}] if b.get("title") else [])+b["blocks"],files,"")
            out.append("\n".join(indent+"> "+l if l else indent+">" for l in (f"[!{kind}]\n"+body).rstrip().split("\n")))
        elif t=="p":add(_md_runs(b["runs"]))
        elif t=="h":add("#"*(b["level"]+1)+" "+_md_runs(b["runs"]," "))
        elif t=="label":add(f"**{_md_esc(b['text'])}**")
        elif t=="pre":add(_md_fence(b["text"],b.get("lang") or ""))
        elif t=="quote":out.append(_md_blocks(b["blocks"],files,indent+"> "))
        elif t=="list":
            lines=[]
            for i,it in enumerate(b["items"]):
                mark=f"{i+1}. " if b["ordered"] else "- "
                lines.append(indent+mark+_md_runs(it["runs"]))
                if it["blocks"]:lines.append(_md_blocks(it["blocks"],files,indent+" "*len(mark)))
            out.append("\n".join(lines))
        elif t=="table":
            rows=b["rows"]
            if not rows:continue
            n=max(len(r) for r in rows);lines=[]
            head=rows[0] if b.get("header") else [None]*n
            lines.append("| "+" | ".join(_md_cell(c) for c in head)+" |")
            lines.append("|"+"|".join(" :---: " if (c and c.get("align")=="C") else " --- " for c in (rows[0]+[None]*n)[:n])+"|")
            for row in (rows[1:] if b.get("header") else rows):
                cells=[_md_cell(c) for c in row]
                if b.get("kv"):cells=[f"**{x}**" if (c and c.get("header") and x.strip()) else x for x,c in zip(cells,row)]
                lines.append("| "+" | ".join(cells)+" |")
            add("\n".join(lines))
        elif t=="hr":add("---")
        elif t=="image":add(_md_image(b,files))
        elif t=="figure":
            cap=_s(b.get("caption"))+(f" ({b['info']})" if b.get("info") else "")
            parts=[]
            if cap:parts.append(f"*{_md_esc(cap)}*")
            if b.get("pre"):parts.append(_md_fence(b["pre"],"text"))
            if b.get("image"):parts.append(_md_image(b["image"],files))
            if b.get("truncated"):parts.append(f"*Output truncated: {int(b['truncated'])} more line(s) not shown.*")
            add("\n\n".join(parts))
        elif t=="chart":
            png=chart_png(b["counts"],b["total"])
            if png:
                files["assets/severity-chart.png"]=png
                add("![Findings by severity](assets/severity-chart.png)")
        elif t=="finding":
            add(f'<a id="{_e(b["anchor"])}"></a>\n\n## {_md_esc(b["id"])} {_md_esc(b["title"])}\n\n**Severity:** {SEV_LABELS[b["severity"]]}'+(f" (CVSS {b['cvss']})" if b.get("cvss") else ""))
    return "\n\n".join(x for x in out if x)
def _md_legacy(blocks):
    out=[]
    for b in blocks:
        if b["t"]=="callout":out.append(b)
        else:out.extend(legacy_blocks([b]))
    return out
def _md_image(b,files):
    a=b.get("asset");cap=_s(b.get("caption") or b.get("alt"))
    if not a:return f"*[Image not available{': '+_md_esc(cap) if cap else ''}]*"
    name=re.sub(r"[^A-Za-z0-9_-]","",a.get("uid") or "") or uuid.uuid4().hex[:12]
    path=f"assets/{name}.{IMAGE_EXT.get(a['mime'],'png')}"
    files[path]=a["data"]
    return f"![{_md_esc(_s(b.get('alt')) or cap)}]({path})"+(f"\n\n*{_md_esc(b['caption'])}*" if b.get("caption") else "")
def markdown_from_doc(doc):
    files={};c=doc["cover"];o=doc["options"];out=[f"# {_md_esc(doc['title'])}"]
    if o["include_cover"]:
        if c["subtitle"]:out.append(f"*{_md_esc(c['subtitle'])}*")
        if c.get("logo"):out.append(_md_image({"asset":c["logo"],"alt":(c["company"]+" logo").strip()},files))
        rows=[("Prepared by",c["company"])]+[f for f in c["facts"] if f[0]!="Prepared by"]+[("Classification",c["classification"])]
        rows=[r for r in rows if r[1]]
        if rows:out.append("| | |\n| --- | --- |\n"+"\n".join(f"| **{_md_esc(k)}** | {_md_esc(v)} |" for k,v in rows))
    if doc["banner"]:out.append(f"> **{_md_esc(doc['banner'])}**")
    if o["include_toc"] and doc["toc"]:
        out.append("## Table of Contents")
        out.append("\n".join(("  " if t["level"]>1 else "")+f"- [{_md_esc(t['text'])}](#{t['anchor']})" for t in doc["toc"]))
    for sec in doc["sections"]:
        out.append(f'<a id="{sec["anchor"]}"></a>\n\n# {_md_esc(sec["heading"])}')
        body=_md_blocks(sec["blocks"],files)
        if body:out.append(body)
    foot=[x for x in (doc["company"],doc["classification"],doc["footer"]) if x]
    if foot:out.append("---\n\n*"+_md_esc(" · ".join(foot))+"*")
    return "\n\n".join(out).rstrip()+"\n",files
def write_markdown_zip(doc,out_path):
    md,files=markdown_from_doc(doc)
    with zipfile.ZipFile(out_path,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.md",md.encode("utf-8"))
        for name in sorted(files):z.writestr(name,files[name])
# ---- JSON (full fidelity) ----
_ASSET_RX=re.compile(r"rptasset:([A-Za-z0-9_\-]{1,80})")
_EVID_RX=re.compile(r"data-evidence\s*=\s*[\"']([A-Za-z0-9_\-]{1,80})[\"']")
def referenced(report):
    """(asset uids, evidence uids) a report points at, in first-seen order."""
    assets=[];evid=[]
    def a(u):
        u=_s(u).strip()
        if u and u not in assets:assets.append(u)
    def e(u):
        u=_s(u).strip()
        if u and u not in evid:evid.append(u)
    def scan(markup):
        markup=_s(markup)
        for m in _ASSET_RX.finditer(markup):a(m.group(1))
        for m in _EVID_RX.finditer(markup):e(m.group(1))
    a((report.get("branding") or {}).get("logo_asset") if isinstance(report.get("branding"),dict) else "")
    for s in report.get("sections") or []:
        if isinstance(s,dict):scan(s.get("content"))
    for f in report.get("findings") or []:
        if not isinstance(f,dict):continue
        for k in ("description","impact","steps","remediation"):scan(f.get(k))
        for ev in f.get("evidence") or []:
            if isinstance(ev,dict):a(ev.get("asset_uid"));e(ev.get("evidence_uid"))
    return assets,evid
def _json_safe(o):
    if isinstance(o,(bytes,bytearray)):return base64.b64encode(bytes(o)).decode("ascii")
    if isinstance(o,dict):return {str(k):_json_safe(v) for k,v in o.items()}
    if isinstance(o,(list,tuple)):return [_json_safe(x) for x in o]
    return o
def collect(report,assets=None,evidence=None):
    """Gather the assets and evidence rows a report needs into the shared maps of an export payload."""
    assets={} if assets is None else assets;evidence=[] if evidence is None else evidence
    ctx=_Ctx(report,False,raw=True);have={_s(e.get("uid")) for e in evidence}
    a_uids,e_uids=referenced(report)
    for uid in e_uids:
        if uid in have:continue
        row=ctx.evidence(uid)
        if not row:continue
        row=_json_safe({k:v for k,v in row.items() if k not in ("id","preview","size","event_count")})
        evidence.append(row);have.add(uid)
        au=(row.get("meta") or {}).get("asset_uid") if isinstance(row.get("meta"),dict) else ""
        if au and au not in a_uids:a_uids.append(au)
    for uid in a_uids:
        if uid in assets:continue
        a=ctx.asset(uid)
        if a:assets[uid]={"mime":a["mime"],"name":a["name"],"width":a["width"],"height":a["height"],"data_b64":base64.b64encode(a["data"]).decode("ascii")}
    return assets,evidence
def _report_payload(report):
    out=_json_safe({k:v for k,v in report.items() if k not in ("_assets","_evidence","stats")})
    svc=_svc("reports_service")
    if svc is not None and hasattr(svc,"resolve_target_values"):
        # Stored reference text is brought in line with the link snapshots, so a backup never carries a stale protected value.
        links=svc.links_by_uid(out.get("targets") if isinstance(out.get("targets"),list) else [])
        for s in out.get("sections") or []:
            if isinstance(s,dict) and isinstance(s.get("content"),str):s["content"]=svc.resolve_target_values(s["content"],links)
        for f in out.get("findings") or []:
            if not isinstance(f,dict):continue
            for k in ("description","impact","steps","remediation"):
                if isinstance(f.get(k),str):f[k]=svc.resolve_target_values(f[k],links)
    return out
def build_json(report):
    assets,evidence=collect(report)
    return {"format":JSON_FORMAT,"version":1,"app":"LOYA NG","exported_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"report":_report_payload(report),"assets":assets,"evidence":evidence}
def build_bundle(reports):
    assets={};evidence=[]
    for r in reports:collect(r,assets,evidence)
    return {"format":BUNDLE_FORMAT,"version":1,"app":"LOYA NG","exported_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"reports":[_report_payload(r) for r in reports],"assets":assets,"evidence":evidence}
# ---- findings tables: CSV / XLSX rows / SARIF ----
FINDING_COLUMNS=("ID","Title","Severity","CVSS Score","CVSS Vector","Status","CWE","OWASP","Affected","Likelihood","Description","Impact","Steps to Reproduce","Remediation","References","Tags","CVE")
def finding_rows(doc):
    rows=[]
    for f in doc["findings"]:
        rows.append([f["number"],f["title"],SEV_LABELS[f["severity"]],f["cvss"],f["cvss_vector_any"],STATUS_LABELS.get(f["status"],f["status"].title()),f["cwe"],f["owasp"],"\n".join(f["affected_list"]),f["likelihood"].title(),
            blocks_text(f["description"]),blocks_text(f["impact"]),blocks_text(f["steps"]),blocks_text(f["remediation"]),"\n".join(f["references"]),", ".join(f["tags"]),", ".join(c["id"] for c in f["cves"])])
    return rows
def csv_safe(v):
    """Spreadsheet formula injection: a cell that starts like a formula is stored as text behind an apostrophe."""
    v=_s(v)
    return "'"+v if v[:1] in ("=","+","-","@","\t","\r","|") else v
def write_csv(doc,out_path):
    with open(out_path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f,quoting=csv.QUOTE_ALL,lineterminator="\r\n")
        w.writerow(FINDING_COLUMNS)
        for row in finding_rows(doc):w.writerow([csv_safe(x) for x in row])
_SARIF_LEVEL={"critical":"error","high":"error","medium":"warning","low":"note","info":"note"}
def _rule_id(f,used):
    base=re.sub(r"[^A-Za-z0-9]+","-",f["title"]).strip("-").lower()[:60] or "finding"
    rid=f"{f['cwe']}/{base}" if re.fullmatch(r"CWE-\d+",f["cwe"]) else base
    n=rid;i=2
    while n in used:n=f"{rid}-{i}";i+=1
    used.add(n)
    return n
def build_sarif(doc):
    rules=[];results=[];used=set()
    for i,f in enumerate(doc["findings"]):
        rid=_rule_id(f,used);desc=blocks_text(f["description"]) or f["title"];fix=blocks_text(f["remediation"])
        cves=[c["id"] for c in f["cves"]]
        tags=["security"]+[x for x in (f["cwe"],f["owasp"]) if x]+f["tags"]+[c for c in cves if c not in f["tags"]]
        rule={"id":rid,"name":re.sub(r"[^A-Za-z0-9]+"," ",f["title"]).title().replace(" ","")[:80] or "Finding","shortDescription":{"text":f["title"]},"fullDescription":{"text":desc[:4000]},
            "defaultConfiguration":{"level":_SARIF_LEVEL[f["severity"]]},"help":{"text":fix or "See the report for remediation guidance."},"properties":{"tags":tags,"severity":f["severity"],"precision":"high"}}
        if f["cvss"]:rule["properties"]["security-severity"]=f["cvss"]
        if cves:rule["properties"]["cve"]=cves
        refs=[r for r in f["references"] if _safe_href(r) and r.lower().startswith("http")]
        if refs:rule["helpUri"]=refs[0]
        m=re.fullmatch(r"CWE-(\d+)",f["cwe"])
        if m:rule["relationships"]=[{"target":{"id":m.group(1),"toolComponent":{"name":"CWE"}},"kinds":["superset"]}]
        rules.append(rule)
        locs=[]
        for a in f["affected_items"]:
            if not isinstance(a,dict):continue
            value=_s(a.get("value")).strip() or _s(a.get("name")).strip()
            if not value:continue
            loc={"logicalLocations":[{"name":value,"kind":"resource","fullyQualifiedName":(_s(a.get("name")).strip()+" "+value).strip() if a.get("name") and a.get("name")!=value else value}]}
            if re.match(r"(?i)^https?://[^\s]+$",value):loc["physicalLocation"]={"artifactLocation":{"uri":value}}
            locs.append(loc)
        res={"ruleId":rid,"ruleIndex":i,"level":_SARIF_LEVEL[f["severity"]],"kind":"fail" if f["status"]!="fixed" else "pass","message":{"text":(f"{f['number']} {f['title']}: "+(_first_sentences(f["description"],600) or f["title"]))},
            "properties":{"findingId":f["number"],"severity":f["severity"],"status":f["status"],"cvssVector":f["cvss_vector_any"],"cvssVersion":f["cvss_version"],"owasp":f["owasp"],"cwe":f["cwe"]},"partialFingerprints":{"loyaFindingUid":f["uid"] or rid}}
        if cves:res["properties"]["cve"]=cves
        if res["kind"]=="pass":res["level"]="none"
        if locs:res["locations"]=locs
        if f["status"]=="accepted":res["suppressions"]=[{"kind":"external","justification":"Risk accepted"}]
        results.append(res)
    run={"tool":{"driver":{"name":"LOYA NG","fullName":"LOYA NG penetration test report","rules":rules}},"results":results,
        "properties":{"reportTitle":doc["title"],"client":doc["meta"]["client"],"engagement":doc["meta"]["engagement"],"reportDate":doc["meta"]["report_date"]}}
    if any(r.get("relationships") for r in rules):run["taxonomies"]=[{"name":"CWE","organization":"MITRE","shortDescription":{"text":"Common Weakness Enumeration"}}]
    return {"$schema":"https://json.schemastore.org/sarif-2.1.0.json","version":"2.1.0","runs":[run]}
# ---- dispatcher ----
def load_report(report_id):
    svc=_svc("reports_service")
    if svc is None or not hasattr(svc,"get_report"):raise ValueError("Reporting is not available.")
    return svc.get_report(report_id)
def slug(text,fallback="Report"):
    t=re.sub(r"[^A-Za-z0-9]+","-",_s(text)).strip("-")
    return t[:80].strip("-") or fallback
def default_filename(report,fmt):
    meta=report.get("meta") if isinstance(report.get("meta"),dict) else {}
    date=_s(meta.get("report_date")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",date):date=today()
    return f"{slug(report.get('title'))}-{date}.{FORMAT_BY_ID[fmt]['ext']}"
def _write_json(obj,path):
    with open(path,"w",encoding="utf-8",newline="\n") as f:json.dump(obj,f,ensure_ascii=False,indent=2)
def atomic_write(out_path,writer):
    """Render next to the destination, then swap it in: a failed render never leaves a truncated export behind."""
    out_path=os.path.abspath(out_path);folder=os.path.dirname(out_path)
    tmp=os.path.join(folder,f".{os.path.basename(out_path)}.{uuid.uuid4().hex[:8]}.part")
    try:
        writer(tmp)
        os.replace(tmp,out_path)
    finally:
        if os.path.exists(tmp):
            try:os.remove(tmp)
            except OSError:pass
    return out_path
PDF_ENGINE_LABELS={"webkit":"the built-in print engine","chromium":"the built-in print engine","fallback":"the basic PDF writer"}
def write_pdf(doc,out_path,result=None):
    """PDF of a prepared document. options.pdf_engine: "auto" prints the HTML design with the app's web engine and falls back to the
    fpdf2 writer when that is not possible; "native" insists (raises); "fallback" (the default for callers outside the app) uses fpdf2.
    `result` receives {"engine","reason","pages",...}."""
    result=result if isinstance(result,dict) else {}
    want=doc["options"].get("pdf_engine") or "fallback"
    if want in ("auto","native"):
        try:
            from Cores.Services import report_pdf_native as _native
            info=_native.write_pdf(doc,out_path)
            result.update(info);result["reason"]=""
            return result
        except Exception as e:
            if want=="native":raise ValueError(f"The print engine could not create the PDF: {e}")
            result["reason"]=_s(e)[:300] or e.__class__.__name__
    from Cores.Services import report_export_pdf
    report_export_pdf.write_pdf(doc,out_path)
    result.update({"engine":"fallback","pages":0,"toc_numbers":True})
    result.setdefault("reason","")
    return result
def render(report,fmt,out_path,options=None):
    """Write `report` (the contract's Report dict) to out_path in the given format. Pure: no dialogs, no DB writes."""
    if fmt not in FORMAT_BY_ID:raise ValueError("Unsupported format.")
    if not isinstance(report,dict):raise ValueError("Report not found.")
    if fmt=="json":return atomic_write(out_path,lambda p:_write_json(build_json(report),p))
    doc=prepare(report,options)
    # Callers that want to know how the file was made pass a dict under options["_result"]; it is filled in place.
    result=options.get("_result") if isinstance(options,dict) and isinstance(options.get("_result"),dict) else {}
    if fmt=="html":
        text=html_from_doc(doc)
        def w(p):
            with open(p,"w",encoding="utf-8",newline="\n") as f:f.write(text)
    elif fmt=="markdown":w=lambda p:write_markdown_zip(doc,p)
    elif fmt=="csv":w=lambda p:write_csv(doc,p)
    elif fmt=="sarif":w=lambda p:_write_json(build_sarif(doc),p)
    elif fmt=="xlsx":
        from Cores.Services import report_xlsx
        w=lambda p:report_xlsx.write_findings(doc,p)
    elif fmt=="pdf":w=lambda p:write_pdf(doc,p,result)
    else:
        from Cores.Services import report_export_docx
        w=lambda p:report_export_docx.write_docx(doc,p)
    return atomic_write(out_path,w)
def render_many(reports,fmt,out_path,options=None):
    """Several reports into one file: a JSON bundle, or a ZIP holding one export per report for every other format."""
    reports=[r for r in reports if isinstance(r,dict)]
    if not reports:raise ValueError("Select at least one report.")
    if fmt=="json":return atomic_write(out_path,lambda p:_write_json(build_bundle(reports),p))
    if fmt not in FORMAT_BY_ID:raise ValueError("Unsupported format.")
    import tempfile,shutil
    def w(p):
        tmp=tempfile.mkdtemp(prefix="loya_report_")
        try:
            used=set()
            with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
                for r in reports:
                    name=default_filename(r,fmt);base,ext=os.path.splitext(name);n=name;i=2
                    while n.lower() in used:n=f"{base}-{i}{ext}";i+=1
                    used.add(n.lower())
                    part=os.path.join(tmp,uuid.uuid4().hex)
                    render(r,fmt,part,options)
                    z.write(part,n);os.remove(part)
        finally:shutil.rmtree(tmp,ignore_errors=True)
    return atomic_write(out_path,w)
