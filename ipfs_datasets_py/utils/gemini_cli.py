"""Gemini CLI wrapper - DEPRECATED.

Use ipfs_datasets_py.utils.cli_tools for CLI tool wrappers.
"""
import warnings
warnings.warn("ipfs_datasets_py.utils.gemini_cli is deprecated. Use ipfs_datasets_py.utils.cli_tools instead.", DeprecationWarning, stacklevel=2)
from .cli_tools import BaseCLITool as GeminiCLI
__all__ = ['GeminiCLI']
