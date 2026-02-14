# GitHub Copilot Agent Setup for CI/CD

## Overview

GitHub Copilot coding agents can be invoked in two ways:

### Method 1: @copilot Mentions (ACTIVE - No Setup Required)
- ✅ **Currently working**
- Job #2 in workflow posts @copilot mentions in PR comments
- `copilot-swe-agent` bot detects mentions and creates child PRs
- No additional setup needed
- **Verified working:** PR #344 → @copilot mention → Agent created PR #379

### Method 2: gh agent-task CLI (OPTIONAL - Requires PAT)
- ⚠️ **Requires setup**
- Uses `gh agent-task create` command programmatically
- Requires Personal Access Token (PAT) authentication
- See setup instructions below

## Setting Up gh agent-task (Optional)

If you want to use the `gh agent-task` CLI approach in addition to @copilot mentions:

### Step 1: Create a Personal Access Token (Classic)

1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a descriptive name: `Copilot Agent CI/CD`
4. Select these scopes:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `read:org` (Read org and team membership)
   - ✅ `workflow` (Update GitHub Action workflows)
5. Click "Generate token"
6. **Copy the token immediately** (you won't see it again!)

### Step 2: Add Token as Repository Secret

1. Go to repository settings: https://github.com/endomorphosis/ipfs_datasets_py/settings/secrets/actions
2. Click "New repository secret"
3. Name: `GH_COPILOT_PAT`
4. Value: Paste your PAT from Step 1
5. Click "Add secret"

### Step 3: Enable the CLI Job in Workflow

1. Edit `.github/workflows/pr-copilot-monitor.yml`
2. Find the commented `invoke-agents-with-cli` job (around line 305)
3. Uncomment the entire job (remove the `#` from each line)
4. Commit and push the changes

### Step 4: Verify It Works

1. Trigger the workflow: `gh workflow run pr-copilot-monitor.yml`
2. Watch the run: `gh run watch`
3. Check that "Invoke Agents with gh agent-task" job succeeds
4. Verify agent tasks are created: `gh agent-task list`

## How It Works

When enabled, the workflow will:

```bash
# Authenticate with your PAT
echo "$GH_COPILOT_PAT" | gh auth login --with-token

# For each incomplete PR:
gh agent-task create \
  "Fix issues in PR #123: Fix workflow. Tasks: 1) Review PR 2) Analyze root cause 3) Implement fix" \
  --base "autofix/workflow-name/branch"
```

The agent then:
1. Creates a new PR based on the specified branch
2. Implements the requested changes
3. Commits to the PR
4. Requests review when complete

## Comparison

| Feature | @copilot Mentions | gh agent-task CLI |
|---------|------------------|-------------------|
| Setup Required | None | PAT + Secret |
| Currently Active | ✅ Yes | ⚠️ Optional |
| Authentication | Automatic | Manual PAT |
| Works in CI/CD | ✅ Yes | ✅ Yes (with PAT) |
| Agent Response | Child PR | New PR |
| Tested & Verified | ✅ PR #344→#379 | 🔄 Needs testing |

## Recommendation

**Start with @copilot mentions** (already working). Only enable `gh agent-task` if you need:
- More programmatic control over agent tasks
- Specific branch-based agent workflows
- Multiple agent task creation patterns

## Troubleshooting

### "GH_COPILOT_PAT secret not set"
- You haven't created the secret yet
- The job will skip gracefully - this is expected

### "this command requires an OAuth token"
- Your PAT doesn't have the right scopes
- Re-create the PAT with: repo, read:org, workflow

### "@copilot mentions not working"
- Mentions ARE working - check for child PRs
- Agent responses can take 1-2 minutes
- Check PR #344 for working example

## Links

- [GitHub Copilot in GitHub Support](https://github.blog/news-insights/product-news/github-copilot-in-github-support/)
- [Workflow File](.github/workflows/pr-copilot-monitor.yml)
- [Example Working Agent Response](https://github.com/endomorphosis/ipfs_datasets_py/pull/344#issuecomment-3479055520)
