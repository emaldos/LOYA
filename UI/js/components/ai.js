let aiState={enabled:true,open:false,width:380,selectedKind:"",statusTimer:null,chatHistory:[],sending:false,sessionId:null,pricing:null,currentModel:"",activeStreamId:null,cancelRequested:false,lastStreamText:"",genToken:0,attachments:[],notices:[],promptHistory:[],historyIndex:-1,complete:{open:false,items:[],index:0,token:null,seq:0,timer:null}}
const AI_SLASH_COMMANDS=[
{name:"help",args:"",desc:"List these commands",local:true},
{name:"explain",args:"<command or output>",desc:"Explain a command or output - on its own, the terminal selection or last output",argKinds:["command"],argField:"detail"},
{name:"summarize-note",args:"<note>",desc:"Summarise one of your notes",argKinds:["note"],argField:"label"},
{name:"new-note",args:"<what it should cover>",desc:"Have the AI write and save a new note",needsArg:true},
{name:"new-command",args:"<what it should do>",desc:"Have the AI create a saved command",needsArg:true},
{name:"newchain",args:"<what it should do>",desc:"Have the AI draw a chain diagram - it opens in the editor for review and never runs by itself",needsArg:true},
{name:"fix-command",args:"<command>",desc:"Fix a broken command - the fix can go into the terminal",argKinds:["command"],argField:"detail",needsArg:true},
{name:"suggest-next",args:"",desc:"Suggest the next recon step for the live target"},
{name:"run",args:"<command>",desc:"Type a command into the terminal with target values filled in - never runs it",argKinds:["command"],argField:"detail",needsArg:true,local:true},
{name:"target",args:"[name]",desc:"Show the live target, or switch to another one",argKinds:["target"],argField:"label",local:true},
{name:"search",args:"<words>",desc:"Find notes, commands and targets to attach",needsArg:true,local:true}
]
const AI_KIND_LABELS={note:"Note",command:"Command",target:"Target",tag:"Tag",category:"Category"}
function aiParseSlash(text){
const m=/^\/([a-z0-9][a-z0-9_-]*)(?:\s+([\s\S]*))?$/i.exec(String(text||"").trim())
if(!m)return null
const name=m[1].toLowerCase()
return {name:name,arg:(m[2]||"").trim(),command:AI_SLASH_COMMANDS.find((c)=>c.name===name)||null}
}
function aiSlashMatches(query){
const q=String(query||"").toLowerCase()
if(!q)return AI_SLASH_COMMANDS.slice()
const starts=AI_SLASH_COMMANDS.filter((c)=>c.name.startsWith(q))
return starts.concat(AI_SLASH_COMMANDS.filter((c)=>!c.name.startsWith(q)&&(c.name.includes(q)||c.desc.toLowerCase().includes(q))))
}
function aiChainStepCount(chain){
const steps=chain&&chain.steps
return Array.isArray(steps)?steps.length:(parseInt(steps,10)||0)
}
function aiChainMatches(chains,query){
const q=String(query||"").toLowerCase()
const list=(chains||[]).filter((c)=>c&&c.caller&&!AI_SLASH_COMMANDS.some((b)=>b.name===String(c.caller).toLowerCase()))
const hay=(c)=>(String(c.caller)+" "+(c.name||"")+" "+(c.description||"")).toLowerCase()
const starts=list.filter((c)=>String(c.caller).toLowerCase().startsWith(q))
const rest=q?list.filter((c)=>!String(c.caller).toLowerCase().startsWith(q)&&hay(c).includes(q)):[]
return starts.concat(rest).map((c)=>{const n=aiChainStepCount(c);return {kind:"chain",label:"/"+c.caller,detail:"Action chain · "+n+" step"+(n===1?"":"s")+(c.name?" - "+c.name:""),caller:String(c.caller)}})
}
function aiActiveToken(text,caret){
text=String(text||"")
caret=caret===undefined||caret===null?text.length:caret
const before=text.slice(0,caret)
if(text.startsWith("/")&&!/\s/.test(before)){
const end=text.search(/\s/)
return {type:"slash",query:before.slice(1),start:0,end:end<0?text.length:end}
}
const after=text.slice(caret)
if(after&&!/^\s/.test(after))return null
const m=/(^|\s)(@?)([^\s@]*)$/.exec(before)
if(m&&m[2]==="@")return {type:"mention",query:m[3],start:before.length-m[3].length-1,end:caret}
const slashArg=/^\/([a-z][a-z-]*)\s+/i.exec(before)
if(slashArg){
const cmd=AI_SLASH_COMMANDS.find((c)=>c.name===slashArg[1].toLowerCase())
if(cmd&&cmd.argKinds&&caret===text.length)return {type:"arg",query:before.slice(slashArg[0].length),start:slashArg[0].length,end:text.length,kinds:cmd.argKinds,field:cmd.argField}
if(cmd)return null
}
if(m&&m[3].length>=3)return {type:"word",query:m[3],start:before.length-m[3].length,end:caret}
return null
}
function aiApplyCompletion(text,token,insert){
text=String(text||"")
let head=text.slice(0,token.start)+insert
let tail=text.slice(token.end)
if(!insert){head=head.replace(/\s+$/,head.trim()?" ":"");tail=tail.replace(/^\s+/,"")}
const sep=!insert||tail.startsWith(" ")?"":" "
return {text:head+sep+tail,caret:head.length+sep.length}
}
function aiExtractCommand(reply){
const fenced=String(reply||"").match(/```[a-z0-9_-]*\r?\n([\s\S]*?)```/i)
if(!fenced)return ""
for(const raw of fenced[1].split(/\r?\n/)){
const line=raw.trim()
if(!line||line.startsWith("#")||line.startsWith("//"))continue
return line.replace(/^[$>]\s+/,"")
}
return ""
}
function aiHistoryStep(list,index,dir){
if(!list.length)return {index:-1,text:null}
if(index<0&&dir>0)return {index:-1,text:null}
const i=index<0?list.length-1:Math.max(0,index+dir)
if(i>=list.length)return {index:-1,text:""}
return {index:i,text:list[i]}
}
function aiSlashHelpText(){
return "AI commands:\n"+AI_SLASH_COMMANDS.map((c)=>"/"+c.name+(c.args?" "+c.args:"")+" - "+c.desc).join("\n")+"\n\nType @ to attach a note, command or target as context. Up arrow in an empty box recalls earlier prompts."
}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function aiEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// Chain diagram cards (ai-chain-card.js): a ```loya-chain reply, or a chain an AI client made with its tools.
function aiChainAppendCards(wrap,turn,i){
if(typeof aiChainTurnCards==="function")aiChainTurnCards(turn,i).forEach((c)=>wrap.appendChild(c))
}
function aiRenderChat(){
const wrap=document.getElementById("aiChatMessages")
wrap.innerHTML=""
if(!aiState.chatHistory.length&&!aiState.notices.length){
const msg=aiState.selectedKind?"Ask the AI anything about your notes, commands, or targets.":"Enable a provider in Settings to start chatting."
wrap.innerHTML=`<div class="ai-placeholder" id="aiChatEmpty"><i class="icon icon-brain"></i><p>${aiEscapeHtml(msg)}</p></div>`
return
}
const noticesAt=(i)=>aiState.notices.filter((n)=>n.at===i).forEach((n)=>wrap.appendChild(aiNoticeElement(n)))
aiState.chatHistory.forEach((turn,i)=>{
noticesAt(i)
if(turn.role==="tool"){
if((turn.content||"").startsWith("Error:")){
const el=document.createElement("div")
el.className="ai-chat-msg ai-chat-msg-error"
el.textContent=turn.content
wrap.appendChild(el)
}
else aiChainAppendCards(wrap,turn,i)
return
}
const el=document.createElement("div")
el.className="ai-chat-msg ai-chat-msg-"+turn.role
let html=""
const usedTools=turn.tool_calls&&turn.tool_calls.length?turn.tool_calls:(turn.agent_tools||[]).map((n)=>({name:n}))
if(usedTools.length){
const names=usedTools.map((tc)=>tc.name||(tc.function&&tc.function.name)||"").join(", ")
html+=`<div class="ai-chat-tool-note">Used: ${aiEscapeHtml(names)}</div>`
}
const shown=turn.role==="user"&&turn.display!==undefined?turn.display:(turn.role==="assistant"&&typeof aiChainStripBlocks==="function"?aiChainStripBlocks(turn.content):turn.content)
if(shown)html+=aiEscapeHtml(shown)
if(turn.role==="user"&&turn.attachments&&turn.attachments.length)html+=`<div class="ai-chat-attached">${turn.attachments.map((a)=>`<span class="ai-chip ai-chip-static">${aiEscapeHtml((AI_KIND_LABELS[a.kind]||a.kind)+": "+a.label)}</span>`).join("")}</div>`
if(!html){aiChainAppendCards(wrap,turn,i);return}
el.innerHTML=html
if(turn.role==="assistant"&&turn.content&&!(turn.content||"").startsWith("Error:"))el.appendChild(aiReplyActions(turn.content))
wrap.appendChild(el)
aiChainAppendCards(wrap,turn,i)
})
noticesAt(aiState.chatHistory.length)
aiState.notices.filter((n)=>n.at>aiState.chatHistory.length).forEach((n)=>wrap.appendChild(aiNoticeElement(n)))
wrap.scrollTop=wrap.scrollHeight
aiRenderUsage()
}
function aiRenderStreamingPreview(text,status){
const wrap=document.getElementById("aiChatMessages")
let el=document.getElementById("aiStreamPreview")
if(!el){
document.getElementById("aiChatEmpty")?.remove()
el=document.createElement("div")
el.id="aiStreamPreview"
el.className="ai-chat-msg ai-chat-msg-assistant ai-chat-msg-streaming"
wrap.appendChild(el)
}
el.textContent=text||(status?status:"…")
wrap.scrollTop=wrap.scrollHeight
}
function aiClearStreamingPreview(){
const el=document.getElementById("aiStreamPreview")
if(el)el.remove()
}
function aiEstimateTokens(){
let chars=0
aiState.chatHistory.forEach((t)=>{chars+=(t.content||"").length})
return Math.max(0,Math.round(chars/4))
}
function aiRenderUsage(){
const el=document.getElementById("aiUsageLabel")
if(!el)return
const tokens=aiEstimateTokens()
if(!tokens){el.textContent="";return}
let text=`~${tokens.toLocaleString()} tokens`
if(aiState.pricing&&aiState.currentModel){
const rate=aiState.pricing[aiState.currentModel]
if(rate){
const cost=rate*tokens/1000
text+=` · ~$${cost<0.01?cost.toFixed(4):cost.toFixed(2)}`
}
}
el.textContent=text
}
function aiRefreshCurrentModel(){
if(!aiState.selectedKind){aiState.currentModel="";aiRenderUsage();return}
bridgeCall("ai.providers").then((providers)=>{
const cfg=providers[aiState.selectedKind]
aiState.currentModel=(cfg&&cfg.model)||""
aiRenderUsage()
}).catch(()=>{})
}
function aiUpdateSendButton(){
const btn=document.getElementById("aiChatSendBtn")
if(!btn)return
const icon=btn.querySelector(".icon")
if(aiState.sending){
if(icon)icon.className="icon icon-stop"
btn.title="Stop"
}else{
if(icon)icon.className="icon icon-arrow-right"
btn.title="Send"
}
btn.disabled=false
}
function aiStopSending(){
if(!aiState.sending)return
aiState.cancelRequested=true
if(aiState.activeStreamId){
// An external agent is a child process: Stop kills its whole process tree, it does not just stop listening.
if(typeof extIsAgentKind==="function"&&extIsAgentKind(aiState.selectedKind))bridgeCall("extAgents.stop",[aiState.activeStreamId]).catch(()=>{})
else bridgeCall("ai.chat_abort_stream",[aiState.activeStreamId]).catch(()=>{})
}
}
function aiRunChatTurn(text,genToken,attachments,display){
if(typeof aiChainWatchStart==="function")aiChainWatchStart()
const agent=typeof extIsAgentKind==="function"&&extIsAgentKind(aiState.selectedKind)
const skill=aiState.pendingSkill||null
aiState.pendingSkill=null
const startArgs=[aiState.sessionId,aiState.selectedKind,text,(attachments||[]).map((a)=>({kind:a.kind,id:a.id,label:a.label})),display&&display!==text?display:null]
return new Promise((resolve,reject)=>{
bridgeCall(agent?"extAgents.run_start":"ai.chat_send_stream_start",agent?startArgs.concat([skill]):startArgs).then((r)=>{
if(agent&&typeof extAgentsSetRunning==="function")extAgentsSetRunning(true)
if(aiState.genToken===genToken)aiState.sessionId=r.session_id
aiState.activeStreamId=r.stream_id
const poll=()=>{
if(aiState.cancelRequested&&!agent){
resolve({cancelled:true,text:aiState.lastStreamText})
return
}
bridgeCall(agent?"extAgents.run_poll":"ai.chat_send_stream_poll",[r.session_id,aiState.selectedKind,r.stream_id]).then((res)=>{
if(aiState.cancelRequested&&!agent){
resolve({cancelled:true,text:res.text||aiState.lastStreamText})
return
}
if(res.error&&res.done){if(aiState.genToken===genToken)aiClearStreamingPreview();reject(new Error(res.error));return}
aiState.lastStreamText=res.text
if(aiState.genToken===genToken)aiRenderStreamingPreview(res.text,res.status)
if(res.done){
if(aiState.genToken===genToken)aiClearStreamingPreview()
if(agent&&typeof extAgentsSetRunning==="function")extAgentsSetRunning(false)
resolve({cancelled:false,history:res.history||aiState.chatHistory})
return
}
setTimeout(poll,agent?300:150)
}).catch((err)=>{if(aiState.genToken===genToken)aiClearStreamingPreview();if(agent&&typeof extAgentsSetRunning==="function")extAgentsSetRunning(false);reject(err)})
}
poll()
}).catch((err)=>{if(agent&&typeof extAgentsHandleRunError==="function")extAgentsHandleRunError(err);reject(err)})
})
}
function aiChatSend(promptText){
if(aiState.sending)return
const input=document.getElementById("aiChatInput")
const text=(promptText!==undefined?promptText:input.value).trim()
if(!text)return
aiCloseCompletions()
const slash=aiParseSlash(text)
if(slash){
if(!slash.command){
Promise.all([aiChainCallers(true),typeof extAgentSkills==="function"?extAgentSkills(aiState.selectedKind):Promise.resolve([])]).then(([chains,skills])=>{
const chain=(chains||[]).find((ch)=>String(ch.caller||"").toLowerCase()===slash.name)
const skill=!chain&&typeof extFindSkill==="function"?extFindSkill(skills,slash.name):null
if(skill){
aiRememberPrompt(text)
if(promptText===undefined){input.value="";input.style.height="auto"}
aiState.pendingSkill={name:skill.name,args:slash.arg}
aiSendPrompt(text,text,aiTakeAttachments())
return
}
if(!chain){showStatusIsland("Unknown command /"+slash.name+" - type /help","error");return}
aiRememberPrompt(text)
if(promptText===undefined){input.value="";input.style.height="auto"}
aiRunChain(chain.caller)
})
return
}
if(slash.command.needsArg&&!slash.arg&&!aiState.attachments.length){showStatusIsland("/"+slash.name+" needs "+slash.command.args,"error");return}
if(!slash.command.local&&!aiState.selectedKind){aiNoProvider();return}
aiRememberPrompt(text)
if(promptText===undefined){input.value="";input.style.height="auto"}
aiRunSlash(slash)
return
}
if(!aiState.selectedKind){aiNoProvider();return}
aiRememberPrompt(text)
if(promptText===undefined){input.value="";input.style.height="auto"}
// "create a chain that ..." without /newchain: a chat provider gets the authoring guide too (an external agent has the chain_* tools).
if(typeof aiChainIntent==="function"&&aiChainIntent(text)&&!(typeof extIsAgentKind==="function"&&extIsAgentKind(aiState.selectedKind))){aiChainRequest(text,text,aiTakeAttachments());return}
aiSendPrompt(text,text,aiTakeAttachments())
}
function aiNoProvider(){
showStatusIsland("No AI provider is enabled - turn on API, Ollama or LM Studio in Settings > Extensions, or an agent in Settings > AI > Agents","error")
}
function aiTakeAttachments(){
const list=aiState.attachments
aiState.attachments=[]
aiRenderAttachments()
return list
}
function aiSendPrompt(prompt,shown,attachments){
if(aiState.sending)return Promise.reject(new Error("A message is already in progress."))
if(!aiState.selectedKind){aiNoProvider();return Promise.reject(new Error("No AI provider is enabled."))}
attachments=attachments||[]
const turn={role:"user",content:prompt}
if(shown!==prompt||attachments.length){turn.display=shown;turn.attachments=attachments.map((a)=>({kind:a.kind,label:a.label}))}
aiState.chatHistory=[...aiState.chatHistory,turn]
aiRenderChat()
aiState.sending=true
aiState.cancelRequested=false
aiState.lastStreamText=""
aiUpdateSendButton()
showStatusIsland("AI is thinking…")
const genToken=aiState.genToken
return aiRunChatTurn(prompt,genToken,attachments,shown).then((res)=>{
if(aiState.genToken!==genToken)return ""
if(res.cancelled){
if(res.text)aiState.chatHistory=[...aiState.chatHistory,{role:"assistant",content:res.text}]
}else{
aiState.chatHistory=res.history
}
aiRenderChat()
showStatusIsland(res.cancelled?"Stopped":"AI replied","success")
const last=[...aiState.chatHistory].reverse().find((m)=>m.role==="assistant"&&m.content)
return last?last.content:""
}).catch((err)=>{
if(aiState.genToken!==genToken)return ""
aiState.chatHistory=[...aiState.chatHistory,{role:"assistant",content:"Error: "+(err&&err.message?err.message:"Failed to get a response.")}]
aiRenderChat()
showStatusIsland(err&&err.message?err.message:"AI request failed","error")
return ""
}).finally(()=>{
aiState.sending=false
aiState.activeStreamId=null
aiUpdateSendButton()
})
}
function aiNotice(text,items){
aiState.notices.push({at:aiState.chatHistory.length,text:text,items:items||null})
aiRenderChat()
}
function aiNoticeElement(n){
const el=document.createElement("div")
el.className="ai-chat-msg ai-chat-msg-notice"
el.textContent=n.text
if(n.items&&n.items.length){
const list=document.createElement("div")
list.className="ai-notice-items"
n.items.forEach((item)=>{
const b=document.createElement("button")
b.type="button"
b.className="ai-chip"
b.title="Attach as context"
b.textContent=(AI_KIND_LABELS[item.kind]||item.kind)+": "+item.label
b.addEventListener("click",()=>{aiAttach(item);document.getElementById("aiChatInput").focus()})
list.appendChild(b)
})
el.appendChild(list)
}
return el
}
function aiResolveArg(slash,kinds){
const attached=aiState.attachments.find((a)=>kinds.includes(a.kind))
if(attached)return Promise.resolve(attached)
if(!slash.arg)return Promise.resolve(null)
return bridgeCall("ai.complete",[slash.arg,kinds,1]).then((rows)=>(rows&&rows[0])||null)
}
function aiTerminalReady(){
return typeof termStageCommand==="function"&&typeof termState!=="undefined"&&termState.enabled
}
function aiRunSlash(slash){
const arg=slash.arg
const name=slash.name
if(name==="help"){
return aiChainCallers(true).then((chains)=>{
const rows=aiChainMatches(chains,"")
aiNotice(aiSlashHelpText()+(rows.length?"\n\nAction chains:\n"+rows.map((r)=>r.label+" - "+r.detail).join("\n"):""))
})
}
if(name==="explain"){
if(arg)return aiSendPrompt("Explain what this does, for a penetration tester. Be concrete and brief; call out anything risky or noisy.\n\n```\n"+arg+"\n```","/explain "+arg,aiTakeAttachments())
if(aiState.attachments.length)return aiSendPrompt("Explain the attached item(s) for a penetration tester. Be concrete and brief.","/explain",aiTakeAttachments())
if(typeof termAiExplainOutput==="function"&&typeof termFindTab==="function"&&termFindTab(termState.activeId)){
const sel=typeof termOutputSelectionText==="function"?termOutputSelectionText():""
const tab=termFindTab(termState.activeId)
return termAiExplainOutput(sel||termAiLastBlockText(tab),sel?"selected output":"output")
}
showStatusIsland("Nothing to explain - add a command after /explain, attach something with @, or open a terminal session","error");return
}
if(name==="summarize-note"){
return aiResolveArg(slash,["note"]).then((note)=>{
if(!note){showStatusIsland(arg?"No note matches \""+arg+"\"":"Pick a note: /summarize-note <name> or attach one with @","error");return}
const rest=aiTakeAttachments().filter((a)=>!(a.kind===note.kind&&String(a.id)===String(note.id)))
return aiSendPrompt("Summarise the attached note \""+note.label+"\" for a pentest engagement. Keep the key findings, hosts, credentials-handling notes and commands; drop filler. Use short bullet points.","/summarize-note "+note.label,[note].concat(rest))
}).catch((err)=>showStatusIsland(err&&err.message?err.message:"Lookup failed","error"))
}
if(name==="new-note")return aiSendPrompt("Create a new note in LOYA NG with the notes_create tool. What it should cover: "+(arg||"the attached item(s)")+"\nGive it a clear name, a fitting group and tags. For every runnable command, call notes_command_block_html and paste the snippet it returns into the content. Reply with the note's name when it is saved.","/new-note "+arg,aiTakeAttachments())
if(name==="new-command")return aiSendPrompt("Create a saved command in LOYA NG with the commands_create tool. What it should do: "+(arg||"see the attached item(s)")+"\nCall parameter_list first and reuse existing {Placeholder} names for target values. Pick a sensible category and sub-category. Reply with the command you saved.","/new-command "+arg,aiTakeAttachments())
if(name==="newchain"){
if(typeof aiChainRequest!=="function"){showStatusIsland("Chain diagrams are not available","error");return}
return aiChainRequest(arg,"/newchain "+arg,aiTakeAttachments())
}
if(name==="fix-command")return aiSendPrompt("This command is broken or does not do what I want:\n```\n"+(arg||"(see the attached command)")+"\n```\nSay what is wrong in one or two sentences, then give the corrected command alone in a fenced code block. Keep {Placeholder} tokens as they are.","/fix-command "+arg,aiTakeAttachments())
if(name==="suggest-next"){
if(typeof termAiSuggestNext==="function"&&typeof termFindTab==="function"&&termFindTab(termState.activeId)&&!aiState.attachments.length)return termAiSuggestNext()
return bridgeCall("ai.live_target").then((t)=>{
const values=t&&t.values?Object.keys(t.values).map((k)=>k+": "+t.values[k]).join("\n"):""
if(!t||!t.name){showStatusIsland("Set a live target first: /target <name>","error");return}
return aiSendPrompt("Live target \""+t.name+"\":\n"+(values||"(no values yet)")+"\n\nSuggest ONE sensible next recon step for this target. Call commands_list first and prefer one of my saved commands if one fits. Give a one-sentence reason, then the command alone in a fenced code block. Nothing destructive.","/suggest-next",aiTakeAttachments())
}).catch((err)=>showStatusIsland(err&&err.message?err.message:"Could not read the live target","error"))
}
if(name==="run"){
const attached=aiState.attachments.find((a)=>a.kind==="command")
const raw=arg||(attached?attached.detail:"")
if(!raw){showStatusIsland("/run needs a command","error");return}
if(!aiTerminalReady()){showStatusIsland("Enable the Terminal extension in Settings first","error");return}
if(attached&&!arg)aiTakeAttachments()
return bridgeCall("ai.resolve_placeholders",[raw]).catch(()=>raw).then((cmd)=>termStageCommand(cmd).then(()=>aiNotice("Typed into the terminal (not run): "+cmd))).catch((err)=>showStatusIsland(err&&err.message?err.message:"Could not reach the terminal","error"))
}
if(name==="target"){
if(!arg)return bridgeCall("ai.live_target").then((t)=>{
if(!t||!t.name){aiNotice("No live target. Use /target <name> to pick one.");return}
const values=Object.keys(t.values||{}).map((k)=>k+": "+t.values[k]).join("\n")
aiNotice("Live target: "+t.name+(values?"\n"+values:""))
}).catch((err)=>showStatusIsland(err&&err.message?err.message:"Could not read the live target","error"))
return bridgeCall("ai.complete",[arg,["target"],1]).then((rows)=>{
const hit=rows&&rows[0]
if(!hit){showStatusIsland("No target matches \""+arg+"\"","error");return}
return bridgeCall("ai.live_target").then((t)=>{
if(t&&t.name===hit.label){aiNotice("Live target is already "+hit.label);return}
return bridgeCall("targets.set_live_target",[hit.id]).then(()=>aiNotice("Live target is now "+hit.label))
})
}).catch((err)=>showStatusIsland(err&&err.message?err.message:"Could not switch target","error"))
}
if(name==="search"){
return bridgeCall("ai.complete",[arg,null,10]).then((rows)=>{
rows=rows||[]
aiNotice(rows.length?"Matches for \""+arg+"\" - click to attach:":"Nothing matches \""+arg+"\".",rows)
}).catch((err)=>showStatusIsland(err&&err.message?err.message:"Search failed","error"))
}
}
function aiSendExternalPrompt(text){
if(!aiState.selectedKind)return Promise.reject(new Error("Enable an AI provider in Settings first."))
if(aiState.sending)return Promise.reject(new Error("A message is already in progress."))
aiState.chatHistory=[...aiState.chatHistory,{role:"user",content:text}]
aiRenderChat()
aiState.sending=true
aiState.cancelRequested=false
aiState.lastStreamText=""
aiUpdateSendButton()
showStatusIsland("AI is thinking…")
const genToken=aiState.genToken
return aiRunChatTurn(text,genToken).then((res)=>{
const history=res.cancelled?(res.text?[...aiState.chatHistory,{role:"assistant",content:res.text}]:aiState.chatHistory):res.history
if(aiState.genToken===genToken){
aiState.chatHistory=history
aiRenderChat()
showStatusIsland("AI replied","success")
}
const last=[...history].reverse().find((m)=>m.role==="assistant"&&m.content)
return last?last.content:""
}).catch((err)=>{
if(aiState.genToken===genToken){
aiState.chatHistory=[...aiState.chatHistory,{role:"assistant",content:"Error: "+(err&&err.message?err.message:"Failed to get a response.")}]
aiRenderChat()
showStatusIsland(err&&err.message?err.message:"AI request failed","error")
}
throw err
}).finally(()=>{
aiState.sending=false
aiState.activeStreamId=null
aiUpdateSendButton()
})
}
function aiLoadSession(sessionId){
aiState.genToken++
const genToken=aiState.genToken
return bridgeCall("ai.get_session",[sessionId]).then((data)=>{
if(aiState.genToken!==genToken)return
aiState.sessionId=data?data.id:null
aiState.chatHistory=(data&&data.messages)||[]
aiState.notices=[]
aiSeedPromptHistory()
aiRenderChat()
})
}
function aiInitSession(){
return bridgeCall("ai.sessions").then((list)=>{
if(list&&list.length)return aiLoadSession(list[0].id)
aiState.genToken++
aiState.sessionId=null
aiState.chatHistory=[]
aiState.notices=[]
aiRenderChat()
}).catch(()=>{})
}
function aiNewSession(){
aiState.genToken++
const genToken=aiState.genToken
bridgeCall("ai.new_session",[aiState.selectedKind]).then((entry)=>{
if(aiState.genToken!==genToken)return
aiState.sessionId=entry.id
aiState.chatHistory=[]
aiState.notices=[]
aiRenderChat()
}).catch((err)=>showToast(err&&err.message?err.message:"Could not start a new conversation","error"))
}
function aiClearSession(){
if(!aiState.sessionId){aiState.chatHistory=[];aiState.notices=[];aiRenderChat();return}
appConfirm("Clear this chat session? This cannot be undone.",{okLabel:"Clear",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("ai.clear_session",[aiState.sessionId]).then(()=>{
aiState.chatHistory=[]
aiState.notices=[]
aiRenderChat()
}).catch((err)=>showToast(err&&err.message?err.message:"Clear failed","error"))
})
}
function aiFormatSessionDate(iso){
if(!iso)return ""
const d=new Date(iso)
return isNaN(d.getTime())?"":d.toLocaleString()
}
function aiOpenHistoryMenu(){
bridgeCall("ai.sessions").then((sessions)=>{
const pop=document.createElement("div")
pop.className="ai-history-popover glass-panel"
let html='<div class="ai-history-title">Chat Sessions</div><div class="ai-history-list">'
if(!sessions.length){
html+='<div class="ai-history-empty">No saved sessions yet.</div>'
}else{
sessions.forEach((s)=>{
const active=s.id===aiState.sessionId
html+=`<div class="ai-history-row"><button type="button" class="ai-history-open${active?" active":""}" data-id="${aiEscapeHtml(s.id)}"><span class="ai-history-row-title">${aiEscapeHtml(s.title||"New Conversation")}</span><span class="ai-history-row-date">${aiEscapeHtml(aiFormatSessionDate(s.updated_at))}</span></button><button type="button" class="ai-history-delete" data-id="${aiEscapeHtml(s.id)}" title="Delete session"><i class="icon icon-close"></i></button></div>`
})
}
html+='</div><div class="ai-history-actions"><button type="button" id="aiHistoryCloseBtn">Close</button></div>'
pop.innerHTML=html
openModal(pop)
pop.querySelectorAll(".ai-history-open").forEach((btn)=>{
btn.addEventListener("click",()=>{
closeModal()
aiLoadSession(btn.dataset.id)
})
})
pop.querySelectorAll(".ai-history-delete").forEach((btn)=>{
btn.addEventListener("click",(e)=>{
e.stopPropagation()
const doDelete=()=>{
bridgeCall("ai.delete_session",[btn.dataset.id]).then(()=>{
if(btn.dataset.id===aiState.sessionId){aiState.genToken++;aiState.sessionId=null;aiState.chatHistory=[];aiRenderChat()}
aiOpenHistoryMenu()
}).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
}
if(e.shiftKey){doDelete();return}
appConfirm("Delete this chat session? This cannot be undone.",{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
doDelete()
})
})
})
pop.querySelector("#aiHistoryCloseBtn").addEventListener("click",closeModal)
}).catch((err)=>console.error("list sessions failed",err))
}
function aiApplyEnabled(enabled){
aiState.enabled=enabled
document.getElementById("aiToggleBtn").classList.toggle("hidden",!enabled)
if(!enabled&&aiState.open)aiClosePanel()
}
function aiSetStatusDot(status){
const dot=document.getElementById("aiStatusDot")
dot.className="ai-status-dot"+(status==="online"?" online":status==="offline"?" offline":"")
}
function aiPollStatus(){
if(!aiState.selectedKind){aiSetStatusDot("");return}
if(typeof extIsAgentKind==="function"&&extIsAgentKind(aiState.selectedKind)){bridgeCall("extAgents.status",[aiState.selectedKind]).then((r)=>aiSetStatusDot(r&&r.ready?"online":"offline")).catch(()=>aiSetStatusDot("offline"));return}
bridgeCall("ai.test_provider",[aiState.selectedKind]).then((r)=>aiSetStatusDot(r&&r.status==="online"?"online":"offline")).catch(()=>aiSetStatusDot("offline"))
}
function aiStartStatusPolling(){
aiPollStatus()
if(aiState.statusTimer)clearInterval(aiState.statusTimer)
aiState.statusTimer=setInterval(aiPollStatus,10000)
}
function aiStopStatusPolling(){
if(aiState.statusTimer)clearInterval(aiState.statusTimer)
aiState.statusTimer=null
}
function aiPopulateProviderSelect(){
const select=document.getElementById("aiProviderSelect")
const agentsCall=typeof extProviderGroups==="function"?bridgeCall("extAgents.enabled").catch(()=>[]):Promise.resolve([])
return Promise.all([bridgeCall("ai.enabled_providers"),bridgeCall("ai.get_default"),agentsCall]).then(([list,defaultKind,agents])=>{
select.innerHTML=""
if(agents&&agents.length){
const groups=extProviderGroups(list,agents)
select.disabled=false
groups.forEach((g)=>{
const og=document.createElement("optgroup")
og.label=g.label
g.options.forEach((o)=>{const opt=document.createElement("option");opt.value=o.kind;opt.textContent=o.label;og.appendChild(opt)})
select.appendChild(og)
})
const pick=extPickProvider(groups,aiState.selectedKind,defaultKind)
select.value=pick
aiState.selectedKind=pick
if(typeof extAgentsOnProviderChange==="function")extAgentsOnProviderChange(pick)
return
}
if(!list.length){
const opt=document.createElement("option")
opt.value=""
opt.textContent="No providers enabled"
select.appendChild(opt)
select.disabled=true
aiState.selectedKind=""
aiSetStatusDot("")
return
}
select.disabled=false
list.forEach((p)=>{
const opt=document.createElement("option")
opt.value=p.kind
opt.textContent=p.label
select.appendChild(opt)
})
const pick=list.some((p)=>p.kind===aiState.selectedKind)?aiState.selectedKind:(list.some((p)=>p.kind===defaultKind)?defaultKind:list[0].kind)
select.value=pick
aiState.selectedKind=pick
if(typeof extAgentsOnProviderChange==="function")extAgentsOnProviderChange(pick)
}).then(aiRenderChat)
}
function aiOpenPanel(){
aiState.open=true
document.getElementById("aiPanel").classList.remove("hidden")
document.getElementById("aiToggleBtn").classList.add("active")
document.getElementById("bottomNavRow").classList.add("ai-open")
let p
if(!aiState.sessionId&&!aiState.chatHistory.length){
p=aiInitSession().then(()=>aiPopulateProviderSelect().then(aiStartStatusPolling))
}else{
p=aiPopulateProviderSelect().then(aiStartStatusPolling)
}
return p.then(aiRefreshCurrentModel)
}
function aiClosePanel(){
aiState.open=false
document.getElementById("aiPanel").classList.add("hidden")
document.getElementById("aiToggleBtn").classList.remove("active")
document.getElementById("bottomNavRow").classList.remove("ai-open")
aiStopStatusPolling()
}
function aiTogglePanel(){
if(aiState.open)aiClosePanel()
else aiOpenPanel()
}
function aiRefreshEnabled(){
bridgeCall("ai.get_settings").then((s)=>aiApplyEnabled(s.enabled)).catch(()=>{})
}
// Resizing and docking (left/right/bottom, drag-to-dock) live in ai-dock.js.
function aiWireResize(){
aiDockWire()
}
function initAI(){
bridgeCall("ai.get_settings").then((s)=>{
aiApplyEnabled(s.enabled)
aiDockInit(s)
}).catch((err)=>console.error("ai init failed",err))
document.getElementById("aiToggleBtn").addEventListener("click",aiTogglePanel)
document.getElementById("aiCloseBtn").addEventListener("click",aiClosePanel)
document.getElementById("aiHistoryBtn").addEventListener("click",aiOpenHistoryMenu)
document.getElementById("aiNewSessionBtn").addEventListener("click",aiNewSession)
document.getElementById("aiClearSessionBtn").addEventListener("click",aiClearSession)
document.getElementById("aiProviderSelect").addEventListener("change",(e)=>{
aiState.selectedKind=e.target.value
if(typeof extAgentsOnProviderChange==="function")extAgentsOnProviderChange(aiState.selectedKind)
aiPollStatus()
aiRenderChat()
aiRefreshCurrentModel()
})
bridgeCall("ai.pricing_table").then((table)=>{aiState.pricing=table;aiRenderUsage()}).catch(()=>{})
document.getElementById("aiChatSendBtn").addEventListener("click",()=>{
if(aiState.sending)aiStopSending()
else aiChatSend()
})
aiUpdateSendButton()
const chatInput=document.getElementById("aiChatInput")
chatInput.placeholder="Ask the AI…  / for commands, @ to attach"
chatInput.addEventListener("keydown",aiInputKeydown)
chatInput.addEventListener("input",()=>{
chatInput.style.height="auto"
chatInput.style.height=Math.min(100,chatInput.scrollHeight)+"px"
aiState.historyIndex=-1
aiScheduleCompletions()
})
chatInput.addEventListener("blur",()=>setTimeout(()=>{if(document.activeElement!==chatInput)aiCloseCompletions()},150))
aiBuildInputChrome()
aiStartApprovalWatch()
aiWireResize()
}
function aiBuildInputChrome(){
const row=document.querySelector("#aiPanel .ai-chat-input-row")
if(!row||document.getElementById("aiAttachRow"))return
const attach=document.createElement("div")
attach.id="aiAttachRow"
attach.className="ai-attach-row hidden"
row.parentNode.insertBefore(attach,row)
const pop=document.createElement("div")
pop.id="aiCompletePopup"
pop.className="ai-complete-popup hidden"
pop.setAttribute("role","listbox")
pop.addEventListener("mousedown",(e)=>e.preventDefault())
pop.addEventListener("click",(e)=>{
const opt=e.target.closest(".ai-complete-item")
if(!opt)return
aiState.complete.index=parseInt(opt.dataset.index,10)||0
aiAcceptCompletion()
})
row.appendChild(pop)
}
function aiAttach(item){
if(!item||aiState.attachments.some((a)=>a.kind===item.kind&&String(a.id)===String(item.id)))return
if(aiState.attachments.length>=6){showStatusIsland("Up to 6 items can be attached","error");return}
aiState.attachments=[...aiState.attachments,{kind:item.kind,id:item.id,label:item.label,detail:item.detail||""}]
aiRenderAttachments()
}
function aiRenderAttachments(){
const row=document.getElementById("aiAttachRow")
if(!row)return
row.innerHTML=""
row.classList.toggle("hidden",!aiState.attachments.length)
aiState.attachments.forEach((a,i)=>{
const chip=document.createElement("span")
chip.className="ai-chip"
chip.title=a.detail||a.label
chip.innerHTML=`<span class="ai-chip-kind">${aiEscapeHtml(AI_KIND_LABELS[a.kind]||a.kind)}</span><span class="ai-chip-label">${aiEscapeHtml(a.label)}</span><button type="button" class="ai-chip-remove" title="Remove"><i class="icon icon-close"></i></button>`
chip.querySelector(".ai-chip-remove").addEventListener("click",()=>{
aiState.attachments=aiState.attachments.filter((_,j)=>j!==i)
aiRenderAttachments()
})
row.appendChild(chip)
})
}
function aiSeedPromptHistory(){
aiState.promptHistory=aiState.chatHistory.filter((t)=>t.role==="user").map((t)=>t.display!==undefined?t.display:t.content).filter((t)=>t&&t.length<2000).slice(-50)
aiState.historyIndex=-1
}
function aiRememberPrompt(text){
const list=aiState.promptHistory.filter((t)=>t!==text)
list.push(text)
aiState.promptHistory=list.slice(-50)
aiState.historyIndex=-1
}
function aiInputKeydown(e){
const input=e.target
const c=aiState.complete
if(c.open&&c.items.length){
if(e.key==="ArrowDown"){e.preventDefault();c.index=(c.index+1)%c.items.length;c.navigated=true;aiRenderCompletions();return}
if(e.key==="ArrowUp"){e.preventDefault();c.index=(c.index-1+c.items.length)%c.items.length;c.navigated=true;aiRenderCompletions();return}
if(e.key==="Tab"||(e.key==="Enter"&&!e.shiftKey&&(c.token.type!=="word"||c.navigated))){e.preventDefault();aiAcceptCompletion();return}
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();aiCloseCompletions();return}
}
if((e.key==="ArrowUp"||e.key==="ArrowDown")&&!e.shiftKey&&(!input.value||aiState.historyIndex>=0)){
const step=aiHistoryStep(aiState.promptHistory,aiState.historyIndex,e.key==="ArrowUp"?-1:1)
if(step.text!==null){
e.preventDefault()
aiState.historyIndex=step.index
input.value=step.text
input.setSelectionRange(input.value.length,input.value.length)
input.style.height="auto"
input.style.height=Math.min(100,input.scrollHeight)+"px"
}
return
}
if(e.key==="Escape"&&aiState.sending){e.preventDefault();aiStopSending();return}
if(e.key==="Backspace"&&!input.value&&aiState.attachments.length){aiState.attachments=aiState.attachments.slice(0,-1);aiRenderAttachments();return}
if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();if(!aiState.sending)aiChatSend()}
}
function aiScheduleCompletions(){
const c=aiState.complete
if(c.timer)clearTimeout(c.timer)
c.timer=setTimeout(aiUpdateCompletions,110)
}
function aiUpdateCompletions(){
const input=document.getElementById("aiChatInput")
const c=aiState.complete
const token=aiActiveToken(input.value,input.selectionStart)
const seq=++c.seq
if(!token){aiCloseCompletions();return}
if(token.type==="slash"){
const rows=aiSlashMatches(token.query).map((cmd)=>({kind:"slash",label:"/"+cmd.name,detail:cmd.args?cmd.args+" - "+cmd.desc:cmd.desc,cmd:cmd}))
// With no built-in match, wait for chains/agent skills: closing the popup here would bump the sequence and drop them.
if(rows.length)aiShowCompletions(token,rows)
Promise.all([aiChainCallers(),typeof extAgentSkills==="function"?extAgentSkills(aiState.selectedKind):Promise.resolve([])]).then(([chains,skills])=>{
if(seq!==c.seq)return
const chainRows=aiChainMatches(chains,token.query)
const taken=AI_SLASH_COMMANDS.map((x)=>x.name).concat((chains||[]).map((x)=>String(x.caller||"")))
const skillRows=typeof extSkillMatches==="function"?extSkillMatches(skills,token.query,taken):[]
const all=typeof extMergeSlashRows==="function"?extMergeSlashRows(rows,chainRows,skillRows):rows.concat(chainRows)
if(all.length!==rows.length||!rows.length)aiShowCompletions(token,all)
})
return
}
const kinds=token.type==="mention"?null:token.type==="arg"?token.kinds:["command","tag","category"]
bridgeCall("ai.complete",[token.query,kinds,8]).then((rows)=>{
if(seq!==c.seq)return
rows=rows||[]
if(token.type==="word"){
const q=token.query.toLowerCase()
rows=rows.filter((r)=>r.label.toLowerCase().startsWith(q)&&r.label.toLowerCase()!==q).slice(0,6)
}
aiShowCompletions(token,rows)
}).catch(()=>{if(seq===c.seq)aiCloseCompletions()})
}
function aiShowCompletions(token,rows){
const c=aiState.complete
if(!rows.length){aiCloseCompletions();return}
c.token=token
c.items=rows
c.index=0
c.navigated=false
c.open=true
aiRenderCompletions()
}
function aiRenderCompletions(){
const pop=document.getElementById("aiCompletePopup")
if(!pop)return
const c=aiState.complete
const type=c.token?c.token.type:""
const hint=type==="mention"?"Attach as context":type==="slash"?"Commands":type==="arg"?"Fill in":"Complete"
pop.innerHTML=`<div class="ai-complete-head">${hint}<span>${type==="word"?"Tab":"Tab/Enter"} · Esc</span></div>`+c.items.map((r,i)=>`<div class="ai-complete-item${i===c.index?" active":""}" role="option" data-index="${i}"><span class="ai-complete-kind">${aiEscapeHtml(r.kind==="slash"?"cmd":r.kind==="chain"?"chain":r.kind==="agent-skill"?"agent":(AI_KIND_LABELS[r.kind]||r.kind))}</span><span class="ai-complete-label">${aiEscapeHtml(r.label)}</span>${r.detail?`<span class="ai-complete-detail">${aiEscapeHtml(r.detail)}</span>`:""}</div>`).join("")
pop.classList.remove("hidden")
const active=pop.querySelector(".ai-complete-item.active")
if(active)active.scrollIntoView({block:"nearest"})
}
function aiCloseCompletions(){
const c=aiState.complete
c.open=false
c.items=[]
c.token=null
c.seq++
if(c.timer){clearTimeout(c.timer);c.timer=null}
const pop=document.getElementById("aiCompletePopup")
if(pop){pop.classList.add("hidden");pop.innerHTML=""}
}
function aiAcceptCompletion(){
const c=aiState.complete
const item=c.items[c.index]
const token=c.token
const input=document.getElementById("aiChatInput")
if(!item||!token){aiCloseCompletions();return}
if(item.kind==="chain"){
aiCloseCompletions()
input.value=""
input.style.height="auto"
aiRememberPrompt(item.label)
aiRunChain(item.caller)
return
}
let insert
if(item.kind==="agent-skill"){
const out=aiApplyCompletion(input.value,token,item.label)
input.value=out.text
input.focus()
input.setSelectionRange(out.caret,out.caret)
aiCloseCompletions()
return
}
if(token.type==="slash")insert=item.label
else if(token.type==="mention"){aiAttach(item);insert=""}
else if(token.type==="arg")insert=token.field==="detail"&&item.detail?item.detail:item.label
else insert=item.label
const out=aiApplyCompletion(input.value,token,insert)
input.value=out.text
input.focus()
input.setSelectionRange(out.caret,out.caret)
aiCloseCompletions()
if(token.type==="slash"&&item.cmd&&!item.cmd.args)return
if(token.type==="slash"&&item.cmd&&item.cmd.argKinds)aiScheduleCompletions()
}
function aiReplyActions(text){
const bar=document.createElement("div")
bar.className="ai-reply-actions"
const command=aiExtractCommand(typeof aiChainStripBlocks==="function"?aiChainStripBlocks(text):text)
const add=(label,icon,title,fn)=>{
const b=document.createElement("button")
b.type="button"
b.className="ai-reply-btn"
b.title=title
b.innerHTML=`<i class="icon icon-${icon}"></i><span>${label}</span>`
b.addEventListener("click",fn)
bar.appendChild(b)
}
add("Copy","copy","Copy the reply",()=>{if(navigator.clipboard)navigator.clipboard.writeText(text).then(()=>showToast("Copied")).catch(()=>showToast("Copy failed","error"))})
if(command)add("To terminal","command-line","Type the suggested command into the terminal - it is not run",()=>{
if(!aiTerminalReady()){showToast("Enable the Terminal extension in Settings first","error");return}
termStageCommand(command).catch((err)=>showToast(err&&err.message?err.message:"Could not reach the terminal","error"))
})
add("To note","save","Save the reply into a note",()=>aiSaveReplyToNote(text))
return bar
}
function aiSaveReplyToNote(text){
const title="AI reply - "+new Date().toLocaleString()
if(typeof termOpenNotePicker==="function"){termOpenNotePicker(title,text);return}
bridgeCall("notes.save",[null,title,"AI","<pre>"+aiEscapeHtml(text)+"</pre>",[],"ai"]).then(()=>showToast("Saved as a new note")).catch((err)=>showToast(err&&err.message?err.message:"Save failed","error"))
}
function aiChainCallers(fresh){
if(typeof loyaChainCallers!=="function")return Promise.resolve([])
const cache=aiState.chainCache
if(!fresh&&cache&&Date.now()-cache.at<5000)return Promise.resolve(cache.list)
return Promise.resolve().then(()=>loyaChainCallers()).then((list)=>{
list=Array.isArray(list)?list:[]
aiState.chainCache={at:Date.now(),list:list}
return list
}).catch(()=>[])
}
function aiRunChain(caller){
if(typeof loyaRunChainByCaller!=="function"){showStatusIsland("Action chains are not available","error");return}
// The notice follows the outcome: a run the user cancels in the confirmation (or that never starts) must not read "Running".
Promise.resolve().then(()=>loyaRunChainByCaller(caller,{source:"ai"})).then((res)=>{
if(res&&res.started===false){if(res.reason!=="unknown-caller")aiNotice("Action chain /"+caller+" was not run.");return}
aiNotice("Running action chain /"+caller+" - progress shows in the chain runner.")
}).catch((err)=>showStatusIsland(err&&err.message?err.message:"The action chain did not start","error"))
}
const AI_LEVEL_LABELS={allow:"Allow",ask:"Ask",deny:"Deny"}
function aiRolesMount(root){
if(!root)return Promise.resolve()
aiState.rolesRoot=root
return Promise.all([bridgeCall("ai.roles_state"),bridgeCall("ai.activity",[15]).catch(()=>[])]).then(([state,activity])=>aiRenderRoles(root,state,activity)).catch((err)=>{root.innerHTML=`<div class="set-status error">${aiEscapeHtml(err&&err.message?err.message:"Could not load AI Roles")}</div>`})
}
function aiRolesStatus(msg,isError){
const el=aiState.rolesRoot&&aiState.rolesRoot.querySelector(".ai-roles-status")
if(!el)return
el.textContent=msg||""
el.classList.toggle("error",!!isError)
}
function aiRolesEntities(rows){
const map=new Map()
rows.forEach((r)=>{
if(!map.has(r.entity))map.set(r.entity,{entity:r.entity,shell:false,cells:{}})
const e=map.get(r.entity)
e.cells[r.action]=r
if(r.is_shell)e.shell=true
})
return [...map.values()]
}
function aiRenderRoles(root,state,activity){
const presetBtns=state.presets.map((p)=>`<button type="button" class="ai-role-preset${state.preset===p.id?" active":""}" data-preset="${aiEscapeHtml(p.id)}" title="${aiEscapeHtml(p.description)}"><span class="ai-role-preset-name">${aiEscapeHtml(p.label)}</span><span class="ai-role-preset-desc">${aiEscapeHtml(p.description)}</span></button>`).join("")+`<div class="ai-role-preset ai-role-preset-custom${state.preset==="custom"?" active":""}"><span class="ai-role-preset-name">Custom</span><span class="ai-role-preset-desc">Any other mix - change a cell below and the role becomes Custom.</span></div>`
const levelSelect=(row)=>`<select class="ai-role-level ai-role-level-${row.level}" data-key="${aiEscapeHtml(row.key)}" title="${aiEscapeHtml(row.tools.join(", "))}">${state.levels.map((l)=>`<option value="${l}"${row.level===l?" selected":""}>${AI_LEVEL_LABELS[l]||l}</option>`).join("")}</select>${row.session_grant?'<span class="ai-role-grant" title="Allowed for this session">session</span>':""}`
const body=aiRolesEntities(state.rows).map((e)=>`<tr${e.shell?' class="ai-role-shell"':""}><td class="set-entity-cell">${aiEscapeHtml(e.entity)}${e.shell?' <span class="set-danger-pill">Shell</span>':""}</td>${state.actions.map((a)=>`<td class="ai-role-cell">${e.cells[a]?levelSelect(e.cells[a]):'<span class="ai-role-none">-</span>'}</td>`).join("")}</tr>`).join("")
const grants=state.session_grants.length?state.session_grants.map((g)=>`<span class="ai-chip">${aiEscapeHtml(g.entity+" > "+g.action)}<button type="button" class="ai-chip-remove" data-revoke="${aiEscapeHtml(g.key)}" title="Revoke"><i class="icon icon-close"></i></button></span>`).join("")+'<button type="button" class="set-btn" data-revoke-all="1">Revoke all</button>':'<span class="ai-role-muted">None. Choosing "Allow for this session" on an approval prompt adds one here; they end when the app closes.</span>'
const acts=(activity||[]).length?(activity||[]).map((a)=>`<li class="${a.success?"":"failed"}"><span class="ai-act-time">${aiEscapeHtml(aiFormatSessionDate(a.ts))}</span><span class="ai-act-detail">${aiEscapeHtml(a.detail)}</span></li>`).join(""):'<li class="ai-role-muted">No AI tool calls yet.</li>'
root.innerHTML=`<div class="ai-roles">
<div class="ai-role-presets">${presetBtns}</div>
<p class="set-info"><b>Allow</b> runs without asking. <b>Ask</b> stops and shows you an approval prompt in the app. <b>Deny</b> blocks it. Nothing above Read can be more open than Read. Every check is enforced in the backend for both the in-app chat and external MCP clients, and every AI tool call is written to the audit log.</p>
<div class="set-table-wrap"><table class="set-table set-table-airoles"><thead><tr><th>Entity</th>${state.actions.map((a)=>`<th class="set-col-perm">${aiEscapeHtml(a)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>
<div class="ai-role-sub">Session grants</div>
<div class="ai-role-grants">${grants}</div>
<div class="ai-role-sub">Recent AI activity <button type="button" class="set-btn" data-refresh="1">Refresh</button></div>
<ul class="ai-activity">${acts}</ul>
<div class="set-status ai-roles-status"></div>
</div>`
root.querySelectorAll("[data-preset]").forEach((b)=>b.addEventListener("click",()=>{
const label=b.querySelector(".ai-role-preset-name").textContent
bridgeCall("ai.apply_preset",[b.dataset.preset]).then(()=>aiRolesMount(root)).then(()=>aiRolesStatus("Role set to "+label+".",false)).catch((err)=>aiRolesStatus(err&&err.message?err.message:"Failed",true))
}))
root.querySelectorAll(".ai-role-level").forEach((sel)=>sel.addEventListener("change",()=>{
const row=state.rows.find((r)=>r.key===sel.dataset.key)
const risky=sel.value!=="deny"&&row&&(row.is_shell||row.is_delete)
const go=()=>bridgeCall("ai.set_permission_levels",[{[sel.dataset.key]:sel.value}]).then(()=>aiRolesMount(root)).then(()=>aiRolesStatus(row?row.entity+" > "+row.action+" set to "+(AI_LEVEL_LABELS[sel.value]||sel.value)+".":"Saved.",false)).catch((err)=>{aiRolesStatus(err&&err.message?err.message:"Failed",true);aiRolesMount(root)})
if(!risky||typeof appConfirm!=="function"){go();return}
appConfirm(row.is_shell?"This lets the AI "+(sel.value==="allow"?"":"ask to ")+"use a shell on this machine ("+row.entity+" > "+row.action+"). Scan output the model reads can contain instructions aimed at it. Continue?":"This lets the AI "+(sel.value==="allow"?"":"ask to ")+"delete "+row.entity.toLowerCase()+". Continue?",{okLabel:AI_LEVEL_LABELS[sel.value],danger:true}).then((yes)=>{if(yes)go();else aiRolesMount(root)})
}))
root.querySelectorAll("[data-revoke]").forEach((b)=>b.addEventListener("click",()=>bridgeCall("ai.revoke_session_grant",[b.dataset.revoke]).then(()=>aiRolesMount(root)).catch(()=>{})))
const all=root.querySelector("[data-revoke-all]")
if(all)all.addEventListener("click",()=>bridgeCall("ai.revoke_session_grant",[null]).then(()=>aiRolesMount(root)).catch(()=>{}))
root.querySelector("[data-refresh]").addEventListener("click",()=>aiRolesMount(root))
}
function aiStartApprovalWatch(){
if(aiState.approvalTimer)return
aiState.approvalShown=null
aiState.approvalTimer=setInterval(aiCheckApprovals,1500)
}
function aiCheckApprovals(){
if(aiState.approvalBusy)return
aiState.approvalBusy=true
bridgeCall("ai.pending_approvals").then((rows)=>{
rows=rows||[]
const shown=aiState.approvalShown
if(shown&&!rows.some((r)=>r.id===shown)){aiCloseApproval();showStatusIsland("An AI approval request expired","error")}
if(!aiState.approvalShown&&rows.length)aiShowApproval(rows[0],rows.length)
}).catch(()=>{}).finally(()=>{aiState.approvalBusy=false})
}
function aiCloseApproval(){
const el=document.getElementById("aiApprovalDialog")
if(el)el.remove()
aiState.approvalShown=null
}
function aiShowApproval(req,count){
aiCloseApproval()
aiState.approvalShown=req.id
const el=document.createElement("div")
el.id="aiApprovalDialog"
el.className="ai-approval"
el.setAttribute("role","alertdialog")
const secs=Math.max(0,Math.round(req.expires-Date.now()/1000))
el.innerHTML=`<div class="ai-approval-card"><div class="ai-approval-title"><i class="icon icon-brain"></i>${aiEscapeHtml(req.client&&req.client!=="LOYA AI"?req.client:"The AI")} wants to: ${aiEscapeHtml(req.entity+" > "+req.action)}</div>
<div class="ai-approval-tool">${aiEscapeHtml(req.tool)}${req.client?" · requested by "+aiEscapeHtml(req.client):""}</div>
${req.summary?`<pre class="ai-approval-args">${aiEscapeHtml(req.summary)}</pre>`:""}
${req.reason?`<div class="ai-approval-reason"><b>The agent's stated reason:</b> ${aiEscapeHtml(req.reason)}</div>`:""}
<div class="ai-approval-note">AI Roles has this set to Ask. Unanswered requests are denied in about ${Math.ceil(secs/60)} min.${count>1?" "+(count-1)+" more waiting.":""}</div>
<div class="ai-approval-actions"><button type="button" data-d="deny" class="ai-approval-deny">Deny</button><button type="button" data-d="session" title="Allow ${aiEscapeHtml(req.entity+" > "+req.action)} without asking until the app closes">Allow for this session</button><button type="button" data-d="once" class="ai-approval-allow">Allow once</button></div></div>`
el.querySelectorAll("[data-d]").forEach((b)=>b.addEventListener("click",()=>{
const d=b.dataset.d
el.querySelectorAll("button").forEach((x)=>{x.disabled=true})
bridgeCall("ai.resolve_approval",[req.id,d]).then(()=>{
showStatusIsland(d==="deny"?"Denied":d==="session"?"Allowed for this session":"Allowed once",d==="deny"?"error":"success")
if(aiState.rolesRoot&&document.body.contains(aiState.rolesRoot))aiRolesMount(aiState.rolesRoot)
}).catch(()=>{}).finally(()=>{aiCloseApproval();aiCheckApprovals()})
}))
document.body.appendChild(el)
const allow=el.querySelector(".ai-approval-allow")
if(allow)allow.focus()
}
