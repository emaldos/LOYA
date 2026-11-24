"""Chain diagrams ("flows"): the safe rule evaluator - regexes with a ReDoS guard, value lookup, template expansion with
shell quoting, decision conditions and output parsers.
Nothing here evaluates user text as code: there is no eval/exec, the only thing ever compiled is a regular expression,
and a regex that is not trivially cheap runs in a throw-away helper process that is killed at a timeout."""
import json,os,re,subprocess,sys
try:from re import _parser as _sre_parser,_constants as _sre_constants   # Python 3.11+
except ImportError:   # pragma: no cover - older interpreters
    import sre_parse as _sre_parser,sre_constants as _sre_constants
class RuleError(ValueError):pass
MAX_REGEX_CHARS=500
MAX_TEXT=262144
_MAX_GROUPS=40
_MAX_ALTERNATIVES=80
_MAX_QUANTIFIERS=60
_BIG_REPEAT=10           # a quantifier allowing this many repetitions (or unbounded) counts as "unbounded" for the screen
_INPROCESS_BUDGET=3e7    # worst-case backtracking steps a regex may need and still run in-process
_FLAG_BITS={"i":re.I,"m":re.M,"s":re.S,"x":re.X}
SOURCES=("exit_code","stdout","stderr","output","var","parsed","line_count","match_count","port_open","host_up")
OPS=("contains","not_contains","equals","not_equals","starts_with","ends_with","regex","not_regex",
     "eq","ne","gt","ge","lt","le","is_empty","not_empty","is_true","is_false")
# ---------------------------------------------------------------- regex screening
def _flag_bits(flags):
    if flags is None:flags=""
    if not isinstance(flags,str):raise RuleError("Regex flags must be text.")
    bits=0
    for ch in flags:
        if ch.lower() not in _FLAG_BITS:raise RuleError("Unknown regex flag %r (use i, m, s, x)."%ch)
        bits|=_FLAG_BITS[ch.lower()]
    return bits
_SAMPLE=[chr(i) for i in range(128)]+["é","中"]
_ALL=frozenset(_SAMPLE)
_NO_NEWLINE=_ALL-{"\n"}
_REPEATS=tuple(op for op in(getattr(_sre_constants,name,None) for name in("MAX_REPEAT","MIN_REPEAT","POSSESSIVE_REPEAT")) if op is not None)
_C=_sre_constants
def _category(av):
    name=str(av)
    def pick(test,negate):return frozenset(ch for ch in _SAMPLE if bool(test(ch))!=negate)
    negate="NOT_" in name
    if "DIGIT" in name:return pick(str.isdigit,negate)
    if "SPACE" in name:return pick(str.isspace,negate)
    if "WORD" in name:return pick(lambda ch:ch.isalnum() or ch=="_",negate)
    if "LINEBREAK" in name:return pick(lambda ch:ch=="\n",negate)
    return _ALL
def _fold(chars,ignore_case):
    if not ignore_case:return chars
    return frozenset(chars)|frozenset(ch.lower() for ch in chars)|frozenset(ch.upper() for ch in chars if len(ch.upper())==1)
def _item_first(op,av,ic):
    """(set of sample characters the item can start with, can it match the empty string)."""
    if op is _C.LITERAL:return _fold(frozenset([chr(av)]) if av<0x110000 else _ALL,ic&re.I),False
    if op is _C.NOT_LITERAL:return frozenset(ch for ch in _SAMPLE if ch!=chr(av)),False
    if op is _C.ANY:return (_ALL if ic&re.S else _NO_NEWLINE),False
    if op is _C.IN:
        chars=set();negate=False
        for sub_op,sub_av in av:
            if sub_op is _C.NEGATE:negate=True
            elif sub_op is _C.LITERAL:chars.add(chr(sub_av))
            elif sub_op is _C.RANGE:chars.update(ch for ch in _SAMPLE if sub_av[0]<=ord(ch)<=sub_av[1])
            elif sub_op is _C.CATEGORY:chars.update(_category(sub_av))
            else:return _ALL,False
        chars=_fold(frozenset(chars),ic&re.I)
        return (frozenset(ch for ch in _SAMPLE if ch not in chars) if negate else chars),False
    if op is _C.CATEGORY:return _category(av),False
    if op in _REPEATS:
        first,nullable=_seq_first(av[2],ic)
        return first,nullable or av[0]==0
    if op is _C.SUBPATTERN:return _seq_first(av[3],ic)
    if op is getattr(_C,"ATOMIC_GROUP",None):return _seq_first(av,ic)
    if op is _C.BRANCH:
        first=frozenset();nullable=False
        for alt in av[1]:
            alt_first,alt_null=_seq_first(alt,ic)
            first|=alt_first;nullable=nullable or alt_null
        return first,nullable
    if op in(_C.AT,_C.ASSERT,_C.ASSERT_NOT):return frozenset(),True
    return _ALL,True   # back-references and anything unknown: assume the worst
def _seq_first(seq,ic):
    first=frozenset()
    for op,av in seq:
        item_first,nullable=_item_first(op,av,ic)
        first|=item_first
        if not nullable:return first,False
    return first,True
def _flatten(seq):
    """The items of a sequence with plain groups opened up: (a(bc)) -> a, b, c."""
    items=[]
    for op,av in seq:
        if op is _C.SUBPATTERN:items.extend(_flatten(av[3]))
        elif op is getattr(_C,"ATOMIC_GROUP",None):items.extend(_flatten(av))
        else:items.append((op,av))
    return items
def _is_big(op,av):
    return op in _REPEATS and av[1]>=_BIG_REPEAT
