import importlib

import pytest


def test_root_star_import_only_exports_exceptions() -> None:
    ns: dict[str, object] = {}
    exec("from ipfs_datasets_py.knowledge_graphs import *", {}, ns)

    # Exceptions are intentionally part of the public package root API.
    assert "KnowledgeGraphError" in ns
    assert "QueryParseError" in ns

    # Convenience imports should *not* be part of __all__ (prevents accidental API surface).
    assert "GraphDatabase" not in ns
    assert "GraphEngine" not in ns
    assert "Entity" not in ns


def test_deprecated_root_convenience_imports_still_work() -> None:
    kg = importlib.import_module("ipfs_datasets_py.knowledge_graphs")

    with pytest.warns(DeprecationWarning):
        GraphDatabase = kg.GraphDatabase  # noqa: N806

    # Sanity check we got a type-like object.
    assert GraphDatabase is not None


def test_from_import_triggers_deprecation_warning() -> None:
    with pytest.warns(DeprecationWarning):
        from ipfs_datasets_py.knowledge_graphs import QueryExecutor  # noqa: F401
