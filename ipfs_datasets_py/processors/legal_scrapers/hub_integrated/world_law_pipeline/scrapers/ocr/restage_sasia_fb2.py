#!/usr/bin/env python3
"""Normalizer feedback #2: restage (a) Tatarstan 1640926 (district issuer, text from quarantined batch-1 file),
(b) IN/iso_IN egazette with header-built title/number (cached OCR text), (c) Kerala lsgkerala:Tharoor_GP re-OCR'd with
tessdata_best mal+eng, staged only if mean conf >= 0.6. New timestamps; tmp -> validate -> rename."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import hashlib, json, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import ocr_afme as A, ocr_sasia as S
from schema import place_key, validate_file, validate_record
q = {}
for f in ("ocr_queue.jsonl", "ru_gosweb_notext.jsonl"):
    for l in open(S.Q / f, encoding="utf-8"):
        if l.strip(): e = json.loads(l); e.setdefault("country", e.get("country_code")); q.setdefault(e["doc_id"], e)
ver = A.tess_version(); rows = []; report = {}
# (a)
for l in open(A.OUT / "RU" / "iso_RU-TA.ocr20261014T130955Zp0001.jsonl", encoding="utf-8"):
    old = json.loads(l)
    if old["doc_id"] != "pravo_tatarstan:npa_file:1640926": continue
    meta = {k: v for k, v in old["extra_metadata"].items() if k not in ("archive", "issuer_match")}
    rows.append(S.row_for(q[old["doc_id"]], old["text"], meta, {"via": "commoncrawl", "url": old["archive_url"]}))
# (b)
for l in open(A.OUT / "IN" / "iso_IN.ocr20261014T133114Zp0001.jsonl", encoding="utf-8"):
    old = json.loads(l); e = q[old["doc_id"]]
    rows.append(S.row_for(e, old["text"], old["extra_metadata"], {"via": old["extra_metadata"].get("ocr_fetch_via"), "url": e["source_url"]}))
# (c)
e = q["lsgkerala:Tharoor_GP"]; b, info = S.fetch(e)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(td) / "x.pdf"; pdf.write_bytes(b); t = time.time()
    texts, pc = S.ocr_pdf(pdf, 60, "mal+eng", best=True); secs = round(time.time() - t, 1)
mean = round(sum(pc) / len(pc), 4) if pc else 0.0
report["kerala_conf_best"] = mean; report["kerala_page_conf"] = [round(c, 3) for c in pc]
(S.CACHE / f"{hashlib.sha1(e['doc_id'].encode()).hexdigest()[:20]}.ocr.json").write_text(json.dumps(
    {"doc_id": e["doc_id"], "texts": texts, "page_conf": pc, "secs": secs, "fetch": info, "sha256": hashlib.sha256(b).hexdigest(), "lang": "mal+eng", "model": "tessdata_best"}, ensure_ascii=False))
if mean >= 0.6:
    text = "\n\f\n".join(texts).strip()
    meta = {"text_source": "ocr", "ocr_engine": "tesseract", "ocr_engine_version": ver, "ocr_lang": "mal+eng", "ocr_model": "tessdata_best",
            "ocr_confidence_mean": mean, "ocr_pages": len(pc), "ocr_low_conf_pages": sum(1 for c in pc if c < 0.5),
            "ocr_low_conf_page_list": [i + 1 for i, c in enumerate(pc) if c < 0.5], "ocr_dpi": 300,
            "source_pdf_sha256": hashlib.sha256(b).hexdigest(), "source_pdf_url": e["source_url"], "ocr_fetch_via": info["via"], "ocr_seconds": secs}
    rows.append(S.row_for(e, text, meta, info))
else:
    with open(A.LOGS / "sasia_skipped.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": A.utcnow(), "doc_id": e["doc_id"], "source": e["source"], "source_url": e["source_url"], "reason": "low_conf_indic", "conf": mean, "model": "tessdata_best"}) + "\n")
ts = A.utctag(); files = []
for i, r in enumerate(rows, 1):
    assert not validate_record(r), validate_record(r)
    pk = place_key(r["place_id"]); fn = A.OUT / r["country_code"] / f"{pk}.ocr{ts}p{i:04d}.jsonl"; assert not fn.exists()
    tmp = fn.with_name("." + fn.name[:-6] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    v = validate_file(tmp, expect_place_key=pk); assert v["ok"], v
    os.rename(tmp, fn); files.append({"file": str(fn), "doc_id": r["doc_id"], "title": r.get("title_native"), "number": r.get("number"),
                                      "issuer": r["extra_metadata"].get("issuer_match")})
report["files"] = files; print(json.dumps(report, ensure_ascii=False, indent=1))
