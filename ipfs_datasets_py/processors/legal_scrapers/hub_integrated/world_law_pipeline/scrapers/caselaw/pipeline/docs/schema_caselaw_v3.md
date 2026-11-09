# caselaw-raw/v0 (revision r5, 2026-10-29) -- Endomorphosis world-laws case law

File `schema_caselaw_v3.md` = **fourth review round** of the Laws Normalizer (`$IPFS_DATASETS_LEGAL_WORKSPACE/normalizer/caselaw_review/recheck_v2.md`; v2 answered `recheck_v1.md`, v1 answered `recheck_v0.md`).
The schema identifier is **unchanged and unfrozen**: row column `schema_version` and kv `schema` stay `caselaw-raw/v0`; the doc revision is
`caselaw-raw/v0-r5` (kv `schema_doc_version`). Supersedes `schema_caselaw_v2.md` (r4), `schema_caselaw_v1.md` (r3) and `schema_caselaw_v0.md` (r2), all kept on disk. **Where an older change list below differs from the r5 list, r5 wins.**
Code: `$CASE_LAW_ROOT/pipeline/caselaw_schema.py` (smoke + negative tests: `python caselaw_schema.py`), `cl_common.py`, `court_matcher.py`, `validate_out.py <source>...`.
Conforms to world-laws-raw/v1 and world-courts-raw/v1. No shard is published to the Hub under v0. Courts dataset revision pinned:
`ipfs_court_data@ef54093beb695b17e8a2676d287717b19aedc274`. The CAP exclusion is unchanged (no static.case.law, no CAP-derived data, no CourtListener Harvard/`U` records).

## Changes r4 -> r5 (recheck_v2 fixes)
1. **Pending review => restricted.** Any row with `metadata_json.terms.pending_legal_review=true` ships `restricted_ai_training=TRUE` until the review is done; validator rule: `pending_legal_review=true` with `restricted_ai_training=false` is rejected. CJEU rows (2,000 decisions + 2,000 opinions) were migrated to `restricted_ai_training=true`; `terms` evidence is kept so a reviewer can flip the flag after clearing it. CH (entscheidsuche) rows ship restricted=true for the same reason. NL stays `restricted_ai_training=false` (CC0, `pending_legal_review=false`). **Consumer rule: use only `restricted_ai_training=false` rows for AI-training; never ignore `terms.pending_legal_review`.**
2. **docket** gains `restricted_ai_training` (BOOL, NOT NULL, default true), so the NC/gated and pending rules apply to all three row tables (docket now 31 columns incl. that column; decision 44, opinion 34, citation_edge 25 unchanged).
3. **Party-key filter**: keys are NFKC-normalised, accents stripped (NFKD), lower-cased, separators/zero-width stripped, then substring-matched. New tokens: `partij, partei, titel, titre, eiser, verweerder, gedaagde, klager, beklagter, demandeur, defendeur, requerant, ricorrente, demandante, recorrente, rubrum, zaaknaam, debtor, creditor, witness, surname, otherside`. Generic `name`, `fullName`, `naam` match **only as a whole key**, so `courtName`/`fileName` stay legal. Full-width `ＰＡＲＴＹ` and `party\u200bName` are caught.
4. **Validator**: (a) `validate_cross` rejects a NULL decision `text_sha256` and checks that every opinion's `restricted_ai_training`, `licence_class` and `terms.pending_legal_review` equal its decision's; (b) `court_match_status=matched` rows require `metadata_json.court_entity_key_candidates` (non-empty, contains the key, key == min) and `courts_dataset_revision` == pinned; (c) `validate_out` now fully checks `summary.json` (`decisions_total_incl_resume`, `rows_total`, `shards_total`, `bytes_total`, `court_match`, `n_rejected_rows` vs `rejected_rows.jsonl`, `schema_doc_version`, `n_fails`/`fails`), `unmatched_courts.json` (country, `admin1` format, `status`, rows, provisional keys, revision, `schema_doc_version`, `match_stats_this_run` present), duplicate manifest paths, manifest `record_type` vs directory, and stray `.part-*`/`*.writing` files; (d) **calendar-valid dates**: `RE_DATE`/`RE_RDATE` (decision/filing/termination/retrieval dates, `terms.checked`, tombstone dates) reject `2026-02-31`, `2026-13-01`, non-leap `02-29`.
5. **job1_cjeu uses `SourceOut.add_pair`** (row-wise validation + `rejected_rows.jsonl`). `add_pair` now runs the full table validator and the decision/opinion flag-equality check before buffering, not just `cast_rows`. (Doc rev r4 item (h) is therefore true for all three collectors NL, CJEU, CH.)
6. **Case-name heuristic** adds ` contra `, ` c/ `, ` ./. `, ` -v- `, ` przeciwko `, ` proti `, ` mot `, ` mod `, ` против `, a trailing `, In re`; ` v/vs/c ` is no longer a hit when followed by a digit (`Case C 123/20`) and `Re`/`In re` need whitespace after (`Re-opened`). Still a heuristic on citation-like columns only.
7. **`court_match` in summary.json counts ALL shard rows (resumed included)**, computed from the shards (`court_match_from_shards`, `write_summary`); this run's matcher counters are `court_match_stats_this_run`. `unmatched_courts.json` is keyed on (country, admin1, name, status).
Not changed (open from recheck_v2 N6/N9/N10): mid-run validation (summary/unmatched are end-of-job files; `validate_out` is run after a job), per-table checks still report the first bad row for some column-consistency checks, and `level_for("")` makes an unnamed NL court `national` (documented, no data impact: `court_name_raw=NULL`).
Migration (nothing deleted): CJEU and NL r4 shards, manifests, summaries and unmatched files -> `out/<source>/superseded/r4/` (with `SUPERSEDED.md`), rewritten 1:1 as r5 by `migrate_r4_to_r5.py` (no refetch). Earlier superseded dirs: `superseded/r2` (CJEU), `superseded/r3` (CJEU, NL).

