let termState={platform:"",extras:null,taskWatch:{},enabled:false,open:false,width:380,height:320,mode:"right",maximized:false,shells:[],tabs:[],activeId:null,pollTimer:null,polling:false,pollDelay:60,lastAliveCheck:0,confirmMultilinePaste:true,snippetClickAction:"copy",commandClickAction:"copy",snippetRunConfirm:"risky",commandRunConfirm:"risky",runDestination:"active",renderedTabId:null,jobs:[],jobsOpen:false,jobsFilter:"all",jobBlocks:true,dragTabId:null,searchOpen:false,searchQuery:"",searchMatches:[],searchIndex:0,searchRegex:false,searchFilter:false,jobsWatch:null,profiles:[],chainsFolded:{},sizeTimer:null,cols:0,rows:0,cellSize:null,aiPrompting:false,aiWatch:null,layout:"single",ratios:{v:0.5,h:0.5},panes:[],focusPane:0,saved:[],closed:[],rememberOutput:true,sessionsOpen:false,workspace:null,workspaceTimer:null,workspaceRestored:false,lastHiddenPoll:0,paneDrag:null}
// followOutput and pendingOutput belong to a pane now (each pane scrolls on its own). The accessors keep every older
// caller that reads termState.followOutput working against the focused pane.
;["followOutput","pendingOutput"].forEach((key)=>Object.defineProperty(termState,key,{configurable:true,enumerable:true,get(){const pane=termFocusedPane();return pane?pane[key]:(key==="followOutput")},set(value){const pane=termFocusedPane();if(pane)pane[key]=key==="followOutput"?!!value:value}}))
function termFocusedPane(){
return termState.panes[termState.focusPane]||termState.panes[0]||null
}
function termPaneIndexOf(sessionId){
if(!sessionId)return -1
return termState.panes.findIndex((p)=>p.sessionId===sessionId)
}
function termPaneForSession(sessionId){
const i=termPaneIndexOf(sessionId)
return i>=0?termState.panes[i]:null
}
function termOutputEl(){
const pane=termFocusedPane()
return pane?pane.out:document.getElementById("terminalOutput")
}
function termFindTab(id){
return termState.tabs.find((t)=>t.sessionId===id)
}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function termEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function termTabIndex(id){
return termState.tabs.findIndex((t)=>t.sessionId===id)
}
function termStartTabRename(el,tab){
const label=el.querySelector(".terminal-tab-label")
if(!label)return
const input=document.createElement("input")
input.type="text"
input.className="terminal-tab-rename"
input.value=tab.label
label.replaceWith(input)
input.focus()
input.select()
let done=false
function commit(save){
if(done)return
done=true
const value=input.value
input.remove()
if(save&&value.trim())termSetTabLabel(tab,value)
else termRenderTabs()
}
input.addEventListener("keydown",(e)=>{
e.stopPropagation()
if(e.key==="Enter"){e.preventDefault();commit(true)}
else if(e.key==="Escape"){e.preventDefault();commit(false)}
})
input.addEventListener("blur",()=>commit(true))
// The box sits inside the tab <button>: WebKit turns a Space keyup there into a click on the button, which re-activated
// the tab and dropped the edit after the first word. Keep these events inside the input.
;["keyup","keypress","click","mousedown","dblclick"].forEach((type)=>input.addEventListener(type,(e)=>{e.stopPropagation();if(type==="keyup"&&e.key===" ")e.preventDefault()}))
}
function termMoveTab(fromId,toId){
const from=termTabIndex(fromId),to=termTabIndex(toId)
if(from<0||to<0||from===to)return
const [moved]=termState.tabs.splice(from,1)
termState.tabs.splice(to,0,moved)
termRenderTabs()
}
function termCycleTab(step){
if(termState.tabs.length<2)return
const current=termTabIndex(termState.activeId)
const next=(current+step+termState.tabs.length)%termState.tabs.length
termActivateTab(termState.tabs[next].sessionId)
}
function termActivateTabIndex(index){
const tab=termState.tabs[index]
if(tab)termActivateTab(tab.sessionId)
}
// The first click re-renders the strip, so the second click lands on a new element and the browser never sends
// dblclick. Detect the double click by session id and time instead.
let termLastTabClick=null
function termTabDoubleClicked(sessionId,now){
now=now||Date.now()
const hit=!!termLastTabClick&&termLastTabClick.id===sessionId&&now-termLastTabClick.at<450
termLastTabClick=hit?null:{id:sessionId,at:now}
return hit
}
function termRenderTabs(){
const wrap=document.getElementById("terminalTabs")
// Polling re-renders the strip whenever a job finishes; doing that mid-rename would drop the edit box.
if(wrap.querySelector(".terminal-tab-rename")){termRenderPaneHeads();return}
wrap.innerHTML=""
termState.tabs.forEach((t)=>{
const el=document.createElement("button")
el.type="button"
el.draggable=true
el.dataset.id=t.sessionId
const paneAt=termPaneIndexOf(t.sessionId)
el.className="terminal-tab"+(t.sessionId===termState.activeId?" active":"")+(paneAt>=0&&t.sessionId!==termState.activeId?" in-pane":"")+(t.dead?" dead":"")+(t.activeJob?" busy":"")
el.title=t.label+(t.cwd?" - "+t.cwd:"")+(t.activeJob?" - running "+(t.activeJob.command||""):"")+(paneAt>=0&&termState.panes.length>1?" (pane "+(paneAt+1)+")":"")
el.innerHTML=`<span class="terminal-tab-dot"></span><span class="terminal-tab-label">${termEscapeHtml(t.label)}</span>${typeof ReportEvidence!=="undefined"?ReportEvidence.recordingBadgeHtml(t.sessionId):""}<span class="terminal-tab-close" data-id="${t.sessionId}"><i class="icon icon-close"></i></span>`
el.addEventListener("click",(e)=>{if(e.target.closest(".terminal-tab-close"))return;if(termTabDoubleClicked(t.sessionId)){const live=document.querySelector('.terminal-tab[data-id="'+t.sessionId+'"]');if(live)termStartTabRename(live,t);return}termActivateTab(t.sessionId)})
el.addEventListener("auxclick",(e)=>{if(e.button===1){e.preventDefault();termCloseTab(t.sessionId)}})
el.addEventListener("contextmenu",(e)=>{e.preventDefault();termOpenTabMenu(t,e.clientX,e.clientY)})
el.addEventListener("dragstart",(e)=>{termState.dragTabId=t.sessionId;e.dataTransfer.effectAllowed="move"})
el.addEventListener("dragover",(e)=>{e.preventDefault();e.dataTransfer.dropEffect="move"})
el.addEventListener("drop",(e)=>{e.preventDefault();if(termState.dragTabId)termMoveTab(termState.dragTabId,t.sessionId);termState.dragTabId=null})
el.querySelector(".terminal-tab-close").addEventListener("click",(e)=>{e.stopPropagation();termCloseTab(t.sessionId)})
wrap.appendChild(el)
})
const add=document.createElement("button")
add.type="button"
add.id="terminalNewTabBtn"
add.className="terminal-tab-new"
add.title="New session"
add.innerHTML='<i class="icon icon-add"></i>'
add.addEventListener("click",()=>termNewTab())
add.addEventListener("contextmenu",(e)=>{e.preventDefault();termOpenNewSessionMenu(e.clientX,e.clientY)})
add.title="New session (right-click to pick a shell)"
wrap.appendChild(add)
termRenderPaneHeads()
}
function termOpenTabMenu(tab,x,y){
const items=[
{label:"Rename",icon:"edit",fn:()=>{const el=document.querySelector('.terminal-tab[data-id="'+tab.sessionId+'"]');if(el)termStartTabRename(el,tab)}},
{label:"Save session...",icon:"save",disabled:!!tab.elevated,fn:()=>termOpenSaveSessionDialog(tab)},
{label:"Duplicate session",icon:"copy",fn:()=>termNewTab(tab.profileId?"profile:"+tab.profileId:tab.shellId,{cwd:tab.cwd}).catch(()=>{})},
...(typeof ReportEvidence!=="undefined"?ReportEvidence.tabMenuItems(tab):[]),
{sep:true},
{label:"Clear output",icon:"trash",fn:()=>{termActivateTab(tab.sessionId);termClearOutput()}},
{label:"Close session",icon:"close",fn:()=>termCloseTab(tab.sessionId)},
{label:"Close other sessions",icon:"close",disabled:termState.tabs.length<2,fn:()=>termState.tabs.slice().filter((t)=>t.sessionId!==tab.sessionId).forEach((t)=>termCloseTab(t.sessionId))},
{sep:true},
{label:"Reopen closed session",icon:"refresh",disabled:!termState.closed.length,fn:()=>termReopenClosed()}
]
openContextMenu(items,x,y)
}
const TERM_ANSI_SGR_RE=/\x1b\[([0-9;]*)m/g
const TERM_ANSI_OTHER_RE=/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[PX^_].*?\x1b\\|\x1b\[[0-9;?]*[A-Za-ln-z]|\x1b[()*+][0-9A-Za-z]|\x1b[=>NOM78]/g
const TERM_ANSI_SGR_KEEP_RE=/\x1b\[[0-9;]*m/g
const TERM_REDRAW_RE=/\r*\x1b\[(\d*)A(?:\x1b\[[0-9;]*m)*\r*\x1b\[0?J/
function termApplyRedraw(text){
let out=text
for(let guard=0;guard<200;guard++){
const match=TERM_REDRAW_RE.exec(out)
if(!match)break
const up=Math.max(1,parseInt(match[1]||"1",10)||1)
let head=out.slice(0,match.index)
for(let step=0;step<=up;step++){
const cut=head.lastIndexOf("\n")
head=cut<0?"":head.slice(0,cut)
}
out=(head?head+"\n":"")+out.slice(match.index+match[0].length)
}
return out
}
function termApplyCarriageReturns(text){
if(text.indexOf("\r")<0)return text
return text.replace(/\r\n/g,"\n").split("\n").map((line)=>{
const cut=line.lastIndexOf("\r")
if(cut<0)return line
const carried=line.slice(0,cut).match(TERM_ANSI_SGR_KEEP_RE)
return (carried?carried.join(""):"")+line.slice(cut+1)
}).join("\n")
}
const TERM_ANSI_CODE_CLASS={
30:"ansi-fg-black",31:"ansi-fg-red",32:"ansi-fg-green",33:"ansi-fg-yellow",34:"ansi-fg-blue",35:"ansi-fg-magenta",36:"ansi-fg-cyan",37:"ansi-fg-white",
90:"ansi-fg-brblack",91:"ansi-fg-brred",92:"ansi-fg-brgreen",93:"ansi-fg-bryellow",94:"ansi-fg-brblue",95:"ansi-fg-brmagenta",96:"ansi-fg-brcyan",97:"ansi-fg-brwhite",
40:"ansi-bg-black",41:"ansi-bg-red",42:"ansi-bg-green",43:"ansi-bg-yellow",44:"ansi-bg-blue",45:"ansi-bg-magenta",46:"ansi-bg-cyan",47:"ansi-bg-white",
100:"ansi-bg-brblack",101:"ansi-bg-brred",102:"ansi-bg-brgreen",103:"ansi-bg-bryellow",104:"ansi-bg-brblue",105:"ansi-bg-brmagenta",106:"ansi-bg-brcyan",107:"ansi-bg-brwhite",
}
const TERM_IOC_RULES=[
{kind:"url",label:"URL",re:/\bhttps?:\/\/[^\s<>"']+/g},
{kind:"cidr",label:"CIDR",re:/\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\/(?:3[0-2]|[12]?\d)\b/g},
{kind:"hostport",label:"Host:Port",re:/\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d):\d{1,5}\b/g},
{kind:"ip",label:"IPv4",re:/\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/g},
{kind:"mac",label:"MAC",re:/\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b/gi},
{kind:"ipv6",label:"IPv6",re:/\b(?:[0-9a-f]{1,4}:){1,7}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,6})?|\b(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}\b/gi},
{kind:"cve",label:"CVE",re:/\bCVE-\d{4}-\d{4,7}\b/gi},
{kind:"sha256",label:"SHA256",re:/\b[0-9a-f]{64}\b/gi},
{kind:"sha1",label:"SHA1",re:/\b[0-9a-f]{40}\b/gi},
{kind:"md5",label:"MD5",re:/\b[0-9a-f]{32}\b/gi},
{kind:"email",label:"Email",re:/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g},
{kind:"domain",label:"Domain",re:/\b(?!(?:\d{1,3}\.){3}\d{1,3}\b)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|dev|local|gov|edu|co|uk|de|fr|ru|cn|info|biz|xyz|internal|lan|htb)\b/gi},
{kind:"unc",label:"UNC Path",re:/\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9._$-]+/g}
]
const TERM_IOC_TARGET_KEY={url:"URL",ip:"IPv4",ipv6:"IPv6",domain:"DOMAIN",hostport:"HOSTPORT",cidr:"CIDR",mac:"MAC",email:"EMAIL",cve:"CVE",md5:"MD5",sha1:"SHA1",sha256:"SHA256",unc:"UNC"}
function termSearchHitHtml(text,hits){
let result=""
let cursor=0
hits.sort((a,b)=>a.start-b.start).forEach((hit)=>{
if(hit.start<cursor)return
if(hit.start>cursor)result+=termEscapeHtml(text.slice(cursor,hit.start))
result+='<span class="term-search-hit'+(hit.current?" current":"")+'">'+termEscapeHtml(text.slice(hit.start,hit.end))+"</span>"
cursor=hit.end
})
result+=termEscapeHtml(text.slice(cursor))
return result
}
function termScanIocs(raw){
const matches=[]
TERM_IOC_RULES.forEach((rule)=>{
rule.re.lastIndex=0
let m
while((m=rule.re.exec(raw))!==null){
const start=m.index,end=m.index+m[0].length
if(m[0].length===0){rule.re.lastIndex++;continue}
if(matches.some((x)=>start<x.end&&end>x.start))continue
matches.push({start,end,kind:rule.kind,value:m[0]})
}
})
return matches.sort((a,b)=>a.start-b.start)
}
function termEscapeAndHighlight(raw,sliceStart){
if(!raw)return ""
if(termState.searchQuery&&sliceStart!==undefined){
const hits=termApplySearchHighlight(raw,sliceStart)
if(hits)return termSearchHitHtml(raw,hits)
}
const matches=termScanIocs(raw)
if(!matches.length)return termEscapeHtml(raw)
matches.sort((a,b)=>a.start-b.start)
let result=""
let cursor=0
matches.forEach((mt)=>{
if(mt.start>cursor)result+=termEscapeHtml(raw.slice(cursor,mt.start))
const esc=termEscapeHtml(mt.value)
result+=`<span class="term-ioc" data-kind="${mt.kind}" data-value="${esc}">${esc}</span>`
cursor=mt.end
})
result+=termEscapeHtml(raw.slice(cursor))
return result
}
function termAnsiRenderChunk(raw,carryClasses,sliceStart){
const text=termApplyCarriageReturns((raw||"").replace(TERM_ANSI_OTHER_RE,""))
let result=""
let activeClasses=(carryClasses||[]).slice()
let spanOpen=false
let cursor=0
let match
function closeSpan(){if(spanOpen){result+="</span>";spanOpen=false}}
function openSpanIfNeeded(){
if(activeClasses.length){result+=`<span class="${activeClasses.join(" ")}">`;spanOpen=true}
}
openSpanIfNeeded()
TERM_ANSI_SGR_RE.lastIndex=0
while((match=TERM_ANSI_SGR_RE.exec(text))!==null){
const chunk=text.slice(cursor,match.index)
if(chunk)result+=termEscapeAndHighlight(chunk,sliceStart===undefined?undefined:sliceStart+cursor)
cursor=TERM_ANSI_SGR_RE.lastIndex
const parts=(match[1]||"").split(";").filter((c)=>c!=="")
const nums=parts.length?parts.map((c)=>parseInt(c,10)):[0]
closeSpan()
nums.forEach((n)=>{
if(isNaN(n)||n===0){activeClasses=[]}
else if(n===1){if(!activeClasses.includes("ansi-bold"))activeClasses.push("ansi-bold")}
else if(n===2){if(!activeClasses.includes("ansi-dim"))activeClasses.push("ansi-dim")}
else if(n===3){if(!activeClasses.includes("ansi-italic"))activeClasses.push("ansi-italic")}
else if(n===4){if(!activeClasses.includes("ansi-underline"))activeClasses.push("ansi-underline")}
else if(n===22){activeClasses=activeClasses.filter((c)=>c!=="ansi-bold"&&c!=="ansi-dim")}
else if(n===23){activeClasses=activeClasses.filter((c)=>c!=="ansi-italic")}
else if(n===24){activeClasses=activeClasses.filter((c)=>c!=="ansi-underline")}
else if(n===39){activeClasses=activeClasses.filter((c)=>!c.startsWith("ansi-fg-"))}
else if(n===49){activeClasses=activeClasses.filter((c)=>!c.startsWith("ansi-bg-"))}
else if(TERM_ANSI_CODE_CLASS[n]){
const isBg=(n>=40&&n<=47)||(n>=100&&n<=107)
activeClasses=activeClasses.filter((c)=>isBg?!c.startsWith("ansi-bg-"):!c.startsWith("ansi-fg-"))
activeClasses.push(TERM_ANSI_CODE_CLASS[n])
}
})
openSpanIfNeeded()
}
const rest=text.slice(cursor)
if(rest)result+=termEscapeAndHighlight(rest,sliceStart===undefined?undefined:sliceStart+cursor)
closeSpan()
return {html:result,classes:activeClasses}
}
function termAnsiToHtml(raw){
return termAnsiRenderChunk(raw,[]).html
}
const TERM_JOB_TOKEN="__LOYA_JOB__"
const TERM_JOB_END="__END__"
const TERM_JOB_RESULT_RE=/__LOYA_JOB__([0-9a-z]+)\|(-?\d+)\|([^|\r\n]*)__END__\r?\n?/g
const TERM_JOB_ECHO_RE={cmd:/\s*&call echo __LOYA_JOB__[^\r\n]*/g,powershell:/\s*;\$LoyaOk=\$\?;Write-Output "__LOYA_JOB__[^\r\n]*/g,posix:/\s*;?printf '__LOYA_JOB__[^\r\n]*/g}
const TERM_JOB_ECHO_START={cmd:" &call echo ",powershell:' ;$LoyaOk=$?;Write-Output "',posix:" ;printf '"}
const TERM_JOB_FALLBACK_TICKS=60
function termShellFamily(shellId){
if(shellId==="powershell"||shellId==="pwsh")return "powershell"
if(shellId==="cmd")return "cmd"
return "posix"
}
function termSubmitNewline(shellId){
const family=termShellFamily(shellId)
if(family==="posix")return "\n"
// PowerShell on Linux runs in a PTY: CR is Enter there, and CRLF would submit a second, empty line.
if(family==="powershell"&&typeof termState!=="undefined"&&termState.platform==="linux")return "\r"
return "\r\n"
}
// The line sent for a job: the command plus its hidden end marker (POSIX: see termPosixJobLine; an open line goes without
// it and the next submitted line continues the same job).
function termJobPayload(tab,text,jobId){
const epilogue=termJobEpilogue(tab.shellId,jobId)
if(termShellFamily(tab.shellId)!=="posix")return text+epilogue
const job=termPosixJobLine(text,epilogue)
tab.continuation=job.open?{jobId,text}:null
return job.line
}
function termNewJobId(){
return "j"+Math.random().toString(36).slice(2,10)
}
function termJobEpilogue(shellId,jobId){
const family=termShellFamily(shellId)
if(family==="cmd")return " &call echo "+TERM_JOB_TOKEN+jobId+"^|%^ERRORLEVEL%^|%^CD%"+TERM_JOB_END
if(family==="powershell")return ' ;$LoyaOk=$?;Write-Output "'+TERM_JOB_TOKEN+jobId+'|$(if($LoyaOk){0}elseif($LASTEXITCODE){$LASTEXITCODE}else{1})|$($PWD.Path)'+TERM_JOB_END+'"'
return " ;printf '"+TERM_JOB_TOKEN+"%s|%s|%s"+TERM_JOB_END+"\\n' '"+jobId+"' \"$?\" \"$PWD\""
}
function termExtractJobResults(text){
const out=[]
TERM_JOB_RESULT_RE.lastIndex=0
let m
while((m=TERM_JOB_RESULT_RE.exec(text))!==null)out.push({jobId:m[1],exitCode:parseInt(m[2],10),cwd:m[3]})
return out
}
function termStripJobMarkers(text,shellId){
let out=String(text||"").replace(TERM_JOB_RESULT_RE,"")
const echoRe=TERM_JOB_ECHO_RE[termShellFamily(shellId)]
if(echoRe){echoRe.lastIndex=0;out=out.replace(echoRe,"")}
return out
}
function termTrimTrailingPrefixOf(text,token){
const max=Math.min(token.length-1,text.length)
for(let n=max;n>0;n--){if(text.endsWith(token.slice(0,n)))return text.slice(0,text.length-n)}
return text
}
function termStripPartialMarker(text,shellId){
const cleaned=termStripJobMarkers(text,shellId)
const tokenAt=cleaned.indexOf(TERM_JOB_TOKEN)
if(tokenAt>=0)return cleaned.slice(0,tokenAt)
const start=TERM_JOB_ECHO_START[termShellFamily(shellId)]
const startAt=cleaned.lastIndexOf(start)
if(startAt>=0&&cleaned.length-startAt<=start.length+TERM_JOB_TOKEN.length)return cleaned.slice(0,startAt)
return termTrimTrailingPrefixOf(termTrimTrailingPrefixOf(cleaned,TERM_JOB_TOKEN),start)
}
// A partial job marker can only be streaming while a job is in flight. Hiding marker prefixes at other times
// swallowed the trailing space of every shell prompt ("└─$ " rendered as "└─$"), since " " starts " ;printf '".
function termPendingVisible(tab){
const raw=tab.pendingRaw||""
if(termShellFamily(tab.shellId)==="posix"&&(termJobEchoPending(tab)||TERM_LINE_EDIT_RE.test(raw)))return termCleanPosixLine(raw,tab.shellId,tab.cols,!!tab.activeJob).text
return tab.activeJob?termStripPartialMarker(raw,tab.shellId):termStripJobMarkers(raw,tab.shellId)
}
// ---- POSIX line editors (zsh ZLE with syntax highlighting / autosuggestions, bash readline). They echo the typed line and
// then repaint it with backspaces, cursor moves and colours, and wrap it at the right margin with " \r" instead of a newline,
// so the hidden job epilogue is never one plain run of text. Replaying the moves on one logical line gives what a real terminal
// shows; the epilogue is then cut off by position, never matched from the raw echo. Lines without these moves are untouched.
const TERM_LINE_EDIT_RE=/\x08|\x1b\[\d*[CDG]|[^\r\n]\r\x1b\[K/
const TERM_EMU_SEQ_RE=/\x1b(?:\[([0-9;?:>=!]*)[ -\/]*([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[PX^_][\s\S]*?(?:\x1b\\|$)|[()*+#%][\s\S]?|[\s\S]?)/y
const TERM_EMU_REDRAW_RE=/\r*\x1b\[\d*A(?:\x1b\[[0-9;]*m)*\r*\x1b\[0?J/g
function termCharWidth(cp){
if((cp>=0x300&&cp<=0x36f)||(cp>=0x200b&&cp<=0x200f)||cp===0xfe0f||cp===0x20e3)return 0
if(cp<0x1100)return 1
if(cp<=0x115f||(cp>=0x2e80&&cp<=0xa4cf&&cp!==0x303f)||(cp>=0xac00&&cp<=0xd7a3)||(cp>=0xf900&&cp<=0xfaff)||(cp>=0xfe30&&cp<=0xfe4f)||(cp>=0xff00&&cp<=0xff60)||(cp>=0xffe0&&cp<=0xffe6)||(cp>=0x1f300&&cp<=0x1f64f)||(cp>=0x1f900&&cp<=0x1f9ff)||(cp>=0x20000&&cp<=0x3fffd))return 2
return 1
}
function termSgrAppend(sgr,params){
if(/^0*$/.test(params))return ""
if(/^0+;/.test(params))return "\x1b["+params+"m"
return (sgr+"\x1b["+params+"m").match(/\x1b\[[0-9;:]*m/g).slice(-8).join("")
}
// One logical line (no LF) on a screen `cols` wide -> {cells:[{ch,sgr}], plain, sgr (the colour state at the end)}.
function termEmulateLine(raw,cols){
const W=cols>=20?cols:80
const text=String(raw||"")
const rows=[[]]
let row=0,col=0,wrap=false,sgr="",i=0
while(i<text.length){
const c=text.charCodeAt(i)
if(c===27){
TERM_EMU_SEQ_RE.lastIndex=i
const m=TERM_EMU_SEQ_RE.exec(text)
const len=m&&m[0].length?m[0].length:1
if(m&&m[2]){
const params=m[1]||"",f=m[2],n=Math.max(1,parseInt(params,10)||1),mode=parseInt(params,10)||0,r=rows[row]
if(f==="m"){if(!/[?>=]/.test(params))sgr=termSgrAppend(sgr,params)}
else if(params.charAt(0)!=="?"&&params.charAt(0)!==">"){
if(f==="D"){col=Math.max(0,col-n);wrap=false}
else if(f==="C"){col=Math.min(W-1,col+n);wrap=false}
else if(f==="G"){col=Math.min(W-1,n-1);wrap=false}
else if(f==="A"){row=Math.max(0,row-n);wrap=false}
else if(f==="B"){row+=n;wrap=false;while(rows.length<=row)rows.push([])}
else if(f==="K"){if(mode===0)r.length=Math.min(r.length,col);else if(mode===1){for(let k=0;k<=col&&k<r.length;k++)r[k]=undefined}else r.length=0}
else if(f==="J"){if(mode===0){r.length=Math.min(r.length,col);rows.length=row+1}}
else if(f==="P"){r.splice(col,n)}
else if(f==="X"){for(let k=col;k<col+n&&k<r.length;k++)r[k]=undefined}
else if(f==="@"){if(col<r.length){r.splice(col,0,...new Array(n));if(r.length>W)r.length=W}}
}
}
i+=len
continue
}
if(c===13){col=0;wrap=false;i++;continue}
if(c===8){col=Math.max(0,col-1);wrap=false;i++;continue}
if(c===9){col=Math.min(W-1,(Math.floor(col/8)+1)*8);i++;continue}
if(c<32||c===127){i++;continue}
const cp=text.codePointAt(i)
const ch=String.fromCodePoint(cp)
i+=ch.length
const w=termCharWidth(cp)
if(w===0){const prev=rows[row][wrap?col:col-1];if(prev)prev.ch+=ch;continue}
if(wrap||(w===2&&col===W-1)){row++;col=0;wrap=false;while(rows.length<=row)rows.push([])}
const r=rows[row]
r[col]={ch,sgr}
if(w===2)r[col+1]={ch:"",sgr}
col+=w
if(col>=W){col=W-1;wrap=true}
}
const cells=[]
rows.forEach((r)=>{for(let k=0;k<r.length;k++){const cell=r[k];if(!cell)cells.push({ch:" ",sgr:""});else if(cell.ch)cells.push(cell)}})
return {cells,plain:cells.map((cell)=>cell.ch).join(""),sgr}
}
function termSerializeCells(em,count,withTail){
let out="",cur=""
for(let k=0;k<count&&k<em.cells.length;k++){const cell=em.cells[k];if(cell.sgr!==cur){out+="\x1b[0m"+cell.sgr;cur=cell.sgr}out+=cell.ch}
if(withTail&&em.sgr!==cur)out+="\x1b[0m"+em.sgr
return out
}
function termCellsForLength(em,length){
let used=0,k=0
while(k<em.cells.length&&used<length){used+=em.cells[k].ch.length;k++}
return k
}
// -> {text, em, head}. head is a prompt redraw (cursor up + erase) left in place for termApplyRedraw.
function termCleanPosixLine(line,shellId,cols,partial){
let head="",body=String(line||"")
TERM_EMU_REDRAW_RE.lastIndex=0
let m,cut=-1
while((m=TERM_EMU_REDRAW_RE.exec(body))!==null)cut=m.index+m[0].length
if(cut>=0){head=body.slice(0,cut);body=body.slice(cut)}
const em=termEmulateLine(body,cols)
const kept=partial?termStripPartialMarker(em.plain,shellId):termStripJobMarkers(em.plain,shellId)
if(em.plain.indexOf(kept)===0)return {text:head+termSerializeCells(em,termCellsForLength(em,kept.length),true),em,head,markerOnly:!kept.trim()&&termExtractJobResults(em.plain).length>0}
return {text:head+termStripJobMarkers(termSerializeCells(em,em.cells.length,true),shellId),em,head,markerOnly:false}
}
// A job's input echo is still arriving: from the submit until the line that carries the epilogue echo has ended.
function termJobEchoPending(tab){
const job=tab.activeJob
return !!(job&&!job.echoDone)
}
// Before the first output after a submit, the pending line is the prompt the command was typed at: remember its width (to
// anchor the job block after it) and its text (to notice the prompt coming back when the end marker never ran).
function termNoteJobPrompt(tab){
const job=tab.activeJob
if(!job||job.promptCells!==undefined||termShellFamily(tab.shellId)!=="posix")return
const em=termEmulateLine(tab.pendingRaw||"",tab.cols)
job.promptCells=em.cells.length
// After "Clear output" the prompt line is gone from the panel until the shell prints a new one: use the last one seen.
job.promptPlain=em.plain.replace(/\s+$/,"")||tab.lastPromptPlain||""
if(job.promptPlain)tab.lastPromptPlain=job.promptPlain
job.echoLines=0
}
// The complete lines of one output chunk, cleaned for display. POSIX shells replay line edits (always for a job's echo
// lines), re-anchor the job block at the typed command, and note where the command's own output starts and ends.
function termCleanComplete(tab,complete){
if(termShellFamily(tab.shellId)!=="posix")return termStripJobMarkers(complete,tab.shellId)
const base=(tab.visible||"").length
let out=""
;(complete.match(/[^\n]*\n|[^\n]+$/g)||[]).forEach((piece)=>{
const nl=piece.endsWith("\n")
const line=nl?piece.slice(0,-1):piece
const job=tab.activeJob
const echo=!!(job&&!job.echoDone)
if(!echo&&!TERM_LINE_EDIT_RE.test(line)){
if(job&&job.echoDone&&job.outputEnd===undefined&&termExtractJobResults(piece).some((r)=>r.jobId===job.jobId))termMarkJobOutput(tab,job,"outputEnd",base+out.length+termStripJobMarkers(piece.slice(0,piece.indexOf(TERM_JOB_TOKEN)),tab.shellId).length)
out+=termStripJobMarkers(piece,tab.shellId)
return
}
const res=termCleanPosixLine(line,tab.shellId,tab.cols,false)
if(echo){
if(job.echoLines===0&&job.promptCells!==undefined){
const anchor=base+out.length+res.head.length+termSerializeCells(res.em,Math.min(job.promptCells,res.em.cells.length),false).length
termMarkJobOutput(tab,job,"startIdx",anchor)
}
job.echoLines=(job.echoLines||0)+1
if(res.em.plain.indexOf(TERM_JOB_TOKEN+"%s")>=0||res.em.plain.indexOf(TERM_JOB_TOKEN+job.jobId)>=0||job.echoLines>200){
job.echoDone=true
termMarkJobOutput(tab,job,"outputStart",base+out.length+res.text.length+(nl?1:0))
}
}
if(res.markerOnly)return
out+=res.text+(nl?"\n":"")
})
return out
}
// Moves a job's block start (startIdx) or records where its own output starts / ends, on every copy of the job.
function termMarkJobOutput(tab,job,key,at){
job[key]=at
const record=(tab.jobHistory||[]).find((j)=>j.jobId===job.jobId)
if(record&&key==="startIdx")record.startIdx=at
const capture=tab.pendingCapture
if(capture&&capture.jobId===job.jobId)capture[key]=at
}
// The end marker never runs when the shell rejects the line (syntax error) or when Ctrl+C aborts it. Then the prompt the
// command was typed at comes back with no marker: close the job with the status the shell itself would report.
const TERM_SHELL_DIAG_RE=/(?:^|\n)\s*(-?(?:ba|z|da|k|mk|)sh)(?::| \d+:| line \d+:) /
function termCheckPromptReturn(tab){
const job=tab.activeJob
if(!job||!job.promptPlain||!job.echoLines||termShellFamily(tab.shellId)!=="posix")return false
if(termEmulateLine(tab.pendingRaw||"",tab.cols).plain.replace(/\s+$/,"")!==job.promptPlain)return false
let exitCode=null
if(job.interrupted)exitCode=130
else{
const since=String(tab.visible||"").slice(Math.max(0,job.startIdx||0)).replace(TERM_ANSI_SGR_RE,"").replace(TERM_ANSI_OTHER_RE,"")
const diag=TERM_SHELL_DIAG_RE.exec(since)
if(!diag)return false
exitCode=/^-?zsh$/i.test(diag[1])?1:2
}
if(job.outputEnd===undefined)termMarkJobOutput(tab,job,"outputEnd",(tab.visible||"").length)
// The command never ran, so its output is no listing (an "ls )" would otherwise list the error words).
if(tab.pendingCapture&&tab.pendingCapture.jobId===job.jobId)tab.pendingCapture.kind=null
tab.continuation=null
termResolveJob(tab,{jobId:job.jobId,exitCode,cwd:tab.cwd||""})
return true
}
// The shell state at the end of a POSIX command line: open (an unclosed quote, "$(" or a trailing "\" - the shell would
// wait for more lines and swallow an appended end marker) and where a trailing "# comment" starts on the last line.
function termPosixLineState(text){
const s=String(text||"")
let state=0,depth=0,commentAt=-1,i=0
while(i<s.length){
const ch=s[i]
if(state===0){
if(ch==="\\"){if(i+1>=s.length)return {open:true,commentAt};i+=2;continue}
if(ch==="\n"){commentAt=-1;i++;continue}
if(ch==="'")state=1
else if(ch==="\"")state=2
else if(ch==="`")state=3
else if(ch==="$"&&s[i+1]==="'"){state=4;i++}
else if(ch==="(")depth++
else if(ch===")"&&depth>0)depth--
else if(ch==="#"&&(i===0||/[\s;&|()<>]/.test(s[i-1]))){const end=s.indexOf("\n",i);if(end<0){commentAt=i;break}i=end;continue}
}else if(state===1){if(ch==="'")state=0}
else if(ch==="\\"){i+=2;continue}
else if((state===2&&ch==="\"")||(state===3&&ch==="`")||(state===4&&ch==="'"))state=0
i++
}
return {open:state!==0||depth>0,commentAt}
}
// What to send for a POSIX job so its end marker runs: a trailing comment would swallow it, and after a trailing ";" or "&"
// the marker's own ";" would be a syntax error. -> {line, open}; open lines go without the marker (see termPosixLineState).
function termPosixJobLine(text,epilogue){
const st=termPosixLineState(text)
if(st.open)return {line:text,open:true}
let line=(st.commentAt>=0?text.slice(0,st.commentAt):text).replace(/[ \t]+$/,"")
if(/(^|\n)$/.test(line)||/(^|[^\\&;]);$/.test(line))line=line.replace(/;$/,"")
let tail=epilogue
if(/(^|\n)\s*$/.test(line)||/(^|[^\\&|>])&$/.test(line))tail=epilogue.replace(/^ ;/," ")
return {line:line+tail,open:false}
}
function termExitLabel(code){
if(code===null||code===undefined)return ""
return code===0?"exit 0":"exit "+code
}
function termUpdateStatusBar(){
const tab=termFindTab(termState.activeId)
const shellEl=document.getElementById("terminalStatusShell")
if(!shellEl)return
const cwdEl=document.getElementById("terminalStatusCwd")
const exitEl=document.getElementById("terminalStatusExit")
if(!tab){shellEl.textContent="";cwdEl.textContent="";exitEl.classList.add("hidden");return}
const shell=termState.shells.find((x)=>x.id===tab.shellId)
shellEl.textContent=(tab.elevated?"Elevated ":"")+(shell?shell.label:tab.shellId)
cwdEl.textContent=termCwdDisplay(tab.cwd)
cwdEl.title=tab.cwd||""
const label=tab.activeJob?"running":termExitLabel(tab.lastExitCode)
exitEl.textContent=label
exitEl.classList.toggle("hidden",!label)
exitEl.classList.toggle("bad",!tab.activeJob&&tab.lastExitCode!==null&&tab.lastExitCode!==0)
exitEl.classList.toggle("busy",!!tab.activeJob)
}
function termFinalizeCapture(tab,jobId){
const capture=tab.pendingCapture
if(!capture||(jobId&&capture.jobId!==jobId)){return}
tab.pendingCapture=null
if(!capture.kind)return
// POSIX jobs know where their own output starts and ends (after the echoed command line, before the next prompt).
const captured=capture.outputStart!==undefined?tab.buffer.slice(capture.outputStart,capture.outputEnd!==undefined?capture.outputEnd:undefined):tab.buffer.slice(capture.startIdx)
const rows=termParseListing(capture.kind,capture.long,capture.outputStart!==undefined?captured.replace(TERM_ANSI_SGR_RE,"").replace(TERM_ANSI_OTHER_RE,""):captured)
if(!rows||!rows.length)return
if(!tab.listings)tab.listings=[]
tab.listings.push({id:"lst"+Math.random().toString(36).slice(2,9),startIdx:capture.startIdx,endIdx:capture.outputEnd!==undefined?capture.outputEnd:tab.buffer.length,kind:capture.kind,rows,rawText:captured,showRaw:false})
termInvalidateRender(tab)
termRenderSession(tab.sessionId)
}
function termRecordJobStart(tab,job,source){
if(!tab||!job)return
bridgeCall("terminal.job_start",[job.jobId,tab.sessionId,job.command,source||"terminal"]).catch(()=>{})
}
function termRecordJobFinish(tab,job,result){
const bytes=job&&job.startIdx!==null&&job.endIdx!==null?Math.max(0,job.endIdx-job.startIdx):0
bridgeCall("terminal.job_finish",[result.jobId,result.exitCode,result.cwd||"",bytes,""]).catch(()=>{})
}
function termResolveJob(tab,result){
if(tab.continuation&&tab.continuation.jobId===result.jobId)tab.continuation=null
tab.lastExitCode=result.exitCode
if(result.cwd&&result.cwd!==tab.cwd){tab.cwd=result.cwd;if(termPaneIndexOf(tab.sessionId)>=0)termSaveWorkspaceSoon()}
const job=tab.activeJob
if(job&&job.jobId===result.jobId){
job.exitCode=result.exitCode
job.endedAt=Date.now()
job.endIdx=tab.buffer.length
tab.activeJob=null
termRecordJobFinish(tab,job,result)
termCloseJobOffset(tab,job.jobId,job.endIdx,result.exitCode)
if(termState.jobsOpen)termRefreshJobs()
termRenderTabs()
termFinalizeCapture(tab,job.jobId)
}else{
termRecordJobFinish(tab,null,result)
}
if(tab.sessionId===termState.activeId)termUpdateStatusBar()
}
function termHumanSize(n){
if(n===null||n===undefined||isNaN(n))return ""
if(n<1024)return n+" B"
const units=["KB","MB","GB","TB"]
let v=n,i=-1
do{v/=1024;i++}while(v>=1024&&i<units.length-1)
return v.toFixed(v<10?1:0)+" "+units[i]
}
function termDetectListingCommand(cmdText,shellId){
const t=(cmdText||"").trim()
const bare=t.replace(/^(?:sudo|doas)\s+/i,"")
if(/^\S*nmap\b/i.test(bare))return {kind:"nmap",long:false}
if(/^(tasklist|ps|get-process|gps)\b/i.test(bare))return {kind:"process",long:false}
if(/^(netstat|ss|get-nettcpconnection)\b/i.test(bare))return {kind:"connection",long:false}
if(shellId==="powershell"||shellId==="pwsh"){
if(/^(ls|dir|gci|get-childitem)\b/i.test(bare))return {kind:"powershell",long:true}
return null
}
const lsMatch=/^ls\b(.*)$/.exec(bare)
if(lsMatch){
const flags=lsMatch[1]||""
const long=/(^|\s)-\w*l\w*(\s|$)/.test(flags)
return {kind:"ls",long}
}
if(/^dir\b/i.test(bare))return {kind:"dir",long:true}
return null
}
const TERM_LS_LONG_RE=/^([dl\-])([r\-][w\-][xsS\-])([r\-][w\-][xsS\-])([r\-][w\-][xtT\-])\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+([A-Za-z]{3}\s+\d{1,2}\s+[\d:]+)\s+(.+)$/
function termParseLsLong(text){
const rows=[]
text.split(/\r?\n/).forEach((line)=>{
const m=TERM_LS_LONG_RE.exec(line.trim())
if(!m)return
const type=m[1]==="d"?"dir":m[1]==="l"?"symlink":"file"
let name=m[10]
if(type==="symlink"){const arrow=name.indexOf(" -> ");if(arrow>=0)name=name.slice(0,arrow)}
const size=parseInt(m[8],10)
rows.push({type,perms:m[1]+m[2]+m[3]+m[4],owner:m[6],group:m[7],size,sizeLabel:type==="dir"?"":termHumanSize(size),date:m[9],name})
})
return rows.length?rows:null
}
function termParseLsPlain(text){
const names=text.split(/\s+/).map((s)=>s.trim()).filter(Boolean)
if(!names.length)return null
return names.map((name)=>({type:"unknown",name}))
}
const TERM_DIR_RE=/^(\d{2}\/\d{2}\/\d{4})\s+(\d{2}:\d{2}\s*[AP]M)\s+(<DIR>|[\d,]+)\s+(.+)$/
function termParseDir(text){
const rows=[]
text.split(/\r?\n/).forEach((line)=>{
const m=TERM_DIR_RE.exec(line.trim())
if(!m)return
const name=m[4].trim()
if(name==="."||name==="..")return
const isDir=m[3]==="<DIR>"
rows.push({type:isDir?"dir":"file",size:isDir?null:parseInt(m[3].replace(/,/g,""),10),sizeLabel:isDir?"":termHumanSize(parseInt(m[3].replace(/,/g,""),10)),date:m[1]+" "+m[2],name})
})
return rows.length?rows:null
}
function termParsePowerShellTable(text){
const lines=text.split(/\r?\n/)
let dashIdx=-1
for(let i=1;i<lines.length;i++){
if(/^-+(\s+-+)+\s*$/.test(lines[i].trim())){dashIdx=i;break}
}
if(dashIdx<1)return null
const dashLine=lines[dashIdx]
const headerLine=lines[dashIdx-1]
const spans=[]
const re=/-+/g
let m
while((m=re.exec(dashLine))!==null)spans.push([m.index,m.index+m[0].length])
if(spans.length<2)return null
spans[spans.length-1][1]=Infinity
const headers=spans.map(([s,e])=>headerLine.slice(s,e===Infinity?headerLine.length:e).trim().toLowerCase())
const rows=[]
for(let i=dashIdx+1;i<lines.length;i++){
const line=lines[i]
if(!line.trim())continue
const cells=spans.map(([s,e])=>line.slice(s,e===Infinity?line.length:e).trim())
if(cells.every((c)=>!c))continue
rows.push(cells)
}
if(!rows.length)return null
return {headers,rows}
}
function termParsePowerShellListing(text){
const table=termParsePowerShellTable(text)
if(!table)return null
const hIdx={}
table.headers.forEach((h,i)=>{if(!(h in hIdx))hIdx[h]=i})
if(!("name" in hIdx))return null
const rows=table.rows.map((cells)=>{
const name=(cells[hIdx.name]||"").trim()
const mode="mode" in hIdx?cells[hIdx.mode]:""
const lengthRaw="length" in hIdx?cells[hIdx.length]:""
const date="lastwritetime" in hIdx?cells[hIdx.lastwritetime]:""
const isDir=/^d/i.test(mode)
const sizeNum=lengthRaw?parseInt(lengthRaw.replace(/,/g,""),10):NaN
return {type:isDir?"dir":"file",size:isDir||isNaN(sizeNum)?null:sizeNum,sizeLabel:isDir||isNaN(sizeNum)?"":termHumanSize(sizeNum),perms:mode,date,name}
}).filter((r)=>r.name&&r.name!=="."&&r.name!=="..")
return rows.length?rows:null
}
const TERM_TABLE_KINDS={
nmap:{label:"Ports",columns:[{key:"port",label:"Port"},{key:"state",label:"State"},{key:"service",label:"Service"},{key:"version",label:"Version"}]},
process:{label:"Processes",columns:[{key:"pid",label:"PID"},{key:"name",label:"Name"},{key:"memory",label:"Memory"},{key:"user",label:"User"}]},
connection:{label:"Connections",columns:[{key:"proto",label:"Proto"},{key:"local",label:"Local"},{key:"remote",label:"Remote"},{key:"state",label:"State"},{key:"pid",label:"PID"}]},
}
const TERM_NMAP_PORT_RE=/^(\d{1,5}\/(?:tcp|udp|sctp))\s+(open|closed|filtered|unfiltered|open\|filtered|closed\|filtered)\s*(\S*)\s*(.*)$/i
function termParseNmap(text){
const rows=[]
text.split(/\r?\n/).forEach((line)=>{
const match=TERM_NMAP_PORT_RE.exec(line.trim())
if(!match)return
rows.push({port:match[1],state:match[2].toLowerCase(),service:match[3]||"",version:(match[4]||"").trim()})
})
return rows.length?rows:null
}
const TERM_TASKLIST_RE=/^(.+?)\s{2,}(\d+)\s+(\S+)\s+(\d+)\s+([\d,]+\s*K)$/
function termParseTasklist(text){
const rows=[]
text.split(/\r?\n/).forEach((line)=>{
const match=TERM_TASKLIST_RE.exec(line.trim())
if(!match)return
rows.push({pid:match[2],name:match[1].trim(),memory:match[5].replace(/\s+/g," ").trim(),user:match[3]})
})
return rows.length?rows:null
}
function termParsePs(text){
const lines=text.split(/\r?\n/).map((line)=>line.trim()).filter(Boolean)
if(!lines.length)return null
const header=lines[0].split(/\s+/).map((part)=>part.toUpperCase())
const pidIndex=header.indexOf("PID")
if(pidIndex<0)return null
const userIndex=header.indexOf("USER")
const memIndex=header.indexOf("%MEM")
const rows=[]
lines.slice(1).forEach((line)=>{
const parts=line.split(/\s+/)
if(parts.length<=pidIndex)return
if(!/^\d+$/.test(parts[pidIndex]))return
rows.push({pid:parts[pidIndex],name:parts.slice(header.length-1).join(" ")||parts[parts.length-1],memory:memIndex>=0?parts[memIndex]:"",user:userIndex>=0?parts[userIndex]:""})
})
return rows.length?rows:null
}
const TERM_NETSTAT_WIN_RE=/^(TCP|UDP)\s+(\S+)\s+(\S+)\s*(LISTENING|ESTABLISHED|TIME_WAIT|CLOSE_WAIT|SYN_SENT|SYN_RECV|FIN_WAIT_1|FIN_WAIT_2|LAST_ACK|CLOSING|\*:\*)?\s*(\d+)?$/i
function termParseNetstat(text){
const rows=[]
text.split(/\r?\n/).forEach((line)=>{
const match=TERM_NETSTAT_WIN_RE.exec(line.trim())
if(!match)return
rows.push({proto:match[1].toUpperCase(),local:match[2],remote:match[3],state:(match[4]||"").toUpperCase(),pid:match[5]||""})
})
return rows.length?rows:null
}
const TERM_SS_RE=/^(tcp|udp)\s+(\S+)\s+\d+\s+\d+\s+(\S+)\s+(\S+)/i
function termParseSs(text){
const rows=[]
text.split(/\r?\n/).forEach((line)=>{
const match=TERM_SS_RE.exec(line.trim())
if(!match)return
rows.push({proto:match[1].toUpperCase(),local:match[3],remote:match[4],state:match[2].toUpperCase(),pid:""})
})
return rows.length?rows:null
}
function termParseConnections(text){
return termParseNetstat(text)||termParseSs(text)
}
function termParseProcesses(text){
return termParseTasklist(text)||termParsePs(text)
}
function termParseListing(kind,long,text){
if(kind==="powershell")return termParsePowerShellListing(text)
if(kind==="dir")return termParseDir(text)
if(kind==="ls")return long?termParseLsLong(text):termParseLsPlain(text)
if(kind==="nmap")return termParseNmap(text)
if(kind==="process")return termParseProcesses(text)
if(kind==="connection")return termParseConnections(text)
return null
}
function termListingIconClass(type){
if(type==="dir")return "icon-folder"
if(type==="symlink")return "icon-link"
return "icon-file"
}
function termBuildListingWidgetHtml(listing){
if(listing.kind==="history"){
if(!listing.rows.length)return `<div class="term-listing term-history-widget" data-listing-id="${listing.id}"><div class="term-listing-head"><span>Command History</span></div><div class="term-history-empty">No commands run yet.</div></div>`
const total=listing.rows.length
const rows=listing.rows.map((cmd,i)=>`<button type="button" class="term-history-item" data-cmd="${termEscapeHtml(cmd)}"><span class="term-history-idx">${total-i}</span><span class="term-history-cmd">${termEscapeHtml(cmd)}</span></button>`).join("")
return `<div class="term-listing term-history-widget" data-listing-id="${listing.id}"><div class="term-listing-head"><span>Command History</span></div><div class="term-history-list">${rows}</div></div>`
}
if(listing.showRaw){
return `<div class="term-listing" data-listing-id="${listing.id}"><div class="term-listing-head"><span>${listing.rows.length} item${listing.rows.length===1?"":"s"} - raw</span><button type="button" class="term-listing-toggle" data-listing-id="${listing.id}">Show table</button></div><pre class="term-listing-raw">${termAnsiToHtml(listing.rawText)}</pre></div>`
}
const table=TERM_TABLE_KINDS[listing.kind]
if(table){
const head=table.columns.map((column)=>`<th>${termEscapeHtml(column.label)}</th>`).join("")
const body=listing.rows.map((row)=>`<tr>${table.columns.map((column)=>`<td class="term-listing-cell term-listing-cell-${column.key}" title="${termEscapeHtml(row[column.key]||"")}">${termEscapeHtml(row[column.key]||"")}</td>`).join("")}</tr>`).join("")
return `<div class="term-listing" data-listing-id="${listing.id}"><div class="term-listing-head"><span>${table.label} - ${listing.rows.length}</span><button type="button" class="term-listing-toggle" data-listing-id="${listing.id}">Show raw</button></div><table class="term-listing-table term-listing-table-wide"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
}
const bodyRows=listing.rows.map((r)=>`<tr><td class="term-listing-icon"><i class="icon ${termListingIconClass(r.type)}"></i></td><td class="term-listing-name" title="Click to copy">${termEscapeHtml(r.name)}</td><td class="term-listing-size">${termEscapeHtml(r.sizeLabel||"")}</td><td class="term-listing-perms">${termEscapeHtml(r.perms||"")}</td><td class="term-listing-date">${termEscapeHtml(r.date||"")}</td></tr>`).join("")
return `<div class="term-listing" data-listing-id="${listing.id}"><div class="term-listing-head"><span>${listing.rows.length} item${listing.rows.length===1?"":"s"}</span><button type="button" class="term-listing-toggle" data-listing-id="${listing.id}">Show raw</button></div><table class="term-listing-table"><tbody>${bodyRows}</tbody></table></div>`
}
function termTriageBlock(jobId){
const tab=termFindTab(termState.activeId)
const record=termJobBlockAt(tab,jobId)
if(!record)return
const output=tab.buffer.slice(record.startIdx,record.endIdx===null||record.endIdx===undefined?tab.buffer.length:record.endIdx)
termAiTriageJob({job_key:record.jobId,command:record.command,exit_code:record.exitCode,state:"failed",session_id:tab.sessionId,_output:output})
}
function termHandleOutputClick(e){
const triage=e.target.closest(".term-job-block-ai")
if(triage){e.stopPropagation();termTriageBlock(triage.dataset.jobAi);return}
const rptJob=typeof ReportEvidence!=="undefined"&&e.target.closest(".rpt-ev-jobbtn")
if(rptJob){e.stopPropagation();const rptTab=termState.tabs.find((t)=>termJobBlockAt(t,rptJob.dataset.rptJob));ReportEvidence.saveJobRecord(rptTab,termJobBlockAt(rptTab,rptJob.dataset.rptJob));return}
const blockHead=e.target.closest(".term-job-block-head")
if(blockHead){
const block=blockHead.closest(".term-job-block")
if(block){termToggleJobBlock(block.dataset.jobBlock);return}
}
const ioc=e.target.closest(".term-ioc")
if(ioc){e.stopPropagation();termOpenSaveTargetPopover(ioc,ioc.dataset.kind,ioc.dataset.value);return}
const toggle=e.target.closest(".term-listing-toggle")
if(toggle){
const tab=termFindTab(termState.activeId)
const listing=tab&&(tab.listings||[]).find((x)=>x.id===toggle.dataset.listingId)
if(listing){listing.showRaw=!listing.showRaw;termInvalidateRender(tab);termRenderActiveOutput()}
return
}
const historyItem=e.target.closest(".term-history-item")
if(historyItem){termSubmitCommand(historyItem.dataset.cmd);return}
const nameCell=e.target.closest(".term-listing-name")
if(nameCell){
if(navigator.clipboard)navigator.clipboard.writeText(nameCell.textContent||"").then(()=>showToast("Copied")).catch(()=>{})
return
}
if(window.getSelection&&!window.getSelection().isCollapsed)return
if(e.target.closest(".term-listing"))return
document.getElementById("terminalInput").focus()
}
function termCollectIocs(tab){
if(!tab)return {}
const found=termScanIocs(tab.buffer)
const grouped={}
found.forEach((hit)=>{
if(!grouped[hit.kind])grouped[hit.kind]=[]
if(grouped[hit.kind].indexOf(hit.value)===-1)grouped[hit.kind].push(hit.value)
})
return grouped
}
function termIocSummaryHtml(grouped){
const kinds=Object.keys(grouped)
if(!kinds.length)return '<div class="terminal-popover-empty">No indicators found in this session.</div>'
return kinds.map((kind)=>{
const label=(TERM_IOC_RULES.find((r)=>r.kind===kind)||{}).label||kind
const values=grouped[kind]
return '<div class="term-ioc-group"><div class="term-ioc-group-head"><label class="term-ioc-group-check"><input type="checkbox" data-kind="'+termEscapeHtml(kind)+'" checked><span>'+termEscapeHtml(label)+'</span></label><span class="term-ioc-group-count">'+values.length+'</span></div><div class="term-ioc-group-values">'+values.slice(0,40).map((v)=>termEscapeHtml(v)).join("\n")+(values.length>40?"\n... and "+(values.length-40)+" more":"")+'</div></div>'
}).join("")
}
function termOpenIocModal(){
const tab=termFindTab(termState.activeId)
const grouped=termCollectIocs(tab)
const total=Object.keys(grouped).reduce((sum,k)=>sum+grouped[k].length,0)
const el=document.createElement("div")
el.className="term-fanout-modal glass-panel"
el.innerHTML='<div class="term-fanout-title">Indicators in this session</div><div class="term-fanout-note">'+total+' unique value'+(total===1?"":"s")+' across '+Object.keys(grouped).length+' type'+(Object.keys(grouped).length===1?"":"s")+'</div><div class="term-fanout-list term-ioc-list" id="termIocList">'+termIocSummaryHtml(grouped)+'</div><div class="term-fanout-actions"><button type="button" id="termIocCopy">Copy selected</button><button type="button" id="termIocNote">Send to note</button><button type="button" class="term-fanout-run" id="termIocTargets">Save as targets</button><button type="button" id="termIocClose">Close</button></div>'
openModal(el)
function selectedKinds(){
return Array.prototype.filter.call(el.querySelectorAll("#termIocList input[type=checkbox]"),(b)=>b.checked).map((b)=>b.dataset.kind)
}
function selectedValues(){
const out=[]
selectedKinds().forEach((kind)=>(grouped[kind]||[]).forEach((v)=>out.push({kind,value:v})))
return out
}
el.querySelector("#termIocClose").addEventListener("click",closeModal)
el.querySelector("#termIocCopy").addEventListener("click",()=>{
const text=selectedValues().map((x)=>x.value).join("\n")
if(!text){showToast("Nothing selected","error");return}
if(navigator.clipboard)navigator.clipboard.writeText(text).then(()=>showToast("Copied "+selectedValues().length+" values")).catch(()=>{})
})
el.querySelector("#termIocNote").addEventListener("click",()=>{
const rows=selectedValues()
if(!rows.length){showToast("Nothing selected","error");return}
const body="<h3>Indicators from terminal</h3><table><tbody>"+rows.map((r)=>"<tr><td>"+termEscapeHtml((TERM_IOC_RULES.find((x)=>x.kind===r.kind)||{}).label||r.kind)+"</td><td>"+termEscapeHtml(r.value)+"</td></tr>").join("")+"</tbody></table>"
bridgeCall("notes.save",[null,"Indicators - "+new Date().toLocaleString(),"Terminal Sessions",body,[],"ioc"]).then(()=>{closeModal();showToast("Saved indicators to a note")}).catch((err)=>showToast(err&&err.message?err.message:"Save failed","error"))
})
el.querySelector("#termIocTargets").addEventListener("click",()=>{
const rows=selectedValues().filter((r)=>TERM_IOC_TARGET_KEY[r.kind])
if(!rows.length){showToast("No saveable values selected","error");return}
const chain=rows.reduce((promise,row)=>promise.then(()=>{
const key=TERM_IOC_TARGET_KEY[row.kind]
const values={}
values[key]=row.value
return bridgeCall("targets.add_key",[key,0]).catch(()=>{}).then(()=>bridgeCall("targets.upsert_target",[null,row.value,"not_used",values])).catch(()=>{})
}),Promise.resolve())
chain.then(()=>{closeModal();showToast("Saved "+rows.length+" targets")})
})
}
function termOpenSaveTargetPopover(anchorEl,kind,value){
const pop=termOpenPopover(anchorEl,280)
const keyLabel=TERM_IOC_TARGET_KEY[kind]||"VALUE"
pop.innerHTML=`<div class="terminal-popover-title">Save as Target</div><div class="term-save-target-field"><label>Name</label><input type="text" id="termSaveTargetName" value="${termEscapeHtml(value)}"></div><div class="term-save-target-value">${termEscapeHtml(keyLabel)}: ${termEscapeHtml(value)}</div><div class="terminal-popover-actions"><button type="button" id="termSaveTargetCancel">Cancel</button><button type="button" class="term-save-target-confirm" id="termSaveTargetConfirm">Save</button></div>`
pop.querySelector("#termSaveTargetCancel").addEventListener("click",termClosePopover)
pop.querySelector("#termSaveTargetConfirm").addEventListener("click",()=>{
const name=pop.querySelector("#termSaveTargetName").value.trim()||value
const values={}
values[keyLabel]=value
bridgeCall("targets.add_key",[keyLabel,0]).catch(()=>{}).then(()=>{
return bridgeCall("targets.upsert_target",[null,name,"not_used",values])
}).then(()=>{
termClosePopover()
showToast("Saved as target")
}).catch((err)=>showToast(err&&err.message?err.message:"Save failed","error"))
})
}
const TERM_SCROLL_SLACK=24
function termIsAtBottom(out){
return out.scrollHeight-out.scrollTop-out.clientHeight<=TERM_SCROLL_SLACK
}
function termScrollToBottom(pane){
pane=pane||termFocusedPane()
if(!pane||!pane.out)return
pane.out.scrollTop=pane.out.scrollHeight
pane.followOutput=true
pane.pendingOutput=0
termUpdatePaneJump(pane)
}
function termUpdatePaneJump(pane){
if(!pane||!pane.jump)return
pane.jump.classList.toggle("hidden",pane.followOutput||!pane.sessionId)
const label=pane.jump.querySelector(".terminal-jump-label")
if(label)label.textContent=pane.pendingOutput>0?"New output":"Jump to bottom"
}
function termUpdateJumpButton(){
termUpdatePaneJump(termFocusedPane())
}
const TERM_MAX_UNCOMMITTED=8192
function termEnsureStreamNodes(out){
let stream=out.querySelector(":scope > .terminal-stream")
if(!stream){
stream=document.createElement("span")
stream.className="terminal-stream"
stream.innerHTML='<span class="terminal-committed"></span><span class="terminal-tail"></span>'
out.insertBefore(stream,out.querySelector(":scope > .term-prior")?out.querySelector(":scope > .term-prior").nextSibling:out.firstChild)
}
return {committed:stream.firstChild,tail:stream.lastChild}
}
function termCommitBoundary(tab){
const lastBreak=tab.buffer.lastIndexOf("\n")+1
if(tab.buffer.length-lastBreak>TERM_MAX_UNCOMMITTED)return tab.buffer.length
return lastBreak>tab.renderedLen?lastBreak:tab.renderedLen
}
function termRenderTail(nodes,tab){
const tail=tab.buffer.slice(tab.renderedLen)
nodes.tail.innerHTML=tail?termAnsiRenderChunk(tail,tab.ansiClasses).html:""
}
function termUpdateLiveEcho(){
const out=termOutputEl()
if(!out)return
let echo=document.getElementById("terminalLiveEcho")
if(!echo){
echo=document.createElement("span")
echo.id="terminalLiveEcho"
out.appendChild(echo)
}else if(echo.parentElement!==out||echo.nextSibling){
out.appendChild(echo)
}
const input=document.getElementById("terminalInput")
const val=input?input.value:""
const focused=document.activeElement===input
const selStart=input&&focused?Math.min(input.selectionStart,val.length):val.length
const selEnd=input&&focused?Math.min(input.selectionEnd,val.length):val.length
const cursorClass="term-cursor"+(focused?"":" term-cursor-blur")
if(selStart!==selEnd)echo.innerHTML=termEscapeHtml(val.slice(0,selStart))+'<span class="term-echo-sel">'+termEscapeHtml(val.slice(selStart,selEnd))+'</span><span class="'+cursorClass+' term-cursor-thin"></span>'+termEscapeHtml(val.slice(selEnd))
else if(selStart<val.length&&val[selStart]!=="\n")echo.innerHTML=termEscapeHtml(val.slice(0,selStart))+'<span class="'+cursorClass+' term-cursor-char">'+termEscapeHtml(val[selStart])+"</span>"+termEscapeHtml(val.slice(selStart+1))
else echo.innerHTML=termEscapeHtml(val.slice(0,selStart))+'<span class="'+cursorClass+'"></span>'+termEscapeHtml(val.slice(selStart))
if(termState.followOutput)out.scrollTop=out.scrollHeight
if(typeof termSuggest!=="undefined"&&termSuggest.open){if(termSuggest.forValue!==val||(focused&&selEnd!==val.length))termSuggestHide();else termSuggestPosition()}
}
function termJobBlockState(record){
if(record.exitCode===null||record.exitCode===undefined)return record.endIdx===null?"running":"orphaned"
return record.exitCode===0?"done":"failed"
}
function termJobBlockOpenHtml(record){
const state=termJobBlockState(record)
const exit=state==="running"?"running":state==="orphaned"?"no exit code":termExitLabel(record.exitCode)
const seconds=record.endedAt&&record.startedAt?Math.max(0,Math.round((record.endedAt-record.startedAt)/1000)):null
const duration=seconds===null?"":(seconds<60?seconds+"s":Math.floor(seconds/60)+"m "+(seconds%60)+"s")
const triage=state==="failed"?'<span class="term-job-block-ai" data-job-ai="'+termEscapeHtml(record.jobId)+'" title="Ask the AI why this failed">Why?</span>':""
return '<span class="term-job-block '+state+(record.folded?" folded":"")+'" data-job-block="'+termEscapeHtml(record.jobId)+'"><span class="term-job-block-head"><span class="term-job-block-toggle"><i class="icon icon-arrow-down"></i></span><span class="term-job-block-cmd">'+termEscapeHtml(record.command||"")+'</span>'+(duration?'<span class="term-job-block-time">'+termEscapeHtml(duration)+'</span>':"")+triage+(typeof ReportEvidence!=="undefined"?ReportEvidence.jobButtonHtml(record.jobId):"")+'<span class="term-job-block-exit">'+termEscapeHtml(exit)+'</span></span><span class="term-job-block-body">'
}
const TERM_JOB_BLOCK_CLOSE="</span></span>"
function termVisibleJobBlocks(tab){
if(!termState.jobBlocks)return []
return (tab.jobHistory||[]).filter((record)=>record.command&&record.startIdx>=0).slice().sort((a,b)=>a.startIdx-b.startIdx)
}
function termJobBlockAt(tab,jobId){
return (tab.jobHistory||[]).find((record)=>record.jobId===jobId)
}
function termToggleJobBlock(jobId){
const tab=termFindTab(termState.activeId)
const record=termJobBlockAt(tab,jobId)
if(!record)return
record.folded=!record.folded
termInvalidateRender(tab)
termRenderActiveOutput()
}
function termJobBlockBoundaries(tab){
const blocks=termVisibleJobBlocks(tab)
return blocks.map((record)=>record.startIdx)
}
function termJumpJobBoundary(direction){
const tab=termFindTab(termState.activeId)
if(!tab)return
const out=termOutputEl()
const marks=out.querySelectorAll(".term-job-block-head")
if(!marks.length){showToast("No job boundaries in this session");return}
const positions=Array.prototype.map.call(marks,(el)=>el.offsetTop)
const current=out.scrollTop
let target=null
if(direction<0){for(let i=positions.length-1;i>=0;i--){if(positions[i]<current-4){target=positions[i];break}}}
else{for(let i=0;i<positions.length;i++){if(positions[i]>current+4){target=positions[i];break}}}
if(target===null){showToast(direction<0?"At the first job":"At the last job");return}
termState.followOutput=false
out.scrollTop=Math.max(0,target-8)
termUpdateJumpButton()
}
function termRenderSegments(tab,commitEnd){
const points=[]
;(tab.listings||[]).forEach((l)=>points.push({at:l.startIdx,kind:"listing",data:l}))
termVisibleJobBlocks(tab).forEach((record)=>points.push({at:record.startIdx,kind:"job",data:record}))
points.sort((a,b)=>a.at-b.at||(a.kind==="job"?-1:1))
let html=""
let cursor=0
let classes=[]
let blockOpen=false
function emitText(to){
if(to<=cursor)return
const rendered=termAnsiRenderChunk(tab.buffer.slice(cursor,to),classes,cursor)
html+=rendered.html
classes=rendered.classes
cursor=to
}
points.forEach((point)=>{
const at=Math.min(point.at,commitEnd)
emitText(at)
if(point.kind==="job"){
if(blockOpen){html+=TERM_JOB_BLOCK_CLOSE;blockOpen=false}
html+=termJobBlockOpenHtml(point.data)
blockOpen=true
return
}
html+=termBuildListingWidgetHtml(point.data)
cursor=Math.max(cursor,Math.min(point.data.endIdx,commitEnd))
})
emitText(commitEnd)
if(blockOpen)html+=TERM_JOB_BLOCK_CLOSE
return {html,classes}
}
function termSearchRegex(){
const query=termState.searchQuery
if(!query)return null
try{
if(termState.searchRegex)return new RegExp(query,"gi")
return new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"),"gi")
}catch(err){return null}
}
function termSearchMatches(tab){
const re=termSearchRegex()
if(!re||!tab)return []
const out=[]
let m
while((m=re.exec(tab.buffer))!==null){
out.push({start:m.index,end:m.index+m[0].length})
if(m.index===re.lastIndex)re.lastIndex++
if(out.length>=2000)break
}
return out
}
function termFilterLines(tab){
const re=termSearchRegex()
if(!re||!tab)return ""
return tab.buffer.split(/\r?\n/).filter((line)=>{re.lastIndex=0;return re.test(line)}).join("\n")
}
function termUpdateSearchStatus(){
const status=document.getElementById("terminalSearchStatus")
if(!status)return
const total=termState.searchMatches.length
if(!termState.searchQuery){status.textContent="";return}
if(!total){status.textContent=termSearchRegex()?"no matches":"bad pattern";return}
status.textContent=(termState.searchIndex+1)+" / "+total
}
function termRunSearch(){
const tab=termFindTab(termState.activeId)
termState.searchMatches=termSearchMatches(tab)
if(termState.searchIndex>=termState.searchMatches.length)termState.searchIndex=0
termInvalidateRender(tab)
termRenderActiveOutput()
termUpdateSearchStatus()
}
function termStepSearch(step){
if(!termState.searchMatches.length)return
termState.searchIndex=(termState.searchIndex+step+termState.searchMatches.length)%termState.searchMatches.length
termInvalidateRender(termFindTab(termState.activeId))
termRenderActiveOutput()
termUpdateSearchStatus()
termScrollToActiveMatch()
}
function termScrollToActiveMatch(){
const out=termOutputEl()
const el=out&&out.querySelector(".term-search-hit.current")
if(!el)return
termState.followOutput=false
out.scrollTop=Math.max(0,el.offsetTop-Math.round(out.clientHeight/2))
termUpdateJumpButton()
}
function termOpenSearch(){
termState.searchOpen=true
document.getElementById("terminalSearchBar").classList.remove("hidden")
const input=document.getElementById("terminalSearchInput")
input.focus()
input.select()
}
function termCloseSearch(){
termState.searchOpen=false
termState.searchQuery=""
termState.searchMatches=[]
termState.searchIndex=0
termState.searchFilter=false
document.getElementById("terminalSearchBar").classList.add("hidden")
document.getElementById("terminalSearchInput").value=""
const tab=termFindTab(termState.activeId)
termInvalidateRender(tab)
termRenderActiveOutput()
document.getElementById("terminalInput").focus()
}
function termToggleSearch(){
if(termState.searchOpen)termCloseSearch()
else termOpenSearch()
}
function termApplySearchHighlight(rawSlice,sliceStart){
const matches=termState.searchMatches
if(!matches.length)return null
const hits=[]
matches.forEach((match,index)=>{
if(match.end<=sliceStart||match.start>=sliceStart+rawSlice.length)return
hits.push({start:Math.max(0,match.start-sliceStart),end:Math.min(rawSlice.length,match.end-sliceStart),current:index===termState.searchIndex})
})
return hits.length?hits:null
}
function termFullRenderOutput(nodes,tab){
if(termState.searchFilter&&termState.searchQuery){
nodes.committed.innerHTML='<span class="term-filter-note">Filtered to lines matching the search</span>\n'+termAnsiRenderChunk(termFilterLines(tab),[]).html
nodes.tail.innerHTML=""
tab.ansiClasses=[]
tab.renderedLen=tab.buffer.length
tab.renderedVersion=tab.renderVersion
termState.renderedTabId=tab.sessionId
return
}
const listings=(tab.listings||[]).slice().sort((a,b)=>a.startIdx-b.startIdx)
const last=listings[listings.length-1]
tab.renderedLen=0
let commitEnd=termCommitBoundary(tab)
if(last&&last.endIdx>commitEnd)commitEnd=tab.buffer.length
const rendered=termRenderSegments(tab,commitEnd)
nodes.committed.innerHTML=rendered.html
tab.ansiClasses=rendered.classes
tab.renderedLen=commitEnd
tab.renderedVersion=tab.renderVersion
termState.renderedTabId=tab.sessionId
termRenderTail(nodes,tab)
}
function termAppendRenderOutput(nodes,tab){
const commitEnd=termCommitBoundary(tab)
if(commitEnd>tab.renderedLen){
const rendered=termAnsiRenderChunk(tab.buffer.slice(tab.renderedLen,commitEnd),tab.ansiClasses)
tab.ansiClasses=rendered.classes
tab.renderedLen=commitEnd
if(rendered.html)nodes.committed.insertAdjacentHTML("beforeend",rendered.html)
}
termRenderTail(nodes,tab)
}
function termRenderActiveOutput(){
termRenderPane(termFocusedPane())
}
// Search highlights and the filter view belong to the focused session only; another pane renders as if no search was open.
function termWithoutSearch(fn){
const saved={searchQuery:termState.searchQuery,searchMatches:termState.searchMatches,searchFilter:termState.searchFilter}
termState.searchQuery="";termState.searchMatches=[];termState.searchFilter=false
try{return fn()}finally{Object.assign(termState,saved)}
}
function termRenderPrior(pane,tab){
let prior=pane.out.querySelector(":scope > .term-prior")
if(!tab||!tab.prior||!tab.prior.text){if(prior)prior.remove();return}
if(!prior){
prior=document.createElement("div")
prior.className="term-prior"
pane.out.insertBefore(prior,pane.out.firstChild)
}
if(prior.dataset.session===tab.sessionId)return
prior.dataset.session=tab.sessionId
prior.innerHTML='<span class="term-prior-text">'+termEscapeHtml(tab.prior.text.replace(/\n+$/,""))+'</span><span class="term-prior-divider"><span>'+termEscapeHtml(tab.prior.note||"Output from an earlier shell - this is a new shell")+"</span></span>"
}
function termRenderPane(pane){
if(!pane||!pane.out)return
const out=pane.out
const tab=termFindTab(pane.sessionId)
const focused=pane===termFocusedPane()
pane.el.classList.toggle("empty",!tab)
if(!tab){
const stream=out.querySelector(":scope > .terminal-stream")
if(stream)stream.remove()
termRenderPrior(pane,null)
pane.renderedTabId=null
termUpdatePaneJump(pane)
if(focused)termUpdateLiveEcho()
return
}
const nodes=termEnsureStreamNodes(out)
const needsFull=pane.renderedTabId!==tab.sessionId||tab.renderedVersion!==tab.renderVersion||tab.renderedLen>tab.buffer.length||(focused&&!!termState.searchQuery)
if(needsFull){
termRenderPrior(pane,tab)
if(focused)termFullRenderOutput(nodes,tab)
else termWithoutSearch(()=>termFullRenderOutput(nodes,tab))
pane.renderedTabId=tab.sessionId
}else termAppendRenderOutput(nodes,tab)
if(focused)termUpdateLiveEcho()
else if(pane.followOutput)out.scrollTop=out.scrollHeight
termUpdatePaneJump(pane)
}
function termRenderSession(sessionId){
const pane=termPaneForSession(sessionId)
if(pane)termRenderPane(pane)
}
function termRenderAllPanes(){
termState.panes.forEach(termRenderPane)
}
function termInvalidateRender(tab){
if(tab)tab.renderVersion+=1
}
function termActivateTab(id){
termSuggestHide()
const shownAt=termPaneIndexOf(id)
if(shownAt>=0&&shownAt!==termState.focusPane){termFocusPane(shownAt);return}
const pane=termFocusedPane()
if(pane&&pane.sessionId!==id){
termStashStagedInput(pane.sessionId,id)
pane.sessionId=id
pane.renderedTabId=null
termScheduleSizeSync()
termSaveWorkspaceSoon()
}
termState.activeId=id
termState.followOutput=true
termState.pendingOutput=0
termUpdateStatusBar()
termRenderTabs()
termRenderActiveOutput()
if(termState.searchQuery)termRunSearch()
document.getElementById("terminalInput").focus()
}
const TERM_SCROLLBACK_CHARS=400000
const TERM_SCROLLBACK_SLACK=65536
function termTrimScrollback(tab){
if(tab.buffer.length<=TERM_SCROLLBACK_CHARS+TERM_SCROLLBACK_SLACK)return false
const cut=tab.buffer.length-TERM_SCROLLBACK_CHARS
tab.buffer=tab.buffer.slice(cut)
tab.visible=(tab.visible||"").slice(cut)
tab.renderedLen=Math.max(0,tab.renderedLen-cut)
if(tab.listings)tab.listings=tab.listings.map((l)=>({...l,startIdx:Math.max(0,l.startIdx-cut),endIdx:Math.max(0,l.endIdx-cut)})).filter((l)=>l.endIdx>0)
if(tab.pendingCapture)tab.pendingCapture.startIdx=Math.max(0,tab.pendingCapture.startIdx-cut)
if(tab.jobHistory)tab.jobHistory=tab.jobHistory.map((j)=>Object.assign({},j,{startIdx:Math.max(0,j.startIdx-cut),endIdx:j.endIdx===null?null:Math.max(0,j.endIdx-cut)})).filter((j)=>j.endIdx===null||j.endIdx>0)
termInvalidateRender(tab)
return true
}
function termAppend(id,text){
const tab=termFindTab(id)
if(!tab||!text)return
termNoteJobPrompt(tab)
tab.pendingRaw=(tab.pendingRaw||"")+text
const lastBreak=tab.pendingRaw.lastIndexOf("\n")
let complete=""
if(lastBreak>=0){complete=tab.pendingRaw.slice(0,lastBreak+1);tab.pendingRaw=tab.pendingRaw.slice(lastBreak+1)}
else if(tab.pendingRaw.length>TERM_MAX_UNCOMMITTED){complete=tab.pendingRaw;tab.pendingRaw=""}
const results=complete?termExtractJobResults(complete):[]
const cleaned=complete?termCleanComplete(tab,complete):""
if(complete)tab.visible=(tab.visible||"")+cleaned
if(complete&&typeof ReportEvidence!=="undefined"&&ReportEvidence.isRecording(id))ReportEvidence.onSessionOutput(id,cleaned)
if(complete&&complete.indexOf("\x1b[")>=0){
const collapsed=termApplyRedraw(tab.visible||"")
if(collapsed!==(tab.visible||"")){tab.visible=collapsed;termInvalidateRender(tab)}
}
tab.buffer=(tab.visible||"")+termPendingVisible(tab)
results.forEach((result)=>termResolveJob(tab,result))
if(termCheckPromptReturn(tab)||results.length)tab.buffer=(tab.visible||"")+termPendingVisible(tab)
termTrimScrollback(tab)
const pane=termPaneForSession(id)
if(!pane)return
if(id===termState.activeId)termUpdateStatusBar()
if(!pane.followOutput)pane.pendingOutput+=text.length
termRenderPane(pane)
}
// Display-only lines from the app itself (the result of a /caller diagram run): placed above the current prompt line, never
// sent to the shell and never recorded as session output. kind: "ok" | "error" | "info". -> false when no session can show them.
function termPrintNotice(sessionId,lines,kind){
const tab=termFindTab(sessionId)||termFindTab(termState.activeId)
const list=(Array.isArray(lines)?lines:[lines]).map((l)=>String(l===undefined||l===null?"":l).replace(/[\x00-\x1f\x7f]+/g," ").trim()).filter(Boolean)
if(!tab||!list.length)return false
const color=kind==="error"?"31":kind==="ok"?"32":"36"
const before=tab.visible||""
let at=before.length
// A two-line prompt (Kali's "┌──(user㉿host)-[dir]" over "└─$"): go above its first line too, so the prompt stays whole.
const top=before.lastIndexOf("\n",before.length-2)+1
if(tab.pendingRaw&&/^\s*[┌╭]/.test(before.slice(top).replace(/\x1b\[[0-9;?]*[A-Za-z]/g,"")))at=top
const note=(at&&before[at-1]!=="\n"?"\n":"")+"\x1b[0m"+list.map((l,i)=>(i?"\x1b[2m  ":"\x1b[1;"+color+"m")+l+"\x1b[0m").join("\n")+"\n"
const shift=(i)=>typeof i==="number"&&i>=at?i+note.length:i
;(tab.listings||[]).forEach((l)=>{l.startIdx=shift(l.startIdx);l.endIdx=shift(l.endIdx)})
;(tab.jobHistory||[]).forEach((j)=>{j.startIdx=shift(j.startIdx);j.endIdx=shift(j.endIdx)})
if(tab.pendingCapture)tab.pendingCapture.startIdx=shift(tab.pendingCapture.startIdx)
tab.visible=before.slice(0,at)+note+before.slice(at)
tab.buffer=tab.visible+termPendingVisible(tab)
termInvalidateRender(tab)
termTrimScrollback(tab)
termRenderSession(tab.sessionId)
return true
}
function termElevationFailureText(tab){
const lines=String(tab.buffer||"").replace(TERM_ANSI_SGR_RE,"").replace(TERM_ANSI_OTHER_RE,"").split("\n").map((l)=>l.trim()).filter(Boolean)
return lines.length?lines[lines.length-1].slice(0,160):"Elevation was refused."
}
function termHandleDeadTab(id){
const tab=termFindTab(id)
if(!tab||tab.dead)return
tab.dead=true
const watch=termState.taskWatch[id]
if(watch){delete termState.taskWatch[id];bridgeCall("terminal.exit_code",[id]).then((code)=>watch(code)).catch(()=>watch(null))}
if(tab.activeJob){bridgeCall("terminal.job_mark",[tab.activeJob.jobId,"orphaned"]).catch(()=>{});tab.activeJob=null}
if(tab.elevated){
bridgeCall("terminal.exit_code",[id]).then((code)=>{
if(code===0||code===null||code===undefined){termRenderTabs();termAppend(id,"\n[process exited]\n");showStatusIsland((tab.label||"Terminal session")+" ended","error");return}
const reason=termElevationFailureText(tab)
termCloseTab(id,true)
showToast(reason,"error")
}).catch(()=>{termRenderTabs();termAppend(id,"\n[process exited]\n")})
return
}
termRenderTabs()
termAppend(id,"\n[process exited]\n")
showStatusIsland((tab.label||"Terminal session")+" ended","error")
}
function termCheckPendingCapture(tab){
const capture=tab.pendingCapture
if(!capture)return
if(tab.buffer.length>capture.lastLen){
capture.lastLen=tab.buffer.length
capture.quietTicks=0
return
}
capture.quietTicks+=1
if(capture.quietTicks<TERM_JOB_FALLBACK_TICKS)return
if(tab.activeJob&&tab.activeJob.jobId===capture.jobId){bridgeCall("terminal.job_mark",[capture.jobId,"orphaned"]).catch(()=>{});tab.activeJob=null}
termFinalizeCapture(tab,capture.jobId)
if(tab.sessionId===termState.activeId)termUpdateStatusBar()
}
const TERM_POLL_MIN_MS=60
const TERM_POLL_MAX_MS=500
const TERM_POLL_BACKOFF=1.5
const TERM_ALIVE_CHECK_MS=1000
function termScheduleNextPoll(delay){
if(!termState.polling||!termState.tabs.length){termState.polling=false;termState.pollTimer=null;return}
termState.pollTimer=setTimeout(termPollTick,delay)
}
const TERM_HIDDEN_POLL_MS=1000
// The ids to read this tick: sessions on screen every tick, sessions that are only tabs about once a second (they have
// no DOM to update, but their job markers and exit codes still need to be seen). A session with a job in flight stays
// at full rate so its block closes on time.
function termPollPlan(tabs,visibleIds,now,lastHidden){
const hiddenDue=now-lastHidden>=TERM_HIDDEN_POLL_MS
const ids=tabs.filter((t)=>!t.dead&&(hiddenDue||visibleIds.indexOf(t.sessionId)>=0||t.activeJob)).map((t)=>t.sessionId)
return {ids,hiddenDue}
}
function termPollTick(){
termState.pollTimer=null
const now=Date.now()
const checkAlive=now-termState.lastAliveCheck>=TERM_ALIVE_CHECK_MS
if(checkAlive)termState.lastAliveCheck=now
const visible=termState.panes.map((p)=>p.sessionId).filter(Boolean)
const plan=termPollPlan(termState.tabs,visible,now,termState.lastHiddenPoll)
if(plan.hiddenDue)termState.lastHiddenPoll=now
const aliveIds=checkAlive?termState.tabs.filter((t)=>!t.dead).map((t)=>t.sessionId):[]
bridgeCall("terminal.poll",[plan.ids,aliveIds]).then((res)=>{
const out=(res&&res.out)||{}
let received=0
plan.ids.forEach((id)=>{
const chunk=out[id]
if(chunk){received+=chunk.length;termAppend(id,chunk)}
const t=termFindTab(id)
if(t)termCheckPendingCapture(t)
})
const alive=(res&&res.alive)||{}
aliveIds.forEach((id)=>{if(alive[id]===false)termHandleDeadTab(id)})
termState.pollDelay=received>0?TERM_POLL_MIN_MS:Math.min(TERM_POLL_MAX_MS,Math.round(termState.pollDelay*TERM_POLL_BACKOFF))
termScheduleNextPoll(termState.pollDelay)
}).catch(()=>termScheduleNextPoll(TERM_POLL_MAX_MS))
}
function termWakePolling(){
termState.pollDelay=TERM_POLL_MIN_MS
if(termState.polling&&termState.pollTimer){clearTimeout(termState.pollTimer);termState.pollTimer=null;termPollTick()}
}
function termStartPolling(){
if(termState.polling||termState.locked)return
termState.polling=true
termState.pollDelay=TERM_POLL_MIN_MS
termState.lastAliveCheck=0
termPollTick()
}
function termStopPolling(){
termState.polling=false
if(termState.pollTimer){clearTimeout(termState.pollTimer);termState.pollTimer=null}
}
// While the app is locked no terminal output is read (terminal.poll / terminal.read are refused anyway): polling stops and
// cannot start; after unlock it starts again if it was running when the lock came down.
function termSetLockPaused(locked){
if(locked){
if(!termState.locked)termState.resumeAfterUnlock=termState.polling
termState.locked=true
termStopPolling()
return
}
termState.locked=false
const resume=termState.resumeAfterUnlock
termState.resumeAfterUnlock=false
if(resume&&termState.tabs.length)termStartPolling()
}
// "zsh 3" style default names: the count of open sessions plus one, moved past any name already taken (after a close,
// a restore or a reopen the plain count could hand out a name that is still on screen).
function termDefaultLabel(prefix,tabs){
const used=new Set((tabs||[]).map((t)=>t.label))
let n=(tabs||[]).length+1
while(used.has(prefix+" "+n))n++
return prefix+" "+n
}
function termAddSessionTab(sessionId,shellId,labelPrefix,opts){
opts=opts||{}
const shell=termState.shells.find((s)=>s.id===shellId)
const label=opts.name||termDefaultLabel(labelPrefix||(shell?shell.label:shellId),termState.tabs)
const elevated=labelPrefix==="Elevated"
termState.tabs.push({sessionId,shellId,label,buffer:"",dead:false,history:[],historyIdx:null,listings:[],pendingCapture:null,elevated,visible:"",pendingRaw:"",activeJob:null,jobHistory:[],lastExitCode:null,cwd:opts.cwd||"",renderVersion:0,renderedVersion:-1,renderedLen:0,ansiClasses:[],profileId:opts.profileId||"",prior:opts.prior||null,staged:"",cols:opts.cols||0,rows:opts.rows||0})
if(opts.name)bridgeCall("terminal.rename",[sessionId,label]).catch(()=>{})
termState.workspaceRestored=true
const target=typeof opts.paneIndex==="number"?opts.paneIndex:-1
const focused=termFocusedPane()
// A new or reopened session goes into an empty pane before it replaces the one the user is looking at.
const empty=target<0&&focused&&focused.sessionId?termState.panes.findIndex((p)=>!p.sessionId):-1
if(target>=0&&target!==termState.focusPane&&termState.panes[target]&&!termState.panes[target].sessionId){
termAssignPane(target,sessionId)
termRenderTabs()
}else if(empty>=0){
termAssignPane(empty,sessionId)
termFocusPane(empty)
}else termActivateTab(sessionId)
termStartPolling()
}
function termRefreshProfiles(){
return bridgeCall("terminal.profiles").then((profiles)=>{
termState.profiles=Array.isArray(profiles)?profiles:[]
termRenderShellSelect()
return termState.profiles
}).catch(()=>{})
}
// The new-session choices: the shells (default first), then an install offer for PowerShell on Linux when pwsh is missing.
// Values starting with "__" are actions, never shell ids.
const TERM_INSTALL_PWSH="__install:pwsh"
function termShellMenuOptions(shells,extras){
const out=(shells||[]).map((s)=>({value:s.id,label:s.label+(s.default?" (default)":""),kind:"shell"}))
const pwsh=extras&&extras.pwsh
if(extras&&extras.platform==="linux"&&pwsh&&!pwsh.installed)out.push({value:TERM_INSTALL_PWSH,label:pwsh.installable?"PowerShell (not installed) \u2013 Install\u2026":"PowerShell (not installed)",kind:"install",disabled:!pwsh.installable,title:pwsh.installable?pwsh.command:pwsh.reason})
return out
}
function termRenderShellSelect(){
const select=document.getElementById("terminalShellSelect")
if(!select)return
const previous=select.value
const shells=termShellMenuOptions(termState.shells,termState.extras).map((o)=>'<option value="'+termEscapeHtml(o.value)+'"'+(o.disabled?" disabled":"")+(o.title?' title="'+termEscapeHtml(o.title)+'"':"")+'>'+termEscapeHtml(o.label)+"</option>").join("")
const profiles=(termState.profiles||[]).map((p)=>'<option value="profile:'+termEscapeHtml(p.id)+'">'+termEscapeHtml(p.name)+"</option>").join("")
select.innerHTML=shells+profiles
if(previous&&previous.indexOf("__")!==0)select.value=previous
if((!select.value||select.value.indexOf("__")===0)&&termState.shells.length)select.value=termState.shells[0].id
select.dataset.last=select.value
}
function termOpenNewSessionMenu(x,y){
const items=termShellMenuOptions(termState.shells,termState.extras).map((o)=>({label:o.label,icon:o.kind==="install"?"add":"command-line",disabled:!!o.disabled,fn:()=>{if(o.kind==="install")termInstallPowershell();else termNewTab(o.value).catch((err)=>showToast(err&&err.message?err.message:"Could not start the session","error"))}}))
;(termState.profiles||[]).forEach((p)=>items.push({label:p.name+" (profile)",icon:"command-line",fn:()=>termNewTab("profile:"+p.id).catch(()=>{})}))
openContextMenu(items,x,y)
}
function termReloadShells(){
return Promise.all([bridgeCall("terminal.shells"),bridgeCall("terminal.shell_extras").catch(()=>null)]).then(([shells,extras])=>{
termState.shells=Array.isArray(shells)?shells:termState.shells
termState.extras=extras
termRenderShellSelect()
return termState.shells
})
}
// The panel without starting a default session (task sessions bring their own).
function termShowPanelOnly(){
if(termState.open)return
termState.open=true
termState.maximized=false
document.getElementById("terminalPanel").classList.remove("hidden")
termApplyLayout()
termApplyPaneLayout()
termSyncToggleButtons()
}
// Runs one of the backend's fixed task commands (installers, first-run steps) in a new session the user can type into.
// onExit(code) is called once the process ends.
function termOpenTaskSession(task,params,onExit){
if(!termState.enabled)return Promise.reject(new Error("Turn on the Terminal extension first (Settings > Extensions > Terminal)."))
termShowPanelOnly()
const grid=termCurrentGrid(termFocusedPane())
return bridgeCall("terminal.create_task",[task,params||{},grid?grid.cols:0,grid?grid.rows:0]).then((res)=>{
if(typeof onExit==="function")termState.taskWatch[res.session_id]=onExit
termAddSessionTab(res.session_id,res.shell_id,res.label,{cols:grid?grid.cols:0,rows:grid?grid.rows:0})
return res
})
}
function termOpenShellSession(shellId){
if(!termState.enabled)return Promise.reject(new Error("Turn on the Terminal extension first (Settings > Extensions > Terminal)."))
termShowPanelOnly()
return termNewTab(shellId)
}
function termInstallPowershell(){
const pwsh=termState.extras&&termState.extras.pwsh
if(!pwsh||pwsh.installed){showToast("PowerShell is already installed.");return Promise.resolve(false)}
if(!pwsh.installable){showToast(pwsh.reason||"PowerShell cannot be installed from here.","error");return Promise.resolve(false)}
return appConfirm("Install PowerShell?",{okLabel:"Install",bodyHtml:'<p class="term-confirm-note">This opens a terminal session that runs, with sudo (you type your password there):</p><pre class="term-run-preview">'+termEscapeHtml(pwsh.command)+'</pre><p class="term-confirm-note">Kali ships PowerShell in its own repository (package <code>powershell</code>, command <code>pwsh</code>).</p>'}).then((ok)=>{
if(!ok)return false
return termOpenTaskSession("pwsh_install",{},(code)=>{
termReloadShells().then(()=>{
const has=termState.extras&&termState.extras.pwsh&&termState.extras.pwsh.installed
showToast(has?"PowerShell is installed. Pick it in the shell list.":"PowerShell was not installed (exit "+code+").",has?"success":"error")
}).catch(()=>{})
}).then(()=>true)
}).catch((err)=>{showToast(err&&err.message?err.message:"Could not start the install","error");return false})
}
// opts: name, cwd, startup (saved / reopened sessions), prior {text,note} shown greyed above the new shell, paneIndex.
function termNewTab(shellId,opts){
opts=opts||{}
const sel=document.getElementById("terminalShellSelect")
let chosen=shellId||(sel.value&&sel.value.indexOf("__")!==0?sel.value:"")||(termState.shells[0]&&termState.shells[0].id)
const isProfile=String(chosen||"").indexOf("profile:")===0
const profileId=isProfile?chosen.slice(8):null
const profile=isProfile?(termState.profiles||[]).find((p)=>p.id===profileId):null
if(!isProfile&&!termState.shells.some((s)=>s.id===chosen)&&termState.shells.length)chosen=termState.shells[0].id
const pane=typeof opts.paneIndex==="number"?termState.panes[opts.paneIndex]:termFocusedPane()
const grid=termCurrentGrid(pane)
return bridgeCall("terminal.create",[isProfile?null:chosen,profileId,grid?grid.cols:0,grid?grid.rows:0,opts.cwd||"",opts.startup||"",opts.name||""]).then((sessionId)=>{
termAddSessionTab(sessionId,profile?profile.shell_id:chosen,profile?profile.name:undefined,Object.assign({},opts,{profileId:profileId||"",cols:grid?grid.cols:0,rows:grid?grid.rows:0}))
return sessionId
}).catch((err)=>{console.error("terminal create failed",err);throw err})
}
function termEnsureActiveSession(){
// A closed panel with live sessions still has an activeId: open it (layout + polling) so a run or staged command is visible.
if(termState.activeId){if(!termState.open)termOpenPanel();return Promise.resolve(termState.activeId)}
if(!termState.enabled)return Promise.reject(new Error("Enable the Terminal extension in Settings first."))
if(!termState.open){
termState.open=true
document.getElementById("terminalPanel").classList.remove("hidden")
}
return termNewTab().then((id)=>{termStartPolling();return id})
}
function termOpenForRun(){
if(!termState.enabled)return Promise.reject(new Error("Enable the Terminal extension in Settings first."))
if(!termState.open){
termState.open=true
document.getElementById("terminalPanel").classList.remove("hidden")
}
return Promise.resolve()
}
function termRunTargetSession(meta){
const destination=(meta&&meta.destination)||termState.runDestination||"active"
if(destination==="new"||!termState.activeId)return termOpenForRun().then(()=>termNewTab())
return termEnsureActiveSession()
}
function termRecordCommandHistory(tab,text){
if(!tab||!text||!text.trim())return
if(tab.history[tab.history.length-1]!==text){
tab.history.push(text)
if(tab.history.length>200)tab.history.shift()
}
tab.historyIdx=null
}
function termRunCommandText(text,meta){
return termRunTargetSession(meta).then((id)=>{
termActivateTab(id)
document.getElementById("terminalInput").focus()
termRecordCommandHistory(termFindTab(id),text)
const runTab=termFindTab(id)
const runJobId=termNewJobId()
if(runTab)runTab.activeJob={jobId:runJobId,command:text,startIdx:runTab.buffer.length,startedAt:Date.now(),exitCode:null,endedAt:null,endIdx:null}
if(runTab)termRecordJobStart(runTab,runTab.activeJob,(meta&&meta.source)||"snippet")
if(runTab)termRecordJobOffset(runTab,runTab.activeJob)
return bridgeCall("terminal.write",[id,(runTab?termJobPayload(runTab,text,runJobId):text)+termSubmitNewline(runTab?runTab.shellId:(termFindTab(id)||{}).shellId)]).then(()=>{termWakePolling();showStatusIsland("Sent to Terminal");return id})
})
}
const TERM_DESTRUCTIVE_RULES=[
{re:/\brm\s+(?:-\w*\s+)*-\w*[rf]/i,label:"recursive or forced delete"},
{re:/\bdd\s+if=/i,label:"raw disk write"},
{re:/\bmkfs(\.\w+)?\b/i,label:"formats a filesystem"},
{re:/\b(shutdown|reboot|halt|poweroff)\b/i,label:"shuts the machine down"},
{re:/\bformat\s+[a-z]:/i,label:"formats a drive"},
{re:/\bdel\s+\/[a-z]*[fsq]/i,label:"forced or recursive delete"},
{re:/Remove-Item\b(?=[^|]*-Recurse)(?=[^|]*-Force)/i,label:"recursive forced delete"},
{re:/\bchmod\s+(-R\s+)?777\b/,label:"world-writable permissions"},
{re:/:\s*\(\s*\)\s*\{.*\|.*&.*\}\s*;?\s*:/,label:"fork bomb"},
{re:/\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?\S*sh\b/i,label:"pipes a download into a shell"},
{re:/\b(iwr|invoke-webrequest|irm|invoke-restmethod)\b[^|]*\|\s*(iex|invoke-expression)\b/i,label:"pipes a download into a shell"},
{re:/\b(drop|truncate)\s+table\b/i,label:"destructive SQL"},
{re:/>\s*\/dev\/[sh]d[a-z]/i,label:"writes to a raw device"}
]
const TERM_ELEVATION_RULE=/\b(sudo|doas|runas|pkexec)\b|Start-Process\b[^|]*-Verb\s+RunAs/i
function termUnresolvedPlaceholders(text){
if(typeof snipIterPlaceholders!=="function")return []
const source=String(text||"")
return snipIterPlaceholders(source).filter((span)=>span[0]===0||source[span[0]-1]!=="$").map((span)=>span[2])
}
function termCommandRisks(text,meta){
meta=meta||{}
const risks=[]
if(String(meta.noise_level||"").toLowerCase()==="destructive")risks.push("This command is marked destructive.")
const unresolved=termUnresolvedPlaceholders(text)
if(unresolved.length)risks.push("Unresolved placeholder"+(unresolved.length>1?"s":"")+": "+unresolved.map((k)=>"{"+k+"}").join(", "))
TERM_DESTRUCTIVE_RULES.forEach((rule)=>{if(rule.re.test(text))risks.push("Matches a destructive pattern - "+rule.label+".")})
if(TERM_ELEVATION_RULE.test(text))risks.push("Requests elevated privileges.")
const tab=termFindTab(termState.activeId)
if(tab&&tab.elevated)risks.push("The active session is elevated.")
return risks
}
function termRunConfirmHtml(text,risks,destinationLabel){
const list=risks.length?`<ul class="term-risk-list">${risks.map((r)=>`<li>${termEscapeHtml(r)}</li>`).join("")}</ul>`:""
return `${list}<pre class="term-run-preview">${termEscapeHtml(text)}</pre><div class="term-run-destination">Destination: ${termEscapeHtml(destinationLabel)}</div>`
}
function termRunDestinationLabel(){
if(termState.runDestination==="new")return "a new terminal session"
const tab=termFindTab(termState.activeId)
return tab?tab.label:"a new terminal session"
}
function termShouldConfirmRun(mode,risks){
if(mode==="never")return false
if(mode==="always")return true
return risks.length>0
}
function termDispatchRun(text,meta){
meta=meta||{}
const risks=termCommandRisks(text,meta)
const mode=meta.confirmMode||"risky"
if(!termShouldConfirmRun(mode,risks))return termRunCommandText(text,meta)
const title=risks.length?"Run this command?":"Run this command in the terminal?"
return appConfirm(title,{okLabel:"Run",cancelLabel:"Cancel",wide:true,danger:risks.length>0,bodyHtml:termRunConfirmHtml(text,risks,termRunDestinationLabel())}).then((ok)=>{
if(!ok)return null
return termRunCommandText(text,meta)
})
}
function termStageCommand(text){
return termEnsureActiveSession().then(()=>{
const input=document.getElementById("terminalInput")
input.value=text
termUpdateLiveEcho()
input.focus()
showStatusIsland("Command ready - press Enter to run")
return null
})
}
function termAskClickAction(text,meta,anchorX,anchorY){
const items=[
{label:"Run in Terminal",icon:"command-line",fn:()=>termDispatchRun(text,meta)},
{label:"Type without running",icon:"edit",fn:()=>termStageCommand(text)},
{label:"Copy command",icon:"copy",fn:()=>{if(navigator.clipboard)navigator.clipboard.writeText(text).then(()=>showToast("Copied")).catch(()=>{})}}
]
openContextMenu(items,anchorX,anchorY)
}
function termPerformClickAction(action,text,meta,event){
if(!text||!text.trim()){showToast("Nothing to run","error");return}
if(action==="ask"){termAskClickAction(text,meta,event?event.clientX:120,event?event.clientY:120);return}
if(action==="run"){termDispatchRun(text,meta).catch((err)=>showToast(err&&err.message?err.message:"Run failed","error"));return}
if(action==="insert"){termStageCommand(text).catch((err)=>showToast(err&&err.message?err.message:"Terminal unavailable","error"));return}
if(navigator.clipboard)navigator.clipboard.writeText(text).catch(()=>{})
}
function termResolveClickAction(base,event){
if(!event)return base
if(event.ctrlKey||event.metaKey)return base==="run"?"copy":"run"
if(event.shiftKey)return "insert"
return base
}
const TERM_SUGGEST_LIMIT=8
const TERM_SUGGEST_MIN_CHARS=2
const TERM_SUGGEST_DEBOUNCE_MS=90
const TERM_SHORTCUT_ACTIONS=[
{id:"suggest",label:"Show command suggestions now",fallback:"Ctrl+Space"},
{id:"toggle_suggest",label:"Turn suggestions while typing on or off",fallback:"Ctrl+Shift+Space"},
{id:"command_search",label:"Search saved commands and insert one",fallback:"Ctrl+Shift+P"},
{id:"reopen_closed",label:"Reopen the last closed session",fallback:"Ctrl+Shift+T"},
{id:"pane_left",label:"Focus the split pane to the left",fallback:"Alt+ArrowLeft"},
{id:"pane_right",label:"Focus the split pane to the right",fallback:"Alt+ArrowRight"},
{id:"pane_up",label:"Focus the split pane above",fallback:"Alt+ArrowUp"},
{id:"pane_down",label:"Focus the split pane below",fallback:"Alt+ArrowDown"}
]
function termSuggestQuery(value,caret,manual){
const text=String(value||"")
if(text.indexOf("\n")!==-1)return null
if(caret!==undefined&&caret!==null&&caret!==text.length)return null
const q=text.replace(/^\s+/,"")
if(manual)return q
return q.trim().length>=TERM_SUGGEST_MIN_CHARS?q:null
}
function termSuggestFuzzy(text,q){
let from=0,gaps=0,first=-1
for(const ch of q){
const at=text.indexOf(ch,from)
if(at<0)return -1
if(first<0)first=at
else gaps+=at-from
from=at+1
}
return Math.max(0,99-gaps*3-first)
}
function termSuggestWordStart(text,token){
let at=text.indexOf(token)
while(at!==-1){
if(at===0||/[^a-z0-9]/.test(text[at-1]))return true
at=text.indexOf(token,at+1)
}
return false
}
function termSuggestScore(entry,query,family){
const cmd=String(entry.command||"").toLowerCase()
const q=String(query||"").toLowerCase().replace(/^\s+/,"")
let score=-1
if(!q.trim())score=1
else if(cmd===q.trimEnd())return -1
else if(cmd.startsWith(q))score=1000-Math.min(200,cmd.length-q.length)
else if(termSuggestWordStart(cmd,q.trim()))score=600
else{
const tokens=q.split(/\s+/).filter(Boolean)
const title=String(entry.title||"").toLowerCase()
const meta=[entry.category,entry.sub,entry.tags,entry.type].join(" ").toLowerCase()
let sum=0,ok=tokens.length>0
for(const token of tokens){
if(cmd.indexOf(token)!==-1)sum+=termSuggestWordStart(cmd,token)?30:20
else if(title.indexOf(token)!==-1)sum+=15
else if(meta.indexOf(token)!==-1)sum+=8
else{ok=false;break}
}
if(ok)score=300+sum
else if(tokens.length===1&&tokens[0].length>=3){
const fuzzy=termSuggestFuzzy(cmd,tokens[0])
if(fuzzy>=0)score=100+fuzzy
}
}
if(score<0)return -1
if(family&&entry.family&&entry.family!=="any")score+=entry.family===family?50:-80
return score
}
function termSuggestRank(entries,query,family,limit){
const scored=[]
const seen={}
;(entries||[]).forEach((entry)=>{
if(!entry||!entry.command)return
const key=String(entry.command).toLowerCase()
if(seen[key])return
const score=termSuggestScore(entry,query,family)
if(score<0)return
seen[key]=true
scored.push({entry,score})
})
scored.sort((a,b)=>b.score-a.score||a.entry.command.length-b.entry.command.length||String(a.entry.title||"").localeCompare(String(b.entry.title||"")))
return scored.slice(0,limit||TERM_SUGGEST_LIMIT).map((x)=>x.entry)
}
function termPlaceholderSpans(text){
if(typeof snipIterPlaceholders!=="function")return []
const source=String(text||"")
return snipIterPlaceholders(source).filter((span)=>span[0]===0||source[span[0]-1]!=="$")
}
function termNextPlaceholder(text,selStart,selEnd,dir){
const spans=termPlaceholderSpans(text)
if(!spans.length)return null
if(dir<0){
for(let i=spans.length-1;i>=0;i--)if(spans[i][1]<=selStart&&!(spans[i][0]===selStart&&spans[i][1]===selEnd))return spans[i]
return spans[spans.length-1]
}
for(const span of spans)if(span[0]>=selEnd&&!(span[0]===selStart&&span[1]===selEnd))return span
return spans[0]
}
function termShortcutFor(shortcuts,id){
const action=TERM_SHORTCUT_ACTIONS.find((a)=>a.id===id)
if(!action)return ""
if(shortcuts&&Object.prototype.hasOwnProperty.call(shortcuts,id))return shortcuts[id]||""
return action.fallback
}
function termShortcutActionFor(shortcuts,combo){
if(!combo)return null
const hit=TERM_SHORTCUT_ACTIONS.find((a)=>termShortcutFor(shortcuts,a.id)===combo)
return hit?hit.id:null
}
function termClipboardKeyAction(e,hasSelection){
if(!e.ctrlKey||e.altKey||e.metaKey)return null
const key=String(e.key||"").toLowerCase()
if(e.shiftKey&&key==="c")return "copy"
if(e.shiftKey&&key==="v")return "paste"
if(!e.shiftKey&&key==="c")return hasSelection?"copy":"interrupt"
return null
}
function termCwdDisplay(cwd){
return cwd?"‎"+cwd+"‎":""
}
let termSuggest={entries:[],sig:null,loadedAt:0,loading:null,open:false,items:[],selected:0,timer:null,forValue:null,manual:false,enabled:true,shortcuts:{}}
function termShortcutSheetItems(){
return TERM_SHORTCUT_ACTIONS.map((a)=>({keys:termShortcutFor(termSuggest.shortcuts,a.id)||"(not set)",desc:a.label}))
}
function termSuggestRefreshIndex(force){
if(termSuggest.loading)return termSuggest.loading
if(!force&&Date.now()-termSuggest.loadedAt<4000)return Promise.resolve(termSuggest.entries)
termSuggest.loading=bridgeCall("terminal.command_index",[termSuggest.sig]).then((res)=>{
if(res&&!res.unchanged&&Array.isArray(res.entries))termSuggest.entries=res.entries
if(res)termSuggest.sig=res.sig
termSuggest.loadedAt=Date.now()
return termSuggest.entries
}).catch(()=>termSuggest.entries).then((entries)=>{termSuggest.loading=null;return entries})
return termSuggest.loading
}
function termSuggestFamily(){
const tab=termFindTab(termState.activeId)
return tab?termShellFamily(tab.shellId):null
}
function termSuggestEl(){
let el=document.getElementById("terminalSuggest")
if(!el){
el=document.createElement("div")
el.id="terminalSuggest"
el.className="terminal-suggest hidden"
el.addEventListener("mousedown",(e)=>e.preventDefault())
el.addEventListener("click",(e)=>{
const row=e.target.closest(".term-suggest-item")
if(!row)return
const entry=termSuggest.items[parseInt(row.dataset.i,10)]
if(entry)termSuggestAccept(entry)
})
el.addEventListener("mousemove",(e)=>{
const row=e.target.closest(".term-suggest-item")
if(!row)return
const i=parseInt(row.dataset.i,10)
if(i!==termSuggest.selected){termSuggest.selected=i;termSuggestHighlight()}
})
document.body.appendChild(el)
}
return el
}
function termSuggestHide(){
clearTimeout(termSuggest.timer)
termSuggest.timer=null
if(!termSuggest.open)return
termSuggest.open=false
termSuggest.items=[]
termSuggest.forValue=null
const el=document.getElementById("terminalSuggest")
if(el)el.classList.add("hidden")
}
function termSuggestHighlight(){
const el=document.getElementById("terminalSuggest")
if(!el)return
el.querySelectorAll(".term-suggest-item").forEach((row,i)=>row.classList.toggle("active",i===termSuggest.selected))
const active=el.querySelector(".term-suggest-item.active")
if(active)active.scrollIntoView({block:"nearest"})
}
function termSuggestPosition(){
if(!termSuggest.open)return
const el=document.getElementById("terminalSuggest")
const cursor=document.querySelector("#terminalLiveEcho .term-cursor")
const out=termOutputEl()
if(!el||!cursor||!out){termSuggestHide();return}
const c=cursor.getBoundingClientRect(),box=out.getBoundingClientRect()
const width=Math.max(220,Math.min(460,box.width-16))
const left=Math.max(box.left+8,Math.min(c.left-12,box.right-width-8))
el.style.width=width+"px"
el.style.left=Math.round(left)+"px"
const h=el.offsetHeight
const above=c.top-h-4
const top=above>=box.top+4||c.bottom+h+4>window.innerHeight?Math.max(4,above):c.bottom+4
el.style.top=Math.round(top)+"px"
}
function termSuggestHighlightMatch(command,query){
const q=String(query||"").replace(/^\s+/,"")
if(q&&command.toLowerCase().startsWith(q.toLowerCase()))return '<b class="term-suggest-hit">'+termEscapeHtml(command.slice(0,q.length))+"</b>"+termEscapeHtml(command.slice(q.length))
return termEscapeHtml(command)
}
function termSuggestRender(query){
const el=termSuggestEl()
const family=termSuggestFamily()
el.innerHTML=termSuggest.items.map((entry,i)=>{
const first=String(entry.command).split(/\r?\n/)[0]+(String(entry.command).indexOf("\n")!==-1?" ...":"")
const meta=[entry.title,entry.category].filter(Boolean).join(" - ")
const other=entry.chainCaller?'<span class="term-suggest-type">chain</span>':family&&entry.family&&entry.family!=="any"&&entry.family!==family?'<span class="term-suggest-type">'+termEscapeHtml(entry.type)+"</span>":""
return '<div class="term-suggest-item'+(i===termSuggest.selected?" active":"")+'" data-i="'+i+'"><span class="term-suggest-cmd">'+termSuggestHighlightMatch(first,query)+'</span><span class="term-suggest-meta">'+other+termEscapeHtml(meta)+"</span></div>"
}).join("")+'<div class="term-suggest-foot">Tab accept - Up/Down choose - Esc dismiss</div>'
el.classList.remove("hidden")
termSuggest.open=true
termSuggestPosition()
}
function termSuggestShow(manual){
const input=document.getElementById("terminalInput")
if(!input||!termState.activeId)return
// "/" at position 0 also lists action chain callers (action-chains.js); "/" anywhere else is just a path.
const slash=typeof acTerminalSlashActive==="function"&&acTerminalSlashActive(input.value,input.selectionEnd)
const query=termSuggestQuery(input.value,input.selectionEnd,manual||slash)
if(query===null){termSuggestHide();return}
const run=()=>{
if(input.value!==termSuggest.pendingValue)return
const chainItems=slash?acTerminalSuggestItems(input.value):[]
// A bare "/" lists only chains; saved commands join in from the usual minimum length.
const ranked=(termSuggest.enabled||manual)&&termSuggestQuery(input.value,input.selectionEnd,manual)!==null
const items=chainItems.concat(ranked?termSuggestRank(termSuggest.entries,query,termSuggestFamily(),TERM_SUGGEST_LIMIT):[]).slice(0,TERM_SUGGEST_LIMIT)
if(!items.length){termSuggestHide();if(manual)showStatusIsland(termSuggest.entries.length?"No saved command matches":"No saved commands yet - add some on the Commands page");return}
termSuggest.items=items
termSuggest.selected=0
termSuggest.forValue=input.value
termSuggest.manual=!!manual
termSuggestRender(query)
}
termSuggest.pendingValue=input.value
if(slash)Promise.all([termSuggestRefreshIndex(manual),acRefreshCallers(false)]).then(run)
else if(manual||!termSuggest.entries.length)termSuggestRefreshIndex(manual).then(run)
else run()
}
function termSuggestOnInput(){
clearTimeout(termSuggest.timer)
const input=document.getElementById("terminalInput")
const slash=typeof acTerminalSlashActive==="function"&&acTerminalSlashActive(input.value,input.selectionEnd)
if(!slash&&!termSuggest.enabled&&!termSuggest.open)return
const keepManual=termSuggest.open&&termSuggest.manual
if(!slash&&termSuggestQuery(input.value,input.selectionEnd,keepManual)===null){termSuggestHide();return}
termSuggest.timer=setTimeout(()=>termSuggestShow(keepManual),TERM_SUGGEST_DEBOUNCE_MS)
}
function termSuggestLiveMap(){
return bridgeCall("search.live_target").then((res)=>(res&&res.map)||{}).catch(()=>({}))
}
function termApplyStagedCommand(text){
const input=document.getElementById("terminalInput")
input.value=text
const tab=termFindTab(termState.activeId)
if(tab)tab.historyIdx=null
const spans=termPlaceholderSpans(text)
input.focus()
if(spans.length){
input.setSelectionRange(spans[0][0],spans[0][1])
showStatusIsland("Type a value for {"+spans[0][2]+"}"+(spans.length>1?" - Tab jumps to the next placeholder":""))
}else input.setSelectionRange(text.length,text.length)
termUpdateLiveEcho()
}
function termSuggestAccept(entry){
if(entry&&entry.chainCaller&&typeof loyaRunChainByCaller==="function"){termClearStagedInput();loyaRunChainByCaller(entry.chainCaller,{source:"terminal"});return}
termSuggestHide()
termSuggest.pendingValue=null
termSuggestLiveMap().then((map)=>termApplyStagedCommand(termResolveForTarget(entry.command,{values:map})))
}
function termJumpPlaceholder(dir){
const input=document.getElementById("terminalInput")
const span=termNextPlaceholder(input.value,input.selectionStart,input.selectionEnd,dir)
if(!span)return false
input.setSelectionRange(span[0],span[1])
termUpdateLiveEcho()
return true
}
function termSetSuggestEnabled(enabled,announce){
termSuggest.enabled=!!enabled
if(!enabled)termSuggestHide()
return bridgeCall("terminal.set_run_behaviour",[{suggest_enabled:!!enabled}]).then((s)=>{
if(announce)showStatusIsland(enabled?"Command suggestions on":"Command suggestions off")
if(typeof setApplyTerminalSuggest==="function")setApplyTerminalSuggest(s)
return s
}).catch(()=>null)
}
function termSuggestHandleKey(e){
if(e.isComposing)return false
const action=termShortcutActionFor(termSuggest.shortcuts,shortcutFromEvent(e))
if(action==="suggest"){e.preventDefault();termSuggestShow(true);return true}
if(action==="toggle_suggest"){e.preventDefault();termSetSuggestEnabled(!termSuggest.enabled,true);return true}
if(action==="command_search"){e.preventDefault();termSuggestHide();termOpenCommandSearch();return true}
if(!termSuggest.open)return false
const plain=!e.ctrlKey&&!e.altKey&&!e.metaKey
if(plain&&!e.shiftKey&&(e.key==="ArrowDown"||e.key==="ArrowUp")){
e.preventDefault()
const n=termSuggest.items.length
termSuggest.selected=(termSuggest.selected+(e.key==="ArrowDown"?1:-1)+n)%n
termSuggestHighlight()
return true
}
const input=document.getElementById("terminalInput")
if(plain&&!e.shiftKey&&(e.key==="Tab"||(e.key==="ArrowRight"&&input.selectionEnd===input.value.length))){
e.preventDefault()
const entry=termSuggest.items[termSuggest.selected]
if(entry)termSuggestAccept(entry)
return true
}
if(e.key==="Escape"){e.preventDefault();termSuggestHide();return true}
return false
}
function termOpenCommandSearch(){
const anchor=document.querySelector("#terminalLiveEcho .term-cursor")||termOutputEl()
if(!anchor)return
const pop=termOpenPopover(anchor,420)
pop.classList.add("term-cmd-search")
pop.innerHTML='<div class="terminal-popover-title">Insert a saved command</div><input type="text" class="term-cmd-search-input" id="termCmdSearchInput" placeholder="Search command, title or category..." autocomplete="off" spellcheck="false"><div class="term-cmd-search-list" id="termCmdSearchList"></div>'
const input=pop.querySelector("#termCmdSearchInput")
const list=pop.querySelector("#termCmdSearchList")
let items=[],selected=0
const close=()=>{termClosePopover();document.getElementById("terminalInput").focus()}
const highlight=()=>{list.querySelectorAll(".term-suggest-item").forEach((row,i)=>row.classList.toggle("active",i===selected));const a=list.querySelector(".active");if(a)a.scrollIntoView({block:"nearest"})}
const render=()=>{
items=termSuggestRank(termSuggest.entries,input.value,termSuggestFamily(),40)
selected=0
if(!items.length){list.innerHTML='<div class="terminal-popover-empty">'+(termSuggest.entries.length?"No matching commands":"No saved commands yet")+"</div>";return}
list.innerHTML=items.map((entry,i)=>'<div class="term-suggest-item'+(i===0?" active":"")+'" data-i="'+i+'"><span class="term-suggest-cmd">'+termEscapeHtml(String(entry.command).split(/\r?\n/)[0])+'</span><span class="term-suggest-meta">'+termEscapeHtml([entry.title,entry.category,entry.type].filter(Boolean).join(" - "))+"</span></div>").join("")
}
const accept=(i)=>{const entry=items[i];if(!entry)return;termClosePopover();termSuggestAccept(entry)}
input.addEventListener("input",render)
input.addEventListener("keydown",(e)=>{
e.stopPropagation()
if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();if(items.length){selected=(selected+(e.key==="ArrowDown"?1:-1)+items.length)%items.length;highlight()}return}
if(e.key==="Enter"){e.preventDefault();accept(selected);return}
if(e.key==="Escape"){e.preventDefault();close()}
})
list.addEventListener("mousedown",(e)=>e.preventDefault())
list.addEventListener("click",(e)=>{const row=e.target.closest(".term-suggest-item");if(row)accept(parseInt(row.dataset.i,10))})
termSuggestRefreshIndex(true).then(()=>{if(document.getElementById("termCmdSearchInput")===input)render()})
render()
setTimeout(()=>input.focus(),0)
}
function termApplySuggestSettings(s){
if(!s)return
termSuggest.enabled=s.suggest_enabled!==false
termSuggest.shortcuts=s.shortcuts||{}
if(!termSuggest.enabled)termSuggestHide()
}
const TERM_JOB_SOURCE_ICON={terminal:"command-line",snippet:"copy",command:"list",playbook:"target",ai:"brain"}
// What the user reads for a job source. "snippet" stays the stored value; the page is called Quick Run.
const TERM_JOB_SOURCE_LABEL={terminal:"Typed in the terminal",snippet:"Quick Run",command:"Commands",playbook:"Action chain",ai:"AI",batch:"Fan-out run"}
function termJobDuration(job){
const start=Date.parse(job.started_at||"")
const end=job.ended_at?Date.parse(job.ended_at):Date.now()
if(isNaN(start)||isNaN(end)||end<start)return ""
const seconds=Math.round((end-start)/1000)
if(seconds<60)return seconds+"s"
if(seconds<3600)return Math.floor(seconds/60)+"m "+(seconds%60)+"s"
return Math.floor(seconds/3600)+"h "+Math.floor((seconds%3600)/60)+"m"
}
function termIsBackgroundJob(sessionId){
const id=String(sessionId||"")
return id.indexOf("batch:")===0||id.indexOf("chain:")===0
}
function termJobSessionLabel(sessionId){
if(termIsBackgroundJob(sessionId))return "background"
const tab=termFindTab(sessionId)
return tab?tab.label:"closed session"
}
function termChainSteps(chainId){
return (termState.jobs||[]).filter((job)=>job.chain_id===chainId).slice().sort((a,b)=>(a.chain_pos||0)-(b.chain_pos||0))
}
function termChainProgress(chainId){
const steps=termChainSteps(chainId)
const settled=steps.filter((step)=>step.state!=="pending"&&step.state!=="running")
return {total:steps.length,settled:settled.length,failed:steps.filter((step)=>step.state==="failed").length,skipped:steps.filter((step)=>step.state==="skipped").length,active:steps.some((step)=>step.state==="running"||step.state==="pending"),label:steps.length?steps[0].label||"Chain":"Chain",source:steps.length?steps[0].source:"playbook",name:steps.length?steps[0].chain_name||"":""}
}
function termGroupJobRows(rows){
const out=[]
const seen={}
rows.forEach((job)=>{
if(!job.chain_id){out.push({kind:"job",job:job});return}
if(seen[job.chain_id])return
seen[job.chain_id]=true
out.push({kind:"chain",chainId:job.chain_id,steps:rows.filter((row)=>row.chain_id===job.chain_id).slice().sort((a,b)=>(a.chain_pos||0)-(b.chain_pos||0))})
})
return out
}
function termChainGroupHtml(chainId,visibleSteps){
const progress=termChainProgress(chainId)
const folded=!!termState.chainsFolded[chainId]
const percent=progress.total?Math.round(progress.settled/progress.total*100):0
const state=progress.active?"running":progress.failed?"failed":progress.skipped?"stopped":"done"
const summary=progress.settled+"/"+progress.total+(progress.failed?" - "+progress.failed+" failed":"")+(progress.skipped?" - "+progress.skipped+" skipped":"")
const action=progress.active?'<span class="terminal-job-action" data-chain-action="cancel" title="Cancel the rest of this chain"><i class="icon icon-stop"></i></span>':'<span class="terminal-job-action" data-chain-action="dismiss" title="Dismiss this chain"><i class="icon icon-close"></i></span>'
const head='<div class="terminal-chain-head '+state+'" data-chain="'+termEscapeHtml(chainId)+'"><span class="terminal-chain-toggle"><i class="icon icon-arrow-down"></i></span><span class="terminal-chain-main"><span class="terminal-chain-title">'+termEscapeHtml((progress.source==="playbook"?"Action chain":"Command chain")+(progress.name?": "+progress.name:""))+'</span><span class="terminal-chain-bar"><span class="terminal-chain-fill" style="width:'+percent+'%"></span></span></span><span class="terminal-chain-count">'+termEscapeHtml(summary)+'</span>'+action+'</div>'
return '<div class="terminal-chain-group'+(folded?" folded":"")+'">'+head+'<div class="terminal-chain-steps">'+visibleSteps.map(termJobRowHtml).join("")+'</div></div>'
}
function termFilteredJobs(){
const rows=termState.jobs||[]
const filter=termState.jobsFilter
if(filter==="running")return rows.filter((j)=>j.state==="running")
if(filter==="failed")return rows.filter((j)=>j.state==="failed"||j.state==="killed"||j.state==="orphaned")
if(filter==="session")return rows.filter((j)=>j.session_id===termState.activeId)
return rows
}
function termRunningJobCount(){
return (termState.jobs||[]).filter((j)=>j.state==="running").length
}
function termUpdateJobsBadge(){
const badge=document.getElementById("terminalJobsBadge")
if(!badge)return
const count=termRunningJobCount()
badge.textContent=count>99?"99+":String(count)
badge.classList.toggle("hidden",count===0)
}
function termJobRowHtml(job){
const exitLabel=job.state==="running"?"running":termExitLabel(job.exit_code)||job.state
const exitClass=job.state==="done"?"good":(job.state==="failed"||job.state==="killed")?"bad":""
const duration=termJobDuration(job)
const icon=TERM_JOB_SOURCE_ICON[job.source]||"command-line"
const meta=[termJobSessionLabel(job.session_id),duration,job.state==="skipped"?job.skip_reason:""].filter(Boolean).join(" - ")
const action=job.state==="running"?'<span class="terminal-job-action" data-action="kill" title="Interrupt"><i class="icon icon-stop"></i></span>':'<span class="terminal-job-action" data-action="dismiss" title="Dismiss"><i class="icon icon-close"></i></span>'
return '<button type="button" class="terminal-job-row'+(job.session_id===termState.activeId?" current":"")+'" data-job="'+termEscapeHtml(job.job_key)+'" data-session="'+termEscapeHtml(job.session_id||"")+'"><span class="terminal-job-dot '+termEscapeHtml(job.state)+'"></span><span class="terminal-job-main"><span class="terminal-job-cmd">'+termEscapeHtml(job.label&&job.source==="batch"?job.label+"  |  "+(job.command||""):(job.command||job.label||""))+'</span><span class="terminal-job-meta"><i class="icon icon-'+icon+'" title="'+termEscapeHtml(TERM_JOB_SOURCE_LABEL[job.source]||job.source||"")+'"></i>'+termEscapeHtml(meta)+'</span></span><span class="terminal-job-exit '+exitClass+'">'+termEscapeHtml(exitLabel)+'</span>'+action+'</button>'
}
function termRenderJobs(){
const list=document.getElementById("terminalJobsList")
if(!list)return
const rows=termFilteredJobs()
const grouped=termGroupJobRows(rows).map((entry)=>entry.kind==="chain"?termChainGroupHtml(entry.chainId,entry.steps):termJobRowHtml(entry.job))
list.innerHTML=grouped.length?grouped.join(""):'<div class="terminal-jobs-empty">No jobs to show.</div>'
document.querySelectorAll(".terminal-jobs-filter").forEach((btn)=>btn.classList.toggle("active",btn.dataset.state===termState.jobsFilter))
termUpdateJobsBadge()
}
function termRefreshJobs(){
return bridgeCall("terminal.jobs_list",[null,200]).then((rows)=>{
termState.jobs=Array.isArray(rows)?rows:[]
termRenderJobs()
return termState.jobs
}).catch(()=>{})
}
function termJumpToJob(sessionId,jobKey){
if(termIsBackgroundJob(sessionId)){
const job=termFindJob(jobKey)
if(job)termShowJobOutput(job)
return
}
const tab=termFindTab(sessionId)
if(!tab){showToast("That session is closed - its output is gone","error");return}
if(termState.activeId!==sessionId)termActivateTab(sessionId)
const record=(tab.jobHistory||[]).find((j)=>j.jobId===jobKey)
if(!record){showToast("Output for this job is no longer in the scrollback");return}
const out=termOutputEl()
const ratio=tab.buffer.length?record.startIdx/tab.buffer.length:0
termState.followOutput=false
out.scrollTop=Math.max(0,Math.round(out.scrollHeight*ratio)-40)
termUpdateJumpButton()
}
function termKillJob(job){
if(!job)return
if(termIsBackgroundJob(job.session_id)){
bridgeCall("terminal.batch_cancel",[job.job_key]).then(()=>termRefreshJobs()).catch(()=>{})
return
}
const owner=termFindTab(job.session_id)
if(owner&&owner.activeJob)owner.activeJob.interrupted=true
bridgeCall("terminal.job_interrupt",[job.session_id]).then((ok)=>{
if(!ok)return bridgeCall("terminal.job_mark",[job.job_key,"killed"])
showStatusIsland("Interrupt sent to "+termJobSessionLabel(job.session_id))
}).then(()=>termRefreshJobs()).catch((err)=>showToast(err&&err.message?err.message:"Could not interrupt","error"))
}
function termDismissJob(job){
if(!job)return
bridgeCall("terminal.job_delete",[job.job_key]).then(()=>termRefreshJobs()).catch(()=>{})
}
function termOpenJobMenu(job,x,y){
if(!job)return
const items=[
{label:"Re-run",icon:"play",fn:()=>termDispatchRun(job.command||"",{confirmMode:termState.commandRunConfirm,source:"terminal"}).catch(()=>{})},
{label:"Re-run in new session",icon:"add",fn:()=>termDispatchRun(job.command||"",{confirmMode:termState.commandRunConfirm,destination:"new",source:"terminal"}).catch(()=>{})},
{sep:true},
{label:"Copy command",icon:"copy",fn:()=>{if(navigator.clipboard)navigator.clipboard.writeText(job.command||"").then(()=>showToast("Copied")).catch(()=>{})}},
{label:"View output",icon:"list",fn:()=>termShowJobOutput(job)},
{label:"Send output to a note",icon:"edit",fn:()=>termSendJobToNote(job)},
{label:"Save for report",icon:"report",disabled:typeof ReportEvidence==="undefined",fn:()=>ReportEvidence.saveJobFromList(job,termJobOutput(job))},
{label:"Copy output",icon:"copy",disabled:!termJobOutput(job),fn:()=>{const text=termJobOutput(job);if(text&&navigator.clipboard)navigator.clipboard.writeText(text).then(()=>showToast("Copied output")).catch(()=>{})}},
{sep:true},
{label:job.state==="failed"||job.state==="killed"?"Ask the AI why this failed":"Explain this output with AI",icon:"brain",fn:()=>job.state==="failed"||job.state==="killed"?termAiTriageJob(job):termAiExplainJob(job)},
{sep:true},
{label:job.state==="running"?"Interrupt":"Dismiss",icon:job.state==="running"?"stop":"trash",fn:()=>job.state==="running"?termKillJob(job):termDismissJob(job)}
]
openContextMenu(items,x,y)
}
function termJobOutput(job){
const tab=termFindTab(job.session_id)
if(!tab)return ""
const record=(tab.jobHistory||[]).find((j)=>j.jobId===job.job_key)
if(!record)return ""
return tab.buffer.slice(record.startIdx,record.endIdx===null||record.endIdx===undefined?tab.buffer.length:record.endIdx)
}
function termFindJob(jobKey){
return (termState.jobs||[]).find((j)=>j.job_key===jobKey)
}
function termCancelChain(chainId){
bridgeCall("terminal.chain_cancel",[chainId]).then(()=>{
showStatusIsland("Chain cancelled - remaining steps skipped")
termRefreshJobs()
}).catch((err)=>showToast(err&&err.message?err.message:"Could not cancel the chain","error"))
}
function termDismissChain(chainId){
const keys=termChainSteps(chainId).map((step)=>step.job_key)
Promise.all(keys.map((key)=>bridgeCall("terminal.job_delete",[key]).catch(()=>{}))).then(()=>{
delete termState.chainsFolded[chainId]
termRefreshJobs()
})
}
function termHandleChainClick(e){
const head=e.target.closest(".terminal-chain-head")
if(!head)return false
const chainId=head.dataset.chain
const action=e.target.closest(".terminal-job-action")
if(action){
e.stopPropagation()
if(action.dataset.chainAction==="cancel")termCancelChain(chainId)
else termDismissChain(chainId)
return true
}
if(termState.chainsFolded[chainId])delete termState.chainsFolded[chainId]
else termState.chainsFolded[chainId]=true
termRenderJobs()
return true
}
function termHandleJobsClick(e){
if(termHandleChainClick(e))return
const row=e.target.closest(".terminal-job-row")
if(!row)return
const job=termFindJob(row.dataset.job)
const action=e.target.closest(".terminal-job-action")
if(action){
e.stopPropagation()
if(action.dataset.action==="kill")termKillJob(job)
else termDismissJob(job)
return
}
termJumpToJob(row.dataset.session,row.dataset.job)
}
function termToggleJobBlocks(){
termState.jobBlocks=!termState.jobBlocks
document.getElementById("terminalBlocksBtn").classList.toggle("active",termState.jobBlocks)
termState.tabs.forEach(termInvalidateRender)
termRenderAllPanes()
showStatusIsland(termState.jobBlocks?"Job blocks on":"Job blocks off")
}
function termPaletteAction(action){
if(!termState.enabled){showToast("Enable the Terminal extension in Settings first","error");return}
if(!termState.open)termOpenPanel()
action()
}
function termRunLastCommand(){
const tab=termFindTab(termState.activeId)
const last=tab&&tab.history.length?tab.history[tab.history.length-1]:null
if(!last){showToast("No command has been run yet","error");return}
termDispatchRun(last,{confirmMode:termState.commandRunConfirm,source:"terminal"}).catch((err)=>showToast(err&&err.message?err.message:"Run failed","error"))
}
function termKillAllJobs(){
const running=(termState.jobs||[]).filter((job)=>job.state==="running")
if(!running.length){showToast("No jobs are running");return}
appConfirm("Interrupt "+running.length+" running job"+(running.length===1?"":"s")+"?",{okLabel:"Interrupt all",cancelLabel:"Cancel",danger:true}).then((ok)=>{
if(!ok)return
running.forEach(termKillJob)
showStatusIsland("Interrupt sent to "+running.length+" jobs")
})
}
function termToggleJobsDrawer(){
termState.jobsOpen=!termState.jobsOpen
if(termState.jobsOpen&&termState.sessionsOpen)termToggleSessionsDrawer()
document.getElementById("terminalJobsDrawer").classList.toggle("hidden",!termState.jobsOpen)
if(termState.jobsOpen)termRefreshJobs()
}
function termRecordJobOffset(tab,job){
if(!tab||!job)return
if(typeof ReportEvidence!=="undefined")ReportEvidence.onJobStart(tab.sessionId,job)
if(!tab.jobHistory)tab.jobHistory=[]
tab.jobHistory.push({jobId:job.jobId,command:job.command,startIdx:job.startIdx,endIdx:null,startedAt:job.startedAt,endedAt:null,exitCode:null,folded:false})
if(tab.jobHistory.length>200)tab.jobHistory.shift()
termInvalidateRender(tab)
}
function termCloseJobOffset(tab,jobId,endIdx,exitCode){
if(!tab||!tab.jobHistory)return
const record=tab.jobHistory.find((j)=>j.jobId===jobId)
if(!record)return
record.endIdx=endIdx
record.endedAt=Date.now()
record.exitCode=exitCode===undefined?null:exitCode
if(typeof ReportEvidence!=="undefined")ReportEvidence.onJobFinish(tab.sessionId,record)
termInvalidateRender(tab)
}
function termResolveForTarget(template,target){
if(typeof snipIterPlaceholders!=="function")return template
const spans=snipIterPlaceholders(template)
if(!spans.length)return template
const values={}
Object.keys(target.values||{}).forEach((key)=>{values[key.toLowerCase()]=target.values[key]})
let out="",last=0
spans.forEach(([start,end,key])=>{
out+=template.slice(last,start)
const lookup=key.toLowerCase()
out+=Object.prototype.hasOwnProperty.call(values,lookup)&&values[lookup]!==""?values[lookup]:"{"+key+"}"
last=end
})
return out+template.slice(last)
}
function termFanoutRowsHtml(template,targets,selected){
return targets.map((target)=>{
const resolved=termResolveForTarget(template,target)
const unresolved=termUnresolvedPlaceholders(resolved).length>0
const checked=selected[target.id]?" checked":""
return '<label class="term-fanout-row'+(unresolved?" unresolved":"")+'"><input type="checkbox" data-target="'+termEscapeHtml(target.id)+'"'+checked+'><span class="term-fanout-name">'+termEscapeHtml(target.name)+'</span><span class="term-fanout-cmd">'+termEscapeHtml(resolved)+'</span></label>'
}).join("")
}
function termOpenFanoutModal(template,meta){
if(!template||!template.trim()){showToast("Nothing to run","error");return}
bridgeCall("targets.targets").then((targets)=>{
if(!targets||!targets.length){showToast("No targets defined yet","error");return}
const selected={}
targets.forEach((t)=>{selected[t.id]=t.status==="live"})
const el=document.createElement("div")
el.className="term-fanout-modal glass-panel"
el.innerHTML='<div class="term-fanout-title">Run against targets</div><pre class="term-run-preview">'+termEscapeHtml(template)+'</pre><div class="term-fanout-controls"><label class="term-fanout-all"><input type="checkbox" id="termFanoutAll"><span>Select all</span></label><span class="term-fanout-spacer"></span><label class="term-fanout-limit">Run at once<input type="number" id="termFanoutLimit" min="1" max="16" value="4"></label></div><div class="term-fanout-list" id="termFanoutList">'+termFanoutRowsHtml(template,targets,selected)+'</div><div class="term-fanout-note" id="termFanoutNote"></div><div class="term-fanout-actions"><button type="button" id="termFanoutCancel">Cancel</button><button type="button" class="term-fanout-run" id="termFanoutRun">Run</button></div>'
openModal(el)
const list=el.querySelector("#termFanoutList")
const note=el.querySelector("#termFanoutNote")
function refreshNote(){
const count=Object.keys(selected).filter((id)=>selected[id]).length
const unresolved=targets.filter((t)=>selected[t.id]&&termUnresolvedPlaceholders(termResolveForTarget(template,t)).length).length
note.textContent=count?count+" target"+(count===1?"":"s")+" selected"+(unresolved?" - "+unresolved+" still have unresolved placeholders":""):"Select at least one target."
note.classList.toggle("warn",unresolved>0)
}
list.addEventListener("change",(e)=>{
const box=e.target.closest("input[type=checkbox]")
if(!box)return
selected[box.dataset.target]=box.checked
refreshNote()
})
el.querySelector("#termFanoutAll").addEventListener("change",(e)=>{
targets.forEach((t)=>{selected[t.id]=e.target.checked})
list.innerHTML=termFanoutRowsHtml(template,targets,selected)
refreshNote()
})
el.querySelector("#termFanoutCancel").addEventListener("click",closeModal)
el.querySelector("#termFanoutRun").addEventListener("click",()=>{
const chosen=targets.filter((t)=>selected[t.id])
if(!chosen.length){showToast("Select at least one target","error");return}
const limit=parseInt(el.querySelector("#termFanoutLimit").value,10)||4
const items=chosen.map((t)=>({label:t.name,command:termResolveForTarget(template,t)}))
const risky=items.filter((item)=>termCommandRisks(item.command,meta||{}).length).length
closeModal()
const proceed=()=>termStartFanout(items,limit)
if(!risky||termState.snippetRunConfirm==="never"){proceed();return}
appConfirm("Run this command against "+items.length+" targets?",{okLabel:"Run all",cancelLabel:"Cancel",wide:true,danger:true,bodyHtml:'<div class="term-risk-list-wrap">'+risky+" of "+items.length+' resolved commands were flagged risky.</div><pre class="term-run-preview">'+termEscapeHtml(items.map((i)=>i.command).join("\n"))+"</pre>"}).then((ok)=>{if(ok)proceed()})
})
refreshNote()
}).catch((err)=>showToast(err&&err.message?err.message:"Could not load targets","error"))
}
function termStartFanout(items,limit){
const shellSelect=document.getElementById("terminalShellSelect")
const shellId=shellSelect?shellSelect.value:""
bridgeCall("terminal.batch_start",[shellId,items,limit,"batch"]).then((res)=>{
showStatusIsland("Running "+items.length+" jobs, "+res.concurrency+" at a time")
if(!termState.jobsOpen)termToggleJobsDrawer()
termState.jobsFilter="all"
termRefreshJobs()
termStartJobsWatch()
}).catch((err)=>showToast(err&&err.message?err.message:"Batch failed","error"))
}
function termRunChain(items,policy,description){
const shellSelect=document.getElementById("terminalShellSelect")
const shellId=shellSelect?shellSelect.value:""
return bridgeCall("terminal.chain_start",[shellId,items,policy,"playbook"]).then((res)=>{
showStatusIsland(description+" - "+items.length+" step"+(items.length===1?"":"s")+(policy==="stop"?", stopping on the first failure":", continuing past failures"))
if(!termState.jobsOpen)termToggleJobsDrawer()
termState.jobsFilter="all"
termRefreshJobs()
termStartJobsWatch()
return res
}).catch((err)=>{
showToast(err&&err.message?err.message:"Could not start the chain","error")
return null
})
}
function termRunPlaybook(playbookId,name){
return bridgeCall("playbooks.commands",[playbookId]).then((items)=>{
if(!items||!items.length){showToast("This action chain has no runnable steps","error");return null}
const unresolved=items.filter((item)=>termUnresolvedPlaceholders(item.command).length).length
const risky=items.filter((item)=>termCommandRisks(item.command,{noise_level:item.noise_level}).length).length
const notes=[]
if(risky)notes.push("<li>"+risky+" of "+items.length+" steps were flagged risky.</li>")
if(unresolved)notes.push("<li>"+unresolved+" step"+(unresolved===1?"":"s")+" still contain unresolved placeholders.</li>")
const body='<div class="term-run-destination">Steps run one at a time in the background, not in a terminal session.</div>'+(notes.length?'<ul class="term-risk-list">'+notes.join("")+"</ul>":"")+'<pre class="term-run-preview">'+termEscapeHtml(items.map((item,index)=>(index+1)+". "+item.command).join("\n"))+"</pre>"
return termAskChainPolicy(name,items.length,body,risky>0).then((policy)=>{
if(!policy)return null
return termRunChain(items,policy,"Running "+name)
})
}).catch((err)=>{
showToast(err&&err.message?err.message:"Could not load the action chain","error")
return null
})
}
function termAskChainPolicy(name,count,bodyHtml,danger){
return appConfirm("Run "+name+" as a chain of "+count+" step"+(count===1?"":"s")+"?",{okLabel:"Stop on failure",cancelLabel:"Cancel",extraLabel:"Run every step",wide:true,danger:danger,bodyHtml:bodyHtml}).then((choice)=>{
if(choice==="extra")return "continue"
return choice?"stop":null
})
}
function termAiRequestBodyHtml(request){
const risk=request.destructive?'<ul class="term-risk-list"><li>This command matches a destructive pattern.</li></ul>':""
const reason=request.reason?'<div class="term-run-destination">The AI says: '+termEscapeHtml(request.reason)+"</div>":""
return risk+'<pre class="term-run-preview">'+termEscapeHtml(request.command)+"</pre>"+reason+'<div class="term-run-destination">It will run in the background as a job, not in your session.</div>'
}
function termPromptAiRequest(request){
termState.aiPrompting=true
return appConfirm("The AI wants to run a command",{okLabel:"Approve and run",cancelLabel:"Deny",wide:true,danger:true,bodyHtml:termAiRequestBodyHtml(request)}).then((approved)=>{
return bridgeCall("terminal.ai_request_resolve",[request.request_id,!!approved]).then(()=>{
showStatusIsland(approved?"Approved - running as an AI job":"Denied",approved?"":"error")
if(approved){
if(!termState.jobsOpen)termToggleJobsDrawer()
termRefreshJobs()
termStartJobsWatch()
}
})
}).catch(()=>{}).finally(()=>{termState.aiPrompting=false})
}
function termCheckAiRequests(){
if(termState.aiPrompting)return Promise.resolve()
return bridgeCall("terminal.ai_requests",[true]).then((rows)=>{
if(!rows||!rows.length)return
return termPromptAiRequest(rows[0])
}).catch(()=>{})
}
function termStartAiRequestWatch(){
if(termState.aiWatch)return
termState.aiWatch=setInterval(termCheckAiRequests,2000)
}
function termStartJobsWatch(){
if(termState.jobsWatch)return
termState.jobsWatch=setInterval(()=>{
termRefreshJobs().then(()=>{
if(!termRunningJobCount()){clearInterval(termState.jobsWatch);termState.jobsWatch=null;showStatusIsland("All jobs finished")}
})
},1200)
}
const TERM_AI_MAX_CHARS=12000
function termAiTail(text){
const body=String(text||"")
return body.length>TERM_AI_MAX_CHARS?body.slice(-TERM_AI_MAX_CHARS):body
}
function termAiUnavailable(){
if(typeof aiOpenPanel!=="function"||typeof aiSendExternalPrompt!=="function")return "The AI panel is not loaded."
if(typeof aiState!=="undefined"&&!aiState.enabled)return "Enable an AI provider in Settings first."
return ""
}
function termAiAsk(prompt){
const blocked=termAiUnavailable()
if(blocked)return Promise.reject(new Error(blocked))
return aiOpenPanel().then(()=>aiSendExternalPrompt(prompt))
}
function termAiRedact(text){
if(!text||!text.trim())return Promise.resolve({text:"",found:[]})
return bridgeCall("terminal.redact",[text]).catch(()=>({text:text,found:[]}))
}
function termAiRedactionNote(found){
if(!found||!found.length)return ""
const total=found.reduce((sum,entry)=>sum+(entry.count||0),0)
return total+" secret"+(total===1?"":"s")+" redacted before sending"
}
function termAiSendWithOutput(buildPrompt,rawOutput,successMessage){
if(!rawOutput||!rawOutput.trim()){showToast("There is no output to send","error");return Promise.resolve("")}
return termAiRedact(termAiTail(rawOutput)).then((result)=>{
const note=termAiRedactionNote(result.found)
if(note)showToast(note)
return termAiAsk(buildPrompt(result.text)).then((reply)=>{
if(successMessage)showStatusIsland(successMessage)
return reply
})
}).catch((err)=>{
showToast(err&&err.message?err.message:"The AI request failed","error")
return ""
})
}
function termAiExplainOutput(text,heading){
return termAiSendWithOutput((safe)=>`You are helping a penetration tester read terminal output. Explain what this ${heading} shows. Be concrete and brief - no filler, no restating the command back. Call out anything security relevant: open services, versions worth checking, credentials, misconfigurations, errors that matter. If the output is unremarkable, say so in one line rather than padding.\n\n---\n${safe}\n---`,text,"AI explained the output")
}
function termAiSummariseSession(){
const tab=termFindTab(termState.activeId)
if(!tab){showToast("Open a terminal session first","error");return Promise.resolve("")}
return termAiSendWithOutput((safe)=>`Summarise this terminal session for a pentest engagement note. Base it ONLY on what is below - do not invent hosts, ports or findings. Keep it tight. Use exactly this structure, omitting any section with nothing to report:\n\n**What was run:** (the commands that mattered, not every keystroke)\n**Findings:** (most severe first, one line each)\n**Hosts and services seen:**\n**Next steps:** (concrete and actionable)\n\n---\n${safe}\n---`,tab.buffer,"AI summarised the session")
}
function termAiTriageJob(job){
if(!job)return Promise.resolve("")
return termAiJobOutput(job).then((output)=>termAiRedact(termAiTail(output)).then((result)=>{
const note=termAiRedactionNote(result.found)
if(note)showToast(note)
const exit=job.exit_code===null||job.exit_code===undefined?job.state:"exit code "+job.exit_code
return termAiAsk(`A command failed in a pentest terminal. Diagnose it. Give the most likely cause first, then how to fix it. Be specific to this error - no generic troubleshooting checklists. If a corrected command is the answer, put it alone in a fenced code block.\n\nCommand: ${job.command||""}\nResult: ${exit}\n\nOutput:\n---\n${result.text||"(no output was captured)"}\n---`)
})).then((reply)=>{
showStatusIsland("AI triaged the failure")
return reply
}).catch((err)=>{
showToast(err&&err.message?err.message:"The AI request failed","error")
return ""
})
}
function termAiJobOutput(job){
if(job._output)return Promise.resolve(job._output)
const local=termJobOutput(job)
if(local&&local.trim())return Promise.resolve(local)
return bridgeCall("terminal.batch_output",[job.job_key]).catch(()=>"")
}
function termAiExplainJob(job){
if(!job)return Promise.resolve("")
return termAiJobOutput(job).then((output)=>termAiExplainOutput(output,"output of `"+(job.command||"the command")+"`"))
}
function termExtractCommand(reply){
const fenced=String(reply||"").match(/```[a-z]*\r?\n([\s\S]*?)```/)
if(!fenced)return ""
const lines=fenced[1].split(/\r?\n/).map((line)=>line.trim()).filter(Boolean)
for(const line of lines){
if(line.startsWith("#")||line.startsWith("//"))continue
return line.replace(/^[$>]\s+/,"")
}
return ""
}
function termAiSuggestNext(){
const tab=termFindTab(termState.activeId)
if(!tab){showToast("Open a terminal session first","error");return Promise.resolve("")}
const recent=(tab.jobHistory||[]).slice(-6).map((record)=>record.command).filter(Boolean).join("\n")||"(nothing yet)"
return termAiRedact(termAiTail(tab.buffer)).then((result)=>{
const note=termAiRedactionNote(result.found)
if(note)showToast(note)
return termAiAsk(`You are assisting a penetration tester at a ${tab.shellId||"shell"} prompt. Based on what has already been run and what came back, suggest ONE sensible next command. Reply with a one-sentence reason, then the command alone in a fenced code block. Do not suggest anything destructive.\n\nRecent commands:\n${recent}\n\nRecent output:\n---\n${result.text}\n---`)
}).then((reply)=>{
const command=termExtractCommand(reply)
if(!command){showStatusIsland("The AI did not propose a runnable command");return ""}
return termStageCommand(command).then(()=>{
showStatusIsland("Suggestion staged - review it, then press Enter to run")
return command
})
}).catch((err)=>{
showToast(err&&err.message?err.message:"The AI request failed","error")
return ""
})
}
function termOpenAiMenu(anchorElement){
const box=anchorElement.getBoundingClientRect()
const tab=termFindTab(termState.activeId)
const selection=termOutputSelectionText()
const items=[]
if(selection)items.push({label:"Explain the selection",icon:"brain",fn:()=>termAiExplainOutput(selection,"selected output")})
items.push({label:"Explain the last output",icon:"brain",disabled:!tab,fn:()=>termAiExplainOutput(termAiLastBlockText(tab),"output")})
items.push({label:"Summarise this session",icon:"list",disabled:!tab,fn:termAiSummariseSession})
items.push({sep:true})
items.push({label:"Suggest the next command",icon:"command-line",disabled:!tab,fn:termAiSuggestNext})
openContextMenu(items,box.left,box.bottom+4)
}
function termAiLastBlockText(tab){
if(!tab)return ""
const blocks=termVisibleJobBlocks(tab)
if(!blocks.length)return tab.buffer
const last=blocks[blocks.length-1]
return tab.buffer.slice(last.startIdx,last.endIdx===null||last.endIdx===undefined?tab.buffer.length:last.endIdx)
}
function termShowJobOutput(job){
bridgeCall("terminal.batch_output",[job.job_key,true]).then((text)=>{
const body=text&&text.trim()?text:termJobOutput(job)
const el=document.createElement("div")
el.className="term-fanout-modal glass-panel"
el.innerHTML='<div class="term-fanout-title">'+termEscapeHtml(job.label||job.command||"Job output")+'</div><pre class="term-run-preview term-job-output">'+termEscapeHtml(body||"No output captured.")+'</pre><div class="term-fanout-actions"><button type="button" id="termJobOutCopy">Copy</button><button type="button" class="term-fanout-run" id="termJobOutClose">Close</button></div>'
openModal(el)
el.querySelector("#termJobOutClose").addEventListener("click",closeModal)
el.querySelector("#termJobOutCopy").addEventListener("click",()=>{if(navigator.clipboard)navigator.clipboard.writeText(body||"").then(()=>showToast("Copied")).catch(()=>{})})
}).catch(()=>{})
}
function termCloseTab(id,confirmed){
const closing=termFindTab(id)
if(closing&&closing.activeJob&&!confirmed){
appConfirm("Close "+closing.label+" while a command is running?",{okLabel:"Close anyway",cancelLabel:"Keep open",danger:true,bodyHtml:'<pre class="term-run-preview">'+termEscapeHtml(closing.activeJob.command||"")+"</pre>"}).then((ok)=>{if(ok)termCloseTab(id,true)})
return
}
if(closing&&closing.activeJob)bridgeCall("terminal.job_mark",[closing.activeJob.jobId,"killed"]).catch(()=>{})
if(typeof ReportEvidence!=="undefined")ReportEvidence.onSessionClosed(id)
const idx=termState.tabs.findIndex((t)=>t.sessionId===id)
const closedTab=idx>=0?termState.tabs[idx]:null
// Remember first, then close: bridge calls run on parallel threads, and the backend reads the live cwd from the process.
const close=()=>bridgeCall("terminal.close",[id]).catch(()=>{})
if(closedTab&&!closedTab.elevated)termRememberClosed(closedTab).then(close,close)
else close()
if(idx>=0)termState.tabs.splice(idx,1)
if(closedTab&&!closedTab.dead)showStatusIsland((closedTab.label||"Terminal session")+" closed")
const pane=termPaneForSession(id)
if(pane){
const next=termNextHiddenTab()
pane.sessionId=next?next.sessionId:null
pane.renderedTabId=null
}
if(termState.activeId===id){
const focused=termFocusedPane()
termState.activeId=focused?focused.sessionId:null
const tab=termFindTab(termState.activeId)
const input=document.getElementById("terminalInput")
if(input){input.value=tab?tab.staged||"":"";if(tab)tab.staged=""}
}
termRenderTabs()
if(pane)termRenderPane(pane)
termUpdateStatusBar()
termScheduleSizeSync()
termSaveWorkspaceSoon()
if(!termState.tabs.length)termStopPolling()
}
function termSubmitCommand(val){
if(!termState.activeId)return
const tab=termFindTab(termState.activeId)
let payload=null
if(tab&&val.trim()){
if(tab.history[tab.history.length-1]!==val){
tab.history.push(val)
if(tab.history.length>200)tab.history.shift()
}
tab.historyIdx=null
// The shell is waiting for the rest of a command (an unclosed quote): this line continues that job, it is not a new one.
const cont=tab.continuation&&tab.activeJob&&tab.activeJob.jobId===tab.continuation.jobId?tab.continuation:null
if(cont){
const whole=cont.text+"\n"+val
tab.activeJob.command=whole
const record=(tab.jobHistory||[]).find((j)=>j.jobId===cont.jobId)
if(record)record.command=whole
termInvalidateRender(tab)
const sent=termJobPayload(tab,whole,cont.jobId)
bridgeCall("terminal.write",[termState.activeId,sent.slice(whole.length-val.length)+termSubmitNewline(tab.shellId)]).then(termWakePolling).catch((err)=>console.error("terminal write failed",err))
return
}
if(val.trim().toLowerCase()==="history"){
termShowHistoryWidget(tab)
return
}
const listingCmd=termDetectListingCommand(val,tab.shellId)
const jobId=termNewJobId()
tab.activeJob={jobId,command:val,startIdx:tab.buffer.length,startedAt:Date.now(),exitCode:null,endedAt:null,endIdx:null}
tab.pendingCapture={command:val,jobId,kind:listingCmd?listingCmd.kind:null,long:listingCmd?listingCmd.long:false,startIdx:tab.buffer.length,lastLen:tab.buffer.length,quietTicks:0}
termRecordJobStart(tab,tab.activeJob,"terminal")
termRecordJobOffset(tab,tab.activeJob)
payload=termJobPayload(tab,val,jobId)
}
bridgeCall("terminal.write",[termState.activeId,(payload===null?val:payload)+termSubmitNewline(tab?tab.shellId:null)]).then(termWakePolling).catch((err)=>console.error("terminal write failed",err))
}
function termSendLine(){
termSuggestHide()
const input=document.getElementById("terminalInput")
const val=input.value
input.value=""
termUpdateLiveEcho()
termSubmitCommand(val)
}
const TERM_SHELL_CONTROL_KEYS={c:"\x03",d:"\x04",z:"\x1a"}
function termSendControl(seq){
if(!termState.activeId)return
const tab=termFindTab(termState.activeId)
if(seq==="\x03"&&tab&&tab.activeJob)tab.activeJob.interrupted=true
bridgeCall("terminal.write",[termState.activeId,seq]).then(termWakePolling).catch((err)=>console.error("terminal control write failed",err))
}
function termOutputSelectionText(){
const sel=window.getSelection()
if(!sel||sel.isCollapsed)return ""
const out=document.getElementById("terminalPanes")||termOutputEl()
if(!out||!out.contains(sel.anchorNode))return ""
return String(sel)
}
function termClearStagedInput(){
termSuggestHide()
const input=document.getElementById("terminalInput")
input.value=""
const tab=termFindTab(termState.activeId)
if(tab)tab.historyIdx=null
termUpdateLiveEcho()
}
// Panel-level shortcuts (reopen closed, pane focus). Also bound on the panel itself so they work from a pane header button.
function termPanelShortcutKey(e){
if(e.isComposing||e.defaultPrevented)return false
const action=termShortcutActionFor(termSuggest.shortcuts,shortcutFromEvent(e))
if(action==="reopen_closed"){e.preventDefault();termSuggestHide();termReopenClosed();return true}
const dir={pane_left:"left",pane_right:"right",pane_up:"up",pane_down:"down"}[action]
if(dir){e.preventDefault();termSuggestHide();termFocusDirection(dir);return true}
return false
}
function termHandleKeydown(e){
const input=document.getElementById("terminalInput")
if(termSuggestHandleKey(e))return
if(termPanelShortcutKey(e))return
if(e.ctrlKey&&e.shiftKey&&!e.altKey&&e.key==="Enter"){e.preventDefault();termToggleMaximize();return}
if(e.ctrlKey&&!e.altKey&&e.key.toLowerCase()==="f"){e.preventDefault();termToggleSearch();return}
if(e.ctrlKey&&e.key==="Tab"){e.preventDefault();termCycleTab(e.shiftKey?-1:1);return}
if(e.ctrlKey&&!e.altKey&&!e.metaKey&&/^[1-9]$/.test(e.key)){e.preventDefault();termActivateTabIndex(parseInt(e.key,10)-1);return}
if(e.key==="Enter"){
if(e.shiftKey)return
e.preventDefault()
// Exactly "/caller" runs that action chain instead of reaching the shell; anything else (/usr/bin/id) is sent as typed.
const chainHit=typeof acTerminalExactCaller==="function"?acTerminalExactCaller(input.value):null
if(chainHit){termClearStagedInput();loyaRunChainByCaller(chainHit.caller,{source:"terminal"});return}
termSendLine()
return
}
if(e.key==="Tab"&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&termJumpPlaceholder(e.shiftKey?-1:1)){e.preventDefault();return}
if(e.key==="Tab"){e.preventDefault();termSendControl("\t");return}
const clip=termClipboardKeyAction(e,!!termOutputSelectionText())
if(clip==="copy"){
e.preventDefault()
const selected=termOutputSelectionText()
if(selected&&navigator.clipboard)navigator.clipboard.writeText(selected).then(()=>showToast("Copied")).catch(()=>{})
return
}
if(clip==="paste"){e.preventDefault();termPasteFromClipboard();return}
if(clip==="interrupt"){
e.preventDefault()
termSendControl(TERM_SHELL_CONTROL_KEYS.c)
termClearStagedInput()
return
}
if(e.ctrlKey&&!e.altKey&&!e.metaKey){
const key=e.key.toLowerCase()
if(key==="l"){e.preventDefault();termClearOutput();return}
if(key==="u"){e.preventDefault();termClearStagedInput();return}
if(key==="arrowup"||e.key==="ArrowUp"){e.preventDefault();termJumpJobBoundary(-1);return}
if(key==="arrowdown"||e.key==="ArrowDown"){e.preventDefault();termJumpJobBoundary(1);return}
if(TERM_SHELL_CONTROL_KEYS[key]){e.preventDefault();termSendControl(TERM_SHELL_CONTROL_KEYS[key]);return}
return
}
if(input.value.includes("\n"))return
if(e.key==="ArrowUp"){e.preventDefault();termRecallHistory(-1);return}
if(e.key==="ArrowDown"){e.preventDefault();termRecallHistory(1)}
}
function termPastePreviewHtml(text){
const lines=text.split(/\r?\n/)
const head=lines.slice(0,8).join("\n")
const extra=lines.length>8?`\n... and ${lines.length-8} more line${lines.length-8===1?"":"s"}`:""
return `<div class="term-paste-warning">Pasted text contains ${lines.length} lines. Each line runs as its own command once you press Enter.</div><pre class="term-paste-preview">${termEscapeHtml(head+extra)}</pre>`
}
function termInsertAtCursor(text){
const input=document.getElementById("terminalInput")
const start=input.selectionStart,end=input.selectionEnd
input.value=input.value.slice(0,start)+text+input.value.slice(end)
const caret=start+text.length
input.setSelectionRange(caret,caret)
input.focus()
termUpdateLiveEcho()
}
function termPasteFromClipboard(){
if(!navigator.clipboard||!navigator.clipboard.readText){showToast("Clipboard is not available here - use Ctrl+V","error");return}
navigator.clipboard.readText().then((text)=>{
if(!text)return
if(!termState.confirmMultilinePaste||!/[\r\n]/.test(text.trim())){termInsertAtCursor(text);return}
termConfirmMultilinePaste(text)
}).catch(()=>showToast("Could not read the clipboard - use Ctrl+V","error"))
}
function termHandlePaste(e){
const data=e.clipboardData||window.clipboardData
const text=data?data.getData("text"):""
if(!text)return
if(!termState.confirmMultilinePaste||!/[\r\n]/.test(text.trim()))return
e.preventDefault()
termConfirmMultilinePaste(text)
}
function termConfirmMultilinePaste(text){
const count=text.split(/\r?\n/).length
appConfirm(`Paste ${count} lines into the terminal?`,{okLabel:"Paste",cancelLabel:"Cancel",wide:true,danger:true,bodyHtml:termPastePreviewHtml(text)}).then((ok)=>{
if(ok)termInsertAtCursor(text)
else document.getElementById("terminalInput").focus()
})
}
function termRecallHistory(dir){
const input=document.getElementById("terminalInput")
const tab=termFindTab(termState.activeId)
if(!tab||!tab.history.length)return
if(dir<0){
tab.historyIdx=tab.historyIdx===null?tab.history.length-1:Math.max(0,tab.historyIdx-1)
input.value=tab.history[tab.historyIdx]
}else{
if(tab.historyIdx===null)return
if(tab.historyIdx>=tab.history.length-1){tab.historyIdx=null;input.value="";termUpdateLiveEcho();return}
tab.historyIdx+=1
input.value=tab.history[tab.historyIdx]
}
termUpdateLiveEcho()
setTimeout(()=>input.setSelectionRange(input.value.length,input.value.length),0)
}
function termClosePopover(){
const p=document.getElementById("terminalPopover")
if(p)p.remove()
document.removeEventListener("mousedown",termPopoverOutsideClick,true)
}
function termPopoverOutsideClick(e){
const pop=document.getElementById("terminalPopover")
if(pop&&!pop.contains(e.target)&&!e.target.closest(".terminal-head-btn"))termClosePopover()
}
function termOpenPopover(anchorEl,widthPx){
termClosePopover()
const rect=anchorEl.getBoundingClientRect()
const pop=document.createElement("div")
pop.id="terminalPopover"
pop.className="terminal-popover glass-panel"
pop.style.visibility="hidden"
const width=widthPx||280
pop.style.left=Math.round(Math.min(rect.left,window.innerWidth-width-16))+"px"
pop.style.top="0px"
document.body.appendChild(pop)
setTimeout(()=>document.addEventListener("mousedown",termPopoverOutsideClick,true),0)
requestAnimationFrame(()=>{
const popH=pop.offsetHeight
// Re-clamp with the real width: max-content can exceed widthPx (the split picker renders 320px) and spill off-window.
pop.style.left=Math.round(Math.max(8,Math.min(rect.left,window.innerWidth-pop.offsetWidth-16)))+"px"
const spaceBelow=window.innerHeight-rect.bottom-6
const spaceAbove=rect.top-6
let top=spaceBelow>=popH||spaceBelow>=spaceAbove?Math.round(rect.bottom+6):Math.round(rect.top-popH-6)
top=Math.max(8,Math.min(top,window.innerHeight-popH-8))
pop.style.top=top+"px"
pop.style.visibility="visible"
})
return pop
}
function termShowHistoryWidget(tab){
if(!tab.listings)tab.listings=[]
tab.listings.push({id:"hist"+Math.random().toString(36).slice(2,9),startIdx:tab.buffer.length,endIdx:tab.buffer.length,kind:"history",rows:tab.history.slice().reverse(),rawText:tab.history.slice().reverse().join("\n"),showRaw:false})
termInvalidateRender(tab)
termRenderSession(tab.sessionId)
}
function termClearOutput(){
const tab=termFindTab(termState.activeId)
if(!tab)return
tab.buffer=""
tab.visible=""
tab.pendingRaw=""
tab.listings=[]
tab.jobHistory=[]
tab.pendingCapture=null
tab.renderedLen=0
tab.ansiClasses=[]
tab.prior=null
termInvalidateRender(tab)
termState.pendingOutput=0
termState.followOutput=true
termRenderActiveOutput()
}
function termTranscriptHtml(title,body){
return "<h3>"+termEscapeHtml(title)+"</h3><pre>"+termEscapeHtml(body)+"</pre>"
}
function termRedactIfAsked(text,redact){
if(!redact)return Promise.resolve({text,found:[]})
return bridgeCall("terminal.redact",[text]).catch(()=>({text,found:[]}))
}
function termOpenNotePicker(title,body){
bridgeCall("notes.list").then((notes)=>{
const element=document.createElement("div")
element.className="term-fanout-modal glass-panel"
const options=(notes||[]).map((note)=>'<button type="button" class="term-note-option" data-id="'+termEscapeHtml(String(note.id))+'"><span class="term-note-name">'+termEscapeHtml(note.note_name)+'</span><span class="term-note-group">'+termEscapeHtml(note.group_name||"")+'</span></button>').join("")
element.innerHTML='<div class="term-fanout-title">Send to a note</div><div class="term-fanout-note">Appends to the end of the note, keeping everything already in it.</div><label class="term-fanout-all"><input type="checkbox" id="termNoteRedact" checked><span>Remove secrets before saving</span></label><div class="term-fanout-list" id="termNoteList">'+(options||'<div class="terminal-popover-empty">No notes yet.</div>')+'</div><div class="term-fanout-actions"><button type="button" id="termNoteNew">Create new note</button><button type="button" id="termNoteCancel">Cancel</button></div>'
openModal(element)
function finish(promise){
promise.then(()=>{closeModal();showToast("Saved to note")}).catch((error)=>showToast(error&&error.message?error.message:"Save failed","error"))
}
element.querySelector("#termNoteCancel").addEventListener("click",closeModal)
element.querySelector("#termNoteNew").addEventListener("click",()=>{
const redact=element.querySelector("#termNoteRedact").checked
finish(termRedactIfAsked(body,redact).then((result)=>bridgeCall("notes.save",[null,title,"Terminal Sessions",termTranscriptHtml(title,result.text),[],"terminal"])))
})
element.querySelector("#termNoteList").addEventListener("click",(event)=>{
const option=event.target.closest(".term-note-option")
if(!option)return
const redact=element.querySelector("#termNoteRedact").checked
finish(termRedactIfAsked(body,redact).then((result)=>bridgeCall("notes.append",[parseInt(option.dataset.id,10),termTranscriptHtml(title,result.text)])))
})
}).catch((error)=>showToast(error&&error.message?error.message:"Could not load notes","error"))
}
function termSessionTitle(tab){
const shell=termState.shells.find((entry)=>entry.id===tab.shellId)
return "Terminal - "+(tab.label||(shell?shell.label:tab.shellId))+" - "+new Date().toLocaleString()
}
function termSendSessionToNote(){
const tab=termFindTab(termState.activeId)
if(!tab||!tab.buffer.trim()){showToast("Nothing captured yet in this session","error");return}
termOpenNotePicker(termSessionTitle(tab),tab.buffer)
}
function termSendJobToNote(job){
const output=termJobOutput(job)
const send=(text)=>termOpenNotePicker((job.label&&job.source==="batch"?job.label+" - ":"")+(job.command||"Job output"),text||"No output captured.")
if(output){send(output);return}
bridgeCall("terminal.batch_output",[job.job_key]).then(send).catch(()=>send(""))
}
function termExportSessionHtml(){
const tab=termFindTab(termState.activeId)
if(!tab||!tab.buffer.trim()){showToast("Nothing captured yet in this session","error");return}
const rendered=termAnsiRenderChunk(tab.buffer,[]).html
bridgeCall("terminal.export_html",[termSessionTitle(tab),rendered]).then((path)=>{
if(path)showToast("Exported to "+path)
}).catch((error)=>showToast(error&&error.message?error.message:"Export failed","error"))
}
function termOpenSaveMenu(anchorEl){
const tab=termFindTab(termState.activeId)
const pop=termOpenPopover(anchorEl,260)
if(!tab||!tab.buffer.trim()){
pop.innerHTML='<div class="terminal-popover-title">Save Session</div><div class="terminal-popover-empty">Nothing captured yet in this session.</div>'
return
}
pop.innerHTML=`<div class="terminal-popover-title">Save Session</div><button type="button" class="terminal-save-item" id="termSaveNoteBtn"><i class="icon icon-edit"></i><span>Send to a Note</span></button><button type="button" class="terminal-save-item" id="termSaveFileBtn"><i class="icon icon-save"></i><span>Save as .txt File</span></button><button type="button" class="terminal-save-item" id="termExportHtmlBtn"><i class="icon icon-table"></i><span>Export as HTML</span></button>`
pop.querySelector("#termSaveNoteBtn").addEventListener("click",()=>{
termClosePopover()
termSendSessionToNote()
})
pop.querySelector("#termExportHtmlBtn").addEventListener("click",()=>{
termClosePopover()
termExportSessionHtml()
})
pop.querySelector("#termSaveFileBtn").addEventListener("click",()=>{
termClosePopover()
bridgeCall("terminal.save_output_to_file",[tab.buffer]).then((path)=>{
if(path)showToast("Saved to "+path)
}).catch((err)=>showToast(err&&err.message?err.message:"Save failed","error"))
})
}
// The terminal is toggled from the dock button next to AI (the title-bar button was removed); it shows when the panel is open.
function termSyncToggleButtons(){["dockTerminalBtn"].forEach((id)=>{const b=document.getElementById(id);if(b)b.classList.toggle("active",!!termState.open)})}
function termOpenPanel(){
termState.open=true
termState.maximized=false
termSuggestRefreshIndex(false)
document.getElementById("terminalPanel").classList.remove("hidden")
termApplyLayout()
termApplyPaneLayout()
if(!termState.tabs.length)termRestoreWorkspaceOrNew()
else{termFillEmptyPanes();termStartPolling()}
document.getElementById("terminalInput").focus()
termScheduleSizeSync()
termSyncToggleButtons()
}
function termClosePanel(){
termSuggestHide()
termState.open=false
document.getElementById("terminalPanel").classList.add("hidden")
termApplyLayout()
termStopPolling()
termSyncToggleButtons()
}
function termTogglePanel(){
if(termState.open)termClosePanel()
else termOpenPanel()
}
// The dock's Terminal button always opens the panel docked on the right; dragging it elsewhere only lasts until it is closed.
function termToggleFromDock(){
if(termState.open){termClosePanel();return}
if(termState.mode!=="right")termSetDockMode("right")
termOpenPanel()
}
const TERM_RESIZE_DEBOUNCE_MS=140
const TERM_CELL_SAMPLE="0".repeat(50)
const TERM_MIN_COLS=20
const TERM_MAX_COLS=500
const TERM_MIN_ROWS=5
const TERM_MAX_ROWS=300
function termClampSize(value,low,high){
if(!isFinite(value))return low
return Math.max(low,Math.min(high,Math.floor(value)))
}
function termGridForBox(box,cell){
if(!box||!cell||!cell.width||!cell.height)return null
return {cols:termClampSize(box.width/cell.width,TERM_MIN_COLS,TERM_MAX_COLS),rows:termClampSize(box.height/cell.height,TERM_MIN_ROWS,TERM_MAX_ROWS)}
}
function termMeasureCell(out){
out=out||termOutputEl()
if(!out)return null
let probe=out.querySelector(":scope > .terminal-cell-probe")
if(!probe){
probe=document.createElement("span")
probe.className="terminal-cell-probe"
probe.textContent=TERM_CELL_SAMPLE
out.appendChild(probe)
}
const rect=probe.getBoundingClientRect()
if(!rect.width||!rect.height)return termState.cellSize
termState.cellSize={width:rect.width/TERM_CELL_SAMPLE.length,height:rect.height}
return termState.cellSize
}
function termCurrentGrid(pane){
const out=pane?pane.out:termOutputEl()
if(!out||!out.clientWidth)return null
const style=window.getComputedStyle(out)
const box={width:out.clientWidth-parseFloat(style.paddingLeft||0)-parseFloat(style.paddingRight||0),height:out.clientHeight-parseFloat(style.paddingTop||0)-parseFloat(style.paddingBottom||0)}
return termGridForBox(box,termMeasureCell(out))
}
// Every visible pane sizes its own pty (TIOCSWINSZ / ResizePseudoConsole) to its own cols x rows. Sessions that are
// only tabs keep the size they last had, and get resized the moment they are shown in a pane.
function termSyncSize(){
if(!termState.open)return
termState.panes.forEach((pane)=>{
const tab=termFindTab(pane.sessionId)
if(!tab||tab.dead)return
const grid=termCurrentGrid(pane)
if(!grid||(grid.cols===tab.cols&&grid.rows===tab.rows))return
tab.cols=grid.cols
tab.rows=grid.rows
if(pane===termFocusedPane()){termState.cols=grid.cols;termState.rows=grid.rows}
bridgeCall("terminal.resize",[tab.sessionId,grid.cols,grid.rows]).catch(()=>{})
})
}
function termScheduleSizeSync(){
if(termState.sizeTimer)clearTimeout(termState.sizeTimer)
termState.sizeTimer=setTimeout(()=>{
termState.sizeTimer=null
termSyncSize()
},TERM_RESIZE_DEBOUNCE_MS)
}
let termResizeObserver=null
function termWatchOutputSize(out){
if(typeof ResizeObserver!=="function"){
if(!termResizeObserver){termResizeObserver=true;window.addEventListener("resize",termScheduleSizeSync)}
return
}
if(!termResizeObserver)termResizeObserver=new ResizeObserver(termScheduleSizeSync)
if(out)termResizeObserver.observe(out)
}
function termWireResize(){
initSidePanelResize({handle:document.getElementById("terminalResizeHandle"),panel:document.getElementById("terminalPanel"),config:()=>{
const vp={width:window.innerWidth,height:window.innerHeight}
if(termState.mode==="bottom")return {axis:"y",anchorSide:"bottom",min:PANEL_DOCK_MIN_BOTTOM,max:panelDockClampSize("bottom",1e6,vp)}
return {axis:"x",anchorSide:termState.mode==="left"?"left":"right",min:PANEL_DOCK_MIN_SIDE,max:panelDockClampSize("right",1e6,vp)}
},onCommit:(size,axis)=>{
if(axis==="y"){termState.height=size;termSaveLayout({height:size});return}
termState.width=size
termSaveLayout({width:size})
}})
}
function termSaveLayout(values){
bridgeCall("terminal.set_panel_layout",[values]).catch(()=>{})
}
function termApplyLayout(){
const area=document.getElementById("workArea")
const panel=document.getElementById("terminalPanel")
const vertical=termState.mode==="bottom"
// Saved sizes from older builds (or from a bigger window) are lifted/limited to what a docked panel may have.
const vp=typeof window!=="undefined"?{width:window.innerWidth,height:window.innerHeight}:null
termState.width=panelDockClampSize("right",termState.width,vp)
termState.height=panelDockClampSize("bottom",termState.height,vp)
area.classList.toggle("dock-left",termState.mode==="left")
area.classList.toggle("dock-bottom",vertical)
area.classList.toggle("maximized",termState.maximized&&termState.open)
panel.style.width=termState.maximized||vertical?"":termState.width+"px"
panel.style.height=termState.maximized||!vertical?"":termState.height+"px"
termScheduleSizeSync()
const icon=document.getElementById("terminalMaximizeIcon")
icon.className="icon "+(termState.maximized?"icon-restore":"icon-maximize")
document.getElementById("terminalMaximizeBtn").classList.toggle("active",termState.maximized)
document.getElementById("terminalMaximizeBtn").title=termState.maximized?"Restore panel (Ctrl+Shift+Enter)":"Maximize panel (Ctrl+Shift+Enter)"
if(termState.followOutput)termScrollToBottom()
termScheduleHeadLayout()
}
// Every dock change goes through panelDockMove so the Terminal and AI panels never both sit at the bottom.
function termSetDockMode(mode){
if(typeof panelDockMove==="function"&&typeof panelDockPanels!=="undefined"&&panelDockPanels.terminal)panelDockMove("terminal",mode)
else termDockApplyMode(mode)
}
// Applies a dock side chosen by drag-and-drop, the position menu, or pushed here by the AI panel taking the bottom.
// A drop un-maximizes (the user put the panel somewhere); maximize stays a per-session choice and is never restored.
function termDockApplyMode(mode,opts){
mode=panelDockNormalizeMode(mode,termState.mode)
const unmax=!!(opts&&opts.fromDrag&&termState.maximized)
if(mode===termState.mode&&!unmax)return
termState.mode=mode
if(unmax)termState.maximized=false
termApplyLayout()
termSaveLayout(unmax?{mode:mode,maximized:false}:{mode:mode})
if(opts&&opts.fromDrag&&termState.open&&typeof showStatusIsland==="function")showStatusIsland("Terminal docked "+mode)
}
// Header toolbar overflow: as the panel narrows, the least important actions move into the "More" (...) menu instead
// of wrapping into a broken second row. Listed in DOM order; priority 1 is the last to go; pinned never move.
const TERM_HEAD_ITEMS=[
{id:"terminalElevateBtn",priority:6,label:"Run elevated",icon:"elevate"},
{id:"terminalClearBtn",priority:7,label:"Clear output",icon:"eraser"},
{id:"terminalIocBtn",priority:5,label:"Extract indicators",icon:"ioc"},
{id:"terminalSearchBtn",priority:1,label:"Search output",icon:"search"},
{id:"terminalBlocksBtn",priority:9,label:"Group output into job blocks",icon:"table",toggle:true},
{id:"terminalJobsBtn",priority:2,label:"Jobs",icon:"list"},
{id:"terminalRecordBtn",priority:8,label:"Record this session for the report",icon:"report",toggle:true},
{id:"terminalSaveBtn",priority:4,label:"Save session output",icon:"save"},
{id:"terminalAiBtn",priority:3,label:"Ask the AI about this session",icon:"brain"},
{id:"terminalMoreBtn",pinned:true,more:true},
{id:"terminalLayoutBtn",pinned:true},
{id:"terminalMaximizeBtn",pinned:true},
{id:"terminalCloseBtn",pinned:true}
]
const TERM_HEAD_GAP=4
const TERM_HEAD_GROUP_GAP=8
// Room always left free between the two button groups so the header can still be grabbed to drag the panel.
const TERM_HEAD_DRAG_SLACK=18
// Pure: which header ids overflow for a given usable row width and per-id widths (tests/js/panel_dock.js).
function termHeadOverflowPlan(available,widths){
const items=TERM_HEAD_ITEMS.filter((it)=>!it.more).map((it)=>({id:it.id,width:widths[it.id]||0,priority:it.priority||0,pinned:!!it.pinned}))
return panelDockOverflow(items,available-TERM_HEAD_GROUP_GAP-TERM_HEAD_DRAG_SLACK,{gap:TERM_HEAD_GAP,moreWidth:widths.terminalMoreBtn||26})
}
let termHeadFrame=0
function termScheduleHeadLayout(){
if(termHeadFrame||typeof requestAnimationFrame!=="function")return
termHeadFrame=requestAnimationFrame(()=>{termHeadFrame=0;termLayoutHead()})
}
function termLayoutHead(){
const row=document.querySelector("#terminalPanel .terminal-panel-actions")
if(!row||!row.clientWidth)return
const more=document.getElementById("terminalMoreBtn")
const widths={}
TERM_HEAD_ITEMS.forEach((it)=>{const el=document.getElementById(it.id);if(el)el.classList.remove("term-head-overflow")})
if(more)more.classList.remove("hidden")
TERM_HEAD_ITEMS.forEach((it)=>{const el=document.getElementById(it.id);widths[it.id]=el?el.offsetWidth:0})
const style=window.getComputedStyle(row)
const available=row.clientWidth-parseFloat(style.paddingLeft||0)-parseFloat(style.paddingRight||0)
const plan=termHeadOverflowPlan(available,widths)
plan.overflow.forEach((id)=>document.getElementById(id).classList.add("term-head-overflow"))
termState.headOverflow=plan.overflow
if(more)more.classList.toggle("hidden",!plan.overflow.length)
}
function termOpenHeadMore(anchorEl){
const box=anchorEl.getBoundingClientRect()
const anchored={terminalSaveBtn:termOpenSaveMenu,terminalAiBtn:termOpenAiMenu,terminalLayoutBtn:termOpenLayoutMenu}
const items=(termState.headOverflow||[]).map((id)=>{
const spec=TERM_HEAD_ITEMS.find((it)=>it.id===id)
const el=document.getElementById(id)
let label=spec.label
if(spec.toggle&&el&&el.classList.contains("active"))label+="  \u2713"
if(id==="terminalJobsBtn"){const n=termRunningJobCount();if(n)label+=" ("+n+" running)"}
return {label:termEscapeHtml(label),icon:spec.icon,fn:()=>{if(anchored[id])anchored[id](anchorEl);else if(el)el.click()}}
})
if(!items.length)return
openContextMenu(items,Math.max(8,box.right-210),box.bottom+4)
}
function termToggleMaximize(){
termState.maximized=!termState.maximized
termApplyLayout()
termSaveLayout({maximized:termState.maximized})
document.getElementById("terminalInput").focus()
}
function termOpenLayoutMenu(anchorEl){
const box=anchorEl.getBoundingClientRect()
const modes=[["right","Dock right","align-right"],["left","Dock left","align-left"],["bottom","Dock bottom","align-center"]]
const items=modes.map(([mode,label,icon])=>({label:termState.mode===mode?label+"  \u2713":label,icon:icon,fn:()=>termSetDockMode(mode)}))
items.push({sep:true})
items.push({label:termState.maximized?"Restore panel":"Maximize panel",icon:termState.maximized?"restore":"maximize",fn:termToggleMaximize})
items.push({sep:true})
items.push({label:"Tip: drag the panel header to an edge",icon:"grip",disabled:true,fn:()=>{}})
openContextMenu(items,box.left,box.bottom+4)
}
function termApplyRunBehaviour(s){
if(!s)return
termState.confirmMultilinePaste=s.confirm_multiline_paste!==false
termState.snippetClickAction=s.snippet_click_action||"copy"
termState.commandClickAction=s.command_click_action||"copy"
termState.snippetRunConfirm=s.snippet_run_confirm||"risky"
termState.commandRunConfirm=s.command_run_confirm||"risky"
termState.runDestination=s.run_destination||"active"
termApplySuggestSettings(s)
}
function termApplyEnabled(enabled){
termState.enabled=enabled
const dockBtn=document.getElementById("dockTerminalBtn")
if(dockBtn)dockBtn.classList.toggle("hidden",!enabled)
if(!enabled&&termState.open)termClosePanel()
}
function termRefreshEnabled(){
bridgeCall("terminal.get_settings").then((s)=>termApplyEnabled(s.enabled)).catch(()=>{})
}
function termDoElevate(){
const sel=document.getElementById("terminalShellSelect")
bridgeCall("terminal.launch_elevated",[sel.value]).then((res)=>{
if(res&&res.kind==="session")termAddSessionTab(res.session_id,sel.value,"Elevated")
else if(res&&res.message)showToast(res.message)
}).catch((err)=>showToast(err&&err.message?err.message:"Elevation failed","error"))
}
// ---- Split panes (S16b). The panel shows 1-4 panes; each pane shows one session, the tabs stay the full session list.
// The pure layout math below (rects, splitter clamping, neighbours, workspace snapshot, closed-list trimming) is
// covered by tests/js/run.js; everything after termBuildPanes touches the DOM.
const TERM_LAYOUTS={single:{label:"Single",panes:1},cols2:{label:"Side by side",panes:2},rows2:{label:"Stacked",panes:2},top1bottom2:{label:"One on top, two below",panes:3},left2right1:{label:"Two left, one right",panes:3},grid4:{label:"Grid of four",panes:4}}
const TERM_LAYOUT_ORDER=["single","cols2","rows2","top1bottom2","left2right1","grid4"]
const TERM_PANE_MIN_W=160
const TERM_PANE_MIN_H=80
const TERM_PANE_GAP=6
const TERM_CLOSED_MAX=10
function termNormalizeLayout(layout){
return Object.prototype.hasOwnProperty.call(TERM_LAYOUTS,layout)?layout:"single"
}
function termLayoutPaneCount(layout){
return TERM_LAYOUTS[termNormalizeLayout(layout)].panes
}
// A splitter ratio is a fraction of the whole pane area. With a known size it keeps minPx on both sides; when the area
// is too small for two minimum panes it centres; with no size yet it only keeps the ratio inside 10%..90%.
function termClampRatio(value,totalPx,minPx){
let v=value===null||value===undefined||value===""?NaN:Number(value)
if(!isFinite(v))v=0.5
if(!(totalPx>0))return Math.max(0.1,Math.min(0.9,v))
if(totalPx<minPx*2)return 0.5
const lo=minPx/totalPx
return Math.max(lo,Math.min(1-lo,v))
}
// Pane rectangles as fractions of the pane area, plus the splitters between them. key "v" is a vertical bar dragged
// left-right (ratios.v), key "h" a horizontal bar dragged up-down (ratios.h).
function termPaneRects(layout,ratios){
const v=termClampRatio(ratios&&ratios.v,0,0),h=termClampRatio(ratios&&ratios.h,0,0)
switch(termNormalizeLayout(layout)){
case "cols2":return {panes:[{x:0,y:0,w:v,h:1},{x:v,y:0,w:1-v,h:1}],splitters:[{key:"v",at:v,from:0,to:1}]}
case "rows2":return {panes:[{x:0,y:0,w:1,h:h},{x:0,y:h,w:1,h:1-h}],splitters:[{key:"h",at:h,from:0,to:1}]}
case "top1bottom2":return {panes:[{x:0,y:0,w:1,h:h},{x:0,y:h,w:v,h:1-h},{x:v,y:h,w:1-v,h:1-h}],splitters:[{key:"h",at:h,from:0,to:1},{key:"v",at:v,from:h,to:1}]}
case "left2right1":return {panes:[{x:0,y:0,w:v,h:h},{x:0,y:h,w:v,h:1-h},{x:v,y:0,w:1-v,h:1}],splitters:[{key:"v",at:v,from:0,to:1},{key:"h",at:h,from:0,to:v}]}
case "grid4":return {panes:[{x:0,y:0,w:v,h:h},{x:v,y:0,w:1-v,h:h},{x:0,y:h,w:v,h:1-h},{x:v,y:h,w:1-v,h:1-h}],splitters:[{key:"v",at:v,from:0,to:1},{key:"h",at:h,from:0,to:1}]}
default:return {panes:[{x:0,y:0,w:1,h:1}],splitters:[]}
}
}
function termPct(f){
return +(f*100).toFixed(4)+"%"
}
// CSS for one pane: fractions become percentages, and each inner edge gives up half the gap to the splitter.
function termPaneStyle(rect,gap){
const half=(gap===undefined?TERM_PANE_GAP:gap)/2
const l=rect.x>1e-9?half:0,r=rect.x+rect.w<1-1e-9?half:0,t=rect.y>1e-9?half:0,b=rect.y+rect.h<1-1e-9?half:0
return {left:"calc("+termPct(rect.x)+" + "+l+"px)",top:"calc("+termPct(rect.y)+" + "+t+"px)",width:"calc("+termPct(rect.w)+" - "+(l+r)+"px)",height:"calc("+termPct(rect.h)+" - "+(t+b)+"px)"}
}
function termSplitterStyle(sp,gap){
const g=gap===undefined?TERM_PANE_GAP:gap
if(sp.key==="v")return {left:"calc("+termPct(sp.at)+" - "+(g/2)+"px)",width:g+"px",top:termPct(sp.from),height:termPct(sp.to-sp.from)}
return {top:"calc("+termPct(sp.at)+" - "+(g/2)+"px)",height:g+"px",left:termPct(sp.from),width:termPct(sp.to-sp.from)}
}
// The pane to move focus to from `from` in direction dir: it must lie wholly on that side and overlap on the other
// axis; the nearest wins, and on a tie the one sharing the longest edge.
function termPaneNeighbor(rects,from,dir){
const a=rects[from]
if(!a)return -1
let best=-1,bestScore=Infinity
rects.forEach((b,i)=>{
if(i===from)return
let gap,overlap
if(dir==="right"||dir==="left"){gap=dir==="right"?b.x-(a.x+a.w):a.x-(b.x+b.w);overlap=Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)}
else{gap=dir==="down"?b.y-(a.y+a.h):a.y-(b.y+b.h);overlap=Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)}
if(gap<-1e-6||overlap<=1e-6)return
const score=gap*10-overlap
if(score<bestScore){bestScore=score;best=i}
})
return best
}
// What is persisted so the split comes back after a restart: the layout, splitter ratios, focused pane and, per pane,
// how to start a fresh shell like the one that was there. Elevated sessions are never restored.
function termWorkspaceSnapshot(state){
return {layout:termNormalizeLayout(state.layout),ratios:{v:termClampRatio(state.ratios&&state.ratios.v,0,0),h:termClampRatio(state.ratios&&state.ratios.h,0,0)},focus:state.focusPane||0,panes:(state.panes||[]).map((pane)=>{
const tab=(state.tabs||[]).find((t)=>t.sessionId===pane.sessionId)
if(!tab||tab.elevated)return null
return {name:tab.label||"",shell_id:tab.shellId||"",profile_id:tab.profileId||"",cwd:tab.cwd||""}
})}
}
// Newest first, at most max, and a session closed twice is only listed once (by its local id).
function termPushClosed(list,entry,max){
const rest=(list||[]).filter((x)=>x&&x.id!==entry.id)
return [entry].concat(rest).slice(0,max||TERM_CLOSED_MAX)
}
function termLayoutIconSvg(layout){
const geo=termPaneRects(layout,{v:0.5,h:0.5})
const W=28,H=18,pad=0.9
const rects=geo.panes.map((r)=>{
const x=1+r.x*W+(r.x>0?pad:0),y=1+r.y*H+(r.y>0?pad:0)
const w=r.w*W-(r.x>0?pad:0)-(r.x+r.w<1?pad:0),h=r.h*H-(r.y>0?pad:0)-(r.y+r.h<1?pad:0)
return '<rect x="'+x.toFixed(2)+'" y="'+y.toFixed(2)+'" width="'+w.toFixed(2)+'" height="'+h.toFixed(2)+'" rx="1.6"/>'
}).join("")
return '<svg class="term-layout-icon" viewBox="0 0 30 20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.3">'+rects+"</svg>"
}
function termBuildPanes(){
const wrap=document.getElementById("terminalPanes")
if(!wrap)return
const count=termLayoutPaneCount(termState.layout)
while(termState.panes.length<count)termState.panes.push(termCreatePane(wrap))
while(termState.panes.length>count){
const pane=termState.panes.pop()
if(termResizeObserver&&termResizeObserver.unobserve)termResizeObserver.unobserve(pane.out)
pane.el.remove()
}
if(termState.focusPane>=count)termState.focusPane=count-1
termApplyPaneLayout()
termMarkFocusedPane()
termUpdateSplitButton()
}
function termCreatePane(wrap){
const el=document.createElement("div")
el.className="terminal-pane empty"
el.innerHTML='<div class="terminal-pane-head"><span class="terminal-pane-dot"></span><button type="button" class="terminal-pane-title" title="Switch the session shown in this pane (double-click to rename)"><span class="terminal-pane-name"></span><i class="icon icon-arrow-down"></i></button><span class="terminal-pane-cwd"></span></div><div class="terminal-output" tabindex="-1"></div><div class="terminal-pane-empty"><span>No session in this pane</span><button type="button" class="terminal-pane-empty-btn" data-act="new">New session</button><button type="button" class="terminal-pane-empty-btn" data-act="pick">Show a session</button></div><button type="button" class="terminal-jump-bottom hidden"><i class="icon icon-arrow-down"></i><span class="terminal-jump-label">Jump to bottom</span></button>'
const pane={el,head:el.querySelector(".terminal-pane-head"),out:el.querySelector(".terminal-output"),jump:el.querySelector(".terminal-jump-bottom"),sessionId:null,renderedTabId:null,followOutput:true,pendingOutput:0}
const index=()=>termState.panes.indexOf(pane)
el.addEventListener("mousedown",(e)=>{if(index()!==termState.focusPane&&index()>=0)termFocusPane(index(),{noInput:!!e.target.closest(".terminal-output")})})
pane.out.addEventListener("click",termHandleOutputClick)
pane.out.addEventListener("scroll",()=>{
if(index()===termState.focusPane)termSuggestPosition()
const atBottom=termIsAtBottom(pane.out)
if(atBottom===pane.followOutput)return
pane.followOutput=atBottom
if(atBottom)pane.pendingOutput=0
termUpdatePaneJump(pane)
})
pane.jump.addEventListener("click",()=>{termScrollToBottom(pane);document.getElementById("terminalInput").focus()})
const title=el.querySelector(".terminal-pane-title")
title.addEventListener("click",(e)=>{e.stopPropagation();termOpenPaneSwitcher(pane,title)})
title.addEventListener("dblclick",(e)=>{e.preventDefault();closeContextMenu();termStartPaneRename(pane)})
el.querySelector(".terminal-pane-empty").addEventListener("click",(e)=>{
const btn=e.target.closest("[data-act]")
if(!btn)return
termFocusPane(index())
if(btn.dataset.act==="new")termNewTab().catch(()=>{})
else termOpenPaneSwitcher(pane,btn)
})
el.addEventListener("dragover",(e)=>{if(termState.dragTabId){e.preventDefault();el.classList.add("drop-target")}})
el.addEventListener("dragleave",()=>el.classList.remove("drop-target"))
el.addEventListener("drop",(e)=>{
el.classList.remove("drop-target")
if(!termState.dragTabId)return
e.preventDefault()
termAssignPane(index(),termState.dragTabId)
termState.dragTabId=null
termFocusPane(index())
})
wrap.appendChild(el)
termWatchOutputSize(pane.out)
return pane
}
// The focused pane's output keeps the historic ids (#terminalOutput, #terminalJumpBottom) so selectors in tests,
// the audit harness and the AI tooling keep pointing at "the terminal" the user is looking at.
function termMarkFocusedPane(){
const focused=termFocusedPane()
termState.panes.forEach((pane)=>{
const on=pane===focused
pane.el.classList.toggle("focused",on)
if(on){pane.out.id="terminalOutput";pane.jump.id="terminalJumpBottom";pane.jump.querySelector(".terminal-jump-label").id="terminalJumpBottomLabel"}
else{if(pane.out.id)pane.out.removeAttribute("id");if(pane.jump.id)pane.jump.removeAttribute("id");pane.jump.querySelector(".terminal-jump-label").removeAttribute("id")}
})
}
function termApplyPaneLayout(){
const wrap=document.getElementById("terminalPanes")
if(!wrap)return
const layout=termNormalizeLayout(termState.layout)
wrap.dataset.layout=layout
const box=wrap.getBoundingClientRect()
if(box.width&&box.height){
termState.ratios.v=termClampRatio(termState.ratios.v,box.width,TERM_PANE_MIN_W)
termState.ratios.h=termClampRatio(termState.ratios.h,box.height,TERM_PANE_MIN_H)
}
const geo=termPaneRects(layout,termState.ratios)
termState.panes.forEach((pane,i)=>{if(geo.panes[i])Object.assign(pane.el.style,termPaneStyle(geo.panes[i]))})
let bars=Array.prototype.slice.call(wrap.querySelectorAll(":scope > .terminal-splitter"))
if(bars.length!==geo.splitters.length||bars.some((bar,i)=>bar.dataset.key!==geo.splitters[i].key)){
bars.forEach((bar)=>bar.remove())
bars=geo.splitters.map((sp)=>{
const bar=document.createElement("div")
bar.className="terminal-splitter terminal-splitter-"+sp.key
bar.dataset.key=sp.key
bar.title="Drag to resize, double-click to even out"
bar.addEventListener("mousedown",(e)=>termStartSplitDrag(e,sp.key))
bar.addEventListener("dblclick",()=>{termState.ratios[sp.key]=0.5;termApplyPaneLayout();termScheduleSizeSync();termSaveWorkspaceSoon()})
wrap.appendChild(bar)
return bar
})
}
geo.splitters.forEach((sp,i)=>{
const style=termSplitterStyle(sp)
bars[i].style.left=style.left||"";bars[i].style.top=style.top||"";bars[i].style.width=style.width||"";bars[i].style.height=style.height||""
})
}
function termStartSplitDrag(e,key){
if(e.button!==0)return
e.preventDefault()
const wrap=document.getElementById("terminalPanes")
const rect=wrap.getBoundingClientRect()
document.body.classList.add("term-split-dragging",key==="v"?"term-split-x":"term-split-y")
termSuggestHide()
const move=(ev)=>{
const raw=key==="v"?(ev.clientX-rect.left)/rect.width:(ev.clientY-rect.top)/rect.height
termState.ratios[key]=termClampRatio(raw,key==="v"?rect.width:rect.height,key==="v"?TERM_PANE_MIN_W:TERM_PANE_MIN_H)
termApplyPaneLayout()
}
const up=()=>{
document.removeEventListener("mousemove",move)
document.removeEventListener("mouseup",up)
document.body.classList.remove("term-split-dragging","term-split-x","term-split-y")
termScheduleSizeSync()
termSaveWorkspaceSoon()
document.getElementById("terminalInput").focus()
}
document.addEventListener("mousemove",move)
document.addEventListener("mouseup",up)
}
function termStashStagedInput(fromId,toId){
if(fromId===toId)return
const input=document.getElementById("terminalInput")
if(!input)return
const from=termFindTab(fromId),to=termFindTab(toId)
if(from){from.staged=input.value;from.historyIdx=null}
input.value=to?to.staged||"":""
if(to)to.staged=""
}
function termFocusPane(i,opts){
const next=termState.panes[i]
if(!next)return
const prev=termFocusedPane()
termSuggestHide()
if(prev!==next){
termStashStagedInput(prev?prev.sessionId:null,next.sessionId)
termState.focusPane=i
termMarkFocusedPane()
if(prev&&termState.searchQuery){const pt=termFindTab(prev.sessionId);if(pt)termInvalidateRender(pt);termRenderPane(prev)}
termSaveWorkspaceSoon()
}
termState.activeId=next.sessionId
termUpdateStatusBar()
termRenderTabs()
termRenderPane(next)
if(termState.searchQuery)termRunSearch()
if(!(opts&&opts.noInput))document.getElementById("terminalInput").focus()
}
function termFocusDirection(dir){
if(termState.panes.length<2){showStatusIsland("Only one pane - pick a split layout first");return}
const target=termPaneNeighbor(termPaneRects(termState.layout,termState.ratios).panes,termState.focusPane,dir)
if(target>=0)termFocusPane(target)
}
// Shows sessionId in pane i. A session is on screen at most once: if another pane has it, the two panes swap.
function termAssignPane(i,sessionId){
const pane=termState.panes[i]
if(!pane||pane.sessionId===sessionId)return
const focused=termFocusedPane()
const before=focused?focused.sessionId:null
const other=termPaneForSession(sessionId)
if(other){other.sessionId=pane.sessionId;other.renderedTabId=null}
pane.sessionId=sessionId
pane.renderedTabId=null
if(focused&&focused.sessionId!==before){termStashStagedInput(before,focused.sessionId);termState.activeId=focused.sessionId;termUpdateStatusBar()}
termRenderPane(pane)
if(other)termRenderPane(other)
termRenderTabs()
termScheduleSizeSync()
termSaveWorkspaceSoon()
}
function termNextHiddenTab(){
return termState.tabs.find((t)=>termPaneIndexOf(t.sessionId)<0)||null
}
function termFocusedShellChoice(){
const tab=termFindTab(termState.activeId)||termState.tabs[0]
if(!tab||tab.elevated)return undefined
return tab.profileId&&(termState.profiles||[]).some((p)=>p.id===tab.profileId)?"profile:"+tab.profileId:tab.shellId
}
// Empty panes take sessions that are only tabs first, then get a fresh shell like the focused one.
function termFillEmptyPanes(){
let chain=Promise.resolve()
termState.panes.forEach((pane,i)=>{
if(pane.sessionId)return
const hidden=termNextHiddenTab()
if(hidden){termAssignPane(i,hidden.sessionId);return}
if(!termState.open)return
chain=chain.then(()=>termState.panes[i]&&!termState.panes[i].sessionId?termNewTab(termFocusedShellChoice(),{paneIndex:i}).catch(()=>{}):null)
})
return chain
}
function termSetLayout(layout){
layout=termNormalizeLayout(layout)
if(layout===termState.layout){document.getElementById("terminalInput").focus();return}
const count=termLayoutPaneCount(layout)
if(termState.focusPane>=count){
const focused=termFocusedPane(),keep=termState.panes[count-1]
const tmp=keep.sessionId
keep.sessionId=focused.sessionId;focused.sessionId=tmp
keep.renderedTabId=null;focused.renderedTabId=null
termState.focusPane=count-1
}
termState.layout=layout
termBuildPanes()
termRenderAllPanes()
termFillEmptyPanes()
termState.activeId=termFocusedPane().sessionId
termUpdateStatusBar()
termRenderTabs()
termScheduleSizeSync()
termSaveWorkspaceSoon()
showStatusIsland("Terminal layout: "+TERM_LAYOUTS[layout].label)
document.getElementById("terminalInput").focus()
}
function termUpdateSplitButton(){
const btn=document.getElementById("terminalSplitBtn")
if(!btn)return
btn.innerHTML=termLayoutIconSvg(termState.layout)
btn.title="Split layout: "+TERM_LAYOUTS[termNormalizeLayout(termState.layout)].label
btn.classList.toggle("active",termState.layout!=="single")
}
function termOpenSplitPicker(anchorEl){
const pop=termOpenPopover(anchorEl,276)
pop.classList.add("term-split-picker")
pop.innerHTML='<div class="terminal-popover-title">Split layout</div><div class="term-split-grid">'+TERM_LAYOUT_ORDER.map((id)=>'<button type="button" class="term-split-option'+(id===termState.layout?" active":"")+'" data-layout="'+id+'" title="'+termEscapeHtml(TERM_LAYOUTS[id].label)+'">'+termLayoutIconSvg(id)+'<span>'+termEscapeHtml(TERM_LAYOUTS[id].label)+"</span></button>").join("")+'</div><button type="button" class="terminal-save-item" data-act="even"><i class="icon icon-refresh"></i><span>Even out pane sizes</span></button><div class="term-split-hint">Alt+Arrow moves between panes. Drag a tab onto a pane to show it there.</div>'
pop.addEventListener("click",(e)=>{
const option=e.target.closest("[data-layout]")
if(option){termClosePopover();termSetLayout(option.dataset.layout);return}
if(e.target.closest('[data-act="even"]')){termClosePopover();termState.ratios={v:0.5,h:0.5};termApplyPaneLayout();termScheduleSizeSync();termSaveWorkspaceSoon()}
})
}
function termRenderPaneHeads(){
termState.panes.forEach((pane)=>{
const tab=termFindTab(pane.sessionId)
const name=pane.head.querySelector(".terminal-pane-name")
if(name&&!pane.head.querySelector(".terminal-pane-rename"))name.textContent=tab?tab.label:"Empty pane"
const cwd=pane.head.querySelector(".terminal-pane-cwd")
cwd.textContent=tab?termCwdDisplay(tab.cwd):""
cwd.title=tab&&tab.cwd?tab.cwd:""
pane.head.classList.toggle("busy",!!(tab&&tab.activeJob))
pane.head.classList.toggle("dead",!!(tab&&tab.dead))
pane.head.classList.toggle("elevated",!!(tab&&tab.elevated))
})
}
function termSetTabLabel(tab,name){
const label=String(name||"").trim().slice(0,60)
if(!tab||!label)return
tab.label=label
termRenderTabs()
termUpdateStatusBar()
bridgeCall("terminal.rename",[tab.sessionId,label]).catch(()=>{})
termSaveWorkspaceSoon()
}
function termStartPaneRename(pane){
const tab=termFindTab(pane.sessionId)
const name=pane.head.querySelector(".terminal-pane-name")
if(!tab||!name)return
const input=document.createElement("input")
input.type="text"
input.className="terminal-tab-rename terminal-pane-rename"
input.value=tab.label
const title=pane.head.querySelector(".terminal-pane-title")
title.replaceWith(input)
input.focus()
input.select()
let done=false
const commit=(save)=>{
if(done)return
done=true
input.replaceWith(title)
if(save&&input.value.trim())termSetTabLabel(tab,input.value)
else termRenderPaneHeads()
}
input.addEventListener("mousedown",(e)=>e.stopPropagation())
input.addEventListener("keydown",(e)=>{
e.stopPropagation()
if(e.key==="Enter"){e.preventDefault();commit(true);document.getElementById("terminalInput").focus()}
else if(e.key==="Escape"){e.preventDefault();commit(false);document.getElementById("terminalInput").focus()}
})
input.addEventListener("blur",()=>commit(true))
}
function termOpenPaneSwitcher(pane,anchorEl){
const i=termState.panes.indexOf(pane)
const box=anchorEl.getBoundingClientRect()
const items=termState.tabs.map((t)=>{
const at=termPaneIndexOf(t.sessionId)
const where=at>=0&&at!==i?"  (pane "+(at+1)+")":""
return {label:termEscapeHtml(t.label+where)+(t.sessionId===pane.sessionId?"  ✓":""),icon:"command-line",fn:()=>{termAssignPane(i,t.sessionId);termFocusPane(i)}}
})
if(items.length)items.push({sep:true})
items.push({label:"New session here",icon:"add",fn:()=>{termFocusPane(i);termNewTab().catch(()=>{})}})
const tab=termFindTab(pane.sessionId)
if(tab){
items.push({label:"Rename",icon:"edit",fn:()=>termStartPaneRename(pane)})
items.push({label:"Save session...",icon:"save",disabled:!!tab.elevated,fn:()=>termOpenSaveSessionDialog(tab)})
items.push({label:"Close session",icon:"close",fn:()=>termCloseTab(tab.sessionId)})
}
openContextMenu(items,box.left,box.bottom+4)
}
function termSaveWorkspaceSoon(){
if(!termState.workspaceRestored)return
clearTimeout(termState.workspaceTimer)
termState.workspaceTimer=setTimeout(()=>{
termState.workspaceTimer=null
bridgeCall("terminal.workspace_set",[termWorkspaceSnapshot(termState)]).then((ws)=>{if(ws)termState.workspace=ws}).catch(()=>{})
},700)
}
// First open of a run: bring the split back with fresh shells named and placed like last time.
function termRestoreWorkspaceOrNew(){
termState.workspaceRestored=true
const ws=termState.workspace
const descs=ws&&Array.isArray(ws.panes)?ws.panes:[]
if(!descs.some(Boolean))return termNewTab().then(()=>termFillEmptyPanes()).catch(()=>{})
const focus=termState.focusPane
let chain=Promise.resolve()
termState.panes.forEach((pane,i)=>{
const d=descs[i]
const shell=d?(d.profile_id&&(termState.profiles||[]).some((p)=>p.id===d.profile_id)?"profile:"+d.profile_id:(d.shell_id||undefined)):undefined
chain=chain.then(()=>termNewTab(shell,{paneIndex:i,name:d&&d.name?d.name:"",cwd:d?d.cwd:""}).catch(()=>{}))
})
return chain.then(()=>{if(termState.panes[focus])termFocusPane(focus)})
}
function termApplySessionsState(st){
if(!st)return
if(Array.isArray(st.saved))termState.saved=st.saved
if(Array.isArray(st.closed))termState.closed=st.closed
if(typeof st.remember_output==="boolean")termState.rememberOutput=st.remember_output
if(termState.sessionsOpen)termRenderSessionsDrawer()
}
function termLoadSessionsState(){
return bridgeCall("terminal.sessions_state").then((st)=>{
termApplySessionsState(st)
const ws=st&&st.workspace
if(ws&&!termState.tabs.length&&!termState.workspaceRestored){
termState.workspace=ws
termState.layout=termNormalizeLayout(ws.layout)
termState.ratios={v:termClampRatio(ws.ratios&&ws.ratios.v,0,0),h:termClampRatio(ws.ratios&&ws.ratios.h,0,0)}
termState.focusPane=Math.max(0,Math.min(termLayoutPaneCount(termState.layout)-1,ws.focus||0))
termBuildPanes()
}
return st
}).catch(()=>null)
}
function termRememberClosed(tab){
const scrollback=termState.rememberOutput?((tab.prior&&tab.prior.text?tab.prior.text+"\n":"")+tab.buffer).slice(-32768):""
const entry={name:tab.label,shell_id:tab.shellId,profile_id:tab.profileId||"",cwd:tab.cwd||"",scrollback}
return bridgeCall("terminal.closed_remember",[tab.sessionId,entry]).then(termApplySessionsState).catch(()=>{
// The store could not be written: keep this run's list in memory so reopening still works until restart.
termState.closed=termPushClosed(termState.closed,Object.assign({id:"local-"+Math.random().toString(36).slice(2,9),closed_at:new Date().toISOString()},entry))
if(termState.sessionsOpen)termRenderSessionsDrawer()
})
}
function termShellLabel(shellId,profileId){
const profile=profileId?(termState.profiles||[]).find((p)=>p.id===profileId):null
if(profile)return profile.name
const shell=termState.shells.find((s)=>s.id===shellId)
return shell?shell.label:(shellId||"shell")
}
function termShellChoiceFor(entry){
return entry.profile_id&&(termState.profiles||[]).some((p)=>p.id===entry.profile_id)?"profile:"+entry.profile_id:(entry.shell_id||undefined)
}
function termWhen(iso){
const d=new Date(iso)
if(isNaN(d))return ""
const same=d.toDateString()===new Date().toDateString()
return same?d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):d.toLocaleDateString([],{month:"short",day:"numeric"})+" "+d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})
}
function termReopenClosed(entryId){
const entry=entryId?termState.closed.find((x)=>x.id===entryId):termState.closed[0]
if(!entry){showStatusIsland("No recently closed sessions");return Promise.resolve(null)}
termState.closed=termState.closed.filter((x)=>x!==entry)
if(termState.sessionsOpen)termRenderSessionsDrawer()
const take=String(entry.id).indexOf("local-")===0?Promise.resolve(entry):bridgeCall("terminal.closed_pop",[entry.id]).then((st)=>{termApplySessionsState(st);return (st&&st.entry)||entry}).catch(()=>entry)
return take.then((e)=>termOpenForRun().then(()=>termNewTab(termShellChoiceFor(e),{name:e.name,cwd:e.cwd,prior:e.scrollback?{text:e.scrollback,note:"Reopened “"+e.name+"” as a new shell in the same folder - the output above is from the closed session"}:null}))).then((id)=>{
showStatusIsland("Reopened "+entry.name+" (new shell)")
return id
}).catch((err)=>{showToast(err&&err.message?err.message:"Could not reopen the session","error");return null})
}
function termOpenSavedSession(entryId){
const entry=termState.saved.find((x)=>x.id===entryId)
if(!entry)return Promise.resolve(null)
return termOpenForRun().then(()=>termNewTab(termShellChoiceFor(entry),{name:entry.name,cwd:entry.cwd,startup:entry.startup,prior:entry.scrollback?{text:entry.scrollback,note:"Saved output of “"+entry.name+"” ("+termWhen(entry.updated)+") - a new shell starts below"}:null})).then((id)=>{
showStatusIsland("Opened "+entry.name+" (new shell)")
return id
}).catch((err)=>{showToast(err&&err.message?err.message:"Could not open the session","error");return null})
}
function termToggleSessionsDrawer(){
termState.sessionsOpen=!termState.sessionsOpen
if(termState.sessionsOpen&&termState.jobsOpen)termToggleJobsDrawer()
document.getElementById("terminalSessionsDrawer").classList.toggle("hidden",!termState.sessionsOpen)
document.getElementById("terminalSessionsBtn").classList.toggle("active",termState.sessionsOpen)
if(termState.sessionsOpen){termRenderSessionsDrawer();termLoadSessionsState()}
}
function termSessionRowHtml(kind,entry){
const meta=[]
if(kind==="closed"&&entry.closed_at)meta.push("closed "+termWhen(entry.closed_at))
meta.push(termShellLabel(entry.shell_id,entry.profile_id))
if(entry.cwd)meta.push(entry.cwd)
if(kind==="saved"&&entry.startup)meta.push("runs: "+entry.startup.split("\n")[0]+(entry.startup.indexOf("\n")>=0?" ...":""))
if(entry.scrollback)meta.push("with output")
const open=kind==="saved"?'<button type="button" class="terminal-session-open" data-act="open" title="Start a new shell from this saved session">Open</button><button type="button" class="terminal-job-action" data-act="more" title="More"><i class="icon icon-dots-vertical"></i></button>':'<button type="button" class="terminal-session-open" data-act="reopen" title="Start a fresh shell with the same name and folder">Reopen</button><button type="button" class="terminal-job-action" data-act="forget" title="Remove from this list"><i class="icon icon-close"></i></button>'
return '<div class="terminal-session-row" data-kind="'+kind+'" data-id="'+termEscapeHtml(entry.id)+'"><i class="icon '+(kind==="saved"?"icon-save":"icon-clock")+' terminal-session-icon"></i><div class="terminal-session-main"><span class="terminal-session-name">'+termEscapeHtml(entry.name)+'</span><span class="terminal-session-meta" title="'+termEscapeHtml(meta.join(" - "))+'">'+termEscapeHtml(meta.join(" - "))+"</span></div>"+open+"</div>"
}
function termRenderSessionsDrawer(){
const drawer=document.getElementById("terminalSessionsDrawer")
if(!drawer)return
const scroll=drawer.querySelector(".terminal-sessions-body")
const top=scroll?scroll.scrollTop:0
const saved=termState.saved.length?termState.saved.map((x)=>termSessionRowHtml("saved",x)).join(""):'<div class="terminal-jobs-empty">No saved sessions yet. Save one to reopen it later with its name, shell, folder and startup commands.</div>'
const closed=termState.closed.length?termState.closed.map((x)=>termSessionRowHtml("closed",x)).join(""):'<div class="terminal-jobs-empty">Sessions you close show up here.</div>'
drawer.innerHTML='<div class="terminal-jobs-head"><span class="terminal-jobs-title">Sessions</span><span class="terminal-sessions-spacer"></span><button type="button" class="terminal-jobs-filter" data-act="save-current"'+(termFindTab(termState.activeId)?"":" disabled")+'>Save current...</button><button type="button" class="terminal-head-btn" data-act="close-drawer" title="Close"><i class="icon icon-close"></i></button></div><div class="terminal-sessions-body"><div class="terminal-sessions-section-title">Saved</div>'+saved+'<div class="terminal-sessions-section-title"><span>Recently closed</span><label class="terminal-sessions-remember" title="Keep the last 32 KB of output (secrets redacted) so a reopened session shows it as history"><input type="checkbox" data-act="remember"'+(termState.rememberOutput?" checked":"")+'><span>Keep output</span></label>'+(termState.closed.length?'<button type="button" class="terminal-sessions-link" data-act="clear-closed">Clear</button>':"")+'</div>'+closed+'<div class="terminal-sessions-note">A closed process cannot come back. Reopen starts a fresh shell with the same name and folder and shows the old output above it as history.</div></div>'
const body=drawer.querySelector(".terminal-sessions-body")
if(body)body.scrollTop=top
}
function termHandleSessionsClick(e){
const btn=e.target.closest("[data-act]")
if(!btn)return
const row=btn.closest(".terminal-session-row")
const id=row?row.dataset.id:null
const act=btn.dataset.act
if(act==="close-drawer"){termToggleSessionsDrawer();return}
if(act==="save-current"){const tab=termFindTab(termState.activeId);if(tab)termOpenSaveSessionDialog(tab);return}
if(act==="remember"){bridgeCall("terminal.set_remember_output",[btn.checked]).then(termApplySessionsState).catch(()=>{});return}
if(act==="clear-closed"){bridgeCall("terminal.closed_forget",[null]).then(termApplySessionsState).catch(()=>{});return}
if(act==="open"){termOpenSavedSession(id);return}
if(act==="reopen"){termReopenClosed(id);return}
if(act==="forget"){bridgeCall("terminal.closed_forget",[id]).then(termApplySessionsState).catch(()=>{});termState.closed=termState.closed.filter((x)=>x.id!==id);termRenderSessionsDrawer();return}
if(act==="more"){
const entry=termState.saved.find((x)=>x.id===id)
if(!entry)return
const box=btn.getBoundingClientRect()
openContextMenu([
{label:"Open",icon:"play",fn:()=>termOpenSavedSession(id)},
{label:"Rename",icon:"edit",fn:()=>termStartSavedRename(row,entry)},
{label:"Edit...",icon:"settings",fn:()=>termOpenSaveSessionDialog(null,entry)},
{sep:true},
{label:"Delete",icon:"trash",danger:true,fn:()=>appConfirm("Delete the saved session “"+entry.name+"”?",{okLabel:"Delete",cancelLabel:"Keep",danger:true}).then((ok)=>{if(ok)bridgeCall("terminal.saved_delete",[id]).then(termApplySessionsState).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))})}
],box.left-150,box.bottom+4)
}
}
function termStartSavedRename(row,entry){
const name=row&&row.querySelector(".terminal-session-name")
if(!name)return
const input=document.createElement("input")
input.type="text"
input.className="terminal-tab-rename"
input.value=entry.name
name.replaceWith(input)
input.focus()
input.select()
let done=false
const commit=(save)=>{
if(done)return
done=true
const value=input.value.trim()
if(!save||!value||value===entry.name){termRenderSessionsDrawer();return}
bridgeCall("terminal.saved_save",[{id:entry.id,name:value,shell_id:entry.shell_id,profile_id:entry.profile_id,cwd:entry.cwd,startup:entry.startup}]).then(termApplySessionsState).catch((err)=>{showToast(err&&err.message?err.message:"Rename failed","error");termRenderSessionsDrawer()})
}
input.addEventListener("keydown",(e)=>{e.stopPropagation();if(e.key==="Enter"){e.preventDefault();commit(true)}else if(e.key==="Escape"){e.preventDefault();commit(false)}})
input.addEventListener("blur",()=>commit(true))
}
// Save the live session (tab) as a reusable definition, or edit an existing saved one (entry).
function termOpenSaveSessionDialog(tab,entry){
const editing=!!entry
const base=editing?entry:{name:tab.label,shell_id:tab.shellId,profile_id:tab.profileId||"",cwd:tab.cwd||"",startup:""}
const cwdPromise=!editing&&tab?bridgeCall("terminal.cwd",[tab.sessionId]).then((cwd)=>cwd||base.cwd).catch(()=>base.cwd):Promise.resolve(base.cwd)
cwdPromise.then((cwd)=>{
const choice=termShellChoiceFor(base)||(termState.shells[0]&&termState.shells[0].id)
const options=termState.shells.map((s)=>'<option value="'+termEscapeHtml(s.id)+'">'+termEscapeHtml(s.label)+"</option>").join("")+(termState.profiles||[]).map((p)=>'<option value="profile:'+termEscapeHtml(p.id)+'">'+termEscapeHtml(p.name)+" (profile)</option>").join("")
const keepLabel=editing?(entry.scrollback?"Keep the output saved with it":""):"Also keep the current output and show it as history when opened"
const el=document.createElement("div")
el.className="term-fanout-modal glass-panel term-session-modal"
el.innerHTML='<div class="term-fanout-title">'+(editing?"Edit saved session":"Save session")+'</div><div class="term-save-target-field"><label for="termSessName">Name</label><input type="text" id="termSessName" maxlength="60" autocomplete="off" spellcheck="false"></div><div class="term-save-target-field"><label for="termSessShell">Shell</label><select id="termSessShell" class="terminal-shell-select">'+options+'</select></div><div class="term-save-target-field"><label for="termSessCwd">Working directory</label><input type="text" id="termSessCwd" autocomplete="off" spellcheck="false" placeholder="Leave empty for the default folder"></div><div class="term-save-target-field"><label for="termSessStartup">Startup commands (one per line, typed into the new shell)</label><textarea id="termSessStartup" rows="3" spellcheck="false" placeholder="cd ~/eng&#10;source venv/bin/activate"></textarea></div>'+(keepLabel?'<label class="term-session-keep"><input type="checkbox" id="termSessKeep"'+(editing?" checked":"")+"><span>"+termEscapeHtml(keepLabel)+"</span></label>":"")+'<div class="term-run-destination">Opening a saved session always starts a fresh shell - a running process cannot be saved.</div><div class="term-fanout-actions"><button type="button" id="termSessCancel">Cancel</button><button type="button" class="term-fanout-run" id="termSessSave">Save</button></div>'
openModal(el)
el.querySelector("#termSessName").value=base.name||""
el.querySelector("#termSessShell").value=choice
el.querySelector("#termSessCwd").value=cwd||""
el.querySelector("#termSessStartup").value=base.startup||""
el.querySelector("#termSessCancel").addEventListener("click",()=>closeModal())
el.querySelector("#termSessSave").addEventListener("click",()=>{
const name=el.querySelector("#termSessName").value.trim()
if(!name){showToast("Give the session a name","error");el.querySelector("#termSessName").focus();return}
const pick=el.querySelector("#termSessShell").value
const isProfile=pick.indexOf("profile:")===0
const profile=isProfile?(termState.profiles||[]).find((p)=>"profile:"+p.id===pick):null
const payload={name,shell_id:profile?profile.shell_id:pick,profile_id:profile?profile.id:"",cwd:el.querySelector("#termSessCwd").value.trim(),startup:el.querySelector("#termSessStartup").value}
const keep=el.querySelector("#termSessKeep")
if(editing){payload.id=entry.id;if(!(keep&&keep.checked))payload.scrollback=""}
else if(keep&&keep.checked&&tab)payload.scrollback=tab.buffer.slice(-65536)
bridgeCall("terminal.saved_save",[payload]).then((st)=>{
termApplySessionsState(st)
closeModal()
showStatusIsland((editing?"Updated ":"Saved session ")+name)
}).catch((err)=>showToast(err&&err.message?err.message:"Save failed","error"))
})
setTimeout(()=>{const n=el.querySelector("#termSessName");n.focus();n.select()},0)
})
}
function termWireDock(){
const panel=document.getElementById("terminalPanel")
panelDockRegister("terminal",{label:"Terminal",getMode:()=>termState.mode,applyMode:termDockApplyMode})
panelDockAttach({name:"terminal",panel:panel,header:panel.querySelector(".terminal-panel-head"),grip:document.getElementById("terminalLayoutBtn"),area:()=>document.getElementById("workArea"),size:(mode)=>mode==="bottom"?termState.height:termState.width,onDrop:(mode)=>panelDockMove("terminal",mode,{fromDrag:true}),canDrag:()=>termState.open})
const head=panel.querySelector(".terminal-panel-head")
if(typeof ResizeObserver==="function")new ResizeObserver(termScheduleHeadLayout).observe(head)
else window.addEventListener("resize",termScheduleHeadLayout)
}
function initTerminal(){
Promise.all([bridgeCall("terminal.shells"),bridgeCall("terminal.get_settings"),bridgeCall("terminal.shell_extras").catch(()=>null)]).then(([shells,settings,extras])=>{
termState.shells=shells
termState.platform=settings.platform||""
termState.extras=extras
termRenderShellSelect()
termRefreshProfiles()
termApplyEnabled(settings.enabled)
termApplyRunBehaviour(settings)
termState.width=settings.panel_width
termState.height=settings.panel_height||320
termState.mode=settings.panel_mode||"right"
// The panel always opens docked at the side (or bottom) the user chose; full size is a choice made with the maximize button.
termState.maximized=false
termApplyLayout()
}).catch((err)=>console.error("terminal init failed",err))
bridgeCall("terminal.jobs_reap").catch(()=>{})
document.getElementById("terminalShellSelect").addEventListener("change",(e)=>{
const sel=e.currentTarget
if(sel.value===TERM_INSTALL_PWSH){sel.value=sel.dataset.last||(termState.shells[0]&&termState.shells[0].id)||"";termInstallPowershell();return}
sel.dataset.last=sel.value
})
document.getElementById("terminalIocBtn").addEventListener("click",termOpenIocModal)
document.getElementById("terminalSearchBtn").addEventListener("click",termToggleSearch)
document.getElementById("terminalSearchClose").addEventListener("click",termCloseSearch)
document.getElementById("terminalSearchPrev").addEventListener("click",()=>termStepSearch(-1))
document.getElementById("terminalSearchNext").addEventListener("click",()=>termStepSearch(1))
document.getElementById("terminalSearchRegex").addEventListener("click",(e)=>{termState.searchRegex=!termState.searchRegex;e.currentTarget.classList.toggle("active",termState.searchRegex);termRunSearch()})
document.getElementById("terminalSearchFilter").addEventListener("click",(e)=>{termState.searchFilter=!termState.searchFilter;e.currentTarget.classList.toggle("active",termState.searchFilter);termRunSearch()})
document.getElementById("terminalSearchInput").addEventListener("input",(e)=>{termState.searchQuery=e.target.value;termState.searchIndex=0;termRunSearch()})
document.getElementById("terminalSearchInput").addEventListener("keydown",(e)=>{
e.stopPropagation()
if(e.key==="Escape"){e.preventDefault();termCloseSearch();return}
if(e.key==="Enter"){e.preventDefault();termStepSearch(e.shiftKey?-1:1)}
})
document.getElementById("terminalBlocksBtn").addEventListener("click",termToggleJobBlocks)
document.getElementById("terminalJobsBtn").addEventListener("click",termToggleJobsDrawer)
document.getElementById("terminalJobsRefreshBtn").addEventListener("click",termRefreshJobs)
document.getElementById("terminalJobsClearBtn").addEventListener("click",()=>bridgeCall("terminal.jobs_clear_finished",[null]).then(()=>termRefreshJobs()).catch(()=>{}))
document.getElementById("terminalJobsList").addEventListener("click",termHandleJobsClick)
document.getElementById("terminalJobsList").addEventListener("contextmenu",(e)=>{const row=e.target.closest(".terminal-job-row");if(!row)return;e.preventDefault();termOpenJobMenu(termFindJob(row.dataset.job),e.clientX,e.clientY)})
document.getElementById("terminalJobsFilters").addEventListener("click",(e)=>{const btn=e.target.closest(".terminal-jobs-filter");if(!btn)return;termState.jobsFilter=btn.dataset.state;termRenderJobs()})
termRefreshJobs()
const dockTerminalBtn=document.getElementById("dockTerminalBtn")
if(dockTerminalBtn)dockTerminalBtn.addEventListener("click",termToggleFromDock)
document.getElementById("terminalAiBtn").addEventListener("click",(e)=>termOpenAiMenu(e.currentTarget))
document.getElementById("terminalLayoutBtn").addEventListener("click",(e)=>termOpenLayoutMenu(e.currentTarget))
document.getElementById("terminalMoreBtn").addEventListener("click",(e)=>termOpenHeadMore(e.currentTarget))
termWireDock()
document.getElementById("terminalMaximizeBtn").addEventListener("click",termToggleMaximize)
document.getElementById("terminalCloseBtn").addEventListener("click",termClosePanel)
document.getElementById("terminalElevateBtn").addEventListener("click",termDoElevate)
document.getElementById("terminalInput").addEventListener("keydown",termHandleKeydown)
document.getElementById("terminalInput").addEventListener("paste",termHandlePaste)
document.getElementById("terminalInput").addEventListener("input",termUpdateLiveEcho)
document.getElementById("terminalInput").addEventListener("input",termSuggestOnInput)
document.getElementById("terminalInput").addEventListener("focus",()=>{termUpdateLiveEcho();termSuggestRefreshIndex(false)})
document.getElementById("terminalInput").addEventListener("blur",()=>{termSuggestHide();termUpdateLiveEcho()})
document.getElementById("terminalInput").addEventListener("keyup",(e)=>{if(/^(Arrow|Home|End|PageUp|PageDown)/.test(e.key))termUpdateLiveEcho()})
document.getElementById("terminalInput").addEventListener("select",termUpdateLiveEcho)
window.addEventListener("resize",termSuggestHide)
termBuildPanes()
document.getElementById("terminalSessionsBtn").addEventListener("click",termToggleSessionsDrawer)
document.getElementById("terminalSplitBtn").addEventListener("click",(e)=>termOpenSplitPicker(e.currentTarget))
document.getElementById("terminalSessionsDrawer").addEventListener("click",termHandleSessionsClick)
document.getElementById("terminalPanel").addEventListener("keydown",(e)=>{if(e.target&&e.target.id!=="terminalInput"&&!/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName||""))termPanelShortcutKey(e)})
termLoadSessionsState()
document.getElementById("terminalClearBtn").addEventListener("click",termClearOutput)
document.getElementById("terminalSaveBtn").addEventListener("click",(e)=>termOpenSaveMenu(e.currentTarget))
termWireResize()
termStartAiRequestWatch()
}
