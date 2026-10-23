# asia_latam lane (JP, ES, BR, PE, AU, ZA, MX, CL)

Code: `pipeline/scrapers/asia_latam/<cc>/`. Output: `staging/asia_latam/` only, per SCHEMA staging rules
(tmp -> fsync -> validate_file -> rename; new batch suffix for additions; `.full` for replacement).
Robots: `common/rfc9309.py` (unreachable/5xx robots.txt = disallow-all). The archive queue, ID/ and `_archive_*`
belong to the archive worker; this lane only appends rows to `_archive_queue_asia_latam.csv`.

## Operations
- `common/supervisor.py` adopts and relaunches lane jobs from checkpoint (jobs in `common/supervisor_jobs.json`,
  exit codes in `_state/supervisor/`). It also writes `_logs/mem_trend.csv` and `_logs/oom_events.log`.
  Stop it with `touch _state/supervisor/STOP`.
- `status_all.py` gives the lane totals.

## Incident log
- 2026-10-10 ~18:48 PT (round 11): I sent one SPARQL query to query.wikidata.org/sparql, which robots.txt
  disallows. It was chained in the same shell command as the robots check, so it ran before I read the rules.
  It returned Portuguese labels for P1585. I deleted the result unused. The coordinator ruled that occasional
  low-volume SPARQL with a descriptive UA is acceptable (it is a programmatic API), but Wikidata dumps or the
  entity API are preferred where practical. Practice since then: robots is checked in a separate step before
  any first request to a new host.
- 2026-10-10 18:56 PT: the JP full crawl (PID 3269143, 40 workers) died with no traceback during a series of
  global OOM kills on the shared 16 GB box (no swap). Fix: the supervisor, JP relaunched with 16 workers,
  and OOM kills are now logged.
- 2026-10-10 19:25 PT: one SPARQL query (P3801 + P856 + es label) -> mx/wd_P3801_sites.csv, under the coordinator's low-volume allowance.

