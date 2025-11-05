# GitHub Copilot Queue Integration

This document describes the queue-managed GitHub Copilot CLI integration used in workflow auto-healing.

## Overview

The `scripts/invoke_copilot_with_queue.py` script provides a queue-managed approach to invoking GitHub Copilot, preventing overload and avoiding duplicate requests through intelligent caching.

## Key Features

### 1. Queue Management
- **Maximum Concurrent Agents**: Default 3 (configurable)
- **Capacity Checking**: Verifies available slots before invocation
- **Active Agent Monitoring**: Tracks ongoing Copilot tasks via GitHub API
- **Utilization Reporting**: Provides queue status and recommendations

### 2. Request Caching
- **Cache Duration**: 1 hour by default
- **Cache Key**: Based on PR number and instruction hash
- **Cache Location**: `/tmp/copilot_cache/`
- **Duplicate Prevention**: Skips identical requests within cache window

### 3. Context-Aware Instructions
The script generates comprehensive instructions from three types of context:

#### Failure Analysis Context
From `analyze_workflow_failure.py` output:
- Error type and root cause
- Fix confidence level
- Captured values (e.g., package names)
- Specific recommendations
- Affected files list

#### Validation Report Context
From `comprehensive_scraper_validation.py` output:
- Total scrapers and pass/fail counts
- Failed scraper details with specific issues
- Schema validation problems
- HuggingFace compatibility issues

#### Issue Analysis Context
From `issue-to-draft-pr.yml` processing:
- Issue number and title
- Categorization (bug, feature, etc.)
- Extracted keywords
- Priority and complexity estimates

## Usage

### Basic Invocation

```bash
# Invoke Copilot on a PR with failure analysis
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/failure_analysis.json \
  --context-type failure

# Invoke with validation report
python3 scripts/invoke_copilot_with_queue.py \
  --pr 456 \
  --context-file validation_results/report.json \
  --context-type validation

# Invoke with issue context
python3 scripts/invoke_copilot_with_queue.py \
  --pr 789 \
  --context-file /tmp/issue_analysis.json \
  --context-type issue
```

### Advanced Options

```bash
# Force invocation (bypass queue and cache)
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/analysis.json \
  --force

# Disable caching
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --instruction "Custom instruction" \
  --no-cache

# Adjust max concurrent agents
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/analysis.json \
  --max-agents 5

# Dry run (preview without execution)
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/analysis.json \
  --dry-run
```

### Status Checking

```bash
# Check Copilot CLI, queue, and cache status
python3 scripts/invoke_copilot_with_queue.py --status
```

Example output:
```
================================================================================
🤖 Copilot Invoker Status
================================================================================

📊 Copilot CLI:
  Installed: ✅
  GitHub CLI: ✅
  Version: gh-copilot 0.5.3-beta

📋 Queue Status:
  Active agents: 2/3
  Available slots: 1
  Utilization: 66.7%
  Queue size: 5

💾 Cache Status:
  Enabled: ✅
  Cached items: 12
  Location: /tmp/copilot_cache
  Copilot cache hits: 8
  Copilot cache misses: 15

💡 Recommendations:
  🟢 Good agent utilization
  🚀 Ready to assign 1 new tasks
================================================================================
```

## Integration in Workflows

### copilot-agent-autofix.yml

```yaml
- name: Invoke Copilot with failure analysis
  run: |
    python3 scripts/invoke_copilot_with_queue.py \
      --pr "$PR_NUMBER" \
      --context-file /tmp/failure_analysis.json \
      --context-type failure \
      --max-agents 3 || echo "⚠️  Copilot invocation queued or failed"
```

**Context Generated**:
- Error type (e.g., "Missing Dependency")
- Root cause with captured values
- Fix confidence percentage
- Specific recommendations from analyzer
- List of affected files

### comprehensive-scraper-validation.yml

```yaml
- name: Invoke Copilot with validation report
  run: |
    if [ -f "validation_results/comprehensive_validation_report.json" ]; then
      python3 scripts/invoke_copilot_with_queue.py \
        --pr "$PR_NUMBER" \
        --context-file validation_results/comprehensive_validation_report.json \
        --context-type validation \
        --max-agents 3
    fi
```

**Context Generated**:
- Validation summary (passed/failed counts)
- Failed scraper details
- Schema issues (missing required fields)
- HuggingFace compatibility problems
- Data quality scores

### issue-to-draft-pr.yml

```yaml
- name: Invoke Copilot with issue context
  run: |
    if [ -f "/tmp/issue_analysis.json" ]; then
      python3 scripts/invoke_copilot_with_queue.py \
        --pr "$PR_NUMBER" \
        --context-file /tmp/issue_analysis.json \
        --context-type issue \
        --max-agents 3
    fi
```

