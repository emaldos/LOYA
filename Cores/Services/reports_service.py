"""Reporting model: reports, sections, findings, versions, templates, findings library, image assets, note import helpers.
Everything is stored in the app database (see common_db._REPORTING_TABLES) so the at-rest encryption covers it.
Shapes and names follow the reporting contract; other modules (evidence, export/import) call the service-level functions here."""
import base64,hashlib,html,io,json,os,re,struct,threading,uuid
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from urllib.parse import unquote
from Cores import common_db
from Cores import db_driver as _db_driver
from Cores import recycle_bin as _recycle_bin
from Cores import settings_lock as _settings_lock
from Cores import target_profiles as _profiles
from Cores.Services import cvss as _cvss
from Cores.Services import report_templates as _tpl
from Cores.Services import report_schedule as _schedule
from Cores.Services import report_sections as _sections
SEVERITIES=("critical","high","medium","low","info")
SEVERITY_LABELS={"critical":"Critical","high":"High","medium":"Medium","low":"Low","info":"Informational"}
FINDING_STATUSES=("open","retest","fixed","accepted")
REPORT_STATUSES=("draft","review","final")
SECTION_KINDS=("executive_summary","scope","methodology","findings_summary","findings","remediation_roadmap","conclusion","document_control","appendix_tools","appendix_commands","appendix_evidence","appendix_timeline","custom")+_sections.EXTRA_KINDS
TYPE_REPORT="report"
TYPE_REPORT_FINDING="report_finding"
TITLE_MAX=300
RICH_MAX=2*1024*1024
ASSET_MAX=10*1024*1024
_RICH_INPUT_MAX=24*1024*1024
_UID_RX=re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HEX_COLOR_RX=re.compile(r"^#[0-9a-fA-F]{6}$")
_DATE_RX=re.compile(r"^\d{4}-\d{2}-\d{2}")
_SEV_ALIASES={"informational":"info","information":"info","none":"info","note":"info","moderate":"medium","med":"medium","crit":"critical","severe":"critical"}
_STATUS_ALIASES={"closed":"fixed","resolved":"fixed","remediated":"fixed","risk accepted":"accepted","risk_accepted":"accepted","accepted risk":"accepted","in retest":"retest","retesting":"retest","new":"open","":"open"}
def _now():return datetime.now(timezone.utc).isoformat()
def _uid():return uuid.uuid4().hex
def _s(v,n=0):
    t="" if v is None else (v if isinstance(v,str) else str(v))
    t=t.replace("\x00","").strip()
    return t[:n] if n else t
def _json_obj(text):
    try:
        d=json.loads(text or "{}")
        return d if isinstance(d,dict) else {}
    except Exception:return {}
def _dump(o):return json.dumps(o,ensure_ascii=False)
def _bool(v,default=False):
    if isinstance(v,bool):return v
    if v is None:return default
    if isinstance(v,(int,float)):return bool(v)
    return str(v).strip().lower() in ("1","true","yes","on")
def _int(v,msg="Not found."):
    try:
        if isinstance(v,bool):raise ValueError
        return int(v)
    except (TypeError,ValueError):raise ValueError(msg)
def _str_list(v,maxn=200,maxlen=500):
    if isinstance(v,str):v=[x for x in re.split(r"[\r\n]+",v)]
    if not isinstance(v,(list,tuple)):return []
    out=[]
    for x in v:
        if isinstance(x,(dict,list,tuple)) or x is None:continue
        t=_s(x,maxlen)
        if t:out.append(t)
        if len(out)>=maxn:break
    return out
_tls=threading.local()
@contextmanager
def _db():
    # Re-entrant per thread: a nested call (an image stored while a section is being saved) joins the open transaction instead of
    # waiting on its own write lock.
    con=getattr(_tls,"con",None)
    if con is not None:
        yield con
        return
    con=common_db.connect(common_db.db_path(),timeout=5)
    try:
        common_db.ensure_schema(con)
        _tls.con=con
        yield con
        con.commit()
    except BaseException:
        try:con.rollback()
        except Exception:pass
        raise
    finally:
        _tls.con=None
        con.close()
# ---- rich HTML sanitiser (the contract's subset; authoritative, applied on every save)
# Subset v2 adds the Notes editor's structures (callouts, checklists, embeds, command figures, masked secrets, colour spans, widget markers): still no style / id / on* attribute, only whitelisted class tokens and pattern-checked data-* values.
_ALLOWED=frozenset(("p","br","h3","h4","strong","b","em","i","u","s","code","pre","blockquote","ul","ol","li","a","table","thead","tbody","tr","th","td","hr","img","figure","figcaption","span","div"))
_VOID=frozenset(("br","hr","img"))
_VOID_ANY=frozenset(("br","hr","img","input","meta","link","base","col","wbr","area","embed","source","track","param","frame","keygen"))
# Dropped together with everything inside them.
_DROP=frozenset(("script","style","iframe","object","svg","form","math","noscript","template","textarea","select","title","head","noframes","noembed","xmp","applet","frameset","audio","video","canvas"))
_BLOCKS=frozenset(("p","br","h3","h4","pre","blockquote","ul","ol","li","table","thead","tbody","tr","th","td","hr","figure","figcaption","div"))
_NOTE_TAG_MAP={"h1":"h3","h2":"h3","h5":"h4","h6":"h4","strike":"s","del":"s","mark":"strong","ins":"u","kbd":"code","samp":"code","tt":"code"}
_NOTE_BREAK=frozenset(("div","section","article","header","footer","aside","main","dl","dt","dd","details","summary","caption","label"))
_HREF_RX=re.compile(r"^(?:https?://|mailto:)[^\s\x00-\x1f]+$",re.I)
_ASSET_SRC_RX=re.compile(r"^rptasset:([A-Za-z0-9_-]{6,64})$")
_WIDTH_RX=re.compile(r"^\d{1,4}(?:px|%)?$")
_LANG_RX=re.compile(r"[A-Za-z0-9_+#.-]{1,32}")
_BOX_OFF="\u2610 ";_BOX_ON="\u2611 "
_ID_RX=re.compile(r"[A-Za-z0-9_-]{1,64}")
_ASSET_RX=re.compile(r"[A-Za-z0-9_-]{6,64}")
_SHAPES_RX=re.compile(r"[A-Za-z0-9_-]{1,400000}")
_LABEL_RX=re.compile(r"[A-Za-z0-9 ._+#/()-]{1,80}")
_TAGS_RX=re.compile(r"[A-Za-z0-9 ._+#/(),-]{1,200}")
_TOKEN_RX=re.compile(r"[a-z_]{1,40}")
_CVSS_ATTR_RX=re.compile(r"[0-9]{1,2}(?:\.[0-9])?")
_ALIGNS=("center","right","justify")
_ALIGN_TAGS=frozenset(("p","h3","h4","li","blockquote","td","th"))
_CALLOUTS=("finding","vuln","info","warning","credential","evidence")
_WIDGETS=("risk_matrix","severity_summary","findings_table","commands_run","scope_targets")
_TABLE_CLS=("note-table","note-table-head","note-align-center","note-align-right")
_EMBED_CLS=("note-embed-inline","note-embed-float-left","note-embed-float-right","note-align-center","note-align-right","note-sketch")
_SPAN_CLS=("rpt-redact","note-secret","note-ts","rpt-fref","rpt-ph","rpt-tv")
# A target value key as the Targets page allows it (no quotes, braces or shell punctuation); "@name" / "@status" are the target's own fields.
_TV_KEY_RX=re.compile(r"@?[^\x00-\x1f\x7f\"'<>&{}\\`$,;=|()*]{1,80}")
_CHECKED=("1","true","checked","yes")
def _int_attr(v,lo,hi):
    v=(v or "").strip()
    if not re.fullmatch(r"[0-9]{1,6}",v):return ""
    n=int(v)
    return str(n) if lo<=n<=hi else ""
def _align_attr(a):
    v=a.get("data-align","").strip().lower()
    return f' data-align="{v}"' if v in _ALIGNS else ""
_MAX_DEPTH=120
class _Sanitizer(HTMLParser):
    def __init__(self,img_resolver=None,note_mode=False):
        super().__init__(convert_charrefs=True)
        self.out=[];self.stack=[];self.drop=[];self.inline=False;self.tv=None
        self.img_resolver=img_resolver;self.note_mode=note_mode
    def _emit(self,s,inline=None):
        self.out.append(s)
        if inline is not None:self.inline=inline
    def _tag(self,tag,extra="",close=False):
        self._emit(("</" if close else "<")+tag+extra+">",False if tag in _BLOCKS else None)
    def _soft_break(self):
        # Note mode: a <div> line has no tag of its own in the subset, so keep the line break it stood for.
        if not self.inline:return
        self._emit("\n" if any(e=="pre" for _,e in self.stack) else "<br>",False)
    def handle_starttag(self,tag,attrs):
        tag=(tag or "").lower()
        if self.drop:
            if tag in _DROP or (tag=="div" and "div" in self.drop):self.drop.append(tag)
            return
        if tag in _DROP:
            self.drop.append(tag);return
        if self.tv is not None:
            # A target-value reference holds text only (its text is rewritten from the link snapshot).
            if tag not in _VOID_ANY:self.stack.append((tag,None))
            return
        a={}
        for k,v in attrs:
            k=(k or "").lower()
            if k not in a:a[k]="" if v is None else v
        if self.note_mode:
            tag=_NOTE_TAG_MAP.get(tag,tag)
            cls=a.get("class","").split()
            if "note-secret" in cls and tag not in _VOID_ANY:
                self._tag("span",' class="rpt-redact"');self.stack.append((tag,"span"));return
            if tag in _NOTE_BREAK and not (tag=="div" and ("note-callout" in cls or "rpt-widget" in cls)):
                self._soft_break();self.stack.append((tag,None));return
            if tag=="input":
                if a.get("type","").lower()=="checkbox":self._emit(_BOX_ON if "checked" in a else _BOX_OFF,True)
                return
        emitted=None
        if tag in _ALLOWED and len(self.stack)<_MAX_DEPTH:
            if tag=="a":
                href=a.get("href","").strip()
                if _HREF_RX.match(href):
                    self._tag("a",f' href="{html.escape(href,quote=True)}"');emitted="a"
            elif tag=="img":
                self._img(a);return
            elif tag in ("td","th"):
                extra=""
                for k in ("colspan","rowspan"):
                    v=a.get(k,"").strip()
                    if v.isdigit() and 1<int(v)<=1000:extra+=f' {k}="{int(v)}"'
                w=_int_attr(a.get("data-width"),20,2000)
                if w:extra+=f' data-width="{w}"'
                self._tag(tag,extra+_align_attr(a));emitted=tag
            elif tag=="figure":
                extra="";cls=a.get("class","").split()
                if "note-embed" in cls:
                    extra=' class="note-embed'+"".join(" "+c for c in _EMBED_CLS if c in cls)+'"'
                    kind=a.get("data-kind","").strip()
                    if kind in ("image","sketch"):extra+=f' data-kind="{kind}"'
                    asset=a.get("data-asset","").strip()
                    if _ASSET_RX.fullmatch(asset):extra+=f' data-asset="{asset}"'
                    shapes=a.get("data-shapes","").strip()
                    if _SHAPES_RX.fullmatch(shapes):extra+=f' data-shapes="{shapes}"'
                elif "rpt-cmd" in cls:
                    extra=' class="rpt-cmd"'
                    for k,rx,n in (("data-type",_LABEL_RX,40),("data-cat",_LABEL_RX,80),("data-sub",_LABEL_RX,80),("data-tags",_TAGS_RX,200)):
                        v=a.get(k,"").strip()
                        if len(v)<=n and rx.fullmatch(v):extra+=f' {k}="{v}"'
                else:
                    if "rpt-ev" in cls:extra+=' class="rpt-ev"'
                    ev=a.get("data-evidence","").strip()
                    if _UID_RX.match(ev):extra+=f' data-evidence="{ev}"'
                self._tag("figure",extra);emitted="figure"
            elif tag=="span":
                cls=a.get("class","").split()
                kind=next((c for c in _SPAN_CLS if c in cls),"")
                extra=""
                if kind:
                    extra=f' class="{kind}"'
                    if kind=="rpt-fref":
                        f=a.get("data-finding","").strip()
                        if _ID_RX.fullmatch(f):extra+=f' data-finding="{f}"'
                    elif kind=="rpt-ph":
                        tk=a.get("data-token","").strip()
                        if _TOKEN_RX.fullmatch(tk):extra+=f' data-token="{tk}"'
                    elif kind=="rpt-tv":
                        # A live reference to a linked target's value; without both attributes it is just its text.
                        tu=a.get("data-target","").strip();tk=a.get("data-key","").strip()
                        extra=f' class="rpt-tv" data-target="{tu}" data-key="{html.escape(tk,quote=True)}"' if _ID_RX.fullmatch(tu) and _TV_KEY_RX.fullmatch(tk) else ""
                        if extra:self.tv=len(self.stack)
                else:
                    col=a.get("data-color","").strip();bg=a.get("data-bg","").strip();size=_int_attr(a.get("data-size"),8,72)
                    if _HEX_COLOR_RX.fullmatch(col):extra+=f' data-color="{col.lower()}"'
                    if _HEX_COLOR_RX.fullmatch(bg):extra+=f' data-bg="{bg.lower()}"'
                    if size:extra+=f' data-size="{size}"'
                if extra:
                    self._tag("span",extra);emitted="span"
            elif tag=="div":
                cls=a.get("class","").split()
                if "rpt-widget" in cls:
                    w=a.get("data-widget","").strip()
                    if w in _WIDGETS:self._tag("div",f' class="rpt-widget" data-widget="{w}"');self._tag("div",close=True)
                    # A marker is always empty: whatever it holds is dropped up to its end tag.
                    self.drop.append("div");return
                if "note-callout" in cls:
                    kind=a.get("data-callout","").strip().lower()
                    if kind=="vulnerability":kind="vuln"
                    if kind not in _CALLOUTS:kind="info"
                    extra=' class="note-callout'+(" note-finding" if "note-finding" in cls else "")+f'" data-callout="{kind}"'
                    if kind in ("finding","vuln"):
                        sev=a.get("data-sev","").strip().lower();cv=a.get("data-cvss","").strip()
                        if sev in SEVERITIES:extra+=f' data-sev="{sev}"'
                        if _CVSS_ATTR_RX.fullmatch(cv) and 0<=float(cv)<=10:extra+=f' data-cvss="{float(cv):.1f}"'
                    self._tag("div",extra);emitted="div"
            elif tag in _VOID:
                if self.note_mode and tag=="br" and any(e=="pre" for _,e in self.stack):self._emit("\n")
                else:self._tag(tag)
                return
            elif tag=="pre":
                lang=a.get("data-lang","").strip()
                self._tag("pre",f' data-lang="{lang}"' if _LANG_RX.fullmatch(lang) else "");emitted="pre"
            else:
                extra=""
                if tag=="li" and a.get("data-checked","").strip().lower() in _CHECKED:extra+=' data-checked="1"'
                elif tag in ("h3","h4") and not self.note_mode and a.get("data-collapsed","").strip()=="1":extra+=' data-collapsed="1"'
                elif tag=="ul" and "note-checklist" in a.get("class","").split():extra+=' class="note-checklist"'
                elif tag=="ol":
                    st=_int_attr(a.get("start"),2,9999)
                    if st:extra+=f' start="{st}"'
                elif tag=="table":
                    cls=a.get("class","").split();keep=[c for c in _TABLE_CLS if c in cls]
                    if keep:extra+=' class="'+" ".join(keep)+'"'
                if tag in _ALIGN_TAGS:extra+=_align_attr(a)
                self._tag(tag,extra);emitted=tag
        if tag in _VOID_ANY:return
        self.stack.append((tag,emitted))
    def _img(self,a):
        src=a.get("src","").strip()
        m=_ASSET_SRC_RX.match(src)
        uid=m.group(1) if m else ""
        if not uid and self.img_resolver:
            try:uid=self.img_resolver(src,a) or ""
            except Exception:uid=""
        alt=_s(a.get("alt",""),300)
        if not uid or not _UID_RX.match(uid):
            if self.note_mode:self._emit(html.escape(f"[Image: {alt}]" if alt else "[Image]",quote=False),True)
            return
        extra=""
        w=a.get("data-width","").strip()
        if _WIDTH_RX.match(w):extra=f' data-width="{w}"'
        self._emit(f'<img src="rptasset:{uid}" alt="{html.escape(alt,quote=True)}"{extra}>',True)
    def handle_endtag(self,tag):
        tag=(tag or "").lower()
        if self.drop:
            for i in range(len(self.drop)-1,-1,-1):
                if self.drop[i]==tag:
                    del self.drop[i:];break
            return
        if self.note_mode:tag=_NOTE_TAG_MAP.get(tag,tag)
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                self._close_to(i);break
    def _close_to(self,i):
        tail=self.stack[i:];del self.stack[i:]
        if self.tv is not None and i<=self.tv:self.tv=None
        for raw,emitted in reversed(tail):
            if emitted:self._tag(emitted,close=True)
            elif self.note_mode and raw in _NOTE_BREAK:self._soft_break()
    def handle_data(self,data):
        if self.drop or not data:return
        self._emit(html.escape(data.replace("\x00",""),quote=False),True if data.strip() else None)
    def result(self):
        try:self.close()
        except Exception:pass
        self._close_to(0)
        return "".join(self.out)
