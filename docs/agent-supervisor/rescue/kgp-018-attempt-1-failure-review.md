# Implementation failure review

- Decision: `reject`
- Reason codes: `hard_deny_findings`, `scope_expansion_denied`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `path_outside_scope`, `test_weakening_forbidden`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/ipfs_datasets_cli.py`
- `tests/cli/test_graph_commands.py`
- `tests/knowledge_graphs/conformance/test_cli.py`

### Out-of-scope / denied paths
These paths are outside task-owned scope or were denied by deterministic adjudication. Prefer in-place edits of declared outputs; do not invent new modules or rename files unless both names are listed in Outputs/Predicted files.
- `ipfs_datasets_cli.py`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Hard deny
Secret, protected-path, submodule, symlink, or test-weakening findings cannot be accepted. Remove those changes entirely.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
