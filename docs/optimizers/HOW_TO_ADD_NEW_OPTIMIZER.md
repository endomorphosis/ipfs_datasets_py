# How to Add a New Optimizer

This guide explains how to add a new optimizer package under `ipfs_datasets_py/optimizers/` so it is consistent with the existing GraphRAG, logic, and agentic implementations.

## 1) Pick the package shape

Create a new folder:

- `ipfs_datasets_py/optimizers/<your_optimizer>/`

Recommended starter files:

- `__init__.py` (public exports)
- `exceptions.py` (package-specific exceptions that inherit from `common.exceptions`)
- `config.py` (typed config dataclasses if needed)
- `optimizer.py` (main `BaseOptimizer` implementation)
- `critic.py` (optional `BaseCritic` implementation)
- `cli_wrapper.py` (optional CLI entrypoint)

## 2) Implement the core contract

All optimizers should align with `common/base_optimizer.py`.

Required lifecycle methods:

- `generate(input_data, context)`
- `critique(artifact, context)`
- `optimize(artifact, score, feedback, context)`
- `validate(artifact, context)`

Use `run_session()` from `BaseOptimizer` to orchestrate the full loop.

## 3) Reuse shared primitives

Prefer shared components before adding package-local utilities:

- `common/base_optimizer.py`
- `common/base_critic.py`
- `common/base_session.py`
- `common/base_harness.py`
- `common/exceptions.py`
- `common/backend_selection.py`
- `common/metrics_prometheus.py`

## 4) Define exception hierarchy

In your package `exceptions.py`, create a package root exception that inherits from `OptimizerError`, then add focused subclasses.

Example pattern:

- `<YourPackage>Error(OptimizerError)`
- `<YourPackage>ExtractionError(ExtractionError)`
- `<YourPackage>ValidationError(ValidationError)`

## 5) Add typed config/context objects

Avoid unbounded `Dict[str, Any]` where possible.

- Use dataclasses for config and runtime context.
- Provide `from_dict()` / `to_dict()` helpers for CLI and serialization interoperability.

## 6) Add tests first-class

Add unit tests under:

- `tests/unit/optimizers/<your_optimizer>/`

Minimum recommended coverage:

- import/smoke tests
- happy-path `run_session()` flow
- error-path tests for typed exceptions
- serialization round-trip for key data objects
- CLI argument parsing if CLI exists

## 7) Wire package exports

Update `__init__.py` in your package with explicit exports and stable names.

If exposing from `optimizers/__init__.py`, add only stable API surface.

## 8) Add documentation

Update:

- `ipfs_datasets_py/ipfs_datasets_py/optimizers/README.md` (overview + quick usage)
- `ipfs_datasets_py/ipfs_datasets_py/optimizers/TODO.md` (track backlog/progress)

Optionally add a deeper guide under `docs/optimizers/`.

## 9) CLI integration checklist (optional)

If your optimizer has a CLI:

- parse args with clear defaults
- return integer exit codes (`0` success, non-zero failure)
- resolve paths safely (`Path.resolve()`)
- mask secrets in output and logs
- add a smoke test for each top-level command

## 10) Observability checklist

For production-grade optimizer runs:

- structured logs for session start/end and score deltas
- timing (`execution_time_ms`) in results where applicable
- optional Prometheus hooks for scores/iterations/errors
- optional OpenTelemetry hooks behind feature flags

## Minimal implementation skeleton

```python
from ipfs_datasets_py.optimizers.common.base_optimizer import BaseOptimizer
from ipfs_datasets_py.optimizers.common.base_critic import CriticResult


class MyOptimizer(BaseOptimizer):
    def generate(self, input_data, context):
        return {"artifact": input_data}

    def critique(self, artifact, context):
        return CriticResult(score=0.5, feedback=["improve"], dimensions={})

    def optimize(self, artifact, score, feedback, context):
        return artifact

    def validate(self, artifact, context):
        return True
```

## Done criteria before merge

- tests pass for new package + touched shared code
- no broad `except Exception` where typed exceptions apply
- docs updated (`README.md` + package guide)
- TODO item added/updated with completion note
