# Copilot Auto-Healing Quickstart

Get your repository healing itself in 5 minutes!

## What is Auto-Healing?

Auto-Healing automatically fixes failed GitHub Actions workflows by:
1. Detecting failures
2. Analyzing root causes
3. **Creating an issue with failure details**
4. **Creating a draft PR linked to the issue**
5. Using GitHub Copilot Agent to implement fixes (via @copilot mention)
6. Marking PRs ready for review when complete

**No manual intervention required!**

## Quick Setup

### Step 1: Verify Prerequisites

✅ GitHub Copilot enabled for your repository  
✅ Repository has GitHub Actions enabled  
✅ You have admin access to repository settings  

### Step 2: Install (Already Done!)

The auto-healing workflow is already configured:
- ✅ Workflow: `.github/workflows/copilot-agent-autofix.yml`
- ✅ Scripts: `.github/scripts/` directory
- ✅ Config: `.github/workflows/workflow-auto-fix-config.yml`

### Step 3: Enable (If Needed)

Check configuration is enabled:

```bash
# View current config
cat .github/workflows/workflow-auto-fix-config.yml | grep "enabled:"
```

Should show:
```yaml
enabled: true
```

If not, edit the file:
```yaml
enabled: true

copilot:
  enabled: true
  use_agent_mode: true
```

### Step 4: Test It!

Create a test failure to see auto-healing in action:

```bash
# Method 1: Manually trigger for a recent failure
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Your-Workflow-Name"

# Method 2: Let it work automatically
# Just push code that causes a workflow to fail
# Auto-healing will trigger automatically!
```

## How to Use

### Automatic Mode (Recommended)

Just let workflows run normally:

1. **Workflow fails** → Auto-healing detects it
2. **Analysis runs** → Root cause identified
3. **Issue created** → Failure details documented
4. **Draft PR created** → Fix proposed and linked to issue
5. **Copilot activated** → @copilot mentioned in PR
6. **Copilot implements** → Fix applied automatically
7. **Tests run** → Validation happens
8. **PR marked ready** → Copilot completes work
9. **Review & merge** → You approve the fix

### Manual Trigger

For specific failures:

```bash
# Fix latest failure of a workflow
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Docker Build and Test"

# Fix specific run
gh workflow run copilot-agent-autofix.yml \
  --field run_id="1234567890"

# Force fix even with low confidence
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Test Workflow" \
  --field force_create_pr=true
```

### Via GitHub UI

1. Go to **Actions** tab
2. Click **Copilot Agent Auto-Healing**
3. Click **Run workflow** button
4. Enter workflow name (optional)
5. Click **Run workflow**

## What Happens Next?

### 1. Analysis (30 seconds)
- Downloads failure logs
- Identifies error patterns
- Determines root cause
- Calculates confidence score

### 2. Fix Proposal (30 seconds)
- Generates fix strategy
- Prepares fix recommendations
- Calculates confidence score

### 3. Issue Creation (10 seconds)
- Creates issue with failure details
- Includes logs and analysis
- Adds recommendations
- Links to failed run

### 4. PR Creation (10 seconds)
- Creates branch
- Opens draft PR linked to issue
- Includes fix proposal
- Mentions @copilot to trigger agent

### 5. Copilot Implementation (1-10 minutes)
- Copilot reads issue for context
- Analyzes fix proposal in PR
- Implements suggested fixes
- Commits changes to PR
- Marks PR as ready for review

### 6. Testing (time varies)
- CI/CD runs automatically
- Tests validate the fix
- Status reported on PR

### 7. Your Turn
- Review Copilot's implementation
- Check test results
- Merge if all looks good!
- Issue auto-closes when PR merges

## Monitor Activity

### View Auto-Healing Activity

```bash
# List all auto-healing issues
gh issue list --label "auto-healing"

# List all auto-healing PRs
gh pr list --label "auto-healing"

# View specific issue
gh issue view 123

# View specific PR
gh pr view 124

# See what Copilot changed
gh pr diff 124
```

### Check Workflow Runs

```bash
# View auto-healing runs
gh run list --workflow="Copilot Agent Auto-Healing"

# See specific run details
gh run view 1234567890

# Download artifacts (analysis, logs, etc.)
gh run download 1234567890
```

### Track Success

```bash
# See merged auto-healing PRs
gh pr list --label "auto-healing" --state merged

# Check current open fixes
gh pr list --label "auto-healing" --state open
```

## Common Scenarios

### Scenario 1: Missing Package

**Failure:**
```
ModuleNotFoundError: No module named 'pytest-asyncio'
```

**Auto-Healing:**
1. Detects missing dependency (90% confidence)
2. **Creates issue #123** with failure details
3. **Creates draft PR #124** linked to issue
4. Copilot implements: adds `pytest-asyncio==0.21.0`
5. Tests pass
6. PR marked ready for review
7. Ready to merge!

**Time:** ~2-3 minutes

### Scenario 2: Timeout

**Failure:**
```
Job exceeded timeout (5 minutes)
```

**Auto-Healing:**
1. Identifies timeout issue (95% confidence)
2. Proposes increasing timeout to 30 minutes
3. Copilot updates workflow YAML
4. Next run succeeds
5. Merge!

**Time:** ~2 minutes

### Scenario 3: Permission Error

**Failure:**
```
Error: Resource not accessible (403 Forbidden)
```

**Auto-Healing:**
1. Detects permission issue (80% confidence)
2. Suggests adding permissions section
3. Copilot adds required permissions
4. Tests validate access
5. Done!

**Time:** ~3-4 minutes

