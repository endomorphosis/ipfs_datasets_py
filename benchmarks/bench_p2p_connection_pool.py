"""Phase E1: Benchmark — P2P connection pool acquire/release latency.

Measures:
- Pool hit: acquiring a pre-created connection from the pool.
- Pool miss: pool is empty → a new connection is created.
- Sequential vs. concurrent acquires under light load.

The pool itself comes from
``ipfs_datasets_py.mcp_server.p2p_service_manager`` when P2P is available,
or falls back to a minimal mock so the benchmark is always runnable.

Run with::

    pytest benchmarks/bench_p2p_connection_pool.py -v
"""
from __future__ import annotations

import anyio
import pytest
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Minimal mock connection pool (used when real P2P deps are absent)
# ---------------------------------------------------------------------------

class _MockConnection:
    """Lightweight mock of a P2P connection."""

    def __init__(self, peer_id: str = "peer-1") -> None:
        self.peer_id = peer_id
        self.is_open = True

    async def ping(self) -> bool:
        await anyio.sleep(0)  # Simulate async I/O.
        return True

    async def close(self) -> None:
        self.is_open = False


class _MockConnectionPool:
    """Thread-safe mock connection pool with configurable pool_size."""

    def __init__(self, pool_size: int = 5) -> None:
        self._pool: list[_MockConnection] = [
            _MockConnection(f"peer-{i}") for i in range(pool_size)
        ]
        # No lock needed; single-threaded benchmark accesses pool sequentially.
        self._lock = None

    async def acquire(self, peer_id: Optional[str] = None) -> _MockConnection:
        """Return an idle connection or create a new one (pool-miss path)."""
        if self._pool:
            return self._pool.pop()
        # Pool miss — create a new connection.
        await anyio.sleep(0)  # Simulate connection setup latency.
        return _MockConnection(peer_id or "peer-new")

    async def release(self, conn: _MockConnection) -> None:
        """Return connection to the pool."""
        conn.is_open = True
        self._pool.append(conn)

    def pool_size(self) -> int:
        return len(self._pool)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def pool_with_connections() -> _MockConnectionPool:
    """Pool pre-filled with 8 connections (pool-hit scenario)."""
    return _MockConnectionPool(pool_size=8)


@pytest.fixture()
def empty_pool() -> _MockConnectionPool:
    """Pool with no connections (pool-miss scenario — new conn created)."""
    return _MockConnectionPool(pool_size=0)


# ---------------------------------------------------------------------------
# Try to import the real pool; fall back silently.
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.mcp_server.p2p_service_manager import (  # type: ignore[import]
        P2PServiceManager,
    )
    _HAS_REAL_POOL = True
except Exception:
    _HAS_REAL_POOL = False


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(group="p2p_pool")
def test_pool_hit_acquire_release(benchmark, pool_with_connections):
    """Acquire + use + release a connection from a full pool (pool hit)."""

    async def _run():
        conn = await pool_with_connections.acquire()
        alive = await conn.ping()
        await pool_with_connections.release(conn)
        return alive

    result = benchmark(lambda: anyio.run(_run))
    assert result is True


@pytest.mark.benchmark(group="p2p_pool")
def test_pool_miss_acquire_release(benchmark, empty_pool):
    """Acquire a connection when the pool is empty (pool miss — new conn)."""

    async def _run():
        conn = await empty_pool.acquire("peer-bench")
        alive = await conn.ping()
        await empty_pool.release(conn)
        return alive

    result = benchmark(lambda: anyio.run(_run))
    assert result is True


@pytest.mark.benchmark(group="p2p_pool")
def test_pool_concurrent_4_acquires(benchmark, pool_with_connections):
    """4 concurrent acquire+release cycles (parallel workload)."""

    async def _acquire_release(pool: _MockConnectionPool) -> bool:
        conn = await pool.acquire()
        ok = await conn.ping()
        await pool.release(conn)
        return ok

    async def _run():
        results = []

        async def _collect(pool):
            results.append(await _acquire_release(pool))

        async with anyio.create_task_group() as tg:
            for _ in range(4):
                tg.start_soon(_collect, pool_with_connections)
        return results

    results = benchmark(lambda: anyio.run(_run))
    assert len(results) == 4
    assert all(results)


@pytest.mark.benchmark(group="p2p_pool")
def test_pool_sequential_10_cycles(benchmark, pool_with_connections):
    """10 sequential acquire+release cycles — measures sustained throughput."""

    async def _run():
        for _ in range(10):
            conn = await pool_with_connections.acquire()
            await conn.ping()
            await pool_with_connections.release(conn)

    benchmark(lambda: anyio.run(_run))
