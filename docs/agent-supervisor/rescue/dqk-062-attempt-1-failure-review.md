# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `scope_expansion_denied`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `patch_parse_error`, `path_outside_scope`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/embeddings/shard_embeddings_engine.py`
- `ipfs_datasets_py/mcp_server/tools/vector_tools/shared_state.py`
- `ipfs_datasets_py/mcp_server/tools/vector_tools/vector_store_management.py`
- `ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py`
- `ipfs_datasets_py/processors/storage/ipld/vector_store.py`
- `ipfs_datasets_py/vector_stores/api.py`
- `ipfs_datasets_py/vector_stores/elasticsearch_store.py`
- `ipfs_datasets_py/vector_stores/faiss_store.py`
- `ipfs_datasets_py/vector_stores/ipld.py`
- `ipfs_datasets_py/vector_stores/ipld_vector_store.py`
- `ipfs_datasets_py/vector_stores/management_engine.py`
- `ipfs_datasets_py/vector_stores/manager.py`
- `ipfs_datasets_py/vector_stores/qdrant_store.py`
- `tests/integration/vector_stores/test_duckdb_shadow_catalog.py`

### Out-of-scope / denied paths
These paths are outside task-owned scope or were denied by deterministic adjudication. Prefer in-place edits of declared outputs; do not invent new modules or rename files unless both names are listed in Outputs/Predicted files.
- `tests/integration/vector_stores/__init__.py`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
