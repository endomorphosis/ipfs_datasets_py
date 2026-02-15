# Function stubs from '/home/kylerose1946/omni_converter_mk2/core/_processing_pipeline.py'

## ProcessingPipeline

```python
class ProcessingPipeline:
    """
    Processing pipeline for the Omni-Converter.
    
    This class orchestrates the conversion of files to plaintext, using various
    components like the format detector, validator, content extractor, text normalizer,
    and output formatter.

    Attributes:
        configs: A pydantic model containing configuration settings.
        resources: A dictionary of callable classes and functions for the class to use.

    Private Attributes:
        _format_detector: An instance of FileFormatDetector for detecting file formats.
        _file_validator: An instance of FileValidator for validating files.
        _content_extractor: An instance of ContentExtractor for extracting content from files.
        _text_normalizer: An instance of TextNormalizer for normalizing extracted text.
        _output_formatter: An instance of OutputFormatter for formatting the output.
        _processing_result: An instance of ProcessingResult for storing processing results.
        _logger: An instance of Logger for logging messages.
        _status: An instance of PipelineStatus for tracking the processing status.
        _hashlib: A reference to the hashlib module for generating content hashes.
        _listeners: A list of status listener functions to notify about processing events.
    """
```

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None):
    """
    Initialize a processing pipeline.

Args:
    configs: A pydantic model containing configuration settings.
    resources: A dictionary of callable classes and functions for the class to use.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingPipeline

## process_file

```python
def process_file(self, file_path: str, *, output_format: str = "txt", output_path: Optional[str] = None, normalizers: Optional[list[str]] = None) -> ProcessingResult:
    """
    Process a single file.

Args:
    file_path: The path to the file to process.
    output_format: The format to convert the file to. Supported formats are: 'txt', 'md'. Defaults to 'txt'.
    output_path: The path to write the output to.
    - If it's a file path, the output will be written to that file.
    - If it's a directory, the output will be written to a file in that directory. 
        The name will be the same as the input file's. 
        Any extension will be removed and replaced with the one specified in output_format.
    - If None, the text is still extracted but written to a file in the temp directory.
        The name will be the same as the input file's, with the extension replaced by the one specified in output_format.
        If a file already exists at that path, the first 4 characters of the content_hash will be appended to the filename to avoid overwriting.
    normalizers: A list of normalizers to apply to the text post-extraction.
    - If None, extracted text will return as-is.

Returns:
    ProcessingResult: A dataclass detailing the result of processing the file.
    The dataclass contains the following fields:
        - success (bool): Whether the processing was successful.
        - file_path (str): The path to the input file.
        - output_path (str): The path to the output file.
        - format (str): The detected format of the input file.
        - errors (list[str]): list of errors encountered during processing.
        - metadata (dict[str, Any]): Metadata about the processing.
        - content_hash (str): Hash of the content for verification.
        - timestamp (datetime): Time when the processing was completed.

Raises:
    FileNotFoundError: If the file does not exist.
    PermissionError: If the file cannot be read.
    ValueError: If the file format is not supported.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingPipeline

## status

```python
@property
def status(self) -> dict[str, Any]:
    """
    Get the current status of the pipeline.

Returns:
    The current pipeline status as a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingPipeline

## register_listener

```python
def register_listener(self, listener: StatusListenerFunc) -> None:
    """
    Register a status listener.

Args:
    listener: The listener function to register.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingPipeline

## _notify_listeners

```python
def _notify_listeners(self, event: str, data: dict[str, Any]) -> None:
    """
    Notify all registered listeners of an event.

Args:
    event: The event type.
    data: The event data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingPipeline
