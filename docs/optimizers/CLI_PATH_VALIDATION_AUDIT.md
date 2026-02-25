# CLI Path Validation Audit

Date: 2026-02-25

## Summary
The optimizer CLI stack now routes file inputs and outputs through a shared path validation module. The module blocks path traversal, restricted system directories, and sensitive filenames while enforcing extension, size, and overwrite rules. This audit documents coverage, controls, tests, and remaining work.

## Scope
In scope:
- Optimizer CLI entry points that accept file paths.
- File I/O performed directly by CLI wrappers.
- Shared path validation utilities in `optimizers/common/path_validator.py`.

Out of scope (for this audit phase):
- Non-CLI internal file I/O outside optimizer modules.
- Subprocess execution policies (tracked separately).
- Network paths, remote storage, or external services.

## Controls Implemented
The shared module provides:
- Path traversal prevention (`../` and absolute path escapes).
- Base directory restriction (relative paths resolve under a controlled root).
- Optional symlink blocking (default deny for inputs).
- System path blocking: `/etc`, `/sys`, `/proc`, `/dev`, `/boot`, `/root`, `/var/run`, `/var/log`, `/usr/bin`, `/usr/sbin`, `/sbin`, `/bin`.
- Sensitive filename blocking: `passwd`, `shadow`, `sudoers`, `hosts`, SSH keys, `.env`, `.git-credentials`, etc.
- Extension allowlist enforcement.
- File size limits for inputs.
- Overwrite protection for outputs.

## Integration Coverage
### Updated CLI wrappers
- `optimizers/graphrag/cli_wrapper.py`
  - `_safe_resolve()` now delegates to `validate_input_path()` or `validate_output_path()` and rethrows as `PathResolutionError`.
- `optimizers/logic_theorem_optimizer/cli_wrapper.py`
  - `_safe_resolve()` now delegates to shared validation and rethrows as `ValueError` for CLI output consistency.
- `optimizers/agentic/cli.py`
  - Config load/save paths validated via `validate_input_path()` / `validate_output_path()`.
  - `cmd_validate()` input uses `validate_input_path()` prior to sanitizer checks.

### Remaining integration targets
- Non-CLI file I/O in optimizer modules (e.g., query visualizations, caches, reports).
- Additional CLI files outside the core wrappers (if they accept paths).

## Tests
- `tests/test_batch_265_path_validation_security.py`
  - 41 tests covering path traversal, system path blocking, sensitive filename blocking, symlink handling, extension checks, size limits, overwrite protection, and edge cases.
  - All tests passing.

## Findings
- No regressions detected in CLI handling after introducing shared validation.
- CLI path resolution now uses a single, auditable policy surface.

## Limitations
- Not all non-CLI file I/O is covered; only CLI path entry points are validated here.
- Base directory enforcement uses current working directory when not specified.
- Some modules still use custom file access patterns and need migration to `safe_open()`.

## Next Steps
1. Extend path validation to non-CLI file I/O in optimizer modules.
2. Add focused CLI wrapper tests for `PathValidationError` propagation.
3. Document any additional CLI entry points that accept file paths.

## References
- `optimizers/common/path_validator.py`
- `tests/test_batch_265_path_validation_security.py`
- `optimizers/graphrag/cli_wrapper.py`
- `optimizers/logic_theorem_optimizer/cli_wrapper.py`
- `optimizers/agentic/cli.py`
