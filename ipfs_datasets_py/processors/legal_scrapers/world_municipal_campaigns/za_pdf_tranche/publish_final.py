"""ZA PDF tranche: coverage report generation + publish + remote verify.

Uploads ONLY: the updated data/<MDB>_html.parquet for municipalities
that gained rows (superseded in place, same paths), an updated
coverage_report.md, and the tranche builder as
scrapers/za_pdf_tranche_build.py. README.md is NOT touched. No Layer 1
file and not manifests/za_overlap_crosswalk.jsonl is touched.
HF auth via the vault connector surrogate (dynamic_credentials);
no token is persisted.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

Z = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/za_pdf_tranche"
V2 = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/za_tranche1_v2"
REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
RETRIEVED = "2026-10-12"
MDB_ORDER = ["CPT", "ETH", "JHB", "EC443", "WC011", "WC012", "WC013",
             "WC015", "WC023", "WC033", "WC041"]

manifest = json.load(open(Z / "run_manifest.json"))
muns = manifest["municipalities"]
assert set(muns) == set(MDB_ORDER)
for code, v in muns.items():
    assert v.get("valid"), f"{code} not valid"

v2m = json.load(open(V2 / "run_manifest.json"))["municipalities"]
tot_before = sum(v["rows_before"] for v in muns.values())
tot_after = sum(v["rows_after"] for v in muns.values())
tot_rec = sum(v["works_recovered"] for v in muns.values())
tot_ex = sum(v["works_excluded"] for v in muns.values())
OCR_PENDING_8 = {
    "/akn/za-cpt/act/by-law/2011/sub-council-further-amendment",
    "/akn/za-eth/act/by-law/1996/water-supply",
    "/akn/za-eth/act/mn/1998/50",
    "/akn/za-eth/act/mn/1998/51",
    "/akn/za-eth/act/mn/1998/52",
    "/akn/za-eth/act/mn/1999/7",
    "/akn/za-eth/act/mn/2012/20",
    "/akn/za-wc023/act/by-law/2007/rules-of-order-regulating-the-conduct-of-meetings",
}
ocr_rec = sum(1 for v in muns.values() for e in v.get("recovered", [])
              if e.get("method") == "ocr_tesseract300"
              and e.get("work") in OCR_PENDING_8)
ocr_total = sum(1 for v in muns.values() for e in v.get("recovered", [])
                if e.get("method") == "ocr_tesseract300")
assert tot_before == 15439, tot_before
assert tot_rec + tot_ex == 105, (tot_rec, tot_ex)
gained = [c for c in MDB_ORDER if muns[c]["rows_after"] > muns[c]["rows_before"]]
print(f"totals: rows {tot_before} -> {tot_after}; PDF works recovered "
      f"{tot_rec}, still excluded {tot_ex}; municipalities gaining rows: {gained}")

# ---------------- coverage report ----------------
lines = [
    "# Coverage report — South Africa municipal laws (AKN layer + PDF tranche)",
    "",
    f"Retrieved {RETRIEVED} from Open By-laws (https://openbylaws.org.za), a project of "
    "Laws.Africa and AfricanLII (part of LawLibrary.org.za), which publishes South African "
    "municipal by-laws as Akoma Ntoso (AKN). The AKN tranche ingested the site's public AKN "
    "HTML expressions via robots-permitted routes only (sitemap, /legislation/<place>/ "
    "listings, /akn/ document pages; Crawl-delay 5 respected with 6 s pacing; /api/, /search/ "
    "and /akn/*/provision/ are robots-disallowed and were not used). The PDF tranche (below) "
    "additionally fetched the source PDFs linked from each work's own public page "
    "(/akn/.../<expression>/source.pdf — a robots-allowed route, verified against the live "
    "robots.txt before fetching, 6 s pacing). The Laws.Africa Content API is token-gated/"
    "paid and was not used.",
    "",
    "## Denominator",
    "",
    "South Africa has **257 municipalities** since the 2016 demarcation: 8 metropolitan "
    "(Category A), 44 district (Category C) and 205 local (Category B). The full registry — "
    "Municipal Demarcation Board (MDB) code, name, province, category — is in "
    "`jurisdictions.jsonl` (MDB-verified 257/257 on codes/category/province against the MDB's "
    "own ArcGIS layers; see the reconciliation audit).",
    "",
    "## Coverage — 11 AKN municipalities, AKN + source-PDF layers combined",
    "",
    "Open By-laws carries by-laws for **11 of 257 municipalities**. Its robots-referenced "
    f"sitemap listed **576 works** on {RETRIEVED}. The AKN tranche ingested the 471 works "
    "that carry AKN HTML (15,439 section-level rows). The PDF tranche then recovered "
    f"**{tot_rec} of the 105 PDF-only works** from their source PDFs "
    f"(+{tot_after - tot_before} rows), bringing the layer to **{tot_after} rows**; "
    f"**{tot_ex} works remain excluded** (reasons per work in the tranche report / builder "
    "run manifest — e.g. instrument not locatable in the source gazette, or no usable "
    "text). Excluded works were not forced past the content gates.",
    "",
    "| MDB code | Municipality | Sitemap works | AKN-ingested | PDF-recovered | Still excluded | Rows |",
    "|---|---|---|---|---|---|---|",
]
for code in MDB_ORDER:
    v = muns[code]
    v2 = v2m[code]
    lines.append(f"| {code} | {v['name']} | {v2['works']} | {v2['docs_ingested']} | "
                 f"{v['works_recovered']} | {v['works_excluded']} | {v['rows_after']} |")
lines += [
    f"| **Total** | **11 municipalities** | **576** | **471** | **{tot_rec}** | "
    f"**{tot_ex}** | **{tot_after}** |",
    "",
    "## PDF tranche method and provenance",
    "",
    "Source PDFs are usually Provincial Gazette issues (some scanned). For each PDF-only "
    "work, the instrument was segmented out of its gazette before normalization: segment "
    "boundaries are municipality/by-law heading events, so no other municipality's text "
    "is attributed to a work. Extraction chain: PyMuPDF -> pdfplumber -> pdftotext. "
    "Scanned-image PDFs with no digital text layer require tesseract OCR (300 dpi, eng); "
    f"of the 8 works that were OCR-pending at the end of the PDF tranche, {ocr_rec} were "
    "recovered by a follow-up OCR pass (2026-10-13); OCR-derived rows are the runs whose "
    f"builder-manifest method is `ocr_tesseract300` ({ocr_total} works in total, "
    "including any recovered during the PDF tranche itself); any still excluded "
    "carry per-work reasons in the run manifest. Rows are section-level where the "
    "PDF's numbered section structure is cleanly detectable, otherwise a single "
    "document-level row per work — section splits are never fabricated. Two-column "
    "gazettes print parallel language versions of the same promulgation; segments are "
    "taken from the language stream matching the work's expression where separable. "
    "PDF-derived rows are distinguishable in the data: their `xml_url` is the source PDF "
    "URL itself (AKN-derived rows carry the AKN work URL), and their `source_url` is the "
    "work's public expression page. The builder is published as "
    "`scrapers/za_pdf_tranche_build.py`; per-work outcomes are in its run manifest.",
    "",
    "All 15,439 AKN-derived rows are preserved exactly in the updated files (verified "
    "row-for-row during the merge); PDF-derived rows are appended after them. Every "
    "updated file passed the fail-closed world_municipal gates on an independent "
    "re-read: exact 19-column schema, sequential doc_order, unique doc_id/cid, zero "
    "empty docs, constant MDB attribution.",
    "",
    "## The other layer in this repo, and the eThekwini crosswalk",
    "",
    "This repo also holds a pre-existing corpus (Layer 1: `data/laws-*.parquet` + "
    "`data/articles-*.parquet`, from metro websites and Provincial Gazettes), which is "
    "untouched by both tranches. The AKN / world_municipal layer "
    "(`data/<MDB>_html.parquet`) is canonical for the 11 AKN municipalities; Layer 1 is "
    "canonical where it is the only layer. The layers overlap only in eThekwini (ETH): "
    "of ETH's 58 AKN works, 33 match Layer 1 documents, 25 are AKN-only, and 12 of "
    "Layer 1's 45 ETH documents have no AKN counterpart. All of these pairs are "
    "published as `manifests/za_overlap_crosswalk.jsonl` (unchanged by this tranche). "
    "Together the two layers cover 26 of 257 municipalities; the remaining 246 have no "
    "AKN coverage and are a Provincial Gazette / municipal-site PDF long-tail.",
    "",
    "## Licence and attribution",
    "",
    "Legislation provided by Laws.Africa and their contributors under a CC-BY-NC-SA "
    "license (as stated at laws.africa/api). There is no copyright in the original "
    "by-law texts themselves (per the SAFLII / Open By-laws mirror note; the HTML form "
    "was historically offered under CC BY 2.5 ZA). This dataset is a non-commercial "
    "republication with attribution and share-alike terms. Note: openbylaws.org.za's "
    "robots.txt carries Content-Signals ai-train=no / ai-input=no — downstream users "
    "should respect the source terms.",
    "",
]
(Z / "out" / "coverage_report.md").write_text("\n".join(lines))
print("coverage_report.md written")

# ---------------- publish ----------------
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

entry = dynamic_credential_entry("custom.huggingface")
token = None
if isinstance(entry, dict):
    token = entry.get("surrogate")
if not token:
    try:
        token = entry[1]["credential"]["surrogate"]
    except Exception:
        token = None
if not token:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")

from huggingface_hub import HfApi  # noqa: E402
try:
    _surr = entry.get("surrogate") if isinstance(entry, dict) else None
except Exception:
    _surr = None
if _surr:
    token = _surr
api = HfApi(token=token)
info = api.dataset_info(REPO_ID)
existing = {s.rfilename for s in info.siblings or []}
print(f"BEFORE: {len(existing)} files")
print(f'BEFORE listing (dataset_info siblings): {len(existing)} files')

uploads = []
for code in gained:
    uploads.append((Z / "out" / f"{code}_html.parquet", f"data/{code}_html.parquet"))
uploads += [
    (Z / "out" / "coverage_report.md", "coverage_report.md"),
    (Z / "za_pdf_tranche_build.py", "scrapers/za_pdf_tranche_build.py"),
]
import time as _t
for local, remote in uploads:
    assert local.exists(), local
    for _try in range(6):
        try:
            api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                            repo_id=REPO_ID, repo_type="dataset",
                            commit_message=f"ZA PDF tranche + OCR recovery: {remote}")
            break
        except Exception as _exc:
            print(f"upload {remote} try {_try+1} failed: {type(_exc).__name__}", flush=True)
            if _try == 5:
                raise
            _t.sleep(20 * (_try + 1))
    print(f"uploaded: {remote}", flush=True)

info = api.dataset_info(REPO_ID)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"AFTER: {len(files)} files")
expected = {r for _, r in uploads}
missing = expected - set(files)
print("MISSING:", missing if missing else "none")
assert not missing
assert "README.md" in files
# Layer 1 + crosswalk untouched check: they must still be present
assert "manifests/za_overlap_crosswalk.jsonl" in files
assert any(f.startswith("data/laws-") for f in files)
json.dump({"before_count": len(existing), "after_count": len(files),
           "after_files": files, "uploaded": sorted(expected)},
          open(Z / "publish_result.json", "w"), indent=2)
print("PUBLISH DONE")
