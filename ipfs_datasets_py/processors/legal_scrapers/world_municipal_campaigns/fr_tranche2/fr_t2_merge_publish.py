"""France tranche 2 — merge ALL Besançon checkpoints (tranche-1
2024–2026 délibérations + tranche-2 pre-2024 délibérations +
tranche-2 actes), validate with the fail-closed gates, publish.

Every row carries `document_type` (extra column after col. 19):
"délibération" for the council corpus (tranche-1 rows are tagged
at load — their checkpoints predate the column), the actes
service's own type ("arrêté"/"décision") for actes rows.

Publishes: supersedes 25056_html.parquet / 25056_validation.json
in place on endomorphosis/ipfs_france_municipal_laws, refreshes
coverage_report.md + README.md to the FINAL France state, adds the
tranche-2 scripts under scrapers/, remote-verifies by re-download.
jurisdictions.jsonl is NOT re-uploaded (unchanged).
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
import pyarrow as pa  # noqa: E402

T1 = HF / "fr_tranche1"
OUT = HF / "fr_tranche2"
DATA = OUT / "data"
DATA.mkdir(parents=True, exist_ok=True)
CODE = "25056"
REPO_ID = "endomorphosis/ipfs_france_municipal_laws"
RETRIEVED = "2026-10-14"
EXTRA = [("document_type", pa.string())]
info = B.REGISTRY[CODE]
name = info["jurisdiction_name"]


def load_records(paths, tag_dtype=None):
    """Latest record per doc_id across the given checkpoint files.

    Two-phase streaming (the naive all-in-memory load OOM-killed the
    first stage-1 attempt on this 7 GB box): phase A indexes the
    last occurrence of each doc_id (file order = precedence) while
    discarding row payloads; phase B re-reads and materializes only
    the winning records. Line-tolerant: a stage-1 merge can run
    while the OCR finisher is still appending to its checkpoint (a
    torn final line is skipped; that doc lands in the next
    supersede)."""
    import gc
    paths = [Path(p) for p in paths if Path(p).exists()]
    last = {}  # doc_id -> (file_idx, line_idx)
    for fi, p in enumerate(paths):
        with p.open(encoding="utf-8") as fh:
            for li, line in enumerate(fh):
                if not line.strip():
                    continue
                try:
                    did = json.loads(line)["doc_id"]
                except Exception:  # noqa: BLE001 — torn line
                    continue
                last[did] = (fi, li)
    want = {}
    for did, key in last.items():
        want.setdefault(key[0], {})[key[1]] = did
    recs = {}
    for fi, p in enumerate(paths):
        keep = want.get(fi, {})
        if not keep:
            continue
        with p.open(encoding="utf-8") as fh:
            for li, line in enumerate(fh):
                if li not in keep or not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if tag_dtype:
                    for row in r.get("rows", []):
                        row.setdefault("document_type", tag_dtype)
                recs[r["doc_id"]] = r
        gc.collect()
    return recs


def class_stats(recs, corpus_ids):
    meta = []
    for did in corpus_ids:
        r = recs.get(did)
        if r is None:
            meta.append({"doc_id": did, "status": "missing_checkpoint"})
        else:
            meta.append({k: v for k, v in r.items() if k != "rows"})
    return {
        "corpus_docs": len(corpus_ids),
        "docs_ok": sum(1 for m in meta if m.get("status") in ("ok", "ok_ocr")),
        "docs_ocr_recovered": sum(1 for m in meta if m.get("status") == "ok_ocr"),
        "docs_ocr_deferred": sum(1 for m in meta
                                 if m.get("status") in ("ocr_deferred_scanned_pdf",
                                                        "ocr_failed_still_deferred")),
        "docs_fetch_failed": sum(1 for m in meta if str(m.get("status", "")).startswith("fetch_failed")),
        "missing": sum(1 for m in meta if m.get("status") == "missing_checkpoint"),
        "attribution_name_in_text": sum(1 for m in meta if m.get("attribution") == "name_in_text"),
        "attribution_official_listing": sum(1 for m in meta if m.get("attribution") == "official_listing"),
        "_meta": meta,
    }


def merge():
    """Memory-bounded merge: one class at a time (the all-in-memory
    version OOM-killed twice on this 7 GB box). finalize semantics
    are preserved exactly — duplicate doc_ids suffixed in encounter
    order with cid recompute (ensure_unique_doc_ids), doc_order
    sequential across the whole file (assign_doc_order) — via shared
    streaming state; drop_empty runs BEFORE finalize (a no-op when
    no row is empty, as in every prior build, and it keeps doc_order
    gapless if it ever fires)."""
    import gc
    from collections import Counter

    # --- corpora + checkpoint paths per class ---
    t1_corpus = json.loads((T1 / "besancon_corpus.json").read_text(encoding="utf-8"))
    t1_ids = [d["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() for d in t1_corpus["docs"]]
    t1_paths = [T1 / "checkpoint_25056.jsonl"] + \
        [Path(p) for p in sorted(glob.glob(str(T1 / "checkpoint_25056_shard*.jsonl")))] + \
        [T1 / "checkpoint_25056_ocr.jsonl"]
    d_corpus = json.loads((OUT / "delib_pre2024_corpus.json").read_text(encoding="utf-8"))
    d_ids = [d["doc_id"] for d in d_corpus["docs"]]
    d_paths = [Path(p) for p in sorted(glob.glob(str(OUT / "checkpoint_delib_shard*.jsonl")))] + \
        [OUT / "checkpoint_delib_retry.jsonl", OUT / "checkpoint_delib_ocr.jsonl"]
    a_corpus = json.loads((OUT / "actes_corpus.json").read_text(encoding="utf-8"))
    a_ids = [d["acte_id"].lower() for d in a_corpus["docs"]]
    a_paths = [Path(p) for p in sorted(glob.glob(str(OUT / "checkpoint_acte_shard*.jsonl")))] + \
        [OUT / "checkpoint_acte_retry.jsonl", OUT / "checkpoint_acte_ocr.jsonl"]

    assert not (set(t1_ids) & set(d_ids)) and not (set(t1_ids) & set(a_ids)) \
        and not (set(d_ids) & set(a_ids)), "doc_id collision across classes"

    seen = {}
    counter = [0]
    rows_pre = [0]

    def finalize_stream(rows):
        out = []
        for row in rows:
            base = str(row.get("doc_id", ""))
            n = seen.get(base, 0) + 1
            seen[base] = n
            if n > 1:
                row["doc_id"] = f"{base}-{n}"
                if row.get("jurisdiction_id"):
                    row["cid"] = B.make_cid(str(row["jurisdiction_id"]), str(row["doc_id"]))
            row["doc_order"] = counter[0]
            counter[0] += 1
            out.append(row)
        return out

    stats, metas, tables = {}, {}, []
    for key, paths, ids, tag in (
            ("t1_delib", t1_paths, t1_ids, "délibération"),
            ("t2_delib", d_paths, d_ids, None),
            ("t2_actes", a_paths, a_ids, None)):
        recs = load_records(paths, tag_dtype=tag)
        st = class_stats(recs, ids)
        metas[key] = st.pop("_meta")
        stats[key] = st
        rows = []
        for r in recs.values():
            rows.extend(r.get("rows", []))
        del recs
        gc.collect()
        rows_pre[0] += len(rows)
        rows = finalize_stream(B.drop_empty_rows(rows))
        tables.append(B.rows_to_table(rows, extra_columns=EXTRA))
        del rows
        gc.collect()
        print(f"merge: {key} table built, cumulative rows: {counter[0]}", flush=True)
    table = pa.concat_tables(tables)
    del tables
    gc.collect()
    errs = B.validate_table(table, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    stats["rows_pre_finalize"] = rows_pre[0]
    stats["rows"] = table.num_rows
    stats["valid"] = not errs
    stats["errors"] = errs
    # per-class row counts from the final table
    dt = table.column("document_type").to_pylist()
    stats["rows_by_document_type"] = dict(Counter(dt))
    urls = table.column("source_url").to_pylist()
    t1_urls = {d["url"] for d in t1_corpus["docs"]}
    d_urls = {d["url"] for d in d_corpus["docs"]}
    a_urls = {d["url"] for d in a_corpus["docs"]}
    stats["rows_t1_docs"] = sum(1 for u in urls if u in t1_urls)
    stats["rows_t2_delib"] = sum(1 for u in urls if u in d_urls)
    stats["rows_t2_actes"] = sum(1 for u in urls if u in a_urls)
    (OUT / "besancon_t2_build_result.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "besancon_t2_doc_meta.json").write_text(
        json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    assert not errs and table.num_rows > 0, "gate failure — do not publish"
    assert stats["rows_t1_docs"] == 6998, f"tranche-1 rows changed: {stats['rows_t1_docs']} != 6998"
    B.write_html_parquet(DATA / B.FR.file_name(CODE), table)
    B.write_validation_report(DATA / f"{CODE}_validation.json",
                              B.validation_report(table, jurisdiction_id=CODE,
                                                  jurisdiction_name=name, country="FR"))
    t2 = B.read_html_parquet(DATA / B.FR.file_name(CODE))
    assert not B.validate_table(t2, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    print("local parquet written + reread valid:", table.num_rows, "rows")
    return stats


def build_docs(s):
    t1, t2, ac = s["t1_delib"], s["t2_delib"], s["t2_actes"]
    delib_docs = t1["corpus_docs"] + t2["corpus_docs"]
    delib_ok = t1["docs_ok"] + t2["docs_ok"]
    actes_ok = ac["docs_ok"]
    by = s["rows_by_document_type"]
    # Two-stage publish (ZA/AT precedent): stage 1 ships the native +
    # recovered corpus while the délibérations OCR lane is still
    # draining; stage 2 supersedes with the final state. Wording is
    # stage-aware so neither stage overclaims.
    ocr_pending = t2["docs_ocr_deferred"]
    if ocr_pending:
        besancon_head = (
            "## Published: Besançon (25056) — full corpus, OCR recovery in progress")
        besancon_note = (
            f"**Stage-1 state**: every enumerated doc is harvested "
            f"except {ocr_pending} scanned délibérations (2017–2019) "
            f"whose fra-OCR recovery is still running; the parquet is "
            f"superseded in place as they land. Actes are complete; "
            f"délibérations are complete for all natively-digital docs.")
    else:
        besancon_head = "## Published: Besançon (25056) — COMPLETE"
        besancon_note = (
            "**Final state**: every enumerated doc is harvested, "
            "except the individually-documented unrecoverable items "
            "counted below (OCR-failed scans and server-side 404s).")
    lines = [
        "# Coverage report — ipfs_france_municipal_laws",
        "",
        f"Generated {RETRIEVED} by the France municipal-law campaign "
        "(legal_scrapers world_municipal_campaigns/fr_pilot + fr_tranche1 "
        "+ fr_tranche2). **France is CLOSED** at this state: the only "
        "robots-allowed harvest channel found in three census passes is "
        "the Grand Besançon affichage portal, and it is now exhausted "
        "(see below). Everything else is robots-parked or unreachable "
        "from this egress, documented and not worked around. France "
        "reopens only if a holder's robots posture changes or another "
        "egress/arrangement is approved.",
        "",
        "Registry: INSEE Code Officiel Géographique (COG), millésime 2026 "
        "(au 01/01/2026) — **34,875 communes** (TYPECOM=COM; arrondissements "
        "municipaux and communes associées/déléguées excluded), 18 régions.",
        "",
        besancon_head,
        "",
        besancon_note,
        "",
        f"Besançon is covered at full enumerated corpus across **every "
        f"year and both act classes** the Ville publishes on the Grand "
        f"Besançon affichage webservices (own host, no robots.txt "
        f"restrictions on either host — data.grandbesancon.fr serves a "
        f"sitemap-only robots.txt, datasets.grandbesancon.fr none):",
        "",
        f"- **Délibérations du conseil municipal, 1989–2026**: "
        f"{delib_docs} docs enumerated on `besanconfr.php?method="
        f"getConseilsMunicipaux` (2024–2026: {t1['corpus_docs']}, tranche 1; "
        f"1989–2023: {t2['corpus_docs']}, tranche 2 — the webservice's "
        f"earliest year is 1989; 1988 returns no sessions), {delib_ok} "
        f"harvested ({t1['docs_ocr_recovered'] + t2['docs_ocr_recovered']} "
        f"via fra OCR), {t2['docs_ocr_deferred']} still OCR-deferred, "
        f"{t1['docs_fetch_failed'] + t2['docs_fetch_failed']} fetch-failed "
        f"→ **{by.get('délibération', 0)} rows**.",
        f"- **Arrêtés et décisions du maire, 2022–2026**: "
        f"{ac['corpus_docs']} actes enumerated on `actes.php?method="
        f"getActesVilleDeBesancon` (the electronic-publication service "
        f"starts 2022), {actes_ok} harvested "
        f"({ac['docs_ocr_recovered']} via fra OCR), "
        f"{ac['docs_ocr_deferred']} still OCR-deferred, "
        f"{ac['docs_fetch_failed']} fetch-failed → "
        f"**{by.get('arrêté', 0)} arrêté rows + {by.get('décision', 0)} "
        f"décision rows**.",
        "",
        f"Total: **{s['rows']} rows** in `25056_html.parquet`. The "
        "`document_type` column (extra column after col. 19, the "
        "schema's sanctioned extension pattern) distinguishes "
        "`délibération` / `arrêté` / `décision`. Doc-ids: délibérations "
        "keep the pilot scheme (PDF filename stem; 222 old-style stems "
        "that repeat across years carry a `-<YYYYMMDD>` session-date "
        "suffix); actes use the service's own acte id.",
        "",
        "| Code INSEE | Commune | Région | Route | Corpus (docs) | Harvested | Rows |",
        "|---|---|---|---|---|---|---|",
        f"| 25056 | Besançon | Bourgogne-Franche-Comté | Grand Besançon "
        f"affichage webservices (délibérations 1989–2026 + actes "
        f"2022–2026) | {delib_docs + ac['corpus_docs']} | "
        f"{delib_ok + actes_ok} | {s['rows']} |",
        "",
        "## The rest of France — parked / unreachable (unchanged, binding)",
        "",
        "- **Opendatasoft** (the dominant platform family): the standard "
        "ODS robots.txt disallows `/api/` for `User-agent: *` on every "
        "portal read in full (Rennes, Nantes, Bordeaux ×2, Toulouse, "
        "Strasbourg, Paris, Anglet, Blois ×2, CapAtlantique, CARENE, …) "
        "→ **PARKED**.",
        "- **data.gouv.fr static resources**: robots.txt disallows "
        "`/resources` for `User-agent: *` → ≥10,608 per-act PDFs "
        "**PARKED** (Soissons 3,571, Pirae 1,099, Jouarre 258, Berck "
        "160, Castelmaurou 116, …). The data.gouv API itself is "
        "robots-clean and was used for census/discovery metadata only.",
        "- **Martigues**: document server `Disallow: /` → PARKED. "
        "**Chelles** (ArcGIS Hub): FeatureServer token-walled (499) → "
        "PARKED.",
        "- **Montpellier (data.montpellier3m.fr)**: robots-allowed DKAN "
        "catalogue but no délibérations/actes corpus and egress-flaky "
        "→ nothing harvestable.",
        "- datacat.datalocale.fr, geo.brest-metropole.fr, datasud.fr, "
        "brest.fr, ccpro.fr: unreachable from this egress.",
        "- Population ceiling: only ~1,100–1,300 communes (≥3,500 hab.) "
        "must publish actes online at all; the tranche-1 census (469 "
        "data.gouv datasets + 24 full robots reads) found no second "
        "Besançon-class own-host affichage service among them.",
        "",
        "All published parquets pass the world_municipal fail-closed "
        "gates (19-column schema + `document_type`; preamble + one row "
        "per Article where the act has articles, else one body row per "
        "document; session compilations split per délibération).",
    ]
    (DATA / "coverage_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readme = f"""# ipfs_france_municipal_laws

