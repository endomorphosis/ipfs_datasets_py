# Issue-to-Draft-PR Workflow

## Overview

This workflow automatically converts **every GitHub issue** into a draft pull request with GitHub Copilot assigned to implement the solution.

## How It Works

When a new issue is created or reopened:

1. ✅ **Issue Detection** - Workflow triggers automatically
2. ✅ **Analysis** - Categorizes the issue (bug, feature, documentation, etc.)
3. ✅ **Branch Creation** - Creates a dedicated branch `issue-{number}/{sanitized-title}`
4. ✅ **Draft PR Creation** - Creates a draft PR linked to the issue
5. ✅ **Copilot Assignment** - Mentions @copilot to trigger automatic implementation
6. ✅ **Issue Linking** - Links PR back to issue with "Fixes #X"

## Workflow Diagram

```
Issue Created/Reopened
         ↓
   Analysis & Categorization
         ↓
   Branch Created (issue-X/title)
         ↓
   Draft PR Created
         ↓
   @copilot Mentioned
         ↓
   Copilot Implements Solution
         ↓
   Ready for Review
```

## Features

### Automatic Issue Analysis

The workflow analyzes issues to identify:
- **Category**: bug, feature, documentation, test, ci/cd, dependency, performance
- **Keywords**: Extracted from title and body
- **Complexity**: Estimated based on content
- **Effort**: Estimated implementation effort

### Smart Branch Naming

Branch names are automatically generated:
- Format: `issue-{number}/{sanitized-title}`
- Example: `issue-42/fix-broken-workflow` for issue #42 "Fix broken workflow"
- Sanitized to be git-safe (lowercase, no special chars)

### Copilot Integration

The workflow mentions @copilot in the PR with specific instructions:
- Review the issue description
- Implement minimal, surgical changes
- Follow existing code patterns
- Add/update tests as appropriate
- Update documentation if needed

### Duplicate Prevention

The workflow checks for existing PRs before creating new ones:
- Searches for PRs with "Fixes #X" in the body
- Skips creation if PR already exists
- Prevents duplicate work

## Usage

### Automatic Triggering

The workflow runs automatically when:
- A new issue is opened
- An issue is reopened

No manual intervention required!

### Manual Triggering

You can also trigger it manually for a specific issue:

```bash
gh workflow run issue-to-draft-pr.yml \
  --field issue_number="42"
```

## Configuration

### Permissions Required

The workflow needs:
- `contents: write` - To create branches
- `pull-requests: write` - To create PRs
- `issues: write` - To comment on issues

### Repository Settings

For automatic PR creation to work:
1. Go to **Settings → Actions → General → Workflow permissions**
2. Select **"Read and write permissions"**
3. Check **"Allow GitHub Actions to create and approve pull requests"**

## Example Workflow

### Step 1: Issue Created

User creates issue #42:
```
Title: Fix broken GraphRAG workflow
Body: The GraphRAG workflow is failing with import errors...
```

### Step 2: Workflow Runs

The workflow automatically:
- Detects the issue
- Analyzes it (category: ci/cd, complexity: medium)
- Creates branch `issue-42/fix-broken-graphrag-workflow`

### Step 3: PR Created

Draft PR #123 is created:
- **Title**: "Fix: Fix broken GraphRAG workflow"
- **Body**: Contains issue details and analysis
- **Mentions**: @copilot with specific instructions
- **Links**: "Fixes #42"

### Step 4: Issue Updated

Issue #42 receives a comment:
```
🤖 Automatic Draft PR Created

A draft PR has been created: #123
GitHub Copilot has been assigned and will implement the solution.
```

### Step 5: Copilot Works

Copilot analyzes the issue and implements:
- Fixes the import errors
- Updates dependencies if needed
- Adds tests to prevent regression
- Updates documentation

### Step 6: Review & Merge

Human reviews the PR:
- Verifies the implementation
- Checks tests pass
- Approves and merges

## Artifacts

Each run creates artifacts for debugging:
- `issue_body.txt` - Original issue description
- `issue_analysis.json` - Analysis results
- `pr_body.md` - Generated PR description

Download with:
```bash
gh run download {run_id} -n issue-to-pr-{issue_number}
```

## Monitoring

### View Recent Conversions

```bash
# List all draft PRs created by this workflow
gh pr list --draft --label "auto-generated"

# View workflow runs
gh run list --workflow="Convert Issues to Draft PRs with Copilot"
```

### Check Workflow Status

```bash
# View specific run
gh run view {run_id}

# View run logs
gh run view {run_id} --log
```

## Troubleshooting

### PR Not Created?

Check:
1. **Permissions** - Ensure Actions has PR creation permissions
2. **Duplicate** - Check if PR already exists for the issue
3. **Logs** - Review workflow run logs for errors
4. **Rate Limits** - GitHub API rate limits may apply

### Copilot Not Responding?

Check:
1. **Copilot Enabled** - Ensure Copilot is enabled for the repository
2. **@mention** - Verify @copilot was mentioned in the PR
3. **Draft Status** - PR must be in draft state
4. **Permissions** - Copilot needs appropriate access

### Branch Already Exists?

If the branch already exists:
- The workflow will fail at branch creation
- Manually delete the old branch or use a different issue number
- Rerun the workflow

## Best Practices

### ✅ Do's

- Review all Copilot-generated PRs before merging
- Provide clear, detailed issue descriptions
- Use appropriate labels on issues
- Monitor Copilot's work and provide feedback
- Keep issue titles concise and descriptive

### ❌ Don'ts

- Don't auto-merge without human review
- Don't create vague or unclear issues
- Don't skip testing Copilot's implementation
- Don't ignore security concerns
- Don't bypass CI/CD checks

## Integration with Auto-Healing

This workflow complements the existing auto-healing system:

| Feature | Auto-Healing | Issue-to-Draft-PR |
|---------|--------------|-------------------|
| **Trigger** | Workflow failures | Issue creation |
| **Scope** | CI/CD fixes | Any issue type |
| **Analysis** | Log analysis | Issue categorization |
| **Automation** | Full (with Copilot) | Full (with Copilot) |
| **Use Case** | Reactive fixes | Proactive development |

## Security Considerations

### What This Workflow Does

- ✅ Creates branches in the repository
- ✅ Creates draft PRs (requires review)
- ✅ Comments on issues
- ✅ Mentions @copilot for automation

### What It Doesn't Do

- ❌ Auto-merge PRs
- ❌ Modify secrets or credentials
- ❌ Bypass branch protection
- ❌ Execute arbitrary code in main branch

### Safety Features

- All changes go through PR review
- PRs are created as drafts
- CI/CD must pass before merge
- Human approval required
- Audit trail in Git history

## Future Enhancements

Potential improvements:
- **Priority Detection** - Auto-label issues by priority
- **Assignee Matching** - Match issues to team members
- **Template Validation** - Validate issue against templates
- **SLA Tracking** - Track time to resolution
- **Smart Batching** - Batch related issues into single PR
- **AI Summary** - Generate implementation summary from Copilot's work

## Resources

- [GitHub Copilot Agent Documentation](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- [GitHub Actions Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
- [GitHub CLI Manual](https://cli.github.com/manual/)

## Support

For issues with this workflow:
1. Check the workflow logs
2. Review the artifacts
3. Search existing issues
4. Create an issue with the `workflow` label

---

**Making issue resolution automatic with GitHub Copilot** 🤖✨
