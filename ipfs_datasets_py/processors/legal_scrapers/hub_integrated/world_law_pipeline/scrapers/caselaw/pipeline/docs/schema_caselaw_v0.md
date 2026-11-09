# caselaw-raw/v0 (revised r2, 2026-10-28) -- Endomorphosis world-laws case law

Status: **v0, not frozen**. Revision r2 applies the 23 required changes of `$IPFS_DATASETS_LEGAL_WORKSPACE/normalizer/caselaw_review/review.md`
(Laws Normalizer). Replaces §6/§7 of `phase0_plan.md`. Code: `$CASE_LAW_ROOT/pipeline/caselaw_schema.py`
(`SCHEMAS`, `make_id`, `dedupe_id`, `cast_rows`, `validate_caselaw_table`, `validate_id_uniqueness`, `write_shard`; smoke test `python caselaw_schema.py`)
and `court_matcher.py`. Conforms to world-laws-raw/v1 (`$IPFS_DATASETS_LEGAL_COLLECTORS_ROOT/SCHEMA.md`) and world-courts-raw/v1 (`SCHEMA_COURTS.md`).
No shard is published to the Hub under v0 (S11). Courts dataset revision pinned: `ipfs_court_data@ef54093beb` (full `ef54093beb695b17e8a2676d287717b19aedc274`).

## Global rules
- One schema per record type: `decision`, `opinion`, `docket`, `citation_edge` (req 16, 17). Raw layer does NOT split to paragraphs (pinpoints belong to the IR layer).
- All text columns `pa.string()` (never `large_string`); `int64` for integers; dates/times are strings (req 7, 8, 9).
- zstd, row groups <= 4096 rows. Common 20-column prefix in courts order (S1/S2), type-specific columns, `metadata_json` last (NOT NULL).
- Parquet kv metadata (req 23): `schema=caselaw-raw/v0`, `record_type=<type>`, `schema_doc_version=caselaw-raw/v0-r2`, `layer=raw_caselaw`, `courts_dataset_revision=<full hash>`. Row column `schema_version` = `caselaw-raw/v0`.
- Unknown/source-specific fields are never widened into columns: folded into `metadata_json.extras` (extras already present win), like `cast_batch` (req 20). `celex`, `disposition`, `source_codes_raw`, `cap_filter_version` live there; `court_name_raw` stays first-class.
- Never invent ids or text: missing NOT NULL value => `cast_rows` raises (fail closed).

## Ids (req 4, 5, 6)
- `id = wc1:<record_type>:<sha256("<source_name>|<source_record_id>")[:24]>` (record_type in decision/opinion/docket/citation_edge). `source_name` is hashed so two sources cannot collide.
- `source_id` is renamed: **`source_name`** = stable source key (e.g. `nl_rechtspraak`, `cjeu_cellar`) and is the value hashed; **`source_type`** = collector tag (e.g. `nl_rechtspraak_api`, `..._archive` for replay) (S5). `source_record_id` = native id (ECLI, CELEX, cluster id, uri) (NOT NULL).
- Duplicate rule (fix1, `ID_RULE=repo_unique_v1`): ids must be unique across all shards (`validate_id_uniqueness`). A later duplicate gets `wc1:<type>:sha256(old_id|<phase>)[:24]` (`dedupe_id`) with `metadata_json.id_original` and `metadata_json.id_rule="repo_unique_v1"`. NOT NULL `phase` (ingest batch label, e.g. `phaseA`) and `source_file` (shard / bulk file name) carry the needed context.
- opinion `decision_id` = FK to `decision.id`; edge `citing_id`/`cited_id` = deterministic ids (cited decision may not be ingested yet).
- `canonical_key` (decision, optional): normalised ECLI / neutral citation for cross-source dedupe; ids stay distinct per source (S6).

## Court join (req 1, 2, 3)
- `court_entity_key`: **only** `^wc1e:court:[0-9a-f]{24}$` or null. Never a provisional value.
- `court_key_provisional`: `wcc1:<ISO>:<admin1|->:<sha256(norm_name)[:16]>`, set iff `court_match_status != matched`.
- `court_match_status` (NOT NULL) in `matched | ambiguous | unmatched`. Validator: matched => key non-null and provisional null; ambiguous/unmatched => key null and provisional valid.
- `entity_key` is not a primary key and is source-specific (1,342 repeated keys; 420 of 2,107 name groups have several keys). The matcher joins to a **deduped court dimension**: group by (country_iso, admin1, normalised name); canonical key = `min(entity_key)` in the group; all keys in `metadata_json.court_entity_key_candidates`. Steps: exact (country, admin1, name) -> website host -> token fuzzy >= 0.92 (S3; never lower => matched). Tie => `ambiguous` with top-3 in metadata. `admin1=null` is valid for national courts.
- `metadata_json` carries `courts_dataset_revision`, `court_match_method`, `court_match_score`. `name` is null in 53% of court rows, and the table has no CH/BR/EU/DE rows, so expect a high `unmatched` rate (S7); a gap list is reported to the Courts agent, re-match after each Courts revision.

## Shared-field conventions
- Spelling: **`licence`** and **`retrieval_date`** (courts family; aliases for the laws normalizer: `license`<->`licence`, `retrieved_at`<->`retrieval_date`). `retrieval_date` = string `YYYY-MM-DD`. `licence` = licence text as published; `licence_class` (decision) = open / NC / gated (S4).
- `country_iso` upper-case alpha-2 (`EU` for EU bodies, `ZZ` supranational/international), NOT NULL. `jurisdiction_level` NOT NULL, exactly `national|state|regional|municipal|local` (no county/supra; raw word to metadata extras). `admin_level` int64 nullable (defaults national 2, state 4, regional 6, municipal 8, local 10). Supranational: `national`, admin_level 2. `admin1` ISO 3166-2 (`^[A-Z]{2}-[A-Z0-9]{1,3}$`, prefix == country_iso) or null; raw name to metadata. `jurisdiction_raw` NOT NULL (S1). `municipality`, `municipality_code` reserved.
- `fetch_mode` closed set: `live, wayback, commoncrawl, bulk, api, hf_dataset` (`wayback-cdx` -> `wayback`; no `derived:*`: provenance of derived rows goes in metadata). `source_url` nullable but required (or `found_on`) when mode is live/wayback/commoncrawl.
- Archive convention (req 14): `source_url` = ORIGINAL url; replay URL in `found_on`; `archive_cid` in `metadata_json`. No `wayback_url` column.
- Dates (req 8): `decision_date`, `filing_date`, `termination_date` strings `YYYY`, `YYYY-MM` or `YYYY-MM-DD` (validated incl. month/day ranges); `decision_year` int64 derived. No invented dates; unparseable values go to metadata.
- `language`: ISO-639-1 (ISO-639-3 only if no 2-letter code); regional variants in metadata (req 21).
- Citations (req 19): `ecli` validated `^ECLI:[A-Z]{2}:[A-Za-z0-9.]{1,7}:\d{4}:[A-Za-z0-9.\-]{1,25}$`; `neutral_citation`, `docket_number` strings; `other_citations` = JSON list of normalised strings only. Field map for the laws normalizer: `ecli`~`eli`, `neutral_citation`~`official_identifier`, `source_record_id`~`identifier`, `text`->IR `body`. `case_name`/`title` is NOT carried (see privacy).
- Text (req 22): opinion `text` is always plain text; `text_format` = SOURCE format (plain/html/xhtml/akn_xml/pdf); `text_sha256` = sha256 of UTF-8 `text` as stored (validated); raw-file hash goes to `metadata_json.source_sha256`. Empty text only if `metadata_json.text_missing` is true.

## Compliance and privacy (req 15, 18)
- First-class NOT NULL `restricted_ai_training` (bool) on every decision AND opinion row, set from robots Content-Signal / licence class (true when ai-train=no or NC-restricted). First-class `ocr` (bool; NOT NULL on opinion) and `text_backend` (string). Other flags (`terms`, `ocr_mean_conf`, `source_sha256`, `official_source_url`) in metadata_json.
- `parties_redaction_status` NOT NULL, closed: `source_pseudonymised | source_anonymised | as_published | unknown` (default `unknown` = treated as sensitive). Present on decision, opinion, docket.
- `sensitivity_flags` (decision, JSON list): criminal, family/juvenile, immigration, mental_health, sealed, tax. Rule: never ingest sealed / segredo-de-justica records; never de-anonymise or re-link pseudonymised parties (all sources).
- **No litigant-name columns** (no `case_name`, parties, plaintiff...). The validator rejects such column names; titles that embed party names are not stored; `metadata_json` must not hold party names/addresses/ID numbers.
- Judges: `judges_raw` = JSON list of {"name","role"} (optional `judge_entity_key`); optional `judge_entity_keys` = JSON list of `wc1e:judge:<hash>`.
- Takedown: tombstones keyed by stable `id` in `$CASE_LAW_ROOT/out/<source>/tombstones.jsonl` (ids withdrawn/removal-requested); consumers must drop them. FLP / CJEU removal policy honoured.

