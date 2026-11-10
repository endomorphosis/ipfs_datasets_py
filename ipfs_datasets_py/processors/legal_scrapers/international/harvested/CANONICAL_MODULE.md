# Canonical module for `international/harvested`

This boundary identifies the harvested copies that repeat the collector stamp `collection_record.v1` and points them at the index. Collector entry points in `national_collectors` stay collectors. They are not a second schema. Harvested scripts under `shared/` were not deleted. The `datasets/` and `legal_scrapers/` download caches were removed in legal_scrapers phase 2 (no catalog entry resolved into them); `harvest_legal_collectors()` regenerates them under `collectors_root()`. Paths below that start with `datasets/` or `legal_scrapers/` refer to those removed caches.

Datasets `HEAD` when this file was written: `d40ab60649b83781e3849e191c1f2ac8545b042f`.

`git status --short` printed no lines for the tracked files quoted below. It printed `??` for `legal_corpus/module_index_v1.py` and `legal_corpus/kinds/law_v1.py`. Those two files are untracked, so this record does not assign them a commit hash.

The duplicate register assigns this tree the group `mirror`. No path in that register is marked `delete`.

## The index is the instrument schema

The canonical index is `ipfs_datasets_py/processors/legal_scrapers/legal_corpus/module_index_v1.py`.

That module loads landed kind and adapter files by path. It exposes `KIND_INDEX`, `ADAPTER_INDEX`, and `INDEX`. `kind_version_ids()` and `adapter_version_ids()` are the version ids those rows assign. Its docstring says it does not import a scraper module. Importing the index does not import this tree.

`legal_corpus/kinds/law_v1.py` assigns:

```python
INTERFACE_ID = "legal-corpus.law@1"
SOURCE_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
VERIFY_SCHEMA_VERSION = "country-laws-normalize-verify/v1"
```

A later assignment in that file rebinds `SOURCE_SCHEMA_VERSION` by reading `SCHEMA_VERSION` from `country_laws_ir/__init__.py`, and rebinds `VERIFY_SCHEMA_VERSION` by reading `SCHEMA_VERSION` from `country_laws_ir/verify.py`. The expected string for each rebind is the constant above.

`country_laws_ir/__init__.py`, last changed in `9df09d3f50b80beebd5ae8bcd83cf72d034078c2`, assigns:

```python
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
```

`LAYOUT_FAMILY` is not the statute schema. `__version__` in that file is `"0.5.0"`.

`country_laws_ir/verify.py`, last changed in `9df09d3f50b80beebd5ae8bcd83cf72d034078c2`, assigns:

```python
SCHEMA_VERSION = "country-laws-normalize-verify/v1"
```

Those versioned modules are the schema authority this boundary points at. A copy under this tree is not a second instrument schema.

A search of `legal_corpus/` for `collection_record` returned no matches. `collection_record.v1` is not an index version id.

## Harvested copies that repeat the collector stamp

`international/harvested/NOTICE`, last changed in `dbd94493a570fdebcd93368fb43b26f7fc79cf58`, starts `Harvested official-gazette collectors from Hugging Face`.

A search for a line beginning `SCHEMA_VERSION` under this tree returned no matches. A search for `schema.py` returned no file. A search for `country-laws`, `graphrag`, `LAYOUT_FAMILY`, `1.2.0`, `world-laws-municipal`, and `skillcenter` in Python files under this tree returned no matches. A search for `legal-corpus` found three Python files, and each hit is the user-agent string in a `collect_bwb.py` copy. `international/harvested/shared/collect_bwb.py` assigns:

```python
UA = (
    "NL-BWB-legal-corpus-collector/1.0 "
    "(research archive of CC-0 BWB; polite; "
    "source=https://wetten.overheid.nl/)"
)
```

The same assignment is in `legal_scrapers/scrapers/collect_bwb.py` and `datasets/endomorphosis__ipfs_netherlands_laws/scrapers/collect_bwb.py`. That string is not `legal-corpus.law@1` and not `country-laws-ir-graphrag/v1`.

The repeated schema stamp is `collection_record.v1`. A search found that exact `schema_version` string in 200 Python files under this tree. 195 of those files also contain `"schema": "collection_record.v1"`. 186 of the Python files are named `common.py`. Those 186 files fall into six byte groups. One file from each group was read. Each opens `Shared helpers for national legislation collectors.` Each sets `SCHEMA_PATH` to `ROOT / "_templates" / "collection_record.schema.json"`. Each defines `base_record` and stamps the collector row with `collection_record.v1`.

