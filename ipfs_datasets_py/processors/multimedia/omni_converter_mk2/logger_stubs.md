# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/logger.py'

Files last updated: 1750747066.2957942

Stub file last updated: 2025-07-17 05:36:42

## _Logger

```python
class _Logger:
    """
    Singleton class to manage logger instances.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources = None, configs = None):
```
* **Async:** False
* **Method:** True
* **Class:** _Logger

## __new__

```python
def __new__(cls):
```
* **Async:** False
* **Method:** True
* **Class:** _Logger

## get_logger

```python
def get_logger(name: str, log_file_name: str = "app.log", level: int = logging.INFO, max_size: int = 5 * 1024 * 1024, backup_count: int = 3) -> logging.Logger:
    """
    Sets up a logger with both file and console handlers.

Args:
    name: Name of the logger.
    log_file_name: Name of the log file. Defaults to 'app.log'.
    level: Logging level. Defaults to logging.INFO.
    max_size: Maximum size of the log file before it rotates. Defaults to 5MB.
    backup_count: Number of backup files to keep. Defaults to 3.

Returns:
    Configured logger.

Example:
    # Usage
    logger = get_logger(__name__)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## logger

```python
@cached_property
def logger(self):
```
* **Async:** False
* **Method:** True
* **Class:** _Logger
