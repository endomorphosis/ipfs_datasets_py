# PR Copilot Monitor - Quick Reference Guide

## Overview

The **PR Copilot Monitor** workflow automatically monitors all open pull requests and assigns GitHub Copilot to PRs that need assistance. It runs every 5 minutes automatically and can also be triggered manually.

## Workflow File

📄 `.github/workflows/pr-copilot-monitor.yml`

## Features

- ✅ **Automatic Monitoring**: Runs every 5 minutes via cron schedule
- ✅ **Smart Detection**: Identifies incomplete PRs needing Copilot assistance
- ✅ **Auto-Assignment**: Assigns @copilot to PRs that need work
- ✅ **Manual Triggers**: Supports workflow_dispatch for on-demand execution
- ✅ **Dry Run Mode**: Test without making changes
- ✅ **Force Reassign**: Override existing Copilot assignments

## Usage

### 1. Monitor All Open PRs

```bash
gh workflow run pr-copilot-monitor.yml
```

This will:
- Check all open PRs in the repository
- Identify incomplete PRs
- Assign @copilot to PRs needing assistance

### 2. Monitor Specific PR

```bash
gh workflow run pr-copilot-monitor.yml -f pr_number=246
```

Replace `246` with your PR number.

### 3. Dry Run Mode

```bash
gh workflow run pr-copilot-monitor.yml -f dry_run=true
```

Analyzes PRs and shows what would be done without making changes.

### 4. Force Reassignment

```bash
gh workflow run pr-copilot-monitor.yml -f force_reassign=true
```

Assigns @copilot even if already assigned (useful for stuck PRs).

### 5. Combined Options

```bash
# Specific PR + dry run
gh workflow run pr-copilot-monitor.yml -f pr_number=246 -f dry_run=true

# Specific PR + force reassign
gh workflow run pr-copilot-monitor.yml -f pr_number=246 -f force_reassign=true

# All PRs + force reassign
gh workflow run pr-copilot-monitor.yml -f force_reassign=true
```

## What Gets Monitored

The workflow detects PRs that need Copilot assistance based on:

### ✅ Incomplete Indicators
- Draft PRs
- PRs with "WIP" (Work In Progress) in title
- PRs with "TODO" or unchecked checkboxes `- [ ]`
- PRs marked as "in progress" or "incomplete"
- PRs with "needs work" or "under development" labels

### ✅ PR Types
- Auto-generated PRs needing review
- Workflow fix PRs
- PRs blocked or waiting for implementation
- PRs with failing tests

### ✅ Assignment Logic
- Only assigns if Copilot not already assigned (unless `force_reassign=true`)
- Prioritizes PRs based on type (workflow fixes = high priority)
- Creates appropriate task comments for Copilot

## Workflow Outputs

The workflow provides:

1. **Job Summary**: Shows completion status in GitHub Actions UI
2. **PR Analysis**: Details what was detected for each PR
3. **Assignment Status**: Confirms if @copilot was assigned
4. **Statistics**: Total PRs checked, incomplete PRs, assignments made

## Automatic Execution

The workflow runs automatically:
- **Schedule**: Every 5 minutes (via cron: `*/5 * * * *`)
- **Trigger**: On push to `main` branch (optional)
- **Manual**: Via `workflow_dispatch` (on-demand)

## Troubleshooting

### Workflow Not Found (HTTP 404)

If you get:
```
HTTP 404: workflow pr-copilot-monitor.yml not found
```

**Solution**:
1. Wait 30-60 seconds for GitHub to index the workflow
2. Verify file exists: `ls .github/workflows/pr-copilot-monitor.yml`
3. Check workflow list: `gh workflow list`
4. Ensure you're in the correct repository

### Workflow Failing

Check:
1. **Permissions**: Ensure workflow has `pull-requests: write` permission
2. **GitHub Token**: Verify `GITHUB_TOKEN` has necessary scopes
3. **PR Access**: Ensure PRs are accessible (not from forks with restrictions)

### Copilot Not Responding

If @copilot doesn't respond:
1. Verify Copilot is enabled for the repository
2. Check PR comments to ensure @copilot was mentioned
3. Try force reassignment: `gh workflow run pr-copilot-monitor.yml -f force_reassign=true`

## Advanced Usage

### Check Workflow Status

```bash
# List all workflows
gh workflow list

# View workflow runs
gh workflow view pr-copilot-monitor.yml

# Check latest run
gh run list --workflow=pr-copilot-monitor.yml --limit 1
```

### View Workflow Logs

```bash
# Get latest run ID
RUN_ID=$(gh run list --workflow=pr-copilot-monitor.yml --limit 1 --json databaseId --jq '.[0].databaseId')

# View logs
gh run view $RUN_ID --log
```

### Disable Automatic Execution

Edit `.github/workflows/pr-copilot-monitor.yml` and comment out the schedule:

```yaml
on:
  # schedule:
  #   - cron: '*/5 * * * *'
  workflow_dispatch:
    # ...
```

## Examples

### Example 1: Weekly PR Cleanup

```bash
# Check all PRs, force reassign if needed
gh workflow run pr-copilot-monitor.yml -f force_reassign=true
```

### Example 2: Dry Run Before Big Changes

```bash
# Test what would happen without making changes
gh workflow run pr-copilot-monitor.yml -f dry_run=true
```

### Example 3: Focus on Specific PR

```bash
# Work on specific PR only
gh workflow run pr-copilot-monitor.yml -f pr_number=123
```

## Integration

This workflow integrates with:
- **copilot-agent-autofix.yml** - Auto-healing system
- **pr-copilot-reviewer.yml** - PR review automation
- **pr-completion-monitor.yml** - Completion tracking
- **issue-to-draft-pr.yml** - Issue to PR conversion

## Notes

- The workflow uses `ubuntu-latest` runner (GitHub-hosted)
- Python 3.11 is used for PR analysis scripts
- GitHub CLI (`gh`) is used for API interactions
- Workflow outputs are saved for monitoring and debugging

## Support

For issues or questions:
1. Check workflow logs: `gh run view --log`
2. Review PR comments for @copilot responses
3. See `.github/workflows/README.md` for general workflow documentation
