"""GitHub Copilot CLI wrapper.

Refactored from utils/copilot_cli.py to use BaseCLITool and unified cache.
"""

import json
import logging
import subprocess
from typing import Any, Dict, Optional

from .base import BaseCLITool

logger = logging.getLogger(__name__)


class Copilot(BaseCLITool):
    """GitHub Copilot CLI wrapper.
    
    Provides Python interface for GitHub Copilot CLI, which is an extension
    for GitHub CLI (gh) that provides AI-powered assistance.
    
    Example:
        >>> copilot = Copilot()
        >>> if copilot.is_installed():
        ...     result = copilot.suggest("list files")
        ...     print(result)
    """
    
    tool_name = "gh"
    
    def __init__(
        self,
        github_cli_path: Optional[str] = None,
        enable_cache: bool = True,
        cache_maxsize: int = 100,
        cache_ttl: int = 600
    ):
        """Initialize Copilot CLI wrapper.
        
        Args:
            github_cli_path: Path to gh executable (auto-detected if None)
            enable_cache: Enable query result caching
            cache_maxsize: Maximum cached entries
            cache_ttl: Cache TTL in seconds (default: 10 minutes)
        """
        super().__init__(
            cli_path=github_cli_path,
            enable_cache=enable_cache,
            cache_maxsize=cache_maxsize,
            cache_ttl=cache_ttl
        )
        
        # Check if Copilot extension is installed
        self.copilot_installed = self._check_copilot_extension()
    
    def _verify_installation(self) -> bool:
        """Verify GitHub CLI is installed.
        
        Returns:
            True if gh CLI is installed
        """
        if not self.cli_path or not self.cli_path.exists():
            return False
        
        try:
            result = subprocess.run(
                [str(self.cli_path), '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Failed to verify gh CLI: {e}")
            return False
    
    def _check_copilot_extension(self) -> bool:
        """Check if Copilot extension is installed.
        
        Returns:
            True if Copilot extension is installed
        """
        if not self.installed:
            return False
        
        try:
            result = subprocess.run(
                [str(self.cli_path), 'extension', 'list'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return 'gh-copilot' in result.stdout or 'copilot' in result.stdout
        except Exception as e:
            logger.debug(f"Failed to check Copilot extension: {e}")
            return False
    
    def install(self) -> bool:
        """Install GitHub Copilot CLI extension.
        
        Returns:
            True if installation succeeded
        """
        if not self.installed:
            logger.error("GitHub CLI not installed, cannot install Copilot extension")
            return False
        
        try:
            result = subprocess.run(
                [str(self.cli_path), 'extension', 'install', 'github/gh-copilot'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                self.copilot_installed = True
                logger.info("Copilot extension installed successfully")
                return True
            else:
                logger.error(f"Failed to install Copilot: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error installing Copilot: {e}")
            return False
    
    def suggest(
        self,
        query: str,
        cache_result: bool = True
    ) -> str:
        """Get command suggestion from Copilot.
        
        Args:
            query: Natural language query
            cache_result: Whether to cache the result
            
        Returns:
            Suggested command as string
            
        Raises:
            RuntimeError: If Copilot is not installed or command fails
        """
        if not self.copilot_installed:
            raise RuntimeError("GitHub Copilot extension not installed")
        
        cache_key = f"suggest:{query}" if cache_result else None
        
        result = self._run_command(
            ['copilot', 'suggest', query],
            cache_key=cache_key
        )
        
        if result['success']:
            return result['stdout'].strip()
        else:
            raise RuntimeError(f"Copilot suggest failed: {result['stderr']}")
    
    def explain(
        self,
        code: str,
        cache_result: bool = True
    ) -> str:
        """Get explanation for code from Copilot.
        
        Args:
            code: Code to explain
            cache_result: Whether to cache the result
            
        Returns:
            Explanation as string
            
        Raises:
            RuntimeError: If Copilot is not installed or command fails
        """
        if not self.copilot_installed:
            raise RuntimeError("GitHub Copilot extension not installed")
        
        cache_key = f"explain:{code[:100]}" if cache_result else None
        
        result = self._run_command(
            ['copilot', 'explain', code],
            cache_key=cache_key
        )
        
        if result['success']:
            return result['stdout'].strip()
        else:
            raise RuntimeError(f"Copilot explain failed: {result['stderr']}")


# Backward compatibility alias
CopilotCLI = Copilot
