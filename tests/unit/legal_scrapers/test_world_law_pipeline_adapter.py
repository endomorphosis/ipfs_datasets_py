"""LCM-032: pipeline schema 1.2.0 keeps DOC_TYPES and national iso_ keys."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/world_law_pipeline_v1.py"
)
_SCHEMA_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/schema.py"
)
_REGISTER_PATH = (
    Path(__file__).resolve().parents[5]
    / "implementation_plan/legal_corpus_modules/registers/municipal.md"
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


def _tuple(path: Path, name: str) -> tuple[str, ...]:
    value = _assignment(path, name)
    assert isinstance(value, (ast.Tuple, ast.List))
    items: list[str] = []
    for item in value.elts:
        assert isinstance(item, ast.Constant) and isinstance(item.value, str)
        items.append(item.value)
    return tuple(items)


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            assert isinstance(segment, str) and segment
            return segment
    raise AssertionError(f"{name} missing from {path}")


def _register_labels(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Label classification":
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        stripped = line.strip()
        if not stripped:
            if found:
                break
            continue
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 2:
            continue
        label, kind = cells
        if label in {"Source label", "---"} or set(label) <= {"-"}:
            continue
        assert label.startswith("`") and label.endswith("`") and len(label) >= 3
        found[label[1:-1]] = kind
    assert found
    return found


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "lcm032_world_law_pipeline_v1",
        _ADAPTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(doc_type: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "1.2.0",
        "doc_type": doc_type,
        "place_id": "wd:Q90",
        "title": f"fixture-{doc_type}",
    }
    row.update(extra)
    return row


def test_classified_labels_keep_version_and_source_doc_type() -> None:
    schema_bytes = _SCHEMA_PATH.read_bytes()
    place_key = _function_source(_SCHEMA_PATH, "place_key")
    is_national = _function_source(_SCHEMA_PATH, "is_national_key")
    assert _string(_SCHEMA_PATH, "SCHEMA_VERSION") == "1.2.0"
    doc_types = _tuple(_SCHEMA_PATH, "DOC_TYPES")
    assert doc_types == (
        "code_section",
        "ordinance",
        "regulation",
        "statute",
        "gazette_act",
        "decision",
    )
    assert 'return str(pkey).startswith("iso_")' in is_national
    assert "iso:US-CA -> iso_US-CA" in place_key
    assert 'return pid.replace(":", "_")' in place_key
    labels = _register_labels(_REGISTER_PATH)
    assert set(labels) == set(doc_types)
    assert labels["decision"] == "not yet classified"
    adapter = _load_adapter()
    assert adapter.SCHEMA_VERSION == "1.2.0"
    assert adapter.DOC_TYPES == doc_types
    assert adapter.CLASSIFICATION == labels
    assert adapter.SOURCE_SCHEMA_FILE == "hub_integrated/world_law_pipeline/schema.py"
    calls: list[str] = []
    real_socket = socket.socket

    def _refuse_socket(*_args: object, **_kwargs: object) -> object:
        calls.append("socket")
        raise AssertionError("adapter opened a socket")

    socket.socket = _refuse_socket  # type: ignore[method-assign]
    try:
        for label, kind in labels.items():
            if kind == "not yet classified":
                continue
            source = _row(label)
            snapshot = dict(source)
            record = adapter.adapt_world_law_pipeline_row(source)
            assert record.schema_version == "1.2.0"
            assert record.doc_type == label
            assert record.source_row["schema_version"] == "1.2.0"
            assert record.source_row["doc_type"] == label
            assert record.classification == kind
            assert record.classified is True
            assert record.classification != "not yet classified"
            assert record.place_key == "wd_Q90"
            assert record.national is False
            assert record.source_row["place_key"] == "wd_Q90"
            assert source == snapshot
            copied = dict(record.source_row)
            assert copied.keys() == {**snapshot, "place_key": "wd_Q90"}.keys()
    finally:
        socket.socket = real_socket  # type: ignore[method-assign]
    assert calls == []
    assert _SCHEMA_PATH.read_bytes() == schema_bytes
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(_ADAPTER_PATH))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        assert "schema" not in name.split(".")
        assert "world_law_pipeline" not in name.split(".")


def test_decision_stays_unclassified_and_iso_keys_stay_national() -> None:
    schema_bytes = _SCHEMA_PATH.read_bytes()
    labels = _register_labels(_REGISTER_PATH)
    assert labels["decision"] == "not yet classified"
    adapter = _load_adapter()
    decision = _row("decision", kind="caselaw")
    record = adapter.adapt_world_law_pipeline_row(decision)
    assert record.doc_type == "decision"
    assert record.source_row["doc_type"] == "decision"
    assert record.source_row["schema_version"] == "1.2.0"
    assert record.classification == "not yet classified"
    assert record.classified is False
    assert record.classification not in {"law", "regulation", "act", "caselaw"}
    national = _row("statute", place_id="iso:US-CA")
    adapted = adapter.adapt_world_law_pipeline_row(national)
    assert adapted.place_key == "iso_US-CA"
    assert adapted.place_key.startswith("iso_")
    assert adapted.national is True
    assert adapted.repo_id == adapter.NATIONAL_REPO_ID
    assert adapted.repo_id != adapter.REPO_ID
    assert adapted.source_row["place_key"] == "iso_US-CA"
    assert adapted.source_row["doc_type"] == "statute"
    assert "wd_" not in adapted.place_key
    stored = _row("ordinance", place_id="iso:US-CA", place_key="iso_US-CA")
    kept = adapter.adapt_world_law_pipeline_row(stored)
    assert kept.place_key == "iso_US-CA"
    assert kept.source_row["place_key"] == "iso_US-CA"
    assert kept.national is True
    rewritten = _row("ordinance", place_id="iso:US-CA", place_key="wd_Q90")
    try:
        adapter.adapt_world_law_pipeline_row(rewritten)
    except adapter.PipelineRejected as exc:
        assert "municipal id" in str(exc)
    else:
        raise AssertionError("an iso_ key rewritten to wd_Q90 was accepted")
    municipal = _row("ordinance", place_id="wd:Q90")
    local = adapter.adapt_world_law_pipeline_row(municipal)
    assert local.place_key == "wd_Q90"
    assert local.national is False
    assert local.repo_id == adapter.REPO_ID
    assert not str(local.place_key).startswith("iso_")
    try:
        adapter.adapt_world_law_pipeline_row(_row("caselaw"))
    except adapter.PipelineRejected as exc:
        assert "DOC_TYPES" in str(exc)
    else:
        raise AssertionError("a label outside DOC_TYPES was mapped")
    assert _SCHEMA_PATH.read_bytes() == schema_bytes
