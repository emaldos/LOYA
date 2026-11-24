// Chains page, "Run History" sub-tab: every run of every chain (chain, start, duration, status, node counts, trigger, target),
// search and filters (chain, status, trigger, date), multi-select delete, a run view (per-node results and timeline, the
// full log through flow-log.js) and the bundle export/import dialogs (chainHistory.* bridge, Cores/Services/chain_history.py).
// pages/chains.js owns the sub-tab switch and calls chhShow()/chhHide(); everything in the DOM is escaped through chhEscape.
// The pure helpers at the top are exported for tests/js/chains_history.js.
const CHH_PAGE=50
const CHH_POLL_MS=3000
const CHH_STATES=[["","Any status"],["done","Done"],["failed","Failed"],["cancelled","Stopped"],["timeout","Timed out"],["running","Running"]]
const CHH_TRIGGERS=[["","Any trigger"],["manual","Manual"],["caller","/caller"],["live","Live target"],["ai","AI"],["import","Imported"]]
const CHH_RANGES=[["","Any time"],["today","Today"],["24h","Last 24 hours"],["7d","Last 7 days"],["30d","Last 30 days"],["custom","Custom range"]]
// ---- pure helpers
function chhEscape(value){
return String(value===undefined||value===null?"":value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function chhDuration(ms){
if(ms===null||ms===undefined||ms===""||isNaN(Number(ms)))return ""
const v=Math.max(0,Number(ms))
if(v<1000)return Math.round(v)+" ms"
if(v<60000)return (v/1000).toFixed(v<10000?1:0)+" s"
const s=Math.round(v/1000)
if(s<3600)return Math.floor(s/60)+" min "+("0"+(s%60)).slice(-2)+" s"
return Math.floor(s/3600)+" h "+("0"+Math.floor((s%3600)/60)).slice(-2)+" min"
}
function chhStateLabel(state){
return {done:"Done",failed:"Failed",cancelled:"Stopped",timeout:"Timed out",running:"Running",paused:"Paused",waiting_approval:"Waiting for approval"}[String(state||"")]||String(state||"Unknown")
}
function chhStateKind(state){
const s=String(state||"")
return s==="done"?"ok":s==="failed"||s==="timeout"?"bad":s==="cancelled"?"muted":s==="paused"||s==="waiting_approval"?"warn":"live"
}
function chhNodeStateKind(state){
const s=String(state||"")
return s==="success"?"ok":s==="fail"||s==="failed"?"bad":s==="skipped"?"muted":s==="running"||s==="waiting"?"live":s==="pending"||s==="planned"?"idle":"muted"
}
function chhTriggerLabel(source,imported){
const base={manual:"Manual",caller:"/caller",live:"Live target",ai:"AI",chains:"Manual"}[String(source||"")]||String(source||"-")
return imported?base+" (imported)":base
}
// "4/6 ok, 1 failed, 1 skipped" from {"total","success","fail","skipped","pending","running"}.
function chhNodesText(counts){
const c=counts||{}
const total=Number(c.total)||0
if(!total)return "-"
const parts=[(Number(c.success)||0)+"/"+total+" ok"]
if(c.fail)parts.push(c.fail+" failed")
if(c.skipped)parts.push(c.skipped+" skipped")
if(c.running)parts.push(c.running+" running")
return parts.join(", ")
}
function chhPad(v){return ("0"+v).slice(-2)}
// Local wall-clock time of an ISO timestamp: "2026-11-24 14:03:05" (empty for junk).
function chhTime(iso){
const t=iso?Date.parse(String(iso)):NaN
if(isNaN(t))return ""
const d=new Date(t)
return d.getFullYear()+"-"+chhPad(d.getMonth()+1)+"-"+chhPad(d.getDate())+" "+chhPad(d.getHours())+":"+chhPad(d.getMinutes())+":"+chhPad(d.getSeconds())
}
// A date range choice -> {date_from,date_to} as ISO UTC strings (empty = open). custom uses "YYYY-MM-DD" local days.
function chhRangeBounds(range,from,to,now){
const n=now instanceof Date?now:new Date()
const iso=(d)=>d.toISOString()
const day=(s,end)=>{const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s||""));if(!m)return null;return end?new Date(+m[1],+m[2]-1,+m[3],23,59,59,999):new Date(+m[1],+m[2]-1,+m[3],0,0,0,0)}
if(range==="today")return {date_from:iso(new Date(n.getFullYear(),n.getMonth(),n.getDate())),date_to:""}
if(range==="24h")return {date_from:iso(new Date(n.getTime()-86400000)),date_to:""}
if(range==="7d")return {date_from:iso(new Date(n.getTime()-7*86400000)),date_to:""}
if(range==="30d")return {date_from:iso(new Date(n.getTime()-30*86400000)),date_to:""}
if(range==="custom"){const a=day(from,false),b=day(to,true);return {date_from:a?iso(a):"",date_to:b?iso(b):""}}
return {date_from:"",date_to:""}
}
// UI filters -> the chainHistory.list filter object.
function chhQuery(f,offset,now){
const x=f||{}
const out={query:String(x.query||"").trim(),state:x.state||"",offset:Math.max(0,Number(offset)||0),limit:CHH_PAGE}
if(x.chain){if(/^id:/.test(x.chain))out.playbook_id=Number(x.chain.slice(3));else if(/^name:/.test(x.chain))out.chain=x.chain.slice(5)}
if(x.trigger==="import")out.mode="import"
else if(x.trigger)out.source=x.trigger
Object.assign(out,chhRangeBounds(x.range,x.from,x.to,now))
return out
}
function chhFiltered(f){
const x=f||{}
return !!(String(x.query||"").trim()||x.chain||x.state||x.trigger||x.range)
}
// Gantt bars for the run view: [{node,title,kind,left,width}] in percent of the run's span.
function chhTimelineBars(timeline,startedAt,endedAt,now){
const rows=(Array.isArray(timeline)?timeline:[]).filter((n)=>n&&n.started_at)
const t0=Date.parse(startedAt||"")
let t1=Date.parse(endedAt||"")
if(isNaN(t1))t1=now instanceof Date?now.getTime():Date.now()
const starts=rows.map((n)=>Date.parse(n.started_at)).filter((v)=>!isNaN(v))
const lo=isNaN(t0)?Math.min.apply(null,starts.length?starts:[0]):t0
const ends=rows.map((n)=>{const e=Date.parse(n.ended_at||"");return isNaN(e)?Date.parse(n.started_at)+(Number(n.duration_ms)||0):e}).filter((v)=>!isNaN(v))
const hi=Math.max(t1,ends.length?Math.max.apply(null,ends):t1)
const span=Math.max(1,hi-lo)
return rows.map((n)=>{
const a=Date.parse(n.started_at)
let b=Date.parse(n.ended_at||"")
if(isNaN(b))b=a+(Number(n.duration_ms)||0)
const left=Math.max(0,Math.min(100,(a-lo)/span*100))
const width=Math.max(0.6,Math.min(100-left,(Math.max(b,a)-a)/span*100))
return {node:n.node,title:n.title||n.node,kind:chhNodeStateKind(n.state),left:Math.round(left*100)/100,width:Math.round(width*100)/100}
})
}
// What an import preview says, as HTML for the confirmation dialog.
function chhPreviewHtml(p,name){
const x=p||{}
const chains=Array.isArray(x.chains)?x.chains:[],runs=Array.isArray(x.runs)?x.runs:[]
const plural=(n,w)=>n+" "+w+(n===1?"":"s")
let h='<div class="chh-preview">'
if(name)h+='<div class="chh-preview-file">'+chhEscape(name)+(x.legacy?" (single chain export)":"")+"</div>"
h+='<div class="chh-preview-counts"><span>'+plural(chains.length,"chain")+"</span><span>"+plural(runs.length,"run")+"</span></div>"
if(chains.length)h+='<ul class="chh-preview-list">'+chains.slice(0,12).map((c)=>"<li><b>"+chhEscape(c.name)+"</b> - "+plural(Number(c.nodes)||0,"node")+(c.scripts?', <span class="chh-warn-text">'+plural(c.scripts,"script")+"</span>":"")+(c.conflict?' <span class="chh-tag">name taken</span>':"")+"</li>").join("")+(chains.length>12?"<li>and "+(chains.length-12)+" more</li>":"")+"</ul>"
if(x.chain_conflicts)h+='<div class="chh-preview-opt"><div class="chh-preview-q">'+plural(x.chain_conflicts,"chain")+' already exist'+(x.chain_conflicts===1?"s":"")+' with the same name:</div><label><input type="radio" name="chhChainMode" value="rename" checked> Import as a copy (adds "(imported)")</label><label><input type="radio" name="chhChainMode" value="skip"> Skip it, keep mine</label><label><input type="radio" name="chhChainMode" value="replace"> Replace my diagram with the file\'s</label></div>'
if(x.run_conflicts)h+='<div class="chh-preview-opt"><div class="chh-preview-q">'+plural(x.run_conflicts,"run")+' already '+(x.run_conflicts===1?"is":"are")+' in the history:</div><label><input type="radio" name="chhRunMode" value="skip" checked> Skip</label><label><input type="radio" name="chhRunMode" value="replace"> Replace</label><label><input type="radio" name="chhRunMode" value="rename"> Keep both (new run id)</label></div>'
if(chains.length&&runs.length)h+='<div class="chh-preview-opt"><label><input type="checkbox" class="chh-imp-chains" checked> Import the chains</label><label><input type="checkbox" class="chh-imp-runs" checked> Import the run history</label></div>'
if(chains.length)h+='<div class="chh-note">Imported chains are marked <b>Imported - review</b>: open each one and read its commands'+(x.scripts?" and <b>"+plural(x.scripts,"script")+"</b>":"")+" before the first run. A file cannot turn off script sandboxing.</div>"
if(x.history_overflow)h+='<div class="chh-note chh-warn-text">The history keeps the newest 300 runs: '+plural(x.history_overflow,"older run")+" will be removed.</div>"
if(Array.isArray(x.problems)&&x.problems.length)h+='<div class="chh-problems"><div class="chh-preview-q">Left out (not valid):</div><ul>'+x.problems.slice(0,8).map((m)=>"<li>"+chhEscape(m)+"</li>").join("")+(x.problems.length>8?"<li>and "+(x.problems.length-8)+" more</li>":"")+"</ul></div>"
return h+"</div>"
}
function chhResultText(r){
const x=r||{},c=x.chains||{},u=x.runs||{}
const parts=[]
const n=(a)=>Array.isArray(a)?a.length:0
if(n(c.created))parts.push(n(c.created)+" chain"+(n(c.created)===1?"":"s")+" imported")
if(n(c.replaced))parts.push(n(c.replaced)+" replaced")
if(n(c.skipped))parts.push(n(c.skipped)+" skipped")
if(u.imported)parts.push(u.imported+" run"+(u.imported===1?"":"s")+" imported")
if(u.skipped)parts.push(u.skipped+" run"+(u.skipped===1?"":"s")+" skipped")
if(n(x.problems))parts.push(n(x.problems)+" left out")
return parts.length?parts.join(", "):"Nothing was imported"
}
// ---- state
let chhState={mounted:false,shown:false,view:"list",filters:{query:"",chain:"",state:"",trigger:"",range:"",from:"",to:""},offset:0,items:[],total:0,selected:new Set(),facets:null,detail:null,detailId:null,token:0,timer:null,typing:null}
function chhBridge(path,args){return typeof bridgeCall==="function"?bridgeCall(path,args||[]):Promise.reject(new Error("bridge unavailable"))}
function chhToast(msg,kind){if(typeof showToast==="function")showToast(msg,kind)}
function chhErr(err,fallback){return err&&err.message?String(err.message):fallback}
function chhHost(){return document.getElementById("chainsHistoryHost")}
function chhOptions(rows,value){return rows.map((r)=>'<option value="'+chhEscape(r[0])+'"'+(String(r[0])===String(value||"")?" selected":"")+">"+chhEscape(r[1])+"</option>").join("")}
// ---- list view
function chhMount(){
if(chhState.mounted)return
const host=chhHost()
if(!host)return
chhState.mounted=true
const f=chhState.filters
host.innerHTML='<div class="chh-list-view"><div class="chh-filters">'+
'<select class="chh-select" data-chh="chain" aria-label="Chain"><option value="">All chains</option></select>'+
'<select class="chh-select" data-chh="state" aria-label="Status">'+chhOptions(CHH_STATES,f.state)+"</select>"+
'<select class="chh-select" data-chh="trigger" aria-label="Trigger">'+chhOptions(CHH_TRIGGERS,f.trigger)+"</select>"+
'<select class="chh-select" data-chh="range" aria-label="Date">'+chhOptions(CHH_RANGES,f.range)+"</select>"+
'<span class="chh-custom hidden"><input type="date" class="chh-date" data-chh="from" aria-label="From"><span class="chh-dash">to</span><input type="date" class="chh-date" data-chh="to" aria-label="To"></span>'+
'<button type="button" class="chh-link-btn hidden" data-chh="reset">Clear filters</button>'+
'<span class="chh-sel-info" aria-live="polite"></span></div>'+
'<div class="chh-table" role="table" aria-label="Chain runs"><div class="chh-row chh-head" role="row"><span class="chh-c-check" role="columnheader"><input type="checkbox" class="chh-check" data-chh="all" aria-label="Select every run on this page"></span><span role="columnheader">Chain</span><span role="columnheader">Started</span><span role="columnheader">Duration</span><span role="columnheader">Status</span><span role="columnheader">Nodes</span><span role="columnheader" class="chh-c-trigger">Trigger</span><span role="columnheader" class="chh-c-target">Target</span></div><div class="chh-body"></div></div>'+
'<div class="chh-pager"><button type="button" class="chh-link-btn" data-chh="prev">Newer</button><span class="chh-page-info"></span><button type="button" class="chh-link-btn" data-chh="next">Older</button></div></div>'+
'<div class="chh-detail-view hidden"></div>'
host.addEventListener("change",chhOnChange)
host.addEventListener("click",chhOnClick)
host.addEventListener("keydown",(e)=>{
const row=e.target.closest&&e.target.closest(".chh-run-row")
if(row&&(e.key==="Enter"||e.key===" ")&&!e.target.closest("input")){e.preventDefault();chhOpenRun(row.dataset.run)}
})
const search=document.getElementById("chhSearchInput")
if(search){
search.addEventListener("input",()=>{
if(chhState.typing)clearTimeout(chhState.typing)
chhState.typing=setTimeout(()=>{chhState.typing=null;chhState.filters.query=search.value;chhState.offset=0;chhState.selected.clear();chhLoad()},200)
})
search.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&search.value){e.preventDefault();e.stopPropagation();search.value="";chhState.filters.query="";chhState.offset=0;chhLoad()}})
}
const on=(id,fn)=>{const el=document.getElementById(id);if(el)el.addEventListener("click",fn)}
on("chhRefreshBtn",()=>{chhLoadFacets();if(chhState.view==="detail")chhOpenRun(chhState.detailId);else chhLoad()})
on("chhImportBtn",chhImport)
on("chhExportBtn",chhExportRunsPrompt)
on("chhDeleteBtn",chhDeleteSelected)
on("chhClearBtn",chhClearPrompt)
// The toolbar wraps onto a second row when the page is narrow (terminal or AI panel docked): the panel keeps a fixed
// height (see chains.css on WebKitGTK repaints) that is recomputed from the toolbar's real height instead of 56px.
const bar=document.querySelector('.page[data-page="chains"] .chains-toolbar')
if(bar&&typeof ResizeObserver==="function")new ResizeObserver(chhFitHeight).observe(bar)
document.addEventListener("loya:ai-data-changed",(e)=>{if(chhState.shown&&e.detail&&e.detail.kind==="chains")chhReload()})
document.addEventListener("loya:page-shown",(e)=>{if(chhState.shown&&e.detail&&e.detail.page==="chains"&&!e.detail.first)chhReload()})
}
function chhFitHeight(){
const host=chhHost()
const bar=document.querySelector('.page[data-page="chains"] .chains-toolbar')
if(!host||!bar||!chhState.shown)return
const h=bar.offsetHeight
const want=h>0?"calc(100% - "+(h+14)+"px)":""
if(host.style.height!==want)host.style.height=want
}
function chhReload(){
chhLoadFacets()
if(chhState.view==="detail"&&chhState.detailId)chhOpenRun(chhState.detailId,true)
else chhLoad()
}
function chhShow(opts){
chhMount()
const o=opts||{}
chhState.shown=true
chhFitHeight()
if(o.playbookId!==undefined&&o.playbookId!==null){chhState.filters.chain="id:"+o.playbookId;chhState.offset=0;chhState.selected.clear();chhSetView("list")}
chhLoadFacets()
if(chhState.view==="detail"&&chhState.detailId&&!o.playbookId)chhOpenRun(chhState.detailId,true)
else chhLoad()
}
function chhHide(){
chhState.shown=false
if(chhState.timer){clearTimeout(chhState.timer);chhState.timer=null}
}
function chhSetView(view){
chhState.view=view
const host=chhHost()
if(!host)return
host.querySelector(".chh-list-view").classList.toggle("hidden",view!=="list")
host.querySelector(".chh-detail-view").classList.toggle("hidden",view!=="detail")
}
function chhLoadFacets(){
return chhBridge("chainHistory.facets").then((f)=>{
chhState.facets=f||{}
chhPaintChainSelect()
}).catch(()=>{})
}
function chhPaintChainSelect(){
const host=chhHost()
const sel=host&&host.querySelector('[data-chh="chain"]')
if(!sel)return
const f=chhState.facets||{}
const seen={}
const rows=[["","All chains"]]
;(f.chains||[]).forEach((c)=>{
const key=c.playbook_id!==null&&c.playbook_id!==undefined?"id:"+c.playbook_id:"name:"+c.name
seen[key]=1
rows.push([key,(c.name||"(unnamed)")+" ("+c.count+")"+(c.exists?"":" - deleted")])
})
;(f.all_chains||[]).forEach((c)=>{const key="id:"+c.playbook_id;if(!seen[key])rows.push([key,c.name+" (0)"])})
const want=chhState.filters.chain
if(want&&!rows.some((r)=>r[0]===want))rows.push([want,"This chain (0)"])
sel.innerHTML=chhOptions(rows,want)
sel.value=want
}
function chhLoad(){
const token=++chhState.token
if(chhState.timer){clearTimeout(chhState.timer);chhState.timer=null}
const body=chhHost()&&chhHost().querySelector(".chh-body")
if(body&&!chhState.items.length)body.innerHTML='<div class="chh-empty">Loading the run history...</div>'
chhSyncFilterUi()
return chhBridge("chainHistory.list",[chhQuery(chhState.filters,chhState.offset)]).then((page)=>{
if(token!==chhState.token)return
const p=page||{}
chhState.items=Array.isArray(p.items)?p.items:[]
chhState.total=Number(p.total)||0
chhRenderRows()
if(chhState.shown&&chhState.items.some((r)=>r.live))chhState.timer=setTimeout(()=>{if(chhState.shown&&chhState.view==="list")chhLoad()},CHH_POLL_MS)
}).catch((err)=>{
if(token!==chhState.token)return
if(body)body.innerHTML='<div class="chh-empty">'+chhEscape(chhErr(err,"Could not load the run history"))+"</div>"
})
}
function chhSyncFilterUi(){
const host=chhHost()
if(!host)return
const f=chhState.filters
host.querySelector(".chh-custom").classList.toggle("hidden",f.range!=="custom")
host.querySelector('[data-chh="reset"]').classList.toggle("hidden",!chhFiltered(f))
}
function chhRowHtml(r){
const checked=chhState.selected.has(r.run_id)
const kind=chhStateKind(r.state)
const name=r.current_name&&r.current_name!==r.chain_name?r.current_name:(r.chain_name||"(unnamed chain)")
return '<div class="chh-row chh-run-row'+(checked?" selected":"")+'" role="row" tabindex="0" data-run="'+chhEscape(r.run_id)+'" title="Open this run">'+
'<span class="chh-c-check" role="cell"><input type="checkbox" class="chh-check" data-chh="pick"'+(checked?" checked":"")+(r.live?' disabled title="Still running"':"")+' aria-label="Select this run"></span>'+
'<span class="chh-c-chain" role="cell"><span class="chh-chain-name">'+chhEscape(name)+"</span>"+(r.mode==="dry"?'<span class="chh-tag">dry run</span>':"")+(r.imported?'<span class="chh-tag">imported</span>':"")+(!r.chain_exists?'<span class="chh-tag chh-tag-muted" title="The chain was deleted or is not in this install">no chain</span>':"")+"</span>"+
'<span role="cell" class="chh-c-time" title="'+chhEscape(r.started_at)+'">'+chhEscape(chhTime(r.started_at))+"</span>"+
'<span role="cell" class="chh-c-dur">'+chhEscape(r.live?"running":chhDuration(r.duration_ms)||"-")+"</span>"+
'<span role="cell"><span class="chh-pill chh-'+kind+'"'+(r.reason?' title="'+chhEscape(r.reason)+'"':"")+">"+chhEscape(chhStateLabel(r.state))+"</span></span>"+
'<span role="cell" class="chh-c-nodes'+((r.nodes&&r.nodes.fail)?" chh-bad-text":"")+'">'+chhEscape(chhNodesText(r.nodes))+"</span>"+
'<span role="cell" class="chh-c-trigger">'+chhEscape(chhTriggerLabel(r.source,r.imported))+"</span>"+
'<span role="cell" class="chh-c-target" title="'+chhEscape(r.target)+'">'+chhEscape(r.target||"-")+"</span></div>"
}
function chhRenderRows(){
const host=chhHost()
if(!host)return
const body=host.querySelector(".chh-body")
const items=chhState.items
if(!items.length){
const filtered=chhFiltered(chhState.filters)
body.innerHTML='<div class="chh-empty">'+(filtered?"No runs match these filters.":"No chain has run yet. Runs show up here with their status, duration and log.")+"</div>"
}else body.innerHTML=items.map(chhRowHtml).join("")
const count=document.getElementById("chhCount")
if(count)count.textContent=chhState.total?chhState.total+" run"+(chhState.total===1?"":"s"):""
const start=chhState.total?chhState.offset+1:0,end=Math.min(chhState.total,chhState.offset+items.length)
host.querySelector(".chh-page-info").textContent=chhState.total>CHH_PAGE?start+"-"+end+" of "+chhState.total:""
host.querySelector('[data-chh="prev"]').disabled=chhState.offset<=0
host.querySelector('[data-chh="next"]').disabled=chhState.offset+CHH_PAGE>=chhState.total
host.querySelector(".chh-pager").classList.toggle("hidden",chhState.total<=CHH_PAGE)
chhPaintSelection()
}
function chhPaintSelection(){
const host=chhHost()
if(!host)return
const pickable=chhState.items.filter((r)=>!r.live)
const n=chhState.selected.size
const all=host.querySelector('[data-chh="all"]')
const onPage=pickable.filter((r)=>chhState.selected.has(r.run_id)).length
all.checked=!!pickable.length&&onPage===pickable.length
all.indeterminate=onPage>0&&onPage<pickable.length
all.disabled=!pickable.length
host.querySelector(".chh-sel-info").textContent=n?n+" selected":""
const del=document.getElementById("chhDeleteBtn")
if(del){del.disabled=!n;del.querySelector("span").textContent=n?"Delete ("+n+")":"Delete"}
const clear=document.getElementById("chhClearBtn")
if(clear)clear.disabled=!chhState.total&&!chhState.filters.chain
}
function chhOnChange(e){
const el=e.target
const what=el.dataset&&el.dataset.chh
if(!what)return
const f=chhState.filters
if(what==="pick"){
const row=el.closest(".chh-run-row")
if(!row)return
if(el.checked)chhState.selected.add(row.dataset.run);else chhState.selected.delete(row.dataset.run)
row.classList.toggle("selected",el.checked)
chhPaintSelection()
return
}
if(what==="all"){
chhState.items.filter((r)=>!r.live).forEach((r)=>{if(el.checked)chhState.selected.add(r.run_id);else chhState.selected.delete(r.run_id)})
chhRenderRows()
return
}
if(what==="chain"||what==="state"||what==="trigger"||what==="range"||what==="from"||what==="to"){
f[what]=el.value
chhState.offset=0
chhState.selected.clear()   // a selection never reaches runs the new filter hides
if(what==="range"&&el.value==="custom"){chhSyncFilterUi();const from=chhHost().querySelector('[data-chh="from"]');if(from)setTimeout(()=>from.focus(),0);return}
chhLoad()
}
}
function chhOnClick(e){
const btn=e.target.closest&&e.target.closest("[data-chh]")
const what=btn?btn.dataset.chh:""
if(what==="prev"){chhState.offset=Math.max(0,chhState.offset-CHH_PAGE);chhLoad();return}
if(what==="next"){chhState.offset+=CHH_PAGE;chhLoad();return}
if(what==="reset"){
chhState.filters={query:"",chain:"",state:"",trigger:"",range:"",from:"",to:""}
chhState.selected.clear()
const host=chhHost()
host.querySelectorAll("select.chh-select").forEach((s)=>{s.value=""})
host.querySelectorAll("input.chh-date").forEach((i)=>{i.value=""})
const search=document.getElementById("chhSearchInput")
if(search)search.value=""
chhState.offset=0
chhLoad()
return
}
if(what&&what.indexOf("d-")===0){chhDetailAction(what.slice(2),btn);return}
if(what==="pick"||what==="all"||e.target.closest(".chh-c-check"))return
const row=e.target.closest&&e.target.closest(".chh-run-row")
if(row)chhOpenRun(row.dataset.run)
}
// ---- run view
function chhOpenRun(runId,quiet){
if(!runId)return Promise.resolve()
chhState.detailId=String(runId)
if(chhState.timer){clearTimeout(chhState.timer);chhState.timer=null}
const host=chhHost()
const view=host.querySelector(".chh-detail-view")
if(!quiet||chhState.view!=="detail")view.innerHTML='<div class="chh-empty">Loading the run...</div>'
chhSetView("detail")
const token=++chhState.token
return chhBridge("chainHistory.detail",[runId]).then((d)=>{
if(token!==chhState.token)return
chhState.detail=d||{}
chhRenderDetail()
if(chhState.shown&&chhState.detail.live)chhState.timer=setTimeout(()=>{if(chhState.shown&&chhState.view==="detail"&&chhState.detailId===String(runId))chhOpenRun(runId,true)},CHH_POLL_MS)
}).catch((err)=>{
if(token!==chhState.token)return
view.innerHTML='<div class="chh-detail-head"><button type="button" class="cmds-playbook-back" data-chh="d-back"><i class="icon icon-arrow-left"></i><span>All runs</span></button></div><div class="chh-empty">'+chhEscape(chhErr(err,"Could not open the run"))+"</div>"
})
}
function chhFact(label,value,cls){return '<div class="chh-fact'+(cls?" "+cls:"")+'"><span class="chh-fact-label">'+chhEscape(label)+'</span><span class="chh-fact-value">'+value+"</span></div>"}
function chhRenderDetail(){
const d=chhState.detail||{}
const view=chhHost().querySelector(".chh-detail-view")
const open=new Set(Array.from(view.querySelectorAll(".chh-node[open]")).map((el)=>el.dataset.node))
const name=d.current_name||d.chain_name||"(unnamed chain)"
const kind=chhStateKind(d.state)
const c=d.nodes||{}
const bars=chhTimelineBars(d.timeline,d.started_at,d.ended_at)
let h='<div class="chh-detail-head"><button type="button" class="cmds-playbook-back" data-chh="d-back"><i class="icon icon-arrow-left"></i><span>All runs</span></button>'+
'<h3 title="'+chhEscape(name)+'">'+chhEscape(name)+'</h3><span class="chh-pill chh-'+kind+'">'+chhEscape(chhStateLabel(d.state))+"</span>"+
'<div class="chh-detail-actions"><button type="button" class="chains-tool-btn" data-chh="d-log" title="The full log: search, level and node filters, copy and export"><i class="icon icon-list"></i><span>Open log</span></button>'+
(d.chain_exists?'<button type="button" class="chains-tool-btn" data-chh="d-chain" title="Open the chain this run belongs to"><i class="icon icon-chain"></i><span>Open chain</span></button>':"")+
'<button type="button" class="chains-tool-btn" data-chh="d-export" title="Save this run (with its log) as a bundle file"><i class="icon icon-copy"></i><span>Export</span></button>'+
'<button type="button" class="chains-tool-btn chh-danger-btn" data-chh="d-delete"'+(d.live?' disabled title="Stop the run first"':' title="Delete this run and its log"')+'><i class="icon icon-trash"></i><span>Delete</span></button></div></div>'
h+='<div class="chh-facts">'+
chhFact("Started",chhEscape(chhTime(d.started_at)||"-"))+
chhFact("Ended",chhEscape(d.live?"still running":chhTime(d.ended_at)||"-"))+
chhFact("Duration",chhEscape(d.live?"running":chhDuration(d.duration_ms)||"-"))+
chhFact("Trigger",chhEscape(chhTriggerLabel(d.source,!!d.imported)))+
chhFact("Target",chhEscape(d.target||"-"))+
chhFact("Mode",chhEscape(d.mode==="dry"?"Dry run":"Real run"))+
chhFact("Nodes",chhEscape(chhNodesText(c)))+
chhFact("Run id",'<code>'+chhEscape(d.run_id)+"</code>")+
(d.reason?chhFact("Reason",chhEscape(d.reason),"chh-fact-wide"+(kind==="bad"?" chh-bad-text":"")):"")+
(d.imported?chhFact("Imported",chhEscape(chhTime(d.imported.at)+(d.imported.by?" by "+d.imported.by:"")),"chh-fact-wide"):"")+
(d.truncated?chhFact("Note","This run's stored output was shortened to fit the history.","chh-fact-wide"):"")+
(!d.chain_exists?chhFact("Chain","This run's chain was deleted or is not in this install.","chh-fact-wide"):"")+
"</div>"
if(bars.length)h+='<div class="chh-section-title">Timeline</div><div class="chh-gantt" role="img" aria-label="When each node ran">'+bars.map((b)=>'<div class="chh-gantt-row"><span class="chh-gantt-label" title="'+chhEscape(b.title)+'">'+chhEscape(b.title)+'</span><span class="chh-gantt-track"><span class="chh-gantt-bar chh-'+b.kind+'" style="left:'+b.left+"%;width:"+b.width+'%"></span></span></div>').join("")+"</div>"
const nodes=Array.isArray(d.timeline)?d.timeline:[]
h+='<div class="chh-section-title">Nodes <span class="chh-dim">('+nodes.length+")</span></div>"
h+=nodes.length?'<div class="chh-nodes">'+nodes.map((n)=>{
const nk=chhNodeStateKind(n.state)
const meta=[n.type,n.visits>1?n.visits+" visits":"",n.branch?"branch "+n.branch:"",n.exit_code!==null&&n.exit_code!==undefined?"exit "+n.exit_code:"",n.started_at&&n.duration_ms!==undefined?chhDuration(n.duration_ms):""].filter(Boolean).join(" - ")
const hasBody=n.error||n.stdout||n.stderr||(n.resolved&&n.resolved.length)
return '<details class="chh-node chh-node-'+nk+'" data-node="'+chhEscape(n.node)+'"'+(open.has(n.node)?" open":"")+'><summary><span class="chh-pill chh-'+nk+'">'+chhEscape(n.state||"pending")+'</span><span class="chh-node-title">'+chhEscape(n.title)+'</span><span class="chh-node-meta">'+chhEscape(meta)+"</span>"+(n.started_at?'<span class="chh-node-time">'+chhEscape(chhTime(n.started_at).slice(11))+"</span>":"")+"</summary>"+
(hasBody?'<div class="chh-node-body">'+(n.error?'<div class="chh-node-error">'+chhEscape(n.error)+"</div>":"")+
(n.resolved&&n.resolved.length?'<div class="chh-out-label">Commands</div><pre class="chh-pre">'+chhEscape(n.resolved.join("\n"))+"</pre>":"")+
(n.stdout?'<div class="chh-out-label">Output (last part)</div><pre class="chh-pre">'+chhEscape(n.stdout)+"</pre>":"")+
(n.stderr?'<div class="chh-out-label chh-bad-text">Errors (last part)</div><pre class="chh-pre chh-pre-err">'+chhEscape(n.stderr)+"</pre>":"")+"</div>":'<div class="chh-node-body chh-dim">'+(n.started_at?"No output.":"This node did not run.")+"</div>")+"</details>"
}).join("")+"</div>":'<div class="chh-empty">This run has no node results.</div>'
view.innerHTML=h
}
function chhDetailAction(what){
const d=chhState.detail||{}
if(what==="back"){chhState.detailId=null;chhState.detail=null;chhSetView("list");chhLoad();return}
if(what==="log"){
const titles={}
;(d.timeline||[]).forEach((n)=>{titles[n.node]={title:n.title}})
if(typeof flowLogOpen==="function")flowLogOpen({runId:d.run_id,name:d.current_name||d.chain_name,titles:titles,live:!!d.live})
else chhToast("The log viewer is not available","error")
return
}
if(what==="chain"){
if(typeof chainsSetTab==="function")chainsSetTab("chains")
if(typeof chainsOpenChain==="function")chainsOpenChain(d.playbook_id)
return
}
if(what==="export"){chhExport({runs:[d.run_id]});return}
if(what==="delete"){
appConfirm("Delete this run?",{okLabel:"Delete",danger:true,bodyHtml:"<div>The run of <b>"+chhEscape(d.current_name||d.chain_name||"this chain")+"</b> from "+chhEscape(chhTime(d.started_at))+" and its whole log are deleted. This cannot be undone.</div>"}).then((ok)=>{
if(!ok)return
chhBridge("chainHistory.delete",[[d.run_id]]).then((res)=>{
if(res&&res.skipped&&res.skipped.length){chhToast("The run is still going: stop it first","error");return}
chhState.selected.delete(d.run_id)
chhToast("Run deleted")
chhDetailAction("back")
chhLoadFacets()
}).catch((err)=>chhToast(chhErr(err,"Could not delete the run"),"error"))
})
}
}
// ---- deleting
function chhDeleteSelected(){
const ids=Array.from(chhState.selected)
if(!ids.length)return
appConfirm("Delete "+ids.length+" run"+(ids.length===1?"":"s")+"?",{okLabel:"Delete",danger:true,bodyHtml:"<div>The selected run"+(ids.length===1?"":"s")+" and "+(ids.length===1?"its":"their")+" logs are deleted from the history. This cannot be undone. Runs that are still going are kept.</div>"}).then((ok)=>{
if(!ok)return
chhBridge("chainHistory.delete",[ids]).then((res)=>{
const r=res||{}
ids.forEach((id)=>{if(!(r.skipped||[]).includes(id))chhState.selected.delete(id)})
chhToast((r.deleted||0)+" run"+(r.deleted===1?"":"s")+" deleted"+(r.skipped&&r.skipped.length?", "+r.skipped.length+" still running kept":""))
chhLoadFacets()
chhLoad()
}).catch((err)=>chhToast(chhErr(err,"Could not delete the runs"),"error"))
})
}
function chhChainLabel(key){
const f=chhState.facets||{}
const hit=(f.chains||[]).find((c)=>(c.playbook_id!==null&&c.playbook_id!==undefined?"id:"+c.playbook_id:"name:"+c.name)===key)||(f.all_chains||[]).find((c)=>"id:"+c.playbook_id===key)
return hit?hit.name:key.replace(/^(id|name):/,"")
}
function chhClearPrompt(){
const key=chhState.filters.chain
const total=(chhState.facets&&chhState.facets.total)||chhState.total
const scoped=!!key
const label=scoped?chhChainLabel(key):""
appConfirm(scoped?"Clear the run history of \""+label+"\"?":"Clear the whole run history?",{okLabel:scoped?"Clear this chain's runs":"Clear all runs",danger:true,wide:true,
bodyHtml:"<div>"+(scoped?"Every finished run of <b>"+chhEscape(label)+"</b> and its log is deleted.":"Every finished run of every chain ("+Number(total||0)+" in all) and its log is deleted.")+" This cannot be undone; export the history first if you may need it. Runs that are still going are kept.</div>"+(scoped?"":'<div class="chh-dim">To clear one chain only, pick it in the chain filter first.</div>')}).then((ok)=>{
if(!ok)return
const args=scoped?(/^id:/.test(key)?[Number(key.slice(3)),null]:[null,key.slice(5)]):[null,null]
chhBridge("chainHistory.clear",args).then((res)=>{
chhState.selected.clear()
chhToast(((res&&res.deleted)||0)+" run"+(res&&res.deleted===1?"":"s")+" deleted")
chhLoadFacets()
chhState.offset=0
chhLoad()
}).catch((err)=>chhToast(chhErr(err,"Could not clear the history"),"error"))
})
}
// ---- export
function chhExport(spec){
return chhBridge("chainHistory.export_file",[spec]).then((res)=>{
if(res&&res.ok&&res.path)chhToast("Saved "+(res.chains?res.chains+" chain"+(res.chains===1?"":"s"):"")+(res.chains&&res.runs?" and ":"")+(res.runs?res.runs+" run"+(res.runs===1?"":"s"):"")+" to "+res.path)
}).catch((err)=>chhToast(chhErr(err,"Could not export"),"error"))
}
function chhExportRunsPrompt(){
const ids=Array.from(chhState.selected)
const key=chhState.filters.chain
const choices=[]
if(ids.length)choices.push(["selected","The "+ids.length+" selected run"+(ids.length===1?"":"s")])
if(key&&/^id:/.test(key))choices.push(["chain","Every run of \""+chhChainLabel(key)+"\""])
choices.push(["all","The whole run history"])
const body='<div class="chh-preview-opt">'+choices.map((c,i)=>'<label><input type="radio" name="chhExportWhat" value="'+c[0]+'"'+(i===0?" checked":"")+"> "+chhEscape(c[1])+"</label>").join("")+'</div><div class="chh-preview-opt"><label><input type="checkbox" class="chh-exp-logs" checked> Include the logs</label><label><input type="checkbox" class="chh-exp-chains"> Include the chains themselves</label></div><div class="chh-note">The file is plain JSON: command output in it is not encrypted. Keep it as safe as the engagement data.</div>'
const pick={what:choices[0][0],logs:true,chains:false}
const ask=appConfirm("Export run history",{okLabel:"Export...",wide:true,bodyHtml:body})
chhWatchDialog((box)=>{
box.querySelectorAll('input[name="chhExportWhat"]').forEach((r)=>r.addEventListener("change",()=>{if(r.checked)pick.what=r.value}))
box.querySelector(".chh-exp-logs").addEventListener("change",(e)=>{pick.logs=e.target.checked})
box.querySelector(".chh-exp-chains").addEventListener("change",(e)=>{pick.chains=e.target.checked})
})
ask.then((ok)=>{
if(!ok)return
const spec={include_logs:pick.logs}
if(pick.what==="selected"){spec.runs=ids;if(pick.chains){const own=Array.from(new Set(chhState.items.filter((r)=>chhState.selected.has(r.run_id)&&r.chain_exists).map((r)=>r.playbook_id)));if(own.length)spec.chains=own}}
else if(pick.what==="chain"){spec.runs_of_chain=Number(key.slice(3));if(pick.chains)spec.chains=[Number(key.slice(3))]}
else{spec.runs="all";if(pick.chains)spec.chains="all"}
chhExport(spec)
})
}
// The dialog appConfirm just opened (it is in the DOM synchronously), for wiring its inputs.
function chhWatchDialog(fn){
const boxes=document.querySelectorAll(".confirm-overlay .confirm-box")
const box=boxes[boxes.length-1]
if(box)fn(box)
}
// Chains tab "Export": one, several or all chains, optionally with their run history.
function chhExportChainsPrompt(){
return chhBridge("chainHistory.facets").then((f)=>{
const chains=(f&&f.all_chains)||[]
if(!chains.length){chhToast("There are no chains to export yet","error");return}
const counts={}
;((f&&f.chains)||[]).forEach((c)=>{if(c.playbook_id!==null&&c.playbook_id!==undefined)counts[c.playbook_id]=c.count})
const preselect=typeof chainsState!=="undefined"&&chainsState.currentId!=null?String(chainsState.currentId):""
const body='<div class="chh-pick-head"><label><input type="checkbox" class="chh-pick-all"'+(preselect?"":" checked")+'> All chains ('+chains.length+')</label><span class="chh-pick-count"></span></div><div class="chh-pick-list">'+
chains.map((c)=>'<label class="chh-pick-row"><input type="checkbox" class="chh-pick" value="'+chhEscape(c.playbook_id)+'"'+(!preselect||String(c.playbook_id)===preselect?" checked":"")+'><span class="chh-pick-name">'+chhEscape(c.name)+'</span><span class="chh-dim">'+(counts[c.playbook_id]?counts[c.playbook_id]+" run"+(counts[c.playbook_id]===1?"":"s"):"no runs")+"</span></label>").join("")+
'</div><div class="chh-preview-opt"><label><input type="checkbox" class="chh-exp-runs"> Include their run history</label><label><input type="checkbox" class="chh-exp-logs" checked> With the logs</label></div><div class="chh-note">Linear chains are exported as diagrams. Whoever imports the file has to review each chain before it runs.</div>'
const state={ids:new Set(chains.filter((c)=>!preselect||String(c.playbook_id)===preselect).map((c)=>String(c.playbook_id))),runs:false,logs:true}
const ask=appConfirm("Export chains",{okLabel:"Export...",wide:true,bodyHtml:body})
chhWatchDialog((box)=>{
const ok=box.querySelector(".confirm-ok"),all=box.querySelector(".chh-pick-all"),info=box.querySelector(".chh-pick-count")
const sync=()=>{const n=state.ids.size;ok.disabled=!n;ok.textContent=n?"Export "+n+" chain"+(n===1?"":"s")+"...":"Export...";all.checked=n===chains.length;all.indeterminate=n>0&&n<chains.length;info.textContent=n+" of "+chains.length+" selected"}
box.querySelectorAll(".chh-pick").forEach((cb)=>cb.addEventListener("change",()=>{if(cb.checked)state.ids.add(cb.value);else state.ids.delete(cb.value);sync()}))
all.addEventListener("change",()=>{box.querySelectorAll(".chh-pick").forEach((cb)=>{cb.checked=all.checked;if(all.checked)state.ids.add(cb.value);else state.ids.delete(cb.value)});sync()})
box.querySelector(".chh-exp-runs").addEventListener("change",(e)=>{state.runs=e.target.checked})
box.querySelector(".chh-exp-logs").addEventListener("change",(e)=>{state.logs=e.target.checked})
sync()
})
return ask.then((ok)=>{
if(!ok||!state.ids.size)return
const every=state.ids.size===chains.length
const ids=Array.from(state.ids).map(Number)
const spec={chains:every?"all":ids,include_logs:state.logs}
if(state.runs){if(every)spec.runs="all";else spec.runs_of_chain=ids}
return chhExport(spec)
})
}).catch((err)=>chhToast(chhErr(err,"Could not list the chains"),"error"))
}
// ---- import (both tabs)
function chhImport(){
return chhBridge("chainHistory.import_pick",[]).then((p)=>{
if(!p||p.ok===false)return
const nothing=!(p.chains&&p.chains.length)&&!(p.runs&&p.runs.length)
if(nothing){
chhBridge("chainHistory.import_cancel",[p.token]).catch(()=>{})
appConfirm("Nothing to import",{okLabel:"OK",bodyHtml:chhPreviewHtml(p,p.name)})
return
}
const opts={chains:"rename",runs:"skip",import_chains:true,import_runs:true}
const ask=appConfirm("Import from this file?",{okLabel:"Import",wide:true,bodyHtml:chhPreviewHtml(p,p.name)})
chhWatchDialog((box)=>{
box.querySelectorAll('input[name="chhChainMode"]').forEach((r)=>r.addEventListener("change",()=>{if(r.checked)opts.chains=r.value}))
box.querySelectorAll('input[name="chhRunMode"]').forEach((r)=>r.addEventListener("change",()=>{if(r.checked)opts.runs=r.value}))
const ic=box.querySelector(".chh-imp-chains"),ir=box.querySelector(".chh-imp-runs"),ok=box.querySelector(".confirm-ok")
const sync=()=>{ok.disabled=!opts.import_chains&&!opts.import_runs}
if(ic)ic.addEventListener("change",()=>{opts.import_chains=ic.checked;sync()})
if(ir)ir.addEventListener("change",()=>{opts.import_runs=ir.checked;sync()})
})
return ask.then((ok)=>{
if(!ok){chhBridge("chainHistory.import_cancel",[p.token]).catch(()=>{});return}
return chhBridge("chainHistory.import_apply",[p.token,opts]).then((res)=>{
const r=res||{}
chhToast(chhResultText(r),(r.problems&&r.problems.length)||(!(r.chains&&r.chains.created&&r.chains.created.length)&&!(r.runs&&r.runs.imported)&&!(r.chains&&r.chains.replaced&&r.chains.replaced.length))?"error":undefined)
const notes=(r.warnings||[]).map((w)=>w.message).filter(Boolean)
if(notes.length)appConfirm("Imported - review before running",{okLabel:"OK",wide:true,bodyHtml:'<ul class="chh-preview-list">'+notes.slice(0,12).map((m)=>"<li>"+chhEscape(m)+"</li>").join("")+(notes.length>12?"<li>and "+(notes.length-12)+" more</li>":"")+"</ul>"})
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
if(typeof chainsFlowRefreshIndex==="function")Promise.resolve(chainsFlowRefreshIndex()).catch(()=>{})
if(typeof chainsRefreshList==="function"&&!chhState.shown)chainsRefreshList()
if(chhState.mounted){chhLoadFacets();if(chhState.shown)chhLoad()}
})
})
}).catch((err)=>chhToast(chhErr(err,"Import failed"),"error"))
}
if(typeof module!=="undefined"&&module.exports)module.exports={CHH_PAGE,CHH_STATES,CHH_TRIGGERS,CHH_RANGES,chhEscape,chhDuration,chhStateLabel,chhStateKind,chhNodeStateKind,chhTriggerLabel,chhNodesText,chhTime,chhRangeBounds,chhQuery,chhFiltered,chhTimelineBars,chhPreviewHtml,chhResultText}
