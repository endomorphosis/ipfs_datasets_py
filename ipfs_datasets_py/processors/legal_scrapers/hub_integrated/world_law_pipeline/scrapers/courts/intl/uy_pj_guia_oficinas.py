"""Uruguay: courts (Juzgados Letrados, Juzgados de Paz, Tribunales de Apelaciones, TCA, Centros de Mediación) with address,
phone and office e-mail, from the official Poder Judicial office guide https://www.poderjudicial.gub.uy/guia-de-oficinas
(Drupal view, ?page=N, live). Administrative offices (archives, DGSA, defensoría, etc.) are skipped. Dedupe on normalized name/court_id."""
import json,re,html,time,datetime,subprocess,unicodedata
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
BASE="https://www.poderjudicial.gub.uy"; URL=BASE+"/guia-de-oficinas"
POL="robots_ignored_per_user_authorization (robots.txt is Drupal default)|poderjudicial.gub.uy official Poder Judicial office guide, public directory information|polite 2.5 s/request"
DEP={"Artigas":"AR","Canelones":"CA","Cerro Largo":"CL","Colonia":"CO","Durazno":"DU","Flores":"FS","Florida":"FD","Lavalleja":"LA","Maldonado":"MA","Montevideo":"MO",
     "Paysandú":"PA","Río Negro":"RN","Rivera":"RV","Rocha":"RO","Salto":"SA","San José":"SJ","Soriano":"SO","Tacuarembó":"TA","Treinta y Tres":"TT"}
def get(u):
    for i in range(4):
        r=subprocess.run(["curl","-s","-m","60","-A",UA,u],capture_output=True)
        if r.returncode==0 and len(r.stdout)>5000: time.sleep(2.5); return r.stdout.decode("utf-8","replace")
        time.sleep(5+5*i)
    raise RuntimeError("fetch failed "+u)
def norm(x):
    x=unicodedata.normalize("NFKD",x or "").encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",re.sub(r"\b(de|del|la|el|los|las|y)\b"," ",x))
def fld(name,a):
    m=re.search(r'field--name-field-'+name+r'\b.*?<div class="field__item">(.*?)</div>',a,re.S)
    if not m: return None
    v=html.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",m.group(1)))).strip(); return v or None
def level(n):
    l=n.lower()
    if "suprema corte" in l: return "supreme",None
    if "contencioso administrativo" in l and "tribunal" in l: return "administrative","uy-supreme-court"
    if "tribunal" in l and "apelaci" in l: return "appellate","uy-court-of-appeal"
    if "mediaci" in l: return "other","uy-supreme-court"
    if "paz" in l: return "trial_limited","uy-lower-court"
    if "adolescente" in l: return "juvenile","uy-lower-court"
    if "familia" in l: return "family","uy-lower-court"
    if "aduana" in l or "tributari" in l or "fiscal" in l and "juzgado" in l: return "tax","uy-lower-court"
    if "contencioso administrativo" in l: return "administrative","uy-lower-court"
    return "trial_general","uy-lower-court"
COURT=re.compile(r"juzgado|tribunal|mediaci|suprema corte|faltas|concurso",re.I)
f=f"{ROOT}/data/uy/uy_courthouses.jsonl"; R=[json.loads(l) for l in open(f)]
have={norm(r["name"]) for r in R}|{r["court_id"] for r in R}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); out=[]; seen=0; skipped=[]
p=0
while p<80:
    s=get(f"{URL}?page={p}")
    arts=re.findall(r'<article data-history-node-id="\d+" class="node node--type-oficinas.*?</article>',s,re.S)
    if not arts: break
    for a in arts:
        seen+=1
        m=re.search(r'<h2 class="node__title">.*?href="(/guia-de-oficinas/[^"]+)".*?hreflang="es">(.*?)</a>',a,re.S)
        if not m: continue
        path,name=m.group(1),html.unescape(re.sub(r"\s+"," ",m.group(2))).strip()
        if not COURT.search(name) or name.startswith("Intendencia") or name.startswith("Suprema Corte de Justicia"): skipped.append(name); continue  # SCJ already present as uy-supreme-court / wikidata row
        dep=fld("departamento",a); loc=fld("localidad",a); addr=fld("direccion",a); tel=fld("telefono",a); mail=fld("correo-electronico",a)
        if loc and "@" in loc: mail=mail or loc; loc=None
        cid="uy-"+(DEP.get(dep,"xx").lower())+"-"+re.sub(r"[^a-z0-9]+","-",unicodedata.normalize("NFKD",path.split("/")[-1]).encode("ascii","ignore").decode().lower()).strip("-")[:70]
        if norm(name) in have or cid in have: continue
        have.add(norm(name)); have.add(cid); lv,parent=level(name)
        out.append({"court_id":cid,"record_type":"courthouse","name":name,"name_local":name,"level":lv,"court_system":"national","country_code":"UY",
            "subdivision":("UY-"+DEP[dep]) if dep in DEP else "UY","jurisdiction":(f"Departamento de {dep}" if dep else None),"parent_court_id":parent,
            "address":{"street":addr,"city":loc,"postcode":None,"region":dep,"country":"UY"},"geo":{"lat":None,"lon":None},"phone":tel,"email":mail,
            **({"operational_status":'abolished (marked "Suprimido" in source)'} if "suprimid" in name.lower() else {}),"website":BASE+path,"wikidata":None,"place_ids":[],"source_url":f"{URL}?page={p}","source_kind":"official","site_policy":POL,"retrieved_at":now})
    if f"page={p+1}" not in s: break
    p+=1
with open(f,"a") as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+"\n")
print("UY pages",p+1,"entries",seen,"new courts",len(out),"skipped non-court",len(skipped))
from collections import Counter; print(Counter(o["level"] for o in out)); print("skipped sample",skipped[:40])
