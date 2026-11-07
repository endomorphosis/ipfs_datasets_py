"""Forms for LatAm / South & SE Asia from official index pages. APPENDS to data/<cc>/<cc>_forms.jsonl, dedup by sha256
(never overwrites existing rows). Keeps only court-user forms (per-country KEEP/DROP regex). python row_forms_lsa.py PK"""
import sys, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
DOC = re.compile(r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", re.I)
CFG = {
 "PK": dict(pages=["https://sindhhighcourt.gov.pk/downloads.php"], lang="en", court_id=None, jur="PK-SD",
            keep=r"form|proforma|application|request", drop=r"circular|notification|administration|dissemination|uniform|rules|performa click|\bACR\b|pension|performance|al-mizan|identity card|leave|PER\b|widow|death grant|skill",
            lic="Sindh High Court (sindhhighcourt.gov.pk) published forms; Pakistan government work, no licence stated"),
  "CL": dict(pages=[], urls=[("https://secretariadegenero.pjud.cl/images/stignd/recursos/infografias/vcm/setRecomendaciones/ANEXO1Formulario_denuncia.pdf", "Formato tipo formulario de denuncia de violencia de género / violencia intrafamiliar")],
            lang="es", court_id=None, jur="CL", keep=".", drop="^$", lic="Poder Judicial de Chile (pjud.cl) published form; Ley 17.336 art. 11 (official texts)"),
 "JM": dict(pages=["https://parishcourt.gov.jm/content/court-forms", "https://supremecourt.gov.jm/supreme-court-forms"], lang="en", court_id=None, jur="JM", delay=10.0,
            keep=r"\.pdf|\.docx?|form", drop=r"Proc\.-Judicature|Bail%20Act|Strategic|Business%20Plan|annual|report|newsletter",
            lic="Judiciary of Jamaica (parishcourt.gov.jm / supremecourt.gov.jm) published court forms; Crown copyright, no licence stated"),
}
def main(cc):
    c = CFG[cc]; low = cc.lower(); os.makedirs(f"{ROOT}/forms/{low}", exist_ok=True)
    fp = f"{ROOT}/data/{low}/{low}_forms.jsonl"; old = rjl(fp) if os.path.exists(fp) else []
    shas = {o["pdf_sha256"] for o in old}; out = []; seen = set()
    for page in c["pages"]:
        b, u, pol = polite_get(page, delay=c.get('delay', 2.0))
        if not b: print("page failed", page); continue
        for a in BeautifulSoup(b, "html.parser").find_all("a", href=True):
            h = urllib.parse.urljoin(u, a["href"].strip()).split("#")[0]
            if not DOC.search(h) or h in seen: continue
            seen.add(h); t = a.get_text(" ", strip=True) or urllib.parse.unquote(h.rsplit("/", 1)[-1])
            if not re.search(c["keep"], t + " " + h, re.I) or re.search(c["drop"], t + " " + urllib.parse.unquote(h), re.I): continue
            d, eu, p2 = polite_get(h, delay=c.get('delay', 2.0), binary=True, maxbytes=40_000_000)
            if not d or len(d) < 500: continue
            ext = DOC.search(h).group(1).lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/{low}/{sh}.{ext}"
            if sh in shas: continue
            shas.add(sh)
            if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
            out.append(dict(form_id=f"{low}-{sh[:16]}", court_id=c["court_id"], jurisdiction=c["jur"], form_number=None, title=t[:200], category=None,
                language=c["lang"], file_format=ext, pdf_path=path, pdf_sha256=sh, file_bytes=len(d), source_url=eu, index_url=page,
                license=c["lic"], site_policy=p2, retrieved_at=NOW()))
    for h, t in c.get("urls", []):
        d, eu, p2 = polite_get(h, delay=c.get('delay', 2.0), binary=True, maxbytes=40_000_000)
        if not d or len(d) < 500: continue
        ext = DOC.search(h).group(1).lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/{low}/{sh}.{ext}"
        if sh in shas: continue
        shas.add(sh)
        if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
        out.append(dict(form_id=f"{low}-{sh[:16]}", court_id=c["court_id"], jurisdiction=c["jur"], form_number=None, title=t, category=None, language=c["lang"], file_format=ext,
            pdf_path=path, pdf_sha256=sh, file_bytes=len(d), source_url=eu, index_url=h, license=c["lic"], site_policy=p2, retrieved_at=NOW()))
    wjl(fp, old + out); print(cc, "new forms", len(out), [o["title"][:50] for o in out])
if __name__ == "__main__": main(sys.argv[1])
