# World-laws dataset schemas (pinned)

Status: pinned 2026-10-10 (PT). Code: [`schema.py`](schema.py) (`RAW_LAWS_SCHEMA`, `RAW_ARTICLES_SCHEMA`,
`IR_CORPUS_SCHEMA`, `cast_batch`, `cast_table`, `validate_table`, `validate_ir_schema`).
Evidence: parquet footers of all 240 `endomorphosis/ipfs_*_laws` repos and 217 `justicedao/ipfs_*_laws_ir`
repos on 2026-10-10 (`lane_ws1/footers_full.json`, `lane_ws1/ir_footers.json`).

Two layers:

1. **Raw layer** `endomorphosis/ipfs_<slug>_laws` — what collectors/packagers (`world_package.py`,
   `country_laws_ir/raw_package.py`) write. One row per instrument (`laws`) and per article/section (`articles`).
2. **Normalized layer** `justicedao/ipfs_<slug>_laws_ir` — produced by the `country_laws_ir` normalizer
   (`country-laws-ir-graphrag/v1`, v0.5.0): CID-keyed retrieval units + BM25/graph/vector shards.

## 1. Raw layer — pinned schema (`world-laws-raw/v1`)

Files: `data/laws.parquet` and `data/articles.parquet` (large repos may shard as `data/laws-00001.parquet` …;
sharded repos use identical columns). zstd compression, row groups <= ~4096 rows recommended.

### 1a. `laws` — 19 columns, this order, no others

| # | column | Arrow type | null? | meaning |
|---|---|---|---|---|
| 1 | `id` | `string` | **no** | stable instrument id (`<cc>-<slug>`); unique within a repo; never invented, empty/null fails validation |
| 2 | `title` | `string` | yes | instrument title (as extracted) |
| 3 | `text` | `string` | yes* | full text (*normalizer requires non-empty; packagers drop bodies < 80 chars) |
| 4 | `source_url` | `string` | yes | official URL the text came from (live or archive replay) |
| 5 | `source_type` | `string` | yes | collector tag, e.g. `tt_parliament_laws`, `..._archive` for Wayback/CC replays |
| 6 | `jurisdiction` | `string` | yes | ISO-3166 alpha-2 (e.g. `SV`) |
| 7 | `country` | `string` | yes | English country name |
| 8 | `language` | `string` | yes | ISO-639-1 code |
| 9 | `eli` | `string` | yes | European Legislation Identifier when one exists |
| 10 | `date` | `string` | yes | ISO-8601 text date (`YYYY-MM-DD`, or year) |
| 11 | `date_issued` | `string` | yes | ISO-8601 text date of enactment/issue |
| 12 | `retrieved_at` | `string` | yes | UTC timestamp `YYYY-MM-DDTHH:MM:SSZ` |
| 13 | `license` | `string` | yes | licence / attribution statement |
| 14 | `law_status` | `string` | yes | in-force / repealed / unknown (free text) |
| 15 | `identifier` | `string` | yes | collector-native identifier |
| 16 | `official_identifier` | `string` | yes | gazette/act number as officially cited |
| 17 | `article_count` | **`int64`** | yes | number of article rows for this law |
| 18 | `json_path` | `string` | yes | relative path of the source instrument JSON |
| 19 | `metadata_json` | `string` | yes | JSON object (string); see "extras" below |

### 1b. `articles` — 9 columns, this order, no others

| # | column | Arrow type | null? |
|---|---|---|---|
| 1 | `law_id` | `string` | **no** (FK to `laws.id`) |
| 2 | `id` | `string` | **no** (see note) |
| 3 | `title` | `string` | yes |
| 4 | `text` | `string` | yes |
| 5 | `source_url` | `string` | yes |
| 6 | `document_number` | `string` | yes |
| 7 | `article_number` | `string` | yes |
| 8 | `record_type` | `string` | yes (`article`, `section`, `law`, …) |
| 9 | `metadata_json` | `string` | yes |

Note: in several packs `articles.id` is **not** unique across the file (e.g. DO: 299,104 rows / 115,761 distinct ids;
SV 12,937/11,843; TT 12,588/8,304). The unique key is a row, not `id`; downstream code must not assume
`id` uniqueness for articles. The pinned schema does not change this (we do not rewrite ids), but new collectors should emit unique ids.

### 1c. Pinning rules (what drifted and how it is fixed)

Observed drift on the Hub (240 repos): 13 distinct `laws` column sets and 11 `articles` column sets;
`article_count` int32 x172 / int64 x67; text columns `string` x183 vs `large_string` x56 (laws), x205 / x28 (articles);
`eli` null-typed in 49 repos, `date` null-typed in 23, `date_issued` in 27. No repo mixes types between its own shards.

