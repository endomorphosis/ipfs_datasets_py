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

from collections.abc import Awaitable, Callable
from typing import Any, Optional, TypeVar

import anyio


T = TypeVar("T")


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
