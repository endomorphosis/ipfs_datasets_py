"""Adapt a RECAP fixture onto ``legal-corpus.caselaw@1``.

``recap_archive_scraper.py`` assigns no ``SCHEMA_VERSION``. The schema id
stays the unversioned id recorded for that file. A search fixture keeps
the keys ``search_recap_documents`` writes. A detail fixture keeps the
keys ``get_recap_document`` writes, including the nested ``metadata``
object. Court identity stays the string already stored on those keys.
This module does not copy a court-module row, does not build
``legal-corpus.court@1``, and does not download a RECAP archive.
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
_COURT_KIND = Path(__file__).resolve().parents[1] / "kinds" / "court_v1.py"
_RECAP = _PROCESSORS / "legal_scrapers/recap_archive_scraper.py"
_COURTS_COMMON = (
    _PROCESSORS
    / "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py"
)
_COURTS_UPLOAD = (
    _PROCESSORS
    / "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/upload_world_courts.py"
)
_STATUTE = _PROCESSORS / "legal_scrapers/country_laws_ir/__init__.py"
_RECAP_RELATIVE = "legal_scrapers/recap_archive_scraper.py"

_INTERFACE_ID = "legal-corpus.caselaw@1"
_UNVERSIONED_SCHEMA_ID = "unversioned"
_STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"
_COURT_INTERFACE_ID = "legal-corpus.court@1"
_SEARCH_SOURCE = "recap_search"
_DETAIL_SOURCE = "recap_detail"
_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_REFERENCE_KEYS = ("court", "court_full_name", "court_id")


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the RECAP reader in the caselaw register."""


class RecapAdapterRejected(ValueError):
    """The row is not a RECAP fixture for ``legal-corpus.caselaw@1``."""


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


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise AdapterBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise AdapterBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _find_function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AdapterBindingError(f"{name} is missing from {path}")


def _dict_keys(node: ast.Dict) -> tuple[str, ...] | None:
    keys: list[str] = []
    for key in node.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.append(key.value)
    if not keys:
        return None
    return tuple(keys)


def _key_tuples(fn: ast.AST) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            if isinstance(func, ast.Name) and func.id == "dict" and call.keywords:
                if any(item.arg is None for item in call.keywords):
                    continue
                found.append(tuple(item.arg for item in call.keywords if item.arg))
        if isinstance(node, ast.Dict):
            keys = _dict_keys(node)
            if keys:
                found.append(keys)
    return found


