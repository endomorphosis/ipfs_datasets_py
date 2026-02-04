# Auto-Healing System Quick Reference

## Quick Start

### Enable Error Reporting

```bash
export ERROR_REPORTING_ENABLED=true
export GITHUB_TOKEN=${{ secrets.GITHUB_TOKEN }}
```

### Monitor System Health

```bash
# View recent workflow runs
gh run list --limit 10

# View specific workflow
gh run list --workflow=cli-error-monitoring.yml --limit 5
gh run list --workflow=javascript-sdk-monitoring.yml --limit 5
gh run list --workflow=mcp-tools-monitoring.yml --limit 5
gh run list --workflow=copilot-agent-autofix.yml --limit 5

# View auto-healing issues
gh issue list --label autofix --state open

# View auto-healing PRs
gh pr list --label autofix --state open
```

## Monitored Components

| Component | Workflow | Schedule | Manual Trigger |
|-----------|----------|----------|----------------|
| CLI Tools | cli-error-monitoring.yml | Daily 4 AM UTC | `gh workflow run cli-error-monitoring.yml` |
| MCP Tools | mcp-tools-monitoring.yml | Daily 6 AM UTC | `gh workflow run mcp-tools-monitoring.yml` |
| JS SDK | javascript-sdk-monitoring.yml | Daily 5 AM UTC | `gh workflow run javascript-sdk-monitoring.yml` |
| Dashboard | mcp-dashboard-tests.yml | Daily 2 AM UTC | `gh workflow run mcp-dashboard-tests.yml` |
| Auto-Healing | copilot-agent-autofix.yml | On workflow failure | `gh workflow run copilot-agent-autofix.yml` |

## Common Commands

### Trigger Manual Test

```bash
# Test CLI monitoring
gh workflow run cli-error-monitoring.yml -f test_mode=comprehensive

# Test specific MCP tool category
gh workflow run mcp-tools-monitoring.yml -f category=dataset_tools -f test_mode=category

# Test JS SDK in browser mode
gh workflow run javascript-sdk-monitoring.yml -f test_mode=browser

# Trigger auto-healing for specific workflow
gh workflow run copilot-agent-autofix.yml -f workflow_name="CLI Tools Error Monitoring"
```

### View Logs

```bash
# Get latest run ID
RUN_ID=$(gh run list --workflow=cli-error-monitoring.yml --limit 1 --json databaseId --jq '.[0].databaseId')

# View run details
gh run view $RUN_ID

# View run logs
gh run view $RUN_ID --log

# Download logs
gh run download $RUN_ID
```

### Check Auto-Healing Status

```bash
# Recent auto-healing activity
gh issue list --label autofix --limit 10 --json number,title,state,createdAt

# Open auto-healing PRs
gh pr list --label autofix --state open

# Recently closed fixes
gh pr list --label autofix --state closed --limit 10
```

## Error Reporting

### Python (CLI/MCP Tools)

```python
from ipfs_datasets_py.error_reporting.error_reporter import ErrorReporter

reporter = ErrorReporter(enabled=True)
try:
    # Your code
    risky_operation()
except Exception as e:
    reporter.report_error(e, context={'component': 'cli', 'command': 'test'})
```

### JavaScript (SDK/Dashboard)

```javascript
// Automatic - just enable
window.ERROR_REPORTING_ENABLED = true;

// Or manual
errorReporter.reportError(new Error('Test error'), {
    component: 'sdk',
    action: 'executeTool'
});
```

## Troubleshooting

### Workflow Not Running

```bash
# Check workflow file syntax
gh workflow view cli-error-monitoring.yml

# Check workflow runs
gh run list --workflow=cli-error-monitoring.yml --status=failure
```

### Auto-Healing Not Triggering

```bash
# 1. Check if workflow is in monitored list
grep "CLI Tools Error Monitoring" .github/workflows/copilot-agent-autofix.yml

# 2. Check for existing issues (duplicate detection)
gh issue list --search "Run ID: 123456 in:body"

# 3. View auto-healing debug info
gh run view <auto-healing-run-id> --log | grep "Debug workflow trigger"
```

### Error Reporter Not Working

```python
# Test Python error reporter
python -c "
from ipfs_datasets_py.error_reporting.error_reporter import ErrorReporter
reporter = ErrorReporter(enabled=True)
print(f'Enabled: {reporter.enabled}')
print(f'GitHub available: {reporter.github_client.is_available()}')
"
```

```javascript
// Test JS error reporter
console.log(window.errorReporter);
console.log(window.errorReporter?.enabled);
```

## Key Metrics

### Success Rate

