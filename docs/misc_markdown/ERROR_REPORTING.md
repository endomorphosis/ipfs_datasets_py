# Error Reporting System

The IPFS Datasets Python project includes an automatic error reporting system that converts runtime errors into GitHub issues. This system helps track and fix bugs by automatically creating detailed issue reports when errors occur.

## Features

- **Automatic GitHub Issue Creation**: Runtime errors are automatically converted to GitHub issues
- **Error Deduplication**: Prevents duplicate issues for the same error
- **Rate Limiting**: Configurable limits to prevent spam
- **Rich Context**: Issues include stack traces, environment info, and recent logs
- **Multi-Source Support**: Works with Python, JavaScript, and Docker container errors
- **Configurable**: Enable/disable via environment variables

## Components

### 1. Python Error Reporting

Runtime errors in Python code (MCP server, tools, etc.) are automatically reported.

**Features:**
- Global exception handler for uncaught exceptions
- Function decorator for specific functions
- Context manager for code blocks
- Automatic log collection

### 2. JavaScript Error Reporting

Client-side errors in the dashboard are captured and reported.

**Features:**
- Global error event handlers
- Unhandled promise rejection handling
- Error batching to reduce server load
- Browser context included in reports

### 3. Docker Container Error Reporting

Errors in Docker containers are captured and reported.

**Features:**
- Python interpreter crashes
- Container startup failures
- Runtime errors in containerized services

## Configuration

Error reporting is configured via environment variables:

### Core Settings

```bash
# Enable/disable error reporting (default: true)
ERROR_REPORTING_ENABLED=true

# GitHub token for creating issues (required)
GITHUB_TOKEN=your_github_token

# GitHub repository (default: endomorphosis/ipfs_datasets_py)
GITHUB_REPOSITORY=owner/repo
```

### Rate Limiting

```bash
# Maximum issues per hour (default: 10)
ERROR_REPORTING_MAX_PER_HOUR=10

# Maximum issues per day (default: 50)
ERROR_REPORTING_MAX_PER_DAY=50

# Deduplication window in hours (default: 24)
ERROR_REPORTING_DEDUP_HOURS=24
```

### Context Settings

```bash
# Include stack trace in issues (default: true)
ERROR_REPORTING_INCLUDE_STACK=true

# Include environment info in issues (default: true)
ERROR_REPORTING_INCLUDE_ENV=true

# Include recent logs in issues (default: true)
ERROR_REPORTING_INCLUDE_LOGS=true

# Maximum log lines to include (default: 100)
ERROR_REPORTING_MAX_LOG_LINES=100
```

## Usage

### Python Usage

#### Automatic Error Reporting

The error reporter is automatically installed when the MCP server starts:

```python
from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

# Error reporting is automatically enabled
server = IPFSDatasetsMCPServer()
```

#### Manual Error Reporting

```python
from ipfs_datasets_py.error_reporting import error_reporter

try:
    # Your code here
    raise ValueError("Something went wrong")
except Exception as e:
    # Manually report error
    issue_url = error_reporter.report_error(
        e,
        source="My Application",
        additional_info="Extra context about the error",
    )
    print(f"Error reported: {issue_url}")
```

#### Function Decorator

```python
from ipfs_datasets_py.error_reporting import error_reporter

@error_reporter.wrap_function("Data Processing")
def process_data(data):
    # Any errors will be automatically reported
    return data.process()
```

#### Context Manager

```python
from ipfs_datasets_py.error_reporting import error_reporter

with error_reporter.context_manager("Database Operation"):
    # Any errors in this block will be reported
    database.connect()
    database.query()
```

### JavaScript Usage

The error reporter is automatically loaded in the dashboard:

```html
<!-- Include error reporter script -->
<script src="/static/js/error-reporter.js"></script>
```

Manual error reporting:

```javascript
try {
    // Your code here
    throw new Error("Something went wrong");
} catch (error) {
    // Manually report error
    window.reportError(error, {
        component: "Dashboard",
        action: "data_load",
    });
}
```

Disable error reporting:

```javascript
window.errorReporter.disable();
```

### Docker Usage

Error reporting is automatically enabled in Docker containers when the MCP server or dashboard is started.

To wrap custom commands with error reporting:

```bash
# In Dockerfile or docker-compose.yml
CMD ["python", "-m", "ipfs_datasets_py.docker_error_wrapper", "python", "-m", "my_module"]
```

## Issue Format

Created issues follow this format:

### Title
```
[Auto-Report] {ErrorType} in {Source}: {Error Message}
```

Example:
```
[Auto-Report] ValueError in MCP Tool: dataset_load: Invalid dataset name
```

### Body

The issue body includes:

1. **Error Details**
   - Error type
   - Error message
   - Source component
   - Timestamp

2. **Stack Trace**
   - Full Python/JavaScript stack trace

3. **Environment**
   - Python version
   - Platform
   - Operating system

4. **Recent Logs**
   - Last N lines from log files

5. **Additional Information**
   - Custom context provided
   - Function arguments
   - User agent (for JS errors)
   - URL (for JS errors)

### Labels

Issues are automatically labeled with:
- `bug`
- `auto-generated`
- `runtime-error`

## Deduplication

The system prevents duplicate issues using:

1. **Error Signature**: Hash of error type, message, and stack trace
2. **Time Window**: Configurable deduplication window (default: 24 hours)
3. **State Tracking**: Persistent state file tracks reported errors

If the same error occurs multiple times within the deduplication window, only one issue is created.

