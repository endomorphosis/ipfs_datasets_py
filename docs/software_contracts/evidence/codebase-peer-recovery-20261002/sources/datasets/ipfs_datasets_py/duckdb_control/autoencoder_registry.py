"""Durable, single-owner control records for independent autoencoder workers.

This is the local owner implementation behind a future typed Quack adapter,
not a remote transport or a DuckLake catalog. Only the owner opens this file.
Workers exchange immutable artifacts and bounded commands, never connections.
No record, optimizer result, model selection or publication intent is an admit.
Importing this module opens no files, imports no DuckDB and starts no services.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from .connections import ConnectionManager
from .contracts import canonical_json_bytes, content_identity


SCHEMA = "ipfs_datasets_py/autoencoder-control@1"
RUN_LIFECYCLE_SCHEMA = "autoencoder-run-lifecycle@1"
RUN_TERMINAL_SCHEMA = "autoencoder-run-terminal@1"
_TERMINAL_RUN_STATES = frozenset({"cancelled", "superseded"})
MAX_COMMAND_BYTES = 65_536
MAX_INPUT_SNAPSHOT_BYTES = 1_048_576
INPUT_SNAPSHOT_SCHEMA = "autoencoder-daemon-corpus-inputs-v1"
_INPUT_SNAPSHOT_FIELDS = frozenset({
    "schema_version", "run_id", "variant_id", "job_spec_sha256",
    "job_spec_artifact", "variant_manifest", "variant_manifest_sha256", "artifact_root",
})
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_DDL = (
    "CREATE SCHEMA autoencoder_control",
    "CREATE TABLE autoencoder_control.meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, schema_hash VARCHAR NOT NULL, catalog_hash VARCHAR NOT NULL, artifact_root VARCHAR NOT NULL, owner_generation BIGINT NOT NULL)",
    "CREATE TABLE autoencoder_control.operations (operation_id VARCHAR PRIMARY KEY, payload_digest VARCHAR NOT NULL, receipt VARCHAR NOT NULL)",
    "CREATE TABLE autoencoder_control.variants (variant_id VARCHAR PRIMARY KEY, manifest VARCHAR NOT NULL)",
    "CREATE TABLE autoencoder_control.versions (version_id VARCHAR PRIMARY KEY, variant_id VARCHAR NOT NULL, parent_version_id VARCHAR, artifact VARCHAR NOT NULL, metadata VARCHAR NOT NULL)",
    "CREATE TABLE autoencoder_control.heads (variant_id VARCHAR, branch VARCHAR, version_id VARCHAR NOT NULL, generation BIGINT NOT NULL, PRIMARY KEY(variant_id, branch))",
    "CREATE TABLE autoencoder_control.runs (run_id VARCHAR PRIMARY KEY, variant_id VARCHAR NOT NULL, base_version_id VARCHAR NOT NULL, spec VARCHAR NOT NULL, status VARCHAR NOT NULL, attempt BIGINT NOT NULL, fence BIGINT NOT NULL, lease VARCHAR, result VARCHAR)",
    "CREATE TABLE autoencoder_control.events (event_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, event_data VARCHAR NOT NULL, created_at DOUBLE NOT NULL)",
    "CREATE TABLE autoencoder_control.outbox (event_id VARCHAR, consumer VARCHAR, status VARCHAR NOT NULL, fence BIGINT NOT NULL, lease VARCHAR, receipt VARCHAR, PRIMARY KEY(event_id, consumer))",
)
_TABLE_NAMES = frozenset(
    ("autoencoder_control", name)
    for name in ("meta", "operations", "variants", "versions", "heads", "runs", "events", "outbox")
)


class RegistryError(ValueError):
    """Invalid, stale, conflicting or unqualified control operation."""


def _token(value: str, name: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise RegistryError(f"{name} must be a bounded identifier")
    return value


def _json(value: Any) -> str:
    try:
        return canonical_json_bytes(value).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegistryError(str(exc)) from exc


def _artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"sha256", "bytes"}:
        raise RegistryError("artifact requires exactly sha256 and bytes")
    digest, size = value["sha256"], value["bytes"]
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise RegistryError("artifact sha256 must be lowercase hexadecimal")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise RegistryError("artifact bytes must be a positive integer")
    return {"sha256": digest, "bytes": size}


def _hash_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


class AutoencoderRegistry:
    """One explicit durable file, one owner process, serialized short commits.

    The advisory lock excludes even a second owner in the same process, while
    DuckDB retains its own file lock. Reads use the same RW pool to avoid mixed
    connection configurations. A new owner increments the persisted generation,
    fencing all leases issued before a restart. ``promotion_validator`` is a
    trusted owner-side policy callback ``(version, evaluation) -> bool``; without
    it trained candidates cannot be promoted. It is never supplied by a worker.
    """

    def __init__(
        self,
        database_path: str | Path,
        artifact_root: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        promotion_validator: Callable[[dict[str, Any], Mapping[str, Any]], bool] | None = None,
        max_artifact_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        if str(database_path).strip() in {"", ":memory:"}:
            raise RegistryError("an explicit durable database path is required")
        if isinstance(max_artifact_bytes, bool) or not isinstance(max_artifact_bytes, int) or max_artifact_bytes < 1:
            raise RegistryError("max_artifact_bytes must be positive")
        self.database_path = Path(database_path).expanduser().resolve()
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.max_artifact_bytes = max_artifact_bytes
        self._clock, self._promotion_validator = clock, promotion_validator
        self._pid, self._lock = os.getpid(), threading.RLock()
        self._closed = True
        new_database = not self.database_path.exists()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.database_path.with_name(self.database_path.name + ".owner.lock")
        self._owner_file = lock_path.open("a+b")
        try:
            fcntl.flock(self._owner_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._owner_file.close()
            raise RegistryError("database already has an owner") from exc
        self._manager = ConnectionManager(control_path=str(self.database_path))
        try:
            with self._manager.short_writer_transaction() as cx:
                tables = cx.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog')"
                ).fetchall()
                if not tables:
                    if not new_database:
                        raise RegistryError("existing database has no registry schema")
                    for statement in _DDL:
                        cx.execute(statement)
                    cx.execute("INSERT INTO autoencoder_control.meta VALUES (1, ?, ?, ?, ?, 0)",
                               [SCHEMA, content_identity(_DDL), self._catalog_identity(cx), str(self.artifact_root)])
                elif set(tables) != _TABLE_NAMES:
                    raise RegistryError("refusing a foreign or incomplete registry schema")
                row = cx.execute("SELECT schema_id, schema_hash, catalog_hash, artifact_root, owner_generation FROM autoencoder_control.meta WHERE singleton=1").fetchone()
                if row is None or row[:2] != (SCHEMA, content_identity(_DDL)):
                    raise RegistryError("unknown or drifted registry schema")
                if row[2] != self._catalog_identity(cx):
                    raise RegistryError("registry table definitions differ from the initialized schema")
                if row[3] != str(self.artifact_root):
                    raise RegistryError("artifact_root differs from the durable registry binding")
                self.owner_generation = row[4] + 1
                cx.execute("UPDATE autoencoder_control.meta SET owner_generation=? WHERE singleton=1", [self.owner_generation])
            self._closed = False
        except BaseException as exc:
            self._manager.close()
            self._owner_file.close()
            if isinstance(exc, Exception) and not isinstance(exc, RegistryError):
                raise RegistryError("cannot initialize the durable registry schema") from exc
            raise

    @staticmethod
    def _catalog_identity(cx: Any) -> str:
        definitions = cx.execute(
            "SELECT schema_name, table_name, sql FROM duckdb_tables() "
            "WHERE schema_name='autoencoder_control' ORDER BY table_name"
        ).fetchall()
        return content_identity(definitions)

    def __enter__(self) -> "AutoencoderRegistry":
        self._ensure_owner()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _ensure_owner(self) -> None:
        if os.getpid() != self._pid:
            raise RegistryError("registry cannot be used from a forked worker")
        if self._closed:
            raise RegistryError("registry is closed")

    def close(self) -> None:
        with self._lock:
            if os.getpid() != self._pid:
                raise RegistryError("forked worker cannot close the owner")
            if not self._closed:
                self._manager.close()
                self._owner_file.close()
                self._closed = True

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self._lock:
            self._ensure_owner()
            with self._manager.short_writer_transaction() as cx:
                yield cx

    @staticmethod
    def _command_digest(operation_id: str, command: str, payload: Mapping[str, Any]) -> str:
        _token(operation_id, "operation_id")
        encoded = _json({"command": command, "payload": payload})
        if len(encoded.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise RegistryError("command exceeds 65536 bytes; stage a manifest artifact")
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _operation_receipt(cx: Any, operation_id: str, digest: str) -> dict[str, Any] | None:
        old = cx.execute("SELECT payload_digest, receipt FROM autoencoder_control.operations WHERE operation_id=?", [operation_id]).fetchone()
        if old:
            if old[0] != digest:
                raise RegistryError("operation ID reused with a different payload")
            return json.loads(old[1])
        return None

    def _committed(self, operation_id: str, command: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        """Resolve historical retries before current artifact or policy checks.

        Returning an existing receipt does not assert current artifact
        availability or re-run its evaluation. New operations still perform all
        checks, and the final transaction repeats this lookup to handle races.
        """
        digest = self._command_digest(operation_id, command, payload)
        with self._transaction() as cx:
            return self._operation_receipt(cx, operation_id, digest)

    def resolve_operation(self, operation_id: str, command: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        """Read a matching committed receipt after an ambiguous response.

        ``None`` means this exact operation ID has no committed record. Reusing
        a recorded ID with a different command or payload remains a conflict.
        This lookup does not execute a command or revalidate current artifacts.
        """
        return self._committed(operation_id, command, payload)

    def _mutate(self, operation_id: str, command: str, payload: Mapping[str, Any], apply: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        digest = self._command_digest(operation_id, command, payload)
        with self._transaction() as cx:
            old = self._operation_receipt(cx, operation_id, digest)
            if old is not None:
                return old
            receipt = {"schema": SCHEMA, "operation_id": operation_id, "command": command,
                       "admitted": False, **apply(cx)}
            receipt_json = _json(receipt)
            cx.execute("INSERT INTO autoencoder_control.operations VALUES (?, ?, ?)", [operation_id, digest, receipt_json])
            return json.loads(receipt_json)

    def artifact_path(self, artifact: Mapping[str, Any]) -> Path:
        descriptor = _artifact(artifact)
        digest = descriptor["sha256"]
        return self.artifact_root / digest[:2] / digest

    def verify_artifact(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        self._ensure_owner()
        descriptor = _artifact(artifact)
        if descriptor["bytes"] > self.max_artifact_bytes:
            raise RegistryError("artifact exceeds configured size bound")
        path = self.artifact_path(descriptor)
        if path.is_symlink() or path.parent.is_symlink():
            raise RegistryError("artifact store must not contain symlink aliases")
        try:
            actual = _hash_file(path)
        except OSError as exc:
            raise RegistryError("artifact is missing or unreadable") from exc
        if actual != (descriptor["sha256"], descriptor["bytes"]):
            raise RegistryError("artifact bytes or digest mismatch")
        return descriptor

    def stage_artifact(self, source: str | Path, expected_sha256: str | None = None) -> dict[str, Any]:
        """Copy, fsync and exclusively publish bytes; never link the source inode."""
        self._ensure_owner()
        if expected_sha256 is not None and not _HASH.fullmatch(expected_sha256):
            raise RegistryError("expected_sha256 must be lowercase hexadecimal")
        source = Path(source)
        if source.stat().st_size > self.max_artifact_bytes:
            raise RegistryError("artifact exceeds configured size bound")
        digest, size = hashlib.sha256(), 0
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.artifact_root, prefix=".stage-", delete=False) as target:
                temporary = Path(target.name)
                with source.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        size += len(block)
                        if size > self.max_artifact_bytes:
                            raise RegistryError("artifact exceeds configured size bound")
                        target.write(block)
                        digest.update(block)
                target.flush()
                os.fsync(target.fileno())
            descriptor = _artifact({"sha256": digest.hexdigest(), "bytes": size})
            if expected_sha256 is not None and descriptor["sha256"] != expected_sha256:
                raise RegistryError("source digest differs from expected_sha256")
            destination = self.artifact_path(descriptor)
            destination.parent.mkdir(exist_ok=True)
            if destination.parent.is_symlink():
                raise RegistryError("artifact prefix cannot be a symlink")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                self.verify_artifact(descriptor)
            for directory in (destination.parent, self.artifact_root):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return descriptor
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _event(self, cx: Any, operation_id: str, kind: str, payload: Mapping[str, Any], consumer: str = "ducklake") -> str:
        event_id = content_identity({"operation_id": operation_id, "kind": kind, "consumer": consumer})
        cx.execute("INSERT INTO autoencoder_control.events VALUES (?, ?, ?, ?)", [event_id, kind, _json(payload), self._clock()])
        cx.execute("INSERT INTO autoencoder_control.outbox VALUES (?, ?, 'pending', 0, NULL, NULL)", [event_id, consumer])
        return event_id

    def register_variant(self, operation_id: str, variant_id: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
        _token(variant_id, "variant_id")
        manifest_json = _json(manifest)
        def apply(cx: Any) -> dict[str, Any]:
            old = cx.execute("SELECT manifest FROM autoencoder_control.variants WHERE variant_id=?", [variant_id]).fetchone()
            if old and old[0] != manifest_json:
                raise RegistryError("variant is immutable; register a new variant ID")
            if not old:
                cx.execute("INSERT INTO autoencoder_control.variants VALUES (?, ?)", [variant_id, manifest_json])
            return {"variant_id": variant_id}
        return self._mutate(operation_id, "RegisterVariant", {"variant_id": variant_id, "manifest": manifest}, apply)

    def get_variant(self, variant_id: str) -> dict[str, Any]:
        _token(variant_id, "variant_id")
        with self._transaction() as cx:
            row = cx.execute("SELECT manifest FROM autoencoder_control.variants WHERE variant_id=?", [variant_id]).fetchone()
            if row is None:
                raise RegistryError("unknown variant")
            return {"variant_id": variant_id, "manifest": json.loads(row[0])}

    @staticmethod
    def _version(cx: Any, version_id: str) -> dict[str, Any]:
        row = cx.execute("SELECT variant_id, parent_version_id, artifact, metadata FROM autoencoder_control.versions WHERE version_id=?", [version_id]).fetchone()
        if row is None:
            raise RegistryError("unknown model version")
        return {"version_id": version_id, "variant_id": row[0], "parent_version_id": row[1],
                "artifact": json.loads(row[2]), "metadata": json.loads(row[3])}

    def get_version(self, version_id: str) -> dict[str, Any]:
        with self._transaction() as cx:
            return self._version(cx, version_id)

    def _insert_version(self, cx: Any, variant_id: str, artifact: Mapping[str, Any], metadata: Mapping[str, Any], parent_version_id: str | None) -> str:
        if cx.execute("SELECT 1 FROM autoencoder_control.variants WHERE variant_id=?", [variant_id]).fetchone() is None:
            raise RegistryError("unknown variant")
        if parent_version_id is not None and self._version(cx, parent_version_id)["variant_id"] != variant_id:
            raise RegistryError("parent version belongs to another variant")
        version_id = content_identity({"schema": SCHEMA, "variant_id": variant_id, "artifact": artifact,
                                       "metadata": metadata, "parent_version_id": parent_version_id})
        cx.execute("INSERT INTO autoencoder_control.versions VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                   [version_id, variant_id, parent_version_id, _json(artifact), _json(metadata)])
        return version_id

    def register_version(self, operation_id: str, variant_id: str, artifact: Mapping[str, Any], metadata: Mapping[str, Any] | None = None, parent_version_id: str | None = None) -> dict[str, Any]:
        descriptor = _artifact(artifact)
        metadata = json.loads(_json(metadata or {}))
        payload = {"variant_id": variant_id, "artifact": descriptor, "metadata": metadata, "parent_version_id": parent_version_id}
        old = self._committed(operation_id, "RegisterVersion", payload)
        if old is not None:
            return old
        self.verify_artifact(descriptor)  # hashing never holds a DB transaction
        def apply(cx: Any) -> dict[str, Any]:
            version_id = self._insert_version(cx, variant_id, descriptor, metadata, parent_version_id)
            event_id = self._event(cx, operation_id, "version_registered", {"version_id": version_id})
            return {"version_id": version_id, "event_id": event_id}
        return self._mutate(operation_id, "RegisterVersion", payload, apply)

    def create_run(self, operation_id: str, run_id: str, variant_id: str, base_version_id: str, spec: Mapping[str, Any]) -> dict[str, Any]:
        _token(run_id, "run_id")
        spec_json = _json(spec)
        def apply(cx: Any) -> dict[str, Any]:
            if self._version(cx, base_version_id)["variant_id"] != variant_id:
                raise RegistryError("base version belongs to another variant")
            if cx.execute("SELECT 1 FROM autoencoder_control.runs WHERE run_id=?", [run_id]).fetchone():
                raise RegistryError("run ID already exists")
            cx.execute("INSERT INTO autoencoder_control.runs VALUES (?, ?, ?, ?, 'queued', 0, 0, NULL, NULL)", [run_id, variant_id, base_version_id, spec_json])
            return {"run_id": run_id, "status": "queued"}
        return self._mutate(operation_id, "CreateRun", {"run_id": run_id, "variant_id": variant_id, "base_version_id": base_version_id, "spec": spec}, apply)

    def register_input_snapshot(
        self, operation_id: str, run_id: str, artifact: Mapping[str, Any],
        job_spec_sha256: str, variant_manifest_sha256: str,
    ) -> dict[str, Any]:
        """Record an immutable input export without granting execution authority.

        The owner export factory separately verifies the complete corpus/job
        closure. This operation binds its bounded snapshot to immutable registry
        records, including completed runs. It neither claims a lease nor changes
        a model version/head. Offline consumers must receive the descriptor via
        a trusted handoff; a digest alone does not authenticate the issuer.
        Retrying a committed operation returns its historical receipt, which is
        not a claim of current artifact availability.
        """
        _token(run_id, "run_id")
        for name, value in (("job_spec_sha256", job_spec_sha256),
                            ("variant_manifest_sha256", variant_manifest_sha256)):
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise RegistryError(f"{name} must be lowercase hexadecimal")
        descriptor = _artifact(artifact)
        payload = {"run_id": run_id, "artifact": descriptor,
                   "job_spec_sha256": job_spec_sha256,
                   "variant_manifest_sha256": variant_manifest_sha256}
        old = self._committed(operation_id, "RegisterInputSnapshot", payload)
        if old is not None:
            return old
        if descriptor["bytes"] > min(MAX_INPUT_SNAPSHOT_BYTES, self.max_artifact_bytes):
            raise RegistryError("input snapshot exceeds size bound")

        # Read and hash outside the short DB transaction. O_NONBLOCK plus fstat
        # rejects a replaced FIFO/device instead of blocking an owner thread.
        path = self.artifact_path(descriptor)
        if path.parent.is_symlink():
            raise RegistryError("input snapshot prefix must not be a symlink")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["bytes"]:
                    raise RegistryError("input snapshot must be a bounded regular file")
                raw = stream.read(descriptor["bytes"] + 1)
        except OSError as exc:
            raise RegistryError("input snapshot is missing or unreadable") from exc
        if len(raw) != descriptor["bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise RegistryError("input snapshot bytes or digest mismatch")
        try:
            snapshot = json.loads(raw.decode("utf-8"))
            canonical = _json(snapshot).encode("utf-8")
        except (ValueError, TypeError, RecursionError) as exc:
            raise RegistryError("input snapshot must be canonical JSON") from exc
        if (not isinstance(snapshot, dict) or set(snapshot) != _INPUT_SNAPSHOT_FIELDS
                or raw != canonical or snapshot["schema_version"] != INPUT_SNAPSHOT_SCHEMA):
            raise RegistryError("input snapshot must use the closed canonical v1 schema")
        if (snapshot["run_id"] != run_id or snapshot["job_spec_sha256"] != job_spec_sha256
                or snapshot["variant_manifest_sha256"] != variant_manifest_sha256
                or snapshot["artifact_root"] != str(self.artifact_root)):
            raise RegistryError("input snapshot differs from command or artifact root")
        _token(snapshot["variant_id"], "variant_id")
        if not isinstance(snapshot["variant_manifest"], dict):
            raise RegistryError("input snapshot variant manifest must be an object")
        manifest_json = _json(snapshot["variant_manifest"])
        if hashlib.sha256(manifest_json.encode("utf-8")).hexdigest() != variant_manifest_sha256:
            raise RegistryError("input snapshot variant manifest digest mismatch")
        job_artifact = _artifact(snapshot["job_spec_artifact"])

        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, run_id)
            if (run["variant_id"] != snapshot["variant_id"]
                    or run["spec"].get("job_spec_sha256") != job_spec_sha256
                    or run["spec"].get("job_spec_artifact") != job_artifact):
                raise RegistryError("input snapshot differs from registered job binding")
            variant = cx.execute("SELECT manifest FROM autoencoder_control.variants WHERE variant_id=?",
                                 [run["variant_id"]]).fetchone()
            if variant is None or variant[0] != manifest_json:
                raise RegistryError("input snapshot differs from registered variant")
            event_payload = {**payload, "variant_id": run["variant_id"]}
            event_id = self._event(cx, operation_id, "input_snapshot_registered", event_payload)
            return {**event_payload, "event_id": event_id,
                    "scope": "immutable_inputs_only", "execution_authorized": False,
                    "promotion_authorized": False}

        return self._mutate(operation_id, "RegisterInputSnapshot", payload, apply)

    @staticmethod
    def _run(cx: Any, run_id: str) -> dict[str, Any]:
        row = cx.execute("SELECT variant_id, base_version_id, spec, status, attempt, fence, lease, result FROM autoencoder_control.runs WHERE run_id=?", [run_id]).fetchone()
        if row is None:
            raise RegistryError("unknown run")
        return dict(run_id=run_id, variant_id=row[0], base_version_id=row[1], spec=json.loads(row[2]),
                    status=row[3], attempt=row[4], fence=row[5], lease=json.loads(row[6]) if row[6] else None,
                    result=json.loads(row[7]) if row[7] else None)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._transaction() as cx:
            return self._run(cx, run_id)

    def get_run_completion(self, run_id: str) -> dict[str, Any] | None:
        """Resolve a completed run to its exact registered candidate after restart.

        The operation, retained terminal lease, version metadata and event must
        agree. Historical leases need not be live or belong to the current owner
        generation. Noncompleted runs return ``None``; inconsistent completed
        records raise instead of inferring completion from result flags.

        This reads registry history only. It does not check current artifact
        availability, replay sparse checkpoints, qualify model results, promote
        a head or authorize another job. Callers must verify those inputs before
        using the returned candidate.
        """
        _token(run_id, "run_id")
        with self._transaction() as cx:
            try:
                run = self._run(cx, run_id)
                if run["status"] != "completed":
                    return None
                rows = cx.execute(
                    "SELECT operation_id, payload_digest, receipt "
                    "FROM autoencoder_control.operations "
                    "WHERE CASE WHEN json_valid(receipt) THEN "
                    "json_extract_string(receipt, '$.command') END = ? "
                    "AND CASE WHEN json_valid(receipt) THEN "
                    "json_extract_string(receipt, '$.run_id') END = ? "
                    "ORDER BY operation_id LIMIT 2", ["CompleteRun", run_id],
                ).fetchall()
                if len(rows) != 1:
                    raise RegistryError("completed run requires exactly one completion receipt")
                operation_id, payload_digest, receipt_json = rows[0]
                receipt = json.loads(receipt_json)
                receipt_fields = {"schema", "operation_id", "command", "admitted",
                                  "run_id", "version_id", "event_id", "status", "promoted"}
                if (type(receipt) is not dict or set(receipt) != receipt_fields
                        or receipt["schema"] != SCHEMA or receipt["operation_id"] != operation_id
                        or receipt["command"] != "CompleteRun" or receipt["run_id"] != run_id
                        or receipt["status"] != "completed" or receipt["admitted"] is not False
                        or receipt["promoted"] is not False):
                    raise RegistryError("completed run receipt binding differs")
                lease = run["lease"]
                lease_fields = {"run_id", "attempt", "worker_id", "owner_generation", "fence", "expires_at"}
                if (type(lease) is not dict or set(lease) != lease_fields
                        or lease["run_id"] != run_id
                        or any(type(lease[name]) is not int or lease[name] < 1
                               for name in ("attempt", "owner_generation", "fence"))
                        or type(run["attempt"]) is not int or type(run["fence"]) is not int
                        or lease["attempt"] != run["attempt"] or lease["fence"] != run["fence"]
                        or isinstance(lease["expires_at"], bool)
                        or not isinstance(lease["expires_at"], (int, float))
                        or not math.isfinite(lease["expires_at"])):
                    raise RegistryError("completed run terminal lease differs")
                _token(lease["worker_id"], "worker_id")
                if type(run["result"]) is not dict or run["result"].get("admitted") is not False:
                    raise RegistryError("completed run result must record admitted=false")
                _token(receipt["version_id"], "version_id")
                version = self._version(cx, receipt["version_id"])
                descriptor = _artifact(version["artifact"])
                metadata = {"producer_run": run_id, "attempt": run["attempt"], "result": run["result"]}
                if (version["variant_id"] != run["variant_id"]
                        or version["parent_version_id"] != run["base_version_id"]
                        or _json(version["metadata"]) != _json(metadata)):
                    raise RegistryError("completed run candidate metadata differs")
                expected_version = content_identity({"schema": SCHEMA, "variant_id": run["variant_id"],
                    "artifact": descriptor, "metadata": metadata, "parent_version_id": run["base_version_id"]})
                if version["version_id"] != expected_version:
                    raise RegistryError("completed run candidate content identity differs")
                payload = {"lease": lease, "artifact": descriptor, "result": run["result"]}
                if self._command_digest(operation_id, "CompleteRun", payload) != payload_digest:
                    raise RegistryError("completed run operation payload digest differs")
                expected_event_id = content_identity({"operation_id": operation_id,
                                                     "kind": "candidate_durable", "consumer": "ducklake"})
                if receipt["event_id"] != expected_event_id:
                    raise RegistryError("completed run event identity differs")
                event = cx.execute(
                    "SELECT kind, event_data FROM autoencoder_control.events WHERE event_id=?",
                    [expected_event_id],
                ).fetchone()
                expected_event = {"run_id": run_id, "version_id": version["version_id"]}
                if (event is None or event[0] != "candidate_durable"
                        or _json(json.loads(event[1])) != _json(expected_event)):
                    raise RegistryError("completed run durable event differs")
                return {"run": run, "completion_receipt": receipt, "candidate_version": version}
            except RegistryError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistryError("invalid completed run records") from exc

    def _new_lease(self, key: Mapping[str, Any], worker_id: str, fence: int, lease_seconds: float) -> dict[str, Any]:
        _token(worker_id, "worker_id")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 86400:
            raise RegistryError("lease_seconds must be finite and within (0, 86400]")
        now = self._clock()
        if not math.isfinite(now):
            raise RegistryError("clock must be finite")
        return {**key, "worker_id": worker_id, "owner_generation": self.owner_generation,
                "fence": fence, "expires_at": now + lease_seconds}

    def _live(self, lease: Mapping[str, Any] | None) -> bool:
        return bool(lease and lease.get("owner_generation") == self.owner_generation and lease["expires_at"] > self._clock())

    def _check_lease(self, supplied: Mapping[str, Any], stored: Mapping[str, Any] | None) -> None:
        if not self._live(stored) or _json(supplied) != _json(stored):
            raise RegistryError("stale, expired or invalid lease")

    def claim_run(self, operation_id: str, run_id: str, worker_id: str, lease_seconds: float = 300) -> dict[str, Any]:
        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, run_id)
            if run["status"] in _TERMINAL_RUN_STATES:
                raise RegistryError("cancelled or superseded run is terminal")
            policy = self._run_lifecycle(cx, run_id)
            if policy is not None and run["attempt"] >= policy["max_attempts"]:
                raise RegistryError("run attempt budget exhausted")
            if policy is not None and (type(lease_seconds) not in (int, float)
                    or not math.isfinite(lease_seconds) or lease_seconds > policy["wall_time_seconds"] + 10):
                raise RegistryError("run lease exceeds configured wall-time budget")
            if run["status"] == "completed" or self._live(run["lease"]):
                raise RegistryError("run is completed or already leased")
            lease = self._new_lease({"run_id": run_id, "attempt": run["attempt"] + 1}, worker_id, run["fence"] + 1, lease_seconds)
            cx.execute("UPDATE autoencoder_control.runs SET status='running', attempt=?, fence=?, lease=? WHERE run_id=?", [lease["attempt"], lease["fence"], _json(lease), run_id])
            return {"lease": lease}
        return self._mutate(operation_id, "ClaimRun", {"run_id": run_id, "worker_id": worker_id, "lease_seconds": lease_seconds}, apply)

    def renew_lease(self, operation_id: str, lease: Mapping[str, Any], lease_seconds: float = 300) -> dict[str, Any]:
        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, lease["run_id"])
            self._check_lease(lease, run["lease"])
            if run["status"] != "running":
                raise RegistryError("run is not running")
            renewed = self._new_lease({"run_id": lease["run_id"], "attempt": lease["attempt"]}, lease["worker_id"], lease["fence"], lease_seconds)
            cx.execute("UPDATE autoencoder_control.runs SET lease=? WHERE run_id=?", [_json(renewed), lease["run_id"]])
            return {"lease": renewed}
        return self._mutate(operation_id, "RenewLease", {"lease": lease, "lease_seconds": lease_seconds}, apply)

    def complete_run(self, operation_id: str, lease: Mapping[str, Any], artifact: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
        descriptor = _artifact(artifact)
        payload = {"lease": lease, "artifact": descriptor, "result": result}
        old = self._committed(operation_id, "CompleteRun", payload)
        if old is not None:
            return old
        self.verify_artifact(descriptor)
        if not isinstance(result, Mapping) or result.get("admitted") is not False:
            raise RegistryError("result must explicitly record admitted=false")
        result_json = _json(result)
        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, lease["run_id"])
            self._check_lease(lease, run["lease"])
            if run["status"] != "running":
                raise RegistryError("run is not running")
            policy = self._run_lifecycle(cx, run["run_id"])
            if policy is not None:
                if descriptor["bytes"] > policy["max_checkpoint_bytes"]:
                    raise RegistryError("candidate exceeds configured checkpoint budget")
                expected = policy["expected_head"]
                if self._head(cx, expected["variant_id"], expected["branch"]) != expected:
                    raise RegistryError("run parent head changed before completion")
            metadata = {"producer_run": run["run_id"], "attempt": lease["attempt"], "result": result}
            version_id = self._insert_version(cx, run["variant_id"], descriptor, metadata, run["base_version_id"])
            cx.execute("UPDATE autoencoder_control.runs SET status='completed', result=? WHERE run_id=?", [result_json, run["run_id"]])
            event_id = self._event(cx, operation_id, "candidate_durable", {"run_id": run["run_id"], "version_id": version_id})
            return {"run_id": run["run_id"], "version_id": version_id, "event_id": event_id, "status": "completed", "promoted": False}
        return self._mutate(operation_id, "CompleteRun", payload, apply)

    def fail_run(self, operation_id: str, lease: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
        """Record a worker failure without creating a candidate or retaining a lease."""
        if not isinstance(result, Mapping) or result.get("admitted") is not False:
            raise RegistryError("result must explicitly record admitted=false")
        result_json = _json(result)
        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, lease["run_id"])
            self._check_lease(lease, run["lease"])
            if run["status"] != "running":
                raise RegistryError("run is not running")
            cx.execute("UPDATE autoencoder_control.runs SET status='failed', result=?, lease=NULL WHERE run_id=?", [result_json, run["run_id"]])
            event_id = self._event(cx, operation_id, "run_failed", {"run_id": run["run_id"], "attempt": lease["attempt"]})
            return {"run_id": run["run_id"], "status": "failed", "event_id": event_id}
        return self._mutate(operation_id, "FailRun", {"lease": lease, "result": result}, apply)

    @staticmethod
    def _lifecycle_operation(run_id: str) -> str:
        return "run-lifecycle:" + hashlib.sha256(run_id.encode()).hexdigest()

    @staticmethod
    def _lifecycle_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
        keys = {"schema", "max_attempts", "wall_time_seconds", "memory_bytes", "max_input_bytes",
                "max_samples", "optimizer_steps", "head_refits", "max_checkpoint_bytes", "expected_head"}
        if not isinstance(policy, Mapping) or set(policy) != keys or policy["schema"] != RUN_LIFECYCLE_SCHEMA:
            raise RegistryError("closed versioned run lifecycle policy required")
        limits = {"max_attempts": (1, 3), "memory_bytes": (1024**3, 16 * 1024**3),
                  "max_input_bytes": (1, 32 * 1024**2), "max_samples": (3, 128),
                  "optimizer_steps": (0, 0), "head_refits": (1, 1),
                  "max_checkpoint_bytes": (1, 32 * 1024**2)}
        for key, (lower, upper) in limits.items():
            if type(policy[key]) is not int or not lower <= policy[key] <= upper:
                raise RegistryError("invalid lifecycle budget: " + key)
        seconds = policy["wall_time_seconds"]
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 600:
            raise RegistryError("invalid lifecycle wall-time budget")
        head = policy["expected_head"]
        if not isinstance(head, Mapping) or set(head) != {"variant_id", "branch", "version_id", "generation"}:
            raise RegistryError("exact lifecycle parent head required")
        for name in ("variant_id", "branch", "version_id"):
            _token(head[name], name)
        if type(head["generation"]) is not int or head["generation"] < 1:
            raise RegistryError("invalid lifecycle head generation")
        return json.loads(_json(policy))

    def _run_lifecycle(self, cx: Any, run_id: str) -> dict[str, Any] | None:
        operation = self._lifecycle_operation(run_id)
        row = cx.execute("SELECT payload_digest, receipt FROM autoencoder_control.operations WHERE operation_id=?", [operation]).fetchone()
        if row is None:
            return None
        receipt = json.loads(row[1])
        if (set(receipt) != {"schema", "operation_id", "command", "admitted", "run_id", "policy"}
                or receipt["schema"] != SCHEMA or receipt["operation_id"] != operation
                or receipt["command"] != "ConfigureRunLifecycle" or receipt["run_id"] != run_id
                or receipt["admitted"] is not False):
            raise RegistryError("run lifecycle receipt differs")
        policy = self._lifecycle_policy(receipt["policy"])
        expected = self._command_digest(operation, "ConfigureRunLifecycle", {"run_id": run_id, "policy": policy})
        if row[0] != expected:
            raise RegistryError("run lifecycle operation identity differs")
        return policy

    def configure_run_lifecycle(self, run_id: str, policy: Mapping[str, Any]) -> dict[str, Any]:
        """Opt in one queued run to immutable bounded lifecycle semantics.

        The extension lives in the existing command log; DDL, version IDs and
        legacy run semantics are unchanged. No mutable parallel head is added.
        """
        _token(run_id, "run_id")
        policy = self._lifecycle_policy(policy)
        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, run_id)
            head = policy["expected_head"]
            if run["status"] != "queued" or run["attempt"] != 0 or run["lease"] is not None:
                raise RegistryError("lifecycle must be configured before the first claim")
            if (run["variant_id"] != head["variant_id"] or run["base_version_id"] != head["version_id"]
                    or self._head(cx, head["variant_id"], head["branch"]) != head):
                raise RegistryError("lifecycle parent head differs")
            return {"run_id": run_id, "policy": policy}
        return self._mutate(self._lifecycle_operation(run_id), "ConfigureRunLifecycle",
                            {"run_id": run_id, "policy": policy}, apply)

    def get_run_lifecycle(self, run_id: str) -> dict[str, Any] | None:
        """Read the immutable lifecycle policy without training or claiming."""
        with self._transaction() as cx:
            self._run(cx, run_id)
            return self._run_lifecycle(cx, run_id)

    def terminate_run(self, operation_id: str, run_id: str, *, terminal: str,
                      expected_attempt: int, expected_fence: int, reason: str,
                      successor_run_id: str | None = None) -> dict[str, Any]:
        """Atomically revoke an unfinished run; completed history stays intact."""
        _token(run_id, "run_id")
        if terminal not in _TERMINAL_RUN_STATES:
            raise RegistryError("cancelled or superseded terminal state required")
        if any(type(value) is not int or value < 0 for value in (expected_attempt, expected_fence)):
            raise RegistryError("exact nonnegative run attempt/fence required")
        if type(reason) is not str or not 0 < len(reason.encode()) <= 1024:
            raise RegistryError("bounded terminal reason required")
        if successor_run_id is not None:
            _token(successor_run_id, "successor_run_id")
            if successor_run_id == run_id or terminal != "superseded":
                raise RegistryError("distinct superseding run required")
        payload = {"run_id": run_id, "terminal": terminal, "expected_attempt": expected_attempt,
                   "expected_fence": expected_fence, "reason": reason, "successor_run_id": successor_run_id}
        def apply(cx: Any) -> dict[str, Any]:
            run = self._run(cx, run_id)
            if self._run_lifecycle(cx, run_id) is None:
                raise RegistryError("run has not opted into versioned terminal semantics")
            if run["status"] not in {"queued", "running", "failed"}:
                raise RegistryError("completed or terminal run cannot be terminated again")
            if (run["attempt"], run["fence"]) != (expected_attempt, expected_fence):
                raise RegistryError("terminal run attempt/fence compare-and-swap conflict")
            if successor_run_id is not None:
                successor = self._run(cx, successor_run_id)
                if successor["variant_id"] != run["variant_id"] or successor["status"] in _TERMINAL_RUN_STATES:
                    raise RegistryError("superseding run variant or state differs")
            result = {"schema": RUN_TERMINAL_SCHEMA, "run_id": run_id, "terminal": terminal,
                "reason": reason, "successor_run_id": successor_run_id, "prior_status": run["status"],
                "previous_result_sha256": content_identity(run["result"]),
                "previous_lease_sha256": content_identity(run["lease"]),
                "attempt": run["attempt"], "fence": run["fence"] + 1,
                "owner_generation": self.owner_generation, "admitted": False,
                "retryable": False, "publishable": False}
            cx.execute("UPDATE autoencoder_control.runs SET status=?, fence=?, lease=NULL, result=? WHERE run_id=?",
                       [terminal, result["fence"], _json(result), run_id])
            event_id = self._event(cx, operation_id, "run_" + terminal, result)
            return {"run_id": run_id, "status": terminal, "fence": result["fence"], "event_id": event_id,
                    "terminal_schema": RUN_TERMINAL_SCHEMA}
        return self._mutate(operation_id, "TerminateRun", payload, apply)

    @classmethod
    def _reject_terminal_producer(cls, cx: Any, version: Mapping[str, Any]) -> None:
        producer = version["metadata"].get("producer_run")
        if type(producer) is str:
            row = cx.execute("SELECT status FROM autoencoder_control.runs WHERE run_id=?", [producer]).fetchone()
            if row is not None and row[0] in _TERMINAL_RUN_STATES:
                raise RegistryError("terminal producer run cannot publish or promote a candidate")

    @staticmethod
    def _head(cx: Any, variant_id: str, branch: str) -> dict[str, Any] | None:
        row = cx.execute("SELECT version_id, generation FROM autoencoder_control.heads WHERE variant_id=? AND branch=?", [variant_id, branch]).fetchone()
        return None if row is None else {"variant_id": variant_id, "branch": branch, "version_id": row[0], "generation": row[1]}

    def resolve_head(self, variant_id: str, branch: str) -> dict[str, Any] | None:
        with self._transaction() as cx:
            return self._head(cx, variant_id, branch)

    def initialize_head(self, operation_id: str, variant_id: str, branch: str, version_id: str) -> dict[str, Any]:
        _token(branch, "branch")
        def apply(cx: Any) -> dict[str, Any]:
            version = self._version(cx, version_id)
            if version["variant_id"] != variant_id or version["parent_version_id"] is not None:
                raise RegistryError("bootstrap head requires a root version of this variant")
            if self._head(cx, variant_id, branch) is not None:
                raise RegistryError("head already initialized")
            cx.execute("INSERT INTO autoencoder_control.heads VALUES (?, ?, ?, 1)", [variant_id, branch, version_id])
            self._event(cx, operation_id, "head_initialized", {"variant_id": variant_id, "branch": branch, "version_id": version_id})
            return {"version_id": version_id, "generation": 1}
        return self._mutate(operation_id, "InitializeHead", {"variant_id": variant_id, "branch": branch, "version_id": version_id}, apply)

    def promote_head(self, operation_id: str, variant_id: str, branch: str, version_id: str, expected_version_id: str, expected_generation: int, evaluation: Mapping[str, Any]) -> dict[str, Any]:
        _token(branch, "branch")
        payload = {"variant_id": variant_id, "branch": branch, "version_id": version_id, "expected_version_id": expected_version_id, "expected_generation": expected_generation, "evaluation": evaluation}
        old = self._committed(operation_id, "PromoteHead", payload)
        if old is not None:
            return old
        version = self.get_version(version_id)
        if evaluation.get("candidate_version_id") != version_id or not evaluation.get("protocol_id"):
            raise RegistryError("evaluation must bind the candidate and protocol")
        if self._promotion_validator is None or self._promotion_validator(version, evaluation) is not True:
            raise RegistryError("promotion requires a qualified owner-side evaluation policy")
        # Evaluation may be slow. It runs before the short transaction; CAS is
        # rechecked afterward. This callback cannot turn a model into a proof.
        def apply(cx: Any) -> dict[str, Any]:
            head = self._head(cx, variant_id, branch)
            self._reject_terminal_producer(cx, self._version(cx, version_id))
            if version["variant_id"] != variant_id or head is None or (head["version_id"], head["generation"]) != (expected_version_id, expected_generation):
                raise RegistryError("head compare-and-swap conflict")
            cx.execute("UPDATE autoencoder_control.heads SET version_id=?, generation=? WHERE variant_id=? AND branch=?", [version_id, expected_generation + 1, variant_id, branch])
            self._event(cx, operation_id, "head_promoted", {"variant_id": variant_id, "branch": branch, "version_id": version_id, "evaluation": evaluation})
            return {"version_id": version_id, "generation": expected_generation + 1}
        return self._mutate(operation_id, "PromoteHead", payload, apply)

    def enqueue_publication(self, operation_id: str, version_id: str, publication_plan_artifact: Mapping[str, Any]) -> dict[str, Any]:
        descriptor = _artifact(publication_plan_artifact)
        payload = {"version_id": version_id, "plan_artifact": descriptor}
        old = self._committed(operation_id, "EnqueuePublication", payload)
        if old is not None:
            return old
        self.verify_artifact(descriptor)
        def apply(cx: Any) -> dict[str, Any]:
            self._reject_terminal_producer(cx, self._version(cx, version_id))
            event_id = self._event(cx, operation_id, "publication_requested", {"version_id": version_id, "plan_artifact": descriptor}, "huggingface")
            return {"event_id": event_id, "uploaded": False}
        return self._mutate(operation_id, "EnqueuePublication", payload, apply)

    @staticmethod
    def _consumer(consumer: str) -> None:
        if type(consumer) is not str or consumer not in {"ducklake", "huggingface"}:
            raise RegistryError("unknown outbox consumer")

    @staticmethod
    def _event_id(event_id: str) -> None:
        if type(event_id) is not str or not event_id.startswith("sha256:") or not _HASH.fullmatch(event_id[7:]):
            raise RegistryError("event_id must be sha256 followed by a lowercase hexadecimal digest")

    @staticmethod
    def _limit(limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise RegistryError("limit must be between 1 and 100")

    def pending_outbox(self, consumer: str, limit: int = 100) -> list[dict[str, Any]]:
        self._consumer(consumer)
        self._limit(limit)
        with self._transaction() as cx:
            rows = cx.execute("SELECT e.event_id, e.kind, e.event_data, o.status, o.lease FROM autoencoder_control.outbox o JOIN autoencoder_control.events e USING(event_id) WHERE o.consumer=? AND o.status!='acknowledged' ORDER BY e.created_at, e.event_id LIMIT ?", [consumer, limit]).fetchall()
            return [{"event_id": r[0], "consumer": consumer, "kind": r[1], "payload": json.loads(r[2]), "status": r[3], "lease": json.loads(r[4]) if r[4] else None} for r in rows]

    def get_outbox_event(self, consumer: str, event_id: str) -> dict[str, Any]:
        """Read one persisted event, including acknowledged delivery state.

        The payload and timestamp are the original event values. In particular,
        historical run failures are not enriched from the run's current state.
        A returned lease or receipt describes history, not current authority.
        """
        self._consumer(consumer)
        self._event_id(event_id)
        with self._transaction() as cx:
            row = cx.execute(
                "SELECT e.kind, e.event_data, e.created_at, o.status, o.lease, o.receipt "
                "FROM autoencoder_control.outbox o JOIN autoencoder_control.events e USING(event_id) "
                "WHERE o.event_id=? AND o.consumer=?", [event_id, consumer],
            ).fetchone()
            if row is None:
                raise RegistryError("unknown outbox event for this consumer")
            return {"event_id": event_id, "consumer": consumer, "kind": row[0],
                    "payload": json.loads(row[1]), "created_at": row[2], "status": row[3],
                    "lease": json.loads(row[4]) if row[4] else None,
                    "receipt": json.loads(row[5]) if row[5] else None}

    def claim_outbox_event(self, operation_id: str, event_id: str, consumer: str, worker_id: str, lease_seconds: float = 300) -> dict[str, Any]:
        """Claim exactly one event without changing a recovery batch's members."""
        self._consumer(consumer)
        self._event_id(event_id)
        def apply(cx: Any) -> dict[str, Any]:
            row = cx.execute(
                "SELECT o.status, o.fence, o.lease, e.kind, e.event_data "
                "FROM autoencoder_control.outbox o JOIN autoencoder_control.events e USING(event_id) "
                "WHERE o.event_id=? AND o.consumer=?", [event_id, consumer],
            ).fetchone()
            if row is None:
                raise RegistryError("unknown outbox event for this consumer")
            if row[0] == "acknowledged" or self._live(json.loads(row[2]) if row[2] else None):
                raise RegistryError("outbox event is acknowledged or already leased")
            lease = self._new_lease({"event_id": event_id, "consumer": consumer}, worker_id, row[1] + 1, lease_seconds)
            cx.execute("UPDATE autoencoder_control.outbox SET status='leased', fence=?, lease=? WHERE event_id=? AND consumer=?", [lease["fence"], _json(lease), event_id, consumer])
            return {"delivery": {"event_id": event_id, "consumer": consumer, "kind": row[3],
                                 "payload": json.loads(row[4]), "lease": lease}}
        return self._mutate(operation_id, "ClaimOutboxEvent", {"event_id": event_id, "consumer": consumer, "worker_id": worker_id, "lease_seconds": lease_seconds}, apply)

    def renew_outbox(self, operation_id: str, event_id: str, consumer: str, lease: Mapping[str, Any], lease_seconds: float = 300) -> dict[str, Any]:
        """Renew a live exact delivery lease, retaining its worker and fence."""
        self._consumer(consumer)
        self._event_id(event_id)
        def apply(cx: Any) -> dict[str, Any]:
            row = cx.execute("SELECT status, lease FROM autoencoder_control.outbox WHERE event_id=? AND consumer=?", [event_id, consumer]).fetchone()
            if row is None or row[0] != "leased":
                raise RegistryError("outbox event is not leased by this consumer")
            stored = json.loads(row[1])
            self._check_lease(lease, stored)
            renewed = self._new_lease({"event_id": event_id, "consumer": consumer}, stored["worker_id"], stored["fence"], lease_seconds)
            cx.execute("UPDATE autoencoder_control.outbox SET lease=? WHERE event_id=? AND consumer=?", [_json(renewed), event_id, consumer])
            return {"lease": renewed}
        return self._mutate(operation_id, "RenewOutbox", {"event_id": event_id, "consumer": consumer, "lease": lease, "lease_seconds": lease_seconds}, apply)

    def claim_outbox(self, operation_id: str, consumer: str, worker_id: str, lease_seconds: float = 300, limit: int = 1) -> dict[str, Any]:
        self._consumer(consumer)
        self._limit(limit)
        # Each delivered event costs two statements. Stay under the existing
        # control session's 32-statement budget.
        if limit > 10:
            raise RegistryError("claim batches are bounded to 10 events")
        def apply(cx: Any) -> dict[str, Any]:
            # Filter and bound at the database, so a backlog does not become an
            # unbounded Python allocation or extend the writer transaction.
            now = self._clock()
            if not math.isfinite(now):
                raise RegistryError("clock must be finite")
            rows = cx.execute(
                "SELECT o.event_id, o.fence, o.lease, e.kind, e.event_data "
                "FROM autoencoder_control.outbox o JOIN autoencoder_control.events e USING(event_id) "
                "WHERE o.consumer=? AND o.status!='acknowledged' AND "
                "(o.lease IS NULL OR CAST(json_extract_string(o.lease, '$.owner_generation') AS BIGINT) != ? "
                "OR CAST(json_extract_string(o.lease, '$.expires_at') AS DOUBLE) <= ?) "
                "ORDER BY e.created_at, e.event_id LIMIT ?",
                [consumer, self.owner_generation, now, limit],
            ).fetchall()
            deliveries = []
            for event_id, fence, raw_lease, kind, payload in rows:
                if self._live(json.loads(raw_lease) if raw_lease else None):
                    continue
                lease = self._new_lease({"event_id": event_id, "consumer": consumer}, worker_id, fence + 1, lease_seconds)
                cx.execute("UPDATE autoencoder_control.outbox SET status='leased', fence=?, lease=? WHERE event_id=? AND consumer=?", [fence + 1, _json(lease), event_id, consumer])
                deliveries.append({"event_id": event_id, "consumer": consumer, "kind": kind, "payload": json.loads(payload), "lease": lease})
                if len(deliveries) == limit:
                    break
            return {"deliveries": deliveries}
        return self._mutate(operation_id, "ClaimOutbox", {"consumer": consumer, "worker_id": worker_id, "lease_seconds": lease_seconds, "limit": limit}, apply)

    def ack_outbox(self, operation_id: str, event_id: str, consumer: str, receipt: Mapping[str, Any], lease: Mapping[str, Any]) -> dict[str, Any]:
        self._consumer(consumer)
        def apply(cx: Any) -> dict[str, Any]:
            row = cx.execute("SELECT status, lease FROM autoencoder_control.outbox WHERE event_id=? AND consumer=?", [event_id, consumer]).fetchone()
            if row is None or row[0] != "leased":
                raise RegistryError("outbox event is not leased by this consumer")
            self._check_lease(lease, json.loads(row[1]))
            cx.execute("UPDATE autoencoder_control.outbox SET status='acknowledged', receipt=? WHERE event_id=? AND consumer=?", [_json(receipt), event_id, consumer])
            return {"event_id": event_id, "consumer": consumer, "acknowledged": True}
        return self._mutate(operation_id, "AckOutbox", {"event_id": event_id, "consumer": consumer, "receipt": receipt, "lease": lease}, apply)
