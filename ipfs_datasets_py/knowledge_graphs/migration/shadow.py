"""Shadow dual-read comparison for knowledge-graph adoption (KGP-033).

Shadow mode executes a primary (legacy / production) read and a secondary
(candidate / new-stack) read for the same logical request, **always returning
the primary result to the caller**. Comparison outcomes, bounded mismatch
evidence, and performance metrics are retained for observability and automatic
threshold enforcement.

Normative rules:

* Caller-visible results are **never** replaced by the shadow path.
* Shadow is **read-only by default**; dual-write requires an explicit
  ``allow_dual_write=True`` flag and an idempotency key.
* Mismatch and latency evidence is **bounded** (item count and byte size).
* Automatic stop fires when security or correctness thresholds are exceeded.
* No legacy data is converted or deleted in place.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Final,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

T = TypeVar("T")

SHADOW_SCHEMA_VERSION: Final = "kg-shadow-read/v1"
METRICS_SCHEMA_VERSION: Final = "kg-shadow-metrics/v1"

DEFAULT_MAX_MISMATCH_EVIDENCE: Final = 64
DEFAULT_MAX_EVIDENCE_BYTES: Final = 8_192
DEFAULT_MAX_MISMATCH_RATE: Final = 0.05
DEFAULT_MAX_ABSOLUTE_MISMATCHES: Final = 50
DEFAULT_MAX_LATENCY_RATIO: Final = 3.0
DEFAULT_MAX_SHADOW_ERROR_RATE: Final = 0.10
DEFAULT_MIN_SAMPLES_FOR_RATE: Final = 20
DEFAULT_SECURITY_STOP_IMMEDIATE: Final = True


class ShadowStopReason(str, Enum):
    """Why shadow comparison was automatically stopped."""

    NONE = "none"
    MISMATCH_RATE = "mismatch_rate"
    ABSOLUTE_MISMATCHES = "absolute_mismatches"
    LATENCY_RATIO = "latency_ratio"
    SHADOW_ERROR_RATE = "shadow_error_rate"
    SECURITY = "security"
    CORRECTNESS = "correctness"
    MANUAL = "manual"


class MismatchKind(str, Enum):
    """Classification of a shadow vs primary divergence."""

    MATCH = "match"
    VALUE_MISMATCH = "value_mismatch"
    TYPE_MISMATCH = "type_mismatch"
    SHADOW_ERROR = "shadow_error"
    PRIMARY_ERROR = "primary_error"
    SECURITY = "security"
    MISSING = "missing"
    EXTRA = "extra"


class ShadowError(Exception):
    """Base error for shadow migration controls."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "SHADOW_ERROR",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class ShadowStoppedError(ShadowError):
    """Raised when dual-write is refused because shadow is stopped.

    Dual-read still returns primary results when stopped; only mutating
    dual-write paths raise this to fail closed.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: ShadowStopReason,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(
            message,
            code="SHADOW_STOPPED",
            details={"reason": reason.value, **dict(details or {})},
        )
        self.reason = reason


# ---------------------------------------------------------------------------
# Canonical comparison helpers
# ---------------------------------------------------------------------------


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def canonicalize(value: Any) -> Any:
    """Return a JSON-safe, deterministically ordered structure for comparison."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(k): canonicalize(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, set):
        items = [canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return canonicalize(value.to_dict())
    return str(value)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def results_equal(left: Any, right: Any) -> bool:
    """Structural equality under canonicalization."""

    try:
        return canonicalize(left) == canonicalize(right)
    except (TypeError, ValueError):
        return False


def clip_evidence(value: Any, *, max_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES) -> Any:
    """Bound evidence size for metrics retention."""

    try:
        canon = canonicalize(value)
        raw = canonical_json_bytes(canon)
    except (TypeError, ValueError):
        text = repr(value)
        if len(text.encode("utf-8")) <= max_bytes:
            return text
        return {
            "_truncated": True,
            "_type": type(value).__name__,
            "_repr_prefix": text[: max(16, max_bytes // 4)],
        }
    if len(raw) <= max_bytes:
        return canon
    summary: Dict[str, Any] = {
        "_truncated": True,
        "_original_bytes": len(raw),
        "_max_bytes": max_bytes,
        "_type": type(value).__name__,
        "_digest": content_digest(value),
    }
    if isinstance(value, Mapping):
        summary["_keys"] = sorted(str(k) for k in value.keys())[:32]
        summary["_key_count"] = len(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        summary["_length"] = len(value)
        head = [canonicalize(item) for item in list(value)[:8]]
        if len(canonical_json_bytes(head)) <= max_bytes // 2:
            summary["_head"] = head
    elif isinstance(value, str):
        keep = max(16, max_bytes // 4)
        summary["_prefix"] = value[:keep]
        summary["_length"] = len(value)
    return summary


# ---------------------------------------------------------------------------
# Configuration and metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShadowConfig:
    """Thresholds and bounds for shadow dual-read comparison."""

    max_mismatch_rate: float = DEFAULT_MAX_MISMATCH_RATE
    max_absolute_mismatches: int = DEFAULT_MAX_ABSOLUTE_MISMATCHES
    max_latency_ratio: float = DEFAULT_MAX_LATENCY_RATIO
    max_shadow_error_rate: float = DEFAULT_MAX_SHADOW_ERROR_RATE
    min_samples_for_rate: int = DEFAULT_MIN_SAMPLES_FOR_RATE
    max_mismatch_evidence: int = DEFAULT_MAX_MISMATCH_EVIDENCE
    max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES
    security_stop_immediate: bool = DEFAULT_SECURITY_STOP_IMMEDIATE
    enabled: bool = True
    # Dual-write is opt-in and requires an idempotency key at call time.
    allow_dual_write: bool = False
    # Optional label for telemetry grouping (e.g. corpus name).
    label: str = "default"

    def __post_init__(self) -> None:
        if not 0.0 <= self.max_mismatch_rate <= 1.0:
            raise ValueError("max_mismatch_rate must be in [0, 1]")
        if self.max_absolute_mismatches < 0:
            raise ValueError("max_absolute_mismatches must be >= 0")
        if self.max_latency_ratio < 1.0:
            raise ValueError("max_latency_ratio must be >= 1.0")
        if not 0.0 <= self.max_shadow_error_rate <= 1.0:
            raise ValueError("max_shadow_error_rate must be in [0, 1]")
        if self.min_samples_for_rate < 1:
            raise ValueError("min_samples_for_rate must be >= 1")
        if self.max_mismatch_evidence < 0:
            raise ValueError("max_mismatch_evidence must be >= 0")
        if self.max_evidence_bytes < 64:
            raise ValueError("max_evidence_bytes must be >= 64")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_mismatch_rate": self.max_mismatch_rate,
            "max_absolute_mismatches": self.max_absolute_mismatches,
            "max_latency_ratio": self.max_latency_ratio,
            "max_shadow_error_rate": self.max_shadow_error_rate,
            "min_samples_for_rate": self.min_samples_for_rate,
            "max_mismatch_evidence": self.max_mismatch_evidence,
            "max_evidence_bytes": self.max_evidence_bytes,
            "security_stop_immediate": self.security_stop_immediate,
            "enabled": self.enabled,
            "allow_dual_write": self.allow_dual_write,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class MismatchEvidence:
    """Bounded record of one primary/shadow divergence."""

    kind: MismatchKind
    operation: str
    graph_id: Optional[str]
    primary_digest: Optional[str]
    shadow_digest: Optional[str]
    primary_clip: Any
    shadow_clip: Any
    primary_latency_ms: float
    shadow_latency_ms: float
    security: bool = False
    message: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "operation": self.operation,
            "graph_id": self.graph_id,
            "primary_digest": self.primary_digest,
            "shadow_digest": self.shadow_digest,
            "primary_clip": self.primary_clip,
            "shadow_clip": self.shadow_clip,
            "primary_latency_ms": self.primary_latency_ms,
            "shadow_latency_ms": self.shadow_latency_ms,
            "security": self.security,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class ShadowMetrics:
    """In-process, thread-safe shadow comparison metrics."""

    schema_version: str = METRICS_SCHEMA_VERSION
    label: str = "default"
    total_reads: int = 0
    matches: int = 0
    mismatches: int = 0
    shadow_errors: int = 0
    primary_errors: int = 0
    security_events: int = 0
    primary_latency_sum_ms: float = 0.0
    shadow_latency_sum_ms: float = 0.0
    primary_latency_samples: List[float] = field(default_factory=list)
    shadow_latency_samples: List[float] = field(default_factory=list)
    evidence: List[MismatchEvidence] = field(default_factory=list)
    stopped: bool = False
    stop_reason: ShadowStopReason = ShadowStopReason.NONE
    stop_message: str = ""
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def record_sample(
        self,
        *,
        matched: bool,
        primary_latency_ms: float,
        shadow_latency_ms: float,
        shadow_error: bool = False,
        primary_error: bool = False,
        security: bool = False,
        evidence: Optional[MismatchEvidence] = None,
        max_evidence: int = DEFAULT_MAX_MISMATCH_EVIDENCE,
        max_latency_samples: int = 256,
    ) -> None:
        with self._lock:
            self.total_reads += 1
            self.primary_latency_sum_ms += max(0.0, primary_latency_ms)
            self.shadow_latency_sum_ms += max(0.0, shadow_latency_ms)
            self._append_sample(
                self.primary_latency_samples, primary_latency_ms, max_latency_samples
            )
            self._append_sample(
                self.shadow_latency_samples, shadow_latency_ms, max_latency_samples
            )
            if primary_error:
                self.primary_errors += 1
            if shadow_error:
                self.shadow_errors += 1
            if security:
                self.security_events += 1
            if matched and not shadow_error and not primary_error:
                self.matches += 1
            elif not matched and not primary_error:
                self.mismatches += 1
            if evidence is not None and max_evidence > 0:
                if len(self.evidence) < max_evidence:
                    self.evidence.append(evidence)
                # else: drop (bounded)

    @staticmethod
    def _append_sample(
        samples: List[float], value: float, max_samples: int
    ) -> None:
        samples.append(max(0.0, value))
        if len(samples) > max_samples:
            del samples[: len(samples) - max_samples]

    @property
    def mismatch_rate(self) -> float:
        with self._lock:
            denom = self.matches + self.mismatches
            if denom == 0:
                return 0.0
            return self.mismatches / denom

    @property
    def shadow_error_rate(self) -> float:
        with self._lock:
            if self.total_reads == 0:
                return 0.0
            return self.shadow_errors / self.total_reads

    @property
    def mean_primary_latency_ms(self) -> float:
        with self._lock:
            if self.total_reads == 0:
                return 0.0
            return self.primary_latency_sum_ms / self.total_reads

    @property
    def mean_shadow_latency_ms(self) -> float:
        with self._lock:
            if self.total_reads == 0:
                return 0.0
            return self.shadow_latency_sum_ms / self.total_reads

    @property
    def latency_ratio(self) -> float:
        """shadow / primary mean latency; 1.0 when primary mean is zero."""

        primary = self.mean_primary_latency_ms
        shadow = self.mean_shadow_latency_ms
        if primary <= 0.0:
            return 1.0 if shadow <= 0.0 else float("inf")
        return shadow / primary

    def mark_stopped(self, reason: ShadowStopReason, message: str = "") -> None:
        with self._lock:
            self.stopped = True
            self.stop_reason = reason
            self.stop_message = message

    def reset_stop(self) -> None:
        with self._lock:
            self.stopped = False
            self.stop_reason = ShadowStopReason.NONE
            self.stop_message = ""

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.schema_version,
                "label": self.label,
                "total_reads": self.total_reads,
                "matches": self.matches,
                "mismatches": self.mismatches,
                "shadow_errors": self.shadow_errors,
                "primary_errors": self.primary_errors,
                "security_events": self.security_events,
                "mismatch_rate": self.mismatch_rate,
                "shadow_error_rate": self.shadow_error_rate,
                "mean_primary_latency_ms": self.mean_primary_latency_ms,
                "mean_shadow_latency_ms": self.mean_shadow_latency_ms,
                "latency_ratio": (
                    self.latency_ratio
                    if math.isfinite(self.latency_ratio)
                    else None
                ),
                "stopped": self.stopped,
                "stop_reason": self.stop_reason.value,
                "stop_message": self.stop_message,
                "evidence_count": len(self.evidence),
                "evidence": [e.to_dict() for e in self.evidence],
            }


@dataclass(frozen=True, slots=True)
class ShadowReadResult:
    """Caller-facing dual-read outcome.

    ``result`` is always the primary path value (or re-raised primary
    exception). Shadow comparison is observational only.
    """

    result: Any
    matched: bool
    primary_latency_ms: float
    shadow_latency_ms: float
    mismatch: Optional[MismatchEvidence]
    stopped: bool
    stop_reason: ShadowStopReason
    primary_error: Optional[str] = None
    shadow_error: Optional[str] = None
    schema_version: str = SHADOW_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "matched": self.matched,
            "primary_latency_ms": self.primary_latency_ms,
            "shadow_latency_ms": self.shadow_latency_ms,
            "mismatch": self.mismatch.to_dict() if self.mismatch else None,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason.value,
            "primary_error": self.primary_error,
            "shadow_error": self.shadow_error,
            "result_digest": content_digest(self.result)
            if self.primary_error is None
            else None,
        }


# ---------------------------------------------------------------------------
# Shadow reader
# ---------------------------------------------------------------------------


def _timed_call(fn: Callable[[], T]) -> Tuple[Optional[T], Optional[BaseException], float]:
    start = time.perf_counter()
    try:
        value = fn()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return value, None, elapsed_ms
    except BaseException as exc:  # noqa: BLE001 — capture for dual-path
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return None, exc, elapsed_ms


def _classify_security(
    primary: Any,
    shadow: Any,
    *,
    security_checker: Optional[Callable[[Any, Any], Optional[str]]],
) -> Optional[str]:
    if security_checker is not None:
        return security_checker(primary, shadow)
    # Default heuristic: never treat equal digests as security issues.
    return None


class ShadowReader:
    """Dual-read comparator that preserves primary caller results.

    Example::

        reader = ShadowReader(ShadowConfig(label="cvefixes"))
        outcome = reader.read(
            primary=lambda: legacy_query(...),
            shadow=lambda: new_query(...),
            operation="query",
            graph_id="kg://acme/cve",
        )
        # Caller uses outcome.result — always the primary value.
    """

    def __init__(
        self,
        config: Optional[ShadowConfig] = None,
        *,
        metrics: Optional[ShadowMetrics] = None,
        security_checker: Optional[Callable[[Any, Any], Optional[str]]] = None,
        comparator: Optional[Callable[[Any, Any], bool]] = None,
    ) -> None:
        self.config = config or ShadowConfig()
        self.metrics = metrics or ShadowMetrics(label=self.config.label)
        self.security_checker = security_checker
        self.comparator = comparator or results_equal
        self._lock = threading.RLock()

    @property
    def is_stopped(self) -> bool:
        return self.metrics.stopped

    @property
    def stop_reason(self) -> ShadowStopReason:
        return self.metrics.stop_reason

    def stop(self, reason: ShadowStopReason = ShadowStopReason.MANUAL, message: str = "") -> None:
        """Manually stop shadow comparison (and dual-write)."""

        self.metrics.mark_stopped(reason, message or f"stopped:{reason.value}")

    def resume(self) -> None:
        """Clear automatic/manual stop so comparison resumes."""

        self.metrics.reset_stop()

    def read(
        self,
        primary: Callable[[], T],
        shadow: Callable[[], Any],
        *,
        operation: str = "read",
        graph_id: Optional[str] = None,
        reraise_primary: bool = True,
    ) -> ShadowReadResult:
        """Execute primary then shadow; always prefer primary for the caller.

        When ``reraise_primary`` is True (default) and the primary callable
        raises, that exception is re-raised after metrics are updated so
        callers observe legacy error behaviour unchanged.
        """

        if not self.config.enabled:
            value, exc, primary_ms = _timed_call(primary)
            if exc is not None:
                if reraise_primary:
                    raise exc
                return ShadowReadResult(
                    result=None,
                    matched=False,
                    primary_latency_ms=primary_ms,
                    shadow_latency_ms=0.0,
                    mismatch=None,
                    stopped=self.is_stopped,
                    stop_reason=self.stop_reason,
                    primary_error=f"{type(exc).__name__}: {exc}",
                )
            return ShadowReadResult(
                result=value,
                matched=True,
                primary_latency_ms=primary_ms,
                shadow_latency_ms=0.0,
                mismatch=None,
                stopped=self.is_stopped,
                stop_reason=self.stop_reason,
            )

        primary_value, primary_exc, primary_ms = _timed_call(primary)
        shadow_value, shadow_exc, shadow_ms = _timed_call(shadow)

        matched = False
        security_msg: Optional[str] = None
        kind = MismatchKind.MATCH
        message = ""
        evidence: Optional[MismatchEvidence] = None
        primary_error_str: Optional[str] = None
        shadow_error_str: Optional[str] = None

        if primary_exc is not None:
            primary_error_str = f"{type(primary_exc).__name__}: {primary_exc}"
            kind = MismatchKind.PRIMARY_ERROR
            message = primary_error_str
            if shadow_exc is not None:
                shadow_error_str = f"{type(shadow_exc).__name__}: {shadow_exc}"
                # Both failed — not a value mismatch for rate purposes.
                matched = True
            else:
                matched = False
        elif shadow_exc is not None:
            shadow_error_str = f"{type(shadow_exc).__name__}: {shadow_exc}"
            kind = MismatchKind.SHADOW_ERROR
            message = shadow_error_str
            matched = False
        else:
            security_msg = _classify_security(
                primary_value,
                shadow_value,
                security_checker=self.security_checker,
            )
            if security_msg:
                kind = MismatchKind.SECURITY
                message = security_msg
                matched = False
            elif self.comparator(primary_value, shadow_value):
                matched = True
                kind = MismatchKind.MATCH
            else:
                matched = False
                kind = MismatchKind.VALUE_MISMATCH
                message = "primary and shadow results diverge"

        if not matched or kind != MismatchKind.MATCH:
            primary_clip = (
                clip_evidence(
                    primary_value if primary_exc is None else primary_error_str,
                    max_bytes=self.config.max_evidence_bytes,
                )
                if kind != MismatchKind.MATCH
                else None
            )
            shadow_clip = (
                clip_evidence(
                    shadow_value if shadow_exc is None else shadow_error_str,
                    max_bytes=self.config.max_evidence_bytes,
                )
                if kind != MismatchKind.MATCH
                else None
            )
            evidence = MismatchEvidence(
                kind=kind,
                operation=operation,
                graph_id=graph_id,
                primary_digest=(
                    content_digest(primary_value) if primary_exc is None else None
                ),
                shadow_digest=(
                    content_digest(shadow_value) if shadow_exc is None else None
                ),
                primary_clip=primary_clip,
                shadow_clip=shadow_clip,
                primary_latency_ms=primary_ms,
                shadow_latency_ms=shadow_ms,
                security=kind == MismatchKind.SECURITY,
                message=message,
            )

        self.metrics.record_sample(
            matched=matched and kind == MismatchKind.MATCH,
            primary_latency_ms=primary_ms,
            shadow_latency_ms=shadow_ms,
            shadow_error=shadow_exc is not None,
            primary_error=primary_exc is not None,
            security=kind == MismatchKind.SECURITY,
            evidence=evidence if kind != MismatchKind.MATCH else None,
            max_evidence=self.config.max_mismatch_evidence,
        )

        self._evaluate_thresholds(security=(kind == MismatchKind.SECURITY))

        outcome = ShadowReadResult(
            result=primary_value if primary_exc is None else None,
            matched=matched and kind == MismatchKind.MATCH,
            primary_latency_ms=primary_ms,
            shadow_latency_ms=shadow_ms,
            mismatch=evidence if kind != MismatchKind.MATCH else None,
            stopped=self.is_stopped,
            stop_reason=self.stop_reason,
            primary_error=primary_error_str,
            shadow_error=shadow_error_str,
        )

        if primary_exc is not None and reraise_primary:
            raise primary_exc
        return outcome

    def dual_write(
        self,
        primary: Callable[[], T],
        shadow: Callable[[], Any],
        *,
        idempotency_key: str,
        operation: str = "write",
        graph_id: Optional[str] = None,
    ) -> ShadowReadResult:
        """Optional dual-write path (disabled by default).

        Requires ``config.allow_dual_write`` and a non-empty idempotency key.
        When shadow is stopped, dual-write fails closed without invoking the
        shadow writer (primary still runs so producers are not blocked on
        shadow faults — only the dual path is refused).
        """

        if not self.config.allow_dual_write:
            raise ShadowError(
                "dual-write requires explicit allow_dual_write=True",
                code="DUAL_WRITE_DISABLED",
            )
        if not idempotency_key or not str(idempotency_key).strip():
            raise ShadowError(
                "dual-write requires a non-empty idempotency_key",
                code="IDEMPOTENCY_REQUIRED",
            )
        if self.is_stopped:
            raise ShadowStoppedError(
                "dual-write refused: shadow comparison is stopped",
                reason=self.stop_reason,
                details={"operation": operation, "graph_id": graph_id},
            )

        # Primary write first; shadow write best-effort for comparison only.
        # We never convert or delete legacy data here.
        return self.read(
            primary=primary,
            shadow=shadow,
            operation=operation,
            graph_id=graph_id,
            reraise_primary=True,
        )

    def _evaluate_thresholds(self, *, security: bool) -> None:
        if self.is_stopped:
            return
        cfg = self.config
        m = self.metrics

        if security and cfg.security_stop_immediate:
            m.mark_stopped(
                ShadowStopReason.SECURITY,
                "security mismatch detected; shadow stopped automatically",
            )
            return

        comparable = m.matches + m.mismatches
        if (
            comparable >= cfg.min_samples_for_rate
            and m.mismatch_rate > cfg.max_mismatch_rate
        ):
            m.mark_stopped(
                ShadowStopReason.MISMATCH_RATE,
                f"mismatch_rate {m.mismatch_rate:.4f} > {cfg.max_mismatch_rate}",
            )
            return

        if m.mismatches > cfg.max_absolute_mismatches:
            m.mark_stopped(
                ShadowStopReason.ABSOLUTE_MISMATCHES,
                f"mismatches {m.mismatches} > {cfg.max_absolute_mismatches}",
            )
            return

        if (
            m.total_reads >= cfg.min_samples_for_rate
            and m.shadow_error_rate > cfg.max_shadow_error_rate
        ):
            m.mark_stopped(
                ShadowStopReason.SHADOW_ERROR_RATE,
                f"shadow_error_rate {m.shadow_error_rate:.4f} > {cfg.max_shadow_error_rate}",
            )
            return

        ratio = m.latency_ratio
        if (
            m.total_reads >= cfg.min_samples_for_rate
            and math.isfinite(ratio)
            and ratio > cfg.max_latency_ratio
            and m.mean_primary_latency_ms > 0.0
        ):
            m.mark_stopped(
                ShadowStopReason.LATENCY_RATIO,
                f"latency_ratio {ratio:.2f} > {cfg.max_latency_ratio}",
            )
            return

        # Absolute mismatch ceiling also maps to correctness stop when
        # security events accumulate without immediate security stop disabled.
        if m.security_events > 0 and not cfg.security_stop_immediate:
            if m.security_events >= max(1, cfg.max_absolute_mismatches):
                m.mark_stopped(
                    ShadowStopReason.CORRECTNESS,
                    f"security_events {m.security_events} exceeded correctness budget",
                )

    def metrics_snapshot(self) -> Dict[str, Any]:
        snap = self.metrics.snapshot()
        snap["config"] = self.config.to_dict()
        return snap


__all__ = [
    "SHADOW_SCHEMA_VERSION",
    "METRICS_SCHEMA_VERSION",
    "DEFAULT_MAX_MISMATCH_EVIDENCE",
    "DEFAULT_MAX_EVIDENCE_BYTES",
    "DEFAULT_MAX_MISMATCH_RATE",
    "DEFAULT_MAX_ABSOLUTE_MISMATCHES",
    "DEFAULT_MAX_LATENCY_RATIO",
    "DEFAULT_MAX_SHADOW_ERROR_RATE",
    "DEFAULT_MIN_SAMPLES_FOR_RATE",
    "ShadowStopReason",
    "MismatchKind",
    "ShadowError",
    "ShadowStoppedError",
    "canonicalize",
    "canonical_json_bytes",
    "content_digest",
    "results_equal",
    "clip_evidence",
    "ShadowConfig",
    "MismatchEvidence",
    "ShadowMetrics",
    "ShadowReadResult",
    "ShadowReader",
]