def _ambiguous(seq,ic):
    """Why the body of an unbounded repeat can match the same text in many ways (catastrophic backtracking), or ""."""
    items=_flatten(seq)
    if not items:return ""
    nullable=[_item_first(op,av,ic)[1] for op,av in items]
    for index,(op,av) in enumerate(items):
        others=all(nullable[j] for j in range(len(items)) if j!=index)
        if not others:continue
        if _is_big(op,av):return "a repeated group that itself repeats without limit, like (a+)+"
        if op is _C.BRANCH:
            firsts=[]
            for alt in av[1]:
                alt_first,alt_null=_seq_first(alt,ic)
                if alt_null:return "a repeated group with an alternative that can be empty"
                reason=_ambiguous(alt,ic)
                if reason:return reason
                firsts.append(alt_first)
            for a in range(len(firsts)):
                for b in range(a+1,len(firsts)):
                    if firsts[a]&firsts[b]:return "a repeated group whose alternatives overlap, like (a|aa)*"
    if len(items)>1 and nullable[-1] and not all(nullable):
        tail_first=_item_first(items[-1][0],items[-1][1],ic)[0]
        if tail_first&_seq_first(items,ic)[0]:return "a repeated group whose optional ending overlaps its beginning, like (a|aa)*"
    return ""
def _analyse(pattern,bits):
    """Static facts about a pattern: {"reason": why it is refused or "", "nested","backref","loops":[max counts],"alternatives","groups"}."""
    try:tree=_sre_parser.parse(pattern,bits)
    except re.error as exc:raise RuleError("Invalid regex: %s"%exc) from None
    except (RecursionError,OverflowError,ValueError) as exc:raise RuleError("Invalid regex: %s"%exc) from None
    ic=(bits|getattr(getattr(tree,"state",None),"flags",0))&(re.I|re.S)   # the flags that change which characters an item matches
    info={"reason":"","nested":False,"backref":False,"loops":[],"alternatives":0,"groups":0}
    def walk(seq,depth):
        for op,av in seq:
            if op in _REPEATS:
                low,high,body=av
                info["loops"].append(high)
                if depth:info["nested"]=True   # any quantifier inside a repeated group: never run in-process
                if high>=_BIG_REPEAT and not info["reason"]:info["reason"]=_ambiguous(body,ic)
                walk(body,depth+(1 if high>1 else 0))
            elif op is _C.SUBPATTERN:
                info["groups"]+=1;walk(av[3],depth)
            elif op is getattr(_C,"ATOMIC_GROUP",None):walk(av,depth)
            elif op is _C.BRANCH:
                info["alternatives"]+=len(av[1])
                for alt in av[1]:walk(alt,depth)
            elif op in(_C.ASSERT,_C.ASSERT_NOT):walk(av[1],depth)
            elif op is _C.GROUPREF:info["backref"]=True
            elif op is _C.GROUPREF_EXISTS:
                info["backref"]=True
                walk(av[1],depth)
                if av[2] is not None:walk(av[2],depth)
    walk(tree,0)
    return info
def _checked(pattern,flags):
    if not isinstance(pattern,str):raise RuleError("The regex must be text.")
    if not pattern:raise RuleError("The regex is empty.")
    if len(pattern)>MAX_REGEX_CHARS:raise RuleError("The regex is longer than %d characters."%MAX_REGEX_CHARS)
    if "\x00" in pattern:raise RuleError("The regex contains a NUL character.")
    bits=_flag_bits(flags)
    info=_analyse(pattern,bits)
    if info["groups"]>_MAX_GROUPS:raise RuleError("The regex has too many groups (more than %d)."%_MAX_GROUPS)
    if info["alternatives"]>_MAX_ALTERNATIVES:raise RuleError("The regex has too many alternatives (more than %d)."%_MAX_ALTERNATIVES)
    if len(info["loops"])>_MAX_QUANTIFIERS:raise RuleError("The regex has too many quantifiers (more than %d)."%_MAX_QUANTIFIERS)
    if info["reason"]:raise RuleError("This regex could take forever on some input: it has %s."%info["reason"])
    try:compiled=re.compile(pattern,bits)
    except re.error as exc:raise RuleError("Invalid regex: %s"%exc) from None
    except (RecursionError,OverflowError,ValueError) as exc:raise RuleError("Invalid regex: %s"%exc) from None
    return compiled,info
def check_regex(pattern,flags=""):
    """None when the regex is acceptable; raises RuleError (length cap, syntax, static ReDoS screen, complexity counts)."""
    _checked(pattern,flags)
    return None
def _cheap(info,length):
    """True when the pattern cannot need more than a small, bounded number of steps on a text of this length."""
    if info["nested"] or info["backref"]:return False
    cost=float(max(length,1))*(1+info["alternatives"])
    for high in info["loops"]:
        cost*=max(2,min(high,length))
        if cost>_INPROCESS_BUDGET:return False
    return cost<=_INPROCESS_BUDGET
# ---------------------------------------------------------------- regex matching
def _match_dict(match):
    if match is None:return {"matched":False,"groups":[],"named":{},"span":[-1,-1]}
    return {"matched":True,"groups":[match.group(0)]+[g if g is not None else "" for g in match.groups()],
            "named":{k:(v if v is not None else "") for k,v in match.groupdict().items()},"span":[match.start(),match.end()]}
def _run_local(op,compiled,text,limit):
    if op=="search":return _match_dict(compiled.search(text))
    if op=="count":
        count=0
        for _ in compiled.finditer(text):
            count+=1
            if count>=limit:break
        return count
    found=[]
    for match in compiled.finditer(text):
        groups=match.groups()
        if not groups:found.append(match.group(0))
        elif len(groups)==1:found.append(groups[0] if groups[0] is not None else "")
        else:found.append([g if g is not None else "" for g in groups])
        if len(found)>=limit:break
    return found
# The helper process runs exactly this text, never anything built from user input: the pattern and the text arrive as JSON on stdin.
_MATCHER_SOURCE=r'''
import json,re,sys
def main():
    req=json.loads(sys.stdin.buffer.read().decode("utf-8"))
    bits=0
    for ch in req.get("flags",""):bits|={"i":re.I,"m":re.M,"s":re.S,"x":re.X}.get(ch,0)
    rx=re.compile(req["pattern"],bits)
    text=req["text"];op=req.get("op");limit=int(req.get("limit",1000))
    if op=="search":
        m=rx.search(text)
        if m is None:out={"matched":False,"groups":[],"named":{},"span":[-1,-1]}
        else:out={"matched":True,"groups":[m.group(0)]+[g if g is not None else "" for g in m.groups()],"named":{k:(v if v is not None else "") for k,v in m.groupdict().items()},"span":[m.start(),m.end()]}
    elif op=="count":
        out=0
        for _ in rx.finditer(text):
            out+=1
            if out>=limit:break
    else:
        out=[]
        for m in rx.finditer(text):
            g=m.groups()
            if not g:out.append(m.group(0))
            elif len(g)==1:out.append(g[0] if g[0] is not None else "")
            else:out.append([x if x is not None else "" for x in g])
            if len(out)>=limit:break
    return out
try:reply={"ok":True,"result":main()}
except BaseException as exc:reply={"ok":False,"error":str(exc)[:300]}
sys.stdout.buffer.write(json.dumps(reply).encode("ascii"))
'''
def _matcher_argv():
    return [sys.executable,"-I","-S","-c",_MATCHER_SOURCE]
