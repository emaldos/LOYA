#!/usr/bin/env python3
"""Maintainer tool: build the offline CVE index that ships with LOYA NG.

Run it before each app release (see README "Release Publishing"):

    python tools/build_cve_index.py                       # build into dist/cve-index/
    python tools/build_cve_index.py --install-seed        # ...and copy the seed into Assets/cve/ (git-ignored) for local runs
    python tools/build_cve_index.py --add-to-package LOYA-NG-vX.Y.Z.zip   # ...and put the seed into the release zip

What it does: downloads the newest "all CVEs at midnight" baseline from the CVEProject/cvelistV5 GitHub releases
(about 670 MB, SHA-256 checked against GitHub's asset digest), applies the newest hourly delta, marks the CISA KEV
entries, optionally fills missing severities from the NVD API (--nvd-severity, slow), and writes

    cve-index-YYYYMMDD.sqlite.xz   the release asset the in-app updater falls back to (upload it with the release)
    cve-index.sqlite.xz            the same bytes under the name the app bundles as Assets/cve/cve-index.sqlite.xz
    cve-index.json                 its SHA-256, sizes, CVE count, build date and data watermark

Only the Python standard library is used. This tool is for maintainers and always goes online (unless --baseline-zip
and --offline are given); the app's own "online lookups" switch is about the app, not about this script.
"""
import argparse,hashlib,json,os,shutil,sys,time,urllib.request,urllib.parse,zipfile
from datetime import datetime,timezone
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:sys.path.insert(0,ROOT)
from Cores.Services import cve_index as X
UA="LOYA-NG index build"
GH_API="https://api.github.com/repos/CVEProject/cvelistV5/releases"
KEV_URL="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
NVD_URL="https://services.nvd.nist.gov/rest/json/cves/2.0"
MIN_RECORDS=200000  # a build with fewer records than this is treated as truncated
_ALLOWED={"api.github.com","github.com","release-assets.githubusercontent.com","objects.githubusercontent.com","www.cisa.gov","services.nvd.nist.gov"}
def log(msg):print(f"[{time.strftime('%H:%M:%S')}] {msg}",flush=True)
class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        _check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def _check_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!="https" or p.hostname not in _ALLOWED:raise SystemExit(f"refusing to contact {url!r}: not https or not an expected host")
def _open(url,headers=None,timeout=60):
    _check_url(url)
    h={"User-Agent":UA,"Accept":"application/json"};h.update(headers or {})
    return urllib.request.build_opener(_Redirect()).open(urllib.request.Request(url,headers=h),timeout=timeout)
def get_json(url,headers=None):
    with _open(url,headers) as r:return json.loads(r.read().decode("utf-8","replace"))
def download(url,dest,expect_size=0,expect_sha=""):
    h=hashlib.sha256();done=0;t0=time.time();last=0
    with _open(url,{"Accept":"application/octet-stream"},timeout=120) as r,open(dest,"wb") as f:
        while True:
            chunk=r.read(1024*1024)
            if not chunk:break
            f.write(chunk);h.update(chunk);done+=len(chunk)
            if time.time()-last>5:
                last=time.time();log(f"  {done/1e6:.0f} MB"+(f" of {expect_size/1e6:.0f} MB" if expect_size else ""))
    if expect_size and done!=expect_size:raise SystemExit(f"download of {url} is {done} bytes, expected {expect_size}")
    if expect_sha and h.hexdigest()!=expect_sha:raise SystemExit(f"SHA-256 mismatch for {url}")
    log(f"  downloaded {done/1e6:.1f} MB in {time.time()-t0:.0f}s"+(" (SHA-256 ok)" if expect_sha else " (no digest to check)"))
    return h.hexdigest()
def _digest(asset):
    d=str(asset.get("digest") or "")
    return d[7:].lower() if d.startswith("sha256:") else ""
