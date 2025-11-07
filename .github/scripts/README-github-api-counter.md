# GitHub API Call Counter

This system tracks GitHub API calls made during GitHub Actions workflows to ensure we stay under the rate limit of 5000 requests per hour and identify optimization opportunities.

## Components

### 1. Core Counter Module (`github_api_counter.py`)
The main counter that tracks GitHub CLI and API calls.

**Features:**
- Tracks all `gh` CLI commands
- Counts API calls by type
- Monitors rate limit usage
- Saves metrics to JSON files
- Generates reports and summaries
- Appends to GitHub Actions step summary

### 2. Helper Module (`github_api_counter_helper.py`)
Drop-in replacement for subprocess that automatically tracks GitHub API calls.

**Features:**
- Transparent subprocess wrapper
- Auto-save on script exit
- Global counter singleton
- Optional monkey-patching

### 3. Shell Wrapper (`gh_wrapper.sh`)
Bash wrapper for `gh` CLI commands.

**Usage:**
```bash
# Instead of:
gh pr list

# Use:
.github/scripts/gh_wrapper.sh pr list
```

### 4. Dashboard Generator (`github_api_dashboard.py`)
Generates comprehensive reports of API usage.

**Features:**
- Aggregates metrics across workflows
- Identifies top API consumers
- Provides optimization suggestions
- Generates text, Markdown, or HTML reports

## Quick Start

### Method 1: Use in Python Scripts

```python
from github_api_counter import GitHubAPICounter

# Use as context manager
with GitHubAPICounter() as counter:
    counter.run_gh_command(['gh', 'pr', 'list'])
    counter.run_gh_command(['gh', 'issue', 'create', '--title', 'Test'])
# Metrics auto-saved on exit

# Or use manually
counter = GitHubAPICounter()
counter.run_gh_command(['gh', 'pr', 'list'])
counter.save_metrics()
```

### Method 2: Use Helper Module

```python
# Minimal changes to existing code
from github_api_counter_helper import tracked_subprocess

# Instead of:
# result = subprocess.run(['gh', 'pr', 'list'], ...)

# Use:
result = tracked_subprocess.run(['gh', 'pr', 'list'], ...)
# Metrics auto-saved on script exit
```

### Method 3: Monkey-Patch subprocess

```python
# At the top of your script
from github_api_counter_helper import patch_subprocess
patch_subprocess()

# Now all subprocess calls are automatically tracked
import subprocess
subprocess.run(['gh', 'pr', 'list'])  # Automatically counted!
```

### Method 4: Use Shell Wrapper

```bash
# In GitHub Actions workflows
- name: List PRs with tracking
  run: |
    .github/scripts/gh_wrapper.sh pr list --repo ${{ github.repository }}
```

## Integration into Workflows

### Example: Minimal Change Integration

```yaml
name: Example Workflow with API Tracking

on: push

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # Step 1: Run your workflow with tracking
      - name: Run workflow tasks
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # Use Python counter for scripts
          python3 .github/scripts/my_script.py
          
          # Or use shell wrapper for direct gh commands
          .github/scripts/gh_wrapper.sh pr list
          .github/scripts/gh_wrapper.sh issue list
      
      # Step 2: Generate dashboard (optional)
      - name: Generate API Usage Report
        run: |
          python3 .github/scripts/github_api_dashboard.py \
            --format markdown \
            --output $GITHUB_STEP_SUMMARY
      
      # Step 3: Upload metrics as artifact
      - name: Upload API metrics
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: github-api-metrics
          path: ${{ runner.temp }}/github_api_metrics_*.json
          retention-days: 30
```

### Example: Update Existing Script

**Before:**
```python
import subprocess

result = subprocess.run(['gh', 'pr', 'list'], capture_output=True)
print(result.stdout)
```

**After (Option 1 - Import helper):**
```python
from github_api_counter_helper import tracked_subprocess

result = tracked_subprocess.run(['gh', 'pr', 'list'], capture_output=True)
print(result.stdout)
# Metrics automatically saved on exit
```

**After (Option 2 - Use counter directly):**
```python
from github_api_counter import GitHubAPICounter

counter = GitHubAPICounter()
result = counter.run_gh_command(['gh', 'pr', 'list'], capture_output=True)
print(result.stdout)
counter.save_metrics()
```

