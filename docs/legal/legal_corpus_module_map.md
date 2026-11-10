# Legal corpus module map

This map was read on 2026-11-09 from `external/ipfs_datasets` after the boundary records had landed. `git rev-parse HEAD` was `7e860a5fa1a0bd1c0f940ac141665461b332de29`. Paths below sit under `ipfs_datasets_py/processors/legal_scrapers/` unless a line says otherwise. `git log -1 --format=%H` was run on each path whose revision is quoted. Schema strings are copied from the source file that assigns them.

`PLAN.md` names these duplicate trees. Each directory was still present. The copies were not deleted. This file does not rewrite `docs/legal/justicedao_refresh_plan_20261021.md`.

The canonical index is `legal_corpus/module_index_v1.py`, last changed in `12f22dc9c8fe90b479144dcb94b78ffd06932b5a`. It loads landed kind and adapter files by path. It exposes `KIND_INDEX`, `ADAPTER_INDEX`, and `INDEX`. It loads `quarantine_notes_v1.py` and skips `QUARANTINE_NOTE_FILENAMES`. `_COPY_MARKERS` refuse `justicedao__ipfs_argentina_laws-ir` and `justicedao__ipfs_malta_laws-ir`. Importing the index does not import a duplicate tree.

`legal_corpus/instrument_v1.py`, last changed in the same commit, assigns `INTERFACE_ID = "legal-corpus.instrument@1"`. Its `KINDS` tuple is `law`, `regulation`, `legislative_act`, `caselaw`, `court`, and `municipal_instrument`. That file does not name the SkillCenter copies.

`legal_corpus/kinds/law_v1.py`, same commit, assigns:

```python
INTERFACE_ID = "legal-corpus.law@1"
SOURCE_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
VERIFY_SCHEMA_VERSION = "country-laws-normalize-verify/v1"
```

A later assignment in that file rebinds those schema strings by reading `country_laws_ir/__init__.py` and `country_laws_ir/verify.py`.

`legal_corpus/kinds/municipal_instrument_v1.py`, same commit, assigns `INTERFACE_ID = "legal-corpus.municipal-instrument@1"` and `SOURCE_SCHEMA_FILE = "world_municipal/schema.py"`.

`legal_corpus/adapters/world_law_pipeline_v1.py`, same commit, sets `_READ_SCHEMA_VERSION = "1.2.0"` and `_SOURCE_SCHEMA_FILE = "hub_integrated/world_law_pipeline/schema.py"`.

The statute schema home is `country_laws_ir/__init__.py`, last changed in `9df09d3f50b80beebd5ae8bcd83cf72d034078c2`:

```python
__version__ = "0.5.0"
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

`LAYOUT_FAMILY` is not the statute schema. `country_laws_ir/verify.py`, same commit, assigns `SCHEMA_VERSION = "country-laws-normalize-verify/v1"`. `world_municipal/schema.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, is the 19-column contract. A search of that file found no `SCHEMA_VERSION` assignment. `EXPECTED_COLUMNS` lists 19 names, from `cid` through `retrieved`.

## Each duplicate tree

| Duplicate tree | Boundary record | Index |
| --- | --- | --- |
| `hub_dataset_scripts` | `hub_dataset_scripts/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `hub_integrated/justicedao_world_law_scrapers` | `hub_integrated/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `hub_integrated/legal_scrapers` | `hub_integrated/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `hub_integrated/world_law_pipeline` | `hub_integrated/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `international/harvested` | `international/harvested/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `national_collectors` | `international/harvested/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `national_campaigns` | `hub_dataset_scripts/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `state_scrapers` | `hub_dataset_scripts/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `world_municipal_campaigns` | `hub_dataset_scripts/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |
| `municipal` | `hub_dataset_scripts/CANONICAL_MODULE.md` | `legal_corpus/module_index_v1.py` |

The three `CANONICAL_MODULE.md` files last changed in `12f22dc9c8fe90b479144dcb94b78ffd06932b5a`. Each one says the tree it records was not deleted, and each one names `module_index_v1.py` as the canonical index. `git status --short` on those three files and on `module_index_v1.py` printed no lines. The copies were not deleted.

`hub_dataset_scripts/CANONICAL_MODULE.md` lists every duplicate-register group. It says `canonical`, `collector-entry`, and `quarantine` name other trees, and that this file does not write their boundary records. `national_campaigns`, `state_scrapers`, `world_municipal_campaigns`, and `municipal` are named there and have no separate `CANONICAL_MODULE.md`. They still point at `module_index_v1.py`. They are not a second instrument schema. `national_collectors` is also named in that groups table. Its boundary section is in `international/harvested/CANONICAL_MODULE.md`.

The duplicate register at `implementation_plan/legal_corpus_modules/registers/duplicates.md` assigns `mirror` to `hub_dataset_scripts`, `hub_integrated/justicedao_world_law_scrapers`, `hub_integrated/legal_scrapers`, `international/harvested`, `state_scrapers`, `world_municipal_campaigns`, and `municipal`. It assigns `canonical` to `hub_integrated/world_law_pipeline`. It assigns `collector-entry` to `national_collectors` and `national_campaigns`. No path in that register is marked `delete`.

## `hub_dataset_scripts`

`hub_dataset_scripts/CANONICAL_MODULE.md` points the mirrors in this tree at `module_index_v1` and lists the register groups. The tree was not deleted.

`hub_dataset_scripts/justicedao__ipfs_germany_laws_ir/country_laws_ir/__init__.py`, last changed in `5f457fb04b1bbc27ccc84451fe6ba7f93700d9cd`, repeats the statute pair:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

`__version__` in that file is `"0.3.0"`. `hub_dataset_scripts/justicedao__ipfs_malta_laws_ir/country_laws_ir/__init__.py`, same commit, assigns `SCHEMA_VERSION = "country-laws-ir-graphrag/v1"` and `LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"`. That underscore package stays in the mirror. It is not a SkillCenter `leave-in-place` copy.

