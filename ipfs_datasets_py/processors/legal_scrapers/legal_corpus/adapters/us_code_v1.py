"""Adapt US Code consolidation as ``legal-corpus.law@1``.

Schema ids are the assignments the legislative-act register quotes from
``uscode_release_processor.py`` and ``uscode_release_schema.py``. A row
that claims one of those ids is recorded as law with that source schema
id. ``us_code_scraper.py`` assigns no ``SCHEMA_VERSION``; a package
prefix from that file is still law and is not given a schema id.
The kind stays ``law``. This module reads those files with the parser.
It does not import or edit them.
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
_LAW_KIND = Path(__file__).resolve().parents[1] / "kinds" / "law_v1.py"
_INSTRUMENT = Path(__file__).resolve().parents[1] / "instrument_v1.py"
_USCODE_PROCESSOR = "legal_scrapers/federal_scrapers/uscode_release_processor.py"
_USCODE_RELEASE = "legal_data/uscode_release_schema.py"
_USCODE_SCRAPER = "legal_scrapers/federal_scrapers/us_code_scraper.py"
_PUBLIC_LAW = "legal_scrapers/federal_scrapers/public_law_change_processor.py"
_STATUTE = "legal_scrapers/country_laws_ir/__init__.py"
_AUTHORITY = "legal_data/patent_authority_sources.py"
_PIPELINE = "legal_scrapers/hub_integrated/world_law_pipeline/schema.py"

_INTERFACE_ID = "legal-corpus.law@1"
_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_SECTION_FIELDS = ("section_number", "heading", "text")
_PACKAGE_PREFIXES = ("USHOUSE-USCODE-", "USCODE-")

# Name, assignment, string read from that file. Register order.
_USCODE_SOURCES: tuple[tuple[str, str, str], ...] = (
    (_USCODE_PROCESSOR, "SCHEMA_VERSION", "uscode-release-processor-v1"),
    (_USCODE_PROCESSOR, "FIXTURE_SCHEMA_VERSION", "uscode-release-fixture-v1"),
    (_USCODE_RELEASE, "SCHEMA_VERSION", "uscode-sparse-graphrag-release-schema-v2"),
    (_USCODE_RELEASE, "RELEASE_PROFILE", "publicus-ir-graphrag/v2"),
)
_REFUSED_SOURCES: tuple[tuple[str, str, str], ...] = (
    (_PUBLIC_LAW, "SCHEMA_VERSION", "public-law-change-processor-v1"),
    (_PUBLIC_LAW, "FIXTURE_SCHEMA_VERSION", "public-law-change-fixture-v1"),
    (_STATUTE, "SCHEMA_VERSION", "country-laws-ir-graphrag/v1"),
    (_AUTHORITY, "SCHEMA_VERSION", "patent-authority-sources-v1"),
    (_PIPELINE, "SCHEMA_VERSION", "1.2.0"),
)


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the US Code files named by the register."""


class UsCodeAdapterRejected(ValueError):
    """The row is not US Code consolidation recorded as law."""


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