def _sanitize(text,img_resolver=None,note_mode=False):
    t="" if text is None else (text if isinstance(text,str) else str(text))
    if not t:return ""
    t=t[:_RICH_INPUT_MAX].replace("\x00","")
    def run(src):
        p=_Sanitizer(img_resolver=img_resolver,note_mode=note_mode)
        try:p.feed(src)
        except Exception:return html.escape(re.sub(r"<[^>]*>?","",src),quote=False)
        return p.result()
    out=run(t)
    if len(out)>RICH_MAX:out=run(out[:RICH_MAX])[:RICH_MAX+4096]
    return out
def sanitize_html(text):
    """Reduce any HTML to the reporting rich subset. Pure: no database access; images survive only as rptasset:UID."""
    return _sanitize(text)
def _data_image_resolver(src,attrs=None):
    if not src[:11].lower().startswith("data:image/"):return ""
    try:return add_asset(_s((attrs or {}).get("alt",""),120) or "image",_b64_bytes(src))["uid"]
    except Exception:return ""
def _rich(text):
    """Sanitise a rich field for storage; images the editor still holds as data: URLs become assets."""
    t="" if text is None else (text if isinstance(text,str) else str(text))
    return _sanitize(t,img_resolver=_data_image_resolver if "data:image/" in t.lower() else None)
_TAG_STRIP_RX=re.compile(r"<[^>]+>")
def _plain(rich):return html.unescape(_TAG_STRIP_RX.sub(" ",rich or "")).strip()
def _rich_empty(rich):return not _plain(rich) and "<img" not in (rich or "") and "<hr>" not in (rich or "")
# ---- assets (images only, stored as BLOBs)
def _b64_bytes(data_b64):
    raw=data_b64 if isinstance(data_b64,str) else ""
    if raw[:5].lower()=="data:":
        if "," not in raw:raise ValueError("Invalid image data.")
        raw=raw.split(",",1)[1]
    raw=re.sub(r"\s+","",raw)
    if not raw:raise ValueError("No image data provided.")
    if len(raw)>ASSET_MAX*4//3+16:raise ValueError("Image is too large (maximum 10 MB).")
    try:return base64.b64decode(raw+"="*((4-len(raw)%4)%4),validate=True)
    except Exception:raise ValueError("Invalid image data.")
def _sniff_image(raw):
    if raw[:8]==b"\x89PNG\r\n\x1a\n":return "image/png"
    if raw[:3]==b"\xff\xd8\xff":return "image/jpeg"
    if raw[:6] in (b"GIF87a",b"GIF89a"):return "image/gif"
    if raw[:4]==b"RIFF" and raw[8:12]==b"WEBP":return "image/webp"
    return ""
def _header_size(raw,mime):
    try:
        if mime=="image/png" and raw[12:16]==b"IHDR":return struct.unpack(">II",raw[16:24])
        if mime=="image/gif":return struct.unpack("<HH",raw[6:10])
        if mime=="image/jpeg":
            i=2;n=len(raw)
            while i+9<n:
                if raw[i]!=0xFF:i+=1;continue
                marker=raw[i+1]
                if marker in (0xFF,0x00):i+=1;continue
                if 0xD0<=marker<=0xD9 or marker==0x01:i+=2;continue
                seg=struct.unpack(">H",raw[i+2:i+4])[0]
                if 0xC0<=marker<=0xCF and marker not in (0xC4,0xC8,0xCC):
                    h,w=struct.unpack(">HH",raw[i+5:i+9]);return w,h
                i+=2+seg
        if mime=="image/webp":
            chunk=raw[12:16]
            if chunk==b"VP8X":return 1+int.from_bytes(raw[24:27],"little"),1+int.from_bytes(raw[27:30],"little")
            if chunk==b"VP8L":
                b=int.from_bytes(raw[21:25],"little");return (b&0x3FFF)+1,((b>>14)&0x3FFF)+1
            if chunk==b"VP8 ":
                w,h=struct.unpack("<HH",raw[26:30]);return w&0x3FFF,h&0x3FFF
    except Exception:pass
    return 0,0
def _image_size(raw,mime):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            w,h=im.size
            return int(w),int(h)
    except Exception:
        w,h=_header_size(raw,mime)
        return int(w or 0),int(h or 0)
def _asset_name(name):
    n=re.sub(r'[\\/:*?"<>|\x00-\x1f]',"_",_s(name,200)).strip(". ")
    return n[:120] or "image"
def _asset_meta(r):return {"uid":r[0],"mime":r[1],"width":int(r[2] or 0),"height":int(r[3] or 0),"name":r[4] or ""}
def add_asset(name,raw_bytes):
    """Store an image (png/jpeg/gif/webp by magic bytes, at most 10 MB). The same bytes are stored once. -> {uid,mime,width,height,name}"""
    if not isinstance(raw_bytes,(bytes,bytearray,memoryview)):raise ValueError("Invalid image data.")
    raw=bytes(raw_bytes)
    if not raw:raise ValueError("No image data provided.")
    if len(raw)>ASSET_MAX:raise ValueError("Image is too large (maximum 10 MB).")
    mime=_sniff_image(raw)
    if not mime:raise ValueError("Only PNG, JPEG, GIF and WebP images can be added to a report.")
    sha=hashlib.sha256(raw).hexdigest()
    with _db() as con:
        cur=con.cursor()
        cur.execute("SELECT uid,mime,width,height,name FROM ReportAssets WHERE sha256=? LIMIT 1",(sha,))
        row=cur.fetchone()
        if row:return _asset_meta(row)
        w,h=_image_size(raw,mime)
        uid=_uid();nm=_asset_name(name)
        cur.execute("INSERT INTO ReportAssets(uid,name,mime,data,width,height,sha256,created_at) VALUES(?,?,?,?,?,?,?,?)",(uid,nm,mime,_db_driver.Binary(raw),w,h,sha,_now()))
        return {"uid":uid,"mime":mime,"width":w,"height":h,"name":nm}
def asset_add(name,data_b64):return add_asset(name,_b64_bytes(data_b64))
def get_asset(uid):
    """-> {uid,mime,name,width,height,data:bytes}"""
    u=_s(uid)
    if u.startswith("rptasset:"):u=u[9:]
    if not _UID_RX.match(u):raise ValueError("Asset not found.")
    with _db() as con:
        row=con.execute("SELECT uid,mime,width,height,name,data FROM ReportAssets WHERE uid=?",(u,)).fetchone()
    if not row:raise ValueError("Asset not found.")
    d=_asset_meta(row);d["data"]=bytes(row[5])
    return d
def asset_get(uid):
    d=get_asset(uid)
    raw=d.pop("data")
    d["data_url"]=f"data:{d['mime']};base64,"+base64.b64encode(raw).decode("ascii")
    return d
_ASSET_TOKEN_RX=re.compile(r"[0-9a-f]{32}")
_ASSET_REF_SOURCES=(("Reports","branding"),("ReportSections","content"),("ReportFindings","data"),("FindingLibrary","data"),("ReportTemplates","data"),("ReportVersions","snapshot"),("ReportEvidence","meta"),("ReportEvidence","content"),("RecycleBin","payload"))
def purge_orphan_assets(dbp=None,grace_seconds=86400):
    """Delete assets nothing refers to any more (reports, versions, library, templates, evidence, Recycle Bin, defaults). Assets younger than
    the grace period are kept: the editor uploads an image before the text that references it is saved. -> number removed"""
    try:
        con=common_db.connect(dbp or common_db.db_path(),timeout=5)
        try:
            common_db.ensure_schema(con)
            cur=con.cursor()
            cutoff=(datetime.now(timezone.utc)-timedelta(seconds=max(0,int(grace_seconds or 0)))).isoformat()
            cand=[r[0] for r in cur.execute("SELECT uid FROM ReportAssets WHERE created_at<=?",(cutoff,))]
            if not cand:return 0
            used=set()
            for table,col in _ASSET_REF_SOURCES:
                try:
                    for (text,) in cur.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL AND {col}<>''"):
                        if isinstance(text,str):used.update(_ASSET_TOKEN_RX.findall(text))
                except Exception:continue
            try:used.update(_ASSET_TOKEN_RX.findall(_dump(_stored_defaults())))
            except Exception:pass
            dead=[u for u in cand if u not in used]
            for u in dead:cur.execute("DELETE FROM ReportAssets WHERE uid=?",(u,))
            con.commit()
            return len(dead)
        finally:
            con.close()
    except Exception:
        return 0
# ---- defaults (Data/settings.json, key "reports")
_BRANDING_DEFAULT={"company":"","logo_asset":"","accent":"#1f4e79","secondary":"#5b6770","banner":"","footer":"","cover_subtitle":"","show_cover":True,"theme":"corporate","font":"theme","cover_style":""}
_OPTIONS_DEFAULT={"page_size":"A4","include_toc":True,"include_appendices":True,"number_sections":True,"finding_id_prefix":"F-"}
_DEFAULTS={"default_format":"pdf","page_size":"A4","include_appendices":True,"include_toc":True,"branding":dict(_BRANDING_DEFAULT),"testers":[],"classification":"Confidential","redact_evidence":True}
_FORMATS=("pdf","docx","html","markdown","json","csv","xlsx","sarif")
_LIBRARY_SEED_VERSION=1
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def _stored_defaults():
    d=_settings_lock.read_json(_settings_path(),{})
    r=d.get("reports",{}) if isinstance(d,dict) else {}
    return r if isinstance(r,dict) else {}
def _norm_branding(src,base=None):
    out=dict(base or _BRANDING_DEFAULT)
    if not isinstance(src,dict):return out
    for k,n in (("company",200),("banner",300),("footer",300),("cover_subtitle",300)):
        if k in src:out[k]=_s(src[k],n)
    if "logo_asset" in src:
        u=_s(src["logo_asset"])
        if u.startswith("rptasset:"):u=u[9:]
        out["logo_asset"]=u if _UID_RX.match(u) else ""
    for k in ("accent","secondary"):
        if k in src:
            v=_s(src[k])
            if _HEX_COLOR_RX.match(v):out[k]=v.lower()
    if "show_cover" in src:out["show_cover"]=_bool(src["show_cover"],True)
    # Report design (Cores/Services/report_design.py): unknown ids fall back to the default; "" for cover_style = the theme's own.
    from Cores.Services import report_design as _design
    if "theme" in src:out["theme"]=_design.theme_id(src["theme"])
    if "font" in src:out["font"]=_s(src["font"]).lower() if _s(src["font"]).lower() in _design.FONT_BY_ID else "theme"
    if "cover_style" in src:out["cover_style"]=_s(src["cover_style"]).lower() if _s(src["cover_style"]).lower() in _design.COVER_IDS else ""
    return out
def _norm_testers(v):
    out=[]
    for t in (v if isinstance(v,(list,tuple)) else []):
        if isinstance(t,str):t={"name":t}
        if not isinstance(t,dict):continue
        row={"name":_s(t.get("name"),120),"role":_s(t.get("role"),120),"email":_s(t.get("email"),200)}
        if row["name"] or row["role"] or row["email"]:out.append(row)
        if len(out)>=50:break
    return out
def _norm_defaults(src,base=None):
    """Full defaults dict: `base` (or the built-in defaults) with every valid value of `src` applied."""
    out={k:(dict(v) if isinstance(v,dict) else (list(v) if isinstance(v,list) else v)) for k,v in (base or _DEFAULTS).items()}
    if not isinstance(src,dict):return out
    f=_s(src.get("default_format")).lower()
    if f in _FORMATS:out["default_format"]=f
    if _s(src.get("page_size")) in ("A4","Letter"):out["page_size"]=_s(src.get("page_size"))
    for k in ("include_appendices","include_toc","redact_evidence"):
        if k in src:out[k]=_bool(src[k],out[k])
    if "branding" in src:out["branding"]=_norm_branding(src.get("branding"),out["branding"])
    if "testers" in src:out["testers"]=_norm_testers(src["testers"])
    if "classification" in src:out["classification"]=_s(src["classification"],80)
    return out
def defaults_get():return _norm_defaults(_stored_defaults())
def defaults_set(patch):
    if not isinstance(patch,dict):raise ValueError("Invalid report defaults.")
    result={}
    def mutate(d):
        cur=d.get("reports") if isinstance(d.get("reports"),dict) else {}
        norm=_norm_defaults(patch,_norm_defaults(cur))
        keep={k:v for k,v in cur.items() if k not in _DEFAULTS}
        keep.update(norm)
        d["reports"]=keep
        result.update(norm)
    if not _settings_lock.update_json(_settings_path(),mutate):raise ValueError("Could not save the report defaults.")
    return result
# ---- report meta / options
_META_STR={"client":200,"client_contact":300,"engagement":200,"project_code":80,"report_type":120,"rules_of_engagement":20000,"methodology":300,"classification":80,"version":20,"authors":500,"reviewers":500}
_META_DATES=("start_date","end_date","report_date")
_META_LISTS=("scope_in","scope_out","distribution")
_META_EXTRA_MAX=200000
def _date(v):
    t=_s(v)
    if not _DATE_RX.match(t):return ""
    try:
        datetime.strptime(t[:10],"%Y-%m-%d")
        return t[:10]
    except ValueError:return ""
def _norm_meta(src,base=None):
    out={k:"" for k in _META_STR}
    for k in _META_DATES:out[k]=""
    for k in _META_LISTS:out[k]=[]
    out["testers"]=[]
    if isinstance(base,dict):out.update(base)
    if not isinstance(src,dict):return out
    for k,v in src.items():
        if k in _META_STR:out[k]=_s(v,_META_STR[k])
        elif k in _META_DATES:out[k]=_date(v)
        elif k in _META_LISTS:out[k]=_str_list(v,500,1000)
        elif k=="testers":out[k]=_norm_testers(v)
        elif k=="schedule":out[k]=_schedule.normalize(v)
        elif isinstance(k,str) and re.match(r"^[A-Za-z0-9_]{1,40}$",k):
            # Extra keys (other modules keep generated data here) are stored as given when they are plain JSON of a sane size.
            try:
                if v is None:out.pop(k,None)
                elif len(_dump(v))<=_META_EXTRA_MAX:out[k]=json.loads(_dump(v))
            except Exception:pass
    return out
def _norm_options(src,base=None):
    out=dict(base or _OPTIONS_DEFAULT)
    if not isinstance(src,dict):return out
    if _s(src.get("page_size")) in ("A4","Letter"):out["page_size"]=_s(src.get("page_size"))
    for k in ("include_toc","include_appendices","number_sections"):
        if k in src:out[k]=_bool(src[k],out.get(k,True))
    if "finding_id_prefix" in src:out["finding_id_prefix"]=_s(src["finding_id_prefix"],12)
    # Scope table (linked targets): both keys exist only once the user chose something; absent means the defaults.
    if "scope_table" in src:
        if src["scope_table"] is None:out.pop("scope_table",None)
        else:out["scope_table"]=_bool(src["scope_table"],True)
    if "scope_columns" in src:
        if src["scope_columns"] is None:out.pop("scope_columns",None)
        else:
            cols=[]
            for k in _str_list(src["scope_columns"],12,80):
                if _TV_KEY_RX.fullmatch(k) and k not in cols:cols.append(k)
            out["scope_columns"]=cols
    return out
def _small_obj(v,limit=100000):
    if not isinstance(v,dict):return {}
    try:
        t=_dump(v)
        return json.loads(t) if len(t)<=limit else {}
    except Exception:return {}
def _sev(v,strict=True,default="info"):
    k=_s(v).lower()
    k=_SEV_ALIASES.get(k,k)
    if k in SEVERITIES:return k
    if strict:raise ValueError("Invalid severity.")
    return default
def _status(v,strict=True):
    k=_s(v).lower()
    k=_STATUS_ALIASES.get(k,k)
    if k in FINDING_STATUSES:return k
    if strict:raise ValueError("Invalid finding status.")
    return "open"
def severity_counts(findings):
    out={k:0 for k in SEVERITIES}
    for f in findings or []:
        k=_sev(f.get("severity") if isinstance(f,dict) else "",strict=False)
        out[k]+=1
    return out
def _report_stats(findings):
    by={k:0 for k in FINDING_STATUSES}
    for f in findings:by[f.get("status") if f.get("status") in by else "open"]+=1
    return {"counts":severity_counts(findings),"total":len(findings),"open":by["open"],"by_status":by}
