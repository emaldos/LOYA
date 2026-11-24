import os,re,html,base64,uuid,tempfile
from datetime import datetime,timezone
from Cores.Services import notes_service as _notes_svc
def save_temp_logo(data_b64):
    raw=data_b64.split(",",1)[-1] if "," in (data_b64 or "") else (data_b64 or "")
    if not raw:raise ValueError("No logo image data provided.")
    try:blob=base64.b64decode(raw)
    except Exception:raise ValueError("Invalid logo image data.")
    path=os.path.join(tempfile.gettempdir(),f"loya_report_logo_{uuid.uuid4().hex}.png")
    with open(path,"wb") as f:f.write(blob)
    return path
def _norm(s):return _notes_svc._norm(s)
_CMD_TOKEN_RX=re.compile(r'<a[^>]*href="cmd:[^"]*"[^>]*>\s*<img[^>]*src="cmdcard:([^"]+)"[^>]*/?>\s*</a>|<img[^>]*src="cmdcard:([^"]+)"[^>]*/?>',re.I)
_PLAIN_IMG_RX=re.compile(r'<img\b[^>]*>',re.I)
def _cmd_block(token):
    d=_notes_svc._decode_cmd_data(token)
    title=_norm(d.get("cmd_note_title",""))or"Command"
    meta=" / ".join([x for x in (_norm(d.get("category","")),_norm(d.get("sub_category",""))) if x])
    desc=_norm(d.get("description",""))
    cmd=(d.get("command","")or"").rstrip()
    tags=_notes_svc._split_tags(d.get("tags",""))
    command_type=_norm(d.get("command_type",""))or"other"
    return {"type":"command","title":title,"meta":meta,"desc":desc,"command":cmd,"tags":tags,"command_type":command_type}
def _text_segment_blocks(seg):
    if not seg or not seg.strip():return []
    seg=_notes_svc._NOTE_LINK_A_RX.sub(lambda m:m.group(2),seg)
    seg=_PLAIN_IMG_RX.sub("[Image attachment]",seg)
    text=_notes_svc._strip_html(seg)
    if not text.strip():return []
    paras=[p.strip() for p in re.split(r"\n\s*\n",text) if p.strip()]
    if not paras and text.strip():paras=[text.strip()]
    return [{"type":"paragraph","text":p} for p in paras]
def build_note_blocks(note):
    blocks=[]
    blocks.append({"type":"heading","text":note.get("note_name","")or"Untitled"})
    meta_parts=[]
    group=_norm(note.get("group_name",""))
    if group:meta_parts.append(f"Group: {group}")
    tags=_notes_svc._split_tags(note.get("tags",""))
    if tags:meta_parts.append("Tags: "+", ".join(tags))
    if meta_parts:blocks.append({"type":"meta","text":"  |  ".join(meta_parts)})
    content=note.get("content","")or""
    pos=0
    for m in _CMD_TOKEN_RX.finditer(content):
        blocks.extend(_text_segment_blocks(content[pos:m.start()]))
        token=m.group(1)or m.group(2)
        blocks.append(_cmd_block(token))
        pos=m.end()
    blocks.extend(_text_segment_blocks(content[pos:]))
    return blocks
def load_notes_for_report(note_ids):
    dbp=_notes_svc._db_path()
    notes=_notes_svc._load_notes(dbp)
    by_id={int(n["id"]):n for n in notes}
    out=[]
    for nid in note_ids or []:
        try:nid=int(nid)
        except Exception:continue
        n=by_id.get(nid)
        if n:out.append(n)
    return out
def render_markdown(notes,title=None):
    lines=[]
    if title:
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}_")
        lines.append("")
    for note in notes:
        for b in build_note_blocks(note):
            t=b["type"]
            if t=="heading":
                lines.append(f"## {b['text']}")
                lines.append("")
            elif t=="meta":
                lines.append(f"*{b['text']}*")
                lines.append("")
            elif t=="paragraph":
                lines.append(b["text"])
                lines.append("")
            elif t=="command":
                head=b["title"]
                if b["meta"]:head+=f" ({b['meta']})"
                lines.append(f"**{head}**")
                lines.append("")
                if b["desc"]:
                    lines.append(b["desc"])
                    lines.append("")
                lines.append("```")
                lines.append(b["command"])
                lines.append("```")
                if b["tags"]:
                    lines.append("")
                    lines.append("Tags: "+", ".join(b["tags"]))
                lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip()+"\n"
