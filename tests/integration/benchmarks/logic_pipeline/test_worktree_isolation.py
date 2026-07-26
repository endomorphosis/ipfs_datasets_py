"""Executable evidence for worktree and state-root isolation.

These tests intentionally use real, disposable Git repositories.  Mocked Git
responses cannot prove that creating a benchmark worktree leaves the operator's
active checkout, branch, index, and uncommitted progress unchanged.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Iterable

import pytest

from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.capabilities import (
    CapabilityContractError,
    HSSLEV0118D14,
    WORKTREE_SAFETY_RECEIPT_NAME,
    WorktreeSafetyReceipt,
    canonical_worktree_safety_json,
    prepare_isolated_worktree,
    worktree_safety_sha256,
)


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
    config: Iterable[str] = (),
) -> subprocess.CompletedProcess[str]:
    """Run Git without consulting a shell or prompting for credentials."""

    command = ["git", "-c", "core.autocrlf=false"]
    for item in config:
        command.extend(("-c", item))
    command.extend(("-C", str(repository), *arguments))
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )


def _init_repository(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.name", "Logic Pipeline Benchmark Tests")
    _git(path, "config", "user.email", "logic-pipeline@example.invalid")


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--no-gpg-sign", "-m", message)
    return _git(repository, "rev-parse", "HEAD").stdout.strip()


def _marker_script(
    path: Path,
    marker: Path,
    *,
    pass_stdin: bool = False,
) -> Path:
    body = [
        "#!/bin/sh",
        f"printf executed > {marker.as_posix()}",
    ]
    if pass_stdin:
        body.append("cat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def disposable_repository(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Return an active checkout with two commits, a submodule, and dirty work."""

    dependency = tmp_path / "dependency"
    _init_repository(dependency)
    (dependency / "identity.txt").write_text(
        "pinned dependency identity\n",
        encoding="utf-8",
    )
    dependency_commit = _commit(dependency, "dependency identity")

    checkout = tmp_path / "active-checkout"
    _init_repository(checkout)
    (checkout / "tracked.txt").write_text("pinned base\n", encoding="utf-8")
    _git(
        checkout,
        "submodule",
        "add",
        str(dependency),
        "vendor/example dependency",
        config=("protocol.file.allow=always",),
    )
    pinned_base = _commit(checkout, "pinned benchmark base")

    # Advance the dependency and active superproject after the pinned base.
    # The receipt must read the old gitlink from ``pinned_base``, not inspect
    # whichever submodule happens to be checked out in the active checkout.
    (dependency / "identity.txt").write_text(
        "newer dependency identity\n",
        encoding="utf-8",
    )
    newer_dependency_commit = _commit(dependency, "advance dependency")
    active_submodule = checkout / "vendor" / "example dependency"
    _git(active_submodule, "fetch", "origin")
    _git(active_submodule, "checkout", "--detach", newer_dependency_commit)
    (checkout / "tracked.txt").write_text("active head\n", encoding="utf-8")
    active_head = _commit(checkout, "advance active checkout")

    # This is operator progress that the isolation boundary must preserve.
    (checkout / "tracked.txt").write_text(
        "active head\nuncommitted operator edit\n",
        encoding="utf-8",
    )
    (checkout / "operator-notes.txt").write_text(
        "untracked operator progress\n",
        encoding="utf-8",
    )
    return checkout, pinned_base, active_head, dependency_commit


