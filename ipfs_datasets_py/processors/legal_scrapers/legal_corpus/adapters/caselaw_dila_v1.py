"""Adapt a France DILA fixture onto ``legal-corpus.caselaw@1``.

``collect_fr_dila.py`` assigns no ``SCHEMA_VERSION``. The schema id stays
the unversioned id recorded for that file. The row keeps the keys
``parse`` returns. This module reads that file and ``catalog.py`` with
the parser. It does not import the collector, register ``collect_legi``,
or change the France lookup.
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
_DILA = _PROCESSORS / "legal_scrapers/national_collectors/collect_fr_dila.py"
_CATALOG = _PROCESSORS / "legal_scrapers/national_collectors/catalog.py"
_STATUTE = _PROCESSORS / "legal_scrapers/country_laws_ir/__init__.py"
_DILA_RELATIVE = "legal_scrapers/national_collectors/collect_fr_dila.py"

_INTERFACE_ID = "legal-corpus.caselaw@1"
_UNVERSIONED_SCHEMA_ID = "unversioned"
_STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"
_LEGI_MODULE = "collect_legi"
_LEGI_FILENAME = "collect_legi.py"
_SOURCE_NAME = "dila"
_CLAIM_FIELDS = ("source_schema_id", "schema_version")


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the DILA reader in the caselaw register."""


class DilaAdapterRejected(ValueError):
    """The row is not a DILA fixture for ``legal-corpus.caselaw@1``."""


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


