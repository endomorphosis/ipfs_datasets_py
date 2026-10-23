"""AU state gazette council local-law crawler (wave 9). usage: afme_aus_gaz.py vic|wa <years e.g. 2010-2026> [max_issues|0] [test]
VIC: www.gazette.vic.gov.au General gazettes GG{Y}G{NNN}.pdf (robots: Allow /), notices under LGA 1989 s119 / LGA 2020 s74 (making/amending/revoking a
local law; proposed-law notices skipped). WA: legislation.wa.gov.au gazette PDFs (robots 404 = allow; content CC BY 4.0), local laws under the Local
Government Act 1995 published in full. Council local laws only: blocks must name a council that maps to an AU council place row; LEP/SEPP/planning-scheme
and non-council (state authority) instruments dropped. >=3 s per host. Checkpoint per issue (_gaz_<st>_done.tsv); per-place files rewritten atomically."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,os,re,json,time,datetime,csv,subprocess,tempfile,shutil,unicodedata
import requests
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key
from rfc9309 import Robots
UA="JusticeDAO-WorldLaw/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; municipal law research)"
ST=sys.argv[1]; Y0,Y1=map(int,sys.argv[2].split("-")); MAXI=int(sys.argv[3]) if len(sys.argv)>3 else 0; TEST=len(sys.argv)>4
OUT=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/AU"); os.makedirs(OUT,exist_ok=True); BATCH=f"gaz_{ST}_20261018"+(".test" if TEST else "")
DONE=f"{OUT}/_gaz_{ST}_done{'_test' if TEST else ''}.tsv"; done={l.split("\t")[0] for l in open(DONE)} if os.path.exists(DONE) else set()
S=requests.Session(); S.headers["User-Agent"]=UA; _last=[0.0]; DELAY=3.0
HOST={"vic":"https://www.gazette.vic.gov.au","wa":"https://www.legislation.wa.gov.au"}[ST]
rb=S.get(HOST+"/robots.txt",timeout=30)
if rb.status_code==200 and "text/plain" in rb.headers.get("content-type",""): R=Robots(rb.text); POL="robots_allowed_rfc9309"; DELAY=max(3.0,float(R.crawl_delay(UA) or 0))
elif rb.status_code in (404,410): R=Robots(allow_all=True); POL="robots_404_allow_rfc9309"
else: print("robots unavailable",rb.status_code); sys.exit(5)
def get(u):
    if not R.can_fetch(UA,u): return None
    for att in range(3):
        w=DELAY-(time.time()-_last[0]); 
        if w>0: time.sleep(w)
        _last[0]=time.time()
        try: r=S.get(u,timeout=120)
        except Exception: time.sleep(20*(att+1)); continue
        if r.status_code==429 or r.status_code>=500: time.sleep(60*(att+1)); continue
        return r
    return None
def fold(s): return re.sub(r"[^a-z0-9 ]+"," ",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()).split()
SUF={"vic":".vic.gov.au","wa":".wa.gov.au"}[ST]
OTHER=[x for x in (".nsw.gov.au",".vic.gov.au",".qld.gov.au",".wa.gov.au",".sa.gov.au",".tas.gov.au",".nt.gov.au") if x!=SUF]
places=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]=="AU" and r["admin_level"]=="municipality" and not any(o in r["source_url"] for o in OTHER)]
ALIAS={}
for p in places:
    n=p["place_name"]; base=re.sub(r"^(Shire|City|Town|Rural City|Borough|Municipality) of\s+","",n); base=re.sub(r"\s+(Shire|City|Region)$","",base)
    kind=re.match(r"^(Shire|City|Town|Rural City|Borough)",n); kind=kind.group(1) if kind else ("Shire" if n.endswith("Shire") else "City" if n.endswith("City") else "")
    for v in {n,f"{kind} of {base}",f"{base} {kind} Council",f"{base} {kind}",f"{base} Council" if kind else n}:
        ALIAS[" ".join(fold(v))]=p
    h=re.sub(r"^https?://(www\.)?","",p["source_url"]).split("/")[0].lower()
    ALIAS["host:"+h]=p
def _name(txt):
    f=" "+" ".join(fold(txt))+" "; best=None
    for k,p in ALIAS.items():
        if k.startswith("host:") or len(k.split())<2: continue
        if " "+k+" " in f and (best is None or len(k)>len(best[0])): best=(k,p)
    return best[1] if best else None
def mapc(block):
    p=_name(block[:800])
    if p: return p
    for h in re.findall(r"(?i)\b(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*"+re.escape(SUF)+r")",block): 
        if "host:"+h.lower() in ALIAS: return ALIAS["host:"+h.lower()]
    f=" "+" ".join(fold(block[:3000]))+" "
    best=None
    for k,p in ALIAS.items():
        if k.startswith("host:"): continue
        if " "+k+" " in f and (best is None or len(k)>len(best[0])): best=(k,p)
    return best[1] if best else None
BAD=re.compile(r"(?i)local\s+environmental\s+plan|\bLEP\b|state\s+environmental\s+planning|\bSEPP\b|planning\s+scheme|town\s+planning\s+scheme")
def pdftext(b,layout):
    with tempfile.NamedTemporaryFile(suffix=".pdf",dir=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme")) as f:
        f.write(b); f.flush()
        try: return subprocess.run(["pdftotext"]+(["-layout"] if layout else [])+[f.name,"-"],capture_output=True,timeout=300).stdout.decode("utf8","replace")
        except Exception: return ""
def clean(lines):
    return [l for l in lines if not re.match(r"(?i)^\s*(\d{1,5}\s+)?(G\s*\d+\s+)?(\d{1,2}\s+\w+\s+\d{4}\s+)?(Victoria Government Gazette|GOVERNMENT GAZETTE, WA)(\s+\d+)?\s*$",l) and not re.fullmatch(r"\s*(G\s*\d+|\d{1,5}|\d{1,2} \w+ \d{4})\s*",l) and not re.fullmatch(r"\s*(\d+\s+GOVERNMENT GAZETTE, WA\s+\d{1,2} \w+ \d{4}|\d{1,2} \w+ \d{4}\s+GOVERNMENT GAZETTE, WA\s+\d+)\s*",l)]
def seg_vic(txt):
    L=clean(txt.split("\n")); out=[]; i=0
    while i<len(L):
        l=L[i].strip()
        if len(l)>=10 and l==l.upper() and re.search(r"LOCAL\s+LAWS?",l) and re.search(r"[A-Z]{3}",l):
            blk=[l]; j=i+1
            while j<len(L) and j<i+160:
                m=L[j].strip()
                nx=next((x.strip() for x in L[j+1:j+4] if x.strip()),"")
                if len(blk)>3 and ((len(m)>=10 and m==m.upper() and re.search(r"[A-Z]{4}",m) and not re.search(r"LOCAL\s+LAW",m) and (re.match(r"^(NOTICE|[A-Z ]+ ACT \d{4})",m) or re.match(r"(?i)^(notice|pursuant|under|in accordance|at its|take notice|section|council|the\s)",nx))) or re.fullmatch(r"[A-Z][a-z]+(?: (?:and|of|[A-Z][a-z]+))* Act \d{4}",m)): break
                blk.append(L[j]); j+=1
                if re.fullmatch(r"(?i)\s*(acting\s+|interim\s+)?(chief\s+executive\s+officer|ceo)\s*",L[j-1]) : break
            b="\n".join(blk).strip()
            if not re.search(r"(?i)propos|intention|submissions?\s+(may|are)|have your say",b[:600]) and re.search(r"(?i)(made|make|resolved|amend|revok|adopt)",b):
                out.append((l,b))
            i=j
        else: i+=1
    return out
def seg_wa(txt):
    L=clean(txt.split("\n")); out=[]; starts=[]
    for i,l in enumerate(L):
        if re.fullmatch(r"\s*LOCAL GOVERNMENT ACT 1995\s*",l):
            win=[x.strip() for x in L[i+1:i+14] if x.strip()]
            co=next((x for x in win[:6] if re.fullmatch(r"(SHIRE|CITY|TOWN|MUNICIPALITY) OF [A-Z][A-Z \-’']+",x)),None)
            ti=next((k for k,x in enumerate(win[:9]) if re.search(r"LOCAL LAWS?",x) and x==x.upper()),None)
            body=" ".join(win)
            if co and ti is not None and re.search(r"(?i)under the powers|resolved on|resolved to make|in pursuance",body):
                t=win[ti]+(" "+win[ti+1] if ti+1<len(win) and re.fullmatch(r"\d{4}",win[ti+1]) else "")
                starts.append((i,co,t))
    for k,(i,co,t) in enumerate(starts):
        e=starts[k+1][0] if k+1<len(starts) else len(L)
        for j in range(i+5,e):
            if re.fullmatch(r"\s*[A-Z]{2,3}\d{3}\*?\s*",L[j]): e=j; break
        out.append((f"{co} — {t}","\n".join(L[i:e]).strip()))
    return out
def issues():
    for y in range(Y1,Y0-1,-1):
        if ST=="vic":
            miss=0
            for n in range(1,60):
                u=f"{HOST}/gazette/Gazettes{y}/GG{y}G{n:03d}.pdf"; yield (u,y,f"G{n}",None)
        else:
            r=get(f"{HOST}/legislation/statutes.nsf/gazettes{y}.html")
            if r is None or r.status_code!=200: continue
            for m in re.finditer(r"<td>\s*(\d{1,2} \w{3} \d{4})\s*</td>\s*<td>\s*(\d+)\s*</td>.*?query=(gg\d{4}_\d+\.pdf)",r.text,re.S):
                yield (f"{HOST}/legislation/statutes.nsf/RedirectURL?OpenAgent&query={m.group(3)}",y,"No. "+m.group(2),m.group(1))
rows_by={}; stats={"issues":0,"blocks":0,"mapped":0,"bad_title":0}
def flush(key,recs):
    f=f"{OUT}/{key}.{BATCH}.jsonl"; old=[json.loads(l) for l in open(f)] if os.path.exists(f) else []
    ids={r["doc_id"] for r in recs}; allr=[r for r in old if r["doc_id"] not in ids]+recs
    with open(f+".tmp","w") as o:
        for r in allr: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f)
vmiss=0; lasty=None
for u,y,no,dt in issues():
    if MAXI and stats["issues"]>=MAXI: break
    if ST=="vic" and y!=lasty: vmiss=0; lasty=y
    if ST=="vic" and vmiss>=2: continue
    if u in done: continue
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor"); sys.exit(3)
    r=get(u)
    if r is None or r.status_code!=200 or r.content[:4]!=b"%PDF":
        if ST=="vic": vmiss+=1
        open(DONE,"a").write(f"{u}\tmiss\n") if (r is not None and r.status_code==404 and y<datetime.date.today().year) else None; continue
    vmiss=0; stats["issues"]+=1
    txt=pdftext(r.content,ST=="wa")
    if ST=="vic" and not dt:
        m=re.search(r"\b(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4})\b",txt[:3000]); dt=m.group(1) if m else None
    pub=datetime.datetime.strptime(dt,"%d %B %Y" if ST=="vic" else "%d %b %Y").strftime("%Y-%m-%d") if dt else None
    per={}
    for k,(head,blk) in enumerate(seg_vic(txt) if ST=="vic" else seg_wa(txt)):
        stats["blocks"]+=1
        if BAD.search(head) or BAD.search(blk[:400]): stats["bad_title"]+=1; continue
        p=mapc(blk)
        if p is None: continue
        stats["mapped"]+=1; key=place_key(p["place_id"],None,"AU")
        laws=re.findall(r"([A-Z][\w()’' ,&-]{3,90}?\s(?:\(Amendment\)\s)?Local\s+Laws?(?:\s+No\.?\s*\d+)?(?:\s+\d{4})?)",blk) if ST=="vic" else []
        t=" ".join(head.split()).title() if ST=="vic" else " ".join(head.split())
        gz="Victoria Government Gazette" if ST=="vic" else "Western Australian Government Gazette"
        title=f"{t} — {p['place_name']} ({gz} {no}, {dt or y})"
        src=r.url if ST=="wa" else u
        rec=dict(place_id=p["place_id"],country_code="AU",doc_id=re.sub(r"^https?://(www\.)?","",u).lower()+f"#ll{k+1}",source_platform=f"au_{ST}_government_gazette",source_url=src,
            doc_type="gazette_act",language="en",title_native=title[:500],number=None,published_date=pub,consolidated=False,in_force=None,content_format="pdf_text",
            text=blk,retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),content_complete=True,source_policy=POL,source_official=True,
            source_org=gz+(" (State of Western Australia, CC BY 4.0)" if ST=="wa" else " (State of Victoria)"),license_note="CC BY 4.0, © State of Western Australia" if ST=="wa" else None,
            place_name=p["place_name"],qid=p["qid"],admin_level="municipality",state_code=ST.upper(),platform=f"au_{ST}_government_gazette",platform_place_id=p["place_name"],
            extra_metadata={"gazette_issue":no,"gazette_date":dt,"block_index":k+1,"notice_heading":head[:300],"kind":"local law notice (s74 LGA 2020 / s119 LGA 1989)" if ST=="vic" else "local law text (LGA 1995 Part 3)","crawl_delay_s":DELAY})
        per.setdefault(key,[]).append(rec)
    for key,recs in per.items(): flush(key,recs)
    open(DONE,"a").write(f"{u}\tok\t{sum(len(v) for v in per.values())}\n")
    print(u,{k:len(v) for k,v in per.items()},flush=True)
print(json.dumps(stats),"DONE",flush=True)
