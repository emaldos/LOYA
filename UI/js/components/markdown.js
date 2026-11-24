// Small Markdown -> blocks / HTML converter (no dependencies, no DOM). Used by the note editor (Markdown as you type, Markdown paste) and reusable by reports.
// Browser: global LoyaMarkdown. Node: require("./markdown.js").
//   LoyaMarkdown.toBlocks(md)          -> [{type:"heading",level,text}|{type:"paragraph",text}|{type:"code",lang,text}|{type:"list",ordered,start,items:[{text,checked,children}]}|{type:"quote",blocks}|{type:"table",head,rows,align}|{type:"hr"}]
//   LoyaMarkdown.toHtml(md,opts)       -> HTML string; every piece of text is escaped and links are limited to http/https/mailto/notelink. opts.noteClasses=false drops the note-* classes.
//   LoyaMarkdown.inline(text)          -> escaped inline HTML (code, bold, italic, strike, links)
//   LoyaMarkdown.looksLikeMarkdown(t)  -> true when a pasted text is clearly Markdown (fences, headings, lists, tables, links)
//   LoyaMarkdown.inlineTrigger(before) -> the span a just-typed closing marker completes: {type,start,raw,text,url} or null
//   LoyaMarkdown.tableRow(line) / tableSeparator(line) / safeUrl(url) / escape(text)
const LoyaMarkdown=(function(){
function escape(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function safeUrl(url){
const raw=String(url||"").trim()
const v=raw.replace(/[\u0000- \u007f-\u009f]+/g,"")
if(/^(?:https?:\/\/|mailto:|notelink:)/i.test(v)&&v.length<=2000)return v
return ""
}
function inline(text){
const stash=[]
const keep=(html)=>{stash.push(html);return "\u0001"+(stash.length-1)+"\u0001"}
let s=String(text===undefined||text===null?"":text).replace(/\u0001/g,"")
s=s.replace(/(`+)([^`\n]|[^`\n][^\n]*?[^`\n])\1(?!`)/g,(m,t,code)=>keep("<code>"+escape(code)+"</code>"))
s=s.replace(/!?\[([^\]\n]+)\]\(\s*([^)\s]+)(?:\s+"[^"\n]*")?\s*\)/g,(m,label,url)=>{
const u=safeUrl(url)
return u?keep('<a href="'+escape(u)+'">'+inlineEmphasis(escape(label))+"</a>"):m
})
s=s.replace(/<((?:https?:\/\/|mailto:)[^\s<>]+)>/gi,(m,url)=>{const u=safeUrl(url);return u?keep('<a href="'+escape(u)+'">'+escape(u)+"</a>"):m})
s=s.replace(/(^|[\s(])(https?:\/\/[^\s<>"'`]+[^\s<>"'`.,;:!?)\]])/gi,(m,pre,url)=>{const u=safeUrl(url);return u?pre+keep('<a href="'+escape(u)+'">'+escape(u)+"</a>"):m})
s=inlineEmphasis(escape(s))
return s.replace(/\u0001(\d+)\u0001/g,(m,i)=>stash[parseInt(i,10)]||"")
}
function inlineEmphasis(s){
return s
.replace(/\*\*([^\s*](?:[^*\n]*?[^\s*])?)\*\*/g,"<b>$1</b>")
.replace(/(^|[^\w_])__([^\s_](?:[^_\n]*?[^\s_])?)__(?![\w_])/g,"$1<b>$2</b>")
.replace(/(^|[^*\w])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?![*\w])/g,"$1<i>$2</i>")
.replace(/(^|[^\w_])_([^\s_](?:[^_\n]*?[^\s_])?)_(?![\w_])/g,"$1<i>$2</i>")
.replace(/~~([^\s~](?:[^~\n]*?[^\s~])?)~~/g,"<s>$1</s>")
}
function tableRow(line){
let t=String(line||"").trim()
if(!t.includes("|"))return null
if(t.startsWith("|"))t=t.slice(1)
if(t.endsWith("|")&&!t.endsWith("\\|"))t=t.slice(0,-1)
const cells=[]
let cur=""
for(let i=0;i<t.length;i++){
if(t[i]==="\\"&&t[i+1]==="|"){cur+="|";i++}
else if(t[i]==="|"){cells.push(cur.trim());cur=""}
else cur+=t[i]
}
cells.push(cur.trim())
return cells.length?cells:null
}
function tableSeparator(line){
const cells=tableRow(line)
if(!cells||!cells.length)return null
if(!cells.every((c)=>/^:?-{1,}:?$/.test(c.replace(/\s+/g,""))))return null
if(!/-/.test(line))return null
return cells.map((c)=>{const k=c.replace(/\s+/g,"");return k.startsWith(":")&&k.endsWith(":")?"center":k.endsWith(":")?"right":k.startsWith(":")?"left":""})
}
const RX_FENCE=/^ {0,3}(`{3,}|~{3,})\s*([A-Za-z0-9+#._-]*)[^`]*$/
const RX_HEADING=/^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/
const RX_HR=/^ {0,3}([-*_])(?:\s*\1){2,}\s*$/
const RX_LIST=/^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const RX_QUOTE=/^ {0,3}>\s?(.*)$/
function parseList(lines,i){
const first=RX_LIST.exec(lines[i])
const baseIndent=first[1].replace(/\t/g,"    ").length
const ordered=/\d/.test(first[2])
const list={type:"list",ordered,start:ordered?parseInt(first[2],10):1,items:[]}
while(i<lines.length){
const m=RX_LIST.exec(lines[i])
if(!m){
// an indented continuation line belongs to the last item
if(list.items.length&&/^\s+\S/.test(lines[i])&&!RX_FENCE.test(lines[i])){list.items[list.items.length-1].text+="\n"+lines[i].trim();i++;continue}
break
}
const indent=m[1].replace(/\t/g,"    ").length
if(indent<baseIndent)break
if(indent>=baseIndent+2&&list.items.length){
const sub=parseList(lines,i)
list.items[list.items.length-1].children.push(sub.block)
i=sub.next
continue
}
if(/\d/.test(m[2])!==ordered)break
let text=m[3]
let checked=null
const c=/^\[( |x|X)?\]\s+(.*)$/.exec(text)
if(c){checked=!!c[1]&&c[1].toLowerCase()==="x";text=c[2]}
list.items.push({text,checked,children:[]})
i++
}
return {block:list,next:i}
}
function toBlocks(md){
const lines=String(md===undefined||md===null?"":md).replace(/\r\n?/g,"\n").replace(/\u0000/g,"").split("\n")
const blocks=[]
let para=[]
const flush=()=>{if(para.length){blocks.push({type:"paragraph",text:para.join("\n")});para=[]}}
let i=0
while(i<lines.length){
const line=lines[i]
const fence=RX_FENCE.exec(line)
if(fence){
flush()
const mark=fence[1][0],len=fence[1].length
const body=[]
i++
while(i<lines.length){
const close=new RegExp("^ {0,3}"+(mark==="`"?"`":"~")+"{"+len+",}\\s*$")
if(close.test(lines[i])){i++;break}
body.push(lines[i]);i++
}
blocks.push({type:"code",lang:(fence[2]||"").toLowerCase(),text:body.join("\n")})
continue
}
if(!line.trim()){flush();i++;continue}
const h=RX_HEADING.exec(line)
if(h){flush();blocks.push({type:"heading",level:h[1].length,text:h[2]});i++;continue}
if(RX_HR.test(line)){flush();blocks.push({type:"hr"});i++;continue}
const head=tableRow(line)
const align=head&&i+1<lines.length?tableSeparator(lines[i+1]):null
if(head&&align&&align.length===head.length){
flush()
const rows=[]
i+=2
while(i<lines.length&&lines[i].trim()&&lines[i].includes("|")){
const r=tableRow(lines[i])||[]
while(r.length<head.length)r.push("")
rows.push(r.slice(0,head.length));i++
}
blocks.push({type:"table",head,rows,align})
continue
}
if(RX_QUOTE.test(line)){
flush()
const inner=[]
while(i<lines.length&&RX_QUOTE.test(lines[i])){inner.push(RX_QUOTE.exec(lines[i])[1]);i++}
blocks.push({type:"quote",blocks:toBlocks(inner.join("\n"))})
continue
}
if(RX_LIST.test(line)){
flush()
const r=parseList(lines,i)
blocks.push(r.block)
i=r.next
continue
}
para.push(line.replace(/\s+$/,""))
i++
}
flush()
return blocks
}
function listHtml(b,cls){
const check=b.items.some((it)=>it.checked!==null)&&!b.ordered
const tag=b.ordered?"ol":"ul"
const attrs=(check&&cls?' class="note-checklist"':"")+(b.ordered&&b.start>1?' start="'+b.start+'"':"")
return "<"+tag+attrs+">"+b.items.map((it)=>{
const mark=check&&cls?(it.checked?' data-checked="1"':""):""
const prefix=check&&!cls?(it.checked?"☑ ":"☐ "):""
return "<li"+mark+">"+prefix+inline(it.text).replace(/\n/g,"<br>")+it.children.map((c)=>listHtml(c,cls)).join("")+"</li>"
}).join("")+"</"+tag+">"
}
function blocksToHtml(blocks,opts){
const cls=!opts||opts.noteClasses!==false
return blocks.map((b)=>{
if(b.type==="heading")return "<h"+b.level+">"+inline(b.text)+"</h"+b.level+">"
if(b.type==="hr")return "<hr>"
if(b.type==="code"){
const lang=String(b.lang||"").replace(/[^a-z0-9+#._-]/g,"").slice(0,20)
return "<pre"+(cls?' class="note-code"':"")+(lang?' data-lang="'+lang+'"':"")+">"+(escape(b.text)||"<br>")+"</pre>"
}
if(b.type==="list")return listHtml(b,cls)
if(b.type==="quote")return "<blockquote>"+blocksToHtml(b.blocks,opts)+"</blockquote>"
if(b.type==="table"){
const al=(i)=>b.align[i]?' style="text-align:'+b.align[i]+'"':""
return "<table"+(cls?' class="note-table"':"")+"><tbody><tr>"+b.head.map((c,i)=>"<th"+al(i)+">"+(inline(c)||"<br>")+"</th>").join("")+"</tr>"+b.rows.map((r)=>"<tr>"+r.map((c,i)=>"<td"+al(i)+">"+(inline(c)||"<br>")+"</td>").join("")+"</tr>").join("")+"</tbody></table>"
}
return "<p>"+inline(b.text).replace(/\n/g,"<br>")+"</p>"
}).join("")
}
function toHtml(md,opts){return blocksToHtml(toBlocks(md),opts)}
// A plain-text paste is treated as Markdown only on strong signals, so ordinary tool output is not reformatted.
function looksLikeMarkdown(text){
const t=String(text||"")
if(t.length<3||t.length>400000)return false
const lines=t.replace(/\r\n?/g,"\n").split("\n")
let score=0,fences=0,lists=0
// In a pasted shell session "# whoami" is a root prompt, not a heading.
const shell=lines.some((l)=>/^(?:\$ |PS [A-Z]:\\|[\w.-]+@[\w.-]+[:~ ])/.test(l))
for(let i=0;i<lines.length;i++){
const l=lines[i]
if(/^ {0,3}(`{3,}|~{3,})/.test(l))fences++
else if(/^ {0,3}#{1,6}\s+\S/.test(l))score+=shell?0:2
else if(/^\s*(?:[-*+]|\d{1,3}[.)])\s+\[[ xX]?\]\s+\S/.test(l))score+=2
else if(/^\s*(?:[-*+])\s+\S/.test(l)||/^\s*\d{1,3}[.)]\s+\S/.test(l))lists++
else if(/^ {0,3}>\s+\S/.test(l))score+=1
if(i+1<lines.length&&tableRow(l)&&tableSeparator(lines[i+1])&&tableRow(l).length===tableSeparator(lines[i+1]).length)score+=3
if(/\[[^\]\n]+\]\((?:https?:\/\/|mailto:)[^)\s]+\)/.test(l))score+=2
if(/\*\*[^\s*][^*\n]*\*\*/.test(l))score+=1
}
if(fences>=2)score+=3
if(lists>=2)score+=2
return score>=2
}
// Called with the text of the line up to the caret right after a closing marker was typed.
function inlineTrigger(before){
const t=String(before||"")
let m
if((m=/\[([^\]\n]+)\]\(([^)\s]+)\)$/.exec(t))){
const url=safeUrl(m[2])
if(url&&!/!$/.test(t.slice(0,m.index)))return {type:"link",start:m.index,raw:m[0],text:m[1],url}
return null
}
if((m=/\*\*([^\s*](?:[^*\n]*[^\s*])?)\*\*$/.exec(t)))return {type:"bold",start:m.index,raw:m[0],text:m[1]}
if((m=/(?:^|[^\w_])(__([^\s_](?:[^_\n]*[^\s_])?)__)$/.exec(t)))return {type:"bold",start:m.index+m[0].length-m[1].length,raw:m[1],text:m[2]}
if((m=/~~([^\s~](?:[^~\n]*[^\s~])?)~~$/.exec(t)))return {type:"strike",start:m.index,raw:m[0],text:m[1]}
// ```code``` or ``code`` written on one line: inline code, or a whole code block when the span is the entire line.
if((m=/(`{2,3})([^`\n]*[^`\s][^`\n]*)\1$/.exec(t))&&!(m.index>0&&t[m.index-1]==="`")){
return {type:"code",start:m.index,raw:m[0],text:m[2].trim(),block:m[1].length===3&&!t.slice(0,m.index).trim()}
}
if((m=/`([^`\n]+)`$/.exec(t))){
if(m.index>0&&t[m.index-1]==="`")return null
return {type:"code",start:m.index,raw:m[0],text:m[1]}
}
if((m=/(?:^|[^*\w])(\*([^\s*](?:[^*\n]*[^\s*])?)\*)$/.exec(t)))return {type:"italic",start:m.index+m[0].length-m[1].length,raw:m[1],text:m[2]}
if((m=/(?:^|[^\w_])(_([^\s_](?:[^_\n]*[^\s_])?)_)$/.exec(t)))return {type:"italic",start:m.index+m[0].length-m[1].length,raw:m[1],text:m[2]}
return null
}
// ---- HTML back to Markdown ("Copy as Markdown"). Works on anything shaped like a DOM node (nodeType, tagName, childNodes, nodeValue, getAttribute), so it is tested without a browser.
// opts.custom(node) may return the Markdown for a node it knows better (a command card, an attachment), or null to let the walker handle it.
const MD_BLOCK_TAGS=new Set(["P","DIV","H1","H2","H3","H4","H5","H6","UL","OL","LI","PRE","BLOCKQUOTE","TABLE","HR","FIGURE","THEAD","TBODY","TR"])
function mdKids(node){return Array.prototype.slice.call(node.childNodes||[])}
function mdAttr(node,name){return node.getAttribute?(node.getAttribute(name)||""):""}
function mdHasClass(node,cls){return (" "+mdAttr(node,"class")+" ").indexOf(" "+cls+" ")>=0}
function mdText(node){
if(node.nodeType===3)return node.nodeValue||""
if(node.nodeType!==1&&node.nodeType!==11)return ""
if(node.tagName==="BR")return "\n"
return mdKids(node).map(mdText).join("")
}
function mdWrap(mark,inner){
const m=/^(\s*)([\s\S]*?)(\s*)$/.exec(inner)
return m[2]?m[1]+mark+m[2]+mark+m[3]:inner
}
function mdInlineNode(node,opts){
if(node.nodeType===3)return (node.nodeValue||"").replace(/​/g,"").replace(/\s*\n\s*/g," ").replace(/([`*])/g,"\\$1")
if(node.nodeType!==1)return ""
const custom=opts&&opts.custom?opts.custom(node):null
if(custom!==null&&custom!==undefined)return custom
const tag=node.tagName
const inner=()=>mdKids(node).map((k)=>mdInlineNode(k,opts)).join("")
if(tag==="BR")return "\n"
if(tag==="B"||tag==="STRONG")return mdWrap("**",inner())
if(tag==="I"||tag==="EM")return mdWrap("*",inner())
if(tag==="S"||tag==="STRIKE"||tag==="DEL")return mdWrap("~~",inner())
if(tag==="CODE"||tag==="KBD"||tag==="SAMP"){const t=mdText(node);return t?(t.indexOf("`")>=0?"`` "+t+" ``":"`"+t+"`"):""}
if(tag==="A"){
const href=mdAttr(node,"href")
const text=inner()
if(/^https?:|^mailto:/i.test(href))return mdText(node).trim()===href?"<"+href+">":"["+text+"]("+href.replace(/\)/g,"%29")+")"
return /^notelink:/i.test(href)?"[["+mdText(node).trim()+"]]":text
}
if(tag==="IMG"){const src=mdAttr(node,"src");return "!["+mdAttr(node,"alt")+"]"+(/^https?:/i.test(src)?"("+src+")":"")}
return inner()
}
function mdInlineRun(nodes,opts){return nodes.map((n)=>mdInlineNode(n,opts)).join("").replace(/[ \t]+\n/g,"\n").replace(/^\s+|\s+$/g,"")}
function mdIsBlock(node){return node.nodeType===1&&(MD_BLOCK_TAGS.has(node.tagName)||mdHasClass(node,"note-callout")||mdHasClass(node,"cmd-card-embed"))}
function mdListItems(list,depth,opts){
const ordered=list.tagName==="OL"
const check=mdHasClass(list,"note-checklist")
let n=parseInt(mdAttr(list,"start"),10)||1
const out=[]
mdKids(list).forEach((li)=>{
if(li.nodeType!==1||li.tagName!=="LI")return
const inline=[],nested=[]
mdKids(li).forEach((k)=>{if(k.nodeType===1&&(k.tagName==="UL"||k.tagName==="OL"))nested.push(k);else inline.push(k)})
const mark=ordered?(n++)+". ":"- "+(check?(mdAttr(li,"data-checked")?"[x] ":"[ ] "):"")
const body=mdBlocks(inline,opts).join("\n").replace(/\n/g,"\n"+" ".repeat(mark.length))
out.push("  ".repeat(depth)+mark+body)
nested.forEach((sub)=>mdListItems(sub,depth+1,opts).forEach((l)=>out.push(l)))
})
return out
}
function mdTable(table,opts){
const rows=[]
const collect=(node)=>mdKids(node).forEach((k)=>{if(k.nodeType!==1)return;if(k.tagName==="TR")rows.push(k);else if(k.tagName==="THEAD"||k.tagName==="TBODY"||k.tagName==="TFOOT")collect(k)})
collect(table)
const cells=rows.map((r)=>mdKids(r).filter((c)=>c.nodeType===1&&(c.tagName==="TD"||c.tagName==="TH")).map((c)=>mdInlineRun(mdKids(c),opts).replace(/\n+/g," ").replace(/\|/g,"\\|")))
if(!cells.length)return ""
const width=Math.max.apply(null,cells.map((r)=>r.length))
const line=(r)=>"| "+Array.from({length:width},(_,i)=>r[i]||"").join(" | ")+" |"
return [line(cells[0]),"|"+Array.from({length:width},()=>" --- ").join("|")+"|"].concat(cells.slice(1).map(line)).join("\n")
}
// The blocks of a run of sibling nodes: loose inline nodes between two blocks become a paragraph.
function mdBlocks(nodes,opts){
const out=[]
let run=[]
const flush=()=>{if(run.length){const t=mdInlineRun(run,opts);if(t)out.push(t);run=[]}}
nodes.forEach((node)=>{
if(node.nodeType===3||(node.nodeType===1&&!mdIsBlock(node))){run.push(node);return}
if(node.nodeType!==1)return
flush()
const custom=opts&&opts.custom?opts.custom(node):null
if(custom!==null&&custom!==undefined){if(custom)out.push(custom);return}
const tag=node.tagName
const h=/^H([1-6])$/.exec(tag)
if(h){const t=mdInlineRun(mdKids(node),opts).replace(/\n+/g," ");if(t)out.push("#".repeat(parseInt(h[1],10))+" "+t);return}
if(tag==="HR"){out.push("---");return}
if(tag==="PRE"){const t=mdText(node).replace(/\n$/,"");const fence=t.indexOf("```")>=0?"````":"```";out.push(fence+mdAttr(node,"data-lang")+"\n"+t+"\n"+fence);return}
if(tag==="UL"||tag==="OL"){const l=mdListItems(node,0,opts);if(l.length)out.push(l.join("\n"));return}
if(tag==="TABLE"){const t=mdTable(node,opts);if(t)out.push(t);return}
if(tag==="BLOCKQUOTE"||mdHasClass(node,"note-callout")){
const inner=mdBlocks(mdKids(node),opts)
if(mdHasClass(node,"note-callout")){
const kind=mdAttr(node,"data-callout")||"info"
const sev=mdAttr(node,"data-sev"),cvss=mdAttr(node,"data-cvss")
const extra=[sev?sev.charAt(0).toUpperCase()+sev.slice(1):"",cvss?"CVSS "+cvss:""].filter(Boolean).join(", ")
inner.unshift("**"+(kind==="vuln"?"VULNERABILITY":kind.toUpperCase())+(extra?" ("+extra+")":"")+"**")
}
if(inner.length)out.push(inner.join("\n\n").split("\n").map((l)=>l?"> "+l:">").join("\n"))
return
}
mdBlocks(mdKids(node),opts).forEach((b)=>out.push(b))
})
flush()
return out
}
function fromDom(root,opts){
if(!root)return ""
return mdBlocks(root.nodeType===1&&mdIsBlock(root)?[root]:mdKids(root),opts||{}).join("\n\n").replace(/ /g," ").replace(/\n{3,}/g,"\n\n").trim()
}
return {escape,safeUrl,inline,tableRow,tableSeparator,toBlocks,blocksToHtml,toHtml,looksLikeMarkdown,inlineTrigger,fromDom}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=LoyaMarkdown
