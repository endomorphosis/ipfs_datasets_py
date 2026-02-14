"""VSCode CLI wrapper - DEPRECATED.

This module is maintained for backward compatibility only.
Use ipfs_datasets_py.utils.cli_tools for new CLI tool wrappers.

The VSCodeCLI class previously provided methods for managing the VSCode CLI tool.
This compatibility shim preserves the API for legacy code while issuing deprecation warnings.

Migration Guide:
    Old: from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    New: from ipfs_datasets_py.utils.cli_tools import BaseCLITool or create custom wrapper
"""
import warnings
from pathlib import Path
from typing import Optional, Any, Dict, List

warnings.warn(
    "ipfs_datasets_py.utils.vscode_cli is deprecated. "
    "Use ipfs_datasets_py.utils.cli_tools.BaseCLITool for new CLI wrappers. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)


class VSCodeCLI:
    """
    Deprecated VSCode CLI wrapper.
    
    This class is kept only for backward compatibility with existing code
    that uses VSCodeCLI. All methods now raise NotImplementedError with
    migration guidance.
    
    For new code, use ipfs_datasets_py.utils.cli_tools.BaseCLITool or
    create a custom CLI wrapper inheriting from it.
    """
    
    def __init__(self, install_dir: Optional[str] = None, commit: Optional[str] = None):
        """Initialize deprecated VSCodeCLI shim.
        
        Args:
            install_dir: Installation directory (ignored)
            commit: VSCode commit ID (ignored)
        """
        warnings.warn(
            "VSCodeCLI is deprecated. Use ipfs_datasets_py.utils.cli_tools.BaseCLITool "
            "or create a custom CLI wrapper instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.install_dir = Path(install_dir) if install_dir else Path.home() / '.vscode-cli'
    
    def _deprecated_method(self, method_name: str) -> None:
        """Raise consistent deprecation error."""
        raise NotImplementedError(
            f"VSCodeCLI.{method_name}() is no longer implemented. "
            "This module is deprecated. Please migrate to "
            "ipfs_datasets_py.utils.cli_tools.BaseCLITool or create a "
            "custom CLI wrapper for your VSCode integration needs."
        )
    
    def is_installed(self) -> bool:
        """Check if VSCode CLI is installed (deprecated)."""
        self._deprecated_method("is_installed")
    
    def download_and_install(self) -> bool:
        """Download and install VSCode CLI (deprecated)."""
        self._deprecated_method("download_and_install")
    
    def execute(self, command: List[str], **kwargs) -> Any:
        """Execute command (deprecated)."""
        self._deprecated_method("execute")
    
    def get_status(self) -> Dict[str, Any]:
        """Get status (deprecated)."""
        self._deprecated_method("get_status")
    
    def list_extensions(self) -> List[str]:
        """List installed extensions (deprecated)."""
        self._deprecated_method("list_extensions")
    
    def tunnel_create(self, name: str) -> Any:
        """Create tunnel (deprecated)."""
        self._deprecated_method("tunnel_create")
    
    def tunnel_status(self) -> Any:
        """Get tunnel status (deprecated)."""
        self._deprecated_method("tunnel_status")


__all__ = ['VSCodeCLI']
