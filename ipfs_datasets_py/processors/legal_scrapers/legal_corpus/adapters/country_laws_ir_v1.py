"""Adapt a country-laws IR row into ``legal-corpus.law@1``.

Required columns and ``SCHEMA_VERSION`` are read from ``country_laws_ir``.
The adapter copies the fixture through the law kind. It does not import
``query.py``, open a socket, or define ``document_shard_paths``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

_COUNTRY_LAWS = Path(__file__).resolve().parents[2] / "country_laws_ir"
_PACKAGE_SCHEMA = _COUNTRY_LAWS / "__init__.py"
_COLUMN_SCHEMA = _COUNTRY_LAWS / "schema.py"
_LAW_KIND = Path(__file__).resolve().parents[1] / "kinds" / "law_v1.py"

_READ_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
_READ_LAW_COLUMNS = ("id", "title", "text")
_READ_INTERFACE = "legal-corpus.law@1"


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to the country-laws register or the law kind."""


def _module_assignment(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
            return value
    raise AdapterBindingError(f"{name} is missing from {path}")


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise AdapterBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise AdapterBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _bound_columns(path: Path, name: str) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise AdapterBindingError(f"{name} in {path} is not a sequence")
    columns: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise AdapterBindingError(f"{name} in {path} contains a non-string")
        columns.append(item.value)
    return tuple(columns)


SOURCE_SCHEMA_VERSION = _bound_string(
    _PACKAGE_SCHEMA,
    "SCHEMA_VERSION",
    _READ_SCHEMA_VERSION,
)
REQUIRED_LAW_COLUMNS = _bound_columns(_COLUMN_SCHEMA, "REQUIRED_LAW_COLUMNS")
if REQUIRED_LAW_COLUMNS != _READ_LAW_COLUMNS:
    raise AdapterBindingError(
        f"required law columns are {REQUIRED_LAW_COLUMNS!r}, not {_READ_LAW_COLUMNS!r}"
    )


def _load_law_kind() -> Any:
    """Load the law kind from its file. This does not import ``query.py``."""

    spec = importlib.util.spec_from_file_location("_lcm_law_v1_for_country_laws_ir", _LAW_KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"law kind is missing at {_LAW_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _READ_INTERFACE:
        raise AdapterBindingError("law kind does not export legal-corpus.law@1")
    if getattr(module, "SOURCE_SCHEMA_VERSION", "") != SOURCE_SCHEMA_VERSION:
        raise AdapterBindingError("law kind source schema version drifted")
    if getattr(module, "REQUIRED_LAW_COLUMNS", ()) != REQUIRED_LAW_COLUMNS:
        raise AdapterBindingError("law kind required columns drifted")
    return module


_LAW = _load_law_kind()
INTERFACE_ID = _LAW.INTERFACE_ID
LawRejected = _LAW.LawRejected


def adapt_country_laws_ir_row(row: Mapping[str, Any]) -> Any:
    """Read one fixture and emit a ``legal-corpus.law@1`` record.

    Columns are required in ``REQUIRED_LAW_COLUMNS`` order. Every key on
    the fixture is kept. ``source_schema_version`` stays
    ``country-laws-ir-graphrag/v1``. No shard lookup runs.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise LawRejected("law row must be a mapping")
    for column in REQUIRED_LAW_COLUMNS:
        if column not in row:
            raise LawRejected(f"missing required column {column}")
    record = _LAW.accept_law_row(row)
    if record.interface_id != INTERFACE_ID:
        raise LawRejected("emitted interface is not legal-corpus.law@1")
    if record.source_schema_version != SOURCE_SCHEMA_VERSION:
        raise LawRejected("source_schema_version was replaced")
    return record
