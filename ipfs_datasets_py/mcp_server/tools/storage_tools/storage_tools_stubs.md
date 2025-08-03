# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/storage_tools/storage_tools.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## Collection

```python
@dataclass
class Collection:
    """
    Represents a collection of stored items.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CompressionType

```python
class CompressionType(Enum):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockStorageManager

```python
class MockStorageManager:
    """
    Mock storage manager for testing and development.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## StorageItem

```python
@dataclass
class StorageItem:
    """
    Represents an item stored in the storage system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## StorageType

```python
class StorageType(Enum):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## _create_collection

```python
def _create_collection(self, name: str, description: str) -> Collection:
    """
    Create a new collection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## _create_default_collection

```python
def _create_default_collection(self):
    """
    Create default collection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## _generate_item_id

```python
def _generate_item_id(self, content: Union[str, bytes]) -> str:
    """
    Generate unique ID for content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## create_collection

```python
def create_collection(self, name: str, description: str = "", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a new collection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## delete_collection

```python
def delete_collection(self, name: str, delete_items: bool = False) -> bool:
    """
    Delete a collection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## delete_item

```python
def delete_item(self, item_id: str) -> bool:
    """
    Delete an item.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## get_collection

```python
def get_collection(self, name: str) -> Optional[Dict[str, Any]]:
    """
    Get collection information.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## get_storage_stats

```python
def get_storage_stats(self) -> Dict[str, Any]:
    """
    Get comprehensive storage statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## list_collections

```python
def list_collections(self) -> List[Dict[str, Any]]:
    """
    List all collections.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## list_items

```python
def list_items(self, collection_name: Optional[str] = None, storage_type: Optional[StorageType] = None, tags: Optional[List[str]] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    List items with optional filtering.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## manage_collections

```python
async def manage_collections(action: str, collection_name: Optional[str] = None, description: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, delete_items: bool = False) -> Dict[str, Any]:
    """
    Manage storage collections (create, read, update, delete).

Args:
    action: Action to perform (create, get, list, delete, update)
    collection_name: Name of the collection to manage
    description: Description for new collections
    metadata: Metadata for collections
    delete_items: Whether to delete items when deleting collection

Returns:
    Dict containing collection management results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## query_storage

```python
async def query_storage(collection: Optional[str] = None, storage_type: Optional[str] = None, tags: Optional[List[str]] = None, size_range: Optional[Tuple[int, int]] = None, date_range: Optional[Tuple[str, str]] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """
    Query and filter stored items based on various criteria.

Args:
    collection: Filter by collection name
    storage_type: Filter by storage type
    tags: Filter by tags (items must have at least one tag)
    size_range: Filter by size range in bytes (min, max)
    date_range: Filter by creation date range (ISO format)
    limit: Maximum number of results to return
    offset: Number of results to skip

Returns:
    Dict containing query results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## retrieve_data

```python
async def retrieve_data(item_ids: List[str], include_content: bool = False, format_type: str = "json") -> Dict[str, Any]:
    """
    Retrieve stored data by item IDs.

Args:
    item_ids: List of item IDs to retrieve
    include_content: Whether to include actual content in response
    format_type: Format for returned data

Returns:
    Dict containing retrieved data
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## retrieve_item

```python
def retrieve_item(self, item_id: str, include_content: bool = False) -> Optional[Dict[str, Any]]:
    """
    Retrieve an item by ID.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager

## store_data

```python
async def store_data(data: Union[str, bytes, Dict[str, Any], List[Any]], storage_type: str = "memory", compression: str = "none", collection: str = "default", metadata: Optional[Dict[str, Any]] = None, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Store data in the storage system with specified configuration.

Args:
    data: Data to store (text, bytes, JSON object, or list)
    storage_type: Type of storage backend to use
    compression: Compression algorithm to apply
    collection: Collection to store the data in
    metadata: Additional metadata to associate with the data
    tags: Tags for categorizing and filtering the data

Returns:
    Dict containing storage operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## store_item

```python
def store_item(self, content: Union[str, bytes, Dict[str, Any]], storage_type: StorageType = StorageType.MEMORY, compression: CompressionType = CompressionType.NONE, metadata: Optional[Dict[str, Any]] = None, tags: Optional[List[str]] = None, collection_name: str = "default") -> StorageItem:
    """
    Store an item in the storage system.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockStorageManager
