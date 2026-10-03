"""Selected stable configuration and descriptor-relative source boundaries."""
from dataclasses import replace
import os
from pathlib import Path
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_git_operation as operations
from ipfs_datasets_py.logic.software_contracts import codebase_path_boundary as paths
from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy as policy
from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy_live as live
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.backends import process as transport
from tests.integration.logic.software_contracts.test_codebase_scan_policy import (
    current, git, private_configuration,
)
from tests.integration.logic.software_contracts.test_codebase_scan_operation_compatibility import (
    dirty_fixture, prepare_dirty, advance_dirty, verify, files,
)

CONFIG_QUERY = ("config", "--null", "--includes", "--show-origin", "--show-scope", "--list")


def config_append(root, text):
    with (root / ".git" / "config").open("a") as stream:
        stream.write("\n" + text)


def native_calls(monkeypatch):
    calls = []
    actual = transport.SubprocessExecutor.execute
    def observe(self, invocation, cancellation=None):
        calls.append(invocation)
        return actual(self, invocation, cancellation)
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", observe)
    return calls


def only_config(calls):
    assert calls and all(tuple(call.argv[-len(CONFIG_QUERY):]) == CONFIG_QUERY for call in calls)


@pytest.mark.parametrize("declaration", [
    '\tclean = forbidden-codebase-filter\n', '\tprocess = forbidden-codebase-filter\n',
    '\tsmudge = forbidden-codebase-filter\n', '\trequired = false\n',
    '\tclean\n', '\tclean =\n',
])
def test_filter_configuration_is_refused_before_status_or_source(current, monkeypatch, declaration):
    root, index, prepare, _, _ = current
    (root / ".gitattributes").write_text("*.py filter=blocked\n")
    config_append(root, '[filter "blocked"]\n' + declaration)
    before = files(index)
    calls = native_calls(monkeypatch)
    with pytest.raises(policy.CodebaseScanPolicyError, match="filter"):
        prepare()
    only_config(calls)
    assert index.current("scan:fixture") is None and files(index) == before
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("origin", ["home", "xdg", "include", "worktree", "command"])
def test_filter_rejection_retains_native_configuration_origins(current, tmp_path, monkeypatch, origin):
    root, index, prepare, _, _ = current
    text = '[filter "blocked"]\n\tclean = forbidden-codebase-filter\n'
    if origin in {"home", "xdg", "include"}:
        home, xdg = private_configuration(tmp_path, monkeypatch)
        if origin == "home":
            (home / ".gitconfig").write_text(text)
        elif origin == "xdg":
            (xdg / "git" / "config").write_text(text)
        else:
            (home / "selected.conf").write_text(text)
            (home / ".gitconfig").write_text('[include]\n\tpath = selected.conf\n')
    elif origin == "worktree":
        config_append(root, '[extensions]\n\tworktreeConfig = true\n')
        (root / ".git" / "config.worktree").write_text(text)
    else:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "10")
        monkeypatch.setenv("GIT_CONFIG_KEY_9", "filter.blocked.clean")
        monkeypatch.setenv("GIT_CONFIG_VALUE_9", "forbidden-codebase-filter")
    before = files(index)
    calls = native_calls(monkeypatch)
    with pytest.raises(policy.CodebaseScanPolicyError, match="filter"):
        prepare()
    only_config(calls)
    assert index.current("scan:fixture") is None and files(index) == before


@pytest.mark.parametrize("change", ["duplicate", "filter"])
def test_configuration_added_after_preflight_is_refused_before_first_source_query(current, monkeypatch, change):
    root, index, prepare, _, _ = current
    actual = transport.SubprocessExecutor.execute
    calls = []
    def mutate(self, invocation, cancellation=None):
        result = actual(self, invocation, cancellation)
        calls.append(invocation)
        if len(calls) == 1:
            config_append(root, '[user]\n\temail = changed@example.invalid\n' if change == "duplicate"
                          else '[filter "blocked"]\n\tprocess = forbidden-codebase-filter\n')
        return result
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", mutate)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="configuration"):
        prepare()
    only_config(calls)
    assert files(index) == before and index.current("scan:fixture") is None


