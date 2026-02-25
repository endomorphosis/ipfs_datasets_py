# Deprecation Audit Report (Optimizers)

Date: 2026-02-25

## Scope

- `ipfs_datasets_py/ipfs_datasets_py/optimizers/**/*.py`

## Audit Query

Searched for removal markers in source:

- `TODO: remove`
- `TODO remove`
- `remove after`

## Result

- No matching removal markers were found in optimizer Python modules.
- No methods currently require adding `@deprecated` to satisfy the
  "TODO remove" policy.

## Follow-up

- Keep this grep audit in recurring maintenance.
- If future removal markers are introduced, add:
  - explicit `@deprecated` annotation
  - migration note in docstring
  - changelog deprecation entry and removal window
