"""LCM-036: map a CAP fixture onto legal-corpus.caselaw@1."""

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
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/caselaw_cap_v1.py"
)
_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/caselaw_v1.py"
)
_CAP_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/caselaw_access_program/vector_search_integration.py"
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
    "vector_search_integration",
    "caselaw_access_program",
    "embeddings",
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


def _class_body(path: Path, class_name: str) -> list[ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return list(node.body)
    raise AssertionError(f"{class_name} missing")


def _class_string(path: Path, class_name: str, field: str) -> str:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field:
            continue
        value = stmt.value
        assert isinstance(value, ast.Constant) and isinstance(value.value, str)
        return value.value
    raise AssertionError(field)


def _class_tuple(path: Path, class_name: str, field: str) -> tuple[str, ...]:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field or not isinstance(stmt.value, ast.Tuple):
            continue
        values: list[str] = []
        for item in stmt.value.elts:
            assert isinstance(item, ast.Constant) and isinstance(item.value, str)
            values.append(item.value)
        return tuple(values)
    raise AssertionError(field)


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


def test_cap_fixture_keeps_the_schema_id_and_opinion_fields() -> None:
    cap_before = _CAP_PATH.read_bytes()
    kind_before = _KIND_PATH.read_bytes()
    assert _assignment(_CAP_PATH, "SCHEMA_VERSION") is None
    dataset_id = _class_string(_CAP_PATH, "CAPVectorSearchConfig", "dataset_id")
    text_fields = _class_tuple(_CAP_PATH, "CAPVectorSearchConfig", "text_field_candidates")
    embedding_fields = _class_tuple(_CAP_PATH, "CAPVectorSearchConfig", "embedding_field_candidates")
    statute_id = _string(_STATUTE_PATH, "SCHEMA_VERSION")
    assert dataset_id == "justicedao/Caselaw_Access_Project_embeddings"
    assert "opinion_text" in text_fields
    assert "case_text" in text_fields
    assert "embedding" in embedding_fields
    assert statute_id == "country-laws-ir-graphrag/v1"
    for name in _imports(_ADAPTER_PATH):
        for banned in _BANNED_IMPORTS:
            assert banned not in name

    adapter = _load(_ADAPTER_PATH, "lcm036_caselaw_cap_v1")
    kind = _load(_KIND_PATH, "lcm036_caselaw_kind_for_test")
    assert adapter.INTERFACE_ID == "legal-corpus.caselaw@1"
    assert adapter.CAP_SCHEMA_ID == "unversioned"
    assert adapter.CAP_SCHEMA_ID == kind.SOURCE_SCHEMA_IDS["cap"]
    assert adapter.CAP_DATASET_ID == dataset_id
    assert adapter.TEXT_FIELDS == text_fields
    assert adapter.EMBEDDING_FIELDS == embedding_fields
    assert adapter.CaselawCapAdapter.schema_id == adapter.CAP_SCHEMA_ID

    def _adapt() -> None:
        row = {
            "source_schema_id": adapter.CAP_SCHEMA_ID,
            "opinion_text": "The fixture opinion.",
            "case_text": "The fixture case text.",
            "case_id": "cap-fixture-1",
            "citation": "1 F. Cas. 1",
            "court": "Example Court",
            "jurisdiction": "us",
            "decision_date": "2020-01-15",
            "docket_number": "1:20-cv-1",
            "reporter": "F. Cas.",
            "cluster_id": "cluster-1",
            "cluster": "cluster-1",
            "model_name": "fixture-model",
            "embedding": [0.25, 0.5],
        }
        snapshot = dict(row)
        record = adapter.CaselawCapAdapter().adapt(row)
        assert record.interface_id == "legal-corpus.caselaw@1"
        assert record.interface_id == adapter.INTERFACE_ID
        assert record.source_name == "cap"
        assert record.source_schema_id == "unversioned"
        assert record.source_schema_id == adapter.CAP_SCHEMA_ID
        assert record.instrument.kind == "caselaw"
        assert record.instrument.source_schema_id == adapter.CAP_SCHEMA_ID
        assert record.instrument.source_schema_version == adapter.CAP_SCHEMA_ID
        assert record.instrument.source_dataset == (
            "legal_scrapers/caselaw_access_program/vector_search_integration.py"
        )
        assert dict(record.source_row) == snapshot
        assert record.opinion_fields["opinion_text"] == "The fixture opinion."
        assert record.opinion_fields["case_text"] == "The fixture case text."
        assert record.opinion_fields["case_id"] == "cap-fixture-1"
        assert record.opinion_fields["citation"] == snapshot["citation"]
        assert record.opinion_fields["court"] == snapshot["court"]
        assert record.opinion_fields["decision_date"] == snapshot["decision_date"]
        assert record.opinion_fields["docket_number"] == snapshot["docket_number"]
        assert record.opinion_fields["reporter"] == snapshot["reporter"]
        assert record.opinion_fields["cluster"] == "cluster-1"
        assert record.opinion_fields["model_name"] == "fixture-model"
        assert "embedding" not in record.opinion_fields
        assert "source_schema_id" not in record.opinion_fields
        assert list(record.source_row["embedding"]) == [0.25, 0.5]
        assert row == snapshot
        row["opinion_text"] = "changed"
        row["embedding"] = [9.0]
        assert record.opinion_fields["opinion_text"] == "The fixture opinion."
        assert record.source_row["opinion_text"] == "The fixture opinion."
        assert list(record.source_row["embedding"]) == [0.25, 0.5]
        with pytest.raises(TypeError):
            record.opinion_fields["opinion_text"] = "rewritten"
        with pytest.raises(TypeError):
            record.source_row["opinion_text"] = "rewritten"

        dila = {"source_schema_id": kind.SOURCE_SCHEMA_IDS["dila"]}
        for key in kind.DILA_COLUMNS:
            dila[key] = False if key == "is_archive" else "dila-fixture"
        with pytest.raises(adapter.CapAdapterRejected) as caught:
            adapter.CaselawCapAdapter().adapt(dila)
        assert "not a CAP fixture" in str(caught.value)

        statute = {
            "source_schema_id": statute_id,
            "opinion_text": "not a statute",
            "case_id": "cap-statute",
        }
        with pytest.raises(adapter.CapAdapterRejected) as caught:
            adapter.CaselawCapAdapter().adapt(statute)
        assert "statute" in str(caught.value)

        dataset_claim = {
            "source_schema_id": dataset_id,
            "opinion_text": "dataset id is not the schema id",
            "case_id": "cap-dataset",
        }
        with pytest.raises(adapter.CapAdapterRejected) as caught:
            adapter.CaselawCapAdapter().adapt(dataset_claim)
        assert "not a schema id" in str(caught.value)

        id_only = {"source_schema_id": adapter.CAP_SCHEMA_ID, "case_id": "cap-no-text"}
        with pytest.raises(adapter.CapAdapterRejected) as caught:
            adapter.CaselawCapAdapter().adapt(id_only)
        assert "no opinion text" in str(caught.value)

    _without_socket(_adapt)
    assert _CAP_PATH.read_bytes() == cap_before
    assert _KIND_PATH.read_bytes() == kind_before
    loaded = [name for name in sys.modules if "vector_search_integration" in name]
    assert loaded == []
