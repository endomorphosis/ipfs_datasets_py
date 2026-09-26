"""Bounded, isolated native DuckLake history; never production activation.

The registry remains authority. This optional sink writes metadata only, owns a
fresh local namespace, and reconciles events plus a batch marker in one DuckLake
transaction. Its process lock is local ownership, not a distributed fence or a
DQK-102 approval. No CAS file is registered/transferred into DATA_PATH. Native
DuckLake creates its own Parquet files. No training or publication is performed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import stat
import threading
from typing import Any, Mapping

from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.ducklake import capabilities as caps

BATCH_SCHEMA = "autoencoder-ducklake-batch-v1"
RECEIPT_SCHEMA = "autoencoder-ducklake-commit-v1"
MAX_BATCH_BYTES = 1_048_576
MAX_EVENTS = 10
_AUTHOR = "autoencoder-isolated-history-v1"


class HistoryError(ValueError):
    """Invalid history input, incompatible runtime, or unverifiable commit."""


def _json(value: Any) -> bytes:
    try:
        raw = canonical_json_bytes(value)
        if len(raw) > MAX_BATCH_BYTES:
            raise HistoryError("canonical batch byte bound exceeded")
        return raw
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise HistoryError(str(exc)) from exc


def _identity(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value)).hexdigest()


def _plain(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [50_000, MAX_BATCH_BYTES]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise HistoryError("JSON depth/node bound exceeded")
    kind = type(value)
    if kind in (str, int, bool, type(None)):
        if kind is str:
            if len(value) > MAX_BATCH_BYTES:
                raise HistoryError("string bound exceeded")
            try:
                budget[1] -= len(value.encode("utf-8"))
            except UnicodeError as exc:
                raise HistoryError("invalid UTF-8 string") from exc
            if budget[1] < 0:
                raise HistoryError("aggregate JSON string byte bound exceeded")
        return
    if kind is float and math.isfinite(value):
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise HistoryError("JSON object keys must be strings")
            _plain(key, depth=depth + 1, budget=budget)
            _plain(item, depth=depth + 1, budget=budget)
        return
    if kind is list:
        for item in value:
            _plain(item, depth=depth + 1, budget=budget)
        return
    raise HistoryError("only finite ordinary JSON values are supported")


def _closed(value: Any, fields: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise HistoryError(f"invalid {name} fields")


def _text(value: Any, name: str) -> None:
    if type(value) is not str or not value or len(value) > 4096 or "\x00" in value:
        raise HistoryError(f"invalid {name}")


def _lexical_path(value: Any) -> Path:
    _text(value, "absolute local path")
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        raise HistoryError("path must be canonical and absolute")
    return path


def validate_history_source(source: Mapping[str, Any]) -> dict[str, Any]:
    """Validate configured namespace binding without implying issuer authority."""
    _closed(source, {"source_id", "database_path", "artifact_root"}, "source")
    _text(source["source_id"], "source_id")
    _lexical_path(source["database_path"])
    _lexical_path(source["artifact_root"])
    return json.loads(_json(source))


def _validate_body(source: Any, events: Any) -> None:
    validate_history_source(source)
    if type(events) is not list or not 1 <= len(events) <= MAX_EVENTS:
        raise HistoryError("batch requires 1..10 events")
    ids = []
    for event in events:
        _closed(event, {"event_id", "kind", "payload", "created_at", "version", "variant"}, "event")
        for key in ("event_id", "kind"):
            _text(event[key], key)
        if type(event["created_at"]) is not float or not math.isfinite(event["created_at"]):
            raise HistoryError("created_at must retain the registry finite DOUBLE value")
        if type(event["payload"]) is not dict:
            raise HistoryError("event payload must be an object")
        for key in ("version", "variant"):
            if event[key] is not None and type(event[key]) is not dict:
                raise HistoryError(f"event {key} must be an object or null")
        ids.append(event["event_id"])
    if ids != sorted(set(ids)):
        raise HistoryError("event IDs must be unique and sorted")
    _plain({"source": source, "events": events})


def build_history_batch(source: Mapping[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Detach fixed immutable event records; no live run/head enrichment."""
    if type(events) is not list or not 1 <= len(events) <= MAX_EVENTS or any(type(event) is not dict for event in events):
        raise HistoryError("events must be ordinary JSON objects")
    if any(type(event.get("event_id")) is not str for event in events):
        raise HistoryError("invalid event_id")
    ordered = sorted(events, key=lambda event: event["event_id"])
    _validate_body(source, ordered)
    body = {"schema": BATCH_SCHEMA, "source": source, "events": ordered}
    batch = {**body, "batch_id": _identity(body)}
    return validate_history_batch(batch)


