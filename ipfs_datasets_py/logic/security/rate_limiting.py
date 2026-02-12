"""Rate limiting for logic module.

Provides rate limiting to prevent abuse and DoS attacks.
"""

import time
from functools import wraps
from collections import defaultdict
from typing import Callable, Dict, List, Optional
from threading import RLock
from ipfs_datasets_py.logic.config import get_config


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    pass


class RateLimiter:
    """Rate limiter using sliding window algorithm."""
    
    def __init__(self, calls: int = 100, period: int = 60):
        """Initialize rate limiter.
        
        Args:
            calls: Maximum number of calls allowed
            period: Time period in seconds
        """
        self.calls = calls
        self.period = period
        self.cache: Dict[str, List[float]] = defaultdict(list)
        self.lock = RLock()
    
    def check_rate_limit(self, user_id: str) -> None:
        """Check if user has exceeded rate limit.
        
        Args:
            user_id: User identifier
            
        Raises:
            RateLimitExceeded: If rate limit exceeded
        """
        now = time.time()
        
        with self.lock:
            # Remove old entries outside the window
            self.cache[user_id] = [
                timestamp for timestamp in self.cache[user_id]
                if now - timestamp < self.period
            ]
            
            # Check if limit exceeded
            if len(self.cache[user_id]) >= self.calls:
                oldest = self.cache[user_id][0]
                wait_time = self.period - (now - oldest)
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.calls} calls per {self.period}s. "
                    f"Try again in {wait_time:.1f}s"
                )
            
            # Record this call
            self.cache[user_id].append(now)
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator to apply rate limiting to a function.
        
        Args:
            func: Function to rate limit
            
        Returns:
            Wrapped function
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Try to get user_id from kwargs, or use 'default'
            user_id = kwargs.get('user_id', 'default')
            
            # Check rate limit
            self.check_rate_limit(user_id)
            
            # Call original function
            return func(*args, **kwargs)
        
        return wrapper
    
    def reset(self, user_id: Optional[str] = None) -> None:
        """Reset rate limit for a user.
        
        Args:
            user_id: User to reset. If None, reset all users.
        """
        with self.lock:
            if user_id is None:
                self.cache.clear()
            elif user_id in self.cache:
                del self.cache[user_id]
    
    def get_remaining(self, user_id: str) -> int:
        """Get remaining calls for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            Number of remaining calls
        """
        now = time.time()
        
        with self.lock:
            # Clean old entries
            self.cache[user_id] = [
                timestamp for timestamp in self.cache[user_id]
                if now - timestamp < self.period
            ]
            
            return max(0, self.calls - len(self.cache[user_id]))


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        config = get_config()
        _rate_limiter = RateLimiter(
            calls=config.security.rate_limit_calls,
            period=config.security.rate_limit_period
        )
    return _rate_limiter


def rate_limit(func: Callable) -> Callable:
    """Decorator to apply rate limiting.
    
    Uses global rate limiter configuration.
    
    Args:
        func: Function to rate limit
        
    Returns:
        Wrapped function
    
    Example:
        @rate_limit
        def prove(formula, user_id='default'):
            # Your code here
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        limiter = get_rate_limiter()
        user_id = kwargs.get('user_id', 'default')
        limiter.check_rate_limit(user_id)
        return func(*args, **kwargs)
    
    return wrapper
