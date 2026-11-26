const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...parts)=>fs.readFileSync(path.join(ROOT,...parts),"utf8")
const source=read("UI","js","components","ai-provider-list.js")
const api=new Function(source+"\nreturn {AI_PROVIDER_STATE_GROUPS,aiProviderOptionText,aiProviderGroups,aiPickProvider}")()
let passed=0,failed=0
function check(name,condition,detail){if(condition){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,actual,expected){check(name,JSON.stringify(actual)===JSON.stringify(expected),JSON.stringify(actual)+" != "+JSON.stringify(expected))}
const catalog=[
{kind:"api",label:"Anthropic API",category:"api",state:"setup",reason:"not set up"},
{kind:"ollama",label:"Ollama",category:"local",state:"available",reason:"off"},
{kind:"lmstudio",label:"LM Studio",category:"local",state:"setup",reason:"not installed"},
{kind:"ext:claude",label:"Claude Agent",category:"agent",state:"setup",reason:"not installed"},
{kind:"ext:codex",label:"OpenAI Codex",category:"agent",state:"available",reason:"no API key"},
{kind:"cli:claude_code",label:"Claude Code",category:"cli",state:"setup",reason:"not installed"},
{kind:"cli:codex_cli",label:"Codex CLI",category:"cli",state:"ready",reason:""}]
const groups=api.aiProviderGroups(catalog)
eq("groups in status order",groups.map((group)=>group.label),["Connected","Available","Not set up"])
eq("connected first: the installed Codex CLI",groups[0].options.map((option)=>option.kind),["cli:codex_cli"])
eq("available sorted by category",groups[1].options.map((option)=>option.kind),["ext:codex","ollama"])
eq("not set up sorted by category",groups[2].options.map((option)=>option.kind),["cli:claude_code","ext:claude","api","lmstudio"])
eq("every provider is listed",groups.reduce((total,group)=>total+group.options.length,0),catalog.length)
eq("ready label has the category and no reason",groups[0].options[0].text,"Codex CLI (your CLI)")
eq("other labels carry the reason",groups[1].options.map((option)=>option.text),["OpenAI Codex (agent) - no API key","Ollama (local) - off"])
eq("api label has no tag",api.aiProviderOptionText({label:"Anthropic API",category:"api",state:"ready"}),"Anthropic API")
eq("empty groups are dropped",api.aiProviderGroups([{kind:"api",label:"API",category:"api",state:"ready"}]).map((group)=>group.label),["Connected"])
eq("unknown states and duplicates are dropped",api.aiProviderGroups([{kind:"api",label:"A",category:"api",state:"ready"},{kind:"api",label:"B",category:"api",state:"ready"},{kind:"x",label:"X",category:"api",state:"weird"}]).map((group)=>group.options.map((option)=>option.text)),[["A"]])
eq("nothing gives no groups",api.aiProviderGroups([]),[])
eq("pick the first connected entry",api.aiPickProvider(groups,"","",false),"cli:codex_cli")
eq("a ready default wins over the first entry",api.aiPickProvider(api.aiProviderGroups(catalog.map((entry)=>entry.kind==="ollama"?Object.assign({},entry,{state:"ready"}):entry)),"","ollama",false),"ollama")
eq("a default that is not ready is skipped",api.aiPickProvider(groups,"","ollama",false),"cli:codex_cli")
eq("an automatic pick moves to a connected entry",api.aiPickProvider(groups,"ext:claude","",false),"cli:codex_cli")
eq("the user's own pick is kept even when not ready",api.aiPickProvider(groups,"ext:claude","",true),"ext:claude")
eq("a vanished user pick falls back",api.aiPickProvider(groups,"gone","",true),"cli:codex_cli")
const noneReady=api.aiProviderGroups(catalog.filter((entry)=>entry.state!=="ready"))
eq("nothing ready keeps the current entry",api.aiPickProvider(noneReady,"ollama","",false),"ollama")
eq("nothing ready and no current takes the first",api.aiPickProvider(noneReady,"","",false),"ext:codex")
eq("no groups pick nothing",api.aiPickProvider([],"","",false),"")
const mainHtml=read("UI","windows","main.html")
check("main.html loads the provider list after ext-cli-launch.js and before app.js",mainHtml.indexOf("ext-cli-launch.js")<mainHtml.indexOf("ai-provider-list.js")&&mainHtml.indexOf("ai-provider-list.js")<mainHtml.indexOf("js/app.js"))
const aiJs=read("UI","js","components","ai.js")
check("ai.js builds the list from the catalog",/ai\.provider_catalog/.test(aiJs)&&/aiRenderProviderSelect\(\)/.test(aiJs))
check("ai.js refuses to chat with an entry that is not set up",(aiJs.match(/aiRefuseUnready\(\)/g)||[]).length>=3)
check("a manual pick is remembered",/kindPickedByUser=true/.test(aiJs))
console.log("ai_provider_list: "+passed+" passed, "+failed+" failed")
if(failed)process.exit(1)
