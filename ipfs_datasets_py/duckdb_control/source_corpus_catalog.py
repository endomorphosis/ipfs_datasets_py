"""Single-owner, durable source rows from independently verified corpus exports.

Dataset and language labels are declarations. Retrieval claims in record_json
remain historical data; neither a row nor a registration receipt is an admit.
This catalog is deliberately separate from the training registry. Importing it
opens no database, loads no model and starts no service.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading

from .connections import ConnectionManager
from ..optimizers.logic_theorem_optimizer import autoencoder_uscode_corpus_export as export
from ..optimizers.logic_theorem_optimizer.autoencoder_uscode_corpus_rows import ROW_FIELDS, ROW_TYPES, NULLABLE_FIELDS


SCHEMA = "source-corpus-catalog-v1"
PROFILE = "uscode-source-export-v1"
_QUALIFICATION = dict.fromkeys(("admitted", "formalized", "source_authority_authenticated",
                              "language_verified", "publication_performed"), False)
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SQL_TYPES = {"string": "VARCHAR", "int64": "BIGINT", "bool": "BOOLEAN"}
_COLUMNS = ", ".join('"' + key + '"' for key in ROW_FIELDS)
_STRING_BYTES = " + ".join('coalesce(octet_length(encode("' + key + '")),0)'
                           for key in ROW_FIELDS if ROW_TYPES[key] == "string")
_ROW_DDL = ", ".join('"' + key + '" ' + _SQL_TYPES[ROW_TYPES[key]] +
                      ("" if key in NULLABLE_FIELDS else " NOT NULL") for key in ROW_FIELDS)
_DDL = (
    "CREATE SCHEMA source_corpus",
    "CREATE TABLE source_corpus.meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, schema_hash VARCHAR NOT NULL, catalog_hash VARCHAR NOT NULL, package_root VARCHAR NOT NULL, root_device BIGINT NOT NULL, root_inode BIGINT NOT NULL)",
    "CREATE TABLE source_corpus.operations (operation_id VARCHAR PRIMARY KEY, request_digest VARCHAR NOT NULL, request_json VARCHAR NOT NULL, receipt VARCHAR)",
    "CREATE TABLE source_corpus.datasets (dataset_id VARCHAR PRIMARY KEY, binding VARCHAR NOT NULL)",
    "CREATE TABLE source_corpus.releases (release_id VARCHAR PRIMARY KEY, manifest VARCHAR NOT NULL, package_directory VARCHAR NOT NULL, package_bytes BIGINT NOT NULL, row_count BIGINT NOT NULL, row_digest VARCHAR, status VARCHAR NOT NULL, owner_operation VARCHAR NOT NULL, next_ordinal BIGINT NOT NULL)",
    "CREATE TABLE source_corpus.versions (version_id VARCHAR PRIMARY KEY, dataset_id VARCHAR NOT NULL, release_id VARCHAR NOT NULL, metadata VARCHAR NOT NULL)",
    "CREATE TABLE source_corpus.rows (release_id VARCHAR NOT NULL, ordinal BIGINT NOT NULL, " + _ROW_DDL + ", PRIMARY KEY(release_id, ordinal), UNIQUE(release_id, source_row_id))",
    "CREATE TABLE source_corpus.batches (release_id VARCHAR NOT NULL, start_ordinal BIGINT NOT NULL, row_count BIGINT NOT NULL, digest VARCHAR NOT NULL, PRIMARY KEY(release_id, start_ordinal))",
)
_TABLES = {("source_corpus", name) for name in ("meta", "operations", "datasets", "releases", "versions", "rows", "batches")}


class SourceCorpusCatalogError(ValueError):
    """Invalid, conflicting, unavailable or changed source catalog data."""


@dataclass(frozen=True)
class SourceCatalogLimits:
    max_batch_rows: int = 64
    max_batch_bytes: int = 8 * 1024**2
    max_read_rows: int = 256
    max_read_bytes: int = 8 * 1024**2
    max_releases: int = 64
    max_versions: int = 256
    max_operations: int = 1024
    max_total_rows: int = 4194304
    max_package_bytes: int = 512 * 1024**2
    max_owned_package_bytes: int = 8 * 1024**3

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            _require(type(value) is int and 1 <= value <= field.default,
                     "invalid catalog limit: " + field.name)


def _require(condition, message):
    if not condition:
        raise SourceCorpusCatalogError(message)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise SourceCorpusCatalogError("invalid JSON value") from exc


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _token(value):
    _require(type(value) is str and _TOKEN.fullmatch(value), "invalid bounded identifier")
    return value


def _payload(value):
    _require(type(value) is dict and set(value) == {"dataset", "package_manifest_artifact"}, "invalid registration payload")
    dataset, ref = value["dataset"], value["package_manifest_artifact"]
    _require(type(dataset) is dict and set(dataset) == {"namespace", "source_language", "jurisdiction", "profile"}, "invalid dataset declaration")
    for item in dataset.values():
        _token(item)
    _require(dataset["profile"] == PROFILE, "unsupported dataset profile")
    _require(type(ref) is dict and set(ref) == {"sha256", "bytes"}, "invalid manifest descriptor")
    _require(type(ref["sha256"]) is str and _HASH.fullmatch(ref["sha256"]), "invalid manifest digest")
    _require(type(ref["bytes"]) is int and 1 <= ref["bytes"] <= 4 * 1024**2, "invalid manifest size")
    return json.loads(_json(value))


def _identities(payload):
    dataset_id = "sha256:" + _digest({"schema_version": "source-corpus-dataset-v1", "dataset": payload["dataset"]})
    release_id = "sha256:" + payload["package_manifest_artifact"]["sha256"]
    version_id = "sha256:" + _digest({"schema_version": "source-corpus-version-v1", "dataset_id": dataset_id,
                                      "release_id": release_id, "package_manifest_artifact": payload["package_manifest_artifact"]})
    return dataset_id, release_id, version_id


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and str(path) == os.path.abspath(path) and ".." not in path.parts,
             "absolute normalized path required")
    _require(path.resolve() == path, "path aliases are forbidden")
    return path


def _signature(path, *, directory=False):
    info = path.lstat()
    _require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
             "unsafe directory or nonexclusive regular file")
    _require(path.resolve() == path, "path alias changed")
    return info.st_dev, info.st_ino


def _rows_digest(rows, start):
    digest = hashlib.sha256()
    for ordinal, row in enumerate(rows, start):
        digest.update(_json({"ordinal": ordinal, **row}).encode() + b"\n")
    return digest.hexdigest()


def _row_contract(row):
    export._row_size(row, export.CorpusExportLimits())
    _require(row["admitted"] is False and row["formalized"] is False
             and row["formalization_status"] == "not_observed", "source row authority flags changed")


def _normalize_errors(function):
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (export.CorpusExportError, OSError) as exc:
            raise SourceCorpusCatalogError(str(exc)) from exc
    return call


class SourceCorpusCatalog:
    """An exclusive local owner; short commits never encompass package decoding.

    Committed operation lookup reports registration-time evidence, even if a
    package later becomes unavailable. Use verify_version for current evidence.
    Failed copies retain their files. Exact complete files can resume; changed
    or truncated partial files require explicit recovery and are never replaced.
    """
    @_normalize_errors
    def __init__(self, database_path, package_root, *, limits=SourceCatalogLimits()):
        _require(type(limits) is SourceCatalogLimits, "invalid catalog limits")
        self.limits = SourceCatalogLimits(**{field.name: getattr(limits, field.name) for field in fields(limits)})
        self.database_path, self.package_root = _path(database_path), _path(package_root)
        _require(not self.database_path.is_relative_to(self.package_root) and not self.package_root.is_relative_to(self.database_path),
                 "database and package root overlap")
        _signature(self.database_path.parent, directory=True)
        _signature(self.package_root.parent, directory=True)
        new_database = not self.database_path.exists()
        initial_database = None if new_database else _signature(self.database_path)
        if not self.package_root.exists():
            self.package_root.mkdir(mode=0o700)
            parent_fd = export._directory(self.package_root.parent)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        self._root_signature = _signature(self.package_root, directory=True)
        _require(not new_database or not any(self.package_root.iterdir()), "new catalog cannot adopt an occupied package root")
        self._pid, self._lock, self._closed = os.getpid(), threading.RLock(), True
        self._lock_path = self.database_path.with_name(self.database_path.name + ".owner.lock")
        lock_fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        self._owner_file = os.fdopen(lock_fd, "r+b")
        try:
            self._lock_signature = _signature(self._lock_path)
            _require(self._lock_signature == (os.fstat(lock_fd).st_dev, os.fstat(lock_fd).st_ino), "owner lock changed")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self._owner_file.close()
            raise
        self._manager = ConnectionManager(control_path=str(self.database_path))
        try:
            with self._manager.short_writer_transaction() as cx:
                tables = set(cx.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema', 'pg_catalog')").fetchall())
                if not tables:
                    _require(new_database, "existing database has no catalog schema")
                    for statement in _DDL:
                        cx.execute(statement)
                    cx.execute("INSERT INTO source_corpus.meta VALUES (1, ?, ?, ?, ?, ?, ?)",
                               [SCHEMA, _digest(_DDL), self._catalog_identity(cx), str(self.package_root), *self._root_signature])
                else:
                    _require(tables == _TABLES, "foreign or incomplete catalog schema")
                metadata = cx.execute("SELECT schema_id, schema_hash, catalog_hash, package_root, root_device, root_inode FROM source_corpus.meta WHERE singleton=1").fetchall()
                _require(metadata == [(SCHEMA, _digest(_DDL), self._catalog_identity(cx), str(self.package_root), *self._root_signature)],
                         "catalog schema or package root binding changed")
            self._database_signature = _signature(self.database_path)
            _require(initial_database is None or initial_database == self._database_signature, "database changed during owner acquisition")
            self._closed = False
        except BaseException as exc:
            self._manager.close()
            self._owner_file.close()
            if isinstance(exc, Exception) and not isinstance(exc, SourceCorpusCatalogError):
                raise SourceCorpusCatalogError("cannot initialize source catalog") from exc
            raise

    @staticmethod
    def _catalog_identity(cx):
        return _digest(cx.execute("SELECT schema_name, table_name, sql FROM duckdb_tables() WHERE schema_name='source_corpus' ORDER BY table_name").fetchall())

    def _ensure_owner(self):
        _require(os.getpid() == self._pid and not self._closed, "catalog closed or used by a different process")
        _require(_signature(self.database_path) == self._database_signature and
                 _signature(self.package_root, directory=True) == self._root_signature and
                 _signature(self._lock_path) == self._lock_signature, "catalog owner paths changed")

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._ensure_owner()
            with self._manager.short_writer_transaction() as cx:
                yield cx
            self._ensure_owner()

    def __enter__(self):
        self._ensure_owner()
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        with self._lock:
            _require(os.getpid() == self._pid, "different process cannot close catalog")
            if not self._closed:
                try:
                    self._manager.close()
                finally:
                    self._owner_file.close()
                    self._closed = True

    @contextmanager
    def try_owner_access(self):
        """Acquire the actual owner lock without blocking a command dispatcher.

        Callers must leave a false result immediately. A true result covers the
        complete bounded command, including any nested catalog transactions.
        Heavy owner work uses the same lock, including direct register/verify
        calls made outside a controller.
        """
        _require(os.getpid() == self._pid, "catalog used by a different process")
        acquired = self._lock.acquire(blocking=False)
        try:
            if acquired:
                self._ensure_owner()
            yield acquired
        finally:
            if acquired:
                self._lock.release()

    def _operation(self, cx, operation_id, payload):
        row = cx.execute("SELECT request_digest, request_json, receipt FROM source_corpus.operations WHERE operation_id=?", [operation_id]).fetchone()
        if row is None:
            return None
        _require(row[:2] == (_digest(payload), _json(payload)), "operation payload conflict or corruption")
        if row[2] is None:
            return None
        receipt = json.loads(row[2])
        dataset_id, release_id, version_id = _identities(payload)
        version = self._version(cx, version_id)
        expected = self._receipt(operation_id, payload, version)
        _require(_json(receipt) == _json(expected) and version["dataset_id"] == dataset_id and version["release_id"] == release_id,
                 "operation receipt does not bind durable version")
        return receipt

    @_normalize_errors
    def resolve_operation(self, operation_id, payload):
        operation_id, payload = _token(operation_id), _payload(payload)
        with self._transaction() as cx:
            return self._operation(cx, operation_id, payload)

    def _registration_status(self, cx, operation_id, payload):
        exists = cx.execute("SELECT operation_id FROM source_corpus.operations WHERE operation_id=?",
                            [operation_id]).fetchone() is not None
        receipt = self._operation(cx, operation_id, payload)
        return {"schema_version": "source-corpus-operation-status-v1",
                "operation_id": operation_id,
                "state": "completed" if receipt is not None else "pending" if exists else "unknown",
                "receipt": receipt, "admitted": False, "formalized": False}

    @_normalize_errors
    def registration_status(self, operation_id, payload):
        """Bounded historical operation status; no source files are decoded."""
        operation_id, payload = _token(operation_id), _payload(payload)
        with self._transaction() as cx:
            return self._registration_status(cx, operation_id, payload)

    @_normalize_errors
    def reserve_registration(self, operation_id, payload):
        """Durably reserve an exact intent, without resolving or copying files.

        The owner subsequently executes register_export with the same payload.
        A pending intent survives restart but is neither an imported release nor
        evidence that its package is currently available.
        """
        operation_id, payload = _token(operation_id), _payload(payload)
        with self._transaction() as cx:
            status = self._registration_status(cx, operation_id, payload)
            if status["state"] == "unknown":
                _require(cx.execute("SELECT count(*) FROM source_corpus.operations").fetchone()[0]
                         < self.limits.max_operations, "operation capacity exceeded")
                cx.execute("INSERT INTO source_corpus.operations VALUES (?,?,?,NULL)",
                           [operation_id, _digest(payload), _json(payload)])
                status["state"] = "pending"
            return status

    @_normalize_errors
    def pending_registrations(self, limit=1, *, operation_prefix=None):
        """Owner-only bounded enumeration; pending work is never auto-started."""
        _require(type(limit) is int and 1 <= limit <= 64, "invalid pending operation bound")
        if operation_prefix is not None:
            operation_prefix = _token(operation_prefix)
        with self._transaction() as cx:
            rows = cx.execute("SELECT operation_id,request_digest,request_json FROM source_corpus.operations WHERE receipt IS NULL AND (? IS NULL OR starts_with(operation_id,?)) ORDER BY operation_id LIMIT ?",
                              [operation_prefix, operation_prefix, limit]).fetchall()
            result = []
            for operation_id, digest, encoded in rows:
                operation_id = _token(operation_id)
                payload = _payload(json.loads(encoded))
                _require(digest == _digest(payload) and encoded == _json(payload),
                         "pending operation payload corruption")
                result.append({"operation_id": operation_id, "payload": payload})
            return result

    def _version(self, cx, version_id):
        row = cx.execute("SELECT v.dataset_id,v.release_id,v.metadata,d.binding,r.manifest,r.package_directory,r.row_count,r.row_digest,r.status,r.next_ordinal FROM source_corpus.versions v JOIN source_corpus.datasets d ON d.dataset_id=v.dataset_id JOIN source_corpus.releases r ON r.release_id=v.release_id WHERE v.version_id=?", [version_id]).fetchone()
        _require(row is not None and row[8] == "complete" and row[9] == row[6], "unknown or incomplete source version")
        payload = _payload({"dataset": json.loads(row[3]), "package_manifest_artifact": json.loads(row[4])})
        _require(_identities(payload) == (row[0], row[1], version_id), "source version identity mismatch")
        expected = {"schema_version": "source-corpus-version-v1", "version_id": version_id,
                    "dataset_id": row[0], "dataset": payload["dataset"], "release_id": row[1],
                    "package_manifest_artifact": payload["package_manifest_artifact"],
                    "package_directory": str(self.package_root / payload["package_manifest_artifact"]["sha256"]),
                    "row_count": row[6], "row_digest": row[7], "qualification": dict(_QUALIFICATION)}
        _require(row[5] == expected["package_directory"] and _json(json.loads(row[2])) == _json(expected), "version metadata differs from durable rows")
        _require(type(row[6]) is int and 0 <= row[6] <= self.limits.max_total_rows and type(row[7]) is str and _HASH.fullmatch(row[7]), "invalid durable row summary")
        return expected

    @_normalize_errors
    def get_version(self, version_id):
        with self._transaction() as cx:
            return self._version(cx, _token(version_id))

    @staticmethod
    def _receipt(operation_id, payload, version):
        return {"schema_version": "source-corpus-registration-v1", "operation_id": operation_id,
                **{key: version[key] for key in ("dataset_id", "version_id", "release_id", "row_count", "row_digest")},
                "package_manifest_artifact": payload["package_manifest_artifact"],
                "verification_scope": "registration_time_owned_package_and_materialized_rows",
                "current_availability_verified": False, **_QUALIFICATION}

    def _package(self, root, ref):
        raw = export._read(root / export.MANIFEST_NAME, 4 * 1024**2)
        _require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"], "package manifest differs")
        manifest = export._parse(raw)
        export._manifest(manifest, export.CorpusExportLimits())
        total = len(raw) + sum(item["bytes"] for item in manifest["files"])
        _require(total <= self.limits.max_package_bytes, "package byte bound exceeded")
        report = export.verify_uscode_source_export(root, expected_manifest_sha256=ref["sha256"])
        _require(report["manifest_artifact"]["bytes"] == ref["bytes"], "package descriptor changed")
        return raw, manifest, report, total

    def _copy_package(self, source, destination, raw, manifest):
        _require(not source.is_relative_to(self.package_root) and not self.package_root.is_relative_to(source), "source and owned package roots overlap")
        if not destination.exists():
            destination.mkdir(mode=0o700)
            parent_fd = export._directory(self.package_root)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        root_fd = export._directory(destination)
        try:
            limits = export.CorpusExportLimits(max_total_bytes=self.limits.max_package_bytes)
            budget = export._Budget(limits)
            items = [*manifest["files"], {"relative_path": export.MANIFEST_NAME, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "kind": "manifest"}]
            expected = {item["relative_path"] for item in items}
            # Only an operation-bound partial package may be resumed. Existing
            # completed files are verified exactly; damaged files are retained.
            present, pending, entries = set(), [destination], 0
            while pending:
                directory = pending.pop()
                with os.scandir(directory) as scanned:
                    for entry in scanned:
                        entries += 1
                        _require(entries <= limits.max_namespace_entries, "partial namespace exceeds bound")
                        info = entry.stat(follow_symlinks=False)
                        path = Path(entry.path)
                        if stat.S_ISDIR(info.st_mode):
                            _require(any(name.startswith(path.relative_to(destination).as_posix() + "/") for name in expected), "unexpected partial directory")
                            pending.append(path)
                        else:
                            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe partial package file")
                            present.add(path.relative_to(destination).as_posix())
            _require(present <= expected, "unexpected partial package file")
            for item in items:
                relative = item["relative_path"]
                target = destination / relative
                reference = {key: item[key] for key in ("sha256", "bytes")}
                if target.exists() or target.is_symlink():
                    export._hash(target, reference, maximum=limits.max_file_bytes)
                    budget.add_file(relative)
                    budget.charge(item["bytes"], 0)
                else:
                    export._copy(destination, root_fd, {"path": str(source / relative), **reference}, relative, budget, item["kind"])
                self._ensure_owner()
            export._namespace(destination, limits, expected)
            export._root_current(destination, root_fd)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)

    def _iter_rows(self, root, report):
        import pyarrow.parquet as pq
        for item in report["row_shards"]:
            path = root / item["relative_path"]
            with os.fdopen(export._regular(path), "rb") as stream:
                before = os.fstat(stream.fileno())
                parquet = pq.ParquetFile(stream)
                export._parquet_footer(parquet, item["row_count"], export.CorpusExportLimits(), export._arrow_schema())
                for batch in parquet.iter_batches(batch_size=self.limits.max_batch_rows, use_threads=False):
                    # Arrow pages are bounded by the verified Parquet footer.
                    # Row batches below are independently bounded in bytes.
                    for row in batch.to_pylist():
                        _row_contract(row)
                        yield row
                after = os.fstat(stream.fileno())
                _require(export._identity(before) == export._identity(after), "Parquet changed while reading")
            export._current_file(path, after)

    def _batches(self, root, report):
        rows, size = [], 2
        for row in self._iter_rows(root, report):
            encoded = len(_json(row).encode()) + 1
            _require(encoded + 2 <= self.limits.max_batch_bytes, "source row exceeds catalog batch byte bound")
            if rows and (len(rows) >= self.limits.max_batch_rows or size + encoded > self.limits.max_batch_bytes):
                yield rows
                rows, size = [], 2
            rows.append(row)
            size += encoded
        if rows:
            yield rows

    def _database_rows(self, cx, release_id, start, count):
        cursor = self._row_cursor(cx, release_id, start, count)
        result, size = [], 2
        while values := cursor.fetchone():
            row = self._cursor_row(values)
            size += len(_json(row).encode()) + 1
            _require(size <= self.limits.max_batch_bytes + 8192, "stored row batch exceeds byte bound")
            result.append(row)
        return result

    def _row_cursor(self, cx, release_id, start, count):
        # Avoid transferring an arbitrarily enlarged, corrupted VARCHAR to
        # Python. The SQL byte estimate is a lower bound; canonical JSON bytes
        # are checked separately on every actual row and returned page.
        # Both ordinal bounds restrict eligible rows before wide string work;
        # valid releases have contiguous ordinals, so this preserves the page.
        columns = ", ".join(('CASE WHEN _row_bytes<=? THEN "' + key + '" ELSE NULL END')
                            if ROW_TYPES[key] == "string" else '"' + key + '"' for key in ROW_FIELDS)
        bounds = [self.limits.max_batch_bytes for key in ROW_FIELDS if ROW_TYPES[key] == "string"]
        return cx.execute("SELECT ordinal,_row_bytes," + columns + " FROM (SELECT ordinal," + _COLUMNS + ",(" + _STRING_BYTES + ") AS _row_bytes FROM source_corpus.rows WHERE release_id=? AND ordinal>=? AND ordinal<? ORDER BY ordinal LIMIT ?)",
                          [*bounds, release_id, start, start + count, count])

    def _cursor_row(self, values):
        _require(type(values[1]) is int and values[1] <= self.limits.max_batch_bytes, "stored row exceeds byte bound")
        row = {"ordinal":values[0], **dict(zip(ROW_FIELDS, values[2:]))}
        _row_contract({key:row[key] for key in ROW_FIELDS})
        return row

    def _store_batch(self, release_id, start, rows):
        """One durable insert/checkpoint; interruption after return is resumable."""
        import pyarrow as pa
        _require(rows and len(rows) <= self.limits.max_batch_rows and len(_json(rows).encode()) <= self.limits.max_batch_bytes,
                 "materialization batch exceeds bound")
        schema = pa.schema([pa.field("release_id", pa.string(), nullable=False), pa.field("ordinal", pa.int64(), nullable=False), *export._arrow_schema()])
        table = pa.Table.from_pylist([{"release_id": release_id, "ordinal": start + offset, **row} for offset, row in enumerate(rows)], schema=schema)
        _require(table.nbytes <= self.limits.max_batch_bytes and table.schema.equals(schema, check_metadata=True), "Arrow batch exceeds bound or schema")
        with self._transaction() as cx:
            state = cx.execute("SELECT status,next_ordinal,row_count FROM source_corpus.releases WHERE release_id=?", [release_id]).fetchone()
            _require(state is not None and state[0] == "loading" and state[1] == start and start + len(rows) <= state[2], "batch checkpoint conflict")
            # Trusted, scoped Arrow hand-off. SQL accepts no caller expression,
            # filename or table name; filesystem SQL remains disabled.
            cx.raw.register("_source_corpus_batch", table)
            try:
                cx.execute("INSERT INTO source_corpus.rows SELECT release_id,ordinal," + _COLUMNS + " FROM _source_corpus_batch")
            finally:
                cx.raw.unregister("_source_corpus_batch")
            cx.execute("INSERT INTO source_corpus.batches VALUES (?,?,?,?)", [release_id, start, len(rows), _rows_digest(rows, start)])
            cx.execute("UPDATE source_corpus.releases SET next_ordinal=? WHERE release_id=?", [start + len(rows), release_id])

    def _readback(self, release_id, root, report):
        digest, start = hashlib.sha256(), 0
        for rows in self._batches(root, report):
            with self._transaction() as cx:
                actual = self._database_rows(cx, release_id, start, len(rows))
            expected = [{"ordinal": start + offset, **row} for offset, row in enumerate(rows)]
            _require(_json(actual) == _json(expected), "materialized rows differ from owned package")
            for row in expected:
                digest.update(_json(row).encode() + b"\n")
            start += len(rows)
        with self._transaction() as cx:
            count = cx.execute("SELECT count(*) FROM source_corpus.rows WHERE release_id=?", [release_id]).fetchone()[0]
            checkpoints = cx.execute("SELECT start_ordinal,row_count,digest FROM source_corpus.batches WHERE release_id=? ORDER BY start_ordinal", [release_id]).fetchall()
        _require(start == count == report["row_count"], "materialized row count mismatch")
        end = 0
        for offset, count, expected_digest in checkpoints:
            _require(type(count) is int and 0 < count <= 64 and offset == end, "invalid batch checkpoint sequence")
            with self._transaction() as cx:
                actual = self._database_rows(cx, release_id, offset, count)
            actual_digest = hashlib.sha256(b"".join(_json(row).encode() + b"\n" for row in actual)).hexdigest()
            _require(len(actual) == count and actual_digest == expected_digest, "batch checkpoint differs from rows")
            end += count
        _require(end == start, "batch checkpoint coverage mismatch")
        return digest.hexdigest()

    @_normalize_errors
    def register_export(self, operation_id, *, dataset, package_manifest_artifact, package_resolver):
        operation_id = _token(operation_id)
        payload = _payload({"dataset": dataset, "package_manifest_artifact": package_manifest_artifact})
        dataset_id, release_id, version_id = _identities(payload)
        ref = payload["package_manifest_artifact"]
        destination = self.package_root / ref["sha256"]
        with self._lock:
            with self._transaction() as cx:
                receipt = self._operation(cx, operation_id, payload)
                if receipt is not None:
                    return receipt
                operation = cx.execute("SELECT operation_id FROM source_corpus.operations WHERE operation_id=?", [operation_id]).fetchone()
                release = cx.execute("SELECT manifest,package_directory,package_bytes,row_count,row_digest,status,owner_operation,next_ordinal FROM source_corpus.releases WHERE release_id=?", [release_id]).fetchone()
                if release is not None:
                    _require(release[0] == _json(ref) and release[1] == str(destination), "release descriptor conflict")
                    _require(release[5] in {"loading", "complete"} and type(release[7]) is int
                             and 0 <= release[7] <= release[3] <= 65536, "invalid release state")
                    _require(release[5] == "complete" or release[6] == operation_id, "incomplete release belongs to another operation")
                if operation is None:
                    _require(cx.execute("SELECT count(*) FROM source_corpus.operations").fetchone()[0] < self.limits.max_operations, "operation capacity exceeded")
                existing_version = cx.execute("SELECT version_id FROM source_corpus.versions WHERE version_id=?", [version_id]).fetchone()
                _require(existing_version is not None or cx.execute("SELECT count(*) FROM source_corpus.versions").fetchone()[0] < self.limits.max_versions, "version capacity exceeded")
            if release is not None and (destination / export.MANIFEST_NAME).exists():
                raw, manifest, report, total = self._package(destination, ref)
                _require((total, report["row_count"]) == (release[2], release[3]), "owned release summary changed")
            else:
                source_manifest = _path(package_resolver(dict(ref)))
                _require(source_manifest.name == export.MANIFEST_NAME, "resolver must identify source-export.json")
                source = source_manifest.parent
                _require(not source.is_relative_to(self.package_root) and not self.package_root.is_relative_to(source), "source/output alias is forbidden")
                raw, manifest, report, total = self._package(source, ref)
                self._ensure_owner()
                with self._transaction() as cx:
                    if release is None:
                        counts = cx.execute("SELECT count(*),coalesce(sum(package_bytes),0),coalesce(sum(row_count),0) FROM source_corpus.releases").fetchone()
                        _require(counts[0] < self.limits.max_releases and counts[1] + total <= self.limits.max_owned_package_bytes and counts[2] + report["row_count"] <= self.limits.max_total_rows, "catalog release capacity exceeded")
                        _require(not destination.exists(), "unbound owned package directory")
                        if operation is None:
                            cx.execute("INSERT INTO source_corpus.operations VALUES (?,?,?,NULL)", [operation_id, _digest(payload), _json(payload)])
                            operation = (operation_id,)
                        cx.execute("INSERT INTO source_corpus.releases VALUES (?,?,?,?,?,NULL,'loading',?,0)", [release_id, _json(ref), str(destination), total, report["row_count"], operation_id])
                    else:
                        _require((total, report["row_count"]) == (release[2], release[3]), "resumed package differs")
                self._copy_package(source, destination, raw, manifest)
                raw, manifest, report, total = self._package(destination, ref)
                for item in manifest["files"]:
                    export._hash(source / item["relative_path"], {key:item[key] for key in ("sha256","bytes")}, maximum=256 * 1024**2)
                export._hash(source / export.MANIFEST_NAME, ref, maximum=4 * 1024**2)
            with self._transaction() as cx:
                if operation is None:
                    cx.execute("INSERT INTO source_corpus.operations VALUES (?,?,?,NULL)", [operation_id, _digest(payload), _json(payload)])
                state = cx.execute("SELECT status,next_ordinal,row_digest FROM source_corpus.releases WHERE release_id=?", [release_id]).fetchone()
            if state[0] == "loading":
                start = 0
                for rows in self._batches(destination, report):
                    if start < state[1]:
                        # Resume boundaries do not depend on the next caller's
                        # batch size; split around the exact durable prefix.
                        count = min(len(rows), state[1] - start)
                        with self._transaction() as cx:
                            actual = self._database_rows(cx, release_id, start, count)
                        _require(_json(actual) == _json([{"ordinal": start+i, **row} for i,row in enumerate(rows[:count])]), "resumed prefix differs")
                        start += count
                        rows = rows[count:]
                    if rows:
                        self._store_batch(release_id, start, rows)
                        start += len(rows)
            row_digest = self._readback(release_id, destination, report)
            _require(state[0] == "loading" or state[2] == row_digest, "committed row digest differs")
            # Rehash exact owned bytes after every decode/database comparison.
            for item in manifest["files"]:
                export._hash(destination / item["relative_path"], {key:item[key] for key in ("sha256","bytes")}, maximum=256 * 1024**2)
            export._hash(destination / export.MANIFEST_NAME, ref, maximum=4 * 1024**2)
            export._namespace(destination, export.CorpusExportLimits(), {export.MANIFEST_NAME, *(item["relative_path"] for item in manifest["files"])})
            version = {"schema_version":"source-corpus-version-v1", "version_id":version_id, "dataset_id":dataset_id,
                       "dataset":payload["dataset"], "release_id":release_id, "package_manifest_artifact":ref,
                       "package_directory":str(destination), "row_count":report["row_count"], "row_digest":row_digest,
                       "qualification":dict(_QUALIFICATION)}
            receipt = self._receipt(operation_id, payload, version)
            with self._transaction() as cx:
                self._operation(cx, operation_id, payload)
                binding = cx.execute("SELECT binding FROM source_corpus.datasets WHERE dataset_id=?", [dataset_id]).fetchone()
                _require(binding is None or binding[0] == _json(payload["dataset"]), "dataset binding differs")
                if binding is None:
                    cx.execute("INSERT INTO source_corpus.datasets VALUES (?,?)", [dataset_id, _json(payload["dataset"])])
                existing = cx.execute("SELECT metadata FROM source_corpus.versions WHERE version_id=?", [version_id]).fetchone()
                _require(existing is None or existing[0] == _json(version), "version binding differs")
                if existing is None:
                    cx.execute("INSERT INTO source_corpus.versions VALUES (?,?,?,?)", [version_id,dataset_id,release_id,_json(version)])
                cx.execute("UPDATE source_corpus.releases SET status='complete',row_digest=? WHERE release_id=?", [row_digest,release_id])
                cx.execute("UPDATE source_corpus.operations SET receipt=? WHERE operation_id=?", [_json(receipt),operation_id])
            return receipt

    @_normalize_errors
    def read_rows(self, version_id, after_ordinal=-1, limit=64, max_bytes=None):
        max_bytes = self.limits.max_read_bytes if max_bytes is None else max_bytes
        _require(type(after_ordinal) is int and -1 <= after_ordinal <= self.limits.max_total_rows, "invalid row cursor")
        _require(type(limit) is int and 1 <= limit <= self.limits.max_read_rows and type(max_bytes) is int and 2 <= max_bytes <= self.limits.max_read_bytes, "invalid page bound")
        with self._transaction() as cx:
            version = self._version(cx, _token(version_id))
            cursor = self._row_cursor(cx, version["release_id"], after_ordinal + 1, limit)
            page, size, byte_limited = [], 2, False
            while values := cursor.fetchone():
                row = self._cursor_row(values)
                _require(row["ordinal"] == after_ordinal + len(page) + 1 and row["ordinal"] < version["row_count"], "row ordinal gap or overflow")
                addition = len(_json(row).encode()) + bool(page)
                if size + addition > max_bytes:
                    _require(page, "first row exceeds page byte bound")
                    byte_limited = True
                    break
                page.append(row)
                size += addition
        expected_count = min(limit, max(0, version["row_count"] - after_ordinal - 1))
        _require(byte_limited or len(page) == expected_count, "materialized row window incomplete")
        last = page[-1]["ordinal"] if page else after_ordinal
        complete = last >= version["row_count"] - 1
        _require(page or complete, "materialized rows missing")
        return {"version_id":version_id, "rows":page, "next_after_ordinal":None if complete else last,
                "complete":complete, "row_count":len(page)}

    @_normalize_errors
    def verify_version(self, version_id):
        with self._lock:
            version = self.get_version(version_id)
            root = Path(version["package_directory"])
            raw, manifest, report, total = self._package(root, version["package_manifest_artifact"])
            digest = self._readback(version["release_id"], root, report)
            _require(digest == version["row_digest"] and report["row_count"] == version["row_count"], "current materialized release differs")
            for item in manifest["files"]:
                export._hash(root / item["relative_path"], {key:item[key] for key in ("sha256","bytes")}, maximum=256 * 1024**2)
            export._hash(root / export.MANIFEST_NAME, version["package_manifest_artifact"], maximum=4 * 1024**2)
            _require(self.get_version(version_id) == version, "version changed during verification")
            return {"schema_version":"source-corpus-verification-v1", "version_id":version_id,
                    "release_id":version["release_id"], "row_count":version["row_count"], "row_digest":digest,
                    "current_package_verified":True, "materialized_rows_verified":True,
                    "qualification":dict(_QUALIFICATION)}
