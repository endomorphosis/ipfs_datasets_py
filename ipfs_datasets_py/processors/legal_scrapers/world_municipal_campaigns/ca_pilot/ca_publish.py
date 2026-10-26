"""Canada pilot — publish validated seed to
endomorphosis/ipfs_canada_municipal_laws (Portugal layout).
Runs only after all world_municipal gates pass; dedupes against the
live repo before uploading. The repo does not exist yet (checked
2026-10-12: RepositoryNotFoundError); it is created here."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/ca_pilot"
REPO = "endomorphosis/ipfs_canada_municipal_laws"
RETRIEVED = "2026-10-12"

manifest = json.load(open(PILOT / "run_manifest.json"))
regstats = json.load(open(PILOT / "registry_stats.json"))
muns = manifest["municipalities"]
assert all(v["valid"] for v in muns.values()), "gate failure in manifest — refusing to publish"
total_rows = sum(v["rows"] for v in muns.values())
total_docs = sum(len(v["docs"]) for v in muns.values())
DENOM = regstats["municipal_government_csds"]
TOTAL_CSD = regstats["total_csds"]

entry = dynamic_credential_entry("custom.huggingface")
token = entry.get("surrogate") if isinstance(entry, dict) else None
if not token:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

try:
    info = api.dataset_info(REPO)
    existing = {s.rfilename for s in info.siblings or []}
    print(f"dataset exists: {len(existing)} files: {sorted(existing)}")
except Exception as e:  # noqa: BLE001
    print("dataset_info failed (creating):", type(e).__name__, str(e)[:100])
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = set()

# ---------- coverage report ----------
lines = [
    "# Coverage report — Canada municipal laws (pilot seed)",
    "",
    f"Retrieved {RETRIEVED}. This is a **pilot seed**, not a Canada harvest: "
    f"**{len(muns)} municipalities, {total_docs} bylaw documents, {total_rows} "
    "article-level rows**, sampled to prove the routes, the Statistics "
    "Canada SGC jurisdiction scheme, and the shared `world_municipal` "
    "19-column normalization pipeline end to end.",
    "",
    "## Denominator",
    "",
    f"Statistics Canada's SGC 2021 counts **{TOTAL_CSD} census "
    "subdivisions (CSDs)** in total (table 17-10-0155, 2021 boundaries, "
    "retrieved 2026-10-13). Classifying every CSD type by whether it is "
    "an incorporated municipal government — reserves/settlements, "
    "unorganized territories, BC regional-district electoral areas, NS "
    "county subdivisions, PEI fire districts, NB parishes and similar "
    "non-municipal geographies excluded — gives **"
    f"{DENOM} municipal-government CSDs** (per-province counts cross-check "
    "within 1–2 of official provincial municipal counts: BC 161, SK 776, "
    "MB 138, PEI 59, NB 104). The full registry is published at "
    "`registry/sgc_registry_2021.jsonl` and is the completion checklist "
    f"for this dataset. This seed covers **{len(muns)} of {DENOM}**. "
    "`jurisdictions.jsonl` lists the sampled municipalities with their "
    "SGC codes, CSD types and document languages (en/fr).",
    "",
    "## Sampled municipalities (all gates pass)",
    "",
    "| SGC code | Municipality | Province | Route | Documents | Rows |",
    "|---|---|---|---|---|---|",
]
prov = {"3520005": "Ontario", "5915004": "British Columbia",
        "1209034": "Nova Scotia", "2481017": "Quebec"}
for jid, v in sorted(muns.items()):
    lines.append(f"| {jid} | {v['name']} | {prov[jid]} | {v['route']} | {len(v['docs'])} | {v['rows']} |")
lines += [
    "",
    "## Routes surveyed — excluded or blocked (with evidence, 2026-10-12)",
    "",
    "- **CivicWeb (*.civicweb.net, iCompass)** — the dominant small-town "
    "vendor platform. Its robots.txt wildcard group is `User-agent: * / "
    "Disallow: /` (486 user-agent groups; only individually named bots "
    "receive partial allowances). EXCLUDED on robots grounds, untouched "
    "(same posture class as the Netherlands CVDR and Denpasar JDIH "
    "exclusions in this program). A full-Canada harvest needs this route "
    "resolved (vendor permission or a robots change) — it is the single "
    "biggest blocker for Canada.",
    "- **eScribe (pub-*.escribemeetings.com)** — robots.txt blocks only "
    "PetalBot and the portals load, but the document endpoint "
    "(filestream.ashx) sits behind a Cloudflare bot check: direct fetch "
    "returns a 403 'Verifying your browser' challenge page, a "
    "portal-session fetch hangs past 60 s, and no Wayback snapshots exist "
    "for sampled documents. The City of Kawartha Lakes (SGC 3516010) "
    "sample was therefore NOT harvested. Document download from this "
    "egress is blocked; revisit from an unchallenged network.",
    "- **City of Winnipeg (winnipeg.ca)** — HTTP 403 F5 rejection for "
    "every path including robots.txt from this egress. Blocked.",
    "- **Ville de Québec (reglements.ville.quebec.qc.ca, Cyberlex)** — "
    "robots disallows the PDF endpoints (/fr/showPdf, /en/showPdf) and "
    "search paths. EXCLUDED on robots grounds.",
    "- **ottawa.ca** — Incapsula bot wall (robots.txt itself returns a "
    "challenge page). Blocked from this egress.",
    "- **City of Calgary / City of Edmonton** — bylaw libraries are "
    "JavaScript applications (AEM / Drupal front-ends) whose document "
    "links are not present in server-rendered HTML; enumerable via "
    "their search services, deferred to the template census. Calgary "
    "council documents are reachable via its eScribe portal (subject "
    "to the eScribe block above).",
    "- **City of Vancouver** — legacy bylaws.vancouver.ca PDF library "
    "is retired (root redirects to an ASP.NET search application, "
    "app.vancouver.ca/bylaw_net; sampled legacy PDF URLs return 404). "
    "The search application is the future route; not harvested here.",
    "- **City of Montréal** — the open-data portal (donnees.montreal.ca, "
    "CC-BY) exposes a règlements index via the CKAN datastore, but "
    "carries no document URLs, and the datastore export was not "
    "retrievable from this egress (access denied); documents sit behind "
    "the montreal.ca search service (whose search paths are robots-"
    "disallowed for the règlements section). Metadata route documented; "
    "not harvested here.",
    "",
    "## Method",
    "",
    "Consolidated bylaw PDFs from official municipal sites, text "
    "extracted with PyMuPDF, split at section/article headings, "
    "normalized with the shared `world_municipal` library (19-column "
    "schema, fail-closed gates: exact schema, no NULLs, zero empty "
    "docs, sequential doc_order, unique doc_id/cid, constant "
    "attribution). Every document passed a client-side attribution "
    "check (municipality marker in the document text) before emission. "
    "Gatineau documents are administrative compilations in French; "
    "their `date_modified` is the compilation date stated in the "
    "document. Gatineau's host declares Crawl-delay 10; harvesting "
    "paced at 11 s. All other hosts paced at 2 s.",
    "",
    "Attribution: City of Toronto; City of Surrey; Halifax Regional "
    "Municipality; Ville de Gatineau. Bylaw texts are public legal "
    "documents published by those municipalities; consolidated versions "
    "are unofficial compilations provided for convenience by the "
    "municipalities themselves.",
]
(PILOT / "coverage_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---------- README ----------
readme = f"""---
license: other
language:
- en
- fr
task_categories:
- text-retrieval
tags:
- law
- municipal
- canada
- bylaws
- legal
---

