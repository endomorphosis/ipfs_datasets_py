"""LCM-034: accept act-shaped fixtures and reject a US Code row."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/legislative_act_v1.py"
)
_PROCESSORS = _DATASETS / "ipfs_datasets_py/processors"
_PUBLIC_LAW = _PROCESSORS / "legal_scrapers/federal_scrapers/public_law_change_processor.py"
_USCODE_SCRAPER = _PROCESSORS / "legal_scrapers/federal_scrapers/us_code_scraper.py"
_FORBIDDEN = (_PUBLIC_LAW, _USCODE_SCRAPER)


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


def _act(**extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "congress": "118",
        "law_number": "47",
        "package_id": "PLAW-118publ47",
        "citation": "Pub. L. 118-47",
        "title": "Further Consolidated Appropriations Act, 2024 (fixture)",
        "text_excerpt": (
            "Making further consolidated appropriations for the fiscal year "
            "ending September 30, 2024."
        ),
    }
    row.update(extra)
    return row


def test_act_fixtures_record_the_interface_and_reject_us_code() -> None:
    before = {path: path.read_bytes() for path in _FORBIDDEN}
    adapter = _load(_ADAPTER_PATH, "lcm034_legislative_act_v1")
    processor_id = _string(_PUBLIC_LAW, "SCHEMA_VERSION")
    fixture_id = _string(_PUBLIC_LAW, "FIXTURE_SCHEMA_VERSION")
    uscode_id = _string(
        _PROCESSORS / "legal_scrapers/federal_scrapers/uscode_release_processor.py",
        "SCHEMA_VERSION",
    )
    uscode_fixture_id = _string(
        _PROCESSORS / "legal_scrapers/federal_scrapers/uscode_release_processor.py",
        "FIXTURE_SCHEMA_VERSION",
    )
    release_id = _string(
        _PROCESSORS / "legal_data/uscode_release_schema.py",
        "SCHEMA_VERSION",
    )
    release_profile = _string(
        _PROCESSORS / "legal_data/uscode_release_schema.py",
        "RELEASE_PROFILE",
    )
    authority_id = _string(
        _PROCESSORS / "legal_data/patent_authority_sources.py",
        "SCHEMA_VERSION",
    )
    pipeline_id = _string(
        _PROCESSORS / "legal_scrapers/hub_integrated/world_law_pipeline/schema.py",
        "SCHEMA_VERSION",
    )
    assert adapter.INTERFACE_ID == "legal-corpus.legislative-act@1"
    assert adapter.ACT_SCHEMA_IDS == (processor_id, fixture_id)
    assert adapter.USCODE_SCHEMA_IDS == (
        uscode_id,
        uscode_fixture_id,
        release_id,
        release_profile,
    )
    assert processor_id == "public-law-change-processor-v1"
    assert fixture_id == "public-law-change-fixture-v1"
    assert _assignment(_USCODE_SCRAPER, "SCHEMA_VERSION") is None

    def _adapt() -> None:
        single = _act(schema_version=processor_id, note="kept extra")
        snapshot = dict(single)
        record = adapter.LegislativeActAdapter().adapt(single)
        assert record.interface_id == "legal-corpus.legislative-act@1"
        assert record.interface_id == adapter.INTERFACE_ID
        assert record.source_schema_id == processor_id
        assert record.instrument.kind == "legislative_act"
        assert record.instrument.source_schema_id == processor_id
        assert record.instrument.source_schema_version == processor_id
        assert record.source_row["note"] == "kept extra"
        assert single == snapshot
        single["note"] = "changed extra"
        assert record.source_row["note"] == "kept extra"

        first = _act()
        second = _act(
            congress="118",
            law_number="45",
            package_id="PLAW-118publ45",
            citation="Pub. L. 118-45",
            title="Unleashing American Innovators Act of 2022 (fixture)",
        )
        recipe = {
            "schema_version": fixture_id,
            "fixture_id": "public-laws-compact",
            "public_laws": [first, second],
        }
        recipe_snapshot = {
            "schema_version": recipe["schema_version"],
            "fixture_id": recipe["fixture_id"],
            "public_laws": [dict(item) for item in recipe["public_laws"]],
        }
        records = adapter.LegislativeActAdapter().adapt(recipe)
        assert isinstance(records, tuple) and len(records) == 2
        for saved in records:
            assert saved.interface_id == "legal-corpus.legislative-act@1"
            assert saved.source_schema_id == fixture_id
            assert saved.instrument.kind == "legislative_act"
            assert saved.instrument.source_schema_id == fixture_id
        assert recipe["public_laws"] == recipe_snapshot["public_laws"]
        assert "schema_version" not in recipe["public_laws"][0]

        uscode = {
            "schema_version": uscode_id,
            "section_number": "122",
            "heading": "fixture heading",
            "text": "consolidated section body",
            "package": "USCODE-2024-title35",
        }
        try:
            adapter.LegislativeActAdapter().adapt(uscode)
        except adapter.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("US Code schema row was accepted")
        scraper_row = {
            "section_number": "122",
            "heading": "fixture heading",
            "text": "consolidated section body",
            "package": "USCODE-2024-title35",
        }
        try:
            adapter.LegislativeActAdapter().adapt(scraper_row)
        except adapter.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("US Code scraper row was accepted")
        house = dict(scraper_row)
        house["package"] = "USHOUSE-USCODE-118-2024-title35"
        try:
            adapter.LegislativeActAdapter().adapt(house)
        except adapter.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("House US Code package was accepted")
        release = _act(schema_version=release_id, package="USCODE-2024-title35")
        try:
            adapter.LegislativeActAdapter().adapt(release)
        except adapter.LegislativeActAdapterRejected as exc:
            assert "US Code consolidation is rejected" in str(exc)
        else:
            raise AssertionError("US Code release schema was accepted")

        gazette = {
            "document_type": "gazette_act",
            "source_type": "uradni_list",
            "title": "Uradni list act",
            "congress": "118",
            "law_number": "1",
        }
        try:
            adapter.LegislativeActAdapter().adapt(gazette)
        except adapter.LegislativeActAdapterRejected as exc:
            assert "gazette_act is not claimed" in str(exc)
        else:
            raise AssertionError("gazette_act was claimed without an act schema id")
        pipeline = _act(schema_version=pipeline_id, document_type="gazette_act")
        try:
            adapter.LegislativeActAdapter().adapt(pipeline)
        except adapter.LegislativeActAdapterRejected as exc:
            assert pipeline_id in str(exc)
        else:
            raise AssertionError("pipeline schema was accepted as a legislative act")
        authority = _act(schema_version=authority_id)
        try:
            adapter.LegislativeActAdapter().adapt(authority)
        except adapter.LegislativeActAdapterRejected as exc:
            assert authority_id in str(exc)
        else:
            raise AssertionError("patent authority schema was accepted as a legislative act")

    _without_socket(_adapt)
    after = {path: path.read_bytes() for path in _FORBIDDEN}
    assert after == before


def test_adapter_does_not_import_the_processors() -> None:
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(_ADAPTER_PATH))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    for name in modules:
        parts = name.split(".")
        assert "public_law_change_processor" not in parts
        assert "us_code_scraper" not in parts
        assert "uscode_release_processor" not in parts
        assert "uscode_release_schema" not in parts
        assert "federal_scrapers" not in parts
        assert name not in {"requests", "httpx", "urllib", "socket"}
