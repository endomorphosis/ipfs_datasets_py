"""Canada tranche 1, Wave A — finalize: append the Wave A appendix to
the dataset's coverage_report.md (append-only; README and both
registry JSONLs untouched), publish the Wave A builder under
scrapers/, and run the full remote verification (fresh listing,
per-town remote row counts vs the local checkpoint state, one French
town parquet fully re-validated from its remote copy, pilot parquets
re-counted to prove the 1,210-row baseline is untouched)."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

GOAL = Path.home() / "workspace/goals/world-municipal-law-coverage"
WAVEA = GOAL / "hidden_files/ca_wavea"
REPO_ID = "endomorphosis/ipfs_canada_municipal_laws"
PILOT_BASELINE = {"3520005": 417, "5915004": 608, "1209034": 64, "2481017": 121}

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validation_report  # noqa: E402

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

entry = dynamic_credential_entry("custom.huggingface")
token = entry.get("surrogate") if isinstance(entry, dict) else None
if not token:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402
api = HfApi(token=token)

state = json.loads((WAVEA / "state" / "state.json").read_text(encoding="utf-8"))
towns = state["towns"]
done = {sgc: t for sgc, t in sorted(towns.items()) if t.get("status") == "done"}
not_done = {sgc: t for sgc, t in towns.items() if t.get("status") != "done"}
total_rows = sum(t["rows"] for t in done.values())
total_docs = sum(len(t["docs"]) for t in done.values())
prov_docs = sum(t.get("provenance_docs", 0) for t in done.values())
print(f"done towns: {len(done)}  rows: {total_rows}  docs: {total_docs}  provenance-attributed docs: {prov_docs}")
for sgc, t in not_done.items():
    print(f"  NOT DONE: {sgc} {t['name']} status={t['status']} notes={t.get('notes')}")

# ---------- coverage appendix (append-only) ----------
lines = [
    "",
    "## APPENDIX — Tranche 1, Wave A: Québec WordPress towns (added 2026-10-13)",
    "",
    f"Scope: the {len(done) + len(not_done)} Québec towns the platform census classified as "
    "WordPress with robots-allowed by-law routes and direct PDF evidence "
    "(`index_with_pdfs` / `direct_pdf_links_on_homepage`). One WordPress template "
    "adapter harvested each town's by-law index (WordPress pagination followed), "
    "re-checking robots.txt per town before fetching. Documents went through the "
    "pilot's fail-closed gates: attribution (municipality named in the text, or — "
    "recorded per document — own-host provenance for small-town template règlements "
    "that never name their town), ≥ 2 split sections per document, exact 19-column "
    "schema validation on write and on independent re-read. Scanned documents were "
    "OCR'd (tesseract, French) only when the full document finished inside a "
    "bounded budget — partially-OCR'd documents were dropped, never published.",
    "",
    f"**Wave A published: {len(done)} municipalities, {total_docs} documents, "
    f"{total_rows} rows** (dataset total now {1210 + total_rows} rows across "
    f"{4 + len(done)} municipalities; the 4 pilot parquets are untouched).",
    "",
    "| SGC code | Municipality | Documents | Rows |",
    "|---|---|---|---|",
]
for sgc, t in sorted(done.items()):
    lines.append(f"| {sgc} | {t['name']} | {len(t['docs'])} | {t['rows']} |")
if not_done:
    lines += ["", "### Attempted but not published (with reasons)", ""]
    for sgc, t in sorted(not_done.items()):
        reason = "; ".join(t.get("notes", []) or [t["status"]])
        nd = len(t.get("dropped_docs", []))
        lines.append(f"- **{t['name']} ({sgc})** — status `{t['status']}`: {reason}"
                     + (f" ({nd} documents dropped at gates)" if nd else ""))
dropped_total = sum(len(t.get("dropped_docs", [])) for t in done.values())
lines += [
    "",
    f"Across the published towns, {dropped_total} candidate documents were dropped "
    "at the gates (zoning-plan maps and annexes with no municipal attribution, "
    "documents with no extractable text inside the OCR budget, documents that do "
    "not split into ≥ 2 sections, duplicates), each recorded with its reason in "
    "the wave manifest. Per-document detail: `scrapers/ca_wavea_build.py` is the "
    "adapter; the run state (per-town, per-document, with drop reasons) is kept "
    "in the program workspace.",
    "",
]

# upload appendix only if not already appended
current = hf_hub_download(REPO_ID, "coverage_report.md", repo_type="dataset",
                          token=token, local_dir=str(WAVEA / "remote_final"))
text = Path(current).read_text(encoding="utf-8")
if "Tranche 1, Wave A" not in text:
    out = WAVEA / "coverage_report_wavea.md"
    out.write_text(text.rstrip("\n") + "\n" + "\n".join(lines), encoding="utf-8")
    api.upload_file(path_or_fileobj=str(out), path_in_repo="coverage_report.md",
                    repo_id=REPO_ID, repo_type="dataset",
                    commit_message="Canada tranche 1 wave A: coverage appendix")
    print("coverage_report.md appendix uploaded")
else:
    print("coverage appendix already present — skipping")

builder = WAVEA / "scripts" / "ca_wavea_build.py"
api.upload_file(path_or_fileobj=str(builder), path_in_repo="scrapers/ca_wavea_build.py",
                repo_id=REPO_ID, repo_type="dataset",
                commit_message="Canada tranche 1 wave A: WordPress adapter")
print("builder uploaded")

# ---------- remote verification ----------
info = api.dataset_info(REPO_ID)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"REMOTE: {len(files)} files")
verify = {"files": len(files), "towns": {}, "pilot": {}, "valid_sample": None}
for sgc, t in sorted(done.items()):
    p = hf_hub_download(REPO_ID, f"data/{sgc}_html.parquet", repo_type="dataset",
                        token=token, local_dir=str(WAVEA / "remote_final"))
    back = read_html_parquet(p)
    ok = back.num_rows == t["rows"]
    verify["towns"][sgc] = {"remote_rows": back.num_rows, "expected": t["rows"], "match": ok}
    print(f"  {sgc} {t['name']}: remote {back.num_rows} vs local {t['rows']} -> {'OK' if ok else 'MISMATCH'}")
    assert ok, f"row mismatch for {sgc}"
for sgc, expect in PILOT_BASELINE.items():
    p = hf_hub_download(REPO_ID, f"data/{sgc}_html.parquet", repo_type="dataset",
                        token=token, local_dir=str(WAVEA / "remote_final"))
    back = read_html_parquet(p)
    verify["pilot"][sgc] = back.num_rows
    print(f"  pilot {sgc}: remote {back.num_rows} vs baseline {expect} -> {'OK' if back.num_rows == expect else 'CHANGED'}")
    assert back.num_rows == expect, f"pilot parquet {sgc} changed!"

# full gate re-validation of one French town from its remote copy
sample_sgc = "2403025" if "2403025" in done else next(iter(done))
p = hf_hub_download(REPO_ID, f"data/{sample_sgc}_html.parquet", repo_type="dataset",
                    token=token, local_dir=str(WAVEA / "remote_final"))
back = read_html_parquet(p)
rep = validation_report(back, jurisdiction_id=sample_sgc,
                        jurisdiction_name=done[sample_sgc]["name"], country="Canada")
print(f"REMOTE VALIDATION {sample_sgc}: {rep['rows']} rows, valid = {rep['valid']}, errors = {rep['errors']}")
assert rep["valid"]
verify["valid_sample"] = {"sgc": sample_sgc, "rows": rep["rows"], "valid": rep["valid"]}
(WAVEA / "remote_verify_result.json").write_text(json.dumps(verify, indent=1), encoding="utf-8")
print(f"REMOTE VERIFY OK: {len(files)} files, {len(done)} wave-A towns match, pilot baseline intact")