def validate_history_batch(batch: Mapping[str, Any]) -> dict[str, Any]:
    _closed(batch, {"schema", "source", "events", "batch_id"}, "batch")
    if batch["schema"] != BATCH_SCHEMA:
        raise HistoryError("unsupported batch schema")
    _validate_body(batch["source"], batch["events"])
    body = {key: value for key, value in batch.items() if key != "batch_id"}
    if type(batch["batch_id"]) is not str or batch["batch_id"] != _identity(body):
        raise HistoryError("batch identity mismatch")
    return json.loads(_json(batch))


def _read(path: Path, maximum: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise HistoryError("invalid bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        fingerprint = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if len(raw) != info.st_size or fingerprint(os.fstat(fd)) != fingerprint(info) or fingerprint(path.lstat()) != fingerprint(info):
            raise HistoryError("file changed while reading")
        return raw
    finally:
        os.close(fd)


def _literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _native_connection() -> tuple[Any, dict[str, Any]]:
    """Reuse DQK capability pins and the proven explicit local LOAD order."""
    import duckdb
    if duckdb.__version__ != caps.REQUIRED_DUCKDB_VERSION_TEXT:
        raise HistoryError("DuckDB version does not match pinned runtime")
    machine = {"aarch64": "linux_arm64", "x86_64": "linux_amd64"}.get(platform.machine().lower())
    if machine is None:
        raise HistoryError("unsupported native platform")
    pins = caps.platform_extension_pins(machine)
    loaded = {}
    paths = {}
    for name in caps.explicit_load_order():
        path = Path.home() / ".duckdb/extensions" / ("v" + duckdb.__version__) / machine / (name + ".duckdb_extension")
        if path.resolve() != path:
            raise HistoryError("extension path is aliased")
        raw = _read(path, 128 * 1024 * 1024)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != pins[name].bin_digest.removeprefix("sha256:"):
            raise HistoryError(f"{name} extension digest mismatch")
        loaded[name] = digest
        paths[name] = path
    connection = duckdb.connect(":memory:", config={"autoinstall_known_extensions": "false", "autoload_known_extensions": "false", "allow_unsigned_extensions": "false", "threads": "1"})
    try:
        for name, path in paths.items():
            if hashlib.sha256(_read(path, 128 * 1024 * 1024)).hexdigest() != loaded[name]:
                raise HistoryError("extension changed before LOAD")
            connection.execute(f"LOAD {_literal(path)}")
        # Pinned build supports per-ATTACH migration control. The historical
        # probe explicitly records that the global migration setting is absent.
        return connection, {"duckdb": duckdb.__version__, "platform": machine, "extensions": loaded}
    except BaseException as error:
        try:
            connection.close()
        except BaseException as cleanup:
            error.add_note(f"native connection cleanup failed: {type(cleanup).__name__}")
        raise


class IsolatedNativeDuckLakeHistory:
    """Caller-owned local sink; production namespaces/activation unsupported."""

    def __init__(self, root: str | Path, *, create: bool = False, production: bool = False, max_history_bytes: int = 256 * 1024 * 1024):
        if type(create) is not bool or type(production) is not bool or production:
            raise HistoryError("production activation is held; flags must be exact booleans")
        if type(max_history_bytes) is not int or not 1 <= max_history_bytes <= 256 * 1024 * 1024:
            raise HistoryError("history byte cap must be an exact integer within 1..256MiB")
        self._pid = os.getpid()
        self._max_history_bytes = max_history_bytes
        self._connection = None
        self._fd = None
        self._closed = False
        self._mutex = threading.RLock()
        self.root = _lexical_path(str(root))
        if self.root.resolve() != self.root:
            raise HistoryError("history root is aliased")
        self._catalog = self.root / "history.ducklake"
        self._data = self.root / "data"
        self._descriptor = self.root / "history.json"
        try:
            if create:
                self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
            if not self.root.is_dir():
                raise HistoryError("history root does not exist")
            self._root_identity = (self.root.stat().st_dev, self.root.stat().st_ino)
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            self._fd = os.open(self.root / "owner.lock", flags, 0o600)
            if not stat.S_ISREG(os.fstat(self._fd).st_mode):
                raise HistoryError("owner lock must be regular")
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._guard_paths()
            if not create and (not self._catalog.is_file() or not self._data.is_dir()):
                raise HistoryError("incomplete history namespace")
            self._connection, runtime = _native_connection()
            body = {"schema": "autoencoder-isolated-history-v1", "scope": "isolated_history", "root": str(self.root), "catalog_path": str(self._catalog), "data_path": str(self._data), "runtime": runtime, "max_history_bytes": max_history_bytes, "production_activated": False}
            self._identity = {**body, "history_id": _identity(body)}
            self._descriptor_bytes = _json(self._identity)
            if not create and _read(self._descriptor, 16_384) != self._descriptor_bytes:
                raise HistoryError("history descriptor/runtime mismatch")
            self._connection.execute(f"ATTACH {_literal('ducklake:' + str(self._catalog))} AS history (DATA_PATH {_literal(self._data)}, CREATE_IF_NOT_EXISTS {str(create).lower()}, OVERRIDE_DATA_PATH false, AUTOMATIC_MIGRATION false, DATA_INLINING_ROW_LIMIT 0)")
            version = self._connection.execute("SELECT value FROM __ducklake_metadata_history.main.ducklake_metadata WHERE key='version'").fetchone()
            if version != ("1.0",):
                raise HistoryError("DuckLake catalog version mismatch")
            if create:
                self._connection.execute("BEGIN")
                self._connection.execute("CREATE TABLE history.sources (source_id VARCHAR, source_json VARCHAR)")
                self._connection.execute("CREATE TABLE history.events (source_id VARCHAR, event_id VARCHAR, event_json VARCHAR)")
                self._connection.execute("CREATE TABLE history.commits (batch_id VARCHAR, batch_json VARCHAR)")
                self._connection.execute("CREATE TABLE history.identity (identity_json VARCHAR)")
                self._connection.execute("INSERT INTO history.identity VALUES (?)", [self._descriptor_bytes.decode()])
                self._connection.execute("COMMIT")
                fd = os.open(self._descriptor, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(self._descriptor_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            self._path_identities = {str(path): (path.stat().st_dev, path.stat().st_ino) for path in (self._catalog, self._data)}
            self._boundary()
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                error.add_note(f"history cleanup failed: {type(cleanup).__name__}")
            raise

    @property
    def identity(self) -> dict[str, Any]:
        return json.loads(_json(self._identity))

    def _owner_process(self) -> None:
        if os.getpid() != self._pid:
            raise HistoryError("history cannot be used or closed by an inherited process")

    def _guard_paths(self) -> int:
        self._owner_process()
        for raw_path, identity in getattr(self, "_path_identities", {}).items():
            path = Path(raw_path)
            if path.resolve() != path or (path.stat().st_dev, path.stat().st_ino) != identity:
                raise HistoryError("history catalog/data path identity changed")
        if self.root.resolve() != self.root or (self.root.stat().st_dev, self.root.stat().st_ino) != self._root_identity:
            raise HistoryError("history root changed")
        if self._fd is not None:
            actual = os.fstat(self._fd)
            path = (self.root / "owner.lock").lstat()
            if not stat.S_ISREG(path.st_mode) or (path.st_dev, path.st_ino) != (actual.st_dev, actual.st_ino):
                raise HistoryError("history lock changed")
        total = 0
        for index, path in enumerate(self.root.rglob("*")):
            info = path.lstat()
            mode = info.st_mode
            if stat.S_ISREG(mode):
                if info.st_nlink != 1:
                    raise HistoryError("history namespace contains hard-linked files")
                total += info.st_size
            if index >= 10_000 or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise HistoryError("history namespace contains aliases/special files or exceeds file bound")
        if total > self._max_history_bytes:
            raise HistoryError("history namespace exceeds byte cap")
        return total

    def _boundary(self) -> None:
        if self._closed:
            raise HistoryError("history is closed")
        self._guard_paths()
        if _read(self._descriptor, 16_384) != self._descriptor_bytes:
            raise HistoryError("history descriptor changed")
        rows = self._connection.execute("SELECT identity_json FROM history.identity LIMIT 2").fetchall()
        if rows != [(self._descriptor_bytes.decode(),)]:
            raise HistoryError("catalog identity mismatch")

    def _existing(self, batch: dict[str, Any]) -> list[dict[str, Any]]:
        source = batch["source"]
        rows = self._connection.execute("SELECT source_json FROM history.sources WHERE source_id=? LIMIT 2", [source["source_id"]]).fetchall()
        if rows and rows != [(_json(source).decode(),)]:
            raise HistoryError("source namespace binding conflict")
        missing = []
        for event in batch["events"]:
            found = self._connection.execute("SELECT event_json FROM history.events WHERE source_id=? AND event_id=? LIMIT 2", [source["source_id"], event["event_id"]]).fetchall()
            if found and found != [(_json(event).decode(),)]:
                raise HistoryError("event identity/content conflict")
            if not found:
                missing.append(event)
        if not rows and len(missing) != len(batch["events"]):
            raise HistoryError("events lack source binding")
        return missing

    def _lookup(self, batch: dict[str, Any]) -> dict[str, Any] | None:
        missing = self._existing(batch)
        rows = self._connection.execute("SELECT batch_json FROM history.commits WHERE batch_id=? LIMIT 2", [batch["batch_id"]]).fetchall()
        snapshots = self._connection.execute("SELECT snapshot_id FROM history.snapshots() WHERE author=? AND commit_message=? LIMIT 2", [_AUTHOR, batch["batch_id"]]).fetchall()
        if not rows:
            if snapshots:
                raise HistoryError("native commit has no batch marker")
            return None
        if rows != [(_json(batch).decode(),)] or missing or len(snapshots) != 1:
            raise HistoryError("committed marker/event/snapshot mismatch")
        snapshot = snapshots[0][0]
        if type(snapshot) is not int or snapshot < 0:
            raise HistoryError("invalid native snapshot identity")
        return {"schema": RECEIPT_SCHEMA, "scope": "isolated_history", "history_id": self._identity["history_id"], "batch_id": batch["batch_id"], "source_id": batch["source"]["source_id"], "event_ids": [event["event_id"] for event in batch["events"]], "event_count": len(batch["events"]), "snapshot_id": snapshot, "event_payloads_verified": True, "production_activated": False, "admitted": False}

    def lookup(self, batch: Mapping[str, Any]) -> dict[str, Any] | None:
        self._owner_process()
        value = validate_history_batch(batch)
        with self._mutex:
            self._boundary()
            result = self._lookup(value)
            self._boundary()
            return result

    def append(self, batch: Mapping[str, Any]) -> dict[str, Any]:
        self._owner_process()
        value = validate_history_batch(batch)
        with self._mutex:
            self._boundary()
            prior = self._lookup(value)
            if prior is not None:
                self._boundary()
                return prior
            if self._guard_paths() + max(8 * 1024 * 1024, 8 * len(_json(value))) > self._max_history_bytes:
                raise HistoryError("history byte cap cannot fit conservative batch reserve")
            self._connection.execute("BEGIN")
            try:
                missing = self._existing(value)
                source = value["source"]
                if not self._connection.execute("SELECT 1 FROM history.sources WHERE source_id=? LIMIT 1", [source["source_id"]]).fetchone():
                    self._connection.execute("INSERT INTO history.sources VALUES (?,?)", [source["source_id"], _json(source).decode()])
                if missing:
                    self._connection.executemany("INSERT INTO history.events VALUES (?,?,?)", [[source["source_id"], event["event_id"], _json(event).decode()] for event in missing])
                self._connection.execute("INSERT INTO history.commits VALUES (?,?)", [value["batch_id"], _json(value).decode()])
                self._connection.execute("CALL history.set_commit_message(?, ?)", [_AUTHOR, value["batch_id"]])
                self._connection.execute("COMMIT")
            except BaseException:
                try:
                    self._connection.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            # A lost response after COMMIT is resolved through exactly this same
            # lookup on reopen. Never infer success from an attempted write.
            result = self._lookup(value)
            self._boundary()
            if result is None:
                raise HistoryError("commit could not be verified")
            return result

    def close(self) -> None:
        self._owner_process()
        with getattr(self, "_mutex", threading.RLock()):
            self._closed = True
            try:
                if self._connection is not None:
                    self._connection.close()
            finally:
                self._connection = None
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None

    def __enter__(self) -> "IsolatedNativeDuckLakeHistory":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.close()
        except BaseException:
            if exc is None:
                raise
