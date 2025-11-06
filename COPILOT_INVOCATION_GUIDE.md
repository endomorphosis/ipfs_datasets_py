# Copilot Issue Assignment Guide

## TL;DR

✅ **Correct**: `gh agent-task create` → Copilot creates PR and works autonomously
⚠️ **Works but deprecated**: `@copilot` comment on issue → Copilot creates PR
❌ **Wrong**: Create PR → `@copilot` comment → Copilot creates child PR (PR sprawl)

## The Discovery (Updated November 6, 2025)

After extensive testing, we discovered the **official method**:

1. **Use `gh agent-task create` command** (requires GitHub CLI v2.80.0+)
2. **Copilot automatically creates a PR and works directly in it**
3. **Concurrency limit: 3 active agents maximum**
4. **Queue management: Check active count before creating new tasks**

## Why This Matters

### PR #49 Example (Success Case)

- **Author**: `app/copilot-swe-agent` (Copilot itself)
- **Invocation**: Plain `@copilot` mentions
- **Result**: Copilot worked in-place, no child PRs

### PRs #297-#340 (Failure Case)

- **Author**: `app/github-actions` (bot)
- **Invocation**: `@copilot /fix` comments
- **Result**: Copilot created 15+ child PRs (PR sprawl)

**The difference?** PR #49 was created BY Copilot. PRs #297-#340 were created by a bot.

## How To Invoke Copilot Correctly

### Method 1: Using `gh agent-task create` (Official Method, Recommended)

**Requirements:**
- GitHub CLI v2.80.0 or later
- Authenticated with `gh auth login`

**Command:**
```bash
# Basic invocation
gh agent-task create "Fix workflow failure in graphrag-production-ci.yml

The workflow is failing with import errors. Please analyze the logs, identify the root cause, and implement a fix.

References:
- Issue: https://github.com/endomorphosis/ipfs_datasets_py/issues/772
- Workflow: .github/workflows/graphrag-production-ci.yml

Ensure all tests pass and security scans are clean." \
  --repo endomorphosis/ipfs_datasets_py \
  --base main

# With follow mode to see logs in real-time
gh agent-task create "Fix the issue" --repo endomorphosis/ipfs_datasets_py --base main --follow

# From a file
gh agent-task create -F task-description.md --repo endomorphosis/ipfs_datasets_py --base main
```

**What happens:**
1. Copilot agent is invoked immediately
2. Creates a new branch (`copilot/[descriptive-name]`)
3. Creates a WIP pull request
4. Analyzes code and implements fixes
5. Runs tests and security scans
6. Updates PR based on review comments

**Concurrency Limit:** Maximum 3 active agents at once

### Method 2: @copilot Comment on Issue (Works but Deprecated)

```bash
gh issue comment 772 --repo endomorphosis/ipfs_datasets_py --body "@copilot

Please analyze this workflow failure and create a pull request with fixes."
```

**Note:** This method still works but is not the official CLI method. Use `gh agent-task create` for better control and visibility.

### Method 3: Automated via Workflow

The `.github/workflows/copilot-issue-assignment.yml` workflow now uses `gh agent-task create`:

- **Triggers**: Issues with "Fix:" prefix or "copilot-fix" label
- **Checks concurrency**: Ensures max 3 active agents
- **Queues if needed**: Labels issue "copilot-queued" if limit reached
- **Creates task**: Uses `gh agent-task create` when slot available

## Cleanup Completed

### Actions Taken (November 6, 2025)

