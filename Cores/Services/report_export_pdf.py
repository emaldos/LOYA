"""PDF writer for the reporting render model (fpdf2). See report_export.prepare for the block shapes."""
import os,io,sys,logging,unicodedata
from Cores.Services import report_export as rx
TEXT=(31,41,55)
MUTED=(107,114,128)
RULE=(213,218,225)
SOFT=(246,248,250)
ZEBRA=(247,249,251)
# Family -> style -> candidate file names (first hit wins). Nothing is bundled: these ship with the OS.
_SANS=(
    {"":"segoeui.ttf","B":"segoeuib.ttf","I":"segoeuii.ttf","BI":"segoeuiz.ttf"},
    {"":"arial.ttf","B":"arialbd.ttf","I":"ariali.ttf","BI":"arialbi.ttf"},
    {"":"LiberationSans-Regular.ttf","B":"LiberationSans-Bold.ttf","I":"LiberationSans-Italic.ttf","BI":"LiberationSans-BoldItalic.ttf"},
    {"":"DejaVuSans.ttf","B":"DejaVuSans-Bold.ttf","I":"DejaVuSans-Oblique.ttf","BI":"DejaVuSans-BoldOblique.ttf"},
    {"":"NotoSans-Regular.ttf","B":"NotoSans-Bold.ttf","I":"NotoSans-Italic.ttf","BI":"NotoSans-BoldItalic.ttf"},
    {"":"Arial.ttf","B":"Arial Bold.ttf","I":"Arial Italic.ttf","BI":"Arial Bold Italic.ttf"},
)
_MONO=(
    {"":"consola.ttf","B":"consolab.ttf"},
    {"":"DejaVuSansMono.ttf","B":"DejaVuSansMono-Bold.ttf"},
    {"":"LiberationMono-Regular.ttf","B":"LiberationMono-Bold.ttf"},
    {"":"cour.ttf","B":"courbd.ttf"},
    {"":"NotoSansMono-Regular.ttf","B":"NotoSansMono-Bold.ttf"},
    {"":"Courier New.ttf","B":"Courier New Bold.ttf"},
)
_FALLBACK=("DejaVuSans.ttf","seguisym.ttf","NotoSansSymbols2-Regular.ttf","Arial Unicode.ttf")
# Script fallbacks (CJK, Arabic, Hebrew, Thai, Devanagari). Large files, so one is only loaded when the report holds characters the
# fonts above cannot draw.
_SCRIPT_FALLBACK=("NotoSansCJK-Regular.ttc","msgothic.ttc","YuGothR.ttc","msyh.ttc","malgun.ttf","simsun.ttc","PingFang.ttc","Hiragino Sans GB.ttc","DroidSansFallbackFull.ttf","wqy-microhei.ttc","wqy-zenhei.ttc",
    "NotoSansArabic-Regular.ttf","NotoNaskhArabic-Regular.ttf","tahoma.ttf","NotoSansHebrew-Regular.ttf","NotoSansThai-Regular.ttf","leelawui.ttf","NotoSansDevanagari-Regular.ttf","Nirmala.ttf","nirmala.ttc","Arial Unicode.ttf")
_MAX_SCRIPT_FONTS=3
_font_cache={}
def _font_dirs():
    dirs=[]
    if sys.platform.startswith("win"):
        dirs.append(os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows","Fonts"))
        local=os.environ.get("LOCALAPPDATA")
        if local:dirs.append(os.path.join(local,"Microsoft","Windows","Fonts"))
    elif sys.platform=="darwin":
        dirs+=["/System/Library/Fonts/Supplemental","/Library/Fonts",os.path.expanduser("~/Library/Fonts")]
    else:
        dirs+=["/usr/share/fonts","/usr/local/share/fonts",os.path.expanduser("~/.local/share/fonts"),os.path.expanduser("~/.fonts")]
    return [d for d in dirs if os.path.isdir(d)]
def _font_index():
    if "index" in _font_cache:return _font_cache["index"]
    idx={}
    for d in _font_dirs():
        try:
            for root,_dirs,files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".ttf",".ttc",".otf")):idx.setdefault(f.lower(),os.path.join(root,f))
        except OSError:pass
    _font_cache["index"]=idx
    return idx
def find_fonts():
    """{"sans":{style:path},"mono":{style:path},"fallback":[path]} from the OS font folders, or None to use the core fonts."""
    if "fonts" in _font_cache:return _font_cache["fonts"]
    idx=_font_index();out=None
    def pick(cands,need):
        for fam in cands:
            got={st:idx.get(name.lower()) for st,name in fam.items()}
            if all(got.get(st) for st in need):return {st:p for st,p in got.items() if p}
        return None
    sans=pick(_SANS,("","B","I","BI")) or pick(_SANS,("","B"))
    mono=pick(_MONO,("","B")) or pick(_MONO,("",))
    if sans and mono:
        fb=[idx[n.lower()] for n in _FALLBACK if n.lower() in idx and idx[n.lower()] not in sans.values()]
        out={"sans":sans,"mono":mono,"fallback":fb[:2],"script":[idx[n.lower()] for n in _SCRIPT_FALLBACK if n.lower() in idx and idx[n.lower()] not in fb[:2]]}
    _font_cache["fonts"]=out
    return out
_TRANSLIT={0x2014:"-",0x2013:"-",0x2012:"-",0x2010:"-",0x2011:"-",0x2192:"->",0x2190:"<-",0x21d2:"=>",0x2194:"<->",0x201c:'"',0x201d:'"',0x201e:'"',0x2018:"'",0x2019:"'",0x201a:"'",0x2026:"...",0x2022:"*",0x25cf:"*",0x25e6:"o",
    0x2265:">=",0x2264:"<=",0x2260:"!=",0x2248:"~",0x2611:"[x]",0x2610:"[ ]",0x2612:"[x]",0x2713:"[x]",0x2714:"[x]",0x2717:"[ ]",0x2718:"[ ]",0x2009:" ",0x202f:" ",0x200b:"",0x200c:"",0x200d:"",0xfeff:"",0x2500:"-",0x2502:"|",0x250c:"+",0x2510:"+",0x2514:"+",0x2518:"+",0x251c:"+",0x2524:"+",0x252c:"+",0x2534:"+",0x253c:"+",0x2550:"=",0x2551:"|",0x2588:"#",0x2591:".",0x2592:":",0x2593:"#",0x20ac:"EUR",0x2122:"(TM)"}
def translit(ch):
    """Closest printable stand-in for a character the active font cannot draw."""
    t=_TRANSLIT.get(ord(ch))
    if t is not None:return t
    d=unicodedata.normalize("NFKD",ch).encode("ascii","ignore").decode("ascii")
    return d if d else "?"
def latin1_safe(s):
    out=[]
    for ch in s:
        o=ord(ch)
        if o<0x80 or 0xa0<=o<=0xff:out.append(ch)
        else:out.append(translit(ch))
    return "".join(out)
def doc_text(doc):
    """Every string of the render model in one piece (used only to see which scripts the report needs)."""
    parts=[]
    def walk(o):
        if isinstance(o,str):parts.append(o)
        elif isinstance(o,dict):
            for k,v in o.items():
                if k not in ("asset","ctx","raw","data","logo"):walk(v)
        elif isinstance(o,(list,tuple)):
            for v in o:walk(v)
    for k in ("title","cover","sections","banner","footer","company","classification"):walk(doc.get(k))
    return "".join(parts)
def design_fonts(dz):
    """The report's bundled faces in the shape find_fonts returns (system fonts still back them up for other scripts)."""
    if not dz:return None
    try:
        from Cores.Services import report_design as _d
        files=_d.font_files(dz);body,mono=files.get("body"),files.get("mono")
        if not body or not mono:return None
        sysf=find_fonts() or {}
        sans={"":body[""],"B":body["B"],"I":body.get("I") or body[""],"BI":body["B"]}
        return {"sans":sans,"mono":{"":mono[""],"B":mono["B"]},"fallback":[p for p in (list((sysf.get("sans") or {}).values())[:1]+(sysf.get("fallback") or []))][:3],"script":sysf.get("script") or []}
    except Exception:return None
def write_pdf(doc,out_path,fonts="auto"):
    """fonts: "auto" = system TrueType fonts when found; None = core PDF fonts with transliteration (never fails on Unicode)."""
    from fpdf import FPDF
    from fpdf.fonts import FontFace
    from fpdf.enums import XPos,YPos
    logging.getLogger("fpdf").setLevel(logging.ERROR)
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    if fonts=="auto":fonts=design_fonts(doc.get("design")) or find_fonts()
    # This writer draws the basic block kinds; callouts, dashboards, matrices and timelines arrive as tables, labels and quotes.
    doc=dict(doc,sections=[dict(s,blocks=rx.legacy_blocks(s["blocks"])) for s in doc["sections"]])
    o=doc["options"];cover=doc["cover"]
    accent=rx.hex_rgb(doc["accent"]);secondary=rx.hex_rgb(doc["secondary"])
    on_accent=rx.hex_rgb(doc.get("on_accent") or "#ffffff");light=on_accent==(255,255,255)
    on_accent_soft=(226,232,240) if light else (55,65,81)
    # Accent used as a text colour (headings, links, labels) must stay readable on white even when the brand colour is light.
    ink=accent if light else rx.hex_rgb(rx.mix(doc["accent"],"#111827",0.55))
    banner=doc["banner"] or (doc["classification"].upper() if doc["classification"] else "")
    class PDF(FPDF):
        plain_page=False
        def header(self):
            if self.plain_page:return
            y=0
            if banner:
                self.set_fill_color(*accent);self.rect(0,0,self.w,6.2,style="F")
                self.set_font(SANS,"B",6.8);self.set_text_color(*on_accent)
                self.set_xy(0,0);self.cell(self.w,6.2,fit(T(banner),self.w-20),align="C")
                y=6.2
            self.set_font(SANS,"",7.8);self.set_text_color(*MUTED)
            half=(self.w-self.l_margin-self.r_margin)/2
            self.set_xy(self.l_margin,y+4);self.cell(half,5,fit(T(doc["company"]),half-4),align="L")
            self.set_xy(self.l_margin+half,y+4);self.cell(half,5,fit(T(doc["title"]),half-4),align="R")
            self.set_draw_color(*RULE);self.set_line_width(0.25);self.line(self.l_margin,y+10,self.w-self.r_margin,y+10)
            self.set_xy(self.l_margin,self.t_margin)
        def footer(self):
            if self.plain_page:return
            y=self.h-13;width=self.w-self.l_margin-self.r_margin
            self.set_draw_color(*RULE);self.set_line_width(0.25);self.line(self.l_margin,y,self.w-self.r_margin,y)
            self.set_xy(self.l_margin,y+1.5);self.set_font(SANS,"B",7.5);self.set_text_color(*ink)
            self.cell(width*0.28,5,fit(T(doc["classification"]),width*0.28-2),align="L")
            self.set_font(SANS,"",7.5);self.set_text_color(*MUTED)
            self.cell(width*0.44,5,fit(T(doc["footer"]),width*0.44-2),align="C")
            self.cell(width*0.28,5,f"Page {self.page_no()} of {{nb}}",align="R")
    pdf=PDF(format="Letter" if o["page_size"]=="Letter" else "A4",unit="mm")
    cover_cov={"sans":None,"mono":None}
    if fonts:
        try:
            for st,p in fonts["sans"].items():pdf.add_font("rsans",st,p)
            for st,p in fonts["mono"].items():pdf.add_font("rmono",st,p)
            fb=[]
            for i,p in enumerate(fonts.get("fallback") or []):
                try:pdf.add_font(f"rfb{i}","",p);fb.append(f"rfb{i}")
                except Exception:pass
            # Characters outside the base fonts pull in script fonts, each only when it actually covers some of them.
            have=set(pdf.fonts["rsans"].cmap)
            for f in fb:have|=set(pdf.fonts[f].cmap)
            missing={ord(ch) for ch in doc_text(doc) if ord(ch)>0x2ff}-have
            for p in fonts.get("script") or []:
                if not missing or len(fb)>=len(fonts.get("fallback") or [])+_MAX_SCRIPT_FONTS:break
                key=f"rfs{len(fb)}"
                try:
                    pdf.add_font(key,"",p)
                    # CFF-flavoured collections (e.g. Noto CJK .ttc) are skipped: embedded as TrueType they upset strict PDF readers.
                    got=missing&set(pdf.fonts[key].cmap) if "glyf" in pdf.fonts[key].ttfont else set()
                    if got:fb.append(key);missing-=got
                    else:del pdf.fonts[key]
                except Exception:pdf.fonts.pop(key,None)
            if fb:pdf.set_fallback_fonts(fb,exact_match=False)
            def cov(key):
                c=set(pdf.fonts[key].cmap)
                for f in fb:c|=set(pdf.fonts[f].cmap)
                return c
            cover_cov={"sans":cov("rsans"),"mono":cov("rmono")}
        except Exception:
            fonts=None;pdf=PDF(format="Letter" if o["page_size"]=="Letter" else "A4",unit="mm")
    SANS="rsans" if fonts else "Helvetica";MONO="rmono" if fonts else "Courier"
    sans_styles=set(fonts["sans"]) if fonts else {"","B","I","BI"};mono_styles=set(fonts["mono"]) if fonts else {"","B","I","BI"}
    def T(s,mono=False):
        s=rx._s(s)
        if s.isascii():return s
        if not fonts:return latin1_safe(s)
        c=cover_cov["mono" if mono else "sans"]
        return "".join(ch if (ord(ch) in c or ch=="\n") else translit(ch) for ch in s)
    def fit(s,width):
        if pdf.get_string_width(s)<=width:return s
        while s and pdf.get_string_width(s+"...")>width:s=s[:-1]
        return s.rstrip()+"..."
    def font(style="",size=10,mono=False):
        st="".join(x for x in "BI" if x in style)
        avail=mono_styles if mono else sans_styles
        if st not in avail:st="B" if "B" in st and "B" in avail else ""
        if "U" in style:st+="U"
        try:pdf.set_font(MONO if mono else SANS,st+("S" if "S" in style else ""),size)
        except Exception:pdf.set_font(MONO if mono else SANS,st,size)
    pdf.set_title(doc["title"]);pdf.set_author(cover["authors"] or doc["company"]);pdf.set_creator("LOYA NG");pdf.set_subject(" - ".join(x for x in (doc["meta"]["report_type"],doc["meta"]["client"]) if x))
    if doc["classification"]:pdf.set_keywords(doc["classification"])
    top=24+(6.2 if banner else 0)
    pdf.set_margins(20,top,20);pdf.set_auto_page_break(True,margin=19)
    CW=pdf.w-pdf.l_margin-pdf.r_margin;LM=pdf.l_margin
    links={}
    def link_for(anchor):
        if anchor not in links:links[anchor]=pdf.add_link()
        return links[anchor]
    def here(anchor):pdf.set_link(link_for(anchor),y=max(0,pdf.get_y()-4),page=pdf.page)
    def need(h):
        if pdf.get_y()+h>pdf.h-pdf.b_margin:pdf.add_page()
    def text_color(c):pdf.set_text_color(*c)
    # ---- inline text ----
    def write_runs(runs,size=10,color=TEXT,lh=5.1,indent=0,base="",after=2.2):
        x0=LM+indent
        pdf.set_left_margin(x0);pdf.set_x(x0);prev_space=True
        for r in runs or []:
            if r.get("redact"):
                prev_space=False
                font("",size);w=pdf.get_string_width("REDACTED")+2
                if pdf.get_x()+w>pdf.w-pdf.r_margin:pdf.ln(lh)
                pdf.set_fill_color(0,0,0);pdf.rect(pdf.get_x(),pdf.get_y()+0.7,w,lh-1.4,style="F");pdf.set_x(pdf.get_x()+w+0.6)
                continue
            st=base+("B" if r.get("b") else "")+("I" if r.get("i") else "")+("U" if r.get("u") or r.get("href") else "")+("S" if r.get("s") else "")
            code=bool(r.get("code"))
            font(st,size-0.8 if code else size,mono=code)
            href=rx._safe_href(r.get("href"))
            text_color(ink if href else ((71,85,105) if code else color))
            text=T(r.get("text",""),code)
            # A styled run that starts mid-line with a word too long for the rest of the line would be split inside the word
            # (fpdf only sees this run); move it to the next line when the break before it is a legal one.
            word=text.split("\n",1)[0].split(" ",1)[0]
            if word and prev_space and pdf.get_x()>x0+0.5:
                ww=pdf.get_string_width(word)
                if ww>pdf.w-pdf.r_margin-pdf.get_x()-2.2 and ww<=pdf.w-pdf.r_margin-x0-2.2:pdf.ln(lh)
            pdf.write(lh,text,link=href or "")
            prev_space=text.endswith((" ","\n"))
        pdf.ln(lh+after)
        pdf.set_left_margin(LM);pdf.set_x(LM)
    def plain(text,size=10,style="",color=TEXT,lh=5.1,indent=0,after=2.2,align="L",mono=False):
        font(style,size,mono=mono);text_color(color)
        pdf.set_x(LM+indent)
        pdf.multi_cell(CW-indent,lh,T(text,mono),align=align,new_x=XPos.LMARGIN,new_y=YPos.NEXT)
        if after:pdf.ln(after)
    # ---- blocks ----
    def pre_lines(text,width,size):
        font("",size,mono=True)
        cw=pdf.get_string_width("M") or 1.6
        n=max(8,int((width-0.2)/cw))
        out=[]
        for line in T(text,True).split("\n"):
            if not line:out.append("");continue
            if line.isascii():
                for i in range(0,len(line),n):out.append(line[i:i+n])
            else:
                cur="";curw=0.0
                for ch in line:
                    w=pdf.get_string_width(ch)
                    if curw+w>width-0.2 and cur:out.append(cur);cur="";curw=0.0
                    cur+=ch;curw+=w
                out.append(cur)
        return out
    def pre_block(text,indent=0,size=7.8,after=3,lang=""):
        x=LM+indent;w=CW-indent;pad=2.4;lh=3.75
        lines=pre_lines(text,w-2*pad-1,size)
        need(min(len(lines),4)*lh+2*pad)
        def edge(h):
            pdf.set_fill_color(*SOFT);pdf.rect(x,pdf.get_y(),w,h,style="F")
            pdf.set_fill_color(*secondary);pdf.rect(x,pdf.get_y(),0.9,h,style="F")
        edge(pad)
        if lang:
            font("",5.8,mono=True);label=T(lang.upper(),True);lw=pdf.get_string_width(label)+3
            pdf.set_fill_color(233,237,242);pdf.rect(x+w-lw,pdf.get_y(),lw,3.1,style="F")
            text_color((100,116,139));pdf.set_xy(x+w-lw,pdf.get_y());pdf.cell(lw,3.1,label,align="C");pdf.set_x(LM)
        pdf.set_y(pdf.get_y()+pad)
        font("",size,mono=True);text_color((30,41,59))
        for line in lines:
            if pdf.get_y()+lh>pdf.h-pdf.b_margin:
                pdf.add_page();font("",size,mono=True);text_color((30,41,59))
            edge(lh)
            if line:
                pdf.set_x(x+pad+1);pdf.cell(w-2*pad-1,lh,line)
            pdf.set_y(pdf.get_y()+lh)
        if pdf.get_y()+pad<=pdf.h-pdf.b_margin:
            edge(pad);pdf.set_y(pdf.get_y()+pad)
        pdf.ln(after)
    def image_block(b,indent=0):
        a=b.get("asset");cap=b.get("caption") or ""
        if not a:
            plain(f"[Image not available{': '+(cap or b.get('alt')) if (cap or b.get('alt')) else ''}]",9,"I",MUTED,indent=indent);return
        data,_mime=rx.image_as(a)
        iw,ih=a.get("width") or 0,a.get("height") or 0
        if not data or not iw or not ih:
            plain("[Image could not be embedded]",9,"I",MUTED,indent=indent);return
        maxw=CW-indent
        w=maxw*b["width"]/100.0 if b.get("width") else min(maxw,iw*25.4/110.0)
        h=w*ih/iw
        maxh=(pdf.h-pdf.t_margin-pdf.b_margin)*0.72
        if h>maxh:h=maxh;w=h*iw/ih
        need(h+(7 if cap else 2))
        x=LM+indent+(maxw-w)/2;y=pdf.get_y()
        try:
            pdf.image(io.BytesIO(data),x=x,y=y,w=w,h=h)
            pdf.set_draw_color(*RULE);pdf.set_line_width(0.2);pdf.rect(x,y,w,h)
        except Exception:
            plain("[Image could not be embedded]",9,"I",MUTED,indent=indent);return
        pdf.set_y(y+h+1.5)
        if cap:plain(cap,8.2,"I",MUTED,lh=4,indent=indent,after=2.5,align="C")
        else:pdf.ln(2)
    def cell_style(c,size,zebra_fill=None):
        emph="B" if (c.get("bold") or c.get("header")) else ""
        fill=rx.hex_rgb(c["fill"]) if c.get("fill") else ((238,241,245) if c.get("header") else (zebra_fill or (255,255,255)))
        color=rx.hex_rgb(c["color"]) if c.get("color") else ((55,65,81) if c.get("header") else TEXT)
        if c.get("link"):color=ink
        fam=MONO if c.get("mono") else SANS
        if emph and c.get("mono") and "B" not in mono_styles:emph=""
        return FontFace(family=fam,emphasis=emph or None,size_pt=size-0.6 if c.get("mono") else size,color=color,fill_color=fill)
    def table_cols(b,indent):
        ncols=max(len(r) for r in b["rows"]);width=CW-indent
        widths=b.get("widths")
        if not widths or len(widths)!=ncols:widths=[1.0/ncols]*ncols
        return width,tuple(width*w/sum(widths) for w in widths)
    def table_heights(b,indent=0,size=8.6):
        """Estimated row heights (first 60 rows) and the total, or a huge total for long tables."""
        rows=b["rows"];_width,col_w=table_cols(b,indent)
        def row_h(row):
            lines=1;ci=0
            for c in row:
                if c is None:ci+=1;continue
                span=int(c.get("colspan",1));w=max(4.0,sum(col_w[ci:ci+span])-3.4);ci+=span
                mono=bool(c.get("mono"));font("B" if (c.get("bold") or c.get("header")) else "",size-0.6 if mono else size,mono=mono)
                text=T(rx.runs_text(c["runs"]) if c.get("runs") is not None else c.get("text",""),mono)
                n=sum(max(1,int(pdf.get_string_width(part)/w*1.12)+1) for part in text.split("\n")) if text else 1
                lines=max(lines,n)
            return lines*4.3+2.6
        heights=[row_h(r) for r in rows[:60]]
        return heights,(sum(heights) if len(rows)<=60 else 10**6)
    def table_room(b,indent=0,extra=0):
        """Keep a table that fits on one page in one piece, and never leave its heading row (or a label above it) alone at a page bottom."""
        heights,est=table_heights(b,indent)
        room=pdf.h-pdf.b_margin-pdf.get_y()-extra;page_h=pdf.h-pdf.t_margin-pdf.b_margin
        if est>room and est<=page_h*0.92 and room<page_h*0.75:pdf.add_page()
        else:need(extra+min(est,sum(heights[:3])+1))
    def table_block(b,indent=0,size=8.6):
        rows=b["rows"]
        if not rows:return
        width,col_w=table_cols(b,indent)
        head=bool(b.get("header"));kv=bool(b.get("kv"))
        table_room(b,indent)
        pdf.set_draw_color(*RULE);pdf.set_line_width(0.2);font("",size);text_color(TEXT)
        pdf.set_x(LM+indent)
        try:
            with pdf.table(col_widths=col_w,width=width,align="LEFT",first_row_as_headings=head,headings_style=FontFace(emphasis="B",color=on_accent,fill_color=accent),
                    line_height=4.3,padding=(1.3,1.6,1.3,1.6),text_align="LEFT",v_align="TOP",borders_layout="ALL",repeat_headings=1) as t:
                for ri,row in enumerate(rows):
                    r=t.row()
                    is_head=head and ri==0
                    zebra=None if (kv or b.get("nozebra") or is_head) else (ZEBRA if (ri-(1 if head else 0))%2 else None)
                    for c in row:
                        if c is None:continue
                        text=T(rx.runs_text(c["runs"]) if c.get("runs") is not None else c.get("text",""),bool(c.get("mono")))
                        align={"C":"CENTER","R":"RIGHT"}.get(c.get("align"),"LEFT")
                        lk=rx._s(c.get("link"))
                        kw={"align":align,"colspan":int(c.get("colspan",1))}
                        if c.get("fill") and c.get("align")=="C":kw["v_align"]="MIDDLE"
                        if lk.startswith("#"):kw["link"]=link_for(lk[1:])
                        if is_head:
                            r.cell(text,**kw)
                        else:r.cell(text,style=cell_style(c,size,zebra),**kw)
        except Exception:
            # A table fpdf cannot lay out (pathological spans/widths) still exports, as plain rows.
            for row in rows:plain(" | ".join(T(c.get("text","")) for c in row if c),size,indent=indent,after=0.6)
        pdf.set_x(LM);pdf.ln(3.2)
    def list_block(b,indent=0):
        for i,it in enumerate(b["items"]):
            need(6)
            y=pdf.get_y()
            if b["ordered"]:
                font("",10);text_color(TEXT);pdf.set_xy(LM+indent,y);pdf.cell(6.5,5.1,f"{i+1}.",align="R")
            else:
                pdf.set_fill_color(*secondary);pdf.ellipse(LM+indent+3.4,y+1.95,1.25,1.25,style="F")
            pdf.set_xy(LM+indent+8,y)
            if it["runs"]:write_runs(it["runs"],indent=indent+8,after=0.6)
            if it["blocks"]:blocks(it["blocks"],indent+8)
        pdf.ln(1.8)
    def figure_block(b,indent=0):
        need(18)
        cap=b.get("caption") or ""
        if cap or b.get("info"):
            pdf.set_x(LM+indent);pdf.set_left_margin(LM+indent)
            font("B",8.2);text_color((55,65,81));pdf.write(4.2,T(cap))
            if b.get("info"):
                font("",8.2);text_color(MUTED);pdf.write(4.2,T(("  \u00b7  " if cap else "")+b["info"]))
            pdf.ln(5);pdf.set_left_margin(LM);pdf.set_x(LM)
        if b.get("pre"):pre_block(b["pre"],indent,after=1.5 if (b.get("truncated") or b.get("image")) else 3)
        if b.get("image"):image_block(b["image"],indent)
        if b.get("truncated"):plain(f"Output truncated: {int(b['truncated'])} more line(s) not shown.",7.6,"I",MUTED,lh=3.8,indent=indent,after=3)
    def chart_block(b):
        counts,total=b["counts"],b["total"]
        need(52)
        y0=pdf.get_y()+2;cx=LM+26;cy=y0+22;r=19
        if total:
            ang=90.0
            for s in rx.SEVERITIES:
                if not counts[s]:continue
                span=360.0*counts[s]/total
                pdf.set_fill_color(*rx.hex_rgb(rx.SEV_COLORS[s]))
                if span>=359.99:pdf.ellipse(cx-r,cy-r,2*r,2*r,style="F")
                else:pdf.solid_arc(cx-r,cy-r,2*r,ang-span,ang,style="F")
                ang-=span
        else:
            pdf.set_fill_color(238,241,245);pdf.ellipse(cx-r,cy-r,2*r,2*r,style="F")
        pdf.set_fill_color(255,255,255);pdf.ellipse(cx-r*0.6,cy-r*0.6,r*1.2,r*1.2,style="F")
        font("B",17);text_color((17,24,39));pdf.set_xy(cx-r,cy-6.2);pdf.cell(2*r,8,str(total),align="C")
        font("",7);text_color(MUTED);pdf.set_xy(cx-r,cy+1.6);pdf.cell(2*r,4,"finding" if total==1 else "findings",align="C")
        bx=LM+86;bw=CW-86-14;mx=max([counts[s] for s in rx.SEVERITIES]+[1])
        for i,s in enumerate(rx.SEVERITIES):
            y=y0+3+i*8
            font("",8.6);text_color((55,65,81));pdf.set_xy(LM+50,y);pdf.cell(33,5.4,rx.SEV_LABELS[s],align="R")
            pdf.set_fill_color(241,243,246);pdf.rect(bx,y,bw,5.4,style="F")
            if counts[s]:
                pdf.set_fill_color(*rx.hex_rgb(rx.SEV_COLORS[s]));pdf.rect(bx,y,max(0.8,bw*counts[s]/mx),5.4,style="F")
            font("B",8.6);text_color((17,24,39));pdf.set_xy(bx+bw+2,y);pdf.cell(12,5.4,str(counts[s]))
        pdf.set_xy(LM,y0+48)
    def finding_head(b):
        col=rx.hex_rgb(rx.SEV_COLORS[b["severity"]]);tint=rx.hex_rgb(rx.SEV_TINTS[b["severity"]])
        font("B",10.5);idw=max(17,pdf.get_string_width(T(b["id"]))+7)
        tag=rx.SEV_LABELS[b["severity"]].upper()+(f"  {b['cvss']}" if b.get("cvss") else "")
        font("B",7.6);tagw=pdf.get_string_width(tag)+7
        tw=CW-idw-tagw
        font("B",11.5)
        try:n=len(pdf.multi_cell(tw-5,5.4,T(b["title"]),dry_run=True,output="LINES",align="L"))
        except Exception:n=1
        h=max(10.5,n*5.4+4.6)
        if pdf.get_y()+h+42>pdf.h-pdf.b_margin:pdf.add_page()
        else:pdf.ln(4)
        y=pdf.get_y()
        here(b["anchor"])
        try:pdf.start_section(T(f"{b['id']}  {b['title']}"),level=1)
        except Exception:pass
        toc_meta.append(b["severity"])
        pdf.set_fill_color(*col);pdf.rect(LM,y,idw,h,style="F")
        pdf.set_fill_color(248,250,252);pdf.rect(LM+idw,y,tw,h,style="F")
        pdf.set_fill_color(*tint);pdf.rect(LM+idw+tw,y,tagw,h,style="F")
        pdf.set_draw_color(*RULE);pdf.set_line_width(0.2);pdf.rect(LM,y,CW,h)
        font("B",10.5);text_color(rx.hex_rgb(rx.SEV_ON[b["severity"]]));pdf.set_xy(LM,y);pdf.cell(idw,h,T(b["id"]),align="C")
        font("B",11.5);text_color((17,24,39));pdf.set_xy(LM+idw+2.5,y+(h-n*5.4)/2)
        pdf.multi_cell(tw-5,5.4,T(b["title"]),align="L",new_x=XPos.LMARGIN,new_y=YPos.NEXT)
        font("B",7.6);text_color(rx.hex_rgb(rx.SEV_INK[b["severity"]]));pdf.set_xy(LM+idw+tw,y);pdf.cell(tagw,h,tag,align="C")
        pdf.set_xy(LM,y+h+2.6)
    def blocks(bl,indent=0):
        for bi,b in enumerate(bl):
            t=b["t"];nxt=bl[bi+1] if bi+1<len(bl) else None
            if t=="p":
                need(6);write_runs(b["runs"],indent=indent)
            elif t=="h":
                need(18);pdf.ln(1.5)
                write_runs(b["runs"],size=12 if b["level"]<=3 else 10.6,color=(17,24,39) if b["level"]<=3 else (55,65,81),lh=6,indent=indent,base="B",after=1.2)
            elif t=="label":
                if nxt and nxt["t"]=="table" and nxt["rows"]:table_room(nxt,indent,8.5)
                elif nxt and nxt["t"]=="chart":need(62)
                else:need(16)
                pdf.ln(1.2)
                font("B",8);text_color(ink);pdf.set_x(LM+indent)
                pdf.cell(CW-indent,4.6,T(b["text"]).upper(),new_x=XPos.LMARGIN,new_y=YPos.NEXT);pdf.ln(1.4)
            elif t=="pre":pre_block(b["text"],indent,lang=b.get("lang") or "")
            elif t=="quote":
                page,y=pdf.page,pdf.get_y()
                blocks(b["blocks"],indent+5)
                y1=pdf.get_y()-2.2;pdf.set_fill_color(*secondary)
                if pdf.page==page and y1>y:pdf.rect(LM+indent+1,y,0.9,y1-y,style="F")
                elif y1>pdf.t_margin:pdf.rect(LM+indent+1,pdf.t_margin,0.9,y1-pdf.t_margin,style="F")
            elif t=="list":list_block(b,indent)
            elif t=="table":table_block(b,indent)
            elif t=="hr":
                pdf.ln(1.5);pdf.set_draw_color(*RULE);pdf.set_line_width(0.25);pdf.line(LM+indent,pdf.get_y(),LM+CW,pdf.get_y());pdf.ln(3.5)
            elif t=="image":image_block(b,indent)
            elif t=="figure":figure_block(b,indent)
            elif t=="chart":chart_block(b)
            elif t=="finding":finding_head(b)
    toc_meta=[]
    # ---- cover ----
    if o["include_cover"]:
        pdf.plain_page=True;pdf.set_auto_page_break(False);pdf.add_page()
        W,H=pdf.w,pdf.h;x=22;tw=W-2*x
        font("B",28)
        try:n_title=len(pdf.multi_cell(tw,12,T(cover["title"]),dry_run=True,output="LINES",align="L"))
        except Exception:n_title=1
        n_title=min(n_title,6)
        band=max(H*0.44,74+n_title*12+(22 if cover["client"] else 8))
        pdf.set_fill_color(*accent);pdf.rect(0,0,W,band,style="F")
        pdf.set_fill_color(*secondary);pdf.rect(0,band,W,2.2,style="F")
        font("B",10.5);pdf.set_text_color(*on_accent)
        pdf.set_xy(x,24)
        if cover["company"]:pdf.cell(tw*0.6,8,fit(T(cover["company"]).upper(),tw*0.6),align="L")
        logo=cover.get("logo")
        if logo and logo.get("width") and logo.get("height"):
            data,_m=rx.image_as(logo)
            if data:
                lh=17.0;lw=lh*logo["width"]/logo["height"]
                if lw>52:lw=52.0;lh=lw*logo["height"]/logo["width"]
                try:
                    pdf.set_fill_color(255,255,255);pdf.rect(W-x-lw-5,19,lw+5,lh+5,style="F",round_corners=True,corner_radius=1.2)
                    pdf.image(io.BytesIO(data),x=W-x-lw-2.5,y=21.5,w=lw,h=lh)
                except Exception:pass
        y=band-18-n_title*12-(16 if cover["client"] else 0)
        if cover["subtitle"]:
            font("",10.5);pdf.set_text_color(*on_accent_soft);pdf.set_xy(x,y-9);pdf.cell(tw,6,fit(T(cover["subtitle"]).upper(),tw))
        font("B",28);pdf.set_text_color(*on_accent);pdf.set_xy(x,y)
        pdf.multi_cell(tw,12,T(cover["title"]),align="L",new_x=XPos.LMARGIN,new_y=YPos.NEXT,max_line_height=12)
        if cover["client"]:
            font("",14);pdf.set_text_color(*on_accent_soft);pdf.set_xy(x,pdf.get_y()+3);pdf.cell(tw,8,fit(T("Prepared for "+cover["client"]),tw))
        y=band+16
        for k,v in cover["facts"]:
            if y>H-52:break
            font("",7.8);text_color(MUTED);pdf.set_xy(x,y+0.8);pdf.cell(tw*0.3,6,T(k).upper())
            font("",11);text_color(TEXT);pdf.set_xy(x+tw*0.32,y)
            pdf.multi_cell(tw*0.68,6,T(v),align="L",new_x=XPos.LMARGIN,new_y=YPos.NEXT)
            y=pdf.get_y()+2.2
            pdf.set_draw_color(229,231,235);pdf.set_line_width(0.2);pdf.line(x,y,W-x,y);y+=2.4
        if cover["classification"]:
            font("B",9);label=T(cover["classification"]).upper();pw=pdf.get_string_width(label)+12
            pdf.set_draw_color(*accent);pdf.set_line_width(0.5);pdf.rect(x,H-34,pw,9.5)
            text_color(ink);pdf.set_xy(x,H-34);pdf.cell(pw,9.5,label,align="C")
        if doc["footer"]:
            font("",7.8);text_color(MUTED);pdf.set_xy(W-x-tw*0.55,H-36)
            pdf.multi_cell(tw*0.55,4,T(doc["footer"]),align="R",new_x=XPos.LMARGIN,new_y=YPos.NEXT)
        pdf.plain_page=False;pdf.set_auto_page_break(True,margin=19)
    # ---- table of contents ----
    def render_toc(p,outline):
        font("B",19);text_color(ink);p.set_x(LM);p.cell(CW,10,"Table of Contents",new_x=XPos.LMARGIN,new_y=YPos.NEXT)
        p.set_draw_color(*accent);p.set_line_width(0.6);p.line(LM,p.get_y()+1,LM+CW,p.get_y()+1);p.ln(6)
        for i,sec in enumerate(outline):
            lvl=sec.level;lh=7.2 if lvl==0 else 5.4
            if p.get_y()+lh>p.h-p.b_margin:p.add_page()
            y=p.get_y();x=LM+(7 if lvl else 0)
            lk=p.add_link(page=sec.page_number)
            if lvl and i<len(toc_meta) and toc_meta[i]:
                p.set_fill_color(*rx.hex_rgb(rx.SEV_COLORS[toc_meta[i]]));p.ellipse(x-4.2,y+lh/2-1,2,2,style="F")
            font("B" if lvl==0 else "",10.2 if lvl==0 else 9);text_color(TEXT if lvl==0 else (55,65,81))
            num=str(sec.page_number);nw=p.get_string_width(num)+1
            name=fit(sec.name,CW-(x-LM)-nw-6)
            p.set_xy(x,y);p.cell(CW-(x-LM)-nw,lh,name,link=lk)
            x1=x+p.get_string_width(name)+2;x2=LM+CW-nw-2
            if x2>x1:
                p.set_draw_color(203,213,225);p.set_line_width(0.2);p.set_dash_pattern(dash=0.3,gap=1.1)
                p.line(x1,y+lh-2.1,x2,y+lh-2.1);p.set_dash_pattern()
            p.set_xy(LM+CW-nw,y);p.cell(nw,lh,num,align="R",link=lk)
            p.set_xy(LM,y+lh)
    if o["include_toc"] and doc["toc"]:
        pdf.add_page()
        usable=pdf.h-pdf.t_margin-pdf.b_margin-18
        est=sum(7.2 if t["level"]==1 else 5.4 for t in doc["toc"])
        pdf.insert_toc_placeholder(render_toc,pages=max(1,int(est//usable)+1),allow_extra_pages=True)
    # ---- sections ----
    first=True
    for sec in doc["sections"]:
        if not (first and pdf.page and not o["include_toc"] and not o["include_cover"]):
            if not (first and o["include_toc"] and doc["toc"]):pdf.add_page()
        first=False
        here(sec["anchor"])
        try:pdf.start_section(T(sec["heading"]),level=0)
        except Exception:pass
        toc_meta.append("")
        font("B",19);text_color(ink);pdf.set_x(LM)
        pdf.multi_cell(CW,9,T(sec["heading"]),align="L",new_x=XPos.LMARGIN,new_y=YPos.NEXT)
        pdf.set_draw_color(*accent);pdf.set_line_width(0.6);pdf.line(LM,pdf.get_y()+1.2,LM+CW,pdf.get_y()+1.2);pdf.ln(6.5)
        blocks(sec["blocks"])
    if not pdf.page:
        pdf.add_page();plain("This report has no visible sections.",10,"I",MUTED)
    pdf.output(out_path)
    return pdf.pages_count
