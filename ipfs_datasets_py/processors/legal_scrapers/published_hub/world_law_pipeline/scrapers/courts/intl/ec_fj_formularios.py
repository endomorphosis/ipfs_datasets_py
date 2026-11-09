"""Ecuador: official court forms from the Consejo de la Judicatura / Función Judicial forms page
https://www.funcionjudicial.gob.ec/formularios/ (live). Skips the notary-accreditation form and the user manual (not court forms).
Dedupe on source_url and sha256 against data/ec/ec_forms.jsonl."""
import json,re,html,hashlib,os,subprocess,time,datetime
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
IDX="https://www.funcionjudicial.gob.ec/formularios/"
POL="robots_ignored_per_user_authorization|funcionjudicial.gob.ec official Consejo de la Judicatura site; public forms, no licence stated|polite 3 s/request"
CAT={"acta":"hearing-record-template","pension":"family-claim","monitorio":"civil-claim","copias":"court-service-request","quejas":"court-service-complaint"}
def get(u,binary=False):
    r=subprocess.run(["curl","-s","-L","-m","90","-A",UA,u],capture_output=True); time.sleep(3)
    if r.returncode: raise RuntimeError(u)
    return r.stdout if binary else r.stdout.decode("utf-8","replace")
t=get(IDX); F=f"{ROOT}/data/ec/ec_forms.jsonl"; E=[json.loads(l) for l in open(F)]
seen={e["source_url"] for e in E}|{e.get("pdf_sha256") for e in E}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); out=[]; os.makedirs(f"{ROOT}/forms/ec",exist_ok=True)
for m in re.finditer(r'href="(https://www\.funcionjudicial\.gob\.ec/resources/[^"]+\.(pdf|docx?))"',t):
    u,ext=m.group(1),m.group(2).lower()
    if re.search(r"notario|manual",u,re.I) or u in seen: continue
    raw=re.sub(r"<a [^>]*$","",t[max(0,m.start()-600):m.start()])
    seg=html.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",raw))).strip()
    nodes=[html.unescape(x).strip() for x in re.findall(r">([^<]+)",raw) if x.strip()]; title=nodes[-1] if nodes else ""
    if "quejas" in u.lower(): title="Formulario 06: Solicitud de Reclamo - Quejas"
    title=re.sub(r"^Descargar\s+","",title); title=re.sub(r"\s*Conozca las direcciones.*$","",title).strip() or u.split("/")[-1]
    b=get(u,True)
    if len(b)<1000: continue
    h=hashlib.sha256(b).hexdigest()
    if h in seen: continue
    p=f"forms/ec/{h}.{ext}"; open(f"{ROOT}/{p}","wb").write(b); seen|={u,h}
    fn=(re.search(r"Formulario\s+(\d+)",title) or [None,None])[1]
    cat=next((v for k,v in CAT.items() if k in (title+u).lower()),"official-court-forms")
    out.append({"form_id":"ec-"+h[:16],"court_id":None,"jurisdiction":"EC","form_number":("F"+fn.zfill(2)) if fn else None,"title":title,"category":cat,"language":"es",
        "file_format":ext,"pdf_path":p,"pdf_sha256":h,"file_bytes":len(b),"source_url":u,"index_url":IDX,"issuer":"Consejo de la Judicatura (Función Judicial del Ecuador)",
        "license":"official public forms; no licence stated","site_policy":POL,"retrieved_at":now,"needs_review":False})
with open(F,"a") as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+"\n")
print("EC forms new",len(out),[o["title"] for o in out])
