# Error Reporting Quick Start Guide

This guide shows you how to quickly enable and use the runtime error reporting system.

## Quick Setup (3 Steps)

### 1. Set Environment Variables

```bash
# Enable error reporting
export ERROR_REPORTING_ENABLED=true

# Set your GitHub token
export GITHUB_TOKEN=your_github_token_here
```

Or add to your `.env` file:
```
ERROR_REPORTING_ENABLED=true
GITHUB_TOKEN=your_github_token_here
```

### 2. Install GitHub CLI

```bash
# macOS
brew install gh

# Ubuntu/Debian
sudo apt install gh

# Or visit https://cli.github.com/

# Authenticate
gh auth login
```

### 3. Start Your Application

The error reporting system will now automatically capture and report errors!

## Usage Examples

### Python - MCP Server

```python
# Start MCP server with error reporting
python -m ipfs_datasets_py.mcp_server --http --port 8000
```

Error reporting is automatically enabled if `ERROR_REPORTING_ENABLED=true`.

### Python - Manual Reporting

```python
from ipfs_datasets_py.error_reporting import get_global_error_reporter

reporter = get_global_error_reporter()

# Report an error
try:
    risky_operation()
except Exception as e:
    reporter.report_exception(e, context={'user': 'admin'})
```

### JavaScript - Dashboard

Error reporting is automatically enabled in the dashboard when:
- `ERROR_REPORTING_ENABLED=true`
- The error-reporter.js script is included

### Docker - Wrapped Commands

```dockerfile
FROM python:3.12-slim

# Copy error monitor
COPY ipfs_datasets_py/error_reporting/docker_error_monitor.py /app/

# Use it as entrypoint
ENTRYPOINT ["python", "/app/docker_error_monitor.py"]
CMD ["python", "your_app.py"]
```

## What Gets Reported

When an error occurs, a GitHub issue is automatically created with:

- **Error Type** (e.g., TypeError, ValueError)
- **Error Message**
- **Stack Trace**
- **Source** (python, javascript, docker)
- **Context** (custom data you provide)
- **Environment Info** (Python version, platform, hostname)

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ERROR_REPORTING_ENABLED` | `false` | Enable/disable error reporting |
| `GITHUB_REPOSITORY` | `endomorphosis/ipfs_datasets_py` | Target repository |
| `GITHUB_TOKEN` | - | GitHub authentication token |
| `GH_TOKEN` | - | Alternative GitHub token variable |

### Python Configuration

```python
from ipfs_datasets_py.error_reporting import ErrorReporter

reporter = ErrorReporter(
    enabled=True,
    repo='owner/repo',
    github_token='token',
    min_report_interval=3600  # Don't report same error for 1 hour
)
```

## Testing the System

Run the example script:

```bash
python examples/error_reporting_example.py
```

This demonstrates all features in dry-run mode (won't create real issues).

## API Endpoints

When integrated with the MCP server:

### Check Status
```bash
curl http://localhost:8000/api/error-reporting/status
```

### Report Error
```bash
curl -X POST http://localhost:8000/api/report-error \
  -H "Content-Type: application/json" \
  -d '{
    "error_type": "ValueError",
    "error_message": "Invalid input",
    "source": "python"
  }'
```

## Troubleshooting

### Error reporting not working

1. **Check if enabled:**
   ```bash
   echo $ERROR_REPORTING_ENABLED
   ```

2. **Verify GitHub CLI:**
   ```bash
   gh auth status
   ```

3. **Check logs:**
   Look for "Error reporting enabled" or "Error reporting disabled" messages.

### Issues not being created

1. **Token permissions**: Ensure your GitHub token has `repo` and `issues:write` permissions
2. **Deduplication**: Same error won't be reported twice within the interval (default: 1 hour)
3. **Rate limiting**: JavaScript errors are limited to 10 per session

## Security Notes

- ⚠️ **Never commit tokens to source code**
- 🔒 **Use environment variables for sensitive data**
- 🛡️ **Review error context for sensitive information**
- 📊 **Deduplication prevents spam**

## Next Steps

- See [README.md](README.md) for detailed documentation
- Check [examples/error_reporting_example.py](../examples/error_reporting_example.py) for code examples
- Review [tests/](../../tests/unit/error_reporting/) for usage patterns

## Support

For issues or questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review the full documentation in README.md
