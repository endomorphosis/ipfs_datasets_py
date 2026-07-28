"""Redacted authorization telemetry and staged rollout policy (LIG-039).

Interfaces:

* ``AuthorizationTelemetry@1`` — privacy-preserving counters and latency
  observations with a closed, bounded label vocabulary.  Raw prompts,
  arguments, formulas, witnesses, secrets, and CID labels are rejected.
* ``AuthorizationRolloutPolicy@1`` — ordered stage policy
  (``off`` → ``audit`` → ``shadow`` → ``deny-canary`` →
  ``allow-token-canary`` → ``enforce``) with transition validation,
  allowlisted reversible effects, human-approval gates, and immediate
  receipt-consumption disable for rollback.

This leaf owns pure metric/policy logic and config load/validate.  It does
not wire external dashboards, edit the runbook, or change gate/service/
receipt production paths (those remain separate owners).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

AUTHORIZATION_TELEMETRY_INTERFACE: Final = "AuthorizationTelemetry@1"
AUTHORIZATION_TELEMETRY_SCHEMA_VERSION: Final = "authorization-telemetry/v1"
AUTHORIZATION_ROLLOUT_POLICY_INTERFACE: Final = "AuthorizationRolloutPolicy@1"
AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION: Final = (
    "authorization-rollout-policy/v1"
)
ROLLOUT_CONFIG_SCHEMA: Final = "intent-authorization-rollout/v1"

DEFAULT_ROLLOUT_CONFIG_RELATIVE: Final = "config/intent_authorization_rollout.json"

MAX_LABEL_KEY_CHARS: Final = 64
MAX_LABEL_VALUE_CHARS: Final = 64
MAX_LABELS_PER_EVENT: Final = 16
MAX_METRIC_NAME_CHARS: Final = 128
MAX_IDENTIFIER_CHARS: Final = 256
MAX_EFFECT_ALLOWLIST: Final = 256
MAX_APPROVAL_IDS: Final = 64
MAX_LATENCY_SAMPLES_PER_KEY: Final = 10_000

# Substrings / exact tokens that must never appear as metric labels.
# CIDs are detected via structural patterns, not free-form hash dumps.
_FORBIDDEN_LABEL_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "argument",
        "arguments",
        "formula",
        "formulas",
        "witness",
        "witnesses",
        "secret",
        "secrets",
        "cid",
        "cids",
        "raw_prompt",
        "raw_argument",
        "private_formula",
        "auth_token",
        "password",
        "api_key",
    }
)

# Structural CID / multihash detectors (reject as labels).
_CID_V0_RE: Final = re.compile(r"^Qm[1-9A-HJ-NP-Za-km-z]{44}$")
_CID_V1_RE: Final = re.compile(r"^b[a-z2-7]{58,}$")
_BARE_SHA256_RE: Final = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TelemetryError(ValueError):
    """Raised when telemetry recording or redaction fails closed."""


class RolloutPolicyError(ValueError):
    """Raised when a rollout stage transition or config is invalid."""


class ForbiddenTelemetryLabelError(TelemetryError):
    """Raised when a metric label would leak private content."""


# ---------------------------------------------------------------------------
# Closed label vocabularies (bounded; enum-stable wire values)
# ---------------------------------------------------------------------------


class TelemetrySourceKind(str, Enum):
    """Bounded invocation source classes for decision metrics."""

    SKILL = "skill"
    PROMPT_SOURCE = "prompt_source"
    MCP = "mcp"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"


class TelemetryOutcome(str, Enum):
    """Bounded decision outcomes (internal multi-status + wire)."""

    ALLOW = "allow"
    DENY = "deny"
    REJECT = "reject"
    ABSTAIN = "abstain"
    REVIEW = "review"
    INDETERMINATE = "indeterminate"
    ERROR = "error"


class TelemetryPolicyProfile(str, Enum):
    """Bounded policy profile ids mirrored from AdmissibilityProfile@1."""

    DEV_OFFLINE = "dev-offline"
    SECURITY_LITE = "security-lite"
    LEGAL_STRICT = "legal-strict"
    ZKP_REQUIRED = "zkp-required"
    UNKNOWN = "unknown"


class TelemetryProofAuthority(str, Enum):
    """Bounded proof-authority classes (never raw backend payloads)."""

    NATIVE = "native"
    ZKP = "zkp"
    ATTESTED = "attested"
    SIMULATED = "simulated"
    LEGACY = "legacy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class TelemetryCacheClass(str, Enum):
    """Bounded cache hit / miss classification."""

    HIT = "hit"
    MISS = "miss"
    STALE = "stale"
    BYPASS = "bypass"
    UNKNOWN = "unknown"


class TelemetryFilterClass(str, Enum):
    """Bounded candidate-filter stages."""

    CANDIDATE = "candidate"
    APPLICABILITY = "applicability"
    AUTHORITY = "authority"
    TEMPORAL = "temporal"
    TENANT = "tenant"
    REVOCATION = "revocation"
    VERIFICATION = "verification"
    RANKING = "ranking"


class TelemetryRejectionClass(str, Enum):
    """Bounded integrity / freshness rejection classes."""

    STALE = "stale"
    REVOKED = "revoked"
    TAMPERED = "tampered"
    SIMULATION = "simulation"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"


class TelemetryBackendEvent(str, Enum):
    """Bounded backend availability / quality events."""

    AVAILABLE = "available"
    TIMEOUT = "timeout"
    DISAGREEMENT = "disagreement"
    RECONSTRUCTION_FAILURE = "reconstruction_failure"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"


class TelemetryAdjudicationClass(str, Enum):
    """Bounded human review / adjudication rate classes."""

    REVIEW = "review"
    FALSE_ALLOW = "false_allow"
    FALSE_DENY = "false_deny"
    CONFIRMED_ALLOW = "confirmed_allow"
    CONFIRMED_DENY = "confirmed_deny"


class TelemetryReceiptEvent(str, Enum):
    """Bounded receipt lifecycle / enforcement events."""

    CONSUMPTION = "consumption"
    REPLAY = "replay"
    EXPIRY = "expiry"
    TOCTOU = "toctou"
    ISSUED = "issued"
    DISABLED = "disabled"


class RolloutStage(str, Enum):
    """Ordered staged rollout modes (no skipping)."""

    OFF = "off"
    AUDIT = "audit"
    SHADOW = "shadow"
    DENY_CANARY = "deny-canary"
    ALLOW_TOKEN_CANARY = "allow-token-canary"
    ENFORCE = "enforce"


# Pinned ordered stage ladder — skip detection is pure index comparison.
ROLLOUT_STAGE_ORDER: Final[tuple[RolloutStage, ...]] = (
    RolloutStage.OFF,
    RolloutStage.AUDIT,
    RolloutStage.SHADOW,
    RolloutStage.DENY_CANARY,
    RolloutStage.ALLOW_TOKEN_CANARY,
    RolloutStage.ENFORCE,
)

ROLLOUT_STAGE_WIRE_VALUES: Final[tuple[str, ...]] = tuple(
    stage.value for stage in ROLLOUT_STAGE_ORDER
)

# Stages that may authorize any form of live dispatch effect.
_LIVE_EFFECT_STAGES: Final[frozenset[RolloutStage]] = frozenset(
    {
        RolloutStage.DENY_CANARY,
        RolloutStage.ALLOW_TOKEN_CANARY,
        RolloutStage.ENFORCE,
    }
)

# Stages that may mint / consume allow-token receipts for dispatch.
_ALLOW_TOKEN_STAGES: Final[frozenset[RolloutStage]] = frozenset(
    {
        RolloutStage.ALLOW_TOKEN_CANARY,
        RolloutStage.ENFORCE,
    }
)

# Default safe posture when no config is loaded.
DEFAULT_ROLLOUT_STAGE: Final[RolloutStage] = RolloutStage.OFF
DEFAULT_OFFLINE_STAGE: Final[RolloutStage] = RolloutStage.AUDIT


# ---------------------------------------------------------------------------
# Low-level validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_IDENTIFIER_CHARS,
) -> str:
    if not isinstance(value, str):
        raise TelemetryError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise TelemetryError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise TelemetryError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise TelemetryError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise TelemetryError(f"{name} is not a stable identifier")
    return text


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise TelemetryError(f"{name} must be one of: {allowed}") from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TelemetryError(f"{name} must be a mapping")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise TelemetryError(f"{name} must be a boolean")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TelemetryError(f"{name} must be a non-negative integer")
    if value < 0:
        raise TelemetryError(f"{name} must be a non-negative integer")
    return value


def _optional_non_negative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, name)


def stage_index(stage: RolloutStage | str) -> int:
    """Return the ladder index of a rollout stage (raises on unknown)."""

    parsed = parse_rollout_stage(stage)
    return ROLLOUT_STAGE_ORDER.index(parsed)


def parse_rollout_stage(value: Any) -> RolloutStage:
    """Parse a rollout stage wire value; unknown values fail closed."""

    if isinstance(value, RolloutStage):
        return value
    try:
        return RolloutStage(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(ROLLOUT_STAGE_WIRE_VALUES)
        raise RolloutPolicyError(
            f"rollout stage must be one of: {allowed}; fail closed"
        ) from exc


def is_forward_transition(
    current: RolloutStage | str,
    target: RolloutStage | str,
) -> bool:
    """Return True when *target* is strictly later on the stage ladder."""

    return stage_index(target) > stage_index(current)


def is_adjacent_transition(
    current: RolloutStage | str,
    target: RolloutStage | str,
) -> bool:
    """Return True when *target* is exactly one step from *current*."""

    return abs(stage_index(target) - stage_index(current)) == 1


def transition_skips_stages(
    current: RolloutStage | str,
    target: RolloutStage | str,
) -> bool:
    """Return True when the move jumps more than one ladder step."""

    return abs(stage_index(target) - stage_index(current)) > 1


# ---------------------------------------------------------------------------
# Label redaction
# ---------------------------------------------------------------------------


def _normalize_label_token(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _looks_like_cid_or_digest(value: str) -> bool:
    if _CID_V0_RE.fullmatch(value):
        return True
    if _CID_V1_RE.fullmatch(value):
        return True
    if _BARE_SHA256_RE.fullmatch(value):
        return True
    # Common content-address prefixes.
    lower = value.lower()
    if lower.startswith(("cid:", "ipfs://", "baguqeera", "bafy", "bafk", "bafz")):
        return True
    return False


def is_forbidden_telemetry_label(key: str, value: str) -> bool:
    """Return True when a key or value would leak private content as a label."""

    key_norm = _normalize_label_token(key)
    value_norm = _normalize_label_token(value)

    if key_norm in _FORBIDDEN_LABEL_TOKENS:
        return True
    if value_norm in _FORBIDDEN_LABEL_TOKENS:
        return True
    # Compound keys like ``prompt_body`` / ``secret_ref`` / ``cid_label``.
    for token in _FORBIDDEN_LABEL_TOKENS:
        if token in key_norm.split("_") or key_norm.endswith(f"_{token}"):
            return True
        if token in value_norm.split("_"):
            # Allow profile-like values that only share prefix letters by
            # requiring whole-token membership (handled above) — keep
            # substring only for explicit leak tokens in keys.
            pass

    if _looks_like_cid_or_digest(value):
        return True
    if _looks_like_cid_or_digest(value_norm):
        return True
    return False


def redact_metric_labels(
    labels: Mapping[str, Any] | None,
    *,
    allowed_keys: frozenset[str] | None = None,
) -> dict[str, str]:
    """Validate and normalize metric labels under the closed redaction policy.

    Raises :class:`ForbiddenTelemetryLabelError` on any forbidden key/value
    (including raw CID / digest labels).  Unknown free-form keys are rejected
    when *allowed_keys* is provided; otherwise only the privacy filters apply
    and keys must be stable identifiers.
    """

    if labels is None:
        return {}
    mapping = _mapping(labels, "labels")
    if len(mapping) > MAX_LABELS_PER_EVENT:
        raise TelemetryError(
            f"labels exceeds maximum of {MAX_LABELS_PER_EVENT} entries"
        )

    redacted: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        key = _text(raw_key, "label key", max_chars=MAX_LABEL_KEY_CHARS)
        if not _ID_RE.fullmatch(key):
            raise TelemetryError(f"label key {key!r} is not a stable identifier")
        if allowed_keys is not None and key not in allowed_keys:
            raise TelemetryError(
                f"label key {key!r} is not in the closed vocabulary"
            )
        if isinstance(raw_value, Enum):
            value = str(raw_value.value)
        elif isinstance(raw_value, str):
            value = raw_value
        elif isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            # Numeric label values are not used; reject to keep vocabulary closed.
            raise TelemetryError(
                f"label value for {key!r} must be a bounded string enum, not a number"
            )
        else:
            raise TelemetryError(
                f"label value for {key!r} must be a string or enum"
            )
        if not isinstance(value, str):
            raise TelemetryError(f"label value for {key!r} must be a string")
        # Privacy filters run before length limits so CID/digest dumps and
        # forbidden tokens fail closed with a redaction error, not a generic
        # length error that could obscure the leak attempt.
        if is_forbidden_telemetry_label(key, value.strip() if value else value):
            raise ForbiddenTelemetryLabelError(
                f"forbidden telemetry label {key}={value!r}; "
                "metrics must not carry prompt/argument/formula/witness/"
                "secret/CID labels"
            )
        value = _text(value, f"label:{key}", max_chars=MAX_LABEL_VALUE_CHARS)
        redacted[key] = value
    return dict(sorted(redacted.items()))


def _labels_key(labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


# ---------------------------------------------------------------------------
# Metric name constants (closed set for standard observations)
# ---------------------------------------------------------------------------


class TelemetryMetricName(str, Enum):
    """Closed set of standard authorization metric names."""

    DECISION_COUNT = "authorization.decision.count"
    DECISION_LATENCY_MS = "authorization.decision.latency_ms"
    CANDIDATE_COUNT = "authorization.candidate.count"
    FILTER_COUNT = "authorization.filter.count"
    CACHE_COUNT = "authorization.cache.count"
    REJECTION_COUNT = "authorization.rejection.count"
    BACKEND_EVENT_COUNT = "authorization.backend.event_count"
    ADJUDICATION_COUNT = "authorization.adjudication.count"
    RECEIPT_EVENT_COUNT = "authorization.receipt.event_count"
    ROLLOUT_TRANSITION_COUNT = "authorization.rollout.transition_count"
    ROLLOUT_DISABLE_COUNT = "authorization.rollout.disable_count"


STANDARD_METRIC_NAMES: Final[frozenset[str]] = frozenset(
    item.value for item in TelemetryMetricName
)

_DECISION_LABEL_KEYS: Final[frozenset[str]] = frozenset(
    {"source", "outcome", "policy", "authority"}
)
_CACHE_LABEL_KEYS: Final[frozenset[str]] = frozenset({"cache_class"})
_FILTER_LABEL_KEYS: Final[frozenset[str]] = frozenset({"filter_class"})
_REJECTION_LABEL_KEYS: Final[frozenset[str]] = frozenset({"rejection_class"})
_BACKEND_LABEL_KEYS: Final[frozenset[str]] = frozenset({"backend_event"})
_ADJUDICATION_LABEL_KEYS: Final[frozenset[str]] = frozenset(
    {"adjudication_class"}
)
_RECEIPT_LABEL_KEYS: Final[frozenset[str]] = frozenset({"receipt_event"})
_ROLLOUT_LABEL_KEYS: Final[frozenset[str]] = frozenset(
    {"from_stage", "to_stage", "direction"}
)


# ---------------------------------------------------------------------------
# Telemetry sink
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One redacted counter or latency observation."""

    name: str
    value: float
    labels: Mapping[str, str]
    kind: str  # "counter" | "latency_ms"
    recorded_at_monotonic: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "labels": dict(self.labels),
            "name": self.name,
            "recorded_at_monotonic": self.recorded_at_monotonic,
            "value": self.value,
        }


@dataclass
class AuthorizationTelemetry:
    """In-process redacted metric sink (``AuthorizationTelemetry@1``).

    Thread-safe.  Records only closed-vocabulary labels and never stores raw
    prompts, arguments, formulas, witnesses, secrets, or CID labels.
    """

    interface: str = AUTHORIZATION_TELEMETRY_INTERFACE
    schema_version: str = AUTHORIZATION_TELEMETRY_SCHEMA_VERSION
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = field(
        default_factory=dict, repr=False
    )
    _latency_sums_ms: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
        field(default_factory=dict, repr=False)
    )
    _latency_counts: dict[tuple[str, tuple[tuple[str, str], ...]], int] = field(
        default_factory=dict, repr=False
    )
    _latency_max_ms: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
        field(default_factory=dict, repr=False)
    )
    _samples: list[MetricSample] = field(default_factory=list, repr=False)
    _retain_samples: bool = False

    def __post_init__(self) -> None:
        if self.interface != AUTHORIZATION_TELEMETRY_INTERFACE:
            raise TelemetryError(
                f"interface must be {AUTHORIZATION_TELEMETRY_INTERFACE!r}"
            )
        if self.schema_version != AUTHORIZATION_TELEMETRY_SCHEMA_VERSION:
            raise TelemetryError(
                f"schema_version must be {AUTHORIZATION_TELEMETRY_SCHEMA_VERSION!r}"
            )

    # -- core record paths -------------------------------------------------

    def _record_counter(
        self,
        name: str,
        labels: Mapping[str, str],
        *,
        amount: int = 1,
    ) -> None:
        if amount < 1:
            raise TelemetryError("counter amount must be a positive integer")
        name = _text(name, "metric name", max_chars=MAX_METRIC_NAME_CHARS)
        key = (name, _labels_key(labels))
        now = time.monotonic()
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount
            if self._retain_samples:
                self._samples.append(
                    MetricSample(
                        name=name,
                        value=float(amount),
                        labels=dict(labels),
                        kind="counter",
                        recorded_at_monotonic=now,
                    )
                )

    def _record_latency_ms(
        self,
        name: str,
        labels: Mapping[str, str],
        latency_ms: float,
    ) -> None:
        if not isinstance(latency_ms, (int, float)) or isinstance(
            latency_ms, bool
        ):
            raise TelemetryError("latency_ms must be a number")
        if latency_ms < 0:
            raise TelemetryError("latency_ms must be non-negative")
        name = _text(name, "metric name", max_chars=MAX_METRIC_NAME_CHARS)
        key = (name, _labels_key(labels))
        now = time.monotonic()
        with self._lock:
            self._latency_sums_ms[key] = (
                self._latency_sums_ms.get(key, 0.0) + float(latency_ms)
            )
            self._latency_counts[key] = self._latency_counts.get(key, 0) + 1
            prev_max = self._latency_max_ms.get(key, 0.0)
            if float(latency_ms) > prev_max:
                self._latency_max_ms[key] = float(latency_ms)
            if self._retain_samples and (
                len(self._samples) < MAX_LATENCY_SAMPLES_PER_KEY
            ):
                self._samples.append(
                    MetricSample(
                        name=name,
                        value=float(latency_ms),
                        labels=dict(labels),
                        kind="latency_ms",
                        recorded_at_monotonic=now,
                    )
                )

    # -- public observation APIs -------------------------------------------

    def record_decision(
        self,
        *,
        source: TelemetrySourceKind | str,
        outcome: TelemetryOutcome | str,
        policy: TelemetryPolicyProfile | str,
        authority: TelemetryProofAuthority | str,
        latency_ms: float | None = None,
        count: int = 1,
    ) -> None:
        """Record a decision count (and optional latency) with bounded labels."""

        labels = redact_metric_labels(
            {
                "source": _enum(source, TelemetrySourceKind, "source").value,
                "outcome": _enum(outcome, TelemetryOutcome, "outcome").value,
                "policy": _enum(policy, TelemetryPolicyProfile, "policy").value,
                "authority": _enum(
                    authority, TelemetryProofAuthority, "authority"
                ).value,
            },
            allowed_keys=_DECISION_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.DECISION_COUNT.value, labels, amount=count
        )
        if latency_ms is not None:
            self._record_latency_ms(
                TelemetryMetricName.DECISION_LATENCY_MS.value,
                labels,
                latency_ms,
            )

    def record_candidate_count(
        self,
        *,
        filter_class: TelemetryFilterClass | str,
        count: int = 1,
    ) -> None:
        """Record candidate / filter-class throughput."""

        labels = redact_metric_labels(
            {
                "filter_class": _enum(
                    filter_class, TelemetryFilterClass, "filter_class"
                ).value,
            },
            allowed_keys=_FILTER_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.CANDIDATE_COUNT.value, labels, amount=count
        )
        self._record_counter(
            TelemetryMetricName.FILTER_COUNT.value, labels, amount=count
        )

    def record_cache(
        self,
        *,
        cache_class: TelemetryCacheClass | str,
        count: int = 1,
    ) -> None:
        """Record a cache hit/miss/stale/bypass class observation."""

        labels = redact_metric_labels(
            {
                "cache_class": _enum(
                    cache_class, TelemetryCacheClass, "cache_class"
                ).value,
            },
            allowed_keys=_CACHE_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.CACHE_COUNT.value, labels, amount=count
        )

    def record_rejection(
        self,
        *,
        rejection_class: TelemetryRejectionClass | str,
        count: int = 1,
    ) -> None:
        """Record stale/revoked/tampered/simulation/… rejection counts."""

        labels = redact_metric_labels(
            {
                "rejection_class": _enum(
                    rejection_class,
                    TelemetryRejectionClass,
                    "rejection_class",
                ).value,
            },
            allowed_keys=_REJECTION_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.REJECTION_COUNT.value, labels, amount=count
        )

    def record_backend_event(
        self,
        *,
        backend_event: TelemetryBackendEvent | str,
        count: int = 1,
    ) -> None:
        """Record backend availability, timeout, or disagreement."""

        labels = redact_metric_labels(
            {
                "backend_event": _enum(
                    backend_event, TelemetryBackendEvent, "backend_event"
                ).value,
            },
            allowed_keys=_BACKEND_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.BACKEND_EVENT_COUNT.value, labels, amount=count
        )

    def record_adjudication(
        self,
        *,
        adjudication_class: TelemetryAdjudicationClass | str,
        count: int = 1,
    ) -> None:
        """Record review / false-allow / false-deny adjudication rates."""

        labels = redact_metric_labels(
            {
                "adjudication_class": _enum(
                    adjudication_class,
                    TelemetryAdjudicationClass,
                    "adjudication_class",
                ).value,
            },
            allowed_keys=_ADJUDICATION_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.ADJUDICATION_COUNT.value, labels, amount=count
        )

    def record_receipt_event(
        self,
        *,
        receipt_event: TelemetryReceiptEvent | str,
        count: int = 1,
    ) -> None:
        """Record receipt consumption / replay / expiry / TOCTOU events."""

        labels = redact_metric_labels(
            {
                "receipt_event": _enum(
                    receipt_event, TelemetryReceiptEvent, "receipt_event"
                ).value,
            },
            allowed_keys=_RECEIPT_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.RECEIPT_EVENT_COUNT.value, labels, amount=count
        )

    def record_rollout_transition(
        self,
        *,
        from_stage: RolloutStage | str,
        to_stage: RolloutStage | str,
        direction: str,
    ) -> None:
        """Record a validated rollout stage transition (redacted labels only)."""

        direction = _text(direction, "direction", max_chars=32)
        if direction not in {"promote", "demote", "rollback", "disable"}:
            raise TelemetryError(
                "direction must be one of: promote, demote, rollback, disable"
            )
        labels = redact_metric_labels(
            {
                "from_stage": parse_rollout_stage(from_stage).value,
                "to_stage": parse_rollout_stage(to_stage).value,
                "direction": direction,
            },
            allowed_keys=_ROLLOUT_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.ROLLOUT_TRANSITION_COUNT.value, labels
        )

    def record_immediate_disable(self) -> None:
        """Record an immediate receipt-consumption disable event."""

        labels = redact_metric_labels(
            {
                "receipt_event": TelemetryReceiptEvent.DISABLED.value,
            },
            allowed_keys=_RECEIPT_LABEL_KEYS,
        )
        self._record_counter(
            TelemetryMetricName.ROLLOUT_DISABLE_COUNT.value, labels
        )
        self._record_counter(
            TelemetryMetricName.RECEIPT_EVENT_COUNT.value, labels
        )

    # -- snapshots ---------------------------------------------------------

    def counter_value(
        self,
        name: str,
        labels: Mapping[str, str] | None = None,
    ) -> int:
        """Return the accumulated counter for *name* and exact *labels*."""

        redacted = redact_metric_labels(labels or {})
        key = (name, _labels_key(redacted))
        with self._lock:
            return int(self._counters.get(key, 0))

    def latency_stats(
        self,
        name: str,
        labels: Mapping[str, str] | None = None,
    ) -> dict[str, float]:
        """Return count / sum / avg / max for a latency series."""

        redacted = redact_metric_labels(labels or {})
        key = (name, _labels_key(redacted))
        with self._lock:
            count = int(self._latency_counts.get(key, 0))
            total = float(self._latency_sums_ms.get(key, 0.0))
            maximum = float(self._latency_max_ms.get(key, 0.0))
        avg = (total / count) if count else 0.0
        return {
            "avg_ms": avg,
            "count": float(count),
            "max_ms": maximum,
            "sum_ms": total,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a deterministic redacted metrics snapshot."""

        with self._lock:
            counters = [
                {
                    "labels": dict(labels),
                    "name": name,
                    "value": value,
                }
                for (name, labels), value in sorted(
                    self._counters.items(),
                    key=lambda item: (item[0][0], item[0][1]),
                )
            ]
            latencies = []
            for key in sorted(
                self._latency_counts.keys(),
                key=lambda item: (item[0], item[1]),
            ):
                name, labels = key
                count = self._latency_counts[key]
                total = self._latency_sums_ms.get(key, 0.0)
                maximum = self._latency_max_ms.get(key, 0.0)
                latencies.append(
                    {
                        "avg_ms": (total / count) if count else 0.0,
                        "count": count,
                        "labels": dict(labels),
                        "max_ms": maximum,
                        "name": name,
                        "sum_ms": total,
                    }
                )
            return {
                "counters": counters,
                "interface": self.interface,
                "latencies": latencies,
                "schema_version": self.schema_version,
            }

    def reset(self) -> None:
        """Clear all accumulated metrics (test / restart helper)."""

        with self._lock:
            self._counters.clear()
            self._latency_sums_ms.clear()
            self._latency_counts.clear()
            self._latency_max_ms.clear()
            self._samples.clear()

    def to_dict(self) -> dict[str, Any]:
        """Alias for :meth:`snapshot` (interface identity included)."""

        return self.snapshot()


# ---------------------------------------------------------------------------
# Rollout policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RolloutApproval:
    """One human approval bound to a stage transition or scope change."""

    approval_id: str
    approver_role: str
    scope: str
    issued_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "approver_role": self.approver_role,
            "issued_at": self.issued_at,
            "scope": self.scope,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RolloutApproval:
        mapping = _mapping(data, "approval")
        return cls(
            approval_id=_identifier(mapping.get("approval_id"), "approval_id"),
            approver_role=_identifier(
                mapping.get("approver_role"), "approver_role"
            ),
            scope=_text(mapping.get("scope", "stage_transition"), "scope"),
            issued_at=_text(
                mapping.get("issued_at", ""),
                "issued_at",
                allow_empty=True,
                max_chars=64,
            ),
        )


@dataclass(frozen=True, slots=True)
class CanaryScope:
    """Tightly scoped canary cohort definition."""

    cohort_id: str
    owner: str
    duration_seconds: int
    actor_allowlist: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    effect_allowlist: tuple[str, ...] = ()
    reversible_effects_only: bool = True
    max_population: int | None = None

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise RolloutPolicyError("duration_seconds must be non-negative")
        if len(self.effect_allowlist) > MAX_EFFECT_ALLOWLIST:
            raise RolloutPolicyError("effect_allowlist exceeds maximum size")
        if self.max_population is not None and self.max_population < 1:
            raise RolloutPolicyError("max_population must be >= 1 when set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_allowlist": list(self.actor_allowlist),
            "cohort_id": self.cohort_id,
            "duration_seconds": self.duration_seconds,
            "effect_allowlist": list(self.effect_allowlist),
            "max_population": self.max_population,
            "owner": self.owner,
            "reversible_effects_only": self.reversible_effects_only,
            "tool_allowlist": list(self.tool_allowlist),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> CanaryScope | None:
        if data is None:
            return None
        mapping = _mapping(data, "canary_scope")

        def _id_tuple(key: str) -> tuple[str, ...]:
            raw = mapping.get(key, [])
            if raw is None:
                return ()
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise RolloutPolicyError(f"{key} must be a list of identifiers")
            if len(raw) > MAX_EFFECT_ALLOWLIST:
                raise RolloutPolicyError(f"{key} exceeds maximum size")
            return tuple(_identifier(item, f"{key}[]") for item in raw)

        max_pop = mapping.get("max_population")
        return cls(
            cohort_id=_identifier(mapping.get("cohort_id"), "cohort_id"),
            owner=_identifier(mapping.get("owner"), "owner"),
            duration_seconds=_non_negative_int(
                mapping.get("duration_seconds", 0), "duration_seconds"
            ),
            actor_allowlist=_id_tuple("actor_allowlist"),
            tool_allowlist=_id_tuple("tool_allowlist"),
            effect_allowlist=_id_tuple("effect_allowlist"),
            reversible_effects_only=_bool(
                mapping.get("reversible_effects_only", True),
                "reversible_effects_only",
            ),
            max_population=_optional_non_negative_int(
                max_pop, "max_population"
            ),
        )


@dataclass
class AuthorizationRolloutPolicy:
    """Staged rollout controller (``AuthorizationRolloutPolicy@1``).

    Defaults to ``off`` with offline evaluations in ``audit``.  Live stages
    require adjacent transitions, human approvals, and (for allow-token
    stages) an allowlist of reversible effects.  Rollback can immediately
    disable receipt consumption while preserving redacted evidence.
    """

    stage: RolloutStage = DEFAULT_ROLLOUT_STAGE
    offline_stage: RolloutStage = DEFAULT_OFFLINE_STAGE
    receipt_consumption_enabled: bool = False
    require_approvals: bool = True
    require_adjacent_transitions: bool = True
    require_reversible_effects: bool = True
    preserve_evidence_on_rollback: bool = True
    canary_scope: CanaryScope | None = None
    effect_allowlist: tuple[str, ...] = ()
    approvals: list[RolloutApproval] = field(default_factory=list)
    interface: str = AUTHORIZATION_ROLLOUT_POLICY_INTERFACE
    schema_version: str = AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION
    schema: str = ROLLOUT_CONFIG_SCHEMA
    _telemetry: AuthorizationTelemetry | None = field(
        default=None, repr=False, compare=False
    )
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        self.stage = parse_rollout_stage(self.stage)
        self.offline_stage = parse_rollout_stage(self.offline_stage)
        if self.interface != AUTHORIZATION_ROLLOUT_POLICY_INTERFACE:
            raise RolloutPolicyError(
                f"interface must be {AUTHORIZATION_ROLLOUT_POLICY_INTERFACE!r}"
            )
        if self.schema_version != AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION:
            raise RolloutPolicyError(
                "schema_version must be "
                f"{AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION!r}"
            )
        # Safe defaults: off/audit never enable receipt consumption.
        if self.stage in (RolloutStage.OFF, RolloutStage.AUDIT):
            self.receipt_consumption_enabled = False
        if self.stage is RolloutStage.SHADOW:
            # Shadow evaluates only; dispatch consumption stays off.
            self.receipt_consumption_enabled = False
        if not isinstance(self.effect_allowlist, tuple):
            self.effect_allowlist = tuple(self.effect_allowlist)
        if len(self.effect_allowlist) > MAX_EFFECT_ALLOWLIST:
            raise RolloutPolicyError("effect_allowlist exceeds maximum size")

    # -- properties --------------------------------------------------------

    @property
    def stage_value(self) -> str:
        return self.stage.value

    @property
    def is_live_enforcement(self) -> bool:
        return self.stage in _LIVE_EFFECT_STAGES

    @property
    def allows_allow_tokens(self) -> bool:
        return (
            self.stage in _ALLOW_TOKEN_STAGES
            and self.receipt_consumption_enabled
        )

    @property
    def evaluates_offline(self) -> bool:
        return self.stage is not RolloutStage.OFF or (
            self.offline_stage is not RolloutStage.OFF
        )

    # -- transition rules --------------------------------------------------

    def validate_transition(
        self,
        target: RolloutStage | str,
        *,
        approvals: Sequence[RolloutApproval | Mapping[str, Any]] | None = None,
        effect_allowlist: Sequence[str] | None = None,
        canary_scope: CanaryScope | Mapping[str, Any] | None = None,
        enable_receipt_consumption: bool | None = None,
    ) -> RolloutStage:
        """Validate a proposed stage change; return the parsed target.

        Rejects:

        * unknown stages
        * skipped ladder steps when ``require_adjacent_transitions``
        * promotion into live stages without approvals
        * allow-token stages without reversible effect allowlists
        * enabling receipt consumption under off/audit/shadow
        """

        target_stage = parse_rollout_stage(target)
        current = self.stage

        effects = self._merge_effects(effect_allowlist, canary_scope)

        # Receipt-consumption enablement is validated even when the stage
        # does not change (e.g. attempting to enable under shadow).
        if enable_receipt_consumption is True:
            if target_stage not in _ALLOW_TOKEN_STAGES:
                raise RolloutPolicyError(
                    "receipt consumption may only be enabled under "
                    "allow-token-canary or enforce"
                )
            if not effects:
                raise RolloutPolicyError(
                    "receipt consumption requires an effect allowlist"
                )

        if target_stage is current:
            return target_stage

        if self.require_adjacent_transitions and transition_skips_stages(
            current, target_stage
        ):
            raise RolloutPolicyError(
                f"rejected skipped transition from {current.value!r} to "
                f"{target_stage.value!r}; stages must move one step at a time"
            )

        promoting = is_forward_transition(current, target_stage)

        parsed_approvals = self._parse_approvals(approvals)
        if promoting and self.require_approvals:
            if target_stage in _LIVE_EFFECT_STAGES and not parsed_approvals:
                raise RolloutPolicyError(
                    f"promotion to {target_stage.value!r} requires human "
                    "approvals"
                )
            # Any promotion past shadow needs at least one approval when
            # the require_approvals flag is set.
            if (
                stage_index(target_stage) > stage_index(RolloutStage.SHADOW)
                and not parsed_approvals
                and not self.approvals
            ):
                raise RolloutPolicyError(
                    f"promotion to {target_stage.value!r} requires approvals"
                )

        if target_stage in _ALLOW_TOKEN_STAGES:
            if not effects:
                raise RolloutPolicyError(
                    f"stage {target_stage.value!r} requires an allowlisted "
                    "set of reversible effects"
                )
            if self.require_reversible_effects:
                scope = self._coerce_canary_scope(canary_scope)
                if scope is not None and not scope.reversible_effects_only:
                    raise RolloutPolicyError(
                        "allow-token stages require reversible_effects_only"
                    )

        return target_stage

    def transition_to(
        self,
        target: RolloutStage | str,
        *,
        approvals: Sequence[RolloutApproval | Mapping[str, Any]] | None = None,
        effect_allowlist: Sequence[str] | None = None,
        canary_scope: CanaryScope | Mapping[str, Any] | None = None,
        enable_receipt_consumption: bool | None = None,
        direction: str | None = None,
    ) -> RolloutStage:
        """Apply a validated stage transition and emit redacted telemetry."""

        with self._lock:
            previous = self.stage
            target_stage = self.validate_transition(
                target,
                approvals=approvals,
                effect_allowlist=effect_allowlist,
                canary_scope=canary_scope,
                enable_receipt_consumption=enable_receipt_consumption,
            )
            if target_stage is previous:
                return previous

            parsed_approvals = self._parse_approvals(approvals)
            if parsed_approvals:
                # Cap retained approval history.
                combined = list(self.approvals) + parsed_approvals
                self.approvals = combined[-MAX_APPROVAL_IDS:]

            if effect_allowlist is not None:
                self.effect_allowlist = tuple(
                    _identifier(item, "effect_allowlist[]")
                    for item in effect_allowlist
                )
            if canary_scope is not None:
                self.canary_scope = self._coerce_canary_scope(canary_scope)

            # Default consumption: off until explicitly enabled on allow-token
            # stages; always off for off/audit/shadow/deny-canary.
            if target_stage in _ALLOW_TOKEN_STAGES:
                if enable_receipt_consumption is None:
                    # Keep prior value only when already on an allow-token stage.
                    if previous not in _ALLOW_TOKEN_STAGES:
                        self.receipt_consumption_enabled = False
                else:
                    self.receipt_consumption_enabled = bool(
                        enable_receipt_consumption
                    )
            else:
                self.receipt_consumption_enabled = False

            self.stage = target_stage

            if direction is None:
                if is_forward_transition(previous, target_stage):
                    direction = "promote"
                else:
                    direction = "demote"

            if self._telemetry is not None:
                self._telemetry.record_rollout_transition(
                    from_stage=previous,
                    to_stage=target_stage,
                    direction=direction,
                )
            return target_stage

    def immediate_disable_receipt_consumption(
        self,
        *,
        demote_to: RolloutStage | str | None = None,
    ) -> dict[str, Any]:
        """Immediately disable receipt consumption (rollback first step).

        Preserves redacted evidence by default.  Optionally demotes the stage
        toward audit/shadow without re-enabling consumption.
        """

        with self._lock:
            previous_stage = self.stage
            was_enabled = self.receipt_consumption_enabled
            self.receipt_consumption_enabled = False

            if demote_to is not None:
                target = parse_rollout_stage(demote_to)
                # Disable path may jump downward for emergency rollback.
                if stage_index(target) > stage_index(previous_stage):
                    raise RolloutPolicyError(
                        "immediate disable may only demote or hold stage; "
                        "promotion is forbidden"
                    )
                self.stage = target
                # Off/audit/shadow already force consumption false above.
                if self.stage in _ALLOW_TOKEN_STAGES:
                    self.receipt_consumption_enabled = False

            if self._telemetry is not None:
                self._telemetry.record_immediate_disable()
                if demote_to is not None and self.stage is not previous_stage:
                    self._telemetry.record_rollout_transition(
                        from_stage=previous_stage,
                        to_stage=self.stage,
                        direction="disable",
                    )

            return {
                "evidence_preserved": self.preserve_evidence_on_rollback,
                "previous_receipt_consumption_enabled": was_enabled,
                "previous_stage": previous_stage.value,
                "receipt_consumption_enabled": self.receipt_consumption_enabled,
                "stage": self.stage.value,
            }

    def effect_is_allowlisted(self, effect_id: str) -> bool:
        """Return True when *effect_id* is on the active reversible allowlist."""

        effect = _identifier(effect_id, "effect_id")
        with self._lock:
            if effect in self.effect_allowlist:
                return True
            if self.canary_scope is not None:
                return effect in self.canary_scope.effect_allowlist
            return False

    def attach_telemetry(self, telemetry: AuthorizationTelemetry) -> None:
        """Bind a telemetry sink for transition / disable observations."""

        if not isinstance(telemetry, AuthorizationTelemetry):
            raise TelemetryError(
                "telemetry must be an AuthorizationTelemetry instance"
            )
        self._telemetry = telemetry

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "approvals": [item.to_dict() for item in self.approvals],
                "canary_scope": (
                    self.canary_scope.to_dict()
                    if self.canary_scope is not None
                    else None
                ),
                "effect_allowlist": list(self.effect_allowlist),
                "interface": self.interface,
                "offline_stage": self.offline_stage.value,
                "preserve_evidence_on_rollback": (
                    self.preserve_evidence_on_rollback
                ),
                "receipt_consumption_enabled": (
                    self.receipt_consumption_enabled
                ),
                "require_adjacent_transitions": (
                    self.require_adjacent_transitions
                ),
                "require_approvals": self.require_approvals,
                "require_reversible_effects": self.require_reversible_effects,
                "schema": self.schema,
                "schema_version": self.schema_version,
                "stage": self.stage.value,
            }

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        telemetry: AuthorizationTelemetry | None = None,
    ) -> AuthorizationRolloutPolicy:
        """Build a policy from a config mapping (JSON object)."""

        mapping = _mapping(data, "rollout config")
        schema = mapping.get("schema", ROLLOUT_CONFIG_SCHEMA)
        if schema != ROLLOUT_CONFIG_SCHEMA:
            raise RolloutPolicyError(
                f"unsupported rollout config schema {schema!r}"
            )

        interface = mapping.get(
            "interface", AUTHORIZATION_ROLLOUT_POLICY_INTERFACE
        )
        schema_version = mapping.get(
            "schema_version", AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION
        )

        approvals_raw = mapping.get("approvals") or []
        if not isinstance(approvals_raw, Sequence) or isinstance(
            approvals_raw, (str, bytes)
        ):
            raise RolloutPolicyError("approvals must be a list")
        approvals = [
            RolloutApproval.from_mapping(item) for item in approvals_raw
        ]

        effects_raw = mapping.get("effect_allowlist") or []
        if not isinstance(effects_raw, Sequence) or isinstance(
            effects_raw, (str, bytes)
        ):
            raise RolloutPolicyError("effect_allowlist must be a list")
        effect_allowlist = tuple(
            _identifier(item, "effect_allowlist[]") for item in effects_raw
        )

        policy = cls(
            stage=parse_rollout_stage(mapping.get("stage", DEFAULT_ROLLOUT_STAGE)),
            offline_stage=parse_rollout_stage(
                mapping.get("offline_stage", DEFAULT_OFFLINE_STAGE)
            ),
            receipt_consumption_enabled=_bool(
                mapping.get("receipt_consumption_enabled", False),
                "receipt_consumption_enabled",
            ),
            require_approvals=_bool(
                mapping.get("require_approvals", True), "require_approvals"
            ),
            require_adjacent_transitions=_bool(
                mapping.get("require_adjacent_transitions", True),
                "require_adjacent_transitions",
            ),
            require_reversible_effects=_bool(
                mapping.get("require_reversible_effects", True),
                "require_reversible_effects",
            ),
            preserve_evidence_on_rollback=_bool(
                mapping.get("preserve_evidence_on_rollback", True),
                "preserve_evidence_on_rollback",
            ),
            canary_scope=CanaryScope.from_mapping(
                mapping.get("canary_scope")
            ),
            effect_allowlist=effect_allowlist,
            approvals=list(approvals),
            interface=str(interface),
            schema_version=str(schema_version),
            schema=str(schema),
        )
        if telemetry is not None:
            policy.attach_telemetry(telemetry)
        # Re-apply safe consumption defaults after load.
        if policy.stage not in _ALLOW_TOKEN_STAGES:
            policy.receipt_consumption_enabled = False
        return policy

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _parse_approvals(
        approvals: Sequence[RolloutApproval | Mapping[str, Any]] | None,
    ) -> list[RolloutApproval]:
        if approvals is None:
            return []
        parsed: list[RolloutApproval] = []
        for item in approvals:
            if isinstance(item, RolloutApproval):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(RolloutApproval.from_mapping(item))
            else:
                raise RolloutPolicyError(
                    "approvals entries must be mappings or RolloutApproval"
                )
        if len(parsed) > MAX_APPROVAL_IDS:
            raise RolloutPolicyError("approvals exceeds maximum size")
        return parsed

    def _merge_effects(
        self,
        effect_allowlist: Sequence[str] | None,
        canary_scope: CanaryScope | Mapping[str, Any] | None,
    ) -> tuple[str, ...]:
        effects: list[str] = list(self.effect_allowlist)
        if effect_allowlist is not None:
            effects.extend(
                _identifier(item, "effect_allowlist[]")
                for item in effect_allowlist
            )
        scope = self._coerce_canary_scope(canary_scope)
        if scope is None:
            scope = self.canary_scope
        if scope is not None:
            effects.extend(scope.effect_allowlist)
        # De-dupe preserving order.
        seen: set[str] = set()
        ordered: list[str] = []
        for item in effects:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return tuple(ordered)

    @staticmethod
    def _coerce_canary_scope(
        canary_scope: CanaryScope | Mapping[str, Any] | None,
    ) -> CanaryScope | None:
        if canary_scope is None:
            return None
        if isinstance(canary_scope, CanaryScope):
            return canary_scope
        return CanaryScope.from_mapping(canary_scope)


# ---------------------------------------------------------------------------
# Config load helpers
# ---------------------------------------------------------------------------


def default_rollout_policy(
    *,
    telemetry: AuthorizationTelemetry | None = None,
) -> AuthorizationRolloutPolicy:
    """Return the fail-closed default policy (``off`` / offline ``audit``)."""

    policy = AuthorizationRolloutPolicy(
        stage=DEFAULT_ROLLOUT_STAGE,
        offline_stage=DEFAULT_OFFLINE_STAGE,
        receipt_consumption_enabled=False,
        require_approvals=True,
        require_adjacent_transitions=True,
        require_reversible_effects=True,
        preserve_evidence_on_rollback=True,
    )
    if telemetry is not None:
        policy.attach_telemetry(telemetry)
    return policy


def load_rollout_policy(
    path: str | Path | None = None,
    *,
    telemetry: AuthorizationTelemetry | None = None,
) -> AuthorizationRolloutPolicy:
    """Load and validate a rollout policy JSON document.

    When *path* is ``None``, attempts ``config/intent_authorization_rollout.json``
    relative to the process working directory, then falls back to defaults.
    """

    if path is None:
        candidate = Path(DEFAULT_ROLLOUT_CONFIG_RELATIVE)
        if not candidate.is_file():
            return default_rollout_policy(telemetry=telemetry)
        path = candidate

    config_path = Path(path)
    if not config_path.is_file():
        raise RolloutPolicyError(
            f"rollout config not found: {config_path}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RolloutPolicyError(
            f"failed to load rollout config from {config_path}: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise RolloutPolicyError("rollout config root must be a JSON object")
    return AuthorizationRolloutPolicy.from_mapping(raw, telemetry=telemetry)


def rollout_policy_from_json(
    text: str,
    *,
    telemetry: AuthorizationTelemetry | None = None,
) -> AuthorizationRolloutPolicy:
    """Parse a rollout policy from a JSON string."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RolloutPolicyError(f"invalid rollout JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise RolloutPolicyError("rollout config root must be a JSON object")
    return AuthorizationRolloutPolicy.from_mapping(raw, telemetry=telemetry)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "AUTHORIZATION_ROLLOUT_POLICY_INTERFACE",
    "AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION",
    "AUTHORIZATION_TELEMETRY_INTERFACE",
    "AUTHORIZATION_TELEMETRY_SCHEMA_VERSION",
    "AuthorizationRolloutPolicy",
    "AuthorizationTelemetry",
    "CanaryScope",
    "DEFAULT_OFFLINE_STAGE",
    "DEFAULT_ROLLOUT_CONFIG_RELATIVE",
    "DEFAULT_ROLLOUT_STAGE",
    "ForbiddenTelemetryLabelError",
    "MetricSample",
    "ROLLOUT_CONFIG_SCHEMA",
    "ROLLOUT_STAGE_ORDER",
    "ROLLOUT_STAGE_WIRE_VALUES",
    "RolloutApproval",
    "RolloutPolicyError",
    "RolloutStage",
    "STANDARD_METRIC_NAMES",
    "TelemetryAdjudicationClass",
    "TelemetryBackendEvent",
    "TelemetryCacheClass",
    "TelemetryError",
    "TelemetryFilterClass",
    "TelemetryMetricName",
    "TelemetryOutcome",
    "TelemetryPolicyProfile",
    "TelemetryProofAuthority",
    "TelemetryReceiptEvent",
    "TelemetryRejectionClass",
    "TelemetrySourceKind",
    "default_rollout_policy",
    "is_adjacent_transition",
    "is_forbidden_telemetry_label",
    "is_forward_transition",
    "load_rollout_policy",
    "parse_rollout_stage",
    "redact_metric_labels",
    "rollout_policy_from_json",
    "stage_index",
    "transition_skips_stages",
]
