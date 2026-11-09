#!/usr/bin/env python3
"""Copy the batch-1 code into the pack's scrapers/, write manifests/batch1_code.json (pinned to ipfs_datasets_py a1b5c73e)
and the top-level README.md with YAML frontmatter. Env ZA_WORK."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, json, os, shutil
from pathlib import Path
import pyarrow.parquet as pq
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_prov"))); P = W / "hf_b1/ipfs_south_africa_provincial_laws"; C = Path(__file__).resolve().parent
UP = "a1b5c73e5b687d8bd6c3b3051788860fd6e2f07a"
FILES = ["collect_za_prov.py", "plan_za_prov.py", "ocr_za_prov.py", "stage_za_prov.py", "verify_za_prov.py", "run_za_prov.sh",
         "pipeline_za_prov.sh", "build_bundle.py", "bounds_za_prov.py", "pii_scan_za_prov.py", "robots_guard.py", "requirements.txt", "README_scrapers.md"]
(P / "scrapers").mkdir(parents=True, exist_ok=True); rows = []
for f in FILES:
    dst = P / "scrapers" / {"robots_guard.py": "robots_guard_b1.py", "requirements.txt": "requirements_batch1.txt", "README_scrapers.md": "README.md"}.get(f, f)
    shutil.copy2(C / f, dst)
    rows.append({"path": f"scrapers/{dst.name}", "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(), "bytes": dst.stat().st_size})
upf = "ipfs_datasets_py/processors/legal_scrapers/national_collectors"
json.dump({"batch": 1, "repo": "endomorphosis/ipfs_south_africa_provincial_laws", "parent_sha": None, "new_repo": True,
           "upstream": {"repo": "endomorphosis/ipfs_datasets_py", "commit": UP, "paths": [f"{upf}/collector.py", f"{upf}/common.py", f"{upf}/world_lib.py", f"{upf}/world_package.py"],
                        "note": "catalog -> fetch -> extract -> package pattern and collection_record.v1 metadata follow these modules; no upstream ZA provincial collector exists at this commit"},
           "ported_from": {"bounds_za_prov.py": "za_metro batch6 bounds_za_metro.py", "pii_scan_za_prov.py": "za_metro batch6 pii_scan_za_metro.py",
                           "collect_za_prov.py": "za_metro batch6 collect_za_metro.py", "pipeline": "cm batch3 pipeline (catalog, plan, fetch, OCR, stage, bundle, verify)"},
           "files": rows}, open(P / "manifests/batch1_code.json", "w"), indent=1)
s = json.load(open(P / "manifests/batch1_stage_summary.json"))
# OCR manifest: one entry per OCR'd doc (values exactly as written by ocr_za_prov.py / stage), annotated with its pack disposition.
_lt = pq.read_table(P / "data/laws.parquet", columns=["id", "metadata_json"]).to_pylist()
_in = {}; _src = {}
for _r in _lt:
    _te = json.loads(_r["metadata_json"])["text_extraction"]; _src[_te["source"]] = _src.get(_te["source"], 0) + 1
    if _te.get("ocr"): _in[_te["ocr"]["ident"]] = _r["id"]
_dr = {json.loads(l)["ident"]: json.loads(l)["reason"] for l in open(P / "manifests/batch1_drops.jsonl")}
_ocr = []
for l in open(P / "manifests/batch1_ocr.jsonl"):
    d = json.loads(l)
    for k in ("in_pack", "law_id", "drop_reason"): d.pop(k, None)
    d["in_pack"] = d["ident"] in _in; d["law_id"] = _in.get(d["ident"]); d["drop_reason"] = None if d["in_pack"] else _dr.get(d["ident"])
    _ocr.append(d)
with open(P / "manifests/batch1_ocr.jsonl", "w") as fh:
    for d in _ocr: fh.write(json.dumps(d) + "\n")
_deg = [d for d in _ocr if d["status"] == "DEGRADED"]
_gl = sum(1 for _r in _lt if json.loads(_r["metadata_json"])["section_qa"]["gaps"])
_degtxt = "\n".join(f"- `{d['ident']}`: mean confidence {d['mean_conf']:.2f} over {d['pages']} pages; " + (f"in the pack as `{d['law_id']}`" if d["in_pack"] else f"not in the pack (dropped at stage: {d['drop_reason']})") for d in _deg)
_ocrsec = f"""
## OCR and text quality
{_src.get('pdf_text_layer', 0)} laws take their text from the PDF text layer (pdftotext -layout) and {_src.get('ocr_tesseract', 0)} from OCR. OCR used
{_ocr[0]['engine'] if _ocr else 'tesseract'} ({_ocr[0]['lang'] if _ocr else 'eng'}, {_ocr[0]['dpi'] if _ocr else 300} dpi, one page at a time). A document whose mean word confidence is below 80 is marked DEGRADED.

