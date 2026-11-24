// App-wide navigation guard (SECURITY-AUDIT.md H-05). pywebview gives whatever page the window shows the Python bridge, so the
// window must never navigate: a link click, a form submit, window.open() or a URL/file dropped on the page would otherwise load
// another document in the app window. Links in notes and release notes keep their own handlers (they open http(s)/mailto
// through notes.open_url); everything else is simply not followed. The native backstop is _install_nav_guard() in api.py.
// Loaded right after bridge.js, before any page script, in main.html and mini.html. Pure helpers are exported for Node tests.
const NavGuard=(function(){
// Elements whose own handler decides what a click does with a link (they call preventDefault themselves; we only make sure).
function linkOf(target){
if(!target||typeof target.closest!=="function")return null
return target.closest("a[href],area[href]")
}
function isEditable(target){
if(!target||typeof target.closest!=="function")return false
return !!target.closest("input,textarea,[contenteditable=''],[contenteditable='true'],[contenteditable='plaintext-only']")
}
// A drag that would make the browser navigate when dropped: links, URLs and files.
function dragCarriesNavigation(dt){
const types=Array.from((dt&&dt.types)||[])
return types.some((t)=>t==="Files"||t==="text/uri-list"||t==="text/x-moz-url"||t==="URL")
}
function onClick(e){
const a=linkOf(e.target)
if(a)e.preventDefault()
}
function onSubmit(e){e.preventDefault()}
function onDragOver(e){
// Editors handle their own drops; elsewhere a URL/file drag gets "none" so the drop cannot navigate.
if(e.defaultPrevented||isEditable(e.target)||!dragCarriesNavigation(e.dataTransfer))return
e.preventDefault()
try{e.dataTransfer.dropEffect="none"}catch(_){}
}
function onDrop(e){
// Runs last (bubble phase on window): app drop zones that handled the drop already called preventDefault.
if(e.defaultPrevented)return
if(isEditable(e.target)&&!Array.from((e.dataTransfer&&e.dataTransfer.types)||[]).includes("Files"))return
e.preventDefault()
}
function install(win){
win=win||window
if(win.__loyaNavGuard)return false
win.__loyaNavGuard=true
const doc=win.document
doc.addEventListener("click",onClick,true)
doc.addEventListener("auxclick",onClick,true)
doc.addEventListener("submit",onSubmit,true)
win.addEventListener("dragover",onDragOver,false)
win.addEventListener("drop",onDrop,false)
try{Object.defineProperty(win,"open",{value:function(){return null},writable:false,configurable:false})}catch(_){win.open=function(){return null}}
return true
}
return {install,linkOf,isEditable,dragCarriesNavigation,onClick,onSubmit,onDragOver,onDrop}
})()
if(typeof window!=="undefined"&&window.document)NavGuard.install(window)
if(typeof module!=="undefined"&&module.exports)module.exports=NavGuard
