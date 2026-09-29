"""Prepare a scoped source audit/tree, never a commit or push.

Run from the canonical external/ipfs_datasets repository after the root agent
finalizes publication-files.json and freezes native evidence:

    python workspace/test-logs/federal-corpus-audits/autoencoder-search-20260929/prepare_publication.py --audit-only

Copy/review workspace source-scope.json into the evidence directory, finalize its
artifact manifest, and then invoke without --audit-only. Both modes leave the
live checkout, HEAD and index unchanged. --fetch refreshes origin/main explicitly.
The modal autoencoder is prepared from origin/main plus only this task's bound
delta. Its preexisting worker-budget edit is excluded. Full native before/after
source maps and explicitly allowed changes are audited separately. The final
serial/parallel comparison must use identical sources. Earlier baseline changes
are historical accounting only and cannot establish a matched speed claim.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent
PACKAGE = "ipfs_datasets_py/"
MODAL = PACKAGE + "optimizers/logic_theorem_optimizer/modal_autoencoder.py"
EVIDENCE = "docs/implementation/reports/evidence/autoencoder-search-20260929"
SOURCE_AUDIT = EVIDENCE + "/source-scope.json"
CORE_PATHS = {
    "compiler": PACKAGE + "logic/legal_ir/canonical_compiler.py",
    "decompiler": PACKAGE + "logic/legal_ir/canonical_decompiler.py",
    "parser": PACKAGE + "logic/deontic/utils/deontic_parser.py",
    "autoencoder": MODAL,
    "samples": PACKAGE + "optimizers/logic_theorem_optimizer/legal_samples.py",
    "worker": PACKAGE + "optimizers/logic_theorem_optimizer/autoencoder_training_worker.py",
}
CLEAN_ENV = {key: value for key, value in os.environ.items() if key not in {
    "GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"}}


def git(*args, data=None, extra=None, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd,
        env={**CLEAN_ENV, **(extra or {})}, input=data)


def git_text(*args, **kwargs):
    return git(*args, **kwargs).decode().strip()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    return sha(path.read_bytes()) if path.is_file() else None


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def safe_file(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name:
        raise ValueError("publication path must be canonical and repository-relative")
    target = ROOT / path
    if any(item.is_symlink() for item in (target, *target.parents)):
        raise ValueError("publication paths must not contain symlinks")
    return target


def blob_bytes(ref, name):
    process = subprocess.run(["git", "show", ref + ":" + name], cwd=ROOT,
        env=CLEAN_ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        # Missing path is legitimate for newly introduced source files.
        if b"does not exist in" in process.stderr or b"exists on disk, but not in" in process.stderr:
            return None
        raise RuntimeError("cannot read source blob " + name)
    return process.stdout


def package_hashes_from_git(ref):
    entries = []
    for row in git("ls-tree", "-r", "-z", ref, "--", PACKAGE).split(b"\0"):
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = path.decode()
        if kind == "blob" and name.endswith(".py"):
            if mode == "120000":
                raise ValueError("published producer Python source is a symlink")
            entries.append((name.removeprefix(PACKAGE), oid))
    result = {}
    process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT,
        env=CLEAN_ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for name, oid in entries:
            process.stdin.write((oid + "\n").encode()); process.stdin.flush()
            header = process.stdout.readline().decode().strip().split()
            if len(header) != 3 or header[:2] != [oid, "blob"]:
                raise ValueError("git batch returned another source object")
            remaining = int(header[2])
            if not 0 <= remaining <= 64 * 1024 * 1024:
                raise ValueError("Python source blob exceeds audit bound")
            digest = hashlib.sha256()
            while remaining:
                chunk = process.stdout.read(min(remaining, 65536))
                if not chunk:
                    raise ValueError("truncated source blob")
                digest.update(chunk); remaining -= len(chunk)
            if process.stdout.read(1) != b"\n":
                raise ValueError("invalid git batch source separator")
            result[name] = digest.hexdigest()
        process.stdin.close()
        if process.wait(timeout=30):
            raise ValueError("git batch failed")
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
    return result


def package_hashes_from_workspace():
    package_root = ROOT / PACKAGE
    entries = {}
    for path in sorted(package_root.rglob("*.py")):
        if path.is_symlink() or package_root.resolve() not in path.resolve().parents:
            raise ValueError("native package source aliases another tree")
        if path.is_file():
            entries[path.relative_to(package_root).as_posix()] = file_sha(path)
    return entries


def manifest(entries):
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": sha(raw), "file_count": len(entries)}


def scoped_modal_update(parent, current, temporary):
    change_manifest = json.loads((BASE / "optimizer-change-manifest.json").read_bytes())
    rows = [row for row in change_manifest["files"] if row["path"] == MODAL]
    if len(rows) != 1:
        raise ValueError("scoped modal change manifest is ambiguous")
    baseline = (BASE / "before" / MODAL).read_bytes()
    if sha(baseline) != rows[0]["before_sha256"] or sha(current) != rows[0]["after_sha256"]:
        raise ValueError("modal bytes differ from reviewed before/after delta")
    upstream = blob_bytes(parent, MODAL)
    if upstream is None:
        raise ValueError("origin/main lacks modal source")
    patch = "".join(difflib.unified_diff(baseline.decode().splitlines(keepends=True),
        current.decode().splitlines(keepends=True), fromfile="a/" + MODAL, tofile="b/" + MODAL))
    if not patch:
        raise ValueError("scoped optimizer delta is empty")
    patch_path = BASE / "scoped-modal-training-screen.patch"
    patch_path.write_text(patch)
    target = temporary / MODAL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(upstream)
    # No fallback to the full dirty workspace. Context conflict needs review.
    git("apply", "--check", "--whitespace=error", str(patch_path), cwd=temporary)
    git("apply", "--whitespace=error", str(patch_path), cwd=temporary)
    prepared = target.read_bytes()
    return prepared, {"publication_includes_modal_autoencoder": True,
        "workspace_before_sha256": sha(baseline), "workspace_current_sha256": sha(current),
        "origin_main_sha256": sha(upstream), "prepared_sha256": sha(prepared),
        "scoped_patch_sha256": sha(patch.encode()),
        "change_manifest_sha256": file_sha(BASE / "optimizer-change-manifest.json"),
        "preexisting_workspace_delta_excluded": baseline != upstream,
        "live_workspace_modified": False}


def native_change_audit(binding, captured, baseline_binding_path, baseline_map_path, allowed_path, historical_binding_path, historical_map_path):
    baseline_binding = json.loads(baseline_binding_path.read_bytes())
    baseline = json.loads(baseline_map_path.read_bytes())
    if manifest(baseline) != baseline_binding["producer_manifest"]:
        raise ValueError("baseline source map differs from its native binding")
    allowed = json.loads(allowed_path.read_bytes())
    if type(allowed) is not list or any(type(name) is not str for name in allowed) or len(set(allowed)) != len(allowed):
        raise ValueError("allowed native changes must be a unique explicit path list")
    for name in allowed:
        safe_file(name)
        if not name.startswith((PACKAGE, "scripts/")) or not name.endswith(".py"):
            raise ValueError("native change allowance must name package or orchestration Python source")
    differences = [{"package_path": PACKAGE + name,
        "baseline_sha256": baseline.get(name), "updated_sha256": captured.get(name),
        "explicitly_allowed": PACKAGE + name in allowed}
        for name in sorted(set(baseline) | set(captured)) if baseline.get(name) != captured.get(name)]
    def dependencies(value):
        result = {CORE_PATHS[key]: digest for key, digest in value["core_sources"].items()}
        result.update(value["orchestration"])
        return result
    old_dependencies, new_dependencies = dependencies(baseline_binding), dependencies(binding)
    dependency_changes = [{"path": name, "baseline_sha256": old_dependencies.get(name),
        "updated_sha256": new_dependencies.get(name), "explicitly_allowed": name in allowed}
        for name in sorted(set(old_dependencies) | set(new_dependencies))
        if old_dependencies.get(name) != new_dependencies.get(name)]
    if differences or dependency_changes:
        raise ValueError("final serial/parallel native comparison must use identical package and bound sources")
    historical_binding = json.loads(historical_binding_path.read_bytes())
    historical = json.loads(historical_map_path.read_bytes())
    if manifest(historical) != historical_binding["producer_manifest"]:
        raise ValueError("historical baseline mapping differs from its original binding")
    historical_dependencies = dependencies(historical_binding)
    historical_differences = [{"package_path": PACKAGE + name,
        "historical_sha256": historical.get(name), "final_native_sha256": captured.get(name),
        "owned_change": PACKAGE + name in allowed}
        for name in sorted(set(historical) | set(captured)) if historical.get(name) != captured.get(name)]
    historical_dependency_changes = [{"path": name,
        "historical_sha256": historical_dependencies.get(name), "final_native_sha256": new_dependencies.get(name),
        "owned_change": name in allowed}
        for name in sorted(set(historical_dependencies) | set(new_dependencies))
        if historical_dependencies.get(name) != new_dependencies.get(name)]
    return {"baseline_binding": {"path": str(baseline_binding_path), "sha256": file_sha(baseline_binding_path)},
        "baseline_map": {"path": str(baseline_map_path), "sha256": file_sha(baseline_map_path)},
        "baseline_producer_manifest": baseline_binding["producer_manifest"],
        "updated_producer_manifest": binding["producer_manifest"],
        "allowed_change_manifest": {"path": str(allowed_path), "sha256": file_sha(allowed_path), "paths": allowed},
        "package_differences": differences, "bound_dependency_changes": dependency_changes,
        "same_source_physical_dispatch_comparison": True,
        "historical_source_accounting": {
            "binding": {"path": str(historical_binding_path), "sha256": file_sha(historical_binding_path)},
            "source_map": {"path": str(historical_map_path), "sha256": file_sha(historical_map_path)},
            "producer_manifest": historical_binding["producer_manifest"],
            "package_differences": historical_differences,
            "bound_dependency_changes": historical_dependency_changes,
            "matched_parity_or_causal_speed_claim": False,
            "scope": "Earlier baseline predates optimizer and parallel qualification changes plus concurrent unrelated producer edits. Original failed source checks remain failed; this accounting neither certifies their final source nor qualifies the excluded changes."},
        "scope": "Final same-source binding check only; successful native audits and exact-result parity are separate requirements for a matched timing comparison."}


def build_scope_audit(parent, staged, binding, modal_scope, binding_path, captured_map, native_changes):
    current_sources = package_hashes_from_workspace()
    observed = manifest(current_sources)
    workspace = json.loads(captured_map.read_bytes()) if captured_map else current_sources
    if manifest(workspace) != binding["producer_manifest"]:
        raise ValueError("captured source mapping differs from native binding")
    # This is a publication scope audit, not a native qualification override.
    # Preserve later unrelated edits explicitly. Every published package byte
    # must still be the byte captured by the original native run.
    for name, raw in staged.items():
        if name.startswith(PACKAGE) and name.endswith(".py"):
            expected = workspace.get(name.removeprefix(PACKAGE))
            if name == MODAL:
                if expected != modal_scope["workspace_current_sha256"] or sha(raw) != modal_scope["prepared_sha256"]:
                    raise ValueError("scoped optimizer transformation differs from native source binding")
            elif sha(raw) != expected:
                raise ValueError("staged producer differs from captured native source: " + name)
    upstream = package_hashes_from_git(parent)
    prepared = dict(upstream)
    for name, raw in staged.items():
        if name.startswith(PACKAGE) and name.endswith(".py"):
            prepared[name.removeprefix(PACKAGE)] = sha(raw)
    gitlinks = []
    for item in git("ls-tree", "-r", "-z", parent, "--", PACKAGE).split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        if mode == "160000" and kind == "commit":
            gitlinks.append({"path": name.decode(), "commit": oid,
                             "contents_expanded_in_prepared_manifest": False})
    def comparison_kind(name):
        if any((PACKAGE + name).startswith(row["path"] + "/") for row in gitlinks):
            return "gitlinked_contents_not_expanded"
        return "superproject_content_difference" if name in upstream else "workspace_only_python_source"
    differences = [{"package_path": PACKAGE + name,
        "comparison_kind": comparison_kind(name),
        "captured_native_sha256": workspace.get(name),
        "origin_main_sha256": upstream.get(name),
        "prepared_sha256": prepared.get(name),
        "prepared_matches_native": prepared.get(name) == workspace.get(name)}
        for name in sorted(set(workspace) | set(prepared)) if workspace.get(name) != prepared.get(name)]
    rows = []
    paths = [("core", CORE_PATHS[key], value) for key, value in binding["core_sources"].items()]
    paths += [("orchestration", key, value) for key, value in binding["orchestration"].items()]
    for kind, name, expected in paths:
        path = Path(name) if Path(name).is_absolute() else ROOT / name
        current = file_sha(path)
        if current != expected:
            raise ValueError("native dependency changed: " + name)
        external = not path.is_relative_to(ROOT)
        planned = None if external else staged.get(name, blob_bytes(parent, name))
        rows.append({"section": kind, "path": name, "captured_native_sha256": expected,
            "workspace_sha256": current, "workspace_matches_native": current == expected,
            "external_to_this_publication": external,
            "prepared_sha256": sha(planned) if planned is not None else None,
            "prepared_matches_native": None if external else planned is not None and sha(planned) == expected})
    return {"schema": "scoped-native-publication-source-audit/v1", "origin_main_base": parent,
        "native_binding_file": binding_path.name,
        "native_binding_sha256": file_sha(binding_path),
        "captured_native_package_manifest": binding["producer_manifest"],
        "current_workspace_package_manifest": observed,
        "prepared_package_manifest": manifest(prepared),
        "native_package_matches_workspace": observed == binding["producer_manifest"],
        "captured_source_map": {"path": str(captured_map), "sha256": file_sha(captured_map)} if captured_map else None,
        "current_workspace_differences_from_native": [{"package_path": PACKAGE + name,
            "captured_native_sha256": workspace.get(name), "current_workspace_sha256": current_sources.get(name)}
            for name in sorted(set(workspace) | set(current_sources)) if workspace.get(name) != current_sources.get(name)],
        "staged_package_sources_match_native_except_scoped_autoencoder": True,
        "native_before_after_source_changes": native_changes,
        "prepared_package_matches_native": None if gitlinks else manifest(prepared) == binding["producer_manifest"],
        "prepared_package_manifest_scope": "superproject Python blobs plus explicit scoped changes; Git-linked contents are not expanded and must not be inferred to be deleted",
        "gitlinked_source_repositories": gitlinks,
        "package_differences": differences, "dependency_rows": rows,
        "scoped_autoencoder_source_change": modal_scope,
        "scope_limit": "Native evidence belongs to the captured workspace producer. Scoped publication excludes concurrent edits; differences are explicit and are not retroactively qualified. A post-run native audit failure remains a failure; this publication mapping cannot waive it.",
        "admitted": False, "formalized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, default=BASE / "publication-files.json")
    parser.add_argument("--binding", type=Path, default=BASE / "parallel-binding.json")
    parser.add_argument("--captured-producer-map", type=Path, default=BASE / "package-optimized.json")
    parser.add_argument("--baseline-binding", type=Path, default=BASE / "serial-binding.json")
    parser.add_argument("--baseline-producer-map", type=Path, default=BASE / "package-optimized.json")
    parser.add_argument("--allowed-native-changes", type=Path, default=BASE / "publication-owned-sources.json")
    parser.add_argument("--historical-binding", type=Path, default=BASE / "baseline-binding.json")
    parser.add_argument("--historical-producer-map", type=Path, default=BASE / "package-baseline.json")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if Path(git_text("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise ValueError("publication helper is outside the intended repository")
    names = json.loads(args.files.read_bytes())
    if type(names) is not list or not names or any(type(x) is not str for x in names) or len(names) != len(set(names)):
        raise ValueError("root must finalize a unique explicit publication file list")
    if SOURCE_AUDIT not in names or MODAL not in names:
        raise ValueError("scope must include reviewed source audit and scoped optimizer source")
    head = git_text("rev-parse", "HEAD")
    index = Path(git_text("rev-parse", "--git-path", "index"))
    if not index.is_absolute(): index = ROOT / index
    index_sha = file_sha(index)
    if args.fetch: git("fetch", "origin", "main")
    parent = git_text("rev-parse", "origin/main")
    binding = json.loads(args.binding.read_bytes())
    snapshots, staged, modes = {}, {}, {}
    for name in names:
        path = safe_file(name)
        if name == SOURCE_AUDIT:
            continue
        if not path.is_file():
            if args.audit_only and name.startswith("docs/"):
                continue  # Reports/evidence may not be curated until audit review.
            raise ValueError("missing finalized publication file: " + name)
        raw = path.read_bytes()
        snapshots[name] = sha(raw); staged[name] = raw
        modes[name] = "100755" if path.stat().st_mode & 0o111 else "100644"
    with tempfile.TemporaryDirectory(prefix="autoencoder-scoped-publication-") as directory:
        temporary = Path(directory)
        staged[MODAL], modal_scope = scoped_modal_update(parent, staged[MODAL], temporary)
        captured = json.loads(args.captured_producer_map.read_bytes())
        native_changes = native_change_audit(binding, captured, args.baseline_binding,
            args.baseline_producer_map, args.allowed_native_changes,
            args.historical_binding, args.historical_producer_map)
        audit = build_scope_audit(parent, staged, binding, modal_scope, args.binding,
            args.captured_producer_map, native_changes)
        write(BASE / "source-scope.json", audit)
        report = {"repository": str(ROOT), "origin_main_base": parent, "live_head": head,
            "live_index_sha256": index_sha, "workspace_file_sha256": snapshots,
            "prepared_file_sha256": {name: sha(raw) for name, raw in staged.items()},
            "source_audit_sha256": file_sha(BASE / "source-scope.json"), "modal_scope": modal_scope,
            "audit_only": args.audit_only, "commit_created": False, "pushed": False}
        if not args.audit_only:
            reviewed = safe_file(SOURCE_AUDIT)
            if not reviewed.is_file() or json.loads(reviewed.read_bytes()) != audit:
                raise ValueError("reviewed evidence source-scope.json differs; copy audit and refresh evidence manifest first")
            staged[SOURCE_AUDIT] = reviewed.read_bytes()
            snapshots[SOURCE_AUDIT] = sha(staged[SOURCE_AUDIT]); modes[SOURCE_AUDIT] = "100644"
            private = {"GIT_INDEX_FILE": str(temporary / "private-index")}
            git("read-tree", parent, extra=private)
            for name, raw in staged.items():
                blob = git_text("hash-object", "-w", "--stdin", data=raw)
                git("update-index", "--add", "--cacheinfo", f"{modes[name]},{blob},{name}", extra=private)
            tree = git_text("write-tree", extra=private)
            # Preserve immutable pytest output and unified-patch context bytes.
            # All product source, tests and prose remain whitespace checked.
            git("diff", "--check", parent, tree, "--", ".",
                ":(exclude)" + EVIDENCE + "/optimizer-staged-delta.patch",
                ":(exclude)" + EVIDENCE + "/scoped-modal-training-screen.patch")
            changed = git_text("diff", "--name-only", parent, tree).splitlines()
            if not set(changed) <= set(names):
                raise ValueError("prepared tree escaped explicit publication scope")
            report.update(tree=tree, changed_files=changed,
                prepared_file_sha256={name: sha(raw) for name, raw in staged.items()})
            (BASE / "prepared-publication.stat").write_bytes(git("diff", "--stat", parent, tree))
        if git_text("rev-parse", "HEAD") != head or file_sha(index) != index_sha:
            raise ValueError("live HEAD or index changed during preparation")
        if git_text("rev-parse", "origin/main") != parent:
            raise ValueError("origin/main moved during preparation")
        if any(file_sha(ROOT / name) != value for name, value in snapshots.items()):
            raise ValueError("publication workspace file changed during preparation")
        report["live_checkout_preserved"] = True
        write(BASE / ("publication-audit.json" if args.audit_only else "prepared-publication.json"), report)
        print(json.dumps({key: value for key, value in report.items() if key in
            {"origin_main_base", "tree", "live_head", "audit_only", "commit_created", "pushed", "live_checkout_preserved"}}, sort_keys=True))


if __name__ == "__main__":
    main()
