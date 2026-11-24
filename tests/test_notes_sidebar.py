import os,sys,json,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import notes_service as ns
from Cores.Bridge import api
FINDING='<h2>Web</h2><div class="note-callout note-finding" data-callout="finding" data-sev="medium"><h3>XSS</h3></div><div class="note-callout" data-callout="vuln" data-sev="critical" data-cvss="9.8"><p>RCE on portal.acme.example</p></div><div class="note-callout" data-callout="warning"><p>scope</p></div>'
class NotesSidebarTest(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        ns._SB_META_CACHE.clear();ns._SB_TEXT_CACHE.clear()
        self._stubs=[(api._semantic_svc,"index_note",api._semantic_svc.index_note),(api._semantic_svc,"remove_note",api._semantic_svc.remove_note),(api._targets_svc,"auto_add_target_values",api._targets_svc.auto_add_target_values)]
        for mod,name,_ in self._stubs:setattr(mod,name,lambda *a,**k:0)
        self.api=api.NotesAPI()
        self.targets=[]
        self.api._sidebar_targets=lambda:self.targets
    def tearDown(self):
        for mod,name,fn in self._stubs:setattr(mod,name,fn)
        ns._abs=self._abs
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        ns._SB_META_CACHE.clear();ns._SB_TEXT_CACHE.clear()
        self.iso.stop()
    def _note(self,name,group="",html="<p>body</p>",tags="",cmds=None):
        # Command cards reach save() the way the editor sends them: a marker span per card plus the card data keyed by cid.
        cmds=[dict(c,cid="c%d"%i) for i,c in enumerate(cmds or [])]
        html+="".join('<span class="cmd-card-marker" data-cid="%s"></span>'%c["cid"] for c in cmds)
        return self.api.save(None,name,group,html,cmds,tags)["id"]
    def _settings(self):
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as f:return json.load(f)
    # ---- preferences
    def test_prefs_defaults(self):
        p=self.api.sidebar_prefs()
        self.assertEqual((p["view"],p["sort"],p["dir"],p["density"],p["width"],p["filters"],p["scopes"],p["nested"],p["show_recent"],p["group_styles"]),("groups","name","asc","comfortable",280,[],["name","tags"],True,True,{}))
        self.assertEqual((p["width_min"],p["width_max"]),(220,560))
    def test_prefs_are_validated_and_stored_in_settings_json(self):
        s=self.api.set_sidebar_pref
        self.assertEqual(s("view","Tags")["view"],"tags")
        self.assertEqual(s("view","<script>")["view"],"groups")
        self.assertEqual(s("sort","created")["sort"],"created")
        self.assertEqual(s("dir","desc")["dir"],"desc")
        self.assertEqual(s("density","compact")["density"],"compact")
        self.assertEqual(s("width",9999)["width"],560)
        self.assertEqual(s("width","abc")["width"],280)
        self.assertEqual(s("width",10)["width"],220)
        self.assertEqual(s("filters",["untagged","evil","pinned"])["filters"],["pinned","untagged"])
        self.assertEqual(s("filters","pinned")["filters"],[])
        self.assertEqual(s("scopes",["content"])["scopes"],["content"])
        self.assertEqual(s("scopes",[])["scopes"],["name"])
        self.assertIs(s("nested",False)["nested"],False)
        self.assertIs(s("show_recent","yes")["show_recent"],False)
        with self.assertRaises(ValueError):s("group_styles",{})
        with self.assertRaises(ValueError):s("nope",1)
        with self.assertRaises(ValueError):s(None,1)
        self.assertEqual(s("view",7)["view"],"groups")
        self.assertEqual(s("filters",[1,None,"pinned"])["filters"],["pinned"])
        sb=self._settings()["note"]["sidebar"]
        self.assertEqual((sb["view"],sb["sort"],sb["density"],sb["width"],sb["nested"]),("groups","created","compact",220,False))
    def test_prefs_keep_other_note_settings(self):
        self.api.set_editor_pref("editor_outline",True)
        self.api.set_sidebar_pref("density","compact")
        self.api.set_editor_pref("draw_width",3)
        n=self._settings()["note"]
        self.assertEqual((n["editor_outline"],n["draw_width"],n["sidebar"]["density"]),(True,3,"compact"))
        self.assertIs(self.api.editor_prefs()["editor_outline"],True)
    def test_corrupt_sidebar_settings_fall_back(self):
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as f:json.dump({"note":{"sidebar":{"view":7,"width":"wide","filters":"x","scopes":None,"group_styles":["a"],"nested":"no"}}},f)
        ns._SETTINGS_CACHE=None
        p=self.api.sidebar_prefs()
        self.assertEqual((p["view"],p["width"],p["filters"],p["scopes"],p["group_styles"],p["nested"]),("groups",280,[],["name"],{},True))
    # ---- group colour and icon
    def test_group_style_set_validate_clear(self):
        st=self.api.set_group_style("Web App","#F03E3E","target")
        self.assertEqual(st,{"web app":{"color":"#f03e3e","icon":"target"}})
        self.assertEqual(self.api.set_group_style("Recon",'red" onx="1',"<i>"),st)
        self.assertEqual(self.api.set_group_style("Recon","","star")["recon"],{"color":"","icon":"star"})
        self.assertEqual(self.api.set_group_style("","#000000","")["__ungrouped__"],{"color":"#000000","icon":""})
        self.assertNotIn("web app",self.api.set_group_style("WEB APP","",""))
    def test_group_style_follows_rename_and_delete(self):
        self._note("A","Old")
        self.api.set_group_style("Old","#37b24d","star")
        self.api.rename_group("Old","New Name")
        st=self.api.sidebar_prefs()["group_styles"]
        self.assertEqual(st,{"new name":{"color":"#37b24d","icon":"star"}})
        self.api.create_group("Spare");self.api.set_group_style("Spare","#1c7ed6","")
        self.assertTrue(self.api.delete_group("Spare"))
        self.assertNotIn("spare",self.api.sidebar_prefs()["group_styles"])
    # ---- per-note facts
    def test_note_meta(self):
        m=ns.note_sidebar_meta(FINDING+'<img src="cmdcard:abc" /><a href="cmd:edit:x"><img src="cmdcard:def" width="320" /></a>')
        self.assertEqual(m,{"cmds":2,"callouts":3,"findings":2,"sev":"critical"})
        self.assertEqual(ns.note_sidebar_meta("<p>plain</p>"),{"cmds":0,"callouts":0,"findings":0,"sev":""})
        self.assertEqual(ns.note_sidebar_meta(None)["sev"],"")
        self.assertEqual(ns.note_sidebar_meta('<div data-callout="finding" data-sev="LOW"></div><div data-sev="bogus"></div>')["sev"],"low")
    def test_epoch(self):
        self.assertEqual(ns.note_epoch_ms("2026-11-23T10:00:00+00:00"),1795428000000)
        self.assertEqual(ns.note_epoch_ms("2026-11-23T10:00:00Z"),1795428000000)
        self.assertGreater(ns.note_epoch_ms("2026-11-23 10:00:00"),0)
        self.assertEqual((ns.note_epoch_ms(""),ns.note_epoch_ms("garbage"),ns.note_epoch_ms(None)),(0,0,0))
    # ---- the payload
    def test_sidebar_payload(self):
        a=self._note("Alpha","Recon",FINDING,"web, xss",cmds=[{"cmd_note_title":"scan","category":"Recon","sub_category":"","description":"","tags":"","command":"nmap -sV {IP}"}])
        b=self._note("Beta","","<p>hello</p>")
        self.api.create_group("Empty")
        self.api.set_pinned(b,"Beta",True);self.api.set_pinned(a,"Alpha",True)
        self.api.set_group_collapsed("Recon",True);self.api.set_group_collapsed("",True)
        d=self.api.sidebar()
        self.assertEqual(set(d),{"notes","groups","collapsed","pinned","recent","targets","prefs","now"})
        rows={n["id"]:n for n in d["notes"]}
        self.assertEqual((rows[a]["note_name"],rows[a]["group_name"],rows[a]["tags"],rows[a]["pinned"],rows[a]["sev"],rows[a]["findings"],rows[a]["cmds"]),("Alpha","Recon","web, xss",True,"critical",2,1))
        self.assertEqual((rows[b]["sev"],rows[b]["cmds"],rows[b]["findings"]),("",0,0))
        self.assertTrue(rows[a]["updated_ts"]>0 and rows[a]["created_ts"]>0 and abs(d["now"]-rows[a]["updated_ts"])<60000)
        self.assertNotIn("content",rows[a]);self.assertNotIn("preview",rows[a])
        self.assertEqual(d["pinned"],[b,a])
        self.assertIn("Empty",d["groups"])
        self.assertEqual(sorted(d["collapsed"]),["__ungrouped__","recon"])
        self.assertEqual(d["prefs"]["view"],"groups")
        json.dumps(d)
    def test_sidebar_matches_list_and_cache_follows_edits(self):
        a=self._note("Alpha","G","<p>one</p>")
        self.assertEqual(sorted(n["id"] for n in self.api.sidebar()["notes"]),sorted(n["id"] for n in self.api.list()))
        self.assertEqual(self.api.sidebar()["notes"][0]["sev"],"")
        self.api.save(a,"Alpha","G",FINDING,[],"")
        self.assertEqual(self.api.sidebar()["notes"][0]["sev"],"critical")
        self.api.delete(a)
        self.assertEqual(self.api.sidebar()["notes"],[])
        self.assertEqual((ns._SB_META_CACHE,ns._SB_TEXT_CACHE),({},{}))
    # ---- pinned order and recents
    def test_reorder_pinned(self):
        ids=[self._note(n) for n in ("A","B","C","D")]
        for i,n in zip(ids[:3],"ABC"):self.api.set_pinned(i,n,True)
        self.assertEqual(self.api.reorder_pinned([ids[2],ids[0],ids[1]]),[ids[2],ids[0],ids[1]])
        self.assertEqual(self.api.sidebar()["pinned"],[ids[2],ids[0],ids[1]])
        # Unknown, unpinned and repeated ids are ignored; pinned notes left out keep their place after the listed ones.
        self.assertEqual(self.api.reorder_pinned([ids[1],ids[3],999,"x",ids[1]]),[ids[1],ids[2],ids[0]])
        self.assertEqual(self.api.reorder_pinned("nope"),[ids[1],ids[2],ids[0]])
        self.assertEqual([g["notes"] for g in self.api.groups() if g["group_name"]=="__pinned__"][0],[{"id":ids[1]},{"id":ids[2]},{"id":ids[0]}])
    def test_recent(self):
        ids=[self._note("N%d"%i) for i in range(15)]
        for i in ids:self.api.touch_recent(i)
        self.assertEqual(self.api.touch_recent(ids[3],"N3")[:2],[ids[3],ids[14]])
        r=self.api.sidebar()["recent"]
        self.assertEqual((len(r),r[0],len(set(r))),(12,ids[3],12))
        self.api.delete(ids[3])
        self.assertNotIn(ids[3],self.api.sidebar()["recent"])
        # Pins and groups survive a recent write.
        self.api.set_pinned(ids[5],"N5",True);self.api.create_group("Keep");self.api.touch_recent(ids[6])
        d=self.api.sidebar()
        self.assertEqual((d["pinned"],"Keep" in d["groups"]),([ids[5]],True))
    def test_set_groups_collapsed(self):
        self.assertEqual(sorted(self.api.set_groups_collapsed(["Recon","","CTF/HTB","__pinned__"],True)),["__pinned__","__ungrouped__","ctf/htb","recon"])
        self.assertEqual(sorted(self.api.set_groups_collapsed(["RECON","__ungrouped__"],False)),["__pinned__","ctf/htb"])
        self.assertEqual(sorted(self.api.set_groups_collapsed(["ctf/htb"],True)),["__pinned__","ctf/htb"])
        self.assertEqual(self.api.set_groups_collapsed("x",False),self.api.sidebar()["collapsed"])
    # ---- targets view
    def test_target_terms_skip_weak_values(self):
        t=ns.target_terms([{"name":"web01","values":{"IPv4":"10.10.20.15","Port":"443","Wordlist":"/usr/share/wordlists/x.txt","Domain":"Acme.Example","Win":"C:\\Tools","Short":"ab"}},{"name":""},"junk",{"name":"dc01","values":None}])
        self.assertEqual(t,[{"name":"web01","terms":["web01","10.10.20.15","acme.example"]},{"name":"dc01","terms":["dc01"]}])
        self.assertEqual(ns.target_terms(None),[])
    def test_notes_are_matched_to_targets(self):
        a=self._note("Portal login","Web","<p>tested https://portal.acme.example/login</p>")
        b=self._note("DC01 enumeration","AD","<p>ldap</p>")
        c=self._note("Unrelated","","<p>nothing</p>")
        self.targets=[{"name":"web01","values":{"Domain":"acme.example","Port":"443"}},{"name":"dc01","values":{}}]
        d=self.api.sidebar()
        rows={n["id"]:n["targets"] for n in d["notes"]}
        self.assertEqual((d["targets"],rows[a],rows[b],rows[c]),(["web01","dc01"],["web01"],["dc01"],[]))
        # Changing the targets re-evaluates the cached matches.
        self.targets=[{"name":"other","values":{"Host":"nothing"}}]
        self.assertEqual({n["id"]:n["targets"] for n in self.api.sidebar()["notes"]}[c],["other"])
        self.targets=[]
        self.assertNotIn("targets",self.api.sidebar()["notes"][0])
    def test_sidebar_targets_reads_without_error_when_there_is_no_profile(self):
        self.assertIsInstance(api.NotesAPI()._sidebar_targets(),list)
    # ---- content search
    def test_search_content(self):
        a=self._note("Alpha","","<h2>Scope</h2><p>The <b>Kerberos</b> ticket for svc_sql was cracked offline with hashcat.</p>")
        b=self._note("Beta","","<p>nothing here</p>",cmds=[{"cmd_note_title":"Roast","category":"AD","sub_category":"","description":"","tags":"","command":"GetUserSPNs.py corp/user -request"}])
        hit=self.api.search_content("kerberos")
        self.assertEqual([h["id"] for h in hit],[a])
        self.assertIn("Kerberos ticket",hit[0]["snippet"])
        self.assertNotIn("<",hit[0]["snippet"])
        self.assertEqual([h["id"] for h in self.api.search_content("HASHCAT svc_sql")],[a])
        self.assertEqual(self.api.search_content("kerberos missing"),[])
        # Command cards are searchable although their text lives in a base64 token.
        self.assertEqual([h["id"] for h in self.api.search_content("getuserspns")],[b])
        self.assertEqual([h["id"] for h in self.api.search_content("roast")],[b])
        # Markup and attributes are not content.
        self.assertEqual(self.api.search_content("cmdcard"),[])
        self.assertEqual(self.api.search_content("h2"),[])
        self.assertEqual((self.api.search_content(""),self.api.search_content("a"),self.api.search_content(None)),([],[],[]))
        self.assertEqual(len(self.api.search_content("e",1)),0)
        self.assertEqual(len(self.api.search_content("he",1)),1)
        self.assertEqual(len(self.api.search_content("he","junk")),2)
    def test_search_content_sees_edits(self):
        a=self._note("Alpha","","<p>first text</p>")
        self.assertEqual(len(self.api.search_content("first")),1)
        self.api.save(a,"Alpha","","<p>second text</p>",[],"")
        self.assertEqual((len(self.api.search_content("first")),len(self.api.search_content("second"))),(0,1))
    def test_search_text_separates_blocks(self):
        t=ns.note_search_text("<h2>Title</h2><p>Body</p><ul><li>one</li><li>two</li></ul>")
        self.assertNotIn("TitleBody",t);self.assertNotIn("onetwo",t)
    # ---- no selection: a null id is a clean error, never a TypeError from int(None)
    def test_null_note_id_is_a_clean_error(self):
        a=self._note("Alpha")
        for bad in (None,"","  ","abc",True,[1]):
            for call in (lambda v:self.api.get(v),lambda v:self.api.edit_content(v),lambda v:self.api.delete(v),lambda v:self.api.append(v,"<p>x</p>"),lambda v:self.api.touch_recent(v),lambda v:self.api.move_note(v,"G")):
                with self.assertRaises(ValueError) as cm:call(bad)
                self.assertEqual(str(cm.exception),"No note selected.")
        self.assertEqual(self.api.get(str(a))["id"],a)
        self.assertEqual(self.api.edit_content(a)["id"] if "id" in self.api.edit_content(a) else a,a)
        with self.assertRaises(ValueError):self.api.get(99999)
        self.assertEqual(self.api.sidebar()["recent"],[])
if __name__=="__main__":unittest.main()
