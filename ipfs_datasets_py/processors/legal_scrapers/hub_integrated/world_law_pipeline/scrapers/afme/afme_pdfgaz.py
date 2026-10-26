"""PDF national-gazette municipal-section splitter. CC=SV: Diario Oficial (diariooficial.gob.sv; robots allows everything). The edition list comes from the site's
own month selector (POST /api/v1/diarios-disponibles), and the PDF from /seleccion/<Id>. Each edition's SUMARIO is read column by column (pdftotext -layout crop).
Entries of the 'Alcaldias Municipales' block (up to SECCION CARTELES) that are decretos/ordenanzas/reglamentos/acuerdos are kept; association statutes are excluded.
The issuer is taken from the entry text ('Alcaldía/Concejo Municipal de X'), and X is mapped to one of the 44 post-2024 municipios (Spanish 'Dept Centro/Norte/...' or es labels).
Plural or ambiguous issuers are dropped. Text is the item's page range (2-column crop). It works only from 2024-05-01 (the 2024 municipal reform; older acts belong
to former municipios that are now districts). The checkpoint is a per-edition cache. usage: afme_pdfgaz.py SV <from YYYY-MM> <to YYYY-MM> [test N_editions] | afme_pdfgaz.py NI <list page from> <list page to> [test N]
CC=NI: La Gaceta (lagaceta.gob.ni, robots 404 -> allow). The /ediciones?page=N list is used; the PDF is base64 inside the edition page; the ALCALDIAS body section is split at ALCALDIA (MUNICIPAL) DE X headings; legal items only (licitaciones etc. dropped)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,os,re,sys,time,datetime,glob,shutil,subprocess,unicodedata,collections
import requests
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import place_key, validate_file
from rfc9309 import Robots
UA="world-municipal-law-research/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law)"
CC=sys.argv[1]; M0,M1=sys.argv[2:4]; TEST=len(sys.argv)>4 and sys.argv[4]=="test"; NTEST=int(sys.argv[5]) if TEST and len(sys.argv)>5 else 40
BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); CK=f"{BASE}/_pdfgaz_{CC}"+("_test" if TEST else ""); OUT=f"{BASE}/_test/{CC}_gaz" if TEST else f"{BASE}/{CC}"
os.makedirs(CK,exist_ok=True); os.makedirs(OUT,exist_ok=True)
CHAL=re.compile(r"(?i)(captcha|cf-chl|challenge-platform|just a moment|incapsula|SHA256_init)")
def fold(s): return re.sub(r"[^a-z0-9]+"," ",unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()).strip()
class Host:
    def __init__(s,base):
        s.base=base; s.S=requests.Session(); s.S.headers["User-Agent"]=UA; r=s.S.get(base+"/robots.txt",timeout=30)
        s.rb=Robots(r.text) if r.status_code==200 and "<html" not in r.text[:300].lower() else (Robots(allow_all=True) if r.status_code==404 else None)
        if s.rb is None: raise PermissionError(f"robots unusable {r.status_code}")
        s.delay=max(float(s.rb.crawl_delay(UA) or 0),5.0); s.nxt=0
    def req(s,m,path,**kw):
        u=path if path.startswith("http") else s.base+path
        if not s.rb.can_fetch(UA,u): raise PermissionError("robots "+u)
        for i in range(4):
            w=s.nxt-time.time()
            if w>0: time.sleep(w)
            s.nxt=time.time()+s.delay
            try: r=s.S.request(m,u,timeout=180,**kw)
            except Exception: time.sleep(s.delay*2**i); continue
            if r.status_code in (429,503): time.sleep(s.delay*2**(i+2)); continue
            if "html" in r.headers.get("Content-Type","") and CHAL.search(r.text[:20000]): print("STOP challenge",flush=True); sys.exit(3)
            r.raise_for_status(); return r
        raise RuntimeError("fetch failed "+u)
def cols(pdf,p0,p1):
    w,h=[float(x) for x in re.search(r"Page size:\s*([\d.]+) x ([\d.]+)",subprocess.run(["pdfinfo",pdf],capture_output=True,text=True).stdout).groups()]
    out=[]
    for p in range(p0,p1+1):
        for x in (0,w/2):
            t=subprocess.run(["pdftotext","-layout","-f",str(p),"-l",str(p),"-x",str(int(x)),"-y","0","-W",str(int(w/2)+1),"-H",str(int(h)),pdf,"-"],capture_output=True,text=True).stdout
            out+= [l.strip() for l in t.split("\n") if len(l.strip())>=12 or re.search(r"\d\s*$",l)]
    return out
places=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"]==CC and r["admin_level"]=="municipality"]
LED={json.loads(l)["place_key"] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/confirmed_batches/afme.jsonl")) if json.loads(l)["cc"]==CC}
idx=collections.defaultdict(set); DIR={"central":"centro","northern":"norte","southern":"sur","eastern":"este","western":"oeste","coastal":"costa"}
labs={}
if os.path.exists(f"{BASE}/_labels/{CC}.jsonl"):
    for l in open(f"{BASE}/_labels/{CC}.jsonl"): x=json.loads(l); labs[x["qid"]]=[x["labels"].get("es")]+x.get("aliases",{}).get("es",[])
for p in places:
    names={p["place_name"]}|{v for v in labs.get(p["qid"],[]) if v}
    m=re.match(r"(Central|Northern|Southern|Eastern|Western|Coastal) (.+)$",p["place_name"])
    if m: names.add(f"{m.group(2)} {DIR[m.group(1).lower()]}"); names.add(f"{m.group(2)} {DIR[m.group(1).lower()]}".replace("costa","costa"))
    for n in names: idx[fold(re.sub(r"(?i)^municipio de ","",n))].add(p["place_id"])
byp={p["place_id"]:p for p in places}
ISS=re.compile(r"(?i)(?:Alcald[íi]a|Concejo|Municipalidad)\s+Municipal(?:es)?\s+(?:del?\s+(?:Municipio\s+de\s+)?)?([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñü ]{2,60}?)(?=[,.;:)]|\s+(?:y|aprob|que|para|del departamento|departamento|en)\b|$)")
KEEP=re.compile(r"(?i)\b(decreto|ordenanza|reglamento|acuerdo|tasa|tarifa|disposiciones)\b"); DROP=re.compile(r"(?i)^\W*estatutos|asociaci[óo]n comunal|confiri[ée]ndoles el car[áa]cter de persona jur")
def map_issuer(t):
    hits=set()
    for m in ISS.finditer(t):
        toks=fold(m.group(1)).split()
        for k in range(min(len(toks),6),0,-1):
            c=idx.get(" ".join(toks[:k]))
            if c: hits|=c; break
    if re.search(r"(?i)Alcald[íi]as Municipales|Concejos Municipales",t): return None
    return next(iter(hits)) if len(hits)==1 else None
def sumario(pdf):
    L=cols(pdf,1,3); s=None; ents=[]; buf=[]
    for i,l in enumerate(L):
        if s is None:
            if re.fullmatch(r"(?i)alcald[íi]as municipales",l): s=i
            continue
        if re.search(r"(?i)^SECCI[ÓO]N CARTELES",l): break
        buf.append(l); m=re.search(r"\.{3,}\s*(\d+)(?:\s*-\s*(\d+))?\s*$",l)
        if m:
            t=re.sub(r"\.{3,}\s*[\d\s-]+$","", " ".join(buf)).strip(); ents.append((t,int(m.group(1)),int(m.group(2) or m.group(1)))); buf=[]
    return ents
def urllib_q(u):
    import urllib.parse; return urllib.parse.quote(u,safe="/-_.~%")
if CC=="NI":
    import base64,html as HT
    H=Host("https://www.lagaceta.gob.ni"); stat=collections.Counter(); P0,P1=int(M0),int(M1)
    pages=list(range(P0,P1+1))
    if TEST: pages=pages[::max(1,len(pages)//max(1,NTEST//9))][:max(1,NTEST//9)]
    HEADNI=re.compile(r"^ALCALD[ÍI]A\s+(?:MUNICIPAL\s+)?(?:DEL?\s+(?:MUNICIPIO\s+DE\s+)?)?([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .\-]{2,50})$")
    TOPNI=re.compile(r"^(UNIVERSIDADES|SECCI[ÓO]N (JUDICIAL|MERCANTIL)|MINISTERIO\b|BANCO\b|INSTITUTO\b|EMPRESA\b|CORTE\b|ASAMBLEA\b|CONSEJO\b|CASA DE GOBIERNO|PROCURADUR|CONTRALOR|SUPERINTENDENCIA|DIRECCI[ÓO]N GENERAL|REGISTRO DE LA PROPIEDAD|ENTE REGULADOR|POLIC[ÍI]A|FUERZA|TRIBUNAL|COMISI[ÓO]N|ASOCIACI|ESTADO MAYOR)")
    KEEPNI=re.compile(r"(?i)\b(ordenanza|reglamento|plan de arbitrios|acuerdo municipal|resoluci[óo]n municipal|el concejo municipal|certificaci[óo]n|tasa|tarifa|impuesto municipal|disposici[óo]n)\b")
    DROPNI=re.compile(r"(?i)(convocatoria|licitaci[óo]n|cotizaci[óo]n|contrataci[óo]n|aviso de|pliego de bases|adquisici[óo]n|programa anual de contrataciones|PAC\b|t[íi]tulo supletorio|edicto)")
    eds=[]
    for pg in pages:
        f=f"{CK}/list_{pg}.json"
        if not os.path.exists(f):
            t=H.req("GET",f"/ediciones?page={pg}&search=").text; L=list(dict.fromkeys(HT.unescape(x) for x in re.findall(r'href="(/la-gaceta-[^"]+)"',t)))
            json.dump(L,open(f+".tmp","w")); os.rename(f+".tmp",f)
        eds+=json.load(open(f))
    for u in eds:
        cf=f"{CK}/e_{re.sub(r'[^a-z0-9]+','_',u.lower()).strip('_')[:120]}.json"
        if os.path.exists(cf): continue
        if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor",flush=True); sys.exit(2)
        try: r=H.req("GET",urllib_q(u))
        except Exception as ex: print(u,"ERR",repr(ex)[:90],flush=True); stat["err"]+=1; continue
        m=re.search(r"JVBERi0[A-Za-z0-9+/=]+",r.text); items=[]
        dm=re.search(r"(\d{1,2})-de-([a-zé]+)-(?:de-)?(\d{4})",u.replace("&#xe9;","e"))
        MES={"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
        date=f"{dm.group(3)}-{MES.get(dm.group(2).replace('é','e'),0):02d}-{int(dm.group(1)):02d}" if dm and MES.get(dm.group(2).replace('é','e')) else None
        if m:
            pdf=f"/tmp/afme_pdfgaz_{os.getpid()}.pdf"; open(pdf,"wb").write(base64.b64decode(m.group(0)))
            n=int(re.search(r"Pages:\s*(\d+)",subprocess.run(["pdfinfo",pdf],capture_output=True,text=True).stdout).group(1))
            Ls=cols(pdf,1,min(n,400)); os.remove(pdf); insec=False; cur=None; seen_sum=0
            for l in Ls:
                if re.fullmatch(r"ALCALD[ÍI]AS",l): seen_sum+=1; insec=seen_sum>=2 or insec; continue
                if not insec: 
                    if HEADNI.match(l): insec=True
                    else: continue
                if TOPNI.match(l) and not l.startswith("ALCALD"):
                    if cur: items.append(cur)
                    cur=None; insec=False; continue
                h=HEADNI.match(l)
                if h:
                    if cur: items.append(cur)
                    cur={"name":h.group(1).strip(" .-"),"lines":[]}; continue
                if cur: cur["lines"].append(l)
            if cur: items.append(cur)
        keep=[]
        for it in items:
            body="\n".join(it["lines"]); head=body[:600]
            if DROPNI.search(head) or not KEEPNI.search(head): stat["skip_notice"]+=1; continue
            c=idx.get(fold(it["name"])) or idx.get(fold(re.sub(r"(?i)\s+(DEPARTAMENTO|DPTO).*$","",it["name"])))
            keep.append(dict(name=it["name"],place_id=(next(iter(c)) if c and len(c)==1 else None),text=body))
        json.dump({"u":u,"date":date,"items":keep},open(cf+".tmp","w"),ensure_ascii=False); os.rename(cf+".tmp",cf)
        stat["editions"]+=1; print(u,date,len(items),len(keep),flush=True)
    ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); per=collections.defaultdict(list); unm=collections.Counter()
    for cf in glob.glob(f"{CK}/e_*.json"):
        x=json.load(open(cf))
        for k,it in enumerate(x["items"]):
            if not it["place_id"]: unm[it["name"]]+=1; continue
            p=byp[it["place_id"]]; key=place_key(p["place_id"],None,CC)
            if key in LED: stat["ledger_skip"]+=1; continue
            reg=re.search(r"Reg\.?\s*(?:No\.?)?\s*([\w-]+)",it["text"]); u="https://www.lagaceta.gob.ni"+x["u"]
            t1=re.search(r"(?i)(ordenanza|reglamento|plan de arbitrios|acuerdo|resoluci[óo]n|certificaci[óo]n)[^\n]{0,160}",it["text"])
            per[key].append(dict(place_id=p["place_id"],country_code=CC,doc_id=f"lagaceta.gob.ni{x['u'].rstrip('/')}/{k}"+(f"-{reg.group(1)}" if reg else ""),source_platform="ni_la_gaceta",
                source_url=u,doc_type="gazette_act",language="es",title_native=(f"Alcaldía Municipal de {p['place_name']}: "+(t1.group(0) if t1 else it["text"][:160]).replace("\n"," "))[:500],
                published_date=x["date"],consolidated=False,in_force=None,content_format="pdf_text",text=it["text"],retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source_policy="robots_allowed_rfc9309",source_official=True,source_org="La Gaceta, Diario Oficial de Nicaragua",place_name=p["place_name"],qid=p["qid"],
                admin_level=p["admin_level"],platform="ni_la_gaceta",platform_place_id=it["name"],extra_metadata={"edition_page":u,"gazette_reg":reg.group(1) if reg else None,
                "note":"ALCALDIAS section item; PDF embedded (base64) in the edition page","crawl_delay_s":H.delay}))
    rep=[]
    for key,rows in per.items():
        if glob.glob(f"{OUT}/{key}.gaz2*.jsonl") and not TEST: continue
        seen=set(); rows=[r for r in rows if not (r["doc_id"] in seen or seen.add(r["doc_id"]))]
        f=f"{OUT}/{key}.gaz{ts}p0001.jsonl"
        with open(f+".tmp","w") as o:
            for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
            o.flush(); os.fsync(o.fileno())
        os.rename(f+".tmp",f); v=validate_file(f); rep.append({"key":key,"rows":len(rows),"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1]),flush=True)
    json.dump({"stat":stat,"unmapped":unm.most_common(80),"files":rep},open(f"{BASE}/_pdfgaz_{CC}_report_{'test' if TEST else 'full'}_{ts}.json","w"),indent=1,ensure_ascii=False)
    print("DONE ok",sum(r["ok"] for r in rep),"bad",sum(not r["ok"] for r in rep),"files",len(rep),dict(stat),"unmapped",len(unm),unm.most_common(10),flush=True); sys.exit(0)
H=Host("https://www.diariooficial.gob.sv"); stat=collections.Counter()
months=[]; y,m=map(int,M1.split("-")); y0,m0=map(int,M0.split("-"))
while (y,m)>=(y0,m0): months.append((y,m)); y,m=(y,m-1) if m>1 else (y-1,12)
eds=[]
for y,m in months:
    f=f"{CK}/list_{y}-{m:02d}.json"
    if not os.path.exists(f) or (y,m)==months[0]:
        j=H.req("POST","/api/v1/diarios-disponibles",data={"year":str(y),"month":f"{m:02d}"}).json(); json.dump(j,open(f+".tmp","w")); os.rename(f+".tmp",f)
    eds+=sorted(json.load(open(f)),key=lambda e:e["FechaInicio"],reverse=True)
    if TEST and len(eds)>=NTEST: break
if TEST: eds=eds[:NTEST]
for e in eds:
    cf=f"{CK}/{e['Id']}.json"
    if os.path.exists(cf): continue
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor",flush=True); sys.exit(2)
    try: r=H.req("GET",f"/seleccion/{e['Id']}")
    except Exception as ex: print(e["FechaInicio"],"ERR",repr(ex)[:90],flush=True); stat["err"]+=1; continue
    pdf=f"/tmp/afme_pdfgaz_{os.getpid()}.pdf"; open(pdf,"wb").write(r.content); items=[]
    if r.content[:5]==b"%PDF-":
        for t,p0,p1 in sumario(pdf):
            if DROP.search(t) or not KEEP.search(t): stat["skip_entry"]+=1; continue
            pid=map_issuer(t)
            if not pid: stat["unmapped"]+=1; items.append(dict(title=t,p0=p0,p1=p1,place_id=None)); continue
            txt="\n".join(cols(pdf,p0,min(p1,p0+40)))
            items.append(dict(title=t,p0=p0,p1=p1,place_id=pid,text=txt))
    os.remove(pdf); json.dump({"e":e,"items":items},open(cf+".tmp","w"),ensure_ascii=False); os.rename(cf+".tmp",cf)
    stat["editions"]+=1; print(e["FechaInicio"],len(items),sum(1 for i in items if i["place_id"]),flush=True)
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); per=collections.defaultdict(list); unm=collections.Counter()
for cf in glob.glob(f"{CK}/[0-9]*.json"):
    x=json.load(open(cf)); e=x["e"]
    if e["FechaInicio"]<"2024-05-01": continue
    for it in x["items"]:
        if not it["place_id"]: unm[it["title"][:90]]+=1; continue
        p=byp[it["place_id"]]; key=place_key(p["place_id"],None,CC)
        if key in LED: stat["ledger_skip"]+=1; continue
        u=f"https://www.diariooficial.gob.sv/seleccion/{e['Id']}"
        per[key].append(dict(place_id=p["place_id"],country_code=CC,doc_id=f"diariooficial.gob.sv/{e['FechaInicio']}/{e['Id']}/p{it['p0']}-{it['p1']}",source_platform="sv_diario_oficial",
            source_url=u,doc_type="gazette_act",language="es",title_native=it["title"][:500],published_date=e["FechaInicio"],consolidated=False,in_force=None,content_format="pdf_text",
            text=it["text"],retrieved_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),source_policy="robots_allowed_rfc9309",source_official=True,
            source_org="Imprenta Nacional - Diario Oficial de El Salvador",place_name=p["place_name"],qid=p["qid"],admin_level=p["admin_level"],platform="sv_diario_oficial",
            platform_place_id=p["place_name"],extra_metadata={"edition_file":e["NombreArchivo"],"pages":f"{it['p0']}-{it['p1']}","pdf_url":u+"#"+e["NombreArchivo"],
            "note":"text = printed page range of the item (2-column crop); may include adjacent items on shared pages","crawl_delay_s":H.delay}))
rep=[]
for key,rows in per.items():
    if glob.glob(f"{OUT}/{key}.gaz2*.jsonl") and not TEST: continue
    f=f"{OUT}/{key}.gaz{ts}p0001.jsonl"
    with open(f+".tmp","w") as o:
        for r in rows: o.write(json.dumps(r,ensure_ascii=False)+"\n")
        o.flush(); os.fsync(o.fileno())
    os.rename(f+".tmp",f); v=validate_file(f); rep.append({"key":key,"rows":len(rows),"ok":v["ok"],"errors":v.get("errors",[])[:2]}); print(json.dumps(rep[-1]),flush=True)
json.dump({"stat":stat,"unmapped":unm.most_common(80),"files":rep},open(f"{BASE}/_pdfgaz_{CC}_report_{'test' if TEST else 'full'}_{ts}.json","w"),indent=1,ensure_ascii=False)
print("DONE ok",sum(r["ok"] for r in rep),"bad",sum(not r["ok"] for r in rep),"files",len(rep),dict(stat),"unmapped",len(unm),flush=True)
