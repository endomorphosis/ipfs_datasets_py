#!/usr/bin/env python3
"""Italy pilot — publish validated seed to
endomorphosis/ipfs_italy_municipal_laws (Portugal layout).
Creates the repo if absent; additive if present (fail closed on any
name clash with different content). Auth: vault connector surrogate
via dynamic_credentials (never persisted). Remote verification:
re-download every parquet and re-run world_municipal validation.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path(__file__).resolve().parent.parent
OUT = PILOT / "out"
REPO = "endomorphosis/ipfs_italy_municipal_laws"
RETRIEVED = "2026-10-14"

summary = json.loads((OUT / "pilot_summary.json").read_text(encoding="utf-8"))
comuni = {s["code"]: s for s in summary if s.get("valid") and s.get("rows", 0) > 0}
assert comuni, "no valid comuni — refusing to publish"
total_rows = sum(v["rows"] for v in comuni.values())
total_docs = sum(v["extracted"] for v in comuni.values())
registry = [json.loads(ln) for ln in
            (OUT / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines()]
n_comuni = len(registry)
regions_covered = sorted({v["region"] for v in comuni.values()})
platforms = sorted({v["platform"] for v in comuni.values()})

entry = dynamic_credential_entry("custom.huggingface")
token = str(entry["surrogate"]).strip() if entry and entry.get("surrogate") else None
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

try:
    info = api.dataset_info(REPO, files_metadata=True)
    existing = {s.rfilename: s.size for s in info.siblings or []}
    print(f"dataset EXISTS: {len(existing)} files")
except Exception as e:  # noqa: BLE001
    print("dataset does not exist yet (creating):", type(e).__name__)
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = {}

rows_tbl = "\n".join(
    f"| {c} | {v['name']} | {v['region']} | {v['platform']} | "
    f"{v['extracted']} | {v['rows']} |"
    for c, v in sorted(comuni.items()))

coverage = f"""# Coverage report — Italy municipal laws (PILOT SEED)

Retrieved {RETRIEVED} from the comuni's own official websites.
**Pilot status: this is a seed, not full coverage.** Italy has
**{n_comuni} comuni** in ISTAT's official registry (Elenco comuni
italiani, istat.it). The full registry ships in `jurisdictions.jsonl`.

Jurisdiction IDs are the ISTAT *codice comune* (6 digits: provincia 3
+ comune 3 — e.g. `058091` Roma), registered in the program as
`IstatCodiceScheme`.

## Pilot seed — {len(comuni)} of {n_comuni} comuni, {total_docs} documents, {total_rows} rows

| Code | Comune | Region | Platform | Docs | Rows |
|---|---|---|---|---|---|
{rows_tbl}

Regions covered: {", ".join(regions_covered)}. Platform families:
{", ".join(platforms)}.

## Route

No national collection of Italian municipal regulations exists.
Comuni publish their *regolamenti comunali* and *statuto* as PDFs on
their own institutional sites (usually from a "Statuto e regolamenti"
page, an Amministrazione Trasparente section, or a documents area of
the comune CMS). This seed harvests those PDFs directly
(robots-checked per comune), extracts text (PyMuPDF → pdfplumber →
pdftotext → OCR with tesseract `ita` for scanned documents), splits
on `Art.`/`Articolo` headings, and normalizes to the program's
19-column schema (+ a `platform` provenance column).

## Survey caveats (honest limits)

- From the harvesting network used here, most comune hosts outside
  the Trentino-Alto Adige/Südtirol provincial networks answered only
  intermittently (frequent connect/read timeouts at survey time —
  an egress/origin latency wall, not robots refusals). 22 candidate
  comuni were surveyed; the seed covers the platform families that
  responded reliably enough to harvest with full validation.
- Documents whose digital text layer was empty were OCR'd; any that
  still failed extraction are counted as deferred in the pilot
  report, not silently dropped.

## Schema

