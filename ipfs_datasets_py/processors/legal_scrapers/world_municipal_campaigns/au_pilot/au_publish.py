"""Australia pilot — publish validated seed to
endomorphosis/ipfs_australia_municipal_laws (NZ/Portugal layout).
Additive: if the dataset already exists, upload only pilot files whose
jurisdiction names are disjoint from what's there; never delete.
Auth: vault connector surrogate via dynamic_credentials (never persisted).
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path(__file__).resolve().parent.parent
REPO = "endomorphosis/ipfs_australia_municipal_laws"
RETRIEVED = "2026-10-13"

manifest = json.loads((PILOT / "run_manifest.json").read_text())
councils = {k: v for k, v in manifest["councils"].items() if v.get("valid")}
assert councils, "no valid councils — refusing to publish"
total_rows = sum(v["rows"] for v in councils.values())
total_docs = sum(len([d for d in v["docs"] if d.get("units")]) for v in councils.values())

entry = dynamic_credential_entry("custom.huggingface")
token = str(entry["surrogate"]).strip() if entry and entry.get("surrogate") else None
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

try:
    info = api.dataset_info(REPO, files_metadata=True)
    existing = {s.rfilename for s in info.siblings or []}
    print(f"dataset EXISTS: {len(existing)} files: {sorted(existing)[:20]}")
    clash = {f"data/{c}_html.parquet" for c in councils} & existing
    if clash:
        raise SystemExit(f"ABORT: name clash with existing files {clash} — additive-only pilot")
except SystemExit:
    raise
except Exception as e:  # noqa: BLE001
    print("dataset does not exist yet (creating):", type(e).__name__)
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = set()

rows_tbl = "\n".join(
    f"| {c} | {v['name']} | {v['state']} | {v['platform']} | "
    f"{len([d for d in v['docs'] if d.get('units')])} | {v['rows']} |"
    for c, v in sorted(councils.items()))

coverage = f"""# Coverage report — Australia municipal laws (PILOT SEED)

Retrieved {RETRIEVED} from the councils' own websites. **Pilot status:
this is a seed, not full coverage.** Australia has **542 local government
areas** in the ABS ASGS Edition 3 LGA 2025 registry (567 ABS records
minus 19 non-geographic pseudo codes and 6 unincorporated-area records;
ALGA counts 537 incorporated councils — the ABS structure additionally
carries a few special-purpose areas). The full registry ships in
`jurisdictions.jsonl` (all 567 records, flagged by kind).

Jurisdiction IDs are the ABS LGA 2025 codes (5 digits; first digit =
state: 1 NSW, 2 Vic, 3 Qld, 4 SA, 5 WA, 6 Tas, 7 NT, 8 ACT, 9 OT),
registered in the program as `AbsLgaScheme`.

## Pilot seed — 4 of 542 councils, {total_docs} documents, {total_rows} rows

| Code | Council | State | Platform | Docs | Rows |
|---|---|---|---|---|---|
{rows_tbl}

## Route

No national collection of AU council local laws exists. Councils
self-host "Local Laws / By-laws" as PDFs on their own sites; this seed
harvests those PDFs directly (robots-checked per council, no
crawl-delay declared by any harvested site), extracts text
(pdfplumber → PyMuPDF → pdftotext → OCR), and normalizes to the
program's 19-column schema, one row per clause-level unit.

Platform notes from the pilot survey (7+6 councils probed):
- **Granicus OpenCities** (Merri-bek, Vic) is reachable and harvests
  cleanly.
- The **Queensland LGAQ/OpenCities family is uniformly HTTP 403 from
  the harvesting network used here** (Logan, Moreton Bay, Redland,
  Ipswich, Townsville, Cairns) — an egress wall, documented per
  council; Brisbane (Qld) is covered via its Adobe AEM site instead.
- Melbourne (Vic) serves a 202 WAF interstitial from this network;
  Banyule (Vic, OpenCities) is likewise 403.
- Adelaide (SA) publishes its 9 numbered by-laws as PDFs; By-law No. 1
  is digital text and included. By-laws 2, 4 and 7 are scanned images
  and are **OCR-deferred** (listed in the pilot report), not yet rows.

## Schema

19-column `world_municipal` schema (see the program's legal_scrapers
dataset): one row per clause-level unit; `data/{{code}}_html.parquet`
per council plus a `{{code}}_validation.json` gate report.
"""

readme = f"""---
license: other
language:
- en
tags:
- law
- legal
- australia
- municipal
- ipfs
---

# IPFS Australia Municipal Laws

Structured corpus of Australian council local laws and by-laws,
normalized into the world municipal-law program's 19-column schema
(one row per clause-level unit, one parquet per council, jurisdiction
IDs = ABS LGA 2025 codes).

**Pilot seed** — {len(councils)} of 542 councils, {total_docs} documents,
{total_rows} rows. See `coverage_report.md` for exactly what is and is
not covered, and why.

Primary legal texts are public legal information published by the
councils. Dataset compilation is a research artifact; always verify
against the official source before relying on a text. Not legal advice.
"""

cov_path = PILOT / "coverage_report.md"
cov_path.write_text(coverage)
(PILOT / "README.md").write_text(readme)

uploads = [(cov_path, "coverage_report.md"), (PILOT / "README.md", "README.md"),
           (PILOT / "data" / "jurisdictions.jsonl", "jurisdictions.jsonl")]
for c in sorted(councils):
    uploads.append((PILOT / "data" / f"{c}_html.parquet", f"data/{c}_html.parquet"))
    uploads.append((PILOT / "data" / f"{c}_validation.json", f"data/{c}_validation.json"))
for s in ("au_build.py", "probe.py", "parse_abs_dbf.py"):
    uploads.append((PILOT / "scripts" / s, f"scrapers/{s}"))

for local, remote in uploads:
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"AU pilot seed: {remote}")
    print("uploaded", remote, flush=True)

# ---- remote verification ----
info = api.dataset_info(REPO, files_metadata=True)
remote = {s.rfilename: s.size for s in info.siblings or []}
print(f"remote files: {len(remote)}")
bad = []
for local, remote_path in uploads:
    if remote_path not in remote:
        bad.append((remote_path, "missing"))
    elif remote[remote_path] != local.stat().st_size:
        bad.append((remote_path, f"size {remote[remote_path]} != {local.stat().st_size}"))
print("upload mismatches:", bad)

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from huggingface_hub import hf_hub_download  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402

reg = {}
for ln in (PILOT / "data" / "jurisdictions.jsonl").read_text().splitlines():
    r = json.loads(ln)
    if r["kind"] == "lga":
        reg[r["code"]] = r["name"]
verify = {}
for c in sorted(councils):
    p = hf_hub_download(REPO, f"data/{c}_html.parquet", repo_type="dataset", token=token)
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=c, jurisdiction_name=reg[c], country="AU")
    verify[c] = {"remote_rows": t.num_rows, "local_rows": councils[c]["rows"], "errors": errs}
    print("verify", c, verify[c], flush=True)
assert all(v["remote_rows"] == v["local_rows"] and not v["errors"] for v in verify.values())
assert not bad
print("PUBLISH + REMOTE VERIFY OK:", json.dumps(verify))
