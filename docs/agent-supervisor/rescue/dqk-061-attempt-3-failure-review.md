# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `validation_command_failed`
- Finding codes: none

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/knowledge_graphs/catalog/store.py`
- `ipfs_datasets_py/knowledge_graphs/service.py`
- `ipfs_datasets_py/knowledge_graphs/storage/hybrid.py`
- `tests/e2e/knowledge_graphs/test_duckdb_only_graph_control.py`

### Failed validation commands
- `python -m pytest -q tests/e2e/knowledge_graphs/test_duckdb_only_graph_control.py`
Re-run these commands after edits and keep them green before exit.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
