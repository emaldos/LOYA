// Update notice rendering: release notes come from the network, so the HTML must be escaped/sanitised and links must be inert
// except http(s)/mailto (opened in the system browser by the click handler, never by navigating the app window).
const M=require("../../UI/js/components/markdown.js")
const U=require("../../UI/js/components/update-notice.js")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
const notice={show:true,popup:true,version:"1.0.1",current_version:"1.0.0",title:"LOYA NG 1.0.1 is available",release_name:"Spring <b>fixes</b>",published_at:"2026-11-20T10:00:00Z",size:5*1024*1024,installable:true,staged:false,
notes:"## What's new\n- **Faster** search\n- [docs](https://github.com/emaldos/LOYA)\n- [bad](javascript:alert(1))\n- [note](notelink:abc)\n<img src=x onerror=alert(1)>\n<script>alert(1)</script>\n![pic](https://evil.example/p.png)"}
const html=U.updNoticeHtml(notice,M)
check("title is shown",html.includes("LOYA NG 1.0.1 is available"))
check("markdown rendered",/<b>Faster<\/b>/.test(html)&&/<h2[^>]*>What&#39;s new<\/h2>|<h2[^>]*>What's new<\/h2>/.test(html),html.slice(0,400))
check("raw html is escaped",!/<img/i.test(html)&&!/<script/i.test(html)&&html.includes("&lt;script&gt;"))
check("no event handler attributes",!/\son\w+=/i.test(html.replace(/&lt;[^&]*&gt;/g,"")))
check("javascript: link not rendered as a link",!/href="javascript:/i.test(html))
check("web link marked for the system browser",/href="https:\/\/github\.com\/emaldos\/LOYA" data-upd-link="1"/.test(html))
check("notelink is inert",!/href="notelink:/i.test(html)&&html.includes('data-upd-dead="1"'))
check("images are never loaded",!/<img/i.test(html)&&!/<[^>]*\ssrc=/i.test(html))
check("release name escaped",html.includes("Spring &lt;b&gt;fixes&lt;/b&gt;"))
check("buttons present",["update","later","skip","github"].every((a)=>html.includes('data-upd-act="'+a+'"')))
check("meta line",html.includes("You have 1.0.0")&&html.includes("Released 20 Nov 2026")&&html.includes("Download 5.0 MB"))
check("staged wording",U.updNoticeHtml(Object.assign({},notice,{staged:true}),M).includes("Restart and install"))
check("no package -> GitHub download",U.updNoticeHtml(Object.assign({},notice,{installable:false}),M).includes("Download from GitHub")&&!U.updNoticeHtml(Object.assign({},notice,{installable:false}),M).includes('data-upd-act="update"'))
check("empty notes message",U.updNotesHtml("",M).includes("No release notes"))
check("no markdown lib falls back to escaped pre",U.updNotesHtml("<b>x</b>",{}).startsWith("<pre>")&&U.updNotesHtml("<b>x</b>",{}).includes("&lt;b&gt;"))
check("size formatting",U.updFormatSize(0)===""&&U.updFormatSize(2048)==="2 KB"&&U.updFormatSize(3*1024*1024)==="3.0 MB")
check("bad date is blank",U.updFormatDate("nope")==="")
// once-per-session decisions
check("popup first",U.updDecide(notice,{},{})==="popup")
check("popup only once per version",U.updDecide(notice,{"1.0.1":true},{})==="bell")
check("bell only once",U.updDecide(notice,{"1.0.1":true},{"1.0.1":true})==="")
check("notify mode -> bell",U.updDecide(Object.assign({},notice,{popup:false}),{},{})==="bell")
check("nothing when hidden",U.updDecide(Object.assign({},notice,{show:false}),{},{})==="")
check("new version pops again",U.updDecide(Object.assign({},notice,{version:"1.0.2"}),{"1.0.1":true},{"1.0.1":true})==="popup")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