## Tables
### decision (case-level metadata, no text)
| # | column | type | null? |
|---|---|---|---|
| 1 | `id` | `string` | **no** |
| 2 | `record_type` | `string` | **no** |
| 3 | `schema_version` | `string` | **no** |
| 4 | `country_iso` | `string` | **no** |
| 5 | `jurisdiction_level` | `string` | **no** |
| 6 | `admin_level` | `int64` | yes |
| 7 | `admin1` | `string` | yes |
| 8 | `municipality` | `string` | yes |
| 9 | `municipality_code` | `string` | yes |
| 10 | `jurisdiction_raw` | `string` | **no** |
| 11 | `source_name` | `string` | **no** |
| 12 | `source_type` | `string` | **no** |
| 13 | `source_record_id` | `string` | **no** |
| 14 | `source_url` | `string` | yes |
| 15 | `found_on` | `string` | yes |
| 16 | `fetch_mode` | `string` | **no** |
| 17 | `retrieval_date` | `string` | yes |
| 18 | `licence` | `string` | yes |
| 19 | `phase` | `string` | **no** |
| 20 | `source_file` | `string` | **no** |
| 21 | `court_entity_key` | `string` | yes |
| 22 | `court_key_provisional` | `string` | yes |
| 23 | `court_match_status` | `string` | **no** |
| 24 | `court_name_raw` | `string` | yes |
| 25 | `docket_number` | `string` | yes |
| 26 | `decision_date` | `string` | yes |
| 27 | `filing_date` | `string` | yes |
| 28 | `decision_year` | `int64` | yes |
| 29 | `ecli` | `string` | yes |
| 30 | `neutral_citation` | `string` | yes |
| 31 | `other_citations` | `string` | yes |
| 32 | `canonical_key` | `string` | yes |
| 33 | `decision_type` | `string` | yes |
| 34 | `language` | `string` | yes |
| 35 | `judges_raw` | `string` | yes |
| 36 | `judge_entity_keys` | `string` | yes |
| 37 | `opinion_count` | `int64` | yes |
| 38 | `restricted_ai_training` | `bool` | **no** |
| 39 | `ocr` | `bool` | yes |
| 40 | `sensitivity_flags` | `string` | yes |
| 41 | `licence_class` | `string` | yes |
| 42 | `parties_redaction_status` | `string` | **no** |
| 43 | `metadata_json` | `string` | **no** |

### opinion (text units; FK first among type-specific columns)
| # | column | type | null? |
|---|---|---|---|
| 1 | `id` | `string` | **no** |
| 2 | `record_type` | `string` | **no** |
| 3 | `schema_version` | `string` | **no** |
| 4 | `country_iso` | `string` | **no** |
| 5 | `jurisdiction_level` | `string` | **no** |
| 6 | `admin_level` | `int64` | yes |
| 7 | `admin1` | `string` | yes |
| 8 | `municipality` | `string` | yes |
| 9 | `municipality_code` | `string` | yes |
| 10 | `jurisdiction_raw` | `string` | **no** |
| 11 | `source_name` | `string` | **no** |
| 12 | `source_type` | `string` | **no** |
| 13 | `source_record_id` | `string` | **no** |
| 14 | `source_url` | `string` | yes |
| 15 | `found_on` | `string` | yes |
| 16 | `fetch_mode` | `string` | **no** |
| 17 | `retrieval_date` | `string` | yes |
| 18 | `licence` | `string` | yes |
| 19 | `phase` | `string` | **no** |
| 20 | `source_file` | `string` | **no** |
| 21 | `decision_id` | `string` | **no** |
| 22 | `opinion_type` | `string` | yes |
| 23 | `author_raw` | `string` | yes |
| 24 | `text` | `string` | yes |
| 25 | `text_format` | `string` | yes |
| 26 | `page_count` | `int64` | yes |
| 27 | `language` | `string` | yes |
| 28 | `ocr` | `bool` | **no** |
| 29 | `text_backend` | `string` | yes |
| 30 | `text_sha256` | `string` | yes |
| 31 | `restricted_ai_training` | `bool` | **no** |
| 32 | `parties_redaction_status` | `string` | **no** |
| 33 | `metadata_json` | `string` | **no** |

