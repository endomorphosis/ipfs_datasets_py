"""Independent, test-first authority probes for repository snapshots.

This file is deliberately outside the production task's ownership.  It
exercises only public snapshot/scanner entry points while perturbing Git or
the filesystem underneath those entry points.  A provider repairing the
implementation must not edit, replace, rename, or weaken these assertions.
"""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import sys
import threading
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


def _git_metadata(repository: Path) -> Path:
    rendered = _git(repository, "rev-parse", "--git-dir").stdout.decode(
        "utf-8", "strict"
    ).strip()
    path = Path(rendered)
    if not path.is_absolute():
        path = repository / path
    return path.resolve()


def _bootstrap_marker(repository: Path) -> Path:
    return _git_metadata(repository) / ".ipfs-datasets-semantic-index-unborn-id"


def _exception_messages(error: BaseException) -> tuple[str, ...]:
    """Render an injected failure and every linked/aggregated failure once."""
    pending = [error]
    seen: set[int] = set()
    messages: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        messages.append(str(current))
        pending.extend(
            item
            for item in getattr(current, "exceptions", ())
            if isinstance(item, BaseException)
        )
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return tuple(messages)


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


def test_automatic_unborn_bootstrap_id_survives_repository_move(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    relocated_parent = tmp_path / "relocated"
    relocated = relocated_parent / "repository"
    _init(original)

    before = repository_identity(original)
    relocated_parent.mkdir()
    original.rename(relocated)

    assert repository_identity(relocated) == before


def test_concurrent_unborn_identity_reader_never_observes_partial_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_urandom = module.os.urandom
    first_generator_entered = threading.Event()
    release_first_generator = threading.Event()
    call_lock = threading.Lock()
    random_calls = 0

    def controlled_urandom(size: int) -> bytes:
        nonlocal random_calls
        with call_lock:
            random_calls += 1
            call_number = random_calls
        if call_number == 1:
            first_generator_entered.set()
            if not release_first_generator.wait(5):
                raise OSError("audit bootstrap generator timed out")
        return real_urandom(size)

    monkeypatch.setattr(module.os, "urandom", controlled_urandom)
    identities: dict[str, str] = {}
    errors: dict[str, Exception] = {}

    def identify(name: str) -> None:
        try:
            identities[name] = repository_identity(tmp_path)
        except Exception as exc:  # pragma: no branch - asserted below
            errors[name] = exc

    first = threading.Thread(target=identify, args=("first",), daemon=True)
    second = threading.Thread(target=identify, args=("second",), daemon=True)
    first.start()
    assert first_generator_entered.wait(5)
    partial_final_visible = _bootstrap_marker(tmp_path).exists()
    second.start()
    try:
        # A lock-based publisher may wait here.  A no-replace publisher may
        # instead finish and force the first publisher to reread its winner.
        second.join(0.5)
    finally:
        release_first_generator.set()
        first.join(5)
        second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not partial_final_visible
    assert errors == {}
    assert identities["first"] == identities["second"]
    assert repository_identity(tmp_path) == identities["first"]


def test_unborn_reader_waits_for_visible_final_to_be_directory_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    real_fsync = module.os.fsync
    final_directory_sync_entered = threading.Event()
    release_directory_sync = threading.Event()

    def block_visible_final_directory_sync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISDIR(mode) and marker.is_file():
            final_directory_sync_entered.set()
            if not release_directory_sync.wait(5):
                raise OSError("audit metadata-directory sync timed out")
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", block_visible_final_directory_sync)
    identities: dict[str, str] = {}
    errors: dict[str, Exception] = {}
    first_finished = threading.Event()
    second_finished = threading.Event()

    def identify(name: str, finished: threading.Event) -> None:
        try:
            identities[name] = repository_identity(tmp_path)
        except Exception as exc:  # pragma: no branch - asserted below
            errors[name] = exc
        finally:
            finished.set()

    first = threading.Thread(
        target=identify,
        args=("first", first_finished),
        daemon=True,
    )
    second = threading.Thread(
        target=identify,
        args=("second", second_finished),
        daemon=True,
    )
    first.start()
    sync_was_reached = False
    final_was_visible = False
    second_started = False
    reader_finished_before_release = False
    try:
        if first_finished.wait(0.25):
            sync_was_reached = final_directory_sync_entered.is_set()
        else:
            sync_was_reached = final_directory_sync_entered.wait(5)
        final_was_visible = marker.is_file()
        if sync_was_reached:
            second.start()
            second_started = True
            reader_finished_before_release = second_finished.wait(0.5)
    finally:
        release_directory_sync.set()
        first.join(5)
        if second_started:
            second.join(5)

    assert sync_was_reached
    assert final_was_visible
    assert second_started
    assert not reader_finished_before_release
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == {}
    assert identities["first"] == identities["second"]
    assert repository_identity(tmp_path) == identities["first"]


def test_unborn_directory_sync_failure_is_typed_and_retry_reestablishes_durability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    real_fsync = module.os.fsync
    directory_sync_attempts = 0
    successful_directory_syncs = 0
    final_visibility: list[bool] = []

    def fail_first_visible_final_directory_sync(descriptor: int) -> None:
        nonlocal directory_sync_attempts, successful_directory_syncs
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISDIR(mode) and marker.is_file():
            directory_sync_attempts += 1
            final_visibility.append(True)
            if directory_sync_attempts == 1:
                raise OSError("audit metadata-directory sync failure")
            real_fsync(descriptor)
            successful_directory_syncs += 1
            return
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_first_visible_final_directory_sync)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc

    attempts_after_failure = directory_sync_attempts
    assert isinstance(first_error, GitSnapshotError)
    assert attempts_after_failure >= 1
    assert all(final_visibility)
    assert marker.is_file()
    token = marker.read_bytes()
    assert len(token) == 64
    assert all(byte in b"0123456789abcdef" for byte in token)

    recovered = repository_identity(tmp_path)
    assert directory_sync_attempts > attempts_after_failure
    assert successful_directory_syncs >= 1
    assert repository_identity(tmp_path) == recovered


