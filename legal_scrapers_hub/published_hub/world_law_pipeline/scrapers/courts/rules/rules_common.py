"""Shared helpers for US state court-rule collection: polite fetch with robots/site_policy tagging and Wayback fallback,
text extraction (HTML/PDF), rule splitting, and upstream (justicedao/ipfs_court_rules) record building."""
import os,re,sys,json,time,html,hashlib,base64,datetime,subprocess,urllib.request,urllib.parse
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from robots_policy import policy,UA
ROOT="/workspace/world_courts";RAW=ROOT+"/rules/raw";PDFDIR=ROOT+"/rules/pdf"
STATES={"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut","DE":"Delaware","DC":"District of Columbia","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming"}
_last={}
import gzip as _gzip
def _gz(b):
    return _gzip.decompress(b) if b[:2]==b'\x1f\x8b' else b
def polite_get(url,delay=2.0,binary=False,maxbytes=60_000_000):
    url=url.replace(" ","%20")
    """returns (bytes, effective_url, site_policy). Crawl delay >= `delay` s per host. robots-disallowed or blocked -> Wayback snapshot."""
    import robots_policy as _RP
    if _RP.optout(url): return None,url,"ai_train_optout_skipped"
    delay=max(delay,_RP.crawl_delay(url))
    host=urllib.parse.urlsplit(url).netloc;w=delay-(time.time()-_last.get(host,0))
    if w>0: time.sleep(w)
    pol=policy(url)
    if pol!="robots_disallowed":
        try:
            r=urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=60);b=_gz(r.read(maxbytes));_last[host]=time.time();return b,url,pol
        except Exception as e: _last[host]=time.time();err=str(e)[:80]
    try:
        _w=1.5-(time.time()-_last.get("archive.org",0))
        if _w>0: time.sleep(_w)
        _last["archive.org"]=time.time()
        j=json.load(urllib.request.urlopen("https://archive.org/wayback/available?url="+urllib.parse.quote(url,safe=""),timeout=30))
        ts=j["archived_snapshots"]["closest"]["timestamp"];u=f"https://web.archive.org/web/{ts}id_/{url}"
        b=_gz(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=90).read(maxbytes));_last['archive.org']=time.time()
        return b,f"https://web.archive.org/web/{ts}/{url}",pol+("+live_blocked" if pol!="robots_disallowed" else "")+"|archive_wayback"
    except Exception: return None,url,pol
def cached(url,key,**kw):
    p=f"{RAW}/{key}"
    if os.path.exists(p) and os.path.exists(p+".meta"):
        m=json.load(open(p+".meta"));return open(p,"rb").read(),m["url"],m["policy"]
    b,u,pol=polite_get(url,**kw)
    if b is None: return None,url,pol
    os.makedirs(RAW,exist_ok=True);open(p,"wb").write(b);json.dump({"url":u,"policy":pol,"fetched":datetime.datetime.now(datetime.UTC).isoformat()},open(p+".meta","w"))
    return b,u,pol
def html_text(b,root=None):
    """block-aware text: block tags -> newlines, inline joined, source hard-wraps collapsed to spaces."""
    from bs4 import BeautifulSoup,NavigableString,Comment
    s=BeautifulSoup(b,"html.parser")
    for t in s(["script","style","nav","header","footer","noscript"]): t.decompose()
    for n in s.find_all(string=True):
        if isinstance(n,Comment): n.extract()
        else: n.replace_with(NavigableString(re.sub(r"\s+"," ",str(n))))
    for t in s.find_all(["p","div","br","h1","h2","h3","h4","h5","h6","li","tr","table","section","article","center","blockquote","pre","hr","ul","ol","dd","dt"]):
        t.insert_before("\n");t.insert_after("\n")
    return norm((root(s) if root else s).get_text(""))
def pdf_text(path,layout=False,mode=None):
    return norm(subprocess.run(["pdftotext"]+(["-layout"] if layout else [])+(["-raw"] if mode=="raw" else [])+[path,"-"],capture_output=True,text=True).stdout)
def norm(t):
    t=t.replace("\r","")
    t=t.replace("\u2002"," ").replace("\u2003"," ").replace("\u2009"," ").replace("\xa0"," ").replace("\u200b","").replace("\f","\n")
    t=re.sub(r"[ \t]+"," ",t);t=re.sub(r"[ \t]*\n[ \t]*","\n",t);return re.sub(r"\n{2,}","\n",t).strip()
def flatten(t):
    """join hard-wrapped lines into paragraphs: keep a break before '(a)', 'Rule N', 'Comment', 'Advisory' etc."""
    t=re.sub(r"\n(?!\s*(?:\([a-zA-Z0-9]{1,4}\)|[A-Z]?\d+(?:\.\d+)?\s*[.)]\s|Rule\s+\d|RULE\s+\d|\[|Comment|COMMENT|Advisory|ADVISORY|Note|NOTE|Source|SOURCE|Editor|Historical)))"," ",t)
    return re.sub(r" {2,}"," ",t)
def split_rules(t,head_re,min_len=40):
    """head_re: regex with named groups num, title (optional); anchored per-line (MULTILINE). Returns list of dict(num,title,text,start)."""
    ms=list(re.finditer(head_re,t,re.M))
    out=[]
    for i,m in enumerate(ms):
        end=ms[i+1].start() if i+1<len(ms) else len(t)
        body=t[m.end():end].strip()
        out.append({"num":m.group("num"),"title":(m.groupdict().get("title") or "").strip(" .:-—–"),"text":body,"start":m.start()})
    return out
def dagjson_cid(obj):
    b=json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return "b"+base64.b32encode(b"\x01\xa9\x02\x12\x20"+hashlib.sha256(b).digest()).decode().lower().rstrip("=")
