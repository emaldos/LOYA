// WebKitGTK drops ::-webkit-scrollbar styling once scrollbar-width/color are set, so those are applied to Chromium only (see base.css).
if(typeof document!=="undefined"&&typeof navigator!=="undefined"&&!/\bChrom(e|ium)\//.test(navigator.userAgent))document.documentElement.classList.add("engine-webkit")
// A file dropped where no drop zone handled it would make the webview navigate to that file and replace the app; refuse it.
if(typeof window!=="undefined"&&window.addEventListener){
const loyaHasFiles=(e)=>!!(e.dataTransfer&&Array.prototype.indexOf.call(e.dataTransfer.types||[],"Files")>=0)
window.addEventListener("dragover",(e)=>{if(loyaHasFiles(e)&&!e.defaultPrevented){e.preventDefault();e.dataTransfer.dropEffect="none"}})
window.addEventListener("drop",(e)=>{if(loyaHasFiles(e)&&!e.defaultPrevented)e.preventDefault()})
}
function bridgeResolve(path){
let obj=window.pywebview&&window.pywebview.api
if(!obj)return null
let ctx=null
const parts=path.split(".")
for(let i=0;i<parts.length;i++){
ctx=obj
obj=obj[parts[i]]
if(obj===undefined||obj===null)return null
}
return {fn:obj,ctx:ctx}
}
function bridgeCall(path,args){
args=args||[]
return new Promise((resolve,reject)=>{
function run(){
const target=bridgeResolve(path)
if(!target||typeof target.fn!=="function"){reject(new Error("bridge method missing: "+path));return}
Promise.resolve(target.fn.apply(target.ctx,args)).then(resolve).catch(reject)
}
if(window.pywebview&&window.pywebview.api)run()
else window.addEventListener("pywebviewready",run,{once:true})
})
}
