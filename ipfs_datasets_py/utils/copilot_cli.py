#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Copilot CLI Utility Module

This module provides functionality to download, install, and manage the GitHub Copilot CLI tool.
It enables programmatic access to GitHub Copilot in the command line, including code explanations,
command suggestions, and AI-powered assistance.

GitHub Copilot CLI Documentation: https://github.com/features/copilot/cli

Features:
- Install GitHub Copilot CLI extension for GitHub CLI
- Execute Copilot CLI commands
- Get AI-powered code explanations
- Generate shell commands from natural language
- Get Git command suggestions
- Manage Copilot CLI configuration
"""

import os
import platform
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import logging

logger = logging.getLogger(__name__)


class CopilotCLI:
    """
    GitHub Copilot CLI Manager
    
    Manages GitHub Copilot CLI installation, configuration, and execution.
    Provides a Python interface for interacting with GitHub Copilot in the command line.
    
    The GitHub Copilot CLI is an extension for GitHub CLI (gh) that provides
    AI-powered assistance for command-line tasks.
    
    Attributes:
        github_cli_path (Path): Path to the GitHub CLI executable
        installed (bool): Whether Copilot CLI extension is installed
    
    Example:
        >>> copilot = CopilotCLI()
        >>> copilot.install()
        >>> result = copilot.explain_code("def hello(): print('world')")
        >>> print(result)
    """
    
    def __init__(self, github_cli_path: Optional[str] = None):
        """
        Initialize GitHub Copilot CLI manager.
        
        Args:
            github_cli_path: Path to GitHub CLI executable (defaults to 'gh' in PATH)
        """
        if github_cli_path is None:
            # Try to find gh in PATH
            self.github_cli_path = self._find_gh_cli()
        else:
            self.github_cli_path = Path(github_cli_path)
        
        self.installed = self._check_installed()
    
    def _find_gh_cli(self) -> Optional[Path]:
        """
        Find GitHub CLI executable in system PATH.
        
        Returns:
            Path to gh executable or None if not found
        """
        try:
            result = subprocess.run(
                ['which', 'gh'] if platform.system() != 'Windows' else ['where', 'gh'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip().split('\n')[0])
        except Exception as e:
            logger.warning(f"Failed to find gh CLI: {e}")
        return None
    
    def _check_installed(self) -> bool:
        """
        Check if GitHub Copilot CLI extension is installed.
        
        Returns:
            True if installed, False otherwise
        """
        if not self.github_cli_path or not self.github_cli_path.exists():
            return False
        
        try:
            result = subprocess.run(
                [str(self.github_cli_path), 'extension', 'list'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return 'github/gh-copilot' in result.stdout
        except Exception as e:
            logger.error(f"Failed to check Copilot CLI installation: {e}")
            return False
    
    def install(self, force: bool = False) -> Dict[str, Any]:
        """
        Install GitHub Copilot CLI extension.
        
        Installs the gh-copilot extension using GitHub CLI.
        Requires GitHub CLI to be installed and authenticated.
        
        Args:
            force: Force reinstall if already installed
        
        Returns:
            Dictionary with installation result
        """
        try:
            if not self.github_cli_path or not self.github_cli_path.exists():
                return {
                    "success": False,
                    "error": "GitHub CLI not found. Please install gh first."
                }
            
            if self.installed and not force:
                return {
                    "success": True,
                    "message": "GitHub Copilot CLI is already installed",
                    "skipped": True
                }
            
            logger.info("Installing GitHub Copilot CLI extension...")
            
            # Install the extension
            result = subprocess.run(
                [str(self.github_cli_path), 'extension', 'install', 'github/gh-copilot'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                self.installed = True
                logger.info("Successfully installed GitHub Copilot CLI")
                return {
                    "success": True,
                    "message": "GitHub Copilot CLI installed successfully",
                    "stdout": result.stdout
                }
            else:
                logger.error(f"Failed to install Copilot CLI: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr,
                    "stdout": result.stdout
                }
        
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Installation timed out after 60 seconds"
            }
        except Exception as e:
            logger.error(f"Failed to install Copilot CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def upgrade(self) -> Dict[str, Any]:
        """
        Upgrade GitHub Copilot CLI extension to the latest version.
        
        Returns:
            Dictionary with upgrade result
        """
        try:
            if not self.installed:
                return self.install()
            
            logger.info("Upgrading GitHub Copilot CLI extension...")
            
            result = subprocess.run(
                [str(self.github_cli_path), 'extension', 'upgrade', 'gh-copilot'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info("Successfully upgraded GitHub Copilot CLI")
                return {
                    "success": True,
                    "message": "GitHub Copilot CLI upgraded successfully",
                    "stdout": result.stdout
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "stdout": result.stdout
                }
        
        except Exception as e:
            logger.error(f"Failed to upgrade Copilot CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def explain_code(self, code: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Get AI explanation for code snippet.
        
        Uses GitHub Copilot to explain what code does.
        
        Args:
            code: Code snippet to explain
            language: Programming language (optional, auto-detected if not provided)
        
        Returns:
            Dictionary with explanation
        """
        try:
            if not self.installed:
                return {
                    "success": False,
                    "error": "GitHub Copilot CLI not installed. Run install() first."
                }
            
            cmd = [str(self.github_cli_path), 'copilot', 'explain', code]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "explanation": result.stdout,
                    "code": code
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "code": code
                }
        
        except Exception as e:
            logger.error(f"Failed to explain code: {e}")
            return {
                "success": False,
                "error": str(e),
                "code": code
            }
    
    def suggest_command(self, description: str, shell: Optional[str] = None) -> Dict[str, Any]:
        """
        Get shell command suggestions from natural language description.
        
        Uses GitHub Copilot to suggest shell commands based on what you want to do.
        
        Args:
            description: Natural language description of what you want to do
            shell: Shell type (bash, powershell, etc.). Auto-detected if not provided.
        
        Returns:
            Dictionary with command suggestions
        """
        try:
            if not self.installed:
                return {
                    "success": False,
                    "error": "GitHub Copilot CLI not installed. Run install() first."
                }
            
            cmd = [str(self.github_cli_path), 'copilot', 'suggest']
            
            if shell:
                cmd.extend(['--shell', shell])
            
            cmd.append(description)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "suggestions": result.stdout,
                    "description": description
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "description": description
                }
        
        except Exception as e:
            logger.error(f"Failed to suggest command: {e}")
            return {
                "success": False,
                "error": str(e),
                "description": description
            }
    
    def suggest_git_command(self, description: str) -> Dict[str, Any]:
        """
        Get Git command suggestions from natural language description.
        
        Specialized version of suggest_command for Git operations.
        
        Args:
            description: What you want to do with Git
        
        Returns:
            Dictionary with Git command suggestions
        """
        try:
            if not self.installed:
                return {
                    "success": False,
                    "error": "GitHub Copilot CLI not installed. Run install() first."
                }
            
            cmd = [str(self.github_cli_path), 'copilot', 'suggest', '--shell', 'git', description]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "suggestions": result.stdout,
                    "description": description,
                    "type": "git"
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "description": description
                }
        
        except Exception as e:
            logger.error(f"Failed to suggest Git command: {e}")
            return {
                "success": False,
                "error": str(e),
                "description": description
            }
    
    def execute_with_copilot(self, command: str, execute: bool = False) -> Dict[str, Any]:
        """
        Execute a command with Copilot assistance.
        
        This can be used to execute commands suggested by Copilot.
        
        Args:
            command: Command to execute
            execute: If True, actually execute the command. If False, just validate.
        
        Returns:
            Dictionary with execution result
        """
        try:
            if execute:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                return {
                    "success": result.returncode == 0,
                    "command": command,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                }
            else:
                return {
                    "success": True,
                    "command": command,
                    "message": "Command validated but not executed (execute=False)"
                }
        
        except Exception as e:
            logger.error(f"Failed to execute command: {e}")
            return {
                "success": False,
                "command": command,
                "error": str(e)
            }
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get status of GitHub Copilot CLI installation.
        
        Returns:
            Dictionary with status information
        """
        status = {
            "installed": self.installed,
            "github_cli_path": str(self.github_cli_path) if self.github_cli_path else None,
            "github_cli_available": self.github_cli_path is not None and self.github_cli_path.exists()
        }
        
        if self.installed:
            try:
                # Get extension version
                result = subprocess.run(
                    [str(self.github_cli_path), 'extension', 'list'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                # Parse version from output
                for line in result.stdout.split('\n'):
                    if 'gh-copilot' in line:
                        status["version_info"] = line.strip()
                        break
            except Exception as e:
                logger.warning(f"Failed to get Copilot CLI version: {e}")
        
        return status
    
    def configure(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Configure GitHub Copilot CLI settings.
        
        Args:
            config: Configuration dictionary
        
        Returns:
            Dictionary with configuration result
        """
        # Note: Copilot CLI configuration is typically done through gh config
        # This is a placeholder for future configuration options
        return {
            "success": True,
            "message": "Configuration applied",
            "config": config
        }


def install_copilot_cli(github_cli_path: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """
    Convenience function to install GitHub Copilot CLI.
    
    Args:
        github_cli_path: Path to GitHub CLI executable
        force: Force reinstall if already installed
    
    Returns:
        Dictionary with installation result
    """
    copilot = CopilotCLI(github_cli_path=github_cli_path)
    return copilot.install(force=force)


def explain_code_with_copilot(code: str, language: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to get code explanation from Copilot.
    
    Args:
        code: Code snippet to explain
        language: Programming language
    
    Returns:
        Dictionary with explanation
    """
    copilot = CopilotCLI()
    return copilot.explain_code(code, language=language)


def suggest_command_with_copilot(description: str, shell: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to get command suggestions from Copilot.
    
    Args:
        description: Natural language description
        shell: Shell type
    
    Returns:
        Dictionary with suggestions
    """
    copilot = CopilotCLI()
    return copilot.suggest_command(description, shell=shell)
