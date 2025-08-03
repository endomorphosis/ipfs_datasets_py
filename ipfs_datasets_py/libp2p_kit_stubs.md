# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/libp2p_kit.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 02:11:02

## DistributedDatasetManager

```python
class DistributedDatasetManager:
    """
    Stub implementation of DistributedDatasetManager.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LibP2PNotAvailableError

```python
class LibP2PNotAvailableError(Exception):
    """
    Raised when libp2p dependencies are not available.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockDataset

```python
class MockDataset:
    """
    Mock dataset for testing.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockShardManager

```python
class MockShardManager:
    """
    Mock shard manager for testing.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NodeRole

```python
class NodeRole(Enum):
    """
    Role of the node in the distributed network.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, *args, **kwargs):
    """
    Initialize stub manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedDatasetManager

## __init__

```python
def __init__(self, dataset_id: str):
    """
    Initialize mock dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockDataset

## create_distributed_dataset

```python
def create_distributed_dataset(self, *args, **kwargs):
    """
    Stub method.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedDatasetManager

## get_dataset

```python
def get_dataset(self, dataset_id: str):
    """
    Return a mock dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockShardManager

## save_async

```python
async def save_async(self, *args, **kwargs):
    """
    Mock save method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockDataset
