# Workflow Auto-Fix System - Quick Start Guide

## 🚀 Getting Started in 5 Minutes

### What Is This?

An automated system that:
1. **Detects** when your GitHub Actions workflows fail
2. **Analyzes** the failure to find the root cause
3. **Generates** a fix proposal
4. **Creates** a pull request with the fix
5. **Tags** it for GitHub Copilot to review
6. **Waits** for your approval before merging

## ⚡ Quick Start

### Option 1: Let It Run Automatically

**No setup needed!** The system is already active and monitoring all workflows.

When a workflow fails:
1. Wait ~2 minutes for analysis
2. Check for new PR with label `automated-fix`
3. Review the fix
4. Approve and merge if correct

### Option 2: Test It Manually

```bash
# Create a test failure (safe, won't break anything)
gh workflow run workflow-auto-fix.yml \
  --field workflow_name="Test Workflow" \
  --field create_pr=false

# View the analysis
gh run view --log
```

### Option 3: Run the Test Suite

```bash
# Run comprehensive tests
./.github/scripts/test_autofix_system.sh

# Check results
ls -la /tmp/workflow_autofix_test/
```

## 📋 What Can It Fix?

| Error Type | Example | Confidence | Auto-Apply |
|------------|---------|------------|------------|
| Missing Dependencies | `ModuleNotFoundError` | 90% | ✅ Yes |
| Timeouts | Job exceeded time limit | 95% | ✅ Yes |
| Permissions | 403 Forbidden | 80% | ✅ Yes |
| Network Errors | Connection failed | 75% | ⚠️ Review |
| Docker Issues | Build failed | 85% | ⚠️ Review |
| Memory/Disk | Out of memory | 90% | ✅ Yes |
| Env Variables | Variable not set | 95% | ⚠️ Review |
| Syntax Errors | Invalid YAML | 85% | ⚠️ Review |
| Test Failures | Tests failed | 70% | ⚠️ Review |

## 🎯 Common Scenarios

### Scenario 1: Missing Python Package

**What happens:**
```
❌ Workflow fails: ModuleNotFoundError: No module named 'pytest-asyncio'
🤖 System detects failure
🔍 Analyzes: Missing dependency detected (90% confidence)
🔧 Generates fix:
   - Add to requirements.txt
   - Add pip install step
🔀 Creates PR with both changes
```

**Your action:** Review and merge PR

### Scenario 2: Timeout

**What happens:**
```
❌ Workflow fails: Job exceeded timeout of 5 minutes
🤖 System detects failure
🔍 Analyzes: Timeout detected (95% confidence)
🔧 Generates fix:
   - Increase timeout to 30 minutes
🔀 Creates PR with change
```

**Your action:** Review and merge PR (or adjust timeout further)

### Scenario 3: Permission Error

**What happens:**
```
❌ Workflow fails: Resource not accessible by integration
🤖 System detects failure
🔍 Analyzes: Permission error (80% confidence)
🔧 Generates fix:
   - Add permissions block to workflow
🔀 Creates PR with changes
```

**Your action:** Review permissions and merge

## 🔧 Configuration

### Enable/Disable for Specific Workflows

Edit `.github/workflows/workflow-auto-fix-config.yml`:

```yaml
# Only monitor these workflows
monitored_workflows:
  - "Docker Build and Test"
  - "PDF Processing"

# OR exclude specific ones
excluded_workflows:
  - "Deploy Production"
```

### Adjust Confidence Thresholds

```yaml
# Only create PRs for fixes with 85%+ confidence
min_confidence_for_pr: 85

# Per-fix-type thresholds
fix_types:
  add_dependency:
    confidence_threshold: 85
    auto_apply: true
  
  fix_test:
    confidence_threshold: 60
    auto_apply: false  # Always requires review
```

### Disable Auto-Fix

```yaml
# Completely disable
enabled: false

# OR disable PR creation (analysis only)
auto_create_pr: false
```

## 📊 Monitoring

### Check Recent Auto-Fix PRs

```bash
# List auto-generated PRs
gh pr list --label "automated-fix"

# View specific PR
gh pr view 123
```

### Check Workflow Runs

```bash
# List auto-fix runs
gh run list --workflow="Workflow Auto-Fix System"

# View specific run
gh run view 12345 --log
```

### View Artifacts

```bash
# Download analysis artifacts
gh run download 12345

# View analysis
cat workflow-autofix-12345/failure_analysis.json | jq
```

## 🐛 Troubleshooting

### PR Not Created

**Check:**
1. Is confidence above threshold? (default: 70%)
2. Is workflow excluded in config?
3. Check workflow logs for errors

**Fix:**
```bash
# Manually trigger
gh workflow run workflow-auto-fix.yml \
  --field workflow_name="Your Workflow"
```

### Wrong Fix Applied

**Check:**
1. Review pattern matching in analyzer
2. Check captured values in analysis

**Fix:**
1. Close PR
2. Add custom pattern in config
3. Re-run workflow

### Copilot Not Reviewing

**Check:**
1. Is `copilot-ready` label applied?
2. Is Copilot enabled for repo?
3. Check PR size (too large?)

**Fix:**
- Verify labels on PR
- Check repository settings
- Split into smaller PRs if needed

## 📚 More Information

- **Full Documentation**: `.github/workflows/README-workflow-auto-fix.md`
- **Scripts Documentation**: `.github/scripts/README.md`
- **Configuration Reference**: `.github/workflows/workflow-auto-fix-config.yml`
- **Test Suite**: `.github/scripts/test_autofix_system.sh`

## 🤔 FAQ

**Q: Will it auto-merge fixes?**
A: No, all PRs require manual review and approval.

**Q: What if the fix is wrong?**
A: Close the PR and fix manually. Consider updating patterns.

**Q: Can I customize the fixes?**
A: Yes, edit the generator and applier scripts.

**Q: How do I add new error patterns?**
A: Edit `analyze_workflow_failure.py` and add to `FAILURE_PATTERNS`.

**Q: Does it work with private repos?**
A: Yes, requires appropriate permissions.

**Q: Can I disable it temporarily?**
A: Yes, set `enabled: false` in config.

## 💡 Tips

1. **Start Small**: Monitor first few PRs carefully
2. **Adjust Thresholds**: Tune confidence levels based on results
3. **Add Patterns**: Add project-specific error patterns
4. **Track Success**: Monitor which fix types work best
5. **Keep Updated**: Update patterns as errors evolve

## 🎉 Success!

You're now ready to use the Workflow Auto-Fix System!

Next time a workflow fails, check for the auto-generated PR and review the proposed fix.

Happy fixing! 🚀
