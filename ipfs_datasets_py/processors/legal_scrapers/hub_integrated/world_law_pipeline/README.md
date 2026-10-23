---
tags:
- legal
- municipal-law
- data-pipeline
- web-scraping
datasets:
- endomorphosis/world_municipal_law
- endomorphosis/world_national_law
---

# world_law_pipeline

Code that builds the [`endomorphosis/world_municipal_law`](https://huggingface.co/datasets/endomorphosis/world_municipal_law) and [`endomorphosis/world_national_law`](https://huggingface.co/datasets/endomorphosis/world_national_law) Hugging Face datasets. Scrapers write to a staging
tree, and the normalizer/uploader validates the rows, holds back rows whose source policy forbids publishing,
then writes sharded ZSTD parquet, metadata, a manifest and the dataset card.

| path | what |
|---|---|
| `run_loop.py` | normalizer + uploader: discovery, batch ordering, holds, doc overrides, streaming/sharded writes, Hub commit plan (incl. stale-shard deletes). Always try `--once --dry-run` first |
| `normalize.py`, `schema.py`, `SCHEMA.md` | schema v1.1.0 (34 columns incl. optional provenance), staging contract, hold policy (§2.1) |
| `card.py` | dataset cards (municipal + national; cross-linked) incl. provenance/archived-share table |
| `tools/split_national.py` | one-off 2026-10-11 move of iso_* places from world_municipal_law to world_national_law (upload + verify sha256/rows, then a separate delete commit) |
| `tools/prune_processed.py` | verified pruning of `processed/` sources + `state/confirmed_batches/<bot>.jsonl` (called by `run_loop.py` after each upload) |
| `world/` | refactor of the US `american_municipal_law` hub code (CID function byte-identical; see `world/CID.md`) |
| `tests/` | `test_us_cid.py` (US CID parity; needs the original ipfs_datasets_py checkout), `test_hold_policy.py`, `test_routing.py`, `test_disk_prune.py` (synthetic, /tmp only), `make_synthetic.py` |
| `codes/` | `build_place_additions.py` (places missing from the candidate list, incl. former-type false positives restored by `audit_former_types.py`), `build_place_codes.py`: place_id ↔ national code crosswalk (CBS, TERYT, RÚIAN, KSH, GKZ, INE, ISTAT, INSEE, AGS, BFS, dantai/JIS, IBGE, INEGI, UBIGEO, CUT, BPS/Kemendagri, LAU, NUTS); cached inputs are not bundled. Run it to regenerate |
| `archive_fetcher/` | Wayback/Common Crawl fetcher (`core.py`, `ratelimit.py`, `staging.py`, `cli.py`) + vendored legal_scrapers helpers |
| `scrapers/eu/` | NL CVDR, PL e-dzienniki |
| `scrapers/national/` | national/subnational collectors (`shared/collect_*.py`, ~230 jurisdictions), archive emitters, run scripts |
| `scrapers/asia_latam/` | JP reiki (gyosei, d1-law, joureikun, legalsquare), ES BOP, BR, PE, MX, CL, ID, ZA, AU, archive jobs (`arch/`) |
| `scrapers/web/` | DE Ortsrecht crawler + robots audit |
| `state/doc_overrides.json` | per-doc quarantine list applied by `run_loop.py` (misfiled / non-law docs) |
| `extras/staging_scripts/` | ad-hoc probe scripts found under `staging/national/_archive_work/` (kept for provenance; not part of the pipeline) |

Excluded on purpose: virtualenvs, `__pycache__`, caches (`archive/_cache`, `_ratelimit`), raw downloads (`raw/`,
`_sitemaps/`, `data/`), `*.bak*` backups and `world/*_draft.py` drafts, and all staged/output data.

Environment: Python 3.13, `pyarrow`, `huggingface_hub` (upload only), `requests`; `openpyxl` for the code
builder's xlsx inputs; `tesseract` for the OCR collectors.

### Paths / environment variables
| variable | default | used by |
|---|---|---|
| `WORLD_LAW_ROOT` | `/workspace/world_law` | `run_loop.py` (staging/, out/, processed/, quarantine/, held/, state/), scrapers (staging + pipeline paths), `codes/` |
| `GLOBAL_MUNICIPALITIES_ROOT` | `/workspace/global_municipalities` | scrapers that read `global_municipalities_candidate.csv` |
| `GLOBAL_MUNICIPALITIES_CSV` | `/workspace/global_municipalities/global_municipalities_candidate.csv` | `codes/build_place_codes.py` |
| `TESSDATA_PREFIX` | `/home/box/tessdata` (set via `os.environ.setdefault`, so an existing value wins) | OCR collectors in `scrapers/national/shared/` (`collect_sr.py` and `collect_ht.py` also probe `/home/box/tessdata/*.traineddata` for the language choice) |

Still hard-coded (documented, not env-ified): `/workspace/ipfs_datasets_py[_latest]` (the upstream
`ipfs_datasets_py` checkout used by some collectors, `cvdr.py`, `es_sede.py`, `de_ortsrecht_crawler.py` and
`tests/test_us_cid.py`), `/workspace/municipal_law/_verify_tmp` (US CID test fixtures), the `sys.path` hint in
`schema.py`'s docstring, and a few f-string paths in one-off scripts (e.g. `scrapers/national/archive/peek.py`).
`run_loop.py` command-line flags (`--staging --out --state --held …`) override everything.

Uploader usage: `python run_loop.py --once` (hourly-safe: `flock` lock in `state/run_loop.lock`; a sha256
ledger in `state/ledger.jsonl` means nothing is processed twice; staged files move to `processed/` only after every
commit succeeds; 429/5xx commits are retried with backoff). Always try `--once --dry-run` first.

### Repo routing (since 2026-10-11)
Places whose place_key starts with `iso_` (place_id `iso:*`: admin_level country, adm1, supranational) are
written to `endomorphosis/world_national_law` (local state `out_national/`, `--national-repo`, `--out-national`);
everything else (municipalities, counties, water boards, ...) to `endomorphosis/world_municipal_law` (`out/`).
Both repos have the same layout (`world_law/data`, `metadata`, `manifests`, `places.parquet`) and their own card.
Each repo is committed separately (plan files `planned_commit.jsonl` / `planned_commit_national.jsonl`); staged files
stay in staging only for the repo whose commit failed. The ledger records the target repo per file.

### Disk guard and verified pruning
At the start of each run `run_loop.py` checks free space on `/`: below `--disk-warn-gb` (15) it logs, writes
`state/disk_alert.json` and prints a `DISK_LOW free=...` line; below `--disk-stop-gb` (8) it builds no new places
(and stops building mid-run if it crosses the threshold; already-built places still commit). After the upload it
calls `tools/prune_processed.py`, which deletes a `processed/<bot>/` file (plain or `.gz`) only when: the bot is in
`state/prune_config.json` (default `["eu", "national"]`); its content sha256 matches a ledger entry >= 2h old; the
commit that carried its place is in the Hub repo history; and every parquet of its place in `out/`/`out_national/`
matches the Hub file's sha256 and size. Each delete is first appended to `state/pruned_manifest.jsonl`. The ledger
is never changed, so a re-staged identical file is still skipped. `--no-prune` disables it.

Secret scan (2026-10-10): no tokens, keys, cookies files, `.env` or credentials-in-URL in this bundle. See
the report given to the maintainer for details. Collectors read `HF_TOKEN` / `~/.cache/huggingface/token` from the
environment only. `collect_td.py` fetches a public Supabase anon key at runtime (not stored). Several
OCR collectors hard-code `/home/box/tessdata`.

<!-- lane-scrapers:start (tools/sync_code.py) -->
## Datasets

| dataset | contents |
|---|---|
| [`endomorphosis/world_municipal_law`](https://huggingface.co/datasets/endomorphosis/world_municipal_law) | municipal / local law texts (one parquet per place) |
| [`endomorphosis/world_national_law`](https://huggingface.co/datasets/endomorphosis/world_national_law) | national, subdivision and supranational (`iso:*`) law texts |
| [`endomorphosis/world_law_scanned_pdfs`](https://huggingface.co/datasets/endomorphosis/world_law_scanned_pdfs) | raw image-only scanned PDFs: loose `pdfs/` (before 2026-10-18) + per-country tar shards `shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar`; `manifest.parquet`; `world_law_loader.fetch_pdf(pdf_ref)` reads one PDF (shards via HTTP Range) |

## Lane scrapers

All scraper / runner code of the world-law lanes is under [`scrapers/`](scrapers/README.md); the
[index](scrapers/README.md) lists every file with its lane, the source/platform it covers and a one-line purpose.
Synced hourly by `tools/sync_code.py` (only new/changed files; secret scan must be clean).

| path | files | lane |
|---|---:|---|
| `scrapers/eu/` | 69 | EU member states (NL CVDR/GMB, PL e-dzienniki, BE, EE, ES BOE autonómico, GR Diavgeia, IT statuti, LV, PT DRE, SI, UK LA) |
| `scrapers/web/` | 31 | Web crawlers for municipal by-laws (DE Ortsrecht + archive pass, FR actes, IT, CH, CA) |
| `scrapers/national/` | 306 | National/subnational collectors (`shared/collect_*.py`, ~230 jurisdictions), archive emitters |
| `scrapers/asia_latam/` | 91 | JP reiki, ES BOP/sede, BR LexML/SAPL, PE, MX, CL, ID, ZA, AU, archive jobs (`arch/`) |
| `scrapers/afme/` | 20 | Africa & Middle East gazettes/LII/live sites, Common Crawl index jobs (`afme_cfg_*.json` source lists) |
| `scrapers/sasia_ru/` | 53 | South Asia & Russia/CIS: RU gosweb, BY pravo, KG CBD, NP palika, PK Sindh, IN MCGM, UZ lex, VN VBPL |
| `scrapers/eap/` | 4 | East Asia & Pacific archive runner (KR, TW, NZ, PG, SB, TO, VU, WS) |
| `scrapers/ph/` | 11 | Philippines LGU sites + Wayback pass |
| `scrapers/id_jdih/` | 5 | Indonesia JDIH (regional legal documentation networks) |
| `scrapers/ocr/` | 23 | OCR passes for scanned PDFs (afme, GB, PH, RO, South Asia) + sweep tools |
| `scrapers/states/` | 40 | States & provinces lane (staging/states/) |
| `scrapers/ukie/` | 31 | UK & Ireland lane (staging/ukie/) |

How to run a lane scraper:
* Python 3.13 in a virtualenv: `python3.13 -m venv venv && venv/bin/pip install requests pyarrow beautifulsoup4 lxml huggingface_hub`
  (+ `tesseract` / `pdftotext` for OCR lanes, `playwright` for `collect_spa_playwright.py`). On the build box the
  interpreter is `/workspace/world_law/pipeline/venv/bin/python`.
* Set `WORLD_LAW_ROOT` (default `/workspace/world_law`) and, for scrapers that read the candidate list,
  `GLOBAL_MUNICIPALITIES_ROOT`. Lane scripts are run from their own directory, e.g.
  `cd scrapers/eu && ../../venv/bin/python cvdr.py --help`, or via the lane's `run_*.sh`.
* Staging contract ([`SCHEMA.md`](SCHEMA.md) §1): a lane writes only `staging/<lane>/<CC>/<place_key>[.<batch>].jsonl`
  (`<CC>` = ISO 3166-1 alpha-2 uppercase, `<place_key>` = `schema.place_key(place_id)`, a UTC timestamp
  `YYYYMMDDTHHMMSSZ` in `<batch>`, write to a `.tmp` and rename). Anything under `staging/<lane>/_*` is ignored.
  `run_loop.py --once --dry-run` validates and shows what would be published; `iso:*` places go to
  `world_national_law`, everything else to `world_municipal_law`.
<!-- lane-scrapers:end -->

## world_law_loader.py

`world_law_loader.py` loads `endomorphosis/world_municipal_law` (optionally `world_national_law`) plus the US corpus in
`endomorphosis/american_municipal_law` through the pointer rows (`has_local_data=false`) in
`world_law/places.parquet`, maps the US 5-column files onto the 34-column schema (other columns null), and filters
by country and place: `load(countries=["US"], places=["gnis:1085809"])`. `us_pointers.py` maintains the pointer rows
(refreshed from the US listing at most daily). `run_loop.py` has a per-commit watchdog (20 min, one retry after a Hub
history check), a 50 min run deadline, heartbeats and a PID/heartbeat lock file with stale-holder reporting.
