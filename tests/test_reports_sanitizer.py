import re,unittest
from Cores.Services import reports_service as reports
san=reports.sanitize_html
XSS=(
    '<script>alert(1)</script>',
    '<SCRIPT SRC=//evil/x.js></SCRIPT>',
    '<scr<script>ipt>alert(1)</scr</script>ipt>',
    '<img src=x onerror=alert(1)>',
    '<img src="rptasset:abcdef123456" onerror="alert(1)" onload=alert(2)>',
    '<img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+">',
    '<img src="javascript:alert(1)">',
    '<a href="javascript:alert(1)">x</a>',
    '<a href=" JaVaScRiPt:alert(1)">x</a>',
    '<a href="java\tscript:alert(1)">x</a>',
    '<a href="&#106;avascript:alert(1)">x</a>',
    '<a href="data:text/html,<script>alert(1)</script>">x</a>',
    '<a href="vbscript:msgbox(1)">x</a>',
    '<a href="https://ok.example" onclick="alert(1)" style="x:expression(alert(1))">x</a>',
    '<p style="background:url(javascript:alert(1))">x</p>',
    '<style>*{background:url("javascript:alert(1)")}</style>',
    '<svg onload=alert(1)><circle/></svg>',
    '<svg><script>alert(1)</script></svg>',
    '<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>',
    '<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>',
    '<iframe src="javascript:alert(1)"></iframe>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<object data="javascript:alert(1)"></object><embed src="javascript:alert(1)">',
    '<form action="javascript:alert(1)"><input type=submit formaction="javascript:alert(2)"></form>',
    '<body onload=alert(1)>',
    '<details open ontoggle=alert(1)>x</details>',
    '<video><source onerror="alert(1)"></video>',
    '<audio src=x onerror=alert(1)>',
    '<input autofocus onfocus=alert(1)>',
    '<marquee onstart=alert(1)>x</marquee>',
    '<base href="javascript:alert(1)//">',
    '<link rel=stylesheet href="javascript:alert(1)">',
    '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">',
    '<p><b><i>nested<script>alert(1)</script><img src=x onerror=alert(1)></i></b></p>',
    '<table><tr><td onmouseover="alert(1)" background="javascript:alert(1)">x</td></tr></table>',
    '<div><p>x</p><iframe><p>y</p>',
    '<img src=x onerror=alert(1)',
    '<a href="https://x" <script>alert(1)</script>>y</a>',
    '<<script>alert(1);//<</script>',
    '<p title="</p><script>alert(1)</script>">x</p>',
    '<span class="rpt-redact" onmouseover=alert(1)>x</span>',
    '<figure class="rpt-ev" data-evidence=\'"><script>alert(1)</script>\'>x</figure>',
    '<noscript><p title="</noscript><img src=x onerror=alert(1)>"></noscript>',
    '<textarea></textarea><img src=x onerror=alert(1)>',
    '<!--<script>alert(1)</script>-->',
    '<![CDATA[<script>alert(1)</script>]]>',
    '<?xml version="1.0"?><x onclick=alert(1)>y</x>',
    '\x00<scri\x00pt>alert(1)</script>',
)
_TAG_RX=re.compile(r"<(/?)([a-zA-Z0-9]+)((?:\s+[a-z-]+=\"[^\"<>]*\")*)>")
_ATTR_RX=re.compile(r'\s+([a-z-]+)="([^"<>]*)"')
_ALIGN={"data-align"}
ALLOWED_ATTRS={"a":{"href"},"td":{"colspan","rowspan","data-width"}|_ALIGN,"th":{"colspan","rowspan","data-width"}|_ALIGN,"img":{"src","alt","data-width"},"figure":{"class","data-evidence","data-kind","data-asset","data-shapes","data-type","data-cat","data-sub","data-tags"},"span":{"class","data-finding","data-token","data-color","data-bg","data-size"},"pre":{"data-lang"},
    "div":{"class","data-callout","data-sev","data-cvss","data-widget"},"p":_ALIGN,"blockquote":_ALIGN,"h3":{"data-collapsed"}|_ALIGN,"h4":{"data-collapsed"}|_ALIGN,"li":{"data-checked"}|_ALIGN,"ul":{"class"},"ol":{"start"},"table":{"class"}}
