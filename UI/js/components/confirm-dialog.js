// appConfirm(message,opts) -> Promise<true|false|"extra">. A modal confirmation: focus is trapped inside it (Tab/Shift+Tab cycle
// through its buttons), Esc cancels, focus starts on Cancel for a dangerous action and on OK otherwise, and it goes back to
// the element that had it once the dialog closes. Labels are plain text; opts.bodyHtml is HTML the caller has escaped.
const CONFIRM_FOCUSABLE='button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
function confirmTrapKey(e,box,close){
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();close(false);return true}
if(e.key!=="Tab")return false
const items=Array.from(box.querySelectorAll(CONFIRM_FOCUSABLE)).filter((el)=>!el.closest(".hidden"))
if(!items.length){e.preventDefault();return true}
const first=items[0],last=items[items.length-1],active=box.ownerDocument.activeElement
if(e.shiftKey&&(active===first||!box.contains(active))){e.preventDefault();last.focus();return true}
if(!e.shiftKey&&(active===last||!box.contains(active))){e.preventDefault();first.focus();return true}
return false
}
function appConfirm(message,opts){
opts=opts||{}
return new Promise((resolve)=>{
const before=document.activeElement
const overlay=document.createElement("div")
overlay.className="confirm-overlay"
const box=document.createElement("div")
box.className="confirm-box glass-panel"
box.setAttribute("role","alertdialog")
box.setAttribute("aria-modal","true")
if(opts.wide)box.classList.add("confirm-box-wide")
box.innerHTML=`<div class="confirm-message"></div><div class="confirm-body"></div><div class="confirm-actions"><button type="button" class="confirm-cancel"></button>${opts.extraLabel?'<button type="button" class="confirm-extra"></button>':""}<button type="button" class="confirm-ok${opts.danger?" danger":""}"></button></div>`
const msg=box.querySelector(".confirm-message")
msg.textContent=message
msg.id="confirmMsg"+Date.now().toString(36)
box.setAttribute("aria-labelledby",msg.id)
box.querySelector(".confirm-cancel").textContent=opts.cancelLabel||"Cancel"
box.querySelector(".confirm-ok").textContent=opts.okLabel||"OK"
if(opts.extraLabel)box.querySelector(".confirm-extra").textContent=opts.extraLabel
const body=box.querySelector(".confirm-body")
if(opts.bodyHtml)body.innerHTML=opts.bodyHtml
else body.remove()
overlay.appendChild(box)
document.body.appendChild(overlay)
let done=false
function onKey(e){confirmTrapKey(e,box,close)}
function close(result){
if(done)return
done=true
document.removeEventListener("keydown",onKey,true)
overlay.remove()
try{if(before&&typeof before.focus==="function"&&document.contains(before))before.focus()}catch(_){}
resolve(result)
}
document.addEventListener("keydown",onKey,true)
box.querySelector(".confirm-cancel").addEventListener("click",()=>close(false))
box.querySelector(".confirm-ok").addEventListener("click",()=>close(true))
if(opts.extraLabel)box.querySelector(".confirm-extra").addEventListener("click",()=>close("extra"))
overlay.addEventListener("click",(e)=>{if(e.target===overlay)close(false)})
const start=box.querySelector(opts.danger?".confirm-cancel":".confirm-ok")
try{start.focus()}catch(_){}
})
}
if(typeof module!=="undefined"&&module.exports)module.exports={appConfirm,confirmTrapKey}