```bash
# Count auto-fix PRs merged
MERGED=$(gh pr list --label autofix --state merged --json number | jq '. | length')
TOTAL=$(gh pr list --label autofix --state all --json number | jq '. | length')
echo "Success rate: $MERGED/$TOTAL"
```

### Average Time to Fix

```bash
# View PR merge times
gh pr list --label autofix --state merged --limit 10 --json number,createdAt,mergedAt
```

### Active Issues

```bash
# Open auto-healing issues
gh issue list --label autofix --state open --json number,title,createdAt
```

## Configuration Files

| File | Purpose |
|------|---------|
| `.github/workflows/cli-error-monitoring.yml` | CLI monitoring config |
| `.github/workflows/mcp-tools-monitoring.yml` | MCP tools monitoring config |
| `.github/workflows/javascript-sdk-monitoring.yml` | JS SDK monitoring config |
| `.github/workflows/copilot-agent-autofix.yml` | Auto-healing orchestrator |
| `.github/workflows/workflow-auto-fix-config.yml` | Exclusions config |
| `ipfs_datasets_py/error_reporting/` | Error reporting code |

## Environment Variables

```bash
# Core configuration
ERROR_REPORTING_ENABLED=true         # Enable/disable reporting
GITHUB_TOKEN=ghp_xxx                 # GitHub API token
GITHUB_REPOSITORY=owner/repo         # Target repository

# Advanced configuration
ERROR_MIN_REPORT_INTERVAL=3600       # Min seconds between same error (1 hour)
ERROR_MAX_REPORTS_PER_SESSION=10     # Max reports per session
MCP_DASHBOARD_PORT=8899              # Dashboard port for tests
```

## Workflow Dispatch Parameters

### CLI Monitoring

```bash
gh workflow run cli-error-monitoring.yml -f test_mode=basic
gh workflow run cli-error-monitoring.yml -f test_mode=comprehensive
gh workflow run cli-error-monitoring.yml -f test_mode=stress
```

### MCP Tools Monitoring

```bash
gh workflow run mcp-tools-monitoring.yml -f test_mode=basic
gh workflow run mcp-tools-monitoring.yml -f test_mode=comprehensive
gh workflow run mcp-tools-monitoring.yml -f category=dataset_tools -f test_mode=category
```

### JS SDK Monitoring

```bash
gh workflow run javascript-sdk-monitoring.yml -f test_mode=basic
gh workflow run javascript-sdk-monitoring.yml -f test_mode=comprehensive
gh workflow run javascript-sdk-monitoring.yml -f test_mode=browser
```

### Auto-Healing

```bash
gh workflow run copilot-agent-autofix.yml \
  -f workflow_name="CLI Tools Error Monitoring" \
  -f run_id=123456 \
  -f force_create_pr=false
```

## Best Practices

1. ✅ **Always provide context** when reporting errors
2. ✅ **Use appropriate log levels** (ERROR, WARNING, INFO, DEBUG)
3. ✅ **Test in disabled mode** before enabling reporting
4. ✅ **Monitor auto-healing metrics** regularly
5. ✅ **Review and merge PRs promptly** to close the feedback loop
6. ✅ **Update workflow lists** when adding new workflows
7. ✅ **Document custom error patterns** for your components

## Support Links

- **Full Documentation**: `.github/workflows/AUTO_HEALING_COMPREHENSIVE_GUIDE.md`
- **Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Discussions**: https://github.com/endomorphosis/ipfs_datasets_py/discussions
- **Actions**: https://github.com/endomorphosis/ipfs_datasets_py/actions

## Emergency Procedures

### Disable Auto-Healing

```bash
# Disable specific workflow
gh workflow disable copilot-agent-autofix.yml

# Or set environment variable
export ERROR_REPORTING_ENABLED=false
```

### Clean Up Stale PRs

```bash
# List old draft PRs
gh pr list --label autofix --state open --draft --json number,title,createdAt

# Close stale PR
gh pr close <number> --delete-branch
```

### Reset Error Reporter

```python
# Clear reported errors cache
from ipfs_datasets_py.error_reporting.error_reporter import ErrorReporter
reporter = ErrorReporter(enabled=True)
reporter._reported_errors.clear()
```

## Quick Checklist

Before deploying changes:
- [ ] Error reporting is tested and working
- [ ] Workflows are added to copilot-agent-autofix.yml
- [ ] Environment variables are set correctly
- [ ] GitHub token has required permissions
- [ ] Workflow syntax is valid (use `gh workflow view`)
- [ ] Test runs are successful
- [ ] Documentation is updated

## Version History

- **v1.0** (2024-02-04): Initial comprehensive auto-healing system
  - CLI monitoring
  - MCP tools monitoring  
  - JavaScript SDK monitoring
  - Enhanced dashboard monitoring
  - Unified auto-healing workflow
