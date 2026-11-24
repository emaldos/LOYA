"""The report design as HTML + CSS. One document serves the in-app preview, the HTML export and - through the print engine of the
app's own web view - the PDF. It never contains a script; images and fonts are data: URIs so the file is self-contained."""
import math
from Cores.Services import report_export as rx
from Cores.Services import report_design as design
from Cores.Services.report_design import SEVERITIES,SEV_LABELS,SEV_SHORT,SEV_COLORS,SEV_TINTS,SEV_ON,SEV_INK,STATUS_COLORS
_e=rx._e
# WebKit lays a printed page out 1.0667x larger than its physical size (1.25 CSS px per point); this zoom restores true mm/pt.
WEBKIT_PRINT_ZOOM=0.9375
_BASE_CSS="""
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#e6e9ee;color:var(--text);font-family:var(--fb);font-size:10pt;line-height:1.5;-webkit-print-color-adjust:exact;print-color-adjust:exact;text-rendering:geometricPrecision;font-kerning:normal}
.doc{width:var(--pw);max-width:100%;margin:22px auto;background:#fff;box-shadow:0 2px 20px rgba(15,23,42,.16);overflow:hidden}
.classbar{background:var(--accent);color:var(--on-accent);text-align:center;font-size:7.5pt;letter-spacing:.16em;text-transform:uppercase;padding:4px 12px;font-weight:700}
.body{padding:var(--mt) var(--mr) var(--mb) var(--ml)}
.mk{display:inline-block;width:2px;height:2px;vertical-align:baseline;margin-right:-2px}
h1,h2,h3,h4{font-family:var(--fh);margin:0;font-weight:700}
p{margin:0 0 7pt;overflow-wrap:anywhere;orphans:3;widows:3}
a{color:var(--ink);text-decoration:none}
p a,li a,td a.x{text-decoration:underline;text-decoration-color:var(--rule);text-underline-offset:2px}
ul,ol{margin:0 0 7pt;padding-left:16pt}
li{margin:1.5pt 0;overflow-wrap:anywhere}
li>ul,li>ol{margin-bottom:1pt}
h3{font-size:12pt;color:var(--text);margin:13pt 0 5pt;break-after:avoid;page-break-after:avoid}
h4{font-size:10.5pt;color:var(--text);margin:10pt 0 4pt;break-after:avoid;page-break-after:avoid}
hr{border:none;border-top:1px solid var(--rule);margin:11pt 0}
.ac{text-align:center}.ar{text-align:right}.aj{text-align:justify}
.muted{color:var(--muted)}
.keep{break-inside:avoid;page-break-inside:avoid}
blockquote{margin:0 0 8pt;padding:5pt 11pt;border-left:2.5pt solid var(--secondary);background:var(--soft);color:var(--text)}
blockquote>:last-child{margin-bottom:0}
code{font-family:var(--fm);font-size:.86em;background:var(--soft);border:1px solid var(--rule);border-radius:2.5px;padding:0 3px;overflow-wrap:anywhere}
pre{font-family:var(--fm);font-size:7.8pt;line-height:1.42;background:var(--soft);border:1px solid var(--rule);border-radius:3px;padding:7pt 9pt;margin:0 0 9pt;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;color:#1b2330;orphans:3;widows:3;tab-size:4}
.code{position:relative;margin:0 0 9pt}
.code pre{margin:0;padding-top:13pt}
.code .lang{position:absolute;top:0;left:0;font-family:var(--fm);font-size:6.3pt;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);background:#fff;border:1px solid var(--rule);border-radius:3px 0 3px 0;padding:1px 6px;-webkit-user-select:none;user-select:none}
.redact{background:#111;color:#111;border-radius:1.5px;padding:0 5px;font-size:.78em;letter-spacing:.05em;-webkit-user-select:none;user-select:none;white-space:nowrap}
.missing{border:1px dashed var(--rule);color:var(--muted);font-size:8.5pt;padding:6pt 8pt;margin:0 0 8pt;font-style:italic}
/* cover */
.cover{position:relative;height:var(--ph);display:flex;flex-direction:column;overflow:hidden;background:#fff;color:var(--text)}
.cv-top{display:flex;align-items:center;justify-content:space-between;gap:10mm;min-height:20mm}
.cv-logo{max-height:20mm;max-width:62mm;display:block}
.cv-logo.chip{background:#fff;padding:2.5mm 4mm;border-radius:2px}
.cv-company{font-family:var(--fh);font-size:10.5pt;letter-spacing:.18em;text-transform:uppercase;font-weight:700}
.cv-kicker{font-size:9.5pt;letter-spacing:.2em;text-transform:uppercase;font-weight:700;margin:0 0 5mm}
.cv-title{font-family:var(--fh);font-size:31pt;line-height:1.12;font-weight:700;margin:0;overflow-wrap:anywhere;letter-spacing:-.005em}
.cv-for{font-size:13pt;margin-top:6mm;overflow-wrap:anywhere}
.cv-for b{font-weight:700}
.cv-facts{display:table;width:100%;table-layout:fixed;border-collapse:collapse}
.cv-fr{display:table-row}
.cv-f{display:table-cell;padding:3.2mm 6mm 3.2mm 0;vertical-align:top;border-top:1px solid var(--rule);overflow-wrap:anywhere}
.cv-f .k{display:block;font-size:6.8pt;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:1mm}
.cv-f .v{display:block;font-size:10.5pt;line-height:1.35}
.cv-class{display:inline-block;border:1.2pt solid currentColor;font-weight:700;font-size:8.5pt;letter-spacing:.18em;text-transform:uppercase;padding:2mm 4.5mm;border-radius:2px}
.cv-foot{display:flex;align-items:flex-end;justify-content:space-between;gap:10mm;margin-top:auto}
.cv-note{font-size:7.8pt;color:var(--muted);max-width:105mm;text-align:right;line-height:1.45;overflow-wrap:anywhere}
.cs-band .cv-band{background:var(--accent);color:var(--on-accent);padding:20mm 20mm 17mm;min-height:49%;display:flex;flex-direction:column;position:relative}
.cs-band .cv-band:after{content:"";position:absolute;left:0;right:0;bottom:-2.2mm;height:2.2mm;background:var(--secondary)}
.cs-band .cv-head{margin-top:auto;padding-top:14mm}
.cs-band .cv-kicker{color:var(--on-soft)}
.cs-band .cv-for{color:var(--on-soft)}
.cs-band .cv-rest{padding:15mm 20mm 14mm;flex:1;display:flex;flex-direction:column}
.cs-band .cv-class{color:var(--ink)}
.cs-full .cover{background:var(--accent);color:var(--on-accent);padding:20mm}
.cs-full .cv-head{margin-top:52mm}
.cs-full .cv-kicker,.cs-full .cv-for{color:var(--on-soft)}
.cs-full .cv-title{font-size:35pt}
.cs-full .cv-rule{width:24mm;height:1.6mm;background:var(--on-accent);opacity:.9;margin:0 0 9mm}
.cs-full .cv-rest{margin-top:auto;display:flex;flex-direction:column}
.cs-full .cv-f{border-top-color:var(--on-line)}
.cs-full .cv-f .k,.cs-full .cv-note{color:var(--on-soft)}
.cs-full .cv-foot{margin-top:10mm}
.cs-simple .cover{padding:22mm 22mm 18mm}
.cs-simple .cv-head{margin-top:44mm;padding-bottom:9mm;border-bottom:1.5pt solid var(--accent)}
.cs-simple .cv-kicker{color:var(--ink)}
.cs-simple .cv-title{color:var(--text)}
.cs-simple .cv-for{color:var(--muted)}
.cs-simple .cv-rest{margin-top:11mm;flex:1;display:flex;flex-direction:column}
.cs-simple .cv-f:first-child,.cs-simple .cv-fr:first-child .cv-f{border-top:none}
.cs-simple .cv-class{color:var(--text)}
/* contents */
.toc{break-after:page;page-break-after:always}
.toc-h,.sh h1{font-size:20pt;line-height:1.2;color:var(--ink);overflow-wrap:anywhere}
.toc-h{margin:0 0 9mm;padding-bottom:3mm;border-bottom:1.5pt solid var(--accent)}
.toc-r{display:flex;align-items:baseline;color:var(--text);padding:2.3mm 0 0;break-inside:avoid;page-break-inside:avoid}
.toc-r .n{flex:none;width:9mm;font-weight:700;color:var(--ink);font-family:var(--fh)}
.toc-r .tt{flex:0 1 auto;font-weight:700;overflow-wrap:anywhere}
.toc-r .ld{flex:1 1 6mm;min-width:6mm;border-bottom:1px dotted var(--muted);margin:0 2mm;opacity:.55;position:relative;top:-2.5pt}
.toc-r .pg{flex:none;width:9mm;text-align:right}
html:not(.pm) .toc-r .ld,html:not(.pm) .toc-r .pg{display:none}
.toc-r.l2{padding-top:1.1mm;font-size:9pt}
.toc-r.l2 .n{width:9mm;visibility:hidden}
.toc-r.l2 .tt{font-weight:400}
.toc-r.l2 .fid{font-family:var(--fm);font-size:8pt;color:var(--muted);margin-right:2.2mm;white-space:nowrap}
.dot{display:inline-block;width:6.5pt;height:6.5pt;border-radius:50%;margin-right:2mm;flex:none;position:relative;top:.4pt}
.toc-app{margin-top:5mm;font-size:6.8pt;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:700}
/* sections */
.sec{break-before:page;page-break-before:always}
.sec.first{break-before:auto;page-break-before:auto}
.sh{margin:0 0 7mm;break-after:avoid;page-break-after:avoid;break-inside:avoid;page-break-inside:avoid}
.sh .sn{display:block;font-family:var(--fh);font-weight:700;color:var(--secondary-ink);font-size:9pt;letter-spacing:.18em;text-transform:uppercase;margin-bottom:1.5mm}
.sh h1{padding-bottom:3mm;border-bottom:1.5pt solid var(--accent)}
.label{font-family:var(--fh);font-size:8pt;font-weight:700;color:var(--ink);text-transform:uppercase;letter-spacing:.11em;margin:11pt 0 4pt;break-after:avoid;page-break-after:avoid}
/* tables */
table.t{width:100%;border-collapse:collapse;margin:0 0 10pt;font-size:8.8pt;line-height:1.4;table-layout:fixed}
table.t th,table.t td{padding:4pt 6pt;text-align:left;vertical-align:top;overflow-wrap:anywhere;word-break:break-word;border-bottom:1px solid var(--rule)}
table.t thead{display:table-header-group}
table.t thead th{background:var(--hf);color:var(--ho);font-weight:700;font-size:8pt;letter-spacing:.03em;border-bottom:none;vertical-align:bottom}
table.t tr{break-inside:avoid;page-break-inside:avoid}
.tw{margin:0 0 10pt}
.tw table.t{margin:0;break-inside:avoid;page-break-inside:avoid}
.tw table.t.mid tbody tr:last-child>*{border-bottom:1px solid var(--rule)}
.tw table.t.ev tbody tr>td{background:var(--zebra)}
.tw table.t.kv.nf{border-top:none}
table.t tbody tr:last-child>*{border-bottom:1.2pt solid var(--accent)}
table.t.zebra tbody tr:nth-child(even)>td{background:var(--zebra)}
table.t tbody th{background:var(--soft);color:var(--text);font-weight:700}
table.t.kv{border-top:1.2pt solid var(--accent)}
table.t.kv tbody th{width:26%;color:var(--muted);font-size:8pt;letter-spacing:.03em}
table.t td.mono{font-family:var(--fm);font-size:7.8pt}
table.t td.num{font-weight:700;white-space:nowrap}
table.t td.b>a{white-space:nowrap}
table.t td.tot,table.t th.tot{background:var(--soft);font-weight:700}
.c{text-align:center!important}.r{text-align:right!important}.b{font-weight:700}
.sv{display:inline-block;font-size:7.3pt;font-weight:700;letter-spacing:.07em;text-transform:uppercase;padding:1.6pt 6pt;border-radius:2.5px;white-space:nowrap;line-height:1.35}
.st{white-space:normal}
.st i{display:inline-block;width:5.5pt;height:5.5pt;border-radius:50%;margin-right:3.5pt;position:relative;top:-.5pt}
.pr{display:inline-block;min-width:17pt;font-weight:700;font-size:8pt;border:1px solid var(--rule);border-radius:2.5px;padding:.5pt 4pt;text-align:center}
/* dashboard */
.dash{display:table;width:100%;table-layout:fixed;border-collapse:separate;border-spacing:0;margin:0 0 11pt;break-inside:avoid;page-break-inside:avoid}
.dash>div{display:table-cell;vertical-align:top}
.dash-o{width:31%;padding:9pt 11pt;color:#fff}
.dash-o .k{font-size:6.8pt;letter-spacing:.15em;text-transform:uppercase;font-weight:700;opacity:.92}
.dash-o .v{font-family:var(--fh);font-size:21pt;font-weight:700;line-height:1.15;margin:2pt 0 3pt}
.dash-o .s{font-size:7.8pt;line-height:1.4;opacity:.95}
.tile{padding:9pt 4pt 7pt 10pt;border-top:2.5pt solid var(--rule);background:var(--soft);border-left:2.5pt solid #fff}
.tile .n{font-family:var(--fh);font-size:21pt;font-weight:700;line-height:1.15;color:var(--text)}
.tile .l{font-size:6.8pt;letter-spacing:.11em;text-transform:uppercase;font-weight:700;color:var(--muted);margin-top:3pt}
.tile.zero .n{color:#a3acb9}
.chart{margin:2pt 0 11pt;break-inside:avoid;page-break-inside:avoid}
.chart svg{max-width:100%;height:auto;display:block}
svg text{font-family:var(--fb)}
svg .hd{font-family:var(--fh)}
.mx-note{font-size:7.8pt;color:var(--muted);margin:-5pt 0 10pt}
/* timeline */
.tl{display:table;width:100%;table-layout:fixed;border-collapse:collapse;margin:4pt 0 12pt;break-inside:avoid;page-break-inside:avoid}
.tl>div{display:table-cell;vertical-align:top;text-align:center;padding:0 2pt;position:relative}
.tl .ln{position:absolute;left:0;right:0;top:4.2pt;height:1.2pt;background:var(--rule)}
.tl>div:first-child .ln{left:50%}.tl>div:last-child .ln{right:50%}
.tl .nd{position:relative;display:inline-block;width:9.6pt;height:9.6pt;border-radius:50%;border:1.6pt solid var(--accent);background:#fff}
.tl .on .nd{background:var(--accent)}
.tl .tk{display:block;font-size:8pt;font-weight:700;line-height:1.3;margin-top:4pt;overflow-wrap:anywhere}
.tl .td{display:block;font-size:7.3pt;color:var(--muted);margin-top:1pt}
/* findings */
.fd{margin:0 0 15pt}
.fd+.fd{margin-top:20pt}
.fd.np{break-before:page;page-break-before:always}
.fd-top{break-inside:avoid;page-break-inside:avoid}
.fd-h{display:table;width:100%;table-layout:auto;border-collapse:collapse}
.fd-h>*{display:table-cell;vertical-align:middle}
.fd-id{width:1%;white-space:nowrap;font-family:var(--fh);font-weight:700;font-size:10pt;padding:7pt 10pt;letter-spacing:.02em}
.fd-h h2{font-size:12.5pt;line-height:1.28;padding:6pt 10pt;color:var(--text);overflow-wrap:anywhere;background:var(--soft)}
.fd-badge{width:1%;white-space:nowrap;padding:0 10pt;background:var(--soft);text-align:right}
.fd-m{display:table;width:100%;table-layout:fixed;border-collapse:collapse;border-bottom:1px solid var(--rule)}
.fd-m>div{display:table-row}
.fd-c{display:table-cell;padding:5pt 8pt 5pt 0;vertical-align:top;border-top:1px solid var(--rule);overflow-wrap:anywhere}
.fd-m>div:first-child .fd-c{border-top:none;padding-top:7pt}
.fd-c .k{display:block;font-size:6.5pt;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:1.5pt}
.fd-c .v{display:block;font-size:9pt;line-height:1.4}
.fd-c .v.mono{font-family:var(--fm);font-size:7.8pt}
.fd-c .v b{font-size:11pt}
.meter{display:inline-block;width:56pt;height:3.5pt;background:var(--rule);border-radius:2px;vertical-align:middle;margin-left:6pt;overflow:hidden}
.meter i{display:block;height:100%}
.aff{margin:0;padding:0;list-style:none}
.aff li{display:inline-block;font-family:var(--fm);font-size:7.8pt;background:var(--soft);border:1px solid var(--rule);border-radius:2.5px;padding:.5pt 5pt;margin:0 3pt 2.5pt 0;overflow-wrap:anywhere;max-width:100%}
/* figures */
figure{margin:0 0 10pt}
figure.img{break-inside:avoid;page-break-inside:avoid;text-align:center}
figure.img.al{text-align:left}figure.img.arr{text-align:right}
figure.img img{max-width:100%;max-height:150mm;height:auto;border:1px solid var(--rule);border-radius:2px;display:inline-block;vertical-align:top}
figcaption{font-size:8pt;color:var(--muted);overflow-wrap:anywhere;line-height:1.4}
figcaption b{color:var(--text);font-weight:700}
figure.img figcaption{margin:4pt 0 0;text-align:center}
figure.ev{border:1px solid var(--rule);border-radius:3px;overflow:hidden}
figure.ev figcaption{background:var(--soft);padding:4pt 9pt;border-bottom:1px solid var(--rule);break-after:avoid;page-break-after:avoid}
figure.ev figcaption .cap{color:var(--text);font-weight:700}
figure.ev pre{margin:0;border:none;border-radius:0;background:#fff}
figure.ev figure.img{margin:0;padding:6pt}
figure.ev .trunc{font-size:7.5pt;color:var(--muted);font-style:italic;padding:3pt 9pt;border-top:1px solid var(--rule)}
.cmdc{border:1px solid var(--rule);border-radius:3px;margin:0 0 10pt;break-inside:avoid;page-break-inside:avoid;overflow:hidden}
.cmdc .ch{padding:4pt 9pt;background:var(--soft);border-bottom:1px solid var(--rule);font-size:8.5pt}
.cmdc .ch b{font-weight:700}
.tag{display:inline-block;font-size:6.5pt;font-weight:700;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--rule);border-radius:2.5px;padding:.5pt 4.5pt;margin-right:5pt;color:var(--muted);background:#fff;position:relative;top:-.5pt}
.cmdc .cd{padding:5pt 9pt 0;font-size:8.8pt}
.cmdc pre{margin:0;border:none;border-radius:0;background:#fff}
/* callouts */
.co{border:1px solid var(--rule);border-left:3pt solid var(--cc,#64748b);border-radius:2.5px;margin:0 0 10pt;padding:6pt 10pt 1pt;background:#fff}
.co.short{break-inside:avoid;page-break-inside:avoid}
.co-h{font-size:7pt;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--cc,#64748b);margin-bottom:4pt;break-after:avoid;page-break-after:avoid}
.co-h .sv{margin-left:6pt;letter-spacing:.07em}
.co-h .cv{margin-left:6pt;color:var(--muted);letter-spacing:.04em}
.co-t{font-family:var(--fh);font-size:10.5pt;font-weight:700;margin:0 0 4pt;color:var(--text);text-transform:none;letter-spacing:0}
/* checklists */
ul.ck{list-style:none;padding-left:2pt}
ul.ck>li{position:relative;padding-left:15pt}
.bx{position:absolute;left:0;top:2.6pt;width:8.2pt;height:8.2pt;border:1.1pt solid var(--muted);border-radius:1.5px;background:#fff}
.bx.on{background:var(--accent);border-color:var(--accent)}
.bx.on:after{content:"";position:absolute;left:2pt;top:.1pt;width:2.4pt;height:4.8pt;border:solid var(--on-accent);border-width:0 1.2pt 1.2pt 0;transform:rotate(45deg)}
.docfoot{padding:5mm var(--mr) 7mm var(--ml);color:var(--muted);font-size:7.5pt;display:flex;justify-content:space-between;gap:12px;border-top:1px solid var(--rule)}
@media screen and (max-width:840px){.doc{margin:0 auto;box-shadow:none}}
@media screen and (max-width:700px){.doc{margin:0}.body{padding:10mm 7mm}.cover{height:auto;min-height:0}.cs-band .cv-band,.cs-band .cv-rest{padding-left:8mm;padding-right:8mm}.cs-full .cover,.cs-simple .cover{padding:10mm 8mm}.cs-full .cv-head,.cs-simple .cv-head{margin-top:16mm}.cv-rest{margin-top:10mm}.dash,.dash>div{display:block;width:auto}.tile{border-left:none}}
"""
_THEME_CSS={
"corporate":"""
.t-corporate .sh h1{font-weight:700}
.t-corporate table.t thead th{text-transform:none}
.t-corporate .fd-h>*{border-bottom:1.5pt solid var(--sc)}
.t-corporate .dash-o{border-radius:2px 0 0 2px}
""",
"modern":"""
.t-modern .cv-title{font-weight:900;letter-spacing:-.015em}
.t-modern .cv-company{letter-spacing:.2em}
.t-modern .toc-h{border-bottom:none;padding-bottom:0;font-size:25pt;font-weight:900}
.t-modern .toc-h:before,.t-modern .sh:before{content:"";display:block;width:16mm;height:1.5mm;background:var(--accent);margin-bottom:4mm}
.t-modern .sh{display:table;width:100%}
.t-modern .sh:before{display:none}
.t-modern .sh .sn{display:table-cell;width:1%;white-space:nowrap;vertical-align:baseline;font-size:36pt;font-weight:900;letter-spacing:-.02em;line-height:1;color:var(--accent);padding-right:5mm;text-transform:none}
.t-modern .sh h1{display:table-cell;vertical-align:baseline;border-bottom:none;padding-bottom:0;font-size:22pt;font-weight:900;color:var(--text)}
.t-modern .sh.nonum h1{border-left:1.5mm solid var(--accent);padding-left:4mm}
.t-modern .label{color:var(--text);letter-spacing:.12em}
.t-modern .label:before{content:"";display:inline-block;width:5pt;height:5pt;background:var(--accent);margin-right:5pt;position:relative;top:-.5pt}
.t-modern table.t tbody tr:last-child>*{border-bottom:1.2pt solid var(--text)}
.t-modern .tw table.t.mid tbody tr:last-child>*{border-bottom:1px solid var(--rule)}
.t-modern table.t.kv{border-top-color:var(--text)}
.t-modern table.t thead th{text-transform:uppercase;font-size:7.3pt;letter-spacing:.09em}
.t-modern .tile .n,.t-modern .dash-o .v{font-weight:900}
.t-modern .tile .n{font-size:25pt}
.t-modern .tile{background:#fff;border-top-width:4pt;border-left:none;padding-left:9pt}
.t-modern .dash-o{background:#0f172a!important}
.t-modern .dash-o .v{color:var(--sc-on-dark)}
.t-modern .fd-h h2{background:#0f172a;color:#fff;font-size:12.5pt}
.t-modern .fd-badge{background:#0f172a}
.t-modern .fd-id{font-weight:900}
.t-modern .sv{border-radius:20px;padding-left:7pt;padding-right:7pt}
.t-modern blockquote{border-left-color:var(--accent)}
""",
"minimal":"""
.t-minimal .classbar{background:#fff;color:var(--text);border-bottom:1px solid var(--rule)}
.t-minimal .cs-band .cv-band:after{display:none}
.t-minimal .toc-h,.t-minimal .sh h1{border-bottom:.8pt solid var(--text);font-size:18pt;color:var(--text)}
.t-minimal .sh .sn{color:var(--muted)}
.t-minimal .label{color:var(--text)}
.t-minimal table.t thead th{background:none;color:var(--text);border-bottom:1pt solid var(--text);border-top:1pt solid var(--text)}
.t-minimal table.t tbody tr:last-child>*{border-bottom:1pt solid var(--text)}
.t-minimal .tw table.t.mid tbody tr:last-child>*{border-bottom:1px solid var(--rule)}
.t-minimal table.t.kv{border-top:1pt solid var(--text)}
.t-minimal table.t tbody th{background:none}
.t-minimal table.t td.tot,.t-minimal table.t th.tot{background:none}
.t-minimal .sv{background:none!important;color:var(--text)!important;border:1px solid var(--rule);padding-left:4pt}
.t-minimal .sv:before{content:"";display:inline-block;width:5.5pt;height:5.5pt;border-radius:50%;background:var(--sc);margin-right:4pt}
.t-minimal .dash-o{background:#fff!important;color:var(--text)!important;border:1pt solid var(--text);border-left:4pt solid var(--sc)}
.t-minimal .tile{background:#fff;border-top:none;border-left:none;border-bottom:1px solid var(--rule);padding-left:12pt}
.t-minimal .tile .n:before{content:"";display:inline-block;width:6pt;height:6pt;border-radius:50%;background:var(--sc);margin-right:5pt;position:relative;top:-9pt}
.t-minimal .fd-h>*{border-top:1pt solid var(--text);border-bottom:1px solid var(--rule)}
.t-minimal .fd-id{background:none!important;color:var(--text)!important;padding-left:0;border-left:3pt solid var(--sc);padding-left:8pt}
.t-minimal .fd-h h2,.t-minimal .fd-badge{background:none}
.t-minimal pre,.t-minimal blockquote,.t-minimal code,.t-minimal figure.ev figcaption,.t-minimal .cmdc .ch,.t-minimal .aff li{background:#fff}
.t-minimal blockquote{border-left-color:var(--text)}
.t-minimal .co{border-left-color:var(--text)}
.t-minimal .co-h{color:var(--text)}
.t-minimal .bx.on{background:var(--text);border-color:var(--text)}
""",
}
_PRINT_CSS="""
@media print{
body{background:#fff}
.doc{margin:0;box-shadow:none;width:auto;max-width:none;overflow:visible}
.body{padding:0}
.classbar,.docfoot{display:none}
.cover{break-after:page;page-break-after:always}
}
"""
# Browser printing of the exported HTML file (Chromium honours margin boxes; other engines simply ignore them).
_PAGE_BROWSER="""
@page{size:%(size)s;margin:%(mt)smm %(mr)smm %(mb)smm %(ml)smm;
@top-left{content:"%(company)s";font-size:7.5pt;color:#6b7280}
@top-right{content:"%(title)s";font-size:7.5pt;color:#6b7280}
@bottom-left{content:"%(classification)s";font-size:7.5pt;font-weight:700;color:#374151}
@bottom-right{content:"Page " counter(page) " of " counter(pages);font-size:7.5pt;color:#6b7280}}
@page:first{margin:0;@top-left{content:none}@top-right{content:none}@bottom-left{content:none}@bottom-right{content:none}}
"""
_CMD_TAG='<span class="tag">Command</span>'
def _css_str(s):
    """Text inside a CSS string literal of an @page margin box."""
    out=[]
    for ch in rx._s(s)[:120]:
        if ch in '"\\' or ord(ch)<32 or ch in "<>&":out.append("\\%x "%ord(ch))
        else:out.append(ch)
    return "".join(out)
