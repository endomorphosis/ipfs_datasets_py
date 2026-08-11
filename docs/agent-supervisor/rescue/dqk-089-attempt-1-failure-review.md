# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `validation_command_failed`
- Finding codes: none

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/core_operations/dataset_converter.py`
- `ipfs_datasets_py/core_operations/dataset_loader.py`
- `ipfs_datasets_py/core_operations/dataset_saver.py`
- `ipfs_datasets_py/ducklake/adapters.py`
- `ipfs_datasets_py/knowledge_graphs/storage/parquet.py`
- `ipfs_datasets_py/processors/serialization/ipfs_parquet_to_car.py`
- `ipfs_datasets_py/processors/serialization/jsonl_to_parquet.py`
- `tests/integration/ducklake/test_parquet_producer_shadow.py`

### Failed validation commands
- `python -m pytest -q tests/integration/ducklake/test_parquet_producer_shadow.py`
Re-run these commands after edits and keep them green before exit.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
