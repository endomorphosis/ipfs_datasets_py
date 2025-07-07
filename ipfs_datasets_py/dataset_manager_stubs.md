# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/dataset_manager.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:11:01

## DatasetManager

```python
class DatasetManager:
    """
    Simple dataset manager for MCP tools.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ManagedDataset

```python
class ManagedDataset:
    """
    A managed dataset wrapper.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the dataset manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetManager

## __init__

```python
def __init__(self, dataset: Dataset, dataset_id: str):
    """
    Initialize managed dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ManagedDataset

## get_dataset

```python
def get_dataset(self, dataset_id: str) -> "ManagedDataset":
    """
    Get a dataset by ID.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetManager

## save

```python
def save(self, destination: str, format: Optional[str] = None, **options) -> Dict[str, Any]:
    """
    Save the dataset synchronously.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ManagedDataset

## save_async

```python
async def save_async(self, destination: str, format: Optional[str] = None, **options) -> Dict[str, Any]:
    """
    Save the dataset asynchronously.
    """
```
* **Async:** True
* **Method:** True
* **Class:** ManagedDataset

## save_dataset

```python
def save_dataset(self, dataset_id: str, dataset: Dataset) -> None:
    """
    Save a dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetManager
