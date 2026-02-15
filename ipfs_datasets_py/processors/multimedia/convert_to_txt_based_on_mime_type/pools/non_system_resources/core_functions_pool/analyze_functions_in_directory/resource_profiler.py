
import ast
import os
import psutil
import cProfile
import pstats
import time
import inspect
import gc
import tracemalloc
from typing import Dict, List, Set, Optional, Any, Callable
from dataclasses import dataclass
from memory_profiler import profile as memory_profile
from functools import wraps


@dataclass
class ResourceUsage:
    cpu_percent: float
    ram_mb: float
    vram_mb: Optional[float]
    execution_time: float
    peak_memory: float


@dataclass
class FunctionAnalysis:
    name: str
    file_path: str
    parameters: List[str]
    return_type_hints: Optional[str]
    calls_external_functions: bool
    has_loops: bool
    has_recursion: bool
    complexity_warnings: List[str]
    imported_modules: Set[str]
    resource_usage: Optional[ResourceUsage] = None


class ResourceProfiler:

    def __init__(self, max_execution_time: float = 5.0):
        self.max_execution_time = max_execution_time
        self.has_torch: bool = None
        try:
            import torch
            self.has_torch = True
        except Exception as e:
            print("Could not load torch. Skipping VRAM profiling...")
            self.has_torch = False

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Start resource tracking
            process = psutil.Process()
            start_cpu = process.cpu_percent()
            tracemalloc.start()
            
            # Track VRAM if CUDA is available
            if self.has_torch:
                vram_start = None
                if torch.cuda.is_available():
                    torch.cuda.reset_peak_memory_stats()
                    vram_start = torch.cuda.memory_allocated()
                
            start_time = time.time()
            
            # Execute with timeout
            result = None
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                print(f"Error executing {func.__name__}: {e}")
                return None
            finally:
                execution_time = time.time() - start_time
                
                # Get CPU usage
                cpu_percent = process.cpu_percent()
                
                # Get RAM usage
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                
                # Get VRAM usage if applicable
                if self.has_torch:
                    vram_used = None
                    if vram_start is not None:
                        vram_used = (torch.cuda.memory_allocated() - vram_start) / 1024 / 1024  # MB

                # Store resource usage
                func.resource_usage = ResourceUsage(
                    cpu_percent=cpu_percent - start_cpu,
                    ram_mb=peak / 1024 / 1024,  # Convert to MB
                    vram_mb=vram_used,
                    execution_time=execution_time,
                    peak_memory=peak / 1024 / 1024  # Convert to MB
                )

                if execution_time > self.max_execution_time:
                    print(f"Warning: {func.__name__} exceeded maximum execution time")
                
            return result
        return wrapper