"""Real Git integrations preserve the ordinary worktree and fail closed."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_merge as merge
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_lease import source_lease, SourceLeaseTimeout
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True).stdout.strip()


def commit(repo, name, content):
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@localhost")
    commit(repo, "base.txt", "base\n")
    base = commit(repo, "merge_identity.py", "VALUE = 'merged'\n")
    git(repo, "switch", "-qc", "left")
    left = commit(repo, "left.txt", "left\n")
    git(repo, "switch", "--detach", base)
    git(repo, "switch", "-qc", "right")
    right = commit(repo, "right.txt", "right\n")
    git(repo, "switch", "--detach", base)
    (repo / "base.txt").write_text("uncommitted precious edits\n")
    (repo / "untracked.txt").write_text("preserve me\n")
    (repo / "staged.txt").write_text("staged only\n")
    git(repo, "add", "staged.txt")
    return repo, base, left, right


def state(repo):
    return (git(repo, "rev-parse", "HEAD"), (repo / ".git/index").read_bytes(),
            (repo / "base.txt").read_bytes(), (repo / "untracked.txt").read_bytes(),
            (repo / "staged.txt").read_bytes())


def prepare(repo, tmp_path, **kwargs):
    root, base, left, right = repo
    plan = merge.prepare_source_merge(root, base_commit=base, candidate_commits=[left, right],
        integration_ref="refs/autoencoder/integration/test", **kwargs)
    path = tmp_path / "plan.json"
    digest = merge.write_merge_plan(path, plan)
    return plan, dict(repo_root=root, plan_path=path, expected_plan_sha256=digest,
        validator_argv=[sys.executable, "-c", "from pathlib import Path; assert Path('left.txt').read_text() == 'left\\n'; assert Path('right.txt').read_text() == 'right\\n'; assert Path('base.txt').read_text() == 'base\\n'"],
        scratch_directory=tmp_path)


def test_nonconflicting_merge_validates_exact_tree_without_changing_dirty_checkout(repo, tmp_path):
    root = repo[0]; before = state(root)
    plan, args = prepare(repo, tmp_path)
    assert plan["status"] == "prepared"
    assert state(root) == before
    receipt = merge.apply_source_merge(**args)
    assert receipt["applied"] is True
    assert receipt["admitted"] is receipt["model_qualified"] is receipt["main_published"] is False
    assert receipt["validation"]["merged_tree"] == plan["merged_tree"]
    assert git(root, "rev-parse", plan["integration_ref"] + "^{tree}") == plan["merged_tree"]
    assert git(root, "show", plan["integration_commit"] + ":left.txt") == "left"
    assert git(root, "show", plan["integration_commit"] + ":right.txt") == "right"
    assert state(root) == before
    assert not list(tmp_path.glob("autoencoder-source-validation-*"))


def test_conflict_is_retained_and_cannot_apply(repo, tmp_path):
    root, base, _, _ = repo
    # Commit objects are created via a temporary index; live dirty index remains intact.
    def branch(value):
        blob = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=value,
            text=True, capture_output=True, check=True).stdout.strip()
        tree = subprocess.run(["git", "-C", str(root), "mktree"], input=f"100644 blob {blob}\tbase.txt\n",
            text=True, capture_output=True, check=True).stdout.strip()
        return merge._candidate_commit(root, tree, [base])
    before = state(root)
    plan = merge.prepare_source_merge(root, base_commit=base, candidate_commits=[branch("A\n"), branch("B\n")],
        integration_ref="refs/autoencoder/integration/conflict")
    assert plan["status"] == "conflicted" and plan["merged_tree"] is None
    assert "CONFLICT" in plan["steps"][-1]["diagnostic"]
    path = tmp_path / "conflict.json"; digest = merge.write_merge_plan(path, plan)
    with pytest.raises(merge.SourceMergeError, match="nonconflicting"):
        merge.apply_source_merge(root, plan_path=path, expected_plan_sha256=digest, validator_argv=["true"])
    assert state(root) == before


def test_stale_ref_refuses_before_validator(repo, tmp_path):
    plan, args = prepare(repo, tmp_path)
    git(repo[0], "update-ref", plan["integration_ref"], repo[2])
    args["validator_argv"] = ["cannot-run-this-command"]
    with pytest.raises(merge.SourceMergeError, match="stale integration ref"):
        merge.apply_source_merge(**args)
    assert git(repo[0], "rev-parse", plan["integration_ref"]) == repo[2]


def test_reader_lease_blocks_ref_application(repo, tmp_path):
    plan, args = prepare(repo, tmp_path)
    args["lease_timeout_seconds"] = 0
    with source_lease(repo[0], mode="read"):
        with pytest.raises(SourceLeaseTimeout):
            merge.apply_source_merge(**args)
    assert merge._ref(repo[0], plan["integration_ref"]) is None


@pytest.mark.parametrize("command", ["raise SystemExit(3)", "from pathlib import Path; Path('left.txt').write_text('changed')"])
def test_failing_or_tree_mutating_validator_cannot_advance_ref(repo, tmp_path, command):
    before = state(repo[0]); plan, args = prepare(repo, tmp_path)
    args["validator_argv"] = [sys.executable, "-c", command]
    receipt = merge.apply_source_merge(**args)
    assert not receipt["applied"] and "failure" in receipt["validation"]
    assert merge._ref(repo[0], plan["integration_ref"]) is None
    assert state(repo[0]) == before


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/autoencoder/integration/", "refs/autoencoder/integration/bad..ref"])
def test_only_internal_well_formed_ref_allowed(repo, ref):
    with pytest.raises(merge.SourceMergeError):
        merge.prepare_source_merge(repo[0], base_commit=repo[1], candidate_commits=[repo[2]], integration_ref=ref)


def test_symbolic_ref_cannot_redirect_application(repo, tmp_path):
    plan, args = prepare(repo, tmp_path)
    git(repo[0], "symbolic-ref", plan["integration_ref"], "refs/heads/main")
    with pytest.raises(merge.SourceMergeError, match="symbolic"):
        merge.apply_source_merge(**args)


@pytest.mark.parametrize("fault", ["digest", "tamper", "bytes", "timeout", "candidate_alias"])
def test_review_and_validation_bounds_fail_closed(repo, tmp_path, fault):
    plan, args = prepare(repo, tmp_path)
    if fault == "digest":
        args["expected_plan_sha256"] = "0" * 64
    elif fault == "tamper":
        plan["merged_tree"] = git(repo[0], "rev-parse", repo[1] + "^{tree}")
        args["plan_path"].unlink()
        args["expected_plan_sha256"] = merge.write_merge_plan(args["plan_path"], plan)
    elif fault == "bytes":
        args["max_checkout_bytes"] = 1
    elif fault == "timeout":
        args["validation_timeout_seconds"] = 0.04
        args["validator_argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        receipt = merge.apply_source_merge(**args)
        assert receipt["validation"]["failure"] == "validator timeout" and not receipt["applied"]
        return
    else:
        with pytest.raises(merge.SourceMergeError, match="immutable"):
            merge.prepare_source_merge(repo[0], base_commit="HEAD", candidate_commits=[repo[2]],
                integration_ref=plan["integration_ref"])
        return
    with pytest.raises(merge.SourceMergeError):
        merge.apply_source_merge(**args)
    assert merge._ref(repo[0], plan["integration_ref"]) is None


def test_existing_internal_base_cas_and_fresh_validation(repo, tmp_path):
    ref = "refs/autoencoder/integration/test"
    git(repo[0], "update-ref", ref, repo[1])
    plan, args = prepare(repo, tmp_path)
    assert plan["expected_ref_commit"] == repo[1]
    receipt = merge.apply_source_merge(**args)
    assert receipt["applied"]
    with pytest.raises(merge.SourceMergeError, match="stale"):
        merge.apply_source_merge(**args)


def test_git_environment_does_not_select_callers_index(repo, tmp_path, monkeypatch):
    bad = tmp_path / "unrelated-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(bad))
    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    plan, args = prepare(repo, tmp_path)
    assert merge.apply_source_merge(**args)["applied"]
    assert not bad.exists()


def test_ref_change_during_validation_preserves_evidence_and_ref(repo, tmp_path):
    plan, args = prepare(repo, tmp_path)
    args["validator_argv"] = [sys.executable, "-c", "import subprocess; subprocess.run(" + repr(
        ["git", "-C", str(repo[0]), "update-ref", plan["integration_ref"], repo[2]]) + ", check=True)"]
    receipt = merge.apply_source_merge(**args)
    assert not receipt["applied"] and "stale" in receipt["failure"]
    assert receipt["validation"]["returncode"] == 0
    assert git(repo[0], "rev-parse", plan["integration_ref"]) == repo[2]


@pytest.mark.parametrize("symlink", [False, True])
def test_plan_cli_and_apply_cli_preserve_dirty_checkout(repo, tmp_path, setup, monkeypatch, symlink):
    import json
    script = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/merge_autoencoder_source.py"
    root, base, left, right = repo
    before = state(root)
    if symlink:
        blob = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input="left.txt",
            text=True, capture_output=True, check=True).stdout.strip()
        listing = git(root, "ls-tree", left) + f"\n120000 blob {blob}\talias\n"
        tree = subprocess.run(["git", "-C", str(root), "mktree"], input=listing,
            text=True, capture_output=True, check=True).stdout.strip()
        left = merge._candidate_commit(root, tree, [left])
    path, receipt_path = tmp_path / "cli-plan.json", tmp_path / "cli-receipt.json"
    result = subprocess.run([sys.executable, str(script), "--repo", str(root), "plan", "--base", base,
        "--candidate", left, "--candidate", right, "--integration-ref", "refs/autoencoder/integration/cli",
        "--output", str(path)], check=True, text=True, capture_output=True)
    digest = json.loads(result.stdout)["sha256"]
    import importlib.util
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    monkeypatch.setattr(resources, "MAX_STORAGE_BYTES", 100_000_000)
    factory, roots, ledger, scheduler = setup
    with factory(storage_bytes=1000) as owner:
        owner.release(artifacts_durable=True)
    spec = importlib.util.spec_from_file_location("_source_merge_cli", script)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    output = roots[0] / "merge"
    rc = cli.main(["--repo", str(root), "apply", "--plan", str(path),
        "--plan-sha256", digest, "--output-directory", str(output), "--resource-ledger", str(ledger),
        "--max-checkout-bytes", "10000", "--", sys.executable, "-c",
        "from pathlib import Path; assert Path('left.txt').exists() and Path('right.txt').exists()" +
        ("; assert Path('alias').is_symlink() and Path('alias').read_text() == 'left\\n'" if symlink else "")])
    assert rc == 0
    receipt_path = output / "evidence/receipt.json"
    accounting = json.loads((output / "evidence/resources.json").read_text())
    assert accounting["status"] == "released"
    assert accounting["record"]["external_charges"]["isolated-source-checkout"] >= 10000
    assert scheduler.snapshot()["allocated_child_process_slots"] == 0
    receipt = json.loads(receipt_path.read_text())
    assert receipt["applied"] and not receipt["admitted"]
    assert state(root) == before


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_plan_alias_cannot_authorize_update(repo, tmp_path, alias):
    _, args = prepare(repo, tmp_path)
    other = tmp_path / "aliased.json"
    if alias == "symlink":
        other.symlink_to(args["plan_path"])
    else:
        os.link(args["plan_path"], other)
    args["plan_path"] = other
    with pytest.raises((merge.SourceMergeError, OSError)):
        merge.apply_source_merge(**args)


def test_untracked_source_added_by_validator_cannot_be_integrated(repo, tmp_path):
    plan, args = prepare(repo, tmp_path)
    args["validator_argv"] = [sys.executable, "-c", "from pathlib import Path; Path('extra.py').write_text('x = 1')"]
    receipt = merge.apply_source_merge(**args)
    assert not receipt["applied"] and "untracked" in receipt["validation"]["failure"]
    assert merge._ref(repo[0], plan["integration_ref"]) is None


@pytest.mark.parametrize("fault", ["no_capacity", "external_growth"])
def test_cli_resource_gate_blocks_unfunded_or_growing_checkout(repo, tmp_path, setup, monkeypatch, fault):
    import importlib.util
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    cap = 50_000_000 if fault == "no_capacity" else 100_000_000
    monkeypatch.setattr(resources, "MAX_STORAGE_BYTES", cap)
    factory, roots, ledger, _ = setup
    with factory(storage_bytes=1000) as owner:
        owner.release(artifacts_durable=True)
    plan, args = prepare(repo, tmp_path)
    script = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/merge_autoencoder_source.py"
    spec = importlib.util.spec_from_file_location("_source_merge_cli_resource", script)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    output = roots[0] / "blocked"
    validator = ("raise AssertionError('must not run')" if fault == "no_capacity" else
                 "from pathlib import Path; Path('oversized').write_bytes(b'x' * (18 * 1024 * 1024))")
    with pytest.raises((resources.DaemonResourceError, merge.SourceMergeError)):
        cli.main(["--repo", str(repo[0]), "apply", "--plan", str(args["plan_path"]),
            "--plan-sha256", args["expected_plan_sha256"], "--output-directory", str(output),
            "--resource-ledger", str(ledger), "--max-checkout-bytes", "10000", "--",
            sys.executable, "-c", validator])
    assert merge._ref(repo[0], plan["integration_ref"]) is None
    assert not list(output.glob("autoencoder-source-validation-*"))


def test_validator_imports_merged_source_despite_conflicting_outer_pythonpath(repo, tmp_path, monkeypatch):
    outside = tmp_path / "drifted"; outside.mkdir()
    (outside / "merge_identity.py").write_text("VALUE = 'drifted'\n")
    monkeypatch.setenv("PYTHONPATH", str(outside))
    monkeypatch.setenv("PYTHONHOME", "/invalid-python-home")
    plan, args = prepare(repo, tmp_path)
    args["validator_argv"] = [sys.executable, "-c", "import os, pathlib, merge_identity; "
        "assert merge_identity.VALUE == 'merged'; "
        "assert pathlib.Path(merge_identity.__file__).parent == pathlib.Path(os.environ['AUTOENCODER_VALIDATION_SOURCE_ROOT']); "
        "assert os.environ['AUTOENCODER_VALIDATION_GIT_TREE'] == " + repr(plan["merged_tree"])]
    receipt = merge.apply_source_merge(**args)
    assert receipt["applied"] and receipt["validation"]["returncode"] == 0
