# Copilot Auto-Fix All Pull Requests

## Overview

The `copilot_auto_fix_all_prs.py` script is a comprehensive solution for automatically invoking GitHub Copilot coding agent on open pull requests to fix them. This script combines functionality from multiple existing tools into a unified, easy-to-use interface.

## Features

- **Automatic PR Discovery**: Finds all open pull requests in the repository
- **Intelligent Analysis**: Analyzes each PR to determine the appropriate fix strategy
- **Copilot Integration**: Invokes GitHub Copilot with tailored instructions based on PR type
- **Progress Tracking**: Provides detailed progress reporting and statistics
- **Dry-Run Mode**: Preview actions without making changes
- **Flexible Targeting**: Process all PRs or specific PR numbers
- **Error Handling**: Robust error handling with detailed error reporting

## Prerequisites

Before using this script, ensure you have:

1. **GitHub CLI (gh)** installed and authenticated
   ```bash
   # Install GitHub CLI (if not already installed)
   # macOS
   brew install gh
   
   # Linux
   curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
   sudo apt update
   sudo apt install gh
   
   # Authenticate
   gh auth login
   ```

2. **GitHub Copilot CLI Extension** installed
   ```bash
   gh extension install github/gh-copilot
   ```

3. **GitHub Token** set in environment
   ```bash
   export GITHUB_TOKEN="your_github_token"
   # or
   export GH_TOKEN="your_github_token"
   ```

4. **GitHub Copilot Subscription** (required for Copilot features)

## Installation

The script is part of the `ipfs_datasets_py` package and located in the `scripts/` directory:

```bash
cd /path/to/ipfs_datasets_py
chmod +x scripts/copilot_auto_fix_all_prs.py
```

## Usage

### Basic Usage

Fix all open PRs:
```bash
python scripts/copilot_auto_fix_all_prs.py
```

### Dry Run Mode

Preview what would be done without making changes:
```bash
python scripts/copilot_auto_fix_all_prs.py --dry-run
```

### Fix Specific PR

Fix a single PR:
```bash
python scripts/copilot_auto_fix_all_prs.py --pr 123
```

Fix multiple specific PRs:
```bash
python scripts/copilot_auto_fix_all_prs.py --pr 123 --pr 456 --pr 789
```

### Limit Number of PRs

Process only the first N PRs:
```bash
python scripts/copilot_auto_fix_all_prs.py --limit 10
```

### With Custom Token

Use a specific GitHub token:
```bash
python scripts/copilot_auto_fix_all_prs.py --token "ghp_your_token_here"
```

### Verbose Mode

Enable verbose logging:
```bash
python scripts/copilot_auto_fix_all_prs.py --verbose
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--pr NUMBER` | Specific PR number to process (can be used multiple times) | Process all |
| `--limit N` | Maximum number of PRs to process | 100 |
| `--dry-run` | Show what would be done without making changes | False |
| `--token TOKEN` | GitHub token for authentication | From environment |
| `--verbose`, `-v` | Enable verbose logging | False |
| `--help`, `-h` | Show help message | - |

## How It Works

### 1. PR Discovery

The script uses GitHub CLI to fetch all open pull requests:
```bash
gh pr list --state open --limit <limit> --json <fields>
```

### 2. PR Analysis

Each PR is analyzed to determine:
- **Fix Type**: auto-fix, workflow, permissions, syntax, test, draft, bugfix, or review
- **Priority**: critical, high, medium, normal, or low
- **Reasons**: Why the PR needs fixing

Analysis considers:
- PR title keywords (auto-fix, workflow, permission, syntax, test, bug, etc.)
- PR body content
- Draft status
- File changes (e.g., workflow files)
- Existing comments

### 3. Instruction Generation

Based on the analysis, the script creates tailored Copilot instructions:

- **Auto-fix PRs**: Focus on implementing workflow fixes
- **Workflow PRs**: Fix GitHub Actions configurations
- **Permission PRs**: Resolve permission issues
- **Syntax PRs**: Fix compilation/syntax errors
- **Test PRs**: Fix failing tests
- **Draft PRs**: Implement proposed changes
- **Bug PRs**: Implement bug fixes
- **Review PRs**: General code review

### 4. Copilot Invocation

The script posts a comment on the PR mentioning `@copilot` with the generated instructions:

```markdown
@copilot Please implement the auto-fix described in this PR.

**Context**: This PR was automatically created by the auto-healing workflow...

**Task**:
1. Review the PR description and understand the failure
2. Analyze any error logs or stack traces mentioned
3. Implement the fix with minimal, surgical changes
...
```

### 5. Progress Reporting

The script provides detailed progress reporting:
```
🔨 Processing PR #123
════════════════════════════════════════
📄 Title: Fix workflow permission error
📊 Status: open
👤 Author: testuser
🔗 URL: https://github.com/...
🎯 Fix Type: workflow
⚡ Priority: high
📝 Reasons: Workflow/CI fix
✅ Successfully invoked Copilot on PR #123
```

Final summary:
```
📊 Execution Summary
════════════════════════════════════════
Total PRs found:          10
PRs processed:            10
Successfully invoked:     7
Already had Copilot:      2
Skipped:                  1
Failed:                   0
```

