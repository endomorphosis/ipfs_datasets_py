"""LCM-037: map a DILA fixture onto legal-corpus.caselaw@1."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

import pytest

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_dila_v1.py"
)
_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/caselaw_v1.py"
)
_DILA_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_fr_dila.py"
)
_CATALOG_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/national_collectors/catalog.py"
)
_STATUTE_PATH = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py"
_BANNED_IMPORTS = (
    "huggingface_hub",
    "datasets",
    "torch",
    "requests",
    "httpx",
    "urllib",
    "socket",
    "lxml",
    "collect_fr_dila",
    "collect_legi",
    "catalog",
)


def _assignment(path: Path, name: str) -> ast.AST | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: ast.AST | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
            value = node.value
        else:
            continue
        if value is None:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            assert found is None
            found = value
    return found


def _string(path: Path, name: str) -> str:
    value = _assignment(path, name)
    assert isinstance(value, ast.Constant) and isinstance(value.value, str)
    return value.value


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _legi_identity(found: object) -> str:
    module = getattr(found, "module", found)
    filename = getattr(found, "filename", "")
    if module == "collect_legi" and (filename in {"", "collect_legi.py"}):
        return "collect_legi"
    if isinstance(module, str) and module in {"collect_legi", "collect_legi.py"}:
        return "collect_legi"
    raise AssertionError(f"France lookup is {module!r} {filename!r}")


def _without_socket(callback):
    calls: list[str] = []
    real_socket = socket.socket

    def _refuse_socket(*_args: object, **_kwargs: object) -> object:
        calls.append("socket")
        raise AssertionError("adapter opened a socket")

    socket.socket = _refuse_socket  # type: ignore[method-assign]
    try:
        callback()
    finally:
        socket.socket = real_socket  # type: ignore[method-assign]
    assert calls == []


def test_dila_rows_keep_the_schema_id_and_legi_route() -> None:
    dila_before = _DILA_PATH.read_bytes()
    catalog_before = _CATALOG_PATH.read_bytes()
    kind_before = _KIND_PATH.read_bytes()
    assert _assignment(_DILA_PATH, "SCHEMA_VERSION") is None
    assert "collect_legi" not in _functions(_DILA_PATH)
    assert "collect_legi" not in _functions(_ADAPTER_PATH)
    assert "get" not in _functions(_ADAPTER_PATH)
    statute_id = _string(_STATUTE_PATH, "SCHEMA_VERSION")
    assert statute_id == "country-laws-ir-graphrag/v1"
    for name in _imports(_ADAPTER_PATH):
        for banned in _BANNED_IMPORTS:
            assert banned not in name

    catalog_functions = _functions(_CATALOG_PATH)
    catalog = _load(_CATALOG_PATH, "lcm037_national_catalog")
    france = catalog.get_national_collector("fr")
    assert _legi_identity(france) == "collect_legi"
    assert france.filename == "collect_legi.py"
    assert france.module == "collect_legi"
    assert catalog.BY_ISO["fr"][0].module == "collect_legi"
    assert any(item.module == "collect_fr_dila" for item in catalog.BY_ISO["fr"])
    assert all(item.module != "caselaw_dila_v1" for item in catalog.COLLECTORS)
    assert all(item.module != "collect_legi" or item.filename == "collect_legi.py" for item in catalog.COLLECTORS)
    if "get" in catalog_functions:
        assert _legi_identity(catalog.get("fr")) == "collect_legi"

    adapter = _load(_ADAPTER_PATH, "lcm037_caselaw_dila_v1")
    kind = _load(_KIND_PATH, "lcm037_caselaw_kind_for_test")
    assert adapter.INTERFACE_ID == "legal-corpus.caselaw@1"
    assert adapter.DILA_SCHEMA_ID == "unversioned"
    assert adapter.DILA_SCHEMA_ID == kind.SOURCE_SCHEMA_IDS["dila"]
    assert adapter.DILA_COLUMNS == kind.DILA_COLUMNS
    assert adapter.DILA_COLUMNS[-2:] == ("dila_id", "config")
    assert "dila_id" in adapter.DILA_COLUMNS
    assert adapter.FONDS["CASS"] == "fr_cass"
    assert adapter.FONDS["CASS"] != adapter.DILA_SCHEMA_ID
    assert adapter.LEGI_MODULE == "collect_legi"
    assert adapter.CaselawDilaAdapter.schema_id == adapter.DILA_SCHEMA_ID
    assert not hasattr(adapter.CaselawDilaAdapter, "collect_legi")
    assert "collect_legi" not in _functions(_ADAPTER_PATH)

    def _adapt() -> None:
        row = {"source_schema_id": adapter.DILA_SCHEMA_ID}
        values = {
            "ecli": "ECLI:FR:CCASS:2020:FIXTURE",
            "jurisdiction": "FR",
            "court": "Cour de cassation",
            "chamber": "civile",
            "date": "2020-01-15",
            "number": "19-12.345",
            "title": "Fixture decision",
            "text": "The fixture decision body.",
            "source_url": "https://example.test/dila/1",
            "archive_name": "CASS_fixture.tar.gz",
            "is_archive": False,
            "licence": "Licence Ouverte 2.0",
            "retrieved_at": "2020-01-16T00:00:00+00:00",
            "court_id": None,
            "dila_id": "CASS-fixture",
            "config": adapter.FONDS["CASS"],
        }
        assert tuple(values) == adapter.DILA_COLUMNS
        for key in adapter.DILA_COLUMNS:
            row[key] = values[key]
        snapshot = dict(row)
        record = adapter.CaselawDilaAdapter().adapt(row)
        assert record.interface_id == "legal-corpus.caselaw@1"
        assert record.interface_id == adapter.INTERFACE_ID
        assert record.source_name == "dila"
        assert record.source_schema_id == "unversioned"
        assert record.source_schema_id == adapter.DILA_SCHEMA_ID
        assert record.instrument.kind == "caselaw"
        assert record.instrument.source_schema_id == adapter.DILA_SCHEMA_ID
        assert record.instrument.source_schema_version == adapter.DILA_SCHEMA_ID
        assert record.instrument.source_dataset == (
            "legal_scrapers/national_collectors/collect_fr_dila.py"
        )
        assert "collect_legi" not in record.instrument.source_dataset
        assert dict(record.source_row) == snapshot
        assert tuple(record.columns) == adapter.DILA_COLUMNS
        assert record.columns["dila_id"] == "CASS-fixture"
        assert record.columns["text"] == "The fixture decision body."
        assert record.columns["config"] == "fr_cass"
        assert record.columns["jurisdiction"] == "FR"
        assert "source_schema_id" not in record.columns
        assert row == snapshot
        row["text"] = "changed"
        assert record.columns["text"] == "The fixture decision body."
        assert record.source_row["text"] == "The fixture decision body."
        with pytest.raises(TypeError):
            record.columns["text"] = "rewritten"
        with pytest.raises(TypeError):
            record.source_row["text"] = "rewritten"

        bare = {key: values[key] for key in adapter.DILA_COLUMNS}
        bare_record = adapter.CaselawDilaAdapter().adapt(bare)
        assert bare_record.source_schema_id == adapter.DILA_SCHEMA_ID
        assert bare_record.source_row["source_schema_id"] == "unversioned"
        assert bare_record.columns["dila_id"] == bare["dila_id"]
        assert "source_schema_id" not in bare

        cap = {
            "source_schema_id": adapter.DILA_SCHEMA_ID,
            "opinion_text": "The fixture opinion.",
            "case_id": "cap-fixture-1",
        }
        with pytest.raises(adapter.DilaAdapterRejected) as caught:
            adapter.CaselawDilaAdapter().adapt(cap)
        assert "not a DILA fixture" in str(caught.value)

        statute = {"source_schema_id": statute_id}
        for key in adapter.DILA_COLUMNS:
            statute[key] = values[key]
        with pytest.raises(adapter.DilaAdapterRejected) as caught:
            adapter.CaselawDilaAdapter().adapt(statute)
        assert "statute" in str(caught.value)

        legi = {"source_schema_id": "collect_legi"}
        for key in adapter.DILA_COLUMNS:
            legi[key] = values[key]
        with pytest.raises(adapter.DilaAdapterRejected) as caught:
            adapter.CaselawDilaAdapter().adapt(legi)
        assert "collect_legi" in str(caught.value)

    _without_socket(_adapt)
    assert _DILA_PATH.read_bytes() == dila_before
    assert _CATALOG_PATH.read_bytes() == catalog_before
    assert _KIND_PATH.read_bytes() == kind_before
    assert france.module == "collect_legi"
    if "get" in catalog_functions:
        assert _legi_identity(catalog.get("fr")) == "collect_legi"
    loaded = [name for name in sys.modules if "collect_fr_dila" in name or name.endswith(".catalog")]
    assert loaded == []
