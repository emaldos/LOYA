let statusIslandTimer=null
function showStatusIsland(message,kind){
let host=document.getElementById("statusIsland")
if(!host){
host=document.createElement("div")
host.id="statusIsland"
host.className="status-island"
const content=document.getElementById("content")
;(content||document.body).appendChild(host)
}
host.className="status-island"+(kind==="error"?" status-island-error":kind==="success"?" status-island-success":"")
host.textContent=message||""
host.title=message||""
// Long messages wrap (components.css); two or more lines get the card radius, and stay up long enough to be read.
host.classList.toggle("status-island-multi",host.offsetHeight>40)
requestAnimationFrame(()=>host.classList.add("show"))
if(statusIslandTimer)clearTimeout(statusIslandTimer)
statusIslandTimer=setTimeout(()=>{
host.classList.remove("show")
},statusIslandDuration(message))
}
// 3.2 s for a short message, plus about 1 s per 25 extra characters, at most 9 s.
function statusIslandDuration(message){
const extra=Math.max(0,String(message||"").length-60)
return Math.min(9000,3200+Math.round(extra*40))
}
if(typeof module!=="undefined"&&module.exports)module.exports={statusIslandDuration}