| drift | rule |
|---|---|
| `string` vs `large_string` | all text columns are `pa.string()` (32-bit offsets). Cast per batch (<= a few thousand rows) so no single array exceeds 2 GiB. |
| `int32` vs `int64` `article_count` | `pa.int64()`. |
| null-typed `eli`/`date`/`date_issued` (all-null columns written as `null` type) | cast to `string` (all-null string column). Collectors must always declare the schema when writing. |
| municipal / per-country extra columns (22 repos, 22–38 columns: `municipality_id`, `municipality_name`, `wikidata_qid`/`municipality_qid`, `gn_number`, `gazette_number`, `gazette_date`, `commencement_date`, `act_type`, `national_law_id`, …) | **not widened.** Folded into `metadata_json` under key `"extras"` (non-null values only), existing `metadata_json` keys preserved, existing `extras` win on key clash. `municipality_qid` is renamed `wikidata_qid`. `metadata_json` that is not valid JSON is kept as `{"_orig_metadata_raw": "<original>"}`. Nothing is dropped. |
| missing optional column | added as an all-null column of the pinned type. |
| missing required column (`laws`: id,title,text; `articles`: id,law_id,title,text) | `SchemaError` — fail closed, never invent ids. |

Usage (streaming, constant memory):

```python
import pyarrow.parquet as pq
from schema import RAW_LAWS_SCHEMA, cast_batch, validate_table
with pq.ParquetWriter("out/laws.parquet", RAW_LAWS_SCHEMA, compression="zstd") as w:
    for b in pq.ParquetFile("data/laws.parquet").iter_batches(batch_size=2048):
        t = cast_batch(b, "laws")
        assert not validate_table(t, "laws")
        w.write_table(t)
```

`pack_raw_for_ir.py` applies this to a whole (possibly sharded) Hub repo and produces a one-file local pack.

Compatibility: readers that selected columns by name keep working; readers that relied on municipal extra columns
must read them from `json.loads(metadata_json)["extras"]`. Existing Hub repos are **not** rewritten wholesale by this
doc; new/merged writes use the pinned schema (SV and TT were rewritten 2026-10-10 as part of the duplicate merge).

## 2. Normalized layer — `justicedao/ipfs_<slug>_laws_ir` (`country-laws-ir-graphrag/v1`)

Repo layout (v0.5.0, skillcenter-huggingface-release/v3): `README.md`, `manifest.json`, `dataset_configs.json`,
`normalization_report.json`, `data/corpus/part-NNNNNN.parquet` (<= 4096 rows/file), `data/bm25/**`,
`data/graph/**`, `data/vectors/**`, `indexes/`, a code snapshot (`country_laws_ir/`, `normalize.py`, `build.py`, `query.py`, `scripts/`) and `skill/`.

Retrieval unit = article/section row, with a law-level row fallback. `entry_cid` / `law_cid` = CIDv1 (raw, sha2-256, base32)
over canonical JSON; `entry_cid` is the primary key.

### 2a. `data/corpus` — 49 columns (current build; 184 of 217 Hub repos have exactly this)

`record_type, source_dataset, source_revision, source_id, instrument_id, instrument_title, law_id, law_cid,
article_number, article_title, title, body, body_sha256, jurisdiction, language, source_url, snapshot_date, coverage,
license, collector, schema_version, entry_identity_schema_version, eli, identifier, official_identifier, source_type,
country, law_status, parent_law_id, article_id, reconstructed_from_articles (bool), hierarchy_kind, hierarchy_path,
title_number, chapter_number, part_number, section_number, subsections (list<string>), official_citation,
bluebook_citation, cite_key, citation_status, pinpoint, entry_cid, title_length (int64), body_length (int64),
document_length (int64), document_index (int64), corpus_index (int64)`

All other columns are `string`. Required: `record_type, source_id, law_id, entry_cid, body, body_sha256, schema_version`.
Optional (3 repos built with the reconstruction pass → 54 columns): `reconstruction_truncated (bool),
reconstruction_gap_note, reconstruction_article_count (double), reconstruction_article_ids (list<string>),
reconstruction_article_sha256 (list<string>)`.
Field map from raw: `source_id←laws.id`, `body←text`, `license←license`, `law_status`, `eli`, `identifier`,
`official_identifier`, `jurisdiction`, `language`, `source_url`, `source_type`; article rows add `article_id←articles.id`,
`article_number`, `parent_law_id←articles.law_id`.

