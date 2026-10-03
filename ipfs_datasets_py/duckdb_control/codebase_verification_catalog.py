"""Durable, exact references to historical conditional codebase evidence.

This additive domain shares the structural AST owner's file-backed connection.
It never changes structural heads or writes an authoritative proof cache. Reads
replay immutable native artifacts without solvers and observe the current tree
at both boundaries. A current source observation does not attest historical
process observations or establish Python runtime, kernel or planner authority.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath
import time
from typing import Any, Iterator

from .codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
from ipfs_datasets_py.logic.software_contracts.codebase_verification import (
    CodebaseVerificationRecord, load_codebase_verification,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_structured, validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore

SCHEMA = "codebase-verification-control@1"
PROJECTION_SCHEMA = "codebase-conditional-verification-projection@1"
REQUEST_SCHEMA = "codebase-verification-publication-request@1"
_DOMAIN = "codebase_verification_control"
_DDL = (
    f"CREATE SCHEMA {_DOMAIN}",
    f"CREATE TABLE {_DOMAIN}.meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, schema_cid VARCHAR NOT NULL, catalog_cid VARCHAR NOT NULL, artifact_root VARCHAR NOT NULL)",
    f"CREATE TABLE {_DOMAIN}.records (projection_cid VARCHAR PRIMARY KEY, repository_id VARCHAR NOT NULL, head_cid VARCHAR NOT NULL, path VARCHAR NOT NULL, verification_cid VARCHAR NOT NULL, applicability_cid VARCHAR NOT NULL, payload VARCHAR NOT NULL)",
    f"CREATE TABLE {_DOMAIN}.entries (entry_id VARCHAR PRIMARY KEY, projection_cid VARCHAR NOT NULL, repository_id VARCHAR NOT NULL, head_cid VARCHAR NOT NULL, path VARCHAR NOT NULL, contract_id VARCHAR NOT NULL, contract_cid VARCHAR NOT NULL, domain_id VARCHAR NOT NULL, domain_cid VARCHAR NOT NULL, keys_json VARCHAR NOT NULL, dependencies_json VARCHAR NOT NULL)",
    f"CREATE TABLE {_DOMAIN}.operations (operation_id VARCHAR PRIMARY KEY, request_cid VARCHAR NOT NULL, projection_cid VARCHAR NOT NULL)",
)
_COLUMNS = {
    "meta": (("singleton", "INTEGER"), ("schema_id", "VARCHAR"), ("schema_cid", "VARCHAR"), ("catalog_cid", "VARCHAR"), ("artifact_root", "VARCHAR")),
    "records": tuple((name, "VARCHAR") for name in ("projection_cid", "repository_id", "head_cid", "path", "verification_cid", "applicability_cid", "payload")),
    "entries": tuple((name, "VARCHAR") for name in ("entry_id", "projection_cid", "repository_id", "head_cid", "path", "contract_id", "contract_cid", "domain_id", "domain_cid", "keys_json", "dependencies_json")),
    "operations": tuple((name, "VARCHAR") for name in ("operation_id", "request_cid", "projection_cid")),
}
_AUTHORITY = {
    "historical_conditional_evidence": True, "kernel_checked": False,
    "source_runtime_semantics_verified": False, "behavioral_satisfaction": False,
    "authoritative_cache_eligible": False, "admission_authority": False,
    "completion_authority": False,
}


class CodebaseVerificationCatalogError(ValueError):
    """A projection, owner, selector or bounded persistent domain is invalid."""


class CodebaseVerificationOperationConflict(CodebaseVerificationCatalogError):
    """An operation identity already belongs to another exact request."""


@dataclass(frozen=True, slots=True)
class CodebaseVerificationCatalogLimits:
    max_records: int = 4096
    max_entries: int = 32768
    max_operations: int = 8192
    max_lookup_results: int = 16
    max_projection_bytes: int = 2 * 1024 * 1024
    max_evidence_bytes: int = 16 * 1024 * 1024
    max_result_bytes: int = 64 * 1024 * 1024
    max_query_page_size: int = 64
    max_query_keys: int = 131072
    max_query_dependencies: int = 262144
    max_query_inventory_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise CodebaseVerificationCatalogError(f"{name} must be a positive exact integer")


@dataclass(frozen=True, slots=True)
class CodebaseVerificationProjection:
    """Detached immutable refs; replay records retain their historical origin."""

    projection_cid: str
    _payload: bytes
    verification: CodebaseVerificationRecord
    applicability: Any = None

    def __post_init__(self) -> None:
        if type(self._payload) is not bytes or type(self.verification) is not CodebaseVerificationRecord:
            raise CodebaseVerificationCatalogError("projection requires immutable bytes and a native replay record")
        value = json.loads(self._payload)
        if (canonical_dag_json_bytes(value) != self._payload
                or cid_for_structured(value) != self.projection_cid
                or value.get("schema") != PROJECTION_SCHEMA
                or value.get("verification_cid") != self.verification.artifact_cid
                or self.verification.observed_live is not False
                or value.get("applicability_cid") != (None if self.applicability is None else self.applicability.artifact_cid)):
            raise CodebaseVerificationCatalogError("projection content or historical origin does not bind its refs")

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._payload)


def _text(value: Any, name: str, maximum: int = 512) -> str:
    if (type(value) is not str or not value or value != value.strip()
            or len(value.encode("utf-8")) > maximum or any(ord(char) < 32 for char in value)):
        raise CodebaseVerificationCatalogError(f"{name} must be a bounded nonempty string")
    return value


def _cid(value: Any) -> str:
    try:
        return validate_cid(value, codecs={"dag-json"})
    except (TypeError, ValueError) as exc:
        raise CodebaseVerificationCatalogError("expected a canonical structured CID") from exc


def _path(value: Any) -> str:
    _text(value, "path", 1024)
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts or not value.endswith(".py"):
        raise CodebaseVerificationCatalogError("path must be a canonical relative Python path")
    return value


def _request(head: CodebaseHead, verification_cid: str, applicability_cid: str | None) -> str:
    return cid_for_structured({"schema": REQUEST_SCHEMA, "head": head.to_dict(),
                               "verification_cid": verification_cid, "applicability_cid": applicability_cid})


class CodebaseVerificationCatalog:
    """Bounded exact projection on the native owner's serialized connection.

    Full heads deliberately prevent cross-generation reuse, including ABA and
    identical-snapshot republication. Old rows remain historical. Caps reject
    new writes rather than discarding operation replay protection. This owner
    does not hydrate evidence on startup and has no training/proving callbacks.
    """

    def __init__(self, index: RepositoryCodebaseIndex, *, limits: CodebaseVerificationCatalogLimits | None = None) -> None:
        import duckdb
        if (type(index) is not RepositoryCodebaseIndex or type(index.catalog) is not CodebaseCatalog
                or type(index.artifacts) is not ImmutableCAS or type(index.ingestor.store) is not DuckDBASTStore
                or index.catalog.store is not index.ingestor.store or index.catalog.artifacts is not index.artifacts
                or type(index.catalog.store._connection) is not duckdb.DuckDBPyConnection):
            raise CodebaseVerificationCatalogError("projection requires one exact durable native index/store/CAS owner")
        self.index, self.store, self.artifacts = index, index.catalog.store, index.artifacts
        self.limits = CodebaseVerificationCatalogLimits() if limits is None else limits
        if type(self.limits) is not CodebaseVerificationCatalogLimits:
            raise CodebaseVerificationCatalogError("limits must be native CodebaseVerificationCatalogLimits")
        self.limits = CodebaseVerificationCatalogLimits(**{name: getattr(self.limits, name) for name in self.limits.__dataclass_fields__})
        self._catalog, self._cx, self._pid = index.catalog, self.store._connection, os.getpid()
        with self.store._lock, self.store._transaction():
            self._ensure_owner()
            found = self._cx.execute("SELECT schema_name FROM information_schema.schemata WHERE catalog_name=current_database() AND schema_name=?", [_DOMAIN]).fetchall()
            if not found:
                for statement in _DDL:
                    self._cx.execute(statement)
                self._cx.execute(f"INSERT INTO {_DOMAIN}.meta VALUES (1, ?, ?, ?, ?)",
                                 [SCHEMA, cid_for_structured(list(_DDL)), self._catalog_identity(), str(self.artifacts.root.resolve())])
            self._check_schema()
            self._check_counts()
            from .codebase_verification_projection import VerificationProjectionStore
            self._queries = VerificationProjectionStore(self)

    def _ensure_owner(self) -> None:
        if (os.getpid() != self._pid or self.index.catalog is not self._catalog
                or self.index.ingestor.store is not self.store or self.index.artifacts is not self.artifacts
                or self.store._connection is not self._cx):
            raise CodebaseVerificationCatalogError("projection process/index/store/artifact owner changed")
        self._catalog._ensure_owner()

    def _catalog_identity(self) -> str:
        rows = self._cx.execute("SELECT table_name, sql FROM duckdb_tables() WHERE database_name=current_database() AND schema_name=? ORDER BY table_name", [_DOMAIN]).fetchall()
        return cid_for_structured([list(row) for row in rows])

    def _check_schema(self) -> None:
        tables = self._cx.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema=? LIMIT 5", [_DOMAIN]).fetchall()
        if set(tables) != {(name, "BASE TABLE") for name in _COLUMNS}:
            raise CodebaseVerificationCatalogError("foreign, incomplete or drifted verification schema")
        columns = self._cx.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_catalog=current_database() AND table_schema=? ORDER BY table_name, ordinal_position LIMIT 27", [_DOMAIN]).fetchall()
        expected = [(table, name, kind, "NO", None) for table, fields in sorted(_COLUMNS.items()) for name, kind in fields]
        if columns != expected:
            raise CodebaseVerificationCatalogError("verification schema columns changed")
        constraints = self._cx.execute("SELECT table_name, constraint_type, constraint_column_names, expression FROM duckdb_constraints() WHERE database_name=current_database() AND schema_name=? LIMIT 32", [_DOMAIN]).fetchall()
        actual = [(table, kind, tuple(names), expression) for table, kind, names, expression in constraints]
        expected_constraints = [(table, "NOT NULL", (name,), None) for table, fields in _COLUMNS.items() for name, _ in fields]
        expected_constraints += [(table, "PRIMARY KEY", (fields[0][0],), None) for table, fields in _COLUMNS.items()]
        expected_constraints += [("meta", "CHECK", ("singleton",), "(singleton = 1)")]
        if len(actual) != len(expected_constraints) or set(actual) != set(expected_constraints):
            raise CodebaseVerificationCatalogError("verification schema constraints changed")
        sizes = self._cx.execute(f"SELECT octet_length(encode(schema_id)) + octet_length(encode(schema_cid)) + octet_length(encode(catalog_cid)) + octet_length(encode(artifact_root)) FROM {_DOMAIN}.meta LIMIT 2").fetchall()
        if len(sizes) != 1 or sizes[0][0] is None or sizes[0][0] > 64 * 1024:
            raise CodebaseVerificationCatalogError("verification metadata exceeds its bound")
        rows = self._cx.execute(f"SELECT singleton, schema_id, schema_cid, catalog_cid, artifact_root FROM {_DOMAIN}.meta LIMIT 2").fetchall()
        if rows != [(1, SCHEMA, cid_for_structured(list(_DDL)), self._catalog_identity(), str(self.artifacts.root.resolve()))]:
            raise CodebaseVerificationCatalogError("verification schema/artifact binding changed")

    def _check_counts(self) -> tuple[int, int, int]:
        counts = self._cx.execute(f"SELECT (SELECT count(*) FROM {_DOMAIN}.records), (SELECT count(*) FROM {_DOMAIN}.entries), (SELECT count(*) FROM {_DOMAIN}.operations)").fetchone()
        if any(count > maximum for count, maximum in zip(counts, (self.limits.max_records, self.limits.max_entries, self.limits.max_operations))):
            raise CodebaseVerificationCatalogError("verification domain exceeds configured row bounds")
        return counts

    def _bounded_artifact(self, cid: str, maximum: int) -> dict[str, Any]:
        _cid(cid)
        cap = min(maximum, self.artifacts.max_object_bytes)
        try:
            with self.artifacts.path_for(cid).open("rb") as stream:
                raw = stream.read(cap + 1)
            if len(raw) > cap:
                raise CodebaseVerificationCatalogError("referenced immutable artifact exceeds its byte bound")
            value = json.loads(raw)
            if canonical_dag_json_bytes(value) != raw or cid_for_structured(value) != cid:
                raise CodebaseVerificationCatalogError("referenced immutable artifact identity changed")
            return value
        except (OSError, TypeError, ValueError, RecursionError) as exc:
            raise CodebaseVerificationCatalogError("required bounded immutable artifact is unavailable or malformed") from exc

    def _derive(self, verification_cid: str, applicability_cid: str | None) -> CodebaseVerificationProjection:
        self._bounded_artifact(verification_cid, self.limits.max_evidence_bytes)
        verification = load_codebase_verification(self.index, verification_cid)
        payload = verification.to_dict()
        source = payload["source_binding"]
        head = CodebaseHead.from_dict(source["head"])
        common = {"head_cid": cid_for_structured(head.to_dict()), "manifest_cid": head.manifest_cid,
            "snapshot_cid": head.snapshot_cid, "ast_revision_id": head.ast_revision_id,
            "source_cid": source["entry"]["source_cid"], "ast_cid": source["ast_cid"],
            "content_sha256": source["content_sha256"], "source_revision": source["source_revision"],
            "profile": payload["profile"], "environment": payload["environment"],
            "environment_cid": cid_for_structured(payload["environment"]),
            "pipeline_cid": cid_for_structured(payload["pipeline"]),
            "effective_bounds": payload["effective_bounds"], "verification_cid": verification_cid}
        lowered = {item["contract_id"]: item for item in payload["pipeline_result"]["contracts"]}
        contracts = []
        for requested in payload["requested_contracts"]:
            contract_id = requested["contract_id"]
            keys = []
            for item, key in zip(payload["pipeline_result"]["obligation_results"], payload["canonical_keys"]):
                if item["vc_obligation"]["parent_contract_id"] == contract_id:
                    native_key = CanonicalProofCacheKey.from_dict(key)
                    if canonical_dag_json_bytes(key) != canonical_dag_json_bytes(native_key.to_dict()):
                        raise CodebaseVerificationCatalogError("noncanonical native proof key")
                    keys.append({"key_id": native_key.key_id, "key": native_key.to_dict(),
                                 "obligation_id": item["vc_obligation"]["obligation_id"]})
            contracts.append({"contract_id": contract_id, "requested_contract": requested,
                "contract_cid": cid_for_structured(requested),
                "lowered_contract_cid": None if contract_id not in lowered else cid_for_structured(lowered[contract_id]),
                "domain_id": None, "domain_cid": None, "canonical_keys": keys,
                "applicability_keys": []})
        applicability = None
        if applicability_cid is not None:
            self._bounded_artifact(applicability_cid, self.limits.max_evidence_bytes)
            from ipfs_datasets_py.logic.software_contracts.codebase_applicability import load_codebase_applicability
            applicability = load_codebase_applicability(self.index, applicability_cid)
            app = applicability.to_dict()
            if (app["verification_cid"] != verification_cid
                    or canonical_dag_json_bytes(app["source_binding"]) != canonical_dag_json_bytes(source)
                    or applicability.observed_live is not False):
                raise CodebaseVerificationCatalogError("applicability does not bind this exact verification/source")
            by_contract = {item["parent_contract_id"]: item for item in app["contract_results"]}
            if len(by_contract) != len(app["contract_results"]) or set(by_contract) != set(lowered):
                raise CodebaseVerificationCatalogError("applicability contract inventory differs")
            for contract in contracts:
                item = by_contract[contract["contract_id"]]
                if (item["contract_cid"] != contract["lowered_contract_cid"]
                        or item["function_name"] != contract["requested_contract"]["function_name"]):
                    raise CodebaseVerificationCatalogError("applicability lowered contract identity differs")
                contract.update(domain_id=item["domain_id"], domain_cid=item["domain_cid"])
                for check, key in zip(app["checks"], app["canonical_keys"]):
                    if check["parent_contract_id"] == contract["contract_id"]:
                        native_key = CanonicalProofCacheKey.from_dict(key)
                        if canonical_dag_json_bytes(key) != canonical_dag_json_bytes(native_key.to_dict()):
                            raise CodebaseVerificationCatalogError("noncanonical applicability proof key")
                        contract["applicability_keys"].append({"key_id": native_key.key_id,
                            "key": native_key.to_dict(), "kind": check["kind"],
                            "obligation_id": check["obligation"]["smt_obligation"]["obligation_id"]})
            common["applicability_cid"] = applicability_cid
            common["requested_domains"] = app["requested_domains"]
            common["applicability_environment"] = app["environment"]
            common["applicability_profile"] = app["profile"]
            common["applicability_bounds"] = app["effective_bounds"]
        value = {"schema": PROJECTION_SCHEMA, "authority": dict(_AUTHORITY),
            "requires_current_source_observation": True, "head": head.to_dict(), "path": source["path"],
            "source_binding": source, "verification_cid": verification_cid,
            "applicability_cid": applicability_cid, "contracts": contracts, "dependencies": common}
        encoded = canonical_dag_json_bytes(value)
        if len(encoded) > self.limits.max_projection_bytes:
            raise CodebaseVerificationCatalogError("projection exceeds its byte bound")
        self._bounded_artifact(verification_cid, self.limits.max_evidence_bytes)
        if applicability_cid is not None:
            self._bounded_artifact(applicability_cid, self.limits.max_evidence_bytes)
        return CodebaseVerificationProjection(cid_for_structured(value), encoded, verification, applicability)

    @staticmethod
    def _entry_rows(projection: CodebaseVerificationProjection) -> list[tuple[Any, ...]]:
        value = projection.to_dict()
        head = value["head"]
        dependencies = canonical_dag_json_bytes(value["dependencies"]).decode("utf-8")
        rows = []
        for item in value["contracts"]:
            identity = cid_for_structured({"projection_cid": projection.projection_cid, "contract_id": item["contract_id"]})
            rows.append((identity, projection.projection_cid, head["repository_id"], cid_for_structured(head),
                value["path"], item["contract_id"], item["contract_cid"], item["domain_id"] or "", item["domain_cid"] or "",
                canonical_dag_json_bytes(item["canonical_keys"] + item["applicability_keys"]).decode("utf-8"), dependencies))
        return rows

    def _operation(self, operation_id: str) -> tuple[str, str] | None:
        sizes = self._cx.execute(f"SELECT octet_length(encode(operation_id)) + octet_length(encode(request_cid)) + octet_length(encode(projection_cid)) FROM {_DOMAIN}.operations WHERE operation_id=? LIMIT 2", [operation_id]).fetchall()
        if len(sizes) > 1 or any(item[0] is None or item[0] > 4096 for item in sizes):
            raise CodebaseVerificationCatalogError("stored operation exceeds its bound or is ambiguous")
        rows = self._cx.execute(f"SELECT request_cid, projection_cid FROM {_DOMAIN}.operations WHERE operation_id=? LIMIT 2", [operation_id]).fetchall()
        if not rows:
            return None
        return _cid(rows[0][0]), _cid(rows[0][1])

    def _read(self, projection_cid: str) -> CodebaseVerificationProjection:
        sizes = self._cx.execute(f"SELECT octet_length(encode(payload)), octet_length(encode(projection_cid)) + octet_length(encode(repository_id)) + octet_length(encode(head_cid)) + octet_length(encode(path)) + octet_length(encode(verification_cid)) + octet_length(encode(applicability_cid)) FROM {_DOMAIN}.records WHERE projection_cid=? LIMIT 2", [projection_cid]).fetchall()
        if (len(sizes) != 1 or sizes[0][0] is None or not 0 < sizes[0][0] <= self.limits.max_projection_bytes
                or sizes[0][1] is None or sizes[0][1] > 4096):
            raise CodebaseVerificationCatalogError("stored projection is missing, ambiguous or oversized")
        row = self._cx.execute(f"SELECT projection_cid, repository_id, head_cid, path, verification_cid, applicability_cid, payload FROM {_DOMAIN}.records WHERE projection_cid=? LIMIT 2", [projection_cid]).fetchone()
        sealed = self._bounded_artifact(projection_cid, self.limits.max_projection_bytes)
        projection = self._derive(row[4], row[5] or None)
        value = projection.to_dict()
        expected = (projection.projection_cid, value["head"]["repository_id"], cid_for_structured(value["head"]),
                    value["path"], value["verification_cid"], value["applicability_cid"] or "", projection._payload.decode("utf-8"))
        if row != expected or canonical_dag_json_bytes(sealed) != projection._payload:
            raise CodebaseVerificationCatalogError("stored projection/ref payload does not recompute from native artifacts")
        expected_rows = self._entry_rows(projection)
        lengths = self._cx.execute(f"SELECT octet_length(encode(keys_json)) + octet_length(encode(dependencies_json)) + octet_length(encode(entry_id)) + octet_length(encode(projection_cid)) + octet_length(encode(repository_id)) + octet_length(encode(head_cid)) + octet_length(encode(path)) + octet_length(encode(contract_id)) + octet_length(encode(contract_cid)) + octet_length(encode(domain_id)) + octet_length(encode(domain_cid)) FROM {_DOMAIN}.entries WHERE projection_cid=? LIMIT ?", [projection_cid, len(expected_rows) + 1]).fetchall()
        if len(lengths) != len(expected_rows) or any(item[0] is None or item[0] > 2 * self.limits.max_projection_bytes for item in lengths):
            raise CodebaseVerificationCatalogError("stored entry inventory is missing, oversized or ambiguous")
        actual = self._cx.execute(f"SELECT entry_id, projection_cid, repository_id, head_cid, path, contract_id, contract_cid, domain_id, domain_cid, keys_json, dependencies_json FROM {_DOMAIN}.entries WHERE projection_cid=? LIMIT ?", [projection_cid, len(expected_rows) + 1]).fetchall()
        if sorted(actual) != sorted(expected_rows):
            raise CodebaseVerificationCatalogError("stored keys/dependencies/contract selectors differ from native projection")
        operation_sizes = self._cx.execute(f"SELECT octet_length(encode(operation_id)) + octet_length(encode(request_cid)) + octet_length(encode(projection_cid)) FROM {_DOMAIN}.operations WHERE projection_cid=? LIMIT ?", [projection_cid, self.limits.max_operations + 1]).fetchall()
        if (not operation_sizes or len(operation_sizes) > self.limits.max_operations
                or any(item[0] is None or item[0] > 4096 for item in operation_sizes)):
            raise CodebaseVerificationCatalogError("stored projection has missing or malformed operation links")
        operations = self._cx.execute(f"SELECT operation_id, request_cid FROM {_DOMAIN}.operations WHERE projection_cid=? LIMIT ?", [projection_cid, self.limits.max_operations + 1]).fetchall()
        request = _request(CodebaseHead.from_dict(value["head"]), value["verification_cid"], value["applicability_cid"])
        if any(_text(operation, "operation_id", 256) != operation or identity != request for operation, identity in operations):
            raise CodebaseVerificationCatalogError("stored projection operation request does not recompute")
        return projection

    @contextmanager
    def _resources(self, repository: str | Path, head: CodebaseHead, *, scheduler: Any,
                   parent_lease: Any, cancel_event: Any, admission_timeout_seconds: float,
                   timeout_seconds: float, memory_mb: int) -> Iterator[Any]:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
        if type(head) is not CodebaseHead:
            raise CodebaseVerificationCatalogError("expected_head must be an exact native CodebaseHead")
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise CodebaseVerificationCatalogError("timeout_seconds must be finite and positive")
        if (type(admission_timeout_seconds) not in {int, float} or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0):
            raise CodebaseVerificationCatalogError("admission timeout must be finite and nonnegative")
        if type(memory_mb) is not int or memory_mb <= 0:
            raise CodebaseVerificationCatalogError("memory_mb must be a positive exact integer")
        if max(self.limits.max_projection_bytes, self.limits.max_evidence_bytes) > min(self.artifacts.max_object_bytes, memory_mb * 1024 * 1024 // 8):
            raise CodebaseVerificationCatalogError("projection/evidence bounds exceed the CAS/admission envelope")
        if max(self.limits.max_result_bytes, self.limits.max_query_inventory_bytes) > memory_mb * 1024 * 1024 // 8:
            raise CodebaseVerificationCatalogError("aggregate result bound exceeds admission envelope")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)

            def checkpoint() -> None:
                if cancelled.is_set():
                    raise LeaseCancelledError("verification projection cancelled")
                if time.monotonic() >= deadline:
                    raise LeaseTimeoutError("verification projection deadline exceeded")
                self._ensure_owner()

            def observe() -> None:
                checkpoint()
                self.index.observe_current(repository, expected_head=head, parent_lease=lease,
                    cancel_event=cancelled, memory_mb=memory_mb,
                    admission_timeout_seconds=min(admission_timeout_seconds, deadline - time.monotonic()),
                    timeout_seconds=deadline - time.monotonic())
                checkpoint()

            observe()
            yield checkpoint, observe
            observe()

    def publish(self, repository: str | Path, *, expected_head: CodebaseHead,
                verification_cid: str, operation_id: str, applicability_cid: str | None = None,
                scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
                admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
                memory_mb: int = 512) -> CodebaseVerificationProjection:
        """Project native CAS refs atomically under an exact structural head.

        Replay uses the same current-source boundary as a new write. Racing
        edits can leave historical rows, but cannot return a current result.
        There is no caller-provided verdict, status, checker or loader callback.
        """
        _text(operation_id, "operation_id", 256)
        _cid(verification_cid)
        if applicability_cid is not None:
            _cid(applicability_cid)
        with self._resources(repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
                timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (checkpoint, observe):
            projection = self._derive(verification_cid, applicability_cid)
            value = projection.to_dict()
            if canonical_dag_json_bytes(value["head"]) != canonical_dag_json_bytes(expected_head.to_dict()):
                raise StaleCodebaseError("verification artifact belongs to another complete head")
            request_cid = _request(expected_head, verification_cid, applicability_cid)
            # The CAS sidecar is published before SQL; rollback may leave only
            # an inert historical object, never a partial SQL projection.
            if self.artifacts.put(value) != projection.projection_cid:
                raise CodebaseVerificationCatalogError("CAS publication returned another projection identity")
            if canonical_dag_json_bytes(self._bounded_artifact(projection.projection_cid, self.limits.max_projection_bytes)) != projection._payload:
                raise CodebaseVerificationCatalogError("sealed projection does not bind the derived payload")
            observe()
            with self.store._lock, self.store._transaction():
                checkpoint()
                self._check_schema()
                self._catalog._check_schema()
                if self._catalog._current(expected_head.repository_id) != expected_head:
                    raise StaleCodebaseError("structural head changed before projection commit")
                self._guard_head(expected_head)
                self._queries.validate_inventory(expected_head=expected_head, checkpoint=checkpoint, initialize_empty=True)
                previous = self._operation(operation_id)
                if previous is not None:
                    if previous != (request_cid, projection.projection_cid):
                        raise CodebaseVerificationOperationConflict("operation_id already names another exact projection request")
                    projection = self._read(previous[1])
                else:
                    counts = self._check_counts()
                    existing = self._cx.execute(f"SELECT projection_cid FROM {_DOMAIN}.records WHERE projection_cid=? LIMIT 2", [projection.projection_cid]).fetchall()
                    entry_rows = self._entry_rows(projection)
                    if (counts[2] >= self.limits.max_operations or (not existing and (
                            counts[0] >= self.limits.max_records or counts[1] + len(entry_rows) > self.limits.max_entries))):
                        raise CodebaseVerificationCatalogError("publication would exceed row bounds")
                    if existing:
                        projection = self._read(projection.projection_cid)
                    else:
                        self._cx.execute(f"INSERT INTO {_DOMAIN}.records VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [projection.projection_cid, expected_head.repository_id, cid_for_structured(expected_head.to_dict()),
                             value["path"], verification_cid, applicability_cid or "", projection._payload.decode("utf-8")])
                        for row in entry_rows:
                            checkpoint()
                            self._cx.execute(f"INSERT INTO {_DOMAIN}.entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(row))
                    self._cx.execute(f"INSERT INTO {_DOMAIN}.operations VALUES (?, ?, ?)", [operation_id, request_cid, projection.projection_cid])
                self._queries.synchronize(expected_head=expected_head, checkpoint=checkpoint)
                checkpoint()
            return projection

    def _guard_head(self, head: CodebaseHead) -> None:
        """Take a real DuckDB write-conflict guard without publishing a head.

        A no-op UPDATE is optimized away. Adjacent sign-flip/restore writes
        remain transaction-local; no callback or read can see the transient
        value. A competing native publisher conflicts, and rollback restores it.
        """
        self._cx.execute("UPDATE codebase_control.heads SET generation=-generation WHERE repository_id=?", [head.repository_id])
        self._cx.execute("UPDATE codebase_control.heads SET generation=? WHERE repository_id=?", [head.generation, head.repository_id])

    def rebuild_current(self, repository: str | Path, *, expected_head: CodebaseHead,
                        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
                        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
                        memory_mb: int = 512):
        """Explicit, atomic bounded backfill from native historical projections.

        Startup and queries never silently repair existing evidence. Rebuilding
        increments the evidence epoch even if the final inventory is identical,
        invalidating older cursors without changing the structural source head.
        """
        with self._resources(repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
                timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (checkpoint, observe):
            with self.store._lock, self.store._transaction():
                checkpoint()
                self._check_schema()
                self._check_counts()
                self._catalog._check_schema()
                if self._catalog._current(expected_head.repository_id) != expected_head:
                    raise StaleCodebaseError("structural head changed before normalized rebuild")
                self._guard_head(expected_head)
                retained = 0
                for identity in self._queries.source_ids(expected_head):
                    checkpoint()
                    projection = self._read(identity)
                    retained += len(projection._payload)
                    if retained > self.limits.max_query_inventory_bytes:
                        raise CodebaseVerificationCatalogError("rebuild artifact inventory exceeds its byte bound")
                inventory = self._queries.synchronize(expected_head=expected_head, checkpoint=checkpoint, rebuild=True)
                self._queries.validate_inventory(expected_head=expected_head, checkpoint=checkpoint)
                checkpoint()
            return inventory

    def query_current(self, repository: str | Path, *, expected_head: CodebaseHead, selector,
                      page_size: int = 16, cursor=None, scheduler: Any = None,
                      parent_lease: Any = None, cancel_event: Any = None,
                      admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
                      memory_mb: int = 512):
        """Return an exact page bound to current source and sealed evidence.

        A full bounded normalized inventory check prevents false absence caused
        by omitted keys/dependencies. Selected native artifacts are then replayed
        without solver launches. These historical observations grant no new
        proof, behavior, cache-admission or completion authority.
        """
        from .codebase_verification_queries import (CodebaseVerificationSelector,
            CodebaseVerificationQueryCursor, CodebaseVerificationQueryEntry, CodebaseVerificationQueryPage)
        if type(selector) is not CodebaseVerificationSelector:
            raise CodebaseVerificationCatalogError("query requires a native exact selector")
        selector = CodebaseVerificationSelector.from_dict(selector.to_dict())
        if type(page_size) is not int or not 1 <= page_size <= self.limits.max_query_page_size:
            raise CodebaseVerificationCatalogError("query page size exceeds its bounded positive limit")
        if cursor is not None:
            if type(cursor) is not CodebaseVerificationQueryCursor:
                raise CodebaseVerificationCatalogError("query cursor must be a native exact continuation")
            cursor = CodebaseVerificationQueryCursor.from_dict(cursor.to_dict())
        with self._resources(repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
                timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (checkpoint, observe):
            with self.store._lock, self.store._transaction():
                checkpoint()
                self._check_schema()
                self._check_counts()
                self._catalog._check_schema()
                if self._catalog._current(expected_head.repository_id) != expected_head:
                    raise StaleCodebaseError("structural head changed during normalized query")
                # Only an actually empty head can acquire its first inventory
                # during a read. Existing legacy evidence requires explicit rebuild.
                if self._queries._state(expected_head) is None and not self._queries.source_ids(expected_head):
                    self._guard_head(expected_head)
                inventory = self._queries.validate_inventory(expected_head=expected_head,
                    checkpoint=checkpoint, initialize_empty=True)
                if cursor is not None:
                    if (cursor.head_cid != inventory.head_cid or cursor.inventory_cid != inventory.inventory_cid
                            or cursor.epoch != inventory.epoch or cursor.selector_cid != selector.cid):
                        raise CodebaseVerificationCatalogError("query cursor belongs to another head, selector or evidence inventory")
                    if not self._queries.select_entries(selector.to_dict(), inventory=inventory,
                            exact_entry=cursor.after, limit=1):
                        raise CodebaseVerificationCatalogError("query cursor does not name a matching inventory entry")
                selected = self._queries.select_entries(selector.to_dict(), inventory=inventory,
                    after=None if cursor is None else cursor.after, limit=page_size + 1)
                entries, retained_bytes, replayed = [], 0, {}
                for entry_id, projection_cid, contract_id in selected[:page_size]:
                    checkpoint()
                    projection = replayed.get(projection_cid)
                    if projection is None:
                        projection = self._read(projection_cid)
                        retained_bytes += len(projection._payload) + len(projection.verification._payload)
                        if projection.applicability is not None:
                            retained_bytes += len(projection.applicability._payload)
                        if retained_bytes > self.limits.max_result_bytes:
                            raise CodebaseVerificationCatalogError("aggregate exact results exceed their byte bound")
                        replayed[projection_cid] = projection
                    entries.append(CodebaseVerificationQueryEntry(entry_id, contract_id, projection))
                continuation = None
                if len(selected) > page_size:
                    continuation = CodebaseVerificationQueryCursor(inventory.head_cid, inventory.inventory_cid,
                        inventory.epoch, selector.cid, entries[-1].entry_id)
                page = CodebaseVerificationQueryPage(selector, expected_head, inventory.inventory_cid,
                    inventory.epoch, tuple(entries), continuation, start_cursor=cursor)
                checkpoint()
            return page

    def lookup_current(self, repository: str | Path, *, expected_head: CodebaseHead,
                       path: str, contract_id: str, verification_cid: str | None = None,
                       expected_contract_cid: str | None = None, expected_key_id: str | None = None,
                       domain_id: str | None = None, expected_domain_cid: str | None = None, limit: int = 16,
                       scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
                       admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
                       memory_mb: int = 512) -> tuple[CodebaseVerificationProjection, ...]:
        """Compatibility exact lookup, now backed by normalized query rows."""
        from .codebase_verification_queries import CodebaseVerificationSelector
        if type(limit) is not int or not 1 <= limit <= self.limits.max_lookup_results:
            raise CodebaseVerificationCatalogError("lookup limit must be a bounded positive exact integer")
        selector = CodebaseVerificationSelector(path=path, contract_id=contract_id,
            verification_cid=verification_cid, expected_contract_cid=expected_contract_cid,
            canonical_key_id=expected_key_id, requested_domain_id=domain_id,
            requested_domain_cid=expected_domain_cid)
        page = self.query_current(repository, expected_head=expected_head, selector=selector,
            page_size=min(limit + 1, self.limits.max_query_page_size), scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb)
        if not page.complete or len(page.entries) > limit:
            raise CodebaseVerificationCatalogError("exact selector exceeds requested result limit")
        return tuple(entry.projection for entry in page.entries)


__all__ = ["CodebaseVerificationCatalog", "CodebaseVerificationCatalogLimits",
           "CodebaseVerificationCatalogError", "CodebaseVerificationOperationConflict",
           "CodebaseVerificationProjection", "PROJECTION_SCHEMA"]
