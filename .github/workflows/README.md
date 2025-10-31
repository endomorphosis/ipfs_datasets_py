# GitHub Actions Workflows - Automated Development System

This directory contains all GitHub Actions workflows for the repository, including the **Auto-Healing System** and **Issue-to-Draft-PR System** that automatically resolve issues using GitHub Copilot Agent.

## 🎯 Automation Overview

This repository features **two complementary automation systems**:

### 1. 🔧 Auto-Healing System (Reactive)
Automatically fixes workflow failures

### 2. 📝 Issue-to-Draft-PR System (Proactive)
Automatically converts **every GitHub issue** into a draft PR with Copilot assigned

## 🤖 Auto-Healing System (Workflow Failures)

### What is it?

The Auto-Healing System is an advanced workflow maintenance solution that:
1. **Detects** workflow failures automatically across **ALL 16 workflows**
2. **Analyzes** the root cause using pattern matching
3. **Creates issues** with detailed failure logs and analysis
4. **Creates draft PRs** linked to the issues
5. **Uses GitHub Copilot Agent** to implement fixes automatically
6. **Requires human review** only for final PR merge

**Key Innovation**: Fully automated from detection to fix implementation! Human intervention only needed for review and merge.

## 📝 Issue-to-Draft-PR System (All Issues)

### What is it?

The Issue-to-Draft-PR System automatically converts **every GitHub issue** into actionable code:
1. **Detects** when any issue is created or reopened
2. **Analyzes** the issue content and categorizes it
3. **Creates a branch** with sanitized naming
4. **Creates a draft PR** linked to the issue
5. **Assigns GitHub Copilot** to implement the solution
6. **Links everything** back to the original issue

**Key Innovation**: Turn every issue into a PR automatically! Zero manual setup required.

### How Auto-Healing Works

```
Workflow Fails → Issue Created → Draft PR Created → @copilot Implements Fix → Human Reviews & Merges
```

**100% Automated** until the review step!

### How Issue-to-Draft-PR Works

```
Issue Created/Reopened → Analysis → Branch Created → Draft PR Created → @copilot Implements → Ready for Review
```

**100% Automated** until the review step!

### Combined Power

When used together:
- **Workflow failures** → Auto-healing creates issue → Issue-to-PR creates draft PR → Copilot fixes
- **User issues** → Issue-to-PR creates draft PR → Copilot implements → Ready for review
- **Result**: Near-zero manual issue management!

### Quick Start (Auto-Healing)

The auto-healing system is already configured and active. When a workflow fails:
1. ✅ **Auto-healing automatically detects it** (within seconds)
2. ✅ **Issue is created** with logs and analysis
3. ✅ **Draft PR is created** with fix instructions
4. ✅ **GitHub Copilot Agent implements the fix** (mentioned via @copilot)
5. ✅ **Tests validate the fix** automatically
6. 👤 **You review and merge** the PR

**No manual intervention required until step 6!**

### Quick Start (Issue-to-Draft-PR)

The issue-to-PR system activates automatically. When any issue is created:
1. ✅ **System detects the issue** (within seconds)
2. ✅ **Branch is created** with clean naming
3. ✅ **Draft PR is created** and linked to issue
4. ✅ **GitHub Copilot is assigned** via @mention
5. ✅ **Copilot implements the solution**
6. 👤 **You review and merge** the PR

**No manual intervention required until step 6!**

### All Workflows Monitored (16 Total)

The auto-healing system monitors **every workflow** in this repository:
- ARM64 Self-Hosted Runner
- Comprehensive Scraper Validation
- Docker Build and Test (2 variants)
- Documentation Maintenance
- GPU-Enabled Tests
- GraphRAG Production CI/CD
- MCP Dashboard & Integration Tests (2 workflows)
- PDF Processing (2 workflows)
- Publish Python Package
- Runner Validation (3 workflows)
- Scraper Validation and Testing

📝 **This list is automatically updated** when workflows are added/removed!

### Documentation

#### Auto-Healing System
- **[Complete Auto-Healing Guide](AUTO_HEALING_GUIDE.md)** - Full documentation ⭐
- **[Quickstart Guide](QUICKSTART-copilot-autohealing.md)** - Get started in 5 minutes
- **[Copilot Integration Docs](README-copilot-autohealing.md)** - How Copilot Agent works
- **[Configuration](workflow-auto-fix-config.yml)** - Customize behavior

#### Issue-to-Draft-PR System
- **[Complete Issue-to-PR Guide](README-issue-to-draft-pr.md)** - Full documentation ⭐
- **[Quickstart Guide](QUICKSTART-issue-to-draft-pr.md)** - Get started in 5 minutes
- **[Workflow File](issue-to-draft-pr.yml)** - The workflow definition

## Workflows Overview

### Auto-Healing & Automation Workflows

