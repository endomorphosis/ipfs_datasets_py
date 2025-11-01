# PR Copilot Reviewer - Integration Guide

## Overview

The PR Copilot Reviewer is a critical component of the automated fixing and healing software. It automatically assigns GitHub Copilot to pull requests with context-aware instructions using the GitHub CLI tooling.

## Key Features

- **GitHub CLI Integration**: Uses `gh pr comment` and `gh agent-task` commands to properly invoke Copilot agent
- **Agent Task Verification**: Verifies that Copilot agent task was created successfully
- **Progress Monitoring**: Optionally monitors Copilot agent progress after assignment
- **Context-Aware Assignment**: Analyzes PR content and assigns appropriate task type (fix, implement, review)

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Auto-Healing Ecosystem                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │     Any Workflow Fails                  │
        │  (e.g., Docker Build, GPU Tests)        │
        └────────────┬────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────────────┐
        │  copilot-agent-autofix.yml              │
        │  - Detects failure                      │
        │  - Analyzes logs                        │
        │  - Generates fix proposal               │
        │  - Creates issue                        │
        │  - Creates draft PR                     │
        └────────────┬────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────────────┐
        │  pr-copilot-reviewer.yml ⭐             │
        │  - Detects new PR                       │
        │  - Analyzes PR content                  │
        │  - Determines task type                 │
        │  - Invokes Copilot via GitHub CLI       │
        │  - Verifies agent task creation         │
        │  - Monitors agent progress (optional)   │
        └────────────┬────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────────────┐
        │  GitHub Copilot Agent                   │
        │  - Reviews PR                           │
        │  - Implements fixes                     │
        │  - Runs tests                           │
        │  - Ready for human review               │
        └─────────────────────────────────────────┘
```

## Workflow Integration

### Monitored by Auto-Healing

The PR Copilot Reviewer workflow is **itself monitored** by the auto-healing system:

- **Position**: #2 in the monitored workflows list
- **Effect**: If the reviewer workflow fails, auto-healing will create a fix PR
- **Result**: Self-healing automation loop - the automation heals itself!

### Current Monitored Workflows (17 Total)

1. ARM64 Self-Hosted Runner
2. **Automated PR Review and Copilot Assignment** ⭐ (pr-copilot-reviewer)
3. Comprehensive Scraper Validation
4. Docker Build and Test
5. Docker Build and Test (Multi-Platform)
6. Documentation Maintenance
7. GPU-Enabled Tests
8. GraphRAG Production CI/CD
9. MCP Dashboard Automated Tests
10. MCP Endpoints Integration Tests
11. PDF Processing Pipeline CI/CD
12. PDF Processing and MCP Tools CI
13. Publish Python Package
14. Scraper Validation and Testing
15. Self-Hosted Runner Test
16. Self-Hosted Runner Validation
17. Test Datasets ARM64 Runner

## Triggers

The workflow triggers on:

- **pull_request**: When a PR is opened, reopened, or marked ready for review
- **workflow_dispatch**: Manual trigger with PR number input

## Analysis Logic

The workflow analyzes PRs and classifies them into task types:

### Task Classification

```python
if auto_generated or workflow_fix:
    task = "fix"
    command = "@copilot /fix"
    
elif is_draft and needs_implementation:
    task = "implement"
    command = "@copilot"
    
else:
    task = "review"
    command = "@copilot /review"
```

### Assignment Reasons

The workflow tracks why Copilot was assigned:

- Auto-generated PR
- Workflow fix PR
- Resolves an issue
- Draft PR needing implementation
- General review

## Usage Examples

### Example 1: Auto-Generated Workflow Fix

```
Workflow Fails: Docker Build and Test
         ↓
Auto-Healing: Creates Issue #123, Draft PR #456
         ↓
PR Copilot Reviewer: Detects PR #456
         ↓
Analysis: "auto-generated", "workflow fix"
         ↓
Assignment: @copilot /fix with specific instructions
         ↓
Copilot: Implements the fix
         ↓
Result: PR ready for review in ~2-5 minutes
```

### Example 2: User Creates Draft PR

```
User: Opens draft PR #789 "Add new feature X"
         ↓
