# Automated PR Review System with GitHub Copilot Agents

## Overview

The Automated PR Review System intelligently examines all open pull requests in your repository and automatically decides whether to invoke GitHub Copilot coding agents to work on them using the **`gh agent-task create`** command. This system provides a sophisticated multi-criteria analysis to determine which PRs would benefit most from Copilot's assistance.

## Features

- **🤖 Intelligent PR Analysis**: Uses 12+ criteria to evaluate PRs
- **📊 Confidence Scoring**: Assigns confidence scores (0-100) for decision-making
- **🎯 Task Type Detection**: Automatically identifies the type of work needed (fix, workflow, review, etc.)
- **🚀 Proper Agent Invocation**: Uses `gh agent-task create` to actually start Copilot agents
- **🔍 Dry-Run Mode**: Test the system without actually invoking Copilot
- **⚙️ Configurable Thresholds**: Customize minimum confidence levels
- **📈 Detailed Statistics**: Get comprehensive reports on PR reviews
- **🔧 CLI & MCP Integration**: Access via command-line or MCP tools

## Based On

- [Welcome Home, Agents (GitHub Blog)](https://github.blog/news-insights/company-news/welcome-home-agents/)
- [GitHub Copilot Coding Agent Documentation](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- [GitHub Copilot Code Review](https://docs.github.com/en/copilot/concepts/agents/code-review)

## How It Works

The system uses the **GitHub CLI (`gh`) agent-task commands** to properly invoke Copilot agents:

1. **Analyze PR**: Evaluates PR using 12+ weighted criteria
2. **Generate Task Description**: Creates detailed, task-specific instructions
3. **Checkout PR**: Switches to the PR branch
4. **Create Agent Task**: Runs `gh agent-task create` with the task description
5. **Monitor**: Agent task ID is returned for tracking

This is the **correct way** to invoke GitHub Copilot agents, not just posting `@copilot` comments.

## Decision Criteria

The system evaluates PRs using the following criteria:

### Positive Indicators (Increase Confidence)

| Criterion | Weight | Description |
|-----------|--------|-------------|
| `is_draft` | 30 | PR is marked as draft |
| `has_auto_fix_label` | 40 | Has auto-fix or autohealing labels |
| `autohealing_pr` | 50 | From autohealing/auto-fix branch |
| `workflow_failure` | 45 | Workflow-related PR or files |
| `permission_issue` | 40 | Permission-related keywords |
| `recent_activity` | 10 | Updated within 2 days |
| `has_description` | 15 | Has meaningful description (>100 chars) |
| `file_count_reasonable` | 10 | Between 1-50 files changed |
| `no_conflicts` | 15 | No merge conflicts |
| `has_linked_issue` | 20 | References issues or fixes |

### Negative Indicators (Decrease Confidence)

| Criterion | Weight | Description |
|-----------|--------|-------------|
| `has_wip_label` | -20 | Has WIP or "do-not-review" labels |
| `has_do_not_merge_label` | -100 | Has "do-not-merge" or "hold" labels (blocks completely) |

### Confidence Score Calculation

1. Sum all applicable criteria weights
2. Normalize to 0-100 scale
3. Block if "do-not-merge" label present (confidence = 0)
4. Invoke Copilot if confidence ≥ minimum threshold (default: 60%)

## Task Type Detection

The system automatically determines the most appropriate task type:

- **`implement_fix`**: Auto-fix labels, autohealing branches
- **`fix_workflow`**: Workflow files or workflow keywords in title
- **`fix_permissions`**: Permission-related keywords
- **`implement_draft`**: Draft PRs needing implementation
- **`review`**: General code review (default)

## Usage

### Command Line Interface

#### Basic Usage

```bash
# Dry run to see what would be done
python scripts/automated_pr_review.py --dry-run

# Actually invoke Copilot on qualifying PRs
python scripts/automated_pr_review.py

# Custom minimum confidence threshold
python scripts/automated_pr_review.py --min-confidence 70

# Analyze specific PR
python scripts/automated_pr_review.py --pr 123 --dry-run

# Verbose output
python scripts/automated_pr_review.py --dry-run --verbose
```

#### Options

- `--pr PR`: Analyze/invoke Copilot on specific PR number
- `--dry-run`: Show what would be done without actually invoking Copilot
- `--min-confidence N`: Minimum confidence score (0-100) to invoke Copilot (default: 60)
- `--limit N`: Maximum number of PRs to process (default: 100)
- `--verbose`: Enable verbose logging

### MCP Tools

The system is also available as MCP tools for AI assistant integration:

#### AutomatedPRReviewTool

Automatically review all open PRs:

```python
{
    "tool": "automated_pr_review",
    "parameters": {
        "dry_run": false,
        "min_confidence": 60,
        "limit": 100
    }
}
```

#### AnalyzePRTool

Analyze a specific PR without invoking Copilot:

```python
{
    "tool": "analyze_pr",
    "parameters": {
        "pr_number": 123,
        "min_confidence": 60
    }
}
```

#### InvokeCopilotOnPRTool

Invoke Copilot on a specific PR:

```python
{
    "tool": "invoke_copilot_on_pr",
    "parameters": {
        "pr_number": 123,
        "force": false,
        "dry_run": false
    }
}
```

## Example Output

### Dry-Run Mode

```
2025-10-31 18:00:00 - automated_pr_review - INFO - ✅ GitHub CLI verified
2025-10-31 18:00:00 - automated_pr_review - INFO - 🔍 DRY RUN MODE - No actual changes will be made

2025-10-31 18:00:00 - automated_pr_review - INFO - 🔍 Fetching open pull requests...
2025-10-31 18:00:00 - automated_pr_review - INFO - 📊 Found 5 open PRs

2025-10-31 18:00:00 - automated_pr_review - INFO - 
================================================================================
2025-10-31 18:00:00 - automated_pr_review - INFO - 📋 Analyzing PR #123
2025-10-31 18:00:00 - automated_pr_review - INFO - ================================================================================
2025-10-31 18:00:00 - automated_pr_review - INFO - 📄 Title: Fix workflow permissions issue
2025-10-31 18:00:00 - automated_pr_review - INFO - 📊 Draft: False
2025-10-31 18:00:00 - automated_pr_review - INFO - 👤 Author: autohealing-bot
2025-10-31 18:00:00 - automated_pr_review - INFO - 🎯 Task Type: fix_permissions
2025-10-31 18:00:00 - automated_pr_review - INFO - 📊 Confidence: 85%
2025-10-31 18:00:00 - automated_pr_review - INFO - 📝 Reasons: Auto-fix label, Autohealing branch, Permission issue, Workflow fix needed
2025-10-31 18:00:00 - automated_pr_review - INFO - 📈 Criteria Scores: {'has_auto_fix_label': 40, 'autohealing_pr': 50, 'permission_issue': 40, 'workflow_failure': 45}

2025-10-31 18:00:00 - automated_pr_review - INFO - 
────────────────────────────────────────────────────────────────────────────────
2025-10-31 18:00:00 - automated_pr_review - INFO - 🔍 DRY RUN - Would post comment:
2025-10-31 18:00:00 - automated_pr_review - INFO - ────────────────────────────────────────────────────────────────────────────────
2025-10-31 18:00:00 - automated_pr_review - INFO - @copilot Please resolve the permission issues in this PR.

**Context**: This PR addresses permission-related errors.

**Task**:
1. Identify the specific permission errors
2. Review required permissions for the failing operations
3. Update permissions configuration appropriately
4. Ensure security best practices are maintained
5. Document any permission changes made

**Confidence**: 85%
**Analysis**: Auto-fix label, Autohealing branch, Permission issue, Workflow fix needed

Please fix the permission issues.
2025-10-31 18:00:00 - automated_pr_review - INFO - ────────────────────────────────────────────────────────────────────────────────

2025-10-31 18:00:00 - automated_pr_review - INFO - 
================================================================================
2025-10-31 18:00:00 - automated_pr_review - INFO - 📊 SUMMARY
2025-10-31 18:00:00 - automated_pr_review - INFO - ================================================================================
2025-10-31 18:00:00 - automated_pr_review - INFO - Total PRs:              5
2025-10-31 18:00:00 - automated_pr_review - INFO - Analyzed:               5
2025-10-31 18:00:00 - automated_pr_review - INFO - Copilot Invoked:        0
2025-10-31 18:00:00 - automated_pr_review - INFO - Skipped:                3
2025-10-31 18:00:00 - automated_pr_review - INFO - Failed:                 0
2025-10-31 18:00:00 - automated_pr_review - INFO - ================================================================================
```

## Architecture

The system consists of three main components:

### 1. Core Script (`scripts/automated_pr_review.py`)

- **AutomatedPRReviewer class**: Main orchestrator
  - `analyze_pr()`: Analyzes individual PR
  - `invoke_copilot_on_pr()`: Invokes Copilot on specific PR
  - `review_all_prs()`: Processes all open PRs
  - `create_copilot_comment()`: Generates task-specific comments

### 2. MCP Tools (`ipfs_datasets_py/mcp_tools/tools/automated_pr_review_tools.py`)

- **AutomatedPRReviewTool**: Review all PRs
- **AnalyzePRTool**: Analyze specific PR
- **InvokeCopilotOnPRTool**: Invoke on specific PR

### 3. Test Suite (`tests/test_automated_pr_review.py`)

- 19 comprehensive tests covering:
  - Criteria evaluation
  - Task type detection
  - Confidence scoring
  - Comment generation
  - Edge cases

## Integration with Existing Tools

The automated PR review system builds upon and integrates with:

### Existing Scripts

- **`scripts/copilot_pr_manager.py`**: Interactive PR management
- **`scripts/invoke_copilot_coding_agent_on_prs.py`**: Manual PR invocation
- **`scripts/batch_assign_copilot_to_prs.py`**: Batch processing

### GitHub CLI Tools

- **`ipfs_datasets_py/utils/github_cli.py`**: GitHub CLI wrapper
- **`ipfs_datasets_py/mcp_tools/tools/github_cli_tools.py`**: MCP tools for GitHub CLI

### Copilot CLI Tools

- **`ipfs_datasets_py/utils/copilot_cli.py`**: Copilot CLI wrapper
- **`ipfs_datasets_py/mcp_tools/tools/copilot_cli_tools.py`**: MCP tools for Copilot CLI

## Configuration

### Environment Variables

The system respects GitHub CLI authentication configured via:

```bash
# Login to GitHub CLI
gh auth login

# Check authentication status
gh auth status
```

### Customization

You can customize the decision criteria by modifying `CRITERIA_WEIGHTS` in `AutomatedPRReviewer`:

```python
CRITERIA_WEIGHTS = {
    'is_draft': 30,
    'has_auto_fix_label': 40,
    'workflow_failure': 45,
    # Add or modify weights here
}
```

## Workflow Integration

### GitHub Actions

Add to your workflow for automated PR reviews:

```yaml
name: Automated PR Review

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:

jobs:
  review-prs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run automated PR review
        run: python scripts/automated_pr_review.py --min-confidence 70
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Manual Trigger

```bash
# Review all PRs
python scripts/automated_pr_review.py

# Review with custom confidence threshold
python scripts/automated_pr_review.py --min-confidence 75

# Analyze specific PR without invoking
python scripts/automated_pr_review.py --pr 456 --dry-run
```

## Security Considerations

1. **Authentication**: Uses GitHub CLI authentication (gh auth)
2. **Read-Only Analysis**: PR analysis is read-only
3. **Explicit Invocation**: Copilot invocation requires explicit action
4. **Dry-Run by Default**: Can be configured to require manual approval

## Troubleshooting

### GitHub CLI Not Found

```bash
# Install GitHub CLI
# On Ubuntu/Debian
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh

# Authenticate
gh auth login
```

### Copilot Extension Not Found

```bash
# Install Copilot CLI extension
gh extension install github/gh-copilot
```

### Permission Denied

Ensure GitHub CLI has proper authentication and repository access:

```bash
gh auth status
gh auth refresh -h github.com -s repo,workflow
```

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
pytest tests/test_automated_pr_review.py -v

# Run specific test
pytest tests/test_automated_pr_review.py::test_analyze_pr_auto_fix_label -v

# Run with coverage
pytest tests/test_automated_pr_review.py --cov=scripts.automated_pr_review --cov-report=html
```

## Contributing

When contributing to the automated PR review system:

1. Add tests for new criteria in `tests/test_automated_pr_review.py`
2. Update `CRITERIA_WEIGHTS` for new decision factors
3. Document new task types in this README
4. Test with `--dry-run` before deploying

## Future Enhancements

Planned improvements:

- [ ] Machine learning-based confidence scoring
- [ ] Historical success rate tracking
- [ ] Integration with PR templates
- [ ] Custom criteria via configuration file
- [ ] Support for GitHub Enterprise
- [ ] Multi-repository support
- [ ] Slack/Discord notifications
- [ ] Dashboard for statistics

## License

This component is part of the ipfs_datasets_py project and follows the same license.
