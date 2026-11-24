// Terminal right-click menu (UI/js/components/terminal-menu.js): which rows are built and enabled for a given state,
// CVE / URL detection on the selection, the one-line paste, ANSI stripping, text size steps and the viewport clamp.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const SOURCE=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal-menu.js"),"utf8")
const TERMINAL=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal.js"),"utf8")
const CSS=fs.readFileSync(path.join(ROOT,"UI","css","terminal.css"),"utf8")
const HTML=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8")
let passed=0,failed=0
function check(name,condition,detail){
if(condition){passed++;return}
failed++
console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))
}
const pure=SOURCE.slice(0,SOURCE.indexOf("// ---- DOM"))
const M=new Function(pure+";return{termCtxDetect,termCtxStripAnsi,termCtxOneLine,termCtxFontStep,termCtxClamp,termCtxSubmenuPos,termCtxBuildItems,termCtxNextIndex,TERM_CTX_FONT_DEFAULT,TERM_CTX_FONT_MIN,TERM_CTX_FONT_MAX}")()
const base={hasSession:true,dead:false,jobRunning:false,hasOutput:true,layout:"single",mode:"right",maximized:false,fontSize:12,closedCount:0,canNote:true,canCve:true,canSearch:true,canOpenUrl:true,canSplit:true}
function build(extra){return M.termCtxBuildItems(Object.assign({},base,extra||{}))}
function row(items,id){
for(const it of items){if(it.id===id)return it;if(it.submenu){const hit=row(it.submenu,id);if(hit)return hit}}
return null
}
function ids(items){return items.filter((it)=>!it.sep).map((it)=>it.id)}
// ---- selection state
const none=build({selection:""})
check("no selection: Copy is disabled",row(none,"copy").disabled===true)
check("no selection: Paste, Select all, Find, Clear stay enabled",["paste","paste_line","select_all","find","clear"].every((id)=>!row(none,id).disabled))
check("no selection: no selection actions",["note","search_loya","cve","open_url"].every((id)=>!row(none,id)))
check("no selection: Find is plain Find",row(none,"find").label==="Find")
const sel=build({selection:"uid=0(root) gid=0(root)"})
check("selection: Copy is enabled",row(sel,"copy").disabled===false)
check("selection: Send to note and Search in LOYA appear",!!row(sel,"note")&&!!row(sel,"search_loya"))
check("selection: plain text gives no CVE or URL row",!row(sel,"cve")&&!row(sel,"open_url"))
check("selection: single line offers Find selection",row(sel,"find").label==="Find selection")
check("selection: multi-line selection is plain Find",row(build({selection:"a\nb"}),"find").label==="Find")
check("whitespace-only selection counts as none",row(build({selection:"   \n "}),"copy").disabled===true)
check("Copy, Paste, Find show their shortcuts",row(none,"copy").key==="Ctrl+Shift+C"&&row(none,"paste").key==="Ctrl+Shift+V"&&row(none,"find").key==="Ctrl+F"&&row(none,"clear").key==="Ctrl+L")
// ---- CVE / URL
const cve=build({selection:" cve-2021-44228 "})
check("CVE selection: Look up row with the normalised id",row(cve,"cve")&&row(cve,"cve").value==="CVE-2021-44228"&&/CVE-2021-44228/.test(row(cve,"cve").label))
check("CVE inside a short line is found",M.termCtxDetect("Apache Log4j CVE-2021-44228 RCE").cve==="CVE-2021-44228")
check("CVE with a 7 digit sequence",M.termCtxDetect("CVE-2024-1234567").cve==="CVE-2024-1234567")
check("CVE needs 4+ digits",M.termCtxDetect("CVE-2021-123").cve==="")
check("not a CVE inside a longer token",M.termCtxDetect("XCVE-2021-44228").cve==="")
check("long selections are not scanned for CVEs",M.termCtxDetect("x".repeat(300)+" CVE-2021-44228").cve==="")
check("no CVE API: no CVE row",!row(build({selection:"CVE-2021-44228",canCve:false}),"cve"))
const url=build({selection:"https://example.com/a?b=1"})
check("URL selection: Open link row",row(url,"open_url")&&row(url,"open_url").value==="https://example.com/a?b=1")
check("URL trailing punctuation is trimmed",M.termCtxDetect("http://10.0.0.5:8080/login).").url==="http://10.0.0.5:8080/login")
check("non-web schemes are not links",M.termCtxDetect("file:///etc/passwd").url===""&&M.termCtxDetect("javascript:alert(1)").url==="")
check("text with spaces is not a link",M.termCtxDetect("see https://a.b now").url==="")
check("IOC under the pointer is used without a selection",!!row(build({selection:"",target:"https://203.0.113.5/x"}),"open_url"))
check("IOC target alone does not enable Copy or note",row(build({selection:"",target:"https://a.b"}),"copy").disabled&&!row(build({selection:"",target:"https://a.b"}),"note"))
// ---- session state
const dead=build({dead:true})
check("dead session: paste disabled",row(dead,"paste").disabled&&row(dead,"paste_line").disabled)
check("interrupt only while a job runs",row(none,"interrupt").disabled===true&&row(build({jobRunning:true}),"interrupt").disabled===false)
const empty=build({hasSession:false,hasOutput:false})
check("no session: Clear, Close, Rename, Duplicate disabled",["clear","close","rename","duplicate"].every((id)=>row(empty,id).disabled))
check("no output: Copy all and Select all disabled",row(empty,"copy_all").disabled&&row(empty,"select_all").disabled)
check("reopen needs a closed session",row(none,"reopen").disabled&&!row(build({closedCount:2}),"reopen").disabled)
check("single layout offers Split, split layout offers Single pane",!!row(none,"split")&&!row(none,"unsplit")&&!!row(build({layout:"cols2"}),"unsplit")&&!row(build({layout:"cols2"}),"split"))
check("submenus: Session, Text size, Panel position",["session","font","dock"].every((id)=>Array.isArray(row(none,id).submenu)))
check("Close session is marked danger",row(none,"close").danger===true)
// ---- font
check("text size label shows the size",row(build({fontSize:15}),"font").label==="Text size (15 px)")
check("text size buttons disable at the limits",row(build({fontSize:22}),"font_up").disabled&&row(build({fontSize:9}),"font_down").disabled&&row(none,"font_reset").disabled)
check("font steps clamp",M.termCtxFontStep(12,1)===13&&M.termCtxFontStep(22,1)===22&&M.termCtxFontStep(9,-1)===9&&M.termCtxFontStep("x",1)===13&&M.termCtxFontStep(17,0)===12)
// ---- dock
const dockRows=row(build({mode:"bottom"}),"dock").submenu
check("dock: right, left, bottom and maximize",ids(dockRows).join()==="dock_right,dock_left,dock_bottom,maximize")
check("dock: current mode is checked",dockRows.filter((it)=>it.checked).map((it)=>it.id).join()==="dock_bottom")
check("dock: maximize label follows state",row(build({maximized:true}),"maximize").label==="Restore panel")
// ---- text helpers
check("one line: lines joined with spaces, blanks dropped",M.termCtxOneLine("ls -la\r\n\n  cd /tmp  \nid\n")==="ls -la cd /tmp id")
check("strip ANSI: colours and cursor codes go",M.termCtxStripAnsi("\x1b[1;31mred\x1b[0m \x1b]0;title\x07ok\x1b[2K")==="red ok")
check("strip ANSI: carriage return redraws keep the last write",M.termCtxStripAnsi("10%\r50%\r100%\ndone\r\n")==="100%\ndone\n")
// ---- keyboard index
const rows=[{id:"a",disabled:true},{sep:true},{id:"b"},{id:"c",disabled:true},{id:"d"}]
check("next index skips disabled and separators",M.termCtxNextIndex(rows,-1,1)===2&&M.termCtxNextIndex(rows,2,1)===4&&M.termCtxNextIndex(rows,4,1)===2)
check("previous index from none starts at the end",M.termCtxNextIndex(rows,-1,-1)===4&&M.termCtxNextIndex(rows,2,-1)===4)
check("next index: nothing enabled gives -1",M.termCtxNextIndex([{id:"x",disabled:true},{sep:true}],-1,1)===-1)
// ---- clamp
const c1=M.termCtxClamp(100,100,240,400,1280,800,8)
check("clamp: fits as is",c1.left===100&&c1.top===100)
const c2=M.termCtxClamp(1200,100,240,400,1280,800,8)
check("clamp: flips left at the right edge",c2.left===960&&c2.left+240<=1272)
const c3=M.termCtxClamp(100,700,240,400,1280,800,8)
check("clamp: moves up at the bottom edge",c3.top===392&&c3.top+400<=792)
const c4=M.termCtxClamp(20,20,240,900,300,600,8)
check("clamp: taller than the window pins to the top margin",c4.top===8)
const c5=M.termCtxClamp(150,10,280,100,300,600,8)
check("clamp: no room on the right or left pins to the left margin",c5.left===8&&c5.left+280<=292)
const s1=M.termCtxSubmenuPos({top:200},{left:100,right:340},200,150,1280,800,8)
check("submenu opens to the right of its parent",s1.left===338&&s1.top===194)
const s2=M.termCtxSubmenuPos({top:200},{left:1000,right:1240},200,150,1280,800,8)
check("submenu flips to the left near the right edge",s2.left===802)
const s3=M.termCtxSubmenuPos({top:760},{left:100,right:340},200,150,1280,800,8)
check("submenu stays inside the bottom edge",s3.top+150<=792)
// ---- UI text and wiring
const labels=[]
;(function walk(items){items.forEach((it)=>{if(it.label)labels.push(it.label);if(it.submenu)walk(it.submenu)})})(build({selection:"CVE-2021-44228",layout:"cols2"}))
check("menu text: no em/en dashes, ellipsis characters or middle dots",labels.every((l)=>!/[\u2013\u2014\u2026\u00b7]/.test(l)),labels.join("|"))
check("source text: no em/en dashes, ellipsis characters or middle dots",!/[\u2013\u2014\u2026\u00b7]/.test(SOURCE))
check("Shift+right-click keeps the native menu",/function termCtxOnContextMenu\(e\)\{\nif\(e\.shiftKey\)return/.test(SOURCE))
check("native menu is only suppressed inside the terminal panes",/if\(!panes\|\|!panes\.contains\(e\.target\)\)return\n[^]*?e\.preventDefault\(\)/.test(SOURCE.slice(SOURCE.indexOf("function termCtxOnContextMenu")))&&!/document\.addEventListener\("contextmenu"/.test(SOURCE))
check("copy falls back to execCommand when the async clipboard is refused",/writeText\(value\)\.then\(done\)\.catch\(viaField\)/.test(SOURCE)&&/execCommand\("copy"\)/.test(SOURCE))
check("paste tries execCommand first on WebKitGTK",/engine-webkit[^]*?if\(webkit\)\{\nconst got=viaField\(\)/.test(SOURCE))
check("paste respects the multi-line confirm setting",/termState\.confirmMultilinePaste[^]*termConfirmMultilinePaste\(text\)/.test(SOURCE.slice(SOURCE.indexOf("function termCtxPaste"))))
check("Ctrl+Shift+V uses the same clipboard read as the menu",/function termPasteFromClipboard\(\)\{\n[^\n]*\nif\(typeof termCtxPaste==="function"\)\{termCtxPaste\(false\);return\}/.test(TERMINAL))
check("terminal.js wires the menu",/if\(typeof termCtxWire==="function"\)termCtxWire\(\)/.test(TERMINAL))
check("main.html loads terminal-menu.js after terminal.js",HTML.indexOf("components/terminal-menu.js")>HTML.indexOf("components/terminal.js\""))
check("output font size follows the variable",/\.terminal-output\{[^}]*font-size:var\(--term-font-size,12px\)/.test(CSS))
check("menu CSS uses theme tokens only",(()=>{const block=CSS.slice(CSS.indexOf(".term-ctx-menu"));return !/#[0-9a-f]{3,6}\b/i.test(block.replace(/rgba\([^)]*\)/g,""))})())
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
