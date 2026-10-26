#!/usr/bin/env python3
"""Stage-1 publish: the municipalities whose PDF-tranche builds are
complete and gated (digital extraction), while CPT/WC023/ETH await
OCR completion on a CPU-contended box. Interim coverage_report.md is
truthful about the pending three; stage 2 supersedes it."""
import os, sys, json
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dynamic_credentials import dynamic_credential_entry
import za_pdf_tranche_build as B

DONE8 = ["JHB", "EC443", "WC011", "WC012", "WC013", "WC015", "WC033",
         "WC041"]
PENDING = ["CPT", "WC023", "ETH"]

WORK = B.OUT
OUTD = B.OUTD
REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
BASELINE = {"CPT": 1795, "ETH": 1761, "JHB": 1910, "EC443": 1308, "WC011": 488, "WC012": 1476, "WC013": 1688, "WC015": 1926, "WC023": 1516, "WC033": 879, "WC041": 692}
man = json.load(open(WORK / "run_manifest.json"))["municipalities"]
for c in DONE8:
    assert man[c]["valid"], c
entry = dynamic_credential_entry("custom.huggingface")
from huggingface_hub import HfApi
repo = HfApi(token=entry["surrogate"])
files = sorted(r.rfilename for r in
               repo.list_repo_tree(REPO_ID, repo_type="dataset", recursive=True)
               if hasattr(r, "rfilename"))
assert len(files) >= 98 and "README.md" in files and "scrapers/za_pdf_tranche_build.py" not in files, len(files)

lines = []
tot_b = tot_a = 0
for c in B.MDB_ORDER:
    if c in DONE8:
        m = man[c]
        tot_b += m["rows_before"]; tot_a += m["rows_after"]
        lines.append((c, m))
    else:
        tot_b += BASELINE[c]; tot_a += BASELINE[c]

txt = []
txt.append("# South Africa municipal laws — coverage report")
txt.append("")
txt.append("World Municipal Laws dataset — South Africa (MDB-coded municipalities, "
           "source: Open By-laws / Akoma Ntoso).")
txt.append("")
txt.append("## PDF-only tranche (interim, stage 1)")
txt.append("")
txt.append("Tranche 1 (AKN HTML) excluded 105 works whose public pages are PDF "
           "viewer stubs with no AKN markup (`pdf_only_no_akn_html`). This tranche "
           "recovers them from the source PDF linked from each work's own page on "
           "openbylaws.org.za (route verified against robots.txt; >=6 s pacing). "
           "PDFs are usually whole Provincial Gazette issues; the instrument for "
           "each work is segmented out of the gazette before normalization. Text "
           "extraction: PyMuPDF -> pdfplumber -> pdftotext -> OCR (tesseract, "
           "eng/afr, 300 dpi) when digital extraction is insufficient. Rows from "
           "this tranche carry the source-PDF URL in `xml_url` (AKN rows carry "
           "the AKN work URL), so provenance is explicit in the data.")
txt.append("")
txt.append("Stage 1 (this update) publishes the municipalities whose builds are "
           "complete. CPT, WC023 and ETH are still being processed — several of "
           "their source PDFs are scanned-only and are OCRing with per-page "
           "checkpoints; their parquets are unchanged in this update and will be "
           "superseded when processing completes.")
txt.append("")
txt.append("| Municipality | Rows before | Rows after | Works recovered | Works still excluded |")
txt.append("|---|---|---|---|---|")
gain = 0
for c in B.MDB_ORDER:
    if c in DONE8:
        m = man[c]
        gain += m["rows_after"] - m["rows_before"]
        txt.append(f"| {c} | {m['rows_before']} | {m['rows_after']} | "
                   f"{len(m['recovered'])}/{len(m['recovered']) + len(m['excluded'])} | "
                   f"{len(m['excluded'])} |")
    else:
        txt.append(f"| {c} | {BASELINE[c]} | {BASELINE[c]} "
                   f"| pending | pending |")
txt.append(f"| **Total** | **{tot_b}** | **{tot_a}** | | |")
txt.append("")
txt.append(f"Stage-1 gain: +{gain} rows.")
txt.append("")
txt.append("## Remaining exclusions (stage-1 municipalities)")
txt.append("")
any_ex = False
for c in DONE8:
    for e in man[c]["excluded"]:
        any_ex = True
        txt.append(f"- {c} `{e['work']}` — {e.get('reason') or e.get('status')}")
if not any_ex:
    txt.append("- none")
txt.append("")
txt.append("## Licensing / use signals")
txt.append("")
txt.append("Source content: CC-BY-NC-SA via Laws.Africa / Open By-laws terms. "
           "The source site's robots.txt carries a Content-Signal of "
           "ai-train=no, search=yes, ai-input=no; this dataset is published for "
           "search, research and archival purposes consistent with those signals.")
txt.append("")
(WORK / "coverage_report_stage1.md").write_text("\n".join(txt) + "\n")

import time as _time
def upload_retry(local, remote, tries=6):
    for i in range(tries):
        try:
            repo.upload_file(path_or_fileobj=str(local),
                             path_in_repo=remote,
                             repo_id=REPO_ID, repo_type="dataset")
            print("uploaded", remote, flush=True)
            return
        except Exception as exc:
            print(f"upload {remote} attempt {i+1} failed: {type(exc).__name__}",
                  flush=True)
            _time.sleep(20 * (i + 1))
    raise RuntimeError(f"upload failed after {tries} tries: {remote}")

up = []
for c in DONE8:
    m = man[c]
    if m["rows_after"] > m["rows_before"]:
        upload_retry(OUTD / f"{c}_html.parquet", f"data/{c}_html.parquet")
        up.append(c)
upload_retry(WORK / "coverage_report_stage1.md", "coverage_report.md")
upload_retry(WORK / "za_pdf_tranche_build.py", "scrapers/za_pdf_tranche_build.py")
print("STAGE1 PUBLISHED:", up, "+ coverage_report.md + scrapers/za_pdf_tranche_build.py", flush=True)
