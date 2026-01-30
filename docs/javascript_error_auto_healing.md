# JavaScript Error Auto-Healing System

## Overview

The JavaScript Error Auto-Healing System automatically captures JavaScript errors from the MCP dashboard, creates GitHub issues with detailed error information, and triggers auto-healing workflows to fix the issues.

## Architecture

```
┌─────────────────────┐
│  Dashboard (Browser)│
│                     │
│  error_capture.js   │◄─── Captures errors, console logs, user actions
└──────────┬──────────┘
           │ HTTP POST
           ▼
┌─────────────────────┐
│   Flask Backend     │
│                     │
│  dashboard_error_api│◄─── Receives error reports
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Error Reporter     │
│                     │
│  js_error_reporter  │◄─── Processes errors, creates GitHub issues
└──────────┬──────────┘
           │
           ├─► GitHub Issue Created
           │
           ▼
┌─────────────────────┐
│  Auto-Healing       │
│                     │
│  GitHub Actions     │◄─── Creates draft PR with fixes
└─────────────────────┘
```

## Components

### 1. Frontend: `error_capture.js`

**Location:** `ipfs_datasets_py/dashboards/static/admin/js/error_capture.js`

**Features:**
- Captures unhandled JavaScript errors
- Captures unhandled promise rejections
- Intercepts console methods (log, error, warn, info)
- Tracks user actions (clicks, form submissions, navigation)
- Maintains console history (last 100 entries)
- Maintains action history (last 50 actions)
- Debounces error reporting to avoid overwhelming the server
- Automatically reports errors to the backend

**Configuration:**
```javascript
new DashboardErrorCapture({
    apiEndpoint: '/api/report-js-error',
    maxConsoleHistory: 100,
    maxActionHistory: 50,
    debounceMs: 1000,
    enableConsoleCapture: true,
    enableActionTracking: true
});
```

**Usage:**
The module is automatically initialized when the dashboard loads. It can also be used to manually report errors:

```javascript
window.dashboardErrorCapture.reportManualError(error, { context: 'Custom context' });
```

### 2. Backend: `js_error_reporter.py`

**Location:** `ipfs_datasets_py/mcp_server/tools/dashboard_tools/js_error_reporter.py`

**Features:**
- Formats JavaScript error data into structured reports
- Creates detailed GitHub issue bodies with:
  - Stack traces
  - Console history
  - User action history
  - Browser information
  - Error context
- Maintains error history (last 100 reports)
- Triggers auto-healing workflows
- Provides error statistics

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.dashboard_tools import get_js_error_reporter

reporter = get_js_error_reporter()

# Process an error report
result = reporter.process_error_report(
    error_data={
        'errors': [{'type': 'error', 'message': 'Test error'}],
        'sessionId': 'session_123'
    },
    create_issue=True
)

# Get statistics
stats = reporter.get_error_statistics()
```

### 3. API: `dashboard_error_api.py`

**Location:** `ipfs_datasets_py/dashboards/dashboard_error_api.py`

**Endpoints:**

#### POST `/api/report-js-error`
Receives JavaScript error reports from the dashboard.

**Request:**
```json
{
    "errors": [{
        "type": "error",
        "message": "Error message",
        "filename": "app.js",
        "lineno": 42,
        "colno": 15,
        "stack": "Stack trace...",
        "timestamp": "2024-01-01T00:00:00.000Z",
        "url": "http://localhost/dashboard",
        "userAgent": "Mozilla/5.0...",
        "consoleHistory": [...],
        "actionHistory": [...]
    }],
    "reportedAt": "2024-01-01T00:00:00.000Z",
    "sessionId": "session_123"
}
```

**Response:**
```json
{
    "success": true,
    "issue_created": true,
    "issue_url": "https://github.com/owner/repo/issues/123",
    "issue_number": 123,
    "report": {
        "error_count": 1,
        "session_id": "session_123"
    }
}
```

#### GET `/api/js-error-stats`
Returns error statistics.

**Response:**
```json
{
    "success": true,
    "statistics": {
        "total_reports": 10,
        "total_errors": 15,
        "error_types": {
            "error": 10,
            "unhandledrejection": 5
        },
        "last_report": "2024-01-01T00:00:00.000Z"
    }
}
```

#### GET `/api/js-error-history?limit=10`
Returns recent error reports.

**Response:**
```json
{
    "success": true,
    "count": 10,
    "history": [...]
}
```

## Integration

### Admin Dashboard Integration

The error reporting routes are automatically registered in the admin dashboard:

```python
# In admin_dashboard.py
from ipfs_datasets_py.dashboards.dashboard_error_api import setup_dashboard_error_routes

setup_dashboard_error_routes(app)
```

### Dashboard Template Integration

The error capture script is included in the dashboard template:

```html
<!-- In mcp_dashboard.html -->
<script src="{{ url_for('static', filename='admin/js/error_capture.js') }}"></script>
```

## GitHub Issue Creation

When a JavaScript error is reported, the system creates a detailed GitHub issue with the following information:

**Issue Title:**
```
[Dashboard JS Error] error: Cannot read property 'foo' of undefined
```

**Issue Body:**
```markdown
## JavaScript Dashboard Error Report