1. ✅ **Closed 30 bot-created PRs** (#256-#340)
   - Reason: Copilot can't work in bot-created PRs without creating child PRs

2. ✅ **Closed 185 duplicate issues**
   - Kept most recent issue per workflow type
   - 12 unique workflow failures remain

3. ✅ **Disabled old workflows**
   - `pr-copilot-monitor.yml`
   - `enhanced-pr-completion-monitor.yml`

4. ✅ **Created new workflow**
   - `copilot-issue-assignment.yml` for issue-based invocation

5. ✅ **Updated documentation**
   - This guide
   - Backed up old DRAFT_PR_INVOCATION_METHOD.md

## Current State

### Open Issues (12 Unique Workflow Failures)

| Issue | Workflow |
|-------|----------|
| #363 | GPU-Enabled Tests |
| #495 | GPU-Enabled Tests |
| #705 | Automated PR Review and Copilot Assignment |
| #720 | Docker Build and Test (Multi-Platform) |
| #723 | MCP Endpoints Integration Tests |
| #725 | Docker Build and Test |
| #728 | MCP Dashboard Automated Tests |
| #734 | Self-Hosted Runner Validation |
| #735 | GraphRAG Production CI/CD |
| #736 | Publish Python Package |
| #737 | ARM64 Self-Hosted Runner |
| #738 | PDF Processing Pipeline CI/CD |

### Next Steps

1. Label issues with "copilot-fix" to trigger assignment
2. Monitor Copilot's PR creation
3. Review and provide feedback
4. Merge successful fixes

## GitHub Documentation References

### Key Quotes

From [Making Changes to Existing PRs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/make-changes-to-an-existing-pr):

> "Copilot will create a child pull request, using the existing pull request's branch as the base branch."

From [About Coding Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent):

> "To delegate tasks to Copilot, you can:
> - Ask Copilot to open a new pull request from many places, including GitHub Issues..."

## Commands Summary

### Check Active Agents
```bash
# See how many agents are currently active
gh pr list --author "app/copilot-swe-agent" --state open --repo endomorphosis/ipfs_datasets_py --json number | jq 'length'

# List active Copilot PRs
gh pr list --author "app/copilot-swe-agent" --state open --repo endomorphosis/ipfs_datasets_py
```

### Create Agent Task
```bash
# Official method (requires gh CLI v2.80.0+)
gh agent-task create "Fix issue description..." \
  --repo endomorphosis/ipfs_datasets_py \
  --base main

# With real-time logs
gh agent-task create "Fix issue..." --repo endomorphosis/ipfs_datasets_py --base main --follow

# From file
gh agent-task create -F task.md --repo endomorphosis/ipfs_datasets_py --base main
```

### Trigger Assignment Workflow
```bash
gh workflow run copilot-issue-assignment.yml \
  --repo endomorphosis/ipfs_datasets_py \
  --field issue_number=772
```

### Add Copilot-Fix Label (Triggers Auto-Assignment)
```bash
gh issue edit 772 \
  --repo endomorphosis/ipfs_datasets_py \
  --add-label "copilot-fix"
```

### Monitor Copilot Sessions
Visit: https://github.com/copilot/agents

## Lessons Learned

1. **`gh agent-task create`** is the official GitHub CLI method (v2.80.0+)
2. **Concurrency limit is 3 agents** - check before creating new tasks
3. **@copilot comments** work but are not the official CLI method
4. **Commenting @copilot on existing PRs** creates child PRs (by design, for preserving original work)
5. **Queue management** is essential to avoid hitting concurrency limits
6. **Session URLs** provide real-time progress tracking

## Old vs New Flow

### Old Flow (Deprecated)
```
Workflow Fails
    ↓
Create Draft PR (by bot)
    ↓
Post @copilot /fix comment
    ↓
Copilot creates Child PR  ← PR SPRAWL
    ↓
Child PR needs review
```

### New Flow (Current - November 6, 2025)
```
Workflow Fails
    ↓
Create Issue
    ↓
gh agent-task create  ← OFFICIAL METHOD
    ↓
Check concurrency (max 3 agents)
    ↓
Copilot creates PR directly  ← CLEAN
    ↓
Single PR needs review
```

**Benefits:**
- Official GitHub CLI command
- Built-in concurrency awareness
- Session URL for progress tracking
- Clean PR structure (no child PRs)
- Better error handling

## Contact & Support

- **Copilot Agents Tab**: https://github.com/copilot/agents
- **GitHub Copilot Docs**: https://docs.github.com/en/copilot
- **Repository**: https://github.com/endomorphosis/ipfs_datasets_py
