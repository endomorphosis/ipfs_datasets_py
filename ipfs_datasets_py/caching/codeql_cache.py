"""
CodeQL API Cache

This module provides caching capabilities for CodeQL security scanning results
to reduce redundant scans and improve CI/CD performance.

Features:
- Cache CodeQL analysis results by commit SHA and scan configuration
- Content-addressed storage using IPFS multiformats
- P2P cache sharing between runners (reuses GitHub cache infrastructure)
- Automatic invalidation on code changes
- Integration with GitHub's CodeQL action
"""

import json
import logging
import os
import time
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# Import the existing GitHub cache infrastructure
from .cache import GitHubAPICache, CacheEntry

logger = logging.getLogger(__name__)


@dataclass
class CodeQLScanResult:
    """Represents a CodeQL security scan result."""
    commit_sha: str
    scan_config_hash: str
    results: Dict[str, Any]
    timestamp: float
    scan_duration: float
    alerts_count: int
    severity_breakdown: Dict[str, int]
    sarif_location: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'commit_sha': self.commit_sha,
            'scan_config_hash': self.scan_config_hash,
            'results': self.results,
            'timestamp': self.timestamp,
            'scan_duration': self.scan_duration,
            'alerts_count': self.alerts_count,
            'severity_breakdown': self.severity_breakdown,
            'sarif_location': self.sarif_location
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodeQLScanResult':
        """Create from dictionary."""
        return cls(**data)


class CodeQLCache:
    """
    Cache for CodeQL security scan results.
    
    This cache reduces redundant security scans by:
    - Caching results by commit SHA and scan configuration
    - Sharing results via P2P between runners
    - Automatically invalidating on code changes
    - Maintaining cache coherency across the repository
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        github_cache: Optional[GitHubAPICache] = None,
        default_ttl: int = 86400,  # 24 hours - scans are expensive
        enable_p2p: bool = True
    ):
        """
        Initialize the CodeQL cache.
        
        Args:
            cache_dir: Directory for persistent cache (default: ~/.cache/codeql)
            github_cache: GitHub API cache instance to reuse (creates new if None)
            default_ttl: Default time-to-live for cache entries in seconds
            enable_p2p: Whether to enable P2P cache sharing
        """
        self.default_ttl = default_ttl
        
        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".cache" / "codeql"
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Reuse GitHub cache infrastructure for P2P and persistence
        if github_cache:
            self.github_cache = github_cache
        else:
            self.github_cache = GitHubAPICache(
                cache_dir=str(self.cache_dir / "github_cache"),
                enable_p2p=enable_p2p,
                enable_peer_discovery=True,
                default_ttl=default_ttl
            )
        
        # Statistics
        self._stats = {
            "scans_cached": 0,
            "scans_retrieved": 0,
            "scans_skipped": 0,
            "scan_time_saved_seconds": 0
        }
        
        logger.info(f"Initialized CodeQL cache at {self.cache_dir}")
        logger.info(f"  P2P sharing: {'enabled' if enable_p2p else 'disabled'}")
    
    def _compute_scan_config_hash(self, config: Dict[str, Any]) -> str:
        """
        Compute a hash of the scan configuration.
        
        Args:
            config: Scan configuration dictionary
            
        Returns:
            Hash of the configuration
        """
        # Sort config for deterministic hashing
        config_json = json.dumps(config, sort_keys=True)
        hasher = hashlib.sha256()
        hasher.update(config_json.encode('utf-8'))
        return hasher.hexdigest()
    
    def _make_cache_key(
        self,
        repo: str,
        commit_sha: str,
        scan_config_hash: str,
        language: Optional[str] = None
    ) -> str:
        """
        Create a cache key for a CodeQL scan.
        
        Args:
            repo: Repository name (owner/repo)
            commit_sha: Commit SHA being scanned
            scan_config_hash: Hash of scan configuration
            language: Programming language being scanned
            
        Returns:
            Cache key string
        """
        parts = ["codeql_scan", repo, commit_sha, scan_config_hash]
        if language:
            parts.append(language)
        return ":".join(parts)
    
    def get_scan_result(
        self,
        repo: str,
        commit_sha: str,
        scan_config: Dict[str, Any],
        language: Optional[str] = None
    ) -> Optional[CodeQLScanResult]:
        """
        Get cached CodeQL scan result.
        
        Args:
            repo: Repository name (owner/repo)
            commit_sha: Commit SHA being scanned
            scan_config: Scan configuration used
            language: Programming language being scanned
            
        Returns:
            Cached scan result or None if not found/expired
        """
        scan_config_hash = self._compute_scan_config_hash(scan_config)
        cache_key = self._make_cache_key(repo, commit_sha, scan_config_hash, language)
        
        # Try to get from cache
        cached_data = self.github_cache.get("codeql", cache_key)
        
        if cached_data:
            logger.info(f"CodeQL cache hit for {repo}@{commit_sha[:8]}")
            self._stats["scans_retrieved"] += 1
            
            result = CodeQLScanResult.from_dict(cached_data)
            
            # Track time saved (average CodeQL scan takes ~5 minutes)
            self._stats["scan_time_saved_seconds"] += result.scan_duration or 300
            
            return result
        
        logger.debug(f"CodeQL cache miss for {repo}@{commit_sha[:8]}")
        return None
    
    def put_scan_result(
        self,
        repo: str,
        commit_sha: str,
        scan_config: Dict[str, Any],
        results: Dict[str, Any],
        scan_duration: float,
        language: Optional[str] = None,
        sarif_location: Optional[str] = None,
        ttl: Optional[int] = None
    ) -> str:
        """
        Store CodeQL scan result in cache.
        
        Args:
            repo: Repository name (owner/repo)
            commit_sha: Commit SHA being scanned
            scan_config: Scan configuration used
            results: Scan results (SARIF format or processed)
            scan_duration: Time taken for the scan in seconds
            language: Programming language scanned
            sarif_location: Path to SARIF file if stored separately
            ttl: Time-to-live in seconds (uses default if None)
            
        Returns:
            Cache key used for storage
        """
        scan_config_hash = self._compute_scan_config_hash(scan_config)
        cache_key = self._make_cache_key(repo, commit_sha, scan_config_hash, language)
        
        # Extract alert statistics from results
        alerts_count = 0
        severity_breakdown = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "warning": 0,
            "note": 0
        }
        
        # Parse SARIF format if present
        if isinstance(results, dict):
            runs = results.get('runs', [])
            for run in runs:
                for result in run.get('results', []):
                    alerts_count += 1
                    # Extract severity
                    level = result.get('level', 'warning').lower()
                    severity = result.get('properties', {}).get('security-severity', 'medium')
                    
                    # Map to severity category
                    if level in severity_breakdown:
                        severity_breakdown[level] += 1
        
        # Create scan result object
        scan_result = CodeQLScanResult(
            commit_sha=commit_sha,
            scan_config_hash=scan_config_hash,
            results=results,
            timestamp=time.time(),
            scan_duration=scan_duration,
            alerts_count=alerts_count,
            severity_breakdown=severity_breakdown,
            sarif_location=sarif_location
        )
        
        # Store in cache using GitHub cache infrastructure
        self.github_cache.put(
            "codeql",
            scan_result.to_dict(),
            ttl or self.default_ttl,
            cache_key
        )
        
        self._stats["scans_cached"] += 1
        logger.info(f"Cached CodeQL scan for {repo}@{commit_sha[:8]} ({alerts_count} alerts)")
        
        return cache_key
    
    def should_skip_scan(
        self,
        repo: str,
        commit_sha: str,
        scan_config: Dict[str, Any],
        language: Optional[str] = None,
        changed_files: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[CodeQLScanResult]]:
        """
        Determine if a CodeQL scan can be skipped based on cache.
        
        Args:
            repo: Repository name (owner/repo)
            commit_sha: Commit SHA being scanned
            scan_config: Scan configuration to use
            language: Programming language to scan
            changed_files: List of changed files (for smarter invalidation)
            
        Returns:
            Tuple of (should_skip, cached_result)
        """
        # Check if we have a cached result
        cached_result = self.get_scan_result(repo, commit_sha, scan_config, language)
        
        if not cached_result:
            logger.debug("No cached scan found")
            return (False, None)
        
        # If we have changed files info, check if they affect the scan
        if changed_files and language:
            # Language-specific file extensions
            lang_extensions = {
                'python': ['.py'],
                'javascript': ['.js', '.jsx', '.ts', '.tsx'],
                'java': ['.java'],
                'cpp': ['.cpp', '.cc', '.cxx', '.c', '.h', '.hpp'],
                'csharp': ['.cs'],
                'go': ['.go'],
                'ruby': ['.rb'],
                'swift': ['.swift']
            }
            
            extensions = lang_extensions.get(language.lower(), [])
            
            # Check if any changed files match the language
            relevant_changes = False
            for file_path in changed_files:
                if any(file_path.endswith(ext) for ext in extensions):
                    relevant_changes = True
                    break
            
            if not relevant_changes:
                logger.info(f"No relevant changes for {language}, using cached scan")
                self._stats["scans_skipped"] += 1
                return (True, cached_result)
        
        # By default, if we have a recent cached result, use it
        cache_age_hours = (time.time() - cached_result.timestamp) / 3600
        if cache_age_hours < 24:  # Less than 24 hours old
            logger.info(f"Using recent cached scan ({cache_age_hours:.1f} hours old)")
            self._stats["scans_skipped"] += 1
            return (True, cached_result)
        
        logger.debug("Cached scan too old or changes detected")
        return (False, cached_result)
    
    def invalidate_scan(
        self,
        repo: str,
        commit_sha: str,
        scan_config: Optional[Dict[str, Any]] = None,
        language: Optional[str] = None
    ) -> None:
        """
        Invalidate a cached scan result.
        
        Args:
            repo: Repository name (owner/repo)
            commit_sha: Commit SHA to invalidate
            scan_config: Scan configuration (invalidates all if None)
            language: Programming language (invalidates all if None)
        """
        if scan_config:
            scan_config_hash = self._compute_scan_config_hash(scan_config)
            cache_key = self._make_cache_key(repo, commit_sha, scan_config_hash, language)
            self.github_cache.invalidate("codeql", cache_key)
            logger.info(f"Invalidated CodeQL scan for {repo}@{commit_sha[:8]}")
        else:
            # Invalidate all scans for this commit
            pattern = f"codeql_scan:{repo}:{commit_sha}"
            count = self.github_cache.invalidate_pattern(pattern)
            logger.info(f"Invalidated {count} CodeQL scans for {repo}@{commit_sha[:8]}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary of cache statistics
        """
        github_stats = self.github_cache.get_stats()
        
        time_saved_hours = self._stats["scan_time_saved_seconds"] / 3600
        
        return {
            **self._stats,
            "scan_time_saved_hours": round(time_saved_hours, 2),
            "github_cache_stats": github_stats
        }
    
    def clear(self) -> None:
        """Clear all cached CodeQL scans."""
        self.github_cache.invalidate_pattern("codeql_scan")
        self._stats = {
            "scans_cached": 0,
            "scans_retrieved": 0,
            "scans_skipped": 0,
            "scan_time_saved_seconds": 0
        }
        logger.info("Cleared all CodeQL cache entries")


# Global cache instance
_global_codeql_cache: Optional[CodeQLCache] = None


def get_global_codeql_cache(**kwargs) -> CodeQLCache:
    """
    Get or create the global CodeQL cache instance.
    
    Args:
        **kwargs: Arguments to pass to CodeQLCache constructor
        
    Returns:
        Global CodeQLCache instance
    """
    global _global_codeql_cache
    
    if _global_codeql_cache is None:
        _global_codeql_cache = CodeQLCache(**kwargs)
    
    return _global_codeql_cache


def configure_codeql_cache(**kwargs) -> CodeQLCache:
    """
    Configure the global CodeQL cache with custom settings.
    
    Args:
        **kwargs: Arguments to pass to CodeQLCache constructor
        
    Returns:
        Configured CodeQLCache instance
    """
    global _global_codeql_cache
    _global_codeql_cache = CodeQLCache(**kwargs)
    return _global_codeql_cache