def find_release():
    """Newest release with a baseline zip: (date, baseline asset, newest delta asset or None, delta hour or '')."""
    rels=get_json(GH_API+"?per_page=40")
    for r in rels:
        base=next((a for a in r.get("assets",[]) if a["name"].endswith("_all_CVEs_at_midnight.zip.zip")),None)
        if not base:continue
        delta=next((a for a in r.get("assets",[]) if "_delta_CVEs_at_" in a["name"] and a["name"].endswith("Z.zip")),None)
        date=base["name"][:10]
        hour=delta["name"].split("_delta_CVEs_at_")[1][:2] if delta else ""
        return date,base,delta,hour
    raise SystemExit("no cvelistV5 release with a baseline zip was found")
def iter_records(inner_zip):
    with zipfile.ZipFile(inner_zip) as z:
        for i in z.infolist():
            if i.is_dir() or not X._DELTA_NAME_RX.search(i.filename) or i.file_size>X.MAX_DELTA_FILE_BYTES:continue
            try:
                with z.open(i) as f:yield json.loads(f.read().decode("utf-8","replace"))
            except Exception:continue
def nvd_scores(api_key=""):
    """Every NVD record's best CVSS, page by page (slow: about 6.5 s per 2000 CVEs without a key)."""
    start=0;total=None;wait=0.8 if api_key else 6.5
    headers={"apiKey":api_key} if api_key else {}
    order=(("cvssMetricV31",31),("cvssMetricV40",40),("cvssMetricV30",30),("cvssMetricV2",20))
    while total is None or start<total:
        for attempt in range(6):
            try:
                d=get_json(f"{NVD_URL}?resultsPerPage=2000&startIndex={start}",headers);break
            except Exception as e:
                log(f"  NVD page at {start} failed ({e}); retrying");time.sleep(15*(attempt+1))
        else:raise SystemExit("NVD kept failing; run again without --nvd-severity or with NVD_API_KEY set")
        total=int(d.get("totalResults") or 0)
        for v in d.get("vulnerabilities",[]):
            c=v.get("cve") or {}
            for key,ver in order:
                rows=sorted((m for m in (c.get("metrics") or {}).get(key,[]) if isinstance(m,dict) and isinstance(m.get("cvssData"),dict)),key=lambda m:0 if m.get("type")=="Primary" else 1)
                if rows:
                    cd=rows[0]["cvssData"]
                    yield c.get("id"),ver,cd.get("baseScore"),cd.get("baseSeverity") or rows[0].get("baseSeverity"),cd.get("vectorString")
                    break
        start+=2000
        log(f"  NVD {min(start,total)}/{total}")
        time.sleep(wait)
def add_to_package(package,seed,info):
    """Put the seed into a release zip (under its single top folder when it has one) as Assets/cve/..."""
    with zipfile.ZipFile(package) as z:names=z.namelist()
    tops={n.split("/",1)[0] for n in names if "/" in n}
    prefix=(next(iter(tops))+"/") if len(tops)==1 and not any("/" not in n for n in names) else ""
    for n in (prefix+"Assets/cve/"+X.SEED_NAME,prefix+"Assets/cve/"+X.SEED_INFO):
        if n in names:raise SystemExit(f"{package} already contains {n}; build the package again from the tag first")
    with zipfile.ZipFile(package,"a",zipfile.ZIP_STORED) as z:
        z.write(seed,prefix+"Assets/cve/"+X.SEED_NAME)
        z.write(info,prefix+"Assets/cve/"+X.SEED_INFO)
    log(f"added the index to {package} ({os.path.getsize(package)/1e6:.1f} MB now; the updater's limit is 200 MB)")
