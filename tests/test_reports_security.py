import io,os,tempfile,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores.Services import reports_service as reports
from Cores.Services import report_export as rx
class PdfImageSourceTests(unittest.TestCase):
    """H-07 (GHSA-rw7v-4hrq-x6r9): fpdf2 must only ever be handed image bytes LOYA resolved itself, never a URL or path from report HTML."""
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.env=mock.patch.dict(os.environ,{"LOYA_REPORT_PDF_ENGINE":"fallback"});self.env.start()
    def tearDown(self):
        self.env.stop();self.iso.stop()
    def test_urls_and_paths_in_report_html_never_reach_fpdf_image(self):
        png=("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
        asset=reports.asset_add("dot.png",png)
        hostile=('<p>x</p><img src="http://127.0.0.1:9/evil.png"><img src="https://example.invalid/a.png"><img src="/etc/passwd">'
                 '<img src="file:///etc/passwd"><img src="C:\\Windows\\win.ini"><img src="..\\..\\secret.png">'
                 f'<img src="rptasset:{asset["uid"]}"><figure class="note-embed"><img src="//evil.invalid/x.png"></figure>')
        rep=reports.create_report({"title":"H07","template_id":"blank"})
        reports.add_section(rep["id"],{"kind":"custom","title":"S","content":hostile})
        reports.add_finding(rep["id"],{"title":"F","severity":"high","description":hostile,"steps":hostile})
        seen=[]
        from fpdf import FPDF
        real=FPDF.image
        def spy(self_,name=None,*a,**k):
            seen.append(name);return real(self_,name,*a,**k)
        out=os.path.join(tempfile.mkdtemp(dir=self.iso.dir),"r.pdf")
        with mock.patch.object(FPDF,"image",spy),mock.patch("urllib.request.urlopen",side_effect=AssertionError("network access")):
            rx.render(reports.get_report(rep["id"]),"pdf",out,{})
        self.assertTrue(os.path.getsize(out)>500)
        self.assertTrue(seen,"the report asset should have been embedded")
        for name in seen:self.assertIsInstance(name,io.BytesIO,repr(name))
    def test_stored_html_keeps_only_asset_images(self):
        clean=reports.sanitize_html('<img src="http://e/x.png"><img src="/etc/passwd"><img src="file:///x"><img src="rptasset:abc123">')
        self.assertNotIn("http://",clean);self.assertNotIn("passwd",clean);self.assertNotIn("file:",clean)
if __name__=="__main__":unittest.main()
