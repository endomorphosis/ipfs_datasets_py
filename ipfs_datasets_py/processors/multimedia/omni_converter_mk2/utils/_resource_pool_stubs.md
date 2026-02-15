# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/_resource_pool.py'

Files last updated: 1751066158.503025

Stub file last updated: 2025-07-17 05:29:23

## ExternalProgramDict

```python
class ExternalProgramDict(ProcessSafeDict):
    """
    A dictionary to manage external programs with process-safe access.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ExternalService

```python
class ExternalService:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessSafeCounter

```python
class ProcessSafeCounter(object):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessSafeDict

```python
class ProcessSafeDict(object):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ResourcePool

```python
class ResourcePool:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __getitem__

```python
def __getitem__(self, key):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeDict

## __init__

```python
def __init__(self, manager: SyncManager, init_val: int = 0):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeCounter

## __init__

```python
def __init__(self, manager: SyncManager):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeDict

## __init__

```python
def __init__(self, manager: SyncManager):
```
* **Async:** False
* **Method:** True
* **Class:** ExternalProgramDict

## __init__

```python
def __init__(self, service_a, service_b, service_c) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** ExternalService

## __init__

```python
def __init__(self, configs: Configs):
```
* **Async:** False
* **Method:** True
* **Class:** ResourcePool

## add_resource

```python
def add_resource(self, name, resource):
    """
    Add a resource to the pool.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourcePool

## get

```python
def get(self, key):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeDict

## get_cluster_info

```python
def get_cluster_info(self, name: str):
    """
    Useful for things like Runpod, AWS, or other cloud providers.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalService

## get_resource

```python
def get_resource(self, name):
    """
    Retrieve a resource from the pool.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourcePool

## increment

```python
def increment(self):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeCounter

## remove

```python
def remove(self, key):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeDict

## remove_resource

```python
def remove_resource(self, name):
    """
    Remove a resource from the pool.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourcePool

## set

```python
def set(self, key, value):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeDict

## value

```python
def value(self):
```
* **Async:** False
* **Method:** True
* **Class:** ProcessSafeCounter
