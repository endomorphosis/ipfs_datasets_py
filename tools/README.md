# ⚠️ DEPRECATED - tools/ Directory

**This directory is deprecated and will be removed in a future release.**

## Migration Information

All tools have been moved to their appropriate production locations:

### File Migrations

| Old Location | New Location | Purpose |
|--------------|--------------|---------|
| `tools/dependency_checker.py` | `scripts/utilities/dependency_checker.py` | Comprehensive dependency checker |
| `tools/test_dashboard.py` | `scripts/testing/test_dashboard.py` | Dashboard testing script |
| `tools/run_mcp_dashboard.sh` | `scripts/run_mcp_dashboard.sh` | MCP dashboard launcher |
| `tools/run_mcp_dashboard_quick.sh` | `scripts/run_mcp_dashboard_quick.sh` | Quick MCP dashboard launcher |

## Action Required

If you have any scripts or documentation referencing files in `tools/`, please update them to use the new locations listed above.

### Updated Docker References

All Docker files and docker-compose configurations have been updated to use the new paths:
- `COPY scripts/utilities/dependency_checker.py ...`
- `python scripts/utilities/dependency_checker.py ...`

### Updated Shell Scripts

The launcher scripts now reference the new locations:
- `scripts/run_mcp_dashboard.sh`
- `scripts/run_mcp_dashboard_quick.sh`

## Timeline

- **Deprecated:** 2026-01-30
- **Removal:** TBD (will be announced in release notes)

## Questions?

If you have any questions about this migration, please open an issue on GitHub.
