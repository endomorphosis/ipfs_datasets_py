> Historical. This report describes the tree from before the module boundary. The current map is `docs/legal/legal_corpus_module_map.md`.

# legal_scrapers — per-lane manifest

Generated 2026-10-30T10:39:15.790142-07:00. 407 files, 3228.6 KB. Machine-readable: `manifest.json`.

`ipfs_datasets_py` dependency: *direct* = imports the package; *transitive* = imports a local module that does; *mentioned* = referenced in docs/strings only; *none detected* = no import.

| Lane | Files | Bytes |
|---|---:|---:|
| docs | 11 | 180707 |
| deepeners | 20 | 132261 |
| normalizer | 42 | 626024 |
| probes-and-archive-helpers | 23 | 290196 |
| countries | 187 | 960785 |
| shared-libs | 11 | 196694 |
| municipal | 63 | 835352 |
| packaging-upload | 50 | 84043 |

## Lane: docs (11 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `AFRICA_MENA_BATCH2_STATUS.md` | Africa & MENA Batch 2 status | `n/a (documentation)` | n/a |
| `AFRICA_MENA_PROGRESS.md` | Africa + Middle East lane progress (updated 2026-10-10 16:05 PT) | `n/a (documentation)` | n/a |
| `MANIFEST.md` | legal_scrapers — per-lane manifest | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `MUNICIPAL_HANDOFF.md` | Municipal handoff spec (Municipal Laws Scraper -> WS-1 normalizer) | `n/a (documentation)` | n/a |
| `NA_NAMIBLII_STATUS.md` | NA NamibLII archive pack status (resume-safe) | `n/a (documentation)` | n/a |
| `README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `STATUS_asia_americas_europe.md` | STATUS — Asia/Pacific + Americas/Caribbean + Europe stubs + big systems (executor lane) | `n/a (documentation)` | n/a |
| `STATUS_asia_americas_europe_b2.md` | STATUS b2 — Asia/Americas/Europe executor (Batch 2 from CoS) | `n/a (documentation)` | n/a |
| `WORLD_COVERAGE_AUDIT.md` | WORLD COVERAGE AUDIT | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `partial_resume_status.md` | Partial resume status — legal corpus scrapers | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `world_scrape_status.md` | World scrape status | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |

## Lane: deepeners (20 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `IT_DEEPEN_STATUS.md` | Italy Normattiva deepen — 2026-09-04 14:37 PT | `n/a (documentation)` | n/a |
| `RESTORE_PACK_DEEPEN_STATUS.md` | Restore + packaging + deepen — 2026-09-04 12:33 PT | `n/a (documentation)` | n/a |
| `na_namiblii_work/hub_base_head_20261027/scrapers/pdf_extract_lib.py` | PDF text extraction helpers mirroring ipfs_datasets_py IntegratedPDFProcessor. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `ocr_pdf_pass_results.md` | OCR / PDF deepen pass results | `n/a (documentation)` | n/a |
| `run_cm_deepen4.sh` | (no docstring; inferred from filename) | `bash run_cm_deepen4.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_it_deepen.sh` | (no docstring; inferred from filename) | `bash run_it_deepen.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_it_deepen_api.sh` | (no docstring; inferred from filename) | `bash run_it_deepen_api.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_reprocess_priority.sh` | (no docstring; inferred from filename) | `bash run_reprocess_priority.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/cy_extract_articles.py` | Cyprus: honest article/section extraction from GPO gazette texts. | `python scrapers/cy_extract_articles.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/deepen_it_articles.py` | Italy deepen: fill thin bodies via dettaglio-atto + honest Art. articleization. | `python scrapers/deepen_it_articles.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/deepen_it_idarticolo.py` | Italy deepen: Normattiva dettaglio-atto idArticolo walk for multi-article acts. | `python scrapers/deepen_it_idarticolo.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/deepen_la_ocr.py` | Laos deepen: quarantine site-chrome/annex junk; fetch gazette PDFs with OCR. | `python scrapers/deepen_la_ocr.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/deepen_md_reprocess.py` | Re-fetch Moldova legis.md downloadpdf instruments with proper PDF text extract. | `python scrapers/deepen_md_reprocess.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/deepen_mz_ocr.py` | Re-OCR Mozambique image-only / Pandora-watermark PDFs; expand Parlamento harvest. | `python scrapers/deepen_mz_ocr.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/deepen_sv_pdf.py` | El Salvador deepen: replace 1847 garbage Diario scans with official Asamblea / Diario | `python scrapers/deepen_sv_pdf.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/ocr_deepen_pass.py` | Stronger OCR + honest-split deepen for SV/TN/ET/FJ/LA/LK. | `python scrapers/ocr_deepen_pass.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/pdf_extract_lib.py` | PDF text extraction helpers mirroring ipfs_datasets_py IntegratedPDFProcessor. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/reprocess_iq_ir_articles.py` | Reprocess Iraq/Iran instruments: RTL-normalize, honest article splits, optional OCR. | `python scrapers/reprocess_iq_ir_articles.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/reprocess_pdf_articles.py` | Re-extract PDF text (IntegratedPDFProcessor-style) and honest article splits | `python scrapers/reprocess_pdf_articles.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `tmp_la_ocr.py` | (no docstring; inferred from filename) | `python tmp_la_ocr.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |

## Lane: normalizer (42 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `NORMALIZER_STATUS.md` | NORMALIZER_STATUS (WS-1 lane) — updated 2026-10-10 15:50 PT | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `SCHEMA.md` | World-laws dataset schemas (pinned) | `n/a (documentation)` | n/a |
| `local_package.py` | Local-only packager (no huggingface_hub). Mirrors world_package.package(). | `python local_package.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/NORMALIZER_VERSION.md` | Normalizer snapshot | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `normalizers/country_laws_ir/__init__.py` | Country-law CID-keyed sparse GraphRAG packager (SkillCenter / publicus-ir family). | `python normalizers/country_laws_ir/__init__.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/__main__.py` | python -m country_laws_ir {build,query,batch,catalog,normalize,package-raw} | `python normalizers/country_laws_ir/__main__.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/auth.py` | Hugging Face auth helpers. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/bm25.py` | Okapi BM25 (k1=1.2, b=0.75, title_weight=5, body_weight=1) + posting shards. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/build.py` | End-to-end build: normalize → incremental vectors → BM25 → graph → package. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `normalizers/country_laws_ir/catalog.py` | Catalog of endomorphosis/ipfs_*_laws corpora. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `normalizers/country_laws_ir/cidutil.py` | CIDv1 (raw + sha2-256) helpers. Produces bafkrei... identifiers. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/citations.py` | Official and Bluebook citations for country-law corpus rows. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/coverage.py` | Compare endomorphosis raw sources against justicedao GraphRAG releases. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/duckdb_store.py` | DuckDB views over country-laws sparse GraphRAG parquet shards. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/graph.py` | Property graph: entry nodes, facet nodes, BM25_NEIGHBOR_OF k=8, ARTICLE_OF, ELI. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/incremental.py` | CID-keyed incremental GraphRAG rebuild for country-laws IR. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `normalizers/country_laws_ir/mem.py` | Process / host memory watchdog for large IR builds (DO OOM lesson). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/normalize.py` | Normalize endomorphosis/ipfs_*_laws into a CID-keyed canonical corpus. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `normalizers/country_laws_ir/normalize_loop.py` | Improve the row normalizer, then let that script normalize every row. | `library (import)` | direct import of ipfs_datasets_py |
| `normalizers/country_laws_ir/package.py` | Write country-laws-ir-graphrag/v1 thin-client layout (SkillCenter / publicus-ir family). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/parquet_io.py` | ZSTD parquet shard writer matching skillcenter-huggingface-release/v3. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/profiles.py` | Per-language legal heading lexicons for country-law structure extraction. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/query.py` | Thin-client query for country-laws IR releases (local dir). | `python normalizers/country_laws_ir/query.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/raw_package.py` | Incrementally package raw collector instruments into laws/articles parquet. | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `normalizers/country_laws_ir/reconstruct.py` | Reconstruct empty parent law bodies from article children. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/schema.py` | Fail-closed schema mapping for endomorphosis/ipfs_*_laws parquet tables. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/sparse.py` | Country-law sparse GraphRAG export through the shared HF GraphRAG builders. | `library (import)` | direct import of ipfs_datasets_py |
| `normalizers/country_laws_ir/spill.py` | Disk-spill helpers for large country IR builds (DuckDB + parquet). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/structure.py` | Extract legal hierarchy from country-law text (Oregon-style, multilingual). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/tokenize.py` | FTS5 unicode61 remove_diacritics=2-style tokenizer. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir/upload.py` | Publish a local country-laws-ir release to the JusticeDAO Hugging Face org. | `library (import)` | direct import of ipfs_datasets_py |
| `normalizers/country_laws_ir/vectors.py` | thenlper/gte-small 384-d embeddings + centroid-sorted shards. | `library (import)` | direct import of ipfs_datasets_py |
| `normalizers/country_laws_ir/verify.py` | Admission verifiers for country-law normalization, before GraphRAG. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir_scripts/build_country_laws_ir.py` | CLI: build a country-laws IR release (local; does not upload). | `python normalizers/country_laws_ir_scripts/build_country_laws_ir.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir_scripts/generate_country_laws_ir.py` | Generation entrypoint copied into Hub dataset repos. | `python normalizers/country_laws_ir_scripts/generate_country_laws_ir.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir_scripts/normalize_country_laws.py` | Normalize a country-law source into a CID-keyed corpus report (no GraphRAG, no upload). | `python normalizers/country_laws_ir_scripts/normalize_country_laws.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir_scripts/query_country_laws_hf.py` | (no docstring; inferred from filename) | `python normalizers/country_laws_ir_scripts/query_country_laws_hf.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/country_laws_ir_scripts/query_country_laws_ir.py` | CLI wrapper for country_laws_ir.query. | `python normalizers/country_laws_ir_scripts/query_country_laws_ir.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/pack_raw_for_ir.py` | Merge a (possibly sharded) raw ``endomorphosis/ipfs_<slug>_laws`` repo into ONE pinned-schema local pack. | `python normalizers/pack_raw_for_ir.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `normalizers/schema.py` | Pinned Arrow schemas + cast/validate helpers for the world-laws datasets. | `python normalizers/schema.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `schema.py` | Pinned Arrow schemas + cast/validate helpers for the world-laws datasets. | `python schema.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `world_package.py` | Package instruments -> parquet + README and upload ipfs_<slug>_laws datasets. | `python world_package.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |

## Lane: probes-and-archive-helpers (23 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `README_COMMON_CRAWL_HELPER.md` | common_crawl_helper.py — ranged Common Crawl harvest for official-gazette domains | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `check_it.py` | (no docstring; inferred from filename) | `python check_it.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `common_crawl_helper.py` | Shared Common Crawl helper: S3 cluster.idx -> CDXJ block -> ranged WARC fetch. | `python common_crawl_helper.py` | direct import of ipfs_datasets_py |
| `data_bg/scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `data_cy/scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `data_it/scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `data_ro/scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `data_si/scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `na_namiblii_work/hub_base_head_20261027/scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/archive_fallbacks.py` | Public Wayback CDX + Common Crawl CDX/WARC fetch (ipfs_datasets_py fallback intent). | `library (import)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/probe_it_api.py` | Probe official Normattiva dettaglio-atto / caricaAKN for multi-article structure. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_art_heads.py` | several patterns | `python scrapers/probe_it_art_heads.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_bodies.py` | (no docstring; inferred from filename) | `python scrapers/probe_it_bodies.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_formato_o.py` | Legge with many articles - Codice civile? or known multi-art legge | `python scrapers/probe_it_formato_o.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_html_arts.py` | (no docstring; inferred from filename) | `python scrapers/probe_it_html_arts.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_idart_small.py` | (no docstring; inferred from filename) | `python scrapers/probe_it_idart_small.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_idarticolo.py` | Multi-article law already known locally | `python scrapers/probe_it_idarticolo.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_multi_endpoint.py` | also a classic multi-article law: Legge 241/1990 | `python scrapers/probe_it_multi_endpoint.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_multiart.py` | Law that already has 8 article docs | `python scrapers/probe_it_multiart.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/probe_it_split_potential.py` | Broader IT-specific pattern: line-start Art. N optionally with title in parens | `python scrapers/probe_it_split_potential.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/run_cc_probe_r4.py` | Small CC CDX probes for BG/CY — index only, no WARC. | `python scrapers/run_cc_probe_r4.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/sample_it_instruments.py` | (no docstring; inferred from filename) | `python scrapers/sample_it_instruments.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |

## Lane: countries (187 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `al_alfresco_tip26b.py` | (no docstring; inferred from filename) | `python al_alfresco_tip26b.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `al_close_tip26b.py` | (no docstring; inferred from filename) | `python al_close_tip26b.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `az_cdx_extra_tip26f.py` | (no docstring; inferred from filename) | `python az_cdx_extra_tip26f.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `az_live_gap_tip24o.py` | (no docstring; inferred from filename) | `python az_live_gap_tip24o.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `az_live_gap_tip26f.py` | (no docstring; inferred from filename) | `python az_live_gap_tip26f.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `bo_live_cdx_miss_tip26m.py` | (no docstring; inferred from filename) | `python bo_live_cdx_miss_tip26m.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `bo_live_failures_tip26a.py` | (no docstring; inferred from filename) | `python bo_live_failures_tip26a.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `bo_live_failures_tip26b.py` | (no docstring; inferred from filename) | `python bo_live_failures_tip26b.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_bg/MANIFEST.md` | ipfs_bulgaria_laws manifest | `n/a (documentation)` | n/a |
| `data_bg/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | n/a |
| `data_bg/scrapers/collect_bg.py` | Bulgaria: State Gazette (dv.parliament.bg) RSS + materiali.faces issue HTML. | `python data_bg/scrapers/collect_bg.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_cy/MANIFEST.md` | ipfs_cyprus_laws manifest | `n/a (documentation)` | n/a |
| `data_cy/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | n/a |
| `data_cy/scrapers/collect_cy.py` | Cyprus: official GPO gazette (mof.gov.cy). legislation.gov.cy does not resolve. Not cylaw.org. | `python data_cy/scrapers/collect_cy.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_it/MANIFEST.md` | ipfs_italy_laws manifest | `n/a (documentation)` | n/a |
| `data_it/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | n/a |
| `data_it/scrapers/collect_it.py` | Italy: Normattiva OpenData ricerca/avanzata + dettaglio-atto (official BFF). | `python data_it/scrapers/collect_it.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_ro/MANIFEST.md` | ipfs_romania_laws manifest | `n/a (documentation)` | n/a |
| `data_ro/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | n/a |
| `data_ro/scrapers/collect_ro.py` | Romania: official Portal Legislativ SOAP API (http FreeWebService.svc/SOAP). | `python data_ro/scrapers/collect_ro.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_si/MANIFEST.md` | ipfs_slovenia_laws manifest | `n/a (documentation)` | n/a |
| `data_si/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | n/a |
| `data_si/scrapers/collect_si.py` | Slovenia: Uradni list RS official issue TOCs + act HTML (pisrs API is token-gated). | `python data_si/scrapers/collect_si.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `fix_iceland_gap.py` | (no docstring; inferred from filename) | `python fix_iceland_gap.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `ir_media_recent_tip25q.py` | (no docstring; inferred from filename) | `python ir_media_recent_tip25q.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `ir_media_recent_tip26b.py` | (no docstring; inferred from filename) | `python ir_media_recent_tip26b.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `ir_media_recent_tip26n.py` | (no docstring; inferred from filename) | `python ir_media_recent_tip26n.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `manifest.json` | (no docstring; inferred from filename) | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `mw_akn_miss_tip25m.py` | (no docstring; inferred from filename) | `python mw_akn_miss_tip25m.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `mw_akn_miss_tip26b.py` | (no docstring; inferred from filename) | `python mw_akn_miss_tip26b.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `mw_akn_miss_tip26n.py` | (no docstring; inferred from filename) | `python mw_akn_miss_tip26n.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `mw_extra_akn_tip25p.py` | (no docstring; inferred from filename) | `python mw_extra_akn_tip25p.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `mw_extra_akn_tip26b.py` | (no docstring; inferred from filename) | `python mw_extra_akn_tip26b.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `mw_extra_akn_tip26m.py` | (no docstring; inferred from filename) | `python mw_extra_akn_tip26m.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `na_namiblii_work/build.py` | (no docstring; inferred from filename) | `python na_namiblii_work/build.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `na_namiblii_work/fetch.py` | NA NamibLII archive fetcher: Wayback id_ snapshots (<=1 req/s, sequential, backoff), archived source.pdf fallback, | `python na_namiblii_work/fetch.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `na_namiblii_work/hub_base/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `na_namiblii_work/hub_base_head_20261027/MANIFEST.md` | ipfs_namibia_laws manifest | `n/a (documentation)` | n/a |
| `na_namiblii_work/hub_base_head_20261027/README.md` | (no docstring; inferred from filename) | `n/a (documentation)` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `na_namiblii_work/hub_base_head_20261027/scrapers/collect_na.py` | Namibia: official Acts / Bills / Gazette PDFs via *.gov.na + parliament.na. | `python na_namiblii_work/hub_base_head_20261027/scrapers/collect_na.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `na_namiblii_work/runner.sh` | nohup runner: fetch.py waits for >=30G disk / >=4.5G mem before every request (recheck 3 min); resumes from results.jsonl. | `bash na_namiblii_work/runner.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `rebuild_20261027/build_baseline_from_hub.py` | Same TSV format as countries-laws-verifier/tip31zm_save_baseline.py, built from Hub-downloaded staging_<cc>. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `rebuild_20261027/rebuild_from_hub.py` | Read-only against the Hub. Rebuild staging_<cc> for the 13 CCs. No uploads/deletes. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `rebuild_20261027/write_handoffs.py` | (no docstring; inferred from filename) | `python rebuild_20261027/write_handoffs.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_al.sh` | (no docstring; inferred from filename) | `bash run_al.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_al_create.sh` | (no docstring; inferred from filename) | `bash run_al_create.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ao.sh` | Angola deepen: digital PDFs + OCR of official scans when ALLOW_OCR=1. | `bash run_ao.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_az.sh` | (no docstring; inferred from filename) | `bash run_az.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ba.sh` | (no docstring; inferred from filename) | `bash run_ba.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_bg.sh` | (no docstring; inferred from filename) | `bash run_bg.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_bg2.sh` | (no docstring; inferred from filename) | `bash run_bg2.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_bg3.sh` | (no docstring; inferred from filename) | `bash run_bg3.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_bg4.sh` | (no docstring; inferred from filename) | `bash run_bg4.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_bg5.sh` | (no docstring; inferred from filename) | `bash run_bg5.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_bo.sh` | (no docstring; inferred from filename) | `bash run_bo.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_by.sh` | (no docstring; inferred from filename) | `bash run_by.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_cu.sh` | (no docstring; inferred from filename) | `bash run_cu.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_cy.sh` | (no docstring; inferred from filename) | `bash run_cy.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_cy2.sh` | (no docstring; inferred from filename) | `bash run_cy2.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_cy4.sh` | (no docstring; inferred from filename) | `bash run_cy4.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_cy5.sh` | (no docstring; inferred from filename) | `bash run_cy5.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_cy_upload.sh` | (no docstring; inferred from filename) | `bash run_cy_upload.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_do.sh` | (no docstring; inferred from filename) | `bash run_do.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_dz.sh` | (no docstring; inferred from filename) | `bash run_dz.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_et.sh` | (no docstring; inferred from filename) | `bash run_et.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_fj.sh` | (no docstring; inferred from filename) | `bash run_fj.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ge.sh` | (no docstring; inferred from filename) | `bash run_ge.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ge_create.sh` | (no docstring; inferred from filename) | `bash run_ge_create.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_gt.sh` | (no docstring; inferred from filename) | `bash run_gt.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_it2.sh` | (no docstring; inferred from filename) | `bash run_it2.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_it3.sh` | (no docstring; inferred from filename) | `bash run_it3.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_it4.sh` | (no docstring; inferred from filename) | `bash run_it4.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_it5.sh` | (no docstring; inferred from filename) | `bash run_it5.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_jm.sh` | (no docstring; inferred from filename) | `bash run_jm.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_kh.sh` | (no docstring; inferred from filename) | `bash run_kh.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_la.sh` | (no docstring; inferred from filename) | `bash run_la.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_md.sh` | (no docstring; inferred from filename) | `bash run_md.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_md_create.sh` | (no docstring; inferred from filename) | `bash run_md_create.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_me.sh` | (no docstring; inferred from filename) | `bash run_me.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_mk.sh` | (no docstring; inferred from filename) | `bash run_mk.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_mn.sh` | (no docstring; inferred from filename) | `bash run_mn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_mz.sh` | (no docstring; inferred from filename) | `bash run_mz.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_na.sh` | (no docstring; inferred from filename) | `bash run_na.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ni.sh` | (no docstring; inferred from filename) | `bash run_ni.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_np.sh` | (no docstring; inferred from filename) | `bash run_np.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pa.sh` | (no docstring; inferred from filename) | `bash run_pa.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ro.sh` | (no docstring; inferred from filename) | `bash run_ro.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ro2.sh` | (no docstring; inferred from filename) | `bash run_ro2.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ro3.sh` | (no docstring; inferred from filename) | `bash run_ro3.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ro4.sh` | (no docstring; inferred from filename) | `bash run_ro4.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ro5.sh` | (no docstring; inferred from filename) | `bash run_ro5.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ro6.sh` | (no docstring; inferred from filename) | `bash run_ro6.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_rs.sh` | (no docstring; inferred from filename) | `bash run_rs.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_rs_create.sh` | (no docstring; inferred from filename) | `bash run_rs_create.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_rw.sh` | (no docstring; inferred from filename) | `bash run_rw.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_si.sh` | (no docstring; inferred from filename) | `bash run_si.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_si2.sh` | (no docstring; inferred from filename) | `bash run_si2.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_si3.sh` | Resume remaining from existing 8015 catalog first (no rediscover) | `bash run_si3.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_si4.sh` | (no docstring; inferred from filename) | `bash run_si4.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_sn.sh` | (no docstring; inferred from filename) | `bash run_sn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_sn_pilot.sh` | (no docstring; inferred from filename) | `bash run_sn_pilot.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_sv.sh` | (no docstring; inferred from filename) | `bash run_sv.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_tn.sh` | (no docstring; inferred from filename) | `bash run_tn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_tn2.sh` | (no docstring; inferred from filename) | `bash run_tn2.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_tz.sh` | (no docstring; inferred from filename) | `bash run_tz.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_ug.sh` | (no docstring; inferred from filename) | `bash run_ug.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_uz.sh` | (no docstring; inferred from filename) | `bash run_uz.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_verify.sh` | (no docstring; inferred from filename) | `bash run_verify.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_xk.sh` | (no docstring; inferred from filename) | `bash run_xk.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_zw.sh` | (no docstring; inferred from filename) | `bash run_zw.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_af.py` | Afghanistan: MoJ Official Gazette PDFs + laws.moj.gov.af (Dari/fa primary). | `python scrapers/collect_af.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_al.py` | Albania: Official Fletorja Zyrtare PDFs from QPZ (predecessor of QBZ) + QBZ Alfresco content via Wayback. | `python scrapers/collect_al.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_am.py` | Armenia: official ARLIS (Pashtonakan teghekagir / Ministry of Justice). | `python scrapers/collect_am.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ao.py` | Angola: Diário da República / official legislation PDFs. | `python scrapers/collect_ao.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_az.py` | Azerbaijan: e-qanun.az downloadDetailPdf (non-SPA PDF path) + Wayback + ID probe. | `python scrapers/collect_az.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ba.py` | Bosnia: Sluzbeni list BiH PdfDownload gazette issues (live + Wayback of official URLs). | `python scrapers/collect_ba.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_bg.py` | Bulgaria: State Gazette via Wayback of official URLs (live TLS fails). | `python scrapers/collect_bg.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_blocked_archives.py` | Collect blocked EU gazettes via archive fallbacks (Wayback / Common Crawl / archive.is / HTTP). | `python scrapers/collect_blocked_archives.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_bn.py` | Brunei: AGC Laws of Brunei ACT_PDF (agc.gov.bn/AGC Images/LAWS). | `python scrapers/collect_bn.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_bo.py` | Bolivia: Gaceta Oficial de Bolivia (HTTP; HTTPS TLS often fails) + Wayback. | `python scrapers/collect_bo.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_bw.py` | Botswana: official Acts / Bills / Gazette / SI PDFs from government portals. | `python scrapers/collect_bw.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_by.py` | Belarus: pravo.by official normative documents / codes. | `python scrapers/collect_by.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_cm.py` | Cameroon: official acts from Présidence (prc.cm) + Lois et Règlements SPM (spm.gov.cm). | `python scrapers/collect_cm.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_cu.py` | Cuba: Gaceta Oficial (gacetaoficial.gob.cu) PDF issues + Wayback. | `python scrapers/collect_cu.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_cy.py` | Cyprus: official GPO gazette (mof.gov.cy). PDF body extraction. Not cylaw.org. | `python scrapers/collect_cy.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `scrapers/collect_do.py` | Dominican Republic: Consultoría Jurídica API + Congreso Biblioteca gacetas/leyes. | `python scrapers/collect_do.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_documents_gov_lk.py` | Official Sri Lanka Acts from documents.gov.lk (alias entrypoint). | `python scrapers/collect_documents_gov_lk.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_dz.py` | Algeria: Journal Officiel (JORADP / SGG) official PDF issues over HTTP. | `python scrapers/collect_dz.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ec.py` | Ecuador: official gob.ec regulaciones API + Registro Oficial PDFs. | `python scrapers/collect_ec.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_et.py` | Ethiopia: Federal Negarit Gazette / MoJ proclamation & regulation PDFs. | `python scrapers/collect_et.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_fj.py` | Fiji: laws.gov.fj LawsAsMade PDF downloads + Wayback of official URLs. | `python scrapers/collect_fj.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ge.py` | Georgia: matsne.gov.ge (Wayback PDFs) + parliament.ge/_special/kan/files (CDX PDF snapshots). | `python scrapers/collect_ge.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_gh.py` | Ghana: Constitution + Acts of Parliament from official hosts only. | `python scrapers/collect_gh.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_gt.py` | Guatemala: Congreso de la República (congreso.gob.gt) official PDF acuerdos/leyes + Wayback. | `python scrapers/collect_gt.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_hn.py` | Honduras: Tribunal Superior de Cuentas La Gaceta / leyes PDFs (tsc.gob.hn/web/leyes). | `python scrapers/collect_hn.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_iq.py` | Iraq: Ministry of Justice uploaded gazette/law PDFs (moj.gov.iq/uploaded). | `python scrapers/collect_iq.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ir.py` | Iran: National System of Laws / DOTIC (dotic.ir) official PDFs + Wayback. | `python scrapers/collect_ir.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_is.py` | Iceland: Alþingi Lagasafn consolidated HTML laws (althingi.is). | `python scrapers/collect_is.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_it.py` | Italy: Normattiva OpenData ricerca/avanzata + dettaglio-atto (official BFF). | `python scrapers/collect_it.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_jm.py` | Jamaica: Laws of Jamaica official PDFs (MOJ laws/ + laws.moj.gov.jm). | `python scrapers/collect_jm.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_kh.py` | Cambodia: Ministry of Justice (moj.gov.kh) official document PDFs + Wayback. | `python scrapers/collect_kh.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_la.py` | Laos: Lao Official Gazette (laoofficialgazette.gov.la) kcfinder PDF uploads + Wayback. | `python scrapers/collect_la.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_lb.py` | Lebanon: Official Gazette (jo.pcm.gov.lb) PDFs + pcm.gov.lb DynamicFile docs. | `python scrapers/collect_lb.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_lk.py` | Sri Lanka: Constitution + Acts from official government hosts. | `python scrapers/collect_lk.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_md.py` | Moldova legislation collector. | `python scrapers/collect_md.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_me.py` | Montenegro: Sluzbeni list Crne Gore (sluzbenilist.me) + Wayback of official URLs. | `python scrapers/collect_me.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_mg.py` | Stub collector metadata for mg (CC S3 CDXJ ingest primary). | `python scrapers/collect_mg.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_mk.py` | North Macedonia: Sluzben vesnik (slvesnik.com.mk) PDFs. Live TLS often fails; HTTP/Wayback. | `python scrapers/collect_mk.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_mn.py` | Mongolia: legalinfo.mn official legal acts (HTML detail pages + CDX PDFs). | `python scrapers/collect_mn.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_mw.py` | Stub collector metadata for mw (CC S3 CDXJ ingest primary). | `python scrapers/collect_mw.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_mz.py` | Mozambique: Boletim da República / official legislation PDFs. | `python scrapers/collect_mz.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_na.py` | Namibia: official Bills / Acts / Gazette instruments from Parliament + BoN. | `python scrapers/collect_na.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ni.py` | Nicaragua: Asamblea Nacional legislación / Gaceta (legislacion.asamblea.gob.ni) PDFs + Wayback. | `python scrapers/collect_ni.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_np.py` | Nepal: lawcommission.gov.np / Nepal Law Commission official acts (HTML/PDF). | `python scrapers/collect_np.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_pa.py` | Panama: Gaceta Oficial (gacetaoficial.gob.pa) PDFs via live/Wayback. | `python scrapers/collect_pa.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_pg.py` | Papua New Guinea: Parliament Acts PDFs (parliament.gov.pg/uploads/acts). | `python scrapers/collect_pg.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_py.py` | Paraguay: BACN leyes HTML (.entry-content full text; descarga PDFs are CF HTML shells). | `python scrapers/collect_py.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_remaining.py` | Best-effort remaining EU gazettes: HR SI RO HU PT GR BG CY HU. | `python scrapers/collect_remaining.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ro.py` | Romania: official Portal Legislativ SOAP API (http FreeWebService.svc/SOAP). | `python scrapers/collect_ro.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_rs.py` | Serbia: Constitution + закони from Pravno-informacioni sistem / Službeni glasnik. | `python scrapers/collect_rs.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_rw.py` | Rwanda: Official Gazette PDFs from minijust.gov.rw file list. | `python scrapers/collect_rw.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_si.py` | Slovenia: Uradni list RS official issue TOCs + act HTML (pisrs API is token-gated). | `python scrapers/collect_si.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_sn.py` | Senegal: Journal Officiel — jo.gouv.sn (primary, live+Wayback) + archives.sn official JO PDFs. | `python scrapers/collect_sn.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ss.py` | South Sudan: MoJCA laws PDFs (mojca.gov.ss) via CDX/Wayback + live list pages. | `python scrapers/collect_ss.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_sv.py` | El Salvador: Asamblea Legislativa decree PDFs + Diario Oficial API gazettes. | `python scrapers/collect_sv.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_tn.py` | Tunisia: Journal Officiel (IORT / JORT). | `python scrapers/collect_tn.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_tt.py` | Trinidad and Tobago: Parliament Acts PDFs + laws.gov.tt Digital Legislative Library PDFs. | `python scrapers/collect_tt.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_tz.py` | Tanzania: OAG MIS portal acts (acts-ajax catalog + /portal/acts/{id}/download PDFs). | `python scrapers/collect_tz.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ug.py` | Uganda: Parliament of Uganda official act PDFs. | `python scrapers/collect_ug.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_uz.py` | Uzbekistan: lex.uz official legislation HTML documents. | `python scrapers/collect_uz.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_ve.py` | Venezuela: Gaceta Oficial (gacetaoficial.gob.ve/storage) PDFs + Wayback. | `python scrapers/collect_ve.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_xk.py` | Kosovo: Gazeta Zyrtare (gzk.rks-gov.net) official act PDFs via ASP.NET download. | `python scrapers/collect_xk.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_zm.py` | Stub collector metadata for zm (CC S3 CDXJ ingest primary). | `python scrapers/collect_zm.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collect_zw.py` | Zimbabwe: Parliament of Zimbabwe official Act PDFs (parlzim.gov.zw). | `python scrapers/collect_zw.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_ao_cc_live.py` | Live-ingest AO PDFs discovered via Common Crawl URL list. | `python scrapers/ingest_ao_cc_live.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_ao_cc_warc.py` | Ingest Angola official PDFs from Common Crawl WARC byte-ranges. | `python scrapers/ingest_ao_cc_warc.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_do_getdocument.py` | Ingest consultoria.gov.do Documents/GetDocument PDFs discovered via Wayback CDX. | `python scrapers/ingest_do_getdocument.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_et_hopr.py` | Ingest hopr.gov.et proclamation/regulation PDFs from Wayback CDX list. | `python scrapers/ingest_et_hopr.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_gh_cc_warc.py` | Ingest Ghana Act PDFs from Common Crawl WARC byte-ranges. | `python scrapers/ingest_gh_cc_warc.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_ir_cc_warc.py` | Ingest Iran DOTIC laws from Common Crawl WARC byte-ranges. | `python scrapers/ingest_ir_cc_warc.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/ingest_thin_cc_live.py` | Live-ingest official PDFs discovered via S3 CC harvest (*_cc_urls.jsonl). | `python scrapers/ingest_thin_cc_live.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers_collect_remaining.py` | Best-effort remaining EU gazettes: HR SI RO HU PT GR BG CY HU. | `python scrapers_collect_remaining.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `tmp_fj_rights.py` | (no docstring; inferred from filename) | `python tmp_fj_rights.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `tmp_fj_struct.py` | (no docstring; inferred from filename) | `python tmp_fj_struct.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `tmp_fj_struct2.py` | (no docstring; inferred from filename) | `python tmp_fj_struct2.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `tmp_sv_cdx3.py` | (no docstring; inferred from filename) | `python tmp_sv_cdx3.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `world_gap_scan.py` | (no docstring; inferred from filename) | `python world_gap_scan.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |

## Lane: shared-libs (11 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_bg/scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_cy/scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_it/scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_ro/scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `data_si/scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `na_namiblii_work/hub_base_head_20261027/scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `na_namiblii_work/hub_base_head_20261027/scrapers/world_lib.py` | Shared helpers for new-country official gazette collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/collector.py` | Collect current Swiss federal classified compilation (SR) from Fedlex. | `python scrapers/collector.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/common.py` | Shared helpers for national legislation collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `scrapers/world_lib.py` | Shared helpers for new-country official gazette collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |

## Lane: municipal (63 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `municipal/build_ch_municipal.py` | Turn collect_ch_municipal.py raw docs.jsonl into the MUNICIPAL_HANDOFF layout. | `python municipal/build_ch_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_dk_municipal.py` | Build denmark_municipal from the NSTAR texts fetched by collect_dk_nstar.py (offline). | `python municipal/build_dk_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_fi_municipal.py` | collect_fi_municipal.py raw docs_fi.jsonl -> MUNICIPAL_HANDOFF layout (finland_municipal). | `python municipal/build_fi_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_gr_municipal.py` | Build the Greek municipal regulatory-acts corpus (Diavgeia) into OUT (MUNICIPAL_HANDOFF layout). | `python municipal/build_gr_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_hu_municipal.py` | Build hungary_municipal from the Common Crawl captures fetched by collect_hu_cc.py (offline). | `python municipal/build_hu_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_ie_municipal.py` | Build the Ireland municipal corpus (local-authority bye-laws) from the collector output. | `python municipal/build_ie_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_jo_municipal.py` | Build the JO municipal supplement (add-only vs endomorphosis/ipfs_jordan_municipal_laws) from the collected state. | `python municipal/build_jo_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_lu_municipal.py` | Build the Luxembourg municipal corpus (communal regulations) from the collector output. | `python municipal/build_lu_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_sk_municipal.py` | Build the Slovak municipal VZN corpus from the collectors' JSONL (RAW/raw/*.jsonl) into OUT (MUNICIPAL_HANDOFF layout). | `python municipal/build_sk_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/build_za_municipal_supplement.py` | Build the South Africa municipal SUPPLEMENT pack (never replaces endomorphosis/ipfs_south_africa_municipal_laws). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/cc_dryrun.py` | Count-only Common Crawl dry run + HEAD reachability for municipal portals. | `python municipal/cc_dryrun.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_ch_municipal.py` | Switzerland municipal law collector (polite live fetches, no OCR). | `python municipal/collect_ch_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_ch_zurich.py` | Stadt Zuerich (BFS 261) Amtliche Sammlung collector - polite live fetches, official PDFs, pdftotext (no OCR). | `python municipal/collect_ch_zurich.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_dk_kommune_pdfs.py` | Currency check of the pre-2021 NSTAR rows + replacement texts from the kommuner's own websites. | `python municipal/collect_dk_kommune_pdfs.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_dk_nstar.py` | Denmark municipal waste regulations (affaldsregulativer) from NSTAR, Energistyrelsen's national regulation database (nstar.ens.dk). | `python municipal/collect_dk_nstar.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_fi_municipal.py` | Finland municipal rules collector (polite live fetches + Common Crawl index pointers; no OCR). | `python municipal/collect_fi_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_gr_diavgeia.py` | Greek municipal regulatory acts from Diavgeia (diavgeia.gov.gr open-data API). | `python municipal/collect_gr_diavgeia.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_hu_cc.py` | Hungarian local-government decrees (önkormányzati rendeletek) from Common Crawl captures of the Önkormányzati Rendeletek Tára | `python municipal/collect_hu_cc.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_hu_njt.py` | Hungarian local-government decrees fetched directly from the official Nemzeti Jogszabálytár, njt.jog.gov.hu (the successor of | `python municipal/collect_hu_njt.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_ie_municipal.py` | Ireland local-authority bye-laws — collector. | `python municipal/collect_ie_municipal.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_jo_gazette.py` | Jordan Official Gazette (الجريدة الرسمية, www.pm.gov.jo) -> municipal regulations / instructions (أنظمة / تعليمات). | `python municipal/collect_jo_gazette.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_jo_lists.py` | Greater Amman Municipality (media.ammancity.gov.jo, 'التشريعات') and Ministry of Local Administration | `python municipal/collect_jo_lists.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_jo_terms.py` | Fetch the publishers' terms / copyright / disclaimer pages and robots.txt status for every JO host used | `python municipal/collect_jo_terms.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_lu_communes.py` | Luxembourg communal regulations (règlements communaux) — collector. | `python municipal/collect_lu_communes.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_na_munisites.py` | NA municipal supplement: collector for official Namibian local-authority websites (adapted from collect_za_munisites.py; | `python municipal/collect_na_munisites.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_bratislava.py` | Bratislava (hlavné mesto, obec code 582000) VZN: URL list from bratislava.sk sitemaps (/vzn/<n>-<yyyy>), metadata from each page's | `python municipal/collect_sk_bratislava.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_cc_karlovaves.py` | Bratislava-Karlova Ves (obec code 529397) from Common Crawl only (www.karlovaves.sk times out for us). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_kosice.py` | Košice (obec code 599981) VZN: register www.kosice.sk/vzn (all terms; repealed acts marked 'ZRUŠENÉ'), detail page /vzn/<n> | `python municipal/collect_sk_kosice.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_petrzalka.py` | Bratislava-Petržalka (obec code 529460): archive www.petrzalka.sk/vseobecne-zavazne-nariadenia/page/N/; each <figure class="vzn"> | `python municipal/collect_sk_petrzalka.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_trencin.py` | Trenčín (obec code 505820): register trencin.sk/samosprava/transparentny-trencin/vseobecne-zavazne-nariadenia/ (current acts; | `python municipal/collect_sk_trencin.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_wp.py` | WordPress city sites with a VZN post type, read through the public WP REST API (wp-json): | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_sk_zoznamvzn.py` | Cities on the shared 'zoznam-vzn' CMS (Trnava, Poprad, ...): register /zoznam-vzn filtered by status (valid = 'Platné znenie', | `python municipal/collect_sk_zoznamvzn.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_za_munisites.py` | ZA municipal supplement: collector for official municipal websites. | `python municipal/collect_za_munisites.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_za_openbylaws.py` | ZA municipal supplement: Open By-laws (openbylaws.org.za) gap fetch. | `python municipal/collect_za_openbylaws.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/collect_za_terms.py` | Record each source host's stated terms (terms of use / disclaimer / copyright page) for the README and row licence field. | `python municipal/collect_za_terms.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/fetch_zh_pdfs.py` | Re-download the Zürich AS PDFs listed in docs_zh.jsonl (polite, 1 req/s) into a cache dir for re-extraction. | `python municipal/fetch_zh_pdfs.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/fi_fixes.py` | Verifier-driven fixes for the FI municipal build: text repair, non-normative filtering, titles, language, | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/fi_pointers.py` | Find FI municipal rule-collection documents via Common Crawl index (ranged reads only, no WARC). | `python municipal/fi_pointers.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/finalize_jo_municipal.py` | Finalize the JO municipal supplement: scrapers/, report.json, MANIFEST.json, README.md, then HANDOFF_READY LAST | `python municipal/finalize_jo_municipal.py` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `municipal/finalize_za_supplement.py` | Self-check + MANIFEST / README / scrapers for the ZA municipal supplement pack; HANDOFF_READY is written LAST and only | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/fix_za_verifier_20261023.py` | Verifier FIX pass (audit 2026-10-18) on the built ZA supplement. Usage: ZA_STATE PACK_DIR VERIFIER_HUB_DIR | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/gr_common.py` | Shared helpers for the Greek municipal collectors (copy of sk_common.py with its own cache): polite session (robots.txt via urllib.robotparser, 1 req/s per host | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/gr_fixes.py` | Greek-specific rules: subject classifier (real regulations vs. decisions that merely mention one), | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/gr_fonts.py` | Broken Greek font maps (no OCR). Diavgeia PDFs typed in non-embedded Greek TrueType fonts often carry a glyph->Unicode | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/hu_fixes.py` | Hungarian local decrees (or.njt.hu pages from Common Crawl): heading parse, issuer -> KSH code, text, § split, quality checks. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/ie_common.py` | Polite HTTP for the Ireland municipal collector: robots.txt (own matcher: '*' and '$' wildcards, longest match wins, | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/ie_fixes.py` | Ireland bye-laws: text layer, cleaning, classification, dates, issuing organ, article splitter. Self-contained; the generic text-layer and | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/jo_common.py` | Polite HTTP + resource guard for the Jordan (JO) municipal collectors (adapted from za_common.py). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/lu_common.py` | Polite HTTP for the Luxembourg municipal collector: robots.txt (own matcher: '*' and '$' wildcards, longest match wins, | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/lu_fixes.py` | Text helpers for the Luxembourg communal regulations (no OCR): text layer, cleaning, signature / page-furniture stripping, | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/ocr_candidates.py` | Image-only PDF lists for an OCR pass (not run: OCR is not approved). Adds MANIFEST['excluded_image_only_pdfs'] to packs whose build | `python municipal/ocr_candidates.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/patch_za_terms_rows.py` | Targeted row-terms patch (CoS ruling 2026-10-18 14:27 PT): rewrite only the 'Site terms:' part of `license` and | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/pdf_columns.py` | Column-aware text extraction for law PDFs with marginal notes (Randtitel), e.g. Stadt Zürich AS. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/reextract_zh.py` | Re-extract Stadt Zürich AS texts with the column-aware extractor (pdf_columns.layout_text) from the PDF cache filled by | `python municipal/reextract_zh.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/run_za_collect.sh` | ZA municipal supplement: one detached job, steps in sequence (resumable; re-run to continue). | `bash municipal/run_za_collect.sh` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `municipal/sk_common.py` | Shared helpers for the Slovak municipal VZN collectors: polite session (robots.txt via urllib.robotparser, 1 req/s per host), | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/sk_fixes.py` | Slovak VZN helpers: exclusions, dates, status, article splitting (§ / Článok / Čl. with arabic or roman numbers). | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/sk_ligature_fix.py` | Repair 'fi'/'fl' ligatures that pdftotext dropped (e.g. 'identi kačné' for 'identifikačné'): re-read the same cached PDF with | `python municipal/sk_ligature_fix.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/sk_reextract.py` | Re-extract raw records whose document was RTF or legacy .doc (collected before LibreOffice support) or HTML (re-decoded with the page charset, e.g. windows-1250 | `python municipal/sk_reextract.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/za_cc_list.py` | Selective Common Crawl index listing for ZA municipal sources (cluster.idx binary search + the few cdx blocks that | `python municipal/za_cc_list.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/za_common.py` | Polite HTTP + resource guard for the South Africa municipal supplement collectors. | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/za_split.py` | Section splitter for ZA by-law texts. split(text) -> list of (start, end, label, record_type) covering text exactly | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `municipal/zh_pointers.py` | Stadt Zuerich Amtliche Sammlung PDFs via Common Crawl index (ranged reads only). | `python municipal/zh_pointers.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |

## Lane: packaging-upload (50 files)

| File | Purpose | Entry point | ipfs_datasets_py dependency |
|---|---|---|---|
| `pack_raw_for_ir.py` | Merge a (possibly sharded) raw ``endomorphosis/ipfs_<slug>_laws`` repo into ONE pinned-schema local pack. | `python pack_raw_for_ir.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_cm_local.py` | Local-only CM package (no Hugging Face upload). Mirrors world_package.package. | `python package_cm_local.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_it_local.py` | Package Italy instruments -> staging_it (no HF upload). | `python package_it_local.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_mz_local.py` | Local-only MZ package (no Hugging Face upload). Mirrors world_package.package. | `python package_mz_local.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_na_local.py` | Local-only NA package (no Hugging Face upload). Mirrors world_package.package. | `python package_na_local.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_sn.sh` | (no docstring; inferred from filename) | `bash package_sn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_sn_local.py` | Local-only SN package (no Hugging Face upload). Mirrors world_package.package. | `python package_sn_local.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `package_zw_local.py` | Local-only ZW package (no Hugging Face upload). Mirrors world_package.package. | `python package_zw_local.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `pkg_na.sh` | (no docstring; inferred from filename) | `bash pkg_na.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `restore_and_package.py` | Restore instruments from HF parquet; package instruments -> parquet; upload. | `python restore_and_package.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_by.sh` | (no docstring; inferred from filename) | `bash run_pkg_by.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_is.sh` | (no docstring; inferred from filename) | `bash run_pkg_is.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_jm.sh` | (no docstring; inferred from filename) | `bash run_pkg_jm.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_lk.sh` | (no docstring; inferred from filename) | `bash run_pkg_lk.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_mn.sh` | (no docstring; inferred from filename) | `bash run_pkg_mn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_np.sh` | (no docstring; inferred from filename) | `bash run_pkg_np.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_rw.sh` | (no docstring; inferred from filename) | `bash run_pkg_rw.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_sn.sh` | (no docstring; inferred from filename) | `bash run_pkg_sn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_ug.sh` | (no docstring; inferred from filename) | `bash run_pkg_ug.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_upload_pdf.sh` | (no docstring; inferred from filename) | `bash run_pkg_upload_pdf.sh` | mentioned in docs/comments/strings (optional / output-format target; no import) |
| `run_pkg_uz.sh` | (no docstring; inferred from filename) | `bash run_pkg_uz.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_pkg_xk.sh` | (no docstring; inferred from filename) | `bash run_pkg_xk.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_by.sh` | (no docstring; inferred from filename) | `bash run_up_by.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_is.sh` | (no docstring; inferred from filename) | `bash run_up_is.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_jm.sh` | (no docstring; inferred from filename) | `bash run_up_jm.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_mn.sh` | (no docstring; inferred from filename) | `bash run_up_mn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_np.sh` | (no docstring; inferred from filename) | `bash run_up_np.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_rw.sh` | (no docstring; inferred from filename) | `bash run_up_rw.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_sn.sh` | (no docstring; inferred from filename) | `bash run_up_sn.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_ug.sh` | (no docstring; inferred from filename) | `bash run_up_ug.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_uz.sh` | (no docstring; inferred from filename) | `bash run_up_uz.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `run_up_xk.sh` | (no docstring; inferred from filename) | `bash run_up_xk.sh` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `sync_gap.py` | (no docstring; inferred from filename) | `python sync_gap.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_ao.py` | (no docstring; inferred from filename) | `python upload_ao.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_ao_mz.py` | (no docstring; inferred from filename) | `python upload_ao_mz.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_az2.py` | (no docstring; inferred from filename) | `python upload_az2.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_backlog.py` | Upload staging packages to Hugging Face datasets. Never prints token. | `python upload_backlog.py` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_backlog_results.md` | Upload backlog results | `n/a (documentation)` | n/a |
| `upload_batch.py` | (no docstring; inferred from filename) | `python upload_batch.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_cm.py` | (no docstring; inferred from filename) | `python upload_cm.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_do_sv.py` | (no docstring; inferred from filename) | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_it.py` | (no docstring; inferred from filename) | `python upload_it.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_rw.py` | (no docstring; inferred from filename) | `python upload_rw.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_sn.py` | (no docstring; inferred from filename) | `python upload_sn.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_sn2.py` | (no docstring; inferred from filename) | `python upload_sn2.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_tn.py` | (no docstring; inferred from filename) | `python upload_tn.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_tn_zw.py` | (no docstring; inferred from filename) | `python upload_tn_zw.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_ug.py` | (no docstring; inferred from filename) | `python upload_ug.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_zw.py` | (no docstring; inferred from filename) | `python upload_zw.py (top-level script)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
| `upload_zw_tn.py` | (no docstring; inferred from filename) | `library (import)` | none detected (stdlib/third-party only; outputs feed ipfs_datasets_py-style IR datasets) |
