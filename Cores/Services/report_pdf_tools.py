"""A small PDF reader/writer for the report pipeline (standard library only): read the PDFs the web engine prints, find the
position markers the report design left in them, and write one document from several with an overlay stamped on every page,
link annotations, bookmarks and document properties. It is not a general PDF library: encrypted files are refused."""
import re,zlib
class PdfError(Exception):pass
class Ref:
    __slots__=("num","gen")
    def __init__(self,num,gen=0):self.num=num;self.gen=gen
    def __eq__(self,o):return isinstance(o,Ref) and o.num==self.num and o.gen==self.gen
    def __hash__(self):return hash((self.num,self.gen))
    def __repr__(self):return f"Ref({self.num})"
class Name(str):
    __slots__=()
class Raw(bytes):
    """A string token kept exactly as written: (literal) or <hex>."""
    __slots__=()
class Stream:
    __slots__=("dict","data")
    def __init__(self,d,data):self.dict=d;self.data=data
_WS=b" \t\r\n\x0c\x00"
_DELIM=b"()<>[]{}/%"
_NUM_RX=re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
def _skip(b,i):
    n=len(b)
    while i<n:
        c=b[i]
        if c in _WS:i+=1
        elif c==0x25:
            while i<n and b[i] not in b"\r\n":i+=1
        else:break
    return i
def parse(b,i=0,depth=0):
    """One object starting at b[i] -> (value, next index)."""
    if depth>60:raise PdfError("nesting too deep")
    i=_skip(b,i)
    if i>=len(b):raise PdfError("unexpected end")
    c=b[i:i+1]
    if c==b"/":
        j=i+1
        while j<len(b) and b[j] not in _WS and b[j] not in _DELIM:j+=1
        return Name(b[i+1:j].decode("latin-1")),j
    if c==b"<":
        if b[i:i+2]==b"<<":
            d={};i+=2
            while True:
                i=_skip(b,i)
                if b[i:i+2]==b">>":return d,i+2
                k,i=parse(b,i,depth+1)
                if not isinstance(k,Name):raise PdfError("bad dictionary key")
                v,i=parse(b,i,depth+1);d[str(k)]=v
        j=b.index(b">",i)
        return Raw(b[i:j+1]),j+1
    if c==b"[":
        out=[];i+=1
        while True:
            i=_skip(b,i)
            if b[i:i+1]==b"]":return out,i+1
            v,i=parse(b,i,depth+1);out.append(v)
    if c==b"(":
        j=i+1;lvl=1
        while lvl:
            ch=b[j:j+1]
            if not ch:raise PdfError("unterminated string")
            if ch==b"\\":j+=2;continue
            if ch==b"(":lvl+=1
            elif ch==b")":lvl-=1
            j+=1
        return Raw(b[i:j]),j
    m=_NUM_RX.match(b,i)
    if m:
        tok=m.group(0);j=m.end()
        if tok.isdigit():
            # "12 0 R" is a reference, not three tokens.
            m2=re.compile(rb"[ \t\r\n\x0c\x00]+(\d+)[ \t\r\n\x0c\x00]+R(?![A-Za-z0-9])").match(b,j)
            if m2:return Ref(int(tok),int(m2.group(1))),m2.end()
            return int(tok),j
        return (float(tok) if b"." in tok else int(tok)),j
    for word,val in ((b"true",True),(b"false",False),(b"null",None)):
        if b.startswith(word,i):return val,i+len(word)
    raise PdfError("unexpected token at %d: %r"%(i,b[i:i+12]))
def _num(v):
    if isinstance(v,bool):return b"true" if v else b"false"
    if isinstance(v,int):return str(v).encode()
    s=("%.4f"%v).rstrip("0").rstrip(".")
    return (s if s not in ("","-","-0") else "0").encode()
def dump(v):
    if v is None:return b"null"
    if isinstance(v,Ref):return b"%d %d R"%(v.num,v.gen)
    if isinstance(v,Name):return b"/"+v.encode("latin-1")
    if isinstance(v,Raw):return bytes(v)
    if isinstance(v,(bool,int,float)):return _num(v)
    if isinstance(v,str):return text_string(v)
    if isinstance(v,(list,tuple)):return b"["+b" ".join(dump(x) for x in v)+b"]"
    if isinstance(v,dict):return b"<<"+b"".join(b"/"+k.encode("latin-1")+b" "+dump(x)+b"\n" for k,x in v.items())+b">>"
    raise PdfError("cannot write %r"%type(v))
def text_string(s):
    """A Python string as a PDF text string (UTF-16BE hex, readable by every viewer)."""
    return b"<"+("﻿"+s).encode("utf-16-be").hex().upper().encode()+b">"
