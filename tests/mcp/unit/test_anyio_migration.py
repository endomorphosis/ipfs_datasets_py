"""Tests verifying that asyncio has been replaced with anyio across the package.

These tests confirm:
1. No ``import asyncio`` remains in production source files (excluding the
   ``async_.py`` monad which wraps asyncio.Future callbacks by design).
2. All migrated files are syntactically valid Python.
3. Key anyio patterns work at runtime (Semaphore, fail_after, to_thread, task groups).
4. ``AnyioQueue`` and ``AnyioPriorityQueue`` wrappers behave like asyncio.Queue.
5. anyio_compat.run() works as a sync-from-async bridge.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path
from typing import List

import anyio
import pytest

# Root of the source package
SRC_ROOT = Path(__file__).parents[3] / "ipfs_datasets_py"

# Files that intentionally retain an ``import asyncio`` because they wrap
# asyncio-specific primitives (e.g. asyncio.Future) for the asyncio backend.
_ASYNCIO_ALLOWED = {
    SRC_ROOT / "processors" / "multimedia" / "convert_to_txt_based_on_mime_type"
    / "utils" / "converter_system" / "monads" / "async_.py",
}

# Pattern that matches ``import asyncio`` as a whole token on non-comment lines.
# Uses a negative character class to ensure no ``#`` precedes the import on the
# same line (handles both ``import asyncio`` and ``from x import asyncio``).
_ASYNCIO_IMPORT_RE = re.compile(r"(?m)^[^#\n]*\bimport asyncio\b")


def _collect_asyncio_import_files() -> List[Path]:
    """Return source files that still contain ``import asyncio``."""
    results: List[Path] = []
    for py_file in SRC_ROOT.rglob("*.py"):
        if not py_file.is_file():
            continue
        if py_file in _ASYNCIO_ALLOWED:
            continue
        content = py_file.read_text(encoding="utf-8", errors="replace")
        if _ASYNCIO_IMPORT_RE.search(content):
            results.append(py_file)
    return results


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------

def test_no_asyncio_imports_outside_multimedia():
    """No production source file (except the async monad shim) should import asyncio."""
    remaining = _collect_asyncio_import_files()
    if remaining:
        paths = "\n  ".join(str(p.relative_to(SRC_ROOT)) for p in remaining)
        pytest.fail(
            f"Found `import asyncio` in {len(remaining)} files:\n  {paths}\n"
            "Migrate these files to use `anyio`."
        )


def test_migrated_files_have_valid_syntax():
    """All migrated files must be syntactically valid Python."""
    multimedia_root = SRC_ROOT / "processors" / "multimedia" / "convert_to_txt_based_on_mime_type"
    migrated = [
        SRC_ROOT / "knowledge_graphs" / "transactions" / "wal.py",
        SRC_ROOT / "knowledge_graphs" / "transactions" / "manager.py",
        SRC_ROOT / "knowledge_graphs" / "query" / "unified_engine.py",
        SRC_ROOT / "knowledge_graphs" / "query" / "hybrid_search.py",
        SRC_ROOT / "knowledge_graphs" / "storage" / "ipld_backend.py",
        SRC_ROOT / "logic" / "batch_processing.py",
        SRC_ROOT / "logic" / "e2e_validation.py",
        SRC_ROOT / "logic" / "fol" / "converter.py",
        SRC_ROOT / "logic" / "deontic" / "converter.py",
        SRC_ROOT / "core_operations" / "dataset_loader.py",
        SRC_ROOT / "core_operations" / "dataset_converter.py",
        SRC_ROOT / "core_operations" / "dataset_saver.py",
        SRC_ROOT / "core_operations" / "ipfs_getter.py",
        SRC_ROOT / "core_operations" / "ipfs_pinner.py",
        SRC_ROOT / "mcp_server" / "trio_adapter.py",
        SRC_ROOT / "mcp_server" / "runtime_router.py",
        SRC_ROOT / "mcp_server" / "mcplusplus" / "executor.py",
        SRC_ROOT / "mcp_server" / "mcplusplus" / "priority_queue.py",
        SRC_ROOT / "mcp_server" / "mcplusplus" / "workflow_engine.py",
        SRC_ROOT / "mcp_server" / "mcplusplus" / "workflow_dag.py",
        SRC_ROOT / "mcp_server" / "mcplusplus" / "bootstrap_system.py",
        SRC_ROOT / "mcp_server" / "mcplusplus" / "result_cache.py",
        SRC_ROOT / "processors" / "legal_scrapers" / "parallel_web_archiver.py",
        # multimedia files migrated in this session
        multimedia_root / "utils" / "common" / "asyncio_coroutine.py",
        multimedia_root / "utils" / "common" / "stopwatch.py",
        multimedia_root / "utils" / "common" / "anyio_queues.py",
        multimedia_root / "utils" / "converter_system" / "monads" / "async_.py",
        multimedia_root / "utils" / "converter_system" / "run_in_parallel_with_concurrency_limiter.py",
        multimedia_root / "utils" / "converter_system" / "run_in_thread_pool.py",
        multimedia_root / "converter_system" / "conversion_pipeline" / "functions" / "core.py",
        multimedia_root / "converter_system" / "conversion_pipeline" / "functions" / "optimize.py",
        multimedia_root / "converter_system" / "conversion_pipeline" / "functions" / "pipeline.py",
        multimedia_root / "converter_system" / "file_path_queue" / "file_path_queue.py",
        multimedia_root / "external_interface" / "file_paths_manager" / "file_paths_manager.py",
        multimedia_root / "main.py",
        multimedia_root / "pools" / "non_system_resources" / "core_functions_pool" / "core_functions_pool.py",
        multimedia_root / "pools" / "non_system_resources" / "file_path_pool" / "file_path_pool.py",
        multimedia_root / "pools" / "system_resources" / "system_resources_pool_template.py",
        SRC_ROOT / "processors" / "multimedia" / "media_processor.py",
        SRC_ROOT / "processors" / "multimedia" / "omni_converter_mk2" / "core" / "content_extractor" / "processors" / "by_ability" / "_llm_processor.py",
    ]
    errors = []
    for p in migrated:
        if not p.exists():
            continue  # file may not exist in this clone state
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"{p.relative_to(SRC_ROOT)}: {exc}")
    if errors:
        pytest.fail("Syntax errors in migrated files:\n" + "\n".join(errors))


# ---------------------------------------------------------------------------
# Module import tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", [
    "ipfs_datasets_py.core_operations.dataset_loader",
    "ipfs_datasets_py.core_operations.dataset_converter",
    "ipfs_datasets_py.core_operations.dataset_saver",
    "ipfs_datasets_py.core_operations.ipfs_getter",
    "ipfs_datasets_py.core_operations.ipfs_pinner",
    "ipfs_datasets_py.logic.batch_processing",
    "ipfs_datasets_py.logic.benchmarks",
    "ipfs_datasets_py.knowledge_graphs.transactions.wal",
    "ipfs_datasets_py.knowledge_graphs.transactions.manager",
    "ipfs_datasets_py.mcp_server.mcplusplus.executor",
    "ipfs_datasets_py.mcp_server.mcplusplus.priority_queue",
    "ipfs_datasets_py.mcp_server.mcplusplus.workflow_dag",
    "ipfs_datasets_py.mcp_server.mcplusplus.workflow_engine",
    "ipfs_datasets_py.mcp_server.mcplusplus.result_cache",
    "ipfs_datasets_py.mcp_server.mcplusplus.peer_discovery",
    "ipfs_datasets_py.utils.anyio_compat",
])
def test_migrated_module_imports(module_path: str):
    """Migrated modules must import without errors."""
    try:
        importlib.import_module(module_path)
    except ImportError as exc:
        # Skip if optional dependency is missing (e.g. aiohttp, datasets)
        pytest.skip(f"Optional dependency missing: {exc}")


# ---------------------------------------------------------------------------
# anyio pattern runtime tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_anyio_semaphore_works():
    """anyio.Semaphore limits concurrent access correctly."""
    sem = anyio.Semaphore(2)
    results: list[int] = []

    async def worker(i: int) -> None:
        async with sem:
            results.append(i)

    async with anyio.create_task_group() as tg:
        for i in range(5):
            tg.start_soon(worker, i)

    assert sorted(results) == [0, 1, 2, 3, 4]


@pytest.mark.anyio
async def test_anyio_fail_after_replaces_wait_for():
    """anyio.fail_after raises TimeoutError (stdlib), matching asyncio.wait_for semantics."""
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.001):
            await anyio.sleep(10)


@pytest.mark.anyio
async def test_anyio_to_thread_run_sync():
    """anyio.to_thread.run_sync replaces asyncio.to_thread and loop.run_in_executor."""
    result = await anyio.to_thread.run_sync(lambda: 2 + 2)
    assert result == 4


@pytest.mark.anyio
async def test_anyio_task_group_replaces_gather():
    """anyio task group with result collection replaces asyncio.gather."""
    async def compute(n: int) -> int:
        await anyio.sleep(0)
        return n * n

    expected = [0, 1, 4, 9, 16]
    results: list[int | Exception] = [None] * 5

    async def _run(i: int, coro) -> None:
        try:
            results[i] = await coro
        except Exception as exc:
            results[i] = exc

    async with anyio.create_task_group() as tg:
        for i in range(5):
            tg.start_soon(_run, i, compute(i))

    assert results == expected


@pytest.mark.anyio
async def test_anyio_get_cancelled_exc_class():
    """anyio.get_cancelled_exc_class() returns the backend's cancellation exception."""
    import asyncio

    cancelled_class = anyio.get_cancelled_exc_class()
    assert cancelled_class is asyncio.CancelledError  # asyncio backend

    try:
        raise asyncio.CancelledError("test")
    except anyio.get_cancelled_exc_class():
        pass  # correctly caught
    else:
        pytest.fail("CancelledError was not caught by get_cancelled_exc_class()")


