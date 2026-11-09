"""LCM-038: map an RII fixture onto legal-corpus.caselaw@1."""

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
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_rii_v1.py"
)
_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/caselaw_v1.py"
)
_RII_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_de_rii.py"
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
    "pyarrow",
    "subprocess",
    "collect_de_rii",
    "collect_gii",
    "catalog",
)
_BANNED_CALLS = (
    "snapshot_download",
    "subprocess",
    "HfApi",
    "git checkout",
    "justicedao/ipfs_germany_laws_ir",
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


def _gii_identity(found: object) -> str:
    module = getattr(found, "module", found)
    filename = getattr(found, "filename", "")
    if module == "collect_gii" and (filename in {"", "collect_gii.py"}):
        return "collect_gii"
    if isinstance(module, str) and module in {"collect_gii", "collect_gii.py"}:
        return "collect_gii"
    raise AssertionError(f"Germany lookup is {module!r} {filename!r}")


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


def test_rii_rows_keep_the_schema_id_and_gii_route() -> None:
    rii_before = _RII_PATH.read_bytes()
    catalog_before = _CATALOG_PATH.read_bytes()
    kind_before = _KIND_PATH.read_bytes()
    statute_before = _STATUTE_PATH.read_bytes()
    adapter_text = _ADAPTER_PATH.read_text(encoding="utf-8")
    assert _assignment(_RII_PATH, "SCHEMA_VERSION") is None
    assert "collect_gii" not in _functions(_RII_PATH)
    assert "collect_gii" not in _functions(_ADAPTER_PATH)
    assert "get" not in _functions(_ADAPTER_PATH)
    statute_id = _string(_STATUTE_PATH, "SCHEMA_VERSION")
    assert statute_id == "country-laws-ir-graphrag/v1"
    for name in _imports(_ADAPTER_PATH):
        for banned in _BANNED_IMPORTS:
            assert banned not in name
    for banned in _BANNED_CALLS:
        assert banned not in adapter_text

    catalog_functions = _functions(_CATALOG_PATH)
    catalog = _load(_CATALOG_PATH, "lcm038_national_catalog")
    germany = catalog.get_national_collector("de")
    assert _gii_identity(germany) == "collect_gii"
    assert germany.filename == "collect_gii.py"
    assert germany.module == "collect_gii"
    assert catalog.BY_ISO["de"][0].module == "collect_gii"
    assert any(item.module == "collect_de_rii" for item in catalog.BY_ISO["de"])
    assert all(item.module != "caselaw_rii_v1" for item in catalog.COLLECTORS)
    assert all(item.module != "collect_gii" or item.filename == "collect_gii.py" for item in catalog.COLLECTORS)
    assert all(
        item.module != "collect_de_rii" or item.filename == "collect_de_rii.py"
        for item in catalog.COLLECTORS
    )
    if "get" in catalog_functions:
        assert _gii_identity(catalog.get("de")) == "collect_gii"

    adapter = _load(_ADAPTER_PATH, "lcm038_caselaw_rii_v1")
    kind = _load(_KIND_PATH, "lcm038_caselaw_kind_for_test")
    assert adapter.INTERFACE_ID == "legal-corpus.caselaw@1"
    assert adapter.RII_SCHEMA_ID == "unversioned"
    assert adapter.RII_SCHEMA_ID == kind.SOURCE_SCHEMA_IDS["rii"]
    assert adapter.RII_COLUMNS == kind.RII_COLUMNS
    assert adapter.RII_COLUMNS[-4:] == ("rii_doknr", "doctype", "norm", "config")
    assert "rii_doknr" in adapter.RII_COLUMNS
    assert "dila_id" not in adapter.RII_COLUMNS
    assert adapter.RII_CONFIG == "de_bund"
    assert adapter.RII_CONFIG != adapter.RII_SCHEMA_ID
    assert adapter.RII_JURISDICTION == "de"
    assert adapter.LIC == _string(_RII_PATH, "LIC")
    assert adapter.GII_MODULE == "collect_gii"
    assert adapter.CaselawRiiAdapter.schema_id == adapter.RII_SCHEMA_ID
    assert not hasattr(adapter.CaselawRiiAdapter, "collect_gii")
    assert "collect_gii" not in _functions(_ADAPTER_PATH)

    def _adapt() -> None:
        row = {"source_schema_id": adapter.RII_SCHEMA_ID}
        values = {
            "ecli": "ECLI:DE:BGH:2020:FIXTURE",
            "jurisdiction": adapter.RII_JURISDICTION,
            "court": "BGH 1. Senat",
            "chamber": "1. Senat",
            "date": "2020-01-15",
            "number": "1 StR 1/20",
            "title": "Fixture decision",
            "text": "Leitsatz\nThe fixture decision body.",
            "source_url": "https://example.test/rii/1",
            "archive_name": None,
            "is_archive": False,
            "licence": adapter.LIC,
            "retrieved_at": "2020-01-16T00:00:00Z",
            "court_id": None,
            "rii_doknr": "KORE000000000",
            "doctype": "Urteil",
            "norm": "BGB",
            "config": adapter.RII_CONFIG,
        }
        assert tuple(values) == adapter.RII_COLUMNS
        for key in adapter.RII_COLUMNS:
            row[key] = values[key]
        snapshot = dict(row)
        record = adapter.CaselawRiiAdapter().adapt(row)
        assert record.interface_id == "legal-corpus.caselaw@1"
        assert record.interface_id == adapter.INTERFACE_ID
        assert record.source_name == "rii"
        assert record.source_schema_id == "unversioned"
        assert record.source_schema_id == adapter.RII_SCHEMA_ID
        assert record.instrument.kind == "caselaw"
        assert record.instrument.source_schema_id == adapter.RII_SCHEMA_ID
        assert record.instrument.source_schema_version == adapter.RII_SCHEMA_ID
        assert record.instrument.source_dataset == (
            "legal_scrapers/national_collectors/collect_de_rii.py"
        )
        assert "collect_gii" not in record.instrument.source_dataset
        assert dict(record.source_row) == snapshot
        assert tuple(record.columns) == adapter.RII_COLUMNS
        assert record.columns["rii_doknr"] == "KORE000000000"
        assert record.columns["doctype"] == "Urteil"
        assert record.columns["norm"] == "BGB"
        assert record.columns["config"] == "de_bund"
        assert record.columns["text"] == "Leitsatz\nThe fixture decision body."
        assert record.columns["jurisdiction"] == "de"
        assert "source_schema_id" not in record.columns
        assert row == snapshot
        row["text"] = "changed"
        assert record.columns["text"] == "Leitsatz\nThe fixture decision body."
        assert record.source_row["text"] == "Leitsatz\nThe fixture decision body."
        with pytest.raises(TypeError):
            record.columns["text"] = "rewritten"
        with pytest.raises(TypeError):
            record.source_row["text"] = "rewritten"

        bare = {key: values[key] for key in adapter.RII_COLUMNS}
        bare_record = adapter.CaselawRiiAdapter().adapt(bare)
        assert bare_record.source_schema_id == adapter.RII_SCHEMA_ID
        assert bare_record.source_row["source_schema_id"] == "unversioned"
        assert bare_record.columns["rii_doknr"] == bare["rii_doknr"]
        assert "source_schema_id" not in bare

        cap = {
            "source_schema_id": adapter.RII_SCHEMA_ID,
            "opinion_text": "The fixture opinion.",
            "case_id": "cap-fixture-1",
        }
        with pytest.raises(adapter.RiiAdapterRejected) as caught:
            adapter.CaselawRiiAdapter().adapt(cap)
        assert "not an RII fixture" in str(caught.value)

        statute = {"source_schema_id": statute_id}
        for key in adapter.RII_COLUMNS:
            statute[key] = values[key]
        with pytest.raises(adapter.RiiAdapterRejected) as caught:
            adapter.CaselawRiiAdapter().adapt(statute)
        assert "statute" in str(caught.value)

        gii = {"source_schema_id": "collect_gii"}
        for key in adapter.RII_COLUMNS:
            gii[key] = values[key]
        with pytest.raises(adapter.RiiAdapterRejected) as caught:
            adapter.CaselawRiiAdapter().adapt(gii)
        assert "collect_gii" in str(caught.value)

    _without_socket(_adapt)
    assert _RII_PATH.read_bytes() == rii_before
    assert _CATALOG_PATH.read_bytes() == catalog_before
    assert _KIND_PATH.read_bytes() == kind_before
    assert _STATUTE_PATH.read_bytes() == statute_before
    assert germany.module == "collect_gii"
    if "get" in catalog_functions:
        assert _gii_identity(catalog.get("de")) == "collect_gii"
    loaded = [name for name in sys.modules if "collect_de_rii" in name or name.endswith(".catalog")]
    assert loaded == []
