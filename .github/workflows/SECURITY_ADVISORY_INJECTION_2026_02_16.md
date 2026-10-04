# GitHub Actions Security Advisory - Injection Vulnerabilities
**Date:** 2026-02-16  
**Severity:** HIGH  
**Status:** Active Remediation  
**Phase:** 1.3 - Security Hardening

---

## Executive Summary

This security advisory documents **48+ injection vulnerability instances** found across GitHub Actions workflows in the ipfs_datasets_py repository. These vulnerabilities arise from unsafe usage of GitHub context variables (`github.event.*`) directly in shell commands without proper sanitization.

### Risk Assessment

**Severity:** HIGH  
**Impact:** Command injection, potential code execution  
**Exploitability:** MEDIUM (requires specific event triggers)  
**CVSS Score:** 7.5 (High)

**Affected Workflows:** 20+ workflows  
**Total Vulnerable Instances:** 50+  
**Remediation Status:** 0% complete (0/50+ fixed)

---

## Vulnerability Description

### Problem

GitHub Actions workflows use expressions like `${{ github.event.* }}` to access event data. When these expressions are used directly in shell commands without sanitization, they create command injection vulnerabilities.

### Attack Vector

An attacker with ability to trigger workflows (via issues, PR reviews, workflow_dispatch, etc.) could inject malicious commands through:
- Issue titles/bodies
- PR titles/descriptions
- Workflow dispatch inputs
- PR review comments

### Example Vulnerability

**Unsafe Pattern:**
```yaml
run: |
  TARGET="${{ github.event.inputs.target_files }}"
  echo "Processing: $TARGET"
```

**Exploit:**
```
Input: "; rm -rf / #"
Result: TARGET="; rm -rf / #"
Executes: echo "Processing: "; rm -rf / #"
```

---

## Affected Workflows

### Critical Priority (Direct User Input)

#### 1. agentic-optimization.yml (8 instances)
**Lines:** 67, 78, 79, 133, 145, 146, 179, 194, 204, 205, 213

**Vulnerable Patterns:**
```yaml
Line 67:  if [[ "${{ github.event_name }}" == "issues" ]]; then
Line 78:    echo "target_files=${{ github.event.inputs.target_files || 'ipfs_datasets_py/' }}" >> $GITHUB_OUTPUT
Line 79:    echo "method=${{ github.event.inputs.optimization_method || 'test_driven' }}" >> $GITHUB_OUTPUT
Line 133:   --value ${{ github.event.inputs.validation_level || 'standard' }}
Line 145: PRIORITY="${{ github.event.inputs.priority || '50' }}"
Line 146: DRY_RUN="${{ github.event.inputs.dry_run == true && '--dry-run' || '' }}"
```

**Risk Level:** HIGH - Direct workflow_dispatch inputs without sanitization

---

#### 2. approve-optimization.yml (5 instances)
**Lines:** 38, 57, 58, 60, 163, 184

**Vulnerable Patterns:**
```yaml
Line 38:  ref: ${{ github.event.pull_request.head.ref || format('automated-optimization-{0}', github.event.inputs.pr_number) }}
Line 57:  if [ "${{ github.event_name }}" == "workflow_dispatch" ]; then
Line 58:    PR_NUMBER=${{ github.event.inputs.pr_number }}
Line 60:    PR_NUMBER=${{ github.event.pull_request.number }}
```

**Risk Level:** MEDIUM - PR numbers (integer) have limited injection risk

---

#### 3. close-stale-draft-prs.yml (5 instances)
**Lines:** 66, 67, 291, 292, 296

**Vulnerable Patterns:**
```yaml
Line 66:  MAX_AGE_HOURS: ${{ github.event.inputs.max_age_hours || env.MAX_AGE_HOURS }}
Line 67:  DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }}
```

**Risk Level:** MEDIUM - Numeric and boolean inputs

---

#### 4. continuous-queue-management.yml (6 instances)
**Lines:** 47, 124, 303, 348, 397, 550

**Vulnerable Patterns:**
```yaml
Line 47:  MAX_CONCURRENT_AGENTS: ${{ github.event.inputs.max_agents || '3' }}
Line 124: FORCE_PROCESS: ${{ github.event.inputs.force_process_all || 'false' }}
```

**Risk Level:** MEDIUM - Controlled inputs but still vulnerable

---

#### 5. copilot-agent-autofix.yml (9 instances)
**Lines:** 63, 91-99, 148-152, 156

**Vulnerable Patterns:**
```yaml
Line 63:  group: ${{ github.workflow }}-${{ github.event.workflow_run.id || github.run_id }}
Line 91:  echo "- **Event Name**: ${{ github.event_name }}" >> $GITHUB_STEP_SUMMARY
Line 92:  echo "- **Workflow Run Conclusion**: ${{ github.event.workflow_run.conclusion }}" >> $GITHUB_STEP_SUMMARY
Line 148: if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
Line 149:   if [ -n "${{ github.event.inputs.run_id }}" ]; then
Line 150:     RUN_ID="${{ github.event.inputs.run_id }}"
```

**Risk Level:** MEDIUM-HIGH - Mix of system and user inputs

---

#### 6. copilot-issue-assignment.yml (3 instances)
**Lines:** 79, 81, 84

**Vulnerable Patterns:**
```yaml
Line 79:  if [ "${{ github.event_name }}" == "workflow_dispatch" ]; then
Line 84:    echo "number=${{ github.event.issue.number }}" >> $GITHUB_OUTPUT
```

**Risk Level:** MEDIUM - Issue numbers are integers

---

#### 7. docker-build-test.yml (2 instances)
**Lines:** 294, 305

**Vulnerable Patterns:**
```yaml
Line 294: platforms: ${{ github.event.inputs.platform || 'linux/amd64,linux/arm64' }}
```

**Risk Level:** MEDIUM - Platform string could be exploited

---

#### 8. documentation-maintenance.yml (1 instance)
**Lines:** 345

**Vulnerable Patterns:**
```yaml
Line 345: if [ "${{ github.event.inputs.auto_fix }}" = "true" ] || [ "${{ github.event_name }}" = "schedule" ]; then
```

**Risk Level:** LOW - Boolean input

---

#### 9. enhanced-pr-completion-monitor.yml (2 instances)
**Lines:** 164, 165

**Vulnerable Patterns:**
```yaml
Line 164: PR_NUMBER="${{ github.event.inputs.pr_number || '' }}"
Line 165: DRY_RUN="${{ github.event.inputs.dry_run || 'false' }}"
```

**Risk Level:** MEDIUM

---

### Additional Workflows (8+ more)

Other workflows with similar patterns:
- cli-error-monitoring-unified.yml
- enhanced-pr-completion-monitor.yml
- github-api-usage-monitor.yml
- issue-to-draft-pr.yml
- mcp-dashboard-tests.yml
- pr-copilot-monitor.yml
- pr-copilot-reviewer.yml
- workflow-health-dashboard.yml

---

## Remediation Plan

### Phase 1: High-Risk Workflows (Week 2, 8 hours)

#### Priority 1: User-Controlled Inputs (4 hours)
1. **agentic-optimization.yml** - 8 instances
2. **approve-optimization.yml** - 5 instances
3. **continuous-queue-management.yml** - 6 instances
4. **copilot-agent-autofix.yml** - 9 instances

#### Priority 2: Mixed Inputs (4 hours)
5. **close-stale-draft-prs.yml** - 5 instances
6. **copilot-issue-assignment.yml** - 3 instances
7. **docker-build-test.yml** - 2 instances
8. **documentation-maintenance.yml** - 1 instance

### Phase 2: Remaining Workflows (Week 2, 4 hours)

Complete remediation of all remaining workflows with injection vulnerabilities.

---

## Fix Pattern

### Standard Fix Pattern

**Before (UNSAFE):**
```yaml
run: |
  TARGET="${{ github.event.inputs.target_files }}"
  echo "Processing: $TARGET"
```

**After (SAFE):**
```yaml
env:
  TARGET: ${{ github.event.inputs.target_files }}
run: |
  echo "Processing: ${TARGET}"
```

### Key Principles

1. **Use Environment Variables:** Move all `${{ }}` expressions to `env:` block
2. **Quote Variables:** Always quote when expanding: `"${VAR}"`
3. **Validate Input:** Add input validation where possible
4. **Escape Output:** Use proper escaping for display

### Complete Example

**Before:**
```yaml
- name: Process input
  run: |
    echo "Title: ${{ github.event.issue.title }}"
    echo "Method: ${{ github.event.inputs.method }}"
    TARGET="${{ github.event.inputs.target }}"
    ./script.sh "$TARGET"
```

**After:**
```yaml
- name: Process input
  env:
    ISSUE_TITLE: ${{ github.event.issue.title }}
    INPUT_METHOD: ${{ github.event.inputs.method }}
    INPUT_TARGET: ${{ github.event.inputs.target }}
  run: |
    echo "Title: ${ISSUE_TITLE}"
    echo "Method: ${INPUT_METHOD}"
    ./script.sh "${INPUT_TARGET}"
```

---

## Validation

### Manual Testing

For each fixed workflow:
1. Test with normal inputs
2. Test with special characters: `; | & $ ( ) < > " ' \`
3. Test with command injection attempts
4. Verify output is properly escaped

### Automated Testing

```bash
# Run validator after fixes
python .github/scripts/enhanced_workflow_validator.py

# Check for remaining injection risks
grep -r '${{ github.event' .github/workflows/*.yml | grep -v 'env:'
```

---

## Timeline

**Week 2 (Phase 1.3):**
- Day 1-2: Fix Priority 1 workflows (4 hours)
- Day 3-4: Fix Priority 2 workflows (4 hours)
- Day 5: Validation and testing (2 hours)
- Day 5: Documentation update (2 hours)

**Total:** 12 hours (Phase 2 of improvement plan)

---

## Security Checklist

### Before Fix
- [ ] Identify all `${{ github.event.* }}` usage
- [ ] Classify by risk level
- [ ] Plan fix approach

### During Fix
- [ ] Move expressions to `env:` block
- [ ] Quote all variable expansions
- [ ] Add input validation where possible
- [ ] Test with malicious inputs

### After Fix
- [ ] Run validation tools
- [ ] Manual testing with edge cases
- [ ] Update documentation
- [ ] Mark as complete

---

## References

### GitHub Security Best Practices

- [Security hardening for GitHub Actions](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Preventing script injection attacks](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#understanding-the-risk-of-script-injections)

### Internal Documentation

- [Improvement Plan Quick Reference](IMPROVEMENT_PLAN_QUICK_REFERENCE_2026_02_16.md)
- [Comprehensive Improvement Plan](COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md)
- [Implementation Checklist](IMPLEMENTATION_CHECKLIST_2026_02_16.md)

---

## Contact

**Owner:** DevOps Security Team  
**Assignee:** Phase 1 Implementation Team  
**Priority:** HIGH  
**Deadline:** End of Week 2 (Phase 2 completion)

For questions or concerns about this advisory:
1. Create issue with tag `security`, `github-actions`
2. Reference this document: `SECURITY_ADVISORY_INJECTION_2026_02_16.md`

---

**Status:** ACTIVE  
**Last Updated:** 2026-02-16  
**Next Review:** Daily during remediation
