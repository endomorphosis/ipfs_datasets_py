"""France tranche 1 — merge Besançon checkpoints, validate, publish.

Merges checkpoint_25056.jsonl + checkpoint_25056_shard*.jsonl into
the full-corpus table with the pilot's exact gates, writes
data/25056_html.parquet + validation sidecar, then publishes:
supersedes 25056_html.parquet / 25056_validation.json in place,
refreshes coverage_report.md + README.md (full-corpus wording),
adds the tranche-1 scraper scripts under scrapers/, and
remote-verifies by re-downloading the parquet and re-running the
gates. jurisdictions.jsonl is NOT re-uploaded (unchanged).
Auth: HF vault surrogate, never persisted.
"""
import glob
import json
import os
import shutil
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche1"
DATA = OUT / "data"
DATA.mkdir(parents=True, exist_ok=True)
CODE = "25056"
REPO_ID = "endomorphosis/ipfs_france_municipal_laws"
RETRIEVED = "2026-10-14"
info = B.REGISTRY[CODE]
name = info["jurisdiction_name"]


def merge():
    corpus = json.loads((OUT / "besancon_corpus.json").read_text(encoding="utf-8"))
    docs_by_id = {}
    for d in corpus["docs"]:
        docs_by_id[d["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()] = d
    recs = {}
    ckpts = [OUT / "checkpoint_25056.jsonl"] + \
        [Path(p) for p in sorted(glob.glob(str(OUT / "checkpoint_25056_shard*.jsonl")))]
    ocr_ckpt = OUT / "checkpoint_25056_ocr.jsonl"
    if ocr_ckpt.exists():
        ckpts.append(ocr_ckpt)  # read LAST: OCR records override the deferred ones
    for path in ckpts:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["doc_id"]] = r
    print("checkpoints:", len(recs), "corpus:", len(docs_by_id),
          "missing:", sorted(set(docs_by_id) - set(recs))[:5])
    all_rows, meta = [], []
    for did in docs_by_id:
        r = recs.get(did)
        if r is None:
            meta.append({"doc_id": did, "status": "missing_checkpoint"})
            continue
        meta.append({k: v for k, v in r.items() if k != "rows"})
        all_rows.extend(r.get("rows", []))
    rows = B.drop_empty_rows(B.finalize_rows(all_rows))
    table = B.rows_to_table(rows)
    errs = B.validate_table(table, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    stats = {"corpus_docs": len(docs_by_id),
             "docs_ok": sum(1 for m in meta if m.get("status") in ("ok", "ok_ocr")),
             "docs_ocr_recovered": sum(1 for m in meta if m.get("status") == "ok_ocr"),
             "docs_ocr_deferred": sum(1 for m in meta if m.get("status") == "ocr_deferred_scanned_pdf"),
             "docs_fetch_failed": sum(1 for m in meta if str(m.get("status", "")).startswith("fetch_failed")),
             "rows_pre_finalize": len(all_rows), "rows": table.num_rows,
             "valid": not errs, "errors": errs,
             "per_year": corpus["per_year"]}
    (OUT / "besancon_build_result.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "besancon_doc_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    assert not errs and table.num_rows > 0, "gate failure — do not publish"
    B.write_html_parquet(DATA / B.FR.file_name(CODE), table)
    B.write_validation_report(DATA / f"{CODE}_validation.json",
                              B.validation_report(table, jurisdiction_id=CODE,
                                                  jurisdiction_name=name, country="FR"))
    t2 = B.read_html_parquet(DATA / B.FR.file_name(CODE))
    assert not B.validate_table(t2, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    print("local parquet written + reread valid:", table.num_rows, "rows")
    return stats


def build_docs(stats):
    lines = [
        "# Coverage report — ipfs_france_municipal_laws",
        "",
        f"Generated {RETRIEVED} by the France municipal-law campaign "
        "(legal_scrapers world_municipal_campaigns/fr_pilot + fr_tranche1).",
        "",
        "Registry: INSEE Code Officiel Géographique (COG), millésime 2026 "
        "(au 01/01/2026) — **34,875 communes** (TYPECOM=COM; arrondissements "
        "municipaux and communes associées/déléguées excluded), 18 régions.",
        "",
        f"Published: 1 commune at FULL corpus coverage — Besançon (25056): "
        f"{stats['corpus_docs']} délibérations enumerated on the Grand "
        f"Besançon affichage webservice (2024: 382, 2025: 372, 2026: 241), "
        f"{stats['docs_ok']} harvested "
        f"({stats.get('docs_ocr_recovered', 0)} of them via fra OCR of "
        f"scanned PDFs — the route is robots-allowed and the tessroot "
        f"carries fra), {stats['docs_ocr_deferred']} still OCR-deferred, "
        f"{stats['docs_fetch_failed']} fetch-failed → **{stats['rows']} rows**. "
        "This supersedes the pilot seed's 16-document sample (83 rows).",
        "",
        "| Code INSEE | Commune | Région | Route | Corpus (docs) | Harvested | Rows |",
        "|---|---|---|---|---|---|---|",
        f"| 25056 | Besançon | Bourgogne-Franche-Comté | Grand Besançon "
        f"affichage webservice (own host, no robots restrictions) | "
        f"{stats['corpus_docs']} | {stats['docs_ok']} | {stats['rows']} |",
        "",
        "## Tranche-1 route census (2026-10-14, data.gouv API metadata + full robots.txt reads)",
        "",
        "- **data.gouv.fr API census** (metadata only — robots-clean): 469 "
        "datasets across 15 searches, 127 with PDF resources = 10,608 PDFs. "
        "10,584 of them sit on static.data.gouv.fr whose robots.txt disallows "
        "`/resources` for `User-agent: *` → **PARKED** (Soissons 3,571, Pirae "
        "1,099, Jouarre 258, Berck 160, Castelmaurou 116, …).",
        "- **Opendatasoft** (the dominant family): the FULL robots.txt of 12 "
        "ODS hosts was read (Rennes, Nantes, Bordeaux ×2, Toulouse, "
        "Strasbourg, Paris, Anglet, Blois ×2, CapAtlantique, CARENE) — every "
        "one disallows `/api/` for `User-agent: *` (Googlebot-only Allow) → "
        "**PARKED**.",
        "- **Montpellier (data.montpellier3m.fr)**: NOT an ODS portal — a "
        "DKAN/Drupal catalogue whose robots.txt (Crawl-delay 10) does not bar "
        "the content paths → robots-ALLOWED, but its catalogue holds no "
        "délibérations/actes dataset (administration + citoyenneté categories "
        "and the catalogue front page checked; the only arrêtés dataset is "
        "temporary traffic orders), and the host is intermittent from this "
        "egress (API-style and POST requests ProxyError/time out). Nothing "
        "harvestable this tranche.",
        "- **Grand Besançon portal (data.grandbesancon.fr)**: robots.txt is a "
        "sitemap line only → ALLOWED. Its affichage services are all "
        "Besançon bodies (Ville, Métropole, CCAS, District) — censused, not "
        "commune-attributable beyond Besançon itself.",
        "- **Martigues** document server: `Disallow: /` → PARKED. **Chelles** "
        "(ArcGIS Hub): Hub robots allows with Crawl-delay 60 but the "
        "FeatureServer is token-walled (499) → PARKED. datacat.datalocale.fr, "
        "geo.brest-metropole.fr, datasud.fr, brest.fr, ccpro.fr: unreachable "
        "from this egress (timeouts/ProxyError).",
        "",
        "Net: France's obligated-commune bulk stays robots-parked; the only "
        "open channel found is the Besançon-class own-host affichage service, "
        "and no second instance of that class was found in the census. "
        "Remaining Besançon backlog: the webservice's pre-2024 archive "
        "(2020–2023) is the same allowed route, not yet harvested.",
        "",
        "All published parquets pass the world_municipal fail-closed gates "
        "(19-column schema; preamble + one row per Article where the act has "
        "articles, else one body row per document).",
    ]
    (DATA / "coverage_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readme = f"""# ipfs_france_municipal_laws

French municipal law (délibérations du conseil municipal — council
deliberations and decisions) normalized to the shared `world_municipal`
19-column schema used across the world-municipal-law program in
`endomorphosis/ipfs_datasets_py`
(`ipfs_datasets_py/processors/legal_scrapers/world_municipal/`).

**Status: 1 commune at full corpus coverage, {RETRIEVED}.** Besançon
(25056) is represented by its complete enumerated corpus —
{stats['corpus_docs']} délibérations (2024–2026) from the Grand
Besançon affichage webservice, {stats['rows']} rows. The registry
holds 34,875 communes (INSEE COG, millésime 2026); most French
publication channels disallow bots in robots.txt and are documented
in `coverage_report.md`, not worked around — see the tranche-1 route
census summarized there.

## Layout (Portugal precedent)

- `<Code INSEE>_html.parquet` — one file per commune; one row per
  Article where the act has articles, plus a preamble row, else one
  body row per document.
- `<code>_validation.json` — fail-closed gate report per parquet.
- `jurisdictions.jsonl` — the full INSEE COG registry (34,875 communes).
- `scrapers/` — the harvesters that produced this dataset (also in
  the repo under `legal_scrapers/world_municipal_campaigns/fr_pilot/`
  and `fr_tranche1/`).

## Sources

- Besançon (25056, Doubs, Bourgogne-Franche-Comté): Grand Besançon
  affichage webservice at datasets.grandbesancon.fr — structured JSON
  index of council sessions and their délibérations, per-act PDFs on
  the same host (no robots.txt restrictions); corpus enumerated in
  full: {stats['corpus_docs']} délibérations (2024: 382, 2025: 372,
  2026: 241).

`source_url` in every row points at the act's PDF on the publishing
body's own host. Acts are public legal texts published by the communes
themselves (publication des actes, communes ≥ 3,500 inhabitants).
"""
    (DATA / "README.md").write_text(readme, encoding="utf-8")


def main():
    from huggingface_hub import HfApi, hf_hub_download
    stats = merge()
    build_docs(stats)
    entry = dynamic_credential_entry("custom.huggingface")
    api = HfApi(token=entry["surrogate"])
    api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True)

    uploads = [
        (DATA / f"{CODE}_html.parquet", f"{CODE}_html.parquet"),
        (DATA / f"{CODE}_validation.json", f"{CODE}_validation.json"),
        (DATA / "coverage_report.md", "coverage_report.md"),
        (DATA / "README.md", "README.md"),
    ]
    scripts_dir = OUT / "scripts"
    for fn in sorted(os.listdir(scripts_dir)):
        if fn.endswith(".py"):
            uploads.append((scripts_dir / fn, f"scrapers/{fn}"))
    for local, repo_path in uploads:
        if not local.exists():
            raise SystemExit(f"missing local file: {local}")
    for local, repo_path in uploads:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=repo_path,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"FR tranche 1: {repo_path}")
        print("uploaded", repo_path, flush=True)

    print("--- remote verification ---")
    tmp = OUT / "scratch" / "verify"
    tmp.mkdir(parents=True, exist_ok=True)
    p = hf_hub_download(REPO_ID, f"{CODE}_html.parquet", repo_type="dataset",
                        local_dir=str(tmp))
    t = B.read_html_parquet(Path(p))
    errs = B.validate_table(t, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    print("remote rows:", t.num_rows, "valid:", not errs, errs)
    assert t.num_rows == stats["rows"] and not errs
    remote = {f.rfilename for f in api.list_repo_tree(REPO_ID, repo_type="dataset", recursive=True)
              if getattr(f, "rfilename", None)}
    print("remote files:", sorted(remote))
    shutil.rmtree(tmp, ignore_errors=True)
    print("PUBLISH + VERIFY DONE")


if __name__ == "__main__":
    main()
