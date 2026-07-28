# Implementation failure review

- Decision: `reject`
- Reason codes: `hard_deny_findings`, `proposal_gate_failed`
- Finding codes: `secret_change_forbidden`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/logic/admissibility/api.py`
- `ipfs_datasets_py/mcp_server/tools/logic_admissibility_enforcement.py`
- `tests/unit/logic/admissibility/test_api.py`
- `tests/unit/mcp_server/test_logic_admissibility_enforcement.py`

### Hard deny
Secret, protected-path, submodule, symlink, or test-weakening findings cannot be accepted. Remove those changes entirely.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
