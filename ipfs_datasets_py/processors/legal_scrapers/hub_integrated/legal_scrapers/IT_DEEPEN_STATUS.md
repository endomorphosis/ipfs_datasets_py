# Italy Normattiva deepen — 2026-09-04 14:37 PT

## Goal
PRIORITY #1 Verifier SoT: deepen bodies/articleization (not empty law-row expansion). No HF upload. No FI/HR/SK.

## Sample (local instruments after run)
- Local JSON: ~11986 under `~/.ipfs_datasets/legal_corpora/it/instruments/`
- empty text (<40): 0
- short (40–199): ~3108 (mostly abrogation/decaduto stubs)
- ok (>=200): ~8878
- with documents (>=1): ~935 / document rows ~7919

## Deepen run (bounded)
- Script: `scrapers/deepen_it_idarticolo.py`
- Official API only: `POST .../api/v1/atto/dettaglio-atto` with `idArticolo` walk
- Bounds: MAX_NEW=350, MAX_SECONDS=3600, MAX_ARTS_PER_LAW=80
- Stopped: MAX_SECONDS at law 279/350
- Result: filled_bodies=231, api_articleized_laws=231, arts_added=+2629, singles_skipped=39, failed=8, elapsed=3615s
- Log: `~/.ipfs_datasets/legal_corpora/it/logs/deepen_api_run.log`
- Summary JSON: `~/.ipfs_datasets/legal_corpora/it/logs/deepen_articles.json`

## Packaging (no HF upload)
- Path: `~/.ipfs_datasets/legal_collectors/staging_it`
- **laws=9947 / articles=7917** (text≥80 filter; dropped 1985 shells of 11932 JSON at package time)
- Prior staging: 6314 / 1265
- Prior HF shell tip: ~42 articles (or historical shell catalog)
- Success: articles **7917 >> 42** with real article text (median art len ~2406; 7503 arts with len≥80)

## Source
- Normattiva OpenData BFF (`api.normattiva.it/.../bff-opendata/v1`)
- Catalog discovery: `ricerca/avanzata` (existing local catalog; parallel `collect_it` also grew law rows)
- Bodies/articles: `dettaglio-atto` + `idArticolo` integer walk (confirmed Art.N mapping on multi-article acts e.g. L.241/1990)
- `caricaAKN` currently returns error HTML page (not used for this deepen)

## Gaps
1. ~1.8–3.1k short instruments are abrogated/decaduto notices — little body to fill.
2. Many acts are genuinely single-article in Normattiva (`idArticolo=2` → 404); cross-ref `Art. N` mentions are not article boundaries.
3. Normattiva catalog ~200k; local still incomplete vs full catalog — deepen prioritized existing IDs.
4. Parallel `collect_it.py` catalog expansion ran during deepen (increased law-row count); this pass did not start a second catalog scrape.
5. Run hit MAX_SECONDS before finishing all 350 candidates (~279 processed).
6. Some `idArticolo=1` payloads include preamble with the first article blob.

## Do not
- HF upload (not done)
- FI/HR/SK bulk expansion (not touched)
