from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


_IPFS_DATASETS_PKG_ROOT = Path(__file__).resolve().parents[3] / "ipfs_datasets_py"
_LOGIC_ROOT = _IPFS_DATASETS_PKG_ROOT / "logic"


@dataclass(frozen=True)
class ImportFinding:
    file: Path
    lineno: int
    imported: str


def _module_name_for_file(py_file: Path) -> str:
    rel = py_file.relative_to(_IPFS_DATASETS_PKG_ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts)


def _resolve_from_import(current_module: str, level: int, module: str | None) -> str | None:
    if level == 0:
        return module

    current_parts = current_module.split(".")

    # For `from .foo import bar` inside pkg `a.b.c`, ast gives level=1 and module="foo".
    # The import base becomes `a.b.foo`.
    up = level
    if up > len(current_parts):
        return None

    base_parts = current_parts[:-up]
    if module:
        base_parts.append(module)

    return ".".join(base_parts)


def _iter_imports(py_file: Path) -> list[ImportFinding]:
    text = py_file.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(text, filename=str(py_file))

    current_module = _module_name_for_file(py_file)
    findings: list[ImportFinding] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                findings.append(ImportFinding(py_file, node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_import(current_module, node.level, node.module)
            if resolved:
                findings.append(ImportFinding(py_file, node.lineno, resolved))

    return findings


def test_common_and_types_do_not_import_integration_or_heavy_layers() -> None:
    assert _LOGIC_ROOT.is_dir(), str(_LOGIC_ROOT)

    # Keep this list narrow and uncontroversial: these are orchestration/heavy layers
    # that should not be pulled into dependency-light primitives.
    forbidden_prefixes = (
        "ipfs_datasets_py.logic.integration",
        "ipfs_datasets_py.logic.external_provers",
        "ipfs_datasets_py.logic.ml_confidence",
        "ipfs_datasets_py.logic.zkp",
        "ipfs_datasets_py.logic.tools",
        "ipfs_datasets_py.logic.cli",
    )

    candidates: list[Path] = []
    for subdir in ("common", "types"):
        for py_file in (_LOGIC_ROOT / subdir).rglob("*.py"):
            # Skip cached artifacts.
            if "__pycache__" in py_file.parts:
                continue
            candidates.append(py_file)

    violations: list[ImportFinding] = []
    for py_file in candidates:
        for finding in _iter_imports(py_file):
            if finding.imported.startswith(forbidden_prefixes):
                violations.append(finding)

    assert violations == [], [
        f"{v.file.relative_to(_IPFS_DATASETS_PKG_ROOT)}:{v.lineno} imports {v.imported}"
        for v in violations
    ]
