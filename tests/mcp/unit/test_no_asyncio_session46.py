"""
Session 46 — Phase N2: CI regression check for asyncio usage in production code.

Ensures that no production .py file inside ipfs_datasets_py/mcp_server/ directly
imports asyncio.  All async code must use anyio APIs so the codebase stays
compatible with both the asyncio and trio backends.

This test uses the AST to detect imports statically (no need to execute code).
"""

import ast
import pathlib

# Root of the mcp_server source tree (relative to repo root)
MCP_ROOT = pathlib.Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "mcp_server"


def _collect_asyncio_violations():
    """Walk every .py file in mcp_server/ and return a list of offending locations."""
    violations = []
    for py_file in sorted(MCP_ROOT.rglob("*.py")):
        # Skip test files and compiled cache
        rel = str(py_file)
        if "__pycache__" in rel or "/test_" in rel or "\\test_" in rel:
            continue
        src = py_file.read_text(errors="replace")
        try:
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError:
            continue  # Not our problem

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "asyncio" or alias.name.startswith("asyncio."):
                        violations.append(f"{py_file}:{node.lineno}  import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "asyncio" or module.startswith("asyncio."):
                    names = ", ".join(a.name for a in node.names)
                    violations.append(f"{py_file}:{node.lineno}  from {module} import {names}")
    return violations


def test_no_asyncio_imports_in_mcp_server_production_code():
    """No production mcp_server .py file should import asyncio directly.

    All async primitives must use anyio equivalents:
      asyncio.run()           → anyio.run()
      asyncio.sleep()         → await anyio.sleep()
      asyncio.gather()        → anyio TaskGroup / gather
      asyncio.get_event_loop() → (not needed with anyio)
      asyncio.Lock            → anyio.Lock()
      asyncio.Event           → anyio.Event()
      asyncio.Semaphore(n)    → anyio.Semaphore(n)
    """
    violations = _collect_asyncio_violations()
    assert violations == [], (
        "Found asyncio imports in production mcp_server files "
        "(use anyio equivalents instead):\n  " + "\n  ".join(violations)
    )


def test_mcp_root_exists():
    """Sanity check: the mcp_server root must exist."""
    assert MCP_ROOT.is_dir(), f"mcp_server root not found: {MCP_ROOT}"


def test_at_least_one_py_file_scanned():
    """Make sure the scanner actually visits files (guards against misconfigured path)."""
    py_files = [
        p for p in MCP_ROOT.rglob("*.py")
        if "__pycache__" not in str(p) and "/test_" not in str(p)
    ]
    assert len(py_files) >= 10, (
        f"Expected to scan at least 10 production .py files, found {len(py_files)}"
    )


def test_anyio_present_in_mcp_server():
    """At least one production mcp_server file should import anyio (ensures the
    scanner's sibling 'pass' condition is not vacuously true)."""
    anyio_files = []
    for py_file in MCP_ROOT.rglob("*.py"):
        if "__pycache__" in str(py_file) or "/test_" in str(py_file):
            continue
        src = py_file.read_text(errors="replace")
        try:
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name == "anyio" or a.name.startswith("anyio.") for a in node.names):
                    anyio_files.append(str(py_file))
                    break
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("anyio"):
                    anyio_files.append(str(py_file))
                    break
    assert len(anyio_files) >= 1, (
        "Expected at least one production mcp_server file to import anyio"
    )
