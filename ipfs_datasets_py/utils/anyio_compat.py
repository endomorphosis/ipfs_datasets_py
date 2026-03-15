"""Async runtime compatibility helpers.

This project historically used `asyncio` directly. For compatibility with both
`asyncio` and `trio` (e.g. libp2p), we prefer building new async code on `anyio`.

This module provides small, focused helpers for:
- running an awaitable from synchronous code
- basic timeouts
- thread offload for blocking functions

Design notes:
- `anyio.run()` can only be called from *synchronous* context (i.e., not from
  inside an already-running event loop). For that reason, `run()` detects an
  active async library via `sniffio` and raises a clear error if misused.

Keep this module dependency-light; `anyio` already depends on `sniffio`.
"""

from __future__ import annotations

import asyncio as _stdlib_asyncio
from collections.abc import Awaitable, Callable
import inspect
import threading
from typing import Any, Optional, TypeVar

import anyio


T = TypeVar("T")
TimeoutError = TimeoutError
Semaphore = anyio.Semaphore


class AsyncContextError(RuntimeError):
    """Raised when attempting to start a new event loop inside an async context."""


def in_async_context() -> bool:
    """Return True if running inside an anyio-managed async context."""

    try:
        anyio.get_current_task()
        return True
    except Exception:
        return False


def run(awaitable: Awaitable[T]) -> T:
    """Run an awaitable from synchronous code via `anyio.run`.

    Raises:
        AsyncContextError: If called from within an already-running async context.
    """

    if in_async_context():
        raise AsyncContextError(
            "Cannot call anyio_compat.run() from within an async context. "
            "Use `await` in async code instead."
        )

    async def _runner() -> T:
        return await awaitable

    return anyio.run(_runner)


async def sleep(seconds: float) -> None:
    """Backend-agnostic sleep."""

    await anyio.sleep(seconds)


async def run_sync_in_worker_thread(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a blocking function in a worker thread."""

    return await anyio.to_thread.run_sync(func, *args, **kwargs)


def cancelled_exc_class() -> type[BaseException]:
    """Return the backend-specific cancellation exception class."""

    return anyio.get_cancelled_exc_class()


def fail_after(seconds: float):
    """Create a timeout scope that raises TimeoutError when exceeded."""

    return anyio.fail_after(seconds)


def move_on_after(seconds: float):
    """Create a timeout scope that cancels on timeout (no exception)."""

    return anyio.move_on_after(seconds)


async def gather(*coros: Awaitable[T], return_exceptions: bool = True) -> list[T | BaseException]:
    """Run *coros* concurrently and return a list of results.

    Mirrors ``asyncio.gather(*coros, return_exceptions=True)``.

    When *return_exceptions* is ``True`` (default) exceptions are collected
    into the result list instead of propagating.  When ``False`` the first
    exception is re-raised after all tasks finish.

    Args:
        *coros: Awaitables to run concurrently.
        return_exceptions: If ``True`` (default) exceptions are returned as
            items in the result list.

    Returns:
        List of results in the same order as *coros*.
    """
    coro_list = list(coros)
    results: list[Any] = [None] * len(coro_list)

    async def _run(i: int, coro: Awaitable[T]) -> None:
        try:
            results[i] = await coro
        except Exception as exc:
            if return_exceptions:
                results[i] = exc
            else:
                raise

    async with anyio.create_task_group() as tg:
        for i, coro in enumerate(coro_list):
            tg.start_soon(_run, i, coro)

    return results


def iscoroutinefunction(func: Any) -> bool:
    return inspect.iscoroutinefunction(func)


async def wait_for(awaitable: Awaitable[T], timeout: float) -> T:
    with anyio.fail_after(timeout):
        return await awaitable


async def to_thread(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await anyio.to_thread.run_sync(func, *args, **kwargs)


class _CompatFuture(Awaitable[T]):
    """Small awaitable future for non-asyncio anyio backends."""

    def __init__(self) -> None:
        self._event = anyio.Event()
        self._lock = threading.Lock()
        self._done = False
        self._result: Optional[T] = None
        self._exception: Optional[BaseException] = None
        self._callbacks: list[Callable[[Any], Any]] = []

    def done(self) -> bool:
        with self._lock:
            return self._done

    def cancelled(self) -> bool:
        return False

    def set_result(self, result: T) -> None:
        callbacks: list[Callable[[Any], Any]] = []
        with self._lock:
            if self._done:
                raise _stdlib_asyncio.InvalidStateError("Future already done")
            self._done = True
            self._result = result
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        self._event.set()
        for callback in callbacks:
            callback(self)

    def set_exception(self, exc: BaseException) -> None:
        callbacks: list[Callable[[Any], Any]] = []
        with self._lock:
            if self._done:
                raise _stdlib_asyncio.InvalidStateError("Future already done")
            self._done = True
            self._exception = exc
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        self._event.set()
        for callback in callbacks:
            callback(self)

    def result(self) -> T:
        with self._lock:
            if not self._done:
                raise _stdlib_asyncio.InvalidStateError("Result is not ready")
            if self._exception is not None:
                raise self._exception
            return self._result  # type: ignore[return-value]

    def exception(self) -> Optional[BaseException]:
        with self._lock:
            if not self._done:
                raise _stdlib_asyncio.InvalidStateError("Result is not ready")
            return self._exception

    def add_done_callback(self, callback: Callable[[Any], Any]) -> None:
        call_now = False
        with self._lock:
            if self._done:
                call_now = True
            else:
                self._callbacks.append(callback)
        if call_now:
            callback(self)

    async def _wait(self) -> T:
        await self._event.wait()
        return self.result()

    def __await__(self):
        return self._wait().__await__()


class _FutureMeta(type):
    def __instancecheck__(cls, instance: Any) -> bool:
        return isinstance(instance, (_stdlib_asyncio.Future, _CompatFuture))


class Future(metaclass=_FutureMeta):
    """Runtime-checkable Future facade for asyncio-compatible call sites."""

    def __class_getitem__(cls, _item: Any) -> type[Future]:
        return cls


class _CompatLoop:
    """Minimal loop shim for legacy code paths expecting asyncio loop helpers."""

    def __init__(self) -> None:
        self._asyncio_loop: Optional[_stdlib_asyncio.AbstractEventLoop] = None
        self._anyio_token: Any = None
        if in_async_context():
            try:
                self._asyncio_loop = _stdlib_asyncio.get_running_loop()
            except RuntimeError:
                self._asyncio_loop = None
            try:
                self._anyio_token = anyio.lowlevel.current_token()
            except Exception:
                self._anyio_token = None

    def is_running(self) -> bool:
        return in_async_context()

    def run_until_complete(self, awaitable: Awaitable[T]) -> T:
        return run(awaitable)

    def create_future(self) -> _stdlib_asyncio.Future[T] | _CompatFuture[T]:
        if self._asyncio_loop is not None:
            return self._asyncio_loop.create_future()
        return _CompatFuture()

    def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> Any:
        if self._asyncio_loop is not None:
            return self._asyncio_loop.call_soon_threadsafe(callback, *args)
        if self._anyio_token is None:
            raise RuntimeError("no running event loop")
        return anyio.from_thread.run_sync(lambda: callback(*args), token=self._anyio_token)

    async def run_in_executor(self, _executor: Any, func: Callable[..., T], *args: Any) -> T:
        return await anyio.to_thread.run_sync(func, *args)


def get_event_loop() -> _CompatLoop:
    return _CompatLoop()


def get_running_loop() -> _CompatLoop:
    if not in_async_context():
        raise RuntimeError("no running event loop")
    return _CompatLoop()