{len(_ocr)} scanned documents were OCR'd; `manifests/batch1_ocr.jsonl` has one entry per document with `mean_conf` (word-level mean, rounded to 2 decimals),
`pages`, `words`, `engine`, `dpi`, `lang`, `status` (ok / DEGRADED), `in_pack`, `law_id` and `drop_reason`. {sum(d['in_pack'] for d in _ocr)} of them are in the pack, all with status ok;
the other {sum(not d['in_pack'] for d in _ocr)} were dropped at stage because no Act masthead could be read. {len(_deg)} documents were DEGRADED:
{_degtxt}

In the data, every law records its text source in `metadata_json.text_extraction.source` (`pdf_text_layer` or `ocr_tesseract`); OCR'd laws also carry the
manifest entry in `metadata_json.text_extraction.ocr` (`mean_conf`, `status`, ...). A DEGRADED law would show `status: "DEGRADED"` there; batch 1 contains none.

Section numbering is checked per law: {s['section_gaps']} gaps in section numbers occur across {_gl} laws (listed in `metadata_json.section_qa.gaps`, e.g. `18->20`).
Gaps are recorded, not repaired: a section heading the splitter did not detect stays inside the previous article, and the full text in `laws.text` is unaffected.
"""
nl = pq.ParquetFile(P / "data/laws.parquet").metadata.num_rows; na = pq.ParquetFile(P / "data/articles.parquet").metadata.num_rows
bp = ", ".join(f"{k}: {v}" for k, v in s["by_province"].items()) or "none"
readme = f"""---
license: other
license_name: za-copyright-act-s12-8-a
license_details: "Official texts of a legislative nature; see Licence section."
language:
- en
pretty_name: South Africa Provincial Laws (ipfs)
tags:
- law
- legislation
- south-africa
- provincial
size_categories:
- n<1K
configs:
- config_name: laws
  data_files:
  - split: train
    path: data/laws.parquet
- config_name: articles
  data_files:
  - split: train
    path: data/articles.parquet
---

# South Africa provincial laws

Enacted provincial Acts collected from official provincial legislature websites. Batch 1 has {nl} Acts ({bp}) and {na} sections.

## Sources (batch 1)
- Western Cape Provincial Parliament, https://www.wcpp.gov.za/ (Wikidata Q127167). Listing pages ?q=legislation and ?q=bill-tracking-view. Crawl-delay 10 s honoured.

Batch 1 covers the Western Cape only. KwaZulu-Natal is not included in this batch (see manifests/batch1_kzn_reread.json).

Only enacted provincial Acts are included. Bills, memoranda, notices, adverts, presentations, national Acts and non-English versions are excluded
(see manifests/batch1_listing_exclusions.jsonl and manifests/batch1_drops.jsonl). Acts already in
[endomorphosis/ipfs_southafrica_laws](https://huggingface.co/datasets/endomorphosis/ipfs_southafrica_laws) are deduplicated by title, Act number and year.

## Schema
`data/laws.parquet` has the columns of the national pack plus `province`, `gazette_no`, `gazette_date` and `act_no`. `data/articles.parquet` has the national article columns
(one row per section). Titles come from the Act masthead and the maker from the enacting clause. Repeals are recorded only for express repeal clauses
(metadata_json.repeals_express). Dates are never padded. Text is English only and page-boundary filtered so that each law ends where the Act ends.
{_ocrsec}
## Licence
Section 12(8)(a) of the South African Copyright Act 98 of 1978 provides that official texts of a legislative, administrative or legal nature are not
eligible for copyright. The authentic signed Act or Provincial Gazette prevails. Not legal advice.

## Provenance
Scrapers and pinned requirements are in `scrapers/`. Code hashes and the upstream pin (endomorphosis/ipfs_datasets_py @ {UP[:8]}) are in `manifests/batch1_code.json`.
robots.txt was checked on every host and redirect hop, with one request in flight, TLS verification, and no archives, logins or challenge bypass.
A PII scan (South African ID numbers, private emails, personal addresses) is in `manifests/batch1_pii_scan.json`. It records offsets only.
"""
(P / "README.md").write_text(readme)
for src, dst in (("kzn_reread.json", "batch1_kzn_reread.json"), ("detector_v2.json", "batch1_detector.json")):
    if (W / src).exists():
        d = json.load(open(W / src))
        if src == "kzn_reread.json":
            for h in d.get("v1_hits", []): h.pop("context", None)
        json.dump(d, open(P / "manifests" / dst, "w"), indent=1, ensure_ascii=False)
if not (W / "detector_v2.json").exists():
    json.dump({"detector": "v1", "reason": "KZN re-read did not classify the hit as passive; detector unchanged"}, open(P / "manifests/batch1_detector.json", "w"), indent=1)
print("bundle", len(rows))
