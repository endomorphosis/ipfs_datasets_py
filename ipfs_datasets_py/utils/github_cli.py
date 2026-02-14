"""GitHub CLI - DEPRECATED.

This module is maintained for backward compatibility only.
Use ipfs_datasets_py.utils.github.GitHubCLI instead.

Migration Guide:
    Old: from ipfs_datasets_py.utils.github_cli import GitHubCLI
    New: from ipfs_datasets_py.utils.github import GitHubCLI
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.utils.github_cli is deprecated. "
    "Use ipfs_datasets_py.utils.github instead.",
    DeprecationWarning, stacklevel=2
)
from .github import GitHubCLI, APICounter, RateLimiter
__all__ = ['GitHubCLI', 'APICounter', 'RateLimiter']
