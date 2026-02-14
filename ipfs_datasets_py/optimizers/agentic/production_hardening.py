"""Production hardening utilities for agentic optimizer.

This module provides security, performance, and reliability improvements
for production deployment.
"""

import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import hashlib
import logging

logger = logging.getLogger(__name__)


@dataclass
class SecurityConfig:
    """Security configuration for optimizer."""
    
    # Sandboxing
    enable_sandbox: bool = True
    sandbox_timeout: int = 60
    max_memory_mb: int = 512
    max_cpu_percent: int = 80
    
    # Input validation
    allowed_file_extensions: List[str] = None
    max_file_size_mb: int = 10
    forbidden_patterns: List[str] = None
    
    # Token security
    mask_tokens_in_logs: bool = True
    token_patterns: List[str] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.allowed_file_extensions is None:
            self.allowed_file_extensions = ['.py', '.js', '.ts', '.java', '.go', '.rs']
        
        if self.forbidden_patterns is None:
            self.forbidden_patterns = [
                r'rm\s+-rf',  # Dangerous rm commands
                r'eval\s*\(',  # Eval calls
                r'exec\s*\(',  # Exec calls
                r'__import__\s*\(',  # Dynamic imports
                r'system\s*\(',  # System calls
            ]
        
        if self.token_patterns is None:
            self.token_patterns = [
                r'sk-[a-zA-Z0-9]{48}',  # OpenAI
                r'sk-ant-[a-zA-Z0-9]{48}',  # Anthropic
                r'ya29\.[a-zA-Z0-9_-]{68}',  # Google
                r'ghp_[a-zA-Z0-9]{36}',  # GitHub
            ]


class InputSanitizer:
    """Sanitize and validate user inputs."""
    
    def __init__(self, config: SecurityConfig):
        """Initialize sanitizer."""
        self.config = config
    
    def validate_file_path(self, path: str) -> bool:
        """Validate file path is safe."""
        try:
            # Convert to absolute path and resolve symlinks
            abs_path = Path(path).resolve()
            
            # Check file exists
            if not abs_path.exists():
                logger.warning(f"File does not exist: {path}")
                return False
            
            # Check file extension
            if self.config.allowed_file_extensions:
                if abs_path.suffix not in self.config.allowed_file_extensions:
                    logger.warning(f"File extension not allowed: {abs_path.suffix}")
                    return False
            
            # Check file size
            if abs_path.is_file():
                size_mb = abs_path.stat().st_size / (1024 * 1024)
                if size_mb > self.config.max_file_size_mb:
                    logger.warning(f"File too large: {size_mb:.1f}MB")
                    return False
            
            # Check for path traversal
            if '..' in str(abs_path):
                logger.warning(f"Path traversal attempt: {path}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating path {path}: {e}")
            return False
    
    def validate_code(self, code: str) -> tuple[bool, List[str]]:
        """Validate code for dangerous patterns."""
        issues = []
        
        # Check for forbidden patterns
        for pattern in self.config.forbidden_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                issues.append(f"Forbidden pattern detected: {pattern}")
        
        # Check for long lines (possible injection)
        for i, line in enumerate(code.split('\n'), 1):
            if len(line) > 1000:
                issues.append(f"Suspiciously long line {i}: {len(line)} chars")
        
        return len(issues) == 0, issues
    
    def sanitize_log_message(self, message: str) -> str:
        """Remove sensitive tokens from log messages."""
        if not self.config.mask_tokens_in_logs:
            return message
        
        sanitized = message
        for pattern in self.config.token_patterns:
            sanitized = re.sub(pattern, '[TOKEN_REDACTED]', sanitized)
        
        return sanitized


