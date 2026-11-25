import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
APP_NAME="LOYA NG"
DEFAULT_APP_VERSION="1.0.1"
OFFICIAL_SOURCE_REPO="https://github.com/emaldos/LOYA"
OFFICIAL_SOURCE_OWNER="emaldos"
OFFICIAL_SOURCE_NAME="LOYA"
# The repository was github.com/emaldos/LOYA-Note-NG before it moved; that name is no longer trusted for anything. A stored update
# state that still names it is rewritten to this repository by update_service.normalize_update_state.
# Internal id, kept for compatibility: the Windows AppUserModelID (taskbar pins, toast settings) is built from this, not from the repo name.
WINDOWS_APP_ID_NAME="LOYA-Note-NG"
REMOTE_MANIFEST_VERSION=1
GITHUB_RELEASES_API_URL=f"https://api.github.com/repos/{OFFICIAL_SOURCE_OWNER}/{OFFICIAL_SOURCE_NAME}/releases/latest"
_SEMVER_RX=re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHORT_VER_RX=re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_GITHUB_REPO_RX=re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?(?:$|#|\?)",re.I)
_SHA256_RX=re.compile(r"^[a-f0-9]{64}$",re.I)
_COMMIT_SHA_RX=re.compile(r"^[a-f0-9]{7,40}$",re.I)
_ALLOWED_DOWNLOAD_REDIRECT_HOSTS={"github.com","api.github.com","objects.githubusercontent.com","release-assets.githubusercontent.com","github-releases.githubusercontent.com"}
# The release must ship this zip asset; anything else (source zipballs, other names) is refused because it has no published SHA-256.
PACKAGE_ASSET_PREFIX="LOYA-NG-"
CHECKSUM_ASSET_NAMES=("SHA256SUMS","SHA256SUMS.txt")
MAX_PACKAGE_BYTES=200*1024*1024
MAX_CHECKSUM_BYTES=64*1024
MAX_RELEASE_NOTES_CHARS=20000
MAX_ZIP_ENTRIES=20000
MAX_ZIP_FILE_BYTES=100*1024*1024
MAX_ZIP_TOTAL_BYTES=600*1024*1024
MAX_ZIP_RATIO=200
_SHA_LINE_RX=re.compile(r"^\s*([a-f0-9]{64})\s+[ *]?(.+?)\s*$",re.I)
_BODY_SHA_RX=re.compile(r"sha-?256\s*(?:\(\s*`?([^)`]+?)`?\s*\))?\s*[:=]\s*`?([a-f0-9]{64})`?",re.I)
def root_dir():
    return Path(__file__).resolve().parents[2]
def update_dir():
    return root_dir().joinpath("Cores","Update")
def version_info_path():
    return update_dir().joinpath("CurrentVersion.info")
def legacy_version_info_path():
    return update_dir().joinpath("CurentVersion.info")
def update_state_path():
    return update_dir().joinpath("state.json")
def update_log_path():
    return root_dir().joinpath("Logs","Update_log.log")
def normalize_text(value):
    return str(value or "").strip()
def parse_semver(text):
    m=_SEMVER_RX.match(normalize_text(text))
    if not m:
        return None
    return int(m.group(1)),int(m.group(2)),int(m.group(3))
def is_semver(text):
    return bool(parse_semver(text))
def normalize_semver(text,fallback=""):
    parts=parse_semver(text)
    if not parts:
        return normalize_text(fallback)
    return ".".join(str(int(x)) for x in parts)
def coerce_local_version(text,fallback=""):
    raw=normalize_text(text)
    if not raw:
        return normalize_text(fallback)
    if raw[:1] in ("v","V"):
        raw=raw[1:].strip()
    ver=normalize_semver(raw,"")
    if ver:
        return ver
    m=_SHORT_VER_RX.match(raw)
    if m:
        return f"{int(m.group(1))}.{int(m.group(2))}.0"
    return normalize_text(fallback)
def compare_semver(a,b):
    av=parse_semver(a)
    bv=parse_semver(b)
    if not av or not bv:
        raise ValueError("compare_semver requires X.X.X values")
    if av<bv:
        return -1
    if av>bv:
        return 1
    return 0
def version_to_tag(version):
    ver=normalize_semver(version,"")
    return f"v{ver}" if ver else ""
def tag_to_version(tag):
    raw=normalize_text(tag)
    if raw[:1] in ("v","V"):
        raw=raw[1:].strip()
    return normalize_semver(raw,"")
def normalize_sha256(value):
    raw=normalize_text(value).lower()
    return raw if _SHA256_RX.fullmatch(raw) else ""
def normalize_commit_sha(value):
    raw=normalize_text(value).lower()
    return raw if _COMMIT_SHA_RX.fullmatch(raw) else ""
def canonical_repo_parts(repo_url=""):
    raw=normalize_text(repo_url)
    m=_GITHUB_REPO_RX.match(raw)
    if not m:
        return "","",""
    owner=normalize_text(m.group(1))
    name=normalize_text(m.group(2))
    canonical=f"https://github.com/{owner}/{name}"
    return owner,name,canonical
def canonical_repo_url(repo_url=""):
    return canonical_repo_parts(repo_url)[2]
def is_official_repo(repo_url="",owner="",name=""):
    if owner and name:
        return owner.lower()==OFFICIAL_SOURCE_OWNER.lower() and name.lower()==OFFICIAL_SOURCE_NAME.lower()
    got_owner,got_name,_=canonical_repo_parts(repo_url)
    if not got_owner or not got_name:
        return False
    return is_official_repo(owner=got_owner,name=got_name)
def _url_parts(url):
    try:
        p=urlparse(normalize_text(url))
        return p.scheme.lower(),p.netloc.lower(),p.path or ""
    except Exception:
        return "","",""
def is_allowed_download_redirect_url(url):
    # Every hop of a package download (GitHub answers with a redirect to its asset CDN) must stay on HTTPS GitHub hosts.
    scheme,host,_=_url_parts(url)
    return scheme=="https" and host in _ALLOWED_DOWNLOAD_REDIRECT_HOSTS
def is_official_package_url(url,owner="",name="",tag=""):
    # Only release assets of the official repository qualify (optionally of one exact tag). Source zipballs/archives are refused:
    # GitHub publishes no checksum for them, so they could never pass the integrity check.
    scheme,host,path=_url_parts(url)
    if scheme!="https":
        return False
    owner=(normalize_text(owner) or OFFICIAL_SOURCE_OWNER).lower()
    name=(normalize_text(name) or OFFICIAL_SOURCE_NAME).lower()
    if owner!=OFFICIAL_SOURCE_OWNER.lower() or name!=OFFICIAL_SOURCE_NAME.lower():
        return False
    path=(path or "").lower()
    if ".." in path.split("/"):
        return False
    if host=="github.com":
        prefix=f"/{owner}/{name}/releases/download/"
        if not path.startswith(prefix):
            return False
        rest=path[len(prefix):].split("/")
        if len(rest)!=2 or not rest[0] or not rest[1]:
            return False
        return not tag or rest[0]==normalize_text(tag).lower()
    if host=="api.github.com":
        return re.fullmatch(rf"/repos/{re.escape(owner)}/{re.escape(name)}/releases/assets/\d+",path) is not None
    return False
def expected_package_asset_name(version):
    tag=version_to_tag(version)
    return f"{PACKAGE_ASSET_PREFIX}{tag}.zip" if tag else ""
def parse_sha256_listing(text,asset_name):
    # SHA256SUMS format ("<hex>  <name>" or "<hex> *<name>"); returns the hash for asset_name, "" when absent.
    want=normalize_text(asset_name).lower()
    for line in str(text or "").splitlines():
        m=_SHA_LINE_RX.match(line)
        if m and m.group(2).strip().lstrip("./").lower()==want:
            return m.group(1).lower()
    return ""
def sha256_from_release_body(body,asset_name):
    # "SHA256: <hex>" or "SHA-256 (LOYA-NG-v1.0.1.zip): <hex>" in the release notes. A named line must name this asset.
    found=set()
    want=normalize_text(asset_name).lower()
    for m in _BODY_SHA_RX.finditer(str(body or "")):
        label=normalize_text(m.group(1)).lower()
        if label and label!=want:
            continue
        found.add(m.group(2).lower())
    if len(found)>1:
        raise ValueError("The release notes list more than one SHA-256 for the package.")
    return found.pop() if found else ""
def sha256_from_asset_digest(digest):
    raw=normalize_text(digest).lower()
    if raw.startswith("sha256:"):
        return normalize_sha256(raw[7:])
    return ""
def build_windows_app_id(version):
    ver=coerce_local_version(version,DEFAULT_APP_VERSION)
    owner=re.sub(r"[^A-Za-z0-9]+",".",OFFICIAL_SOURCE_OWNER).strip(".") or "loya"
    name=re.sub(r"[^A-Za-z0-9]+",".",WINDOWS_APP_ID_NAME).strip(".") or "note"
    return f"{owner}.{name}.{ver}"
def read_json(path,default=None):
    try:
        with open(path,"r",encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default
def write_json(path,obj):
    path=str(path)
    tmp=path+".tmp"
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(tmp,"w",encoding="utf-8") as fh:
        json.dump(obj,fh,ensure_ascii=False,indent=2)
    os.replace(tmp,path)
def read_text(path,default=""):
    try:
        with open(path,"r",encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return default
def write_text(path,text):
    path=str(path)
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"w",encoding="utf-8") as fh:
        fh.write(str(text))
def _to_size(value):
    try:
        n=int(value)
    except Exception:
        return 0
    return n if n>0 else 0
def remote_manifest_template(version="",release_id="",commit_sha="",package_sha256="",html_url="",asset_url="",published_at="",asset_name="",asset_size=0,release_name="",release_notes="",checksum_url="",digest_sha256="",body_sha256=""):
    ver=normalize_semver(version,"") or DEFAULT_APP_VERSION
    return {
        "manifest_version":REMOTE_MANIFEST_VERSION,
        "source_repo":OFFICIAL_SOURCE_REPO,
        "source_owner":OFFICIAL_SOURCE_OWNER,
        "source_name":OFFICIAL_SOURCE_NAME,
        "version":ver,
        "source_tag":version_to_tag(ver),
        "package_sha256":normalize_sha256(package_sha256),
        "release_id":normalize_text(release_id),
        "commit_sha":normalize_commit_sha(commit_sha),
        "html_url":normalize_text(html_url),
        "asset_url":normalize_text(asset_url),
        "asset_name":normalize_text(asset_name),
        "asset_size":_to_size(asset_size),
        "checksum_url":normalize_text(checksum_url),
        "digest_sha256":normalize_sha256(digest_sha256),
        "body_sha256":normalize_sha256(body_sha256),
        "release_name":normalize_text(release_name)[:200],
        "release_notes":str(release_notes or "")[:MAX_RELEASE_NOTES_CHARS],
        "published_at":normalize_text(published_at),
    }
def is_official_release_page(url,tag=""):
    scheme,host,path=_url_parts(url)
    if scheme!="https" or host!="github.com":
        return False
    base=f"/{OFFICIAL_SOURCE_OWNER}/{OFFICIAL_SOURCE_NAME}/releases".lower()
    path=(path or "").lower().rstrip("/")
    if path==base:
        return True
    return path==f"{base}/tag/{normalize_text(tag).lower()}" if tag else path.startswith(base+"/tag/")
def validate_remote_manifest(data):
    if not isinstance(data,dict):
        raise ValueError("Remote manifest must be an object.")
    repo_url=normalize_text(data.get("source_repo") or data.get("repo_url") or data.get("repository") or "")
    owner=normalize_text(data.get("source_owner") or data.get("owner") or "")
    name=normalize_text(data.get("source_name") or data.get("name") or "")
    if repo_url:
        owner2,name2,repo_url2=canonical_repo_parts(repo_url)
        if not owner2 or not name2:
            raise ValueError("Remote manifest source is not the official emaldos/LOYA repository.")
        if (owner and owner.lower()!=owner2.lower()) or (name and name.lower()!=name2.lower()):
            raise ValueError("Remote manifest source is not the official emaldos/LOYA repository.")
        owner=owner or owner2
        name=name or name2
        repo_url=repo_url2
    if not is_official_repo(repo_url=repo_url,owner=owner,name=name):
        raise ValueError("Remote manifest source is not the official emaldos/LOYA repository.")
    version=normalize_semver(data.get("version") or tag_to_version(data.get("source_tag") or data.get("tag_name") or ""), "")
    if not version:
        raise ValueError("Remote manifest version must use X.X.X format.")
    tag=normalize_text(data.get("source_tag") or data.get("tag_name") or version_to_tag(version))
    if tag!=version_to_tag(version):
        raise ValueError("Remote manifest tag does not match the semantic version.")
    package_sha256=normalize_sha256(data.get("package_sha256",""))
    release_id=normalize_text(data.get("release_id") or data.get("id") or "")
    commit_sha=normalize_commit_sha(data.get("commit_sha") or data.get("target_commitish") or "")
    asset_url=normalize_text(data.get("asset_url",""))
    if asset_url and not is_official_package_url(asset_url,owner or OFFICIAL_SOURCE_OWNER,name or OFFICIAL_SOURCE_NAME):
        raise ValueError("Remote manifest package URL is not a release asset of the official emaldos/LOYA repository.")
    checksum_url=normalize_text(data.get("checksum_url",""))
    if checksum_url and not is_official_package_url(checksum_url,owner or OFFICIAL_SOURCE_OWNER,name or OFFICIAL_SOURCE_NAME):
        raise ValueError("Remote manifest checksum URL is not a release asset of the official emaldos/LOYA repository.")
    html_url=normalize_text(data.get("html_url",""))
    if html_url and not is_official_release_page(html_url):
        html_url=""
    if not release_id and not commit_sha:
        raise ValueError("Remote manifest must include release_id or commit_sha.")
    manifest=remote_manifest_template(
        version=version,
        release_id=release_id,
        commit_sha=commit_sha,
        package_sha256=package_sha256,
        html_url=html_url,
        asset_url=asset_url,
        published_at=data.get("published_at",""),
        asset_name=data.get("asset_name",""),
        asset_size=data.get("asset_size",0),
        release_name=data.get("release_name",""),
        release_notes=data.get("release_notes",""),
        checksum_url=checksum_url,
        digest_sha256=data.get("digest_sha256",""),
        body_sha256=data.get("body_sha256",""),
    )
    if manifest["asset_size"]>MAX_PACKAGE_BYTES:
        raise ValueError(f"The release package is larger than the {MAX_PACKAGE_BYTES//(1024*1024)} MB limit.")
    manifest["manifest_version"]=int(data.get("manifest_version") or REMOTE_MANIFEST_VERSION)
    return manifest
_WIN_RESERVED={"con","prn","aux","nul",*{f"com{i}" for i in range(1,10)},*{f"lpt{i}" for i in range(1,10)}}
def safe_zip_member_parts(raw_name):
    # Normalised path parts of one zip entry, or ValueError when the name could escape the target folder on Windows or Linux.
    name=str(raw_name or "")
    if not name or "\x00" in name:
        raise ValueError("Package contains an empty or invalid entry name.")
    if "\\" in name:
        raise ValueError(f"Package entry uses backslashes: {name[:120]}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:",name):
        raise ValueError(f"Package entry has an absolute path: {name[:120]}")
    parts=[p for p in name.split("/") if p and p!="."]
    for p in parts:
        if p=="..":
            raise ValueError(f"Package entry escapes the package root: {name[:120]}")
        if ":" in p or p.rstrip(" .")!=p or p.split(".",1)[0].lower() in _WIN_RESERVED:
            raise ValueError(f"Package entry has a name Windows cannot store safely: {name[:120]}")
    return parts
def inspect_package_zip(zip_path):
    # Zip-safety gate run before anything is extracted: no traversal/absolute paths, no symlinks or special files, no encrypted
    # entries, no duplicate paths (case-insensitive, as on Windows), and size/ratio limits against zip bombs.
    import stat as _stat
    import zipfile as _zipfile
    rows=[];seen=set();total=0
    with _zipfile.ZipFile(zip_path,"r") as zf:
        infos=zf.infolist()
        if len(infos)>MAX_ZIP_ENTRIES:
            raise ValueError("Package has too many entries.")
        for info in infos:
            parts=safe_zip_member_parts(info.filename)
            if not parts:
                continue
            mode=(info.external_attr>>16)&0xFFFF
            ftype=_stat.S_IFMT(mode)
            if ftype and ftype not in (_stat.S_IFREG,_stat.S_IFDIR):
                raise ValueError(f"Package entry is a link or special file: {info.filename[:120]}")
            if info.flag_bits&0x1:
                raise ValueError("Package contains encrypted entries.")
            if info.is_dir():
                continue
            if info.file_size>MAX_ZIP_FILE_BYTES:
                raise ValueError(f"Package entry is too large: {info.filename[:120]}")
            if info.file_size>1024*1024 and info.compress_size>0 and info.file_size/info.compress_size>MAX_ZIP_RATIO:
                raise ValueError(f"Package entry has a suspicious compression ratio: {info.filename[:120]}")
            total+=info.file_size
            if total>MAX_ZIP_TOTAL_BYTES:
                raise ValueError("Package expands beyond the size limit.")
            rel="/".join(parts)
            key=rel.lower()
            if key in seen:
                raise ValueError(f"Package lists the same path twice: {rel[:120]}")
            seen.add(key)
            rows.append(rel)
    if not rows:
        raise ValueError("Downloaded package is empty.")
    return rows
def strip_package_prefix(rows):
    # Release zips may wrap everything in one top folder (LOYA-NG-v1.0.1/...); return (prefix, paths relative to the app root).
    tops={r.split("/",1)[0] for r in rows}
    if len(tops)==1 and all("/" in r for r in rows):
        prefix=tops.pop()
        return prefix,[r.split("/",1)[1] for r in rows]
    return "",list(rows)
