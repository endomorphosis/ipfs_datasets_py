# Landed adapters

This file has one section for each adapter module on disk under `ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/`. Each source schema id below is copied from that adapter file. Where the adapter binds the id by reading another file, the bound value is the string the adapter requires that file to assign. Loading those eleven modules in this pass reproduced the ids quoted here.

This note does not report a live network fetch or a GraphRAG rebuild.

## Closed routes

`tests/unit/legal_scrapers/test_lcm_041_closed_national_routes.py` is the closed-route guard. Its source states that France's statute lookup is `collect_legi` and Germany's is `collect_gii`. It states that Belgium, Portugal, Lithuania, and Ghana have no "{country} statute route" phrase. The test source assigns:

| Key | Collector module |
| --- | --- |
| `fr` | `collect_legi` |
| `de` | `collect_gii` |
| `be` | `collect_be` |
| `pt` | `collect_pt` |
| `lt` | `collect_lt` |
| `gh` | `collect_gh` |

The test source asserts `catalog.BY_ISO["fr"][0].module` is `collect_legi` and `catalog.BY_ISO["de"][0].module` is `collect_gii`. It asserts each closed key resolves to the collector in that table. It asserts a closed collector row's summary does not contain `statute route`. It asserts no adapter module under `legal_corpus/adapters/` registers `collect_be`, `collect_pt`, `collect_lt`, `collect_gh`, `collect_lt_eseimas`, `collect_pt_1s_pdf`, `collect_pt_dre_archive`, or `collect_pt_ro_lt_archives`. These statements are copied from that test file.

## Country-laws IR

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/country_laws_ir_v1.py` emits `legal-corpus.law@1`.

Its source schema id is `SOURCE_SCHEMA_VERSION` `country-laws-ir-graphrag/v1`. The adapter requires `SCHEMA_VERSION` in `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py` to be that string. `REQUIRED_LAW_COLUMNS` bound from `country_laws_ir/schema.py` are `id`, `title`, `text`.

## Municipal HTML

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/world_municipal_v1.py` emits `legal-corpus.municipal-instrument@1`.

Its source schema id is `SOURCE_SCHEMA_FILE` and `SOURCE_SCHEMA_VERSION`, both `world_municipal/schema.py`. The adapter raises if that file assigns `SCHEMA_VERSION`. It requires `EXPECTED_COLUMNS` from that file to be these 19 names, in this order:

- `cid`
- `jurisdiction_id`
- `jurisdiction_name`
- `country`
- `doc_id`
- `regeling_id`
- `regeling_work_id`
- `doc_order`
- `title`
- `structural_path`
- `node_label`
- `html_title`
- `html`
- `text`
- `source_url`
- `xml_url`
- `date_effective`
- `date_modified`
- `retrieved`

## Pipeline schema 1.2.0

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/world_law_pipeline_v1.py` reads `hub_integrated/world_law_pipeline/schema.py`.

Its source schema id is `SCHEMA_VERSION` `1.2.0`. `SOURCE_SCHEMA_FILE` is `hub_integrated/world_law_pipeline/schema.py`. The adapter also binds `REPO_ID` `endomorphosis/world_municipal_law` and `NATIONAL_REPO_ID` `endomorphosis/world_national_law` from that schema file.

`DOC_TYPES` bound from that file are `code_section`, `ordinance`, `regulation`, `statute`, `gazette_act`, `decision`. The municipal-register labels the adapter requires are:

| Source label | Classification |
| --- | --- |
| `code_section` | `law` |
| `ordinance` | `law` |
| `regulation` | `regulation` |
| `statute` | `law` |
| `gazette_act` | `act` |
| `decision` | `not yet classified` |

`decision` stays `not yet classified`. An `iso_` key stays national-shaped.

## Regulation

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/regulation_v1.py` checks that the regulation kind exports `legal-corpus.regulation@1`.

Its source schema ids are the `SCHEMA_VERSION` strings in `_VERSIONED`:

| Section | Schema id | Path the adapter reads |
| --- | --- | --- |
| CFR | `cfr-annual-processor-v1` | `legal_scrapers/federal_scrapers/cfr_annual_processor.py` |
| CFR | `live-cfr-source-processor-v1` | `legal_scrapers/federal_scrapers/live_cfr_source_processor.py` |
| eCFR | `ecfr-crosscheck-processor-v1` | `legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py` |
| Federal Register | `federal-register-change-processor-v1` | `legal_scrapers/federal_scrapers/federal_register_change_processor.py` |
| Federal Register | `federal-register-sparse-graphrag-release-schema-v2` | `legal_data/federal_register_release_schema.py` |