## Place-code crosswalk adoption (2026-10-10 ~20:15–20:40 PT)
- `common/place_codes.py`: stdlib reader for `pipeline/codes/place_codes.csv` (parquet needs pyarrow, not installed). `code_to_place(system, cc)` keeps only current, unambiguous codes and drops `not_municipal_level`.
- PE (`pe/pe_places.py`, backup `_pe_places.bak_pre_ubigeo.py`): fallback on the official INEI UBIGEO list (`codes/cache/pe_ubigeo_geodir.csv`) + `pe_ubigeo` → place_id. Provincial/metropolitan municipality → capital district DDPP01; district name with a province/department hint. Non-municipal issuers still unmatched. `pe/reresolve.py` re-emitted the remaining 347 rows (Huamachuco 141, Santa Ana 55, Castilla 51, Callería 50, Pariñas 50). pe_gobpe was held with `"disabled": true` in supervisor_jobs.json, stopped right after an institution "done" line, then re-enabled.
- ES (`es/es_places.py`, backup `_es_places.bak_pre_inedic.py`): official INE diccionario 2025 names (bilingual "A/B" forms split) as an extra name source, `es_ine` → place_id first in `place_for_ine`, and "Ayuntamiento de X. <department>" stripped to the ayuntamiento. All es_bop runs were restarted (SIGTERM; they resume from state) and `es/reresolve_bop.py` was rerun.
- BR (`br/lexml.py`, backup `_lexml.bak_pre_ibge.py`): official IBGE names (`codes/cache/ibge_municipios.json`) + `br_ibge` → place_id take precedence over the Wikidata labels (no existing mapping changed). Renamed-municipality aliases: São Valério da Natividade → São Valério, Presidente Juscelino (RN) → Serra Caiada. New `br/reresolve.py` (manifest `_unmatched/_reemitted_br.jsonl`).
- MX (P3801 is what the crosswalk's `mx_inegi` uses) and JP (soumu dantai codes) already match the crosswalk, so they were not changed.
- Supervisor: per-job log names (`<job>_<ts>.log`). Previously, jobs relaunched in the same minute shared one log. To hold a job, set `"disabled": true` in supervisor_jobs.json; the file is reread every poll.
- `status_all.py` (backup `_status_all.bak_pre_dedup.py`):
  - Counts doc_ids once per place.
  - A `.full` batch supersedes the place's older batches.
  - New MX sources are labelled.
  - New `unmatched_staged` field: parked rows minus re-emitted manifests.

## Health-check fixes (2026-10-11 ~03:35–03:50 PT)
- legal_square (backup `jp/_legal_square.bak_pre_matcher.py`):
  - Cause: the SessionLost loops came from the viewer, which truncates long titles with "…". jp0605 and jp0597 hit this, and so did 19 earlier seeds that ended in error.
  - Fix: `viewer_matches()` compares titles after NFKC (full/half width), whitespace removal, kana and long-vowel folding, and bracketed-suffix stripping. A truncated viewer title must be a prefix of the list title (at least 8 characters). The viewer's 公布 line (date + number) must also match.
  - Seed order: interrupted seeds resume first, and `--first jp0605,jp0597` is in the supervisor cmd.
- es_bop BORM (backup `es/_es_bop.bak_pre_borm_skip.py`):
  - Cause: the "unexpected sumario response (15074 bytes)" was a Radware/ShieldSquare CAPTCHA page (sample in `_logs/_samples/`). It is never solved or circumvented.
  - Handling: a challenge is recorded in error_days and in `_logs/_skipped_days_es_bop.csv`, followed by a 15-minute cooldown; after 3 challenges the gazette pauses at its checkpoint. BORM now runs at 3 s per request.
  - Error days used to be recorded but never retried. They are now retried at every run start. Other non-sumario pages get 3 quick retries, are then logged as skipped, and are retried later.
  - Two captcha pages had been staged as docs (BORM-2024-3599/3600 in `ES/wd_Q12225.borm-p00154-20261011T103526Z.jsonl` and `ES/wd_Q931116.borm-p00154-20261011T103526Z.jsonl`). They were re-fetched and re-emitted, and the Normalizer needs to tombstone those two files. Doc text that is a captcha page now raises instead of being staged.
- Castellón (forward-only): the 1 doc is expected. BOP Nº 122 (10/10/2026) has 22 items, 16 of them local, and only one is ordinance-type (Torreblanca, CS-168229). `run_forward` now tracks bulletin-number continuity (`last_number` in castellon_fwd state, seeded at 122) and logs any missed issue to `_skipped_days_es_bop.csv`.

## Disk hygiene (2026-10-11 ~08:25–08:45 PT)
- `common/jsonl_io.py` provides `open_text`, `glob_jsonl` and `locate`, which read `.jsonl` and `.jsonl.gz` transparently. Switched readers: jp/reemit_d1law.py (new `--dry`), jp/reemit_opsjg.py (`--dry`, uses `locate`), jp/audit_robots.py, arch/pe_pdf.py, arch/policy_reemit.py (`--dry --all` test mode), arch/meta_scan.py, status_all.py (now also counts processed/), es/reresolve_bop.py, br/reresolve.py, pe/reresolve.py.
- `common/gzip_processed.py`: gzips processed/asia_latam in place. Per file: .gz.tmp, fsync, verify sha256 and line count, rename, unlink the original. Ledger in `_logs/gzip_processed.tsv`. Supervisor job `gzip_processed` reruns it hourly (`--loop-minutes 60`). run_loop.py never reads processed/ (see pipeline/tools/compress_processed.py).
- Archive bodies: `arch/arch_common.py` (backup `_arch_common.bak_pre_evict.py`) evicts a capture's cached body from pipeline/archive/_cache once its doc is staged. Robots-meta-flagged captures are kept. Evictions are logged in `_logs/_archive_cache_evicted.jsonl`. The running archive jobs pick this up at their next launch. That cache is shared by all lanes and capped at 8 GB by the archive library.
- pe/_sitemaps/sitemap*.normas.txt (extracted URL lists, already split into by_slug/) are gzipped; fetch_sitemaps.py skips existing .gz files.

## 2026-10-12 PE filename fix + prune tolerance
- pe_gobpe: batch token from `safe_token(slug)` (percent-decode, ASCII-fold, [A-Za-z0-9_-] only); write_atomic refuses non-SCHEMA names and overwrites. Touch `_state/pe/_RESTART` for a graceful between-institution restart (exit 75, supervisor relaunches).
- status_all.py: tolerates files vanishing mid-scan (falls back to .gz, then ledger). Per-file ledger `_state/status_ledger/<CC>.json` keeps pruned files counted: `docs` = cumulative, `docs_on_disk`, `docs_pruned`.
- gzip_processed.py: skips files pruned mid-scan, never resurrects a pruned file as .gz.
