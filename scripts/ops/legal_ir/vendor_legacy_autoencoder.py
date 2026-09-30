#!/usr/bin/env python3
"""Reproduce the isolated legacy runtime from its immutable Git revision.

This reads local Git objects only. It never fetches Git, downloads weights, or
imports either autoencoder implementation. Source bytes are preserved except
for recorded namespace and source-root/cache relocation edits. Use --verify
against the checked-in snapshot to detect any drift.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any


SOURCE_REVISION = "ddf6b79467b68159650df81befc288c8553df664"
SOURCE_PACKAGE = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
TARGET_PACKAGE = SOURCE_PACKAGE + ".autoencoder_lineages.legacy_v1._snapshot"
SCHEMA = "legacy-autoencoder-vendored-runtime/v1"
EXPECTED_MODULE_COUNT = 23
SNAPSHOT_INIT = '''"""Frozen legacy numerical/runtime dependency closure.

Generated from ddf6b79467b68159650df81befc288c8553df664. See MANIFEST.json
for original Git blobs, byte hashes, exact relocation edits, and shared
canonical logic boundaries. The public lineage facade lives one level above.
This namespace deliberately performs no eager imports or module aliasing.
"""
'''


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_path(module: str) -> str:
    return SOURCE_PACKAGE.replace(".", "/") + "/" + module.replace(".", "/") + ".py"


def _resolved_import(node: ast.ImportFrom) -> str:
    if not node.module:
        raise ValueError("Unqualified relative imports require an explicit relocation audit")
    if node.level:
        return importlib.util.resolve_name("." * node.level + node.module, SOURCE_PACKAGE)
    return node.module


def _audit_imports(source: str, module: str) -> tuple[list[str], list[dict[str, Any]]]:
    dependencies: set[str] = set()
    shared: list[dict[str, Any]] = []
    for node in ast.walk(ast.parse(source, filename=module)):
        if isinstance(node, ast.ImportFrom):
            resolved = _resolved_import(node)
            if resolved.startswith(SOURCE_PACKAGE + "."):
                dependencies.add(resolved.removeprefix(SOURCE_PACKAGE + "."))
            elif resolved.startswith("ipfs_datasets_py."):
                shared.append({"line": node.lineno, "module": resolved,
                               "names": [alias.name for alias in node.names]})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(SOURCE_PACKAGE):
                    raise ValueError(f"Unreviewed absolute optimizer import in {module}:{node.lineno}")
                if alias.name.startswith("ipfs_datasets_py."):
                    shared.append({"line": node.lineno, "module": alias.name, "names": []})
        elif isinstance(node, ast.Call):
            function = node.func
            if ((isinstance(function, ast.Name) and function.id == "__import__") or
                    (isinstance(function, ast.Attribute) and function.attr == "import_module")):
                raise ValueError(f"Dynamic import needs explicit audit in {module}:{node.lineno}")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "sys" and node.attr == "modules":
                raise ValueError(f"Module aliasing forbidden in {module}:{node.lineno}")
    return sorted(dependencies), sorted(shared, key=lambda item: item["line"])


def _rewrite(source: str, module: str) -> tuple[str, list[dict[str, str]]]:
    rewrites: list[dict[str, str]] = []

    def replace_once(before: str, after: str, reason: str) -> None:
        nonlocal source
        if source.count(before) != 1:
            raise ValueError(f"Expected exactly one relocation anchor in {module}: {before!r}")
        source = source.replace(before, after, 1)
        rewrites.append({"before": before, "after": after, "reason": reason})

    # Flat intra-closure relative imports already select the frozen sibling.
    # Escaping relatives must resolve relative to the original package depth.
    import_rewrites: dict[str, tuple[str, str]] = {}
    for node in ast.walk(ast.parse(source, filename=module)):
        if not isinstance(node, ast.ImportFrom):
            continue
        resolved = _resolved_import(node)
        original = "." * node.level + (node.module or "")
        if not node.level and resolved.startswith(SOURCE_PACKAGE + "."):
            replacement = TARGET_PACKAGE + resolved[len(SOURCE_PACKAGE):]
            import_rewrites[original] = (replacement, "isolate absolute optimizer dependency")
        elif node.level > 1:
            if resolved.startswith(SOURCE_PACKAGE + "."):
                replacement = TARGET_PACKAGE + resolved[len(SOURCE_PACKAGE):]
            else:
                replacement = resolved
            import_rewrites[original] = (replacement, "retain original canonical external import boundary")
    for original, (replacement, reason) in sorted(import_rewrites.items()):
        replace_once(f"from {original} import", f"from {replacement} import", reason)

    if module == "modal_autoencoder":
        replace_once("repo_root = Path(__file__).resolve().parents[3]",
                     "repo_root = Path(__file__).resolve().parents[6]",
                     "preserve repository root after three namespace levels")
        replace_once("package_root = Path(__file__).resolve().parents[2]",
                     "package_root = Path(__file__).resolve().parents[5]",
                     "fingerprint the real canonical package and its shared bridges")
        replace_once('return repo_root / "workspace" / "test-logs" / "legal-ir-metric-cache"',
                     'return repo_root / "workspace" / "test-logs" / "legal-ir-metric-cache" / "legacy-v1"',
                     "separate the default legacy disk target cache")

    # A newly discovered file-relative resource would need its own adaptation.
    if module != "modal_autoencoder" and "__file__" in source:
        raise ValueError(f"Unaudited file-relative resource in {module}")
    compile(source, _source_path(module), "exec")
    return source, rewrites


def build_snapshot(repo: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    revision = _git(repo, "rev-parse", SOURCE_REVISION + "^{commit}").decode().strip()
    if revision != SOURCE_REVISION:
        raise ValueError("Source revision did not resolve to the pinned commit")
    sources: dict[str, bytes] = {}
    metadata: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    pending = ["modal_autoencoder"]
    while pending:
        module = pending.pop()
        if module in sources:
            continue
        raw = _git(repo, "show", f"{SOURCE_REVISION}:{_source_path(module)}")
        dependencies, shared = _audit_imports(raw.decode("utf-8"), module)
        sources[module] = raw
        metadata[module] = dependencies, shared
        pending.extend(dependencies)
    if len(sources) != EXPECTED_MODULE_COUNT:
        raise ValueError(f"Unexpected closure size: {len(sources)}")

    files: dict[str, bytes] = {"__init__.py": SNAPSHOT_INIT.encode("utf-8")}
    records = []
    for module, raw in sorted(sources.items()):
        text, rewrites = _rewrite(raw.decode("utf-8"), module)
        data = text.encode("utf-8")
        filename = module.replace(".", "/") + ".py"
        files[filename] = data
        dependencies, shared = metadata[module]
        records.append({
            "module": module, "source_path": _source_path(module), "vendored_path": filename,
            "source_git_blob": _git(repo, "rev-parse", f"{SOURCE_REVISION}:{_source_path(module)}").decode().strip(),
            "source_sha256": _sha256(raw), "source_bytes": len(raw),
            "vendored_sha256": _sha256(data), "vendored_bytes": len(data),
            "frozen_dependencies": dependencies, "shared_canonical_imports": shared,
            "relocation_edits": rewrites,
        })
    manifest = {
        "schema_version": SCHEMA, "source_revision": SOURCE_REVISION,
        "source_package": SOURCE_PACKAGE, "runtime_package": TARGET_PACKAGE,
        "module_count": len(records), "source_bytes": sum(len(raw) for raw in sources.values()),
        "vendored_module_bytes": sum(record["vendored_bytes"] for record in records),
        "snapshot_init_sha256": _sha256(files["__init__.py"]),
        "isolation": {
            "numerics_state_checkpoint_helpers": "frozen transitive optimizer closure",
            "internal_modal_parser_registry_ir": "frozen in this namespace",
            "typed_deontic_compiler_decompiler_parser": "shared canonical workspace logic tree",
            "external_bridges_provers_proof_feedback_checkpoint_contracts": "shared canonical workspace logic tree",
            "module_aliases": False, "new_lineage_fallback": False,
            "legacy_checkpoint_requires_explicit_verified_local_path": True,
            "independent_learned_formula_decoder": False,
            "admission": "lake build <Lib> only; model metrics and bridge syntax are not admission",
        },
        "files": records,
    }
    files["MANIFEST.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return files, manifest


def materialize(files: dict[str, bytes], destination: Path, *, verify: bool) -> None:
    expected = set(files)
    existing = ({str(path.relative_to(destination)) for path in destination.rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts}
                if destination.exists() else set())
    unexpected = existing - expected
    if unexpected:
        raise ValueError(f"Unexpected snapshot files; refusing overwrite: {sorted(unexpected)}")
    for name, raw in sorted(files.items()):
        path = destination / name
        if verify:
            if not path.is_file() or path.read_bytes() != raw:
                raise ValueError(f"Vendored snapshot drift: {name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Exact _snapshot directory; use a staging directory during a running campaign")
    parser.add_argument("--verify", action="store_true", help="Compare every byte; do not write files")
    args = parser.parse_args()
    files, manifest = build_snapshot(args.repo)
    materialize(files, args.output_dir, verify=args.verify)
    print(json.dumps({"verified": args.verify, "output_dir": str(args.output_dir),
                      "module_count": manifest["module_count"], "source_bytes": manifest["source_bytes"],
                      "manifest_sha256": _sha256(files["MANIFEST.json"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
