"""Complete committed coverage is explicit and never inferred from a partial scan."""

import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import committed_snapshot as c
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import snapshot_repository


def git(root, *args, data=None):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
                                   input=data, stderr=subprocess.DEVNULL).decode().strip()


def commit(root):
    git(root, "add", "-A")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "fixture")
    return dict(expected_commit=git(root, "rev-parse", "HEAD"),
                expected_tree=git(root, "rev-parse", "HEAD^{tree}"), repository_id="fixture:complete")


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "module.py").write_bytes(b"value = 1\n")
    return root, commit(root)


def test_explicit_complete_scope_includes_normally_excluded_committed_paths(source):
    root, _ = source
    for relative in ("coverage/report.py", "venv/required.py"):
        path = root / relative
        path.parent.mkdir()
        path.write_bytes(b"value = 1\n")
    request = commit(root)
    ordinary = snapshot_repository(root, exclusions=())
    assert [entry.path for entry in ordinary.entries] == ["module.py"]
    plan = c.preflight_committed_repository(root, **request)
    assert [entry.path for entry in plan.entries] == ["coverage/report.py", "module.py", "venv/required.py"]
    assert plan.blob_count == 3
    assert plan.total_blob_bytes == 30  # Shared blob OIDs still count per path.
    assert plan.maximum_blob_bytes == 10
    snapshot = c.snapshot_committed_repository(root, **request, expected_population_cid=plan.population_cid)
    assert [entry.path for entry in snapshot.entries] == [entry.path for entry in plan.entries]
    assert snapshot.exclusions == ()
    assert all(entry.captured_bytes == b"value = 1\n" for entry in snapshot.entries)
    assert not any(entry.path.startswith(".git/") for entry in snapshot.entries)
    assert snapshot_repository(root, exclusions=()).snapshot_cid == ordinary.snapshot_cid


@pytest.mark.parametrize("limits,expected", [
    ({"max_file_bytes": 9}, ("max_file_bytes",)),
    ({"max_total_bytes": 9}, ("max_total_bytes",)),
    ({"max_file_bytes": 9, "max_total_bytes": 9}, ("max_file_bytes", "max_total_bytes")),
])
def test_metadata_plan_reports_exact_budget_deficiency_before_blob_reads(source, monkeypatch, limits, expected):
    root, request = source
    real_git = c._run_git
    def forbid_blob_acquisition(root, args, limit):
        assert args[:2] != ("cat-file", "blob"), "budgets must be checked before blob acquisition"
        return real_git(root, args, limit)
    monkeypatch.setattr(c, "_run_git", forbid_blob_acquisition)
    plan = c.preflight_committed_repository(root, **request, **limits)
    assert plan.total_blob_bytes == plan.maximum_blob_bytes == 10
    assert plan.budget_violations == expected
    assert plan.to_dict()["blob_bytes_acquired"] == 0
    assert plan.to_dict()["entries"][0]["git_object_oid"] == git(root, "rev-parse", "HEAD:module.py")
    with pytest.raises(c.CommittedPopulationBudgetError) as error:
        c.snapshot_committed_repository(root, **request, **limits)
    assert error.value.plan == plan


def test_entry_budget_refuses_whole_population_without_partial_snapshot(source, monkeypatch):
    root, _ = source
    (root / "second.py").write_text("other = 2\n")
    request = commit(root)
    plan = c.preflight_committed_repository(root, **request, max_entries=1)
    assert len(plan.entries) == 2
    assert plan.budget_violations == ("max_entries",)
    with pytest.raises(c.CommittedPopulationBudgetError):
        c.snapshot_committed_repository(root, **request, max_entries=1)


def test_dirty_checkout_and_hidden_index_bytes_are_refused(source):
    root, request = source
    (root / "module.py").write_bytes(b"value = 2\n")
    with pytest.raises(c.GitSnapshotError, match="clean checkout"):
        c.preflight_committed_repository(root, **request)
    git(root, "update-index", "--assume-unchanged", "module.py")
    with pytest.raises(c.GitSnapshotError, match="hides tracked bytes"):
        c.preflight_committed_repository(root, **request)


