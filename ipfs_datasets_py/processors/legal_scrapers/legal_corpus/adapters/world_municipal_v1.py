"""Adapt a world-municipal row into ``legal-corpus.municipal-instrument@1``.

The 19 canonical columns are read from ``world_municipal/schema.py``.
A trailing provenance column stays on the row. A reordered column is
rejected. This module does not call ``build_schema`` and does not upload
a municipal shard.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

_SCHEMA = Path(__file__).resolve().parents[2] / "world_municipal" / "schema.py"
_KIND = Path(__file__).resolve().parents[1] / "kinds" / "municipal_instrument_v1.py"

_SOURCE_SCHEMA_FILE = "world_municipal/schema.py"
_READ_INTERFACE = "legal-corpus.municipal-instrument@1"
_READ_KIND = "municipal_instrument"


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to ``world_municipal/schema.py`` or the municipal kind."""


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


def _bound_columns(path: Path, name: str) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise AdapterBindingError(f"{name} in {path} is not a sequence")
    columns: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise AdapterBindingError(f"{name} in {path} contains a non-string")
        columns.append(item.value)
    if not columns:
        raise AdapterBindingError(f"{name} in {path} is empty")
    return tuple(columns)


def _assigned_names(path: Path) -> set[str]:
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


if _SCHEMA.parts[-2:] != ("world_municipal", "schema.py"):
    raise AdapterBindingError(f"{_SCHEMA} is not world_municipal/schema.py")
if "SCHEMA_VERSION" in _assigned_names(_SCHEMA):
    raise AdapterBindingError(f"{_SCHEMA} assigns SCHEMA_VERSION")
if "build_schema" not in {
    node.name
    for node in ast.parse(_SCHEMA.read_text(encoding="utf-8"), filename=str(_SCHEMA)).body
    if isinstance(node, ast.FunctionDef)
}:
    raise AdapterBindingError(f"{_SCHEMA} does not define build_schema")

EXPECTED_COLUMNS = _bound_columns(_SCHEMA, "EXPECTED_COLUMNS")
if len(EXPECTED_COLUMNS) != 19:
    raise AdapterBindingError(
        f"EXPECTED_COLUMNS in {_SCHEMA} has {len(EXPECTED_COLUMNS)} names, not 19"
    )


def _load_municipal_kind() -> Any:
    """Load the municipal kind from its file. This does not import ``schema.py``."""

    spec = importlib.util.spec_from_file_location("_lcm031_municipal_instrument_v1", _KIND)
    if spec is None or spec.loader is None:
        raise AdapterBindingError(f"municipal kind is missing at {_KIND}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "INTERFACE_ID", "") != _READ_INTERFACE:
        raise AdapterBindingError("municipal kind does not export legal-corpus.municipal-instrument@1")
    if getattr(module, "SOURCE_SCHEMA_FILE", "") != _SOURCE_SCHEMA_FILE:
        raise AdapterBindingError("municipal kind does not cite world_municipal/schema.py")
    if getattr(module, "CANONICAL_COLUMNS", ()) != EXPECTED_COLUMNS:
        raise AdapterBindingError("municipal kind columns drifted from world_municipal/schema.py")
    return module


_MUNICIPAL = _load_municipal_kind()
INTERFACE_ID = _MUNICIPAL.INTERFACE_ID
SOURCE_SCHEMA_FILE = _MUNICIPAL.SOURCE_SCHEMA_FILE
SOURCE_SCHEMA_VERSION = _MUNICIPAL.SOURCE_SCHEMA_FILE
MunicipalRejected = _MUNICIPAL.MunicipalRejected


def adapt_world_municipal_row(row: Mapping[str, Any]) -> Any:
    """Read one fixture and emit a ``legal-corpus.municipal-instrument@1`` record.

    The first 19 keys must be ``EXPECTED_COLUMNS`` in that order. A
    provenance column after those 19 is kept. ``source_schema_version``
    cites ``world_municipal/schema.py``. No shard upload runs.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise MunicipalRejected("municipal row must be a mapping")
    keys = tuple(row)
    if keys[: len(EXPECTED_COLUMNS)] != EXPECTED_COLUMNS:
        raise MunicipalRejected(
            "canonical columns must be the first 19 in order; "
            "extra columns are only allowed after those 19"
        )
    record = _MUNICIPAL.accept_municipal_row(row)
    if record.instrument.kind != _READ_KIND:
        raise MunicipalRejected("output kind is not municipal_instrument")
    if record.instrument.source_schema_version != SOURCE_SCHEMA_VERSION:
        raise MunicipalRejected("source version does not cite world_municipal/schema.py")
    if record.instrument.source_schema_id != SOURCE_SCHEMA_FILE:
        raise MunicipalRejected("source schema id does not cite world_municipal/schema.py")
    return record