## Changes r3 -> r4 (recheck_v1 fixes; superseded where r5 differs)
1. **Party-key filter**: case-insensitive **substring** match on the key with separators/camelCase collapsed (`partyName`, `plaintiffName`, `CaseTitle`, `nameOfParties`, `name_of_case`, `litigantNames` all match; replaces the r3 whole-word regex). Tokens: `casename, casetitle, nameofcase, title, caption, party, parties, plaintiff, defendant, appellant, appellee, respondent, applicant, petitioner, claimant, complainant, litigant, accused, versus, opponent, victim, heading`; exact keys `vs`, `v`, `case`. Fails closed (e.g. `subtitle` is dropped too). `parties_redaction_status` is the only allow-listed match. Applies to column names and every `metadata_json` key at any depth; values under non-matching keys are not inspected.
2. **Citation case-name check widened**: ` v `, ` vs `, ` versus `, ` c. `, ` contre `, ` tegen `, ` gegen `, ` contro `, ` gegenüber `, ` ex parte `, `v.Name` / `c.Name`, and a leading `In re`, `Re`, `Matter of`, `Ex parte`. Heuristic on citation-like columns only (see fix 8). ECLI, CELEX, `C-123/20`, `[2020] UKSC 1` still pass.
3. **Unnamed courts / NL**: `job2_nl` no longer substitutes `unknown`; a missing creator passes `None` to the matcher (key path `unnamed|<source>|<ECLI court code>`) and stores `court_name_raw = NULL`. Fixtures: `pipeline/test_court_paths.py`.
4. **Language** = membership in the 184-code ISO-639-1 list (`ISO639_1` in code); 3-letter codes and non-members are rejected. A language without a 2-letter code is stored NULL with the ISO-639-3 code in `metadata_json.extras.language_639_3`.
5. **CJEU**: (a) every `restricted_ai_training=false` row requires boolean `metadata_json.terms.pending_legal_review` (validated; CJEU = `true`, NL = `false`), plus `terms.basis`, `terms.evidence_url` (http/https URL(s)) and `terms.checked`. (b) `licence_class` is `unknown` for CJEU (no verified licence text) instead of `open`; the licence string states the reuse basis. NL stays `open` (CC0, verified on data.overheid.nl). (c) `court_name_raw` is the exact string passed to the matcher ("Court of Justice of the European Union" / "General Court" / "Civil Service Tribunal"), so rows, `unmatched_courts.json` and the provisional key agree; `unmatched_courts.json` is now derived from all decision shards on disk.
6. **Licence consistency rule**: `licence_class` `NC` or `gated` requires `restricted_ai_training=true` (validated on all record types).
7. **`validate_out.py <source>...`** checks all 4 record types, id uniqueness within and across sources, decision/opinion cross-links, tombstones, `manifest.jsonl` (every live shard listed; rows and bytes match), `summary.json` (decision total == shard rows == opinion rows) and `unmatched_courts.json` (court set, row counts, provisional keys vs decision shards, courts-dataset revision). Terms and vocabulary checks count every bad row, not just the first.
8. **Text vs names**: case names are excluded from **metadata columns, `metadata_json` and citation-like columns only**. The opinion `text` is the judgment itself and may contain party names where the source does not pseudonymise (CJEU: `parties_redaction_status=unknown`); consumers must rely on `parties_redaction_status` and `sensitivity_flags`, not on the text being name-free.
9. **Hygiene**: `celex` moved to `metadata_json.extras.celex` (code now matches this doc); stale `sealed` comment removed from code (`sealed` is not a flag value; sealed records are never ingested); fixtures for matched / ambiguous (shared website host) / unmatched / unnamed court paths and negative tests for every new rule (`python caselaw_schema.py`, `python test_court_paths.py`).
Counts: CJEU = **2,000 decision rows including part-0000** (5-row smoke shard), not 1,995.
Existing r3 shards were not deleted: CJEU r3 -> `out/cjeu_cellar/superseded/r3/` (content migrated 1:1 to r4 by `migrate_r3_to_r4.py`, no refetch); the 24-row NL r3 smoke shard -> `out/nl_rechtspraak/superseded/r3/` (NL regenerated under r4); r2 CJEU shards remain in `superseded/r2/`.

