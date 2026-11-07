"""Panama: magistrates (names + court + title only) of the Corte Suprema, Tribunales Superiores (civil, penal, familia,
niñez, trabajo, district TS), maritime tribunals, Tribunal Especial de Integridad y Transparencia and Tercer Tribunal
Superior, from the 'Despacho de la Magistrada/del Magistrado X' and 'MAG. X' entries in the official Órgano Judicial
directory XLSX (https://www.organojudicial.gob.pa/uploads/blogs.dir/1/2023/10/406/dir23.xlsx, Oct-2023 snapshot; cached
by pa_oj_directorio_courts.py). Phone numbers/staff are NOT extracted. Snapshot is from 2023 so rows are needs_review
(composition may have changed). Dedupe on judge_id and on normalized name+court against data/pa/pa_judges.jsonl."""
import json,re,os,subprocess,datetime,unicodedata,openpyxl
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
URL="https://www.organojudicial.gob.pa/uploads/blogs.dir/1/2023/10/406/dir23.xlsx"; IDX="https://www.organojudicial.gob.pa/app/directorio-telefonico"
RAW=f"{ROOT}/rules/raw/pa/oj_dir23.xlsx"
POL="robots_ignored_per_user_authorization|organojudicial.gob.pa official Órgano Judicial phone directory download (public); © Órgano Judicial, no licence stated|single download"
if not os.path.exists(RAW): subprocess.run(["curl","-s","-m","90","-A",UA,"-o",RAW,URL],check=True)
def norm(x):
    x=unicodedata.normalize("NFKD",x or "").encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",re.sub(r"\b(de|del|la|el|los|las|y|en|lo)\b"," ",x))
def slug(x):
    x=unicodedata.normalize("NFKD",x).encode("ascii","ignore").decode().lower(); return re.sub(r"[^a-z0-9]+","-",x).strip("-")
SMALL={"de","del","la","el","los","las","y","en","lo","a"}
def tc(s):
    w=s.lower().split(); return " ".join(x if (i and x in SMALL) else x.capitalize() for i,x in enumerate(w))
courts=[json.loads(l) for l in open(f"{ROOT}/data/pa/pa_courthouses.jsonl")]
byn={norm(c["name"]):c["court_id"] for c in courts}
MAP=[("CORTE SUPREMA","pa-supreme-court"),("PRIMER TRIBUNAL MARITIMO","pa-primer-tribunal-maritimo"),("SEGUNDO TRIBUNAL MARITIMO","pa-segundo-tribunal-maritimo"),
 ("TRIBUNAL SUPERIOR DE APELACIONES MAR","pa-tribunal-superior-de-apelaciones-maritimas"),("TERCER TRIBUNAL SUPERIOR","pa-tercer-tribunal-superior-libre-competencia-y-asuntos-del-consumidor"),
 ("TRIBUNAL SUPERIOR DE FAMILIA","pa-tribunal-superior-de-familia"),("TRIBUNAL SUPERIOR DE NI","pa-tribunal-superior-de-ninez-y-adolescencia"),
 ("TRIBUNAL SUPERIOR DE TRABAJO SEGUNDO","pa-tribunal-superior-de-trabajo-segundo-distrito-judicial"),("TRIBUNAL SUPERIOR DE TRABAJO","pa-tribunal-superior-de-trabajo"),
 ("SEGUNDO TRIBUNAL SUPERIOR - RAMO PENAL","pa-segundo-tribunal-superior-ramo-penal"),("PRIMER TRIBUNAL SUPERIOR - RAMO CIVIL","pa-primer-tribunal-superior-del-primer-distrito-ramo-civil-panama"),
 ("TRIBUNAL SUPERIOR DEL CUARTO","pa-tribunal-superior-del-cuarto-distrito-judicial"),("TRIBUNAL SUPERIOR DEL SEGUNDO","pa-tribunal-superior-del-segundo-distrito-judicial"),
 ("TRIBUNAL SUPERIOR - DESPACHO","pa-tribunal-superior-del-tercer-distrito-judicial-david-chiriqui"),("TRIBUNAL ESPECIAL DE INTEGRIDAD",None)]
LABEL={"TRIBUNAL ESPECIAL DE INTEGRIDAD":"TRIBUNAL ESPECIAL DE INTEGRIDAD Y TRANSPARENCIA"}
ids={c["court_id"] for c in courts}
wb=openpyxl.load_workbook(RAW,read_only=True); S=set()
for ws in wb.worksheets:
    for row in ws.iter_rows(values_only=True):
        for c in row:
            if c and re.search(r"MAG\.|MAGISTRAD",str(c)) and len(str(c))>25: S.add(re.sub(r"\s+"," ",str(c)).strip())
F=f"{ROOT}/data/pa/pa_judges.jsonl"; E=[json.loads(l) for l in open(F)] if os.path.exists(F) else []
have={e["judge_id"] for e in E}|{(norm(e["name"]),e.get("court_id")) for e in E}|{norm(e["name"]) for e in E if e.get("court_id")=="pa-supreme-court"}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); out=[]
for d in sorted(S):
    if d.startswith("CORTE SUPREMA"): continue  # CSJ roster comes from the live pa_csj page (2023 entries include former justices)
    m=re.search(r"DESPACHO DE(?:L| LA)? MAGISTRAD([OA])\s+(.+?)(?:\s+-\s+.*)?$",d) or re.search(r"-\s+MAG\.\s+(.+?)(?:\s+-\s+.*)?$",d)
    g=None
    if m and m.lastindex==2: g,name=m.group(1),m.group(2)
    elif m: name=m.group(1)
    m2=re.match(r"TRIBUNAL SUPERIOR DEL CUARTO DISTRITO JUDICIAL ([A-ZÁÉÍÓÚÑ ]+?) - DESPACHO DE LA MAGISTRADA",d)
    if m2: name=m2.group(1); g="A"
    if not m and not m2: continue
    name=tc(name.strip(" -"))
    cid=next((v for k,v in MAP if d.startswith(k)),None)
    if cid and cid not in ids: cid=None
    court_label=re.split(r"\s+-\s+(?:DESPACHO|MAG\.)|\s+DESPACHO|\s+[A-ZÁÉÍÓÚÑ ]+ - DESPACHO",d)[0].strip()
    court_label=next((v for k,v in LABEL.items() if d.startswith(k)),court_label)
    if "CUARTO DISTRITO" in d: court_label="TRIBUNAL SUPERIOR DEL CUARTO DISTRITO JUDICIAL"
    jid=f"{cid or 'pa-'+slug(court_label)}-{slug(name)}"
    key=(norm(name),cid)
    if jid in have or key in have or (cid=="pa-supreme-court" and norm(name) in have): continue
    have|={jid,key}
    title="Magistrada" if g=="A" else ("Magistrado" if g=="O" else "Magistrado/a")
    out.append({"judge_id":jid,"court_id":cid,"court_name":tc(court_label),"name":name,"title":title,"position_type":"appellate" if "SUPERIOR" in d or "SUPREMA" in d else "trial",
      "term_start":None,"term_end":None,"status":"listed_in_2023_directory","roster_url":IDX,"source_url":URL,"directory_snapshot":"2023-10 (dir23.xlsx)",
      "site_policy":POL,"retrieved_at":now,"needs_review":True,"extraction":"official judiciary directory XLSX: 'Despacho del Magistrado'/'MAG.' entries (names and court only)",
      "license":"official judiciary website (facts)"})
with open(F,"a") as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+"\n")
print("PA magistrates new",len(out)); [print(o["judge_id"],"|",o["name"]) for o in out]
