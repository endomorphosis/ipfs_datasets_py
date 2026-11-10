"""Federal Court (Canada) forms listed in endomorphosis/ipfs_canada_courts. fct-cf.ca is unreachable (TLS) from the box, so files are fetched from the Wayback Machine (id_ raw). forms/ca/<sha>.<ext>"""
import sys, os, json, hashlib, time, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
import pandas as pd
OUT = f"{ROOT}/data/ca/ca_forms_fc.jsonl"; DIR = f"{ROOT}/forms/ca"; os.makedirs(DIR, exist_ok=True)
f = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_ca/data/forms-00000.parquet")
done = {r["form_id"] for r in rjl(OUT)}; n = 0
for r in f.itertuples():
    if r.form_id in done: continue
    ex = dict(r.external_ids)
    base = dict(form_id=r.form_id, court_id="ca-fc", jurisdiction="CA", form_number=None, title=r.title, category=r.category, language=r.language, revision_date=None, file_format=r.file_format,
                source_url=r.url, index_url=r.source_url, license="gc-non-commercial", upstream="endomorphosis/ipfs_canada_courts", form_category_raw=ex.get("form_category"))
    try:
        b = get("https://web.archive.org/web/2026id_/" + urllib.parse.quote(r.url, safe=":/?&=%"), delay=2.0, binary=True, timeout=120)
        if len(b) < 200 or b[:5] == b"<!DOC" or b[:5] == b"<html": raise ValueError("not a file")
    except Exception as e:
        base.update(pdf_path=None, pdf_sha256=None, file_bytes=None, site_policy="download_failed:" + str(e)[:60], retrieved_at=NOW())
        open(OUT, "a").write(json.dumps(base) + "\n"); continue
    h = hashlib.sha256(b).hexdigest(); ext = r.file_format if r.file_format in ("pdf", "rtf", "docx") else "bin"
    open(f"{DIR}/{h}.{ext}", "wb").write(b)
    base.update(pdf_path=f"forms/ca/{h}.{ext}", pdf_sha256=h, file_bytes=len(b), site_policy="archive_wayback(live_tls_blocked_from_box)", retrieved_at=NOW())
    open(OUT, "a").write(json.dumps(base) + "\n"); n += 1
    if n % 20 == 0: print("downloaded", n, flush=True)
print("done", n)
