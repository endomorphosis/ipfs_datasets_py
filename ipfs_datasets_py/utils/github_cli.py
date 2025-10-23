#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub CLI Utility Module

This module provides functionality to download, install, and manage the GitHub CLI tool.
It enables programmatic access to GitHub CLI features including repository management,
issue tracking, pull requests, and GitHub Actions.

Features:
- Download and install GitHub CLI for various platforms
- Execute GitHub CLI commands
- Manage GitHub CLI installations
- Python interface for programmatic access
"""

import os
import platform
import subprocess
import tarfile
import zipfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class GitHubCLI:
    """
    GitHub CLI Manager
    
    Manages GitHub CLI installation, configuration, and execution.
    Provides a Python interface for interacting with the GitHub CLI tool.
    
    Attributes:
        install_dir (Path): Directory where GitHub CLI is installed
        platform_name (str): Detected platform name
        arch (str): Detected system architecture
        cli_executable (Path): Path to the GitHub CLI executable
    
    Example:
        >>> cli = GitHubCLI()
        >>> cli.download_and_install()
        >>> result = cli.execute(['--version'])
        >>> print(result.stdout)
    """
    
    # GitHub CLI download URLs by platform
    # Using official GitHub releases from https://github.com/cli/cli/releases
    BASE_URL = "https://github.com/cli/cli/releases/download"
    DEFAULT_VERSION = "v2.40.0"
    
    DOWNLOAD_TEMPLATES = {
        'linux': {
            'x64': '{base_url}/{version}/gh_{version_no_v}_linux_amd64.tar.gz',
            'arm64': '{base_url}/{version}/gh_{version_no_v}_linux_arm64.tar.gz',
        },
        'darwin': {
            'x64': '{base_url}/{version}/gh_{version_no_v}_macOS_amd64.tar.gz',
            'arm64': '{base_url}/{version}/gh_{version_no_v}_macOS_arm64.tar.gz',
        },
        'windows': {
            'x64': '{base_url}/{version}/gh_{version_no_v}_windows_amd64.zip',
            'arm64': '{base_url}/{version}/gh_{version_no_v}_windows_arm64.zip',
        }
    }
    
    def __init__(self, install_dir: Optional[str] = None, version: Optional[str] = None):
        """
        Initialize GitHub CLI manager.
        
        Args:
            install_dir: Directory to install GitHub CLI (defaults to ~/.github-cli)
            version: GitHub CLI version to download (defaults to latest stable version)
        """
        if install_dir is None:
            install_dir = os.path.expanduser('~/.github-cli')
        
        self.install_dir = Path(install_dir)
        self.version = version or self.DEFAULT_VERSION
        self.platform_name = self._detect_platform()
        self.arch = self._detect_architecture()
        
        # Determine the executable name based on platform
        if self.platform_name == 'windows':
            self.cli_executable = self.install_dir / 'bin' / 'gh.exe'
        else:
            self.cli_executable = self.install_dir / 'bin' / 'gh'
        
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
            url_template = self.DOWNLOAD_TEMPLATES[self.platform_name][self.arch]
            version_no_v = self.version.lstrip('v')
            return url_template.format(
                base_url=self.BASE_URL,
                version=self.version,
                version_no_v=version_no_v
            )
        except KeyError:
            raise RuntimeError(
                f"No download URL available for platform={self.platform_name}, arch={self.arch}"
            )
    
    def is_installed(self) -> bool:
        """
        Check if GitHub CLI is installed.
        
        Returns:
            True if CLI executable exists and is executable
        """
        return self.cli_executable.exists() and os.access(self.cli_executable, os.X_OK)
    
    def download_and_install(self, force: bool = False) -> bool:
        """
        Download and install GitHub CLI.
        
        Args:
            force: Force reinstallation even if already installed
        
        Returns:
            True if installation successful
        """
        if self.is_installed() and not force:
            logger.info(f"GitHub CLI already installed at {self.cli_executable}")
            return True
        
        try:
            download_url = self.get_download_url()
            logger.info(f"Downloading GitHub CLI from {download_url}")
            
            # Determine archive extension
            is_zip = download_url.endswith('.zip')
            archive_ext = 'zip' if is_zip else 'tar.gz'
            archive_path = self.install_dir / f'gh_cli.{archive_ext}'
            
            # Download archive
            urllib.request.urlretrieve(download_url, archive_path)
            
            # Extract archive
            logger.info(f"Extracting GitHub CLI to {self.install_dir}")
            if is_zip:
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(self.install_dir)
            else:
                with tarfile.open(archive_path, 'r:gz') as tar:
                    tar.extractall(self.install_dir)
            
            # Move extracted files to the correct location
            # GitHub CLI extracts to a versioned directory like gh_2.40.0_linux_amd64
            version_no_v = self.version.lstrip('v')
            platform_str = self._get_platform_string()
            extracted_dir = self.install_dir / f"gh_{version_no_v}_{platform_str}"
            
            if extracted_dir.exists():
                # Move bin directory
                src_bin = extracted_dir / 'bin'
                dst_bin = self.install_dir / 'bin'
                
                if src_bin.exists():
                    # Create destination if it doesn't exist
                    dst_bin.mkdir(parents=True, exist_ok=True)
                    
                    # Move executable
                    for item in src_bin.iterdir():
                        dst_item = dst_bin / item.name
                        if dst_item.exists():
                            dst_item.unlink()
                        item.rename(dst_item)
                
                # Clean up extracted directory
                import shutil
                shutil.rmtree(extracted_dir)
            
            # Clean up archive
            archive_path.unlink()
            
            # Make executable (Unix-like systems)
            if self.cli_executable.exists():
                if self.platform_name != 'windows':
                    self.cli_executable.chmod(0o755)
                logger.info(f"GitHub CLI installed successfully at {self.cli_executable}")
                return True
            else:
                logger.error("GitHub CLI executable not found after extraction")
                return False
                
        except Exception as e:
            logger.error(f"Failed to download and install GitHub CLI: {e}")
            return False
    
    def _get_platform_string(self) -> str:
        """
        Get the platform string used in archive names.
        
        Returns:
            Platform string like 'linux_amd64' or 'macOS_arm64'
        """
        platform_map = {
            'linux': 'linux',
            'darwin': 'macOS',
            'windows': 'windows'
        }
        arch_map = {
            'x64': 'amd64',
            'arm64': 'arm64'
        }
        return f"{platform_map[self.platform_name]}_{arch_map[self.arch]}"
    
    def execute(self, args: List[str], capture_output: bool = True, 
                timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Execute a GitHub CLI command.
        
        Args:
            args: Command arguments to pass to GitHub CLI
            capture_output: Whether to capture stdout/stderr
            timeout: Command timeout in seconds
        
        Returns:
            CompletedProcess object with command results
        
        Raises:
            RuntimeError: If GitHub CLI is not installed
            subprocess.TimeoutExpired: If command times out
        """
        if not self.is_installed():
            raise RuntimeError(
                "GitHub CLI is not installed. Call download_and_install() first."
            )
        
        cmd = [str(self.cli_executable)] + args
        logger.debug(f"Executing GitHub CLI command: {' '.join(cmd)}")
        
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
            logger.error(f"GitHub CLI command timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(f"Failed to execute GitHub CLI command: {e}")
            raise
    
    def get_version(self) -> Optional[str]:
        """
        Get the installed GitHub CLI version.
        
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
            logger.error(f"Failed to get GitHub CLI version: {e}")
            return None
    
    def auth_login(self, hostname: str = 'github.com', web: bool = True) -> subprocess.CompletedProcess:
        """
        Login to GitHub.
        
        Args:
            hostname: GitHub hostname (default: github.com, can use GitHub Enterprise)
            web: Use web browser for authentication
        
        Returns:
            CompletedProcess with login results
        """
        args = ['auth', 'login', '--hostname', hostname]
        if web:
            args.append('--web')
        return self.execute(args)
    
    def auth_status(self) -> subprocess.CompletedProcess:
        """
        Check authentication status.
        
        Returns:
            CompletedProcess with authentication status
        """
        return self.execute(['auth', 'status'])
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get GitHub CLI status information.
        
        Returns:
            Dictionary with status information
        """
        auth_status = None
        if self.is_installed():
            try:
                result = self.auth_status()
                auth_status = result.stdout.strip() if result.returncode == 0 else "Not authenticated"
            except:
                auth_status = "Unknown"
        
        return {
            'installed': self.is_installed(),
            'version': self.get_version(),
            'install_dir': str(self.install_dir),
            'executable': str(self.cli_executable),
            'platform': self.platform_name,
            'architecture': self.arch,
            'auth_status': auth_status
        }
    
    def repo_list(self, limit: int = 30) -> List[str]:
        """
        List user's repositories.
        
        Args:
            limit: Maximum number of repositories to list
        
        Returns:
            List of repository names
        """
        try:
            result = self.execute(['repo', 'list', '--limit', str(limit)], timeout=30)
            if result.returncode == 0:
                return [line.strip().split()[0] for line in result.stdout.split('\n') if line.strip()]
            return []
        except Exception as e:
            logger.error(f"Failed to list repositories: {e}")
            return []
    
    def configure_auth(self, hostname: str = 'github.com', web: bool = True) -> Dict[str, Any]:
        """
        Configure authentication for GitHub.
        
        This method sets up authentication by logging in with the specified hostname.
        
        Args:
            hostname: GitHub hostname (default: github.com)
            web: Use web browser for authentication
        
        Returns:
            Dictionary with authentication result
        
        Example:
            >>> cli = GitHubCLI()
            >>> cli.download_and_install()
            >>> result = cli.configure_auth(hostname='github.com', web=True)
            >>> if result['success']:
            ...     print("Authentication successful!")
        """
        if not self.is_installed():
            return {
                'success': False,
                'hostname': hostname,
                'error': 'GitHub CLI is not installed. Call download_and_install() first.',
                'message': 'Installation required before authentication'
            }
        
        try:
            logger.info(f"Configuring authentication for {hostname}...")
            result = self.auth_login(hostname=hostname, web=web)
            
            return {
                'success': result.returncode == 0,
                'hostname': hostname,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'message': 'Authentication successful' if result.returncode == 0 else 'Authentication failed'
            }
        except Exception as e:
            logger.error(f"Failed to configure authentication: {e}")
            return {
                'success': False,
                'hostname': hostname,
                'error': str(e),
                'message': f'Authentication error: {str(e)}'
            }


def create_github_cli(install_dir: Optional[str] = None) -> GitHubCLI:
    """
    Create and return a GitHub CLI manager instance.
    
    Args:
        install_dir: Optional installation directory
    
    Returns:
        GitHubCLI instance
    """
    return GitHubCLI(install_dir=install_dir)
