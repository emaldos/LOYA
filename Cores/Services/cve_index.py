"""The offline CVE index: one compact SQLite file with a row for every published CVE (id, dates, title, severity and
score, CWE, KEV flag, state) and an FTS5 index over the titles. It is public data, so it is a plain SQLite file in
Data/cve_index/ (never in the encrypted main database).

This module is storage only - it never touches the network. It is shared by the maintainer tool that builds the index
(tools/build_cve_index.py), by the app's search, and by the in-app updater (cve_index_updater.py).

The index is installed from the bundled seed Assets/cve/cve-index.sqlite.xz the first time it is needed, and replaced
by a newer seed when an app update brings one. Every swap is atomic: the new file is written next to the old one,
checked, and only then renamed over it.
"""
import os,re,io,json,lzma,shutil,sqlite3,hashlib,zipfile,threading
from datetime import datetime,timezone
from Cores import common_db as _common_db
INDEX_VERSION=1
SEED_NAME="cve-index.sqlite.xz"
SEED_INFO="cve-index.json"
MAX_RAW_BYTES=600*1024*1024      # an index larger than this once decompressed is refused (xz bomb limit)
MAX_XZ_BYTES=150*1024*1024
MAX_RATIO=60                     # real indexes compress about 4:1
MAX_DELTA_ENTRIES=120_000
MAX_DELTA_FILE_BYTES=8*1024*1024
MAX_DELTA_TOTAL_BYTES=700*1024*1024
MAX_ZIP_RATIO=200
TITLE_MAX=200
STATES=("published","rejected","reserved")
SEVERITIES=("info","low","medium","high","critical")
_LOCK=threading.RLock()
class IndexError_(ValueError):pass
def _root(*p):return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p))
def index_dir():
    d=os.path.join(_common_db.data_dir(),"cve_index")
    os.makedirs(d,exist_ok=True)
    return d
def index_path():return os.path.join(index_dir(),"cve_index.sqlite")
def seed_dir():return _root("Assets","cve")
def seed_path():return os.path.join(seed_dir(),SEED_NAME)
def seed_info_path():return os.path.join(seed_dir(),SEED_INFO)
# ---------------------------------------------------------------- ids and text
_ID_RX=re.compile(r"^CVE-(\d{4})-(\d{4,7})$",re.I)
def id_to_int(cid):
    m=_ID_RX.match(str(cid or "").strip())
    if not m:return None
    return int(m.group(1))*10_000_000+int(m.group(2))
def int_to_id(n):
    n=int(n)
    return f"CVE-{n//10_000_000}-{n%10_000_000:04d}"
_CTRL_RX=re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
def _clean(v,n):
    if v is None or isinstance(v,(dict,list,bool)):return ""
    return re.sub(r"\s+"," ",_CTRL_RX.sub(" ",str(v))).strip()[:n]
def _first_sentence(text,n=TITLE_MAX):
    t=_clean(text,600)
    m=re.match(r"^(.{20,%d}?[.!?])(\s|$)"%n,t)
    if m:return m.group(1)
    return t if len(t)<=n else t[:n-1].rstrip()+"…"
def _day(v):
    m=re.match(r"^(\d{4})-(\d{2})-(\d{2})",str(v or ""))
    return int(m.group(1)+m.group(2)+m.group(3)) if m else 0
def day_text(n):
    n=int(n or 0)
    return f"{n//10000:04d}-{n//100%100:02d}-{n%100:02d}" if n>0 else ""
def _en(items,key="value"):
    rows=[d for d in (items if isinstance(items,list) else []) if isinstance(d,dict)]
    for d in rows:
        if str(d.get("lang","")).lower().startswith("en") and d.get(key):return d.get(key)
    return rows[0].get(key) if rows else ""
def _score(v):
    try:
        if isinstance(v,bool):return None
        f=float(v)
        return f if 0<=f<=10 else None
    except Exception:return None
def sev_rank(score,label=""):
    s=str(label or "").strip().lower()
    if s in ("none","informational"):s="info"
    if s in SEVERITIES:return SEVERITIES.index(s)
    if score is None:return 0
    return 4 if score>=9 else 3 if score>=7 else 2 if score>=4 else 1 if score>0 else 0
