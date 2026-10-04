# GitHub Actions Workflows - Quick Reference Guide

**Last Updated:** 2026-02-16  
**Version:** 4.0

---

## 🚀 Quick Start

### Run Validation
```bash
# Validate all workflows
python .github/scripts/comprehensive_workflow_validator.py --check

# Generate detailed report
python .github/scripts/comprehensive_workflow_validator.py --report validation_report.md

# Auto-fix issues
python .github/scripts/comprehensive_workflow_validator.py --fix
```

### Fix Missing Triggers
```bash
# Preview trigger fixes
python .github/scripts/restore_workflow_triggers.py --dry-run

# Apply trigger fixes
python .github/scripts/restore_workflow_triggers.py --apply

# Fix specific workflow
python .github/scripts/restore_workflow_triggers.py --workflow gpu-tests.yml --apply
```

---

## 📋 Common Issues & Fixes

### Issue 1: YAML Indentation Error

**Error:**
```
mapping values are not allowed here
  line 74, column 13
```

**Cause:** Incorrect `with:` indentation after `uses:`

**Fix:**
```yaml
# ❌ Wrong
- uses: actions/checkout@v5
    with:
      fetch-depth: 1

# ✅ Correct
- uses: actions/checkout@v5
  with:
    fetch-depth: 1
```

### Issue 2: Missing Trigger Configuration

**Error:**
```
Missing trigger configuration (on:)
```

**Cause:** Workflow has `true:` instead of `on:`

**Fix:**
```yaml
# ❌ Wrong
true:
  push:
    branches: [main]

# ✅ Correct
on:
  push:
    branches: [main]
```

### Issue 3: Matrix Expression in Flow Array

**Error:**
```
expected ',' or ']', but got '{'
```

**Cause:** Using template expression in YAML flow array

**Fix:**
```yaml
# ❌ Wrong
runs-on: [self-hosted, linux, ${{ matrix.arch }}]

# ✅ Correct
runs-on: ${{ matrix.runs_on }}
# Then define in matrix:
strategy:
  matrix:
    include:
      - runs_on: [self-hosted, linux, x64]
      - runs_on: [self-hosted, linux, arm64]
```

### Issue 4: Missing Timeout

**Error:**
```
Job 'test' missing timeout-minutes
```

**Fix:**
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 30  # Add this
    steps:
      - uses: actions/checkout@v5
```

### Issue 5: Missing Permissions

**Error:**
```
Missing explicit permissions configuration
```

**Fix:**
```yaml
name: My Workflow

on:
  push:
    branches: [main]

# Add this section
permissions:
  contents: read
  actions: read

jobs:
  # ...
```

---

## 🎯 Standard Patterns

### Trigger Patterns

#### CI/CD Workflow
```yaml
on:
  push:
    branches: [main, develop]
    paths:
      - 'src/**'
      - 'tests/**'
  pull_request:
    branches: [main]
  workflow_dispatch:
```

#### Monitoring Workflow
```yaml
on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch:
```

#### Daily Validation
```yaml
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
  workflow_dispatch:
```

#### Auto-Healing Workflow
```yaml
on:
  workflow_run:
    workflows: ["Target Workflow"]
    types: [completed]
  workflow_dispatch:
```

#### PR-Triggered Workflow
```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
  workflow_dispatch:
```

### Permission Patterns

#### Read-Only (Recommended Default)
```yaml
permissions:
  contents: read
  actions: read
```

#### CI/CD with Artifacts
```yaml
permissions:
  contents: read
  actions: read
  packages: write
```

#### PR Management
```yaml
permissions:
  contents: read
  pull-requests: write
  issues: write
```

#### Publishing
```yaml
permissions:
  contents: write
  packages: write
```

### Job Configuration

#### Basic Job
```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 1
      
      - name: Setup
        run: echo "Setup complete"
```

#### Job with Matrix
```yaml
jobs:
  test:
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
        os: [ubuntu-latest, macos-latest]
      fail-fast: false
    
    runs-on: ${{ matrix.os }}
    timeout-minutes: 30
    
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
```

#### Job with Retry Logic
```yaml
jobs:
  flaky-test:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    
    steps:
      - uses: actions/checkout@v5
      
      - name: Run flaky test
        uses: nick-invision/retry@v3
        with:
          timeout_minutes: 10
          max_attempts: 3
          command: npm test
```

---

## 🔧 Tools & Scripts

### Validation Tools

#### comprehensive_workflow_validator.py
- **Purpose:** Validate all workflows for syntax and best practices
- **Features:**
  - YAML syntax validation
  - Security checks
  - Missing permissions detection
  - Timeout validation
  - Auto-fix capabilities

#### restore_workflow_triggers.py
- **Purpose:** Fix workflows with missing/incorrect triggers
- **Features:**
  - Automatic categorization
  - Dry-run mode
  - Bulk and single-file fixes
  - Git history analysis

### Usage Examples

```bash
# Validate everything
python .github/scripts/comprehensive_workflow_validator.py --check