def _mm(v):return ("%.2f"%v).rstrip("0").rstrip(".")
class _R:
    """One render: collects the position markers the PDF pipeline reads back after printing."""
    def __init__(self,doc,mode):
        self.doc=doc;self.mode=mode or {};self.dz=doc["design"]
        self.print=bool(self.mode.get("engine"));self.marks=[];self.np=bool(doc["options"].get("findings_new_page"))
    def mark(self,kind,anchor):
        if not self.print:return ""
        k=len(self.marks)%60;self.marks.append({"kind":kind,"anchor":anchor,"code":k})
        return f'<i class="mk" style="background:#ff{254-k//12:02x}{253-k%12:02x}"></i>'
    # ---- inline ----
    def runs(self,runs):
        out=[]
        for r in runs or []:
            if r.get("redact"):out.append('<span class="redact">REDACTED</span>');continue
            t=_e(r.get("text","")).replace("\n","<br>")
            if r.get("code"):t=f"<code>{t}</code>"
            if r.get("b"):t=f"<strong>{t}</strong>"
            if r.get("i"):t=f"<em>{t}</em>"
            if r.get("u"):t=f"<u>{t}</u>"
            if r.get("s"):t=f"<s>{t}</s>"
            st=[]
            if r.get("color"):st.append("color:"+rx._hex(r["color"],"#000000"))
            if r.get("bg"):st.append("background:"+rx._hex(r["bg"],"#ffffff"))
            if r.get("size"):st.append("font-size:%.1fpt"%(max(8,min(72,int(r["size"])))*0.75))
            if st:t=f'<span style="{";".join(st)}">{t}</span>'
            if r.get("muted"):t=f'<span class="muted">{t}</span>'
            href=rx._safe_href(r.get("href"));link=rx._s(r.get("link"))
            if link.startswith("#"):t=f'<a href="{_e(link)}"><strong>{t}</strong></a>'
            elif r.get("fref"):t=f"<strong>{t}</strong>"
            elif href:t=f'<a href="{_e(href)}" target="_blank" rel="noopener noreferrer">{t}</a>'
            out.append(t)
        return "".join(out)
    def sev(self,s,text=None):
        return f'<span class="sv" style="background:{SEV_COLORS[s]};color:{SEV_ON[s]};--sc:{SEV_COLORS[s]}">{_e(text or SEV_LABELS[s])}</span>'
    def status(self,st,label):
        return f'<span class="st"><i style="background:{STATUS_COLORS.get(st,"#64748b")}"></i>{_e(label)}</span>'
    # ---- blocks ----
    def image(self,b,inner=False):
        a=b.get("asset");cap=rx.figure_caption(b," — ") if not inner else rx._s(b.get("caption"))
        if not a:return f'<div class="missing">Image not available{": "+_e(b.get("caption") or b.get("alt")) if (b.get("caption") or b.get("alt")) else ""}</div>'
        st=""
        if b.get("width"):st=f' style="width:{int(b["width"])}%"'
        elif b.get("px"):st=f' style="width:{b["px"]*0.75:.1f}pt"'
        cls="img"+({"C":"","R":" arr"}.get(b.get("align"),"" if not (b.get("width") or b.get("px")) else ""))
        if b.get("fig") and cap:
            n=f"Figure {b['fig']}";rest=cap[len(n):]
            caph=f"<figcaption><b>{n}</b>{_e(rest)}</figcaption>"
        else:caph=f"<figcaption>{_e(cap)}</figcaption>" if cap else ""
        return f'<figure class="{cls}"><img src="{rx.data_uri(a)}" alt="{_e(b.get("alt") or b.get("caption"))}"{st}>{caph}</figure>'
    def cell(self,c,tag,tb):
        cls=[]
        if c.get("align")=="C":cls.append("c")
        elif c.get("align")=="R":cls.append("r")
        if c.get("bold") and not c.get("sev"):cls.append("b")
        if c.get("mono"):cls.append("mono")
        style=[]
        if c.get("sev"):pass
        elif c.get("fill") and rx._hex(c["fill"],"")=="#eef1f5":cls.append("tot")
        else:
            if c.get("fill"):style.append("background:"+rx._hex(c["fill"],"#ffffff"))
            if c.get("color"):style.append("color:"+rx._hex(c["color"],"#000000"))
        attrs=(f' class="{" ".join(cls)}"' if cls else "")+(f' style="{";".join(style)}"' if style else "")
        if c.get("colspan",1)>1:attrs+=f' colspan="{int(c["colspan"])}"'
        if c.get("rowspan",1)>1:attrs+=f' rowspan="{int(c["rowspan"])}"'
        if c.get("sev"):inner=self.sev(c["sev"],SEV_SHORT[c["sev"]])
        elif c.get("status"):inner=self.status(c["status"],c.get("text",""))
        elif tb.get("roadmap") and c is tb["_row"][0] and c.get("text") not in ("","-"):inner=f'<span class="pr">{_e(c["text"])}</span>'
        else:inner=self.runs(c["runs"]) if c.get("runs") is not None else _e(c.get("text","")).replace("\n","<br>")
        link=rx._s(c.get("link"))
        if link.startswith("#"):inner=f'<a href="{_e(link)}">{inner}</a>'
        return f"<{tag}{attrs}>{inner}</{tag}>"
    def table(self,b):
        rows=b["rows"];cls="t"+(" kv" if b.get("kv") else "")+("" if b.get("kv") or b.get("nozebra") else " zebra")
        if self.mode.get("engine")=="webkit" and len(rows)>1 and not any(c and c.get("rowspan",1)>1 for r in rows for c in r):return self.table_rows(b,cls.replace(" zebra",""),"zebra" in cls)
        out=[f'<table class="{cls}">']
        if b.get("widths"):out.append("<colgroup>"+"".join(f'<col style="width:{w*100:.2f}%">' for w in b["widths"])+"</colgroup>")
        body=rows;tb=dict(b)
        if b.get("header") and rows:
            tb["_row"]=rows[0]
            out.append("<thead><tr>"+"".join(self.cell(c,"th",{}) for c in rows[0] if c)+"</tr></thead>");body=rows[1:]
        out.append("<tbody>")
        for row in body:
            tb["_row"]=row
            out.append("<tr>"+"".join(self.cell(c,"th" if c.get("header") else "td",tb) for c in row if c)+"</tr>")
        out.append("</tbody></table>")
        return "".join(out)
    def table_rows(self,b,cls,zebra):
        """WebKit print splits a table row across pages; a table of its own per row (same fixed column widths) cannot be split."""
        rows=b["rows"];n=max(len(r) for r in rows);widths=b.get("widths")
        if not widths or len(widths)!=n:widths=([0.26]+[0.74/(n-1)]*(n-1)) if b.get("kv") and n>1 else [1.0/n]*n
        cg="<colgroup>"+"".join(f'<col style="width:{w*100:.2f}%">' for w in widths)+"</colgroup>"
        out=['<div class="tw">'];tb=dict(b);body=rows;parts=[]
        if b.get("header"):
            parts.append(f'<table class="{cls} hd mid">{cg}<thead><tr>'+"".join(self.cell(c,"th",{}) for c in rows[0] if c)+"</tr></thead></table>");body=rows[1:]
        head=len(parts)
        for i,row in enumerate(body):
            tb["_row"]=row;last=i==len(body)-1
            c2=cls+("" if last else " mid")+(" ev" if zebra and i%2==1 else "")+(" nf" if i else "")
            parts.append(f'<table class="{c2}">{cg}<tbody><tr>'+"".join(self.cell(c,"th" if c.get("header") else "td",tb) for c in row if c)+"</tr></tbody></table>")
        # No header alone at the foot of a page and no single row alone at the top of the next one.
        a=head+1 if head and len(parts)>1 else 0;z=len(parts)-2 if len(body)>=4 else len(parts)
        if a:out.append('<div class="keep">'+"".join(parts[:a])+"</div>")
        out.append("".join(parts[a:z]))
        if z<len(parts):out.append('<div class="keep">'+"".join(parts[z:])+"</div>")
        out.append("</div>")
        return "".join(out)
    def figure(self,b):
        n=f"<b>Figure {b['fig']}</b> — " if b.get("fig") else ""
        cap=n+f'<span class="cap">{_e(b.get("caption"))}</span>'+(f' <span class="info">· {_e(b["info"])}</span>' if b.get("info") else "")
        inner=f"<figcaption>{cap}</figcaption>"
        if b.get("pre"):inner+=f"<pre>{_e(b['pre'])}</pre>"
        if b.get("image"):inner+=self.image(b["image"],True)
        if b.get("truncated"):inner+=f'<div class="trunc">Output truncated: {int(b["truncated"])} more line(s) not shown.</div>'
        return f'<figure class="ev">{inner}</figure>'
    def callout(self,b):
        col={"info":"#2563eb","warning":"#b45309","credential":"#6d28d9","evidence":"#0f766e"}.get(b["kind"]) or (SEV_INK[b["sev"]] if b.get("sev") else "#b91c1c")
        head=_e(b["label"])+(self.sev(b["sev"]) if b.get("sev") else "")+(f'<span class="cv">CVSS {_e(b["cvss"])}</span>' if b.get("cvss") else "")
        title=f'<div class="co-t">{_e(b["title"])}</div>' if b.get("title") else ""
        short=len(rx.blocks_text(b["blocks"]))<1400 and not any(x["t"] in ("image","figure","table") for x in b["blocks"])
        return f'<div class="co{" short" if short else ""}" style="--cc:{col}"><div class="co-h">{head}</div>{title}{self.blocks(b["blocks"])}</div>'
    def cmd(self,b):
        tags="".join(f'<span class="tag">{_e(x)}</span>' for x in (b.get("kind"),) if x)
        head=f'<div class="ch">{tags or _CMD_TAG}<b>{_e(b["title"])}</b>'+(f' <span class="muted">· {_e(b["category"])}</span>' if b.get("category") else "")+"</div>"
        desc=f'<div class="cd">{self.blocks(b["desc"])}</div>' if b.get("desc") else ""
        return f'<div class="cmdc">{head}{desc}<pre>{_e(b["text"])}</pre></div>'
    def dashboard(self,b):
        s=b["overall"];col=SEV_COLORS[s] if s else "#15803d"
        on_dark={"critical":"#fca5a5","high":"#fca5a5","medium":"#fcd34d","low":"#93c5fd","info":"#cbd5e1"}.get(s,"#86efac")
        bs=b["by_status"];bits=[f"{b['total']} finding{'s' if b['total']!=1 else ''}"]
        for st,word in (("open","open"),("retest","awaiting retest"),("fixed","fixed"),("accepted","risk accepted")):
            if bs.get(st):bits.append(f"{bs[st]} {word}")
        out=[f'<div class="dash"><div class="dash-o" style="background:{col};--sc:{col};--sc-on-dark:{on_dark};{"color:"+SEV_ON[s] if s else ""}"><div class="k">Overall risk rating</div><div class="v">{_e(b["overall_label"])}</div><div class="s">{_e(" · ".join(bits))}</div></div>']
        for x in SEVERITIES:
            n=b["counts"][x]
            out.append(f'<div class="tile{" zero" if not n else ""}" style="border-top-color:{SEV_COLORS[x]};--sc:{SEV_COLORS[x]}"><div class="n">{n}</div><div class="l">{SEV_SHORT[x]}</div></div>')
        out.append("</div>")
        return "".join(out)
    def charts(self,b):return f'<div class="chart">{charts_svg(b["counts"],b["total"],b.get("by_status"),self.dz)}</div>'
    def matrix(self,b):
        note='<div class="mx-note">Likelihood is estimated from the CVSS exploitability metrics where a finding does not state one. Fixed findings are not plotted.</div>' if b.get("estimated") else '<div class="mx-note">Fixed findings are not plotted.</div>'
        return f'<div class="chart">{matrix_svg(b,self.dz)}</div>{note}'
    def timeline(self,b):
        items=b["items"];out=[]
        if 2<=len(items)<=8:
            out.append('<div class="tl">'+"".join(f'<div class="{"on" if m["done"] else ""}"><span class="ln"></span><span class="nd"></span><span class="tk">{_e(m["label"])}</span><span class="td">{_e(m["date"])}</span></div>' for m in items)+"</div>")
        rows=[[rx._hc("Milestone"),rx._hc("Date"),rx._hc("Status"),rx._hc("Notes")]]
        for m in items:rows.append([rx._c(m["label"],bold=True),rx._c(m["date"]),rx._c("Completed" if m["done"] else "Planned",status="fixed" if m["done"] else "accepted"),rx._c(m["notes"] or "-")])
        out.append(self.table(rx._table(rows,[0.3,0.2,0.16,0.34])))
        return "".join(out)
    def finding_top(self,b):
        f=b["f"];s=f["severity"];col=SEV_COLORS[s]
        badge=self.sev(s,SEV_LABELS[s]+(" · "+f["cvss"] if f["cvss"] else ""))
        head=f'<div class="fd-h" style="--sc:{col}"><span class="fd-id" style="background:{col};color:{SEV_ON[s]}">{_e(f["number"])}</span><h2>{self.mark("target",f["anchor"])}{_e(f["title"])}</h2><span class="fd-badge">{badge}</span></div>'
        def cellh(k,v,cls=""):return f'<div class="fd-c" style="width:25%"><span class="k">{_e(k)}</span><span class="v{cls}">{v}</span></div>'
        try:sc=float(f["cvss"])
        except Exception:sc=None
        cv=(f'<b>{_e(f["cvss"])}</b><span class="meter"><i style="width:{sc*10:.0f}%;background:{col}"></i></span>' if sc is not None else '<span class="muted">Not scored</span>')
        rows=['<div>'+cellh("Severity",f'<span style="color:{SEV_INK[s]};font-weight:700">{SEV_LABELS[s]}</span>')+cellh(f.get("cvss_label") or "CVSS v3.1",cv)+cellh("Status",self.status(f["status"],rx.STATUS_LABELS.get(f["status"],f["status"].title())))+cellh("Likelihood",_e(f["likelihood"].title() or "–"))+"</div>"]
        out=[head,'<div class="fd-m">'+rows[0]+"</div>"]
        extra=[]
        if f.get("cvss_vector_any") or f["cvss_vector"]:extra.append(("CVSS vector",_e(f.get("cvss_vector_any") or f["cvss_vector"])," mono"))
        refs=" · ".join(x for x in (f["cwe"],f["owasp"]) if x)
        if refs:extra.append(("Classification",_e(refs),""))
        if f.get("cves"):extra.append(("CVE",'<ul class="aff">'+"".join(f'<li><a href="{_e(c["url"])}" target="_blank" rel="noopener noreferrer">{_e(c["id"])}</a>'+(f' <b style="font-size:inherit;color:{SEV_INK["critical"]}">{_e(rx.KEV_LABEL)}</b>' if c["kev"] else "")+"</li>" for c in f["cves"])+"</ul>",""))
        if f["affected_list"]:extra.append(("Affected assets",'<ul class="aff">'+"".join(f"<li>{_e(a)}</li>" for a in f["affected_list"])+"</ul>",""))
        if extra:
            out.append('<div class="fd-m">'+"".join(f'<div><div class="fd-c" style="width:19%"><span class="k" style="margin-top:2pt">{_e(k)}</span></div><div class="fd-c"><span class="v{cls}">{v}</span></div></div>' for k,v,cls in extra)+"</div>")
        return '<div class="fd-top">'+"".join(out)+"</div>"
    def _small(self,b):
        t=b["t"]
        if t=="p":return len(rx.runs_text(b["runs"]))<1100
        if t=="list":return len(b["items"])<=9 and len(rx.blocks_text([b]))<1100
        if t=="table":return len(b["rows"])<=9
        if t=="figure":return b.get("pre","").count("\n")<28 and not b.get("image")
        if t=="pre":return b["text"].count("\n")<28
        if t in ("image","charts","matrix","dashboard","cmd","timeline"):return True
        if t=="callout":return len(rx.blocks_text(b["blocks"]))<1100
        return False
    def block(self,b):
        t=b["t"]
        al={"C":' class="ac"',"R":' class="ar"',"J":' class="aj"'}.get(b.get("align"),"")
        if t=="p":return f"<p{al}>{self.runs(b['runs'])}</p>"
        if t=="h":return f"<h{b['level']}{al}>{self.runs(b['runs'])}</h{b['level']}>"
        if t=="label":return f'<div class="label">{_e(b["text"])}</div>'
        if t=="pre":
            lang=b.get("lang") or ""
            return f'<div class="code"><span class="lang">{_e(lang)}</span><pre data-lang="{_e(lang)}">{_e(b["text"])}</pre></div>' if lang else f"<pre>{_e(b['text'])}</pre>"
        if t=="quote":return f"<blockquote{al}>{self.blocks(b['blocks'])}</blockquote>"
        if t=="list":
            if b.get("check"):
                return '<ul class="ck">'+"".join(f'<li><span class="bx{" on" if it.get("checked") else ""}"></span>{self.runs(it["runs"])}{self.blocks(it["blocks"])}</li>' for it in b["items"])+"</ul>"
            tag="ol" if b["ordered"] else "ul";start=f' start="{int(b["start"])}"' if b.get("start") else ""
            return f"<{tag}{start}>"+"".join(f"<li>{self.runs(it['runs'])}{self.blocks(it['blocks'])}</li>" for it in b["items"])+f"</{tag}>"
        if t=="table":return self.table(b)
        if t=="hr":return "<hr>"
        if t=="image":return self.image(b)
        if t=="figure":return self.figure(b)
        if t=="callout":return self.callout(b)
        if t=="cmd":return self.cmd(b)
        if t=="dashboard":return self.dashboard(b)
        if t=="charts":return self.charts(b)
        if t=="chart":return self.charts({"counts":b["counts"],"total":b["total"]})
        if t=="matrix":return self.matrix(b)
        if t=="timeline":return self.timeline(b)
        return ""
    def blocks(self,blocks):
        out=[];i=0;n=len(blocks);open_fd=False
        while i<n:
            b=blocks[i];t=b["t"]
            if t=="finding":
                if open_fd:out.append("</article>")
                first=not any(x["t"]=="finding" for x in blocks[:i])
                out.append(f'<article class="fd{" np" if self.np and not first else ""}" id="{_e(b["anchor"])}">');open_fd=True
                top=self.finding_top(b);i+=1
                if i<n and blocks[i].get("fmeta"):i+=1
                # The header never ends a page on its own: it travels with the first label and block that follow it.
                tail=[]
                if i<n and blocks[i]["t"]=="label":
                    tail.append(self.block(blocks[i]));i+=1
                    if i<n and self._small(blocks[i]) and blocks[i]["t"] not in ("finding","finding_end"):tail.append(self.block(blocks[i]));i+=1
                out.append(f'<div class="keep">{top}{"".join(tail)}</div>')
                continue
            if t=="finding_end":
                if open_fd:out.append("</article>");open_fd=False
                i+=1;continue
            if b.get("fmeta"):
                i+=1;continue
            if t in ("label","h") and i+1<n and blocks[i+1]["t"] not in ("label","h","finding","finding_end") and self._small(blocks[i+1]):
                out.append(f'<div class="keep">{self.block(b)}{self.block(blocks[i+1])}</div>');i+=2;continue
            out.append(self.block(b));i+=1
        if open_fd:out.append("</article>")
        return "".join(out)
    # ---- document ----
    def cover(self):
        doc=self.doc;c=doc["cover"];cs=self.dz["cover_style"]
        chip=cs!="simple"
        logo=f'<img class="cv-logo{" chip" if chip else ""}" src="{rx.data_uri(c["logo"])}" alt="{_e(c["company"])} logo">' if c.get("logo") else ""
        company=f'<span class="cv-company">{_e(c["company"])}</span>' if c["company"] else "<span></span>"
        top=f'<div class="cv-top">{logo or company}{company if logo else "<span></span>"}</div>'
        head='<div class="cv-head">'+('<div class="cv-rule"></div>' if cs=="full" else "")+(f'<div class="cv-kicker">{_e(c["subtitle"])}</div>' if c["subtitle"] else "")+f'<h1 class="cv-title">{_e(c["title"])}</h1>'+(f'<div class="cv-for">Prepared for <b>{_e(c["client"])}</b></div>' if c["client"] else "")+"</div>"
        facts=[(k,v) for k,v in c["facts"] if k!="Client"]
        rows=[]
        for i in range(0,len(facts),2):
            pair=facts[i:i+2]
            rows.append('<div class="cv-fr">'+"".join(f'<div class="cv-f"><span class="k">{_e(k)}</span><span class="v">{_e(v)}</span></div>' for k,v in pair)+('<div class="cv-f"></div>' if len(pair)==1 else "")+"</div>")
        ft='<div class="cv-facts">'+"".join(rows)+"</div>" if rows else ""
        foot='<div class="cv-foot">'+(f'<span class="cv-class">{_e(c["classification"])}</span>' if c["classification"] else "<span></span>")+(f'<span class="cv-note">{_e(doc["banner"] or doc["footer"])}</span>' if (doc["banner"] or doc["footer"]) else "")+"</div>"
        if cs=="band":return f'<section class="cover"><div class="cv-band">{top}{head}</div><div class="cv-rest">{ft}{foot}</div></section>'
        return f'<section class="cover">{top}{head}<div class="cv-rest">{ft}{foot}</div></section>'
    def toc(self):
        out=['<nav class="toc"><h1 class="toc-h">Contents</h1>'];app=False
        secs={s["anchor"]:s for s in self.doc["sections"]}
        for t in self.doc["toc"]:
            mk=self.mark("toc",t["anchor"])
            if t["level"]==1:
                sec=secs.get(t["anchor"]) or {}
                if sec.get("appendix") and not app:
                    app=True;out.append('<div class="toc-app">Appendices</div>')
                out.append(f'<a class="toc-r l1" href="#{_e(t["anchor"])}"><span class="n">{_e(sec.get("number") or "")}</span><span class="tt">{mk}{_e(sec.get("title") or t["text"])}</span><span class="ld"></span><span class="pg"></span></a>')
            else:
                fid,_sep,title=t["text"].partition("  ")
                dot=f'<span class="dot" style="background:{SEV_COLORS[t["severity"]]}"></span>' if t.get("severity") else ""
                out.append(f'<a class="toc-r l2" href="#{_e(t["anchor"])}"><span class="n"></span>{dot}<span class="tt">{mk}<span class="fid">{_e(fid)}</span>{_e(title or "")}</span><span class="ld"></span><span class="pg"></span></a>')
        out.append("</nav>")
        return "".join(out)
    def section(self,sec,first):
        num=sec.get("number") or ""
        sn=f'<span class="sn">{_e(num)}</span>' if num else ""
        if self.dz["theme"]=="corporate" and num:sn=f'<span class="sn">Section {_e(num)}</span>'
        head=f'<header class="sh{"" if num else " nonum"}">{sn}<h1>{self.mark("target",sec["anchor"])}{_e(sec["title"])}</h1></header>'
        return f'<section class="sec{" first" if first else ""} k-{_e(sec["kind"])}" id="{_e(sec["anchor"])}">{head}{self.blocks(sec["blocks"])}</section>'
    def css(self):
        dz=self.dz;o=self.doc["options"];m=dz["margins"];pw,ph=design.PAGE_MM["Letter" if o["page_size"]=="Letter" else "A4"]
        v={"--accent":dz["accent"],"--on-accent":dz["on_accent"],"--on-soft":dz["on_accent_soft"],"--on-line":design.mix(dz["on_accent"],dz["accent"],0.62),"--ink":dz["ink"],"--secondary":dz["secondary"],"--secondary-ink":dz["secondary_ink"],
            "--text":dz["text"],"--muted":dz["muted"],"--rule":dz["rule"],"--soft":dz["soft"],"--zebra":dz["zebra"],"--hf":dz["head_fill"] or "transparent","--ho":dz["head_on"],
            "--fb":design.css_family(dz,"body"),"--fh":design.css_family(dz,"head"),"--fm":design.css_family(dz,"mono"),
            "--pw":_mm(pw)+"mm","--ph":_mm(ph)+"mm","--mt":_mm(m["top"])+"mm","--mr":_mm(m["right"])+"mm","--mb":_mm(m["bottom"])+"mm","--ml":_mm(m["left"])+"mm"}
        # The bundled faces are embedded on request (the app's preview and exports ask for them) and always for the print engine;
        # without them the same stacks fall back to the fonts of the machine.
        fonts=design.font_face_css(dz,bool(o.get("embed_fonts")) or self.print,black=dz["theme"]=="modern")
        out=[fonts,":root{"+";".join(f"{k}:{val}" for k,val in v.items())+"}",_BASE_CSS,_THEME_CSS.get(dz["theme"],""),_PRINT_CSS]
        eng=self.mode.get("engine")
        if eng:
            part=self.mode.get("part","body")
            # The engine prints the cover (no margins) and the body (page margins) as two jobs; headers and footers are stamped afterwards.
            # Anything wider than the page would make WebKit shrink the whole document to fit: clip instead.
            out.append("html,body{background:#fff}.doc{margin:0;box-shadow:none;width:auto;max-width:none;overflow:visible}.body{padding:0}.sec,.toc{overflow-x:clip}.classbar,.docfoot{display:none}")
            if part=="cover":
                out.append(f".body{{display:none}}.cover{{height:{_mm(ph-0.6)}mm;break-after:auto;page-break-after:auto}}@page{{size:{_mm(pw)}mm {_mm(ph)}mm;margin:0}}")
            else:
                out.append(f".cover{{display:none}}@page{{size:{_mm(pw)}mm {_mm(ph)}mm;margin:{_mm(m['top'])}mm {_mm(m['right'])}mm {_mm(m['bottom'])}mm {_mm(m['left'])}mm}}")
            if eng=="webkit":out.append(f"html{{zoom:{WEBKIT_PRINT_ZOOM}}}")
        else:
            d=self.doc
            out.append(_PAGE_BROWSER%{"size":"letter" if o["page_size"]=="Letter" else "A4","mt":_mm(m["top"]),"mr":_mm(m["right"]),"mb":_mm(m["bottom"]),"ml":_mm(m["left"]),
                "company":_css_str(d["company"]),"title":_css_str(d["title"]),"classification":_css_str(d["classification"])})
            if not o["include_cover"]:out.append("@page:first{margin:%smm %smm %smm %smm}"%(_mm(m["top"]),_mm(m["right"]),_mm(m["bottom"]),_mm(m["left"])))
        return "".join(out)
    def render(self):
        doc=self.doc;o=doc["options"];dz=self.dz
        banner=doc["banner"] or (doc["classification"] and doc["classification"].upper()) or ""
        cls=f't-{dz["theme"]} cs-{dz["cover_style"]}'+(" pm" if self.print else "")
        body=[]
        part=self.mode.get("part")
        if banner and not self.print:body.append(f'<div class="classbar">{_e(banner)}</div>')
        if o["include_cover"] and part!="body":body.append(self.cover())
        if part!="cover":
            body.append('<div class="body">')
            if o["include_toc"] and doc["toc"]:body.append(self.toc())
            for i,sec in enumerate(doc["sections"]):body.append(self.section(sec,i==0))
            if not doc["sections"]:body.append('<p class="muted">This report has no visible sections.</p>')
            body.append("</div>")
            if not self.print:
                foot=[x for x in (doc["company"],doc["classification"],doc["footer"]) if x]
                body.append(f'<footer class="docfoot"><span>{_e(" · ".join(foot))}</span><span>{_e(doc["title"])}{" · v"+_e(doc["meta"]["version"]) if doc["meta"]["version"] else ""}</span></footer>')
        inner="".join(body)
        head=['<!doctype html><html lang="en" class="'+cls+'"><head><meta charset="utf-8">',f'<meta http-equiv="Content-Security-Policy" content="{rx.CSP}">','<meta name="viewport" content="width=device-width,initial-scale=1">','<meta name="generator" content="LOYA NG">',
            f"<title>{_e(doc['title'])}</title>",f"<style>{self.css()}</style></head><body><div class=\"doc\">"]
        return "".join(head)+inner+"</div></body></html>"
