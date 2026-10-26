# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
# PDF staging contract — scanned (image-only) PDFs → `endomorphosis/world_law_scanned_pdfs`

For the OCR bot (1b081175-572b-4b0b-b0e7-0962b6c051fb). Consumer: `tools/upload_pdfs.py` (run hourly by
`tools/pdf_step.py` right after `run_loop.py --once`). Version 1.0 (2026-10-14).

## 1. What to stage
Only **image-only** PDFs (no usable text layer) that are the source of a law document (published or not yet
published in world_municipal_law / world_national_law). Text-layer PDFs: don't stage here.

## 2. Files
```
/workspace/world_law/staging/pdf/<CC>/<place_key>/<doc_id-sanitized>.pdf
```
* `<CC>`: ISO 3166-1 alpha-2, upper case (`EU` for supranational).
* `<place_key>`: `schema.place_key(place_id)` — `place_id` with `:` → `_` (`wd:Q90` → `wd_Q90`, `iso:US-CA` →
  `iso_US-CA`, `gnis:123` → `123`). No bucket level in staging (the uploader adds it on the Hub).
* `<doc_id-sanitized>`: the raw `doc_id` with every `:`, `/` and `\` replaced by `_`; nothing else changes
  (`upload_pdfs.sanitize_doc_id`). If two doc_ids of one place collide after sanitizing, put the real relative
  path in the optional manifest field `pdf_file` (e.g. `"PH/wd_Q1/abc_1.v2.pdf"`, relative to `staging/pdf/`).
* The file must start with `%PDF-`. Write as `<name>.pdf.tmp` (or `.<name>`/`_<name>`) and rename; the uploader
  ignores names starting with `_` or `.` and `*.tmp`, and any file no manifest line points to.

## 3. Batch manifest
```
/workspace/world_law/staging/pdf/_manifest/batch_<NNNN>.jsonl     NNNN = 0001, 0002, ... (zero-padded, increasing)
/workspace/world_law/staging/pdf/_manifest/batch_<NNNN>.ready     empty marker, written LAST
```
One JSON object per PDF, UTF-8, one per line. All fields required (`source_policy` may be null):

| field | type | notes |
|---|---|---|
| `doc_id` | string | **raw** doc_id, exactly as in the law row (unsanitized) |
| `place_id` | string | `wd:Q…` / `iso:CC[-SUB]` / `gnis:N` |
| `place_key` | string | must equal `schema.place_key(place_id)` |
| `country_code` | string | ISO alpha-2 |
| `source_url` | string | URL the PDF was fetched from (archive URL if archive-sourced) |
| `sha256` | string | lower-case hex sha256 of the file bytes |
| `bytes` | int | file size |
| `fetched_at` | string | ISO 8601 UTC, e.g. `2026-10-14T10:00:00Z` |
| `source_policy` | string, list or null | same tags as the law rows; keep **all** tags incl. `content_signal…` (`;`-joined or a list) |
| `lane` | string | your collection lane (e.g. `live`, `archive`, `gb`, `afme`) |

Optional: `pdf_file` (see §2); `robots_disallowed` / `archive_*` keys are honoured exactly as in SCHEMA.md §2.1.

Batch size: about **2 GB** of PDFs (any number of files). A batch is processed only once `batch_<NNNN>.ready`
exists. Never edit a batch's jsonl or PDFs after writing `.ready`.

## 4. Source policy (same rule as the law rows, SCHEMA.md §2.1)
Records whose `source_policy` contains `robots_unreachable` or `robots_disallowed`, or that are live fetches with
`robots_disallowed=true`, are **held**: the PDF is moved to `/workspace/world_law/held/pdf/<CC>/<place_key>/` and
never published. Everything else is published with its `source_policy` tags in `manifest.parquet`.

## 5. What the uploader does / gives back
1. Validates each line, checks size, `%PDF-` header and sha256 (streaming).
2. (Since 2026-10-18, default `--shard-mode tar`) packs the batch into per-country tar shards
   `shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar` (members `<place_key>/<sha256>.pdf`, ~768 MB, see tools/pdf_shards.py;
   pdf_ref `<repo>:<shard>#member=..&offset=..&size=..&sha256=..`). Nothing changes for the OCR bot. Fallback
   `--shard-mode loose`: uploads to `pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf` (`b` = sha256(place_key)[:2] for FR, IT, DE) in a few
   large xet commits, then verifies every file's sha256 on the Hub.
3. Updates `manifest.parquet` + README, writes `pdf_ref` sources for the law datasets.
4. Deletes the batch's **verified** PDFs (held ones are moved, unverified/skipped ones stay), keeps the jsonl, and
   writes `batch_<NNNN>.pushed`:
```json
{"batch": "batch_0001", "repo": "endomorphosis/world_law_scanned_pdfs", "records": 812,
 "commits": ["<oid>", "..."], "manifest_commit": "<oid>", "uploaded": 800, "already_on_hub": 2,
 "verified": 802, "deleted_local": 802, "manifest_rows_total": 5021, "backfill_queued_places": 31,
 "held":    [{"doc_id": "...", "reason": "source_policy:robots_unreachable"}],
 "skipped": [{"doc_id": "...", "reason": "sha256_mismatch:<hex> | bytes_mismatch:.. | missing_file:<rel> | not_a_pdf | missing:<field> | place_key_mismatch:.. | hub_sha256_verify_failed"}],
 "started_at": "...", "finished_at": "..."}
```
If any upload fails Hub verification, `batch_<NNNN>.retry.json` is written instead of `.pushed` and the batch is
retried next hour (verified files are not re-uploaded). Skipped records: fix and stage them in a **new** batch.
Re-staging an already-published PDF is harmless (deduplicated by sha256 path; it is just deleted).

## Upload loop (tools/pdf_loop.py, 2026-10-15)

Uploads no longer wait for the hourly step. A detached loop (`tools/pdf_loop.py --start`; pid in state/pdf_loop.pid,
log state/pdf_loop.log, child output state/pdf_loop_upload.log, heartbeat state/pdf_loop.status.json) runs
upload_pdfs.py every 5 min or within 20 s of a new `.ready`. upload_pdfs has a per-commit timeout (--commit-timeout,
25 min) and a MemAvailable floor (1.5 GB, same as run_loop); the loop watchdog kills a child silent > 35 min or
running > 4 h and retries; a live upload_pdfs holding state/pdf_upload.lock > 120 min is killed. The loop never
takes run_loop.lock; the pdf_ref backfill stays in hourly pdf_step.py, which skips its upload while the loop is alive,
restarts a dead loop (state/alerts/pdf_loop_dead.json) and maintains state/alerts/pdf_staging_over_6gb.json
(written by the loop as well while staging/pdf > 6 GB, removed once below).
