# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/common/try_except_decorator.py'

Files last updated: 1748075101.4335172

Stub file last updated: 2025-07-17 05:30:21

## async_wrapper

```python
@wraps(func)
async def async_wrapper(*args, **kwargs):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## decorator

```python
def decorator(func: Callable | Coroutine) -> Callable | Coroutine:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## try_except

```python
def try_except(func: Callable = lambda x: x, raise_: bool = None, exception_type: Exception | tuple[Exception, ...] = Exception, msg: str = "An unexpected exception occurred", raise_as: Optional[Exception] = None, default_return: Optional[Any] = None) -> Callable:
    """
    Decorator to handle exceptions in a function.

Args:
    raise_: Whether to re-raise the exception after logging.
        NOTE: This must be manually set to True or False. 
            This reduces the risk of accidentally raising or passing an exception.
    func: The function to decorate
    exception_type: The type of exception to catch. Equivalent to 
        `except exception_type as e`
    msg: The message to log on exception
    raise_as: Raise the exception as this type if specified and raise_ = True. Equivalent to 
        `raise raise_as from e` in the exception handler.
    default_return: The value to return if an exception occurs. Only returned if raise_ is False

Returns:
    A wrapped function that handles exceptions
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## wrapper

```python
@wraps(func)
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