19-column `world_municipal` schema (see the program's legal_scrapers
dataset): one row per article-level unit; `data/{{code}}_html.parquet`
per comune plus a `{{code}}_validation.json` gate report.
"""

readme = f"""---
license: other
language:
- it
tags:
- law
- legal
- italy
- municipal
- ipfs
---

# IPFS Italy Municipal Laws

Structured corpus of Italian *regolamenti comunali* and *statuti*,
normalized into the world municipal-law program's 19-column schema
(one row per article-level unit, one parquet per comune, jurisdiction
IDs = ISTAT codice comune).

**Pilot seed** — {len(comuni)} of {n_comuni} comuni, {total_docs} documents,
{total_rows} rows. See `coverage_report.md` for exactly what is and is
not covered, and why.

Primary legal texts are public legal information published by the
comuni. Dataset compilation is a research artifact; always verify
against the official source before relying on a text. Not legal advice.
"""

cov_path = PILOT / "coverage_report.md"
cov_path.write_text(coverage, encoding="utf-8")
readme_path = PILOT / "README.md"
readme_path.write_text(readme, encoding="utf-8")

uploads = [(cov_path, "coverage_report.md"), (readme_path, "README.md"),
           (OUT / "jurisdictions.jsonl", "jurisdictions.jsonl")]
for c in sorted(comuni):
    uploads.append((OUT / f"{c}_html.parquet", f"data/{c}_html.parquet"))
    uploads.append((OUT / f"{c}_validation.json", f"data/{c}_validation.json"))
for s in ("harvest_it.py", "net.py", "build_registry.py", "probe_sites.py"):
    uploads.append((PILOT / "scripts" / s, f"scrapers/{s}"))

REFRESHABLE = {"coverage_report.md", "README.md"}  # + scrapers/ (code)


def refreshable(remote):
    return remote in REFRESHABLE or remote.startswith("scrapers/")
todo = []
for local, remote in uploads:
    if remote in existing:
        if existing[remote] == local.stat().st_size:
            print(f"skip (present, same size): {remote}")
            continue
        if refreshable(remote):
            print(f"refresh (program artifact): {remote}")
            todo.append((local, remote))
            continue
        raise RuntimeError(
            f"remote {remote} exists with different size — refusing to "
            "overwrite DATA in pilot seed publish")
    todo.append((local, remote))

for local, remote in todo:
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"IT pilot seed: {remote}")
    print("uploaded", remote, local.stat().st_size, "B", flush=True)

# ---- remote verification ----
info = api.dataset_info(REPO, files_metadata=True)
remote_files = {s.rfilename: s.size for s in info.siblings or []}
print(f"remote files: {len(remote_files)}")
bad = []
for local, remote_path in uploads:
    if remote_path not in remote_files:
        bad.append((remote_path, "missing"))
    elif remote_files[remote_path] != local.stat().st_size:
        bad.append((remote_path, "size mismatch"))
print("upload mismatches:", bad)

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from huggingface_hub import hf_hub_download  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.world_municipal.parquet_io import (  # noqa: E402
    read_html_parquet,
)
from ipfs_datasets_py.processors.legal_scrapers.world_municipal.schema import (  # noqa: E402
    validate_table,
)

reg = {r["code"]: r["name"] for r in registry}
verify = {}
for c in sorted(comuni):
    p = hf_hub_download(REPO, f"data/{c}_html.parquet", repo_type="dataset",
                        token=token, force_download=True)
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=c, jurisdiction_name=reg[c],
                          country="IT")
    verify[c] = {"remote_rows": t.num_rows, "local_rows": comuni[c]["rows"],
                 "errors": errs}
    print("verify", c, verify[c], flush=True)
assert all(v["remote_rows"] == v["local_rows"] and not v["errors"]
           for v in verify.values())
assert not bad
print("PUBLISH + REMOTE VERIFY OK:", json.dumps(verify))
