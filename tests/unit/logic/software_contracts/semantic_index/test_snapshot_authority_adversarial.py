"""Independent, test-first authority probes for repository snapshots.

This file is deliberately outside the production task's ownership.  It
exercises only public snapshot/scanner entry points while perturbing Git or
the filesystem underneath those entry points.  A provider repairing the
implementation must not edit, replace, rename, or weaken these assertions.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path
import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import (
    RepositoryScanner,
    scan_repository_state,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    GitSnapshotError,
    RepositorySnapshot,
    SnapshotEntry,
    SnapshotError,
    repository_identity,
    snapshot_repository,
)


def _git(
    repository: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=check,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init(repository: Path) -> None:
    repository.mkdir(parents=True, exist_ok=True)
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "snapshot-audit@example.invalid")
    _git(repository, "config", "user.name", "Snapshot Audit")


def _commit_module(repository: Path, source: bytes = b"value = 1\n") -> None:
    _init(repository)
    (repository / "module.py").write_bytes(source)
    _git(repository, "add", "module.py")
    _git(repository, "commit", "-q", "-m", "root")


def _entry(snapshot: RepositorySnapshot, path: str) -> SnapshotEntry:
    return next(item for item in snapshot.entries if item.path == path)


def _raw_file(parent: Path, relative: bytes, data: bytes = b"value = 1\n") -> None:
    absolute = os.fsencode(parent) + b"/" + relative
    descriptor = os.open(absolute, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def _is_git_command(command: object, *args: str) -> bool:
    return (
        isinstance(command, (list, tuple))
        and tuple(command) == ("git", *args)
    )


def test_born_identity_is_portable_stable_and_history_distinct(tmp_path: Path) -> None:
    original = tmp_path / "original"
    clone = tmp_path / "clone"
    linked = tmp_path / "linked"
    unrelated = tmp_path / "unrelated"
    _commit_module(original)
    _git(tmp_path, "clone", "-q", str(original), str(clone))
    _git(original, "worktree", "add", "-q", "--detach", str(linked), "HEAD")

    first = repository_identity(original)
    assert repository_identity(clone) == first
    assert repository_identity(linked) == first

    (original / "module.py").write_text("value = 2\n", encoding="utf-8")
    _git(original, "add", "module.py")
    _git(original, "commit", "-q", "-m", "ordinary change")
    _git(original, "commit", "-q", "--allow-empty", "-m", "same-tree change")
    assert repository_identity(original) == first

    _commit_module(unrelated, b"unrelated = True\n")
    assert repository_identity(unrelated) != first


def test_unrelated_unborn_repositories_have_distinct_local_bootstrap_ids(
    tmp_path: Path,
) -> None:
    repositories = [tmp_path / "one" / "same", tmp_path / "two" / "same"]
    for repository in repositories:
        _init(repository)
    assert repository_identity(repositories[0]) != repository_identity(repositories[1])


def test_explicit_unborn_bootstrap_id_and_inventory_survive_first_commit(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    (tmp_path / "staged.py").write_text("staged = True\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("untracked = True\n", encoding="utf-8")
    _git(tmp_path, "add", "staged.py")

    unborn = snapshot_repository(tmp_path, repository_id="repo:explicit-bootstrap")
    by_path = {item.path: item for item in unborn.entries}
    assert unborn.mode == "git-unborn"
    assert unborn.repository_id == "repo:explicit-bootstrap"
    assert by_path["staged.py"].disposition == "staged_added"
    assert by_path["staged.py"].git_blob_oid is not None
    assert by_path["untracked.py"].disposition == "untracked"
    assert by_path["untracked.py"].git_blob_oid is None

    _git(tmp_path, "commit", "-q", "-m", "first")
    born = snapshot_repository(tmp_path, repository_id="repo:explicit-bootstrap")
    assert born.repository_id == unborn.repository_id


def test_captured_commit_derives_its_own_tree_and_head_advance_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit_module(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run
    advanced = False

    def run(command, *args, **kwargs):
        nonlocal advanced
        result = real_run(command, *args, **kwargs)
        command_args = tuple(command) if isinstance(command, (list, tuple)) else ()
        if (
            not advanced
            and len(command_args) == 3
            and command_args[:2] == ("git", "rev-parse")
            and command_args[2].endswith("^{tree}")
        ):
            advanced = True
            (tmp_path / "module.py").write_text("value = 2\n", encoding="utf-8")
            real_run(["git", "add", "module.py"], cwd=tmp_path, check=True)
            real_run(
                ["git", "commit", "-q", "-m", "advance"],
                cwd=tmp_path,
                check=True,
            )
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)
    assert advanced


@pytest.mark.parametrize("mutation", ["working", "index"])
def test_same_head_status_or_index_mutation_fails_generation_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _commit_module(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run
    mutated = False

    def run(command, *args, **kwargs):
        nonlocal mutated
        result = real_run(command, *args, **kwargs)
        command_args = tuple(command) if isinstance(command, (list, tuple)) else ()
        trigger = (
            mutation == "working"
            and command_args[:3] == ("git", "status", "--porcelain")
        ) or (
            mutation == "index"
            and command_args[:3] == ("git", "ls-files", "--stage")
        )
        if trigger and not mutated:
            mutated = True
            (tmp_path / "module.py").write_text("value = 2\n", encoding="utf-8")
            if mutation == "index":
                real_run(["git", "add", "module.py"], cwd=tmp_path, check=True)
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)
    assert mutated


def test_mode_and_all_entry_evidence_are_cid_bound_and_closed(tmp_path: Path) -> None:
    _commit_module(tmp_path)
    snapshot = snapshot_repository(tmp_path)
    entry = snapshot.entries[0]
    assert "mode" in snapshot.identity_payload()
    assert RepositorySnapshot.from_dict(snapshot.to_dict()) == snapshot
    assert SnapshotEntry.from_dict(entry.to_dict()) == entry

    forged_mode = snapshot.to_dict()
    forged_mode["mode"] = "git-working"
    with pytest.raises(SnapshotError):
        RepositorySnapshot.from_dict(forged_mode)

    missing = snapshot.to_dict()
    missing.pop("git_tree")
    with pytest.raises(SnapshotError):
        RepositorySnapshot.from_dict(missing)

    unknown = snapshot.to_dict()
    unknown["unknown"] = True
    with pytest.raises(SnapshotError):
        RepositorySnapshot.from_dict(unknown)

    forged_entry = entry.to_dict()
    forged_entry["disposition"] = "tracked_modified"
    with pytest.raises(SnapshotError):
        SnapshotEntry.from_dict(forged_entry)


def test_raw_path_hex_is_canonically_bound_to_safe_and_unsafe_paths() -> None:
    source_cid = cid_for_bytes(b"x")
    safe = SnapshotEntry("safe.py", "python", 1, source_cid)
    manifest = safe.to_dict()
    manifest["path"] = "other.py"
    with pytest.raises(SnapshotError):
        SnapshotEntry.from_dict(manifest)

    uppercase_hex = safe.to_dict()
    uppercase_hex["raw_path_hex"] = uppercase_hex["raw_path_hex"].upper()
    with pytest.raises(SnapshotError):
        SnapshotEntry.from_dict(uppercase_hex)


def test_configured_exclusion_precedes_mode_bounds_and_invalid_child_enumeration(
    tmp_path: Path,
) -> None:
    _commit_module(tmp_path)
    control = tmp_path / "state" / "control"
    control.mkdir(parents=True)
    for number in range(4):
        _raw_file(control, f"ignored-{number}.py".encode())
    _raw_file(control, b"ignored-\xff.py")

    snapshot = snapshot_repository(
        tmp_path,
        exclusions=("state/control",),
        max_entries=1,
    )
    assert snapshot.mode == "git-clean"
    assert [item.path for item in snapshot.entries] == ["module.py"]


def test_excluded_only_changes_preserve_roots_and_invalid_lookalike_is_visible(
    tmp_path: Path,
) -> None:
    _commit_module(tmp_path)
    control = tmp_path / "state" / "control"
    control.mkdir(parents=True)
    state_file = control / "state.json"
    state_file.write_text('{"generation": 1}\n', encoding="utf-8")
    _git(tmp_path, "add", "state/control/state.json")
    _git(tmp_path, "commit", "-q", "-m", "tracked control state")

    first = snapshot_repository(tmp_path, exclusions=("state/control",))
    state_file.write_text('{"generation": 2}\n', encoding="utf-8")
    second = snapshot_repository(tmp_path, exclusions=("state/control",))
    assert second.mode == "git-clean"
    assert second.snapshot_cid == first.snapshot_cid

    lookalike = b".semantic-index\xff.py"
    _raw_file(tmp_path, lookalike)
    visible = snapshot_repository(tmp_path, exclusions=("state/control",))
    assert any(item.raw_path_hex == lookalike.hex() for item in visible.entries)


def test_scanner_and_convenience_entry_point_honor_configured_exclusions(
    tmp_path: Path,
) -> None:
    (tmp_path / "keep.py").write_text("keep = True\n", encoding="utf-8")
    (tmp_path / "state" / "control").mkdir(parents=True)
    (tmp_path / "state" / "control" / "drop.py").write_text(
        "drop = True\n", encoding="utf-8"
    )
    direct = RepositoryScanner(
        repository_id="repo:configured-exclusion",
        exclusions=("state/control",),
    ).scan(tmp_path)
    convenience = scan_repository_state(
        tmp_path,
        repository_id="repo:configured-exclusion",
        exclusions=("state/control",),
    )
    assert direct.state_cid == convenience.state_cid
    assert {symbol.module_path for symbol in direct.symbols} == {"keep.py"}


def test_dirty_dispositions_and_head_index_oids_are_exact(tmp_path: Path) -> None:
    _commit_module(tmp_path)
    head_oid = _git(tmp_path, "rev-parse", "HEAD:module.py").stdout.decode().strip()

    clean = _entry(snapshot_repository(tmp_path), "module.py")
    assert clean.disposition == "clean"
    assert clean.acquisition == "git-object"
    assert clean.head_blob_oid == head_oid
    assert clean.git_blob_oid == head_oid

    (tmp_path / "module.py").write_text("value = 2\n", encoding="utf-8")
    modified = _entry(snapshot_repository(tmp_path), "module.py")
    assert modified.disposition == "tracked_modified"
    assert modified.acquisition == "working-captured"
    assert modified.head_blob_oid == head_oid
    assert modified.git_blob_oid == head_oid

    _git(tmp_path, "add", "module.py")
    staged = _entry(snapshot_repository(tmp_path), "module.py")
    staged_oid = _git(tmp_path, "rev-parse", ":module.py").stdout.decode().strip()
    assert staged.disposition == "staged_modified"
    assert staged.head_blob_oid == head_oid
    assert staged.git_blob_oid == staged_oid

    (tmp_path / "new.py").write_text("new = True\n", encoding="utf-8")
    untracked = _entry(snapshot_repository(tmp_path), "new.py")
    assert untracked.disposition == "untracked"
    assert untracked.head_blob_oid is None
    assert untracked.git_blob_oid is None

    _git(tmp_path, "add", "new.py")
    staged_added = _entry(snapshot_repository(tmp_path), "new.py")
    assert staged_added.disposition == "staged_added"
    assert staged_added.head_blob_oid is None
    assert staged_added.git_blob_oid is not None


def test_staged_and_unstaged_deletions_are_retained_but_not_analyzed(
    tmp_path: Path,
) -> None:
    _commit_module(tmp_path, b"def deleted():\n    return 1\n")
    head_oid = _git(tmp_path, "rev-parse", "HEAD:module.py").stdout.decode().strip()
    (tmp_path / "module.py").unlink()

    unstaged_snapshot = snapshot_repository(tmp_path)
    unstaged = _entry(unstaged_snapshot, "module.py")
    assert unstaged.disposition == "unstaged_deleted"
    assert unstaged.is_opaque
    assert unstaged.head_blob_oid == head_oid
    assert unstaged.git_blob_oid == head_oid
    assert not RepositoryScanner().scan(tmp_path, snapshot=unstaged_snapshot).symbols

    _git(tmp_path, "add", "-u")
    staged_snapshot = snapshot_repository(tmp_path)
    staged = _entry(staged_snapshot, "module.py")
    assert staged.disposition == "staged_deleted"
    assert staged.is_opaque
    assert staged.head_blob_oid == head_oid
    assert staged.git_blob_oid is None
    assert not RepositoryScanner().scan(tmp_path, snapshot=staged_snapshot).symbols


def test_conflict_retains_index_stages_one_two_three(tmp_path: Path) -> None:
    _commit_module(tmp_path, b"value = 'base'\n")
    initial_branch = _git(tmp_path, "branch", "--show-current").stdout.decode().strip()
    _git(tmp_path, "checkout", "-q", "-b", "other")
    (tmp_path / "module.py").write_text("value = 'other'\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "other")
    _git(tmp_path, "checkout", "-q", initial_branch)
    (tmp_path / "module.py").write_text("value = 'main'\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "main")
    merge = _git(tmp_path, "merge", "other", check=False)
    assert merge.returncode != 0

    snapshot = snapshot_repository(tmp_path)
    conflict = _entry(snapshot, "module.py")
    assert conflict.disposition == "conflicted"
    assert conflict.is_opaque
    assert set(dict(conflict.index_blob_oids or ())) == {"1", "2", "3"}
    assert conflict.head_blob_oid is not None
    assert not RepositoryScanner().scan(tmp_path, snapshot=snapshot).symbols


def test_same_size_rewrite_with_restored_mtime_is_opaque_without_second_read(
    tmp_path: Path,
) -> None:
    source = tmp_path / "module.py"
    source.write_bytes(b"value = 1\n")
    snapshot = snapshot_repository(tmp_path, repository_id="repo:ctime-race")
    before = source.stat()
    time.sleep(0.01)
    source.write_bytes(b"value = 2\n")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_ctime_ns != before.st_ctime_ns

    state = RepositoryScanner(repository_id="repo:ctime-race").scan(
        tmp_path,
        snapshot=snapshot,
    )
    artifact = next(item for item in state.artifacts if item.path == "module.py")
    assert artifact.confidence == "opaque"
    assert artifact.metadata["opaque_reason"] == "source_cid_mismatch"
    assert not state.symbols


def test_raw_display_source_artifact_and_snapshot_domains_do_not_collide(
    tmp_path: Path,
) -> None:
    invalid = b"\xff.txt"
    _raw_file(tmp_path, invalid, b"invalid raw bytes name\n")
    marker = tmp_path / "@malformed-path"
    marker.mkdir()
    (marker / invalid.hex()).write_text("valid marker-like name\n", encoding="utf-8")
    nfd = "cafe\u0301.txt"
    backslash = "slash\\name.txt"
    (tmp_path / nfd).write_text("nfd\n", encoding="utf-8")
    (tmp_path / backslash).write_text("backslash\n", encoding="utf-8")
    (tmp_path / "@snapshot-evidence").write_text("ordinary file\n", encoding="utf-8")

    snapshot = snapshot_repository(tmp_path, repository_id="repo:path-domains")
    raw_ids = [item.raw_path_hex for item in snapshot.entries]
    source_keys = [item.source_key for item in snapshot.entries]
    entry_cids = [item.entry_cid for item in snapshot.entries]
    assert len(raw_ids) == len(set(raw_ids))
    assert len(source_keys) == len(set(source_keys))
    assert len(entry_cids) == len(set(entry_cids))

    safe_by_raw = {bytes.fromhex(item.raw_path_hex or ""): item for item in snapshot.entries}
    assert safe_by_raw[os.fsencode(nfd)].path == nfd
    assert safe_by_raw[os.fsencode(backslash)].path == backslash
    assert safe_by_raw[invalid].is_opaque
    assert safe_by_raw[invalid].path == f"@malformed-path/{invalid.hex()}"
    assert safe_by_raw[os.fsencode(f"@malformed-path/{invalid.hex()}")].path == safe_by_raw[invalid].path

    state = RepositoryScanner(repository_id="repo:path-domains").scan(
        tmp_path,
        snapshot=snapshot,
    )
    artifact_ids = [item.artifact_id for item in state.artifacts]
    artifact_domain_keys = [(item.kind, item.path) for item in state.artifacts]
    assert len(artifact_ids) == len(set(artifact_ids))
    assert len(artifact_domain_keys) == len(set(artifact_domain_keys))
    assert "artifact:snapshot-evidence" in artifact_ids
    assert any(item.path == "@snapshot-evidence" and item.kind == "artifact" for item in state.artifacts)
    assert any(item.metadata.get("raw_path_hex") == invalid.hex() for item in state.artifacts)


def test_restored_manifest_is_a_claim_until_exact_bytes_are_injected(
    tmp_path: Path,
) -> None:
    source = b"def answer() -> int:\n    return 42\n"
    (tmp_path / "module.py").write_bytes(source)
    captured = snapshot_repository(tmp_path, repository_id="repo:manifest-claim")
    restored = RepositorySnapshot.from_dict(captured.to_dict())
    entry = restored.entries[0]
    assert entry.captured_bytes is None

    claimed = RepositoryScanner(repository_id="repo:manifest-claim").scan(
        tmp_path,
        snapshot=restored,
    )
    assert not claimed.symbols
    opaque = next(item for item in claimed.artifacts if item.path == "module.py")
    assert opaque.metadata["opaque_reason"] == "source_bytes_unavailable"

    injected = RepositoryScanner(repository_id="repo:manifest-claim").scan_snapshot(
        restored,
        {entry.source_key: source},
    )
    assert any(symbol.qualified_name == "module.answer" for symbol in injected.symbols)

    mismatched = RepositoryScanner(repository_id="repo:manifest-claim").scan_snapshot(
        restored,
        {entry.source_key: b"def attacker():\n    return True\n"},
    )
    assert not mismatched.symbols
    mismatch = next(item for item in mismatched.artifacts if item.path == "module.py")
    assert mismatch.metadata["opaque_reason"] == "source_cid_mismatch"


def test_self_consistent_replacement_manifest_cannot_trigger_source_reopen(
    tmp_path: Path,
) -> None:
    original = b"def original():\n    return True\n"
    replacement = b"def replacement():\n    return False\n"
    (tmp_path / "module.py").write_bytes(original)
    snapshot = snapshot_repository(tmp_path, repository_id="repo:forged-claim")
    entry = replace(
        snapshot.entries[0],
        source_cid=cid_for_bytes(replacement),
        captured_bytes=None,
        witness=None,
    )
    forged = replace(snapshot, entries=(entry,))
    assert RepositorySnapshot.from_dict(forged.to_dict()) == forged

    state = RepositoryScanner(repository_id="repo:forged-claim").scan(
        tmp_path,
        snapshot=forged,
    )
    assert not state.symbols
    artifact = next(item for item in state.artifacts if item.path == "module.py")
    assert artifact.metadata["opaque_reason"] == "source_bytes_unavailable"


def test_clean_git_and_filesystem_inputs_are_read_once_across_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_repository = tmp_path / "git"
    filesystem_repository = tmp_path / "filesystem"
    _commit_module(git_repository, b"def git_source():\n    return 1\n")
    filesystem_repository.mkdir()
    filesystem_source = filesystem_repository / "module.py"
    filesystem_source.write_bytes(b"def filesystem_source():\n    return 1\n")

    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run
    blob_reads = 0

    def run(command, *args, **kwargs):
        nonlocal blob_reads
        if (
            isinstance(command, (list, tuple))
            and len(command) >= 4
            and tuple(command[:3]) == ("git", "cat-file", "blob")
        ):
            blob_reads += 1
        return real_run(command, *args, **kwargs)

    real_open = module.os.open
    filesystem_reads = 0

    def open_once(path, flags, *args, **kwargs):
        nonlocal filesystem_reads
        if Path(path) == filesystem_source and flags & os.O_RDONLY == os.O_RDONLY:
            filesystem_reads += 1
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.os, "open", open_once)
    RepositoryScanner().scan(git_repository)
    RepositoryScanner(repository_id="repo:one-read").scan(filesystem_repository)
    assert blob_reads == 1
    assert filesystem_reads == 1


def test_oversized_clean_blob_is_rejected_by_size_without_content_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit_module(tmp_path, b"x" * 32)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run
    blob_reads = 0

    def run(command, *args, **kwargs):
        nonlocal blob_reads
        if (
            isinstance(command, (list, tuple))
            and len(command) >= 4
            and tuple(command[:3]) == ("git", "cat-file", "blob")
        ):
            blob_reads += 1
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", run)
    snapshot = snapshot_repository(tmp_path, max_file_bytes=8)
    entry = _entry(snapshot, "module.py")
    assert entry.is_opaque
    assert entry.opaque_reason == "oversized"
    assert blob_reads == 0


def test_clean_smudge_filter_uses_indexed_bytes(tmp_path: Path) -> None:
    _init(tmp_path)
    _git(tmp_path, "config", "filter.audit.smudge", "sed s/indexed/smudged/g")
    _git(tmp_path, "config", "filter.audit.clean", "sed s/smudged/indexed/g")
    (tmp_path / ".gitattributes").write_text("module.py filter=audit\n", encoding="utf-8")
    (tmp_path / "module.py").write_text("value = 'indexed'\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "smudge fixture")
    (tmp_path / "module.py").unlink()
    _git(tmp_path, "checkout", "--", "module.py")
    assert b"smudged" in (tmp_path / "module.py").read_bytes()

    snapshot = snapshot_repository(tmp_path)
    module_entry = _entry(snapshot, "module.py")
    assert module_entry.captured_bytes == b"value = 'indexed'\n"
    state = RepositoryScanner().scan(tmp_path, snapshot=snapshot)
    module_symbol = next(symbol for symbol in state.symbols if symbol.qualified_name == "module")
    assert module_symbol.source_cid == cid_for_bytes(b"value = 'indexed'\n")


def test_corrupt_git_marker_never_downgrades_to_filesystem(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)


def test_quiet_head_failure_in_born_repository_is_not_unborn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit_module(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run

    def run(command, *args, **kwargs):
        if _is_git_command(command, "rev-parse", "--verify", "--quiet", "HEAD"):
            return subprocess.CompletedProcess(command, 1, b"", b"")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)


@pytest.mark.parametrize("payload", [b"", b"\xff\n"])
def test_successful_head_identity_output_must_be_nonempty_ascii_oid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    _commit_module(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run

    def run(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        if _is_git_command(command, "rev-parse", "--verify", "--quiet", "HEAD"):
            return subprocess.CompletedProcess(command, 0, payload, b"")
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        repository_identity(tmp_path)


def test_non_ascii_symbolic_head_is_a_typed_snapshot_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run

    def run(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        if _is_git_command(command, "symbolic-ref", "-q", "HEAD"):
            return subprocess.CompletedProcess(command, 0, b"\xff\n", b"")
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        repository_identity(tmp_path)


def test_successful_head_warning_fails_identity_and_snapshot_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit_module(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run

    def run(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        if _is_git_command(command, "rev-parse", "--verify", "--quiet", "HEAD"):
            return subprocess.CompletedProcess(command, 0, result.stdout, b"warning\n")
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        repository_identity(tmp_path)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)


@pytest.mark.parametrize("failure", ["nonzero", "warning"])
def test_status_nonzero_or_incomplete_traversal_warning_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    _commit_module(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run

    def run(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        if (
            isinstance(command, (list, tuple))
            and tuple(command[:3]) == ("git", "status", "--porcelain")
        ):
            if failure == "nonzero":
                return subprocess.CompletedProcess(command, 2, result.stdout, b"failed\n")
            return subprocess.CompletedProcess(command, 0, result.stdout, b"incomplete traversal\n")
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)


def test_git_execution_oserror_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    def unavailable(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(module.subprocess, "run", unavailable)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)


def test_empty_or_non_ascii_repository_root_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    for payload in (b"", b"\xff\n"):
        monkeypatch.setattr(
            module.subprocess,
            "run",
            lambda *args, payload=payload, **kwargs: subprocess.CompletedProcess(
                args[0], 0, payload, b""
            ),
        )
        with pytest.raises(GitSnapshotError):
            snapshot_repository(tmp_path)


def test_remote_is_not_an_identity_authority(tmp_path: Path) -> None:
    _commit_module(tmp_path)
    baseline = repository_identity(tmp_path)
    _git(tmp_path, "remote", "add", "origin", "file:///definitely/missing/repository")
    assert repository_identity(tmp_path) == baseline


def test_identical_and_incremental_scans_keep_deterministic_roots(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text(
        "def answer(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    first = scan_repository_state(tmp_path, repository_id="repo:deterministic")
    second = scan_repository_state(
        tmp_path,
        repository_id="repo:deterministic",
        previous_state=first,
    )
    third = scan_repository_state(tmp_path, repository_id="repo:deterministic")
    assert first.state_cid == second.state_cid == third.state_cid