def _run_isolated(op,pattern,flags,text,limit,timeout):
    if getattr(sys,"frozen",False) or not sys.executable:raise RuleError("This regex is too complex to run safely here.")
    request=json.dumps({"op":op,"pattern":pattern,"flags":flags,"text":text,"limit":limit}).encode("ascii")
    options={"input":request,"stdout":subprocess.PIPE,"stderr":subprocess.DEVNULL,"timeout":timeout}
    if os.name=="nt":options["creationflags"]=getattr(subprocess,"CREATE_NO_WINDOW",0)
    try:done=subprocess.run(_matcher_argv(),**options)   # run() kills the child when the timeout expires
    except subprocess.TimeoutExpired:raise RuleError("regex timed out") from None
    except OSError as exc:raise RuleError("The regex helper could not start: %s"%exc) from None
    try:reply=json.loads(done.stdout.decode("ascii"))
    except ValueError:raise RuleError("The regex helper failed.") from None
    if not isinstance(reply,dict) or not reply.get("ok"):raise RuleError("Regex failed: %s"%(reply.get("error") if isinstance(reply,dict) else "no answer"))
    return reply["result"]
def _regex(op,pattern,text,flags,timeout,max_text,limit):
    compiled,info=_checked(pattern,flags)
    text="" if text is None else (text if isinstance(text,str) else str(text))
    text=text[:max(0,int(max_text))]
    try:timeout=min(30.0,max(0.05,float(timeout)))
    except (TypeError,ValueError):timeout=2.0
    limit=max(1,min(int(limit),100000))
    if _cheap(info,len(text)):return _run_local(op,compiled,text,limit)
    return _run_isolated(op,pattern,"".join(ch.lower() for ch in (flags or "")),text,limit,timeout)
def regex_search(pattern,text,flags="",timeout=2.0,max_text=MAX_TEXT):
    """-> {"matched","groups":[whole match, group 1, ...],"named":{},"span":[start,end]}; raises RuleError (bad regex, "regex timed out")."""
    return _regex("search",pattern,text,flags,timeout,max_text,1)
def regex_findall(pattern,text,flags="",timeout=2.0,limit=1000,max_text=MAX_TEXT):
    """Like re.findall with a cap: whole matches, or the group, or a list of groups per match."""
    return _regex("findall",pattern,text,flags,timeout,max_text,limit)
def regex_count(pattern,text,flags="",timeout=2.0,limit=100000,max_text=MAX_TEXT):
    return _regex("count",pattern,text,flags,timeout,max_text,limit)
# ---------------------------------------------------------------- value lookup
_TOKEN_RE=re.compile(r"\.?([^.\[\]]+)|\[(\*|-?\d+)\]|\[\"([^\"\]]*)\"\]|\['([^'\]]*)'\]")
_MAX_PATH=400
_MAX_DEPTH=24
def _tokens(path):
    if not isinstance(path,str):return None
    path=path.strip()
    if path.startswith("$."):path=path[2:]
    elif path=="$":path=""
    if len(path)>_MAX_PATH:return None
    tokens=[];pos=0
    while pos<len(path):
        match=_TOKEN_RE.match(path,pos)
        if match is None or match.end()==pos:return None
        if match.group(1) is not None:tokens.append(("key",match.group(1).strip()))
        elif match.group(2) is not None:tokens.append(("all",None) if match.group(2)=="*" else ("index",int(match.group(2))))
        else:tokens.append(("key",match.group(3) if match.group(3) is not None else match.group(4)))
        pos=match.end()
    return tokens if len(tokens)<=_MAX_DEPTH else None
def _walk(value,tokens):
    for position,(kind,arg) in enumerate(tokens):
        if kind=="all":
            if isinstance(value,dict):value=list(value.values())
            if not isinstance(value,list):return None
            rest=tokens[position+1:]
            found=[]
            for element in value:
                item=_walk(element,rest) if rest else element
                if item is not None:found.append(item)
            return found
        if kind=="index":
            if not isinstance(value,list) or not -len(value)<=arg<len(value):return None
            value=value[arg]
        elif isinstance(value,dict):
            if arg in value:value=value[arg]
            else:
                lowered=arg.lower()
                for key in value:
                    if isinstance(key,str) and key.lower()==lowered:
                        value=value[key];break
                else:return None
        elif isinstance(value,list) and re.match(r"^-?\d{1,9}$",arg):
            index=int(arg)
            if not -len(value)<=index<len(value):return None
            value=value[index]
        else:return None
    return value
def lookup(scope,path):
    """Value at "a.b[0].c" / "ports[*].port" (-> list) inside nested dicts and lists, or None. Dict keys and list indexes only:
    no attribute access, no calls, nothing is evaluated."""
    tokens=_tokens(path)
    if tokens is None:return None
    if not tokens:return scope
    return _walk(scope,tokens)
_ROOTS=("vars","last","nodes","target","item","index")
def resolve(scope,path):
    """A template/condition name: run-scope roots (last, nodes, target, item, index, vars) first, then a flow variable."""
    tokens=_tokens(path)
    if not tokens or not isinstance(scope,dict):return None
    head=tokens[0]
    if head[0]=="key" and head[1] in _ROOTS and head[1] in scope:
        value=_walk(scope,tokens)
        if value is not None:return value
    variables=scope.get("vars")
    if isinstance(variables,dict):
        value=_walk(variables,tokens)
        if value is not None:return value
    return None
