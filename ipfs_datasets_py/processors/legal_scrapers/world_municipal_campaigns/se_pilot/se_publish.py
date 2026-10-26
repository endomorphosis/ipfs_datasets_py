"""Sweden pilot — publish validated seed to
endomorphosis/ipfs_sweden_municipal_laws (Portugal layout).
Runs only on kommuner marked valid in run_manifest.json; dedupes
against the live repo before uploading (additive)."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/se_pilot"
REPO = "endomorphosis/ipfs_sweden_municipal_laws"
RETRIEVED = "2026-10-14"

manifest = json.loads((PILOT / "run_manifest.json").read_text())
kommuner = {k: v for k, v in manifest["kommuner"].items() if v.get("valid")}
failed = {k: v for k, v in manifest["kommuner"].items() if not v.get("valid")}
assert kommuner, "no valid kommuner in manifest — refusing to publish"
total_rows = sum(v["rows"] for v in kommuner.values())
total_docs = sum(len([d for d in v["docs"] if not d.get("skipped")]) for v in kommuner.values())

entry = dynamic_credential_entry("custom.huggingface")
tok = entry.get("surrogate")
if not tok:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=tok)

try:
    info = api.dataset_info(REPO)
    existing = {s.rfilename for s in info.siblings or []}
    print(f"dataset exists: {len(existing)} files")
except Exception as e:  # noqa: BLE001
    print("dataset_info failed (creating):", type(e).__name__, str(e)[:100])
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = set()

names = {r["jurisdiction_id"]: r["jurisdiction_name"] for r in
         (json.loads(ln) for ln in (PILOT / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines())}
fetch = json.loads((PILOT / "fetch_manifest.json").read_text())

lines = [
    "# Coverage report — Sweden municipal laws (seed)",
    "",
    f"Retrieved {RETRIEVED} from the kommuners' own websites. Sweden has "
    "**290 kommuner**, each statutorily required (Kommunallagen) to keep "
    "its kommunala föreskrifter publicly available on its website in a "
    "**författningssamling**. Jurisdiction IDs are SCB kommunkoder "
    "(4-digit: 2-digit län code + 2-digit kommun code). The full "
    "registry is in `jurisdictions.jsonl`.",
    "",
    "## Route",
    "",
    "No national register of municipal föreskrifter exists; the route is "
    "per-kommun harvest of the författningssamling index page each "
    "kommun maintains, respecting each site's robots.txt. Platforms in "
    "the pilot sample: **SiteVision** dominates (Västerås, Malmö, "
    "Örebro, Umeå, Luleå, Jönköping, Gotland — documents served at "
    "`/download/18.<hash>/<file>.pdf`), Uppsala runs "
    "Episerver/Optimizely (doc landing pages link a canonical PDF "
    "under `/contentassets/<hash>/`), Stockholm and Göteborg are "
    "bespoke. PDF text is extracted with PyMuPDF -> pdfplumber -> "
    "pdftotext (no OCR rung in the pilot environment) and split into "
    "§-level rows in the world_municipal 19-column schema; both "
    "Swedish numbering conventions are handled ('1 §' föreskrift "
    "style, '§ 3' reglemente style, plus 'N.' numbered headings).",
    "",
    "## Seed status",
    "",
    f"**{len(kommuner)} of 290 kommuner** seeded by this pilot "
    f"({total_docs} documents, {total_rows} section rows):",
    "",
    "| Code | Kommun | Documents | Rows |",
    "|---|---|---|---|",
]
for code, v in sorted(kommuner.items()):
    ndocs = len([d for d in v["docs"] if not d.get("skipped")])
    lines.append(f"| {code} | {names.get(code, v['name'])} | {ndocs} | {v['rows']} |")
lines += [
    "",
    "Documents that are prose-structured (no §/numbered-heading "
    "structure, e.g. Umeå's attestreglemente and the two Malmö "
    "nature-reserve föreskrifter) ship as single doc-level rows; "
    "§-structured documents split at paragraph level.",
    "",
    "## Route outcomes for the 12-kommun probe sample",
    "",
    "- **Harvested (seed):** Uppsala 0380 (index at "
    "`/kommun-och-politik/dokumentsamlingar/lokala-foreskrifter/`), "
    "Malmö 1280 (index at `/forfattningssamling` -> "
    "`/Om-Malmo-stad/.../Forfattningssamling.html` category pages), "
    "Västerås 1980 (index at `/kommun-och-politik/forfattningssamling`, "
    "82 documents listed), Umeå 2480 (index at `/styrdokument`, 123 "
    "document links, 8 KFS-class).",
    "- **Örebro 1880 — index found, document list is JS-rendered.** "
    "The författningssamling index exists (SiteVision category pages) "
    "but the document lists load dynamically; zero static PDF anchors. "
    "Needs the SiteVision document-archive API or a rendered fetch.",
    "- **Gotland 0980 — index found, document list is JS-rendered.** "
    "Dedicated författningssamling tree at "
    "`/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument/`; "
    "category pages carry no static PDF anchors (same SiteVision "
    "document widget as Örebro).",
    "- **Index not located in the pilot window:** Stockholm 0180 "
    "(start.stockholm), Göteborg 1480, Linköping 0580 (KFS described "
    "under 'Regler och styrande dokument' — a document portal needing "
    "its own discovery), Luleå 2580, Jönköping 0680, Gävle 2180 "
    "(/styrdokument exists but lists subpages, not documents). All are "
    "unattempted beyond index discovery, **not dead ends**.",
    "- **Explicitly out of scope:** länsstyrelsernas "
    "författningssamlingar (county administrative board collections — "
    "the '03FS'/'18FS'/'24FS' series on lansstyrelsen.se) are "
    "county-state law, not kommun law, and are excluded even where "
    "they promulgate documents *about* a kommun. Municipal traffic "
    "föreskrifter also appear in Transportstyrelsen's RDT database — "
    "a possible supplementary source for that subset, not used here.",
    "- **Robots posture:** robots.txt fetched for all 12 sampled "
    "kommuner before content fetches (all HTTP 200 via curl); no "
    "collection or download path used is disallowed (SiteVision "
    "boilerplate disallows cover image/checkout actions and printable "
    "variants; Uppsala disallows its search path and two legacy "
    "sections, neither used).",
    "",
    "All other kommuner are unattempted, not dead ends. Full-country "
    "completion is a per-kommun harvest over the remaining 286 "
    "kommuner preceded by a platform/index census; see the pilot "
    "report for the measured per-kommun cost.",
]
(PILOT / "coverage_report.md").write_text("\n".join(lines) + "\n")

readme = f"""---
license: other
language:
- sv
pretty_name: Sweden Municipal Laws
---

