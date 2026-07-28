# Implementation failure review

- Decision: `reject`
- Reason codes: `hard_deny_findings`, `proposal_gate_failed`
- Finding codes: `secret_change_forbidden`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/logic/proof_corpus/applicability.py`
- `ipfs_datasets_py/logic/proof_corpus/audit.py`
- `tests/unit/logic/proof_corpus/test_applicability_audit.py`

### Hard deny
Secret, protected-path, submodule, symlink, or test-weakening findings cannot be accepted. Remove those changes entirely.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