def test_configuration_drift_after_policy_sealing_withholds_current_success(current, monkeypatch):
    root, index, prepare, _, _ = current
    actual, receipts = index.artifacts.put, []
    def mutate(value):
        result = actual(value)
        if value.get("schema") == policy.RECEIPT_SCHEMA:
            receipts.append(result)
            config_append(root, '[user]\n\temail = final@example.invalid\n')
        return result
    monkeypatch.setattr(index.artifacts, "put", mutate)
    with pytest.raises(policy.CodebaseScanPolicyError, match="configuration records changed"):
        prepare()
    assert len(receipts) == 1
    assert policy.load_policy_receipt(index, receipts[0])["source_observed_live"] is False
    assert operations.current_git_operation() is None


def test_context_exit_checks_config_after_last_live_source_helper(current, monkeypatch):
    root, index, prepare, _, _ = current
    value = prepare()
    before = files(index)
    actual, calls = index.observe_current, []
    def mutate(*args, **kwargs):
        result = actual(*args, **kwargs)
        calls.append(result)
        if len(calls) == 2:
            config_append(root, '[user]\n\temail = live-final@example.invalid\n')
        return result
    monkeypatch.setattr(index, "observe_current", mutate)
    with pytest.raises(policy.CodebaseScanPolicyError, match="configuration records changed"):
        verify(current, value)
    assert len(calls) == 2 and files(index) == before
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("operation", ["prepare", "advance"])
def test_context_exit_checks_config_after_dirty_status_replay(dirty_fixture, monkeypatch, operation):
    state = prepare_dirty(dirty_fixture) if operation == "advance" else None
    stager = dirty_fixture["stager"]
    actual, statuses = stager.status, []
    def mutate(generation):
        result = actual(generation)
        statuses.append(result)
        config_append(dirty_fixture["root"], '[user]\n\temail = dirty-final@example.invalid\n')
        return result
    monkeypatch.setattr(stager, "status", mutate)
    with pytest.raises(ValueError, match="configuration records changed"):
        prepare_dirty(dirty_fixture) if operation == "prepare" else advance_dirty(dirty_fixture, state)
    assert len(statuses) == 1 and dirty_fixture["index"].current("dirty:fixture") is None
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("variable", ["GIT_TRACE", "GIT_TRACE2_EVENT", "GIT_TRACE_SETUP"])
def test_ambient_trace_targets_are_refused_before_any_native_child(current, tmp_path, monkeypatch, variable):
    _, index, prepare, _, _ = current
    target = tmp_path / "trace-must-not-exist"
    monkeypatch.setenv(variable, str(target))
    calls = native_calls(monkeypatch)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="redirect"):
        prepare()
    assert calls == [] and not target.exists() and files(index) == before


@pytest.mark.parametrize("text", [
    '[trace2]\n\teventTarget = trace-must-not-exist\n',
    '[extensions]\n\tpartialClone = origin\n',
    '[remote "origin"]\n\tpromisor = false\n',
    '[core]\n\talternateRefsCommand = forbidden-codebase-filter\n',
])
def test_native_child_configuration_extensions_are_refused_before_source(current, monkeypatch, text):
    root, index, prepare, _, _ = current
    config_append(root, text)
    calls = native_calls(monkeypatch)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="configuration is outside"):
        prepare()
    only_config(calls)
    assert not (root / "trace-must-not-exist").exists() and files(index) == before


def test_native_protocol_trace_pager_and_submodule_controls_are_explicit(current, monkeypatch):
    _, _, prepare, _, _ = current
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    calls = native_calls(monkeypatch)
    prepare()
    assert calls and all(call.environment["GIT_ALLOW_PROTOCOL"] == "" and
        call.environment["GIT_NO_LAZY_FETCH"] == "1" and
        all(call.environment[key] == "0" for key in ["GIT_TRACE2", "GIT_TRACE2_PERF", "GIT_TRACE2_EVENT"])
        and call.argv[3] == "--no-pager" for call in calls)
    statuses = [call for call in calls if "status" in call.argv]
    assert statuses and all(call.argv[-1] == "--ignore-submodules=all" for call in statuses)