def _names_assigned(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _bound_package_prefixes(path: Path) -> tuple[str, ...]:
    """Keep the package prefixes that ``us_code_scraper.py`` writes."""

    if "SCHEMA_VERSION" in _names_assigned(path):
        raise AdapterBindingError(f"{path} assigns SCHEMA_VERSION")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or not node.values:
            continue
        first = node.values[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        for prefix in _PACKAGE_PREFIXES:
            if first.value == prefix or first.value.startswith(prefix):
                found.add(prefix)
    missing = [prefix for prefix in _PACKAGE_PREFIXES if prefix not in found]
    if missing:
        raise AdapterBindingError(f"{path} is missing package prefixes {missing}")
    return _PACKAGE_PREFIXES


def _bind_ids(rows: tuple[tuple[str, str, str], ...]) -> tuple[str, ...]:
    schema_ids: list[str] = []
    seen: set[str] = set()
    for relative, name, expected in rows:
        schema_id = _bound_string(_PROCESSORS / relative, name, expected)
        if schema_id in seen:
            raise AdapterBindingError(f"duplicate schema id {schema_id}")
        seen.add(schema_id)
        schema_ids.append(schema_id)
    return tuple(schema_ids)


def _load_law_interface() -> str:
    """Read the law kind's interface id. Do not accept a row through it."""

    spec = importlib.util.spec_from_file_location("_lcm035_law_kind", _LAW_KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"law kind is missing at {_LAW_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    interface = getattr(module, "INTERFACE_ID", "")
    if interface != _INTERFACE_ID:
        raise AdapterBindingError("law kind does not export legal-corpus.law@1")
    statute = getattr(module, "SOURCE_SCHEMA_VERSION", "")
    if statute != "country-laws-ir-graphrag/v1":
        raise AdapterBindingError("law kind statute schema drifted")
    return interface


def _load_instrument() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm035_instrument", _INSTRUMENT)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"instrument module is missing at {_INSTRUMENT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != "legal-corpus.instrument@1":
        raise AdapterBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    kinds = tuple(getattr(module, "KINDS", ()))
    if "law" not in kinds or "legislative_act" not in kinds:
        raise AdapterBindingError("instrument kinds drifted")
    return module


INTERFACE_ID = _load_law_interface()
_INSTRUMENT_MODULE = _load_instrument()
USCODE_SCHEMA_IDS = _bind_ids(_USCODE_SOURCES)
USCODE_PACKAGE_PREFIXES = _bound_package_prefixes(_PROCESSORS / _USCODE_SCRAPER)
REFUSED_SCHEMA_IDS = _bind_ids(_REFUSED_SOURCES)
_USCODE_REGISTERED = frozenset(USCODE_SCHEMA_IDS)
_REFUSED = frozenset(REFUSED_SCHEMA_IDS)
_DATASETS = {schema_id: relative for relative, _name, schema_id in _USCODE_SOURCES}
if _USCODE_REGISTERED & _REFUSED:
    raise AdapterBindingError("a US Code schema id is also a refused schema id")
if INTERFACE_ID != _INTERFACE_ID:
    raise AdapterBindingError("law interface id drifted")


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise UsCodeAdapterRejected("US Code row must be a mapping")


def _claim(row: Mapping[str, Any]) -> str | None:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise UsCodeAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return None
    if any(item != claims[0] for item in claims):
        raise UsCodeAdapterRejected("source schema id fields disagree")
    return claims[0]


def _uscode_package(row: Mapping[str, Any]) -> bool:
    for key in ("package", "package_id"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith(USCODE_PACKAGE_PREFIXES):
            return True
    return False


@dataclass(frozen=True)
class UsCodeLawRecord:
    """One US Code row carried as ``legal-corpus.law@1``."""

    source_row: Mapping[str, Any]
    instrument: Any
    source_schema_id: str

    def __post_init__(self) -> None:
        if self.source_schema_id not in _USCODE_REGISTERED:
            raise UsCodeAdapterRejected("source schema id is not a US Code schema id")
        if self.instrument.kind != "law":
            raise UsCodeAdapterRejected("output kind is not law")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise UsCodeAdapterRejected("source schema id was replaced")
        if self.instrument.source_schema_version != self.source_schema_id:
            raise UsCodeAdapterRejected("source schema id was replaced")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise UsCodeAdapterRejected("US Code row must be a mapping")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID

    @property
    def kind(self) -> str:
        return "law"


@dataclass(frozen=True)
class UsCodeScraperRecord:
    """A scraper section. That file assigns no schema id."""

    source_row: Mapping[str, Any]
    source_dataset: str
    source_schema_id: str | None = None

    def __post_init__(self) -> None:
        if self.source_schema_id is not None:
            raise UsCodeAdapterRejected("us_code_scraper.py assigns no SCHEMA_VERSION")
        if self.source_dataset != _USCODE_SCRAPER:
            raise UsCodeAdapterRejected("scraper dataset was replaced")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise UsCodeAdapterRejected("US Code row must be a mapping")
        if not _uscode_package(row):
            raise UsCodeAdapterRejected("US Code scraper row needs a US Code package")
        object.__setattr__(self, "source_row", MappingProxyType({key: row[key] for key in row}))

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID

    @property
    def kind(self) -> str:
        return "law"


def _accept_versioned(row: Mapping[str, Any], claim: str) -> UsCodeLawRecord:
    copied = {key: row[key] for key in row}
    instrument = _INSTRUMENT_MODULE.InstrumentRecord(
        kind="law",
        source_schema_id=claim,
        source_schema_version=claim,
        source_dataset=_DATASETS[claim],
        source_row=copied,
    )
    return UsCodeLawRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        source_schema_id=claim,
    )


def _require_section(row: Mapping[str, Any]) -> None:
    for key in _SECTION_FIELDS:
        value = row.get(key)
        if not isinstance(value, str) or value.strip() == "":
            raise UsCodeAdapterRejected(f"US Code section needs {key}")


def _accept_scraper(row: Mapping[str, Any]) -> UsCodeScraperRecord:
    _require_section(row)
    if not _uscode_package(row):
        raise UsCodeAdapterRejected("US Code scraper row needs a US Code package")
    return UsCodeScraperRecord(
        source_row={key: row[key] for key in row},
        source_dataset=_USCODE_SCRAPER,
        source_schema_id=None,
    )


class UsCodeLaw:
    """Record US Code consolidation as law and keep its source schema id."""

    interface_id = INTERFACE_ID
    schema_ids = USCODE_SCHEMA_IDS

    def adapt(self, row: Mapping[str, Any]) -> UsCodeLawRecord | UsCodeScraperRecord:
        _mapping(row)
        claim = _claim(row)
        if claim is not None:
            if claim not in _USCODE_REGISTERED:
                raise UsCodeAdapterRejected(f"{claim} is not a US Code schema id")
            record = _accept_versioned(row, claim)
            if record.kind != "law" or record.interface_id != INTERFACE_ID:
                raise UsCodeAdapterRejected("output kind is not law")
            return record
        if row.get("document_type") == "gazette_act":
            raise UsCodeAdapterRejected("gazette_act is not a US Code schema id")
        if _uscode_package(row):
            record = _accept_scraper(row)
            if record.kind != "law" or record.interface_id != INTERFACE_ID:
                raise UsCodeAdapterRejected("output kind is not law")
            return record
        raise UsCodeAdapterRejected("US Code row needs a source schema id or a US Code package")
