# world_municipal_law — schema & staging contract (v1.2.0)

Source of truth: `/workspace/world_law/pipeline/schema.py` (import it; don't copy constants).
Design: `/workspace/global_municipalities/WORLDWIDE_SCRAPE_PLAN.md` §1.2, §4.2.
Target Hub dataset: `endomorphosis/world_municipal_law` (NOT `american_municipal_law`).

```python
import sys; sys.path.insert(0, "/workspace/world_law/pipeline")
from schema import place_key, html_cid, validate_record, validate_file, html_schema
```
`place_key`, `html_cid`, `validate_record` need only the stdlib; `html_schema`/parquet
validation need pyarrow (`/workspace/hf-venv/bin/python`).

## 1. Staging contract for scraper bots (READ THIS)

1. **Where:** `/workspace/world_law/staging/<bot_name>/<CC>/<place_key>[.<batch>].jsonl`
   (`.parquet` with the same column names is also accepted). `<CC>` = ISO 3166-1 alpha-2,
   uppercase (`NL`, `US`, `EU` for EU-level law). `<place_key>` = `place_key(place_id)`, e.g.
   `wd_Q727`, `iso_FR`, `1008538`. `<batch>` is optional and free-form
   (`[A-Za-z0-9_-]`, e.g. a UTC timestamp `20261010T2200Z` or `part0003`).
   One place per file. Each line = one document (JSON object, UTF-8).
2. **Done marker = atomic rename.** Write to `<final name>.tmp` in the same directory, flush+fsync,
   close, then `os.rename()` to the final `.jsonl`/`.parquet` name. The uploader only reads
   `*.jsonl` / `*.parquet` and ignores `*.tmp`, dot-files and `_`-prefixed files/dirs. A renamed file is
   **final and immutable**: never append to or rewrite it. More docs for the same place later →
   a new file with a new `<batch>` suffix.
3. **Single writer:** each bot writes only inside its own `staging/<bot_name>/`. Never touch other bots'
   dirs, and never move/delete your own finished files: `run_loop.py` moves them to
   `/workspace/world_law/processed/<bot_name>/<CC>/` and bad rows go to
   `/workspace/world_law/quarantine/<bot_name>/<CC>/` with reasons. Your logs/scratch can live in
   `staging/<bot_name>/_anything` (ignored).
4. **Merge semantics:** rows are merged per place (across all bots) by `doc_id`; the **newest batch wins**.
   "Newest" = the UTC timestamp embedded in the batch name (`YYYYMMDDTHHMM[SS]Z` anywhere in it:
   `iso_FR.20261011T003234Zp0001`, `iso_FR.archive20261011T003234Zp0001`, `wd_Q1.full.20261010T2200Z`,
   `wd_Q1.full.archive-policy20261011T021231Z`, `wd_Q1.gyosei-p0001-20261011T0148Z`), else the file mtime;
   ties → part number (`pNNNN`/`bNNNN`), mtime, name. So always put a UTC timestamp in the batch name.
   To declare a file the *complete* current set for a place (drop every doc not in it, including docs in
   older batches and already-published files), put `.full` in the batch: `wd_Q727.full.20261010T2200Z.jsonl`.
   A `.full` batch replaces the **whole place**, not just the batch it supersedes.

Before renaming, run `validate_file(path)` (or `validate_record` per row); rows with errors are
quarantined, not uploaded.

## 2. Staged record (one JSON object per doc)

Required: `place_id, country_code, doc_id, source_platform, source_url, doc_type, language,
content_format, consolidated`, plus content (`html` or `text`) and a title (`html_title`,
`title_native` or `number`).

| field | type | notes |
|---|---|---|
| `place_id` | str | `gnis:<N>` (US) · `wd:Q<N>` (Wikidata, default for non-US places, as in `global_municipalities_candidate.csv`) · `iso:<CC>` (national) · `iso:<ISO 3166-2>` (subnational, e.g. `iso:US-CA`, `iso:DE-BY`) · `KG-kg_cbd:<organ id>` (KG only: Kyrgyz aiyl aimak councils without a Wikidata item, keyed by the CBD cbd.minjust.gov.kg issuing-organ id, `[0-9A-Za-z-]+`) |
| `country_code` | str | ISO 3166-1 alpha-2 uppercase (`EU` allowed for EU law) |
| `gnis` | str/null | US only, digits |
| `doc_id` | str | **stable** id from the source (CVDR id, ELI, CELEX, node id…). Unique per place. The CID depends on it, so never change how you build it |
| `doc_order` | int ≥0 | optional; defaults to the order in the file (then sorted by doc_order, doc_id) |
| `html_title` | str | optional; built from `title_native` if missing |
| `html` | str | optional if `text` given (pipeline wraps text in `<div class="chunk-content"><pre>…</pre></div>`) |
| `text` | str | plain text; derived from `html` if missing |
| `source_platform` | str | short slug, e.g. `nl_cvdr`, `pl_edziennik`, `jp_reiki_gyosei`, `eurlex`, `legislation_gov_uk` |
| `source_url` | str | http(s) URL of this doc |
| `doc_type` | enum | `code_section` · `ordinance` · `regulation` · `statute` · `gazette_act` · `decision` |
| `language` | str | BCP-47, lowercase primary tag (`nl`, `ja`, `pt-BR`) |
| `title_native` | str | title in source language |
| `number` | str | official number (e.g. `Ord. 2024-17`, `Dz.U. 2023 poz. 12`) |
| `adopted_date` / `published_date` / `effective_date` | str | ISO `YYYY`, `YYYY-MM` or `YYYY-MM-DD` |
| `in_force` | bool/null | null = unknown |
| `consolidated` | bool | `false` for gazette/as-published acts |
| `content_format` | enum | `html` · `xml` · `pdf_text` · `docx_text` (format of the *source*) |
| `retrieved_at` | str | ISO 8601 UTC `2026-10-10T22:00:00Z`; defaults to the file mtime |

Optional **provenance** fields (v1.1.0). Read from the top level, else `extra_metadata`, else
`extra_metadata.archive`. Published as columns:

| field | type | notes |
|---|---|---|
| `archive_source` | str | `wayback`, `commoncrawl`, … (null = live fetch) |
| `archive_crawl_id`, `archive_timestamp`, `archive_url`, `original_url` | str | archive capture provenance |
| `content_complete` | bool | `false` = metadata-only / partial record. **Valid** without `html`/`text` |
| `possibly_stale` | bool | |
| `source_policy` | str or list | crawl-policy tag, case-insensitive (see §2.1). Published lower-case, `;`-joined |
| `source_official` | bool | `false` = non-government mirror / aggregator |
| `source_org`, `license_note` | str | |

Every other key you stage (and every other key in `extra_metadata`) goes into the `extra_metadata`
column as a JSON string, so nothing is lost. `raw_path` / `raw_xml_path` (local file paths) are dropped
and never published.

### 2.1 Source policy: rows that are HELD (never published)
A row is held when (`schema.hold_reason()`):
* `source_policy` (top level or `extra_metadata`, case-insensitive, string or list) contains
  **`robots_unreachable`** or **`robots_disallowed`** (live fetches against an unreachable or disallowing
  robots.txt), or
* `robots_disallowed` (or `robots_txt_disallowed`) is true **and** the record is not archive-sourced
  (archive-sourced = any of `archive_source/archive_url/archive_timestamp/archive_crawl_id`, a
  non-empty `extra_metadata.archive`, or a `source_policy` starting with `archived_`).

These are allowed through and keep their `source_policy`: `noarchive_meta`, `archived_robots_disallowed`,
`robots_404_allow_rfc9309`, `robots_allowed_rfc9309`, `*_archive_fallback`, anything else, or no policy.
Held rows go to `/workspace/world_law/held/<bot>/<CC>/<file>.<run>.held.jsonl` with the full record and the
reason. They never reach `out/`, manifests, places.parquet or the card. A held `doc_id` is also removed from the
place if an older batch or an already-published file had it. A later batch can re-allow it, e.g. the
`robots_404_allow_rfc9309` re-emits.

### 2.2 Per-doc overrides
`/workspace/world_law/state/doc_overrides.json` → `{"quarantine": [{"country_code", "place_key",
"doc_id", "reason", "source_file"?}]}`. Matching rows (in any batch) are quarantined with the reason.

Optional **place-level** fields (put them on the first record, or every record; first non-empty wins;
they go to metadata JSON / `places.parquet`, not the parquet rows):
`place_name, qid, iso_3166_2, admin_level, state_code, platform, platform_place_id`.

Tiny example line (`staging/scraper_b/NL/wd_Q727.20261010T2200Z.jsonl`):
```json
{"place_id":"wd:Q727","country_code":"NL","doc_id":"CVDR123456_1","source_platform":"nl_cvdr","source_url":"https://lokaleregelgeving.overheid.nl/CVDR123456/1","doc_type":"regulation","language":"nl","title_native":"Algemene plaatselijke verordening Amsterdam","number":"CVDR123456","adopted_date":"2024-01-25","published_date":"2024-02-01","effective_date":"2024-02-02","in_force":true,"consolidated":true,"content_format":"xml","html":"<div class=\"chunk-content\"><p>Artikel 1 ...</p></div>","retrieved_at":"2026-10-10T22:00:00Z","place_name":"Amsterdam","qid":"Q727","iso_3166_2":"NL-NH","admin_level":"municipality","platform":"nl_cvdr","platform_place_id":"gm0363"}
```
Writing it:
```python
tmp = final.with_name(final.name + ".tmp")
with tmp.open("w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    f.flush(); os.fsync(f.fileno())
os.rename(tmp, final)
```

## 3. Jurisdiction levels / national & subnational law

| level | `admin_level` | `place_id` | `place_key` | file |
|---|---|---|---|---|
| supranational | `supranational` | `iso:EU` | `iso_EU` | `world_law/data/EU/iso_EU_html.parquet` |
| national | `country` | `iso:{CC}` | `iso_FR` | `world_law/data/FR/iso_FR_html.parquet` |
| 1st-level subdivision (state, Land, province, région…) | `adm1` | `iso:{ISO 3166-2}` | `iso_US-CA` | `world_law/data/US/iso_US-CA_html.parquet` |
| municipal & other local (incl. counties, districts) | label from candidate CSV (`municipality`, `county`, `township`, `district`, …) | `wd:Q…` (US: `gnis:N`) | `wd_Q90`, `1008538` | `world_law/data/FR/wd_Q90_html.parquet` |
| KG council without a Wikidata item | `municipality` | `KG-kg_cbd:<organ id>` | `KG-kg_cbd_<organ id>` | `world_law/data/KG/KG-kg_cbd_6284b63e72a046e7a44c73502293fa91_html.parquet` |

Rationale: ISO codes are deterministic (no Wikidata lookup needed), never collide with
`gnis:`/`wd:` keys, and US national/state law can't clash with GNIS-keyed US municipal files.
Put the country/state QID in the optional `qid` field. The `iso:` scheme is ONLY for country and
first-level subdivisions; every lower unit (even one with an ISO 3166-2 code, e.g. FR départements)
uses `wd:Q…` with `admin_level` `adm2`/`county`/`department`/… . US counties/municipalities keep `gnis:N`.
Places that are not in the candidate CSV (PL powiats → `county`, NL waterschappen → `water_board`, plus a few
municipalities the candidate list dropped) are listed in `pipeline/codes/place_additions.csv` with `wd:Q…` ids.
`KG-kg_cbd:<organ id>` (approved 2026-10-16) is the only non-Wikidata local scheme: Kyrgyz aiyl aimaks / councils
that have no Wikidata item, keyed by their CBD (cbd.minjust.gov.kg) issuing-organ id. Valid only with
`country_code` KG; the organ id must match `[0-9A-Za-z-]+` (no `_`, `.` or `:`), so `place_key`
(`KG-kg_cbd_<organ id>`) is filesystem-safe and maps back to the place_id unambiguously
(`schema.place_id_from_key`). The keys are municipal (never `iso_`, so they go to world_municipal_law) and KG is
not bucketed. They are listed in `place_additions.csv` (`official_code_system=kg_cbd_body`); when a Wikidata item
appears later its QID goes into the `qid` alias column and the `KG-kg_cbd:` place_id never changes.
`admin_level` is free text (not enforced by `validate_record`); `schema.KNOWN_ADMIN_LEVELS` lists the labels in use.

## 4. Published layout (in the dataset repo and under `/workspace/world_law/out/`)

```
world_law/data/{CC}/{place_key}_html.parquet      # ZSTD, schema below
world_law/metadata/{CC}/{place_key}.json
world_law/manifests/drop_{UTC ts}_manifest.jsonl  # one line per uploaded file, with sha256
world_law/places.parquet                          # crosswalk
README.md                                         # card: one config per country + default
```
No `_citation.parquet` for non-US places in v1 (Bluebook citations are US-only, §1.2.2).

### Hash buckets for big countries (HF limit: 10,000 files per folder)
Any country with more than 5,000 places is hash-bucketed (decided 2026-10-14; currently **FR, IT, DE**):
```
world_law/data/{CC}/{b}/{place_key}_html.parquet   (+ .s0001_html.parquet shards, same bucket)
world_law/metadata/{CC}/{b}/{place_key}.json
b = sha256(place_key.encode("utf-8")).hexdigest()[:2]   # "00".."ff", 256 buckets (~40 files each per 10k places)
```
The list lives in ONE place, `schema.BUCKETED_COUNTRIES`, and `schema.place_dir()` / `html_path()` /
`shard_path()` / `metadata_path()` are the single source of truth for every path (pipeline, out_store, prune,
evict). `iso_*` keys (world_national_law) are never bucketed. Readers accept both layouts
(`schema.place_dirs()`, `world_law_loader.layout_alternatives()`); the card's `data_files` list both
`data/{CC}/*_html.parquet` and `data/{CC}/*/*_html.parquet`. To bucket another country: add it to
`BUCKETED_COUNTRIES` and run `tools/migrate_buckets.py --cc XX` (Hub copy+delete in batched commits, then local
out/ tree, metadata `html_files` and `state/evicted_out.jsonl` rewritten), holding `state/run_loop.lock`.
run_loop's DIR_FULL check counts every dir (flat `data/{CC}/` and each bucket) and defers a place that would push
any of its dirs past 9,900 files.

### HTML parquet (34 columns, this order)
`cid, doc_id, doc_order(uint32), html_title, html` (the 5 US columns, unchanged, first) +
`place_id, country_code, gnis(null), source_platform, source_url, doc_type, language,
title_native, number, adopted_date, published_date, effective_date, in_force(bool|null),
consolidated(bool), content_format, text, retrieved_at` (v1.0.0, 22 columns) + v1.1.0 optional provenance
`archive_source, archive_crawl_id, archive_timestamp, archive_url, original_url, content_complete(bool),
possibly_stale(bool), source_policy, source_official(bool), source_org, license_note, extra_metadata(JSON str)`.
All other columns are strings. v1.0.0 files on disk/Hub are read with the new columns null.

### Sharding
A place over 20,000 rows or ~200 MB is written as `world_law/data/{CC}[/{b}]/{place_key}.s0001_html.parquet`,
`.s0002_…` (still matches `*_html.parquet`). Metadata has `html_files` + `n_shards`, and places.parquet has
`n_shards`, with `html_path` set to a `{place_key}.s*_html.parquet` glob. When a place is re-sharded or emptied,
the stale Hub files are deleted in the **same commit** as the new ones (`CommitOperationDelete`). Dry runs
write that plan to `planned_commit.jsonl`.

### CID
`cid = cid_v1_raw_sha256(f"{place_key}_{doc_id}.json")` (CIDv1, base32 `b…`, raw codec, sha2-256),
the same function the US pipeline uses. For US `place_key == gnis`, so US CIDs are byte-identical.

### Metadata JSON
`place_id, place_key, qid, gnis, country_code, iso_3166_2, admin_level, place_name, state_code
(optional, US), platform, platform_place_id, total_docs, total_sections (= total_docs, kept for
US catalog readers), last_updated (epoch ms), schema_version`.

### places.parquet
`place_id, place_key, qid, gnis, country_code, iso_3166_2, admin_level, place_name, platform,
platform_place_id, total_docs, html_path, metadata_path, last_updated`. Crosswalk platform ids →
place_id via the Wikidata national codes listed in plan §4.2.

### Manifest line
`path_in_repo, sha256, bytes, rows, place_id, place_key, country_code, source_files, built_at, schema_version`.

## 5. Uploader (`run_loop.py`; the single writer to the Hub dataset)
`/workspace/hf-venv/bin/python /workspace/world_law/pipeline/run_loop.py --once [--dry-run|--no-upload] [--workers N]`
picks up renamed staged files older than `--min-age` (5 s). It groups them per place, orders them (§1.4),
applies overrides and holds, normalizes and validates, spools rows to disk, and writes each place streaming
(sharded if large) into `/workspace/world_law/out/world_law/…`. It then uploads the changed files plus
places.parquet, the manifest and README, with stale-shard deletes in the same commit (≤500 ops each), and
moves the inputs to `processed/`. `--dry-run` writes everything (including `held/`, `quarantine/`,
`planned_commit.jsonl` and `summary.json`) under `state/dryrun_<ts>/` and touches nothing else. It keeps
a sha256 ledger in `state/ledger.jsonl` and holds a lock so only one instance runs. Each pass is logged to `state/runs.jsonl`.


## v1.2.0 — `pdf_ref` (2026-10-14)

One nullable string column appended after `extra_metadata` (35 columns):

* `pdf_ref` — `endomorphosis/world_law_scanned_pdfs:pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf` when the document's
  source is an image-only scanned PDF published in the scanned-PDF dataset, else null. `<b>` = first 2 hex of
  sha256(place_key) for `PDF_BUCKETED_COUNTRIES` (= `BUCKETED_COUNTRIES`: FR, IT, DE; never for iso_* keys).
* Bots never stage it. `tools/upload_pdfs.py` writes `state/pdf_refs/<CC>/<place_key>.json` ({doc_id: pdf_ref})
  after verifying the PDF's sha256 on the Hub; `run_loop.build_place` applies it to every (new or rebuilt) row
  of that place, and keeps an already-published `pdf_ref` otherwise.
* Existing places are backfilled by `tools/pdf_step.py` via `run_loop.py --rebuild-places-file` (only places
  that have PDFs). Files written before v1.2.0 lack the column: readers treat it as null
  (`world_law_loader` does).
* The PDF staging contract (OCR bot → `staging/pdf/`) is in `PDF_STAGING.md`.

## Pointer rows (duplicate checks for NEW rows, 2026-10-19)

`xdedup.py` (called from `run_loop.build_place`) checks every NEW staged row (a doc_id not yet published in
its place; already-published rows are never rewritten):

* **old_repo** (both repos): normalized `source_url` is in `state/dedup/old_urls.sqlite` (older
  endomorphosis/justicedao `ipfs_*_laws` + `ipfs_*_municipal_laws`). An `hf:` import is never matched
  against its own source repo (alias-insensitive, e.g. dominican_republic == dominicanrepublic).
* **cross_place** (world_municipal_law): same normalized URL or same normalized-text sha (>=200 chars) in a
  different place, published (`state/dedup/mun_published.sqlite`) or staged in the same run. Canonical:
  published copy > DE Amt/Verbandsgemeinde/Samtgemeinde/Verwaltungsgemeinschaft place > (PT
  diariodarepublica.pt) issuer named in the title > most specific admin level > smallest place_key. A new
  Amt row outranks a published member-Gemeinde row (new row kept; the published one is only counted).

Matched rows are KEPT as pointer rows (chosen over dropping: the place still lists the document, the
schema needs no new column, and the link to the full copy is explicit):
`text = null`, `content_complete = false`, `source_policy` += `duplicate_pointer`,
`extra_metadata` += `{"duplicate_of": "<repo>" | "<CC>/<place_key>/<doc_id>", "duplicate_check":
"old_repo"|"cross_place", "duplicate_key": "source_url"|"text_hash"}`. Every decision is logged to
`quarantine/_dedupe/<CC>/<place_key>.<run_id>.pointers.jsonl`. Modes per check in
`state/dedup/config.json`: `pointer` (default), `tag` (keep text), `skip` (drop), `off`.
URL normalization (`dedup_index.norm_url`): scheme dropped, host lower-cased, `www.`/default port dropped,
Wayback `web.archive.org/web/<ts>/` unwrapped, `;jsessionid` + tracking params (utm_*, fbclid, gclid, ...)
dropped, query sorted, fragment and trailing `/` dropped, path case kept.
