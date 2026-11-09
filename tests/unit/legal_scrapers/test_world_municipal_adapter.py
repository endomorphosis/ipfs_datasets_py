"""LCM-031: a 19-column municipal row plus one trailing provenance column."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/world_municipal_v1.py"
)
_SCHEMA_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/world_municipal/schema.py"
)

_NINETEEN = (
    "cid",
    "jurisdiction_id",
    "jurisdiction_name",
    "country",
    "doc_id",
    "regeling_id",
    "regeling_work_id",
    "doc_order",
    "title",
    "structural_path",
    "node_label",
    "html_title",
    "html",
    "text",
    "source_url",
    "xml_url",
    "date_effective",
    "date_modified",
    "retrieved",
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


def _columns(path: Path, name: str) -> tuple[str, ...]:
    value = _assignment(path, name)
    assert isinstance(value, (ast.List, ast.Tuple))
    columns: list[str] = []
    for item in value.elts:
        assert isinstance(item, ast.Constant) and isinstance(item.value, str)
        columns.append(item.value)
    return tuple(columns)


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            assert isinstance(segment, str) and segment
            return segment
    raise AssertionError(f"{name} missing from {path}")


def _trailing_provenance_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "appends ``"
    start = text.find(marker)
    assert start >= 0
    rest = text[start + len(marker):]
    end = rest.find("``")
    assert end > 0
    return rest[:end]


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "lcm031_world_municipal_v1",
        _ADAPTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture(columns: tuple[str, ...], provenance: str) -> dict[str, object]:
    row: dict[str, object] = {}
    for name in columns:
        row[name] = 0 if name == "doc_order" else f"value-{name}"
    row[provenance] = "kept provenance"
    return row


def test_fixture_with_trailing_provenance_emits_municipal_instrument() -> None:
    columns = _columns(_SCHEMA_PATH, "EXPECTED_COLUMNS")
    provenance = _trailing_provenance_name(_SCHEMA_PATH)
    assert columns == _NINETEEN
    assert len(columns) == 19
    assert provenance == "tipo"
    schema_bytes = _SCHEMA_PATH.read_bytes()
    build_schema = _function_source(_SCHEMA_PATH, "build_schema")
    assert build_schema.startswith("def build_schema(")
    adapter = _load_adapter()
    assert adapter.EXPECTED_COLUMNS == columns
    assert adapter.SOURCE_SCHEMA_VERSION == "world_municipal/schema.py"
    assert adapter.SOURCE_SCHEMA_FILE == "world_municipal/schema.py"
    source = _fixture(columns, provenance)
    snapshot = dict(source)
    calls: list[str] = []
    real_socket = socket.socket

    def _refuse_socket(*_args: object, **_kwargs: object) -> object:
        calls.append("socket")
        raise AssertionError("adapter opened a socket")

    socket.socket = _refuse_socket  # type: ignore[method-assign]
    try:
        record = adapter.adapt_world_municipal_row(source)
    finally:
        socket.socket = real_socket  # type: ignore[method-assign]
    assert calls == []
    assert record.interface_id == "legal-corpus.municipal-instrument@1"
    assert record.interface_id == adapter.INTERFACE_ID
    assert record.instrument.kind == "municipal_instrument"
    assert record.instrument.source_schema_version == "world_municipal/schema.py"
    assert record.instrument.source_schema_version == adapter.SOURCE_SCHEMA_VERSION
    assert record.instrument.source_schema_id == "world_municipal/schema.py"
    assert "world_municipal/schema.py" in record.instrument.source_schema_version
    assert tuple(record.source_row)[:19] == columns
    assert tuple(record.source_row)[-1] == provenance
    assert record.source_row[provenance] == "kept provenance"
    assert type(record.source_row["doc_order"]) is int
    assert record.doc_order == 0
    assert dict(record.source_row) == snapshot
    assert source == snapshot
    source["title"] = "changed"
    assert record.source_row["title"] == "value-title"
    assert _SCHEMA_PATH.read_bytes() == schema_bytes
    assert _function_source(_SCHEMA_PATH, "build_schema") == build_schema
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(_ADAPTER_PATH))
    imported: list[str] = []
    called: list[str] = []
    defined: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.append(func.id)
            elif isinstance(func, ast.Attribute):
                called.append(func.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.append(node.name)
    assert "build_schema" not in defined
    assert "build_schema" not in called
    for banned in ("upload", "push_to_hub", "write_html_parquet"):
        assert banned not in defined
        assert banned not in called
    for name in imported:
        parts = name.split(".")
        for banned in (
            "pyarrow",
            "world_municipal",
            "schema",
            "parquet_io",
            "huggingface_hub",
            "datasets",
            "requests",
            "urllib",
            "socket",
            "http",
        ):
            assert banned not in parts


def test_reordered_column_is_rejected() -> None:
    adapter = _load_adapter()
    columns = _columns(_SCHEMA_PATH, "EXPECTED_COLUMNS")
    provenance = _trailing_provenance_name(_SCHEMA_PATH)
    source = _fixture(columns, provenance)
    items = list(source.items())
    items[0], items[1] = items[1], items[0]
    schema_bytes = _SCHEMA_PATH.read_bytes()
    build_schema = _function_source(_SCHEMA_PATH, "build_schema")
    try:
        adapter.adapt_world_municipal_row(dict(items))
    except adapter.MunicipalRejected as exc:
        assert "only allowed after those 19" in str(exc)
    else:
        raise AssertionError("a reordered column was accepted")
    inserted = list(source.items())
    extra = inserted.pop()
    inserted.insert(3, extra)
    try:
        adapter.adapt_world_municipal_row(dict(inserted))
    except adapter.MunicipalRejected as exc:
        assert "only allowed after those 19" in str(exc)
    else:
        raise AssertionError("a provenance column inserted into the 19 was accepted")
    assert _SCHEMA_PATH.read_bytes() == schema_bytes
    assert _function_source(_SCHEMA_PATH, "build_schema") == build_schema