# ---- placeholders
def placeholders():return [dict(p) for p in _tpl.PLACEHOLDERS]
def placeholder_values(report):
    """Token -> plain-text value for a report dict (escape before putting it into HTML)."""
    meta=report.get("meta",{}) if isinstance(report,dict) else {}
    branding=report.get("branding",{}) if isinstance(report,dict) else {}
    return {"{{client}}":_s(meta.get("client")),"{{engagement}}":_s(meta.get("engagement")),"{{start_date}}":_s(meta.get("start_date")),"{{end_date}}":_s(meta.get("end_date")),"{{company}}":_s(branding.get("company")),"{{report_date}}":_s(meta.get("report_date"))}
_PLACEHOLDER_RX=re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
def apply_placeholders(text,report,escape=True,missing=None):
    """Substitute the {{tokens}} in rich HTML (escape=True) or plain text. Empty values stay as the token unless `missing` is given."""
    vals=placeholder_values(report)
    def rep(m):
        tok="{{"+m.group(1)+"}}"
        if tok not in vals:return m.group(0)
        v=vals[tok]
        if not v:
            if missing is None:return m.group(0)
            v=missing
        return html.escape(v,quote=False) if escape else v
    return _PLACEHOLDER_RX.sub(rep,text or "")
# ---- sections
def _section_dict(r):
    return {"id":int(r[0]),"uid":r[1] or "","kind":r[2] or "custom","title":r[3] or "","content":r[4] or "","position":int(r[5] or 0),"hidden":bool(r[6]),"options":_json_obj(r[7])}
_SECTION_COLS="id,uid,kind,title,content,position,hidden,options"
def _kind(v):
    k=_s(v).lower()
    return k if k in SECTION_KINDS else "custom"
def _load_sections(cur,rid):
    cur.execute(f"SELECT {_SECTION_COLS} FROM ReportSections WHERE report_id=? ORDER BY position,id",(rid,))
    return [_section_dict(r) for r in cur.fetchall()]
