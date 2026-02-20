"""
anyio-compatible queue wrappers for use in place of asyncio.Queue and
asyncio.PriorityQueue throughout the multimedia processing pipeline.

anyio does not expose a Queue class; its equivalent is a pair of
MemoryObjectStream channels returned by anyio.create_memory_object_stream().
These wrappers present the familiar asyncio.Queue API so that existing call
sites need only change the class name in __init__ methods.

Usage::

    # before
    self.queue: asyncio.Queue = asyncio.Queue(maxsize=32)

    # after
    from utils.common.anyio_queues import AnyioQueue
    self.queue: AnyioQueue = AnyioQueue(maxsize=32)

"""

from __future__ import annotations

import heapq
from typing import Any, Generic, TypeVar

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

T = TypeVar("T")


class AnyioQueue(Generic[T]):
    """Drop-in replacement for ``asyncio.Queue``.

    Backed by :func:`anyio.create_memory_object_stream`.  Provides the same
    ``put``, ``put_nowait``, ``get``, ``get_nowait``, ``task_done``, ``join``,
    ``qsize``, and ``empty`` interface as ``asyncio.Queue``.

    Note:
        ``task_done()`` and ``join()`` are no-ops because anyio memory streams
        do not track in-flight items.  If you rely on those semantics you should
        use explicit synchronisation (e.g. ``anyio.Event``).
    """

    def __init__(self, maxsize: int = 0) -> None:
        buf: float = float("inf") if maxsize == 0 else float(maxsize)
        self._send: MemoryObjectSendStream[T]
        self._recv: MemoryObjectReceiveStream[T]
        self._send, self._recv = anyio.create_memory_object_stream(max_buffer_size=buf)

    # ------------------------------------------------------------------
    # async API
    # ------------------------------------------------------------------

    async def put(self, item: T) -> None:
        """Put *item* into the queue, blocking until a slot is available."""
        await self._send.send(item)

    async def get(self) -> T:
        """Remove and return an item from the queue, blocking until one is available."""
        return await self._recv.receive()

    # ------------------------------------------------------------------
    # sync (nowait) API
    # ------------------------------------------------------------------

    def put_nowait(self, item: T) -> None:
        """Put *item* without blocking; raise ``anyio.WouldBlock`` if full."""
        self._send.send_nowait(item)

    def get_nowait(self) -> T:
        """Get an item without blocking; raise ``anyio.WouldBlock`` if empty."""
        return self._recv.receive_nowait()

    # ------------------------------------------------------------------
    # Compatibility shims (no-ops)
    # ------------------------------------------------------------------

    def task_done(self) -> None:  # noqa: D401
        """No-op — anyio memory streams do not track in-flight items."""

    async def join(self) -> None:  # noqa: D401
        """No-op — anyio memory streams do not support join()."""

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def qsize(self) -> int:
        """Return the approximate number of items buffered in the stream."""
        try:
            stats = self._recv.statistics()
            return stats.current_buffer_used
        except Exception:
            return 0

    def empty(self) -> bool:
        """Return ``True`` if the queue is empty."""
        return self.qsize() == 0

    def full(self) -> bool:
        """Return ``True`` if the buffer is at capacity."""
        try:
            stats = self._recv.statistics()
            return stats.current_buffer_used >= stats.max_buffer_size
        except Exception:
            return False


class AnyioPriorityQueue(Generic[T]):
    """Drop-in replacement for ``asyncio.PriorityQueue``.

    Items are stored in a min-heap protected by an ``anyio.Lock``.  Callers
    block on ``get()`` until an item is available (signalled via an
    ``anyio.Event``).

    Args:
        maxsize: Maximum number of items.  ``0`` means unbounded.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._maxsize = maxsize
        self._heap: list[Any] = []
        self._lock = anyio.Lock()
        self._not_empty = anyio.Event()

    async def put(self, item: T) -> None:
        """Put *item* into the priority queue."""
        async with self._lock:
            heapq.heappush(self._heap, item)
            # Signal waiting getters if this is the first item
            if not self._not_empty.is_set():
                self._not_empty.set()

    def put_nowait(self, item: T) -> None:
        """Put *item* without blocking (no capacity enforcement)."""
        heapq.heappush(self._heap, item)

    async def get(self) -> T:
        """Remove and return the lowest-priority item, blocking until available."""
        while True:
            await self._not_empty.wait()
            async with self._lock:
                if self._heap:
                    item = heapq.heappop(self._heap)
                    if not self._heap:
                        # Reset the event so next get() will wait again
                        self._not_empty = anyio.Event()
                    return item
                # Item was grabbed by a concurrent getter; reset and retry
                self._not_empty = anyio.Event()

    def get_nowait(self) -> T:
        """Remove and return lowest-priority item without blocking."""
        if not self._heap:
            raise anyio.WouldBlock
        return heapq.heappop(self._heap)

    def task_done(self) -> None:  # noqa: D401
        """No-op."""

    async def join(self) -> None:  # noqa: D401
        """No-op."""

    def qsize(self) -> int:
        return len(self._heap)

    def empty(self) -> bool:
        return not self._heap

    def full(self) -> bool:
        return bool(self._maxsize and len(self._heap) >= self._maxsize)