def test_unborn_restart_cleans_stale_temporary_and_avoids_pid_reuse_collision(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    marker = _bootstrap_marker(tmp_path)
    program = "\n".join(
        (
            "import os",
            "import sys",
            "from pathlib import Path",
            "repository = Path(sys.argv[1])",
            "marker = Path(sys.argv[2])",
            "stale_candidates = (",
            "    marker.parent / f'.{marker.name}.tmp-{os.getpid()}-0',",
            "    marker.parent / f'.{marker.name}.tmp-crashed-writer-7',",
            ")",
            "for stale in stale_candidates:",
            "    descriptor = os.open(stale, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)",
            "    try:",
            "        os.write(descriptor, b'partial-crashed-candidate')",
            "        os.fsync(descriptor)",
            "    finally:",
            "        os.close(descriptor)",
            "from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import GitSnapshotError, repository_identity",
            "try:",
            "    first = repository_identity(repository)",
            "except GitSnapshotError as exc:",
            "    print(f'typed failure instead of recovery: {exc}', file=sys.stderr)",
            "    raise SystemExit(31)",
            "except Exception as exc:",
            "    print(f'untyped failure instead of recovery: {type(exc).__name__}: {exc}', file=sys.stderr)",
            "    raise SystemExit(32)",
            "if not marker.is_file():",
            "    print('final marker was not published', file=sys.stderr)",
            "    raise SystemExit(33)",
            "residue = [str(stale) for stale in stale_candidates if stale.exists()]",
            "if residue:",
            "    print(f'stale candidates survived successful recovery: {residue}', file=sys.stderr)",
            "    raise SystemExit(34)",
            "if repository_identity(repository) != first:",
            "    print('recovered identity was unstable', file=sys.stderr)",
            "    raise SystemExit(35)",
        )
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    recovered = subprocess.run(
        [sys.executable, "-B", "-c", program, str(tmp_path), str(marker)],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=10,
    )

    assert recovered.returncode == 0, recovered.stderr.decode("utf-8", "replace")
    assert marker.is_file()
    assert repository_identity(tmp_path) == repository_identity(tmp_path)


def test_unborn_post_publication_cleanup_failure_is_typed_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    real_unlink = module.os.unlink
    real_fsync = module.os.fsync
    cleanup_attempts: list[Path] = []
    final_was_visible: list[bool] = []
    final_was_durable: list[bool] = []
    metadata_directory_synced = False

    def record_sync(descriptor: int) -> None:
        nonlocal metadata_directory_synced
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            metadata_directory_synced = True
        real_fsync(descriptor)

    def fail_candidate_cleanup(path, *args, **kwargs) -> None:
        candidate = Path(os.fsdecode(os.fspath(path)))
        if candidate.parent == marker.parent and marker.name in candidate.name:
            cleanup_attempts.append(candidate)
            final_was_visible.append(marker.is_file())
            final_was_durable.append(metadata_directory_synced)
            raise OSError("audit temporary cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", record_sync)
    monkeypatch.setattr(module.os, "unlink", fail_candidate_cleanup)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc

    assert cleanup_attempts
    assert all(final_was_visible)
    assert all(final_was_durable)
    assert isinstance(first_error, GitSnapshotError)
    assert marker.is_file()

    monkeypatch.setattr(module.os, "unlink", real_unlink)
    recovered = repository_identity(tmp_path)
    assert repository_identity(tmp_path) == recovered
    assert all(not candidate.exists() for candidate in cleanup_attempts)


def test_existing_unborn_winner_syncs_directory_after_stale_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    marker.write_bytes(b"c" * 64)
    marker.chmod(0o600)
    stale = marker.parent / f".{marker.name}.tmp-crashed-writer-19"
    stale.write_bytes(b"partial-crashed-candidate")
    stale.chmod(0o600)

    real_fsync = module.os.fsync
    real_unlink = module.os.unlink
    events: list[str] = []

    def record_sync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            events.append("directory_sync")
        real_fsync(descriptor)

    def record_unlink(path, *args, **kwargs) -> None:
        if Path(os.fsdecode(os.fspath(path))) == stale:
            events.append("stale_unlink")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", record_sync)
    monkeypatch.setattr(module.os, "unlink", record_unlink)

    first = repository_identity(tmp_path)

    assert not stale.exists()
    cleanup_index = events.index("stale_unlink")
    assert "directory_sync" in events[:cleanup_index]
    assert "directory_sync" in events[cleanup_index + 1 :]
    assert repository_identity(tmp_path) == first


def test_concurrent_first_publishers_do_not_reap_a_live_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    real_fsync = module.os.fsync
    first_candidate_synced = threading.Event()
    release_first_publisher = threading.Event()
    visibility_at_first_file_sync: list[bool] = []

    def pause_first_publisher_after_file_sync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        real_fsync(descriptor)
        if (
            threading.current_thread().name == "audit-first-publisher"
            and stat.S_ISREG(mode)
            and not first_candidate_synced.is_set()
        ):
            visibility_at_first_file_sync.append(marker.exists())
            first_candidate_synced.set()
            if not release_first_publisher.wait(5):
                raise OSError("audit first publisher timed out")

    monkeypatch.setattr(module.os, "fsync", pause_first_publisher_after_file_sync)
    identities: dict[str, str] = {}
    errors: dict[str, Exception] = {}
    second_finished = threading.Event()

    def identify(name: str) -> None:
        try:
            identities[name] = repository_identity(tmp_path)
        except Exception as exc:  # pragma: no branch - asserted below
            errors[name] = exc
        finally:
            if name == "second":
                second_finished.set()

    first = threading.Thread(
        target=identify,
        args=("first",),
        name="audit-first-publisher",
        daemon=True,
    )
    second = threading.Thread(
        target=identify,
        args=("second",),
        name="audit-second-publisher",
        daemon=True,
    )
    first.start()
    assert first_candidate_synced.wait(5)
    second.start()
    try:
        # A no-replace publisher may finish here; a lock-based publisher may
        # wait. Detect final visibility without requiring either strategy.
        deadline = time.monotonic() + 2
        while not marker.exists() and second.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
        if marker.exists():
            # If the second no-lock publisher made the winner visible, let it
            # finish its cleanup before releasing the first. A sound publisher
            # must not classify that first caller's still-live candidate as
            # crash residue. A lock-based implementation never enters here.
            second_finished.wait(2)
    finally:
        release_first_publisher.set()
        first.join(5)
        second.join(5)

    assert visibility_at_first_file_sync == [False]
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == {}
    assert identities["first"] == identities["second"]
    temporary_prefix = f".{marker.name}.tmp-"
    assert not any(item.name.startswith(temporary_prefix) for item in marker.parent.iterdir())
    assert repository_identity(tmp_path) == identities["first"]


def test_unborn_stale_cleanup_is_bounded_per_call_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    # This is an oracle ceiling, not a required implementation strategy. A
    # smaller production batch, a bounded quarantine, or another fail-closed
    # scheme is acceptable as long as no public call exceeds this work bound.
    max_cleanup_operations = 256
    marker = _bootstrap_marker(tmp_path)
    marker.write_bytes(b"d" * 64)
    marker.chmod(0o600)
    temporary_prefix = f".{marker.name}.tmp-"
    for index in range(max_cleanup_operations + 17):
        stale = marker.parent / f"{temporary_prefix}crashed-{index:04d}"
        stale.write_bytes(b"partial")
        stale.chmod(0o600)

    real_unlink = module.os.unlink
    real_remove = module.os.remove
    cleanup_operations = 0

    def count_cleanup(function, path, *args, **kwargs) -> None:
        nonlocal cleanup_operations
        candidate = Path(os.fsdecode(os.fspath(path)))
        if candidate.parent == marker.parent and candidate.name.startswith(temporary_prefix):
            cleanup_operations += 1
        function(path, *args, **kwargs)

    def count_unlink(path, *args, **kwargs) -> None:
        count_cleanup(real_unlink, path, *args, **kwargs)

    def count_remove(path, *args, **kwargs) -> None:
        count_cleanup(real_remove, path, *args, **kwargs)

    monkeypatch.setattr(module.os, "unlink", count_unlink)
    monkeypatch.setattr(module.os, "remove", count_remove)
    per_call_cleanup: list[int] = []
    typed_failures: list[GitSnapshotError] = []
    identity: str | None = None

    for _attempt in range(8):
        cleanup_operations = 0
        try:
            identity = repository_identity(tmp_path)
        except GitSnapshotError as exc:
            typed_failures.append(exc)
        per_call_cleanup.append(cleanup_operations)
        assert cleanup_operations <= max_cleanup_operations
        if identity is not None:
            break

    assert typed_failures
    assert identity is not None
    assert not any(item.name.startswith(temporary_prefix) for item in marker.parent.iterdir())
    assert repository_identity(tmp_path) == identity
    assert all(count <= max_cleanup_operations for count in per_call_cleanup)


def test_unborn_write_and_cleanup_failure_is_typed_then_restart_recovers(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    marker = _bootstrap_marker(tmp_path)
    program = "\n".join(
        (
            "import os",
            "import resource",
            "import signal",
            "import sys",
            "from pathlib import Path",
            "import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module",
            "from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import GitSnapshotError, repository_identity",
            "repository = Path(sys.argv[1])",
            "marker = Path(sys.argv[2])",
            "prefix = f'.{marker.name}.tmp-'",
            "real_unlink = module.os.unlink",
            "cleanup_attempts = []",
            "def fail_candidate_cleanup(path, *args, **kwargs):",
            "    candidate = Path(os.fsdecode(os.fspath(path)))",
            "    if candidate.parent == marker.parent and candidate.name.startswith(prefix):",
            "        cleanup_attempts.append(candidate)",
            "        raise OSError('audit prepublication cleanup failure')",
            "    return real_unlink(path, *args, **kwargs)",
            "module.os.unlink = fail_candidate_cleanup",
            "signal.signal(signal.SIGXFSZ, signal.SIG_IGN)",
            "resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))",
            "try:",
            "    repository_identity(repository)",
            "except GitSnapshotError as exc:",
            "    pending = [exc]",
            "    seen = set()",
            "    messages = []",
            "    while pending:",
            "        current = pending.pop()",
            "        if id(current) in seen:",
            "            continue",
            "        seen.add(id(current))",
            "        messages.append(str(current))",
            "        nested = getattr(current, 'exceptions', ())",
            "        pending.extend(item for item in nested if isinstance(item, BaseException))",
            "        for linked in (current.__cause__, current.__context__):",
            "            if linked is not None:",
            "                pending.append(linked)",
            "    residue = [item for item in marker.parent.iterdir() if item.name.startswith(prefix)]",
            "    cleanup_was_surfaced = any('audit prepublication cleanup failure' in message for message in messages)",
            "    if marker.exists() or not cleanup_attempts or not residue or not cleanup_was_surfaced:",
            "        raise SystemExit(31)",
            "    raise SystemExit(23)",
            "except Exception as exc:",
            "    print(f'{type(exc).__name__}: {exc}', file=sys.stderr)",
            "    raise SystemExit(24)",
            "raise SystemExit(25)",
        )
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    interrupted = subprocess.run(
        [sys.executable, "-B", "-c", program, str(tmp_path), str(marker)],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=10,
    )

    assert interrupted.returncode == 23, interrupted.stderr.decode(
        "utf-8", "replace"
    )
    assert not marker.exists()
    recovered = repository_identity(tmp_path)
    temporary_prefix = f".{marker.name}.tmp-"
    assert not any(item.name.startswith(temporary_prefix) for item in marker.parent.iterdir())
    assert repository_identity(tmp_path) == recovered


def test_unborn_cleanup_bounds_discovery_and_inspection_not_only_unlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    # Materialising/listing an arbitrary-sized metadata directory is already
    # unbounded work even if a later loop limits successful unlink calls.
    max_inspections = 256
    marker = _bootstrap_marker(tmp_path)
    marker.write_bytes(b"e" * 64)
    marker.chmod(0o600)
    temporary_prefix = f".{marker.name}.tmp-"
    for index in range(max_inspections + 37):
        stale = marker.parent / f"{temporary_prefix}bounded-discovery-{index:04d}"
        stale.write_bytes(b"partial")
        stale.chmod(0o600)

    real_listdir = module.os.listdir
    real_scandir = module.os.scandir
    inspections = 0

    def is_metadata_directory(path: object) -> bool:
        if isinstance(path, int):
            return False
        try:
            return Path(os.fsdecode(os.fspath(path))) == marker.parent
        except TypeError:
            return False

    def audited_listdir(path, *args, **kwargs):
        nonlocal inspections
        names = real_listdir(path, *args, **kwargs)
        if is_metadata_directory(path):
            inspections += len(names)
        return names

    class AuditedScandir:
        def __init__(self, delegate) -> None:
            self._delegate = delegate

        def __enter__(self):
            self._delegate.__enter__()
            return self

        def __exit__(self, *args):
            return self._delegate.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal inspections
            item = next(self._delegate)
            inspections += 1
            return item

        def close(self) -> None:
            self._delegate.close()

    def audited_scandir(path):
        delegate = real_scandir(path)
        if is_metadata_directory(path):
            return AuditedScandir(delegate)
        return delegate

    monkeypatch.setattr(module.os, "listdir", audited_listdir)
    monkeypatch.setattr(module.os, "scandir", audited_scandir)
    per_call_inspections: list[int] = []
    typed_failures: list[GitSnapshotError] = []
    identity: str | None = None

    for _attempt in range(8):
        inspections = 0
        try:
            identity = repository_identity(tmp_path)
        except GitSnapshotError as exc:
            typed_failures.append(exc)
        per_call_inspections.append(inspections)
        if identity is not None:
            break

    residue = [
        name for name in real_listdir(marker.parent) if name.startswith(temporary_prefix)
    ]

    assert typed_failures
    assert identity is not None
    assert residue == []
    assert all(count <= max_inspections for count in per_call_inspections)
    assert repository_identity(tmp_path) == identity


@pytest.mark.parametrize("scenario", ("symlink", "fifo", "nonprivate"))
def test_unsafe_marker_derived_residue_fails_typed_and_bounded(
    tmp_path: Path,
    scenario: str,
) -> None:
    _init(tmp_path)
    marker = _bootstrap_marker(tmp_path)
    marker.write_bytes(b"f" * 64)
    marker.chmod(0o600)
    residue = marker.parent / f".{marker.name}.tmp-audit-{scenario}"
    if scenario == "symlink":
        target = marker.parent / "audit-temporary-symlink-target"
        target.write_bytes(b"partial")
        target.chmod(0o600)
        residue.symlink_to(target.name)
    elif scenario == "fifo":
        os.mkfifo(residue, 0o600)
    else:
        residue.write_bytes(b"partial")
        residue.chmod(0o644)

    program = "\n".join(
        (
            "import sys",
            "from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import GitSnapshotError, repository_identity",
            "try:",
            "    repository_identity(sys.argv[1])",
            "except GitSnapshotError:",
            "    raise SystemExit(21)",
            "except Exception as exc:",
            "    print(f'{type(exc).__name__}: {exc}', file=sys.stderr)",
            "    raise SystemExit(22)",
            "print('unsafe temporary residue was silently accepted', file=sys.stderr)",
            "raise SystemExit(23)",
        )
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", program, str(tmp_path)],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        result: int | str = "timeout"
        diagnostic = "temporary-residue validation blocked"
    else:
        result = completed.returncode
        diagnostic = completed.stderr.decode("utf-8", "replace")

    assert result == 21, diagnostic


def test_unreadable_marker_derived_residue_cannot_be_skipped_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    marker.write_bytes(b"0" * 64)
    marker.chmod(0o600)
    residue = marker.parent / f".{marker.name}.tmp-audit-unreadable"
    residue.write_bytes(b"partial")
    residue.chmod(0o600)
    real_open = module.os.open
    denied = False

    def deny_residue_open(path, flags, *args, **kwargs):
        nonlocal denied
        candidate = Path(os.fsdecode(os.fspath(path)))
        if candidate == residue:
            denied = True
            raise PermissionError("audit temporary inspection failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", deny_residue_open)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc

    monkeypatch.setattr(module.os, "open", real_open)
    if os.path.lexists(residue):
        os.unlink(residue)
    recovered = repository_identity(tmp_path)

    assert denied
    assert isinstance(first_error, GitSnapshotError)
    assert repository_identity(tmp_path) == recovered


def test_file_exists_loser_cleanup_failure_is_typed_then_retry_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    temporary_prefix = f".{marker.name}.tmp-"
    real_open = module.os.open
    real_unlink = module.os.unlink
    real_fsync = module.os.fsync
    real_close = module.os.close
    candidate_path: Path | None = None
    winner_created = False
    cleanup_attempts = 0

    def create_durable_winner() -> None:
        winner = real_open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            payload = b"1" * 64
            written = 0
            while written < len(payload):
                written += os.write(winner, payload[written:])
            real_fsync(winner)
        finally:
            real_close(winner)
        directory = real_open(
            marker.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            real_fsync(directory)
        finally:
            real_close(directory)

    def race_after_candidate_open(path, flags, *args, **kwargs):
        nonlocal candidate_path, winner_created
        descriptor = real_open(path, flags, *args, **kwargs)
        candidate = Path(os.fsdecode(os.fspath(path)))
        if (
            candidate.parent == marker.parent
            and candidate.name.startswith(temporary_prefix)
            and flags & os.O_CREAT
            and flags & os.O_EXCL
            and not winner_created
        ):
            candidate_path = candidate
            create_durable_winner()
            winner_created = True
        return descriptor

    def fail_first_loser_cleanup(path, *args, **kwargs) -> None:
        nonlocal cleanup_attempts
        candidate = Path(os.fsdecode(os.fspath(path)))
        if candidate_path is not None and candidate == candidate_path:
            cleanup_attempts += 1
            if cleanup_attempts == 1:
                raise OSError("audit FileExists loser cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", race_after_candidate_open)
    monkeypatch.setattr(module.os, "unlink", fail_first_loser_cleanup)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc

    monkeypatch.setattr(module.os, "open", real_open)
    monkeypatch.setattr(module.os, "unlink", real_unlink)
    recovered = repository_identity(tmp_path)
    residue = [
        item
        for item in marker.parent.iterdir()
        if item.name.startswith(temporary_prefix)
    ]

    assert winner_created
    assert candidate_path is not None
    assert cleanup_attempts >= 1
    assert isinstance(first_error, GitSnapshotError)
    assert any(
        "audit FileExists loser cleanup failure" in message
        for message in _exception_messages(first_error)
    )
    assert residue == []
    assert repository_identity(tmp_path) == recovered


@pytest.mark.parametrize("failure_point", ("unlock", "close"))
def test_publish_lock_finalization_failure_is_typed_and_recoverable_when_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    real_open = module.os.open
    real_close = module.os.close
    real_flock = fcntl.flock
    lock_descriptor: int | None = None
    injected = False
    diagnostic = f"audit publish lock {failure_point} failure"

    def record_lock_open(path, flags, *args, **kwargs):
        nonlocal lock_descriptor
        descriptor = real_open(path, flags, *args, **kwargs)
        candidate = Path(os.fsdecode(os.fspath(path)))
        if (
            candidate.parent == marker.parent
            and candidate != marker
            and flags & os.O_CREAT
            and not flags & os.O_EXCL
        ):
            lock_descriptor = descriptor
        return descriptor

    def fail_unlock(descriptor: int, operation: int) -> None:
        nonlocal injected
        if (
            failure_point == "unlock"
            and descriptor == lock_descriptor
            and operation == fcntl.LOCK_UN
            and not injected
        ):
            real_flock(descriptor, operation)
            injected = True
            raise OSError(diagnostic)
        real_flock(descriptor, operation)

    def fail_lock_close(descriptor: int) -> None:
        nonlocal injected
        if (
            failure_point == "close"
            and descriptor == lock_descriptor
            and not injected
        ):
            real_close(descriptor)
            injected = True
            raise OSError(diagnostic)
        real_close(descriptor)

    monkeypatch.setattr(module.os, "open", record_lock_open)
    monkeypatch.setattr(module.os, "close", fail_lock_close)
    monkeypatch.setattr(fcntl, "flock", fail_unlock)
    first_identity: str | None = None
    first_error: Exception | None = None
    try:
        first_identity = repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted conditionally below
        first_error = exc

    monkeypatch.setattr(module.os, "open", real_open)
    monkeypatch.setattr(module.os, "close", real_close)
    monkeypatch.setattr(fcntl, "flock", real_flock)
    recovered = repository_identity(tmp_path)

    if injected:
        assert isinstance(first_error, GitSnapshotError)
        assert any(diagnostic in message for message in _exception_messages(first_error))
    else:
        # A lock-free no-replace design has no lock-finalization obligation to
        # inject; its ordinary result remains acceptable.
        assert first_error is None
        assert first_identity == recovered
    assert repository_identity(tmp_path) == recovered


def test_primary_and_candidate_close_failures_preserve_both_typed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    temporary_prefix = f".{marker.name}.tmp-"
    real_open = module.os.open
    real_fsync = module.os.fsync
    real_close = module.os.close
    candidate_descriptor: int | None = None
    candidate_path: Path | None = None
    sync_failed = False
    close_failed = False

    def record_candidate_open(path, flags, *args, **kwargs):
        nonlocal candidate_descriptor, candidate_path
        descriptor = real_open(path, flags, *args, **kwargs)
        candidate = Path(os.fsdecode(os.fspath(path)))
        if (
            candidate.parent == marker.parent
            and candidate.name.startswith(temporary_prefix)
            and flags & os.O_CREAT
            and flags & os.O_EXCL
        ):
            candidate_descriptor = descriptor
            candidate_path = candidate
        return descriptor

    def fail_candidate_sync(descriptor: int) -> None:
        nonlocal sync_failed
        if descriptor == candidate_descriptor and not sync_failed:
            sync_failed = True
            raise OSError("audit candidate primary sync failure")
        real_fsync(descriptor)

    def fail_candidate_close(descriptor: int) -> None:
        nonlocal close_failed
        if descriptor == candidate_descriptor and sync_failed and not close_failed:
            real_close(descriptor)
            close_failed = True
            raise OSError("audit candidate close failure")
        real_close(descriptor)

    monkeypatch.setattr(module.os, "open", record_candidate_open)
    monkeypatch.setattr(module.os, "fsync", fail_candidate_sync)
    monkeypatch.setattr(module.os, "close", fail_candidate_close)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc

    monkeypatch.setattr(module.os, "open", real_open)
    monkeypatch.setattr(module.os, "fsync", real_fsync)
    monkeypatch.setattr(module.os, "close", real_close)
    recovered = repository_identity(tmp_path)
    messages = _exception_messages(first_error) if first_error is not None else ()

    assert candidate_path is not None
    assert sync_failed
    assert close_failed
    assert isinstance(first_error, GitSnapshotError)
    assert any("audit candidate primary sync failure" in message for message in messages)
    assert any("audit candidate close failure" in message for message in messages)
    assert not os.path.lexists(candidate_path)
    assert repository_identity(tmp_path) == recovered


def test_prepublication_stale_cleanup_is_followed_by_directory_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    temporary_prefix = f".{marker.name}.tmp-"
    real_open = module.os.open
    real_fsync = module.os.fsync
    real_unlink = module.os.unlink
    candidate_descriptor: int | None = None
    candidate_path: Path | None = None
    sync_failed = False
    events: list[str] = []

    def record_candidate_open(path, flags, *args, **kwargs):
        nonlocal candidate_descriptor, candidate_path
        descriptor = real_open(path, flags, *args, **kwargs)
        candidate = Path(os.fsdecode(os.fspath(path)))
        if (
            candidate.parent == marker.parent
            and candidate.name.startswith(temporary_prefix)
            and flags & os.O_CREAT
            and flags & os.O_EXCL
        ):
            candidate_descriptor = descriptor
            candidate_path = candidate
        return descriptor

    def fail_candidate_sync(descriptor: int) -> None:
        nonlocal sync_failed
        if descriptor == candidate_descriptor and not sync_failed:
            sync_failed = True
            events.append("candidate_sync_failure")
            raise OSError("audit prepublication candidate sync failure")
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            events.append("directory_sync")
        real_fsync(descriptor)

    def record_candidate_unlink(path, *args, **kwargs) -> None:
        candidate = Path(os.fsdecode(os.fspath(path)))
        if candidate_path is not None and candidate == candidate_path:
            events.append("candidate_unlink")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", record_candidate_open)
    monkeypatch.setattr(module.os, "fsync", fail_candidate_sync)
    monkeypatch.setattr(module.os, "unlink", record_candidate_unlink)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc

    monkeypatch.setattr(module.os, "open", real_open)
    monkeypatch.setattr(module.os, "fsync", real_fsync)
    monkeypatch.setattr(module.os, "unlink", real_unlink)
    recovered = repository_identity(tmp_path)

    assert candidate_path is not None
    assert sync_failed
    assert isinstance(first_error, GitSnapshotError)
    cleanup_index = events.index("candidate_unlink")
    assert "directory_sync" in events[cleanup_index + 1 :]
    assert not os.path.lexists(candidate_path)
    assert repository_identity(tmp_path) == recovered


def test_unborn_entropy_failure_is_typed_cleans_up_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    before = {item.name for item in marker.parent.iterdir()}
    real_urandom = module.os.urandom
    failed = False

    def fail_once(size: int) -> bytes:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("audit entropy failure")
        return real_urandom(size)

    monkeypatch.setattr(module.os, "urandom", fail_once)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc
    published_after_failure = marker.exists()
    residue = {item.name for item in marker.parent.iterdir()} - before

    retry: str | None = None
    retry_error: Exception | None = None
    try:
        retry = repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        retry_error = exc

    assert failed
    assert isinstance(first_error, GitSnapshotError)
    assert not published_after_failure
    assert all("lock" in name.casefold() for name in residue)
    assert retry_error is None
    assert retry is not None
    assert repository_identity(tmp_path) == retry


def test_unborn_write_failure_is_typed_and_restart_recovers(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    marker = _bootstrap_marker(tmp_path)
    before = {item.name for item in marker.parent.iterdir()}
    program = "\n".join(
        (
            "import resource",
            "import signal",
            "import sys",
            "from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import GitSnapshotError, repository_identity",
            "signal.signal(signal.SIGXFSZ, signal.SIG_IGN)",
            "resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))",
            "try:",
            "    repository_identity(sys.argv[1])",
            "except GitSnapshotError:",
            "    raise SystemExit(23)",
            "except Exception:",
            "    raise SystemExit(24)",
            "raise SystemExit(25)",
        )
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    interrupted = subprocess.run(
        [sys.executable, "-B", "-c", program, str(tmp_path)],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=10,
    )
    published_after_failure = marker.exists()
    residue = {item.name for item in marker.parent.iterdir()} - before

    retry: str | None = None
    retry_error: Exception | None = None
    try:
        retry = repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        retry_error = exc

    assert interrupted.returncode == 23, interrupted.stderr.decode(
        "utf-8", "replace"
    )
    assert not published_after_failure
    assert all("lock" in name.casefold() for name in residue)
    assert retry_error is None
    assert retry is not None
    assert repository_identity(tmp_path) == retry


def test_unborn_file_sync_interruption_is_typed_and_restart_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    before = {item.name for item in marker.parent.iterdir()}
    real_fsync = module.os.fsync
    interrupted = False

    def interrupt_first_file_sync(descriptor: int) -> None:
        nonlocal interrupted
        if not interrupted and stat.S_ISREG(os.fstat(descriptor).st_mode):
            interrupted = True
            raise InterruptedError("audit file sync interruption")
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", interrupt_first_file_sync)
    first_error: Exception | None = None
    try:
        repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        first_error = exc
    published_after_failure = marker.exists()
    residue = {item.name for item in marker.parent.iterdir()} - before
    monkeypatch.setattr(module.os, "fsync", real_fsync)

    retry: str | None = None
    retry_error: Exception | None = None
    try:
        retry = repository_identity(tmp_path)
    except Exception as exc:  # pragma: no branch - asserted below
        retry_error = exc

    assert interrupted
    assert isinstance(first_error, GitSnapshotError)
    assert not published_after_failure
    assert all("lock" in name.casefold() for name in residue)
    assert retry_error is None
    assert retry is not None
    assert repository_identity(tmp_path) == retry


def test_unborn_bootstrap_publication_syncs_file_and_git_metadata_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    real_fsync = module.os.fsync
    real_unlink = module.os.unlink
    events: list[str] = []

    def record_sync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISREG(mode):
            events.append("file_sync")
        elif stat.S_ISDIR(mode):
            events.append("directory_sync")
        real_fsync(descriptor)

    def record_unlink(path, *args, **kwargs) -> None:
        candidate = Path(os.fsdecode(os.fspath(path)))
        if candidate.parent == marker.parent and marker.name in candidate.name:
            events.append("temporary_unlink")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", record_sync)
    monkeypatch.setattr(module.os, "unlink", record_unlink)
    first = repository_identity(tmp_path)

    assert "file_sync" in events
    assert "temporary_unlink" in events
    cleanup_index = events.index("temporary_unlink")
    assert "directory_sync" in events[:cleanup_index]
    assert "directory_sync" in events[cleanup_index + 1 :]
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert repository_identity(tmp_path) == first


def test_existing_unborn_marker_rejects_symlink_fifo_and_nonprivate_file(
    tmp_path: Path,
) -> None:
    program = "\n".join(
        (
            "import sys",
            "from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import GitSnapshotError, repository_identity",
            "try:",
            "    repository_identity(sys.argv[1])",
            "except GitSnapshotError:",
            "    raise SystemExit(21)",
            "except Exception as exc:",
            "    print(f'{type(exc).__name__}: {exc}', file=sys.stderr)",
            "    raise SystemExit(22)",
            "print('unsafe marker was accepted', file=sys.stderr)",
            "raise SystemExit(23)",
        )
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    results: dict[str, object] = {}
    diagnostics: dict[str, str] = {}

    for scenario in ("symlink", "fifo", "nonprivate"):
        repository = tmp_path / scenario
        _init(repository)
        marker = _bootstrap_marker(repository)
        if scenario == "symlink":
            target = marker.parent / "audit-bootstrap-token-target"
            target.write_bytes(b"a" * 64)
            target.chmod(0o600)
            marker.symlink_to(target.name)
        elif scenario == "fifo":
            os.mkfifo(marker, 0o600)
        else:
            marker.write_bytes(b"b" * 64)
            marker.chmod(0o644)

        try:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", program, str(repository)],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            results[scenario] = "timeout"
        else:
            results[scenario] = completed.returncode
            diagnostics[scenario] = completed.stderr.decode("utf-8", "replace")

    assert results == {
        "symlink": 21,
        "fifo": 21,
        "nonprivate": 21,
    }, diagnostics


def test_explicit_unborn_identity_avoids_bootstrap_metadata_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    marker = _bootstrap_marker(tmp_path)
    before = {item.name for item in marker.parent.iterdir()}

    def forbidden_urandom(size: int) -> bytes:
        raise AssertionError(f"unexpected bootstrap entropy request for {size} bytes")

    monkeypatch.setattr(module.os, "urandom", forbidden_urandom)
    explicit = "repo:caller-supplied-unborn"
    original_mode = stat.S_IMODE(marker.parent.stat().st_mode)
    marker.parent.chmod(original_mode & ~0o222)
    try:
        assert repository_identity(tmp_path, repository_id=explicit) == explicit
        snapshot = snapshot_repository(tmp_path, repository_id=explicit)
    finally:
        marker.parent.chmod(original_mode)

    assert snapshot.repository_id == explicit
    assert snapshot.mode == "git-unborn"
    assert not marker.exists()
    assert {item.name for item in marker.parent.iterdir()} == before


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


def test_unborn_to_born_transition_between_identity_and_snapshot_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path)
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as module

    real_run = module.subprocess.run
    committed = False

    def run(command, *args, **kwargs):
        nonlocal committed
        result = real_run(command, *args, **kwargs)
        if (
            not committed
            and _is_git_command(command, "rev-list", "--max-count=1", "HEAD")
            and result.returncode != 0
        ):
            real_run(["git", "add", "module.py"], cwd=tmp_path, check=True)
            real_run(
                ["git", "commit", "-q", "-m", "first"],
                cwd=tmp_path,
                check=True,
            )
            committed = True
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(GitSnapshotError):
        snapshot_repository(tmp_path)
    assert committed


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
