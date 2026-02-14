"""Base CLI tool abstraction.

This module provides a base class for wrapping external CLI tools with
consistent interfaces, caching, and error handling.
"""

import json
import logging
import os
import platform
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..cache import LocalCache

logger = logging.getLogger(__name__)


class BaseCLITool(ABC):
    """Abstract base class for CLI tool wrappers.
    
    Provides common functionality for wrapping external CLI tools:
    - Installation verification
    - Command execution with retry
    - Result caching
    - Error handling
    - Statistics tracking
    
    Subclasses should implement:
    - tool_name: Name of the CLI tool
    - _verify_installation(): Check if tool is installed
    - Any tool-specific methods
    """
    
    # Override in subclass
    tool_name: str = "cli_tool"
    
    def __init__(
        self,
        cli_path: Optional[str] = None,
        enable_cache: bool = True,
        cache_maxsize: int = 100,
        cache_ttl: int = 600
    ):
        """Initialize CLI tool wrapper.
        
        Args:
            cli_path: Path to CLI executable (auto-detected if None)
            enable_cache: Enable query result caching
            cache_maxsize: Maximum cached entries
            cache_ttl: Cache TTL in seconds
        """
        # Find CLI executable
        if cli_path is None:
            self.cli_path = self._find_cli()
        else:
            self.cli_path = Path(cli_path)
        
        # Set up cache
        self.cache = None
        if enable_cache:
            try:
                self.cache = LocalCache(
                    maxsize=cache_maxsize,
                    default_ttl=cache_ttl,
                    name=f"{self.tool_name}Cache"
                )
                logger.info(
                    f"{self.tool_name} cache enabled "
                    f"(maxsize={cache_maxsize}, ttl={cache_ttl}s)"
                )
            except Exception as e:
                logger.warning(f"Failed to initialize {self.tool_name} cache: {e}")
        
        # Verify installation
        self.installed = self._verify_installation()
        if not self.installed:
            logger.warning(f"{self.tool_name} not installed or not accessible")
    
    def _find_cli(self) -> Optional[Path]:
        """Find CLI executable in system PATH.
        
        Returns:
            Path to executable or None if not found
        """
        try:
            cmd = ['where' if platform.system() == 'Windows' else 'which', self.tool_name]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                path = Path(result.stdout.strip().split('\n')[0])
                logger.debug(f"Found {self.tool_name} at {path}")
                return path
        except Exception as e:
            logger.debug(f"Could not find {self.tool_name}: {e}")
        return None
    
    @abstractmethod
    def _verify_installation(self) -> bool:
        """Verify that CLI tool is installed and accessible.
        
        Returns:
            True if installed, False otherwise
        """
        pass
    
    def _run_command(
        self,
        args: List[str],
        stdin: Optional[str] = None,
        timeout: int = 30,
        cache_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run a CLI command with optional caching.
        
        Args:
            args: Command arguments
            stdin: Optional stdin input
            timeout: Command timeout in seconds
            cache_key: Optional cache key for caching results
            
        Returns:
            Dict with stdout, stderr, and returncode
            
        Raises:
            RuntimeError: If command fails or times out
        """
        # Check cache first
        if self.cache and cache_key:
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.debug(f"{self.tool_name} cache hit: {cache_key}")
                return cached
        
        # Run command
        try:
            cmd = [str(self.cli_path)] + args
            logger.debug(f"Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            response = {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'success': result.returncode == 0
            }
            
            # Cache successful results
            if self.cache and cache_key and response['success']:
                self.cache.set(cache_key, response)
                logger.debug(f"{self.tool_name} cached: {cache_key}")
            
            return response
            
        except subprocess.TimeoutExpired as e:
            error_msg = f"{self.tool_name} command timed out after {timeout}s"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"{self.tool_name} command failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
    
    def is_installed(self) -> bool:
        """Check if CLI tool is installed.
        
        Returns:
            True if installed, False otherwise
        """
        return self.installed
    
    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """Get cache statistics.
        
        Returns:
            Dict with cache stats or None if caching disabled
        """
        if self.cache:
            stats = self.cache.get_stats()
            return {
                'size': stats.size,
                'hits': stats.hits,
                'misses': stats.misses,
                'hit_rate': stats.hit_rate,
            }
        return None
    
    def clear_cache(self) -> None:
        """Clear cache if enabled."""
        if self.cache:
            self.cache.clear()
            logger.info(f"Cleared {self.tool_name} cache")
