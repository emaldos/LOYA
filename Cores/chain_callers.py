import re,unicodedata
# Action chain "callers": the /name a chain is invoked with from the terminal or the AI input.
# No imports from the rest of the app, so the DB migration can use it too.
CALLER_RE=re.compile(r"^[a-z0-9_-]{1,32}$")
CALLER_MAX=32
# The AI panel's built-in slash commands (UI/js/components/ai.js AI_SLASH_COMMANDS). A caller may not shadow one.
RESERVED_CALLERS=("help","explain","summarize-note","new-note","new-command","fix-command","suggest-next","run","target","search","newchain")
def normalize_caller(value):
    text=str(value if value is not None else "").strip()
    if text.startswith("/"):text=text[1:].strip()
    return text.lower()
def caller_error(caller):
    """Why a (normalized) caller is not allowed, or "" when it is fine. Uniqueness is checked by the caller."""
    if not caller:return "A caller is required."
    if len(caller)>CALLER_MAX:return f"A caller is at most {CALLER_MAX} characters."
    if not CALLER_RE.match(caller):return "A caller may only use lowercase letters, digits, - and _."
    if caller in RESERVED_CALLERS:return f"/{caller} is a built-in AI command - pick another caller."
    return ""
def slugify_caller(name):
    text=unicodedata.normalize("NFKD",str(name or "")).encode("ascii","ignore").decode("ascii").lower()
    text=re.sub(r"[^a-z0-9_-]+","-",text)
    text=re.sub(r"-{2,}","-",text).strip("-_")
    return text[:CALLER_MAX].strip("-_")
def suggest_caller(name,taken=()):
    """A free caller derived from the name: slug, then slug-2, slug-3... Falls back to 'chain'."""
    used={str(t).lower() for t in taken if t}
    base=slugify_caller(name) or "chain"
    if base in RESERVED_CALLERS:base=(base+"-chain")[:CALLER_MAX]
    if base not in used:return base
    n=2
    while True:
        tail="-"+str(n)
        candidate=base[:CALLER_MAX-len(tail)].rstrip("-_")+tail
        if candidate not in used and candidate not in RESERVED_CALLERS:return candidate
        n+=1