def main(argv=None):
    ap=argparse.ArgumentParser(description="Build the offline CVE index for LOYA NG.")
    ap.add_argument("--out",default=os.path.join(ROOT,"dist","cve-index"),help="output folder (default: dist/cve-index, git-ignored)")
    ap.add_argument("--work",default="",help="scratch folder for the 0.7 GB download and its 0.75 GB inner zip (default: <out>/work)")
    ap.add_argument("--baseline-zip",default="",help="use an already downloaded *_all_CVEs_at_midnight.zip.zip")
    ap.add_argument("--baseline-date",default="",help="the date of --baseline-zip (YYYY-MM-DD)")
    ap.add_argument("--offline",action="store_true",help="with --baseline-zip: no delta, no KEV, no NVD")
    ap.add_argument("--no-delta",action="store_true",help="do not apply today's newest hourly delta")
    ap.add_argument("--no-kev",action="store_true",help="do not mark CISA KEV entries")
    ap.add_argument("--nvd-severity",action="store_true",help="fill missing severities from the NVD API (slow; set NVD_API_KEY to speed it up)")
    ap.add_argument("--preset",type=int,default=9,help="xz preset 0-9 (default 9)")
    ap.add_argument("--keep-work",action="store_true",help="keep the downloads and the uncompressed index")
    ap.add_argument("--install-seed",action="store_true",help="copy the result into Assets/cve/ of this checkout")
    ap.add_argument("--add-to-package",default="",help="add the result to this release zip as Assets/cve/...")
    a=ap.parse_args(argv)
    if not X.has_fts5():raise SystemExit("this Python's SQLite has no FTS5; use another Python to build the index")
    if a.baseline_zip and not a.baseline_date:raise SystemExit("--baseline-zip needs --baseline-date YYYY-MM-DD")
    if a.offline and not a.baseline_zip:raise SystemExit("--offline needs --baseline-zip")
    t_start=time.time()
    out=os.path.abspath(a.out);work=os.path.abspath(a.work or os.path.join(out,"work"))
    os.makedirs(out,exist_ok=True);os.makedirs(work,exist_ok=True)
    free=shutil.disk_usage(work).free
    if free<2.2e9 and not a.baseline_zip or free<1.2e9:raise SystemExit(f"not enough free space in {work}: {free/1e9:.1f} GB (about 2.2 GB is needed)")
    delta=None;hour=""
    if a.baseline_zip:
        date=a.baseline_date;outer=os.path.abspath(a.baseline_zip)
        if not a.offline and not a.no_delta:
            d2,_b,dl,h=find_release()
            if d2==date:delta,hour=dl,h
            else:log(f"newest upstream release is {d2}, the given baseline is {date}: no hourly delta applied")
    else:
        date,base,delta,hour=find_release()
        outer=os.path.join(work,base["name"])
        log(f"downloading the {date} baseline ({base['size']/1e6:.0f} MB)")
        download(base["browser_download_url"],outer,base["size"],_digest(base))
    watermark=f"{date}T00:00:00Z"
    log("unpacking the inner zip")
    with zipfile.ZipFile(outer) as z:
        inner=[i for i in z.infolist() if i.filename.endswith(".zip")]
        if len(inner)!=1 or inner[0].file_size>3e9:raise SystemExit("unexpected baseline layout")
        inner_path=os.path.join(work,"cves.zip")
        with z.open(inner[0]) as src,open(inner_path,"wb") as dst:shutil.copyfileobj(src,dst,4*1024*1024)
    raw=os.path.join(work,"cve_index.sqlite")
    con=X.create(raw)
    log("reading CVE records")
    t0=time.time();n=0;batch=[]
    for rec in iter_records(inner_path):
        row=X.summarize(rec)
        if not row:continue
        batch.append(row);n+=1
        if len(batch)>=5000:
            X.insert_rows(con,batch);batch=[]
            if n%50000==0:log(f"  {n} records")
    if batch:X.insert_rows(con,batch)
    con.commit()
    log(f"  {n} records in {time.time()-t0:.0f}s")
    if n<MIN_RECORDS:raise SystemExit(f"only {n} records were read - refusing to publish a truncated index")
    if delta is not None and not a.no_delta and not a.offline:
        dpath=os.path.join(work,delta["name"])
        log(f"applying the newest hourly delta ({delta['name']})")
        download(delta["browser_download_url"],dpath,delta["size"],_digest(delta))
        rows=X.read_delta_zip(dpath)
        X.insert_rows(con,rows);con.commit()
        watermark=f"{date}T{hour}:00:00Z"
        log(f"  {len(rows)} records")
    extra={"source":"CVEProject/cvelistV5","baseline_date":date,"nvd_merged":"0","kev_version":""}
    if not a.no_kev and not a.offline:
        log("marking CISA KEV entries")
        kev=get_json(KEV_URL)
        ids=[v.get("cveID") for v in kev.get("vulnerabilities",[]) if isinstance(v,dict)]
        marked=X.apply_kev(con,ids);con.commit()
        extra["kev_version"]=str(kev.get("catalogVersion") or "")
        log(f"  {marked} KEV ids ({extra['kev_version']})")
    if a.nvd_severity and not a.offline:
        log("filling missing severities from NVD (this takes a while)")
        filled=X.apply_scores(con,nvd_scores(os.environ.get("NVD_API_KEY","")));con.commit()
        extra["nvd_merged"]=datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log(f"  {filled} severities filled from NVD")
    log("building the search index and compacting")
    X.finish(con,watermark,extra=extra)
    meta=X.get_meta(con);con.close()
    meta=X.validate(raw)
    raw_size=os.path.getsize(raw)
    stamp=watermark[:10].replace("-","")
    asset=os.path.join(out,f"cve-index-{stamp}.sqlite.xz")
    log(f"compressing (xz preset {a.preset})")
    t0=time.time()
    xz_size=X.compress(raw,asset,a.preset)
    sha=X.sha256_file(asset)
    seed=os.path.join(out,X.SEED_NAME);shutil.copyfile(asset,seed)
    info={"name":os.path.basename(asset),"sha256":sha,"size":xz_size,"raw_size":raw_size,"raw_sha256":X.sha256_file(raw),"index_version":X.INDEX_VERSION,"count":int(meta["cve_count"]),
          "published":int(meta.get("published_count",0)),"scored":int(meta.get("scored_count",0)),"kev":int(meta.get("kev_count",0)),"built_at":meta.get("built_at",""),"watermark":watermark,"source":"CVEProject/cvelistV5","nvd_merged":extra["nvd_merged"]}
    info_path=os.path.join(out,X.SEED_INFO)
    with open(info_path,"w",encoding="utf-8",newline="\n") as f:json.dump(info,f,indent=2);f.write("\n")
    with open(asset+".sha256","w",encoding="utf-8",newline="\n") as f:f.write(f"{sha}  {os.path.basename(asset)}\n")
    log(f"  {xz_size/1e6:.1f} MB compressed in {time.time()-t0:.0f}s (uncompressed {raw_size/1e6:.1f} MB)")
    pub=info["published"] or 1
    log(f"done in {time.time()-t_start:.0f}s: {info['count']} CVEs ({info['published']} published, {info['count']-info['published']} rejected), "
        f"{info['scored']} with a severity ({100*info['scored']/pub:.1f}% of published), {info['kev']} in KEV, data up to {watermark}")
    log(f"release asset: {asset}")
    log(f"bundled seed:  {seed} + {info_path}")
    if a.install_seed:
        os.makedirs(X.seed_dir(),exist_ok=True)
        shutil.copyfile(seed,X.seed_path());shutil.copyfile(info_path,X.seed_info_path())
        log(f"installed the seed into {X.seed_dir()}")
    if a.add_to_package:add_to_package(os.path.abspath(a.add_to_package),seed,info_path)
    if not a.keep_work:
        for p in (inner_path,raw)+(() if a.baseline_zip else (outer,)):
            try:os.remove(p)
            except OSError:pass
    return 0
if __name__=="__main__":raise SystemExit(main())