`hub_dataset_scripts/endomorphosis__legal_scrapers/scrapers/common.py`, last changed in `e5f5381b5c9f83d01129ceb72f67d90fde15dd51`, opens `Shared helpers for national legislation collectors.` It assigns:

```python
ROOT = Path(os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", os.environ.get("LEGAL_CORPORA_ROOT", str(Path.home() / ".ipfs_datasets" / "legal_corpora"))))
SCHEMA_PATH = ROOT / "_templates" / "collection_record.schema.json"
```

The collector row in that file stamps `"schema_version": "collection_record.v1"`. That helper is not an instrument schema and is not an index row. The boundary record quotes an older `ROOT = Path("/workspace/legal-corpora")` for this path. The assignment above is the one in the file now.

## `hub_integrated/justicedao_world_law_scrapers`

`hub_integrated/CANONICAL_MODULE.md` covers this directory, `legal_scrapers`, and `world_law_pipeline`. It points schema authority at the versioned modules and at `module_index_v1.py`. The tree was not deleted.

`hub_integrated/justicedao_world_law_scrapers/ir_builder/country_laws_ir/__init__.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, sets `__version__ = "0.3.0"` and assigns:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

That pair repeats the statute schema home. `law_v1.py` reads `country_laws_ir/__init__.py`, not this copy.

## `hub_integrated/legal_scrapers`

The same `hub_integrated/CANONICAL_MODULE.md` covers this directory and points it at `module_index_v1.py`. The tree was not deleted.

`hub_integrated/legal_scrapers/schema.py`, last changed in `d40ab60649b83781e3849e191c1f2ac8545b042f`, assigns:

```python
IR_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
```

```python
MUNICIPAL_SCHEMA_VERSION = "world-laws-municipal/v1"
```

`hub_integrated/legal_scrapers/municipal/schema.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, assigns the same `IR_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"`. Those strings are copies. The 19-column municipal contract is `world_municipal/schema.py`. The versioned interface that names it is `legal-corpus.municipal-instrument@1`. `world-laws-municipal/v1` is not that interface id.

The 17 quarantine notes live in this tree. They are listed below and were not deleted.

## `hub_integrated/world_law_pipeline`

The same `hub_integrated/CANONICAL_MODULE.md` covers this directory. It says `world_law_pipeline/schema.py` remains the `1.2.0` source of truth until a named go-ahead says otherwise, and it points the index at `module_index_v1.py`. The tree was not deleted.

`hub_integrated/world_law_pipeline/schema.py`, last changed in `d40ab60649b83781e3849e191c1f2ac8545b042f`, opens `world_municipal_law schema (WORLDWIDE_SCRAPE_PLAN.md §1.2 / §4.2).` The docstring says it is the single source of truth for scraper bots, the normalizer (`run_loop.py`), and the uploader. It assigns:

```python
SCHEMA_VERSION = "1.2.0"  # 1.1.0: optional provenance columns + extra_metadata (appended); 1.2.0: pdf_ref (appended)
```

```python
DOC_TYPES = ("code_section", "ordinance", "regulation", "statute", "gazette_act", "decision")
```

