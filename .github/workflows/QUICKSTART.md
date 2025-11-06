# 🚀 Quick Start: GitHub Copilot Auto-Healing System

Get up and running with the auto-healing system in 5 minutes!

## What is Auto-Healing?

When a GitHub Actions workflow fails, this system automatically:
1. 🔍 **Detects** the failure
2. 📊 **Analyzes** the root cause
3. 🔧 **Generates** a fix
4. 🤖 **Creates** a PR with GitHub Copilot
5. ✨ **Implements** the fix automatically (via Copilot Agent)
6. ✅ **Validates** with tests

**No manual intervention required!**

## Prerequisites

✅ GitHub repository with Actions enabled  
✅ GitHub Copilot enabled for the repository  
✅ Branch protection configured for main branch  
✅ Basic understanding of GitHub Actions  

## Quick Setup (Already Done!)

The system is **already configured** in this repository:

```
✅ Workflow file: .github/workflows/copilot-agent-autofix.yml
✅ Python scripts: .github/scripts/*.py
✅ Documentation: .github/workflows/README*.md
✅ Permissions: Configured correctly
```

**You don't need to install anything!**

## How to Use

### 1. Automatic Mode (Recommended)

The system runs automatically when any workflow fails.

**What happens:**
1. Any workflow fails → Auto-healing triggers
2. Analyzes logs → Identifies error type
3. Generates fix → Creates PR
4. Mentions @copilot → Copilot implements
5. Tests run → Validates fix
6. PR ready → Review and merge

**You do nothing!** Just review the PR when ready.

### 2. Manual Trigger

Trigger manually for specific failures:

#### Via GitHub UI
1. Go to **Actions** tab
2. Select **Copilot Agent Auto-Healing**
3. Click **Run workflow** (top right)
4. Optional: Enter workflow name or run ID
5. Click **Run workflow** button

#### Via GitHub CLI
```bash
# Analyze latest failure for a specific workflow
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Docker Build and Test"

# Analyze specific workflow run
gh workflow run copilot-agent-autofix.yml \
  --field run_id="1234567890"

# Force create PR even with low confidence
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Test Suite" \
  --field force_create_pr=true
```

## Example: Dependency Error

Let's walk through a real example:

### Problem
```yaml
# .github/workflows/test.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pytest
      - run: pytest tests/
```

Workflow fails with:
```
ERROR: ModuleNotFoundError: No module named 'pytest-asyncio'
```

### Auto-Healing Response

**Step 1: Detection** (automatic, within seconds)
```
🔍 Workflow failure detected: Test Suite
📊 Analyzing logs...
```

**Step 2: Analysis** (automatic)
```
✅ Error Type: Missing Dependency
✅ Root Cause: ModuleNotFoundError: pytest-asyncio
✅ Confidence: 90%
```

**Step 3: Fix Generation** (automatic)
```
🔧 Generating fix proposal...
✅ Add pytest-asyncio to requirements.txt
✅ Update workflow install step
```

**Step 4: PR Creation** (automatic)
```
🌿 Branch created: autofix/test-suite/add-dependency/20251030
📝 PR created: fix: Auto-fix Missing Dependency in Test Suite
🤖 @copilot mentioned in comment
```

**Step 5: Copilot Implementation** (automatic)
```
🤖 Copilot Agent reading task...
✅ Adding pytest-asyncio==0.21.0 to requirements.txt
✅ Updating workflow install step
✅ Committing changes
✅ Running tests
```

**Step 6: Validation** (automatic)
```
✅ Tests passed
✅ PR ready for review
```

### Your Action

1. Receive PR notification
2. Review Copilot's changes
3. Merge PR (if changes look good)

**Total time: ~5 minutes** (all automatic!)

## What Errors Can It Fix?

| Error Type | Example | Confidence |
|------------|---------|------------|
| 🔧 Missing Dependencies | `ModuleNotFoundError` | 90% |
| ⏱️ Timeouts | `timeout exceeded` | 95% |
| 🔒 Permissions | `403 Forbidden` | 80% |
| 🌐 Network Issues | `ConnectionError` | 75% |
| 🐳 Docker Problems | `Docker daemon` | 85% |
| 💾 Resource Issues | `out of memory` | 90% |
| 🔑 Environment Variables | `variable not set` | 95% |
| 📝 Syntax Errors | `SyntaxError` | 85% |
| 🧪 Test Failures | `AssertionError` | 70% |

## Monitoring

### Check Auto-Healing Status

```bash
# List all auto-healing PRs
gh pr list --label "auto-healing"

# View recent workflow runs
gh run list --workflow="Copilot Agent Auto-Healing" --limit 5

# Check specific PR
gh pr view 123
```