ALLOWED_CLASSES={"rpt-ev","rpt-redact","rpt-cmd","rpt-widget","rpt-fref","rpt-ph","note-callout","note-finding","note-secret","note-ts","note-checklist","note-table","note-table-head","note-align-center","note-align-right","note-embed","note-embed-inline","note-embed-float-left","note-embed-float-right","note-sketch"}
class SanitizerTests(unittest.TestCase):
    def assert_subset(self,out,src=""):
        """Every tag in the output is in the subset, carries only its allowed attributes, and nothing is left that is not text."""
        rest=_TAG_RX.sub("",out)
        self.assertNotIn("<",rest,f"stray markup in {out!r} (from {src!r})")
        for close,tag,attrs in _TAG_RX.findall(out):
            self.assertIn(tag,reports._ALLOWED,f"{tag} in {out!r} (from {src!r})")
            for name,value in _ATTR_RX.findall(attrs):
                self.assertFalse(close)
                self.assertIn(name,ALLOWED_ATTRS.get(tag,set()),f"{name} on {tag} (from {src!r})")
                self.assertFalse(name.startswith("on"))
                if name=="href":self.assertRegex(value,r"^(https?://|mailto:)")
                if name=="src":self.assertRegex(value,r"^rptasset:[A-Za-z0-9_-]+$")
                if name=="class":
                    for token in value.split(" "):self.assertIn(token,ALLOWED_CLASSES,f"class {token} (from {src!r})")
                if name.startswith("data-") or name=="start":self.assertRegex(value,r"^[A-Za-z0-9 ._+#/(),%-]*$",f"{name} (from {src!r})")
                if name=="data-lang":self.assertRegex(value,r"^[A-Za-z0-9_+#.-]{1,32}$")
    def test_xss_payloads_are_neutralised(self):
        for payload in XSS:
            out=san(payload)
            self.assert_subset(out,payload)
            low=out.lower()
            self.assertNotIn("<script",low,payload)
            self.assertNotRegex(low,r"<[^>]*\son\w+\s*=",payload)
            self.assertNotRegex(low,r"<[^>]*javascript:",payload)
            self.assertNotRegex(low,r"<[^>]*style\s*=",payload)
            self.assertNotIn("<svg",low);self.assertNotIn("<iframe",low)
            self.assertEqual(out,san(out),f"not idempotent for {payload!r}")
    def test_script_and_style_content_is_dropped_not_shown(self):
        self.assertEqual("ab",san("a<script>alert(1)</script>b"))
        self.assertEqual("ab",san("a<style>p{color:red}</style>b"))
        self.assertEqual("ab",san("a<svg><text>t</text></svg>b"))
        self.assertEqual("ab",san("a<iframe>inner</iframe>b"))
        self.assertEqual("ab",san("a<form><input value=x>inner</form>b"))
        self.assertEqual("ab",san("a<object><p>inner</p></object>b"))
        self.assertEqual("a",san("a<script>never closed <p>x</p>"))
    def test_allowed_subset_survives_a_round_trip(self):
        doc=('<h3>Title</h3><h4>Sub</h4><p>Text <strong>s</strong> <b>b</b> <em>e</em> <i>i</i> <u>u</u> <s>s</s> <code>c</code><br>line</p>'
            '<pre>  $ nmap -sV 10.0.0.5\n\tPORT   STATE</pre><blockquote>q</blockquote><ul><li>one</li><li>two</li></ul><ol><li>1</li></ol>'
            '<p><a href="https://example.com/a?b=1&amp;c=2">link</a> <a href="http://example.com">h</a> <a href="mailto:sec@example.com">m</a></p>'
            '<table><thead><tr><th colspan="2">H</th></tr></thead><tbody><tr><td rowspan="3">a</td><td>b</td></tr></tbody></table><hr>'
            '<img src="rptasset:0123456789abcdef0123456789abcdef" alt="Screen &quot;1&quot;" data-width="60%">'
            '<figure class="rpt-ev" data-evidence="0123456789abcdef0123456789abcdef"><figcaption>$ id — exit 0</figcaption><pre>uid=0(root)</pre></figure>'
            '<p>Password: <span class="rpt-redact">hunter2</span></p>'
            '<pre data-lang="bash">ls -la</pre><pre data-lang="C++">x</pre><pre data-lang="objective-c_2.0#">y</pre>')
        self.assertEqual(doc,san(doc))
        self.assert_subset(san(doc))
    def test_unknown_tags_are_unwrapped(self):
        self.assertEqual("ab<p>c</p>",san("<div>a<font color=red>b</font><p>c</p></div>"))
        self.assertEqual("Big",san("<h1>Big</h1>"))
        self.assertEqual("plain",san('<span class="other" style="color:red">plain</span>'))
        self.assertEqual("x",san('<a>x</a>'))
        self.assertEqual("x",san('<a href="/relative">x</a>'))
        self.assertEqual("x",san('<a href="ftp://h/x">x</a>'))
    def test_attributes_are_filtered(self):
        self.assertEqual('<a href="https://x.y/">t</a>',san('<a HREF="https://x.y/" target="_blank" rel="x" id="i" class="c" title="t">t</a>'))
        self.assertEqual("<td>a</td>",san('<td colspan="abc" rowspan="-2" width="5">a</td>'))
        self.assertEqual('<td colspan="2">a</td>',san('<td colspan=2 rowspan=1>a</td>'))
        self.assertEqual("<figure>x</figure>",san('<figure class="evil" data-evidence="has space">x</figure>'))
        self.assertEqual('<img src="rptasset:abcdef123456" alt="">',san('<img src="rptasset:abcdef123456" data-width="100; x" width="5">'))
        self.assertEqual("<p>x</p>",san('<p class="a" id="b" data-x="1" style="color:red" dir="rtl">x</p>'))
    def test_code_block_language(self):
        for src,want in (
            ('<pre data-lang="bash" class="note-code" onclick="x" style="y">a</pre>','<pre data-lang="bash">a</pre>'),
            ("<pre data-lang=' http '>a</pre>",'<pre data-lang="http">a</pre>'),
            ('<pre data-lang="&#98;ash">a</pre>','<pre data-lang="bash">a</pre>'),
            ('<pre data-lang="">a</pre>',"<pre>a</pre>"),
            ('<pre data-lang="two words">a</pre>',"<pre>a</pre>"),
            ('<pre data-lang="a&quot;onmouseover=alert(1)">a</pre>',"<pre>a</pre>"),
            ('<pre data-lang="x><script>alert(1)</script>">a</pre>',"<pre>a</pre>"),
            ('<pre data-lang="bash\n">a</pre>','<pre data-lang="bash">a</pre>'),
            ('<pre data-lang="'+"a"*33+'">a</pre>',"<pre>a</pre>"),
            ('<pre data-lang="'+"a"*32+'">a</pre>','<pre data-lang="'+"a"*32+'">a</pre>'),
            ("<pre DATA-LANG=json>{}</pre>",'<pre data-lang="json">{}</pre>'),
            ('<p data-lang="bash">a</p><code data-lang="bash">b</code>',"<p>a</p><code>b</code>"),
        ):
            out=san(src)
            self.assertEqual(want,out,src);self.assert_subset(out,src);self.assertEqual(out,san(out))
    def test_images_must_be_assets(self):
        for src in ("https://evil/x.png","http://x/y.gif","file:///etc/passwd","//evil/x.png","x.png","rptasset:","rptasset:../../x","rptasset:abc def","data:image/png;base64,AAAA","cmdcard:abc"):
            self.assertEqual("",san(f'<img src="{src}" alt="a">'),src)
    def test_text_is_escaped(self):
        self.assertEqual("a &lt; b &amp;&amp; c &gt; d",san("a < b && c > d"))
        self.assertEqual("&lt;script&gt;",san("&lt;script&gt;"))
        self.assertEqual("&lt;script&gt;alert(1)&lt;/script&gt;",san("&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;".replace("&amp;","&")))
        self.assertEqual("x &amp; y é —",san("x &amp; y &eacute; &mdash;"))
    def test_malformed_markup_is_closed(self):
        self.assertEqual("<p>a <b>b</b></p>",san("<p>a <b>b"))
        self.assertEqual("<p><b>a</b></p>c",san("<p><b>a</p></b>c"))
        self.assertEqual("ab",san("a</p></div></b>b"))
        self.assertEqual("<ul><li>a</li><li>b</li></ul>",san("<ul><li>a</li><li>b"))
        self.assertEqual("",san(None));self.assertEqual("",san(""));self.assertEqual("12",san(12))
    def test_deep_nesting_and_size_are_bounded(self):
        out=san("<b>"*5000+"x"+"</b>"*5000)
        self.assertLessEqual(out.count("<b>"),reports._MAX_DEPTH)
        self.assertEqual(out.count("<b>"),out.count("</b>"))
        big=san("<p>"+"a"*(reports.RICH_MAX+50000)+"</p>")
        self.assertLessEqual(len(big),reports.RICH_MAX+4096)
    def test_note_mode_code_blocks(self):
        out=reports._sanitize('<pre class="note-code" data-lang="bash">a<br>b<span class="tok">c</span></pre><p>x<br>y</p><input type="checkbox" checked>on <input type="checkbox">off',note_mode=True)
        self.assertEqual('<pre data-lang="bash">a\nbc</pre><p>x<br>y</p>\u2611 on \u2610 off',out)
        self.assert_subset(out)
        self.assertEqual("<pre>a<br>b</pre>",san("<pre>a<br>b</pre>"))
    # ---- subset v2: the Notes editor's structures
    def test_v2_structures_survive_a_round_trip(self):
        for markup in (
            '<div class="note-callout" data-callout="finding" data-sev="high" data-cvss="8.1"><h3 data-collapsed="1">T</h3><p data-align="center">x</p></div>',
            '<div class="note-callout note-finding" data-callout="vuln" data-sev="low"><p>x</p></div>',
            '<div class="note-callout" data-callout="credential"><p><b>Secret: </b><span class="note-secret">P@ss</span></p></div>',
            '<ul class="note-checklist"><li data-checked="1">done</li><li>open</li></ul><ol start="5"><li>x</li></ol>',
            '<table class="note-table note-table-head note-align-center"><tbody><tr><th data-width="120">k</th><td data-align="right">v</td></tr></tbody></table>',
            '<figure class="note-embed note-embed-float-left note-sketch" data-kind="sketch" data-asset="abcdef123456" data-shapes="eyJ2IjoxfQ-_"><img src="rptasset:abcdef123456" alt="Drawing" data-width="420px"></figure>',
            '<figure class="rpt-cmd" data-type="Linux Shell" data-cat="Recon" data-sub="Ports (TCP)" data-tags="nmap, scan"><figcaption>Full scan</figcaption><p>All ports</p><pre>nmap -p- 10.0.0.5</pre></figure>',
            '<p><span class="note-ts">[2026-11-23 10:12]</span> <span class="rpt-fref" data-finding="ab12cd">F-03 SQL injection</span> <span class="rpt-ph" data-token="client">{{client}}</span></p>',
            '<p><span data-color="#ff0000" data-bg="#fff3bf" data-size="18">x</span></p>',
            '<div class="rpt-widget" data-widget="risk_matrix"></div><div class="rpt-widget" data-widget="commands_run"></div>'):
            self.assertEqual(markup,san(markup));self.assert_subset(san(markup),markup)
    def test_v2_values_are_validated(self):
        self.assertEqual('<div class="note-callout" data-callout="info"><p>x</p></div>',san('<div class="note-callout evil" data-callout="x" data-sev="high" data-cvss="9" style="position:fixed" onclick="a()"><p>x</p></div>'))
        self.assertEqual('<div class="note-callout" data-callout="vuln" data-cvss="10.0">x</div>',san('<div class="note-callout" data-callout="Vulnerability" data-sev="extreme" data-cvss="10">x</div>'))
        self.assertEqual('<div class="note-callout" data-callout="finding">x</div>',san('<div class="note-callout" data-callout="finding" data-cvss="11">x</div>'))
        self.assertEqual("plain",san('<div class="app-modal-backdrop">plain</div>'))
        self.assertEqual('<span data-color="#ff0000">a</span>b',san('<span data-color="#FF0000" data-bg="url(x)" data-size="999">a</span><span data-color="red" style="color:red">b</span>'))
        self.assertEqual('<span class="rpt-fref">a</span><span class="rpt-ph">b</span>',san('<span class="rpt-fref" data-finding="a b&quot;x">a</span><span class="rpt-ph" data-token="Client;">b</span>'))
        self.assertEqual('<span class="note-secret">s</span>',san('<span class="note-secret revealed notes-popover" data-x="1">s</span>'))
        self.assertEqual('<ul><li>a</li></ul><ol><li>b</li></ol><table><tr><td>c</td></tr></table>',san('<ul class="x"><li data-checked="0" data-align="left">a</li></ul><ol start="0"><li>b</li></ol><table class="evil"><tr><td data-width="5" data-align="top">c</td></tr></table>'))
        self.assertEqual('<figure class="note-embed"><img src="rptasset:abcdef123456" alt=""></figure>',san('<figure class="note-embed app-x" data-kind="file" data-asset="../x" data-shapes="a b" contenteditable="false" draggable="true"><img src="rptasset:abcdef123456" style="width:9px"></figure>'))
        self.assertEqual('<figure class="rpt-cmd"><pre>x</pre></figure>',san('<figure class="rpt-cmd" data-type="&lt;img&gt;" data-cat="a&quot;b" data-tags="x&#10;y"><pre>x</pre></figure>'))
    def test_v2_widget_markers_are_empty_and_known(self):
        self.assertEqual('<div class="rpt-widget" data-widget="findings_table"></div>after',san('<div class="rpt-widget" data-widget="findings_table"><p>x</p><div>y</div><script>alert(1)</script></div>after'))
        self.assertEqual("after",san('<div class="rpt-widget" data-widget="evil"><p>x</p></div>after'))
    def test_v2_unemitted_tags_do_not_close_their_parent(self):
        self.assertEqual('<span class="note-secret">abc</span>',san('<span class="note-secret">a<span>b</span>c</span>'))
        self.assertEqual('<div class="note-callout" data-callout="info">a<p>b</p></div>',san('<div class="note-callout"><div>a</div><p>b</p></div>'))
    def test_v2_xss_in_new_attributes(self):
        for payload in ('<div class="note-callout" data-callout="finding&quot; onmouseover=&quot;alert(1)">x</div>','<span class="rpt-ph" data-token="x&quot;><script>alert(1)</script>">y</span>','<figure class="note-embed" data-shapes="&quot;><img src=x onerror=alert(1)>">z</figure>','<span data-color="#fff&quot; style=&quot;background:url(javascript:alert(1))">c</span>','<td data-width="100&quot; onclick=&quot;x">d</td>','<div class="rpt-widget" data-widget="risk_matrix&quot;><svg onload=alert(1)>"></div>','<ul class="note-checklist&quot; onfocus=&quot;x"><li data-checked="1&quot; onclick=&quot;x">e</li></ul>'):
            out=san(payload);self.assert_subset(out,payload)
            self.assertNotRegex(out.lower(),r"<[^>]*\s(on\w+|style)\s*=",payload);self.assertNotIn("<script",out.lower());self.assertNotIn("<svg",out.lower())
    def test_note_mode_keeps_structure(self):
        out=reports._sanitize('<div>line1</div><div>line2</div><h1>H</h1><h6>h</h6><div class="note-callout" data-callout="finding"><h3>x</h3><p>y</p></div><ul class="note-checklist"><li data-checked="true">done</li><li data-checked="false">todo</li></ul><span class="note-secret">pw</span><img src="https://x/y.png" alt="shot">',note_mode=True)
        self.assertEqual('line1<br>line2<br><h3>H</h3><h4>h</h4><div class="note-callout" data-callout="finding"><h3>x</h3><p>y</p></div><ul class="note-checklist"><li data-checked="1">done</li><li>todo</li></ul><span class="rpt-redact">pw</span>[Image: shot]',out)
        self.assert_subset(out)
if __name__=="__main__":unittest.main()
