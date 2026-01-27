#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord Chat Exporter Utility Module

This module provides functionality to download, install, and manage the DiscordChatExporter CLI tool.
DiscordChatExporter enables exporting message history from Discord channels, DMs, and servers
to various formats including HTML, JSON, CSV, and plain text.

Features:
- Download and install DiscordChatExporter CLI for various platforms
- Cross-platform support (Linux, macOS, Windows)
- Multiple architecture support (x64, x86, arm64, arm)
- Version management
- Python interface for programmatic access

Repository: https://github.com/Tyrrrz/DiscordChatExporter
"""

import os
import platform
import subprocess
import zipfile
import urllib.request
import re
from pathlib import Path
from typing import Dict, Optional, Any
import logging
import shutil

logger = logging.getLogger(__name__)

# Optional cache import - gracefully handle if not available
try:
    from ipfs_datasets_py.utils.query_cache import QueryCache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    logger.warning("QueryCache not available, caching disabled")


class DiscordChatExporter:
    """
    Discord Chat Exporter CLI Manager
    
    Manages DiscordChatExporter CLI installation, configuration, and execution.
    Provides a Python interface for interacting with the DiscordChatExporter tool
    to export Discord chat histories from channels, DMs, and servers.
    
    Attributes:
        install_dir (Path): Directory where DiscordChatExporter is installed
        platform_name (str): Detected platform name
        arch (str): Detected system architecture
        cli_executable (Path): Path to the DiscordChatExporter CLI executable
        version (str): Version of DiscordChatExporter to install
    
    Example:
        >>> exporter = DiscordChatExporter()
        >>> exporter.download_and_install()
        >>> exporter.verify_installation()
        True
    """
    
    # DiscordChatExporter download URLs
    # Using official releases from https://github.com/Tyrrrz/DiscordChatExporter/releases
    BASE_URL = "https://github.com/Tyrrrz/DiscordChatExporter/releases/download"
    DEFAULT_VERSION = "2.46"
    
    # Platform and architecture mapping to download file names
    DOWNLOAD_TEMPLATES = {
        'linux': {
            'x64': '{base_url}/{version}/DiscordChatExporter.Cli.linux-x64.zip',
            'arm64': '{base_url}/{version}/DiscordChatExporter.Cli.linux-arm64.zip',
            'arm': '{base_url}/{version}/DiscordChatExporter.Cli.linux-arm.zip',
            'musl-x64': '{base_url}/{version}/DiscordChatExporter.Cli.linux-musl-x64.zip',
        },
        'darwin': {  # macOS
            'x64': '{base_url}/{version}/DiscordChatExporter.Cli.osx-x64.zip',
            'arm64': '{base_url}/{version}/DiscordChatExporter.Cli.osx-arm64.zip',
        },
        'windows': {
            'x64': '{base_url}/{version}/DiscordChatExporter.Cli.win-x64.zip',
            'x86': '{base_url}/{version}/DiscordChatExporter.Cli.win-x86.zip',
            'arm64': '{base_url}/{version}/DiscordChatExporter.Cli.win-arm64.zip',
        }
    }
    
    def __init__(self, install_dir: Optional[str] = None, version: Optional[str] = None,
                 enable_cache: bool = True, cache_maxsize: int = 100, cache_ttl: int = 300):
        """
        Initialize Discord Chat Exporter manager.
        
        Args:
            install_dir: Directory to install DiscordChatExporter (defaults to ~/.discord-chat-exporter)
            version: DiscordChatExporter version to download (defaults to latest stable)
            enable_cache: Enable query result caching (default: True)
            cache_maxsize: Maximum number of cached entries (default: 100)
            cache_ttl: Cache time-to-live in seconds (default: 300)
        """
        if install_dir is None:
            install_dir = os.path.expanduser('~/.discord-chat-exporter')
        
        self.install_dir = Path(install_dir)
        self.version = version or self.DEFAULT_VERSION
        self.platform_name = self._detect_platform()
        self.arch = self._detect_architecture()
        
        # Determine the executable name based on platform
        if self.platform_name == 'windows':
            self.cli_executable = self.install_dir / 'DiscordChatExporter.Cli.exe'
        else:
            self.cli_executable = self.install_dir / 'DiscordChatExporter.Cli'
        
        # Initialize cache if available and enabled
        self.cache = None
        if enable_cache and CACHE_AVAILABLE:
            try:
                self.cache = QueryCache(maxsize=cache_maxsize, ttl=cache_ttl)
                logger.info(f"Query cache enabled (maxsize={cache_maxsize}, ttl={cache_ttl}s)")
            except Exception as e:
                logger.warning(f"Failed to initialize cache: {e}")
        
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
            Architecture name: 'x64', 'x86', 'arm64', or 'arm'
        """
        machine = platform.machine().lower()
        
        # Map various architecture names to standardized values
        if machine in ('x86_64', 'amd64'):
            return 'x64'
        elif machine in ('i386', 'i686', 'x86'):
            return 'x86'
        elif machine in ('arm64', 'aarch64'):
            return 'arm64'
        elif machine.startswith('arm'):
            return 'arm'
        else:
            # Default to x64 for unknown architectures
            logger.warning(f"Unknown architecture '{machine}', defaulting to x64")
            return 'x64'
    
    def get_download_url(self) -> str:
        """
        Get the download URL for the current platform and architecture.
        
        Returns:
            Download URL string
        
        Raises:
            RuntimeError: If no download URL is available for the platform/architecture
        """
        try:
            url_template = self.DOWNLOAD_TEMPLATES[self.platform_name][self.arch]
            return url_template.format(
                base_url=self.BASE_URL,
                version=self.version
            )
        except KeyError:
            raise RuntimeError(
                f"No download URL available for platform={self.platform_name}, arch={self.arch}"
            )
    
    def is_installed(self) -> bool:
        """
        Check if DiscordChatExporter is installed.
        
        Returns:
            True if CLI executable exists and is executable (on Unix-like systems),
            or exists (on Windows)
        """
        if self.platform_name == 'windows':
            # On Windows, execute permission bits are not meaningful; existence is sufficient
            return self.cli_executable.exists()
        # On Unix-like systems, require both existence and executable permission
        return self.cli_executable.exists() and os.access(self.cli_executable, os.X_OK)
    
    def download_and_install(self, force: bool = False) -> bool:
        """
        Download and install DiscordChatExporter CLI.
        
        Args:
            force: Force reinstallation even if already installed
        
        Returns:
            True if installation successful, False otherwise
        """
        if self.is_installed() and not force:
            logger.info(f"DiscordChatExporter already installed at {self.cli_executable}")
            return True
        
        try:
            download_url = self.get_download_url()
            logger.info(f"Downloading DiscordChatExporter from {download_url}")
            
            # Download archive to temporary file
            archive_path = self.install_dir / 'discord_chat_exporter.zip'
            urllib.request.urlretrieve(download_url, archive_path)
            
            # Extract archive directly to install directory
            logger.info(f"Extracting DiscordChatExporter to {self.install_dir}")
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # Safely extract ZIP contents to prevent Zip Slip (path traversal)
                install_dir_path = Path(self.install_dir).resolve()
                safe_members = []
                for member in zip_ref.infolist():
                    member_path = Path(member.filename)
                    # Reject absolute paths
                    if member_path.is_absolute():
                        logger.warning(f"Skipping absolute path in archive: {member.filename}")
                        continue
                    # Resolve target path and ensure it stays within install_dir
                    resolved_target = (install_dir_path / member_path).resolve()
                    # Use pathlib's is_relative_to for robust cross-platform path validation
                    try:
                        resolved_target.relative_to(install_dir_path)
                    except ValueError:
                        logger.warning(f"Skipping potentially unsafe path in archive: {member.filename}")
                        continue
                    safe_members.append(member)

                if not safe_members:
                    logger.error("No safe files found to extract from DiscordChatExporter archive")
                    return False

                zip_ref.extractall(self.install_dir, members=safe_members)
            
            # Clean up archive
            archive_path.unlink()
            
            # Make executable (Unix-like systems)
            if self.cli_executable.exists():
                if self.platform_name != 'windows':
                    self.cli_executable.chmod(0o755)
                logger.info(f"DiscordChatExporter installed successfully at {self.cli_executable}")
                return True
            else:
                logger.error("DiscordChatExporter executable not found after extraction")
                return False
                
        except Exception as e:
            logger.error(f"Failed to install DiscordChatExporter: {e}")
            return False
    
    def verify_installation(self) -> bool:
        """
        Verify that DiscordChatExporter is properly installed by running a version check.
        
        Returns:
            True if verification successful, False otherwise
        """
        if not self.is_installed():
            logger.error("DiscordChatExporter is not installed")
            return False
        
        try:
            result = subprocess.run(
                [str(self.cli_executable), '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                version_info = result.stdout.strip()
                logger.info(f"DiscordChatExporter verification successful: {version_info}")
                return True
            else:
                logger.error(f"DiscordChatExporter verification failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("DiscordChatExporter verification timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to verify DiscordChatExporter: {e}")
            return False
    
    def get_version(self) -> Optional[str]:
        """
        Get the installed DiscordChatExporter version.
        
        Returns:
            Version string if successful, None otherwise
        """
        if not self.is_installed():
            return None
        
        try:
            result = subprocess.run(
                [str(self.cli_executable), '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                version_info = result.stdout.strip()
                match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_info)
                if match:
                    return match.group(1)
                return version_info
            return None
            
        except Exception as e:
            logger.error(f"Failed to get version: {e}")
            return None
    
    def execute(self, args: list, timeout: int = 300) -> subprocess.CompletedProcess:
        """
        Execute DiscordChatExporter CLI command.
        
        Args:
            args: Command arguments to pass to DiscordChatExporter
            timeout: Command timeout in seconds (default: 300)
        
        Returns:
            CompletedProcess object with the command result
        
        Raises:
            RuntimeError: If DiscordChatExporter is not installed
            subprocess.TimeoutExpired: If command times out
        """
        if not self.is_installed():
            raise RuntimeError(
                "DiscordChatExporter is not installed. "
                "Run download_and_install() first."
            )
        
        cmd = [str(self.cli_executable)] + args
        logger.debug(f"Executing: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        return result
    
    def uninstall(self) -> bool:
        """
        Uninstall DiscordChatExporter by removing the installation directory.
        
        Returns:
            True if uninstallation successful, False otherwise
        """
        try:
            if self.install_dir.exists():
                shutil.rmtree(self.install_dir)
                logger.info(f"DiscordChatExporter uninstalled from {self.install_dir}")
                return True
            else:
                logger.warning("DiscordChatExporter installation directory not found")
                return False
        except Exception as e:
            logger.error(f"Failed to uninstall DiscordChatExporter: {e}")
            return False


# Convenience function for quick setup
def get_discord_chat_exporter(
    install_dir: Optional[str] = None,
    version: Optional[str] = None,
    auto_install: bool = True
) -> DiscordChatExporter:
    """
    Get a DiscordChatExporter instance with optional automatic installation.
    
    Args:
        install_dir: Installation directory (defaults to ~/.discord-chat-exporter)
        version: Version to install (defaults to latest)
        auto_install: Automatically download and install if not present
    
    Returns:
        Configured DiscordChatExporter instance
    
    Example:
        >>> exporter = get_discord_chat_exporter(auto_install=True)
        >>> result = exporter.execute(['guilds', '-t', 'YOUR_TOKEN'])
    """
    exporter = DiscordChatExporter(install_dir=install_dir, version=version)
    
    if auto_install and not exporter.is_installed():
        logger.info("DiscordChatExporter not found, installing...")
        if not exporter.download_and_install():
            raise RuntimeError("Failed to install DiscordChatExporter")
        if not exporter.verify_installation():
            raise RuntimeError("DiscordChatExporter installation verification failed")
    
    return exporter