## Changes r2 -> r3 (recheck_v0 fixes; superseded where r4 differs)
1. **Privacy keys** (fix 1): `RE_PARTY_KEY` = `case_name|casename|title|caption|party|parties|plaintiff(s)|defendant(s)|appellant(s)|respondent(s)|applicant(s)|petitioner(s)|claimant(s)|litigant(s)|accused|versus|vs`
   as whole word tokens, case-insensitive. Applied to (a) column names and (b) **every key at any depth of `metadata_json`** (incl. `extras`). `cast_rows` DROPS such keys
   (recording the dropped key paths, never values, in `metadata_json.privacy_dropped_keys`); the validator REJECTS any that remain. `parties_redaction_status` is the only allowed match.
   Case-name-free citations: `other_citations`, `canonical_key`, `court_name_raw`, `docket_number`, `neutral_citation` are rejected when a value looks like `A v. B` / `A vs B`
   (heuristic; r4 widened list: see r4 fix 2). Citation-only forms (ECLI, CELEX, `[2020] UKSC 1`, `410 U.S. 113`) pass. No exception is taken: case names are not stored in metadata or citations (opinion text is unmodified source text; see r4 fix 8).
2. **`restricted_ai_training` fail-safe** (fix 2): NOT NULL; `cast_rows` defaults a missing value to **TRUE**. `false` is accepted only with evidence in
   `metadata_json.terms = {"basis": <non-empty text>, "evidence_url": <url or list>, "checked": "YYYY-MM-DD"}` (validated on every false row). Robots `Content-Signal: ai-train=no`
   or a licence/NC restriction => true. Jobs record `terms` on decision and opinion rows.
3. **`parties_redaction_status`** (fix 3): defaults to `unknown` in `cast_rows` when missing (no more raise). Vocabulary `source_pseudonymised | source_anonymised | as_published | unknown`.
4. **Unnamed courts** (fix 4): `court_key_provisional = wcc1:<ISO>:<admin1|->:<sha256(basis)[:16]>`. Named court: basis = normalised name (same key across sources for the same
   (ISO, admin1, name)). **Unnamed court: basis = `unnamed|<source_name>|<discriminator>`** (discriminator = source-specific court code, e.g. CELEX court letter or ECLI court code),
   so unnamed courts of different sources/courts no longer collapse. If a collector supplies no discriminator the key falls back to `unknown` and is **non-unique** (documented fallback; do not join on it).
