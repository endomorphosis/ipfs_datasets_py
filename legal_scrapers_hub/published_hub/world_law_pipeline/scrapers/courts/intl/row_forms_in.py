"""Supreme Court of India forms (sci.gov.in/forms/ table; files on the official cdnbbsr.s3waas.gov.in CDN). Brochures/subscription/guidance items filtered out -> data/in/in_rejected_brochures.jsonl.
-> forms/in/<sha>.<ext>, data/in/in_forms.jsonl"""
import sys, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
BAD = re.compile(r"brochure|subscription|list of mandatory|documents required|check ?list|guideline|circular|annual report|handbook|manual|calendar|rules, 20|\brules\b", re.I)
def main():
    os.makedirs(f"{ROOT}/forms/in", exist_ok=True); b, u, pol = polite_get("https://www.sci.gov.in/forms/", delay=2)
    s = BeautifulSoup(b, "html.parser"); seen = {}; rej = []; out = []
    for tr in s.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2: continue
        a = tr.find("a", href=re.compile(r"\.(pdf|docx?|xlsx?)", re.I))
        if not a: continue
        title = re.sub(r"\s+", " ", tds[0].get_text(" ", strip=True)); href = a["href"]
        if href in seen: continue
        seen[href] = title
        if BAD.search(title): rej.append(dict(title=title, source_url=href, reason="not a fillable form/format (brochure/guidance/checklist)")); continue
        d, eu, p2 = polite_get(href, delay=2.0, binary=True)
        if not d or len(d) < 500: continue
        ext = (re.search(r"\.(pdf|docx?|xlsx?)", href, re.I).group(1) or "pdf").lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/in/{sh}.{ext}"
        if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
        if any(o["pdf_sha256"] == sh for o in out): continue
        out.append(dict(form_id=f"in-{sh[:16]}", court_id="in-supreme-court", jurisdiction="IN", form_number=(re.search(r"\bForm\s*[-–]?\s*(\d+)", title, re.I) or [None, None])[1], title=title, category="Supreme Court of India forms", language="en", file_format=ext, pdf_path=path,
                        pdf_sha256=sh, file_bytes=len(d), source_url=eu, index_url="https://www.sci.gov.in/forms/", license="Supreme Court of India public website; official forms, reuse per site terms", site_policy=p2, retrieved_at=NOW()))
    os.makedirs(f"{ROOT}/data/in", exist_ok=True); wjl(f"{ROOT}/data/in/in_forms.jsonl", out); wjl(f"{ROOT}/data/in/in_rejected_brochures.jsonl", rej); print("IN forms", len(out), "rejected", len(rej))
    for r in rej: print(" rej:", r["title"][:80])
if __name__ == "__main__": main()
