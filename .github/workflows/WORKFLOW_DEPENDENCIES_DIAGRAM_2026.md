# GitHub Actions Workflow Dependencies Diagram

**Date:** 2026-02-16  
**Purpose:** Visualize workflow relationships and dependencies

---

## Workflow Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Trigger Sources                              │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                 ┌────────────────┼────────────────┐
                 │                │                │
                 ▼                ▼                ▼
         Push to main      Pull Request      Scheduled/Manual
                 │                │                │
                 │                │                │
    ┌────────────┴────────┐      │     ┌──────────┴──────────┐
    │                     │      │     │                     │
    ▼                     ▼      ▼     ▼                     ▼
┌─────────┐         ┌─────────┐   ┌─────────┐         ┌──────────┐
│ Docker  │         │GraphRAG │   │   MCP   │         │   GPU    │
│ Build   │         │   CI    │   │  Tests  │         │  Tests   │
└────┬────┘         └────┬────┘   └────┬────┘         └────┬─────┘
     │                   │             │                    │
     │                   │             │                    │
     └───────────┬───────┴─────────┬───┴────────────────────┘
                 │                 │
                 ▼                 ▼
         ┌──────────────┐  ┌──────────────┐
         │   Workflow   │  │     Auto     │
         │   Failure    │──│   Healing    │
         └──────────────┘  └──────┬───────┘
                                  │
                                  ▼
                           ┌──────────────┐
                           │   Issue +    │
                           │  Draft PR    │
                           └──────────────┘
```

---

## Critical Path Workflows

**Critical path** = Must pass for production deployment

```
1. docker-build-test.yml
   ├─> Builds Docker images
   └─> Required by: docker-ci.yml, deployment workflows
   
2. graphrag-production-ci.yml
   ├─> Tests GraphRAG document processing
   ├─> Runs security scans
   └─> Gates production deployment
   
3. mcp-integration-tests.yml
   ├─> Tests MCP server endpoints
   ├─> Validates 200+ tools
   └─> Required for MCP features
   
4. gpu-tests-gated.yml
   ├─> Tests GPU acceleration
   ├─> Validates CUDA integration
   └─> Required for ML features
   
5. pdf_processing_ci.yml
   ├─> Tests PDF processing pipeline
   ├─> Validates GraphRAG integration
   └─> Required for document features
```

---

## Workflow Categories & Dependencies

### 1. CI/CD Pipelines (11 workflows)

**Primary Build & Test:**
```
docker-build-test.yml
├─ Depends on: self-hosted x64/arm64 runners
├─ Duration: 20-30 min
└─ Blocks: docker-ci.yml, production deployment

graphrag-production-ci.yml
├─ Depends on: docker-build-test.yml (images)
├─ Duration: 30-40 min
└─ Blocks: staging/production deployment

mcp-integration-tests.yml
├─ Depends on: MCP server, test fixtures
├─ Duration: 25-35 min
└─ Blocks: MCP feature releases

pdf_processing_ci.yml
├─ Depends on: GraphRAG, MCP server
├─ Duration: 35-45 min
└─ Blocks: document processing features

gpu-tests-gated.yml
├─ Depends on: GPU runners (CUDA)
├─ Duration: 30-40 min
└─ Blocks: ML/AI features
```

**Secondary Pipelines:**
```
mcp-dashboard-tests.yml
├─ Depends on: MCP server
├─ Duration: 15-20 min
└─ For: Dashboard UI validation

logic-benchmarks.yml
├─ Depends on: theorem provers (Z3, CVC5, Lean 4)
├─ Duration: 20-30 min
└─ For: Logic system benchmarking

test-datasets-runner.yml
├─ Depends on: dataset infrastructure
├─ Duration: 10-15 min
└─ For: Dataset loading validation
```

### 2. Automation & Monitoring (10 workflows)

**Auto-Healing System:**
```
copilot-agent-autofix.yml (Master)
├─ Triggered by: workflow_run (19 workflows)
├─ Depends on: GitHub Copilot API
├─ Duration: 30-60 min
├─> Creates: GitHub issues
└─> Invokes: issue-to-draft-pr.yml

issue-to-draft-pr.yml
├─ Triggered by: issue creation/reopen
├─ Depends on: copilot-agent-autofix.yml output
├─ Duration: 5-10 min
├─> Creates: Draft PRs
└─> Assigns: @copilot for implementation

workflow-health-check.yml
├─ Triggered by: schedule (hourly)
├─ Monitors: all workflow health
├─ Duration: 5-10 min
└─> Alerts: on failures
```

**Error Monitoring:**
```
cli-error-monitoring-unified.yml
├─ Triggered by: schedule (every 15 min)
├─ Monitors: CLI tool errors
└─> Reports: GitHub issues

javascript-sdk-monitoring-unified.yml
├─ Triggered by: schedule (every 15 min)
├─ Monitors: JavaScript SDK errors
└─> Reports: GitHub issues

mcp-tools-monitoring-unified.yml
├─ Triggered by: schedule (every 15 min)
├─ Monitors: MCP tool errors
└─> Reports: GitHub issues
```

**PR Management:**
```
pr-completion-monitor-unified.yml
├─ Triggered by: PR events
├─ Monitors: PR completion status
└─> Notifies: team on blockers

enhanced-pr-completion-monitor.yml
├─ Triggered by: PR events
├─ Advanced monitoring with predictions
└─> Estimates: completion time

pr-copilot-reviewer.yml
├─ Triggered by: PR creation
├─> Invokes: Copilot for code review
└─> Comments: review suggestions
```

### 3. Infrastructure & Runners (7 workflows)

**Runner Management:**
```
runner-validation-unified.yml (Master)
├─ Validates: x64, arm64 runners
├─ Schedule: hourly
├─ Duration: 5-10 min
└─> Reports: runner status

self-hosted-runner.yml
├─ Tests: self-hosted runner setup
├─ Validates: Docker, tools, permissions
└─> Ensures: runner readiness

arm64-runner.yml
├─ Tests: ARM64 architecture
├─ Validates: multi-arch support
└─> Ensures: ARM64 compatibility

test-github-hosted.yml
├─ Tests: GitHub-hosted runners
├─ Fallback validation
└─> Ensures: fallback ready
```

**Infrastructure Validation:**
```
comprehensive-scraper-validation.yml
├─ Tests: legal/municipal scrapers
├─ Validates: 100+ scraper configs
└─> Ensures: data collection works

scraper-validation.yml
├─ Quick validation
├─ Subset of scrapers
└─> Fast feedback
```

### 4. Documentation & Maintenance (4 workflows)

```
documentation-maintenance.yml
├─ Schedule: daily
├─ Updates: auto-generated docs
├─ Validates: doc accuracy
└─> Creates: PRs for updates

close-stale-draft-prs.yml
├─ Schedule: daily
├─ Closes: stale draft PRs (30+ days)
└─> Maintains: clean PR list

continuous-queue-management.yml
├─ Schedule: every 6 hours
├─ Monitors: issue/PR queue
├─> Prioritizes: critical items
└─> Assigns: to agents

update-autohealing-list.yml
├─ Manual only
├─ Updates: workflow monitoring list
└─> Maintains: auto-healing config
```

### 5. Validation & Quality (4 workflows)

```
github-api-usage-monitor.yml
├─ Schedule: hourly
├─ Monitors: API rate limits
└─> Alerts: on quota nearing

agentic-optimization.yml
├─ PR triggered
├─ Analyzes: code for optimizations
└─> Suggests: improvements

approve-optimization.yml
├─ PR review triggered
├─ Auto-approves: automated PRs
└─> Merges: when safe

fix-docker-permissions.yml
├─ Manual dispatch
├─ Diagnoses: Docker permission issues
└─> Fixes: common problems
```

### 6. Publishing & Release (2 workflows)

```
publish_to_pipy.yml
├─ Tag triggered (v*)
├─ Builds: Python package
├─ Tests: package integrity
└─> Publishes: to PyPI

