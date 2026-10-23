"""Japan pilot — publish the seed of endomorphosis/ipfs_japan_municipal_laws.

Additive-only: creates the repo if needed, refuses to overwrite an
existing data file, uploads per-jurisdiction parquets + validation
sidecars + jurisdictions.jsonl + coverage_report.md + README.md +
scrapers/, then remote-verifies by re-downloading every parquet and
re-running the world_municipal gates. Auth: HF vault surrogate, never
persisted.
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.schema import validate_table  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
DATA = OUT / "data"
REPO_ID = "endomorphosis/ipfs_japan_municipal_laws"
RETRIEVED = "2026-10-14"


def build_docs(manifest):
    pubs = {c: v for c, v in manifest["municipalities"].items() if v.get("valid")}
    total_rows = sum(v["rows"] for v in pubs.values())
    total_docs = sum(v["sampled_docs"] for v in pubs.values())
    lines = [
        "# Coverage report — ipfs_japan_municipal_laws (SEED)",
        "",
        f"Generated {RETRIEVED} by the Japan municipal-law pilot "
        "(legal_scrapers world_municipal_campaigns/jp_pilot).",
        "",
        f"Registry: MIC （総務省） 全国地方公共団体コード list, 2024-01-01 — "
        "1,794 registered bodies (47 prefectures, 1,724 municipalities, "
        "23 Tokyo special wards; designated-city wards are in the MIC "
        "designated-cities sheet and do not enact ordinances).",
        "",
        f"Published in this seed: {len(pubs)} municipalities, "
        f"{total_docs} ordinances sampled, {total_rows} rows. Per municipality "
        "the sample is 16 ordinances drawn deterministically (up to 4 from "
        "the first chapter + evenly spaced picks) from the fully enumerated "
        "corpus shown below — this is a pilot seed, not full coverage.",
        "",
        "| JIS X 0402 | Municipality | System | Corpus (ordinances) | Sampled | Rows |",
        "|---|---|---|---|---|---|",
    ]
    fam_name = {"reikibase": "Reiki-Base (Gyosei, self-hosted)",
                "d1law": "Daiichi Hoki d1-law system"}
    for c, v in sorted(pubs.items()):
        lines.append(f"| {c} | {v['name']} | {fam_name.get(v['family'], v['family'])} "
                     f"| {v['corpus_docs']} | {v['sampled_docs']} | {v['rows']} |")
    lines += [
        "",
        "## Documented dead ends (not published)",
        "",
        "- 11100 さいたま市 / 47201 那覇市： 例規集 hosted on www1.g-reiki.net "
        "(Gyosei cloud) — the host returns 403 for every path from this "
        "egress, including robots.txt; not harvestable from here.",
        "- 28100 神戸市： 例規集 section on the city CMS returns 403 from this egress.",
        "- 01202 函館市： d1-law tenant archived in the Wayback Machine but "
        "the live tenant no longer answers (connection fails) — tenant retired.",
        "- 14100 横浜市： /reiki/ path is a redirect to a 404 page.",
        "",
        "All published parquets pass the world_municipal fail-closed gates "
        "(19-column schema, article-level rows: preamble + one row per 条 "
        "+ one row per 附則 block).",
    ]
    (DATA / "coverage_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readme = f"""# ipfs_japan_municipal_laws

Japanese municipal law （条例・規則 — ordinances and rules) normalized to
the shared `world_municipal` 19-column schema used across the
world-municipal-law program in `endomorphosis/ipfs_datasets_py`
(`ipfs_datasets_py/processors/legal_scrapers/world_municipal/`).

**Status: SEED (pilot), {RETRIEVED}.** {len(pubs)} of 1,794 registered
local bodies (MIC 全国地方公共団体コード， 2024-01-01) are represented, each
by a deterministic 16-ordinance sample of its fully enumerated 例規集
corpus — {total_rows} article-level rows in total. See
`coverage_report.md` for per-municipality corpus sizes, the sampling
rule, and documented dead ends. This is not full coverage of any
municipality yet; the harvesters enumerate each corpus completely, so
scaling a municipality is a sampling-parameter change, not new code.

## Layout (Portugal precedent)

- `<JIS X 0402 code>_html.parquet` — one file per municipality; one row
  per article （条）, plus a preamble row （題名・公布） and one row per
  supplementary-provisions block （附則） per ordinance.
