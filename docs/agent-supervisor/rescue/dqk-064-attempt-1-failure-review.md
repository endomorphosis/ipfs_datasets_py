# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `validation_command_failed`
- Finding codes: none

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/embeddings/shard_embeddings_engine.py`
- `ipfs_datasets_py/mcp_server/tools/vector_tools/shared_state.py`
- `ipfs_datasets_py/mcp_server/tools/vector_tools/vector_store_management.py`
- `ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py`
- `ipfs_datasets_py/processors/storage/ipld/vector_store.py`
- `ipfs_datasets_py/vector_stores/api.py`
- `ipfs_datasets_py/vector_stores/faiss_store.py`
- `ipfs_datasets_py/vector_stores/ipld.py`
- `ipfs_datasets_py/vector_stores/ipld_vector_store.py`
- `ipfs_datasets_py/vector_stores/management_engine.py`
- `ipfs_datasets_py/vector_stores/manager.py`
- `tests/e2e/vector_stores/test_duckdb_only_vector_metadata.py`

### Failed validation commands
- `python -m pytest -q tests/e2e/vector_stores/test_duckdb_only_vector_metadata.py`
Re-run these commands after edits and keep them green before exit.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
