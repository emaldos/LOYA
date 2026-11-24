"""Design tokens for exported reports: severity palette, fonts and the built-in themes.
One structure feeds every writer (HTML/print PDF, the fpdf2 fallback and Word) so the outputs match."""
import os,re,io,base64
SEVERITIES=("critical","high","medium","low","info")
SEV_LABELS={"critical":"Critical","high":"High","medium":"Medium","low":"Low","info":"Informational"}
SEV_SHORT={"critical":"Critical","high":"High","medium":"Medium","low":"Low","info":"Info"}
SEV_COLORS={"critical":"#9b1c1c","high":"#dc2626","medium":"#f59e0b","low":"#2563eb","info":"#6b7280"}
SEV_TINTS={"critical":"#f6e4e4","high":"#fde8e8","medium":"#fef3d7","low":"#e3ecfd","info":"#eceef1"}
# Text colours that stay readable: SEV_ON on a solid severity fill (white fails on amber), SEV_INK on the tint or on white.
SEV_ON={"critical":"#ffffff","high":"#ffffff","medium":"#1f2937","low":"#ffffff","info":"#ffffff"}
SEV_INK={"critical":"#9b1c1c","high":"#b91c1c","medium":"#92400e","low":"#1d4ed8","info":"#4b5563"}
STATUS_COLORS={"open":"#b91c1c","retest":"#b45309","fixed":"#15803d","accepted":"#475569"}
STOCK_ACCENTS=("#1f4e79",)
STOCK_SECONDARY=("#475569","#5b6770")
_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_DIR=os.path.join(_ROOT,"Assets","fonts")
# css: family name used in the document; files: bundled faces (regular/bold/italic[/black]); stack: what follows when a face or glyph is
# missing; docx: fonts Word is asked for (it substitutes on its own when they are not installed, nothing is embedded there).
_SANS_STACK='"Segoe UI","Helvetica Neue",Helvetica,Arial,"Liberation Sans","DejaVu Sans",sans-serif'
_SERIF_STACK='Georgia,Cambria,"Times New Roman","Liberation Serif","DejaVu Serif",serif'
_MONO_STACK='Consolas,"Cascadia Mono","DejaVu Sans Mono","Liberation Mono",Menlo,monospace'
FAMILIES={
    "sans":{"css":"LOYA Report Sans","files":{"":"LoyaSans-Regular.ttf","B":"LoyaSans-Bold.ttf","I":"LoyaSans-Italic.ttf","K":"LoyaSans-Black.ttf"},"stack":_SANS_STACK,"docx":"Calibri"},
    "text":{"css":"LOYA Report Text","files":{"":"LoyaText-Regular.ttf","B":"LoyaText-Bold.ttf","I":"LoyaText-Italic.ttf"},"stack":_SANS_STACK,"docx":"Segoe UI"},
    "serif":{"css":"LOYA Report Serif","files":{"":"LoyaSerif-Regular.ttf","B":"LoyaSerif-Bold.ttf","I":"LoyaSerif-Italic.ttf"},"stack":_SERIF_STACK,"docx":"Cambria"},
    "mono":{"css":"LOYA Report Mono","files":{"":"LoyaMono-Regular.ttf","B":"LoyaMono-Bold.ttf"},"stack":_MONO_STACK,"docx":"Consolas"},
    "system":{"css":"","files":{},"stack":_SANS_STACK,"docx":"Arial"},
    "system-serif":{"css":"","files":{},"stack":_SERIF_STACK,"docx":"Georgia"},
}
# Font choices offered per report: body family + heading family.
FONTS=[
    {"id":"theme","label":"Theme default","body":"","head":""},
    {"id":"humanist","label":"Humanist sans (Lato)","body":"sans","head":"sans"},
    {"id":"neutral","label":"Neutral sans (Noto Sans)","body":"text","head":"text"},
    {"id":"serif-head","label":"Serif headings, sans text","body":"text","head":"serif"},
    {"id":"serif","label":"Serif (Noto Serif)","body":"serif","head":"serif"},
    {"id":"system","label":"System sans (Segoe UI / Arial)","body":"system","head":"system"},
    {"id":"system-serif","label":"System serif (Georgia / Cambria)","body":"system-serif","head":"system-serif"},
]
FONT_BY_ID={f["id"]:f for f in FONTS}
COVER_STYLES=[{"id":"band","label":"Colour band"},{"id":"full","label":"Full colour page"},{"id":"simple","label":"Plain, typographic"}]
COVER_IDS=tuple(c["id"] for c in COVER_STYLES)
THEMES=[
    {"id":"corporate","name":"Corporate","description":"Classic consultancy report: serif headings, navy bands, ruled tables.",
        "body":"text","head":"serif","cover_style":"band","accent":"#1f4e79","secondary":"#a67c37",
        "text":"#1f2933","muted":"#5f6b7a","rule":"#d3d9e0","soft":"#f4f6f8","zebra":"#f7f9fb","head_fill":"accent","solid_sev":True},
    {"id":"modern","name":"Modern","description":"Bold colour blocks, large numerals and a clean humanist sans.",
        "body":"sans","head":"sans","cover_style":"full","accent":"#3b3fd8","secondary":"#0f172a",
        "text":"#1e2430","muted":"#647084","rule":"#dfe3ea","soft":"#f3f4f8","zebra":"#f7f8fb","head_fill":"dark","solid_sev":True},
    {"id":"minimal","name":"Minimal","description":"Monochrome and ink-saving: hairlines instead of fills, prints well on any printer.",
        "body":"text","head":"text","cover_style":"simple","accent":"#111827","secondary":"#6b7280",
        "text":"#111827","muted":"#5b6472","rule":"#c9ced6","soft":"#f6f6f7","zebra":"#ffffff","head_fill":"none","solid_sev":False},
]
THEME_BY_ID={t["id"]:t for t in THEMES}
# A built-in theme's own colour stored on a report (the picker writes it there) follows the theme like a stock colour does.
_THEME_ACCENTS=frozenset(t["accent"] for t in THEMES);_THEME_SECONDARY=frozenset(t["secondary"] for t in THEMES)
THEME_IDS=tuple(t["id"] for t in THEMES)
DEFAULT_THEME="corporate"
# Page furniture (mm). The print engine lays the body out inside these margins; headers and footers are stamped into them.
MARGINS={"top":24.0,"right":18.0,"bottom":21.0,"left":18.0}
PAGE_MM={"A4":(210.0,297.0),"Letter":(215.9,279.4)}
def _s(v):return "" if v is None else str(v)
def _hex(v,default):
    v=_s(v).strip()
    return v.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}",v) else default