def test_oversized_configuration_is_native_output_bounded_before_source(current, monkeypatch):
    root, index, prepare, _, _ = current
    config_append(root, '[user]\n\tpadding = ' + 'x' * (600 * 1024) + '\n')
    calls = native_calls(monkeypatch)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="bounded process profile"):
        prepare()
    only_config(calls)
    assert len(calls) == 1 and calls[0].limits.max_output_bytes == 512 * 1024
    assert files(index) == before and operations.current_git_operation() is None


def test_malformed_configuration_records_are_refused(current, monkeypatch):
    _, index, prepare, _, _ = current
    actual = transport.SubprocessExecutor.execute
    def malformed(self, invocation, cancellation=None):
        result = actual(self, invocation, cancellation)
        return replace(result, stdout=b"local\0file:config\0user.name\nvalue\0trailing")
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", malformed)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="records are malformed"):
        prepare()
    assert files(index) == before and operations.current_git_operation() is None


def stat_identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def parent_pair(root, tmp_path):
    parent, replacement = root / "nested", tmp_path / "replacement"
    parent.mkdir(); replacement.mkdir()
    source = parent / "unit.py"
    source.write_text("x = 1\n")
    os.link(source, replacement / "unit.py")
    before = stat_identity(source)
    def swap():
        parent.rename(tmp_path / "old-parent")
        replacement.rename(parent)
        assert stat_identity(source) == before
    return source, swap


def test_nested_capture_preserves_content_and_serialized_identity(current):
    root, _, _, _, _ = current
    (root / "nested").mkdir()
    source = root / "nested" / "unit.py"
    source.write_bytes(b"x = 1\r\n")
    entry = policy.snapshots._working_entry(root, b"nested/unit.py", 512)
    assert entry.captured_bytes == source.read_bytes() and entry.source_cid == cid_for_bytes(source.read_bytes())
    assert entry.ancestor_witness and "ancestor_witness" not in entry.to_dict()
    replayed = policy.snapshots.SnapshotEntry.from_dict(entry.to_dict())
    assert replayed == entry and replayed.entry_cid == entry.entry_cid and replayed.ancestor_witness is None


@pytest.mark.parametrize("present", [True, False])
def test_source_ancestor_symlinks_never_open_or_capture_leaf(current, tmp_path, monkeypatch, present):
    root, _, _, _, _ = current
    target = tmp_path / "outside"
    if present:
        target.mkdir(); (target / "unit.py").write_text("x = 99\n")
    (root / "nested").symlink_to(target)
    actual, opened = paths.PathBoundary.open_leaf, []
    def observe(boundary):
        opened.append(boundary.path)
        return actual(boundary)
    monkeypatch.setattr(paths.PathBoundary, "open_leaf", observe)
    entry = policy.snapshots._working_entry(root, b"nested/unit.py", 512)
    assert entry.opaque_reason == "unsafe_ancestor" and entry.captured_bytes is None and entry.source_cid is None
    assert opened == []


def test_non_directory_source_ancestor_is_opaque(current):
    root, _, _, _, _ = current
    (root / "nested").write_text("x = 1\n")
    entry = policy.snapshots._working_entry(root, b"nested/unit.py", 512)
    assert entry.opaque_reason == "unsafe_ancestor" and entry.captured_bytes is None


def test_parent_swap_with_identical_leaf_is_rejected_during_capture(current, tmp_path, monkeypatch):
    root, _, _, _, _ = current
    source, swap = parent_pair(root, tmp_path)
    actual, swaps = paths.PathBoundary.open_leaf, []
    def mutate(boundary):
        if boundary.path == source:
            swap(); swaps.append(True)
        return actual(boundary)
    monkeypatch.setattr(paths.PathBoundary, "open_leaf", mutate)
    entry = policy.snapshots._working_entry(root, b"nested/unit.py", 512)
    assert swaps == [True] and entry.opaque_reason == "unsafe_ancestor" and entry.captured_bytes is None


