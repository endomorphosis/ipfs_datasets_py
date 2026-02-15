# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/handlers/_check_if_all_these_processors_are_mocks.py'

Files last updated: 1750023288.2056684

Stub file last updated: 2025-07-17 05:32:27

## check_if_all_these_processors_are_mocks

```python
def check_if_all_these_processors_are_mocks(name: str, keys: list[str], processors: dict[str, Processor]) -> bool:
    """
    Check if all specified processors are mock objects.

Args:
    name (str): The name of the handler being checked (used for logging context).
    keys (list[str]): List of processor keys to check in the processors dictionary.
    processors (dict[str, Processor]): Dictionary mapping processor names to Processor instances.
    logger (Logger): Logger instance for recording warnings about mock processors.

Returns:
    bool: True if all specified processors are mocks, False otherwise.
    NOTE:  If only some are mocks, it logs a warning for each mocked processor, then returns False.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