French municipal law (délibérations du conseil municipal, arrêtés et
décisions du maire) normalized to the shared `world_municipal`
19-column schema (+ a `document_type` extension column) used across
the world-municipal-law program in `endomorphosis/ipfs_datasets_py`
(`ipfs_datasets_py/processors/legal_scrapers/world_municipal/`).

**Status: France CLOSED, {RETRIEVED}.** One commune is published —
Besançon (25056) — covering every délibération the Ville publishes
(1989–2026, {delib_docs} docs enumerated) and every arrêté /
décision on its electronic-publication service (2022–2026,
{ac['corpus_docs']} actes) → **{s['rows']} rows** at this stage
(see `coverage_report.md` for the per-class harvested counts and
any OCR recovery still in flight). The registry holds
34,875 communes (INSEE COG, millésime 2026); the tranche-1 census
established that every other French publication channel is
robots-parked or unreachable from this egress — documented in
`coverage_report.md`, not worked around. France reopens only if a
robots posture changes or another egress/arrangement is approved.

## Layout (Portugal precedent)

- `<Code INSEE>_html.parquet` — one file per commune; one row per
  Article where the act has articles, plus a preamble row, else one
  body row per document. `document_type` ∈ {{délibération, arrêté,
  décision}} distinguishes the act classes.
