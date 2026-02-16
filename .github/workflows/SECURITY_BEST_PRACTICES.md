# GitHub Actions Security Best Practices

**Last Updated:** 2026-02-16  
**Version:** 1.0  
**Applies To:** All GitHub Actions workflows in this repository

## Table of Contents
1. [Permission Management](#permission-management)
2. [Secret Handling](#secret-handling)
3. [Action Security](#action-security)
4. [Shell Safety](#shell-safety)
5. [Dependency Security](#dependency-security)
6. [Incident Response](#incident-response)
7. [Compliance](#compliance)

## Permission Management

### Principle of Least Privilege

**Always use explicit permissions:**
```yaml
permissions:
  contents: read        # Minimum required
  pull-requests: write  # Only if needed
  issues: write         # Only if needed
```

**Never use:**
```yaml
permissions: write-all  # ❌ Too permissive (unless absolutely required and documented)
```

### Permission Categories

#### 1. Read-Only Workflows
For validation, testing, and monitoring that doesn't modify anything:
```yaml
permissions:
  contents: read
```

Examples:
- Unit tests
- Linting
- Security scans
- Validation checks

#### 2. Monitoring Workflows
For workflows that track issues and PRs:
```yaml
permissions:
  contents: read
  issues: write
  pull-requests: write
```

Examples:
- Error monitoring
- PR completion tracking
- Issue triage

#### 3. CI/CD Workflows
For build and deployment:
```yaml
permissions:
  contents: read
  packages: write  # For Docker/container registries
  actions: read    # For workflow artifacts
```

Examples:
- Docker builds
- Package publishing
- Artifact uploads

#### 4. Autofix Workflows
For automated fixes and PR creation:
```yaml
permissions:
  contents: write      # Create branches
  pull-requests: write # Create/update PRs
  issues: write        # Update issues
  actions: read        # Read workflow status
```

Examples:
- Copilot autofix
- Dependency updates
- Auto-formatting

#### 5. Admin Workflows (Rare)
Only when absolutely necessary and documented:
```yaml
permissions: write-all
# JUSTIFICATION: This workflow manages repository settings
# REVIEW DATE: 2026-06-01
# APPROVED BY: Security Team
```

Must document:
- Why elevated permissions needed
- What operations require them
- Review schedule
- Approval process

### Testing Permissions

Test workflows with restricted permissions:
```bash
# Test locally with act
act -j your-job --secret-file .env.secrets

# Monitor workflow runs for permission errors
gh run list --workflow=your-workflow.yml --limit=10
```

## Secret Handling

### Never Hardcode Secrets

❌ **Bad:**
```yaml
- name: Login
  run: |
    echo "password123" | docker login -u user --password-stdin
```

✅ **Good:**
```yaml
- name: Login
  run: |
    echo "${{ secrets.DOCKER_PASSWORD }}" | docker login -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
```

### Use GitHub Secrets

1. **Repository Secrets** (most common)
   - Settings → Secrets and variables → Actions
   - Use for repo-specific credentials

2. **Environment Secrets**
   - For environment-specific values (dev/staging/prod)
   - Provides protection rules

3. **Organization Secrets**
   - Share across multiple repos
   - Use for company-wide credentials

### Secret Rotation

**Rotation Schedule:**
- **Monthly:** High-risk secrets (API tokens with write access)
- **Quarterly:** Medium-risk secrets (CI/CD tokens)
- **Annual:** Low-risk secrets (public API keys)

**Rotation Process:**
1. Generate new secret
2. Add to GitHub Secrets (don't delete old yet)
3. Update workflows to use new secret name
4. Test workflows with new secret
5. Delete old secret after validation period (1 week)

### Secret Validation

Always validate secrets before use:
```yaml
- name: Validate secrets
  run: |
    if [ -z "${{ secrets.REQUIRED_SECRET }}" ]; then
      echo "::error::Required secret REQUIRED_SECRET is not set"
      exit 1
    fi
```

### Secrets Inventory

Maintain `SECRETS_INVENTORY.md` with:
- Secret name
- Purpose
- Used by which workflows
- Rotation schedule
- Owner/contact
- Last rotation date

## Action Security

### Pin Action Versions

❌ **Bad:**
```yaml
- uses: actions/checkout@latest  # Unpredictable, can break
- uses: actions/checkout@main    # Can introduce vulnerabilities
```

✅ **Good:**
```yaml
- uses: actions/checkout@v4       # Stable major version
- uses: actions/checkout@v4.1.2   # Specific version
```

✅ **Best (for critical workflows):**
```yaml
- uses: actions/checkout@8e5e7e5ab8b370d6c329ec480221332ada57f0ab  # v4.1.2 SHA
  # Pin to exact commit SHA for maximum security
```

### Verify Action Sources

**Trusted Sources:**
- ✅ actions/* (GitHub official)
- ✅ github/* (GitHub official)
- ✅ Verified publishers with GitHub badge
- ✅ Well-known open source projects

**Untrusted Sources:**
- ❌ Random user accounts
- ❌ Recently created repos
- ❌ Actions with few stars/downloads
- ❌ No maintenance history

### Review Action Permissions

Check what actions can do:
```yaml
- uses: some/action@v1
  # Review the action's code first
  # Check permissions it requests
  # Verify it doesn't access secrets unnecessarily
```

### Fork Actions for Critical Use

For mission-critical workflows:
1. Fork the action to your organization
2. Review the code
3. Use your fork
4. Keep it updated manually

```yaml
- uses: your-org/forked-action@v1
```

## Shell Safety

### Avoid Command Injection

❌ **Bad:**
```yaml
- name: Dangerous
  run: |
    echo "User input: ${{ github.event.comment.body }}"
    # Can inject commands!
```

✅ **Good:**
```yaml
- name: Safe
  env:
    USER_INPUT: ${{ github.event.comment.body }}
  run: |
    # Input is in environment variable, safely quoted
    echo "User input: $USER_INPUT"
```

### Validate Inputs

Always validate external inputs:
```yaml
- name: Validate input
  run: |
    INPUT="${{ github.event.inputs.version }}"
    if [[ ! "$INPUT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "::error::Invalid version format"
      exit 1
    fi
```

### Use Safe Shell Options

Enable safety features:
```yaml
- name: Safe script
  shell: bash
  run: |
    set -euo pipefail  # Exit on error, undefined var, pipe failure
    # Your commands here
```

### Quote Variables

Always quote shell variables:
```yaml
- name: Proper quoting
  run: |
    FILE="${{ github.event.inputs.filename }}"
    if [ -f "$FILE" ]; then  # Quoted!
      cat "$FILE"
    fi
```

## Dependency Security

### Scan Dependencies

Use automated scanning:
```yaml
- name: Dependency scan
  uses: github/dependency-scan-action@v1
  with:
    severity: high
```

### Pin Dependencies

Pin to specific versions:
```yaml
# package.json
{
  "dependencies": {
    "express": "4.18.2"  # Specific version, not "^4.18.2"
  }
}

# requirements.txt
requests==2.31.0  # Not requests>=2.31.0
```

### Regular Updates

Update dependencies regularly:
- Security updates: immediate
- Minor updates: monthly
- Major updates: quarterly with testing

### Verify Checksums

When downloading binaries:
```yaml
- name: Download with verification
  run: |
    curl -LO https://example.com/tool.tar.gz
    echo "expected-sha256-hash tool.tar.gz" | sha256sum -c -
```

## Incident Response

### Detection

Monitor for:
- Unexpected workflow failures
- Permission errors
- Secret access attempts
- Unusual action usage
- Security scanner alerts

### Response Steps

1. **Identify**
   - What happened?
   - Which workflow/job?
   - What was compromised?

2. **Contain**
   - Disable affected workflows
   - Revoke compromised secrets
   - Block malicious actions

3. **Eradicate**
   - Remove malicious code
   - Update affected workflows
   - Rotate all secrets

4. **Recover**
   - Test workflows in isolation
   - Gradually re-enable
   - Monitor closely

5. **Learn**
   - Document incident
   - Update security practices
   - Improve detection

### Emergency Contacts

- **Security Team:** security@example.com
- **On-Call:** +1-555-0123
- **Escalation:** CTO/CISO

### Incident Report Template

```markdown
# Incident Report

**Date:** YYYY-MM-DD
**Severity:** Critical/High/Medium/Low
**Status:** Open/Investigating/Resolved

## Summary
Brief description of the incident

## Timeline
- HH:MM - Event 1
- HH:MM - Event 2

## Impact
What was affected

## Root Cause
Why it happened

## Resolution
How it was fixed

## Prevention
How to prevent recurrence
```

## Compliance

### Audit Logging

Enable audit log:
- Organization settings → Audit log
- Review monthly
- Export for compliance

### Access Control

Review access regularly:
- Repository collaborators
- Action secrets access
- Deployment environment protection
- Required reviews

### Compliance Checklist

- [ ] All workflows have explicit permissions
- [ ] All secrets are rotated on schedule
- [ ] All actions are from trusted sources
- [ ] Security scanner is enabled
- [ ] Audit logs are reviewed monthly
- [ ] Incident response plan is documented
- [ ] Team is trained on security practices
- [ ] Compliance reports are generated

### Required Reviews

**Before Merging:**
- Security team review for new workflows
- Approval for permission changes
- Review for new secrets
- Validation of action sources

**Periodic Reviews:**
- Quarterly permission audit
- Semi-annual secret rotation
- Annual security training
- Monthly compliance check

## Security Checklist for New Workflows

When creating a new workflow, check:

- [ ] **Explicit permissions** defined with minimum required
- [ ] **No hardcoded secrets** in workflow file
- [ ] **Actions pinned** to specific versions or SHAs
- [ ] **Actions from trusted sources** only
- [ ] **Inputs validated** if accepting external data
- [ ] **Shell commands safe** from injection
- [ ] **Error handling** standardized
- [ ] **Cleanup steps** in `always()` block
- [ ] **Documentation** added for complex logic
- [ ] **Security scanner** will catch any issues
- [ ] **Tested** with restricted permissions
- [ ] **Reviewed** by security team (if high-risk)

## Security Scanner Integration

The automated security scanner checks:
- Hardcoded secrets
- Action versions
- Permission scopes
- Shell safety
- Dependency vulnerabilities

**How to use:**
1. Push your workflow changes
2. Scanner runs automatically
3. Review findings in PR comments
4. Fix any critical issues
5. Re-run scanner

**Scanner Configuration:**
`.github/workflows/workflow-security-scanner.yml`

## Training Resources

### For Developers
- GitHub Actions Security Guide: https://docs.github.com/actions/security-guides
- Secret management: https://docs.github.com/actions/security-guides/encrypted-secrets
- OIDC tokens: https://docs.github.com/actions/security-guides/automatic-token-authentication

### Internal Resources
- This document (SECURITY_BEST_PRACTICES.md)
- SECRETS_INVENTORY.md
- ERROR_HANDLING_PATTERNS.md
- PHASE_3_COMPLETE.md

### Security Training
- Annual security awareness training
- Quarterly workflow security reviews
- On-boarding security checklist
- Incident response drills

## Questions?

Contact:
- **Security Team:** security@example.com
- **DevOps Team:** devops@example.com
- **Documentation:** See `.github/workflows/README.md`

---

**Document Owner:** Security Team  
**Review Schedule:** Quarterly  
**Last Review:** 2026-02-16  
**Next Review:** 2026-05-16