### docket
| # | column | type | null? |
|---|---|---|---|
| 1 | `id` | `string` | **no** |
| 2 | `record_type` | `string` | **no** |
| 3 | `schema_version` | `string` | **no** |
| 4 | `country_iso` | `string` | **no** |
| 5 | `jurisdiction_level` | `string` | **no** |
| 6 | `admin_level` | `int64` | yes |
| 7 | `admin1` | `string` | yes |
| 8 | `municipality` | `string` | yes |
| 9 | `municipality_code` | `string` | yes |
| 10 | `jurisdiction_raw` | `string` | **no** |
| 11 | `source_name` | `string` | **no** |
| 12 | `source_type` | `string` | **no** |
| 13 | `source_record_id` | `string` | **no** |
| 14 | `source_url` | `string` | yes |
| 15 | `found_on` | `string` | yes |
| 16 | `fetch_mode` | `string` | **no** |
| 17 | `retrieval_date` | `string` | yes |
| 18 | `licence` | `string` | yes |
| 19 | `phase` | `string` | **no** |
| 20 | `source_file` | `string` | **no** |
| 21 | `court_entity_key` | `string` | yes |
| 22 | `court_key_provisional` | `string` | yes |
| 23 | `court_match_status` | `string` | **no** |
| 24 | `court_name_raw` | `string` | yes |
| 25 | `docket_number` | `string` | **no** |
| 26 | `filing_date` | `string` | yes |
| 27 | `termination_date` | `string` | yes |
| 28 | `parties_redaction_status` | `string` | **no** |
| 29 | `metadata_json` | `string` | **no** |

### citation_edge
| # | column | type | null? |
|---|---|---|---|
| 1 | `id` | `string` | **no** |
| 2 | `record_type` | `string` | **no** |
| 3 | `schema_version` | `string` | **no** |
| 4 | `country_iso` | `string` | **no** |
| 5 | `jurisdiction_level` | `string` | **no** |
| 6 | `admin_level` | `int64` | yes |
| 7 | `admin1` | `string` | yes |
| 8 | `municipality` | `string` | yes |
| 9 | `municipality_code` | `string` | yes |
| 10 | `jurisdiction_raw` | `string` | **no** |
| 11 | `source_name` | `string` | **no** |
| 12 | `source_type` | `string` | **no** |
| 13 | `source_record_id` | `string` | **no** |
| 14 | `source_url` | `string` | yes |
| 15 | `found_on` | `string` | yes |
| 16 | `fetch_mode` | `string` | **no** |
| 17 | `retrieval_date` | `string` | yes |
| 18 | `licence` | `string` | yes |
| 19 | `phase` | `string` | **no** |
| 20 | `source_file` | `string` | **no** |
| 21 | `citing_id` | `string` | **no** |
| 22 | `cited_id` | `string` | **no** |
| 23 | `depth` | `int64` | yes |
| 24 | `treatment` | `string` | yes |
| 25 | `metadata_json` | `string` | **no** |

## Validator (`validate_caselaw_table(t, kind)` -> list of problems)
Checks: exact column set/order and pinned dtypes; NOT NULL columns; kv metadata keys; id format `wc1:<kind>:<24hex>` and uniqueness (table; `validate_id_uniqueness(paths)` across shards); record_type/schema_version; country_iso; jurisdiction_level vocab; fetch_mode vocab; admin1 pattern + prefix; retrieval_date; source_url required for live/wayback/commoncrawl; metadata_json is a JSON object; court key regex and match-status consistency; redaction vocab; date regexes; ecli regex; language; JSON-list columns; `judge_entity_keys` pattern; opinion `decision_id`, `text_sha256` recomputed, non-empty text unless `text_missing`, `opinion_type` vocab; `decision_year` consistency; edge id format; no litigant-name columns.

## Output layout (S10)
Working layout `$CASE_LAW_ROOT/out/<source>/<record_type>/part-NNNN.parquet` (<= 4096 rows per row group; one decision shard directory and one opinion shard directory per source, plus `manifest.jsonl`, `unmatched_courts.json`). Hub-compatible mapping later: `data/<record_type>/part-NNNN.parquet`.

## Review item status
Required 1-23: all applied. Optional: S1, S2, S3, S4, S5, S6, S7, S8, S10, S11 applied; S9 (no embedding placeholders) applied. Judgement calls for the Normalizer to confirm: (a) both `source_name` (hashed source key) and `source_type` (collector tag) are kept since the review text and the rename instruction differ; (b) `docket_number` stays on `decision` (case identifier, not a litigant name) in addition to the `docket` table; (c) `retrieval_date` pinned as date-only `YYYY-MM-DD`; (d) `restricted_ai_training` is NOT NULL on decision and opinion.
