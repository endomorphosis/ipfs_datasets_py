"""Isolated native DuckLake source rows with exact durable commit reconciliation.

This optional sink consumes a verified, read-only package binding. It never opens
the historical source catalog, registers immutable package files into DATA_PATH,
loads a model, starts a listener, or activates a production namespace. DuckLake
creates its own managed files. Rows and operation markers commit together;
neither a snapshot nor a captured source version is a legal admit.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

from . import autoencoder_history as history
from ..duckdb_control.source_corpus_binding import SourceCorpusBinding, validate_source_version
from ..duckdb_control.source_corpus_catalog import _row_contract
from ..optimizers.logic_theorem_optimizer import autoencoder_uscode_corpus_export as export
from ..optimizers.logic_theorem_optimizer.autoencoder_uscode_corpus_rows import ROW_FIELDS, ROW_TYPES


SCHEMA = "isolated-native-source-corpus-v1"
RECEIPT_SCHEMA = "source-corpus-ducklake-commit-v1"
MAX_STORAGE_BYTES = 1024**3
MAX_ROWS = 65536
MAX_VERSIONS = 64
MAX_OPERATIONS = 256
MAX_INSERT_ROWS = 4096
MAX_ROW_BYTES = 8 * 1024**2
MAX_CONTROL_BYTES = 64 * 1024
_AUTHOR = SCHEMA
_QUALIFICATION = dict.fromkeys(("admitted", "formalized", "source_authority_authenticated",
                              "language_verified", "publication_performed", "production_activated"), False)
_SQL_TYPES = {"string": "VARCHAR", "int64": "BIGINT", "bool": "BOOLEAN"}
_COLUMNS = ",".join('"' + name + '"' for name in ROW_FIELDS)
_DDL = (
    "CREATE TABLE corpus.identity (identity_json VARCHAR)",
    "CREATE TABLE corpus.releases (release_id VARCHAR, summary_json VARCHAR)",
    "CREATE TABLE corpus.versions (version_id VARCHAR, version_json VARCHAR)",
    "CREATE TABLE corpus.operations (operation_id VARCHAR, request_json VARCHAR, commit_key VARCHAR)",
    "CREATE TABLE corpus.rows (release_id VARCHAR, ordinal BIGINT," +
    ",".join('"' + name + '" ' + _SQL_TYPES[ROW_TYPES[name]] for name in ROW_FIELDS) + ")",
)
_TABLE_COLUMNS = {
    "identity": [("identity_json", "VARCHAR")],
    "releases": [("release_id", "VARCHAR"), ("summary_json", "VARCHAR")],
    "versions": [("version_id", "VARCHAR"), ("version_json", "VARCHAR")],
    "operations": [("operation_id", "VARCHAR"), ("request_json", "VARCHAR"), ("commit_key", "VARCHAR")],
    "rows": [("release_id", "VARCHAR"), ("ordinal", "BIGINT"),
             *((name, _SQL_TYPES[ROW_TYPES[name]]) for name in ROW_FIELDS)],
}
_STRING_BYTES = "+".join('coalesce(octet_length(encode("' + name + '")),0)'
                         for name in ROW_FIELDS if ROW_TYPES[name] == "string")


class SourceCorpusLakeError(ValueError):
    """Changed, conflicting, unsafe or unverifiable native source data."""


def _require(condition, message):
    if not condition:
        raise SourceCorpusLakeError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _control(value):
    raw = _json(value).encode("utf-8")
    _require(len(raw) <= MAX_CONTROL_BYTES, "control record exceeds byte bound")
    return raw.decode("utf-8")


def _id(value):
    return "sha256:" + hashlib.sha256(_control(value).encode("utf-8")).hexdigest()


def _token(value):
    _require(type(value) is str and 1 <= len(value) <= 256 and value.isascii()
             and all(ch.isalnum() or ch in "_.:/@+-" for ch in value), "invalid operation or version identifier")
    return value


def _path(value):
    path = history._lexical_path(str(value))
    _require(path.resolve() == path, "native source namespace path is aliased")
    return path


def _signature(path):
    info = path.lstat()
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _row(value, ordinal=None):
    _require(type(value) is dict and set(value) == {"ordinal", *ROW_FIELDS}, "invalid source row fields")
    _require(type(value["ordinal"]) is int and 0 <= value["ordinal"] < MAX_ROWS
             and (ordinal is None or value["ordinal"] == ordinal), "source ordinal gap or overflow")
    try:
        _row_contract({name: value[name] for name in ROW_FIELDS})
    except ValueError as exc:
        raise SourceCorpusLakeError(str(exc)) from exc
    raw = _json(value).encode("utf-8")
    _require(len(raw) <= MAX_ROW_BYTES, "source row exceeds byte bound")
    return raw


class IsolatedNativeSourceCorpus:
    """One local native owner; configured limits are part of durable identity.

    lookup verifies current sink data and the original native snapshot. It does
    not assert current source-package availability. materialize_version always
    rechecks its entered source binding, including an already committed retry.
    read_rows is bounded current row access; use lookup for whole-release proof
    of storage integrity. No method establishes legal or source authority.
    """

    def __init__(self, root, *, create=False, production=False, max_storage_bytes=MAX_STORAGE_BYTES):
        _require(type(create) is bool and type(production) is bool and not production,
                 "production activation is held; flags must be exact booleans")
        _require(type(max_storage_bytes) is int and 1 <= max_storage_bytes <= MAX_STORAGE_BYTES,
                 "invalid native source storage cap")
        self.root = _path(root)
        self._pid, self._mutex = os.getpid(), threading.RLock()
        self._closed, self._connection, self._fd = False, None, None
        self._max_storage_bytes = max_storage_bytes
        self._catalog, self._data = self.root / "source.ducklake", self.root / "data"
        self._descriptor = self.root / "source.json"
        try:
            if create:
                self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
            _require(stat.S_ISDIR(self.root.lstat().st_mode), "native source root is not a directory")
            self._root_identity = _signature(self.root)[:2]
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            self._fd = os.open(self.root / "owner.lock", flags, 0o600)
            _require(stat.S_ISREG(os.fstat(self._fd).st_mode), "owner lock must be regular")
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._guard_paths()
            if not create:
                _require(self._catalog.is_file() and self._data.is_dir(), "incomplete native source namespace")
            self._connection, runtime = history._native_connection()
            self._connection.execute("SET memory_limit='512MB'")
            self._extension_signatures = {}
            for name in runtime["extensions"]:
                path = Path.home() / ".duckdb/extensions" / ("v" + runtime["duckdb"]) / runtime["platform"] / (name + ".duckdb_extension")
                _require(hashlib.sha256(history._read(path, 128 * 1024**2)).hexdigest() == runtime["extensions"][name],
                         "extension changed after native initialization")
                self._extension_signatures[str(path)] = _signature(path)
            body = {"schema_version": SCHEMA, "scope": "isolated_source_corpus", "root": str(self.root),
                    "catalog_path": str(self._catalog), "data_path": str(self._data), "runtime": runtime,
                    "schema_sha256": hashlib.sha256(_control(_DDL).encode()).hexdigest(),
                    "max_storage_bytes": max_storage_bytes, "max_rows": MAX_ROWS,
                    "max_insert_rows": MAX_INSERT_ROWS, "max_insert_batch_bytes": MAX_ROW_BYTES,
                    "production_activated": False}
            self._identity = {**body, "sink_id": _id(body)}
            self._descriptor_bytes = _control(self._identity).encode("utf-8")
            if not create:
                _require(history._read(self._descriptor, MAX_CONTROL_BYTES) == self._descriptor_bytes,
                         "native source descriptor/runtime mismatch")
            self._connection.execute(f"ATTACH {history._literal('ducklake:' + str(self._catalog))} AS corpus (DATA_PATH {history._literal(self._data)}, CREATE_IF_NOT_EXISTS {str(create).lower()}, OVERRIDE_DATA_PATH false, AUTOMATIC_MIGRATION false, DATA_INLINING_ROW_LIMIT 0)")
            _require(self._connection.execute("SELECT value FROM __ducklake_metadata_corpus.main.ducklake_metadata WHERE key='version'").fetchone() == ("1.0",), "DuckLake catalog version mismatch")
            if create:
                self._connection.execute("BEGIN")
                try:
                    for statement in _DDL:
                        self._connection.execute(statement)
                    self._connection.execute("INSERT INTO corpus.identity VALUES (?)", [self._descriptor_bytes.decode()])
                    self._connection.execute("COMMIT")
                except BaseException:
                    self._rollback()
                    raise
                fd = os.open(self._descriptor, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(self._descriptor_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            self._path_identities = {str(path): _signature(path)[:2] for path in (self._catalog, self._data)}
            self._shape()
            self._boundary()
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                error.add_note("native source cleanup failed: " + type(cleanup).__name__)
            raise

    @property
    def identity(self):
        return json.loads(_control(self._identity))

    def _owner_process(self):
        _require(os.getpid() == self._pid, "native source owner cannot be inherited by another process")

    def _guard_paths(self):
        self._owner_process()
        _require(self.root.resolve() == self.root and _signature(self.root)[:2] == self._root_identity,
                 "native source root identity changed")
        for value, identity in getattr(self, "_path_identities", {}).items():
            path = Path(value)
            _require(path.resolve() == path and _signature(path)[:2] == identity, "native catalog/data path identity changed")
        if self._fd is not None:
            actual = os.fstat(self._fd)
            named = (self.root / "owner.lock").lstat()
            _require(stat.S_ISREG(named.st_mode) and named.st_nlink == 1
                     and (actual.st_dev, actual.st_ino) == (named.st_dev, named.st_ino), "native owner lock changed")
        total = 0
        for index, path in enumerate(self.root.rglob("*")):
            info = path.lstat()
            _require(index < 10000 and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)),
                     "native source namespace has aliases/special files or too many entries")
            if stat.S_ISREG(info.st_mode):
                _require(info.st_nlink == 1, "native source namespace has hard-linked files")
                total += info.st_size
        _require(total <= self._max_storage_bytes, "native source namespace exceeds byte cap")
        return total

    def _shape(self):
        tables = self._connection.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_catalog='corpus'").fetchall()
        _require(set(tables) == {("main", name) for name in _TABLE_COLUMNS}, "native source schema table set changed")
        for name, columns in _TABLE_COLUMNS.items():
            actual = self._connection.execute("DESCRIBE corpus." + name).fetchall()
            _require([(item[0], item[1]) for item in actual] == columns, "native source table columns changed")

    def _boundary(self):
        _require(not self._closed, "native source sink is closed")
        self._guard_paths()
        for path, signature in self._extension_signatures.items():
            _require(Path(path).resolve() == Path(path) and _signature(Path(path)) == signature,
                     "pinned extension changed during native source ownership")
        _require(history._read(self._descriptor, MAX_CONTROL_BYTES) == self._descriptor_bytes,
                 "native source descriptor changed")
        _require(self._one_json("identity", "identity_json") == self._descriptor_bytes.decode(),
                 "native source identity row changed")

    def _one_json(self, table, column, key=None, value=None):
        # Fixed internal identifiers only. Reject enlarged metadata in SQL before
        # transferring its contents to Python; detect duplicate keys explicitly.
        where, params = ("", []) if key is None else (" WHERE " + key + "=?", [value])
        rows = self._connection.execute("SELECT octet_length(encode(" + column + ")), CASE WHEN octet_length(encode(" + column + "))<=? THEN " + column + " ELSE NULL END FROM corpus." + table + where + " LIMIT 2", [MAX_CONTROL_BYTES, *params]).fetchall()
        if not rows:
            return None
        _require(len(rows) == 1 and type(rows[0][0]) is int and rows[0][0] <= MAX_CONTROL_BYTES
                 and type(rows[0][1]) is str, "duplicate or oversized native metadata")
        return rows[0][1]

    def _request(self, operation_id, source_version):
        source = validate_source_version(source_version)
        _require(source["row_count"] <= MAX_ROWS, "source row count exceeds native sink limit")
        return {"schema_version": "source-corpus-ducklake-request-v1", "operation_id": _token(operation_id),
                "sink_id": self._identity["sink_id"], "source_version": source}

    @staticmethod
    def _release(source):
        return {name: source[name] for name in ("release_id", "package_manifest_artifact", "row_count", "row_digest")}

    def _version(self, version_id):
        raw = self._one_json("versions", "version_json", "version_id", _token(version_id))
        _require(raw is not None, "native source version not committed")
        source = validate_source_version(json.loads(raw))
        _require(source["version_id"] == version_id and raw == _control(source), "native version binding changed")
        return source

    def _rows(self, release_id, start, limit):
        expressions = ["CASE WHEN _row_bytes<=? THEN \"" + name + "\" ELSE NULL END"
                       if ROW_TYPES[name] == "string" else '"' + name + '"' for name in ROW_FIELDS]
        params = [MAX_ROW_BYTES for name in ROW_FIELDS if ROW_TYPES[name] == "string"]
        cursor = self._connection.execute("SELECT ordinal,_row_bytes," + ",".join(expressions) +
            " FROM (SELECT ordinal," + _COLUMNS + ",(" + _STRING_BYTES + ") AS _row_bytes FROM corpus.rows WHERE release_id=? AND ordinal>=? AND ordinal<? ORDER BY ordinal LIMIT ?)",
            [*params, release_id, start, start + limit, limit])
        while values := cursor.fetchone():
            _require(type(values[1]) is int and values[1] <= MAX_ROW_BYTES, "native row exceeds byte bound")
            row = {"ordinal": values[0], **dict(zip(ROW_FIELDS, values[2:]))}
            _row(row)
            yield row

    def _verify_rows(self, source):
        release = source["release_id"]
        summary = self._one_json("releases", "summary_json", "release_id", release)
        _require(summary == _control(self._release(source)), "native release summary differs")
        count, unique_ordinals, unique_ids = self._connection.execute("SELECT count(*),count(DISTINCT ordinal),count(DISTINCT source_row_id) FROM corpus.rows WHERE release_id=?", [release]).fetchone()
        _require(count == unique_ordinals == unique_ids == source["row_count"], "native row count or physical uniqueness differs")
        digest, ordinal = hashlib.sha256(), 0
        while ordinal < count:
            rows = self._rows(release, ordinal, min(64, count - ordinal))
            observed = 0
            for row in rows:
                digest.update(_row(row, ordinal) + b"\n")
                ordinal += 1
                observed += 1
            _require(observed > 0, "native source rows made no progress")
        _require(digest.hexdigest() == source["row_digest"], "native ordered row digest differs")

    def _lookup(self, request):
        source = request["source_version"]
        operation, commit_key = request["operation_id"], _id(request)
        marker = self._one_json("operations", "request_json", "operation_id", operation)
        snapshots = self._connection.execute("SELECT snapshot_id FROM corpus.snapshots() WHERE author=? AND commit_message=? LIMIT 2", [_AUTHOR, commit_key]).fetchall()
        if marker is None:
            _require(not snapshots, "native snapshot has no operation marker")
            return None
        _require(marker == _control(request), "operation identifier conflicts with source binding")
        keys = self._connection.execute("SELECT commit_key FROM corpus.operations WHERE operation_id=? LIMIT 2", [operation]).fetchall()
        _require(keys == [(commit_key,)] and len(snapshots) == 1 and type(snapshots[0][0]) is int
                 and snapshots[0][0] >= 1, "native marker/snapshot identity differs")
        _require(self._version(source["version_id"]) == source, "native version differs from requested source")
        self._verify_rows(source)
        return {"schema_version": RECEIPT_SCHEMA, "scope": "isolated_source_corpus",
                "operation_id": operation, "request_digest": commit_key, "sink_id": self._identity["sink_id"],
                "source_version": source, "snapshot_id": snapshots[0][0], "row_count": source["row_count"],
                "row_digest": source["row_digest"], "source_rows_verified": True,
                "source_package_currently_verified": False, "qualification": dict(_QUALIFICATION)}

    def lookup(self, operation_id, source_version):
        self._owner_process()
        request = self._request(operation_id, source_version)
        with self._mutex:
            self._boundary()
            self._shape()
            result = self._lookup(request)
            self._boundary()
            return result

    def _insert_rows(self, source, binding):
        import pyarrow as pa
        schema = pa.schema([pa.field("release_id", pa.string(), nullable=False),
                            pa.field("ordinal", pa.int64(), nullable=False), *export._arrow_schema()])
        rows, size, ordinal = [], 2, 0

        def flush():
            _require(0 < len(rows) <= MAX_INSERT_ROWS and len(_json(rows).encode()) <= MAX_ROW_BYTES,
                     "native insertion batch exceeds row or byte bound")
            table = pa.Table.from_pylist(rows, schema=schema)
            _require(table.nbytes <= MAX_ROW_BYTES and table.schema.equals(schema, check_metadata=True),
                     "native insertion Arrow batch exceeds bound or schema")
            self._connection.register("_verified_source_batch", table)
            try:
                self._connection.execute("INSERT INTO corpus.rows SELECT * FROM _verified_source_batch")
            finally:
                self._connection.unregister("_verified_source_batch")
            self._guard_paths()

        iterator = binding.iter_rows()
        try:
            for row in iterator:
                _row(row, ordinal)
                value = {"release_id": source["release_id"], **row}
                row_bytes = len(_json(value).encode()) + 1
                _require(row_bytes + 2 <= MAX_ROW_BYTES, "native insertion row exceeds batch bound")
                if rows and (len(rows) >= MAX_INSERT_ROWS or size + row_bytes > MAX_ROW_BYTES):
                    flush()
                    rows, size = [], 2
                rows.append(value)
                size += row_bytes
                ordinal += 1
                _require(ordinal <= source["row_count"], "source iterator returned excess rows")
            if rows:
                flush()
        finally:
            iterator.close()
        _require(ordinal == source["row_count"], "source iterator returned incomplete rows")

    def _rollback(self):
        try:
            self._connection.execute("ROLLBACK")
        except Exception:
            pass

    def materialize_version(self, operation_id, binding):
        self._owner_process()
        _require(type(binding) is SourceCorpusBinding, "materialization requires an entered exact source binding")
        source = binding.source_version
        _require(not binding.package_root.is_relative_to(self.root)
                 and not self.root.is_relative_to(binding.package_root), "source package and native sink overlap")
        request = self._request(operation_id, source)
        with self._mutex:
            self._boundary()
            self._shape()
            binding.verify_current()
            prior = self._lookup(request)
            if prior is not None:
                binding.verify_current()
                self._boundary()
                return prior
            _require(self._guard_paths() + 16 * 1024**2 <= self._max_storage_bytes,
                     "native source cap cannot fit minimum append reserve")
            _require(self._connection.execute("SELECT count(*) FROM corpus.operations").fetchone()[0] < MAX_OPERATIONS,
                     "native operation count exceeds bound")
            existing_version = self._one_json("versions", "version_json", "version_id", source["version_id"])
            _require(existing_version is not None
                     or self._connection.execute("SELECT count(*) FROM corpus.versions").fetchone()[0] < MAX_VERSIONS,
                     "native version count exceeds bound")
            self._connection.execute("BEGIN")
            try:
                release = self._one_json("releases", "summary_json", "release_id", source["release_id"])
                if release is None:
                    _require(self._connection.execute("SELECT count(*) FROM corpus.rows WHERE release_id=?", [source["release_id"]]).fetchone() == (0,), "unbound native source rows exist")
                    self._insert_rows(source, binding)
                    self._connection.execute("INSERT INTO corpus.releases VALUES (?,?)", [source["release_id"], _control(self._release(source))])
                else:
                    _require(release == _control(self._release(source)), "native release identity conflicts")
                old_version = self._one_json("versions", "version_json", "version_id", source["version_id"])
                _require(old_version is None or old_version == _control(source), "native version identity conflicts")
                if old_version is None:
                    self._connection.execute("INSERT INTO corpus.versions VALUES (?,?)", [source["version_id"], _control(source)])
                self._verify_rows(source)
                binding.verify_current()
                _require(binding.source_version == source, "source binding changed during materialization")
                self._guard_paths()
                self._connection.execute("INSERT INTO corpus.operations VALUES (?,?,?)", [operation_id, _control(request), _id(request)])
                self._connection.execute("CALL corpus.set_commit_message(?, ?)", [_AUTHOR, _id(request)])
                self._connection.execute("COMMIT")
            except BaseException:
                self._rollback()
                raise
            result = self._lookup(request)
            binding.verify_current()
            self._boundary()
            _require(result is not None, "native source commit could not be verified")
            return result

    def read_rows(self, version_id, *, after_ordinal=-1, limit=64, max_bytes=MAX_ROW_BYTES):
        self._owner_process()
        _require(type(after_ordinal) is int and -1 <= after_ordinal <= MAX_ROWS and type(limit) is int
                 and 1 <= limit <= 256 and type(max_bytes) is int and 2 <= max_bytes <= MAX_ROW_BYTES,
                 "invalid native row page bounds")
        with self._mutex:
            self._boundary()
            source = self._version(version_id)
            rows, size, next_ordinal = [], 2, after_ordinal + 1
            expected_count = max(0, min(limit, source["row_count"] - next_ordinal))
            byte_limited = False
            iterator = self._rows(source["release_id"], next_ordinal, limit)
            try:
                for row in iterator:
                    encoded = _row(row, next_ordinal)
                    _require(next_ordinal < source["row_count"], "native row exceeds committed count")
                    addition = len(encoded) + bool(rows)
                    if size + addition > max_bytes:
                        _require(rows, "first native row exceeds page byte bound")
                        byte_limited = True
                        break
                    rows.append(row)
                    size += addition
                    next_ordinal += 1
            finally:
                iterator.close()
            complete = next_ordinal >= source["row_count"]
            _require(byte_limited or len(rows) == expected_count, "native source page has a missing endpoint")
            _require(rows or complete, "native source rows missing")
            self._boundary()
            return {"version_id": version_id, "rows": rows, "row_count": len(rows),
                    "complete": complete, "next_after_ordinal": None if complete else next_ordinal - 1}

    def close(self):
        self._owner_process()
        with self._mutex:
            self._closed = True
            try:
                if self._connection is not None:
                    self._connection.close()
            finally:
                self._connection = None
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None

    def __enter__(self):
        self._boundary()
        return self

    def __exit__(self, *args):
        self.close()
