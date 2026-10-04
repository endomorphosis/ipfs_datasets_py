# PR Copilot Monitor - Throttled Invocation

## Overview

The PR Copilot Monitor workflow has been updated to properly invoke the GitHub Copilot CLI and implement intelligent throttling to prevent API rate limiting.

## Changes Made

### 1. New Throttled Copilot Invoker Script

**File**: `scripts/invoke_copilot_with_throttling.py`

This new script replaces the old `invoke_copilot_coding_agent_on_prs.py` and provides:

- **Proper Copilot CLI Integration**: Uses the actual `CopilotCLI` class from `ipfs_datasets_py.utils.copilot_cli` instead of just posting `@copilot` mentions
- **Intelligent Throttling**: Processes PRs in controlled batches to prevent API overload
- **Active Agent Monitoring**: Checks for active copilot agents before processing new PRs
- **Fallback Mechanism**: Falls back to `@copilot` mentions if CLI extension is unavailable
- **Configurable Parameters**: Supports customization of batch size, max concurrent agents, and check intervals

### 2. Updated Workflow

**File**: `.github/workflows/pr-copilot-monitor.yml`

The workflow now:

- Uses the new throttled script instead of the old one
- Configures throttling parameters: `--batch-size 3 --max-concurrent 3 --check-interval 30`
- Provides clearer summary messages about the throttling approach

## Configuration

The script supports the following configuration options:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--batch-size` | 3 | Number of PRs to process in each batch |
| `--max-concurrent` | 3 | Maximum number of concurrent copilot agents |
| `--check-interval` | 30 | Seconds to wait between agent status checks |
| `--dry-run` | false | Test mode without making actual changes |
| `--pr` | none | Specific PR number(s) to process |

## How It Works

1. **Batch Processing**: PRs are processed in batches of 3 at a time
2. **Agent Monitoring**: Before each batch, the script checks how many copilot agents are currently active
3. **Throttling**: If 3 agents are already running, the script waits before processing the next batch
4. **Invocation**: The script uses the Copilot CLI to properly invoke copilot on each PR
5. **Fallback**: If the CLI extension is not available, it falls back to posting `@copilot` mentions

## Testing

Comprehensive tests have been added in:

- `tests/test_invoke_copilot_with_throttling.py`: Full test suite with 9 test cases
- `scripts/test_throttling.py`: Standalone unit tests for throttling logic

All tests pass successfully and validate:

- Script existence and executability
- Help output and command-line arguments
- Dry-run mode functionality
- Class instantiation and configuration
- Throttling logic implementation
- CopilotCLI integration

## Usage Examples

### Process all open PRs with throttling
```bash
python scripts/invoke_copilot_with_throttling.py
```

### Process specific PR
```bash
python scripts/invoke_copilot_with_throttling.py --pr 199
```

### Test without making changes
```bash
python scripts/invoke_copilot_with_throttling.py --dry-run
```

### Custom throttling configuration
```bash
python scripts/invoke_copilot_with_throttling.py \
  --batch-size 5 \
  --max-concurrent 5 \
  --check-interval 60
```

## Benefits

1. **Prevents API Rate Limiting**: Controlled batch processing prevents overwhelming GitHub's API
2. **Proper CLI Integration**: Uses actual copilot CLI tool instead of just mentions
3. **Better Resource Management**: Ensures no more than 3 agents run concurrently
4. **Configurable**: Easy to adjust throttling parameters based on needs
5. **Robust**: Falls back to @copilot mentions if CLI is unavailable
6. **Tested**: Comprehensive test suite ensures reliability

## Migration Notes

The old script `invoke_copilot_coding_agent_on_prs.py` is still available but no longer used by the workflow. The new script provides all the same functionality plus throttling and better CLI integration.

No manual migration is needed - the workflow automatically uses the new script.