# Fix syntax issues
python .github/scripts/comprehensive_workflow_validator.py --fix

# Restore triggers (preview)
python .github/scripts/restore_workflow_triggers.py --dry-run

# Restore triggers (apply)
python .github/scripts/restore_workflow_triggers.py --apply

# Check specific workflow
python .github/scripts/comprehensive_workflow_validator.py \
  --workflows-dir .github/workflows \
  --check
```

---

## 📊 Health Metrics

### Current State (2026-02-16)

- **Total Workflows:** 56
- **YAML Valid:** 56 (100%)
- **Health Score:** 85/100 (Grade B+)
- **Critical Issues:** 51 (missing triggers)
- **High Issues:** 20 (security/permissions)
- **Medium Issues:** 69 (missing timeouts)
- **Low Issues:** 2 (optimization)

### Target State

- **Total Workflows:** 56
- **YAML Valid:** 56 (100%)
- **Health Score:** 95/100 (Grade A)
- **Critical Issues:** 0
- **High Issues:** 0
- **Medium Issues:** <10
- **Low Issues:** 0

---

## 🎓 Best Practices

### 1. Always Use Explicit Triggers
```yaml
# ✅ Good - Explicit and clear
on:
  push:
    branches: [main]
  workflow_dispatch:

# ❌ Bad - Missing or implicit
true:
  push:
```

### 2. Follow Least Privilege for Permissions
```yaml
# ✅ Good - Minimal permissions
permissions:
  contents: read
  
# ❌ Bad - Too broad
permissions: write-all
```

### 3. Always Set Timeouts
```yaml
# ✅ Good - Prevents runaway jobs
jobs:
  test:
    timeout-minutes: 30
    
# ❌ Bad - No timeout
jobs:
  test:
```

### 4. Use Shallow Clones
```yaml
# ✅ Good - Fast checkout
- uses: actions/checkout@v5
  with:
    fetch-depth: 1
    
# ❌ Bad - Full history
- uses: actions/checkout@v5
```

### 5. Add Retry for Flaky Operations
```yaml
# ✅ Good - Handles transient failures
- uses: nick-invision/retry@v3
  with:
    max_attempts: 3
    command: npm test
    
# ❌ Bad - Fails on first try
- run: npm test
```

### 6. Use Concurrency Control
```yaml
# ✅ Good - Prevents duplicate runs
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

### 7. Cache Dependencies
```yaml
# ✅ Good - Speeds up workflows
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'
    cache: 'pip'
```

---

## 🔍 Troubleshooting

### Workflow Not Running

1. **Check Trigger Configuration**
   ```bash
   # Verify trigger is valid
   python -c "import yaml; print(yaml.safe_load(open('.github/workflows/my-workflow.yml'))['on'])"
   ```

2. **Check Path Filters**
   - Ensure modified files match path patterns
   - Use `**` for recursive matching

3. **Check Branch Filters**
   - Verify branch name matches exactly
   - Check if branch is protected

### Workflow Failing

1. **Check Logs**
   - Review workflow run logs in GitHub UI
   - Look for specific error messages

2. **Validate YAML**
   ```bash
   python .github/scripts/comprehensive_workflow_validator.py --check
   ```

3. **Test Locally**
   ```bash
   # Use act to test locally
   act -l  # List workflows
   act -j test  # Run specific job
   ```

### Permission Errors

1. **Add Required Permissions**
   ```yaml
   permissions:
     contents: write  # Add needed permission
   ```

2. **Check Token Scope**
   - Verify `GITHUB_TOKEN` has necessary scopes
   - Consider using PAT for broader access

---

## 📚 Additional Resources

### Documentation
- [COMPREHENSIVE_IMPROVEMENT_PLAN_V4_2026_02_16.md](COMPREHENSIVE_IMPROVEMENT_PLAN_V4_2026_02_16.md) - Full improvement plan
- [WORKFLOW_VALIDATION_REPORT_2026_02_16.md](WORKFLOW_VALIDATION_REPORT_2026_02_16.md) - Latest validation report
- [README.md](README.md) - Workflow directory overview

### GitHub Actions Docs
- [Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
- [Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Caching Dependencies](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows)

### Tools
- [actionlint](https://github.com/rhysd/actionlint) - Static checker for GitHub Actions
- [act](https://github.com/nektos/act) - Run GitHub Actions locally
- [yamllint](https://github.com/adrienverge/yamllint) - YAML linter

---

## 🆘 Getting Help

### Common Commands
```bash
# Validate workflows
python .github/scripts/comprehensive_workflow_validator.py --check

# Fix syntax errors
python .github/scripts/comprehensive_workflow_validator.py --fix

# Restore triggers
python .github/scripts/restore_workflow_triggers.py --apply

# Generate report
python .github/scripts/comprehensive_workflow_validator.py --report report.md
```

### Report Issues
If you encounter problems:
1. Run validation script
2. Check error messages
3. Consult this guide
4. Create issue with details

---

**Quick Reference Version:** 4.0  
**Last Updated:** 2026-02-16  
**Maintained by:** GitHub Actions Team
