"""Explicit frozen-source capsules at the canonical paths; never a Lean admit.

The snapshot is separate from editable source. Rootless Docker mounts it at the
original absolute paths, so normal tree pins and complete producer hashes still
apply. Host changes to the backing capsule remain detectable by those hashes;
this is concurrency isolation, not a security boundary against the host owner.
"""
from __future__ import annotations

import hashlib
import fcntl
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

SCHEMA = "autoencoder-frozen-source/v1"
MANIFEST_ENV = "IPFS_DATASETS_FROZEN_SOURCE_MANIFEST"
DIGEST_ENV = "IPFS_DATASETS_FROZEN_SOURCE_SHA256"
SCHEDULER_ENV = "IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 30_000
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_EXTRA_FILES = 32
FONT_ALIAS = "static/admin/webfonts"
FONT_SUFFIXES = {".woff", ".woff2", ".ttf", ".eot"}
IMAGE = "sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517"


class SourceSnapshotError(RuntimeError):
    """Source, namespace, resource identity or lifecycle could not be verified."""


def canonical_root():
    return Path(__file__).absolute().parents[3]


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _path(value, *, missing=False):
    path = Path(os.path.abspath(os.fspath(value)))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing and part == path:
                return path
            raise SourceSnapshotError(f"missing path: {part}") from None
        if stat.S_ISLNK(info.st_mode):
            raise SourceSnapshotError(f"aliased path: {part}")
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise SourceSnapshotError(f"non-directory ancestor: {part}")
    return path


def _read(path, limit=MAX_MANIFEST_BYTES):
    path = _path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise SourceSnapshotError(f"not a bounded unaliased regular file: {path}")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(data) > limit or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise SourceSnapshotError(f"file changed while reading: {path}")
    return data


