"""Bounded, opt-in observations of ontology capture; never a reuse certificate.

This module uses only the standard library. It retains primitive diagnostics,
not sample objects, capture records, exception objects or exception messages.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import time
from typing import Any, Iterator


_COLLECTOR: ContextVar[Any] = ContextVar("ontology_observation_collector", default=None)
_SCOPE: ContextVar[Any] = ContextVar("ontology_observation_scope", default=None)
_OBSERVATIONS_SCOPE = (
    "Instrumented capture boundaries, direct suppressed exceptions, and explicitly "
    "observed conversion results only; transitive parser/repair failures may remain "
    "unobserved. Returned without observed error does not establish reuse eligibility."
)


def _identity(value: Any) -> Any:
    def validate(item: Any, depth: int = 0) -> None:
        if depth > 16:
            raise ValueError("producer identity nesting exceeds observation bound")
        if item is None or type(item) in (str, bool, int, float):
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                validate(child, depth + 1)
            return
        if type(item) in (list, tuple):
            for child in item:
                validate(child, depth + 1)
            return
        raise TypeError("producer identity must contain plain JSON values")

    validate(value)
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > 65536:
        raise ValueError("producer identity exceeds 64 KiB observation bound")
    return json.loads(encoded)


class OntologyCaptureObservation:
    """One bounded collection. ``producer_identity`` is a caller-supplied label."""

    def __init__(self, *, producer_identity: Any = None, max_batches: int = 128,
                 max_records: int = 4096, max_stages: int = 32768,
                 max_errors: int = 4096) -> None:
        limits = {"captures": max_batches, "records": max_records,
                  "stages": max_stages, "errors": max_errors, "conversions": max_stages}
        if any(type(v) is not int or not 1 <= v <= 100000 for v in limits.values()):
            raise ValueError("observation limits must be integers between 1 and 100000")
        self._identity = _identity(producer_identity)
        self._limits = limits
        self._rows: dict[str, list[dict[str, Any]]] = {key: [] for key in limits}
        self._counts: dict[str, int] = {}
        self._complete = True
        self._closed = False
        self._sequence = 0

    def _count(self, name: str) -> None:
        self._counts[name] = self._counts.get(name, 0) + 1

    def _fault(self) -> None:
        self._complete = False
        self._count("instrumentation_errors")

    def _text(self, value: Any, limit: int = 256) -> str | None:
        # Never invoke an arbitrary object's __str__ merely to observe it.
        if type(value) is not str:
            self._complete = False
            self._count("unsupported_labels")
            return None
        if len(value) > limit:
            self._complete = False
            self._count("truncated_labels")
            return value[:limit]
        return value

    def _append(self, kind: str, row: dict[str, Any]) -> dict[str, Any] | None:
        self._count(kind + "_observed")
        if len(self._rows[kind]) >= self._limits[kind]:
            self._complete = False
            self._count(kind + "_dropped")
            return None
        self._rows[kind].append(row)
        return row

    def to_dict(self) -> dict[str, Any]:
        """Return a fully detached snapshot, including any bounded-data loss."""
        totals: dict[str, dict[str, Any]] = {}
        for row in self._rows["stages"]:
            aggregate = totals.setdefault(row["name"], {
                "calls": 0, "elapsed_seconds": 0.0, "aborted_scopes": 0,
                "scopes_with_observed_error": 0,
            })
            aggregate["calls"] += 1
            aggregate["elapsed_seconds"] += row["elapsed_seconds"] or 0.0
            aggregate["aborted_scopes"] += row["outcome"] == "aborted"
            aggregate["scopes_with_observed_error"] += bool(row["observed_error_count"])
        return deepcopy({
            "schema_version": "ontology-capture-observation-v1",
            "observations_scope": _OBSERVATIONS_SCOPE,
            "reuse_qualified": False,
            "observations_complete": self._complete,
            "context_closed": self._closed,
            "producer_identity": self._identity,
            "producer_identity_verified": False,
            "limits": {**self._limits, "label_characters": 256,
                       "producer_identity_json_bytes": 65536},
            "memory_bound_scope": "retained row counts and label lengths; Python overhead is not byte-attested",
            "counters": self._counts,
            "stage_totals": totals,
            "stage_totals_scope": "retained stage rows; incomplete when observation bounds truncate rows",
            **self._rows,
        })


@contextmanager
def observe_ontology_captures(**kwargs: Any) -> Iterator[OntologyCaptureObservation]:
    """Install a collection for this context and restore enclosing contexts."""
    observer = OntologyCaptureObservation(**kwargs)
    token = _COLLECTOR.set(observer)
    scope_token = _SCOPE.set(None)
    try:
        yield observer
    finally:
        observer._closed = True
        _SCOPE.reset(scope_token)
        _COLLECTOR.reset(token)


class _NoopScope:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def identify(self, sample_id: str) -> str:
        return sample_id

    def emitted(self) -> None:
        pass

    def returned(self, count: int | None = None) -> None:
        pass


_NOOP = _NoopScope()


class _ObservationScope(_NoopScope):
    def __init__(self, observer: OntologyCaptureObservation, kind: str,
                 name: str, ordinal: int | None = None) -> None:
        self.observer = observer
        self.kind = kind
        self.parent = _SCOPE.get()
        if self.parent is not None and self.parent.observer is not observer:
            self.parent = None
        observer._sequence += 1
        self.scope_id = observer._sequence
        self.row = observer._append(kind, {
            "scope_id": self.scope_id,
            "parent_scope_id": self.parent.scope_id if self.parent else None,
            "capture_scope_id": self._ancestor_id("captures"),
            "record_scope_id": self._ancestor_id("records"),
            "name": observer._text(name),
            "ordinal": ordinal if type(ordinal) is int else None,
            "sample_id": None,
            "outcome": "in_progress",
            "observed_error_count": 0,
            "started_record_count": 0,
            "emitted_record_count": 0,
            "returned_record_count": None,
            "discarded_record_count": 0,
            "elapsed_seconds": None,
            "reuse_qualified": False,
        })
        self.returned_marked = kind == "stages"
        self.started = None
        self.token = None
        if kind == "records":
            self._increment_ancestors("started_record_count")

    def _ancestor_id(self, kind: str) -> int | None:
        scope = self.parent
        while scope is not None:
            if scope.kind == kind:
                return scope.scope_id
            scope = scope.parent
        return None

    def _increment_ancestors(self, key: str) -> None:
        scope = self.parent
        while scope is not None:
            if scope.row is not None:
                scope.row[key] += 1
            scope = scope.parent

    def __enter__(self):
        self.token = _SCOPE.set(self)
        try:
            self.started = time.perf_counter()
        except Exception:
            self.observer._fault()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc is not None:
                _error(self, self.row["name"] if self.row else self.kind, exc, "escaped")
            if self.row is not None:
                self.row["elapsed_seconds"] = (
                    max(0.0, time.perf_counter() - self.started) if self.started is not None else None
                )
                if exc is not None:
                    self.row["outcome"] = "aborted"
                elif not self.returned_marked:
                    self.row["outcome"] = "exited_without_return_marker"
                    self.observer._complete = False
                else:
                    self.row["outcome"] = (
                        "returned_with_observed_error" if self.row["observed_error_count"]
                        else "returned_without_observed_error"
                    )
                if self.kind == "captures":
                    emitted = self.row["emitted_record_count"]
                    returned = self.row["returned_record_count"]
                    self.row["discarded_record_count"] = (
                        emitted if exc is not None else max(0, emitted - returned)
                        if returned is not None else 0
                    )
        except Exception:
            self.observer._fault()
        finally:
            if self.token is not None:
                _SCOPE.reset(self.token)
        return False

    def identify(self, sample_id: str) -> str:
        try:
            if self.row is not None:
                self.row["sample_id"] = self.observer._text(sample_id)
        except Exception:
            self.observer._fault()
        return sample_id

    def emitted(self) -> None:
        try:
            if not self.returned_marked:
                self.returned_marked = True
                self._increment_ancestors("emitted_record_count")
                self.observer._count("records_emitted")
        except Exception:
            self.observer._fault()

    def returned(self, count: int | None = None) -> None:
        try:
            self.returned_marked = True
            if self.row is not None and (count is None or type(count) is int and count >= 0):
                self.row["returned_record_count"] = count
        except Exception:
            self.observer._fault()


def _scope(kind: str, name: str, ordinal: int | None = None):
    observer = _COLLECTOR.get()
    if observer is None or observer._closed:
        return _NOOP
    try:
        return _ObservationScope(observer, kind, name, ordinal)
    except Exception:
        observer._fault()
        return _NOOP


def capture_scope(kind: str):
    return _scope("captures", kind)


batch_scope = capture_scope


def record_scope(ordinal: int):
    return _scope("records", "record", ordinal)


def stage_scope(stage: str):
    return _scope("stages", stage)


def _mark_error(scope: _ObservationScope) -> None:
    while scope is not None:
        if scope.row is not None:
            scope.row["observed_error_count"] += 1
        scope = scope.parent


def _error(scope: _ObservationScope, stage: str, exc: BaseException, disposition: str) -> None:
    observer = scope.observer
    _mark_error(scope)
    observer._append("errors", {
        "scope_id": scope.scope_id,
        "capture_scope_id": scope.scope_id if scope.kind == "captures" else scope._ancestor_id("captures"),
        "record_scope_id": scope.scope_id if scope.kind == "records" else scope._ancestor_id("records"),
        "stage": observer._text(stage),
        "exception_type": observer._text(type(exc).__module__ + "." + type(exc).__qualname__),
        "disposition": disposition,
    })


def note_suppressed(stage: str, exc: BaseException) -> None:
    scope = _SCOPE.get()
    if scope is None or scope.observer._closed:
        return
    try:
        _error(scope, stage, exc, "suppressed")
    except Exception:
        scope.observer._fault()


def note_conversion_result(stage: str, *, status: str | None,
                           successful: bool | None = None,
                           error_count: int | None = 0,
                           warning_count: int | None = 0,
                           supported: bool = True) -> None:
    """Receive primitives from an exact-type adapter, without retaining results."""
    observer = _COLLECTOR.get()
    if observer is None or observer._closed:
        return
    try:
        scope = _SCOPE.get()
        supported = supported is True
        if (type(successful) is not bool or type(status) is not str
                or type(error_count) is not int or error_count < 0
                or type(warning_count) is not int or warning_count < 0):
            supported = False
        if not supported:
            observer._complete = False
            status = successful = error_count = warning_count = None
        observed_error = not supported or not successful or bool(error_count)
        if observed_error and scope is not None:
            _mark_error(scope)
        observer._append("conversions", {
            "stage": observer._text(stage),
            "scope_id": scope.scope_id if scope else None,
            "capture_scope_id": (scope.scope_id if scope.kind == "captures" else scope._ancestor_id("captures")) if scope else None,
            "record_scope_id": (scope.scope_id if scope.kind == "records" else scope._ancestor_id("records")) if scope else None,
            "status": observer._text(status) if status is not None else None,
            "successful": successful,
            "supported": supported,
            "error_count": error_count,
            "warning_count": warning_count,
            "reuse_qualified": False,
        })
    except Exception:
        observer._fault()


def observation_active() -> bool:
    observer = _COLLECTOR.get()
    return observer is not None and not observer._closed


def observe_conversion_result(stage: str, converted: Any, *, result_type: type,
                              status_type: type) -> None:
    """Inspect only the caller's exact native result and built-in containers."""
    if not observation_active():
        return
    try:
        data = vars(converted) if type(converted) is result_type else {}
        status = data.get("status")
        errors, warnings = data.get("errors"), data.get("warnings")
        supported = (type(status) is status_type and type(errors) in (list, tuple)
                     and type(warnings) in (list, tuple))
        note_conversion_result(
            stage, supported=supported,
            status=status.value if supported else None,
            successful=status in (status_type.SUCCESS, status_type.PARTIAL, status_type.CACHED) if supported else None,
            error_count=len(errors) if supported else None,
            warning_count=len(warnings) if supported else None,
        )
    except Exception:
        observer = _COLLECTOR.get()
        if observer is not None:
            observer._fault()