def to_text(value):
    """How a flow value is written into text: lists of plain values become a,b,c; other structures become JSON."""
    if value is None:return ""
    if isinstance(value,str):return value.replace("\x00","")
    if isinstance(value,bool):return "true" if value else "false"
    if isinstance(value,int):return str(value)
    if isinstance(value,float):return str(int(value)) if value.is_integer() and abs(value)<1e15 else repr(value)
    if isinstance(value,(list,tuple)) and all(not isinstance(v,(dict,list,tuple)) for v in value):return ",".join(to_text(v) for v in value)
    try:return json.dumps(value,ensure_ascii=False,separators=(",",":"),default=str)
    except (TypeError,ValueError):return str(value)
# ---------------------------------------------------------------- shell quoting
_POSIX_BARE=re.compile(r"^[A-Za-z0-9_@%+:,./-][A-Za-z0-9_@%+=:,./-]*$")
_PS_BARE=re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./:-]*$")
_CMD_BARE=re.compile(r"^[A-Za-z0-9_.:/\\@+-]+$")
_PS_SINGLE="'‘’‚‛"    # PowerShell accepts typographic quotes as quote characters
_PS_DOUBLE="\"“”„"
_CMD_FORBIDDEN="&|<>^%\"!()\r\n"
MAX_VALUE_CHARS=4096
def _clean(value):
    """A value made fit for a command line: control characters removed (a TAB becomes a space), length bounded."""
    value=to_text(value)
    if len(value)>MAX_VALUE_CHARS*8:raise RuleError("A value longer than %d characters cannot be put into a command."%MAX_VALUE_CHARS)
    value="".join(" " if ch=="\t" else ch for ch in value if ch=="\t" or not(ord(ch)<32 or 127<=ord(ch)<160 or ch in "\u2028\u2029"))
    if len(value)>MAX_VALUE_CHARS:raise RuleError("A value longer than %d characters cannot be put into a command."%MAX_VALUE_CHARS)
    return value
def _cmd_clean(value):
    value=to_text(value)
    for ch in _CMD_FORBIDDEN:
        if ch in value:raise RuleError("A value with %s cannot be used in a cmd.exe command line."%("a line break" if ch in "\r\n" else repr(ch)))
    return _clean(value)
def quote_posix(value):
    value=_clean(value)
    if _POSIX_BARE.match(value):return value
    return "'"+value.replace("'","'\\''")+"'"
def quote_powershell(value):
    value=_clean(value)
    if _PS_BARE.match(value):return value
    return "'"+"".join(ch+ch if ch in _PS_SINGLE else ch for ch in value)+"'"
def quote_cmd(value):
    value=_cmd_clean(value)
    if _CMD_BARE.match(value):return value
    trailing=len(value)-len(value.rstrip("\\"))
    return '"'+value+"\\"*trailing+'"'
def _posix_context(prefix):
    """Quoting state at the end of a POSIX shell fragment: plain, single, double, or complex (cannot be quoted reliably)."""
    stack=[];state="plain";i=0;n=len(prefix)
    while i<n:
        ch=prefix[i];nxt=prefix[i+1:i+2]
        if state=="single":
            if ch=="'":state="plain"
        elif state=="ansi":
            if ch=="\\":
                if i+1>=n:return "complex"
                i+=1
            elif ch=="'":state="plain"
        elif state=="double":
            if ch=="\\":
                if i+1>=n:return "complex"
                i+=1
            elif ch=='"':state="plain"
            elif ch=="`":return "complex"
            elif ch=="$" and nxt=="(":
                stack.append("double");state="plain";i+=1
        else:
            if ch=="\\":
                if i+1>=n:return "complex"
                i+=1
            elif ch=="'":state="single"
            elif ch=='"':state="double"
            elif ch=="`":return "complex"
            elif ch=="$" and nxt=="'":
                state="ansi";i+=1
            elif ch=="$" and nxt=="(":
                stack.append("plain");i+=1
            elif ch=="(":stack.append("paren")
            elif ch==")" and stack:
                top=stack.pop()
                if top!="paren":state=top
            elif ch=="<" and nxt=="<":return "complex"
            elif ch=="#" and (i==0 or prefix[i-1] in " \t\n;&|("):
                end=prefix.find("\n",i)
                if end<0:return "complex"
                i=end
        i+=1
    return "complex" if state=="ansi" else state
def _powershell_context(prefix):
    state="plain";i=0;n=len(prefix)
    while i<n:
        ch=prefix[i];nxt=prefix[i+1:i+2]
        if state=="single":
            if ch in _PS_SINGLE:
                if nxt and nxt in _PS_SINGLE:i+=1
                else:state="plain"
        elif state=="double":
            if ch=="`":
                if i+1>=n:return "complex"
                i+=1
            elif ch in _PS_DOUBLE:
                if nxt and nxt in _PS_DOUBLE:i+=1
                else:state="plain"
            elif ch=="$" and nxt=="(":return "complex"
        else:
            if ch=="`":
                if i+1>=n:return "complex"
                i+=1
            elif ch=="@" and nxt and nxt in _PS_SINGLE+_PS_DOUBLE:return "complex"
            elif ch=="<" and nxt=="#":return "complex"
            elif ch in _PS_SINGLE:state="single"
            elif ch in _PS_DOUBLE:state="double"
            elif ch=="#" and (i==0 or prefix[i-1] in " \t\n;|({"):
                end=prefix.find("\n",i)
                if end<0:return "complex"
                i=end
        i+=1
    return state
def _complex(value,bare,shell):
    if value and bare.match(value):return value
    raise RuleError("A value with spaces or special characters cannot be inserted at this place in a %s command (inside a comment, back-ticks, a here-document or a nested string). Put ${...} in a plain or simply quoted position."%shell)
def _posix_quoter(value,prefix=""):
    value=_clean(value);state=_posix_context(prefix or "")
    if state=="plain":
        if (prefix or "").endswith("$") and not _POSIX_BARE.match(value):return _complex(value,_POSIX_BARE,"shell")
        return quote_posix(value)
    if state=="single":return value.replace("'","'\\''")
    if state=="double":return re.sub(r"([\\\"$`])",r"\\\1",value)
    return _complex(value,_POSIX_BARE,"shell")
