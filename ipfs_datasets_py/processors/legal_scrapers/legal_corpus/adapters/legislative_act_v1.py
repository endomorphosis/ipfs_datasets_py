"""Adapt legislative-act fixtures named by the legislative-act register.

Public-law schema ids are read from ``public_law_change_processor.py``.
US Code schema ids and package prefixes are read from the US Code modules
the register excludes. An act-shaped fixture is recorded as
``legal-corpus.legislative-act@1`` with the schema id the row or its
fixture wrapper claims. A US Code row is rejected. ``gazette_act`` is not
claimed from ``document_type`` alone. This module reads those files with
the parser. It does not import or edit them.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

_PROCESSORS = Path(__file__).resolve().parents[3]
_KIND = Path(__file__).resolve().parents[1] / "kinds" / "legislative_act_v1.py"
_PUBLIC_LAW = "legal_scrapers/federal_scrapers/public_law_change_processor.py"
_USCODE_PROCESSOR = "legal_scrapers/federal_scrapers/uscode_release_processor.py"
_USCODE_RELEASE = "legal_data/uscode_release_schema.py"
_USCODE_SCRAPER = "legal_scrapers/federal_scrapers/us_code_scraper.py"
_AUTHORITY = "legal_data/patent_authority_sources.py"
_PIPELINE = "legal_scrapers/hub_integrated/world_law_pipeline/schema.py"

_INTERFACE_ID = "legal-corpus.legislative-act@1"
_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_ACT_FIELDS = ("congress", "law_number", "title")
_PACKAGE_PREFIXES = ("USHOUSE-USCODE-", "USCODE-")

# Name, assignment, string read from that file. Register order.
_ACT_SOURCES: tuple[tuple[str, str, str], ...] = (
    (_PUBLIC_LAW, "SCHEMA_VERSION", "public-law-change-processor-v1"),
    (_PUBLIC_LAW, "FIXTURE_SCHEMA_VERSION", "public-law-change-fixture-v1"),
)
_USCODE_SOURCES: tuple[tuple[str, str, str], ...] = (
    (_USCODE_PROCESSOR, "SCHEMA_VERSION", "uscode-release-processor-v1"),
    (_USCODE_PROCESSOR, "FIXTURE_SCHEMA_VERSION", "uscode-release-fixture-v1"),
    (_USCODE_RELEASE, "SCHEMA_VERSION", "uscode-sparse-graphrag-release-schema-v2"),
    (_USCODE_RELEASE, "RELEASE_PROFILE", "publicus-ir-graphrag/v2"),
)
_AUTHORITY_SCHEMA_ID = "patent-authority-sources-v1"
_PIPELINE_SCHEMA_ID = "1.2.0"


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the legislative-act register's source files."""


class LegislativeActAdapterRejected(ValueError):
    """The row is not an act-shaped fixture from the legislative-act register."""


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


def _load_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm034_legislative_act_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"legislative-act kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _INTERFACE_ID:
        raise AdapterBindingError("legislative-act kind does not export legal-corpus.legislative-act@1")
    return module


_KIND_MODULE = _load_kind()
ACT_SCHEMA_IDS = _bind_ids(_ACT_SOURCES)
USCODE_SCHEMA_IDS = _bind_ids(_USCODE_SOURCES)
USCODE_PACKAGE_PREFIXES = _bound_package_prefixes(_PROCESSORS / _USCODE_SCRAPER)
AUTHORITY_SCHEMA_ID = _bound_string(_PROCESSORS / _AUTHORITY, "SCHEMA_VERSION", _AUTHORITY_SCHEMA_ID)
PIPELINE_SCHEMA_ID = _bound_string(_PROCESSORS / _PIPELINE, "SCHEMA_VERSION", _PIPELINE_SCHEMA_ID)
INTERFACE_ID = _INTERFACE_ID
if tuple(_KIND_MODULE.ACT_SCHEMA_IDS) != ACT_SCHEMA_IDS:
    raise AdapterBindingError("legislative-act kind schema ids drifted from the register files")
if tuple(_KIND_MODULE.USCODE_SCHEMA_IDS) != USCODE_SCHEMA_IDS:
    raise AdapterBindingError("US Code schema ids drifted from the register files")
if tuple(_KIND_MODULE.USCODE_PACKAGE_PREFIXES) != USCODE_PACKAGE_PREFIXES:
    raise AdapterBindingError("US Code package prefixes drifted from us_code_scraper.py")
