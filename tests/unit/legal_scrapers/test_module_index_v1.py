"""LCM-050: the canonical index lists landed kind and adapter version ids.

Importing the index must not import the 17 note files, the SkillCenter v3
copies, or a scraper module. ``legal_corpus/__init__.py`` stays unchanged.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_LIFT = _DATASETS.parents[1]
_CORPUS = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus"
_INDEX = _CORPUS / "module_index_v1.py"
_INIT = _CORPUS / "__init__.py"
_PLAN = _LIFT / "implementation_plan/legal_corpus_modules/PLAN.md"
_NOTES = _CORPUS / "quarantine_notes_v1.py"
_NOTE_DIR = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/legal_scrapers"
)
_COPIES = (
    "justicedao__ipfs_argentina_laws-ir",
    "justicedao__ipfs_malta_laws-ir",
)
_HUB = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/hub_dataset_scripts"
_ALLOWED_IMPORTS = frozenset({
    "__future__",
    "importlib.util",
    "sys",
    "dataclasses",
    "pathlib",
    "types",
})


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plan_names(text: str) -> tuple[str, ...]:
    sentence = ""
    for line in text.splitlines():
        if "The names are `" in line:
            sentence = line
            break
    assert sentence
    return tuple(re.findall(r"`([^`]+\.py)`", sentence))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in {"import_module", "__import__"}:
                found.append(name)
    return found


def _disk_modules(role: str) -> tuple[str, ...]:
    folder = _CORPUS / role
    return tuple(sorted(
        path.relative_to(_CORPUS).as_posix()
        for path in folder.glob("*.py")
        if path.is_file() and path.name != "__init__.py"
    ))


def _public_version_ids(module) -> tuple[str, ...]:
    found: list[str] = []
    interface = getattr(module, "INTERFACE_ID", None)
    if isinstance(interface, str) and interface.strip():
        found.append(interface.strip())
    schema = getattr(module, "SCHEMA_VERSION", None)
    if isinstance(schema, str) and schema.strip():
        found.append(schema.strip())
    source_ids = getattr(module, "SOURCE_SCHEMA_IDS", None)
    if isinstance(source_ids, (tuple, list)):
        found.extend(item for item in source_ids if isinstance(item, str))
    elif isinstance(source_ids, dict):
        found.extend(item for item in source_ids.values() if isinstance(item, str))
    sections = getattr(module, "_SECTION_SCHEMA_IDS", None)
    if isinstance(sections, dict):
        for value in sections.values():
            if isinstance(value, (tuple, list, set, frozenset)):
                found.extend(item for item in value if isinstance(item, str))
    return tuple(dict.fromkeys(found))


def test_index_lists_every_kind_and_adapter_version_without_side_effects() -> None:
    names = _plan_names(_PLAN.read_text(encoding="utf-8"))
    assert len(names) == 17
    assert len(set(names)) == 17
    note_paths = tuple(_NOTE_DIR / name for name in names)
    note_bytes = {path: path.read_bytes() for path in note_paths}
    copy_inits = tuple(_HUB / copy / "country_laws_ir" / "__init__.py" for copy in _COPIES)
    for path in copy_inits:
        assert path.is_file()
    copy_bytes = {path: path.read_bytes() for path in copy_inits}
    init_bytes = _INIT.read_bytes()
    assert b"module_index_v1" not in init_bytes
    assert _imports(_INDEX) == [
        "__future__",
        "importlib.util",
        "sys",
        "dataclasses",
        "pathlib",
        "types",
    ]
    assert set(_imports(_INDEX)) <= _ALLOWED_IMPORTS

    loaded_before = set(sys.modules)
    index = _load(_INDEX, "lcm050_module_index_v1")
    loaded = set(sys.modules) - loaded_before
    source = _INDEX.read_text(encoding="utf-8")

    assert tuple(row.path for row in index.KIND_INDEX) == _disk_modules("kinds")
    assert tuple(row.path for row in index.ADAPTER_INDEX) == _disk_modules("adapters")
    assert index.INDEX == index.KIND_INDEX + index.ADAPTER_INDEX
    assert index.kind_version_ids()
    assert index.adapter_version_ids()

    for row in index.INDEX:
        assert row.role in {"kinds", "adapters"}
        assert row.path.startswith(row.role + "/")
        fresh = _load(_CORPUS / row.path, "lcm050_check_" + row.path.replace("/", "_"))
        assert index.version_ids_of(fresh) == row.version_ids
        for version_id in _public_version_ids(fresh):
            assert version_id in row.version_ids
            assert version_id not in source
        for version_id in row.version_ids:
            assert version_id not in source
            assert isinstance(version_id, str) and version_id.strip()

    mixed = names + ("kinds/law_v1.py",)
    assert index.indexed_paths(mixed) == ("kinds/law_v1.py",)
    assert index.QUARANTINE_NOTE_FILENAMES == names
    notes = _load(_NOTES, "lcm050_quarantine_notes_v1")
    assert notes.QUARANTINE_NOTE_FILENAMES == names

    for name, module in sys.modules.items():
        if name not in loaded and name not in loaded_before:
            continue
        if name not in loaded:
            continue
        module_file = str(getattr(module, "__file__", "") or "")
        for note in names:
            assert note not in name
            assert not module_file.endswith("/" + note)
        for copy in _COPIES:
            assert copy not in name
            assert copy not in module_file
        if "/legal_scrapers/" in module_file:
            assert "/legal_corpus/" in module_file

    assert _INIT.read_bytes() == init_bytes
    for path, raw in note_bytes.items():
        assert path.read_bytes() == raw
    for path, raw in copy_bytes.items():
        assert path.read_bytes() == raw
