# Comprehensive Auto-Healing System Documentation

## Overview

The IPFS Datasets Python auto-healing system automatically detects, reports, and fixes errors across all major components of the platform:

- **CLI Tools** (ipfs-datasets, enhanced CLI, MCP CLI)
- **MCP Server Tools** (200+ tools across 49+ categories)
- **JavaScript SDK** (mcp-sdk.js, mcp-api-client.js)
- **MCP Dashboard** (Web UI and error reporting)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Error Detection Layer                         │
├─────────────┬─────────────┬─────────────┬──────────────────────┤
│ CLI Tools   │ MCP Tools   │ JS SDK      │ MCP Dashboard        │
│ Monitoring  │ Monitoring  │ Monitoring  │ Monitoring           │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬───────────────┘
       │             │              │             │
       │             │              │             │
       ▼             ▼              ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│              Error Reporting Infrastructure                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ CLI Error    │  │ Python Error │  │ JS Error     │         │
│  │ Reporter     │  │ Reporter     │  │ Reporter     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│              Copilot Agent Auto-Healing Workflow                 │
│  1. Detect workflow failure                                      │
│  2. Download and analyze logs                                    │
│  3. Create GitHub issue with error details                       │
│  4. Generate draft PR on unique branch                           │
│  5. @mention Copilot to implement fixes                          │
│  6. Monitor and iterate until fixed                              │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. CLI Tools Error Monitoring

**Workflow**: `.github/workflows/cli-error-monitoring.yml`

**Purpose**: Monitor all CLI tool variations for errors and failures

**What it monitors**:
- `ipfs-datasets` main CLI
- `enhanced_cli.py` (100+ tools across 31+ categories)
- `mcp_cli.py` (MCP-specific interface)
- `integrated_cli.py` (integrated functionality)
- `comprehensive_distributed_cli.py`

**Test levels**:
- **Smoke tests**: Basic command functionality
- **Comprehensive tests**: All CLI tool variations
- **Error reporting tests**: Error capture integration
- **Stress tests**: Multiple operations under load

**Triggers**:
- Push to main/develop (CLI files changed)
- Pull requests
- Manual dispatch
- Daily at 4 AM UTC

**Error capture**:
```python
from ipfs_datasets_py.error_reporting.cli_error_reporter import CLIErrorReporter

reporter = CLIErrorReporter()
error_report = reporter.format_cli_error(
    error=exception,
    command='ipfs-datasets',
    args=['test', 'command'],
    logs='command output'
)
```

### 2. MCP Server Tools Error Monitoring

**Workflow**: `.github/workflows/mcp-tools-monitoring.yml`

**Purpose**: Monitor 200+ MCP server tools across 49+ categories

**What it monitors**:
- Tool discovery and loading
- Tool initialization
- Tool execution via API
- Error reporting for tool failures

**Test levels**:
- **Discovery**: Find all tool categories and tools
- **Loading tests**: Import and initialize each tool
- **Execution tests**: Test tools via MCP API
- **Category tests**: Test specific tool categories
- **Health check**: Comprehensive tool health report

**Monitored categories** (examples):
- `dataset_tools` - Dataset management
- `ipfs_tools` - IPFS operations
- `embedding_tools` - Vector embeddings
- `pdf_tools` - PDF processing
- `media_tools` - Multimedia processing
- `legal_dataset_tools` - Legal document tools
- ...and 43+ more

**Triggers**:
- Push to main/develop (tool files changed)
- Pull requests
- Manual dispatch (can specify category)
- Daily at 6 AM UTC

### 3. JavaScript SDK Error Monitoring

**Workflow**: `.github/workflows/javascript-sdk-monitoring.yml`

**Purpose**: Monitor JavaScript SDK for browser and API integration errors

**What it monitors**:
- `mcp-sdk.js` - Main SDK client
- `mcp-api-client.js` - API client
- `mcp_client_sdk.js` - Client SDK wrapper
- `error-reporter.js` - JavaScript error reporter

**Test levels**:
- **Static analysis**: Linting and syntax checks
- **Functionality tests**: SDK API integration
- **Error reporter tests**: JS error capture
- **Browser tests**: Headless browser testing with Selenium

**Error capture**:
```javascript
const reporter = new JavaScriptErrorReporter({
    enabled: true,
    endpoint: '/api/report-error'
});

// Automatic error capture on window.onerror and unhandledrejection
```

**Triggers**:
- Push to main/develop (JS SDK files changed)
- Pull requests
- Manual dispatch
- Daily at 5 AM UTC

### 4. MCP Dashboard Monitoring

**Workflow**: `.github/workflows/mcp-dashboard-tests.yml` (enhanced)