_CVSS_KEYS=(("cvssV3_1",31),("cvssV4_0",40),("cvssV3_0",30),("cvssV2_0",20))
_VEC_RX=re.compile(r"^[A-Za-z0-9:./()]{3,200}$")
def _best_cvss(containers):
    """(version int, score, severity rank, vector without its CVSS:x.y/ prefix) - CVSS 3.1 first, then 4.0, 3.0, 2.0; the CNA's own score before an ADP's."""
    found={}
    for c in containers:
        for m in c.get("metrics") if isinstance(c.get("metrics"),list) else []:
            if not isinstance(m,dict):continue
            for key,ver in _CVSS_KEYS:
                d=m.get(key)
                if ver in found or not isinstance(d,dict):continue
                sc=_score(d.get("baseScore"))
                if sc is None:continue
                vec=_clean(d.get("vectorString"),200)
                vec=re.sub(r"^CVSS:\d\.\d/","",vec) if _VEC_RX.match(vec) else ""
                found[ver]=(ver,sc,sev_rank(sc,d.get("baseSeverity")),vec)
    for _key,ver in _CVSS_KEYS:
        if ver in found:return found[ver]
    return (0,None,0,"")
def summarize(rec):
    """One CVE Record (cvelistV5 JSON 5.x) -> an index row dict, or None when it is not a usable record. Text is cleaned and capped."""
    if not isinstance(rec,dict):return None
    meta=rec.get("cveMetadata") if isinstance(rec.get("cveMetadata"),dict) else {}
    n=id_to_int(meta.get("cveId"))
    if n is None:return None
    st=str(meta.get("state") or "").upper()
    state=0 if st=="PUBLISHED" else 1 if st=="REJECTED" else 2
    cont=rec.get("containers") if isinstance(rec.get("containers"),dict) else {}
    cna=cont.get("cna") if isinstance(cont.get("cna"),dict) else {}
    adps=[a for a in (cont.get("adp") if isinstance(cont.get("adp"),list) else []) if isinstance(a,dict)]
    if state==0:
        title=_clean(cna.get("title"),TITLE_MAX+200)
        if len(title)>TITLE_MAX:title=title[:TITLE_MAX-1].rstrip()+"…"
        if not title:title=_first_sentence(_en(cna.get("descriptions")))
    else:
        why=_first_sentence(_en(cna.get("rejectedReasons")),TITLE_MAX-12)
        title=("Rejected: "+why) if (state==1 and why) else ("Rejected" if state==1 else "Reserved")
    ver,score,sev,vec=_best_cvss([cna]+adps) if state==0 else (0,None,0,"")
    cwes=[]
    for c in [cna]+adps:
        for p in c.get("problemTypes") if isinstance(c.get("problemTypes"),list) else []:
            for x in (p.get("descriptions") if isinstance(p,dict) and isinstance(p.get("descriptions"),list) else []):
                if not isinstance(x,dict):continue
                m=re.match(r"^CWE-(\d{1,5})\b",str(x.get("cweId") or x.get("description") or "").strip())
                if m and m.group(1) not in cwes:cwes.append(m.group(1))
    vps=[]
    for a in cna.get("affected") if isinstance(cna.get("affected"),list) else []:
        if not isinstance(a,dict):continue
        v=_clean(a.get("vendor"),40);p=_clean(a.get("product") or a.get("packageName"),50)
        if v.lower() in ("n/a","unknown","unspecified"):v=""
        if p.lower() in ("n/a","unknown","unspecified"):p=""
        t=(v+" "+p).strip() if p.lower().find(v.lower())<0 or not v else p
        if t and t.lower() not in [x.lower() for x in vps]:vps.append(t)
        if len(vps)>=2:break
    return {"id":n,"pub":_day(meta.get("datePublished") or meta.get("dateRejected") or meta.get("dateReserved")),"mod":_day(meta.get("dateUpdated") or meta.get("datePublished")),"state":state,
        "sev":sev,"score":int(round(score*10)) if score is not None else None,"ver":ver,"vec":vec,"cwe":",".join(cwes[:3]),"kev":0,"title":title,"vp":"; ".join(vps)[:90]}
