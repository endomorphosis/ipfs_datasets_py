#!/usr/bin/env python3
"""Generate optimizer API reference from type hints and docstrings."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_MODULES = [
    "ipfs_datasets_py/optimizers/common/base_optimizer.py",
    "ipfs_datasets_py/optimizers/graphrag/ontology_generator.py",
    "ipfs_datasets_py/optimizers/graphrag/ontology_critic.py",
    "ipfs_datasets_py/optimizers/graphrag/ontology_mediator.py",
    "ipfs_datasets_py/optimizers/agentic/cli.py",
]


@dataclass
class FunctionDoc:
    name: str
    signature: str
    summary: str


@dataclass
class ClassDoc:
    name: str
    summary: str
    methods: list[FunctionDoc]


@dataclass
class ModuleDoc:
    path: str
    summary: str
    functions: list[FunctionDoc]
    classes: list[ClassDoc]


def _first_line(docstring: str | None) -> str:
    if not docstring:
        return ""
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _annotation_to_str(node: ast.AST | None) -> str:
    if node is None:
        return "Any"
    return ast.unparse(node)


def _format_params(node: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_self: bool) -> str:
    args = node.args
    params: list[str] = []

    posonly = list(args.posonlyargs)
    positional = list(args.args)

    defaults = list(args.defaults)
    default_start = len(posonly) + len(positional) - len(defaults)

    def _param_text(arg: ast.arg, default_index: int) -> str:
        text = arg.arg
        if arg.annotation is not None:
            text += f": {_annotation_to_str(arg.annotation)}"
        if default_index >= default_start and defaults:
            default_node = defaults[default_index - default_start]
            text += f" = {ast.unparse(default_node)}"
        return text

    combined = posonly + positional
    if drop_self and combined and combined[0].arg in {"self", "cls"}:
        combined = combined[1:]
        default_start = max(0, default_start - 1)

    for idx, arg in enumerate(combined):
        params.append(_param_text(arg, idx))

    if args.vararg is not None:
        vararg_text = f"*{args.vararg.arg}"
        if args.vararg.annotation is not None:
            vararg_text += f": {_annotation_to_str(args.vararg.annotation)}"
        params.append(vararg_text)

    for kwarg in args.kwonlyargs:
        kw_text = kwarg.arg
        if kwarg.annotation is not None:
            kw_text += f": {_annotation_to_str(kwarg.annotation)}"
        params.append(kw_text)

    if args.kwarg is not None:
        kwarg_text = f"**{args.kwarg.arg}"
        if args.kwarg.annotation is not None:
            kwarg_text += f": {_annotation_to_str(args.kwarg.annotation)}"
        params.append(kwarg_text)

    return ", ".join(params)


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_self: bool = False) -> str:
    params = _format_params(node, drop_self=drop_self)
    ret = _annotation_to_str(node.returns) if node.returns is not None else "Any"
    return f"{node.name}({params}) -> {ret}"


def _extract_module_doc(module_path: Path, repo_root: Path) -> ModuleDoc:
    content = module_path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    functions: list[FunctionDoc] = []
    classes: list[ClassDoc] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions.append(
                FunctionDoc(
                    name=node.name,
                    signature=_format_signature(node),
                    summary=_first_line(ast.get_docstring(node)),
                )
            )
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods: list[FunctionDoc] = []
            for class_node in node.body:
                if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not class_node.name.startswith("_"):
                    methods.append(
                        FunctionDoc(
                            name=class_node.name,
                            signature=_format_signature(class_node, drop_self=True),
                            summary=_first_line(ast.get_docstring(class_node)),
                        )
                    )
            classes.append(
                ClassDoc(
                    name=node.name,
                    summary=_first_line(ast.get_docstring(node)),
                    methods=methods,
                )
            )

    return ModuleDoc(
        path=str(module_path.relative_to(repo_root)),
        summary=_first_line(ast.get_docstring(tree)),
        functions=functions,
        classes=classes,
    )


def build_reference_markdown(modules: Iterable[ModuleDoc]) -> str:
    lines = [
        "# Optimizers API Reference (Auto-generated)",
        "",
        "This file is generated from type hints and docstrings.",
        "Do not edit manually; update source code/docstrings and regenerate.",
        "",
    ]

    for module in modules:
        lines.append(f"## {module.path}")
        if module.summary:
            lines.append("")
            lines.append(module.summary)
        lines.append("")

        if module.functions:
            lines.append("### Functions")
            lines.append("")
            for fn in module.functions:
                lines.append(f"- `{fn.signature}`")
                if fn.summary:
                    lines.append(f"  - {fn.summary}")
            lines.append("")

        if module.classes:
            lines.append("### Classes")
            lines.append("")
            for cls in module.classes:
                lines.append(f"#### `{cls.name}`")
                if cls.summary:
                    lines.append("")
                    lines.append(cls.summary)
                lines.append("")
                if cls.methods:
                    lines.append("Methods:")
                    for method in cls.methods:
                        lines.append(f"- `{method.signature}`")
                        if method.summary:
                            lines.append(f"  - {method.summary}")
                    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_api_reference(module_paths: Iterable[Path], output_path: Path, repo_root: Path) -> str:
    docs = [_extract_module_doc(path, repo_root) for path in module_paths]
    markdown = build_reference_markdown(docs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate optimizer API reference docs")
    parser.add_argument(
        "--modules",
        nargs="*",
        default=DEFAULT_MODULES,
        help="Module file paths (relative to repo root)",
    )
    parser.add_argument(
        "--output",
        default="docs/api/OPTIMIZERS_API_REFERENCE.md",
        help="Output markdown path (relative to repo root)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    module_paths = [repo_root / module for module in args.modules]
    output_path = repo_root / args.output

    generate_api_reference(module_paths, output_path, repo_root)
    print(f"Generated {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
