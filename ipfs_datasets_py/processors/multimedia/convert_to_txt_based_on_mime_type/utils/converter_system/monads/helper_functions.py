"""
Helper functions to control Monad pipeline behavior
"""
from typing import Any, Callable, TypeVar, Type


from utils.converter_system.monads.monad import Monad
from utils.converter_system.monads.error import ErrorMonad


T = TypeVar('T')
Container = TypeVar('Container', list, set, tuple)


def coerce_to_right_container(x, type: T) -> Container:
    if not isinstance(x, type):
        try:
            return type(x)
        except TypeError as e:
            raise TypeError(f"Could not coerce {x} to {type}") from e

def this_and_not_that(x: Any, this: Any, not_that: Any) -> bool:
    return True if isinstance(x, this) and not isinstance(x, not_that) else False

def all_in(x: Container, are_a: Any = None, are_not_a: Any = None) -> bool:
    """Check if all elements in a container are of a certain type."""
    if are_a and are_not_a:
        raise ValueError("Cannot specify both are_this and are_not_a")
    if not are_a and not are_not_a:
        raise ValueError("Must specify either are_this or are_not_a")
    else:
        if are_a: 
            return all(isinstance(y, are_a) for y in x)
        elif are_not_a:
            return all(not isinstance(y, are_not_a) for y in x)

def catch_error(func: Callable):
    return lambda x: ErrorMonad.left(x.value).catch(func) if x.errored else x


def except_(e: Exception | tuple[Exception]) -> Callable[[T], ErrorMonad[T]]:
    """Check if an input is an instance of the given exception type, and throw an error if it is."""
    if this_and_not_that(e, Exception, Container):
        e = (e,) # Coerce to tuple if not already
    if isinstance(e, tuple):
        if all_in(e, are_not_a=Exception):
            raise TypeError("Input must be an exception type or tuple of exception types")
    return lambda x: ErrorMonad.right(x) if isinstance(x, e) else ErrorMonad.left(x)


def error_on(e: Exception) -> Callable[[T], ErrorMonad[T]]:
    """Check if an input is an instance of the given exception type, and throw an error if it is."""
    return lambda x: ErrorMonad.right(x) if isinstance(x, e) else ErrorMonad.left(x)

def add_one(x: Any):
    return x + 1

def start(x, type: Monad[T]) -> Monad[T]:
    """Initialize the pipeline with a value and a monad type."""
    return type(x)

def stop(x: Any) -> Any:
    """Return the final value from a pipeline."""
    return x

def switch(monad: Monad) -> Monad:
    """Switch to a different Monad type."""
    return lambda x: monad(x.value) if isinstance(x, Monad) else monad(x)

