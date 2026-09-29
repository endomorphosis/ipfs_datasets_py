"""Publish reviewed convergence changes without replacing either live checkout.

This is an explicit final action, never invoked by preparation or test helpers.
Run only after source-scope review, native audit, exact prepared-main tests and
final evidence curation. No weights or Hugging Face uploads occur here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent
EVIDENCE = "docs/implementation/reports/evidence/autoencoder-convergence-20260929"
ENV = {key: value for key, value in os.environ.items() if key not in {
    "GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"}}


def git(cwd, *args, data=None, extra=None):
    return subprocess.check_output(["git", *args], cwd=cwd,
        env={**ENV, **(extra or {})}, input=data).decode().strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_path(cwd):
    path = Path(git(cwd, "rev-parse", "--git-path", "index"))
    return path if path.is_absolute() else cwd / path


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-audit", type=Path, default=BASE / "native-audit.json")
    args = parser.parse_args()
    prepared = json.loads((BASE / "prepared-publication.json").read_bytes())
    assert prepared["live_checkout_preserved"] and not prepared["commit_created"] and not prepared["pushed"]
    assert git(ROOT, "rev-parse", "HEAD") == prepared["live_head"]
    assert sha(index_path(ROOT)) == prepared["live_index_sha256"]
    assert all(sha(ROOT / name) == value for name, value in prepared["workspace_file_sha256"].items())
    assert git(ROOT, "ls-remote", "origin", "refs/heads/main").split()[0] == prepared["origin_main_base"]
    isolated = json.loads((BASE / "main-source-test-summary.json").read_bytes())
    assert isolated["passed"] and isolated["tests"] >= 876 and isolated["failures"] == isolated["errors"] == 0
    assert "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_adaptive_optimizer.py" in isolated["test_files"]
    after_test_changes = git(ROOT, "diff", "--name-only", isolated["source_tree"], prepared["tree"]).splitlines()
    assert all(name.startswith("docs/") for name in after_test_changes), after_test_changes
    native = json.loads(args.native_audit.read_bytes())
    assert native["passed"] and not native["failures"] and native["counts"]["arms"] == 3
    assert native["global_minimum_claim"] is False and native["admitted"] is False
    source_scope = json.loads((ROOT / EVIDENCE / "source-scope.json").read_bytes())
    assert source_scope["captured_native_package_manifest"] == native["producer_manifest"]
    assert source_scope["native_before_after_source_changes"]["same_source_optimizer_ablation"] is True
    # Preserve exact unified-patch context in immutable evidence. Product code,
    # tests, prose, JSON, and ordinary logs remain whitespace checked.
    git(ROOT, "diff", "--check", prepared["origin_main_base"], prepared["tree"], "--", ".",
        ":(exclude,glob)" + EVIDENCE + "/**/*.patch", ":(exclude,glob)" + EVIDENCE + "/*.patch",
        ":(exclude)" + EVIDENCE + "/convergence-curves.svg")
    message = (
        "Add guarded adaptive projection search and bounded epoch controls\n\n"
        "Reject nonfinite baseline/candidate metrics before they can hide loss.\n"
        "Expose bounded epochs, learning rates and attempts; offer explicit\n"
        "job-local adaptive rates and sparse accepted-step momentum while\n"
        "preserving rollback, validation guards and inference separation.\n\n"
        f"Validation: {isolated['tests']} exact prepared-main tests passed.\n"
        "Three same-source native optimizer arms record qualification\n"
        "outcomes, source-locked numeric Lake evidence and six logic-family\n"
        "syntax checks. Tuning and untouched synthetic canaries remain separate.\n"
        "Scoped main differs from the native workspace as documented.\n"
        "No global-minimum, complete legal IR or Constitution claim.\n"
    )
    commit = git(ROOT, "commit-tree", prepared["tree"], "-p", prepared["origin_main_base"], data=message.encode())
    prepared.update(commit=commit, commit_created=True)
    write(BASE / "prepared-publication.json", prepared)
    git(ROOT, "push", "origin", commit + ":refs/heads/main")
    assert git(ROOT, "ls-remote", "origin", "refs/heads/main").split()[0] == commit
    prepared["pushed"] = True
    write(BASE / "prepared-publication.json", prepared)

    parent = ROOT.parents[1]
    live_parent = git(parent, "rev-parse", "HEAD")
    parent_index = sha(index_path(parent))
    git(parent, "fetch", "origin", "main")
    previous = git(parent, "rev-parse", "origin/main")
    old_pin = git(parent, "rev-parse", previous + ":external/ipfs_datasets")
    git(ROOT, "merge-base", "--is-ancestor", old_pin, commit)
    with tempfile.TemporaryDirectory(prefix="convergence-parent-private-index-") as temporary:
        private = {"GIT_INDEX_FILE": str(Path(temporary) / "index")}
        git(parent, "read-tree", previous, extra=private)
        git(parent, "update-index", "--cacheinfo", f"160000,{commit},external/ipfs_datasets", extra=private)
        tree = git(parent, "write-tree", extra=private)
        assert git(parent, "diff", "--name-only", previous, tree) == "external/ipfs_datasets"
        git(parent, "diff", "--check", previous, tree)
        parent_commit = git(parent, "commit-tree", tree, "-p", previous,
            data=b"Pin guarded adaptive autoencoder training controls\n\nRetain unchanged qualification gates and explicit source provenance.\n")
        assert git(parent, "rev-parse", "HEAD") == live_parent and sha(index_path(parent)) == parent_index
        git(parent, "push", "origin", parent_commit + ":refs/heads/main")
        assert git(parent, "ls-remote", "origin", "refs/heads/main").split()[0] == parent_commit
    assert git(ROOT, "rev-parse", "HEAD") == prepared["live_head"] and sha(index_path(ROOT)) == prepared["live_index_sha256"]
    assert git(parent, "rev-parse", "HEAD") == live_parent and sha(index_path(parent)) == parent_index
    assert all(sha(ROOT / name) == value for name, value in prepared["workspace_file_sha256"].items())
    report = {"datasets_commit": commit, "datasets_parent": prepared["origin_main_base"],
        "parent_commit": parent_commit, "parent_previous": previous,
        "live_dataset_head": prepared["live_head"], "live_parent_head": live_parent,
        "live_indexes_preserved": True, "working_trees_preserved": True, "github_main_verified": True,
        "hf_uploads_performed": False, "native_audit_sha256": sha(args.native_audit),
        "native_evidence_scope": "captured pinned workspace; explicit scoped-main differences retained",
        "unrelated_concurrent_edits_included": False, "admitted": False}
    write(BASE / "publication-closeout.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
