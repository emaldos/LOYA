// Pure logic for the note editor's options (no DOM, no bridge): the command registry shared by the toolbar, the More panel, the selection bubble, the right-click menu and the slash menu, the toolbar layout, and the pentest text tools (encoders, hashes, JWT, ATT&CK list, nmap tables, CVSS).
// Loaded by the app as a plain script (global NotesEd) and by tests/js/notes_editor_actions.js through require().
const NotesEd=(function(){
// ---- command registry
// tier: "main" is on the toolbar by default, "advanced" lives in the More panel (and can be pinned), "context" only appears in menus and the bubble.
// needs: what must be true for the command to be enabled - sel (text selected), fmt (caret where inline formatting applies), block (a movable block), table (inside a table), finding (inside a finding / vulnerability callout).
const GROUPS=[
{id:"style",label:"Text style"},
{id:"format",label:"Format"},
{id:"lists",label:"Lists"},
{id:"align",label:"Alignment"},
{id:"insert",label:"Insert"},
{id:"callout",label:"Callouts"},
{id:"pentest",label:"Pentest"},
{id:"selection",label:"Selection tools"},
{id:"block",label:"Block"},
{id:"table",label:"Table"},
{id:"view",label:"View and editing"},
{id:"clipboard",label:"Clipboard"}
]
const COMMANDS=[
{id:"style",label:"Text style",kind:"style",group:"style",tier:"main",hint:"Paragraph, headings, quote or code block"},
{id:"style.p",label:"Normal text",icon:"pilcrow",group:"style",tier:"context",shortcut:"Ctrl+Alt+0",needs:["fmt"]},
{id:"style.h1",label:"Heading 1",glyph:"H1",group:"style",tier:"context",shortcut:"Ctrl+Alt+1",needs:["fmt"],slash:{hint:"Large section title",keys:"h1 heading title #"}},
{id:"style.h2",label:"Heading 2",glyph:"H2",group:"style",tier:"context",shortcut:"Ctrl+Alt+2",needs:["fmt"],slash:{hint:"Section title",keys:"h2 heading subtitle ##"}},
{id:"style.h3",label:"Heading 3",glyph:"H3",group:"style",tier:"context",shortcut:"Ctrl+Alt+3",needs:["fmt"],slash:{hint:"Sub-section title",keys:"h3 heading ###"}},
{id:"style.quote",label:"Quote",icon:"quote",group:"style",tier:"context",needs:["fmt"],slash:{hint:"Indented quote",keys:"quote blockquote"}},
{id:"fmt.bold",label:"Bold",icon:"bold",group:"format",tier:"main",shortcut:"Ctrl+B",bubble:true,needs:["fmt"]},
{id:"fmt.italic",label:"Italic",icon:"italic",group:"format",tier:"main",shortcut:"Ctrl+I",bubble:true,needs:["fmt"]},
{id:"fmt.underline",label:"Underline",icon:"underline",group:"format",tier:"main",shortcut:"Ctrl+U",bubble:true,needs:["fmt"]},
{id:"fmt.strike",label:"Strikethrough",icon:"strike",group:"format",tier:"main",shortcut:"Ctrl+Shift+X",bubble:true,needs:["fmt"]},
{id:"fmt.color",label:"Text colour",icon:"color",kind:"color",group:"format",tier:"main",bubble:true,needs:["fmt"],hint:"Click the arrow for the palette"},
{id:"fmt.highlight",label:"Highlight",icon:"marker",kind:"color",group:"format",tier:"main",shortcut:"Ctrl+Shift+H",bubble:true,needs:["fmt"],hint:"Click the arrow for the palette"},
{id:"fmt.sizeDown",label:"Smaller text",icon:"font-smaller",group:"format",tier:"context",shortcut:"Ctrl+Shift+,",bubble:true,needs:["sel","fmt"]},
{id:"fmt.sizeUp",label:"Larger text",icon:"font-bigger",group:"format",tier:"context",shortcut:"Ctrl+Shift+.",bubble:true,needs:["sel","fmt"]},
{id:"fmt.size",label:"Font size",kind:"size",group:"format",tier:"advanced",hint:"Size of the selected text"},
{id:"fmt.code",label:"Inline code",icon:"code-inline",group:"format",tier:"advanced",shortcut:"Ctrl+E",bubble:true,needs:["fmt"]},
{id:"fmt.clear",label:"Clear formatting",icon:"eraser",group:"format",tier:"advanced",shortcut:"Ctrl+\\",bubble:true,needs:["fmt"]},
{id:"list.bullet",label:"Bullet list",icon:"list-bullet",group:"lists",tier:"main",shortcut:"Ctrl+Shift+8",needs:["fmt"],slash:{hint:"- item",keys:"ul bullet list unordered"}},
{id:"list.number",label:"Numbered list",icon:"list-number",group:"lists",tier:"main",shortcut:"Ctrl+Shift+7",needs:["fmt"],slash:{hint:"1. item",keys:"ol numbered list ordered steps"}},
{id:"list.check",label:"Checklist",icon:"checklist",group:"lists",tier:"main",shortcut:"Ctrl+Shift+9",needs:["fmt"],slash:{hint:"Methodology / to-do items",keys:"check checklist todo task"}},
{id:"align.left",label:"Align left",icon:"align-left",group:"align",tier:"advanced"},
{id:"align.center",label:"Align centre",icon:"align-center",group:"align",tier:"advanced"},
{id:"align.right",label:"Align right",icon:"align-right",group:"align",tier:"advanced"},
{id:"ins.link",label:"Link",icon:"link",group:"insert",tier:"main",shortcut:"Ctrl+L",bubble:true,needs:["fmt"],hint:"Web link or link to another note",slash:{label:"Link",hint:"Web link or link to a note",keys:"link url note href"}},
{id:"ins.image",label:"Image or file",icon:"image",group:"insert",tier:"main",slash:{label:"Image / file",hint:"Attach a screenshot or file",keys:"image file screenshot attachment picture"}},
{id:"ins.cmd",label:"Command block",icon:"command-line",group:"insert",tier:"main",shortcut:"Ctrl+Shift+C",slash:{hint:"Reusable command card",keys:"command cmd block"}},
{id:"ins.finding",label:"Finding",menuLabel:"Finding template",icon:"bug",group:"insert",tier:"main",hint:"Finding template: title, severity, hosts, steps, impact, fix",slash:{label:"Finding template",hint:"Title, severity, hosts, steps, impact, fix",keys:"finding template vuln report"}},
{id:"ins.table",label:"Table",icon:"table",group:"insert",tier:"main",slash:{hint:"3 x 3 table",keys:"table grid"}},
{id:"ins.pickcmd",label:"Pick a saved command",icon:"search",group:"insert",tier:"advanced",slash:{hint:"Insert a command from the library",keys:"pick command library saved"}},
{id:"ins.code",label:"Code block",icon:"code-block",group:"insert",tier:"advanced",shortcut:"Ctrl+Alt+C",hint:"Wraps the selection when there is one",slash:{hint:"Monospace, keeps whitespace",keys:"code snippet output pre exploit"}},
{id:"ins.divider",label:"Divider",icon:"hr",group:"insert",tier:"advanced",slash:{hint:"Horizontal line",keys:"divider hr line separator"}},
{id:"ins.time",label:"Timestamp",icon:"clock",group:"insert",tier:"advanced",shortcut:"Ctrl+Shift+;",slash:{hint:"Insert the current date and time",keys:"timestamp time date now"}},
{id:"ins.drawing",label:"Drawing",icon:"brush",group:"insert",tier:"advanced",hint:"Sketch a diagram (hover a picture and press Annotate to draw on it)",slash:{hint:"Sketch a diagram",keys:"drawing sketch draw diagram canvas"}},
{id:"callout.finding",label:"Finding callout",menuLabel:"Finding",icon:"bug",group:"callout",tier:"advanced",slash:{label:"Callout: Finding",hint:"With severity and CVSS",keys:"callout finding severity"}},
{id:"callout.vuln",label:"Vulnerability callout",menuLabel:"Vulnerability",icon:"shield",group:"callout",tier:"advanced",slash:{label:"Callout: Vulnerability",hint:"With severity and CVSS",keys:"callout vulnerability vuln cve"}},
{id:"callout.info",label:"Info callout",menuLabel:"Info",icon:"info",group:"callout",tier:"advanced",slash:{label:"Callout: Info",hint:"Neutral note",keys:"callout info note"}},
{id:"callout.warning",label:"Warning callout",menuLabel:"Warning",icon:"warning",group:"callout",tier:"advanced",slash:{label:"Callout: Warning",hint:"Careful / out of scope",keys:"callout warning caution scope"}},
{id:"callout.credential",label:"Credential callout",menuLabel:"Credential",icon:"key",group:"callout",tier:"advanced",hint:"Host, user and a masked secret (a selected user:password is filled in)",slash:{label:"Callout: Credential",hint:"Masked secret with reveal / copy",keys:"callout credential password secret creds login"}},
{id:"callout.evidence",label:"Evidence callout",menuLabel:"Evidence",icon:"clipboard-check",group:"callout",tier:"advanced",slash:{label:"Callout: Evidence",hint:"Proof, output, screenshot",keys:"callout evidence proof"}},
{id:"pt.output",label:"Command output",icon:"terminal-out",group:"pentest",tier:"advanced",hint:"Command, exit code and output as one evidence block",slash:{hint:"Command, exit code and its output",keys:"output command exit result evidence"}},
{id:"pt.nmap",label:"Nmap to table",icon:"network",group:"pentest",tier:"advanced",hint:"Turn pasted or selected nmap output into a host / port table",slash:{label:"Nmap table",hint:"Host / port table from nmap output",keys:"nmap ports hosts table scan"}},
{id:"pt.mitre",label:"ATT&CK technique",icon:"crosshair",group:"pentest",tier:"advanced",hint:"Tag the note with a MITRE ATT&CK technique",slash:{hint:"MITRE ATT&CK technique tag",keys:"mitre attack technique ttp tag"}},
{id:"pt.cve",label:"CVE",menuLabel:"CVE callout",icon:"shield",group:"pentest",tier:"advanced",hint:"Look up a CVE and insert it as a vulnerability callout (severity, CVSS, KEV, EPSS, how to protect yourself, references)",slash:{label:"CVE",hint:"Insert a CVE as a vulnerability callout",keys:"cve vulnerability nvd kev epss advisory"}},
{id:"pt.cvss",label:"CVSS calculator",icon:"gauge",group:"pentest",tier:"advanced",needs:["finding"],hint:"Score the finding the caret is in (CVSS 3.1 base)"},
{id:"pt.ioc",label:"IOC tools",icon:"target",group:"pentest",tier:"advanced",hint:"IPs, domains, URLs and hashes in the selection or the note: copy, defang, add to Targets"},
{id:"pt.encode",label:"Encode / decode",icon:"shuffle",group:"selection",tier:"advanced",bubbleMenu:true,hint:"Base64, URL, HTML entities, hex and JWT view for the selection"},
{id:"pt.hash",label:"Hash",icon:"hash",group:"selection",tier:"advanced",needs:["sel"],bubbleMenu:true,hint:"MD5, SHA-1, SHA-256 and NTLM of the selection"},
{id:"pt.defang",label:"Defang",icon:"shield",group:"selection",tier:"advanced",needs:["sel"],bubbleMenu:true,hint:"10.0.0.1 becomes 10[.]0[.]0[.]1, http becomes hxxp"},
{id:"pt.refang",label:"Refang",icon:"shield",group:"selection",tier:"context",needs:["sel"],bubbleMenu:true},
{id:"pt.terminal",label:"Send to terminal",icon:"send",group:"selection",tier:"advanced",needs:["sel"],bubbleMenu:true,hint:"Puts the selection on the terminal input line. It is never run for you."},
{id:"pt.savecmd",label:"Save as command",icon:"commands",group:"selection",tier:"advanced",needs:["sel"],bubbleMenu:true,hint:"Opens the command form with the selection filled in"},
{id:"pt.wrapcode",label:"Wrap as code block",icon:"code-block",group:"selection",tier:"context",needs:["sel"],bubbleMenu:true},
{id:"pt.evidence",label:"Wrap as evidence",icon:"clipboard-check",group:"selection",tier:"advanced",needs:["sel"],bubbleMenu:true,hint:"Evidence block with a timestamp and a source"},
{id:"pt.secret",label:"Mask as secret",icon:"eye-off",group:"selection",tier:"advanced",shortcut:"Ctrl+Shift+M",bubbleMenu:true,hint:"Mask the selected text (again inside it to unmask)"},
{id:"pt.copysecret",label:"Copy unmasked",icon:"key",group:"selection",tier:"context",needs:["secret"]},
{id:"pt.copymd",label:"Copy as Markdown",icon:"markdown",group:"selection",tier:"advanced",bubbleMenu:true,hint:"The selection, or the whole note when nothing is selected"},
{id:"pt.copytext",label:"Copy as plain text",icon:"text",group:"selection",tier:"advanced",bubbleMenu:true,hint:"The selection, or the whole note when nothing is selected"},
{id:"block.up",label:"Move block up",icon:"arrow-up",group:"block",tier:"context",shortcut:"Alt+Shift+Up",needs:["block"]},
{id:"block.down",label:"Move block down",icon:"arrow-down",group:"block",tier:"context",shortcut:"Alt+Shift+Down",needs:["block"]},
{id:"block.dup",label:"Duplicate block",icon:"copy",group:"block",tier:"context",shortcut:"Ctrl+Shift+D",needs:["block"]},
{id:"block.del",label:"Delete block",icon:"trash",group:"block",tier:"context",danger:true,needs:["block"]},
{id:"tbl.rowAbove",label:"Insert row above",icon:"arrow-up",group:"table",tier:"context",needs:["table"]},
{id:"tbl.rowBelow",label:"Insert row below",icon:"arrow-down",group:"table",tier:"context",needs:["table"]},
{id:"tbl.colLeft",label:"Insert column left",icon:"arrow-left",group:"table",tier:"context",needs:["table"]},
{id:"tbl.colRight",label:"Insert column right",icon:"arrow-right",group:"table",tier:"context",needs:["table"]},
{id:"tbl.header",label:"Header row on / off",icon:"table",group:"table",tier:"context",needs:["table"]},
{id:"tbl.delRow",label:"Delete row",icon:"close",group:"table",tier:"context",danger:true,needs:["table"]},
{id:"tbl.delCol",label:"Delete column",icon:"close",group:"table",tier:"context",danger:true,needs:["table"]},
{id:"tbl.delTable",label:"Delete table",icon:"trash",group:"table",tier:"context",danger:true,needs:["table"]},
{id:"view.undo",label:"Undo",icon:"undo",group:"view",tier:"advanced",shortcut:"Ctrl+Z"},
{id:"view.redo",label:"Redo",icon:"redo",group:"view",tier:"advanced",shortcut:"Ctrl+Y"},
{id:"view.find",label:"Find in note",icon:"search",group:"view",tier:"advanced",shortcut:"Ctrl+F"},
{id:"view.outline",label:"Outline",icon:"list",group:"view",tier:"advanced",hint:"Show / hide the heading outline",slash:{hint:"Show / hide the heading outline",keys:"outline toc contents"}},
{id:"view.pairs",label:"Auto-close brackets",icon:"pairs",group:"view",tier:"advanced",hint:"Typing ( [ { or a quote adds the closing one"},
{id:"view.bubble",label:"Selection toolbar",icon:"dots",group:"view",tier:"advanced",hint:"Show the small toolbar next to selected text"},
{id:"view.remoteImages",label:"Block remote images",icon:"image",group:"view",tier:"advanced",hint:"Web images in notes load only when clicked (privacy: no tracking pixels, no IP leak)"},
{id:"clip.cut",label:"Cut",icon:"cut",group:"clipboard",tier:"context",shortcut:"Ctrl+X",needs:["sel"]},
{id:"clip.copy",label:"Copy",icon:"copy",group:"clipboard",tier:"context",shortcut:"Ctrl+C",needs:["sel"]},
{id:"clip.paste",label:"Paste",icon:"paste",group:"clipboard",tier:"context",shortcut:"Ctrl+V"},
{id:"clip.pastePlain",label:"Paste as plain text",icon:"text",group:"clipboard",tier:"context",shortcut:"Ctrl+Shift+V"}
]
const BY_ID={}
COMMANDS.forEach((c)=>{BY_ID[c.id]=c})
function get(id){return BY_ID[id]||null}
function group(id){return GROUPS.find((g)=>g.id===id)||null}
function title(cmd){
const c=typeof cmd==="string"?get(cmd):cmd
if(!c)return ""
return c.label+(c.shortcut?" ("+c.shortcut+")":"")+(c.hint?" - "+c.hint:"")
}
// ctx: {hasSel,fmt,block,table,finding,secret}. A command with no needs is always available.
function enabledFor(cmd,ctx){
const c=typeof cmd==="string"?get(cmd):cmd
if(!c)return false
const x=ctx||{}
return (c.needs||[]).every((n)=>n==="sel"?!!x.hasSel:!!x[n])
}
// ---- toolbar layout
function defaultMain(){return COMMANDS.filter((c)=>c.tier==="main").map((c)=>c.id)}
function pinnable(id){const c=get(id);return !!c&&(c.tier==="main"||c.tier==="advanced")}
// The saved main-bar list: known, pinnable ids, each once. Anything else (an old id after an update, junk in settings.json) is dropped; an unusable value means the default bar.
function normPins(list){
if(!Array.isArray(list))return defaultMain()
const out=[]
list.forEach((id)=>{if(typeof id==="string"&&pinnable(id)&&!out.includes(id))out.push(id)})
return out.slice(0,40)
}
function togglePin(list,id){
const pins=normPins(list)
if(!pinnable(id))return pins
if(pins.includes(id))return pins.filter((x)=>x!==id)
// A pinned tool goes next to the others of its group, in registry order, so the bar keeps its grouping.
const order=COMMANDS.map((c)=>c.id)
const next=pins.concat([id])
return next.sort((a,b)=>order.indexOf(a)-order.indexOf(b))
}
// The main bar as a flat list with a separator wherever the group changes.
function barItems(pins){
const out=[]
let last=null
normPins(pins).forEach((id)=>{
const c=get(id)
if(last&&c.group!==last)out.push({sep:true})
out.push({id})
last=c.group
})
return out
}
// How many leading items fit: widths are the item widths in order (separators included), gap the space between two items, more the width kept for the More button.
function fitCount(widths,available,gap,more){
const g=gap||0
let used=0
const total=widths.reduce((a,w,i)=>a+w+(i?g:0),0)
if(total+g+(more||0)<=available)return widths.length
const room=available-(more||0)-g
let n=0
for(let i=0;i<widths.length;i++){
const next=used+widths[i]+(i?g:0)
if(next>room)break
used=next;n=i+1
}
return n
}
// What the More panel lists: tools pushed off the bar by a narrow editor first, then every group with its unpinned tools. In customise mode every pinnable tool is listed so it can be pinned or unpinned.
function moreSections(pins,overflowIds,customise){
const main=normPins(pins)
const over=(overflowIds||[]).filter((id)=>main.includes(id))
const out=[]
if(over.length&&!customise)out.push({id:"overflow",label:"More from the toolbar",items:over})
GROUPS.forEach((g)=>{
const items=COMMANDS.filter((c)=>c.group===g.id&&pinnable(c.id)&&(customise||!main.includes(c.id))).map((c)=>c.id)
if(items.length)out.push({id:g.id,label:g.label,items})
})
return out
}
function bubbleItems(){
const ids=COMMANDS.filter((c)=>c.bubble).map((c)=>c.id)
const order=["fmt.bold","fmt.italic","fmt.underline","fmt.strike","-","fmt.color","fmt.highlight","-","fmt.sizeDown","fmt.sizeUp","-","fmt.code","ins.link","fmt.clear"]
return order.filter((id)=>id==="-"||ids.includes(id))
}
function bubbleMenuItems(){
return ["pt.encode","pt.hash","-","pt.defang","pt.refang","pt.ioc","-","pt.terminal","pt.savecmd","-","pt.wrapcode","pt.evidence","pt.secret","callout.credential","pt.mitre","-","pt.copymd","pt.copytext"]
}
function slashItems(){
return COMMANDS.filter((c)=>c.slash).map((c)=>({id:c.id,label:c.slash.label||c.label,hint:c.slash.hint||c.hint||"",keys:c.slash.keys||""}))
}
// The right-click menu as a tree of command ids. "-" is a separator, {label,icon,items} a submenu, {strip} a row of icon buttons, {palette} a colour grid, {sizes} the size presets.
function menuModel(ctx){
const x=ctx||{}
const out=[]
if(x.card)out.push("card.edit","card.copy","card.delete","-")
if(x.link)out.push("link.open","link.remove","-")
if(x.secret)out.push("secret.toggle","pt.copysecret","-")
if(x.callout)out.push("callout.settings")
if(x.finding)out.push("pt.cvss")
if(x.callout||x.finding)out.push("-")
if(x.code)out.push("code.lang","code.copy","-")
out.push({strip:["fmt.bold","fmt.italic","fmt.underline","fmt.strike","fmt.code","fmt.clear"]})
out.push({label:"Format",icon:"color",items:[
{label:"Text colour",icon:"color",items:[{palette:"text"}]},
{label:"Highlight",icon:"marker",items:[{palette:"highlight"}]},
{label:"Size",icon:"font-bigger",items:["fmt.sizeUp","fmt.sizeDown","-",{sizes:[10,11,12,13,14,16,18,20,24,32]}]},
"-","fmt.bold","fmt.italic","fmt.underline","fmt.strike","fmt.code","-","fmt.clear"
]})
out.push({label:"Paragraph",icon:"pilcrow",items:["style.p","style.h1","style.h2","style.h3","style.quote","ins.code","-","list.bullet","list.number","list.check","-","align.left","align.center","align.right"]})
out.push({label:"Insert",icon:"add",items:[
"ins.cmd","ins.pickcmd","ins.image","ins.table","ins.divider","ins.code","list.check","ins.time","ins.drawing","ins.link","-",
{label:"Callout",icon:"info",items:["callout.finding","callout.vuln","callout.info","callout.warning","callout.credential","callout.evidence"]},
"ins.finding","pt.cve","pt.output","pt.nmap","pt.mitre"
]})
if(x.block)out.push({label:"Block",icon:"grip",items:[
"block.up","block.down","block.dup","-",
{label:"Align",icon:"align-left",items:["align.left","align.center","align.right"]},
{label:"Convert to",icon:"shuffle",items:["style.p","style.h1","style.h2","style.h3","style.quote",{cmd:"ins.code",label:"Code block",opts:{convert:true}},"list.bullet","list.number","list.check",{cmd:"callout.info",label:"Info callout",opts:{convert:true}},{cmd:"callout.warning",label:"Warning callout",opts:{convert:true}},{cmd:"callout.evidence",label:"Evidence callout",opts:{convert:true}}]},
"-","block.del"
]})
if(x.table)out.push({label:"Table",icon:"table",items:["tbl.rowAbove","tbl.rowBelow","tbl.colLeft","tbl.colRight","tbl.header","-","tbl.delRow","tbl.delCol","tbl.delTable"]})
out.push({label:x.hasSel?"Selection":"Pentest tools",icon:"shield",items:[
{label:"Encode / decode",icon:"shuffle",items:TRANSFORMS.map((t)=>({op:t.id,label:t.label}))},
"pt.hash","-","pt.defang","pt.refang","pt.ioc","-","pt.terminal","pt.savecmd","-","pt.wrapcode","pt.evidence","pt.secret","callout.credential","pt.mitre","-","pt.copymd","pt.copytext"
]})
out.push("-","clip.cut","clip.copy","clip.paste","clip.pastePlain")
return out
}
// Ids a menu uses that are not registry commands: actions on the thing that was right-clicked.
const MENU_LOCAL=[
{id:"card.edit",label:"Edit command",icon:"edit"},
{id:"card.copy",label:"Copy command",icon:"copy"},
{id:"card.delete",label:"Delete command",icon:"trash",danger:true},
{id:"link.open",label:"Open link",icon:"link"},
{id:"link.remove",label:"Remove link",icon:"close"},
{id:"secret.toggle",label:"Show / hide secret",icon:"eye-off"},
{id:"callout.settings",label:"Callout type and severity",icon:"sliders"},
{id:"code.lang",label:"Code language",icon:"code-block"},
{id:"code.copy",label:"Copy code",icon:"copy"}
]
function menuIds(model){
const out=[]
const walk=(items)=>items.forEach((it)=>{
if(typeof it==="string"){if(it!=="-")out.push(it)}
else if(it.cmd)out.push(it.cmd)
else if(it.strip)it.strip.forEach((id)=>out.push(id))
else if(it.items)walk(it.items)
})
walk(model)
return out
}
// ---- shortcuts ("Ctrl+Shift+X" as shown in tooltips; matched on the physical key so layouts with other symbols still work)
const KEY_CODES={",":"Comma",".":"Period",";":"Semicolon","\\":"Backslash","/":"Slash",Up:"ArrowUp",Down:"ArrowDown"}
function shortcutParse(s){
const parts=String(s||"").split("+")
const key=parts.pop()
if(!key)return null
const code=KEY_CODES[key]||(/^[0-9]$/.test(key)?"Digit"+key:/^[A-Za-z]$/.test(key)?"Key"+key.toUpperCase():key)
return {ctrl:parts.includes("Ctrl"),shift:parts.includes("Shift"),alt:parts.includes("Alt"),code}
}
// The command a key event stands for, or null. ev: {ctrlKey,metaKey,shiftKey,altKey,code}.
function shortcutMatch(ev,skip){
if(!ev||!ev.code)return null
const ctrl=!!(ev.ctrlKey||ev.metaKey)
for(const c of COMMANDS){
if(!c.shortcut||(skip&&skip.includes(c.id)))continue
const p=shortcutParse(c.shortcut)
if(p&&p.code===ev.code&&p.ctrl===ctrl&&p.shift===!!ev.shiftKey&&p.alt===!!ev.altKey)return c.id
}
return null
}
// ---- bytes and text
function utf8Bytes(s){
const out=[]
const str=String(s===undefined||s===null?"":s)
for(let i=0;i<str.length;i++){
let c=str.codePointAt(i)
if(c>0xffff)i++
else if(c>=0xd800&&c<=0xdfff)c=0xfffd
if(c<0x80)out.push(c)
else if(c<0x800)out.push(0xc0|(c>>6),0x80|(c&63))
else if(c<0x10000)out.push(0xe0|(c>>12),0x80|((c>>6)&63),0x80|(c&63))
else out.push(0xf0|(c>>18),0x80|((c>>12)&63),0x80|((c>>6)&63),0x80|(c&63))
}
return out
}
// Strict: returns null when the bytes are not valid UTF-8 (so binary data is shown as hex instead of garbage).
function utf8Text(bytes){
let out=""
for(let i=0;i<bytes.length;){
const b=bytes[i]
let n=0,c=0
if(b<0x80){c=b;n=0}
else if(b>=0xc2&&b<0xe0){c=b&31;n=1}
else if(b>=0xe0&&b<0xf0){c=b&15;n=2}
else if(b>=0xf0&&b<0xf5){c=b&7;n=3}
else return null
for(let k=1;k<=n;k++){const t=bytes[i+k];if(t===undefined||(t&0xc0)!==0x80)return null;c=(c<<6)|(t&63)}
if((n===2&&c<0x800)||(n===3&&(c<0x10000||c>0x10ffff))||(c>=0xd800&&c<=0xdfff))return null
out+=String.fromCodePoint(c)
i+=n+1
}
return out
}
function utf16leBytes(s){
const out=[]
const str=String(s||"")
for(let i=0;i<str.length;i++){const c=str.charCodeAt(i);out.push(c&255,c>>8)}
return out
}
function hexOf(bytes){return bytes.map((b)=>(b<16?"0":"")+b.toString(16)).join("")}
function printable(text){return !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text)}
// Decoded bytes as text when they are text, otherwise as a hex dump with a note.
function bytesResult(bytes){
const t=utf8Text(bytes)
if(t!==null&&printable(t))return {ok:true,text:t}
return {ok:true,text:hexOf(bytes).replace(/(..)(?=.)/g,"$1 "),note:"The result is binary, so it is shown as hex."}
}
const B64="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
function b64FromBytes(bytes){
let out=""
for(let i=0;i<bytes.length;i+=3){
const a=bytes[i],b=bytes[i+1],c=bytes[i+2]
out+=B64[a>>2]+B64[((a&3)<<4)|((b||0)>>4)]+(b===undefined?"=":B64[((b&15)<<2)|((c||0)>>6)])+(c===undefined?"=":B64[c&63])
}
return out
}
// Standard and URL-safe alphabets, with or without padding, white space ignored. Returns null when it is not Base64.
function b64ToBytes(text){
const s=String(text||"").replace(/\s+/g,"").replace(/-/g,"+").replace(/_/g,"/").replace(/=+$/,"")
if(!s||/[^A-Za-z0-9+\/]/.test(s)||s.length%4===1)return null
const out=[]
for(let i=0;i<s.length;i+=4){
const n=[0,1,2,3].map((k)=>i+k<s.length?B64.indexOf(s[i+k]):-1)
out.push((n[0]<<2)|(n[1]>>4))
if(n[2]>=0)out.push(((n[1]&15)<<4)|(n[2]>>2))
if(n[3]>=0)out.push(((n[2]&3)<<6)|n[3])
}
return out
}
const HTML_NAMED={amp:"&",lt:"<",gt:">",quot:'"',apos:"'",nbsp:"\u00a0",copy:"\u00a9",reg:"\u00ae",trade:"\u2122",hellip:"\u2026",ndash:"\u2013",mdash:"\u2014",lsquo:"\u2018",rsquo:"\u2019",ldquo:"\u201c",rdquo:"\u201d",euro:"\u20ac",pound:"\u00a3",yen:"\u00a5",cent:"\u00a2",sect:"\u00a7",deg:"\u00b0",middot:"\u00b7",bull:"\u2022",laquo:"\u00ab",raquo:"\u00bb",times:"\u00d7",divide:"\u00f7",tab:"\t",newline:"\n",sol:"/",colon:":",lpar:"(",rpar:")",equals:"=",excl:"!",num:"#",percnt:"%",semi:";",comma:",",period:".",quest:"?",commat:"@",lsqb:"[",rsqb:"]",lcub:"{",rcub:"}",bsol:"\\",grave:"`",verbar:"|",plus:"+",ast:"*",dollar:"$",lowbar:"_",hyphen:"-"}
function htmlEncode(text){
return String(text||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function htmlDecode(text){
return String(text||"").replace(/&(#x[0-9a-f]{1,6}|#\d{1,7}|[a-z][a-z0-9]{1,10});?/gi,(m,e)=>{
if(e[0]==="#"){
const n=/^#x/i.test(e)?parseInt(e.slice(2),16):parseInt(e.slice(1),10)
if(!(n>0&&n<=0x10ffff)||(n>=0xd800&&n<=0xdfff))return m
return String.fromCodePoint(n)
}
const k=e in HTML_NAMED?e:e.toLowerCase()
return Object.prototype.hasOwnProperty.call(HTML_NAMED,k)&&(m.endsWith(";")||["amp","lt","gt","quot"].includes(k))?HTML_NAMED[k]:m
})
}
function urlEncodeAll(text){return utf8Bytes(text).map((b)=>"%"+(b<16?"0":"")+b.toString(16).toUpperCase()).join("")}
function urlDecode(text){
const bytes=[]
const s=String(text||"")
for(let i=0;i<s.length;i++){
if(s[i]==="%"&&/^[0-9a-f]{2}$/i.test(s.substr(i+1,2))){bytes.push(parseInt(s.substr(i+1,2),16));i+=2}
else if(s[i]==="+")bytes.push(32)
else utf8Bytes(s[i]+(s.codePointAt(i)>0xffff?s[++i]:"")).forEach((b)=>bytes.push(b))
}
return bytes
}
// "68656c6c6f", "68 65 6c", "0x68,0x65", "\x68\x65" and "%68%65" are all read as hex bytes.
function hexToBytes(text){
const s=String(text||"").replace(/\\x|0x|%/gi," ").replace(/[\s,:;-]+/g,"")
if(!s||/[^0-9a-f]/i.test(s)||s.length%2)return null
const out=[]
for(let i=0;i<s.length;i+=2)out.push(parseInt(s.substr(i,2),16))
return out
}
const TRANSFORMS=[
{id:"b64e",label:"Base64 encode"},
{id:"b64d",label:"Base64 decode"},
{id:"urle",label:"URL encode"},
{id:"urlall",label:"URL encode every character"},
{id:"urld",label:"URL decode"},
{id:"htmle",label:"HTML entities encode"},
{id:"htmld",label:"HTML entities decode"},
{id:"hexe",label:"Hex encode"},
{id:"hexd",label:"Hex decode"},
{id:"jwt",label:"JWT decode (view)"}
]
// Returns {ok,text,note} or {ok:false,error}. Never throws.
function transform(op,input,now){
const text=String(input===undefined||input===null?"":input)
if(!text)return {ok:false,error:"Nothing to convert."}
if(op==="b64e")return {ok:true,text:b64FromBytes(utf8Bytes(text))}
if(op==="b64d"){const b=b64ToBytes(text);return b&&b.length?bytesResult(b):{ok:false,error:"This is not valid Base64."}}
if(op==="urle"){try{return {ok:true,text:encodeURIComponent(text).replace(/[!'()*]/g,(c)=>"%"+c.charCodeAt(0).toString(16).toUpperCase())}}catch(e){return {ok:false,error:"This text cannot be URL encoded."}}}
if(op==="urlall")return {ok:true,text:urlEncodeAll(text)}
if(op==="urld"){if(!/%[0-9a-f]{2}|\+/i.test(text))return {ok:false,error:"Nothing here is URL encoded."};return bytesResult(urlDecode(text))}
if(op==="htmle")return {ok:true,text:htmlEncode(text)}
if(op==="htmld"){const t=htmlDecode(text);return t===text?{ok:false,error:"No HTML entities found."}:{ok:true,text:t}}
if(op==="hexe")return {ok:true,text:hexOf(utf8Bytes(text))}
if(op==="hexd"){const b=hexToBytes(text);return b?bytesResult(b):{ok:false,error:"This is not hex (pairs of 0-9 a-f)."}}
if(op==="jwt"){const j=jwtDecode(text,now);return j.ok?{ok:true,text:j.pretty,note:j.notes.join(" ")}:{ok:false,error:j.error}}
return {ok:false,error:"Unknown conversion."}
}
// What a selection most likely is, so the panel can open on the useful conversion.
function transformGuess(text){
const t=String(text||"").trim()
if(!t)return "b64e"
if(/^[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*$/.test(t)&&jwtDecode(t).ok)return "jwt"
if(/%[0-9a-f]{2}/i.test(t))return "urld"
if(/&(?:#x?[0-9a-f]+|[a-z]{2,8});/i.test(t))return "htmld"
if(/^(?:[0-9a-f]{2}[\s:]?){4,}$/i.test(t)||/^(?:\\x[0-9a-f]{2}){2,}$/i.test(t))return "hexd"
if(/^[A-Za-z0-9+\/_-]{8,}={0,2}$/.test(t)&&t.replace(/=+$/,"").length%4!==1){const b=b64ToBytes(t);const s=b?utf8Text(b):null;if(s!==null&&printable(s))return "b64d"}
return "b64e"
}
// ---- JWT (decoded for reading only: the signature is not checked)
function fmtTime(sec){
const d=new Date(sec*1000)
return isNaN(d.getTime())?"":d.toISOString().replace("T"," ").replace(/\.\d+Z$/," UTC")
}
function jwtDecode(token,now){
const t=String(token||"").trim().replace(/^Bearer\s+/i,"")
const parts=t.split(".")
if(parts.length<2||parts.length>3||!parts[0]||!parts[1])return {ok:false,error:"A JWT has three parts separated by dots."}
const part=(p)=>{const b=b64ToBytes(p);if(!b)return null;const s=utf8Text(b);if(s===null)return null;try{const o=JSON.parse(s);return o&&typeof o==="object"&&!Array.isArray(o)?o:null}catch(e){return null}}
const header=part(parts[0]),payload=part(parts[1])
if(!header||!payload)return {ok:false,error:"The header or payload is not Base64 encoded JSON."}
const notes=[]
const alg=typeof header.alg==="string"?header.alg:""
if(!alg)notes.push("The header has no alg.")
else if(alg.toLowerCase()==="none")notes.push("alg is none: the token is unsigned.")
else if(/^HS/i.test(alg))notes.push(alg+" is a shared-secret signature: the secret can be attacked offline.")
if(!parts[2]&&alg.toLowerCase()!=="none")notes.push("The signature part is empty.")
const sec=now===undefined?Math.floor(Date.now()/1000):now
if(typeof payload.exp==="number")notes.push(payload.exp<sec?"Expired "+fmtTime(payload.exp)+".":"Valid until "+fmtTime(payload.exp)+".")
else notes.push("No exp claim: the token does not expire.")
if(typeof payload.nbf==="number"&&payload.nbf>sec)notes.push("Not valid before "+fmtTime(payload.nbf)+".")
if(typeof payload.iat==="number")notes.push("Issued "+fmtTime(payload.iat)+".")
if(header.kid!==undefined)notes.push("kid is set: test it for injection and path traversal.")
if(header.jku!==undefined||header.x5u!==undefined||header.jwk!==undefined)notes.push("The header points at its own key (jku / x5u / jwk).")
notes.push("The signature is not verified here.")
const pretty="Header\n"+JSON.stringify(header,null,2)+"\n\nPayload\n"+JSON.stringify(payload,null,2)+"\n\nSignature\n"+(parts[2]||"(none)")
return {ok:true,header,payload,signature:parts[2]||"",alg,notes,pretty}
}
// ---- hashes (plain JS and synchronous: crypto.subtle only exists on secure origins, which the app's local pages are not on every engine, and it has no MD5 or MD4)
function rol(x,n){return (x<<n)|(x>>>(32-n))}
function wordsLE(bytes){
const len=bytes.length
const n=(((len+8)>>6)+1)*16
const w=new Array(n).fill(0)
for(let i=0;i<len;i++)w[i>>2]|=bytes[i]<<((i%4)*8)
w[len>>2]|=0x80<<((len%4)*8)
w[n-2]=(len*8)>>>0
w[n-1]=Math.floor(len/0x20000000)
return w
}
function hexLE(words){
let out=""
words.forEach((w)=>{for(let i=0;i<4;i++){const b=(w>>>(i*8))&255;out+=(b<16?"0":"")+b.toString(16)}})
return out
}
const MD5_K=[]
for(let i=0;i<64;i++)MD5_K[i]=Math.floor(Math.abs(Math.sin(i+1))*4294967296)>>>0
const MD5_S=[7,12,17,22,5,9,14,20,4,11,16,23,6,10,15,21]
function md5Bytes(bytes){
const m=wordsLE(bytes)
let a0=0x67452301,b0=0xefcdab89|0,c0=0x98badcfe|0,d0=0x10325476
for(let o=0;o<m.length;o+=16){
let A=a0,B=b0,C=c0,D=d0
for(let i=0;i<64;i++){
let F,g
if(i<16){F=(B&C)|(~B&D);g=i}
else if(i<32){F=(D&B)|(~D&C);g=(5*i+1)%16}
else if(i<48){F=B^C^D;g=(3*i+5)%16}
else{F=C^(B|~D);g=(7*i)%16}
F=(F+A+MD5_K[i]+m[o+g])|0
A=D;D=C;C=B
B=(B+rol(F,MD5_S[(i>>4)*4+(i%4)]))|0
}
a0=(a0+A)|0;b0=(b0+B)|0;c0=(c0+C)|0;d0=(d0+D)|0
}
return hexLE([a0,b0,c0,d0])
}
const MD4_ORDER=[[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],[0,4,8,12,1,5,9,13,2,6,10,14,3,7,11,15],[0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15]]
const MD4_S=[[3,7,11,19],[3,5,9,13],[3,9,11,15]]
const MD4_K=[0,0x5a827999,0x6ed9eba1]
function md4Bytes(bytes){
const m=wordsLE(bytes)
let a0=0x67452301,b0=0xefcdab89|0,c0=0x98badcfe|0,d0=0x10325476
for(let o=0;o<m.length;o+=16){
let A=a0,B=b0,C=c0,D=d0
for(let r=0;r<3;r++)for(let i=0;i<16;i++){
const F=r===0?(B&C)|(~B&D):r===1?(B&C)|(B&D)|(C&D):B^C^D
const t=rol((A+F+m[o+MD4_ORDER[r][i]]+MD4_K[r])|0,MD4_S[r][i%4])
A=D;D=C;C=B;B=t
}
a0=(a0+A)|0;b0=(b0+B)|0;c0=(c0+C)|0;d0=(d0+D)|0
}
return hexLE([a0,b0,c0,d0])
}
function wordsBE(bytes){
const len=bytes.length
const n=(((len+8)>>6)+1)*16
const w=new Array(n).fill(0)
for(let i=0;i<len;i++)w[i>>2]|=bytes[i]<<(24-(i%4)*8)
w[len>>2]|=0x80<<(24-(len%4)*8)
w[n-2]=Math.floor(len/0x20000000)
w[n-1]=(len*8)>>>0
return w
}
function hexBE(words){return words.map((w)=>("00000000"+(w>>>0).toString(16)).slice(-8)).join("")}
function sha1Bytes(bytes){
const m=wordsBE(bytes)
let h0=0x67452301,h1=0xefcdab89|0,h2=0x98badcfe|0,h3=0x10325476,h4=0xc3d2e1f0|0
const w=new Array(80)
for(let o=0;o<m.length;o+=16){
for(let i=0;i<16;i++)w[i]=m[o+i]
for(let i=16;i<80;i++)w[i]=rol(w[i-3]^w[i-8]^w[i-14]^w[i-16],1)
let a=h0,b=h1,c=h2,d=h3,e=h4
for(let i=0;i<80;i++){
const f=i<20?(b&c)|(~b&d):i<40?b^c^d:i<60?(b&c)|(b&d)|(c&d):b^c^d
const k=i<20?0x5a827999:i<40?0x6ed9eba1:i<60?0x8f1bbcdc:0xca62c1d6
const t=(rol(a,5)+f+e+k+w[i])|0
e=d;d=c;c=rol(b,30);b=a;a=t
}
h0=(h0+a)|0;h1=(h1+b)|0;h2=(h2+c)|0;h3=(h3+d)|0;h4=(h4+e)|0
}
return hexBE([h0,h1,h2,h3,h4])
}
const SHA256_K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]
function ror(x,n){return (x>>>n)|(x<<(32-n))}
function sha256Bytes(bytes){
const m=wordsBE(bytes)
const h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]
const w=new Array(64)
for(let o=0;o<m.length;o+=16){
for(let i=0;i<16;i++)w[i]=m[o+i]
for(let i=16;i<64;i++){
const s0=ror(w[i-15],7)^ror(w[i-15],18)^(w[i-15]>>>3)
const s1=ror(w[i-2],17)^ror(w[i-2],19)^(w[i-2]>>>10)
w[i]=(w[i-16]+s0+w[i-7]+s1)|0
}
let a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],k=h[7]
for(let i=0;i<64;i++){
const t1=(k+(ror(e,6)^ror(e,11)^ror(e,25))+((e&f)^(~e&g))+SHA256_K[i]+w[i])|0
const t2=((ror(a,2)^ror(a,13)^ror(a,22))+((a&b)^(a&c)^(b&c)))|0
k=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0
}
h[0]=(h[0]+a)|0;h[1]=(h[1]+b)|0;h[2]=(h[2]+c)|0;h[3]=(h[3]+d)|0;h[4]=(h[4]+e)|0;h[5]=(h[5]+f)|0;h[6]=(h[6]+g)|0;h[7]=(h[7]+k)|0
}
return hexBE(h)
}
function md5(text){return md5Bytes(utf8Bytes(text))}
function sha1(text){return sha1Bytes(utf8Bytes(text))}
function sha256(text){return sha256Bytes(utf8Bytes(text))}
function ntlm(text){return md4Bytes(utf16leBytes(text))}
function hashes(text){
return [{id:"md5",label:"MD5",value:md5(text)},{id:"sha1",label:"SHA-1",value:sha1(text)},{id:"sha256",label:"SHA-256",value:sha256(text)},{id:"ntlm",label:"NTLM",value:ntlm(text)}]
}
// ---- MITRE ATT&CK (Enterprise), checked against ATT&CK v20.1 (2026-11-05): the techniques that come up in most pentest and red-team notes. id | name | tactic | words that point at it (tools, commands).
const MITRE_RAW=`T1595|Active Scanning|Reconnaissance|scan nessus nuclei nikto
T1592|Gather Victim Host Information|Reconnaissance|
T1589|Gather Victim Identity Information|Reconnaissance|theharvester linkedin emails usernames
T1590|Gather Victim Network Information|Reconnaissance|whois dnsrecon subfinder amass
T1593|Search Open Websites/Domains|Reconnaissance|osint google dork github
T1596|Search Open Technical Databases|Reconnaissance|shodan censys crt.sh
T1598|Phishing for Information|Reconnaissance|
T1583|Acquire Infrastructure|Resource Development|
T1587|Develop Capabilities|Resource Development|msfvenom payload
T1588|Obtain Capabilities|Resource Development|exploit-db searchsploit
T1190|Exploit Public-Facing Application|Initial Access|sqli sqlmap rce lfi rfi ssrf xxe ssti deserialization upload
T1133|External Remote Services|Initial Access|vpn citrix exposed
T1566|Phishing|Initial Access|phish gophish
T1566.001|Spearphishing Attachment|Initial Access|macro maldoc
T1566.002|Spearphishing Link|Initial Access|
T1078|Valid Accounts|Initial Access|default credentials reused password login
T1078.002|Domain Accounts|Initial Access|
T1078.003|Local Accounts|Initial Access|
T1078.004|Cloud Accounts|Initial Access|aws azure gcp
T1189|Drive-by Compromise|Initial Access|
T1195|Supply Chain Compromise|Initial Access|
T1199|Trusted Relationship|Initial Access|
T1059|Command and Scripting Interpreter|Execution|
T1059.001|PowerShell|Execution|powershell iex invoke-expression
T1059.003|Windows Command Shell|Execution|cmd.exe
T1059.004|Unix Shell|Execution|bash reverse shell /bin/sh
T1059.005|Visual Basic|Execution|vbs vba
T1059.006|Python|Execution|
T1059.007|JavaScript|Execution|xss
T1203|Exploitation for Client Execution|Execution|
T1047|Windows Management Instrumentation|Execution|wmiexec wmic
T1053|Scheduled Task/Job|Execution|
T1053.005|Scheduled Task|Execution|schtasks
T1053.003|Cron|Execution|crontab
T1569.002|Service Execution|Execution|psexec sc.exe
T1204|User Execution|Execution|
T1106|Native API|Execution|
T1547.001|Registry Run Keys / Startup Folder|Persistence|
T1543.003|Windows Service|Persistence|
T1136|Create Account|Persistence|
T1136.001|Local Account|Persistence|net user useradd
T1098|Account Manipulation|Persistence|authorized_keys
T1505.003|Web Shell|Persistence|webshell
T1546|Event Triggered Execution|Persistence|
T1574.001|DLL|Stealth|dll hijack search order sideload side-loading
T1037|Boot or Logon Initialization Scripts|Persistence|
T1068|Exploitation for Privilege Escalation|Privilege Escalation|kernel exploit printnightmare dirtycow pwnkit
T1548|Abuse Elevation Control Mechanism|Privilege Escalation|
T1548.001|Setuid and Setgid|Privilege Escalation|suid sgid
T1548.002|Bypass User Account Control|Privilege Escalation|uac
T1548.003|Sudo and Sudo Caching|Privilege Escalation|sudo gtfobins
T1134|Access Token Manipulation|Privilege Escalation|token impersonation potato seimpersonate
T1055|Process Injection|Privilege Escalation|
T1484.001|Group Policy Modification|Privilege Escalation|gpo
T1027|Obfuscated Files or Information|Stealth|
T1036|Masquerading|Stealth|
T1070|Indicator Removal|Stealth|
T1685.005|Clear Windows Event Logs|Defense Impairment|wevtutil
T1070.004|File Deletion|Stealth|
T1112|Modify Registry|Defense Impairment|
T1140|Deobfuscate/Decode Files or Information|Stealth|certutil -decode
T1218|System Binary Proxy Execution|Stealth|lolbas lolbin
T1218.005|Mshta|Stealth|
T1218.010|Regsvr32|Stealth|
T1218.011|Rundll32|Stealth|
T1685|Disable or Modify Tools|Defense Impairment|amsi defender bypass
T1110|Brute Force|Credential Access|hydra medusa
T1110.001|Password Guessing|Credential Access|
T1110.002|Password Cracking|Credential Access|hashcat john
T1110.003|Password Spraying|Credential Access|spray kerbrute
T1110.004|Credential Stuffing|Credential Access|
T1003|OS Credential Dumping|Credential Access|
T1003.001|LSASS Memory|Credential Access|mimikatz lsass procdump sekurlsa nanodump
T1003.002|Security Account Manager|Credential Access|sam
T1003.003|NTDS|Credential Access|ntds.dit ntdsutil
T1003.004|LSA Secrets|Credential Access|
T1003.006|DCSync|Credential Access|secretsdump
T1003.008|/etc/passwd and /etc/shadow|Credential Access|unshadow
T1558|Steal or Forge Kerberos Tickets|Credential Access|rubeus
T1558.001|Golden Ticket|Credential Access|krbtgt
T1558.002|Silver Ticket|Credential Access|
T1558.003|Kerberoasting|Credential Access|kerberoast getuserspns
T1558.004|AS-REP Roasting|Credential Access|asreproast getnpusers
T1552|Unsecured Credentials|Credential Access|
T1552.001|Credentials In Files|Credential Access|config password in file
T1552.002|Credentials in Registry|Credential Access|
T1552.004|Private Keys|Credential Access|id_rsa
T1552.006|Group Policy Preferences|Credential Access|gpp cpassword
T1555|Credentials from Password Stores|Credential Access|keepass lazagne
T1555.003|Credentials from Web Browsers|Credential Access|
T1557|Adversary-in-the-Middle|Credential Access|mitm arp spoof bettercap
T1557.001|Name Resolution Poisoning and SMB Relay|Credential Access|responder ntlmrelayx relay llmnr nbt-ns mdns
T1040|Network Sniffing|Credential Access|wireshark tcpdump
T1187|Forced Authentication|Credential Access|petitpotam printerbug coerce
T1649|Steal or Forge Authentication Certificates|Credential Access|adcs certipy esc1 esc8
T1539|Steal Web Session Cookie|Credential Access|session hijack
T1528|Steal Application Access Token|Credential Access|oauth
T1606.001|Web Cookies|Credential Access|forge cookie jwt
T1212|Exploitation for Credential Access|Credential Access|
T1046|Network Service Discovery|Discovery|nmap masscan rustscan
T1087|Account Discovery|Discovery|
T1087.001|Local Account|Discovery|
T1087.002|Domain Account|Discovery|bloodhound ldapsearch enum4linux
T1069|Permission Groups Discovery|Discovery|net group
T1082|System Information Discovery|Discovery|systeminfo uname linpeas winpeas
T1083|File and Directory Discovery|Discovery|
T1018|Remote System Discovery|Discovery|ping sweep
T1135|Network Share Discovery|Discovery|smbclient smbmap shares
T1057|Process Discovery|Discovery|tasklist
T1016|System Network Configuration Discovery|Discovery|ipconfig ifconfig
T1049|System Network Connections Discovery|Discovery|netstat
T1033|System Owner/User Discovery|Discovery|whoami
T1482|Domain Trust Discovery|Discovery|nltest trusts
T1201|Password Policy Discovery|Discovery|net accounts
T1518.001|Security Software Discovery|Discovery|
T1615|Group Policy Discovery|Discovery|
T1007|System Service Discovery|Discovery|
T1012|Query Registry|Discovery|reg query
T1021|Remote Services|Lateral Movement|
T1021.001|Remote Desktop Protocol|Lateral Movement|rdp xfreerdp
T1021.002|SMB/Windows Admin Shares|Lateral Movement|smbexec admin$ c$
T1021.003|Distributed Component Object Model|Lateral Movement|dcomexec
T1021.004|SSH|Lateral Movement|
T1021.006|Windows Remote Management|Lateral Movement|winrm evil-winrm
T1210|Exploitation of Remote Services|Lateral Movement|eternalblue ms17-010 zerologon
T1570|Lateral Tool Transfer|Lateral Movement|
T1550.002|Pass the Hash|Lateral Movement|pth
T1550.003|Pass the Ticket|Lateral Movement|ptt
T1563|Remote Service Session Hijacking|Lateral Movement|
T1005|Data from Local System|Collection|
T1039|Data from Network Shared Drive|Collection|
T1113|Screen Capture|Collection|screenshot
T1056.001|Keylogging|Collection|
T1560|Archive Collected Data|Collection|
T1114|Email Collection|Collection|
T1213|Data from Information Repositories|Collection|sharepoint confluence
T1119|Automated Collection|Collection|
T1071|Application Layer Protocol|Command and Control|
T1071.001|Web Protocols|Command and Control|
T1071.004|DNS|Command and Control|dnscat
T1105|Ingress Tool Transfer|Command and Control|wget curl certutil upload download
T1090|Proxy|Command and Control|proxychains socks
T1572|Protocol Tunneling|Command and Control|chisel ligolo tunnel port forward
T1573|Encrypted Channel|Command and Control|
T1219|Remote Access Tools|Command and Control|anydesk teamviewer
T1095|Non-Application Layer Protocol|Command and Control|netcat
T1571|Non-Standard Port|Command and Control|
T1102|Web Service|Command and Control|
T1041|Exfiltration Over C2 Channel|Exfiltration|
T1048|Exfiltration Over Alternative Protocol|Exfiltration|
T1567|Exfiltration Over Web Service|Exfiltration|
T1020|Automated Exfiltration|Exfiltration|
T1486|Data Encrypted for Impact|Impact|ransomware
T1490|Inhibit System Recovery|Impact|vssadmin
T1489|Service Stop|Impact|
T1485|Data Destruction|Impact|
T1498|Network Denial of Service|Impact|
T1499|Endpoint Denial of Service|Impact|
T1531|Account Access Removal|Impact|
T1496|Resource Hijacking|Impact|
T1565|Data Manipulation|Impact|`
const MITRE=MITRE_RAW.split("\n").map((l)=>{const p=l.split("|");return {id:p[0],name:p[1],tactic:p[2],keys:p[3]||""}})
const MITRE_BY_ID={}
MITRE.forEach((t)=>{MITRE_BY_ID[t.id]=t})
function mitreNorm(id){
const m=/^\s*t?(\d{4})(?:[.\/](\d{3}))?\s*$/i.exec(String(id||""))
return m?"T"+m[1]+(m[2]?"."+m[2]:""):""
}
function mitreLookup(id){
const k=mitreNorm(id)
const t=k?MITRE_BY_ID[k]:null
if(!t)return null
const parent=k.includes(".")?MITRE_BY_ID[k.split(".")[0]]:null
return {id:t.id,name:t.name,tactic:t.tactic,parent:parent?parent.name:"",full:(parent?parent.name+": ":"")+t.name}
}
function mitreUrl(id){
const k=mitreNorm(id)
return k?"https://attack.mitre.org/techniques/"+k.replace(".","/")+"/":""
}
function mitreSearch(query,limit){
const q=String(query||"").trim().toLowerCase()
const max=limit||40
if(!q)return MITRE.slice(0,max)
const idq=mitreNorm(q)||(/^t?\d{1,4}$/.test(q)?q.toUpperCase().replace(/^(?!T)/,"T"):"")
const a=[],b=[],c=[]
MITRE.forEach((t)=>{
const name=t.name.toLowerCase()
if(idq&&t.id.startsWith(idq))a.push(t)
else if(name.startsWith(q)||name.split(/[\s\/:-]+/).some((w)=>w.startsWith(q))||t.tactic.toLowerCase()===q)b.push(t)
else if((name+" "+t.keys+" "+t.tactic.toLowerCase()).includes(q))c.push(t)
})
return a.concat(b,c).slice(0,max)
}
// Techniques the text points at (tool names, commands, explicit T-ids), best first.
function mitreSuggest(text,limit){
const src=String(text||"").toLowerCase()
if(!src.trim())return []
const hits=[]
MITRE.forEach((t)=>{
let score=0
if(new RegExp("\\b"+t.id.replace(".","\\.")+"(?!\\.?\\d)","i").test(src))score+=10
t.keys.split(/\s+/).filter(Boolean).forEach((k)=>{if(k.length>2&&new RegExp("(?:^|[^a-z0-9])"+k.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+"(?:$|[^a-z0-9])").test(src))score+=2})
if(t.name.length>6&&src.includes(t.name.toLowerCase()))score+=3
if(score)hits.push({t,score})
})
hits.sort((x,y)=>y.score-x.score)
return hits.slice(0,limit||6).map((h)=>h.t)
}
// ---- nmap output to a host / port table (normal and grepable output; only open ports)
function nmapHosts(text){
const hosts=[]
let cur=null
const host=(addr,name)=>{
const key=addr||name||""
cur=hosts.find((h)=>h.key===key)
if(!cur){cur={key,addr:addr||"",name:name||"",ports:[]};hosts.push(cur)}
return cur
}
const add=(port,proto,state,service,version)=>{
const p=parseInt(port,10)
if(!(p>0&&p<65536))return
if(!cur)host("","")
if(cur.ports.some((x)=>x.port===p&&x.proto===proto))return
cur.ports.push({port:p,proto,state,service:String(service||"").replace(/\?$/,""),version:String(version||"").trim()})
}
String(text||"").replace(/\r\n?/g,"\n").split("\n").forEach((line)=>{
let m=/^Nmap scan report for (?:(\S+) \(([^)]+)\)|(\S+))\s*$/i.exec(line.trim())
if(m){if(m[2])host(m[2],m[1]);else host(m[3],"");return}
m=/^\s*(\d{1,5})\/(tcp|udp|sctp)\s+(open(?:\|filtered)?)\s+(\S+)?(?:\s+(.*))?$/i.exec(line)
if(m){add(m[1],m[2].toLowerCase(),m[3].toLowerCase(),m[4],m[5]);return}
m=/^Host:\s+(\S+)\s+\(([^)]*)\)\s+.*?Ports:\s+(.*)$/i.exec(line)
if(m){
host(m[1],m[2])
m[3].split(/\t/)[0].split(/,\s*/).forEach((part)=>{
const f=part.trim().split("/")
if(f.length>=5&&/^open/i.test(f[1]))add(f[0],f[2].toLowerCase(),f[1].toLowerCase(),f[4],f[6])
})
}
})
return hosts.filter((h)=>h.ports.length).map((h)=>({addr:h.addr,name:h.name,ports:h.ports}))
}
function nmapTable(hosts){
const list=hosts||[]
const many=list.length>1||list.some((h)=>h.addr||h.name)
const head=(many?["Host"]:[]).concat(["Port","State","Service","Version"])
const rows=[]
list.forEach((h)=>h.ports.forEach((p,i)=>{
const label=h.addr&&h.name?h.addr+" ("+h.name+")":h.addr||h.name||""
rows.push((many?[i===0?label:""]:[]).concat([p.port+"/"+p.proto,p.state,p.service,p.version]))
}))
return {head,rows}
}
// ---- CVSS 3.1 base score
const CVSS_METRICS=[
{id:"AV",label:"Attack vector",values:[["N","Network",0.85],["A","Adjacent",0.62],["L","Local",0.55],["P","Physical",0.2]]},
{id:"AC",label:"Attack complexity",values:[["L","Low",0.77],["H","High",0.44]]},
{id:"PR",label:"Privileges required",values:[["N","None",0.85],["L","Low",0.62],["H","High",0.27]]},
{id:"UI",label:"User interaction",values:[["N","None",0.85],["R","Required",0.62]]},
{id:"S",label:"Scope",values:[["U","Unchanged",0],["C","Changed",0]]},
{id:"C",label:"Confidentiality",values:[["H","High",0.56],["L","Low",0.22],["N","None",0]]},
{id:"I",label:"Integrity",values:[["H","High",0.56],["L","Low",0.22],["N","None",0]]},
{id:"A",label:"Availability",values:[["H","High",0.56],["L","Low",0.22],["N","None",0]]}
]
function cvssParse(vector){
const out={}
String(vector||"").trim().toUpperCase().split("/").forEach((part)=>{
const m=/^([A-Z]{1,2}):([A-Z])$/.exec(part)
if(!m)return
const def=CVSS_METRICS.find((x)=>x.id===m[1])
if(def&&def.values.some((v)=>v[0]===m[2]))out[m[1]]=m[2]
})
return out
}
function cvssComplete(metrics){return CVSS_METRICS.every((m)=>metrics&&metrics[m.id])}
function cvssVector(metrics){
if(!cvssComplete(metrics))return ""
return "CVSS:3.1/"+CVSS_METRICS.map((m)=>m.id+":"+metrics[m.id]).join("/")
}
function cvssRoundUp(x){
const n=Math.round(x*100000)
return n%10000===0?n/100000:(Math.floor(n/10000)+1)/10
}
// Returns the base score as a string with one decimal ("9.8"), or "" while a metric is missing.
function cvssScore(input){
const mt=typeof input==="string"?cvssParse(input):input||{}
if(!cvssComplete(mt))return ""
const w=(id)=>CVSS_METRICS.find((m)=>m.id===id).values.find((v)=>v[0]===mt[id])[2]
const changed=mt.S==="C"
const pr=mt.PR==="L"?(changed?0.68:0.62):mt.PR==="H"?(changed?0.5:0.27):0.85
const iss=1-(1-w("C"))*(1-w("I"))*(1-w("A"))
const impact=changed?7.52*(iss-0.029)-3.25*Math.pow(iss-0.02,15):6.42*iss
const expl=8.22*w("AV")*w("AC")*pr*w("UI")
if(impact<=0)return "0.0"
return cvssRoundUp(Math.min(changed?1.08*(impact+expl):impact+expl,10)).toFixed(1)
}
// ---- small parsers
// "user:password", "DOMAIN\user:password", "user:password@host" and "user / password" as the fields of a credential.
function parseCredential(text){
const t=String(text||"").trim()
if(!t||/\n/.test(t)||t.length>400)return {host:"",user:"",secret:t.length>400?"":t.replace(/\n[\s\S]*$/,"")}
let m=/^([^\s:@]+(?:\\[^\s:@]+)?):(.+)@([A-Za-z0-9._-]+(?::\d+)?)$/.exec(t)
if(m)return {host:m[3],user:m[1],secret:m[2]}
m=/^([^\s:]{1,80}):(.+)$/.exec(t)
if(m&&/^[a-z][a-z0-9+.-]*$/i.test(m[1])&&/^\/\//.test(m[2]))return {host:"",user:"",secret:t}
if(m)return {host:"",user:m[1],secret:m[2]}
m=/^(\S{1,80})\s*[\/|]\s*(\S.*)$/.exec(t)
if(m)return {host:"",user:m[1],secret:m[2]}
return {host:"",user:"",secret:t}
}
function normExit(v){
const s=String(v===undefined||v===null?"":v).trim()
if(!/^-?\d{1,5}$/.test(s))return ""
return String(parseInt(s,10))
}
return {GROUPS,COMMANDS,MENU_LOCAL,TRANSFORMS,MITRE,CVSS_METRICS,get,group,title,enabledFor,defaultMain,pinnable,normPins,togglePin,barItems,fitCount,moreSections,bubbleItems,bubbleMenuItems,slashItems,menuModel,menuIds,shortcutParse,shortcutMatch,utf8Bytes,utf8Text,b64FromBytes,b64ToBytes,htmlEncode,htmlDecode,urlDecode,hexToBytes,transform,transformGuess,jwtDecode,md5,sha1,sha256,ntlm,hashes,mitreNorm,mitreLookup,mitreUrl,mitreSearch,mitreSuggest,nmapHosts,nmapTable,cvssParse,cvssVector,cvssScore,parseCredential,normExit}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=NotesEd