`world_law_pipeline_v1.py` reads that file and does not import it. This map does not edit `schema.py`.

## `international/harvested`

`international/harvested/CANONICAL_MODULE.md` identifies harvested copies that repeat `collection_record.v1` and points them at `module_index_v1.py` and at `legal-corpus.law@1`. It says harvested scripts were not deleted. The tree was not deleted.

`international/harvested/NOTICE`, last changed in `dbd94493a570fdebcd93368fb43b26f7fc79cf58`, starts `Harvested official-gazette collectors from Hugging Face`.

A search for a line beginning `SCHEMA_VERSION` under this tree matched only the boundary record's quotations of other files. `international/harvested/shared/common.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, assigns `SCHEMA_PATH = ROOT / "_templates" / "collection_record.schema.json"` and stamps `"schema_version": "collection_record.v1"` and `"schema": "collection_record.v1"`. That stamp is a collector row. It is not an index version id.

## `national_collectors`

`international/harvested/CANONICAL_MODULE.md` says collector entry points stay in `national_collectors`. They are collectors, not a second schema. The same section points the repeated collector stamp at `module_index_v1.py`. The catalog was not deleted.

`national_collectors/catalog.py`, last changed in `1a7397980fac52420470694bd4e15fe65f1709c3`, opens `Catalog of official national gazette collectors vendored from Hugging Face.` It sets `COLLECTORS_DIR = Path(__file__).resolve().parent`. The harvested boundary record says this path last changed in `d40ab60649b83781e3849e191c1f2ac8545b042f`. The revision above is the last commit on the path now.

A search for a line beginning `SCHEMA_VERSION` under `national_collectors/` returned no matches. `national_collectors/common.py`, last changed in `e5f5381b5c9f83d01129ceb72f67d90fde15dd51`, stamps `"schema_version": "collection_record.v1"` and `"schema": "collection_record.v1"`. The harvested boundary record cites `0b9e4f0903c2aaa36e998a354afa01b36d149d76` for this path. The revision above is the last commit on the path now.

## `national_campaigns`

`hub_dataset_scripts/CANONICAL_MODULE.md` lists this tree in the `collector-entry` group and points the index at `module_index_v1.py`. That file says it does not write this tree's boundary record. There is no `national_campaigns/CANONICAL_MODULE.md`. The wave scripts were not deleted.

A search for a line beginning `SCHEMA_VERSION` under `national_campaigns/` returned no matches. `national_campaigns/wave13/pw_harvest13.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, writes `'schema_version': 'collection_record.v1'`. That stamp is a collector row.

## `state_scrapers`

`hub_dataset_scripts/CANONICAL_MODULE.md` lists this tree in the `mirror` group and points the index at `module_index_v1.py`. That file says it does not write this tree's boundary record. There is no `state_scrapers/CANONICAL_MODULE.md`. The scrapers were not deleted.

`state_scrapers/README.md`, last changed in `df93e91e6338c84a17c3208ef68b88de8566f78c`, says the directory contains individual scrapers for each US state's official legislative website and that each scraper outputs data in a normalized `NormalizedStatute` schema. A search for a line beginning `SCHEMA_VERSION` under `state_scrapers/` returned no matches.

`state_scrapers/new_york_law_pdf.py`, last changed in `1226373a4f2a69a8f4965273fc958aaffda815b5`, assigns `SUPPLEMENTAL_PROOF_SCHEMA_VERSION = "new-york-supplemental-proof-input-v1"`.

`state_scrapers/california_bulk.py`, last changed in `df53f62e06d00ab69f53aadf0ec0d997c1647d87`, assigns `LARGE_FILE_TRANSPORT_RECEIPT_SCHEMA = "state-laws-large-file-transport-receipt-v1"`.

Those receipt strings are not `country-laws-ir-graphrag/v1`. This tree is not an independent instrument schema.

## `world_municipal_campaigns`

`hub_dataset_scripts/CANONICAL_MODULE.md` lists this tree in the `mirror` group and points the index at `module_index_v1.py`. That file says it does not write this tree's boundary record. There is no `world_municipal_campaigns/CANONICAL_MODULE.md`. The campaigns were not deleted.

A search for `schema_version` under `world_municipal_campaigns/` returned no matches. `world_municipal_campaigns/de_pilot/harvest_de_pilot.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, is titled `Germany municipal-law pilot harvester.` The docstring says rows split on § headings into the world_municipal 19-column schema. This file does not assign `SCHEMA_VERSION`. The 19-column contract remains `world_municipal/schema.py`, indexed through `legal-corpus.municipal-instrument@1`.