def hex_rgb(v):
    v=_hex(v,"#000000")
    return int(v[1:3],16),int(v[3:5],16),int(v[5:7],16)
def mix(a,b,t):
    ra,rb=hex_rgb(a),hex_rgb(b)
    return "#%02x%02x%02x"%tuple(int(round(ra[i]+(rb[i]-ra[i])*t)) for i in range(3))
def luminance(c):
    r,g,b=[(x/255.0/12.92) if x/255.0<=0.03928 else ((x/255.0+0.055)/1.055)**2.4 for x in hex_rgb(c)]
    return 0.2126*r+0.7152*g+0.0722*b
def contrast(a,b):
    la,lb=luminance(a),luminance(b)
    return (max(la,lb)+0.05)/(min(la,lb)+0.05)
def on_color(fill):
    """Readable text colour for a solid fill: white, or near-black when the brand colour is a light one."""
    return "#111827" if luminance(fill)>0.36 else "#ffffff"
def ink_of(color,bg="#ffffff",need=4.5):
    """The colour itself when it reads on bg, else darkened until it does (brand colours are often too light for text)."""
    c=color
    for i in range(1,11):
        if contrast(c,bg)>=need:return c
        c=mix(color,"#111827",i/10.0)
    return "#111827"
def theme_id(v):
    v=_s(v).strip().lower()
    return v if v in THEME_BY_ID else DEFAULT_THEME
def resolve(branding=None,options=None):
    """Branding (+ per-export overrides) -> the concrete tokens every writer reads."""
    br=branding if isinstance(branding,dict) else {};op=options if isinstance(options,dict) else {}
    def pick(k):
        v=op.get(k)
        return v if isinstance(v,str) and v.strip() else br.get(k)
    th=THEME_BY_ID[theme_id(pick("theme"))]
    font=_s(pick("font")).strip().lower()
    f=FONT_BY_ID.get(font) or FONT_BY_ID["theme"]
    body=f["body"] or th["body"];head=f["head"] or th["head"]
    cover=_s(pick("cover_style")).strip().lower()
    if cover not in COVER_IDS:cover=th["cover_style"]
    # A report still on the stock colours takes the theme's palette; a colour the author chose always wins.
    accent=_hex(br.get("accent"),"");secondary=_hex(br.get("secondary"),"")
    if not accent or accent in STOCK_ACCENTS or accent in _THEME_ACCENTS:accent=th["accent"]
    if not secondary or secondary in STOCK_SECONDARY or secondary in _THEME_SECONDARY:secondary=th["secondary"]
    on_accent=on_color(accent);ink=ink_of(accent)
    head_fill={"accent":accent,"dark":"#0f172a","none":""}[th["head_fill"]]
    d={"theme":th["id"],"theme_name":th["name"],"font":f["id"],"body":body,"head":head,"mono":"mono","cover_style":cover,
        "accent":accent,"secondary":secondary,"on_accent":on_accent,"ink":ink,"accent_soft":mix(accent,"#ffffff",0.9),"accent_mid":mix(accent,"#ffffff",0.55),
        "on_accent_soft":mix(on_accent,accent,0.22),"secondary_ink":ink_of(secondary),
        "text":th["text"],"muted":th["muted"],"rule":th["rule"],"soft":th["soft"],"zebra":th["zebra"],
        "head_fill":head_fill,"head_on":on_color(head_fill) if head_fill else th["text"],"solid_sev":th["solid_sev"],
        "margins":dict(MARGINS),"sev":{s:{"fill":SEV_COLORS[s],"on":SEV_ON[s],"ink":SEV_INK[s],"tint":SEV_TINTS[s]} for s in SEVERITIES}}
    d["docx_body"]=FAMILIES[body]["docx"];d["docx_head"]=FAMILIES[head]["docx"];d["docx_mono"]=FAMILIES["mono"]["docx"]
    return d
def font_path(family,style=""):
    name=FAMILIES.get(family,{}).get("files",{}).get(style)
    if not name:return ""
    p=os.path.join(FONT_DIR,name)
    return p if os.path.isfile(p) else ""
def font_files(design):
    """Bundled TTF paths for the fpdf2 writers: {"body":{style:path},"head":{...},"mono":{...}}; a family is {} when not bundled."""
    out={}
    for role in ("body","head","mono"):
        fam=design[role];got={}
        for st in ("","B","I","K"):
            p=font_path(fam,st)
            if p:got[st]=p
        out[role]=got if got.get("") and got.get("B") else {}
    return out
def css_family(design,role):
    fam=FAMILIES[design[role]]
    return (f'"{fam["css"]}",' if fam["css"] else "")+fam["stack"]
_woff_cache={}
def _woff_b64(path):
    """TTF -> WOFF (zlib) for embedding: about half the size, and both engines read it."""
    key=(path,os.path.getmtime(path))
    if key in _woff_cache:return _woff_cache[key]
    try:
        from fontTools.ttLib import TTFont
        f=TTFont(path);f.flavor="woff";buf=io.BytesIO();f.save(buf)
        out=("font/woff","woff",base64.b64encode(buf.getvalue()).decode("ascii"))
    except Exception:
        with open(path,"rb") as fh:out=("font/ttf","truetype",base64.b64encode(fh.read()).decode("ascii"))
    _woff_cache[key]=out
    return out
_FACE={"":("400","normal"),"B":("700","normal"),"I":("400","italic"),"K":("900","normal")}
def font_face_css(design,embed=True,black=False):
    """@font-face rules for the families a document uses. embed=False names local fonts only (smaller file, system fallback)."""
    if not embed:return ""
    out=[];seen=set()
    for role in ("body","head","mono"):
        fam=FAMILIES[design[role]]
        if not fam["css"] or design[role] in seen:continue
        seen.add(design[role])
        for st,name in fam["files"].items():
            if st=="K" and not black:continue
            p=os.path.join(FONT_DIR,name)
            if not os.path.isfile(p):continue
            try:mime,fmt,b64=_woff_b64(p)
            except OSError:continue
            w,sty=_FACE[st]
            out.append(f'@font-face{{font-family:"{fam["css"]}";font-weight:{w};font-style:{sty};font-display:block;src:url(data:{mime};base64,{b64}) format("{fmt}")}}')
    return "".join(out)
def themes():
    """What the theme picker shows."""
    out=[]
    for t in THEMES:
        d=resolve({"theme":t["id"]})
        out.append({"id":t["id"],"name":t["name"],"description":t["description"],"default_font":"theme","default_cover_style":t["cover_style"],
            "fonts":[{"id":f["id"],"label":f["label"] if f["id"]!="theme" else f"Theme default ({_font_label(t)})"} for f in FONTS],
            "cover_styles":[dict(c) for c in COVER_STYLES],
            "preview":{"accent":d["accent"],"secondary":d["secondary"],"on_accent":d["on_accent"],"ink":d["ink"],"text":d["text"],"muted":d["muted"],"rule":d["rule"],"soft":d["soft"],
                "head_fill":d["head_fill"],"head_on":d["head_on"],"solid_sev":d["solid_sev"],"heading_serif":t["head"] in ("serif","system-serif"),"sev":dict(SEV_COLORS)}})
    return out
def _font_label(t):
    names={"sans":"Lato","text":"Noto Sans","serif":"Noto Serif"}
    return names[t["head"]] if t["head"]==t["body"] else f'{names[t["head"]]} + {names[t["body"]]}'
