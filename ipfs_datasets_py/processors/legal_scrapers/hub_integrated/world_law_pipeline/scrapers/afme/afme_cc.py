"""afme Common Crawl harvester (rebuilt 2026-10-16 after reboot). Reads _cdx_<CC>.jsonl from afme_ccidx.py (slim-loaded),
maps captures to places, range-fetches WARC records from data.commoncrawl.org, writes schema rows per place, validate_file each.
Mapping (cfg.map): "host"  = capture host == official-site host of a place (candidate CSV source_url) or host slug == folded place name/label
                   "title" = a place name/label (Wikidata, cfg.label_langs) appears in the doc title AND title matches cfg.title_legal_regex; unique longest
                   "host,title" = host first, then title.  Laws.Africa hosts in cfg.content_signal_hosts get source_policy content_signal_ai_train_no.
usage: afme_cc.py cfg.json <max_places|0> <max_docs|0> [test]   checkpoint: skips places having <placekey>.*cc*.jsonl in the outdir."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,gzip,glob,subprocess,datetime,unicodedata,urllib.request,time,collections,shutil
from bs4 import BeautifulSoup as B
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import place_key, validate_file
UA="world-municipal-law-research/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law)"
cfg=json.load(open(sys.argv[1])); MAXP=int(sys.argv[2]); MAXD=int(sys.argv[3]); TEST=len(sys.argv)>4
CC=cfg["cc"]; BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); OUT=f"{BASE}/_test/{CC}{cfg.get('suffix','')}" if TEST else f"{BASE}/{CC}"; os.makedirs(OUT,exist_ok=True)
BATCH=cfg.get("batch","cc"); CDX=cfg.get("cdx",f"{BASE}/_probe/{CC}/_cdx_{CC}.jsonl")
last=[0.0]
def get(url,rng):
    d=5
    for i in range(5):
        w=0.5-(time.time()-last[0]); time.sleep(max(0,w)); last[0]=time.time()
        try: return urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA,"Range":rng}),timeout=120).read()
        except Exception: time.sleep(d); d*=2
    raise RuntimeError("warc fetch failed")
def fold(s): return re.sub(r"[^\w]+"," ",unicodedata.normalize("NFKD",s or "").encode("ascii","ignore").decode().lower()).strip() if re.search(r"[A-Za-z]",s or "") else re.sub(r"[^\w]+"," ",(s or "").lower()).strip()
def host(u): return re.sub(r"^www\d?\.","",(re.match(r"https?://([^/:]+)",u) or [None,""])[1].lower())
GEN=set(cfg.get("generic_words",["district","municipality","municipal","council","city","town","region","governorate","province","county","of","the","urban","rural","local","government","emirate","commune","municipalite","province","prefecture"]))
places=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]==CC]
labs={}
lf=f"{BASE}/_labels/{CC}.jsonl"
if os.path.exists(lf):
    for l in open(lf): x=json.loads(l); labs[x["qid"]]=x
DONE_LEDGER=set()
for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/confirmed_batches/afme.jsonl")):
    x=json.loads(l)
    if x["cc"]==CC: DONE_LEDGER.add(x["place_key"])
hostmap={}; names=collections.defaultdict(set)   # name -> place idx
for i,p in enumerate(places):
    h=host(p.get("source_url") or "")
    if h and not re.search(r"globaldatalab|elevationmap|wikipedia|wikidata|citypopulation|geonames|parliament|statehouse|mlhud|molg|ministry|facebook|twitter|blogspot|wordpress\.com|google",h) and h.count(".")>=2-(1 if not re.search(r"\.(gov|go|co|org|com|ac)\.[a-z]{2}$",h) else 0): hostmap.setdefault(h,[]).append(i)
    ns={p["place_name"]}
    L=labs.get(p["qid"],{})
    for lg in cfg.get("label_langs",["en"]):
        if L.get("labels",{}).get(lg): ns.add(L["labels"][lg])
        ns|=set(L.get("aliases",{}).get(lg,[]))
    for n in ns:
        w=[x for x in fold(n).split() if x not in GEN]
        if w and len(" ".join(w))>=4: names[" ".join(w)].add(i)
hostmap={h:v[0] for h,v in hostmap.items() if len(v)==1}
for hh,pid in cfg.get("host_alias",{}).items():   # curated official host -> place (e.g. mupa.gob.pa -> Panamá District); subdomains match via endswith
    ii=[i for i,p in enumerate(places) if p["place_id"]==pid]
    if ii: hostmap[hh]=ii[0]
STRIP=re.compile(cfg.get("slug_strip","^(www)"))
def by_host(h):
    h=re.sub(r"^(mail|webmail|web|portal|en|ar|fr)\.","",h)
    if h in hostmap: return hostmap[h]
    for hh,i in hostmap.items():
        if h.endswith("."+hh): return i
    if cfg.get("host_slug",True):
        sl=STRIP.sub("",h.split(".")[0]); sl=re.sub(cfg.get("slug_suffix_strip","(mc|dc|cc|tc|municipal|council|district|city|town|lga)+$"),"",sl)
        if len(sl)>=4:
            c=[i for n,ii in names.items() for i in ii if n.replace(" ","")==sl]
            if len(set(c))==1: return c[0]
    return None
LEG=re.compile(cfg.get("title_legal_regex","(?i)by-?laws?|regulations?|order|ordinance|decree|resolution|قرار|لائحة|arr[eê]t[eé]"),re.I)
def by_title(t):
    if not t or not LEG.search(t): return None
    ft=" "+fold(t)+" "; hits={}
    for n,ii in names.items():
        if " "+n+" " in ft:
            for i in ii: hits[i]=max(hits.get(i,0),len(n))
    if not hits: return None
    top=max(hits.values()); c=[i for i,v in hits.items() if v==top]
    return c[0] if len(c)==1 else None
MODES=cfg.get("map","host").split(",")
DOCRX=re.compile(cfg.get("doc_url_regex",".")); EXC=re.compile(cfg.get("exclude_regex","$^"))
KEEP=("url","mime","mime-detected","length","offset","filename","timestamp","crawl")
groups=collections.defaultdict(list); pending_title=[]; unm=collections.Counter()
for l in open(CDX):
    x=json.loads(l); u=x["url"]
    if not DOCRX.search(u) or EXC.search(u): continue
    x={k:x.get(k) for k in KEEP}; i=by_host(host(u)) if "host" in MODES else None
    if i is not None: groups[i].append(x)
    elif "title" in MODES: pending_title.append(x)
    else: unm[host(u)]+=1
print("cdx host-mapped places",len(groups),"title-candidates",len(pending_title),flush=True)
def parse(x,body):
    if (x.get("mime-detected") or x.get("mime") or "").endswith("pdf") or body[:5]==b"%PDF-":
        pf=f"/tmp/afme_cc_{os.getpid()}.pdf"; open(pf,"wb").write(body)
        t=subprocess.run(["pdftotext","-layout",pf,"-"],capture_output=True,text=True,timeout=120).stdout
        m=re.search(r"\S.{10,200}",t); return "pdf_text",None,t,(m.group(0).strip() if m else x["url"].rsplit("/",1)[-1] or x["url"]),len(body)
    s=B(body,"html.parser")
    for t in s(["script","style","nav","header","footer","noscript","form","aside"]): t.decompose()
    og=s.find("meta",attrs={"property":"og:title"})
    title=((og.get("content") or "").strip() if og else "") or (s.h1.get_text(" ",strip=True) if s.h1 else "") or (s.title.get_text(" ",strip=True) if s.title else "") or x["url"]
    main=None
    for sel in cfg.get("content_selectors",[])+["article","main","#content",".content","body"]:
        main=s.select_one(sel)
        if main and len(main.get_text(strip=True))>200: break
    main=main or s
    return "html",f'<div class="chunk-content">{main.decode_contents()}</div>',main.get_text("\n",strip=True),title,len(body)
def fetch(x):
    b=get(f"https://data.commoncrawl.org/{x['filename']}",f"bytes={x['offset']}-{int(x['offset'])+int(x['length'])-1}")
    raw=gzip.decompress(b); parts=raw.split(b"\r\n\r\n",2); return parse(x,parts[2] if len(parts)>2 else b"")
fetched={}
if "title" in MODES and pending_title:   # title mapping needs the record: fetch (capped) and map
    cap=int(cfg.get("title_fetch_cap",3000)); cap=min(cap,200) if TEST else cap
    for x in pending_title[:cap]:
        try: r=fetch(x)
        except Exception: continue
        i=by_title(r[3])
        if i is not None: groups[i].append(x); fetched[x["url"]]=r
        else: unm[host(x["url"])]+=1
    print("title-mapped places total",len(groups),flush=True)
json.dump(unm.most_common(300),open(f"{OUT}/_unmapped_{CC}.json","w"))
CS=set(cfg.get("content_signal_hosts",[])); CSRAW=cfg.get("content_signal_raw","Content-Signal: ai-train=no, search=yes, ai-input=no")
EXDOC=set()
if cfg.get("exclude_doc_ids_file"):
    for l in open(cfg["exclude_doc_ids_file"]):
        if "\t" in l: k,d=l.rstrip("\n").split("\t",1); EXDOC.add((k,d))
order=sorted(groups.items(),key=lambda g:-len(g[1]))
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); rep=[]; np_=0
for i,xs in order:
    p=places[i]; key=place_key(p["place_id"],p.get("gnis"),CC)
    if cfg.get("only_place_ids") and p["place_id"] not in cfg["only_place_ids"]: continue
    if key in DONE_LEDGER and not cfg.get("allow_ledger_places"): continue
    if glob.glob(f"{OUT}/{key}.*{BATCH}2*.jsonl"): continue
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor",flush=True); break
    if MAXP and np_>=MAXP: break
    np_+=1; rows=[]; fails=0; inc=0
    xs=[x for x in xs if (key,re.sub(r"^https?://(www\.)?","",x["url"]).rstrip("/")) not in EXDOC]   # already-confirmed docs (add-on batches)
    for x in sorted(xs,key=lambda x:x["url"])[:(MAXD or None)]:
        try:
            fmt,html,text,title,blen=fetched.get(x["url"]) or fetch(x)
            if re.search(r"(?i)^(one moment|just a moment|attention required|access denied|403 forbidden|404|page not found)",title.strip()): raise RuntimeError("challenge/error page")
            u=x["url"]; h=host(u); cs=h in CS or any(h.endswith("."+c) for c in CS)
            rec=dict(place_id=p["place_id"],country_code=CC,doc_id=re.sub(r"^https?://(www\.)?","",u).rstrip("/"),source_platform=cfg["platform"],source_url=u,
              doc_type=cfg.get("doc_type","ordinance"),language=cfg["language"],title_native=(title or u)[:500],consolidated=False,in_force=None,content_format=fmt,
              retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),archive_source="commoncrawl",archive_crawl_id=x["crawl"],
              archive_timestamp=x["timestamp"],archive_url=f"https://data.commoncrawl.org/{x['filename']}",original_url=u,
              source_policy=("content_signal_ai_train_no" if cs else "archived_commoncrawl"),source_official=(not cs) and not any(h==x or h.endswith('.'+x) for x in cfg.get('unofficial_hosts',[])),source_org=(h if cs else p["place_name"]),
              place_name=p["place_name"],qid=p["qid"],admin_level=p["admin_level"],platform=cfg["platform"],platform_place_id=h,
              extra_metadata={"archive":{"warc_filename":x["filename"],"warc_offset":x["offset"],"warc_length":x["length"]},"mapping":("host" if i in groups and by_host(h)==i else "title")})
            if cs: rec["extra_metadata"]["source_policy_raw"]=CSRAW; rec["source_policy_raw"]=CSRAW
            rd=next((v for k,v in cfg.get("robots_disallow_hosts",{}).items() if h==k or h.endswith("."+k)),None)
            if rd: rec["source_policy"]="archived_robots_disallowed"; rec["source_policy_raw"]=rd; rec["extra_metadata"]["source_policy_raw"]=rd; rec["source_official"]=False
            y=re.search(r"(19|20)\d\d",title or "")
            if y: rec["adopted_date"]=y.group(0)
            if html: rec["html"]=html
            rec["text"]=text
            tl=len((text or "").strip())
            if tl<(500 if fmt=="html" else 200) or (fmt=="pdf_text" and tl<blen/20000):
                rec["content_complete"]=False; rec["extra_metadata"]["note"]="no/insufficient text layer (scan or stub); raw PDF / re-fetch needed"; inc+=1
            rows.append(rec)
        except Exception as e: fails+=1
    if not rows: rep.append({"place_id":p["place_id"],"name":p["place_name"],"status":"FAIL","why":"no docs"}); print(json.dumps(rep[-1]),flush=True); continue
    f=f"{OUT}/{key}.{'full.' if not MAXD else ''}{BATCH}{ts}p0001.jsonl"
    with open(f+".tmp","w") as o:
        for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f); v=validate_file(f)
    rep.append({"place_id":p["place_id"],"name":p["place_name"],"docs":len(rows),"incomplete":inc,"fails":fails,"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1],ensure_ascii=False),flush=True)
json.dump(rep,open(f"{OUT}/_report_{ts}.json","w"),indent=1,ensure_ascii=False)
print("DONE",sum(r.get("ok",False) for r in rep),"/",len(rep),flush=True)
