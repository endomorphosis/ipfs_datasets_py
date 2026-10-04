"""Typed-exception regression tests for patch_control."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.agentic.patch_control import (
    IPFSPatchStore,
    Patch,
    PatchManager,
    WorktreeManager,
)


def _patch() -> Patch:
    return Patch(
        patch_id="p1",
        agent_id="a1",
        task_id="t1",
        description="desc",
        diff_content="diff --git a/x.py b/x.py\n",
        target_files=["x.py"],
        created_at=datetime.now(),
    )


def test_patch_manager_apply_patch_returns_false_on_typed_error(monkeypatch, tmp_path):
    manager = PatchManager(patches_dir=tmp_path / "patches")

    class _FailingTempFile:
        def __init__(self, *_args, **_kwargs):
            raise OSError("tempfile unavailable")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", _FailingTempFile)
    ok = manager.apply_patch(_patch(), tmp_path)
    assert ok is False


def test_patch_manager_apply_patch_propagates_base_exception(monkeypatch, tmp_path):
    manager = PatchManager(patches_dir=tmp_path / "patches")

    class _InterruptingTempFile:
        def __init__(self, *_args, **_kwargs):
            raise KeyboardInterrupt("stop")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", _InterruptingTempFile)
    with pytest.raises(KeyboardInterrupt):
        manager.apply_patch(_patch(), tmp_path)


def test_worktree_cleanup_returns_false_on_typed_error(monkeypatch, tmp_path):
    manager = WorktreeManager(repo_path=tmp_path, worktrees_base=tmp_path / "wts")
    wt = tmp_path / "wts" / "wt-a1"
    wt.mkdir(parents=True)
    manager.active_worktrees["a1"] = wt

    def _raise_oserror(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr("subprocess.run", _raise_oserror)
    assert manager.cleanup_worktree("a1") is False


def test_worktree_cleanup_propagates_base_exception(monkeypatch, tmp_path):
    manager = WorktreeManager(repo_path=tmp_path, worktrees_base=tmp_path / "wts")
    wt = tmp_path / "wts" / "wt-a1"
    wt.mkdir(parents=True)
    manager.active_worktrees["a1"] = wt

    def _raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr("subprocess.run", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        manager.cleanup_worktree("a1")


def test_ipfs_get_patch_wraps_typed_decode_errors():
    client = SimpleNamespace(cat=lambda _cid: b"not-json")
    store = IPFSPatchStore(client)
    with pytest.raises(ValueError, match="Failed to retrieve patch"):
        store.get_patch("cid123")


def test_ipfs_get_patch_propagates_base_exception():
    def _interrupt(_cid):
        raise KeyboardInterrupt("stop")

    client = SimpleNamespace(cat=_interrupt)
    store = IPFSPatchStore(client)
    with pytest.raises(KeyboardInterrupt):
        store.get_patch("cid123")


def test_ipfs_pin_patch_returns_false_on_typed_error():
    pin = SimpleNamespace(add=lambda _cid: (_ for _ in ()).throw(OSError("pin failed")))
    client = SimpleNamespace(pin=pin)
    store = IPFSPatchStore(client)
    assert store.pin_patch("cid123") is False


def test_ipfs_pin_patch_propagates_base_exception():
    pin = SimpleNamespace(add=lambda _cid: (_ for _ in ()).throw(KeyboardInterrupt("stop")))
    client = SimpleNamespace(pin=pin)
    store = IPFSPatchStore(client)
    with pytest.raises(KeyboardInterrupt):
        store.pin_patch("cid123")
