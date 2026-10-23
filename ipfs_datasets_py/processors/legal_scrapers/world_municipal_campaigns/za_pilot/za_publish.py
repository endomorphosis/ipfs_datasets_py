"""South Africa pilot — publish validated seed to
endomorphosis/ipfs_south_africa_municipal_laws (Portugal layout).
Runs only after all world_municipal gates pass; dedupes against the
live repo before uploading."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/za_pilot"
REPO = "endomorphosis/ipfs_south_africa_municipal_laws"
RETRIEVED = "2026-10-12"

manifest = json.load(open(PILOT / "run_manifest.json"))
muns = manifest["municipalities"]
assert all(v["valid"] for v in muns.values()), "gate failure in manifest — refusing to publish"
total_rows = sum(v["rows"] for v in muns.values())
total_docs = sum(len([d for d in v["docs"] if "title" in d]) for v in muns.values())

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
    "# Coverage report — South Africa municipal laws (seed)",
    "",
    f"Retrieved {RETRIEVED} from Open By-laws (https://openbylaws.org.za), a "
    "project of Laws.Africa and AfricanLII (part of LawLibrary.org.za), which "
    "publishes South African municipal by-laws as Akoma Ntoso (AKN). This seed "
    "ingests the site's public AKN HTML expressions via its robots-permitted "
    "routes only (sitemap, /legislation/<place>/ listings, /akn/ document "
    "pages; Crawl-delay 5 respected with 6 s pacing; /api/, /search/ and "
    "/akn/*/provision/ are robots-disallowed and were not used). The "
    "Laws.Africa Content API is token-gated/paid and was not used.",
    "",
    "## Denominator",
    "",
    "South Africa has **257 municipalities** since the 2016 demarcation: "
    "8 metropolitan (Category A), 44 district (Category C) and 205 local "
    "(Category B). The full registry — Municipal Demarcation Board (MDB) "
    "code, name, province, category — is in `jurisdictions.jsonl` "
    "(transcribed from the MDB/Stats SA-derived municipality list and "
    "count-verified at 257 = 8 + 44 + 205).",
    "",
    "## AKN coverage (the adopt-first route)",
    "",
    "Open By-laws carries by-laws for **11 of 257 municipalities**. Its "
    f"robots-referenced sitemap listed **{manifest['sitemap_works_total']} works** "
    f"on {RETRIEVED}:",
    "",
    "| AKN place | MDB code | Works in sitemap |",
    "|---|---|---|",
]
place2code = {"za-cpt": "CPT", "za-jhb": "JHB", "za-eth": "ETH", "za-wc013": "WC013",
              "za-wc033": "WC033", "za-wc012": "WC012", "za-wc023": "WC023",
              "za-wc041": "WC041", "za-wc011": "WC011", "za-wc015": "WC015",
              "za-ec443": "EC443"}
for place, n in sorted(manifest["sitemap_per_place"].items(), key=lambda kv: -kv[1]):
    lines.append(f"| {place} | {place2code.get(place, '')} | {n} |")
lines += [
    "",
    "The other **246 municipalities have no AKN coverage** on this route. "
    "Their by-laws exist in Provincial Gazettes and on municipal websites "
    "(PDF long-tail); the Sabinet Municipal By-laws index is paywalled and "
    "is not used. See the pilot report for the full-country estimate.",
    "",
    f"## Published in this seed: {len(muns)} municipalities, {total_docs} by-laws, {total_rows} rows",
    "",
    "| MDB code | Municipality | By-laws | Rows |",
    "|---|---|---|---|",
]
for code, v in sorted(muns.items()):
    ndocs = len([d for d in v["docs"] if "title" in d])
    lines.append(f"| {code} | {v['name']} | {ndocs} | {v['rows']} |")
lines += [
    "",
    "Rows are AKN section-level units (sections, preambles/prefaces, "
    "schedules; subsections ride inside their section), normalized to the "
    "world_municipal 19-column schema. Every file passed the fail-closed "
    "gates on an independent re-read: exact schema, sequential doc_order, "
    "unique doc_id/cid, zero empty docs, constant MDB attribution.",
    "",
    "## Licence and attribution",
    "",
    "Legislation provided by Laws.Africa and their contributors under a "
    "CC-BY-NC-SA license (as stated at laws.africa/api). There is no "
    "copyright in the original by-law texts themselves (per the SAFLII / "
    "Open By-laws mirror note; the HTML form was historically offered "
    "under CC BY 2.5 ZA). This dataset is a non-commercial republication "
    "with attribution and share-alike terms. Note: openbylaws.org.za's "
    "robots.txt carries Content-Signals ai-train=no / ai-input=no — "
    "downstream users should respect the source terms; see the pilot "
    "report's flagged-ambiguity note.",
    "",
]
(PILOT / "coverage_report.md").write_text("\n".join(lines))

readme = f"""---
license: cc-by-nc-sa-4.0
language:
- en
pretty_name: South Africa Municipal Laws (Open By-laws / Laws.Africa AKN ingest)
---

# South Africa — Municipal Laws

Municipal by-laws of South Africa, normalized to the shared
`world_municipal` 19-column schema (one row per AKN section-level unit,
one parquet per municipality under `data/`).

**Seed status ({RETRIEVED}): {len(muns)} of 257 municipalities,
{total_docs} by-laws, {total_rows} rows.** The seed covers five of the
eleven municipalities published as Akoma Ntoso by Open By-laws
(Laws.Africa / AfricanLII); the remaining six AKN municipalities and
the 246 municipalities without AKN coverage are future tranches — see
`coverage_report.md` for the full denominator, per-place AKN counts
and the gap analysis. The full 257-municipality registry (Municipal
Demarcation Board codes) is in `jurisdictions.jsonl`.

## Source and attribution

By-laws ingested from [Open By-laws](https://openbylaws.org.za)
(public AKN HTML expressions; robots-permitted routes only, crawl-delay
respected). Legislation provided by Laws.Africa and their contributors
under a CC-BY-NC-SA license. There is no copyright in the original
by-law texts themselves. The harvester is in `scrapers/`
(`za_pilot_build.py`, built on the `world_municipal` normalization
library from `Endomorphosis/ipfs_datasets_py`).

## Schema

`cid, jurisdiction_id (MDB code), jurisdiction_name, country ("ZA"),
doc_id, regeling_id / regeling_work_id (AKN work FRBR URI), doc_order,
title, structural_path, node_label, html_title, html, text, source_url
(AKN expression page), xml_url (AKN work page), date_effective
(expression date), date_modified, retrieved`.
"""
(PILOT / "README.md").write_text(readme)

uploads = []
for code in sorted(muns):
    uploads.append((PILOT / f"{code}_html.parquet", f"data/{code}_html.parquet"))
uploads += [
    (PILOT / "jurisdictions.jsonl", "jurisdictions.jsonl"),
    (PILOT / "coverage_report.md", "coverage_report.md"),
    (PILOT / "README.md", "README.md"),
    (PILOT / "za_pilot_build.py", "scrapers/za_pilot_build.py"),
]
for local, remote in uploads:
    if remote in existing:
        print(f"skip (already on HF): {remote}")
        continue
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"South Africa seed: {remote}")
    print(f"uploaded: {remote}")

info = api.dataset_info(REPO)
files = sorted(s.rfilename for s in info.siblings or [])
print("REMOTE FILES:", json.dumps(files, indent=2))
expected = {r for _, r in uploads}
missing = expected - set(files)
print("MISSING:", missing if missing else "none")
assert not missing
print(f"PUBLISH VERIFIED: {REPO} — {len(muns)} municipalities, {total_rows} rows")
