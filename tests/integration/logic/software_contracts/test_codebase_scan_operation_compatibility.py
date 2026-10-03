"""Live and dirty callers share the admitted byte-preserving Git context."""
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.software_contracts.content import cid_for_byte_chunks, cid_for_bytes

from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy as policy
from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy_live as live
from ipfs_datasets_py.logic.software_contracts import codebase_git_operation as operations
from ipfs_datasets_py.logic.software_contracts import codebase_dirty_paged_staging as staged
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.backends import process as transport
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
from tests.integration.logic.software_contracts.test_codebase_scan_policy import current, git
from tests.integration.logic.software_contracts.test_codebase_dirty_paged_staging import (
    fixture as dirty_fixture, prepare as prepare_dirty, advance as advance_dirty,
    test_seal_without_parsing_then_bounded_pages_and_complete_global_equivalence as exercise_dirty_equivalence,
)


def files(index):
    return sorted((str(path), path.read_bytes()) for path in index.artifacts.root.rglob("*") if path.is_file())


def verify(current, value, **kwargs):
    root, index, _, scheduler, _ = current
    return live.verify_policy_current(index, root, expected_head=CodebaseHead.from_dict(value["head"]),
        receipt_cid=value["receipt_cid"], scheduler=scheduler, **kwargs)


def test_live_policy_replay_observes_current_source_without_artifact_writes(current):
    _, index, prepare, _, _ = current
    value = prepare()
    before = files(index)
    assert verify(current, value) == policy.load_policy_receipt(index, value["receipt_cid"])
    assert files(index) == before and operations.current_git_operation() is None


@pytest.mark.parametrize("helper", ["_external_ignore_scope", "_repository_rule_paths"])
def test_live_policy_final_scope_edit_is_rejected(current, monkeypatch, helper):
    root, index, prepare, _, _ = current
    value = prepare()
    before = files(index)
    original = getattr(live, helper)
    calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        if len(calls) == 2:
            (root / "main.py").write_text("def changed(n: int) -> int:\n    return n + 88\n")
        return result
    monkeypatch.setattr(live, helper, mutate)
    with pytest.raises(StaleCodebaseError):
        verify(current, value)
    assert len(calls) == 2 and files(index) == before
    assert operations.current_git_operation() is None


def test_live_policy_changed_external_scope_is_rejected_without_cas_writes(current, tmp_path):
    root, index, prepare, _, _ = current
    value = prepare()
    before = files(index)
    path = tmp_path / "new.ignore"
    path.write_text("*.py\n")
    git(root, "config", "core.excludesfile", str(path))
    with pytest.raises(policy.CodebaseScanPolicyError, match="active or oversized external"):
        verify(current, value)
    assert files(index) == before and operations.current_git_operation() is None


def test_live_policy_precancellation_prevents_native_queries(current, monkeypatch):
    _, index, prepare, _, _ = current
    value = prepare()
    before = files(index)
    cancelled = threading.Event()
    cancelled.set()
    calls = []
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", lambda *a, **k: calls.append(a))
    with pytest.raises(LeaseCancelledError):
        verify(current, value, cancel_event=cancelled)
    assert calls == [] and files(index) == before and operations.current_git_operation() is None


def test_live_policy_environment_drift_withholds_current_result(current, tmp_path, monkeypatch):
    _, index, prepare, _, _ = current
    value = prepare()
    before = files(index)
    original = live._repository_rule_paths
    calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        if len(calls) == 2:
            monkeypatch.setenv("HOME", str(tmp_path / "different-home"))
        return result
    monkeypatch.setattr(live, "_repository_rule_paths", mutate)
    with pytest.raises(policy.CodebaseScanPolicyError, match="configuration environment changed"):
        verify(current, value)
    assert files(index) == before and operations.current_git_operation() is None


@pytest.mark.parametrize("key", ["GIT_CONFIG", "GIT_DIR", "GIT_INDEX_FILE", "LD_PRELOAD"])
def test_native_redirects_are_rejected_before_initial_git(current, tmp_path, monkeypatch, key):
    root, index, prepare, _, _ = current
    home = tmp_path / "private-home"
    home.mkdir()
    active, bait = tmp_path / "active.ignore", tmp_path / "bait.config"
    active.write_text("*.py\n")
    (home / ".gitconfig").write_text(f"[core]\n\texcludesfile = {active}\n")
    bait.write_text("# inactive alternate config\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    monkeypatch.setenv(key, str(bait))
    calls = []
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", lambda *a, **k: calls.append(a))
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="loader or Git redirect"):
        prepare()
    assert calls == [] and files(index) == before and index.current("scan:fixture") is None
    assert operations.current_git_operation() is None