def _fonds(path: Path) -> dict[str, str]:
    value = _module_assignment(path, "FONDS")
    if not isinstance(value, ast.Dict) or not value.keys:
        raise AdapterBindingError(f"FONDS in {path} is not a dict")
    found: dict[str, str] = {}
    for key, item in zip(value.keys, value.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise AdapterBindingError(f"FONDS in {path} has a non-string key")
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise AdapterBindingError(f"FONDS in {path} has a non-string value")
        found[key.value] = item.value
    if not found:
        raise AdapterBindingError(f"FONDS in {path} is empty")
    return found


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


def _bind_dila() -> tuple[tuple[str, ...], dict[str, str]]:
    """Read the DILA schema id and column order from the collector file."""

    if "SCHEMA_VERSION" in _names_assigned(_DILA):
        raise AdapterBindingError(f"{_DILA} assigns SCHEMA_VERSION")
    if _LEGI_MODULE in _function_names(_DILA):
        raise AdapterBindingError("DILA collector defines collect_legi")
    if _LEGI_MODULE in _function_names(Path(__file__)):
        raise AdapterBindingError("DILA adapter defines collect_legi")
    columns = _column_list(_DILA, "parse", "dila_id")
    fonds = _fonds(_DILA)
    if any(value in {_UNVERSIONED_SCHEMA_ID, _LEGI_MODULE, _STATUTE_SCHEMA_ID} for value in fonds.values()):
        raise AdapterBindingError("a FONDS value was bound as a schema id or LEGI module")
    if fonds.get("CASS") == _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("CASS config was bound as the DILA schema id")
    statute = _bound_string(_STATUTE, "SCHEMA_VERSION", _STATUTE_SCHEMA_ID)
    if statute == _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("statute schema id collided with the DILA schema id")
    catalog_rows = _string_dict_entries(_CATALOG, (_LEGI_MODULE, "collect_fr_dila"))
    legi = catalog_rows[_LEGI_MODULE]
    dila_row = catalog_rows["collect_fr_dila"]
    if legi.get("filename") != _LEGI_FILENAME or legi.get("iso") != "fr":
        raise AdapterBindingError("catalog LEGI row is not the France statute collector")
    if dila_row.get("filename") != "collect_fr_dila.py" or dila_row.get("iso") != "fr":
        raise AdapterBindingError("catalog DILA row drifted")
    if dila_row.get("module") == _LEGI_MODULE or legi.get("module") != _LEGI_MODULE:
        raise AdapterBindingError("DILA catalog row replaced collect_legi")
    if "get_national_collector" not in _function_names(_CATALOG):
        raise AdapterBindingError("catalog is missing get_national_collector")
    return columns, fonds


def _load_caselaw_kind() -> Any:
    spec = importlib.util.spec_from_file_location("_lcm037_caselaw_kind", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"caselaw kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _INTERFACE_ID:
        raise AdapterBindingError("caselaw kind does not export legal-corpus.caselaw@1")
    if getattr(module, "SOURCE_SCHEMA_IDS", {}).get(_SOURCE_NAME) != _UNVERSIONED_SCHEMA_ID:
        raise AdapterBindingError("caselaw kind DILA schema id is not unversioned")
    if tuple(getattr(module, "DILA_COLUMNS", ())) != DILA_COLUMNS:
        raise AdapterBindingError("caselaw kind DILA columns drifted")
    if getattr(module, "SOURCE_DATASETS", {}).get(_SOURCE_NAME) != _DILA_RELATIVE:
        raise AdapterBindingError("caselaw kind DILA source path drifted")
    if _LEGI_MODULE in str(getattr(module, "SOURCE_DATASETS", {}).get(_SOURCE_NAME, "")):
        raise AdapterBindingError("caselaw kind bound DILA to collect_legi")
    return module


DILA_COLUMNS, FONDS = _bind_dila()
DILA_SCHEMA_ID = _UNVERSIONED_SCHEMA_ID
INTERFACE_ID = _INTERFACE_ID
STATUTE_SCHEMA_ID = _STATUTE_SCHEMA_ID
LEGI_MODULE = _LEGI_MODULE
_CASELAW = _load_caselaw_kind()
CaselawRejected = _CASELAW.CaselawRejected


def _mapping(row: Mapping[str, Any]) -> None:
    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise DilaAdapterRejected("DILA row must be a mapping")


def _claim(row: Mapping[str, Any]) -> str:
    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise DilaAdapterRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        return DILA_SCHEMA_ID
    if any(item != claims[0] for item in claims):
        raise DilaAdapterRejected("source schema id fields disagree")
    return claims[0]


def _body_keys(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(key for key in row if key not in _CLAIM_FIELDS)


def _prepare(row: Mapping[str, Any]) -> dict[str, Any]:
    claim = _claim(row)
    if claim == STATUTE_SCHEMA_ID:
        raise DilaAdapterRejected("statute schema id is rejected")
    if claim == LEGI_MODULE or claim == _LEGI_FILENAME:
        raise DilaAdapterRejected("collect_legi is not the DILA schema id")
    if claim != DILA_SCHEMA_ID:
        raise DilaAdapterRejected("source schema id is not the DILA schema id")
    prepared = {"source_schema_id": claim}
    for key, value in row.items():
        if key in _CLAIM_FIELDS:
            continue
        prepared[key] = value
    if _body_keys(prepared) != DILA_COLUMNS:
        raise DilaAdapterRejected("row is not a DILA fixture")
    return prepared


@dataclass(frozen=True)
class DilaAdaptation:
    """One DILA fixture carried as ``legal-corpus.caselaw@1``."""

    source_row: Mapping[str, Any]
    instrument: Any
    source_schema_id: str
    source_name: str
    columns: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.source_name != _SOURCE_NAME:
            raise DilaAdapterRejected("row is not a DILA fixture")
        if self.source_schema_id != DILA_SCHEMA_ID:
            raise DilaAdapterRejected("DILA schema id was replaced")
        if self.instrument.kind != "caselaw":
            raise DilaAdapterRejected("output kind is not caselaw")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise DilaAdapterRejected("instrument schema id was replaced")
        if self.instrument.source_schema_version != self.source_schema_id:
            raise DilaAdapterRejected("instrument schema version was replaced")
        if self.instrument.source_dataset != _DILA_RELATIVE:
            raise DilaAdapterRejected("DILA source path was replaced")
        if LEGI_MODULE in self.instrument.source_dataset:
            raise DilaAdapterRejected("adapter registered itself as collect_legi")
        row = self.source_row
        fields = self.columns
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise DilaAdapterRejected("DILA row must be a mapping")
        if isinstance(fields, (str, bytes)) or not isinstance(fields, Mapping):
            raise DilaAdapterRejected("DILA columns must be a mapping")
        if tuple(fields) != DILA_COLUMNS:
            raise DilaAdapterRejected("DILA column order was replaced")
        for key, value in fields.items():
            if key in _CLAIM_FIELDS:
                raise DilaAdapterRejected("DILA columns include a schema claim")
            if key not in row or row[key] != value:
                raise DilaAdapterRejected("DILA column was replaced")
        object.__setattr__(self, "columns", MappingProxyType(dict(fields)))

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


class CaselawDilaAdapter:
    """Map one DILA fixture onto ``legal-corpus.caselaw@1``."""

    interface_id = INTERFACE_ID
    schema_id = DILA_SCHEMA_ID

    def adapt(self, row: Mapping[str, Any]) -> DilaAdaptation:
        _mapping(row)
        prepared = _prepare(row)
        columns = {key: prepared[key] for key in DILA_COLUMNS}
        try:
            record = _CASELAW.accept_caselaw_row(prepared)
        except CaselawRejected as exc:
            raise DilaAdapterRejected(str(exc)) from exc
        if dict(record.source_row) != prepared:
            raise DilaAdapterRejected("DILA row was rewritten")
        if record.source_name != _SOURCE_NAME:
            raise DilaAdapterRejected("row is not a DILA fixture")
        return DilaAdaptation(
            source_row=record.source_row,
            instrument=record.instrument,
            source_schema_id=record.source_schema_id,
            source_name=record.source_name,
            columns=columns,
        )
