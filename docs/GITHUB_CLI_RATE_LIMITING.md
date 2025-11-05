# GitHub CLI Rate Limiting and Caching Guide

This guide explains how to use rate limiting and caching with GitHub CLI commands in workflows to prevent hitting API rate limits.

## Problem

When running multiple workflows or making many `gh` CLI calls in quick succession, you can hit GitHub's API rate limits, causing:
- Failed workflow runs
- Delayed processing
- Unnecessary API consumption

## Solution

We provide two mechanisms to prevent rate limiting issues:

### 1. Rate-Limited gh Wrapper Script

**Script:** `scripts/gh_rate_limited.sh`

This bash script wraps `gh` CLI commands with intelligent rate limiting and caching.

**Features:**
- ✅ Automatic delay between API calls (configurable, default: 2 seconds)
- ✅ Caching of read-only operations (5-minute TTL)
- ✅ Exponential backoff on rate limit errors
- ✅ Retry logic for transient failures

**Usage:**

```bash
# Instead of:
gh pr list --limit 10

# Use:
./scripts/gh_rate_limited.sh pr list --limit 10
```

**Configuration (via environment variables):**

```bash
# Delay between calls (seconds)
export GH_RATE_LIMIT_DELAY=2

# Enable/disable caching
export GH_ENABLE_CACHE=true

# Cache TTL (seconds)
export GH_CACHE_TTL=300

# Cache directory
export GH_CACHE_DIR="${HOME}/.gh_cache"

# Enable debug logging
export GH_DEBUG=false
```

**In Workflows:**

```yaml
- name: List PRs with rate limiting
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    GH_RATE_LIMIT_DELAY: 2
    GH_ENABLE_CACHE: true
  run: |
    # Use rate-limited wrapper
    ./scripts/gh_rate_limited.sh pr list --limit 10
    
    # Multiple calls are automatically rate-limited
    ./scripts/gh_rate_limited.sh issue list --limit 10
```

### 2. Python Queue Manager

**Script:** `scripts/queue_manager.py`

For more sophisticated queue management with agent capacity planning.

**Features:**
- ✅ Tracks active Copilot agents
- ✅ Ensures max concurrent agents limit
- ✅ Batched processing
- ✅ Intelligent scheduling

**Usage:**

```python
from scripts.queue_manager import QueueManager

manager = QueueManager(max_agents=3)

# Check active agents
status = manager.get_active_agents()
print(f"Active agents: {status['total']}")

# Get available capacity
available = status['available_slots']
```

### 3. Throttled Copilot Invoker

**Script:** `scripts/invoke_copilot_with_throttling.py`

For invoking Copilot on multiple PRs with throttling.

**Features:**
- ✅ Process PRs in batches
- ✅ Wait between batches
- ✅ Monitor active agents
- ✅ Prevent concurrent agent overload

**Usage:**

```bash
# Process PR with throttling
python scripts/invoke_copilot_with_throttling.py \
    --pr 123 \
    --batch-size 3 \
    --max-concurrent 3
```

## Best Practices

### 1. Use Self-Hosted Runners

All workflows now use self-hosted runners which have higher rate limits and persistent authentication:

```yaml
jobs:
  my-job:
    runs-on: [self-hosted, linux, x64]  # ✅ Good
    # runs-on: ubuntu-latest              # ❌ Avoid for gh CLI heavy workflows
```

### 2. Add Delays Between gh Calls

```bash
# Bad: No delay
gh pr list
gh issue list
gh api /user

# Good: With delays
gh pr list
sleep 2
gh issue list
sleep 2
gh api /user

# Better: Use rate-limited wrapper
./scripts/gh_rate_limited.sh pr list
./scripts/gh_rate_limited.sh issue list
./scripts/gh_rate_limited.sh api /user
```

### 3. Cache Read-Only Operations

The rate-limited wrapper automatically caches:
- `gh pr view`
- `gh pr list`
- `gh issue view`
- `gh issue list`
- `gh api` (GET requests)

