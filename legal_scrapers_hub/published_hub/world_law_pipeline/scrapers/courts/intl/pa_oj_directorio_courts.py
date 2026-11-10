"""Panama: courts of the Órgano Judicial (Corte Suprema salas, Tribunales Superiores, Juzgados de Circuito, Municipales, Seccionales,
de Niñez y Adolescencia, Agrarios, SPA Oficinas Judiciales, Centros de Métodos Alternos) with building, province, office e-mail and phone,
from the official directory XLSX linked at https://www.organojudicial.gob.pa/app/directorio-telefonico
(https://www.organojudicial.gob.pa/uploads/blogs.dir/1/2023/10/406/dir23.xlsx, Oct-2023 snapshot). One row per court; magistrate
'Despacho' sub-entries are collapsed into their court; non-court offices (Defensa Pública, seguridad, administración, Tribunal Electoral) skipped.
Contact data is office-level only (no personal staff data)."""
import json,re,os,subprocess,datetime,unicodedata,openpyxl
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
IDX="https://www.organojudicial.gob.pa/app/directorio-telefonico"; URL="https://www.organojudicial.gob.pa/uploads/blogs.dir/1/2023/10/406/dir23.xlsx"
RAW=f"{ROOT}/rules/raw/pa/oj_dir23.xlsx"
POL="robots_ignored_per_user_authorization|organojudicial.gob.pa official Órgano Judicial phone directory download (public); © Órgano Judicial, no licence stated|single download"
if not os.path.exists(RAW): subprocess.run(["curl","-s","-m","90","-A",UA,"-o",RAW,URL],check=True)
PROV={"BOCAS DEL TORO":"PA-1","COCLÉ":"PA-2","COLÓN":"PA-3","CHIRIQUÍ":"PA-4","DARIEN":"PA-5","HERRERA":"PA-6","LOS SANTOS":"PA-7","PANAMÁ":"PA-8","VERAGUAS":"PA-9",
      "PANAMÁ OESTE":"PA-10","COMARCA EMBERÁ-WOUNNAN":"PA-EM","COMARCA GUNA YALA":"PA-KY","COMARCA NGÄGBE-BUGLÉ":"PA-NB"}
def norm(x):
    x=unicodedata.normalize("NFKD",x or "").encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",re.sub(r"\b(de|del|la|el|los|las|y|en|lo)\b"," ",x))
SMALL={"de","del","la","el","los","las","y","en","lo","a"}
def tc(s):
    w=s.lower().split(); return " ".join(x if (i and x in SMALL) else (x.upper() if x in("spa","csj") else x.capitalize()) for i,x in enumerate(w))
COURT=re.compile(r"JUZGADO|TRIBUNAL|SALA |CORTE SUPREMA|OFICINA JUDICIAL|M[ÉE]TODOS ALTERNOS|CENTRO ALTERNO",re.I)
SKIP=re.compile(r"TRIBUNAL ELECTORAL|DEFENSA P[ÚU]BLICA|SEGURIDAD|ASISTENCIA ADMINISTRATIVA|TRIBUNAL DE CUENTAS|PRESIDENCIA|EQUIPO INTERDISCIPLINARIO|SALA DE AUDIENCIA|SECRETAR[IÍ]A GENERAL|DIRECCI[ÓO]N NACIONAL|^TRIBUNAL SUPERIOR$|^CORTE SUPREMA DE JUSTICIA$|^PRIMER TRIBUNAL SUPERIOR - RAMO CIVIL$",re.I)
def clean(d):
    d=re.sub(r"\s+"," ",d).strip()
    d=re.split(r"\s+-\s+DESPACHO\b|\s+DESPACHO\b|\s+-\s+MAG\.|\s+MAG\.",d,flags=re.I)[0].strip(" -")
    d=re.sub(r"^(CORTE SUPREMA DE JUSTICIA\s*-\s*)SECRETAR[IÍ]A\s+(DE\s+LA\s+)?",r"\1",d,flags=re.I)
    d=re.sub(r"^SECRETAR[IÍ]A\s+(DEL|DE LA|DE)?\s*","",d,flags=re.I)
    d=re.sub(r"^TRIBUNAL SUPERIOR\s+-\s+","TRIBUNAL SUPERIOR DEL ",d) if False else d
    d=re.sub(r"^(?=TERCER|PRIMER|SEGUNDO)","",d)
    return d
