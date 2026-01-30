# CLI Error Auto-Healing System

## Overview

The CLI Error Auto-Healing System automatically captures errors from `ipfs-datasets` CLI tools, creates GitHub issues with detailed stack traces and logs, and triggers auto-healing workflows to fix the issues.

## Features

✅ **Automatic Error Capture**
- Captures all unhandled exceptions in CLI tools
- Includes full stack traces
- Captures recent log output (last 100 lines)
- Records command and arguments

✅ **GitHub Integration**
- Automatic issue creation via GitHub CLI
- Detailed issue bodies with error context
- Auto-healing labels for workflow triggers

✅ **Context Collection**
- Python version and platform information
- Working directory
- Command line arguments
- Additional context (if provided)

## How It Works

```
CLI Command → Error Occurs → cli_error_reporter.py
    → GitHub Issue Created (labels: bug, cli, auto-healing)
    → auto_healing_coordinator → GitHub Actions → Draft PR
```

## Installation

The CLI error handler is automatically installed when you run `ipfs-datasets` CLI tools. No manual configuration is needed.

## Usage

### Automatic (Default Behavior)

When you run any `ipfs-datasets` command and an error occurs, it will be automatically captured:

```bash
# Any CLI command that fails will be reported
./ipfs-datasets info status
./ipfs-datasets dataset load squad
./ipfs-datasets vector search "query"
```

If an error occurs, the system will:
1. Capture the full stack trace
2. Collect recent logs
3. Create a GitHub issue with all context
4. Trigger the auto-healing workflow

### Manual Error Reporting

You can also manually report errors in your CLI tools:

```python
from ipfs_datasets_py.error_reporting.cli_error_reporter import get_cli_error_reporter

try:
    # Your CLI operation
    perform_operation()
except Exception as e:
    reporter = get_cli_error_reporter()
    reporter.report_cli_error(
        error=e,
        command="my-command",
        args=["arg1", "arg2"],
        logs=get_recent_logs(),  # Optional
        context={'custom': 'data'},  # Optional
        create_issue=True
    )
    raise  # Re-raise to exit with error code
```

## GitHub Issue Format

When an error is captured, the system creates a GitHub issue like this:

**Title:** `[CLI Error] ValueError in 'ipfs-datasets': Invalid dataset name`

**Body:**
```markdown
## CLI Tool Error Report

**Command:** `ipfs-datasets`
**Arguments:** `dataset load invalid-name`
**Error Type:** `ValueError`
**Timestamp:** 2024-01-30T23:00:00.000Z

---

### Error Message

```
Invalid dataset name: 'invalid-name'
```

### Stack Trace

```python
Traceback (most recent call last):
  File "ipfs_datasets_cli.py", line 42, in main
    load_dataset(args.dataset_name)
  File "dataset_loader.py", line 15, in load_dataset
    raise ValueError(f"Invalid dataset name: '{name}'")
ValueError: Invalid dataset name: 'invalid-name'
```

### Recent Logs

```
[INFO] Starting dataset loader...
[DEBUG] Validating dataset name: invalid-name
[ERROR] Dataset validation failed
```

### Environment

**Python Version:** `3.12.0 (main, Oct  2 2023, 12:00:00)`
**Platform:** `linux`
**Working Directory:** `/home/user/project`

---

## Auto-Healing

This issue was automatically created by the CLI error reporting system.
The auto-healing workflow will attempt to create a draft PR to fix this issue.

**Labels:** `bug`, `cli`, `auto-healing`
```

## Integration with Existing CLI Tools

### ipfs_datasets_cli.py

The main CLI already has the error handler installed:

```python
# Install CLI error handler early
try:
    from ipfs_datasets_py.error_reporting.cli_error_reporter import install_cli_error_handler
    install_cli_error_handler()
except ImportError:
    # Error reporting not available, continue without it
    pass
```

### Other CLI Tools

To add error reporting to other CLI tools:

```python
#!/usr/bin/env python3
import sys
from ipfs_datasets_py.error_reporting.cli_error_reporter import install_cli_error_handler

# Install error handler at the start of your CLI
install_cli_error_handler()

# Rest of your CLI code...
def main():
    # Your CLI logic
    pass

if __name__ == '__main__':
    main()
```

## Testing

Run the test suite:

```bash
python tests/unit_tests/test_cli_error_reporter_standalone.py
```

Test output:
```
Running CLI Error Reporter Tests...
============================================================
✓ test_initialization passed
✓ test_format_cli_error_basic passed
✓ test_format_cli_error_with_logs passed
✓ test_format_cli_error_truncates_long_logs passed
✓ test_create_github_issue_body passed
✓ test_report_cli_error_without_issue passed
✓ test_error_history_limit passed
✓ test_format_cli_error_with_context passed
✓ test_get_cli_error_reporter_singleton passed
============================================================
Results: 9 passed, 0 failed
```

## Configuration

### Environment Variables

- `GITHUB_TOKEN` or `GH_TOKEN` - GitHub personal access token for creating issues
- `GITHUB_REPOSITORY` - Repository name (default: `endomorphosis/ipfs_datasets_py`)

### Error History Limit

The system maintains a history of the last 50 errors. You can change this:

```python
from ipfs_datasets_py.error_reporting.cli_error_reporter import get_cli_error_reporter

reporter = get_cli_error_reporter()
reporter.max_history = 100  # Keep last 100 errors
```

## Auto-Healing Workflow

After creating a GitHub issue, the system triggers the auto-healing workflow:

1. **Issue Created** - GitHub issue with labels `bug`, `cli`, `auto-healing`
2. **Auto-Healing Triggered** - `auto_healing_coordinator` is invoked
3. **Draft PR Created** - GitHub Actions workflow creates a draft PR
4. **Copilot Agent** - GitHub Copilot analyzes and suggests fixes
5. **Review and Merge** - Human reviews the fix and merges

## Security Considerations

- **Stack traces** are truncated to 2000 characters
- **Logs** are truncated to last 100 lines (3000 characters max)
- **No sensitive data** is exposed in error messages
- **GitHub token** is stored securely in environment variables

## Troubleshooting

### GitHub CLI Not Available

If GitHub CLI is not installed:

```bash
# Install GitHub CLI
sudo apt install gh  # Debian/Ubuntu
brew install gh      # macOS

# Authenticate
gh auth login
```

### Errors Not Being Reported

1. Check that the error handler is installed (should be automatic)
2. Verify GitHub token is set: `echo $GITHUB_TOKEN`
3. Check GitHub CLI authentication: `gh auth status`
4. Review logs for error reporting failures

### Issues Not Being Created

1. Ensure GitHub CLI is authenticated
2. Verify repository permissions
3. Check network connectivity
4. Review error logs for GitHub API failures

## Files

**Created:**
- `ipfs_datasets_py/error_reporting/cli_error_reporter.py` - CLI error reporter
- `tests/unit_tests/test_cli_error_reporter_standalone.py` - Test suite
- `docs/CLI_ERROR_AUTO_HEALING.md` - This documentation

**Modified:**
- `ipfs_datasets_cli.py` - Added error handler installation

## Comparison with Dashboard Error Reporting

| Feature | Dashboard Errors | CLI Errors |
|---------|-----------------|------------|
| **Source** | JavaScript in browser | Python CLI tools |
| **Capture** | JS errors, console logs, user actions | Stack traces, command args, logs |
| **Labels** | `bug`, `javascript`, `dashboard`, `auto-healing` | `bug`, `cli`, `auto-healing` |
| **Context** | Browser info, session ID | Python version, platform, cwd |
| **Workflow** | Same auto-healing workflow | Same auto-healing workflow |

Both systems integrate with the same auto-healing infrastructure and create similar GitHub issues.

## Example: Complete Error Report

```python
# Example error that would be reported
def load_dataset(name):
    if not validate_name(name):
        raise ValueError(f"Invalid dataset name: '{name}'")
    # ... rest of the function

# When this error occurs, the system creates:
{
    'source': 'cli_tool',
    'command': 'ipfs-datasets',
    'args': ['dataset', 'load', 'invalid-name'],
    'error_type': 'ValueError',
    'error_message': "Invalid dataset name: 'invalid-name'",
    'stack_trace': 'Traceback (most recent call last)...',
    'timestamp': '2024-01-30T23:00:00.000Z',
    'python_version': '3.12.0 (main, Oct  2 2023, 12:00:00)',
    'platform': 'linux',
    'cwd': '/home/user/project',
    'logs': 'Recent log output...',
    'logs_truncated': False
}
```

## Future Enhancements

- [ ] Error deduplication to prevent duplicate issues
- [ ] Severity classification based on error type
- [ ] Integration with monitoring/alerting systems
- [ ] Support for error recovery suggestions
- [ ] Offline error queuing for later reporting

## References

- [Dashboard Error Auto-Healing](javascript_error_auto_healing.md)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [Auto-Healing Coordinator](../ipfs_datasets_py/mcp_server/tools/software_engineering_tools/auto_healing_coordinator.py)
- [Error Reporting Infrastructure](../ipfs_datasets_py/error_reporting/)

---

**Status:** ✅ Complete and Tested  
**Version:** 1.0.0  
**Last Updated:** 2024-01-30
