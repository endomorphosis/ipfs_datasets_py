# GitHub Actions Workflows - Auto-Healing System

This directory contains all GitHub Actions workflows for the repository, including the **Auto-Healing System** that automatically fixes failed workflows using GitHub Copilot Agent.

## 🤖 Auto-Healing System

### What is it?

The Auto-Healing System is an advanced workflow maintenance solution that:
1. **Detects** workflow failures automatically
2. **Analyzes** the root cause using pattern matching
3. **Proposes** fixes with confidence scores
4. **Uses GitHub Copilot Agent** to implement fixes automatically
5. **Creates PRs** ready for review and merge

**Key Innovation**: No manual label required! Copilot Agent is automatically invoked to implement fixes.

### Quick Start

The system is already configured and active. When a workflow fails:
1. Auto-healing automatically detects it
2. Analysis runs and identifies the issue
3. A PR is created with the fix proposal
4. GitHub Copilot Agent is mentioned and implements the fix
5. Tests validate the fix
6. You review and merge

**No manual intervention required!**

### Documentation

- **[Quickstart Guide](QUICKSTART-copilot-autohealing.md)** - Get started in 5 minutes
- **[Full Documentation](README-copilot-autohealing.md)** - Complete guide
- **[Configuration](workflow-auto-fix-config.yml)** - Customize behavior

## Workflows Overview

### Auto-Healing Workflows

| Workflow | Purpose | Trigger |
|----------|---------|---------|
| [copilot-agent-autofix.yml](copilot-agent-autofix.yml) | **Auto-healing with Copilot Agent** | On workflow failure |
| [workflow-auto-fix.yml](workflow-auto-fix.yml) | Manual auto-fix system | On workflow failure / manual |

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