class SandboxExecutor:
    """Execute code in sandboxed environment."""
    
    def __init__(self, config: SecurityConfig):
        """Initialize sandbox executor."""
        self.config = config
    
    def execute_code(
        self,
        code: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> tuple[bool, str, str]:
        """Execute code in sandbox with timeout.
        
        Args:
            code: Code to execute
            timeout: Execution timeout in seconds
            env: Environment variables
        
        Returns:
            Tuple of (success, stdout, stderr)
        """
        if timeout is None:
            timeout = self.config.sandbox_timeout
        
        # Create safe environment
        safe_env = os.environ.copy()
        if env:
            safe_env.update(env)
        
        # Remove sensitive env vars
        for key in list(safe_env.keys()):
            if any(token in key.upper() for token in ['KEY', 'TOKEN', 'SECRET', 'PASSWORD']):
                safe_env.pop(key)
        
        try:
            # Execute in subprocess with timeout
            result = subprocess.run(
                ['python', '-c', code],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
                check=False,
            )
            
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
            )
            
        except subprocess.TimeoutExpired:
            logger.warning(f"Code execution timeout after {timeout}s")
            return False, "", f"Execution timeout after {timeout}s"
        
        except Exception as e:
            logger.error(f"Sandbox execution error: {e}")
            return False, "", str(e)


class CircuitBreaker:
    """Circuit breaker pattern for external services."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: type = Exception,
    ):
        """Initialize circuit breaker."""
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Call function with circuit breaker protection."""
        with self._lock:
            if self.state == "OPEN":
                # Check if timeout has passed
                if time.time() - self.last_failure_time >= self.timeout:
                    self.state = "HALF_OPEN"
                    logger.info("Circuit breaker half-open, trying request")
                else:
                    raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            
            # Success - reset failure count
            with self._lock:
                self.failure_count = 0
                if self.state == "HALF_OPEN":
                    self.state = "CLOSED"
                    logger.info("Circuit breaker closed")
            
            return result
            
        except self.expected_exception as e:
            with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                
                if self.failure_count >= self.failure_threshold:
                    self.state = "OPEN"
                    logger.error(f"Circuit breaker opened after {self.failure_count} failures")
            
            raise e


class RetryHandler:
    """Exponential backoff retry handler."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ):
        """Initialize retry handler."""
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
    
    def retry(
        self,
        func: Callable,
        *args,
        retryable_exceptions: tuple = (Exception,),
        **kwargs,
    ) -> Any:
        """Retry function with exponential backoff."""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
                
            except retryable_exceptions as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    # Calculate delay with exponential backoff
                    delay = min(
                        self.base_delay * (self.exponential_base ** attempt),
                        self.max_delay,
                    )
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.max_retries + 1} failed, "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"All {self.max_retries + 1} attempts failed: {e}"
                    )
        
        raise last_exception


class ResourceMonitor:
    """Monitor resource usage."""
    
    def __init__(self):
        """Initialize resource monitor."""
        self.start_time = None
        self.peak_memory = 0
    
    @contextmanager
    def monitor(self):
        """Context manager for resource monitoring."""
        import resource
        import tracemalloc
        
        # Start monitoring
        self.start_time = time.time()
        tracemalloc.start()
        
        try:
            yield self
        finally:
            # Get peak memory
            current, peak = tracemalloc.get_traced_memory()
            self.peak_memory = peak / (1024 * 1024)  # Convert to MB
            tracemalloc.stop()
    
    def get_stats(self) -> Dict[str, float]:
        """Get resource usage statistics."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        return {
            "elapsed_time": elapsed,
            "peak_memory_mb": self.peak_memory,
        }


# Global instances
_security_config = SecurityConfig()
_input_sanitizer = InputSanitizer(_security_config)
_sandbox_executor = SandboxExecutor(_security_config)


def get_security_config() -> SecurityConfig:
    """Get global security configuration."""
    return _security_config


def get_input_sanitizer() -> InputSanitizer:
    """Get global input sanitizer."""
    return _input_sanitizer


def get_sandbox_executor() -> SandboxExecutor:
    """Get global sandbox executor."""
    return _sandbox_executor
