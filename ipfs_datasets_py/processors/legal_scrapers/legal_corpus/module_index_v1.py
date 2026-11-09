"""Canonical index of the landed kind and adapter version ids.

Each version id is read from the kind or adapter module that defines it.
This module loads those files by path. It does not import the package
initializer, the 17 quarantine notes, the SkillCenter v3 copies, or a
scraper module. It does not edit ``legal_corpus/__init__.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

_CORPUS = Path(__file__).resolve().parent
_NOTES = _CORPUS / "quarantine_notes_v1.py"
_ROLES = ("kinds", "adapters")
_EXACT_VERSION_NAMES = frozenset({
    "INTERFACE_ID",
    "SCHEMA_VERSION",
    "SOURCE_SCHEMA_FILE",
    "SOURCE_SCHEMA_VERSION",
    "SOURCE_SCHEMA_ID",
    "SOURCE_SCHEMA_IDS",
    "VERIFY_SCHEMA_VERSION",
    "UNVERSIONED_SCHEMA_ID",
    "LAW_SOURCE_SCHEMA",
})
_VERSION_SUFFIXES = (
    "_SCHEMA_ID",
    "_SCHEMA_IDS",
    "_SCHEMA_VERSION",
    "_INTERFACE_ID",
)
_COPY_MARKERS = (
    "justicedao__ipfs_argentina_laws-ir",
    "justicedao__ipfs_malta_laws-ir",
)


class IndexBindingError(RuntimeError):
    """The index is not bound to the landed kind and adapter modules."""


def _load_file(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise IndexBindingError(f"module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_NOTES_MODULE = _load_file(_NOTES, "lcm_index_quarantine_notes_v1")
skip_quarantine_notes = _NOTES_MODULE.skip_quarantine_notes
is_quarantine_note = _NOTES_MODULE.is_quarantine_note
QUARANTINE_NOTE_FILENAMES = tuple(_NOTES_MODULE.QUARANTINE_NOTE_FILENAMES)


def _version_name(name: str) -> bool:
    token = name[1:] if name.startswith("_") and not name.startswith("__") else name
    if not token.isupper():
        return False
    if token in _EXACT_VERSION_NAMES:
        return True
    return token.endswith(_VERSION_SUFFIXES)


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, dict):
        found: list[str] = []
        for item in value.values():
            found.extend(_strings(item))
        return tuple(found)
    if isinstance(value, (tuple, list, set, frozenset)):
        found = []
        for item in value:
            found.extend(_strings(item))
        return tuple(found)
    return ()


def version_ids_of(module: ModuleType) -> tuple[str, ...]:
    """Return the version ids assigned on one landed module."""

    found: list[str] = []
    for name, value in vars(module).items():
        if _version_name(name):
            found.extend(_strings(value))
    return tuple(dict.fromkeys(found))


def _module_paths(role: str) -> tuple[str, ...]:
    if role not in _ROLES:
        raise IndexBindingError(f"unknown index role {role}")
    folder = _CORPUS / role
    found = tuple(sorted(
        path.relative_to(_CORPUS).as_posix()
        for path in folder.glob("*.py")
        if path.is_file() and path.name != "__init__.py"
    ))
    kept = tuple(skip_quarantine_notes(found))
    if kept != found:
        raise IndexBindingError(f"a {role} path names a quarantine note")
    if not kept:
        raise IndexBindingError(f"no {role} modules are landed")
    return kept


def _refuse_path(relative: str) -> None:
    if is_quarantine_note(relative):
        raise IndexBindingError(f"quarantine note is not an index module: {relative}")
    for marker in _COPY_MARKERS:
        if marker in relative:
            raise IndexBindingError(f"SkillCenter copy is not an index module: {relative}")
    path = (_CORPUS / relative).resolve()
    if path != _CORPUS and _CORPUS not in path.parents:
        raise IndexBindingError(f"path escapes the corpus package: {relative}")
    if path.suffix != ".py" or not path.is_file():
        raise IndexBindingError(f"index module is missing: {relative}")
    parts = path.relative_to(_CORPUS).parts
    if len(parts) != 2 or parts[0] not in _ROLES:
        raise IndexBindingError(f"index module is outside kinds and adapters: {relative}")


@dataclass(frozen=True)
class IndexedModule:
    """One landed module and the version ids it assigns."""

    role: str
    path: str
    version_ids: tuple[str, ...]


def _index_role(role: str) -> tuple[IndexedModule, ...]:
    rows: list[IndexedModule] = []
    for relative in _module_paths(role):
        _refuse_path(relative)
        loaded = _load_file(_CORPUS / relative, "lcm_index_" + relative.replace("/", "_").removesuffix(".py"))
        version_ids = version_ids_of(loaded)
        if not version_ids:
            raise IndexBindingError(f"{relative} assigns no version id")
        for version_id in version_ids:
            if is_quarantine_note(version_id):
                raise IndexBindingError(f"{relative} lists a quarantine note as a version id")
            for marker in _COPY_MARKERS:
                if marker in version_id:
                    raise IndexBindingError(f"{relative} lists a SkillCenter copy as a version id")
        rows.append(IndexedModule(role, relative, version_ids))
    return tuple(rows)


def indexed_paths(paths: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Keep index paths. Quarantine note filenames are dropped."""

    return tuple(skip_quarantine_notes(paths))


KIND_INDEX = _index_role("kinds")
ADAPTER_INDEX = _index_role("adapters")
INDEX = KIND_INDEX + ADAPTER_INDEX


def kind_version_ids() -> tuple[str, ...]:
    """Every kind version id, in module order, without repeats."""

    return tuple(dict.fromkeys(version_id for row in KIND_INDEX for version_id in row.version_ids))


def adapter_version_ids() -> tuple[str, ...]:
    """Every adapter version id, in module order, without repeats."""

    return tuple(dict.fromkeys(version_id for row in ADAPTER_INDEX for version_id in row.version_ids))
