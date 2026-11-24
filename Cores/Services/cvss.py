"""CVSS v3.1 base score calculator (FIRST specification, section 7 and appendix A roundup)."""
import math,re
_ORDER=("AV","AC","PR","UI","S","C","I","A")
_W={"AV":{"N":0.85,"A":0.62,"L":0.55,"P":0.2},"AC":{"L":0.77,"H":0.44},"UI":{"N":0.85,"R":0.62},"S":{"U":0,"C":0},"C":{"H":0.56,"L":0.22,"N":0.0},"I":{"H":0.56,"L":0.22,"N":0.0},"A":{"H":0.56,"L":0.22,"N":0.0}}
_PR={"U":{"N":0.85,"L":0.62,"H":0.27},"C":{"N":0.85,"L":0.68,"H":0.5}}
# Temporal and environmental metrics are accepted and dropped: only the base score is calculated.
_EXTRA={"E":"XUPFH","RL":"XOTWU","RC":"XURC","CR":"XLMH","IR":"XLMH","AR":"XLMH","MAV":"XNALP","MAC":"XLH","MPR":"XNLH","MUI":"XNR","MS":"XUC","MC":"XNLH","MI":"XNLH","MA":"XNLH"}
_PREFIX_RX=re.compile(r"^CVSS:(\d\.\d)/?",re.I)
def roundup(x):
    """Smallest number, to one decimal place, that is equal to or higher than x (spec appendix A, safe against float error)."""
    i=int(round(x*100000))
    if i%10000==0:return i/100000.0
    return (math.floor(i/10000)+1)/10.0
def severity(score):
    """Qualitative rating as the app's severity id; 0.0 (None) maps to info."""
    try:s=float(score)
    except (TypeError,ValueError):return "info"
    if s>=9.0:return "critical"
    if s>=7.0:return "high"
    if s>=4.0:return "medium"
    if s>=0.1:return "low"
    return "info"
def parse(vector):
    """-> (metrics dict, error text). Order-insensitive; the CVSS:3.x prefix is optional."""
    v=re.sub(r"\s+","",str(vector or "")).upper()
    if not v:return None,"Vector is empty."
    m=_PREFIX_RX.match(v)
    if m:
        if m.group(1) not in ("3.1","3.0"):return None,f"Only CVSS v3.x vectors are supported (got {m.group(1)})."
        v=v[m.end():]
    v=v.strip("/")
    metrics={}
    for part in v.split("/"):
        if not part:continue
        if ":" not in part:return None,f"Malformed metric \"{part[:20]}\"."
        k,val=part.split(":",1)
        if k in _EXTRA:
            if len(val)!=1 or val not in _EXTRA[k]:return None,f"Invalid value for {k}."
            continue
        if k not in _ORDER:return None,f"Unknown metric \"{k[:10]}\"."
        if k in metrics:return None,f"Metric {k} is repeated."
        allowed=_PR["U"] if k=="PR" else _W[k]
        if val not in allowed:return None,f"Invalid value for {k}."
        metrics[k]=val
    missing=[k for k in _ORDER if k not in metrics]
    if missing:return None,"Missing metric"+("s" if len(missing)>1 else "")+": "+", ".join(missing)+"."
    return metrics,""
def build(metrics):return "CVSS:3.1/"+"/".join(f"{k}:{metrics[k]}" for k in _ORDER)
def score(metrics):
    changed=metrics["S"]=="C"
    iss=1-(1-_W["C"][metrics["C"]])*(1-_W["I"][metrics["I"]])*(1-_W["A"][metrics["A"]])
    impact=7.52*(iss-0.029)-3.25*(iss-0.02)**15 if changed else 6.42*iss
    expl=8.22*_W["AV"][metrics["AV"]]*_W["AC"][metrics["AC"]]*_PR["C" if changed else "U"][metrics["PR"]]*_W["UI"][metrics["UI"]]
    if impact<=0:return 0.0
    return roundup(min(1.08*(impact+expl),10)) if changed else roundup(min(impact+expl,10))
def calc(vector):
    """-> {valid,score,severity,vector (normalised CVSS:3.1/...),error}. Never raises."""
    try:
        metrics,err=parse(vector)
        if not metrics:return {"valid":False,"score":None,"severity":"","vector":str(vector or "").strip()[:200],"error":err}
        s=score(metrics)
        return {"valid":True,"score":s,"severity":severity(s),"vector":build(metrics),"error":""}
    except Exception as e:
        return {"valid":False,"score":None,"severity":"","vector":str(vector or "").strip()[:200],"error":str(e) or "Invalid vector."}
