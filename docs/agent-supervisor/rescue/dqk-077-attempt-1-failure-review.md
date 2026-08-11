# Implementation failure review

- Decision: `reject`
- Reason codes: `hard_deny_findings`, `scope_expansion_denied`, `proposal_gate_failed`, `large_or_undeclared_refactor`
- Finding codes: `path_outside_scope`, `secret_change_forbidden`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `ipfs_datasets_py/alerts/alert_manager.py`
- `ipfs_datasets_py/audit/audit_logger.py`
- `ipfs_datasets_py/duckdb_control/observability_adapters.py`
- `ipfs_datasets_py/logic/observability/structured_logging.py`
- `ipfs_datasets_py/logic/security/audit_log.py`
- `ipfs_datasets_py/mcp_server/logger.py`
- `ipfs_datasets_py/optimizers/common/logging_audit.py`
- `ipfs_datasets_py/optimizers/graphrag/audit_logger.py`
- `ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py`
- `tests/integration/test_duckdb_observability_shadow.py`

### Out-of-scope / denied paths
These paths are outside task-owned scope or were denied by deterministic adjudication. Prefer in-place edits of declared outputs; do not invent new modules or rename files unless both names are listed in Outputs/Predicted files.
- `ipfs_datasets_py.egg-info/PKG-INFO`
- `ipfs_datasets_py.egg-info/SOURCES.txt`
- `ipfs_datasets_py.egg-info/requires.txt`
- `ipfs_datasets_py.egg-info/top_level.txt`

### Refactor constraints
Large refactors are allowed **only inside declared output paths**. Do not extract helpers into new undeclared files; do not touch submodule gitlinks (for example `ipfs_accelerate_py/`); do not delete or weaken tests.

### Hard deny
Secret, protected-path, submodule, symlink, or test-weakening findings cannot be accepted. Remove those changes entirely.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