# ---------------------------------------------------------------- schema and writing
_SCHEMA=(
    "CREATE TABLE IF NOT EXISTS cve(id INTEGER PRIMARY KEY,pub INTEGER,mod INTEGER,state INTEGER NOT NULL DEFAULT 0,sev INTEGER NOT NULL DEFAULT 0,score INTEGER,ver INTEGER NOT NULL DEFAULT 0,vec TEXT,cwe TEXT,kev INTEGER NOT NULL DEFAULT 0,title TEXT,vp TEXT)",
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)",
    "CREATE INDEX IF NOT EXISTS cve_kev ON cve(id) WHERE kev=1",
)
_FTS_SQL="CREATE VIRTUAL TABLE IF NOT EXISTS cve_fts USING fts5(title,vp,content='cve',content_rowid='id',detail=none,columnsize=0,tokenize=\"unicode61 remove_diacritics 2\")"
_COLS=("id","pub","mod","state","sev","score","ver","vec","cwe","kev","title","vp")
def has_fts5():
    try:
        c=sqlite3.connect(":memory:")
        try:c.execute("CREATE VIRTUAL TABLE t USING fts5(a)");return True
        finally:c.close()
    except Exception:return False
def create(path):
    """A new, empty index file (overwrites). Returns the open connection."""
    if os.path.exists(path):os.remove(path)
    con=sqlite3.connect(path)
    con.execute("PRAGMA page_size=4096");con.execute("PRAGMA journal_mode=OFF");con.execute("PRAGMA synchronous=OFF")
    for sql in _SCHEMA:con.execute(sql)
    con.execute(_FTS_SQL)
    set_meta(con,"index_version",INDEX_VERSION)
    return con
def set_meta(con,key,value):con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(key),str(value)))
def get_meta(con):
    try:return {k:v for k,v in con.execute("SELECT key,value FROM meta")}
    except Exception:return {}
def insert_rows(con,rows):
    """Bulk insert for a fresh build (no FTS upkeep - call finish() afterwards)."""
    con.executemany("INSERT OR REPLACE INTO cve("+",".join(_COLS)+") VALUES("+",".join("?"*len(_COLS))+")",[tuple(r[c] for c in _COLS) for r in rows])
def upsert_rows(con,rows):
    """Insert or update rows in a live index, keeping the FTS index and each row's KEV flag right. Returns (added, changed)."""
    added=changed=0
    fts=_has_fts_table(con)
    for r in rows:
        old=con.execute("SELECT title,vp,kev,mod,state,sev,score FROM cve WHERE id=?",(r["id"],)).fetchone()
        if old:
            if fts:con.execute("INSERT INTO cve_fts(cve_fts,rowid,title,vp) VALUES('delete',?,?,?)",(r["id"],old[0] or "",old[1] or ""))
            r=dict(r);r["kev"]=old[2]
            con.execute("UPDATE cve SET pub=?,mod=?,state=?,sev=?,score=?,ver=?,vec=?,cwe=?,kev=?,title=?,vp=? WHERE id=?",tuple(r[c] for c in _COLS[1:])+(r["id"],))
            changed+=1
        else:
            con.execute("INSERT INTO cve("+",".join(_COLS)+") VALUES("+",".join("?"*len(_COLS))+")",tuple(r[c] for c in _COLS))
            added+=1
        if fts:con.execute("INSERT INTO cve_fts(rowid,title,vp) VALUES(?,?,?)",(r["id"],r["title"] or "",r["vp"] or ""))
    return added,changed
def _has_fts_table(con):
    try:
        con.execute("SELECT 1 FROM cve_fts LIMIT 0");return True
    except Exception:return False
def apply_kev(con,ids):
    """Set the KEV flag to exactly the given CVE ids."""
    nums=sorted({n for n in (id_to_int(i) for i in ids) if n is not None})
    con.execute("UPDATE cve SET kev=0 WHERE kev=1")
    con.executemany("UPDATE cve SET kev=1 WHERE id=?",[(n,) for n in nums])
    return len(nums)
def apply_scores(con,scores):
    """Fill in severity for rows that have none. scores: iterable of (cve_id, version int, score, severity label, vector). Returns rows filled."""
    n=0
    for cid,ver,score,label,vec in scores:
        i=id_to_int(cid);sc=_score(score)
        if i is None or sc is None:continue
        vec=_clean(vec,200);vec=re.sub(r"^CVSS:\d\.\d/","",vec) if _VEC_RX.match(vec) else ""
        cur=con.execute("UPDATE cve SET sev=?,score=?,ver=?,vec=? WHERE id=? AND score IS NULL AND state=0",(sev_rank(sc,label),int(round(sc*10)),int(ver),vec,i))
        n+=cur.rowcount
    return n
def finish(con,watermark,built_at=None,extra=None):
    """Build the FTS index, stamp the meta table and compact the file. Call once at the end of a full build."""
    con.execute("INSERT INTO cve_fts(cve_fts) VALUES('rebuild')")
    con.execute("INSERT INTO cve_fts(cve_fts) VALUES('optimize')")
    stamp(con,watermark,built_at,extra)
    con.commit()
    con.execute("VACUUM")
    con.commit()
def stamp(con,watermark=None,built_at=None,extra=None):
    total=con.execute("SELECT COUNT(*) FROM cve").fetchone()[0]
    set_meta(con,"index_version",INDEX_VERSION)
    set_meta(con,"cve_count",total)
    set_meta(con,"published_count",con.execute("SELECT COUNT(*) FROM cve WHERE state=0").fetchone()[0])
    set_meta(con,"scored_count",con.execute("SELECT COUNT(*) FROM cve WHERE state=0 AND score IS NOT NULL").fetchone()[0])
    set_meta(con,"kev_count",con.execute("SELECT COUNT(*) FROM cve WHERE kev=1").fetchone()[0])
    if watermark:set_meta(con,"watermark",watermark)
    if built_at or not get_meta(con).get("built_at"):set_meta(con,"built_at",built_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    for k,v in (extra or {}).items():set_meta(con,k,v)
# ---------------------------------------------------------------- compressed files (stdlib lzma)
def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def compress(src,dst,preset=9):
    with open(src,"rb") as fi,lzma.open(dst,"wb",format=lzma.FORMAT_XZ,preset=preset) as fo:
        shutil.copyfileobj(fi,fo,1024*1024)
    return os.path.getsize(dst)
def validate(path):
    """Open an index file read-only and check it is a sane index. Returns its meta dict (with ints parsed) or raises IndexError_."""
    try:
        con=sqlite3.connect("file:"+path.replace("?","%3f").replace("#","%23")+"?mode=ro",uri=True,timeout=10)
    except Exception as e:raise IndexError_("The CVE index file could not be opened.") from e
    try:
        try:
            meta=get_meta(con)
            ver=int(meta.get("index_version","0") or 0)
            count=con.execute("SELECT COUNT(*) FROM cve").fetchone()[0]
            con.execute("SELECT id,pub,mod,state,sev,score,ver,vec,cwe,kev,title,vp FROM cve LIMIT 1").fetchall()
            ok=con.execute("PRAGMA quick_check(1)").fetchone()
        except sqlite3.Error as e:raise IndexError_("The CVE index file is damaged.") from e
        if ver!=INDEX_VERSION:raise IndexError_(f"This CVE index is format {ver}; this version of the app reads format {INDEX_VERSION}.")
        if count<1:raise IndexError_("The CVE index is empty.")
        if not ok or str(ok[0]).lower()!="ok":raise IndexError_("The CVE index file is damaged.")
        meta["cve_count"]=int(count);meta["index_version"]=ver
        return meta
    finally:con.close()
def _free_bytes(path):
    try:return shutil.disk_usage(os.path.dirname(path) or ".").free
    except Exception:return None
def install_xz(xz_path,dest=None,expected_sha256="",max_raw=None,cancel=None,raw_hint=0):
    """Decompress an index (.sqlite.xz) next to dest, check it, then atomically replace dest. The old index stays until the new one verifies.
    Limits: compressed size, decompressed size and ratio (xz bomb), free disk space. Returns the new index's meta."""
    dest=dest or index_path()
    max_raw=max_raw or MAX_RAW_BYTES
    size=os.path.getsize(xz_path)
    if size<=0 or size>MAX_XZ_BYTES:raise IndexError_("The CVE index download has an unexpected size, so it was not used.")
    if expected_sha256 and sha256_file(xz_path).lower()!=str(expected_sha256).lower():raise IndexError_("The CVE index file does not match its SHA-256, so it was not used.")
    free=_free_bytes(dest)
    need=(raw_hint or size*6)+32*1024*1024
    if free is not None and free<need:raise IndexError_(f"Not enough free disk space to install the CVE index (about {need//(1024*1024)} MB is needed).")
    tmp=dest+".new"
    try:
        written=0
        with lzma.open(xz_path,"rb",format=lzma.FORMAT_XZ) as fi,open(tmp,"wb") as fo:
            while True:
                if cancel is not None and cancel.is_set():raise IndexError_("Cancelled.")
                chunk=fi.read(1024*1024)
                if not chunk:break
                written+=len(chunk)
                if written>max_raw or written>size*MAX_RATIO+16*1024*1024:raise IndexError_("The CVE index is larger than expected once decompressed, so it was not used.")
                fo.write(chunk)
            fo.flush();os.fsync(fo.fileno())
        meta=validate(tmp)
        swap_in(tmp,dest)
        return meta
    except (lzma.LZMAError,EOFError) as e:
        raise IndexError_("The CVE index file is damaged (it could not be decompressed).") from e
    finally:
        try:
            if os.path.exists(tmp):os.remove(tmp)
        except OSError:pass
def swap_in(tmp,dest):
    """Atomic replace. On Windows the target cannot be replaced while a reader has it open, so readers take _LOCK too; retried briefly."""
    import time
    with _LOCK:
        last=None
        for _ in range(20):
            try:
                for side in ("-wal","-shm","-journal"):
                    try:os.remove(dest+side)
                    except OSError:pass
                os.replace(tmp,dest);_state["checked"]=None;return
            except OSError as e:
                last=e;time.sleep(0.15)
        raise IndexError_("The CVE index file is in use and could not be replaced.") from last
# ---------------------------------------------------------------- install from the bundled seed
_state={"checked":None}
def seed_info():
    try:
        with open(seed_info_path(),"r",encoding="utf-8") as f:d=json.load(f)
        if not isinstance(d,dict) or not os.path.isfile(seed_path()):return None
        return {"sha256":str(d.get("sha256") or "").lower(),"watermark":str(d.get("watermark") or ""),"built_at":str(d.get("built_at") or ""),"count":int(d.get("count") or 0),"index_version":int(d.get("index_version") or 0),"raw_size":int(d.get("raw_size") or 0)}
    except Exception:return None
def info():
    """What is installed right now (never installs anything)."""
    p=index_path()
    out={"installed":False,"count":0,"built_at":"","watermark":"","version":0,"size_bytes":0,"seed_available":seed_info() is not None,"published":0,"scored":0}
    if not os.path.isfile(p):return out
    try:
        with _LOCK:
            con=sqlite3.connect("file:"+p.replace("?","%3f").replace("#","%23")+"?mode=ro",uri=True,timeout=10)
            try:meta=get_meta(con)
            finally:con.close()
        if int(meta.get("index_version","0") or 0)!=INDEX_VERSION:return out
        out.update({"installed":True,"count":int(meta.get("cve_count","0") or 0),"built_at":meta.get("built_at",""),"watermark":meta.get("watermark",""),"version":INDEX_VERSION,"size_bytes":os.path.getsize(p),
            "published":int(meta.get("published_count","0") or 0),"scored":int(meta.get("scored_count","0") or 0)})
    except Exception:pass
    return out
def ensure_installed():
    """Install the bundled seed when there is no index yet, or when an app update brought a seed with newer data. Cheap after the first call. Returns info()."""
    with _LOCK:
        seed=seed_info()
        key=(seed or {}).get("sha256","")+"|"+str(os.path.isfile(index_path()))
        if _state["checked"]==key:return info()
        cur=info()
        if seed and seed["index_version"]==INDEX_VERSION and (not cur["installed"] or seed["watermark"]>cur["watermark"]):
            try:
                install_xz(seed_path(),index_path(),seed["sha256"],raw_hint=seed["raw_size"])
                cur=info()
            except (IndexError_,OSError):pass  # a bad seed never breaks the app: the old index (or none) stays
        _state["checked"]=(seed or {}).get("sha256","")+"|"+str(os.path.isfile(index_path()))
        return cur
# ---------------------------------------------------------------- reading
def _open_ro():
    p=index_path()
    if not os.path.isfile(p):return None
    return sqlite3.connect("file:"+p.replace("?","%3f").replace("#","%23")+"?mode=ro",uri=True,timeout=10)
def _row(r,built_at=""):
    score=r[5]/10.0 if r[5] is not None else None
    ver={31:"3.1",40:"4.0",30:"3.0",20:"2.0"}.get(r[6],"")
    vec=r[7] or ""
    cwes=["CWE-"+c for c in (r[8] or "").split(",") if c.isdigit()]
    return {"id":int_to_id(r[0]),"title":r[10] or "","description":"","severity":SEVERITIES[r[4]] if 0<=(r[4] or 0)<5 else "info","score":score,"cvss_version":ver,
        "vector":(vec if ver=="2.0" else f"CVSS:{ver}/{vec}") if (vec and ver) else "","kev":bool(r[9]),"epss":None,"published":day_text(r[1]),"modified":day_text(r[2]),"fetched_at":built_at,
        "origin":"index","index_only":True,"state":STATES[r[3]] if 0<=(r[3] or 0)<3 else "published","cwe":cwes[0] if cwes else "","cwes":cwes,"vendors":r[11] or ""}
_SELECT="SELECT c.id,c.pub,c.mod,c.state,c.sev,c.score,c.ver,c.vec,c.cwe,c.kev,c.title,c.vp FROM cve c"
def get(cid):
    n=id_to_int(cid)
    if n is None:return None
    with _LOCK:
        con=_open_ro()
        if con is None:return None
        try:
            r=con.execute(_SELECT+" WHERE c.id=?",(n,)).fetchone()
            return _row(r,get_meta(con).get("built_at","")) if r else None
        except sqlite3.Error:return None
        finally:con.close()
_TOKEN_RX=re.compile(r"[0-9A-Za-zÀ-￿]+")
_PREFIX_RX=re.compile(r"^(?:cve-?)?(\d{4})(?:-(\d{0,7}))?$",re.I)
def _filters_sql(filters):
    f=filters if isinstance(filters,dict) else {}
    where=[];args=[]
    sev=str(f.get("severity") or "").lower()
    if sev in SEVERITIES and SEVERITIES.index(sev)>0:
        where.append("c.sev>=?");args.append(SEVERITIES.index(sev))
    if f.get("kev_only") is True:where.append("c.kev=1")
    try:
        y=int(f.get("year") or 0)
        if 1999<=y<=2999:where.append("c.id BETWEEN ? AND ?");args+=[y*10_000_000,y*10_000_000+9_999_999]
    except (TypeError,ValueError):pass
    return where,args
def search(query,limit=20,filters=None,ids=None,exclude=None):
    """Search the index: exact ids (ids=[...]), an id prefix ("2021-442"), or keywords (all must match; the last one as a prefix). Newest first. [] when no index."""
    limit=max(1,min(200,int(limit or 20)))
    skip={id_to_int(x) for x in (exclude or [])}
    where,args=_filters_sql(filters)
    q=_clean(query,200)
    with _LOCK:
        con=_open_ro()
        if con is None:return []
        try:
            built=get_meta(con).get("built_at","")
            sql=None
            if ids:
                nums=[n for n in (id_to_int(i) for i in ids) if n is not None][:60]
                if not nums:return []
                sql=_SELECT+" WHERE c.id IN ("+",".join("?"*len(nums))+")"+("".join(" AND "+w for w in where));a=nums+args
            else:
                m=_PREFIX_RX.match(q.replace(" ",""))
                tokens=[t.lower() for t in _TOKEN_RX.findall(q)][:8]
                if m and (m.group(2) is not None or q.lower().startswith("cve")):
                    y=int(m.group(1));seq=m.group(2) or ""
                    rng=[]
                    for width in range(max(4,len(seq)),8):  # "442" -> 4420-4429, 44200-44299 ...; "044" -> 0440-0449
                        if width>4 and seq.startswith("0"):break
                        pad=width-len(seq)
                        rng.append((y*10_000_000+int((seq or "0")+"0"*pad) if seq else y*10_000_000,y*10_000_000+int(seq+"9"*pad) if seq else y*10_000_000+9_999_999))
                        if not seq:break
                    sql=_SELECT+" WHERE ("+" OR ".join("c.id BETWEEN ? AND ?" for _ in rng)+")"+("".join(" AND "+w for w in where));a=[v for pair in rng for v in pair]+args
                elif tokens:
                    if _has_fts_table(con):
                        terms=['"'+t+'"' for t in tokens]
                        if len(tokens[-1])>=2:terms[-1]+="*"
                        match=" AND ".join(terms)
                        sql=_SELECT+" JOIN cve_fts f ON f.rowid=c.id WHERE cve_fts MATCH ?"+("".join(" AND "+w for w in where));a=[match]+args
                    else:
                        like=[];la=[]
                        for t in tokens:
                            e=t.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
                            like.append("(c.title LIKE ? ESCAPE '\\' OR c.vp LIKE ? ESCAPE '\\')");la+=[f"%{e}%",f"%{e}%"]
                        sql=_SELECT+" WHERE "+" AND ".join(like+where);a=la+args
                elif where:
                    sql=_SELECT+" WHERE "+" AND ".join(where);a=args
                else:
                    sql=_SELECT;a=[]
            rows=con.execute(sql+" ORDER BY c.id DESC LIMIT ?",a+[limit+len(skip)]).fetchall()
            return [_row(r,built) for r in rows if r[0] not in skip][:limit]
        except sqlite3.Error:return []
        finally:con.close()
# ---------------------------------------------------------------- delta zips (untrusted)
_DELTA_NAME_RX=re.compile(r"(?:^|/)CVE-\d{4}-\d{4,7}\.json$",re.I)
def read_delta_zip(data,cancel=None):
    """Rows from a cvelistV5 delta zip (bytes or a path). Bounded against zip bombs; unreadable members are skipped."""
    try:z=zipfile.ZipFile(io.BytesIO(data) if isinstance(data,(bytes,bytearray)) else data)
    except Exception as e:raise IndexError_("The CVE update file is not a readable zip.") from e
    with z:
        infos=z.infolist()
        if len(infos)>MAX_DELTA_ENTRIES:raise IndexError_("The CVE update file has too many entries, so it was not used.")
        total=0
        for i in infos:
            if i.file_size>MAX_DELTA_FILE_BYTES:raise IndexError_("The CVE update file contains an oversized entry, so it was not used.")
            if i.file_size>1024*1024 and i.compress_size>0 and i.file_size/i.compress_size>MAX_ZIP_RATIO:raise IndexError_("The CVE update file looks like a zip bomb, so it was not used.")
            total+=i.file_size
            if total>MAX_DELTA_TOTAL_BYTES:raise IndexError_("The CVE update file is too large once unpacked, so it was not used.")
        out=[]
        for i in infos:
            if cancel is not None and cancel.is_set():raise IndexError_("Cancelled.")
            if i.is_dir() or not _DELTA_NAME_RX.search(i.filename):continue
            try:
                with z.open(i) as f:raw=f.read(MAX_DELTA_FILE_BYTES+1)
                if len(raw)>MAX_DELTA_FILE_BYTES:continue
                row=summarize(json.loads(raw.decode("utf-8","replace")))
            except Exception:continue
            if row:out.append(row)
        return out
def apply_delta(rows,watermark,kev_ids=None):
    """Apply rows to the installed index in one transaction (all or nothing). Returns (added, changed)."""
    p=index_path()
    with _LOCK:
        if not os.path.isfile(p):raise IndexError_("No CVE index is installed.")
        con=sqlite3.connect(p,timeout=30)
        try:
            con.execute("BEGIN IMMEDIATE")
            added,changed=upsert_rows(con,rows)
            if kev_ids is not None:apply_kev(con,kev_ids)
            stamp(con,watermark)
            con.commit()
            return added,changed
        except Exception:
            con.rollback();raise
        finally:con.close()
