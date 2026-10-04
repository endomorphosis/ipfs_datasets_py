# Testing the Auto-Healing System

This guide explains how to test the auto-healing system to ensure it works correctly.

## Overview

The auto-healing system can be tested in several ways:
1. **Wait for natural failure** (passive testing)
2. **Create intentional failure** (active testing)
3. **Manual trigger** (controlled testing)
4. **Dry run** (safe testing)

## Method 1: Wait for Natural Failure (Passive)

Simply wait for a workflow to fail naturally. The system will automatically:
1. Detect the failure
2. Analyze it
3. Create a PR
4. Mention @copilot
5. Have Copilot implement the fix

**No action required** - just monitor for auto-healing PRs.

## Method 2: Create Intentional Failure (Active)

Create a test workflow that intentionally fails to trigger the auto-healing system.

### Step 1: Create Test Workflow

```bash
# Create a test workflow
cat > .github/workflows/test-autohealing.yml << 'EOF'
name: Test Auto-Healing

on:
  workflow_dispatch:
  push:
    branches:
      - test-autohealing

jobs:
  test-dependency-error:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Test missing dependency
        run: |
          python -c "import nonexistent_package"  # This will fail
EOF

git add .github/workflows/test-autohealing.yml
git commit -m "Add test workflow for auto-healing"
git push
```

### Step 2: Trigger Test Workflow

```bash
# Via GitHub CLI
gh workflow run test-autohealing.yml

# Or via GitHub UI
# Go to Actions → Test Auto-Healing → Run workflow
```

### Step 3: Observe Auto-Healing

1. **Wait for failure** (~1 minute)
2. **Check for auto-healing run**:
   ```bash
   gh run list --workflow="Copilot Agent Auto-Healing"
   ```
3. **Look for PR created**:
   ```bash
   gh pr list --label "auto-healing"
   ```
4. **Monitor Copilot implementation**:
   ```bash
   gh pr view <PR_NUMBER> --comments
   ```

### Step 4: Validate Fix

Once Copilot implements the fix:
1. Review the changes
2. Check test results
3. Verify fix addresses the error
4. Merge if correct

### Step 5: Cleanup

```bash
# Delete test workflow
git rm .github/workflows/test-autohealing.yml
git commit -m "Remove test workflow"
git push

# Close test PR if created
gh pr close <PR_NUMBER>
```

## Method 3: Manual Trigger (Controlled)

Test with a specific failed workflow run.

### Step 1: Find a Failed Run

```bash
# List recent failed runs
gh run list --status failure --limit 10
```

### Step 2: Trigger Auto-Healing

```bash
# For specific workflow
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Docker Build and Test"

# For specific run ID
gh workflow run copilot-agent-autofix.yml \
  --field run_id="1234567890"

# Force PR creation
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Test Workflow" \
  --field force_create_pr=true
```

### Step 3: Monitor Progress

```bash
# Watch the auto-healing workflow
gh run watch

# Check for PR
gh pr list --label "auto-healing"
```

## Method 4: Dry Run (Safe Testing)

Test without creating actual PRs.

### Configure Dry Run

Edit `.github/workflows/workflow-auto-fix-config.yml`:

```yaml
debug:
  dry_run: true  # Enable dry run mode
  verbose_logging: true
```

### Run Test

```bash
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Any-Workflow"
```

### Check Results

The workflow will:
- ✅ Analyze the failure
- ✅ Generate fix proposal
- ✅ Create artifacts
- ❌ NOT create PR
- ❌ NOT mention @copilot

Review artifacts to see what would have happened:

```bash
# Download artifacts
gh run download <RUN_ID>

# Review analysis
cat workflow_logs/summary.txt
cat failure_analysis.json
cat fix_proposal.json
```

## Test Scenarios

### Scenario 1: Missing Dependency

**Setup**:
```python
# In a workflow, add:
- name: Test import
  run: python -c "import pytest_asyncio"
```

**Expected**:
- Error detected: "Missing Dependency"
- Fix proposed: Add `pytest-asyncio` to requirements
- Copilot adds package and updates workflow
- Tests pass

### Scenario 2: Timeout

**Setup**:
```yaml
# In a workflow job:
timeout-minutes: 1
steps:
  - name: Long running task
    run: sleep 120  # Will timeout
```

**Expected**:
- Error detected: "Timeout"
- Fix proposed: Increase timeout to 30 minutes
- Copilot updates `timeout-minutes`
- Workflow completes

### Scenario 3: Permission Error

**Setup**:
```yaml
# In a workflow WITHOUT permissions:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Create PR
        run: gh pr create ...  # Will fail with 403
```

**Expected**:
- Error detected: "Permission Error"
- Fix proposed: Add permissions section
- Copilot adds required permissions
- Workflow succeeds

### Scenario 4: Docker Error

**Setup**:
```yaml
# In a workflow:
- name: Build image
  run: docker build -t test .  # May fail if Docker not available
```

**Expected**:
- Error detected: "Docker Error"
- Fix proposed: Add Docker Buildx setup
- Copilot adds Docker setup steps
- Build succeeds

## Verification Checklist

After testing, verify:

- [ ] Workflow failure detected
- [ ] Analysis ran successfully
- [ ] Fix proposal generated
- [ ] PR created with correct labels
- [ ] @copilot mentioned in PR
- [ ] Task file created (`.github/copilot-tasks/`)
- [ ] Copilot implemented fix
- [ ] Changes committed to PR
- [ ] Tests ran and passed
- [ ] Issue tracking updated
- [ ] Artifacts uploaded

## Monitoring Commands

### View Auto-Healing Activity

