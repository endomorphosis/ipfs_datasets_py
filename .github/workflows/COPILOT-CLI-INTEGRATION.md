# GitHub Copilot CLI Integration in Workflows

## Overview

This document describes how GitHub Actions workflows in this repository invoke GitHub Copilot to automatically implement fixes for workflow failures.

## Background

Previously, workflows used `@copilot` mentions in PR comments, which relied on manual GitHub UI interaction. This has been updated to use a programmatic approach via the `invoke_copilot_on_pr.py` script that uses GitHub CLI to properly trigger the Copilot coding agent.

## How It Works

### The Tool: `scripts/invoke_copilot_on_pr.py`

This Python script provides a programmatic interface to invoke GitHub Copilot on pull requests. It:

1. **Uses GitHub CLI** (`gh`) to interact with GitHub's API
2. **Posts properly formatted comments** that trigger the Copilot coding agent
3. **Includes specific instructions** for what Copilot should do
4. **Supports both individual and batch PR processing**

### Key Features

- **Slash Command Support**: Uses `@github-copilot /fix` format which is the recommended way to invoke Copilot
- **Custom Instructions**: Allows specifying detailed instructions for what Copilot should implement
- **Dry Run Mode**: Preview what would be done without making actual changes
- **Batch Processing**: Can invoke Copilot on multiple PRs at once
- **Label-Based Discovery**: Can find PRs that need Copilot based on labels

## Usage in Workflows

### Basic Invocation

```yaml
- name: Invoke GitHub Copilot on PR
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    python3 scripts/invoke_copilot_on_pr.py \
      --pr "$PR_NUMBER" \
      --repo "${{ github.repository }}"
```

### With Custom Instructions

```yaml
- name: Invoke Copilot with specific instructions
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    INSTRUCTION="Please fix the Docker permission errors by:
    1. Adding proper user permissions
    2. Updating the Dockerfile
    3. Testing the build"
    
    python3 scripts/invoke_copilot_on_pr.py \
      --pr "$PR_NUMBER" \
      --instruction "$INSTRUCTION"
```

### Batch Processing

```yaml
- name: Invoke Copilot on all ready PRs
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    python3 scripts/invoke_copilot_on_pr.py \
      --find-all \
      --label "copilot-ready"
```

## Workflows Using Copilot CLI

### 1. `copilot-agent-autofix.yml`

**Purpose**: Automatically creates issues and PRs for workflow failures, then invokes Copilot to implement fixes.

**How it invokes Copilot**:
```yaml
# Generate custom instruction from failure analysis
COPILOT_INSTRUCTION=$(python -c "
import json
with open('/tmp/failure_analysis.json') as f:
    data = json.load(f)
    recommendations = '\n'.join([f'- {rec}' for rec in data.get('recommendations', [])])
    print(f'''Please implement the fixes for the workflow failure. Focus on:

{recommendations}''')
")

# Invoke Copilot using the CLI tool
python3 scripts/invoke_copilot_on_pr.py \
  --pr "$PR_NUMBER" \
  --repo "${{ github.repository }}" \
  --instruction "$COPILOT_INSTRUCTION"
```

**What Copilot receives**:
- PR with workflow failure analysis
- Specific recommendations for fixing the issue
- Links to full logs and artifacts

### 2. `comprehensive-scraper-validation.yml`

**Purpose**: Validates scrapers and creates fix PRs when validation fails, then invokes Copilot.

**How it invokes Copilot**:
```yaml
python3 scripts/invoke_copilot_on_pr.py \
  --pr "$PR_NUMBER" \
  --instruction "Please analyze the scraper validation failures and implement fixes. Focus on:
1. Ensure all scrapers produce data with required fields: \`title\` and \`text\`
2. Fix schema validation issues
3. Ensure HuggingFace dataset compatibility
4. Improve data quality scores"
```

## Command-Line Usage

The script can also be used manually:

```bash
# Invoke Copilot on a specific PR
python3 scripts/invoke_copilot_on_pr.py --pr 123

# With custom instructions
python3 scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix the linting errors"

# Dry run (preview only)
python3 scripts/invoke_copilot_on_pr.py --pr 123 --dry-run

# Find and process all PRs with copilot-ready label
python3 scripts/invoke_copilot_on_pr.py --find-all --label copilot-ready

# Specify a different repository
python3 scripts/invoke_copilot_on_pr.py --pr 123 --repo owner/repo
```

