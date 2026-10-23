"""Offline remap of CR La Gaceta cached items (afme/_cr_gaceta/*.json, no fetches). Repairs headings split around accented capitals ("PO Á S"→"POÁS") and latin1/utf8
mojibake ("Ã"), then does an accent-insensitive longest-prefix match against candidate names plus Wikidata es/en labels. It writes files only for cantons that have no CR gaceta file
yet and are not in the confirmed ledger. Batch name 'gaceta' (same as the main run), new timestamp."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,glob,datetime,unicodedata,collections,html as H
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import place_key, validate_file
BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); OUT=f"{BASE}/CR"
def fold(s): return re.sub(r"[^a-z0-9]+"," ",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()).strip()
def demoji(s):
    if re.search(r"Ã|Â",s):
        try: return s.encode("latin1").decode("utf8")
        except Exception: pass
    return s
def glue(s): return re.sub(r"(?<=[A-ZÑ]) ?([ÁÉÍÓÚÜÑ]) ?(?=[A-ZÑ])|(?<=[A-ZÑ]) ([ÁÉÍÓÚÜ])(?=\b)",lambda m:m.group(1) or m.group(2),s)
places=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]=="CR" and r["admin_level"]=="municipality"]
LED={json.loads(l)["place_key"] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/confirmed_batches/afme.jsonl")) if json.loads(l)["cc"]=="CR"}
nm=collections.defaultdict(set); byq={p["qid"]:p for p in places}; byp={p["place_id"]:p for p in places}
for p in places:
    for n in {p["place_name"],re.sub(r"(?i)^(cant[oó]n de |municipalidad de )","",p["place_name"]),re.sub(r"(?i) canton$","",p["place_name"])}: nm[fold(n)].add(p["place_id"])
for l in open(f"{BASE}/_labels/CR.jsonl"):
    x=json.loads(l); p=byq.get(x["qid"])
    if p:
        for v in [x["labels"].get(k) for k in ("es","en")]+x.get("aliases",{}).get("es",[])+x.get("aliases",{}).get("en",[]):
            if v: nm[fold(re.sub(r"(?i)^(cant[oó]n de |cant[oó]n |municipalidad de )|( canton)$","",v))].add(p["place_id"])
ADDON=len(sys.argv)>1 and sys.argv[1]=="addon"
have={os.path.basename(f).split(".")[0] for f in glob.glob(f"{OUT}/*.gaceta2*.jsonl")}
HEAD=re.compile(r"^(MUNICIPALIDAD DE|CONCEJO MUNICIPAL DE DISTRITO DE)\s+((?:[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\.\-]*\s?){1,6})")
per=collections.defaultdict(list); st=collections.Counter(); still=collections.Counter(); ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
DELAY=5.0
for cf in sorted(glob.glob(f"{BASE}/_cr_gaceta/*.json")):
    x=json.load(open(cf))
    for it in x["items"]:
        old=nm.get(fold(it["name"]),set())
        if len(old)==1: continue          # mapped in the main run already
        b=demoji(it["body"]); hb=glue(b[:160]); h=HEAD.match(hb)
        if not h: still[it["name"]]+=1; continue
        g=fold(hb[h.start(2):]).replace(" ",""); best=None
        for n,c in nm.items():
            nn=n.replace(" ","")
            if len(nn)>=3 and g.startswith(nn) and (best is None or len(nn)>len(best[0])): best=(nn,c)
        pid=(next(iter(best[1])) if best and len(best[1])==1 else None)
        if not pid: still[g[:24]]+=1; continue
        p=byp[pid]; key=place_key(pid,None,"CR")
        if ADDON and key not in LED: st["not_ledger_skip"]+=1; continue
        if not ADDON and key in LED: st["ledger_skip"]+=1; continue
        if not ADDON and key in have: st["has_file_skip"]+=1; continue
        name=glue(h.group(2)).strip(); kind=h.group(1)
        m=re.search(r"(REGLAMENTO|ACUERDO|REFORMA|TARIFA|PLAN REGULADOR|ORDENANZA|MANUAL|POL[ÍI]TICA)[^.]{0,200}",b,re.I)
        title=(f"{kind.title()} {p['place_name'].replace(' Canton','')}: "+(m.group(0) if m else b[len(hb[:h.end()]):][:200])).strip()[:500]
        per[key].append(dict(place_id=pid,country_code="CR",doc_id=f"imprentanacional.go.cr/gaceta/{x['date']}/{it['code'] or abs(hash(b))%10**10}",source_platform="cr_la_gaceta",source_url=x["url"],
            doc_type="gazette_act",language="es",title_native=title,published_date=x["date"],consolidated=False,in_force=None,content_format="html",
            html=f'<div class="chunk-content"><p>{H.escape(b)}</p></div>',text=b,retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            source_policy="robots_allowed_rfc9309",source_official=True,source_org="Imprenta Nacional de Costa Rica - La Gaceta",place_name=p["place_name"],qid=p["qid"],
            admin_level=p["admin_level"],platform="cr_la_gaceta",platform_place_id=name,
            extra_metadata={"gazette_pdf":x["pdf"],"publication_code":it["code"],"issuer_heading":f"{kind} {name}","crawl_delay_s":DELAY,"remap":"accent-glue/mojibake offline remap "+ts}))
CONF=collections.defaultdict(list)
for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/confirmed_batches/afme.jsonl")):
    x=json.loads(l)
    if x["cc"]=="CR": CONF[x["place_key"]].append(x["rel"])
miss=[]
rep=[]
for key,rows in per.items():
    ex=set()
    for f in set(glob.glob(f"{OUT}/{key}.*.jsonl"))|{(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/")+r for r in CONF.get(key,[])}:
        if not os.path.exists(f): miss.append(f); continue
        for l in open(f): ex.add(json.loads(l)["doc_id"])
    n0=len(rows); rows=[r for r in rows if r["doc_id"] not in ex]; st["dropped_existing_docid"]+=n0-len(rows)
    if not rows: continue
    seen=set(); rows=[r for r in rows if not (r["doc_id"] in seen or seen.add(r["doc_id"]))]
    f=f"{OUT}/{key}.gaceta{ts}p0001.jsonl"
    with open(f+".tmp","w") as o:
        for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f); v=validate_file(f); rep.append({"key":key,"place":rows[0]["place_name"],"rows":len(rows),"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1],ensure_ascii=False))
print("missing_confirmed_files",sorted(set(miss)))
print("DONE ok",sum(r["ok"] for r in rep),"bad",sum(not r["ok"] for r in rep),"files",len(rep),"rows",sum(r["rows"] for r in rep),dict(st),"still_unmapped",still.most_common(12))
