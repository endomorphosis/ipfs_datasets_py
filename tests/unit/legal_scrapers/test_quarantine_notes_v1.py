"""LCM-042: the 17 note files stay put and a canonical index can skip them.

The names come from the ``The names are`` sentence in ``PLAN.md``.
Each file is read only to check that its first line still starts with
``linked logs/``. The notes are not imported or rewritten.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_LIFT = _DATASETS.parents[1]
_PLAN = _LIFT / "implementation_plan/legal_corpus_modules/PLAN.md"
_MODULE = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/quarantine_notes_v1.py"
)
_NOTE_DIR = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/legal_scrapers"
)
_KEPT = ("archive_fallbacks.py", "hub_integrated/legal_scrapers/schema.py")


def _plan_names(text: str) -> tuple[str, ...]:
    sentence = ""
    for line in text.splitlines():
        if "The names are `" in line:
            sentence = line
            break
    assert sentence
    return tuple(re.findall(r"`([^`]+\.py)`", sentence))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def test_plan_filenames_stay_in_place_and_an_index_skips_them() -> None:
    names = _plan_names(_PLAN.read_text(encoding="utf-8"))
    assert len(names) == 17
    assert len(set(names)) == 17
    paths = tuple(_NOTE_DIR / name for name in names)
    before = {path: path.read_bytes() for path in paths}
    loaded_before = set(sys.modules)
    module = _load(_MODULE, "lcm042_quarantine_notes_v1")
    loaded = set(sys.modules) - loaded_before
    assert module.QUARANTINE_NOTE_DIR == "hub_integrated/legal_scrapers"
    assert module.QUARANTINE_NOTE_FILENAMES == names
    assert _imports(_MODULE) == ["__future__", "collections.abc"]
    for name in names:
        assert name not in loaded
        assert name[:-3] not in loaded
    for name, path in zip(names, paths):
        assert path.is_file()
        assert path.parent == _NOTE_DIR
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("linked logs/")
        assert module.is_quarantine_note(name)
        assert module.is_quarantine_note(f"hub_integrated/legal_scrapers/{name}")
        assert module.is_quarantine_note(str(path))
    kept = module.skip_quarantine_notes([*names, *_KEPT])
    assert kept == _KEPT
    assert module.is_quarantine_note("al_alfresco_tip26b.py.bak") is False
    assert module.skip_quarantine_notes(["archive_fallbacks.py"]) == ("archive_fallbacks.py",)
    for path, raw in before.items():
        assert path.is_file()
        assert path.read_bytes() == raw
