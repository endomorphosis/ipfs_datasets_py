# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `validation_command_failed`
- Finding codes: none

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `scripts/validation/validate_accelerate_duckdb_quack_release.py`
- `tests/integration/test_accelerate_duckdb_quack_release.py`

### Failed validation commands
- `python -m pytest -q tests/integration/test_accelerate_duckdb_quack_release.py`
Re-run these commands after edits and keep them green before exit.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