```bash
# List auto-healing PRs
gh pr list --label "auto-healing"

# View auto-healing workflow runs
gh run list --workflow="Copilot Agent Auto-Healing"

# Get latest auto-healing run
gh run list --workflow="Copilot Agent Auto-Healing" --limit 1

# View specific PR
gh pr view <PR_NUMBER>

# See Copilot's commits
gh pr view <PR_NUMBER> --json commits

# Check test status
gh pr checks <PR_NUMBER>
```

### Download Artifacts

```bash
# List artifacts
gh run view <RUN_ID> --json artifacts

# Download specific artifact
gh run download <RUN_ID> -n copilot-autofix-<RUN_ID>

# Extract and review
cd copilot-autofix-<RUN_ID>
cat failure_analysis.json | jq
cat fix_proposal.json | jq
ls -la workflow_logs/
```

### Get Metrics

```bash
# View metrics
python .github/scripts/analyze_autohealing_metrics.py

# Export to JSON
python .github/scripts/analyze_autohealing_metrics.py --json metrics.json

# Recent activity only
python .github/scripts/analyze_autohealing_metrics.py --days 7
```

## Troubleshooting Tests

### PR Not Created

**Check**:
1. Workflow run logs for errors
2. Confidence score in artifacts (may be too low)
3. Rate limiting (max PRs per day)
4. Permissions

**Debug**:
```bash
# View workflow run
gh run view <RUN_ID> --log

# Check config
cat .github/workflows/workflow-auto-fix-config.yml | grep -A 5 "min_confidence"

# Verify permissions
gh api /repos/:owner/:repo --jq .permissions
```

### Copilot Didn't Respond

**Check**:
1. @copilot mentioned in PR comment
2. Task file created
3. Copilot enabled for repo

**Debug**:
```bash
# Check PR comments
gh pr view <PR_NUMBER> --comments

# Check for task file in branch
gh pr checkout <PR_NUMBER>
ls -la .github/copilot-tasks/

# Verify Copilot is enabled
# Go to repo settings → Code security and analysis
```

### Fix Didn't Work

**Check**:
1. Test results
2. Copilot's implementation
3. Analysis was correct

**Debug**:
```bash
# View test logs
gh run view <RUN_ID> --log

# See what Copilot changed
gh pr diff <PR_NUMBER>

# Review analysis
gh run download <AUTOFIX_RUN_ID>
cat failure_analysis.json | jq
```

## Performance Testing

### Measure Time to Fix

```bash
# Track timestamps
START=$(gh pr view <PR_NUMBER> --json createdAt --jq .createdAt)
END=$(gh pr view <PR_NUMBER> --json mergedAt --jq .mergedAt)

# Calculate duration
python -c "
from datetime import datetime
start = datetime.fromisoformat('$START'.replace('Z', '+00:00'))
end = datetime.fromisoformat('$END'.replace('Z', '+00:00'))
print(f'Time to fix: {(end - start).total_seconds() / 60:.1f} minutes')
"
```

### Measure Success Rate

```bash
# Get metrics
python .github/scripts/analyze_autohealing_metrics.py --json metrics.json

# View success rate
jq '.success_rate' metrics.json
```

## Continuous Testing

### Set Up Monitoring

Create a script to monitor auto-healing activity:

```bash
#!/bin/bash
# monitor_autohealing.sh

while true; do
  echo "=== $(date) ==="
  
  # Check for new PRs
  NEW_PRS=$(gh pr list --label "auto-healing" --state open --json number --jq length)
  echo "Open auto-healing PRs: $NEW_PRS"
  
  # Check recent runs
  RECENT_RUNS=$(gh run list --workflow="Copilot Agent Auto-Healing" --limit 5 --json status,conclusion --jq '.[] | "\(.status) - \(.conclusion)"')
  echo "Recent runs:"
  echo "$RECENT_RUNS"
  
  # Get metrics
  python .github/scripts/analyze_autohealing_metrics.py --quiet --json /tmp/metrics.json
  SUCCESS_RATE=$(jq -r '.success_rate.success_rate' /tmp/metrics.json)
  echo "Success rate: $SUCCESS_RATE%"
  
  echo ""
  sleep 300  # Check every 5 minutes
done
```

## Best Practices

### Before Testing

1. ✅ Review documentation
2. ✅ Understand expected behavior
3. ✅ Have monitoring commands ready
4. ✅ Know how to rollback if needed

### During Testing

1. ✅ Monitor workflow runs
2. ✅ Watch for PRs created
3. ✅ Check Copilot activity
4. ✅ Review artifacts
5. ✅ Validate fixes

### After Testing

1. ✅ Review all PRs created
2. ✅ Check test results
3. ✅ Gather metrics
4. ✅ Document any issues
5. ✅ Clean up test resources

## Success Criteria

A successful test should demonstrate:

- ✅ Failure detected automatically
- ✅ Analysis completed with >70% confidence
- ✅ PR created with proper labels
- ✅ @copilot mentioned correctly
- ✅ Task file generated
- ✅ Copilot implemented fix
- ✅ Tests passed
- ✅ Fix merged successfully
- ✅ Workflow now passes

## Next Steps

After successful testing:

1. **Monitor in production** - Let it run on real failures
2. **Track metrics** - Use metrics script regularly
3. **Tune thresholds** - Adjust confidence levels as needed
4. **Add patterns** - Extend error detection
5. **Share results** - Report success to team

## Support

If you encounter issues:

1. Check workflow logs
2. Review artifacts
3. Search documentation
4. Create issue with details
5. Tag maintainers

---

**Happy Testing!** 🧪✨

The auto-healing system is designed to work reliably. These tests help verify it's functioning correctly in your environment.
