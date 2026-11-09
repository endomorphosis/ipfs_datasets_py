"""Adapt each regulation-register section without scraping.

One class per section in the regulation register. A versioned source keeps
the ``SCHEMA_VERSION`` assigned in its file. A source that assigns no
``SCHEMA_VERSION`` keeps that absence. A CFR fixture stays on its CFR schema
id and does not validate as a statute. This module reads those files with
the parser. It does not import ``federal_scrapers`` and does not edit them.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

_PROCESSORS = Path(__file__).resolve().parents[3]
_KIND = Path(__file__).resolve().parents[1] / "kinds" / "regulation_v1.py"
_LAW_KIND = Path(__file__).resolve().parents[1] / "kinds" / "law_v1.py"
_STATUTE_FILE = _PROCESSORS / "legal_scrapers" / "country_laws_ir" / "__init__.py"
_AUTHORITY_FILE = _PROCESSORS / "legal_data" / "patent_authority_sources.py"

_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"
_AUTHORITY_SCHEMA_ID = "patent-authority-sources-v1"

# Register order. The expected string is the assignment read from that file.
_VERSIONED: tuple[tuple[str, str, str], ...] = (
    ("CFR", "legal_scrapers/federal_scrapers/cfr_annual_processor.py", "cfr-annual-processor-v1"),
    ("CFR", "legal_scrapers/federal_scrapers/live_cfr_source_processor.py", "live-cfr-source-processor-v1"),
    ("eCFR", "legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py", "ecfr-crosscheck-processor-v1"),
    (
        "Federal Register",
        "legal_scrapers/federal_scrapers/federal_register_change_processor.py",
        "federal-register-change-processor-v1",
    ),
    (
        "Federal Register",
        "legal_data/federal_register_release_schema.py",
        "federal-register-sparse-graphrag-release-schema-v2",
    ),
)
_FIXTURE_SCHEMAS: tuple[tuple[str, str], ...] = (
    ("legal_scrapers/federal_scrapers/cfr_annual_processor.py", "cfr-annual-fixture-v1"),
    ("legal_scrapers/federal_scrapers/live_cfr_source_processor.py", "live-cfr-recipe-v1"),
    ("legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py", "ecfr-crosscheck-fixture-v1"),
    (
        "legal_scrapers/federal_scrapers/federal_register_change_processor.py",
        "federal-register-change-fixture-v1",
    ),
)
_UNVERSIONED: tuple[tuple[str, str], ...] = (
    ("Federal Register", "legal_scrapers/federal_scrapers/federal_register_scraper.py"),
    ("regulation_version_tracker.py", "legal_scrapers/regulation_version_tracker.py"),
    ("State admin-rules scrapers", "legal_scrapers/state_admin_rules_scraper.py"),
)
_TRACKER_FIELDS = ("regulation_id", "version_id", "content", "effective_date")


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the regulation register's source files."""


class RegulationAdapterRejected(ValueError):
    """The row is not a record for this regulation-register section."""


def _module_assignment(path: Path, name: str) -> ast.AST | None:
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
            if found is not None:
                raise AdapterBindingError(f"{name} is assigned twice in {path}")
            found = value
    return found


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise AdapterBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise AdapterBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _require_absent(path: Path, name: str) -> None:
    if _module_assignment(path, name) is not None:
        raise AdapterBindingError(f"{path} assigns {name}")


def _bind_sources() -> tuple[dict[str, tuple[str, ...]], dict[str, str], frozenset[str]]:
    """Read each register schema id from the file that assigns it."""

    by_section: dict[str, list[str]] = {}
    datasets: dict[str, str] = {}
    for section, relative, expected in _VERSIONED:
        path = _PROCESSORS / relative
        schema_id = _bound_string(path, "SCHEMA_VERSION", expected)
        if schema_id in datasets:
            raise AdapterBindingError(f"duplicate regulation schema id {schema_id}")
        by_section.setdefault(section, []).append(schema_id)
        datasets[schema_id] = relative
    fixture_ids: set[str] = set()
    for relative, expected in _FIXTURE_SCHEMAS:
        fixture_id = _bound_string(_PROCESSORS / relative, "FIXTURE_SCHEMA_VERSION", expected)
        if fixture_id in datasets:
            raise AdapterBindingError(f"fixture schema {fixture_id} collides with a source schema")
        fixture_ids.add(fixture_id)
    for _section, relative in _UNVERSIONED:
        _require_absent(_PROCESSORS / relative, "SCHEMA_VERSION")
    statute = _bound_string(_STATUTE_FILE, "SCHEMA_VERSION", _STATUTE_SCHEMA_ID)
    authority = _bound_string(_AUTHORITY_FILE, "SCHEMA_VERSION", _AUTHORITY_SCHEMA_ID)
    if statute in datasets or authority in datasets:
        raise AdapterBindingError("a refused schema id was bound as a regulation source")
    return (
        {section: tuple(schema_ids) for section, schema_ids in by_section.items()},
        datasets,
        frozenset(fixture_ids),
    )


