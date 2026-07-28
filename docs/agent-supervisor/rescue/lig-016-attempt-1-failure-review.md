# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `incomplete_expected_outputs`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `output_too_large`, `patch_parse_error`, `patch_too_large`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `tests/fixtures/logic/admissibility`
- `tests/integration/logic/test_intent_admissibility_gate.py`

### Missing or unfinished expected outputs
Implement **every** declared output before finishing the attempt:
- create/update `tests/fixtures/logic/admissibility`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