| Workflow | Purpose | Status | Trigger |
|----------|---------|--------|---------|
| [issue-to-draft-pr.yml](issue-to-draft-pr.yml) | **Convert ALL issues to draft PRs with Copilot** | ✅ Active | On issue created/reopened |
| [copilot-agent-autofix.yml](copilot-agent-autofix.yml) | **Auto-healing with Copilot Agent** | ✅ Active | On any workflow failure |
| [update-autohealing-list.yml](update-autohealing-list.yml) | **Auto-update monitored workflows** | ✅ Active | On workflow file changes |
| [enhanced-autohealing.yml](enhanced-autohealing.yml) | Enhanced auto-healing | ⛔ Disabled | Used unsupported wildcard |
| [workflow-auto-fix.yml](workflow-auto-fix.yml) | Legacy auto-fix system | ⛔ Disabled | Superseded by copilot-agent |

### CI/CD Workflows

| Workflow | Purpose |
|----------|---------|
| [docker-build-test.yml](docker-build-test.yml) | Docker image build and testing |
| [docker-ci.yml](docker-ci.yml) | Docker CI pipeline |
| [pdf_processing_ci.yml](pdf_processing_ci.yml) | PDF processing pipeline |
| [graphrag-production-ci.yml](graphrag-production-ci.yml) | GraphRAG production tests |
| [mcp-integration-tests.yml](mcp-integration-tests.yml) | MCP integration tests |
| [mcp-dashboard-tests.yml](mcp-dashboard-tests.yml) | MCP dashboard tests |
| [gpu-tests.yml](gpu-tests.yml) | GPU-specific tests |

### Infrastructure Workflows

| Workflow | Purpose |
|----------|---------|
| [self-hosted-runner.yml](self-hosted-runner.yml) | Self-hosted runner setup |
| [arm64-runner.yml](arm64-runner.yml) | ARM64 runner configuration |
| [runner-validation.yml](runner-validation.yml) | Runner validation |
| [test-datasets-runner.yml](test-datasets-runner.yml) | Dataset testing runner |

### Maintenance Workflows

| Workflow | Purpose |
|----------|---------|
| [documentation-maintenance.yml](documentation-maintenance.yml) | Auto-update documentation |
| [publish_to_pipy.yml](publish_to_pipy.yml) | PyPI package publishing |

## Auto-Healing Features

### Supported Fix Types

- ✅ **Dependency Errors** (90% confidence) - Missing packages, import errors
- ✅ **Timeout Issues** (95% confidence) - Job/step timeouts
- ✅ **Permission Errors** (80% confidence) - Access denied, 403s
- ✅ **Docker Errors** (85% confidence) - Build failures, daemon issues
- ✅ **Network Errors** (75% confidence) - Connection failures
- ✅ **Resource Exhaustion** (90% confidence) - Out of memory, disk full
- ✅ **Test Failures** (70% confidence) - Assertion errors, test timeouts
- ✅ **Syntax Errors** (85% confidence) - YAML syntax, indentation

### How It Works

```
Workflow Failure
      ↓
Auto-Detection
      ↓
Log Analysis
      ↓
Root Cause ID
      ↓
Fix Proposal
      ↓
PR Creation
      ↓
@copilot Mention
      ↓
Copilot Implements Fix
      ↓
Tests Validate
      ↓
Ready for Review
```

## Usage

### Automatic (Default)

Just let it work! When workflows fail, auto-healing kicks in automatically.

### Manual Trigger

```bash
# Fix latest failure of a workflow
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Docker Build and Test"

# Fix specific run
gh workflow run copilot-agent-autofix.yml \
  --field run_id="1234567890"
```

### Monitor Activity

```bash
# List auto-healing PRs
gh pr list --label "auto-healing"

# View auto-healing runs
gh run list --workflow="Copilot Agent Auto-Healing"

# Check metrics
python .github/scripts/analyze_autohealing_metrics.py
```

## Configuration

Edit [workflow-auto-fix-config.yml](workflow-auto-fix-config.yml) to customize:

```yaml
# Enable/disable
enabled: true

# Confidence thresholds
min_confidence_for_pr: 70

# Exclude workflows
excluded_workflows:
  - "Deploy to Production"

# Copilot Agent settings
copilot:
  enabled: true
  use_agent_mode: true
  auto_mention: true
```

## Monitoring

### View Activity

```bash
# Auto-healing PRs
gh pr list --label "auto-healing"

# Recent runs
gh run list --workflow="Copilot Agent Auto-Healing" --limit 10

# Success metrics
python .github/scripts/analyze_autohealing_metrics.py
```

### Artifacts

Each auto-healing run creates artifacts:
- `copilot-autofix-{run_id}/`
  - `workflow_logs/` - Downloaded failure logs
  - `failure_analysis.json` - Analysis results
  - `fix_proposal.json` - Fix proposal
  - `.github/copilot-tasks/` - Copilot task files

