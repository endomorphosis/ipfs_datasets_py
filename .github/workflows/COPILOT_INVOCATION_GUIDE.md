# GitHub Copilot Invocation Guide for Workflows

## Overview

This guide clarifies the **correct** way to invoke GitHub Copilot in different scenarios within GitHub Actions workflows.

## Important: Two Different Use Cases

### 1. Creating NEW Tasks (New PRs) - Use `gh agent-task create`

When you want Copilot to **create a NEW pull request** from scratch:

```bash
# ✅ CORRECT: Create a new agent task that will create a new PR
gh agent-task create "Fix the failing tests in test_utils.py" --base main

# Or with detailed instructions from a file
gh agent-task create -F task-description.txt --base main
```

**Use this when:**
- Starting completely new work from an issue
- Creating a feature from scratch
- No existing PR exists yet

**What happens:**
- Copilot analyzes the task
- Copilot creates changes on a new branch
- Copilot opens a new PR with the implementation

### 2. Working on EXISTING PRs - Use PR Comments

When you want Copilot to work on an **existing pull request**:

```bash
# ✅ CORRECT: Add a comment on existing PR to invoke Copilot
gh pr comment 123 --body "@github-copilot /fix

Please analyze this PR and implement the necessary fixes based on:
1. The PR description and linked issue
2. Any workflow failure logs mentioned
3. Code review comments
4. Test failures

Focus on making minimal, surgical changes that directly address the problem."
```

**Use this when:**
- A PR already exists that needs work
- Auto-healing workflows created a draft PR
- Issue-to-PR workflow created a draft PR
- You want Copilot to fix/review/implement on existing PR

**What happens:**
- Copilot receives the comment notification
- Copilot analyzes the existing PR
- Copilot pushes commits to the same branch
- Copilot responds with comments

## Workflow Scripts

### For Existing PRs (Most Common)

Use `scripts/invoke_copilot_on_pr.py`:

```yaml
- name: Assign Copilot to existing PR
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    python3 scripts/invoke_copilot_on_pr.py \
      --pr "$PR_NUMBER" \
      --instruction "Your specific instructions here" \
      --repo ${{ github.repository }}
```

### For New Tasks (Rare in Auto-Healing)

Only use `gh agent-task create` directly if you want a completely new PR:

```yaml
- name: Create new Copilot task
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    gh agent-task create "Build a new feature for X" --base main --repo ${{ github.repository }}
```

**⚠️ WARNING**: Do NOT use `gh agent-task create` when you already have a PR! It will create a DIFFERENT, NEW PR instead of working on the existing one.

## Common Mistakes

### ❌ WRONG: Using gh agent-task for Existing PRs

```yaml
# This is WRONG - it will create a NEW PR, not work on PR #123
- run: |
    gh agent-task create "Fix PR #123" --base main
```

**Problem**: Creates a new agent task and NEW PR instead of working on the existing PR #123.

### ✅ CORRECT: Using Comments for Existing PRs

```yaml
# This is CORRECT - Copilot will work on the EXISTING PR #123
- run: |
    python3 scripts/invoke_copilot_on_pr.py --pr 123 \
      --instruction "Fix the issues in this PR" \
      --repo ${{ github.repository }}
```

**Result**: Copilot works on the existing PR #123 directly.

## Workflow-Specific Usage

### pr-copilot-reviewer.yml
- **Purpose**: Assign Copilot to existing PRs
- **Method**: PR comments via `invoke_copilot_on_pr.py`
- **Why**: PRs already exist, just need Copilot assignment

### issue-to-draft-pr.yml
- **Purpose**: Create draft PR and assign Copilot
- **Method**: Create PR first, then use comments via `invoke_copilot_with_queue.py` (has fallback)
- **Why**: Workflow creates the PR, then needs Copilot to work on it

### copilot-agent-autofix.yml
- **Purpose**: Auto-heal failed workflows
- **Method**: Create draft PR, then use comments via `invoke_copilot_on_pr.py`
- **Why**: Auto-healing creates fix PR, then Copilot implements the fix

## Testing Copilot Invocation

### Test if Comment-Based Invocation Works

```bash
# 1. Create a test PR (or use existing one)
gh pr create --draft --title "Test PR" --body "Test body"

# 2. Invoke Copilot using the script
python3 scripts/invoke_copilot_on_pr.py --pr <PR_NUMBER> \
  --instruction "Please review this PR" \
  --dry-run  # Remove --dry-run to actually invoke
```

### Test if Agent Task Creation Works

```bash
# This creates a NEW task and NEW PR
gh agent-task create "Build a hello world script in Python" \
  --base main --follow
```

## Troubleshooting

### Copilot Not Responding on PR

1. **Check the comment was posted**: Look at PR comments
2. **Verify @github-copilot mention**: Should be in comment
3. **Check Copilot is enabled**: Repository settings
4. **Wait a few minutes**: Copilot may take time to respond

### "Unknown command: agent-task"

**Solution**: Update GitHub CLI:
```bash
gh extension list  # Check if copilot extension is installed
gh extension upgrade --all  # Update extensions
```

### Permission Denied

**Solution**: Ensure GH_TOKEN has proper permissions:
```yaml
permissions:
  contents: write
  pull-requests: write
```

## References

- [GitHub CLI Manual](https://cli.github.com/manual/gh)
- [Copilot CLI Documentation](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)
- [Agent Management](https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management)

## Summary

**Golden Rule**: 
- 🆕 **New work** → `gh agent-task create` (creates NEW PR)
- 📝 **Existing PR** → PR comments via scripts (works on EXISTING PR)

Most workflows in this repository work with **existing PRs**, so they should use the **comment-based** approach via `invoke_copilot_on_pr.py`.
