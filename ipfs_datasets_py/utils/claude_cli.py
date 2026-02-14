"""Claude CLI wrapper - DEPRECATED.

This module is maintained for backward compatibility only.
Use ipfs_datasets_py.utils.cli_tools for new CLI tool wrappers.

The ClaudeCLI class previously provided methods for managing the Anthropic Claude CLI.
This compatibility shim preserves the API for legacy code while issuing deprecation warnings.

Migration Guide:
    Old: from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    New: from ipfs_datasets_py.utils.cli_tools import BaseCLITool or create custom wrapper
"""
import warnings
from pathlib import Path
from typing import Optional, Any, Dict, List

warnings.warn(
    "ipfs_datasets_py.utils.claude_cli is deprecated. "
    "Use ipfs_datasets_py.utils.cli_tools.BaseCLITool for new CLI wrappers. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)


class ClaudeCLI:
    """
    Deprecated Anthropic Claude CLI wrapper.
    
    This class is kept only for backward compatibility with existing code
    that uses ClaudeCLI. All methods now raise NotImplementedError with
    migration guidance.
    
    For new code, use ipfs_datasets_py.utils.cli_tools.BaseCLITool or
    create a custom CLI wrapper inheriting from it.
    """
    
    def __init__(self, install_dir: Optional[str] = None, use_accelerate: bool = True):
        """Initialize deprecated ClaudeCLI shim.
        
        Args:
            install_dir: Installation directory (ignored)
            use_accelerate: Use accelerate (ignored)
        """
        warnings.warn(
            "ClaudeCLI is deprecated. Use ipfs_datasets_py.utils.cli_tools.BaseCLITool "
            "or create a custom CLI wrapper instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.install_dir = Path(install_dir) if install_dir else Path.home() / '.claude-cli'
    
    def _deprecated_method(self, method_name: str) -> None:
        """Raise consistent deprecation error."""
        raise NotImplementedError(
            f"ClaudeCLI.{method_name}() is no longer implemented. "
            "This module is deprecated. Please migrate to "
            "ipfs_datasets_py.utils.cli_tools.BaseCLITool or create a "
            "custom CLI wrapper for your Claude integration needs."
        )
    
    def is_installed(self) -> bool:
        """Check if Claude CLI is installed (deprecated)."""
        self._deprecated_method("is_installed")
    
    def install(self) -> bool:
        """Install Claude CLI (deprecated)."""
        self._deprecated_method("install")
    
    def configure_api_key(self, api_key: str) -> bool:
        """Configure API key (deprecated)."""
        self._deprecated_method("configure_api_key")
    
    def execute(self, command: List[str], **kwargs) -> Any:
        """Execute command (deprecated)."""
        self._deprecated_method("execute")
    
    def get_status(self) -> Dict[str, Any]:
        """Get status (deprecated)."""
        self._deprecated_method("get_status")


__all__ = ['ClaudeCLI']
