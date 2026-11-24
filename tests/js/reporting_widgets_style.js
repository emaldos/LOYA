// Report rich editor -> stored HTML: theme text colour/size the engine re-applies when blocks merge must not be stored
// (dark-theme #eaf6ff text was invisible in exports). Run: node tests/js/reporting_widgets_style.js
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","pages","reporting_widgets.js"),"utf8")
function grab(name){
const start=source.indexOf("function "+name+"(")
if(start<0)throw new Error("missing "+name)
const next=source.indexOf("\nfunction ",start+1)
return source.slice(start,next<0?undefined:next)
}
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const env=new Function("getComputedStyle","document",[grab("toHex"),grab("themeTextStyle"),grab("styleToData")].join("\n;\n")+"\nreturn {toHex,themeTextStyle,styleToData}")
const computed=new Map()
const lib=env((el)=>computed.get(el)||{color:"",fontSize:""},{createElement:()=>{throw new Error("no font in these cases")}})
function span(style){return {tagName:"SPAN",className:"",style,attrs:{},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]}}}
function clone(nodes){return {querySelectorAll:(sel)=>sel==="[style]"?nodes:[]}}
const p={},h4={}
const body={querySelector:(t)=>t==="p"?p:t==="h4"?h4:null}
computed.set(body,{color:"rgb(234, 246, 255)",fontSize:"12.5px"})
computed.set(p,{color:"rgb(234, 246, 255)",fontSize:"12.5px"})
computed.set(h4,{color:"rgb(159, 179, 200)",fontSize:"13px"})
const theme=lib.themeTextStyle(body)
eq("theme colours collected",[...theme.colors].sort(),["#9fb3c8","#eaf6ff"])
eq("theme size",theme.size,"12.5px")
// Backspace at the start of a paragraph after a heading (WebKitGTK output)
const merged=span({color:"rgb(234, 246, 255)",fontSize:"12.5px",fontFamily:"var(--font-ui)"})
// Merged heading text into a paragraph
const mergedHead=span({color:"rgb(159, 179, 200)",fontSize:"13px",letterSpacing:"normal",textTransform:"none"})
// What the colour and size tools produce
const red=span({color:"rgb(220, 38, 38)"}),big=span({fontSize:"18px"}),sameSize=span({fontSize:"12.5px"})
lib.styleToData(clone([merged,mergedHead,red,big,sameSize]),theme)
eq("merge artifact: no colour, no size",merged.attrs,{})
eq("merged heading: no colour, no size",mergedHead.attrs,{})
eq("user colour kept",red.attrs,{"data-color":"#dc2626"})
eq("user size kept",big.attrs,{"data-size":"18"})
eq("base size dropped",sameSize.attrs,{})
// Without theme information (other callers) colours still pass through
const plain=span({color:"rgb(234, 246, 255)"})
lib.styleToData(clone([plain]))
eq("no theme: colour kept",plain.attrs,{"data-color":"#eaf6ff"})
check("fromEditable passes the live theme",/function fromEditable\(body,cards\)\{\nconst theme=themeTextStyle\(body\)/.test(source)&&source.includes("styleToData(c,theme)"))
console.log(`reporting_widgets_style: ${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
