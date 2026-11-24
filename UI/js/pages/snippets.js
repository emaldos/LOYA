let snipState={rows:[],favorites:[],favoritesOnly:false,search:"",sortMode:"A -> Z",liveMap:{},liveName:"",liveSig:"",stamp:"",liveTimer:null}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function snipEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function snipIterPlaceholders(text){
const t=String(text||"")
const out=[]
const keyRe=/^[A-Za-z_][A-Za-z0-9_ ]*$/
let i=0
const n=t.length
while(i<n){
if(t[i]!=="{"){i++;continue}
const start=i
let j=i+1,bad=false
while(j<n&&t[j]!=="}"){
if(t[j]==="{"||t[j]==="\r"||t[j]==="\n")bad=true
j++
}
if(j>=n)break
// ${VAR} is a shell variable, not a target placeholder.
if(!bad&&!(start>0&&t[start-1]==="$")){
const raw=t.slice(start+1,j).trim()
if(raw&&keyRe.test(raw))out.push([start,j+1,raw])
}
i=j+1
}
return out
}
function snipResolveCommand(cmd){
const s=(cmd||"").toString().trim()
if(!s)return ""
const map=snipState.liveMap
if(!map||Object.keys(map).length===0)return s
const spans=snipIterPlaceholders(s)
if(!spans.length)return s
let out="",last=0
spans.forEach(([start,end,key])=>{
out+=s.slice(last,start)
const lk=key.toLowerCase()
out+=Object.prototype.hasOwnProperty.call(map,lk)?map[lk]:"{"+key+"}"
last=end
})
out+=s.slice(last)
return out
}
function snipCompactCmd(cmd){
const raw=(cmd||"").toString().trim()
if(!raw)return ""
return raw.split(/\r?\n/).map((l)=>l.trim()).filter(Boolean).join(" ").replace(/\s+/g," ").trim()
}
function snipFavKey(n){
if(!n)return ""
const src=n.src||""
if(n.id!==undefined&&n.id!==null)return src+":"+n.id
if(n.command)return n.command.trim().toLowerCase()
if(n.title)return n.title.trim().toLowerCase()
return ""
}
function snipIsFav(n){
return snipState.favorites.indexOf(snipFavKey(n))!==-1
}
function snipSortKey(n){
return [(n.title||"").toLowerCase(),(n.category||"").toLowerCase(),(n.sub||"").toLowerCase(),(n.command||"").toLowerCase()]
}
function snipCompareKeys(a,b){
for(let i=0;i<a.length;i++){
if(a[i]<b[i])return -1
if(a[i]>b[i])return 1
}
return 0
}
function snipSortRows(rows){
const mode=snipState.sortMode
const list=rows.slice()
if(mode==="Z -> A")return list.sort((a,b)=>-snipCompareKeys(snipSortKey(a),snipSortKey(b)))
if(mode==="Newest")return list.sort((a,b)=>(parseInt(b.id,10)||0)-(parseInt(a.id,10)||0))
if(mode==="Fav First")return list.sort((a,b)=>{
const fa=snipIsFav(a)?0:1,fb=snipIsFav(b)?0:1
if(fa!==fb)return fa-fb
return snipCompareKeys(snipSortKey(a),snipSortKey(b))
})
return list.sort((a,b)=>snipCompareKeys(snipSortKey(a),snipSortKey(b)))
}
function snipFiltered(){
const q=snipState.search.trim().toLowerCase()
let list=snipState.rows
if(q)list=list.filter((n)=>{
const blob=[n.title,n.note_name,n.group_name,n.category,n.sub,n.tags,n.command,n.description].join(" ").toLowerCase()
return blob.includes(q)
})
if(snipState.favoritesOnly)list=list.filter((n)=>snipIsFav(n))
return snipSortRows(list)
}
function snipCopy(text){
if(navigator.clipboard)navigator.clipboard.writeText(text||"").catch(()=>{})
}
function snipRunRow(n,resolved,action,event){
if(event&&event.altKey){snipCopy(n.command||"");showToast("Copied raw command");return}
const meta={noise_level:n.noise_level,confirmMode:termState.snippetRunConfirm,destination:event&&event.destination?event.destination:undefined,row:n,src:n.src}
termPerformClickAction(termResolveClickAction(action,event),resolved,meta,event)
}
function snipToggleFavorite(n){
const key=snipFavKey(n)
if(!key)return
const idx=snipState.favorites.indexOf(key)
if(idx===-1)snipState.favorites.push(key)
else snipState.favorites.splice(idx,1)
bridgeCall("search.set_favorites",[snipState.favorites,snipState.favoritesOnly]).catch((err)=>console.error("set_favorites failed",err))
snipRender()
}
function snipClosePopover(){
const p=document.getElementById("snipNotePopover")
if(p)p.remove()
}
function snipOpenNotePopover(notes,anchorX,anchorY){
snipClosePopover()
const pop=document.createElement("div")
pop.id="snipNotePopover"
pop.className="snip-note-popover glass-panel"
pop.style.top=Math.round(Math.min(anchorY,window.innerHeight-220))+"px"
pop.style.left=Math.round(Math.min(anchorX,window.innerWidth-296))+"px"
pop.innerHTML=`<div class="snip-note-popover-title">This command is used in ${notes.length} notes</div><div class="snip-note-popover-list" id="snipNoteList"></div>`
document.body.appendChild(pop)
const list=pop.querySelector("#snipNoteList")
notes.forEach((n)=>{
const btn=document.createElement("button")
btn.className="snip-note-popover-item"
btn.textContent=(n.note_name||"Untitled")+(n.group_name?"  |  "+n.group_name:"")
btn.addEventListener("click",()=>{
snipClosePopover()
goToPage("notes").then(()=>notesOpen(n.note_id))
})
list.appendChild(btn)
})
setTimeout(()=>document.addEventListener("mousedown",snipPopoverOutsideClick,true),0)
}
function snipPopoverOutsideClick(e){
const p=document.getElementById("snipNotePopover")
if(p&&!p.contains(e.target)){p.remove();document.removeEventListener("mousedown",snipPopoverOutsideClick,true)}
}
function snipShowInNote(n,x,y){
bridgeCall("search.related_notes",[n]).then((all)=>{
const notes=(all||[]).filter((r)=>r&&r.note_id!=null)
if(!notes.length){showToast("Related note not found.","error");return}
if(notes.length===1){goToPage("notes").then(()=>notesOpen(notes[0].note_id));return}
snipOpenNotePopover(notes,x,y)
}).catch((err)=>console.error("related_notes failed",err))
}
function snipOpenMenu(n,x,y){
const favLabel=snipIsFav(n)?"Remove Favorite":"Add Favorite"
const items=[
{label:"Show in Note",icon:"edit",disabled:n.src!=="Commands",fn:()=>snipShowInNote(n,x,y)},
{sep:true},
{label:"Copy Command",icon:"copy",fn:()=>snipCopy(snipResolveCommand(n.command))},
{label:"Copy Raw Command",icon:"copy",fn:()=>snipCopy(n.command||"")},
{label:"Run in Terminal",icon:"command-line",fn:()=>cmdsRunInTerminal(n,snipResolveCommand(n.command))},
{label:"Run against targets...",icon:"target",fn:()=>termOpenFanoutModal(n.command||"",{noise_level:n.noise_level})},
{sep:true},
{label:favLabel,icon:"star",fn:()=>snipToggleFavorite(n)},
{sep:true},
{label:"Copy Title",icon:"copy",fn:()=>snipCopy(n.title||"")}
]
openContextMenu(items,x,y)
}
function snipRenderRow(n){
const tr=document.createElement("tr")
tr.className="snip-row"
const isFav=snipIsFav(n)
const resolved=snipResolveCommand(n.command)
const compact=snipCompactCmd(resolved)
const cat=n.category||"Uncategorized",sub=n.sub||"General"
const metaBits=[]
if(n.tags)metaBits.push("tags: "+n.tags)
if(n.note_name)metaBits.push("note: "+n.note_name)
tr.innerHTML=`<td class="snip-fav-cell"><button class="snip-fav-toggle${isFav?" active":""}" title="Toggle favorite"><i class="icon ${isFav?"icon-star-filled":"icon-star"}"></i></button></td><td>${notesCmdTypeBadgeHtml(n.command_type)}</td><td title="${snipEscapeHtml(metaBits.join(" | ")||cat)}">${snipEscapeHtml(cat)}</td><td>${snipEscapeHtml(sub)}</td><td class="snip-cell-command" title="${snipEscapeHtml(resolved)}">${snipEscapeHtml(compact)}</td><td class="snip-run-cell"><button type="button" class="snip-run-btn" title="Run in Terminal"><i class="icon icon-command-line"></i></button></td>`
tr.querySelector(".snip-fav-toggle").addEventListener("click",(e)=>{e.stopPropagation();snipToggleFavorite(n)})
tr.querySelector(".snip-run-btn").addEventListener("click",(e)=>{e.stopPropagation();snipRunRow(n,resolved,"run",e)})
tr.addEventListener("click",(e)=>snipRunRow(n,resolved,termState.snippetClickAction,e))
tr.addEventListener("auxclick",(e)=>{if(e.button===1){e.preventDefault();snipRunRow(n,resolved,"run",{destination:"new"})}})
tr.addEventListener("contextmenu",(e)=>{e.preventDefault();snipOpenMenu(n,e.clientX,e.clientY)})
return tr
}
function snipRender(){
const tbody=document.getElementById("snipTableBody")
tbody.innerHTML=""
const list=snipFiltered()
document.getElementById("snipEmptyMsg").classList.toggle("hidden",list.length>0)
list.forEach((n)=>tbody.appendChild(snipRenderRow(n)))
document.getElementById("snipTotal").textContent="Total: "+list.length
document.getElementById("snipFavBtn").classList.toggle("active",snipState.favoritesOnly)
document.querySelectorAll(".snip-sort-menu button").forEach((b)=>b.classList.toggle("active",b.dataset.mode===snipState.sortMode))
document.getElementById("snipSortLabel").textContent="Sort: "+snipState.sortMode
}
function snipLiveSig(res){
return ((res&&res.name)||"")+"\u0000"+JSON.stringify((res&&res.map)||{})
}
function snipPageActive(){
const p=document.querySelector('.page[data-page="snippets"]')
return !!(p&&p.classList.contains("active"))&&!document.hidden
}
function snipApplyLive(res){
const sig=snipLiveSig(res)
if(sig===snipState.liveSig)return false
snipState.liveSig=sig
snipState.liveMap=(res&&res.map)||{}
snipState.liveName=(res&&res.name)||""
return true
}
function snipRefreshLiveTarget(){
if(!snipPageActive())return
bridgeCall("search.live_target").then((res)=>{if(snipApplyLive(res))snipRender()}).catch(()=>{})
bridgeCall("commands.stamp").then((st)=>{if(st&&snipState.stamp&&st!==snipState.stamp)snipRefresh()}).catch(()=>{})
}
function snipRefresh(){
return bridgeCall("commands.stamp").catch(()=>"").then((stamp)=>Promise.all([bridgeCall("search.list"),bridgeCall("search.favorites"),bridgeCall("search.live_target")]).then((results)=>{
snipState.stamp=stamp||""
snipState.rows=results[0]
snipState.favorites=results[1].favorites
snipState.favoritesOnly=results[1].favorites_only
snipApplyLive(results[2])
snipRender()
}))
}
function initSnippets(){
return fetch("../pages/snippets.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="snippets"]').innerHTML=html
document.getElementById("snipSearchInput").addEventListener("input",(e)=>{snipState.search=e.target.value;snipRender()})
document.getElementById("snipSortBtn").addEventListener("click",(e)=>{
e.stopPropagation()
document.getElementById("snipSortMenu").classList.toggle("hidden")
})
document.querySelectorAll(".snip-sort-menu button").forEach((b)=>{
b.addEventListener("click",()=>{
snipState.sortMode=b.dataset.mode
document.getElementById("snipSortMenu").classList.add("hidden")
snipRender()
})
})
document.addEventListener("click",(e)=>{
const menu=document.getElementById("snipSortMenu")
const btn=document.getElementById("snipSortBtn")
if(menu&&!menu.classList.contains("hidden")&&!menu.contains(e.target)&&e.target!==btn)menu.classList.add("hidden")
})
document.getElementById("snipFavBtn").addEventListener("click",()=>{
snipState.favoritesOnly=!snipState.favoritesOnly
bridgeCall("search.set_favorites",[snipState.favorites,snipState.favoritesOnly]).catch((err)=>console.error("set_favorites failed",err))
snipRender()
})
if(snipState.liveTimer)clearInterval(snipState.liveTimer)
snipState.liveTimer=setInterval(snipRefreshLiveTarget,2500)
document.addEventListener("loya:page-shown",(e)=>{if(e.detail&&e.detail.page==="snippets"&&!e.detail.first)snipRefresh().catch((err)=>console.error("snippets refresh failed",err))})
return snipRefresh()
}).catch((err)=>console.error("snippets init failed",err))
}
