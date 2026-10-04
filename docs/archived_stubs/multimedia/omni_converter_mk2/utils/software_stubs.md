# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/software.py'

Files last updated: 1751233307.6905246

Stub file last updated: 2025-07-17 05:29:23

## Software

```python
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
* **Class:** Software

## _classproperty

```python
class _classproperty:
    """
    Helper decorator to turn class methods into properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** Software