Observed IR drift (2026-10-10, 217 repos): column counts 49 x184, 36 x19 (pre-citation/hierarchy builds), 48 x5, 54 x3, 37 x3, 43 x3;
`string` vs `large_string` in 22 repos; `subsections` `list<null>` in 15 repos. The 36/37/43/48-column repos predate the current
normalizer and are *stale builds* — rebuild them with the current code (`python -m country_laws_ir reindex --renormalize`, needs a
shard-aware raw pack for sharded sources, see `pack_raw_for_ir.py`). `schema.validate_ir_schema()` reports which.

### 2b. Known normalizer limitation fixed by `pack_raw_for_ir.py`

`country_laws_ir.normalize.load_source` / `_pick_repo_file` read only `data/laws.parquet` and `data/articles.parquet`.
Raw repos named `data/laws-0000N.parquet` (even single-shard ones) therefore could not be normalized from the Hub: of the 23 such repos
(22 municipal sets + `uk`, 3 shards) only `uk` has an `_ir` repo (built from a local pack); the 22 municipal sets have none. `pack_raw_for_ir.py` merges shards through the pinned schema into a one-file local pack with
`pack_meta.json` (`slug`, `repo`, `source_revision`) that `python -m country_laws_ir build --source-repo <dir>` accepts.
A native fix would make `_pick_repo_file` return all matching shards and concatenate them (see `normalizers/shard_support.patch`).

### 2c. Vectors

`gte-small` 384-d embeddings need torch/sentence-transformers (+GPU in practice). Builds without an encoder write a
*stub* vector layer (`manifest.vector.assignment == "stub"`); `country_laws_ir coverage --gaps` reports these as `stub_vectors` so a GPU
host can fill them in later without re-normalizing.

## 3. Municipal / sub-national variant — `MUNICIPAL_LAWS_SCHEMA` (`world-laws-municipal/v1`)

Repos: `endomorphosis/ipfs_<slug>_municipal_laws`. `laws` = the 19 pinned raw columns **plus 7 first-class
jurisdiction columns** (appended in this order); `articles` = the unchanged 9-column `RAW_ARTICLES_SCHEMA` (join on `law_id`).

| column | type | null? | meaning |
|---|---|---|---|
| `jurisdiction_level` | string | **no** | one of `national, state, regional, municipal, local` |
| `admin_level` | int64 | yes | OSM-style level; defaults national 2, state 4, regional 6, municipal 8, local 10 |
| `country_iso` | string | **no** | ISO-3166 alpha-2, upper case |
| `admin1` | string | yes | first-level subdivision, ISO 3166-2 code preferred (`AT-2`, `ET-AA`) or name |
| `municipality` | string | yes* | municipality name as published (*required unless `municipality_code` is set, for municipal/local rows) |
| `municipality_code` | string | yes* | stable code: national statistical code (`at-gkz-20701`), else Wikidata QID |
| `source_body` | string | yes | issuing body (council, mayor, assembly) |

Helpers: `cast_municipal_batch(batch, default_level="municipal", country_iso=None)`, `validate_municipal_table(t)`,
`municipal_law_id(cc, municipality_code, native_id)`; smoke test in `python3 schema.py`.

### Mapping of existing municipal sets (legacy wide columns or `metadata_json.extras`, first non-empty wins)

| new column | taken from |
|---|---|
| `municipality` | `municipality_name`, `municipality_name_en/_fr/_sw` |
| `municipality_code` | `municipality_id`, `wikidata_qid`, `municipality_qid` |
| `admin1` | `province`, `region`, `state`, else `jurisdiction` when it is an ISO 3166-2 code (`AT-2`) |
| `source_body` | `issuer`, `issuer_organ`, `council_normalized`, `council` |
| `country_iso` | 2-letter prefix of `jurisdiction` (`AT-2`, `JO/JO-Q…`, `TN/TN-Q…`), else `country` if 2 letters |
| `jurisdiction_level` | `municipal`, but `national` when `jurisdiction` ends with `-national` (JO, SA) |
| `admin_level` | existing integer, else the default for the level (non-integer words such as Kenya's `county` stay in extras) |

Legacy columns are still kept in `metadata_json.extras`; nothing is dropped.
Dry run over the 16 local municipal packs (`lane_ws1/municipal_promotion_coverage.json`): `country_iso`, `municipality` and `municipality_code`
are ~100% filled everywhere, and all 16 validate except tunisia_municipal, where 64 of 4,734 rows lack both municipality and code.
`admin1` is filled only for AT, ET and ZA. `source_body` is filled only for AD and MT. All 192 saudi_arabia_municipal rows are `SA-national`, i.e. national, not municipal.
