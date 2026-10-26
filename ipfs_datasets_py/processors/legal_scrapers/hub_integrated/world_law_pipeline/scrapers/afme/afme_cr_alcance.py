"""[ALCANCE variant] Reads each day page's AlcancesDiv, fetches each /pub/.../ALCA<n>_DD_MM_YYYY.html supplement and applies the same MUNICIPALIDADES splitter. Batch "alcance", cache afme/_cr_alcance/.
Costa Rica La Gaceta (imprentanacional.go.cr) municipal acts -> SCHEMA rows. robots: /gaceta/ allowed (RFC 9309 checked); GET /gaceta/?date=DD/MM/YYYY
returns the full HTML edition. Items under MUNICIPALIDADES / RÉGIMEN MUNICIPAL sub-sections are split at 'MUNICIPALIDAD DE X' / 'CONCEJO MUNICIPAL DE DISTRITO DE X'
headings, ended by the '( IN2026... )' publication code; kept only if the item head is regulatory (reglamento/acuerdo/tarifa/plan regulador...). Mapped to the CR
canton by folded name (unique). Ledger places skipped. Day cache checkpoint: afme/_cr_gaceta/<date>.json. usage: afme_cr_gaceta.py <from YYYY-MM-DD> <to> [test]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,time,datetime,glob,shutil,unicodedata,collections,html as H
import requests
from bs4 import BeautifulSoup as B
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key, validate_file
from rfc9309 import Robots
UA="world-municipal-law-research/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law)"
D0,D1=[datetime.date.fromisoformat(x) for x in sys.argv[1:3]]; TEST=len(sys.argv)>3 and sys.argv[3]=="test"
BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); CACHE=f"{BASE}/_cr_alcance"+("_test" if TEST else ""); OUT=f"{BASE}/_test/CR_alcance" if TEST else f"{BASE}/CR"
os.makedirs(CACHE,exist_ok=True); os.makedirs(OUT,exist_ok=True)
def fold(s): return re.sub(r"[^a-z0-9]+"," ",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()).strip()
places=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]=="CR" and r["admin_level"]=="municipality"]
LED={json.loads(l)["place_key"] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/confirmed_batches/afme.jsonl")) if json.loads(l)["cc"]=="CR"}
nm=collections.defaultdict(list)
for p in places:
    for n in {p["place_name"],re.sub(r"(?i)^(cant[oó]n de |municipalidad de )","",p["place_name"])}: nm[fold(n)].append(p)
labf=f"{BASE}/_labels/CR.jsonl"
if os.path.exists(labf):
    byq={p["qid"]:p for p in places}
    for l in open(labf):
        x=json.loads(l); p=byq.get(x["qid"])
        if p:
            for v in [x["labels"].get(k) for k in ("es","en")]+x.get("aliases",{}).get("es",[]):
                if v: f=fold(re.sub(r"(?i)^(cant[oó]n de |cant[oó]n |municipalidad de )","",v)); 
                if v and p not in nm[f]: nm[f].append(p)
rb_txt=requests.get("https://www.imprentanacional.go.cr/robots.txt",headers={"User-Agent":UA},timeout=30).text; RB=Robots(rb_txt)
DELAY=max(float(RB.crawl_delay(UA) or 0),5.0); S=requests.Session(); S.headers["User-Agent"]=UA; nxt=0
TOP=r"(PODER LEGISLATIVO|PODER EJECUTIVO|PODER JUDICIAL|DOCUMENTOS VARIOS|TRIBUNAL SUPREMO DE ELECCIONES|CONTRATACI[ÓO]N P[ÚU]BLICA|INSTITUCIONES DESCENTRALIZADAS|NOTIFICACIONES|AVISOS|REMATES|FE DE ERRATAS|REGLAMENTOS|R[ÉE]GIMEN MUNICIPAL|MUNICIPALIDADES|BANCO CENTRAL|AUTORIDAD REGULADORA)"
HEAD=re.compile(r"\b(MUNICIPALIDAD DE|CONCEJO MUNICIPAL DE DISTRITO DE)\s+((?:[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\.\-]*\s?){1,6})")
LEGAL=re.compile(r"(?i)\b(reglamento|ordenanza|acuerdo|tarifa|tasa[s]?\b|plan regulador|reforma|se acuerda|aprob[óo]|derog|tributo|impuesto|canon|precio p[úu]blico|manual de|pol[íi]tica|disposici[oó]n)")
NOT=re.compile(r"(?i)\b(edicto|reposici[oó]n de t[íi]tulo|derecho de cementerio|nichos|exhumaci|zona mar[íi]timo terrestre.*solicita|solicita en concesi|interrumpir[aá]n|vacaciones|cierre de oficinas|licitaci[óo]n|remate|patente de licores a nombre|cobro administrativo|notifica a)")
def fetch(u):
    global nxt
    if not RB.can_fetch(UA,u): raise PermissionError(u)
    for i in range(4):
        w=nxt-time.time()
        if w>0: time.sleep(w)
        nxt=time.time()+DELAY
        try: r=S.get(u,timeout=120)
        except Exception: time.sleep(DELAY*(2**i)); continue
        if r.status_code in (429,503): time.sleep(DELAY*(2**(i+1))); continue
        r.raise_for_status(); return r
    raise RuntimeError("fetch failed")
def get(d):
    u=f"https://www.imprentanacional.go.cr/gaceta/?date={d:%d/%m/%Y}"; return u,fetch(u)
def items(t):
    out=[]
    secs=[m.start() for m in re.finditer(r"\b(MUNICIPALIDADES|R[ÉE]GIMEN MUNICIPAL)\b",t)]
    for s0 in secs:
        m=re.compile(r"\b"+TOP+r"\b(?=\s+[A-ZÁÉÍÓÚ])").search(t,s0+20); seg=t[s0:m.start() if m else len(t)]
        pos=0
        for cm in list(re.finditer(r"\(\s*(IN\s?\d{8,})\s*\)",seg))+[None]:
            chunk=seg[pos:cm.end() if cm else len(seg)]; pos=cm.end() if cm else len(seg)
            h=HEAD.search(chunk[:400])
            if not h or not cm: continue
            toks=h.group(2).split(); name=next((" ".join(toks[:k]) for k in range(len(toks),0,-1) if fold(" ".join(toks[:k])) in nm)," ".join(toks[:2]))
            out.append((h.group(1),name.strip(" .-"),chunk[h.start():].strip(),cm.group(1).replace(" ","")))
    return out
days=[D0+datetime.timedelta(n) for n in range((D1-D0).days+1)]; days=[d for d in days if d.weekday()<5][::-1]
if TEST: days=days[:int(os.environ.get("CR_ALC_TEST_DAYS","60"))]
stat=collections.Counter()
for d in days:
    cf=f"{CACHE}/{d}.json"
    if os.path.exists(cf): continue
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor",flush=True); sys.exit(2)
    try: u,r=get(d)
    except Exception as e: print(d,"ERR",repr(e)[:100],flush=True); stat["err"]+=1; continue
    al=sorted(set(re.findall(r"/pub/(\d{4}/\d\d/\d\d)/(ALCA\d+[A-Z]?_\d\d_\d\d_\d{4})\.html",r.text)))
    al=[x for x in al if x[0]==f"{d:%Y/%m/%d}"]; keep=[]
    for ymd,name in al:
        au=f"https://www.imprentanacional.go.cr/pub/{ymd}/{name}.html"
        try: ar=fetch(au)
        except Exception as e: print(d,name,"ERR",repr(e)[:80],flush=True); stat["err"]+=1; continue
        ar.encoding=ar.apparent_encoding if not ar.encoding or ar.encoding.lower()=="iso-8859-1" else ar.encoding
        t=re.sub(r"\s+"," ",B(ar.text,"html.parser").get_text(" ",strip=True))
        for kind,name2,body,code in items(t):
            if NOT.search(body[:400]) or not LEGAL.search(body[:400]): stat["skip_notice"]+=1; continue
            keep.append(dict(kind=kind,name=name2,body=body,code=code,alcance=name,url=au,pdf=au[:-5]+".pdf"))
    json.dump({"date":str(d),"url":None,"pdf":None,"edition":True,"alcances":[x[1] for x in al],"items":keep},open(cf+".tmp","w"),ensure_ascii=False); os.rename(cf+".tmp",cf)
    stat["days"]+=1; stat["items"]+=len(keep); print(d,len(keep),flush=True)
# write
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); per=collections.defaultdict(list); unm=collections.Counter()
for cf in sorted(glob.glob(f"{CACHE}/*.json")):
    x=json.load(open(cf))
    for it in x["items"]:
        c=nm.get(fold(it["name"]),[]); c=list({p["place_id"]:p for p in c}.values())
        if len(c)!=1: unm[it["name"]]+=1; continue
        p=c[0]; key=place_key(p["place_id"],None,"CR")
        if key in LED: stat["ledger_skip"]+=1; continue
        b=it["body"]; m=re.search(r"(REGLAMENTO|ACUERDO|REFORMA|TARIFA|PLAN REGULADOR|ORDENANZA|MANUAL|POL[ÍI]TICA)[^.]{0,200}",b,re.I)
        title=(f"{it['kind'].title()} {it['name'].title()}: "+(m.group(0) if m else b[len(it['kind'])+len(it['name'])+1:][:200])).strip()[:500]
        did=f"imprentanacional.go.cr/alcance/{it['alcance']}/{it['code'] or hash(b)%10**10}"
        rec=dict(place_id=p["place_id"],country_code="CR",doc_id=did,source_platform="cr_la_gaceta_alcance",source_url=it["url"],doc_type="gazette_act",language="es",
            title_native=title,published_date=x["date"],consolidated=False,in_force=None,content_format="html",
            html=f'<div class="chunk-content"><p>{H.escape(b)}</p></div>',text=b,retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            source_policy="robots_allowed_rfc9309",source_official=True,source_org="Imprenta Nacional de Costa Rica - La Gaceta",place_name=p["place_name"],qid=p["qid"],
            admin_level=p["admin_level"],platform="cr_la_gaceta_alcance",platform_place_id=it["name"],
            extra_metadata={"gazette_pdf":it["pdf"],"alcance":it["alcance"],"publication_code":it["code"],"issuer_heading":f"{it['kind']} {it['name']}","crawl_delay_s":DELAY})
        per[key].append(rec)
rep=[]
for key,rows in per.items():
    if glob.glob(f"{OUT}/{key}.alcance2*.jsonl") and not TEST: continue
    seen=set(); rows=[r for r in rows if not (r["doc_id"] in seen or seen.add(r["doc_id"]))]
    f=f"{OUT}/{key}.alcance{ts}p0001.jsonl"
    with open(f+".tmp","w") as o:
        for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f); v=validate_file(f); rep.append({"key":key,"rows":len(rows),"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1]),flush=True)
json.dump({"stat":stat,"unmapped":unm.most_common(60),"files":rep},open(f"{BASE}/_cr_alcance_report_{'test' if TEST else 'full'}_{ts}.json","w"),indent=1,ensure_ascii=False)
print("DONE ok",sum(r["ok"] for r in rep),"bad",sum(not r["ok"] for r in rep),"files",len(rep),dict(stat),"unmapped",unm.most_common(15),flush=True)
