# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/common/dependencies/tqdm.py'

Files last updated: 1748064619.6163821

Stub file last updated: 2025-07-17 05:30:47

## Tqdm

```python
class Tqdm:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## cleanup_progress_bar

```python
@staticmethod
def cleanup_progress_bar(pbar: tqdm.tqdm):
```
* **Async:** False
* **Method:** True
* **Class:** Tqdm

## get_progress_bar

```python
@staticmethod
def get_progress_bar(total: int, unit: str = "file", desc: str = None) -> tqdm.tqdm:
```
* **Async:** False
* **Method:** True
* **Class:** Tqdm

## progress_bar

```python
@contextmanager
@staticmethod
def progress_bar(total: int, unit: str = "file", desc: str = None) -> Generator[None, None, tqdm.tqdm]:
    """
    Context manager for a progress bar.

Args:
    total: Total number of iterations.
    unit: Unit of measurement for the progress bar.
    desc: Description for the progress bar.

Yields:
    A tqdm progress bar instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Tqdm

## set_progress_bar_description

```python
@staticmethod
def set_progress_bar_description(pbar: tqdm.tqdm, description: str = None):
```
* **Async:** False
* **Method:** True
* **Class:** Tqdm

## update_progress_bar

```python
@staticmethod
def update_progress_bar(pbar: tqdm.tqdm, unit: int = 1):
```
* **Async:** False
* **Method:** True
* **Class:** Tqdm