def test_wrong_unreachable_and_tampered_refs_are_refused(source):
    root, request = source
    unreachable = git(root, "-c", "user.name=Fixture", "-c", "user.email=test@example.invalid",
                      "commit-tree", request["expected_tree"], "-m", "unreachable")
    assert unreachable != request["expected_commit"]
    with pytest.raises(c.GitSnapshotError, match="HEAD differs"):
        c.preflight_committed_repository(root, **dict(request, expected_commit=unreachable))
    with pytest.raises(c.GitSnapshotError, match="HEAD differs"):
        c.preflight_committed_repository(root, **dict(request, expected_commit="0" * 40))
    with pytest.raises(c.GitSnapshotError, match="tree differs"):
        c.preflight_committed_repository(root, **dict(request, expected_tree="0" * 40))
    (root / ".git/refs/heads/main").write_text("0" * 40 + "\n")
    with pytest.raises(c.GitSnapshotError):
        c.preflight_committed_repository(root, **request)


def test_missing_blob_is_refused_by_metadata_preflight(source, monkeypatch):
    root, request = source
    oid = git(root, "rev-parse", "HEAD:module.py")
    (root / ".git/objects" / oid[:2] / oid[2:]).unlink()
    with pytest.raises(c.GitSnapshotError):
        c.preflight_committed_repository(root, **request)


def test_git_replacement_cannot_substitute_requested_blob(source):
    root, request = source
    original = git(root, "rev-parse", "HEAD:module.py")
    replacement = git(root, "hash-object", "-w", "--stdin", data=b"evil = 999\n")
    git(root, "replace", original, replacement)
    snapshot = c.snapshot_committed_repository(root, **request)
    assert snapshot.entries[0].git_blob_oid == original
    assert snapshot.entries[0].captured_bytes == b"value = 1\n"


def test_tampered_blob_bytes_and_population_binding_are_refused(source, monkeypatch):
    root, request = source
    with pytest.raises(c.GitSnapshotError, match="requested preflight"):
        c.snapshot_committed_repository(root, **request, expected_population_cid="tampered")
    real_git = c._run_git
    def tampered(root, args, limit):
        if args[:2] == ("cat-file", "blob"):
            return b"value = 9\n"
        return real_git(root, args, limit)
    monkeypatch.setattr(c, "_run_git", tampered)
    with pytest.raises(c.GitSnapshotError, match="object identity"):
        c.snapshot_committed_repository(root, **request)


def test_head_move_during_metadata_inventory_is_refused(source, monkeypatch):
    root, original = source
    (root / "module.py").write_bytes(b"value = 2\n")
    other = commit(root)
    git(root, "reset", "--hard", original["expected_commit"])
    real_git = c._run_git
    def move_head(root, args, limit):
        data = real_git(root, args, limit)
        if args[0] == "ls-tree":
            git(root, "update-ref", "HEAD", other["expected_commit"])
        return data
    monkeypatch.setattr(c, "_run_git", move_head)
    with pytest.raises(c.GitSnapshotError, match="HEAD differs"):
        c.preflight_committed_repository(root, **original)


def test_gitlinks_symlinks_and_non_utf8_names_remain_explicit(source):
    root, original = source
    (root / "linked.py").symlink_to("module.py")
    raw_path = os.fsencode(root) + b"/invalid-\xff.py"
    descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(descriptor, b"x = 1\n")
    os.close(descriptor)
    (root / "nested").mkdir()
    git(root, "update-index", "--add", "--cacheinfo", "160000", original["expected_commit"], "nested")
    request = commit(root)
    plan = c.preflight_committed_repository(root, **request)
    snapshot = c.snapshot_committed_repository(root, **request)
    assert {entry.raw_path_hex for entry in snapshot.entries} == {entry.raw_path_hex for entry in plan.entries}
    by_path = {entry.path: entry for entry in snapshot.entries}
    assert by_path["linked.py"].opaque_reason == "symlink_or_nonregular"
    assert by_path["nested"].opaque_reason == "symlink_or_nonregular"
    malformed = next(entry for entry in snapshot.entries if entry.raw_path_hex == b"invalid-\xff.py".hex())
    assert malformed.opaque_reason == "malformed_path"


def test_subdirectory_and_metadata_overflow_never_downgrade_to_filesystem(source):
    root, request = source
    child = root / "ignored-child"
    child.mkdir()
    with pytest.raises(c.GitSnapshotError, match="exact repository root"):
        c.preflight_committed_repository(child, **request)
    with pytest.raises(c.GitSnapshotError, match="acquisition budget"):
        c.preflight_committed_repository(root, **request, max_metadata_bytes=1)


@pytest.mark.parametrize("field,value", [("max_entries", True), ("max_file_bytes", 0),
                                        ("max_total_bytes", -1), ("max_metadata_bytes", 0)])
def test_invalid_acquisition_limits_are_rejected(source, field, value):
    root, request = source
    with pytest.raises(c.SnapshotError, match="positive integers"):
        c.preflight_committed_repository(root, **request, **{field: value})
