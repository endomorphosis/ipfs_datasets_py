"""LCM-033: one adapter class per regulation-register section."""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters/regulation_v1.py"
)
_LAW_KIND = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/kinds/law_v1.py"
)
_PROCESSORS = _DATASETS / "ipfs_datasets_py/processors"
_REGISTER = (
    Path(__file__).resolve().parents[5]
    / "implementation_plan/legal_corpus_modules/registers/regulation.md"
)
_VERSIONED = {
    "cfr-annual-processor-v1": "legal_scrapers/federal_scrapers/cfr_annual_processor.py",
    "live-cfr-source-processor-v1": "legal_scrapers/federal_scrapers/live_cfr_source_processor.py",
    "ecfr-crosscheck-processor-v1": "legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py",
    "federal-register-change-processor-v1": (
        "legal_scrapers/federal_scrapers/federal_register_change_processor.py"
    ),
    "federal-register-sparse-graphrag-release-schema-v2": (
        "legal_data/federal_register_release_schema.py"
    ),
}
_UNVERSIONED = (
    "legal_scrapers/federal_scrapers/federal_register_scraper.py",
    "legal_scrapers/regulation_version_tracker.py",
    "legal_scrapers/state_admin_rules_scraper.py",
)
_FEDERAL_SCRAPERS = _PROCESSORS / "legal_scrapers/federal_scrapers"


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


def _register_sections(path: Path) -> list[str]:
    sections: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            sections.append(line[3:].strip().strip("`"))
    return sections


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _schema_id(relative: str) -> str:
    return _string(_PROCESSORS / relative, "SCHEMA_VERSION")


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


def test_one_class_per_register_section_keeps_the_source_schema_id() -> None:
    assert _register_sections(_REGISTER) == [
        "CFR",
        "eCFR",
        "Federal Register",
        "regulation_version_tracker.py",
        "State admin-rules scrapers",
    ]
    federal_before = {
        path: path.read_bytes()
        for path in sorted(_FEDERAL_SCRAPERS.glob("*.py"))
    }
    adapter = _load(_ADAPTER_PATH, "lcm033_regulation_v1")
    assert [cls.section for cls in adapter.SECTIONS] == _register_sections(_REGISTER)
    assert len({cls.section for cls in adapter.SECTIONS}) == 5
    for cls in adapter.SECTIONS:
        assert callable(cls.adapt)
    seen: list[str] = []
    for cls in adapter.SECTIONS:
        for schema_id in cls.schema_ids:
            seen.append(schema_id)
            assert _schema_id(_VERSIONED[schema_id]) == schema_id
    assert seen == [
        "cfr-annual-processor-v1",
        "live-cfr-source-processor-v1",
        "ecfr-crosscheck-processor-v1",
        "federal-register-change-processor-v1",
        "federal-register-sparse-graphrag-release-schema-v2",
    ]
    for relative in _UNVERSIONED:
        assert _assignment(_PROCESSORS / relative, "SCHEMA_VERSION") is None
    assert adapter.STATUTE_SCHEMA_ID == _schema_id("legal_scrapers/country_laws_ir/__init__.py")
    assert adapter.AUTHORITY_SCHEMA_ID == _schema_id("legal_data/patent_authority_sources.py")
    assert adapter.STATUTE_SCHEMA_ID == "country-laws-ir-graphrag/v1"
    assert adapter.AUTHORITY_SCHEMA_ID == "patent-authority-sources-v1"

    def _adapt_all() -> None:
        annual_id = _schema_id(_VERSIONED["cfr-annual-processor-v1"])
        live_id = _schema_id(_VERSIONED["live-cfr-source-processor-v1"])
        ecfr_id = _schema_id(_VERSIONED["ecfr-crosscheck-processor-v1"])
        change_id = _schema_id(_VERSIONED["federal-register-change-processor-v1"])
        release_id = _schema_id(_VERSIONED["federal-register-sparse-graphrag-release-schema-v2"])
        annual = {
            "schema_version": annual_id,
            "citation": "37 CFR 1.1",
            "title": "37",
            "section": "1.1",
            "stable_id": "t37-s1.1",
            "text_excerpt": "annual fixture",
            "formats": {},
            "year": "2024",
        }
        live = {
            "schema_version": live_id,
            "title": "37",
            "section": "1.1",
            "source_cid": "bafyfixture",
            "citation": "37 CFR 1.1",
            "text_excerpt": "live fixture",
            "authority_status": "official",
            "authentication_status": "unverified",
        }
        ecfr = {
            "schema_version": ecfr_id,
            "citation": "37 CFR 1.1",
            "title": "37",
            "section": "1.1",
            "text_excerpt": "unofficial fixture",
            "up_to_date_as_of": "2024-01-01",
        }
        change = {
            "schema_version": change_id,
            "document_number": "2024-00001",
            "title": "Example rule",
            "document_type": "Rule",
            "citation": "89 FR 1",
        }
        release = {
            "schema_version": release_id,
            "document_number": "2024-00001",
            "publication_date": "2024-01-02",
        }
        for source, expected in (
            (annual, annual_id),
            (live, live_id),
        ):
            snapshot = dict(source)
            record = adapter.CfrRegulation().adapt(source)
            assert record.source_schema_id == expected
            assert record.instrument.kind == "regulation"
            assert record.instrument.source_schema_id == expected
            assert record.instrument.source_schema_version == expected
            assert source == snapshot
        ecfr_record = adapter.EcfrRegulation().adapt(ecfr)
        assert ecfr_record.source_schema_id == ecfr_id
        assert ecfr_record.instrument.kind == "regulation"
        change_record = adapter.FederalRegisterRegulation().adapt(change)
        assert change_record.source_schema_id == change_id
        release_record = adapter.FederalRegisterRegulation().adapt(release)
        assert release_record.source_schema_id == release_id
        scraper = {
            "document_number": "2024-00002",
            "title": "Example notice",
            "fr_url": "https://example.invalid/fr/2024-00002",
            "document_type": "Notice",
            "citation": "89 FR 2",
        }
        scraper_record = adapter.FederalRegisterRegulation().adapt(scraper)
        assert scraper_record.source_schema_id is None
        assert scraper_record.section == "Federal Register"
        assert scraper_record.source_dataset.endswith("federal_register_scraper.py")
        assert dict(scraper_record.source_row) == scraper
        tracker = {
            "regulation_id": "EPA-001",
            "version_id": "v1",
            "content": "fixture body",
            "effective_date": "2020-01-01T00:00:00",
            "title": "Example",
        }
        tracker_record = adapter.RegulationVersionTrackerRegulation().adapt(tracker)
        assert tracker_record.source_schema_id is None
        assert tracker_record.section == "regulation_version_tracker.py"
        assert dict(tracker_record.source_row) == tracker
        admin = {
            "state_code": "CA",
            "legal_area": "administrative",
            "section_name": "Title 1",
            "full_text": "administrative rule fixture",
            "structured_data": {"type": "regulation"},
        }
        admin_record = adapter.StateAdminRulesRegulation().adapt(admin)
        assert admin_record.source_schema_id is None
        assert admin_record.section == "State admin-rules scrapers"
        assert admin_record.source_row["structured_data"]["type"] == "regulation"

    _without_socket(_adapt_all)
    federal_after = {
        path: path.read_bytes()
        for path in sorted(_FEDERAL_SCRAPERS.glob("*.py"))
    }
    assert federal_after == federal_before


