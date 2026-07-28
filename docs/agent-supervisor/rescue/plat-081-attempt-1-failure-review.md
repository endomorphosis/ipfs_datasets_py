# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `validation_command_failed`, `large_or_undeclared_refactor`
- Finding codes: none

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `benchmarks/semantic_roundtrip/constructors/typed_deontic.py`
- `tests/unit/benchmarks/semantic_roundtrip`
- `workspace/benchmarks/semantic-roundtrip-compositions/plateau_edit_wave_receipts/legal_doc_1.json`

### Failed validation commands
- `PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=15`
Re-run these commands after edits and keep them green before exit.

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
