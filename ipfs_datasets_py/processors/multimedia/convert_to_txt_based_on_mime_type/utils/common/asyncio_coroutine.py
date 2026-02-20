import inspect
from functools import wraps
from typing import Callable


def asyncio_coroutine(fn: Callable) -> Callable:
    """
    Decorator to convert a regular function to a coroutine function.

    This allows awaiting a regular function. 
    Not useful as a @-based decorator,
    but very helpful for inline conversions of unknown functions, 
    especially lambdas.
    """
    if inspect.iscoroutinefunction(fn):
        return fn

    @wraps(fn)
    async def _wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return _wrapper
