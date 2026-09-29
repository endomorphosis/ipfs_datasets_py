"""Prepare a scoped source audit/tree, never a commit or push.

Run from the canonical external/ipfs_datasets repository after the root agent
finalizes publication-files.json and freezes native evidence:

    python workspace/test-logs/federal-corpus-audits/autoencoder-convergence-20260929/prepare_publication.py --audit-only

Copy/review workspace source-scope.json into the evidence directory, finalize its
artifact manifest, and then invoke without --audit-only. Both modes leave the
live checkout, HEAD and index unchanged. --fetch refreshes origin/main explicitly.
Each existing owned file is prepared from origin/main plus only its bound
before-to-after task delta. Unrelated preexisting modal and worker changes stay
excluded. The fixed/adaptive/momentum native arms must bind identical producer
contents and source dependencies; different optimizer settings are intentional.
This helper does not turn workspace-native evidence into prepared-main proof.
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
EVIDENCE = "docs/implementation/reports/evidence/autoencoder-convergence-20260929"
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


def scoped_source_update(parent, name, current, temporary, change):
    if sha(current) != change["after_sha256"]:
        raise ValueError("owned bytes differ from reviewed final delta: " + name)
    upstream = blob_bytes(parent, name)
    baseline_path = BASE / "before" / name
    baseline = None if change["new_file"] else baseline_path.read_bytes()
    if baseline is not None and sha(baseline) != change["before_sha256"]:
        raise ValueError("owned before snapshot changed: " + name)
    patch_ref = None
    if change["new_file"]:
        if upstream is not None and upstream != current:
            raise ValueError("new owned file already exists differently on main: " + name)
        prepared = current
    else:
        if upstream is None:
            raise ValueError("origin/main lacks existing owned source: " + name)
        patch = "".join(difflib.unified_diff(baseline.decode().splitlines(keepends=True),
            current.decode().splitlines(keepends=True), fromfile="a/" + name, tofile="b/" + name))
        if not patch:
            raise ValueError("reviewed owned delta is empty: " + name)
        patch_path = BASE / "scoped-deltas" / (sha(name.encode()) + ".patch")
        patch_path.parent.mkdir(exist_ok=True)
        patch_path.write_text(patch)
        target = temporary / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(upstream)
        # Never substitute the full dirty workspace on a context conflict.
        git("apply", "--check", "--whitespace=error", str(patch_path), cwd=temporary)
        git("apply", "--whitespace=error", str(patch_path), cwd=temporary)
        prepared = target.read_bytes()
        patch_ref = {"path": str(patch_path), "sha256": sha(patch.encode())}
    return prepared, {"path": name, "new_file": change["new_file"],
        "workspace_before_sha256": sha(baseline) if baseline is not None else None,
        "workspace_current_sha256": sha(current), "origin_main_sha256": sha(upstream) if upstream is not None else None,
        "prepared_sha256": sha(prepared), "scoped_patch": patch_ref,
        "preexisting_workspace_delta_excluded": baseline is not None and baseline != upstream,
        "live_workspace_modified": False}


def native_change_audit(directory, binding, captured):
    arms = {}
    shared_fields = ("core_sources", "orchestration", "producer_manifest", "checkpoint",
                     "input_sha256", "validation_sha256", "canary_sha256")
    for name in ("fixed", "adaptive_lr", "adaptive_momentum"):
        binding_path = directory / name / "arm-binding.json"
        source_map_path = directory / ("package-" + name + ".json")
        arm = json.loads(binding_path.read_bytes())
        sources = json.loads(source_map_path.read_bytes())
        if manifest(sources) != arm["producer_manifest"] or sources != captured:
            raise ValueError("native arm source mapping differs: " + name)
        if any(arm.get(field) != binding.get(field) for field in shared_fields):
            raise ValueError("native arms differ in source, seed or sample binding: " + name)
        arms[name] = {"binding": {"path": str(binding_path), "sha256": file_sha(binding_path)},
            "source_map": {"path": str(source_map_path), "sha256": file_sha(source_map_path)},
            "producer_manifest": arm["producer_manifest"]}
    return {"arms": arms, "same_source_optimizer_ablation": True,
        "same_optimizer_configuration": False, "same_weight_result_claimed": False,
        "scope": "Producer/seed/sample binding comparison only. Successful native audits, finite metrics, qualified Lake/family evidence, tuning-only selection and untouched canary audit remain separate requirements."}


def build_scope_audit(parent, staged, binding, source_scopes, binding_path, captured_map, native_changes):
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
            if name in source_scopes:
                scope = source_scopes[name]
                if expected != scope["workspace_current_sha256"] or sha(raw) != scope["prepared_sha256"]:
                    raise ValueError("scoped source transformation differs from native source binding: " + name)
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
        "staged_package_sources_match_native_except_reviewed_scoped_deltas": True,
        "native_before_after_source_changes": native_changes,
        "prepared_package_matches_native": None if gitlinks else manifest(prepared) == binding["producer_manifest"],
        "prepared_package_manifest_scope": "superproject Python blobs plus explicit scoped changes; Git-linked contents are not expanded and must not be inferred to be deleted",
        "gitlinked_source_repositories": gitlinks,
        "package_differences": differences, "dependency_rows": rows,
        "scoped_autoencoder_source_change": source_scopes[MODAL],
        "scoped_source_changes": source_scopes,
        "scope_limit": "Native evidence belongs to the captured workspace producer. Scoped publication excludes concurrent edits; differences are explicit and are not retroactively qualified. A post-run native audit failure remains a failure; this publication mapping cannot waive it.",
        "admitted": False, "formalized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, default=BASE / "publication-files.json")
    parser.add_argument("--native-directory", type=Path, default=BASE / "native-three-arm-retry")
    parser.add_argument("--change-manifest", type=Path, default=BASE / "publication-change-manifest.json")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if Path(git_text("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise ValueError("publication helper is outside the intended repository")
    names = json.loads(args.files.read_bytes())
    if type(names) is not list or not names or any(type(x) is not str for x in names) or len(names) != len(set(names)):
        raise ValueError("root must finalize a unique explicit publication file list")
    changes = json.loads(args.change_manifest.read_bytes())
    if type(changes) is not dict or not set(changes) <= set(names):
        raise ValueError("publication scope must include every reviewed task delta")
    for name, change in changes.items():
        safe_file(name)
        if not name.endswith(".py") or type(change.get("new_file")) is not bool:
            raise ValueError("reviewed source change is malformed: " + name)
    if SOURCE_AUDIT not in names or MODAL not in names:
        raise ValueError("scope must include reviewed source audit and scoped optimizer source")
    head = git_text("rev-parse", "HEAD")
    index = Path(git_text("rev-parse", "--git-path", "index"))
    if not index.is_absolute(): index = ROOT / index
    index_sha = file_sha(index)
    if args.fetch: git("fetch", "origin", "main")
    parent = git_text("rev-parse", "origin/main")
    binding_path = args.native_directory / "fixed/arm-binding.json"
    captured_map = args.native_directory / "package-fixed.json"
    binding = json.loads(binding_path.read_bytes())
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
        source_scopes = {}
        for name, change in changes.items():
            staged[name], source_scopes[name] = scoped_source_update(parent, name, staged[name], temporary, change)
        captured = json.loads(captured_map.read_bytes())
        native_changes = native_change_audit(args.native_directory, binding, captured)
        audit = build_scope_audit(parent, staged, binding, source_scopes, binding_path,
            captured_map, native_changes)
        write(BASE / "source-scope.json", audit)
        report = {"repository": str(ROOT), "origin_main_base": parent, "live_head": head,
            "live_index_sha256": index_sha, "workspace_file_sha256": snapshots,
            "prepared_file_sha256": {name: sha(raw) for name, raw in staged.items()},
            "source_audit_sha256": file_sha(BASE / "source-scope.json"), "modal_scope": source_scopes[MODAL],
            "source_scopes": source_scopes, "change_manifest_sha256": file_sha(args.change_manifest),
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
                ":(exclude,glob)" + EVIDENCE + "/**/*.patch",
                ":(exclude,glob)" + EVIDENCE + "/*.patch",
        ":(exclude)" + EVIDENCE + "/convergence-curves.svg")
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
