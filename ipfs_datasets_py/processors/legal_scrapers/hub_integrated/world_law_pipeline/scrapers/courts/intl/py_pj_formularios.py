"""Paraguay Poder Judicial (pj.gov.py) public forms from /contenido/466-formularios and homepage downloads."""
import sys,os,json,hashlib,datetime,re,time,urllib.request
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (+public court directory research; polite 4s crawl)"
def get(u,t=40):
    for i in range(4):
        try:
            b=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=t).read(); time.sleep(4); return b
        except Exception as e: err=e; time.sleep(5+3*i)
    raise err
IDX="https://www.pj.gov.py/contenido/466-formularios/"
ITEMS=[("https://www.pj.gov.py/images/contenido/formulario_notarios_trimestral.xlsx","Formulario de Informe Notarial Trimestral","notarial-reports",IDX,"2016-12"),
 ("https://www.pj.gov.py/images/contenido/formulario_notarios_anual.doc","Formulario de Informe Notarial Anual","notarial-reports",IDX,None),
 ("https://www.pj.gov.py/includes/descargar.php?file=ID1-79_id1_787_formatodeformulariodeentrega.pdf","Formulario para retirar antecedentes (formato de formulario de entrega)","records-requests",IDX,None),
 ("https://www.pj.gov.py/descargas/formulario-fsg001.pdf","Formulario FSG-001","general",'https://www.pj.gov.py/',None)]
POL="robots_ignored_per_user_authorization|pj.gov.py official Poder Judicial / Corte Suprema de Justicia del Paraguay website, no restrictive terms found|polite 4 s/request"
f=f"{ROOT}/data/py/py_forms.jsonl"; have={json.loads(l)["source_url"] for l in open(f)} if os.path.exists(f) else set()
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); os.makedirs(f"{ROOT}/forms/py",exist_ok=True); n=0
with open(f,"a") as fh:
    for u,t,cat,idx,rev in ITEMS:
        if u in have: continue
        try: b=get(u)
        except Exception as e: print("fail",u,e); continue
        ext=u.rsplit(".",1)[-1].lower(); sha=hashlib.sha256(b).hexdigest(); p=f"forms/py/{sha}.{ext}"
        if b[:5]==b"<!DOC" or b[:5]==b"<html": print("html not file",u); continue
        open(f"{ROOT}/{p}","wb").write(b)
        fh.write(json.dumps({"form_id":f"py-{sha[:16]}","court_id":"py-supreme-court","jurisdiction":"PY","form_number":None,"title":t,"category":cat,"language":"es",
          "revision_date":rev,"file_format":ext,"pdf_path":p,"pdf_sha256":sha,"file_bytes":len(b),"source_url":u,"index_url":idx,"source_kind":"official","site_policy":POL,
          "license":"Poder Judicial del Paraguay official form; government work, no licence stated","description":t,"retrieved_at":now},ensure_ascii=False)+"\n"); n+=1
print("PY forms new",n)
