"""France pilot — publish the seed of endomorphosis/ipfs_france_municipal_laws.

Additive-only: creates the repo if needed, refuses to overwrite an
existing data file, uploads per-commune parquets + validation sidecars
+ jurisdictions.jsonl + coverage_report.md + README.md + scrapers/,
then remote-verifies by re-downloading every parquet and re-running
the world_municipal gates. Auth: HF vault surrogate, never persisted.
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"  # httpx chokes on the ambient bracketed-IPv6 no_proxy
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.schema import validate_table  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
DATA = OUT / "data"
REPO_ID = "endomorphosis/ipfs_france_municipal_laws"
RETRIEVED = "2026-10-14"


def build_docs(manifest):
    pubs = {c: v for c, v in manifest["communes"].items() if v.get("valid")}
    total_rows = sum(v["rows"] for v in pubs.values())
    total_docs = sum(v["sampled_docs"] for v in pubs.values())
    lines = [
        "# Coverage report — ipfs_france_municipal_laws (SEED)",
        "",
        f"Generated {RETRIEVED} by the France municipal-law pilot "
        "(legal_scrapers world_municipal_campaigns/fr_pilot).",
        "",
        "Registry: INSEE Code Officiel Géographique (COG), millésime 2026 "
        "(au 01/01/2026) — **34,875 communes** (TYPECOM=COM; arrondissements "
        "municipaux and communes associées/déléguées excluded), 18 régions.",
        "",
        f"Published in this seed: {len(pubs)} commune(s), {total_docs} "
        f"documents sampled, {total_rows} rows. Per commune the sample is "
        "16 documents drawn evenly from the fully enumerated corpus below — "
        "this is a pilot seed, not full coverage.",
        "",
        "| Code INSEE | Commune | Région | Route | Corpus (docs) | Sampled | Rows |",
        "|---|---|---|---|---|---|---|",
    ]
    fam_name = {"besancon_webservice": "Grand Besançon affichage webservice (ville host, no robots restrictions)",
                "datagouv_static": "data.gouv.fr static resources",
                "arcgis_hub": "ArcGIS Hub"}
    for c, v in sorted(pubs.items()):
        lines.append(f"| {c} | {v['name']} | {v['region']} | "
                     f"{fam_name.get(v['family'], v['family'])} | {v['corpus_docs']} "
                     f"| {v['sampled_docs']} | {v['rows']} |")
    lines += [
        "",
        "## Surveyed but NOT published (robots / access walls — parked, not worked around)",
        "",
        "- **Opendatasoft portals** (the dominant platform family: Rennes, "
        "Nantes, Bordeaux, Toulouse, Strasbourg, Montpellier métropole, "
        "Anglet…): the standard ODS robots.txt disallows `/api/` for "
        "`User-agent: *` (only Googlebot is allowed), so the Explore API "
        "route is closed to this program.",
        "- **data.gouv.fr uploaded resources** (static.data.gouv.fr): the "
        "data.gouv robots.txt disallows `/resources` for `User-agent: *`. "
        "This parks the richest per-act PDF collections found: Soissons "
        "02722 (3,571 PDFs over 2020–2026), Jouarre 77238 (258 PDFs, "
        "also scanned images), Faugères 07088 (56 session PDFs, native "
        "text), Berck-sur-Mer 62108, Castelmaurou 31117, Templemars, "
        "Méry-sur-Marne. The data.gouv API itself (metadata/discovery) "
        "is not disallowed and was used for the census.",
        "- **Martigues 13056** document server "
        "(arretes-deliberations.ville-martigues.fr): robots.txt is "
        "`User-agent: * / Disallow: /` — fully parked despite a public "
        "1,635-act index on datasud.fr.",
        "- **Chelles 77108** (ArcGIS Hub): FeatureServer answers "
        "499 'Token Required'; Hub downloads redirect off-host; Hub "
        "robots sets Crawl-delay 60.",
        "- **Scanned-image PDFs**: Jouarre and Castelmaurou publish "
        "télétransmission scans (native text = préfecture stamp only). "
        "The workspace tesseract has no `fra` traineddata, so these are "
        "OCR-deferred even where a route opens.",
        "- **Ville websites**: of ~20 mid-size ville homepages probed, "
        "most were unreachable or anti-bot walled from this egress "
        "(Valence 418, Chambéry/Caen/Angers homepages timing out; "
        "Montpellier's ODS host ProxyError). Annecy and Angers loaded "
        "but expose no actes listing from the homepage.",
        "",
        "All published parquets pass the world_municipal fail-closed "
        "gates (19-column schema; preamble + one row per Article where "
        "the act has articles, else one body row per document).",
    ]
    (DATA / "coverage_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readme = f"""# ipfs_france_municipal_laws

French municipal law (délibérations du conseil municipal — council
deliberations and decisions) normalized to the shared `world_municipal`
19-column schema used across the world-municipal-law program in
`endomorphosis/ipfs_datasets_py`
(`ipfs_datasets_py/processors/legal_scrapers/world_municipal/`).

**Status: SEED (pilot), {RETRIEVED}.** {len(pubs)} of 34,875 registered
communes (INSEE COG, millésime 2026) are represented, by a deterministic
16-document sample of the fully enumerated corpus — {total_rows} rows
in total. See `coverage_report.md` for the per-commune corpus size, the
sampling rule, and the surveyed-but-parked routes (most French
publication channels disallow bots in robots.txt; they are documented,
not worked around). This is not full coverage of any commune yet; the
harvester enumerates the published corpus completely, so scaling a
commune is a sampling-parameter change, not new code.

## Layout (Portugal precedent)

- `<Code INSEE>_html.parquet` — one file per commune; one row per
  Article where the act has articles, plus a preamble row, else one
  body row per document.
- `<code>_validation.json` — fail-closed gate report per parquet.
- `jurisdictions.jsonl` — the full INSEE COG registry (34,875 communes).
- `scrapers/` — the pilot harvester/registry builder that produced this
  seed (also in the repo under
  `legal_scrapers/world_municipal_campaigns/fr_pilot/`).

## Sources

- Besançon (25056, Doubs, Bourgogne-Franche-Comté): Grand Besançon
  affichage webservice at datasets.grandbesancon.fr — structured JSON
  index of council sessions and their délibérations, per-act PDFs on
  the same host; corpus enumerated: 754 délibérations (2024–2025).

`source_url` in every row points at the act's PDF on the publishing
body's own host. Acts are public legal texts published by the communes
themselves (publication des actes, communes ≥ 3,500 inhabitants).
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
    for name in ("fr_build.py", "build_registry.py"):
        uploads.append((scrapers_dir / name, f"scrapers/{name}"))

    for local, repo_path in uploads:
        if not local.exists():
            raise SystemExit(f"missing local file: {local}")
    for local, repo_path in uploads:
        if repo_path in existing and repo_path.endswith(("_html.parquet", "_validation.json")):
            print("already published, skipping", repo_path, flush=True)
            continue
        api.upload_file(path_or_fileobj=str(local), path_in_repo=repo_path,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"FR pilot seed: add {repo_path}")
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
                              jurisdiction_name=pubs[code]["name"], country="FR")
        grand += t.num_rows
        print(code, pubs[code]["name"], "remote rows", t.num_rows, "valid", not errs, errs)
        assert t.num_rows == pubs[code]["rows"] and not errs
    print("TOTAL remote rows:", grand, "== local total:", total_rows, grand == total_rows)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
