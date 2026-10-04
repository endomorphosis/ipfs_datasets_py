# JavaScript Error Auto-Healing System - Quick Start

## What is This?

An automated system that captures JavaScript errors from the MCP dashboard, creates GitHub issues with detailed context, and triggers auto-healing workflows to automatically fix the problems.

## Quick Demo

```bash
# Run the demonstration
python scripts/demo/demonstrate_js_error_healing.py

# Run tests
python tests/unit_tests/test_js_error_reporter_standalone.py
```

## How It Works

```
Browser Error → Capture → API → GitHub Issue → Auto-Healing → Draft PR → Fix
```

1. **Error Occurs:** JavaScript error happens in the dashboard
2. **Captured:** Error, stack trace, console history, and user actions are captured
3. **Reported:** Sent to backend API endpoint
4. **Issue Created:** Detailed GitHub issue is automatically created
5. **Auto-Healing:** GitHub Actions workflow creates a draft PR
6. **Fixed:** GitHub Copilot suggests/implements fixes
7. **Merged:** Human reviews and merges the fix

## Files Created

### Frontend
- `ipfs_datasets_py/dashboards/static/admin/js/error_capture.js` - Captures JS errors

### Backend
- `ipfs_datasets_py/mcp_server/tools/dashboard_tools/js_error_reporter.py` - Processes errors
- `ipfs_datasets_py/dashboards/dashboard_error_api.py` - Flask API endpoints

### Tests
- `tests/unit_tests/test_js_error_reporter_standalone.py` - 8 passing tests
- `tests/unit_tests/test_dashboard_error_api.py` - API endpoint tests
- `tests/unit_tests/test_js_error_reporter.py` - Full test suite

### Documentation
- `docs/javascript_error_auto_healing.md` - Complete documentation
- `scripts/demo/demonstrate_js_error_healing.py` - Interactive demonstration

### Integration
- Modified `ipfs_datasets_py/admin_dashboard.py` - Added API route registration
- Modified `ipfs_datasets_py/templates/admin/mcp_dashboard.html` - Added error capture script

## API Endpoints

### POST `/api/report-js-error`
Receives error reports from the dashboard.

### GET `/api/js-error-stats`
Returns error statistics.

### GET `/api/js-error-history?limit=10`
Returns recent error reports.

## Example GitHub Issue

When an error occurs, this system creates an issue like:

**Title:** `[Dashboard JS Error] error: Cannot read property 'data' of undefined`

**Body:** Includes:
- Stack trace
- Console history (last 10 entries)
- User actions (last 10)
- Browser information
- Session ID
- Timestamp

**Labels:** `bug`, `javascript`, `dashboard`, `auto-healing`

## Configuration

### Required Environment Variables
```bash
export GITHUB_TOKEN="your_github_token"
export GITHUB_REPOSITORY="endomorphosis/ipfs_datasets_py"
```

### JavaScript Configuration
```javascript
// In error_capture.js (automatically configured)
new DashboardErrorCapture({
    apiEndpoint: '/api/report-js-error',
    maxConsoleHistory: 100,
    maxActionHistory: 50,
    debounceMs: 1000
});
```

## Features

✅ **Automatic Error Capture**
- Unhandled JavaScript errors
- Unhandled promise rejections
- Console logging (log, error, warn, info)
- User action tracking (clicks, forms, navigation)

✅ **Rich Context**
- Full stack traces
- Console history (last 100 entries)
- User action history (last 50 actions)
- Browser information
- Session tracking

✅ **GitHub Integration**
- Automatic issue creation via GitHub CLI
- Detailed issue bodies with all context
- Auto-healing labels for workflow triggers

✅ **Auto-Healing**
- Triggers existing GitHub Actions workflows
- Creates draft PRs automatically
- Integrates with GitHub Copilot

✅ **Monitoring**
- Error statistics endpoint
- Error history endpoint
- Configurable history limits

## Testing

All tests pass:
```bash
$ python tests/unit_tests/test_js_error_reporter_standalone.py

Running JavaScript Error Reporter Tests...
============================================================
✓ test_initialization passed
✓ test_format_error_report_basic passed
✓ test_format_error_report_with_stack passed
✓ test_create_github_issue_body passed
✓ test_process_error_report_without_issue_creation passed
✓ test_get_error_statistics_empty passed
✓ test_get_error_statistics_with_errors passed
✓ test_error_history_limit passed
============================================================

Results: 8 passed, 0 failed
```

## Usage

### Automatic (Recommended)

The error capture system is automatically enabled when you load the MCP dashboard. No additional configuration is needed.

### Manual Error Reporting

```javascript
// In browser console
window.dashboardErrorCapture.reportManualError(
    new Error('Custom error'),
    { context: 'Additional context' }
);
```

### Python API

```python
from ipfs_datasets_py.mcp_server.tools.dashboard_tools import get_js_error_reporter

# Get reporter instance
reporter = get_js_error_reporter()

# Process error report
result = reporter.process_error_report(error_data, create_issue=True)

# Get statistics
stats = reporter.get_error_statistics()
```

## Troubleshooting

### GitHub CLI Not Found
```bash
# Install GitHub CLI
sudo apt install gh  # Debian/Ubuntu
brew install gh      # macOS

# Authenticate
gh auth login
```

### Errors Not Being Captured
1. Check browser console for error_capture.js loading
2. Verify API endpoint is accessible: `curl http://localhost:8888/api/js-error-stats`
3. Check Flask logs for errors

### Issues Not Being Created
1. Verify GitHub token: `echo $GITHUB_TOKEN`
2. Check authentication: `gh auth status`
3. Review backend logs for error messages

## Next Steps

1. **Run the demo:** `python scripts/demo/demonstrate_js_error_healing.py`
2. **Read the docs:** `docs/javascript_error_auto_healing.md`
3. **Run tests:** `python tests/unit_tests/test_js_error_reporter_standalone.py`
4. **Start the dashboard:** The system will automatically capture errors

## Integration with Existing Workflows

This system integrates seamlessly with the existing auto-healing infrastructure:

- **copilot-agent-autofix.yml** - Monitors and fixes workflow failures
- **issue-to-draft-pr.yml** - Converts issues to draft PRs
- **Auto-Healing Coordinator** - Orchestrates healing strategies
- **Error Pattern Detector** - Detects error patterns

The JavaScript error system adds a new error source (dashboard JavaScript) to this existing ecosystem.

## Security Considerations

- ✅ Stack traces are truncated to 1000 characters
- ✅ Console logs are truncated to 200 characters per entry
- ✅ Error reporting is debounced (1 second) to prevent abuse
- ✅ Session IDs are generated client-side (no PII)
- ✅ GitHub token is stored securely in environment variables

## Performance

- **Minimal overhead:** Error capture has negligible performance impact
- **Efficient reporting:** Errors are debounced and batched
- **Limited history:** Only the most recent 100 console logs and 50 actions are kept
- **Async processing:** Error reporting doesn't block the UI

## Support

For issues, questions, or feature requests:
1. Check the documentation: `docs/javascript_error_auto_healing.md`
2. Run the demo: `scripts/demo/demonstrate_js_error_healing.py`
3. Create a GitHub issue (which will trigger auto-healing! 🎉)

---

**Status:** ✅ Fully Implemented and Tested  
**Version:** 1.0.0  
**Last Updated:** 2024-01-30
