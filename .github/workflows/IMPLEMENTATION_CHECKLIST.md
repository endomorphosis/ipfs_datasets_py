# GitHub Actions Improvement Plan - Implementation Checklist

**Start Date:** 2026-02-15  
**Target Completion:** 2026-04-15 (9 weeks)  
**Status:** 🔄 Phase 1 In Progress (Runner Gating Implemented)

**Latest Update:** 2026-02-15 - Runner gating system complete, applying to workflows

---

## Phase 1: Infrastructure & Reliability (Week 1-2)

**Goal:** Implement runner availability gating (REVISED: No fallback to GitHub-hosted)  
**Duration:** 40 hours | **Priority:** P0 | **Risk:** Low  
**Progress:** 40% Complete (16/40 hours)

### 1.1 Self-Hosted Runner Gating Strategy (REVISED)

**Note:** Strategy changed from "fallback to GitHub-hosted" to "gate and skip gracefully"  
**Reason:** Dataset-heavy operations require self-hosted runners; GitHub-hosted insufficient

- [x] **Audit workflows using self-hosted runners** (2 hours) ✅
  - [x] Listed all workflows with `[self-hosted, linux, x64]` (31 workflows)
  - [x] Listed all workflows with `[self-hosted, linux, arm64]` (5 workflows)
  - [x] Documented dependencies (Docker, GPU, large datasets)
  - [x] Identified runners cannot be replaced with GitHub-hosted

- [x] **Design runner gating strategy** (3 hours) ✅
  - [x] Created runner availability check script
  - [x] Created reusable workflow template
  - [x] Tested on GPU workflow example
  - [x] Documented usage patterns

- [x] **Implement gating infrastructure** (6 hours) ✅
  - [x] `check_runner_availability.py` - API-based availability check
  - [x] `templates/check-runner-availability.yml` - Reusable workflow
  - [x] `gpu-tests-gated.yml` - Example implementation
  - [x] Comprehensive documentation created

- [ ] **Apply gating to CI/CD workflows** (5 hours) 🔄 IN PROGRESS
  - [x] `gpu-tests.yml` - Gated version created ✅
  - [ ] `docker-build-test.yml` - Apply gating pattern
  - [ ] `graphrag-production-ci.yml` - Apply gating pattern
  - [ ] `mcp-integration-tests.yml` - Apply gating pattern
  - [ ] `pdf_processing_ci.yml` - Apply gating pattern

- [ ] **Implement fallback for monitoring workflows** (4 hours)
  - [ ] `workflow-health-check.yml` - Add fallback
  - [ ] `github-api-usage-monitor.yml` - Add fallback
  - [ ] `cli-error-monitoring.yml` - Add fallback
  - [ ] `mcp-tools-monitoring.yml` - Add fallback

- [ ] **Document and validate** (2 hours)
  - [ ] Update README with fallback strategy
  - [ ] Create troubleshooting guide
  - [ ] Test failure scenarios
  - [ ] Monitor first 48 hours after deployment

### 1.2 Runner Health Check Enhancement

- [ ] **Create runner health monitor workflow** (4 hours)
  - [ ] Create `.github/workflows/runner-health-monitor.yml`
  - [ ] Add checks for x64 runners
  - [ ] Add checks for arm64 runners
  - [ ] Add checks for GPU runners
  - [ ] Configure 5-minute schedule

- [ ] **Implement health checks** (3 hours)
  - [ ] Check runner online status
  - [ ] Check runner capacity
  - [ ] Check runner labels
  - [ ] Test Docker availability
  - [ ] Test GPU availability

- [ ] **Add alerting** (2 hours)
  - [ ] Configure alerts for offline runners
  - [ ] Configure alerts for capacity issues
  - [ ] Set up notification channels
  - [ ] Test alert delivery

- [ ] **Create dashboard** (3 hours)
  - [ ] Design runner status dashboard
  - [ ] Implement metrics collection
  - [ ] Deploy dashboard
  - [ ] Document access and usage

### 1.3 Python Version Standardization

- [ ] **Audit current Python versions** (1 hour)
  - [ ] Scan all workflows for python-version
  - [ ] Document version usage by workflow
  - [ ] Identify compatibility issues

- [ ] **Update to Python 3.12** (2 hours)
  - [ ] Update all workflows to 3.12
  - [ ] Test each workflow after update
  - [ ] Fix any compatibility issues
  - [ ] Update documentation

- [ ] **Validate and monitor** (1 hour)
  - [ ] Run full test suite
  - [ ] Monitor first 24 hours
  - [ ] Address any issues
  - [ ] Document changes

### 1.4 Action Version Updates

- [ ] **Audit current action versions** (1 hour)
  - [ ] List all actions/setup-python usage
  - [ ] List all actions/checkout usage
  - [ ] List all actions/cache usage
  - [ ] List all docker/* action usage
  - [ ] Document current versions

- [ ] **Update actions/setup-python to v5** (1 hour)
  - [ ] Update all workflows
  - [ ] Test workflows
  - [ ] Fix any issues

- [ ] **Update actions/checkout to v4** (1 hour)
  - [ ] Update all workflows
  - [ ] Test workflows
  - [ ] Fix any issues

- [ ] **Update actions/cache to v4** (1 hour)
  - [ ] Update all workflows
  - [ ] Test workflows
  - [ ] Fix any issues

- [ ] **Update docker actions to v3** (1 hour)
  - [ ] Update docker/setup-buildx-action
  - [ ] Update docker/build-push-action
  - [ ] Update docker/login-action
  - [ ] Test workflows

- [ ] **Validate and document** (1 hour)
  - [ ] Run full test suite
  - [ ] Monitor for 24 hours
  - [ ] Update changelog
  - [ ] Document breaking changes

---

## Phase 2: Consolidation & Optimization (Week 2-3)

**Goal:** Reduce duplication and standardize common patterns  
**Duration:** 32 hours | **Priority:** P1 | **Risk:** Medium

### 2.1 Consolidate PR Monitoring Workflows

- [ ] **Design unified workflow** (3 hours)
  - [ ] Analyze existing workflows
  - [ ] Design parameterized structure
  - [ ] Create workflow specification
  - [ ] Review with team

- [ ] **Implement unified workflow** (4 hours)
  - [ ] Create `.github/workflows/pr-unified-monitor.yml`
  - [ ] Add mode selection (completion/copilot/enhanced)
  - [ ] Implement common setup logic
  - [ ] Implement mode-specific logic
  - [ ] Add configuration options

- [ ] **Test unified workflow** (2 hours)
  - [ ] Test completion mode
  - [ ] Test copilot mode
  - [ ] Test enhanced mode
  - [ ] Test all trigger types
  - [ ] Verify outputs match old workflows

- [ ] **Migrate and deprecate** (2 hours)
  - [ ] Update all references to old workflows
  - [ ] Rename old workflows to .disabled
  - [ ] Update documentation
  - [ ] Monitor for 48 hours
  - [ ] Remove old workflows if successful

### 2.2 Merge Runner Validation Workflows

- [ ] **Design unified validation workflow** (2 hours)
  - [ ] Analyze current validation logic
  - [ ] Design matrix strategy for architectures
  - [ ] Design mode selection (standard/clean)
  - [ ] Document new structure

- [ ] **Implement unified workflow** (3 hours)
  - [ ] Create `.github/workflows/runner-validation-unified.yml`
  - [ ] Add architecture matrix (x64/arm64)
  - [ ] Add validation mode selection
  - [ ] Implement validation logic
  - [ ] Add reporting

- [ ] **Test and migrate** (2 hours)
  - [ ] Test x64 standard validation
  - [ ] Test x64 clean validation
  - [ ] Test arm64 validation
  - [ ] Migrate references
  - [ ] Deprecate old workflows

### 2.3 Unify Error Monitoring Workflows

- [ ] **Create monitoring template** (3 hours)
  - [ ] Create `.github/workflows/templates/service-monitor-template.yml`
  - [ ] Define reusable inputs
  - [ ] Implement monitoring logic
  - [ ] Add reporting and alerting
  - [ ] Document usage

- [ ] **Create caller workflows** (2 hours)
  - [ ] Update `javascript-sdk-monitoring.yml` to use template
  - [ ] Update `cli-error-monitoring.yml` to use template
  - [ ] Update `mcp-tools-monitoring.yml` to use template
  - [ ] Test each workflow

- [ ] **Validate and document** (1 hour)
  - [ ] Run all monitoring workflows
  - [ ] Verify outputs are correct
  - [ ] Update documentation
  - [ ] Monitor for 24 hours

### 2.4 Create Reusable Workflow Components

- [ ] **Create Python setup template** (2 hours)
  - [ ] Create `.github/workflows/templates/python-setup.yml`
  - [ ] Add caching logic
  - [ ] Add dependency installation
  - [ ] Test template

- [ ] **Create Docker build template** (2 hours)
  - [ ] Create `.github/workflows/templates/docker-build.yml`
  - [ ] Add multi-platform support
  - [ ] Add caching
  - [ ] Test template

- [ ] **Create test runner template** (2 hours)
  - [ ] Create `.github/workflows/templates/pytest-runner.yml`
  - [ ] Add coverage reporting
  - [ ] Add artifact upload
  - [ ] Test template

- [ ] **Document templates** (2 hours)
  - [ ] Create template usage guide
  - [ ] Add examples
  - [ ] Update main README
  - [ ] Create migration guide

---

## Phase 3: Security & Best Practices (Week 3-4)

**Goal:** Harden workflows and implement security best practices  
**Duration:** 24 hours | **Priority:** P1 | **Risk:** Low

### 3.1 Add Explicit GITHUB_TOKEN Permissions

- [ ] **Audit current permissions** (2 hours)
  - [ ] List workflows without explicit permissions
  - [ ] Document required permissions per workflow
  - [ ] Create permission matrix
  - [ ] Review with security team

- [ ] **Add permissions to CI/CD workflows** (3 hours)
  - [ ] Add to docker-build-test.yml
  - [ ] Add to graphrag-production-ci.yml
  - [ ] Add to pdf_processing_ci.yml
  - [ ] Add to mcp-integration-tests.yml
  - [ ] Test workflows

- [ ] **Add permissions to automation workflows** (3 hours)
  - [ ] Add to copilot-agent-autofix.yml
  - [ ] Add to issue-to-draft-pr.yml
  - [ ] Add to pr-copilot-reviewer.yml
  - [ ] Add to close-stale-draft-prs.yml
  - [ ] Test workflows

- [ ] **Add permissions to monitoring workflows** (2 hours)
  - [ ] Add to workflow-health-check.yml
  - [ ] Add to monitoring workflows
  - [ ] Test workflows

- [ ] **Document and validate** (1 hour)
  - [ ] Update security documentation
  - [ ] Test all workflows
  - [ ] Monitor for permission errors

### 3.2 Implement Workflow Security Scanner

- [ ] **Design security scanner** (2 hours)
  - [ ] Define security checks
  - [ ] Research tools (actionlint, etc.)
  - [ ] Design workflow structure
  - [ ] Create check list

- [ ] **Implement scanner** (4 hours)
  - [ ] Create `.github/workflows/workflow-security-scan.yml`
  - [ ] Add hardcoded secrets check
  - [ ] Add permission scope check
  - [ ] Add action version check
  - [ ] Add dangerous pattern check
  - [ ] Create script for detailed scanning

- [ ] **Test and deploy** (2 hours)
  - [ ] Test scanner on existing workflows
  - [ ] Fix any issues found
  - [ ] Deploy scanner
  - [ ] Monitor results

### 3.3 Secrets Management Audit

- [ ] **Inventory all secrets** (2 hours)
  - [ ] Create `.github/workflows/SECRETS_INVENTORY.md`
  - [ ] List all secrets used
  - [ ] Document purpose of each secret
  - [ ] Document access controls
  - [ ] Define rotation schedule

- [ ] **Review secret usage** (1 hour)
  - [ ] Audit where each secret is used
  - [ ] Check for unnecessary exposure
  - [ ] Verify least privilege
  - [ ] Document findings

- [ ] **Implement rotation** (2 hours)
  - [ ] Set up rotation reminders
  - [ ] Create rotation procedures
  - [ ] Test rotation process
  - [ ] Document schedule

### 3.4 Add Workflow Validation Pre-Commit Hook

- [ ] **Create validation script** (2 hours)
  - [ ] Create `.github/scripts/validate_workflows.py`
  - [ ] Add YAML syntax validation
  - [ ] Add required field checks
  - [ ] Add security checks
  - [ ] Add best practice checks

- [ ] **Configure pre-commit** (1 hour)
  - [ ] Create `.github/pre-commit-config.yaml`
  - [ ] Add workflow validation hook
  - [ ] Test locally
  - [ ] Document usage

- [ ] **Deploy and monitor** (1 hour)
  - [ ] Update contribution guide
  - [ ] Announce to team
  - [ ] Monitor adoption
  - [ ] Address issues

---

## Phase 4: Testing & Validation (Week 4-5)

**Goal:** Ensure all workflows work as expected with automated testing  
**Duration:** 32 hours | **Priority:** P2 | **Risk:** Low

### 4.1 Create Workflow Testing Framework

- [ ] **Design testing strategy** (3 hours)
  - [ ] Define testing layers
  - [ ] Choose testing tools
  - [ ] Create test structure
  - [ ] Document approach

- [ ] **Implement syntax validation** (2 hours)
  - [ ] Create `.github/scripts/test_workflow_syntax.py`
  - [ ] Add YAML parsing tests
  - [ ] Add schema validation
  - [ ] Test on all workflows

- [ ] **Implement logic testing** (4 hours)
  - [ ] Create `.github/tests/test_workflows.py`
  - [ ] Add trigger validation tests
  - [ ] Add permission tests
  - [ ] Add structure tests
  - [ ] Run test suite

- [ ] **Implement integration testing** (4 hours)
  - [ ] Create `.github/workflows/test-workflows.yml`
  - [ ] Add CI validation
  - [ ] Test on PR
  - [ ] Monitor results

### 4.2 Smoke Tests for Critical Workflows

- [ ] **Design smoke tests** (2 hours)
  - [ ] Identify critical workflows
  - [ ] Define test scenarios
  - [ ] Design test workflow
  - [ ] Document approach

- [ ] **Implement smoke tests** (4 hours)
  - [ ] Create `.github/workflows/smoke-tests.yml`
  - [ ] Add docker-build-test smoke test
  - [ ] Add graphrag-production-ci smoke test
  - [ ] Add copilot-agent-autofix smoke test
  - [ ] Add mcp-integration-tests smoke test
  - [ ] Add pdf_processing_ci smoke test

- [ ] **Schedule and monitor** (2 hours)
  - [ ] Configure schedule (every 6 hours)
  - [ ] Set up alerting
  - [ ] Run initial tests
  - [ ] Monitor results

### 4.3 CI Check for Workflow Changes

- [ ] **Create validation workflow** (3 hours)
  - [ ] Create `.github/workflows/validate-workflow-changes.yml`
  - [ ] Add syntax validation
  - [ ] Add breaking change detection
  - [ ] Add autohealing list verification
  - [ ] Test workflow

- [ ] **Deploy and document** (1 hour)
  - [ ] Enable workflow
  - [ ] Update contribution guide
  - [ ] Test on sample PR
  - [ ] Monitor results

### 4.4 Documentation and Training

- [ ] **Create testing guide** (3 hours)
  - [ ] Document testing framework
  - [ ] Add usage examples
  - [ ] Create troubleshooting guide
  - [ ] Add to main README

- [ ] **Team training** (4 hours)
  - [ ] Schedule training session
  - [ ] Prepare materials
  - [ ] Conduct training
  - [ ] Gather feedback

---

## Phase 5: Monitoring & Observability (Week 5-6)

**Goal:** Comprehensive monitoring and alerting for workflow health  
**Duration:** 40 hours | **Priority:** P2 | **Risk:** Low

### 5.1 Workflow Health Dashboard

- [ ] **Design dashboard** (4 hours)
  - [ ] Define metrics to track
  - [ ] Design dashboard layout
  - [ ] Choose visualization tools
  - [ ] Create mockups

- [ ] **Implement data collection** (6 hours)
  - [ ] Create `.github/scripts/collect_workflow_metrics.py`
  - [ ] Collect run status metrics
  - [ ] Collect performance metrics
  - [ ] Collect resource metrics
  - [ ] Store metrics data

- [ ] **Build dashboard** (6 hours)
  - [ ] Create `.github/workflows/workflow-health-dashboard.yml`
  - [ ] Implement dashboard generation
  - [ ] Add visualizations
  - [ ] Deploy dashboard
  - [ ] Test dashboard

- [ ] **Deploy and document** (2 hours)
  - [ ] Publish dashboard
  - [ ] Create user guide
  - [ ] Share with team
  - [ ] Gather feedback

### 5.2 Automated Performance Monitoring

- [ ] **Define performance metrics** (2 hours)
  - [ ] Identify key metrics
  - [ ] Set baseline values
  - [ ] Define alert thresholds
  - [ ] Document metrics

- [ ] **Implement monitoring** (4 hours)
  - [ ] Create monitoring script
  - [ ] Add duration tracking
  - [ ] Add failure rate tracking
  - [ ] Add queue time tracking
  - [ ] Test monitoring

- [ ] **Configure alerting** (3 hours)
  - [ ] Set up alert conditions
  - [ ] Configure notification channels
  - [ ] Test alerts
  - [ ] Document alerts

- [ ] **Deploy and monitor** (1 hour)
  - [ ] Enable monitoring
  - [ ] Validate metrics
  - [ ] Monitor first 24 hours
  - [ ] Adjust thresholds

### 5.3 Cost Tracking & Optimization

- [ ] **Design cost tracking** (2 hours)
  - [ ] Identify cost factors
  - [ ] Design tracking approach
  - [ ] Create reporting structure
  - [ ] Document methodology

- [ ] **Implement tracking** (4 hours)
  - [ ] Create `.github/scripts/track_workflow_costs.py`
  - [ ] Track runner minutes
  - [ ] Track storage costs
  - [ ] Track API usage
  - [ ] Generate reports

- [ ] **Analysis and optimization** (3 hours)
  - [ ] Analyze cost data
  - [ ] Identify expensive workflows
  - [ ] Propose optimizations
  - [ ] Document recommendations

- [ ] **Deploy and review** (1 hour)
  - [ ] Enable tracking
  - [ ] Generate first report
  - [ ] Review with team
  - [ ] Plan optimizations

---

## Phase 6: Documentation & Maintenance (Week 6-7)

**Goal:** Comprehensive documentation and automated maintenance  
**Duration:** 48 hours | **Priority:** P2 | **Risk:** Low

### 6.1 Complete Workflow Documentation

- [ ] **Document each workflow** (24 hours)
  - [ ] copilot-agent-autofix.yml (1.5h)
  - [ ] issue-to-draft-pr.yml (1.5h)
  - [ ] pr-copilot-reviewer.yml (1.5h)
  - [ ] docker-build-test.yml (1.5h)
  - [ ] graphrag-production-ci.yml (1.5h)
  - [ ] mcp-integration-tests.yml (1.5h)
  - [ ] pdf_processing_ci.yml (1.5h)
  - [ ] gpu-tests.yml (1.5h)
  - [ ] self-hosted-runner.yml (1.5h)
  - [ ] runner-validation-unified.yml (1.5h)
  - [ ] workflow-health-check.yml (1.5h)
  - [ ] documentation-maintenance.yml (1.5h)
  - [ ] publish_to_pipy.yml (1.5h)
  - [ ] workflow-security-scan.yml (1.5h)
  - [ ] smoke-tests.yml (1.5h)
  - [ ] Other workflows (9h)

- [ ] **Update main README** (3 hours)
  - [ ] Add workflow inventory
  - [ ] Add quick start guide
  - [ ] Add troubleshooting section
  - [ ] Add contribution guide
  - [ ] Review and polish

### 6.2 Create Runbooks for Common Tasks

- [ ] **Runbook: Adding a New Workflow** (2 hours)
  - [ ] Document prerequisites
  - [ ] List steps
  - [ ] Add validation checklist
  - [ ] Include examples

- [ ] **Runbook: Updating Action Versions** (2 hours)
  - [ ] Document safe upgrade process
  - [ ] Add testing checklist
  - [ ] Include rollback procedure
  - [ ] Add examples

- [ ] **Runbook: Troubleshooting Runner Issues** (3 hours)
  - [ ] Document diagnostic steps
  - [ ] Add common issues and fixes
  - [ ] Include escalation path
  - [ ] Add examples

- [ ] **Runbook: Responding to Workflow Failures** (3 hours)
  - [ ] Document investigation steps
  - [ ] Add decision tree
  - [ ] Include fix procedures
  - [ ] Add examples

- [ ] **Runbook: Security Incident Response** (3 hours)
  - [ ] Document detection steps
  - [ ] Add response procedures
  - [ ] Include recovery steps
  - [ ] Add examples

- [ ] **Runbook: Disaster Recovery** (3 hours)
  - [ ] Document backup procedures
  - [ ] Add recovery steps
  - [ ] Include testing procedures
  - [ ] Add examples

### 6.3 Automated Dependency Updates

- [ ] **Configure Dependabot** (2 hours)
  - [ ] Create `.github/dependabot.yml`
  - [ ] Configure for github-actions
  - [ ] Set update schedule
  - [ ] Configure reviewers and labels

- [ ] **Test and monitor** (1 hour)
  - [ ] Wait for first PRs
  - [ ] Review PRs
  - [ ] Test auto-merge (if desired)
  - [ ] Monitor for issues

### 6.4 Workflow Changelog

- [ ] **Create changelog** (1 hour)
  - [ ] Create `.github/workflows/CHANGELOG.md`
  - [ ] Document recent changes
  - [ ] Set up template
  - [ ] Define maintenance process

- [ ] **Backfill history** (2 hours)
  - [ ] Review git history
  - [ ] Document major changes
  - [ ] Organize by version/date
  - [ ] Review with team

---

## Final Review & Handoff

### Pre-Launch Checklist

- [ ] **All phases complete**
  - [ ] Phase 1: Infrastructure & Reliability ✅
  - [ ] Phase 2: Consolidation & Optimization ✅
  - [ ] Phase 3: Security & Best Practices ✅
  - [ ] Phase 4: Testing & Validation ✅
  - [ ] Phase 5: Monitoring & Observability ✅
  - [ ] Phase 6: Documentation & Maintenance ✅

- [ ] **Quality assurance**
  - [ ] All workflows tested
  - [ ] All documentation reviewed
  - [ ] All security checks passed
  - [ ] All tests passing
  - [ ] All alerts configured

- [ ] **Team readiness**
  - [ ] Training completed
  - [ ] Documentation shared
  - [ ] Support channels established
  - [ ] Feedback collected

- [ ] **Launch preparation**
  - [ ] Rollback plan documented
  - [ ] Monitoring in place
  - [ ] On-call schedule confirmed
  - [ ] Communication plan ready

### Post-Launch

- [ ] **Week 1 monitoring**
  - [ ] Monitor all workflows daily
  - [ ] Address issues immediately
  - [ ] Collect feedback
  - [ ] Document lessons learned

- [ ] **Week 2-4 stabilization**
  - [ ] Monitor key metrics
  - [ ] Fine-tune configurations
  - [ ] Address feedback
  - [ ] Update documentation

- [ ] **Month 1 review**
  - [ ] Analyze success metrics
  - [ ] Review team feedback
  - [ ] Document improvements
  - [ ] Plan next iteration

---

## Progress Tracking

**Overall Progress:** 0% (0/216 hours completed)

| Phase | Status | Progress | Hours | Complete |
|-------|--------|----------|-------|----------|
| Phase 1 | 🔄 Planning | 0/40 | 0/40 | ❌ |
| Phase 2 | 🔄 Planning | 0/32 | 0/32 | ❌ |
| Phase 3 | 🔄 Planning | 0/24 | 0/24 | ❌ |
| Phase 4 | 🔄 Planning | 0/32 | 0/32 | ❌ |
| Phase 5 | 🔄 Planning | 0/40 | 0/40 | ❌ |
| Phase 6 | 🔄 Planning | 0/48 | 0/48 | ❌ |

**Legend:**
- ✅ Complete
- 🔄 In Progress
- ❌ Not Started
- ⚠️ Blocked
- ⏸️ Paused

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-15  
**Next Review:** Weekly during implementation  
**Owner:** DevOps Team