# Canada Municipal Laws — pilot seed

Municipal by-laws of Canada, normalized to the shared 19-column
`world_municipal` schema used by the world municipal-law program
(one row per section/article; one parquet per municipality under
`data/<SGC code>_html.parquet`).

**Status: pilot seed ({RETRIEVED}).** {len(muns)} municipalities,
{total_docs} consolidated bylaw documents, {total_rows} rows:

| SGC | Municipality | Province | Documents | Rows |
|---|---|---|---|---|
"""
for jid, v in sorted(muns.items()):
    readme += f"| {jid} | {v['name']} | {prov[jid]} | {len(v['docs'])} | {v['rows']} |\n"
readme += f"""
Jurisdiction IDs are Statistics Canada **SGC census subdivision
codes** (7 digits: province + census division + census subdivision).
The denominator is {DENOM} municipal-government CSDs of {TOTAL_CSD}
total CSDs (SGC 2021, Statistics Canada table 17-10-0155); the full
registry is at `registry/sgc_registry_2021.jsonl`.
See `coverage_report.md` for the route survey — including why the
dominant CivicWeb platform is excluded (robots `Disallow: /` for the
wildcard agent) and why eScribe document downloads are blocked from
the harvesting network (Cloudflare bot check) — and `jurisdictions.jsonl`
for the sampled registry entries.

