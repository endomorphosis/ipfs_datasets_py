# GitHub Actions Workers Fix Guide

## Overview

This guide documents the fixes applied to GitHub Actions workflows to resolve broken workers using GitHub CLI and Copilot CLI tools.

## Tools Created

### 1. Workflow Health Check (`enhance_workflow_copilot_integration.py`)

**Purpose**: Comprehensive health check for GitHub Actions workflows

**Features**:
- Detects GitHub CLI and Copilot CLI installation
- Analyzes all workflow files for issues
- Identifies workflows using self-hosted runners
- Checks for missing GH_TOKEN configurations
- Generates detailed health report

**Usage**:
```bash
python .github/scripts/enhance_workflow_copilot_integration.py
```

**Output**:
- Console report with health status
- JSON report saved to `.github/workflow_health_report.json`

### 2. Workflow Fixer (`fix_workflow_issues.py`)

**Purpose**: Automatically fix common workflow issues

**Features**:
- Adds missing GH_TOKEN to steps using gh CLI
- Suggests container isolation for self-hosted runners
- Validates workflow YAML syntax
- Supports dry-run mode

**Usage**:
```bash
# Dry run (preview changes)
python .github/scripts/fix_workflow_issues.py --dry-run

# Apply fixes
python .github/scripts/fix_workflow_issues.py

# Fix specific workflow
python .github/scripts/fix_workflow_issues.py --workflow copilot-agent-autofix.yml
```

**Output**:
- Console report with fixes applied
- JSON report saved to `.github/workflow_fixes_applied.json`

### 3. Copilot Workflow Helper (`copilot_workflow_helper.py`)

**Purpose**: Integrate GitHub Copilot CLI with workflows

**Features**:
- Install gh-copilot extension
- Analyze workflow files using Copilot
- Get AI-powered code explanations
- Suggest workflow fixes
- Generate command suggestions

**Usage**:
```bash
# Install Copilot CLI extension
python .github/scripts/copilot_workflow_helper.py install

# Analyze a workflow
python .github/scripts/copilot_workflow_helper.py analyze copilot-agent-autofix.yml

# Suggest fixes
python .github/scripts/copilot_workflow_helper.py suggest-fix copilot-agent-autofix.yml

# Explain code
python .github/scripts/copilot_workflow_helper.py explain "gh run list"

# Suggest a command
python .github/scripts/copilot_workflow_helper.py suggest "list failed workflow runs"
```

## Issues Found and Fixed

### Summary
- **Total Workflows**: 27 active + 3 disabled
- **Self-Hosted Runners**: 26 workflows use self-hosted runners
- **Fixes Applied**: 14 GH_TOKEN additions
- **Issues Identified**: 12 workflows with potential issues

### Specific Fixes

#### 1. Missing GH_TOKEN Environment Variable

**Issue**: Workflows using `gh` CLI commands without proper authentication

**Workflows Fixed**:
- `continuous-queue-management.yml` (3 steps)
- `copilot-agent-autofix.yml` (1 step)
- `enhanced-pr-completion-monitor.yml` (1 step)
- `issue-to-draft-pr.yml` (1 step)
- `pr-completion-monitor.yml` (2 steps)
- `pr-copilot-monitor.yml` (1 step)
- `pr-copilot-reviewer.yml` (2 steps)
- `runner-validation.yml` (1 step)

**Fix Applied**:
```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

#### 2. Self-Hosted Runners Without Container Isolation

**Issue**: 12 workflows use self-hosted runners without container isolation

**Workflows Affected**:
- `continuous-queue-management.yml`
- `enhanced-pr-completion-monitor.yml`
- `fix-docker-permissions.yml`
- `gpu-tests.yml`
- `pr-completion-monitor.yml`
- `pr-copilot-monitor.yml`
- `pr-copilot-reviewer.yml`
- `publish_to_pipy.yml`
- `runner-validation-clean.yml`
- `runner-validation.yml`
- `test-datasets-runner.yml`
- `test-github-hosted.yml`

**Recommendation**:
```yaml
jobs:
  my-job:
    runs-on: [self-hosted, linux, x64]
    container:
      image: python:3.12-slim
      options: --user root
```

**Note**: This is a suggestion only. Some workflows may intentionally avoid containers (e.g., Docker-related workflows).

#### 3. Copilot CLI Integration Enhancement

**Issue**: Auto-healing workflows don't fully leverage Copilot CLI capabilities

**Workflow**: `copilot-agent-autofix.yml`

**Suggestion**: Add Copilot CLI commands for:
- Automated code analysis
- Command suggestions
- Error explanation

**Example Integration**:
```yaml
- name: Analyze failure with Copilot
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    # Use Copilot to explain the error
    gh copilot explain "$ERROR_LOG"
    
    # Get suggestions for fixing
    gh copilot suggest -t shell "fix GitHub Actions workflow failure: $ERROR_MESSAGE"
