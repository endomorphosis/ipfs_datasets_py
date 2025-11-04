# PR Completion Monitor Workflow

## Overview

The **PR Completion Monitor** workflow automatically checks if pull requests are incomplete and uses the Copilot CLI tool to work on them until they appear complete. This workflow leverages AI/LLM to intelligently determine if a PR's task objective has been completed based on its title and description.

## What It Does

1. **🔍 Monitors PRs**: Checks open pull requests on a schedule or on-demand
2. **🤖 LLM Analysis**: Uses an LLM (OpenAI GPT-4 or Anthropic Claude) to analyze if the PR is complete
3. **📊 Completion Assessment**: Determines completion based on:
   - PR title and description
   - TODO items and checkboxes
   - Draft status
   - Work-in-progress indicators
4. **🔧 Auto-Fix**: Invokes the Copilot CLI auto-fix tool on incomplete PRs
5. **♻️ Continuous Monitoring**: Runs periodically to ensure all PRs reach completion

## Triggers

### 1. Pull Request Events
Triggers when PRs are opened, reopened, synchronized, or marked ready for review:

```yaml
on:
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review]
```

### 2. Scheduled Runs
Runs every 2 hours to check all open PRs:

```yaml
on:
  schedule:
    - cron: '0 */2 * * *'  # Every 2 hours
```

### 3. Manual Dispatch
Run manually on specific PR or force fix:

```yaml
on:
  workflow_dispatch:
    inputs:
      pr_number: 'Specific PR to check'
      force_fix: 'Force fix even if complete'
```

## How It Works

### Step 1: PR Discovery
- For PR events: Uses the triggering PR
- For scheduled runs: Gets all open PRs
- For manual runs: Uses specified PR number

### Step 2: LLM-Based Completion Check

The workflow asks an LLM to analyze the PR and determine if it's complete:

**Prompt Structure:**
```
Analyze this GitHub Pull Request and determine if the task objective has been completed.

PR #123: Fix authentication bug

Description:
[PR body content]

Based on the title and description, determine:
1. Is the task objective clearly completed? (yes/no/unclear)
2. Confidence level (0-100%)
3. Brief reason for your assessment

Consider incomplete if:
- Description says "in progress", "WIP", "draft"
- Lists uncompleted tasks or TODOs
- Explicitly marked as draft
- Indicates work is ongoing

Consider complete if:
- All described objectives are met
- No outstanding TODOs
- Description indicates work is done
- Tests are passing (if mentioned)
```

**LLM Response Format:**
```json
{
  "is_complete": true/false,
  "confidence": 85,
  "reason": "All objectives met, no TODOs remaining"
}
```

### Step 3: Decision Making

Based on LLM analysis:
- **If complete** (and confidence > 60%): Skip PR, no action needed
- **If incomplete**: Invoke Copilot CLI auto-fix tool
- **If uncertain**: Use heuristic fallback

### Step 4: Copilot Invocation

For incomplete PRs, the workflow runs:

```bash
python3 scripts/copilot_auto_fix_all_prs.py --pr <pr_number>
```

This invokes the Copilot coding agent with appropriate instructions based on the PR type.

### Step 5: Continuous Monitoring

The scheduled runs (every 2 hours) ensure that:
- Newly opened PRs are quickly identified
- In-progress PRs continue to receive Copilot assistance
- Stale PRs are re-evaluated

## LLM Providers

The workflow supports multiple LLM providers with automatic fallback:

### Primary: OpenAI GPT-4
```yaml
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```
- Model: `gpt-4o-mini`
- Fast and accurate completion assessment

### Secondary: Anthropic Claude
```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```
- Model: `claude-3-5-sonnet-20241022`
- Fallback if OpenAI unavailable

### Tertiary: Heuristic Fallback
If no LLM API is available, uses simple keyword matching:
- Checks for: "WIP", "in progress", "TODO", "draft", etc.
- Less accurate but doesn't require API access

## Configuration

### Required Secrets

At least one LLM API key should be configured:

```yaml
# Option 1: OpenAI (recommended)
OPENAI_API_KEY: your_openai_api_key

# Option 2: Anthropic
ANTHROPIC_API_KEY: your_anthropic_api_key

# Required for GitHub operations
GITHUB_TOKEN: (automatically provided)
```

### Permissions

```yaml
permissions:
  contents: write
  pull-requests: write
  issues: write
  actions: read
```

## Usage Examples

### Example 1: Automatic Monitoring
The workflow automatically runs every 2 hours:

```
🔍 PR Completion Monitor Starting...
📋 Checking 3 PR(s): 246, 247, 248

================================================================================
Analyzing PR #246
================================================================================
📄 Title: Fix authentication bug
📊 State: open
✅ OpenAI analysis for PR #246: {'is_complete': False, 'confidence': 80, 'reason': 'TODO items remain in description'}
🎯 Completion Status: Incomplete
📊 Confidence: 80%
💡 Reason: TODO items remain in description
🤖 Invoking Copilot on PR #246
✅ Successfully invoked Copilot on PR #246

================================================================================
📊 Summary
================================================================================
Total PRs checked:        3
Complete PRs:             1
Incomplete PRs:           2
Copilot invoked:          2
Skipped (already working): 0
Failed:                   0
```

