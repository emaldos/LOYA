function closeContextMenu(){
const m=document.getElementById("appContextMenu")
if(m)m.remove()
document.removeEventListener("mousedown",contextMenuOutsideClick,true)
}
function contextMenuOutsideClick(e){
const m=document.getElementById("appContextMenu")
if(m&&!m.contains(e.target))closeContextMenu()
}
function openContextMenu(items,x,y){
closeContextMenu()
const menu=document.createElement("div")
menu.id="appContextMenu"
menu.className="app-context-menu glass-panel"
const width=210
const rowCount=items.filter((it)=>!it.sep).length
const height=Math.min(340,rowCount*34+items.filter((it)=>it.sep).length*9+14)
menu.style.top=Math.round(Math.min(y,window.innerHeight-height-8))+"px"
menu.style.left=Math.round(Math.min(x,window.innerWidth-width-8))+"px"
items.forEach((it)=>{
if(it.sep){
const sep=document.createElement("div")
sep.className="app-context-menu-sep"
menu.appendChild(sep)
return
}
const btn=document.createElement("button")
btn.type="button"
btn.className="app-context-menu-item"+(it.danger?" danger":"")
btn.disabled=!!it.disabled
btn.innerHTML=(it.icon?`<i class="icon icon-${it.icon}"></i>`:"")+`<span>${it.label}</span>`
if(!it.disabled)btn.addEventListener("click",(e)=>{closeContextMenu();it.fn(e)})
menu.appendChild(btn)
})
document.body.appendChild(menu)
setTimeout(()=>document.addEventListener("mousedown",contextMenuOutsideClick,true),0)
}
