# Copilot Invocation: Old vs New Approach

This document compares the old `invoke_copilot_on_pr.py` with the new `invoke_copilot_with_queue.py`.

## Key Differences

| Feature | Old (`invoke_copilot_on_pr.py`) | New (`invoke_copilot_with_queue.py`) |
|---------|--------------------------------|-------------------------------------|
| **Invocation Method** | GitHub CLI (`gh pr comment`) | GitHub Copilot CLI (`gh copilot`) |
| **Queue Management** | ❌ None | ✅ Max 3 concurrent agents |
| **Caching** | ❌ No caching | ✅ 1-hour request cache |
| **Context Generation** | ❌ Basic string instructions | ✅ Structured from JSON |
| **Capacity Checking** | ❌ No checks | ✅ Verifies available slots |
| **Duplicate Prevention** | ❌ No protection | ✅ Hash-based cache keys |
| **Status Reporting** | ❌ Not available | ✅ Full status command |

## Old Approach Issues

### 1. No Queue Management
```bash
# Old: Could spam Copilot with unlimited requests
python3 scripts/invoke_copilot_on_pr.py --pr 123
python3 scripts/invoke_copilot_on_pr.py --pr 124
python3 scripts/invoke_copilot_on_pr.py --pr 125
# All execute immediately, no capacity check
```

### 2. Duplicate Requests
```bash
# Old: Same PR could be invoked multiple times
python3 scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix bug"
python3 scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix bug"
# Both execute, wasting resources
```

### 3. Basic Instructions
```bash
# Old: Simple string instructions
INSTRUCTION="Please implement the fixes. Focus on:
- Fix A
- Fix B
See the full analysis in issue #123"

python3 scripts/invoke_copilot_on_pr.py --pr 123 --instruction "$INSTRUCTION"
```

## New Approach Advantages

### 1. Queue-Managed Invocation
```bash
# New: Respects capacity limits
python3 scripts/invoke_copilot_with_queue.py --pr 123 --context-file analysis.json
# Checks: Are there available agent slots?
# If yes: Proceed
# If no: Queue or wait

# Status check before batch operations
python3 scripts/invoke_copilot_with_queue.py --status
# Shows: 2/3 agents active, 1 slot available
```

### 2. Smart Caching
```bash
# New: Prevents duplicates within 1-hour window
python3 scripts/invoke_copilot_with_queue.py --pr 123 --context-file analysis.json
# Result: Invoked successfully, cached

python3 scripts/invoke_copilot_with_queue.py --pr 123 --context-file analysis.json
# Result: Cache hit, returns cached result (unless --force used)
```

### 3. Structured Context
```bash
# New: Generates comprehensive instructions from JSON
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/failure_analysis.json \
  --context-type failure

# Generated instruction includes:
# - Error Type: Missing Dependency
# - Root Cause: ModuleNotFoundError: No module named 'pytest'
# - Fix Confidence: 90%
# - Captured Values: pytest
# - Recommendations (numbered list)
# - Affected Files (bulleted list)
# - Structured instructions
```

## Migration Guide

### Workflow Update Pattern

#### Before (Old Approach)
```yaml
- name: Invoke Copilot
  run: |
    INSTRUCTION="Please fix the issue..."
    python3 scripts/invoke_copilot_on_pr.py \
      --pr "$PR_NUMBER" \
      --repo "${{ github.repository }}" \
      --instruction "$INSTRUCTION"
```

#### After (New Approach)
```yaml
- name: Invoke Copilot with queue management
  run: |
    python3 scripts/invoke_copilot_with_queue.py \
      --pr "$PR_NUMBER" \
      --context-file /tmp/analysis.json \
      --context-type failure \
      --max-agents 3 || echo "⚠️  Queued or failed"
```

### Context File Examples

#### Failure Analysis Context
```json
{
  "error_type": "Missing Dependency",
  "root_cause": "ModuleNotFoundError: No module named 'pytest'",
  "fix_confidence": 90,
  "captured_values": ["pytest"],
  "recommendations": [
    "Add 'pytest' to requirements.txt",
    "Add pip install step in workflow"
  ],
  "affected_files": [
    "requirements.txt",
    ".github/workflows/test.yml"
  ]
}
```

#### Validation Report Context
```json
{
  "total_scrapers": 10,
  "passed": 7,
  "failed": 3,
  "results": [
    {
      "scraper_name": "legal_scraper",
      "execution_success": false,
      "schema_valid": false,
      "schema_issues": ["missing 'title' field"],
      "hf_compatible": false
    }
  ]
}
```

