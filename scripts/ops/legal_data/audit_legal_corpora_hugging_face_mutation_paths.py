#!/usr/bin/env python3
"""Inventory reachable Hugging Face mutation paths (LCR-084).

Walks the repository AST for HfApi write methods and protected-repo literals.
A callsite is safe only when the module also imports the canonical publication
runtime. ``--check`` fails closed when any unprotected protected-repo write
path remains. This CLI never mutates Hub.

Validation::

    python scripts/ops/legal_data/audit_legal_corpora_hugging_face_mutation_paths.py \\
        --protected-repo justicedao/ipfs_state_laws \\
        --protected-repo justicedao/ipfs_federal_register \\
        --require-runtime ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime \\
        --check
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.protected_repo_guard import (  # noqa: E402
    CANONICAL_RUNTIME,
    PROTECTED_REPOS,
    PROTECTED_WRITE_METHODS,
)

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_legal_corpora_hugging_face_mutation_paths.py"
SCHEMA = "ipfs_datasets_py/legal-corpora-hugging-face-mutation-path-audit@1"
REPORT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/hugging_face_mutation_path_audit.json"
)
SCAN_ROOTS = (
    Path("ipfs_datasets_py/huggingface"),
    Path("ipfs_datasets_py/processors/legal_data"),
    Path("ipfs_datasets_py/processors/legal_scrapers"),
    Path("ipfs_datasets_py/processors/domains/patent"),
    Path("scripts/ops/legal_data"),
    Path("scripts/repair"),
    Path("scripts/ops/security_ir"),
)
SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    "workspace",
    "external",
}


class MutationPathAuditError(RuntimeError):
    pass


def _iter_python_files(root: Path, *, repository_root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*.py"):
        try:
            rel_parts = path.relative_to(repository_root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        files.append(path)
    return sorted(files)


def _module_imports_runtime(tree: ast.AST, runtime: str) -> bool:
    needle = runtime.split(".")[-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == runtime or node.module.endswith(
                ".legal_corpora_publication_runtime"
            ):
                return True
            if any(alias.name == needle for alias in node.names):
                if "publication_runtime" in (node.module or ""):
                    return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == runtime:
                    return True
    return False


def _string_constants(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    return found


def inventory_mutation_paths(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
) -> dict[str, Any]:
    protected = {str(item) for item in protected_repos}
    callsites: list[dict[str, Any]] = []
    unprotected: list[dict[str, Any]] = []
    for scan_root in SCAN_ROOTS:
        for path in _iter_python_files(
            repository_root / scan_root, repository_root=repository_root
        ):
            rel = path.relative_to(repository_root).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            imports_runtime = _module_imports_runtime(tree, required_runtime)
            constants = _string_constants(tree)
            mentions_protected = sorted(constants & protected)
            write_hits: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in PROTECTED_WRITE_METHODS:
                    write_hits.append(node.attr)
                if isinstance(node, ast.Name) and node.id in {"HfApi"}:
                    write_hits.append("HfApi")
            write_hits = sorted(set(write_hits))
            if not write_hits and not mentions_protected:
                continue
            record = {
                "path": rel,
                "write_methods": write_hits,
                "protected_repo_literals": mentions_protected,
                "imports_canonical_runtime": imports_runtime,
            }
            callsites.append(record)
            if mentions_protected and write_hits and not imports_runtime:
                unprotected.append(record)
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "required_runtime": required_runtime,
        "protected_repos": sorted(protected),
        "callsite_count": len(callsites),
        "unprotected_count": len(unprotected),
        "callsites": callsites,
        "unprotected_callsites": unprotected,
        "authorizing_hub_upload": False,
        "status": "passed" if not unprotected else "blocked",
        "reasons": (
            []
            if not unprotected
            else [
                f"{item['path']} mutates {item['protected_repo_literals']} via "
                f"{item['write_methods']} without importing {required_runtime}"
                for item in unprotected
            ]
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory Hugging Face mutation paths for protected LCR repos"
    )
    parser.add_argument(
        "--protected-repo",
        action="append",
        dest="protected_repos",
        default=[],
    )
    parser.add_argument(
        "--require-runtime",
        default=CANONICAL_RUNTIME,
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the audit receipt (never a Hub mutation).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "audit_legal_corpora_hugging_face_mutation_paths: FAILED: --check is required\n"
        )
        return 2
    repos = tuple(args.protected_repos) or tuple(sorted(PROTECTED_REPOS))
    report = inventory_mutation_paths(
        protected_repos=repos,
        required_runtime=str(args.require_runtime),
    )
    if args.write:
        target = REPOSITORY_ROOT / REPORT_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "audit_legal_corpora_hugging_face_mutation_paths: "
            f"{report['status'].upper()} unprotected={report['unprotected_count']} "
            f"callsites={report['callsite_count']}\n"
        )
        for reason in report["reasons"][:12]:
            sys.stderr.write(f"  {reason}\n")
    if report["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
