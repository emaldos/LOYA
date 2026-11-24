// Reporting: report design picker - theme cards with a live mock-up, font and cover style (window.ReportThemes).
var ReportThemes=(function(){
// Mirror of Cores/Services/report_design.py, used until reportsIO.themes() answers (and when it cannot).
const FONTS=[["theme","Theme default"],["humanist","Humanist sans (Lato)"],["neutral","Neutral sans (Noto Sans)"],["serif-head","Serif headings, sans text"],["serif","Serif (Noto Serif)"],["system","System sans (Segoe UI / Arial)"],["system-serif","System serif (Georgia / Cambria)"]]
const COVERS=[["band","Colour band"],["full","Full colour page"],["simple","Plain, typographic"]]
const SEV={critical:"#9b1c1c",high:"#dc2626",medium:"#f59e0b",low:"#2563eb",info:"#6b7280"}
function builtin(id,name,description,cover,p){
return {id:id,name:name,description:description,default_font:"theme",default_cover_style:cover,fonts:FONTS.map((f)=>({id:f[0],label:f[1]})),cover_styles:COVERS.map((c)=>({id:c[0],label:c[1]})),preview:Object.assign({sev:SEV,text:"#1f2933",muted:"#5f6b7a",rule:"#d3d9e0",soft:"#f4f6f8",on_accent:"#ffffff"},p)}
}
const BUILTIN=[
builtin("corporate","Corporate","Classic consultancy report: serif headings, navy bands, ruled tables.","band",{accent:"#1f4e79",secondary:"#a67c37",ink:"#1f4e79",head_fill:"#1f4e79",head_on:"#ffffff",solid_sev:true,heading_serif:true}),
builtin("modern","Modern","Bold colour blocks, large numerals and a clean humanist sans.","full",{accent:"#3b3fd8",secondary:"#0f172a",ink:"#3b3fd8",head_fill:"#0f172a",head_on:"#ffffff",solid_sev:true,heading_serif:false}),
builtin("minimal","Minimal","Monochrome and ink-saving: hairlines instead of fills, prints well on any printer.","simple",{accent:"#111827",secondary:"#6b7280",ink:"#111827",head_fill:"",head_on:"#111827",solid_sev:false,heading_serif:false}),
]
const STOCK_ACCENT=["#1f4e79"],STOCK_SECONDARY=["#475569","#5b6770"]
let cache=null
// ---- pure helpers (also exercised by tests/js/reporting_export.js) ----
function hex(v){v=String(v||"").trim().toLowerCase();return /^#[0-9a-f]{6}$/.test(v)?v:""}
function lum(c){
const n=[1,3,5].map((i)=>parseInt(c.slice(i,i+2),16)/255).map((x)=>x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4))
return 0.2126*n[0]+0.7152*n[1]+0.0722*n[2]
}
function onColor(c){return lum(c)>0.36?"#111827":"#ffffff"}
function themeOf(themes,id){return themes.filter((t)=>t.id===id)[0]||themes[0]}
// A colour is "the theme's own" when it is unset, a stock default or any built-in theme's default: only those follow a theme change.
function isThemeColor(themes,key,value){
const v=hex(value)
if(!v)return true
if((key==="accent"?STOCK_ACCENT:STOCK_SECONDARY).indexOf(v)>=0)return true
return themes.some((t)=>t.preview&&hex(t.preview[key])===v)
}
// What the document will use: the report's own colour when the author chose one, else the theme's palette.
function colors(themes,theme,branding){
const p=theme.preview||{},b=branding||{}
const accent=isThemeColor(themes,"accent",b.accent)?hex(p.accent)||"#1f4e79":hex(b.accent)
const secondary=isThemeColor(themes,"secondary",b.secondary)?hex(p.secondary)||"#475569":hex(b.secondary)
const fill=p.head_fill===""?"":(theme.id==="modern"?"#0f172a":accent)
return {accent:accent,secondary:secondary,on_accent:onColor(accent),head_fill:fill,head_on:fill?onColor(fill):(hex(p.text)||"#111827"),text:hex(p.text)||"#1f2933",rule:hex(p.rule)||"#d3d9e0",soft:hex(p.soft)||"#f4f6f8",solid_sev:p.solid_sev!==false,serif:!!p.heading_serif,sev:p.sev||SEV}
}
function normalize(themes,branding){
const b=branding||{},t=themeOf(themes,b.theme||"corporate")
const font=t.fonts.some((f)=>f.id===b.font)?b.font:"theme"
const cover=t.cover_styles.some((c)=>c.id===b.cover_style)?b.cover_style:""
return {theme:t.id,font:font,cover_style:cover}
}
// The patch for choosing a theme: its id, and its palette too unless the author picked colours of their own.
function themePatch(themes,branding,id){
const t=themeOf(themes,id),b=branding||{},patch={theme:t.id}
if(isThemeColor(themes,"accent",b.accent)&&hex(t.preview.accent))patch.accent=hex(t.preview.accent)
if(isThemeColor(themes,"secondary",b.secondary)&&hex(t.preview.secondary))patch.secondary=hex(t.preview.secondary)
return patch
}
// ---- DOM ----
function el(tag,cls,text){
const n=document.createElement(tag)
if(cls)n.className=cls
if(text!==undefined&&text!==null)n.textContent=text
return n
}
function bar(cls,style){const n=el("span","rth-b "+(cls||""));if(style)n.setAttribute("style",style);return n}
function mock(theme,c,cover){
const wrap=el("span","rth-mock")
wrap.setAttribute("aria-hidden","true")
const cv=el("span","rth-pg rth-cover rth-cv-"+cover)
cv.style.setProperty("--rth-accent",c.accent)
cv.style.setProperty("--rth-on",c.on_accent)
cv.style.setProperty("--rth-secondary",c.secondary)
cv.style.setProperty("--rth-text",c.text)
const band=el("span","rth-band")
band.appendChild(bar("rth-logo"))
band.appendChild(bar("rth-t1"))
band.appendChild(bar("rth-t2"))
cv.appendChild(band)
const facts=el("span","rth-facts")
for(let i=0;i<4;i++)facts.appendChild(bar("rth-f"))
cv.appendChild(facts)
wrap.appendChild(cv)
const pg=el("span","rth-pg rth-page rth-"+theme.id)
pg.style.setProperty("--rth-accent",c.accent)
pg.style.setProperty("--rth-secondary",c.secondary)
pg.style.setProperty("--rth-text",c.text)
pg.style.setProperty("--rth-rule",c.rule)
pg.style.setProperty("--rth-soft",c.soft)
pg.style.setProperty("--rth-head",c.head_fill||"transparent")
const h=el("span","rth-h"+(c.serif?" serif":""),theme.id==="modern"?"1":"Aa")
pg.appendChild(h)
pg.appendChild(bar("rth-hr"))
const tiles=el("span","rth-tiles")
;["critical","high","medium","low"].forEach((s)=>{const t=bar("rth-tile");t.style.setProperty("--rth-sev",c.sev[s]||SEV[s]);tiles.appendChild(t)})
pg.appendChild(tiles)
pg.appendChild(bar("rth-l"))
pg.appendChild(bar("rth-l short"))
pg.appendChild(bar("rth-th"))
;["critical","high","medium"].forEach((s)=>{
const row=el("span","rth-tr")
row.appendChild(bar("rth-td"))
const badge=bar("rth-sv"+(c.solid_sev?"":" outline"))
badge.style.setProperty("--rth-sev",c.sev[s]||SEV[s])
row.appendChild(badge)
pg.appendChild(row)
})
wrap.appendChild(pg)
return wrap
}
function select(options,value,label){
const s=el("select","rpt-input rpt-select rth-select")
s.setAttribute("aria-label",label)
options.forEach((o)=>{const op=el("option",null,o[1]);op.value=o[0];s.appendChild(op)})
s.value=value
return s
}
function load(){
if(cache)return Promise.resolve(cache)
if(typeof bridgeCall!=="function")return Promise.resolve(BUILTIN)
return bridgeCall("reportsIO.themes",[]).then((list)=>{
if(Array.isArray(list)&&list.length&&list.every((t)=>t&&t.id&&t.preview&&Array.isArray(t.fonts)&&Array.isArray(t.cover_styles)))cache=list
return cache||BUILTIN
}).catch(()=>BUILTIN)
}
// mountPicker(host,{branding,onChange(patch)}) -> {setBranding(branding),value(),destroy()}
function mountPicker(host,opts){
opts=opts||{}
let themes=BUILTIN,branding=Object.assign({},opts.branding||{}),alive=true
const root=el("div","rth")
host.appendChild(root)
function emit(patch){
branding=Object.assign({},branding,patch)
render()
if(typeof opts.onChange==="function"){try{opts.onChange(patch)}catch(e){}}
}
function render(){
if(!alive)return
const cur=normalize(themes,branding),active=themeOf(themes,cur.theme)
root.textContent=""
const cards=el("div","rth-cards")
cards.setAttribute("role","radiogroup")
cards.setAttribute("aria-label","Report theme")
themes.forEach((t)=>{
const on=t.id===cur.theme
const card=el("button","rth-card"+(on?" active":""))
card.type="button"
card.setAttribute("role","radio")
card.setAttribute("aria-checked",on?"true":"false")
card.dataset.theme=t.id
card.title=t.description||""
// The active card shows the chosen cover style; the others their own default, as they would look once picked.
card.appendChild(mock(t,colors(themes,t,on?branding:Object.assign({},branding,themePatch(themes,branding,t.id))),on&&cur.cover_style?cur.cover_style:t.default_cover_style))
const text=el("span","rth-card-text")
text.appendChild(el("span","rth-card-name",t.name))
text.appendChild(el("span","rth-card-desc",t.description||""))
card.appendChild(text)
card.addEventListener("click",()=>{if(t.id!==cur.theme)emit(themePatch(themes,branding,t.id))})
cards.appendChild(card)
})
root.appendChild(cards)
const row=el("div","rth-row")
const fontField=el("label","rth-field")
fontField.appendChild(el("span","rth-field-label","Font"))
const font=select(active.fonts.map((f)=>[f.id,f.label]),cur.font,"Report font")
font.addEventListener("change",()=>emit({font:font.value}))
fontField.appendChild(font)
row.appendChild(fontField)
const coverField=el("label","rth-field")
coverField.appendChild(el("span","rth-field-label","Cover style"))
const def=active.cover_styles.filter((c)=>c.id===active.default_cover_style)[0]
const cover=select([["","Theme default"+(def?" ("+def.label+")":"")]].concat(active.cover_styles.map((c)=>[c.id,c.label])),cur.cover_style,"Cover style")
cover.addEventListener("change",()=>emit({cover_style:cover.value}))
coverField.appendChild(cover)
row.appendChild(coverField)
root.appendChild(row)
}
render()
load().then((list)=>{themes=list;render()})
return {
setBranding:(b)=>{branding=Object.assign({},b||{});render()},
value:()=>normalize(themes,branding),
destroy:()=>{alive=false;if(root.parentNode)root.parentNode.removeChild(root)},
}
}
return {mountPicker:mountPicker,themes:load,_pure:{BUILTIN:BUILTIN,hex:hex,onColor:onColor,isThemeColor:isThemeColor,colors:colors,normalize:normalize,themePatch:themePatch}}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=ReportThemes
if(typeof window!=="undefined")window.ReportThemes=ReportThemes
