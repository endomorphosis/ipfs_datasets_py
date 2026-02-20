# MASTER REFACTORING PLAN 2026 — Bluebook Citation Validator

## Overview

This document records every bug found in the original
`municipal_bluebook_citation_validator` package, explains the new
architecture, and outlines the migration path and future roadmap.

---

## 1. New Architecture

```
ipfs_datasets_py/processors/legal_scrapers/bluebook_citation_validator/
├── __init__.py          # Public API
├── config.py            # ValidatorConfig dataclass
├── types_.py            # CheckResult, ErrorRecord type definitions
├── database.py          # setup_reference/error/report_database(), make_cid()
├── sampling.py          # StratifiedSampler
├── validator.py         # CitationValidator (main orchestrator)
├── analysis.py          # ConfusionMatrixStats, ResultsAnalyzer, ExtrapolateToFullDataset
├── report.py            # generate_validation_report()
├── cli.py               # argparse CLI entry point
├── thread_pool.py       # run_in_thread_pool()
└── checkers/
    ├── __init__.py
    ├── geography.py     # check_geography()
    ├── code_type.py     # check_code_type()
    ├── section.py       # check_section()
    ├── date.py          # check_date()
    └── format.py        # check_format()
```

The thin MCP wrapper lives at:
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/bluebook_citation_validator_tool.py
```

The old package path is preserved as a deprecation shim that re-exports all
public names and emits a `DeprecationWarning` on import.

---

## 2. Bug Inventory

### 2.1 Critical Bugs (all fixed)

| # | File | Line | Bug | Fix |
|---|------|------|-----|-----|
| 1 | `citation_validator.py` | 83 | `self._citation_dir = configs['html_dir']` overwrote itself | `self._html_dir = configs['html_dir']` |
| 2 | `citation_validator.py` | 163–165 | `error_message` static method missing `return` keyword | Added `return` before the f-string |
| 3 | `citation_validator.py` | 226–241 | `_check_geography`/`_check_code` called `_run_check(reference_db=…)` but `_run_check` has no such param | `reference_db` is now captured via lambda closure at the call site |
| 4 | `citation_validator.py` | 335 | `with self._lock.acquire(timeout=10):` — `RLock` context-manager does not accept timeout; `error_count` used before assignment | Changed to `threading.Lock`; initialised `error_count = 0` before use; explicit `acquire`/`release` with timeout |
| 5 | `citation_validator.py` | 384 | `for gnis in gnis_batch:` — `gnis_batch` not defined at that scope | Changed to `for gnis in sampled_gnis:` |
| 6 | `citation_validator.py` | 399 | `result_list.extend(results)` — `results` not in scope | `place_results` is now captured from the thread pool yield |
| 7 | `factory.py` | — | `"logger": dependencies.tqdm` — tqdm is not a Logger; missing `run_in_thread_pool` / `validate_citation_consistency` resources | New architecture injects a proper `logging.getLogger(__name__)` logger; factory pattern replaced by direct construction |
| 8 | `_check_code.py` | — | Returns `dict` instead of `str \| None` | `check_code_type` now returns `str \| None` |
| 9 | `_check_dates.py` | 33 | Returns `'Date check passed'` string on success | Returns `None` on success |
| 10 | `_save_validation_errors.py` | 41 | `sum(len(error_messages))` should be `len(error_messages)`; function returns `None` | Fixed to `len(error_messages)`; function now returns `error_count` |
| 11 | `_results_analyzer.py` | — | `__init__` and `analyze` doubly indented (parse error); `analyze` missing `return` | Fixed indentation; added `return` statement |
| 12 | `_extrapolate_to_full_dataset.py` | 173 | `cv = self._apply_geographic_weighting(cv, scaling_factor)` — `cv` undefined; wrong args | Fixed to `cv = ExtrapolateToFullDataset._apply_geographic_weighting(gnis_counts_by_state)` |
| 13 | `_extrapolate_to_full_dataset.py` | 152–155 | `.recall` → `.true_positive_rate`; `.total_population` → `.total` | Both corrected on `ConfusionMatrixStats` |
| 14 | `_setup_database_and_files.py` | 95–97 | `get_databases` returns only `(error_db, reference_db)` — missing `error_report_db` | Now returns `(reference_db, error_db, error_report_db)` (3 values) |
| 15 | `_setup_database_and_files.py` | 121–122 | `get_all_files_in_directory("*_citation.parquet")` — missing `(self, directory, pattern)` args; also missing `self` | `get_all_files_in_directory` is now a proper `def` with `self`; calls pass both args |
| 16 | `_count_gnis_by_state.py` | 31 | `.to_records('records')` should be `.to_dict('records')` | Fixed |
| 17 | `run_in_thread_pool.py` | 60 | `pbar.update(1)` in `else:` branch where `pbar` is not defined | Removed the stray call; the `use_tqdm=False` path has no progress-bar reference |
| 18 | `_save_validation_errors.sql` | — | 11 columns but only 10 `?` placeholders (`?, ?. ?` typo) | SQL string now has exactly 11 `?` placeholders |
| 19 | `_setup_reference_db.py` | 36–38 | `finally:` block closes `conn` before returning it | `conn.close()` moved to error path only; caller receives an open connection |
| 20 | `configs.py` | — | `_Configs` missing `max_concurrency` field | `ValidatorConfig` includes `max_concurrency: int = 8` |

### 2.2 Major Bugs (all fixed)

| # | File | Bug | Fix |
|---|------|-----|-----|
| 21 | `_check_geography.py` | `citation['state']` — wrong field name | Now uses `citation.get('bluebook_state_code')` per PRD |
| 22 | `_check_code.py` | Used `feature_class` text strings instead of `class_code` values (C1–C8, H1/H4–H6) | Now uses `class_code` with `_MUNICIPAL_CLASS_CODES`, `_COUNTY_CLASS_CODES`, `_CONSOLIDATED_CLASS_CODES` frozensets |
| 23 | `_check_section.py` | Wrong signature `(citation_section: str, html_body: str)` but called as `(citation, reference_db, docs)` | Signature corrected to `(citation: dict, documents: list[dict])` |
| 24 | `_analyze_error_patterns.py` | `row[2:6]` unpacks only 4 flags (geography, section, date, format) — `type_error` silently dropped | Now reads by column index from schema: col 3=geography, col 4=type, col 5=section, col 6=date, col 7=format |
| 25 | `_setup_reference_db.py` | (same as #19) — caller gets closed connection | Fixed (see #19) |

### 2.3 Deferred Features (now implemented)

| # | Feature | Implementation |
|---|---------|----------------|
| 26 | `check_date` — document date cross-reference | Year from citation is searched in each document's `html_body`/`content` field |
| 27 | `check_format` — validate full `bluebook_citation` string against Rule 12.9 | `_BLUEBOOK_PATTERN` regex + `_BLUEBOOK_STATE_ABBREVS` frozenset; validates structure, abbreviation, section, year |
| 28 | `check_section` — fix signature and extract section from citation dict | New signature `(citation: dict, documents: list[dict])`; extracts from `title_num` or `bluebook_citation` |

---

## 3. Security Notes

All SQL queries use parameterised bindings (`?` placeholders). No user-supplied
data is ever interpolated directly into SQL strings. See:

- `checkers/geography.py` — `execute("SELECT … WHERE gnis = ?", [gnis])`
- `checkers/code_type.py` — same pattern
- `sampling.py` — batch placeholders generated as `", ".join("?" * len(batch))`

---

## 4. Migration Guide

### Before (deprecated)

```python
from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs \
    .municipal_bluebook_citation_validator import CitationValidator
```

### After (canonical)

```python
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator import (
    CitationValidator, ValidatorConfig, StratifiedSampler, ResultsAnalyzer,
    generate_validation_report,
)
```

The old import path continues to work (with a `DeprecationWarning`) until it
is removed in a future release.

### Config migration

Old `_Configs` Pydantic model → new `ValidatorConfig` plain dataclass.

```python
# Old
from …configs import _Configs
configs = _Configs(citation_dir=…, error_db_path=…)

# New
from …bluebook_citation_validator import ValidatorConfig
config = ValidatorConfig(citation_dir=…, error_db_path=…)
```

`ValidatorConfig` still supports dict-style read access (`config['key']`) for
backwards compatibility.

---

## 5. Future Work

### Phase 2 — MySQL Integration Testing

- Add integration tests that spin up a test MySQL instance (or use a DuckDB
  in-memory substitute) to exercise `setup_reference_database()` end-to-end.
- Add a health-check CLI command (`validate-citations --check-db`).

### Phase 3 — PDF Citation Validation

- Extend `check_section` to accept PDF text extracted via the existing
  `ipfs_datasets_py.pdf_processing` pipeline.
- Add a `check_pdf_format` checker for citations that reference PDF documents
  rather than HTML.

### Phase 4 — Async-Native Validator

- Replace `run_in_thread_pool` with `asyncio.TaskGroup` for Python 3.11+.
- Make `CitationValidator.validate_citations_against_html_and_references` a
  native `async def`.

---

*Generated as part of the 2026 refactoring of the municipal Bluebook citation
validator.  All 20 critical bugs and 5 major bugs listed above have been
resolved in the new package.*