## PR Fix Types

The script recognizes the following PR types:

### Auto-Fix (Critical Priority)
- Title contains: "auto-fix", "autofix", "auto fix"
- Typically auto-generated by CI/CD workflows
- Focuses on implementing automated fixes

### Workflow (High Priority)
- Title/files contain: "workflow", "ci", "github actions"
- Fixes GitHub Actions workflow configurations
- Ensures proper workflow syntax and permissions

### Permissions (High Priority)
- Title/body contains: "permission", "denied", "unauthorized"
- Resolves permission errors in workflows or code
- Updates permission configurations

### Syntax (High Priority)
- Title/body contains: "syntax", "compile", "build", "error"
- Fixes syntax and compilation errors
- Ensures code compiles successfully

### Test (Medium Priority)
- Title contains: "test", "failing", "failure"
- Fixes failing tests or test infrastructure
- Maintains test coverage

### Draft (Normal Priority)
- PR is marked as draft
- Needs implementation of proposed changes
- Prepares PR for review

### Bug Fix (Medium Priority)
- Title contains: "bug", "fix", "issue"
- Implements bug fixes
- Adds regression tests

### Review (Low Priority)
- General PRs needing review
- Code quality improvements
- Documentation updates

## Examples

### Example 1: Fix All Auto-Generated PRs

```bash
# Dry run to see what would be done
python scripts/copilot_auto_fix_all_prs.py --dry-run

# Actually invoke Copilot
python scripts/copilot_auto_fix_all_prs.py
```

Output:
```
🚀 Starting Copilot Auto-Fix for Pull Requests
════════════════════════════════════════
🔍 Fetching open pull requests (limit: 100)...
✅ Found 3 open PRs

[1/3] Processing PR #246...
════════════════════════════════════════
📄 Title: Auto-fix: workflow permission error
📊 Status: open (Draft)
👤 Author: github-actions[bot]
🔗 URL: https://github.com/endomorphosis/ipfs_datasets_py/pull/246
🎯 Fix Type: auto-fix
⚡ Priority: critical
📝 Reasons: Auto-generated fix PR, Workflow/CI fix
📤 Posting Copilot instructions...
✅ Successfully invoked Copilot on PR #246
```

### Example 2: Fix Specific PRs

```bash
python scripts/copilot_auto_fix_all_prs.py --pr 246 --pr 247 --pr 248
```

### Example 3: Process First 5 PRs Only

```bash
python scripts/copilot_auto_fix_all_prs.py --limit 5 --verbose
```

## Integration with Existing Tools

This script unifies functionality from several existing tools:

1. **`ipfs_datasets_py/utils/copilot_cli.py`**: Core Copilot CLI utilities
2. **`scripts/invoke_copilot_coding_agent_on_prs.py`**: PR invocation logic
3. **`scripts/copilot_cli_pr_worker.py`**: PR worker functionality
4. **`scripts/copilot_pr_manager.py`**: PR management interface
5. **`scripts/batch_assign_copilot_to_prs.py`**: Batch processing

## Troubleshooting

### "GitHub CLI (gh) not found"
```bash
# Install GitHub CLI
# See: https://cli.github.com/
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

### "Failed to fetch PRs: rate limit"
Wait for rate limit to reset or use a different token with higher limits.

### "Copilot already invoked on PR"
The script automatically skips PRs that already have Copilot invoked. This is expected behavior.

## Advanced Usage

### Environment Variables

- `GITHUB_TOKEN` or `GH_TOKEN`: GitHub authentication token
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

### Exit Codes

- `0`: Success (all PRs processed successfully)
- `1`: Failure (one or more PRs failed)
- `130`: Interrupted by user (Ctrl+C)

### Programmatic Usage

You can also use the script programmatically:

```python
from scripts.copilot_auto_fix_all_prs import CopilotAutoFixAllPRs

# Create instance
auto_fixer = CopilotAutoFixAllPRs(dry_run=False, github_token="your_token")

# Process all PRs
auto_fixer.process_all_prs(limit=10)

# Process specific PRs
auto_fixer.process_all_prs(pr_numbers=[123, 456])

# Get statistics
print(auto_fixer.stats)
```

## Testing

Run the test suite:

```bash
# Run all tests
pytest tests/test_copilot_auto_fix_all_prs.py -v

# Run specific test
pytest tests/test_copilot_auto_fix_all_prs.py::TestCopilotAutoFixAllPRs::test_analyze_pr_auto_fix -v

# Run with coverage
pytest tests/test_copilot_auto_fix_all_prs.py --cov=scripts.copilot_auto_fix_all_prs --cov-report=html
```

## Contributing

When contributing to this script:

1. Follow the existing code style
2. Add tests for new functionality
3. Update documentation
4. Ensure all tests pass
5. Test in dry-run mode first

## License

This script is part of the `ipfs_datasets_py` project and follows the same license.

## Related Documentation

- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)
- [GitHub Copilot Coding Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [GitHub Copilot CLI Extension](https://github.com/github/gh-copilot)

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review existing GitHub issues
3. Create a new issue with details about your problem
4. Include relevant log output and environment information
