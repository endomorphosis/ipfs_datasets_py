"""Durable authority primitives for the datasets DuckDB manual gates.

This module deliberately contains no command-line entry point.  The program
owner in :mod:`ipfs_datasets_duckdb_quack_program` is the sole public surface.
The helpers here make transported evidence immutable and make the DQK-056
gitlink mutation independently replayable; task-owned signature and
transaction adapters must still be supplied by the tasks that define them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


BLOB_SCHEMA = "ipfs_datasets_py/duckdb-quack-manual-gate-blob@2"
CHECKOUT_LEASE_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-checkout-lease@2"
)
CHECKOUT_LEASE_OWNER_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-checkout-owner@2"
)
CHECKOUT_RELEASE_TOMBSTONE_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-checkout-release-tombstone@2"
)
GITLINK_PIN_INTENT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-gitlink-pin-intent@2"
)
GITLINK_PIN_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-gitlink-pin-receipt@2"
)
ROLLOVER_BINDING_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-rollover-binding@2"
)
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_CID = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_BLOB_BYTES = 2 * 1024 * 1024


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manual-gate authority is not canonical JSON") from exc


def strict_json_object(raw: bytes | str, *, noun: str) -> dict[str, Any]:
    if isinstance(raw, bytes):
        if not 1 <= len(raw) <= _MAX_BLOB_BYTES:
            raise RuntimeError(f"{noun} exceeds its bounded object size")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"{noun} is not UTF-8") from exc
    elif isinstance(raw, str) and 1 <= len(raw.encode("utf-8")) <= _MAX_BLOB_BYTES:
        text = raw
    else:
        raise RuntimeError(f"{noun} must be a bounded JSON object")

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(f"{noun} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise RuntimeError(f"{noun} contains non-finite value {value}")

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{noun} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{noun} must contain one JSON object")
    return value


def content_id(namespace: str, value: Mapping[str, Any]) -> str:
    body = canonical_json({"namespace": namespace, "value": dict(value)})
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _aware_timestamp(value: Any, *, noun: str) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 128:
        raise RuntimeError(f"{noun} is not a bounded timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{noun} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError(f"{noun} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _owner_controlled(metadata: os.stat_result, *, directory: bool) -> bool:
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    return bool(
        expected
        and metadata.st_uid == os.geteuid()
        and not metadata.st_mode & 0o077
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ContentBlobStore:
    """Owner-controlled, immutable content-addressed manual-gate blobs."""

    def __init__(self, lifecycle_root: Path) -> None:
        self.lifecycle_root = Path(lifecycle_root)
        self.blob_root = self.lifecycle_root / "blobs"

    def _open_root(self, *, create_blobs: bool) -> int:
        try:
            root_metadata = self.lifecycle_root.lstat()
        except OSError as exc:
            raise RuntimeError("manual-gate lifecycle root is unavailable") from exc
        if self.lifecycle_root.is_symlink() or not _owner_controlled(
            root_metadata, directory=True
        ):
            raise RuntimeError("manual-gate lifecycle root is not owner-controlled")
        root_fd = os.open(
            self.lifecycle_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            if create_blobs:
                try:
                    os.mkdir("blobs", 0o700, dir_fd=root_fd)
                    os.fsync(root_fd)
                except FileExistsError:
                    pass
            blob_fd = os.open(
                "blobs",
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        except Exception:
            os.close(root_fd)
            raise
        os.close(root_fd)
        if not _owner_controlled(os.fstat(blob_fd), directory=True):
            os.close(blob_fd)
            raise RuntimeError("manual-gate blob root is not owner-controlled")
        return blob_fd

    @staticmethod
    def _record(kind: str, raw: bytes) -> dict[str, Any]:
        if (
            not isinstance(kind, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind) is None
            or not 0 <= len(raw) <= _MAX_BLOB_BYTES
        ):
            raise RuntimeError("manual-gate blob kind or size is invalid")
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "schema": BLOB_SCHEMA,
            "kind": kind,
            "blob_cid": f"sha256:{digest}",
            "byte_length": len(raw),
            "relative_path": f"blobs/{digest}.blob",
        }

    def put(self, kind: str, raw: bytes) -> dict[str, Any]:
        if not isinstance(raw, bytes):
            raise RuntimeError("manual-gate blob content must be exact bytes")
        record = self._record(kind, raw)
        filename = str(record["relative_path"]).split("/", 1)[1]
        directory_fd = self._open_root(create_blobs=True)
        descriptor: int | None = None
        temporary_name = (
            f".{filename}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
        )
        try:
            try:
                descriptor = os.open(
                    filename,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                offset = 0
                while offset < len(raw):
                    written = os.write(descriptor, raw[offset:])
                    if written <= 0:
                        raise RuntimeError("manual-gate blob write was incomplete")
                    offset += written
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                try:
                    os.link(
                        temporary_name,
                        filename,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    pass
                os.fsync(directory_fd)
                descriptor = os.open(
                    filename,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
            metadata = os.fstat(descriptor)
            if not _owner_controlled(metadata, directory=False):
                raise RuntimeError("manual-gate blob is not owner-controlled")
            existing = bytearray()
            while len(existing) <= _MAX_BLOB_BYTES:
                chunk = os.read(
                    descriptor,
                    min(1024 * 1024, _MAX_BLOB_BYTES + 1 - len(existing)),
                )
                if not chunk:
                    break
                existing.extend(chunk)
            if bytes(existing) != raw:
                raise RuntimeError("manual-gate blob path conflicts with different bytes")
            return record
        except OSError as exc:
            raise RuntimeError("manual-gate blob publication failed closed") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)

    def read(self, record: Mapping[str, Any], *, expected_kind: str) -> bytes:
        expected_keys = {
            "schema",
            "kind",
            "blob_cid",
            "byte_length",
            "relative_path",
        }
        if set(record) != expected_keys or record.get("schema") != BLOB_SCHEMA:
            raise RuntimeError("manual-gate blob record shape is unsupported")
        if record.get("kind") != expected_kind:
            raise RuntimeError("manual-gate blob kind is detached")
        cid = str(record.get("blob_cid") or "")
        if _CID.fullmatch(cid) is None:
            raise RuntimeError("manual-gate blob CID is invalid")
        size = record.get("byte_length")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= _MAX_BLOB_BYTES:
            raise RuntimeError("manual-gate blob length is invalid")
        filename = f"{cid.split(':', 1)[1]}.blob"
        if record.get("relative_path") != f"blobs/{filename}":
            raise RuntimeError("manual-gate blob path is not content-derived")
        directory_fd = self._open_root(create_blobs=False)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                filename,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            before = os.fstat(descriptor)
            if not _owner_controlled(before, directory=False) or before.st_size != size:
                raise RuntimeError("manual-gate blob metadata is invalid")
            chunks: list[bytes] = []
            remaining = _MAX_BLOB_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or len(raw) != size
                or "sha256:" + hashlib.sha256(raw).hexdigest() != cid
            ):
                raise RuntimeError("manual-gate blob changed or failed its CID")
            return raw
        except OSError as exc:
            raise RuntimeError("manual-gate blob is unavailable without symlinks") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)


def _git(repository: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=not binary,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", "replace")
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8", "replace")
        raise RuntimeError(stderr.strip() or stdout.strip() or "Git command failed")
    return result.stdout if binary else result.stdout.rstrip("\r\n")


def _process_identity(pid: int) -> dict[str, Any] | None:
    try:
        stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if len(stat_fields) < 22 or not boot_id or not cmdline:
        return None
    return {
        "pid": pid,
        "boot_id": boot_id,
        "start_ticks": int(stat_fields[21]),
        "cmdline_sha256": "sha256:" + hashlib.sha256(cmdline).hexdigest(),
    }


def compatibility_owner_script(identity: Mapping[str, Any]) -> str:
    """Return the argv[0] basename visible to the released native lock reader."""

    pid = identity.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise RuntimeError("manual-gate compatibility owner identity is invalid")
    current = _process_identity(pid)
    if current is None or not _same_owner(current, identity):
        raise RuntimeError("manual-gate compatibility owner is not the exact live process")
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        command = b""
    try:
        executable = command.split(b"\0", 1)[0].decode("utf-8", errors="strict")
        fallback = Path(executable).name
    except (IndexError, UnicodeDecodeError, ValueError):
        fallback = ""
    if not fallback or fallback.encode("utf-8") not in command:
        raise RuntimeError("manual-gate compatibility owner script is unavailable")
    return fallback


def _compatibility_owner_script() -> str:
    identity = _process_identity(os.getpid())
    if identity is None:
        raise RuntimeError("manual-gate compatibility owner identity is unavailable")
    return compatibility_owner_script(identity)


def _lease_is_live(lease: Mapping[str, Any]) -> bool:
    pid = lease.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return False
    current = _process_identity(pid)
    return current is not None and all(
        current.get(key) == lease.get(key)
        for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
    )


def _lease_owner_cid(owner: Mapping[str, Any]) -> str:
    material = dict(owner)
    claimed = material.pop("owner_cid", "")
    derived = content_id("manual-gate-checkout-owner", material)
    if claimed and claimed != derived:
        raise RuntimeError("manual-gate checkout owner CID is invalid")
    return derived


def _lease_stable_id(lease: Mapping[str, Any]) -> str:
    material = {
        key: lease.get(key)
        for key in (
            "schema",
            "kind",
            "lease_role",
            "operation_id",
            "repository_role",
            "repository_root",
            "repository_id",
            "lock_path",
        )
    }
    return content_id("manual-gate-checkout-lease", material)


def _lease_record_cid(lease: Mapping[str, Any]) -> str:
    material = dict(lease)
    claimed = material.pop("record_cid", "")
    derived = content_id("manual-gate-checkout-lease-record", material)
    if claimed and claimed != derived:
        raise RuntimeError("manual-gate checkout lease record CID is invalid")
    return derived


def _owner_record(
    identity: Mapping[str, Any], *, generation: int, previous_owner_cid: str
) -> dict[str, Any]:
    owner: dict[str, Any] = {
        "schema": CHECKOUT_LEASE_OWNER_SCHEMA,
        "generation": generation,
        "previous_owner_cid": previous_owner_cid,
        "adopted_at": datetime.now(timezone.utc).isoformat(),
        "identity": dict(identity),
    }
    owner["owner_cid"] = _lease_owner_cid(owner)
    return owner


def _validate_lease(lease: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema",
        "kind",
        "lease_role",
        "operation_id",
        "repository_role",
        "repository_root",
        "repository_id",
        "lock_path",
        "pid",
        "owner_script",
        "repo_root",
        "task_id",
        "attempt",
        "branch",
        "compatibility_owner",
        "lease_id",
        "generation",
        "owner_history",
        "record_cid",
    }
    generation = lease.get("generation")
    history = lease.get("owner_history")
    compatibility_owner = lease.get("compatibility_owner")
    if (
        set(lease) != expected_keys
        or lease.get("schema") != CHECKOUT_LEASE_SCHEMA
        or lease.get("kind") != "implementation"
        or lease.get("lease_role") != "manual_gate_checkout"
        or lease.get("repository_role") not in {"parent", "accelerator"}
        or _CID.fullmatch(str(lease.get("operation_id") or "")) is None
        or not isinstance(lease.get("repository_root"), str)
        or Path(str(lease.get("repository_root") or "")).absolute()
        != Path(str(lease.get("repository_root") or ""))
        or not isinstance(lease.get("repository_id"), str)
        or not str(lease.get("repository_id") or "").startswith("repository:")
        or not isinstance(lease.get("lock_path"), str)
        or Path(str(lease.get("lock_path") or "")).absolute()
        != Path(str(lease.get("lock_path") or ""))
        or lease.get("repo_root") != lease.get("repository_root")
        or not isinstance(lease.get("pid"), int)
        or isinstance(lease.get("pid"), bool)
        or lease.get("pid", 0) < 1
        or not isinstance(lease.get("owner_script"), str)
        or not str(lease.get("owner_script") or "")
        or lease.get("task_id") != ""
        or lease.get("attempt") != 0
        or lease.get("branch") != ""
        or not isinstance(compatibility_owner, Mapping)
        or set(compatibility_owner)
        != {"pid", "boot_id", "start_ticks", "cmdline_sha256", "owner_script"}
        or not isinstance(compatibility_owner.get("pid"), int)
        or isinstance(compatibility_owner.get("pid"), bool)
        or compatibility_owner.get("pid", 0) < 1
        or not isinstance(compatibility_owner.get("start_ticks"), int)
        or isinstance(compatibility_owner.get("start_ticks"), bool)
        or compatibility_owner.get("start_ticks", 0) < 1
        or not isinstance(compatibility_owner.get("boot_id"), str)
        or not compatibility_owner.get("boot_id")
        or _CID.fullmatch(
            str(compatibility_owner.get("cmdline_sha256") or "")
        )
        is None
        or not isinstance(compatibility_owner.get("owner_script"), str)
        or Path(str(compatibility_owner.get("owner_script") or "")).name
        != compatibility_owner.get("owner_script")
        or not compatibility_owner.get("owner_script")
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or not 1 <= generation <= 32
        or not isinstance(history, list)
        or len(history) != generation
        or lease.get("lease_id") != _lease_stable_id(lease)
    ):
        raise RuntimeError("manual-gate checkout lease shape is foreign or malformed")
    previous = ""
    prior_adopted_at: datetime | None = None
    for index, owner in enumerate(history, 1):
        if not isinstance(owner, Mapping) or set(owner) != {
            "schema",
            "generation",
            "previous_owner_cid",
            "adopted_at",
            "identity",
            "owner_cid",
        }:
            raise RuntimeError("manual-gate checkout owner history is malformed")
        identity = owner.get("identity")
        if (
            owner.get("schema") != CHECKOUT_LEASE_OWNER_SCHEMA
            or owner.get("generation") != index
            or owner.get("previous_owner_cid") != previous
            or not isinstance(owner.get("adopted_at"), str)
            or not isinstance(identity, Mapping)
            or set(identity)
            != {"pid", "boot_id", "start_ticks", "cmdline_sha256"}
            or not isinstance(identity.get("pid"), int)
            or isinstance(identity.get("pid"), bool)
            or identity.get("pid", 0) < 1
            or not isinstance(identity.get("start_ticks"), int)
            or isinstance(identity.get("start_ticks"), bool)
            or identity.get("start_ticks", 0) < 1
            or not isinstance(identity.get("boot_id"), str)
            or not identity.get("boot_id")
            or _CID.fullmatch(str(identity.get("cmdline_sha256") or "")) is None
            or owner.get("owner_cid") != _lease_owner_cid(owner)
        ):
            raise RuntimeError("manual-gate checkout owner history is not content-bound")
        adopted_at = _aware_timestamp(
            owner["adopted_at"], noun="manual-gate checkout owner adoption"
        )
        if prior_adopted_at is not None and adopted_at < prior_adopted_at:
            raise RuntimeError("manual-gate checkout owner history time regressed")
        prior_adopted_at = adopted_at
        previous = str(owner["owner_cid"])
    if lease.get("pid") != compatibility_owner["pid"]:
        raise RuntimeError("manual-gate checkout compatibility owner is detached")
    if lease.get("owner_script") != compatibility_owner["owner_script"]:
        raise RuntimeError("manual-gate checkout compatibility script is detached")
    if lease.get("record_cid") != _lease_record_cid(lease):
        raise RuntimeError("manual-gate checkout lease record is not content-bound")
    return dict(lease)


def _assert_lock_authority(
    *, repository: Path, role: str, lock_path: Path, checkout_module: Any
) -> str:
    repository = repository.resolve()
    canonical = Path(
        os.path.abspath(os.fspath(checkout_module.checkout_mutation_lock_path(repository)))
    )
    repository_id = str(checkout_module.checkout_repository_id(repository))
    selected_lock = Path(os.path.abspath(os.fspath(lock_path)))
    if selected_lock != canonical or role not in {"parent", "accelerator"}:
        raise RuntimeError("manual-gate checkout lock is not canonical")
    common = canonical.parent.lstat()
    if (
        stat.S_ISLNK(common.st_mode)
        or not stat.S_ISDIR(common.st_mode)
        or common.st_uid != os.geteuid()
        or common.st_gid != os.getegid()
        or common.st_mode & stat.S_IWOTH
    ):
        raise RuntimeError("manual-gate Git common directory is not trusted")
    return repository_id


def _read_lease(path: Path) -> dict[str, Any] | None:
    raw = _read_current_lock_bytes(path, require_private=True)
    if raw is None:
        return None
    return _validate_lease(strict_json_object(raw, noun="manual-gate checkout lease"))


def _read_current_lock_bytes(
    path: Path, *, require_private: bool = False
) -> bytes | None:
    """Read any owner-controlled checkout record without interpreting its schema."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError("manual-gate checkout lease is unavailable without symlinks") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or (
                stat.S_IMODE(before.st_mode) != 0o600
                if require_private
                else bool(before.st_mode & stat.S_IWOTH)
            )
            or not 1 <= before.st_size <= 64 * 1024
        ):
            raise RuntimeError("manual-gate checkout lease file is not trusted")
        chunks: list[bytes] = []
        remaining = 64 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise RuntimeError("manual-gate checkout lease changed during read")
    finally:
        os.close(descriptor)
    return raw


