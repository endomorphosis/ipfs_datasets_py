# Contributing to `ipfs_datasets_py.optimizers`

This guide defines contribution standards for the optimizers module.

## Scope

This document applies to:

- `ipfs_datasets_py/optimizers/common`
- `ipfs_datasets_py/optimizers/graphrag`
- `ipfs_datasets_py/optimizers/logic_theorem_optimizer`
- `ipfs_datasets_py/optimizers/agentic`

## PR Guidelines

Before opening a PR:

- Keep changes focused to one primary concern (correctness, typing, perf, docs, or observability).
- Update `ipfs_datasets_py/optimizers/TODO.md`:
  - mark completed items as `[x]`
  - add a short `Done YYYY-MM-DD` note with files/tests touched
- Update `ipfs_datasets_py/optimizers/CHANGELOG.md` for user-facing behavior or API changes.
- Add or update tests for all behavior changes.
- Run relevant test subsets locally.
- If public API behavior changes, include migration notes in PR description.

## Batch Commit Conventions

Optimizer work is tracked in numbered "batch" increments.

- Preferred branch naming:
  - `optimizers/batch-<N>-<short-topic>`
- Preferred commit subject format:
  - `optimizers(batch-<N>): <summary>`
- Preferred test file naming for batch coverage:
  - `tests/unit/optimizers/.../test_batch_<N>_<topic>.py`

If a batch includes multiple concerns, split into separate commits with one concern per commit.

## Required Quality Checks

Run what is relevant for touched code:

```bash
# Example focused unit run
pytest -q tests/unit/optimizers/graphrag

# Example strict typing slice
mypy --strict --follow-imports=skip ipfs_datasets_py/optimizers/graphrag/<module>.py
```

At minimum, each PR should include:

- green tests for touched modules
- no new broad `except Exception` handlers (unless explicitly intentional and documented)
- TODO and changelog updates when applicable

## API Stability Rules

- Public APIs follow semantic versioning policy documented in `optimizers/CHANGELOG.md`.
- Deprecated public APIs must include:
  - changelog deprecation note
  - migration guidance
  - removal timeline (minimum two minor releases unless security/correctness requires faster action)

## Documentation Rules

When adding or changing behavior:

- update nearby docstrings
- update `docs/optimizers/*` guides when operator/developer workflows change
- keep examples executable when practical
