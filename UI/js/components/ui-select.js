function uiSelectLabel(select){
const opt=select.options[select.selectedIndex]
return opt?opt.textContent:""
}
function uiSelectSyncTrigger(trigger,select){
const label=trigger.querySelector(".ui-select-trigger-label")
if(label)label.textContent=uiSelectLabel(select)
trigger.disabled=select.disabled
}
function uiSelectClose(){
const pop=document.getElementById("uiSelectPopover")
if(pop)pop.remove()
document.removeEventListener("mousedown",uiSelectOutsideClick,true)
window.removeEventListener("keydown",uiSelectKey,true)
const open=document.querySelector(".ui-select-trigger.open")
if(open)open.classList.remove("open")
}
// Escape closes the open list first (window capture runs before the modals' document handlers), so it never closes the
// dialog underneath and leaves the list floating over the next page.
function uiSelectKey(e){
if(e.key!=="Escape")return
e.preventDefault()
e.stopImmediatePropagation()
const open=document.querySelector(".ui-select-trigger.open")
uiSelectClose()
if(open&&typeof open.focus==="function")open.focus()
}
function uiSelectOutsideClick(e){
const pop=document.getElementById("uiSelectPopover")
if(pop&&!pop.contains(e.target)&&!e.target.closest(".ui-select-trigger"))uiSelectClose()
}
function uiSelectOpen(trigger,select){
uiSelectClose()
trigger.classList.add("open")
const rect=trigger.getBoundingClientRect()
const pop=document.createElement("div")
pop.id="uiSelectPopover"
pop.className="ui-select-popover glass-panel"
pop.style.visibility="hidden"
const width=Math.max(rect.width,140)
pop.style.width=Math.round(width)+"px"
pop.style.left=Math.round(Math.min(rect.left,window.innerWidth-width-8))+"px"
pop.style.top="0px"
Array.from(select.options).forEach((opt)=>{
const item=document.createElement("button")
item.type="button"
item.className="ui-select-popover-item"+(opt.selected?" active":"")
item.disabled=opt.disabled
item.textContent=opt.textContent
if(!opt.disabled)item.addEventListener("click",()=>{
select.value=opt.value
select.dispatchEvent(new Event("change",{bubbles:true}))
uiSelectClose()
})
pop.appendChild(item)
})
document.body.appendChild(pop)
// Widen to the longest option (items are nowrap): a long option under a short trigger was clipped mid-word with a sideways scrollbar.
if(pop.scrollWidth>pop.clientWidth){
// scrollWidth stops at the text's end: add back the item's and the popover's right padding and the borders.
const padR=(el)=>parseFloat(getComputedStyle(el).paddingRight)||0
const wide=Math.min(pop.scrollWidth+padR(pop.firstElementChild||pop)+padR(pop)+(pop.offsetWidth-pop.clientWidth),window.innerWidth-16)
pop.style.width=Math.round(wide)+"px"
pop.style.left=Math.round(Math.max(8,Math.min(rect.left,window.innerWidth-wide-8)))+"px"
}
const popH=pop.offsetHeight
const forceDown=select.dataset.dropDown==="down"
let top
if(forceDown){
top=Math.round(rect.bottom+6)
}else{
const spaceBelow=window.innerHeight-rect.bottom-6
const spaceAbove=rect.top-6
top=spaceBelow>=popH||spaceBelow>=spaceAbove?Math.round(rect.bottom+6):Math.round(rect.top-popH-6)
}
top=Math.max(8,Math.min(top,window.innerHeight-popH-8))
pop.style.top=top+"px"
pop.style.visibility="visible"
setTimeout(()=>document.addEventListener("mousedown",uiSelectOutsideClick,true),0)
window.addEventListener("keydown",uiSelectKey,true)
}
function uiSelectEnhance(select){
if(select.dataset.uiSelectEnhanced)return
if(select.closest('[data-page="dashboard"]'))return
select.dataset.uiSelectEnhanced="1"
const trigger=document.createElement("button")
trigger.type="button"
trigger.className="ui-select-trigger "+select.className
trigger.innerHTML='<span class="ui-select-trigger-label"></span><i class="icon icon-arrow-down ui-select-trigger-icon"></i>'
select.classList.add("ui-select-native")
select.insertAdjacentElement("afterend",trigger)
uiSelectSyncTrigger(trigger,select)
trigger.addEventListener("click",(e)=>{
e.stopPropagation()
if(select.disabled)return
if(trigger.classList.contains("open")){uiSelectClose();return}
uiSelectOpen(trigger,select)
})
select.addEventListener("change",()=>uiSelectSyncTrigger(trigger,select))
new MutationObserver(()=>uiSelectSyncTrigger(trigger,select)).observe(select,{childList:true,attributes:true,attributeFilter:["disabled"]})
const valueDesc=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value")
Object.defineProperty(select,"value",{
configurable:true,
get(){return valueDesc.get.call(select)},
set(v){valueDesc.set.call(select,v);uiSelectSyncTrigger(trigger,select)}
})
}
function uiSelectEnhanceIn(root){
if(root.nodeType!==1)return
if(root.matches&&root.matches("select"))uiSelectEnhance(root)
if(root.querySelectorAll)root.querySelectorAll("select").forEach(uiSelectEnhance)
}
function initUiSelects(){
uiSelectEnhanceIn(document.body)
new MutationObserver((mutations)=>{
mutations.forEach((m)=>m.addedNodes.forEach((node)=>uiSelectEnhanceIn(node)))
}).observe(document.body,{childList:true,subtree:true})
}
