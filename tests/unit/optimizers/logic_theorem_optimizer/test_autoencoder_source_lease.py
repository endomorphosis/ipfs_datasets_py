"""Actual process locks keep readers stable without discarding editor changes."""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as leases


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments],
                                   stderr=subprocess.PIPE, text=True).strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "base")
    return root


def _hold(root, mode, pipe):
    try:
        with leases.source_lease(root, mode=mode, timeout_seconds=2.0) as lease:
            pipe.send(("acquired", lease.to_dict()))
            pipe.recv()
        pipe.send(("released", None))
    except BaseException as exc:
        pipe.send(("error", type(exc).__name__, str(exc)))
    finally:
        pipe.close()


@pytest.fixture
def holders():
    children = []

    def start(root, mode):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_hold, args=(str(root), mode, child))
        process.start()
        child.close()
        children.append((process, parent))
        return process, parent

    yield start
    for process, pipe in children:
        if process.is_alive():
            process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        pipe.close()


def received(pipe):
    assert pipe.poll(5), "child did not report lock acquisition"
    message = pipe.recv()
    assert message[0] == "acquired", message
    return message[1]


def release(process, pipe):
    pipe.send("release")
    assert pipe.poll(5)
    assert pipe.recv()[0] == "released"
    process.join(5)
    assert process.exitcode == 0


def test_two_process_readers_overlap_and_exclude_writer(repository, holders):
    first, a = holders(repository, "read")
    receipt = received(a)
    second, b = holders(repository, "read")
    received(b)
    assert receipt["canonical_root"] == str(repository)
    assert receipt["cooperative"] is True
    before = time.monotonic()
    with pytest.raises(leases.SourceLeaseTimeout):
        with leases.source_lease(repository, mode="write", timeout_seconds=0.12):
            pytest.fail("writer entered while readers held leases")
    assert time.monotonic() - before < 1.5
    release(first, a)
    with pytest.raises(leases.SourceLeaseTimeout):
        with leases.source_lease(repository, mode="write", timeout_seconds=0):
            pytest.fail("second reader did not retain its lease")
    release(second, b)
    with leases.source_lease(repository, mode="write", timeout_seconds=0):
        pass


def test_waiting_writer_blocks_new_readers_then_runs(repository, holders):
    first, a = holders(repository, "read")
    received(a)
    writer, w = holders(repository, "write")
    # Observe the writer's actual turnstile lock instead of assuming a sleep
    # is sufficient for process startup. This probe never takes the source lock.
    import fcntl
    admission = repository / leases.CONTROL_DIRECTORY / "admission.lock"
    deadline = time.monotonic() + 5
    with admission.open("rb") as probe:
        while True:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
    with pytest.raises(leases.SourceLeaseTimeout, match="admission"):
        with leases.source_lease(repository, timeout_seconds=0.08):
            pytest.fail("new reader bypassed the waiting writer")
    assert not w.poll(0.02)
    release(first, a)
    received(w)
    with pytest.raises(leases.SourceLeaseTimeout):
        with leases.source_lease(repository, timeout_seconds=0.05):
            pytest.fail("reader entered while writer held lease")
    release(writer, w)


@pytest.mark.parametrize("mode", ["read", "write"])
def test_crashed_holder_releases_kernel_lock_without_deleting_files(repository, holders, mode):
    child, pipe = holders(repository, mode)
    received(pipe)
    lock = repository / leases.CONTROL_DIRECTORY / "source.lock"
    identity = (lock.stat().st_dev, lock.stat().st_ino)
    os.kill(child.pid, signal.SIGKILL)
    child.join(5)
    assert child.exitcode == -signal.SIGKILL
    with leases.source_lease(repository, mode="write", timeout_seconds=0.3):
        assert (lock.stat().st_dev, lock.stat().st_ino) == identity


def test_linked_worktree_resolves_same_control_directory(repository, tmp_path, holders):
    lane = tmp_path / "lane"
    git(repository, "worktree", "add", "--detach", str(lane), "HEAD")
    assert leases.canonical_source_root(lane) == repository
    child, pipe = holders(repository, "read")
    received(pipe)
    with pytest.raises(leases.SourceLeaseTimeout):
        with leases.source_lease(lane, mode="write", timeout_seconds=0.05):
            pytest.fail("lane acquired a different writer lock")
    assert not (lane / leases.CONTROL_DIRECTORY).exists()
    release(child, pipe)


def test_submodule_style_gitdir_resolves_primary_checkout(repository, tmp_path):
    common = tmp_path / "module-git-dir"
    (repository / ".git").rename(common)
    (repository / ".git").write_text("gitdir: " + str(common) + "\n")
    git(repository, "config", "core.worktree", os.path.relpath(repository, common))
    lane = tmp_path / "submodule-lane"
    git(repository, "worktree", "add", "--detach", str(lane), "HEAD")
    assert leases.canonical_source_root(repository) == repository
    assert leases.canonical_source_root(lane) == repository


