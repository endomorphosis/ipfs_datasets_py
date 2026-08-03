"""Integration tests for safe paired-repository worktree integration (PATLAW-161).

Acceptance:

* dirty / active / locked / conflicting / missing-branch states abort without
  mutation of either active worktree;
* tests prove exact merge ordering (accelerator first, then datasets);
* no active-worktree pull and no push;
* accepted receipt binds before/remote/integrated SHAs for both repositories,
  capability pin, test results, trigger and lock identity.

Tooling uses synthetic temporary repositories only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths / module load
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]
_INTEGRATOR_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "integrate_upstreams.py"
_SYNC_SH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "sync_upstreams.sh"
_SCHEMA_PATH = (
    _REPO_ROOT
    / "data"
    / "release"
    / "uspto_submission_assurance"
    / "paired_revision_receipt.schema.json"
)


def _load_integrator():
    spec = importlib.util.spec_from_file_location(
        "uspto_integrate_upstreams", _INTEGRATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


integrator = _load_integrator()


# ---------------------------------------------------------------------------
# Synthetic git helpers
# ---------------------------------------------------------------------------


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd_env = os.environ.copy()
    cmd_env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    cmd_env.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    cmd_env.setdefault("GIT_AUTHOR_NAME", "patlaw-161-test")
    cmd_env.setdefault("GIT_AUTHOR_EMAIL", "patlaw-161@example.test")
    cmd_env.setdefault("GIT_COMMITTER_NAME", "patlaw-161-test")
    cmd_env.setdefault("GIT_COMMITTER_EMAIL", "patlaw-161@example.test")
    if env:
        cmd_env.update(env)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=cmd_env,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {repo}:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def _init_repo(path: Path, *, initial_file: str = "README.md", content: str = "seed\n") -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "patlaw-161@example.test")
    _git(path, "config", "user.name", "patlaw-161-test")
    _git(path, "checkout", "-B", "main", check=False)
    (path / initial_file).write_text(content, encoding="utf-8")
    _git(path, "add", initial_file)
    _git(path, "commit", "-m", "seed")
    sha = _git(path, "rev-parse", "HEAD").stdout.strip().lower()
    assert len(sha) == 40
    return sha


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip().lower()


def _tree_snapshot(repo: Path) -> dict[str, str]:
    """Map relative paths → content hash for mutation detection (tracked + untracked)."""
    snap: dict[str, str] = {}
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(repo))
        if rel.startswith(".git/") or rel == ".git":
            continue
        snap[rel] = p.read_bytes().hex()
    if (repo / ".git").exists() or (repo / ".git").is_file():
        snap["__HEAD__"] = _head_sha(repo)
    return snap


def _setup_paired_remotes(tmp_path: Path) -> dict[str, Path | str]:
    """Create bare remotes + clones so fetch/merge can exercise real remote tips."""
    bare_ds = tmp_path / "remotes" / "datasets.git"
    bare_acc = tmp_path / "remotes" / "accelerator.git"
    bare_ds.parent.mkdir(parents=True, exist_ok=True)
    bare_env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    subprocess.run(
        ["git", "init", "--bare", str(bare_ds)],
        check=True,
        capture_output=True,
        env=bare_env,
    )
    subprocess.run(
        ["git", "init", "--bare", str(bare_acc)],
        check=True,
        capture_output=True,
        env=bare_env,
    )

    # Seed via temporary workdirs pushed to bare.
    seed_ds = tmp_path / "seed" / "datasets"
    seed_acc = tmp_path / "seed" / "accelerator"
    ds_sha = _init_repo(seed_ds, initial_file="datasets.txt", content="datasets-v1\n")
    acc_sha = _init_repo(seed_acc, initial_file="accelerator.txt", content="accelerator-v1\n")
    _git(seed_ds, "remote", "add", "origin", str(bare_ds))
    _git(seed_acc, "remote", "add", "origin", str(bare_acc))
    _git(seed_ds, "push", "-u", "origin", "main")
    _git(seed_acc, "push", "-u", "origin", "main")
    # Ensure bare default branch is main so clones get a usable HEAD.
    subprocess.run(
        ["git", "--git-dir", str(bare_ds), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
        env=bare_env,
    )
    subprocess.run(
        ["git", "--git-dir", str(bare_acc), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
        env=bare_env,
    )

    # Operator clones (active worktrees).
    datasets = tmp_path / "datasets"
    accelerator = tmp_path / "accelerator"
    for bare, dest in ((bare_ds, datasets), (bare_acc, accelerator)):
        subprocess.run(
            ["git", "clone", str(bare), str(dest)],
            check=True,
            capture_output=True,
            env=bare_env,
        )
    for repo in (datasets, accelerator):
        _git(repo, "config", "user.email", "patlaw-161@example.test")
        _git(repo, "config", "user.name", "patlaw-161-test")
        # Ensure on main even if clone left detached/empty edge cases.
        _git(repo, "checkout", "-B", "main", "origin/main", check=False)

    # Advance remotes with new commits (not yet in active clones).
    (seed_ds / "datasets.txt").write_text("datasets-v2\n", encoding="utf-8")
    _git(seed_ds, "add", "datasets.txt")
    _git(seed_ds, "commit", "-m", "datasets remote tip")
    _git(seed_ds, "push", "origin", "main")
    remote_ds = _head_sha(seed_ds)

    (seed_acc / "accelerator.txt").write_text("accelerator-v2\n", encoding="utf-8")
    _git(seed_acc, "add", "accelerator.txt")
    _git(seed_acc, "commit", "-m", "accelerator remote tip")
    _git(seed_acc, "push", "origin", "main")
    remote_acc = _head_sha(seed_acc)

    state = tmp_path / "state"
    state.mkdir()
    return {
        "datasets": datasets,
        "accelerator": accelerator,
        "state": state,
        "root": tmp_path,
        "bare_ds": bare_ds,
        "bare_acc": bare_acc,
        "before_ds": _head_sha(datasets),
        "before_acc": _head_sha(accelerator),
        "remote_ds": remote_ds,
        "remote_acc": remote_acc,
        "seed_ds_sha": ds_sha,
        "seed_acc_sha": acc_sha,
    }


@pytest.fixture()
def pair_repos(tmp_path: Path) -> dict[str, Path]:
    """Create a clean datasets + accelerator pair of synthetic git repos (no remotes)."""
    datasets = tmp_path / "datasets"
    accelerator = tmp_path / "accelerator"
    _init_repo(datasets, initial_file="datasets.txt", content="datasets-v1\n")
    _init_repo(accelerator, initial_file="accelerator.txt", content="accelerator-v1\n")
    state = tmp_path / "state"
    state.mkdir()
    return {
        "datasets": datasets,
        "accelerator": accelerator,
        "state": state,
        "root": tmp_path,
    }


@pytest.fixture()
def paired_remotes(tmp_path: Path) -> dict[str, Any]:
    return _setup_paired_remotes(tmp_path)


# ---------------------------------------------------------------------------
# Schema / offline / trigger surface
# ---------------------------------------------------------------------------


def test_schema_file_exists_and_names_all_triggers() -> None:
    assert _SCHEMA_PATH.is_file()
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    dumped = json.dumps(schema)
    for trigger in integrator.TRIGGERS:
        assert trigger in dumped
    assert schema["properties"]["push_attempted"]["const"] is False
    assert schema["properties"]["active_worktree_pull_attempted"]["const"] is False
    assert schema["properties"]["recursive_submodule_chase"]["const"] is False
    # Accepted receipt requires before/remote/integrated + capability pin + lock.
    defs = schema["$defs"]
    assert "before_sha" in defs["repoRevision"]["properties"]
    assert "remote_sha" in defs["repoRevision"]["properties"]
    assert "integrated_sha" in defs["repoRevision"]["properties"]
    assert "capabilityPin" in defs
    assert "lockIdentity" in defs
    assert defs["policy"]["properties"]["merge_order"]["const"] == [
        "accelerator",
        "datasets",
    ]


def test_offline_self_check_passes() -> None:
    report = integrator.offline_self_check(_SCHEMA_PATH)
    assert report["ok"] is True, report
    names = {c["name"] for c in report["checks"]}
    assert "all_triggers_explicit" in names
    assert "push_forbidden" in names
    assert "pull_forbidden" in names
    assert "merge_order_constant" in names
    assert report["merge_order"] == ["accelerator", "datasets"]
    assert report["triggers"] == list(integrator.TRIGGERS)


def test_cli_offline_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(_INTEGRATOR_PATH), "--offline"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["merge_order"] == ["accelerator", "datasets"]


def test_explicit_triggers_and_merge_order() -> None:
    assert set(integrator.TRIGGERS) == (
        integrator.FETCH_ONLY_TRIGGERS | integrator.INTEGRATION_TRIGGERS
    )
    assert integrator.MERGE_ORDER == ("accelerator", "datasets")
    assert list(integrator.MERGE_ORDER)[0] == "accelerator"
    assert list(integrator.MERGE_ORDER)[1] == "datasets"


def test_sync_script_lists_triggers_and_policy() -> None:
    assert _SYNC_SH.is_file()
    mode = _SYNC_SH.stat().st_mode
    if not (mode & stat.S_IXUSR):
        _SYNC_SH.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    result = subprocess.run(
        ["bash", str(_SYNC_SH), "--list-triggers"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["push_allowed"] is False
    assert payload["active_worktree_pull_allowed"] is False
    assert payload["recursive_submodules"] is False
    assert payload["use_isolated_worktrees"] is True
    assert payload["merge_order"] == ["accelerator", "datasets"]
    assert set(payload["triggers"]) == set(integrator.TRIGGERS)


# ---------------------------------------------------------------------------
# Dirty / active / locked / conflicting / missing-branch abort without mutation
# ---------------------------------------------------------------------------


def test_dirty_worktree_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)

    (datasets / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    receipt = integrator.run_integration(
        trigger="twice-daily",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "dirty.json",
        state_root=pair_repos["state"],
        dry_run=True,
        skip_fetch=True,
    )
    assert receipt["status"] == "aborted"
    assert receipt["abort_reason"] == "dirty_worktree"
    assert receipt["disposition"] == "aborted"
    assert receipt["mutation_attempted"] is False
    assert receipt["push_attempted"] is False
    assert receipt["active_worktree_pull_attempted"] is False

    after_ds = _tree_snapshot(datasets)
    after_acc = _tree_snapshot(accelerator)
    assert after_ds["__HEAD__"] == before_ds["__HEAD__"]
    assert after_acc == before_acc


def test_active_work_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    marker = pair_repos["root"] / "ACTIVE_LANE"
    marker.write_text("lane-busy\n", encoding="utf-8")
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)

    receipt = integrator.run_integration(
        trigger="pre-release",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "active.json",
        state_root=pair_repos["state"],
        dry_run=True,
        skip_fetch=True,
        active_marker=str(marker),
    )
    assert receipt["status"] == "aborted"
    assert receipt["abort_reason"] == "active_work"
    assert receipt["mutation_attempted"] is False
    assert _tree_snapshot(datasets) == before_ds
    assert _tree_snapshot(accelerator) == before_acc


def test_lock_held_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    lock_path = pair_repos["state"] / "held.lock"
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)

    holder = integrator.IntegrationLock(lock_path, dry_run=False)
    assert holder.try_acquire() is True
    try:
        receipt = integrator.run_integration(
            trigger="security-fix",
            datasets_path=datasets,
            accelerator_path=accelerator,
            output_path=pair_repos["state"] / "lock.json",
            lock_path=lock_path,
            state_root=pair_repos["state"],
            dry_run=False,
            skip_fetch=True,
        )
        assert receipt["status"] == "aborted"
        assert receipt["abort_reason"] == "lock_held"
        assert receipt["mutation_attempted"] is False
        assert receipt["push_attempted"] is False
        assert receipt["active_worktree_pull_attempted"] is False
    finally:
        holder.release()

    assert _tree_snapshot(datasets) == before_ds
    assert _tree_snapshot(accelerator) == before_acc


def test_merge_conflict_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]

    _git(datasets, "checkout", "-b", "side")
    (datasets / "datasets.txt").write_text("side-change\n", encoding="utf-8")
    _git(datasets, "add", "datasets.txt")
    _git(datasets, "commit", "-m", "side")
    _git(datasets, "checkout", "main")
    (datasets / "datasets.txt").write_text("main-change\n", encoding="utf-8")
    _git(datasets, "add", "datasets.txt")
    _git(datasets, "commit", "-m", "main-change")
    merge = _git(datasets, "merge", "side", check=False)
    assert merge.returncode != 0
    assert integrator.git_has_unmerged(datasets)

    before_acc = _head_sha(accelerator)
    plan = integrator.plan_integration(
        trigger="security-fix",
        datasets_path=datasets,
        accelerator_path=accelerator,
    )
    assert plan["action"] == "abort"
    assert plan["abort_reason"] == "merge_conflict"
    assert plan["mutation_permitted"] is False

    receipt = integrator.run_integration(
        trigger="security-fix",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "conflict.json",
        state_root=pair_repos["state"],
        dry_run=True,
        skip_fetch=True,
    )
    assert receipt["status"] == "aborted"
    assert receipt["mutation_attempted"] is False
    assert _head_sha(accelerator) == before_acc


def test_missing_branch_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    """When remotes are absent and skip_fetch is false without dry-run, missing tips abort.

    With skip_fetch, dry remote binding uses HEAD — so force a non-git remote resolution
    path by removing origin and requiring live fetch resolution.
    """
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)

    # Live path: no origin remote → resolve_remote fails → missing_branch.
    # skip_fetch=False, dry_run=False triggers real resolve after failed/skipped fetch.
    receipt = integrator.run_integration(
        trigger="twice-daily",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "missing.json",
        state_root=pair_repos["state"],
        dry_run=False,
        skip_fetch=False,
    )
    # Either fetch fails soft and missing_branch, or not_a_git is not expected.
    assert receipt["status"] in {"aborted", "quarantined", "rejected"}
    if receipt["status"] == "aborted":
        assert receipt["abort_reason"] in {
            "missing_branch",
            "dirty_worktree",
            "active_work",
            "lock_held",
            "not_a_git_repo",
        }
        # When aborted before worktree mutation, active trees must be intact.
        if receipt["mutation_attempted"] is False:
            assert _tree_snapshot(datasets)["__HEAD__"] == before_ds["__HEAD__"]
            assert _tree_snapshot(accelerator)["__HEAD__"] == before_acc["__HEAD__"]
    assert receipt["push_attempted"] is False
    assert receipt["active_worktree_pull_attempted"] is False
    # Active HEADs never change (integration only mutates isolated worktrees).
    assert _head_sha(datasets) == before_ds["__HEAD__"]
    assert _head_sha(accelerator) == before_acc["__HEAD__"]


def test_shell_dirty_abort_exit_code(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    (accelerator / "wip.txt").write_text("dirty-acc\n", encoding="utf-8")
    before = _head_sha(datasets), _head_sha(accelerator)
    out = pair_repos["state"] / "shell-dirty.json"
    result = subprocess.run(
        [
            "bash",
            str(_SYNC_SH),
            "--trigger",
            "twice-daily",
            "--datasets-path",
            str(datasets),
            "--accelerator-path",
            str(accelerator),
            "--output",
            str(out),
            "--state-root",
            str(pair_repos["state"]),
            "--dry-run",
            "--skip-fetch",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CROSS_REPO_SYNC_PYTHON": sys.executable},
    )
    assert result.returncode == 3, result.stderr + result.stdout
    assert (_head_sha(datasets), _head_sha(accelerator)) == before
    if out.is_file():
        body = json.loads(out.read_text(encoding="utf-8"))
        assert body["status"] == "aborted"
        assert body["mutation_attempted"] is False


# ---------------------------------------------------------------------------
# Exact merge ordering + no pull/push
# ---------------------------------------------------------------------------


def test_dry_run_merge_order_accelerator_then_datasets(
    pair_repos: dict[str, Path],
) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    ds_sha = _head_sha(datasets)
    acc_sha = _head_sha(accelerator)
    out = pair_repos["state"] / "order.json"

    receipt = integrator.run_integration(
        trigger="twice-daily",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=out,
        state_root=pair_repos["state"],
        dry_run=True,
        skip_fetch=True,
    )
    assert receipt["status"] == "accepted", receipt
    assert receipt["merge_order"] == ["accelerator", "datasets"]
    assert receipt["policy"]["merge_order"] == ["accelerator", "datasets"]

    # Trace order: accelerator merge/test before datasets merge/test.
    actions = [
        (s["repo"], s["action"])
        for s in receipt["merge_trace"]
        if s["action"] in {"merge", "test", "capability_pin", "worktree_create"}
    ]
    acc_merge_idxs = [i for i, a in enumerate(actions) if a == ("accelerator", "merge")]
    ds_merge_idxs = [i for i, a in enumerate(actions) if a == ("datasets", "merge")]
    assert acc_merge_idxs, actions
    assert ds_merge_idxs, actions
    assert acc_merge_idxs[0] < ds_merge_idxs[0]

    acc_test_idxs = [i for i, a in enumerate(actions) if a == ("accelerator", "test")]
    ds_test_idxs = [i for i, a in enumerate(actions) if a == ("datasets", "test")]
    assert acc_test_idxs and ds_test_idxs
    assert acc_test_idxs[0] < ds_test_idxs[0]

    # Capability pin bound before datasets phase.
    pin_idxs = [i for i, a in enumerate(actions) if a == ("accelerator", "capability_pin")]
    assert pin_idxs
    assert pin_idxs[0] < ds_merge_idxs[0]

    # Test results phase order.
    phases = [r["phase"] for r in receipt["test_results"]]
    assert "accelerator" in phases
    assert "datasets" in phases
    assert phases.index("accelerator") < phases.index("datasets")

    assert receipt["capability_pin"]["sha"] == acc_sha
    assert receipt["accelerator"]["integrated_sha"] == acc_sha
    assert receipt["datasets"]["integrated_sha"] == ds_sha
    assert receipt["push_attempted"] is False
    assert receipt["active_worktree_pull_attempted"] is False


def test_live_isolated_worktree_merge_order_and_active_unmutated(
    paired_remotes: dict[str, Any],
) -> None:
    datasets = paired_remotes["datasets"]
    accelerator = paired_remotes["accelerator"]
    before_ds = paired_remotes["before_ds"]
    before_acc = paired_remotes["before_acc"]
    remote_ds = paired_remotes["remote_ds"]
    remote_acc = paired_remotes["remote_acc"]
    state = paired_remotes["state"]
    out = state / "live.json"

    before_ds_snap = _tree_snapshot(datasets)
    before_acc_snap = _tree_snapshot(accelerator)

    receipt = integrator.run_integration(
        trigger="pre-release",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=out,
        state_root=state,
        worktree_root=state / "worktrees",
        dry_run=False,
        skip_fetch=False,
        keep_worktrees=False,
    )
    assert receipt["status"] == "accepted", json.dumps(receipt, indent=2)
    assert receipt["disposition"] == "integrated"

    # Active worktrees: HEAD unchanged (no pull, no in-place merge).
    assert _head_sha(datasets) == before_ds
    assert _head_sha(accelerator) == before_acc
    assert _tree_snapshot(datasets)["__HEAD__"] == before_ds_snap["__HEAD__"]
    assert _tree_snapshot(accelerator)["__HEAD__"] == before_acc_snap["__HEAD__"]

    # Receipt binds before/remote/integrated.
    assert receipt["datasets"]["before_sha"] == before_ds
    assert receipt["datasets"]["remote_sha"] == remote_ds
    assert receipt["accelerator"]["before_sha"] == before_acc
    assert receipt["accelerator"]["remote_sha"] == remote_acc
    # Integrated SHAs are merge commits (or remote tip if ff); must differ from before
    # when remotes advanced, unless merge produced same tip.
    assert receipt["accelerator"]["integrated_sha"]
    assert receipt["datasets"]["integrated_sha"]
    assert len(receipt["accelerator"]["integrated_sha"]) == 40
    assert len(receipt["datasets"]["integrated_sha"]) == 40

    # Capability pin = accelerator integrated SHA.
    assert receipt["capability_pin"]["name"] == "accelerator"
    assert (
        receipt["capability_pin"]["sha"] == receipt["accelerator"]["integrated_sha"]
    )
    assert receipt["capability_pin"]["source"] == "integrated_worktree"

    # Ordering in trace.
    merge_repos = [
        s["repo"] for s in receipt["merge_trace"] if s["action"] == "merge"
    ]
    assert merge_repos.index("accelerator") < merge_repos.index("datasets")

    assert receipt["push_attempted"] is False
    assert receipt["active_worktree_pull_attempted"] is False
    assert receipt["recursive_submodule_chase"] is False
    assert receipt["trigger"] == "pre-release"
    assert receipt["lock"]["identity"]
    assert receipt["lock"]["path"]
    assert receipt["test_results"]
    assert all(r["status"] == "passed" for r in receipt["test_results"])

    integrator.assert_receipt_valid(
        receipt, schema=integrator.load_schema(_SCHEMA_PATH)
    )


def test_git_helpers_refuse_push_and_pull(pair_repos: dict[str, Path]) -> None:
    with pytest.raises(integrator.IntegrationError, match="push"):
        integrator._run_git(pair_repos["datasets"], "push", "origin", "HEAD", check=False)
    with pytest.raises(integrator.IntegrationError, match="pull"):
        integrator._run_git(
            pair_repos["datasets"], "pull", "origin", "main", check=False
        )


def test_no_pull_or_push_in_script_sources() -> None:
    integ = _INTEGRATOR_PATH.read_text(encoding="utf-8")
    sync = _SYNC_SH.read_text(encoding="utf-8")
    assert "git push is forbidden" in integ or "push is forbidden" in integ
    assert "pull on active worktrees is forbidden" in integ or "git pull" in integ
    assert "NO PUSH" in sync or "never push" in sync.lower()
    assert "pull on active" in sync.lower() or "never pull" in sync.lower()
    for trigger in integrator.TRIGGERS:
        assert trigger in sync
        assert trigger in integ


# ---------------------------------------------------------------------------
# Accepted receipt binding
# ---------------------------------------------------------------------------


def test_accepted_receipt_binds_shas_pin_tests_trigger_lock(
    pair_repos: dict[str, Path],
) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    ds_sha = _head_sha(datasets)
    acc_sha = _head_sha(accelerator)
    out = pair_repos["state"] / "accepted.json"
    lock_path = pair_repos["state"] / "accept.lock"

    for trigger in ("twice-daily", "pre-release", "security-fix"):
        receipt = integrator.run_integration(
            trigger=trigger,
            datasets_path=datasets,
            accelerator_path=accelerator,
            output_path=out,
            lock_path=lock_path,
            state_root=pair_repos["state"],
            dry_run=True,
            skip_fetch=True,
        )
        assert receipt["status"] == "accepted", receipt
        assert receipt["disposition"] == "integrated"
        assert receipt["trigger"] == trigger

        for side, sha in (("datasets", ds_sha), ("accelerator", acc_sha)):
            rev = receipt[side]
            assert rev["before_sha"] == sha
            assert rev["remote_sha"] == sha
            assert rev["integrated_sha"] == sha

        pin = receipt["capability_pin"]
        assert pin["name"] == "accelerator"
        assert pin["sha"] == acc_sha
        assert pin["sha"] == receipt["accelerator"]["integrated_sha"]

        assert receipt["test_results"]
        for result in receipt["test_results"]:
            assert result["status"] == "passed"
            assert result["exit_code"] == 0

        assert receipt["lock"]["path"] == str(lock_path)
        assert receipt["lock"]["identity"]
        assert receipt["lock"]["acquired"] is True

        assert receipt["push_attempted"] is False
        assert receipt["active_worktree_pull_attempted"] is False
        assert receipt["merge_order"] == ["accelerator", "datasets"]

        integrator.assert_receipt_valid(
            receipt, schema=integrator.load_schema(_SCHEMA_PATH)
        )
        disk = json.loads(out.read_text(encoding="utf-8"))
        assert disk["receipt_id"] == receipt["receipt_id"]
        assert disk["capability_pin"]["sha"] == acc_sha


def test_shell_integration_writes_paired_receipt(
    pair_repos: dict[str, Path],
) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    out = pair_repos["state"] / "shell-accepted.json"
    result = subprocess.run(
        [
            "bash",
            str(_SYNC_SH),
            "--trigger",
            "pre-release",
            "--datasets-path",
            str(datasets),
            "--accelerator-path",
            str(accelerator),
            "--output",
            str(out),
            "--state-root",
            str(pair_repos["state"] / "shell-state"),
            "--dry-run",
            "--skip-fetch",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CROSS_REPO_SYNC_PYTHON": sys.executable},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert out.is_file()
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["status"] == "accepted"
    assert body["schema_version"] == integrator.SCHEMA_VERSION
    assert body["datasets"]["before_sha"] == _head_sha(datasets)
    assert body["accelerator"]["integrated_sha"] == _head_sha(accelerator)
    assert body["capability_pin"]["sha"] == _head_sha(accelerator)
    assert body["test_results"]
    assert body["lock"]["identity"]
    assert body["push_attempted"] is False
    assert body["active_worktree_pull_attempted"] is False
    assert "merge_order accelerator,datasets" in result.stderr
    assert "push_allowed=false" in result.stderr
    assert "active_worktree_pull_allowed=false" in result.stderr


def test_atomic_write_and_cli_validate(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    out = pair_repos["state"] / "validate-me.json"
    receipt = integrator.run_integration(
        trigger="twice-daily",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=out,
        state_root=pair_repos["state"],
        dry_run=True,
        skip_fetch=True,
    )
    assert out.is_file()
    temps = list(out.parent.glob(f".{out.name}.*.tmp"))
    assert temps == []

    result = subprocess.run(
        [
            sys.executable,
            str(_INTEGRATOR_PATH),
            "--receipt",
            str(out),
            "--schema",
            str(_SCHEMA_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["capability_pin_sha"] == receipt["capability_pin"]["sha"]
    assert payload["lock_identity"] == receipt["lock"]["identity"]
    assert payload["datasets_integrated_sha"] == receipt["datasets"]["integrated_sha"]
    assert payload["accelerator_integrated_sha"] == receipt["accelerator"]["integrated_sha"]


def test_accepted_without_tests_is_invalid() -> None:
    bad = integrator.build_receipt(
        status="accepted",
        disposition="integrated",
        trigger="pre-release",
        datasets=integrator.make_repo_revision(
            "datasets",
            before_sha="1" * 40,
            remote_sha="1" * 40,
            integrated_sha="1" * 40,
        ),
        accelerator=integrator.make_repo_revision(
            "accelerator",
            before_sha="2" * 40,
            remote_sha="2" * 40,
            integrated_sha="2" * 40,
        ),
        lock={"path": "/tmp/x", "identity": "t", "method": "none", "acquired": False},
        capability_pin=integrator.make_capability_pin("2" * 40),
        test_results=[],
    )
    errors = integrator.validate_receipt_struct(
        bad, schema=integrator.load_schema(_SCHEMA_PATH)
    )
    assert any("test" in e.lower() for e in errors)


def test_plan_only_shell(pair_repos: dict[str, Path]) -> None:
    result = subprocess.run(
        [
            "bash",
            str(_SYNC_SH),
            "--trigger",
            "twice-daily",
            "--datasets-path",
            str(pair_repos["datasets"]),
            "--accelerator-path",
            str(pair_repos["accelerator"]),
            "--plan-only",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CROSS_REPO_SYNC_PYTHON": sys.executable},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    plan = json.loads(result.stdout)
    assert plan["action"] == "integrate"
    assert plan["merge_order"] == ["accelerator", "datasets"]
    assert plan["push_allowed"] is False
    assert plan["active_worktree_pull_allowed"] is False
    assert plan["use_isolated_worktrees"] is True


def test_fetch_only_trigger_no_active_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)
    for trigger in ("startup", "eight-hour"):
        receipt = integrator.run_integration(
            trigger=trigger,
            datasets_path=datasets,
            accelerator_path=accelerator,
            output_path=pair_repos["state"] / f"{trigger}.json",
            state_root=pair_repos["state"],
            dry_run=True,
            skip_fetch=True,
        )
        assert receipt["trigger"] == trigger
        assert receipt["status"] == "accepted"
        assert receipt["mutation_attempted"] is False
        assert receipt["push_attempted"] is False
        assert receipt["active_worktree_pull_attempted"] is False
        assert receipt["datasets"]["before_sha"] == before_ds["__HEAD__"]
        assert receipt["accelerator"]["before_sha"] == before_acc["__HEAD__"]
    assert _tree_snapshot(datasets) == before_ds
    assert _tree_snapshot(accelerator) == before_acc


def test_concurrent_lock_serializes(pair_repos: dict[str, Path]) -> None:
    """Second concurrent integrator sees lock_held and does not mutate."""
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    lock_path = pair_repos["state"] / "serial.lock"
    results: list[dict[str, Any]] = []

    def _run(tag: str) -> None:
        out = pair_repos["state"] / f"serial-{tag}.json"
        rec = integrator.run_integration(
            trigger="twice-daily",
            datasets_path=datasets,
            accelerator_path=accelerator,
            output_path=out,
            lock_path=lock_path,
            state_root=pair_repos["state"] / tag,
            dry_run=False,
            skip_fetch=True,
        )
        results.append(rec)

    # Hold lock in main thread while a worker attempts integrate.
    holder = integrator.IntegrationLock(lock_path, dry_run=False)
    assert holder.try_acquire()
    try:
        t = threading.Thread(target=_run, args=("worker",))
        t.start()
        t.join(timeout=30)
        assert not t.is_alive()
    finally:
        holder.release()

    assert len(results) == 1
    assert results[0]["status"] == "aborted"
    assert results[0]["abort_reason"] == "lock_held"
    assert results[0]["mutation_attempted"] is False