def _write(path, value):
    raw = _json(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _sync(directory):
    for parent, _, _ in os.walk(directory, topdown=False):
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _identity(path):
    path = _path(path)
    info = path.stat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _git(root):
    environment = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        environment.pop(key, None)
    def run(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                timeout=20, env=environment, check=True)
        if len(result.stdout) > 64 * 1024 * 1024:
            raise SourceSnapshotError("Git provenance exceeds bound")
        return result.stdout
    return {"root": run("rev-parse", "--show-toplevel").decode().strip(),
            "head": run("rev-parse", "HEAD").decode().strip(),
            "status_sha256": _sha(run("status", "--porcelain=v1", "--untracked-files=all")),
            "tracked_diff_sha256": _sha(run("diff", "HEAD", "--binary")),
            "untracked_source_contents": "included in complete captured file inventory"}


def _bindings(root, extra_files=(), *, verify_live=True):
    absolute = lambda value: Path(os.path.abspath(os.fspath(value)))
    root = _path(root) if verify_live else absolute(root)
    workspace = root.parents[1]
    sources = [(root / "ipfs_datasets_py", "package"),
               (root / "scripts/ops/legal_ir", "scripts"),
               (workspace / "JevOps/jevops", "jevops")]
    if len(extra_files) > MAX_EXTRA_FILES:
        raise SourceSnapshotError("too many extra harness files")
    for index, item in enumerate(extra_files):
        item = _path(item) if verify_live else absolute(item)
        if workspace not in item.parents or item.suffix != ".py" or (verify_live and not item.is_file()):
            raise SourceSnapshotError("extra harness must be a workspace Python file")
        if any(item == source or source in item.parents for source, _ in sources):
            raise SourceSnapshotError("extra harness overlaps an existing binding")
        sources.append((item, f"extra-{index}"))
    if len({str(path) for path, _ in sources}) != len(sources):
        raise SourceSnapshotError("duplicate source binding")
    return [{"source": str(_path(source) if verify_live else source), "snapshot": f"sources/{label}",
             "kind": "file" if label.startswith("extra-") else "directory"} for source, label in sources]


def _inventory(bindings, max_bytes):
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1_000_000_000:
        raise SourceSnapshotError("source byte ceiling must be 1..1000000000")
    entries, aliases, total = [], [], 0
    def add(actual, source, relative, *, font=False):
        nonlocal total
        info = actual.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SourceSnapshotError(f"source must be regular without hardlinks: {actual}")
        if font and (actual.suffix.lower() not in FONT_SUFFIXES or info.st_mode & 0o111):
            raise SourceSnapshotError("font alias contains code or executable resources")
        if actual.suffix in {".safetensors", ".pt", ".pth", ".ckpt", ".onnx"} or actual.name.endswith(".state.json"):
            raise SourceSnapshotError("model weights cannot enter a source capsule")
        total += info.st_size
        if total > max_bytes or len(entries) >= MAX_FILES:
            raise SourceSnapshotError("source inventory exceeds byte/file ceiling")
        data = _read(actual, max_bytes)
        entries.append({"source": str(source), "read_from": str(actual), "snapshot": relative,
                        "bytes": len(data), "sha256": _sha(data),
                        "executable": bool(info.st_mode & 0o111)})
    for binding in bindings:
        source = _path(binding["source"])
        if binding["kind"] == "file":
            add(source, source, binding["snapshot"])
            continue
        for parent, directories, filenames in os.walk(source, followlinks=False):
            directories[:] = sorted(name for name in directories if name != "__pycache__")
            for name in list(directories) + sorted(filenames):
                actual = Path(parent) / name
                relative = actual.relative_to(source).as_posix()
                if actual.suffix in {".pyc", ".pyo"}:
                    continue
                if actual.is_symlink():
                    if binding["snapshot"] != "sources/package" or relative != FONT_ALIAS:
                        raise SourceSnapshotError(f"unsupported source alias: {actual}")
                    target = os.readlink(actual)
                    if target != "../webfonts":
                        raise SourceSnapshotError("font alias target changed")
                    resolved = _path(source / "static/webfonts")
                    if not resolved.is_dir():
                        raise SourceSnapshotError("font alias target missing")
                    start = len(entries)
                    for font in sorted(resolved.iterdir()):
                        add(font, actual / font.name, f"{binding['snapshot']}/{relative}/{font.name}", font=True)
                    aliases.append({"source": str(actual), "target": target,
                                    "resolved": str(resolved), "files": entries[start:]})
                    directories.remove(name)
                elif actual.is_dir():
                    _path(actual)
                else:
                    add(actual, actual, f"{binding['snapshot']}/{relative}")
    return {"entries": sorted(entries, key=lambda row: row["snapshot"]),
            "materialized_font_aliases": aliases, "bytes": total}


def capture_snapshot(root, directory, *, extra_files=(), max_bytes=DEFAULT_MAX_BYTES):
    """Capture under the caller's source lease and resource reservation."""
    root, directory = _path(root), _path(directory)
    if any(directory.iterdir()):
        raise SourceSnapshotError("snapshot directory must be new and empty")
    bindings = _bindings(root, extra_files)
    before_git = {"datasets": _git(root), "jevops": _git(root.parents[1] / "JevOps")}
    before = _inventory(bindings, max_bytes)
    for binding in bindings:
        if binding["kind"] == "directory":
            (directory / binding["snapshot"]).mkdir(parents=True, exist_ok=False)
    for entry in before["entries"]:
        target = directory / entry["snapshot"]
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _read(entry["read_from"], max_bytes)
        if len(data) != entry["bytes"] or _sha(data) != entry["sha256"]:
            raise SourceSnapshotError("source changed during capture")
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        target.chmod(0o555 if entry["executable"] else 0o444)
    after = _inventory(bindings, max_bytes)
    after_git = {"datasets": _git(root), "jevops": _git(root.parents[1] / "JevOps")}
    if before != after or before_git != after_git:
        raise SourceSnapshotError("source/Git provenance changed while capturing; failed capsule retained")
    manifest = {"schema": SCHEMA, "canonical_root": str(root), "capsule": str(directory),
                "bindings": bindings, "inventory": before, "git": before_git,
                "max_source_bytes": max_bytes, "admitted": False,
                "scope": "Complete package resources, legal IR scripts and JevOps package; explicit Python harness files; no model weights"}
    path = directory / "manifest.json"
    _write(path, manifest)
    path.chmod(0o444)
    _sync(directory)
    for parent, _, _ in os.walk(directory, topdown=False):
        Path(parent).chmod(0o555)
    return {"path": str(path), "sha256": _sha(path.read_bytes()),
            "source_bytes": before["bytes"], "file_count": len(before["entries"]), "admitted": False}


def prepare_snapshot(directory, *, resource_ledger, extra_files=(), max_bytes=DEFAULT_MAX_BYTES,
                     storage_bytes=1_000_000_000, source_timeout_seconds=300):
    """Bounded canonical capture; failures preserve their artifacts and claim."""
    from .autoencoder_daemon_resources import DaemonResourceReservation
    from .autoencoder_source_lease import source_lease
    root = canonical_root()
    directory = _path(directory, missing=True)
    ledger = _path(resource_ledger)
    state = json.loads(_read(ledger, 8 * 1024 * 1024))
    roots = [_path(row["path"]) for row in state["roots"]]
    if not any(parent in directory.parents for parent in roots):
        raise SourceSnapshotError("snapshot attempt must be inside existing charged roots")
    if type(storage_bytes) is not int or not max_bytes + MAX_MANIFEST_BYTES < storage_bytes <= 2_000_000_000:
        raise SourceSnapshotError("snapshot reservation must cover source ceiling and metadata")
    owner = DaemonResourceReservation(ledger, roots=roots, storage_bytes=storage_bytes,
                                     memory_mb=1024, cpu_slots=1, child_process_slots=1,
                                     timeout_seconds=0, ledger_lock_timeout_seconds=60)
    with owner:
        directory.mkdir(exist_ok=False)
        owner.check_usage(directory)
        try:
            capsule = directory / "capsule"
            capsule.mkdir()
            with source_lease(root, mode="read", timeout_seconds=source_timeout_seconds) as lease:
                result = capture_snapshot(root, capsule, extra_files=extra_files, max_bytes=max_bytes)
                result["source_lease"] = lease.to_dict()
            result["resource_reservation_id"] = owner.reservation_id
            _write(directory / "capture.json", result)
            owner.check_usage(directory)
            _sync(directory)
            resources = owner.finalize(directory, artifacts_durable=True)
            _write(directory / "resources.json", resources)
            return result
        except BaseException as error:
            _write(directory / "failure.json", {"error": type(error).__name__, "message": str(error)[:2048],
                                                "reservation_id": owner.reservation_id, "admitted": False})
            _sync(directory)
            raise


def verify_snapshot(manifest_path, expected_sha256):
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise SourceSnapshotError("expected manifest SHA256 required")
    manifest_path = _path(manifest_path)
    raw = _read(manifest_path)
    if _sha(raw) != expected_sha256:
        raise SourceSnapshotError("manifest digest mismatch")
    data = json.loads(raw)
    capsule = manifest_path.parent
    if (data.get("schema") != SCHEMA or data.get("canonical_root") != str(canonical_root())
            or data.get("capsule") != str(capsule) or manifest_path.name != "manifest.json"
            or data.get("admitted") is not False):
        raise SourceSnapshotError("manifest schema or canonical path mismatch")
    bindings = data.get("bindings", [])
    if not isinstance(bindings, list) or not 3 <= len(bindings) <= 3 + MAX_EXTRA_FILES:
        raise SourceSnapshotError("invalid snapshot bindings")
    expected_bindings = _bindings(canonical_root(), [row["source"] for row in bindings[3:]], verify_live=False)
    # Immutable snapshot verification does not depend on mutable live checkout files.
    if bindings != expected_bindings:
        raise SourceSnapshotError("snapshot binding mismatch")
    entries = data.get("inventory", {}).get("entries", [])
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise SourceSnapshotError("invalid snapshot file inventory")
    expected = {"manifest.json"}
    total = 0
    for entry in entries:
        relative = Path(entry["snapshot"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in expected:
            raise SourceSnapshotError("invalid/duplicate snapshot entry")
        matches = [row for row in bindings if str(relative) == row["snapshot"] or
                   (row["kind"] == "directory" and row["snapshot"] + "/" == str(relative)[:len(row["snapshot"]) + 1])]
        if len(matches) != 1:
            raise SourceSnapshotError("entry is outside snapshot bindings")
        binding = matches[0]
        source = Path(binding["source"]) / relative.relative_to(binding["snapshot"])
        if str(source) != entry["source"]:
            raise SourceSnapshotError("entry source mapping mismatch")
        content = _read(capsule / relative, data["max_source_bytes"])
        if len(content) != entry["bytes"] or _sha(content) != entry["sha256"]:
            raise SourceSnapshotError("snapshot bytes changed")
        total += len(content)
        expected.add(str(relative))
    observed = set()
    for parent, directories, files in os.walk(capsule, followlinks=False):
        for name in directories:
            _path(Path(parent) / name)
        for name in files:
            file = _path(Path(parent) / name)
            if file.stat().st_nlink != 1:
                raise SourceSnapshotError("hardlinked capsule content")
            observed.add(file.relative_to(capsule).as_posix())
    if expected != observed or total != data["inventory"]["bytes"] or total > data["max_source_bytes"]:
        raise SourceSnapshotError("snapshot inventory changed")
    return data


def _mounts():
    result = {}
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        parts = line.split()
        decode = lambda value: re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)
        result[decode(parts[4])] = {"root": decode(parts[3]), "options": parts[5].split(",")}
    return result


def verify_frozen_runtime_from_environment():
    """Return verified identity, None when absent, or fail closed on any mismatch."""
    path, digest = os.environ.get(MANIFEST_ENV), os.environ.get(DIGEST_ENV)
    if path is None and digest is None:
        return None
    if not path or not digest:
        raise SourceSnapshotError("partial frozen source environment")
    data = verify_snapshot(path, digest)
    mounts = _mounts()
    capsule = data["capsule"]
    for target, backing in [(capsule, capsule), *[(row["source"], str(Path(capsule) / row["snapshot"])) for row in data["bindings"]]]:
        mount = mounts.get(target)
        if not mount or "ro" not in mount["options"] or mount["root"] != backing:
            raise SourceSnapshotError(f"exact read-only frozen mount missing: {target}")
        if any(name != target and Path(target) in Path(name).parents for name in mounts):
            raise SourceSnapshotError("descendant mount hides frozen source")
    for row in data["inventory"]["entries"]:
        raw = _read(row["source"], data["max_source_bytes"])
        if _sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise SourceSnapshotError("canonical frozen bytes differ from capsule")
    return {"manifest": path, "sha256": digest, "canonical_root": data["canonical_root"],
            "source_bytes": data["inventory"]["bytes"], "read_only_mounts_verified": True,
            "admitted": False}


def _process(pid):
    raw = Path("/proc", str(pid), "stat").read_text()
    values = raw[raw.rfind(")") + 2:].split()
    return {"pid": pid, "parent_pid": int(values[1]), "group_pid": int(values[2]), "birth": values[19]}


def _host_owner_alive(identity):
    try:
        observed = _process(identity["pid"])
        raw = Path("/proc", str(identity["pid"]), "stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return False
    return observed["birth"] == identity["birth"] and raw[raw.rfind(")") + 2:].split()[0] != "Z"


def _runtime_paths(data, directories):
    if not 1 <= len(directories) <= 16:
        raise SourceSnapshotError("one to sixteen explicit writable directories required")
    paths = [_path(item) for item in directories]
    protected = [Path(data["capsule"]), *[Path(row["source"]) for row in data["bindings"] if row["kind"] == "directory"]]
    for index, path in enumerate(paths):
        if not path.is_dir() or path == Path("/") or any(path == item or path in item.parents or item in path.parents for item in protected):
            raise SourceSnapshotError("writable runtime overlaps frozen source/backing capsule")
        if any(path == other or path in other.parents or other in path.parents for other in paths[:index]):
            raise SourceSnapshotError("writable runtime paths overlap")
        # Whole /tmp is necessary for the existing scheduler's atomic replacement.
        if path != Path("/tmp") and canonical_root().parents[1] not in path.parents:
            raise SourceSnapshotError("runtime must be a workspace directory or explicit /tmp scheduler directory")
    return paths


def _check_process_pair(inside, outside):
    if inside != outside:
        raise SourceSnapshotError("container and host process identities disagree")


@contextmanager
def _host_interruptions():
    if threading.current_thread() is not threading.main_thread():
        raise SourceSnapshotError("owned container launcher requires the signal-handling main thread")
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"owned launcher interrupted by signal {signum}")
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        for number in previous:
            signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def _control_observation_locks(paths):
    """Brief read observation of atomically replaced state under stable locks."""
    descriptors = []
    deadline = time.monotonic() + 10
    try:
        for path in sorted(paths):
            _read(path, 1024 * 1024)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            descriptors.append(descriptor)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise SourceSnapshotError("control observation lock deadline expired") from None
                    time.sleep(.02)
            before, after = os.fstat(descriptor), Path(path).stat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise SourceSnapshotError("control observation lock identity changed")
        yield
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _stop_owned_container(name, process):
    """Only this launch's unique container; never select containers by ancestry."""
    try:
        subprocess.run(["docker", "stop", "--time", "3", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
        process.kill()
        process.wait(timeout=5)


def _container_entry(configuration, configuration_sha):
    """Private entrypoint: no command starts before host acknowledges preflight."""
    raw = _read(configuration)
    if _sha(raw) != configuration_sha:
        raise SourceSnapshotError("runtime configuration changed")
    config = json.loads(raw)
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"container interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    frozen = verify_frozen_runtime_from_environment()
    if frozen is None or frozen["sha256"] != config["manifest_sha256"]:
        raise SourceSnapshotError("frozen source identity absent")
    if sys.prefix != config["python_prefix"] or str(Path.home()) != config["home"]:
        raise SourceSnapshotError("Python environment or home changed in container")
    if os.environ.get(SCHEDULER_ENV) != config["scheduler_path"]:
        raise SourceSnapshotError("shared scheduler path changed")
    for identity in config["identities"]:
        if _identity(identity["path"]) != identity:
            raise SourceSnapshotError("host control/runtime inode changed")
    from .resource_scheduler import default_scheduler_state_path
    if str(default_scheduler_state_path()) != config["scheduler_path"]:
        raise SourceSnapshotError("resource scheduler default differs from host")
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    pinned = require_workspace_logic_tree()
    lake = Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin/lake"
    version = subprocess.run([str(lake), "--version"], capture_output=True, text=True, timeout=5, check=True)
    run = Path(configuration).parent
    child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(45)"], start_new_session=True)
    try:
        with _control_observation_locks(config["control_locks"]):
            preflight = {"frozen": frozen, "process": _process(os.getpid()), "child": _process(child.pid),
                         "tree_pin": pinned, "identities": config["identities"], "scheduler_path": config["scheduler_path"],
                         "state_identities": [_identity(path) for path in config["control_state_paths"]],
                         "python_prefix": sys.prefix, "home": str(Path.home()),
                         "lake_version_only": version.stdout.strip(), "admitted": False}
            _write(run / "preflight.json", preflight)
            deadline = time.monotonic() + 30
            while not (run / "host-verified.json").exists():
                if not _host_owner_alive(config["host_owner"]):
                    raise SourceSnapshotError("host launcher exited during preflight")
                if time.monotonic() >= deadline:
                    raise SourceSnapshotError("host did not acknowledge namespace preflight")
                time.sleep(.05)
            acknowledgment = json.loads(_read(run / "host-verified.json"))
            if acknowledgment != {"configuration_sha256": configuration_sha, "preflight_sha256": _sha(_read(run / "preflight.json"))}:
                raise SourceSnapshotError("host preflight acknowledgment differs")
    finally:
        child.terminate()
        child.wait(timeout=5)
    verify_frozen_runtime_from_environment()
    command = subprocess.Popen(config["argv"], cwd=config["canonical_root"], start_new_session=True)
    try:
        deadline = time.monotonic() + config["timeout_seconds"]
        while command.poll() is None:
            if not _host_owner_alive(config["host_owner"]):
                raise SourceSnapshotError("host launcher exited; stopping owned command")
            if time.monotonic() >= deadline:
                raise SourceSnapshotError("frozen command deadline expired")
            time.sleep(min(.25, max(0, deadline - time.monotonic())))
        result = command.returncode
    except BaseException:
        os.killpg(command.pid, signal.SIGTERM)
        try:
            command.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(command.pid, signal.SIGKILL)
            command.wait(timeout=3)
        raise
    finally:
        # A completed coordinator must not leave background children in its group.
        try:
            os.killpg(command.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    verified = verify_frozen_runtime_from_environment()
    _write(run / "command-result.json", {"returncode": result, "frozen": verified, "admitted": False})
    return result


def run_snapshot(manifest_path, expected_sha256, *, run_directory, writable_directories,
                 resource_ledger, argv, timeout_seconds, tmp_directory, image=IMAGE):
    """Launch only after both host and container agree on frozen paths/PIDs."""
    from .autoencoder_daemon_resources import DaemonResourceReservation
    ledger = _path(resource_ledger)
    state = json.loads(_read(ledger, 8 * 1024 * 1024))
    roots = [_path(row["path"]) for row in state["roots"]]
    directory = _path(run_directory, missing=True)
    if not any(root in directory.parents for root in roots):
        raise SourceSnapshotError("launcher attempt must be inside existing charged roots")
    owner = DaemonResourceReservation(ledger, roots=roots, storage_bytes=16 * 1024 * 1024,
                                     memory_mb=1024, cpu_slots=1, child_process_slots=3,
                                     timeout_seconds=0, ledger_lock_timeout_seconds=60)
    with _host_interruptions():
        with owner:
            result = _run_snapshot(manifest_path, expected_sha256, run_directory=run_directory,
                                   writable_directories=writable_directories, resource_ledger=resource_ledger,
                                   argv=argv, timeout_seconds=timeout_seconds, tmp_directory=tmp_directory,
                                   image=image, owner=owner)
            _sync(directory)
            resources = owner.finalize(directory, artifacts_durable=True)
            _write(directory / "resources.json", resources)
            return result


def _run_snapshot(manifest_path, expected_sha256, *, run_directory, writable_directories,
                  resource_ledger, argv, timeout_seconds, tmp_directory, image, owner):
    from .resource_scheduler import default_scheduler_state_path
    data = verify_snapshot(manifest_path, expected_sha256)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise SourceSnapshotError("cached image must be pinned by exact SHA256")
    if type(timeout_seconds) not in (float, int) or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 86_400:
        raise SourceSnapshotError("run deadline must be 1..86400 seconds")
    if not argv or not all(isinstance(value, str) and value and "\0" not in value for value in argv) or len(_json(argv)) > 65536:
        raise SourceSnapshotError("bounded nonempty command argv required")
    if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
        raise SourceSnapshotError("command executable must be an existing absolute path")
    paths = _runtime_paths(data, writable_directories)
    run = _path(run_directory, missing=True)
    if run.exists():
        raise SourceSnapshotError("run directory already exists; use a new owned attempt")
    if not any(path in run.parents for path in paths):
        raise SourceSnapshotError("run receipts must be within explicit writable runtime")
    ledger, scheduler, temporary = _path(resource_ledger), _path(default_scheduler_state_path()), _path(tmp_directory)
    scheduler_lock = _path(scheduler.with_name(scheduler.name + ".lock"))
    ledger_lock = _path(ledger.with_name(ledger.name + ".lock"))
    for path in (ledger.parent, scheduler.parent, temporary):
        if not any(path == root or root in path.parents for root in paths):
            raise SourceSnapshotError("ledger/scheduler parent and temp directory must be explicitly writable")
    if not temporary.is_dir():
        raise SourceSnapshotError("temporary directory is not a directory")
    subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=10, check=True)
    run.mkdir()
    owner.check_usage(run)
    config = {"manifest_sha256": expected_sha256, "canonical_root": data["canonical_root"],
              "argv": list(argv), "timeout_seconds": float(timeout_seconds), "python_prefix": sys.prefix,
              "home": str(Path.home()), "scheduler_path": str(scheduler),
              "identities": [_identity(path) for path in (*paths, ledger_lock, scheduler_lock)],
              "control_locks": [str(ledger_lock), str(scheduler_lock)],
              "control_state_paths": [str(ledger), str(scheduler)],
              "host_owner": _process(os.getpid()),
              "admitted": False}
    configuration = run / "configuration.json"
    _write(configuration, config)
    configuration_sha = _sha(configuration.read_bytes())
    name = "autoencoder-frozen-" + uuid.uuid4().hex
    command = ["docker", "run", "--pull=never", "--rm", "--name", name, "--network=none", "--read-only",
               "--pid=host", "--cap-drop=ALL", "--cap-add=SYS_CHROOT", "--mount", "type=bind,src=/,dst=/host,readonly"]
    for path in paths:
        command += ["--mount", f"type=bind,src={path},dst=/host{path}"]
    capsule = Path(data["capsule"])
    command += ["--mount", f"type=bind,src={capsule},dst=/host{capsule},readonly"]
    for binding in data["bindings"]:
        command += ["--mount", f"type=bind,src={capsule / binding['snapshot']},dst=/host{binding['source']},readonly"]
    environment = {key: value for key, value in os.environ.items() if
                   (key.startswith("IPFS_DATASETS_") or key in {"PATH", "LANG", "LC_ALL", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "TOKENIZERS_PARALLELISM"})}
    environment.update({MANIFEST_ENV: str(manifest_path), DIGEST_ENV: expected_sha256,
                        SCHEDULER_ENV: str(scheduler), "HOME": str(Path.home()), "TMPDIR": str(temporary),
                        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": data["canonical_root"],
                        "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    for key, value in sorted(environment.items()):
        command += ["--env", f"{key}={value}"]
    entry = Path(data["canonical_root"]) / "scripts/ops/legal_ir/run_frozen_autoencoder_source.py"
    command += ["--entrypoint", "/usr/sbin/chroot", image, "/host", sys.executable, "-B", str(entry),
                "_container-entry", str(configuration), configuration_sha]
    _write(run / "launch.json", {"container": name, "image": image, "writable_directories": list(map(str, paths)),
                                 "network": "none", "host_pid_namespace": True, "manifest_sha256": expected_sha256,
                                 "source_origin": data["canonical_root"], "source_git": data["git"],
                                 "wrapper_reservation_id": owner.reservation_id,
                                 "wrapper_process_observation": "Docker CLI group; coordinator/training retain their own reservations",
                                 "scheduler_path": str(scheduler), "admitted": False})
    started = time.monotonic()
    process = None
    tails = {"stdout": bytearray(), "stderr": bytearray()}
    threads = []
    def drain(stream, tail):
        try:
            while chunk := stream.read(4096):
                tail.extend(chunk)
                del tail[:-65536]
        finally:
            stream.close()
    try:
        # Pipes are drained into bounded tails, never unbounded output files.
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        for label in tails:
            thread = threading.Thread(target=drain, args=(getattr(process, label), tails[label]), daemon=True)
            thread.start()
            threads.append(thread)
        deadline = started + 60
        while not (run / "preflight.json").exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise SourceSnapshotError("frozen container preflight failed or timed out")
            time.sleep(.05)
        preflight = json.loads(_read(run / "preflight.json"))
        _check_process_pair(preflight["process"], _process(preflight["process"]["pid"]))
        _check_process_pair(preflight["child"], _process(preflight["child"]["pid"]))
        if preflight["child"]["parent_pid"] != preflight["process"]["pid"] or preflight["child"]["group_pid"] != preflight["child"]["pid"]:
            raise SourceSnapshotError("container child is not a direct isolated child")
        state = json.loads(subprocess.check_output(["docker", "inspect", "--format", "{{json .State}}", name], timeout=5))
        if state["Pid"] != preflight["process"]["pid"] or preflight["identities"] != config["identities"]:
            raise SourceSnapshotError("host container/control identity differs")
        if preflight["state_identities"] != [_identity(path) for path in config["control_state_paths"]]:
            raise SourceSnapshotError("current host/container control state identities differ")
        _write(run / "host-verified.json", {"configuration_sha256": configuration_sha,
                                             "preflight_sha256": _sha(_read(run / "preflight.json"))})
        # The container releases its brief state-observation locks after this
        # acknowledgment. Never request the disk ledger while it awaits us.
        owner.check_usage(run, child_pid=process.pid)
        deadline = time.monotonic() + float(timeout_seconds) + 60
        next_usage = time.monotonic() + 15
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise SourceSnapshotError("owned container deadline expired")
            if time.monotonic() >= next_usage:
                owner.check_usage(run, child_pid=process.pid)
                next_usage = time.monotonic() + 15
            time.sleep(.1)
        for thread in threads:
            thread.join(timeout=5)
        _write(run / "process.json", {"returncode": process.returncode, "elapsed_seconds": time.monotonic() - started,
                                      "stdout_tail": tails["stdout"].decode(errors="replace"),
                                      "stderr_tail": tails["stderr"].decode(errors="replace"), "admitted": False})
        verify_snapshot(manifest_path, expected_sha256)
        if process.returncode != 0 or not (run / "command-result.json").is_file():
            raise SourceSnapshotError("frozen command failed; retained diagnostics are not qualification")
        return json.loads(_read(run / "command-result.json"))
    finally:
        if process is not None and process.poll() is None:
            _stop_owned_container(name, process)
        for thread in threads:
            thread.join(timeout=5)
        if not (run / "process.json").exists():
            _write(run / "process.json", {"returncode": None if process is None else process.returncode,
                                          "elapsed_seconds": time.monotonic() - started,
                                          "stdout_tail": tails["stdout"].decode(errors="replace"),
                                          "stderr_tail": tails["stderr"].decode(errors="replace"), "admitted": False})
        remaining = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
                                   capture_output=True, text=True, timeout=5, check=True)
        if remaining.stdout.strip() and process is not None:
            _stop_owned_container(name, process)
            remaining = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
                                       capture_output=True, text=True, timeout=5, check=True)
        _write(run / "cleanup.json", {"container": name, "absent": not remaining.stdout.strip(), "admitted": False})
        _sync(run)
        if remaining.stdout.strip():
            raise SourceSnapshotError("owned container remains after cleanup")