PR Copilot Reviewer: Detects PR #789
         ↓
Analysis: "draft", "needs implementation"
         ↓
Assignment: @copilot with implementation instructions
         ↓
Copilot: Implements the feature
         ↓
Result: Draft PR updated with implementation
```

### Example 3: PR Ready for Review

```
Developer: Marks PR #101 as ready for review
         ↓
PR Copilot Reviewer: Detects state change
         ↓
Analysis: "ready_for_review", "general review"
         ↓
Assignment: @copilot /review with review checklist
         ↓
Copilot: Reviews code, suggests improvements
         ↓
Result: Review comments posted
```

## GitHub CLI Integration

### How Copilot is Invoked

The workflow uses the **GitHub CLI (`gh`)** to properly invoke the Copilot agent:

1. **Comment Posting**: Uses `gh pr comment` to post @copilot mentions
   ```bash
   gh pr comment "$PR_NUMBER" --repo OWNER/REPO --body "@copilot /fix ..."
   ```

2. **Agent Task Verification**: Verifies agent task was created
   ```bash
   gh agent-task view "$PR_NUMBER" --repo OWNER/REPO
   ```

3. **Progress Monitoring**: Optionally monitors agent progress
   ```bash
   gh agent-task view "$PR_NUMBER" --log
   ```

### Why GitHub CLI?

The workflow uses the GitHub CLI instead of just mentioning @copilot because:

- **Programmatic Control**: Allows automation to invoke Copilot from CI/CD
- **Verification**: Can verify that agent task was created successfully
- **Monitoring**: Can track agent progress programmatically
- **Error Handling**: Better error detection and handling
- **Consistency**: Ensures reliable invocation across different scenarios

### CLI vs Web UI

| Method | Use Case | Advantages |
|--------|----------|------------|
| `gh pr comment` with @copilot | Existing PRs (automation) | Works in CI/CD, programmatic control |
| `gh agent-task create` | New PRs (from scratch) | Creates PR and assigns task in one step |
| Web UI @copilot mention | Existing PRs (manual) | Simple for humans, but not automatable |

## Configuration

### Workflow Inputs (Manual Trigger)

```yaml
pr_number: 
  description: 'PR number to analyze and assign to Copilot'
  required: true
  type: string

force_assign:
  description: 'Force Copilot assignment even if already assigned'
  required: false
  default: false
  type: boolean

monitor_agent:
  description: 'Monitor Copilot agent progress after assignment'
  required: false
  default: true
  type: boolean
```

### Permissions Required

- **contents**: read (to access PR content)
- **pull-requests**: write (to comment and assign Copilot)
- **issues**: read (to check related issues)

## Preventing Duplicates

The workflow includes duplicate detection:

1. Checks if Copilot has already been mentioned in PR comments
2. Skips assignment if already assigned (unless `force_assign=true`)
3. Logs skip reason in workflow summary

## Step-by-Step Flow

1. **Clean workspace**: Removes git lock files
2. **Checkout repository**: Gets latest code
3. **Set up Python**: Installs dependencies
4. **Setup GitHub CLI**: Ensures `gh` CLI is available
5. **Get PR details**: Fetches PR metadata using `gh pr view`
6. **Check existing assignment**: Prevents duplicates
7. **Analyze PR**: Determines task type (fix, implement, review)
8. **Invoke Copilot via GitHub CLI**: 
   - Posts comment with `gh pr comment`
   - Verifies agent task with `gh agent-task view`
9. **Monitor agent progress** (optional): Tracks Copilot's work
10. **Summary**: Reports completion status

## Testing

### Manual Test

```bash
# Test with a specific PR
gh workflow run pr-copilot-reviewer.yml \
  -f pr_number=123

# Force reassignment
gh workflow run pr-copilot-reviewer.yml \
  -f pr_number=123 \
  -f force_assign=true

# Disable agent monitoring
gh workflow run pr-copilot-reviewer.yml \
  -f pr_number=123 \
  -f monitor_agent=false
```

### Verify Agent Task

After the workflow runs, verify the agent task was created:

```bash
# View agent task for a PR
gh agent-task view 123 --repo OWNER/REPO

