# Canonical module for `hub_dataset_scripts`

This boundary record points the mirrors in this tree at `module_index_v1`. It lists the groups from the duplicate register. This tree was not deleted. In legal_scrapers phase 3 the 63 unreferenced `justicedao__ipfs_*_laws_ir` mirror kits were moved, unchanged, out of the importable package to `legal_scrapers_hub/hub_dataset_scripts/` at the repository root. No script was rewritten.

Datasets `HEAD` when this file was written: `d40ab60649b83781e3849e191c1f2ac8545b042f`.

## Mirrors point at `module_index_v1`

The canonical index is `ipfs_datasets_py/processors/legal_scrapers/legal_corpus/module_index_v1.py`.

That module loads landed kind and adapter files by path. It exposes `KIND_INDEX`, `ADAPTER_INDEX`, and `INDEX`. `kind_version_ids()` and `adapter_version_ids()` are the version ids those rows assign. Importing the index does not import this tree. `_COPY_MARKERS` in that file refuse `justicedao__ipfs_argentina_laws-ir` and `justicedao__ipfs_malta_laws-ir`.

A `mirror` package in this tree is a copy of a schema the index already records. It is not a second instrument schema. The statute schema home the `country-laws-ir-graphrag/v1` copies repeat is `country_laws_ir/__init__.py`, last changed in `9df09d3f50b80beebd5ae8bcd83cf72d034078c2`. That file assigns:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

`LAYOUT_FAMILY` is not the statute schema. `legal_corpus/kinds/law_v1.py` binds `INTERFACE_ID` `legal-corpus.law@1` to `SOURCE_SCHEMA_VERSION` `country-laws-ir-graphrag/v1` and `VERIFY_SCHEMA_VERSION` `country-laws-normalize-verify/v1`. A v1 mirror in this tree points at that index row.

The canonical module that would replace this tree's `mirror` group is `module_index_v1`. This file does not perform that replacement.

## Groups from the duplicate register

The groups are the ones named in `implementation_plan/legal_corpus_modules/registers/duplicates.md`. They are `canonical`, `mirror`, `collector-entry`, `quarantine`, and `leave-in-place`. No path in that register is marked `delete`.

| Group | Trees or files the register assigns |
| --- | --- |
| `canonical` | `hub_integrated/world_law_pipeline` |
| `mirror` | `hub_dataset_scripts`, `hub_integrated/justicedao_world_law_scrapers`, `hub_integrated/legal_scrapers`, `international/harvested`, `state_scrapers`, `world_municipal_campaigns`, `municipal` |
| `collector-entry` | `national_collectors`, `national_campaigns` |
| `quarantine` | the 17 note files under `hub_integrated/legal_scrapers/` |
| `leave-in-place` | `justicedao__ipfs_argentina_laws-ir` and `justicedao__ipfs_malta_laws-ir` |

This tree's group is `mirror`. The two hyphenated copies inside it are `leave-in-place`. `canonical`, `collector-entry`, and `quarantine` name other trees. This file does not write their boundary records.

## `mirror` copies checked in this tree

`legal_scrapers_hub/hub_dataset_scripts/justicedao__ipfs_germany_laws_ir/country_laws_ir/__init__.py`, last changed in `5f457fb04b1bbc27ccc84451fe6ba7f93700d9cd`, repeats the statute pair:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

`legal_scrapers_hub/hub_dataset_scripts/justicedao__ipfs_malta_laws_ir/country_laws_ir/__init__.py`, last changed in `5f457fb04b1bbc27ccc84451fe6ba7f93700d9cd`, assigns the same two strings. That underscore package stays in the `mirror` group. It is not a `leave-in-place` copy.

`hub_dataset_scripts/endomorphosis__legal_scrapers/scrapers/common.py`, last changed in `af81ba630119ad59022b531294e82421fc4a17cb`, opens `Shared helpers for national legislation collectors.` and sets:

```python
ROOT = Path("/workspace/legal-corpora")
SCHEMA_PATH = ROOT / "_templates" / "collection_record.schema.json"
```

That helper is not an instrument schema and is not an index row. It stays in the `mirror` group.

## `leave-in-place` copies

Both files last changed in `5f457fb04b1bbc27ccc84451fe6ba7f93700d9cd`. Both open `Country-law CID-keyed sparse GraphRAG packager (SkillCenter IR v3 layout).` Both assign:

```python
SCHEMA_VERSION = "skillcenter-huggingface-release/v3"
```

`hub_dataset_scripts/justicedao__ipfs_argentina_laws-ir/country_laws_ir/__init__.py` and `hub_dataset_scripts/justicedao__ipfs_malta_laws-ir/country_laws_ir/__init__.py` are not `country-laws-ir-graphrag/v1`. `module_index_v1` does not index them. They were not moved.

## This tree was not deleted

This tree was not deleted. The two `leave-in-place` copies, `endomorphosis__legal_scrapers`, and the other non-kit directories stay here. The 63 `*_laws_ir` kits were moved, not deleted (phase 3); no script was rewritten. Bulk retirement still needs a later named go-ahead.
