# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/external_programs.py'

Files last updated: 1751185406.0781615

Stub file last updated: 2025-07-17 05:36:42

## ExternalPrograms

```python
class ExternalPrograms:
    """
    Check the availability of external programs.

NOTE: As these programs are entirely external, this class does not provide access to them.
It only checks if they exist and can be run.

Properties:
    ffmpeg (bool): Whether ffmpeg is available.
    ffprobe (bool): Whether ffprobe is available.
    tesseract (bool): Whether tesseract is available.
    calibre (bool): Whether calibre is available.
    cuda (bool): Whether nvcc (NVIDIA CUDA Compiler) is available.
    seven_zip (bool): Whether 7-zip is available.
    libreoffice (bool): Whether LibreOffice is available.
    audacity (bool): Whether Audacity is available (optional, TODO: check for CLI).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __get__

```python
def __get__(self, instance, owner):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## __getitem__

```python
def __getitem__(self, name: str) -> bool:
    """
    Get a external program by name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## __init__

```python
def __init__(self, func):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## _classproperty

```python
class _classproperty:
    """
    Helper decorator to turn class methods into properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _test_for_non_critical_external_programs

```python
def _test_for_non_critical_external_programs() -> None:
    """
    Test for non-critical dependencies in a separate thread to ensure the application starts promptly.

This function creates a temporary instance of the `_Dependencies` class to load all required
modules without causing deadlocks. Once the modules are loaded, the temporary instance is
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

## calibre

```python
@_classproperty
def calibre(cls) -> bool:
    """
    Check if calibre is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## check_for_external_programs

```python
@classmethod
def check_for_external_programs(cls) -> None:
    """
    Check if external programs are available.

This method checks the availability of various external programs by attempting to run them
with the '--help' option. If the program is found and runs successfully, it is marked as available.
If it fails or is not found, it is marked as unavailable.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## cuda

```python
@_classproperty
def cuda(cls) -> bool:
    """
    Check if nvcc (NVIDIA CUDA Compiler) is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## ffmpeg

```python
@_classproperty
def ffmpeg(cls) -> bool:
    """
    Check if ffmpeg is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## ffprobe

```python
@_classproperty
def ffprobe(cls) -> bool:
    """
    Check if ffprobe is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## get

```python
@classmethod
def get(cls, name: str, default: bool = False) -> bool:
    """
    Get a external program by name with a default value.

Args:
    name (str): The name of the external program.
    default (bool): The default value to return if the external program is not found.
        Defaults to False.

Returns:
    The external program if found, otherwise the default value.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## items

```python
@classmethod
def items(cls) -> list[tuple[str, bool]]:
    """
    Get a list of all dependencies as (name, dependency) tuples.

Returns:
    A list of tuples containing dependency names and their corresponding objects.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## keys

```python
@classmethod
def keys(cls) -> list[str]:
    """
    Get a list of all external program names.

Returns:
    A list of external program names.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## libreoffice

```python
@_classproperty
def libreoffice(cls) -> bool:
    """
    Check if LibreOffice is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## nvidia_smi

```python
@_classproperty
def nvidia_smi(cls) -> bool:
    """
    Check if nvidia-smi is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## seven_zip

```python
@_classproperty
def seven_zip(cls) -> bool:
    """
    Check if 7-zip is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms

## tesseract

```python
@_classproperty
def tesseract(cls) -> bool:
    """
    Check if tesseract is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExternalPrograms
