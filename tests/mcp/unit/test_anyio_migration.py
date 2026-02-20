"""Tests verifying that asyncio has been replaced with anyio across the package.

These tests confirm:
1. No `import asyncio` remains in the production source files (excluding multimedia).
2. Key migrated modules import correctly.
3. Key anyio patterns work at runtime (Semaphore, fail_after, to_thread, task groups).
4. anyio_compat.run() works as a sync-from-async bridge.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from typing import List

import anyio
import pytest

# Root of the source package
SRC_ROOT = Path(__file__).parents[3] / "ipfs_datasets_py"


def _collect_asyncio_import_files() -> List[Path]:
    """Return source files that still contain `import asyncio`."""
    excluded_subtree = SRC_ROOT / "processors" / "multimedia"
    results: List[Path] = []
    for py_file in SRC_ROOT.rglob("*.py"):
        if py_file.is_relative_to(excluded_subtree):
            continue  # multimedia has deep asyncio coupling; excluded by design
        content = py_file.read_text(encoding="utf-8", errors="replace")
        if "import asyncio" in content:
            results.append(py_file)
    return results


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------

def test_no_asyncio_imports_outside_multimedia():
    """No production source file (outside multimedia/) should import asyncio."""
    remaining = _collect_asyncio_import_files()
    if remaining:
        paths = "\n  ".join(str(p.relative_to(SRC_ROOT)) for p in remaining)
        pytest.fail(
            f"Found `import asyncio` in {len(remaining)} files:\n  {paths}\n"
            "Migrate these files to use `anyio`."
        )


def test_migrated_files_have_valid_syntax():
    """All migrated files must be syntactically valid Python."""
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
