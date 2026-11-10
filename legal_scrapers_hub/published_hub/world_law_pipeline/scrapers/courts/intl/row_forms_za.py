"""South Africa court forms from justice.gov.za /forms/ pages (li items with PDF/DOC links). Brochures/guides/rules/regulations/acts filtered -> data/za/za_rejected_brochures.jsonl.
-> forms/za/<sha>.<ext>, data/za/za_forms.jsonl"""
import sys, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
B = "https://www.justice.gov.za/forms/"
PAGES = [("form_hcur.htm", "za-high-court", "High Court Uniform Rules forms"), ("form_hcur_other.htm", "za-high-court", "High Court Uniform Rules - other forms"), ("form_mcr.htm", "za-magistrates-courts", "Magistrates' Courts Rules forms"),
         ("form_mnt.htm", "za-magistrates-courts", "Maintenance forms"), ("form_dva.htm", "za-magistrates-courts", "Domestic Violence forms"), ("form_scc.htm", "za-small-claims-courts", "Small Claims Court forms"),
         ("form_pha.html", "za-magistrates-courts", "Protection from Harassment forms"), ("form_cj.html", "za-magistrates-courts", "Child Justice and Children's Act forms"), ("form_expungement.html", None, "Expungement of criminal record forms"),
         ("form_mediation.html", None, "Mediation forms"), ("../mc/mc-index.html", "za-magistrates-courts", "Magistrate's Court civil section forms")]
BAD = re.compile(r"brochure|guideline|booklet|pamphlet|handbook|manual|annual report|circular|\bfaq|information (sheet|leaflet)|flyer|poster|infographic|presentation|\bguide\b|leaflet|newsletter|^(act \d+|regulations?|amendment)\b|/legislation/|read more", re.I)
def main():
    os.makedirs(f"{ROOT}/forms/za", exist_ok=True); seen = {}; rej = []; out = []
    for pg, cid, cat in PAGES:
        try: b, u, pol = polite_get(urllib.parse.urljoin(B, pg), delay=2)
        except Exception as e: print("ERR", pg, e); continue
        if not b: print("no page", pg); continue
        s = BeautifulSoup(b, "html.parser")
        for li in s.find_all("li"):
            for a in li.find_all("a", href=re.compile(r"\.(pdf|docx?|xlsx?)(\?|$)", re.I)):
                href = urllib.parse.urljoin(urllib.parse.urljoin(B, pg), a["href"].strip()); lt = re.sub(r"\s+", " ", a.get_text(" ", strip=True)); lang = "af" if re.fullmatch(r"(?i)afr(ikaans)?", lt) else "en"
                if href in seen: continue
                full = re.sub(r"\s+", " ", li.get_text(" ", strip=True)); title = full if lang == "en" else (seen_title if "seen_title" in dir() else full)
                title = re.sub(r"\s*\d+(\.\d+)?\s*(KB|MB)\b.*$", "", title).strip(" -:[]")[:220] or lt
                seen[href] = title
                if BAD.search(title) or BAD.search(urllib.parse.unquote(href)): rej.append(dict(title=title, source_url=href, reason="not a fillable court form (brochure/guide/act/regulation/rules)")); continue
                d, eu, p2 = polite_get(href, delay=2.0, binary=True)
                if not d or len(d) < 500 or d[:5] == b"<!DOC": continue
                ext = re.search(r"\.(pdf|docx?|xlsx?)", href, re.I).group(1).lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/za/{sh}.{ext}"
                if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
                if any(o["pdf_sha256"] == sh for o in out): continue
                m = re.search(r"\b(J\s?\d{2,4}[A-Z]?|Form\s*[A-Z0-9]+|Form\s*\d+\s*[A-Z]?)\b", lt + " " + title)
                out.append(dict(form_id=f"za-{sh[:16]}", court_id=cid, jurisdiction="ZA", form_number=m.group(1) if m else None, title=title, category=cat, language=lang, file_format=ext, pdf_path=path, pdf_sha256=sh, file_bytes=len(d), source_url=eu,
                                index_url=urllib.parse.urljoin(B, pg), license="Department of Justice and Constitutional Development (South Africa) published forms; public information, reuse per site terms", site_policy=p2, retrieved_at=NOW()))
        print(pg, len(out), len(rej), flush=True)
    os.makedirs(f"{ROOT}/data/za", exist_ok=True); wjl(f"{ROOT}/data/za/za_forms.jsonl", out); wjl(f"{ROOT}/data/za/za_rejected_brochures.jsonl", rej); print("ZA forms", len(out), "rejected", len(rej))
    for r in rej: print(" rej:", r["title"][:80])
if __name__ == "__main__": main()
