"""[wave 10 copy: + old-repo/Hub URL skip via pipeline/tools/old_url_check, + skip doc ids already in any lane staging for this CC]
AU council local-law live crawler (wave 9). usage: afme_au_live.py places.json <max_places|0> [test]
Per council: RFC 9309 robots (rfc9309.py; 404=allow, unreachable/HTML robots=skip), crawl-delay max(robots,3s) per host, homepage + sitemap + 2-hop
BFS through local-law/policy pages; collects council local laws (QLD/VIC/WA/SA/TAS/NT), subordinate local laws, NSW local approvals/orders policies.
Excludes LEP/SEPP/state planning instruments, forms, drafts, consultation material. PDF->pdftotext (scans -> metadata-only + OCR queue).
Checkpoint: one atomic file per place out/afme/AU/<key>.<batch>.jsonl + _au_done.tsv."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,os,re,json,time,datetime,threading,subprocess,tempfile,zipfile,io,shutil,resource
from urllib.parse import urljoin,urlparse,urldefrag
from concurrent.futures import ThreadPoolExecutor
import requests,urllib3,gc,ctypes
urllib3.disable_warnings()
from bs4 import BeautifulSoup
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key
from rfc9309 import Robots
UA="JusticeDAO-WorldLaw/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; municipal law research)"
cfg=json.load(open(sys.argv[1])); MAXP=int(sys.argv[2]); TEST=len(sys.argv)>3
CC=cfg.get("cc","AU"); LANG=cfg.get("language","en"); PLAT=cfg.get("platform","au_council_site")
OUT=f"/workspace/world_law/out/afme/{CC}"; os.makedirs(OUT,exist_ok=True)
BATCH=cfg.get("batch","au_ll_"+datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"))
DONE=f"{OUT}/_au_done{'_test' if TEST else ''}.tsv"; OCRQ=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/_ocr_queue.jsonl")
EXCL={}  # place_key -> set(normalised doc ids/urls already on the Hub)
if cfg.get("exclude_file"):
    for l in open(cfg["exclude_file"]):
        k,_,d=l.rstrip("\n").partition("\t"); EXCL.setdefault(k,set()).add(d)
LAWTXT=re.compile(r"(?i)\b(local\s*laws?|subordinate\s*local|by-?laws?|local\s+approvals?\s+policy|local\s+orders?\s+policy|law\s+no\.?\s*\d)")
if cfg.get("lawtxt"): LAWTXT=re.compile(cfg["lawtxt"])
NAVTXT=re.compile(r"(?i)(local[\s_-]*laws?|by-?laws?|subordinate|laws?[\s_-]*(and|&)[\s_-]*polic|polic(y|ies)|governance|legislation|council[\s_-]*documents|publications|documents)")
if cfg.get("navtxt"): NAVTXT=re.compile(cfg["navtxt"])
NAVURL=re.compile(r"(?i)(local[-_]?laws?|by-?laws?|subordinate|polic(y|ies)|governance|legislation|council-documents|publications|document)")
if cfg.get("navurl"): NAVURL=re.compile(cfg["navurl"])
BAD=re.compile(r"(?i)(local\s+environmental\s+plan|\bLEP\b|state\s+environmental\s+planning|\bSEPP\b|planning\s+scheme|application|\bform\b|checklist|fact\s*sheet|brochure|guideline|submission|consultation|have\s+your\s+say|engagement|survey|draft|proposed|notice\s+of\s+intention|agenda|minutes|report|annual|budget|newsletter|media\s+release|explanatory|review\s+of|competition\s+review|public\s+interest\s+test|map\b|register\b|fee|charges|infringement\s+notice|declaration|manual|protocol)")
if cfg.get("bad"): BAD=re.compile(cfg["bad"])
DOCEXT=re.compile(r"(?i)\.(pdf|docx?)(\?|$)|/(download|downloads|files|assets|documents?|file|getmedia|media)/|/(file|download)$|[?&](download|dl)=")
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/tools"))
from old_url_check import covered as _covered
import glob as _g
SEEN=set()
for _f in _g.glob(f"/workspace/world_law/staging/*/{CC}/*.jsonl"):
    try:
        for _l in open(_f):
            try: _r=json.loads(_l)
            except Exception: continue
            for _k in ("doc_id","source_url"): SEEN.add(re.sub(r"^https?://(www\.)?","",str(_r.get(_k,""))).rstrip("/").lower())
    except Exception: pass
_hl=threading.Lock(); _last={}
def ts(): return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
def nid(u):
    u=urldefrag(u)[0]; return re.sub(r"^https?://(www\.)?","",u).rstrip("/").lower()
class Host:
    def __init__(s,site):
        s.S=requests.Session(); s.S.headers["User-Agent"]=UA; s.base=site; s.n=0
        s.robots=None; s.delay=3.0; s.policy=None; s.verify=True
    def wait(s,host):
        while True:
            with _hl:
                t=_last.get(host,0); now=time.time()
                if now-t>=s.delay: _last[host]=now; return
            time.sleep(s.delay-(now-t)+0.05)
    def get(s,u,stream=False,**kw):
        h=urlparse(u).netloc.lower()
        if s.robots and not s.robots.can_fetch(UA,u): return None
        s.wait(h); s.n+=1
        try: return s.S.get(u,timeout=40,stream=stream,allow_redirects=True,verify=s.verify,**kw)
        except requests.exceptions.SSLError:
            if s.verify:   # broken/incomplete certificate chain on a public council site: retry once without verification (no challenge bypass)
                s.verify=False; return s.get(u,stream,**kw) if False else s.S.get(u,timeout=40,stream=stream,allow_redirects=True,verify=False,**kw)
            return None
        except Exception: return None
def load_robots(H,site):
    p=urlparse(site); u=f"{p.scheme}://{p.netloc}/robots.txt"; H.wait(p.netloc.lower())
    try: r=H.S.get(u,timeout=20)
    except requests.exceptions.SSLError:
        try: r=H.S.get(u,timeout=20,verify=False); H.verify=False
        except Exception as e: return None,f"robots_unreachable: {type(e).__name__}"
    except Exception as e: return None,f"robots_unreachable: {type(e).__name__}"
    if r.status_code in (404,410): return Robots(allow_all=True),"robots_404_allow_rfc9309"
    if r.status_code>=400: return None,f"robots_unreachable: HTTP {r.status_code}"
    t=r.text
    if re.search(r"(?i)<html|<!doctype",t[:500]): return None,"robots_html_skip"
    R=Robots(t); return R,"robots_allowed_rfc9309"
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf",dir=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme")) as f:
        f.write(b); f.flush()
        try: return subprocess.run(["pdftotext","-layout","-enc","UTF-8",f.name,"-"],capture_output=True,timeout=120).stdout.decode("utf8","replace")
        except Exception: return ""
def docxtext(b):
    try:
        x=zipfile.ZipFile(io.BytesIO(b)).read("word/document.xml").decode("utf8","replace")
        x=re.sub(r"</w:p>","\n",x); return re.sub(r"<[^>]+>","",x)
    except Exception: return ""
def same_site(u,hosts): h=urlparse(u).netloc.lower().removeprefix("www."); return any(h==x or h.endswith("."+x) for x in hosts)
def crawl(p):
    key=place_key(p["place_id"],None,CC); site=p["site"].rstrip("/")
    site=re.sub(r"^(https?://)?","https://",site)   # https first (port 80 times out from the box); http fallback
    H=Host(site); st={"key":key,"site":site,"pages":0,"docs":0,"rows":0,"policy":None,"err":None}
    R,pol=load_robots(H,site)
    if R is None and pol.startswith("robots_unreachable: Conn"):
        site2=site.replace("https://","http://",1); R2,pol2=load_robots(H,site2)
        if R2 is not None: site,R,pol=site2,R2,pol2
    st["policy"]=pol; st["site"]=site
    if R is None: return st
    H.robots=R; cd=R.crawl_delay(UA); H.delay=max(3.0,float(cd or 0)); H.policy=pol
    if H.delay>30: st["err"]="crawl_delay>30"; return st
    r=H.get(site+"/")
    if r is None or r.status_code>=400: st["err"]=f"home {getattr(r,'status_code',None)}"; return st
    hosts={urlparse(site).netloc.lower().removeprefix("www."),urlparse(r.url).netloc.lower().removeprefix("www.")}
    if R is not None and urlparse(r.url).netloc.lower()!=urlparse(site).netloc.lower():   # redirected host: its own robots
        R2,pol2=load_robots(H,r.url)
        if R2 is None: st["policy"]=pol2; return st
        H.robots=R2; H.delay=max(3.0,float(R2.crawl_delay(UA) or 0)); st["policy"]=pol=pol2
    pages=[]; seen=set(); docs={}
    def links(html,base):
        try: s=BeautifulSoup(html[:3_000_000],"html.parser")
        except Exception: return []
        out=[]
        for a in s.find_all("a",href=True):
            u=urljoin(base,a["href"].strip()); u=urldefrag(u)[0]
            if not u.startswith("http"): continue
            t=" ".join(a.get_text(" ",strip=True).split())[:300] or a.get("title","") or a.get("aria-label","")
            out.append((u,t))
        return out
    def consider(lst,depth):
        for u,t in lst:
            if not same_site(u,hosts): continue
            path=urlparse(u).path
            if DOCEXT.search(u) or re.search(r"(?i)\.(pdf|docx?)$",path):
                blob=t+" "+path.replace("-"," ").replace("_"," ").replace("/"," ")
                if LAWTXT.search(blob) and not BAD.search(blob):
                    docs.setdefault(u,t or os.path.basename(path))
            elif depth<3 and u not in seen and (NAVTXT.search(t) or NAVURL.search(path)) and not re.search(r"(?i)(news|event|media|careers|jobs|tender|whats-on|search\?|calendar|/my-|login)",u):
                if LAWTXT.search(t+" "+path.replace("-"," ")): pages.insert(0,(u,depth+1))
                else: pages.append((u,depth+1))
    consider(links(r.text,r.url),0); seen.add(site+"/")
    # sitemap hints
    for sm in [site+"/sitemap.xml"][:1]:
        x=H.get(sm)
        if x is not None and x.status_code==200 and len(x.content)<20_000_000:
            locs=re.findall(r"<loc>\s*([^<\s]+)\s*</loc>",x.text)
            subs=[l for l in locs if l.endswith(".xml")][:4]
            for sub in subs:
                y=H.get(sub)
                if y is not None and y.status_code==200 and len(y.content)<20_000_000: locs+=re.findall(r"<loc>\s*([^<\s]+)\s*</loc>",y.text)
            for l in locs:
                if re.search(r"(?i)local[-_]?laws?|subordinate|by-?law",l) and not l.endswith(".xml"):
                    if re.search(r"(?i)\.(pdf|docx?)$",urlparse(l).path):
                        b=os.path.basename(urlparse(l).path).replace("-"," ")
                        if not BAD.search(b): docs.setdefault(l,b)
                    else: pages.insert(0,(l,1))
    cap=cfg.get("page_cap",25)
    while pages and st["pages"]<cap:
        u,d=pages.pop(0)
        if u in seen: continue
        seen.add(u); x=H.get(u)
        if x is None or x.status_code>=400 or "html" not in x.headers.get("content-type",""): continue
        st["pages"]+=1
        consider(links(x.text,x.url),d)
    ex=EXCL.get(key,set()); rows=[]
    for u,t in list(docs.items())[:cfg.get("doc_cap",40)]:
        if nid(u) in ex or nid(u) in SEEN or _covered(u): continue
        x=H.get(u)
        if x is None or x.status_code>=400 or len(x.content)>25_000_000: continue
        ctype=x.headers.get("content-type","").lower(); b=x.content; fu=x.url
        if nid(fu) in ex or nid(fu) in SEEN: continue
        if b[:4]==b"%PDF" or "pdf" in ctype: txt=pdftext(b); fmt="pdf_text"
        elif b[:2]==b"PK" and ("word" in ctype or fu.lower().endswith(".docx") or u.lower().endswith(".docx")): txt=docxtext(b); fmt="docx_text"
        else: continue
        txt=re.sub(r"[ \t]+\n","\n",txt).strip(); st["docs"]+=1
        title=t if len(t)>6 and not re.fullmatch(r"(?i)(download|view|pdf|here|click here|descarregar|baixar|transferir|ver|abrir|download\s+\(.*\)|.*\.pdf)",t) else ""
        if not title:
            m=re.search(cfg.get("title_re") or r"(?im)^\s*((subordinate\s+)?local\s+law\s+(no\.?\s*)?\d+[^\n]{0,120})",txt[:6000]); title=(m.group(1) if m else os.path.basename(urlparse(fu).path)).strip()
        if re.fullmatch(r"(?i)[\w.%-]+\.(pdf|docx?)|[A-Za-z0-9._-]{8,}",title) and ("-" in title or "_" in title or title.lower().endswith((".pdf",".doc",".docx"))):
            title=re.sub(r"(?i)\.(pdf|docx?)$","",title).replace("_"," ").replace("-"," "); title=re.sub(r"\s+"," ",title).strip()
        if cfg.get("bad_title") and re.search(cfg["bad_title"],title): continue
        title=re.sub(r"(?i)\s*[\(\[]\s*(pdf|docx?|word)\b[^)\]]*[\)\]]","",title)
        title=re.sub(r"(?i)^(view|download|read|open)(\s+the)?(\s+(current|adopted))?\s+","",title).strip(" -–|")
        title=re.sub(r"(?i)[\s(]+(pdf|docx?)[\s,]*[\d.,]+\s*[KM]B\)?\s*$","",title).strip()
        if BAD.search(title) or not LAWTXT.search(title+" "+txt[:3000]): continue
        if re.search(r"(?i)local\s+environmental\s+plan|state\s+environmental\s+planning",txt[:1500]): continue
        num=re.search(r"(?i)(?:law\s+no\.?\s*|local\s+law\s+)(\d{1,2}(?:\.\d+)?[A-Za-z]?)\b(?!\d)(?:\s*\(|\s+of\s+|\s*[-–,]?\s*)((19|20)\d\d)?",title)
        numv=(num.group(1)+(" of "+num.group(2) if num.group(2) else "")) if num else None
        if cfg.get("number_re"): mm=re.search(cfg["number_re"],title); numv=mm.group(1) if mm else None
        sub=bool(re.search(r"(?i)subordinate|polic",title))
        complete=len(txt)>200
        rec=dict(place_id=p["place_id"],country_code=CC,doc_id=nid(fu),source_platform=PLAT,source_url=fu,
            doc_type=("regulation" if re.search(cfg["regulation_re"],title) else "ordinance") if cfg.get("regulation_re") else ("regulation" if sub else "ordinance"),language=LANG,title_native=" ".join(title.split())[:400],
            number=numv,published_date=None,
            consolidated=bool(re.search(r"(?i)consolidat",title)),in_force=None,content_format=fmt,text=txt if complete else "",
            retrieved_at=ts(),content_complete=complete,source_policy=pol,source_official=True,source_org=p["name"],
            place_name=p["name"],qid=p["place_id"].split(":")[1],admin_level=p.get("admin_level","municipality"),state_code=p.get("state"),
            platform=PLAT,platform_place_id=urlparse(site).netloc,
            extra_metadata={"crawl_delay_s":H.delay,"tls_verify":H.verify,"link_text":t[:300],"discovered_via":"council site crawl (homepage/sitemap/local-law pages)","bytes":len(b)})
        if not complete: rec["extra_metadata"]["note"]="no text layer (scan?) -> OCR queue"
        rows.append(rec)
    seen_ids=set(); rows=[r for r in rows if not (r["doc_id"] in seen_ids or seen_ids.add(r["doc_id"]))]
    seen_tx=set(); rows=[r for r in rows if not r["text"] or not (hash(r["text"]) in seen_tx or seen_tx.add(hash(r["text"])))]
    if rows:
        f=f"{OUT}/{key}.{BATCH}{'.test' if TEST else ''}.jsonl"
        with open(f+".tmp","w") as o:
            for x in rows: o.write(json.dumps(x,ensure_ascii=False)+"\n")
            o.flush(); os.fsync(o.fileno())
        os.rename(f+".tmp",f)
        if not TEST:
            with _hl, open(OCRQ,"a") as q:
                for x in rows:
                    if not x["content_complete"]: q.write(json.dumps({"cc":CC,"place_key":key,"doc_id":x["doc_id"],"pdf_url":x["source_url"],"file":f})+"\n")
    st["rows"]=len(rows); st["n_req"]=H.n; return st
places=cfg["places"]
done=set()
if os.path.exists(DONE): done={l.split("\t")[0] for l in open(DONE)}
todo=[p for p in places if place_key(p["place_id"],None,CC) not in done][:(MAXP or None)]
print(f"{len(todo)} councils to crawl ({len(done)} done)",flush=True)
def job(p):
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor",flush=True); os._exit(3)
    try: st=crawl(p)
    except Exception as e: st={"key":place_key(p["place_id"],None,CC),"err":repr(e)[:200],"rows":0}
    gc.collect()   # per-council pages/docs/soup trees are locals of crawl(); collect and hand freed arenas back to the OS
    try: ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception: pass
    with _hl, open(DONE,"a") as d: d.write(f"{st['key']}\t{json.dumps(st)}\n")
    print(json.dumps(st),"rss_mb=%d"%(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024),flush=True)
with ThreadPoolExecutor(cfg.get("threads",8)) as ex: list(ex.map(job,todo))
print("DONE",flush=True)
