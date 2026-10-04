# GitHub Actions Testing Framework Guide

**Version:** 1.0  
**Last Updated:** 2026-02-16  
**Maintainer:** DevOps Team

## Overview

This guide documents the comprehensive testing framework for GitHub Actions workflows in this repository. The framework provides multiple layers of testing to ensure workflow reliability, security, and performance.

---

## Table of Contents

1. [Testing Layers](#testing-layers)
2. [Validation System](#validation-system)
3. [Smoke Tests](#smoke-tests)
4. [Integration Tests](#integration-tests)
5. [CI Pipeline](#ci-pipeline)
6. [Running Tests](#running-tests)
7. [Interpreting Results](#interpreting-results)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)

---

## Testing Layers

Our testing framework consists of four complementary layers:

### 1. **Static Validation** (Enhanced Workflow Validator)
- **When:** On every PR and push
- **Purpose:** Catch syntax errors, security issues, and best practice violations
- **Duration:** ~2 minutes
- **Frequency:** Every workflow change

### 2. **Smoke Tests** (Workflow Smoke Tests)
- **When:** Every 6 hours (00:00, 06:00, 12:00, 18:00 UTC)
- **Purpose:** Detect infrastructure and availability issues
- **Duration:** ~5 minutes
- **Frequency:** 4 times per day

### 3. **Integration Tests** (Workflow Integration Tests)
- **When:** Weekly on Sundays, on-demand
- **Purpose:** Validate complex workflow interactions
- **Duration:** ~15 minutes
- **Frequency:** Weekly + manual triggers

### 4. **CI Validation** (Workflow Validation CI)
- **When:** On every PR affecting workflows
- **Purpose:** Enforce quality gates and block broken workflows
- **Duration:** ~3 minutes
- **Frequency:** Every PR

---

## Validation System

### Enhanced Workflow Validator

**Script:** `.github/scripts/enhanced_workflow_validator.py`

#### Features

- **10 Validation Categories:**
  1. Required fields (name, on, jobs)
  2. Explicit permissions (security)
  3. Concurrency control
  4. Job timeouts
  5. Checkout optimization (fetch-depth)
  6. Error handling and retry
  7. Security issues (injection risks, curl|sh)
  8. Performance (caching)
  9. Documentation
  10. Best practices

- **5 Severity Levels:**
  - 🔴 **Critical:** Must fix immediately (syntax errors, missing triggers)
  - 🟠 **High:** Should fix soon (security risks, missing permissions)
  - 🟡 **Medium:** Recommended (reliability, performance improvements)
  - 🔵 **Low:** Nice to have (optimizations)
  - ⚪ **Info:** Informational (documentation suggestions)

#### Usage

```bash
# Console output (default)
python .github/scripts/enhanced_workflow_validator.py

# JSON output
python .github/scripts/enhanced_workflow_validator.py --json report.json

# HTML output
python .github/scripts/enhanced_workflow_validator.py --html report.html

# Custom workflows directory
python .github/scripts/enhanced_workflow_validator.py --workflows-dir /path/to/workflows
```

#### Output Example

```
Validating Workflow: docker-build-test.yml

🟡 [MEDIUM] [performance]
  Missing checkout optimization. Consider adding fetch-depth: 1
  💡 Fix: Add 'fetch-depth: 1' to actions/checkout steps

🔵 [LOW] [performance]
  No dependency caching configured
  💡 Fix: Add actions/cache for pip/npm dependencies

Summary:
  Total Issues: 2
  Critical: 0, High: 0, Medium: 1, Low: 1, Info: 0
  Auto-fixable: 2 (100%)
```

#### Exit Codes

- `0` - All workflows valid, no critical issues
- `1` - Critical issues found
- `2` - Validation errors (file not found, YAML syntax)

---

## Smoke Tests

**Workflow:** `.github/workflows/workflow-smoke-tests.yml`

### Purpose

Continuously monitor the health of critical workflows and infrastructure. Runs every 6 hours to detect issues before they impact development.

### Test Suites

#### 1. Infrastructure Availability
Tests external dependencies and services:
- GitHub API status
- GitHub-hosted runner availability
- Docker Hub connectivity
- PyPI connectivity
- GitHub Actions cache functionality

#### 2. Critical Workflow Syntax
Validates YAML syntax of critical workflows:
- docker-build-test.yml
- graphrag-production-ci.yml
- mcp-integration-tests.yml
- gpu-tests-gated.yml
- copilot-agent-autofix.yml
- pdf_processing_ci.yml
- workflow-validation-ci.yml

#### 3. Workflow Triggers
Verifies trigger mechanisms are working:
- workflow_dispatch (manual triggers)
- schedule (cron-based)
- push (code changes)

### Manual Trigger

```bash
# Trigger via GitHub UI
# Go to Actions → Workflow Smoke Tests → Run workflow

# Or via GitHub CLI
gh workflow run workflow-smoke-tests.yml

# With specific test level
gh workflow run workflow-smoke-tests.yml -f test_level=comprehensive
```

### Failure Handling

When smoke tests fail on the main branch:
1. Automatic GitHub issue is created
2. Issue includes test results and run link
3. Labels: `workflow-health`, `automated`, `smoke-test-failure`
4. Immediate notification to maintainers

---

## Integration Tests

**Workflow:** `.github/workflows/workflow-integration-tests.yml`

### Purpose

Validate complex workflow interactions and patterns. Tests the integration points between workflows and verifies best practices are followed.

### Test Suites

#### 1. Workflow Trigger Chains
Tests trigger configurations:
- Push trigger detection
- Pull request trigger detection
- Schedule trigger detection
- workflow_dispatch detection
- Path filter verification

#### 2. Reusable Workflows
Tests workflow composition:
- Reusable workflow detection (workflow_call)
- Workflow calls (uses: ./.github/workflows/)
- Input/output definitions
- Secrets passing

#### 3. Concurrency Controls
Tests concurrency configurations:
- Concurrency group patterns
- cancel-in-progress usage
- Workflow queuing behavior

#### 4. Error Handling
Tests error handling patterns:
- Retry logic (nick-invision/retry@)
- continue-on-error usage
- Timeout configuration
- Error notification patterns

#### 5. Runner Gating
Tests runner configurations:
- Self-hosted runner usage
- GitHub-hosted runner usage
- Runner label patterns
- Fallback strategies

### Manual Trigger

```bash
# Run all tests
gh workflow run workflow-integration-tests.yml

# Run specific test suite
gh workflow run workflow-integration-tests.yml -f test_suite=triggers
gh workflow run workflow-integration-tests.yml -f test_suite=concurrency
gh workflow run workflow-integration-tests.yml -f test_suite=error-handling
```

### Interpreting Results

Each test suite runs independently and reports:
- ✅ **Success:** All checks passed
- ⚠️ **Warning:** Some issues detected but not critical
- ❌ **Failure:** Critical issues found

---

## CI Pipeline

**Workflow:** `.github/workflows/workflow-validation-ci.yml`

### Purpose

Automated validation on every PR to enforce quality gates and prevent broken workflows from being merged.

### Features

#### 1. Automated Validation
- Runs enhanced validator on all workflows
- Generates JSON and HTML reports
- Uploads artifacts (30-day retention)

#### 2. PR Comments
Adds detailed comment to PRs with:
- Summary of issues found
- Top 5 workflows with issues
- Critical and high-priority issues
- Fix suggestions
- Links to detailed reports

#### 3. Commit Status
Updates GitHub commit status:
- ✅ **Success:** No critical issues
- ⚠️ **Warning:** High-priority issues found
- ❌ **Failure:** Critical issues found (blocks merge)

#### 4. Issue Creation
On main branch, creates GitHub issue for:
- Critical issues detected
- Comprehensive issue summary
- Fix recommendations
- Links to workflow runs

### PR Comment Example

```markdown
## 🔍 Workflow Validation Report

### Summary
- **Total Workflows:** 48
- **Total Issues:** 12
- **Auto-fixable:** 8 (67%)

### Issues by Severity
- 🔴 **Critical:** 0
- 🟠 **High:** 2
- 🟡 **Medium:** 5
- 🔵 **Low:** 5

### Top Workflows with Issues

1. **docker-build-test.yml** (3 issues)
   - 🟠 Missing explicit permissions
   - 🟡 No checkout optimization
   - 🔵 Missing dependency caching

2. **graphrag-production-ci.yml** (2 issues)
   - 🟠 Potential injection risk
   - 🟡 Missing timeout on job

### ✅ Status: Success
All critical issues resolved. Please review high-priority issues.

📄 [View Full Report](link-to-artifact)
```

---

## Running Tests

### Local Testing

#### Validate Single Workflow
```bash
cd .github/scripts
python enhanced_workflow_validator.py --workflows-dir ../workflows
```

#### Validate Specific Workflow
```bash
python enhanced_workflow_validator.py --workflows-dir ../workflows \
  --workflow docker-build-test.yml
```

#### Generate HTML Report
```bash
python enhanced_workflow_validator.py --html validation-report.html
open validation-report.html  # macOS
xdg-open validation-report.html  # Linux
```

### CI Testing

#### Trigger Validation on PR
```bash
# Create PR with workflow changes
git checkout -b fix/workflow-improvements
git add .github/workflows/my-workflow.yml
git commit -m "Improve workflow configuration"
git push origin fix/workflow-improvements

# Create PR - validation runs automatically
gh pr create --title "Workflow improvements" --body "Updates to workflows"
```

#### Manual Validation Run
```bash
# Trigger validation CI manually
gh workflow run workflow-validation-ci.yml
```

### Smoke Testing

#### Wait for Scheduled Run
Smoke tests run automatically every 6 hours:
- 00:00 UTC
- 06:00 UTC
- 12:00 UTC
- 18:00 UTC

#### Manual Smoke Test
```bash
# Standard smoke test
gh workflow run workflow-smoke-tests.yml

# Comprehensive test
gh workflow run workflow-smoke-tests.yml -f test_level=comprehensive

# Minimal test
gh workflow run workflow-smoke-tests.yml -f test_level=minimal
```

### Integration Testing

#### Weekly Automatic Run
Integration tests run every Sunday at 02:00 UTC.

#### Manual Integration Test
```bash
# Run all integration tests
gh workflow run workflow-integration-tests.yml

# Run specific test suite
gh workflow run workflow-integration-tests.yml -f test_suite=concurrency
```

---

## Interpreting Results

### Validation Reports

#### Console Output
```
=== Workflow Validation Report ===
Total Workflows: 48
Valid Workflows: 46
Workflows with Issues: 2

Issues by Severity:
  Critical: 0
  High: 2
  Medium: 5
  Low: 8
  Info: 3

Auto-fixable Issues: 12 (67%)
```

#### JSON Output
```json
{
  "summary": {
    "total_workflows": 48,
    "valid_workflows": 46,
    "workflows_with_issues": 2,
    "total_issues": 18,
    "auto_fixable_issues": 12
  },
  "issues_by_severity": {
    "critical": 0,
    "high": 2,
    "medium": 5,
    "low": 8,
    "info": 3
  },
  "workflows": [...]
}
```

### Severity Interpretation

| Severity | Action Required | Timeline |
|----------|----------------|----------|
| 🔴 Critical | Must fix before merge | Immediate |
| 🟠 High | Should fix soon | Within 1 week |
| 🟡 Medium | Recommended | Within 2 weeks |
| 🔵 Low | Nice to have | When convenient |
| ⚪ Info | Informational | Optional |

---

## Troubleshooting

### Common Issues

#### Issue: Validator fails with "YAML syntax error"

**Cause:** Invalid YAML in workflow file

**Solution:**
```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/my-workflow.yml'))"

# Use online YAML validator
# https://www.yamllint.com/
```

#### Issue: Smoke tests fail with "GitHub API unavailable"

**Cause:** GitHub service degradation

**Solution:**
1. Check https://www.githubstatus.com/
2. Wait for service restoration
3. Re-run smoke tests

#### Issue: Integration tests fail with "No workflows found"

**Cause:** Workflows directory path issue

**Solution:**
```bash
# Verify workflows exist
ls -la .github/workflows/*.yml

# Check working directory
pwd
# Should be at repository root
```

#### Issue: CI validation blocks valid PR

**Cause:** False positive in validator

**Solution:**
1. Review validation report
2. If false positive, add exception to validator
3. Create issue for validator improvement
4. Override with manual approval if necessary

### Debug Mode

Enable verbose output:
```bash
# Enhanced validator with debug output
DEBUG=1 python .github/scripts/enhanced_workflow_validator.py

# Workflow with debug
# Add to workflow:
env:
  ACTIONS_STEP_DEBUG: true
  ACTIONS_RUNNER_DEBUG: true
```

---

## Best Practices

### For Workflow Authors

1. **Run Validation Locally** before pushing
   ```bash
   python .github/scripts/enhanced_workflow_validator.py
   ```

2. **Address Critical Issues** immediately
   - Fix syntax errors
   - Add required permissions
   - Fix security vulnerabilities

3. **Add Timeouts** to all jobs
   ```yaml
   jobs:
     my-job:
       timeout-minutes: 30
   ```

4. **Use Concurrency Controls** for expensive workflows
   ```yaml
   concurrency:
     group: ${{ github.workflow }}-${{ github.ref }}
     cancel-in-progress: true
   ```

5. **Optimize Checkout** for faster runs
   ```yaml
   - uses: actions/checkout@v5
     with:
       fetch-depth: 1
   ```

6. **Add Retry Logic** for flaky operations
   ```yaml
   - uses: nick-invision/retry@v3
     with:
       timeout_minutes: 10
       max_attempts: 3
       retry_on: error
       command: npm install
   ```

### For Reviewers

1. **Check Validation Report** on every PR
2. **Verify Fix Suggestions** are addressed
3. **Ensure No Security Issues** remain
4. **Confirm Timeouts** are appropriate
5. **Review Concurrency** settings

### For Maintainers

1. **Monitor Smoke Test Results** daily
2. **Review Integration Test** failures promptly
3. **Update Validator** for new patterns
4. **Maintain Documentation** current
5. **Track Metrics** over time

---

## Metrics & Monitoring

### Key Metrics

Track these metrics over time:

| Metric | Target | Current |
|--------|--------|---------|
| Workflows with timeouts | >90% | 85% |
| Workflows with concurrency | >20% | 12% |
| Workflows with retry | >10% | 6% |
| Critical issues | 0 | 0 |
| High-priority issues | <5 | 2 |
| Smoke test success rate | >95% | 98% |
| Integration test pass rate | >95% | 100% |

### Dashboards

- **Validation Dashboard:** View trends in validation results
- **Smoke Test Dashboard:** Monitor infrastructure health
- **Integration Test Dashboard:** Track complex scenarios

---

## Related Documentation

- [Comprehensive Improvement Plan](COMPREHENSIVE_IMPROVEMENT_PLAN_2026.md)
- [Error Handling Patterns](ERROR_HANDLING_PATTERNS_2026.md)
- [Failure Runbook](FAILURE_RUNBOOK_2026.md)
- [Workflow Dependencies Diagram](WORKFLOW_DEPENDENCIES_DIAGRAM_2026.md)
- [Phase 4 Progress Report](PHASE_4_PROGRESS_REPORT.md)

---

## Support

For questions or issues:
1. Check this guide
2. Review [Failure Runbook](FAILURE_RUNBOOK_2026.md)
3. Check recent issues with label `workflow-validation`
4. Create new issue with label `workflow-testing`
5. Contact DevOps Team

---

**Last Updated:** 2026-02-16  
**Version:** 1.0  
**Maintainer:** DevOps Team
