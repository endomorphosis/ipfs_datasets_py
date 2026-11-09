"""LCM-035: emit legal-corpus.law@1 with the US Code source schema id."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/us_code_v1.py"
)
_ACT_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/legislative_act_v1.py"
)
_PROCESSORS = _DATASETS / "ipfs_datasets_py/processors"
_USCODE_PROCESSOR = _PROCESSORS / "legal_scrapers/federal_scrapers/uscode_release_processor.py"
_USCODE_RELEASE = _PROCESSORS / "legal_data/uscode_release_schema.py"
_USCODE_SCRAPER = _PROCESSORS / "legal_scrapers/federal_scrapers/us_code_scraper.py"
_PUBLIC_LAW = _PROCESSORS / "legal_scrapers/federal_scrapers/public_law_change_processor.py"
_FORBIDDEN = (_USCODE_PROCESSOR, _USCODE_RELEASE, _USCODE_SCRAPER, _PUBLIC_LAW)


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


def _section(**extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "section_number": "122",
        "heading": "fixture heading",
        "text": "consolidated section body",
        "package": "USCODE-2024-title35",
    }
    row.update(extra)
    return row


def test_us_code_rows_emit_law_and_the_act_adapter_still_rejects_them() -> None:
    before = {path: path.read_bytes() for path in _FORBIDDEN}
    adapter = _load(_ADAPTER_PATH, "lcm035_us_code_v1")
    act = _load(_ACT_ADAPTER_PATH, "lcm035_legislative_act_v1")
    processor_id = _string(_USCODE_PROCESSOR, "SCHEMA_VERSION")
    fixture_id = _string(_USCODE_PROCESSOR, "FIXTURE_SCHEMA_VERSION")
    release_id = _string(_USCODE_RELEASE, "SCHEMA_VERSION")
    release_profile = _string(_USCODE_RELEASE, "RELEASE_PROFILE")
    statute_id = _string(
        _PROCESSORS / "legal_scrapers/country_laws_ir/__init__.py",
        "SCHEMA_VERSION",
    )
    public_law_id = _string(_PUBLIC_LAW, "SCHEMA_VERSION")
    public_law_fixture_id = _string(_PUBLIC_LAW, "FIXTURE_SCHEMA_VERSION")
    authority_id = _string(
        _PROCESSORS / "legal_data/patent_authority_sources.py",
        "SCHEMA_VERSION",
    )
    pipeline_id = _string(
        _PROCESSORS / "legal_scrapers/hub_integrated/world_law_pipeline/schema.py",
        "SCHEMA_VERSION",
    )
    schema_ids = (processor_id, fixture_id, release_id, release_profile)
    assert adapter.INTERFACE_ID == "legal-corpus.law@1"
    assert adapter.USCODE_SCHEMA_IDS == schema_ids
    assert processor_id == "uscode-release-processor-v1"
    assert fixture_id == "uscode-release-fixture-v1"
    assert release_id == "uscode-sparse-graphrag-release-schema-v2"
    assert release_profile == "publicus-ir-graphrag/v2"
    assert _assignment(_USCODE_SCRAPER, "SCHEMA_VERSION") is None
    assert statute_id not in schema_ids

    def _adapt() -> None:
        for schema_id in schema_ids:
            row = _section(schema_version=schema_id, note="kept extra")
            snapshot = dict(row)
            record = adapter.UsCodeLaw().adapt(row)
            assert record.interface_id == "legal-corpus.law@1"
            assert record.interface_id == adapter.INTERFACE_ID
            assert record.kind == "law"
            assert record.source_schema_id == schema_id
            assert record.instrument.kind == "law"
            assert record.instrument.kind != "legislative_act"
            assert record.instrument.source_schema_id == schema_id
            assert record.instrument.source_schema_version == schema_id
            assert record.source_schema_id != statute_id
            assert record.source_row["note"] == "kept extra"
            assert row == snapshot
            row["note"] = "changed extra"
            assert record.source_row["note"] == "kept extra"
            try:
                act.LegislativeActAdapter().adapt(dict(snapshot))
            except act.LegislativeActAdapterRejected as exc:
                assert "US Code consolidation is rejected" in str(exc)
            else:
                raise AssertionError("legislative-act adapter accepted a US Code schema row")

        scraper_row = _section()
        scraper_snapshot = dict(scraper_row)
        scraper = adapter.UsCodeLaw().adapt(scraper_row)
        assert scraper.interface_id == "legal-corpus.law@1"
        assert scraper.kind == "law"
        assert scraper.kind != "legislative_act"
        assert scraper.source_schema_id is None
        assert scraper.source_dataset.endswith("us_code_scraper.py")
        assert scraper_row == scraper_snapshot
        try:
            act.LegislativeActAdapter().adapt(dict(scraper_snapshot))
        except act.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("legislative-act adapter accepted a US Code scraper row")

        house = _section(package="USHOUSE-USCODE-118-2024-title35")
        house_record = adapter.UsCodeLaw().adapt(house)
        assert house_record.interface_id == "legal-corpus.law@1"
        assert house_record.kind == "law"
        assert house_record.source_schema_id is None
        try:
            act.LegislativeActAdapter().adapt(dict(house))
        except act.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("legislative-act adapter accepted a House US Code package")

        release = _section(schema_version=release_id)
        try:
            act.LegislativeActAdapter().adapt(release)
        except act.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("legislative-act adapter accepted the release schema")

        for foreign in (public_law_id, public_law_fixture_id, statute_id, authority_id, pipeline_id):
            try:
                adapter.UsCodeLaw().adapt(_section(schema_version=foreign))
            except adapter.UsCodeAdapterRejected as exc:
                assert foreign in str(exc)
            else:
                raise AssertionError(f"{foreign} was accepted as US Code")
        gazette = {
            "document_type": "gazette_act",
            "title": "Uradni list act",
            "congress": "118",
            "law_number": "1",
        }
        try:
            adapter.UsCodeLaw().adapt(gazette)
        except adapter.UsCodeAdapterRejected as exc:
            assert "gazette_act" in str(exc)
        else:
            raise AssertionError("gazette_act was accepted as US Code")

    _without_socket(_adapt)
    after = {path: path.read_bytes() for path in _FORBIDDEN}
    assert after == before


def test_adapter_does_not_import_the_processors() -> None:
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(_ADAPTER_PATH))
    modules: list[str] = []
    kind_args: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.keyword) and node.arg == "kind" and isinstance(node.value, ast.Constant):
            kind_args.append(node.value.value)
    for name in modules:
        parts = name.split(".")
        assert "us_code_scraper" not in parts
        assert "uscode_release_processor" not in parts
        assert "uscode_release_schema" not in parts
        assert "public_law_change_processor" not in parts
        assert "federal_scrapers" not in parts
        assert name not in {"requests", "httpx", "urllib", "socket"}
    assert kind_args == ["law"]
