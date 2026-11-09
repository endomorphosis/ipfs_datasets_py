"""LCM-030: country-laws IR rows become legal-corpus.law@1 without a shard rewrite."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/country_laws_ir_v1.py"
)
_SCHEMA_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/schema.py"
)
_PACKAGE_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py"
)
_QUERY_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/query.py"
)
_STORE_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/duckdb_store.py"
)


def _assignment(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
            value = node.value
        else:
            continue
        if value is not None and any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            return value
    raise AssertionError(f"{name} missing from {path}")


def _string(path: Path, name: str) -> str:
    value = _assignment(path, name)
    assert isinstance(value, ast.Constant) and isinstance(value.value, str)
    return value.value


def _columns(path: Path, name: str) -> tuple[str, ...]:
    value = _assignment(path, name)
    assert isinstance(value, ast.Tuple)
    columns: list[str] = []
    for item in value.elts:
        assert isinstance(item, ast.Constant) and isinstance(item.value, str)
        columns.append(item.value)
    return tuple(columns)


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "lcm030_country_laws_ir_v1",
        _ADAPTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_store():
    spec = importlib.util.spec_from_file_location(
        "lcm030_country_laws_ir_duckdb_store",
        _STORE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture(columns: tuple[str, ...]) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "law-fixture-1",
        "title": "Example statute",
        "text": "The fixture body is present.",
        "source_url": "http://example.invalid/laws/1",
        "note": "kept extra",
    }
    for column in columns:
        row.setdefault(column, f"value-{column}")
    return row


def test_adapter_emits_law_kind_and_keeps_schema_and_shard_lookup() -> None:
    schema_version = _string(_PACKAGE_PATH, "SCHEMA_VERSION")
    columns = _columns(_SCHEMA_PATH, "REQUIRED_LAW_COLUMNS")
    assert schema_version == "country-laws-ir-graphrag/v1"
    assert columns == ("id", "title", "text")
    query_before = _QUERY_PATH.read_bytes()
    store_before = _STORE_PATH.read_bytes()
    store = _load_store()
    shard_lookup = store.document_shard_paths
    adapter = _load_adapter()
    source = _fixture(columns)
    snapshot = dict(source)
    calls: list[str] = []
    real_socket = socket.socket

    def _refuse_socket(*_args: object, **_kwargs: object) -> object:
        calls.append("socket")
        raise AssertionError("adapter opened a socket")

    socket.socket = _refuse_socket  # type: ignore[method-assign]
    try:
        record = adapter.adapt_country_laws_ir_row(source)
    finally:
        socket.socket = real_socket  # type: ignore[method-assign]
    assert calls == []
    assert record.interface_id == "legal-corpus.law@1"
    assert record.interface_id == adapter.INTERFACE_ID
    assert record.source_schema_version == "country-laws-ir-graphrag/v1"
    assert record.source_schema_version == adapter.SOURCE_SCHEMA_VERSION
    assert record.source_schema_version == schema_version
    assert record.instrument.source_schema_version == schema_version
    assert record.instrument.kind == "law"
    assert list(record.source_row) == list(snapshot)
    assert dict(record.source_row) == snapshot
    assert source == snapshot
    for column in columns:
        assert record.source_row[column] == snapshot[column]
    assert store.document_shard_paths is shard_lookup
    assert store.document_shard_paths.__code__.co_filename == str(_STORE_PATH)
    assert _QUERY_PATH.read_bytes() == query_before
    assert _STORE_PATH.read_bytes() == store_before
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(_ADAPTER_PATH))
    imported: list[str] = []
    defined: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.append(target.id)
    assert "document_shard_paths" not in defined
    for name in imported:
        parts = name.split(".")
        assert "query" not in parts
        assert "duckdb_store" not in parts
        assert "socket" not in parts
        assert "urllib" not in parts
        assert "requests" not in parts
        assert parts[0] != "http"


def test_fixture_missing_register_column_is_rejected() -> None:
    adapter = _load_adapter()
    columns = _columns(_SCHEMA_PATH, "REQUIRED_LAW_COLUMNS")
    missing = _fixture(columns)
    del missing["text"]
    try:
        adapter.adapt_country_laws_ir_row(missing)
    except adapter.LawRejected as exc:
        assert "missing required column text" in str(exc)
    else:
        raise AssertionError("a fixture without text was accepted")
