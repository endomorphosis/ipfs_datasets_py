# Retry Logic and Error Handling Guide for GitHub Actions Workflows

**Date:** 2026-02-16  
**Purpose:** Best practices for implementing retry logic and error handling in workflows

---

## Executive Summary

This guide provides patterns and recommendations for adding retry logic and error handling to GitHub Actions workflows to improve reliability and reduce flaky test failures.

**Key Statistics:**
- 31 workflows identified with retry opportunities
- 80 steps that could benefit from retry logic
- 5 common patterns for flaky operations

---

## Table of Contents

1. [Retry Logic Patterns](#retry-logic-patterns)
2. [Error Handling Patterns](#error-handling-patterns)
3. [Implementation Examples](#implementation-examples)
4. [Testing Retry Logic](#testing-retry-logic)
5. [Monitoring and Metrics](#monitoring-and-metrics)
6. [Recommendations](#recommendations)

---

## Retry Logic Patterns

### 1. Using nick-fields/retry Action (Recommended)

**Best for:** Single command operations, API calls, downloads

```yaml
- name: Install dependencies with retry
  uses: nick-fields/retry@v2
  with:
    timeout_minutes: 10
    max_attempts: 3
    retry_wait_seconds: 30
    command: pip install -r requirements.txt
```

**Configuration Options:**
- `timeout_minutes`: Maximum time per attempt
- `max_attempts`: Number of retry attempts (2-3 recommended)
- `retry_wait_seconds`: Wait time between attempts (exponential backoff available)
- `retry_on`: Specific exit codes to retry on (optional)
- `warning_on_retry`: Show warning on retry (default: true)

### 2. Manual Retry with Bash Loop

**Best for:** Complex operations, conditional retries

```yaml
- name: Install with manual retry
  run: |
    MAX_ATTEMPTS=3
    ATTEMPT=0
    until pip install -r requirements.txt; do
      ATTEMPT=$((ATTEMPT + 1))
      if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        echo "Failed after $MAX_ATTEMPTS attempts"
        exit 1
      fi
      echo "Attempt $ATTEMPT failed, retrying in 30 seconds..."
      sleep 30
    done
```

### 3. Conditional Retry Based on Error Type

```yaml
- name: Smart retry based on error
  run: |
    set +e  # Don't exit on error
    
    for i in {1..3}; do
      pip install -r requirements.txt 2>&1 | tee install.log
      EXIT_CODE=$?
      
      if [ $EXIT_CODE -eq 0 ]; then
        echo "Success!"
        exit 0
      fi
      
      # Check if error is retryable (network, timeout)
      if grep -q "timeout\|network\|ConnectionError" install.log; then
        echo "Retryable error detected, attempt $i/3"
        sleep $((i * 15))  # Exponential backoff
      else
        echo "Non-retryable error, failing immediately"
        exit $EXIT_CODE
      fi
    done
    
    echo "Failed after 3 attempts"
    exit 1
```

---

## Error Handling Patterns

### 1. Continue on Error with Notification

```yaml
- name: Operation that may fail
  continue-on-error: true
  id: flaky_step
  run: |
    # Your operation here
    
- name: Notify on failure
  if: steps.flaky_step.outcome == 'failure'
  run: |
    echo "::warning::Step failed but continuing workflow"
    # Optional: Send notification to Slack, email, etc.
```

### 2. Graceful Degradation

```yaml
- name: Try primary method
  id: primary
  continue-on-error: true
  run: |
    # Primary operation (e.g., download from CDN)
    
- name: Fallback method
  if: steps.primary.outcome == 'failure'
  run: |
    echo "Primary method failed, using fallback"
    # Fallback operation (e.g., download from mirror)
```

### 3. Error Context and Debugging

```yaml
- name: Operation with error context
  run: |
    set -euxo pipefail  # Exit on error, show commands, fail on pipe errors
    
    # Your operation
    
  env:
    # Add debugging information
    RUST_BACKTRACE: 1
    PYTHONVERBOSE: 1
    DEBUG: "*"
```

### 4. Cleanup on Failure

```yaml
- name: Setup resources
  id: setup
  run: |
    # Create temporary resources
    
- name: Main operation
  run: |
    # Your operation
    
- name: Cleanup on failure
  if: failure() && steps.setup.outcome == 'success'
  run: |
    # Cleanup temporary resources
```

---

## Implementation Examples

### Example 1: Pip Installation with Retry

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - name: Install dependencies with retry
        uses: nick-fields/retry@v2
        with:
          timeout_minutes: 10
          max_attempts: 3
          retry_wait_seconds: 30
          command: |
            pip install --upgrade pip
            pip install -r requirements.txt
```

### Example 2: Docker Build with Retry and Fallback

```yaml
- name: Build Docker image with retry
  uses: nick-fields/retry@v2
  with:
    timeout_minutes: 30
    max_attempts: 2
    retry_wait_seconds: 60
    command: |
      docker build -t myimage:latest .
      
- name: Fallback to docker-compose
  if: failure()
  run: |
    echo "Docker build failed, trying docker-compose"
    docker-compose build
```

### Example 3: GitHub API with Exponential Backoff

```yaml
- name: GitHub API call with retry
  run: |
    MAX_ATTEMPTS=5
    ATTEMPT=0
    WAIT_TIME=5
    
    until gh api /repos/${{ github.repository }}/issues; do
      ATTEMPT=$((ATTEMPT + 1))
      if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        echo "Failed after $MAX_ATTEMPTS attempts"
        exit 1
      fi
      
      echo "API call failed, waiting ${WAIT_TIME}s before retry $ATTEMPT/$MAX_ATTEMPTS"
      sleep $WAIT_TIME
      WAIT_TIME=$((WAIT_TIME * 2))  # Exponential backoff
    done
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Example 4: Network Download with Retry

```yaml
- name: Download with retry
  uses: nick-fields/retry@v2
  with:
    timeout_minutes: 5
    max_attempts: 3
    retry_wait_seconds: 15
    command: |
      curl -fsSL -o downloaded_file.tar.gz \
        https://example.com/file.tar.gz
      
- name: Verify download
  run: |
    if [ ! -f downloaded_file.tar.gz ]; then
      echo "Download failed"
      exit 1
    fi
    
    if [ $(stat -c%s downloaded_file.tar.gz) -lt 1000 ]; then
      echo "Downloaded file is too small, likely corrupted"
      exit 1
    fi
```

---

## Testing Retry Logic

### 1. Intentional Failure Test

```yaml
- name: Test retry logic
  if: github.event_name == 'workflow_dispatch'
  uses: nick-fields/retry@v2
  with:
    timeout_minutes: 1
    max_attempts: 3
    retry_wait_seconds: 5
    command: |
      # Fail on first 2 attempts, succeed on 3rd
      ATTEMPT_FILE=/tmp/attempt_count
      ATTEMPTS=$(cat $ATTEMPT_FILE 2>/dev/null || echo 0)
      ATTEMPTS=$((ATTEMPTS + 1))
      echo $ATTEMPTS > $ATTEMPT_FILE
      
      echo "Attempt $ATTEMPTS"
      if [ $ATTEMPTS -lt 3 ]; then
        echo "Intentional failure for testing"
        exit 1
      fi
      
      echo "Success on attempt $ATTEMPTS"
```

### 2. Monitor Retry Metrics

```yaml
- name: Track retry statistics
  id: operation_with_retry
  uses: nick-fields/retry@v2
  with:
    timeout_minutes: 10
    max_attempts: 3
    retry_wait_seconds: 30
    command: your-command-here
    
- name: Report retry metrics
  if: always()
  run: |
    echo "Operation outcome: ${{ steps.operation_with_retry.outcome }}"
    echo "Attempts made: ${{ steps.operation_with_retry.outputs.total_attempts }}"
    # Log to monitoring system
```

---

## Monitoring and Metrics

### Recommended Metrics to Track

1. **Retry Success Rate**
   - Operations that succeed after retry
   - Average number of attempts needed

2. **Failure Patterns**
   - Common error types causing retries
   - Time of day when retries are most common
   - Workflows with highest retry rates

3. **Performance Impact**
   - Additional time added by retries
   - Cost impact of retry operations

### Example Monitoring Setup

```yaml
- name: Report retry metrics to monitoring
  if: always()
  run: |
    # Send metrics to your monitoring system
    curl -X POST https://monitoring.example.com/metrics \
      -H "Content-Type: application/json" \
      -d '{
        "workflow": "${{ github.workflow }}",
        "job": "${{ github.job }}",
        "outcome": "${{ steps.operation.outcome }}",
        "attempts": "${{ steps.operation.outputs.total_attempts }}",
        "duration": "${{ steps.operation.outputs.duration }}"
      }'
```

---

## Recommendations

### When to Add Retry Logic

✅ **DO add retry for:**
- Package installations (pip, npm, cargo)
- Network operations (downloads, API calls)
- Docker operations (build, push, pull)
- GitHub API calls
- Database connections
- External service integrations

❌ **DON'T add retry for:**
- Compilation errors (code issues)
- Test failures (logic issues)
- Syntax errors
- Permission/authentication errors (won't resolve with retry)

### Configuration Guidelines

| Operation Type | Timeout | Max Attempts | Wait Time | Notes |
|----------------|---------|--------------|-----------|-------|
| Pip install | 10 min | 3 | 30s | Use pip cache |
| npm install | 10 min | 3 | 30s | Use npm cache |
| Docker build | 30 min | 2 | 60s | Long timeout for large builds |
| GitHub API | 5 min | 5 | 5-30s | Use exponential backoff |
| Downloads | 5 min | 3 | 15s | Verify download after |
| Tests | 15 min | 1 | N/A | Don't retry tests |

### Best Practices

1. **Always set timeout_minutes** - Prevent infinite hangs
2. **Use appropriate max_attempts** - Usually 2-3 is sufficient
3. **Implement exponential backoff** - For API rate limits
4. **Log retry attempts** - For debugging and monitoring
5. **Notify on repeated failures** - Alert team if pattern emerges
6. **Document retry rationale** - Explain why retry is needed
7. **Test retry logic** - Ensure it works as expected
8. **Monitor retry metrics** - Track effectiveness over time

---

## Common Flaky Operations Analysis

Based on analysis of 53 workflows, the following operations most commonly need retry logic:

### Top 5 Flaky Operation Types

1. **Pip installs** - 35 instances
   - Network timeouts during package download
   - PyPI rate limiting
   - Dependency resolution conflicts

2. **Docker builds** - 18 instances
   - Base image pull failures
   - Network timeouts
   - Layer caching issues

3. **GitHub API calls** - 15 instances
   - Rate limiting
   - Temporary API unavailability
   - Network issues

4. **npm installs** - 8 instances
   - Registry unavailability
   - Package download failures
   - Integrity check failures

5. **Downloads (curl/wget)** - 4 instances
   - Network timeouts
   - Source unavailability
   - Incomplete downloads

---

## Implementation Roadmap

### Phase 1: Critical Operations (High Priority)
- [ ] Add retry to all pip installations (35 steps)
- [ ] Add retry to all Docker builds (18 steps)
- [ ] Add retry to GitHub API calls (15 steps)

### Phase 2: Secondary Operations (Medium Priority)
- [ ] Add retry to npm installations (8 steps)
- [ ] Add retry to downloads (4 steps)

### Phase 3: Error Handling (Low Priority)
- [ ] Add graceful degradation patterns
- [ ] Implement failure notifications
- [ ] Add cleanup on failure handlers

**Total Estimated Time:** 3-4 hours
**Expected Benefit:** 30-50% reduction in flaky failures

---

## Tools and Resources

### Scripts Created
- `add_retry_logic.py` - Analyze and suggest retry logic additions
- Run: `python .github/scripts/add_retry_logic.py --dry-run`

### External Actions
- [nick-fields/retry@v2](https://github.com/nick-fields/retry) - Recommended retry action
- [actions/cache@v4](https://github.com/actions/cache) - Reduce need for retries

### Documentation
- [GitHub Actions: continue-on-error](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idstepscontinue-on-error)
- [GitHub Actions: Conditional execution](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idstepsif)

---

## Conclusion

Implementing retry logic and proper error handling significantly improves workflow reliability. Focus on high-traffic operations first, monitor effectiveness, and iterate based on real-world performance.

**Next Steps:**
1. Review identified retry opportunities
2. Prioritize critical workflows
3. Implement retry logic incrementally
4. Test and monitor effectiveness
5. Document learnings and patterns

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Maintained By:** DevOps Team
