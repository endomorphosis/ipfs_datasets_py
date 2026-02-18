#!/usr/bin/env python3
"""Generate a lightweight static import graph for ipfs_datasets_py.logic.

Goal:
- AST-only (no importing project code)
- Deterministic, fast, OOM-safe
- Outputs a JSON adjacency list, optionally a DOT graph

Usage:
  python scripts/generate_logic_import_graph.py --out tmp/logic_import_graph.json
  python scripts/generate_logic_import_graph.py --dot tmp/logic_import_graph.dot

By default this script:
- scans ipfs_datasets_py/logic/**/*.py
- resolves absolute + relative imports into fully-qualified module names
- keeps only edges where both sides are within ipfs_datasets_py.logic.*
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "ipfs_datasets_py"
LOGIC_ROOT = PKG_ROOT / "logic"
LOGIC_PREFIX = "ipfs_datasets_py.logic"


@dataclass(frozen=True)
class ImportEdge:
    src: str
    dst: str
    file: str
    lineno: int


def _module_for_file(py_file: Path) -> str:
    rel = py_file.relative_to(PKG_ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return "ipfs_datasets_py." + ".".join(parts)


def _resolve_from_import(current_module: str, level: int, module: str | None) -> str | None:
    if level == 0:
        return module

    current_parts = current_module.split(".")
    up = level
    if up > len(current_parts):
        return None

    base_parts = current_parts[:-up]
    if module:
        base_parts.append(module)
    return ".".join(base_parts)


def _iter_edges(py_file: Path) -> Iterable[ImportEdge]:
    text = py_file.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(text, filename=str(py_file))
    current_module = _module_for_file(py_file)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield ImportEdge(
                    src=current_module,
                    dst=alias.name,
                    file=str(py_file.relative_to(REPO_ROOT)),
                    lineno=node.lineno,
                )
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_import(current_module, node.level, node.module)
            if resolved:
                yield ImportEdge(
                    src=current_module,
                    dst=resolved,
                    file=str(py_file.relative_to(REPO_ROOT)),
                    lineno=node.lineno,
                )


def _logic_py_files() -> list[Path]:
    if not LOGIC_ROOT.is_dir():
        raise SystemExit(f"logic root not found: {LOGIC_ROOT}")

    files: list[Path] = []
    for py_file in LOGIC_ROOT.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        files.append(py_file)
    return sorted(files)


def build_graph() -> tuple[dict[str, list[str]], list[ImportEdge]]:
    edges: list[ImportEdge] = []
    for py_file in _logic_py_files():
        for edge in _iter_edges(py_file):
            edges.append(edge)

    # Keep only edges within the logic namespace.
    logic_edges = [e for e in edges if e.src.startswith(LOGIC_PREFIX) and e.dst.startswith(LOGIC_PREFIX)]

    adj: dict[str, set[str]] = {}
    for e in logic_edges:
        adj.setdefault(e.src, set()).add(e.dst)
        adj.setdefault(e.dst, set())

    adj_list = {k: sorted(v) for k, v in sorted(adj.items())}
    return adj_list, logic_edges


def to_dot(adj: dict[str, list[str]]) -> str:
    lines = ["digraph logic_imports {"]
    for src, dsts in adj.items():
        if not dsts:
            lines.append(f"  \"{src}\";")
        for dst in dsts:
            lines.append(f"  \"{src}\" -> \"{dst}\";")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Write JSON adjacency list to this path")
    parser.add_argument("--dot", type=Path, default=None, help="Write GraphViz DOT to this path")
    args = parser.parse_args()

    adj, _ = build_graph()

    payload = {
        "namespace": LOGIC_PREFIX,
        "root": str(LOGIC_ROOT.relative_to(REPO_ROOT)),
        "adjacency": adj,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))

    if args.dot:
        args.dot.parent.mkdir(parents=True, exist_ok=True)
        args.dot.write_text(to_dot(adj), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