_HTML_STYLE="""
body{margin:0;padding:32px;background:#0d1117;color:#e8eef7;font-family:Segoe UI,Arial,sans-serif;line-height:1.6}
.report-title{font-size:26px;font-weight:700;color:#ffffff;margin:0 0 4px}
.report-meta{font-size:12px;color:#9fb3c8;margin:0 0 28px}
.note-section{background:#141b24;border:1px solid #263446;border-radius:10px;padding:20px 22px;margin-bottom:18px}
.note-section h2{margin:0 0 6px;font-size:18px;color:#ffffff}
.note-meta{font-size:12px;color:#9fb3c8;margin:0 0 12px}
.note-section p{font-size:13px;margin:0 0 12px;white-space:pre-wrap}
.cmd-block{background:#08111d;border:1px solid #304663;border-radius:8px;padding:12px 14px;margin:0 0 14px}
.cmd-block .cmd-title{font-weight:700;color:#ffffff;font-size:13px}
.cmd-block .cmd-meta{color:#9fb3c8;font-size:11px;margin-left:8px}
.cmd-block .cmd-desc{font-size:12px;color:#9fb3c8;margin:6px 0}
.cmd-block pre{background:#000000;border-radius:6px;padding:10px 12px;color:#8cecff;font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-word;margin:6px 0 0}
.cmd-block .cmd-tags{font-size:11px;color:#8ab5ff;margin-top:6px}
hr{border:none;border-top:1px solid #394b63;margin:24px 0}
"""
def render_html(notes,title=None):
    parts=['<!doctype html><html><head><meta charset="utf-8"><title>%s</title><style>%s</style></head><body>'%(html.escape(title or "LOYA NG Report"),_HTML_STYLE)]
    if title:
        parts.append(f'<div class="report-title">{html.escape(title)}</div>')
        parts.append(f'<div class="report-meta">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d")}</div>')
    for note in notes:
        parts.append('<div class="note-section">')
        for b in build_note_blocks(note):
            t=b["type"]
            if t=="heading":
                parts.append(f'<h2>{html.escape(b["text"])}</h2>')
            elif t=="meta":
                parts.append(f'<div class="note-meta">{html.escape(b["text"])}</div>')
            elif t=="paragraph":
                parts.append(f'<p>{html.escape(b["text"])}</p>')
            elif t=="command":
                head=html.escape(b["title"])
                meta=f'<span class="cmd-meta">{html.escape(b["meta"])}</span>' if b["meta"] else ""
                desc=f'<div class="cmd-desc">{html.escape(b["desc"])}</div>' if b["desc"] else ""
                tags=f'<div class="cmd-tags">Tags: {html.escape(", ".join(b["tags"]))}</div>' if b["tags"] else ""
                parts.append(f'<div class="cmd-block"><span class="cmd-title">{head}</span>{meta}{desc}<pre>{html.escape(b["command"])}</pre>{tags}</div>')
        parts.append('</div>')
    parts.append('</body></html>')
    return "".join(parts)
