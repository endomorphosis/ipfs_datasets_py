"""LexJuris PR municipal ordinances (www.lexjuris.com/ordenanzas/). robots.txt 404 -> allowed (RFC 9309); 3 s delay.
Rows: country_code from the place row (US; GNIS key) per Normalizer option 1; staged to staging/afme/US by afme_stage.py REDIRECT.
usage: afme_pr_lexjuris.py <outdir> [max_places] [max_docs]
Checkpoint: skips places with a lexjuris file in outdir OR already staged as a PR src in staging/afme/_logs manifests (rebuilt 2026-10-16 after reboot).
Stops before a place if /workspace free < 35 GB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,time,subprocess,datetime,unicodedata,urllib.request,urllib.parse,glob,shutil
from bs4 import BeautifulSoup as B
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import place_key, validate_file
UA="world-municipal-law-research/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law)"
OUT=sys.argv[1]; MAXP=int(sys.argv[2]) if len(sys.argv)>2 else 0; MAXD=int(sys.argv[3]) if len(sys.argv)>3 else 0
os.makedirs(OUT,exist_ok=True); last=[0]
DONE=set()
for m in glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/afme/_logs/staged_*.json")):
    for f in json.load(open(m)).get("files",[]):
        if "/afme/PR/" in f["src"] and ".lexjuris" in f["src"]: DONE.add(os.path.basename(f["src"]).split(".")[0])
def get(u):
    for i in range(3):
        w=3-(time.time()-last[0]); time.sleep(max(0,w)); last[0]=time.time()
        try:
            r=urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u,safe=":/?=&%#"),headers={"User-Agent":UA}),timeout=60); return r.read(),r.headers.get("Content-Type","")
        except urllib.error.HTTPError as e:
            if e.code in (403,404,410): raise
            time.sleep(10)
        except Exception: time.sleep(10)
    raise RuntimeError("fail "+u)
def fold(s): return re.sub(r"[^a-z]","",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower())
def fixm(n):
    try: return n.encode("latin-1").decode("utf-8")
    except Exception: return n
P={}
for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))):
    if r.get("state_code")=="PR" and r["admin_level"]=="county":
        r["place_name"]=fixm(r["place_name"]); P[fold(re.sub(r"(?i)\s*municipio$","",r["place_name"]))]=r
idx=B(get("https://www.lexjuris.com/ordenanzas/index.htm")[0],"html.parser"); muni=[]; seenm=set()
for a in idx.find_all("a",href=True):
    h=urllib.parse.urljoin("https://www.lexjuris.com/ordenanzas/index.htm",a["href"])
    if re.search(r"/ordenanzas/[^/]+/[^/]+\.htm",h):
        k=fold(a.get_text()); seg=fold(urllib.parse.unquote(h.split("/ordenanzas/")[1].split("/")[0]))
        p=P.get(k) or P.get(seg) or next((v for kk,v in P.items() if kk.startswith(seg) and len(seg)>=4),None)
        if (seg,h) in seenm: continue
        seenm.add((seg,h)); muni.append((p,h,seg))
print("munis",len(muni),"mapped",sum(1 for m in muni if m[0]),"already_done",len(DONE),flush=True)
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); rep=[]; n=0
for p,ih,seg in muni:
    if not p: rep.append({"seg":seg,"status":"unmapped"}); continue
    key=place_key(p['place_id'],p.get('gnis'),p['country_code'])
    if key in DONE or glob.glob(f"{OUT}/{key}.lexjuris*.jsonl"): continue
    if shutil.disk_usage("/workspace").free < 35*2**30: print("STOP disk floor 35 GB",flush=True); break
    if MAXP and n>=MAXP: break
    n+=1; base=ih.rsplit("/",1)[0]+"/"; seen={ih}; queue=[ih]; docs=[]; subfail=[]
    print("place",p["place_name"],flush=True)
    try:
        while queue and len(seen)<400:
            u=queue.pop(0)
            try: s=B(get(u)[0],"html.parser")
            except Exception as e:
                if u==ih: raise
                subfail.append(u); continue
            for a in s.find_all("a",href=True):
                h=urllib.parse.urljoin(u,a["href"]).split("#")[0]
                if not urllib.parse.unquote(h).startswith(urllib.parse.unquote(base)) or h in seen: continue
                seen.add(h)
                if re.search(r"(?i)indice|index",h) and h.lower().endswith(".htm"): queue.append(h)
                elif re.search(r"(?i)\.(htm|html|pdf)$",h): docs.append((h,a.get_text(" ",strip=True)))
    except Exception as e: rep.append({"place":p["place_name"],"status":"index_fail","err":repr(e)[:120]}); print(rep[-1],flush=True); continue
    rows=[]; fails=0
    for h,lt in docs[:(MAXD or None)]:
        try:
            b,ct=get(h)
            if b[:5]==b"%PDF-":
                pf=f"/tmp/afme_lj_{os.getpid()}.pdf"; open(pf,"wb").write(b); text=subprocess.run(["pdftotext","-layout",pf,"-"],capture_output=True,text=True).stdout; html=None; fmt="pdf_text"; title=lt or h.rsplit("/",1)[-1]
            else:
                s=B(b,"html.parser")
                for t in s(["script","style","nav","header","footer","noscript","form"]): t.decompose()
                title=lt or (s.title.get_text(strip=True) if s.title else h); m=s.body or s
                text=m.get_text("\n",strip=True); html=f'<div class="chunk-content">{m.decode_contents()}</div>'; fmt="html"
            rec=dict(place_id=p["place_id"],country_code=p["country_code"],doc_id=re.sub(r"^https?://(www\.)?","",h),source_platform="lexjuris.com",source_url=h,
              doc_type="ordinance",language="es",title_native=(title or h)[:500],consolidated=False,in_force=None,content_format=fmt,
              retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),source_policy="live_robots_absent_allowed",source_official=False,
              source_org="LexJuris de Puerto Rico",place_name=p["place_name"],qid=p["qid"],admin_level=p["admin_level"],platform="lexjuris.com",platform_place_id=seg,
              extra_metadata={"index_url":ih,"territory":"PR"})
            y=re.search(r"(19|20)\d\d",title or "")
            if y: rec["adopted_date"]=y.group(0)
            if html: rec["html"]=html
            rec["text"]=text
            if len(text.strip())<200: rec["content_complete"]=False; rec["extra_metadata"]["note"]="insufficient text; OCR needed"
            rows.append(rec)
        except Exception: fails+=1
    if not rows: rep.append({"place":p["place_name"],"status":"FAIL","docs_found":len(docs)}); print(rep[-1],flush=True); continue
    f=f"{OUT}/{key}.lexjuris{ts}p0001.jsonl"
    with open(f+".tmp","w") as o:
        for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f); v=validate_file(f)
    rep.append({"place_id":p["place_id"],"name":p["place_name"],"docs":len(rows),"fails":fails,"subindex_404":len(subfail),"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1],ensure_ascii=False),flush=True)
json.dump(rep,open(f"{OUT}/_report_lexjuris_{ts}.json","w"),indent=1,ensure_ascii=False)
print("DONE",sum(r.get("ok",False) for r in rep),"/",sum(1 for r in rep if "ok" in r or r.get("status")=="FAIL"),flush=True)
