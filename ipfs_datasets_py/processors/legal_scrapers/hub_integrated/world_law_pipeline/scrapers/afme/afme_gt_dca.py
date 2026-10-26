"""GT Diario de Centro America, legal.dca.gob.gt: Otras Instituciones > Publicaciones Varias > Actas Municipales (4.1.2) and Acuerdos Municipales (4.1.3).
Uses the site's own public search form endpoints (robots: Allow /), plain requests, >=5 s apart; a CAPTCHA/challenge or non-JSON answer stops the run.
The documents are image-only PDFs (no text layer), so rows are metadata-only (content_complete=false) and the PDF goes to the raw-scan queue (pdf_url, not OCR'd).
Mapping: the section is enumerated (set A). For each municipio, the site text search for "Concejo Municipal <name>" (AND match) is paged, and hits in A are attributed.
Multi-hit docs: substring names keep the longest; department-capital/department names yield to the more specific one; otherwise the doc is dropped as ambiguous.
Duplicate municipio names (7) and ledger places are skipped. Checkpoints go to afme/_gt_dca[_test]/ (A_<sub>.json, m_<qid>.json).
usage: afme_gt_dca.py <from DD/MM/YYYY> <to DD/MM/YYYY> [test]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,time,datetime,glob,shutil,collections
import requests
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key, validate_file
from rfc9309 import Robots
UA="world-municipal-law-research/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law)"
F0,F1=sys.argv[1:3]; TEST=len(sys.argv)>3 and sys.argv[3]=="test"
BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); CK=f"{BASE}/_gt_dca"+("_test" if TEST else ""); OUT=f"{BASE}/_test/GT_dca" if TEST else f"{BASE}/GT"
os.makedirs(CK,exist_ok=True); os.makedirs(OUT,exist_ok=True)
H="https://legal.dca.gob.gt"; RB=Robots(requests.get(H+"/robots.txt",headers={"User-Agent":UA},timeout=30).text)
DELAY=max(float(RB.crawl_delay(UA) or 0),5.0); S=requests.Session(); S.headers["User-Agent"]=UA; nxt=[0]
CHAL=re.compile(r"(?i)(captcha|recaptcha|hcaptcha|cf-chl|challenge-platform|just a moment|incapsula|SHA256_init)")
def call(m,path,**kw):
    u=H+path
    if not RB.can_fetch(UA,u): raise PermissionError("robots "+u)
    for i in range(4):
        w=nxt[0]-time.time()
        if w>0: time.sleep(w)
        nxt[0]=time.time()+DELAY
        try: r=S.request(m,u,timeout=120,headers={"X-Requested-With":"XMLHttpRequest"},**kw)
        except Exception: time.sleep(DELAY*2**i); continue
        if r.status_code in (429,503): time.sleep(DELAY*2**(i+2)); continue
        if CHAL.search(r.text[:20000]): print("STOP captcha/challenge",flush=True); sys.exit(3)
        r.raise_for_status(); return r
    raise RuntimeError("fetch failed "+u)
def search(sub,texto):
    d=dict(categoria="4",tipo="4.1",subtipo=sub,texto=texto,fechaPublicacionInicial=F0,fechaPublicacionFinal=F1,numeroTomo="",numeroPagina="",numeroEdicion="",
           numeroAnuncio="",tituloPublicacion="",numeroReciboPago="",busquedaAvanzada="true")
    j=call("POST","/GestionDocumento/BusquedaDocumento",data=d).json()
    if not j.get("isSuccessful"): raise RuntimeError(j.get("error"))
    tot0=int(j.get("total") or 0)
    if j.get("documentos") is None and tot0>0: raise RuntimeError("documentos missing with total>0")
    docs=list(j.get("documentos") or []); j["total"]=tot0; last=int(j.get("last") or 1); cap=60 if texto else 10**6
    for p in range(2,min(last,cap)+1):
        docs+=call("GET","/GestionDocumento/BusquedaDocumentoAsync",params={"page":p}).json().get("documentos") or []
    return j["total"],docs
call("GET","/GestionDocumento/BusquedaDocumento?encabezado=4&subtitulo1=4.1&subtitulo2=4.1.3")
SUBS={"4.1.2":"Acta Municipal","4.1.3":"Acuerdo Municipal"}; A={}
for sub in SUBS:
    f=f"{CK}/A_{sub}.json"
    if not os.path.exists(f):
        tot,docs=search(sub,""); json.dump({"total":tot,"docs":docs},open(f+".tmp","w")); os.rename(f+".tmp",f); print("A",sub,tot,len(docs),flush=True)
    for x in json.load(open(f))["docs"]: A[x["DocumentID"]]=dict(x,sub=sub)
print("A total",len(A),flush=True)
def fold(s):
    import unicodedata; return re.sub(r"[^a-z0-9]+"," ",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()).strip()
R=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]=="GT"]
DEPTS={fold(re.sub(r"(?i) department$","",r["place_name"])) for r in R if r["admin_level"]=="department"}
labs={}
if os.path.exists(f"{BASE}/_labels/GT.jsonl"):
    for l in open(f"{BASE}/_labels/GT.jsonl"): x=json.loads(l); labs[x["qid"]]=x["labels"].get("es")
M=[r for r in R if r["admin_level"]=="municipality"]
for r in M: r["q"]=re.sub(r"(?i)^(municipio de |municipalidad de )","",labs.get(r["qid"]) or r["place_name"]).replace("Guatemala City","Guatemala")
dup={k for k,v in collections.Counter(fold(r["q"]) for r in M).items() if v>1}
LED={json.loads(l)["place_key"] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/confirmed_batches/afme.jsonl")) if json.loads(l)["cc"]=="GT"}
todo=[r for r in M if fold(r["q"]) not in dup and place_key(r["place_id"],None,"GT") not in LED]
if TEST: todo=todo[:20]
hits=collections.defaultdict(set)
for r in todo:
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor"); sys.exit(2)
    f=f"{CK}/m_{r['qid']}.json"
    if not os.path.exists(f):
        tot,docs=search("4.1.3",f"Concejo Municipal {r['q']}")
        ids=[x["DocumentID"] for x in docs]; json.dump({"q":r["q"],"total":tot,"ids":ids},open(f+".tmp","w")); os.rename(f+".tmp",f)
        print(r["q"],tot,sum(i in A for i in ids),flush=True)
    for i in json.load(open(f))["ids"]:
        if i in A: hits[i].add(r["place_id"])
byp={r["place_id"]:r for r in M}; per=collections.defaultdict(list); st=collections.Counter()
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
for i,ps in hits.items():
    ps=list(ps)
    if len(ps)>1:
        ps=[p for p in ps if not any(fold(byp[p]["q"])!=fold(byp[o]["q"]) and fold(byp[p]["q"]) in fold(byp[o]["q"]) for o in ps)]
        if len(ps)>1: ps=[p for p in ps if fold(byp[p]["q"]) not in DEPTS] or ps
    if len(ps)!=1: st["ambiguous"]+=1; continue
    p=byp[ps[0]]; x=A[i]; d=datetime.datetime.strptime(x["FechaPublicacion"][:10],"%d/%m/%Y").date().isoformat()
    pdf=f"{H}/GestionDocumento/DescargarPDFDocumento?idDocumento={i}"
    per[place_key(p["place_id"],None,"GT")].append(dict(place_id=p["place_id"],country_code="GT",doc_id=f"legal.dca.gob.gt/doc/{i}",source_platform="gt_diario_centro_america",
        source_url=pdf,doc_type="gazette_act",language="es",title_native=f"{SUBS[x['sub']]} - Concejo Municipal de {p['q']} (Diario de Centro América, {d}, {x.get('numeroPagina') or '?'} p.)",
        published_date=d,consolidated=False,in_force=None,content_format="pdf_text",content_complete=False,retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_policy="robots_allowed_rfc9309",source_official=True,source_org="Diario de Centro América (Diario Oficial), Guatemala",place_name=p["place_name"],qid=p["qid"],
        admin_level=p["admin_level"],platform="gt_diario_centro_america",platform_place_id=p["q"],
        extra_metadata={"dca_document_id":i,"dca_section":x["sub"]+" "+SUBS[x["sub"]],"viewer_url":H+x["UrlDocument"],"pdf_url":pdf+"#dca.pdf","receipt":x.get("noRecibo"),
            "note":"image-only scan (no text layer) -> raw PDF queue; mapped via site text search 'Concejo Municipal <name>'","crawl_delay_s":DELAY}))
rep=[]
for key,rows in per.items():
    if glob.glob(f"{OUT}/{key}.dca2*.jsonl") and not TEST: continue
    f=f"{OUT}/{key}.dca{ts}p0001.jsonl"
    with open(f+".tmp","w") as o:
        for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f); v=validate_file(f); rep.append({"key":key,"rows":len(rows),"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1]),flush=True)
json.dump({"stat":st,"A":len(A),"mapped_docs":sum(len(v) for v in per.values()),"files":rep},open(f"{BASE}/_gt_dca_report_{'test' if TEST else 'full'}_{ts}.json","w"),indent=1)
print("DONE ok",sum(r["ok"] for r in rep),"bad",sum(not r["ok"] for r in rep),"files",len(rep),"A",len(A),"mapped",sum(len(v) for v in per.values()),dict(st),flush=True)
