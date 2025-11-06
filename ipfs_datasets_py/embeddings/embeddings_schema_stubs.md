# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/embeddings/schema.py'

## BaseComponent

```python
class BaseComponent(BaseModel if BaseModel != object else object):
    """
    Base component object to capture class names.
    """
```
## ChunkingStrategy

```python
class ChunkingStrategy(Enum):
    """
    Supported chunking strategies.
    """
```
## DocumentChunk

```python
@dataclass
class DocumentChunk:
    """
    Represents a chunk of a document for embedding processing.
    """
```
## EmbeddingConfig

```python
@dataclass
class EmbeddingConfig:
    """
    Configuration for embedding operations.
    """
```
## EmbeddingResult

```python
@dataclass
class EmbeddingResult:
    """
    Represents the result of an embedding operation.
    """
```
## SearchResult

```python
@dataclass
class SearchResult:
    """
    Represents a search result from vector similarity search.
    """
```
## VectorStoreConfig

```python
@dataclass
class VectorStoreConfig:
    """
    Configuration for vector store operations.
    """
```
## VectorStoreType

```python
class VectorStoreType(Enum):
    """
    Supported vector store types.
    """
```
## __init_subclass__

```python
def __init_subclass__(cls, **kwargs):
```
* **Async:** False
* **Method:** True
* **Class:** BaseComponent

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** DocumentChunk

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingResult

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** SearchResult

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** VectorStoreConfig

## class_name

```python
@classmethod
def class_name(cls) -> str:
    """
    Get the class name, used as a unique ID in serialization.

This provides a key that makes serialization robust against actual class
name changes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseComponent

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "BaseComponent":
    """
    Create instance from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseComponent

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "DocumentChunk":
    """
    Create instance from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DocumentChunk

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "EmbeddingResult":
    """
    Create instance from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingResult

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
    """
    Create instance from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SearchResult

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "EmbeddingConfig":
    """
    Create instance from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingConfig

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "VectorStoreConfig":
    """
    Create instance from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorStoreConfig

## from_json

```python
@classmethod
def from_json(cls, json_str: str) -> "BaseComponent":
    """
    Create instance from JSON string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseComponent

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseComponent

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DocumentChunk

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingResult

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SearchResult

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingConfig

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorStoreConfig

## to_json

```python
def to_json(self, **kwargs: Any) -> str:
    """
    Convert to JSON string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseComponent

## truncate_text

```python
def truncate_text(text: str, length: int = 350) -> str:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## truncate_text

```python
def truncate_text(text: str, length: int = 350) -> str:
```
* **Async:** False
* **Method:** False
* **Class:** N/A
