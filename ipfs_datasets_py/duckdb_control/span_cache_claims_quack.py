"""Fenced span work over the existing private, queued Quack transport.

The existing native SpanCache remains the only catalog writer. A gateway
serves one owner-issued worker scope and queues worker commands onto that
cache's original owner thread. Its transient Quack inbox never attaches the
private catalog. Use a separate gateway/token per worker backed by the same
owner; workers receive connection_parameters(), never a catalog path. Its
reply table is visible to holders of that endpoint bearer. Separate endpoints
reduce accidental cross-worker scope, but this is not a confidentiality claim.

This is an explicit loopback prototype, preserving the existing transport's
bearer authentication and exact SQL allowlist. It is not a distributed
capability broker, DuckLake production activation, or semantic qualification.
Timeout/error replies can follow a committed mutation: resolve the original
operation ID and exact payload before retrying. Oversized source replies are
refused rather than truncated or reclassified as shorter spans.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import queue
import threading
from typing import Any, Mapping
import uuid

from .autoencoder_quack import (
    MAX_PENDING, RegistryTransportClient, _identifier,
)
from .autoencoder_quack_wire import (
    SCHEMA, QuackWireError, _request as encode_request, make_reply, parse_request,
)
from .contracts import canonical_json_bytes
from .span_cache_quack import SpanCacheQuackError, SpanCacheQuackGateway
from ..logic.autoformal.span_cache_claims import SpanClaimError

BIND = "BindSpanSourcesFenced"
CLAIM = "ClaimSpansFenced"
READ = "ReadClaimedSpanFenced"
COMPLETE = "CompleteSpansFenced"
RELEASE = "ReleaseSpansFenced"
RESOLVE = "ResolveSpanOperation"
COMMANDS = frozenset({CLAIM, READ, COMPLETE, RELEASE, RESOLVE})
MUTATIONS = frozenset({CLAIM, COMPLETE, RELEASE})
MAX_ROWS = 32
OWNER_RESPONSE_SECONDS = 55


@dataclass(frozen=True)
class SpanClaimWorkerScope:
    """Immutable assignment minted by the owner, never supplied in a request."""

    worker_id: str
    span_ids: frozenset[str]

    def __post_init__(self) -> None:
        _identifier(self.worker_id, "worker_id")
        if type(self.span_ids) not in {set, frozenset}:
            raise SpanCacheQuackError("owner scope span_ids must be a set")
        spans = frozenset(self.span_ids)
        if not 1 <= len(spans) <= 64:
            raise SpanCacheQuackError("owner scope requires 1..64 assigned spans")
        for value in spans:
            if type(value) is not str or not value or len(value.encode("utf-8")) > 512:
                raise SpanCacheQuackError("owner scope requires bounded span identifiers")
        object.__setattr__(self, "span_ids", spans)


def _envelope(command: str, payload: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    if command not in COMMANDS:
        raise SpanCacheQuackError("command is outside the fenced span vocabulary")
    if not isinstance(payload, Mapping):
        raise SpanCacheQuackError("payload must be an object")
    return parse_request(encode_request({
        "schema": SCHEMA, "request_id": str(uuid.uuid4()),
        "operation_id": operation_id, "command": command, "payload": dict(payload),
    }))


class SpanClaimsTransportClient(RegistryTransportClient):
    """The existing native Quack client with the closed fenced span vocabulary."""

    @staticmethod
    def _request_envelope(command, payload, operation_id):
        return _envelope(command, payload, operation_id)


class SpanClaimsQuackGateway(SpanCacheQuackGateway):
    """Typed queue adapter; only serve(cache) can invoke the native facade."""

    def __init__(self, cache: Any, scope: SpanClaimWorkerScope, *,
                 enable_prototype: bool = False) -> None:
        if enable_prototype is not True:
            raise SpanCacheQuackError("fenced span gateway requires explicit prototype opt-in")
        if type(scope) is not SpanClaimWorkerScope:
            raise SpanCacheQuackError("an owner-issued span worker scope is required")
        self._cache = cache
        self.scope = scope
        self._owner_pid = os.getpid()
        self._owner_thread = threading.get_ident()
        self._claims = cache.fenced_claims()
        self._closed = False
        self._queue_lock = threading.Lock()
        super().__init__()
        self._requests = queue.Queue(maxsize=MAX_PENDING)

    def _owner(self, cache: Any = None) -> None:
        if os.getpid() != self._owner_pid:
            raise SpanCacheQuackError("fenced span commands must run in the original catalog owner process")
        if threading.get_ident() != self._owner_thread:
            raise SpanCacheQuackError("fenced span commands must run on the original catalog owner thread")
        if cache is not None and cache is not self._cache:
            raise SpanCacheQuackError("gateway cannot serve a different span catalog owner")

    def _before_start(self) -> None:
        self._owner()
        if self._closed:
            raise SpanCacheQuackError("fenced span gateway is closed")

    @staticmethod
    def _fields(payload: Any, required: set[str], optional: frozenset[str] = frozenset()) -> None:
        if type(payload) is not dict or not required <= payload.keys() or payload.keys() - required - optional:
            raise SpanCacheQuackError("payload does not match the closed command schema")

    def _span(self, span_id: Any) -> str:
        if type(span_id) is not str or span_id not in self.scope.span_ids:
            raise SpanCacheQuackError("span is outside the assigned worker scope")
        return span_id

    def _batch(self, value: Any, label: str) -> list:
        if type(value) is not list or not 1 <= len(value) <= MAX_ROWS:
            raise SpanCacheQuackError(label + " requires 1..32 rows")
        return value

    def _lease(self, lease: Any) -> dict:
        if type(lease) is not dict or lease.get("claim_worker") != self.scope.worker_id:
            raise SpanCacheQuackError("claim is outside the assigned worker scope")
        self._span(lease.get("source_span_id"))
        return lease

    def _validate(self, command: str, payload: Any) -> None:
        if command == CLAIM:
            self._fields(payload, {"span_ids"}, frozenset({"lease_seconds"}))
            for span_id in self._batch(payload["span_ids"], "span_ids"):
                self._span(span_id)
        elif command == READ:
            self._fields(payload, {"claim"})
            self._lease(payload["claim"])
        elif command == COMPLETE:
            self._fields(payload, {"rows", "code_identity", "path_hashes"})
            for row in self._batch(payload["rows"], "rows"):
                self._fields(row, {"claim", "agrees", "decompiled", "rule", "repair", "reason"})
                self._lease(row["claim"])
        elif command == RELEASE:
            self._fields(payload, {"claims"})
            for lease in self._batch(payload["claims"], "claims"):
                self._lease(lease)
        elif command == RESOLVE:
            self._fields(payload, {"operation_id", "command", "payload"})
            _identifier(payload["operation_id"], "original operation_id")
            if payload["command"] not in MUTATIONS:
                raise SpanCacheQuackError("resolve requires an original mutation command")
            self._validate(payload["command"], payload["payload"])
        else:
            raise SpanCacheQuackError("command is outside the fenced span vocabulary")

    def _durable_id(self, operation_id: str) -> str:
        return "span-quack:" + hashlib.sha256(canonical_json_bytes({
            "worker_id": self.scope.worker_id, "operation_id": operation_id,
        })).hexdigest()

    def bind_sources_fenced(self, operation_id: str, bindings: list, *,
                            owner_authorized: bool = False) -> dict:
        """Owner-local explicit binding only; never part of the worker RPC.

        The bool records an explicit invocation choice, not independent trust.
        This owner method does not establish statutory review or qualification.
        """
        self._owner()
        if self._closed or owner_authorized is not True:
            raise SpanCacheQuackError("source binding requires the open native owner and explicit authorization")
        _identifier(operation_id, "owner operation_id")
        for binding in self._batch(bindings, "bindings"):
            self._fields(binding, {"source_span_id", "source_revision", "source_sha256", "expected_binding"})
            self._span(binding["source_span_id"])
        durable_id = "span-quack-owner:" + hashlib.sha256(canonical_json_bytes({
            "worker_id": self.scope.worker_id, "operation_id": operation_id,
        })).hexdigest()
        return self._claims.bind_sources_fenced(durable_id, bindings)

    def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        request = parse_request(encode_request(dict(envelope)))
        self._validate(request["command"], request["payload"])
        item = {"request": request, "state": "queued", "event": threading.Event(),
                "lock": threading.Lock(), "result": None, "error": None}
        with self._queue_lock:
            if self._closed:
                raise SpanCacheQuackError("fenced span gateway is closed")
            try:
                self._requests.put_nowait(item)
            except queue.Full:
                raise SpanCacheQuackError("fenced span owner queue is full") from None
        if not item["event"].wait(OWNER_RESPONSE_SECONDS):
            with item["lock"]:
                if item["state"] == "queued":
                    item["state"] = "cancelled"
                committed_unknown = item["state"] != "cancelled"
            if committed_unknown:
                raise SpanCacheQuackError("owner reply unavailable; resolve the original operation ID and exact payload")
            raise SpanCacheQuackError("owner request cancelled before dispatch")
        if item["error"] is not None:
            raise SpanCacheQuackError(item["error"])
        return item["result"]

    def _apply(self, request: dict) -> dict:
        command, payload = request["command"], request["payload"]
        durable_id = self._durable_id(request["operation_id"])
        if command == CLAIM:
            return self._claims.claim_batch_fenced(durable_id, self.scope.worker_id,
                payload["span_ids"], lease_seconds=payload.get("lease_seconds", 300))
        if command == READ:
            return self._claims.read_claim_source_fenced(payload["claim"])
        if command == COMPLETE:
            return self._claims.complete_claimed_fenced(durable_id, payload["rows"],
                code_identity=payload["code_identity"], path_hashes=payload["path_hashes"])
        if command == RELEASE:
            return self._claims.release_claims_fenced(durable_id, payload["claims"])
        original_command, original_payload = self._native_operation(payload["command"], payload["payload"])
        receipt = self._claims.resolve_operation(self._durable_id(payload["operation_id"]),
                                                 original_command, original_payload)
        return {"status": "resolved" if receipt is not None else "not_found",
                "receipt": receipt, "historical_receipt_only": True,
                "qualified": False, "admitted": False, "formalized": False, "roundtrip_ok": False}

    def _native_operation(self, command: str, payload: dict) -> tuple[str, dict]:
        """Reconstruct the native payload exactly, including owner-issued scope."""
        if command == CLAIM:
            return "ClaimSpans", {"worker_id": self.scope.worker_id,
                "span_ids": payload["span_ids"], "lease_seconds": payload.get("lease_seconds", 300)}
        if command == COMPLETE:
            return "CompleteSpans", dict(payload)
        return "ReleaseSpans", {"claims": payload["claims"]}

    def serve(self, cache: Any) -> int:
        """Dequeue at most MAX_PENDING items per owner tick, counting cancellations."""
        self._owner(cache)
        if self._closed:
            raise SpanCacheQuackError("fenced span gateway is closed")
        served = 0
        for _ in range(MAX_PENDING):
            try:
                item = self._requests.get_nowait()
            except queue.Empty:
                return served
            with item["lock"]:
                if item["state"] != "queued":
                    continue
                item["state"] = "started"
            request = item["request"]
            try:
                result = self._apply(request)
                # Validate the full actual bound reply before reporting it. A
                # refusal after commit requires exact operation resolution.
                make_reply(request, result=result)
                item["result"] = result
            except QuackWireError:
                item["result"] = {"status": "refused",
                    "refusal": {"code": "reply_requires_data_plane",
                                "reason": "complete owner reply exceeds the bounded transport; no truncation applied"},
                    "command": request["command"], "operation_id": request["operation_id"],
                    "must_resolve_original_operation": request["command"] in MUTATIONS,
                    "qualified": False, "admitted": False, "formalized": False, "roundtrip_ok": False}
            except SpanClaimError as exc:
                # This refusal is not a committed-success receipt or a claim
                # that an earlier uncertain invocation did not commit.
                item["result"] = {"status": "refused",
                    "refusal": {"code": "native_claim_refused", "reason": str(exc)},
                    "command": request["command"], "operation_id": request["operation_id"],
                    "must_resolve_original_operation": True, "qualified": False,
                    "admitted": False, "formalized": False, "roundtrip_ok": False}
            except Exception as exc:
                item["error"] = ("owner operation unavailable (" + type(exc).__name__
                    + "); resolve the original operation ID and exact payload")
            finally:
                with item["lock"]:
                    item["state"] = "finished"
                item["event"].set()
            served += 1
        return served

    def close(self) -> None:
        self._owner()
        with self._queue_lock:
            self._closed = True
            while True:
                try:
                    item = self._requests.get_nowait()
                except queue.Empty:
                    break
                with item["lock"]:
                    if item["state"] == "queued":
                        item["state"] = "cancelled"
                        item["error"] = "fenced span gateway closed before owner dispatch"
                        item["event"].set()
        # Native facade lifetime belongs to SpanCache, never this endpoint.
        super().close()

    def status(self) -> dict:
        return {"schema": SCHEMA, "prototype": True, "runtime_qualified": False,
                "worker_id": self.scope.worker_id, "assigned_span_count": len(self.scope.span_ids),
                "pending": self._requests.qsize(), "closed": self._closed,
                "private_catalog_attached": False, "worker_catalog_open": False,
                "production_mutation_enabled": False, "admitted": False,
                "formalized": False, "roundtrip_ok": False, "failure": self._failure}
