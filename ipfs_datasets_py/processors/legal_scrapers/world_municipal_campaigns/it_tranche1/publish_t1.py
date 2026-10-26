#!/usr/bin/env python3
"""Italy TRANCHE 1 — publish validated comuni to
endomorphosis/ipfs_italy_municipal_laws (Portugal layout).

Additive for comuni not yet on the dataset. For comuni already
published by the pilot (the OpenPA deepening targets), the parquet is
superseded in place ONLY when the tranche harvest extracted strictly
more documents AND more rows than the pilot's published version —
otherwise fail closed. coverage_report.md / README.md are refreshed
from the merged pilot+tranche state. Auth: vault connector surrogate
via dynamic_credentials (never persisted). Remote verification:
re-download every parquet this run ships and re-run world_municipal
validation; also re-verify the untouched pilot comuni still match.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"  # xet transfers stall via this proxy
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HERE = Path(__file__).resolve().parent
T1 = HERE.parent
PILOT = T1.parent / "it_pilot"
OUT = T1 / "out"
REPO = "endomorphosis/ipfs_italy_municipal_laws"
RETRIEVED = date.today().isoformat()


def load_summary(path):
    if not path.exists():
        return {}
    return {s["code"]: s for s in json.loads(path.read_text(encoding="utf-8"))}


pilot = load_summary(PILOT / "out" / "pilot_summary.json")
tranche = {}
for p in sorted(OUT.glob("tranche1_summary*.json")):
    tranche.update(load_summary(p))

# Prior published state = pilot valids, overridden by this script's
# own state file (written after every verified publish — it records
# what is actually on the dataset, including tranche comuni that an
# earlier tranche publish shipped and later deepened further).
STATE_PATH = OUT / "published_state.json"
prior = {c: s for c, s in pilot.items()
         if s.get("valid") and s.get("rows", 0) > 0}
if STATE_PATH.exists():
    for c, s in json.loads(STATE_PATH.read_text(encoding="utf-8")).items():
        prior[c] = s

# published state after this run = prior, overridden by any valid
# tranche result that STRICTLY grows docs and rows (deepening), plus
# new tranche valids.
published = dict(prior)
to_ship = {}   # code -> stats
for c, s in tranche.items():
    if not (s.get("valid") and s.get("rows", 0) > 0):
        continue
    if c in published:
        old = published[c]
        if not (s["extracted"] > old["extracted"] and s["rows"] > old["rows"]):
            print(f"SKIP {c}: deepening did not strictly grow "
                  f"({old['extracted']}->{s['extracted']} docs, "
                  f"{old['rows']}->{s['rows']} rows); published version stays")
            continue
        print(f"SUPERSEDE {c}: {old['extracted']}->{s['extracted']} docs, "
              f"{old['rows']}->{s['rows']} rows")
    published[c] = s
    to_ship[c] = s

assert to_ship, "no new/deepened comuni to ship — refusing to publish"
registry = [json.loads(ln) for ln in
            (OUT / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines()]
n_comuni = len(registry)
total_rows = sum(v["rows"] for v in published.values())
total_docs = sum(v["extracted"] for v in published.values())
regions_covered = sorted({v["region"] for v in published.values()})
platforms = sorted({v["platform"] for v in published.values()})

entry = dynamic_credential_entry("custom.huggingface")
token = str(entry["surrogate"]).strip() if entry and entry.get("surrogate") else None
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

info = api.dataset_info(REPO, files_metadata=True)
existing = {s.rfilename: s.size for s in info.siblings or []}
print(f"dataset EXISTS: {len(existing)} files")

rows_tbl = "\n".join(
    f"| {c} | {v['name']} | {v['region']} | {v['platform']} | "
    f"{v['extracted']} | {v['rows']} |"
    for c, v in sorted(published.items()))

coverage = f"""# Coverage report — Italy municipal laws

Retrieved {RETRIEVED} from the comuni's own official websites.
**Status: partial corpus (pilot seed + tranche 1), not full coverage.**
Italy has **{n_comuni} comuni** in ISTAT's official registry (Elenco
comuni italiani, istat.it). The full registry ships in
`jurisdictions.jsonl`.

Jurisdiction IDs are the ISTAT *codice comune* (6 digits: provincia 3
+ comune 3 — e.g. `058091` Roma), registered in the program as
`IstatCodiceScheme`.

## Coverage — {len(published)} of {n_comuni} comuni, {total_docs} documents, {total_rows} rows

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
the comune CMS). This corpus harvests those PDFs directly
(robots-checked per comune), extracts text (PyMuPDF → pdfplumber →
pdftotext → OCR with tesseract `ita` for scanned documents; every
digital extraction must pass an extraction-usability gate), splits
on `Art.`/`Articolo` headings, and normalizes to the program's
19-column schema (+ a `platform` provenance column).

## Survey caveats (honest limits)

