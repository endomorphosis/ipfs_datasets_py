#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI MCP Server Tools

This module provides MCP server tool functions for VSCode CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

logger = logging.getLogger(__name__)


def vscode_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get VSCode CLI installation status and information.
    
    Returns information about the VSCode CLI installation including version,
    installation path, platform, architecture, and installed extensions.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing:
        - success (bool): Whether the operation succeeded
        - status (dict): Status information including:
          - installed (bool): Whether VSCode CLI is installed
          - version (str): Version string if installed
          - install_dir (str): Installation directory path
          - executable (str): Path to CLI executable
          - platform (str): Operating system platform
          - architecture (str): System architecture
          - extensions (list): List of installed extensions
        - error (str): Error message if operation failed
    
    Example:
        >>> result = vscode_cli_status()
        >>> if result['success']:
        ...     print(f"Version: {result['status']['version']}")
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get VSCode CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False,
    commit: Optional[str] = None
) -> Dict[str, Any]:
    """
    Install or update VSCode CLI.
    
    Downloads and installs the VSCode CLI for the current platform and architecture.
    Will skip installation if already installed unless force=True.
    
    Args:
        install_dir: Optional custom installation directory path (defaults to ~/.vscode-cli)
        force: Force reinstallation even if already installed (default: False)
        commit: Optional specific VSCode commit ID to install (defaults to stable)
    
    Returns:
        Dictionary containing:
        - success (bool): Whether installation succeeded
        - message (str): Success message
        - status (dict): Post-installation status information
        - error (str): Error message if installation failed
    
    Example:
        >>> result = vscode_cli_install()
        >>> if result['success']:
        ...     print(result['message'])
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir, commit=commit)
        success = cli.download_and_install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "VSCode CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install VSCode CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    Execute VSCode CLI commands.
    
    Executes arbitrary VSCode CLI commands and returns stdout, stderr, and return code.
    The VSCode CLI must be installed first using vscode_cli_install.
    
    Args:
        command: List of command arguments to pass to VSCode CLI
        install_dir: Optional custom installation directory path
        timeout: Command timeout in seconds (default: 60, max: 300)
    
    Returns:
        Dictionary containing:
        - success (bool): Whether command executed successfully (returncode == 0)
        - returncode (int): Command exit code
        - stdout (str): Standard output from command
        - stderr (str): Standard error from command
        - command (list): The command that was executed
        - error (str): Error message if execution failed
    
    Example:
        >>> result = vscode_cli_execute(['--version'])
        >>> if result['success']:
        ...     print(f"Version output: {result['stdout']}")
    """
    try:
        if not command:
            return {
                "success": False,
                "error": "Command parameter is required"
            }
        
        cli = VSCodeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "VSCode CLI is not installed. Use vscode_cli_install first."
            }
        
        result = cli.execute(command, timeout=timeout)
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command
        }
    except Exception as e:
        logger.error(f"Failed to execute VSCode CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_list_extensions(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    List installed VSCode extensions.
    
    Returns a list of all currently installed VSCode extensions by their IDs.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing:
        - success (bool): Whether operation succeeded
        - action (str): "list"
        - extensions (list): List of installed extension IDs
        - count (int): Number of installed extensions
        - error (str): Error message if operation failed
    
    Example:
        >>> result = vscode_cli_list_extensions()
        >>> if result['success']:
        ...     print(f"Installed extensions: {result['extensions']}")
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "VSCode CLI is not installed. Use vscode_cli_install first."
            }
        
        extensions = cli.list_extensions()
        return {
            "success": True,
            "action": "list",
            "extensions": extensions,
            "count": len(extensions)
        }
    except Exception as e:
        logger.error(f"Failed to list VSCode extensions: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_install_extension(
    extension_id: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Install a VSCode extension.
    
    Installs the specified VSCode extension by its marketplace ID.
    
    Args:
        extension_id: Extension ID from VSCode marketplace (e.g., 'ms-python.python')
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing:
        - success (bool): Whether installation succeeded
        - action (str): "install"
        - extension_id (str): The extension that was installed
        - message (str): Success or failure message
        - error (str): Error message if installation failed
    
    Example:
        >>> result = vscode_cli_install_extension('ms-python.python')
        >>> if result['success']:
        ...     print(result['message'])
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "VSCode CLI is not installed. Use vscode_cli_install first."
            }
        
        success = cli.install_extension(extension_id)
        return {
            "success": success,
            "action": "install",
            "extension_id": extension_id,
            "message": f"Extension {extension_id} {'installed' if success else 'failed to install'}"
        }
    except Exception as e:
        logger.error(f"Failed to install extension {extension_id}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_uninstall_extension(
    extension_id: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Uninstall a VSCode extension.
    
    Removes the specified VSCode extension by its marketplace ID.
    
    Args:
        extension_id: Extension ID to uninstall (e.g., 'ms-python.python')
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing:
        - success (bool): Whether uninstallation succeeded
        - action (str): "uninstall"
        - extension_id (str): The extension that was uninstalled
        - message (str): Success or failure message
        - error (str): Error message if uninstallation failed
    
    Example:
        >>> result = vscode_cli_uninstall_extension('ms-python.python')
        >>> if result['success']:
        ...     print(result['message'])
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "VSCode CLI is not installed. Use vscode_cli_install first."
            }
        
        success = cli.uninstall_extension(extension_id)
        return {
            "success": success,
            "action": "uninstall",
            "extension_id": extension_id,
            "message": f"Extension {extension_id} {'uninstalled' if success else 'failed to uninstall'}"
        }
    except Exception as e:
        logger.error(f"Failed to uninstall extension {extension_id}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_tunnel_login(
    provider: str = "github",
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Login to VSCode tunnel service.
    
    Authenticates with the VSCode tunnel service using the specified provider.
    This is required before using tunnel features.
    
    Args:
        provider: Auth provider to use - 'github' or 'microsoft' (default: 'github')
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing:
        - success (bool): Whether login succeeded
        - action (str): "login"
        - provider (str): The auth provider used
        - stdout (str): Command output
        - stderr (str): Command error output
        - error (str): Error message if login failed
    
    Example:
        >>> result = vscode_cli_tunnel_login(provider='github')
        >>> if result['success']:
        ...     print("Logged in successfully")
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "VSCode CLI is not installed. Use vscode_cli_install first."
            }
        
        result = cli.tunnel_user_login(provider=provider)
        return {
            "success": result.returncode == 0,
            "action": "login",
            "provider": provider,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        logger.error(f"Failed to login to VSCode tunnel: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def vscode_cli_tunnel_install_service(
    tunnel_name: Optional[str] = None,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Install VSCode tunnel as a system service.
    
    Installs the VSCode tunnel as a background service that runs automatically.
    Requires prior authentication with vscode_cli_tunnel_login.
    
    Args:
        tunnel_name: Optional name for the tunnel
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing:
        - success (bool): Whether service installation succeeded
        - action (str): "install_service"
        - tunnel_name (str): The tunnel name if specified
        - stdout (str): Command output
        - stderr (str): Command error output
        - error (str): Error message if installation failed
    
    Example:
        >>> result = vscode_cli_tunnel_install_service(tunnel_name='my-tunnel')
        >>> if result['success']:
        ...     print("Tunnel service installed")
    """
    try:
        cli = VSCodeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "VSCode CLI is not installed. Use vscode_cli_install first."
            }
        
        result = cli.tunnel_service_install(name=tunnel_name)
        return {
            "success": result.returncode == 0,
            "action": "install_service",
            "tunnel_name": tunnel_name,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        logger.error(f"Failed to install VSCode tunnel service: {e}")
        return {
            "success": False,
            "error": str(e)
        }
