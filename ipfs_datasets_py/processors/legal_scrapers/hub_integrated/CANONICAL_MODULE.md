# Canonical module for `hub_integrated`

This boundary record covers `justicedao_world_law_scrapers`, `legal_scrapers`, and `world_law_pipeline`. Schema authority for instrument versions is the versioned modules under `legal_corpus/`. The 17 note files under `legal_scrapers/` are `quarantine`. `world_law_pipeline/schema.py` remains the `1.2.0` source of truth until a named go-ahead says otherwise. This file does not edit that schema. This tree was not deleted.

Datasets `HEAD` when this file was written: `d40ab60649b83781e3849e191c1f2ac8545b042f`.

`git status --short` printed no lines for the tracked schema files quoted below. It printed `??` for `legal_corpus/module_index_v1.py`, `legal_corpus/quarantine_notes_v1.py`, `legal_corpus/instrument_v1.py`, `legal_corpus/kinds/law_v1.py`, `legal_corpus/kinds/municipal_instrument_v1.py`, and `legal_corpus/adapters/world_law_pipeline_v1.py`. Those six files are untracked, so this record does not assign them a commit hash.

## Schema authority is the versioned modules

The canonical index is `ipfs_datasets_py/processors/legal_scrapers/legal_corpus/module_index_v1.py`.

That module loads landed kind and adapter files by path. It exposes `KIND_INDEX`, `ADAPTER_INDEX`, and `INDEX`. `kind_version_ids()` and `adapter_version_ids()` are the version ids those rows assign. Importing the index does not import this tree. It loads `quarantine_notes_v1.py` and skips `QUARANTINE_NOTE_FILENAMES`. `_COPY_MARKERS` in that file refuse `justicedao__ipfs_argentina_laws-ir` and `justicedao__ipfs_malta_laws-ir`.

`legal_corpus/instrument_v1.py` assigns:

```python
INTERFACE_ID = "legal-corpus.instrument@1"
```

Its `KINDS` tuple is `law`, `regulation`, `legislative_act`, `caselaw`, `court`, and `municipal_instrument`.

`legal_corpus/kinds/law_v1.py` assigns:

```python
INTERFACE_ID = "legal-corpus.law@1"
SOURCE_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
VERIFY_SCHEMA_VERSION = "country-laws-normalize-verify/v1"
```

A later assignment in that file reads `SCHEMA_VERSION` from `country_laws_ir/__init__.py`. That schema home is outside this tree. It last changed in `9df09d3f50b80beebd5ae8bcd83cf72d034078c2` and assigns:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

`LAYOUT_FAMILY` is not the statute schema. `__version__` in that home file is `"0.5.0"`.

`legal_corpus/kinds/municipal_instrument_v1.py` assigns:

```python
INTERFACE_ID = "legal-corpus.municipal-instrument@1"
SOURCE_SCHEMA_FILE = "world_municipal/schema.py"
```

That source file is outside this tree. A search of `world_municipal/schema.py` for `SCHEMA_VERSION` returned no matches. The kind names 19 `EXPECTED_COLUMNS`, from `cid` through `retrieved`.

`legal_corpus/adapters/world_law_pipeline_v1.py` reads `hub_integrated/world_law_pipeline/schema.py` and does not import it. It sets `_READ_SCHEMA_VERSION = "1.2.0"` and `_SOURCE_SCHEMA_FILE = "hub_integrated/world_law_pipeline/schema.py"`. `_bound_string` raises `AdapterBindingError` when the assignment in that file is not the expected string. The adapter docstring says this module does not edit `schema.py`.

These versioned modules are the schema authority this boundary points at. A copy under this tree is not a second instrument schema.

## `world_law_pipeline`

`registers/duplicates.md` assigns this directory the group `canonical`.

`hub_integrated/world_law_pipeline/schema.py`, last changed in `d40ab60649b83781e3849e191c1f2ac8545b042f`, opens `world_municipal_law schema (WORLDWIDE_SCRAPE_PLAN.md §1.2 / §4.2).` The docstring says it is the single source of truth for scraper bots, the normalizer (`run_loop.py`), and the uploader. It assigns:

```python
SCHEMA_VERSION = "1.2.0"  # 1.1.0: optional provenance columns + extra_metadata (appended); 1.2.0: pdf_ref (appended)
```

```python
DOC_TYPES = ("code_section", "ordinance", "regulation", "statute", "gazette_act", "decision")
```

`world_law_pipeline/schema.py` remains the `1.2.0` source of truth until a named go-ahead says otherwise. This boundary does not edit it. Scripts under `world_law_pipeline/scrapers/` are not a second schema id.

## `justicedao_world_law_scrapers`

`registers/duplicates.md` assigns this directory the group `mirror`.

`hub_integrated/justicedao_world_law_scrapers/ir_builder/country_laws_ir/__init__.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, sets `__version__ = "0.3.0"` and assigns:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

That pair repeats the schema home. The statute binding authority is `legal_corpus/kinds/law_v1.py`, which reads `country_laws_ir/__init__.py`, not this copy. The tree also repeats collectors. The nested stale package copy under `ipfs_datasets_py_legal/` (1,495 files) was removed in legal_scrapers phase 1; `MANIFEST.json` records it under `excluded`. The rest of this tree was not deleted.

## `legal_scrapers`

`registers/duplicates.md` assigns this directory the group `mirror`.

`hub_integrated/legal_scrapers/schema.py`, last changed in `d40ab60649b83781e3849e191c1f2ac8545b042f`, assigns:

```python
IR_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
```

```python
MUNICIPAL_SCHEMA_VERSION = "world-laws-municipal/v1"
```

`hub_integrated/legal_scrapers/municipal/schema.py`, last changed in `4cdca488f0bd997e8f7a90438aa90a859cb85c5b`, assigns the same `IR_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"`. Those strings are copies. The 19-column municipal contract is `world_municipal/schema.py`, and the versioned interface that names it is `legal-corpus.municipal-instrument@1`. `world-laws-municipal/v1` is not that interface id.

## Seventeen notes — `quarantine`

These 17 files are under `hub_integrated/legal_scrapers/`. Each first line was read in this checkout. Each first line starts with `linked logs/`. They are not importable scrapers. Each file is `quarantine`. They stay at these paths. They were not rewritten. `git log -1` for `al_alfresco_tip26b.py` is `d40ab60649b83781e3849e191c1f2ac8545b042f`.

`legal_corpus/quarantine_notes_v1.py` sets `QUARANTINE_NOTE_DIR = "hub_integrated/legal_scrapers"` and lists these same 17 filenames. `module_index_v1.py` skips them.

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

## This tree was not deleted

This tree was not deleted. `world_law_pipeline/schema.py` was not edited and remains the `1.2.0` source of truth until a named go-ahead says otherwise. No scraper under `justicedao_world_law_scrapers`, `legal_scrapers`, or `world_law_pipeline` was moved or rewritten.
