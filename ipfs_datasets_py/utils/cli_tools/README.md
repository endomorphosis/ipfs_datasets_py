# Unified CLI Tools

This module provides unified wrappers for various CLI tools with consistent interfaces, caching, and error handling.

## Architecture

All CLI tools extend `BaseCLITool`, which provides:
- Automatic CLI path detection
- Command execution with timeout
- Result caching using `utils.cache.LocalCache`
- Error handling and logging
- Statistics tracking

## Quick Start

### GitHub Copilot

```python
from ipfs_datasets_py.utils.cli_tools import Copilot

# Create wrapper
copilot = Copilot(enable_cache=True)

# Check installation
if not copilot.is_installed():
    # Install Copilot extension
    copilot.install()

# Get command suggestions
suggestion = copilot.suggest("list all Python files")
print(suggestion)

# Explain code
explanation = copilot.explain("def hello(): print('world')")
print(explanation)

# Cache statistics
stats = copilot.get_cache_stats()
print(f"Hit rate: {stats['hit_rate']:.2%}")
```

### Other Tools (Stubs)

```python
from ipfs_datasets_py.utils.cli_tools import Claude, VSCode, Gemini

# These are minimal stubs - full implementations coming
claude = Claude()
vscode = VSCode()
gemini = Gemini()

if vscode.is_installed():
    print("VS Code CLI available")
```

## Creating Custom CLI Tool Wrappers

Extend `BaseCLITool`:

```python
from ipfs_datasets_py.utils.cli_tools import BaseCLITool

class MyTool(BaseCLITool):
    tool_name = "mytool"
    
    def _verify_installation(self) -> bool:
        """Check if tool is installed."""
        if not self.cli_path or not self.cli_path.exists():
            return False
        # Additional verification...
        return True
    
    def my_command(self, arg: str) -> str:
        """Custom command."""
        result = self._run_command(
            ['subcommand', arg],
            cache_key=f"my_command:{arg}"
        )
        if result['success']:
            return result['stdout']
        raise RuntimeError(result['stderr'])
```

## Features

### Automatic Path Detection

Tools are automatically located in PATH:

```python
# Auto-detect
copilot = Copilot()

# Or specify path
copilot = Copilot(github_cli_path="/usr/local/bin/gh")
```

### Caching

All tool wrappers support caching:

```python
copilot = Copilot(
    enable_cache=True,
    cache_maxsize=100,
    cache_ttl=600  # 10 minutes
)

# Results are cached
result1 = copilot.suggest("list files")  # Cache miss
result2 = copilot.suggest("list files")  # Cache hit

# Check stats
stats = copilot.get_cache_stats()
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")

# Clear cache
copilot.clear_cache()
```

### Error Handling

Consistent error handling across tools:

```python
try:
    result = copilot.suggest("query")
except RuntimeError as e:
    print(f"Command failed: {e}")
```

## Migration Guide

### From copilot_cli.py

```python
# Old code
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
copilot = CopilotCLI()

# New code
from ipfs_datasets_py.utils.cli_tools import Copilot
copilot = Copilot()

# Or use backward-compatible alias
from ipfs_datasets_py.utils.cli_tools import CopilotCLI
copilot = CopilotCLI()
```

### From other CLI files

Similar pattern for claude_cli, vscode_cli, gemini_cli:

```python
# Old
from ipfs_datasets_py.utils.claude_cli import ClaudeCLI

# New
from ipfs_datasets_py.utils.cli_tools import Claude
```

## Status

### Implemented
- ✅ BaseCLITool: Abstract base class
- ✅ Copilot: Full GitHub Copilot CLI wrapper
- ✅ Caching integration with utils.cache
- ✅ Error handling and logging

### Stubs (Minimal Implementation)
- ⚠️ Claude: Basic stub
- ⚠️ VSCode: Basic stub  
- ⚠️ Gemini: Basic stub

Full implementations of Claude, VSCode, and Gemini can be added following the Copilot pattern.

## See Also

- `utils/cache/` - Caching infrastructure
- `utils/copilot_cli.py` - Original implementation (deprecated)
- `docs/REFACTORING_PLAN_GITHUB_UTILS.md` - Overall refactoring plan