#### Issue Analysis Context
```json
{
  "issue_number": "123",
  "issue_title": "Fix authentication bug",
  "categories": ["bug", "authentication"],
  "keywords": ["bug", "auth", "login", "error"],
  "complexity": "medium"
}
```

## Command Comparison

### Invoking on PR

#### Old
```bash
python3 scripts/invoke_copilot_on_pr.py \
  --pr 123 \
  --instruction "Fix the bug"
```

#### New
```bash
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/analysis.json \
  --context-type failure
```

### Batch Operations

#### Old
```bash
# No built-in batch support
for PR in 123 124 125; do
  python3 scripts/invoke_copilot_on_pr.py --pr $PR --instruction "Fix"
done
# No capacity checking, could overload system
```

#### New
```bash
# Check capacity first
python3 scripts/invoke_copilot_with_queue.py --status
# Shows available slots

# Invoke respecting queue
for PR in 123 124 125; do
  python3 scripts/invoke_copilot_with_queue.py \
    --pr $PR \
    --context-file /tmp/analysis_${PR}.json \
    --context-type failure
done
# Automatically queues if at capacity
```

### Status Checking

#### Old
```bash
# Not available - had to manually check GitHub
```

#### New
```bash
python3 scripts/invoke_copilot_with_queue.py --status

# Output:
# 📊 Copilot CLI: ✅ Installed
# 📋 Queue Status: 2/3 agents active, 1 slot available
# 💾 Cache Status: 12 cached items
# 💡 Recommendations: Good agent utilization
```

### Force Invocation

#### Old
```bash
# No bypass needed, always executes
python3 scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix"
```

#### New
```bash
# Bypass queue and cache when needed
python3 scripts/invoke_copilot_with_queue.py \
  --pr 123 \
  --context-file /tmp/analysis.json \
  --force
```

## Performance Impact

### Resource Usage

#### Old Approach
- No limits on concurrent requests
- No deduplication
- Potential for quota exhaustion
- Manual monitoring required

#### New Approach
- Max 3 concurrent agents (configurable)
- Automatic deduplication via cache
- Prevents quota exhaustion
- Built-in monitoring and reporting

### Response Times

#### Old Approach
- Immediate invocation (but could compete for resources)
- No visibility into capacity

#### New Approach
- May queue if at capacity (predictable behavior)
- Clear visibility into available slots
- Better resource distribution

## Backwards Compatibility

The old `invoke_copilot_on_pr.py` remains available for:
- Legacy workflows not yet updated
- Cases requiring direct PR comments
- Special use cases outside the queue system

However, **new workflows should use `invoke_copilot_with_queue.py`** for:
- Better resource management
- Improved efficiency through caching
- Richer context from JSON files
- Queue capacity management

## Updated Workflows

The following workflows now use the new approach:

1. **copilot-agent-autofix.yml**
   - Context: Failure analysis JSON
   - Includes: Error type, root cause, recommendations, affected files

2. **comprehensive-scraper-validation.yml**
   - Context: Validation report JSON
   - Includes: Failed scrapers, schema issues, HF compatibility

3. **issue-to-draft-pr.yml**
   - Context: Issue analysis JSON
   - Includes: Categories, keywords, complexity

## Best Practices

### When to Use Old Script
- Quick one-off invocations
- Direct comment posting needed
- Testing/debugging scenarios

### When to Use New Script
- **Always prefer the new script for production workflows**
- Automated batch operations
- High-frequency invocations
- Context-rich scenarios
- Resource-constrained environments

## Troubleshooting

### "Queue at capacity" with old script
**Solution**: Migrate to new script which handles this gracefully.

### Old script still being called
**Solution**: Update workflow YAML files to use new script path.

### Missing context benefits
**Solution**: Generate context JSON files before invocation.

## Future Deprecation

**Timeline**:
- ✅ New script deployed
- 🔄 Migration period (current)
- 📋 Update all workflows
- ⚠️  Deprecation warning for old script
- ❌ Old script removal (TBD)

**Migration Status**:
- ✅ copilot-agent-autofix.yml - MIGRATED
- ✅ comprehensive-scraper-validation.yml - MIGRATED
- ✅ issue-to-draft-pr.yml - MIGRATED
- ⏳ Other workflows - PENDING

## Questions?

For issues or questions about the migration:
1. Check the [Copilot Queue Integration docs](../docs/copilot_queue_integration.md)
2. Review the [script source](invoke_copilot_with_queue.py)
3. Run `python3 scripts/invoke_copilot_with_queue.py --help`
4. Check `python3 scripts/invoke_copilot_with_queue.py --status`
