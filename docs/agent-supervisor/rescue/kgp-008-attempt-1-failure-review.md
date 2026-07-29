# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `scope_expansion_denied`, `incomplete_expected_outputs`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `path_outside_scope`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `tests/chaos/knowledge_graphs/test_crash_recovery.py`
- `tests/integration/knowledge_graphs/concurrency`

### Missing or unfinished expected outputs
Implement **every** declared output before finishing the attempt:
- create/update `tests/integration/knowledge_graphs/concurrency`

### Out-of-scope / denied paths
These paths are outside task-owned scope or were denied by deterministic adjudication. Prefer in-place edits of declared outputs; do not invent new modules or rename files unless both names are listed in Outputs/Predicted files.
- `tests/chaos/knowledge_graphs/__init__.py`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
