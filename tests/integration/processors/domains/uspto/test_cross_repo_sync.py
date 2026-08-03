"""Integration tests for serialized datasets/accelerator upstream sync (PATLAW-080).

Acceptance:

* dirty or active work aborts without mutation;
* conflicts fail closed;
* no recursive mutual-submodule chase;
* accepted manifest binds both SHAs and test receipts;
* startup, eight-hour, twice-daily, pre-release, and security-fix triggers
  are explicit;
* no push occurs.

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
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths / module load
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]
_CHECKER_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "check_cross_repo_compatibility.py"
_SYNC_SH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "sync_upstreams.sh"
_SCHEMA_PATH = (
    _REPO_ROOT
    / "data"
    / "release"
    / "uspto_submission_assurance"
    / "compatibility_manifest.schema.json"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "uspto_check_cross_repo_compatibility", _CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


checker = _load_checker()


# ---------------------------------------------------------------------------
# Synthetic git helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd_env = os.environ.copy()
    # Isolate from user/global git config noise.
    cmd_env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    cmd_env.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    cmd_env.setdefault("GIT_AUTHOR_NAME", "patlaw-080-test")
    cmd_env.setdefault("GIT_AUTHOR_EMAIL", "patlaw-080@example.test")
    cmd_env.setdefault("GIT_COMMITTER_NAME", "patlaw-080-test")
    cmd_env.setdefault("GIT_COMMITTER_EMAIL", "patlaw-080@example.test")
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
    _git(path, "config", "user.email", "patlaw-080@example.test")
    _git(path, "config", "user.name", "patlaw-080-test")
    # Avoid default branch ambiguity across git versions.
    _git(path, "checkout", "-B", "main", check=False)
    (path / initial_file).write_text(content, encoding="utf-8")
    _git(path, "add", initial_file)
    _git(path, "commit", "-m", "seed")
    sha = _git(path, "rev-parse", "HEAD").stdout.strip().lower()
    assert len(sha) == 40
    return sha


def _add_submodule_gitlink_stub(parent: Path, name: str, url: str) -> None:
    """Register a submodule in .gitmodules without recursive materialization.

    Uses a file-level .gitmodules entry so mutual registration can be detected
    without performing ``git submodule add`` (which may require network).
    """
    gitmodules = parent / ".gitmodules"
    block = textwrap.dedent(
        f"""
        [submodule "{name}"]
        \tpath = {name}
        \turl = {url}
        """
    ).lstrip()
    existing = gitmodules.read_text(encoding="utf-8") if gitmodules.exists() else ""
    gitmodules.write_text(existing + block, encoding="utf-8")
    _git(parent, "add", ".gitmodules")
    _git(parent, "commit", "-m", f"register submodule {name}")


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
    # Also capture HEAD as a synthetic key.
    if (repo / ".git").exists() or (repo / ".git").is_file():
        snap["__HEAD__"] = _head_sha(repo)
    return snap


@pytest.fixture()
def pair_repos(tmp_path: Path) -> dict[str, Path]:
    """Create a clean datasets + accelerator pair of synthetic git repos."""
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


# ---------------------------------------------------------------------------
# Schema / offline / trigger surface
# ---------------------------------------------------------------------------


def test_schema_file_exists_and_names_all_triggers() -> None:
    assert _SCHEMA_PATH.is_file()
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    dumped = json.dumps(schema)
    for trigger in checker.TRIGGERS:
        assert trigger in dumped
    assert schema["properties"]["push_attempted"]["const"] is False
    assert schema["properties"]["recursive_submodule_chase"]["const"] is False


def test_offline_self_check_passes() -> None:
    report = checker.offline_self_check(_SCHEMA_PATH)
    assert report["ok"] is True
    names = {c["name"] for c in report["checks"]}
    assert "all_triggers_explicit" in names
    assert "push_forbidden" in names
    assert "recursive_forbidden" in names
    assert report["triggers"] == list(checker.TRIGGERS)


def test_cli_offline_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(_CHECKER_PATH), "--offline"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert set(payload["triggers"]) == set(checker.TRIGGERS)


def test_explicit_triggers_partition() -> None:
    assert set(checker.TRIGGERS) == checker.FETCH_ONLY_TRIGGERS | checker.INTEGRATION_TRIGGERS
    assert checker.FETCH_ONLY_TRIGGERS.isdisjoint(checker.INTEGRATION_TRIGGERS)
    assert list(checker.TRIGGERS) == [
        "startup",
        "eight-hour",
        "twice-daily",
        "pre-release",
        "security-fix",
    ]


def test_sync_script_lists_triggers() -> None:
    assert _SYNC_SH.is_file()
    # Ensure executable bit is present for operators (tests may still invoke via bash).
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
    assert payload["recursive_submodules"] is False
    assert set(payload["triggers"]) == set(checker.TRIGGERS)
    assert set(payload["fetch_only_triggers"]) == checker.FETCH_ONLY_TRIGGERS
    assert set(payload["integration_triggers"]) == checker.INTEGRATION_TRIGGERS


# ---------------------------------------------------------------------------
# Dirty / active abort without mutation
# ---------------------------------------------------------------------------


def test_dirty_worktree_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)

    (datasets / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    manifest = checker.run_sync(
        trigger="twice-daily",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "manifest.json",
        dry_run=True,
        skip_fetch=True,
    )
    assert manifest["status"] == "aborted"
    assert manifest["abort_reason"] == "dirty_worktree"
    assert manifest["mutation_attempted"] is False
    assert manifest["push_attempted"] is False
    assert manifest["recursive_submodule_chase"] is False

    after_ds = _tree_snapshot(datasets)
    after_acc = _tree_snapshot(accelerator)
    # Only the intentional dirty file may differ on datasets; HEAD unchanged.
    assert after_ds["__HEAD__"] == before_ds["__HEAD__"]
    assert after_acc == before_acc
    assert after_ds["__HEAD__"] == before_ds["__HEAD__"]


def test_active_work_aborts_without_mutation(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    marker = pair_repos["root"] / "ACTIVE_LANE"
    marker.write_text("lane-busy\n", encoding="utf-8")
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)

    manifest = checker.run_sync(
        trigger="pre-release",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "active.json",
        dry_run=True,
        skip_fetch=True,
        active_marker=str(marker),
    )
    assert manifest["status"] == "aborted"
    assert manifest["abort_reason"] == "active_work"
    assert manifest["mutation_attempted"] is False
    assert _tree_snapshot(datasets) == before_ds
    assert _tree_snapshot(accelerator) == before_acc


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
# Conflicts fail closed
# ---------------------------------------------------------------------------


def test_merge_conflict_fails_closed(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]

    # Create a conflicted index on datasets without completing the merge.
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
    assert checker.git_has_unmerged(datasets)

    before_head = _head_sha(accelerator)
    plan = checker.plan_sync(
        trigger="security-fix",
        datasets_path=datasets,
        accelerator_path=accelerator,
    )
    assert plan["action"] == "abort"
    assert plan["abort_reason"] == "merge_conflict"
    assert plan["mutation_permitted"] is False
    assert plan["conflict"]["kind"] == "merge_conflict"

    manifest = checker.run_sync(
        trigger="security-fix",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "conflict.json",
        dry_run=True,
        skip_fetch=True,
    )
    assert manifest["status"] == "aborted"
    assert manifest["mutation_attempted"] is False
    assert _head_sha(accelerator) == before_head


# ---------------------------------------------------------------------------
# No recursive mutual-submodule chase
# ---------------------------------------------------------------------------


def test_mutual_submodule_registration_does_not_recurse(
    pair_repos: dict[str, Path],
) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]

    _add_submodule_gitlink_stub(
        datasets, "ipfs_accelerate_py", str(accelerator)
    )
    _add_submodule_gitlink_stub(
        accelerator, "ipfs_datasets_py", str(datasets)
    )
    risk = checker.detect_submodule_cycle_risk(datasets, accelerator)
    assert risk is not None
    assert "mutual" in risk.lower() or "recursive" in risk.lower()

    # Policy helpers must refuse recursive flags.
    with pytest.raises(checker.CompatibilityError):
        checker.forbid_recursive_submodule_args(
            ["submodule", "update", "--init", "--recursive"]
        )
    with pytest.raises(checker.CompatibilityError):
        checker._run_git(datasets, "submodule", "update", "--recursive", check=False)

    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)
    manifest = checker.run_sync(
        trigger="twice-daily",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=pair_repos["state"] / "cycle.json",
        dry_run=True,
        skip_fetch=True,
    )
    assert manifest["recursive_submodule_chase"] is False
    assert manifest["push_attempted"] is False
    # Dry-run integration should accept when SHAs bind + synthetic tests pass.
    assert manifest["status"] == "accepted"
    # No nested submodule checkout materialization.
    assert not (datasets / "ipfs_accelerate_py" / ".git").exists()
    assert not (accelerator / "ipfs_datasets_py" / ".git").exists()
    # HEADs unchanged (no recursive update mutation).
    assert _tree_snapshot(datasets)["__HEAD__"] == before_ds["__HEAD__"]
    assert _tree_snapshot(accelerator)["__HEAD__"] == before_acc["__HEAD__"]


def test_git_helper_refuses_push(pair_repos: dict[str, Path]) -> None:
    with pytest.raises(checker.CompatibilityError, match="push"):
        checker._run_git(pair_repos["datasets"], "push", "origin", "HEAD", check=False)


# ---------------------------------------------------------------------------
# Accepted manifest binds both SHAs and test receipts
# ---------------------------------------------------------------------------


def test_accepted_manifest_binds_sha_pair_and_receipts(
    pair_repos: dict[str, Path],
) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    ds_sha = _head_sha(datasets)
    acc_sha = _head_sha(accelerator)
    out = pair_repos["state"] / "accepted.json"

    for trigger in ("twice-daily", "pre-release", "security-fix"):
        manifest = checker.run_sync(
            trigger=trigger,
            datasets_path=datasets,
            accelerator_path=accelerator,
            output_path=out,
            dry_run=True,
            skip_fetch=True,
        )
        assert manifest["status"] == "accepted", manifest
        assert manifest["trigger"] == trigger
        assert manifest["datasets"]["sha"] == ds_sha
        assert manifest["accelerator"]["sha"] == acc_sha
        assert manifest["test_receipts"], "accepted requires test receipts"
        for receipt in manifest["test_receipts"]:
            assert receipt["status"] == "passed"
            assert receipt["exit_code"] == 0
            assert receipt.get("datasets_sha") in {None, ds_sha}
            assert receipt.get("accelerator_sha") in {None, acc_sha}
        assert manifest["push_attempted"] is False
        assert manifest["recursive_submodule_chase"] is False
        assert manifest["policy"]["push_allowed"] is False
        assert manifest["policy"]["recursive_submodules"] is False
        checker.assert_manifest_valid(manifest, schema=checker.load_schema(_SCHEMA_PATH))
        # On-disk atomic write matches.
        disk = json.loads(out.read_text(encoding="utf-8"))
        assert disk["manifest_id"] == manifest["manifest_id"]
        assert disk["datasets"]["sha"] == ds_sha
        assert disk["accelerator"]["sha"] == acc_sha


def test_fetch_only_triggers_bind_shas_without_mutation(
    pair_repos: dict[str, Path],
) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    before_ds = _tree_snapshot(datasets)
    before_acc = _tree_snapshot(accelerator)
    for trigger in ("startup", "eight-hour"):
        manifest = checker.run_sync(
            trigger=trigger,
            datasets_path=datasets,
            accelerator_path=accelerator,
            output_path=pair_repos["state"] / f"{trigger}.json",
            dry_run=True,
            skip_fetch=True,
        )
        assert manifest["trigger"] == trigger
        assert manifest["status"] == "accepted"
        assert manifest["datasets"]["sha"] == before_ds["__HEAD__"]
        assert manifest["accelerator"]["sha"] == before_acc["__HEAD__"]
        assert manifest["mutation_attempted"] is False
        assert manifest["push_attempted"] is False
    assert _tree_snapshot(datasets) == before_ds
    assert _tree_snapshot(accelerator) == before_acc


def test_shell_integration_writes_accepted_manifest(
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
    assert body["datasets"]["sha"] == _head_sha(datasets)
    assert body["accelerator"]["sha"] == _head_sha(accelerator)
    assert body["test_receipts"]
    assert body["push_attempted"] is False
    assert "push_allowed=false" in result.stderr
    assert "recursive_submodules=false" in result.stderr


# ---------------------------------------------------------------------------
# Atomic write + validate path
# ---------------------------------------------------------------------------


def test_atomic_write_and_cli_validate(pair_repos: dict[str, Path]) -> None:
    datasets = pair_repos["datasets"]
    accelerator = pair_repos["accelerator"]
    out = pair_repos["state"] / "validate-me.json"
    manifest = checker.run_sync(
        trigger="startup",
        datasets_path=datasets,
        accelerator_path=accelerator,
        output_path=out,
        dry_run=True,
        skip_fetch=True,
    )
    assert out.is_file()
    # No leftover temp siblings.
    temps = list(out.parent.glob(f".{out.name}.*.tmp"))
    assert temps == []

    result = subprocess.run(
        [sys.executable, str(_CHECKER_PATH), "--manifest", str(out), "--schema", str(_SCHEMA_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["datasets_sha"] == manifest["datasets"]["sha"]
    assert payload["accelerator_sha"] == manifest["accelerator"]["sha"]


def test_accepted_without_receipts_is_invalid() -> None:
    bad = checker.build_manifest(
        status="accepted",
        trigger="pre-release",
        datasets=checker.make_repo_pin("datasets", sha="1" * 40),
        accelerator=checker.make_repo_pin("accelerator", sha="2" * 40),
        test_receipts=[],
    )
    errors = checker.validate_manifest_struct(bad, schema=checker.load_schema(_SCHEMA_PATH))
    assert any("receipt" in e.lower() for e in errors)


def test_no_push_policy_in_script_source() -> None:
    text = _SYNC_SH.read_text(encoding="utf-8")
    assert "NO PUSH" in text or "never push" in text.lower() or "No push" in text
    assert "git push is forbidden" in text
    assert "recursive submodule chase is forbidden" in text
    for trigger in checker.TRIGGERS:
        assert trigger in text


def test_plan_only_shell(pair_repos: dict[str, Path]) -> None:
    result = subprocess.run(
        [
            "bash",
            str(_SYNC_SH),
            "--trigger",
            "eight-hour",
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
    assert plan["action"] == "fetch"
    assert plan["push_allowed"] is False
    assert plan["recursive_submodules"] is False