def _insert_sections(cur,rid,sections,now,keep_uid=False):
    pos=0
    for s in sections or []:
        if not isinstance(s,dict):continue
        uid=_s(s.get("uid")) if keep_uid else ""
        if not _UID_RX.match(uid):uid=_uid()
        kind=_kind(s.get("kind"))
        cur.execute("INSERT INTO ReportSections(report_id,uid,kind,title,content,position,hidden,options,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(rid,uid,kind,_s(s.get("title"),TITLE_MAX) or _default_section_title(kind),_rich(s.get("content")),pos,1 if _bool(s.get("hidden")) else 0,_dump(_small_obj(s.get("options"))),now))
        pos+=1
def _default_section_title(kind):
    return {"executive_summary":"Executive Summary","scope":"Scope and Rules of Engagement","methodology":"Methodology","findings_summary":"Findings Summary","findings":"Detailed Findings","remediation_roadmap":"Remediation Roadmap","conclusion":"Conclusion","document_control":"Document Control","appendix_tools":"Appendix - Tools Used","appendix_commands":"Appendix - Commands Run","appendix_evidence":"Appendix - Evidence","appendix_timeline":"Appendix - Testing Timeline",**_sections.EXTRA_TITLES}.get(kind,"New Section")
def _renumber(cur,table,rid,ordered_ids):
    for i,x in enumerate(ordered_ids):cur.execute(f"UPDATE {table} SET position=? WHERE id=? AND report_id=?",(i,x,rid))
def _touch(cur,rid,now):cur.execute("UPDATE Reports SET updated_at=? WHERE id=?",(now,rid))
def _require_report(cur,report_id):
    rid=report_id
    if isinstance(rid,str) and not rid.strip().lstrip("-").isdigit():
        row=cur.execute("SELECT id FROM Reports WHERE uid=?",(rid.strip(),)).fetchone()
    else:
        row=cur.execute("SELECT id FROM Reports WHERE id=?",(_int(rid,"Report not found."),)).fetchone()
    if not row:raise ValueError("Report not found.")
    return int(row[0])
def add_section(report_id,fields=None,**kw):
    f=dict(fields) if isinstance(fields,dict) else {}
    f.update(kw)
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        ids=[r[0] for r in cur.execute("SELECT id FROM ReportSections WHERE report_id=? ORDER BY position,id",(rid,))]
        kind=_kind(f.get("kind"))
        # No content given (not even an empty one): the section starts with the built-in boilerplate for its kind.
        if f.get("content") is None:f["content"]=_sections.boilerplate(kind,(cur.execute("SELECT template_id FROM Reports WHERE id=?",(rid,)).fetchone() or ("",))[0] or "")
        cur.execute("INSERT INTO ReportSections(report_id,uid,kind,title,content,position,hidden,options,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(rid,_uid(),kind,_s(f.get("title"),TITLE_MAX) or _default_section_title(kind),_rich(f.get("content")),len(ids),1 if _bool(f.get("hidden")) else 0,_dump(_small_obj(f.get("options"))),now))
        sid=int(cur.lastrowid)
        after=f.get("after_id")
        idx=len(ids)
        if after not in (None,""):
            try:
                a=int(after)
                idx=0 if a<=0 else (ids.index(a)+1 if a in ids else len(ids))
            except (TypeError,ValueError):idx=len(ids)
        ids.insert(idx,sid)
        _renumber(cur,"ReportSections",rid,ids)
        _touch(cur,rid,now)
        return _section_dict(cur.execute(f"SELECT {_SECTION_COLS} FROM ReportSections WHERE id=?",(sid,)).fetchone())
def _section_row(cur,section_id):
    row=cur.execute("SELECT id,report_id FROM ReportSections WHERE id=?",(_int(section_id,"Section not found."),)).fetchone()
    if not row:raise ValueError("Section not found.")
    return int(row[0]),int(row[1])
def update_section(section_id,patch):
    if not isinstance(patch,dict):raise ValueError("Invalid section data.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        sid,rid=_section_row(cur,section_id)
        sets=[];vals=[]
        if "title" in patch:sets.append("title=?");vals.append(_s(patch["title"],TITLE_MAX))
        if "content" in patch:sets.append("content=?");vals.append(_tv_refresh(cur,rid,_rich(patch["content"])))
        if "hidden" in patch:sets.append("hidden=?");vals.append(1 if _bool(patch["hidden"]) else 0)
        if "kind" in patch:sets.append("kind=?");vals.append(_kind(patch["kind"]))
        if "options" in patch and isinstance(patch["options"],dict):
            cur_opts=_json_obj(cur.execute("SELECT options FROM ReportSections WHERE id=?",(sid,)).fetchone()[0])
            for k,v in patch["options"].items():
                if v is None:cur_opts.pop(k,None)
                else:cur_opts[k]=v
            sets.append("options=?");vals.append(_dump(_small_obj(cur_opts)))
        sets.append("updated_at=?");vals.append(now)
        cur.execute("UPDATE ReportSections SET "+",".join(sets)+" WHERE id=?",vals+[sid])
        _touch(cur,rid,now)
    return {"id":sid,"updated_at":now}
def delete_section(section_id):
    now=_now()
    with _db() as con:
        cur=con.cursor()
        sid,rid=_section_row(cur,section_id)
        cur.execute("DELETE FROM ReportSections WHERE id=?",(sid,))
        _renumber(cur,"ReportSections",rid,[r[0] for r in cur.execute("SELECT id FROM ReportSections WHERE report_id=? ORDER BY position,id",(rid,)).fetchall()])
        _touch(cur,rid,now)
    return True
def _reorder(table,report_id,ids):
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        have=[r[0] for r in cur.execute(f"SELECT id FROM {table} WHERE report_id=? ORDER BY position,id",(rid,))]
        want=[];seen=set()
        for x in ids if isinstance(ids,(list,tuple)) else []:
            try:x=int(x)
            except (TypeError,ValueError):continue
            if x in have and x not in seen:want.append(x);seen.add(x)
        want+=[x for x in have if x not in seen]
        _renumber(cur,table,rid,want)
        _touch(cur,rid,now)
    return True
def reorder_sections(report_id,ids):return _reorder("ReportSections",report_id,ids)
# ---- findings
_FINDING_COLS="id,report_id,uid,position,title,severity,cvss_vector,cvss_score,status,data,created_at,updated_at"
_RICH_FIELDS=("description","impact","steps","remediation")
_SOURCE_KINDS=("note","library","autogen","import","")
def _finding_blank():
    return {"title":"","severity":"info","cvss_vector":"","cvss_score":None,"status":"open","cwe":"","owasp":"","references":[],"affected":[],"description":"","impact":"","likelihood":"","steps":"","remediation":"","evidence":[],"tags":[],"retest_notes":"","source":{"kind":"","ref":""},"cves":[]}
_DATA_KEYS=("cwe","owasp","references","affected","description","impact","likelihood","steps","remediation","evidence","tags","retest_notes","source","cves")
def _finding_dict(r):
    f=_finding_blank()
    data=_json_obj(r[9])
    for k in _DATA_KEYS:
        if k in data and type(data[k])==type(f[k]):f[k]=data[k]
    f.update({"id":int(r[0]),"report_id":int(r[1]),"uid":r[2] or "","position":int(r[3] or 0),"title":r[4] or "","severity":_sev(r[5],strict=False),"cvss_vector":r[6] or "","cvss_score":(float(r[7]) if r[7] is not None else None),"status":_status(r[8],strict=False),"created_at":r[10] or "","updated_at":r[11] or ""})
    f["targets"]=[]
    return f
def _score(v):
    try:
        if v is None or v=="" or isinstance(v,bool):return None
        n=float(str(v).replace(",","."))
        if n!=n or n<0 or n>10:return None
        return round(n,1)
    except (TypeError,ValueError):return None
def _norm_affected(v):
    if isinstance(v,str):v=[x for x in re.split(r"[\r\n]+",v)]
    out=[]
    for a in (v if isinstance(v,(list,tuple)) else []):
        if isinstance(a,str):a={"name":a}
        if not isinstance(a,dict):continue
        row={"target_id":_s(a.get("target_id"),64),"name":_s(a.get("name"),200),"value":_s(a.get("value"),500)}
        if row["name"] or row["value"]:out.append(row)
        if len(out)>=500:break
    return out
def _norm_evidence(v):
    out=[]
    for e in (v if isinstance(v,(list,tuple)) else []):
        if not isinstance(e,dict):continue
        ev=_s(e.get("evidence_uid"));asset=_s(e.get("asset_uid"))
        if asset.startswith("rptasset:"):asset=asset[9:]
        if ev and _UID_RX.match(ev):row={"evidence_uid":ev,"asset_uid":"","caption":_s(e.get("caption"),500)}
        elif asset and _UID_RX.match(asset):row={"evidence_uid":"","asset_uid":asset,"caption":_s(e.get("caption"),500)}
        else:continue
        out.append(row)
        if len(out)>=200:break
    return out
def _norm_tags(v):
    if isinstance(v,str):v=re.split(r"[,;\r\n]+",v)
    out=[];seen=set()
    for t in _str_list(v,50,60):
        if t.lower() in seen:continue
        seen.add(t.lower());out.append(t)
    return out
_CVE_ID_RX=re.compile(r"^CVE-\d{4}-\d{4,19}$")
_CVE_URL_RX=re.compile(r"^https?://[^\s\"'<>`\\\x00-\x1f]+$",re.I)
_CVE_MAX=50
def _norm_cves(v):
    """The CVEs of a finding: [{id,title,cvss_version,cvss_vector,cvss_score,severity,cwe,description,remediation,references,kev,kev_due,epss,source,fetched_at}].
    All text is plain text (escaped wherever it is shown); an entry without a valid id is dropped, a repeated id keeps the first."""
    if isinstance(v,str):v=re.split(r"[,;\s]+",v)
    out=[];seen=set()
    for e in (v if isinstance(v,(list,tuple)) else []):
        if isinstance(e,str):e={"id":e}
        if not isinstance(e,dict):continue
        cid=_s(e.get("id"),40).upper()
        if not _CVE_ID_RX.match(cid) or cid in seen:continue
        seen.add(cid)
        score=_score(e.get("cvss_score"))
        sev=_s(e.get("severity")).lower();sev=_SEV_ALIASES.get(sev,sev)
        if sev not in SEVERITIES:sev=_cvss.severity(score) if score is not None else ""
        version=_s(e.get("cvss_version"),8)
        refs=[];have=set()
        for r in _str_list(e.get("references"),200,1000):
            if _CVE_URL_RX.match(r) and r.lower() not in have and len(refs)<30:
                have.add(r.lower());refs.append(r)
        try:
            epss=None if e.get("epss") is None or e.get("epss")=="" or isinstance(e.get("epss"),bool) else float(e.get("epss"))
            if epss is not None and not 0<=epss<=1:epss=None
        except (TypeError,ValueError):epss=None
        source=_s(e.get("source"),20).lower()
        out.append({"id":cid,"title":_s(e.get("title"),TITLE_MAX),"cvss_version":version if version in ("2.0","3.0","3.1","4.0") else "","cvss_vector":_s(e.get("cvss_vector"),200),"cvss_score":score,"severity":sev,
            "cwe":_s(e.get("cwe"),120),"description":_s(e.get("description"),20000),"remediation":_s(e.get("remediation"),20000),"references":refs,"kev":e.get("kev") is True,"kev_due":_s(e.get("kev_due"),40),
            "epss":epss,"source":source if source in ("manual","cache","live","index") else "manual","fetched_at":_s(e.get("fetched_at"),40)})
        if len(out)>=_CVE_MAX:break
    return out
def _apply_finding_patch(f,patch,creating=False,strict=True):
    """Merge patch into the flat finding dict f, validating as it goes. Unknown keys are ignored."""
    if "title" in patch:f["title"]=_s(patch["title"],TITLE_MAX)
    if "cvss_vector" in patch:
        v=_s(patch["cvss_vector"],200)
        if v:
            r=_cvss.calc(v)
            f["cvss_vector"]=r["vector"] if r["valid"] else v
            f["cvss_score"]=r["score"] if r["valid"] else None
        else:
            f["cvss_vector"]="";f["cvss_score"]=_score(patch.get("cvss_score"))
    elif "cvss_score" in patch and not f.get("cvss_vector"):
        # No vector: a bare score (imported data, a note callout) is kept as given.
        f["cvss_score"]=_score(patch["cvss_score"])
    if "severity" in patch and (strict or _s(patch["severity"])):f["severity"]=_sev(patch["severity"],strict=strict,default=f["severity"])
    elif creating and f["cvss_score"] is not None:f["severity"]=_cvss.severity(f["cvss_score"])
    if "status" in patch:f["status"]=_status(patch["status"],strict=strict)
    for k,n in (("cwe",120),("owasp",160)):
        if k in patch:f[k]=_s(patch[k],n)
    if "retest_notes" in patch:f["retest_notes"]=_s(patch["retest_notes"],50000)
    if "likelihood" in patch:
        v=_s(patch["likelihood"]).lower()
        f["likelihood"]=v if v in ("low","medium","high") else ""
    for k in _RICH_FIELDS:
        if k in patch:f[k]=_rich(patch[k])
    if "references" in patch:f["references"]=_str_list(patch["references"],100,1000)
    if "tags" in patch:f["tags"]=_norm_tags(patch["tags"])
    if "affected" in patch:f["affected"]=_norm_affected(patch["affected"])
    if "evidence" in patch:f["evidence"]=_norm_evidence(patch["evidence"])
    if "cves" in patch:f["cves"]=_norm_cves(patch["cves"])
    if "source" in patch:
        s=patch["source"] if isinstance(patch["source"],dict) else {}
        f["source"]={"kind":_s(s.get("kind"),20).lower(),"ref":_s(s.get("ref"),300)}
    return f
def _finding_data(f):return _dump({k:f[k] for k in _DATA_KEYS})
def _insert_finding(cur,rid,f,pos,now,uid="",created_at=""):
    cur.execute("INSERT INTO ReportFindings(report_id,uid,position,title,severity,cvss_vector,cvss_score,status,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(rid,uid if _UID_RX.match(uid or "") else _uid(),pos,f["title"] or "Untitled finding",f["severity"],f["cvss_vector"],f["cvss_score"],f["status"],_finding_data(f),created_at or now,now))
    return int(cur.lastrowid)
def _insert_findings(cur,rid,findings,now,keep_uid=False,strict=False):
    pos=int(cur.execute("SELECT COUNT(*) FROM ReportFindings WHERE report_id=?",(rid,)).fetchone()[0])
    for src in findings or []:
        if not isinstance(src,dict):continue
        f=_apply_finding_patch(_finding_blank(),src,creating=True,strict=strict)
        fid=_insert_finding(cur,rid,f,pos,now,uid=_s(src.get("uid")) if keep_uid else "",created_at=_s(src.get("created_at")) if keep_uid else "")
        if src.get("targets"):_set_finding_targets(cur,fid,rid,src["targets"])
        pos+=1
def _load_findings(cur,rid):
    cur.execute(f"SELECT {_FINDING_COLS} FROM ReportFindings WHERE report_id=? ORDER BY position,id",(rid,))
    out=[_finding_dict(r) for r in cur.fetchall()]
    links=_finding_targets_map(cur,rid)
    for f in out:f["targets"]=links.get(f["id"],[])
    return out
def _finding_by_id(cur,finding_id):
    row=cur.execute(f"SELECT {_FINDING_COLS} FROM ReportFindings WHERE id=?",(_int(finding_id,"Finding not found."),)).fetchone()
    if not row:raise ValueError("Finding not found.")
    f=_finding_dict(row)
    f["targets"]=_finding_targets(cur,f["id"])
    return f
def get_finding(finding_id):
    with _db() as con:return _finding_by_id(con.cursor(),finding_id)
def add_finding(report_id,fields=None):
    if fields is not None and not isinstance(fields,dict):raise ValueError("Invalid finding data.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        f=_apply_finding_patch(_finding_blank(),fields or {},creating=True)
        pos=int(cur.execute("SELECT COUNT(*) FROM ReportFindings WHERE report_id=?",(rid,)).fetchone()[0])
        _tv_refresh_finding(cur,rid,f)
        fid=_insert_finding(cur,rid,f,pos,now)
        if (fields or {}).get("targets"):_set_finding_targets(cur,fid,rid,fields["targets"])
        _touch(cur,rid,now)
        return _finding_by_id(cur,fid)
def update_finding(finding_id,patch):
    if not isinstance(patch,dict):raise ValueError("Invalid finding data.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        f=_finding_by_id(cur,finding_id)
        _apply_finding_patch(f,patch)
        if any(k in patch for k in _RICH_FIELDS):_tv_refresh_finding(cur,f["report_id"],f)
        cur.execute("UPDATE ReportFindings SET title=?,severity=?,cvss_vector=?,cvss_score=?,status=?,data=?,updated_at=? WHERE id=?",(f["title"],f["severity"],f["cvss_vector"],f["cvss_score"],f["status"],_finding_data(f),now,f["id"]))
        if "targets" in patch:_set_finding_targets(cur,f["id"],f["report_id"],patch["targets"])
        _touch(cur,f["report_id"],now)
        return _finding_by_id(cur,f["id"])
def _finding_payload(f):return {k:v for k,v in f.items() if k not in ("id","report_id")}
def delete_finding(finding_id):
    now=_now()
    with _db() as con:
        cur=con.cursor()
        f=_finding_by_id(cur,finding_id)
        rep=cur.execute("SELECT uid,title FROM Reports WHERE id=?",(f["report_id"],)).fetchone() or ("","")
        _recycle_bin.put_entry_cur(cur,TYPE_REPORT_FINDING,f["title"] or "Untitled finding",{"finding":_finding_payload(f),"report_id":f["report_id"],"report_uid":rep[0],"report_title":rep[1]},source=rep[1] or "Report",entity_key=f["uid"])
        cur.execute("DELETE FROM ReportFindings WHERE id=?",(f["id"],))
        cur.execute("DELETE FROM ReportFindingTargets WHERE finding_id=?",(f["id"],))
        _renumber(cur,"ReportFindings",f["report_id"],[r[0] for r in cur.execute("SELECT id FROM ReportFindings WHERE report_id=? ORDER BY position,id",(f["report_id"],)).fetchall()])
        _touch(cur,f["report_id"],now)
    return True
def reorder_findings(report_id,ids):return _reorder("ReportFindings",report_id,ids)
_SEV_RANK={k:i for i,k in enumerate(SEVERITIES)}
_STATUS_RANK={"open":0,"retest":1,"accepted":2,"fixed":3}
def sort_findings(report_id,by="severity"):
    by=_s(by).lower() or "severity"
    keys={
        "severity":lambda f:(_SEV_RANK[f["severity"]],-(f["cvss_score"] or 0),f["title"].lower()),
        "cvss":lambda f:(-(f["cvss_score"] if f["cvss_score"] is not None else -1),_SEV_RANK[f["severity"]],f["title"].lower()),
        "title":lambda f:(f["title"].lower(),_SEV_RANK[f["severity"]]),
        "status":lambda f:(_STATUS_RANK[f["status"]],_SEV_RANK[f["severity"]],-(f["cvss_score"] or 0),f["title"].lower()),
    }
    if by not in keys:raise ValueError("Unknown sort order.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        items=sorted(_load_findings(cur,rid),key=keys[by])
        _renumber(cur,"ReportFindings",rid,[f["id"] for f in items])
        _touch(cur,rid,now)
        return _load_findings(cur,rid)
# ---- targets / profiles (engagements)
def _profile_list():
    try:return [{"id":_s(p.get("id")),"name":_s(p.get("name")) or "Profile","active":bool(p.get("active"))} for p in _profiles.list_profiles() if isinstance(p,dict) and _s(p.get("id"))]
    except Exception:return []
def _profile_targets(pid):
    """Targets of a profile, read straight from its JSON (the Targets Store prunes and saves as a side effect, so it is not used here)."""
    try:
        d=_settings_lock.read_json(_profiles.profile_targets_json_path(pid),[])
    except Exception:d=[]
    out=[]
    for t in (d if isinstance(d,list) else []):
        if not isinstance(t,dict):continue
        name=_s(t.get("name"))
        if not name:continue
        vals=t.get("values") if isinstance(t.get("values"),dict) else {}
        eng=_s(t.get("engagement_status")).lower()
        out.append({"id":_s(t.get("id")) or hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:16],"name":name,"values":{str(k):("" if v is None else str(v)) for k,v in vals.items()},"status":"live" if _s(t.get("status")).lower()=="live" else "not_used","engagement_status":eng if eng in ("not_started","in_progress","compromised","reported") else "not_started"})
    return out
# Target values also hold passwords, user names, ports and wordlist paths; only addresses belong in a client-facing scope list (same rule as rpgIsScopeValue in reporting.js).
_SCOPE_VALUE_RES=(re.compile(r"^https?://[^/\s]+\S*$",re.I),re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?(-\d{1,3})?$"),re.compile(r"^[0-9a-f]*:[0-9a-f:]*:[0-9a-f:.]*(/\d{1,3})?$",re.I),re.compile(r"^(\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$",re.I))
_SCOPE_SECRET_KEY_RE=re.compile(r"pass|pwd|secret|token|hash|cred|cookie|key|user|login",re.I)
def _is_scope_value(key,v):
    return not _SCOPE_SECRET_KEY_RE.search(str(key)) and any(rx.match(v) for rx in _SCOPE_VALUE_RES)
def _target_scope_line(t):
    vals=[];seen=set()
    for k,v in t["values"].items():
        v=_s(v)
        if v and v.lower() not in seen and _is_scope_value(k,v):seen.add(v.lower());vals.append(v)
    # Same line as rpgTargetScopeLine in reporting.js, so "Fill from targets" does not add the seeded targets twice.
    if not vals or (len(vals)==1 and vals[0]==t["name"]):return t["name"]
    return t["name"]+": "+", ".join(vals)
def sources(profile_id=None):
    """Data for the pickers: profiles, the targets of the given (or active) profile, and the notes."""
    profiles=_profile_list()
    pid=_s(profile_id)
    if not any(p["id"]==pid for p in profiles):pid=next((p["id"] for p in profiles if p["active"]),profiles[0]["id"] if profiles else "")
    # Secret-named values (passwords, hashes, tokens, user names...) never leave the Targets store through the pickers: the page
    # gets their key names only, like targets_available().
    targets=[dict(t,values=_public_values(t["values"]),secret_keys=_secret_names(t["values"])) for t in (_profile_targets(pid) if pid else [])]
    notes=[]
    with _db() as con:
        for r in con.execute("SELECT id,note_name,group_name,tags,updated_at,content FROM Notes ORDER BY updated_at DESC,id DESC"):
            notes.append({"id":int(r[0]),"name":_s(r[1]),"group":_s(r[2]),"tags":[t for t in (_s(x) for x in re.split(r"[,;]",r[3] or "")) if t],"updated_at":r[4] or "","findings":_count_note_findings(r[5] or "")})
    return {"profiles":profiles,"targets":targets,"notes":notes,"profile_id":pid}
# ---- report scope from Targets (optional): links hold a snapshot of the target, so a report does not change when the target does
# Keys that name a credential or an account. Their values are never copied into a report unless the user allows that key on that link.
_TARGET_SECRET_KEY_RE=re.compile(r"pass|pwd|secret|token|hash|key|cred|cookie|session|private|otp|pin|user|login",re.I)
_ENGAGEMENT_STATUSES=("not_started","in_progress","compromised","reported")
_LINK_MAX=500
_RT_COLS="uid,target_id,profile_id,name,snapshot,allowed_secret_keys,position,linked_at,updated_at"
def is_secret_key(key):return bool(_TARGET_SECRET_KEY_RE.search(_s(key)))
def _json_list(text):
    try:
        d=json.loads(text or "[]")
        return d if isinstance(d,list) else []
    except Exception:return []
def _allowed_keys(v):
    out=[]
    for k in _str_list(v,40,80):
        if is_secret_key(k) and _TV_KEY_RX.fullmatch(k) and k not in out:out.append(k)
    return out
def _public_values(values,allowed=()):
    allow={_s(k).lower() for k in allowed or ()}
    out={}
    for k,v in (values.items() if isinstance(values,dict) else ()):
        k=_s(k,80);v=_s(v,2000)
        if not k or not v or len(out)>=200:continue
        if is_secret_key(k) and k.lower() not in allow:continue
        out[k]=v
    return out
def _secret_names(values,allowed=()):
    allow={_s(k).lower() for k in allowed or ()}
    return [k for k,v in (values.items() if isinstance(values,dict) else ()) if _s(v) and is_secret_key(k) and _s(k).lower() not in allow]
def _norm_snapshot(v,allowed=()):
    v=v if isinstance(v,dict) else {}
    eng=_s(v.get("engagement_status")).lower()
    return {"values":_public_values(v.get("values"),allowed),"engagement_status":eng if eng in _ENGAGEMENT_STATUSES else "not_started"}
class _Live:
    """The targets as they are right now, read once per profile."""
    def __init__(self):
        self.profiles=_profile_list();self.names={p["id"]:p["name"] for p in self.profiles};self._targets={}
    def targets(self,pid):
        if pid not in self._targets:self._targets[pid]=_profile_targets(pid) if pid in self.names else []
        return self._targets[pid]
    def get(self,pid,tid):return next((t for t in self.targets(pid) if t["id"]==tid),None)
def link_state(link,target):
    """("ok"|"changed"|"removed", [what differs]) of a link against the live target; only what the link may hold is compared."""
    if target is None:return "removed",[]
    cur=_norm_snapshot(target,link["allowed_secret_keys"]);a=link["snapshot"]["values"];b=cur["values"]
    changed=(["@name"] if target["name"]!=link["name"] else [])+(["@status"] if cur["engagement_status"]!=link["snapshot"]["engagement_status"] else [])+sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))
    return ("changed" if changed else "ok"),changed
def _load_targets(cur,rid,live=None):
    rows=cur.execute(f"SELECT {_RT_COLS} FROM ReportTargets WHERE report_id=? ORDER BY position,id",(rid,)).fetchall()
    if not rows:return []
    live=live or _Live()
    out=[]
    for i,r in enumerate(rows):
        allowed=_allowed_keys(_json_list(r[5]))
        link={"uid":r[0],"target_id":r[1] or "","profile_id":r[2] or "","profile_name":live.names.get(r[2] or "",""),"name":r[3] or "","snapshot":_norm_snapshot(_json_obj(r[4]),allowed),"allowed_secret_keys":allowed,"position":i,"linked_at":r[7] or "","updated_at":r[8] or ""}
        t=live.get(link["profile_id"],link["target_id"])
        link["state"],link["changed_keys"]=link_state(link,t)
        link["live"]=bool(t and t["status"]=="live")
        # Names only: the values of these keys stay on the Targets page until the user allows one.
        link["secret_keys"]=_secret_names(t["values"],allowed) if t else []
        out.append(link)
    return out
def _link_payload(l):return {k:l[k] for k in ("uid","target_id","profile_id","name","snapshot","allowed_secret_keys","linked_at","updated_at") if k in l}
def _insert_targets(cur,rid,links,now):
    """Store link dicts (a copy, an import, a restored version). Snapshots are re-filtered: a secret value survives only with its key allowed."""
    have={r[0] for r in cur.execute("SELECT uid FROM ReportTargets WHERE report_id=?",(rid,)).fetchall()}
    pos=len(have)
    for l in links or []:
        if not isinstance(l,dict) or pos>=_LINK_MAX:continue
        name=_s(l.get("name"),200)
        if not name:continue
        uid=_s(l.get("uid"))
        if not _UID_RX.match(uid) or uid in have:uid=_uid()
        have.add(uid)
        allowed=_allowed_keys(l.get("allowed_secret_keys"))
        cur.execute("INSERT INTO ReportTargets(report_id,uid,target_id,profile_id,name,snapshot,allowed_secret_keys,position,linked_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(rid,uid,_s(l.get("target_id"),64),_s(l.get("profile_id"),64),name,_dump(_norm_snapshot(l.get("snapshot"),allowed)),_dump(allowed),pos,_s(l.get("linked_at"),40) or now,_s(l.get("updated_at"),40) or now))
        pos+=1
def _delete_report_targets(cur,rid,links=True):
    cur.execute("DELETE FROM ReportFindingTargets WHERE finding_id IN (SELECT id FROM ReportFindings WHERE report_id=?)",(rid,))
    if links:cur.execute("DELETE FROM ReportTargets WHERE report_id=?",(rid,))
def _finding_target_rows(rows):
    out={}
    for fid,uid,keys in rows:
        out.setdefault(int(fid),[]).append({"uid":uid,"keys":[k for k in _str_list(_json_list(keys),40,80)]})
    return out
def _finding_targets_map(cur,rid):
    return _finding_target_rows(cur.execute("SELECT ft.finding_id,ft.report_target_uid,ft.keys FROM ReportFindingTargets ft JOIN ReportFindings f ON f.id=ft.finding_id JOIN ReportTargets t ON t.report_id=f.report_id AND t.uid=ft.report_target_uid WHERE f.report_id=? ORDER BY ft.finding_id,ft.position,ft.id",(rid,)).fetchall())
def _finding_targets(cur,fid):
    return _finding_target_rows(cur.execute("SELECT ft.finding_id,ft.report_target_uid,ft.keys FROM ReportFindingTargets ft JOIN ReportFindings f ON f.id=ft.finding_id JOIN ReportTargets t ON t.report_id=f.report_id AND t.uid=ft.report_target_uid WHERE ft.finding_id=? ORDER BY ft.position,ft.id",(fid,)).fetchall()).get(int(fid),[])
def _set_finding_targets(cur,fid,rid,v):
    """Replace the linked targets of a finding: [{uid (a link of the same report), keys:[value keys to show]}]. Unknown uids are dropped."""
    valid={r[0] for r in cur.execute("SELECT uid FROM ReportTargets WHERE report_id=?",(rid,)).fetchall()}
    cur.execute("DELETE FROM ReportFindingTargets WHERE finding_id=?",(fid,))
    seen=set();pos=0
    for e in (v if isinstance(v,(list,tuple)) else []):
        if isinstance(e,str):e={"uid":e}
        if not isinstance(e,dict):continue
        uid=_s(e.get("uid"))
        if uid not in valid or uid in seen:continue
        seen.add(uid)
        keys=[]
        for k in _str_list(e.get("keys"),40,80):
            if _TV_KEY_RX.fullmatch(k) and k not in keys:keys.append(k)
        cur.execute("INSERT INTO ReportFindingTargets(finding_id,report_target_uid,keys,position) VALUES(?,?,?,?)",(fid,uid,_dump(keys),pos))
        pos+=1
# A reference to a linked target's value in rich text: <span class="rpt-tv" data-target="LINK UID" data-key="KEY">text</span>. The text is
# only a copy: it is rewritten from the link snapshot on every save and at export, so "Update from target" reaches the whole report.
_TV_RX=re.compile(r'(<span class="rpt-tv" data-target="([A-Za-z0-9_-]{1,64})" data-key="([^"<>]{1,480})">)([^<]*)</span>')
TV_WITHHELD="[withheld]"
ENGAGEMENT_LABELS={"not_started":"Not started","in_progress":"In progress","compromised":"Compromised","reported":"Reported"}
def links_by_uid(links):
    if isinstance(links,dict):return links
    return {l["uid"]:l for l in links or [] if isinstance(l,dict) and l.get("uid")}
def target_value(links,uid,key):
    """The current text of a reference (key: a value key, "@name" or "@status"); None when the link or the value is not available."""
    l=links_by_uid(links).get(_s(uid))
    if not l:return None
    key=_s(key)
    if key=="@name":return _s(l.get("name"))
    snap=l.get("snapshot") if isinstance(l.get("snapshot"),dict) else {}
    if key=="@status":return ENGAGEMENT_LABELS.get(_s(snap.get("engagement_status")),"Not started")
    vals=snap.get("values") if isinstance(snap.get("values"),dict) else {}
    allow={_s(k).lower() for k in l.get("allowed_secret_keys") or []}
    for k,v in vals.items():
        if k==key or k.lower()==key.lower():return None if is_secret_key(k) and k.lower() not in allow else _s(v)
    return None
def resolve_target_values(markup,links,plain=False):
    """Rewrite the text of every reference from the link snapshots (plain=True drops the wrapper). A reference that no longer resolves
    keeps its last text, unless its key is a protected one: then the text is withheld."""
    markup=markup or ""
    if "rpt-tv" not in markup:return markup
    by=links_by_uid(links)
    def one(m):
        key=html.unescape(m.group(3))
        v=target_value(by,m.group(2),key)
        text=html.escape(v,quote=False) if v is not None else (html.escape(TV_WITHHELD) if is_secret_key(key) else m.group(4))
        return text if plain else m.group(1)+text+"</span>"
    return _TV_RX.sub(one,markup)
def _tv_refresh(cur,rid,markup):
    return resolve_target_values(markup,_load_targets(cur,rid)) if "rpt-tv" in (markup or "") else markup
def _tv_refresh_finding(cur,rid,f):
    if not any("rpt-tv" in (f.get(k) or "") for k in _RICH_FIELDS):return
    links=links_by_uid(_load_targets(cur,rid))
    for k in _RICH_FIELDS:f[k]=resolve_target_values(f.get(k),links)
def _tv_refresh_report(cur,rid):
    """After the links changed: bring every stored reference of the report in line with them."""
    links=None
    for sid,content in cur.execute("SELECT id,content FROM ReportSections WHERE report_id=? AND content LIKE '%rpt-tv%'",(rid,)).fetchall():
        links=links_by_uid(_load_targets(cur,rid)) if links is None else links
        new=resolve_target_values(content,links)
        if new!=content:cur.execute("UPDATE ReportSections SET content=? WHERE id=?",(new,sid))
    for fid,data in cur.execute("SELECT id,data FROM ReportFindings WHERE report_id=? AND data LIKE '%rpt-tv%'",(rid,)).fetchall():
        links=links_by_uid(_load_targets(cur,rid)) if links is None else links
        d=_json_obj(data);hit=False
        for k in _RICH_FIELDS:
            if isinstance(d.get(k),str):
                new=resolve_target_values(d[k],links)
                if new!=d[k]:d[k]=new;hit=True
        if hit:cur.execute("UPDATE ReportFindings SET data=? WHERE id=?",(_dump(d),fid))
def targets_available(query=None):
    """Every target of every profile for the link picker. Secret keys are listed by name only; their values never leave the Targets store here."""
    live=_Live();q=_s(query).lower();out=[]
    for p in sorted(live.profiles,key=lambda p:(not p["active"],p["name"].lower())):
        for t in live.targets(p["id"]):
            vals=_public_values(t["values"])
            if q and q not in (t["name"]+" "+p["name"]+" "+" ".join(k+" "+v for k,v in vals.items())).lower():continue
            out.append({"target_id":t["id"],"profile_id":p["id"],"profile_name":p["name"],"profile_active":p["active"],"name":t["name"],"live":p["active"] and t["status"]=="live","values":vals,"secret_keys":_secret_names(t["values"]),"engagement_status":t["engagement_status"]})
    return out
def targets_list(report_id):
    with _db() as con:
        cur=con.cursor()
        return _load_targets(cur,_require_report(cur,report_id))
def _link_row(cur,rid,uid):
    row=cur.execute(f"SELECT {_RT_COLS} FROM ReportTargets WHERE report_id=? AND uid=?",(rid,_s(uid))).fetchone()
    if not row:raise ValueError("That target is not linked to this report.")
    return row
def target_link(report_id,items):
    """Link targets [{target_id,profile_id}] to the report as scope; each link stores a snapshot of the non-secret values. Already linked targets are skipped."""
    if isinstance(items,dict):items=[items]
    if not isinstance(items,(list,tuple)):raise ValueError("Choose at least one target.")
    now=_now();live=_Live()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        have={(r[0] or "",r[1] or "") for r in cur.execute("SELECT profile_id,target_id FROM ReportTargets WHERE report_id=?",(rid,)).fetchall()}
        add=[]
        for it in items:
            if not isinstance(it,dict):continue
            pid=_s(it.get("profile_id"),64);tid=_s(it.get("target_id"),64)
            if (pid,tid) in have:continue
            t=live.get(pid,tid)
            if t is None:raise ValueError("Target not found. It may have been deleted on the Targets page.")
            have.add((pid,tid))
            add.append({"target_id":tid,"profile_id":pid,"name":t["name"],"snapshot":_norm_snapshot(t),"allowed_secret_keys":[]})
        if len(have)>_LINK_MAX:raise ValueError(f"A report can link at most {_LINK_MAX} targets.")
        _insert_targets(cur,rid,add,now)
        if add:_touch(cur,rid,now)
        return _load_targets(cur,rid,live)
def target_unlink(report_id,uid):
    """Remove a link; findings of the report stop listing that target. Text already written keeps its last value."""
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        _link_row(cur,rid,uid)
        cur.execute("DELETE FROM ReportFindingTargets WHERE report_target_uid=? AND finding_id IN (SELECT id FROM ReportFindings WHERE report_id=?)",(_s(uid),rid))
        cur.execute("DELETE FROM ReportTargets WHERE report_id=? AND uid=?",(rid,_s(uid)))
        for i,r in enumerate(cur.execute("SELECT id FROM ReportTargets WHERE report_id=? ORDER BY position,id",(rid,)).fetchall()):cur.execute("UPDATE ReportTargets SET position=? WHERE id=?",(i,r[0]))
        _tv_refresh_report(cur,rid)
        _touch(cur,rid,now)
        return _load_targets(cur,rid)
def target_update(report_id,uid=None):
    """Take the target's current name, non-secret values and engagement status into the link ("Update from target"). uid None = every link whose target still exists."""
    now=_now();live=_Live()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        rows=[_link_row(cur,rid,uid)] if uid not in (None,"") else cur.execute(f"SELECT {_RT_COLS} FROM ReportTargets WHERE report_id=?",(rid,)).fetchall()
        n=0
        for r in rows:
            t=live.get(r[2] or "",r[1] or "")
            if t is None:
                if uid not in (None,""):raise ValueError("This target was removed from the Targets page; the report keeps its last snapshot.")
                continue
            cur.execute("UPDATE ReportTargets SET name=?,snapshot=?,updated_at=? WHERE report_id=? AND uid=?",(t["name"],_dump(_norm_snapshot(t,_allowed_keys(_json_list(r[5])))),now,rid,r[0]))
            n+=1
        if n:
            _tv_refresh_report(cur,rid)
            _touch(cur,rid,now)
        return _load_targets(cur,rid,live)
def target_allow_secret(report_id,uid,key,allow=True):
    """Explicitly allow (or withdraw) one secret key of a linked target: only then is its value copied into the report's snapshot."""
    key=_s(key,80);now=_now();live=_Live()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        r=_link_row(cur,rid,uid)
        allowed=_allowed_keys(_json_list(r[5]));snap=_norm_snapshot(_json_obj(r[4]),allowed)
        if _bool(allow,True):
            if not is_secret_key(key) or not _TV_KEY_RX.fullmatch(key):raise ValueError("That value is not a protected one; it is already available.")
            t=live.get(r[2] or "",r[1] or "")
            if t is None:raise ValueError("This target was removed from the Targets page; its protected values are no longer available.")
            name=next((k for k in t["values"] if k.lower()==key.lower() and _s(t["values"][k])),"")
            if not name:raise ValueError("The target has no value for that key.")
            if name not in allowed:allowed.append(name)
            snap["values"][name]=_s(t["values"][name],2000)
        else:
            allowed=[k for k in allowed if k.lower()!=key.lower()]
            snap["values"]={k:v for k,v in snap["values"].items() if k.lower()!=key.lower()}
        cur.execute("UPDATE ReportTargets SET snapshot=?,allowed_secret_keys=?,updated_at=? WHERE report_id=? AND uid=?",(_dump(snap),_dump(allowed),now,rid,r[0]))
        _tv_refresh_report(cur,rid)
        _touch(cur,rid,now)
        return _load_targets(cur,rid,live)
def targets_reorder(report_id,uids):
    if not isinstance(uids,(list,tuple)):raise ValueError("Invalid order.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        have=[r[0] for r in cur.execute("SELECT uid FROM ReportTargets WHERE report_id=? ORDER BY position,id",(rid,)).fetchall()]
        want=[]
        for u in uids:
            u=_s(u)
            if u in have and u not in want:want.append(u)
        want+=[u for u in have if u not in want]
        for i,u in enumerate(want):cur.execute("UPDATE ReportTargets SET position=? WHERE report_id=? AND uid=?",(i,rid,u))
        _touch(cur,rid,now)
        return _load_targets(cur,rid)
def finding_targets_set(finding_id,targets):
    """Which linked targets a finding affects: [{uid,keys:[value keys to show]}]. Returns the finding."""
    now=_now()
    with _db() as con:
        cur=con.cursor()
        f=_finding_by_id(cur,finding_id)
        _set_finding_targets(cur,f["id"],f["report_id"],targets)
        cur.execute("UPDATE ReportFindings SET updated_at=? WHERE id=?",(now,f["id"]))
        _touch(cur,f["report_id"],now)
        return _finding_by_id(cur,f["id"])
def targets_state(report_id):
    """Everything the links of a report consist of, as targets_restore takes it back (the page keeps it for undo / redo)."""
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        return {"targets":[_link_payload(l) for l in _load_targets(cur,rid)],"findings":{str(k):v for k,v in _finding_targets_map(cur,rid).items()}}
def targets_restore(report_id,state):
    """Put the links of a report back to a state taken with targets_state. Returns {targets,findings:{finding id:[{uid,keys}]}}."""
    if not isinstance(state,dict) or not isinstance(state.get("targets"),list):raise ValueError("Invalid scope state.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        _delete_report_targets(cur,rid)
        _insert_targets(cur,rid,state["targets"],now)
        mine={int(r[0]) for r in cur.execute("SELECT id FROM ReportFindings WHERE report_id=?",(rid,)).fetchall()}
        for fid,links in (state.get("findings") if isinstance(state.get("findings"),dict) else {}).items():
            try:fid=int(fid)
            except (TypeError,ValueError):continue
            if fid in mine:_set_finding_targets(cur,fid,rid,links)
        _tv_refresh_report(cur,rid)
        _touch(cur,rid,now)
        return {"targets":_load_targets(cur,rid),"findings":{str(k):v for k,v in _finding_targets_map(cur,rid).items()}}
# ---- reports
def _report_head(cur,rid):
    row=cur.execute("SELECT id,uid,title,status,template_id,profile_id,meta,branding,options,created_at,updated_at FROM Reports WHERE id=?",(rid,)).fetchone()
    if not row:raise ValueError("Report not found.")
    return {"id":int(row[0]),"uid":row[1],"title":row[2] or "","status":row[3] if row[3] in REPORT_STATUSES else "draft","template_id":row[4] or "","profile_id":row[5] or "","created_at":row[9] or "","updated_at":row[10] or "","meta":_norm_meta(_json_obj(row[6])),"branding":_norm_branding(_json_obj(row[7])),"options":_norm_options(_json_obj(row[8]))}
def _load_report(cur,rid):
    rep=_report_head(cur,rid)
    rep["sections"]=_load_sections(cur,rid)
    rep["targets"]=_load_targets(cur,rid)
    rep["findings"]=_load_findings(cur,rid)
    rep["versions"]=_versions(cur,rid)
    rep["stats"]=_report_stats(rep["findings"])
    return rep
def get_report(report_id):
    """Full report dict (the bridge's reports.get). Accepts the numeric id or the uid. Raises ValueError("Report not found.")."""
    with _db() as con:
        cur=con.cursor()
        return _load_report(cur,_require_report(cur,report_id))
def list_reports():
    names={p["id"]:p["name"] for p in _profile_list()}
    out=[]
    with _db() as con:
        cur=con.cursor()
        counts={}
        for rid,sev,n in cur.execute("SELECT report_id,severity,COUNT(*) FROM ReportFindings GROUP BY report_id,severity"):
            counts.setdefault(int(rid),{k:0 for k in SEVERITIES})[_sev(sev,strict=False)]+=int(n)
        for r in cur.execute("SELECT id,uid,title,status,template_id,profile_id,meta,created_at,updated_at FROM Reports ORDER BY updated_at DESC,id DESC"):
            c=counts.get(int(r[0]),{k:0 for k in SEVERITIES})
            out.append({"id":int(r[0]),"uid":r[1],"title":r[2] or "","status":r[3] if r[3] in REPORT_STATUSES else "draft","client":_s(_json_obj(r[6]).get("client")),"profile_id":r[5] or "","profile_name":names.get(r[5] or "",""),"template_id":r[4] or "","updated_at":r[8] or "","created_at":r[7] or "","counts":c,"total":sum(c.values())})
    return out
def create_report(payload=None):
    """payload {title, template_id?, profile_id?, meta?, branding?, options?}; also accepted: status, sections (replaces the template's),
    findings, uid (kept when free) - used by import and auto-generation."""
    p=payload if isinstance(payload,dict) else {}
    tid=_s(p.get("template_id")) or "blank"
    tpl=template_get(tid)
    defaults=defaults_get()
    meta={"classification":defaults["classification"],"testers":defaults["testers"],"version":"1.0","report_date":datetime.now().strftime("%Y-%m-%d"),"authors":", ".join(t["name"] for t in defaults["testers"] if t["name"])}
    for k,v in (tpl.get("meta") or {}).items():
        if v not in ("",None,[]):meta[k]=v
    pid=_s(p.get("profile_id"),64)
    if pid:
        prof=next((x for x in _profile_list() if x["id"]==pid),None)
        if not prof:pid=""
        else:
            meta["engagement"]=prof["name"]
            meta["scope_in"]=[_target_scope_line(t) for t in _profile_targets(pid)]
    if isinstance(p.get("meta"),dict):meta.update(p["meta"])
    meta=_norm_meta(meta)
    branding=_norm_branding(p.get("branding"),_norm_branding(defaults["branding"]))
    options=_norm_options({"page_size":defaults["page_size"],"include_toc":defaults["include_toc"],"include_appendices":defaults["include_appendices"]})
    options=_norm_options(tpl.get("options"),options)
    options=_norm_options(p.get("options"),options)
    status=_s(p.get("status")).lower()
    if status not in REPORT_STATUSES:status="draft"
    now=_now()
    with _db() as con:
        cur=con.cursor()
        uid=_s(p.get("uid"))
        if not _UID_RX.match(uid) or cur.execute("SELECT 1 FROM Reports WHERE uid=?",(uid,)).fetchone():uid=_uid()
        cur.execute("INSERT INTO Reports(uid,title,status,template_id,profile_id,meta,branding,options,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(uid,_s(p.get("title"),TITLE_MAX) or "Untitled report",status,tpl["id"],pid,_dump(meta),_dump(branding),_dump(options),now,now))
        rid=int(cur.lastrowid)
        _insert_sections(cur,rid,p["sections"] if isinstance(p.get("sections"),list) else tpl["sections"],now)
        if isinstance(p.get("targets"),list):_insert_targets(cur,rid,p["targets"],now)
        if isinstance(p.get("findings"),list):_insert_findings(cur,rid,p["findings"],now)
        return _load_report(cur,rid)
def update_report(report_id,patch):
    if not isinstance(patch,dict):raise ValueError("Invalid report data.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        head=_report_head(cur,rid)
        sets=["updated_at=?"];vals=[now]
        if "title" in patch:
            t=_s(patch["title"],TITLE_MAX)
            if not t:raise ValueError("A report needs a title.")
            sets.append("title=?");vals.append(t)
        if "status" in patch:
            st=_s(patch["status"]).lower()
            if st not in REPORT_STATUSES:raise ValueError("Invalid report status.")
            sets.append("status=?");vals.append(st)
        if "profile_id" in patch:
            pid=_s(patch["profile_id"],64)
            if pid and not any(x["id"]==pid for x in _profile_list()):raise ValueError("Engagement profile not found.")
            sets.append("profile_id=?");vals.append(pid)
        if isinstance(patch.get("meta"),dict):sets.append("meta=?");vals.append(_dump(_norm_meta(patch["meta"],head["meta"])))
        if isinstance(patch.get("branding"),dict):sets.append("branding=?");vals.append(_dump(_norm_branding(patch["branding"],head["branding"])))
        if isinstance(patch.get("options"),dict):sets.append("options=?");vals.append(_dump(_norm_options(patch["options"],head["options"])))
        cur.execute("UPDATE Reports SET "+",".join(sets)+" WHERE id=?",vals+[rid])
    return {"id":rid,"updated_at":now}
def duplicate_report(report_id):
    now=_now()
    with _db() as con:
        cur=con.cursor()
        src=_load_report(cur,_require_report(cur,report_id))
        title=(src["title"][:TITLE_MAX-7]+" (copy)")
        cur.execute("INSERT INTO Reports(uid,title,status,template_id,profile_id,meta,branding,options,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(_uid(),title,"draft",src["template_id"],src["profile_id"],_dump({k:v for k,v in src["meta"].items() if k!="schedule_fired"}),_dump(src["branding"]),_dump(src["options"]),now,now))
        rid=int(cur.lastrowid)
        _insert_sections(cur,rid,src["sections"],now)
        # Link uids are kept: the copied text and findings refer to them.
        _insert_targets(cur,rid,src["targets"],now)
        _insert_findings(cur,rid,src["findings"],now)
        return _load_report(cur,rid)
def _report_snapshot(rep):
    return {"v":1,"title":rep["title"],"status":rep["status"],"template_id":rep["template_id"],"profile_id":rep["profile_id"],"meta":rep["meta"],"branding":rep["branding"],"options":rep["options"],
        "sections":[{k:v for k,v in s.items() if k!="id"} for s in rep["sections"]],"findings":[_finding_payload(f) for f in rep["findings"]],"targets":[_link_payload(l) for l in rep.get("targets") or []]}
def delete_report(report_id):
    """Move the report (with its sections, findings and saved versions; not the image blobs) to the Recycle Bin."""
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        rep=_load_report(cur,rid)
        payload={"report":{"uid":rep["uid"],"created_at":rep["created_at"],"updated_at":rep["updated_at"],**_report_snapshot(rep)},
            "versions":[{"label":r[0] or "","snapshot":r[1],"created_at":r[2]} for r in cur.execute("SELECT label,snapshot,created_at FROM ReportVersions WHERE report_id=? ORDER BY id",(rid,)).fetchall()]}
        _recycle_bin.put_entry_cur(cur,TYPE_REPORT,rep["title"] or "Untitled report",payload,source=rep["meta"].get("client") or "Reports",entity_key=rep["uid"])
        _delete_report_targets(cur,rid)
        for t in ("ReportSections","ReportFindings","ReportVersions"):cur.execute(f"DELETE FROM {t} WHERE report_id=?",(rid,))
        cur.execute("DELETE FROM Reports WHERE id=?",(rid,))
    return True
def _restore_snapshot_rows(cur,rid,snap,now):
    if isinstance(snap.get("targets"),list):_insert_targets(cur,rid,snap["targets"],now)
    _insert_sections(cur,rid,snap.get("sections") if isinstance(snap.get("sections"),list) else [],now,keep_uid=True)
    _insert_findings(cur,rid,snap.get("findings") if isinstance(snap.get("findings"),list) else [],now,keep_uid=True)
def restore_from_bin(cur,entity_type,payload):
    """Recreate a deleted report or finding inside the Recycle Bin's own transaction (called by recycle_bin.restore_entry)."""
    now=_now()
    if entity_type==TYPE_REPORT:
        rep=payload.get("report") if isinstance(payload.get("report"),dict) else None
        if not rep or not _s(rep.get("title")):raise ValueError("Recycle Bin report payload is invalid.")
        uid=_s(rep.get("uid"))
        if not _UID_RX.match(uid) or cur.execute("SELECT 1 FROM Reports WHERE uid=?",(uid,)).fetchone():uid=_uid()
        status=rep.get("status") if rep.get("status") in REPORT_STATUSES else "draft"
        cur.execute("INSERT INTO Reports(uid,title,status,template_id,profile_id,meta,branding,options,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(uid,_s(rep.get("title"),TITLE_MAX),status,_s(rep.get("template_id"),64),_s(rep.get("profile_id"),64),_dump(_norm_meta(rep.get("meta"))),_dump(_norm_branding(rep.get("branding"))),_dump(_norm_options(rep.get("options"))),_s(rep.get("created_at")) or now,now))
        rid=int(cur.lastrowid)
        _restore_snapshot_rows(cur,rid,rep,now)
        for v in payload.get("versions") if isinstance(payload.get("versions"),list) else []:
            if isinstance(v,dict) and isinstance(v.get("snapshot"),str):cur.execute("INSERT INTO ReportVersions(report_id,label,snapshot,created_at) VALUES(?,?,?,?)",(rid,_s(v.get("label"),200),v["snapshot"],_s(v.get("created_at")) or now))
        return rid
    if entity_type==TYPE_REPORT_FINDING:
        src=payload.get("finding") if isinstance(payload.get("finding"),dict) else None
        if not src:raise ValueError("Recycle Bin finding payload is invalid.")
        row=cur.execute("SELECT id FROM Reports WHERE uid=?",(_s(payload.get("report_uid")),)).fetchone()
        if not row:raise ValueError("The report this finding belonged to no longer exists. Restore the report first.")
        rid=int(row[0])
        f=_apply_finding_patch(_finding_blank(),src,creating=True,strict=False)
        uid=_s(src.get("uid"))
        if cur.execute("SELECT 1 FROM ReportFindings WHERE uid=?",(uid,)).fetchone():uid=""
        ids=[r[0] for r in cur.execute("SELECT id FROM ReportFindings WHERE report_id=? ORDER BY position,id",(rid,)).fetchall()]
        fid=_insert_finding(cur,rid,f,len(ids),now,uid=uid,created_at=_s(src.get("created_at")))
        if src.get("targets"):_set_finding_targets(cur,fid,rid,src["targets"])
        try:pos=max(0,min(len(ids),int(src.get("position",len(ids)))))
        except (TypeError,ValueError):pos=len(ids)
        ids.insert(pos,fid)
        _renumber(cur,"ReportFindings",rid,ids)
        _touch(cur,rid,now)
        return fid
    raise ValueError("Unsupported Recycle Bin item.")
# ---- versions (snapshots)
def _versions(cur,rid):
    return [{"id":int(r[0]),"label":r[1] or "","created_at":r[2] or ""} for r in cur.execute("SELECT id,label,created_at FROM ReportVersions WHERE report_id=? ORDER BY created_at DESC,id DESC",(rid,)).fetchall()]
def versions(report_id):
    with _db() as con:
        cur=con.cursor()
        return _versions(cur,_require_report(cur,report_id))
def _version_create(cur,rid,label,now):
    rep=_load_report(cur,rid)
    lab=_s(label,200) or ("Version "+(rep["meta"].get("version") or "")).strip()+" - "+now[:16].replace("T"," ")
    cur.execute("INSERT INTO ReportVersions(report_id,label,snapshot,created_at) VALUES(?,?,?,?)",(rid,lab,_dump(_report_snapshot(rep)),now))
    return {"id":int(cur.lastrowid),"label":lab,"created_at":now}
def version_create(report_id,label=""):
    with _db() as con:
        cur=con.cursor()
        return _version_create(cur,_require_report(cur,report_id),label,_now())
def version_restore(report_id,version_id):
    """Replace the report's content with a saved version. The current state is saved as a new version first, so a restore can be undone."""
    now=_now()
    with _db() as con:
        cur=con.cursor()
        rid=_require_report(cur,report_id)
        row=cur.execute("SELECT label,snapshot FROM ReportVersions WHERE id=? AND report_id=?",(_int(version_id,"Version not found."),rid)).fetchone()
        if not row:raise ValueError("Version not found.")
        snap=_json_obj(row[1])
        if not snap:raise ValueError("This version cannot be read.")
        _version_create(cur,rid,"Before restoring \""+(row[0] or "version")[:150]+"\"",now)
        status=snap.get("status") if snap.get("status") in REPORT_STATUSES else "draft"
        cur.execute("UPDATE Reports SET title=?,status=?,template_id=?,profile_id=?,meta=?,branding=?,options=?,updated_at=? WHERE id=?",(_s(snap.get("title"),TITLE_MAX) or "Untitled report",status,_s(snap.get("template_id"),64),_s(snap.get("profile_id"),64),_dump(_norm_meta(snap.get("meta"))),_dump(_norm_branding(snap.get("branding"))),_dump(_norm_options(snap.get("options"))),now,rid))
        cur.execute("DELETE FROM ReportSections WHERE report_id=?",(rid,))
        # A version saved before targets could be linked says nothing about them: the current links stay.
        _delete_report_targets(cur,rid,links=isinstance(snap.get("targets"),list))
        cur.execute("DELETE FROM ReportFindings WHERE report_id=?",(rid,))
        _restore_snapshot_rows(cur,rid,snap,now)
        return _load_report(cur,rid)
def version_delete(version_id):
    with _db() as con:
        cur=con.cursor()
        cur.execute("DELETE FROM ReportVersions WHERE id=?",(_int(version_id,"Version not found."),))
        if not cur.rowcount:raise ValueError("Version not found.")
    purge_orphan_assets()
    return True
# ---- templates
_TEMPLATE_META_KEYS=("report_type","methodology","classification","rules_of_engagement")
def _builtin_template(tid):
    for t in _tpl.BUILTIN:
        if t["id"]==tid:return t
    return None
def _template_out(tid,name,description,builtin,data):
    secs=[]
    for s in data.get("sections") if isinstance(data.get("sections"),list) else []:
        if isinstance(s,dict):secs.append({"kind":_kind(s.get("kind")),"title":_s(s.get("title"),TITLE_MAX),"content":s.get("content") or "","hidden":_bool(s.get("hidden"))})
    meta=data.get("meta") if isinstance(data.get("meta"),dict) else {}
    return {"id":tid,"name":name,"description":description,"builtin":builtin,"sections":secs,"meta":{k:_s(meta.get(k),_META_STR[k]) for k in _TEMPLATE_META_KEYS if _s(meta.get(k))},"options":_template_options(data.get("options"))}
def _template_options(src):
    if not isinstance(src,dict):return {}
    full=_norm_options(src)
    return {k:full[k] for k in _OPTIONS_DEFAULT if k in src}
def templates():
    out=[{"id":t["id"],"name":t["name"],"description":t["description"],"builtin":True,"sections":len(t["sections"])} for t in _tpl.BUILTIN]
    with _db() as con:
        for r in con.execute("SELECT uid,name,description,data FROM ReportTemplates ORDER BY name COLLATE NOCASE,id"):
            secs=_json_obj(r[3]).get("sections")
            out.append({"id":r[0],"name":r[1] or "","description":r[2] or "","builtin":False,"sections":len(secs) if isinstance(secs,list) else 0})
    return out
def template_get(template_id):
    tid=_s(template_id)
    b=_builtin_template(tid)
    if b:
        t=_template_out(b["id"],b["name"],b["description"],True,b)
        for s in t["sections"]:s["content"]=sanitize_html(s["content"])
        return t
    if not _UID_RX.match(tid):raise ValueError("Template not found.")
    with _db() as con:
        row=con.execute("SELECT uid,name,description,data FROM ReportTemplates WHERE uid=?",(tid,)).fetchone()
    if not row:raise ValueError("Template not found.")
    return _template_out(row[0],row[1] or "",row[2] or "",False,_json_obj(row[3]))
def _template_data(src):
    secs=[]
    for s in src.get("sections") if isinstance(src.get("sections"),list) else []:
        if not isinstance(s,dict):continue
        kind=_kind(s.get("kind"))
        secs.append({"kind":kind,"title":_s(s.get("title"),TITLE_MAX) or _default_section_title(kind),"content":_rich(s.get("content")),"hidden":_bool(s.get("hidden"))})
        if len(secs)>=200:break
    meta=src.get("meta") if isinstance(src.get("meta"),dict) else {}
    return {"sections":secs,"meta":{k:_s(meta.get(k),_META_STR[k]) for k in _TEMPLATE_META_KEYS if _s(meta.get(k))},"options":_template_options(src.get("options"))}
def template_save(template):
    """Create a user template, or update one when `id` names an existing user template. Built-in templates are never overwritten: saving one makes a copy."""
    if not isinstance(template,dict):raise ValueError("Invalid template.")
    name=_s(template.get("name"),120)
    if not name:raise ValueError("A template needs a name.")
    desc=_s(template.get("description"),500)
    data=_dump(_template_data(template))
    tid=_s(template.get("id"))
    now=_now()
    with _db() as con:
        cur=con.cursor()
        exists=bool(tid) and _UID_RX.match(tid) and not _builtin_template(tid) and cur.execute("SELECT 1 FROM ReportTemplates WHERE uid=?",(tid,)).fetchone()
        if exists:cur.execute("UPDATE ReportTemplates SET name=?,description=?,data=?,updated_at=? WHERE uid=?",(name,desc,data,now,tid))
        else:
            tid=_uid()
            cur.execute("INSERT INTO ReportTemplates(uid,name,description,data,created_at,updated_at) VALUES(?,?,?,?,?,?)",(tid,name,desc,data,now,now))
    return template_get(tid)
def template_save_from_report(report_id,name,description=""):
    rep=get_report(report_id)
    return template_save({"name":_s(name) or rep["title"],"description":description,"sections":[{"kind":s["kind"],"title":s["title"],"content":s["content"],"hidden":s["hidden"]} for s in rep["sections"]],"meta":{k:rep["meta"].get(k,"") for k in _TEMPLATE_META_KEYS},"options":rep["options"]})
def template_delete(template_id):
    tid=_s(template_id)
    if _builtin_template(tid):raise ValueError("Built-in templates cannot be deleted.")
    with _db() as con:
        cur=con.cursor()
        cur.execute("DELETE FROM ReportTemplates WHERE uid=?",(tid,))
        if not cur.rowcount:raise ValueError("Template not found.")
    return True
# ---- findings library
_LIB_COLS="id,uid,title,category,severity,cvss_vector,cvss_score,data,created_at,updated_at"
_LIB_DATA_KEYS=("cwe","owasp","references","description","impact","likelihood","steps","remediation","tags","retest_notes","source","cves")
def _lib_dict(r):
    f=_finding_blank()
    data=_json_obj(r[7])
    for k in _LIB_DATA_KEYS:
        if k in data and type(data[k])==type(f[k]):f[k]=data[k]
    out={"id":int(r[0]),"uid":r[1] or "","title":r[2] or "","category":r[3] or "","severity":_sev(r[4],strict=False),"cvss_vector":r[5] or "","cvss_score":(float(r[6]) if r[6] is not None else None)}
    for k in _LIB_DATA_KEYS:out[k]=f[k]
    out.update({"builtin":(r[1] or "").startswith("builtin-"),"created_at":r[8] or "","updated_at":r[9] or ""})
    return out
def _lib_data(f):return _dump({k:f[k] for k in _LIB_DATA_KEYS})
def _ensure_library(cur):
    """Seed the built-in entries once per data folder. The marker lives in settings.json; entries the user deleted are not brought back."""
    try:seeded=int(_stored_defaults().get("library_seed",0) or 0)
    except (TypeError,ValueError):seeded=0
    if seeded>=_LIBRARY_SEED_VERSION:return
    now=_now()
    for e in _tpl.LIBRARY:
        f=_apply_finding_patch(_finding_blank(),e,creating=True,strict=False)
        cur.execute("INSERT OR IGNORE INTO FindingLibrary(uid,title,category,severity,cvss_vector,cvss_score,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(e["uid"],f["title"],_s(e.get("category"),80),f["severity"],f["cvss_vector"],f["cvss_score"],_lib_data(f),now,now))
    def mark(d):
        r=d.get("reports") if isinstance(d.get("reports"),dict) else {}
        r["library_seed"]=_LIBRARY_SEED_VERSION
        d["reports"]=r
    _settings_lock.update_json(_settings_path(),mark)
def library_list():
    with _db() as con:
        cur=con.cursor()
        _ensure_library(cur)
        return [{"id":int(r[0]),"uid":r[1],"title":r[2] or "","category":r[3] or "","severity":_sev(r[4],strict=False),"cvss_vector":r[5] or "","cvss_score":(float(r[6]) if r[6] is not None else None),"updated_at":r[7] or "","builtin":(r[1] or "").startswith("builtin-")}
            for r in cur.execute("SELECT id,uid,title,category,severity,cvss_vector,cvss_score,updated_at FROM FindingLibrary ORDER BY category COLLATE NOCASE,title COLLATE NOCASE,id").fetchall()]
def _lib_by_id(cur,library_id):
    v=library_id
    if isinstance(v,str) and not v.strip().lstrip("-").isdigit():row=cur.execute(f"SELECT {_LIB_COLS} FROM FindingLibrary WHERE uid=?",(v.strip(),)).fetchone()
    else:row=cur.execute(f"SELECT {_LIB_COLS} FROM FindingLibrary WHERE id=?",(_int(v,"Library entry not found."),)).fetchone()
    if not row:raise ValueError("Library entry not found.")
    return _lib_dict(row)
def library_get(library_id):
    with _db() as con:
        cur=con.cursor()
        _ensure_library(cur)
        return _lib_by_id(cur,library_id)
def library_save(entry):
    """Create (no id) or update a library entry. Updates are merge patches."""
    if not isinstance(entry,dict):raise ValueError("Invalid library entry.")
    now=_now()
    with _db() as con:
        cur=con.cursor()
        _ensure_library(cur)
        if entry.get("id") not in (None,"",0):
            cur_e=_lib_by_id(cur,entry["id"])
            f=_finding_blank()
            for k in ("title","severity","cvss_vector","cvss_score")+_LIB_DATA_KEYS:f[k]=cur_e[k]
            _apply_finding_patch(f,entry)
            if not f["title"]:raise ValueError("A library entry needs a title.")
            cat=_s(entry["category"],80) if "category" in entry else cur_e["category"]
            cur.execute("UPDATE FindingLibrary SET title=?,category=?,severity=?,cvss_vector=?,cvss_score=?,data=?,updated_at=? WHERE id=?",(f["title"],cat,f["severity"],f["cvss_vector"],f["cvss_score"],_lib_data(f),now,cur_e["id"]))
            return _lib_by_id(cur,cur_e["id"])
        f=_apply_finding_patch(_finding_blank(),entry,creating=True)
        if not f["title"]:raise ValueError("A library entry needs a title.")
        cur.execute("INSERT INTO FindingLibrary(uid,title,category,severity,cvss_vector,cvss_score,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(_uid(),f["title"],_s(entry.get("category"),80),f["severity"],f["cvss_vector"],f["cvss_score"],_lib_data(f),now,now))
        return _lib_by_id(cur,int(cur.lastrowid))
def library_save_from_finding(finding_id,category=""):
    f=get_finding(finding_id)
    entry={k:f[k] for k in ("title","severity","cvss_vector","cvss_score")+_LIB_DATA_KEYS}
    entry["retest_notes"]=""
    entry["source"]={"kind":"","ref":""}
    entry["category"]=_s(category,80) or "Custom"
    return library_save(entry)
def library_delete(library_id):
    with _db() as con:
        cur=con.cursor()
        _ensure_library(cur)
        e=_lib_by_id(cur,library_id)
        cur.execute("DELETE FROM FindingLibrary WHERE id=?",(e["id"],))
    return True
def finding_from_library(report_id,library_id):
    e=library_get(library_id)
    fields={k:e[k] for k in ("title","severity","cvss_vector","cvss_score")+_LIB_DATA_KEYS}
    fields["retest_notes"]=""
    fields["source"]={"kind":"library","ref":e["uid"]}
    return add_finding(report_id,fields)
# ---- dashboard
def stats():
    """Cheap totals for the dashboard card: three small queries, no report bodies."""
    out={"reports":0,"by_status":{k:0 for k in REPORT_STATUSES},"findings":{k:0 for k in SEVERITIES},"open_by_severity":{k:0 for k in SEVERITIES},"open_findings":0,"recent":[],"next_deadline":None,"overdue":0}
    with _db() as con:
        cur=con.cursor()
        for st,n in cur.execute("SELECT status,COUNT(*) FROM Reports GROUP BY status"):
            out["by_status"][st if st in REPORT_STATUSES else "draft"]+=int(n)
            out["reports"]+=int(n)
        for sev,st,n in cur.execute("SELECT f.severity,f.status,COUNT(*) FROM ReportFindings f JOIN Reports r ON r.id=f.report_id GROUP BY f.severity,f.status"):
            out["findings"][_sev(sev,strict=False)]+=int(n)
            if st=="open":
                out["open_findings"]+=int(n)
                out["open_by_severity"][_sev(sev,strict=False)]+=int(n)
        out["recent"]=[{"id":int(r[0]),"title":r[1] or "","status":r[2] if r[2] in REPORT_STATUSES else "draft","updated_at":r[3] or ""} for r in cur.execute("SELECT id,title,status,updated_at FROM Reports ORDER BY updated_at DESC,id DESC LIMIT 5")]
        out["next_deadline"],out["overdue"]=_schedule.overview(cur)
    return out
def section_boilerplate(kind,report_id=None):
    """Starting text for a section kind (the built-in templates' boilerplate); the methodology follows the report's template."""
    tid=""
    if report_id not in (None,""):
        with _db() as con:
            cur=con.cursor()
            tid=(cur.execute("SELECT template_id FROM Reports WHERE id=?",(_require_report(cur,report_id),)).fetchone() or ("",))[0] or ""
    k=_kind(kind)
    return {"kind":k,"title":_default_section_title(k),"content":_sections.boilerplate(k,tid),"auto":k in _sections.AUTO_KINDS}
def cvss_calc(vector):return _cvss.calc(vector)
# ---- notes -> report
_DOM_PHRASING_ONLY=frozenset(("p","h1","h2","h3","h4","h5","h6"))
_DOM_BLOCKS=frozenset(("p","h1","h2","h3","h4","h5","h6","div","table","ul","ol","pre","blockquote","section","figure","hr"))
class _Dom(HTMLParser):
    """Small forgiving DOM, enough to walk a note's blocks."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root={"tag":"","attrs":{},"kids":[]}
        self.stack=[self.root]
    def handle_starttag(self,tag,attrs):
        n={"tag":tag.lower(),"attrs":{(k or "").lower():("" if v is None else v) for k,v in attrs},"kids":[]}
        # A block cannot sit inside a paragraph or heading: an unclosed one ends here, as it does in a browser.
        if n["tag"] in _DOM_BLOCKS and len(self.stack)>1 and self.stack[-1]["tag"] in _DOM_PHRASING_ONLY:self.stack.pop()
        self.stack[-1]["kids"].append(n)
        if n["tag"] not in _VOID_ANY and len(self.stack)<200:self.stack.append(n)
    def handle_endtag(self,tag):
        tag=tag.lower()
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i]["tag"]==tag:
                del self.stack[i:];break
    def handle_data(self,data):
        if data:self.stack[-1]["kids"].append(data)
def _dom(text):
    p=_Dom()
    try:
        p.feed(text or "");p.close()
    except Exception:pass
    return p.root
_TEXT_BLOCKS=frozenset(("p","div","li","tr","h1","h2","h3","h4","h5","h6","pre","blockquote","table","ul","ol","figure","figcaption","section"))
def _node_text(n):
    if isinstance(n,str):return n
    if n["tag"] in _DROP:return ""
    if n["tag"]=="br":return "\n"
    t="".join(_node_text(k) for k in n["kids"])
    if n["tag"] in ("td","th"):return t+"\t"
    return t+"\n" if n["tag"] in _TEXT_BLOCKS else t
def _text(n):return re.sub(r"[ \t\xa0]+"," ",_node_text(n)).strip()
def _node_html(n):
    if isinstance(n,str):return html.escape(n,quote=False)
    attrs="".join(f' {k}="{html.escape(v,quote=True)}"' for k,v in n["attrs"].items() if re.match(r"^[a-z][a-z0-9_:-]*$",k))
    if n["tag"] in _VOID_ANY:return f"<{n['tag']}{attrs}>"
    return f"<{n['tag']}{attrs}>"+"".join(_node_html(k) for k in n["kids"])+f"</{n['tag']}>"
_HEADINGS=("h1","h2","h3","h4","h5","h6")
_FINDING_CALLOUTS=("finding","vuln","vulnerability")
_VECTOR_RX=re.compile(r"(?:CVSS:3\.[01]/)?AV:[NALP]/AC:[LH]/PR:[NLH]/UI:[NR]/S:[UC]/C:[HLN]/I:[HLN]/A:[HLN]",re.I)
_SCORE_RX=re.compile(r"CVSS[^0-9\n]{0,24}?(10(?:\.0)?|\d(?:\.\d)?)(?![\d.])",re.I)
_CWE_RX=re.compile(r"\bCWE-\d{1,5}\b",re.I)
_OWASP_RX=re.compile(r"\b(?:A(?:0[1-9]|10):20\d{2}|M(?:[1-9]|10):20\d{2}|API(?:[1-9]|10):20\d{2})\b(?:\s*[-\u2013:]?\s*[A-Z][A-Za-z ,()/&-]{2,60})?")
_URL_RX=re.compile(r"https?://[^\s<>\"')\]]+",re.I)
_SEV_WORD=r"critical|high|medium|moderate|low|informational|info"
_TITLE_PREFIX_RX=re.compile(r"^(?:finding|vulnerability|vuln|issue)\s*(?:#?\s*\d+)?\s*[:\-\u2013\u2014]\s*(.+)$",re.I|re.S)
_TITLE_BRACKET_RX=re.compile(rf"^\[\s*({_SEV_WORD})\s*\]\s*[:\-\u2013\u2014]?\s*(.+)$",re.I|re.S)
_TITLE_SEV_SUFFIX_RX=re.compile(rf"\s*[\(\[]\s*({_SEV_WORD})\s*[\)\]]\s*$",re.I)
_SECTION_NAMES=(
    ("description",("description","details","summary","overview","issue","background")),
    ("steps",("steps to reproduce","reproduction steps","reproduction","steps","proof of concept","poc","evidence","exploitation","how to reproduce")),
    ("impact",("impact","risk","business impact")),
    ("remediation",("remediation","recommendation","recommendations","fix","mitigation","solution","how to fix")),
    ("references",("references","reference","links","further reading")),
)
def _section_key(text):
    t=re.sub(r"[:\s]+$","",(text or "").strip().lower())
    for key,names in _SECTION_NAMES:
        if t in names:return key
    return ""
def _is_callout(n):
    if isinstance(n,str):return False
    a=n["attrs"]
    return a.get("data-callout","").strip().lower() in _FINDING_CALLOUTS or "note-finding" in a.get("class","").split()
_CALLOUT_COUNT_RX=re.compile(r"""data-callout\s*=\s*["']?(?:finding|vuln|vulnerability)\b""",re.I)
_HEADING_COUNT_RX=re.compile(rf"<(?:h[1-6]|p|div)\b[^>]*>\s*(?:<(?:strong|b|span|em|u)\b[^>]*>\s*)*(?:(?:finding|vulnerability|vuln)\s*(?:#?\s*\d+)?\s*[:\-\u2013\u2014]|\[\s*(?:{_SEV_WORD})\s*\])",re.I)
def _count_note_findings(content):
    if not content or "<" not in content:return 0
    n=len(_CALLOUT_COUNT_RX.findall(content))
    return n or len(_HEADING_COUNT_RX.findall(content))
def _only_bold(n):
    """True for a paragraph whose whole text is bold (used as a heading by people who do not use heading styles)."""
    if isinstance(n,str) or n["tag"] not in ("p","div"):return False
    kids=[k for k in n["kids"] if not (isinstance(k,str) and not k.strip()) and not (isinstance(k,dict) and k["tag"]=="br")]
    return len(kids)==1 and isinstance(kids[0],dict) and kids[0]["tag"] in ("strong","b") and bool(_text(kids[0]))
def _table_pairs(n):
    """th/td (or td/td) rows of a key/value table -> {lower key: value node}"""
    out={}
    def rows(x):
        for k in x["kids"]:
            if isinstance(k,str):continue
            if k["tag"]=="tr":yield k
            elif k["tag"] in ("tbody","thead","tfoot"):yield from rows(k)
    for tr in rows(n):
        cells=[c for c in tr["kids"] if isinstance(c,dict) and c["tag"] in ("th","td")]
        if len(cells)!=2:return {}
        key=re.sub(r"[:\s]+$","",_text(cells[0]).lower())
        if key:out[key]=cells[1]
    return out
_TABLE_KEYS={"severity":"severity","risk":"severity","rating":"severity","cvss":"cvss","cvss score":"cvss","cvss vector":"cvss","cvss v3.1":"cvss","cvss 3.1":"cvss","affected hosts":"affected","affected":"affected","affected assets":"affected","affected host":"affected","hosts":"affected","host":"affected","assets":"affected","target":"affected","targets":"affected","references":"references","reference":"references","cwe":"cwe","owasp":"owasp","status":"status"}
# ---- the Notes editor's blocks (UI/js/pages/notes_pro.js) -> subset markup, applied to the parsed note before the sanitiser runs
_CALLOUT_LABELS={"finding":"Finding","vuln":"Vulnerability","vulnerability":"Vulnerability","info":"Info","warning":"Warning","evidence":"Evidence","credential":"Credential"}
_SECRET_LINE_RX=re.compile(r"^(\s*(?:secret|password|passwd|pass|pwd|passphrase|(?:ntlm|nt|lm)?[ _-]?hash|ntlm|(?:api|private|ssh|access|secret)?[ _-]?key|(?:access|bearer|session)?[ _-]?token|pin|cookie)\s*[:=]\s*)(\S.*)$",re.I|re.S)
_LEAF_BLOCKS=frozenset(("p","div","li","td","th","h1","h2","h3","h4","h5","h6","pre"))
def _el(tag,kids=None,**attrs):return {"tag":tag,"attrs":{k.replace("_","-"):v for k,v in attrs.items()},"kids":list(kids or [])}
def _classes(n):return n["attrs"].get("class","").split()
def _callout_kind(n):
    if isinstance(n,str):return ""
    k=n["attrs"].get("data-callout","").strip().lower()
    if k in _CALLOUT_LABELS:return "vuln" if k=="vulnerability" else k
    cls=_classes(n)
    if "note-finding" in cls:return "finding"
    return "info" if "note-callout" in cls else ""
def _callout_label(n,kind):
    label=_CALLOUT_LABELS[kind]
    if kind in ("finding","vuln"):
        a=n["attrs"]
        sev=_sev(a.get("data-sev") or a.get("data-severity"),strict=False,default="")
        score=_score(a.get("data-cvss"))
        if sev:label+=" \u2014 "+SEVERITY_LABELS[sev]
        if score is not None:label+=f" (CVSS {score:.1f})"
    return label
def _is_secret(n):return isinstance(n,dict) and ("note-secret" in _classes(n) or "rpt-redact" in _classes(n))
def _has(n,test):return isinstance(n,dict) and any(isinstance(k,dict) and (test(k) or _has(k,test)) for k in n["kids"])
def _redact_span(kids):return _el("span",kids,**{"class":"rpt-redact"})
def _redact_credential(kids):
    """A credential callout: what the editor marked as a secret stays marked, a "Password: x" line gets its value marked, and a callout with neither is masked whole."""
    state={"found":any(_is_secret(k) or _has(k,_is_secret) for k in kids)}
    def lines(n):
        # Inline content split at line breaks: [[node,...],...]
        out=[[]]
        for k in n["kids"]:
            if isinstance(k,dict) and k["tag"]=="br":out.append([])
            elif isinstance(k,str) and n["tag"]=="pre" and "\n" in k:
                parts=k.split("\n")
                out[-1].append(parts[0])
                for part in parts[1:]:out.append([part])
            else:out[-1].append(k)
        return out
    def mark(n):
        res=[];sep="\n" if n["tag"]=="pre" else _el("br")
        for i,line in enumerate(lines(n)):
            if i:res.append(sep)
            text="".join(_node_text(k) for k in line)
            m=_SECRET_LINE_RX.match(text)
            if m and not any(_is_secret(k) or _has(k,_is_secret) for k in line):
                state["found"]=True
                res+=[_el("strong",[m.group(1)]) if n["tag"]!="pre" else m.group(1),_redact_span([m.group(2).rstrip()])]
            else:res+=line
        return dict(n,kids=res)
    def walk(nodes):
        out=[]
        for k in nodes:
            if isinstance(k,str) or _is_secret(k):out.append(k)
            elif k["tag"] in _LEAF_BLOCKS and not _has(k,lambda x:x["tag"] in _DOM_BLOCKS or x["tag"]=="li"):out.append(mark(k))
            else:out.append(dict(k,kids=walk(k["kids"])))
        return out
    done=walk(kids)
    if state["found"]:return done
    def mask(nodes):
        out=[]
        for k in nodes:
            if isinstance(k,str):out.append(_redact_span([k]) if k.strip() else k)
            elif k["tag"] in _VOID_ANY:out.append(k)
            elif k["tag"] in _LEAF_BLOCKS and not _has(k,lambda x:x["tag"] in _DOM_BLOCKS or x["tag"]=="li"):out.append(dict(k,kids=[_redact_span(k["kids"])]) if _text(k) else k)
            elif k["tag"] in _DOM_BLOCKS or k["tag"] in ("li","tbody","thead","tr","td","th"):out.append(dict(k,kids=mask(k["kids"])))
            else:out.append(_redact_span([k]))
        return out
    return mask(kids)
def _pre_kids(n):
    """The text of a code block (tint spans and <br> lines flattened); redaction marks survive."""
    out=[]
    def walk(x):
        for k in x["kids"]:
            if isinstance(k,str):out.append(k)
            elif k["tag"]=="br":out.append("\n")
            elif _is_secret(k):out.append(_redact_span([_node_text(k)]))
            elif k["tag"] not in _DROP:
                walk(k)
                if k["tag"] in ("div","p"):out.append("\n")
    walk(n)
    while out and isinstance(out[-1],str) and not out[-1].strip("\n"):out.pop()
    if out and isinstance(out[-1],str):out[-1]=out[-1].rstrip("\n")
    return out
def _note_prepare(nodes):
    out=[]
    for n in nodes:
        if isinstance(n,str):
            out.append(n);continue
        tag=n["tag"];cls=_classes(n)
        kind=_callout_kind(n)
        if kind:
            # Subset v2 holds callouts natively; a credential keeps its secrets masked.
            kids=_redact_credential(n["kids"]) if kind=="credential" else n["kids"]
            a={"class":"note-callout note-finding" if "note-finding" in cls else "note-callout","data-callout":kind}
            if kind in ("finding","vuln"):
                sev=_sev(n["attrs"].get("data-sev") or n["attrs"].get("data-severity"),strict=False,default="")
                score=_score(n["attrs"].get("data-cvss"))
                if sev:a["data-sev"]=sev
                if score is not None:a["data-cvss"]=f"{score:.1f}"
            out.append({"tag":"div","attrs":a,"kids":_note_prepare(kids)})
        elif tag=="pre":
            lang=n["attrs"].get("data-lang","").strip()
            out.append({"tag":"pre","attrs":{"data-lang":lang} if lang else {},"kids":_pre_kids(n)})
        elif tag=="ul" and "note-checklist" in cls:
            kids=[]
            for k in n["kids"]:
                if isinstance(k,dict) and k["tag"]=="li":
                    on=k["attrs"].get("data-checked","").lower() in ("true","1","checked","yes")
                    k=dict(k,attrs=dict(k["attrs"],**{"data-checked":"1" if on else "0"}))
                kids.append(k)
            out.append(dict(n,kids=_note_prepare(kids)))
        elif tag=="figure" and ("note-embed" in cls or "data-attachment-id" in n["attrs"]):
            # Pictures and flattened drawings: the <img> alone (a <figure> in the subset is an evidence block). Other attachments stay behind as their file name.
            imgs=[]
            def find(x):
                for k in x["kids"]:
                    if isinstance(k,dict):
                        if k["tag"]=="img":imgs.append(k)
                        else:find(k)
            find(n)
            if imgs:out.append(_el("p",imgs))
            else:
                name=_text(_el("",[k for k in n["kids"] if not (isinstance(k,dict) and "note-embed-toolbar" in _classes(k))])).replace("\n"," ")
                if name:out.append(_el("p",[f"[Attachment: {name}]"]))
        elif tag in ("p","div") and not _text(n) and not _has(n,lambda x:x["tag"] in ("img","hr","table","figure","pre","ul","ol","blockquote")):
            # The editor's empty lines (<p><br></p>) are spacing, not content.
            continue
        else:out.append(dict(n,kids=_note_prepare(n["kids"])))
    return out
def _note_rich(nodes,resolver=None):
    return _sanitize("".join(_node_html(n) for n in _note_prepare(nodes)),img_resolver=resolver,note_mode=True)
def _match_targets(names,targets):
    out=[]
    for name in names:
        low=name.lower();hit=None
        for t in targets:
            vals=[v for v in t["values"].values() if v]
            if t["name"].lower()==low or any(v.lower()==low for v in vals):
                hit={"target_id":t["id"],"name":t["name"],"value":name if t["name"].lower()!=low else (vals[0] if vals else "")};break
        out.append(hit or {"target_id":"","name":name,"value":""})
    return out
def _draft_from_nodes(title,nodes,note,hints,targets,resolver=None):
    """Build a finding draft from a title and the block nodes that follow it. hints: {severity,cvss} taken from the callout's attributes or the heading."""
    buckets={"description":[],"steps":[],"impact":[],"remediation":[],"references":[]}
    current="description"
    table={}
    for n in nodes:
        if isinstance(n,dict):
            if n["tag"]=="table" and not table:
                pairs=_table_pairs(n)
                known={_TABLE_KEYS[k]:v for k,v in pairs.items() if k in _TABLE_KEYS}
                if known:
                    table=known;continue
            if n["tag"] in _HEADINGS or _only_bold(n):
                key=_section_key(_text(n))
                if key:
                    current=key;continue
            # Proof pasted into the finding before any section heading belongs to the steps, not the description.
            if current=="description" and _callout_kind(n)=="evidence":
                buckets["steps"].append(n);continue
        buckets[current].append(n)
    all_text="\n".join(_text(n) for n in nodes if not isinstance(n,str) or n.strip())
    sev=_sev(hints.get("severity"),strict=False,default="")
    if not sev and "severity" in table:
        m=re.search(rf"\b({_SEV_WORD})\b",_text(table["severity"]),re.I)
        if m:sev=_sev(m.group(1),strict=False,default="")
    cvss_text=_text(table["cvss"]) if "cvss" in table else ""
    vector="";score=None
    m=_VECTOR_RX.search(cvss_text) or _VECTOR_RX.search(all_text)
    if m:
        r=_cvss.calc(m.group(0))
        if r["valid"]:vector=r["vector"];score=r["score"]
    if score is None:
        score=_score(hints.get("cvss"))
        if score is None and cvss_text:
            m=re.search(r"(?<![\d.])(10(?:\.0)?|\d(?:\.\d)?)(?![\d.])",cvss_text)
            if m:score=_score(m.group(1))
        if score is None:
            m=_SCORE_RX.search(all_text)
            if m:score=_score(m.group(1))
    if not sev:sev=_cvss.severity(score) if score is not None else "info"
    affected=[]
    if "affected" in table:
        affected=_match_targets([x for x in (_s(p,200) for p in re.split(r"[,;\n]+",_text(table["affected"]))) if x][:100],targets)
    refs=[]
    for src in ([table["references"]] if "references" in table else [])+buckets["references"]:
        for u in _URL_RX.findall(_node_html(src) if isinstance(src,dict) else src):
            u=html.unescape(u).rstrip(".,;")
            if u not in refs:refs.append(u)
    cwe=_text(table["cwe"]) if "cwe" in table else ""
    m=_CWE_RX.search(cwe) or _CWE_RX.search(all_text)
    cwe=m.group(0).upper() if m else ""
    owasp=_s(_text(table["owasp"]),160) if "owasp" in table else ""
    if not owasp:
        m=_OWASP_RX.search(all_text)
        if m:owasp=_s(m.group(0),160).rstrip(" -:(")
    status="open"
    if "status" in table:status=_status(_text(table["status"]),strict=False)
    rich={k:_note_rich(buckets[k],resolver) for k in _RICH_FIELDS}
    for k in rich:
        if _rich_empty(rich[k]):rich[k]=""
    f=_finding_blank()
    f.update({"title":_s(title,TITLE_MAX),"severity":sev,"cvss_vector":vector,"cvss_score":score,"status":status,"cwe":cwe,"owasp":owasp,"references":refs[:100],"affected":affected,"source":{"kind":"note","ref":str(note["id"])},"note_id":int(note["id"]),"note_name":note["name"]})
    f.update(rich)
    return f
def _clean_title(raw):
    """-> (title, severity hint) from heading text such as "Finding: X (High)" or "[HIGH] X"."""
    t=re.sub(r"\s+"," ",raw or "").strip()
    sev=""
    m=_TITLE_BRACKET_RX.match(t)
    if m:sev=m.group(1);t=m.group(2).strip()
    m=_TITLE_PREFIX_RX.match(t)
    if m:t=m.group(1).strip()
    m=_TITLE_SEV_SUFFIX_RX.search(t)
    if m:
        sev=sev or m.group(1);t=t[:m.start()].strip()
    return t,sev
def _callout_draft(n,note,targets,resolver):
    kids=[k for k in n["kids"] if not (isinstance(k,str) and not k.strip())]
    title="";rest=kids
    for i,k in enumerate(kids):
        if isinstance(k,dict) and (k["tag"] in _HEADINGS or (_only_bold(k) and not _section_key(_text(k)))):
            if any(isinstance(p,dict) and p["tag"]=="table" for p in kids[:i]):break
            title=_text(k);rest=kids[:i]+kids[i+1:];break
        if isinstance(k,str) or k["tag"] not in ("br",):
            if i>=1:break
    if not title:
        first=_text({"tag":"","attrs":{},"kids":kids}).split("\n")[0]
        title=first[:120]
        # A plain callout (no heading): its first line is the title, the rest is the body.
        if kids and title:
            head=kids[0]
            if isinstance(head,str) and head.strip()==first:
                rest=kids[1:]
                while rest and isinstance(rest[0],dict) and rest[0]["tag"]=="br":rest=rest[1:]
            elif isinstance(head,dict) and head["tag"] in ("p","div") and _text(head)==first and not _callout_kind(head):rest=kids[1:]
    title,sev_hint=_clean_title(title)
    a=n["attrs"]
    draft=_draft_from_nodes(title,rest,note,{"severity":a.get("data-sev") or a.get("data-severity") or sev_hint,"cvss":a.get("data-cvss")},targets,resolver)
    untouched=draft["title"].lower() in ("","finding title","vulnerability title") and not any(draft[k] for k in _RICH_FIELDS)
    if untouched:return None
    if not draft["title"]:draft["title"]="Untitled finding"
    return draft
def _heading_level(n):
    if isinstance(n,dict) and n["tag"] in _HEADINGS:return int(n["tag"][1])
    return 7
def _is_marker(n):
    """A heading (or all-bold paragraph) that starts a finding in a note without callouts."""
    if isinstance(n,str) or not (n["tag"] in _HEADINGS or n["tag"] in ("p","div")):return None
    t=_text(n)
    if not t or len(t)>300 or "\n" in t:return None
    if n["tag"] not in _HEADINGS and not _only_bold(n) and not _TITLE_BRACKET_RX.match(t):return None
    if _TITLE_PREFIX_RX.match(t) or _TITLE_BRACKET_RX.match(t):return _clean_title(t)
    return None
def _parse_note_findings(note,targets=(),resolver=None):
    root=_dom(note.get("content") or "")
    drafts=[];callouts=[]
    def walk(n):
        for k in n["kids"]:
            if isinstance(k,str):continue
            if _is_callout(k):callouts.append(k)
            elif k["tag"] not in _DROP:walk(k)
    walk(root)
    for c in callouts:
        try:d=_callout_draft(c,note,targets,resolver)
        except Exception:d=None
        if d:drafts.append(d)
    if callouts:return drafts
    blocks=root["kids"]
    # A note saved as one wrapper element: look inside it.
    while len([b for b in blocks if not (isinstance(b,str) and not b.strip())])==1:
        only=[b for b in blocks if not (isinstance(b,str) and not b.strip())][0]
        if isinstance(only,str) or only["tag"] not in ("div","section","article","body","html","main"):break
        blocks=only["kids"]
    i=0
    while i<len(blocks):
        mark=_is_marker(blocks[i])
        if not mark:
            i+=1;continue
        level=_heading_level(blocks[i])
        j=i+1
        while j<len(blocks):
            if _is_marker(blocks[j]) or (_heading_level(blocks[j])<=min(level,2) and not _section_key(_text(blocks[j]))):break
            j+=1
        try:
            d=_draft_from_nodes(mark[0],blocks[i+1:j],note,{"severity":mark[1]},targets,resolver)
            if d["title"]:drafts.append(d)
        except Exception:pass
        i=j
    return drafts
def _load_note(cur,note_id):
    row=cur.execute("SELECT id,note_name,content FROM Notes WHERE id=?",(_int(note_id,"Note not found."),)).fetchone()
    if not row:raise ValueError("Note not found.")
    return {"id":int(row[0]),"name":_s(row[1]) or "Untitled","content":row[2] or ""}
_IMG_EXT_RX=re.compile(r"\.(png|jpe?g|gif|webp|bmp)$",re.I)
def _note_image_resolver(note_id):
    """Resolver for the sanitiser: turns a note's image (data: URL, or a file inside the app's own data / attachment folders) into an asset."""
    roots=[]
    try:roots.append(os.path.realpath(common_db.data_dir()))
    except Exception:pass
    try:
        from Cores.Services import notes_service as _notes
        roots.append(os.path.realpath(_notes._attachments_root()))
    except Exception:pass
    def from_file(path,name):
        real=os.path.realpath(path)
        if not any(real==r or real.startswith(r+os.sep) for r in roots):return ""
        if not os.path.isfile(real) or os.path.getsize(real)>ASSET_MAX:return ""
        with open(real,"rb") as fh:raw=fh.read()
        try:
            from Cores.Services import notes_service as _notes
            raw=_notes.attachment_bytes(raw)  # encrypted at rest -> plain bytes (needs the session key)
        except Exception:return ""
        if not _sniff_image(raw) and raw[:2]==b"BM":
            # BMP is not a report image type: convert it when Pillow is there.
            from PIL import Image
            buf=io.BytesIO()
            with Image.open(io.BytesIO(raw)) as im:im.convert("RGB").save(buf,"PNG")
            raw=buf.getvalue()
        return add_asset(name or os.path.basename(real),raw)["uid"]
    def resolve(src,attrs=None):
        alt=_s((attrs or {}).get("alt"),120)
        low=src[:12].lower()
        if low.startswith("data:image/"):return add_asset(alt or "image",_b64_bytes(src))["uid"]
        if not low.startswith("file:"):return ""
        path=unquote(src[5:].split("?",1)[0].split("#",1)[0])
        if not _IMG_EXT_RX.search(path):return ""
        path=re.sub(r"^/+","/",path)
        if re.match(r"^/[A-Za-z]:[\\/]",path):path=path[1:]
        cands=[os.path.normpath(path)]
        base=os.path.basename(path.replace("\\","/"))
        # The stored file:// URL can be stale (data folder moved): fall back to the attachment's file name under the known folders.
        for r in roots[1:]:cands+=[os.path.join(r,str(note_id),base),os.path.join(r,"_pending",base)]
        for c in cands:
            try:
                uid=from_file(c,alt)
                if uid:return uid
            except Exception:continue
        return ""
    return resolve
def _note_html_to_rich(content,note_id):
    from Cores.Services import notes_service as _notes
    def card(m):
        d=_notes._decode_cmd_data(m.group(1))
        cmd=_s(d.get("command"))
        if not cmd:return ""
        title=_s(d.get("cmd_note_title"),200)
        return (f"<p><strong>{html.escape(title,quote=False)}</strong></p>" if title else "")+f"<pre>{html.escape(cmd,quote=False)}</pre>"
    t=content or ""
    t=_notes._CMD_CARD_A_RX.sub(card,t)
    t=_notes._CMD_CARD_IMG_RX.sub(card,t)
    return _note_rich(_dom(t[:_RICH_INPUT_MAX])["kids"],_note_image_resolver(note_id))
def note_content(note_id):
    """A note as report rich text (subset v2): callouts, checklists and code blocks are kept natively (a credential callout keeps its secrets masked), command cards become <pre>, images become assets where the file can be read."""
    with _db() as con:note=_load_note(con.cursor(),note_id)
    return {"name":note["name"],"html":_note_html_to_rich(note["content"],note["id"])}
def note_findings(note_ids):
    """Finding drafts parsed from the notes' finding / vulnerability callouts (or "Finding: ..." / "[HIGH] ..." headings). [] when there are none."""
    ids=[]
    for x in (note_ids if isinstance(note_ids,(list,tuple)) else [note_ids]):
        try:
            x=int(x)
            if x not in ids:ids.append(x)
        except (TypeError,ValueError):continue
    if not ids:return []
    notes=[]
    with _db() as con:
        cur=con.cursor()
        for nid in ids[:500]:
            try:notes.append(_load_note(cur,nid))
            except ValueError:continue
    try:
        pid=next((p["id"] for p in _profile_list() if p["active"]),"")
        targets=_profile_targets(pid) if pid else []
    except Exception:targets=[]
    out=[]
    for note in notes:
        if not _count_note_findings(note["content"]):continue
        try:
            from Cores.Services import notes_service as _notes
            content=_notes._CMD_CARD_A_RX.sub(lambda m:_cmd_pre(_notes,m),note["content"])
            content=_notes._CMD_CARD_IMG_RX.sub(lambda m:_cmd_pre(_notes,m),content)
        except Exception:content=note["content"]
        try:out+=_parse_note_findings({"id":note["id"],"name":note["name"],"content":content},targets,_note_image_resolver(note["id"]))
        except Exception:continue
    return out
def _cmd_pre(_notes,m):
    cmd=_s(_notes._decode_cmd_data(m.group(1)).get("command"))
    return f"<pre>{html.escape(cmd,quote=False)}</pre>" if cmd else ""