## Updating Existing Python Scripts

For existing scripts like `invoke_copilot_on_pr.py`, add this at the top:

```python
# Add import at the top
from github_api_counter_helper import patch_subprocess
patch_subprocess()

# Rest of your code stays the same!
# All subprocess calls to 'gh' will be automatically tracked
```

Or use the context manager approach:

```python
from github_api_counter import GitHubAPICounter

class CopilotAgentInvoker:
    def __init__(self):
        self.api_counter = GitHubAPICounter()
    
    def run_command(self, cmd):
        # Use counter to run commands
        return self.api_counter.run_gh_command(cmd)
    
    def cleanup(self):
        # Save metrics
        self.api_counter.save_metrics()
```

## Viewing Reports

### Generate Text Report
```bash
python3 .github/scripts/github_api_dashboard.py
```

### Generate Markdown Report
```bash
python3 .github/scripts/github_api_dashboard.py \
  --format markdown \
  --output report.md
```

### Generate HTML Dashboard
```bash
python3 .github/scripts/github_api_dashboard.py \
  --format html \
  --output dashboard.html
```

## Metrics File Format

Metrics are saved as JSON files:

```json
{
  "workflow_run_id": "12345",
  "workflow_name": "CI Tests",
  "start_time": "2025-11-07T04:47:20.008Z",
  "end_time": "2025-11-07T04:52:20.008Z",
  "duration_seconds": 300,
  "call_counts": {
    "gh_pr_list": 5,
    "gh_issue_create": 2,
    "gh_run_view": 10
  },
  "call_timestamps": [
    {
      "type": "gh_pr_list",
      "count": 1,
      "timestamp": "2025-11-07T04:47:25.123Z",
      "metadata": {"command": "gh pr list"}
    }
  ],
  "total_calls": 17,
  "estimated_cost": 17
}
```

## Rate Limits

- **GitHub API**: 5000 requests per hour for authenticated requests
- **Warning threshold**: 80% (4000 requests)
- **Critical threshold**: 90% (4500 requests)

The counter will:
- ✅ Log warnings when approaching limits
- ⚠️ Show alerts in step summary
- 📊 Track which workflows consume most API calls

## Optimization Strategies

Based on metrics, you can optimize by:

1. **Caching Results**: Cache `gh pr list` responses instead of repeated calls
2. **Batch Operations**: Combine multiple API calls into single operations
3. **Reduce Frequency**: Decrease polling intervals
4. **Use GraphQL**: Replace multiple REST calls with single GraphQL query
5. **Conditional Execution**: Skip API calls when not needed

## Troubleshooting

### Metrics not saving
- Check `$RUNNER_TEMP` is writable
- Ensure script has exit handler registered
- Verify no early exits that skip cleanup

### Counts seem low
- Verify you're using the wrapper/counter
- Check that `gh` commands go through the counter
- Look for direct API calls not using `gh` CLI

### Rate limit warnings
- Review the dashboard for top consumers
- Implement caching for repeated calls
- Add delays between non-critical calls
- Consider splitting workflows

## Testing

Run the test suite:

```bash
python3 .github/scripts/test_github_api_counter.py
```

Expected output: All tests should pass.

## Files in This System

```
.github/scripts/
├── github_api_counter.py          # Core counter module
├── github_api_counter_helper.py   # Helper for easy integration
├── gh_wrapper.sh                  # Shell wrapper for gh commands
├── github_api_dashboard.py        # Dashboard/report generator
├── test_github_api_counter.py     # Test suite
└── README-github-api-counter.md   # This file
```

## Best Practices

1. **Always use the counter** for production workflows
2. **Review metrics weekly** to identify optimization opportunities
3. **Set up alerts** for workflows approaching limits
4. **Archive metrics** for long-term analysis
5. **Document optimizations** when reducing API calls

## Examples in This Repository

See these files for examples:
- `.github/workflows/example-with-api-tracking.yml` - Example workflow
- `.github/scripts/invoke_copilot_on_pr.py` - Can be updated to use counter
- `.github/scripts/analyze_workflow_failure.py` - Example Python script

## Support

For questions or issues:
1. Check this README
2. Review test suite for examples
3. Check metrics JSON for debugging
4. Open an issue with metrics attached
