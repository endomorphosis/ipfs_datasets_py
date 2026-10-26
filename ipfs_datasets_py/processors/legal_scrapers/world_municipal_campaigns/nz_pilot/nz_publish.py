"""New Zealand pilot — publish validated seed to
endomorphosis/ipfs_new_zealand_municipal_laws (Portugal layout).
Runs only after all world_municipal gates pass; dedupes against the
live repo before uploading (additive; only this layer's own seed files
at the same path may be superseded)."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/nz_pilot"
REPO = "endomorphosis/ipfs_new_zealand_municipal_laws"
RETRIEVED = "2026-10-13"

manifest = json.loads((PILOT / "run_manifest.json").read_text())
councils = {k: v for k, v in manifest["councils"].items() if v.get("valid")}
failed = {k: v for k, v in manifest["councils"].items() if not v.get("valid")}
assert councils, "no valid councils in manifest — refusing to publish"
total_rows = sum(v["rows"] for v in councils.values())
total_docs = sum(len(v["docs"]) for v in councils.values())

entry = dynamic_credential_entry("custom.huggingface")
token = entry["surrogate"]
if not token:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

try:
    info = api.dataset_info(REPO)
    existing = {s.rfilename for s in info.siblings or []}
    print(f"dataset exists: {len(existing)} files")
except Exception as e:  # noqa: BLE001
    print("dataset_info failed (creating):", type(e).__name__, str(e)[:100])
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = set()

names = {r["jurisdiction_id"]: r["jurisdiction_name"] for r in
         (json.loads(ln) for ln in (PILOT / "jurisdictions.jsonl").read_text().splitlines())}

# ---------- coverage report ----------
lines = [
    "# Coverage report — New Zealand municipal laws (seed)",
    "",
    f"Retrieved {RETRIEVED} from the councils' own websites. New Zealand has "
    "**78 local authorities**: 67 territorial authorities (Stats NZ TA2023 "
    "codes) and 11 regional councils (registered here as \"R\" + ISO "
    "3166-2:NZ region code). The full registry is in `jurisdictions.jsonl`. "
    "Unitary authorities (Auckland, Gisborne, Nelson, Tasman, Marlborough, "
    "Chatham Islands) are counted once, as territorial authorities.",
    "",
    "## Route",
    "",
    "No aggregator carries NZ council bylaws (NZLII coverage is minimal and "
    "the site is bot-walled from many networks; legislation.govt.nz does "
    "not cover council bylaws). The route is per-council harvest of the "
    "bylaw PDFs councils publish on their own sites, respecting each "
    "site's robots.txt; pacing 6.5 s between requests (the strictest "
    "observed Crawl-delay was 5 s, Hastings). PDF text is extracted with "
    "PyMuPDF -> pdfplumber -> pdftotext -> tesseract OCR and split into "
    "clause-level rows in the world_municipal 19-column schema.",
    "",
    "## Seed status",
    "",
    f"**{len(councils)} of 78 councils** seeded by this pilot "
    f"({total_docs} bylaws, {total_rows} section rows):",
    "",
    "| Code | Council | Bylaws | Rows |",
    "|---|---|---|---|",
]
for code, v in sorted(councils.items()):
    lines.append(f"| {code} | {names.get(code, v['name'])} | {len(v['docs'])} | {v['rows']} |")

# fetch-reality section from the recovery fetch manifest, when present
fetch_path = PILOT / "fetch_manifest.json"
if fetch_path.exists():
    fetch = json.loads(fetch_path.read_text())
    lines += [
        "",
        "## Fetch reality (measured, recovery run 2026-10-13)",
        "",
        "The route to NZ council sites from the pilot network is extremely "
        "slow and stall-prone (a 53 KB index page took ~81 s; multi-MB PDFs "
        "routinely timed out at 120-180 s read timeouts on the first attempt "
        "at this pilot). The seed was therefore fetched with a checkpointed "
        "disk-first downloader (300 s timeouts, Range-resume, Wayback "
        "Machine fallback per PDF). Per-council fetch outcomes:",
        "",
        "| Code | Council | PDFs OK | Fetch wall (s) | Source |",
        "|---|---|---|---|---|",
    ]
    for code, e in sorted(fetch.get("councils", {}).items()):
        okf = [f for f in e.get("files", []) if f.get("status") == "ok"]
        srcs = sorted({f.get("source") or "?" for f in okf})
        lines.append(f"| {code} | {e.get('name', '')} | {len(okf)}/{len(e.get('files', []))} "
                     f"| {e.get('wall_seconds', '')} | {', '.join(srcs) or '—'} |")
    for code, v in sorted(failed.items()):
        lines.append(f"| {code} | {names.get(code, '')} | 0 | — | failed: "
                     f"{str(v.get('error', ''))[:80]} |")
lines += [
    "",
    "## Dead ends observed from the pilot network",
    "",
    "- Auckland Council (076): HTTP 406 on every request from this egress.",
    "- Christchurch City (060): Incapsula challenge stub on robots.txt and "
    "bylaw pages.",
    "- Palmerston North City (040) and Whangarei District (002): HTTP 403.",
    "- Invercargill City (075), Nelson City (052), Rotorua District (024): "
    "HTTP 202 WAF interstitial pages.",
    "- Dunedin City (071) and Lower Hutt City (046): HTTP 403 (WAF block "
    "page) on robots.txt and homepage (finish-run probe, 2026-10-13).",
    "- New Plymouth District (033): robots.txt loads only after ~200 s of "
    "retries and the site (npdc.govt.nz) then read-times-out at 180 s — "
    "delivers too slowly from this egress for the pilot window.",
    "- Hastings District (030): index loads fast (~35 s) but every bylaw "
    "PDF transfer stalls at 0 bytes from this egress (the Consolidated "
    "Bylaw 2021 link also 404s when the host responds).",
    "- Wellington City (047) and Selwyn District (062): live hosts "
    "read-time-out (Selwyn's robots.txt fetch itself timed out after "
    "688 s; its index also returns 403). Wellington was attempted via "
    "Wayback Machine snapshots of the same URLs.",
    "",
    "All other councils are unattempted, not dead ends. Full-country "
    "completion is a per-council PDF harvest over the remaining councils; "
    "see the pilot report for the measured per-council cost.",
]
(PILOT / "coverage_report.md").write_text("\n".join(lines) + "\n")

readme = f"""---
license: other
language:
- en
pretty_name: New Zealand Municipal Laws
---