def swap_after_capture(monkeypatch, source, swap):
    actual, swaps = policy.snapshots._working_entry, []
    def mutate(*args, **kwargs):
        result = actual(*args, **kwargs)
        if result.path == "nested/unit.py" and not swaps:
            swap(); swaps.append(True)
        return result
    monkeypatch.setattr(policy.snapshots, "_working_entry", mutate)
    return swaps


def test_snapshot_final_fence_rejects_parent_swap_with_identical_leaf(current, tmp_path, monkeypatch):
    root, index, prepare, _, _ = current
    source, swap = parent_pair(root, tmp_path)
    swaps = swap_after_capture(monkeypatch, source, swap)
    with pytest.raises(ValueError, match="ancestor changed"):
        prepare()
    assert swaps == [True] and index.current("scan:fixture") is None
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("present", [True, False])
def test_external_ignore_ancestor_symlink_is_strictly_refused(current, tmp_path, monkeypatch, present):
    root, index, prepare, _, _ = current
    target = tmp_path / "outside"
    if present:
        target.mkdir(); (target / "ignore").write_text("# inactive\n")
    link = tmp_path / "linked"
    link.symlink_to(target)
    git(root, "config", "core.excludesfile", str(link / "ignore"))
    actual, opened = paths.PathBoundary.open_leaf, []
    def observe(boundary):
        opened.append(boundary.path)
        return actual(boundary)
    monkeypatch.setattr(paths.PathBoundary, "open_leaf", observe)
    with pytest.raises(policy.CodebaseScanPolicyError, match="ancestor binding"):
        prepare()
    assert link / "ignore" not in opened and target / "ignore" not in opened
    assert index.current("scan:fixture") is None


def test_external_ignore_parent_swap_with_identical_leaf_is_refused(current, tmp_path, monkeypatch):
    root, index, prepare, _, _ = current
    parent, replacement = tmp_path / "ignores", tmp_path / "replacement"
    parent.mkdir(); replacement.mkdir()
    path = parent / "ignore"; path.write_text("# inactive\n")
    os.link(path, replacement / "ignore"); before = stat_identity(path)
    git(root, "config", "core.excludesfile", str(path))
    actual, swaps = paths.PathBoundary.open_leaf, []
    def mutate(boundary):
        if boundary.path == path:
            parent.rename(tmp_path / "old-ignore-parent"); replacement.rename(parent)
            assert stat_identity(path) == before
            swaps.append(True)
        return actual(boundary)
    monkeypatch.setattr(paths.PathBoundary, "open_leaf", mutate)
    with pytest.raises(policy.CodebaseScanPolicyError, match="ancestor binding"):
        prepare()
    assert swaps == [True] and index.current("scan:fixture") is None


def test_external_ignore_parent_traversal_is_refused_without_normalizing(current, tmp_path):
    root, _, prepare, _, _ = current
    target = tmp_path / "outside"; target.mkdir()
    (tmp_path / "linked").symlink_to(target)
    git(root, "config", "core.excludesfile", str(tmp_path / "linked" / ".." / "ignore"))
    with pytest.raises(policy.CodebaseScanPolicyError, match="parent components"):
        prepare()


def test_root_parent_replacement_prevents_the_next_native_query(current, tmp_path, monkeypatch):
    root, index, prepare, _, _ = current
    actual, calls = transport.SubprocessExecutor.execute, []
    def mutate(self, invocation, cancellation=None):
        result = actual(self, invocation, cancellation)
        calls.append(invocation)
        root.rename(tmp_path / "old-repository")
        root.mkdir()
        return result
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", mutate)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="root ancestor binding"):
        prepare()
    only_config(calls)
    assert len(calls) == 1 and files(index) == before and index.current("scan:fixture") is None
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("unsafe", [False, True])
def test_path_acquisition_closes_all_opened_descriptors(current, tmp_path, monkeypatch, unsafe):
    root, _, _, _, _ = current
    if unsafe:
        (root / "nested").symlink_to(tmp_path / "absent")
    else:
        (root / "nested").mkdir(); (root / "nested" / "unit.py").write_text("x = 1\n")
    actual, descriptors = os.open, []
    def observe(*args, **kwargs):
        fd = actual(*args, **kwargs)
        descriptors.append(fd)
        return fd
    monkeypatch.setattr(os, "open", observe)
    entry = policy.snapshots._working_entry(root, b"nested/unit.py", 512)
    assert entry.is_opaque is unsafe and descriptors
    for fd in set(descriptors):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_live_reobservation_rejects_parent_swap_without_cas_writes(current, tmp_path, monkeypatch):
    root, index, prepare, _, _ = current
    source, swap = parent_pair(root, tmp_path)
    value = prepare(); before = files(index)
    swaps = swap_after_capture(monkeypatch, source, swap)
    with pytest.raises(ValueError, match="ancestor changed"):
        verify(current, value)
    assert swaps == [True] and files(index) == before and operations.current_git_operation() is None