```

## GitHub CLI and Copilot CLI Status

### GitHub CLI (gh)
- **Status**: ✅ Installed
- **Version**: 2.82.1
- **Location**: `/usr/bin/gh`
- **Documentation**: https://cli.github.com/manual/gh

### Copilot CLI (gh-copilot)
- **Status**: ⚠️ Not installed (requires GH_TOKEN for installation)
- **Installation**: `gh extension install github/gh-copilot`
- **Documentation**: https://docs.github.com/en/copilot/github-copilot-in-the-cli

## Best Practices

### 1. Always Set GH_TOKEN for gh CLI

When using `gh` commands in workflows:

```yaml
- name: Step using gh CLI
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    gh run list
```

### 2. Use Container Isolation for Self-Hosted Runners

For better security and reproducibility:

```yaml
jobs:
  build:
    runs-on: [self-hosted, linux, x64]
    container:
      image: python:3.12-slim
      options: --user root
    steps:
      - uses: actions/checkout@v4
      # ... rest of steps
```

### 3. Leverage Copilot CLI for Auto-Healing

In auto-healing workflows:

```yaml
- name: Analyze failure with Copilot
  if: failure()
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    # Get AI-powered analysis
    python .github/scripts/copilot_workflow_helper.py analyze ${{ github.workflow }}
```

## Testing

### 1. Test Workflow Health Check

```bash
python .github/scripts/enhance_workflow_copilot_integration.py
```

Expected output:
- GitHub CLI status
- Copilot extension status
- Workflow summary
- Issues list

### 2. Test Workflow Fixer (Dry Run)

```bash
python .github/scripts/fix_workflow_issues.py --dry-run
```

Expected output:
- List of changes that would be made
- No actual file modifications

### 3. Test Copilot Helper (if token available)

```bash
export GH_TOKEN=$GITHUB_TOKEN  # Set token
python .github/scripts/copilot_workflow_helper.py install
python .github/scripts/copilot_workflow_helper.py suggest "list workflow runs"
```

## Resources

### Official Documentation
- [GitHub CLI Manual](https://cli.github.com/manual/gh)
- [GitHub Copilot CLI](https://docs.github.com/en/copilot/github-copilot-in-the-cli)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Copilot CLI Agents](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)

### Internal Documentation
- [Workflow README](.github/workflows/README.md)
- [Auto-Healing Guide](.github/workflows/AUTO_HEALING_GUIDE.md)
- [Scripts README](.github/scripts/README.md)

## Monitoring

### Health Check Schedule

Run health check regularly:

```bash
# Add to cron or workflow
0 */6 * * * cd /path/to/repo && python .github/scripts/enhance_workflow_copilot_integration.py
```

### Metrics to Track

1. **Workflow Success Rate**: Monitor via GitHub Actions UI
2. **Self-Hosted Runner Health**: Check runner availability
3. **Copilot Usage**: Track auto-healing success rate
4. **Fix Application**: Number of automatic fixes applied

## Troubleshooting

### Issue: GH_TOKEN not working

**Symptoms**: `gh` commands fail with authentication error

**Solution**:
```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  # OR
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Issue: Copilot CLI not available

**Symptoms**: `gh copilot` command not found

**Solution**:
1. Ensure GH_TOKEN is set
2. Install extension: `gh extension install github/gh-copilot`
3. Verify: `gh extension list`

### Issue: Self-hosted runner offline

**Symptoms**: Workflow queued indefinitely

**Solution**:
1. Check runner status: `gh api /repos/$REPO/actions/runners`
2. Restart runner service
3. Check runner logs

## Future Enhancements

1. **Automated Copilot Integration**: Add Copilot CLI to all auto-healing workflows
2. **Container Templates**: Create standard container configurations
3. **Health Monitoring Dashboard**: Real-time workflow health visualization
4. **Smart Retry Logic**: Use Copilot to suggest retry strategies
5. **Dependency Analysis**: Copilot-powered dependency issue detection

## Changelog

### 2025-11-05
- Created workflow health check script
- Created workflow fixer script
- Created Copilot workflow helper script
- Fixed 14 instances of missing GH_TOKEN
- Identified 12 workflows needing container isolation
- Documented all fixes and best practices

---

**Last Updated**: 2025-11-05
**Maintainer**: GitHub Actions Team
