// Every HTML-escape helper must escape quotes: their output is also used inside attributes (title, data-*, value),
// and a saved name like  " onmouseover="...  must never become a live handler with bridge access.
const fs=require("fs"),path=require("path")
const root=path.join(__dirname,"..","..")
const helpers=[["UI/js/components/toast.js","toastEscapeHtml"],["UI/js/pages/snippets.js","snipEscapeHtml"],["UI/js/components/ai.js","aiEscapeHtml"],["UI/js/pages/settings.js","setEscapeHtml"],["UI/js/pages/commands.js","cmdsEscapeHtml"],["UI/js/pages/chains.js","chainsEscapeHtml"],["UI/js/pages/notes.js","notesEscapeHtml"],["UI/js/components/terminal.js","termEscapeHtml"],["UI/js/pages/targets.js","tgtEscapeHtml"],["UI/js/components/palette.js","paletteEscapeHtml"],["UI/js/windows/mini.js","miniEscapeHtml"],["UI/js/components/card.js","dashEsc"]]
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
const payload=`" onmouseover="alert(1)" x='y' <img src=x onerror=1> & done`
for(const [file,fn] of helpers){
const src=fs.readFileSync(path.join(root,file),"utf8")
const m=new RegExp("function "+fn+"\\(s\\)\\{[\\s\\S]*?\\n\\}").exec(src)
if(!m){check(fn+" exists in "+file,false);continue}
const f=new Function(m[0]+";return "+fn)()
const out=f(payload)
check(fn+" escapes double quotes",!out.includes('"'),out)
check(fn+" escapes single quotes",!out.includes("'"),out)
check(fn+" escapes angle brackets",!/[<>]/.test(out),out)
check(fn+" escapes & once",out.includes("&amp; done")&&!out.includes("&amp;amp;"),out)
check(fn+" keeps 0",f(0)==="0",String(f(0)))
check(fn+" handles null",f(null)==="",String(f(null)))
}
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
