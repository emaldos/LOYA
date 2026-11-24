// The custom <select> popover widens to its longest option. Before, it kept the trigger's width (min 140px), so
// "Download in the background and install on next restart" under the short "Ask me" trigger was clipped mid-word
// with a sideways scrollbar (Settings > Update). uiSelectOpen runs against a tiny fake DOM.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","components","ui-select.js"),"utf8")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function run(contentWidth,innerWidth){
const appended=[]
function el(tag){
const e={tag,style:{},children:[],classList:{add(){},remove(){}},dataset:{},addEventListener(){},appendChild(c){this.children.push(c);return c},
get firstElementChild(){return this.children[0]||null}}
return e
}
const pop=el("div")
Object.defineProperties(pop,{
scrollWidth:{get(){return Math.max(contentWidth,parseFloat(pop.style.width)-2)}},
clientWidth:{get(){return parseFloat(pop.style.width)-2}},
offsetWidth:{get(){return parseFloat(pop.style.width)}},
offsetHeight:{get(){return 120}},
})
let first=true
const document={
getElementById:()=>null,
querySelector:()=>null,
createElement:(tag)=>{if(tag==="div"&&first){first=false;return pop}return el(tag)},
body:{appendChild:(c)=>appended.push(c)},
addEventListener(){},removeEventListener(){},
}
const window={innerWidth,innerHeight:800,addEventListener(){},removeEventListener(){}}
const getComputedStyle=(e)=>({paddingRight:e===pop?"6px":"10px"})
const trigger={classList:{add(){}},getBoundingClientRect:()=>({left:214,top:250,bottom:282,width:80})}
const select={dataset:{},options:[{textContent:"Ask me",selected:true},{textContent:"Download in the background and install on next restart"},{textContent:"Only notify"}]}
const fn=new Function("document","window","getComputedStyle","setTimeout",source+";return uiSelectOpen")(document,window,getComputedStyle,()=>{})
fn(trigger,select)
return pop
}
const wide=run(312,1280)
check("long option: popover widened to content + paddings + borders",parseFloat(wide.style.width)===312+10+6+2,wide.style.width)
check("long option: still starts under the trigger",wide.style.left==="214px",wide.style.left)
const narrow=run(100,1280)
check("short options keep the trigger/min width",narrow.style.width==="140px",narrow.style.width)
const tight=run(2000,600)
check("never wider than the window minus margins",parseFloat(tight.style.width)===584&&tight.style.left==="8px",tight.style.width+" "+tight.style.left)
// Escape closes the open list (and only the list): before, the popover had no key handling, so Escape closed the
// modal underneath (or nothing) and the list stayed on screen over the next page.
{
const listeners={},removed=[]
let popRemoved=false,focused=false,triggerOpen=true
const trig={classList:{remove(){triggerOpen=false}},focus(){focused=true}}
const document={getElementById:()=>({remove(){popRemoved=true}}),querySelector:(q)=>q===".ui-select-trigger.open"&&triggerOpen?trig:null,removeEventListener(){},addEventListener(){}}
const window={addEventListener(t,f){listeners[t]=f},removeEventListener(t,f){removed.push(t)}}
const api=new Function("document","window",source+";return {uiSelectKey,uiSelectClose}")(document,window)
let prevented=0,stopped=0
const ev=(key)=>({key,preventDefault(){prevented++},stopImmediatePropagation(){stopped++}})
api.uiSelectKey(ev("a"))
check("other keys are left alone",!popRemoved&&prevented===0)
api.uiSelectKey(ev("Escape"))
check("Escape closes the list, keeps the event from the modal and refocuses the trigger",popRemoved&&prevented===1&&stopped===1&&focused&&!triggerOpen)
check("closing drops the key listener",removed.indexOf("keydown")!==-1)
check("opening registers the Escape listener on window capture",/window\.addEventListener\("keydown",uiSelectKey,true\)/.test(source))
}
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
