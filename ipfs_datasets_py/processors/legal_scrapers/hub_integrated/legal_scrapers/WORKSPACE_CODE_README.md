# Workspace code addendum (scrapers + normalizers)

This addendum was added on top of the existing `README.md` (which is unchanged). It documents
additional **source-only** files taken from the working tree used to build the
`endomorphosis/ipfs_*_laws` and `justicedao/ipfs_*_laws_ir` datasets.
No data, logs, WARCs, parquet/json datasets, caches, virtualenvs, credentials or tokens are included.

## Layout

| Path | What it is |
|---|---|
| `scrapers/` | Per-country collectors (`collect_<cc>.py`), shared libs (`common.py`, `world_lib.py`, `archive_fallbacks.py`, `pdf_extract_lib.py`), OCR/deepen/reprocess passes, CDX/Common Crawl probes |
| `normalizers/` | `country_laws_ir` normalizer package (schema, normalize, package, upload, auth), `NORMALIZER_VERSION.md` and the build scripts |
| `municipal/` | Municipal collectors/builders/fix-ups (`collect_*_municipal.py`, `build_*_municipal.py`, `*_fixes.py`) |
| `data_<cc>/scrapers/` | Per-country snapshots of the scrapers as run for that lane |
| `na_namiblii_work/`, `rebuild_20261027/` | Small helper scripts for specific rebuilds |
| root `run_*.sh`, `upload_*.py`, `package_*`, `*_tip*.py` | Orchestration, packaging and one-off gap-fill scripts |
| `*STATUS*.md`, `SCHEMA.md`, `WORLD_COVERAGE_AUDIT.md` | Status notes, schema and coverage audit |

Local absolute user paths in notes were replaced by `/home/USER`.

## Using with ipfs_datasets_py

The normalizer output (`country_laws_ir`) is designed to feed
[`ipfs_datasets_py`](https://github.com/endomorphosis/ipfs_datasets_py): collectors write raw
laws/articles parquet, the normalizer packages them into IR releases, and `ipfs_datasets_py` is
used for content-addressed (IPFS/CID) storage, indexing and dataset loading.

```bash
pip install ipfs_datasets_py          # or install from the GitHub repo
cd normalizers && python -m country_laws_ir --help   # packaging / normalization CLI (needs HF_TOKEN only for upload)
```

Tokens are never stored in this repository; scripts read `HF_TOKEN` (and optionally
`BRAVE_API_KEY`) from the environment.

**Not legal advice.** Collectors target official gazettes / portals; the official gazette prevails.
