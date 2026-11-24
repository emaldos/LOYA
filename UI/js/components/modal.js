let _modalOpts={},_modalGuarding=false
function _modalRemove(){
const existing=document.getElementById("appModalBackdrop")
if(existing)existing.remove()
document.removeEventListener("keydown",_modalKeydown,true)
_modalOpts={};_modalGuarding=false
}
// closeModal(true) skips the open modal's onBeforeClose guard; onBeforeClose may return false or a Promise of false to keep the modal open.
function closeModal(force){
const existing=document.getElementById("appModalBackdrop")
if(!existing){_modalRemove();return}
const guard=_modalOpts.onBeforeClose
if(force===true||typeof guard!=="function"){_modalRemove();return}
if(_modalGuarding)return
_modalGuarding=true
Promise.resolve().then(guard).then((ok)=>{
_modalGuarding=false
if(ok!==false&&document.getElementById("appModalBackdrop")===existing)_modalRemove()
}).catch(()=>{_modalGuarding=false})
}
function _modalKeydown(e){
if(e.key!=="Escape")return
if(document.querySelector(".confirm-overlay"))return
if(typeof _modalOpts.onEscape==="function"&&_modalOpts.onEscape(e)===false)return
closeModal()
}
function openModal(contentEl,opts){
opts=opts||{}
closeModal(true)
_modalOpts=opts
const backdrop=document.createElement("div")
backdrop.id="appModalBackdrop"
backdrop.className="app-modal-backdrop"
contentEl.classList.add("app-modal-card")
backdrop.appendChild(contentEl)
if(opts.closeOnBackdrop!==false){
backdrop.addEventListener("mousedown",(e)=>{if(e.target===backdrop)closeModal()})
}
document.addEventListener("keydown",_modalKeydown,true)
document.getElementById("content").appendChild(backdrop)
return backdrop
}
