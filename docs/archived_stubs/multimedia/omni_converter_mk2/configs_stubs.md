# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/configs.py'

Files last updated: 1751247493.492226

Stub file last updated: 2025-07-17 05:36:42

## Configs

```python
class Configs(BaseModel):
    """
    Configurations for the Omni-Converter.
Unlike options, these configurations are 

Attributes:
    resources: Resource limits and settings.
        - memory_limit_gb: Memory limit in GB. Defaults to 6 GB.
        - memory_limit_mb: Memory limit in MB (calculated from memory_limit_gb).
        - cpu_limit_percent: CPU utilization limit percentage. Defaults to 80%.
        - timeout_seconds: Timeout in seconds. Defaults to 3600 seconds (1 hour).
        - max_batch_size: Maximum number of files to process in one batch. Defaults to 100.
        - max_threads: Maximum number of worker threads.
        - monitoring_interval_seconds: Monitoring interval in seconds.
        - force_mocks: Force use of mocks, even if libraries are available.
    formats: Supported file formats.
        - text: List of supported text formats.
        - image: List of supported image formats.
        - audio: List of supported audio formats.
        - video: List of supported video formats.
        - application: List of supported application formats.
    security: Security settings for file processing.
        - max_file_size_mb: Maximum file size in MB.
        - sandbox_enabled: Enable sandbox for file processing.
        - allowed_formats: List of allowed formats (empty means all formats are allowed).
        - sanitize_output: Sanitize output to remove potential security risks.
    processing: Processing options for files.
        - continue_on_error: Continue processing batch even if some files fail. Defaults to True.
        - extract_metadata: Extract metadata from files. Defaults to True.
        - normalize_text: Normalize extracted text. Defaults to True.
        - quality_threshold: Minimum quality score for text extraction. Defaults to 0.9.
        - whisper_model: Whisper model to use for audio processing. Defaults to "base".
        - whisper_language: Language for Whisper model. Defaults to "en".
        - tesseract_language: Tesseract model for OCR. Defaults to "eng".
    output: Output settings for processed files.
        - default_format: Default output format. Defaults to "txt".
        - include_metadata: Include metadata in output. Defaults to True.
        - preserve_structure: Attempt to preserve document structure. Defaults to True.
        - encoding: Output file encoding. Defaults to "utf-8".

Properties:
    - version: str: The version of the Omni-Converter.
    - paths: Paths for important files and directories.

Methods:
    get_config_value(key: str, default: Any) -> Any:
        Get a configuration value by key, using dot notation for nested keys.
    set_config_value(key: str, value: Any) -> None:
        Set a configuration value by key, using dot notation for nested keys.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _Formats

```python
class _Formats(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _Output

```python
class _Output(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _PathsBaseModel

```python
class _PathsBaseModel(BaseModel):
    """
    Paths for important files and directories.

Attributes:
    THIS_FILE: DirectoryPath: The path to this file (configs.py)
    THIS_DIR: DirectoryPath: The directory containing this file (utils).
    ROOT_DIR: DirectoryPath: The root directory of the project.
    CONFIG_PATH: DirectoryPath: The path to the configuration file (configs.yaml).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _Processing

```python
class _Processing(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _Resources

```python
class _Resources(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _Security

```python
class _Security(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_cpu_cores

```python
def _get_cpu_cores(minus: int) -> int:
    """
    Get the number of CPU cores.

Returns:
    Number of CPU cores.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_config_value

```python
def get_config_value(self, key: str, default: Any) -> Any:
    """
    Get a configuration value by key.

Args:
    key: The key to get the value for, using dot notation for nested keys.
    default: The default value to return if the key is not found.
    
Returns:
    The configuration value, or the default if the key is not found.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs

## getitem

```python
def getitem(self, key: str) -> Union[str, int, float]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## memory_limit_mb

```python
@property
def memory_limit_mb(self) -> float:
    """
    Get the memory limit in MB.

Returns:
    Memory limit in MB.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Resources

## name

```python
def name(e: Exception) -> str:
    """
    Get the string name of the error.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## paths

```python
@property
def paths(self) -> _PathsBaseModel:
    """
    Get the paths for important files and directories.

Returns:
    _PathsBaseModel object containing important file and directory paths.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs

## set_config_value

```python
def set_config_value(self, key: str, value: Any) -> None:
    """
    Set a configuration value by key.

Args:
    key: The key to set the value for, using dot notation for nested keys.
    value: The value to set.
    
Raises:
    KeyError: If the key is not found in the configuration.
    ValueError: If the value is invalid for the specified key.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs

## setitem

```python
def setitem(self, key: str, value: Any) -> None:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## version

```python
@property
def version(self) -> str:
    """
    Get the version of the Omni-Converter.

Returns:
    The version of the Omni-Converter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs
