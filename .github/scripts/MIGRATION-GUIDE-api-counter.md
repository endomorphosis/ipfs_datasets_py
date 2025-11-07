# Migration Guide: Adding API Counter to Existing Workflows

This guide shows how to integrate the GitHub API counter into your existing workflows with minimal changes.

## Quick Migration Checklist

- [ ] Add counter import to Python scripts that use `gh` CLI
- [ ] Update workflow YAML to generate metrics report
- [ ] Add artifact upload step for metrics
- [ ] Review and optimize based on first metrics

## Step-by-Step Migration

### 1. For Python Scripts

**Option A: Import and use directly (Recommended for new code)**

```python
# Add at the top of your script
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.github', 'scripts'))

from github_api_counter import GitHubAPICounter

# In your class __init__:
self.api_counter = GitHubAPICounter()

# Replace subprocess.run calls:
# Old:
result = subprocess.run(['gh', 'pr', 'list'], ...)

# New:
result = self.api_counter.run_gh_command(['gh', 'pr', 'list'], ...)

# At the end (cleanup method or main):
self.api_counter.save_metrics()
```

**Option B: Use helper module (Easiest for existing code)**

```python
# Add at the very top of your script
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.github', 'scripts'))

from github_api_counter_helper import patch_subprocess
patch_subprocess()

# That's it! All subprocess calls are now tracked automatically
# Metrics auto-save on script exit
```

**Option C: Drop-in replacement**

```python
# Change your imports
# Old:
import subprocess

# New:
from github_api_counter_helper import tracked_subprocess as subprocess

# Everything else stays the same!
# Metrics auto-save on script exit
```

### 2. For Bash Scripts in Workflows

**Before:**
```yaml
- name: List PRs
  run: gh pr list --repo ${{ github.repository }}
```

**After:**
```yaml
- name: List PRs with tracking
  run: .github/scripts/gh_wrapper.sh pr list --repo ${{ github.repository }}
```

### 3. For Workflow YAML Files

Add these steps to your workflow:

```yaml
# Add this after your main workflow steps
- name: Generate API Usage Report
  if: always()
  run: |
    python3 .github/scripts/github_api_dashboard.py \
      --format markdown \
      --output api_usage_report.md
    
    # Append to step summary
    if [ -f api_usage_report.md ]; then
      cat api_usage_report.md >> $GITHUB_STEP_SUMMARY
    fi

- name: Upload API metrics
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: github-api-metrics-${{ github.run_id }}
    path: |
      ${{ runner.temp }}/github_api_metrics_*.json
      api_usage_report.md
    retention-days: 30
```

## Specific Migration Examples

### Example 1: copilot-agent-autofix.yml

**Current code (lines 152-154):**
```yaml
EXISTING_PRS=$(gh pr list --repo ${{ github.repository }} \
  --search "Run ID: $RUN_ID in:body" \
  --state all --json number --jq 'length' 2>&1 || echo "0")
```

**Updated code:**
```yaml
EXISTING_PRS=$(.github/scripts/gh_wrapper.sh pr list --repo ${{ github.repository }} \
  --search "Run ID: $RUN_ID in:body" \
  --state all --json number --jq 'length' 2>&1 || echo "0")
```

**Or with Python:**
```yaml
# Add this step before any gh commands
- name: Initialize API counter
  run: |
    cat > /tmp/count_gh.py <<'EOF'
    import sys
    sys.path.insert(0, '.github/scripts')
    from github_api_counter import GitHubAPICounter
    counter = GitHubAPICounter()
    
    import subprocess
    result = counter.run_gh_command(sys.argv[1:])
    print(result.stdout)
    sys.exit(result.returncode)
    EOF
    
    # Create wrapper function
    gh() { python3 /tmp/count_gh.py gh "$@"; }
    export -f gh
```

### Example 2: analyze_workflow_failure.py

**Add to imports:**
```python
try:
    from github_api_counter_helper import patch_subprocess
    patch_subprocess()
except ImportError:
    pass  # Counter not available, continue without tracking
```

### Example 3: invoke_copilot_on_pr.py

Already done! See the updated file for reference.

## Verifying Integration

### 1. Test Locally

```bash
# Run your script
python3 scripts/your_script.py

# Check if metrics were created
ls -la /tmp/github_api_metrics_*.json

# View the metrics
python3 .github/scripts/github_api_dashboard.py
```

### 2. Test in Workflow

Trigger your workflow and check:

1. **Step Summary**: Should show API usage metrics
2. **Artifacts**: Should contain `github-api-metrics-*.json`
3. **Logs**: Should show "GitHub API counter enabled"

### 3. Review Metrics

```bash
# Download artifacts from workflow run
gh run download <RUN_ID> -n github-api-metrics

# Generate report
python3 .github/scripts/github_api_dashboard.py \
  --metrics-dir . \
  --format text
```

## Common Issues and Solutions

### Issue: "Module not found: github_api_counter"

**Solution:** Add the correct path to sys.path:
```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.github', 'scripts'))
```

### Issue: "Metrics file not created"

**Solution:** Ensure the script exits cleanly. Add explicit save:
```python
import atexit
counter = GitHubAPICounter()
atexit.register(counter.save_metrics)
```

### Issue: "Permission denied: gh_wrapper.sh"

**Solution:** Make the wrapper executable:
```bash
chmod +x .github/scripts/gh_wrapper.sh
```

Or run with bash explicitly:
```yaml
run: bash .github/scripts/gh_wrapper.sh pr list
```

## Gradual Migration Strategy

You don't have to migrate everything at once. Here's a recommended approach:

### Phase 1: High-Traffic Workflows (Week 1)
- copilot-agent-autofix.yml
- pr-copilot-monitor.yml
- issue-to-draft-pr.yml

### Phase 2: CI/CD Workflows (Week 2)
- graphrag-production-ci.yml
- mcp-integration-tests.yml
- docker-build-test.yml

### Phase 3: Monitoring Workflows (Week 3)
- pr-completion-monitor.yml
- workflow-health-check.yml

### Phase 4: All Remaining Workflows (Week 4)
- Any workflows not yet migrated

## Optimization After Migration

Once you have metrics from all workflows, use them to optimize:

### 1. Identify Top Consumers

```bash
python3 .github/scripts/github_api_dashboard.py --format text
```

Look for:
- Workflows with > 500 API calls
- Call types with high frequency
- Workflows hitting rate limits

### 2. Common Optimizations

**Cache gh pr list results:**
```bash
# Before: Multiple calls
gh pr list > /tmp/prs.json
gh pr list | grep "something"

# After: One call, reuse result
gh pr list > /tmp/prs.json
cat /tmp/prs.json | grep "something"
```

**Batch operations:**
```python
# Before: N API calls
for pr in pr_list:
    get_pr_details(pr)

# After: 1 API call
prs = gh pr list --json number,title,body
```

**Add caching:**
```python
import functools
import time

@functools.lru_cache(maxsize=128)
def get_pr_list(repo, max_age=300):
    return gh_pr_list(repo)
```

### 3. Set Up Alerts

Create a monitoring workflow:

```yaml
name: API Usage Monitor

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours

jobs:
  check-usage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Check API usage
        run: |
          python3 .github/scripts/github_api_dashboard.py
          
          # Check if approaching limits
          if python3 -c "from github_api_counter import GitHubAPICounter; \
             c = GitHubAPICounter(); c._load_existing_metrics(); \
             exit(1 if c.is_approaching_limit(threshold=0.8) else 0)"; then
            echo "::warning::Approaching GitHub API rate limit!"
          fi
```

## Testing Your Migration

Use the test script:

```bash
# Test the counter itself
python3 .github/scripts/test_github_api_counter.py

# Test your integration
python3 your_updated_script.py

# Verify metrics were created
ls -la $RUNNER_TEMP/github_api_metrics_*.json
```

## Support

If you encounter issues:
1. Check the README: `.github/scripts/README-github-api-counter.md`
2. Review test examples: `.github/scripts/test_github_api_counter.py`
3. Check example workflow: `.github/workflows/example-github-api-tracking.yml`
4. Look at updated script: `scripts/invoke_copilot_on_pr.py`

## Rollback Plan

If you need to rollback a migration:

1. **Python scripts**: Remove the import and use regular subprocess
2. **Bash scripts**: Change back from gh_wrapper.sh to gh
3. **Workflows**: Remove the reporting and artifact steps

The counter is designed to fail gracefully - if it's not available or has issues, your scripts will continue to work without tracking.