_SECTION_SCHEMA_IDS, SOURCE_DATASETS, FIXTURE_SCHEMA_IDS = _bind_sources()
STATUTE_SCHEMA_ID = _STATUTE_SCHEMA_ID
AUTHORITY_SCHEMA_ID = _AUTHORITY_SCHEMA_ID


def _load_regulation_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm033_regulation_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"regulation kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != "legal-corpus.regulation@1":
        raise AdapterBindingError("regulation kind does not export legal-corpus.regulation@1")
    if tuple(module.SOURCE_SCHEMA_IDS) != tuple(
        schema_id for _section, _relative, schema_id in _VERSIONED
    ):
        raise AdapterBindingError("regulation kind schema ids drifted from the register files")
    if getattr(module, "STATUTE_SCHEMA_ID", "") != STATUTE_SCHEMA_ID:
        raise AdapterBindingError("regulation kind statute schema id drifted")
    return module


_REGULATION = _load_regulation_kind()
LAW_SOURCE_SCHEMA = _REGULATION.LAW_SOURCE_SCHEMA
RegulationRejected = _REGULATION.RegulationRejected


def _load_law_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm033_law_kind", _LAW_KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"law kind is missing at {_LAW_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != "legal-corpus.law@1":
        raise AdapterBindingError("law kind does not export legal-corpus.law@1")
    if getattr(module, "SOURCE_SCHEMA_VERSION", "") != STATUTE_SCHEMA_ID:
        raise AdapterBindingError("law kind statute schema id drifted")
    return module


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise RegulationAdapterRejected("regulation row must be a mapping")


def _claim(row: Mapping[str, Any]) -> str | None:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise RegulationAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return None
    if any(item != claims[0] for item in claims):
        raise RegulationAdapterRejected("source schema id fields disagree")
    return claims[0]


def _refuse_foreign(claim: str) -> None:
    if claim == STATUTE_SCHEMA_ID:
        raise RegulationAdapterRejected("statute schema id is rejected")
    if claim == LAW_SOURCE_SCHEMA:
        raise RegulationAdapterRejected("row claims worldwide-legal-search.law-source@1")
    if claim == AUTHORITY_SCHEMA_ID:
        raise RegulationAdapterRejected("patent-authority-sources-v1 is not a regulation id")
    if claim in FIXTURE_SCHEMA_IDS:
        raise RegulationAdapterRejected("fixture schema version is not the source schema id")


def _adapt_versioned(schema_ids: tuple[str, ...], row: Mapping[str, Any]) -> Any:
    _mapping(row)
    claim = _claim(row)
    if claim is None:
        raise RegulationAdapterRejected("source schema id is required")
    _refuse_foreign(claim)
    if claim not in schema_ids:
        raise RegulationAdapterRejected("source schema id is not in this register section")
    try:
        record = _REGULATION.accept_regulation_row(row)
    except RegulationRejected as exc:
        raise RegulationAdapterRejected(str(exc)) from exc
    if record.source_schema_id != claim:
        raise RegulationAdapterRejected("schema id was replaced")
    if record.instrument.kind != "regulation":
        raise RegulationAdapterRejected("output kind is not regulation")
    if record.instrument.source_schema_id != claim:
        raise RegulationAdapterRejected("instrument schema id was replaced")
    return record


@dataclass(frozen=True)
class UnversionedRegulation:
    """A register section that assigns no schema version."""

    section: str
    source_dataset: str
    source_row: Mapping[str, Any]
    source_schema_id: str | None = None

    def __post_init__(self) -> None:
        if self.source_schema_id is not None:
            raise RegulationAdapterRejected("unversioned source assigned a schema id")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise RegulationAdapterRejected("regulation row must be a mapping")
        object.__setattr__(self, "source_row", MappingProxyType({key: row[key] for key in row}))


def _adapt_unversioned(
    section: str,
    dataset: str,
    row: Mapping[str, Any],
    check: Any,
) -> UnversionedRegulation:
    _mapping(row)
    claim = _claim(row)
    if claim is not None:
        _refuse_foreign(claim)
        raise RegulationAdapterRejected("source assigns no schema id")
    check(row)
    return UnversionedRegulation(
        section=section,
        source_dataset=dataset,
        source_row={key: row[key] for key in row},
        source_schema_id=None,
    )


def _require_scraper(row: Mapping[str, Any]) -> None:
    document_number = row.get("document_number")
    fr_url = row.get("fr_url")
    if not isinstance(document_number, str) or document_number.strip() == "":
        raise RegulationAdapterRejected("federal register scraper record needs document_number")
    if not isinstance(fr_url, str) or fr_url.strip() == "":
        raise RegulationAdapterRejected("federal register scraper record needs fr_url")
    if any(key in row for key in ("official_artifact", "derived_presentation", "authority_tier")):
        raise RegulationAdapterRejected("change-processor fields need that source schema id")


def _require_tracker(row: Mapping[str, Any]) -> None:
    for key in _TRACKER_FIELDS:
        if key not in row:
            raise RegulationAdapterRejected(f"missing {key}")
    if not isinstance(row["content"], str):
        raise RegulationAdapterRejected("content must be a string")


def _require_admin(row: Mapping[str, Any]) -> None:
    state_code = row.get("state_code")
    if not isinstance(state_code, str) or state_code.strip() == "":
        raise RegulationAdapterRejected("state admin rule needs state_code")
    structured = row.get("structured_data")
    if isinstance(structured, (str, bytes)) or not isinstance(structured, Mapping):
        raise RegulationAdapterRejected("state admin rule needs structured_data")
    if structured.get("type") != "regulation":
        raise RegulationAdapterRejected("structured_data type must stay regulation")


class CfrRegulation:
    """CFR section. Annual and live processors keep their own schema ids."""

    section = "CFR"
    schema_ids = _SECTION_SCHEMA_IDS["CFR"]

    def adapt(self, row: Mapping[str, Any]) -> Any:
        return _adapt_versioned(self.schema_ids, row)

    def validates_as_statute(self, row: Mapping[str, Any]) -> bool:
        """Return whether this CFR fixture validates as a statute.

        A row that adapts on a CFR schema id is a regulation. Statute
        columns do not replace that schema id, and the law kind's refusal
        of a section record that has no ``id`` or ``text`` stays a refusal.
        """

        record = self.adapt(row)
        if record.source_schema_id == STATUTE_SCHEMA_ID or record.instrument.kind == "law":
            return True
        if record.source_schema_id not in self.schema_ids:
            raise RegulationAdapterRejected("CFR fixture left its schema id")
        law = _load_law_kind()
        statute_row = {key: row[key] for key in row if key not in _CLAIM_FIELDS}
        try:
            law.accept_law_row(statute_row)
        except law.LawRejected:
            return False
        return False


class EcfrRegulation:
    """eCFR section. The crosscheck processor keeps its own schema id."""

    section = "eCFR"
    schema_ids = _SECTION_SCHEMA_IDS["eCFR"]

    def adapt(self, row: Mapping[str, Any]) -> Any:
        return _adapt_versioned(self.schema_ids, row)


class FederalRegisterRegulation:
    """Federal Register section. Versioned contracts keep their schema ids.

    ``federal_register_scraper.py`` assigns no schema version, so a scraper
    document keeps that absence.
    """

    section = "Federal Register"
    schema_ids = _SECTION_SCHEMA_IDS["Federal Register"]
    unversioned_dataset = "legal_scrapers/federal_scrapers/federal_register_scraper.py"

    def adapt(self, row: Mapping[str, Any]) -> Any:
        _mapping(row)
        if _claim(row) is None:
            return _adapt_unversioned(self.section, self.unversioned_dataset, row, _require_scraper)
        return _adapt_versioned(self.schema_ids, row)


class RegulationVersionTrackerRegulation:
    """``regulation_version_tracker.py`` assigns no schema version."""

    section = "regulation_version_tracker.py"
    schema_ids: tuple[str, ...] = ()
    unversioned_dataset = "legal_scrapers/regulation_version_tracker.py"

    def adapt(self, row: Mapping[str, Any]) -> UnversionedRegulation:
        return _adapt_unversioned(self.section, self.unversioned_dataset, row, _require_tracker)


class StateAdminRulesRegulation:
    """State admin-rules scrapers assign no schema version."""

    section = "State admin-rules scrapers"
    schema_ids: tuple[str, ...] = ()
    unversioned_dataset = "legal_scrapers/state_admin_rules_scraper.py"

    def adapt(self, row: Mapping[str, Any]) -> UnversionedRegulation:
        return _adapt_unversioned(self.section, self.unversioned_dataset, row, _require_admin)


SECTIONS: tuple[type, ...] = (
    CfrRegulation,
    EcfrRegulation,
    FederalRegisterRegulation,
    RegulationVersionTrackerRegulation,
    StateAdminRulesRegulation,
)


def _require_section_bindings() -> None:
    names = [cls.section for cls in SECTIONS]
    if len(names) != len(set(names)):
        raise AdapterBindingError("register sections are not one class each")
    bound = tuple(schema_id for cls in SECTIONS for schema_id in cls.schema_ids)
    if bound != tuple(_REGULATION.SOURCE_SCHEMA_IDS):
        raise AdapterBindingError("section schema ids drifted from the regulation kind")
    for schema_id, relative in SOURCE_DATASETS.items():
        if not (_PROCESSORS / relative).is_file():
            raise AdapterBindingError(f"missing source file for {schema_id}")


_require_section_bindings()
