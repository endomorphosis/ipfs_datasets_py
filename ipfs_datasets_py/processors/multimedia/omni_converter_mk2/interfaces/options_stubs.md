# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/interfaces/options.py'

Files last updated: 1751015660.564282

Stub file last updated: 2025-07-17 04:44:10

## Options

```python
class Options(BaseModel):
    """
    Options for the Omni-Converter.

These options are intended to validate argparse arguments 
and provide a structured way to manage conversion settings.

Attributes:
    input: The input file(s) or directory to convert.
    output: Output directory for the converted content.
    walk: Process directories recursively, including all subdirectories.
    normalize: Normalize text before saving.
    security_checks: Check input files for malicious aspects.
    metadata: Extract metadata from input files.
    structure: Extract structural elements from input files.
    format: Output format for the converted text.
    max_threads: Maximum number of threads for parallel processing.
    max_memory: Maximum memory usage (GB).
    max_vram: Maximum VRAM usage (GB).
    budget_in_usd: Budget in USD for priced API calls.
    normalizers: Text normalizers to apply (comma-separated).
    max_cpu: Maximum CPU usage percentage.
    quality_threshold: Quality filtering threshold (0-1).
    continue_on_error: Continue processing files even if some fail.
    parallel: Enable parallel document processing.
    follow_symlinks: Follow symbolic links when processing directories.
    include_metadata: Include file metadata in output.
    lossy: Relax quality threshold for large/complex files.
    normalize_text: Normalize text output.
    sanitize: Sanitize output files.
    show_options: Show current options and exit.
    show_progress: Show progress bar during batch operations.
    verbose: Log detailed information during processing.
    list_formats: List supported input formats and exit.
    list_normalizers: List supported text normalizers and exit.
    list_output_formats: List supported output formats and exit.
    version: Show version information and exit.
    max_batch_size: Maximum number of files to process in a single batch.
    retries: Maximum number of retries for failed conversions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OutputFormat

```python
class OutputFormat(StrEnum):
    """
    Enumeration for supported output file formats.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __contains__

```python
def __contains__(self, key: str) -> bool:
    """
    Check if a key exists in the options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## __getitem__

```python
def __getitem__(self, key: str) -> str | int | float:
    """
    Get an item by key.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## __iter__

```python
def __iter__(self):
    """
    Make the options iterable.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## __len__

```python
def __len__(self) -> int:
    """
    Get the number of options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## __setitem__

```python
def __setitem__(self, key: str, value: Any) -> None:
    """
    Set an item by key.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## _validate_format

```python
def _validate_format(format: str) -> str:
    """
    Validate the output format option.

Args:
    format: The output format string.

Returns:
    The validated output format string.

Raises:
    ValueError: If the format is not supported.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _validate_max_memory

```python
def _validate_max_memory(max_memory: PositiveInt) -> PositiveInt:
    """
    Validate the maximum memory usage in GB.

Args:
    max_memory: The maximum memory usage in GB.

Returns:
    The validated maximum memory usage in GB.

Raises:
    ValueError: If the maximum memory is greater than the system's memory.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _validate_max_vram

```python
def _validate_max_vram(max_vram: PositiveInt) -> PositiveInt:
    """
    Validate the maximum VRAM usage in GB.)

Args:
    max_vram: The maximum VRAM usage in GB.

Returns:
    The validated maximum VRAM usage in GB.

Raises:
    ValueError: If the maximum VRAM is less than 1MB.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _validate_max_workers

```python
def _validate_max_workers(max_threads: PositiveInt) -> PositiveInt:
    """
    Validate the maximum number of worker threads.

Returns:
    The validated maximum number of worker threads.

Raises:
    ValueError: If the maximum number of workers is less than 1.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## add_arguments_to_parser

```python
def add_arguments_to_parser(self, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """
    Assign the options to an argparse parser.

Args:
    parser: The argparse parser to assign the options to.
    
Returns:
    The configured argparse parser.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## get

```python
def get(self, key: str, default: Optional[Any] = None) -> str | int | float | None:
    """
    Get an item by key, returning a default value if the key does not exist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## getitem

```python
def getitem(self, key: str) -> str | int | float:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## items

```python
def items(self) -> list[tuple[str, str | int | float]]:
    """
    Get the items of the options as (key, value) pairs.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## keys

```python
def keys(self) -> list[str]:
    """
    Get the keys of the options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

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

## print_options

```python
def print_options(self, type_: str = "defaults", return_string: bool = False) -> Optional[str]:
    """
    Pretty-print the options in a human-readable format.

Args:
    type_: Type of options to print ('defaults', 'current', or 'argparse').
    Defaults will show the default values for each option.
    Current will show the current values set in the instance.

Raises:
    ValueError: If an invalid type is specified.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## setitem

```python
def setitem(self, key: str, value: Any) -> None:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options

## values

```python
def values(self) -> list[str | int | float]:
    """
    Get the values of the options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Options
