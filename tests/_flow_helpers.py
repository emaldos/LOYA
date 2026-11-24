"""Shared helpers for the Chain Diagrams tests: tiny graph builders and a live target written into the isolated Data dir."""
import json,os,sys,time
from Cores import common_db
from Cores.Services import flow_schema as schema
from Cores.Services import terminal_service as terminal
WINDOWS=terminal._IS_WINDOWS
PY='"'+sys.executable+'"'
def slow(seconds=30):
    """A command that sleeps: the shell stays as the parent so a stop has a process TREE to kill."""
    return ("ping -n %d 127.0.0.1 >nul"%(int(seconds)+1)) if WINDOWS else ("sleep %s; echo never"%seconds)
def node(node_id,node_type,label="",**config):
    return {"id":node_id,"type":node_type,"title":label or node_id,"x":0,"y":0,"config":config}
def cmd(node_id,*lines,**config):
    return node(node_id,"command",commands=[{"text":line} for line in lines],**config)
def graph(nodes,edges,**settings):
    """edges: "a.port>b" strings. The graph is validated (must be valid) and returned normalized."""
    rows=[]
    for index,spec in enumerate(edges):
        left,target=spec.split(">")
        source,port=left.split(".")
        rows.append({"id":"e%d"%(index+1),"from":source,"port":port,"to":target})
    result=schema.validate_graph({"schema":1,"settings":settings,"nodes":[node("start","start")]+list(nodes),"edges":rows})
    if not result["ok"]:raise AssertionError("test graph is not valid: %r"%result["errors"])
    return result["graph"]
def set_live_target(values,name="box"):
    path=os.path.join(common_db.data_dir(),"Targets.json")
    with open(path,"w",encoding="utf-8") as handle:
        json.dump([{"id":"t1","name":name,"status":"live","values":values}],handle)
def wait_until(check,timeout=15,step=0.02):
    deadline=time.time()+timeout
    while time.time()<deadline:
        if check():return True
        time.sleep(step)
    return bool(check())
