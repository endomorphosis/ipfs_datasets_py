# scrapers_and_normalizers/ (justicedao/world_law_scrapers caselaw/)

Provenance bundle: the exact collector(s) and normalizer used to build this dataset.
Canonical copy: https://huggingface.co/datasets/justicedao/world_law_scrapers (folder `caselaw/`).

| path | role |
|---|---|
| `fr_dila/` | collector |
| `de_rii/` | collector |
| `au_oalc/` | collector |
| `ca_a2aj/` | collector |
| `in_aws/` | collector |
| `in_hc/` | collector |
| `at_ris/` | collector |
| `common/guard.py` | memory/disk guards (MemAvailable stop 3.2G default `CASELAW_MEM_STOP`, disk stop 20G `CASELAW_DISK_STOP`, `MALLOC_ARENA_MAX=2`), resumable `state.json`, 2,000-row zstd parquet parts |
| `common/normalize_caselaw.py` | normalizer backed by `ipfs_datasets_py` (`endomorphosis/ipfs_datasets_py`, `processors.legal_data.canonical_legal_corpora`): standard string-typed core fields, `licence`/`licence_flag`/`flag`, provenance, `doc_id`, CAP-exclusion check |

Policy: keyless public sources only; no captcha/WAF/login bypass; text only (PDFs not stored); excludes Caselaw Access Project / CourtListener / Free Law Project / Harvard LIL material.
No credentials are contained in this bundle (scanned before upload).

Datasets: justicedao/ipfs_{france,germany,australia,canada,india,austria}_caselaw. `in_hc` (India High Courts, AWS Open Data CC-BY-4.0) is collecting; not yet published.