### Example 2: Manual Run on Specific PR

```bash
# Via GitHub UI:
Actions → PR Completion Monitor → Run workflow
  - PR number: 246
  - Force fix: false

# Or via gh CLI:
gh workflow run pr-completion-monitor.yml \
  -f pr_number=246 \
  -f force_fix=false
```

### Example 3: Force Fix Complete PR

Sometimes you want Copilot to review even "complete" PRs:

```bash
gh workflow run pr-completion-monitor.yml \
  -f pr_number=246 \
  -f force_fix=true
```

## Integration with Copilot Auto-Fix Tool

This workflow integrates seamlessly with the `copilot_auto_fix_all_prs.py` script:

```python
# The workflow calls:
python3 scripts/copilot_auto_fix_all_prs.py --pr <pr_number>

# Which:
1. Analyzes the PR type (auto-fix, workflow, permissions, etc.)
2. Generates tailored Copilot instructions
3. Posts a comment invoking @copilot
4. Copilot agent then works on the PR
```

## Workflow Outputs

### GitHub Step Summary
Each run creates a summary showing:
- Trigger type and configuration
- PRs that were checked
- What the workflow does
- Link to detailed logs

### Detailed Logs
The workflow logs show:
- LLM analysis for each PR
- Completion status and confidence
- Copilot invocation results
- Summary statistics

## Best Practices

### 1. Write Clear PR Descriptions
Help the LLM understand completion status:
- ✅ List objectives explicitly
- ✅ Use checkboxes for tasks: `- [x] Done`, `- [ ] Todo`
- ✅ Update description when work is complete
- ✅ Remove "WIP" or "Draft" when done

### 2. Monitor the Workflow
- Check the scheduled run results
- Review Copilot's work on PRs
- Adjust PR descriptions based on LLM feedback

### 3. Use Manual Runs for Testing
- Test on specific PRs before relying on automation
- Use `force_fix` to see what Copilot would do

### 4. Coordinate with Other Workflows
This workflow complements:
- `copilot-agent-autofix.yml` - Fixes workflow failures
- `pr-copilot-reviewer.yml` - Reviews PR code quality
- Auto-healing workflows

## Troubleshooting

### Issue: LLM says PR is complete but it's not

**Solution:**
1. Improve PR description with clearer objectives
2. Add TODO checkboxes: `- [ ] Incomplete item`
3. Use manual run with `force_fix=true`

### Issue: Copilot keeps working on same PR

**Solution:**
1. The workflow checks for recent `@copilot` mentions
2. Skips if Copilot was already invoked
3. Wait for Copilot to finish before next run

### Issue: No LLM API key available

**Workaround:**
The workflow falls back to heuristic checking based on keywords. This works but is less accurate.

**Fix:**
Add at least one API key:
```bash
gh secret set OPENAI_API_KEY
# or
gh secret set ANTHROPIC_API_KEY
```

### Issue: Too many API calls

**Solution:**
1. Reduce schedule frequency (e.g., every 4 hours instead of 2)
2. Use heuristic mode without API keys
3. Limit to specific PRs with manual runs

## Cost Considerations

### LLM API Costs

**OpenAI GPT-4o-mini:**
- ~$0.15 per 1M input tokens
- ~$0.60 per 1M output tokens
- Each PR check: ~2000 tokens = $0.0003
- With 10 PRs every 2 hours: ~$0.036/day

**Anthropic Claude:**
- ~$3 per 1M input tokens
- ~$15 per 1M output tokens
- Each PR check: ~2000 tokens = $0.006
- With 10 PRs every 2 hours: ~$0.72/day

**Recommendation:** Use OpenAI GPT-4o-mini for cost-effective operation.

## Advanced Configuration

### Adjust Schedule Frequency

```yaml
schedule:
  # Every 4 hours instead of 2
  - cron: '0 */4 * * *'
  
  # Daily at midnight
  - cron: '0 0 * * *'
  
  # Every 30 minutes (more aggressive)
  - cron: '*/30 * * * *'
```

### Customize LLM Prompt

Edit the prompt in the workflow file to adjust how completion is assessed:

```python
prompt = f"""Analyze this GitHub Pull Request...
[Customize completion criteria here]
"""
```

### Add Slack Notifications

```yaml
- name: Notify Slack
  if: steps.check_completion.outputs.incomplete_count > 0
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      {
        "text": "Found ${{ steps.check_completion.outputs.incomplete_count }} incomplete PRs"
      }
```

## Related Documentation

- [Copilot Auto-Fix Script](../../scripts/copilot_auto_fix_all_prs.py)
- [HOW_TO_USE_COPILOT_AUTO_FIX.md](../../HOW_TO_USE_COPILOT_AUTO_FIX.md)
- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)

## Workflow File Location

`.github/workflows/pr-completion-monitor.yml`

## Version

1.0.0

## Last Updated

2025-11-02