## Customization

### Exclude Workflows

Don't want auto-healing for certain workflows?

Edit `.github/workflows/workflow-auto-fix-config.yml`:

```yaml
excluded_workflows:
  - "Deploy to Production"
  - "Publish Release"
```

### Adjust Confidence

Only fix high-confidence issues:

```yaml
min_confidence_for_pr: 85  # Only create PR if 85%+ confident
```

### Rate Limiting

Prevent PR spam:

```yaml
rate_limiting:
  max_prs_per_workflow_per_day: 3
  max_prs_per_day: 10
```

## Troubleshooting

### No PR Created?

**Check:**
1. Was failure detected? → View workflow runs
2. Confidence too low? → Check artifacts
3. Workflow excluded? → Review config
4. Permission issue? → Check repository settings

**Fix:**
```bash
# Manually trigger with force
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Your-Workflow" \
  --field force_create_pr=true
```

### Copilot Didn't Implement?

**Check:**
1. Is Copilot enabled? → Repository settings
2. Was @copilot mentioned? → Check PR comments
3. Task file created? → Look for `.github/copilot-tasks/`
4. PR too complex? → May need manual fix

**Fix:**
- Comment again: `@copilot please implement the fix`
- Or implement manually and close PR

### Fix Didn't Work?

**Check:**
1. Did tests fail? → Review CI results
2. Wrong fix applied? → Review Copilot's changes
3. Multiple issues? → May need separate fixes

**Fix:**
- Close PR
- Review failure manually
- Create issue to track
- Consider updating error patterns

## Tips for Success

### ✅ Do's

- ✅ Review all auto-healed PRs before merging
- ✅ Check test results carefully
- ✅ Provide feedback on fixes
- ✅ Update patterns when you find new errors
- ✅ Monitor success rate
- ✅ Keep Copilot task files clear

### ❌ Don'ts

- ❌ Auto-merge without review
- ❌ Ignore test failures
- ❌ Skip security checks
- ❌ Merge with low confidence
- ❌ Disable branch protection
- ❌ Ignore repeated failures

## Next Steps

### 1. Learn More

- [Full Documentation](README-copilot-autohealing.md)
- [Configuration Guide](workflow-auto-fix-config.yml)
- [Copilot Integration](COPILOT-INTEGRATION.md)

### 2. Customize

- Add custom error patterns
- Tune confidence thresholds
- Configure notifications
- Set up metrics tracking

### 3. Contribute

- Report issues
- Suggest improvements
- Share success stories
- Add documentation

## Examples Repository

Check out example fixes:

```bash
# View closed auto-healing PRs to see examples
gh pr list --label "auto-healing" --state closed --limit 20

# Look at successful fixes
gh pr list --label "auto-healing" --state merged
```

## Getting Help

### Documentation
- [Auto-Healing README](README-copilot-autohealing.md)
- [Workflow Auto-Fix](README-workflow-auto-fix.md)
- [GitHub Actions Docs](https://docs.github.com/actions)

### Support
- Check workflow logs
- Review artifacts
- Search existing issues
- Create new issue with `auto-healing` label

### Community
- Share experiences
- Report bugs
- Suggest features
- Contribute fixes

## Success Metrics

Track your auto-healing effectiveness:

```bash
# Total auto-healing PRs
gh pr list --label "auto-healing" --json number | jq 'length'

# Success rate (merged / total)
TOTAL=$(gh pr list --label "auto-healing" --state all --json number | jq 'length')
MERGED=$(gh pr list --label "auto-healing" --state merged --json number | jq 'length')
echo "Success rate: $(( MERGED * 100 / TOTAL ))%"

# Average time to fix
gh pr list --label "auto-healing" --state merged --json createdAt,mergedAt
```

## Quick Reference

### Commands

```bash
# List auto-healing PRs
gh pr list --label "auto-healing"

# Trigger for workflow
gh workflow run copilot-agent-autofix.yml --field workflow_name="NAME"

# View run details
gh run view RUN_ID

# Download artifacts
gh run download RUN_ID

# Check PR diff
gh pr diff PR_NUMBER
```

### Files

```
.github/
├── workflows/
│   ├── copilot-agent-autofix.yml      # Main auto-healing workflow
│   ├── workflow-auto-fix-config.yml   # Configuration
│   └── README-copilot-autohealing.md  # Full documentation
├── scripts/
│   ├── analyze_workflow_failure.py    # Failure analyzer
│   ├── generate_workflow_fix.py       # Fix generator
│   └── apply_workflow_fix.py          # Fix applier
└── copilot-tasks/
    └── fix-workflow-failure.md        # Created per PR
```

### Labels

- `auto-healing` - Auto-healed PRs
- `automated-fix` - All automated fixes
- `workflow-fix` - Workflow-related fixes

### Confidence Scores

- **90-100%**: Very likely to work, high priority for auto-implementation
- **80-89%**: Good confidence, should work in most cases
- **70-79%**: Moderate confidence, review recommended
- **60-69%**: Lower confidence, careful review needed
- **<60%**: Low confidence, may need manual investigation

---

## That's It!

You're now set up with auto-healing workflows. Your repository will automatically fix itself when workflows fail.

**What to expect:**
- Faster recovery from failures
- Reduced manual intervention
- Consistent fix quality
- 24/7 automated maintenance

**Remember:**
- Always review PRs before merging
- Monitor success rate
- Provide feedback
- Keep patterns updated

**Happy Auto-Healing!** 🤖✨

---

*Need help? Check the [full documentation](README-copilot-autohealing.md) or create an issue.*