def render_pdf(out_path,notes,title=None):
    from fpdf import FPDF
    pdf=FPDF(format="A4")
    pdf.set_auto_page_break(True,margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica","B",20)
    if title:
        pdf.multi_cell(0,10,title,new_x="LMARGIN",new_y="NEXT")
        pdf.set_font("Helvetica","",9)
        pdf.set_text_color(120,120,120)
        pdf.cell(0,6,f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",new_x="LMARGIN",new_y="NEXT")
        pdf.set_text_color(0,0,0)
        pdf.ln(4)
    for note in notes:
        for b in build_note_blocks(note):
            t=b["type"]
            if t=="heading":
                pdf.set_font("Helvetica","B",15)
                pdf.multi_cell(0,9,b["text"],new_x="LMARGIN",new_y="NEXT")
                pdf.ln(1)
            elif t=="meta":
                pdf.set_font("Helvetica","I",9)
                pdf.set_text_color(110,110,110)
                pdf.multi_cell(0,6,b["text"],new_x="LMARGIN",new_y="NEXT")
                pdf.set_text_color(0,0,0)
                pdf.ln(2)
            elif t=="paragraph":
                pdf.set_font("Helvetica","",11)
                pdf.multi_cell(0,6,b["text"],new_x="LMARGIN",new_y="NEXT")
                pdf.ln(2)
            elif t=="command":
                pdf.set_font("Helvetica","B",11)
                head=b["title"]+(f" ({b['meta']})" if b["meta"] else "")
                pdf.multi_cell(0,6,head,new_x="LMARGIN",new_y="NEXT")
                if b["desc"]:
                    pdf.set_font("Helvetica","",10)
                    pdf.multi_cell(0,6,b["desc"],new_x="LMARGIN",new_y="NEXT")
                pdf.set_font("Courier","",9)
                pdf.set_fill_color(240,240,240)
                pdf.multi_cell(0,5,b["command"]or" ",fill=True,new_x="LMARGIN",new_y="NEXT")
                if b["tags"]:
                    pdf.set_font("Helvetica","I",8)
                    pdf.set_text_color(90,90,90)
                    pdf.multi_cell(0,5,"Tags: "+", ".join(b["tags"]),new_x="LMARGIN",new_y="NEXT")
                    pdf.set_text_color(0,0,0)
                pdf.ln(3)
        pdf.set_draw_color(200,200,200)
        pdf.ln(2)
        y=pdf.get_y()
        pdf.line(pdf.l_margin,y,pdf.w-pdf.r_margin,y)
        pdf.ln(4)
    pdf.output(out_path)
def render_docx(out_path,notes,title=None,client_name="",logo_path="",report_date=""):
    from docx import Document
    from docx.shared import Pt,Inches,RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    doc=Document()
    if logo_path and os.path.isfile(logo_path):
        try:
            doc.add_picture(logo_path,width=Inches(1.6))
            doc.paragraphs[-1].alignment=WD_ALIGN_PARAGRAPH.CENTER
        except Exception:pass
    p=doc.add_paragraph()
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    run=p.add_run(title or"LOYA NG Report")
    run.bold=True
    run.font.size=Pt(26)
    if client_name:
        p2=doc.add_paragraph()
        p2.alignment=WD_ALIGN_PARAGRAPH.CENTER
        r2=p2.add_run(f"Prepared for {client_name}")
        r2.font.size=Pt(13)
    p3=doc.add_paragraph()
    p3.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r3=p3.add_run(report_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    r3.font.size=Pt(10)
    r3.font.color.rgb=RGBColor(120,120,120)
    doc.add_page_break()
    for note in notes:
        for b in build_note_blocks(note):
            t=b["type"]
            if t=="heading":
                doc.add_heading(b["text"],level=1)
            elif t=="meta":
                mp=doc.add_paragraph()
                mr=mp.add_run(b["text"])
                mr.italic=True
                mr.font.size=Pt(9)
                mr.font.color.rgb=RGBColor(110,110,110)
            elif t=="paragraph":
                doc.add_paragraph(b["text"])
            elif t=="command":
                hp=doc.add_paragraph()
                head=b["title"]+(f" ({b['meta']})" if b["meta"] else "")
                hr=hp.add_run(head)
                hr.bold=True
                if b["desc"]:
                    doc.add_paragraph(b["desc"])
                cp=doc.add_paragraph()
                cr=cp.add_run(b["command"]or" ")
                cr.font.name="Consolas"
                cr.font.size=Pt(9.5)
                if b["tags"]:
                    tp=doc.add_paragraph()
                    tr=tp.add_run("Tags: "+", ".join(b["tags"]))
                    tr.italic=True
                    tr.font.size=Pt(8.5)
                    tr.font.color.rgb=RGBColor(90,90,90)
        doc.add_paragraph("_"*40)
    doc.save(out_path)
