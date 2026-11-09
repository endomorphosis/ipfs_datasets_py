"""LCM-043: the Argentina and Malta SkillCenter v3 copies stay in place.

Intent IR and the legal-IR autoencoder are out of scope. This test reads
the two hyphenated hub copies and ``instrument_v1.py``. It does not import
those copies and it does not move them onto ``country-laws-ir-graphrag/v1``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_HUB = _DATASETS / "ipfs_datasets_py/processors/legal_scrapers/hub_dataset_scripts"
_INSTRUMENT = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/instrument_v1.py"
)
_COPIES = (
    "justicedao__ipfs_argentina_laws-ir",
    "justicedao__ipfs_malta_laws-ir",
)
_SCHEMA = "skillcenter-huggingface-release/v3"
_STATUTE_SCHEMA = "country-laws-ir-graphrag/v1"
_OUT_OF_SCOPE = ("Intent IR", "legal-IR autoencoder")


def _schema_assignments(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
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
        if not any(isinstance(target, ast.Name) and target.id == "SCHEMA_VERSION" for target in targets):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.append(value.value)
        else:
            found.append(type(value).__name__)
    return found


def _imported_modules(path: Path) -> list[str]:
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
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append(arg.value)
    return found


def test_skillcenter_v3_copies_stay_outside_instrument_v1() -> None:
    """Intent IR and the legal-IR autoencoder are out of scope."""

    doc = test_skillcenter_v3_copies_stay_outside_instrument_v1.__doc__ or ""
    assert _OUT_OF_SCOPE == ("Intent IR", "legal-IR autoencoder")
    for lane in _OUT_OF_SCOPE:
        assert lane in doc
    assert "out of scope" in doc

    loaded_before = set(sys.modules)
    instrument_imports = _imported_modules(_INSTRUMENT)
    snapshots: dict[Path, bytes] = {}
    for name in _COPIES:
        root = _HUB / name
        assert root.is_dir()
        init = root / "country_laws_ir" / "__init__.py"
        assert init.is_file()
        reported: list[str] = []
        for path in sorted(item for item in root.rglob("*.py") if item.is_file()):
            snapshots[path] = path.read_bytes()
            reported.extend(_schema_assignments(path))
        assert reported == [_SCHEMA]
        assert _STATUTE_SCHEMA not in init.read_text(encoding="utf-8")
        assert all(name not in imported for imported in instrument_imports)
    for path, raw in snapshots.items():
        assert path.is_file()
        assert path.read_bytes() == raw
    for name, module in sys.modules.items():
        if name not in loaded_before:
            module_file = str(getattr(module, "__file__", "") or "")
            for copy in _COPIES:
                assert copy not in module_file
