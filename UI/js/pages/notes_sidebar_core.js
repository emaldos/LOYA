// Pure logic for the Notes sidebar (no DOM, no bridge): preferences, search, highlight, filters, sorting, grouping into sections, the flat
// item list the virtual scroller draws, and pinned reordering. Loaded by the app as a plain script (global NotesSidebar) and by
// tests/js/notes_sidebar.js through require().
const NotesSidebar=(function(){
const VIEWS=["groups","tags","recent","targets"]
const SORTS=["name","edited","created"]
const DIRS=["asc","desc"]
const DENSITIES=["comfortable","compact"]
const FILTERS=["pinned","findings","commands","untagged"]
const SCOPES=["name","tags","content"]
const SEVERITIES=["critical","high","medium","low","info"]
const ICONS=["folder","target","command-line","report","star","file","link","brain","search","list","home","info"]
const COLORS=["#f03e3e","#f76707","#f59f00","#37b24d","#0ca678","#1098ad","#1c7ed6","#7048e8","#ae3ec9","#d6336c","#868e96"]
const UNGROUPED="__ungrouped__"
const PINNED="__pinned__"
const RECENT="__recent__"
const HEIGHTS={comfortable:{head:30,row:48,empty:28},compact:{head:28,row:28,empty:24}}
const RECENT_SHOWN=5
const WIDTH_MIN=220,WIDTH_MAX=560,WIDTH_DEFAULT=280
const collator=typeof Intl!=="undefined"&&Intl.Collator?new Intl.Collator(undefined,{numeric:true,sensitivity:"base"}):null
function cmpText(a,b){
a=String(a||"");b=String(b||"")
return collator?collator.compare(a,b):a.toLowerCase()<b.toLowerCase()?-1:a.toLowerCase()>b.toLowerCase()?1:0
}
function norm(s){return String(s===undefined||s===null?"":s).trim().split(/\s+/).filter(Boolean).join(" ")}
function pick(v,allowed,fallback){
const s=String(v||"").toLowerCase()
return allowed.indexOf(s)>=0?s:fallback
}
function pickList(v,allowed){
const have=new Set((Array.isArray(v)?v:[]).map((x)=>String(x||"").toLowerCase()))
return allowed.filter((x)=>have.has(x))
}
function normHex(v){
const m=/^#?([0-9a-f]{6})$/i.exec(String(v||"").trim())
return m?"#"+m[1].toLowerCase():""
}
function clampWidth(v,min,max){
const n=Math.round(Number(v))
return Math.max(min||WIDTH_MIN,Math.min(max||WIDTH_MAX,isFinite(n)&&n>0?n:WIDTH_DEFAULT))
}
function normPrefs(p){
p=p&&typeof p==="object"?p:{}
const styles={}
Object.keys(p.group_styles&&typeof p.group_styles==="object"?p.group_styles:{}).forEach((k)=>{
const st=p.group_styles[k]||{}
const color=normHex(st.color),icon=pick(st.icon,ICONS,"")
if(k&&(color||icon))styles[String(k).toLowerCase()]={color,icon}
})
const scopes=Array.isArray(p.scopes)?pickList(p.scopes,SCOPES):["name","tags"]
return {view:pick(p.view,VIEWS,"groups"),sort:pick(p.sort,SORTS,"name"),dir:pick(p.dir,DIRS,"asc"),density:pick(p.density,DENSITIES,"comfortable"),width:clampWidth(p.width,p.width_min,p.width_max),width_min:p.width_min||WIDTH_MIN,width_max:p.width_max||WIDTH_MAX,filters:pickList(p.filters,FILTERS),scopes:scopes.length?scopes:["name"],nested:p.nested!==false,show_recent:p.show_recent!==false,group_styles:styles}
}
function splitTags(s){
const out=[],seen=new Set()
String(s||"").split(",").forEach((t)=>{
const v=norm(t),k=v.toLowerCase()
if(v&&!seen.has(k)){seen.add(k);out.push(v)}
})
return out
}
function sevRank(s){
const i=SEVERITIES.indexOf(String(s||"").toLowerCase())
return i<0?SEVERITIES.length:i
}
function sevLabel(s){
const k=pick(s,SEVERITIES,"")
return k?k.charAt(0).toUpperCase()+k.slice(1):""
}
// ---- time
function relTime(ts,now){
ts=Number(ts)||0
if(!ts)return ""
const s=Math.max(0,Math.floor(((Number(now)||Date.now())-ts)/1000))
if(s<60)return "now"
if(s<3600)return Math.floor(s/60)+"m"
if(s<86400)return Math.floor(s/3600)+"h"
if(s<604800)return Math.floor(s/86400)+"d"
if(s<2629800)return Math.floor(s/604800)+"w"
if(s<31557600)return Math.floor(s/2629800)+"mo"
return Math.floor(s/31557600)+"y"
}
function relTimeLong(ts,now){
const r=relTime(ts,now)
if(!r)return ""
if(r==="now")return "just now"
const m=/^(\d+)(mo|[mhdwy])$/.exec(r)
const n=Number(m[1]),unit={m:"minute",h:"hour",d:"day",w:"week",mo:"month",y:"year"}[m[2]]
return n+" "+unit+(n===1?"":"s")+" ago"
}
const BUCKETS=[{key:"today",label:"Today"},{key:"yesterday",label:"Yesterday"},{key:"week",label:"Last 7 days"},{key:"month",label:"Last 30 days"},{key:"older",label:"Older"},{key:"unknown",label:"No date"}]
function dayBucket(ts,now){
ts=Number(ts)||0
if(!ts)return "unknown"
const d=new Date(Number(now)||Date.now())
const midnight=new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime()
if(ts>=midnight)return "today"
if(ts>=midnight-86400000)return "yesterday"
if(ts>=midnight-6*86400000)return "week"
if(ts>=midnight-29*86400000)return "month"
return "older"
}
// ---- search
function searchWords(q){
const out=[]
String(q||"").toLowerCase().split(/\s+/).forEach((w)=>{if(w&&out.indexOf(w)<0)out.push(w)})
return out.slice(0,8)
}
// A note matches when every word is found in the scopes that are on (name also covers the group). Content hits come from the backend
// as a set of ids for the whole query, so a content hit matches on its own.
function matchNote(n,words,scopes,contentIds){
if(!words||!words.length)return true
const sc=scopes&&scopes.length?scopes:["name"]
if(sc.indexOf("content")>=0&&contentIds&&contentIds.has(n.id))return true
let hay=""
if(sc.indexOf("name")>=0)hay+=String(n.note_name||"").toLowerCase()+"\n"+String(n.group_name||"").toLowerCase()+"\n"
if(sc.indexOf("tags")>=0)hay+=String(n.tags||"").toLowerCase()
if(!hay)return false
return words.every((w)=>hay.indexOf(w)>=0)
}
function matchRanges(text,words){
const low=String(text||"").toLowerCase()
const ranges=[]
;(words||[]).forEach((w)=>{
if(!w)return
let i=low.indexOf(w)
while(i>=0){ranges.push([i,i+w.length]);i=low.indexOf(w,i+w.length)}
})
ranges.sort((a,b)=>a[0]-b[0]||a[1]-b[1])
const out=[]
ranges.forEach((r)=>{
const last=out[out.length-1]
if(last&&r[0]<=last[1])last[1]=Math.max(last[1],r[1])
else out.push([r[0],r[1]])
})
return out
}
// Escaped HTML of text with every match wrapped in <mark>. esc must escape &, <, > and quotes; text is never inserted unescaped.
function highlight(text,words,esc){
const s=String(text===undefined||text===null?"":text)
// toLowerCase can change the length of a few characters; ranges would then point at the wrong place, so those names are not marked.
const ranges=s.toLowerCase().length===s.length?matchRanges(s,words):[]
if(!ranges.length)return esc(s)
let html="",at=0
ranges.forEach((r)=>{
html+=esc(s.slice(at,r[0]))+'<mark class="notes-hl">'+esc(s.slice(r[0],r[1]))+"</mark>"
at=r[1]
})
return html+esc(s.slice(at))
}
// ---- filters and sorting
function noteHas(n,filter){
if(filter==="pinned")return !!n.pinned
if(filter==="findings")return (Number(n.findings)||0)>0||!!n.sev
if(filter==="commands")return (Number(n.cmds)||0)>0
if(filter==="untagged")return splitTags(n.tags).length===0
return true
}
function filterNotes(notes,filters){
const on=pickList(filters,FILTERS)
if(!on.length)return notes.slice()
return notes.filter((n)=>on.every((f)=>noteHas(n,f)))
}
function filterCounts(notes){
const out={}
FILTERS.forEach((f)=>{out[f]=0})
notes.forEach((n)=>FILTERS.forEach((f)=>{if(noteHas(n,f))out[f]++}))
return out
}
function sortNotes(notes,sort,dir){
const s=pick(sort,SORTS,"name"),sign=pick(dir,DIRS,"asc")==="desc"?-1:1
const byName=(a,b)=>cmpText(a.note_name,b.note_name)||(a.id-b.id)
const field=s==="created"?"created_ts":"updated_ts"
return notes.map((n,i)=>[n,i]).sort((x,y)=>{
const a=x[0],b=y[0]
let c=s==="name"?byName(a,b):((Number(a[field])||0)-(Number(b[field])||0))
if(!c&&s!=="name")c=byName(a,b)*sign
return c*sign||x[1]-y[1]
}).map((x)=>x[0])
}
// ---- groups
function groupKey(name){
const k=norm(name).toLowerCase()
return !k||k===UNGROUPED?UNGROUPED:k
}
function pathParts(name){
return norm(name).split("/").map((p)=>norm(p)).filter(Boolean)
}
function groupNames(notes,declared){
const seen=new Map()
;(declared||[]).concat((notes||[]).map((n)=>n.group_name)).forEach((g)=>{
const v=norm(g)
if(v&&!seen.has(v.toLowerCase()))seen.set(v.toLowerCase(),v)
})
return Array.from(seen.values()).sort(cmpText)
}
// Tree of groups. With nesting on, "CTF/HTB" sits under "CTF"; a parent that is not a group itself is a virtual node (real:false).
function groupTree(names,nested){
const root={children:[],byKey:new Map()}
const node=(key,name,label,depth,parent)=>{
let n=root.byKey.get(key)
if(!n){
n={key,name,label,depth,real:false,children:[],rows:[],total:0}
root.byKey.set(key,n)
;(parent?parent.children:root.children).push(n)
}
return n
}
;(names||[]).forEach((full)=>{
const name=norm(full)
if(!name)return
const parts=nested?pathParts(name):[name]
if(parts.length<2){node(name.toLowerCase(),name,name,0,null).real=true;return}
let parent=null,path=""
parts.forEach((p,i)=>{
path=path?path+"/"+p:p
const last=i===parts.length-1
// The stored name of a nested group keeps its own spelling ("CTF / HTB"); ancestors use the normalised path.
parent=node(last?name.toLowerCase():path.toLowerCase(),last?name:path,p,i,parent)
if(last)parent.real=true
})
})
const sortRec=(list)=>{list.sort((a,b)=>cmpText(a.label,b.label));list.forEach((n)=>sortRec(n.children))}
sortRec(root.children)
return root
}
function treeTotals(list){
let sum=0
list.forEach((n)=>{n.total=n.rows.length+treeTotals(n.children);sum+=n.total})
return sum
}
// ---- sections
// state: {notes, groups (declared names), pinned (ids, in order), recent (ids), targets (names), prefs, search, contentIds (Set), draft, now}
// Returns {sections, matched, total, searching, filtering}. A section: {key, kind, label, title, depth, group, real, rows, count, children}.
function buildSections(state){
const prefs=normPrefs(state.prefs)
const all=state.notes||[]
const words=searchWords(state.search)
const searching=words.length>0
const filtering=prefs.filters.length>0
const base=filterNotes(all,prefs.filters).filter((n)=>matchNote(n,words,prefs.scopes,state.contentIds))
const sorted=sortNotes(base,prefs.sort,prefs.dir)
const byId=new Map(sorted.map((n)=>[n.id,n]))
const sections=[]
const sec=(key,kind,label,rows,extra)=>Object.assign({key,kind,label,title:label,depth:0,group:null,real:false,rows,count:rows.length,children:[]},extra||{})
if(state.draft)sections.push(sec("__draft__","draft","Draft",[],{draft:state.draft,count:1}))
if(prefs.view==="groups"){
const pinned=(state.pinned||[]).map((id)=>byId.get(id)).filter(Boolean)
if(pinned.length)sections.push(sec(PINNED,"pinned","Pinned",pinned))
if(prefs.show_recent&&!searching&&!filtering){
const recent=(state.recent||[]).map((id)=>byId.get(id)).filter(Boolean).slice(0,RECENT_SHOWN)
if(recent.length)sections.push(sec(RECENT,"recent","Recently opened",recent))
}
const ungrouped=sorted.filter((n)=>!norm(n.group_name))
if(ungrouped.length)sections.push(sec(UNGROUPED,"group","Ungrouped",ungrouped,{group:""}))
const tree=groupTree(groupNames(all,state.groups),prefs.nested)
sorted.forEach((n)=>{
const g=norm(n.group_name)
if(!g)return
const node=tree.byKey.get(g.toLowerCase())
if(node)node.rows.push(n)
})
treeTotals(tree.children)
const conv=(n)=>sec(n.key,"group",n.label,n.rows,{title:n.name,depth:n.depth,group:n.name,real:n.real,count:n.total,children:n.children.filter((c)=>c.total>0||!(searching||filtering)).map(conv)})
tree.children.forEach((n)=>{if(n.total>0||!(searching||filtering))sections.push(conv(n))})
}else if(prefs.view==="tags"){
const byTag=new Map(),untagged=[]
sorted.forEach((n)=>{
const tags=splitTags(n.tags)
if(!tags.length){untagged.push(n);return}
tags.forEach((t)=>{
const k=t.toLowerCase()
if(!byTag.has(k))byTag.set(k,{label:t,from:n.id,rows:[]})
const e=byTag.get(k)
// One spelling per tag ("Web" / "web"): the oldest note's, so the label does not change with the sort order.
if(n.id<e.from){e.from=n.id;e.label=t}
e.rows.push(n)
})
})
Array.from(byTag.keys()).sort((a,b)=>cmpText(byTag.get(a).label,byTag.get(b).label)).forEach((k)=>sections.push(sec("tag:"+k,"tag",byTag.get(k).label,byTag.get(k).rows,{tag:byTag.get(k).label})))
if(untagged.length)sections.push(sec("tag:","tag","Untagged",untagged,{tag:""}))
}else if(prefs.view==="recent"){
const field=prefs.sort==="created"?"created_ts":"updated_ts"
const rows=prefs.sort==="name"?sortNotes(base,"edited","desc"):sorted
const by={}
rows.forEach((n)=>{const b=dayBucket(n[field],state.now);(by[b]=by[b]||[]).push(n)})
const order=prefs.sort!=="name"&&prefs.dir==="asc"?BUCKETS.slice(0,5).reverse().concat(BUCKETS.slice(5)):BUCKETS
order.forEach((b)=>{if(by[b.key])sections.push(sec("when:"+b.key,"bucket",b.label,by[b.key]))})
}else{
const names=state.targets||[]
const by=new Map(names.map((t)=>[t,[]])),none=[]
sorted.forEach((n)=>{
const hits=(n.targets||[]).filter((t)=>by.has(t))
if(!hits.length){none.push(n);return}
hits.forEach((t)=>by.get(t).push(n))
})
names.forEach((t)=>{if(by.get(t).length)sections.push(sec("target:"+t.toLowerCase(),"target",t,by.get(t)))})
if(none.length)sections.push(sec("target:","target",names.length?"No target":"All notes",none))
}
return {sections,matched:base.length,total:all.length,searching,filtering,words,prefs}
}
// Flat list for the virtual scroller. collapsed: {key:true}. While searching, every section is open so no match hides in a closed group.
function flatten(sections,collapsed,forceOpen){
const items=[]
const walk=(s,depth)=>{
const closed=!forceOpen&&!!(collapsed&&collapsed[s.key])
items.push({type:"head",key:s.key,kind:s.kind,label:s.label,title:s.title,depth,count:s.count,collapsed:closed,group:s.group,real:s.real,hasChildren:s.children.length>0,tag:s.tag})
if(closed)return
if(s.kind==="draft"){items.push({type:"draft",section:s.key,kind:s.kind,depth:depth+1,draft:s.draft});return}
s.rows.forEach((n)=>items.push({type:"row",note:n,section:s.key,kind:s.kind,depth:depth+1}))
s.children.forEach((c)=>walk(c,depth+1))
if(!s.rows.length&&!s.children.length)items.push({type:"empty",section:s.key,kind:s.kind,depth:depth+1,text:"No notes"})
}
sections.forEach((s)=>walk(s,0))
return items
}
function layout(items,density){
const h=HEIGHTS[pick(density,DENSITIES,"comfortable")]
const tops=new Array(items.length)
let y=0
for(let i=0;i<items.length;i++){
const it=items[i]
// A little air above every top-level header except the first.
if(it.type==="head"&&it.depth===0&&i>0)y+=6
tops[i]=y
y+=it.type==="head"?h.head:it.type==="empty"?h.empty:h.row
}
return {tops,total:y,heights:h}
}
function itemHeight(item,heights){return item.type==="head"?heights.head:item.type==="empty"?heights.empty:heights.row}
// First and last item index to draw for a scroll position (binary search on the tops).
function windowRange(tops,total,scrollTop,viewHeight,overscan){
const n=tops.length
if(!n)return {start:0,end:-1}
const find=(y)=>{
let lo=0,hi=n-1
while(lo<hi){
const mid=(lo+hi+1)>>1
if(tops[mid]<=y)lo=mid;else hi=mid-1
}
return lo
}
const over=overscan===undefined?6:overscan
return {start:Math.max(0,find(Math.max(0,scrollTop))-over),end:Math.min(n-1,find(Math.max(0,scrollTop+Math.max(0,viewHeight)))+over)}
}
function rowIndex(items,noteId,preferSection){
let first=-1
for(let i=0;i<items.length;i++){
if(items[i].type!=="row"||items[i].note.id!==noteId)continue
if(preferSection===undefined||items[i].section===preferSection)return i
if(first<0)first=i
}
return first
}
// Section keys that must be open for a note to be visible (its own section and every ancestor).
function sectionPath(sections,noteId,skipKinds){
const skip=skipKinds||[]
let found=null
const walk=(s,trail)=>{
if(found||skip.indexOf(s.kind)>=0)return
const here=trail.concat(s.key)
if(s.rows.some((n)=>n.id===noteId)){found=here;return}
s.children.forEach((c)=>walk(c,here))
}
sections.forEach((s)=>walk(s,[]))
return found
}
function sectionKeys(sections){
const out=[]
const walk=(s)=>{out.push(s.key);s.children.forEach(walk)}
sections.forEach(walk)
return out
}
function firstStop(items){
for(let i=0;i<items.length;i++)if(items[i].type!=="empty")return i
return -1
}
// Move fromId next to toId in the pinned order (before it, or after it when after is true).
function reorder(ids,fromId,toId,after){
const list=(ids||[]).slice()
const from=list.indexOf(fromId)
if(from<0||fromId===toId||list.indexOf(toId)<0)return list
list.splice(from,1)
const to=list.indexOf(toId)
list.splice(after?to+1:to,0,fromId)
return list
}
function moveBy(ids,id,delta){
const list=(ids||[]).slice()
const i=list.indexOf(id),j=i+delta
if(i<0||j<0||j>=list.length)return list
list.splice(i,1);list.splice(j,0,id)
return list
}
// New name of a group after its ancestor (or itself) oldPath was renamed to newPath; "" when the group is not under oldPath.
function renamedPath(group,oldPath,newPath){
const g=pathParts(group),o=pathParts(oldPath)
if(!o.length||g.length<o.length)return ""
for(let i=0;i<o.length;i++)if(g[i].toLowerCase()!==o[i].toLowerCase())return ""
return pathParts(newPath).concat(g.slice(o.length)).join("/")
}
function countLabel(model){
const n=model.matched,t=model.total
if(model.searching)return n+(n===1?" match":" matches")
if(model.filtering)return n+" of "+t
return t+(t===1?" note":" notes")
}
return {VIEWS,SORTS,DIRS,DENSITIES,FILTERS,SCOPES,SEVERITIES,ICONS,COLORS,UNGROUPED,PINNED,RECENT,HEIGHTS,BUCKETS,cmpText,norm,normHex,clampWidth,normPrefs,splitTags,sevRank,sevLabel,relTime,relTimeLong,dayBucket,searchWords,matchNote,matchRanges,highlight,noteHas,filterNotes,filterCounts,sortNotes,groupKey,pathParts,groupNames,groupTree,buildSections,flatten,layout,itemHeight,windowRange,rowIndex,sectionPath,sectionKeys,firstStop,reorder,moveBy,renamedPath,countLabel}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=NotesSidebar
