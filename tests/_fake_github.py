"""Test-only fake GitHub for the updater: a 127.0.0.1 HTTP server serving releases/latest JSON and release assets, plus
helpers to build release packages and to point the updater at the server *in-process* (never via settings/env vars)."""
import hashlib,io,json,os,threading,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
OWNER="emaldos";NAME="LOYA"
class FakeGitHub:
    def __init__(self):
        self.routes={}
        self.hits=[]
        fake=self
        class H(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                fake.hits.append(self.path)
                route=fake.routes.get(urlparse(self.path).path)
                if route is None:
                    self.send_response(404);self.send_header("Content-Length","0");self.end_headers();return
                status,headers,body=route
                if callable(body):body=body()
                rng=self.headers.get("Range","")
                if status==200 and rng.startswith("bytes=") and isinstance(body,bytes):
                    start=int(rng[6:].split("-")[0] or 0)
                    part=body[start:]
                    self.send_response(206);self.send_header("Content-Range",f"bytes {start}-{len(body)-1}/{len(body)}");self.send_header("Content-Length",str(len(part)))
                    for k,v in headers.items():self.send_header(k,v)
                    self.end_headers();self.wfile.write(part);return
                self.send_response(status)
                for k,v in headers.items():self.send_header(k,v)
                self.send_header("Content-Length",str(len(body or b"")))
                self.end_headers()
                if body:self.wfile.write(body)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),H)
        self.port=self.server.server_address[1]
        self.base=f"http://127.0.0.1:{self.port}"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def start(self):
        self.thread.start();return self
    def stop(self):
        self.server.shutdown();self.server.server_close()
    def set(self,path,body,status=200,headers=None,content_type="application/octet-stream"):
        h={"Content-Type":content_type};h.update(headers or {})
        self.routes[path]=(status,h,body)
    def api_path(self):
        return f"/repos/{OWNER}/{NAME}/releases/latest"
    def asset_path(self,tag,name):
        return f"/{OWNER}/{NAME}/releases/download/{tag}/{name}"
    def publish(self,version,package_bytes,body="",digest=True,sha_override="",extra_assets=None,asset_name=None,draft=False,prerelease=False):
        tag=f"v{version}"
        name=asset_name or f"LOYA-NG-{tag}.zip"
        self.set(self.asset_path(tag,name),package_bytes)
        sha=sha_override or hashlib.sha256(package_bytes).hexdigest()
        asset={"id":1,"name":name,"size":len(package_bytes),"browser_download_url":self.base+self.asset_path(tag,name)}
        if digest:asset["digest"]="sha256:"+sha
        assets=[asset]+list(extra_assets or [])
        payload={"id":123456,"tag_name":tag,"name":f"LOYA NG {version}","draft":draft,"prerelease":prerelease,"target_commitish":"main","html_url":f"https://github.com/{OWNER}/{NAME}/releases/tag/{tag}","published_at":"2026-11-20T10:00:00Z","body":body,"assets":assets}
        self.set(self.api_path(),json.dumps(payload).encode(),content_type="application/json")
        return payload
def build_package(version,files=None,prefix=None,extra=None):
    """A minimal valid release zip (or the given file map). prefix wraps everything in one top folder like GitHub-built zips."""
    files=dict(files or {
        "LOYA_Note.py":"print('app')\n","RunNote.py":"print('launcher')\n","Requirements.json":"{}\n",
        "Assets/logox.png":"png","Cores/__init__.py":"","Cores/Update/__init__.py":"","Cores/Update/apply_update.py":"#\n",
        "Cores/Update/CurrentVersion.info":version+"\n","UI/windows/main.html":"<html></html>\n",
    })
    files.update(extra or {})
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for rel,data in files.items():
            z.writestr((prefix+"/" if prefix else "")+rel,data)
    return buf.getvalue()
def build_package_from_tree(root,version,prefix=None,mutate=None):
    """Zip an app tree the way a release is published (code only), with CurrentVersion.info set to version inside the zip only."""
    skip_top={"Data","Logs","Backups",".git",".venv_linux",".venv_windows","tests",".claude","__pycache__"}
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for base,dirs,fnames in os.walk(root):
            rel_dir=os.path.relpath(base,root).replace("\\","/")
            rel_dir="" if rel_dir=="." else rel_dir
            dirs[:]=[d for d in dirs if d!="__pycache__" and not (not rel_dir and d in skip_top) and not (rel_dir=="Cores/Update" and d=="OldVersions")]
            for fn in fnames:
                rel=(rel_dir+"/"+fn) if rel_dir else fn
                if fn.endswith((".pyc",".log")) or rel in ("Cores/Update/state.json","UI/js/appearance-boot.js"):continue
                data=open(os.path.join(base,fn),"rb").read()
                if rel=="Cores/Update/CurrentVersion.info":data=(version+"\n").encode()
                if mutate:data=mutate(rel,data)
                if data is None:continue
                z.writestr((prefix+"/" if prefix else "")+rel,data)
    return buf.getvalue()
def patch_updater_for(fake,helpers):
    """Point the in-process updater at the fake server. Returns an undo function. Test/sandbox only."""
    orig={k:getattr(helpers,k) for k in ("GITHUB_RELEASES_API_URL","is_official_package_url","is_allowed_download_redirect_url")}
    real_pkg=orig["is_official_package_url"];real_redirect=orig["is_allowed_download_redirect_url"]
    def pkg_ok(url,owner="",name="",tag=""):
        if real_pkg(url,owner,name,tag):return True
        p=urlparse(str(url or ""))
        if p.scheme!="http" or p.netloc!=f"127.0.0.1:{fake.port}":return False
        https_twin="https://github.com"+p.path
        return real_pkg(https_twin,owner,name,tag)
    def redirect_ok(url):
        p=urlparse(str(url or ""))
        return real_redirect(url) or (p.scheme=="http" and p.netloc==f"127.0.0.1:{fake.port}")
    helpers.GITHUB_RELEASES_API_URL=fake.base+fake.api_path()
    helpers.is_official_package_url=pkg_ok
    helpers.is_allowed_download_redirect_url=redirect_ok
    def undo():
        for k,v in orig.items():setattr(helpers,k,v)
    return undo