**Context Generated**:
- Issue number and title
- Categories (bug, feature, documentation, etc.)
- Extracted keywords
- Complexity estimation
- Priority indicators

## Queue Management Strategy

The queue manager implements a smart capacity planning algorithm:

1. **Active Agent Detection**: Scans for recent @copilot mentions in PRs/issues
2. **Capacity Calculation**: `available_slots = max_agents - active_count`
3. **Work Distribution**: Prioritizes PRs over issues when slots available
4. **Utilization Monitoring**: Tracks and reports agent utilization percentage

### Queue States

- **🟢 Low Utilization (<50%)**: System ready for more work
- **🟡 Good Utilization (50-99%)**: Optimal operating range
- **🔴 At Capacity (100%)**: All agents busy, wait for completion

## Caching Strategy

### Cache Key Generation
```python
cache_key = f"pr_{pr_number}_{instruction_hash}"
instruction_hash = md5(instruction.encode()).hexdigest()[:12]
```

### Cache Validation
- Entries expire after 1 hour (3600 seconds)
- Expired entries are ignored, new invocation proceeds
- Cache can be bypassed with `--force` flag

### Cache Location
```
/tmp/copilot_cache/
├── pr_123_a1b2c3d4e5f6.json
├── pr_456_f6e5d4c3b2a1.json
└── pr_789_1a2b3c4d5e6f.json
```

## Error Handling

### Queue at Capacity
```
⚠️  No queue capacity available
Recommendation: Wait for active agents to complete or use --force
```

### Copilot CLI Not Installed
```
GitHub Copilot CLI not installed, attempting installation...
```

### Context File Not Found
```
Falls back to basic instruction without structured context
```

### GitHub Token Missing (CI)
```
Requires GH_TOKEN environment variable in GitHub Actions
Set: env.GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Best Practices

### 1. Always Use Context When Available
Structured context from JSON files produces better results than generic instructions.

### 2. Monitor Queue Status
Check status before batch operations to avoid overwhelming the system.

### 3. Respect Cache
Don't use `--force` unless genuinely needed - cache improves efficiency.

### 4. Set Appropriate Agent Limits
Default of 3 concurrent agents is good for most repositories. Adjust based on:
- Repository activity level
- Available Copilot quota
- Desired response time

### 5. Use Dry Run for Testing
Test workflows with `--dry-run` before production use.

## Troubleshooting

### "Queue at capacity" errors
**Solution**: Wait for active agents to complete, or increase `--max-agents` limit.

### Copilot responses seem generic
**Solution**: Ensure context files are being generated and passed correctly.

### High cache miss rate
**Solution**: Normal for first run. Rate should improve over time.

### Script fails in CI
**Solution**: Ensure `GH_TOKEN` environment variable is set in workflow.

### Copilot CLI not found
**Solution**: Script auto-installs, but requires gh CLI and authentication.

## Monitoring

### Key Metrics
- **Active Agents**: Current concurrent Copilot tasks
- **Queue Size**: Total work items pending
- **Cache Hit Rate**: Efficiency of duplicate prevention
- **Utilization %**: How busy the system is

### Alerts
The system provides recommendations based on these metrics:
- Low utilization: Suggests triggering more work
- High queue: Suggests increasing capacity
- Full capacity: Recommends monitoring

## Security Considerations

1. **No Secrets in Context**: Never include secrets in context JSON files
2. **Cache Isolation**: Cache stored in /tmp, cleared on reboot
3. **Queue Limits**: Prevent resource exhaustion
4. **Token Security**: GH_TOKEN only used for queue status checks

## Future Enhancements

Potential improvements:
- Persistent cache with database backend
- Priority queue for urgent fixes
- Metrics dashboard
- Auto-scaling based on queue size
- Multi-repository coordination
- Cost tracking per invocation

## Related Files

- `scripts/invoke_copilot_with_queue.py` - Main invoker script
- `scripts/queue_manager.py` - Queue management utilities
- `ipfs_datasets_py/utils/copilot_cli.py` - Copilot CLI wrapper
- `.github/scripts/analyze_workflow_failure.py` - Failure analyzer
- `.github/scripts/generate_workflow_fix.py` - Fix proposal generator
- `.github/workflows/copilot-agent-autofix.yml` - Auto-fix workflow
- `.github/workflows/comprehensive-scraper-validation.yml` - Validation workflow
- `.github/workflows/issue-to-draft-pr.yml` - Issue converter workflow

## References

- [GitHub Copilot CLI Documentation](https://docs.github.com/en/copilot/github-copilot-in-the-cli)
- [Queue Manager Documentation](../scripts/queue_manager.py)
- [Workflow Auto-Fix System](../.github/workflows/README.md)
