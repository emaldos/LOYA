// Title bar on narrow windows (min width 460): the centred search must leave the absolute centre and join the flex row,
// or it covers the live-target badge and the bell (seen at 800 px on Linux, search 250-550 over badge 201-314 and bell 533).
const fs=require("fs")
const path=require("path")
const css=fs.readFileSync(path.join(__dirname,"..","..","UI","css","layout.css"),"utf8")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
function media(max){
const at=css.indexOf("@media (max-width:"+max+"px){")
if(at<0)return ""
let depth=0,i=css.indexOf("{",at)
for(let j=i;j<css.length;j++){if(css[j]==="{")depth++;else if(css[j]==="}"){depth--;if(depth===0)return css.slice(i+1,j)}}
return ""
}
check("wide windows keep the search centred",/\.titlebar-search\{position:absolute;left:50%/.test(css))
const narrow=media(1100)
check("a narrow-window rule exists for the title bar",/\.titlebar-search\{/.test(narrow))
check("narrow: search is in the flex row",/\.titlebar-search\{[^}]*position:static/.test(narrow)&&/\.titlebar-search\{[^}]*transform:none/.test(narrow))
check("narrow: search can shrink to its icon",/\.titlebar-search\{[^}]*flex:0 \d+ /.test(narrow)&&/\.titlebar-search\{[^}]*min-width:36px/.test(narrow))
check("narrow: the app name never wraps",/\.titlebar-title\{[^}]*white-space:nowrap/.test(narrow))
const tiny=media(640)
check("very narrow: name and version are hidden so the window controls fit",/\.titlebar-title,\.titlebar-version-badge\{display:none\}/.test(tiny))
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
