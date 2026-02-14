"""GitHub CLI wrapper - DEPRECATED.

This module is maintained for backward compatibility only.
Use ipfs_datasets_py.utils.github.GitHubCLI instead.

Migration Guide:
    Old code:
    >>> from ipfs_datasets_py.utils.github_wrapper import GitHubWrapper
    
    New code:
    >>> from ipfs_datasets_py.utils.github import GitHubCLI as GitHubWrapper
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.utils.github_wrapper is deprecated. "
    "Use ipfs_datasets_py.utils.github.GitHubCLI instead.",
    DeprecationWarning, stacklevel=2
)
from .github import GitHubCLI as GitHubWrapper, APICounter, RateLimiter
__all__ = ['GitHubWrapper', 'APICounter', 'RateLimiter']