def test_submodule_primary_worktree_config_is_used_instead_of_lane_override(repository, tmp_path):
    common = tmp_path / "module-git-dir"
    (repository / ".git").rename(common)
    (repository / ".git").write_text("gitdir: " + str(common) + "\n")
    git(repository, "config", "extensions.worktreeConfig", "true")
    primary_config = common / "config.worktree"
    git(repository, "config", "--file", str(primary_config), "core.worktree",
        os.path.relpath(repository, common))
    git(repository, "config", "--file", str(primary_config), "core.bare", "false")
    git(repository, "config", "--local", "--unset", "core.bare")
    assert git(repository, "config", "--local", "--default", "", "--get", "core.worktree") == ""
    lane = tmp_path / "submodule-config-lane"
    git(repository, "worktree", "add", "--detach", str(lane), "HEAD")
    git(lane, "config", "--worktree", "core.worktree", str(lane))
    assert git(lane, "config", "--get", "core.worktree") == str(lane)
    assert leases.canonical_source_root(repository) == repository
    assert leases.canonical_source_root(lane) == repository
    with leases.source_lease(repository, mode="write", timeout_seconds=0):
        with pytest.raises(leases.SourceLeaseTimeout):
            with leases.source_lease(lane, timeout_seconds=0):
                pytest.fail("linked worktree escaped the canonical lease")


def test_primary_worktree_config_alias_is_rejected(repository, tmp_path):
    git(repository, "config", "extensions.worktreeConfig", "true")
    alias_target = tmp_path / "aliased-config"
    alias_target.write_text("[core]\nworktree = " + str(repository) + "\n")
    (repository / ".git/config.worktree").symlink_to(alias_target)
    with pytest.raises(leases.SourceLeaseError, match="configuration is aliased"):
        leases.canonical_source_root(repository)


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "hardlink", "fifo", "root_symlink"])
def test_aliases_and_special_lock_files_are_rejected(repository, tmp_path, kind):
    if kind == "root_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(repository, target_is_directory=True)
        with pytest.raises(leases.SourceLeaseError):
            with leases.source_lease(alias):
                pass
        return
    control = repository / leases.CONTROL_DIRECTORY
    control.mkdir(parents=True)
    lock = control / "source.lock"
    other = tmp_path / "other"
    if kind == "parent_symlink":
        control.rmdir()
        other.mkdir()
        control.symlink_to(other, target_is_directory=True)
    elif kind == "file_symlink":
        other.write_text("untouched")
        lock.symlink_to(other)
    elif kind == "hardlink":
        other.write_text("untouched")
        os.link(other, lock)
    else:
        os.mkfifo(lock)
    with pytest.raises(leases.SourceLeaseError):
        with leases.source_lease(repository, timeout_seconds=0):
            pass
    if kind in {"file_symlink", "hardlink"}:
        assert other.read_text() == "untouched"


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan"), True, None, "3"])
def test_timeout_is_explicit_finite_nonnegative(repository, timeout):
    with pytest.raises(leases.SourceLeaseError, match="timeout"):
        with leases.source_lease(repository, timeout_seconds=timeout):
            pass


def test_unknown_mode_is_rejected(repository):
    with pytest.raises(leases.SourceLeaseError, match="mode"):
        with leases.source_lease(repository, mode="repair"):
            pass


def test_lock_replacement_during_operation_fails_closed(repository):
    with pytest.raises(leases.SourceLeaseError, match="unaliased"):
        with leases.source_lease(repository) as receipt:
            path = Path(receipt.lock_path)
            path.rename(path.with_suffix(".old"))
            path.touch()


def test_lock_directory_replacement_during_operation_fails_closed(repository):
    with pytest.raises(leases.SourceLeaseError, match="directory identity changed"):
        with leases.source_lease(repository) as receipt:
            path = Path(receipt.lock_path).parent
            path.rename(path.with_name("retained-old-locks"))
            path.mkdir()


def test_missing_repository_is_not_recreated_for_control_files(repository, monkeypatch):
    monkeypatch.setattr(leases, "canonical_source_root", lambda root: repository / "gone")
    with pytest.raises(leases.SourceLeaseError, match="directory"):
        with leases.source_lease(repository):
            pass
    assert not (repository / "gone").exists()


def test_source_files_and_git_index_are_not_modified(repository):
    source = repository / "local.py"
    source.write_text("preserved = True\n")
    before = git(repository, "status", "--porcelain")
    with leases.source_lease(repository):
        pass
    assert source.read_text() == "preserved = True\n"
    assert (repository / "workspace/control-plane/source-leases/source.lock").read_bytes() == b""
    assert before in git(repository, "status", "--porcelain")


def test_existing_codex_apply_lock_excludes_training_reader(repository, holders):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    process, pipe = holders(repository, "read")
    received(pipe)
    with pytest.raises(leases.SourceLeaseTimeout):
        with runner.codex_main_apply_lock({"source_repo_root": str(repository)}, timeout_seconds=0.05):
            pytest.fail("merger entered during training")
    release(process, pipe)
    with runner.codex_main_apply_lock({"source_repo_root": str(repository)}, timeout_seconds=1):
        with pytest.raises(leases.SourceLeaseTimeout):
            with leases.source_lease(repository, timeout_seconds=0.05):
                pytest.fail("training entered during merger")


def test_codex_dirty_check_failure_cannot_apply_patch(repository, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    monkeypatch.setattr(runner, "_codex_worktree_diff", lambda path: {
        "diff_content": "a patch", "target_files": ["source.py"]})
    def fail(*args):
        raise OSError("unreadable destination")
    monkeypatch.setattr(runner, "_dirty_target_files", fail)
    def never(*args, **kwargs):
        pytest.fail("apply must not run after dirty-check failure")
    monkeypatch.setattr(runner, "_run_git_apply_stdin", never)
    result = runner.apply_codex_worktree_changes_to_main(
        {"source_repo_root": str(repository), "worktree_path": str(repository)})
    assert result["patch_status"] == "main_apply_dirty_check_failed"
    assert result["main_apply_status"] == "failed"
    assert "unreadable destination" in result["main_apply_dirty_check_error"]