### 4. Batch Operations

Instead of processing items one-by-one, batch them:

```yaml
strategy:
  matrix:
    pr_number: [1, 2, 3, 4, 5]
  max-parallel: 3  # ✅ Limit concurrent jobs
  fail-fast: false
```

### 5. Use Queue Management

For workflows that process multiple PRs/issues:

```yaml
- name: Check Queue Capacity
  id: check_queue
  run: |
    python3 << 'EOF'
    from scripts.queue_manager import QueueManager
    
    manager = QueueManager(max_agents=3)
    status = manager.get_active_agents()
    
    print(f"available_slots={status['available_slots']}")
    EOF
```

## Workflow Updates

All workflows have been updated to:

1. ✅ Use self-hosted runners (except `test-github-hosted.yml` which is for testing)
2. ✅ Add rate limiting delays where needed
3. ✅ Use cached operations where appropriate
4. ✅ Implement max-parallel limits in matrix strategies

### Updated Workflows

- ✅ `continuous-queue-management.yml` - Added rate limiting, using self-hosted
- ✅ `enhanced-pr-completion-monitor.yml` - Using self-hosted runners
- ✅ `pr-copilot-monitor.yml` - Using self-hosted runners
- ✅ `fix-docker-permissions.yml` - Using self-hosted runners
- ✅ `scraper-validation.yml` - Using self-hosted runners
- ✅ `update-autohealing-list.yml` - Using self-hosted runners
- ✅ `pdf_processing_ci.yml` - Using self-hosted runners
- ⚪ `test-github-hosted.yml` - Kept on GitHub-hosted for testing purposes

## Monitoring

### Check Rate Limit Status

```bash
# Check current rate limit
gh api rate_limit

# With rate-limited wrapper (cached for 5 minutes)
./scripts/gh_rate_limited.sh api rate_limit
```

### Check Cache Stats

```bash
# View cached items
ls -lah ~/.gh_cache/

# Clear cache
rm -rf ~/.gh_cache/*

# Check cache size
du -sh ~/.gh_cache/
```

## Troubleshooting

### "Rate limit exceeded" errors

1. Check your current rate limit:
   ```bash
   gh api rate_limit
   ```

2. Use the rate-limited wrapper:
   ```bash
   ./scripts/gh_rate_limited.sh <command>
   ```

3. Increase delay between calls:
   ```bash
   export GH_RATE_LIMIT_DELAY=5
   ./scripts/gh_rate_limited.sh <command>
   ```

### Cache not working

1. Check cache directory exists:
   ```bash
   ls -la ~/.gh_cache/
   ```

2. Enable debug logging:
   ```bash
   export GH_DEBUG=true
   ./scripts/gh_rate_limited.sh pr list
   ```

3. Check cache permissions:
   ```bash
   chmod 700 ~/.gh_cache
   ```

### Too many concurrent agents

1. Check active agents:
   ```python
   from scripts.queue_manager import QueueManager
   manager = QueueManager(max_agents=3)
   print(manager.get_active_agents())
   ```

2. Reduce max-parallel in workflows:
   ```yaml
   strategy:
     max-parallel: 2  # Reduce from 3
   ```

## Configuration Examples

### Aggressive Rate Limiting (Conservative)

```bash
export GH_RATE_LIMIT_DELAY=5       # 5 seconds between calls
export GH_ENABLE_CACHE=true         # Enable caching
export GH_CACHE_TTL=600             # 10-minute cache
```

### Balanced (Default)

```bash
export GH_RATE_LIMIT_DELAY=2       # 2 seconds between calls
export GH_ENABLE_CACHE=true         # Enable caching
export GH_CACHE_TTL=300             # 5-minute cache
```

### Minimal Rate Limiting (For testing)

```bash
export GH_RATE_LIMIT_DELAY=1       # 1 second between calls
export GH_ENABLE_CACHE=false        # Disable caching
```

## References

- [GitHub API Rate Limits](https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [Workflow Syntax - max-parallel](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idstrategymax-parallel)
