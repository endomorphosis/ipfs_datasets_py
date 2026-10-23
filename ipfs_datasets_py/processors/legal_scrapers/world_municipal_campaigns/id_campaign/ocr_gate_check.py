"""OCR probe gate-sanity recheck (Paser 6401): re-derive the probe
sample, find the doc that measured 4,847,358 bytes in the probe run
(32 Pasal chunks over its first 15 pages), OCR its first 15 pages,
build world_municipal rows exactly as the harvester does, and run the
fail-closed validation gates on them."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

CAMP = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "id_campaign"
sys.path.insert(0, str(CAMP))
import harvest as H  # noqa: E402
import harvest2  # noqa: E402

BASE = "https://jdih.paserkab.go.id"
TARGET_BYTES = 4847358
OUT = CAMP / "ocr_probe"

sess = H.PoliteSession()


def download_bytes(url):
    buf = bytearray()
    expected = None
    for _ in range(8):
        headers = {"Accept-Encoding": "identity"}
        if buf:
            headers["Range"] = f"bytes={len(buf)}-"
        try:
            r = sess.get(url, timeout=180, stream=True, headers=headers)
            r.raise_for_status()
            if buf and r.status_code == 200:
                buf = bytearray()
            cr = r.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)\s*$", cr)
            if m:
                expected = int(m.group(1))
            elif r.headers.get("Content-Length"):
                cl = int(r.headers["Content-Length"])
                expected = cl if r.status_code == 200 else len(buf) + cl
            try:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        buf.extend(chunk)
                    if len(buf) > H.MAX_PDF_BYTES:
                        break
            except Exception:
                time.sleep(2)
                continue
        except Exception:
            time.sleep(2)
            continue
        if expected is None or len(buf) >= expected:
            break
    return bytes(buf)


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
print("sample size:", len(sample), flush=True)

target, raw = None, None
for i, doc in enumerate(sample):
    data = download_bytes(doc["pdf_url"])
    print(f"doc[{i}] bytes={len(data)}", flush=True)
    if len(data) == TARGET_BYTES:
        target, raw = doc, data
        break
    if i == 1 and target is None:
        target, raw = doc, data  # fallback: second doc
print("target:", target["pdf_url"] if target else None, flush=True)

import fitz  # noqa: E402
d = fitz.open(stream=raw, filetype="pdf")
texts, chars_page, secs = [], [], 0.0
for pno in range(min(d.page_count, 15)):
    page = d[pno]
    if len(page.get_text().strip()) >= 200:
        texts.append(page.get_text())
        chars_page.append(len(page.get_text().strip()))
        continue
    pix = page.get_pixmap(matrix=fitz.Matrix(250 / 72, 250 / 72))
    t0 = time.time()
    p = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "3"],
                       input=pix.tobytes("png"), capture_output=True, timeout=600)
    secs += time.time() - t0
    txt = p.stdout.decode("utf-8", "replace")
    chars_page.append(len(txt.strip()))
    texts.append(txt)
    print(f"  page {pno + 1}: {len(txt.strip())} chars (ocr {secs:.0f}s cum)", flush=True)
full = "\n".join(texts)
chunks = H.split_pasal(full)
title = ""
m = re.search(r"(?im)^\s*(PERATURAN DAERAH[^\n]{0,160})", full)
if m:
    title = H.clean_ws(m.group(1))
nomor, tahun = H.nomor_tahun(title)
base_id = f"id-6401-perda-{tahun or 'nd'}-{H.slug(str(nomor or 'x'))}"
regeling = f"jdih:jdih.paserkab.go.id:{target.get('key', '')}"
rows = []
for j, (suffix, label, bab, body) in enumerate(chunks):
    rows.append(H.make_row(
        jurisdiction_id="6401", jurisdiction_name="Kabupaten Paser", country="ID",
        doc_id=f"{base_id}-{suffix}", doc_order=j,
        regeling_id=regeling, regeling_work_id=regeling,
        title=title, structural_path=f"{title} > {bab}" if bab else title,
        node_label=label, body_html=H.text_to_html(body),
        source_url=target["pdf_url"], date_effective="", retrieved=H.RETRIEVED))
rows = H.finalize_rows(rows)
table = H.rows_to_table(rows)
errors = H.validate_table(table, jurisdiction_id="6401",
                          jurisdiction_name="Kabupaten Paser", country="ID")
res = {"target_pdf": target["pdf_url"], "bytes": len(raw), "pages_total": d.page_count,
       "pages_ocrd": len(chars_page), "chars_per_page": chars_page,
       "mean_chars_per_page": sum(chars_page) / len(chars_page) if chars_page else 0,
       "ocr_seconds_total": round(secs, 1), "pasal_chunks": len(chunks),
       "title_from_ocr": title, "rows_built": len(rows),
       "validation_errors": errors}
(OUT / "gate_check.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
print(json.dumps(res, indent=1, ensure_ascii=False)[:1200], flush=True)
