"""Cabo Verde Boletim Oficial (boe.incv.cv) Parte G - Autarquias locais -> municipal acts per municipio. usage: afme_cv_boe.py <max_pages|0> [test]
User-approved 2026-10-18 despite terms §6 (rows tagged site_terms_no_copy_user_approved). robots.txt 404 = allow (RFC 9309). >=5 s between requests,
plain GET only (no login, no challenge bypass; stops on CAPTCHA/challenge). Phase 1 enumerates the listing (?part=7, 100 rows/page, cached),
phase 2 keeps normative acts (posturas, regulamentos, códigos, tabelas de taxas, regimentos, planos, estatutos) and fetches the act PDF (DownloadAct)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,os,re,json,time,datetime,unicodedata,subprocess,tempfile,shutil,csv
import requests
from bs4 import BeautifulSoup
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key
from rfc9309 import Robots
UA="JusticeDAO-WorldLaw/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; municipal law research)"
H="https://boe.incv.cv"; DELAY=5.0; MAXP=int(sys.argv[1]); TEST=len(sys.argv)>2
OUT=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/CV"); WK=f"{OUT}/_boe"; os.makedirs(WK,exist_ok=True)
BATCH="boe_g_20261018"+(".test" if TEST else "")
POL="site_terms_no_copy_user_approved"
POLRAW=("boe.incv.cv Termos e condições §6 (https://boe.incv.cv/Documents/Index/7): \"É proibida a cópia, total ou parcial do site, incluindo qualquer "
        "conteúdo ou formato digital pertencente ao site da INCV, sem a prévia autorização da INCV.\" Crawled on the user's explicit approval (2026-10-18); robots.txt 404 (allow, RFC 9309).")
S=requests.Session(); S.headers["User-Agent"]=UA; _last=[0.0]
def fold(s): return re.sub(r"\s+"," ",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()).strip()
def get(u,**kw):
    for att in range(4):
        w=DELAY-(time.time()-_last[0])
        if w>0: time.sleep(w)
        _last[0]=time.time()
        try: r=S.get(u,timeout=90,**kw)
        except Exception as e: print("neterr",u,type(e).__name__,flush=True); time.sleep(30*(att+1)); continue
        if r.status_code in (429,503) or r.status_code>=500: time.sleep(60*(att+1)); continue
        if re.search(r"(?i)captcha|challenge-platform|cf-chl|Just a moment",r.text[:5000] if "html" in r.headers.get("content-type","") else ""): print("CHALLENGE/CAPTCHA -> stop",u,flush=True); sys.exit(4)
        return r
    return None
# robots
r=S.get(H+"/robots.txt",timeout=30)
if r.status_code==200 and not re.search(r"(?i)<html",r.text[:300]):
    if not Robots(r.text).can_fetch(UA,H+"/Bulletins/DownloadAct?id=1"): print("robots disallow -> stop"); sys.exit(5)
elif r.status_code not in (404,410): print("robots unavailable",r.status_code); sys.exit(5)
# places
P=[x for x in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if x["country_code"]=="CV" and x["admin_level"]=="municipality"]
NM={fold(re.sub(r"(?i)\s+municipality$","",x["place_name"])):x for x in P}
def mapent(ent):
    e=fold(ent.split(">")[0])
    m=re.match(r"(municipio|camara municipal|assembleia municipal)\s+d[aoe]s?\s+(.+)$",e)
    if not m: return None
    n=m.group(2).strip(" .-")
    return NM.get(n) or NM.get(re.sub(r"\s+de\s+santiago$","",n))
# phase 1: listing
LST=f"{WK}/listing.jsonl"; PG=f"{WK}/listing_pages.txt"
donep={int(l) for l in open(PG)} if os.path.exists(PG) else set()
page=1; last=None
while True:
    if MAXP and page>MAXP: break
    if page in donep and last is not None and page<=last: page+=1; continue
    r=get(f"{H}/Bulletins?part=7&highlight=False&page={page}&rows=100")
    if r is None: print("listing fail",page); break
    s=BeautifulSoup(r.text,"html.parser")
    if last is None:
        nums=[int(m) for m in re.findall(r"page=(\d+)&(?:amp;)?rows=100",r.text)]; last=max(nums) if nums else page
        print("listing pages",last,flush=True)
    items=[]
    for a in s.find_all("a",href=re.compile(r"^/Bulletins/View\?id=\d+")):
        row=a.parent.parent; ds=row.find_all("div",recursive=False)
        t=" ".join(a.get_text(" ",strip=True).split()); ent=ds[1].get_text(" ",strip=True) if len(ds)>1 else ""; sm=ds[2].get_text(" ",strip=True) if len(ds)>2 else ""
        items.append({"id":int(a["href"].split("=")[1]),"title":t,"entity":ent,"sumario":sm})
    if page not in donep:
        with open(LST,"a") as o:
            for x in items: o.write(json.dumps(x,ensure_ascii=False)+"\n")
        with open(PG,"a") as o: o.write(f"{page}\n")
    if not items or page>=last: break
    page+=1
# phase 2
INC=re.compile(r"(?i)(postura|regulamento|c[óo]digo\s+(de\s+postura|tribut|de\s+taxas|municipal)|tabela\s+de\s+(taxas|tarif|pre[çc]os)|tarif[áa]rio|regimento\s+d[ao]\s+assembleia|plano\s+(director|diretor|detalhado|de\s+pormenor|de\s+urbaniza|urban[íi]stico)|\bPDM\b|regime\s+jur[íi]dico|taxas?\s+(e\s+emolumentos\s+)?municipa|imposto\s+[uú]nico|emolumentos)")
EXC=re.compile(r"(?i)(nomea|exonera|aposenta|louvor|concurso|licen[çc]a\s+(sem|de\s+longa)|transfer[êe]ncia\s+de\s+funcion|promov|promo[çc][ãa]o\s+d|reclassifica|destacamento|requisi|designa|cessa|recondu|contrato\s+de\s+trabalho|lista\s+(de\s+antiguidade|nominal|nominativa|definitiva|dos\s+candidatos)|homologa[çc][ãa]o\s+da\s+lista|j[úu]ri|subs[íi]dio|aviso\s+de\s+abertura|comiss[ãa]o\s+(eventual|de\s+acompanhamento|ordin[áa]ria\s+de\s+servi|de\s+servi)|senhas\s+de\s+presen|profissionaliza|doa[çc][ãa]o|concess[ãa]o\s+d[eo]\s+(um\s+)?(lote|terreno)|evolu[çc][ãa]o\s+(horizontal|na\s+carreira)|pens[ãa]o)")
def dtype(t):
    if re.search(r"(?i)postura|c[óo]digo",t): return "ordinance"
    if re.search(r"(?i)regulamento|regimento|tabela|tarif|taxa|normas|estatuto|regime",t): return "regulation"
    return "decision"
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf",dir=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme")) as f:
        f.write(b); f.flush()
        try: return subprocess.run(["pdftotext","-layout",f.name,"-"],capture_output=True,timeout=180).stdout.decode("utf8","replace")
        except Exception: return ""
seen=set(); acts=[]
for l in open(LST):
    x=json.loads(l)
    if x["id"] in seen: continue
    seen.add(x["id"]); blob=x["title"]+" "+x["sumario"]
    if INC.search(blob) and not EXC.search(blob): acts.append(x)
stat={"listed":len(seen),"normative":len(acts),"unmapped":0}
DONE=f"{WK}/done{'_test' if TEST else ''}.tsv"; done={l.split("\t")[0] for l in open(DONE)} if os.path.exists(DONE) else set()
per={}
if TEST:   # test: at most 2 acts per municipio, all municipios that appear
    c={}; a2=[]
    for x in acts:
        p=mapent(x["entity"]);
        if p is None: continue
        k=p["place_id"]; c[k]=c.get(k,0)+1
        if c[k]<=2: a2.append(x)
    acts=a2[:40]
for x in acts:
    if str(x["id"]) in done: continue
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor"); sys.exit(3)
    p=mapent(x["entity"])
    if p is None: stat["unmapped"]+=1; open(DONE,"a").write(f"{x['id']}\tunmapped\t{x['entity']}\n"); continue
    r=get(f"{H}/Bulletins/DownloadAct?id={x['id']}")
    if r is None or r.status_code!=200 or r.content[:4]!=b"%PDF": open(DONE,"a").write(f"{x['id']}\tnopdf\n"); continue
    txt=re.sub(r"[ \t]+\n","\n",pdftext(r.content)).strip(); complete=len(txt)>200
    m=re.search(r"Boletim Oficial n\.º\s*(\d+),\s*([IV]+)\s*Série de (\d\d)-(\d\d)-(\d{4})",x["title"]); pub=f"{m.group(5)}-{m.group(4)}-{m.group(3)}" if m else None
    t0=x["title"].split(" - Boletim Oficial")[0].strip(); num=re.search(r"n\.?\s*[º°]\s*([\w./-]+)",t0)
    key=place_key(p["place_id"],None,"CV")
    rec=dict(place_id=p["place_id"],country_code="CV",doc_id=f"boe.incv.cv/bulletins/view?id={x['id']}",source_platform="cv_boletim_oficial",
        source_url=f"{H}/Bulletins/View?id={x['id']}",doc_type=dtype(x["title"]+" "+x["sumario"]),language="pt",
        title_native=(f"{t0}: {x['sumario']}" if x["sumario"] else t0)[:500],number=num.group(1) if num else None,published_date=pub,
        consolidated=False,in_force=None,content_format="pdf_text",text=txt if complete else "",retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        content_complete=complete,source_policy=POL,source_policy_raw=POLRAW,source_official=True,source_org="Imprensa Nacional de Cabo Verde (Boletim Oficial, II Série, Parte G – Autarquias locais)",
        place_name=p["place_name"],qid=p["qid"],admin_level="municipality",platform="cv_boletim_oficial",platform_place_id=x["entity"].split(">")[0].strip(),
        extra_metadata={"boe_act_id":x["id"],"boe_entity":x["entity"],"boe_title":x["title"],"pdf_url":f"{H}/Bulletins/DownloadAct?id={x['id']}","source_policy_raw":POLRAW,"crawl_delay_s":DELAY})
    f=f"{OUT}/{key}.{BATCH}.jsonl"; rows=[json.loads(l) for l in open(f)] if os.path.exists(f) else []
    rows=[y for y in rows if y["doc_id"]!=rec["doc_id"]]+[rec]
    with open(f+".tmp","w") as o:
        for y in rows: o.write(json.dumps(y,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f)
    if not complete and not TEST:
        with open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/_ocr_queue.jsonl"),"a") as q: q.write(json.dumps({"cc":"CV","place_key":key,"doc_id":rec["doc_id"],"pdf_url":rec["extra_metadata"]["pdf_url"],"file":f})+"\n")
    open(DONE,"a").write(f"{x['id']}\tok\t{key}\n")
print(json.dumps(stat),"DONE",flush=True)
