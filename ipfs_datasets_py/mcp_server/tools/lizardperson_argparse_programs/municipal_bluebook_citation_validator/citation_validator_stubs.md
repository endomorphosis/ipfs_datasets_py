# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/citation_validator/citation_validator.py'

Files last updated: 1751408933.7164564

Stub file last updated: 2025-07-07 01:10:14

## CheckResult

```python
@dataclass
class CheckResult:
    """
    The result of a citation validation check.

Attributes:
    valid (bool): Whether the citation passed validation. Defaults to True.
    error_type (Optional[str]): The type of validation error encountered, if any.
        None when the citation is valid.
    message (Optional[str]): A descriptive message about the validation result.
        None when the citation is valid.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CitationValidator

```python
class CitationValidator:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ErrorDbInsert

```python
@dataclass
class ErrorDbInsert:
    """
    Represents an error record to be inserted into the errors database table.

Attributes:
    cid (str): Primary CID identifier for the error record. 
        Created by hashing all other fields together once they are assigned.
    citation_cid (str): CID Identifier for the related citation
    gnis (int): Geographic Names Information System identifier
    geography_error (str): Geography validation error message (empty string if none)
    type_error (str): Type validation error message (empty string if none)
    section_error (str): Section validation error message (empty string if none)
    date_error (str): Date validation error message (empty string if none)
    format_error (str): Format validation error message (empty string if none)
    error_message (str): Combined error message for all validation errors
    severity (int): Error severity level (1-5, where 1 is low and 5 is critical)
    created_at (Optional[str]): Timestamp when the error was created (auto-generated in DB)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _CitationValidatorError

```python
class _CitationValidatorError(Exception):
    """
    Base class for all citation validation errors.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources = None, configs: Configs = None):
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## __post_init__

```python
def __post_init__(self):
    """
    Validate severity is within acceptable range.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorDbInsert

## _check_code

```python
def _check_code(self, citation: dict = None, place_documents = None) -> dict:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _check_dates

```python
def _check_dates(self, citation: dict = None, place_documents = None) -> dict:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _check_formats

```python
def _check_formats(self, citation: dict = None, place_documents = None) -> dict:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _check_geography

```python
def _check_geography(self, citation: dict = None, place_documents = None) -> dict:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _check_section

```python
def _check_section(self, citation: dict = None, place_documents = None) -> dict:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _load_save_validation_errors_string

```python
def _load_save_validation_errors_string(self) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _queue_to_iterable

```python
@staticmethod
def _queue_to_iterable(queue: Queue) -> Generator[Any, None, None]:
    """
    Convert a Queue to an iterable generator.

Args:
    queue (Queue): The queue to convert.

Yields:
    Any: Items from the queue.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _run_check

```python
def _run_check(self, func: Callable = None, citation: dict = None, error_type: str = None, place_documents: Optional[list[dict]] = None) -> Optional[dict]:
    """
    Run a validation check on a citation.
Args:
    func (Callable): The validation function to run.
    citation (dict): The citation to validate.
    error_type (str): The type of error to report if validation fails.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## _validate_citations

```python
def _validate_citations(self, gnis: int) -> list[dict[str, CheckResult]]:
    """
    Returns:
    A list of dictionaries containing validation results for each citation in the parquet file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## error_message

```python
@staticmethod
def error_message(name: str, e: Exception) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## iterable_gnis_queue

```python
@property
def iterable_gnis_queue(self) -> Generator[Any, None, None]:
    """
    Convert the queue to an iterable for batch processing
    """
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## iterable_validation_queue

```python
@property
def iterable_validation_queue(self) -> Generator[Any, None, None]:
    """
    Convert the queue to an iterable for batch processing
    """
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## save_validation_errors

```python
def save_validation_errors(self, result_batch: list[dict[str, Any]], error_db: duckdb.DuckDBPyConnection) -> int:
    """
    Save validation errors for a citation to the error database.

Args:
    results: The validation results containing error information
    error_db: The database connection for storing validation errors
    """
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert the CheckResult to a dictionary.

Returns:
    A dictionary representation of the CheckResult.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CheckResult

## validate_citations_against_html_and_references

```python
def validate_citations_against_html_and_references(self, sampled_gnis, reference_db, error_db) -> tuple[list]:
```
* **Async:** False
* **Method:** True
* **Class:** CitationValidator
