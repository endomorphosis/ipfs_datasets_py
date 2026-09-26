"""Durable exact-operation intents for an owner-controlled daemon invocation.

This journal is not lease authority. Registry lookup remains authoritative on
every replay, including receipts already saved locally. Historical completion
does not revalidate artifacts. Only the five explicit registry methods below
are dispatched; errors never invent a replacement operation ID.

The persistent sibling lock excludes cooperating processes. Paths must remain
privately owned: boundary checks detect persistent replacement, not a hostile
writer that changes and restores files between checks. Importing opens nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any
import uuid


SCHEMA_VERSION = "autoencoder-daemon-operation-journal-v1"
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_OPERATIONS = 1024
MAX_VALUE_BYTES = 65_536
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 500_000
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SLOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_COMMANDS = {
    "CreateRun": ("create_run", ("run_id", "variant_id", "base_version_id", "spec")),
    "ClaimRun": ("claim_run", ("run_id", "worker_id", "lease_seconds")),
    "RenewLease": ("renew_lease", ("lease", "lease_seconds")),
    "CompleteRun": ("complete_run", ("lease", "artifact", "result")),
    "FailRun": ("fail_run", ("lease", "result")),
}


class DaemonOperationJournalError(ValueError):
    """Invalid, conflicting, unavailable or changed durable journal state."""


def _json(value: Any, limit: int = MAX_VALUE_BYTES) -> bytes:
    remaining = MAX_JSON_NODES

    def check(item: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > MAX_JSON_DEPTH:
            raise DaemonOperationJournalError("JSON structural bound exceeded")
        kind = type(item)
        if item is None or kind in (bool, int):
            return
        if kind is float:
            if not math.isfinite(item):
                raise DaemonOperationJournalError("non-finite JSON number")
            return
        if kind is str:
            if len(item) > limit:
                raise DaemonOperationJournalError("JSON string exceeds byte bound")
            return
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise DaemonOperationJournalError("JSON keys must be strings")
                check(key, depth + 1)
                check(child, depth + 1)
            return
        if kind is list:
            for child in item:
                check(child, depth + 1)
            return
        raise DaemonOperationJournalError("only ordinary JSON values are supported")

    check(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise DaemonOperationJournalError("invalid canonical JSON") from exc
    if len(raw) > limit:
        raise DaemonOperationJournalError("JSON byte bound exceeded")
    return raw


def _copy(value: Any, limit: int = MAX_VALUE_BYTES) -> Any:
    return json.loads(_json(value, limit))


def _mapping(value: Any) -> dict:
    if not isinstance(value, Mapping):
        raise DaemonOperationJournalError("expected a mapping")
    return _copy(dict(value))


def _token(value: Any) -> None:
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise DaemonOperationJournalError("invalid bounded identifier")


def _lease(value: Any) -> None:
    if type(value) is not dict or set(value) != {
        "run_id", "worker_id", "owner_generation", "attempt", "fence", "expires_at",
    }:
        raise DaemonOperationJournalError("invalid lease fields")
    for name in ("run_id", "worker_id"):
        _token(value[name])
    for name in ("owner_generation", "attempt", "fence"):
        if type(value[name]) is not int or value[name] < 1:
            raise DaemonOperationJournalError("invalid lease counter")
    if type(value["expires_at"]) not in (int, float):
        raise DaemonOperationJournalError("invalid lease expiry")


def _payload(command: str, value: Any) -> dict:
    if type(command) is not str or command not in _COMMANDS:
        raise DaemonOperationJournalError("unsupported registry command")
    payload = _mapping(value)
    if set(payload) != set(_COMMANDS[command][1]):
        raise DaemonOperationJournalError("registry command fields differ")
    for name in ("run_id", "variant_id", "base_version_id", "worker_id"):
        if name in payload:
            _token(payload[name])
    if "lease_seconds" in payload:
        seconds = payload["lease_seconds"]
        if type(seconds) not in (int, float) or not 0 < seconds <= 86_400:
            raise DaemonOperationJournalError("invalid lease duration")
    if "lease" in payload:
        _lease(payload["lease"])
    if "spec" in payload and type(payload["spec"]) is not dict:
        raise DaemonOperationJournalError("spec must be an object")
    if "result" in payload:
        result = payload["result"]
        if type(result) is not dict or result.get("admitted") is not False:
            raise DaemonOperationJournalError("result requires admitted=false")
    if "artifact" in payload:
        artifact = payload["artifact"]
        if (type(artifact) is not dict or set(artifact) != {"sha256", "bytes"}
                or type(artifact["sha256"]) is not str or not _HEX.fullmatch(artifact["sha256"])
                or type(artifact["bytes"]) is not int or artifact["bytes"] < 1):
            raise DaemonOperationJournalError("invalid artifact descriptor")
    # Match the registry bound on the complete command, not payload alone.
    _json({"command": command, "payload": payload})
    return payload


def _receipt(value: Any, operation: dict) -> dict:
    receipt = _mapping(value)
    common = {"schema", "operation_id", "command", "admitted"}
    command = operation["command"]
    fields = {
        "CreateRun": {"run_id", "status"},
        "ClaimRun": {"lease"}, "RenewLease": {"lease"},
        "CompleteRun": {"run_id", "version_id", "event_id", "status", "promoted"},
        "FailRun": {"run_id", "event_id", "status"},
    }[command]
    if (set(receipt) != common | fields
            or receipt["schema"] != "ipfs_datasets_py/autoencoder-control@1"
            or receipt["operation_id"] != operation["operation_id"]
            or receipt["command"] != command or receipt["admitted"] is not False):
        raise DaemonOperationJournalError("registry receipt does not match operation")
    if "lease" in receipt:
        _lease(receipt["lease"])
    if "status" in receipt:
        expected = {"CreateRun": "queued", "CompleteRun": "completed", "FailRun": "failed"}[command]
        if receipt["status"] != expected:
            raise DaemonOperationJournalError("unexpected registry receipt status")
        run_id = operation["payload"].get("run_id", operation["payload"].get("lease", {}).get("run_id"))
        if receipt["run_id"] != run_id:
            raise DaemonOperationJournalError("registry receipt run differs")
    if command == "CompleteRun" and receipt["promoted"] is not False:
        raise DaemonOperationJournalError("completion cannot authorize promotion")
    return receipt


def _fingerprint(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_directory(path: Path) -> int:
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_fd
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class DurableDaemonOperationJournal:
    """One exclusive, bounded journal, opened on construction.

    Parent directories must already exist. ``operations()``, ``pending()``,
    ``receipt(slot)``, ``binding`` and metadata reads return detached JSON data.
    A pending operation is unresolved, not failed. Retrying ``invoke`` with its
    exact slot/command/payload resolves the registry before sending anything.
    Metadata is caller bookkeeping, never additional registry authority.
    ``create=False`` requires both the existing journal and its lock file; it
    never recreates either one. This is an existing-only open mode, not a ban
    on subsequent explicit metadata or operation writes by the caller.
    """

    def __init__(self, path: str | Path, binding: Mapping[str, Any], *, create: bool = True) -> None:
        if type(create) is not bool:
            raise DaemonOperationJournalError("create must be boolean")
        self._pid = os.getpid()
        self._mutex = threading.RLock()
        self._dir_fd = self._lock_fd = None
        self._closed = True
        self._poisoned = False
        self._expected = None
        candidate = Path(path).expanduser()
        if ".." in candidate.parts or not candidate.name:
            raise DaemonOperationJournalError("journal path must not traverse parents")
        self.path = candidate.absolute()
        self._name = self.path.name
        self._lock_name = f".{self._name}.lock"
        bound = _mapping(binding)
        try:
            self._dir_fd = _open_directory(self.path.parent)
            directory_info = os.fstat(self._dir_fd)
            self._parent_identity = (directory_info.st_dev, directory_info.st_ino)
            self._lock_fd = os.open(self._lock_name, os.O_RDWR | (os.O_CREAT if create else 0) | os.O_NOFOLLOW | os.O_NONBLOCK,
                                    0o600, dir_fd=self._dir_fd)
            info = os.fstat(self._lock_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size:
                raise DaemonOperationJournalError("lock must be an empty unaliased regular file")
            self._lock_identity = (info.st_dev, info.st_ino)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._closed = False
            raw, identity = self._read()
            self._expected = None if raw is None else (hashlib.sha256(raw).digest(), identity)
            if raw is None:
                if not create:
                    raise DaemonOperationJournalError("existing journal is required")
                data = {"schema_version": SCHEMA_VERSION, "journal_id": uuid.uuid4().hex,
                        "binding": bound, "metadata": {}, "operations": {}}
                self._persist(data)
            else:
                data = self._parse(raw)
                if _json(data["binding"]) != _json(bound):
                    raise DaemonOperationJournalError("journal binding differs")
            self._data = data
        except BaseException as exc:
            self.close()
            if isinstance(exc, OSError):
                raise DaemonOperationJournalError("journal path unavailable or already locked") from exc
            raise

    def _check(self) -> None:
        if os.getpid() != self._pid:
            raise DaemonOperationJournalError("journal cannot be used from a forked process")
        if self._closed or self._poisoned:
            raise DaemonOperationJournalError("journal is closed or unavailable after a write failure")
        descriptor = _open_directory(self.path.parent)
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != self._parent_identity:
                raise DaemonOperationJournalError("journal parent directory changed")
        finally:
            os.close(descriptor)
        info = os.stat(self._lock_name, dir_fd=self._dir_fd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != self._lock_identity or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DaemonOperationJournalError("journal lock path changed")

    def _read(self) -> tuple[bytes | None, tuple | None]:
        self._check()
        try:
            descriptor = os.open(self._name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._dir_fd)
        except FileNotFoundError:
            return None, None
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_JOURNAL_BYTES:
                raise DaemonOperationJournalError("journal must be a bounded unaliased regular file")
            raw = stream.read(MAX_JOURNAL_BYTES + 1)
            after = os.fstat(stream.fileno())
        named = os.stat(self._name, dir_fd=self._dir_fd, follow_symlinks=False)
        if len(raw) != info.st_size or _fingerprint(info) != _fingerprint(after) or _fingerprint(info) != _fingerprint(named):
            raise DaemonOperationJournalError("journal changed while reading")
        return raw, _fingerprint(info)

    def _unchanged(self) -> None:
        raw, identity = self._read()
        actual = None if raw is None else (hashlib.sha256(raw).digest(), identity)
        if actual != self._expected:
            raise DaemonOperationJournalError("journal file changed outside this owner")

    def _operation_id(self, slot: str, data: dict | None = None) -> str:
        document = self._data if data is None else data
        raw = _json({"journal_id": document["journal_id"], "binding": document["binding"], "slot": slot}, MAX_JOURNAL_BYTES)
        return "daemon-journal:" + hashlib.sha256(raw).hexdigest()

    def _parse(self, raw: bytes) -> dict:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise DaemonOperationJournalError("duplicate JSON key")
                result[key] = value
            return result
        try:
            data = json.loads(raw, object_pairs_hook=pairs,
                              parse_constant=lambda value: (_ for _ in ()).throw(DaemonOperationJournalError("non-finite JSON number")))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise DaemonOperationJournalError("invalid journal JSON") from exc
        if _json(data, MAX_JOURNAL_BYTES) != raw:
            raise DaemonOperationJournalError("journal JSON must be canonical")
        if type(data) is not dict or set(data) != {"schema_version", "journal_id", "binding", "metadata", "operations"}:
            raise DaemonOperationJournalError("journal fields differ")
        if data["schema_version"] != SCHEMA_VERSION or type(data["journal_id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", data["journal_id"]):
            raise DaemonOperationJournalError("unsupported journal identity")
        _mapping(data["binding"])
        metadata = _mapping(data["metadata"])
        for key in metadata:
            self._slot(key)
        operations = data["operations"]
        if type(operations) is not dict or len(operations) > MAX_OPERATIONS:
            raise DaemonOperationJournalError("operation count exceeds bound")
        for slot, operation in operations.items():
            self._slot(slot)
            if type(operation) is not dict or set(operation) != {"operation_id", "command", "payload", "receipt"}:
                raise DaemonOperationJournalError("operation fields differ")
            if operation["operation_id"] != self._operation_id(slot, data):
                raise DaemonOperationJournalError("operation identity differs")
            _payload(operation["command"], operation["payload"])
            if operation["receipt"] is not None:
                _receipt(operation["receipt"], operation)
        return data

    @staticmethod
    def _slot(slot: Any) -> None:
        if type(slot) is not str or not _SLOT.fullmatch(slot):
            raise DaemonOperationJournalError("invalid bounded journal slot")

    def _persist(self, data: dict) -> None:
        raw = _json(data, MAX_JOURNAL_BYTES)
        # Reserve a bounded reply for every unresolved intent before sending.
        pending_count = sum(row["receipt"] is None for row in data["operations"].values())
        if len(raw) + pending_count * MAX_VALUE_BYTES > MAX_JOURNAL_BYTES:
            raise DaemonOperationJournalError("journal has no reserved receipt capacity")
        self._unchanged()
        temporary = f".{self._name}.{uuid.uuid4().hex}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=self._dir_fd)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._unchanged()
            if self._expected is None:
                os.link(temporary, self._name, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd, follow_symlinks=False)
                os.unlink(temporary, dir_fd=self._dir_fd)
            else:
                os.replace(temporary, self._name, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd)
            os.fsync(self._dir_fd)
            saved, identity = self._read()
            if saved != raw:
                raise DaemonOperationJournalError("published journal differs")
            self._expected = hashlib.sha256(raw).digest(), identity
        except BaseException:
            self._poisoned = True
            raise
        finally:
            try:
                os.unlink(temporary, dir_fd=self._dir_fd)
            except OSError:
                pass

    def _record_receipt(self, slot: str, value: Any) -> dict:
        operation = self._data["operations"][slot]
        receipt = _receipt(value, operation)
        old = operation["receipt"]
        if old is not None:
            if _json(old) != _json(receipt):
                raise DaemonOperationJournalError("historical registry receipt differs")
        else:
            data = _copy(self._data, MAX_JOURNAL_BYTES)
            data["operations"][slot]["receipt"] = receipt
            self._persist(data)
            self._data = data
        return _copy(receipt)

    def invoke(self, registry: Any, slot: str, command: str, payload: Mapping[str, Any]) -> dict:
        """Persist exact intent, resolve history, then dispatch at most once.

        A failed send is followed by one ledger lookup. If lookup cannot resolve
        it, the original exception is preserved and the durable intent remains
        pending. A subsequent call/restart uses exactly the same operation ID.
        """
        with self._mutex:
            self._unchanged()
            self._slot(slot)
            supplied = _payload(command, payload)
            operation = self._data["operations"].get(slot)
            if operation is None:
                if len(self._data["operations"]) >= MAX_OPERATIONS:
                    raise DaemonOperationJournalError("operation count exceeds bound")
                operation = {"operation_id": self._operation_id(slot), "command": command,
                             "payload": supplied, "receipt": None}
                data = _copy(self._data, MAX_JOURNAL_BYTES)
                data["operations"][slot] = operation
                self._persist(data)
                self._data = data
            elif operation["command"] != command or _json(operation["payload"]) != _json(supplied):
                raise DaemonOperationJournalError("journal slot payload conflicts")
            operation_id = operation["operation_id"]
            resolved = registry.resolve_operation(operation_id, command, _copy(supplied))
            if resolved is not None:
                return self._record_receipt(slot, resolved)
            if operation["receipt"] is not None:
                raise DaemonOperationJournalError("saved receipt is absent from registry history")
            method, _fields = _COMMANDS[command]
            try:
                result = getattr(registry, method)(operation_id, **_copy(supplied))
            except Exception:
                try:
                    resolved = registry.resolve_operation(operation_id, command, _copy(supplied))
                except Exception:
                    resolved = None
                if resolved is not None:
                    return self._record_receipt(slot, resolved)
                raise
            return self._record_receipt(slot, result)

    @property
    def binding(self) -> dict:
        with self._mutex:
            self._unchanged()
            return _copy(self._data["binding"])

    def operations(self) -> dict:
        with self._mutex:
            self._unchanged()
            return _copy(self._data["operations"], MAX_JOURNAL_BYTES)

    def pending(self) -> dict:
        return {slot: operation for slot, operation in self.operations().items() if operation["receipt"] is None}

    def receipt(self, slot: str) -> dict | None:
        self._slot(slot)
        operation = self.operations().get(slot)
        return None if operation is None else operation["receipt"]

    def get_metadata(self, key: str, default: Any = None) -> Any:
        with self._mutex:
            self._unchanged()
            self._slot(key)
            return _copy(self._data["metadata"].get(key, default))

    def set_metadata(self, key: str, value: Any) -> None:
        with self._mutex:
            self._unchanged()
            self._slot(key)
            data = _copy(self._data, MAX_JOURNAL_BYTES)
            data["metadata"][key] = _copy(value)
            _json(data["metadata"])
            self._persist(data)
            self._data = data

    def close(self) -> None:
        with self._mutex:
            if os.getpid() != self._pid:
                raise DaemonOperationJournalError("forked process cannot close owner's journal")
            self._closed = True
            try:
                if self._lock_fd is not None:
                    os.close(self._lock_fd)
                    self._lock_fd = None
            finally:
                if self._dir_fd is not None:
                    os.close(self._dir_fd)
                    self._dir_fd = None

    def __enter__(self) -> DurableDaemonOperationJournal:
        self._check()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