| SHA-256 | Files | Example read | Last commit on that path | `schema_version` line |
| --- | --- | --- | --- | --- |
| `1344277c3aaac23ceddb488790d8c7b45c2c9abd75c447fb006853fad797d8c8` | 3 | `shared/common.py` | `4cdca488f0bd997e8f7a90438aa90a859cb85c5b` | 508 |
| `8c16ffd240e48365b87b29be8051d955b5bf7dad4f3d74ac725611d3eecdefa1` | 121 | `datasets/endomorphosis__ipfs_puerto_rico_laws/scrapers/common.py` | `dbd94493a570fdebcd93368fb43b26f7fc79cf58` | 447 |
| `85459b4e787f9c782115af5eba478f60752f1b3a814afe3bc6412068e7413db7` | 26 | `datasets/endomorphosis__ipfs_belgium_laws/scrapers/common.py` | `dbd94493a570fdebcd93368fb43b26f7fc79cf58` | 447 |
| `e9d8ebfd3cd6e54cfc2de8187455618a7c92ad175e6dae260523241b5fbfc146` | 25 | `datasets/endomorphosis__ipfs_serbia_laws/scrapers/common.py` | `dbd94493a570fdebcd93368fb43b26f7fc79cf58` | 449 |
| `cea5d792299b6983347b1fff5ada5407eb1845b4400410be69d288886406c5ef` | 9 | `datasets/endomorphosis__ipfs_uae_laws/scrapers/common.py` | `dbd94493a570fdebcd93368fb43b26f7fc79cf58` | 453 |
| `16dd1574251f3e537bc68284d987f7fb7d750729482509fcaab1aa53db547cf9` | 2 | `datasets/endomorphosis__ipfs_bulgaria_laws/scrapers/common.py` | `dbd94493a570fdebcd93368fb43b26f7fc79cf58` | 447 |

The three files in the first group are `shared/common.py`, `legal_scrapers/common.py`, and `legal_scrapers/scrapers/common.py`. `shared/common.py` assigns:

```python
SCHEMA_PATH = ROOT / "_templates" / "collection_record.schema.json"
```

`base_record` in that file builds the row with:

```python
"schema_version": "collection_record.v1",
```

and, inside `metadata`:

```python
"schema": "collection_record.v1",
```

`national_collectors/common.py` has the same SHA-256. Its last commit on that path is `0b9e4f0903c2aaa36e998a354afa01b36d149d76`. The harvested trio repeats that helper. The helper is not an instrument schema. These copies are pointed at `module_index_v1` and at `legal-corpus.law@1`. They do not replace `country-laws-ir-graphrag/v1`.

## Collector entry points stay in `national_collectors`

`national_collectors/catalog.py`, last changed in `d40ab60649b83781e3849e191c1f2ac8545b042f`, opens `Catalog of official national gazette collectors vendored from Hugging Face.` It sets:

```python
COLLECTORS_DIR = Path(__file__).resolve().parent
```

That directory is `national_collectors`, not this tree. The Belgium row in the catalog contains `'filename': 'collect_be.py'`, `'module': 'collect_be'`, and `'summary': 'Belgium: official Justel ELI year listings (HTTP fallback when HTTPS drops).'`.

`get_national_collector("be")` returned module `collect_be`, filename `collect_be.py`, and the path `national_collectors/collect_be.py`. That path is not under `international/harvested`. `load_collector_module` imports `spec.module` after putting `COLLECTORS_DIR` on `sys.path`. Its docstring says it does not run `main()`.

`national_collectors/collect_be.py`, last changed in `b560f8d60962277b09c12c44457b424de25de83b`, has the docstring `Belgium: official Justel ELI year listings (HTTP fallback when HTTPS drops).` Its SHA-256 is `1979a47b9fcd8956c7a93d37863fd983a85e3a973d1a488ad56d5140f60cd096`. Four harvested copies have the same bytes. Each last changed in `dbd94493a570fdebcd93368fb43b26f7fc79cf58`:

- `shared/collect_be.py`
- `legal_scrapers/collect_be.py`
- `legal_scrapers/scrapers/collect_be.py`
- `datasets/endomorphosis__ipfs_belgium_laws/scrapers/collect_be.py`

Those four files repeat the collector script. They are not the catalog entry and they are not a second schema.

A search for a line beginning `SCHEMA_VERSION` under `national_collectors/` returned no matches. A search found `"schema_version": "collection_record.v1"` in six Python files there: `common.py`, `collector.py`, `collect_eurlex.py`, `collect_fedlex.py`, `collect_gii.py`, and `collect_legi.py`. In `common.py` the stamp is inside `base_record`, the same collector row the harvested copies repeat. That stamp is not an instrument schema. The catalog remains the collector entry point.

## This tree was not deleted

This tree was not deleted. No harvested script was moved or rewritten. `national_collectors` was not edited. `module_index_v1.py` and `law_v1.py` were not edited by this record.
