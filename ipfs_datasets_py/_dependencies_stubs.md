# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/_dependencies.py'

Files last updated: 1751437511.5321875

Stub file last updated: 2025-07-07 02:11:01

## _Dependencies

```python
class _Dependencies:
    """
    Class to enable the lazy-loading of dependencies and third-party libraries.
This optimizes performance, allows for dynamic error checking, and reduce initial load time.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __contains__

```python
def __contains__(self, item: str) -> bool:
    """
    Check if a specific module is loaded.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## __getitem__

```python
def __getitem__(self, item: str) -> _ModuleType | None:
    """
    Get a specific module by name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## __init__

```python
def __init__(self) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## __iter__

```python
def __iter__(self):
    """
    Iterate over the loaded modules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## __repr__

```python
def __repr__(self) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## __str__

```python
def __str__(self) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## _load_module

```python
def _load_module(self, module_name: str) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## _test_for_non_critical_dependencies

```python
def _test_for_non_critical_dependencies() -> None:
    """
    Test for non-critical dependencies in a separate thread to ensure the application starts promptly and to avoid dead.

This function creates a temporary instance of the `_Dependencies` class to load all required
modules without causing deadlocks. Once all modules have been checked, the temporary instance is
cleared from memory to optimize resource usage.

Key Steps:
1. Creates a separate `_Dependencies` instance to handle module loading.
2. Ensures all modules are loaded using `load_all_modules`.
3. Clears the cache and deletes the temporary instance to free up memory.
4. Triggers garbage collection to reclaim unused memory.

Note:
- This function is designed to handle non-critical dependencies, allowing the application
    to start without waiting for all dependencies to be fully loaded.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## anthropic

```python
@property
def anthropic(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## bs4

```python
@property
def bs4(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## chardet

```python
@property
def chardet(self) -> _ModuleType | None:
    """
    Load the chardet module.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## check_critical_dependencies

```python
def check_critical_dependencies(self) -> None:
    """
    Check if all critical dependencies are available.

Raises:
    ImportError: If any critical dependency is not available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## clear_cache

```python
def clear_cache(self) -> None:
    """
    Clear the cache of loaded modules.

Used to save memory when large dependencies are no longer needed.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## clear_module

```python
def clear_module(self, module_name: str) -> None:
    """
    Clear a specific module from the cache.

Args:
    module_name (str): The name of the module to clear.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## cv2

```python
@property
def cv2(self) -> _ModuleType | None:
    """
    Load the cv2 module.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## duckdb

```python
@property
def duckdb(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## is_available

```python
def is_available(self, module_name: str) -> bool:
    """
    Check if a specific module is available.

Args:
    module_name (str): The name of the module to check.

Returns:
    bool: True if the module is available, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## items

```python
def items(self) -> list[tuple[str, _ModuleType | None]]:
    """
    Get a list of all dependencies as (name, module) tuples.

Returns:
    A list of tuples containing dependency names and their corresponding modules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## keys

```python
def keys(self) -> list[str]:
    """
    Get a list of all dependency names.

Returns:
    A list of dependency names.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## load_all_modules

```python
def load_all_modules(self) -> None:
    """
    Load all modules and cache them.

This is called at the start of the program to check which dependencies are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## multiformats

```python
@property
def multiformats(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## numpy

```python
@property
def numpy(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## openai

```python
@property
def openai(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## openpyxl

```python
@property
def openpyxl(self) -> _ModuleType | None:
    """
    Load the openpyxl module.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## pandas

```python
@property
def pandas(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## pil

```python
@property
def pil(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## playsound

```python
@property
def playsound(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## pydantic

```python
@property
def pydantic(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## pydub

```python
@property
def pydub(self) -> _ModuleType | None:
    """
    Load the pydub module.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## pymediainfo

```python
@property
def pymediainfo(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## pytesseract

```python
@property
def pytesseract(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## python_docx

```python
@property
def python_docx(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## startswith

```python
def startswith(self, prefix: str) -> bool:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## tiktoken

```python
@property
def tiktoken(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## torch

```python
@property
def torch(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## tqdm

```python
@property
def tqdm(self) -> _ModuleType | None:
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## values

```python
def values(self) -> list[_ModuleType | None]:
    """
    Get a list of all loaded modules.

Returns:
    A list of loaded modules, with None for unloaded modules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies

## whisper

```python
@property
def whisper(self) -> _ModuleType | None:
    """
    Load the whisper module.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Dependencies
