"""Word (.docx) writer for the reporting render model (python-docx). The result is meant to be edited further:
real heading styles, a TOC field, PAGE/NUMPAGES fields, list styles and ordinary tables."""
import io,re
from Cores.Services import report_export as rx
# WordprocessingML is order-sensitive inside property elements; Word may refuse a file whose children are out of sequence.
_ORDER={
    "pPr":"pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange".split(),
    "rPr":"rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath".split(),
    "tblPr":"tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription".split(),
    "tcPr":"cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark".split(),
}
def _local(el):return el.tag.rsplit("}",1)[-1]
def _put(parent,el):
    """Insert a property child at its schema position, replacing an existing one of the same kind."""
    order=_ORDER.get(_local(parent));name=_local(el)
    for old in [c for c in parent if _local(c)==name]:parent.remove(old)
    if not order or name not in order:parent.append(el);return el
    after=set(order[order.index(name)+1:])
    for i,child in enumerate(parent):
        if _local(child) in after:parent.insert(i,el);return el
    parent.append(el)
    return el
def write_docx(doc,out_path):
    from docx import Document
    from docx.shared import Pt,Mm,RGBColor,Emu
    from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_TAB_ALIGNMENT,WD_BREAK
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    doc=dict(doc,sections=[dict(s,blocks=rx.legacy_blocks(s["blocks"])) for s in doc["sections"]])
    o=doc["options"];cover=doc["cover"];dz=doc.get("design") or rx.design.resolve({})
    accent=doc["accent"][1:].upper();secondary=doc["secondary"][1:].upper()
    on_accent=(doc.get("on_accent") or "#ffffff")[1:].upper();light=on_accent=="FFFFFF"
    on_soft="E2E8F0" if light else "374151"
    # Accent as a text colour must stay readable on white when the brand colour is a light one.
    ink=accent if light else rx.mix(doc["accent"],"#111827",0.55)[1:].upper()
    def rgb(h):return RGBColor(*rx.hex_rgb(h if h.startswith("#") else "#"+h))
    d=Document()
    # Fonts, colours and the cover follow the report theme (same tokens as the HTML/PDF design); Word substitutes a missing font itself.
    FONT=dz["docx_body"];HEAD=dz["docx_head"];MONO=dz["docx_mono"]
    TEXT=dz["text"][1:].upper();MUTED=dz["muted"][1:].upper();RULE=dz["rule"][1:].upper();SOFT=dz["soft"][1:].upper()
    head_fill=dz["head_fill"][1:].upper() if dz["head_fill"] else "";head_on=dz["head_on"][1:].upper()
    minimal=dz["theme"]=="minimal";modern=dz["theme"]=="modern"
    # ---- page ----
    sec=d.sections[0]
    sec.orientation=WD_ORIENT.PORTRAIT
    if o["page_size"]=="Letter":sec.page_width,sec.page_height=Mm(215.9),Mm(279.4)
    else:sec.page_width,sec.page_height=Mm(210),Mm(297)
    sec.left_margin=sec.right_margin=Mm(20);sec.top_margin=Mm(24);sec.bottom_margin=Mm(20)
    sec.header_distance=Mm(9);sec.footer_distance=Mm(9)
    CW=sec.page_width-sec.left_margin-sec.right_margin
    # ---- styles ----
    def set_font(style,name,size=None,bold=None,color=None,italic=None):
        f=style.font;f.name=name
        rpr=style.element.get_or_add_rPr();rf=rpr.find(qn("w:rFonts"))
        if rf is None:rf=OxmlElement("w:rFonts");rpr.insert(0,rf)
        for a in ("w:ascii","w:hAnsi","w:cs","w:eastAsia"):rf.set(qn(a),name)
        for a in ("w:asciiTheme","w:hAnsiTheme","w:cstheme","w:eastAsiaTheme"):
            if rf.get(qn(a)) is not None:del rf.attrib[qn(a)]
        if size is not None:f.size=Pt(size)
        if bold is not None:f.bold=bold
        if italic is not None:f.italic=italic
        if color is not None:f.color.rgb=rgb(color)
    st=d.styles
    def ensure(name,base="Normal",kind=WD_STYLE_TYPE.PARAGRAPH):
        try:return st[name]
        except KeyError:
            s=st.add_style(name,kind)
            if base:s.base_style=st[base]
            return s
    normal=st["Normal"];set_font(normal,FONT,10.5,color=TEXT)
    normal.paragraph_format.space_after=Pt(6);normal.paragraph_format.line_spacing=1.12
    for lvl,size,color,before,after in ((1,20 if not modern else 22,TEXT if (minimal or modern) else ink,0,10),(2,13,TEXT,14,6),(3,12,TEXT,12,4),(4,11,TEXT,10,3)):
        h=st[f"Heading {lvl}"];set_font(h,HEAD,size,True,color,False)
        h.paragraph_format.space_before=Pt(before);h.paragraph_format.space_after=Pt(after);h.paragraph_format.keep_with_next=True
    st["Heading 1"].paragraph_format.page_break_before=True
    code=ensure("Code Block");set_font(code,MONO,8.5,color="1E293B")
    code.paragraph_format.space_after=Pt(8);code.paragraph_format.line_spacing=1.0;code.paragraph_format.left_indent=Mm(1.5)
    label=ensure("Finding Label");set_font(label,HEAD,8.5,True,TEXT if minimal else ink)
    label.paragraph_format.space_before=Pt(9);label.paragraph_format.space_after=Pt(3);label.paragraph_format.keep_with_next=True
    cap=st["Caption"];set_font(cap,FONT,8.5,False,"4B5563",True);cap.paragraph_format.space_after=Pt(8)
    cell_st=ensure("Table Text");set_font(cell_st,FONT,9);cell_st.paragraph_format.space_after=Pt(0);cell_st.paragraph_format.line_spacing=1.0
    toc1=ensure("toc 1");set_font(toc1,FONT,10.5,True);toc1.paragraph_format.space_after=Pt(4)
    toc2=ensure("toc 2");set_font(toc2,FONT,9.5,False);toc2.paragraph_format.space_after=Pt(1);toc2.paragraph_format.left_indent=Mm(6)
    toc3=ensure("toc 3");set_font(toc3,FONT,9,False);toc3.paragraph_format.space_after=Pt(0);toc3.paragraph_format.left_indent=Mm(12)
    for s in (toc1,toc2,toc3):
        s.paragraph_format.tab_stops.add_tab_stop(CW,WD_TAB_ALIGNMENT.RIGHT,leader=1)
    toch=st["TOC Heading"];set_font(toch,HEAD,20,True,TEXT if (minimal or modern) else ink)
    for name in ("List Bullet","List Bullet 2","List Bullet 3","List Number","List Number 2","List Number 3","Quote","Header","Footer"):
        try:set_font(st[name],FONT)
        except KeyError:pass
    try:
        q=st["Quote"];q.font.italic=False;q.font.color.rgb=rgb("374151");q.paragraph_format.left_indent=Mm(5)
    except KeyError:pass
    # ---- low-level helpers ----
    def shade(el_pr,fill):
        shd=OxmlElement("w:shd");shd.set(qn("w:val"),"clear");shd.set(qn("w:color"),"auto");shd.set(qn("w:fill"),fill)
        _put(el_pr,shd)
    def p_border(p,side,color,size=6,space=4):
        ppr=p._p.get_or_add_pPr();bdr=ppr.find(qn("w:pBdr"))
        if bdr is None:bdr=_put(ppr,OxmlElement("w:pBdr"))
        e=OxmlElement("w:"+side);e.set(qn("w:val"),"single");e.set(qn("w:sz"),str(size));e.set(qn("w:space"),str(space));e.set(qn("w:color"),color)
        bdr.append(e)
    def p_shade(p,fill):shade(p._p.get_or_add_pPr(),fill)
    def field(p,instr,placeholder=""):
        """Complex field in one paragraph; returns the 'end' run so callers can extend the cached result first."""
        r=p.add_run();fc=OxmlElement("w:fldChar");fc.set(qn("w:fldCharType"),"begin");fc.set(qn("w:dirty"),"true");r._r.append(fc)
        r=p.add_run();it=OxmlElement("w:instrText");it.set(qn("xml:space"),"preserve");it.text=instr;r._r.append(it)
        r=p.add_run();fc=OxmlElement("w:fldChar");fc.set(qn("w:fldCharType"),"separate");r._r.append(fc)
        if placeholder:p.add_run(placeholder)
        r=p.add_run();fc=OxmlElement("w:fldChar");fc.set(qn("w:fldCharType"),"end");r._r.append(fc)
        return r
    bm={"n":0}
    def bookmark(p,name):
        bm["n"]+=1
        s=OxmlElement("w:bookmarkStart");s.set(qn("w:id"),str(bm["n"]));s.set(qn("w:name"),name)
        e=OxmlElement("w:bookmarkEnd");e.set(qn("w:id"),str(bm["n"]))
        p._p.insert(0 if p._p.pPr is None else 1,s);p._p.append(e)
    def bm_name(anchor):return "loya_"+re.sub(r"[^A-Za-z0-9_]","_",anchor)[:32]
    def hyperlink(p,text,url=None,anchor=None,bold=False,size=None,color=None):
        h=OxmlElement("w:hyperlink")
        if anchor:h.set(qn("w:anchor"),bm_name(anchor))
        else:h.set(qn("r:id"),p.part.relate_to(url,RT.HYPERLINK,is_external=True))
        h.set(qn("w:history"),"1")
        r=OxmlElement("w:r");rpr=OxmlElement("w:rPr")
        if bold:rpr.append(OxmlElement("w:b"))
        c=OxmlElement("w:color");c.set(qn("w:val"),color or ink);rpr.append(c)
        if size:
            sz=OxmlElement("w:sz");sz.set(qn("w:val"),str(int(size*2)));rpr.append(sz)
        if not anchor:
            u=OxmlElement("w:u");u.set(qn("w:val"),"single");rpr.append(u)
        r.append(rpr)
        t=OxmlElement("w:t");t.set(qn("xml:space"),"preserve");t.text=text;r.append(t)
        h.append(r);p._p.append(h)
    def add_runs(p,runs,base_bold=None,size=None,color=None):
        for r in runs or []:
            if r.get("redact"):
                run=p.add_run("REDACTED");run.font.color.rgb=RGBColor(0,0,0)
                shade(run._r.get_or_add_rPr(),"000000")
                continue
            text=r.get("text","")
            href=rx._safe_href(r.get("href"))
            if href and "\n" not in text:
                try:
                    hyperlink(p,text,url=href,bold=bool(r.get("b")),size=size);continue
                except Exception:pass
            run=p.add_run(text)
            if r.get("b") or base_bold:run.bold=True
            if r.get("i"):run.italic=True
            if r.get("u"):run.underline=True
            if r.get("s"):run.font.strike=True
            if size:run.font.size=Pt(size)
            if color:run.font.color.rgb=rgb(color)
            if r.get("code"):
                run.font.name=MONO;run.font.size=Pt((size or 10.5)-1.5)
                rf=run._r.get_or_add_rPr().find(qn("w:rFonts"))
                if rf is not None:
                    for a in ("w:cs","w:eastAsia"):rf.set(qn(a),MONO)
                shade(run._r.get_or_add_rPr(),"F1F3F6")
    def tc_pr(cell):return cell._tc.get_or_add_tcPr()
    def cell_margins(table,top=45,left=90,bottom=45,right=90):
        pr=table._tbl.tblPr;m=OxmlElement("w:tblCellMar")
        for side,v in (("top",top),("left",left),("bottom",bottom),("right",right)):
            e=OxmlElement("w:"+side);e.set(qn("w:w"),str(v));e.set(qn("w:type"),"dxa");m.append(e)
        _put(pr,m)
    def table_borders(table,color="D5DAE1",inside=True,outer=True):
        pr=table._tbl.tblPr;b=OxmlElement("w:tblBorders")
        for side in ("top","left","bottom","right","insideH","insideV"):
            e=OxmlElement("w:"+side);on=(inside if side.startswith("inside") else outer)
            e.set(qn("w:val"),"single" if on else "nil");e.set(qn("w:sz"),"4");e.set(qn("w:space"),"0");e.set(qn("w:color"),color)
            b.append(e)
        _put(pr,b)
    def fixed_layout(table):
        lay=OxmlElement("w:tblLayout");lay.set(qn("w:type"),"fixed");_put(table._tbl.tblPr,lay)
    def new_table(container,nrows,ncols,width):
        t=container.add_table(rows=nrows,cols=ncols) if container is d else container.add_table(nrows,ncols)
        t.alignment=WD_TABLE_ALIGNMENT.LEFT;t.autofit=False
        return t
    numbering={"n":None}
    def restart_number(style_name):
        """Each ordered list restarts at 1 (python-docx otherwise continues the previous list's numbering)."""
        try:
            num_root=d.part.numbering_part.element
            ppr=st[style_name].element.pPr
            base=ppr.numPr.numId.val
            abstract=None
            for n in num_root.findall(qn("w:num")):
                if n.get(qn("w:numId"))==str(base):abstract=n.find(qn("w:abstractNumId")).get(qn("w:val"))
            if abstract is None:return None
            new_id=max(int(n.get(qn("w:numId"))) for n in num_root.findall(qn("w:num")))+1
            num=OxmlElement("w:num");num.set(qn("w:numId"),str(new_id))
            a=OxmlElement("w:abstractNumId");a.set(qn("w:val"),abstract);num.append(a)
            ov=OxmlElement("w:lvlOverride");ov.set(qn("w:ilvl"),"0")
            so=OxmlElement("w:startOverride");so.set(qn("w:val"),"1");ov.append(so);num.append(ov)
            num_root.append(num)
            return new_id
        except Exception:return None
    def set_num(p,num_id):
        if not num_id:return
        ppr=p._p.get_or_add_pPr();npr=OxmlElement("w:numPr")
        il=OxmlElement("w:ilvl");il.set(qn("w:val"),"0");npr.append(il)
        ni=OxmlElement("w:numId");ni.set(qn("w:val"),str(num_id));npr.append(ni)
        _put(ppr,npr)
    # ---- blocks ----
    _sid={}
    def sid(name):
        # python-docx resolves a style name by scanning styles.xml on every assignment; a 200-finding report does that ~10k times.
        if name not in _sid:_sid[name]=st[name].style_id
        return _sid[name]
    def para(container,style=None):
        p=container.add_paragraph()
        if style:p._p.style=sid(style)
        return p
    def image_block(container,b,width_limit):
        a=b.get("asset");capt=b.get("caption") or ""
        if not a:
            p=para(container);r=p.add_run(f"[Image not available{': '+(capt or b.get('alt')) if (capt or b.get('alt')) else ''}]");r.italic=True;r.font.color.rgb=rgb("6B7280");return
        data,_mime=rx.image_as(a,("image/png","image/jpeg","image/gif"))
        iw,ih=a.get("width") or 0,a.get("height") or 0
        if not data or not iw or not ih:
            p=para(container);r=p.add_run("[Image could not be embedded]");r.italic=True;return
        w=int(width_limit*b["width"]/100.0) if b.get("width") else min(int(width_limit),int(Emu(914400)*iw/110.0))
        maxh=int(sec.page_height*0.6)
        if w*ih/iw>maxh:w=int(maxh*iw/ih)
        p=para(container);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.keep_with_next=bool(capt);p.paragraph_format.space_after=Pt(3 if capt else 8)
        try:p.add_run().add_picture(io.BytesIO(data),width=w)
        except Exception:
            r=p.add_run("[Image could not be embedded]");r.italic=True;return
        if capt:
            c=para(container,"Caption");c.alignment=WD_ALIGN_PARAGRAPH.CENTER;c.add_run(capt)
    def pre_block(container,text,after=8):
        p=para(container,"Code Block");p_shade(p,"F6F8FA");p_border(p,"left",secondary,18,6)
        p.paragraph_format.space_after=Pt(after)
        p.add_run(text)
    def table_block(container,b,width):
        rows=b["rows"]
        if not rows:return
        ncols=max(len(r) for r in rows)
        widths=b.get("widths")
        if not widths or len(widths)!=ncols:widths=[1.0/ncols]*ncols
        tot=sum(widths);col_w=[int(width*w/tot) for w in widths]
        t=new_table(container,len(rows),ncols,width)
        table_borders(t,RULE,inside=True,outer=True);fixed_layout(t);cell_margins(t)
        if dz["theme"]!="corporate" or True:
            # Ruled, not boxed: horizontal hairlines only, as in the HTML design.
            pr_=t._tbl.tblPr;bd_=OxmlElement("w:tblBorders")
            for side in ("top","left","bottom","right","insideH","insideV"):
                e_=OxmlElement("w:"+side);e_.set(qn("w:val"),"single" if side in ("top","bottom","insideH") else "nil")
                e_.set(qn("w:sz"),"8" if side in ("top","bottom") else "4");e_.set(qn("w:space"),"0");e_.set(qn("w:color"),(TEXT if (minimal or modern) else accent) if side in ("top","bottom") else RULE);bd_.append(e_)
            _put(pr_,bd_)
        head=bool(b.get("header"));kv=bool(b.get("kv"))
        grid=[r.cells for r in t.rows]
        for ri,row in enumerate(rows):
            is_head=head and ri==0
            tr=t.rows[ri]._tr;trpr=tr.get_or_add_trPr()
            cs=OxmlElement("w:cantSplit");trpr.append(cs)
            if is_head:
                th=OxmlElement("w:tblHeader");trpr.append(th)
            zebra=(not kv and not b.get("nozebra") and not is_head and (ri-(1 if head else 0))%2==1)
            for ci in range(ncols):
                cell=grid[ri][ci];cell.width=col_w[ci]
                c=row[ci] if ci<len(row) else None
                if c is None:continue
                p=cell.paragraphs[0];p._p.style=sid("Table Text")
                fill=None;color=None;bold=bool(c.get("bold"))
                if is_head:fill=head_fill or None;color=head_on;bold=True
                elif c.get("fill"):fill=rx._hex(c["fill"],"#ffffff")[1:].upper()
                elif c.get("header"):fill=None if minimal else SOFT;bold=True;color=MUTED
                elif zebra and not minimal and not modern:fill=dz["zebra"][1:].upper()
                if minimal and c.get("sev"):fill=None;color=rx.SEV_INK[c["sev"]][1:].upper()
                if c.get("color") and not is_head:color=rx._hex(c["color"],"#000000")[1:].upper()
                if fill:shade(tc_pr(cell),fill)
                p.alignment={"C":WD_ALIGN_PARAGRAPH.CENTER,"R":WD_ALIGN_PARAGRAPH.RIGHT}.get(c.get("align"),WD_ALIGN_PARAGRAPH.LEFT)
                link=rx._s(c.get("link"))
                if c.get("runs") is not None and not is_head:
                    add_runs(p,c["runs"],base_bold=bold,size=9,color=color)
                elif link.startswith("#"):
                    hyperlink(p,c.get("text",""),anchor=link[1:],bold=True,size=9)
                else:
                    run=p.add_run(rx.runs_text(c["runs"]) if c.get("runs") is not None else c.get("text",""))
                    run.font.size=Pt(8.5 if c.get("mono") else 9)
                    if bold:run.bold=True
                    if color:run.font.color.rgb=rgb(color)
                    if c.get("mono"):run.font.name=MONO
        # Merges last: merging moves content, so every cell is filled before any span is applied.
        for ri,row in enumerate(rows):
            for ci,c in enumerate(row):
                if c is None:continue
                cs_,rs_=int(c.get("colspan",1)),int(c.get("rowspan",1))
                if cs_>1 or rs_>1:
                    try:
                        a=t.cell(ri,ci);z=t.cell(min(len(rows)-1,ri+rs_-1),min(ncols-1,ci+cs_-1))
                        if a._tc is not z._tc:a.merge(z)
                    except Exception:pass
        sp=para(container);sp.paragraph_format.space_after=Pt(4);sp.paragraph_format.line_spacing=0.6
    def list_block(container,b,width,level=1):
        style=("List Number" if b["ordered"] else "List Bullet")+("" if level==1 else f" {min(level,3)}")
        num_id=None;first=True
        for it in b["items"]:
            p=para(container,style);p.paragraph_format.space_after=Pt(2)
            if b["ordered"]:
                if first:num_id=restart_number(style)
                set_num(p,num_id)
            first=False
            add_runs(p,it["runs"])
            for sb in it["blocks"]:
                if sb["t"]=="list":list_block(container,sb,width,level+1)
                else:blocks(container,[sb],width)
    def figure_block(container,b,width):
        capt=b.get("caption") or ""
        if capt or b.get("info"):
            p=para(container);p.paragraph_format.keep_with_next=True;p.paragraph_format.space_after=Pt(2)
            r=p.add_run(capt);r.bold=True;r.font.size=Pt(8.5);r.font.color.rgb=rgb("374151")
            if b.get("info"):
                r=p.add_run(("  ·  " if capt else "")+b["info"]);r.font.size=Pt(8.5);r.font.color.rgb=rgb("6B7280")
        if b.get("pre"):pre_block(container,b["pre"],3 if (b.get("truncated") or b.get("image")) else 8)
        if b.get("image"):image_block(container,b["image"],width)
        if b.get("truncated"):
            p=para(container);r=p.add_run(f"Output truncated: {int(b['truncated'])} more line(s) not shown.");r.italic=True;r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
    def finding_head(b):
        col=rx.SEV_COLORS[b["severity"]][1:].upper();tint=rx.SEV_TINTS[b["severity"]][1:].upper()
        p=para(d,"Heading 2")
        p_shade(p,tint);p_border(p,"left",col,48,6)
        r=p.add_run(b["id"]+"  ");r.font.color.rgb=rgb(rx.SEV_INK[b["severity"]])
        p.add_run(b["title"])
        bookmark(p,bm_name(b["anchor"]))
    def blocks(container,bl,width):
        for b in bl:
            t=b["t"]
            if t=="p":add_runs(para(container),b["runs"])
            elif t=="h":
                if container is d:add_runs(para(d,f"Heading {3 if b['level']<=3 else 4}"),b["runs"])
                else:add_runs(para(container),b["runs"],base_bold=True)
            elif t=="label":para(container,"Finding Label").add_run(b["text"].upper())
            elif t=="pre":pre_block(container,b["text"])
            elif t=="quote":
                for sb in b["blocks"]:
                    if sb["t"]=="p":
                        p=para(container,"Quote");p_border(p,"left",secondary,18,8);add_runs(p,sb["runs"])
                    else:blocks(container,[sb],width)
            elif t=="list":list_block(container,b,width)
            elif t=="table":table_block(container,b,width)
            elif t=="hr":
                p=para(container);p_border(p,"bottom","D5DAE1",6,1);p.paragraph_format.space_after=Pt(8)
            elif t=="image":image_block(container,b,width)
            elif t=="figure":figure_block(container,b,width)
            elif t=="chart":
                fp=None
                try:
                    from Cores.Services import report_export_pdf as _pdf
                    fonts=_pdf.find_fonts();fp=fonts["sans"][""] if fonts else None
                except Exception:fp=None
                png=rx.chart_png(b["counts"],b["total"],fp)
                if png:
                    p=para(container);p.paragraph_format.space_after=Pt(8)
                    try:p.add_run().add_picture(io.BytesIO(png),width=int(width*0.82))
                    except Exception:pass
            elif t=="finding":finding_head(b)
    # ---- header / footer (the cover is the section's "different first page", so it carries neither) ----
    banner=doc["banner"] or (doc["classification"].upper() if doc["classification"] else "")
    sec.different_first_page_header_footer=bool(o["include_cover"])
    hdr=sec.header;hdr.is_linked_to_previous=False
    hp=hdr.paragraphs[0]
    if banner:
        hp.alignment=WD_ALIGN_PARAGRAPH.CENTER;p_shade(hp,accent)
        r=hp.add_run(banner.upper());r.bold=True;r.font.size=Pt(7.5);r.font.color.rgb=rgb(on_accent)
        hp.paragraph_format.space_after=Pt(4)
        hp=hdr.add_paragraph()
    hp.paragraph_format.tab_stops.add_tab_stop(CW,WD_TAB_ALIGNMENT.RIGHT)
    r=hp.add_run(doc["company"]);r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
    r=hp.add_run("\t"+doc["title"]);r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
    p_border(hp,"bottom","D5DAE1",4,3)
    ftr=sec.footer;ftr.is_linked_to_previous=False
    fp_=ftr.paragraphs[0];p_border(fp_,"top","D5DAE1",4,4)
    fp_.paragraph_format.tab_stops.add_tab_stop(int(CW/2),WD_TAB_ALIGNMENT.CENTER);fp_.paragraph_format.tab_stops.add_tab_stop(CW,WD_TAB_ALIGNMENT.RIGHT)
    r=fp_.add_run(doc["classification"]);r.bold=True;r.font.size=Pt(8);r.font.color.rgb=rgb(ink)
    r=fp_.add_run("\t"+doc["footer"]+"\t");r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
    r=fp_.add_run("Page ");r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
    field(fp_,"PAGE","1")
    r=fp_.add_run(" of ");r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
    field(fp_,"NUMPAGES","1")
    for run in fp_.runs:
        if run.font.size is None:run.font.size=Pt(8);run.font.color.rgb=rgb("6B7280")
    # ---- cover ----
    body_started=False
    if o["include_cover"]:
        t=d.add_table(rows=1,cols=1);t.alignment=WD_TABLE_ALIGNMENT.CENTER;table_borders(t,inside=False,outer=False);cell_margins(t,360,340,420,340)
        c=t.rows[0].cells[0]
        if dz["cover_style"]=="simple":
            # Plain cover: dark type on white with a rule under the title block.
            on_accent=TEXT;on_soft=MUTED
            bd_=OxmlElement("w:tcBorders");e_=OxmlElement("w:bottom");e_.set(qn("w:val"),"single");e_.set(qn("w:sz"),"12");e_.set(qn("w:space"),"0");e_.set(qn("w:color"),accent);bd_.append(e_);_put(tc_pr(c),bd_)
        else:shade(tc_pr(c),accent)
        p=c.paragraphs[0];p.paragraph_format.space_after=Pt(60)
        logo=cover.get("logo")
        r=p.add_run((cover["company"] or "").upper());r.bold=True;r.font.size=Pt(11);r.font.color.rgb=rgb(on_accent)
        if cover["subtitle"]:
            p=c.add_paragraph();p.paragraph_format.space_after=Pt(4)
            r=p.add_run(cover["subtitle"].upper());r.font.size=Pt(10.5);r.font.color.rgb=rgb(on_soft)
        p=c.add_paragraph();p.paragraph_format.space_after=Pt(8);p.paragraph_format.line_spacing=1.0
        r=p.add_run(cover["title"]);r.bold=True;r.font.size=Pt(30);r.font.color.rgb=rgb(on_accent);r.font.name=HEAD
        if dz["cover_style"]=="full":p.paragraph_format.space_before=Pt(90)
        if cover["client"]:
            p=c.add_paragraph();r=p.add_run("Prepared for "+cover["client"]);r.font.size=Pt(14);r.font.color.rgb=rgb(on_soft)
        sp=d.add_paragraph();sp.paragraph_format.space_after=Pt(18)
        if logo and logo.get("width") and logo.get("height"):
            data,_m=rx.image_as(logo,("image/png","image/jpeg","image/gif"))
            if data:
                try:
                    w=min(Mm(55),int(Mm(20)*logo["width"]/logo["height"]))
                    sp.add_run().add_picture(io.BytesIO(data),width=w)
                except Exception:pass
        if cover["facts"]:
            ft=d.add_table(rows=len(cover["facts"]),cols=2);ft.autofit=False;fixed_layout(ft);cell_margins(ft,90,60,90,60)
            pr=ft._tbl.tblPr;bd=OxmlElement("w:tblBorders")
            for side in ("top","left","bottom","right","insideH","insideV"):
                e=OxmlElement("w:"+side);e.set(qn("w:val"),"single" if side in ("bottom","insideH") else "nil");e.set(qn("w:sz"),"4");e.set(qn("w:space"),"0");e.set(qn("w:color"),"E5E7EB");bd.append(e)
            _put(pr,bd)
            for i,(k,v) in enumerate(cover["facts"]):
                cells=ft.rows[i].cells;cells[0].width=int(CW*0.32);cells[1].width=int(CW*0.68)
                p=cells[0].paragraphs[0];p._p.style=sid("Table Text");r=p.add_run(k.upper());r.font.size=Pt(8);r.font.color.rgb=rgb("6B7280")
                p=cells[1].paragraphs[0];p._p.style=sid("Table Text");r=p.add_run(v);r.font.size=Pt(11.5)
        if cover["classification"]:
            p=d.add_paragraph();p.paragraph_format.space_before=Pt(40)
            r=p.add_run(cover["classification"].upper());r.bold=True;r.font.size=Pt(10);r.font.color.rgb=rgb(ink)
        if doc["footer"]:
            p=d.add_paragraph();r=p.add_run(doc["footer"]);r.font.size=Pt(8.5);r.font.color.rgb=rgb("6B7280")
        body_started=True
    # ---- table of contents ----
    if o["include_toc"] and doc["toc"]:
        p=para(d,"TOC Heading");p.add_run("Table of Contents")
        if body_started:p.paragraph_format.page_break_before=True
        p_border(p,"bottom",accent,12,4);p.paragraph_format.space_after=Pt(10)
        # The cached result is a plain list of the headings so the page reads correctly before Word refreshes the field.
        first=para(d,"toc 1")
        r=first.add_run();fc=OxmlElement("w:fldChar");fc.set(qn("w:fldCharType"),"begin");fc.set(qn("w:dirty"),"true");r._r.append(fc)
        r=first.add_run();it=OxmlElement("w:instrText");it.set(qn("xml:space"),"preserve");it.text='TOC \\o "1-3" \\h \\z \\u';r._r.append(it)
        r=first.add_run();fc=OxmlElement("w:fldChar");fc.set(qn("w:fldCharType"),"separate");r._r.append(fc)
        cur=first
        for i,t in enumerate(doc["toc"]):
            if i:cur=para(d,"toc 1" if t["level"]==1 else "toc 2")
            hyperlink(cur,t["text"],anchor=t["anchor"],bold=t["level"]==1,color="1F2937")
        hint=d.add_paragraph();hr_=hint.add_run("Page numbers appear once the table is updated: right-click it in Word and choose Update Field.");hr_.italic=True;hr_.font.size=Pt(8);hr_.font.color.rgb=rgb("6B7280")
        r=hint.add_run();fc=OxmlElement("w:fldChar");fc.set(qn("w:fldCharType"),"end");r._r.append(fc)
        body_started=True
    # ---- sections ----
    for i,s in enumerate(doc["sections"]):
        p=para(d,"Heading 1");p.add_run(s["heading"])
        if not body_started and i==0:p.paragraph_format.page_break_before=False
        p_border(p,"bottom",accent,12,4)
        bookmark(p,bm_name(s["anchor"]))
        blocks(d,s["blocks"],CW)
    if not doc["sections"]:d.add_paragraph("This report has no visible sections.")
    # ---- document properties / settings ----
    cp=d.core_properties
    cp.title=doc["title"][:255];cp.author=(cover["authors"] or doc["company"] or "")[:255];cp.subject=" - ".join(x for x in (doc["meta"]["report_type"],doc["meta"]["client"]) if x)[:255]
    cp.keywords=", ".join(x for x in (doc["classification"],doc["meta"]["project_code"]) if x)[:255];cp.category=doc["classification"][:255];cp.comments="Generated by LOYA NG";cp.last_modified_by=cp.author
    if doc["meta"]["version"]:cp.version=doc["meta"]["version"][:255]
    try:
        import html as _html
        for part in d.part.package.iter_parts():
            if str(part.partname)=="/docProps/app.xml":
                xml=part.blob.decode("utf-8");comp=f"<Company>{_html.escape(doc['company'])}</Company>"
                xml=re.sub(r"<Company>.*?</Company>|<Company\s*/>",comp,xml,flags=re.S) if re.search(r"<Company[\s>/]",xml) else xml.replace("</Properties>",comp+"</Properties>")
                part._blob=xml.encode("utf-8")
    except Exception:pass
    try:
        settings=d.settings.element
        uf=OxmlElement("w:updateFields");uf.set(qn("w:val"),"true");settings.append(uf)
    except Exception:pass
    d.save(out_path)
