"""Descriptor-only commands for one owner's verified source corpus catalog.

Remote registration only reserves durable metadata. The explicit local owner
calls execute_pending to verify/copy/materialize packages. Read commands expose
historical catalog evidence, never a proof or a current package verification.
No SQL, filesystem path, listener, model or execution policy comes from a client.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import re
import threading

from . import source_corpus_catalog as catalog_module

SCHEMA = "source-corpus-control-result-v1"
COMMANDS = frozenset({"RegisterSourceExport", "ResolveSourceExport", "ReadSourceVersion", "ReadSourceRows"})
MAX_BINDINGS = 64
MAX_VERSION_IDS = 64
MAX_READ_ROWS = 64
MAX_RESULT_BYTES = 96 * 1024
MAX_DRAIN_OPERATIONS = 64
_VERSION = re.compile(r"^sha256:[0-9a-f]{64}$")
_FLAGS = {"admitted": False, "formalized": False}


class SourceCorpusControlError(ValueError):
    """A fixed, path-free error suitable for an authenticated command reply."""


def _require(condition, code):
    if not condition:
        raise SourceCorpusControlError(code)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _copy(value):
    return json.loads(_json(value))


def _token(value):
    _require(type(value) is str and catalog_module._TOKEN.fullmatch(value) is not None,
             "invalid_identifier")
    return value


def _version_id(value):
    _require(type(value) is str and _VERSION.fullmatch(value) is not None, "invalid_version_id")
    return value


def _binding(value):
    try:
        return catalog_module._payload(value)
    except (ValueError, TypeError, KeyError):
        raise SourceCorpusControlError("invalid_source_binding") from None


def _bounded(value):
    encoded = _json(value)
    _require(len(encoded.encode("utf-8")) <= MAX_RESULT_BYTES, "result_too_large")
    return json.loads(encoded)


@dataclass(frozen=True, init=False)
class SourceCorpusScope:
    """Exact declared dataset/manifest pairs, plus explicit immutable read IDs.

    Labels are owner declarations, not language detection or source authority.
    Derived version IDs are readable automatically. A caller cannot combine a
    dataset from one binding with the manifest from another binding.
    """
    principal_id: str
    _bindings: tuple[str, ...]
    version_ids: frozenset[str]
    readable_version_ids: frozenset[str]

    def __init__(self, principal_id, *, bindings=(), version_ids=()):
        principal_id = _token(principal_id)
        _require(type(bindings) in (tuple, list) and len(bindings) <= MAX_BINDINGS,
                 "invalid_binding_scope")
        _require(type(version_ids) in (tuple, list, set, frozenset) and len(version_ids) <= MAX_VERSION_IDS,
                 "invalid_version_scope")
        encoded = tuple(_json(_binding(item)) for item in bindings)
        _require(len(set(encoded)) == len(encoded), "duplicate_source_binding")
        versions = frozenset(_version_id(item) for item in version_ids)
        _require(len(versions) == len(version_ids), "duplicate_version_id")
        _require(bool(encoded or versions), "empty_source_scope")
        derived = frozenset(catalog_module._identities(json.loads(item))[2] for item in encoded)
        object.__setattr__(self, "principal_id", principal_id)
        object.__setattr__(self, "_bindings", encoded)
        object.__setattr__(self, "version_ids", versions)
        object.__setattr__(self, "readable_version_ids", versions | derived)

    @property
    def bindings(self):
        return tuple(json.loads(item) for item in self._bindings)


class SourceCorpusControl:
    """Bounded command dispatcher; heavy execution is an explicit owner action.

    Operation IDs are namespaced by principal: source-control:<principal SHA>:
    <client-operation SHA>. The outer reply keeps the caller ID; nested catalog
    status and receipts retain this durable ID. Restart with the same principal
    preserves idempotency; a different principal has a distinct operation.

    Busy returns are nonblocking on the actual catalog owner lock, including
    imports/verification performed directly on the catalog outside this object.
    Closing this controller does not close its catalog. No background drain is
    started. Failed imports remain pending for a later explicit owner attempt.
    """
    def __init__(self, catalog, scope, *, package_resolver):
        _require(type(catalog) is catalog_module.SourceCorpusCatalog, "invalid_catalog_owner")
        _require(type(scope) is SourceCorpusScope and callable(package_resolver), "invalid_control_configuration")
        self._catalog = catalog
        self._scope = SourceCorpusScope(scope.principal_id, bindings=scope.bindings,
                                        version_ids=scope.version_ids)
        self._resolver = package_resolver
        self._prefix = "source-control:" + hashlib.sha256(scope.principal_id.encode("utf-8")).hexdigest() + ":"
        self._bindings = frozenset(self._scope._bindings)
        self._pid = os.getpid()
        self._closed = False
        self._draining = False
        self._lock = threading.RLock()

    @property
    def catalog(self):
        return self._catalog

    @property
    def scope(self):
        return self._scope

    def _ensure_open(self):
        _require(os.getpid() == self._pid and not self._closed, "control_unavailable")

    @contextmanager
    def _access(self):
        self._ensure_open()
        acquired = self._lock.acquire(blocking=False)
        try:
            if not acquired:
                yield False
                return
            self._ensure_open()
            if self._draining:
                yield False
                return
            with self.catalog.try_owner_access() as owned:
                yield owned
        finally:
            if acquired:
                self._lock.release()

    def close(self):
        acquired = self._lock.acquire(blocking=False)
        _require(acquired, "control_busy")
        try:
            _require(os.getpid() == self._pid and not self._draining, "control_busy")
            self._closed = True
        finally:
            self._lock.release()

    def _authorize(self, command, payload):
        if command in {"RegisterSourceExport", "ResolveSourceExport"}:
            binding = _binding(payload)
            _require(_json(binding) in self._bindings, "source_binding_out_of_scope")
            return binding
        keys = {"version_id"} if command == "ReadSourceVersion" else {"version_id", "after_ordinal", "limit"}
        _require(type(payload) is dict and set(payload) == keys, "invalid_read_payload")
        version = _version_id(payload["version_id"])
        _require(version in self.scope.readable_version_ids, "version_out_of_scope")
        if command == "ReadSourceRows":
            _require(type(payload["after_ordinal"]) is int and -1 <= payload["after_ordinal"] < 2**63,
                     "invalid_row_cursor")
            _require(type(payload["limit"]) is int and 1 <= payload["limit"] <= MAX_READ_ROWS,
                     "invalid_row_limit")
        return dict(payload)

    def _operation_id(self, operation_id):
        return self._prefix + hashlib.sha256(operation_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _envelope(command, operation_id, result=None, *, busy=False):
        return {"schema_version": SCHEMA, "command": command, "operation_id": operation_id,
                "status": "busy" if busy else "ok", "result": result, **_FLAGS}

    def _status(self, value, durable_id, binding):
        _require(type(value) is dict and set(value) == {"schema_version", "operation_id", "state", "receipt", "admitted", "formalized"}
                 and value["schema_version"] == "source-corpus-operation-status-v1"
                 and value["operation_id"] == durable_id and value["state"] in {"unknown", "pending", "completed"}
                 and value["admitted"] is False and value["formalized"] is False, "invalid_catalog_status")
        receipt = value["receipt"]
        if value["state"] == "completed":
            dataset_id, release_id, version_id = catalog_module._identities(binding)
            _require(type(receipt) is dict and receipt.get("operation_id") == durable_id
                     and receipt.get("dataset_id") == dataset_id and receipt.get("release_id") == release_id
                     and receipt.get("version_id") == version_id
                     and _json(receipt.get("package_manifest_artifact")) == _json(binding["package_manifest_artifact"])
                     and receipt.get("admitted") is False and receipt.get("formalized") is False,
                     "invalid_catalog_status")
        else:
            _require(receipt is None, "invalid_catalog_status")
        return _copy(value)

    def _read_version(self, payload):
        version = self.catalog.get_version(payload["version_id"])
        fields = {"schema_version", "version_id", "dataset_id", "dataset", "release_id", "package_manifest_artifact",
                  "package_directory", "row_count", "row_digest", "qualification"}
        _require(type(version) is dict and set(version) == fields
                 and version["version_id"] == payload["version_id"], "invalid_catalog_version")
        return {key: value for key, value in version.items() if key != "package_directory"}

    def dispatch(self, command, operation_id, payload):
        """Reserve/read only. All failures are fixed codes without private paths."""
        try:
            _require(type(command) is str and command in COMMANDS, "unsupported_source_command")
            operation_id = _token(operation_id)
            payload = self._authorize(command, payload)
            with self._access() as acquired:
                if not acquired:
                    return _bounded(self._envelope(command, operation_id, busy=True))
                if command in {"RegisterSourceExport", "ResolveSourceExport"}:
                    durable_id = self._operation_id(operation_id)
                    method = (self.catalog.reserve_registration if command == "RegisterSourceExport"
                              else self.catalog.registration_status)
                    result = self._status(method(durable_id, payload), durable_id, payload)
                elif command == "ReadSourceVersion":
                    result = self._read_version(payload)
                else:
                    # Budget the full outer result, not just the catalog rows list.
                    worst = {"version_id": payload["version_id"], "rows": [], "next_after_ordinal": 2**63 - 1,
                             "complete": False, "row_count": MAX_READ_ROWS}
                    overhead = len(_json(self._envelope(command, operation_id, worst)).encode("utf-8")) - 2
                    budget = min(self.catalog.limits.max_read_bytes, MAX_RESULT_BYTES - overhead)
                    result = self.catalog.read_rows(payload["version_id"], payload["after_ordinal"],
                                                    payload["limit"], max_bytes=budget)
                return _bounded(self._envelope(command, operation_id, result))
        except SourceCorpusControlError:
            raise
        except catalog_module.SourceCorpusCatalogError as exc:
            if str(exc) == "first row exceeds page byte bound":
                raise SourceCorpusControlError("source_row_too_large") from None
            raise SourceCorpusControlError("catalog_operation_failed") from None
        except Exception:
            raise SourceCorpusControlError("catalog_operation_failed") from None

    def execute_pending(self, max_operations=1):
        """Explicit owner work, at most one attempt per selected pending intent.

        A single bounded scan reads at most 64 intents for this principal. Exact
        binding filtering also protects a narrowed scope. scan_limit_reached
        means this call makes no claim to have enumerated all pending intents.
        Errors retain pending state; a later explicit drain may resume the exact
        operation using the catalog's durable batch checkpoints. This is source
        materialization only, never model training or formalization.
        """
        try:
            _require(type(max_operations) is int and 1 <= max_operations <= MAX_DRAIN_OPERATIONS,
                     "invalid_drain_bound")
            with self._access() as acquired:
                if not acquired:
                    return {"schema_version": "source-corpus-drain-v1", "status": "busy", "operations": [],
                            "scanned_count": 0, "scan_limit_reached": False, **_FLAGS}
                self._draining = True
                try:
                    pending = self.catalog.pending_registrations(64, operation_prefix=self._prefix)
                    results = []
                    for item in pending:
                        operation_id = item["operation_id"]
                        binding = _binding(item["payload"])
                        if (not operation_id.startswith(self._prefix) or len(operation_id) != len(self._prefix) + 64
                                or re.fullmatch(r"[0-9a-f]{64}", operation_id[len(self._prefix):]) is None
                                or _json(binding) not in self._bindings):
                            continue
                        error = None
                        try:
                            self.catalog.register_export(operation_id, **binding, package_resolver=self._resolver)
                        except Exception:
                            error = "catalog_operation_failed"
                        # Resolve lost replies without repeating the import in this call.
                        status = self._status(self.catalog.registration_status(operation_id, binding), operation_id, binding)
                        results.append({"operation": status, "error": None if status["state"] == "completed" else error})
                        if len(results) == max_operations:
                            break
                    return _bounded({"schema_version": "source-corpus-drain-v1", "status": "finished",
                                     "operations": results, "scanned_count": len(pending),
                                     "scan_limit_reached": len(pending) == 64, **_FLAGS})
                finally:
                    self._draining = False
        except SourceCorpusControlError:
            raise
        except Exception:
            raise SourceCorpusControlError("catalog_operation_failed") from None
