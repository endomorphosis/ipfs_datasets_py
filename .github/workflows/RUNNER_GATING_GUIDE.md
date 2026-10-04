# Self-Hosted Runner Gating System

## Overview

This system provides a gating mechanism for GitHub Actions workflows that require self-hosted runners. Instead of failing when runners are unavailable, workflows skip gracefully with clear communication.

## Problem Statement

Previously, workflows requiring self-hosted runners (e.g., GPU tests, large dataset operations) would fail when:
- Runners were offline for maintenance
- Runners were overloaded
- Runners weren't configured yet

This created noise in the CI/CD pipeline and made it hard to distinguish real failures from infrastructure issues.

## Solution

The **Runner Gating System** checks runner availability before executing workflows. If runners are unavailable:
- ✅ Workflow **skips gracefully** (doesn't fail)
- ✅ Clear message in workflow summary
- ✅ Other workflows continue normally
- ✅ No false alarms or broken CI/CD

## Components

### 1. Runner Availability Check Script
**Location:** `.github/scripts/check_runner_availability.py`

Python script that queries the GitHub API to check if runners with specific labels are available.

**Usage:**
```bash
python check_runner_availability.py --labels self-hosted,linux,x64,gpu
```

**Exit Codes:**
- `0` - Runners available (proceed with workflow)
- `1` - No runners available (skip gracefully)
- `2` - Error checking runners (API error, auth failure)

### 2. Reusable Workflow Template
**Location:** `.github/workflows/templates/check-runner-availability.yml`

Reusable workflow that can be called from other workflows to check runner availability.

**Inputs:**
- `runner_labels` - Comma-separated list of required labels
- `skip_if_unavailable` - Skip (true) or fail (false) when unavailable

**Outputs:**
- `runners_available` - true/false/unknown
- `should_run` - Whether subsequent jobs should run

### 3. Implementation Pattern

Workflows use the gating system with this pattern:

```yaml
jobs:
  # Gate job - checks runner availability
  check-runner:
    uses: ./.github/workflows/templates/check-runner-availability.yml
    with:
      runner_labels: "self-hosted,linux,x64,gpu"
      skip_if_unavailable: true
  
  # Main job - only runs if gate passes
  main-job:
    needs: [check-runner]
    if: ${{ needs.check-runner.outputs.should_run == 'true' }}
    runs-on: [self-hosted, linux, x64, gpu]
    steps:
      # ... workflow steps ...
```

## How It Works

### Workflow Execution Flow

```
┌─────────────────────────────────────────────┐
│  Workflow Triggered                         │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  Gate Job (on ubuntu-latest)                │
│  - Checkout code                            │
│  - Run availability check script            │
│  - Query GitHub API for runners             │
│  - Filter by required labels                │
│  - Check online status                      │
└─────────────────┬───────────────────────────┘
                  │
         ┌────────┴────────┐
         │                 │
    Runners            No Runners
    Available          Available
         │                 │
         ▼                 ▼
┌─────────────┐   ┌─────────────────┐
│ should_run  │   │ should_run      │
│ = true      │   │ = false         │
└──────┬──────┘   └────────┬────────┘
       │                    │
       ▼                    ▼
┌─────────────┐   ┌──────────────────┐
│ Main Jobs   │   │ Main Jobs        │
│ Execute     │   │ Skipped          │
└─────────────┘   └──────────────────┘
```

### Example: GPU Tests

**Scenario 1: GPU Runner Available**
```
✅ check-gpu-runner: Runners available
✅ gpu-tests: Executed successfully
✅ test-summary: Shows "GPU tests passed"
```

**Scenario 2: GPU Runner Unavailable**
```
⚠️ check-gpu-runner: No runners available
⏭️ gpu-tests: Skipped
✅ test-summary: Shows "GPU tests skipped (runner not available)"
```

**Scenario 3: API Error**
```
⚠️ check-gpu-runner: Error checking runners
⏭️ gpu-tests: Skipped
✅ test-summary: Shows "GPU tests skipped (could not verify runner)"
```

## Implemented Workflows

The following workflows have been updated with runner gating:

### GPU Tests (gpu-tests-gated.yml)
- **Runner:** `self-hosted, linux, x64, gpu`
- **Purpose:** GPU-accelerated testing, CUDA operations
- **Behavior:** Skips if no GPU runner available

### GraphRAG Production CI (graphrag-production-ci-gated.yml)
- **Runner:** `self-hosted, linux, x64`
- **Purpose:** Large dataset operations, knowledge graph processing
- **Behavior:** Skips if no runners available

### Docker Build & Test (docker-build-test-gated.yml)
- **Runner:** `self-hosted, linux, x64`
- **Purpose:** Multi-platform Docker builds
- **Behavior:** Skips if no runners available

### MCP Integration Tests (mcp-integration-tests-gated.yml)
- **Runner:** `self-hosted, linux, x64`
- **Purpose:** Integration testing with large datasets
- **Behavior:** Skips if no runners available

### PDF Processing CI (pdf_processing_ci-gated.yml)
- **Runner:** `self-hosted, linux, x64`
- **Purpose:** PDF processing with GraphRAG
- **Behavior:** Skips if no runners available

## Configuration

### Workflow Configuration

**Skip gracefully (recommended):**
```yaml
check-runner:
  uses: ./.github/workflows/templates/check-runner-availability.yml
  with:
    runner_labels: "self-hosted,linux,x64"
    skip_if_unavailable: true  # Skip if unavailable
```

**Fail if unavailable:**
```yaml
check-runner:
  uses: ./.github/workflows/templates/check-runner-availability.yml
  with:
    runner_labels: "self-hosted,linux,x64"
    skip_if_unavailable: false  # Fail if unavailable
```

### Runner Labels

Common label combinations:

| Runner Type | Labels | Use Case |
|-------------|--------|----------|
| Standard x64 | `self-hosted,linux,x64` | General compute |
| ARM64 | `self-hosted,linux,arm64` | ARM architecture |
| GPU | `self-hosted,linux,x64,gpu` | CUDA, machine learning |
| High Memory | `self-hosted,linux,x64,high-mem` | Large datasets |

### Script Configuration

Environment variables for the check script:

```bash
export GITHUB_TOKEN="ghp_xxxxx"           # Required: GitHub API token
export GITHUB_REPOSITORY="owner/repo"     # Required: Repository name

# Optional:
python check_runner_availability.py \
  --labels "self-hosted,linux,x64,gpu" \
  --retries 3 \                          # Number of retry attempts
  --delay 2 \                            # Delay between retries (seconds)
  --json                                  # Output as JSON
```

## Benefits

### For CI/CD Pipeline
- ✅ **No false failures** - Unavailable runners don't break builds
- ✅ **Clear communication** - Summaries explain why jobs skipped
- ✅ **Reliable metrics** - Test success rates reflect actual code quality
- ✅ **Graceful degradation** - Workflows adapt to infrastructure state

### For Developers
- ✅ **Less noise** - No alerts for infrastructure issues
- ✅ **Faster debugging** - Distinguish code failures from runner issues
- ✅ **Better visibility** - Clear runner status in workflow summaries
- ✅ **Predictable behavior** - Consistent handling of runner unavailability

### For Infrastructure
- ✅ **Maintenance windows** - Take runners offline without breaking CI
- ✅ **Load management** - Prevent overload during runner provisioning
- ✅ **Cost optimization** - Scale down runners without failing workflows
- ✅ **Gradual rollout** - Deploy new runners without disrupting existing workflows

## Monitoring

### Workflow Summaries

Each gated workflow provides a detailed summary:

```markdown
## 🏃 Runner Availability Check

**Required labels:** self-hosted,linux,x64,gpu

✅ **Status:** Runners available
🎯 **Action:** Workflow will proceed

---

**Configuration:**
- Skip if unavailable: true
- Repository: endomorphosis/ipfs_datasets_py
- Triggered by: push
```

### Test Summary

Summary jobs aggregate results:

```markdown
## 🧪 Test Results Summary

### Runner Availability
| Runner Type | Available | Workflow Action |
|-------------|-----------|-----------------|
| GPU Runner (x64 + gpu) | true | Ran |
| Standard Runner (x64) | true | Ran |

### Test Results
| Test Suite | Status |
|------------|--------|
| GPU Tests | success |
| CPU Tests | success |
| Docker GPU Tests | success |
```

## Troubleshooting

### Gate Job Fails

**Symptom:** Gate job shows "Error checking runners"

**Causes:**
1. GitHub API rate limiting
2. Authentication failure
3. Network timeout

**Solutions:**
```bash
# Check API rate limit
gh api rate_limit

# Verify token permissions
gh auth status

# Check repository access
gh api /repos/owner/repo/actions/runners
```

### Jobs Always Skip

**Symptom:** Jobs skip even when runners are online

**Causes:**
1. Label mismatch
2. Runners in "offline" status
3. Wrong repository

**Solutions:**
```bash
# List runners and their labels
gh api /repos/owner/repo/actions/runners | jq '.runners[] | {name, status, labels: [.labels[].name]}'

# Check specific runner status
gh api /repos/owner/repo/actions/runners/{runner_id}

# Verify labels match
python check_runner_availability.py --labels "self-hosted,linux,x64" --json
```

### False Positives

**Symptom:** Gate passes but jobs fail to find runner

**Causes:**
1. Runner went offline after check
2. Runner busy with other jobs
3. Network partition

**Solutions:**
- Increase check retries
- Add delay between check and execution
- Monitor runner queue depth
- Set up runner health checks

## Best Practices

### DO's ✅

1. **Always use for dataset-heavy operations**
   - Large file processing
   - GPU-intensive tasks
   - Memory-intensive operations

2. **Set appropriate timeouts**
   ```yaml
   timeout-minutes: 60  # Prevent indefinite hangs
   ```

3. **Provide clear documentation**
   - Explain why runners are needed
   - Document runner requirements
   - Link to setup guides

4. **Monitor runner health**
   - Regular health checks
   - Capacity planning
   - Performance metrics

### DON'Ts ❌

1. **Don't use for lightweight tasks**
   - Use GitHub-hosted runners for simple tests
   - Reserve self-hosted for heavy workloads

2. **Don't hardcode runner names**
   - Use labels, not specific runner names
   - Allows flexible runner assignment

3. **Don't skip error handling**
   - Always check gate outputs
   - Handle edge cases gracefully

4. **Don't forget maintenance windows**
   - Plan runner updates
   - Communicate downtime
   - Use graceful skip during maintenance

## Migration Guide

### Converting Existing Workflows

**Before (no gating):**
```yaml
jobs:
  test:
    runs-on: [self-hosted, linux, x64, gpu]
    steps:
      - uses: actions/checkout@v4
      # ... test steps ...
```

**After (with gating):**
```yaml
jobs:
  check-runner:
    uses: ./.github/workflows/templates/check-runner-availability.yml
    with:
      runner_labels: "self-hosted,linux,x64,gpu"
      skip_if_unavailable: true
  
  test:
    needs: [check-runner]
    if: ${{ needs.check-runner.outputs.should_run == 'true' }}
    runs-on: [self-hosted, linux, x64, gpu]
    steps:
      - uses: actions/checkout@v4
      # ... test steps ...
```

### Testing Changes

1. **Test with runners available:**
   ```bash
   gh workflow run workflow-name.yml
   # Verify: Jobs execute normally
   ```

2. **Test with runners unavailable:**
   - Temporarily take runners offline
   - Trigger workflow
   - Verify: Jobs skip gracefully

3. **Test error conditions:**
   - Invalid token
   - Network timeout
   - API rate limit

## Future Enhancements

### Planned Features

1. **Runner capacity check**
   - Check queue depth
   - Predict wait time
   - Skip if queue too long

2. **Runner health metrics**
   - CPU usage
   - Memory usage
   - Disk space
   - Network latency

3. **Intelligent scheduling**
   - Prefer least-busy runners
   - Balance load across runners
   - Priority-based queuing

4. **Dashboard integration**
   - Real-time runner status
   - Historical availability
   - Capacity planning

5. **Automated alerting**
   - Notify when runners offline
   - Alert on capacity issues
   - Report on skip patterns

## Support

### Documentation
- [COMPREHENSIVE_IMPROVEMENT_PLAN.md](./COMPREHENSIVE_IMPROVEMENT_PLAN.md) - Full improvement plan
- [IMPROVEMENT_QUICK_REFERENCE.md](./IMPROVEMENT_QUICK_REFERENCE.md) - Quick reference guide
- [README.md](./README.md) - Main workflows documentation

### Getting Help

**Questions?** Create an issue with the `workflow-gating` label

**Need runner setup?** See [runner setup guide](../../docs/guides/deployment/runner_setup.md)

**Emergency?** Contact DevOps on-call

---

**Version:** 1.0  
**Last Updated:** 2026-02-15  
**Maintained By:** DevOps Team
