"""Adapt a court-register row onto ``legal-corpus.court@1``.

The identifier fields are the institution fields named for ``rec`` in the
court register. Opinion text is left off the court row. The cited schema
id is the court kind's unversioned id, and only when ``courts_common.py``
and ``upload_world_courts.py`` assign no ``SCHEMA_VERSION``. A court row
is not returned as caselaw.
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
_KIND = Path(__file__).resolve().parents[1] / "kinds" / "court_v1.py"
_CASELAW_KIND = Path(__file__).resolve().parents[1] / "kinds" / "caselaw_v1.py"
_COURTS_COMMON = (
    _PROCESSORS
    / "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py"
)
_COURTS_UPLOAD = (
    _PROCESSORS
    / "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/upload_world_courts.py"
)
_STATUTE = _PROCESSORS / "legal_scrapers/country_laws_ir/__init__.py"
_COMMON_RELATIVE = (
    "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py"
)

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
_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_FLAT_OMITS = ("name_local",)


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the court register's source files."""


class CourtAdapterRejected(ValueError):
    """The row cannot be carried as ``legal-corpus.court@1``."""


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


def _bound_string(path: Path, name: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise AdapterBindingError(f"{name} in {path} is not a string")
    if value.value.strip() == "":
        raise AdapterBindingError(f"{name} in {path} is empty")
    return value.value


def _bound_strings(path: Path, name: str) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise AdapterBindingError(f"{name} in {path} is not a sequence")
    items: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise AdapterBindingError(f"{name} in {path} contains a non-string")
        items.append(item.value)
    if not items:
        raise AdapterBindingError(f"{name} in {path} is empty")
    return tuple(items)


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


def _bind_court() -> dict[str, Any]:
    """Read identifier fields and the cited schema id from the source files."""

    if "SCHEMA_VERSION" in _names_assigned(_COURTS_COMMON):
        raise AdapterBindingError(f"{_COURTS_COMMON} assigns SCHEMA_VERSION")
    if "SCHEMA_VERSION" in _names_assigned(_COURTS_UPLOAD):
        raise AdapterBindingError(f"{_COURTS_UPLOAD} assigns SCHEMA_VERSION")
    interface_id = _bound_string(_KIND, "INTERFACE_ID")
    schema_id = _bound_string(_KIND, "UNVERSIONED_SCHEMA_ID")
    caselaw_interface = _bound_string(_CASELAW_KIND, "INTERFACE_ID")
    statute_schema = _bound_string(_STATUTE, "SCHEMA_VERSION")
    repo = _bound_string(_COURTS_UPLOAD, "DS")
    opinion_fields = _bound_strings(_KIND, "_OPINION_BODY_NAMES")
    rec_fields = _call_keywords(_find_function(_COURTS_COMMON, "rec"), "dict", "court_id")
    flat_fields = _return_dict_keys(_find_function(_COURTS_UPLOAD, "flat_court"), "court_id")
    if schema_id in {interface_id, caselaw_interface, statute_schema, repo}:
        raise AdapterBindingError("court schema id collided with another id")
    if interface_id == caselaw_interface:
        raise AdapterBindingError("court interface id is the caselaw interface id")
    missing = [name for name in _IDENTIFIER_FIELDS if name not in rec_fields]
    if missing:
        raise AdapterBindingError(f"rec is missing identifier fields {missing}")
    for name in _IDENTIFIER_FIELDS:
        if name in _FLAT_OMITS:
            if name in flat_fields:
                raise AdapterBindingError(f"flat_court gained {name}")
            continue
        if name not in flat_fields:
            raise AdapterBindingError(f"flat_court is missing {name}")
    if set(_IDENTIFIER_FIELDS) & set(opinion_fields):
        raise AdapterBindingError("an identifier field is opinion text")
    if "text" in rec_fields or "text" in flat_fields:
        raise AdapterBindingError("court constructor carries opinion text")
    if "court_id" not in _IDENTIFIER_FIELDS:
        raise AdapterBindingError("court identifier is not an identifier field")
    return {
        "interface_id": interface_id,
        "schema_id": schema_id,
        "caselaw_interface": caselaw_interface,
        "statute_schema": statute_schema,
        "repo": repo,
        "opinion_fields": opinion_fields,
        "rec_fields": rec_fields,
        "flat_fields": flat_fields,
    }


def _load_court_kind(bound: Mapping[str, Any]) -> Any:
    spec = importlib.util.spec_from_file_location("_lcm040_court_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"court kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != bound["interface_id"]:
        raise AdapterBindingError("court kind does not export the court interface")
    if getattr(module, "SOURCE_SCHEMA_ID", "") != bound["schema_id"]:
        raise AdapterBindingError("court kind schema id drifted from the register")
    if tuple(getattr(module, "OPINION_BODY_FIELDS", ())) != bound["opinion_fields"]:
        raise AdapterBindingError("court kind opinion fields drifted")
    if tuple(getattr(module, "REC_FIELDS", ())) != bound["rec_fields"]:
        raise AdapterBindingError("court kind rec fields drifted")
    if tuple(getattr(module, "FLAT_COURT_FIELDS", ())) != bound["flat_fields"]:
        raise AdapterBindingError("court kind flat_court fields drifted")
    if getattr(module, "WORLD_COURTS_REPO", "") != bound["repo"]:
        raise AdapterBindingError("court kind repo id drifted")
    if getattr(module, "STATUTE_SCHEMA_ID", "") != bound["statute_schema"]:
        raise AdapterBindingError("court kind statute schema id drifted")
    if getattr(module, "SOURCE_DATASET", "") != _COMMON_RELATIVE:
        raise AdapterBindingError("court kind source path drifted")
    accept = getattr(module, "accept_court_row", None)
    if accept is None:
        raise AdapterBindingError("court kind does not export accept_court_row")
    return module


_BOUND = _bind_court()
INTERFACE_ID = str(_BOUND["interface_id"])
SOURCE_SCHEMA_ID = str(_BOUND["schema_id"])
CASELAW_INTERFACE_ID = str(_BOUND["caselaw_interface"])
STATUTE_SCHEMA_ID = str(_BOUND["statute_schema"])
WORLD_COURTS_REPO = str(_BOUND["repo"])
OPINION_BODY_FIELDS = tuple(_BOUND["opinion_fields"])
REC_FIELDS = tuple(_BOUND["rec_fields"])
FLAT_COURT_FIELDS = tuple(_BOUND["flat_fields"])
IDENTIFIER_FIELDS = _IDENTIFIER_FIELDS
SOURCE_DATASET = _COMMON_RELATIVE
_COURT = _load_court_kind(_BOUND)
CourtRejected = _COURT.CourtRejected


def _mapping(row: object) -> Mapping[str, Any]:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise CourtAdapterRejected("court row must be a mapping")
    return row


def _claim(row: Mapping[str, Any]) -> str:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise CourtAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return SOURCE_SCHEMA_ID
    if any(item != claims[0] for item in claims):
        raise CourtAdapterRejected("source schema id fields disagree")
    return claims[0]


def _build(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy identifier fields and cite the register schema. Opinion keys stay out."""

    claim = _claim(row)
    if claim == STATUTE_SCHEMA_ID:
        raise CourtAdapterRejected("statute schema id is rejected")
    if claim == WORLD_COURTS_REPO:
        raise CourtAdapterRejected("world courts repo id is not the schema id")
    if claim == CASELAW_INTERFACE_ID:
        raise CourtAdapterRejected("caselaw schema is not the court schema id")
    if claim == INTERFACE_ID:
        raise CourtAdapterRejected("court interface id is not the source schema id")
    if claim != SOURCE_SCHEMA_ID:
        raise CourtAdapterRejected("source schema id is not in the court register")
    built: dict[str, Any] = {"source_schema_id": SOURCE_SCHEMA_ID}
    for key in IDENTIFIER_FIELDS:
        if key in OPINION_BODY_FIELDS:
            raise CourtAdapterRejected("opinion text was not dropped")
        if key in row:
            built[key] = row[key]
    for key in OPINION_BODY_FIELDS:
        if key in built:
            raise CourtAdapterRejected("opinion text was not dropped")
    court_id = built.get("court_id")
    if not isinstance(court_id, str) or court_id.strip() == "":
        raise CourtAdapterRejected("court identifier is required")
    return built


@dataclass(frozen=True)
class CourtAdaptation:
    """One court-register row carried as ``legal-corpus.court@1``."""

    source_row: Mapping[str, Any]
    instrument: Any
    source_schema_id: str
    court_id: str
    identifier_fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.interface_id != INTERFACE_ID or self.interface_id == CASELAW_INTERFACE_ID:
            raise CourtAdapterRejected("output interface is not legal-corpus.court@1")
        if self.source_schema_id != SOURCE_SCHEMA_ID:
            raise CourtAdapterRejected("source schema id was replaced")
        if self.instrument.kind != "court":
            raise CourtAdapterRejected("output kind is not court")
        if self.instrument.kind == "caselaw":
            raise CourtAdapterRejected("court row was merged into caselaw")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise CourtAdapterRejected("instrument schema id was replaced")
        if self.instrument.source_schema_version != self.source_schema_id:
            raise CourtAdapterRejected("instrument schema version was replaced")
        if self.instrument.source_dataset != SOURCE_DATASET:
            raise CourtAdapterRejected("court source path was replaced")
        row = self.source_row
        fields = self.identifier_fields
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise CourtAdapterRejected("court row must be a mapping")
        if isinstance(fields, (str, bytes)) or not isinstance(fields, Mapping):
            raise CourtAdapterRejected("identifier fields must be a mapping")
        if not isinstance(self.court_id, str) or self.court_id.strip() == "":
            raise CourtAdapterRejected("court identifier is required")
        allowed = set(IDENTIFIER_FIELDS) | {"source_schema_id"}
        if set(row) - allowed:
            raise CourtAdapterRejected("court row contains a non-identifier field")
        for key in OPINION_BODY_FIELDS:
            if key in row or key in fields:
                raise CourtAdapterRejected("opinion text was not dropped")
        if tuple(fields) != tuple(key for key in IDENTIFIER_FIELDS if key in fields):
            raise CourtAdapterRejected("identifier field order was replaced")
        if row.get("court_id") != self.court_id or fields.get("court_id") != self.court_id:
            raise CourtAdapterRejected("court identifier does not match the row")
        if row.get("source_schema_id") != self.source_schema_id:
            raise CourtAdapterRejected("source schema id was not cited")
        for key, value in fields.items():
            if key not in IDENTIFIER_FIELDS or key not in row or row[key] != value:
                raise CourtAdapterRejected("identifier field was replaced")
        object.__setattr__(self, "identifier_fields", MappingProxyType(dict(fields)))

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


class CourtAdapter:
    """Map court-register identifier fields onto ``legal-corpus.court@1``."""

    interface_id = INTERFACE_ID
    schema_id = SOURCE_SCHEMA_ID

    def adapt(self, row: Mapping[str, Any]) -> CourtAdaptation:
        source = _mapping(row)
        built = _build(source)
        fields = {key: built[key] for key in IDENTIFIER_FIELDS if key in built}
        try:
            record = _COURT.accept_court_row(built)
        except CourtRejected as exc:
            raise CourtAdapterRejected(str(exc)) from exc
        if record.interface_id != INTERFACE_ID or record.instrument.kind != "court":
            raise CourtAdapterRejected("output kind is not court")
        if dict(record.source_row) != built:
            raise CourtAdapterRejected("court row was rewritten")
        for key in OPINION_BODY_FIELDS:
            if key in record.source_row:
                raise CourtAdapterRejected("opinion text was not dropped")
        return CourtAdaptation(
            source_row=record.source_row,
            instrument=record.instrument,
            source_schema_id=record.source_schema_id,
            court_id=record.court_id,
            identifier_fields=fields,
        )
