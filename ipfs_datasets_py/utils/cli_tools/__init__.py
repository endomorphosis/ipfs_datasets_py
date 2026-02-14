"""Unified CLI Tools.

This module provides unified wrappers for various CLI tools with consistent
interfaces, caching, and error handling.

Public API:
- BaseCLITool: Abstract base for CLI tool wrappers
- Copilot: GitHub Copilot CLI wrapper
- Claude: Claude CLI wrapper
- VSCode: VS Code CLI wrapper
- Gemini: Google Gemini CLI wrapper

Example:
    >>> from ipfs_datasets_py.utils.cli_tools import Copilot
    >>> 
    >>> copilot = Copilot()
    >>> if copilot.is_installed():
    ...     suggestion = copilot.suggest("list files")
    ...     print(suggestion)
"""

# Base class
from .base import BaseCLITool

# Tool implementations
from .copilot import Copilot, CopilotCLI

# Placeholders for other tools (minimal stubs)
class Claude(BaseCLITool):
    """Claude CLI wrapper (stub)."""
    tool_name = "claude"
    
    def _verify_installation(self) -> bool:
        """Verify Claude CLI is installed."""
        return self.cli_path is not None and self.cli_path.exists()


class VSCode(BaseCLITool):
    """VS Code CLI wrapper (stub)."""
    tool_name = "code"
    
    def _verify_installation(self) -> bool:
        """Verify VS Code CLI is installed."""
        return self.cli_path is not None and self.cli_path.exists()


class Gemini(BaseCLITool):
    """Gemini CLI wrapper (stub)."""
    tool_name = "gemini"
    
    def _verify_installation(self) -> bool:
        """Verify Gemini CLI is installed."""
        return self.cli_path is not None and self.cli_path.exists()


__all__ = [
    # Base class
    'BaseCLITool',
    
    # Implementations
    'Copilot',
    'Claude',
    'VSCode',
    'Gemini',
    
    # Backward compatibility
    'CopilotCLI',
]
