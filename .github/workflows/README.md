# GitHub Actions Workflows - Automated Development System

This directory contains all GitHub Actions workflows for the repository, including the **Auto-Healing System** and **Issue-to-Draft-PR System** that automatically resolve issues using GitHub Copilot Agent.

## 📋 Workflow Improvement Plan (2026 Update)

**🎉 NEW COMPREHENSIVE PLAN (2026-02-16):** Complete analysis and improvement roadmap created!

### Current Status: 53 Workflows, 279 Issues Identified

**Previous Achievements (Phases 1-3):**
- ✅ **Phase 1: Infrastructure & Reliability** (40h) - Runner gating, Python 3.12, action updates
- ✅ **Phase 2: Consolidation & Optimization** (30h) - Unified workflows, 2,385 lines eliminated
- ✅ **Phase 3: Security & Best Practices** (24h) - Explicit permissions, security scanner, secrets audit

**Current State:**
- **Total Workflows:** 53 active
- **Total Issues:** 279 (50 critical, 42 high, 41 medium, 117 low)
- **Health Score:** 96/100 (Grade A+)
- **Auto-fixable:** 36 issues

### 📦 NEW Comprehensive Improvement Plan (2026-02-16)

**Start Here:** 📖 **[Improvement Plan Summary](IMPROVEMENT_PLAN_SUMMARY_2026_02_16.md)** - Overview and entry point (8KB)

**Complete Documentation Package (4 documents, 60KB total):**

1. 📊 **[Comprehensive Plan](COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md)** - Full details, 6 phases, 60 hours (20KB)
   - Complete workflow inventory (53 workflows, 7 categories)
   - Detailed validation results (279 issues)
   - Implementation strategy and budget ($8,200)
   - Risk assessment and ROI analysis

2. ⚡ **[Quick Reference](IMPROVEMENT_PLAN_QUICK_REFERENCE_2026_02_16.md)** - Day-to-day reference (11KB)
   - Top 5 priorities (Week 1)
   - Quick commands and fix patterns
   - 5-week timeline
   - Tips and best practices

3. ✅ **[Implementation Checklist](IMPLEMENTATION_CHECKLIST_2026_02_16.md)** - Task tracking (17KB)
   - Detailed task breakdown by phase
   - Time estimates and acceptance criteria
   - Step-by-step instructions
   - Progress tracking

4. 📝 **[Summary Document](IMPROVEMENT_PLAN_SUMMARY_2026_02_16.md)** - This overview (8KB)
   - Executive summary
   - Quick start guide
   - Key statistics

### 🎯 Implementation Phases (5 weeks, 60 hours)

- 🔴 **Phase 1: Critical Security Fixes** (8h) - Missing triggers, permissions
- 🟠 **Phase 2: Security Hardening** (12h) - Fix 48 injection vulnerabilities
- 🟡 **Phase 3: Reliability** (16h) - Timeouts, retry logic, error handling
- 🔵 **Phase 4: Performance** (12h) - Caching, checkout optimization
- ⚪ **Phase 5: Documentation** (8h) - Workflow catalog, updates
- 🟢 **Phase 6: Validation** (8h) - Final sweep, health report

**Target State:**
- ✅ 0 critical issues (from 50)
- ✅ <5 high issues (from 42)
- ✅ <10 medium issues (from 41)
- ✅ Health score 98+ (from 96)
- ✅ 20-30% faster workflows

### Previous Plans (Historical Reference)

- 📖 **[Previous Comprehensive Plan 2026](COMPREHENSIVE_IMPROVEMENT_PLAN_2026.md)** - Phases 4-6 (21KB)
- 📊 **[Current State Assessment](CURRENT_STATE_ASSESSMENT_2026.md)** - Detailed analysis
- 🎯 **[Implementation Roadmap 2026](IMPLEMENTATION_ROADMAP_2026.md)** - Week-by-week plan
- ⚡ **[Quick Wins 2026](IMPROVEMENT_QUICK_WINS_2026.md)** - Fast improvements
- 📖 **[Original Plan](COMPREHENSIVE_IMPROVEMENT_PLAN.md)** - Initial 6-phase plan (34KB)

**Status:** ✅ Phases 1-3 Complete (94h) | 📋 NEW Plan Ready (60h remaining)  
**Priority:** HIGH | **Timeline:** 5 weeks from start

---

## 🚨 IMPORTANT: Self-Hosted Runner Authentication

**If workflows are failing with authentication errors**, you need to configure persistent GitHub CLI authentication on your self-hosted runners.

### Quick Fix

```bash
# On your self-hosted runner machine:
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh
```

📚 **See:** [RUNNER_AUTH_QUICKSTART.md](../../RUNNER_AUTH_QUICKSTART.md) for details

This configures:
- ✅ Persistent GitHub CLI authentication
- ✅ Copilot CLI extension (`gh agent-task` support)
- ✅ Git credential helper
- ✅ Works across reboots and workflow runs

---

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

## 🔍 PR Copilot Reviewer System (Automatic PR Assignment)

### What is it?

The PR Copilot Reviewer System automatically assigns GitHub Copilot to review and implement changes for pull requests:
1. **Detects** when a PR is opened, reopened, or marked ready for review
2. **Analyzes** the PR content, title, and description
3. **Determines** the appropriate task type (fix, implement, or review)
4. **Assigns** GitHub Copilot with targeted instructions via @mention
5. **Integrates** with the auto-healing system for workflow fix PRs

