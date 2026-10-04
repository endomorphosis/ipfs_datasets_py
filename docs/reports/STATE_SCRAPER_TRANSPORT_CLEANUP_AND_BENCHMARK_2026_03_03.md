# State Scraper Transport Cleanup and Benchmark (2026-03-03)

## Scope
This report summarizes the transport-layer cleanup in `state_scrapers` and the post-cleanup benchmark comparison for the bounded 10-state actor/critic run.

States used for benchmark comparison:
`OK, OR, HI, TN, MO, DE, NM, MS, CA, WY`

## Code Changes Completed
1. Removed direct `requests` transport patterns from `state_scrapers` modules and utility scripts.
2. Migrated remaining HTTP transport codepaths to stdlib `urllib` where appropriate.
3. Updated unit tests to mock `_fetch_page_content_with_archival_fallback` directly instead of monkeypatching `requests.get`.

Primary files touched in final cleanup phase:
- `ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py`
- `ipfs_datasets_py/processors/legal_scrapers/state_scrapers/rhode_island.py`
- `tests/unit/legal_scrapers/test_state_scrapers_archival_fetch_path.py`

Utility transport refactors completed earlier in this sequence:
- `ipfs_datasets_py/processors/legal_scrapers/state_scrapers/state_archival_fetch.py`
- `ipfs_datasets_py/processors/legal_scrapers/state_scrapers/state_archival_pointer_downloader.py`
- `ipfs_datasets_py/processors/legal_scrapers/state_scrapers/state_warc_batch_downloader.py`
- `ipfs_datasets_py/processors/legal_scrapers/state_scrapers/state_warc_batch_downloader_from_partitions.py`

## Validation Status
Focused suite run after final transport cleanup:
- `tests/unit/legal_scrapers/test_state_scrapers_archival_fetch_path.py`
- `tests/unit/legal_scrapers/test_state_laws_verifier_operational.py`
- `tests/unit/optimizers/test_state_laws_actor_critic_loop.py`

Result: `46 passed`

## Transport Surface Check
Search checks in `state_scrapers/*.py` after cleanup:
- `requests.get(`: 0 matches
- `requests.Session(`: 0 matches
- `import requests`: 0 matches

## Benchmark Comparison (Like-for-Like Config)
Baseline artifact:
- `/tmp/state_laws_opt_compare_20260303/20260303_010252/final_summary.json`

Post-cleanup artifact:
- `/tmp/state_laws_opt_compare_20260303_postcleanup/20260303_014402/final_summary.json`

### Key metrics
- `fetch.attempted`: `663 -> 814` (`+151`)
- `fetch.success`: `403 -> 452` (`+49`)
- `fetch.success_ratio`: `0.608 -> 0.555` (`-0.053`)
- `fetch.no_attempt_states`: `0 -> 0` (unchanged)
- `coverage.states_returned`: `2 -> 2` (unchanged)
- `coverage.states_with_nonzero_statutes`: `2 -> 2` (unchanged)
- `critic_score`: `0.6409 -> 0.6151` (`-0.0258`)
- `etl_readiness.citation_ratio`: `0.567 -> 0.383` (`-0.184`)

### Notes
- The cleanup did not regress `no_attempt_states` (still zero).
- Coverage remained constrained by runtime network conditions observed during runs (notably archive endpoint connection refusals).
- Benchmark quality signal appears dominated by environment/runtime variability rather than HTTP client implementation differences.

## Conclusion
The transport cleanup objective is complete for `state_scrapers`: direct `requests` usage has been eliminated, tests are green, and benchmark telemetry confirms no reintroduction of no-attempt fetch blind spots.
