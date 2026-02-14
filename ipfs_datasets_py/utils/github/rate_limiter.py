"""GitHub API rate limiter.

This module provides rate limit monitoring and adaptive caching strategies
to avoid hitting GitHub API rate limits.
"""

import logging
import subprocess
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """GitHub API rate limit monitor and manager.
    
    Monitors GitHub API rate limits and implements adaptive strategies:
    - Warning when approaching limits
    - Aggressive caching when near limits
    - Automatic fallback to cached-only mode
    
    Example:
        >>> limiter = RateLimiter()
        >>> if limiter.should_cache_aggressively():
        ...     # Use cache-first strategy
        ...     pass
        >>> limiter.check_rate_limit()  # Raises if at limit
    """
    
    def __init__(
        self,
        warning_threshold: int = 100,
        aggressive_threshold: int = 50,
        gh_path: str = "gh"
    ):
        """Initialize rate limiter.
        
        Args:
            warning_threshold: Warn when remaining < this
            aggressive_threshold: Enable aggressive caching when remaining < this
            gh_path: Path to gh executable
        """
        self.warning_threshold = warning_threshold
        self.aggressive_threshold = aggressive_threshold
        self.gh_path = gh_path
        
        # Cache rate limit info
        self._cached_limits: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = 60  # Cache for 1 minute
    
    def get_rate_limits(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get current rate limit status.
        
        Args:
            force_refresh: Force refresh from API (skip cache)
            
        Returns:
            Dict with rate limit information:
            - limit: Total API calls allowed per hour
            - remaining: Remaining API calls
            - reset: When limit resets (datetime)
            - used: API calls used
        """
        # Check cache
        if not force_refresh and self._cached_limits and self._cache_time:
            age = (datetime.now() - self._cache_time).total_seconds()
            if age < self._cache_ttl:
                return self._cached_limits
        
        try:
            # Query gh API for rate limit
            result = subprocess.run(
                [self.gh_path, 'api', 'rate_limit'],
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )
            
            data = json.loads(result.stdout)
            core_limits = data.get('resources', {}).get('core', {})
            
            # Parse reset time
            reset_timestamp = core_limits.get('reset', 0)
            reset_time = datetime.fromtimestamp(reset_timestamp)
            
            limits = {
                'limit': core_limits.get('limit', 5000),
                'remaining': core_limits.get('remaining', 0),
                'reset': reset_time,
                'used': core_limits.get('used', 0),
            }
            
            # Update cache
            self._cached_limits = limits
            self._cache_time = datetime.now()
            
            return limits
            
        except Exception as e:
            logger.error(f"Failed to get rate limits: {e}")
            # Return conservative defaults
            return {
                'limit': 5000,
                'remaining': 0,
                'reset': datetime.now() + timedelta(hours=1),
                'used': 5000,
            }
    
    def check_rate_limit(self) -> None:
        """Check rate limit and warn/error if approaching limit.
        
        Raises:
            RuntimeError: If rate limit is exhausted
        """
        limits = self.get_rate_limits()
        remaining = limits['remaining']
        
        if remaining <= 0:
            reset_time = limits['reset']
            wait_seconds = (reset_time - datetime.now()).total_seconds()
            raise RuntimeError(
                f"GitHub API rate limit exhausted. "
                f"Resets in {wait_seconds:.0f} seconds at {reset_time}"
            )
        elif remaining <= self.aggressive_threshold:
            logger.warning(
                f"GitHub API rate limit critically low: {remaining} remaining "
                f"(threshold: {self.aggressive_threshold})"
            )
        elif remaining <= self.warning_threshold:
            logger.warning(
                f"GitHub API rate limit getting low: {remaining} remaining "
                f"(threshold: {self.warning_threshold})"
            )
    
    def should_cache_aggressively(self) -> bool:
        """Check if aggressive caching should be used.
        
        Returns:
            True if remaining calls < aggressive_threshold
        """
        limits = self.get_rate_limits()
        remaining = limits['remaining']
        return remaining < self.aggressive_threshold
    
    def should_warn(self) -> bool:
        """Check if warning threshold has been reached.
        
        Returns:
            True if remaining calls < warning_threshold
        """
        limits = self.get_rate_limits()
        remaining = limits['remaining']
        return remaining < self.warning_threshold
    
    def get_status(self) -> str:
        """Get rate limit status string.
        
        Returns:
            Human-readable status string
        """
        limits = self.get_rate_limits()
        remaining = limits['remaining']
        limit = limits['limit']
        reset = limits['reset']
        
        percentage = (remaining / limit * 100) if limit > 0 else 0
        
        status_parts = [
            f"Rate Limit: {remaining}/{limit} ({percentage:.1f}%)",
            f"Resets: {reset.strftime('%Y-%m-%d %H:%M:%S')}"
        ]
        
        if remaining <= self.aggressive_threshold:
            status_parts.append("⚠️  CRITICAL - Aggressive caching enabled")
        elif remaining <= self.warning_threshold:
            status_parts.append("⚠️  Warning - Approaching limit")
        else:
            status_parts.append("✅ OK")
        
        return " | ".join(status_parts)


# Backward compatibility alias
AdaptiveRateLimiter = RateLimiter
