"""Claude CLI wrapper - DEPRECATED.

Use ipfs_datasets_py.utils.cli_tools for CLI tool wrappers.

Migration Guide:
    Old: from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    New: from ipfs_datasets_py.utils.cli_tools import BaseCLITool
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.utils.claude_cli is deprecated. "
    "Use ipfs_datasets_py.utils.cli_tools instead.",
    DeprecationWarning, stacklevel=2
)
from .cli_tools import BaseCLITool as ClaudeCLI
__all__ = ['ClaudeCLI']
