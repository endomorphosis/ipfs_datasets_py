# GitHub Copilot Invocation Method Update

## Overview
This document describes the update to properly invoke GitHub Copilot Coding Agents using `gh agent-task create` instead of `@copilot` mentions in PR comments.

## Problem Statement
The PR Copilot Monitor workflow was incorrectly invoking GitHub Copilot by posting `@copilot` mentions in pull request comments. While this method sometimes works, it is not the recommended or most reliable approach for programmatically invoking the Copilot Coding Agent.

## Solution
Updated the system to use the official GitHub CLI `agent-task` command:

```bash
gh agent-task create "task description" --base branch-name
```

## What Changed

### 1. CopilotCLI Utility Enhancement
**File**: `ipfs_datasets_py/utils/copilot_cli.py`

Added three new methods:
- `create_agent_task()` - Create a new Copilot Coding Agent task
- `list_agent_tasks()` - List active agent tasks
- `view_agent_task()` - View details of a specific task

Example usage:
```python
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

copilot = CopilotCLI()
result = copilot.create_agent_task(
    task_description="Fix failing tests in test_utils.py",
    base_branch="feature-branch"
)
```

### 2. Throttled Invoker Script
**File**: `scripts/invoke_copilot_with_throttling.py`

Updated `invoke_copilot_on_pr()` method to:
1. **Primary Method**: Use `gh agent-task create` with comprehensive task descriptions
2. **Fallback Method**: Use `@copilot` mentions only if agent-task unavailable
3. Extract PR context (body, description, etc.) for better task descriptions
4. Handle authentication properly with GH_TOKEN

### 3. Batch Assignment Script
**File**: `scripts/batch_assign_copilot_to_prs.py`

Updated to:
1. Check for existing agent tasks before creating new ones
2. Use `gh agent-task create` as primary method
3. Provide context-aware task descriptions based on PR analysis
4. Fallback to `@copilot` mentions if needed

### 4. Workflow Documentation
**File**: `.github/workflows/pr-copilot-monitor.yml`

Updated comments and documentation to:
- Explain proper `gh agent-task` usage
- Remove outdated PAT requirements (GITHUB_TOKEN works fine)
- Add links to official documentation
- Clarify authentication on self-hosted vs. GitHub-hosted runners

## Usage

### For Self-Hosted Runners
Self-hosted runners should already be authenticated with `gh auth login`. The workflow will automatically use this authentication.

### For GitHub-Hosted Runners
The workflow uses `GITHUB_TOKEN` automatically. No additional setup required.

### Manual Invocation
You can also manually create agent tasks:

```bash
# Create an agent task for a specific PR
gh agent-task create "Fix the failing tests in PR #123" --base feature-branch

# List active agent tasks
gh agent-task list

# View a specific task
gh agent-task view <session-id>
```

## Benefits

1. **More Reliable**: Direct API calls via `gh agent-task` are more reliable than @mentions
2. **Better Context**: Can provide comprehensive task descriptions with PR details
3. **Proper Throttling**: Can check active tasks and avoid overwhelming the system
4. **Standards-Compliant**: Uses official GitHub CLI commands as intended
5. **Self-Hosted Ready**: Works seamlessly on self-hosted runners with gh auth

## Testing

### Automated Tests
- `tests/test_invoke_copilot_with_throttling.py` - Tests throttling script (9/9 passing)
- `tests/test_copilot_agent_task.py` - Tests agent-task functionality (7/7 passing)

### Manual Testing
```bash
# Test in dry-run mode
python scripts/invoke_copilot_with_throttling.py --dry-run --batch-size 1

# Test with a specific PR
python scripts/invoke_copilot_with_throttling.py --pr 123 --dry-run
```

## Documentation References

- [GitHub CLI agent-task manual](https://cli.github.com/manual/gh_agent-task)
- [About Copilot Coding Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- [Using Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)
- [Copilot CLI concepts](https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli)
- [Agent Management](https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management)

## Migration Notes

### For Developers
No changes needed to existing workflows or processes. The scripts handle both methods automatically with intelligent fallback.

### For CI/CD
Workflows will automatically use the new method. No configuration changes required.

## Troubleshooting

### "command requires an OAuth token"
This usually means `gh` is not authenticated. Run:
```bash
gh auth login
```

### "unknown command 'agent-task'"
Your GitHub CLI version might be outdated. Update with:
```bash
gh extension upgrade gh-copilot
# or
gh upgrade
```

### Script Falls Back to @copilot
This is expected behavior if `gh agent-task` is not available. The fallback ensures the system continues to work even in environments where the latest CLI tools aren't available.

## Future Improvements

1. Add monitoring for agent task completion
2. Implement retry logic for failed tasks
3. Add metrics collection for task success rates
4. Integrate with notification systems for task updates
