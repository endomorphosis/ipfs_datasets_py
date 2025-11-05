# GitHub Copilot Invocation Methods - Proper Usage Guide

## Overview

This repository uses the **OFFICIAL** GitHub Copilot invocation methods as documented by GitHub. This document explains the correct ways to invoke GitHub Copilot Coding Agent and why other methods don't work.

## ✅ Official Methods (USE THESE)

### 1. GitHub CLI: `gh agent-task create`

This is the official method for invoking GitHub Copilot Coding Agent.

**Command:**
```bash
gh agent-task create "Fix the failing tests in test_utils.py" --base main
```

**Python Script:**
```bash
python scripts/invoke_copilot_agent_task.py --pr 123 --description "Fix the failing tests"
```

**Documentation:**
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management

**Features:**
- Creates an actual agent task that Copilot will execute
- Agent analyzes the task and creates a plan
- Agent implements changes and pushes commits
- Provides task tracking and status updates

**Installation:**
```bash
gh extension install github/gh-copilot
gh extension upgrade gh-copilot
```

### 2. Python Wrapper: CopilotCLI Utility

The repository provides a Python wrapper for GitHub Copilot CLI functionality.

**Usage:**
```python
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

copilot = CopilotCLI()

# Create agent task
result = copilot.create_agent_task(
    task_description="Fix the failing tests in test_utils.py",
    base_branch="main"
)

# List agent tasks
result = copilot.list_agent_tasks(limit=30)

# View agent task
result = copilot.view_agent_task(task_identifier="123")
```

**Location:** `ipfs_datasets_py/utils/copilot_cli.py`

### 3. MCP Tools: Agent Task Tools

MCP (Model Context Protocol) tools for AI assistants to interact with GitHub Copilot.

**Available Tools:**
- `copilot_agent_task_create` - Create new agent tasks
- `copilot_agent_task_list` - List existing agent tasks
- `copilot_agent_task_view` - View agent task details

**Location:** `ipfs_datasets_py/mcp_tools/tools/copilot_agent_task_tools.py`

## ❌ Unsupported Methods (DON'T USE THESE)

### 1. Commenting @copilot on PRs

**Why it doesn't work:**
- GitHub Copilot does NOT respond to @copilot mentions in PR comments
- This is not an official invocation method
- It creates comments but no agent task is created
- No automated code changes will be made

**Example (WRONG):**
```bash
gh pr comment 123 --body "@copilot please fix this"  # ❌ Does NOT work
```

### 2. Creating Draft PRs with @copilot

**Why it doesn't work:**
- Draft PRs with @copilot mentions do not trigger the Coding Agent
- This method is not documented by GitHub
- No agent task is created
- Copilot will not automatically work on the PR

**Example (WRONG):**
```bash
# Creating a draft PR and hoping Copilot responds
gh pr create --draft --body "@copilot fix this"  # ❌ Does NOT work
```

## How to Fix Existing Workflows

### Before (Incorrect):

```yaml
- name: Assign Copilot
  run: |
    gh pr comment $PR_NUMBER --body "@copilot please fix this PR"
```

### After (Correct):

```yaml
- name: Create Copilot Agent Task
  run: |
    python scripts/invoke_copilot_agent_task.py \
      --pr $PR_NUMBER \
      --description "Fix the issues in this PR"
```

## Updated Files in This Repository

### Scripts:
1. **`scripts/invoke_copilot_agent_task.py`** - NEW
   - Official gh agent-task create method
   - Comprehensive error handling
   - Task creation, listing, and viewing

2. **`scripts/batch_assign_copilot_to_prs.py`** - UPDATED
   - Removed @copilot mention fallback
   - Uses gh agent-task list for checking assignments

### Workflows:
1. **`.github/workflows/pr-copilot-reviewer.yml`** - UPDATED
   - Changed from PR comment method to agent-task create
   - Uses proper CLI invocation
   - Updated verification steps

### Utilities:
1. **`ipfs_datasets_py/utils/copilot_cli.py`** - EXISTING
   - Full-featured Python wrapper
   - Supports agent-task commands
   - Includes caching and error handling

2. **`ipfs_datasets_py/mcp_tools/tools/copilot_agent_task_tools.py`** - NEW
   - MCP tool wrappers for agent-task functionality
   - Enables AI assistants to use proper methods

## Quick Start

### For Scripts:

```bash
# Create agent task for a PR
python scripts/invoke_copilot_agent_task.py --pr 123

# With custom description
python scripts/invoke_copilot_agent_task.py --pr 123 --description "Fix the failing tests"

# Follow agent execution
python scripts/invoke_copilot_agent_task.py --pr 123 --follow

# List recent agent tasks
python scripts/invoke_copilot_agent_task.py --list

# Dry run (test without making changes)
python scripts/invoke_copilot_agent_task.py --pr 123 --dry-run
```

### For GitHub CLI:

```bash
# Create agent task
gh agent-task create "Fix the failing tests" --base main

# List agent tasks
gh agent-task list --limit 30

# View agent task
gh agent-task view <task-id>
```

### For Python Code:

```python
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

copilot = CopilotCLI()
result = copilot.create_agent_task(
    task_description="Fix the failing tests in test_utils.py",
    base_branch="main",
    follow=False
)

if result["success"]:
    print(f"Agent task created: {result['stdout']}")
else:
    print(f"Failed: {result['error']}")
```

## Verification

To verify that the proper methods are being used:

1. **Check for gh-copilot extension:**
   ```bash
   gh extension list | grep gh-copilot
   ```

2. **Test agent-task command:**
   ```bash
   gh agent-task list --limit 5
   ```

3. **Test Python script:**
   ```bash
   python scripts/invoke_copilot_agent_task.py --help
   ```

## Troubleshooting

### Error: "unknown command: agent-task"

**Solution:** Install gh-copilot extension:
```bash
gh extension install github/gh-copilot
```

### Error: "GitHub CLI not authenticated"

**Solution:** Authenticate with GitHub:
```bash
gh auth login
```

Or in workflows, ensure GH_TOKEN is set:
```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Error: "CopilotCLI not available"

**Solution:** The script will fall back to direct gh commands. This is expected and not an error.

## Additional Resources

- [GitHub Copilot Coding Agent Documentation](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [GitHub Copilot CLI Documentation](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)

## Summary

**Use:**
- ✅ `gh agent-task create` (official GitHub CLI command)
- ✅ `scripts/invoke_copilot_agent_task.py` (Python wrapper)
- ✅ `CopilotCLI` utility (programmatic access)

**Don't use:**
- ❌ Commenting @copilot on PRs (not supported)
- ❌ Creating draft PRs with @copilot (not supported)

The official methods create actual agent tasks that GitHub Copilot will execute, analyze, and implement changes for.
