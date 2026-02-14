# Phase 6 Batch 1: Execution Plan

## Overview

**Goal**: Refactor 4 high-priority .github scripts  
**Target**: Eliminate 766 lines (reaching 2,861 total, 286% of goal)  
**Date**: 2026-02-14

---

## Current Status

### Completed (Phase 5)
- **Scripts**: 9 of 30 refactored (30%)
- **Lines**: 2,095 eliminated (210% of goal)
- **Utils**: 3 modules (analyzer, fixer, dashboard = 1,121 lines)

### Target (Batch 1)
- **Scripts**: 4 additional (13 total = 43%)
- **Lines**: 766 additional (2,861 total = 286% of goal)
- **Utils**: 2 new modules (applier, validator)

---

## Batch 1 Scripts

### 1. apply_workflow_fix.py (347 lines)
**Functionality**:
- WorkflowFixApplier class
- Applies fixes from proposals to workflows
- 9 action types:
  - add_install_step
  - add_line
  - add_timeout
  - add_permissions
  - add_retry_action
  - add_docker_setup
  - change_runner
  - add_env
  - review_required
- YAML manipulation, file I/O

**Refactoring**:
- Create `utils/workflows/applier.py` (~250 lines)
- Extract WorkflowFixApplier class
- Create thin wrapper (140 lines)
- **Reduction**: 60% (207 lines saved)

### 2. validate_workflows.py (323 lines)
**Functionality**:
- WorkflowValidator class
- Validates workflows for common issues
- Checks:
  - Missing GH_TOKEN
  - Incorrect Copilot invocation
  - Missing permissions
  - Self-hosted runner issues
  - Script dependencies
- Issue/warning/info collection

**Refactoring**:
- Create `utils/workflows/validator.py` (~300 lines)
- Extract WorkflowValidator class
- Create thin wrapper (115 lines)
- **Reduction**: 64% (208 lines saved)

### 3. validate_copilot_invocation.py (309 lines)
**Functionality**:
- Validates Copilot CLI invocations in workflows
- Checks Copilot extension installation
- Validates workflow Copilot usage

**Refactoring**:
- Use existing `utils.cli_tools.Copilot`
- Delegate all CLI operations
- Create thin wrapper (140 lines)
- **Reduction**: 55% (169 lines saved)

### 4. analyze_autohealing_metrics.py (292 lines)
**Functionality**:
- Analyzes autohealing system metrics
- Loads metrics from JSON files
- Computes statistics and trends
- Generates reports

**Refactoring**:
- Use existing utils modules
- Extract reusable analysis logic
- Create thin wrapper (110 lines)
- **Reduction**: 62% (182 lines saved)

---

## Implementation Plan

### Step 1: Create utils/workflows/applier.py
**Content**:
```python
# WorkflowFixApplier class
# - __init__(proposal, repo_path)
# - apply() -> List[Dict]
# - _apply_add_install_step(fix)
# - _apply_add_line(fix)
# - _apply_add_timeout(fix)
# - _apply_add_permissions(fix)
# - _apply_add_retry_action(fix)
# - _apply_add_docker_setup(fix)
# - _apply_change_runner(fix)
# - _apply_add_env(fix)
# - _create_review_note(fix)
```

**Imports**: yaml, json, re, Path, typing  
**Size**: ~250 lines

### Step 2: Create utils/workflows/validator.py
**Content**:
```python
# WorkflowValidator class
# - __init__(workflows_dir)
# - validate_all() -> Tuple[int, int, int]
# - validate_workflow(workflow_file)
# - validate_job(workflow_name, job_name, job_config)
# - uses_copilot(workflow)
# - validate_copilot_workflow(workflow_name, workflow)
# - validate_permissions(workflow_name, workflow)
# - check_gh_token_usage(workflow_name, job_name, steps)
# - add_issue/warning/info(workflow, message, suggestion)
```

**Imports**: yaml, Path, typing  
**Size**: ~300 lines

