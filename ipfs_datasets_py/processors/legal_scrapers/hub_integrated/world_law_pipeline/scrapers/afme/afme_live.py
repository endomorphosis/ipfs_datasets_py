"""afme polite live crawler (rebuilt 2026-10-16). RFC 9309 via pipeline/scrapers/web/rfc9309.py; delay = max(robots Crawl-delay, cfg min_delay>=3 s) per host;
robots unreachable (non-200/404 or HTML instead of robots) -> host skipped; 404 robots -> allow (RFC 9309 2.3.1.3). No challenge bypass: a page that looks like a
JS/bot challenge stops the host. Only docs whose title matches cfg title_include and not title_exclude (national-content markers) are kept.
cfg: {cc, name(batch), platform, language, doc_type, min_delay, threads, sites:[{host, seeds[], place_id | "by_host", follow_regex, doc_regex, depth, max_docs, note}],
      title_include, title_exclude}
usage: afme_live.py cfg.json [test]   checkpoint: per place file <key>.<name>2*.jsonl in the outdir -> site skipped."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,time,glob,subprocess,datetime,shutil,threading,urllib.parse,collections
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup as B
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key, validate_file
from rfc9309 import Robots
UA="world-municipal-law-research/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law)"
cfg=json.load(open(sys.argv[1])); TEST=len(sys.argv)>2 and sys.argv[2]=="test"
CC=cfg["cc"]; NAME=cfg["name"]; BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); OUT=f"{BASE}/_test/{CC}_{NAME}" if TEST else f"{BASE}/{CC}"; os.makedirs(OUT,exist_ok=True)
LOG=open(f"{BASE}/_live_{NAME}{'_test' if TEST else ''}.events.log","a")
def ev(*a): LOG.write(datetime.datetime.now().strftime("%H:%M:%S ")+" ".join(map(str,a))+"\n"); LOG.flush()
places={r["place_id"]:r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]==CC}
INC=re.compile(cfg["title_include"],re.I); EXC=re.compile(cfg.get("title_exclude","$^"),re.I)
CHAL=re.compile(r"(?i)(SHA256_init|cf-chl|challenge-platform|just a moment|checking your browser|captcha|ddos-guard|incapsula)")
class Host:
    def __init__(s,host,mind):
        s.host=host; s.next=0; s.S=requests.Session(); s.S.headers["User-Agent"]=UA
        r=s.S.get(f"https://{host}/robots.txt",timeout=30,allow_redirects=True)
        if r.status_code==404 or (r.status_code==200 and "<html" in r.text[:500].lower() and "disallow" not in r.text.lower()): 
            if r.status_code==200: raise PermissionError("robots.txt served as HTML page (unreachable per policy)")
            s.rb=Robots(allow_all=True); s.raw="(404)"
        elif r.status_code==200: s.rb=Robots(r.text); s.raw=r.text[:2000]
        else: raise PermissionError(f"robots http {r.status_code}")
        s.delay=max(float(s.rb.crawl_delay(UA) or 0),mind); s.next=time.time()+s.delay
    def get(s,u):
        if not s.rb.can_fetch(UA,u): raise PermissionError("robots disallow "+u)
        d=s.delay
        for i in range(4):
            w=s.next-time.time()
            if w>0: time.sleep(w)
            s.next=time.time()+s.delay
            try: r=s.S.get(u,timeout=60)
            except Exception as e: time.sleep(d); d*=2; continue
            if r.status_code in (429,503): ra=r.headers.get("Retry-After"); time.sleep(float(ra) if ra and ra.isdigit() else d); d*=2; continue
            if r.status_code>=400: raise RuntimeError(f"http {r.status_code}")
            if "html" in r.headers.get("Content-Type","") and CHAL.search(r.text[:20000]): raise PermissionError("challenge page; stop host")
            return r
        raise RuntimeError("fetch failed")
def text_of(r):
    if r.content[:5]==b"%PDF-":
        p=f"/tmp/afme_live_{os.getpid()}_{threading.get_ident()}.pdf"; open(p,"wb").write(r.content)
        return "pdf_text",None,subprocess.run(["pdftotext","-layout",p,"-"],capture_output=True,text=True,timeout=120).stdout
    s=B(r.content,"html.parser")
    for t in s(["script","style","nav","header","footer","noscript","form","aside"]): t.decompose()
    m=None
    for sel in cfg.get("content_selectors",[])+["article","main","#content",".content","body"]:
        m=s.select_one(sel)
        if m and len(m.get_text(strip=True))>200: break
    m=m or s
    return "html",f'<div class="chunk-content">{m.decode_contents()}</div>',m.get_text("\n",strip=True)
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); rep=[]; lock=threading.Lock()
def run_site(site):
    pid=site["place_id"]; p=places.get(pid)
    if not p: return {"host":site["host"],"status":"no_place"}
    key=place_key(pid,p.get("gnis"),CC)
    if glob.glob(f"{OUT}/{key}.{NAME}2*.jsonl"): return {"host":site["host"],"status":"skip_done"}
    if shutil.disk_usage("/workspace").free<35*2**30: return {"host":site["host"],"status":"disk_floor"}
    try: H=Host(site["host"],float(cfg.get("min_delay",3)))
    except Exception as e: ev(site["host"],"robots",repr(e)[:120]); return {"host":site["host"],"status":"robots_skip","why":repr(e)[:120]}
    FOL=re.compile(site["follow_regex"]); DOC=re.compile(site["doc_regex"]); seen=set(); q=[(u,0) for u in site["seeds"]]; cands={}
    maxd=(5 if TEST else site.get("max_docs",300))
    try:
        while q and len(seen)<site.get("max_pages",60 if not TEST else 15):
            u,dep=q.pop(0)
            if u in seen: continue
            seen.add(u)
            try: r=H.get(u)
            except PermissionError as e:
                ev(site["host"],"perm",repr(e)[:120])
                if "challenge" in str(e): raise
                continue
            except Exception as e: ev(site["host"],"err",u,repr(e)[:80]); continue
            s=B(r.content,"html.parser")
            for a in s.find_all("a",href=True):
                h=urllib.parse.urljoin(u,a["href"]).split("#")[0]
                if urllib.parse.urlparse(h).hostname not in (site["host"],"www."+site["host"],site["host"].replace("www.","")): continue
                lt=a.get_text(" ",strip=True) or a.get("title","")
                if site.get("card_title") and (not lt or re.fullmatch(site.get("generic_link","الاطلاع|عرض|تحميل|download|view|ver|descargar"),lt,re.I)):
                    par=a
                    for _ in range(5):
                        par=par.parent
                        if par is None: break
                        ct=par.get_text(" ",strip=True).replace(lt,"").strip()
                        if len(ct)>8: lt=re.split(site.get("card_cut","تاريخ النشر|Fecha"),ct)[0].strip()[:300]; break
                if DOC.search(h):
                    if h not in cands: cands[h]=lt
                elif FOL.search(h) and dep<site.get("depth",1): q.append((h,dep+1))
    except PermissionError as e: return {"host":site["host"],"status":"challenge_stop"}
    rows=[]; skipped=collections.Counter()
    for h,lt in list(cands.items()):
        if len(rows)>=maxd: break
        title=lt or urllib.parse.unquote(h.rstrip("/").rsplit("/",1)[-1])
        if not INC.search(title) and not INC.search(urllib.parse.unquote(h)): skipped["not_local_rule"]+=1; continue
        if EXC.search(title): skipped["national_marker"]+=1; continue
        try:
            r=H.get(h); fmt,html,text=text_of(r)
            if fmt=="html" and site.get("pdf_in_page",True):   # publication node -> attached PDF
                s=B(r.content,"html.parser"); pdf=next((urllib.parse.urljoin(h,a["href"]) for a in s.find_all("a",href=True) if re.search(r"\.pdf($|\?)",a["href"],re.I)),None)
                ttl=(s.h1.get_text(" ",strip=True) if s.h1 else "")
                if ttl: title=ttl
                if EXC.search(title) or not INC.search(title+" "+h): skipped["title_after_open"]+=1; continue
                if pdf and len((text or "").strip())<800:
                    try: r2=H.get(pdf); f2,_,t2=text_of(r2)
                    except Exception: f2=None
                    if f2=="pdf_text": fmt,html,text,h=f2,None,t2,pdf
        except PermissionError as e:
            if "challenge" in str(e): break
            skipped["robots"]+=1; continue
        except Exception as e: skipped["fetch_err"]+=1; continue
        rec=dict(place_id=pid,country_code=CC,doc_id=re.sub(r"^https?://(www\.)?","",h).rstrip("/"),source_platform=cfg["platform"],source_url=h,
            doc_type=site.get("doc_type",cfg.get("doc_type","decision")),language=site.get("language",cfg["language"]),title_native=title[:500],consolidated=False,in_force=None,
            content_format=fmt,retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),source_policy="robots_allowed_rfc9309",
            source_official=True,source_org=site.get("org",site["host"]),place_name=p["place_name"],qid=p["qid"],admin_level=p["admin_level"],
            platform=cfg["platform"],platform_place_id=site["host"],extra_metadata={"crawl_delay_s":H.delay,"site_note":site.get("note","")})
        if html: rec["html"]=html
        rec["text"]=text
        y=re.search(r"(19|20)\d\d",title)
        if y: rec["adopted_date"]=y.group(0)
        if len((text or "").strip())<200: rec["content_complete"]=False; rec["extra_metadata"]["note"]="no text layer (scan) -> raw PDF queue"
        rows.append(rec)
    if not rows: return {"host":site["host"],"place":p["place_name"],"status":"no_docs","cands":len(cands),"skipped":dict(skipped)}
    with lock:
        f=f"{OUT}/{key}.{NAME}{ts}p0001.jsonl"
        if os.path.exists(f): f=f.replace("p0001",f"p{len(glob.glob(f.replace('p0001','p*'))) +1:04d}")
        with open(f+".tmp","w") as o:
            for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
            o.flush(); os.fsync(o.fileno())
        os.rename(f+".tmp",f); v=validate_file(f)
    return {"host":site["host"],"place_id":pid,"name":p["place_name"],"docs":len(rows),"skipped":dict(skipped),"ok":v["ok"],"errors":v.get("errors",[])[:2]}
sites=cfg["sites"][: (20 if TEST else None)]
with ThreadPoolExecutor(int(cfg.get("threads",3))) as ex:
    for res in ex.map(run_site,sites):
        rep.append(res); print(json.dumps(res,ensure_ascii=False),flush=True)
json.dump(rep,open(f"{BASE}/_live_{NAME}_report_{'test' if TEST else 'full'}_{ts}.json","w"),indent=1,ensure_ascii=False)
print("DONE ok",sum(1 for r in rep if r.get("ok")),"bad",sum(1 for r in rep if r.get("ok") is False),"of",len(rep),flush=True)
