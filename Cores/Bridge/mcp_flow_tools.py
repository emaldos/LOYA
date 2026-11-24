"""MCP tools for building chain diagrams node by node and reading what a run produced. Registered from
mcp_server.build_server() with register(server, check), next to chain_get / chain_create / chain_update / chain_run
(mcp_server.py) and the Run History tools (mcp_chain_history_tools.py). Same rules as the other tool modules:
- every tool calls check(name, args) first (the lock, then AI Roles / ai_service.authorize) and is listed under exactly one
  permission key. No new permission was needed: reading the node catalog, validating a graph and reading a run's node
  output are "Chain Diagrams > Read"; the small edit helpers are "Chain Diagrams > Edit", like chain_update;
- every edit goes through flow_service.ai_update, so the diagram must validate, the chain becomes AI-made and unreviewed
  (the operator reviews it before its next run) and the change is in the audit log;
- text an AI reads is passed through the terminal secret redactor, values under secret-looking keys (passwords, hashes,
  tokens of a target) are hidden (flow_service._redacted / _redacted_deep), and everything is size-capped."""
from Cores.Services import ai_service as _ai
_EXTRA_TOOLS={  # tools added to the permission keys ai_service already has for chain diagrams
    "chain_diagrams_read":["chain_node_types","chain_validate","chain_run_output"],
    "chain_diagrams_edit":["chain_node_add","chain_node_set","chain_node_delete","chain_connect"],
}
def register_permissions():
    for key,tools in _EXTRA_TOOLS.items():
        if key not in _ai.PERMISSION_TOOL_MAP:continue
        for tool in tools:
            if _ai.permission_key(tool) is None:_ai.PERMISSION_TOOL_MAP[key].append(tool)
def all_tool_names():
    return [tool for tools in _EXTRA_TOOLS.values() for tool in tools]
register_permissions()
def register(server,check):
    from Cores.Services import flow_service as _flows
    @server.tool(description="The node types a chain diagram can use. Without `type`: a short, paged list ({type, label, category, ports, description}) - filter with category "
                 "(input, action, logic, math, transform, analysis, app, output, notify, note) or words in query. With type=<id> (several: comma separated, at most 12): that type's full parameter schema - "
                 "output ports, default config, every config field with its type, options, limits and help, the port a failure takes, and the ready-made presets. Read a type's schema before you put it in chain_create / chain_node_add.")
    def chain_node_types(category: str="",type: str="",query: str="",offset: int=0,limit: int=20) -> dict:
        check("chain_node_types",{"category":category,"type":type,"query":query})
        return _flows.ai_node_types(category,type,query,offset,limit)
    @server.tool(description="Check a chain diagram WITHOUT saving it: returns ok, the errors that would make chain_create / chain_update refuse it and the warnings (unreachable nodes, unconnected fail ports ...). "
                 "Pass chain_id when the graph is meant for an existing chain, so sub-chain loops are checked too.")
    def chain_validate(graph: dict,chain_id: int=0) -> dict:
        check("chain_validate",{"chain_id":chain_id,"nodes":len((graph or {}).get("nodes") or []) if isinstance(graph,dict) else 0})
        return _flows.ai_validate(graph,chain_id or None)
    @server.tool(description="Add ONE node to an existing chain's diagram. type is a node type or a preset id from chain_node_types; config holds the keys that differ from the defaults. "
                 "after (a node id) with port (default: that node's first output) also connects the new node behind it and places it to the right (x +300; y +160 per branch) unless you pass x and y. "
                 "The diagram must still validate. Like chain_update this marks the chain AI-made and unreviewed. Returns node_id, edge_id, ok, errors and warnings.")
    def chain_node_add(chain_id: int,type: str,config: dict|None=None,title: str="",after: str="",port: str="",x: float|None=None,y: float|None=None) -> dict:
        check("chain_node_add",{"chain_id":chain_id,"type":type,"title":title,"after":after,"port":port})
        return _flows.ai_node_add(chain_id,type,config,title,x,y,after,port,_ai.client_label())
    @server.tool(description="Change ONE node of an existing chain's diagram: config is merged key by key into the node's config (send only what changes), title, x and y only when given. "
                 "The diagram must still validate; the chain is marked AI-made and unreviewed.")
    def chain_node_set(chain_id: int,node_id: str,config: dict|None=None,title: str="",x: float|None=None,y: float|None=None) -> dict:
        check("chain_node_set",{"chain_id":chain_id,"node_id":node_id,"title":title,"keys":sorted(config)[:20] if isinstance(config,dict) else []})
        return _flows.ai_node_set(chain_id,node_id,config,title,x,y,_ai.client_label())
    @server.tool(description="Delete ONE node (not the Start node) and every connection that touches it from an existing chain's diagram. The chain is marked AI-made and unreviewed.")
    def chain_node_delete(chain_id: int,node_id: str) -> dict:
        check("chain_node_delete",{"chain_id":chain_id,"node_id":node_id})
        return _flows.ai_node_delete(chain_id,node_id,_ai.client_label())
    @server.tool(description="Connect two nodes of an existing chain's diagram: from_node's output port -> to_node's input (port empty = the first output). remove=true deletes that connection instead. "
                 "The chain is marked AI-made and unreviewed.")
    def chain_connect(chain_id: int,from_node: str,to_node: str,port: str="",remove: bool=False) -> dict:
        check("chain_connect",{"chain_id":chain_id,"from_node":from_node,"port":port,"to_node":to_node,"remove":remove})
        return _flows.ai_connect(chain_id,from_node,port,to_node,remove is True,_ai.client_label())
    @server.tool(description="What a chain diagram run (chain_run or chain_dry_run) produced. Without node_id: the run's state, its results list (the values of Return result nodes) and one line per node (state, branch, how much output it has, the variables it set). "
                 "With node_id: that node's stdout and stderr tails, its structured parsed value, the variables it set and, for an HTTP node, status, URL and headers. Secrets are redacted and long values are cut (max_chars, at most 40000). "
                 "The step-by-step log of a run is chain_run_log.")
    def chain_run_output(run_id: str,node_id: str="",max_chars: int=8000) -> dict:
        check("chain_run_output",{"run_id":run_id,"node_id":node_id})
        return _flows.ai_node_output(run_id,node_id,max_chars)   # redacted, secret-keyed values hidden and capped by the service
    return server