def _powershell_quoter(value,prefix=""):
    value=_clean(value);state=_powershell_context(prefix or "")
    if state=="plain":
        if (prefix or "")[-1:] in("$","@") and not _PS_BARE.match(value):return _complex(value,_PS_BARE,"PowerShell")
        return quote_powershell(value)
    if state=="single":return "".join(ch+ch if ch in _PS_SINGLE else ch for ch in value)
    if state=="double":return "".join("`"+ch if ch in "`$"+_PS_DOUBLE else ch for ch in value)
    return _complex(value,_PS_BARE,"PowerShell")
def _cmd_quoter(value,prefix=""):
    value=_cmd_clean(value)
    if (prefix or "").count('"')%2:return value
    return quote_cmd(value)
for _fn,_kind in((_posix_quoter,"posix"),(_powershell_quoter,"powershell"),(_cmd_quoter,"cmd")):
    _fn.context_aware=True;_fn.kind=_kind
def shell_kind(shell_id,windows=None):
    """Which quoting rules a terminal shell id needs: posix, powershell or cmd (mirrors terminal_service._one_shot_command)."""
    windows=(os.name=="nt") if windows is None else bool(windows)
    shell_id=str(shell_id or "").strip()
    if not shell_id:
        try:
            from Cores.Services import terminal_service
            if windows==(os.name=="nt"):shell_id=str(terminal_service.default_shell() or "")
        except Exception:shell_id=""
    if shell_id in("pwsh","powershell"):return "powershell"
    return "cmd" if windows else "posix"
def shell_quoter(shell_id,windows=None):
    """quoter(value, prefix="") -> text that is one literal word for that shell. `prefix` is the command text before the value, so
    a value placed inside the user's own quotes is escaped for those quotes. Raises RuleError when the value cannot be made safe
    (cmd.exe metacharacters; back-tick / here-document positions)."""
    return {"posix":_posix_quoter,"powershell":_powershell_quoter,"cmd":_cmd_quoter}[shell_kind(shell_id,windows)]
# ---------------------------------------------------------------- templates
_TEMPLATE_RE=re.compile(r"\$(\$)?\{(raw:)?\s*([^{}\s][^{}]*?)\s*\}")
def template_names(text):
    """[(name, is_raw)] for every ${...} in a text (escaped $${...} skipped)."""
    return [(m.group(3),bool(m.group(2))) for m in _TEMPLATE_RE.finditer(text if isinstance(text,str) else "") if not m.group(1)]
def _raw_allowed(raw_ok,name):
    if raw_ok is None:return True
    try:return bool(raw_ok(name)) if callable(raw_ok) else name in raw_ok
    except Exception:return False
def expand_template(text,scope,quoter=None,raw_ok=None):
    """Replace ${name} / ${raw:name} with flow values in ONE pass (inserted values are never expanded again). -> (text, warnings).
    With a quoter every ${name} value is passed through it (shell_quoter() also looks at the text before the value); ${raw:name}
    is inserted as is. $${name} is an escape for a literal ${name}. Unknown names become "" plus a warning.
    A quoter may raise RuleError when a value cannot be made safe; that error is passed on to the caller.
    raw_ok (a set of names, or a callable name -> bool): when given, a ${raw:name} whose name is not approved raises
    RuleError("raw value not allowed: name"). None keeps every ${raw:...} allowed.
    Every quoted value first loses its control characters (NUL, CR, LF, ...) and may be at most MAX_VALUE_CHARS long."""
    text="" if text is None else (text if isinstance(text,str) else str(text))
    out=[];warnings=[];position=0
    aware=bool(getattr(quoter,"context_aware",False))
    for match in _TEMPLATE_RE.finditer(text):
        out.append(text[position:match.start()]);position=match.end()
        if match.group(1):
            out.append(match.group(0)[1:]);continue
        name=match.group(3)
        if match.group(2) and not _raw_allowed(raw_ok,name):raise RuleError("raw value not allowed: %s"%name)
        value=resolve(scope,name)
        if value is None:warnings.append("Unknown value ${%s} was replaced with nothing."%name)
        value=to_text(value)
        if quoter is not None and not match.group(2):
            value=quoter(value,text[:match.start()]) if aware else quoter(value)
        out.append(value)
    out.append(text[position:])
    return "".join(out),warnings
def resolve_value(text,scope):
    """Like expand_template without a quoter, but a text that is exactly one ${name} gives the value itself (a list stays a list).
    -> (value, warnings)."""
    if isinstance(text,str):
        match=_TEMPLATE_RE.fullmatch(text.strip())
        if match and not match.group(1):
            value=resolve(scope,match.group(3))
            return value,([] if value is not None else ["Unknown value ${%s} was replaced with nothing."%match.group(3)])
    return expand_template(text,scope)
# ---------------------------------------------------------------- conditions
_PORT_LINE=re.compile(r"^(\d{1,5})/(?:tcp|udp|sctp)[ \t]+open(?:[ \t]|$)",re.I)
_PORT_HINTS=(re.compile(r"Discovered open port (\d{1,5})/",re.I),re.compile(r"^Open [0-9a-fA-F:.\[\]]{2,60}:(\d{1,5})[ \t]*$"))
_RECEIVED_RE=re.compile(r"(\d{1,6})[ \t]+(?:packets[ \t]+)?received|received[ \t]*=[ \t]*(\d{1,6})",re.I)
def _output_of(data):
    data=data if isinstance(data,dict) else {}
    out=to_text(data.get("stdout"));err=to_text(data.get("stderr"))
    return out+("\n"+err if err else "")
def open_ports(data):
    """Open port numbers known from an envelope: its parsed nmap data and nmap-style lines in its output."""
    ports=set()
    data=data if isinstance(data,dict) else {}
    parsed=data.get("parsed")
    def add(value):
        try:number=int(str(value).strip())
        except (TypeError,ValueError):return
        if 0<number<65536:ports.add(number)
    def rows(items):
        for row in items if isinstance(items,list) else []:
            if isinstance(row,dict):
                if str(row.get("state","open")).lower().split("|")[0]=="open":add(row.get("port"))
            else:add(row)
    if isinstance(parsed,dict):
        rows(parsed.get("open_ports"));rows(parsed.get("ports"))
        for host in parsed.get("hosts") if isinstance(parsed.get("hosts"),list) else []:
            if isinstance(host,dict):rows(host.get("ports"))
    elif isinstance(parsed,list):rows(parsed)
    for line in _output_of(data)[:MAX_TEXT*4].splitlines():
        line=line.strip()
        match=_PORT_LINE.match(line)
        if match:add(match.group(1));continue
        for hint in _PORT_HINTS:
            match=hint.search(line) if len(line)<400 else None
            if match:add(match.group(1))
    return sorted(ports)