Download with:
```bash
gh run download {run_id} -n copilot-autofix-{run_id}
```

## Examples

### Example 1: Missing Dependency

**Before (Manual Fix):**
1. Workflow fails with `ModuleNotFoundError`
2. Developer investigates logs
3. Identifies missing package
4. Creates PR to add package
5. Reviews and merges
⏱️ **Time: 30-60 minutes**

**After (Auto-Healing):**
1. Workflow fails with `ModuleNotFoundError`
2. Auto-healing detects and analyzes
3. PR created with fix
4. Copilot implements fix
5. Developer reviews and merges
⏱️ **Time: 2-5 minutes**

### Example 2: Timeout

**Failure:**
```
Job exceeded timeout (5 minutes)
```

**Auto-Healing:**
- Detects timeout issue (95% confidence)
- Proposes increasing to 30 minutes
- Copilot updates workflow YAML
- Tests validate fix
- Ready to merge

⏱️ **Time: ~2 minutes**

## Troubleshooting

### No PR Created?

Check:
1. Confidence score in artifacts
2. Workflow not excluded
3. Permissions correct
4. Rate limits not hit

### Copilot Didn't Implement?

Check:
1. Copilot enabled for repo
2. @copilot mentioned in PR
3. Task file created
4. PR complexity reasonable

### Fix Didn't Work?

1. Review Copilot's implementation
2. Check test results
3. Close PR and investigate
4. Update error patterns
5. Report issue for improvement

## Best Practices

### ✅ Do's

- Review all auto-healed PRs before merging
- Monitor success rate regularly
- Provide feedback on fixes
- Update patterns for new errors
- Keep confidence thresholds appropriate

### ❌ Don'ts

- Don't auto-merge without review
- Don't ignore test failures
- Don't skip security checks
- Don't disable for critical workflows without reason

## Contributing

### Add New Error Patterns

Edit `.github/scripts/analyze_workflow_failure.py`:

```python
'new_error': {
    'patterns': [r'your pattern here'],
    'error_type': 'Error Name',
    'fix_type': 'fix_type',
    'confidence': 85,
}
```

### Add Fix Generators

Edit `.github/scripts/generate_workflow_fix.py`:

```python
def _fix_new_error(self) -> List[Dict[str, Any]]:
    return [{
        'file': 'path/to/file',
        'action': 'your_action',
        'changes': {...},
    }]
```

## Security

### What Auto-Healing Does

- ✅ Creates branches (non-protected)
- ✅ Commits fixes (via Copilot)
- ✅ Creates PRs (requires review)
- ✅ Analyzes logs (read-only)

### What It Doesn't Do

- ❌ Auto-merge PRs
- ❌ Modify secrets
- ❌ Bypass branch protection
- ❌ Execute arbitrary code in main

### Safety Features

- All changes go through PRs
- Requires CI/CD validation
- Human review before merge
- Rate limiting prevents spam
- Audit trail in PR history

## Metrics

Track effectiveness:

```bash
# Get metrics report
python .github/scripts/analyze_autohealing_metrics.py

# Export to JSON
python .github/scripts/analyze_autohealing_metrics.py --json metrics.json

# Recent activity only
python .github/scripts/analyze_autohealing_metrics.py --days 7
```

## Support

### Documentation

- [Auto-Healing Guide](README-copilot-autohealing.md)
- [Quickstart](QUICKSTART-copilot-autohealing.md)
- [Configuration](workflow-auto-fix-config.yml)
- [Scripts Documentation](.github/scripts/README.md)

### Getting Help

1. Check workflow logs
2. Review artifacts
3. Search existing issues
4. Create issue with `auto-healing` label

## Resources

- [GitHub Actions Docs](https://docs.github.com/actions)
- [GitHub Copilot Docs](https://docs.github.com/copilot)
- [Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)

## Changelog

### v2.0.0 (2025-10-29)

- 🚀 **Auto-Healing System** with Copilot Agent
- 🤖 Automatic fix implementation
- ✨ No manual label required
- 📝 Detailed Copilot task files
- 🔄 Self-healing workflow loop
- 📊 Enhanced metrics and monitoring

### v1.0.0

- ✅ Basic auto-fix system
- ✅ Pattern-based detection
- ✅ Fix proposals
- ✅ Manual implementation required

---

## Quick Links

- 📖 [Full Documentation](README-copilot-autohealing.md)
- 🚀 [Quickstart Guide](QUICKSTART-copilot-autohealing.md)
- ⚙️ [Configuration](workflow-auto-fix-config.yml)
- 📊 [View Metrics](../scripts/analyze_autohealing_metrics.py)
- 🔍 [View Auto-Healing PRs](../../pulls?q=is%3Apr+label%3Aauto-healing)

---

**Auto-Healing: Making workflows maintain themselves.** 🤖✨🚀
