"""Adapt a Caselaw Access Project fixture onto ``legal-corpus.caselaw@1``.

The CAP reader assigns no ``SCHEMA_VERSION``. The schema id stays the
unversioned id recorded for that file. Opinion fields are the row's
non-embedding keys, copied unchanged, including keys the reader copies
off the parquet row. This module reads ``vector_search_integration.py``
with the parser. It does not import that module, call the CAP API, or
start vector encoding.
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
_KIND = Path(__file__).resolve().parents[1] / "kinds" / "caselaw_v1.py"
_CAP = _PROCESSORS / "legal_scrapers/caselaw_access_program/vector_search_integration.py"
_STATUTE = _PROCESSORS / "legal_scrapers/country_laws_ir/__init__.py"
_CAP_RELATIVE = "legal_scrapers/caselaw_access_program/vector_search_integration.py"

_INTERFACE_ID = "legal-corpus.caselaw@1"
_UNVERSIONED_SCHEMA_ID = "unversioned"
_DATASET_ID = "justicedao/Caselaw_Access_Project_embeddings"
_STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"
_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_SOURCE_NAME = "cap"


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the CAP reader in the caselaw register."""


class CapAdapterRejected(ValueError):
    """The row is not a CAP fixture for ``legal-corpus.caselaw@1``."""


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


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise AdapterBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise AdapterBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _class_body(path: Path, class_name: str) -> list[ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return list(node.body)
    raise AdapterBindingError(f"{class_name} is missing from {path}")


def _class_string(path: Path, class_name: str, field: str, expected: str) -> str:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field:
            continue
        value = stmt.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            raise AdapterBindingError(f"{field} in {path} is not a string")
        if value.value != expected:
            raise AdapterBindingError(f"{field} in {path} is {value.value!r}, not {expected!r}")
        return value.value
    raise AdapterBindingError(f"{field} is missing from {class_name} in {path}")


def _class_tuple(path: Path, class_name: str, field: str) -> tuple[str, ...]:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field or not isinstance(stmt.value, ast.Tuple):
            continue
        values: list[str] = []
        for item in stmt.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise AdapterBindingError(f"{field} in {path} contains a non-string")
            values.append(item.value)
        if not values:
            raise AdapterBindingError(f"{field} in {path} is empty")
        return tuple(values)
    raise AdapterBindingError(f"{field} is missing from {class_name} in {path}")


def _bind_cap() -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Read the CAP schema id and candidate names from the reader file."""

    if "SCHEMA_VERSION" in _names_assigned(_CAP):
        raise AdapterBindingError(f"{_CAP} assigns SCHEMA_VERSION")
    dataset_id = _class_string(_CAP, "CAPVectorSearchConfig", "dataset_id", _DATASET_ID)
    text_fields = _class_tuple(_CAP, "CAPVectorSearchConfig", "text_field_candidates")
    embedding_fields = _class_tuple(_CAP, "CAPVectorSearchConfig", "embedding_field_candidates")
    id_fields = _class_tuple(_CAP, "CAPVectorSearchConfig", "id_field_candidates")
    metadata_fields = _class_tuple(_CAP, "CAPVectorSearchConfig", "metadata_priority_fields")
    if dataset_id == _UNVERSIONED_SCHEMA_ID or dataset_id in text_fields:
        raise AdapterBindingError("CAP dataset id was bound as a schema or text field")
    overlap = set(embedding_fields).intersection(text_fields + id_fields + metadata_fields)
    if overlap:
        raise AdapterBindingError(f"embedding names overlap opinion fields: {sorted(overlap)}")
    statute = _bound_string(_STATUTE, "SCHEMA_VERSION", _STATUTE_SCHEMA_ID)
    if statute == _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("statute schema id collided with the CAP schema id")
    return dataset_id, text_fields, embedding_fields, id_fields, metadata_fields


def _load_caselaw_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm036_caselaw_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"caselaw kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _INTERFACE_ID:
        raise AdapterBindingError("caselaw kind does not export legal-corpus.caselaw@1")
    if getattr(module, "SOURCE_SCHEMA_IDS", {}).get(_SOURCE_NAME) != _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("caselaw kind CAP schema id is not unversioned")
    if getattr(module, "CAP_DATASET_ID", "") != _DATASET_ID:
        raise AdapterBindingError("caselaw kind CAP dataset id drifted")
    if tuple(getattr(module, "CAP_TEXT_FIELDS", ())) != TEXT_FIELDS:
        raise AdapterBindingError("caselaw kind CAP text fields drifted")
    if tuple(getattr(module, "CAP_EMBEDDING_FIELDS", ())) != EMBEDDING_FIELDS:
        raise AdapterBindingError("caselaw kind CAP embedding fields drifted")
    if tuple(getattr(module, "CAP_ID_FIELDS", ())) != ID_FIELDS:
        raise AdapterBindingError("caselaw kind CAP id fields drifted")
    if tuple(getattr(module, "CAP_METADATA_FIELDS", ())) != METADATA_FIELDS:
        raise AdapterBindingError("caselaw kind CAP metadata fields drifted")
    if getattr(module, "SOURCE_DATASETS", {}).get(_SOURCE_NAME) != _CAP_RELATIVE:
        raise AdapterBindingError("caselaw kind CAP source path drifted")
    return module


CAP_DATASET_ID, TEXT_FIELDS, EMBEDDING_FIELDS, ID_FIELDS, METADATA_FIELDS = _bind_cap()
CAP_SCHEMA_ID = _UNVERSIONED_SCHEMA_ID
INTERFACE_ID = _INTERFACE_ID
STATUTE_SCHEMA_ID = _STATUTE_SCHEMA_ID
_CASELAW = _load_caselaw_kind()
CaselawRejected = _CASELAW.CaselawRejected
_EMBEDDING_NAMES = frozenset(EMBEDDING_FIELDS)


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise CapAdapterRejected("CAP row must be a mapping")


def _claim(row: Mapping[str, Any]) -> str:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise CapAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        raise CapAdapterRejected("missing source schema id")
    if any(item != claims[0] for item in claims):
        raise CapAdapterRejected("source schema id fields disagree")
    return claims[0]


def _opinion_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Non-embedding keys, in row order. Claim fields name the schema id."""

    return {
        key: row[key]
        for key in row
        if key not in _CLAIM_FIELDS and key not in _EMBEDDING_NAMES
    }


def _has_opinion_text(fields: Mapping[str, Any]) -> bool:
    for name in TEXT_FIELDS:
        value = fields.get(name)
        if isinstance(value, str) and value.strip():
            return True
    return False


@dataclass(frozen=True)
class CapAdaptation:
    """One CAP fixture carried as ``legal-corpus.caselaw@1``."""

    source_row: Mapping[str, Any]
    instrument: Any
    source_schema_id: str
    source_name: str
    opinion_fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.source_name != _SOURCE_NAME:
            raise CapAdapterRejected("row is not a CAP fixture")
        if self.source_schema_id != CAP_SCHEMA_ID:
            raise CapAdapterRejected("CAP schema id was replaced")
        if self.instrument.kind != "caselaw":
            raise CapAdapterRejected("output kind is not caselaw")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise CapAdapterRejected("instrument schema id was replaced")
        if self.instrument.source_schema_version != self.source_schema_id:
            raise CapAdapterRejected("instrument schema version was replaced")
        if self.instrument.source_dataset != _CAP_RELATIVE:
            raise CapAdapterRejected("CAP source path was replaced")
        row = self.source_row
        fields = self.opinion_fields
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise CapAdapterRejected("CAP row must be a mapping")
        if isinstance(fields, (str, bytes)) or not isinstance(fields, Mapping):
            raise CapAdapterRejected("opinion fields must be a mapping")
        if not _has_opinion_text(fields):
            raise CapAdapterRejected("CAP fixture has no opinion text")
        for key, value in fields.items():
            if key in _EMBEDDING_NAMES or key in _CLAIM_FIELDS:
                raise CapAdapterRejected("opinion fields include a non-opinion key")
            if key not in row or row[key] != value:
                raise CapAdapterRejected("opinion field was replaced")
        object.__setattr__(self, "opinion_fields", MappingProxyType(dict(fields)))

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


class CaselawCapAdapter:
    """Map one CAP fixture onto ``legal-corpus.caselaw@1``."""

    interface_id = INTERFACE_ID
    schema_id = CAP_SCHEMA_ID

    def adapt(self, row: Mapping[str, Any]) -> CapAdaptation:
        _mapping(row)
        claim = _claim(row)
        if claim == STATUTE_SCHEMA_ID:
            raise CapAdapterRejected("statute schema id is rejected")
        if claim == CAP_DATASET_ID:
            raise CapAdapterRejected("CAP dataset id is not a schema id")
        if claim != CAP_SCHEMA_ID:
            raise CapAdapterRejected("source schema id is not the CAP schema id")
        opinion = _opinion_fields(row)
        if not _has_opinion_text(opinion):
            raise CapAdapterRejected("CAP fixture has no opinion text")
        try:
            record = _CASELAW.accept_caselaw_row(row)
        except CaselawRejected as exc:
            raise CapAdapterRejected(str(exc)) from exc
        if dict(record.source_row) != {key: row[key] for key in row}:
            raise CapAdapterRejected("CAP row was rewritten")
        for key, value in opinion.items():
            if record.source_row[key] != value:
                raise CapAdapterRejected("opinion field was replaced")
        return CapAdaptation(
            source_row=record.source_row,
            instrument=record.instrument,
            source_schema_id=record.source_schema_id,
            source_name=record.source_name,
            opinion_fields=opinion,
        )