**Key Innovation**: Every PR gets automatic Copilot assignment with context-aware instructions!

### How It Works

```
PR Created/Updated → Content Analysis → Task Classification → @copilot Mentioned → Implementation/Review
```

### Task Types

The system intelligently assigns Copilot with different instructions based on PR characteristics:

- **Fix Task** (`@copilot /fix`): For auto-generated workflow fixes or bug fix PRs
- **Implement Task** (`@copilot`): For draft PRs needing implementation
- **Review Task** (`@copilot /review`): For completed PRs needing code review

### Integration with Auto-Healing

The PR Copilot Reviewer is **monitored by the auto-healing system** (#2 in the monitored list), ensuring:
- If the reviewer workflow fails, auto-healing creates a fix PR
- The fix PR gets Copilot assigned automatically
- Creates a self-healing loop for the automation system

### All Workflows Monitored (17 Total)

The auto-healing system monitors **every workflow** in this repository:
- ARM64 Self-Hosted Runner
- **Automated PR Review and Copilot Assignment** ⭐ NEW
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

#### PR Copilot Reviewer System
- **[Workflow File](pr-copilot-reviewer.yml)** - The workflow definition
- **[Copilot Integration](COPILOT-INTEGRATION.md)** - Integration documentation

## Workflows Overview

### Auto-Healing & Automation Workflows

| Workflow | Purpose | Status | Trigger |
|----------|---------|--------|---------|
| [issue-to-draft-pr.yml](issue-to-draft-pr.yml) | **Convert ALL issues to draft PRs with Copilot** | ✅ Active | On issue created/reopened |
| [pr-copilot-reviewer.yml](pr-copilot-reviewer.yml) | **Auto-assign Copilot to PRs for review/implementation** | ✅ Active | On PR opened/reopened/ready_for_review |
| [copilot-agent-autofix.yml](copilot-agent-autofix.yml) | **Auto-healing with Copilot Agent** | ✅ Active | On any workflow failure (17 monitored) |
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
Copilot CLI Invocation (NEW!)
      ↓
Copilot Implements Fix
      ↓
Tests Validate
      ↓
Ready for Review
```

**Note**: The system now uses the `invoke_copilot_on_pr.py` CLI tool to programmatically trigger GitHub Copilot, replacing manual @mentions. See [COPILOT-CLI-INTEGRATION.md](./COPILOT-CLI-INTEGRATION.md) for details.

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

## Best Practices for Workflow Automation

### Invoking GitHub Copilot Coding Agent

**✅ Recommended Approach**: Use `gh agent-task create`

```yaml
- name: Create Copilot Coding Agent Task
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    # Create agent task with comprehensive description
    gh agent-task create "Fix the failing Docker build by updating Dockerfile permissions" --base main
    
    # Or use a file for complex instructions
    cat > task.txt << 'EOF'
    Fix the test failures in tests/test_utils.py:
    1. Analyze the failing test assertions
    2. Identify the root cause
    3. Implement minimal fixes
    4. Ensure all tests pass
    EOF
    gh agent-task create -F task.txt
```

**❌ Deprecated**: `@copilot` mentions in comments

- `@copilot` mentions are for interactive UI use, not automation
- Use `gh agent-task create` for programmatic workflows
- See [COPILOT-CLI-INTEGRATION.md](./COPILOT-CLI-INTEGRATION.md) for migration guide

### Monitoring Agent Tasks

```bash
# List active agent tasks
gh agent-task list --limit 20

# View specific task
gh agent-task view <session-id>

# Follow agent logs
gh agent-task create "task description" --follow
```

### Workflow Configuration

```yaml
# Always set GH_TOKEN for gh CLI commands
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

# Use container isolation for self-hosted runners (recommended)
jobs:
  my-job:
    runs-on: [self-hosted, linux, x64]
    container:
      image: python:3.12-slim
      options: --user root
```

---

## Quick Links

### Workflow Improvement Plan
- 📋 [Comprehensive Improvement Plan](COMPREHENSIVE_IMPROVEMENT_PLAN.md) - Full 6-phase plan
- ⚡ [Quick Reference Guide](IMPROVEMENT_QUICK_REFERENCE.md) - Quick wins and critical issues
- ✅ [Implementation Checklist](IMPLEMENTATION_CHECKLIST.md) - Detailed task breakdown

### Auto-Healing System
- 📖 [Full Documentation](README-copilot-autohealing.md)
- 🚀 [Quickstart Guide](QUICKSTART-copilot-autohealing.md)
- ⚙️ [Configuration](workflow-auto-fix-config.yml)
- 📊 [View Metrics](../scripts/analyze_autohealing_metrics.py)
- 🔍 [View Auto-Healing PRs](../../pulls?q=is%3Apr+label%3Aauto-healing)
- 🤖 [Copilot CLI Integration](./COPILOT-CLI-INTEGRATION.md)

### Architecture & Maintenance
- 🏗️ [Architecture Overview](ARCHITECTURE.md)
- 🔧 [Maintenance Guide](MAINTENANCE.md)
- 🔐 [Secrets Management](SECRETS-MANAGEMENT.md)
- 🧪 [Testing Guide](TESTING_GUIDE.md)

---

**Auto-Healing: Making workflows maintain themselves.** 🤖✨🚀
