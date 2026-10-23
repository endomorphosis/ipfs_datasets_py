"""Tranche-3 OCR gate proof: take one known scanned Paser doc (Perda
No. 2/2019-ish, 4,847,358 bytes in the tranche-2 probe), run it through
the tranche-3 OCR lane end-to-end (pdf_text_ocr with ind+eng ->
doc_rows_from_text guards -> finalize_rows -> rows_to_table ->
validate_table), and record the result. This is the formal gate step
deferred from the tranche-2 probe."""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

CAMP = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "id_campaign"
sys.path.insert(0, str(CAMP))
import harvest as H  # noqa: E402
import harvest3 as H3  # noqa: E402

BASE = "https://jdih.paserkab.go.id"
TARGET_BYTES = 4847358
OUT = CAMP / "ocr_probe"

sess = H.PoliteSession()
res = {"unit": "6401 Kabupaten Paser", "lang": H3.OCR_LANG,
       "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

cands = H._detail_enum(sess, BASE + "/dokumen/peraturan",
                       r"/dokumen/view\?id=\d+", max_pages=3)
sample = []
for cand in list(cands.values())[:16]:
    r = sess.get(cand["detail_url"], timeout=150)
    m = re.search(r'href="([^"]*/common/dokumen/[^"]+\.pdf)"', r.text, re.I)
    if m:
        sample.append({"detail_url": cand["detail_url"],
                       "key": cand.get("key", ""),
                       "pdf_url": urljoin(cand["detail_url"], m.group(1))})
    if len(sample) >= 6:
        break
print("sample:", len(sample), flush=True)

target, raw = None, None
for i, doc in enumerate(sample):
    data, err = H3.download_bytes(sess, doc["pdf_url"])
    print(f"doc[{i}] bytes={len(data)} err={err!r}", flush=True)
    if len(data) == TARGET_BYTES:
        target, raw = doc, data
        break
    if i == 1 and target is None:
        target, raw = doc, data
res["target_pdf"] = target["pdf_url"] if target else None
res["bytes"] = len(raw) if raw else 0

unit = dict(bps="6401", name="Kabupaten Paser", host="jdih.paserkab.go.id",
            adapter="dokumen_view")
cand = dict(detail_url=target["detail_url"], pdf_url=target["pdf_url"],
            title="", nomor="", tahun="", key=target.get("key", ""))
t0 = time.time()
text, nbytes, err = H3.pdf_text_ocr(sess, target["pdf_url"])
res["extract_seconds"] = round(time.time() - t0, 1)
res["extract_err"] = err
res["text_chars"] = len(text)
stats = H3.ocr_stats_snapshot().get("jdih.paserkab.go.id", {})
res["ocr_stats"] = stats
rows, info = H3.doc_rows_from_text(unit, "6401", "jdih.paserkab.go.id",
                                   dict(cand, pdf_url=target["pdf_url"]), text)
res["doc_info"] = {k: info.get(k) for k in ("title", "nomor", "tahun", "rows", "mode")}
rows = H.finalize_rows(rows)
table = H.rows_to_table(rows)
errors = H.validate_table(table, jurisdiction_id="6401",
                          jurisdiction_name="Kabupaten Paser", country="ID")
res["rows_built"] = len(rows)
res["validation_errors"] = errors
res["gate_pass"] = (errors == [] and len(rows) > 0)
res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
(OUT / "gate_proof_tranche3.json").write_text(
    json.dumps(res, indent=1, ensure_ascii=False))
print(json.dumps(res, indent=1, ensure_ascii=False)[:1500], flush=True)
