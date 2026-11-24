// Drawing / annotation tool for notes: a vector shape model (stored with the note, base64url JSON in data-shapes) drawn on a plain canvas, and a flattened PNG for the viewer and reports.
// The first part is pure (no DOM) and is also loaded by tests/js/notes_pro.js; the second part is the modal UI.
const NotesDraw=(function(){
const TYPES=["pen","line","arrow","rect","ellipse","hl","blur","redact","text","step"]
const BOX_TYPES=["rect","ellipse","hl","blur","redact"]
const MAX_DIM=4096,MAX_SHAPES=600,MAX_POINTS=4000
function num(v,min,max,dflt){
const n=Number(v)
if(!isFinite(n))return dflt
return Math.max(min,Math.min(max,Math.round(n*100)/100))
}
function color(v,dflt){
const m=/^#([0-9a-f]{6})$/i.exec(String(v||"").trim())
return m?"#"+m[1].toLowerCase():dflt
}
function normShape(s,i){
if(!s||typeof s!=="object"||!TYPES.includes(s.t))return null
const o={id:String(s.id||"s"+i).replace(/[^a-zA-Z0-9_-]/g,"").slice(0,24)||"s"+i,t:s.t,c:color(s.c,"#f03e3e"),sw:num(s.sw,1,80,4)}
const R=100000
if(s.t==="pen"){
const pts=Array.isArray(s.pts)?s.pts.slice(0,MAX_POINTS*2).map((v)=>num(v,-R,R,0)):[]
if(pts.length<4||pts.length%2)return null
o.pts=pts
}else if(s.t==="line"||s.t==="arrow"){
o.x1=num(s.x1,-R,R,0);o.y1=num(s.y1,-R,R,0);o.x2=num(s.x2,-R,R,0);o.y2=num(s.y2,-R,R,0)
}else if(BOX_TYPES.includes(s.t)){
o.x=num(s.x,-R,R,0);o.y=num(s.y,-R,R,0);o.w=num(s.w,0,R,0);o.h=num(s.h,0,R,0)
if(o.w<1||o.h<1)return null
}else if(s.t==="text"){
o.x=num(s.x,-R,R,0);o.y=num(s.y,-R,R,0);o.fs=num(s.fs,6,400,24)
o.text=String(s.text===undefined||s.text===null?"":s.text).replace(/[\u0000-\u0008\u000b-\u001f]/g,"").slice(0,500)
if(!o.text.trim())return null
o.tw=num(s.tw,0,R,0)
}else if(s.t==="step"){
o.x=num(s.x,-R,R,0);o.y=num(s.y,-R,R,0);o.r=num(s.r,4,400,16);o.n=Math.round(num(s.n,0,999,1))
}
return o
}
function norm(model){
const m=model&&typeof model==="object"?model:{}
const out={v:1,w:Math.round(num(m.w,16,MAX_DIM,900)),h:Math.round(num(m.h,16,MAX_DIM,500)),bg:m.bg==="transparent"?"transparent":color(m.bg,""),shapes:[]}
const seen=new Set()
;(Array.isArray(m.shapes)?m.shapes:[]).slice(0,MAX_SHAPES).forEach((s,i)=>{
const o=normShape(s,i)
if(!o)return
while(seen.has(o.id))o.id=o.id+"x"
seen.add(o.id)
out.shapes.push(o)
})
return out
}
function b64urlEncode(str){
let b
if(typeof Buffer!=="undefined"&&typeof window==="undefined")b=Buffer.from(str,"utf8").toString("base64")
else{const bytes=new TextEncoder().encode(str);let bin="";for(let i=0;i<bytes.length;i+=0x8000)bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));b=btoa(bin)}
return b.replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")
}
function b64urlDecode(tok){
const b=String(tok||"").replace(/-/g,"+").replace(/_/g,"/")
const padded=b+"===".slice((b.length+3)%4)
if(typeof Buffer!=="undefined"&&typeof window==="undefined")return Buffer.from(padded,"base64").toString("utf8")
const raw=atob(padded)
return new TextDecoder("utf-8").decode(Uint8Array.from(raw,(c)=>c.charCodeAt(0)))
}
function encode(model){return b64urlEncode(JSON.stringify(norm(model)))}
// Never throws: a missing or damaged token gives null.
function decode(tok){
if(!tok||!/^[A-Za-z0-9_-]+$/.test(String(tok)))return null
try{const d=JSON.parse(b64urlDecode(tok));return d&&typeof d==="object"?norm(d):null}catch(e){return null}
}
function textWidth(s){return s.tw>0?s.tw:Math.max(1,String(s.text||"").split("\n").reduce((m,l)=>Math.max(m,l.length),0))*s.fs*0.58}
function textHeight(s){return String(s.text||"").split("\n").length*s.fs*1.25}
function bbox(s){
if(s.t==="pen"){
let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity
for(let i=0;i<s.pts.length;i+=2){x0=Math.min(x0,s.pts[i]);x1=Math.max(x1,s.pts[i]);y0=Math.min(y0,s.pts[i+1]);y1=Math.max(y1,s.pts[i+1])}
return {x:x0,y:y0,w:x1-x0,h:y1-y0}
}
if(s.t==="line"||s.t==="arrow")return {x:Math.min(s.x1,s.x2),y:Math.min(s.y1,s.y2),w:Math.abs(s.x2-s.x1),h:Math.abs(s.y2-s.y1)}
if(s.t==="text")return {x:s.x,y:s.y,w:textWidth(s),h:textHeight(s)}
if(s.t==="step")return {x:s.x-s.r,y:s.y-s.r,w:s.r*2,h:s.r*2}
return {x:s.x,y:s.y,w:s.w,h:s.h}
}
function segDist(px,py,x1,y1,x2,y2){
const dx=x2-x1,dy=y2-y1
const len=dx*dx+dy*dy
let t=len?((px-x1)*dx+(py-y1)*dy)/len:0
t=Math.max(0,Math.min(1,t))
return Math.hypot(px-(x1+t*dx),py-(y1+t*dy))
}
function hit(s,x,y,tol){
tol=Math.max(tol||4,(s.sw||2)/2+2)
if(s.t==="pen"){
for(let i=0;i+3<s.pts.length;i+=2)if(segDist(x,y,s.pts[i],s.pts[i+1],s.pts[i+2],s.pts[i+3])<=tol)return true
return false
}
if(s.t==="line"||s.t==="arrow")return segDist(x,y,s.x1,s.y1,s.x2,s.y2)<=tol
if(s.t==="step")return Math.hypot(x-s.x,y-s.y)<=s.r+tol
if(s.t==="ellipse"){
const rx=s.w/2+tol,ry=s.h/2+tol,cx=s.x+s.w/2,cy=s.y+s.h/2
return ((x-cx)*(x-cx))/(rx*rx)+((y-cy)*(y-cy))/(ry*ry)<=1
}
const b=bbox(s)
return x>=b.x-tol&&x<=b.x+b.w+tol&&y>=b.y-tol&&y<=b.y+b.h+tol
}
// Topmost shape under the point, or null.
function pick(model,x,y,tol){
for(let i=model.shapes.length-1;i>=0;i--)if(hit(model.shapes[i],x,y,tol))return model.shapes[i]
return null
}
function move(s,dx,dy){
const o=Object.assign({},s)
if(s.t==="pen")o.pts=s.pts.map((v,i)=>v+(i%2?dy:dx))
else if(s.t==="line"||s.t==="arrow"){o.x1+=dx;o.y1+=dy;o.x2+=dx;o.y2+=dy}
else{o.x+=dx;o.y+=dy}
return o
}
function handles(s){
if(s.t==="line"||s.t==="arrow")return [{id:"p1",x:s.x1,y:s.y1},{id:"p2",x:s.x2,y:s.y2}]
const b=bbox(s)
return [{id:"nw",x:b.x,y:b.y},{id:"ne",x:b.x+b.w,y:b.y},{id:"sw",x:b.x,y:b.y+b.h},{id:"se",x:b.x+b.w,y:b.y+b.h}]
}
// Drag handle `h` of shape s to (x,y). Boxes follow the corner; a pen stroke, text label or step marker is scaled about the opposite corner.
function resize(s,h,x,y){
const o=Object.assign({},s)
if(s.t==="line"||s.t==="arrow"){
if(h==="p1"){o.x1=x;o.y1=y}else{o.x2=x;o.y2=y}
return o
}
const b=bbox(s)
const ax=h==="nw"||h==="sw"?b.x+b.w:b.x
const ay=h==="nw"||h==="ne"?b.y+b.h:b.y
const nx=Math.min(ax,x),ny=Math.min(ay,y)
const nw=Math.max(2,Math.abs(x-ax)),nh=Math.max(2,Math.abs(y-ay))
if(BOX_TYPES.includes(s.t)){o.x=nx;o.y=ny;o.w=nw;o.h=nh;return o}
if(s.t==="pen"){
const sx=b.w>0?nw/b.w:1,sy=b.h>0?nh/b.h:1
o.pts=s.pts.map((v,i)=>i%2?ny+(v-b.y)*sy:nx+(v-b.x)*sx)
return o
}
const f=Math.max(0.1,Math.max(b.w>0?nw/b.w:1,b.h>0?nh/b.h:1))
if(s.t==="text"){o.fs=Math.max(6,Math.min(400,Math.round(s.fs*f)));o.tw=0;o.x=h==="nw"||h==="sw"?ax-textWidth(o):ax;o.y=h==="nw"||h==="ne"?ay-textHeight(o):ay;return o}
if(s.t==="step"){o.r=Math.max(4,Math.min(400,Math.round(s.r*f)));o.x=(h==="nw"||h==="sw"?ax-o.r:ax+o.r);o.y=(h==="nw"||h==="ne"?ay-o.r:ay+o.r);return o}
return o
}
function nextStep(model){
return model.shapes.reduce((m,s)=>s.t==="step"?Math.max(m,s.n):m,0)+1
}
function arrowHead(x1,y1,x2,y2,size){
const a=Math.atan2(y2-y1,x2-x1)
const s=size
return [{x:x2,y:y2},{x:x2-s*Math.cos(a-0.45),y:y2-s*Math.sin(a-0.45)},{x:x2-s*Math.cos(a+0.45),y:y2-s*Math.sin(a+0.45)}]
}
// Fewer points for a freehand stroke: drop points closer than `min` to the last kept one.
function thin(pts,min){
if(pts.length<=4)return pts.slice()
const out=[pts[0],pts[1]]
for(let i=2;i<pts.length-2;i+=2){
if(Math.hypot(pts[i]-out[out.length-2],pts[i+1]-out[out.length-1])>=min)out.push(pts[i],pts[i+1])
}
out.push(pts[pts.length-2],pts[pts.length-1])
return out
}
function blockSize(w,h){return Math.max(10,Math.ceil(Math.min(w,h)/4))}
return {TYPES,BOX_TYPES,MAX_DIM,norm,encode,decode,bbox,hit,pick,move,handles,resize,nextStep,arrowHead,segDist,thin,blockSize,textWidth,textHeight}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=NotesDraw
// ---------------------------------------------------------------- canvas rendering and the modal (browser only)
function notesDrawRender(ctx,model,baseImg){
const W=model.w,H=model.h
ctx.save()
ctx.setTransform(1,0,0,1,0,0)
ctx.clearRect(0,0,W,H)
if(model.bg&&model.bg!=="transparent"){ctx.fillStyle=model.bg;ctx.fillRect(0,0,W,H)}
if(baseImg)ctx.drawImage(baseImg,0,0,W,H)
ctx.lineCap="round"
ctx.lineJoin="round"
model.shapes.forEach((s)=>notesDrawShape(ctx,s,W,H))
ctx.restore()
}
let _notesDrawScratch=null
function notesDrawPixelate(ctx,x,y,w,h,W,H){
// Mosaic: the region is squeezed to at most four cells across its short side and stretched back without smoothing, so text in it cannot be read back.
const x0=Math.max(0,Math.floor(x)),y0=Math.max(0,Math.floor(y))
const x1=Math.min(W,Math.ceil(x+w)),y1=Math.min(H,Math.ceil(y+h))
const rw=x1-x0,rh=y1-y0
if(rw<2||rh<2)return
const block=NotesDraw.blockSize(rw,rh)
const sw=Math.max(1,Math.ceil(rw/block)),sh=Math.max(1,Math.ceil(rh/block))
if(!_notesDrawScratch)_notesDrawScratch=document.createElement("canvas")
const sc=_notesDrawScratch
sc.width=sw;sc.height=sh
const sx=sc.getContext("2d")
sx.imageSmoothingEnabled=true
sx.clearRect(0,0,sw,sh)
sx.fillStyle="#808080"
sx.fillRect(0,0,sw,sh)
// Halve step by step so every cell is an average of its area, not one sampled pixel.
let cw=rw,ch=rh,src=ctx.canvas,ox=x0,oy=y0
if(!notesDrawPixelate.tmp)notesDrawPixelate.tmp=[document.createElement("canvas"),document.createElement("canvas")]
let flip=0
while(cw>sw*2||ch>sh*2){
const nw=Math.max(sw,Math.ceil(cw/2)),nh=Math.max(sh,Math.ceil(ch/2))
const t=notesDrawPixelate.tmp[flip]
flip=1-flip
t.width=nw;t.height=nh
const tx=t.getContext("2d")
tx.imageSmoothingEnabled=true
tx.fillStyle="#808080";tx.fillRect(0,0,nw,nh)
tx.drawImage(src,ox,oy,cw,ch,0,0,nw,nh)
src=t;ox=0;oy=0;cw=nw;ch=nh
}
sx.drawImage(src,ox,oy,cw,ch,0,0,sw,sh)
ctx.save()
ctx.imageSmoothingEnabled=false
ctx.drawImage(sc,0,0,sw,sh,x0,y0,rw,rh)
ctx.restore()
}
function notesDrawShape(ctx,s,W,H){
ctx.save()
ctx.strokeStyle=s.c
ctx.fillStyle=s.c
ctx.lineWidth=s.sw
if(s.t==="pen"){
ctx.beginPath()
ctx.moveTo(s.pts[0],s.pts[1])
for(let i=2;i<s.pts.length;i+=2)ctx.lineTo(s.pts[i],s.pts[i+1])
ctx.stroke()
}else if(s.t==="line"||s.t==="arrow"){
let ex=s.x2,ey=s.y2
const head=Math.max(10,s.sw*3.5)
if(s.t==="arrow"){
const len=Math.hypot(s.x2-s.x1,s.y2-s.y1)
if(len>head){ex=s.x2-(s.x2-s.x1)/len*head*0.7;ey=s.y2-(s.y2-s.y1)/len*head*0.7}
}
ctx.beginPath();ctx.moveTo(s.x1,s.y1);ctx.lineTo(ex,ey);ctx.stroke()
if(s.t==="arrow"){
const p=NotesDraw.arrowHead(s.x1,s.y1,s.x2,s.y2,head)
ctx.beginPath();ctx.moveTo(p[0].x,p[0].y);ctx.lineTo(p[1].x,p[1].y);ctx.lineTo(p[2].x,p[2].y);ctx.closePath();ctx.fill()
}
}else if(s.t==="rect"){
ctx.strokeRect(s.x,s.y,s.w,s.h)
}else if(s.t==="ellipse"){
ctx.beginPath();ctx.ellipse(s.x+s.w/2,s.y+s.h/2,s.w/2,s.h/2,0,0,Math.PI*2);ctx.stroke()
}else if(s.t==="hl"){
ctx.globalAlpha=0.35
ctx.fillRect(s.x,s.y,s.w,s.h)
}else if(s.t==="redact"){
ctx.fillStyle="#000000"
ctx.fillRect(s.x,s.y,s.w,s.h)
}else if(s.t==="blur"){
notesDrawPixelate(ctx,s.x,s.y,s.w,s.h,W,H)
}else if(s.t==="text"){
ctx.font=`700 ${s.fs}px system-ui,"Segoe UI",Cantarell,"Noto Sans",Arial,sans-serif`
ctx.textBaseline="top"
ctx.lineJoin="round"
ctx.lineWidth=Math.max(2,s.fs/7)
ctx.strokeStyle=notesDrawContrast(s.c)
String(s.text).split("\n").forEach((line,i)=>{
ctx.strokeText(line,s.x,s.y+i*s.fs*1.25)
ctx.fillText(line,s.x,s.y+i*s.fs*1.25)
})
}else if(s.t==="step"){
ctx.beginPath();ctx.arc(s.x,s.y,s.r,0,Math.PI*2);ctx.fill()
ctx.lineWidth=Math.max(2,s.r/7);ctx.strokeStyle="#ffffff";ctx.stroke()
ctx.fillStyle=notesDrawContrast(s.c)==="#000000"?"#000000":"#ffffff"
ctx.font=`700 ${Math.round(s.r*1.15)}px system-ui,"Segoe UI",Cantarell,"Noto Sans",Arial,sans-serif`
ctx.textAlign="center";ctx.textBaseline="middle"
ctx.fillText(String(s.n),s.x,s.y+s.r*0.06)
}
ctx.restore()
}
function notesDrawContrast(hex){
const n=parseInt(String(hex||"#000000").slice(1),16)
const l=(0.299*((n>>16)&255)+0.587*((n>>8)&255)+0.114*(n&255))/255
return l>0.6?"#000000":"#ffffff"
}
const NOTES_DRAW_TOOLS=[
{id:"select",label:"Select / move",key:"v",glyph:"↖"},
{id:"pen",label:"Pen",key:"p",glyph:"✎"},
{id:"line",label:"Line",key:"l",glyph:"╱"},
{id:"arrow",label:"Arrow",key:"a",glyph:"↗"},
{id:"rect",label:"Rectangle",key:"r",glyph:"▭"},
{id:"ellipse",label:"Ellipse",key:"e",glyph:"◯"},
{id:"hl",label:"Highlight box",key:"h",glyph:"▒"},
{id:"blur",label:"Pixelate (hide secrets)",key:"b",glyph:"▓"},
{id:"redact",label:"Redact (solid black)",key:"x",glyph:"█"},
{id:"text",label:"Text label",key:"t",glyph:"T"},
{id:"step",label:"Numbered step marker",key:"n",glyph:"①"}
]
const NOTES_DRAW_QUICK=["#f03e3e","#f59f00","#ffd43b","#37b24d","#1c7ed6","#ae3ec9","#ffffff","#000000"]
let notesDrawState=null
function notesDrawIsOpen(){return !!notesDrawState}
// opts: {title, image (a loaded, same-origin/data: HTMLImageElement or null), model, sketch (bool), onSave(model, pngDataUrl)}
function notesDrawOpen(opts){
if(notesDrawState)notesDrawClose(true)
const img=opts.image||null
let model=NotesDraw.norm(opts.model||{})
if(img){
// A very large screenshot is worked on at a capped size; shapes are stored in that same coordinate space.
const scale=Math.min(1,NotesDraw.MAX_DIM/Math.max(img.naturalWidth||1,img.naturalHeight||1))
const w=Math.max(16,Math.round((img.naturalWidth||model.w)*scale)),h=Math.max(16,Math.round((img.naturalHeight||model.h)*scale))
model.w=w;model.h=h;model.bg=""
}else if(!model.bg)model.bg="#ffffff"
const unit=Math.max(1,Math.round(Math.max(model.w,model.h)/900))
const prefs=(typeof notesState!=="undefined"&&notesState.prefs)||{}
const st=notesDrawState={opts,img,model,unit,tool:img?"arrow":"pen",color:NotesDraw.norm({shapes:[{t:"rect",x:0,y:0,w:5,h:5,c:prefs.draw_color}]}).shapes[0].c,width:[1,2,3,4].includes(prefs.draw_width)?prefs.draw_width:2,sel:null,drag:null,undo:[],redo:[],dirty:false,zoom:0,textInput:null}
const el=document.createElement("div")
el.id="notesDrawBackdrop"
el.className="app-modal-backdrop notes-draw-backdrop"
const tools=NOTES_DRAW_TOOLS.map((t)=>`<button type="button" class="notes-draw-tool" data-tool="${t.id}" title="${t.label} (${t.key.toUpperCase()})"><span>${t.glyph}</span></button>`).join("")
const quick=NOTES_DRAW_QUICK.map((c)=>`<button type="button" class="notes-draw-swatch" data-color="${c}" title="${c}" style="background:${c}"></button>`).join("")
const bgSel=img?"":`<span class="notes-toolbar-sep"></span><label class="notes-draw-label">Canvas</label><select class="notes-draw-select" id="notesDrawSize"><option value="900x500">900 x 500</option><option value="1280x720">1280 x 720</option><option value="600x600">600 x 600</option><option value="1600x900">1600 x 900</option></select><select class="notes-draw-select" id="notesDrawBg"><option value="#ffffff">White</option><option value="#1b1f27">Dark</option><option value="transparent">Transparent</option></select>`
el.innerHTML=`<div class="notes-draw-modal app-modal-card glass-panel" id="notesDrawModal"><div class="notes-draw-head"><span class="notes-popover-title" id="notesDrawTitle"></span><span class="notes-draw-hint" id="notesDrawHint"></span></div>
<div class="notes-draw-bar" id="notesDrawBar">${tools}<span class="notes-toolbar-sep"></span>${quick}<button type="button" class="notes-draw-swatch notes-draw-swatch-more" id="notesDrawMoreColor" title="More colours">+</button><span class="notes-draw-current" id="notesDrawCurrent" title="Current colour"></span><span class="notes-toolbar-sep"></span><label class="notes-draw-label">Width</label><button type="button" class="notes-draw-width" data-width="1" title="Thin"><i style="height:2px"></i></button><button type="button" class="notes-draw-width" data-width="2" title="Medium"><i style="height:4px"></i></button><button type="button" class="notes-draw-width" data-width="3" title="Thick"><i style="height:6px"></i></button><button type="button" class="notes-draw-width" data-width="4" title="Heavy"><i style="height:9px"></i></button><span class="notes-toolbar-sep"></span><button type="button" class="notes-draw-act" id="notesDrawUndo" title="Undo (Ctrl+Z)">Undo</button><button type="button" class="notes-draw-act" id="notesDrawRedo" title="Redo (Ctrl+Y)">Redo</button><button type="button" class="notes-draw-act" id="notesDrawDelete" title="Delete selected shape (Del)">Delete</button><button type="button" class="notes-draw-act" id="notesDrawClear" title="Remove every shape">Clear</button>${bgSel}<span class="notes-toolbar-sep"></span><button type="button" class="notes-draw-act" id="notesDrawZoomOut" title="Zoom out">-</button><span class="notes-draw-zoom" id="notesDrawZoom"></span><button type="button" class="notes-draw-act" id="notesDrawZoomIn" title="Zoom in">+</button><button type="button" class="notes-draw-act" id="notesDrawZoomFit" title="Fit to window">Fit</button></div>
<div class="notes-draw-stage" id="notesDrawStage"><div class="notes-draw-canvas-wrap" id="notesDrawWrap"><canvas id="notesDrawCanvas" class="notes-draw-canvas"></canvas><canvas id="notesDrawOverlay" class="notes-draw-overlay"></canvas></div></div>
<div class="notes-popover-actions"><span class="notes-draw-note">The original image is kept; shapes stay editable. Pixelate and Redact are burned into the picture used by the viewer and reports.</span><button type="button" id="notesDrawCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesDrawSave">Save</button></div></div>`
document.getElementById("content").appendChild(el)
el.querySelector("#notesDrawTitle").textContent=opts.title||(img?"Annotate image":"Drawing")
st.el=el
st.canvas=el.querySelector("#notesDrawCanvas")
st.overlay=el.querySelector("#notesDrawOverlay")
st.wrap=el.querySelector("#notesDrawWrap")
st.stage=el.querySelector("#notesDrawStage")
if(!img){
const sizeSel=el.querySelector("#notesDrawSize"),bgSelEl=el.querySelector("#notesDrawBg")
const key=model.w+"x"+model.h
if(!Array.from(sizeSel.options).some((o)=>o.value===key)){const o=document.createElement("option");o.value=key;o.textContent=model.w+" x "+model.h;sizeSel.appendChild(o)}
sizeSel.value=key
bgSelEl.value=model.bg||"#ffffff"
sizeSel.addEventListener("change",()=>{const p=sizeSel.value.split("x").map((v)=>parseInt(v,10));notesDrawSnapshot();st.model.w=p[0];st.model.h=p[1];st.unit=Math.max(1,Math.round(Math.max(p[0],p[1])/900));notesDrawSizeCanvas();notesDrawPaint()})
bgSelEl.addEventListener("change",()=>{notesDrawSnapshot();st.model.bg=bgSelEl.value;notesDrawPaint()})
}
el.querySelectorAll(".notes-draw-tool").forEach((b)=>b.addEventListener("click",()=>notesDrawSetTool(b.dataset.tool)))
el.querySelectorAll(".notes-draw-swatch[data-color]").forEach((b)=>b.addEventListener("click",()=>notesDrawSetColor(b.dataset.color)))
el.querySelector("#notesDrawMoreColor").addEventListener("click",(e)=>{
if(typeof notesOpenColorPopover==="function")notesOpenColorPopover(e.currentTarget,NotesPro.PALETTE_TEXT,(c)=>{if(c&&c!=="transparent")notesDrawSetColor(c)},st.color,false)
})
el.querySelectorAll(".notes-draw-width").forEach((b)=>b.addEventListener("click",()=>notesDrawSetWidth(parseInt(b.dataset.width,10))))
el.querySelector("#notesDrawUndo").addEventListener("click",notesDrawUndo)
el.querySelector("#notesDrawRedo").addEventListener("click",notesDrawRedo)
el.querySelector("#notesDrawDelete").addEventListener("click",notesDrawDeleteSel)
el.querySelector("#notesDrawClear").addEventListener("click",()=>{if(!st.model.shapes.length)return;notesDrawSnapshot();st.model.shapes=[];st.sel=null;notesDrawPaint()})
el.querySelector("#notesDrawZoomIn").addEventListener("click",()=>notesDrawSetZoom(notesDrawScale()*1.25))
el.querySelector("#notesDrawZoomOut").addEventListener("click",()=>notesDrawSetZoom(notesDrawScale()/1.25))
el.querySelector("#notesDrawZoomFit").addEventListener("click",()=>notesDrawSetZoom(0))
el.querySelector("#notesDrawCancel").addEventListener("click",()=>notesDrawClose(false))
el.querySelector("#notesDrawSave").addEventListener("click",notesDrawSave)
st.overlay.addEventListener("mousedown",notesDrawMouseDown)
st.overlay.addEventListener("dblclick",notesDrawDblClick)
st.overlay.addEventListener("contextmenu",(e)=>e.preventDefault())
document.addEventListener("mousemove",notesDrawMouseMove,true)
document.addEventListener("mouseup",notesDrawMouseUp,true)
document.addEventListener("keydown",notesDrawKeydown,true)
window.addEventListener("resize",notesDrawSizeCanvas)
notesDrawSizeCanvas()
notesDrawSetTool(st.tool)
notesDrawSetColor(st.color,true)
notesDrawSetWidth(st.width,true)
notesDrawPaint()
return st
}
function notesDrawClose(force){
const st=notesDrawState
if(!st)return
const finish=()=>{
document.removeEventListener("mousemove",notesDrawMouseMove,true)
document.removeEventListener("mouseup",notesDrawMouseUp,true)
document.removeEventListener("keydown",notesDrawKeydown,true)
window.removeEventListener("resize",notesDrawSizeCanvas)
if(typeof notesClosePopover==="function")notesClosePopover()
st.el.remove()
notesDrawState=null
}
if(force||!st.dirty){finish();return}
appConfirm("Discard the changes to this drawing?",{okLabel:"Discard",danger:true}).then((yes)=>{if(yes)finish()})
}
function notesDrawScale(){
const st=notesDrawState
const r=st.canvas.getBoundingClientRect()
return r.width?r.width/st.model.w:1
}
function notesDrawSizeCanvas(){
const st=notesDrawState
if(!st)return
const m=st.model
;[st.canvas,st.overlay].forEach((c)=>{if(c.width!==m.w)c.width=m.w;if(c.height!==m.h)c.height=m.h})
const availW=Math.max(120,st.stage.clientWidth-24),availH=Math.max(120,st.stage.clientHeight-24)
const fit=Math.min(1,availW/m.w,availH/m.h)
const z=st.zoom>0?st.zoom:fit
st.wrap.style.width=Math.round(m.w*z)+"px"
st.wrap.style.height=Math.round(m.h*z)+"px"
const zl=document.getElementById("notesDrawZoom")
if(zl)zl.textContent=Math.round(z*100)+"%"
notesDrawPaintOverlay()
}
function notesDrawSetZoom(z){
const st=notesDrawState
st.zoom=z>0?Math.max(0.1,Math.min(4,z)):0
notesDrawSizeCanvas()
}
function notesDrawSetTool(tool){
const st=notesDrawState
notesDrawCommitText()
st.tool=tool
if(tool!=="select")st.sel=null
st.el.querySelectorAll(".notes-draw-tool").forEach((b)=>b.classList.toggle("active",b.dataset.tool===tool))
st.overlay.style.cursor=tool==="select"?"default":(tool==="text"?"text":"crosshair")
const t=NOTES_DRAW_TOOLS.find((x)=>x.id===tool)
const hint={select:"Click a shape to select it, drag to move, drag a corner to resize, Del to delete.",text:"Click where the label should start, type, then press Enter.",step:"Click to drop the next number.",blur:"Drag over the secret. The area is pixelated in the saved picture.",redact:"Drag over the secret. The area is covered with solid black."}[tool]||"Drag on the picture to draw."
st.el.querySelector("#notesDrawHint").textContent=(t?t.label+": ":"")+hint
notesDrawPaintOverlay()
}
function notesDrawSetColor(c,silent){
const st=notesDrawState
st.color=c
st.el.querySelector("#notesDrawCurrent").style.background=c
st.el.querySelectorAll(".notes-draw-swatch[data-color]").forEach((b)=>b.classList.toggle("active",b.dataset.color===c))
if(st.sel&&!silent){const s=notesDrawSelShape();if(s&&s.c!==c){notesDrawSnapshot();s.c=c;notesDrawPaint()}}
if(!silent)bridgeCall("notes.set_editor_pref",["draw_color",c]).then((p)=>{if(typeof notesState!=="undefined")notesState.prefs=p}).catch(()=>{})
}
function notesDrawSetWidth(w,silent){
const st=notesDrawState
st.width=[1,2,3,4].includes(w)?w:2
st.el.querySelectorAll(".notes-draw-width").forEach((b)=>b.classList.toggle("active",parseInt(b.dataset.width,10)===st.width))
if(st.sel&&!silent){const s=notesDrawSelShape();if(s){notesDrawSnapshot();s.sw=notesDrawStroke();if(s.t==="text")s.fs=notesDrawFontSize(),s.tw=0;if(s.t==="step")s.r=notesDrawStepRadius();notesDrawMeasure(s);notesDrawPaint()}}
if(!silent)bridgeCall("notes.set_editor_pref",["draw_width",st.width]).then((p)=>{if(typeof notesState!=="undefined")notesState.prefs=p}).catch(()=>{})
}
function notesDrawStroke(){const st=notesDrawState;return [2,4,7,12][st.width-1]*st.unit}
function notesDrawFontSize(){const st=notesDrawState;return [16,22,30,42][st.width-1]*st.unit}
function notesDrawStepRadius(){const st=notesDrawState;return [12,16,22,30][st.width-1]*st.unit}
function notesDrawSelShape(){const st=notesDrawState;return st.sel?st.model.shapes.find((s)=>s.id===st.sel)||null:null}
function notesDrawSnapshot(){
const st=notesDrawState
st.undo.push(JSON.stringify(st.model))
if(st.undo.length>80)st.undo.shift()
st.redo=[]
st.dirty=true
}
function notesDrawUndo(){
const st=notesDrawState
if(!st||!st.undo.length)return
st.redo.push(JSON.stringify(st.model))
st.model=JSON.parse(st.undo.pop())
st.sel=null;st.dirty=true
notesDrawSizeCanvas();notesDrawPaint()
}
function notesDrawRedo(){
const st=notesDrawState
if(!st||!st.redo.length)return
st.undo.push(JSON.stringify(st.model))
st.model=JSON.parse(st.redo.pop())
st.sel=null;st.dirty=true
notesDrawSizeCanvas();notesDrawPaint()
}
function notesDrawDeleteSel(){
const st=notesDrawState
if(!st||!st.sel)return
notesDrawSnapshot()
st.model.shapes=st.model.shapes.filter((s)=>s.id!==st.sel)
st.sel=null
notesDrawPaint()
}
function notesDrawMeasure(s){
if(s.t!=="text")return
const ctx=notesDrawState.canvas.getContext("2d")
ctx.save()
ctx.font=`700 ${s.fs}px system-ui,"Segoe UI",Cantarell,"Noto Sans",Arial,sans-serif`
s.tw=String(s.text).split("\n").reduce((m,l)=>Math.max(m,ctx.measureText(l).width),1)
ctx.restore()
}
function notesDrawPaint(){
const st=notesDrawState
if(!st)return
notesDrawRender(st.canvas.getContext("2d"),st.model,st.img)
notesDrawPaintOverlay()
const u=document.getElementById("notesDrawUndo"),r=document.getElementById("notesDrawRedo"),d=document.getElementById("notesDrawDelete")
if(u)u.disabled=!st.undo.length
if(r)r.disabled=!st.redo.length
if(d)d.disabled=!st.sel
}
function notesDrawPaintOverlay(){
const st=notesDrawState
if(!st)return
const ctx=st.overlay.getContext("2d")
ctx.setTransform(1,0,0,1,0,0)
ctx.clearRect(0,0,st.overlay.width,st.overlay.height)
const px=1/Math.max(0.05,notesDrawScale())
if(st.drag&&st.drag.preview){
ctx.save();ctx.lineCap="round";ctx.lineJoin="round"
const p=st.drag.preview
if(p.t==="blur"||p.t==="redact"){
ctx.fillStyle=p.t==="redact"?"rgba(0,0,0,0.75)":"rgba(128,128,128,0.45)"
ctx.fillRect(p.x,p.y,p.w,p.h)
ctx.setLineDash([6*px,4*px]);ctx.lineWidth=1.5*px;ctx.strokeStyle="#ffffff";ctx.strokeRect(p.x,p.y,p.w,p.h)
}else notesDrawShape(ctx,p,st.model.w,st.model.h)
ctx.restore()
}
const s=notesDrawSelShape()
if(s){
const b=NotesDraw.bbox(s)
ctx.save()
ctx.lineWidth=1.5*px
ctx.setLineDash([5*px,4*px])
ctx.strokeStyle="#ffffff";ctx.strokeRect(b.x-3*px,b.y-3*px,b.w+6*px,b.h+6*px)
ctx.lineDashOffset=5*px
ctx.strokeStyle="#1c7ed6";ctx.strokeRect(b.x-3*px,b.y-3*px,b.w+6*px,b.h+6*px)
ctx.setLineDash([])
NotesDraw.handles(s).forEach((h)=>{
ctx.fillStyle="#ffffff";ctx.strokeStyle="#1c7ed6";ctx.lineWidth=1.5*px
ctx.beginPath();ctx.rect(h.x-5*px,h.y-5*px,10*px,10*px);ctx.fill();ctx.stroke()
})
ctx.restore()
}
}
function notesDrawPoint(e){
const st=notesDrawState
const r=st.overlay.getBoundingClientRect()
return {x:(e.clientX-r.left)*(st.model.w/r.width),y:(e.clientY-r.top)*(st.model.h/r.height)}
}
function notesDrawNewId(){return "s"+Date.now().toString(36)+Math.random().toString(36).slice(2,6)}
function notesDrawMouseDown(e){
const st=notesDrawState
if(!st||e.button!==0)return
e.preventDefault()
if(st.textInput){notesDrawCommitText();return}
const p=notesDrawPoint(e)
const tol=6/Math.max(0.05,notesDrawScale())
if(st.tool==="select"){
const cur=notesDrawSelShape()
if(cur){
const h=NotesDraw.handles(cur).find((k)=>Math.abs(k.x-p.x)<=tol*1.4&&Math.abs(k.y-p.y)<=tol*1.4)
if(h){st.drag={mode:"resize",handle:h.id,orig:JSON.parse(JSON.stringify(cur)),start:p,snap:false};return}
}
const s=NotesDraw.pick(st.model,p.x,p.y,tol)
st.sel=s?s.id:null
if(s){st.drag={mode:"move",orig:JSON.parse(JSON.stringify(s)),start:p,snap:false};st.color=s.c;st.el.querySelector("#notesDrawCurrent").style.background=s.c}
notesDrawPaint()
return
}
if(st.tool==="text"){notesDrawStartText(p,null);return}
if(st.tool==="step"){
notesDrawSnapshot()
st.model.shapes.push({id:notesDrawNewId(),t:"step",c:st.color,sw:notesDrawStroke(),x:p.x,y:p.y,r:notesDrawStepRadius(),n:NotesDraw.nextStep(st.model)})
notesDrawPaint()
return
}
st.drag={mode:"draw",start:p,pts:[p.x,p.y],preview:null}
}
function notesDrawPreviewShape(st,p){
const a=st.drag.start
const base={id:"preview",t:st.tool,c:st.color,sw:notesDrawStroke()}
if(st.tool==="pen")return Object.assign(base,{pts:st.drag.pts.length>=4?st.drag.pts:[a.x,a.y,p.x,p.y]})
if(st.tool==="line"||st.tool==="arrow"){
let x2=p.x,y2=p.y
if(st.drag.shift){const dx=p.x-a.x,dy=p.y-a.y;const ang=Math.round(Math.atan2(dy,dx)/(Math.PI/4))*(Math.PI/4);const len=Math.hypot(dx,dy);x2=a.x+Math.cos(ang)*len;y2=a.y+Math.sin(ang)*len}
return Object.assign(base,{x1:a.x,y1:a.y,x2,y2})
}
let w=Math.abs(p.x-a.x),h=Math.abs(p.y-a.y)
if(st.drag.shift&&(st.tool==="rect"||st.tool==="ellipse"))w=h=Math.max(w,h)
return Object.assign(base,{x:p.x<a.x?a.x-w:a.x,y:p.y<a.y?a.y-h:a.y,w,h})
}
function notesDrawMouseMove(e){
const st=notesDrawState
if(!st||!st.drag)return
const p=notesDrawPoint(e)
const d=st.drag
d.shift=e.shiftKey
if(d.mode==="draw"){
if(st.tool==="pen")d.pts.push(p.x,p.y)
d.preview=notesDrawPreviewShape(st,p)
notesDrawPaintOverlay()
return
}
const idx=st.model.shapes.findIndex((s)=>s.id===st.sel)
if(idx<0)return
if(!d.snap){if(Math.hypot(p.x-d.start.x,p.y-d.start.y)<2/Math.max(0.05,notesDrawScale()))return;notesDrawSnapshot();d.snap=true}
if(d.mode==="move")st.model.shapes[idx]=NotesDraw.move(d.orig,p.x-d.start.x,p.y-d.start.y)
else{st.model.shapes[idx]=NotesDraw.resize(d.orig,d.handle,p.x,p.y);notesDrawMeasure(st.model.shapes[idx])}
notesDrawPaint()
}
function notesDrawMouseUp(e){
const st=notesDrawState
if(!st||!st.drag)return
const d=st.drag
st.drag=null
if(d.mode!=="draw"){notesDrawPaint();return}
const p=notesDrawPoint(e)
d.shift=e.shiftKey
st.drag=d
const shape=notesDrawPreviewShape(st,p)
st.drag=null
const min=3/Math.max(0.05,notesDrawScale())
let ok=true
if(shape.t==="pen"){shape.pts=NotesDraw.thin(shape.pts,Math.max(1,st.unit));const b=NotesDraw.bbox(shape);ok=shape.pts.length>=4&&(b.w>=min||b.h>=min)}
else if(shape.t==="line"||shape.t==="arrow")ok=Math.hypot(shape.x2-shape.x1,shape.y2-shape.y1)>=min*2
else ok=shape.w>=min&&shape.h>=min
if(ok){
notesDrawSnapshot()
shape.id=notesDrawNewId()
const clean=NotesDraw.norm({w:st.model.w,h:st.model.h,shapes:[shape]}).shapes[0]
if(clean)st.model.shapes.push(clean)
}
notesDrawPaint()
}
function notesDrawDblClick(e){
const st=notesDrawState
if(!st||st.tool!=="select")return
const s=notesDrawSelShape()
if(s&&s.t==="text")notesDrawStartText({x:s.x,y:s.y},s)
}
function notesDrawStartText(p,existing){
const st=notesDrawState
notesDrawCommitText()
const scale=notesDrawScale()
const fs=existing?existing.fs:notesDrawFontSize()
const input=document.createElement("input")
input.type="text"
input.className="notes-draw-text-input"
input.style.left=Math.round(p.x*scale)+"px"
input.style.top=Math.round(p.y*scale)+"px"
input.style.fontSize=Math.max(11,Math.round(fs*scale))+"px"
input.style.color=existing?existing.c:st.color
input.value=existing?existing.text:""
input.maxLength=500
st.wrap.appendChild(input)
st.textInput={input,p,existing:existing?existing.id:null}
input.addEventListener("mousedown",(ev)=>ev.stopPropagation())
setTimeout(()=>{input.focus();input.select()},0)
}
function notesDrawCommitText(){
const st=notesDrawState
if(!st||!st.textInput)return
const t=st.textInput
st.textInput=null
const text=t.input.value.trim()
t.input.remove()
if(t.existing){
const s=st.model.shapes.find((x)=>x.id===t.existing)
if(!s)return
if(!text){notesDrawSnapshot();st.model.shapes=st.model.shapes.filter((x)=>x!==s);st.sel=null}
else if(text!==s.text){notesDrawSnapshot();s.text=text;notesDrawMeasure(s)}
}else if(text){
notesDrawSnapshot()
const s={id:notesDrawNewId(),t:"text",c:st.color,sw:notesDrawStroke(),x:t.p.x,y:t.p.y,fs:notesDrawFontSize(),text,tw:0}
notesDrawMeasure(s)
st.model.shapes.push(s)
}
notesDrawPaint()
}
function notesDrawKeydown(e){
const st=notesDrawState
if(!st)return
if(document.querySelector(".confirm-overlay"))return
const inField=e.target&&e.target.closest&&e.target.closest("input,select,textarea")
// Nothing typed here may reach the note editor underneath (Esc would close it, Ctrl+S would save it).
e.stopPropagation()
if(st.textInput&&e.target===st.textInput.input){
if(e.key==="Enter"){e.preventDefault();notesDrawCommitText()}
else if(e.key==="Escape"){e.preventDefault();const t=st.textInput;st.textInput=null;t.input.remove()}
return
}
if(inField)return
const mod=e.ctrlKey||e.metaKey
const key=(e.key||"").toLowerCase()
if(e.key==="Escape"){
e.preventDefault()
if(document.getElementById("notesPopover")){notesClosePopover();return}
if(st.sel){st.sel=null;notesDrawPaint();return}
notesDrawClose(false)
return
}
if(mod&&key==="z"){e.preventDefault();if(e.shiftKey)notesDrawRedo();else notesDrawUndo();return}
if(mod&&key==="y"){e.preventDefault();notesDrawRedo();return}
if(mod&&key==="s"){e.preventDefault();notesDrawSave();return}
if(mod||e.altKey)return
if(e.key==="Delete"||e.key==="Backspace"){e.preventDefault();notesDrawDeleteSel();return}
if(st.sel&&e.key.startsWith("Arrow")){
e.preventDefault()
const step=(e.shiftKey?10:1)*st.unit
const idx=st.model.shapes.findIndex((s)=>s.id===st.sel)
if(idx>=0){notesDrawSnapshot();st.model.shapes[idx]=NotesDraw.move(st.model.shapes[idx],e.key==="ArrowLeft"?-step:e.key==="ArrowRight"?step:0,e.key==="ArrowUp"?-step:e.key==="ArrowDown"?step:0);notesDrawPaint()}
return
}
const tool=NOTES_DRAW_TOOLS.find((t)=>t.key===key)
if(tool){e.preventDefault();notesDrawSetTool(tool.id)}
}
function notesDrawSave(){
const st=notesDrawState
if(!st)return
notesDrawCommitText()
st.sel=null
notesDrawPaint()
const model=NotesDraw.norm(st.model)
let png=""
try{png=st.canvas.toDataURL("image/png")}catch(err){showToast("This picture cannot be exported by the browser engine","error");return}
const btn=document.getElementById("notesDrawSave")
if(btn)btn.disabled=true
Promise.resolve(st.opts.onSave(model,png)).then(()=>notesDrawClose(true)).catch((err)=>{if(btn)btn.disabled=false;showToast(err&&err.message?err.message:"Could not save the drawing","error")})
}
