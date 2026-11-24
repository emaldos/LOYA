"""Minimal XLSX writer (stdlib only: zipfile + XML). Enough for a styled findings workbook: bold filled header row,
column widths, wrapped cells, severity fill colours, frozen header and an auto-filter. No formulas are ever written,
and every value is an inline string or a number, so spreadsheet formula injection is not possible through this file."""
import re,zipfile
from xml.sax.saxutils import escape
from Cores.Services import report_export as rx
_BAD_XML=re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
MAX_CELL=32000
def col_name(i):
    s=""
    i+=1
    while i:
        i,r=divmod(i-1,26);s=chr(65+r)+s
    return s
def _text(v):
    v=_BAD_XML.sub("","" if v is None else str(v)).replace("\r\n","\n").replace("\r","\n")
    return v[:MAX_CELL]
def _cell(ref,value,style):
    if isinstance(value,bool):value=str(value)
    if isinstance(value,(int,float)):return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    t=_text(value)
    if t=="":return f'<c r="{ref}" s="{style}"/>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(t)}</t></is></c>'
def _argb(h):return "FF"+rx._hex(h,"#000000")[1:].upper()
class Workbook:
    """Styles are registered on demand: style(bold=..,fill=..,color=..,wrap=..,align=..) -> index usable in rows."""
    def __init__(self):
        self.sheets=[];self._fonts=[(False,None,False)];self._fills=[None,"gray125"];self._xfs=[(0,0,False,"",False)];self._style_cache={}
    def style(self,bold=False,fill=None,color=None,wrap=True,align="",italic=False,border=True):
        key=(bold,fill,color,wrap,align,italic,border)
        if key in self._style_cache:return self._style_cache[key]
        font=(bool(bold),_argb(color) if color else None,bool(italic))
        if font not in self._fonts:self._fonts.append(font)
        f=_argb(fill) if fill else None
        if f and f not in self._fills:self._fills.append(f)
        xf=(self._fonts.index(font),self._fills.index(f) if f else 0,bool(wrap),align,bool(border))
        if xf not in self._xfs:self._xfs.append(xf)
        self._style_cache[key]=self._xfs.index(xf)
        return self._style_cache[key]
    def add_sheet(self,name,rows,widths=None,freeze=True,autofilter=True):
        """rows: list of rows; a cell is a value or (value, style_index). The first row is the header when freeze is on."""
        name=re.sub(r"[\[\]:*?/\\]"," ",_text(name)).strip()[:31] or f"Sheet{len(self.sheets)+1}"
        self.sheets.append({"name":name,"rows":rows,"widths":widths or [],"freeze":freeze,"autofilter":autofilter})
    def _styles_xml(self):
        fonts="".join('<font>'+("<b/>" if b else "")+("<i/>" if i else "")+'<sz val="10"/>'+(f'<color rgb="{c}"/>' if c else "")+'<name val="Calibri"/><family val="2"/></font>' for b,c,i in self._fonts)
        fills="".join('<fill><patternFill patternType="none"/></fill>' if f is None else ('<fill><patternFill patternType="gray125"/></fill>' if f=="gray125" else f'<fill><patternFill patternType="solid"><fgColor rgb="{f}"/><bgColor indexed="64"/></patternFill></fill>') for f in self._fills)
        side='<{0} style="thin"><color rgb="FFD5DAE1"/></{0}>'
        borders='<border><left/><right/><top/><bottom/><diagonal/></border><border>'+"".join(side.format(s) for s in ("left","right","top","bottom"))+"<diagonal/></border>"
        xfs=""
        for font,fill,wrap,align,border in self._xfs:
            al='<alignment vertical="top"'+(' wrapText="1"' if wrap else "")+(f' horizontal="{align}"' if align else "")+"/>"
            xfs+=f'<xf numFmtId="0" fontId="{font}" fillId="{fill}" borderId="{1 if border else 0}" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">{al}</xf>'
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<fonts count="{len(self._fonts)}">{fonts}</fonts><fills count="{len(self._fills)}">{fills}</fills><borders count="2">{borders}</borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(self._xfs)}">{xfs}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    def _sheet_xml(self,sh):
        rows=sh["rows"];ncols=max([len(r) for r in rows]+[1])
        out=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        out.append(f'<dimension ref="A1:{col_name(ncols-1)}{max(1,len(rows))}"/>')
        if sh["freeze"] and len(rows)>1:out.append('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
        else:out.append('<sheetViews><sheetView workbookViewId="0"/></sheetViews>')
        out.append('<sheetFormatPr defaultRowHeight="15"/>')
        if sh["widths"]:out.append("<cols>"+"".join(f'<col min="{i+1}" max="{i+1}" width="{float(w):.2f}" customWidth="1"/>' for i,w in enumerate(sh["widths"]))+"</cols>")
        out.append("<sheetData>")
        for ri,row in enumerate(rows):
            cells=[]
            for ci,c in enumerate(row):
                value,style=(c if isinstance(c,tuple) else (c,0))
                cells.append(_cell(f"{col_name(ci)}{ri+1}",value,style))
            out.append(f'<row r="{ri+1}">'+"".join(cells)+"</row>")
        out.append("</sheetData>")
        if sh["autofilter"] and len(rows)>1:out.append(f'<autoFilter ref="A1:{col_name(ncols-1)}{len(rows)}"/>')
        out.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/><pageSetup orientation="landscape"/></worksheet>')
        return "".join(out)
    def save(self,path,title="",author=""):
        if not self.sheets:self.add_sheet("Sheet1",[[""]])
        n=len(self.sheets)
        ct=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            +"".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n))+"</Types>")
        rels=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
        wb=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<bookViews><workbookView/></bookViews><sheets>'+"".join(f'<sheet name="{escape(s["name"],{chr(34):"&quot;"})}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i,s in enumerate(self.sheets))+"</sheets></workbook>")
        wrels=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            +"".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(n))
            +f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        core=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(_text(title))}</dc:title><dc:creator>{escape(_text(author))}</dc:creator></cp:coreProperties>')
        with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",ct);z.writestr("_rels/.rels",rels);z.writestr("docProps/core.xml",core)
            z.writestr("xl/workbook.xml",wb);z.writestr("xl/_rels/workbook.xml.rels",wrels);z.writestr("xl/styles.xml",self._styles_xml())
            for i,sh in enumerate(self.sheets):z.writestr(f"xl/worksheets/sheet{i+1}.xml",self._sheet_xml(sh))
