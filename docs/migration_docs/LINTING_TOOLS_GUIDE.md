# IPFS Datasets Linting Tools Guide

This guide explains how to use the linting tools in the `ipfs_datasets_py` project correctly.

## Understanding the Linting Tools

The `ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools` module provides comprehensive linting capabilities for Python code, with specific extensions for IPFS datasets.

### Key features:
- Standard Python code linting (using flake8)
- Dataset-specific rules:
  - DS001: Ensures dataset operations include error handling
  - DS002: Flags hardcoded IPFS hashes that should be in configuration

## Prerequisites

Before using the linting tools, ensure you have the required dependencies:

```bash
pip install flake8
```

Optionally, for type checking:
```bash
pip install mypy
```

## Using the Linting Tools

There are two main ways to use the linting tools:

### 1. Using LintingTools class directly (recommended)

This approach gives you more control and direct access to all features:

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintingTools

# Create the linting tool instance
linter = LintingTools()

# Run asynchronously
async def run_linting():
    result = await linter.execute(
        path="/path/to/code",
        fix_issues=True,  # Automatically fix basic issues
        include_dataset_rules=True,  # Include dataset-specific rules
        dry_run=False  # False to apply changes, True to only show what would change
    )
    return result

# Execute the linting
result = asyncio.run(run_linting())

# Process results
if result['success']:
    print(f"Found {result['result']['total_issues']} issues")
    print(f"Fixed {result['result']['total_fixes']} issues")
    
    # Access detailed information about issues
    for issue in result['result']['issues']:
        print(f"{issue['file']}:{issue['line']} - {issue['rule']}: {issue['message']}")
```

### 2. Using the MCP wrapper function

The `lint_python_codebase()` function is a wrapper for the MCP server, but can be confusing to use directly:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

# This returns the result directly (not a tool instance!)
result = lint_python_codebase(
    path="/path/to/code",
    fix_issues=True,
    dry_run=False
)

# Process results as above
if result['success']:
    print(f"Found {result['result']['total_issues']} issues")
```

## Common Linting Rules

- **E501**: Line too long (> 79 characters)
- **F401**: Imported module not used
- **E302**: Expected 2 blank lines
- **DS001**: Dataset operation should include error handling
- **DS002**: Consider using configuration for IPFS hashes

## Dataset-Specific Rules

- **DS001**: Add try/except blocks around dataset operations
- **DS002**: Move hardcoded IPFS hashes to configuration files

## Example: Fixing Common Issues

### DS001: Adding Error Handling

Before:
```python
data = get_from_ipfs("QmHashGoesHere")
process_dataset(data)
```

After:
```python
try:
    data = get_from_ipfs("QmHashGoesHere")
    process_dataset(data)
except Exception as e:
    logger.error(f"Dataset operation failed: {e}")
    # Handle the error appropriately
```

### DS002: Moving Hashes to Config

Before:
```python
ipfs_hash = "QmHashGoesHere"
data = get_from_ipfs(ipfs_hash)
```

After:
```python
from ipfs_datasets_py.config import get_config

config = get_config()
ipfs_hash = config.datasets.reference_dataset_hash
data = get_from_ipfs(ipfs_hash)
```

## Troubleshooting

**Issue**: AttributeError: 'dict' object has no attribute 'execute'
**Solution**: You're trying to call execute() on the result of lint_python_codebase(). Either use the LintingTools class directly or just use the result dictionary returned by lint_python_codebase().

**Issue**: Many warnings about flake8 not being installed
**Solution**: Run `pip install flake8`

**Issue**: Audit logging failures
**Solution**: These warnings can be ignored as they don't affect the linting functionality.