# Follow agent task logs
gh agent-task view 123 --repo OWNER/REPO --log --follow
```

### Automated Test

Run the test suite:

```bash
python3 << 'EOF'
import yaml

# Test YAML parsing
with open('.github/workflows/pr-copilot-reviewer.yml') as f:
    wf = yaml.safe_load(f)

assert 'on' in wf, "Failed: 'on' key not found"
assert 'pull_request' in wf['on'], "Failed: No pull_request trigger"
print("✅ All tests passed!")
EOF
```

## Troubleshooting

### Workflow Not Triggering

**Problem**: PR created but workflow doesn't run

**Solutions**:
1. Check workflow is enabled in repository settings
2. Verify PR type matches triggers (opened/reopened/ready_for_review)
3. Check workflow file syntax with `yamllint`

### Copilot Not Responding

**Problem**: Copilot mentioned but doesn't respond

**Solutions**:
1. Verify Copilot is enabled for the repository
2. Check @copilot mention format (exactly `@copilot`)
3. Ensure PR has enough context (title + description)
4. Wait 1-2 minutes for Copilot to process

### Duplicate Assignments

**Problem**: Copilot mentioned multiple times

**Solutions**:
1. Workflow has built-in duplicate detection
2. Check logs to see why detection failed
3. Use `force_assign=false` (default)

## Integration Points

### With Auto-Healing System

- **Input**: Receives PRs created by copilot-agent-autofix.yml
- **Output**: Assigns Copilot to implement fixes
- **Monitoring**: Itself monitored by auto-healing

### With Issue-to-Draft-PR System

- **Input**: Receives PRs created by issue-to-draft-pr.yml
- **Output**: Assigns Copilot to implement solutions
- **Linking**: Both mention @copilot in similar way

### With GitHub Actions

- **Events**: Responds to GitHub PR events
- **API**: Uses GitHub CLI (gh) and REST API
- **Permissions**: Uses GITHUB_TOKEN

## Best Practices

### For Users

1. **Write clear PR descriptions**: Helps Copilot understand context
2. **Link related issues**: Use "Fixes #123" in PR body
3. **Mark as draft if incomplete**: Gets implementation task instead of review
4. **Use descriptive titles**: Analyzed by the workflow

### For Maintainers

1. **Monitor workflow runs**: Check for failures
2. **Review Copilot assignments**: Ensure quality
3. **Update monitored list**: Keep auto-healing integrated
4. **Test changes**: Use workflow_dispatch for testing

### For Developers

1. **Keep YAML syntax clean**: Quote `on:` as `'on:'`
2. **Remove trailing spaces**: Prevents lint errors
3. **Test locally**: Validate YAML before committing
4. **Document changes**: Update this guide

## Metrics

Track effectiveness:

```bash
# List PRs with Copilot assignments
gh pr list --search "@copilot in:comments"

# Check workflow success rate
gh run list --workflow="pr-copilot-reviewer.yml" --json conclusion | \
  jq '[.[] | .conclusion] | group_by(.) | map({key: .[0], count: length}) | from_entries'
```

## Future Enhancements

Potential improvements:

- [ ] Machine learning for better task classification
- [ ] Integration with code quality metrics
- [ ] Automatic severity assessment
- [ ] Copilot response time tracking
- [ ] Success rate analytics dashboard
- [ ] A/B testing different instruction formats
- [ ] Multi-language support for instructions

## Resources

- **Workflow File**: [pr-copilot-reviewer.yml](pr-copilot-reviewer.yml)
- **Auto-Healing**: [copilot-agent-autofix.yml](copilot-agent-autofix.yml)
- **Issue-to-PR**: [issue-to-draft-pr.yml](issue-to-draft-pr.yml)
- **Main Documentation**: [README.md](README.md)
- **Copilot Integration**: [COPILOT-INTEGRATION.md](COPILOT-INTEGRATION.md)

## Support

For issues or questions:

1. Check workflow run logs
2. Review GitHub Actions documentation
3. Test with workflow_dispatch
4. Create issue with `auto-healing` label

---

**Last Updated**: 2025-11-01  
**Status**: ✅ Active and Production Ready  
**Integration**: ✅ Monitored by Auto-Healing (#2)
