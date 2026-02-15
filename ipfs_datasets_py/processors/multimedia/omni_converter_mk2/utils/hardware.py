from functools import cache
import os
import subprocess
import platform

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


def _get_info_from_nvidia_smi(command: list[str]) -> dict[str, Any]:
    """Run nvidia-smi command and return parsed output."""
    # We purposefully call nvidia-smi as a subprocess,
    # Otherwise we'd have to load-in a specific dependency like pynvml or torch.
    # TODO This only works with NVIDIA GPUs. Expand this to other vendors.
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return {'error': f'nvidia-smi command failed: {str(e)}\ncmd: {command}\nresult: {result}'}
    except FileNotFoundError:
        return {'error': 'nvidia-smi not found. Please install NVIDIA System Management Interface program.'}
    except Exception as e:
        return {'error': f'Unexpected Error occurred: {str(e)}'}


class Hardware:
    """
    Hardware is a utility class that provides static methods to monitor system and process hardware resource usage.
    This includes:
    - CPU usage
    - Virtual memory usage
    - Memory information (RSS and VMS)
    - Disk usage
    - Number of open files
    - Shared memory usage
    - Number of CPU cores
    - VRAM information (if CUDA is available)

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

    @staticmethod
    def get_cpu_usage_in_percent() -> float:
        """Returns the CPU usage percentage of the current process over a 0.1 second interval."""
        return psutil.cpu_percent(interval=0.1)

    @staticmethod
    def get_virtual_memory_in_percent() -> float:
        """Returns the percentage of virtual memory currently in use."""
        return psutil.virtual_memory().percent

    @staticmethod
    def get_memory_info() -> NamedTuple:
        """Returns detailed memory information of the current process."""
        return psutil.Process(_PID).memory_info()

    @staticmethod
    def get_memory_rss_usage_in_mb() -> float:
        """Returns the Resident Set Size (RSS) memory usage of the current process in megabytes."""
        return psutil.Process(_PID).memory_info().rss / _BYTE_MAPPING["MiB"]

    @staticmethod
    def get_memory_rss_usage_in_gb() -> float:
        """Returns the Resident Set Size (RSS) memory usage of the current process in gigabytes."""
        return psutil.Process(_PID).memory_info().rss / _BYTE_MAPPING["GiB"]

    @staticmethod
    def get_memory_vms_usage_in_mb() -> float:
        """Returns the Virtual Memory Size (VMS) usage of the current process in megabytes."""
        return psutil.Process(_PID).memory_info().vms / _BYTE_MAPPING["MiB"]

    @cache
    @staticmethod
    def get_total_memory_in_mb() -> float:
        """Returns the total physical memory of the system in megabytes."""
        return psutil.virtual_memory().total / _BYTE_MAPPING["MiB"]

    @cache
    @staticmethod
    def get_total_memory_in_gb() -> float:
        """Returns the total physical memory of the system in gigabytes."""
        return psutil.virtual_memory().total / _BYTE_MAPPING["GiB"]

    @staticmethod
    def get_disk_usage_in_percent() -> float:
        """Returns the percentage of disk usage for the root directory."""
        return psutil.disk_usage('/').percent

    @staticmethod
    def get_num_open_files() -> int:
        """Returns the number of open file descriptors for the current process."""
        return len(psutil.Process(_PID).open_files())

    @staticmethod
    def get_shared_memory_usage_in_mb() -> float:
        """Returns the shared memory usage of the current process in megabytes."""
        mem_info = psutil.Process(_PID).memory_info()
        return getattr(mem_info, 'shared', 0) / _BYTE_MAPPING["MiB"]

    @cache
    @staticmethod
    def get_num_cpu_cores(include_logical: bool = False) -> int:
        """Get the number of logical CPUs available."""
        return psutil.cpu_count(logical=include_logical)
    
    @staticmethod
    def get_cpu_info() -> dict[str, Any]:
        """Get CPU information including model, frequency, and core count."""
        cpu_info = {
            'model':  platform.processor(),
            'frequency': psutil.cpu_freq().current,
            'cores': psutil.cpu_count(logical=False),
            'logical_cores': psutil.cpu_count(logical=True)
        }
        return cpu_info

    @staticmethod
    def get_vram_info() -> dict[str, Any]:
        """Get CUDA GPU memory information if available."""
        cmd = [
            'nvidia-smi', 
            '--query-gpu=index,memory.total,memory.used,memory.free', 
            '--format=csv,noheader,nounits'
        ]
        result = _get_info_from_nvidia_smi(cmd)
        if 'error' in result:
            return result
        else:
            cuda_memory_info = {}

            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = [part.strip() for part in line.split(',')]
                    if len(parts) == 4:
                        gpu_index, total_mb, used_mb, free_mb = parts
                        total_mb = float(total_mb)
                        used_mb = float(used_mb)
                        
                        cuda_memory_info[f'gpu_{gpu_index}'] = {
                            'total_mb': total_mb,
                            'used_mb': used_mb,
                            'free_mb': float(free_mb),
                            'used_percent': (used_mb / total_mb) * 100 if total_mb > 0 else 0
                        }
            return cuda_memory_info


    @staticmethod
    def get_gpu_info() -> dict[str, Any]:
        """Get GPU information including model, total physical VRAM, etc."""
        cmd = [
            'nvidia-smi',
            '--query-gpu=index,name,memory.total,driver_version,temperature.gpu',
            '--format=csv,noheader,nounits'
        ]
        result = _get_info_from_nvidia_smi(cmd)
        if 'error' in result:
            return result
        else:
            gpu_info = {}
            
            for line in result.strip().split('\n'):
                if line:
                    parts = [part.strip() for part in line.split(',')]
                    if len(parts) == 5:
                        gpu_index, name, total_memory_mb, driver_version, temperature = parts
                        gpu_info[f'gpu_{gpu_index}'] = {
                            'name': name,
                            'total_memory_mb': float(total_memory_mb),
                            'total_memory_gb': float(total_memory_mb) / _BYTE_MAPPING["MiB"],
                            'driver_version': driver_version,
                            'temperature_celsius': float(temperature) if temperature != '[Not Supported]' else None
                        }
            return gpu_info