def test_scan_disables_optional_git_index_writes_when_parent_setting_is_absent(current, monkeypatch):
    root, _, prepare, _, _ = current
    monkeypatch.delenv("GIT_OPTIONAL_LOCKS", raising=False)
    path = root / ".git" / "index"
    before = path.read_bytes(), path.stat().st_mtime_ns
    original = transport.SubprocessExecutor.execute
    settings = []
    def observe(self, invocation, cancellation=None):
        settings.append(invocation.environment.get("GIT_OPTIONAL_LOCKS"))
        return original(self, invocation, cancellation)
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", observe)
    prepare()
    assert settings and set(settings) == {"0"}
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_dirty_prepare_pages_finalize_and_cold_equivalence(dirty_fixture, monkeypatch):
    exercise_dirty_equivalence(dirty_fixture, monkeypatch)
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("helper", ["_external_ignore_scope", "_repository_rule_paths"])
def test_dirty_final_scope_edit_refuses_page_before_cursor_write(dirty_fixture, monkeypatch, helper):
    state = prepare_dirty(dirty_fixture)
    original = getattr(policy, helper)
    calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        if len(calls) == 2:
            (dirty_fixture["root"] / "b.py").write_text("x = 99\n")
        return result
    monkeypatch.setattr(policy, helper, mutate)
    with pytest.raises(ValueError, match="dirty source"):
        advance_dirty(dirty_fixture, state)
    assert dirty_fixture["stager"].status(state["generation_cid"])["cursor"] == 0
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("operation", ["prepare", "advance"])
@pytest.mark.parametrize("failure", ["deadline", "cancel"])
def test_dirty_late_status_replay_withholds_success(dirty_fixture, monkeypatch, operation, failure):
    stager = dirty_fixture["stager"]
    state = prepare_dirty(dirty_fixture) if operation == "advance" else None
    clock, cancelled, results = [0.0], threading.Event(), []
    original = stager.status
    def late_status(generation):
        result = original(generation)
        results.append(result)
        if failure == "deadline":
            clock[0] = 121.0
        else:
            cancelled.set()
        return result
    with monkeypatch.context() as patch:
        patch.setattr(staged, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        patch.setattr(stager, "status", late_status)
        with pytest.raises(LeaseTimeoutError if failure == "deadline" else LeaseCancelledError):
            if operation == "prepare":
                prepare_dirty(dirty_fixture, cancel_event=cancelled)
            else:
                advance_dirty(dirty_fixture, state, cancel_event=cancelled)
    # Sealed historical work may already be committed; it grants no live success.
    assert len(results) == 1 and original(results[0]["generation_cid"]) == results[0]
    assert results[0]["cursor"] == (0 if operation == "prepare" else 2)
    assert dirty_fixture["index"].current("dirty:fixture") is None
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("failure", ["deadline", "cancel"])
def test_dirty_late_page_boundary_read_withholds_replay_success(dirty_fixture, monkeypatch, failure):
    initial = prepare_dirty(dirty_fixture)
    state = advance_dirty(dirty_fixture, initial)
    historical = dirty_fixture["stager"].status(state["generation_cid"])
    clock, cancelled, boundaries = [0.0], threading.Event(), []
    original = staged._require
    def after_native_boundary(condition, message):
        original(condition, message)
        if message == "cursor is not a sealed dirty page boundary":
            boundaries.append(condition)
            if failure == "deadline":
                clock[0] = 121.0
            else:
                cancelled.set()
    with monkeypatch.context() as patch:
        patch.setattr(staged, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        patch.setattr(staged, "_require", after_native_boundary)
        with pytest.raises(LeaseTimeoutError if failure == "deadline" else LeaseCancelledError):
            advance_dirty(dirty_fixture, initial, cancel_event=cancelled)
    assert boundaries == [True]
    assert dirty_fixture["stager"].status(state["generation_cid"]) == historical
    assert dirty_fixture["stager"].cx is dirty_fixture["stager"].owner._cx
    assert dirty_fixture["index"].current("dirty:fixture") is None
    assert operations.current_git_operation() is None


def test_chunked_source_cid_preserves_existing_raw_identity():
    payload = b"\xff\x00" + "original legal text\r\n§ 1\n".encode()
    assert cid_for_byte_chunks([b"", payload[:3], payload[3:]], max_chunk_bytes=len(payload)) == cid_for_bytes(payload)
    assert cid_for_byte_chunks((payload[offset:offset + 1] for offset in range(len(payload))), max_chunk_bytes=1) == cid_for_bytes(payload)
    assert cid_for_byte_chunks([], max_chunk_bytes=1) == cid_for_bytes(b"")


@pytest.mark.parametrize("chunks,cap", [([b"x"], 0), ([b"x"], True),
                                      ([memoryview(b"x")], 1), ([b"xx"], 1)])
def test_chunked_source_cid_refuses_ambiguous_or_oversized_frames(chunks, cap):
    with pytest.raises((TypeError, ValueError)):
        cid_for_byte_chunks(chunks, max_chunk_bytes=cap)
