let toastHistory=[]
function showToast(message,type){
let host=document.getElementById("toastHost")
if(!host){
host=document.createElement("div")
host.id="toastHost"
host.className="toast-host"
document.body.appendChild(host)
}
const el=document.createElement("div")
el.className="toast"+(type==="error"?" toast-error":"")
el.textContent=message
host.appendChild(el)
requestAnimationFrame(()=>el.classList.add("show"))
setTimeout(()=>{
el.classList.remove("show")
setTimeout(()=>el.remove(),200)
},3200)
toastHistory.unshift({message:message||"",type:type||"info",ts:Date.now(),seen:false})
if(toastHistory.length>20)toastHistory.length=20
toastUpdateBadge()
}
// A bell entry without a toast; onClick (optional) runs when the entry is clicked in the history popover.
function toastAddHistory(message,type,onClick){
toastHistory.unshift({message:message||"",type:type||"info",ts:Date.now(),seen:false,onClick:typeof onClick==="function"?onClick:null})
if(toastHistory.length>20)toastHistory.length=20
toastUpdateBadge()
}
function toastUpdateBadge(){
const badge=document.getElementById("titlebarNotifyBadge")
if(!badge)return
badge.classList.toggle("hidden",!toastHistory.some((t)=>!t.seen))
}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function toastEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function toastRelativeTime(ts){
const delta=Math.max(0,Date.now()-ts)
if(delta<60000)return "Just now"
if(delta<3600000)return Math.floor(delta/60000)+"m ago"
if(delta<86400000)return Math.floor(delta/3600000)+"h ago"
return Math.floor(delta/86400000)+"d ago"
}
function closeToastHistory(){
const existing=document.getElementById("toastHistoryPopover")
if(existing)existing.remove()
document.removeEventListener("mousedown",toastHistoryOutsideClick,true)
document.removeEventListener("keydown",toastHistoryKey,true)
const bell=document.getElementById("btnToastHistory")
if(bell&&bell.dataset.heldTitle){bell.title=bell.dataset.heldTitle;delete bell.dataset.heldTitle}
}
// The bell itself is not "outside": its click handler toggles, so a second click closes instead of close-then-reopen.
function toastHistoryOutsideClick(e){
const pop=document.getElementById("toastHistoryPopover"),bell=document.getElementById("btnToastHistory")
if(pop&&!pop.contains(e.target)&&!(bell&&bell.contains(e.target)))closeToastHistory()
}
function toastHistoryKey(e){if(e.key==="Escape"){e.stopPropagation();closeToastHistory();const b=document.getElementById("btnToastHistory");if(b)b.focus()}}
function openToastHistory(anchorEl){
if(document.getElementById("toastHistoryPopover")){closeToastHistory();return}
closeToastHistory()
toastHistory.forEach((t)=>{t.seen=true})
toastUpdateBadge()
const pop=document.createElement("div")
pop.id="toastHistoryPopover"
pop.className="toast-history-popover glass-panel"
if(!toastHistory.length){
pop.innerHTML='<div class="toast-history-title">Notifications</div><div class="toast-history-empty">No notifications yet.</div>'
}else{
const rows=toastHistory.map((t,i)=>`<div class="toast-history-row${t.type==="error"?" error":""}${t.onClick?" actionable":""}" data-idx="${i}"><span class="toast-history-msg">${toastEscapeHtml(t.message)}</span><span class="toast-history-time">${toastRelativeTime(t.ts)}</span></div>`).join("")
pop.innerHTML=`<div class="toast-history-title">Notifications</div><div class="toast-history-list">${rows}</div>`
pop.addEventListener("click",(e)=>{
const row=e.target.closest(".toast-history-row.actionable")
const entry=row?toastHistory[parseInt(row.dataset.idx,10)]:null
if(entry&&entry.onClick){closeToastHistory();entry.onClick()}
})
}
document.body.appendChild(pop)
// GTK keeps the native tooltip on screen after the click, over the popover header: no title while it is open.
if(anchorEl.title){anchorEl.dataset.heldTitle=anchorEl.title;anchorEl.removeAttribute("title")}
const rect=anchorEl.getBoundingClientRect()
pop.style.left=Math.round(Math.min(rect.left,window.innerWidth-296))+"px"
pop.style.top=Math.round(rect.bottom+6)+"px"
setTimeout(()=>{if(!document.getElementById("toastHistoryPopover"))return;document.addEventListener("mousedown",toastHistoryOutsideClick,true);document.addEventListener("keydown",toastHistoryKey,true)},0)
}
function initToastHistory(){
document.getElementById("btnToastHistory").addEventListener("click",(e)=>openToastHistory(e.currentTarget))
}