**Session ID:** `session_123`
**Reported At:** 2024-01-01T00:00:00.000Z
**Error Count:** 1

---

### Error 1: error

**Message:** Cannot read property 'foo' of undefined
**Timestamp:** 2024-01-01T00:00:00.000Z
**URL:** http://localhost:8888/dashboard
**File:** app.js:42:15

**Stack Trace:**
```
TypeError: Cannot read property 'foo' of undefined
    at Object.foo (app.js:42:15)
    at bar (app.js:100:5)
```

**Console History (last 10 entries):**
```
[log] 2024-01-01T00:00:00.000Z: App started
[warn] 2024-01-01T00:00:01.000Z: API slow response
[error] 2024-01-01T00:00:02.000Z: Error occurred
```

**User Actions (last 10):**
```
[click] 2024-01-01T00:00:00.000Z: BUTTON submit-btn
[submit] 2024-01-01T00:00:01.000Z: FORM user-form
```

**User Agent:** `Mozilla/5.0 (Windows NT 10.0; Win64; x64)...`

---

## Auto-Healing

This issue was automatically created by the MCP Dashboard error reporting system.
The auto-healing workflow will attempt to create a draft PR to fix this issue.

**Labels:** `bug`, `javascript`, `dashboard`, `auto-healing`
```

## Auto-Healing Workflow

After creating a GitHub issue, the system triggers an auto-healing workflow:

1. **Issue Created:** GitHub issue is created with labels `bug`, `javascript`, `dashboard`, `auto-healing`
2. **Auto-Healing Triggered:** The `auto_healing_coordinator` is invoked
3. **Draft PR Created:** The existing auto-healing GitHub Actions workflow creates a draft PR
4. **Copilot Agent:** GitHub Copilot is mentioned in the PR to implement fixes
5. **Review and Merge:** Human reviews the automated fix and merges when ready

## Testing

### Unit Tests

Run the standalone tests:
```bash
python tests/unit_tests/test_js_error_reporter_standalone.py
```

### Manual Testing

1. **Trigger a JavaScript Error:**
   ```javascript
   // In browser console
   throw new Error('Test error for auto-healing');
   ```

2. **Check Error Reporting:**
   ```bash
   curl http://localhost:8888/api/js-error-stats
   ```

3. **Verify GitHub Issue:**
   Check the repository issues for a new issue with the `dashboard` label.

## Configuration

### Environment Variables

- `GITHUB_TOKEN` or `GH_TOKEN`: GitHub personal access token for creating issues
- `GITHUB_REPOSITORY`: Repository name (default: `endomorphosis/ipfs_datasets_py`)

### Dashboard Configuration

```python
from ipfs_datasets_py.admin_dashboard import AdminDashboard, DashboardConfig

config = DashboardConfig(
    host='127.0.0.1',
    port=8888,
    # Other configuration...
)

dashboard = AdminDashboard.initialize(config)
```

## Monitoring

### Error Statistics

Get error statistics via API:
```bash
curl http://localhost:8888/api/js-error-stats
```

Or in Python:
```python
from ipfs_datasets_py.mcp_server.tools.dashboard_tools import get_js_error_reporter

stats = get_js_error_reporter().get_error_statistics()
print(f"Total errors: {stats['total_errors']}")
```

### Error History

Get recent error reports:
```bash
curl http://localhost:8888/api/js-error-history?limit=10
```

## Troubleshooting

### GitHub CLI Not Available

If GitHub CLI is not available:
```bash
# Install GitHub CLI
sudo apt install gh  # Debian/Ubuntu
brew install gh      # macOS

# Authenticate
gh auth login
```

### Errors Not Being Reported

1. Check browser console for error capture script loading
2. Verify API endpoint is accessible
3. Check Flask logs for errors
4. Ensure JavaScript is not disabled

### Issues Not Being Created

1. Verify GitHub token is set: `echo $GITHUB_TOKEN`
2. Check GitHub CLI authentication: `gh auth status`
3. Review backend logs for error messages
4. Verify repository permissions

## Security Considerations

- **Sensitive Data:** The error reporter truncates long stack traces and console logs
- **Rate Limiting:** Error reporting is debounced to prevent abuse
- **Authentication:** GitHub token should be kept secure
- **Issue Visibility:** All created issues are public in the repository

## Future Enhancements

- [ ] Error deduplication to avoid duplicate issues
- [ ] Severity classification for errors
- [ ] User notification system for critical errors
- [ ] Integration with monitoring/alerting systems
- [ ] Error pattern analysis and recommendations
- [ ] Automated error categorization
- [ ] Support for error reporting from other dashboard pages

## References

- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [GitHub Actions Auto-Healing](.github/workflows/copilot-agent-autofix.yml)
- [Auto-Healing Coordinator](ipfs_datasets_py/mcp_server/tools/software_engineering_tools/auto_healing_coordinator.py)
- [Error Reporting Infrastructure](ipfs_datasets_py/error_reporting/)