**Purpose**: Monitor MCP dashboard web UI and frontend errors

**What it monitors**:
- Dashboard page loading
- API endpoint availability
- JavaScript errors in browser console
- User interaction flows
- Performance metrics

**Test levels**:
- **Smoke tests**: Basic dashboard functionality
- **Comprehensive tests**: Full endpoint testing
- **Browser tests**: UI interaction testing
- **Self-hosted tests**: Multi-architecture support

**Triggers**:
- Push to main/develop (dashboard files changed)
- Pull requests
- Manual dispatch
- Daily at 2 AM UTC

### 5. Copilot Agent Auto-Healing

**Workflow**: `.github/workflows/copilot-agent-autofix.yml`

**Purpose**: Central auto-healing orchestrator

**What it does**:
1. **Detects failures**: Monitors all tracked workflows
2. **Checks duplicates**: Prevents duplicate issue/PR creation
3. **Downloads logs**: Captures workflow run logs
4. **Analyzes failures**: Identifies root cause and error patterns
5. **Creates issue**: Simple, clear issue for Copilot
6. **Generates branch**: Unique branch for the fix
7. **Creates draft PR**: Draft PR that @mentions Copilot
8. **Monitors progress**: Tracks fix implementation

**Monitored workflows**:
- ARM64 Self-Hosted Runner
- CLI Tools Error Monitoring ⭐ NEW
- Comprehensive Scraper Validation
- Docker Build and Test
- Documentation Maintenance
- GPU-Enabled Tests
- GraphRAG Production CI/CD
- JavaScript SDK Error Monitoring ⭐ NEW
- MCP Dashboard Automated Tests
- MCP Endpoints Integration Tests
- MCP Tools Error Monitoring ⭐ NEW
- PDF Processing Pipeline CI/CD
- Scraper Validation and Testing
- Self-Hosted Runner Test
- ...and more

**Triggers**:
- Automatic on workflow failure
- Manual dispatch (specify workflow/run)

## Error Reporting Infrastructure

### Python Error Reporter

**Location**: `ipfs_datasets_py/error_reporting/error_reporter.py`

**Features**:
- Error deduplication based on hash
- Configurable via environment variables
- Thread-safe operation
- Support for multiple error sources

**Configuration**:
```bash
export ERROR_REPORTING_ENABLED=true
export GITHUB_REPOSITORY=owner/repo
export GITHUB_TOKEN=ghp_xxxxx
```

**Usage**:
```python
from ipfs_datasets_py.error_reporting.error_reporter import ErrorReporter

reporter = ErrorReporter(enabled=True)

try:
    # Your code
    pass
except Exception as e:
    reporter.report_error(
        error=e,
        context={'component': 'mcp_tools', 'tool': 'dataset_loader'}
    )
```

### CLI Error Reporter

**Location**: `ipfs_datasets_py/error_reporting/cli_error_reporter.py`

**Features**:
- CLI-specific error formatting
- Command and argument capture
- Log output truncation
- GitHub issue body generation

**Automatic installation**:
```python
# Automatically installed in ipfs_datasets_cli.py
from ipfs_datasets_py.error_reporting.cli_error_reporter import install_cli_error_handler
install_cli_error_handler()
```

### JavaScript Error Reporter

**Location**: `ipfs_datasets_py/static/js/error-reporter.js`

**Features**:
- Browser error capture (window.onerror)
- Promise rejection handling
- Error deduplication
- Automatic reporting to backend

**Usage**:
```javascript
// Automatic initialization
const errorReporter = new JavaScriptErrorReporter({
    enabled: window.ERROR_REPORTING_ENABLED || false,
    endpoint: '/api/report-error'
});

// Errors are automatically captured
```

**Configuration**:
```html
<script>
    window.ERROR_REPORTING_ENABLED = true;
</script>
<script src="/static/js/error-reporter.js"></script>
```

## Auto-Healing Flow

### 1. Error Detection

```
Component Error → Workflow Test Failure → Artifact Upload
```

Example: CLI command fails → CLI monitoring workflow fails → Logs uploaded

### 2. Auto-Healing Trigger

```
Workflow Failure → Copilot Agent Auto-Healing Triggered
```

The copilot-agent-autofix workflow is triggered automatically on any monitored workflow failure.

### 3. Analysis Phase

```
Download Logs → Analyze Failure → Generate Fix Proposal
```

- Logs are downloaded from failed workflow run
- Error patterns are identified
- Root cause analysis is performed
- Fix proposal is generated with confidence score

### 4. Issue Creation

```
Create GitHub Issue → Clear Description → Include Run ID
```

