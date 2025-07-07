# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/unixfs_integration.py'

Files last updated: 1751435742.9580474

Stub file last updated: 2025-07-07 02:11:02

## ChunkerBase

```python
class ChunkerBase:
    """
    Base class for chunking strategies.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FixedSizeChunker

```python
class FixedSizeChunker(ChunkerBase):
    """
    Chunker that divides data into fixed-size chunks.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RabinChunker

```python
class RabinChunker(ChunkerBase):
    """
    Chunker using Rabin fingerprinting for content-defined chunking.

Note: This requires the pyrabin package, which is not included by default.
If the package is not available, this will fall back to fixed-size chunking.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UnixFSHandler

```python
class UnixFSHandler:
    """
    Handles files and directories in IPFS using UnixFS.

This class provides methods for storing and retrieving files and
directories in IPFS, using various chunking strategies for efficient
handling of large files.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, chunk_size = 262144):
    """
    Initialize a fixed-size chunker.

Args:
    chunk_size (int): Size of each chunk in bytes, defaults to
        256 KB (262144 bytes).
    """
```
* **Async:** False
* **Method:** True
* **Class:** FixedSizeChunker

## __init__

```python
def __init__(self, min_size = 256 * 1024, avg_size = 1024 * 1024, max_size = 4 * 1024 * 1024):
    """
    Initialize a Rabin chunker.

Args:
    min_size (int): Minimum chunk size in bytes
    avg_size (int): Average chunk size in bytes
    max_size (int): Maximum chunk size in bytes
    """
```
* **Async:** False
* **Method:** True
* **Class:** RabinChunker

## __init__

```python
def __init__(self, ipfs_api = "/ip4/127.0.0.1/tcp/5001"):
    """
    Initialize a new UnixFSHandler.

Args:
    ipfs_api (str): IPFS API endpoint, defaults to the local node.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnixFSHandler

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
* **Class:** UnixFSHandler

## cut

```python
def cut(self, context, buffer, end = False) -> List[int]:
    """
    Cut a buffer into chunks.

Args:
    context: Opaque context maintained between calls
    buffer (bytes): Buffer to chunk
    end (bool): Whether this is the last buffer

Returns:
    List[int]: List of chunk lengths
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkerBase

## cut

```python
def cut(self, context, buffer, end = False) -> List[int]:
    """
    Cut a buffer into fixed-size chunks.

Args:
    context: Ignored for fixed-size chunker
    buffer (bytes): Buffer to chunk
    end (bool): Whether this is the last buffer

Returns:
    List[int]: List of chunk lengths
    """
```
* **Async:** False
* **Method:** True
* **Class:** FixedSizeChunker

## cut

```python
def cut(self, context, buffer, end = False) -> List[int]:
    """
    Cut a buffer using Rabin fingerprinting.

Args:
    context: Opaque context maintained between calls
    buffer (bytes): Buffer to chunk
    end (bool): Whether this is the last buffer

Returns:
    List[int]: List of chunk lengths
    """
```
* **Async:** False
* **Method:** True
* **Class:** RabinChunker

## get_directory

```python
def get_directory(self, cid, output_dir = None):
    """
    Get a directory from IPFS.

Args:
    cid (str): CID of the directory to get
    output_dir (str, optional): Directory to write the contents to.
        If None, the directory listing is returned.

Returns:
    Union[List[str], Dict[str, bytes]]: Directory listing or contents

Raises:
    ImportError: If IPFS client is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnixFSHandler

## get_file

```python
def get_file(self, cid, output_path = None):
    """
    Get a file from IPFS.

Args:
    cid (str): CID of the file to get
    output_path (str, optional): Path to write the file to. If None,
        the file content is returned directly.

Returns:
    Union[bytes, str]: The file content or the output path

Raises:
    ImportError: If IPFS client is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnixFSHandler

## write_directory

```python
def write_directory(self, dir_path, recursive = True):
    """
    Write a directory to IPFS using UnixFS format.

Args:
    dir_path (str): Path to the directory to write
    recursive (bool): Whether to include subdirectories

Returns:
    str: CID of the directory

Raises:
    ImportError: If IPFS client is not available
    NotADirectoryError: If the path is not a directory
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnixFSHandler

## write_file

```python
def write_file(self, file_path, chunker = None):
    """
    Write a file to IPFS using UnixFS format.

Args:
    file_path (str): Path to the file to write
    chunker (ChunkerBase, optional): Chunking strategy to use

Returns:
    str: CID of the file

Raises:
    ImportError: If IPFS client is not available
    FileNotFoundError: If the file does not exist
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnixFSHandler

## write_to_car

```python
def write_to_car(self, path, car_path, chunker = None):
    """
    Write a file or directory to a CAR file.

Args:
    path (str): Path to the file or directory to write
    car_path (str): Path for the output CAR file
    chunker (ChunkerBase, optional): Chunking strategy to use for files

Returns:
    str: CID of the root object in the CAR file

Raises:
    ImportError: If dependencies are not available
    FileNotFoundError: If the path does not exist
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnixFSHandler
