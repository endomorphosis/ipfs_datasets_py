"""LCM-040: build legal-corpus.court@1 from court-register identifier fields."""

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
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/court_v1.py"
)
_COURT_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/court_v1.py"
)
_CASELAW_KIND_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/caselaw_v1.py"
)
_COURTS_COMMON = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py"
)
_COURTS_UPLOAD = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/upload_world_courts.py"
)
_STATUTE_PATH = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/__init__.py"
_IDENTIFIER_FIELDS = (
    "court_id",
    "name",
    "name_local",
    "level",
    "court_system",
    "country_code",
    "subdivision",
    "jurisdiction",
    "parent_court_id",
    "record_type",
)
_BANNED_IMPORTS = (
    "caselaw_v1",
    "requests",
    "httpx",
    "urllib",
    "socket",
    "huggingface_hub",
    "torch",
    "subprocess",
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


def _names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found.add(target.id)
    return found


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


def _function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} missing from {path}")


def _dict_call_keywords(fn: ast.AST, required: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "dict" or required not in {item.arg for item in node.keywords}:
            continue
        names = tuple(item.arg for item in node.keywords if item.arg)
        if names not in matches:
            matches.append(names)
    assert len(matches) == 1
    return matches[0]


def _return_keys(fn: ast.AST, required: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys: list[str] = []
        good = True
        for key in node.value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                good = False
                break
            keys.append(key.value)
        if good and required in keys and tuple(keys) not in matches:
            matches.append(tuple(keys))
    assert len(matches) == 1
    return matches[0]


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


def test_court_adapter_builds_court_identity_and_drops_opinion_text() -> None:
    common_before = _COURTS_COMMON.read_bytes()
    upload_before = _COURTS_UPLOAD.read_bytes()
    court_before = _COURT_KIND_PATH.read_bytes()
    caselaw_before = _CASELAW_KIND_PATH.read_bytes()
    statute_before = _STATUTE_PATH.read_bytes()
    assert "SCHEMA_VERSION" not in _names(_COURTS_COMMON)
    assert "SCHEMA_VERSION" not in _names(_COURTS_UPLOAD)
    for name in _imports(_ADAPTER_PATH):
        for banned in _BANNED_IMPORTS:
            assert banned not in name
    assert "accept_caselaw_row" not in _call_names(_ADAPTER_PATH)
    rec_fields = _dict_call_keywords(_function(_COURTS_COMMON, "rec"), "court_id")
    flat_fields = _return_keys(_function(_COURTS_UPLOAD, "flat_court"), "court_id")
    for name in _IDENTIFIER_FIELDS:
        assert name in rec_fields
    assert "name_local" not in flat_fields
    for name in _IDENTIFIER_FIELDS:
        if name != "name_local":
            assert name in flat_fields
    assert "text" not in rec_fields
    assert "text" not in flat_fields

    adapter = _load(_ADAPTER_PATH, "lcm040_court_v1")
    court_kind = _load(_COURT_KIND_PATH, "lcm040_court_kind_for_test")
    caselaw_kind = _load(_CASELAW_KIND_PATH, "lcm040_caselaw_kind_for_test")
    schema_id = _string(_COURT_KIND_PATH, "UNVERSIONED_SCHEMA_ID")
    interface_id = _string(_COURT_KIND_PATH, "INTERFACE_ID")
    caselaw_interface = _string(_CASELAW_KIND_PATH, "INTERFACE_ID")
    statute_id = _string(_STATUTE_PATH, "SCHEMA_VERSION")
    repo = _string(_COURTS_UPLOAD, "DS")
    assert schema_id == adapter.SOURCE_SCHEMA_ID == court_kind.SOURCE_SCHEMA_ID
    assert interface_id == "legal-corpus.court@1"
    assert adapter.INTERFACE_ID == interface_id == court_kind.INTERFACE_ID
    assert caselaw_interface == "legal-corpus.caselaw@1"
    assert adapter.CASELAW_INTERFACE_ID == caselaw_interface
    assert adapter.INTERFACE_ID != adapter.CASELAW_INTERFACE_ID
    assert statute_id == adapter.STATUTE_SCHEMA_ID == court_kind.STATUTE_SCHEMA_ID
    assert repo == adapter.WORLD_COURTS_REPO == court_kind.WORLD_COURTS_REPO
    assert adapter.SOURCE_SCHEMA_ID != repo
    assert adapter.SOURCE_SCHEMA_ID != statute_id
    assert adapter.IDENTIFIER_FIELDS == _IDENTIFIER_FIELDS
    assert adapter.REC_FIELDS == rec_fields == court_kind.REC_FIELDS
    assert adapter.FLAT_COURT_FIELDS == flat_fields == court_kind.FLAT_COURT_FIELDS
    assert adapter.OPINION_BODY_FIELDS == ("text", "opinion_text", "case_text")
    assert adapter.OPINION_BODY_FIELDS == court_kind.OPINION_BODY_FIELDS
    assert set(adapter.IDENTIFIER_FIELDS).isdisjoint(adapter.OPINION_BODY_FIELDS)
    assert adapter.CourtAdapter.interface_id == interface_id
    assert adapter.CourtAdapter.schema_id == schema_id
    assert not hasattr(adapter.CourtAdapter, "accept_caselaw_row")

    institution = {
        "court_id": "example-court",
        "name": "Example Courthouse",
        "name_local": "Example Courthouse",
        "level": "other",
        "court_system": "national",
        "country_code": "US",
        "subdivision": "US-NY",
        "jurisdiction": "New York",
        "parent_court_id": None,
        "record_type": "courthouse",
        "text": "The fixture decision body.",
        "opinion_text": "The fixture opinion.",
        "case_text": "The fixture case text.",
        "id": "fixture:judgment-1",
        "dila_id": "fixture-doc",
        "docket_number": "19-12.345",
        "official_name": "Example Official",
    }

    def _adapt() -> None:
        snapshot = dict(institution)
        record = adapter.CourtAdapter().adapt(institution)
        assert record.interface_id == "legal-corpus.court@1"
        assert record.interface_id != caselaw_interface
        assert record.instrument.kind == "court"
        assert record.instrument.kind != "caselaw"
        assert record.source_schema_id == schema_id
        assert record.instrument.source_schema_id == schema_id
        assert record.instrument.source_schema_version == schema_id
        assert record.instrument.source_dataset == court_kind.SOURCE_DATASET
        assert record.court_id == "example-court"
        assert tuple(record.identifier_fields) == _IDENTIFIER_FIELDS
        assert dict(record.identifier_fields) == {
            key: snapshot[key] for key in _IDENTIFIER_FIELDS
        }
        assert record.source_row["source_schema_id"] == schema_id
        assert "text" not in record.source_row
        assert "opinion_text" not in record.source_row
        assert "case_text" not in record.source_row
        assert "id" not in record.source_row
        assert "dila_id" not in record.source_row
        assert "docket_number" not in record.source_row
        assert "official_name" not in record.source_row
        assert institution == snapshot
        institution["text"] = "changed opinion"
        assert "text" not in record.source_row
        with pytest.raises(TypeError):
            record.identifier_fields["name"] = "rewritten"
        with pytest.raises(TypeError):
            record.source_row["court_id"] = "rewritten"
        with pytest.raises(caselaw_kind.CaselawRejected):
            caselaw_kind.accept_caselaw_row(dict(record.source_row))

        bare = {key: snapshot[key] for key in _IDENTIFIER_FIELDS}
        bare_record = adapter.CourtAdapter().adapt(bare)
        assert bare_record.source_schema_id == schema_id
        assert bare_record.source_row["source_schema_id"] == schema_id
        assert "source_schema_id" not in bare
        assert "text" not in bare_record.source_row
        assert bare_record.instrument.kind == "court"

        flat = {key: snapshot[key] for key in _IDENTIFIER_FIELDS if key != "name_local"}
        flat["official_name"] = "Example Official"
        flat["text"] = "The fixture decision body."
        flat_record = adapter.CourtAdapter().adapt(flat)
        assert "name_local" not in flat_record.identifier_fields
        assert "text" not in flat_record.source_row
        assert "official_name" not in flat_record.source_row
        assert flat_record.identifier_fields["court_id"] == "example-court"
        assert flat_record.interface_id == interface_id

        opinion_only = {
            "court": "Cour de cassation",
            "court_id": None,
            "dila_id": "fixture-doc",
            "text": "The fixture decision body.",
        }
        with pytest.raises(adapter.CourtAdapterRejected) as caught:
            adapter.CourtAdapter().adapt(opinion_only)
        assert "court identifier is required" in str(caught.value)

        statute = dict(bare)
        statute["source_schema_id"] = statute_id
        with pytest.raises(adapter.CourtAdapterRejected) as caught:
            adapter.CourtAdapter().adapt(statute)
        assert "statute" in str(caught.value)

        repo_claim = dict(bare)
        repo_claim["source_schema_id"] = repo
        with pytest.raises(adapter.CourtAdapterRejected) as caught:
            adapter.CourtAdapter().adapt(repo_claim)
        assert "not the schema id" in str(caught.value)

        caselaw_claim = dict(bare)
        caselaw_claim["source_schema_id"] = caselaw_interface
        with pytest.raises(adapter.CourtAdapterRejected) as caught:
            adapter.CourtAdapter().adapt(caselaw_claim)
        assert "caselaw" in str(caught.value)

    _without_socket(_adapt)
    assert _COURTS_COMMON.read_bytes() == common_before
    assert _COURTS_UPLOAD.read_bytes() == upload_before
    assert _COURT_KIND_PATH.read_bytes() == court_before
    assert _CASELAW_KIND_PATH.read_bytes() == caselaw_before
    assert _STATUTE_PATH.read_bytes() == statute_before
