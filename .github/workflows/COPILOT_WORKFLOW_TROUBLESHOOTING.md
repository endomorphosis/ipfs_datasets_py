# GitHub Copilot Workflow Troubleshooting Guide

## Overview

This guide helps troubleshoot issues with GitHub Actions workflows that use GitHub Copilot integration for automated issue resolution and PR fixes.

## Common Issues and Solutions

### 1. Authentication Failures

**Symptom**: Workflows fail with messages like:
```
gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable
```

**Solution**: Ensure GH_TOKEN is set in the step or job environment:

```yaml
- name: Step using gh CLI
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    gh pr list
```

**Root Cause**: The `gh` CLI requires authentication via the GH_TOKEN environment variable when running in GitHub Actions.

### 2. gh agent-task Command Not Found

**Symptom**: Error message:
```
gh: unknown command "agent-task" for "gh"
```

**Solution**: The `gh agent-task` command is a preview feature available in gh CLI v2.40.0+. To use it:

1. Verify gh CLI version:
   ```bash
   gh --version
   ```

2. Update if needed:
   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt install gh
   ```

**Note**: `gh agent-task` is built into gh CLI v2.40.0+ as a preview feature. The `gh-copilot` extension is separate and provides different functionality (code suggestions, explain commands).

### 3. Copilot Not Responding to PR Comments

**Symptom**: Comments with `@github-copilot` are posted but Copilot doesn't respond.

**Solution**:

1. **Check repository settings**: Ensure GitHub Copilot is enabled for your repository:
   - Go to Settings → Features → Copilot
   - Enable "Allow GitHub Copilot to be used in this repository"

2. **Verify comment format**: Use the correct format:
   ```
   @github-copilot /fix

   [Your instructions here]
   ```

3. **Check permissions**: Ensure the workflow has proper permissions:
   ```yaml
   permissions:
     contents: write
     pull-requests: write
     issues: write
   ```

4. **Wait for processing**: Copilot may take 1-2 minutes to respond

### 4. Self-Hosted Runner Issues

**Symptom**: Workflows fail with permission errors or file access issues on self-hosted runners.

**Solution**:

1. **Use containers for isolation**:
   ```yaml
   jobs:
     my-job:
       runs-on: [self-hosted, linux, x64]
       container:
         image: python:3.12-slim
         options: --user root
   ```

2. **Install gh CLI in container**:
   ```yaml
   - name: Install GitHub CLI
     env:
       GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
     run: |
       apt-get update
       apt-get install -y gh
   ```

3. **Configure git safely**:
   ```yaml
   - name: Configure git
     run: |
       git config --global --add safe.directory '*'
       git config --global user.name "github-actions[bot]"
       git config --global user.email "github-actions[bot]@users.noreply.github.com"
   ```

### 5. Script Import Errors

**Symptom**: Python scripts fail with `ModuleNotFoundError` or `ImportError`.

**Solution**:

1. **Ensure repository is checked out**:
   ```yaml
   - uses: actions/checkout@v4
     with:
       fetch-depth: 0
   ```

2. **Install dependencies**:
   ```yaml
   - name: Install dependencies
     run: |
       python -m pip install --upgrade pip
       pip install PyYAML requests
   ```

3. **Add repository to Python path** (if needed):
   ```python
   import sys
   import os
   sys.path.insert(0, os.path.abspath('.'))
   ```

### 6. Timeout Issues

**Symptom**: Workflows or steps timeout.

**Solution**:

1. **Increase timeout for long-running operations**:
   ```yaml
   - name: Long operation
     timeout-minutes: 30  # Default is 360
     run: |
       python long_script.py
   ```

2. **Add timeout to subprocess calls**:
   ```python
   result = subprocess.run(
       cmd,
       timeout=60,  # 60 seconds
       capture_output=True
   )
   ```

3. **Use retry logic** (already implemented in invoke_copilot_on_pr.py):
   ```python
   for attempt in range(max_retries):
       try:
           result = subprocess.run(cmd, timeout=60)
           break
       except subprocess.TimeoutExpired:
           if attempt < max_retries - 1:
               time.sleep(2 ** attempt)
   ```

### 7. Duplicate Processing

**Symptom**: Multiple workflows or jobs try to process the same failure/issue.

**Solution**: The workflows include duplicate detection:

```python
# Check for existing PRs
EXISTING_PRS=$(gh pr list --search "Run ID: $RUN_ID in:body" --state all)
if [ "$EXISTING_PRS" -gt 0 ]; then
    echo "Already processed, skipping"
    exit 0
fi
```

This is already implemented in `copilot-agent-autofix.yml`.

## Best Practices

### 1. Use Correct Copilot Invocation Method

**Recommended**: Use PR comments with `@github-copilot`

```bash
gh pr comment $PR_NUMBER --body "@github-copilot /fix

