"""Copilot CLI wrapper - DEPRECATED.

Use ipfs_datasets_py.utils.cli_tools.Copilot instead.

Migration Guide:
    Old: from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
    New: from ipfs_datasets_py.utils.cli_tools import Copilot
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.utils.copilot_cli is deprecated. "
    "Use ipfs_datasets_py.utils.cli_tools.Copilot instead.",
    DeprecationWarning, stacklevel=2
)
from .cli_tools import Copilot as CopilotCLI
__all__ = ['CopilotCLI']