- From the harvesting network used here, most comune hosts outside
  the Trentino-Alto Adige/Südtirol provincial networks answered only
  intermittently (frequent connect/read timeouts — an egress/origin
  latency wall, not robots refusals). Comuni that stay unreachable
  across retry cycles remain queued in the campaign reports; they
  are not dead ends.
- Documents whose text layer was empty or unusable were OCR'd; any
  that still failed extraction are counted as deferred in the
  campaign reports, not silently dropped.

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

**Partial corpus (pilot seed + tranche 1)** — {len(published)} of
{n_comuni} comuni, {total_docs} documents, {total_rows} rows. See
`coverage_report.md` for exactly what is and is not covered, and why.

Primary legal texts are public legal information published by the
comuni. Dataset compilation is a research artifact; always verify
against the official source before relying on a text. Not legal advice.
"""

cov_path = T1 / "coverage_report.md"
cov_path.write_text(coverage, encoding="utf-8")
readme_path = T1 / "README.md"
readme_path.write_text(readme, encoding="utf-8")

uploads = [(cov_path, "coverage_report.md"), (readme_path, "README.md")]
for c in sorted(to_ship):
    uploads.append((OUT / f"{c}_html.parquet", f"data/{c}_html.parquet"))
    uploads.append((OUT / f"{c}_validation.json", f"data/{c}_validation.json"))
for s in ("harvest_it.py", "net.py", "build_registry.py", "probe_sites.py"):
    uploads.append((PILOT / "scripts" / s, f"scrapers/{s}"))
uploads.append((HERE / "harvest_t1.py", "scrapers/harvest_t1.py"))
uploads.append((HERE / "publish_t1.py", "scrapers/publish_t1.py"))

REFRESHABLE = {"coverage_report.md", "README.md"}
SUPERSEDE_OK = {f"data/{c}_html.parquet" for c in to_ship if c in prior}
SUPERSEDE_OK |= {f"data/{c}_validation.json" for c in to_ship if c in prior}

todo = []
for local, remote in uploads:
    if remote in existing:
        if existing[remote] == local.stat().st_size:
            print(f"skip (present, same size): {remote}")
            continue
        if remote in REFRESHABLE or remote.startswith("scrapers/") \
                or remote in SUPERSEDE_OK:
            print(f"refresh/supersede: {remote}")
            todo.append((local, remote))
            continue
        raise RuntimeError(
            f"remote {remote} exists with different size — refusing to "
            "overwrite DATA outside the deepening supersede set")
    todo.append((local, remote))

for local, remote in todo:
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"IT tranche 1: {remote}")
    print("uploaded", remote, local.stat().st_size, "B", flush=True)

# ---- remote verification: every comune in the published set ----
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
import requests  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.world_municipal.parquet_io import (  # noqa: E402
    read_html_parquet,
)
from ipfs_datasets_py.processors.legal_scrapers.world_municipal.schema import (  # noqa: E402
    validate_table,
)


def download_remote(code, dest):
    """Plain-requests download of a dataset file with hard timeouts
    and retries (hf_hub_download/xet transfers stall on this proxy)."""
    url = (f"https://huggingface.co/datasets/{REPO}/resolve/main/"
           f"data/{code}_html.parquet")
    last = None
    for attempt in range(5):
        try:
            with requests.get(url, headers={"Authorization": f"Bearer {token}"},
                              timeout=(20, 120), stream=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(262144):
                        fh.write(chunk)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  verify-download {code} try {attempt + 1}: "
                  f"{type(e).__name__}", flush=True)
            import time as _t
            _t.sleep(10 * (attempt + 1))
    raise RuntimeError(f"verify download failed for {code}: {last}")


reg = {r["code"]: r["name"] for r in registry}
verify = {}
import tempfile  # noqa: E402
for c in sorted(published):
    local_rows = published[c]["rows"]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tf:
        tmp = tf.name
    download_remote(c, tmp)
    t = read_html_parquet(tmp)
    errs = validate_table(t, jurisdiction_id=c, jurisdiction_name=reg[c],
                          country="IT")
    verify[c] = {"remote_rows": t.num_rows, "expected_rows": local_rows,
                 "errors": errs}
    print("verify", c, verify[c], flush=True)
assert all(v["remote_rows"] == v["expected_rows"] and not v["errors"]
           for v in verify.values())
assert not bad
print("PUBLISH + REMOTE VERIFY OK:", json.dumps(verify))
print(f"DATASET NOW: {len(published)} comuni, {total_docs} docs, "
      f"{total_rows} rows")
STATE_PATH.write_text(json.dumps(
    {c: {"name": s["name"], "region": s["region"], "platform": s["platform"],
         "extracted": s["extracted"], "rows": s["rows"]}
     for c, s in published.items()}, indent=1, ensure_ascii=False),
    encoding="utf-8")
print("published_state.json written")
