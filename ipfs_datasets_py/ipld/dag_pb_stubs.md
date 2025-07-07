# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/ipld/dag_pb.py'

Files last updated: 1748635923.4313796

Stub file last updated: 2025-07-07 02:17:30

## CID

```python
class CID:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PBLink

```python
class PBLink:
    """
    A link in a DAG-PB node.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PBNode

```python
class PBNode:
    """
    A node in a DAG-PB graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name = None, cid = None, tsize = None):
```
* **Async:** False
* **Method:** True
* **Class:** PBLink

## __init__

```python
def __init__(self, data = None, links = None):
```
* **Async:** False
* **Method:** True
* **Class:** PBNode

## create_dag_node

```python
def create_dag_node(data: bytes, links: List[Dict]) -> bytes:
    """
    Create a DAG-PB node with the given data and links.

Args:
    data (bytes): The data to store in the node
    links (List[Dict]): Links to other nodes, each a dict with at least
        a "cid" key and optionally "name" and "tsize" keys.

Returns:
    bytes: The encoded DAG-PB node
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decode

```python
@staticmethod
def decode(cid_str):
```
* **Async:** False
* **Method:** True
* **Class:** CID

## decode

```python
def decode(buf):
    """
    Decode a protobuf message to a PBNode.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decode_varint

```python
def decode_varint(buf, pos):
    """
    Decode a protobuf varint to an integer.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## encode

```python
@staticmethod
def encode(cid_obj):
```
* **Async:** False
* **Method:** True
* **Class:** CID

## encode

```python
def encode(node):
    """
    Encode a PBNode as a protobuf message.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## encode_bytes

```python
def encode_bytes(value):
    """
    Encode bytes as a protobuf bytes field.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## encode_field

```python
def encode_field(field_num, wire_type, value):
    """
    Encode a protobuf field.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## encode_varint

```python
def encode_varint(value):
    """
    Encode an integer as a protobuf varint.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## from_dict

```python
@classmethod
def from_dict(cls, obj):
    """
    Create a PBLink from a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PBLink

## from_dict

```python
@classmethod
def from_dict(cls, obj):
    """
    Create a PBNode from a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PBNode

## parse_dag_node

```python
def parse_dag_node(node_data: bytes) -> Tuple[bytes, List[Dict]]:
    """
    Parse a DAG-PB node into data and links.

Args:
    node_data (bytes): The encoded DAG-PB node

Returns:
    Tuple[bytes, List[Dict]]: The data and links from the node
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self):
    """
    Convert to a dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PBLink

## to_dict

```python
def to_dict(self):
    """
    Convert to a dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PBNode
