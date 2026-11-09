"""LCM-041: closed national routes stay closed.

The catalog names a statute route in a summary phrase such as
"the France statute route". France's lookup is ``collect_legi``.
Germany's is ``collect_gii``. Belgium, Portugal, Lithuania, and Ghana
have no such phrase. This test only reads the catalog and the adapter
directory.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

_DATASETS = Path(__file__).resolve().parents[3]
_CATALOG_PATH = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/national_collectors/catalog.py"
)
_ADAPTERS = (
    _DATASETS
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/adapters"
)
_STATUTE_COLLECTOR = {"fr": "collect_legi", "de": "collect_gii"}
_CLOSED_COLLECTOR = {
    "be": "collect_be",
    "pt": "collect_pt",
    "lt": "collect_lt",
    "gh": "collect_gh",
}
_CLOSED_COUNTRIES = ("belgium", "portugal", "lithuania", "ghana")
_CLOSED_KEYS = frozenset({*_CLOSED_COLLECTOR, *_CLOSED_COUNTRIES})
_CLOSED_MODULES = frozenset({
    "collect_be",
    "collect_pt",
    "collect_lt",
    "collect_gh",
    "collect_lt_eseimas",
    "collect_pt_1s_pdf",
    "collect_pt_dre_archive",
    "collect_pt_ro_lt_archives",
})
_ROUTE_CALLS = frozenset({"get", "get_national_collector"})


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _assignment(path: Path, name: str) -> ast.AST | None:
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
            assert found is None
            found = value
    return found


def _defines_get(path: Path) -> bool:
    return "get" in _functions(path) or _assignment(path, "get") is not None


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _module_of(found: object) -> str:
    module = getattr(found, "module", "")
    filename = getattr(found, "filename", "")
    assert isinstance(module, str) and module
    if isinstance(filename, str) and filename:
        assert filename == f"{module}.py"
    return module


def _resolve(catalog, key: str) -> str:
    """Return the collector ``get(key)`` names, or the national lookup."""

    named = None
    if "get_national_collector" in _functions(_CATALOG_PATH):
        named = _module_of(catalog.get_national_collector(key))
    if _defines_get(_CATALOG_PATH):
        resolved = _module_of(catalog.get(key))
        if named is not None:
            assert resolved == named, f"get({key!r}) changed collector"
        return resolved
    assert named is not None, "catalog has no collector lookup"
    return named


def _closed_row(spec: object) -> bool:
    iso = str(getattr(spec, "iso", "") or "").casefold()
    slug = str(getattr(spec, "slug", "") or "").casefold()
    country = str(getattr(spec, "country", "") or "").casefold()
    return iso in _CLOSED_COLLECTOR or slug in _CLOSED_KEYS or country in _CLOSED_COUNTRIES


def _adapter_registers(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in _CLOSED_MODULES:
                return node.name
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in _CLOSED_MODULES:
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in _CLOSED_MODULES:
                return node.value
            lowered = node.value.casefold()
            for country in _CLOSED_COUNTRIES:
                if f"{country} statute route" in lowered:
                    return node.value
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                name = ""
            if name not in _ROUTE_CALLS:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.casefold() in _CLOSED_KEYS
                ):
                    return f"{name}({arg.value})"
    return ""


def test_closed_national_routes_stay_closed() -> None:
    catalog_before = _CATALOG_PATH.read_bytes()
    catalog_text = catalog_before.decode("utf-8")
    folded = catalog_text.casefold()
    for country in _CLOSED_COUNTRIES:
        assert f"{country} statute route" not in folded

    catalog = _load(_CATALOG_PATH, "lcm041_national_catalog")
    assert _resolve(catalog, "fr") == _STATUTE_COLLECTOR["fr"]
    assert _resolve(catalog, "de") == _STATUTE_COLLECTOR["de"]
    assert catalog.BY_ISO["fr"][0].module == "collect_legi"
    assert catalog.BY_ISO["de"][0].module == "collect_gii"
    for key, module in _CLOSED_COLLECTOR.items():
        assert _resolve(catalog, key) == module
        assert catalog.BY_ISO[key][0].module == module

    closed_rows = [spec for spec in catalog.COLLECTORS if _closed_row(spec)]
    assert closed_rows
    for spec in closed_rows:
        assert "statute route" not in spec.summary.casefold()
        assert spec.module not in _STATUTE_COLLECTOR.values()

    adapters = sorted(path for path in _ADAPTERS.glob("*.py") if path.is_file())
    assert adapters
    for path in adapters:
        registered = _adapter_registers(path)
        assert registered == "", f"{path.name} registers a closed route ({registered})"

    assert _CATALOG_PATH.read_bytes() == catalog_before
