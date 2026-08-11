# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `scope_expansion_denied`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `path_outside_scope`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py`
- `ipfs_datasets_py/logic/CEC/optimization/formula_cache.py`
- `ipfs_datasets_py/logic/TDFOL/tdfol_proof_cache.py`
- `ipfs_datasets_py/logic/common/proof_cache.py`
- `ipfs_datasets_py/logic/external_provers/proof_cache.py`
- `ipfs_datasets_py/logic/flogic/flogic_proof_cache.py`
- `ipfs_datasets_py/logic/hammers/proof_cache.py`
- `ipfs_datasets_py/logic/integration/caching/ipfs_proof_cache.py`
- `ipfs_datasets_py/logic/integration/caching/proof_cache.py`
- `ipfs_datasets_py/logic/integration/proof_cache.py`
- `ipfs_datasets_py/logic/legal_ir/proof_cache.py`
- `ipfs_datasets_py/logic/proof_corpus/store.py`
- `ipfs_datasets_py/logic/security_ir/constraint_cache.py`
- `ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_cache.py`
- `tests/integration/logic/test_duckdb_proof_authority.py`

### Out-of-scope / denied paths
These paths are outside task-owned scope or were denied by deterministic adjudication. Prefer in-place edits of declared outputs; do not invent new modules or rename files unless both names are listed in Outputs/Predicted files.
- `ipfs_datasets_py.egg-info/PKG-INFO`
- `ipfs_datasets_py.egg-info/SOURCES.txt`
- `ipfs_datasets_py.egg-info/requires.txt`
- `ipfs_datasets_py.egg-info/top_level.txt`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
