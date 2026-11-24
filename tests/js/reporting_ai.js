// Pure helpers of UI/js/pages/reporting_ai.js (no DOM): node tests/js/reporting_ai.js
const path=require("path")
const m=require(path.join(__dirname,"..","..","UI","js","pages","reporting_ai.js"))
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail!==undefined?" - "+JSON.stringify(detail):""))}}
function eq(name,actual,expected){check(name,JSON.stringify(actual)===JSON.stringify(expected),actual)}
// Markdown -> rich subset
eq("paragraphs and inline marks",m.mdToHtml("The **tester** found `id=7` injectable.\n\nSecond paragraph."),"<p>The <b>tester</b> found <code>id=7</code> injectable.</p><p>Second paragraph.</p>")
eq("bullet list",m.mdToHtml("- one\n- two"),"<ul><li>one</li><li>two</li></ul>")
eq("numbered list",m.mdToHtml("1. first\n2. second"),"<ol><li>first</li><li>second</li></ol>")
eq("headings are folded into h3/h4",m.mdToHtml("# A\n\n## B\n\n### C\n\n#### D\n\n###### E"),"<h3>A</h3><h3>B</h3><h3>C</h3><h4>D</h4><h4>E</h4>")
eq("empty input",[m.mdToHtml(""),m.mdToHtml(null),m.mdToHtml("   \n ")],["","",""])
// model output is untrusted
const evil=m.mdToHtml('Hello <script>alert(1)</script> <img src=x onerror=alert(2)> [x](javascript:alert(3)) <a href="javascript:alert(4)" onclick="x()">y</a>')
check("script tags never survive",!/<script/i.test(evil),evil)
check("no event handlers survive",!/<[^>]+\son\w+\s*=/i.test(evil),evil)
check("no img element is created from model text",!/<img/i.test(evil),evil)
check("no javascript: link survives",!/href\s*=\s*["']?\s*javascript:/i.test(evil),evil)
const fence=m.mdToHtml("Run:\n\n```bash\ncurl -s 'http://x/?a=<b>'\n```")
check("code fences become pre with escaped content",fence.indexOf("<pre>")>=0&&fence.indexOf("&lt;b&gt;")>=0&&fence.indexOf("<b>")<0,fence)
check("http links are kept",m.mdToHtml("[OWASP](https://owasp.org/)").indexOf('<a href="https://owasp.org/"')>=0)
// plain text for the evidence manager
eq("mdToPlain strips marks and keeps lists",m.mdToPlain("## Summary\n\nThe **tester** ran `nmap`.\n\n* port 22 open\n- port 80 open\n\n\n\nDone."),"Summary\n\nThe tester ran nmap.\n\n- port 22 open\n- port 80 open\n\nDone.")
eq("mdToPlain tolerates nothing",[m.mdToPlain(null),m.mdToPlain("")],["",""])
// results
const text=m.normalizeResult("exec_summary",{text:"One.\n\nTwo.",provider:"Ollama",model:"llama3.2"})
eq("text result",[text.text,text.html,text.vector,text.provider,text.model],["One.\n\nTwo.","<p>One.</p><p>Two.</p>","","Ollama","llama3.2"])
eq("an empty reply is no result",[m.normalizeResult("exec_summary",{text:"  "}),m.normalizeResult("rewrite_finding",null)],[null,null])
const ses=m.normalizeResult("summarise_session",{text:"The tester ran **nmap**.\n\n- 22/tcp open"})
eq("session summaries are plain text plus html",[ses.text,ses.html],["The tester ran nmap.\n\n- 22/tcp open","<p>The tester ran <b>nmap</b>.</p><ul><li>22/tcp open</li></ul>"])
const cv=m.normalizeResult("suggest_cvss",{vector:"AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",rationale:"- AV: reachable over the network"})
eq("cvss result is normalised and scored",[cv.vector,cv.score,cv.severity,cv.rationale],["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",9.8,"critical","- AV: reachable over the network"])
check("cvss rationale is offered as html too",cv.html==="<ul><li>AV: reachable over the network</li></ul>",cv.html)
eq("an invalid vector is no result",[m.normalizeResult("suggest_cvss",{vector:"CVSS:3.1/AV:X/AC:L"}),m.normalizeResult("suggest_cvss",{vector:"",rationale:"x"}),m.normalizeResult("suggest_cvss",{vector:"<script>"})],[null,null,null])
// labels
eq("character counts",[m.chars(0),m.chars(950),m.chars(1000),m.chars(12345)],["0 characters","950 characters","1k characters","12.3k characters"])
eq("local destination",m.destinationLine({provider:"Ollama",model:"llama3.2",destination:"127.0.0.1:11434",local:true}),{provider:"Ollama",model:"llama3.2",where:"On this machine (127.0.0.1:11434)",local:true})
eq("remote destination",m.destinationLine({provider:"Anthropic API",model:"",destination:"api.anthropic.com",local:false}),{provider:"Anthropic API",model:"the provider's default model",where:"Sent to api.anthropic.com",local:false})
eq("error text",[m.errMessage(new Error("No API key configured."),"x"),m.errMessage(new Error("bridge method missing: reportAI.preview"),"Not available."),m.errMessage(null,"Failed.")],["No API key configured.","Not available.","Failed."])
eq("every contract action has a title",["exec_summary","rewrite_finding","suggest_remediation","suggest_cvss","summarise_session"].every((a)=>!!m.TITLES[a]),true)
console.log("reporting_ai: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
