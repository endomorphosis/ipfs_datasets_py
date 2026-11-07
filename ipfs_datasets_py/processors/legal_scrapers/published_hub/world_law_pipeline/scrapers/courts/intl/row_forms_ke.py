"""Kenya Judiciary forms (judiciary.go.ke/forms/, WordPress Download Manager links). Court procedural forms kept; staff/HR/feedback/guide items -> ke_rejected_brochures.jsonl."""
import sys, hashlib, urllib.parse, re
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
IDX = "https://judiciary.go.ke/forms/"
KEEP = {"small-claims-court-form": ("Small Claims Court form", "small-claims-court", "small-claims"), "probate-and-administration-central-electronic-registry-form": ("Probate and Administration Central Electronic Registry form", "high-court", "probate")}
REJ = {"customer-feedback-form-for-the-environment-and-land-court": "customer feedback survey, not a procedural court form", "office-of-the-judiciary-ombudsman-client-complaint-form": "administrative complaint form to the Judiciary Ombudsman, not a court filing", "steps-for-use-in-microsoft-teams-skype-and-zoom": "user guide, not a form", "wealth-declaration-form": "judiciary staff wealth declaration (HR/integrity), not a court form"}
def main():
    b, u, pol = polite_get(IDX, delay=2.0); h = b.decode("utf-8", "ignore"); os.makedirs(f"{ROOT}/forms/ke", exist_ok=True); out = []; rej = []
    links = sorted(set(re.findall(r"https://judiciary\.go\.ke/download/([a-z0-9\-]+)/\?wpdmdl=(\d+)", h)))
    for slug, wid in links:
        url = f"https://judiciary.go.ke/download/{slug}/?wpdmdl={wid}"
        if slug in REJ or slug not in KEEP: rej.append(dict(title=slug.replace("-", " ").title(), source_url=f"https://judiciary.go.ke/download/{slug}/", reason=REJ.get(slug, "not a court procedural form"))); continue
        d, eu, p2 = polite_get(url, delay=2.0, binary=True, maxbytes=40_000_000)
        if not d or len(d) < 500 or d[:5] == b"<!DOC" or d[:5].lower() == b"<html": print("download failed", slug, len(d or b"")); continue
        ext = "pdf" if d[:4] == b"%PDF" else "docx" if d[:2] == b"PK" else "doc" if d[:4] == b"\xd0\xcf\x11\xe0" else "bin"; sh = hashlib.sha256(d).hexdigest(); path = f"forms/ke/{sh}.{ext}"
        if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
        t, court, cat = KEEP[slug]
        out.append(dict(form_id=f"ke-{sh[:16]}", court_id=f"ke-{court}", jurisdiction="KE", form_number=None, title=t, category=cat, language="en", file_format=ext, pdf_path=path, pdf_sha256=sh, file_bytes=len(d), source_url=f"https://judiciary.go.ke/download/{slug}/", index_url=IDX, license="Judiciary of Kenya public website; reuse with attribution", site_policy=p2, retrieved_at=NOW()))
    os.makedirs(f"{ROOT}/data/ke", exist_ok=True); wjl(f"{ROOT}/data/ke/ke_forms.jsonl", out); wjl(f"{ROOT}/data/ke/ke_rejected_brochures.jsonl", rej); print("KE forms", len(out), "rejected", len(rej))
main()
