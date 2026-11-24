// Update notification: after launch, asks the bridge whether a newer official release is known (update.notice) and shows
// "LOYA NG X.Y.Z is available" with the release notes (Markdown -> sanitised HTML via LoyaMarkdown), Update now / Remind me
// later / Skip this version, plus a bell entry. Never shown over the lock screen. Pure helpers are exported for the Node tests.
// The launch-time check runs in the Python scheduler a few seconds after the window opens; look early, then settle down.
const UPD_POLL_FIRST_MS=[4000,15000,45000]
const UPD_POLL_EVERY_MS=120000
const updState={shownPopup:{},belled:{},resultShown:false,notice:null,polling:false,timer:null,progressTimer:null}
function updEscape(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function updFormatSize(bytes){
const n=Number(bytes)||0
if(n<=0)return ""
if(n<1024)return n+" B"
if(n<1024*1024)return (n/1024).toFixed(0)+" KB"
return (n/(1024*1024)).toFixed(1)+" MB"
}
function updFormatDate(iso){
const t=Date.parse(String(iso||""))
if(!isFinite(t))return ""
const d=new Date(t)
const months=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
return d.getUTCDate()+" "+months[d.getUTCMonth()]+" "+d.getUTCFullYear()
}
// Release notes come from GitHub, i.e. from the network: render through LoyaMarkdown (every text escaped, links limited to
// http/https/mailto) and then keep only web links - notelink: means nothing outside the notes editor.
function updNotesHtml(md,mdLib){
const lib=mdLib||(typeof LoyaMarkdown!=="undefined"?LoyaMarkdown:null)
const text=String(md||"").trim()
if(!text)return '<p class="upd-notes-empty">No release notes were published for this version.</p>'
if(!lib||typeof lib.toHtml!=="function")return "<pre>"+updEscape(text)+"</pre>"
let html=lib.toHtml(text,{noteClasses:false})
html=html.replace(/<a href="([^"]*)">/g,(m,href)=>/^(https?:\/\/|mailto:)/i.test(href.replace(/&amp;/g,"&"))?'<a href="'+href+'" data-upd-link="1" rel="noreferrer">':'<a data-upd-dead="1">')
return html
}
function updMetaLine(n){
const parts=[]
if(n.current_version&&n.version)parts.push("You have "+updEscape(n.current_version))
const date=updFormatDate(n.published_at)
if(date)parts.push("Released "+updEscape(date))
const size=updFormatSize(n.size)
if(size)parts.push("Download "+updEscape(size))
return parts.join(" &middot; ")
}
function updNoticeHtml(n,mdLib){
n=n||{}
const title=n.title||("LOYA NG "+(n.version||"")+" is available")
const staged=!!n.staged
const primary=!n.installable?'<button type="button" class="upd-btn primary" data-upd-act="github">Download from GitHub</button>':
'<button type="button" class="upd-btn primary" data-upd-act="update">'+(staged?"Restart and install":"Update now")+"</button>"
const name=n.release_name&&!String(n.release_name).includes(String(n.version||"\u0000"))?'<div class="upd-release-name">'+updEscape(n.release_name)+"</div>":""
return '<div class="upd-head"><div class="upd-icon" aria-hidden="true">&#x2191;</div><div class="upd-head-text">'+
'<div class="upd-title" id="updTitle">'+updEscape(title)+"</div>"+name+
'<div class="upd-meta">'+updMetaLine(n)+"</div></div>"+
'<button type="button" class="upd-close" data-upd-act="later" title="Remind me later" aria-label="Close">&times;</button></div>'+
(staged?'<div class="upd-staged">Downloaded and verified. It installs the next time LOYA NG starts.</div>':"")+
'<div class="upd-section-title">What\'s new</div>'+
'<div class="upd-notes">'+updNotesHtml(n.notes,mdLib)+"</div>"+
'<div class="upd-progress hidden" id="updProgress"><div class="upd-bar"><div class="upd-bar-fill" id="updBarFill"></div></div><div class="upd-progress-msg" id="updProgressMsg"></div></div>'+
'<div class="upd-error hidden" id="updError"></div>'+
'<div class="upd-actions" id="updActions">'+
'<a href="#" class="upd-link" data-upd-act="github">Release notes on GitHub</a><span class="upd-spacer"></span>'+
'<button type="button" class="upd-btn" data-upd-act="skip">Skip this version</button>'+
'<button type="button" class="upd-btn" data-upd-act="later">Remind me later</button>'+primary+"</div>"
}
// Which UI a notice asks for: "popup" (modal), "bell" (entry + toast only) or "" (nothing). once-per-session per version.
function updDecide(n,shownPopup,belled){
if(!n||!n.show||!n.version)return ""
if(n.popup&&!(shownPopup||{})[n.version])return "popup"
if(!(belled||{})[n.version])return "bell"
return ""
}
function updIsOpen(){return !!document.getElementById("updOverlay")}
function updClose(){
const el=document.getElementById("updOverlay")
if(el)el.remove()
document.removeEventListener("keydown",updKeydown,true)
if(updState.progressTimer){clearInterval(updState.progressTimer);updState.progressTimer=null}
}
function updKeydown(e){
if(e.key!=="Escape")return
const busy=document.getElementById("updOverlay")&&document.getElementById("updOverlay").dataset.busy==="1"
if(busy)return
e.preventDefault();e.stopPropagation()
updRemindLater()
}
function updOpenLink(href){
if(!/^(https?:\/\/|mailto:)/i.test(String(href||"")))return
bridgeCall("notes.open_url",[href]).catch((err)=>{if(typeof showToast==="function")showToast(err&&err.message?err.message:"Could not open the link","error")})
}
function updOpen(n){
if(!n||!n.version)return
updClose()
updState.notice=n
updState.shownPopup[n.version]=true
const overlay=document.createElement("div")
overlay.id="updOverlay"
overlay.className="upd-overlay"
const card=document.createElement("div")
card.className="upd-card glass-panel"
card.setAttribute("role","dialog")
card.setAttribute("aria-modal","true")
card.setAttribute("aria-labelledby","updTitle")
card.innerHTML=updNoticeHtml(n)
overlay.appendChild(card)
// Links inside the notes must never navigate the app window: open web links in the system browser, drop the rest.
card.addEventListener("click",(e)=>{
const a=e.target.closest("a")
if(a){
e.preventDefault()
if(a.dataset.updAct==="github"){updOpenRelease();return}
if(a.dataset.updLink)updOpenLink(a.getAttribute("href"))
return
}
const btn=e.target.closest("[data-upd-act]")
if(!btn||btn.disabled)return
const act=btn.dataset.updAct
if(act==="update")updStart()
else if(act==="later")updRemindLater()
else if(act==="skip")updSkip()
else if(act==="github")updOpenRelease()
else if(act==="cancel")updCancel()
else if(act==="close")updClose()
})
overlay.addEventListener("mousedown",(e)=>{if(e.target===overlay&&overlay.dataset.busy!=="1")updRemindLater()})
document.addEventListener("keydown",updKeydown,true)
document.body.appendChild(overlay)
const primary=card.querySelector(".upd-btn.primary")
if(primary)primary.focus()
}
function updOpenRelease(){
bridgeCall("update.open_release_page").catch((err)=>{if(typeof showToast==="function")showToast(err&&err.message?err.message:"Could not open the release page","error")})
}
function updRemindLater(){
const n=updState.notice
updClose()
if(n&&n.version)bridgeCall("update.remind_later",[n.version]).catch(()=>{})
}
function updSkip(){
const n=updState.notice
updClose()
if(!n||!n.version)return
bridgeCall("update.skip_version",[n.version]).then(()=>{
if(typeof showToast==="function")showToast("LOYA NG "+n.version+" will not be offered again. You can still install it from Settings > Update.")
}).catch(()=>{})
}
function updSetBusy(busy){
const overlay=document.getElementById("updOverlay")
if(!overlay)return
overlay.dataset.busy=busy?"1":""
overlay.querySelectorAll('[data-upd-act="skip"],[data-upd-act="later"],.upd-close').forEach((b)=>{b.disabled=!!busy;b.classList.toggle("hidden",!!busy)})
}
function updShowProgress(p){
const box=document.getElementById("updProgress")
const fill=document.getElementById("updBarFill")
const msg=document.getElementById("updProgressMsg")
const err=document.getElementById("updError")
const actions=document.getElementById("updActions")
if(!box||!actions)return
box.classList.remove("hidden")
fill.style.width=Math.max(2,Math.min(100,p.percent||0))+"%"
msg.textContent=p.message||""
if(p.stage==="error"){
box.classList.add("hidden")
err.textContent=p.error||"The update failed."
err.classList.remove("hidden")
actions.innerHTML='<span class="upd-spacer"></span><button type="button" class="upd-btn" data-upd-act="close">Close</button><button type="button" class="upd-btn primary" data-upd-act="update">Try again</button>'
updSetBusy(false)
return
}
err.classList.add("hidden")
if(p.stage==="ready"){
actions.innerHTML='<span class="upd-spacer"></span><span class="upd-progress-msg">Your notes and settings are kept. The app reopens by itself.</span>'
return
}
const cancellable=p.running&&(p.percent||0)<64
actions.innerHTML='<span class="upd-spacer"></span>'+(cancellable?'<button type="button" class="upd-btn" data-upd-act="cancel">Cancel</button>':"")
}
function updPollProgress(){
bridgeCall("update.progress").then((p)=>{
updShowProgress(p||{})
if(p&&(p.stage==="error"||p.stage==="ready"||(p.done&&!p.running))&&updState.progressTimer){clearInterval(updState.progressTimer);updState.progressTimer=null}
}).catch(()=>{})
}
function updStart(){
bridgeCall("security.is_locked").then((locked)=>{
if(locked)return
updSetBusy(true)
updShowProgress({percent:1,message:"Starting ...",running:true})
return bridgeCall("update.start_update").then(()=>{
if(updState.progressTimer)clearInterval(updState.progressTimer)
updState.progressTimer=setInterval(updPollProgress,500)
updPollProgress()
})
}).catch((err)=>{updShowProgress({stage:"error",error:err&&err.message?err.message:"The update could not start."})})
}
function updCancel(){
bridgeCall("update.cancel_update").then(()=>updPollProgress()).catch(()=>{})
}
function updBell(n){
updState.belled[n.version]=true
const msg=n.staged?"LOYA NG "+n.version+" is downloaded and installs on the next start.":"LOYA NG "+n.version+" is available. Click to see what's new."
if(typeof toastAddHistory==="function")toastAddHistory(msg,"info",()=>updOpen(n))
}
function updShowResult(res){
if(!res||!res.message||updState.resultShown)return
updState.resultShown=true
if(typeof showToast==="function")showToast(res.message,res.ok?"info":"error")
bridgeCall("update.ack_result").catch(()=>{})
}
function updHandleNotice(n){
if(!n)return
if(n.result)updShowResult(n.result)
const what=updDecide(n,updState.shownPopup,updState.belled)
if(!what)return
// Wait for first-run onboarding or an open confirm dialog to finish; the next poll tries again.
if(what==="popup"&&(document.querySelector(".onboarding-overlay")||document.querySelector(".confirm-overlay")))return
if(!updState.belled[n.version])updBell(n)
if(what==="popup"&&!updIsOpen())updOpen(n)
else if(what==="bell"&&n.mode==="notify"&&typeof showToast==="function")showToast("LOYA NG "+n.version+" is available - see the bell for what's new.")
}
function updPoll(){
if(updState.polling)return Promise.resolve()
updState.polling=true
return bridgeCall("security.is_locked").then((locked)=>{
if(locked){if(updIsOpen()&&document.getElementById("updOverlay").dataset.busy!=="1")updClose();return}
return bridgeCall("update.notice").then(updHandleNotice)
}).catch(()=>{}).finally(()=>{updState.polling=false})
}
// Opened from Settings > Update ("Update Now") or the bell, whatever the reminder/skip state.
function updateNoticeOpenFromSettings(){
return bridgeCall("update.notice").then((n)=>{
if(n&&n.version&&n.current_version&&n.version!==n.current_version){n.show=true;updOpen(n);return true}
return false
})
}
function initUpdateNotice(){
// Confirms a just-installed update as soon as the UI has loaded (allowed while locked); otherwise the helper rolls it back.
bridgeCall("update.launch_ready").catch(()=>{})
UPD_POLL_FIRST_MS.forEach((ms)=>setTimeout(updPoll,ms))
updState.timer=setInterval(updPoll,UPD_POLL_EVERY_MS)
// Never leave the notice on screen once the app locks; after an unlock, look again.
const lock=document.getElementById("lockOverlay")
if(lock&&typeof MutationObserver!=="undefined"){
new MutationObserver(()=>{
const locked=!lock.classList.contains("hidden")
const ov=document.getElementById("updOverlay")
if(locked&&ov&&ov.dataset.busy!=="1")updClose()
if(!locked)setTimeout(updPoll,800)
}).observe(lock,{attributes:true,attributeFilter:["class"]})
}
}
if(typeof document!=="undefined"&&typeof window!=="undefined"&&window.addEventListener&&typeof module==="undefined"){
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initUpdateNotice)
else initUpdateNotice()
}
if(typeof module!=="undefined"&&module.exports)module.exports={updEscape,updFormatSize,updFormatDate,updNotesHtml,updNoticeHtml,updDecide,updMetaLine}