5. **Vocabularies** (fix 5), all validated: `opinion_type` = `lead | majority | concurrence | dissent | per_curiam | plurality | judgment | other`
   (`lead` = principal text where the source has no finer typing; `judgment` = the court's judgment text where the source types it (CJEU, NL uitspraak); `other` = e.g. NL *conclusie* of the Advocate General;
   decision-level `decision_type=advocate_general_opinion` carries that meaning). `text_format` = `plain | html | xhtml | xml | akn_xml | pdf` (`xml` kept: Rechtspraak XML;
   the stored `text` is always plain text). `decision_type` = `judgment | order | decree | ruling | advocate_general_opinion | other`. `licence_class` = `open | NC | gated | unknown`.
   `treatment` (citation_edge) = `cites | follows | applies | distinguishes | criticizes | overrules | other`. `sensitivity_flags` items = `criminal | family | juvenile | immigration | mental_health | tax`
   (`sealed` is not a valid flag: sealed records are never ingested).
6. **Tombstones** (fix 6): see "Tombstones" below; validator `validate_tombstone` / `validate_tombstones_file`.
7. **kv metadata** (fix 7): validator now checks `schema`, `record_type`, `schema_doc_version == caselaw-raw/v0-r5`, `layer == raw_caselaw`, `courts_dataset_revision == pinned full hash`.
8. **Canonical court key** (fix 8): `min(entity_key)` over a (country, admin1, normalised name) group is **revision-scoped**: it is only stable within one `courts_dataset_revision`
   (recorded in kv + `metadata_json`). A new Courts revision can add a lower key and change the canonical key; consumers must re-match (or map old->new via `court_entity_key_candidates`) after each Courts revision.
9. **Misc** (fix 9): `licence_class` is now NOT NULL (default `unknown`) on decision, opinion and docket; `decision.text_sha256` added (= `text_sha256` of the lead opinion; `validate_cross` checks it);
   `retrieval_date` stays nullable but is **required for live/wayback/commoncrawl** (validated) and always set by collectors; language rule (r4): membership in the ISO-639-1 code list required, 3-letter ISO-639-3 only when no
   2-letter code exists (`eng`, `nld`, `deu`... rejected); single judge-key name: **`judge_entity_keys`** (list aligned by index with `judges_raw`, elements `wc1e:judge:<24hex>` or null);
   `judges_raw` entries are exactly `{"name","role"}` (no per-entry key).

## Global rules
- One schema per record type: `decision`, `opinion`, `docket`, `citation_edge`. The raw layer does NOT split to paragraphs.
- All text columns `pa.string()`; `int64` for integers; dates/times strings.
- zstd, row groups <= 4096 rows. Common 20-column prefix in courts order, type-specific columns, `metadata_json` last (NOT NULL).
- Parquet kv metadata: `schema=caselaw-raw/v0`, `record_type=<type>`, `schema_doc_version=caselaw-raw/v0-r5`, `layer=raw_caselaw`, `courts_dataset_revision=<full hash>`.
- Unknown/source-specific fields are never widened into columns: folded into `metadata_json.extras` (after the privacy scrub).
- Never invent ids or text: a missing NOT NULL value with no documented default => `cast_rows` raises. Documented defaults: `restricted_ai_training=true`, `parties_redaction_status=unknown`, `licence_class=unknown`.

## Ids
- `id = wc1:<record_type>:<sha256("<source_name>|<source_record_id>")[:24]>`. `source_name` = stable source key (`nl_rechtspraak`, `cjeu_cellar`); `source_type` = collector tag; `source_record_id` = native id (ECLI, CELEX...).
- Duplicate rule `repo_unique_v1`: ids unique across shards (`validate_id_uniqueness`); later duplicate gets `dedupe_id` + `metadata_json.id_original`/`id_rule`.
- opinion `decision_id` = FK to `decision.id` (`validate_cross` checks orphans). Edge `citing_id`/`cited_id` = deterministic ids.
- `canonical_key` (decision, optional): normalised ECLI / neutral citation (citation form only, no case name).