- `<code>_validation.json` — fail-closed gate report per parquet.
- `jurisdictions.jsonl` — the full MIC registry (1,794 bodies) with
  5-digit JIS X 0402 codes (6-digit MIC form incl. check digit retained).
- `scrapers/` — the pilot harvester/registry builder that produced this
  seed (also in the repo under
  `legal_scrapers/world_municipal_campaigns/jp_pilot/`).

## Sources

- 福岡市 (40130): Reiki-Base （株式会社ぎょうせい）, self-hosted at
  city.fukuoka.lg.jp/d1w_reiki/ — corpus 1,340 ordinances.
- 長野市 (20201), 盛岡市 (03201), 福島市 (07201): Daiichi Hoki hosted
  例規集 at en3-jg.d1-law.com/<slug>/d1w_reiki/ — corpora 918 / 1,248 /
  987 ordinances.
- 熊本市 (43100): Daiichi Hoki system, older generation (Shift_JIS),
  self-hosted at city.kumamoto.jp/html/d1w_reiki/ — corpus 2,077
  ordinances (includes ordinances of towns merged into the city).

`source_url` in every row points at the ordinance's full-text page on
the publishing body's own system. `date_effective` carries the
promulgation date （公布日） converted from the Japanese era calendar to
ISO form. Ordinances are public legal texts published by the
municipalities themselves.
"""
    (DATA / "README.md").write_text(readme, encoding="utf-8")
    return pubs, total_rows


def main():
    from huggingface_hub import HfApi

    manifest = json.loads((OUT / "run_manifest.json").read_text(encoding="utf-8"))
    pubs, total_rows = build_docs(manifest)
    entry = dynamic_credential_entry("custom.huggingface")
    api = HfApi(token=entry["surrogate"])
    api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True)
    existing = {f.rfilename for f in api.list_repo_tree(REPO_ID, repo_type="dataset", recursive=True)
                if getattr(f, "rfilename", None)}

    uploads = []  # (local_path, repo_path)
    for code in sorted(pubs):
        uploads.append((DATA / f"{code}_html.parquet", f"{code}_html.parquet"))
        uploads.append((DATA / f"{code}_validation.json", f"{code}_validation.json"))
    uploads.append((DATA / "jurisdictions.jsonl", "jurisdictions.jsonl"))
    uploads.append((DATA / "coverage_report.md", "coverage_report.md"))
    uploads.append((DATA / "README.md", "README.md"))
    scrapers_dir = OUT / "scripts"
    for name in ("jp_build.py", "build_registry.py"):
        uploads.append((scrapers_dir / name, f"scrapers/{name}"))

    for local, repo_path in uploads:
        if not local.exists():
            raise SystemExit(f"missing local file: {local}")
    for local, repo_path in uploads:
        # Data files are immutable once published: skip ones already on
        # the Hub (incremental adds of new municipalities), never
        # overwrite them. Metadata/docs always refresh.
        if repo_path in existing and repo_path.endswith(("_html.parquet", "_validation.json")):
            print("already published, skipping", repo_path, flush=True)
            continue
        api.upload_file(path_or_fileobj=str(local), path_in_repo=repo_path,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"JP pilot seed: add {repo_path}")
        print("uploaded", repo_path, flush=True)

    # Remote verification: re-download every parquet, re-run gates.
    print("--- remote verification ---")
    remote = {f.rfilename for f in api.list_repo_tree(REPO_ID, repo_type="dataset", recursive=True)
              if getattr(f, "rfilename", None)}
    expected = {rp for _, rp in uploads}
    print("files remote:", len(remote), "expected uploads:", len(expected),
          "missing:", sorted(expected - remote))
    tmp = OUT / "scratch" / "verify"
    tmp.mkdir(parents=True, exist_ok=True)
    grand = 0
    for code in sorted(pubs):
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(REPO_ID, f"{code}_html.parquet", repo_type="dataset",
                            local_dir=str(tmp))
        t = read_html_parquet(Path(p))
        errs = validate_table(t, jurisdiction_id=code,
                              jurisdiction_name=pubs[code]["name"], country="JP")
        grand += t.num_rows
        print(code, pubs[code]["name"], "remote rows", t.num_rows, "valid", not errs, errs)
        assert t.num_rows == pubs[code]["rows"] and not errs
    print("TOTAL remote rows:", grand, "== local total:", total_rows, grand == total_rows)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