# New Zealand Municipal Laws (seed)

Municipal bylaws of New Zealand local authorities, harvested from the
councils' own published PDFs and normalized into the world_municipal
19-column schema (one row per bylaw clause/section).

**Seed status: {len(councils)} of 78 councils, {total_docs} bylaws,
{total_rows} rows** — see `coverage_report.md` for the registry,
route notes and dead ends. Bylaws are public legal instruments published
by the councils; each row carries its source PDF URL. Retrieved
{RETRIEVED}.

Layout (Portugal precedent): `data/<CODE>_html.parquet` per council,
`<CODE>_validation.json` sidecars, `jurisdictions.jsonl` (all 78
councils), `coverage_report.md`, `scrapers/` (nz_pilot_build.py —
original harvester/splitter; nz_fetch.py — checkpointed disk-first
downloader; nz_build2.py/nz_build3.py — disk builders, build3 carries
the fixed section splitter used for the seed).
"""
(PILOT / "README.md").write_text(readme)

uploads = []  # (local path, repo path)
for code, v in sorted(councils.items()):
    uploads.append((PILOT / f"{code}_html.parquet", f"data/{code}_html.parquet"))
    uploads.append((PILOT / f"{code}_validation.json", f"data/{code}_validation.json"))
uploads += [
    (PILOT / "jurisdictions.jsonl", "jurisdictions.jsonl"),
    (PILOT / "coverage_report.md", "coverage_report.md"),
    (PILOT / "README.md", "README.md"),
    (PILOT / "nz_pilot_build.py", "scrapers/nz_pilot_build.py"),
    (PILOT / "nz_fetch.py", "scrapers/nz_fetch.py"),
    (PILOT / "nz_build2.py", "scrapers/nz_build2.py"),
    (PILOT / "nz_build3.py", "scrapers/nz_build3.py"),
    (PILOT / "nz_wellington_wb.py", "scrapers/nz_wellington_wb.py"),
]
for local, remote in uploads:
    if remote in existing and remote != "README.md":
        print(f"skip (exists): {remote}")
        continue
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset")
    print(f"uploaded: {remote}")

# ---------- remote verification ----------
info = api.dataset_info(REPO)
now = sorted(s.rfilename for s in info.siblings or [])
print(f"remote now: {len(now)} files")
for f in now:
    print(" ", f)
# round-trip one parquet and re-validate
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from huggingface_hub import hf_hub_download  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402
code0 = sorted(councils)[0]
p = hf_hub_download(REPO, f"data/{code0}_html.parquet", repo_type="dataset")
t = read_html_parquet(p)
errs = validate_table(t, jurisdiction_id=code0,
                      jurisdiction_name=names.get(code0, councils[code0]["name"]),
                      country="NZ")
print(f"round-trip {code0}: {t.num_rows} rows, errors={errs}")
assert not errs
print("PUBLISH VERIFIED")