def _column_list(path: Path, fn_name: str, anchor: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for keys in _key_tuples(_find_function(path, fn_name)):
        if anchor in keys and keys not in matches:
            matches.append(keys)
    if len(matches) != 1:
        raise AdapterBindingError(f"{path} {fn_name} column list count for {anchor} is {len(matches)}")
    return matches[0]


def _call_keywords(fn: ast.AST, call_name: str, required: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != call_name:
            continue
        names = tuple(keyword.arg for keyword in node.keywords if keyword.arg)
        if required in names and names not in matches:
            matches.append(names)
    if len(matches) != 1:
        raise AdapterBindingError(f"{call_name} keyword list count for {required} is {len(matches)}")
    return matches[0]


def _return_dict_keys(fn: ast.AST, required: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys = _dict_keys(node.value)
        if keys and required in keys and keys not in matches:
            matches.append(keys)
    if len(matches) != 1:
        raise AdapterBindingError(f"return dict count for {required} is {len(matches)}")
    return matches[0]


def _bind_recap() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Read RECAP columns and the court-module fields from the source files."""

    if "SCHEMA_VERSION" in _names_assigned(_RECAP):
        raise AdapterBindingError(f"{_RECAP} assigns SCHEMA_VERSION")
    downloaders = {"search_recap_documents", "get_recap_document", "scrape_recap_archive"}
    if downloaders & _function_names(Path(__file__)):
        raise AdapterBindingError("RECAP adapter defines a download function")
    search = _column_list(_RECAP, "search_recap_documents", "abstract")
    detail = _column_list(_RECAP, "get_recap_document", "metadata")
    metadata = _column_list(_RECAP, "get_recap_document", "court_id")
    if search == detail or search == metadata or detail == metadata:
        raise AdapterBindingError("RECAP search, detail, and metadata columns collided")
    if "abstract" not in search or "abstract" in detail or "metadata" not in detail:
        raise AdapterBindingError("RECAP search and detail columns drifted")
    if "court_id" not in metadata or "pacer_doc_id" not in metadata or "docket_number" not in metadata:
        raise AdapterBindingError("RECAP metadata columns drifted")
    if "court" not in search or "court" not in detail or "court_full_name" not in search:
        raise AdapterBindingError("RECAP court reference columns drifted")
    statute = _bound_string(_STATUTE, "SCHEMA_VERSION", _STATUTE_SCHEMA_ID)
    court_interface = _bound_string(_COURT_KIND, "INTERFACE_ID", _COURT_INTERFACE_ID)
    if statute in {_UNVERSIONED_SCHEMA_ID, court_interface}:
        raise AdapterBindingError("statute schema id collided with RECAP or the court module")
    rec_fields = _call_keywords(_find_function(_COURTS_COMMON, "rec"), "dict", "court_id")
    flat_fields = _return_dict_keys(_find_function(_COURTS_UPLOAD, "flat_court"), "court_id")
    if "court_id" not in rec_fields or "court_id" not in flat_fields:
        raise AdapterBindingError("court module fields are missing court_id")
    if "name" not in rec_fields or "record_type" not in rec_fields:
        raise AdapterBindingError("court module institution fields drifted")
    recap_names = frozenset(search + detail + metadata)
    if not (frozenset(rec_fields) - recap_names):
        raise AdapterBindingError("court module fields collapsed into RECAP columns")
    return search, detail, metadata, rec_fields, flat_fields


def _load_caselaw_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm039_caselaw_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"caselaw kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _INTERFACE_ID:
        raise AdapterBindingError("caselaw kind does not export legal-corpus.caselaw@1")
    for source_name, columns in (
        (_SEARCH_SOURCE, RECAP_SEARCH_COLUMNS),
        (_DETAIL_SOURCE, RECAP_DETAIL_COLUMNS),
    ):
        if getattr(module, "SOURCE_SCHEMA_IDS", {}).get(source_name) != _UNVERSIONED_SCHEMA_ID:
            raise AdapterBindingError(f"caselaw kind {source_name} schema id is not unversioned")
        kind_columns = {
            _SEARCH_SOURCE: "RECAP_SEARCH_COLUMNS",
            _DETAIL_SOURCE: "RECAP_DETAIL_COLUMNS",
        }[source_name]
        if tuple(getattr(module, kind_columns, ())) != columns:
            raise AdapterBindingError(f"caselaw kind {source_name} columns drifted")
        if getattr(module, "SOURCE_DATASETS", {}).get(source_name) != _RECAP_RELATIVE:
            raise AdapterBindingError(f"caselaw kind {source_name} source path drifted")
    return module


(
    RECAP_SEARCH_COLUMNS,
    RECAP_DETAIL_COLUMNS,
    RECAP_METADATA_COLUMNS,
    REC_FIELDS,
    FLAT_COURT_FIELDS,
) = _bind_recap()
RECAP_SCHEMA_ID = _UNVERSIONED_SCHEMA_ID
INTERFACE_ID = _INTERFACE_ID
STATUTE_SCHEMA_ID = _STATUTE_SCHEMA_ID
COURT_INTERFACE_ID = _COURT_INTERFACE_ID
SEARCH_SOURCE_NAME = _SEARCH_SOURCE
DETAIL_SOURCE_NAME = _DETAIL_SOURCE
_RECAP_NAMES = frozenset(RECAP_SEARCH_COLUMNS + RECAP_DETAIL_COLUMNS + RECAP_METADATA_COLUMNS)
COURT_MODULE_FIELDS = tuple(dict.fromkeys(REC_FIELDS + FLAT_COURT_FIELDS))
_COURT_MODULE_ONLY = frozenset(COURT_MODULE_FIELDS) - _RECAP_NAMES
_CASELAW = _load_caselaw_kind()
CaselawRejected = _CASELAW.CaselawRejected


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise RecapAdapterRejected("RECAP row must be a mapping")


def _copied_court_module_row(value: object) -> bool:
    """A court-module mapping is not a RECAP string reference."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        return False
    keys = set(value)
    if keys & _COURT_MODULE_ONLY:
        return True
    if keys == set(REC_FIELDS) or keys == set(FLAT_COURT_FIELDS):
        return True
    return any(_copied_court_module_row(item) for item in value.values())


def _claim(row: Mapping[str, Any]) -> str:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise RecapAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return RECAP_SCHEMA_ID
    if any(item != claims[0] for item in claims):
        raise RecapAdapterRejected("source schema id fields disagree")
    return claims[0]


def _body_keys(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(key for key in row if key not in _CLAIM_FIELDS)


def _reference_string(value: object, label: str) -> str:
    if isinstance(value, str):
        return value
    if _copied_court_module_row(value):
        raise RecapAdapterRejected("court identity is a copied court module row")
    raise RecapAdapterRejected(f"{label} court identity must be a string reference")


def _check_metadata(value: object) -> None:
    if value is None:
        return
    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        raise RecapAdapterRejected("metadata is not a RECAP metadata object")
    if tuple(value) != RECAP_METADATA_COLUMNS:
        raise RecapAdapterRejected("metadata is not a RECAP metadata object")
    for key in ("court_id", "court_full_name"):
        _reference_string(value[key], key)


def _check_references(source_name: str, prepared: Mapping[str, Any]) -> None:
    _reference_string(prepared.get("court"), "court")
    if source_name == _SEARCH_SOURCE:
        _reference_string(prepared.get("court_full_name"), "court_full_name")
        return
    _check_metadata(prepared.get("metadata"))


def _court_reference(source_name: str, columns: Mapping[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    court = columns.get("court")
    if isinstance(court, str) and court != "":
        found["court"] = court
    if source_name == _SEARCH_SOURCE:
        full_name = columns.get("court_full_name")
        if isinstance(full_name, str) and full_name != "":
            found["court_full_name"] = full_name
        return found
    metadata = columns.get("metadata")
    if isinstance(metadata, Mapping) and not isinstance(metadata, (str, bytes)):
        for key in ("court_id", "court_full_name"):
            value = metadata.get(key)
            if isinstance(value, str) and value != "":
                found[key] = value
    return found


def _prepare(row: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    claim = _claim(row)
    if claim == STATUTE_SCHEMA_ID:
        raise RecapAdapterRejected("statute schema id is rejected")
    if claim == COURT_INTERFACE_ID:
        raise RecapAdapterRejected("court module schema is not the RECAP schema id")
    if claim != RECAP_SCHEMA_ID:
        raise RecapAdapterRejected("source schema id is not the RECAP schema id")
    body = _body_keys(row)
    if body == RECAP_SEARCH_COLUMNS:
        source_name = _SEARCH_SOURCE
        columns = RECAP_SEARCH_COLUMNS
    elif body == RECAP_DETAIL_COLUMNS:
        source_name = _DETAIL_SOURCE
        columns = RECAP_DETAIL_COLUMNS
    else:
        raise RecapAdapterRejected("row is not a RECAP fixture")
    prepared = {"source_schema_id": claim}
    for key in columns:
        prepared[key] = row[key]
    _check_references(source_name, prepared)
    return prepared, source_name


@dataclass(frozen=True)
class RecapAdaptation:
    """One RECAP fixture carried as ``legal-corpus.caselaw@1``."""

    source_row: Mapping[str, Any]
    instrument: Any
    source_schema_id: str
    source_name: str
    columns: Mapping[str, Any]
    court_reference: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.source_name not in {_SEARCH_SOURCE, _DETAIL_SOURCE}:
            raise RecapAdapterRejected("row is not a RECAP fixture")
        if self.source_schema_id != RECAP_SCHEMA_ID:
            raise RecapAdapterRejected("RECAP schema id was replaced")
        if self.interface_id != INTERFACE_ID or self.interface_id == COURT_INTERFACE_ID:
            raise RecapAdapterRejected("output interface is not legal-corpus.caselaw@1")
        if self.instrument.kind != "caselaw":
            raise RecapAdapterRejected("output kind is not caselaw")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise RecapAdapterRejected("instrument schema id was replaced")
        if self.instrument.source_schema_version != self.source_schema_id:
            raise RecapAdapterRejected("instrument schema version was replaced")
        if self.instrument.source_dataset != _RECAP_RELATIVE:
            raise RecapAdapterRejected("RECAP source path was replaced")
        expected = RECAP_SEARCH_COLUMNS if self.source_name == _SEARCH_SOURCE else RECAP_DETAIL_COLUMNS
        row = self.source_row
        fields = self.columns
        reference = self.court_reference
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise RecapAdapterRejected("RECAP row must be a mapping")
        if isinstance(fields, (str, bytes)) or not isinstance(fields, Mapping):
            raise RecapAdapterRejected("RECAP columns must be a mapping")
        if isinstance(reference, (str, bytes)) or not isinstance(reference, Mapping):
            raise RecapAdapterRejected("court identity must be a string reference")
        if tuple(fields) != expected:
            raise RecapAdapterRejected("RECAP column order was replaced")
        if set(reference) - set(_REFERENCE_KEYS) or set(reference) & _COURT_MODULE_ONLY:
            raise RecapAdapterRejected("court identity is a copied court module row")
        for key, value in reference.items():
            if not isinstance(value, str) or value == "":
                raise RecapAdapterRejected("court identity must be a string reference")
        for key, value in fields.items():
            if key in _CLAIM_FIELDS or key in _COURT_MODULE_ONLY:
                raise RecapAdapterRejected("RECAP columns include a schema claim or court module field")
            if key not in row or row[key] != value:
                raise RecapAdapterRejected("RECAP column was replaced")
        object.__setattr__(self, "columns", MappingProxyType(dict(fields)))
        object.__setattr__(self, "court_reference", MappingProxyType(dict(reference)))

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


class CaselawRecapAdapter:
    """Map one RECAP fixture onto ``legal-corpus.caselaw@1``."""

    interface_id = INTERFACE_ID
    schema_id = RECAP_SCHEMA_ID

    def adapt(self, row: Mapping[str, Any]) -> RecapAdaptation:
        _mapping(row)
        if _copied_court_module_row(row):
            raise RecapAdapterRejected("court identity is a copied court module row")
        prepared, source_name = _prepare(row)
        columns = {key: prepared[key] for key in _body_keys(prepared)}
        try:
            record = _CASELAW.accept_caselaw_row(prepared)
        except CaselawRejected as exc:
            raise RecapAdapterRejected(str(exc)) from exc
        if dict(record.source_row) != prepared:
            raise RecapAdapterRejected("RECAP row was rewritten")
        if record.source_name != source_name:
            raise RecapAdapterRejected("row is not a RECAP fixture")
        return RecapAdaptation(
            source_row=record.source_row,
            instrument=record.instrument,
            source_schema_id=record.source_schema_id,
            source_name=record.source_name,
            columns=columns,
            court_reference=_court_reference(source_name, columns),
        )
