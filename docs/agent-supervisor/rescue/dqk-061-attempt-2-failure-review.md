# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `scope_expansion_denied`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `patch_parse_error`, `path_outside_scope`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/knowledge_graphs/catalog/store.py`
- `ipfs_datasets_py/knowledge_graphs/service.py`
- `ipfs_datasets_py/knowledge_graphs/storage/hybrid.py`
- `tests/e2e/knowledge_graphs/test_duckdb_only_graph_control.py`

### Out-of-scope / denied paths
These paths are outside task-owned scope or were denied by deterministic adjudication. Prefer in-place edits of declared outputs; do not invent new modules or rename files unless both names are listed in Outputs/Predicted files.
- `tests/e2e/knowledge_graphs/__init__.py`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
