"""Download E&W court/tribunal forms listed in endomorphosis/ipfs_uk_courts (OGL/Crown copyright) -> forms/gb/<sha256>.<ext>; resumable. Rows -> data/gb/gb_forms.jsonl"""
import sys, os, json, hashlib, urllib.request, time
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
import pandas as pd
OUT = f"{ROOT}/data/gb/gb_forms.jsonl"; DIR = f"{ROOT}/forms/gb"; os.makedirs(DIR, exist_ok=True)
f = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_uk/data/forms-00000.parquet")
done = {r["form_id"] for r in rjl(OUT)}
CAT_BODY = {"family": "gb-ew-family-court", "civil": "gb-ew-county-court", "criminal": "gb-ew-crown-court", "tribunal": "gb-ew-tribunals-first-tier"}
n = 0
for r in f.itertuples():
    if r.form_id in done: continue
    base = dict(form_id=r.form_id, court_id=CAT_BODY.get(str(r.category)), jurisdiction="GB-EAW", form_number=r.form_number if isinstance(r.form_number, str) else None, title=r.title, category=r.category,
                language=r.language, revision_date=str(r.version_date) if r.version_date is not None else None, file_format=r.file_format, source_url=r.url, index_url=r.source_url, license=r.license,
                upstream="endomorphosis/ipfs_uk_courts", upstream_sha256=r.file_sha256 if isinstance(r.file_sha256, str) else None)
    if not isinstance(r.file_sha256, str):
        base.update(pdf_path=None, pdf_sha256=None, file_bytes=None, site_policy="not_downloaded:landing_page_only", retrieved_at=NOW()); 
        with open(OUT, "a") as o: o.write(json.dumps(base) + "\n")
        continue
    try:
        b = get(r.url, delay=2.0, binary=True, timeout=90)
    except Exception as e:
        print("ERR", r.url, e, flush=True); time.sleep(5); continue
    sha = hashlib.sha256(b).hexdigest(); ext = r.file_format if r.file_format in ("pdf", "docx", "odt", "rtf") else "bin"
    p = f"{DIR}/{sha}.{ext}"
    open(p, "wb").write(b)
    base.update(pdf_path=f"forms/gb/{sha}.{ext}", pdf_sha256=sha, file_bytes=len(b), sha_matches_upstream=(sha == r.file_sha256), site_policy="robots_absent_allowed", retrieved_at=NOW())
    with open(OUT, "a") as o: o.write(json.dumps(base) + "\n")
    n += 1
    if n % 25 == 0: print("downloaded", n, flush=True)
print("done", n)
