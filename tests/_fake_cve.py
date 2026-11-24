"""Test-only fake CVE sources: one 127.0.0.1 HTTP server standing in for NVD, CISA KEV, FIRST EPSS and CVE.org, plus fixtures
trimmed from real responses. The service is pointed at it in-process (ENDPOINTS/_TEST_HOSTS), never via settings or env vars."""
import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
def nvd_cve(cid="CVE-2021-44228",score=10.0,sev="CRITICAL",desc=None,published="2021-12-10T10:15:09.143",kev=True,vendor="apache",product="log4j",cwes=("CWE-502","CWE-400","CWE-20"),v40=False,refs=None):
    c={"id":cid,"sourceIdentifier":"security@apache.org","published":published,"lastModified":"2026-08-11T19:33:44.513","vulnStatus":"Analyzed","cveTags":[],
       "descriptions":[{"lang":"es","value":"Descripcion"},{"lang":"en","value":desc or "Apache Log4j2 2.0-beta9 through 2.15.0 JNDI features do not protect against attacker controlled LDAP and other JNDI related endpoints. An attacker who can control log messages can execute arbitrary code."}],
       "affected":[{"source":"security@apache.org","affectedData":[{"vendor":"Apache Software Foundation","product":"Apache Log4j2","versions":[{"version":"2.0-beta9","lessThan":"2.15.0","versionType":"custom","status":"affected"}]}]}],
       "metrics":{"cvssMetricV31":[{"source":"other@example.org","type":"Secondary","cvssData":{"version":"3.1","vectorString":"CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:L/A:L","baseScore":3.9,"baseSeverity":"LOW"}},
                                   {"source":"nvd@nist.gov","type":"Primary","cvssData":{"version":"3.1","vectorString":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H","baseScore":score,"baseSeverity":sev},"exploitabilityScore":3.9,"impactScore":6.0}],
                  "cvssMetricV2":[{"source":"nvd@nist.gov","type":"Primary","cvssData":{"version":"2.0","vectorString":"AV:N/AC:M/Au:N/C:C/I:C/A:C","baseScore":9.3},"baseSeverity":"HIGH"}],
                  "ssvcV203":[{"source":"134c704f","ssvcData":{"id":cid,"options":[{"exploitation":"active"}],"version":"2.0.3"}}]},
       "weaknesses":[{"source":"security@apache.org","type":"Secondary","description":[{"lang":"en","value":w} for w in cwes]},{"source":"nvd@nist.gov","type":"Primary","description":[{"lang":"en","value":"CWE-917"}]}],
       "configurations":[{"nodes":[{"operator":"OR","negate":False,"cpeMatch":[
           {"vulnerable":True,"criteria":f"cpe:2.3:a:{vendor}:{product}:*:*:*:*:*:*:*:*","versionStartIncluding":"2.0.1","versionEndExcluding":"2.3.1","matchCriteriaId":"X"},
           {"vulnerable":True,"criteria":f"cpe:2.3:a:{vendor}:{product}:2.0:beta9:*:*:*:*:*:*","matchCriteriaId":"Y"},
           {"vulnerable":False,"criteria":"cpe:2.3:h:siemens:6bk1602:-:*:*:*:*:*:*:*","matchCriteriaId":"Z"}]}]}],
       "references":refs if refs is not None else [
           {"url":"http://packetstormsecurity.com/files/165225/x.html","source":"s","tags":["Third Party Advisory","VDB Entry"]},
           {"url":"https://logging.apache.org/log4j/2.x/security.html","source":"s","tags":["Vendor Advisory"]},
           {"url":"https://github.com/apache/logging-log4j2/pull/608","source":"s","tags":["Patch"]},
           {"url":"https://example.org/poc","source":"s","tags":["Exploit"]},
           {"url":"javascript:alert(1)","source":"s","tags":["Patch"]},
           {"url":"https://evil.example/\"><script>alert(1)</script>","source":"s","tags":["Vendor Advisory"]}]}
    if v40:c["metrics"]["cvssMetricV40"]=[{"source":"cna@example.org","type":"Secondary","cvssData":{"version":"4.0","vectorString":"CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N","baseScore":9.3,"baseSeverity":"CRITICAL"}}]
    if kev:c.update({"cisaExploitAdd":"2021-12-10","cisaActionDue":"2021-12-24","cisaRequiredAction":"Apply updates per vendor instructions.","cisaVulnerabilityName":"Apache Log4j2 Remote Code Execution Vulnerability"})
    return c
def nvd_page(cves,total=None,start=0):
    return {"resultsPerPage":len(cves),"startIndex":start,"totalResults":len(cves) if total is None else total,"format":"NVD_CVE","version":"2.0","timestamp":"2026-11-23T18:48:13.335","vulnerabilities":[{"cve":c} for c in cves]}
def kev_catalog(entries=None):
    rows=entries if entries is not None else [kev_entry()]
    return {"title":"CISA Catalog of Known Exploited Vulnerabilities","catalogVersion":"2026.11.23","dateReleased":"2026-11-23T12:54:37.9646Z","count":len(rows),"vulnerabilities":rows}
def kev_entry(cid="CVE-2021-44228",added="2021-12-10",vendor="Apache",product="Log4j2",ransomware="Known",name=None):
    return {"cveID":cid,"vendorProject":vendor,"product":product,"vulnerabilityName":name or f"{vendor} {product} Remote Code Execution Vulnerability","dateAdded":added,"shortDescription":f"{vendor} {product} contains a vulnerability that allows remote code execution.",
            "requiredAction":"For all affected software assets for which updates exist, the only acceptable remediation actions are: 1) Apply updates; OR 2) remove affected assets from agency networks.","dueDate":"2021-12-24","knownRansomwareCampaignUse":ransomware,"forensicTriage":"Yes","notes":"https://nvd.nist.gov/vuln/detail/"+cid,"cwes":["CWE-502"]}
def epss(rows):
    return {"status":"OK","status-code":200,"version":"1.0","access":"public","total":len(rows),"offset":0,"limit":100,"data":[{"cve":c,"epss":s,"percentile":p,"date":"2026-11-23"} for c,s,p in rows]}
def cveorg(cid="CVE-2026-0001",state="PUBLISHED"):
    return {"dataType":"CVE_RECORD","dataVersion":"5.1","cveMetadata":{"state":state,"cveId":cid,"assignerShortName":"acme","dateUpdated":"2026-11-20T10:00:00.000Z","datePublished":"2026-11-19T00:00:00.000Z"},
            "containers":{"cna":{"title":"Acme Router command injection","providerMetadata":{"shortName":"acme"},"descriptions":[{"lang":"en","value":"Acme Router firmware before 3.2 allows OS command injection through the ping form."}],
                "affected":[{"vendor":"Acme","product":"Router","versions":[{"version":"0","status":"affected","lessThan":"3.2","versionType":"semver"}]}],
                "references":[{"url":"https://acme.example/advisories/1","tags":["vendor-advisory"]},{"url":"http://acme.example/old","tags":["patch"]}],
                "metrics":[{"cvssV3_1":{"version":"3.1","vectorString":"CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H","baseScore":8.8,"baseSeverity":"HIGH"}},{"other":{"type":"unknown","content":{"other":"critical"}}}],
                "problemTypes":[{"descriptions":[{"type":"CWE","lang":"en","description":"CWE-78 OS Command Injection","cweId":"CWE-78"}]}]},
              "adp":[{"providerMetadata":{"shortName":"CVE"},"title":"CVE Program Container","references":[{"url":"https://acme.example/advisories/1","tags":["x_transferred"]}]}]}}
class FakeCve:
    """routes: path -> handler(query dict, headers) -> (status, body dict|bytes, headers dict). hits: [(path, query, headers)]."""
    def __init__(self):
        self.routes={};self.hits=[]
        fake=self
        class H(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                u=urlparse(self.path)
                q={k:v[0] for k,v in parse_qs(u.query,keep_blank_values=True).items()}
                fake.hits.append((u.path,q,{k.lower():v for k,v in self.headers.items()}))
                fn=None
                for prefix,f in fake.routes.items():
                    if u.path==prefix or (prefix.endswith("/") and u.path.startswith(prefix)):fn=f
                if fn is None:
                    self.send_response(404);self.send_header("Content-Length","0");self.end_headers();return
                status,body,headers=fn(q,{k.lower():v for k,v in self.headers.items()},u.path)
                if isinstance(body,(dict,list)):body=json.dumps(body).encode()
                self.send_response(status)
                for k,v in (headers or {}).items():self.send_header(k,v)
                self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body or b"")));self.end_headers()
                if body:self.wfile.write(body)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),H)
        self.port=self.server.server_address[1]
        self.base=f"http://127.0.0.1:{self.port}"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def start(self):
        self.thread.start();return self
    def stop(self):
        self.server.shutdown();self.server.server_close()
    def on(self,path,fn):self.routes[path]=fn
    def json(self,path,payload,status=200,headers=None):self.routes[path]=lambda q,h,p:(status,payload,headers or {})
    def paths(self):return [h[0] for h in self.hits]
def patch_service(fake,svc):
    """Point cve_service at the fake server. Returns an undo function. Test only."""
    orig=dict(svc.ENDPOINTS)
    svc.ENDPOINTS.update({"nvd":fake.base+"/rest/json/cves/2.0","kev":fake.base+"/kev.json","epss":fake.base+"/data/v1/epss","cveorg":fake.base+"/api/cve/","gh_api":fake.base+"/ghapi","gh_dl":fake.base+"/gh"})
    svc._TEST_HOSTS.add(f"127.0.0.1:{fake.port}")
    def undo():
        svc.ENDPOINTS.clear();svc.ENDPOINTS.update(orig);svc._TEST_HOSTS.discard(f"127.0.0.1:{fake.port}")
    return undo
def cve_record(cid,title="",desc="A flaw.",state="PUBLISHED",score=None,sev="",vector="",cwe="",vendor="",product="",published="2026-11-01T10:00:00.000Z",updated="2026-11-02T10:00:00.000Z",adp_score=None):
    """A cvelistV5 (CVE JSON 5.x) record for index tests."""
    cna={"descriptions":[{"lang":"en","value":desc}]}
    if title:cna["title"]=title
    if score is not None:cna["metrics"]=[{"cvssV3_1":{"version":"3.1","vectorString":vector or "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","baseScore":score,"baseSeverity":sev or "HIGH"}}]
    if cwe:cna["problemTypes"]=[{"descriptions":[{"type":"CWE","lang":"en","description":cwe+" Something","cweId":cwe}]}]
    if vendor or product:cna["affected"]=[{"vendor":vendor,"product":product,"versions":[{"version":"1.0","status":"affected"}]}]
    meta={"cveId":cid,"state":state,"datePublished":published,"dateUpdated":updated}
    if state=="REJECTED":
        cna={"rejectedReasons":[{"lang":"en","value":"This CVE ID was rejected because it is a duplicate."}]};meta={"cveId":cid,"state":state,"dateRejected":published,"dateUpdated":updated}
    rec={"dataType":"CVE_RECORD","dataVersion":"5.1","cveMetadata":meta,"containers":{"cna":cna}}
    if adp_score is not None:rec["containers"]["adp"]=[{"title":"CISA ADP Vulnrichment","metrics":[{"cvssV3_1":{"version":"3.1","vectorString":"CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:L/I:L/A:L","baseScore":adp_score,"baseSeverity":"MEDIUM"}}]}]
    return rec
def delta_zip(records,folder="deltaCves"):
    import io,zipfile
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for r in records:z.writestr(f"{folder}/{r['cveMetadata']['cveId']}.json",json.dumps(r))
    return buf.getvalue()
def gh_release(fake,repo,tag,name,data,digest=True,size=None,url=None,api_path=None):
    """Publish one release asset on the fake GitHub: the API JSON (by tag, or api_path such as .../releases/latest) and the file itself."""
    import hashlib
    dl=f"/gh/{repo}/releases/download/{tag}/{name}"
    fake.routes[dl]=lambda q,h,p:(200,data,{})
    asset={"name":name,"size":len(data) if size is None else size,"browser_download_url":url or (fake.base+dl)}
    if digest:asset["digest"]="sha256:"+(hashlib.sha256(data).hexdigest() if digest is True else digest)
    fake.json(api_path or f"/ghapi/repos/{repo}/releases/tags/{tag}",{"tag_name":tag,"assets":[asset,{"name":"release_notes.md","size":3,"browser_download_url":fake.base+"/x"}]})
    return asset