def _unpredict(data,pred,cols):
    if pred<10:return data
    row=cols+1;out=bytearray();prev=bytearray(cols)
    for i in range(0,len(data)-row+1,row):
        f=data[i];cur=bytearray(data[i+1:i+row])
        if f==1:
            for j in range(1,cols):cur[j]=(cur[j]+cur[j-1])&255
        elif f==2:
            for j in range(cols):cur[j]=(cur[j]+prev[j])&255
        elif f==3:
            for j in range(cols):cur[j]=(cur[j]+(((cur[j-1] if j else 0)+prev[j])>>1))&255
        elif f==4:
            for j in range(cols):
                a=cur[j-1] if j else 0;bb=prev[j];c=prev[j-1] if j else 0;p=a+bb-c
                pa,pb,pc=abs(p-a),abs(p-bb),abs(p-c)
                cur[j]=(cur[j]+(a if pa<=pb and pa<=pc else bb if pb<=pc else c))&255
        out+=cur;prev=cur
    return bytes(out)
class Reader:
    def __init__(self,data):
        if not data.startswith(b"%PDF-"):raise PdfError("not a PDF file")
        self.b=data;self.offsets={};self.in_stream={};self.cache={};self.trailer={}
        try:self._xref()
        except Exception:self.offsets={};self.in_stream={};self.trailer={}
        if "Root" not in self.trailer:self._scan()
        if "Encrypt" in self.trailer:raise PdfError("encrypted PDF")
        if "Root" not in self.trailer:raise PdfError("no document catalog")
    def _xref(self):
        b=self.b;k=b.rfind(b"startxref")
        if k<0:raise PdfError("no startxref")
        pos=int(_NUM_RX.match(b,_skip(b,k+9)).group(0));seen=set()
        while pos is not None and pos not in seen:
            seen.add(pos);i=_skip(b,pos)
            if b.startswith(b"xref",i):
                i+=4
                while True:
                    i=_skip(b,i)
                    if b.startswith(b"trailer",i):break
                    m=re.compile(rb"(\d+)[ \t]+(\d+)").match(b,i)
                    if not m:raise PdfError("bad xref table")
                    start,count=int(m.group(1)),int(m.group(2));i=_skip(b,m.end())
                    for n in range(count):
                        ent=b[i:i+20];off=int(ent[0:10]);kind=ent[17:18]
                        if kind==b"n" and (start+n) not in self.offsets and (start+n) not in self.in_stream:self.offsets[start+n]=off
                        i+=20
                tr,_j=parse(b,i+7)
            else:
                m=re.compile(rb"(\d+)\s+(\d+)\s+obj").match(b,i)
                if not m:raise PdfError("bad xref offset")
                st=self._obj_at(i)
                if not isinstance(st,Stream):raise PdfError("bad xref stream")
                tr=st.dict;data=self.decode(st);w=tr["W"];index=tr.get("Index") or [0,tr["Size"]]
                rl=sum(w);p=0
                for a in range(0,len(index),2):
                    for n in range(index[a],index[a]+index[a+1]):
                        f=[int.from_bytes(data[p+sum(w[:x]):p+sum(w[:x+1])],"big") if w[x] else (1 if x==0 else 0) for x in range(3)];p+=rl
                        if n in self.offsets or n in self.in_stream:continue
                        if f[0]==1:self.offsets[n]=f[1]
                        elif f[0]==2:self.in_stream[n]=(f[1],f[2])
            for key,val in tr.items():self.trailer.setdefault(key,val)
            pos=tr.get("Prev") if isinstance(tr.get("Prev"),int) else None
    def _scan(self):
        """No usable cross-reference: index every "N G obj" in the file (last definition wins)."""
        for m in re.finditer(rb"(?:^|[\r\n])[ \t]*(\d+)[ \t]+(\d+)[ \t]+obj\b",self.b):self.offsets[int(m.group(1))]=m.start(1)
        for n in list(self.offsets):
            try:o=self.get(n)
            except Exception:continue
            if isinstance(o,dict) and o.get("Type")=="Catalog":self.trailer["Root"]=Ref(n)
    def _obj_at(self,off):
        b=self.b;m=re.compile(rb"\s*(\d+)\s+(\d+)\s+obj").match(b,off)
        if not m:raise PdfError("object header missing")
        v,i=parse(b,m.end());i=_skip(b,i)
        if isinstance(v,dict) and b.startswith(b"stream",i):
            i+=6
            if b[i:i+2]==b"\r\n":i+=2
            elif b[i:i+1] in (b"\n",b"\r"):i+=1
            ln=v.get("Length")
            if isinstance(ln,Ref):ln=self.get(ln.num)
            if not isinstance(ln,int) or not b.startswith(b"endstream",_skip(b,i+ln)):
                j=b.find(b"endstream",i)
                if j<0:raise PdfError("unterminated stream")
                ln=j-i
                while ln and b[i+ln-1:i+ln] in (b"\n",b"\r"):ln-=1
            return Stream(v,b[i:i+ln])
        return v
    def get(self,num):
        if num in self.cache:return self.cache[num]
        v=None
        if num in self.offsets:v=self._obj_at(self.offsets[num])
        elif num in self.in_stream:
            host,idx=self.in_stream[num];st=self.get(host)
            data=self.decode(st);n=st.dict["N"];first=st.dict["First"]
            head=[int(x) for x in data[:first].split()]
            for k in range(n):
                onum,ooff=head[2*k],head[2*k+1]
                if onum not in self.cache:
                    try:self.cache[onum]=parse(data,first+ooff)[0]
                    except Exception:pass
            v=self.cache.get(num)
        self.cache[num]=v
        return v
    def res(self,v):
        n=0
        while isinstance(v,Ref) and n<50:v=self.get(v.num);n+=1
        return v
    def decode(self,st):
        """Stream data with Flate (and PNG predictors) undone; other filters are refused."""
        f=self.res(st.dict.get("Filter"));parms=self.res(st.dict.get("DecodeParms"))
        if f is None:return st.data
        if isinstance(f,list):
            if len(f)!=1:raise PdfError("filter chain not supported")
            f=f[0];parms=self.res(parms[0]) if isinstance(parms,list) and parms else parms
        if f!="FlateDecode":raise PdfError("filter %s not supported"%f)
        data=zlib.decompress(st.data)
        if isinstance(parms,dict) and self.res(parms.get("Predictor",1))>1:
            data=_unpredict(data,self.res(parms["Predictor"]),self.res(parms.get("Columns",1))*self.res(parms.get("Colors",1))*self.res(parms.get("BitsPerComponent",8))//8)
        return data
    def pages(self):
        """[(object number, page dict with inherited MediaBox/Resources/Rotate/CropBox filled in)] in reading order."""
        out=[];root=self.res(self.trailer["Root"])
        def walk(ref,inh,depth):
            if depth>40 or not isinstance(ref,Ref):return
            node=self.get(ref.num)
            if not isinstance(node,dict):return
            inh=dict(inh)
            for k in ("MediaBox","Resources","Rotate","CropBox"):
                if k in node:inh[k]=node[k]
            if node.get("Type")=="Pages" or "Kids" in node:
                for kid in self.res(node.get("Kids")) or []:walk(kid,inh,depth+1)
            else:
                page=dict(node)
                for k,v in inh.items():page.setdefault(k,v)
                out.append((ref.num,page))
        walk(root.get("Pages"),{},0)
        return out
    def page_content(self,page):
        c=self.res(page.get("Contents"));parts=[]
        for x in (c if isinstance(c,list) else [c]):
            st=self.res(x)
            if isinstance(st,Stream):parts.append(self.decode(st))
        return b"\n".join(parts)
    def media_box(self,page):
        mb=[float(self.res(x)) for x in self.res(page.get("MediaBox")) or [0,0,595,842]]
        return mb
# ---- markers ----
_STR_RX=re.compile(rb"\((?:\\.|[^\\()])*\)")
_N=rb"[-+]?(?:\d+\.?\d*|\.\d+)"
# Only what is needed to place a filled rectangle: save/restore, matrix, fill colour, rectangle. Everything else is skipped.
_OPS_RX=re.compile(rb"(?:(?<=\s)|^)(?:(q|Q)|((?:"+_N+rb"\s+){6})cm|("+_N+rb")\s+("+_N+rb")\s+("+_N+rb")\s+rg|("+_N+rb")\s+("+_N+rb")\s+("+_N+rb")\s+("+_N+rb")\s+re)(?=\s|$)")
def _mul(m,n):
    """m applied first, then n (PDF 'cm' pre-multiplies the current matrix)."""
    return (m[0]*n[0]+m[1]*n[2],m[0]*n[1]+m[1]*n[3],m[2]*n[0]+m[3]*n[2],m[2]*n[1]+m[3]*n[3],m[4]*n[0]+m[5]*n[2]+n[4],m[4]*n[1]+m[5]*n[3]+n[5])
def marker_code(r,g,b):
    """The marker palette of the report design: #ff, fa..fe, f2..fd -> 0..59; anything else is not a marker."""
    R,G,B=int(round(r*255)),int(round(g*255)),int(round(b*255))
    if R!=255 or not 250<=G<=254 or not 242<=B<=253:return None
    return (254-G)*12+(253-B)
def find_markers(content):
    """[(code, x, y)] for the marker squares of one page, in PDF user space (origin bottom-left), in drawing order."""
    out=[];ctm=(1.0,0.0,0.0,1.0,0.0,0.0);stack=[];fill=None
    if b"(" in content:content=_STR_RX.sub(b"()",content)
    for m in _OPS_RX.finditer(content):
        if m.group(1)==b"q":stack.append((ctm,fill))
        elif m.group(1)==b"Q":
            if stack:ctm,fill=stack.pop()
        elif m.group(2):
            try:ctm=_mul(tuple(float(x) for x in m.group(2).split()),ctm)
            except ValueError:pass
        elif m.group(3):
            try:fill=marker_code(float(m.group(3)),float(m.group(4)),float(m.group(5)))
            except ValueError:fill=None
        elif fill is not None:
            try:x,y,w,h=[float(m.group(k)) for k in range(6,10)]
            except ValueError:continue
            if abs(w)>4 or abs(h)>4:continue
            # Baseline of the text the marker sits in = the lower edge of the square on the page.
            pts=[(x*ctm[0]+yy*ctm[2]+ctm[4],x*ctm[1]+yy*ctm[3]+ctm[5]) for yy in (y,y+h)]
            out.append((fill,pts[0][0],min(p[1] for p in pts)))
    return out
# ---- writer ----
class Writer:
    def __init__(self):
        self.objs=[None];self.maps={}
    def add(self,obj):
        self.objs.append(obj)
        return Ref(len(self.objs)-1)
    def reserve(self):return self.add(None)
    def set(self,ref,obj):self.objs[ref.num]=obj
    def get(self,ref):return self.objs[ref.num]
    def imp(self,src,value,pages_ref=None):
        """Copy a value of another document (with everything it references) and return it in this document's numbering."""
        memo=self.maps.setdefault(id(src),{});todo=[]
        def conv(v,depth=0):
            if isinstance(v,Ref):
                if v.num not in memo:
                    memo[v.num]=self.reserve();todo.append(v.num)
                return memo[v.num]
            if isinstance(v,dict):
                page=v.get("Type") in ("Page","Pages")
                d={}
                for k,x in v.items():
                    if k=="Parent" and page:
                        if pages_ref is not None:d[k]=pages_ref
                        continue
                    if page and k in ("StructParents","Tabs"):continue
                    d[k]=conv(x,depth+1)
                return d
            if isinstance(v,list):return [conv(x,depth+1) for x in v]
            if isinstance(v,Stream):
                d=conv(v.dict);d.pop("Length",None)
                return Stream(d,v.data)
            return v
        out=conv(value)
        while todo:
            n=todo.pop()
            self.set(memo[n],conv(src.get(n)))
        return out
    def stream(self,data,extra=None,compress=True):
        d=dict(extra or {})
        if compress and "Filter" not in d:
            data=zlib.compress(data);d["Filter"]=Name("FlateDecode")
        return self.add(Stream(d,data))
    def write(self,path,root,info=None):
        out=bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n");offs=[0]*len(self.objs)
        for n in range(1,len(self.objs)):
            o=self.objs[n];offs[n]=len(out)
            out+=b"%d 0 obj\n"%n
            if isinstance(o,Stream):
                d=dict(o.dict);d["Length"]=len(o.data)
                out+=dump(d)+b"\nstream\n"+o.data+b"\nendstream"
            else:out+=dump(o)
            out+=b"\nendobj\n"
        xref=len(out)
        out+=b"xref\n0 %d\n0000000000 65535 f \n"%len(self.objs)
        for n in range(1,len(self.objs)):out+=b"%010d 00000 n \n"%offs[n]
        tr={"Size":len(self.objs),"Root":root}
        if info is not None:tr["Info"]=info
        out+=b"trailer\n"+dump(tr)+b"\nstartxref\n%d\n%%%%EOF\n"%xref
        with open(path,"wb") as f:f.write(out)
# A page that only sets line style (what fpdf2 writes for an empty page) draws nothing.
_BLANK_RX=re.compile(rb"\s*(?:[\d.]+\s+[Jjw]\s*)*")
def assemble(out_path,parts,overlay=None,links=None,outline=None,info=None):
    """Write one PDF.
    parts: [(Reader, [page indices])] in final order.
    overlay: Reader whose page i is drawn on top of final page i (pages without marks may be missing or empty).
    links: [{"page":i,"rect":[x0,y0,x1,y1],"to":j,"top":y}] internal links; outline: [{"title","page","top","level"}] bookmarks.
    info: {"Title":..,"Author":..,...} document properties. Returns the page count."""
    w=Writer();pages_ref=w.reserve();kids=[];boxes=[]
    for rd,idx in parts:
        src_pages=rd.pages()
        for i in idx:
            if i>=len(src_pages):continue
            num,page=src_pages[i]
            ref=w.imp(rd,Ref(num),pages_ref)
            d=w.get(ref)
            for k in ("MediaBox","Resources","Rotate","CropBox"):
                if k not in d and k in page:d[k]=w.imp(rd,page[k],pages_ref)
            d["Parent"]=pages_ref;d["Type"]=Name("Page")
            kids.append(ref);boxes.append(rd.media_box(page))
    if not kids:raise PdfError("no pages")
    def direct(v):
        n=0
        while isinstance(v,Ref) and n<50:v=w.get(v);n+=1
        return v
    if overlay is not None:
        opages=overlay.pages()
        for i,ref in enumerate(kids):
            if i>=len(opages):break
            _n,op=opages[i];data=overlay.page_content(op)
            if _BLANK_RX.fullmatch(data):continue
            form=w.stream(data,{"Type":Name("XObject"),"Subtype":Name("Form"),"BBox":[float(x) for x in overlay.media_box(op)],"Resources":w.imp(overlay,overlay.res(op.get("Resources")) or {})})
            d=w.get(ref)
            res=dict(direct(d.get("Resources")) or {});xo=dict(direct(res.get("XObject")) or {})
            xo["LoyaOv"]=form;res["XObject"]=xo;d["Resources"]=res
            old=d.get("Contents")
            if isinstance(old,Ref) and isinstance(w.get(old),list):old=w.get(old)
            old=list(old) if isinstance(old,list) else ([old] if old is not None else [])
            # The page's own drawing is fenced in q/Q so whatever graphics state it leaves behind cannot move the overlay.
            d["Contents"]=[w.stream(b"q\n",compress=False)]+old+[w.stream(b"\nQ\nq /LoyaOv Do Q\n",compress=False)]
    for ln in links or []:
        if not (0<=ln["page"]<len(kids) and 0<=ln["to"]<len(kids)):continue
        a=w.add({"Type":Name("Annot"),"Subtype":Name("Link"),"Rect":[float(x) for x in ln["rect"]],"Border":[0,0,0],"Dest":[kids[ln["to"]],Name("XYZ"),None,float(ln.get("top") or boxes[ln["to"]][3]),None]})
        d=w.get(kids[ln["page"]]);an=list(direct(d.get("Annots")) or []);an.append(a);d["Annots"]=an
    w.set(pages_ref,{"Type":Name("Pages"),"Kids":kids,"Count":len(kids)})
    cat={"Type":Name("Catalog"),"Pages":pages_ref,"ViewerPreferences":{"DisplayDocTitle":True}}
    items=[o for o in outline or [] if 0<=o["page"]<len(kids)]
    if items:
        root=w.reserve();refs=[w.reserve() for _ in items];top=[];parent_of={};last_top=None;children={}
        for i,o in enumerate(items):
            if o.get("level",1)>1 and last_top is not None:parent_of[i]=last_top;children.setdefault(last_top,[]).append(i)
            else:last_top=i;top.append(i)
        def link(seq,parent_ref):
            for k,i in enumerate(seq):
                o=items[i];d={"Title":o["title"][:200],"Parent":parent_ref,"Dest":[kids[o["page"]],Name("XYZ"),None,float(o.get("top") or boxes[o["page"]][3]),None]}
                if k:d["Prev"]=refs[seq[k-1]]
                if k<len(seq)-1:d["Next"]=refs[seq[k+1]]
                ch=children.get(i)
                if ch:
                    d["First"]=refs[ch[0]];d["Last"]=refs[ch[-1]];d["Count"]=-len(ch)
                    link(ch,refs[i])
                w.set(refs[i],d)
        link(top,root)
        w.set(root,{"Type":Name("Outlines"),"First":refs[top[0]],"Last":refs[top[-1]],"Count":len(top)})
        cat["Outlines"]=root;cat["PageMode"]=Name("UseOutlines")
    root_ref=w.add(cat)
    info_ref=w.add({k:v for k,v in (info or {}).items() if v}) if info else None
    w.write(out_path,root_ref,info_ref)
    return len(kids)
