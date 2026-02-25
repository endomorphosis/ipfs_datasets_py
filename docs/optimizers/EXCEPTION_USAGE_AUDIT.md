# Exception Usage Audit

Date: 2026-02-25

## Scope
- `ipfs_datasets_py/ipfs_datasets_py/optimizers/**/*.py`

## Audit Method
- AST scan of all optimizer Python modules for `except` handlers.
- Broad-catch focus:
  - `except Exception`
  - bare `except`
  - `except BaseException`

## Summary
- Files scanned: `185`
- Files with at least one `except`: `99`
- Total `except` handlers: `537`
- `except Exception` handlers: `11` (before cleanup)
- bare `except` handlers: `0`
- `except BaseException` handlers: `0`

## Cleanup Applied
- Narrowed broad handlers in:
  - `ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/semantic_deduplicator_cached.py`
    - replaced 3x `except Exception` with typed exception groups for embedding generation and persistence helpers.
  - `ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/validation_cache.py`
    - replaced 2x `except Exception` with typed groups for JSON/disk load-save paths.
- Added regression coverage:
  - `ipfs_datasets_py/tests/unit/optimizers/graphrag/test_validation_cache.py`
    - invalid JSON load warning path
    - filesystem save error warning path
  - `ipfs_datasets_py/tests/unit/optimizers/graphrag/test_semantic_entity_deduplication.py`
    - embedding callback failures now assert `ExtractionError`
    - missing backend path asserts `ConfigurationError`

## GraphRAG Migration Slice
- `ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/semantic_deduplicator.py`
  - embedding-generation failures now raise `ExtractionError` (instead of `RuntimeError`)
  - missing `sentence-transformers` backend now raises `ConfigurationError`

## Remaining Broad Catches (intentional / pending)
- `ipfs_datasets_py/ipfs_datasets_py/optimizers/common/exceptions.py`
  - `wrap_exceptions(...)` intentionally catches arbitrary non-base exceptions to wrap into typed `OptimizerError`.
- `ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag_repl.py`
  - 5 broad catches remain in interactive REPL boundaries (candidate for follow-up narrowing).

## Validation
- `pytest -q tests/unit/optimizers/graphrag/test_validation_cache.py`
- Result: `20 passed`