## `municipal`

`hub_dataset_scripts/CANONICAL_MODULE.md` lists this tree in the `mirror` group and points the index at `module_index_v1.py`. That file says it does not write this tree's boundary record. There is no `municipal/CANONICAL_MODULE.md`. The tree was not deleted.

A search for `schema_version` and `SCHEMA_VERSION` under `municipal/` returned no matches. `municipal/__init__.py`, last changed in `dbd94493a570fdebcd93368fb43b26f7fc79cf58`, opens `US municipal code scrapers backed by the Hugging Face American Municipal Law corpus.` `municipal/catalog.py`, same commit, sets `HUB_DATASET_ID = "endomorphosis/american_municipal_law"`. This tree does not hold the 19-column contract.

## Quarantine notes

These 17 files stay under `hub_integrated/legal_scrapers/`. They were not deleted. `legal_corpus/quarantine_notes_v1.py`, last changed in `12f22dc9c8fe90b479144dcb94b78ffd06932b5a`, sets `QUARANTINE_NOTE_DIR = "hub_integrated/legal_scrapers"` and lists these filenames. `module_index_v1.py` skips them. `hub_integrated/CANONICAL_MODULE.md` names them as `quarantine`.

Each first line was read in this checkout. Each first line starts with `linked logs/`. `git log -1` for `al_alfresco_tip26b.py` is `d40ab60649b83781e3849e191c1f2ac8545b042f`.

| File | First line |
| --- | --- |
| `al_alfresco_tip26b.py` | `linked logs/al_alfresco_tip26v.py -` |
| `al_close_tip26b.py` | `linked logs/al_close_tip26v.py -` |
| `az_cdx_extra_tip26f.py` | `linked logs/az_cdx_extra_tip26v.py -` |
| `az_live_gap_tip24o.py` | `linked logs/az_live_gap_tip26v.py -` |
| `az_live_gap_tip26f.py` | `linked logs/az_live_gap_tip26u.py -` |
| `bo_live_cdx_miss_tip26m.py` | `linked logs/bo_live_cdx_miss_tip26v.py -` |
| `bo_live_failures_tip26a.py` | `linked logs/bo_live_failures_tip26v.py -` |
| `bo_live_failures_tip26b.py` | `linked logs/bo_live_failures_tip26u.py -` |
| `ir_media_recent_tip25q.py` | `linked logs/ir_media_recent_tip26v.py -` |
| `ir_media_recent_tip26b.py` | `linked logs/ir_media_recent_tip26u.py -` |
| `ir_media_recent_tip26n.py` | `linked logs/ir_media_recent_tip26s.py -` |
| `mw_akn_miss_tip25m.py` | `linked logs/mw_akn_miss_tip26v.py -` |
| `mw_akn_miss_tip26b.py` | `linked logs/mw_akn_miss_tip26u.py -` |
| `mw_akn_miss_tip26n.py` | `linked logs/mw_akn_miss_tip26s.py -` |
| `mw_extra_akn_tip25p.py` | `linked logs/mw_extra_akn_tip26v.py -` |
| `mw_extra_akn_tip26b.py` | `linked logs/mw_extra_akn_tip26u.py -` |
| `mw_extra_akn_tip26m.py` | `linked logs/mw_extra_akn_tip26s.py -` |

## SkillCenter outliers left in place

`hub_dataset_scripts/justicedao__ipfs_argentina_laws-ir/country_laws_ir/__init__.py` and `hub_dataset_scripts/justicedao__ipfs_malta_laws-ir/country_laws_ir/__init__.py` both last changed in `5f457fb04b1bbc27ccc84451fe6ba7f93700d9cd`. Both open `Country-law CID-keyed sparse GraphRAG packager (SkillCenter IR v3 layout).` Both assign:

```python
__version__ = "0.1.0"
SCHEMA_VERSION = "skillcenter-huggingface-release/v3"
```

They are not `country-laws-ir-graphrag/v1`. `module_index_v1.py` does not index them. `instrument_v1.py` does not import them. `hub_dataset_scripts/CANONICAL_MODULE.md` records them as `leave-in-place`. They were not moved and were not deleted.

## Copies were not deleted

No duplicate tree listed above was removed. The 17 quarantine notes were not removed. The two SkillCenter `v3` copies were left in place. `module_index_v1.py` is the index those trees point at. The three `CANONICAL_MODULE.md` files are the boundary records. This map does not retire a tree and does not edit `docs/legal/justicedao_refresh_plan_20261021.md`.
