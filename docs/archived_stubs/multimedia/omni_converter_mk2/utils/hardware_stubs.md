# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/hardware.py'

Files last updated: 1751075044.5855565

Stub file last updated: 2025-07-17 05:29:23

## Hardware

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __get__

```python
def __get__(self, instance, owner):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## __get__

```python
def __get__(self, instance, owner):
```
* **Async:** False
* **Method:** True
* **Class:** _cached_class_property

## __init__

```python
def __init__(self, func):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## __init__

```python
def __init__(self, func):
```
* **Async:** False
* **Method:** True
* **Class:** _cached_class_property

## _cached_class_property

```python
class _cached_class_property:
    """
    Helper decorator to turn class methods into cached properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** Hardware

## _classproperty

```python
class _classproperty:
    """
    Helper decorator to turn class methods into properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** Hardware

## _get_info_from_nvidia_smi

```python
def _get_info_from_nvidia_smi(command: list[str]) -> dict[str, Any]:
    """
    Run nvidia-smi command and return parsed output.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_cpu_info

```python
@staticmethod
def get_cpu_info() -> dict[str, Any]:
    """
    Get CPU information including model, frequency, and core count.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_cpu_usage_in_percent

```python
@staticmethod
def get_cpu_usage_in_percent() -> float:
    """
    Returns the CPU usage percentage of the current process over a 0.1 second interval.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_disk_usage_in_percent

```python
@staticmethod
def get_disk_usage_in_percent() -> float:
    """
    Returns the percentage of disk usage for the root directory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_gpu_info

```python
@staticmethod
def get_gpu_info() -> dict[str, Any]:
    """
    Get GPU information including model, total physical VRAM, etc.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_memory_info

```python
@staticmethod
def get_memory_info() -> NamedTuple:
    """
    Returns detailed memory information of the current process.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_memory_rss_usage_in_gb

```python
@staticmethod
def get_memory_rss_usage_in_gb() -> float:
    """
    Returns the Resident Set Size (RSS) memory usage of the current process in gigabytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_memory_rss_usage_in_mb

```python
@staticmethod
def get_memory_rss_usage_in_mb() -> float:
    """
    Returns the Resident Set Size (RSS) memory usage of the current process in megabytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_memory_vms_usage_in_mb

```python
@staticmethod
def get_memory_vms_usage_in_mb() -> float:
    """
    Returns the Virtual Memory Size (VMS) usage of the current process in megabytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_num_cpu_cores

```python
@cache
@staticmethod
def get_num_cpu_cores(include_logical: bool = False) -> int:
    """
    Get the number of logical CPUs available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_num_open_files

```python
@staticmethod
def get_num_open_files() -> int:
    """
    Returns the number of open file descriptors for the current process.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_shared_memory_usage_in_mb

```python
@staticmethod
def get_shared_memory_usage_in_mb() -> float:
    """
    Returns the shared memory usage of the current process in megabytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_total_memory_in_gb

```python
@cache
@staticmethod
def get_total_memory_in_gb() -> float:
    """
    Returns the total physical memory of the system in gigabytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_total_memory_in_mb

```python
@cache
@staticmethod
def get_total_memory_in_mb() -> float:
    """
    Returns the total physical memory of the system in megabytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_virtual_memory_in_percent

```python
@staticmethod
def get_virtual_memory_in_percent() -> float:
    """
    Returns the percentage of virtual memory currently in use.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware

## get_vram_info

```python
@staticmethod
def get_vram_info() -> dict[str, Any]:
    """
    Get CUDA GPU memory information if available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Hardware
