# Using Copilot CLI to Auto-Fix All Pull Requests

## Quick Start Guide

This guide shows you how to use the `copilot_auto_fix_all_prs.py` script from the `ipfs_datasets_py` package to automatically invoke GitHub Copilot on all open pull requests.

## What This Does

The script:
1. 🔍 Finds all open pull requests in your repository
2. 🤖 Analyzes each PR to understand what needs fixing
3. 📝 Creates tailored instructions for GitHub Copilot
4. 🚀 Invokes Copilot agent on each PR with appropriate instructions
5. 📊 Provides detailed progress tracking and reporting

## Prerequisites

Before running, ensure you have:

```bash
# 1. GitHub CLI installed
gh --version

# 2. GitHub Copilot CLI extension installed
gh extension list | grep copilot

# 3. GitHub token set
echo $GITHUB_TOKEN  # or $GH_TOKEN

# If not installed:
gh extension install github/gh-copilot
```

## Usage

### 1. Basic Usage - Fix All Open PRs

```bash
# Navigate to the repository
cd /path/to/ipfs_datasets_py

# Run the script
python scripts/copilot_auto_fix_all_prs.py
```

### 2. Dry Run Mode (Recommended First Time)

Preview what would be done without making changes:

```bash
python scripts/copilot_auto_fix_all_prs.py --dry-run
```

This will show:
- Which PRs would be processed
- What type of fix each needs
- The exact instructions that would be sent to Copilot

### 3. Fix Specific Pull Requests

Fix one or more specific PRs:

```bash
# Single PR
python scripts/copilot_auto_fix_all_prs.py --pr 246

# Multiple PRs
python scripts/copilot_auto_fix_all_prs.py --pr 246 --pr 247 --pr 248
```

### 4. Limit Number of PRs

Process only the first N PRs:

```bash
python scripts/copilot_auto_fix_all_prs.py --limit 5
```

### 5. With Custom GitHub Token

Use a specific token:

```bash
python scripts/copilot_auto_fix_all_prs.py --token "ghp_your_token_here"
```

### 6. Verbose Mode

Get detailed logging:

```bash
python scripts/copilot_auto_fix_all_prs.py --verbose
```

## Example Workflow

### Step 1: Check Current PRs

```bash
# See what PRs are open
gh pr list --state open

# Example output:
# #246  Auto-fix: workflow permission error    DRAFT
# #247  Fix workflow syntax error              OPEN
# #248  Fix permission denied error            DRAFT
```

### Step 2: Dry Run

```bash
# Preview what would be done
python scripts/copilot_auto_fix_all_prs.py --dry-run
```

Example output:
```
🚀 Starting Copilot Auto-Fix for Pull Requests
════════════════════════════════════════════════════════════════════════════════
🔍 DRY RUN MODE - No actual changes will be made

🔍 Fetching open pull requests (limit: 100)...
✅ Found 3 open PRs

[1/3] Processing PR #246...
════════════════════════════════════════════════════════════════════════════════
📄 Title: Auto-fix: workflow permission error
📊 Status: open (Draft)
👤 Author: github-actions[bot]
🔗 URL: https://github.com/endomorphosis/ipfs_datasets_py/pull/246
🎯 Fix Type: auto-fix
⚡ Priority: critical
📝 Reasons: Auto-generated fix PR, Workflow/CI fix

────────────────────────────────────────────────────────────────────────────────
🔍 DRY RUN - Would post this comment:
────────────────────────────────────────────────────────────────────────────────
@copilot Please implement the auto-fix described in this PR.

**Context**: This PR was automatically created by the auto-healing workflow...

**Task**:
1. Review the PR description and understand the failure
2. Analyze any error logs or stack traces mentioned
3. Implement the fix with minimal, surgical changes
4. Follow the repository's coding patterns and best practices
5. Ensure all tests pass after the fix
6. Commit the changes with a clear message

**Priority**: CRITICAL
**Reason**: Auto-generated fix PR, Workflow/CI fix

Please proceed with implementing this auto-fix.
────────────────────────────────────────────────────────────────────────────────
```

### Step 3: Run for Real

```bash
# Actually invoke Copilot on all PRs
python scripts/copilot_auto_fix_all_prs.py
```

### Step 4: Monitor Progress

The script will show progress for each PR:

```
[2/3] Processing PR #247...
════════════════════════════════════════════════════════════════════════════════
📄 Title: Fix workflow syntax error
📊 Status: open
👤 Author: developer
🔗 URL: https://github.com/endomorphosis/ipfs_datasets_py/pull/247
🎯 Fix Type: workflow
⚡ Priority: high
📝 Reasons: Workflow/CI fix
📤 Posting Copilot instructions...
✅ Successfully invoked Copilot on PR #247
🔗 View PR: https://github.com/endomorphosis/ipfs_datasets_py/pull/247
```

### Step 5: Review Results

```
════════════════════════════════════════════════════════════════════════════════
📊 Execution Summary
════════════════════════════════════════════════════════════════════════════════
Total PRs found:          3
PRs processed:            3
Successfully invoked:     3
Already had Copilot:      0
Skipped:                  0
Failed:                   0
════════════════════════════════════════════════════════════════════════════════

✨ Successfully invoked Copilot on 3 PR(s)!
```

## PR Fix Types

The script automatically detects and handles different PR types:

### 🔴 Critical Priority
- **Auto-fix**: Auto-generated workflow fixes (detects "auto-fix" in title)