def test_dirty_reobservation_rejects_parent_swap_before_cursor_write(dirty_fixture, monkeypatch):
    source, swap = parent_pair(dirty_fixture["root"], dirty_fixture["tmp"])
    state = prepare_dirty(dirty_fixture)
    swaps = swap_after_capture(monkeypatch, source, swap)
    with pytest.raises(ValueError, match="ancestor changed"):
        advance_dirty(dirty_fixture, state)
    assert swaps == [True]
    assert dirty_fixture["stager"].status(state["generation_cid"])["cursor"] == 0
    assert operations.current_git_operation() is None


def test_closed_git_context_cannot_launch_a_later_configuration_query(current, monkeypatch):
    _, _, prepare, _, _ = current
    actual, contexts, calls = transport.SubprocessExecutor.execute, [], []
    def observe(self, invocation, cancellation=None):
        contexts.append(operations.current_git_operation())
        calls.append(invocation)
        return actual(self, invocation, cancellation)
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", observe)
    prepare()
    count = len(calls)
    context = contexts[0]
    assert context is not None and all(item is context for item in contexts)
    with pytest.raises(operations.GitOperationError, match="active admitted"):
        context.verify_configuration()
    assert len(calls) == count and operations.current_git_operation() is None


def test_final_leaf_stat_cannot_hide_a_subsequent_parent_swap(current, tmp_path, monkeypatch):
    root, index, prepare, _, _ = current
    source, swap = parent_pair(root, tmp_path)
    actual, stats, swaps = paths.PathBoundary.stat_leaf, [], []
    def mutate(boundary):
        result = actual(boundary)
        if boundary.path == source:
            stats.append(result)
            if len(stats) == 3:
                swap(); swaps.append(True)
        return result
    monkeypatch.setattr(paths.PathBoundary, "stat_leaf", mutate)
    with pytest.raises(ValueError, match="changed during snapshot"):
        prepare()
    assert swaps == [True] and index.current("scan:fixture") is None
    assert operations.current_git_operation() is None


def test_source_descriptor_cleanup_failure_is_never_an_opaque_success(current, monkeypatch):
    root, _, _, _, _ = current
    source = root / "unit.py"; source.write_text("x = 1\n")
    actual, faults = os.close, []
    def close_then_fail(fd):
        actual(fd)
        if not faults:
            faults.append(fd)
            raise OSError("injected acknowledgement failure after actual close")
    monkeypatch.setattr(os, "close", close_then_fail)
    with pytest.raises(paths.PathCleanupError, match="cleanup failed"):
        policy.snapshots._working_entry(root, b"unit.py", 512)
    assert len(faults) == 1
    with pytest.raises(OSError):
        os.fstat(faults[0])


def test_global_trace2_target_is_disabled_before_preflight_reads_it(current, tmp_path, monkeypatch):
    _, index, prepare, _, _ = current
    home, _ = private_configuration(tmp_path, monkeypatch)
    target = tmp_path / "trace-must-not-exist"
    (home / ".gitconfig").write_text(f"[trace2]\n\teventTarget = {target}\n")
    calls = native_calls(monkeypatch)
    before = files(index)
    with pytest.raises(policy.CodebaseScanPolicyError, match="configuration is outside"):
        prepare()
    only_config(calls)
    assert all(call.environment["GIT_TRACE2_EVENT"] == "0" for call in calls)
    assert not target.exists() and files(index) == before