Issue template:
```markdown
# Fix Workflow Failure: [Workflow Name]

## Workflow Information
- **Workflow**: [Name]
- **Run ID**: [Link to run]
- **Branch**: [Branch]
- **SHA**: [Commit SHA]

Run ID: [Run ID] (for duplicate detection)

## Error Details
- **Type**: [Error type]
- **Root Cause**: [Root cause description]

## Task
Please analyze and fix the workflow failure:
1. Review the workflow logs at the run link above
2. Identify the root cause of the failure
3. Implement the necessary fixes
4. Test that the workflow passes
5. Create a PR with the fix
```

### 5. Draft PR Creation

```
Create Branch → Add Placeholder → Create Draft PR → @mention Copilot
```

- Unique branch: `autofix/workflow-{run-id}-issue-{issue-number}-{timestamp}`
- Draft PR created with reference to issue
- Copilot automatically assigned via GitHub integration

### 6. Fix Implementation

```
Copilot Analyzes → Implements Fix → Commits Changes → Marks Ready for Review
```

Copilot:
- Reviews the workflow logs
- Analyzes the error
- Implements the fix
- Tests the fix
- Updates PR description
- Marks PR as ready for review

### 7. Review and Merge

```
Human Review → Approve → Merge → Close Issue
```

## Configuration

### Enable Error Reporting

**Environment Variables**:
```bash
# Enable error reporting globally
export ERROR_REPORTING_ENABLED=true

# GitHub configuration
export GITHUB_REPOSITORY=endomorphosis/ipfs_datasets_py
export GITHUB_TOKEN=${{ secrets.GITHUB_TOKEN }}

# Error reporting thresholds
export ERROR_MIN_REPORT_INTERVAL=3600  # 1 hour
export ERROR_MAX_REPORTS_PER_SESSION=10
```

**In workflows**:
```yaml
env:
  ERROR_REPORTING_ENABLED: 'true'
  PYTHON_VERSION: '3.12'
```

### Exclude Workflows from Auto-Healing

Create `.github/workflows/workflow-auto-fix-config.yml`:
```yaml
excluded_workflows:
  - "Workflow Name to Exclude"
  - "Another Excluded Workflow"
```

### Customize Error Reporting

**Python**:
```python
# Custom configuration
reporter = ErrorReporter(
    enabled=True,
    repo='owner/repo',
    github_token='token',
    min_report_interval=7200  # 2 hours
)
```

**JavaScript**:
```javascript
const reporter = new JavaScriptErrorReporter({
    enabled: true,
    endpoint: '/api/report-error',
    minReportInterval: 7200000,  // 2 hours in ms
    maxReportsPerSession: 5
});
```

## Monitoring and Metrics

### View Auto-Healing Activity

**GitHub Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Filter by label: `autofix`, `workflow-failure`

**GitHub PRs**: https://github.com/endomorphosis/ipfs_datasets_py/pulls
- Filter by branch prefix: `autofix/`
- Filter by label: `autofix`, `copilot`

### Workflow Run History

**All workflows**: https://github.com/endomorphosis/ipfs_datasets_py/actions

**Specific monitoring workflows**:
- CLI Tools Monitoring: https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/cli-error-monitoring.yml
- JS SDK Monitoring: https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/javascript-sdk-monitoring.yml
- MCP Tools Monitoring: https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/mcp-tools-monitoring.yml
- Auto-Healing: https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/copilot-agent-autofix.yml

### Metrics to Track

1. **Error Detection Rate**: How many errors are caught?
2. **False Positive Rate**: How many non-issues trigger auto-healing?
3. **Fix Success Rate**: How many auto-healing PRs are successful?
4. **Time to Fix**: Average time from error to merged fix
5. **Manual Intervention Rate**: How often do humans need to intervene?

## Troubleshooting

### Auto-Healing Not Triggering

**Check**:
1. Is the workflow in the monitored list?
2. Did the workflow actually fail?
3. Was the failure already processed? (duplicate detection)
4. Is the workflow excluded in config?

**Debug**:
```bash
# View copilot-agent-autofix runs
gh run list --workflow=copilot-agent-autofix.yml --limit 10

# View specific run logs
gh run view <run-id> --log
```

### Duplicate Issues Created

**Cause**: Duplicate detection failed

**Fix**: Issues include `Run ID: <id>` for tracking. Search for existing issues:
```bash
gh issue list --search "Run ID: 12345678 in:body"
```

### Error Reporter Not Working

**Python**:
```python
# Test error reporter
from ipfs_datasets_py.error_reporting.error_reporter import ErrorReporter

reporter = ErrorReporter(enabled=True)
print(f"Reporter enabled: {reporter.enabled}")
print(f"GitHub CLI available: {reporter.github_client.is_available()}")
```

**JavaScript**:
```javascript
// Check console for initialization
console.log(window.errorReporter);
console.log(window.errorReporter.enabled);
```

### GitHub Token Issues

**Check permissions**:
```bash
gh auth status
```

**Required scopes**:
- `repo` (full repository access)
- `workflow` (manage workflow runs)

## Best Practices

### 1. Error Context

Always provide context when reporting errors:
```python
reporter.report_error(
    error=e,
    context={
        'component': 'cli',
        'command': 'ipfs-datasets',
        'args': ['info', 'status'],
        'user': 'test@example.com'
    }
)
```

### 2. Error Deduplication

Use meaningful error locations:
```python
error_location = f"{__file__}:{sys._getframe().f_lineno}"
```

### 3. Log Levels

Use appropriate log levels:
- ERROR: Issues that need immediate attention
- WARNING: Potential issues that should be monitored
- INFO: Normal operations
- DEBUG: Detailed debugging information

### 4. Testing Error Reporting

Test in disabled mode first:
```python
# Test mode - errors captured but not reported
reporter = ErrorReporter(enabled=False)
```

### 5. Monitor Auto-Healing

Regularly review:
- Auto-healing success rate
- Time to fix
- False positive rate
- Manual intervention frequency

## Examples

### Example 1: CLI Error

```python
# CLI command fails
./ipfs-datasets dataset load invalid_dataset

# Error caught by CLI error reporter
# → CLI monitoring workflow fails
# → Copilot auto-healing triggered
# → Issue created: "Fix: CLI Tools Error Monitoring workflow failure"
# → Draft PR created on branch: autofix/workflow-123-issue-456-1234567890
# → Copilot implements fix
# → PR ready for review
```

### Example 2: MCP Tool Error

```python
# MCP tool fails to load
# ipfs_datasets_py/mcp_server/tools/dataset_tools/broken_tool.py

# Error caught by tool discovery
# → MCP tools monitoring workflow fails
# → Copilot auto-healing triggered
# → Issue created with tool details
# → Copilot fixes import/syntax error
# → PR merged
```

### Example 3: JavaScript SDK Error

```javascript
// Browser error
MCPClient.executeTool('invalid_tool', {});

# Error caught by JS error reporter
# → Sent to /api/report-error endpoint
# → JS SDK monitoring workflow detects pattern
# → Copilot auto-healing triggered
# → Issue created with browser details
# → Copilot adds error handling
# → PR merged
```

### Example 4: Dashboard Error

```javascript
// Dashboard initialization fails
// JavaScript error in console

# Error caught by browser tests
# → Dashboard monitoring workflow fails
# → Copilot auto-healing triggered
# → Issue created with error details
# → Copilot fixes initialization logic
# → PR merged
```

## Future Enhancements

### Planned Improvements

1. **Error Pattern Database**: Build database of common errors and fixes
2. **ML-Based Analysis**: Use ML to predict fix success and prioritize issues
3. **Automatic Fix Validation**: Run tests automatically on draft PRs
4. **Error Clustering**: Group similar errors together
5. **Performance Metrics Dashboard**: Real-time monitoring dashboard
6. **Notification System**: Slack/email notifications for critical failures
7. **A/B Testing**: Test multiple fix approaches
8. **Historical Analysis**: Trend analysis of error patterns

### Integration Opportunities

1. **Sentry Integration**: Send errors to Sentry for advanced tracking
2. **Datadog Integration**: Metrics and APM integration
3. **PagerDuty Integration**: On-call alerting for critical failures
4. **Slack Integration**: Real-time notifications
5. **Grafana Dashboards**: Visualization of error metrics

## Support

### Getting Help

- **Documentation**: This file and related guides
- **Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Discussions**: https://github.com/endomorphosis/ipfs_datasets_py/discussions

### Reporting Issues

When reporting auto-healing issues, include:
1. Workflow name and run ID
2. Error message and logs
3. Expected vs actual behavior
4. Steps to reproduce

### Contributing

Contributions to improve auto-healing are welcome:
1. Error pattern detection improvements
2. New error reporters for additional components
3. Enhanced analysis algorithms
4. Better fix suggestion generation
5. Documentation improvements

## Summary

The comprehensive auto-healing system provides:

✅ **Automatic error detection** across CLI, MCP tools, JS SDK, and dashboard
✅ **Intelligent error reporting** with deduplication and context
✅ **Automated issue creation** with clear descriptions
✅ **Draft PR generation** with unique branches
✅ **Copilot integration** for automated fixes
✅ **Monitoring and metrics** for system health
✅ **Extensible architecture** for future enhancements

The system significantly reduces manual intervention and accelerates issue resolution across all platform components.
