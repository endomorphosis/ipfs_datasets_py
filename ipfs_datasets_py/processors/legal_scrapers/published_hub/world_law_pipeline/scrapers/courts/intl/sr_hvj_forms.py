"""Suriname Hof van Justitie (rechtspraak.sr) public court forms (aanvraagformulieren, indieningsformulieren, verklaringen),
discovered via the site's public WordPress media listing (wp-json/wp/v2/media), official files downloaded live."""
import os,json,hashlib,datetime,re,time,urllib.request,html
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
POL="robots_ignored_per_user_authorization|rechtspraak.sr official Hof van Justitie van Suriname website, no restrictive terms found|polite 3 s/request"
def get(u,t=60):
    for i in range(3):
        try:
            b=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=t).read(); time.sleep(3); return b
        except Exception as e: err=e; time.sleep(5+5*i)
    raise err
items=[]
for page in range(1,8):
    try: d=json.loads(get(f"https://rechtspraak.sr/wp-json/wp/v2/media?per_page=100&page={page}&_fields=id,date,source_url,title,mime_type,post"))
    except Exception as e: break
    if not d: break
    items+=d
    if len(d)<100: break
KEEP=re.compile(r"FORMULIER|VERKLARING|REKEST|VERZOEKSCHRIFT|MODEL",re.I)
def cat(t):
    t=t.upper()
    if "UITTREKSEL" in t: return "register-extracts"
    if "HOGER BEROEP" in t: return "appeals"
    if "GEZAG" in t or "ECHTSCHEID" in t or "FAMILIE" in t: return "family"
    if "NALATENSCHAP" in t or "ERFENIS" in t: return "probate"
    return "general"
f=f"{ROOT}/data/sr/sr_forms.jsonl"; have=set(); shas=set()
if os.path.exists(f):
    for l in open(f): d=json.loads(l); have.add(d["source_url"]); shas.add(d["pdf_sha256"])
os.makedirs(f"{ROOT}/forms/sr",exist_ok=True); now=datetime.datetime.now(datetime.timezone.utc).isoformat(); n=0
with open(f,"a") as fh:
    for it in items:
        t=html.unescape(it["title"]["rendered"]).strip(); u=it["source_url"]
        if not KEEP.search(t) or u in have: continue
        ext=u.rsplit(".",1)[-1].lower()
        if ext not in ("pdf","doc","docx"): continue
        try: b=get(u)
        except Exception as e: print("fail",u,e); continue
        if b[:5] in (b"<!DOC",b"<html"): continue
        sha=hashlib.sha256(b).hexdigest()
        if sha in shas: continue
        shas.add(sha); p=f"forms/sr/{sha}.{ext}"; open(f"{ROOT}/{p}","wb").write(b)
        title=t[:1]+t[1:].lower() if t.isupper() else t
        fh.write(json.dumps({"form_id":f"sr-{sha[:16]}","court_id":"sr-supreme-court","jurisdiction":"SR","form_number":None,"title":title,"category":cat(t),"language":"nl",
          "revision_date":it["date"][:10],"file_format":ext,"pdf_path":p,"pdf_sha256":sha,"file_bytes":len(b),"source_url":u,"index_url":"https://rechtspraak.sr/rechtspraak/civiele-rechtspraak/kanton-civiel/",
          "source_kind":"official","site_policy":POL,"license":"Hof van Justitie van Suriname official court form; government work, no licence stated",
          "description":f"{title} (Hof van Justitie / Kantongerechten Suriname)","retrieved_at":now},ensure_ascii=False)+"\n"); n+=1
print("SR media items",len(items),"SR forms new",n)