def _encoded_lease(lease: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(lease), indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _durable_write_lease(path: Path, lease: Mapping[str, Any], *, replace: bool) -> None:
    encoded = _encoded_lease(lease)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{os.urandom(12).hex()}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("manual-gate checkout lease write was incomplete")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
    except FileExistsError as exc:
        raise RuntimeError("manual-gate checkout lease creation raced") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(path.parent)
    if _read_lease(path) != dict(lease):
        raise RuntimeError("manual-gate checkout lease changed after publication")


def _new_lease(
    *, role: str, repository: Path, repository_id: str, lock_path: Path, operation_id: str
) -> dict[str, Any]:
    identity = _process_identity(os.getpid())
    if identity is None:
        raise RuntimeError("manual-gate checkout owner identity is unavailable")
    lease: dict[str, Any] = {
        "schema": CHECKOUT_LEASE_SCHEMA,
        "kind": "implementation",
        "lease_role": "manual_gate_checkout",
        "operation_id": operation_id,
        "repository_role": role,
        "repository_root": str(repository.resolve()),
        "repository_id": repository_id,
        "lock_path": os.path.abspath(os.fspath(lock_path)),
        # These compatibility fields are intentionally understood by the
        # released ImplementationDaemon lock consumer.  Without them it treats
        # a live manual-gate record as stale and removes it.
        "pid": int(identity["pid"]),
        "owner_script": _compatibility_owner_script(),
        "repo_root": str(repository.resolve()),
        "task_id": "",
        "attempt": 0,
        "branch": "",
        "compatibility_owner": {
            **dict(identity),
            "owner_script": _compatibility_owner_script(),
        },
        "lease_id": "",
        "generation": 1,
        "owner_history": [_owner_record(identity, generation=1, previous_owner_cid="")],
    }
    lease["lease_id"] = _lease_stable_id(lease)
    lease["record_cid"] = _lease_record_cid(lease)
    return lease


def _owner_identity(lease: Mapping[str, Any]) -> Mapping[str, Any]:
    return lease["owner_history"][-1]["identity"]


def _same_owner(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256"))


def _adopt_lease(lease: Mapping[str, Any]) -> dict[str, Any]:
    current = _process_identity(os.getpid())
    if current is None:
        raise RuntimeError("manual-gate checkout owner identity is unavailable")
    # A strict same-operation record may be held by the isolated custodian
    # while its lifecycle owner is down.  Native supervisors use this live
    # compatibility identity, so replacing it before journal recovery would
    # reopen the exact crash window the durable custody is meant to close.
    if _lease_is_live(lease["compatibility_owner"]):
        return dict(lease)
    prior = _owner_identity(lease)
    if _same_owner(prior, current):
        return dict(lease)
    if _lease_is_live(prior):
        raise RuntimeError("live checkout lease blocks manual-gate mutation")
    generation = int(lease["generation"]) + 1
    if generation > 32:
        raise RuntimeError("manual-gate checkout owner history is exhausted")
    history = [dict(item) for item in lease["owner_history"]]
    history.append(
        _owner_record(
            current,
            generation=generation,
            previous_owner_cid=str(history[-1]["owner_cid"]),
        )
    )
    adopted = {
        **dict(lease),
        "pid": int(current["pid"]),
        "owner_script": _compatibility_owner_script(),
        "compatibility_owner": {
            **dict(current),
            "owner_script": _compatibility_owner_script(),
        },
        "generation": generation,
        "owner_history": history,
    }
    adopted.pop("record_cid", None)
    adopted["record_cid"] = _lease_record_cid(adopted)
    return adopted


def _reconcile_expected_lease(
    expected: Mapping[str, Any], physical: Mapping[str, Any]
) -> None:
    if expected == physical:
        return
    if _lease_is_live(_owner_identity(expected)):
        raise RuntimeError(
            "manual-gate checkout journal owner is still live during replacement"
        )
    if (
        expected.get("lease_id") != physical.get("lease_id")
        or expected.get("operation_id") != physical.get("operation_id")
        or expected.get("owner_history")
        != list(physical.get("owner_history") or ())[: len(expected.get("owner_history") or ())]
    ):
        raise RuntimeError("manual-gate checkout lease differs from its journal")
    for owner in list(physical["owner_history"])[len(expected["owner_history"]):]:
        if _lease_is_live(owner["identity"]):
            raise RuntimeError("manual-gate checkout lease has a foreign live extension")


def acquire_or_adopt_checkout_leases(
    repositories: Mapping[str, Path],
    *,
    operation_id: str,
    checkout_module: Any,
    expected_records: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Persist/adopt both leases; callers retain them until governed release."""

    expected_by_path = {
        str(item.get("lock_path") or ""): _validate_lease(item)
        for item in expected_records
    }
    if len(expected_by_path) != len(expected_records):
        raise RuntimeError("manual-gate journal checkout lease paths are duplicated")
    specifications: list[tuple[Path, str, Path, str]] = []
    for role, selected in repositories.items():
        repository = Path(selected).resolve()
        lock_path = Path(
            os.path.abspath(
                os.fspath(checkout_module.checkout_mutation_lock_path(repository))
            )
        )
        repository_id = _assert_lock_authority(
            repository=repository,
            role=role,
            lock_path=lock_path,
            checkout_module=checkout_module,
        )
        specifications.append((lock_path, role, repository, repository_id))
    specifications.sort(key=lambda item: str(item[0]))
    if len(specifications) != 2 or {item[1] for item in specifications} != {"parent", "accelerator"}:
        raise RuntimeError("manual-gate requires exact parent and accelerator leases")
    result: list[dict[str, Any]] = []
    for lock_path, role, repository, repository_id in specifications:
        with checkout_module.serialized_lock_update(lock_path):
            _assert_lock_authority(
                repository=repository,
                role=role,
                lock_path=lock_path,
                checkout_module=checkout_module,
            )
            physical = _read_lease(lock_path)
            expected = expected_by_path.get(str(lock_path))
            if physical is None:
                if expected is not None:
                    raise RuntimeError("held manual-gate checkout lease disappeared")
                physical = _new_lease(
                    role=role,
                    repository=repository,
                    repository_id=repository_id,
                    lock_path=lock_path,
                    operation_id=operation_id,
                )
                _durable_write_lease(lock_path, physical, replace=False)
            else:
                if (
                    physical.get("operation_id") != operation_id
                    or physical.get("repository_role") != role
                    or physical.get("repository_root") != str(repository)
                    or physical.get("repository_id") != repository_id
                    or physical.get("lock_path") != str(lock_path)
                ):
                    raise RuntimeError("foreign checkout lease blocks manual-gate mutation")
                if expected is not None:
                    _reconcile_expected_lease(expected, physical)
                adopted = _adopt_lease(physical)
                if adopted != physical:
                    _durable_write_lease(lock_path, adopted, replace=True)
                    physical = adopted
            result.append(physical)
    if expected_by_path and set(expected_by_path) != {str(item[0]) for item in specifications}:
        raise RuntimeError("manual-gate journal checkout lease set is incomplete")
    return tuple(result)


def assert_checkout_leases(
    records: Sequence[Mapping[str, Any]],
    *,
    checkout_module: Any,
    expected_custodian: Mapping[str, Any] | None = None,
) -> None:
    current = _process_identity(os.getpid())
    if current is None or len(records) != 2:
        raise RuntimeError("manual-gate checkout lease assertion is incomplete")
    validated = tuple(_validate_lease(item) for item in records)
    if (
        len({str(item["lock_path"]) for item in validated}) != 2
        or {str(item["repository_role"]) for item in validated}
        != {"parent", "accelerator"}
    ):
        raise RuntimeError("manual-gate checkout lease set is not exact")
    for lease in sorted(validated, key=lambda item: str(item["lock_path"])):
        path = Path(str(lease["lock_path"]))
        repository = Path(str(lease["repository_root"]))
        with checkout_module.serialized_lock_update(path):
            _assert_lock_authority(
                repository=repository,
                role=str(lease["repository_role"]),
                lock_path=path,
                checkout_module=checkout_module,
            )
            expected_owner = (
                {
                    key: expected_custodian.get(key)
                    for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
                }
                if expected_custodian is not None
                else current
            )
            if (
                _read_lease(path) != lease
                or not _same_owner(lease["compatibility_owner"], expected_owner)
                or not _lease_is_live(expected_owner)
            ):
                raise RuntimeError("manual-gate checkout lease changed or is not owned")


def bind_checkout_leases_to_custodian(
    records: Sequence[Mapping[str, Any]],
    *,
    custodian: Mapping[str, Any],
    owner_script: str,
    checkout_module: Any,
) -> tuple[dict[str, Any], ...]:
    """Bind compatibility ownership to a live relaunched master.

    The lifecycle owner history remains intact.  The top-level fields are the
    compatibility contract consumed by the released implementation daemon,
    preventing that daemon from deleting the durable lease if the CLI dies
    after relaunch but before RELEASED.
    """

    identity = {
        key: custodian.get(key)
        for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
    }
    if (
        Path(owner_script).name != owner_script
        or not owner_script
        or owner_script != compatibility_owner_script(identity)
        or not _lease_is_live(identity)
    ):
        raise RuntimeError("manual-gate checkout custodian is not a live exact process")
    result: list[dict[str, Any]] = []
    for expected_value in sorted(
        records, key=lambda item: str(item.get("lock_path") or "")
    ):
        expected = _validate_lease(expected_value)
        path = Path(str(expected["lock_path"]))
        repository = Path(str(expected["repository_root"]))
        desired = {
            **expected,
            "pid": identity["pid"],
            "owner_script": owner_script,
            "compatibility_owner": {**identity, "owner_script": owner_script},
        }
        desired.pop("record_cid", None)
        desired["record_cid"] = _lease_record_cid(desired)
        with checkout_module.serialized_lock_update(path):
            _assert_lock_authority(
                repository=repository,
                role=str(expected["repository_role"]),
                lock_path=path,
                checkout_module=checkout_module,
            )
            physical = _read_lease(path)
            if physical == desired:
                result.append(desired)
                continue
            comparable_fields = set(expected).difference(
                {"pid", "owner_script", "compatibility_owner", "record_cid"}
            )
            if physical is None or any(
                physical.get(key) != expected.get(key) for key in comparable_fields
            ):
                raise RuntimeError("manual-gate checkout lease changed before custodian bind")
            _durable_write_lease(path, desired, replace=True)
            result.append(desired)
    return tuple(result)


def release_checkout_leases(
    records: Sequence[Mapping[str, Any]],
    *,
    operation_id: str,
    release_prepared_at: str,
    checkout_module: Any,
    blob_store: ContentBlobStore,
    fault_injector: Any | None = None,
) -> tuple[dict[str, Any], ...]:
    """Release exact leases through deterministic durable tombstones."""

    _aware_timestamp(
        release_prepared_at, noun="manual-gate checkout release preparation"
    )
    validated_records = tuple(_validate_lease(item) for item in records)
    if (
        len(validated_records) != 2
        or len({str(item["lock_path"]) for item in validated_records}) != 2
        or {str(item["repository_role"]) for item in validated_records}
        != {"parent", "accelerator"}
    ):
        raise RuntimeError("manual-gate checkout release lease set is incomplete")
    prepared: list[
        tuple[dict[str, Any], dict[str, Any], bytes, dict[str, Any], bool]
    ] = []
    for lease in sorted(
        validated_records, key=lambda item: str(item["lock_path"]), reverse=True
    ):
        if lease.get("operation_id") != operation_id:
            raise RuntimeError("manual-gate lease release belongs to another operation")
        tombstone: dict[str, Any] = {
            "schema": CHECKOUT_RELEASE_TOMBSTONE_SCHEMA,
            "operation_id": operation_id,
            "lease_id": lease["lease_id"],
            "lease_record_cid": lease["record_cid"],
            "repository_role": lease["repository_role"],
            "repository_id": lease["repository_id"],
            "lock_path": lease["lock_path"],
            "released_at": release_prepared_at,
        }
        tombstone["tombstone_cid"] = content_id("manual-gate-checkout-release", tombstone)
        raw = canonical_json(tombstone).encode("utf-8")
        expected_blob = blob_store._record("checkout_release", raw)
        try:
            preexisting_tombstone = (
                blob_store.read(expected_blob, expected_kind="checkout_release") == raw
            )
        except (OSError, RuntimeError):
            preexisting_tombstone = False
        path = Path(str(lease["lock_path"]))
        repository = Path(str(lease["repository_root"]))
        # Validate the complete set before removing either lease.  A missing
        # member is recoverable only when its exact tombstone predates this
        # call (the unlink-before-return crash boundary).
        with checkout_module.serialized_lock_update(path):
            _assert_lock_authority(
                repository=repository,
                role=str(lease["repository_role"]),
                lock_path=path,
                checkout_module=checkout_module,
            )
            physical_raw = _read_current_lock_bytes(path)
            owned = physical_raw == _encoded_lease(lease)
            if physical_raw is not None and not owned and not preexisting_tombstone:
                raise RuntimeError("manual-gate checkout lease changed before release")
            if physical_raw is None and not preexisting_tombstone:
                raise RuntimeError(
                    "manual-gate checkout lease disappeared before its release tombstone"
                )
        prepared.append(
            (lease, tombstone, raw, expected_blob, preexisting_tombstone)
        )

    results: list[dict[str, Any]] = []
    for lease, tombstone, raw, expected_blob, preexisting_tombstone in prepared:
        blob = expected_blob
        path = Path(str(lease["lock_path"]))
        repository = Path(str(lease["repository_root"]))
        with checkout_module.serialized_lock_update(path):
            _assert_lock_authority(
                repository=repository,
                role=str(lease["repository_role"]),
                lock_path=path,
                checkout_module=checkout_module,
            )
            physical_raw = _read_current_lock_bytes(path)
            if physical_raw is not None:
                if physical_raw != _encoded_lease(lease) and preexisting_tombstone:
                    # Our exact durable tombstone proves this path was already
                    # released.  A later owner must never be unlinked here.
                    pass
                elif physical_raw != _encoded_lease(lease):
                    raise RuntimeError("manual-gate checkout lease raced before release")
                else:
                    blob = blob_store.put("checkout_release", raw)
                    if fault_injector:
                        fault_injector(
                            "checkout_release_tombstone_persisted:"
                            + str(lease["repository_role"])
                        )
                    path.unlink()
                    _fsync_directory(path.parent)
                    if fault_injector:
                        fault_injector(
                            "checkout_release_unlinked:"
                            + str(lease["repository_role"])
                        )
            elif not preexisting_tombstone:
                raise RuntimeError("manual-gate checkout lease raced before tombstone")
        if blob_store.read(blob, expected_kind="checkout_release") != raw:
            raise RuntimeError("manual-gate checkout release tombstone is not durable")
        results.append({"tombstone": tombstone, "blob": blob})
    return tuple(sorted(results, key=lambda item: item["tombstone"]["lock_path"]))


def validate_checkout_lease_record(lease: Mapping[str, Any]) -> dict[str, Any]:
    """Public static validator used by historical manual-gate admission."""

    return _validate_lease(lease)


def validate_checkout_lease_descendant(
    basis: Mapping[str, Any], current: Mapping[str, Any]
) -> None:
    """Require a final lease to descend monotonically from its acquired basis."""

    initial = _validate_lease(basis)
    selected = _validate_lease(current)
    immutable = set(initial).difference(
        {
            "pid",
            "owner_script",
            "compatibility_owner",
            "generation",
            "owner_history",
            "record_cid",
        }
    )
    history = selected["owner_history"]
    if (
        any(selected.get(key) != initial.get(key) for key in immutable)
        or selected["generation"] < initial["generation"]
        or history[: len(initial["owner_history"])] != initial["owner_history"]
    ):
        raise RuntimeError("manual-gate checkout lease is not a monotonic descendant")


def validate_checkout_release_record(
    *,
    lease: Mapping[str, Any],
    release: Mapping[str, Any],
    checkout_module: Any,
    blob_store: ContentBlobStore,
) -> None:
    """Reverify one released lease without disturbing a later lease owner."""

    validated = _validate_lease(lease)
    if set(release) != {"tombstone", "blob"}:
        raise RuntimeError("manual-gate checkout release record shape is invalid")
    tombstone = release.get("tombstone")
    blob = release.get("blob")
    expected_tombstone_keys = {
        "schema",
        "operation_id",
        "lease_id",
        "lease_record_cid",
        "repository_role",
        "repository_id",
        "lock_path",
        "released_at",
        "tombstone_cid",
    }
    if (
        not isinstance(tombstone, Mapping)
        or set(tombstone) != expected_tombstone_keys
        or not isinstance(blob, Mapping)
        or tombstone.get("schema") != CHECKOUT_RELEASE_TOMBSTONE_SCHEMA
        or tombstone.get("operation_id") != validated["operation_id"]
        or tombstone.get("lease_id") != validated["lease_id"]
        or tombstone.get("lease_record_cid") != validated["record_cid"]
        or tombstone.get("repository_role") != validated["repository_role"]
        or tombstone.get("repository_id") != validated["repository_id"]
        or tombstone.get("lock_path") != validated["lock_path"]
        or tombstone.get("tombstone_cid")
        != content_id(
            "manual-gate-checkout-release",
            {key: value for key, value in tombstone.items() if key != "tombstone_cid"},
        )
    ):
        raise RuntimeError("manual-gate checkout release is not content-bound")
    _aware_timestamp(
        tombstone.get("released_at"), noun="manual-gate checkout release"
    )
    raw = canonical_json(tombstone).encode("utf-8")
    if blob_store.read(blob, expected_kind="checkout_release") != raw:
        raise RuntimeError("manual-gate checkout release blob is detached")
    path = Path(str(validated["lock_path"]))
    repository = Path(str(validated["repository_root"]))
    with checkout_module.serialized_lock_update(path):
        _assert_lock_authority(
            repository=repository,
            role=str(validated["repository_role"]),
            lock_path=path,
            checkout_module=checkout_module,
        )
        current = _read_current_lock_bytes(path)
        if current == _encoded_lease(validated):
            raise RuntimeError("released manual-gate checkout lease is still active")


def _checkout_binding(repository: Path, repository_id: str) -> dict[str, Any]:
    return {
        "repository_root": str(repository.resolve()),
        "repository_id": repository_id,
        "head_commit": str(_git(repository, "rev-parse", "HEAD")).lower(),
        "head_tree": str(_git(repository, "rev-parse", "HEAD^{tree}")).lower(),
        "branch": str(_git(repository, "branch", "--show-current")),
    }


def prepare_gitlink_pin(
    *,
    parent: Path,
    accelerator: Path,
    target_branch: str,
    desired_commit: str,
    desired_tree: str,
    operation_id: str,
    checkout_leases: Sequence[Mapping[str, Any]],
    checkout_module: Any,
    protected_paths: Sequence[str],
) -> dict[str, Any]:
    if _OID.fullmatch(desired_commit) is None or _OID.fullmatch(desired_tree) is None:
        raise RuntimeError("manual-gate accelerator Git identity is invalid")
    parent = parent.resolve()
    accelerator = accelerator.resolve()
    lease_by_root = {str(item.get("repository_root") or ""): item for item in checkout_leases}
    if set(lease_by_root) != {str(parent), str(accelerator)}:
        raise RuntimeError("manual-gate checkout leases do not bind both repositories")
    for repository in (parent, accelerator):
        lease = _validate_lease(lease_by_root[str(repository)])
        if (
            lease.get("operation_id") != operation_id
            or lease.get("repository_id")
            != checkout_module.checkout_repository_id(repository)
            or not _lease_is_live(_owner_identity(lease))
        ):
            raise RuntimeError("manual-gate checkout lease is stale or foreign")
    parent_binding = _checkout_binding(
        parent, str(checkout_module.checkout_repository_id(parent))
    )
    accelerator_binding = _checkout_binding(
        accelerator, str(checkout_module.checkout_repository_id(accelerator))
    )
    if parent_binding["branch"] != target_branch:
        raise RuntimeError("manual-gate parent checkout is not on the configured target branch")
    if accelerator_binding["head_commit"] != desired_commit:
        raise RuntimeError("manual-gate accelerator checkout is not at the accepted commit")
    if accelerator_binding["head_tree"] != desired_tree:
        raise RuntimeError("manual-gate accelerator tree does not match the accepted release")
    if str(_git(accelerator, "status", "--porcelain=v1", "--untracked-files=all")):
        raise RuntimeError("manual-gate accelerator checkout is not clean")
    tree_record = str(_git(parent, "ls-tree", "HEAD", "--", "ipfs_accelerate_py"))
    fields = tree_record.split()
    if len(fields) < 3 or fields[:2] != ["160000", "commit"]:
        raise RuntimeError("manual-gate parent HEAD has no accelerator gitlink")
    old_gitlink = fields[2].lower()
    if old_gitlink == desired_commit:
        raise RuntimeError("manual-gate refuses an externally pre-pinned gitlink")
    index_fields = str(
        _git(parent, "ls-files", "--stage", "--", "ipfs_accelerate_py")
    ).split()
    if (
        len(index_fields) < 4
        or index_fields[0] != "160000"
        or index_fields[1].lower() != old_gitlink
        or index_fields[2] != "0"
    ):
        raise RuntimeError("manual-gate refuses an externally staged gitlink pin")
    normalized_protected = tuple(sorted(set(str(item) for item in protected_paths)))
    if not normalized_protected or any(
        not item
        or item.startswith("/")
        or ".." in Path(item).parts
        for item in normalized_protected
    ):
        raise RuntimeError("manual-gate protected path set is invalid")
    protected_blobs = {
        item: str(_git(parent, "rev-parse", f"HEAD:{item}")).lower()
        for item in normalized_protected
    }
    status_lines = tuple(
        line for line in str(_git(parent, "status", "--porcelain=v1", "--untracked-files=all")).splitlines() if line
    )
    if len(status_lines) != 1 or status_lines[0][3:] != "ipfs_accelerate_py":
        raise RuntimeError("manual-gate parent checkout has changes beyond the intended gitlink")
    intent: dict[str, Any] = {
        "schema": GITLINK_PIN_INTENT_SCHEMA,
        "operation_id": operation_id,
        "path": "ipfs_accelerate_py",
        "target_branch": target_branch,
        "parent_before": parent_binding,
        "accelerator": accelerator_binding,
        "old_gitlink_commit": old_gitlink,
        "new_gitlink_commit": desired_commit,
        "new_gitlink_tree": desired_tree,
        "protected_blobs": protected_blobs,
        "checkout_lease_set": [
            {
                key: lease_by_root[str(repository)][key]
                for key in (
                    "repository_role",
                    "repository_id",
                    "repository_root",
                    "lock_path",
                    "lease_id",
                    "record_cid",
                )
            }
            for repository in (parent, accelerator)
        ],
    }
    intent["checkout_lease_set_id"] = content_id(
        "manual-gate-checkout-lease-set",
        {"leases": intent["checkout_lease_set"]},
    )
    intent["intent_id"] = content_id("manual-gate-gitlink-pin-intent", intent)
    return intent


def _gitlink_effect_commit(parent: Path, intent: Mapping[str, Any]) -> str:
    base = str(intent["parent_before"]["head_commit"])
    operation_id = str(intent["operation_id"])
    commits = str(
        _git(parent, "rev-list", "--first-parent", "--max-count=64", f"{base}..HEAD")
    ).splitlines()
    matches: list[str] = []
    for commit in commits:
        message = str(_git(parent, "show", "-s", "--format=%B", commit))
        if f"Manual-Gate-Operation: {operation_id}" not in message.splitlines():
            continue
        parents = str(_git(parent, "show", "-s", "--format=%P", commit)).split()
        if len(parents) != 1 or parents[0] != base:
            raise RuntimeError("manual-gate gitlink effect commit has a foreign parent")
        delta = str(_git(parent, "diff-tree", "--no-commit-id", "--raw", "-r", commit)).splitlines()
        if len(delta) != 1 or not delta[0].endswith("\tipfs_accelerate_py"):
            raise RuntimeError("manual-gate gitlink effect commit changed another path")
        fields = delta[0].split()
        if (
            len(fields) < 5
            or fields[0][1:] != "160000"
            or fields[1] != "160000"
            or fields[2].lower() != intent["old_gitlink_commit"]
            or fields[3].lower() != intent["new_gitlink_commit"]
        ):
            raise RuntimeError("manual-gate gitlink effect delta is not exact")
        matches.append(commit.lower())
    if len(matches) != 1:
        raise RuntimeError("manual-gate gitlink effect commit is missing or ambiguous")
    return matches[0]


def apply_or_rederive_gitlink_pin(
    *,
    parent: Path,
    intent: Mapping[str, Any],
    allow_apply: bool = True,
) -> dict[str, Any]:
    expected_keys = {
        "schema",
        "operation_id",
        "path",
        "target_branch",
        "parent_before",
        "accelerator",
        "old_gitlink_commit",
        "new_gitlink_commit",
        "new_gitlink_tree",
        "protected_blobs",
        "checkout_lease_set",
        "checkout_lease_set_id",
        "intent_id",
    }
    if (
        set(intent) != expected_keys
        or intent.get("schema") != GITLINK_PIN_INTENT_SCHEMA
        or intent.get("intent_id")
        != content_id(
            "manual-gate-gitlink-pin-intent",
            {key: value for key, value in intent.items() if key != "intent_id"},
        )
    ):
        raise RuntimeError("manual-gate gitlink intent is invalid")
    parent = parent.resolve()
    accelerator = Path(str(intent["accelerator"]["repository_root"])).resolve()
    base = str(intent["parent_before"]["head_commit"])
    head = str(_git(parent, "rev-parse", "HEAD")).lower()
    if head == base:
        if not allow_apply:
            raise RuntimeError("manual-gate gitlink effect has not been applied")
        current_accelerator = _checkout_binding(
            accelerator, str(intent["accelerator"]["repository_id"])
        )
        parent_status = tuple(
            line
            for line in str(
                _git(parent, "status", "--porcelain=v1", "--untracked-files=all")
            ).splitlines()
            if line
        )
        if (
            current_accelerator != intent["accelerator"]
            or str(_git(accelerator, "status", "--porcelain=v1", "--untracked-files=all"))
            or str(_git(parent, "branch", "--show-current"))
            != intent["target_branch"]
            or len(parent_status) != 1
            or parent_status[0][3:] != "ipfs_accelerate_py"
            or any(
                str(_git(parent, "rev-parse", f"HEAD:{path}")).lower() != blob
                for path, blob in intent["protected_blobs"].items()
            )
        ):
            raise RuntimeError("manual-gate checkout changed after effect preparation")
        current = str(_git(parent, "ls-tree", "HEAD", "--", "ipfs_accelerate_py")).split()
        if len(current) < 3 or current[2].lower() != intent["old_gitlink_commit"]:
            raise RuntimeError("manual-gate gitlink changed after effect preparation")
        index_fields = str(
            _git(parent, "ls-files", "--stage", "--", "ipfs_accelerate_py")
        ).split()
        if (
            len(index_fields) < 4
            or index_fields[0] != "160000"
            or index_fields[1].lower() != intent["old_gitlink_commit"]
            or index_fields[2] != "0"
        ):
            raise RuntimeError("manual-gate staged gitlink changed after preparation")
        _git(
            parent,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{intent['new_gitlink_commit']},ipfs_accelerate_py",
        )
        cached = str(_git(parent, "diff", "--cached", "--raw", "--no-renames")).splitlines()
        if len(cached) != 1 or not cached[0].endswith("\tipfs_accelerate_py"):
            raise RuntimeError("manual-gate staged delta is not the isolated gitlink")
        _git(
            parent,
            "commit",
            "-m",
            "DQK-056: pin validated accelerator control-plane release",
            "-m",
            f"Manual-Gate-Operation: {intent['operation_id']}",
        )
    effect_commit = _gitlink_effect_commit(parent, intent)
    effect_tree = str(_git(parent, "rev-parse", f"{effect_commit}^{{tree}}")).lower()
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", effect_commit, "HEAD"],
        cwd=parent,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode:
        raise RuntimeError("manual-gate gitlink effect is not admitted by current HEAD")
    receipt: dict[str, Any] = {
        "schema": GITLINK_PIN_RECEIPT_SCHEMA,
        "operation_id": intent["operation_id"],
        "intent_id": intent["intent_id"],
        "path": "ipfs_accelerate_py",
        "base_parent_commit": base,
        "base_parent_tree": intent["parent_before"]["head_tree"],
        "effect_commit": effect_commit,
        "effect_tree": effect_tree,
        "old_gitlink_commit": intent["old_gitlink_commit"],
        "new_gitlink_commit": intent["new_gitlink_commit"],
        "new_gitlink_tree": intent["new_gitlink_tree"],
        "parent_repository_id": intent["parent_before"]["repository_id"],
        "accelerator_repository_id": intent["accelerator"]["repository_id"],
        "checkout_lease_set_id": intent["checkout_lease_set_id"],
    }
    receipt["receipt_id"] = content_id("manual-gate-gitlink-pin-receipt", receipt)
    return receipt


def validate_gitlink_pin_receipt(
    *,
    parent: Path,
    accelerator: Path,
    receipt: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> None:
    expected = apply_or_rederive_gitlink_pin(
        parent=parent, intent=intent, allow_apply=False
    )
    if expected != dict(receipt):
        raise RuntimeError("manual-gate gitlink receipt does not match authoritative Git")
    parent = parent.resolve()
    accelerator = accelerator.resolve()
    if str(_git(parent, "branch", "--show-current")) != intent.get("target_branch"):
        raise RuntimeError("manual-gate parent branch changed after gitlink pin")
    current_entry = str(
        _git(parent, "ls-tree", "HEAD", "--", "ipfs_accelerate_py")
    ).split()
    pinned_gitlink = str(intent.get("new_gitlink_commit") or "").strip().lower()
    if (
        len(current_entry) < 3
        or current_entry[:2] != ["160000", "commit"]
        or not re.fullmatch(r"[0-9a-f]{40}", pinned_gitlink)
    ):
        raise RuntimeError("manual-gate accelerator gitlink was reverted or replaced")
    current_gitlink = current_entry[2].lower()
    if current_gitlink != pinned_gitlink:
        # Post-pin accelerate tip advances (control-plane fixes) keep the pin
        # as an ancestor of the live gitlink; only true reverts fail closed.
        ancestry = subprocess.run(
            [
                "git",
                "-C",
                str(accelerator),
                "merge-base",
                "--is-ancestor",
                pinned_gitlink,
                current_gitlink,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestry.returncode != 0:
            raise RuntimeError(
                "manual-gate accelerator gitlink was reverted or replaced"
            )
    protected = intent.get("protected_blobs")
    # Validate protected bootstrap bytes at the pin commit itself.  Later
    # first-parent commits may intentionally evolve protected ops scripts
    # without undoing the accelerator pin admission.
    pin_commit = str(receipt.get("effect_commit") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", pin_commit) is None:
        pin_commit = str(_git(parent, "rev-parse", "HEAD")).lower()
    if not isinstance(protected, Mapping) or not protected or any(
        str(_git(parent, "rev-parse", f"{pin_commit}:{path}")).lower() != str(blob).lower()
        for path, blob in protected.items()
    ):
        raise RuntimeError("manual-gate protected bootstrap artifacts changed after pin")
    # Working trees must stay clean. Exact HEAD/tree equality against the pin is
    # only required when the live gitlink still equals the pin; after an admitted
    # tip advance the accelerate checkout tracks the live gitlink instead.
    parent_dirty = str(
        _git(parent, "status", "--porcelain=v1", "--untracked-files=all")
    )
    accelerator_dirty = str(
        _git(accelerator, "status", "--porcelain=v1", "--untracked-files=all")
    )
    if parent_dirty or accelerator_dirty:
        raise RuntimeError("manual-gate pinned checkouts are not exact and clean")
    accelerator_head = str(_git(accelerator, "rev-parse", "HEAD")).lower()
    accelerator_tree = str(_git(accelerator, "rev-parse", "HEAD^{tree}")).lower()
    pinned_tree = str(intent.get("new_gitlink_tree") or "").strip().lower()
    if current_gitlink == pinned_gitlink:
        if accelerator_head != pinned_gitlink or accelerator_tree != pinned_tree:
            raise RuntimeError("manual-gate pinned checkouts are not exact and clean")
    elif accelerator_head != current_gitlink:
        raise RuntimeError("manual-gate pinned checkouts are not exact and clean")


def rollover_binding(
    *,
    output: Mapping[str, Any],
    snapshot: Any,
    source_identity: Mapping[str, Any],
    writer: tuple[str, int] | None,
    materialization_receipts: Sequence[Mapping[str, Any]],
    content_identity: Any,
) -> dict[str, Any]:
    """Bind DQK-081 to the actual current generation, never a claimed CID."""

    changed = output.get("generation_changed")
    if (
        not isinstance(changed, bool)
        or output.get("active_plan_root_cid") != snapshot.plan_root_cid
        or output.get("accepted_plan_root_cid") != snapshot.plan_root_cid
        or output.get("repository_tree_id") != snapshot.repository_tree_id
    ):
        raise RuntimeError("DQK-081 output must type generation_changed as boolean")
    selected: dict[str, Any] | None = None
    if changed and writer is None:
        raise RuntimeError("DQK-081 changed rollover requires a writer fence")
    if changed:
        receipt_cid = str(output.get("generation_rollover_receipt_cid") or "")
        candidates = [row for row in materialization_receipts if row.get("receipt_cid") == receipt_cid]
        if len(candidates) != 1:
            raise RuntimeError("DQK-081 rollover receipt is not authoritative")
        selected = dict(candidates[0])
        body = strict_json_object(
            str(selected.get("body_json") or ""), noun="DQK-081 materialization receipt"
        )
        if (
            body.get("plan_root_cid") != snapshot.plan_root_cid
            or body.get("repository_tree_id") != snapshot.repository_tree_id
            or str(selected.get("receipt_cid") or "")
            != str(content_identity(body))
        ):
            raise RuntimeError("DQK-081 rollover receipt does not bind the current generation")
        selected["body"] = body
    elif str(output.get("generation_rollover_receipt_cid") or ""):
        raise RuntimeError("DQK-081 unchanged generation cannot claim a rollover receipt")
    binding: dict[str, Any] = {
        "schema": ROLLOVER_BINDING_SCHEMA,
        "generation_changed": changed,
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "projection_cid": snapshot.projection_cid,
        "task_source_identity": dict(source_identity),
        "writer": (
            {"writer_id": writer[0], "fencing_token": writer[1]}
            if writer is not None
            else None
        ),
        "materialization_receipt": selected,
    }
    binding["binding_id"] = content_id("manual-gate-rollover-binding", binding)
    return binding