_WIDTHS=(9,42,14,11,44,14,12,24,34,12,60,50,50,60,44,22,24)
def write_findings(doc,out_path):
    wb=Workbook()
    head=wb.style(bold=True,fill=doc["accent"],color=doc.get("on_accent") or "#ffffff",wrap=True)
    body=wb.style();bold=wb.style(bold=True);center=wb.style(align="center")
    sev_style={rx.SEV_LABELS[s]:wb.style(bold=True,fill=rx.SEV_COLORS[s],color=rx.SEV_ON[s],align="center") for s in rx.SEVERITIES}
    rows=[[(c,head) for c in rx.FINDING_COLUMNS]]
    for r in rx.finding_rows(doc):
        row=[]
        for i,v in enumerate(r):
            if i==0:row.append((v,bold))
            elif i==2:row.append((v,sev_style.get(v,body)))
            elif i==3:
                try:row.append((float(v),center))
                except (TypeError,ValueError):row.append(("",center))
            else:row.append((v,body))
        rows.append(row)
    wb.add_sheet("Findings",rows,_WIDTHS)
    m=doc["meta"];label=wb.style(bold=True,fill="#eef1f5");plain=wb.style();title=wb.style(bold=True,fill=doc["accent"],color=doc.get("on_accent") or "#ffffff")
    srows=[[("Report",title),(doc["title"],title)]]
    for k,v in (("Client",m["client"]),("Engagement",m["engagement"]),("Project code",m["project_code"]),("Report date",m["report_date"]),("Version",m["version"]),("Classification",m["classification"]),("Prepared by",doc["company"]),("Testing period"," - ".join(x for x in (m["start_date"],m["end_date"]) if x))):
        if v:srows.append([(k,label),(v,plain)])
    srows.append([("",0),("",0)])
    srows.append([("Severity",title),("Findings",title)])
    for s in rx.SEVERITIES:srows.append([(rx.SEV_LABELS[s],sev_style[rx.SEV_LABELS[s]]),(doc["counts"][s],center)])
    srows.append([("Total",label),(doc["total"],wb.style(bold=True,align="center"))])
    wb.add_sheet("Summary",srows,(22,60),freeze=False,autofilter=False)
    wb.save(out_path,doc["title"],doc["cover"]["authors"] or doc["company"])