## Court join
- `court_entity_key`: only `^wc1e:court:[0-9a-f]{24}$` or null. `court_key_provisional`: `wcc1:...` (see fix 4), set iff `court_match_status != matched`. `court_match_status` in `matched | ambiguous | unmatched`.
- Matching to a deduped court dimension (country, admin1, normalised name) -> canonical key `min(entity_key)` (revision-scoped, fix 8) -> candidates in `metadata_json.court_entity_key_candidates`. Order: exact, website host, fuzzy >= 0.92 (never lower => matched).
- The Courts table has no EU/NL/CH/BR/DE rows at the pinned revision: every Phase-A row is `unmatched` with a provisional key; `out/<source>/unmatched_courts.json` is the gap list for the Courts agent.

## Shared-field conventions
- `licence` = licence text as published; `licence_class` = `open|NC|gated|unknown`. `retrieval_date` string `YYYY-MM-DD`. `country_iso` upper-case alpha-2 (`EU`, `ZZ`). `jurisdiction_level` in `national|state|regional|municipal|local`; `admin_level` int64 nullable; `admin1` ISO 3166-2 or null.
- `fetch_mode` in `live, wayback, commoncrawl, bulk, api, hf_dataset`; `source_url` required for live/wayback/commoncrawl. Archive convention: `source_url` = original URL, replay URL in `found_on`.
- Dates `YYYY`, `YYYY-MM`, `YYYY-MM-DD`; `decision_year` int64 derived. `language` per fix 9. `ecli` regex-validated.
- Text: opinion `text` always plain text; `text_format` = SOURCE format; `text_sha256` = sha256 of stored UTF-8 `text`; raw-file hash in `metadata_json.source_sha256`.

## Compliance, privacy, terms
- `restricted_ai_training` (decision, opinion AND docket, NOT NULL), `ocr`, `text_backend` first-class. `metadata_json.terms` = evidence object (fix 2).
- Phase A terms evidence recorded: **NL Rechtspraak** -> data.overheid.nl dataset page: licence "Publiek domein", "XML CC-0 (1.0)", owner Raad voor de Rechtspraak (checked 2026-10-29), restricted_ai_training=false.
  **CJEU/EU Cellar** -> no CC licence verified for case-law; reuse basis = CURIA copyright notice ("You may reproduce the judicial decisions found in the case-law database", third-party caveat) + Commission Decision 2011/833/EU;
  no AI-training reservation found; `licence_class=unknown` (r4), **restricted_ai_training=TRUE (r5) while the machine flag `terms.pending_legal_review=true` stands**, pending human legal review of the third-party caveat (a reviewer may flip it to false afterwards). The earlier "CC-BY-4.0" label was never verified and is removed.
- Never ingest sealed / segredo-de-justica records. Never de-anonymise or re-link pseudonymised parties. Judges (public officials) may appear in `judges_raw`.
- CURIA robots.txt lists specific cases/dockets as disallowed: the CJEU job also skips CELEX `62014FJ0050`, `62014FJ0051` (denylist in code) and honours robots for all hosts.

## Tombstones
`$CASE_LAW_ROOT/out/<source>/tombstones.jsonl`, one JSON object per line. Required keys: `id` (`wc1:<type>:<24hex>`), `record_type` (== the type in `id`), `source_name`,
`action` (`drop` | `purge_text`), `reason` (`takedown_request | sealed | redaction_failure | source_withdrawn | licence_change | other`), `requested_date`, `tombstoned_date` (`YYYY-MM-DD`).
Optional: `requester_ref` (opaque ticket/ref, no personal data), `note`. No other keys. `drop` = consumers delete the row (and its opinions/edges); `purge_text` = keep metadata, null `text`
and set `metadata_json.text_missing=true`. Consumers must apply tombstones before use; files are append-only. None exist yet for Phase A.


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
| 38 | `text_sha256` | `string` | yes |
| 39 | `restricted_ai_training` | `bool` | **no** |
| 40 | `ocr` | `bool` | yes |
| 41 | `sensitivity_flags` | `string` | yes |
| 42 | `licence_class` | `string` | **no** |
| 43 | `parties_redaction_status` | `string` | **no** |
| 44 | `metadata_json` | `string` | **no** |

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
| 32 | `licence_class` | `string` | **no** |
| 33 | `parties_redaction_status` | `string` | **no** |
| 34 | `metadata_json` | `string` | **no** |

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
| 28 | `restricted_ai_training` | `bool` | **no** |
| 29 | `licence_class` | `string` | **no** |
| 30 | `parties_redaction_status` | `string` | **no** |
| 31 | `metadata_json` | `string` | **no** |

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

## Validator (`validate_caselaw_table(t, kind)` -> problems)
Exact column set/order and dtypes; NOT NULL; kv keys (5, values checked); id format/uniqueness; record_type/schema_version; country_iso; jurisdiction_level; fetch_mode; admin1; retrieval_date
(format; required for live/wayback/commoncrawl); source_url requirement; metadata_json object; **no party-name keys anywhere in metadata_json (r4 substring rule); NC/gated => restricted_ai_training=true; terms.pending_legal_review boolean when restricted=false; language in ISO-639-1; no `A v. B` in citation-like columns; `restricted_ai_training=false` needs terms**;
court key regex + status consistency; redaction vocab; **licence_class, decision_type, treatment, sensitivity_flags, opinion_type, text_format vocabularies**; date regexes; ecli; **language (ISO-639-1)**; JSON-list columns;
**judge_entity_keys (aligned, null-able)**, **judges_raw shape**; opinion `decision_id`, recomputed `text_sha256`, non-empty text unless `text_missing`; **decision `text_sha256` format**; `decision_year`; edge ids; no party-name column names.
**r5 additions**: pending_legal_review=true => restricted=true; docket flags; matched rows need candidates + revision; calendar-valid dates; `validate_cross` NULL decision hash + opinion/decision licence-flag equality; `validate_out` full summary/unmatched/manifest checks (see r5 list).
Separate: `validate_id_uniqueness(paths)`, `validate_cross(decision_paths, opinion_paths)` (orphans; decision.text_sha256 vs opinion), `validate_tombstones_file(path)`.

## Output layout
`$CASE_LAW_ROOT/out/<source>/<record_type>/part-NNNN.parquet` (+ `manifest.jsonl`, `unmatched_courts.json`, `summary.json`, optional `tombstones.jsonl`). Superseded shards live under
`out/<source>/superseded/<rev>/` with a `SUPERSEDED.md`; nothing is deleted. Resumable state: shard-based (`SourceOut`) + `$CASE_LAW_ROOT/pipeline/state/<source>.json`.

## Judgement calls for the Normalizer to confirm
(a) File named v3 but identifier kept `caselaw-raw/v0` (unfrozen), doc revision r5. (b) Case-name detection is a heuristic on citation-like columns, not on free text. (c) Unnamed-court provisional keys are
source-scoped (not shared across sources) by design. (d) `retrieval_date` stays nullable for bulk/api/hf_dataset rows. (e) CJEU rests on the CURIA reproduction notice + Decision 2011/833/EU; flagged for legal review.

(f) `unmatched_courts.json` is data-derived (all shards); `match_stats_this_run` is informational. (g) CJEU rests on the CURIA reproduction notice + Decision 2011/833/EU; `terms.pending_legal_review=true`, `licence_class=unknown`.
(h) Collector hygiene (r4, no schema change): `SourceOut.add_pair` validates each decision+opinion pair before buffering; failures go to `out/<source>/rejected_rows.jsonl` and are counted in `summary.json` fails, instead of aborting a shard flush. NL drops a docket number that looks like a case name (stored NULL). Shards flush every 500 rows.

(i) r5: CJEU and CH ship `restricted_ai_training=true` while `pending_legal_review=true` (conservative; the evidence stays in `terms`). (j) Case-name exclusion applies to metadata/citation columns only; opinion `text` is unmodified source text.
