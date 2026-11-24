// Title-bar notification bell: the history popover closes on Escape, a second bell click closes it (toggle),
// and an outside mousedown closes it. Runs toast.js against a tiny fake DOM.
const fs=require("fs")
const path=require("path")
const src=fs.readFileSync(path.join(__dirname,"..","..","UI","js","components","toast.js"),"utf8")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
function el(id){
return {id:id||"",title:"",dataset:{},className:"",style:{},innerHTML:"",children:[],listeners:{},focused:false,
addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},
contains(o){let n=o;while(n){if(n===this)return true;n=n.parent}return false},
getBoundingClientRect(){return {left:900,bottom:50}},
focus(){this.focused=true},
removeAttribute(k){if(k==="title")this.title=""},
remove(){byId.delete(this.id)}}
}
const byId=new Map()
const docListeners={}
const bell=el("btnToastHistory");bell.title="Notification History";const bellIcon=el("bellIcon");bellIcon.parent=bell
byId.set(bell.id,bell)
const outside=el("somewhereElse")
const document={
getElementById:(id)=>byId.get(id)||null,
createElement:()=>el(""),
body:{appendChild(n){if(n.id)byId.set(n.id,n)}},
addEventListener(t,f){(docListeners[t]=docListeners[t]||new Set()).add(f)},
removeEventListener(t,f){if(docListeners[t])docListeners[t].delete(f)}
}
const timers=[]
const T=new Function("document","window","setTimeout",src+";return {openToastHistory,closeToastHistory,initToastHistory}")(document,{innerWidth:1280},(f)=>timers.push(f))
function flush(){while(timers.length)timers.shift()()}
function fire(t,target,key){for(const f of [...(docListeners[t]||[])])f({target,key,stopPropagation(){}})}
function click(){for(const f of bell.listeners.click)f({currentTarget:bell})}
const open=()=>!!byId.get("toastHistoryPopover")
T.initToastHistory()
click();flush()
check("bell click opens the popover",open())
check("no native tooltip over the open popover (GTK keeps it after the click)",bell.title==="")
fire("keydown",outside,"a")
check("other keys keep it open",open())
fire("keydown",outside,"Escape")
check("Escape closes it",!open())
check("closing restores the bell tooltip",bell.title==="Notification History")
check("Escape returns focus to the bell",bell.focused)
check("Escape removes its listeners",!(docListeners.keydown&&docListeners.keydown.size)&&!(docListeners.mousedown&&docListeners.mousedown.size))
click();flush()
fire("mousedown",bellIcon)
check("mousedown on the bell does not close it first",open())
click();flush()
check("second bell click closes it (toggle)",!open())
click();flush()
fire("mousedown",outside)
check("outside mousedown closes it",!open())
click();click();flush()
check("open then close before the timer leaves no listeners",!(docListeners.keydown&&docListeners.keydown.size)&&!(docListeners.mousedown&&docListeners.mousedown.size))
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
