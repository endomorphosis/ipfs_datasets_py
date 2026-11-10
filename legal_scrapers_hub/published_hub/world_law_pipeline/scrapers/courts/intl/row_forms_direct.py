"""Direct form-index scraper: fetch given index pages, download linked documents with form-like titles (brochure/guide/report filtered out). python row_forms_direct.py NZ"""
import sys, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
DOC = re.compile(r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|/[0-9a-f-]{36}|$)", re.I)
BAD = re.compile(r"gu[ií][aá]s?\b|cartilla|folleto|instructivo|informe anual|weekly report|brochure|guide\b|guidance|easy.?read|large print|workbook|factsheet|fact sheet|booklet|leaflet|practice note|practice direction|annual report|referencing|what to expect|legal advice and support|information about|making parenting|going through|lawyers working|media|press|report\b", re.I)
CFG = {"NZ": dict(pages=["https://www.justice.govt.nz/courts/going-to-court/without-a-lawyer/representing-yourself-civil-high-court/documents-prescribed-forms-and-useful-templates/", "https://www.justice.govt.nz/courts/civil/forms-and-fees/dc-rules-dc-act-2016/"],
                  lang="en", lic="NZ Ministry of Justice (justice.govt.nz) published court forms/templates; CC-BY 4.0 / NZ Government open access framework", court_id=None),
       "CO": dict(pages=["https://www.ramajudicial.gov.co/portal/atencion-al-usuario/guias-juridicas-generales"], lang="es", lic="Rama Judicial de Colombia (ramajudicial.gov.co) published formats; Colombian official works (Ley 23/1982 art. 41)", court_id=None),
       "AR": dict(pages=["https://servicios.csjn.gov.ar/formularios/ori.html"], lang="es", lic="Corte Suprema de Justicia de la Nación (csjn.gov.ar) published form; Ley 11.723 art. 5", court_id="ar-csjn")}
def main(cc):
    c = CFG[cc]; low = cc.lower(); os.makedirs(f"{ROOT}/forms/{low}", exist_ok=True); out = []; rej = []; seen = set()
    for page in c["pages"]:
        b, u, pol = polite_get(page, delay=2.0)
        if not b: print("page failed", page); continue
        s = BeautifulSoup(b, "html.parser"); m = s.find("main") or s
        for a in m.find_all("a", href=True):
            h = urllib.parse.urljoin(u, a["href"]).split("#")[0]
            if not DOC.search(h) or h in seen: continue
            seen.add(h); t = re.sub(r"\s*\[?\(?(PDF|DOCX?|XLSX?|RTF)[^\]\)]*[\]\)]?\s*$", "", a.get_text(" ", strip=True), flags=re.I).strip() or urllib.parse.unquote(h.rsplit("/", 1)[-1])
            t = re.sub(r"\(external link\)", "", t).strip()
            if BAD.search(t): rej.append(dict(title=t, source_url=h, reason="not a form/template (guide/brochure/report)")); continue
            d, eu, p2 = polite_get(h, delay=2.0, binary=True, maxbytes=40_000_000)
            if not d or len(d) < 500: continue
            ext = DOC.search(h).group(1).lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/{low}/{sh}.{ext}"
            if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
            if any(o["pdf_sha256"] == sh for o in out): continue
            fn = (re.search(r"^(?:Form\s*)?([A-Z]?\d{1,3}[A-Z]?)\s*-\s", t) or [None, None])[1]
            out.append(dict(form_id=f"{low}-{sh[:16]}", court_id=c["court_id"], jurisdiction=cc, form_number=fn, title=t, category=page.rstrip("/").rsplit("/", 1)[-1][:80], language=c["lang"], file_format=ext, pdf_path=path, pdf_sha256=sh, file_bytes=len(d),
                            source_url=eu, index_url=page, license=c["lic"], site_policy=p2, retrieved_at=NOW()))
    wjl(f"{ROOT}/data/{low}/{low}_forms.jsonl", out); wjl(f"{ROOT}/data/{low}/{low}_rejected_brochures.jsonl", rej + rjl(f"{ROOT}/data/{low}/{low}_rejected_brochures.jsonl")); print(cc, "forms", len(out), "rejected", len(rej))
if __name__ == "__main__": main(sys.argv[1])