### 🟠 High Priority
- **Workflow**: GitHub Actions configuration issues
- **Permissions**: Permission denied errors
- **Syntax**: Compilation or syntax errors

### 🟡 Medium Priority
- **Test**: Test failures
- **Bugfix**: General bug fixes

### 🟢 Normal Priority
- **Draft**: Draft PRs needing implementation

### 🔵 Low Priority
- **Review**: General code review

## Integration with Copilot CLI Tool

This script is part of the `ipfs_datasets_py` package and uses the Copilot CLI utility:

```python
# Location in package
ipfs_datasets_py/
  ├── utils/
  │   └── copilot_cli.py          # Core Copilot CLI utility
  └── scripts/
      └── copilot_auto_fix_all_prs.py  # This script
```

You can also use the Copilot CLI utility directly:

```python
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

# Create instance
copilot = CopilotCLI()

# Install Copilot CLI extension
copilot.install()

# Get code explanations
result = copilot.explain_code("def hello(): print('world')")

# Get command suggestions
result = copilot.suggest_command("list all files in current directory")
```

## Programmatic Usage

You can also use the auto-fixer programmatically:

```python
from scripts.copilot_auto_fix_all_prs import CopilotAutoFixAllPRs

# Create instance
auto_fixer = CopilotAutoFixAllPRs(
    dry_run=False,
    github_token="your_token"
)

# Process all PRs
auto_fixer.process_all_prs(limit=10)

# Process specific PRs
auto_fixer.process_all_prs(pr_numbers=[246, 247])

# Check statistics
print(auto_fixer.stats)
```

## Troubleshooting

### "GitHub CLI (gh) not found"

```bash
# Install GitHub CLI
# macOS
brew install gh

# Linux
sudo apt install gh

# Windows
choco install gh
```

### "GitHub Copilot CLI extension not found"

```bash
gh extension install github/gh-copilot
```

### "GitHub CLI not authenticated"

```bash
gh auth login
```

### "No GitHub token found"

```bash
export GITHUB_TOKEN="your_token"
# or
export GH_TOKEN="your_token"
```

### "Copilot already invoked on PR"

This is expected behavior. The script skips PRs that already have Copilot assigned.

## Advanced Options

### All Command-Line Options

```bash
python scripts/copilot_auto_fix_all_prs.py --help
```

| Option | Description | Default |
|--------|-------------|---------|
| `--pr NUMBER` | Process specific PR (repeatable) | All PRs |
| `--limit N` | Max PRs to process | 100 |
| `--dry-run` | Preview without changes | False |
| `--token TOKEN` | Custom GitHub token | From env |
| `--verbose, -v` | Verbose logging | False |

### Environment Variables

- `GITHUB_TOKEN` or `GH_TOKEN`: Authentication token
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

### Exit Codes

- `0`: Success
- `1`: Failure (one or more PRs failed)
- `130`: Interrupted (Ctrl+C)

## Examples

### Example 1: Weekly PR Cleanup

```bash
#!/bin/bash
# weekly_pr_cleanup.sh

# Run in dry-run mode first to preview
python scripts/copilot_auto_fix_all_prs.py --dry-run --limit 10

# If dry-run looks good, run for real
read -p "Proceed with actual fix? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python scripts/copilot_auto_fix_all_prs.py --limit 10
fi
```

### Example 2: Fix Critical PRs Only

```bash
# Get all auto-fix PRs
AUTO_FIX_PRS=$(gh pr list --state open --json number,title | \
               jq -r '.[] | select(.title | contains("auto-fix")) | .number')

# Fix each one
for pr in $AUTO_FIX_PRS; do
    python scripts/copilot_auto_fix_all_prs.py --pr $pr
done
```

### Example 3: Scheduled Cron Job

```bash
# Add to crontab
# 0 */6 * * * cd /path/to/repo && python scripts/copilot_auto_fix_all_prs.py --limit 5
```

## Testing

Run the test suite:

```bash
# Run all tests
pytest tests/test_copilot_auto_fix_all_prs.py -v

# Run specific test
pytest tests/test_copilot_auto_fix_all_prs.py::test_script_help_output

# With coverage
pytest tests/test_copilot_auto_fix_all_prs.py --cov --cov-report=html
```

Run the example:

```bash
python examples/copilot_auto_fix_example.py
```

## More Information

- Full Documentation: [docs/copilot_auto_fix_all_prs.md](docs/copilot_auto_fix_all_prs.md)
- Implementation Summary: [COPILOT_AUTO_FIX_IMPLEMENTATION.md](COPILOT_AUTO_FIX_IMPLEMENTATION.md)
- Example Code: [examples/copilot_auto_fix_example.py](examples/copilot_auto_fix_example.py)
- Test Suite: [tests/test_copilot_auto_fix_all_prs.py](tests/test_copilot_auto_fix_all_prs.py)

## Support

For issues or questions:
1. Check the [troubleshooting section](#troubleshooting)
2. Review the [full documentation](docs/copilot_auto_fix_all_prs.md)
3. Check [existing issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
4. Create a new issue with:
   - Command you ran
   - Error message
   - Environment details (`gh --version`, Python version)

---

**Quick Reference Card**

```bash
# Must-knows
python scripts/copilot_auto_fix_all_prs.py --dry-run   # Preview first!
python scripts/copilot_auto_fix_all_prs.py             # Fix all PRs
python scripts/copilot_auto_fix_all_prs.py --pr 123    # Fix one PR
python scripts/copilot_auto_fix_all_prs.py --help      # Show help
```
