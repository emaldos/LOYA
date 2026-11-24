// Pure helpers of the report design picker (UI/js/pages/reporting_themes.js). Run: node tests/js/reporting_themes.js
const path=require("path")
const fs=require("fs")
const ROOT=path.resolve(__dirname,"..","..")
const RT=require(path.join(ROOT,"UI","js","pages","reporting_themes.js"))
const P=RT._pure
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
const T=P.BUILTIN
check("exports mountPicker and themes",typeof RT.mountPicker==="function"&&typeof RT.themes==="function")
check("three built-in themes",eq(T.map((t)=>t.id),["corporate","modern","minimal"]))
// the built-in list mirrors Cores/Services/report_design.py (ids, default covers, palette, font and cover ids)
const py=fs.readFileSync(path.join(ROOT,"Cores","Services","report_design.py"),"utf8")
T.forEach((t)=>{
const m=new RegExp('\\{"id":"'+t.id+'","name":"([^"]+)","description":"([^"]+)",\\s*"body":"[a-z-]+","head":"[a-z-]+","cover_style":"([a-z]+)","accent":"(#[0-9a-f]{6})","secondary":"(#[0-9a-f]{6})"').exec(py)
check(t.id+" matches the Python theme table",!!m&&m[1]===t.name&&m[2]===t.description&&m[3]===t.default_cover_style&&m[4]===t.preview.accent&&m[5]===t.preview.secondary,m?m.slice(1).join(" | "):"not found")
})
const pyFonts=[];py.replace(/\{"id":"([a-z-]+)","label":"([^"]+)","body"/g,(_a,id)=>{pyFonts.push(id);return ""})
check("font ids match the Python list",eq(pyFonts,T[0].fonts.map((f)=>f.id)),pyFonts.join(","))
const pyCovers=[];(/COVER_STYLES=\[(.*)\]/.exec(py)||["",""])[1].replace(/"id":"([a-z]+)"/g,(_a,id)=>{pyCovers.push(id);return ""})
check("cover style ids match the Python list",eq(pyCovers,T[0].cover_styles.map((c)=>c.id)),pyCovers.join(","))
// colours
check("hex accepts only #rrggbb",P.hex("#1F4E79")==="#1f4e79"&&P.hex("red")===""&&P.hex("#12345")===""&&P.hex(null)==="")
check("text on a dark fill is white, on a light fill near-black",P.onColor("#1f4e79")==="#ffffff"&&P.onColor("#ffe066")==="#111827")
check("unset, stock and built-in theme colours follow the theme",P.isThemeColor(T,"accent","")&&P.isThemeColor(T,"accent","#1f4e79")&&P.isThemeColor(T,"accent","#3B3FD8")&&P.isThemeColor(T,"secondary","#5b6770")&&P.isThemeColor(T,"secondary","#475569"))
check("a colour the author chose does not",!P.isThemeColor(T,"accent","#aa3300")&&!P.isThemeColor(T,"secondary","#00aa33"))
const modern=T[1]
check("stock colours take the theme palette in the mock-up",P.colors(T,modern,{accent:"#1f4e79",secondary:"#5b6770"}).accent==="#3b3fd8")
check("a custom accent wins in every theme",T.every((t)=>P.colors(T,t,{accent:"#AA3300"}).accent==="#aa3300"))
check("minimal has no table header fill",P.colors(T,T[2],{}).head_fill===""&&P.colors(T,T[2],{}).solid_sev===false&&P.colors(T,T[0],{}).head_fill==="#1f4e79")
// normalisation
check("unknown ids fall back",eq(P.normalize(T,{theme:"<x>",font:"../x",cover_style:"7"}),{theme:"corporate",font:"theme",cover_style:""}))
check("known ids are kept",eq(P.normalize(T,{theme:"minimal",font:"serif",cover_style:"full"}),{theme:"minimal",font:"serif",cover_style:"full"}))
check("an empty branding is the corporate default",eq(P.normalize(T,null),{theme:"corporate",font:"theme",cover_style:""}))
// the patch for a theme change
check("picking a theme carries its palette when the colours were not customised",eq(P.themePatch(T,{accent:"#1f4e79",secondary:"#5b6770"},"modern"),{theme:"modern",accent:"#3b3fd8",secondary:"#0f172a"}))
check("and switches the palette back",eq(P.themePatch(T,{theme:"modern",accent:"#3b3fd8",secondary:"#0f172a"},"corporate"),{theme:"corporate",accent:"#1f4e79",secondary:"#a67c37"}))
check("custom colours stay untouched",eq(P.themePatch(T,{accent:"#aa3300",secondary:"#00aa33"},"minimal"),{theme:"minimal"}))
check("an unknown theme id resolves to the first theme",P.themePatch(T,{},"nope").theme==="corporate")
// the files are plain scripts for both web engines: no storage APIs, every user-select has its -webkit- twin
const js=fs.readFileSync(path.join(ROOT,"UI","js","pages","reporting_themes.js"),"utf8")
const css=fs.readFileSync(path.join(ROOT,"UI","css","pages","reporting_themes.css"),"utf8")
check("no localStorage/sessionStorage",!/localStorage|sessionStorage/.test(js))
check("no innerHTML with data",!/innerHTML/.test(js))
check("user-select is prefixed too",(css.match(/[^-]user-select:/g)||[]).length===(css.match(/-webkit-user-select:/g)||[]).length)
check("form controls inherit the app font",/\.rth-select\{[^}]*font-family:inherit/.test(css)&&/\.rth-card\{[^}]*font-family:inherit/.test(css))
console.log(`\nreporting_themes: ${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