def host_is_up(data):
    """Ping / nmap heuristics over an envelope."""
    data=data if isinstance(data,dict) else {}
    parsed=data.get("parsed")
    if isinstance(parsed,dict) and isinstance(parsed.get("alive"),bool):return parsed["alive"]
    text=_output_of(data)[:MAX_TEXT*4].lower()
    received=None
    for line in text.splitlines():
        match=_RECEIVED_RE.search(line) if len(line)<400 else None
        if match:received=int(match.group(1) or match.group(2))
    if "100% packet loss" in text or "100% loss" in text or "host seems down" in text or "0 hosts up" in text or received==0:return False
    if "ttl=" in text or "bytes from" in text or "host is up" in text:return True
    if "unreachable" in text:return False
    if received:return True
    if isinstance(parsed,dict) and (parsed.get("open_ports") or parsed.get("hosts")):return True
    return False
def _number(value):
    if isinstance(value,bool):return float(value)
    if isinstance(value,(int,float)):return float(value)
    try:return float(str(value).strip())
    except (TypeError,ValueError):return None
def _truthy(value):
    if isinstance(value,str):return value.strip().lower() in("true","yes","y","1","on","up","open","ok","success","alive")
    if isinstance(value,(list,dict)):return bool(value)
    return bool(value)
def _empty(value):
    if value is None:return True
    if isinstance(value,str):return not value.strip()
    if isinstance(value,(list,dict,tuple)):return not value
    return False
_TEXT_OPS={"contains":lambda a,b:b in a,"equals":lambda a,b:a==b,"starts_with":lambda a,b:a.startswith(b),"ends_with":lambda a,b:a.endswith(b)}
_NUM_OPS={"eq":lambda a,b:a==b,"ne":lambda a,b:a!=b,"gt":lambda a,b:a>b,"ge":lambda a,b:a>=b,"lt":lambda a,b:a<b,"le":lambda a,b:a<=b}
def _apply(op,actual,expected,ci):
    """One operator on one actual value (lists: "any element" for positive tests, "no element" for the not_ ones)."""
    if op=="is_empty":return _empty(actual)
    if op=="not_empty":return not _empty(actual)
    if op=="is_true":return _truthy(actual)
    if op=="is_false":return not _truthy(actual)
    if op in("not_contains","not_equals","not_regex"):
        return not _apply({"not_contains":"contains","not_equals":"equals","not_regex":"regex"}[op],actual,expected,ci)
    elements=list(actual) if isinstance(actual,(list,tuple)) else [actual]
    if op in _NUM_OPS:
        wanted=_number(expected)
        if wanted is None:raise RuleError("%r is not a number."%expected[:40])
        return any(number is not None and _NUM_OPS[op](number,wanted) for number in (_number(e) for e in elements))
    if op=="regex":
        if not expected:raise RuleError("The regex is empty.")
        return any(regex_search(expected,to_text(e),"i" if ci else "")["matched"] for e in elements)
    if op in _TEXT_OPS:
        wanted=expected.strip() if op=="equals" else expected
        if ci:wanted=wanted.lower()
        for element in elements:
            text=to_text(element)
            if op=="equals":text=text.strip()
            if ci:text=text.lower()
            if _TEXT_OPS[op](text,wanted):return True
        return False
    raise RuleError("Unknown operator %r."%op)
def _short(value,limit=200):
    text=to_text(value)
    return text if len(text)<=limit else text[:limit]+"..."
def _quote(text,limit=60):
    text=str(text)
    return "'"+(text if len(text)<=limit else text[:limit]+"...")+"'"
_SOURCE_LABELS={"exit_code":"exit code","stdout":"stdout","stderr":"stderr","output":"output","line_count":"number of output lines"}
_OP_LABELS={"contains":"contains","not_contains":"does not contain","equals":"is","not_equals":"is not","starts_with":"starts with","ends_with":"ends with",
            "regex":"matches","not_regex":"does not match","eq":"=","ne":"!=","gt":">","ge":">=","lt":"<","le":"<=",
            "is_empty":"is empty","not_empty":"is not empty","is_true":"is true","is_false":"is false"}
def describe_condition(cond):
    """A short sentence for a condition: "output contains 'ttl='"."""
    if not isinstance(cond,dict):return "invalid condition"
    source=cond.get("source","output");op=cond.get("op","contains")
    if not isinstance(source,str) or not isinstance(op,str):return "invalid condition"
    value=to_text(cond.get("value"));field=to_text(cond.get("field"))
    negative=op=="is_false"
    if source=="port_open":return "port %s is %s"%(value.strip() or "?","not open" if negative else "open")
    if source=="host_up":return "host is %s"%("down" if negative else "up")
    if source=="var":subject="variable %s"%(field or "?")
    elif source=="parsed":subject="parsed %s"%field if field else "parsed data"
    elif source=="match_count":subject="matches of /%s/"%(field if len(field)<=60 else field[:60]+"...")
    else:subject=_SOURCE_LABELS.get(source,str(source))
    label=_OP_LABELS.get(op,str(op))
    if op in("is_empty","not_empty","is_true","is_false"):return "%s %s"%(subject,label)
    if op in("regex","not_regex"):return "%s %s /%s/"%(subject,label,value if len(value)<=60 else value[:60]+"...")
    if op in _NUM_OPS:return "%s %s %s"%(subject,label,value.strip() or "?")
    return "%s %s %s"%(subject,label,_quote(value))
def _actual(cond,data,scope,ci):
    source=cond.get("source","output");field=to_text(cond.get("field"))
    data=data if isinstance(data,dict) else {}
    if source=="exit_code":return data.get("exit_code")
    if source=="stdout":return to_text(data.get("stdout"))
    if source=="stderr":return to_text(data.get("stderr"))
    if source=="output":return _output_of(data)
    if source=="var":return resolve(scope,field.strip())
    if source=="parsed":return lookup(data.get("parsed"),field.strip()) if field.strip() else data.get("parsed")
    if source=="line_count":return sum(1 for line in _output_of(data).splitlines() if line.strip())
    if source=="match_count":
        if not field:raise RuleError("The regex to count is empty.")
        return regex_count(field,_output_of(data),"i" if ci else "")
    raise RuleError("Unknown condition source %r."%source)
