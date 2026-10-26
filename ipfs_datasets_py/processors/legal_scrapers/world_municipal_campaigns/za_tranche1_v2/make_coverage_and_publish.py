"""ZA tranche 1 (v2): coverage report generation + publish + remote verify.

Uploads ONLY: the 11 complete data/<MDB>_html.parquet (5 pilot seed
files superseded in place, same paths; 6 new), manifests/
za_overlap_crosswalk.jsonl, an updated coverage_report.md, and the
tranche builder under scrapers/za_akn_tranche1_build.py.
README.md is NOT touched. No Layer 1 file is touched.
HF auth via the vault connector surrogate (dynamic_credentials),
exactly as the verified pilot publish did; no token is persisted.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

V2 = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/za_tranche1_v2"
REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
RETRIEVED = "2026-10-12"
MDB_ORDER = ["CPT", "ETH", "JHB", "EC443", "WC011", "WC012", "WC013",
             "WC015", "WC023", "WC033", "WC041"]

manifest = json.load(open(V2 / "run_manifest.json"))
muns = manifest["municipalities"]
assert set(muns) == set(MDB_ORDER), f"municipalities present: {sorted(muns)}"
for code, v in muns.items():
    assert v.get("complete") and v.get("valid"), f"{code} not complete/valid: {v.get('errors')}"

tot_works = sum(v["works"] for v in muns.values())
tot_docs = sum(v["docs_ingested"] for v in muns.values())
tot_excl = sum(v["docs_excluded"] for v in muns.values())
tot_rows = sum(v["rows"] for v in muns.values())
tot_afr = sum(1 for v in muns.values() for d in v["docs"] if d["lang"] == "afr")
tot_afr_excl = sum(1 for v in muns.values() for d in v["excluded"] if d["lang"] == "afr")
assert tot_works == 576, tot_works
assert tot_docs + tot_excl == 576, (tot_docs, tot_excl)

# ---------------- coverage report ----------------
lines = [
    "# Coverage report — South Africa municipal laws (AKN layer complete)",
    "",
    f"Retrieved {RETRIEVED} from Open By-laws (https://openbylaws.org.za), a project of "
    "Laws.Africa and AfricanLII (part of LawLibrary.org.za), which publishes South African "
    "municipal by-laws as Akoma Ntoso (AKN). This tranche ingests the site's public AKN HTML "
    "expressions via its robots-permitted routes only (sitemap, /legislation/<place>/ listings, "
    "/akn/ document pages; Crawl-delay 5 respected with 6 s pacing; /api/, /search/ and "
    "/akn/*/provision/ are robots-disallowed and were not used). The Laws.Africa Content API "
    "is token-gated/paid and was not used.",
    "",
    "## Denominator",
    "",
    "South Africa has **257 municipalities** since the 2016 demarcation: 8 metropolitan "
    "(Category A), 44 district (Category C) and 205 local (Category B). The full registry — "
    "Municipal Demarcation Board (MDB) code, name, province, category — is in "
    "`jurisdictions.jsonl` (MDB-verified 257/257 on codes/category/province against the MDB's "
    "own ArcGIS layers; see the reconciliation audit).",
    "",
    "## AKN coverage — COMPLETE for this route",
    "",
    "Open By-laws carries by-laws for **11 of 257 municipalities**. Its robots-referenced "
    f"sitemap listed **576 works** on {RETRIEVED}. All 576 were fetched and processed in "
    "this tranche: "
    f"**{tot_docs} works carried AKN HTML and were ingested** "
    f"({tot_rows} section-level rows); **{tot_excl} works were excluded** because their "
    "public pages are PDF-only viewer stubs with no AKN HTML content (or yielded no "
    "extractable section-level units) — each excluded work, with its reason, is listed in "
    "the tranche report and in the builder's run manifest. Excluded works were not forced "
    "past the content gates.",
    "",
    "| MDB code | Municipality | Sitemap works | Ingested | Excluded (no AKN HTML) | Rows |",
    "|---|---|---|---|---|---|",
]
for code in MDB_ORDER:
    v = muns[code]
    lines.append(f"| {code} | {v['name']} | {v['works']} | {v['docs_ingested']} | "
                 f"{v['docs_excluded']} | {v['rows']} |")
lines += [
    f"| **Total** | **11 municipalities** | **{tot_works}** | **{tot_docs}** | "
    f"**{tot_excl}** | **{tot_rows}** |",
    "",
    f"Afrikaans-only expressions: {tot_afr} ingested works exist only as `afr@` "
    f"expressions (plus {tot_afr_excl} excluded afr@ works); they were ingested as "
    "Afrikaans and their language is recorded per work in the tranche manifest. "
    "Rows are AKN section-level units (sections, preambles/prefaces, schedules; "
    "subsections ride inside their section), normalized to the world_municipal "
    "19-column schema. Every file passed the fail-closed gates on an independent "
    "re-read: exact schema, sequential doc_order, unique doc_id/cid, zero empty "
    "docs, constant MDB attribution. The five pilot-seed files (CPT, ETH, JHB, "
    "WC013, WC023) are superseded in place by complete per-municipality files; "
    "the 20 pilot works are included in them.",
    "",
    "## The other layer in this repo, and the eThekwini crosswalk",
    "",
    "This repo also holds a pre-existing corpus (Layer 1: `data/laws-*.parquet` + "
    "`data/articles-*.parquet`, from metro websites and Provincial Gazettes), which is "
    "untouched by this tranche. The AKN / world_municipal layer (`data/<MDB>_html.parquet`) "
    "is canonical for the 11 AKN municipalities; Layer 1 is canonical where it is the "
    "only layer. The layers overlap only in eThekwini (ETH): of ETH's 58 AKN works, "
    "33 match Layer 1 documents, 25 are AKN-only, and 12 of Layer 1's 45 ETH documents "
    "have no AKN counterpart. All of these pairs are published as "
    "`manifests/za_overlap_crosswalk.jsonl` (MDB code, AKN work URI, Layer 1 law id, "
    "confidence), including the explicit Layer 1 id mappings za-bcm -> BUF and "
    "za-ekh -> EKU (mapping in the crosswalk only; no published Layer 1 id was renamed). "
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
    "should respect the source terms; see the pilot report's flagged-ambiguity note.",
    "",
]
(V2 / "out" / "coverage_report.md").write_text("\n".join(lines))
print(f"coverage_report.md written: {tot_docs} docs, {tot_excl} excluded, {tot_rows} rows")

# ---------------- publish ----------------
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

entry = dynamic_credential_entry("custom.huggingface")
token = entry.get("surrogate") if isinstance(entry, dict) else None
if not token:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)
info = api.dataset_info(REPO_ID)
existing = {s.rfilename for s in info.siblings or []}
print(f"BEFORE: {len(existing)} files")
before_html = sorted(f for f in existing if f.endswith("_html.parquet"))
print("BEFORE *_html.parquet:", before_html)

uploads = []
for code in MDB_ORDER:
    uploads.append((V2 / "out" / f"{code}_html.parquet", f"data/{code}_html.parquet"))
uploads += [
    (V2 / "out" / "za_overlap_crosswalk.jsonl", "manifests/za_overlap_crosswalk.jsonl"),
    (V2 / "out" / "coverage_report.md", "coverage_report.md"),
    (V2 / "za_akn_tranche1_build.py", "scrapers/za_akn_tranche1_build.py"),
]
for local, remote in uploads:
    assert local.exists(), local
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO_ID, repo_type="dataset",
                    commit_message=f"ZA AKN tranche 1: {remote}")
    print(f"uploaded: {remote}")

info = api.dataset_info(REPO_ID)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"AFTER: {len(files)} files")
expected = {r for _, r in uploads}
missing = expected - set(files)
print("MISSING:", missing if missing else "none")
assert not missing
assert "README.md" in files
json.dump({"before_count": len(existing), "after_count": len(files),
           "after_files": files}, open(V2 / "publish_result.json", "w"), indent=2)
print("PUBLISH DONE")
