#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI Utility Module

This module provides functionality to download, install, and manage the VSCode CLI tool.
It enables programmatic access to VSCode CLI features including tunnel management,
remote development, and extension management.

Features:
- Download and install VSCode CLI for various platforms
- Execute VSCode CLI commands
- Manage VSCode CLI installations
- Python interface for programmatic access
"""

import os
import platform
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class VSCodeCLI:
    """
    VSCode CLI Manager
    
    Manages VSCode CLI installation, configuration, and execution.
    Provides a Python interface for interacting with the VSCode CLI tool.
    
    Attributes:
        install_dir (Path): Directory where VSCode CLI is installed
        platform_name (str): Detected platform name
        arch (str): Detected system architecture
        cli_executable (Path): Path to the VSCode CLI executable
    
    Example:
        >>> cli = VSCodeCLI()
        >>> cli.download_and_install()
        >>> result = cli.execute(['--version'])
        >>> print(result.stdout)
    """
    
    # VSCode CLI download URLs by platform
    DOWNLOAD_URLS = {
        'linux': {
            'x64': 'https://vscode.download.prss.microsoft.com/dbazure/download/stable/{commit}/vscode_cli_alpine_x64_cli.tar.gz',
            'arm64': 'https://vscode.download.prss.microsoft.com/dbazure/download/stable/{commit}/vscode_cli_alpine_arm64_cli.tar.gz',
        },
        'darwin': {
            'x64': 'https://vscode.download.prss.microsoft.com/dbazure/download/stable/{commit}/vscode_cli_darwin_x64_cli.tar.gz',
            'arm64': 'https://vscode.download.prss.microsoft.com/dbazure/download/stable/{commit}/vscode_cli_darwin_arm64_cli.tar.gz',
        },
        'windows': {
            'x64': 'https://vscode.download.prss.microsoft.com/dbazure/download/stable/{commit}/vscode_cli_win32_x64_cli.zip',
            'arm64': 'https://vscode.download.prss.microsoft.com/dbazure/download/stable/{commit}/vscode_cli_win32_arm64_cli.zip',
        }
    }
    
    # Default stable commit ID (can be updated)
    DEFAULT_COMMIT = '7d842fb85a0275a4a8e4d7e040d2625abbf7f084'
    
    def __init__(self, install_dir: Optional[str] = None, commit: Optional[str] = None):
        """
        Initialize VSCode CLI manager.
        
        Args:
            install_dir: Directory to install VSCode CLI (defaults to ~/.vscode-cli)
            commit: VSCode commit ID to download (defaults to stable version)
        """
        if install_dir is None:
            install_dir = os.path.expanduser('~/.vscode-cli')
        
        self.install_dir = Path(install_dir)
        self.commit = commit or self.DEFAULT_COMMIT
        self.platform_name = self._detect_platform()
        self.arch = self._detect_architecture()
        self.cli_executable = self.install_dir / 'code'
        
        # Ensure install directory exists
        self.install_dir.mkdir(parents=True, exist_ok=True)
    
    def _detect_platform(self) -> str:
        """
        Detect the current platform.
        
        Returns:
            Platform name: 'linux', 'darwin', or 'windows'
        """
        system = platform.system().lower()
        if system == 'linux':
            return 'linux'
        elif system == 'darwin':
            return 'darwin'
        elif system == 'windows':
            return 'windows'
        else:
            raise RuntimeError(f"Unsupported platform: {system}")
    
    def _detect_architecture(self) -> str:
        """
        Detect the system architecture.
        
        Returns:
            Architecture name: 'x64' or 'arm64'
        """
        machine = platform.machine().lower()
        if machine in ('x86_64', 'amd64'):
            return 'x64'
        elif machine in ('arm64', 'aarch64'):
            return 'arm64'
        else:
            raise RuntimeError(f"Unsupported architecture: {machine}")
    
    def get_download_url(self) -> str:
        """
        Get the download URL for the current platform and architecture.
        
        Returns:
            Download URL string
        """
        try:
            url_template = self.DOWNLOAD_URLS[self.platform_name][self.arch]
            return url_template.format(commit=self.commit)
        except KeyError:
            raise RuntimeError(
                f"No download URL available for platform={self.platform_name}, arch={self.arch}"
            )
    
    def is_installed(self) -> bool:
        """
        Check if VSCode CLI is installed.
        
        Returns:
            True if CLI executable exists and is executable
        """
        return self.cli_executable.exists() and os.access(self.cli_executable, os.X_OK)
    
    def download_and_install(self, force: bool = False) -> bool:
        """
        Download and install VSCode CLI.
        
        Args:
            force: Force reinstallation even if already installed
        
        Returns:
            True if installation successful
        """
        if self.is_installed() and not force:
            logger.info(f"VSCode CLI already installed at {self.cli_executable}")
            return True
        
        try:
            download_url = self.get_download_url()
            logger.info(f"Downloading VSCode CLI from {download_url}")
            
            # Download archive
            archive_path = self.install_dir / 'vscode_cli.tar.gz'
            urllib.request.urlretrieve(download_url, archive_path)
            
            # Extract archive
            logger.info(f"Extracting VSCode CLI to {self.install_dir}")
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(self.install_dir)
            
            # Clean up archive
            archive_path.unlink()
            
            # Make executable
            if self.cli_executable.exists():
                self.cli_executable.chmod(0o755)
                logger.info(f"VSCode CLI installed successfully at {self.cli_executable}")
                return True
            else:
                logger.error("VSCode CLI executable not found after extraction")
                return False
                
        except Exception as e:
            logger.error(f"Failed to download and install VSCode CLI: {e}")
            return False
    
    def execute(self, args: List[str], capture_output: bool = True, 
                timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Execute a VSCode CLI command.
        
        Args:
            args: Command arguments to pass to VSCode CLI
            capture_output: Whether to capture stdout/stderr
            timeout: Command timeout in seconds
        
        Returns:
            CompletedProcess object with command results
        
        Raises:
            RuntimeError: If VSCode CLI is not installed
            subprocess.TimeoutExpired: If command times out
        """
        if not self.is_installed():
            raise RuntimeError(
                "VSCode CLI is not installed. Call download_and_install() first."
            )
        
        cmd = [str(self.cli_executable)] + args
        logger.debug(f"Executing VSCode CLI command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                check=False
            )
            return result
        except subprocess.TimeoutExpired as e:
            logger.error(f"VSCode CLI command timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(f"Failed to execute VSCode CLI command: {e}")
            raise
    
    def get_version(self) -> Optional[str]:
        """
        Get the installed VSCode CLI version.
        
        Returns:
            Version string or None if not installed
        """
        if not self.is_installed():
            return None
        
        try:
            result = self.execute(['--version'], timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.error(f"Failed to get VSCode CLI version: {e}")
            return None
    
    def tunnel_user_login(self, provider: str = 'github') -> subprocess.CompletedProcess:
        """
        Login to VSCode tunnel service.
        
        Args:
            provider: Auth provider ('github' or 'microsoft')
        
        Returns:
            CompletedProcess with login results
        """
        return self.execute(['tunnel', 'user', 'login', '--provider', provider])
    
    def tunnel_service_install(self, name: Optional[str] = None) -> subprocess.CompletedProcess:
        """
        Install VSCode tunnel as a service.
        
        Args:
            name: Optional tunnel name
        
        Returns:
            CompletedProcess with installation results
        """
        args = ['tunnel', 'service', 'install']
        if name:
            args.extend(['--name', name])
        return self.execute(args)
    
    def list_extensions(self) -> List[str]:
        """
        List installed VSCode extensions.
        
        Returns:
            List of installed extension IDs
        """
        try:
            result = self.execute(['--list-extensions'], timeout=30)
            if result.returncode == 0:
                return [ext.strip() for ext in result.stdout.split('\n') if ext.strip()]
            return []
        except Exception as e:
            logger.error(f"Failed to list extensions: {e}")
            return []
    
    def install_extension(self, extension_id: str) -> bool:
        """
        Install a VSCode extension.
        
        Args:
            extension_id: Extension ID to install
        
        Returns:
            True if installation successful
        """
        try:
            result = self.execute(['--install-extension', extension_id], timeout=120)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to install extension {extension_id}: {e}")
            return False
    
    def uninstall_extension(self, extension_id: str) -> bool:
        """
        Uninstall a VSCode extension.
        
        Args:
            extension_id: Extension ID to uninstall
        
        Returns:
            True if uninstallation successful
        """
        try:
            result = self.execute(['--uninstall-extension', extension_id], timeout=60)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to uninstall extension {extension_id}: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get VSCode CLI status information.
        
        Returns:
            Dictionary with status information
        """
        return {
            'installed': self.is_installed(),
            'version': self.get_version(),
            'install_dir': str(self.install_dir),
            'executable': str(self.cli_executable),
            'platform': self.platform_name,
            'architecture': self.arch,
            'extensions': self.list_extensions() if self.is_installed() else []
        }
    
    def configure_auth(self, provider: str = 'github') -> Dict[str, Any]:
        """
        Configure authentication for VSCode tunnel.
        
        This method sets up authentication by logging in with the specified provider.
        Can be called directly from Python code to authenticate.
        
        Args:
            provider: Auth provider ('github' or 'microsoft')
        
        Returns:
            Dictionary with authentication result:
            - success (bool): Whether authentication succeeded
            - provider (str): Provider used
            - stdout (str): Command output
            - stderr (str): Error output
            - message (str): User-friendly message
        
        Example:
            >>> cli = VSCodeCLI()
            >>> cli.download_and_install()
            >>> result = cli.configure_auth(provider='github')
            >>> if result['success']:
            ...     print("Authentication successful!")
        """
        if not self.is_installed():
            return {
                'success': False,
                'provider': provider,
                'error': 'VSCode CLI is not installed. Call download_and_install() first.',
                'message': 'Installation required before authentication'
            }
        
        try:
            logger.info(f"Configuring authentication with provider: {provider}")
            result = self.tunnel_user_login(provider=provider)
            
            return {
                'success': result.returncode == 0,
                'provider': provider,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'message': 'Authentication successful' if result.returncode == 0 else 'Authentication failed'
            }
        except Exception as e:
            logger.error(f"Failed to configure authentication: {e}")
            return {
                'success': False,
                'provider': provider,
                'error': str(e),
                'message': f'Authentication error: {str(e)}'
            }
    
    def install_with_auth(self, provider: str = 'github', force: bool = False) -> Dict[str, Any]:
        """
        Install VSCode CLI and configure authentication in one step.
        
        This convenience method combines installation and authentication setup,
        making it easy to get started with VSCode tunnel from Python code.
        
        Args:
            provider: Auth provider ('github' or 'microsoft')
            force: Force reinstallation even if already installed
        
        Returns:
            Dictionary with installation and authentication results:
            - install_success (bool): Whether installation succeeded
            - auth_success (bool): Whether authentication succeeded
            - provider (str): Provider used for authentication
            - status (dict): VSCode CLI status information
            - auth_details (dict): Authentication result details
            - message (str): Overall status message
        
        Example:
            >>> cli = VSCodeCLI()
            >>> result = cli.install_with_auth(provider='github')
            >>> if result['install_success'] and result['auth_success']:
            ...     print("VSCode CLI ready for remote development!")
        """
        result = {
            'install_success': False,
            'auth_success': False,
            'provider': provider,
            'messages': []
        }
        
        # Step 1: Install VSCode CLI
        try:
            logger.info("Installing VSCode CLI...")
            install_success = self.download_and_install(force=force)
            result['install_success'] = install_success
            
            if install_success:
                result['messages'].append("VSCode CLI installed successfully")
            else:
                result['messages'].append("VSCode CLI installation failed")
                result['message'] = "Installation failed"
                return result
        except Exception as e:
            logger.error(f"Installation failed: {e}")
            result['messages'].append(f"Installation error: {str(e)}")
            result['message'] = "Installation failed"
            return result
        
        # Step 2: Configure authentication
        try:
            logger.info(f"Configuring authentication with {provider}...")
            auth_result = self.configure_auth(provider=provider)
            result['auth_success'] = auth_result['success']
            result['auth_details'] = auth_result
            
            if auth_result['success']:
                result['messages'].append(f"Authentication with {provider} successful")
            else:
                result['messages'].append(f"Authentication with {provider} failed")
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            result['messages'].append(f"Authentication error: {str(e)}")
        
        # Step 3: Get final status
        try:
            result['status'] = self.get_status()
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
        
        # Set overall message
        if result['install_success'] and result['auth_success']:
            result['message'] = "VSCode CLI installed and authenticated successfully"
        elif result['install_success']:
            result['message'] = "VSCode CLI installed but authentication failed"
        else:
            result['message'] = "Installation failed"
        
        return result


def create_vscode_cli(install_dir: Optional[str] = None) -> VSCodeCLI:
    """
    Create and return a VSCode CLI manager instance.
    
    Args:
        install_dir: Optional installation directory
    
    Returns:
        VSCodeCLI instance
    """
    return VSCodeCLI(install_dir=install_dir)