### View Dashboard

```bash
# In GitHub UI
# Actions → Copilot Agent Auto-Healing → Latest runs
```

## Configuration

### Adjust Settings (Optional)

Edit `.github/workflows/workflow-auto-fix-config.yml`:

```yaml
# Enable/disable auto-healing
enabled: true

# Minimum confidence to create PR (0-100)
min_confidence: 70

# Workflows to exclude
excluded_workflows:
  - "Deploy to Production"
  - "Publish Release"

# Copilot settings
copilot:
  enabled: true
  auto_mention: true
  timeout_hours: 24
```

## Best Practices

### ✅ Do's
- ✅ Review all auto-generated PRs before merging
- ✅ Monitor fix success rate
- ✅ Provide feedback on false positives
- ✅ Keep branch protection enabled
- ✅ Run full test suite on PRs

### ❌ Don'ts
- ❌ Auto-merge PRs (always review)
- ❌ Disable branch protection
- ❌ Ignore low confidence fixes
- ❌ Skip testing before merge
- ❌ Bypass review process

## Troubleshooting

### Q: Copilot didn't respond to the PR
**A:** Check:
1. Copilot enabled for repo?
2. Task file created in `.github/copilot-tasks/`?
3. @copilot mentioned in comment?
4. Try re-triggering manually

### Q: Fix didn't work
**A:** 
1. Check the confidence score (was it <70%?)
2. Review the analysis in PR description
3. Multiple errors in same run? May need manual fix
4. Close PR and investigate manually

### Q: No PR was created
**A:**
1. Check workflow run logs in Actions tab
2. Was confidence too low? (check threshold)
3. Is workflow excluded in config?
4. Check permissions are correct

### Q: Too many PRs created
**A:**
1. Multiple workflows failing? Normal behavior
2. Check rate limiting in config
3. Close duplicate PRs manually
4. Adjust configuration

## Getting Help

### Resources
- 📖 [Full Documentation](README-copilot-autohealing.md)
- 📊 [Validation Report](VALIDATION_REPORT.md)
- 🧪 [Testing Guide](TESTING_GUIDE.md)
- 🐛 [Report Issues](../../issues/new)

### Support
1. Check workflow logs in Actions tab
2. Review PR description for analysis
3. Search existing issues
4. Create new issue with `auto-healing` label
5. Contact maintainers

## Quick Reference

### Useful Commands

```bash
# View latest auto-healing runs
gh run list -w "Copilot Agent Auto-Healing" -L 5

# Trigger for specific workflow
gh workflow run copilot-agent-autofix.yml -f workflow_name="CI Tests"

# List auto-healing PRs
gh pr list -l auto-healing

# View specific PR details
gh pr view 123 --json state,reviews,checks

# Check Copilot's commits
gh pr view 123 --json commits

# Monitor PR status
gh pr checks 123

# Review PR locally
gh pr checkout 123
```

### GitHub UI Navigation

1. **View Runs**: Actions → Copilot Agent Auto-Healing
2. **Trigger Manual**: Actions → Copilot Agent Auto-Healing → Run workflow
3. **View PRs**: Pull requests → Labels → auto-healing
4. **View Logs**: Actions → Select run → View logs
5. **Check Status**: PR → Checks tab

## Success Metrics

Track your auto-healing effectiveness:

```bash
# Calculate success rate
python .github/scripts/analyze_autohealing_metrics.py

# View merged auto-healing PRs
gh pr list -l auto-healing -s closed --json number,mergedAt

# Count fixes by type
gh pr list -l auto-healing --json labels | jq '.[] | .labels[].name' | sort | uniq -c
```

## What's Next?

Now that you understand the basics:

1. ✅ **Let it run**: System works automatically
2. 📊 **Monitor results**: Check PR success rate
3. 🔧 **Review PRs**: Always validate before merge
4. 📈 **Track metrics**: Measure effectiveness
5. 💬 **Provide feedback**: Help improve patterns
6. 📚 **Read full docs**: Learn advanced features

## Advanced Usage

Want to go deeper? Check out:

- [Full Documentation](README-copilot-autohealing.md) - Complete guide
- [Custom Patterns](README-copilot-autohealing.md#custom-error-patterns) - Add new error types
- [Metrics Analysis](README-copilot-autohealing.md#monitoring) - Track success
- [Configuration](README-copilot-autohealing.md#configuration) - Customize behavior

---

**Questions?** Open an issue or contact maintainers!

**Happy Auto-Healing! 🤖✨**