def evaluate_condition(cond,data,scope):
    """-> {"result":bool,"actual":short text,"text":sentence,"error":""}. Never raises: a broken condition is simply false."""
    text=describe_condition(cond)
    try:
        if not isinstance(cond,dict):raise RuleError("The condition is not an object.")
        source=cond.get("source","output");op=cond.get("op","contains")
        ci=cond.get("ci",True) is not False
        expected,_=expand_template(to_text(cond.get("value")),scope)
        if source=="port_open":
            wanted=_number(expected)
            if wanted is None or not 0<wanted<65536:raise RuleError("%r is not a port number."%expected[:40])
            ports=open_ports(data);is_open=int(wanted) in ports
            return {"result":is_open!=(op=="is_false"),"actual":"open ports: %s"%(_short(ports) or "none"),"text":text,"error":""}
        if source=="host_up":
            up=host_is_up(data)
            return {"result":up!=(op=="is_false"),"actual":"up" if up else "down","text":text,"error":""}
        if op not in OPS:raise RuleError("Unknown operator %r."%op)
        actual=_actual(cond,data,scope,ci)
        return {"result":bool(_apply(op,actual,expected,ci)),"actual":_short(actual),"text":text,"error":""}
    except RuleError as exc:return {"result":False,"actual":"","text":text,"error":str(exc)}
    except Exception as exc:return {"result":False,"actual":"","text":text,"error":"The condition could not be checked: %s"%exc}
def evaluate_decision(config,data,scope):
    """First branch whose conditions hold (all/any) wins; none -> the else port.
    -> {"branch":name,"trace":[{"branch","matched","conditions":[condition results]}]}."""
    config=config if isinstance(config,dict) else {}
    other=config.get("else") if isinstance(config.get("else"),str) and config.get("else") else "else"
    trace=[]
    for branch in config.get("branches") if isinstance(config.get("branches"),list) else []:
        if not isinstance(branch,dict):continue
        name=to_text(branch.get("name"))
        conditions=[c for c in (branch.get("conditions") if isinstance(branch.get("conditions"),list) else [])]
        results=[evaluate_condition(c,data,scope) for c in conditions]
        if not results:matched=False   # a branch without rules is never taken (the else port is the catch-all)
        elif branch.get("match")=="any":matched=any(r["result"] for r in results)
        else:matched=all(r["result"] for r in results)
        trace.append({"branch":name,"matched":matched,"conditions":results})
        if matched:return {"branch":name,"trace":trace}
    return {"branch":other,"trace":trace}
# ---------------------------------------------------------------- parsers
_PARSER_TEXT=1048576
def _parse_nmap(text):
    try:
        from Cores.Services import report_autogen
        hosts=report_autogen.parse_nmap(text)
    except Exception:hosts=_parse_nmap_basic(text)
    ports=[];numbers=set()
    for host in hosts:
        for port in host.get("ports") or []:
            if str(port.get("state","")).lower()!="open":continue
            ports.append({"host":host.get("host",""),"port":port.get("port"),"proto":port.get("proto",""),"state":"open",
                          "service":port.get("service",""),"version":port.get("version","")})
            if isinstance(port.get("port"),int):numbers.add(port["port"])
    return {"hosts":hosts,"ports":ports,"open_ports":sorted(numbers)}
def _parse_nmap_basic(text):
    """Fallback when the report parser cannot be imported: ports only."""
    host={"host":"","hostnames":[],"ports":[],"os":"","scripts":[],"source":"nmap"}
    for line in text.splitlines():
        parts=line.strip().split()
        if len(parts)>=2 and "/" in parts[0]:
            number,_,proto=parts[0].partition("/")
            if number.isdigit() and proto.lower() in("tcp","udp","sctp"):
                host["ports"].append({"port":int(number),"proto":proto.lower(),"state":parts[1].lower(),"service":parts[2] if len(parts)>2 else "","version":" ".join(parts[3:]),"scripts":[]})
    return [host] if host["ports"] else []
_PING_SENT=(re.compile(r"(\d{1,6}) packets transmitted, (\d{1,6}) (?:packets )?received",re.I),re.compile(r"Sent = (\d{1,6}), Received = (\d{1,6})",re.I))
_PING_LOSS=re.compile(r"(\d{1,3}(?:\.\d{1,3})?)% (?:packet )?loss",re.I)
_PING_TTL=re.compile(r"ttl=(\d{1,3})",re.I)
def _parse_ping(text):
    sent=received=0;loss=None;ttl=None;summary=False
    for line in text.splitlines():
        if len(line)>400:continue
        for pattern in _PING_SENT:
            match=pattern.search(line)
            if match:sent,received,summary=int(match.group(1)),int(match.group(2)),True
        match=_PING_LOSS.search(line)
        if match:loss=float(match.group(1))
        if ttl is None:
            match=_PING_TTL.search(line)
            if match:ttl=int(match.group(1))
    if loss is None and summary and sent:loss=round(100.0*(sent-received)/sent,1)
    replied=ttl is not None or "bytes from" in text.lower()
    alive=replied and not(summary and received==0) and loss!=100
    return {"alive":bool(alive),"sent":sent,"received":received,"loss":(int(loss) if loss is not None and float(loss).is_integer() else loss),"ttl":ttl}
def _parse_lines(text):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    return {"lines":lines,"count":len(lines)}
def _load_json(text):
    stripped=text.strip()
    if not stripped:raise RuleError("There is no JSON in the output.")
    try:value=json.loads(stripped)
    except ValueError:
        value=None
        for line in reversed(stripped.splitlines()[-200:]):
            line=line.strip()
            if line[:1] in("{","["):
                try:value=json.loads(line);break
                except ValueError:continue
        if value is None:raise RuleError("The output is not valid JSON.") from None
    return value
