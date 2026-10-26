#!/usr/bin/env python3
"""Re-extract Stadt Zürich AS texts with the column-aware extractor (pdf_columns.layout_text) from the PDF cache filled by
fetch_zh_pdfs.py. Writes RAWDIR/raw/docs_zh_layout.jsonl (same records as docs_zh.jsonl, text replaced, extras.extraction set).
Docs whose PDF is missing from the cache keep the original text (extras.extraction = 'pdftotext-raw').
Usage: python reextract_zh.py RAWDIR PDF_CACHE"""
import json, os, sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_columns import layout_text
raw, cache = sys.argv[1], sys.argv[2]
n = miss = 0
with open(f"{raw}/raw/docs_zh_layout.jsonl", "w") as out:
    for l in open(f"{raw}/raw/docs_zh.jsonl"):
        d = json.loads(l); fn = os.path.join(cache, hashlib.sha1(d["source_url"].encode()).hexdigest() + ".pdf")
        if os.path.exists(fn):
            d["text"] = layout_text(fn); d["extras"]["extraction"] = "pdftotext-layout+margin-notes"; n += 1
        else:
            d["extras"]["extraction"] = "pdftotext-raw"; miss += 1
        out.write(json.dumps(d, ensure_ascii=False) + "\n")
print(json.dumps({"layout": n, "missing_pdf": miss}))