Please implement fixes for this workflow failure:
- Error: [describe error]
- Expected behavior: [describe expected behavior]
- Files to fix: [list files]"
```

### 2. Always Set GH_TOKEN

```yaml
- name: Any step using gh CLI
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    gh ...
```

### 3. Use Containers for Self-Hosted Runners

```yaml
container:
  image: python:3.12-slim
  options: --user root
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock  # If Docker is needed
```

### 4. Add Error Handling in Scripts

```python
try:
    result = subprocess.run(cmd, check=True, timeout=60)
except subprocess.CalledProcessError as e:
    logger.error(f"Command failed: {e.stderr}")
    return False
except subprocess.TimeoutExpired:
    logger.error("Command timed out")
    return False
```

### 5. Log Important Information

```yaml
- name: Debug step
  run: |
    echo "## Debug Information" >> $GITHUB_STEP_SUMMARY
    echo "- PR Number: $PR_NUMBER" >> $GITHUB_STEP_SUMMARY
    echo "- Run ID: ${{ github.run_id }}" >> $GITHUB_STEP_SUMMARY
```

## Workflow-Specific Issues

### copilot-agent-autofix.yml

**Purpose**: Automatically analyzes workflow failures and creates PRs with Copilot fixes.

**Common Issues**:
1. **Workflow not triggering**: Ensure the failed workflow is in the `workflows:` list
2. **Logs not downloaded**: Check runner has disk space and permissions
3. **PR creation fails**: Verify workflow permissions include `pull-requests: write`

**Debug**:
```bash
# Check if workflow is in monitored list
grep "workflow_name" .github/workflows/copilot-agent-autofix.yml
```

### issue-to-draft-pr.yml

**Purpose**: Converts issues to draft PRs with Copilot assigned.

**Common Issues**:
1. **PR not created**: Check if issue already has a PR
2. **Branch creation fails**: Verify branch naming is valid
3. **Copilot not assigned**: Ensure repository has Copilot enabled

**Debug**:
```bash
# Check for existing PRs for issue
gh pr list --search "Fixes #ISSUE_NUMBER in:body"
```

### pr-copilot-reviewer.yml

**Purpose**: Automatically assigns Copilot to review new PRs.

**Common Issues**:
1. **Workspace permission errors**: The workflow cleans workspace in each run
2. **Checkout fails**: Nuclear cleanup may be too aggressive
3. **Python packages not available**: PEP 668 externally-managed-environment

**Solution**: The workflow includes comprehensive cleanup and retry logic.

## Testing Workflows

### Test in Dry Run Mode

Many scripts support dry run:

```bash
python scripts/invoke_copilot_on_pr.py --pr 123 --dry-run
```

### Manual Workflow Dispatch

Test workflows manually:

```bash
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="My Workflow" \
  --field run_id="12345"
```

### Check Workflow Logs

```bash
# List recent runs
gh run list --workflow=copilot-agent-autofix.yml --limit=5

# View specific run
gh run view RUN_ID --log

# Download logs
gh run download RUN_ID
```

## Getting Help

### Check Workflow Health

```bash
python .github/scripts/test_workflow_scripts.py
```

### Review Documentation

- [GitHub Copilot Docs](https://docs.github.com/en/copilot)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [GitHub Actions Docs](https://docs.github.com/en/actions)

### Common Commands

```bash
# Check gh CLI authentication
gh auth status

# Test gh CLI
gh pr list

# Check Copilot availability (if extension installed)
gh copilot --version  # Note: This may not be available

# List workflow runs
gh run list

# View workflow file
gh workflow view copilot-agent-autofix.yml
```

## Recent Fixes Applied

As documented in `.github/workflow_fixes_applied.json`:

1. ✅ Added GH_TOKEN to 14 workflow steps
2. ✅ Fixed Copilot invocation methods
3. ✅ Added container isolation to multiple workflows
4. ✅ Enhanced error handling in invoke_copilot_on_pr.py
5. ✅ Added retry logic with exponential backoff

## Known Limitations

1. **gh agent-task preview**: This command is in preview and may change
2. **Copilot response time**: Copilot may take 1-5 minutes to respond to @mentions
3. **Container performance**: Containers on self-hosted runners may be slower
4. **Rate limits**: GitHub API rate limits apply to gh CLI commands

## Reporting Issues

If you encounter issues not covered here:

1. Check workflow run logs: `gh run view RUN_ID --log`
2. Review the PR or issue for error messages
3. Check repository settings and permissions
4. Open an issue with:
   - Workflow name
   - Run ID
   - Error message
   - Steps to reproduce
