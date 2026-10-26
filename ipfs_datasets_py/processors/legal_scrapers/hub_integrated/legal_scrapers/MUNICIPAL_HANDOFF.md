# Municipal handoff spec (Municipal Laws Scraper -> WS-1 normalizer)

Schema: `MUNICIPAL_LAWS_SCHEMA` in `schema.py` / `SCHEMA.md` §3 (also in `endomorphosis/legal_scrapers`).

## 1. File layout to hand over (one directory per country)
```
/workspace/legal-corpora/municipal/<slug>_municipal/
  data/laws-00001.parquet ...      # MUNICIPAL_LAWS_SCHEMA, zstd, <= ~50k rows or ~400 MB per shard
  data/articles-00001.parquet ...  # RAW_ARTICLES_SCHEMA (9 cols); omit if no article split
  scrapers/collect_<cc>_municipal.py (+ helpers it imports; no secrets, no absolute paths)
  MANIFEST.json   # {slug, country_iso, collector, built_utc, laws_rows, articles_rows, municipalities, sha256 per file, sources[]}
  README.md       # sources, licence/terms, coverage (municipalities covered / total), known gaps
  HANDOFF_READY   # empty marker written LAST
```
`<slug>` = existing country slug (e.g. `kenya`), so the repo becomes `endomorphosis/ipfs_<slug>_municipal_laws`.

## 2. Required columns (laws)
Must be non-empty: `id`, `title`, `text` (>= 80 chars of real text; no placeholders), `source_url` (official host or archive replay of one),
`retrieved_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `language`, `license`, `jurisdiction_level`, `country_iso`, and for municipal/local rows
`municipality` or `municipality_code` (both preferred). `article_count` is int64. Write with the pinned schema
(`pq.ParquetWriter(path, MUNICIPAL_LAWS_SCHEMA)`) or pass rows through `cast_municipal_batch`. Before handing over, `validate_municipal_table` must return `[]`.
No extra columns: put anything else in `metadata_json` (JSON object string), under `"extras"`.

## 3. Dedup / id rule
`id = municipal_law_id(country_iso, municipality_code, native_id)` -> `<cc>-mun-<municipality_code>-<native-id-slug>`, where
native_id is the body's own act/by-law number (else the canonical official URL path). Ids must be unique per repo and stable across re-scrapes.
Dedup order: same `id` -> keep newest `retrieved_at`; else same sha256(text) within one municipality -> keep one and record the
other URL in `metadata_json.extras.alt_urls`. Article rows: unique `(law_id, id)`, `id = <law_id>-art-<n>`.

## 4. Publish flow
1. Scraper writes the directory and `HANDOFF_READY`, then notifies the Watchdog.
2. **Verifier review**: schema validation, row counts, spot-checks of text against source URLs, licence/terms, and the secret scan of the scrapers. Verdict is written to `VERIFIED.json`.
3. WS-1 (us) uploads raw data to `endomorphosis/ipfs_<slug>_municipal_laws` as new commits, never deleting. Protected-pack countries need Chief of Staff sign-off first.
4. WS-1 builds the IR: `pack_raw_for_ir.py` -> `python -m country_laws_ir build --skip-vectors` -> verify (rows, unique `entry_cid`) -> new
   `justicedao/ipfs_<slug>_municipal_laws_ir`. Vectors are stubbed on CPU and filled later on a GPU host.
5. Collector code goes to `endomorphosis/legal_scrapers/scrapers/` after a secret scan. Status is logged in `NORMALIZER_STATUS.md`.
