# Runtime Error Reporting System

This module provides automatic error reporting functionality that captures runtime errors from various sources (Python, JavaScript, Docker) and converts them into GitHub issues for automated tracking and resolution.

## Features

- **Multi-Source Error Capture**: Captures errors from:
  - Python runtime (uncaught exceptions, reported errors)
  - JavaScript (window.onerror, unhandled promise rejections)
  - Docker containers (command failures, runtime errors)

- **GitHub Issue Integration**: Automatically creates GitHub issues with:
  - Detailed error information (type, message, stack trace)
  - Context (environment, hostname, source)
  - Appropriate labels (runtime-error, source:python, bug, etc.)

- **Error Deduplication**: Prevents spam by:
  - Computing error hashes based on type, message, and location
  - Tracking reported errors with configurable time intervals
  - Skipping duplicate reports within the interval

- **Configurable via Environment Variables**:
  - `ERROR_REPORTING_ENABLED`: Enable/disable error reporting (default: false)
  - `GITHUB_REPOSITORY`: Target repository (default: endomorphosis/ipfs_datasets_py)
  - `GITHUB_TOKEN` or `GH_TOKEN`: GitHub authentication token

## Installation

The error reporting module is included in the main package:

```python
from ipfs_datasets_py.error_reporting import (
    ErrorReporter,
    get_global_error_reporter,
    install_error_handlers
)
```

## Usage

### Python Error Reporting

#### Automatic Error Handling

Install global error handlers to automatically report uncaught exceptions:

```python
from ipfs_datasets_py.error_reporting import install_error_handlers

# Install error handlers (call once at application startup)
install_error_handlers()

# Now all uncaught exceptions will be automatically reported
```

#### Manual Error Reporting

Report errors manually using the error reporter:

```python
from ipfs_datasets_py.error_reporting import get_global_error_reporter

reporter = get_global_error_reporter()

# Report a generic error
reporter.report_error(
    error_type='ValueError',
    error_message='Invalid input value',
    source='python',
    error_location='module.py:42',
    stack_trace='Traceback...',
    context={'user_id': 123, 'action': 'process_data'}
)

# Report an exception
try:
    risky_operation()
except Exception as e:
    reporter.report_exception(e, source='python', context={'module': 'data_processor'})
```

### JavaScript Error Reporting

Include the error reporter JavaScript in your HTML:

```html
<script>
    // Configure error reporting
    window.ERROR_REPORTING_ENABLED = true;
</script>
<script src="/static/js/error-reporter.js"></script>
```

The error reporter will automatically capture:
- `window.onerror` events (uncaught errors)
- `unhandledrejection` events (unhandled promise rejections)

Manual error reporting:

```javascript
// Report an error manually
window.errorReporter.reportError(
    'CustomError',
    'Something went wrong',
    'at myFunction (file.js:42)',
    { userId: 123 }
);
```

### Docker Error Monitoring

Use the Docker error monitor to wrap container commands:

```dockerfile
# In your Dockerfile
COPY ipfs_datasets_py/error_reporting/docker_error_monitor.py /app/
ENTRYPOINT ["python", "/app/docker_error_monitor.py"]
CMD ["python", "your_app.py"]
```

Or use it from Python:

```python
from ipfs_datasets_py.error_reporting.docker_error_monitor import DockerErrorMonitor

monitor = DockerErrorMonitor()
exit_code = monitor.run_command(['python', 'script.py'])
```

### MCP Server Integration

The error reporting system is automatically integrated with the MCP server when available.

The standalone server includes:
- Automatic error handler installation
- API endpoints for error reporting (`/api/report-error`, `/api/error-reporting/status`)
- JavaScript error reporter in dashboard

## Configuration

### Environment Variables

```bash
# Enable error reporting
export ERROR_REPORTING_ENABLED=true

# Configure GitHub repository (optional)
export GITHUB_REPOSITORY=owner/repo

# Set GitHub token for authentication
export GITHUB_TOKEN=your_github_token_here
# or
export GH_TOKEN=your_github_token_here
```

### .env File

Add to your `.env` file:

```
# Error Reporting Configuration
ERROR_REPORTING_ENABLED=true
GITHUB_REPOSITORY=endomorphosis/ipfs_datasets_py
GITHUB_TOKEN=your_github_token_here
```

## API Endpoints

### POST /api/report-error

Report an error from any source.

**Request:**
```json
{
  "error_type": "TypeError",
  "error_message": "Cannot read property 'x' of undefined",
  "source": "javascript",
  "error_location": "script.js:42",
  "stack_trace": "Error: ...",
  "context": {
    "userAgent": "...",
    "url": "..."
  }
}
```

**Response:**
```json
{
  "success": true,
  "issue_url": "https://github.com/owner/repo/issues/123",
  "issue_number": "123",
  "error_hash": "abc123..."
}
```

### GET /api/error-reporting/status

Get error reporting system status.

**Response:**
```json
{
  "success": true,
  "enabled": true,
  "github_available": true,
  "reported_count": 5
}
```

## Error Deduplication

Errors are deduplicated based on a hash of:
- Error type
- Error message
- Error location

By default, the same error will not be reported more than once per hour. This prevents spam from recurring errors.

Configure the interval:

```python
from ipfs_datasets_py.error_reporting import ErrorReporter

reporter = ErrorReporter(
    enabled=True,
    min_report_interval=1800  # 30 minutes
)
```

## GitHub Issue Format

Issues created by the error reporting system include:

**Title:**
```
[Runtime Error] TypeError: Cannot read property 'x' of undefined (javascript)
```

**Body:**
```markdown
# Runtime Error Report

An error was automatically detected and reported by the runtime error monitoring system.

## Error Details

- **Type**: TypeError
- **Message**: Cannot read property 'x' of undefined
- **Source**: javascript
- **Timestamp**: 2024-01-01T12:00:00.000Z
- **Location**: script.js:42

## Context

```json
{
  "userAgent": "Mozilla/5.0...",
  "url": "https://example.com/page"
}
```

## Stack Trace

```
Error: Cannot read property 'x' of undefined
    at myFunction (script.js:42)
    at onClick (script.js:100)
```

## Environment

- **Python Version**: 3.12.0
- **Platform**: linux
- **Hostname**: container-123

## Auto-Generated Report

This issue was automatically created by the runtime error monitoring system.
Please review and address the error, or close this issue if it's a false positive.
```

**Labels:**
- `runtime-error`
- `source:javascript` (or `source:python`, `source:docker`)
- `bug` (for Python errors)
- `frontend` (for JavaScript errors)
- `infrastructure` (for Docker errors)

## Testing

Run the test suite:

```bash
pytest tests/unit/error_reporting/
```

## Security Considerations

- **Token Security**: Never commit GitHub tokens to source code. Use environment variables.
- **Error Privacy**: Be cautious about sensitive information in error messages and context.
- **Rate Limiting**: The deduplication system prevents excessive issue creation.
- **GitHub CLI**: Uses the official GitHub CLI (`gh`) for secure API access.

## Requirements

- **GitHub CLI** (`gh`): Install from https://cli.github.com/
- **GitHub Token**: With `repo` and `issues:write` permissions
- **Python 3.12+**: For the Python error reporting
- **Flask**: For API endpoints (if using MCP server integration)

## Limitations

- Requires GitHub CLI to be installed and authenticated
- Error reporting is disabled by default for safety
- Maximum 10 errors per session reported from JavaScript (configurable)
- Deduplication interval prevents reporting same error too frequently

## Examples

See the `examples/` directory for complete examples:

- `error_reporting_example.py`: Python error reporting examples
- `dashboard_error_reporting_demo.html`: JavaScript error reporting demo

## Troubleshooting

### Error reporting not working

1. Check if error reporting is enabled:
   ```bash
   echo $ERROR_REPORTING_ENABLED
   ```

2. Verify GitHub CLI is installed and authenticated:
   ```bash
   gh auth status
   ```

3. Check error reporting status:
   ```bash
   curl http://localhost:8000/api/error-reporting/status
   ```

### Issues not being created

1. Verify GitHub token has correct permissions
2. Check if error is being deduplicated (same error reported recently)
3. Review logs for error reporting failures

## License

This module is part of the IPFS Datasets Python project and follows the same license.
