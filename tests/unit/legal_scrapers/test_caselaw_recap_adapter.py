"""LCM-039: map a RECAP fixture onto legal-corpus.caselaw@1."""

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
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_recap_v1.py"
)
_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/caselaw_v1.py"
)
_COURT_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/court_v1.py"
)
_RECAP_PATH = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/recap_archive_scraper.py"
_COURTS_COMMON = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py"
)
_COURTS_UPLOAD = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/upload_world_courts.py"
)
_STATUTE_PATH = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py"
_BANNED_IMPORTS = (
    "requests",
    "httpx",
    "urllib",
    "socket",
    "recap_archive_scraper",
    "court_v1",
    "huggingface_hub",
    "datasets",
    "torch",
    "subprocess",
)
_DOWNLOAD_CALLS = (
    "search_recap_documents",
    "get_recap_document",
    "scrape_recap_archive",
    "urlopen",
    "requests",
)
_SEARCH_VALUES = {
    "id": "recap-fixture-1",
    "docket_id": "docket-fixture-1",
    "case_name": "Fixture v. Example",
    "court": "nysd",
    "court_full_name": "Southern District of New York",
    "document_type": "opinion",
    "document_number": "1",
    "description": "Fixture description",
    "date_filed": "2020-01-15",
    "page_count": 2,
    "pacer_doc_id": "pacer-fixture-1",
    "recap_url": "https://example.test/recap/1",
    "docket_url": "https://example.test/docket/1",
    "plain_text_available": True,
    "pdf_available": False,
    "ocr_status": "unknown",
    "abstract": "Fixture abstract",
}
_DETAIL_VALUES = {
    "id": "recap-fixture-1",
    "docket_id": "docket-fixture-1",
    "case_name": "Fixture v. Example",
    "court": "nysd",
    "document_type": "opinion",
    "date_filed": "2020-01-15",
    "page_count": 2,
    "recap_url": "https://example.test/recap/1",
    "text": "The fixture document body.",
}
_METADATA_VALUES = {
    "pacer_doc_id": "pacer-fixture-1",
    "pacer_case_id": "case-fixture-1",
    "ocr_status": "",
    "plain_text_available": True,
    "pdf_available": False,
    "description": "Fixture description",
    "document_number": "1",
    "docket_number": "1:20-cv-1",
    "docket_url": "https://example.test/docket/1",
    "court_id": "nysd",
    "court_full_name": "Southern District of New York",
}


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


def _call_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _dicts(path: Path, fn_name: str) -> list[tuple[str, ...]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != fn_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Dict):
                continue
            keys: list[str] = []
            good = True
            for key in child.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    good = False
                    break
                keys.append(key.value)
            if good and keys and tuple(keys) not in found:
                found.append(tuple(keys))
    return found


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _row(columns: tuple[str, ...], values: dict[str, object], schema_id: str) -> dict[str, object]:
    assert set(values) == set(columns)
    row: dict[str, object] = {"source_schema_id": schema_id}
    for key in columns:
        row[key] = values[key]
    return row


def test_recap_fixture_keeps_field_names_and_schema_id() -> None:
    recap_before = _RECAP_PATH.read_bytes()
    kind_before = _KIND_PATH.read_bytes()
    court_before = _COURT_KIND_PATH.read_bytes()
    common_before = _COURTS_COMMON.read_bytes()
    upload_before = _COURTS_UPLOAD.read_bytes()
    statute_before = _STATUTE_PATH.read_bytes()
    assert _assignment(_RECAP_PATH, "SCHEMA_VERSION") is None
    for name in _DOWNLOAD_CALLS:
        assert name not in _functions(_ADAPTER_PATH)
    for name in _imports(_ADAPTER_PATH):
        for banned in _BANNED_IMPORTS:
            assert banned not in name
    for name in _call_names(_ADAPTER_PATH):
        assert name not in _DOWNLOAD_CALLS
    statute_id = _string(_STATUTE_PATH, "SCHEMA_VERSION")
    court_interface = _string(_COURT_KIND_PATH, "INTERFACE_ID")
    assert statute_id == "country-laws-ir-graphrag/v1"
    assert court_interface == "legal-corpus.court@1"

    search_dicts = [keys for keys in _dicts(_RECAP_PATH, "search_recap_documents") if "abstract" in keys]
    detail_dicts = [keys for keys in _dicts(_RECAP_PATH, "get_recap_document") if "metadata" in keys]
    metadata_dicts = [keys for keys in _dicts(_RECAP_PATH, "get_recap_document") if "court_id" in keys]
    assert len(search_dicts) == 1
    assert len(detail_dicts) == 1
    assert len(metadata_dicts) == 1

    adapter = _load(_ADAPTER_PATH, "lcm039_caselaw_recap_v1")
    kind = _load(_KIND_PATH, "lcm039_caselaw_kind_for_test")
    assert adapter.RECAP_SEARCH_COLUMNS == search_dicts[0]
    assert adapter.RECAP_DETAIL_COLUMNS == detail_dicts[0]
    assert adapter.RECAP_METADATA_COLUMNS == metadata_dicts[0]
    assert adapter.RECAP_SEARCH_COLUMNS == kind.RECAP_SEARCH_COLUMNS
    assert adapter.RECAP_DETAIL_COLUMNS == kind.RECAP_DETAIL_COLUMNS
    assert adapter.RECAP_SCHEMA_ID == "unversioned"
    assert adapter.RECAP_SCHEMA_ID == kind.SOURCE_SCHEMA_IDS["recap_search"]
    assert adapter.RECAP_SCHEMA_ID == kind.SOURCE_SCHEMA_IDS["recap_detail"]
    assert adapter.INTERFACE_ID == "legal-corpus.caselaw@1"
    assert adapter.COURT_INTERFACE_ID == court_interface
    assert adapter.INTERFACE_ID != adapter.COURT_INTERFACE_ID
    assert "abstract" in adapter.RECAP_SEARCH_COLUMNS
    assert "abstract" not in adapter.RECAP_DETAIL_COLUMNS
    assert "metadata" in adapter.RECAP_DETAIL_COLUMNS
    assert "court_id" in adapter.RECAP_METADATA_COLUMNS
    assert "court_id" not in adapter.RECAP_SEARCH_COLUMNS
    assert "docket_number" in adapter.RECAP_METADATA_COLUMNS
    assert adapter.RECAP_METADATA_COLUMNS != adapter.REC_FIELDS
    assert adapter.RECAP_DETAIL_COLUMNS != adapter.FLAT_COURT_FIELDS
    assert "name" in adapter.REC_FIELDS
    assert "record_type" in adapter.REC_FIELDS
    assert "name" not in adapter.RECAP_METADATA_COLUMNS
    assert adapter.CaselawRecapAdapter.schema_id == adapter.RECAP_SCHEMA_ID
    assert not hasattr(adapter.CaselawRecapAdapter, "scrape_recap_archive")

    def _adapt() -> None:
        search = _row(adapter.RECAP_SEARCH_COLUMNS, _SEARCH_VALUES, adapter.RECAP_SCHEMA_ID)
        metadata = {key: _METADATA_VALUES[key] for key in adapter.RECAP_METADATA_COLUMNS}
        assert tuple(metadata) == adapter.RECAP_METADATA_COLUMNS
        detail_values = dict(_DETAIL_VALUES)
        detail_values["metadata"] = metadata
        detail = _row(adapter.RECAP_DETAIL_COLUMNS, detail_values, adapter.RECAP_SCHEMA_ID)
        search_snapshot = dict(search)
        detail_snapshot = dict(detail)
        detail_snapshot["metadata"] = dict(metadata)
        search_record = adapter.CaselawRecapAdapter().adapt(search)
        detail_record = adapter.CaselawRecapAdapter().adapt(detail)

        assert search_record.interface_id == "legal-corpus.caselaw@1"
        assert detail_record.interface_id == adapter.INTERFACE_ID
        assert search_record.interface_id != adapter.COURT_INTERFACE_ID
        assert detail_record.interface_id != adapter.COURT_INTERFACE_ID
        assert search_record.source_name == "recap_search"
        assert detail_record.source_name == "recap_detail"
        assert search_record.source_schema_id == "unversioned"
        assert detail_record.source_schema_id == adapter.RECAP_SCHEMA_ID
        assert search_record.instrument.kind == "caselaw"
        assert detail_record.instrument.kind == "caselaw"
        assert search_record.instrument.source_schema_id == adapter.RECAP_SCHEMA_ID
        assert detail_record.instrument.source_schema_version == adapter.RECAP_SCHEMA_ID
        assert search_record.instrument.source_dataset == "legal_scrapers/recap_archive_scraper.py"
        assert detail_record.instrument.source_dataset == search_record.instrument.source_dataset
        assert tuple(search_record.columns) == adapter.RECAP_SEARCH_COLUMNS
        assert tuple(detail_record.columns) == adapter.RECAP_DETAIL_COLUMNS
        assert dict(search_record.source_row) == search_snapshot
        assert dict(search_record.columns) == _SEARCH_VALUES
        assert dict(detail_record.source_row) == detail_snapshot
        assert detail_record.columns["text"] == "The fixture document body."
        assert tuple(detail_record.columns["metadata"]) == adapter.RECAP_METADATA_COLUMNS
        assert dict(detail_record.columns["metadata"]) == metadata
        assert search_record.columns["court"] == "nysd"
        assert search_record.columns["court_full_name"] == "Southern District of New York"
        assert search_record.court_reference == {
            "court": "nysd",
            "court_full_name": "Southern District of New York",
        }
        assert detail_record.court_reference == {
            "court": "nysd",
            "court_id": "nysd",
            "court_full_name": "Southern District of New York",
        }
        for record in (search_record, detail_record):
            assert set(record.court_reference) <= {"court", "court_full_name", "court_id"}
            assert "name" not in record.court_reference
            assert "record_type" not in record.court_reference
            assert "level" not in record.court_reference
            assert all(isinstance(value, str) for value in record.court_reference.values())
            assert not hasattr(record, "court_record")
        assert search == search_snapshot
        assert detail["metadata"] == metadata
        search["abstract"] = "changed"
        assert search_record.columns["abstract"] == "Fixture abstract"
        with pytest.raises(TypeError):
            search_record.columns["court"] = "rewritten"
        with pytest.raises(TypeError):
            search_record.court_reference["court"] = "rewritten"
        with pytest.raises(TypeError):
            search_record.source_row["court"] = "rewritten"

        bare = {key: _SEARCH_VALUES[key] for key in adapter.RECAP_SEARCH_COLUMNS}
        bare_record = adapter.CaselawRecapAdapter().adapt(bare)
        assert bare_record.source_schema_id == adapter.RECAP_SCHEMA_ID
        assert bare_record.source_row["source_schema_id"] == "unversioned"
        assert bare_record.columns["abstract"] == bare["abstract"]
        assert "source_schema_id" not in bare

        copied = _row(adapter.RECAP_SEARCH_COLUMNS, _SEARCH_VALUES, adapter.RECAP_SCHEMA_ID)
        copied["court"] = {
            "court_id": "nysd",
            "name": "Southern District of New York",
            "record_type": "courthouse",
            "level": "other",
            "court_system": "national",
        }
        with pytest.raises(adapter.RecapAdapterRejected) as caught:
            adapter.CaselawRecapAdapter().adapt(copied)
        assert "copied court module row" in str(caught.value)

        nested = _row(adapter.RECAP_DETAIL_COLUMNS, detail_values, adapter.RECAP_SCHEMA_ID)
        nested_metadata = dict(metadata)
        nested_metadata["court_id"] = {
            "court_id": "nysd",
            "name": "Southern District of New York",
            "record_type": "courthouse",
        }
        nested["metadata"] = nested_metadata
        with pytest.raises(adapter.RecapAdapterRejected) as caught:
            adapter.CaselawRecapAdapter().adapt(nested)
        assert "copied court module row" in str(caught.value)

        merged = _row(adapter.RECAP_SEARCH_COLUMNS, _SEARCH_VALUES, adapter.RECAP_SCHEMA_ID)
        merged["metadata"] = dict(metadata)
        merged["text"] = "The fixture document body."
        with pytest.raises(adapter.RecapAdapterRejected) as caught:
            adapter.CaselawRecapAdapter().adapt(merged)
        assert "not a RECAP fixture" in str(caught.value)

        statute = _row(adapter.RECAP_SEARCH_COLUMNS, _SEARCH_VALUES, statute_id)
        with pytest.raises(adapter.RecapAdapterRejected) as caught:
            adapter.CaselawRecapAdapter().adapt(statute)
        assert "statute" in str(caught.value)

        court_schema = _row(adapter.RECAP_SEARCH_COLUMNS, _SEARCH_VALUES, court_interface)
        with pytest.raises(adapter.RecapAdapterRejected) as caught:
            adapter.CaselawRecapAdapter().adapt(court_schema)
        assert "court module" in str(caught.value)

    _without_socket(_adapt)
    assert _RECAP_PATH.read_bytes() == recap_before
    assert _KIND_PATH.read_bytes() == kind_before
    assert _COURT_KIND_PATH.read_bytes() == court_before
    assert _COURTS_COMMON.read_bytes() == common_before
    assert _COURTS_UPLOAD.read_bytes() == upload_before
    assert _STATUTE_PATH.read_bytes() == statute_before