The adapter refuses these fixture ids as source schema ids: `cfr-annual-fixture-v1`, `live-cfr-recipe-v1`, `ecfr-crosscheck-fixture-v1`, `federal-register-change-fixture-v1`.

It requires these paths to assign no `SCHEMA_VERSION`: `legal_scrapers/federal_scrapers/federal_register_scraper.py`, `legal_scrapers/regulation_version_tracker.py`, and `legal_scrapers/state_admin_rules_scraper.py`.

It refuses `STATUTE_SCHEMA_ID` `country-laws-ir-graphrag/v1`, `AUTHORITY_SCHEMA_ID` `patent-authority-sources-v1`, and `LAW_SOURCE_SCHEMA` `worldwide-legal-search.law-source@1`. A CFR fixture stays on its CFR schema id.

## Legislative act

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/legislative_act_v1.py` assigns `INTERFACE_ID` `legal-corpus.legislative-act@1`.

Its source schema ids are `ACT_SCHEMA_IDS`:

- `public-law-change-processor-v1` from `SCHEMA_VERSION` in `legal_scrapers/federal_scrapers/public_law_change_processor.py`
- `public-law-change-fixture-v1` from `FIXTURE_SCHEMA_VERSION` in that same file

The adapter rejects US Code schema ids `uscode-release-processor-v1`, `uscode-release-fixture-v1`, `uscode-sparse-graphrag-release-schema-v2`, and `publicus-ir-graphrag/v2`. It also rejects `patent-authority-sources-v1` and `1.2.0`. `us_code_scraper.py` assigns no `SCHEMA_VERSION`. The package prefixes `USHOUSE-USCODE-` and `USCODE-` are not act schema ids.

## US Code as law

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/us_code_v1.py` emits `legal-corpus.law@1`.

Its source schema ids are `USCODE_SCHEMA_IDS`:

| Name | Value | Path |
| --- | --- | --- |
| `SCHEMA_VERSION` | `uscode-release-processor-v1` | `legal_scrapers/federal_scrapers/uscode_release_processor.py` |
| `FIXTURE_SCHEMA_VERSION` | `uscode-release-fixture-v1` | `legal_scrapers/federal_scrapers/uscode_release_processor.py` |
| `SCHEMA_VERSION` | `uscode-sparse-graphrag-release-schema-v2` | `legal_data/uscode_release_schema.py` |
| `RELEASE_PROFILE` | `publicus-ir-graphrag/v2` | `legal_data/uscode_release_schema.py` |

`us_code_scraper.py` assigns no `SCHEMA_VERSION`. The package prefixes `USHOUSE-USCODE-` and `USCODE-` stay law and are not schema ids. The adapter refuses `public-law-change-processor-v1`, `public-law-change-fixture-v1`, `country-laws-ir-graphrag/v1`, `patent-authority-sources-v1`, and `1.2.0`.

## Caselaw Access Project

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_cap_v1.py` emits `legal-corpus.caselaw@1`.

Its source schema id is `CAP_SCHEMA_ID` `unversioned`. The adapter raises if `legal_scrapers/caselaw_access_program/vector_search_integration.py` assigns `SCHEMA_VERSION`. The dataset id in that adapter is `justicedao/Caselaw_Access_Project_embeddings`, and the adapter raises if that dataset id is bound as the schema id. The source name is `cap`.

## France DILA

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_dila_v1.py` emits `legal-corpus.caselaw@1`.

Its source schema id is `DILA_SCHEMA_ID` `unversioned`. The adapter raises if `legal_scrapers/national_collectors/collect_fr_dila.py` assigns `SCHEMA_VERSION`. `LEGI_MODULE` in the adapter file is `collect_legi`. The source name is `dila`. The adapter raises if the DILA collector or this adapter defines `collect_legi`, and if the catalog DILA row replaces `collect_legi`.

The DILA/LEGI split is stated by `tests/unit/legal_scrapers/test_caselaw_dila_adapter.py` in `test_dila_rows_keep_the_schema_id_and_legi_route`. That test source asserts:

- `collect_fr_dila.py` assigns no `SCHEMA_VERSION`
- `collect_legi` is not a function of the DILA collector or of this adapter
- `get_national_collector("fr")` has module `collect_legi` and filename `collect_legi.py`
- `catalog.BY_ISO["fr"][0].module` is `collect_legi`
- `catalog.BY_ISO["fr"]` also contains module `collect_fr_dila`
- when `catalog.get` exists, `get("fr")` is `collect_legi`
- `DILA_SCHEMA_ID` is `unversioned` and equals the caselaw kind's `SOURCE_SCHEMA_IDS["dila"]`
- `LEGI_MODULE` is `collect_legi`
- `FONDS["CASS"]` is `fr_cass` and is not `DILA_SCHEMA_ID`
- the emitted `source_dataset` is `legal_scrapers/national_collectors/collect_fr_dila.py` and does not contain `collect_legi`
- a row whose `source_schema_id` is `collect_legi` is rejected

The adapter binds `FONDS` from `collect_fr_dila.py`. The loaded map is `CASS` `fr_cass`, `CAPP` `fr_capp`, `JADE` `fr_jade`, `CONSTIT` `fr_constit`, `INCA` `fr_inca`.

## Germany Rechtsprechung im Internet

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_rii_v1.py` emits `legal-corpus.caselaw@1`.

Its source schema id is `RII_SCHEMA_ID` `unversioned`. The adapter raises if `legal_scrapers/national_collectors/collect_de_rii.py` assigns `SCHEMA_VERSION`. `GII_MODULE` in the adapter file is `collect_gii`. The RII module name in the adapter file is `collect_de_rii`. The source name is `rii`. The adapter raises if the RII collector or this adapter defines `collect_gii`, and if the catalog RII row replaces `collect_gii`. The adapter file says it does not start a GraphRAG or embedding job.

The RII/GII split is stated by `tests/unit/legal_scrapers/test_caselaw_rii_adapter.py` in `test_rii_rows_keep_the_schema_id_and_gii_route`. That test source asserts:

- `collect_de_rii.py` assigns no `SCHEMA_VERSION`
- `collect_gii` is not a function of the RII collector or of this adapter
- `get_national_collector("de")` has module `collect_gii` and filename `collect_gii.py`
- `catalog.BY_ISO["de"][0].module` is `collect_gii`
- `catalog.BY_ISO["de"]` also contains module `collect_de_rii`
- when `catalog.get` exists, `get("de")` is `collect_gii`
- `RII_SCHEMA_ID` is `unversioned` and equals the caselaw kind's `SOURCE_SCHEMA_IDS["rii"]`
- `RII_CONFIG` is `de_bund` and is not `RII_SCHEMA_ID`
- `RII_JURISDICTION` is `de`
- `GII_MODULE` is `collect_gii`
- the RII columns end in `rii_doknr`, `doctype`, `norm`, `config`
- the emitted `source_dataset` is `legal_scrapers/national_collectors/collect_de_rii.py` and does not contain `collect_gii`
- a row whose `source_schema_id` is `collect_gii` is rejected

Loading the adapter reproduced `RII_CONFIG` `de_bund` and `RII_JURISDICTION` `de`.

## RECAP

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_recap_v1.py` emits `legal-corpus.caselaw@1`.

Its source schema id is `RECAP_SCHEMA_ID` `unversioned`. The adapter raises if `legal_scrapers/recap_archive_scraper.py` assigns `SCHEMA_VERSION`. `SEARCH_SOURCE_NAME` is `recap_search`. `DETAIL_SOURCE_NAME` is `recap_detail`. The caselaw kind's `SOURCE_SCHEMA_IDS` for both of those names must be `unversioned`. Search rows keep the keys `search_recap_documents` writes, including `abstract`. Detail rows keep the keys `get_recap_document` writes, including nested `metadata`. Court identity stays the string on `court`, `court_full_name`, and metadata `court_id`. The adapter does not build `legal-corpus.court@1`. The court interface id it refuses as a RECAP schema id is `legal-corpus.court@1`.

## Court identity

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/court_v1.py` emits `legal-corpus.court@1`.

Its source schema id is `SOURCE_SCHEMA_ID`, read from `UNVERSIONED_SCHEMA_ID` in `ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/court_v1.py`. That kind file assigns `UNVERSIONED_SCHEMA_ID` `unversioned`. The adapter raises if `courts_common.py` or `upload_world_courts.py` assigns `SCHEMA_VERSION`. Loading the adapter produced `SOURCE_SCHEMA_ID` `unversioned`.

The adapter also binds `CASELAW_INTERFACE_ID` `legal-corpus.caselaw@1`, `STATUTE_SCHEMA_ID` `country-laws-ir-graphrag/v1`, and `WORLD_COURTS_REPO` `endomorphosis/world_courts`. Opinion text is left off the court row. A court row is not returned as caselaw.