if getattr(_KIND_MODULE, "INTERFACE_ID", "") != INTERFACE_ID:
    raise AdapterBindingError("legislative-act kind interface id drifted")
if set(ACT_SCHEMA_IDS) & set(USCODE_SCHEMA_IDS):
    raise AdapterBindingError("an act schema id is also a US Code schema id")
if AUTHORITY_SCHEMA_ID in ACT_SCHEMA_IDS or PIPELINE_SCHEMA_ID in ACT_SCHEMA_IDS:
    raise AdapterBindingError("a refused schema id was bound as a legislative-act source")
_ACT_REGISTERED = frozenset(ACT_SCHEMA_IDS)
_USCODE_REGISTERED = frozenset(USCODE_SCHEMA_IDS)


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise LegislativeActAdapterRejected("legislative-act row must be a mapping")


def _claim(row: Mapping[str, Any]) -> str | None:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise LegislativeActAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return None
    if any(item != claims[0] for item in claims):
        raise LegislativeActAdapterRejected("source schema id fields disagree")
    return claims[0]


def _uscode_package(row: Mapping[str, Any]) -> bool:
    for key in ("package", "package_id"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith(USCODE_PACKAGE_PREFIXES):
            return True
    return False


def _reject_uscode(row: Mapping[str, Any], claim: str | None) -> None:
    if _uscode_package(row) or (claim in _USCODE_REGISTERED if claim is not None else False):
        raise LegislativeActAdapterRejected("US Code consolidation is rejected")


def _require_act_shape(row: Mapping[str, Any]) -> None:
    for key in _ACT_FIELDS:
        value = row.get(key)
        if not isinstance(value, str) or value.strip() == "":
            raise LegislativeActAdapterRejected(f"act fixture needs {key}")


def _accept_one(row: Mapping[str, Any]) -> Any:
    _mapping(row)
    claim = _claim(row)
    _reject_uscode(row, claim)
    if claim == AUTHORITY_SCHEMA_ID:
        raise LegislativeActAdapterRejected("patent-authority-sources-v1 is not a legislative-act schema id")
    if claim == PIPELINE_SCHEMA_ID:
        raise LegislativeActAdapterRejected("pipeline schema 1.2.0 is not a legislative-act schema id")
    if row.get("document_type") == "gazette_act" and claim not in _ACT_REGISTERED:
        raise LegislativeActAdapterRejected("gazette_act is not claimed without an act schema id")
    if claim not in _ACT_REGISTERED:
        raise LegislativeActAdapterRejected("source schema id is not in the legislative-act register")
    _require_act_shape(row)
    try:
        record = _KIND_MODULE.accept_legislative_act_row(row)
    except _KIND_MODULE.LegislativeActRejected as exc:
        raise LegislativeActAdapterRejected(str(exc)) from exc
    if record.interface_id != INTERFACE_ID:
        raise LegislativeActAdapterRejected("interface id was replaced")
    if record.source_schema_id != claim:
        raise LegislativeActAdapterRejected("source schema id was replaced")
    if record.instrument.kind != "legislative_act":
        raise LegislativeActAdapterRejected("output kind is not legislative_act")
    if record.instrument.source_schema_id != claim:
        raise LegislativeActAdapterRejected("instrument schema id was replaced")
    return record


class LegislativeActAdapter:
    """Accept an act-shaped public-law fixture and reject a US Code row."""

    interface_id = INTERFACE_ID
    schema_ids = ACT_SCHEMA_IDS

    def adapt(self, row: Mapping[str, Any]) -> Any:
        _mapping(row)
        if "public_laws" not in row:
            return _accept_one(row)
        claim = _claim(row)
        _reject_uscode(row, claim)
        if claim not in _ACT_REGISTERED:
            raise LegislativeActAdapterRejected("fixture schema id is not in the legislative-act register")
        laws = row.get("public_laws")
        if isinstance(laws, (str, bytes)) or not isinstance(laws, list):
            raise LegislativeActAdapterRejected("public_laws must be a list")
        records = []
        for item in laws:
            _mapping(item)
            child = {key: item[key] for key in item}
            child_claim = _claim(child)
            if child_claim is None:
                child["schema_version"] = claim
            elif child_claim != claim:
                raise LegislativeActAdapterRejected("public law schema id does not match the fixture")
            records.append(_accept_one(child))
        if not records:
            raise LegislativeActAdapterRejected("fixture has no act-shaped public laws")
        return tuple(records)
