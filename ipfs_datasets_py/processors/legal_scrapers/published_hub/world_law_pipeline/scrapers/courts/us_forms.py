"""Statewide court forms collector.
Finds the forms index from the judiciary home page (link text 'Forms'), crawls same-host pages whose URL/text mentions forms
(BFS, depth<=3, max pages per state), downloads linked PDFs to forms/us/<ST>/<sha256>.pdf, writes rows to data/us/us_forms.jsonl.
Resumable: skips URLs already in output. Stops if disk free < 22 GB. Crawl delay 1.5 s per request."""
import re,os,sys,json,time,html,hashlib,shutil,datetime,urllib.request,urllib.parse
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from us_state_judiciaries import STATES
from robots_policy import policy,UA
ROOT="/workspace/world_courts";OUT=ROOT+"/data/us/us_forms.jsonl"
MAXPAGES=int(os.environ.get("MAXPAGES","80"));MAXPDF=int(os.environ.get("MAXPDF","1500"));MAXBYTES=40_000_000
SEEDS=json.loads(os.environ.get("FORM_SEEDS","{}"))
FORMRE=re.compile(r'form',re.I)
def req(u,n=3_000_000):
    r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=40);return r.read(n),r.headers.get("Content-Type","")
def sj(b,x):
    try: return urllib.parse.urljoin(b,html.unescape(x)).split("#")[0]
    except ValueError: return None
def links(h,base):
    for u,t in re.findall(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',h,re.S|re.I):
        u=sj(base,u)
        if u and u.startswith("http"): yield u,re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',t))).strip()
def freegb(): return shutil.disk_usage("/workspace").free/1e9
FNUM=re.compile(r'\b([A-Z]{1,6}[- ]?\d{1,4}(?:[-.]\d{1,4})?[A-Z]?)\b')
def run(states):
    done=set()
    if os.path.exists(OUT):
        for l in open(OUT): done.add(json.loads(l)["source_url"])
    f=open(OUT,"a")
    for st in states:
        home=STATES[st][0];host=urllib.parse.urlsplit(home).netloc;dom=".".join(host.split(".")[-2:])
        try: h=req(home)[0].decode("utf-8","replace")
        except Exception as e:
            print(st,"home_err",e,file=sys.stderr)
            if st not in SEEDS: continue
            h=""
        seeds=[u for u,t in links(h,home) if re.search(r'\bforms?\b',t,re.I) and dom in urllib.parse.urlsplit(u).netloc]
        if st in SEEDS: seeds=SEEDS[st]+seeds  # site-specific form index pages (retry pass)
        q=list(dict.fromkeys(seeds))[:8];seen=set(q);pages=0;pdfs=0;depth={u:0 for u in q}
        while q and pages<MAXPAGES and pdfs<MAXPDF:
            u=q.pop(0);pol=policy(u)
            if pol=="robots_disallowed": continue
            time.sleep(1.5)
            try: b,ct=req(u)
            except Exception: continue
            if "html" not in ct: continue
            pages+=1;hh=b.decode("utf-8","replace")
            for v,t in links(hh,u):
                if dom not in urllib.parse.urlsplit(v).netloc: continue
                if re.search(r'\.pdf($|\?)',v,re.I):
                    if v in done or pdfs>=MAXPDF: continue
                    if freegb()<22: print("DISK LOW stop",file=sys.stderr);return
                    pp=policy(v)
                    if pp=="robots_disallowed": continue
                    time.sleep(1.5)
                    try: data,ct2=req(v,MAXBYTES)
                    except Exception: continue
                    if not data.startswith(b"%PDF"): continue
                    sha=hashlib.sha256(data).hexdigest();d=f"{ROOT}/forms/us/{st}";os.makedirs(d,exist_ok=True)
                    p=f"{d}/{sha}.pdf"
                    if not os.path.exists(p): open(p,"wb").write(data)
                    fn=os.path.basename(urllib.parse.urlsplit(v).path);m=FNUM.search(t) or FNUM.search(fn.replace("_"," "))
                    row={"form_id":f"US-{st}:{sha[:16]}","court_id":None,"jurisdiction":f"US-{st}","form_number":m.group(1) if m else None,"title":t or fn,
                         "category":None,"language":"en","revision_date":None,"pdf_path":f"forms/us/{st}/{sha}.pdf","pdf_sha256":sha,"file_bytes":len(data),
                         "index_url":u,"source_url":v,"site_policy":pp,"retrieved_at":datetime.datetime.now(datetime.UTC).isoformat()}
                    f.write(json.dumps(row)+"\n");f.flush();done.add(v);pdfs+=1
                elif v not in seen and depth[u]<3 and FORMRE.search(v+" "+t) and not re.search(r'\.(docx?|xlsx?|rtf|zip|jpg|png)($|\?)',v,re.I):
                    seen.add(v);depth[v]=depth[u]+1;q.append(v)
        print(st,"pages",pages,"pdfs",pdfs,file=sys.stderr)
if __name__=="__main__": run(sys.argv[1:] or list(STATES))