### Step 3: Update utils/workflows/__init__.py
Export new modules:
```python
from .analyzer import WorkflowAnalyzer
from .fixer import WorkflowFixer
from .dashboard import DashboardGenerator
from .applier import WorkflowFixApplier  # NEW
from .validator import WorkflowValidator  # NEW
```

### Step 4: Create apply_workflow_fix_refactored.py
**Thin wrapper** (~140 lines):
- CLI argument parsing
- Load proposal from JSON
- Use WorkflowFixApplier
- Report results

### Step 5: Create validate_workflows_refactored.py
**Thin wrapper** (~115 lines):
- CLI argument parsing
- Use WorkflowValidator
- Report issues/warnings/info

### Step 6: Create validate_copilot_invocation_refactored.py
**Thin wrapper** (~140 lines):
- CLI argument parsing
- Use utils.cli_tools.Copilot
- Workflow-specific validation

### Step 7: Create analyze_autohealing_metrics_refactored.py
**Thin wrapper** (~110 lines):
- CLI argument parsing
- Use existing utils for analysis
- Report generation

---

## Code Reduction Summary

| Script | Before | After | Saved | % |
|--------|--------|-------|-------|---|
| apply_workflow_fix | 347 | 140 | 207 | 60% |
| validate_workflows | 323 | 115 | 208 | 64% |
| validate_copilot_invocation | 309 | 140 | 169 | 55% |
| analyze_autohealing_metrics | 292 | 110 | 182 | 62% |
| **TOTAL** | **1,271** | **505** | **766** | **60%** |

**New Utils Modules**: 550 lines (applier 250 + validator 300)

---

## Expected Results

### Immediate
- 2 new utils modules created
- 4 scripts refactored to thin wrappers
- 766 lines eliminated
- 2,861 total lines eliminated (286% of goal)

### Architecture
```
utils/workflows/ (1,671 lines total)
├── analyzer.py (270 lines) - Error pattern detection
├── fixer.py (440 lines) - Fix proposal generation
├── dashboard.py (411 lines) - API usage dashboards
├── applier.py (250 lines) - Fix application ✨ NEW
└── validator.py (300 lines) - Workflow validation ✨ NEW

.github/scripts/ (13 refactored of 30)
├── Phase 2-4: 3 scripts ✅
├── Phase 5: 6 scripts ✅
└── Batch 1: 4 scripts ⏳ IN PROGRESS
```

### Benefits
1. **Single source of truth** for fix application and validation
2. **Reusable** across all automation tools
3. **Testable** - core logic in utils modules
4. **Maintainable** - update once, benefit everywhere
5. **Consistent** - all scripts use same patterns

---

## Testing Strategy

### Utils Modules
- Unit tests for each method
- Test YAML manipulation
- Test validation logic
- Test error handling

### Refactored Scripts
- CLI smoke tests (--help)
- Integration tests with sample workflows
- Compare behavior with originals

---

## Success Criteria

- ✅ 2 new utils modules created (applier, validator)
- ✅ 4 scripts refactored (thin wrappers)
- ✅ 766 lines eliminated
- ✅ All functionality preserved
- ✅ Tests passing
- ✅ Documentation updated
- ✅ 286% of original goal achieved

---

## Next Steps After Batch 1

**Batch 2** (4 scripts, 545 lines):
- validate_autohealing_system.py
- test_workflow_scripts.py
- test_autofix_pipeline.py
- minimal_workflow_fixer.py

**Target**: 3,406 lines total (341% of goal)

---

## Timeline

- **Session 1**: Create applier.py and validator.py
- **Session 2**: Refactor all 4 scripts
- **Session 3**: Testing and validation
- **Session 4**: Documentation and commit

**Total**: 4 sessions to complete Batch 1

---

**Status**: Ready to implement  
**Confidence**: High (proven pattern from Phase 5)  
**Risk**: Low (incremental approach, well-defined scope)
