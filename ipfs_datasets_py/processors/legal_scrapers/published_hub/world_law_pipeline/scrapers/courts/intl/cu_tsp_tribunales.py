"""Cuba: Tribunales Provinciales Populares (16), their salas, Tribunales Municipales Populares and secciones, with address,
phone and e-mail, from the official TSP directory https://www.tsp.gob.cu/tribunales-provinciales (live; province filter via GET).
Salas are stored as record_type court_body under their provincial court; TMP/secciones as courthouses. Dedupe on normalized name."""
import json,re,html,time,datetime,urllib.request,unicodedata,subprocess
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
URL="https://www.tsp.gob.cu/tribunales-provinciales"
POL="robots_ignored_per_user_authorization|tsp.gob.cu official Tribunal Supremo Popular website; Términos y condiciones page, public directory information|polite 3 s/request"
PROV={1:("Pinar del Río","CU-01"),3:("Artemisa","CU-15"),2:("Mayabeque","CU-16"),4:("La Habana","CU-03"),5:("Isla de la Juventud","CU-99"),6:("Matanzas","CU-04"),
      9:("Villa Clara","CU-05"),7:("Cienfuegos","CU-06"),8:("Sancti Spíritus","CU-07"),10:("Ciego de Ávila","CU-08"),11:("Camagüey","CU-09"),12:("Las Tunas","CU-10"),
      13:("Holguín","CU-11"),14:("Granma","CU-12"),15:("Santiago de Cuba","CU-13"),16:("Guantánamo","CU-14")}
PN={v[0].replace("ü","u").replace("Guantánamo","Guantámano"):k for k,v in PROV.items()}
def get(u):
    for i in range(4):
        try:
            r=subprocess.run(["curl","-s","-m","60","-A",UA,u],capture_output=True); 
            if r.returncode==0 and len(r.stdout)>5000: time.sleep(3); return r.stdout.decode("utf-8","replace")
        except Exception: pass
        time.sleep(5+5*i)
    raise RuntimeError("fetch failed "+u)
def norm(x):
    x=unicodedata.normalize("NFKD",x or "").encode("ascii","ignore").decode().lower()
    x=re.sub(r"\b(de|del|la|el)\b"," ",x); return re.sub(r"[^a-z0-9]","",x)
def fld(cls,r):
    m=re.search(r'views-field-'+cls+r'.*?<(?:div|span) class="field-content">(.*?)</(?:div|span)>\s*</(?:div|h4)>',r,re.S)
    return html.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",m.group(1)))).strip() or None if m else None
def tpp_id(k): return "cu-tpp-"+norm(PROV[k][0])
f=f"{ROOT}/data/cu/cu_courthouses.jsonl"; R=[json.loads(l) for l in open(f)]
have={norm(r["name"]) for r in R}|{r["court_id"] for r in R}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); out=[]
def row(cid,rt,name,level,k,addr,phone,email,parent,src):
    pv,sub=PROV[k]
    return {"court_id":cid,"record_type":rt,"name":name,"name_local":None,"level":level,"court_system":"national","country_code":"CU","subdivision":sub,
            "jurisdiction":f"Provincia {pv}","parent_court_id":parent,"address":{"street":addr,"city":None,"postcode":None,"region":pv,"country":"CU"},
            "geo":{"lat":None,"lon":None},"phone":phone,"email":email,"website":None,"wikidata":None,"place_ids":[],"source_url":src,"source_kind":"official","site_policy":POL,"retrieved_at":now}
# provincial courts, one per province filter
for k in PROV:
    s=get(f"{URL}?field_provincia_target_id={k}")
    blk=s[s.find('class="view-page-tribunales-prov"'):s.find("block-views-block-tribunales-provinciales-block-1")]
    for r in blk.split('<div class="col-lg-4 views-row">')[1:]:
        name=fld("title",r)
        if not name or "PROVINCIAL" not in name.upper(): continue
        nm="Tribunal Provincial Popular de "+PROV[k][0]
        if norm(nm) in have or tpp_id(k) in have: continue
        have.add(norm(nm)); out.append(row(tpp_id(k),"courthouse",nm,"appellate",k,fld("field-direccion",r),fld("field-telefono",r),fld("field-correo-electronico",r),"cu-supreme-court",f"{URL}?field_provincia_target_id={k}"))
# all salas / municipal courts / sections
s=get(URL); blk=s[s.find("block-views-block-tribunales-provinciales-block-1"):]
for r in blk.split('<div class="col-lg-4 views-row">')[1:]:
    name=fld("title",r); pv=fld("field-provincia",r)
    if not name or not pv: continue
    k=PN.get(pv) or next((kk for kk,v in PROV.items() if norm(v[0])==norm(pv)),None)
    if not k: continue
    name=re.sub(r"^-\s*","",name)
    if name.lower().startswith("sala"):
        full=f"{name} — Tribunal Provincial Popular de {PROV[k][0]}"; cid="cu-tpp-"+norm(PROV[k][0])+"-"+norm(name)[:50]; rt="court_body"; lvl="appellate"; parent=tpp_id(k)
    else:
        full=name; cid="cu-"+norm(name)[:60]; rt="courthouse"; lvl="first_instance"; parent=tpp_id(k)
    if norm(full) in have or cid in have: continue
    have.add(norm(full)); have.add(cid)
    out.append(row(cid,rt,full,lvl,k,fld("field-direccion",r),fld("field-telefono",r),fld("field-correo-electronico",r),parent,URL))
with open(f,"a") as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+"\n")
print("CU courts new",len(out),"(",sum(o['record_type']=='courthouse' for o in out),"courthouses,",sum(o['record_type']=='court_body' for o in out),"salas )")