def _active_checkout_snapshot(checkout: Path) -> dict[str, object]:
    """Capture the active state that worktree preparation must not mutate."""

    return {
        "head": _git(checkout, "rev-parse", "HEAD").stdout,
        "branch": _git(checkout, "symbolic-ref", "HEAD").stdout,
        "status": _git(
            checkout, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout,
        "tracked": (checkout / "tracked.txt").read_bytes(),
        "untracked": (checkout / "operator-notes.txt").read_bytes(),
        "merge_head": _git(
            checkout, "rev-parse", "--verify", "MERGE_HEAD", check=False
        ).returncode,
    }


def _prepare(
    checkout: Path,
    paths: RunPaths,
    revision: str,
) -> WorktreeSafetyReceipt:
    return prepare_isolated_worktree(
        checkout,
        run_paths=paths,
        base_revision=revision,
    )


def test_pinned_detached_worktree_preserves_dirty_active_checkout(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, active_head, _ = disposable_repository
    paths = RunPaths.for_run(
        "isolation-001",
        benchmark_root=tmp_path / "benchmark-state",
    )
    before = _active_checkout_snapshot(checkout)

    receipt = _prepare(checkout, paths, pinned_base)

    assert isinstance(receipt, WorktreeSafetyReceipt)
    assert receipt.base_commit == pinned_base
    assert receipt.source_checkout == checkout.resolve()
    assert receipt.worktree_root == (paths.worktrees / "source").resolve()
    assert receipt.state_root == paths.run_root.resolve()
    assert receipt.detached is True
    assert receipt.auto_merge is False
    assert _git(receipt.worktree_root, "rev-parse", "HEAD").stdout.strip() == pinned_base
    assert (
        _git(
            receipt.worktree_root,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        ).returncode
        != 0
    )
    assert (receipt.worktree_root / "tracked.txt").read_text(
        encoding="utf-8"
    ) == "pinned base\n"
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == active_head
    assert _active_checkout_snapshot(checkout) == before


def test_worktree_checkout_uses_safe_child_umask_without_mutating_caller(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, _active_head, _ = disposable_repository
    paths = RunPaths.for_run(
        "secure-checkout-modes",
        benchmark_root=tmp_path / "benchmark-state",
    )
    original_umask = os.umask(0o002)
    try:
        receipt = _prepare(checkout, paths, pinned_base)
        observed_umask = os.umask(0o002)
        assert observed_umask == 0o002
        tracked_paths = tuple(
            value
            for value in _git(
                receipt.worktree_root,
                "ls-files",
                "-z",
            ).stdout.split("\0")
            if value
        )
        regular_modes = []
        for relative in tracked_paths:
            metadata = (receipt.worktree_root / relative).lstat()
            if stat.S_ISREG(metadata.st_mode):
                regular_modes.append(stat.S_IMODE(metadata.st_mode))
        assert regular_modes
        assert all(mode & 0o022 == 0 for mode in regular_modes)
    finally:
        os.umask(original_umask)


def test_worktree_checkout_disables_post_checkout_hook(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, _active_head, _ = disposable_repository
    marker = tmp_path / "post-checkout-marker"
    _marker_script(
        checkout / ".git" / "hooks" / "post-checkout",
        marker,
    )

    receipt = _prepare(
        checkout,
        RunPaths.for_run(
            "hook-safe-checkout",
            benchmark_root=tmp_path / "benchmark-state",
        ),
        pinned_base,
    )

    assert receipt.worktree_commit == pinned_base
    assert not marker.exists()


def test_worktree_prevalidation_disables_fsmonitor(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, _active_head, _ = disposable_repository
    marker = tmp_path / "fsmonitor-marker"
    monitor = _marker_script(
        tmp_path / "malicious-fsmonitor",
        marker,
    )
    _git(checkout, "config", "core.fsmonitor", monitor.as_posix())

    receipt = _prepare(
        checkout,
        RunPaths.for_run(
            "fsmonitor-safe-checkout",
            benchmark_root=tmp_path / "benchmark-state",
        ),
        pinned_base,
    )

    assert receipt.worktree_commit == pinned_base
    assert not marker.exists()


def test_worktree_prevalidation_ignores_caller_path_git_wrapper(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, pinned_base, _active_head, _ = disposable_repository
    marker = tmp_path / "path-wrapper-marker"
    wrapper = _marker_script(
        tmp_path / "malicious-bin" / "git",
        marker,
    )
    wrapper.write_text(
        wrapper.read_text(encoding="utf-8")
        + f"exec {shutil.which('git', path=os.defpath)} \"$@\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PATH",
        f"{wrapper.parent.as_posix()}:{os.defpath}",
    )

    receipt = _prepare(
        checkout,
        RunPaths.for_run(
            "path-safe-checkout",
            benchmark_root=tmp_path / "benchmark-state",
        ),
        pinned_base,
    )

    assert receipt.worktree_commit == pinned_base
    assert not marker.exists()


def test_worktree_prevalidation_ignores_inherited_git_overrides(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, pinned_base, _active_head, _ = disposable_repository
    marker = tmp_path / "inherited-config-marker"
    hooks = tmp_path / "inherited-hooks"
    _marker_script(hooks / "post-checkout", marker)
    foreign = tmp_path / "foreign"
    _init_repository(foreign)
    monkeypatch.setenv("GIT_DIR", (foreign / ".git").as_posix())
    monkeypatch.setenv("GIT_WORK_TREE", foreign.as_posix())
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", hooks.as_posix())
    monkeypatch.setenv(
        "GIT_CONFIG_PARAMETERS",
        f"'core.hooksPath'='{hooks.as_posix()}'",
    )

    receipt = _prepare(
        checkout,
        RunPaths.for_run(
            "environment-safe-checkout",
            benchmark_root=tmp_path / "benchmark-state",
        ),
        pinned_base,
    )

    assert receipt.worktree_commit == pinned_base
    assert not marker.exists()


@pytest.mark.parametrize("attribute_location", ("tracked", "info"))
@pytest.mark.parametrize("driver_kind", ("clean", "smudge", "process"))
def test_worktree_checkout_rejects_effective_filters_before_execution(
    tmp_path: Path,
    attribute_location: str,
    driver_kind: str,
) -> None:
    checkout = tmp_path / "filter-checkout"
    _init_repository(checkout)
    (checkout / "source.txt").write_text(
        "pinned unfiltered bytes\n",
        encoding="utf-8",
    )
    if attribute_location == "tracked":
        (checkout / ".gitattributes").write_text(
            "*.txt filter=adversarial\n",
            encoding="utf-8",
        )
    commit = _commit(checkout, "filtered source identity")
    if attribute_location == "info":
        attributes = checkout / ".git" / "info" / "attributes"
        attributes.write_text(
            "*.txt filter=adversarial\n",
            encoding="utf-8",
        )
    marker = tmp_path / f"{attribute_location}-{driver_kind}-marker"
    driver = _marker_script(
        tmp_path / f"malicious-{driver_kind}",
        marker,
        pass_stdin=driver_kind in {"clean", "smudge"},
    )
    _git(
        checkout,
        "config",
        f"filter.adversarial.{driver_kind}",
        driver.as_posix(),
    )
    _git(checkout, "config", "filter.adversarial.required", "true")
    paths = RunPaths.for_run(
        f"reject-{attribute_location}-{driver_kind}",
        benchmark_root=tmp_path / "benchmark-state",
    )

    with pytest.raises(
        CapabilityContractError,
        match="checkout filters",
    ):
        _prepare(checkout, paths, commit)

    assert not marker.exists()
    assert not paths.run_root.exists()


def test_isolated_commit_does_not_merge_or_advance_active_branch(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, active_head, _ = disposable_repository
    paths = RunPaths.for_run(
        "no-merge-001",
        benchmark_root=tmp_path / "benchmark-state",
    )
    receipt = _prepare(checkout, paths, pinned_base)
    active_branch_before = _git(checkout, "rev-parse", "refs/heads/main").stdout
    active_before = _active_checkout_snapshot(checkout)

    (receipt.worktree_root / "benchmark-only.txt").write_text(
        "isolated result\n",
        encoding="utf-8",
    )
    isolated_commit = _commit(receipt.worktree_root, "isolated benchmark result")

    assert isolated_commit not in {pinned_base, active_head}
    assert _git(checkout, "rev-parse", "refs/heads/main").stdout == active_branch_before
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == active_head
    assert (
        _git(
            receipt.worktree_root,
            "rev-parse",
            "--verify",
            "MERGE_HEAD",
            check=False,
        ).returncode
        != 0
    )
    assert not (checkout / "benchmark-only.txt").exists()
    assert _active_checkout_snapshot(checkout) == active_before


def test_run_specific_state_roots_and_worktrees_are_disjoint(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, active_head, _ = disposable_repository
    benchmark_root = tmp_path / "benchmark-state"
    first_paths = RunPaths.for_run("run-one", benchmark_root=benchmark_root)
    second_paths = RunPaths.for_run("run-two", benchmark_root=benchmark_root)

    first = _prepare(checkout, first_paths, pinned_base)
    second = _prepare(checkout, second_paths, active_head)

    assert first.state_root != second.state_root
    assert first.worktree_root != second.worktree_root
    assert first.worktree_root.is_relative_to(first.state_root)
    assert second.worktree_root.is_relative_to(second.state_root)
    assert set(first_paths.directories()).isdisjoint(second_paths.directories())
    assert all(path.is_dir() for path in first_paths.directories())
    assert all(path.is_dir() for path in second_paths.directories())
    assert not first.state_root.is_relative_to(checkout.resolve())
    assert not checkout.resolve().is_relative_to(first.state_root)
    assert _git(first.worktree_root, "rev-parse", "HEAD").stdout.strip() == pinned_base
    assert _git(second.worktree_root, "rev-parse", "HEAD").stdout.strip() == active_head


@pytest.mark.parametrize("run_id", ("..", "../escape", "/absolute", "nested/run"))
def test_traversal_run_ids_are_rejected_before_git_is_invoked(
    run_id: str,
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, _, active_head, _ = disposable_repository
    before = _active_checkout_snapshot(checkout)

    with pytest.raises(ValueError, match="run_id"):
        paths = RunPaths.for_run(run_id, benchmark_root=tmp_path / "state")
        _prepare(checkout, paths, active_head)

    assert _active_checkout_snapshot(checkout) == before


@pytest.mark.parametrize("location", ("inside", "same"))
def test_state_root_overlapping_active_checkout_is_rejected_without_mutation(
    location: str,
    disposable_repository: tuple[Path, str, str, str],
) -> None:
    checkout, _, active_head, _ = disposable_repository
    if location == "inside":
        paths = RunPaths.for_run(
            "benchmark-run",
            benchmark_root=checkout / ".benchmark-state",
        )
    else:
        paths = RunPaths.for_run(
            checkout.name,
            benchmark_root=checkout.parent,
        )
        assert paths.run_root == checkout
    before = _active_checkout_snapshot(checkout)

    with pytest.raises(ValueError, match="overlap|checkout|state.root"):
        _prepare(checkout, paths, active_head)

    assert _active_checkout_snapshot(checkout) == before
    if location == "inside":
        assert not paths.run_root.exists()


def test_symlinked_worktree_target_cannot_escape_into_active_checkout(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, _, active_head, _ = disposable_repository
    paths = RunPaths.for_run(
        "symlink-escape",
        benchmark_root=tmp_path / "benchmark-state",
    )
    paths.run_root.mkdir(parents=True)
    paths.worktrees.symlink_to(checkout, target_is_directory=True)
    before = _active_checkout_snapshot(checkout)

    with pytest.raises(ValueError, match="overlap|checkout|worktree|state.root"):
        _prepare(checkout, paths, active_head)

    assert _active_checkout_snapshot(checkout) == before
    assert not (checkout / "source").exists()


def test_existing_worktree_target_is_never_cleaned_reset_or_overwritten(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, _, active_head, _ = disposable_repository
    paths = RunPaths.for_run(
        "existing-target",
        benchmark_root=tmp_path / "benchmark-state",
    )
    target = paths.worktrees / "source"
    target.mkdir(parents=True)
    sentinel = target / "operator-owned.txt"
    sentinel.write_text("preserve me\n", encoding="utf-8")
    before = _active_checkout_snapshot(checkout)

    with pytest.raises(FileExistsError, match="exist|worktree|target"):
        _prepare(checkout, paths, active_head)

    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"
    assert _active_checkout_snapshot(checkout) == before


@pytest.mark.parametrize("revision", ("missing-ref", "--help", "HEAD^{blob}"))
def test_invalid_base_revision_fails_before_state_creation(
    revision: str,
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, _, _, _ = disposable_repository
    paths = RunPaths.for_run(
        "invalid-base",
        benchmark_root=tmp_path / "benchmark-state",
    )
    before = _active_checkout_snapshot(checkout)

    with pytest.raises(ValueError, match="Git|revision|commit"):
        _prepare(checkout, paths, revision)

    assert not paths.run_root.exists()
    assert _active_checkout_snapshot(checkout) == before


def test_receipt_captures_pinned_submodule_gitlink_and_is_json_ready(
    disposable_repository: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    checkout, pinned_base, _, dependency_commit = disposable_repository
    paths = RunPaths.for_run(
        "receipt-001",
        benchmark_root=tmp_path / "benchmark-state",
    )

    receipt = _prepare(checkout, paths, pinned_base)
    payload = receipt.to_dict()
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert receipt.submodule_commits == {
        "vendor/example dependency": dependency_commit
    }
    assert payload["submodule_commits"] == {
        "vendor/example dependency": dependency_commit
    }
    assert payload["base_commit"] == pinned_base
    assert payload["detached"] is True
    assert payload["auto_merge"] is False
    assert json.loads(encoded) == payload
    assert str(paths.run_root.resolve()) in encoded
    receipt_path = paths.receipts / WORKTREE_SAFETY_RECEIPT_NAME
    assert receipt_path.read_text(encoding="utf-8") == (
        canonical_worktree_safety_json(receipt) + "\n"
    )
    restored = WorktreeSafetyReceipt.from_dict(
        json.loads(receipt_path.read_text(encoding="utf-8"))
    )
    assert restored == receipt
    assert worktree_safety_sha256(restored) == receipt.sha256
    with pytest.raises(FrozenInstanceError):
        receipt.base_commit = "0" * 40  # type: ignore[misc]


def test_objective_evidence_symbol_is_bound_to_isolation_contract() -> None:
    evidence = HSSLEV0118D14()

    assert evidence
    assert "worktree" in evidence.lower()
    assert "state" in evidence.lower()