def render(doc,mode=None):
    """(html, marks). mode None = preview / HTML export; {"engine":"webkit"|"chromium","part":"cover"|"body"} = one print job, whose
    1px near-white markers (marks: kind/anchor/code, in document order) let the PDF pipeline find headings and contents rows again."""
    r=_R(doc,mode)
    return r.render(),r.marks
# ---- charts (inline SVG; fonts come from the page) ----
def _t(x,y,text,size=11,fill="#1f2933",anchor="start",weight="400",cls=""):
    c=' class="'+cls+'"' if cls else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{c}>{_e(text)}</text>'
def charts_svg(counts,total,by_status=None,dz=None):
    """Severity donut with its legend, and the findings of each status as a stacked bar."""
    text=(dz or {}).get("text","#1f2933");muted=(dz or {}).get("muted","#5f6b7a");rule=(dz or {}).get("rule","#d3d9e0")
    W,H=640,176;p=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Findings by severity and status">']
    cx,cy,r,sw=78,88,54,22;circ=2*math.pi*r;off=0.0
    p.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{rule}" stroke-width="{sw}" opacity=".55"/>')
    for s in SEVERITIES:
        if not total or not counts[s]:continue
        ln=circ*counts[s]/total
        p.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{SEV_COLORS[s]}" stroke-width="{sw}" stroke-dasharray="{max(0,ln-1.5):.3f} {circ-max(0,ln-1.5):.3f}" stroke-dashoffset="{-off:.3f}" transform="rotate(-90 {cx} {cy})"/>')
        off+=ln
    p.append(_t(cx,cy+6,str(int(total)),28,text,"middle","700","hd"))
    p.append(_t(cx,cy+21,"finding" if total==1 else "findings",9.5,muted,"middle"))
    lx=166
    for i,s in enumerate(SEVERITIES):
        y=36+i*26
        p.append(f'<rect x="{lx}" y="{y-9}" width="10" height="10" rx="2" fill="{SEV_COLORS[s]}"/>')
        p.append(_t(lx+17,y,SEV_LABELS[s],10.5,text))
        p.append(_t(lx+128,y,str(counts[s]),10.5,text,"end","700"))
    p.append(f'<line x1="322" y1="18" x2="322" y2="{H-18}" stroke="{rule}" stroke-width="1"/>')
    bs=by_status or {};x0,x1=424,598
    tot={st:sum((bs.get(st) or {}).values()) for st in rx.STATUSES};mx=max(list(tot.values())+[1])
    p.append(_t(346,22,"BY STATUS",8,muted,"start","700"))
    for i,st in enumerate(rx.STATUSES):
        y=38+i*32
        p.append(_t(346,y+13,rx.STATUS_LABELS[st],10.5,text))
        p.append(f'<rect x="{x0}" y="{y}" width="{x1-x0}" height="18" rx="2" fill="{rule}" opacity=".45"/>')
        x=float(x0)
        for s in SEVERITIES:
            n=(bs.get(st) or {}).get(s,0)
            if not n:continue
            w=(x1-x0)*n/mx
            p.append(f'<rect x="{x:.1f}" y="{y}" width="{max(1.5,w-1.5):.1f}" height="18" rx="2" fill="{SEV_COLORS[s]}"/>');x+=w
        p.append(_t(x1+10,y+13,str(tot[st]),10.5,text,"start","700"))
    p.append("</svg>")
    return "".join(p)