- `<code>_validation.json` — fail-closed gate report per parquet.
- `jurisdictions.jsonl` — the full INSEE COG registry (34,875 communes).
- `scrapers/` — the harvesters that produced this dataset (also in
  the repo under `legal_scrapers/world_municipal_campaigns/fr_pilot/`,
  `fr_tranche1/` and `fr_tranche2/`).

## Sources

- Besançon (25056, Doubs, Bourgogne-Franche-Comté): Grand Besançon
  affichage webservices at datasets.grandbesancon.fr —
  `besanconfr.php?method=getConseilsMunicipaux` (sessions →
  délibérations, per-act PDFs; full enumeration 1989–2026) and
  `actes.php?method=getActesVilleDeBesancon` (arrêtés et décisions,
  2022–2026). No robots.txt restrictions on the host.

`source_url` in every row points at the act's PDF on the publishing
body's own host. Acts are public legal texts published by the commune
itself (publication des actes, communes ≥ 3,500 inhabitants).
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
                        commit_message=f"FR tranche 2: {repo_path}")
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
    from collections import Counter
    print("remote rows by document_type:",
          dict(Counter(t.column("document_type").to_pylist())))
    remote = {f.rfilename for f in api.list_repo_tree(REPO_ID, repo_type="dataset", recursive=True)
              if getattr(f, "rfilename", None)}
    print("remote files:", sorted(remote))
    shutil.rmtree(tmp, ignore_errors=True)
    print("PUBLISH + VERIFY DONE")


if __name__ == "__main__":
    main()
