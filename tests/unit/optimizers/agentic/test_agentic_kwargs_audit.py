"""Prevent `**kwargs` API sprawl in agentic optimizer modules."""

from __future__ import annotations

import ast
from pathlib import Path


def test_agentic_modules_avoid_variadic_kwargs_signatures() -> None:
    root = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py"
        / "optimizers"
        / "agentic"
    )
    assert root.exists()

    offenders: list[tuple[str, int, str]] = []
    for py_file in root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.args.kwarg is not None:
                offenders.append((str(py_file.relative_to(root)), node.lineno, node.name))

    assert not offenders, "Found `**kwargs` signatures:\n" + "\n".join(
        f"- {path}:{line} {name}()" for path, line, name in offenders
    )