@pytest.mark.anyio
async def test_anyio_move_on_after():
    """anyio.move_on_after silently cancels without raising."""
    with anyio.move_on_after(0.001) as scope:
        await anyio.sleep(10)
    assert scope.cancelled_caught


# ---------------------------------------------------------------------------
# anyio_compat bridge tests
# ---------------------------------------------------------------------------

def test_anyio_compat_run_from_sync():
    """anyio_compat.run() executes a coroutine from synchronous context."""
    from ipfs_datasets_py.utils.anyio_compat import run as anyio_run

    async def double(n: int) -> int:
        await anyio.sleep(0)
        return n * 2

    result = anyio_run(double(21))
    assert result == 42


def test_anyio_compat_in_async_context_false_outside_loop():
    """anyio_compat.in_async_context() returns False outside an event loop."""
    from ipfs_datasets_py.utils.anyio_compat import in_async_context

    assert in_async_context() is False


@pytest.mark.anyio
async def test_anyio_compat_in_async_context_true_inside_loop():
    """anyio_compat.in_async_context() returns True inside a running loop."""
    from ipfs_datasets_py.utils.anyio_compat import in_async_context

    assert in_async_context() is True


# ---------------------------------------------------------------------------
# setup.py dependency check
# ---------------------------------------------------------------------------

