const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const terminalSource=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal.js"),"utf8")
const snippetsSource=fs.readFileSync(path.join(ROOT,"UI","js","pages","snippets.js"),"utf8")
let passed=0
let failed=0
function check(name,condition,detail){
if(condition){passed++;return}
failed++
console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))
}
function slice(source,from,to){
const start=source.indexOf(from)
const end=source.indexOf(to)
if(start<0||end<0||end<start)throw new Error("could not slice "+from)
return source.slice(start,end)
}
function escapeHtml(value){
return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")
}
function styleMap(html){
const out=[]
const stack=[]
const pattern=/<span class="([^"]*)"[^>]*>|<\/span>|[^<]+/g
let match
while((match=pattern.exec(html))!==null){
if(match[0].startsWith("</span"))stack.pop()
else if(match[0].startsWith("<span"))stack.push(match[1])
else{
const classes=stack.join(" ").split(/\s+/).filter(Boolean).sort().join(" ")
const text=match[0].replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"')
for(const character of text)out.push(character+"\u0000"+classes)
}
}
return out.join("\n")
}
const ansiState={searchQuery:"",searchMatches:[],searchIndex:0,jobBlocks:false,renderedTabId:null}
const renderModule=new Function("termEscapeHtml","termState","termBuildListingWidgetHtml","termExitLabel",
slice(terminalSource,"const TERM_ANSI_SGR_RE","function termHumanSize")+
slice(terminalSource,"const TERM_MAX_UNCOMMITTED","function termUpdateLiveEcho")+
slice(terminalSource,"function termJobBlockState","function termFullRenderOutput")+
slice(terminalSource,"function termFullRenderOutput","function termRenderActiveOutput")+
";return{termAnsiRenderChunk,termCommitBoundary,termFullRenderOutput,termAppendRenderOutput,termScanIocs,TERM_MAX_UNCOMMITTED}")
(escapeHtml,ansiState,()=>"",code=>code===0?"exit 0":"exit "+code)
function node(){
return {_html:"",set innerHTML(value){this._html=value},get innerHTML(){return this._html},insertAdjacentHTML(position,html){this._html+=html}}
}
function newTab(buffer){
return {sessionId:"t",buffer:buffer||"",listings:[],jobHistory:[],renderVersion:0,renderedVersion:-1,renderedLen:0,ansiClasses:[]}
}
const ESC="\u001b"
const stream=`plain ${ESC}[31mRED bold${ESC}[1m more\nline2 10.0.0.5 tail\nhttp://a.b/c ${ESC}[0mdone\npartial-no-newline`
const reference=(()=>{
const tab=newTab(stream)
const nodes={committed:node(),tail:node()}
renderModule.termFullRenderOutput(nodes,tab)
return styleMap(nodes.committed._html+nodes.tail._html)
})()
let divergences=0
for(let trial=0;trial<300;trial++){
const tab=newTab("")
const nodes={committed:node(),tail:node()}
let position=0
while(position<stream.length){
const step=1+Math.floor(Math.random()*6)
tab.buffer=stream.slice(0,position+step)
renderModule.termAppendRenderOutput(nodes,tab)
position+=step
}
if(styleMap(nodes.committed._html+nodes.tail._html)!==reference)divergences++
}
check("incremental render matches full render across 300 random chunk splits",divergences===0,divergences+" diverged")
const guardTab=newTab("y".repeat(renderModule.TERM_MAX_UNCOMMITTED+200))
renderModule.termAppendRenderOutput({committed:node(),tail:node()},guardTab)
check("newline-free stream force-commits at the guard",guardTab.renderedLen===guardTab.buffer.length)
function renderToHtml(buffer){
const tab=newTab(buffer)
const nodes={committed:node(),tail:node()}
renderModule.termFullRenderOutput(nodes,tab)
return nodes.committed._html+nodes.tail._html
}
const charsetHtml=renderToHtml(`${ESC}(Bplain ${ESC}(0alt${ESC})0 ${ESC}*B${ESC}+A tail\n`)
check("charset designators are consumed, not printed",!/\(B|\(0|\)0|\*B|\+A/.test(charsetHtml),charsetHtml)
check("text around charset designators survives",/plain/.test(charsetHtml)&&/alt/.test(charsetHtml)&&/tail/.test(charsetHtml),charsetHtml)
check("a bare ESC(B leaves no stray glyph",renderToHtml(`${ESC}(Brow\n`).indexOf(ESC)===-1)
const ncursesHtml=renderToHtml(`${ESC}(B${ESC}[m${ESC}[39;49m${ESC}(B${ESC}[m  4869 user  0:16.30 claude\n`)
check("a top-style ncurses line renders clean",!/\(B/.test(ncursesHtml)&&/4869 user/.test(ncursesHtml),ncursesHtml)
const charsetColourHtml=renderToHtml(`${ESC}(B${ESC}[31mred${ESC}[0m done\n`)
check("colour still applies after a charset designator",/<span class="[^"]+"[^>]*>red/.test(charsetColourHtml)&&!/\(B/.test(charsetColourHtml),charsetColourHtml)
const zshFirstPrompt=" ".repeat(80)+`\r\r${ESC}]0;user@kali\x07\r${ESC}[0m${ESC}[J${ESC}[32m in-(user@kali)-[~/x]\r\n`
const zshHtml=renderToHtml(zshFirstPrompt)
check("the zsh startup end-of-line pad is overwritten, not kept",!/^\s{10,}/.test(zshHtml.replace(/<[^>]*>/g,"")),JSON.stringify(zshHtml.replace(/<[^>]*>/g,"").slice(0,40)))
check("the prompt itself survives the carriage return",/in-\(user@kali\)-\[~\/x\]/.test(zshHtml),zshHtml)
check("a progress line keeps only the final update",renderToHtml("10%\r50%\r100% done\n").replace(/<[^>]*>/g,"").trim()==="100% done")
const crlfHtml=renderToHtml("first\r\nsecond\r\n").replace(/<[^>]*>/g,"")
check("CRLF is a line break, not an overwrite",/first/.test(crlfHtml)&&/second/.test(crlfHtml),JSON.stringify(crlfHtml))
const crColourHtml=renderToHtml(`${ESC}[31mERROR\rOK\n`)
check("colour set before a carriage return still applies after it",/<span class="[^"]+"[^>]*>OK/.test(crColourHtml)&&!/ERROR/.test(crColourHtml),crColourHtml)
const crStream="alpha\r\nbeta"+" ".repeat(30)+"\rgamma\r\ndelta\n"
const crReference=(()=>{const t=newTab(crStream);const n={committed:node(),tail:node()};renderModule.termFullRenderOutput(n,t);return styleMap(n.committed._html+n.tail._html)})()
let crDivergences=0
for(let trial=0;trial<150;trial++){
const t=newTab("")
const n={committed:node(),tail:node()}
let position=0
while(position<crStream.length){
const step=1+Math.floor(Math.random()*5)
t.buffer=crStream.slice(0,position+step)
renderModule.termAppendRenderOutput(n,t)
position+=step
}
if(styleMap(n.committed._html+n.tail._html)!==crReference)crDivergences++
}
check("carriage-return output renders the same incrementally as in full",crDivergences===0,crDivergences+" diverged")
const newlineModule=new Function(slice(terminalSource,"function termShellFamily","function termJobEpilogue")+";return{termSubmitNewline,termShellFamily}")()
check("posix shells submit with a bare LF",newlineModule.termSubmitNewline("shell")==="\n","a CR would be translated to a second newline by ICRNL and run an empty command")
check("an unknown shell id is treated as posix",newlineModule.termSubmitNewline(null)==="\n")
check("wsl distros submit with a bare LF too",newlineModule.termSubmitNewline("wsl:Ubuntu")==="\n")
check("cmd still submits with CRLF",newlineModule.termSubmitNewline("cmd")==="\r\n")
check("powershell still submits with CRLF",newlineModule.termSubmitNewline("powershell")==="\r\n"&&newlineModule.termSubmitNewline("pwsh")==="\r\n")
const redrawModule=new Function(slice(terminalSource,"const TERM_ANSI_SGR_RE","function termHumanSize")+";return{termApplyRedraw}")()
const zshPrompt=`${ESC}[32m in-(user@kali)-[~/x]\r\n${ESC}[34m$${ESC}[39m `
const zshRedraw=`\r\r${ESC}[A${ESC}[0m${ESC}[27m${ESC}[24m${ESC}[J`
const redrawn=redrawModule.termApplyRedraw("earlier output\n"+zshPrompt+zshRedraw+zshPrompt)
check("a zsh prompt redraw replaces the old prompt instead of appending",(redrawn.match(/in-\(user@kali\)/g)||[]).length===1,JSON.stringify(redrawn))
check("output above the redrawn prompt is preserved",/earlier output/.test(redrawn),JSON.stringify(redrawn))
check("the redraw escape itself is consumed",!/\[A/.test(redrawn)&&!/\[J/.test(redrawn),JSON.stringify(redrawn))
const multiUp=redrawModule.termApplyRedraw("keep\nl1\nl2\nl3\ntail"+`\r${ESC}[3A${ESC}[J`+"new")
check("cursor-up with a count erases that many lines",multiUp==="keep\nnew",JSON.stringify(multiUp))
check("text with no redraw sequence is returned untouched",redrawModule.termApplyRedraw("plain\nlines\n")==="plain\nlines\n")
check("a redraw at the very start does not underflow",redrawModule.termApplyRedraw(`only${ESC}[A${ESC}[J`+"x")==="x",JSON.stringify(redrawModule.termApplyRedraw(`only${ESC}[A${ESC}[J`+"x")))
const markerModule=new Function(slice(terminalSource,"const TERM_JOB_TOKEN","function termExitLabel")+";return{termJobEpilogue,termExtractJobResults,termStripJobMarkers,termStripPartialMarker,termPendingVisible}")()
for(const shell of ["cmd","powershell","shell"]){
const epilogue=markerModule.termJobEpilogue(shell,"jabc12345")
const raw="prompt> ls"+epilogue+"\nreal output\n__LOYA_JOB__jabc12345|7|/some/path__END__\n"
const results=markerModule.termExtractJobResults(raw)
const visible=markerModule.termStripJobMarkers(raw,shell)
check(shell+": marker yields one result with exit code and cwd",results.length===1&&results[0].exitCode===7&&results[0].cwd==="/some/path")
check(shell+": marker and echoed epilogue removed from view",!visible.includes("__LOYA_JOB__")&&!visible.includes("__END__")&&visible.includes("real output"))
check(shell+": echoed epilogue alone is never read as a result",markerModule.termExtractJobResults("cmd"+epilogue+"\n").length===0)
let leaks=0
for(let index=0;index<=epilogue.length;index++){
if(markerModule.termStripPartialMarker("cmdX"+epilogue.slice(0,index),shell)!=="cmdX")leaks++
}
check(shell+": no partial epilogue state leaks while streaming",leaks===0,leaks+" of "+(epilogue.length+1))
}
check("prompt keeps its trailing space when no job is in flight",markerModule.termPendingVisible({pendingRaw:"\u2514\u2500$ ",shellId:"zsh",activeJob:null})==="\u2514\u2500$ ")
check("a partial marker is still hidden while a job is in flight",markerModule.termPendingVisible({pendingRaw:"nmap -sV x ;pri",shellId:"zsh",activeJob:{jobId:"j1"}})==="nmap -sV x")
check("a complete marker is hidden with no job in flight",!markerModule.termPendingVisible({pendingRaw:"out\n"+markerModule.termJobEpilogue("zsh","j2"),shellId:"zsh",activeJob:null}).includes("__LOYA_JOB__"))
const iocCases=[["https://a.example.com/x","url"],["10.0.0.0/24","cidr"],["10.0.0.5:8080","hostport"],["10.0.0.5","ip"],["fe80::1ff:fe23:4567:890a","ipv6"],["2001:db8::1","ipv6"],["00:1A:2B:3C:4D:5E","mac"],["aa-bb-cc-dd-ee-ff","mac"],["CVE-2021-44228","cve"],["d41d8cd98f00b204e9800998ecf8427e","md5"],["da39a3ee5e6b4b0d3255bfef95601890afd80709","sha1"],["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","sha256"],["root@target.local","email"],["intranet.htb","domain"],["\\\\SRV01\\C$","unc"]]
for(const [text,kind] of iocCases){
const hits=renderModule.termScanIocs(text)
check("ioc "+kind+" detected for "+JSON.stringify(text).slice(0,30),hits.length===1&&hits[0].kind===kind&&hits[0].value===text,JSON.stringify(hits))
}
const mixed="iface fe80::1ff:fe23:4567:890a mac 00:1A:2B:3C:4D:5E ip 10.0.0.5:445 host db.internal"
const mixedHits=renderModule.termScanIocs(mixed)
let overlapping=false
for(let index=1;index<mixedHits.length;index++)if(mixedHits[index].start<mixedHits[index-1].end)overlapping=true
check("ioc matches never overlap on a mixed line",!overlapping)
check("mac is not claimed by the ipv6 rule",renderModule.termScanIocs("00:1A:2B:3C:4D:5E")[0].kind==="mac")
check("plain prose yields no indicators",renderModule.termScanIocs("hello world timeout 30").length===0)
check("version strings are not addresses",renderModule.termScanIocs("v1.2.3").length===0)
const riskState={activeId:null,snippetRunConfirm:"risky"}
const riskModule=new Function("termFindTab","termState",
slice(snippetsSource,"function snipIterPlaceholders","function snipResolveCommand")+
slice(terminalSource,"const TERM_DESTRUCTIVE_RULES","function termRunConfirmHtml")+
";return{termCommandRisks,termUnresolvedPlaceholders}")(()=>null,riskState)
const riskCases=[["rm -rf /var/tmp/x",true],["dd if=/dev/zero of=/dev/sda",true],["mkfs.ext4 /dev/sdb1",true],["curl https://x.sh | sh",true],["iwr https://a/b.ps1 | iex",true],["chmod 777 /srv",true],["shutdown /r /t 0",true],["sudo apt update",true],["nmap -sV {TARGET}",true],["nmap -sV 10.0.0.1",false],["ls -la",false],["echo ${HOME}",false],["git rm --cached f",false],["docker run -it img sh",false]]
for(const [command,risky] of riskCases){
const risks=riskModule.termCommandRisks(command,{})
check("risk "+(risky?"flagged":"clear")+": "+command,(risks.length>0)===risky,JSON.stringify(risks))
}
check("destructive noise level alone is risky",riskModule.termCommandRisks("echo safe",{noise_level:"destructive"}).length===1)
check("shell expansion is not an unresolved placeholder",riskModule.termUnresolvedPlaceholders("echo ${HOME}").length===0)
check("real placeholder is detected",riskModule.termUnresolvedPlaceholders("nmap {TARGET}").length===1)
const fanoutModule=new Function(slice(snippetsSource,"function snipIterPlaceholders","function snipResolveCommand")+slice(terminalSource,"function termResolveForTarget","function termFanoutRowsHtml")+";return{termResolveForTarget}")()
const target={id:"t1",name:"web",values:{IP:"10.0.0.5",PORT:"443"}}
const lowercase={id:"t2",name:"web2",values:{ip:"10.0.0.6",PORT:""}}
check("fan-out resolves per target",fanoutModule.termResolveForTarget("nmap -p {PORT} {IP}",target)==="nmap -p 443 10.0.0.5")
check("fan-out matches keys case-insensitively",fanoutModule.termResolveForTarget("ping {IP}",lowercase)==="ping 10.0.0.6")
check("fan-out leaves empty values as placeholders",fanoutModule.termResolveForTarget("p {PORT}",lowercase)==="p {PORT}")
check("fan-out leaves shell expansion alone",fanoutModule.termResolveForTarget("echo ${HOME} {IP}",target)==="echo ${HOME} 10.0.0.5")
const tabState={tabs:[{sessionId:"a"},{sessionId:"b"},{sessionId:"c"}],activeId:"a"}
const activated=[]
const tabModule=new Function("termState","termRenderTabs","termActivateTab",
slice(terminalSource,"function termTabIndex","function termStartTabRename")+
slice(terminalSource,"function termMoveTab","function termRenderTabs")+
";return{termMoveTab,termCycleTab,termActivateTabIndex}")(tabState,()=>{},id=>{tabState.activeId=id;activated.push(id)})
tabModule.termMoveTab("a","c")
check("tab reorder moves the dragged tab",tabState.tabs.map(t=>t.sessionId).join(",")==="b,c,a")
tabModule.termMoveTab("zz","a")
check("tab reorder ignores unknown ids",tabState.tabs.map(t=>t.sessionId).join(",")==="b,c,a")
tabState.activeId="b"
tabModule.termCycleTab(1);tabModule.termCycleTab(1);tabModule.termCycleTab(1)
check("tab cycling wraps around",activated.join(",")==="c,a,b")
activated.length=0
tabModule.termActivateTabIndex(99)
check("out of range tab index is ignored",activated.length===0)
const parserModule=new Function(slice(terminalSource,"const TERM_TABLE_KINDS","function termParseListing")+slice(terminalSource,"function termDetectListingCommand","const TERM_LS_LONG_RE")+";return{termParseNmap,termParseProcesses,termParseConnections,termDetectListingCommand,TERM_TABLE_KINDS}")()
const nmapOutput=[
"PORT     STATE    SERVICE     VERSION",
"22/tcp   open     ssh         OpenSSH 8.2p1 Ubuntu 4ubuntu0.5",
"80/tcp   open     http        Apache httpd 2.4.41",
"443/tcp  closed   https",
"3306/tcp filtered mysql",
].join("\n")
const nmapRows=parserModule.termParseNmap(nmapOutput)
check("nmap parser finds every port line",nmapRows&&nmapRows.length===4,JSON.stringify(nmapRows))
check("nmap parser keeps version text intact",nmapRows[0].version==="OpenSSH 8.2p1 Ubuntu 4ubuntu0.5")
check("nmap parser records closed and filtered states",nmapRows[2].state==="closed"&&nmapRows[3].state==="filtered")
check("nmap parser tolerates a missing version",nmapRows[2].version==="")
const tasklistOutput=[
"Image Name                     PID Session Name        Session#    Mem Usage",
"svchost.exe                   1234 Services                   0     24,512 K",
"chrome.exe                    5678 Console                    1    312,004 K",
].join("\n")
const tasklistRows=parserModule.termParseProcesses(tasklistOutput)
check("tasklist parser reads pid, name and memory",tasklistRows&&tasklistRows.length===2&&tasklistRows[0].pid==="1234"&&tasklistRows[0].name==="svchost.exe"&&tasklistRows[0].memory==="24,512 K")
const psOutput=[
"USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND",
"root         1  0.0  0.1 168944 11876 ?        Ss   09:12   0:02 /sbin/init",
"www-data  2451  0.3  1.2 214512 98123 ?        S    09:20   0:15 nginx",
].join("\n")
const psRows=parserModule.termParseProcesses(psOutput)
check("ps parser reads pid and user",psRows&&psRows.length===2&&psRows[0].pid==="1"&&psRows[1].user==="www-data")
const netstatOutput=[
"  Proto  Local Address          Foreign Address        State           PID",
"  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1044",
"  TCP    10.0.0.5:52341         52.109.8.20:443        ESTABLISHED     8820",
].join("\n")
const netstatRows=parserModule.termParseConnections(netstatOutput)
check("netstat parser reads proto, addresses, state and pid",netstatRows&&netstatRows.length===2&&netstatRows[0].state==="LISTENING"&&netstatRows[1].pid==="8820")
const ssOutput=[
"Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port",
"tcp   LISTEN 0      128    0.0.0.0:22          0.0.0.0:*",
"tcp   ESTAB  0      0      10.0.0.5:52341      52.109.8.20:443",
].join("\n")
const ssRows=parserModule.termParseConnections(ssOutput)
check("ss parser is used when netstat shape does not match",ssRows&&ssRows.length===2&&ssRows[0].state==="LISTEN")
check("parsers return null on unrelated text",parserModule.termParseNmap("hello")===null&&parserModule.termParseProcesses("hello")===null&&parserModule.termParseConnections("hello")===null)
const detectionCases=[["nmap -sV h","nmap"],["sudo nmap -p- h","nmap"],["doas nmap h","nmap"],["/usr/bin/nmap h","nmap"],["sudo netstat -ano","connection"],["ss -tulpn","connection"],["sudo tasklist","process"],["ps aux","process"],["ls -la","ls"],["sudo ls -la","ls"],["dir","dir"],["pslist","none"],["echo nmap","none"]]
for(const [command,kind] of detectionCases){
const detected=parserModule.termDetectListingCommand(command,"cmd")
check("detect "+JSON.stringify(command)+" as "+kind,((detected||{}).kind||"none")===kind,JSON.stringify(detected))
}
check("every table kind declares columns",Object.keys(parserModule.TERM_TABLE_KINDS).every((key)=>parserModule.TERM_TABLE_KINDS[key].columns.length>0))
const searchState={searchQuery:"",searchRegex:false,searchMatches:[],searchIndex:0}
const searchModule=new Function("termState","termFindTab",slice(terminalSource,"function termSearchRegex","function termUpdateSearchStatus")+";return{termSearchRegex,termSearchMatches,termFilterLines}")(searchState,()=>null)
const searchTab={buffer:"open 22/tcp ssh\nopen 80/tcp http\nclosed 23/tcp telnet\n"}
searchState.searchQuery="open";searchState.searchRegex=false
check("literal search finds every match",searchModule.termSearchMatches(searchTab).length===2)
searchState.searchQuery="22/tcp"
check("literal search treats punctuation literally",searchModule.termSearchMatches(searchTab).length===1)
searchState.searchQuery="a.b"
check("literal search does not treat a dot as a wildcard",searchModule.termSearchMatches(searchTab).length===0)
searchState.searchQuery=String.raw`open \d+`;searchState.searchRegex=true
check("regex search honours escapes",searchModule.termSearchMatches(searchTab).length===2)
searchState.searchQuery="[unclosed"
check("invalid regex reports no pattern instead of throwing",searchModule.termSearchRegex()===null)
searchState.searchQuery="a*";searchState.searchRegex=true
check("zero-width regex terminates",searchModule.termSearchMatches({buffer:"aaaa"}).length>0)
searchState.searchQuery="open";searchState.searchRegex=false
check("filter keeps only matching lines",searchModule.termFilterLines(searchTab).split("\n").length===2)
const resizeSource=fs.readFileSync(path.join(ROOT,"UI","js","components","side-panel-resize.js"),"utf8")
function fakeElement(){
return {style:{},title:"",className:"",focus(){},_classes:new Set(),classList:{
add(name){this.owner._classes.add(name)},
remove(name){this.owner._classes.delete(name)},
contains(name){return this.owner._classes.has(name)},
toggle(name,on){if(on)this.owner._classes.add(name);else this.owner._classes.delete(name)}},
box:{width:0,height:0},getBoundingClientRect(){return {left:0,bottom:0,width:this.box.width,height:this.box.height}}}
}
function fakeDom(ids){
const nodes={}
ids.forEach((id)=>{const el=fakeElement();el.classList.owner=el;nodes[id]=el})
return {nodes,document:{getElementById:(id)=>nodes[id]||null}}
}
const layoutIds=["workArea","terminalPanel","terminalMaximizeIcon","terminalMaximizeBtn","terminalInput"]
const layoutDom=fakeDom(layoutIds)
const layoutState={mode:"right",maximized:false,open:true,width:380,height:320,followOutput:false}
const layoutSaves=[]
const layoutMenus=[]
const panelDock=require("../../UI/js/components/panel-dock.js")
const layoutModule=new Function("document","termState","bridgeCall","termScrollToBottom","openContextMenu","termScheduleSizeSync","panelDockClampSize","panelDockNormalizeMode","panelDockOverflow",
slice(terminalSource,"function termSaveLayout","function termApplyRunBehaviour")+
";return{termApplyLayout,termSetDockMode,termToggleMaximize,termOpenLayoutMenu,termHeadOverflowPlan}")
(layoutDom.document,layoutState,(name,args)=>{layoutSaves.push([name,args[0]]);return {catch(){}}},()=>{},(items)=>layoutMenus.push(items),()=>{},panelDock.panelDockClampSize,panelDock.panelDockNormalizeMode,panelDock.panelDockOverflow)
const area=layoutDom.nodes.workArea
const panel=layoutDom.nodes.terminalPanel
layoutModule.termApplyLayout()
check("right dock sets no dock class",!area.classList.contains("dock-left")&&!area.classList.contains("dock-bottom"))
check("right dock sizes by width",panel.style.width==="380px"&&panel.style.height==="")
layoutModule.termSetDockMode("left")
check("left dock sets dock-left",area.classList.contains("dock-left")&&!area.classList.contains("dock-bottom"))
check("left dock still sizes by width",panel.style.width==="380px"&&panel.style.height==="")
layoutModule.termSetDockMode("bottom")
check("bottom dock swaps the dock class",area.classList.contains("dock-bottom")&&!area.classList.contains("dock-left"))
check("bottom dock sizes by height and clears width",panel.style.height==="320px"&&panel.style.width==="")
check("dock changes persist",layoutSaves.filter(([name])=>name==="terminal.set_panel_layout").length===2)
layoutModule.termSetDockMode("bottom")
check("re-selecting the current mode does not persist again",layoutSaves.length===2)
layoutModule.termToggleMaximize()
check("maximize sets the class",area.classList.contains("maximized"))
layoutState.open=false
layoutModule.termApplyLayout()
check("a closed panel never marks the work area maximized",!area.classList.contains("maximized"),"otherwise the page is hidden behind a panel that is not there, and the app looks blank")
layoutState.open=true
layoutModule.termApplyLayout()
check("reopening the panel restores the maximized class",area.classList.contains("maximized"))
check("maximize clears both inline sizes so the stylesheet wins",panel.style.width===""&&panel.style.height==="")
check("maximize swaps the icon to restore",layoutDom.nodes.terminalMaximizeIcon.className==="icon icon-restore")
check("maximize persists",layoutSaves[layoutSaves.length-1][1].maximized===true)
layoutModule.termToggleMaximize()
check("restore drops the class",!area.classList.contains("maximized"))
check("restore reapplies the bottom dock height",panel.style.height==="320px"&&panel.style.width==="")
check("restore swaps the icon back",layoutDom.nodes.terminalMaximizeIcon.className==="icon icon-maximize")
layoutModule.termSetDockMode("right")
check("returning to right dock restores the width",panel.style.width==="380px"&&panel.style.height==="")
layoutModule.termOpenLayoutMenu(layoutDom.nodes.terminalMaximizeBtn)
const menu=layoutMenus[layoutMenus.length-1]
check("layout menu offers all three docks plus maximize",menu.filter((it)=>!it.sep&&!it.disabled).length===4)
check("layout menu ticks the active dock",menu[0].label.indexOf("\u2713")>=0&&menu[1].label.indexOf("\u2713")<0)
function fakeWindow(){
const handlers={}
return {addEventListener(name,fn){(handlers[name]=handlers[name]||[]).push(fn)},fire(name,event){(handlers[name]||[]).forEach((fn)=>fn(event))},innerHeight:900}
}
function dragPanel(mode,startBox,move){
const handle=fakeElement();handle.classList.owner=handle
const target=fakeElement();target.classList.owner=target
target.box={width:startBox.width,height:startBox.height}
const win=fakeWindow()
const handleEvents={}
handle.addEventListener=(name,fn)=>{handleEvents[name]=fn}
const committed=[]
const module=new Function("window","initSidePanelResize",resizeSource+";return initSidePanelResize")(win)
module({handle,panel:target,config:()=>{
if(mode==="bottom")return {axis:"y",anchorSide:"bottom",min:160,max:700}
return {axis:"x",anchorSide:mode==="left"?"left":"right",min:260,max:900}
},onCommit:(size,axis)=>committed.push([size,axis])})
handleEvents.mousedown({screenX:500,screenY:500,preventDefault(){}})
win.fire("mousemove",{screenX:500+(move.dx||0),screenY:500+(move.dy||0)})
const applied=mode==="bottom"?target.style.height:target.style.width
target.box={width:parseInt(target.style.width||startBox.width,10),height:parseInt(target.style.height||startBox.height,10)}
win.fire("mouseup",{})
return {applied,committed}
}
check("right dock grows when dragged left",dragPanel("right",{width:380,height:320},{dx:-100}).applied==="480px")
check("right dock shrinks when dragged right",dragPanel("right",{width:380,height:320},{dx:100}).applied==="280px")
check("left dock grows when dragged right",dragPanel("left",{width:380,height:320},{dx:100}).applied==="480px")
check("left dock shrinks when dragged left",dragPanel("left",{width:380,height:320},{dx:-100}).applied==="280px")
check("bottom dock grows when dragged up",dragPanel("bottom",{width:380,height:320},{dy:-100}).applied==="420px")
check("bottom dock shrinks when dragged down",dragPanel("bottom",{width:380,height:320},{dy:100}).applied==="220px")
check("horizontal drag clamps to the minimum",dragPanel("right",{width:380,height:320},{dx:9999}).applied==="260px")
check("horizontal drag clamps to the maximum",dragPanel("right",{width:380,height:320},{dx:-9999}).applied==="900px")
check("vertical drag clamps to the minimum",dragPanel("bottom",{width:380,height:320},{dy:9999}).applied==="160px")
check("vertical drag clamps to the maximum",dragPanel("bottom",{width:380,height:320},{dy:-9999}).applied==="700px")
const verticalDrag=dragPanel("bottom",{width:380,height:320},{dy:-100})
check("vertical drag commits the y axis",verticalDrag.committed[0][1]==="y"&&verticalDrag.committed[0][0]===420)
const horizontalDrag=dragPanel("right",{width:380,height:320},{dx:-100})
check("horizontal drag commits the x axis",horizontalDrag.committed[0][1]==="x"&&horizontalDrag.committed[0][0]===480)
const chainState={jobs:[],chainsFolded:{}}
const chainModule=new Function("termState","termEscapeHtml","termJobRowHtml",
slice(terminalSource,"function termChainSteps","function termFilteredJobs")+
";return{termChainSteps,termChainProgress,termGroupJobRows,termChainGroupHtml}")
(chainState,escapeHtml,(job)=>'<row job="'+job.job_key+'">')
function step(key,position,state,extra){
return Object.assign({job_key:key,chain_id:"chainA",chain_pos:position,state:state,label:"Playbook",source:"playbook"},extra||{})
}
function plain(key,state){
return {job_key:key,chain_id:null,chain_pos:null,state:state||"done",label:"solo",source:"terminal"}
}
chainState.jobs=[step("c3",2,"pending"),step("c2",1,"running"),step("c1",0,"done"),plain("p1")]
check("chain steps come back in run order",chainModule.termChainSteps("chainA").map((s)=>s.job_key).join(",")==="c1,c2,c3")
let progress=chainModule.termChainProgress("chainA")
check("progress counts only settled steps",progress.settled===1&&progress.total===3)
check("a chain with a running step is active",progress.active===true)
check("progress reports no failures yet",progress.failed===0&&progress.skipped===0)
let grouped=chainModule.termGroupJobRows(chainState.jobs)
check("a chain collapses to one entry",grouped.filter((e)=>e.kind==="chain").length===1)
check("plain jobs stay separate",grouped.filter((e)=>e.kind==="job").length===1)
check("the chain keeps the position of its newest step",grouped[0].kind==="chain")
check("grouped chain steps are sorted by position",grouped[0].steps.map((s)=>s.job_key).join(",")==="c1,c2,c3")
let html=chainModule.termChainGroupHtml("chainA",grouped[0].steps)
check("an active chain is marked running",html.indexOf('terminal-chain-head running')>=0)
check("an active chain offers cancel",html.indexOf('data-chain-action="cancel"')>=0)
check("progress renders as a percentage width",html.indexOf('width:33%')>=0)
check("every step renders inside the group",html.indexOf('job="c1"')>=0&&html.indexOf('job="c3"')>=0)
check("an unfolded chain has no folded class",html.indexOf("terminal-chain-group folded")<0)
chainState.chainsFolded.chainA=true
check("a folded chain carries the folded class",chainModule.termChainGroupHtml("chainA",grouped[0].steps).indexOf("terminal-chain-group folded")>=0)
delete chainState.chainsFolded.chainA
chainState.jobs=[step("c3",2,"skipped"),step("c2",1,"failed"),step("c1",0,"done")]
progress=chainModule.termChainProgress("chainA")
check("a stopped chain is not active",progress.active===false)
check("a stopped chain counts the failure and the skip",progress.failed===1&&progress.skipped===1)
html=chainModule.termChainGroupHtml("chainA",chainModule.termChainSteps("chainA"))
check("a chain with a failure is marked failed",html.indexOf("terminal-chain-head failed")>=0)
check("a finished chain offers dismiss instead of cancel",html.indexOf('data-chain-action="dismiss"')>=0&&html.indexOf('data-chain-action="cancel"')<0)
check("the summary spells out failures and skips",html.indexOf("3/3 - 1 failed - 1 skipped")>=0)
check("a settled chain shows a full bar",html.indexOf("width:100%")>=0)
chainState.jobs=[step("c2",1,"skipped"),step("c1",0,"done")]
html=chainModule.termChainGroupHtml("chainA",chainModule.termChainSteps("chainA"))
check("a cancelled chain with no failure is marked stopped",html.indexOf("terminal-chain-head stopped")>=0)
chainState.jobs=[step("c2",1,"done"),step("c1",0,"done")]
html=chainModule.termChainGroupHtml("chainA",chainModule.termChainSteps("chainA"))
check("a fully successful chain is marked done",html.indexOf("terminal-chain-head done")>=0)
chainState.jobs=[step("c3",2,"pending"),step("c2",1,"running"),step("c1",0,"done")]
const visibleOnly=[chainState.jobs[1]]
html=chainModule.termChainGroupHtml("chainA",visibleOnly)
check("progress counts the whole chain even when the filter hides steps",html.indexOf("1/3")>=0)
check("a filtered chain renders only the visible steps",html.indexOf('job="c2"')>=0&&html.indexOf('job="c1"')<0)
chainState.jobs=[step("c1",0,"done"),Object.assign(step("d1",0,"running"),{chain_id:"chainB"})]
grouped=chainModule.termGroupJobRows(chainState.jobs)
check("two chains stay separate",grouped.length===2&&grouped.every((e)=>e.kind==="chain"))
check("an unknown chain has no steps",chainModule.termChainSteps("nope").length===0)
check("an empty chain reports zero progress",chainModule.termChainProgress("nope").total===0)
const aiModule=new Function("termFindTab","termState","bridgeCall","showToast","showStatusIsland",
slice(terminalSource,"const TERM_AI_MAX_CHARS","function termAiExplainOutput")+
slice(terminalSource,"function termExtractCommand","function termAiSuggestNext")+
";return{termAiTail,termAiRedactionNote,termExtractCommand,TERM_AI_MAX_CHARS}")
(()=>null,{},()=>({catch(){}}),()=>{},()=>{})
check("short output is sent whole",aiModule.termAiTail("abc")==="abc")
check("long output keeps the tail, not the head",aiModule.termAiTail("H".repeat(100)+"T".repeat(aiModule.TERM_AI_MAX_CHARS)).endsWith("T"))
check("long output is capped at the limit",aiModule.termAiTail("x".repeat(aiModule.TERM_AI_MAX_CHARS*2)).length===aiModule.TERM_AI_MAX_CHARS)
check("empty output stays empty",aiModule.termAiTail(null)==="")
check("no redactions means no note",aiModule.termAiRedactionNote([])==="")
check("one redaction reads singular",aiModule.termAiRedactionNote([{kind:"password",count:1}])==="1 secret redacted before sending")
check("redactions are totalled across kinds",aiModule.termAiRedactionNote([{kind:"password",count:2},{kind:"token",count:3}])==="5 secrets redacted before sending")
const replies=[
["a fenced block wins over prose","Try this instead:\n```bash\nnmap -sV 10.0.0.5\n```\nIt will be slower.","nmap -sV 10.0.0.5"],
["a fenced block with no language still parses","Run:\n```\nls -la /etc\n```","ls -la /etc"],
["a shell prompt marker is stripped","```\n$ whoami\n```","whoami"],
["an angle prompt marker is stripped","```\n> whoami\n```","whoami"],
["a leading comment is skipped","```bash\n# scan the host first\nnmap -p- 10.0.0.5\n```","nmap -p- 10.0.0.5"],
["a double-slash comment is skipped","```\n// try this\ncurl http://a/b\n```","curl http://a/b"],
["only the first command of a block is taken","```\ncd /tmp\nls\n```","cd /tmp"],
["blank lines inside a block are ignored","```\n\n\nid\n```","id"],
["an unfenced reply is refused rather than staging prose","Run whoami to check.",""],
["a bare command with no fence is also refused","whoami",""],
["an empty reply yields nothing",""," "],
["a reply of only a comment yields nothing","```\n# nothing to do\n```",""],
["null is handled",null,""]
]
for(const [name,reply,expected] of replies){
const got=aiModule.termExtractCommand(reply)
check("suggestion parse - "+name,got===expected.trim(),JSON.stringify(got))
}
check("crlf fences parse the same as lf",aiModule.termExtractCommand("```bash\r\nid\r\n```")==="id")
const blockModule=new Function("termEscapeHtml","termExitLabel",
slice(terminalSource,"function termJobBlockState","const TERM_JOB_BLOCK_CLOSE")+
";return{termJobBlockState,termJobBlockOpenHtml}")
(escapeHtml,(code)=>code===0?"exit 0":"exit "+code)
function record(exitCode,endIdx){
return {jobId:"j1",command:"nmap -sV host",exitCode:exitCode,endIdx:endIdx===undefined?10:endIdx,startIdx:0,folded:false,startedAt:0,endedAt:1000}
}
check("a failed block offers the triage affordance",blockModule.termJobBlockOpenHtml(record(1)).indexOf('data-job-ai="j1"')>=0)
check("a successful block does not",blockModule.termJobBlockOpenHtml(record(0)).indexOf("term-job-block-ai")<0)
check("a running block does not",blockModule.termJobBlockOpenHtml(record(null,null)).indexOf("term-job-block-ai")<0)
check("an orphaned block does not",blockModule.termJobBlockOpenHtml(record(null,10)).indexOf("term-job-block-ai")<0)
check("the triage affordance sits inside the head, not the body",blockModule.termJobBlockOpenHtml(record(1)).indexOf("term-job-block-ai")<blockModule.termJobBlockOpenHtml(record(1)).indexOf("term-job-block-body"))
check("the block still reports its exit code",blockModule.termJobBlockOpenHtml(record(7)).indexOf("exit 7")>=0)
check("block state is derived from the exit code",blockModule.termJobBlockState(record(0))==="done"&&blockModule.termJobBlockState(record(3))==="failed")
const trimModule=new Function("termInvalidateRender",
slice(terminalSource,"const TERM_SCROLLBACK_CHARS","function termAppend(id,text)")+
";return{termTrimScrollback,TERM_SCROLLBACK_CHARS,TERM_SCROLLBACK_SLACK}")(()=>{})
function scrollTab(length){
return {buffer:"z".repeat(length),visible:"z".repeat(length),renderedLen:length,listings:[],jobHistory:[],renderVersion:0}
}
const cap=trimModule.TERM_SCROLLBACK_CHARS
const slack=trimModule.TERM_SCROLLBACK_SLACK
check("a buffer at the cap is not trimmed",trimModule.termTrimScrollback(scrollTab(cap))===false)
check("a buffer inside the slack is not trimmed",trimModule.termTrimScrollback(scrollTab(cap+slack))===false)
check("a buffer past the slack is trimmed",trimModule.termTrimScrollback(scrollTab(cap+slack+1))===true)
const trimmed=scrollTab(cap+slack+500)
trimModule.termTrimScrollback(trimmed)
check("trimming cuts back to the cap, not to the threshold",trimmed.buffer.length===cap)
check("buffer and visible stay the same length",trimmed.visible.length===trimmed.buffer.length)
let steady=scrollTab(cap)
let trims=0
for(let tick=0;tick<2000;tick++){
steady.buffer+="line\n"
steady.visible+="line\n"
steady.renderedLen+=5
if(trimModule.termTrimScrollback(steady))trims++
}
check("steady-state output does not re-render on every tick",trims<=Math.ceil(2000*5/slack)+1,trims+" trims over 2000 ticks")
check("steady-state output is still bounded",steady.buffer.length<=cap+slack)
const shifted={buffer:"z".repeat(cap+slack+1000),visible:"z".repeat(cap+slack+1000),renderedLen:cap+slack+1000,listings:[{id:"l1",startIdx:100,endIdx:200},{id:"l2",startIdx:cap+slack+100,endIdx:cap+slack+900}],jobHistory:[{jobId:"old",startIdx:50,endIdx:150},{jobId:"live",startIdx:cap+slack+200,endIdx:null}],pendingCapture:{startIdx:cap+slack+300},renderVersion:0}
trimModule.termTrimScrollback(shifted)
check("listings scrolled off the top are dropped",!shifted.listings.some((l)=>l.id==="l1"))
check("surviving listings keep their span",shifted.listings[0].endIdx-shifted.listings[0].startIdx===800)
check("surviving listings stay inside the buffer",shifted.listings.every((l)=>l.endIdx<=shifted.buffer.length))
check("jobs scrolled off the top are dropped",!shifted.jobHistory.some((j)=>j.jobId==="old"))
check("a still-running job survives the trim",shifted.jobHistory.some((j)=>j.jobId==="live"&&j.endIdx===null))
check("a pending capture index is rebased by exactly the cut",shifted.pendingCapture.startIdx===cap-700,String(shifted.pendingCapture.startIdx)+" wanted "+(cap-700))
check("the surviving listing is rebased by exactly the cut",shifted.listings[0].startIdx===cap-900&&shifted.listings[0].endIdx===cap-100)
check("the running job is rebased by exactly the cut",shifted.jobHistory[0].startIdx===cap-800)
check("rendered length is rebased so the append path stays valid",shifted.renderedLen===shifted.buffer.length)
const gridModule=new Function(slice(terminalSource,"const TERM_RESIZE_DEBOUNCE_MS","function termMeasureCell")+";return{termGridForBox,termClampSize,TERM_MIN_COLS,TERM_MAX_COLS,TERM_MIN_ROWS,TERM_MAX_ROWS}")()
const cell={width:7,height:16}
check("a normal panel maps to a sensible grid",JSON.stringify(gridModule.termGridForBox({width:700,height:320},cell))===JSON.stringify({cols:100,rows:20}))
check("partial cells are floored, never rounded up",gridModule.termGridForBox({width:706,height:320},cell).cols===100)
check("a tiny panel clamps to the minimum",gridModule.termGridForBox({width:10,height:10},cell).cols===gridModule.TERM_MIN_COLS)
check("a huge panel clamps to the maximum",gridModule.termGridForBox({width:99999,height:99999},cell).cols===gridModule.TERM_MAX_COLS)
check("rows clamp to the minimum too",gridModule.termGridForBox({width:700,height:1},cell).rows===gridModule.TERM_MIN_ROWS)
check("a zero-width cell yields no grid",gridModule.termGridForBox({width:700,height:320},{width:0,height:16})===null)
check("a missing cell yields no grid",gridModule.termGridForBox({width:700,height:320},null)===null)
check("a missing box yields no grid",gridModule.termGridForBox(null,cell)===null)
check("a NaN dimension clamps rather than propagating",gridModule.termGridForBox({width:NaN,height:320},cell).cols===gridModule.TERM_MIN_COLS)
check("clamping keeps whole cells",gridModule.termClampSize(42.9,1,100)===42)
const shortcutsSource=fs.readFileSync(path.join(ROOT,"UI","js","components","shortcuts.js"),"utf8")
const suggestModule=new Function(slice(snippetsSource,"function snipIterPlaceholders","function snipResolveCommand")+slice(terminalSource,"const TERM_SUGGEST_LIMIT","let termSuggest=")+";return{termSuggestQuery,termSuggestScore,termSuggestRank,termPlaceholderSpans,termNextPlaceholder,termShortcutFor,termShortcutActionFor,termClipboardKeyAction,termCwdDisplay,TERM_SUGGEST_LIMIT,TERM_SHORTCUT_ACTIONS}")()
const suggestIndex=[
{command:"nmap -sV {IPv4}",title:"Service scan",category:"Recon",type:"Linux Shell",family:"posix"},
{command:"nmap -p- {IPv4}",title:"All ports",category:"Recon",type:"Linux Shell",family:"posix"},
{command:"nikto -h {URL}",title:"Web scanner",category:"Web",type:"Linux Shell",family:"posix"},
{command:"sudo nmap -sU {IPv4}",title:"UDP scan",category:"Recon",type:"Linux Shell",family:"posix"},
{command:"Get-Process | Sort-Object CPU",title:"Top processes",category:"Windows",type:"PowerShell",family:"powershell"},
{command:"gobuster dir -u {URL} -w wordlist",title:"Directory brute force",category:"Web",type:"other",family:"any"},
{command:"netstat -ano",title:"Connections",category:"Windows",type:"CMD",family:"cmd"},
{command:"enum4linux -a {IPv4}",title:"SMB enumeration",category:"Recon",type:"Linux Shell",family:"posix"}
]
const rankCmds=(q,family)=>suggestModule.termSuggestRank(suggestIndex,q,family,8).map((e)=>e.command)
check("suggest: empty input shows nothing",suggestModule.termSuggestQuery("",0,false)===null)
check("suggest: one character shows nothing",suggestModule.termSuggestQuery("n",1,false)===null)
check("suggest: two characters is a query",suggestModule.termSuggestQuery("nm",2,false)==="nm")
check("suggest: leading spaces are ignored",suggestModule.termSuggestQuery("  nm",4,false)==="nm")
check("suggest: caret not at the end shows nothing",suggestModule.termSuggestQuery("nmap",2,false)===null)
check("suggest: a multi-line staged input shows nothing",suggestModule.termSuggestQuery("ls\nnm",5,false)===null)
check("suggest: a manual trigger works on empty input",suggestModule.termSuggestQuery("",0,true)==="")
check("rank: prefix matches come first",rankCmds("nm","posix").slice(0,2).every((c)=>c.startsWith("nmap")),JSON.stringify(rankCmds("nm","posix")))
check("rank: shorter prefix match wins a tie",rankCmds("nmap -","posix")[0]==="nmap -sV {IPv4}"||rankCmds("nmap -","posix")[0]==="nmap -p- {IPv4}")
check("rank: a word inside the command ranks after prefixes",(()=>{const r=rankCmds("nmap","posix");return r.indexOf("sudo nmap -sU {IPv4}")>r.indexOf("nmap -p- {IPv4}")&&r.indexOf("sudo nmap -sU {IPv4}")!==-1})(),JSON.stringify(rankCmds("nmap","posix")))
check("rank: title words match",rankCmds("brute force","posix")[0]==="gobuster dir -u {URL} -w wordlist")
check("rank: category words match",rankCmds("smb","posix")[0]==="enum4linux -a {IPv4}")
check("rank: tokens all have to match",rankCmds("nmap zzz","posix").length===0)
check("rank: fuzzy subsequence on the command",rankCmds("gbstr","posix")[0]==="gobuster dir -u {URL} -w wordlist")
check("rank: nothing for garbage",rankCmds("qqqq","posix").length===0)
check("rank: an exact match is not suggested back",rankCmds("netstat -ano","cmd").indexOf("netstat -ano")===-1)
check("rank: shell family breaks ties toward the session",(()=>{const idx=[{command:"dir /s",family:"cmd"},{command:"dir -la",family:"posix"}];return suggestModule.termSuggestRank(idx,"dir","posix",8)[0].command==="dir -la"&&suggestModule.termSuggestRank(idx,"dir","cmd",8)[0].command==="dir /s"})())
check("rank: other-shell entries are demoted, not hidden",rankCmds("get-","posix")[0]==="Get-Process | Sort-Object CPU")
check("rank: results are capped",suggestModule.termSuggestRank(Array.from({length:30},(_,i)=>({command:"echo "+i,family:"any"})),"ec","posix",8).length===8)
check("rank: duplicate commands collapse",suggestModule.termSuggestRank([{command:"id"},{command:"ID"},{command:"idx"}],"",null,8).length===2)
check("rank: manual empty query lists the session's shell first",suggestModule.termSuggestRank(suggestIndex,"","powershell",8)[0].family==="powershell")
check("rank: case-insensitive prefix",rankCmds("NMAP -s","posix")[0]==="nmap -sV {IPv4}")
const ph="nmap -p {PORT} {IPv4} ${HOME}"
check("placeholders: shell expansions are not placeholders",JSON.stringify(suggestModule.termPlaceholderSpans(ph).map((s)=>s[2]))==='["PORT","IPv4"]')
check("placeholders: Tab from the start selects the first",JSON.stringify(suggestModule.termNextPlaceholder(ph,0,0,1))===JSON.stringify([8,14,"PORT"]))
check("placeholders: Tab from the first selects the second",suggestModule.termNextPlaceholder(ph,8,14,1)[2]==="IPv4")
check("placeholders: Tab past the last wraps",suggestModule.termNextPlaceholder(ph,15,21,1)[2]==="PORT")
check("placeholders: Shift+Tab goes back",suggestModule.termNextPlaceholder(ph,15,21,-1)[2]==="PORT")
check("placeholders: none means Tab goes to the shell",suggestModule.termNextPlaceholder("ls -la",0,0,1)===null)
check("shortcuts: defaults apply when nothing saved",suggestModule.termShortcutFor({},"suggest")==="Ctrl+Space")
check("shortcuts: a cleared shortcut stays cleared",suggestModule.termShortcutFor({suggest:""},"suggest")==="")
check("shortcuts: combo maps to its action",suggestModule.termShortcutActionFor({command_search:"Alt+P"},"Alt+P")==="command_search")
check("shortcuts: an empty combo maps to nothing",suggestModule.termShortcutActionFor({suggest:""},"")===null)
const keyEvent=(key,mods)=>Object.assign({key,ctrlKey:false,shiftKey:false,altKey:false,metaKey:false},mods||{})
check("keys: Ctrl+Shift+C copies and never interrupts",suggestModule.termClipboardKeyAction(keyEvent("C",{ctrlKey:true,shiftKey:true}),false)==="copy")
check("keys: Ctrl+Shift+V pastes",suggestModule.termClipboardKeyAction(keyEvent("V",{ctrlKey:true,shiftKey:true}),false)==="paste")
check("keys: Ctrl+C with a selection copies",suggestModule.termClipboardKeyAction(keyEvent("c",{ctrlKey:true}),true)==="copy")
check("keys: Ctrl+C without a selection interrupts",suggestModule.termClipboardKeyAction(keyEvent("c",{ctrlKey:true}),false)==="interrupt")
check("keys: plain Ctrl+V is left to the native paste",suggestModule.termClipboardKeyAction(keyEvent("v",{ctrlKey:true}),false)===null)
check("keys: Ctrl+Alt+C is not routed",suggestModule.termClipboardKeyAction(keyEvent("c",{ctrlKey:true,altKey:true}),false)===null)
check("cwd: posix path is wrapped in LRM marks",suggestModule.termCwdDisplay("/home/kali")==="‎/home/kali‎")
check("cwd: empty stays empty",suggestModule.termCwdDisplay("")==="")
const shortcutModule=new Function(slice(shortcutsSource,"const SHORTCUT_MODIFIER_KEYS","function shortcutSheetSections")+";return{shortcutNormalize,shortcutFromEvent,shortcutMatches,shortcutConflict}")()
check("shortcut: normalize orders modifiers",shortcutModule.shortcutNormalize("shift+ctrl+space")==="Ctrl+Shift+Space")
check("shortcut: normalize uppercases letters",shortcutModule.shortcutNormalize("alt+p")==="Alt+P")
check("shortcut: a bare letter is refused",shortcutModule.shortcutNormalize("p")===null)
check("shortcut: Shift alone is not enough",shortcutModule.shortcutNormalize("Shift+F")===null)
check("shortcut: function keys need no modifier",shortcutModule.shortcutNormalize("f2")==="F2")
check("shortcut: Super is refused",shortcutModule.shortcutNormalize("Super+Space")===null)
check("shortcut: empty means unset",shortcutModule.shortcutNormalize("")==="")
check("shortcut: event to combo uses the physical key",shortcutModule.shortcutFromEvent(keyEvent("P",{ctrlKey:true,shiftKey:true,code:"KeyP"}))==="Ctrl+Shift+P")
check("shortcut: space is named",shortcutModule.shortcutFromEvent(keyEvent(" ",{ctrlKey:true,code:"Space"}))==="Ctrl+Space")
check("shortcut: a lone modifier is no combo",shortcutModule.shortcutFromEvent(keyEvent("Control",{ctrlKey:true}))==="")
check("shortcut: Meta combos are ignored",shortcutModule.shortcutFromEvent(keyEvent("a",{metaKey:true}))==="")
check("shortcut: matches compares canonically",shortcutModule.shortcutMatches(keyEvent(" ",{ctrlKey:true,code:"Space"}),"Ctrl+Space"))
check("shortcut: terminal control keys are reserved","CDZLRUWAE".split("").every((k)=>shortcutModule.shortcutConflict("Ctrl+"+k)))
check("shortcut: Ctrl+Shift+C and V are reserved",!!shortcutModule.shortcutConflict("Ctrl+Shift+C")&&!!shortcutModule.shortcutConflict("Ctrl+Shift+V"))
check("shortcut: desktop Ctrl+Alt+T is reserved",!!shortcutModule.shortcutConflict("Ctrl+Alt+T"))
check("shortcut: defaults are not reserved",suggestModule.TERM_SHORTCUT_ACTIONS.every((a)=>!shortcutModule.shortcutConflict(a.fallback)&&shortcutModule.shortcutNormalize(a.fallback)===a.fallback))
const paneModule=new Function(slice(terminalSource,"const TERM_LAYOUTS","function termBuildPanes")+";return{TERM_LAYOUTS,TERM_LAYOUT_ORDER,TERM_PANE_MIN_W,TERM_CLOSED_MAX,termNormalizeLayout,termLayoutPaneCount,termClampRatio,termPaneRects,termPaneStyle,termSplitterStyle,termPaneNeighbor,termWorkspaceSnapshot,termPushClosed,termLayoutIconSvg}")()
const near=(a,b)=>Math.abs(a-b)<1e-9
function tiles(geo){
let area=0
geo.panes.forEach((r)=>{area+=r.w*r.h})
const inside=geo.panes.every((r)=>r.x>=0&&r.y>=0&&r.x+r.w<=1+1e-9&&r.y+r.h<=1+1e-9&&r.w>0&&r.h>0)
let overlap=false
geo.panes.forEach((a,i)=>geo.panes.forEach((b,j)=>{if(i<j&&Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>1e-9&&Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>1e-9)overlap=true}))
return near(area,1)&&inside&&!overlap
}
paneModule.TERM_LAYOUT_ORDER.forEach((id)=>{
const geo=paneModule.termPaneRects(id,{v:0.37,h:0.62})
check("panes: "+id+" has the declared pane count",geo.panes.length===paneModule.termLayoutPaneCount(id))
check("panes: "+id+" tiles the area exactly with no overlap",tiles(geo),JSON.stringify(geo.panes))
check("panes: "+id+" splitters sit on pane edges",geo.splitters.every((sp)=>geo.panes.some((r)=>sp.key==="v"?near(r.x,sp.at):near(r.y,sp.at))))
})
const t12=paneModule.termPaneRects("top1bottom2",{v:0.3,h:0.4})
check("panes: one-on-top layout puts pane 0 across the full width",near(t12.panes[0].w,1)&&near(t12.panes[0].h,0.4))
check("panes: the two bottom panes split at the v ratio",near(t12.panes[1].w,0.3)&&near(t12.panes[2].x,0.3)&&near(t12.panes[2].w,0.7))
check("panes: the bottom splitter only spans the bottom row",t12.splitters.find((s)=>s.key==="v").from===0.4)
check("panes: an unknown layout falls back to single",paneModule.termNormalizeLayout("diagonal")==="single"&&paneModule.termPaneRects("diagonal",{}).panes.length===1)
check("panes: inherited keys are not layouts",paneModule.termNormalizeLayout("toString")==="single")
check("panes: missing ratios default to an even split",near(paneModule.termPaneRects("cols2",null).panes[0].w,0.5))
check("splitter: clamps to keep the minimum pane width",near(paneModule.termClampRatio(0.01,1000,160),0.16)&&near(paneModule.termClampRatio(0.99,1000,160),0.84))
check("splitter: a ratio inside the limits is kept",near(paneModule.termClampRatio(0.3,1000,160),0.3))
check("splitter: an area too small for two panes centres",paneModule.termClampRatio(0.2,250,160)===0.5)
check("splitter: no size yet keeps 10%..90%",paneModule.termClampRatio(0.02,0,160)===0.1&&paneModule.termClampRatio(5,0,160)===0.9)
check("splitter: junk ratios become an even split",paneModule.termClampRatio("x",800,160)===0.5&&paneModule.termClampRatio(NaN,800,160)===0.5)
const st=paneModule.termPaneStyle({x:0.5,y:0,w:0.5,h:1},6)
check("pane style: an inner left edge gives up half the gap",st.left==="calc(50% + 3px)"&&st.width==="calc(50% - 3px)",JSON.stringify(st))
check("pane style: outer edges keep the full size",st.top==="calc(0% + 0px)"&&st.height==="calc(100% - 0px)",JSON.stringify(st))
const mid=paneModule.termPaneStyle({x:0.25,y:0.25,w:0.5,h:0.5},6)
check("pane style: a pane with four inner edges loses a full gap each way",mid.width==="calc(50% - 6px)"&&mid.height==="calc(50% - 6px)")
const ss=paneModule.termSplitterStyle({key:"v",at:0.3,from:0.4,to:1},6)
check("splitter style: a vertical bar is centred on its ratio and spans its range",ss.left==="calc(30% - 3px)"&&ss.width==="6px"&&ss.top==="40%"&&ss.height==="60%",JSON.stringify(ss))
const g4=paneModule.termPaneRects("grid4",{v:0.5,h:0.5}).panes
check("focus: right of top-left is top-right",paneModule.termPaneNeighbor(g4,0,"right")===1)
check("focus: below top-left is bottom-left",paneModule.termPaneNeighbor(g4,0,"down")===2)
check("focus: nothing to the left of a left pane",paneModule.termPaneNeighbor(g4,0,"left")===-1)
check("focus: up from bottom-right is top-right",paneModule.termPaneNeighbor(g4,3,"up")===1)
const tb=paneModule.termPaneRects("top1bottom2",{v:0.3,h:0.5}).panes
check("focus: down from the top pane picks the bottom pane sharing the longest edge",paneModule.termPaneNeighbor(tb,0,"down")===2)
check("focus: up from either bottom pane reaches the top pane",paneModule.termPaneNeighbor(tb,1,"up")===0&&paneModule.termPaneNeighbor(tb,2,"up")===0)
const lr=paneModule.termPaneRects("left2right1",{v:0.5,h:0.5}).panes
check("focus: right from either left pane reaches the tall right pane",paneModule.termPaneNeighbor(lr,0,"right")===2&&paneModule.termPaneNeighbor(lr,1,"right")===2)
check("focus: an unknown pane index yields nothing",paneModule.termPaneNeighbor(lr,9,"right")===-1)
const snap=paneModule.termWorkspaceSnapshot({layout:"top1bottom2",ratios:{v:0.3,h:2},focusPane:1,panes:[{sessionId:"a"},{sessionId:"b"},{sessionId:null}],tabs:[{sessionId:"a",label:"recon",shellId:"shell",profileId:"p1",cwd:"/tmp"},{sessionId:"b",label:"root",shellId:"shell",elevated:true}]})
check("workspace: snapshot keeps layout, ratios and focus",snap.layout==="top1bottom2"&&near(snap.ratios.v,0.3)&&snap.ratios.h===0.9&&snap.focus===1)
check("workspace: each pane records how to start a fresh shell",JSON.stringify(snap.panes[0])===JSON.stringify({name:"recon",shell_id:"shell",profile_id:"p1",cwd:"/tmp"}),JSON.stringify(snap.panes[0]))
check("workspace: elevated and empty panes are not restored",snap.panes[1]===null&&snap.panes[2]===null)
check("workspace: an unknown layout is saved as single",paneModule.termWorkspaceSnapshot({layout:"x",ratios:{},panes:[],tabs:[]}).layout==="single")
let closedList=[]
for(let i=0;i<15;i++)closedList=paneModule.termPushClosed(closedList,{id:"c"+i,name:"s"+i})
check("closed: the list keeps only the newest ten",closedList.length===paneModule.TERM_CLOSED_MAX&&closedList[0].id==="c14"&&closedList[9].id==="c5")
closedList=paneModule.termPushClosed(closedList,{id:"c7",name:"again"})
check("closed: re-pushing an entry moves it to the front instead of duplicating it",closedList[0].name==="again"&&closedList.filter((x)=>x.id==="c7").length===1&&closedList.length===10)
check("closed: a custom max is honoured",paneModule.termPushClosed([{id:"a"},{id:"b"}],{id:"c"},2).map((x)=>x.id).join()==="c,a")
check("layout icon: draws one rect per pane",(paneModule.termLayoutIconSvg("grid4").match(/<rect/g)||[]).length===4&&(paneModule.termLayoutIconSvg("single").match(/<rect/g)||[]).length===1)
const pollModule=new Function(slice(terminalSource,"const TERM_HIDDEN_POLL_MS","function termPollTick")+";return{termPollPlan,TERM_HIDDEN_POLL_MS}")()
const pollTabs=[{sessionId:"v1"},{sessionId:"v2"},{sessionId:"h1"},{sessionId:"h2",activeJob:{}},{sessionId:"d1",dead:true}]
const quiet=pollModule.termPollPlan(pollTabs,["v1","v2"],1000,900)
check("poll: visible panes and running jobs are read every tick",quiet.ids.join()==="v1,v2,h2"&&!quiet.hiddenDue,quiet.ids.join())
const due=pollModule.termPollPlan(pollTabs,["v1","v2"],5000,900)
check("poll: sessions that are only tabs are read about once a second",due.hiddenDue&&due.ids.join()==="v1,v2,h1,h2",due.ids.join())
check("poll: dead sessions are never read",!due.ids.includes("d1"))
const dblModule=new Function(slice(terminalSource,"let termLastTabClick","function termRenderTabs")+";return{termTabDoubleClicked}")()
check("tabs: a single click is not a double click",dblModule.termTabDoubleClicked("a",1000)===false)
check("tabs: a second click on the same tab inside 450ms is",dblModule.termTabDoubleClicked("a",1300)===true)
check("tabs: a third click starts a new pair",dblModule.termTabDoubleClicked("a",1400)===false)
check("tabs: clicks on different tabs never pair",dblModule.termTabDoubleClicked("b",1500)===false)
check("tabs: a slow second click does not pair",dblModule.termTabDoubleClicked("b",2500)===false)
check("shortcut: desktop workspace keys Ctrl+Alt+Arrow are reserved",["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].every((k)=>!!shortcutModule.shortcutConflict("Ctrl+Alt+"+k)))
check("shortcut: reopen and pane focus defaults exist",["reopen_closed","pane_left","pane_right","pane_up","pane_down"].every((id)=>suggestModule.TERM_SHORTCUT_ACTIONS.some((a)=>a.id===id)))
check("shortcut: terminal shortcut labels fit the sheet",suggestModule.TERM_SHORTCUT_ACTIONS.every((a)=>a.label.length<=45))
check("shortcut: Alt+Arrow combos round-trip",shortcutModule.shortcutFromEvent(keyEvent("ArrowLeft",{altKey:true,code:"ArrowLeft"}))==="Alt+ArrowLeft"&&shortcutModule.shortcutNormalize("alt+left")==="Alt+ArrowLeft")
check("shortcut: Ctrl+Shift+T comes from the physical key",shortcutModule.shortcutFromEvent(keyEvent("T",{ctrlKey:true,shiftKey:true,code:"KeyT"}))==="Ctrl+Shift+T")
check("terminal css: a maximized panel hides the pages but not the modal backdrop",/\.work-area\.maximized \.content>:not\(#appModalBackdrop\)\{display:none\}/.test(fs.readFileSync(path.join(ROOT,"UI","css","terminal.css"),"utf8"))&&!/\.work-area\.maximized \.content\{display:none\}/.test(fs.readFileSync(path.join(ROOT,"UI","css","terminal.css"),"utf8")))
const labelModule=new Function(slice(terminalSource,"function termDefaultLabel","function termAddSessionTab")+";return{termDefaultLabel}")()
check("names: the default is the session count plus one",labelModule.termDefaultLabel("zsh",[{label:"a"},{label:"b"}])==="zsh 3")
check("names: a default never repeats a name still open",labelModule.termDefaultLabel("zsh",[{label:"zsh 1"},{label:"zsh 3"}])==="zsh 4")
check("names: the first session is number one",labelModule.termDefaultLabel("PowerShell",[])==="PowerShell 1")
const commandsSource=fs.readFileSync(path.join(ROOT,"UI","js","pages","commands.js"),"utf8")
const cardSource=fs.readFileSync(path.join(ROOT,"UI","js","components","card.js"),"utf8")
const cmdsModule=new Function(slice(commandsSource,"function cmdsFilterRows","function cmdsFilterSort")+";return{cmdsFilterRows,cmdsPageSlice,cmdsBraceContext,cmdsApplyBraceKey,cmdsInsertToken,cmdsElementMatches,cmdsSplitTags,cmdsTagContext,cmdsTagMatches,cmdsApplyTag,cmdsFormSig,cmdsRelatedSummary,cmdsSizeLabel}")()
const cmdRows=[{id:3,src:"CommandsNotes",title:"b",category:"X",command:"nmap",note_name:"Alpha",description:""},{id:2,src:"Commands",title:"a",category:"Y",command:"id",note_name:"Beta",description:"find hosts"},{id:1,src:"CommandsNotes",title:"c",category:"X",command:"ls",note_name:"",description:""}]
const cmdState=(o)=>Object.assign({search:"",categoryFilter:"",linkFilter:"",sortKey:"",sortDir:1},o||{})
check("cmds: default order keeps DB order",cmdsModule.cmdsFilterRows(cmdRows,cmdState()).map((r)=>r.id).join()==="3,2,1")
check("cmds: sort by title asc/desc",cmdsModule.cmdsFilterRows(cmdRows,cmdState({sortKey:"title"})).map((r)=>r.title).join("")==="abc"&&cmdsModule.cmdsFilterRows(cmdRows,cmdState({sortKey:"title",sortDir:-1})).map((r)=>r.title).join("")==="cba")
check("cmds: linked filter",cmdsModule.cmdsFilterRows(cmdRows,cmdState({linkFilter:"linked"})).map((r)=>r.id).join()==="2")
check("cmds: not-linked filter",cmdsModule.cmdsFilterRows(cmdRows,cmdState({linkFilter:"standalone"})).map((r)=>r.id).join()==="3,1")
check("cmds: search covers note name",cmdsModule.cmdsFilterRows(cmdRows,cmdState({search:"alpha"})).map((r)=>r.id).join()==="3")
check("cmds: search covers description",cmdsModule.cmdsFilterRows(cmdRows,cmdState({search:"HOSTS"})).map((r)=>r.id).join()==="2")
check("cmds: input rows are not reordered",cmdsModule.cmdsFilterRows(cmdRows,cmdState({sortKey:"title"}))!==cmdRows&&cmdRows[0].id===3)
const pg=cmdsModule.cmdsPageSlice([1,2,3,4,5],1,2)
check("cmds: page slice",pg.rows.join()==="3,4"&&pg.pages===3&&pg.page===1)
check("cmds: page clamps high and low",cmdsModule.cmdsPageSlice([1,2,3],9,2).page===1&&cmdsModule.cmdsPageSlice([1,2,3],-4,2).page===0)
check("cmds: empty list has one page",cmdsModule.cmdsPageSlice([],0,10).pages===1)
const bc=cmdsModule.cmdsBraceContext("nmap {IP} -p {Po",16)
check("cmds: brace context prefix",bc&&bc.prefix==="Po"&&bc.start===14&&bc.end===16)
check("cmds: closed brace has no context",cmdsModule.cmdsBraceContext("nmap {IP} ",10)===null)
check("cmds: brace across newline has no context",cmdsModule.cmdsBraceContext("a {x\ny",6)===null)
check("cmds: nested open has no context",cmdsModule.cmdsBraceContext("a {{x",5)===null)
const ap=cmdsModule.cmdsApplyBraceKey("nmap {I}",{start:6,end:7},"IPv4")
check("cmds: apply key reuses the auto-closed brace",ap.text==="nmap {IPv4}"&&ap.pos===11)
const ap2=cmdsModule.cmdsApplyBraceKey("nmap {I -p",{start:6,end:7},"IP")
check("cmds: apply key adds a closing brace",ap2.text==="nmap {IP} -p"&&ap2.pos===9)
const ins=cmdsModule.cmdsInsertToken("ping  -c1",5,5,"Host")
check("cmds: insert token at cursor",ins.text==="ping {Host} -c1"&&ins.pos===11)
check("cmds: insert token replaces selection",cmdsModule.cmdsInsertToken("ping X",5,6,"{IP}").text==="ping {IP}")
const elRows=[{key:"IP",usage:9},{key:"IPv6",usage:4},{key:"Port",usage:2},{key:"Ident",usage:1}]
check("cmds: element matches keep usage order and limit",cmdsModule.cmdsElementMatches(elRows,"i",3).map((r)=>r.key).join()==="IP,IPv6,Ident")
check("cmds: element matches empty prefix",cmdsModule.cmdsElementMatches(elRows,"",3).length===3&&cmdsModule.cmdsElementMatches(elRows,"{po",0).map((r)=>r.key).join()==="Port")
check("cmds: split tags normalises",cmdsModule.cmdsSplitTags(" a;  b  c ,A,,").join("|")==="a|b c")
const tc=cmdsModule.cmdsTagContext("web, re",7)
check("cmds: tag context is the current token",tc.prefix==="re"&&tc.start===4&&tc.end===7)
check("cmds: tag matches start-with, skip present",cmdsModule.cmdsTagMatches(["recon","Remote","web","rest"],"web, re",tc,8).join()==="recon,Remote,rest"&&cmdsModule.cmdsTagMatches(["recon"],"recon, re",cmdsModule.cmdsTagContext("recon, re",9),8).length===0)
check("cmds: tag matches need a prefix",cmdsModule.cmdsTagMatches(["a"],"",cmdsModule.cmdsTagContext("",0),8).length===0)
const at=cmdsModule.cmdsApplyTag("web, re",tc,"recon")
check("cmds: apply tag",at.text==="web, recon, "&&at.pos===12)
check("cmds: apply tag mid-list",cmdsModule.cmdsApplyTag("re,web",cmdsModule.cmdsTagContext("re,web",2),"recon").text==="recon, web")
const sig=cmdsModule.cmdsFormSig({cmd_note_title:"a",command:"x"})
check("cmds: form sig detects change",sig===cmdsModule.cmdsFormSig({cmd_note_title:"a",command:"x",tags:""})&&sig!==cmdsModule.cmdsFormSig({cmd_note_title:"a",command:"x "}))
check("cmds: related summary",cmdsModule.cmdsRelatedSummary([{note_name:"a"},{note_name:"b"},{note_name:"c"},{note_name:"d"},{note_name:"e"}])==="a, b, c, +2 more"&&cmdsModule.cmdsRelatedSummary([])==="-")
check("cmds: size label",cmdsModule.cmdsSizeLabel("ab\ncd")==="5 chars | 2 lines"&&cmdsModule.cmdsSizeLabel("")==="0 chars | 1 line")
const cardModule=new Function(slice(cardSource,"function cardStatInfo","function renderActivityList")+";return{cardStatInfo}")()
const tj=cardModule.cardStatInfo("terminal_jobs",{terminal_jobs:{running:2,failed:1,total:7}})
check("card: terminal jobs shows running and failed",tj.value==="2"&&tj.sub.includes("1 failed of 7"))
check("card: terminal jobs empty",cardModule.cardStatInfo("terminal_jobs",{}).value==="0"&&cardModule.cardStatInfo("terminal_jobs",{}).sub.includes("no jobs"))
const targetsSource=fs.readFileSync(path.join(ROOT,"UI","js","pages","targets.js"),"utf8")
const miniSource=fs.readFileSync(path.join(ROOT,"UI","js","windows","mini.js"),"utf8")
const tgtState0={targetSearch:"",targets:[{name:"zeta",values:{IP:"10.0.0.9"}},{name:"Alpha",values:{}},{name:"beta",values:{URL:"http://intra.local"}}]}
const tgtModule=new Function("tgtState",slice(targetsSource,"function tgtFilterTargets","const TGT_ENGAGEMENT_STATUSES")+slice(targetsSource,"function tgtFieldMatches","function tgtFilterFormFields")+";return{tgtFilterTargets,tgtStripBraces,tgtFieldMatches}")(tgtState0)
check("targets: list is sorted by name",tgtModule.tgtFilterTargets().map((t)=>t.name).join()==="Alpha,beta,zeta")
tgtState0.targetSearch="10.0.0"
check("targets: search matches values",tgtModule.tgtFilterTargets().map((t)=>t.name).join()==="zeta")
tgtState0.targetSearch="ALPHA"
check("targets: search matches names case-insensitively",tgtModule.tgtFilterTargets().map((t)=>t.name).join()==="Alpha")
check("targets: filtering never reorders the state",tgtState0.targets[0].name==="zeta")
check("targets: braces stripped",tgtModule.tgtStripBraces(" {ip} ")==="ip"&&tgtModule.tgtStripBraces("ip")==="ip"&&tgtModule.tgtStripBraces("{}")==="")
check("targets: field finder matches any token",tgtModule.tgtFieldMatches("RHOST","port, host")&&!tgtModule.tgtFieldMatches("URL","port")&&tgtModule.tgtFieldMatches("URL",""))
const miniModule=new Function(slice(miniSource,"function miniCmdMeta","function miniOpenRelatedNote")+";return{miniCmdMeta}")()
check("mini: tooltip shows category/sub and tags",miniModule.miniCmdMeta({category:"Recon",sub:"",tags:"web"})==="Recon/General | tags: web")
check("mini: no tooltip when there is no meta",miniModule.miniCmdMeta({category:"",sub:"",tags:""})==="")
const miniEsc=new Function(slice(miniSource,"function miniEscapeHtml","function miniIterPlaceholders")+";return miniEscapeHtml")()
check("mini: escaping is safe inside attributes",miniEsc('a" onmouseover="x\' <b>&')==="a&quot; onmouseover=&quot;x&#39; &lt;b&gt;&amp;")
check("mini: escaping handles empty values",miniEsc(null)===""&&miniEsc(undefined)===""&&miniEsc(0)==="0")
// Mini: the live-target poll must not rebuild the command table when nothing changed (a rebuild between mousedown and mouseup eats the click).
function syncThen(v){return{then(f){f(v);return{catch(){}}}}}
const miniLiveCalls={render:0,status:0}
let miniLiveAnswer={name:"Box A",map:{ip:"10.0.0.5"}}
const miniLiveModule=new Function("bridgeCall","miniUpdateStatus","miniRenderCmds","let miniState={liveKey:'',locked:false,liveMap:{},liveName:''};"+slice(miniSource,"function miniLiveKey","function miniRefreshCmds")+";return{miniRefreshLiveTarget,state:()=>miniState}")(()=>syncThen(miniLiveAnswer),()=>miniLiveCalls.status++,()=>miniLiveCalls.render++)
miniLiveModule.miniRefreshLiveTarget();miniLiveModule.miniRefreshLiveTarget();miniLiveModule.miniRefreshLiveTarget()
check("mini: unchanged live target renders once",miniLiveCalls.render===1&&miniLiveModule.state().liveName==="Box A",JSON.stringify(miniLiveCalls))
miniLiveAnswer={name:"Box A",map:{ip:"10.0.0.6"}}
miniLiveModule.miniRefreshLiveTarget()
check("mini: a changed value re-renders",miniLiveCalls.render===2&&miniLiveModule.state().liveMap.ip==="10.0.0.6")
miniLiveModule.state().locked=true;miniLiveAnswer={name:"Other",map:{}}
miniLiveModule.miniRefreshLiveTarget()
check("mini: nothing is rendered while locked",miniLiveCalls.render===2&&miniLiveModule.state().liveName==="Box A")
// Mini: when the app locks, every list and the Quick Space editor are emptied; unsaved edits are kept in memory only.
function fakeEl(){return{innerHTML:"x",textContent:"",classList:{set:new Set(["hidden"]),add(c){this.set.add(c)},remove(c){this.set.delete(c)},contains(c){return this.set.has(c)}}}}
const lockEls={miniCmdTableBody:fakeEl(),miniTgtTableBody:fakeEl(),miniLockOverlay:fakeEl()}
const lockBody=fakeEl();lockBody.innerHTML="<b>secret</b>"
const lockDoc={getElementById:(id)=>lockEls[id],body:fakeEl()}
const lockState={locked:false,quickDirty:2,quickSaveTimer:null,quickWrap:false,cmds:[1],targets:[1],liveMap:{ip:"1"},liveName:"Box A",liveKey:"k",dataSig:{}}
const lockModule=new Function("document","miniState","miniQuickBody","miniQuickCleanHtml","miniQuickSearchOpen","miniQuickCloseSearch","closeContextMenu","miniUpdateStatus",slice(miniSource,"function miniLock(","function miniUnlock(")+";return{miniLock}")(lockDoc,lockState,()=>lockBody,(b)=>b.innerHTML,()=>false,()=>{},()=>{},()=>{})
lockModule.miniLock()
check("mini lock: editor, commands and targets are emptied",lockBody.innerHTML===""&&lockEls.miniCmdTableBody.innerHTML===""&&lockEls.miniTgtTableBody.innerHTML==="")
check("mini lock: live values are dropped",lockState.liveName===""&&Object.keys(lockState.liveMap).length===0&&lockState.cmds.length===0)
check("mini lock: unsaved Quick Space edits are stashed for after unlock",lockState.quickStash&&lockState.quickStash.html==="<b>secret</b>"&&lockState.quickStash.wrap===false)
check("mini lock: the overlay is shown",!lockEls.miniLockOverlay.classList.contains("hidden")&&lockDoc.body.classList.contains("mini-locked"))
check("mini: the poll asks whether the app is locked before loading data",/function miniLiveTick\(\)\{\s*return bridgeCall\("security\.is_locked"\)/.test(miniSource))
check("mini: Quick Space never saves while locked",/function miniQuickSave\(flash\)\{\s*if\(miniState\.locked\)return/.test(miniSource))
check("mini: input is reported to the main window's auto-lock",/bridgeCall\("window\.activity"\)/.test(miniSource))
check("mini: find wrappers are stripped from saved HTML",/querySelectorAll\("mark\.mini-highlight,span\.mini-find-wrap"\)/.test(slice(miniSource,"function miniQuickCleanHtml","function miniQuickSave")))
check("mini: root text is wrapped before ranges are collected",slice(miniSource,"function miniQuickHighlight","function miniQuickUpdateCount").indexOf("miniQuickWrapRootText(body)")<slice(miniSource,"function miniQuickHighlight","function miniQuickUpdateCount").indexOf("miniQuickFindRanges(body,q)"))
const miniHtml=fs.readFileSync(path.join(ROOT,"UI","windows","mini.html"),"utf8")
const miniCss=fs.readFileSync(path.join(ROOT,"UI","css","windows","mini.css"),"utf8")
check("mini: theme.js is loaded so light/royal/accent follow the main window",/<script src="\.\.\/js\/components\/theme\.js"><\/script>/.test(miniHtml)&&/themeApplyAll\(\)/.test(miniSource))
check("mini: the command table has a fixed layout (ellipsis, no horizontal scroll)",/\.mini-table\{[^}]*table-layout:fixed/.test(miniCss))
check("mini: window buttons never shrink off screen",/\.mini-controls\{[^}]*flex:0 0 auto/.test(miniCss)&&/\.mini-tabs\{[^}]*min-width:0/.test(miniCss))
check("mini: the lock overlay and collapsed label exist",/id="miniLockOverlay"/.test(miniHtml)&&/id="miniCollapsedLabel"/.test(miniHtml))
const settingsSource=fs.readFileSync(path.join(ROOT,"UI","js","pages","settings.js"),"utf8")
const secModule=new Function(slice(settingsSource,"function setParseAuditExpiryAmount","function setApplyAuditExpiry")+";return{setParseAuditExpiryAmount}")()
check("security: audit expiry accepts 1 and 999",secModule.setParseAuditExpiryAmount("1")===1&&secModule.setParseAuditExpiryAmount(" 999 ")===999&&secModule.setParseAuditExpiryAmount(30)===30)
check("security: audit expiry rejects 0, 1000, fractions and text",[0,"0","1000",1000,"1.5","-3","","abc","1e2",null].every((v)=>secModule.setParseAuditExpiryAmount(v)===null))
const lockSource=fs.readFileSync(path.join(ROOT,"UI","js","components","lock-screen.js"),"utf8")
const statusCatch=lockSource.slice(lockSource.indexOf("}).catch(()=>{",lockSource.indexOf('bridgeCall("security.status")')))
check("lock screen: a failed status call never hides the overlay or unlocks",!/onUnlock\(\)|finish\(\)|classList\.add\("hidden"\)/.test(statusCatch.slice(0,statusCatch.indexOf("check(0)"))))
// E2E regressions: ${VAR} is not a placeholder (B1); Commands Run fills placeholders from the live target like Snippets (B9).
const phModule=new Function(slice(snippetsSource,"function snipIterPlaceholders","function snipResolveCommand")+slice(commandsSource,"function cmdsApplyLiveMap","function cmdsResolveLive")+";return{snipIterPlaceholders,cmdsApplyLiveMap}")()
check("placeholders: ${VAR}, JSON and {{x}} are skipped",phModule.snipIterPlaceholders("echo ${HOME} {} '{\"a\":1}' {{x}} {IPv4}").map((s)=>s[2]).join()==="IPv4")
check("cmds run: live target fills known keys, keeps unknown and ${VAR}",phModule.cmdsApplyLiveMap("ping {IPv4} {Missing} ${IPv4}",{ipv4:"10.0.0.5"})==="ping 10.0.0.5 {Missing} ${IPv4}")
check("cmds run: no live target leaves the text untouched",phModule.cmdsApplyLiveMap("ping {IPv4}",{})==="ping {IPv4}")
check("cmds run: Run in Terminal resolves the live target before dispatch",/cmdsResolveLive\(raw\)/.test(slice(commandsSource,"function cmdsRunInTerminal","function cmdsHandleRowClick")))
const themeSource=fs.readFileSync(path.join(ROOT,"UI","js","components","theme.js"),"utf8")
const styleDoc={documentElement:{dataset:{}}}
const styleModule=new Function("document",slice(themeSource,"function applyStyleState","function themeApplyAll")+";return{applyStyleState}")(styleDoc)
styleModule.applyStyleState({style:"classic"})
check("style: classic is applied to <html>",styleDoc.documentElement.dataset.style==="classic")
styleModule.applyStyleState({style:"glass"})
check("style: glass is applied to <html>",styleDoc.documentElement.dataset.style==="glass")
;[null,{},{style:"neon"},{style:""}].forEach((v)=>{styleDoc.documentElement.dataset.style="classic";styleModule.applyStyleState(v)})
check("style: a missing or unknown value falls back to glass",styleDoc.documentElement.dataset.style==="glass")
check("style: theme refresh also re-reads the style",/bridgeCall\("theme\.style"\)\)\.then\(applyStyleState\)/.test(slice(themeSource,"function themeApplyAll","function initTheme")))
check("style: settings saves through the bridge, never localStorage",/bridgeCall\("theme\.set_style"/.test(settingsSource)&&!/localStorage/.test(slice(settingsSource,"function setDoChangeStyle","function setDoChangeThemeMode")))
check("style: mini window applies the saved style",/bridgeCall\("theme\.style"\)/.test(miniSource))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
