# GitHub Copilot Workflow Quick Reference

## For Developers: Using Copilot in Workflows

### 1. Invoking Copilot on a PR

**Method 1: Using the Script (Recommended)**
```bash
# Invoke Copilot with default instructions
python scripts/invoke_copilot_on_pr.py --pr 123

# Custom instructions
python scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix the linting errors"

# Specify repository
python scripts/invoke_copilot_on_pr.py --pr 123 --repo owner/repo

# Dry run (show what would be done)
python scripts/invoke_copilot_on_pr.py --pr 123 --dry-run
```

**Method 2: Using gh CLI Directly**
```bash
# Set authentication
export GH_TOKEN="your_token"

# Post Copilot comment
gh pr comment 123 --body "@github-copilot /fix

Please implement the fixes for this PR:
- Fix linting errors
- Update tests
- Add documentation"
```

**Method 3: In Workflow YAML**
```yaml
- name: Invoke Copilot
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    python scripts/invoke_copilot_on_pr.py \
      --pr ${{ github.event.pull_request.number }} \
      --instruction "Fix the workflow failure"
```

### 2. Checking Workflow Health

```bash
# Validate all workflows
python .github/scripts/validate_workflows.py

# Strict mode (warnings as errors)
python .github/scripts/validate_workflows.py --strict

# Validate specific directory
python .github/scripts/validate_workflows.py --workflows-dir .github/workflows
```

### 3. Common Workflow Patterns

#### Adding GH_TOKEN to a Step
```yaml
- name: Step using gh CLI
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    gh pr list
```

#### Self-Hosted Runner with Container
```yaml
jobs:
  my-job:
    runs-on: [self-hosted, linux, x64]
    container:
      image: python:3.12-slim
      options: --user root  # Note: Required for apt-get and system operations
      # For production: Consider using non-root user with sudo
```

#### Retry Logic in Scripts
```python
for attempt in range(max_retries):
    try:
        result = subprocess.run(cmd, timeout=60)
        break
    except subprocess.TimeoutExpired:
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff
```

### 4. Troubleshooting Quick Fixes

#### "gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN"
```yaml
# Add to step:
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

#### "Copilot not responding"
1. Check repository has Copilot enabled
2. Verify comment format: `@github-copilot /fix`
3. Wait 1-2 minutes for response
4. Check PR comments for Copilot's response

#### "Permission denied" errors
```yaml
# Add permissions to workflow:
permissions:
  contents: write
  pull-requests: write
  issues: write
```

#### "Module not found" in Python scripts
```yaml
- name: Install dependencies
  run: |
    pip install PyYAML requests
```

### 5. Best Practices Checklist

- [ ] Always set `GH_TOKEN` when using `gh` commands
- [ ] Use retry logic for network operations
- [ ] Add timeouts to subprocess calls
- [ ] Use containers for self-hosted runners
- [ ] Validate workflows before committing
- [ ] Document custom workflow behavior
- [ ] Test workflows with workflow_dispatch
- [ ] Monitor workflow runs regularly

### 6. Useful Commands

```bash
# List recent workflow runs
gh run list --limit 10

# View specific run
gh run view RUN_ID --log

# Download run logs
gh run download RUN_ID

# Re-run failed workflow
gh run rerun RUN_ID

# List open PRs
gh pr list --state open

# View PR details
gh pr view 123

# Comment on PR
gh pr comment 123 --body "Comment text"

# Check gh authentication
gh auth status

# List workflow files
gh workflow list
```

### 7. Testing Workflows Locally

```bash
# Validate workflows
python .github/scripts/validate_workflows.py

# Test Python scripts
python scripts/invoke_copilot_on_pr.py --pr 123 --dry-run

# Check workflow syntax
yamllint .github/workflows/*.yml
```

### 8. Monitoring Workflow Health

- **Automated**: Workflow Health Check runs daily at 6 AM UTC
- **Manual**: Run `python .github/scripts/validate_workflows.py`
- **Issues**: Auto-created when validation fails
- **Reports**: Available as workflow artifacts

### 9. Getting Help

1. **Documentation**:
   - [Troubleshooting Guide](.github/workflows/COPILOT_WORKFLOW_TROUBLESHOOTING.md)
   - [Workflow README](.github/workflows/README.md)
   - [GitHub Docs](https://docs.github.com/en/actions)

2. **Tools**:
   - Workflow Validator: `.github/scripts/validate_workflows.py`
   - Health Check Workflow: `.github/workflows/workflow-health-check.yml`

3. **Logs**:
   - View logs: `gh run view RUN_ID --log`
   - Download: `gh run download RUN_ID`

### 10. Common Error Solutions

| Error | Solution |
|-------|----------|
| Authentication failed | Set `GH_TOKEN` environment variable |
| Command not found | Install required tool or package |
| Permission denied | Add permissions to workflow or check file permissions |
| Timeout | Increase timeout or add retry logic |
| Module not found | Install Python dependencies |
| Container error | Check container image and options |

## Quick Links

- 🔧 [Troubleshooting Guide](COPILOT_WORKFLOW_TROUBLESHOOTING.md)
- 📊 [Workflow Health Check](.github/workflows/workflow-health-check.yml)
- ✅ [Validator Script](.github/scripts/validate_workflows.py)
- 📚 [Full README](.github/workflows/README.md)
- 🐛 [Report Issue](../../issues/new)

---

**Last Updated**: 2025-11-05
**Maintained By**: Auto-Healing System
