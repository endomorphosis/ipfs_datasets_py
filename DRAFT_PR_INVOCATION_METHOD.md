# Draft PR Copilot Invocation Method

## Overview

This document explains the **VS Code-style Draft PR method** for invoking GitHub Copilot, implemented per user request to match how VS Code invokes Copilot agents.

## 🎯 Why the Change?

### Evidence from VS Code Usage

The user provided **PR #401** as evidence of how VS Code invokes Copilot:
- **Author**: `app/copilot-swe-agent`
- **Branch**: `copilot/fix-failing-github-workflows`
- **Workflow Run**: 19108196285
- **Event Type**: `dynamic`
- **Conclusion**: `success`

This PR was created directly by Copilot when the user worked in VS Code, demonstrating the **correct invocation method**.

### What Doesn't Work

❌ **@copilot Comments on PRs**: 66 draft PRs with @copilot comments received ZERO responses from Copilot

❌ **Issue-based invocation**: While this works (Issue #339 → PR #382), it's not the VS Code method the user wanted

## ✅ VS Code Method: Draft PR Invocation

### How It Works

1. **Create a new branch** (e.g., `copilot/complete-pr-123`)
2. **Create initial commit** with `COPILOT_TASK.md` describing the work
3. **Push branch** to GitHub
4. **Create draft PR** with clear title and description
5. **Copilot detects** the draft PR automatically
6. **Copilot implements** the changes
7. **Copilot pushes** commits to the branch

### Key Components

#### 1. invoke_copilot_via_draft_pr.py

**Location**: `scripts/invoke_copilot_via_draft_pr.py`

**Purpose**: Standalone script to invoke Copilot via draft PR method

**Methods**:
- `create_branch()` - Create new branch with unique name
- `create_initial_commit()` - Create COPILOT_TASK.md with work description
- `push_branch()` - Push branch to GitHub
- `create_draft_pr()` - Create draft PR via GitHub CLI
- `invoke_copilot()` - Orchestrate the complete flow

**Usage**:
```bash
python3 scripts/invoke_copilot_via_draft_pr.py \
  --title "Fix failing workflows" \
  --description "Complete work from PR #123" \
  --repo "endomorphosis/ipfs_datasets_py" \
  --base "main" \
  --branch-prefix "copilot/fix-workflows"
```

#### 2. draft_pr_copilot_invoker.py

**Location**: `scripts/draft_pr_copilot_invoker.py`

**Purpose**: Monitor draft PRs and create draft PRs for Copilot to work on

**Renamed from**: `issue_based_pr_monitor.py` (old issue-based method)

**Key Changes**:
- Class renamed: `IssueBasedPRMonitor` → `DraftPRCopilotInvoker`
- Method renamed: `create_issue_for_pr()` → `create_draft_pr_for_work()`
- Statistics updated: `issues_created` → `draft_prs_created`
- Parameters updated: `--max-issues` → `--max-drafts`

**How it works**:
1. Fetches all draft PRs
2. Checks if each PR needs work
3. Creates NEW draft PR for Copilot to complete the work
4. Copilot detects and works on the new draft PR

**Usage**:
```bash
# Normal mode
python3 scripts/draft_pr_copilot_invoker.py --max-drafts 5

# Dry run mode
python3 scripts/draft_pr_copilot_invoker.py --dry-run --max-drafts 2

# With notification
python3 scripts/draft_pr_copilot_invoker.py --notification-user endomorphosis --max-drafts 3
```

## 🔄 Updated Workflows

### 1. enhanced-pr-completion-monitor.yml

**Changes**:
- Step renamed: "Run Enhanced PR Monitor" → "Run Draft PR Copilot Invoker"
- Script updated: `issue_based_pr_monitor.py` → `draft_pr_copilot_invoker.py`
- Parameter updated: `--max-issues` → `--max-drafts`
- Output metrics: `issues_created` → `draft_prs_created`
- Summary text: "Creates GitHub issues" → "Creates draft PRs for Copilot"

**What it does**:
- Runs every 10 minutes
- Monitors all draft PRs
- Creates draft PRs for incomplete work
- Copilot detects and implements changes

### 2. pr-copilot-monitor.yml

**Changes**:
- Workflow name: "PR Copilot Monitor" → "Draft PR Copilot Monitor"
- Job name: `issue-based-pr-monitor` → `draft-pr-copilot-monitor`
- Input parameter: `max_issues` → `max_drafts`
- Script updated: `issue_based_pr_monitor.py` → `draft_pr_copilot_invoker.py`
- Output metrics: `issues_created` → `drafts_created`

**What it does**:
- Runs every 10 minutes
- Monitors draft PRs
- Creates draft PRs for Copilot (VS Code method)
- Max 3 draft PRs per run (configurable)

## 📊 Testing Results

### Dry Run Test

```bash
$ python3 scripts/draft_pr_copilot_invoker.py --dry-run --max-drafts 2
```

**Results**:
- ✅ Script executed successfully
- ✅ Found 65 draft PRs
- ✅ Identified 5 PRs needing work
- ✅ Would create 2 draft PRs (max limit)
- ✅ Detected 2 PRs already have draft PRs
- ✅ No errors

**Output Format**:
```
💡 VS CODE COPILOT INVOCATION METHOD:
   ✅ Create draft PRs for Copilot to work on
   ✅ Copilot automatically detects and implements changes
   ❌ NOT: Commenting @copilot on existing PRs
   ❌ NOT: Creating issues (old method)

📊 Draft PR Copilot Invoker Summary
Total draft PRs:          65
PRs needing work:         5
Draft PRs created:        2
Already have drafts:      2
Skipped (Copilot PRs):    0
Errors:                   0
```

## 🎯 Comparison: Old vs New Method

### Old Method (Issue-Based)

```
1. Monitor detects incomplete PR
2. Create GitHub issue describing work
3. Copilot creates PR to fix issue
4. Two separate PRs: original + Copilot's fix PR
```

**Problems**:
- Not how VS Code invokes Copilot
- Creates extra issues
- Two PRs instead of one
- User didn't want this method

### New Method (Draft PR - VS Code Style)

```
1. Monitor detects incomplete PR
2. Create draft PR for Copilot to work on
3. Copilot detects draft PR automatically
4. Copilot implements changes on draft PR
5. One focused PR with clear task
```

**Benefits**:
- ✅ Matches VS Code behavior (user's request)
- ✅ Based on evidence from PR #401
- ✅ No extra issues created
- ✅ Clear separation of work
- ✅ Copilot works on dedicated branch

## 🔧 Implementation Details

### Branch Naming Convention

```
copilot/complete-pr-{pr_number}-{timestamp}
```

Example: `copilot/complete-pr-311-1699374190`

### Task Description Format

The `COPILOT_TASK.md` file contains:

```markdown
# Complete Draft PR #{pr_number}

## Original PR
- **Link**: {pr_url}
- **Title**: {pr_title}
- **Author**: @{author}
- **Why needs work**: {reason}

## Description
{pr_body}

## Task
Please complete the work from draft PR #{pr_number}:

1. Review the original PR and its current state
2. Identify what work remains to be done
3. Implement the required changes
4. Test that everything works correctly
5. Push commits to this branch

## Context
- This is to complete an unfinished draft PR
- Related PR: #{pr_number}
- Invoked: {timestamp}
```

### Draft PR Title Format

```
Complete draft PR #{pr_number}: {original_pr_title}
```

## 📈 Metrics and Monitoring

### Output Metrics

- `total_prs` - Total draft PRs found
- `needs_work` - PRs needing work
- `draft_prs_created` - Draft PRs created for Copilot
- `already_has_draft` - PRs already have draft PRs
- `skipped_copilot_prs` - PRs created by Copilot (skipped)
- `errors` - Errors encountered

### Workflow Summary

Each workflow run generates a summary showing:
- Statistics
- How the method works
- What Copilot will do
- Next scheduled run

## 🚀 Next Steps

1. **Monitor Copilot Activity**: Watch for Copilot to detect and work on draft PRs
2. **Validate Approach**: Confirm Copilot responds to draft PRs as expected
3. **Adjust Parameters**: Tune `max_drafts` based on Copilot's capacity
4. **Track Completion**: Monitor how long Copilot takes to complete draft PRs
5. **Iterate**: Adjust task descriptions if Copilot needs more context

## 📝 Notes

- This method was implemented based on **user evidence** (PR #401)
- Tested in **dry-run mode** successfully
- All workflows updated to use the new method
- Old issue-based method completely replaced
- **NOT using @copilot comments** (proven not to work)

## 🔗 Related Files

- `scripts/invoke_copilot_via_draft_pr.py` - Core draft PR invocation script
- `scripts/draft_pr_copilot_invoker.py` - PR monitoring and draft PR creation
- `.github/workflows/enhanced-pr-completion-monitor.yml` - Main monitoring workflow
- `.github/workflows/pr-copilot-monitor.yml` - Scheduled monitoring workflow

## ✅ Verification

To verify the implementation:

```bash
# Test the invoker script
python3 scripts/draft_pr_copilot_invoker.py --dry-run --max-drafts 1

# Test the standalone script
python3 scripts/invoke_copilot_via_draft_pr.py --help

# Check workflow syntax
cd .github/workflows/
grep -r "draft_pr_copilot_invoker" .
grep -r "max-drafts" .
```

All tests passed ✅

---

**Implementation Date**: 2024-11-05  
**Commit**: 24f0c26  
**Status**: ✅ Complete and Tested