def _parse_json(text):
    value=_load_json(text)
    if isinstance(value,dict):return value
    if isinstance(value,list):return {"items":value,"count":len(value)}
    return {"value":value}
def _parse_keyvalue(text):
    pairs={}
    for line in text.splitlines():
        line=line.strip()
        if not line or line[0] in "#;" or len(line)>4000:continue
        cut=min((i for i in (line.find(":"),line.find("=")) if i>0),default=-1)
        if cut<1:continue
        key=line[:cut].strip();value=line[cut+1:].strip()
        if key and len(key)<=120 and key not in pairs:pairs[key]=value
        if len(pairs)>=2000:break
    return pairs
_IP_RE=re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d)")
_URL_RE=re.compile(r"https?://[^\s\"'<>`\\]{1,2000}",re.I)
def _parse_ips(text):
    found=[]
    for match in _IP_RE.finditer(text):
        if all(int(part)<=255 for part in match.groups()):
            ip=".".join(str(int(part)) for part in match.groups())
            if ip not in found:found.append(ip)
        if len(found)>=5000:break
    return {"ips":found,"count":len(found)}
def _parse_urls(text):
    found=[]
    for match in _URL_RE.finditer(text):
        url=match.group(0).rstrip(".,;:!?)]}")
        if url not in found:found.append(url)
        if len(found)>=5000:break
    return {"urls":found,"count":len(found)}
PARSERS={"nmap":_parse_nmap,"ping":_parse_ping,"lines":_parse_lines,"json":_parse_json,"keyvalue":_parse_keyvalue,"ips":_parse_ips,"urls":_parse_urls}
def parse_tool_output(tool,text):
    """Structured data from tool output. tool is a key of PARSERS; raises RuleError for an unknown tool or unusable input."""
    if tool not in PARSERS:raise RuleError("Unknown parser %r. Use one of: %s."%(tool,", ".join(PARSERS)))
    text=to_text(text) if not isinstance(text,str) else text
    return PARSERS[tool](text.replace("\r\n","\n")[:_PARSER_TEXT])
def _has_content(parsed):
    if isinstance(parsed,dict):return any(v not in(None,"",0,False) and v!=[] and v!={} for v in parsed.values())
    return not _empty(parsed)
_VAR_RE=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
def _parse_source(config,data,scope):
    source=to_text(config.get("source") or "stdout").strip()
    data=data if isinstance(data,dict) else {}
    if source=="stdout":return to_text(data.get("stdout"))
    if source=="stderr":return to_text(data.get("stderr"))
    if source=="output":return _output_of(data)
    if source.startswith("var:"):source=source[4:]
    return to_text(resolve(scope,source))
def run_parse(config,data,scope):
    """Run a parse node. -> {"matched":bool,"vars":{name:value},"parsed":any,"error":""}. Never raises."""
    result={"matched":False,"vars":{},"parsed":None,"error":""}
    try:
        config=config if isinstance(config,dict) else {}
        mode=config.get("mode","regex")
        text=_parse_source(config,data,scope)
        extra={}
        if mode=="regex":
            pattern=to_text(config.get("pattern"));flags=to_text(config.get("flags"))
            found=regex_search(pattern,text,flags)
            if found["matched"]:
                result["matched"]=True
                result["parsed"]={"match":found["groups"][0],"groups":found["groups"],"named":found["named"]}
                extra={"pattern":pattern,"flags":flags,"text":text}
        elif mode=="tool":
            result["parsed"]=parse_tool_output(config.get("tool","nmap"),text)
            result["matched"]=_has_content(result["parsed"])
        elif mode=="jsonpath":
            document=_load_json(text)
            path=to_text(config.get("path")).strip()
            value=lookup(document,path) if path else document
            result["parsed"]=value;result["matched"]=value is not None and value!=[]
        else:raise RuleError("Unknown parse mode %r."%mode)
        if result["matched"]:
            name=to_text(config.get("var")).strip()
            if name and _VAR_RE.match(name):result["vars"][name]=result["parsed"]
            for row in config.get("assign") if isinstance(config.get("assign"),list) else []:
                if not isinstance(row,dict) or not _VAR_RE.match(to_text(row.get("var"))):continue
                result["vars"][row["var"]]=_assign_value(to_text(row.get("from")).strip(),result["parsed"],mode,extra)
    except RuleError as exc:
        result.update(matched=False,vars={},error=str(exc))
    except Exception as exc:
        result.update(matched=False,vars={},error="The output could not be parsed: %s"%exc)
    return result
def _assign_value(source,parsed,mode,extra):
    if source in("","value","parsed"):return parsed
    if mode=="regex":
        if source=="match":return parsed["match"]
        if source in("all","count"):
            found=regex_findall(extra["pattern"],extra["text"],extra["flags"])
            return found if source=="all" else len(found)
        if source.startswith("group:") or source.startswith("named:"):
            key=source.split(":",1)[1].strip()
            if re.match(r"^\d{1,3}$",key):
                index=int(key)
                return parsed["groups"][index] if index<len(parsed["groups"]) else ""
            return parsed["named"].get(key,"")
    if source.startswith("path:"):source=source[5:].strip()
    return lookup(parsed,source)
# ---------------------------------------------------------------- for-each items
def split_items(value,mode="auto",max_items=50):
    """The list a for-each loops over. value may already be a list (see resolve_value) or text split by mode (lines/comma/json/auto)."""
    try:max_items=max(1,min(int(max_items),1000))
    except (TypeError,ValueError):max_items=50
    if value is None:return []
    if isinstance(value,tuple):value=list(value)
    if isinstance(value,list):return value[:max_items]
    if isinstance(value,dict):return [value]
    if not isinstance(value,str):return [value]
    text=value.strip()
    if not text:return []
    if mode=="json" or (mode=="auto" and text[:1] in("[","{")):
        try:loaded=json.loads(text)
        except ValueError:loaded=None
        if loaded is not None:return (loaded if isinstance(loaded,list) else [loaded])[:max_items]
        if mode=="json":return []
    if mode=="auto":mode="lines" if "\n" in text else ("comma" if "," in text else "lines")
    parts=text.split(",") if mode=="comma" else text.splitlines()
    items=[]
    for part in parts:
        part=part.strip()
        if part:items.append(part)
        if len(items)>=max_items:break
    return items
