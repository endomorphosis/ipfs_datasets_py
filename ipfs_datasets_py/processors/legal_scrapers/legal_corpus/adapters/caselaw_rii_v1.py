"""Adapt a Rechtsprechung im Internet fixture onto ``legal-corpus.caselaw@1``.

``collect_de_rii.py`` assigns no ``SCHEMA_VERSION``. The schema id stays
the unversioned id recorded for that file. The row keeps the keys
``parse`` returns, including ``rii_doknr``, ``doctype``, ``norm``, and
``config``. This module reads that file and ``catalog.py`` with the
parser. It does not import the collector, register ``collect_gii``, or
start a GraphRAG or embedding job.
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
_RII = _PROCESSORS / "legal_scrapers/national_collectors/collect_de_rii.py"
_CATALOG = _PROCESSORS / "legal_scrapers/national_collectors/catalog.py"
_STATUTE = _PROCESSORS / "legal_scrapers/country_laws_ir/__init__.py"
_RII_RELATIVE = "legal_scrapers/national_collectors/collect_de_rii.py"

_INTERFACE_ID = "legal-corpus.caselaw@1"
_UNVERSIONED_SCHEMA_ID = "unversioned"
_STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"
_GII_MODULE = "collect_gii"
_GII_FILENAME = "collect_gii.py"
_RII_MODULE = "collect_de_rii"
_RII_FILENAME = "collect_de_rii.py"
_SOURCE_NAME = "rii"
_CLAIM_FIELDS = ("source_schema_id", "schema_version")


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the RII reader in the caselaw register."""


class RiiAdapterRejected(ValueError):
    """The row is not an RII fixture for ``legal-corpus.caselaw@1``."""


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


