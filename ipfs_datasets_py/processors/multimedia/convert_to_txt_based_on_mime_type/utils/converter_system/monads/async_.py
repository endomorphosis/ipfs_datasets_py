import asyncio
import inspect
from functools import wraps
import logging
from typing import Any, Callable, TypeVar


from .monad import Monad

T = TypeVar("T")
U = TypeVar("U")

class TaskError(Exception):
    pass

def check_result(future: asyncio.Future, chained: asyncio.Future = None) -> Any:
    if future.exception():
        if chained:
            chained.set_exception(future.exception())
        raise TaskError()
    elif future.cancelled():
        logging.debug(f'{future} was cancelled')
        if chained:
            chained.cancel()
        raise TaskError()
    else:
        return future.result()

def pass_result(resolved: asyncio.Future, unresolved: asyncio.Future):
    if resolved.exception():
        unresolved.set_exception(
            resolved.exception()
        )
    elif resolved.cancelled():
        unresolved.cancel()
    else:
        unresolved.set_result(
            resolved.result()
        )

def ensure_this_is_a_coroutine(fn_or_coro):
    """
    Coerce a function into being a coroutine.
    Like the asyncio_coroutine decorator, except it's a regular function.
    """
    if inspect.iscoroutinefunction(fn_or_coro):
        return fn_or_coro

    elif callable(fn_or_coro):
        # Wrap a callable in a coroutine
        @wraps(fn_or_coro)
        async def wrapper(*args, **kwargs):
            result = fn_or_coro(*args, **kwargs)
            if inspect.iscoroutine(result):
                return await result
            else:
                return result
        return wrapper
    else:
        raise ValueError('Parameter is not method, function or coroutine')


from .monad import Monad
from .error import ErrorMonad


class Async(Monad[T]):

    def __init__(self, work, *args, **kwargs) -> None:
        loop = asyncio.get_event_loop()
        if isinstance(work, asyncio.Future):
            self._future = work
        elif inspect.iscoroutine(work):
            self._future = loop.create_task(work)
        elif callable(work):
            self._future = loop.create_task(
                ensure_this_is_a_coroutine(work)(*args, **kwargs)
            )
        else:
            self._future = loop.create_task(
                ensure_this_is_a_coroutine(lambda: work)()
            )
        self._chained = None

    @staticmethod
    def unit(value):
        return Async(value)

    @staticmethod
    def left(e: Exception) -> 'ErrorMonad[T]':
        """Create a non-successful computation."""
        return ErrorMonad(e)

    def bind(self, next_work: Any) -> 'Async[U]':
        if isinstance(next_work, Exception):
            return self.left(next_work) # Propagate errors

        next_work = ensure_this_is_a_coroutine(next_work)
        loop = asyncio.get_event_loop()

        def resolved(func):
            try:
                res = check_result(func, self._chained)
            except TaskError as e:
                return self.left(next_work) # Return an Error Monad if one occurred.
            task: asyncio.Future = loop.create_task(next_work(res))
            task.add_done_callback(lambda func: pass_result(func, new_future))

        new_future = loop.create_future()
        next_async = Async(new_future)
        self._chained = new_future
        self._future.add_done_callback(resolved)
        return next_async

    def __rshift__(self, other):
        return self.bind(other)

    @property
    def future(self):
        return self._future

    @property
    def errored(self):
        return self._future.done() and self._future.exception()