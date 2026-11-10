# Landed instrument modules

This file quotes the interface ids, kind names, and version strings exported by the landed kind modules. Each string is copied from the Python file cited on that line. Adapter modules and view modules are not described here.

`document_role.ROLES` and `LawStatus` were not replaced.

The eight modules below are on disk. None of these sections describes a module that is missing.

## Shared instrument

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/instrument_v1.py` assigns `INTERFACE_ID` `legal-corpus.instrument@1`.

That file assigns `KINDS`:

- `law`
- `regulation`
- `legislative_act`
- `caselaw`
- `court`
- `municipal_instrument`

`legal-corpus.status@1` is not one of those kind names.

## Law

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/law_v1.py` assigns `INTERFACE_ID` `legal-corpus.law@1`. The kind name is `law`.

`SOURCE_SCHEMA_VERSION` is `country-laws-ir-graphrag/v1`, copied from `SCHEMA_VERSION` in `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py`.

`VERIFY_SCHEMA_VERSION` is `country-laws-normalize-verify/v1`, copied from `SCHEMA_VERSION` in `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/verify.py`.

`REQUIRED_LAW_COLUMNS` is `id`, `title`, `text`, copied from `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/schema.py`.

## Regulation

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/regulation_v1.py` assigns `INTERFACE_ID` `legal-corpus.regulation@1`. The kind name is `regulation`.

`LAW_SOURCE_SCHEMA` is `worldwide-legal-search.law-source@1` in that kind file. A row that claims it is refused.

`STATUTE_SCHEMA_ID` is `country-laws-ir-graphrag/v1`, copied from `SCHEMA_VERSION` in `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py`. A row that claims it is refused.

`SOURCE_SCHEMA_IDS`, in register order, are copied from `SCHEMA_VERSION` in these files:

| Schema id | Path |
| --- | --- |
| `cfr-annual-processor-v1` | `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/cfr_annual_processor.py` |
| `live-cfr-source-processor-v1` | `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_cfr_source_processor.py` |
| `ecfr-crosscheck-processor-v1` | `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py` |
| `federal-register-change-processor-v1` | `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/federal_register_change_processor.py` |
| `federal-register-sparse-graphrag-release-schema-v2` | `ipfs_datasets_py/processors/legal_data/federal_register_release_schema.py` |

## Legislative act

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/legislative_act_v1.py` assigns `INTERFACE_ID` `legal-corpus.legislative-act@1`. The kind name is `legislative_act`.

`ACT_SCHEMA_IDS` are copied from `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/public_law_change_processor.py`:

- `SCHEMA_VERSION` `public-law-change-processor-v1`
- `FIXTURE_SCHEMA_VERSION` `public-law-change-fixture-v1`

`USCODE_SCHEMA_IDS` are the consolidation ids the kind refuses. They are copied from these assignments:

| Name | Value | Path |
| --- | --- | --- |
| `SCHEMA_VERSION` | `uscode-release-processor-v1` | `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/uscode_release_processor.py` |
| `FIXTURE_SCHEMA_VERSION` | `uscode-release-fixture-v1` | `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/uscode_release_processor.py` |
| `SCHEMA_VERSION` | `uscode-sparse-graphrag-release-schema-v2` | `ipfs_datasets_py/processors/legal_data/uscode_release_schema.py` |
| `RELEASE_PROFILE` | `publicus-ir-graphrag/v2` | `ipfs_datasets_py/processors/legal_data/uscode_release_schema.py` |

`USCODE_PACKAGE_PREFIXES` are `USHOUSE-USCODE-` and `USCODE-`, copied from the package strings written in `ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/us_code_scraper.py`. That scraper assigns no `SCHEMA_VERSION`.

## Caselaw

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/caselaw_v1.py` assigns `INTERFACE_ID` `legal-corpus.caselaw@1` and `UNVERSIONED_SCHEMA_ID` `unversioned`. The kind name is `caselaw`.

`SOURCE_SCHEMA_IDS` uses `unversioned` for every source below. Each of those files assigns no `SCHEMA_VERSION`:

| Source name | Path |
| --- | --- |
| `dila` | `ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_fr_dila.py` |
| `rii` | `ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_de_rii.py` |
| `cap` | `ipfs_datasets_py/processors/legal_scrapers/caselaw_access_program/vector_search_integration.py` |
| `recap_search` | `ipfs_datasets_py/processors/legal_scrapers/recap_archive_scraper.py` |
| `recap_detail` | `ipfs_datasets_py/processors/legal_scrapers/recap_archive_scraper.py` |
| `world_peachjam` | `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/scrapers/caselaw/peachjam.py` |
| `world_br_stj` | `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/scrapers/caselaw/br_stj.py` |
| `world_co_cc` | `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/scrapers/caselaw/co_cc.py` |
| `world_wayback` | `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/scrapers/caselaw/wayback_generic.py` |

`CAP_DATASET_ID` is `justicedao/Caselaw_Access_Project_embeddings`, copied from `CAPVectorSearchConfig.dataset_id` in `ipfs_datasets_py/processors/legal_scrapers/caselaw_access_program/vector_search_integration.py`.

`WORLD_REPO` is `endomorphosis/world_caselaw`, copied from `REPO` in `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/upload.py`. That upload file assigns no `SCHEMA_VERSION`.

## Court

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/court_v1.py` assigns `INTERFACE_ID` `legal-corpus.court@1` and `UNVERSIONED_SCHEMA_ID` `unversioned`. The kind name is `court`.

`SOURCE_SCHEMA_ID` is `unversioned`. These files assign no `SCHEMA_VERSION`:

- `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py`
- `ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/upload_world_courts.py`

`WORLD_COURTS_REPO` is `endomorphosis/world_courts`, copied from `DS` in `upload_world_courts.py`.

`STATUTE_SCHEMA_ID` is `country-laws-ir-graphrag/v1`, copied from `SCHEMA_VERSION` in `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py`. `STATUTE_ID_FIELD` is `id`, the first name in `REQUIRED_LAW_COLUMNS` from `ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/schema.py`.

`OPINION_BODY_FIELDS` are `text`, `opinion_text`, and `case_text`. Opinion text is refused. A docket number is not a statute id.

## Municipal instrument

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/municipal_instrument_v1.py` assigns `INTERFACE_ID` `legal-corpus.municipal-instrument@1`. The kind name is `municipal_instrument`.

`SOURCE_SCHEMA_FILE` is `world_municipal/schema.py`. `SOURCE_DATASET` is `world_municipal`.

`ipfs_datasets_py/processors/legal_scrapers/world_municipal/schema.py` assigns no `SCHEMA_VERSION`. `EXPECTED_COLUMNS` in that file, and `CANONICAL_COLUMNS` in the kind module, are these 19 names in this order:

1. `cid`
2. `jurisdiction_id`
3. `jurisdiction_name`
4. `country`
5. `doc_id`
6. `regeling_id`
7. `regeling_work_id`
8. `doc_order`
9. `title`
10. `structural_path`
11. `node_label`
12. `html_title`
13. `html`
14. `text`
15. `source_url`
16. `xml_url`
17. `date_effective`
18. `date_modified`
19. `retrieved`

`doc_order` stays an integer. `TRAILING_EXTRA_EXAMPLE` is `tipo`, copied from the trailing-column example in the `world_municipal/schema.py` docstring. Extra columns are accepted only after those 19.

## Status vocabulary

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/status_v1.py` assigns `INTERFACE_ID` `legal-corpus.status@1`.

`document_role.ROLES` and `LawStatus` were not replaced.

`ipfs_datasets_py/processors/legal_scrapers/world_law/document_role.py` still assigns `ROLES` as `law`, `metadata`, and `informative`.

`ipfs_datasets_py/processors/legal_scrapers/legal_corpus/interfaces.py` still assigns:

- `LawStatus` as `current`, `historical`, `repealed`, `superseded`, and `unknown`
- `StatusConfidence` as `high`, `medium`, `low`, and `unknown`
- `STATUS_FIELD_NAMES` as `law_status`, `is_current`, `valid_from`, `valid_to`, `effective_date`, `retrieved_at`, `status_source`, `status_confidence`, `status_note`, `version_start_date`, and `version_end_date`

`status_v1.py` reads those three assignments. It does not assign a second status enum. `LAW_STATUS_WORDS` is the `LawStatus` list above. A word outside that list is rejected.