## Technical Details

### Comment Format

The script posts comments in this format:

```
@github-copilot /fix

[Custom instructions here]
```

The `/fix` slash command is the recommended way to invoke Copilot as it:
- Clearly indicates the intent
- Is recognized by GitHub's Copilot system
- Triggers the coding agent with appropriate context

### Prerequisites

1. **GitHub CLI** (`gh`) must be installed and authenticated
2. **GITHUB_TOKEN** or **GH_TOKEN** environment variable must be set
3. **Python 3.6+** for running the script
4. **Appropriate permissions** (pull-requests: write)

### Authentication

The script uses the GitHub CLI's authentication, which should be configured with:

```bash
gh auth login
```

In workflows, authentication is handled via:

```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Benefits Over @mentions

### Old Approach (Manual @mentions)
- ❌ Required manual intervention
- ❌ Inconsistent formatting
- ❌ No programmatic control
- ❌ Hard to track and debug
- ❌ No dry-run capability

### New Approach (Copilot CLI Tool)
- ✅ Fully automated
- ✅ Consistent, structured comments
- ✅ Programmatic control and customization
- ✅ Easy to test and debug
- ✅ Supports dry-run mode
- ✅ Can be used in CI/CD pipelines
- ✅ Better error handling
- ✅ Audit trail via GitHub CLI

## Troubleshooting

### Copilot Not Responding

If Copilot doesn't respond to the invocation:

1. **Check PR state**: Copilot works best on draft PRs
2. **Verify permissions**: Ensure the workflow has pull-requests: write
3. **Check authentication**: Verify GH_TOKEN is set correctly
4. **Review comment**: Ensure the comment was posted (check PR on GitHub)
5. **Wait**: Copilot may take a few minutes to respond

### Script Errors

```bash
# Test the script with dry-run first
python3 scripts/invoke_copilot_on_pr.py --pr 123 --dry-run

# Check GitHub CLI authentication
gh auth status

# Verify PR exists and is accessible
gh pr view 123
```

### Workflow Integration Issues

If the script fails in a workflow:

1. Ensure `scripts/invoke_copilot_on_pr.py` is checked out
2. Verify Python 3 is available
3. Check that GH_TOKEN is set in env
4. Review workflow logs for specific error messages

## Migration Guide

For workflows still using `@copilot` mentions, follow this migration:

### Before (Old Approach)
```yaml
- name: Create PR and mention Copilot
  run: |
    gh pr comment "$PR_NUMBER" --body "@copilot /fix
    
    Please fix the issues described above."
```

### After (New Approach)
```yaml
- name: Invoke Copilot using CLI tool
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    python3 scripts/invoke_copilot_on_pr.py \
      --pr "$PR_NUMBER" \
      --instruction "Please fix the issues described above."
```

## Best Practices

1. **Be Specific**: Provide clear, actionable instructions
2. **Include Context**: Reference relevant issues, logs, or artifacts
3. **Use Dry Run**: Test with --dry-run before production use
4. **Monitor Results**: Check that Copilot actually responds
5. **Handle Errors**: Always check exit codes and handle failures
6. **Label PRs**: Use labels like "copilot-ready" for tracking
7. **Document Instructions**: Keep instructions clear and maintainable

## Future Enhancements

Potential improvements to consider:

- **Wait for Response**: Add option to wait for and verify Copilot's response
- **Retry Logic**: Automatically retry if Copilot doesn't respond
- **Status Reporting**: Report back to the issue when Copilot completes work
- **Templating**: Support instruction templates for common scenarios
- **Integration Testing**: Add tests for the invocation flow

## References

- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [Workflow Auto-Healing Guide](./AUTO_HEALING_GUIDE.md)
- [Repository COPILOT Instructions](../../COPILOT.md)

## Support

For issues or questions about Copilot CLI integration:

1. Check this documentation first
2. Review workflow logs for error messages
3. Test the script manually with --dry-run
4. Open an issue with relevant details