Part of the world municipal-law program built on
`Endomorphosis/ipfs_datasets_py` (shared `world_municipal`
normalization library). Sibling datasets: `ipfs_portugal_municipal_laws`,
`ipfs_spain_municipal_laws`, `ipfs_belgium_municipal_laws`,
`ipfs_indonesia_municipal_laws`, `ipfs_brazil_municipal_laws`,
`ipfs_south_africa_municipal_laws`, `american_municipal_law`.
"""
(PILOT / "README.md").write_text(readme, encoding="utf-8")

# ---------- upload (dedupe-first) ----------
uploads = []
for jid, v in sorted(muns.items()):
    uploads.append((PILOT / "data" / f"{jid}_html.parquet", v["file"]))
uploads += [
    (PILOT / "jurisdictions.jsonl", "jurisdictions.jsonl"),
    (PILOT / "sgc_registry_2021.jsonl", "registry/sgc_registry_2021.jsonl"),
    (PILOT / "coverage_report.md", "coverage_report.md"),
    (PILOT / "README.md", "README.md"),
    (PILOT / "scripts" / "ca_pilot_build.py", "scrapers/ca_pilot_build.py"),
    (PILOT / "scripts" / "build_registry.py", "scrapers/build_registry.py"),
]
for local, remote in uploads:
    if remote in existing:
        print(f"SKIP (already on HF): {remote}")
        continue
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"Canada pilot seed: {remote}")
    print(f"UPLOADED {remote} ({local.stat().st_size} bytes)")

info = api.dataset_info(REPO)
final = sorted(s.rfilename for s in info.siblings or [])
print(f"FINAL: {len(final)} files")
for f in final:
    print(" ", f)
expected = {r for _, r in uploads}
missing = expected - set(final)
assert not missing, f"missing after upload: {missing}"

# ---------- round-trip: download one parquet back and re-validate ----------
from huggingface_hub import hf_hub_download  # noqa: E402
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validation_report  # noqa: E402

dl = hf_hub_download(REPO, "data/2481017_html.parquet", repo_type="dataset", token=token)
back = read_html_parquet(dl)
rep = validation_report(back, jurisdiction_id="2481017",
                        jurisdiction_name="Gatineau", country="Canada")
print("ROUND-TRIP 2481017:", rep["rows"], "rows, valid =", rep["valid"], rep["errors"])
assert rep["valid"] and rep["rows"] == muns["2481017"]["rows"]
json.dump({"repo": REPO, "files": final, "rows": total_rows, "docs": total_docs,
           "roundtrip": {"file": "data/2481017_html.parquet", "rows": rep["rows"],
                         "valid": rep["valid"]}},
          open(PILOT / "publish_result.json", "w"), indent=1)
print(f"PUBLISH VERIFIED: {REPO} — {len(muns)} municipalities, {total_rows} rows")
