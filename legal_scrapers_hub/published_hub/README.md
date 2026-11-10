# Scrapers and normalizers published with the Hugging Face datasets

> Moved unchanged in legal_scrapers phase 3b from `ipfs_datasets_py/processors/legal_scrapers/published_hub/` to `legal_scrapers_hub/published_hub/` (repository root), so it is no longer importable or shipped in wheels. Relative paths below are unchanged.

This tree is the code from the JusticeDAO and endomorphosis dataset repos that was not already in `ipfs_datasets_py` on `origin/main`. It was added on 2026-11-07 so the package matches the collectors that built those datasets.

`origin/main` (`22cfb0dc3`, 2026-10-28) already contains `processors/legal_scrapers/` (about 6,154 files) and `processors/legal_data/`. The canonical Hugging Face archive `justicedao/ipfs_legal_scrapers_and_normalizers` was cut from commit `629169ed` (2026-10-20), which is an ancestor of that main. The per-dataset `scrapers_and_normalizers/` folders are subsets of that archive, not separate codebases. Those copies were not vendored again.

## What was added

| Path | Source |
|---|---|
| `canonical/workspace_courts_collector/` | `justicedao/ipfs_legal_scrapers_and_normalizers` |
| `canonical/workspace_courts_intl_collector/` | same archive |
| `canonical/workspace_caselaw_scrapers/` | same archive (AT, AU, CA, DE, FR, IN, and the shared caselaw normalizer) |
| `world_law_scrapers/collectors/` | `justicedao/world_law_scrapers` |
| `world_law_scrapers/normalizers/` | same repo, including `ir_adapters/` |
| `world_law_scrapers/caselaw/` | same repo |
| `world_law_pipeline/` | `endomorphosis/world_law_pipeline`: court, county, and caselaw scrapers, the pipeline normalizer (`normalize.py`, `schema.py`, `run_loop.py`), and scraper files whose names were not already on main |
| `legal_scrapers_hub/` | files from `endomorphosis/legal_scrapers` under `scrapers/`, `normalizers/`, `municipal/`, and `courts/` whose filenames were not already on main |

Court seed JSON under 2 MB is included. County `entries/` JSON, caselaw CDX `state/` files, and `extras/staging_scripts/` (about 11,000 ad-hoc probes) were left on the Hub. Harvested opinion and statute parquet was not copied.

## Dataset repos

760 Hugging Face repos were listed (376 `justicedao` datasets, 364 `endomorphosis` datasets, 20 `endomorphosis` models, 0 `justicedao` models). 747 have a root file or folder whose name contains scraper, normalizer, collector, or pipeline. The repeated pieces are `scrapers_and_normalizers/`, a root `normalize.py` on the IR repos, and a `scrapers/` folder on the `endomorphosis/ipfs_*` law repos. `justicedao` has no models. `endomorphosis/world_law_pipeline` is the model that builds `world_municipal_law` and `world_national_law`.