def _assigned_string(path: Path, name: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or value.value.strip() == "":
        raise AdapterBindingError(f"{name} in {path} is not a string")
    return value.value


def _find_function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AdapterBindingError(f"{name} is missing from {path}")


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
            keys: list[str] = []
            good = True
            for key in node.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    good = False
                    break
                keys.append(key.value)
            if good and keys:
                found.append(tuple(keys))
    return found


def _column_list(path: Path, fn_name: str, anchor: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for keys in _key_tuples(_find_function(path, fn_name)):
        if anchor in keys and keys not in matches:
            matches.append(keys)
    if len(matches) != 1:
        raise AdapterBindingError(f"{path} {fn_name} column list count for {anchor} is {len(matches)}")
    return matches[0]


def _keyword_constant(path: Path, fn_name: str, anchor: str, keyword: str) -> str:
    """Read one string constant from the ``parse`` row. It is not a schema id."""

    found: list[str] = []
    for node in ast.walk(_find_function(path, fn_name)):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if not isinstance(func, ast.Name) or func.id != "dict":
            continue
        names = [item.arg for item in call.keywords if item.arg]
        if anchor not in names:
            continue
        for item in call.keywords:
            if item.arg != keyword:
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                found.append(item.value.value)
    if len(found) != 1 or found[0].strip() == "":
        raise AdapterBindingError(f"{path} {fn_name} {keyword} constant count is {len(found)}")
    return found[0]


def _string_dict_entries(path: Path, wanted: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Read selected catalog rows. The catalog file is not imported or edited."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rows: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        fields: dict[str, str] = {}
        good = True
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                good = False
                break
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                fields[key.value] = value.value
        if not good:
            continue
        module = fields.get("module", "")
        if module in wanted and module not in rows:
            rows[module] = fields
    missing = [name for name in wanted if name not in rows]
    if missing:
        raise AdapterBindingError(f"catalog is missing {missing}")
    return rows


def _refuse_schema_alias(value: str, label: str) -> None:
    if value in {_UNVERSIONED_SCHEMA_ID, _GII_MODULE, _GII_FILENAME, _STATUTE_SCHEMA_ID, _RII_MODULE}:
        raise AdapterBindingError(f"{label} was bound as a schema id or GII module")


def _bind_rii() -> tuple[tuple[str, ...], str, str, str]:
    """Read the RII schema id, column order, and row constants from the collector file."""

    if "SCHEMA_VERSION" in _names_assigned(_RII):
        raise AdapterBindingError(f"{_RII} assigns SCHEMA_VERSION")
    if _GII_MODULE in _function_names(_RII):
        raise AdapterBindingError("RII collector defines collect_gii")
    if _GII_MODULE in _function_names(Path(__file__)):
        raise AdapterBindingError("RII adapter defines collect_gii")
    columns = _column_list(_RII, "parse", "rii_doknr")
    if columns[-4:] != ("rii_doknr", "doctype", "norm", "config"):
        raise AdapterBindingError("RII columns do not end in rii_doknr, doctype, norm, config")
    if "dila_id" in columns:
        raise AdapterBindingError("RII columns include dila_id")
    config = _keyword_constant(_RII, "parse", "rii_doknr", "config")
    jurisdiction = _keyword_constant(_RII, "parse", "rii_doknr", "jurisdiction")
    licence = _assigned_string(_RII, "LIC")
    for label, value in (("config", config), ("jurisdiction", jurisdiction), ("LIC", licence)):
        _refuse_schema_alias(value, label)
    statute = _bound_string(_STATUTE, "SCHEMA_VERSION", _STATUTE_SCHEMA_ID)
    if statute == _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("statute schema id collided with the RII schema id")
    catalog_rows = _string_dict_entries(_CATALOG, (_GII_MODULE, _RII_MODULE))
    gii = catalog_rows[_GII_MODULE]
    rii_row = catalog_rows[_RII_MODULE]
    if gii.get("filename") != _GII_FILENAME or gii.get("iso") != "de":
        raise AdapterBindingError("catalog GII row is not the Germany statute collector")
    if rii_row.get("filename") != _RII_FILENAME or rii_row.get("iso") != "de":
        raise AdapterBindingError("catalog RII row drifted")
    if rii_row.get("module") == _GII_MODULE or gii.get("module") != _GII_MODULE:
        raise AdapterBindingError("RII catalog row replaced collect_gii")
    if "get_national_collector" not in _function_names(_CATALOG):
        raise AdapterBindingError("catalog is missing get_national_collector")
    return columns, config, jurisdiction, licence


def _load_caselaw_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm038_caselaw_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"caselaw kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _INTERFACE_ID:
        raise AdapterBindingError("caselaw kind does not export legal-corpus.caselaw@1")
    if getattr(module, "SOURCE_SCHEMA_IDS", {}).get(_SOURCE_NAME) != _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("caselaw kind RII schema id is not unversioned")
    if tuple(getattr(module, "RII_COLUMNS", ())) != RII_COLUMNS:
        raise AdapterBindingError("caselaw kind RII columns drifted")
    if getattr(module, "SOURCE_DATASETS", {}).get(_SOURCE_NAME) != _RII_RELATIVE:
        raise AdapterBindingError("caselaw kind RII source path drifted")
    if _GII_MODULE in str(getattr(module, "SOURCE_DATASETS", {}).get(_SOURCE_NAME, "")):
        raise AdapterBindingError("caselaw kind bound RII to collect_gii")
    return module


RII_COLUMNS, RII_CONFIG, RII_JURISDICTION, LIC = _bind_rii()
RII_SCHEMA_ID = _UNVERSIONED_SCHEMA_ID
INTERFACE_ID = _INTERFACE_ID
STATUTE_SCHEMA_ID = _STATUTE_SCHEMA_ID
GII_MODULE = _GII_MODULE
_CASELAW = _load_caselaw_kind()
CaselawRejected = _CASELAW.CaselawRejected


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise RiiAdapterRejected("RII row must be a mapping")


def _claim(row: Mapping[str, Any]) -> str:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise RiiAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return RII_SCHEMA_ID
    if any(item != claims[0] for item in claims):
        raise RiiAdapterRejected("source schema id fields disagree")
    return claims[0]


def _body_keys(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(key for key in row if key not in _CLAIM_FIELDS)


def _prepare(row: Mapping[str, Any]) -> dict[str, Any]:
    claim = _claim(row)
    if claim == STATUTE_SCHEMA_ID:
        raise RiiAdapterRejected("statute schema id is rejected")
    if claim in {GII_MODULE, _GII_FILENAME}:
        raise RiiAdapterRejected("collect_gii is not the RII schema id")
    if claim != RII_SCHEMA_ID:
        raise RiiAdapterRejected("source schema id is not the RII schema id")
    prepared = {"source_schema_id": claim}
    for key, value in row.items():
        if key in _CLAIM_FIELDS:
            continue
        prepared[key] = value
    if _body_keys(prepared) != RII_COLUMNS:
        raise RiiAdapterRejected("row is not an RII fixture")
    return prepared


@dataclass(frozen=True)
class RiiAdaptation:
    """One RII fixture carried as ``legal-corpus.caselaw@1``."""

    source_row: Mapping[str, Any]
    instrument: Any
    source_schema_id: str
    source_name: str
    columns: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.source_name != _SOURCE_NAME:
            raise RiiAdapterRejected("row is not an RII fixture")
        if self.source_schema_id != RII_SCHEMA_ID:
            raise RiiAdapterRejected("RII schema id was replaced")
        if self.instrument.kind != "caselaw":
            raise RiiAdapterRejected("output kind is not caselaw")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise RiiAdapterRejected("instrument schema id was replaced")
        if self.instrument.source_schema_version != self.source_schema_id:
            raise RiiAdapterRejected("instrument schema version was replaced")
        if self.instrument.source_dataset != _RII_RELATIVE:
            raise RiiAdapterRejected("RII source path was replaced")
        if GII_MODULE in self.instrument.source_dataset:
            raise RiiAdapterRejected("adapter registered itself as collect_gii")
        row = self.source_row
        fields = self.columns
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise RiiAdapterRejected("RII row must be a mapping")
        if isinstance(fields, (str, bytes)) or not isinstance(fields, Mapping):
            raise RiiAdapterRejected("RII columns must be a mapping")
        if tuple(fields) != RII_COLUMNS:
            raise RiiAdapterRejected("RII column order was replaced")
        for key, value in fields.items():
            if key in _CLAIM_FIELDS:
                raise RiiAdapterRejected("RII columns include a schema claim")
            if key not in row or row[key] != value:
                raise RiiAdapterRejected("RII column was replaced")
        object.__setattr__(self, "columns", MappingProxyType(dict(fields)))

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


class CaselawRiiAdapter:
    """Map one RII fixture onto ``legal-corpus.caselaw@1``."""

    interface_id = INTERFACE_ID
    schema_id = RII_SCHEMA_ID

    def adapt(self, row: Mapping[str, Any]) -> RiiAdaptation:
        _mapping(row)
        prepared = _prepare(row)
        columns = {key: prepared[key] for key in RII_COLUMNS}
        try:
            record = _CASELAW.accept_caselaw_row(prepared)
        except CaselawRejected as exc:
            raise RiiAdapterRejected(str(exc)) from exc
        if dict(record.source_row) != prepared:
            raise RiiAdapterRejected("RII row was rewritten")
        if record.source_name != _SOURCE_NAME:
            raise RiiAdapterRejected("row is not an RII fixture")
        return RiiAdaptation(
            source_row=record.source_row,
            instrument=record.instrument,
            source_schema_id=record.source_schema_id,
            source_name=record.source_name,
            columns=columns,
        )
