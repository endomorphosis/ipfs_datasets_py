# caselaw-raw/v0 (revision r7, 2026-10-29) -- Endomorphosis world-laws case law

File `schema_caselaw_v5.md` = **sixth review round** of the Laws Normalizer (`$IPFS_DATASETS_LEGAL_WORKSPACE/normalizer/caselaw_review/recheck_v4.md`; v4 answered `recheck_v3.md`; v3 answered `recheck_v2.md`, v2 answered `recheck_v1.md`, v1 answered `recheck_v0.md`).
The schema identifier is **unchanged and unfrozen**: row column `schema_version` and kv `schema` stay `caselaw-raw/v0`; the doc revision is
`caselaw-raw/v0-r7` (kv `schema_doc_version`). Supersedes `schema_caselaw_v4.md` (r6), `schema_caselaw_v3.md` (r5), `_v2.md` (r4), `_v1.md` (r3) and `_v0.md` (r2), all kept on disk. **Where an older change list below differs from the r7 list, r7 wins.**
Code: `$CASE_LAW_ROOT/pipeline/caselaw_schema.py` (smoke + negative tests: `python caselaw_schema.py`), `r6_rules.py` (data rules used by the collectors and the migrations; r7 adds `apply_r7`), `migrate_r6_to_r7.py`, `cl_common.py`, `court_matcher.py`, `validate_out.py <source>...`,
`test_regex_all4.py` (read-only regex/party-key scan of all four sources), `run_fixtures_r7.py` + `gen_fixtures_r7.py` (fixture runner, exact-message expectations, works under plain `python3`; see "Fixtures").
Conforms to world-laws-raw/v1 and world-courts-raw/v1. No shard is published to the Hub under v0. Courts dataset revision pinned:
`ipfs_court_data@ef54093beb695b17e8a2676d287717b19aedc274`. The CAP exclusion is unchanged (no static.case.law, no CAP-derived data, no CourtListener Harvard/`U` records).
**Four collectors** write Phase A shards, all through `SourceOut.add_pair`: `cjeu_cellar` (EU), `nl_rechtspraak` (NL), `ch_entscheidsuche` (CH) and `br_stj_dados_abertos` (BR). Table sizes: decision **45** columns, opinion **34**, docket **32**, citation_edge **25**.

## Changes r6 -> r7 (recheck_v4 fixes; local data and code only, nothing fetched)
Counts (unchanged by r7, decision = opinion rows): CJEU **2,000**, NL **2,880**, CH **1,936**, BR **912** (7,728). All four validate clean, individually and with the cross-source id check (`logs/validate_all4.r7.log`).
Migration (nothing deleted): the r6 shards, manifests, summaries and unmatched files of all four sources -> `out/<source>/superseded/r6/` (with `SUPERSEDED.md`; `rejected_rows.jsonl` copied), rewritten from those shards by `migrate_r6_to_r7.py` (no refetch). Manifest records carry `migrated_from: "r6"`; rewritten rows carry `metadata_json.r7_migration = {from, changes}`. Ids are unchanged (they depend only on source and record id). `summary.json` keeps `previous_r6_summary` and `r7_changes`.
1. **Dates (N-A)**. (a) The 20 CH `_nodate` rows (AR Obergericht/Kantonsgericht, BS Appellationsgericht) had been indexed by the source at **2021-01-01**; that default is a source artefact and is no longer used. The year is taken from the docket **only when unambiguous** (exactly one distinct 4-digit year in the docket, and a leading `XXX-YY-N` two-digit segment must agree with it): **12 rows** get that year as `decision_date=YYYY`, `decision_year=YYYY`, `date_precision=year` (e.g. `ARGVP 1988 3044` -> 1988, `VD.2016.97` -> 2016); **8 rows** get `decision_date=NULL`, `decision_year=NULL` and no `date_precision` (seven `O?x-YY-N` dockets with only a two-digit segment, and `O1Z-15-13 ARGVP 2018 3732`, whose two numbers disagree). Every one of the 20 carries `metadata_json.date_placeholder = {evidence: "source_id_nodate", original_decision_date: "2021-01-01", source_default: true, rule: "date_r7"}` plus `year_basis: "docket_year"` or `date_unknown: true`. The source-level flag is also in `summary.json` (`date_flags.nodate_source_default`). The ARGVP number in a docket is a publication-volume year, so for those rows the year is the docket's, not a verified decision year (hence year precision only).
(b) **Full dates recovered from the text** for BGE/ATF/DTF leading cases whose year-only or no-suffix date had a full date in the heading (`vom 29. Oktober 1875`, `du 9 juin ...`): only the first 700 characters are searched, only `vom|du|del|dal|am <day> <month> <year>` with a valid calendar day, and only if the year equals the year already known from the id. **6 rows** recovered (BGE 1 I 143 -> 1875-10-29, 32 II 682 -> 1906-11-10, 36 II 628 -> 1910-11-30, 72 I 194 -> 1946-11-08, 146 II 304 -> 2020-04-06, 147 III 393 -> 2021-07-01); they lose `date_precision`, keep the original in `date_placeholder.original_decision_date` and record `recovered_from_text = {snippet, offset, region: heading}`. The other old leading cases stay year precision (garbled OCR headings or no date in the heading).
(c) **12-31 check**: of the 3 CH rows dated `-12-31`, `AGVE-2002-155` and `PVG-2013-19` never state 31 December in the text and their ids carry the date as a year-end collection placeholder: they are now year precision (`date_placeholder.evidence = source_id_dec31_not_in_text`). `CD-2024-DO-1` (TA sports chamber) states 31 December 2024 in the text and is **unchanged**. This is a judgement call (flagged for the Normalizer).
(d) New validator rule: `metadata_json.date_placeholder`, when present, must carry known `evidence` and `original_decision_date`; a recovered date must be a full date without `date_precision`; a NULL `decision_date` needs `date_unknown=true` and a NULL `decision_year`. `decision_year` may now be NULL on those 8 rows.
2. **Fixture runner (N-B)**: `run_fixtures_r7.py` (a) runs under plain `python3` as well as the venv: the `ipfs_datasets_py` robots-gate import in `cl_common.py` is guarded (`ROBOTS_GATE_AVAILABLE`); only fetching needs the venv; (b) writes only under a run directory inside `$IPFS_DATASETS_LEGAL_WORKSPACE` (`testdata_r7/_runs/<timestamp>`, or `--run-dir`; refuses non-`$IPFS_DATASETS_LEGAL_WORKSPACE` paths, nothing under `/tmp`, nothing deleted); (c) compares the validator output with the EXACT expected message list stored in `expected.json` (`errors`), not a substring; (d) also checks the r7 data rules on in-memory copies. 32 parquet fixtures + 41 rule/`add_pair` checks.
3. **body_type (N-C)**, `r6_rules.body_type_for`, order for CH: CEDH (European Court of Human Rights, `court`; the Swiss rules never apply to it) -> mixed (`Andere Behörden und Gerichte`) and AG `Entscheide Grundbuch und Notariat` (**NULL**) -> **collection** (`Sammlung`/`Sammelwerk`, `Rechenschaftsbericht`, `Praxis des ...`/PVG, ARGVP) -> executive -> exact series names (`OG`, `N. Abteilung`, `Justizleitung` -> court; `Verwaltung` -> administrative_authority) -> court words -> judicial supervisory bodies (SchKG supervisory authorities, autorité de surveillance LP, autorité tutélaire -> court) -> lawyer/notary bodies (commission_or_regulator, both language twins) -> commission -> administrative -> NULL. Distribution CH r6 -> r7: court 1,412 -> 1,480; commission_or_regulator 155 -> 164; administrative_authority 151 -> 155; executive_body 60 -> 60; collection 38 -> 65; NULL 120 -> 12 (10 AG Grundbuch + the 2 not_decision rows). 135 rows changed. The 2 ZH rows (`ZH_SOBE_001_undefined_1998-08-10`, `..._2004-07-16`: UVEK/ASTRA guideline and explanatory documents) are flagged `metadata_json.not_decision = {reason, rule}` with `body_type` NULL (validator: not_decision needs a reason and NULL body_type). Rule-based, per court name, with the two per-row exceptions in `NOT_DECISION`.
4. **Party-key tokens**: added `Beschwerdegegner, apelante, resistente, querelant, imputato, convenuto` (as substring tokens: `beschwerdegegner`, `apelante`, `resistente`, `querelant`, `imputato`+`imputati`, `convenut`; `resistance`, `convention`, `apelacao`, `imputation` do not match). No existing key in the four sources matches (`test_regex_all4.py`: 0 hits).
5. **E-mail regex v2** (`RE_EMAIL`): Unicode local parts and domains, full-width / small commercial at (U+FF20, U+FE6B) and the spaced form `name @ domain` (exactly one space or NBSP on both sides). Rule label `email_v2` (`email_v1+email_v2` where a row had v1 redactions already). Rerun over all four sources: **0 additional addresses** were present (r6 had redacted NL 5 in 3 rows and CH 100 in 76 rows; those counts are unchanged); the validator and `test_regex_all4.py` now scan opinions with the v2 regex (0 hits). Deliberately NOT treated as addresses (documented non-matches): pseudonymisation placeholders such as `[e-mail adres] @gmail.com`, `[telefoonnummer] @s.whatsapp.net`, `@ [gebruikersnaam]` (no real local part), `ticker @ ct7`, a domain with an underscore, a domain without a dotted TLD. Hashes: nothing needed recomputing for e-mail (no new redaction), but the TG strip below changed 18 opinion hashes (decision `text_sha256` follows).
6. **TG boilerplate (N-C)**: the **18** Thurgau texts start with website navigation (`Skip to main content`, `Main navigation`, ... up to the `TVR yyyy` / `RBOG yyyy Nr. n` menu lines) and end with the site footer (`Obergericht / Verwaltungsgericht / Copyright Kanton Thurgau / Powered by Scroll Sites & Atlassian Confluence`). `strip_tg_nav` removes both; `text`, opinion `text_sha256` and decision `text_sha256` are recomputed; both rows record `metadata_json.boilerplate_stripped = {rule: tg_nav_v1, head_chars, tail_chars, original_text_sha256}`.
7. **Doc (N-F)**: one open-item list (see "Open items (r7)"); the r5 and r6 sections point to it. Bern/Berne is no longer an "open item"; it is a data note under "Judgement calls" (spelling in this file: **Bern**).
Open items (r7): (1) mid-run validation: summary/unmatched are end-of-job files and `validate_out` runs after a job; (2) some column-consistency checks report only the first bad row; (3) `level_for("")` makes an unnamed NL court `national` (harmless: 0 NULL court names in any source).
Fixtures: `testdata_r7/` (expected.json with exact messages), `testdata_r6/` and `testdata_r5/` are kept. Backups of the r6 code: `*_r6.py.bak`.

## Changes r5 -> r6 (recheck_v3 fixes; superseded where r7 differs)
1. **Docs (R3)**: this file has a section per collector (below: "Collectors"), the CH and BR terms evidence is recorded under "Compliance", the text says four collectors, and the `opinion_type` wording now matches the data: `lead` is *available* where a source has no finer typing, but CH and BR store `other` (the stored text is the source's single published text, not a typed opinion) and CJEU/NL store `judgment`.
2. **Label hygiene (R2)**: `docket_number` and `court_name_raw` are normalised (control characters and any whitespace run collapse to one space, leading/trailing whitespace and `\r` are stripped; placeholder strings `undefined, null, none, n/a, na, nan, unknown, -, --, ?, tbd, nil` (any case) become NULL). `cast_rows` does not alter them; **the validator rejects an un-normalised value** (`not normalised`). The original value is kept in `metadata_json.normalised_labels.<column>`. Data: CH 43 rows (the 40 dockets, 11 court names, the 2 `undefined` dockets, with overlaps) and NL 17 dockets were rewritten; the provisional court key is recomputed from the cleaned name (all affected rows are `unmatched`; a matched row with a changed name would raise). Row `wc1:decision:8f55402ab71f0aa6d07af15c` (`ZH_SOBE_001_undefined_2004-07-16`, German title "Erl\u00e4uterungen zum Ordnungsbussengesetz...") had `language=ro`; now `de` (opinion too), the change is in `metadata_json.language_correction`.
3. **Party keys and case names (R4/N1)**: new key tokens `partie, parte, recourant, beschwerdef\u00fchrer, autor, r\u00e9u, recorrido` (also matched in their accent-stripped / suffixed forms such as `Partes`, `Recourant_Name`, `Beschwerdef\u00fchrerin`, `autorName`, `reuName`). Short words (`parte`, `autor`, `reu`, `partie`) are matched as **whole words/camel-case tokens only**, not as substrings, so `department`, `autorite`, `preuve`, `reuters`, `partial`, `particle`, `authority`, `author_url`, `courtName` stay legal. Whole-word matching means a key such as `aparte` is legal (caveat). Case-name forms added: ` against `, ` x `, ` e `, ` y ` (in `RE_CASE_NAME_VALUE`, citation-like columns); ` e ` and ` y ` are **not** applied to `court_name_raw` (Italian/Spanish court names such as "Tribunale di Roma e Latina", "Tribunal Superior y Audiencia" are legal; `RE_COURT_NAME_CASE` = base forms only). They require whitespace on both sides and a non-digit, non-citation neighbour, so BGE/ATF cites (`BGE 116 V 182`, `ATF 140 V 12`, `BGE 133 V, E. 3`), `C-123/20 e 456` and `Art. 5 x 2` are not hits. `test_regex_all4.py` scans every metadata key path, citation-like column and court name of all four sources: **0 hits**.
4. **Pending rule, both ways (R6/pending)**: validator rules (all record types incl. docket): (a) `licence_class=unknown` requires `restricted_ai_training=true`; (b) `terms.pending_legal_review=true` requires `restricted_ai_training=true` (as r5); (c) the key `pending_legal_review` may exist **only** under `metadata_json.terms` (a top-level or nested `extras.terms`/`terms.sub` occurrence is rejected) and must be a boolean. Nothing was loosened: restricted=true stays valid in every case, no row changed its flag, `validate_cross` still requires decision/opinion equality, and **`add_pair` now also requires `terms.pending_legal_review` to be equal on decision and opinion**.
5. **E-mail redaction (R4/PII)**: every e-mail address (`RE_EMAIL`) in opinion text is replaced by `[email redacted]` (`cs.redact_emails`). Opinion `text_sha256` and the decision's `text_sha256` are recomputed; both rows record `metadata_json.contact_redaction = {emails_redacted, token, rule: email_v1, original_text_sha256}`; the decision gets sensitivity flag **`personal_contact`** (new member of the vocabulary). Validator: no unredacted address in opinion text; a `contact_redaction` count needs the token in the text; `validate_cross` requires the `personal_contact` flag exactly when the opinion carries `contact_redaction`. Data: NL 5 addresses in 3 rows, CH 100 addresses in 76 rows, CJEU/BR none. One CH pseudonymised placeholder `C@b_ag.com` (underscore in the domain, not a valid address) is left as published.
6. **Other fixes (R6)**: (a) new decision column **`body_type`** (STRING, nullable, after `court_name_raw`): `court | administrative_authority | commission_or_regulator | executive_body | collection` or NULL (not assessed; validated vocabulary). CJEU, NL and BR = `court`. CH is tagged by name rules in `r6_rules.body_type_for`: executive bodies (Regierungsrat, Bundesrat, Conseil f\u00e9d\u00e9ral, Regierungsstatthalter, Conseil d'\u00c9tat...), commissions/regulators (Wettbewerbskommission, Rekurs-/Aufsichtskommissionen...), administrative authorities, collections (Entscheidsammlung Baugesetzgebung, Sammelwerk); judicial supervisory bodies and mixed names are left NULL (see Collectors/CH). (b) Aruba, Cura\u00e7ao and Sint Maarten single-territory courts: `country_iso` AW / CW / SX (10 / 8 / 2 NL rows; `jurisdiction_raw` keeps the source value; level unchanged); the three joint courts naming several territories stay `NL`; the courts are still `unmatched` (the Courts table has no rows for them), keys recomputed under the new ISO. (c) **Fixture runner** `run_fixtures_r6.py` + `testdata_r6/` (19 parquet fixtures + `expected.json` with the expected outcome per fixture, plus `add_pair` behaviour tests: pending-flag mismatch rejected, e-mail redaction + flag, label cleaning, pending+unrestricted rejected); exit code 0 = all as expected. `gen_fixtures_r6.py` regenerates them from local CH rows. `testdata_r5/` is r5-shaped and kept for audit. (d) CH Jan-1 dates: 62 decisions whose `decision_date` was `YYYY-01-01` with evidence of a placeholder are now **`decision_date=YYYY` (year precision)** with `metadata_json.date_precision="year"` and `date_placeholder={evidence, original_decision_date}`. Evidence rule (`r6_rules.ch_year_precision`): the source record id ends in `_YYYY` only (32 rows) or `_nodate` (20 rows, additionally flagged `year_unverified=true`), or the id has no date suffix at all and no "1 January"-style date appears anywhere in the text (10 rows); a Jan-1 date confirmed by the text or by an id ending in a full date is kept. The validator rejects `date_precision=year` unless `decision_date` is `YYYY` (and the reverse).
Counts after the r6 migration (decision = opinion rows): CJEU **2,000**, NL **2,880**, CH **1,936**, BR **912** (7,728). All four validate clean (`logs/validate_all4.r6.log`; r7: `logs/validate_all4.r7.log`).
Open items as of r6 (superseded by the single r7 list at the top of this file): see "Open items (r7)".
Migration (nothing deleted): the r5 shards, manifests, summaries and unmatched files of all four sources -> `out/<source>/superseded/r5/` (with `SUPERSEDED.md`), rewritten from those shards by `migrate_r5_to_r6.py` (no refetch; `rejected_rows.jsonl` was **copied**, the live file stays). Manifest records carry `migrated_from: "r5"`; rewritten rows carry `metadata_json.r6_migration = {from, changes}`. Earlier superseded dirs are unchanged (`r2`..`r4`, BR `failed_run1`).

## Collectors
| source_name | source_type | country | fetch_mode | licence_class / restricted / pending | decision_type | opinion_type | rows |
|---|---|---|---|---|---|---|---|
| `cjeu_cellar` | cellar sparql/rest | EU | api | unknown / true / true | judgment etc. | judgment | 2,000 |
| `nl_rechtspraak` | rechtspraak open data | NL (AW/CW/SX for 20 rows) | api | open / false / false | judgment etc. | judgment (conclusie: other) | 2,880 |
| `ch_entscheidsuche` | `entscheidsuche_api` | CH | api | open / true / true | other | other | 1,936 |
| `br_stj_dados_abertos` | `ckan_dataset_json` | BR | **bulk** | open / true / true | judgment | other | 912 |
**CH `ch_entscheidsuche`**: the entscheidsuche.ch search API (`_search.php`, 114 court/series folders sampled, stratified ~19 rows per body, 273 distinct court names; federal rows have `admin1=NULL`/`national`, cantonal rows `CH-<canton>`/`state`). Text = the extracted attachment text (`text_backend=entscheidsuche_extracted`, plain); `decision_type=other` and `opinion_type=other` because the source does not type the decision. Language is the source's attachment language (de/fr/it). Excluded: user uploads (`*_UPL`), `Blockliste.json` ids, `/hidden`, `/archiv`. `body_type` separates courts from executive bodies, commissions and collections (distribution in the migration report). Federal and cantonal sources include non-court bodies (e.g. Regierungsrat, Wettbewerbskommission, Bundesrat) that ship under `court_name_raw` with `body_type` set accordingly.
**BR `br_stj_dados_abertos`**: Superior Tribunal de Justi\u00e7a "Espelhos de ac\u00f3rd\u00e3os - Terceira Turma" from the STJ open-data CKAN portal (`dadosabertos.web.stj.jus.br`), one monthly JSON (`20260131.json`, 912 decisions) already downloaded to `br_probe/` (one polite fetch with the 10 s crawl-delay; `/api/` disallowed and never used). `fetch_mode=bulk`, `source_url` = dataset page. Text = **ementa + decis\u00e3o (the "espelho"), not the full inteiro teor**, `text_backend=stj_json_ementa_decisao`, plain. `decision_type` = `judgment` for `AC*` types, `ruling` for decis\u00e3o types, else `other`; **`opinion_type=other`** (an espelho is a summary text, not a typed opinion). `docket_number` = `siglaClasse numeroProcesso`. `court_name_raw="Superior Tribunal de Justi\u00e7a"`, `country_iso=BR`, `national`, `language=pt`; the extras keep `classe, numero_registro, orgao_julgador, data_publicacao`. All rows restricted + pending (personal-data/anonymisation status not verified).

## Changes r4 -> r5 (recheck_v2 fixes)
1. **Pending review => restricted.** Any row with `metadata_json.terms.pending_legal_review=true` ships `restricted_ai_training=TRUE` until the review is done; validator rule: `pending_legal_review=true` with `restricted_ai_training=false` is rejected. CJEU rows (2,000 decisions + 2,000 opinions) were migrated to `restricted_ai_training=true`; `terms` evidence is kept so a reviewer can flip the flag after clearing it. CH (entscheidsuche) rows ship restricted=true for the same reason. NL stays `restricted_ai_training=false` (CC0, `pending_legal_review=false`). **Consumer rule: use only `restricted_ai_training=false` rows for AI-training; never ignore `terms.pending_legal_review`.**
2. **docket** gains `restricted_ai_training` (BOOL, NOT NULL, default true), so the NC/gated and pending rules apply to all three row tables (docket now 31 columns incl. that column; decision 44, opinion 34, citation_edge 25 unchanged).
3. **Party-key filter**: keys are NFKC-normalised, accents stripped (NFKD), lower-cased, separators/zero-width stripped, then substring-matched. New tokens: `partij, partei, titel, titre, eiser, verweerder, gedaagde, klager, beklagter, demandeur, defendeur, requerant, ricorrente, demandante, recorrente, rubrum, zaaknaam, debtor, creditor, witness, surname, otherside`. Generic `name`, `fullName`, `naam` match **only as a whole key**, so `courtName`/`fileName` stay legal. Full-width `ＰＡＲＴＹ` and `party\u200bName` are caught.
4. **Validator**: (a) `validate_cross` rejects a NULL decision `text_sha256` and checks that every opinion's `restricted_ai_training`, `licence_class` and `terms.pending_legal_review` equal its decision's; (b) `court_match_status=matched` rows require `metadata_json.court_entity_key_candidates` (non-empty, contains the key, key == min) and `courts_dataset_revision` == pinned; (c) `validate_out` now fully checks `summary.json` (`decisions_total_incl_resume`, `rows_total`, `shards_total`, `bytes_total`, `court_match`, `n_rejected_rows` vs `rejected_rows.jsonl`, `schema_doc_version`, `n_fails`/`fails`), `unmatched_courts.json` (country, `admin1` format, `status`, rows, provisional keys, revision, `schema_doc_version`, `match_stats_this_run` present), duplicate manifest paths, manifest `record_type` vs directory, and stray `.part-*`/`*.writing` files; (d) **calendar-valid dates**: `RE_DATE`/`RE_RDATE` (decision/filing/termination/retrieval dates, `terms.checked`, tombstone dates) reject `2026-02-31`, `2026-13-01`, non-leap `02-29`.
5. **job1_cjeu uses `SourceOut.add_pair`** (row-wise validation + `rejected_rows.jsonl`). `add_pair` now runs the full table validator and the decision/opinion flag-equality check before buffering, not just `cast_rows`. (Doc rev r4 item (h) is therefore true for all three collectors NL, CJEU, CH.)
6. **Case-name heuristic** adds ` contra `, ` c/ `, ` ./. `, ` -v- `, ` przeciwko `, ` proti `, ` mot `, ` mod `, ` против `, a trailing `, In re`; ` v/vs/c ` is no longer a hit when followed by a digit (`Case C 123/20`) and `Re`/`In re` need whitespace after (`Re-opened`). Still a heuristic on citation-like columns only.
7. **`court_match` in summary.json counts ALL shard rows (resumed included)**, computed from the shards (`court_match_from_shards`, `write_summary`); this run's matcher counters are `court_match_stats_this_run`. `unmatched_courts.json` is keyed on (country, admin1, name, status).
Open items as of r5 (superseded by the single r7 list at the top of this file): see "Open items (r7)".
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
   (`lead` = principal text where the source has no finer typing -- **no Phase A collector uses it** (r6); `judgment` = the court's judgment text where the source types it (CJEU, NL uitspraak); `other` = e.g. NL *conclusie* of the Advocate General, and **all CH and BR rows** (the text is a source extract/espelho that the source does not type);
   decision-level `decision_type=advocate_general_opinion` carries that meaning). `text_format` = `plain | html | xhtml | xml | akn_xml | pdf` (`xml` kept: Rechtspraak XML;
   the stored `text` is always plain text). `decision_type` = `judgment | order | decree | ruling | advocate_general_opinion | other`. `licence_class` = `open | NC | gated | unknown`.
   `treatment` (citation_edge) = `cites | follows | applies | distinguishes | criticizes | overrules | other`. `sensitivity_flags` items = `criminal | family | juvenile | immigration | mental_health | tax | personal_contact` (`personal_contact` r6: opinion text had e-mail addresses redacted)
   (`sealed` is not a valid flag: sealed records are never ingested).
6. **Tombstones** (fix 6): see "Tombstones" below; validator `validate_tombstone` / `validate_tombstones_file`.
7. **kv metadata** (fix 7): validator now checks `schema`, `record_type`, `schema_doc_version == caselaw-raw/v0-r7` (r7; r6 earlier), `layer == raw_caselaw`, `courts_dataset_revision == pinned full hash`.
8. **Canonical court key** (fix 8): `min(entity_key)` over a (country, admin1, normalised name) group is **revision-scoped**: it is only stable within one `courts_dataset_revision`
   (recorded in kv + `metadata_json`). A new Courts revision can add a lower key and change the canonical key; consumers must re-match (or map old->new via `court_entity_key_candidates`) after each Courts revision.
9. **Misc** (fix 9): `licence_class` is now NOT NULL (default `unknown`) on decision, opinion and docket; `decision.text_sha256` added (= `text_sha256` of the lead opinion; `validate_cross` checks it);
   `retrieval_date` stays nullable but is **required for live/wayback/commoncrawl** (validated) and always set by collectors; language rule (r4): membership in the ISO-639-1 code list required, 3-letter ISO-639-3 only when no
   2-letter code exists (`eng`, `nld`, `deu`... rejected); single judge-key name: **`judge_entity_keys`** (list aligned by index with `judges_raw`, elements `wc1e:judge:<24hex>` or null);
   `judges_raw` entries are exactly `{"name","role"}` (no per-entry key).

## Global rules
- One schema per record type: `decision`, `opinion`, `docket`, `citation_edge`. The raw layer does NOT split to paragraphs.
- All text columns `pa.string()`; `int64` for integers; dates/times strings.
- zstd, row groups <= 4096 rows. Common 20-column prefix in courts order, type-specific columns (decision 45 / opinion 34 / docket 32 / citation_edge 25 in r6 and r7), `metadata_json` last (NOT NULL).
- Parquet kv metadata: `schema=caselaw-raw/v0`, `record_type=<type>`, `schema_doc_version=caselaw-raw/v0-r7`, `layer=raw_caselaw`, `courts_dataset_revision=<full hash>`.
- Unknown/source-specific fields are never widened into columns: folded into `metadata_json.extras` (after the privacy scrub).
- Never invent ids or text: a missing NOT NULL value with no documented default => `cast_rows` raises. Documented defaults: `restricted_ai_training=true`, `parties_redaction_status=unknown`, `licence_class=unknown`.

## Ids
- `id = wc1:<record_type>:<sha256("<source_name>|<source_record_id>")[:24]>`. `source_name` = stable source key (`nl_rechtspraak`, `cjeu_cellar`, `ch_entscheidsuche`, `br_stj_dados_abertos`); `source_type` = collector tag; `source_record_id` = native id (ECLI, CELEX...).
- Duplicate rule `repo_unique_v1`: ids unique across shards (`validate_id_uniqueness`); later duplicate gets `dedupe_id` + `metadata_json.id_original`/`id_rule`.
- opinion `decision_id` = FK to `decision.id` (`validate_cross` checks orphans). Edge `citing_id`/`cited_id` = deterministic ids.
- `canonical_key` (decision, optional): normalised ECLI / neutral citation (citation form only, no case name).

## Court join
- `court_entity_key`: only `^wc1e:court:[0-9a-f]{24}$` or null. `court_key_provisional`: `wcc1:...` (see fix 4), set iff `court_match_status != matched`. `court_match_status` in `matched | ambiguous | unmatched`.
- Matching to a deduped court dimension (country, admin1, normalised name) -> canonical key `min(entity_key)` (revision-scoped, fix 8) -> candidates in `metadata_json.court_entity_key_candidates`. Order: exact, website host, fuzzy >= 0.92 (never lower => matched).
- The Courts table has no EU/NL(AW/CW/SX)/CH/BR/DE rows at the pinned revision: every Phase-A row is `unmatched` with a provisional key; `out/<source>/unmatched_courts.json` is the gap list for the Courts agent.

## Shared-field conventions
- `licence` = licence text as published; `licence_class` = `open|NC|gated|unknown`. `retrieval_date` string `YYYY-MM-DD`. `country_iso` upper-case alpha-2 (`EU`, `ZZ`; NL territories `AW`, `CW`, `SX`). `jurisdiction_level` in `national|state|regional|municipal|local`; `admin_level` int64 nullable; `admin1` ISO 3166-2 or null.
- `fetch_mode` in `live, wayback, commoncrawl, bulk, api, hf_dataset`; `source_url` required for live/wayback/commoncrawl. Archive convention: `source_url` = original URL, replay URL in `found_on`.
- Dates `YYYY`, `YYYY-MM`, `YYYY-MM-DD`; `decision_year` int64 derived. `language` per fix 9. `ecli` regex-validated.
- Text: opinion `text` always plain text; `text_format` = SOURCE format; `text_sha256` = sha256 of stored UTF-8 `text`; raw-file hash in `metadata_json.source_sha256`.

## Compliance, privacy, terms
- `restricted_ai_training` (decision, opinion AND docket, NOT NULL), `ocr`, `text_backend` first-class. `metadata_json.terms` = evidence object (fix 2).
- Phase A terms evidence recorded: **NL Rechtspraak** -> data.overheid.nl dataset page: licence "Publiek domein", "XML CC-0 (1.0)", owner Raad voor de Rechtspraak (checked 2026-10-29), restricted_ai_training=false.
  **CJEU/EU Cellar** -> no CC licence verified for case-law; reuse basis = CURIA copyright notice ("You may reproduce the judicial decisions found in the case-law database", third-party caveat) + Commission Decision 2011/833/EU;
  no AI-training reservation found; `licence_class=unknown` (r4), **restricted_ai_training=TRUE (r5) while the machine flag `terms.pending_legal_review=true` stands**, pending human legal review of the third-party caveat (a reviewer may flip it to false afterwards). The earlier "CC-BY-4.0" label was never verified and is removed.
  **CH entscheidsuche** -> entscheidsuche.ch `/dataUsage` ("Die ... Daten stehen allen Interessierten zur freien Benutzung und Weiterbearbeitung zur Verfuegung"; cite entscheidsuche.ch; voluntary donation for commercial use) and the API description PDF ("You are free to use the API and the cases in any way you want"); decisions are uncopyrighted under Art. 5(1)(c) URG; no AI/TDM reservation found; robots.txt allows `/_search.php` and `/docs` (checked 2026-10-29; evidence URLs `https://entscheidsuche.ch/dataUsage`, `.../pdf/EntscheidsucheAPI.pdf`, `.../robots.txt`). `licence_class=open`, but **restricted_ai_training=TRUE with `terms.pending_legal_review=true`**: anonymisation is done by the publishing courts and has NOT been verified per court (data-protection caveat; e-mail addresses are redacted since r6).
  **BR STJ Dados Abertos** -> licence field of the dataset page: "Licen\u00e7a Creative Commons Atribui\u00e7\u00e3o" (version not specified; link to opendefinition.org cc-by), attribution to STJ required; robots.txt crawl-delay 10 s, `/api/` disallowed (not used); evidence URLs = the dataset page and `robots.txt` (checked 2026-10-29). `licence_class=open`, **restricted_ai_training=TRUE, `pending_legal_review=true`** (personal-data/anonymisation status of the espelhos not verified; espelho = ementa + decis\u00e3o only).
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
| 25 | `body_type` | `string` | yes |
| 26 | `docket_number` | `string` | yes |
| 27 | `decision_date` | `string` | yes |
| 28 | `filing_date` | `string` | yes |
| 29 | `decision_year` | `int64` | yes |
| 30 | `ecli` | `string` | yes |
| 31 | `neutral_citation` | `string` | yes |
| 32 | `other_citations` | `string` | yes |
| 33 | `canonical_key` | `string` | yes |
| 34 | `decision_type` | `string` | yes |
| 35 | `language` | `string` | yes |
| 36 | `judges_raw` | `string` | yes |
| 37 | `judge_entity_keys` | `string` | yes |
| 38 | `opinion_count` | `int64` | yes |
| 39 | `text_sha256` | `string` | yes |
| 40 | `restricted_ai_training` | `bool` | **no** |
| 41 | `ocr` | `bool` | yes |
| 42 | `sensitivity_flags` | `string` | yes |
| 43 | `licence_class` | `string` | **no** |
| 44 | `parties_redaction_status` | `string` | **no** |
| 45 | `metadata_json` | `string` | **no** |

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
| 25 | `body_type` | `string` | yes |
| 26 | `docket_number` | `string` | **no** |
| 27 | `filing_date` | `string` | yes |
| 28 | `termination_date` | `string` | yes |
| 29 | `restricted_ai_training` | `bool` | **no** |
| 30 | `licence_class` | `string` | **no** |
| 31 | `parties_redaction_status` | `string` | **no** |
| 32 | `metadata_json` | `string` | **no** |

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
**r7 additions**: `not_decision` (object with reason, NULL body_type); `date_placeholder` shape (known evidence, recovered date = full date without `date_precision`, NULL date needs `date_unknown` and NULL year); e-mail check uses the v2 regex; six more party-key tokens. **r6 additions**: normalised `docket_number`/`court_name_raw` (no placeholders, no stray whitespace); `body_type` vocabulary; `date_precision` shape (`year` <=> `decision_date` is `YYYY`); no unredacted e-mail in opinion text and `contact_redaction` needs the token; `personal_contact` flag <=> `contact_redaction` (`validate_cross`); `licence_class=unknown` => restricted; `pending_legal_review` only under `terms`, boolean; party-key whole-word tokens; case-name forms `against`, `x`, `e`, `y`; `add_pair` compares `terms.pending_legal_review` between decision and opinion. Fixture runner: `python run_fixtures_r6.py`.

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
(a) File named v5 but identifier kept `caselaw-raw/v0` (unfrozen), doc revision r7. (b) Case-name detection is a heuristic on citation-like columns, not on free text. (c) Unnamed-court provisional keys are
source-scoped (not shared across sources) by design. (d) `retrieval_date` stays nullable for bulk/api/hf_dataset rows. (e) CJEU rests on the CURIA reproduction notice + Decision 2011/833/EU; flagged for legal review.

(f) `unmatched_courts.json` is data-derived (all shards); `match_stats_this_run` is informational. (g) CJEU rests on the CURIA reproduction notice + Decision 2011/833/EU; `terms.pending_legal_review=true`, `licence_class=unknown`.
(h) Collector hygiene (r4, no schema change; four collectors NL, CJEU, CH and BR use it): `SourceOut.add_pair` validates each decision+opinion pair before buffering; failures go to `out/<source>/rejected_rows.jsonl` and are counted in `summary.json` fails, instead of aborting a shard flush. NL drops a docket number that looks like a case name (stored NULL). Shards flush every 500 rows.

(i) r5: CJEU and CH ship `restricted_ai_training=true` while `pending_legal_review=true` (conservative; the evidence stays in `terms`). (j) Case-name exclusion applies to metadata/citation columns only; opinion `text` is unmodified source text.

(k) r6 (partly superseded by (n)): `body_type` NULL means 'not assessed' (judicial-supervisory names such as SchKG supervisory authorities, bare `OG`, `Verwaltung`, 'Andere Beh\u00f6rden und Gerichte', numbered BGer divisions are left NULL rather than guessed). (l) The three NL joint courts (Gemeinschappelijk Hof, Gerecht in Ambtenarenzaken x2) stay `country_iso=NL`. (m) Year-precision for CH is evidence-based; the 20 `_nodate` rows are re-dated in r7 (docket year or NULL, see r7 item 1). (n) r7: `body_type` is per court name (two per-row exceptions); NULL stays only for AG Grundbuch and the 2 not_decision rows; collections are checked before courts. (o) r7: 12-31 handling (AGVE-2002-155, PVG-2013-19 -> year precision; CD-2024-DO-1 kept) and the choice to leave docket-ambiguous `_nodate` rows NULL are judgement calls. (p) r7 data note, **Bern/Berne**: CH court names are stored as the source spells them (Bern in German, Berne in French/Italian/English: 15 CH-BE court names, 15 distinct after normalising the spelling = language variants of the same bodies); `court_name_raw` is never rewritten. Unifying them is left to the Courts-dimension match (a normalised-name key), not to the raw layer. This is a note, not an open item. (q) Open policy question, unchanged and not decided here: CJEU/CH/BR ship `restricted_ai_training=true` while `pending_legal_review=true`; whether pending should stay `restricted` is the user's decision.
