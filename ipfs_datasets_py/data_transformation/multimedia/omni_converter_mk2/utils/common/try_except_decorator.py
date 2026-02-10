"""
Database connection and session management for the FastAPI application.

This module provides a Database class that encapsulates database connection management,
connection pooling, and CRUD operations. It supports multiple database engines
through a dependency injection pattern.
"""
from functools import wraps
import inspect
from typing import Any, Callable, Coroutine, Optional


from logger import logger


def try_except(func: Callable = lambda x: x, 
               raise_: bool = None,
               exception_type: Exception | tuple[Exception,...] = Exception, 
               msg: str = "An unexpected exception occurred",
               raise_as: Optional[Exception] = None,
               default_return: Optional[Any] = None
               ) -> Callable:
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

    def decorator(func: Callable | Coroutine) -> Callable | Coroutine:

        # Check if the function is asynchronous
        async_ = inspect.iscoroutinefunction(func)
        suc_msg = f"Function {func.__name__} completed successfully."
        fail_msg = f"Function {func.__name__} failed with error"

        @wraps(func)
        def wrapper(*args, **kwargs):
            if raise_ is None:
                raise ValueError("raise must be set to True or False")
            errored = None
            try:
                return func(*args, **kwargs)
            except exception_type as e:
                logger.exception(f"{msg}: {e}", stacklevel=2) # Raise the stack level up to the caller
                errored = e
            finally:
                if errored is None:
                    logger.debug(suc_msg)
                else:
                    logger.debug(fail_msg + f": {errored}")
                    if raise_:
                        if raise_as is not None:
                            raise raise_as from errored
                        else:
                            raise errored
                    else:
                        if default_return is not None:
                            return default_return

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if raise_ is None:
                raise ValueError("raise_ must be set to True or False")
            errored = None
            try:
                return await func(*args, **kwargs)
            except exception_type as e:
                logger.exception(f"{msg}: {e}", stacklevel=2) # Raise the stack level up to the caller
                errored = e
            finally:
                if errored is None:
                    logger.debug(suc_msg)
                else:
                    logger.debug(fail_msg + f": {errored}")
                    if raise_:
                        if raise_as is not None:
                            raise raise_as from errored
                        else:
                            raise errored
                    else:
                        if default_return is not None:
                            return default_return

        return async_wrapper if async_ else wrapper
    return decorator