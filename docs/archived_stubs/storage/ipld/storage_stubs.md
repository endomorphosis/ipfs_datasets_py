# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/ipld/storage.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 02:17:30

## CID

```python
class CID:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IPLDSchema

```python
class IPLDSchema:
    """
    A schema for validating IPLD data structures.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IPLDStorage

```python
class IPLDStorage:
    """
    IPLD Storage provides a high-level interface for storing and retrieving
IPLD blocks using IPFS.

It handles the storage of data blocks, linking between blocks, and
serialization/deserialization of structured data.

Features:
- Store and retrieve content-addressed data blocks
- Link blocks together to form complex data structures
- Store structured data with optional schema validation
- Export and import data using CAR files for interchange
- Cache frequently accessed blocks for performance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name: str, schema_def: Dict[str, Any]):
    """
    Initialize a new IPLD schema.

Args:
    name (str): Schema name
    schema_def (Dict): Schema definition
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDSchema

## __init__

```python
def __init__(self, base_dir = None, ipfs_api = "/ip4/127.0.0.1/tcp/5001"):
    """
    Initialize a new IPLD Storage instance.

Args:
    base_dir (str, optional): Directory for temporary files. If None, a
        temporary directory will be created.
    ipfs_api (str, optional): IPFS API endpoint. Defaults to the local node.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## _register_default_schemas

```python
def _register_default_schemas(self):
    """
    Register default schemas for common data types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## connect

```python
def connect(self, ipfs_api = None):
    """
    Connect or reconnect to the IPFS daemon.

Args:
    ipfs_api (str, optional): IPFS API endpoint. If None, use the endpoint
        specified during initialization.

Returns:
    bool: True if connection successful, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## decode

```python
@staticmethod
def decode(cid_str):
```
* **Async:** False
* **Method:** True
* **Class:** CID

## encode

```python
@staticmethod
def encode(cid_obj):
```
* **Async:** False
* **Method:** True
* **Class:** CID

## export_to_car

```python
def export_to_car(self, cids: List[str], output_path: str) -> str:
    """
    Export IPLD blocks to a CAR file.

Args:
    cids (List[str]): CIDs of root blocks to include
    output_path (str): Path to write the CAR file

Returns:
    str: The root CID

Raises:
    ImportError: If ipld_car module is not available
    ValueError: If blocks cannot be found
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## export_to_car_stream

```python
def export_to_car_stream(self, cids: List[str], output_file, buffer_size: int = 1024 * 1024) -> str:
    """
    Export IPLD blocks to a CAR file using streaming to minimize memory usage.

Args:
    cids (List[str]): CIDs of root blocks to include
    output_file: File object opened in binary write mode
    buffer_size: Size of buffer for streaming (default 1MB)

Returns:
    str: The root CID

Raises:
    ImportError: If ipld_car module is not available
    ValueError: If blocks cannot be found
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## get

```python
def get(self, cid: str) -> bytes:
    """
    Retrieve data for a given CID.

Args:
    cid (str): CID of the block to retrieve

Returns:
    bytes: The data associated with the CID

Raises:
    ValueError: If the block cannot be found
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## get_batch

```python
def get_batch(self, cids: List[str]) -> List[Optional[bytes]]:
    """
    Retrieve multiple blocks by their CIDs in a single efficient operation.

Args:
    cids (List[str]): CIDs of the blocks to retrieve

Returns:
    List[Optional[bytes]]: The data associated with each CID, or None if not found

Note:
    This method is much more efficient than calling get() multiple times
    as it processes blocks in parallel and minimizes overhead.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## get_json

```python
def get_json(self, cid: str) -> Any:
    """
    Retrieve and parse a JSON-encoded IPLD block.

Args:
    cid (str): CID of the block to retrieve

Returns:
    Any: The parsed JSON data

Raises:
    ValueError: If the block cannot be found or is not valid JSON
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## get_json_batch

```python
def get_json_batch(self, cids: List[str]) -> List[Optional[Any]]:
    """
    Retrieve and parse multiple JSON-encoded IPLD blocks efficiently.

Args:
    cids (List[str]): CIDs of the blocks to retrieve

Returns:
    List[Optional[Any]]: The parsed JSON data for each CID, or None if not found or invalid
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## get_with_schema

```python
def get_with_schema(self, cid: str, expected_schema: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieve and validate data against a schema.

Args:
    cid (str): CID of the data to retrieve
    expected_schema (str, optional): Expected schema name. If provided,
        it will be checked against the stored schema name.

Returns:
    Dict: The retrieved data

Raises:
    ValueError: If the data does not match the expected schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## import_from_car

```python
def import_from_car(self, car_path: str) -> List[str]:
    """
    Import blocks from a CAR file.