docker-ci.yml
├─ Depends on: docker-build-test.yml
├─ Tests: Docker Compose
└─> Validates: multi-container setup
```

---

## Dependency Matrix

| Workflow | Depends On | Required By | Can Run Parallel |
|----------|------------|-------------|------------------|
| docker-build-test | None | graphrag-production-ci, docker-ci | ✅ Yes |
| graphrag-production-ci | docker-build-test | Deployment | ⚠️ No (resource intensive) |
| mcp-integration-tests | MCP server | MCP features | ✅ Yes |
| gpu-tests-gated | GPU runners | ML features | ⚠️ No (limited GPU) |
| pdf_processing_ci | GraphRAG, MCP | Document features | ✅ Yes |
| copilot-agent-autofix | Other workflows | issue-to-draft-pr | ✅ Yes |
| issue-to-draft-pr | copilot-agent-autofix | None | ✅ Yes |
| runner-validation-unified | None | All workflows | ✅ Yes |
| documentation-maintenance | None | None | ✅ Yes |

---

## Trigger Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Git Events                               │
└─────────────────────────────────────────────────────────────────┘
     │
     ├─ push to main ──┐
     ├─ push to develop├──> CI/CD Pipelines (11 workflows)
     ├─ PR opened ─────┤    ├─ docker-build-test
     └─ PR updated ────┘    ├─ graphrag-production-ci
                            ├─ mcp-integration-tests
                            ├─ gpu-tests-gated
                            └─ pdf_processing_ci
                                    │
                                    │ (on completion)
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Run Events                           │
└─────────────────────────────────────────────────────────────────┘
     │
     └─ workflow_run completed ──> copilot-agent-autofix.yml
                                         │
                                         │ (if failure)
                                         ▼
                                   ┌──────────────┐
                                   │ Create Issue │
                                   └──────┬───────┘
                                          │
                                          │ (issue created)
                                          ▼
                                   issue-to-draft-pr.yml
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  Draft PR +  │
                                   │  @copilot    │
                                   └──────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Scheduled Events                              │
└─────────────────────────────────────────────────────────────────┘
     │
     ├─ Every 15 min ──> Error Monitoring (3 workflows)
     ├─ Hourly ────────> Runner Validation, API Monitor
     ├─ Daily ─────────> Documentation, Stale PR Cleanup
     └─ Weekly ────────> Comprehensive Validations
```

---

## Critical Dependencies

### External Dependencies

**Required Services:**
- GitHub API (rate limits apply)
- GitHub Copilot API (for auto-healing)
- Docker Hub (for base images)
- PyPI (for package dependencies)

**Required Infrastructure:**
- Self-hosted x64 runners (for builds)
- Self-hosted ARM64 runners (for multi-arch)
- Self-hosted GPU runners (for ML tests)
- GitHub-hosted runners (as fallback)

### Internal Dependencies

**Shared Resources:**
- Docker images (built by docker-build-test.yml)
- Test fixtures (in tests/ directory)
- MCP server (for integration tests)
- GraphRAG system (for document tests)

---

## Workflow Execution Order (Recommended)

For a typical PR, workflows execute in this order:

```
1. ⚡ Immediate (0-5 min)
   ├─ runner-validation-unified.yml
   ├─ pr-completion-monitor-unified.yml
   └─ pr-copilot-reviewer.yml

2. 🏗️ Build Phase (5-20 min)
   ├─ docker-build-test.yml
   └─ test-datasets-runner.yml

3. 🧪 Test Phase (20-45 min)
   ├─ graphrag-production-ci.yml
   ├─ mcp-integration-tests.yml
   ├─ pdf_processing_ci.yml
   └─ gpu-tests-gated.yml (if GPU paths changed)

4. ✅ Validation Phase (45-60 min)
   ├─ mcp-dashboard-tests.yml
   ├─ comprehensive-scraper-validation.yml
   └─ docker-ci.yml

5. 🔧 Auto-Healing (if any failures)
   ├─ copilot-agent-autofix.yml
   └─ issue-to-draft-pr.yml
```

---

## Parallel Execution Groups

**Safe to run in parallel:**
- Group A: graphrag-production-ci, mcp-integration-tests, pdf_processing_ci
- Group B: All monitoring workflows
- Group C: All validation workflows
- Group D: Documentation workflows

**Should NOT run in parallel:**
- docker-build-test + graphrag-production-ci (resource conflict)
- Multiple GPU tests (limited GPU runners)
- Multiple ARM64 tests (limited ARM64 runners)

---

## Concurrency Groups

Workflows use concurrency control to prevent duplicates:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true  # (false for auto-healing)
```

This means:
- ✅ Same workflow on different branches: runs concurrently
- ✅ Different workflows on same branch: runs concurrently
- ❌ Same workflow on same branch: cancels old run
- ⚠️ Auto-healing: preserves runs (doesn't cancel)

---

## Health Monitoring

**Monitored by:**
- workflow-health-check.yml (hourly)
- copilot-agent-autofix.yml (on failures)
- Error monitoring workflows (every 15 min)

**Metrics tracked:**
- Success/failure rates
- Execution duration
- Queue times
- Runner availability
- API usage

---

**Created:** 2026-02-16  
**Maintained by:** DevOps team  
**Review schedule:** Monthly  
**Last review:** 2026-02-16
