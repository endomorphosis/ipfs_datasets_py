"""VSCode CLI wrapper - DEPRECATED.

Use ipfs_datasets_py.utils.cli_tools for CLI tool wrappers.
"""
import warnings
warnings.warn("ipfs_datasets_py.utils.vscode_cli is deprecated. Use ipfs_datasets_py.utils.cli_tools instead.", DeprecationWarning, stacklevel=2)
from .cli_tools import BaseCLITool as VSCodeCLI
__all__ = ['VSCodeCLI']