def test_cfr_fixture_does_not_validate_as_a_statute() -> None:
    adapter = _load(_ADAPTER_PATH, "lcm033_regulation_v1_statute")
    law = _load(_LAW_KIND, "lcm033_law_kind")
    annual_id = _schema_id(_VERSIONED["cfr-annual-processor-v1"])
    fixture = {
        "schema_version": annual_id,
        "citation": "37 CFR 1.1",
        "title": "37",
        "section": "1.1",
        "stable_id": "t37-s1.1",
        "text_excerpt": "annual fixture",
        "formats": {},
        "year": "2024",
    }
    section_record = {key: value for key, value in fixture.items() if key != "schema_version"}

    def _check() -> None:
        cfr = adapter.CfrRegulation()
        assert cfr.validates_as_statute(fixture) is False
        record = cfr.adapt(fixture)
        assert record.source_schema_id == annual_id
        assert record.source_schema_id != adapter.STATUTE_SCHEMA_ID
        assert record.instrument.kind == "regulation"
        try:
            law.accept_law_row(section_record)
        except law.LawRejected as exc:
            assert "missing required column" in str(exc)
        else:
            raise AssertionError("CFR section record validated as a statute")
        enriched = {**fixture, "id": "cfr-1", "text": "not a statute"}
        assert cfr.validates_as_statute(enriched) is False
        kept = cfr.adapt(enriched)
        assert kept.source_schema_id == annual_id
        assert kept.instrument.kind == "regulation"
        statute = {**fixture, "schema_version": adapter.STATUTE_SCHEMA_ID}
        try:
            cfr.adapt(statute)
        except adapter.RegulationAdapterRejected as exc:
            assert "statute schema id is rejected" in str(exc)
        else:
            raise AssertionError("statute schema was accepted as CFR")
        authority = {**fixture, "schema_version": adapter.AUTHORITY_SCHEMA_ID}
        try:
            cfr.adapt(authority)
        except adapter.RegulationAdapterRejected as exc:
            assert "patent-authority-sources-v1" in str(exc)
        else:
            raise AssertionError("authority schema was accepted as CFR")

    _without_socket(_check)


def test_adapter_does_not_import_federal_scrapers() -> None:
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(_ADAPTER_PATH))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    for name in modules:
        assert "federal_scrapers" not in name.split(".")
        assert name not in {"requests", "httpx", "urllib", "socket"}
