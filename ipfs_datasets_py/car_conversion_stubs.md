# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/car_conversion.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:11:01

## DataInterchangeUtils

```python
class DataInterchangeUtils:
    """
    Utilities for data interchange between different formats.

This class provides methods for converting between:
- Arrow tables and CAR files
- Parquet files and CAR files
- HuggingFace datasets and CAR files
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockTable

```python
class MockTable:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockTable

```python
class MockTable:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage = None):
    """
    Initialize a new DataInterchangeUtils instance.

Args:
    storage (IPLDStorage, optional): IPLD storage backend. If None,
        a new IPLDStorage instance will be created.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockTable

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockTable

## batch_generator

```python
def batch_generator():
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## car_to_huggingface

```python
def car_to_huggingface(self, car_path):
    """
    Import a HuggingFace dataset from a CAR file.

Args:
    car_path (str): Path to the CAR file

Returns:
    Dataset: The imported dataset

Raises:
    ImportError: If dependencies are not available
    ValueError: If the CAR file does not contain a valid dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## car_to_parquet

```python
def car_to_parquet(self, car_path, parquet_path):
    """
    Convert a CAR file to a Parquet file.

Args:
    car_path (str): Path to the input CAR file
    parquet_path (str): Path for the output Parquet file

Returns:
    str: Path to the created Parquet file

Raises:
    ImportError: If dependencies are not available
    ValueError: If the CAR file does not contain a valid table
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## export_table_to_car

```python
def export_table_to_car(self, table, output_path, hash_columns = None):
    """
    Export an Arrow table to a CAR file.

Args:
    table: pyarrow.Table to export
    output_path (str): Path for the output CAR file
    hash_columns (List[str], optional): Columns to use for content addressing

Returns:
    str: CID of the root block in the CAR file

Raises:
    ImportError: If dependencies are not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## get_c_data_interface

```python
def get_c_data_interface(self, table):
    """
    Get the C Data Interface representation of an Arrow table.

This can be used for shared memory communication between processes.

Args:
    table: pyarrow.Table to export

Returns:
    dict: C Data Interface representation

Raises:
    ImportError: If PyArrow is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## huggingface_to_car

```python
def huggingface_to_car(self, dataset, output_path, split = "train", hash_columns = None):
    """
    Export a HuggingFace dataset to a CAR file.

Args:
    dataset: HuggingFace dataset to export
    output_path (str): Path for the output CAR file
    split (str, optional): Split to export. Only used for DatasetDict.
    hash_columns (List[str], optional): Columns to use for content addressing

Returns:
    str: CID of the root block in the CAR file

Raises:
    ImportError: If dependencies are not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## import_table_from_car

```python
def import_table_from_car(self, car_path):
    """
    Import an Arrow table from a CAR file.

Args:
    car_path (str): Path to the CAR file

Returns:
    pyarrow.Table: The imported table

Raises:
    ImportError: If dependencies are not available
    ValueError: If the CAR file does not contain a valid table
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## parquet_to_car

```python
def parquet_to_car(self, parquet_path, car_path, hash_columns = None):
    """
    Convert a Parquet file to a CAR file.

Args:
    parquet_path (str): Path to the input Parquet file
    car_path (str): Path for the output CAR file
    hash_columns (List[str], optional): Columns to use for content addressing

Returns:
    str: CID of the root block in the CAR file

Raises:
    ImportError: If dependencies are not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## stream_car_to_parquet

```python
def stream_car_to_parquet(self, car_path, parquet_path, batch_size = 10000):
    """
    Stream a CAR file to a Parquet file in batches.

This is memory-efficient for large files.

Args:
    car_path (str): Path to the input CAR file
    parquet_path (str): Path for the output Parquet file
    batch_size (int, optional): Number of rows per batch

Returns:
    str: Path to the created Parquet file

Raises:
    ImportError: If dependencies are not available
    ValueError: If the CAR file does not contain a valid streaming dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## stream_parquet_to_car

```python
def stream_parquet_to_car(self, parquet_path, car_path, batch_size = 10000):
    """
    Stream a Parquet file to a CAR file in batches.

This is memory-efficient for large files.

Args:
    parquet_path (str): Path to the input Parquet file
    car_path (str): Path for the output CAR file
    batch_size (int, optional): Number of rows per batch

Returns:
    str: CID of the root block in the CAR file

Raises:
    ImportError: If dependencies are not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## table_from_c_data_interface

```python
def table_from_c_data_interface(self, c_data):
    """
    Reconstruct an Arrow table from a C Data Interface representation.

Args:
    c_data (dict): C Data Interface representation

Returns:
    pyarrow.Table: The reconstructed table

Raises:
    ImportError: If PyArrow is not available
    ValueError: If the C Data Interface is invalid
    """
```
* **Async:** False
* **Method:** True
* **Class:** DataInterchangeUtils

## to_pydict

```python
def to_pydict(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockTable

## to_pydict

```python
def to_pydict(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockTable
