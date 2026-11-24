// Reporting: Markdown <-> rich subset (ReportCore.markdownToHtml / htmlToMarkdown / mdShortcut). Run: node tests/js/reporting_markdown.js
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const RC=require(path.join(ROOT,"UI","js","pages","reporting_core.js"))
const MD=require(path.join(ROOT,"UI","js","components","markdown.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const H=(md)=>RC.markdownToHtml(md,MD)
const M=RC.htmlToMarkdown
const UID="0123456789abcdef0123456789abcdef"

// ---- typed block prefixes ----
;[
["#","space",{type:"h3"}],["##","space",{type:"h3"}],["###","space",{type:"h4"}],["######","space",{type:"h4"}],["#######","space",null],
["-","space",{type:"ul"}],["*","space",{type:"ul"}],["+","space",{type:"ul"}],["1.","space",{type:"ol"}],["12)","space",{type:"ol"}],["1234.","space",null],
[">","space",{type:"quote"}],["[]","space",{type:"check",checked:false}],["[ ]","space",{type:"check",checked:false}],["[x]","space",{type:"check",checked:true}],["[X]","space",{type:"check",checked:true}],
["```","space",{type:"code",lang:""}],["```","enter",{type:"code",lang:""}],["```bash","enter",{type:"code",lang:"bash"}],["``` Python","enter",{type:"code",lang:"python"}],["~~~c++","enter",{type:"code",lang:"c++"}],
["```two words","enter",null],["```"+"a".repeat(33),"enter",null],["---","enter",{type:"hr"}],["*****","enter",{type:"hr"}],["___","enter",{type:"hr"}],["--","enter",null],["---","space",null],
["text","space",null],["","space",null],["# x","space",null],["#​","space",{type:"h3"}],["[ ]","space",{type:"check",checked:false}],[null,"space",null],[undefined,"enter",null]
].forEach((c)=>eq("mdShortcut "+JSON.stringify(c[0])+" "+c[1],RC.mdShortcut(c[0],c[1]),c[2]))

// ---- Markdown -> subset ----
eq("headings map to h3/h4",H("# One\n## Two\n### Three\n###### Six"),"<h3>One</h3><h3>Two</h3><h4>Three</h4><h4>Six</h4>")
eq("heading inside a quote",H("> # Q\n> text"),"<blockquote><h3>Q</h3><p>text</p></blockquote>")
eq("inline formatting",H("a **b** *i* _j_ ~~s~~ `c` [l](https://x.test/p) end"),"<p>a <b>b</b> <i>i</i> <i>j</i> <s>s</s> <code>c</code> <a href=\"https://x.test/p\">l</a> end</p>")
eq("fenced code keeps its language",H("```bash\nls -la | grep <x>\n```"),"<pre data-lang=\"bash\">ls -la | grep &lt;x&gt;</pre>")
eq("fenced code without language",H("```\na\n\nb\n```"),"<pre>a\n\nb</pre>")
eq("nothing converts inside code",H("```\n# not **bold** \\* <u>x</u> ![a](rptasset:"+UID+")\n```\n\n`**x** \\_ <redact>`"),"<pre># not **bold** \\* &lt;u&gt;x&lt;/u&gt; ![a](rptasset:"+UID+")</pre><p><code>**x** \\_ &lt;redact&gt;</code></p>")
eq("lists",H("- a\n- b\n  - c\n\n1. x\n2. y"),"<ul><li>a</li><li>b<ul><li>c</li></ul></li></ul><ol><li>x</li><li>y</li></ol>")
eq("task list is a checklist (subset v2)",H("- [ ] todo\n- [x] done\n- plain\n\n- no boxes"),"<ul class=\"note-checklist\"><li>todo</li><li data-checked=\"1\">done</li><li>plain</li></ul><ul><li>no boxes</li></ul>")
eq("escaped backtick does not open a code span",H("a \\` b `c` \\\\`d`"),"<p>a ` b <code>c</code> \\<code>d</code></p>")
eq("quote",H("> one\n> two\n\nafter"),"<blockquote><p>one<br>two</p></blockquote><p>after</p>")
eq("rule",H("a\n\n---\n\nb"),"<p>a</p><hr><p>b</p>")
eq("table",H("| A | B |\n|---|:-:|\n| 1 | **2** |\n| 3 |"),"<table class=\"note-table\"><tbody><tr><th>A</th><th>B</th></tr><tr><td>1</td><td><b>2</b></td></tr><tr><td>3</td><td><br></td></tr></tbody></table>")
eq("report image",H("See ![login page](rptasset:"+UID+") here"),"<p>See <img src=\"rptasset:"+UID+"\" alt=\"login page\"> here</p>")
eq("report image with a width",H("![s](rptasset:"+UID+" \"width=50%\")"),"<p><img src=\"rptasset:"+UID+"\" alt=\"s\" data-width=\"50%\"></p>")
eq("image alt is escaped",H("![a\"><b>x](rptasset:"+UID+")"),"<p><img src=\"rptasset:"+UID+"\" alt=\"a&quot;&gt;&lt;b&gt;x\"></p>")
eq("foreign images never become <img>",H("![x](https://evil.test/a.png) ![y](data:image/png;base64,AAAA) ![z](rptasset:bad uid)").indexOf("<img"),-1)
eq("underline and redaction",H("a <u>under</u> b <redact>hunter2</redact> c"),"<p>a <u>under</u> b <span class=\"rpt-redact\">hunter2</span> c</p>")
eq("unclosed redaction is closed by the sanitiser",H("x <redact>secret"),"<p>x <span class=\"rpt-redact\">secret</span></p>")
eq("backslash escapes",H("\\# no heading\n\n1\\. no list\n\n\\*no\\* \\_it\\_ \\`c\\` \\[l\\](x) \\<u> a \\\\ b"),"<p># no heading</p><p>1. no list</p><p>*no* _it_ `c` [l](x) &lt;u&gt; a \\ b</p>")
eq("escaped pipe stays in its cell",H("| a \\| b | c |\n|---|---|"),"<table class=\"note-table\"><tbody><tr><th>a | b</th><th>c</th></tr></tbody></table>")
eq("quotes are written like the rich view writes them",H("it's \"q\""),"<p>it's \"q\"</p>")
eq("evidence fence (output)",H("```evidence ev-1\n$ id — exit 0\nuid=0(root)\n<b>raw</b>\n```"),"<figure class=\"rpt-ev\" data-evidence=\"ev-1\"><figcaption>$ id — exit 0</figcaption><pre>uid=0(root)\n&lt;b&gt;raw&lt;/b&gt;</pre></figure>")
eq("evidence fence (screenshot)",H("```evidence ev-2\nLogin page\n![Login page](rptasset:"+UID+")\n```"),"<figure class=\"rpt-ev\" data-evidence=\"ev-2\"><figcaption>Login page</figcaption><img src=\"rptasset:"+UID+"\" alt=\"Login page\"></figure>")
eq("evidence fence without uid",H("```evidence\ncap\nout\n```"),"<figure class=\"rpt-ev\"><figcaption>cap</figcaption><pre>out</pre></figure>")
eq("evidence fence with a hostile uid",H("```evidence \"><script>\ncap\nout\n```").indexOf("data-evidence"),-1)
eq("evidence fence between paragraphs",H("a\n```evidence e1\nc\no\n```\nb"),"<p>a</p><figure class=\"rpt-ev\" data-evidence=\"e1\"><figcaption>c</figcaption><pre>o</pre></figure><p>b</p>")
eq("raw subset block",H("```rpt-html\n<table><tbody><tr><td colspan=\"2\">wide</td></tr></tbody></table><script>alert(1)</script>\n```"),"<table><tbody><tr><td colspan=\"2\">wide</td></tr></tbody></table>")
eq("empty",H(""),"");eq("null",H(null),"");eq("whitespace",H("  \n\n "),"")
eq("crlf",H("# T\r\n\r\ntext\r\n"),"<h3>T</h3><p>text</p>")
eq("works without LoyaMarkdown passed in",RC.markdownToHtml("# T"),"<h3>T</h3>")

// ---- subset -> Markdown ----
eq("md headings",M("<h3>One</h3><h4>Two</h4>"),"## One\n\n### Two")
eq("md inline",M("<p>a <strong>b</strong> <b>c</b> <em>d</em> <i>e</i> <s>f</s> <u>g</u> <code>h</code> <a href=\"https://x.test/p?a=1&amp;b=2\">l</a></p>"),"a **b** **c** *d* *e* ~~f~~ <u>g</u> `h` [l](https://x.test/p?a=1&b=2)")
eq("md nested emphasis",M("<p><b>a <i>b</i></b> <i>c <b>d</b></i></p>"),"**a _b_** _c **d**_")
eq("md emphasis keeps spaces outside the markers",M("<p>a<b> b </b>c</p>"),"a **b** c")
eq("md code with backticks",M("<p><code>a `b` c</code> <code>``</code></p>"),"``a `b` c`` ``` `` ```")
eq("md link with brackets and parentheses",M("<p><a href=\"https://x.test/a_(b)\">a [b]</a></p>"),"[a \\[b\\]](https://x.test/a_%28b%29)")
eq("md line break",M("<p>a<br>b</p>"),"a\nb")
eq("md text that looks like Markdown is escaped",M("<p># not a heading</p><p>1. not a list</p><p>- dash</p><p>&gt; quote</p><p>a * b _ c `d` [e] snake_case</p><p>---</p>"),"\\# not a heading\n\n1\\. not a list\n\n\\- dash\n\n\\> quote\n\na \\* b \\_ c \\`d\\` \\[e\\] snake_case\n\n\\---")
eq("md pre",M("<pre data-lang=\"bash\">ls -la\n  x &lt;y&gt;</pre><pre>plain</pre>"),"```bash\nls -la\n  x <y>\n```\n\n```\nplain\n```")
eq("md pre containing a fence",M("<pre>a\n```\nb</pre>"),"````\na\n```\nb\n````")
eq("md pre with a redaction stays a raw block",M("<pre>pw: <span class=\"rpt-redact\">x</span></pre>"),"```rpt-html\n<pre>pw: <span class=\"rpt-redact\">x</span></pre>\n```")
eq("md quote",M("<blockquote><p>a</p><p>b</p><ul><li>c</li></ul></blockquote>"),"> a\n>\n> b\n>\n> - c")
eq("md lists",M("<ul><li>a</li><li>b<ul><li>c</li><li>d<ol><li>e</li></ol></li></ul></li></ul><ol><li>x</li><li>y</li></ol>"),"- a\n- b\n  - c\n  - d\n    1. e\n\n1. x\n2. y")
eq("md task list",M("<ul><li>☐ todo</li><li>☑ done</li><li>☐</li></ul>"),"- [ ] todo\n- [x] done\n- [ ] ")
eq("md list item with a line break",M("<ul><li>a<br>b</li></ul>"),"- a\n  b")
eq("md table",M("<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1 | x</td><td><b>2</b></td></tr><tr><td><br></td><td>4</td></tr></tbody></table>"),"| A | B |\n| --- | --- |\n| 1 \\| x | **2** |\n|   | 4 |")
eq("md table with spans stays a raw block",M("<table><tbody><tr><td colspan=\"2\">w</td></tr></tbody></table>"),"```rpt-html\n<table><tbody><tr><td colspan=\"2\">w</td></tr></tbody></table>\n```")
eq("md rule",M("<p>a</p><hr><p>b</p>"),"a\n\n---\n\nb")
eq("md image",M("<p><img src=\"rptasset:"+UID+"\" alt=\"login [1]\" data-width=\"50%\"></p>"),"![login \\[1\\]](rptasset:"+UID+" \"width=50%\")")
eq("md evidence figure",M("<figure class=\"rpt-ev\" data-evidence=\"ev-1\"><figcaption>$ id — exit 0</figcaption><pre>uid=0(root)\n```</pre></figure>"),"````evidence ev-1\n$ id — exit 0\nuid=0(root)\n```\n````")
eq("md evidence screenshot",M("<figure class=\"rpt-ev\" data-evidence=\"ev-2\"><figcaption>Login</figcaption><img src=\"rptasset:"+UID+"\" alt=\"Login\"></figure>"),"```evidence ev-2\nLogin\n![Login](rptasset:"+UID+")\n```")
eq("md redaction",M("<p>pw <span class=\"rpt-redact\">hunter2</span> <code><span class=\"rpt-redact\">k</span></code></p>"),"pw <redact>hunter2</redact> <redact>`k`</redact>")
eq("md loose text",M("loose <b>text</b><p>para</p>tail"),"loose **text**\n\npara\n\ntail")
eq("md empty",M(""),"");eq("md blank paragraphs",M("<p><br></p><p> </p>"),"")
eq("md input is sanitised first",M("<p onclick=x>a<script>alert(1)</script></p><img src=\"https://evil.test/x.png\">"),"a")

// ---- round trips: html -> md -> html is stable for everything the subset holds ----
const DOCS=[
"<h3>Executive summary</h3><p>During the test <b>two</b> issues were found on <code>10.10.20.5</code>, see <a href=\"https://example.com/adv?id=1&amp;x=2\">the advisory</a>.</p>",
"<h4>Steps</h4><ol><li>Log in as a low-privileged user</li><li>Request another profile<ul><li>id 1001</li><li>id 1002</li></ul></li></ol>",
"<ul class=\"note-checklist\"><li data-checked=\"1\">Reproduced</li><li>Retest after fix</li></ul>",
"<blockquote><p>Rules of engagement forbid destructive tests.</p><p>Second paragraph.</p></blockquote>",
"<blockquote><p><b>Finding — High (CVSS 8.8)</b></p><p>SQL injection</p><blockquote><p><b>Evidence</b></p><pre data-lang=\"output\">uid=0(root)</pre></blockquote></blockquote>",
"<pre data-lang=\"http\">GET /api/v1/users/1001 HTTP/1.1\nHost: portal.example\n\n{\"a\":\"<b>\"}</pre>",
"<pre>  indented\n\ttab\n\n# hash\n```\ninner fence</pre>",
"<table class=\"note-table\"><tbody><tr><th>Endpoint</th><th>Status</th></tr><tr><td>/admin</td><td>403</td></tr><tr><td>/api | v1</td><td><br></td></tr></tbody></table>",
// subset v2: the Notes editor's structures survive the Markdown source view
"<div class=\"note-callout\" data-callout=\"finding\" data-sev=\"high\" data-cvss=\"8.1\"><h3>SQL injection</h3><p>The <code>id</code> parameter is injectable.</p><ul class=\"note-checklist\"><li data-checked=\"1\">Reproduced</li><li>Reported</li></ul></div>",
"<div class=\"note-callout\" data-callout=\"warning\"><p>Out of scope: 10.0.0.9</p></div><p>after</p>",
"<div class=\"note-callout\" data-callout=\"credential\"><p><b>Host:</b> 10.10.10.5 - SMB</p><p><b>Secret:</b> <span class=\"note-secret\">P@ssw0rd!</span></p></div>",
"<div class=\"note-callout\" data-callout=\"vuln\" data-sev=\"low\"><p>Outer</p><div class=\"note-callout\" data-callout=\"evidence\"><pre data-lang=\"output\">uid=0(root)</pre></div></div>",
"<ol start=\"5\"><li>five</li><li>six</li></ol>",
"<p>See <span class=\"rpt-fref\" data-finding=\"ab12_cd-9\">F-03 SQL injection</span> for <span class=\"rpt-ph\" data-token=\"client\">{{client}}</span>.</p>",
"<p><span data-color=\"#ff0000\" data-bg=\"#fff3bf\" data-size=\"18\">loud</span> and <span data-color=\"#1c7ed6\">blue <b>bold</b></span></p>",
"<figure class=\"note-embed note-align-center note-sketch\" data-kind=\"sketch\" data-asset=\""+UID+"\" data-shapes=\"eyJ2IjoxfQ\"><img src=\"rptasset:"+UID+"\" alt=\"Drawing\" data-width=\"420px\"></figure>",
"<figure class=\"rpt-cmd\" data-type=\"Linux Shell\" data-cat=\"Recon\"><figcaption>Full scan</figcaption><p>All ports</p><pre>nmap -p- 10.0.0.5 | tee out</pre></figure>",
"<p>before</p><div class=\"rpt-widget\" data-widget=\"risk_matrix\"></div><p>after</p>",
"<table class=\"note-table note-table-head\"><tbody><tr><th data-width=\"120\">Severity</th><td>High</td></tr></tbody></table>",
"<table><tbody><tr><th colspan=\"2\">Wide</th></tr><tr><td rowspan=\"2\">a</td><td>b</td></tr><tr><td>c</td></tr></tbody></table>",
"<p>a</p><hr><p>b<br>c</p>",
"<p>Shot: <img src=\"rptasset:"+UID+"\" alt=\"login page\" data-width=\"75%\"></p>",
"<figure class=\"rpt-ev\" data-evidence=\"ev-9\"><figcaption>$ nmap -sV 10.0.0.5 — exit 0 — 2026-11-23 10:12 UTC</figcaption><pre>PORT   STATE\n22/tcp open  &lt;ssh&gt; &amp; more</pre></figure>",
"<figure class=\"rpt-ev\" data-evidence=\"ev-3\"><figcaption>Login page</figcaption><img src=\"rptasset:"+UID+"\" alt=\"Login page\"></figure>",
"<p>Password: <span class=\"rpt-redact\">Summer2026!</span> and <u>underlined</u> and <s>struck</s> and <i>it</i>.</p>",
"<pre>token: <span class=\"rpt-redact\">eyJ</span></pre>",
"<p># not a heading</p><p>1. not a list</p><p>- not a bullet</p><p>&gt; not a quote</p><p>a * b ** c _ d ` e [f](g) \\ h ~~ i | j</p><p>---</p><p>| a | b |<br>|---|---|</p>",
"<p>5 &lt; 6 &amp;&amp; 7 &gt; 6, it's \"quoted\"</p>",
"<p><b>bold <i>both</i></b> and <i>italic <b>both</b></i></p>",
"<h3>A</h3><p>x</p><h4>B</h4><ul><li>one <code>c</code></li><li><b>two</b></li></ul><p>y</p>"
]
DOCS.forEach((doc,i)=>{
const clean=RC.sanitizeHtml(doc)
const md=M(clean)
const back=H(md)
// LoyaMarkdown writes <b>/<i>; the stored subset allows both spellings.
eq("round trip html->md->html #"+i,back,clean)
eq("round trip is stable #"+i,M(back),md)
})
// md -> html -> md for the common cases
;[
"## Title\n\nSome **bold**, *italic*, ~~struck~~ and `code`.",
"- a\n- b\n  - c\n\n1. x\n2. y",
"- [ ] todo\n- [x] done",
"> quote\n> more\n\nafter",
"```bash\nls -la\n```",
"| A | B |\n| --- | --- |\n| 1 | 2 |",
"a\n\n---\n\nb",
"![shot](rptasset:"+UID+")",
"```evidence ev-1\n$ id — exit 0\nuid=0(root)\n```",
"x <redact>secret</redact> y <u>z</u>",
"### Deep\n\n[link](https://example.com/a)"
].forEach((md,i)=>eq("round trip md->html->md #"+i,M(H(md)),md))

// ---- hostile Markdown never leaves the subset ----
const ALLOWED="p br h3 h4 strong b em i u s code pre blockquote ul ol li a table thead tbody tr th td hr img figure figcaption span div".split(" ")
const ATTRS={a:["href"],td:["colspan","rowspan","data-width","data-align"],th:["colspan","rowspan","data-width","data-align"],img:["src","alt","data-width"],figure:["class","data-evidence","data-kind","data-asset","data-shapes","data-type","data-cat","data-sub","data-tags"],span:["class","data-finding","data-token","data-color","data-bg","data-size"],pre:["data-lang"],
div:["class","data-callout","data-sev","data-cvss","data-widget"],ul:["class"],ol:["start"],table:["class"],li:["data-checked","data-align"],p:["data-align"],h3:["data-align","data-collapsed"],h4:["data-align","data-collapsed"],blockquote:["data-align"]}
const CLASSES="rpt-ev rpt-redact rpt-cmd rpt-widget rpt-fref rpt-ph note-callout note-finding note-secret note-ts note-checklist note-table note-table-head note-align-center note-align-right note-embed note-embed-inline note-embed-float-left note-embed-float-right note-sketch".split(" ")
function audit(html){
const problems=[]
const rest=html.replace(/<(\/?)([a-zA-Z0-9]+)((?:\s+[a-z\-]+="[^"<>]*")*)>/g,(all,close,name,attrs)=>{
if(ALLOWED.indexOf(name)<0)problems.push("tag "+name)
attrs.replace(/\s+([a-z\-]+)="([^"<>]*)"/g,(m,k,v)=>{
if((ATTRS[name]||[]).indexOf(k)<0)problems.push("attr "+name+"."+k)
if(k==="class"&&v.split(" ").some((c)=>CLASSES.indexOf(c)<0))problems.push("class "+v)
if(/^data-|^start$/.test(k)&&!/^[A-Za-z0-9 ._+#\/(),%\-]*$/.test(v))problems.push(k+" "+v)
if(k==="href"&&!/^(https?:\/\/|mailto:)/i.test(v))problems.push("href "+v)
if(k==="src"&&!/^rptasset:[A-Za-z0-9_.\-]+$/.test(v))problems.push("src "+v)
return ""
})
return ""
})
if(/[<>]/.test(rest))problems.push("stray angle bracket in "+rest)
return problems
}
;[
"<script>alert(1)</script>","<img src=x onerror=alert(1)>","[x](javascript:alert(1))","[x](data:text/html,<script>alert(1)</script>)","![x](javascript:alert(1))",
"<u onclick=alert(1)>x</u>","<redact onmouseover=alert(1)>x</redact>","<u><script>alert(1)</script></u>","```rpt-html\n<script>alert(1)</script><img src=x onerror=alert(1)><a href=\"javascript:alert(1)\">x</a>\n```",
"```evidence x\" onclick=\"alert(1)\n<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n```","![a](rptasset:"+UID+" \"width=50%\\\" onerror=\\\"alert(1)\")","![\" onerror=\"alert(1)](rptasset:"+UID+")",
"[a](https://x.test/\"onmouseover=\"alert(1))","[<u>](https://x.test/<u>)","[![a](rptasset:"+UID+")](https://x.test/![a](rptasset:"+UID+"))","1 999  script ",
"> [!FINDING] severity=high\" onclick=\"alert(1) cvss=<script>alert(1)</script>\n> <img src=x onerror=alert(1)>","> [!EVIL] x\n> y","<secret onclick=alert(1)>x</secret>","<fref a\" onmouseover=\"alert(1)>x</fref>","<span data-color=\"#fff\" style=\"background:url(javascript:alert(1))\">x</span>","<span data-color=\"red;x\">y</span>","{{client}} {{<script>}} {{constructor}}",
"| <script>alert(1)</script> | b |\n|---|---|\n| <img src=x onerror=alert(1)> | 2 |","> <iframe src=javascript:alert(1)>","# <svg onload=alert(1)>","- [ ] <style>*{x:expression(alert(1))}</style>"
].forEach((md,i)=>{
const out=H(md)
check("hostile markdown stays in the subset #"+i,audit(out).length===0,audit(out).join("; ")+"  <=  "+out)
eq("hostile markdown output is already clean #"+i,RC.sanitizeHtml(out),out)
check("hostile markdown round-trips inside the subset #"+i,audit(H(M(out))).length===0,H(M(out)))
})

// ---- subset v2 in Markdown ----
eq("callout -> alert quote",M("<div class=\"note-callout\" data-callout=\"finding\" data-sev=\"high\" data-cvss=\"8.1\"><p>x</p></div>"),"> [!FINDING] severity=high cvss=8.1\n>\n> x")
eq("alert quote -> callout",H("> [!WARNING]\n> Out of scope"),"<div class=\"note-callout\" data-callout=\"warning\"><p>Out of scope</p></div>")
eq("GitHub alert names map to callouts",H("> [!NOTE]\n> a\n\n> [!CAUTION]\n> b"),"<div class=\"note-callout\" data-callout=\"info\"><p>a</p></div><div class=\"note-callout\" data-callout=\"warning\"><p>b</p></div>")
eq("an unknown alert name stays a quote",H("> [!EVIL] x\n> y"),"<blockquote><p>[!EVIL] x<br>y</p></blockquote>")
eq("bad severity / cvss on the marker are dropped",H("> [!VULN] severity=extreme cvss=11\n> t"),"<div class=\"note-callout\" data-callout=\"vuln\"><p>t</p></div>")
eq("checklist -> task list",M("<ul class=\"note-checklist\"><li data-checked=\"1\">a</li><li>b</li></ul>"),"- [x] a\n- [ ] b")
eq("masked secret",M("<p>pw <span class=\"note-secret\">s3cret</span></p>"),"pw <secret>s3cret</secret>")
eq("masked secret reads back",H("pw <secret>s3cret</secret>"),"<p>pw <span class=\"note-secret\">s3cret</span></p>")
eq("placeholder chip is its token",M("<p><span class=\"rpt-ph\" data-token=\"client\">{{client}}</span></p>"),"{{client}}")
eq("a typed placeholder becomes a chip",H("Report for {{client}}"),"<p>Report for <span class=\"rpt-ph\" data-token=\"client\">{{client}}</span></p>")
eq("placeholders stay literal in code",H("`{{client}}`"),"<p><code>{{client}}</code></p>")
eq("widget marker is a raw block",M("<div class=\"rpt-widget\" data-widget=\"findings_table\"></div>"),"```rpt-html\n<div class=\"rpt-widget\" data-widget=\"findings_table\"></div>\n```")
eq("a timestamp degrades to its text",M("<p><span class=\"note-ts\">[2026-11-23 10:12]</span> start</p>"),"\\[2026-11-23 10:12\\] start")
eq("ordered list keeps its start",M("<ol start=\"3\"><li>c</li><li>d</li></ol>"),"3. c\n4. d")
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