# Sweden Municipal Laws (seed)

Municipal föreskrifter and reglementen (the statutory
författningssamling collections) of Swedish kommuner, harvested from
the kommuners' own published PDFs and normalized into the
world_municipal 19-column schema (one row per §/section).

**Seed status: {len(kommuner)} of 290 kommuner, {total_docs}
documents, {total_rows} rows** — see `coverage_report.md` for the
registry, route notes and per-kommun outcomes. The föreskrifter are
public legal instruments published by the kommuner under the
Kommunallagen; each row carries its source PDF URL. Retrieved
{RETRIEVED}.

Layout (Portugal precedent): `data/<CODE>_html.parquet` per kommun
(CODE = SCB kommunkod), `<CODE>_validation.json` sidecars,
`jurisdictions.jsonl` (all 290 kommuner), `coverage_report.md`,
`scrapers/` (se_probe.py — site/robots probe; se_discover.py —
collection-index discovery; se_fetch.py / se_fetch2.py /
se_fetch3.py — checkpointed curl fetchers; se_build.py — §-splitter
builder; fetch_registry.py + build_registry.py — SCB registry).
"""
(PILOT / "README.md").write_text(readme)

uploads = []
for code, v in sorted(kommuner.items()):
    uploads.append((PILOT / f"{code}_html.parquet", f"data/{code}_html.parquet"))
    uploads.append((PILOT / f"{code}_validation.json", f"data/{code}_validation.json"))
uploads += [
    (PILOT / "jurisdictions.jsonl", "jurisdictions.jsonl"),
    (PILOT / "coverage_report.md", "coverage_report.md"),
    (PILOT / "README.md", "README.md"),
    (PILOT / "se_probe.py", "scrapers/se_probe.py"),
    (PILOT / "se_discover.py", "scrapers/se_discover.py"),
    (PILOT / "se_fetch.py", "scrapers/se_fetch.py"),
    (PILOT / "se_fetch2.py", "scrapers/se_fetch2.py"),
    (PILOT / "se_fetch3.py", "scrapers/se_fetch3.py"),
    (PILOT / "se_build.py", "scrapers/se_build.py"),
    (PILOT / "fetch_registry.py", "scrapers/fetch_registry.py"),
    (PILOT / "build_registry.py", "scrapers/build_registry.py"),
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
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from huggingface_hub import hf_hub_download  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402
for code0 in sorted(kommuner):
    p = hf_hub_download(REPO, f"data/{code0}_html.parquet", repo_type="dataset")
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=code0,
                          jurisdiction_name=names.get(code0), country="SE")
    print(f"round-trip {code0}: rows={t.num_rows} errors={errs}")
    assert not errs, errs
print("PUBLISH OK")