def chart_svg(counts,total):return charts_svg(counts,total)
def matrix_svg(b,dz=None):
    """Likelihood x impact grid; every cell lists the findings that sit in it."""
    text=(dz or {}).get("text","#1f2933");muted=(dz or {}).get("muted","#5f6b7a")
    levels=("low","medium","high");W=640;x0=96;cw=176;ch=62;y0=10;H=y0+3*ch+44
    p=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Risk matrix: likelihood by impact">']
    p.append(f'<text x="14" y="{y0+1.5*ch:.1f}" font-size="8" fill="{muted}" font-weight="700" text-anchor="middle" letter-spacing="1.2" transform="rotate(-90 14 {y0+1.5*ch:.1f})">LIKELIHOOD</text>')
    for ri,l in enumerate(reversed(levels)):
        y=y0+ri*ch
        p.append(_t(x0-10,y+ch/2+4,rx.LEVEL_LABELS[l],10.5,text,"end","700"))
        for ci,im in enumerate(levels):
            x=x0+ci*cw;risk=rx.cell_risk(l,im);items=b["cells"][l][im]
            p.append(f'<rect x="{x+1.5}" y="{y+1.5}" width="{cw-3}" height="{ch-3}" rx="3" fill="{SEV_TINTS[risk]}"/>')
            p.append(f'<rect x="{x+1.5}" y="{y+1.5}" width="4" height="{ch-3}" rx="2" fill="{SEV_COLORS[risk]}"/>')
            p.append(_t(x+cw-9,y+14,SEV_SHORT[risk].upper(),6.8,SEV_INK[risk],"end","700"))
            if items:p.append(_t(x+13,y+15,str(len(items)),11,SEV_INK[risk],"start","700","hd"))
            cx=x+13;cy=y+24;shown=0
            for it in items:
                w=len(it["number"])*5.6+11
                if cx+w>x+cw-8:
                    cx=x+13;cy+=17
                    if cy>y+ch-18:break
                if cy>y+24 and cx+w>x+cw-42 and shown<len(items)-1:break
                p.append(f'<rect x="{cx:.1f}" y="{cy}" width="{w:.1f}" height="14" rx="2.5" fill="#fff" stroke="{SEV_COLORS[it["severity"]]}" stroke-width="1"/>')
                p.append(f'<a href="#{_e(it["anchor"])}">{_t(cx+w/2,cy+10.3,it["number"],8.6,text,"middle","700")}</a>')
                cx+=w+4;shown+=1
            if shown<len(items):p.append(_t(cx+2,cy+10.3,f"+{len(items)-shown} more",8.2,SEV_INK[risk],"start","700"))
    for ci,im in enumerate(levels):p.append(_t(x0+ci*cw+cw/2,y0+3*ch+16,rx.LEVEL_LABELS[im],10.5,text,"middle","700"))
    p.append(f'<text x="{x0+1.5*cw:.1f}" y="{y0+3*ch+34}" font-size="8" fill="{muted}" font-weight="700" text-anchor="middle" letter-spacing="1.2">IMPACT</text>')
    p.append("</svg>")
    return "".join(p)