## Rate Limiting

Rate limits prevent the system from creating too many issues:

- **Hourly Limit**: Maximum issues per hour (default: 10)
- **Daily Limit**: Maximum issues per day (default: 50)

When limits are reached, errors are still logged but issues are not created.

## Security Considerations

### GitHub Token

The GitHub token must have the following permissions:
- `repo` scope (to create issues)

Store the token securely:
- Environment variable: `GITHUB_TOKEN`
- GitHub Actions secret (for CI/CD)
- Docker secret (for containers)

**Never commit the token to source code!**

### Sensitive Data

The error reporting system sanitizes data to avoid leaking sensitive information:

- Function arguments are included but may need manual review
- Environment variables are not included
- File paths are included (be cautious with private paths)

### Disabling in Production

If needed, disable error reporting in production:

```bash
ERROR_REPORTING_ENABLED=false
```

## Testing

Run tests for error reporting:

```bash
# Run all error reporting tests
pytest tests/error_reporting/

# Run specific test file
pytest tests/error_reporting/test_config.py
pytest tests/error_reporting/test_issue_creator.py
pytest tests/error_reporting/test_error_handler.py

# Run with coverage
pytest tests/error_reporting/ --cov=ipfs_datasets_py.error_reporting
```

## Troubleshooting

### Issues Not Being Created

1. **Check Configuration**
   ```bash
   echo $ERROR_REPORTING_ENABLED
   echo $GITHUB_TOKEN
   ```

2. **Check Logs**
   ```bash
   tail -f ~/.ipfs_datasets/mcp_server.log | grep -i error
   ```

3. **Verify GitHub Token**
   ```bash
   curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user
   ```

### Rate Limits Reached

If you're hitting rate limits:

1. **Increase Limits**
   ```bash
   ERROR_REPORTING_MAX_PER_HOUR=20
   ERROR_REPORTING_MAX_PER_DAY=100
   ```

2. **Fix Recurring Errors**
   - Check created issues for patterns
   - Fix the underlying bugs
   - Errors will stop being reported once fixed

### Duplicate Issues

If you're getting duplicate issues:

1. **Increase Deduplication Window**
   ```bash
   ERROR_REPORTING_DEDUP_HOURS=48
   ```

2. **Check State File**
   ```bash
   cat ~/.ipfs_datasets/error_reporting_state.json
   ```

## Integration with Auto-Healing

Error reporting integrates with the existing auto-healing system:

1. **Error Occurs** → Issue Created (via error reporting)
2. **Issue Created** → Draft PR Created (via issue-to-draft-pr workflow)
3. **Draft PR Created** → Copilot Invoked (via copilot-agent-autofix)
4. **Copilot Fixes** → PR Ready for Review

This creates a fully automated error detection and fixing pipeline.

## Examples

### Example 1: MCP Tool Error

When an MCP tool fails:

```python
# Tool execution
def load_dataset(name: str):
    if not name:
        raise ValueError("Dataset name is required")
```

Creates issue:
```
Title: [Auto-Report] ValueError in MCP Tool: load_dataset: Dataset name is required

Body:
# Automatic Error Report

## Error Details
**Type:** `ValueError`
**Message:** Dataset name is required
**Source:** MCP Tool: load_dataset
**Timestamp:** 2024-01-15T10:30:00

## Stack Trace
...
```

### Example 2: Dashboard JavaScript Error

When dashboard code fails:

```javascript
// Dashboard code
function loadData() {
    throw new Error("API request failed");
}
```

Creates issue:
```
Title: [Auto-Report] Error in MCP Dashboard JavaScript: API request failed

Body:
# Automatic Error Report

## Error Details
**Type:** `Error`
**Message:** API request failed
**Source:** MCP Dashboard JavaScript
**URL:** http://localhost:8899/dashboard

## Environment
**User Agent:** Mozilla/5.0 ...
**Browser:** Chrome 120.0
...
```

### Example 3: Docker Container Error

When container fails to start:

```bash
# Docker command fails
python -m ipfs_datasets_py.mcp_server --invalid-flag
```

Creates issue:
```
Title: [Auto-Report] SystemExit in Docker Container: Invalid flag --invalid-flag

Body:
# Automatic Error Report

## Error Details
**Type:** `SystemExit`
**Message:** Invalid flag --invalid-flag
**Source:** Docker Container: python -m ipfs_datasets_py.mcp_server
**Command:** python -m ipfs_datasets_py.mcp_server --invalid-flag
...
```

## Best Practices

1. **Monitor Created Issues**
   - Regularly review auto-generated issues
   - Triage and prioritize
   - Close duplicates if deduplication missed them

2. **Adjust Configuration**
   - Tune rate limits based on your needs
   - Adjust deduplication window for your workflow
   - Disable in development if too noisy

3. **Add Context**
   - Use `additional_info` parameter for custom context
   - Include relevant state information
   - Help future developers understand the error

4. **Fix Root Causes**
   - Don't just close issues
   - Fix the underlying bugs
   - Use auto-healing to help with fixes

5. **Test Error Paths**
   - Write tests that trigger error conditions
   - Verify error reporting works correctly
   - Ensure errors are handled gracefully

## API Reference

See module documentation:
- `ipfs_datasets_py.error_reporting.config.ErrorReportingConfig`
- `ipfs_datasets_py.error_reporting.issue_creator.GitHubIssueCreator`
- `ipfs_datasets_py.error_reporting.error_handler.ErrorHandler`