def level(n):
    u=n.upper()
    if "CORTE SUPREMA" in u: return "supreme","pa-supreme-court"
    if "TRIBUNAL SUPERIOR" in u or "TRIBUNAL DE APELACIONES" in u or "TRIBUNAL DE JUICIO" in u and "SUPERIOR" in u: return "appellate","pa-court-of-appeal"
    if "MARITIMO" in u or "MARÍTIMO" in u: return "trial_general","pa-high-court"
    if "NIÑEZ" in u or "ADOLESCEN" in u: return "juvenile","pa-lower-court"
    if "FAMILIA" in u: return "family","pa-lower-court"
    if "MUNICIPAL" in u or "MUNCIPAL" in u: return "municipal","pa-lower-court"
    if "MÉTODOS ALTERNOS" in u or "METODOS ALTERNOS" in u or "CENTRO ALTERNO" in u: return "other","pa-supreme-court"
    if "CIRCUITO" in u or "OFICINA JUDICIAL" in u or "TRIBUNAL DE JUICIO" in u: return "trial_general","pa-lower-court"
    return "trial_general","pa-lower-court"
ws=openpyxl.load_workbook(RAW,read_only=True).active; rows=list(ws.iter_rows(values_only=True))[1:]
C={}
for prov,edif,dep,mail,tel,ext,tipo,_ in rows:
    if not dep or not COURT.search(dep) or SKIP.search(dep.strip()): continue
    base=clean(dep)
    if SKIP.search(base): continue
    if re.match(r"^(TRIBUNAL|PRIMER|SEGUNDO|TERCER)",base,re.I) and not base.upper().startswith(("TRIBUNAL SUPERIOR","PRIMER","SEGUNDO","TERCER","TRIBUNAL DE")): pass
    k=norm(base)
    c=C.setdefault(k,{"name":base,"prov":prov,"edif":edif,"mail":None,"tel":None,"desp":0})
    if "DESPACHO" in dep.upper(): c["desp"]+=1
    if mail and not c["mail"] and "DESPACHO" not in dep.upper(): c["mail"]=mail.strip()
    if tel and not c["tel"] and str(tipo or "").lower().startswith("l"): c["tel"]=str(tel).strip()
ks=sorted(C,key=len)
for k in ks:
    for k2 in ks:
        if k2!=k and k in C and k2 in C and k2.startswith(k) and len(k)>=20 and C[k]["prov"]==C[k2]["prov"] and re.search(r"TRIBUNAL SUPERIOR|CORTE SUPREMA",C[k]["name"]): del C[k2]
F=f"{ROOT}/data/pa/pa_courthouses.jsonl"; R=[json.loads(l) for l in open(F)]
have={norm(r["name"]) for r in R}|{r["court_id"] for r in R}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); out=[]
for k,c in C.items():
    cid="pa-"+re.sub(r"[^a-z0-9]+","-",unicodedata.normalize("NFKD",c["name"]).encode("ascii","ignore").decode().lower()).strip("-")[:80]
    if k in have or cid in have: continue
    have|={k,cid}; lv,parent=level(c["name"]); pv=(c["prov"] or "").strip()
    out.append({"court_id":cid,"record_type":"courthouse","name":tc(c["name"]),"name_local":c["name"],"level":lv,"court_system":"national","country_code":"PA",
        "subdivision":PROV.get(pv,"PA"),"jurisdiction":tc(pv) if pv else None,"parent_court_id":parent,
        "address":{"street":None,"building":tc(c["edif"]) if c["edif"] else None,"city":None,"postcode":None,"region":tc(pv) if pv else None,"country":"PA"},
        "geo":{"lat":None,"lon":None},"phone":c["tel"],"email":c["mail"],"website":None,"wikidata":None,"place_ids":[],
        "source_url":URL,"index_url":IDX,"source_kind":"official","directory_snapshot":"2023-10 (dir23.xlsx)","site_policy":POL,"retrieved_at":now,
        "needs_review":False})
with open(F,"a") as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+"\n")
from collections import Counter
print("PA courts new",len(out),Counter(o["level"] for o in out))
