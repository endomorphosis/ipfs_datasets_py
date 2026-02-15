from dataclasses import dataclass
from functools import wraps
from enum import Enum
import logging
import os
import threading
from typing import Any, Optional, Generic, TypeVar, Callable


import psutil
from pydantic import BaseModel


from configs.configs import Configs
from utils.converter_system.monads.monad import Monad
from utils.converter_system.monads.either import Either
from utils.converter_system.monads.error import ErrorMonad
from utils.converter_system.monads.helper_functions import start, stop


# Type definitions
T = TypeVar('T')
E = TypeVar('E')
Resource = TypeVar('Resource') # TODO Import the pydantic model from experiments file.





class ValidationResult(Enum):
    VALID = "VALID"
    INVALID_TYPE = "INVALID_TYPE"
    CORRUPTED = "CORRUPTED"
    SIZE_EXCEEDED = "SIZE_EXCEEDED"

class ConversionStatus(Enum):
    IDLE = "IDLE"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"

# Health monitoring system
class HealthMonitor:

    def __init__(self, resources=None, configs=None):
        self.configs = configs
        self.resources = resources

        self.counter_lock = threading.RLock()
        self.memory_threshold = 0.85
        self.max_file_handles = 100
        self.status = ConversionStatus.IDLE

    def check_memory(self, x: Any) -> Any|Exception:
        memory = psutil.virtual_memory()
        if memory.percent > (self.memory_threshold * 100):
            return ValueError(f"Memory usage too high: {memory.percent}%")
        return x

    def check_file_handles(self, x: Any) -> Either[str, int]:

        # Get the current process ID
        if os.name == 'nt':
            # On Windows, we'll use the pid we just obtained
            current_handles = psutil.Process(os.getpid()).num_fds()
        else: # On Linux, psutil.Process().num_fds() works directly
            current_handles = psutil.Process().num_fds()

        # Use psutil to get the number of open file descriptors for the current process
        if current_handles >= self.max_file_handles:
            return ValueError(f"Too many open files: {current_handles}")
        return x


# Circuit Breaker implementation TODO Rewrite with Monad pipelines in mind.
class CircuitBreaker:

    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.is_open = False
        self.last_failure_time = 0

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if self.is_open:
                raise Exception("Circuit breaker is open")
            
            try:
                result = func(*args, **kwargs)
                self.failure_count = 0
                return result
            except Exception as e:
                self.failure_count += 1
                if self.failure_count >= self.failure_threshold:
                    self.is_open = True
                raise e
        return wrapper

# Placeholder Resource manager with context
class ResourceManager:

    def __init__(self, resources=None, configs=None):
        self.configs = configs
        self.resources = resources

        self._logger = self.resources['logger']

        self._throttle = self.resources['throttle']
        self._check_memory = self.resources['check_memory']
        self._check_file_handles = self.resources['check_file_handles']

    def __enter__(self):
        x = True # Dummy value. 
        health_check: Monad = start(x, ErrorMonad
            ) >> (
                lambda x: self._check_file_handles(x)
            ) >> (
                lambda x: self._check_memory(x)
            ) >> stop

        if health_check.errored:
            self._logger.error(f"Health check failed: {health_check.value}")
            self._throttle(health_check.value)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup resources
        pass

    def throttle(self, error: Exception):
        """Stop the allocation of resources to the Core Resource Manager."""
        self._throttle(error)


# Example usage with all patterns combined
@dataclass
class ConversionResult:
    success: bool
    content: Optional[str]
    error: Optional[str]


class ResourceException(BaseModel, Exception):
    cid: str
    exception: Exception = None
    message: Optional[str] = None


class CoreErrorManager:

    def __init__(self, resources=None, configs=None):
        self.configs = configs
        self.resources = resources

        self._logger: logging.Logger = self.resources['logger']

    def log(self, result: Resource) -> Resource:
        """
        
        """
        if isinstance(result, Exception):
            self._logger.error(f"Error occurred: {result}")

    def kill_pipeline():
        pass
