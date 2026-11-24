// Title-bar live-target badge: picks the live target, masks secret-looking values, escapes names.
const B=require("../../UI/js/components/live-target-badge.js")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
check("picks the live target",B.liveBadgePick([{id:"a",status:"Not Used"},{id:"b",status:"live"}]).id==="b")
check("status match is case-insensitive",B.liveBadgePick([{id:"c",status:"LIVE"}]).id==="c")
check("no live target means null",B.liveBadgePick([{id:"a",status:"not_used"}])===null&&B.liveBadgePick([])===null&&B.liveBadgePick(null)===null)
for(const k of ["Password","api_key","NTLM_Hash","Session_Cookie","Token","Private_Key","OTP"])check("secret key masked: "+k,B.liveBadgeIsSecret(k))
for(const k of ["IPv4","Domain","URL","Port","Username","Wordlist"])check("normal key shown: "+k,!B.liveBadgeIsSecret(k))
check("names are escaped",B.liveBadgeEsc('<img src=x onerror="a()">')==="&lt;img src=x onerror=&quot;a()&quot;&gt;")
// Search in the details card: keys and plain values match, secret values never do (only their key name).
const V=[["IPv4","10.0.0.5"],["Domain","acme.local"],["Password","Summer2026!"],["Username","bob"]]
check("filter: empty query keeps all, with original indexes",JSON.stringify(B.liveBadgeFilter(V,"").map(x=>x.i))==="[0,1,2,3]")
check("filter: matches a key",B.liveBadgeFilter(V,"ipv").map(x=>x.pair[0]).join()==="IPv4")
check("filter: matches a plain value, case-insensitive",B.liveBadgeFilter(V,"ACME").map(x=>x.pair[0]).join()==="Domain")
check("filter: secret value is not searchable",B.liveBadgeFilter(V,"summer").length===0)
check("filter: secret key name is searchable",B.liveBadgeFilter(V,"pass").map(x=>x.i).join()==="2")
check("filter: keeps the original index for copy/reveal",B.liveBadgeFilter(V,"bob")[0].i===3)
// Native tooltip: GTK leaves it over the open card, so the badge has no title while the card is open.
{
const attrs={},cls=new Set(["hidden"])
const btn={dataset:{},title:"",getAttribute:(k)=>k==="title"?btn.title:attrs[k],setAttribute:(k,v)=>{if(k==="title")btn.title=v;else attrs[k]=v},removeAttribute:(k)=>{if(k==="title")btn.title="";else delete attrs[k]},classList:{toggle:(c,on)=>on?cls.add(c):cls.delete(c)}}
const name={textContent:""}
global.document={getElementById:(id)=>id==="titlebarLive"?btn:id==="titlebarLiveName"?name:null,removeEventListener(){}}
B.liveBadge.target={name:"web01"};B.liveBadge.profile="ACME"
B.liveBadgeRender()
check("closed badge has its tooltip",btn.title==="Live target: web01 (ACME) - click for details")
attrs["aria-expanded"]="true";btn.removeAttribute("title")
B.liveBadge.target={name:"web02"}
B.liveBadgeRender()
check("refresh while the card is open does not bring the tooltip back",btn.title===""&&name.textContent==="web02")
B.liveBadgeClose()
check("closing the card restores the current tooltip",btn.title==="Live target: web02 (ACME) - click for details"&&attrs["aria-expanded"]==="false")
const src=require("fs").readFileSync(require("path").join(__dirname,"..","..","UI","js","components","live-target-badge.js"),"utf8")
check("opening the card drops the title",/setAttribute\("aria-expanded","true"\)\nbtn\.removeAttribute\("title"\)/.test(src))
delete global.document
}
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