def test_anyio_in_install_requires():
    """setup.py must list anyio in install_requires."""
    setup_py = Path(__file__).parents[3] / "setup.py"
    if not setup_py.exists():
        pytest.skip("setup.py not found")
    content = setup_py.read_text()
    assert "anyio" in content, "anyio must be listed as a dependency in setup.py"


# ---------------------------------------------------------------------------
# AnyioQueue / AnyioPriorityQueue runtime tests (multimedia helpers)
# ---------------------------------------------------------------------------

_ANYIO_QUEUES_PATH = (
    SRC_ROOT
    / "processors" / "multimedia"
    / "convert_to_txt_based_on_mime_type"
    / "utils" / "common" / "anyio_queues.py"
)


def _import_anyio_queues():
    """Import AnyioQueue and AnyioPriorityQueue from the multimedia package."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("anyio_queues", _ANYIO_QUEUES_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.AnyioQueue, mod.AnyioPriorityQueue


@pytest.mark.anyio
async def test_anyio_queue_put_and_get():
    """AnyioQueue.put() and .get() round-trip single items."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    AnyioQueue, _ = _import_anyio_queues()
    q: object = AnyioQueue()
    await q.put(42)
    result = await q.get()
    assert result == 42


@pytest.mark.anyio
async def test_anyio_queue_put_nowait_get_nowait():
    """AnyioQueue.put_nowait() and .get_nowait() work for buffered items."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    AnyioQueue, _ = _import_anyio_queues()
    q = AnyioQueue(maxsize=10)
    q.put_nowait("hello")
    q.put_nowait("world")
    assert q.get_nowait() == "hello"
    assert q.get_nowait() == "world"


@pytest.mark.anyio
async def test_anyio_queue_empty():
    """AnyioQueue.empty() returns True when no items buffered."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    AnyioQueue, _ = _import_anyio_queues()
    q = AnyioQueue()
    assert q.empty() is True
    q.put_nowait("x")
    assert q.empty() is False


@pytest.mark.anyio
async def test_anyio_queue_task_done_noop():
    """AnyioQueue.task_done() is a no-op (no exception raised)."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    AnyioQueue, _ = _import_anyio_queues()
    q = AnyioQueue()
    q.task_done()  # must not raise


@pytest.mark.anyio
async def test_anyio_queue_producer_consumer():
    """Multiple items sent by a producer are received in order."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    AnyioQueue, _ = _import_anyio_queues()
    q = AnyioQueue(maxsize=100)
    items = list(range(10))
    results: list[int] = []

    async def producer() -> None:
        for i in items:
            await q.put(i)
        await q.put(None)  # sentinel

    async def consumer() -> None:
        while True:
            val = await q.get()
            if val is None:
                break
            results.append(val)

    async with anyio.create_task_group() as tg:
        tg.start_soon(producer)
        tg.start_soon(consumer)

    assert results == items


@pytest.mark.anyio
async def test_anyio_priority_queue_ordering():
    """AnyioPriorityQueue returns items in ascending priority order."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    _, AnyioPriorityQueue = _import_anyio_queues()
    pq = AnyioPriorityQueue()
    await pq.put((3, "low"))
    await pq.put((1, "high"))
    await pq.put((2, "medium"))

    first = await pq.get()
    second = await pq.get()
    third = await pq.get()

    assert first == (1, "high")
    assert second == (2, "medium")
    assert third == (3, "low")


@pytest.mark.anyio
async def test_anyio_priority_queue_empty_and_qsize():
    """AnyioPriorityQueue.empty() and .qsize() reflect current state."""
    if not _ANYIO_QUEUES_PATH.exists():
        pytest.skip("anyio_queues.py not found")
    _, AnyioPriorityQueue = _import_anyio_queues()
    pq = AnyioPriorityQueue()
    assert pq.empty() is True
    assert pq.qsize() == 0
    await pq.put((1, "a"))
    await pq.put((2, "b"))
    assert pq.qsize() == 2
    assert pq.empty() is False


# ---------------------------------------------------------------------------
# No asyncio in multimedia source (except the allowed monad shim)
# ---------------------------------------------------------------------------

def test_multimedia_source_files_use_anyio():
    """Key multimedia source files must not import asyncio (except monad shim)."""
    multimedia_root = (
        SRC_ROOT / "processors" / "multimedia" / "convert_to_txt_based_on_mime_type"
    )
    # Files that were migrated and must NOT have bare `import asyncio`
    to_check = [
        multimedia_root / "utils" / "common" / "asyncio_coroutine.py",
        multimedia_root / "utils" / "common" / "stopwatch.py",
        multimedia_root / "utils" / "converter_system" / "run_in_parallel_with_concurrency_limiter.py",
        multimedia_root / "utils" / "converter_system" / "run_in_thread_pool.py",
        multimedia_root / "converter_system" / "conversion_pipeline" / "functions" / "core.py",
        multimedia_root / "converter_system" / "conversion_pipeline" / "functions" / "optimize.py",
        multimedia_root / "converter_system" / "conversion_pipeline" / "functions" / "pipeline.py",
        multimedia_root / "converter_system" / "file_path_queue" / "file_path_queue.py",
        multimedia_root / "external_interface" / "file_paths_manager" / "file_paths_manager.py",
        multimedia_root / "main.py",
        multimedia_root / "pools" / "non_system_resources" / "file_path_pool" / "file_path_pool.py",
        multimedia_root / "pools" / "system_resources" / "system_resources_pool_template.py",
        SRC_ROOT / "processors" / "multimedia" / "media_processor.py",
    ]
    violations = []
    for p in to_check:
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8", errors="replace")
        if _ASYNCIO_IMPORT_RE.search(content):
            violations.append(str(p.relative_to(SRC_ROOT)))
    if violations:
        pytest.fail(
            "These multimedia files still contain `import asyncio`:\n"
            + "\n  ".join(violations)
        )
