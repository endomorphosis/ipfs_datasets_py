





from functools import cache
import os
import subprocess


try:
    import psutil
except ImportError:
    raise ImportError("psutil is not installed. Please install it using 'pip install psutil'.")


from types_ import Any, NamedTuple


_PID = os.getpid()

_BYTE_MAPPING = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024 ** 2,
    "GiB": 1024 ** 3,
    "TiB": 1024 ** 4,
    "PiB": 1024 ** 5,
    "EiB": 1024 ** 6,
    "ZiB": 1024 ** 7,
    "YiB": 1024 ** 8,
    "bit": 1 / 8
}

class Software:
    """
    Software is a utility class that provides static methods to monitor system and process external software usage.
    This includes:
    - CPU usage of program's called by the Omni-Converter
    - Virtual memory usage of program's called by the Omni-Converter
    - Memory information (RSS and VMS) of program's called by the Omni-Converter
    - Disk usage of program's called by the Omni-Converter
    - Number of open files
    - Shared memory usage of program's called by the Omni-Converter
    - Number of CPU cores
    - VRAM usage (if CUDA is available) of program's called by the Omni-Converter

    Methods:
        _get_cpu_usage() -> float:
            Returns the CPU usage percentage over a short interval.

        _get_virtual_memory_in_percent() -> float:
            Returns the percentage of virtual memory currently in use.

        _get_memory_info() -> NamedTuple:
            Returns detailed memory information of the current process.

        _get_memory_rss_usage_in_mb() -> float:
            Returns the Resident Set Size (RSS) memory usage of the current process in megabytes.

        _get_memory_vms_usage_in_mb() -> float:
            Returns the Virtual Memory Size (VMS) usage of the current process in megabytes.

        _get_disk_usage_in_percent() -> float:
            Returns the percentage of disk usage for the root directory.

        _get_num_open_files() -> int:
            Returns the number of open file descriptors for the current process.

        _get_shared_memory_usage_in_mb() -> float:
            Returns the shared memory usage of the current process in megabytes, if available.
    """
    # Decorator to create class properties
    class _classproperty:
        """Helper decorator to turn class methods into properties."""
        def __init__(self, func):
            self.func = func
        
        def __get__(self, instance, owner):
            return self.func(owner)

    class _cached_class_property:
        """Helper decorator to turn class methods into cached properties."""
        def __init__(self, func):
            self.func = func
            self.cache_attr = f'_cached_{func.__name__}'

        def __get__(self, instance, owner):
            if not hasattr(owner, self.cache_attr):
                setattr(owner, self.cache_attr, self.func(owner))
            return getattr(owner, self.cache_attr)
        
    