"""Uruguay: sitting judges (Ministros SCJ, Ministros de Tribunales de Apelaciones, Jueces Letrados, Jueces de Paz, de Faltas,
de Conciliación, suplentes) from the official Poder Judicial "Lista completa de autoridades" PDF
https://www.poderjudicial.gub.uy/sites/default/files/autoridades/listaautoridades.pdf (linked from every Guía de oficinas page).
ONLY judicial office holders are kept (role starts with Ministro/Juez/Miembros Militares SCJ); secretaries, actuarios, defensores,
technical staff and all phone/e-mail data are dropped. court_id is matched to uy_courthouses rows (guía de oficinas) by fuzzy name;
unmatched rows point at the generic body (uy-court-of-appeal / uy-lower-court) with court_name = PDF section heading, needs_review."""
import json,re,subprocess,datetime,unicodedata,difflib,os
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
URL="https://www.poderjudicial.gub.uy/sites/default/files/autoridades/listaautoridades.pdf"
RAW=f"{ROOT}/rules/raw/uy/listaautoridades.pdf"
POL="robots_ignored_per_user_authorization (robots.txt is Drupal default)|poderjudicial.gub.uy official list of authorities (public roster PDF); only judge names/titles kept|single download"
if not os.path.exists(RAW): subprocess.run(["curl","-s","-m","120","-A",UA,"-o",RAW,URL],check=True)
txt=subprocess.run(["pdftotext","-layout",RAW,"-"],capture_output=True,text=True).stdout
pdate=(re.search(r"(\d\d/\d\d/\d{4})",txt) or [None,None])[1]
def norm(x):
    x=unicodedata.normalize("NFKD",x or "").encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",re.sub(r"\b(de|del|la|el|los|las|y|en|lo|a|o|s|t|turnos?|seccion|sec)\b"," ",x))
AB=[(r"\bJdos?\.\s*","Juzgado "),(r"\bLdos?\.\s*","Letrado "),(r"\bTrib\.\s*","Tribunal "),(r"\bApel\.\s*","Apelaciones "),(r"\bSecc?\.\s*","Sección "),
    (r"\bDptal\.\s*","Departamental "),(r"\bCap\.\s*","Capital "),(r"\bInt\.\s*","Interior "),(r"\bPaz\b","Paz "),(r"(\d+)\s*[aº°o]\.?","\\1 "),(r"\b1ra\b|\b1er\b","1")]
def expand(h):
    for a,b in AB: h=re.sub(a,b,h)
    return h
C=[json.loads(l) for l in open(f"{ROOT}/data/uy/uy_courthouses.jsonl")]
cand=[(norm(re.sub(r"(\d+)\s*[ªºo°]","\\1",c["name"])),c["court_id"]) for c in C if c["court_id"].startswith("uy-") and (c.get("source_url") or "").startswith("https://www.poderjudicial")]
def match(h):
    n=norm(expand(h)); best=(0,None)
    for cn,cid in cand:
        r=difflib.SequenceMatcher(None,n,cn).ratio()
        if r>best[0]: best=(r,cid)
    return best if best[0]>=0.86 else (best[0],None)
ROLE=re.compile(r"^(MINISTRO S\.C\. de J\.|Ministro Trib\.Apela\.(?:\(Supl\))?|Juez[^ ].*?|Juez .*?|Miembros Militares SCJ)$")
def titlecase(s): return " ".join(w.capitalize() if w.isupper() or w.islower() else w for w in s.split())
lines=txt.split("\n"); head=None; blanks=0; out=[]
J=f"{ROOT}/data/uy/uy_judges.jsonl"; E=[json.loads(l) for l in open(J)]
have={norm(e["name"]) for e in E}|{e["judge_id"] for e in E}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); unmatched=set(); mcache={}
for ln in lines:
    if not ln.strip(): blanks+=1; continue
    if "\f" in ln: ln=ln.replace("\f","")
    if not ln.startswith(" ") and blanks>=2 and "@" not in ln and not ln.startswith("Tel"):
        head=ln.strip(); 
    blanks=0
    if not ln.startswith(" ") or "Página:" in ln: continue
    parts=re.split(r"\s{2,}",ln.strip())
    if len(parts)<2 or not ROLE.match(parts[0]): continue
    role,nm=parts[0],parts[1]; rem=parts[2] if len(parts)>2 else ""
    nm=re.sub(r"^(Dr/a\.|Lic|Esc\.|Dra?\.)\s*","",nm).strip()
    if "," not in nm or re.search(r"VACANTE|RESERVADO",nm): continue
    sur,giv=[x.strip() for x in nm.split(",",1)]
    full=f"{titlecase(giv)} {titlecase(sur)}"
    key=norm(giv.split()[0]+" "+sur)
    if key in have or norm(full) in have: continue
    if head not in mcache: mcache[head]=match(head)
    sc,cid=mcache[head]
    if role.startswith("MINISTRO S.C.") or role.startswith("Miembros Militares"): cid="uy-supreme-court"; pt="chief" if "PRESIDENTE" in rem else "associate"
    elif role.startswith("Ministro"): pt="appellate"; cid=cid or "uy-court-of-appeal"
    else: pt="trial" if "Supl" not in role else "substitute"; cid=cid or "uy-lower-court"
    if "Supl" in role: pt="substitute"
    if mcache[head][1] is None and not cid=="uy-supreme-court": unmatched.add(head)
    jid="uy-"+re.sub(r"[^a-z0-9]+","-",unicodedata.normalize("NFKD",full).encode("ascii","ignore").decode().lower()).strip("-")
    if jid in have: jid+="-"+norm(head)[:20]
    have|={key,norm(full),jid}
    out.append({"judge_id":jid,"court_id":cid,"court_name":head,"name":full,"title":role+(f" ({rem})" if rem else ""),"position_type":pt,"term_start":None,"term_end":None,
        "status":"sitting","roster_url":URL,"source_url":URL,"site_policy":POL,"retrieved_at":now,"roster_date":pdate,
        "needs_review":cid in("uy-lower-court","uy-court-of-appeal") or (cid!="uy-supreme-court" and sc<0.95),"court_match_score":(None if cid=="uy-supreme-court" else round(sc,3)),"extraction":"pdftotext -layout of official authorities list; name order converted from 'SURNAMES, Given' (source has no accents)",
        "license":"official public information; no licence stated"})
with open(J,"a") as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+"\n")
from collections import Counter
print("UY judges new",len(out),Counter(o["position_type"] for o in out),"needs_review",sum(o["needs_review"] for o in out),"unmatched sections",len(unmatched))
print(sorted(unmatched)[:30])