Args:
    car_path (str): Path to the CAR file

Returns:
    List[str]: CIDs of the root blocks

Raises:
    ImportError: If ipld_car module is not available
    ValueError: If the CAR file cannot be read
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## import_from_car_stream

```python
def import_from_car_stream(self, car_file, buffer_size: int = 1024 * 1024) -> List[str]:
    """
    Import blocks from a CAR file using streaming to minimize memory usage.

Args:
    car_file: File object opened in binary read mode
    buffer_size: Size of buffer for streaming (default 1MB)

Returns:
    List[str]: CIDs of the root blocks

Raises:
    ImportError: If ipld_car module is not available
    ValueError: If the CAR file cannot be read
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## list_schemas

```python
def list_schemas(self) -> List[str]:
    """
    List all registered schemas.

Returns:
    List[str]: List of schema names
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## register_schema

```python
def register_schema(self, name: str, schema_def: Dict[str, Any]) -> None:
    """
    Register a new schema for validation.

Args:
    name (str): Schema name
    schema_def (Dict): Schema definition
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store

```python
def store(self, data: bytes, links: Optional[List[Dict]] = None) -> str:
    """
    Store data as an IPLD block and return its CID.

Args:
    data (bytes): The data to store
    links (List[Dict], optional): Links to other blocks. Each link should be
        a dict with at least a "cid" key and optionally a "name" key.

Returns:
    str: CID of the stored block
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_batch

```python
def store_batch(self, data_blocks: List[bytes], links_list: Optional[List[Optional[List[Dict]]]] = None) -> List[str]:
    """
    Store multiple data blocks efficiently in a single operation.

Args:
    data_blocks (List[bytes]): List of data blocks to store
    links_list (List[Optional[List[Dict]]], optional): List of links lists,
        one per data block. Each links list is a list of dicts with
        at least a "cid" key and optionally a "name" key.

Returns:
    List[str]: CIDs of the stored blocks

Note:
    This method is much more efficient than calling store() multiple times
    as it processes blocks in parallel and minimizes overhead.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_dataset

```python
def store_dataset(self, schema: Dict[str, Any], rows: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Store a dataset with schema and rows.

Args:
    schema (Dict): Dataset schema
    rows (List[Dict]): Dataset rows
    metadata (Dict, optional): Dataset metadata

Returns:
    str: CID of the stored dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_json

```python
def store_json(self, obj: Any) -> str:
    """
    Store a JSON-serializable object as an IPLD block.

Args:
    obj (Any): Any JSON-serializable object

Returns:
    str: CID of the stored block
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_json_batch

```python
def store_json_batch(self, objects: List[Any]) -> List[str]:
    """
    Store multiple JSON-serializable objects efficiently in a single operation.

Args:
    objects (List[Any]): List of JSON-serializable objects to store

Returns:
    List[str]: CIDs of the stored objects
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_kg_node

```python
def store_kg_node(self, node_id: str, node_type: str, properties: Optional[Dict[str, Any]] = None, relationships: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Store a knowledge graph node.

Args:
    node_id (str): Node identifier
    node_type (str): Node type
    properties (Dict, optional): Node properties
    relationships (List[Dict], optional): Node relationships

Returns:
    str: CID of the stored node
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_vector_index

```python
def store_vector_index(self, dimension: int, vectors: List[Dict[str, Any]], metric: str = "cosine") -> str:
    """
    Store a vector index.

Args:
    dimension (int): Vector dimension
    vectors (List[Dict]): Vector data
    metric (str, optional): Similarity metric

Returns:
    str: CID of the stored vector index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## store_with_schema

```python
def store_with_schema(self, data: Dict[str, Any], schema_name: str) -> str:
    """
    Store data with schema validation.

Args:
    data (Dict): Data to store
    schema_name (str): Name of the schema to validate against

Returns:
    str: CID of the stored data

Raises:
    ValueError: If the data does not match the schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage

## validate

```python
def validate(self, data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate data against this schema.

Args:
    data (Dict): Data to validate

Returns:
    Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDSchema

## validate_against_schema

```python
def validate_against_schema(self, data: Dict[str, Any], schema_name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate data against a registered schema.

Args:
    data (Dict): Data to validate
    schema_name (str): Name of the schema to validate against

Returns:
    Tuple[bool, Optional[str]]: (is_valid, error_message)

Raises:
    ValueError: If the schema is not registered
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDStorage
