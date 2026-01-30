"""Pytest configuration for migration tests.

This directory contains many historical "migration" scripts that were
intentionally named with a leading underscore (e.g. ``_test_*.py``) so they
would not be collected by the repository-wide ``python_files = test_*.py``
pattern.

To make migration tests runnable on-demand (e.g. ``pytest tests/migration_tests``)
without expanding collection in other test suites, we provide a scoped
collector that:

- Only targets files in this directory.
- Only opts-in ``_test_*.py`` files that *actually* define pytest tests.
- Avoids importing script-like files that have no test definitions.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import pytest


def _looks_like_pytest_test_module(path: Path) -> bool:
    """Heuristic to avoid importing non-test scripts during collection."""
    try:
        # Limit read size to keep collection fast.
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    # Simple, fast indicators that this module likely defines pytest tests.
    return ("def test_" in text) or ("class Test" in text)


def _safe_to_import_for_collection(path: Path) -> bool:
    """Return True if the module appears safe to import at collection time.

    Many files under tests/migration_tests are script-like and perform actions at
    import time (file IO, network, CLI execution). Importing those during pytest
    collection is unsafe.

    This uses an AST-based heuristic: only allow modules whose top-level
    statements are limited to imports, definitions, assignments/constants, and
    guarded main blocks.
    """

    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except Exception:
        return False

    def is_docstring_expr(node: ast.stmt) -> bool:
        return (
            isinstance(node, ast.Expr)
            and isinstance(getattr(node, "value", None), ast.Constant)
            and isinstance(node.value.value, str)
        )

    def is_main_guard(node: ast.If) -> bool:
        # Match: if __name__ == "__main__":
        test = node.test
        return (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        )

    def try_is_import_only(node: ast.Try) -> bool:
        allowed_stmt = (ast.Import, ast.ImportFrom)
        if not all(isinstance(s, allowed_stmt) for s in node.body):
            return False
        if not all(isinstance(s, allowed_stmt) for s in node.orelse):
            return False
        if not all(isinstance(s, allowed_stmt) for s in node.finalbody):
            return False
        for handler in node.handlers:
            if not all(isinstance(s, allowed_stmt) for s in handler.body):
                return False
        return True

    allowed_top_level = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)

    for node in tree.body:
        if isinstance(node, allowed_top_level):
            continue
        if is_docstring_expr(node):
            continue
        if isinstance(node, ast.If) and is_main_guard(node):
            continue
        if isinstance(node, ast.Try) and try_is_import_only(node):
            continue
        # Anything else (e.g., With/For/While/Call Expr) is considered unsafe.
        return False

    return True


def pytest_collect_file(file_path: Path, parent) -> Optional[pytest.Module]:
    """Collect opt-in migration tests.

    This hook runs only when pytest recurses into this directory.
    """

    if file_path.suffix != ".py":
        return None

    name = file_path.name
    if not name.startswith("_test_"):
        return None

    if not _looks_like_pytest_test_module(file_path):
        return None

    if not _safe_to_import_for_collection(file_path):
        return None

    return pytest.Module.from_parent(parent, path=file_path)
