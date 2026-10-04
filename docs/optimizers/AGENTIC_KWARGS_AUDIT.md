# Agentic `**kwargs` Audit

Date: 2026-02-25

## Scope
- `ipfs_datasets_py/ipfs_datasets_py/optimizers/agentic/**/*.py`

## Method
- AST scan for function signatures with a variadic keyword argument (`**kwargs`).

## Findings
- Before cleanup: 2 occurrences, both in `agentic/methods/actor_critic.py`
  - `ActorCriticOptimizer.__init__(..., **_)`
  - `ActorCriticOptimizer.optimize(..., **_)`
- After cleanup: 0 occurrences.

## Changes
- Replaced variadic signatures with typed optional parameters:
  - `extra_init_options: Optional[Dict[str, Any]] = None`
  - `extra_optimize_options: Optional[Dict[str, Any]] = None`
- File updated:
  - `ipfs_datasets_py/ipfs_datasets_py/optimizers/agentic/methods/actor_critic.py`

## Regression Coverage
- Updated tests in:
  - `ipfs_datasets_py/tests/unit/optimizers/agentic/test_actor_critic.py`
- Added checks for typed extras:
  - init stores `extra_init_options`
  - optimize accepts `extra_optimize_options` and returns `OptimizationResult`
