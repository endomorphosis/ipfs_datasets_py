"""Executable, receipt-bound gold-corpus metrics for USPTO processors (PATLAW-123).

This module turns reviewer-labeled gold annotations and actual processor
outputs into versioned metric observations and content-addressed evaluation
receipts. It is deliberately offline: no network I/O, no package re-exports,
and no silent relaxation of thresholds.

Design rules (acceptance-binding):

* Intentionally degraded outputs fail their corresponding metric.
* Thresholds are versioned (gates schema + digest) and compared to observed
  values with fail-closed operators.
* Receipts bind corpus / parser / ruleset / model / config identities.
* Missing labels or unmeasurable cases produce explicit
  ``unknown`` / ``not_applicable`` counts — never automatic passes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    canonical_json,
)

# ---------------------------------------------------------------------------
# Schema / interface identity
# ---------------------------------------------------------------------------

EVALUATION_SCHEMA_VERSION: Final = "uspto.gold-evaluation.v1"
EVALUATION_INTERFACE: Final = "UsptoGoldEvaluator@1"
OBSERVED_METRICS_SCHEMA: Final = "uspto.gold-observed-metrics.v1"
OBSERVED_METRICS_SCHEMA_VERSION: Final = 1
GATES_SCHEMA: Final = "uspto.gold-metric-gates.v1"
ANNOTATION_SCHEMA: Final = "uspto.gold-annotation.v1"
CASE_SCHEMA: Final = "uspto.gold-case-recipe.v1"
MANIFEST_SCHEMA: Final = "uspto.gold-corpus-manifest.v1"

SCHEMA_VERSION: Final = EVALUATION_SCHEMA_VERSION

DEFAULT_THRESHOLDS_VERSION: Final = "uspto.gold-metric-gates.v1@1"
DEFAULT_CORPUS_ID: Final = "uspto-reviewed-gold-v1"

# Gate ids from the reviewed metric_gates fixture (release-assurance core).
GATE_REQUIREMENT_RECALL: Final = "requirement_recall"
GATE_CITATION_RECALL: Final = "citation_recall"
GATE_EVIDENCE_PRECISION: Final = "evidence_precision"
GATE_PROVENANCE_COMPLETENESS: Final = "provenance_completeness"
GATE_FALSE_NEGATIVE_BUDGET: Final = "false_negative_budget"

# Extended executable families (Effects / PATLAW-G151).
METRIC_DOCUMENT_CLASSIFICATION: Final = "document_classification"
METRIC_SPAN: Final = "span_recall"
METRIC_SEMANTIC_FIELD: Final = "semantic_field_accuracy"
METRIC_CITATION: Final = "citation_recall"
METRIC_OBLIGATION: Final = "obligation_recall"
METRIC_CONTRADICTION: Final = "contradiction_detection"
METRIC_DEADLINE: Final = "deadline_recall"
METRIC_PRIVACY: Final = "privacy_isolation"
METRIC_DETERMINISM: Final = "determinism"
METRIC_E2E_COMPLETENESS: Final = "end_to_end_completeness"

REQUIRED_GATE_IDS: Final[frozenset[str]] = frozenset(
    {
        GATE_REQUIREMENT_RECALL,
        GATE_CITATION_RECALL,
        GATE_EVIDENCE_PRECISION,
        GATE_PROVENANCE_COMPLETENESS,
        GATE_FALSE_NEGATIVE_BUDGET,
    }
)

REQUIRED_EXTENDED_METRIC_IDS: Final[frozenset[str]] = frozenset(
    {
        METRIC_DOCUMENT_CLASSIFICATION,
        METRIC_SPAN,
        METRIC_SEMANTIC_FIELD,
        METRIC_OBLIGATION,
        METRIC_CONTRADICTION,
        METRIC_DEADLINE,
        METRIC_PRIVACY,
        METRIC_DETERMINISM,
        METRIC_E2E_COMPLETENESS,
    }
)

# All metric ids emitted on a full corpus evaluation receipt.
REQUIRED_RECEIPT_METRIC_IDS: Final[frozenset[str]] = (
    REQUIRED_GATE_IDS | REQUIRED_EXTENDED_METRIC_IDS
)

PROVENANCE_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "artifact_id",
    "source_receipt_id",
    "span_id",
    "page_index",
    "origin",
    "classification",
)

_SHA256_HEX_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_CITATION_WS_RE = re.compile(r"\s+")


class EvaluationError(ValueError):
    """Base error for gold evaluation contract violations."""


class MetricThresholdError(EvaluationError):
    """Raised when a measurable metric fails its versioned threshold."""


class MetricStatus(str, Enum):
    """Outcome of one metric observation.

    ``unknown`` and ``not_applicable`` are first-class; they must never be
    coerced into a pass.
    """

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class MetricFamily(str, Enum):
    """Metric families spanning release gates and extended executable checks."""

    RECALL = "recall"
    PRECISION = "precision"
    PROVENANCE = "provenance"
    FALSE_NEGATIVE = "false_negative"
    DOCUMENT_CLASSIFICATION = "document_classification"
    SPAN = "span"
    SEMANTIC_FIELD = "semantic_field"
    CITATION = "citation"
    OBLIGATION = "obligation"
    CONTRADICTION = "contradiction"
    DEADLINE = "deadline"
    PRIVACY = "privacy"
    DETERMINISM = "determinism"
    END_TO_END_COMPLETENESS = "end_to_end_completeness"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    """Return lowercase hex SHA-256 of *data* (UTF-8 when str)."""
    if isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
    else:
        raise TypeError(f"sha256_hex expects bytes or str, got {type(data).__name__}")
    return hashlib.sha256(payload).hexdigest()


def content_digest(value: Any) -> str:
    """Content-address a JSON-serializable value via canonical_json + SHA-256."""
    return sha256_hex(canonical_json(value))


def digest_uri(hex_digest: str) -> str:
    """Format a digest as ``sha256:<hex>``."""
    text = _require_sha256_hex(hex_digest, "digest")
    return f"sha256:{text}"


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _require_sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=80).lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not _SHA256_HEX_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _optional_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field)


def _coerce_status(value: Any) -> MetricStatus:
    if isinstance(value, MetricStatus):
        return value
    if isinstance(value, str):
        try:
            return MetricStatus(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid metric status: {value!r}") from exc
    raise TypeError(f"status must be MetricStatus or str, got {type(value).__name__}")


def _coerce_family(value: Any) -> MetricFamily:
    if isinstance(value, MetricFamily):
        return value
    if isinstance(value, str):
        try:
            return MetricFamily(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid metric family: {value!r}") from exc
    raise TypeError(f"family must be MetricFamily or str, got {type(value).__name__}")


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field} key", max_len=128)
        if k in out:
            raise ValueError(f"{field} has duplicate key {k!r}")
        out[k] = _require_str(raw, f"{field}[{k}]", max_len=2048)
    return MappingProxyType(dict(sorted(out.items())))


def normalize_citation(text: str) -> str:
    """Normalize a legal citation string for recall matching."""
    cleaned = _CITATION_WS_RE.sub(" ", text.strip())
    cleaned = cleaned.replace("U.S.C.", "USC").replace("C.F.R.", "CFR")
    cleaned = cleaned.replace("§", " ").replace("  ", " ")
    return cleaned.casefold().strip()


def compare_threshold(
    observed: float,
    *,
    operator: str,
    threshold: float,
) -> bool:
    """Return True when *observed* satisfies *operator* *threshold*."""
    op = operator.strip()
    if op == ">=":
        return observed + 1e-12 >= threshold
    if op == "<=":
        return observed - 1e-12 <= threshold
    if op == ">":
        return observed > threshold
    if op == "<":
        return observed < threshold
    if op == "==":
        return abs(observed - threshold) <= 1e-12
    raise ValueError(f"unsupported threshold operator: {operator!r}")


def default_gold_root() -> Path:
    """Repository-relative default path to the reviewed gold corpus root."""
    # evaluation.py → uspto → domains → processors → ipfs_datasets_py → repo root
    repo = Path(__file__).resolve().parents[4]
    return repo / "tests" / "fixtures" / "uspto" / "gold"


def default_uspto_fixture_root() -> Path:
    return default_gold_root().parent


# ---------------------------------------------------------------------------
# Thresholds (versioned gates)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateSpec:
    """One versioned release-assurance gate."""

    gate_id: str
    metric_id: str
    family: MetricFamily
    operator: str
    threshold: float
    fail_closed: bool
    aggregation: str
    definition: str
    numerator: str
    denominator: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregation": self.aggregation,
            "definition": self.definition,
            "denominator": self.denominator,
            "fail_closed": self.fail_closed,
            "family": self.family.value,
            "gate_id": self.gate_id,
            "metric_id": self.metric_id,
            "numerator": self.numerator,
            "operator": self.operator,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class MetricThresholds:
    """Versioned thresholds loaded from ``metric_gates.json`` (or equivalent)."""

    schema: str
    schema_version: int
    thresholds_version: str
    thresholds_digest: str
    gates: Mapping[str, GateSpec]
    matching: Mapping[str, Any]
    task_id: str | None = None
    goal_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema", _require_str(self.schema, "schema", max_len=128))
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise TypeError("schema_version must be int")
        if self.schema_version < 1:
            raise ValueError("schema_version must be >= 1")
        object.__setattr__(
            self,
            "thresholds_version",
            _require_str(self.thresholds_version, "thresholds_version", max_len=128),
        )
        object.__setattr__(
            self,
            "thresholds_digest",
            digest_uri(_require_sha256_hex(self.thresholds_digest, "thresholds_digest")),
        )
        if not isinstance(self.gates, Mapping) or not self.gates:
            raise ValueError("gates must be a non-empty mapping")
        frozen_gates = MappingProxyType(dict(self.gates))
        object.__setattr__(self, "gates", frozen_gates)
        object.__setattr__(
            self,
            "matching",
            MappingProxyType(dict(self.matching)) if isinstance(self.matching, Mapping) else MappingProxyType({}),
        )

    def gate(self, gate_id: str) -> GateSpec:
        if gate_id not in self.gates:
            raise KeyError(f"unknown gate_id: {gate_id}")
        return self.gates[gate_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gates": {k: v.to_dict() for k, v in sorted(self.gates.items())},
            "goal_id": self.goal_id,
            "matching": dict(self.matching),
            "schema": self.schema,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "thresholds_digest": self.thresholds_digest,
            "thresholds_version": self.thresholds_version,
        }


def load_metric_gates(path: Path | str | None = None) -> MetricThresholds:
    """Load and pin versioned metric gates from the gold fixture."""
    if path is None:
        path = default_gold_root() / "metrics" / "metric_gates.json"
    gates_path = Path(path)
    raw_bytes = gates_path.read_bytes()
    data = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(data, dict):
        raise EvaluationError("metric gates root must be an object")
    schema = data.get("schema")
    if schema != GATES_SCHEMA:
        raise EvaluationError(f"metric gates schema must be {GATES_SCHEMA}, got {schema!r}")
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise EvaluationError(f"unsupported metric gates schema_version: {schema_version!r}")

    gates_raw = data.get("gates")
    if not isinstance(gates_raw, Mapping):
        raise EvaluationError("metric gates.gates must be a mapping")

    family_map = {
        "recall": MetricFamily.RECALL,
        "precision": MetricFamily.PRECISION,
        "provenance": MetricFamily.PROVENANCE,
        "false_negative": MetricFamily.FALSE_NEGATIVE,
    }
    gates: dict[str, GateSpec] = {}
    for gate_id, spec in gates_raw.items():
        if not isinstance(spec, Mapping):
            raise EvaluationError(f"gate {gate_id!r} must be a mapping")
        family_raw = str(spec.get("family", "")).strip()
        if family_raw not in family_map:
            raise EvaluationError(f"gate {gate_id!r} has unsupported family {family_raw!r}")
        operator = str(spec.get("operator", "")).strip()
        if operator not in {">=", "<=", ">", "<", "=="}:
            raise EvaluationError(f"gate {gate_id!r} has invalid operator {operator!r}")
        threshold = _finite_float(spec.get("threshold"), f"gates[{gate_id}].threshold")
        if not 0.0 <= threshold <= 1.0:
            raise EvaluationError(f"gate {gate_id!r} threshold must be in [0,1]")
        fail_closed = spec.get("fail_closed")
        if fail_closed is not True:
            raise EvaluationError(f"gate {gate_id!r} must be fail_closed=true")
        gates[str(gate_id)] = GateSpec(
            gate_id=str(gate_id),
            metric_id=str(spec.get("metric_id") or gate_id),
            family=family_map[family_raw],
            operator=operator,
            threshold=threshold,
            fail_closed=True,
            aggregation=str(spec.get("aggregation") or "micro"),
            definition=str(spec.get("definition") or ""),
            numerator=str(spec.get("numerator") or ""),
            denominator=str(spec.get("denominator") or ""),
        )

    missing = REQUIRED_GATE_IDS - set(gates)
    if missing:
        raise EvaluationError(
            "metric gates missing required gate ids: " + ", ".join(sorted(missing))
        )

    thresholds_version = f"{schema}@{schema_version}"
    thresholds_digest = sha256_hex(raw_bytes)
    matching = data.get("matching") if isinstance(data.get("matching"), Mapping) else {}

    return MetricThresholds(
        schema=schema,
        schema_version=int(schema_version),
        thresholds_version=thresholds_version,
        thresholds_digest=thresholds_digest,
        gates=gates,
        matching=dict(matching),
        task_id=_optional_str(data.get("task_id"), "task_id"),
        goal_id=_optional_str(data.get("goal_id"), "goal_id"),
    )


# ---------------------------------------------------------------------------
# Observed metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedMetric:
    """One executable metric observation (schema: observed_metrics)."""

    metric_id: str
    family: MetricFamily
    status: MetricStatus
    value: float | None
    operator: str | None
    threshold: float | None
    threshold_version: str | None
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    unknown_count: int = 0
    not_applicable_count: int = 0
    numerator: int | None = None
    denominator: int | None = None
    details: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _identifier(self.metric_id, "metric_id"))
        object.__setattr__(self, "family", _coerce_family(self.family))
        object.__setattr__(self, "status", _coerce_status(self.status))
        object.__setattr__(self, "value", _optional_float(self.value, "value"))
        if self.operator is not None:
            object.__setattr__(
                self, "operator", _require_str(self.operator, "operator", max_len=8)
            )
        object.__setattr__(
            self, "threshold", _optional_float(self.threshold, "threshold")
        )
        if self.threshold_version is not None:
            object.__setattr__(
                self,
                "threshold_version",
                _require_str(self.threshold_version, "threshold_version", max_len=128),
            )
        for name in (
            "true_positives",
            "false_positives",
            "false_negatives",
            "unknown_count",
            "not_applicable_count",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        if self.numerator is not None:
            object.__setattr__(
                self, "numerator", _nonneg_int(self.numerator, "numerator")
            )
        if self.denominator is not None:
            object.__setattr__(
                self, "denominator", _nonneg_int(self.denominator, "denominator")
            )
        object.__setattr__(
            self, "details", _frozen_str_map(self.details, "details", max_items=64)
        )
        # Fail-closed: non-measurable statuses must not carry a "pass" value
        # pretence — value may still be recorded for diagnostics, but status
        # must not be PASS when unknown/not_applicable counts dominate without
        # a measurable comparison. Enforced by factory helpers below.

    @property
    def is_measurable(self) -> bool:
        return self.status in {MetricStatus.PASS, MetricStatus.FAIL}

    @property
    def passed(self) -> bool | None:
        if self.status is MetricStatus.PASS:
            return True
        if self.status is MetricStatus.FAIL:
            return False
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "denominator": self.denominator,
            "details": dict(self.details),
            "family": self.family.value,
            "false_negatives": self.false_negatives,
            "false_positives": self.false_positives,
            "metric_id": self.metric_id,
            "not_applicable_count": self.not_applicable_count,
            "numerator": self.numerator,
            "operator": self.operator,
            "status": self.status.value,
            "threshold": self.threshold,
            "threshold_version": self.threshold_version,
            "true_positives": self.true_positives,
            "unknown_count": self.unknown_count,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObservedMetric":
        value = _mapping(value, "ObservedMetric")
        return cls(
            metric_id=value.get("metric_id", ""),
            family=value.get("family", MetricFamily.RECALL.value),
            status=value.get("status", MetricStatus.UNKNOWN.value),
            value=value.get("value"),
            operator=value.get("operator"),
            threshold=value.get("threshold"),
            threshold_version=value.get("threshold_version"),
            true_positives=int(value.get("true_positives") or 0),
            false_positives=int(value.get("false_positives") or 0),
            false_negatives=int(value.get("false_negatives") or 0),
            unknown_count=int(value.get("unknown_count") or 0),
            not_applicable_count=int(value.get("not_applicable_count") or 0),
            numerator=value.get("numerator"),
            denominator=value.get("denominator"),
            details=value.get("details") or {},
        )


def _ratio_metric(
    *,
    metric_id: str,
    family: MetricFamily,
    numerator: int,
    denominator: int,
    operator: str | None,
    threshold: float | None,
    threshold_version: str | None,
    true_positives: int = 0,
    false_positives: int = 0,
    false_negatives: int = 0,
    unknown_count: int = 0,
    not_applicable_count: int = 0,
    details: Mapping[str, str] | None = None,
    unmeasurable_status: MetricStatus = MetricStatus.NOT_APPLICABLE,
) -> ObservedMetric:
    """Build a ratio metric; zero denominator → unknown/not_applicable (never pass)."""
    if denominator < 0 or numerator < 0:
        raise EvaluationError("numerator/denominator must be non-negative")
    if denominator == 0:
        return ObservedMetric(
            metric_id=metric_id,
            family=family,
            status=unmeasurable_status,
            value=None,
            operator=operator,
            threshold=threshold,
            threshold_version=threshold_version,
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            unknown_count=unknown_count,
            not_applicable_count=max(not_applicable_count, 1),
            numerator=numerator,
            denominator=denominator,
            details=details or {"reason": "zero_denominator"},
        )
    value = float(numerator) / float(denominator)
    if operator is None or threshold is None:
        # Measurable ratio without a gate → report unknown (no silent pass).
        return ObservedMetric(
            metric_id=metric_id,
            family=family,
            status=MetricStatus.UNKNOWN,
            value=value,
            operator=operator,
            threshold=threshold,
            threshold_version=threshold_version,
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            unknown_count=max(unknown_count, 1),
            not_applicable_count=not_applicable_count,
            numerator=numerator,
            denominator=denominator,
            details=details or {"reason": "no_threshold"},
        )
    ok = compare_threshold(value, operator=operator, threshold=threshold)
    return ObservedMetric(
        metric_id=metric_id,
        family=family,
        status=MetricStatus.PASS if ok else MetricStatus.FAIL,
        value=value,
        operator=operator,
        threshold=threshold,
        threshold_version=threshold_version,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        unknown_count=unknown_count,
        not_applicable_count=not_applicable_count,
        numerator=numerator,
        denominator=denominator,
        details=details or {},
    )


def _binary_metric(
    *,
    metric_id: str,
    family: MetricFamily,
    success: bool | None,
    threshold_version: str | None,
    unknown_count: int = 0,
    not_applicable_count: int = 0,
    details: Mapping[str, str] | None = None,
) -> ObservedMetric:
    """success=True→pass (value 1), False→fail (0), None→unknown/n/a."""
    if success is None:
        status = (
            MetricStatus.NOT_APPLICABLE
            if not_applicable_count > 0
            else MetricStatus.UNKNOWN
        )
        return ObservedMetric(
            metric_id=metric_id,
            family=family,
            status=status,
            value=None,
            operator="==",
            threshold=1.0,
            threshold_version=threshold_version,
            unknown_count=max(unknown_count, 1 if status is MetricStatus.UNKNOWN else 0),
            not_applicable_count=max(
                not_applicable_count, 1 if status is MetricStatus.NOT_APPLICABLE else 0
            ),
            numerator=None,
            denominator=None,
            details=details or {},
        )
    return ObservedMetric(
        metric_id=metric_id,
        family=family,
        status=MetricStatus.PASS if success else MetricStatus.FAIL,
        value=1.0 if success else 0.0,
        operator="==",
        threshold=1.0,
        threshold_version=threshold_version,
        true_positives=1 if success else 0,
        false_negatives=0 if success else 1,
        unknown_count=unknown_count,
        not_applicable_count=not_applicable_count,
        numerator=1 if success else 0,
        denominator=1,
        details=details or {},
    )


# ---------------------------------------------------------------------------
# Identity + receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvaluationIdentity:
    """Bound identities for a receipt (corpus/parser/ruleset/model/config)."""

    corpus_id: str
    corpus_digest: str
    parser_id: str
    parser_digest: str
    ruleset_id: str
    ruleset_digest: str
    model_id: str
    model_digest: str
    config_id: str
    config_digest: str
    thresholds_version: str
    thresholds_digest: str

    def __post_init__(self) -> None:
        for name in (
            "corpus_id",
            "parser_id",
            "ruleset_id",
            "model_id",
            "config_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "corpus_digest",
            "parser_digest",
            "ruleset_digest",
            "model_digest",
            "config_digest",
            "thresholds_digest",
        ):
            object.__setattr__(
                self, name, digest_uri(_require_sha256_hex(getattr(self, name), name))
            )
        object.__setattr__(
            self,
            "thresholds_version",
            _require_str(self.thresholds_version, "thresholds_version", max_len=128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_digest": self.config_digest,
            "config_id": self.config_id,
            "corpus_digest": self.corpus_digest,
            "corpus_id": self.corpus_id,
            "model_digest": self.model_digest,
            "model_id": self.model_id,
            "parser_digest": self.parser_digest,
            "parser_id": self.parser_id,
            "ruleset_digest": self.ruleset_digest,
            "ruleset_id": self.ruleset_id,
            "thresholds_digest": self.thresholds_digest,
            "thresholds_version": self.thresholds_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationIdentity":
        value = _mapping(value, "EvaluationIdentity")
        return cls(
            corpus_id=value.get("corpus_id", ""),
            corpus_digest=value.get("corpus_digest", ""),
            parser_id=value.get("parser_id", ""),
            parser_digest=value.get("parser_digest", ""),
            ruleset_id=value.get("ruleset_id", ""),
            ruleset_digest=value.get("ruleset_digest", ""),
            model_id=value.get("model_id", ""),
            model_digest=value.get("model_digest", ""),
            config_id=value.get("config_id", ""),
            config_digest=value.get("config_digest", ""),
            thresholds_version=value.get("thresholds_version", ""),
            thresholds_digest=value.get("thresholds_digest", ""),
        )


@dataclass(frozen=True, slots=True)
class GoldEvaluationReceipt:
    """Content-addressed evaluation receipt for gold-corpus metrics."""

    schema_version: str
    observed_metrics_schema: str
    receipt_id: str
    receipt_digest: str
    identity: EvaluationIdentity
    metrics: tuple[ObservedMetric, ...]
    case_ids: tuple[str, ...]
    annotations_digest: str
    outputs_digest: str
    contracts_schema_version: str
    evaluated_at_utc: str | None
    pass_count: int
    fail_count: int
    unknown_count: int
    not_applicable_count: int
    passed: bool
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=128),
        )
        if self.schema_version != EVALUATION_SCHEMA_VERSION:
            raise EvaluationError(
                f"receipt schema_version must be {EVALUATION_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self,
            "observed_metrics_schema",
            _require_str(
                self.observed_metrics_schema, "observed_metrics_schema", max_len=128
            ),
        )
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "receipt_digest",
            digest_uri(_require_sha256_hex(self.receipt_digest, "receipt_digest")),
        )
        if not isinstance(self.identity, EvaluationIdentity):
            if isinstance(self.identity, Mapping):
                object.__setattr__(
                    self, "identity", EvaluationIdentity.from_dict(self.identity)
                )
            else:
                raise TypeError("identity must be EvaluationIdentity or mapping")
        metrics_out: list[ObservedMetric] = []
        for i, item in enumerate(self.metrics):
            if isinstance(item, ObservedMetric):
                metrics_out.append(item)
            elif isinstance(item, Mapping):
                metrics_out.append(ObservedMetric.from_dict(item))
            else:
                raise TypeError(f"metrics[{i}] must be ObservedMetric or mapping")
        object.__setattr__(self, "metrics", tuple(metrics_out))
        case_ids = tuple(
            _identifier(c, f"case_ids[{i}]") for i, c in enumerate(self.case_ids)
        )
        object.__setattr__(self, "case_ids", case_ids)
        object.__setattr__(
            self,
            "annotations_digest",
            digest_uri(_require_sha256_hex(self.annotations_digest, "annotations_digest")),
        )
        object.__setattr__(
            self,
            "outputs_digest",
            digest_uri(_require_sha256_hex(self.outputs_digest, "outputs_digest")),
        )
        object.__setattr__(
            self,
            "contracts_schema_version",
            _require_str(
                self.contracts_schema_version, "contracts_schema_version", max_len=64
            ),
        )
        if self.evaluated_at_utc is not None:
            object.__setattr__(
                self,
                "evaluated_at_utc",
                _require_str(self.evaluated_at_utc, "evaluated_at_utc", max_len=64),
            )
        for name in (
            "pass_count",
            "fail_count",
            "unknown_count",
            "not_applicable_count",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be bool")
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def metric(self, metric_id: str) -> ObservedMetric:
        for item in self.metrics:
            if item.metric_id == metric_id:
                return item
        raise KeyError(f"metric not present on receipt: {metric_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotations_digest": self.annotations_digest,
            "case_ids": list(self.case_ids),
            "contracts_schema_version": self.contracts_schema_version,
            "evaluated_at_utc": self.evaluated_at_utc,
            "fail_count": self.fail_count,
            "identity": self.identity.to_dict(),
            "metadata": dict(self.metadata),
            "metrics": [m.to_dict() for m in self.metrics],
            "not_applicable_count": self.not_applicable_count,
            "observed_metrics_schema": self.observed_metrics_schema,
            "outputs_digest": self.outputs_digest,
            "pass_count": self.pass_count,
            "passed": self.passed,
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "unknown_count": self.unknown_count,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def _receipt_body_for_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strip self-referential digest fields before content-addressing."""
    body = dict(payload)
    body.pop("receipt_digest", None)
    return body


def build_receipt_digest(payload: Mapping[str, Any]) -> str:
    """Compute content address of a receipt body (without receipt_digest)."""
    return digest_uri(content_digest(_receipt_body_for_digest(payload)))


# ---------------------------------------------------------------------------
# Gold case loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoldCase:
    """One reviewed gold case recipe + annotation pair."""

    case_id: str
    case: Mapping[str, Any]
    annotation: Mapping[str, Any]

    @property
    def classification(self) -> str:
        return str(self.case.get("classification") or "unknown")

    @property
    def privacy_class(self) -> str:
        source = self.case.get("source") if isinstance(self.case.get("source"), Mapping) else {}
        return str(source.get("privacy_class") or "unknown")

    @property
    def truth(self) -> Mapping[str, Any]:
        truth = self.annotation.get("truth")
        if not isinstance(truth, Mapping):
            return {}
        return truth

    @property
    def requirements(self) -> list[Mapping[str, Any]]:
        raw = self.truth.get("requirements") or []
        return [r for r in raw if isinstance(r, Mapping)]

    @property
    def citations(self) -> list[Mapping[str, Any]]:
        raw = self.truth.get("citations") or []
        return [c for c in raw if isinstance(c, Mapping)]

    @property
    def dates(self) -> list[Mapping[str, Any]]:
        raw = self.truth.get("dates") or []
        return [d for d in raw if isinstance(d, Mapping)]

    @property
    def provenance(self) -> list[Mapping[str, Any]]:
        raw = self.truth.get("provenance") or []
        return [p for p in raw if isinstance(p, Mapping)]

    @property
    def contradictions(self) -> list[Mapping[str, Any]]:
        raw = self.truth.get("contradictions") or []
        return [c for c in raw if isinstance(c, Mapping)]

    def annotation_digest(self) -> str:
        return digest_uri(content_digest(dict(self.annotation)))


def load_gold_case(
    case_id: str,
    *,
    gold_root: Path | str | None = None,
) -> GoldCase:
    """Load one case recipe and its matching annotation by *case_id*."""
    root = Path(gold_root) if gold_root is not None else default_gold_root()
    case_path = root / "cases" / f"{case_id}.json"
    ann_path = root / "annotations" / f"{case_id}.annotation.json"
    if not case_path.is_file():
        raise FileNotFoundError(f"missing gold case: {case_path}")
    if not ann_path.is_file():
        raise FileNotFoundError(f"missing gold annotation: {ann_path}")
    case = json.loads(case_path.read_text(encoding="utf-8"))
    annotation = json.loads(ann_path.read_text(encoding="utf-8"))
    if not isinstance(case, dict) or not isinstance(annotation, dict):
        raise EvaluationError("case and annotation must be JSON objects")
    if case.get("schema") != CASE_SCHEMA:
        raise EvaluationError(f"unexpected case schema: {case.get('schema')!r}")
    if annotation.get("schema") != ANNOTATION_SCHEMA:
        raise EvaluationError(
            f"unexpected annotation schema: {annotation.get('schema')!r}"
        )
    if case.get("case_id") != case_id or annotation.get("case_id") != case_id:
        raise EvaluationError(f"case_id mismatch for {case_id}")
    return GoldCase(case_id=case_id, case=case, annotation=annotation)


def list_gold_case_ids(*, gold_root: Path | str | None = None) -> tuple[str, ...]:
    root = Path(gold_root) if gold_root is not None else default_gold_root()
    cases_dir = root / "cases"
    return tuple(sorted(p.stem for p in cases_dir.glob("*.json")))


def load_gold_corpus(*, gold_root: Path | str | None = None) -> tuple[GoldCase, ...]:
    root = Path(gold_root) if gold_root is not None else default_gold_root()
    return tuple(load_gold_case(cid, gold_root=root) for cid in list_gold_case_ids(gold_root=root))


def load_corpus_manifest(*, fixture_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(fixture_root) if fixture_root is not None else default_uspto_fixture_root()
    path = root / "GOLD_CORPUS_MANIFEST.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EvaluationError("corpus manifest must be an object")
    if data.get("schema") != MANIFEST_SCHEMA:
        raise EvaluationError(f"unexpected manifest schema: {data.get('schema')!r}")
    return data


def corpus_digest_from_manifest(manifest: Mapping[str, Any]) -> str:
    """Stable digest over the manifest file inventory (sorted paths+hashes)."""
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise EvaluationError("manifest.files must be a mapping")
    material = {str(k): str(v) for k, v in sorted(files.items())}
    material["corpus_id"] = str(manifest.get("corpus_id") or "")
    return digest_uri(content_digest(material))


# ---------------------------------------------------------------------------
# Processor output adapter
# ---------------------------------------------------------------------------


def _as_list_of_maps(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise EvaluationError("expected a sequence of mappings")
    out: list[Mapping[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            out.append(item)
        else:
            raise EvaluationError("sequence items must be mappings")
    return out


def _predicted_requirement_ids(output: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for req in _as_list_of_maps(output.get("requirements")):
        rid = req.get("requirement_id")
        if isinstance(rid, str) and rid.strip():
            ids.add(rid.strip())
    # Obligations may alias requirements.
    for obl in _as_list_of_maps(output.get("obligations")):
        oid = obl.get("requirement_id") or obl.get("obligation_id")
        if isinstance(oid, str) and oid.strip():
            ids.add(oid.strip())
    return ids


def _predicted_citations(output: Mapping[str, Any]) -> set[str]:
    cites: set[str] = set()
    for cite in _as_list_of_maps(output.get("citations")):
        text = cite.get("text") or cite.get("citation") or cite.get("normalized")
        if isinstance(text, str) and text.strip():
            cites.add(normalize_citation(text))
    for req in _as_list_of_maps(output.get("requirements")):
        for raw in req.get("legal_citations") or []:
            if isinstance(raw, str) and raw.strip():
                cites.add(normalize_citation(raw))
    return cites


def _predicted_deadline_ids(output: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in _as_list_of_maps(output.get("dates")):
        did = item.get("deadline_id")
        if isinstance(did, str) and did.strip():
            ids.add(did.strip())
    for item in _as_list_of_maps(output.get("deadlines")):
        did = item.get("deadline_id")
        if isinstance(did, str) and did.strip():
            ids.add(did.strip())
    return ids


def _predicted_span_ids(output: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for span in _as_list_of_maps(output.get("spans")):
        sid = span.get("span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    for req in _as_list_of_maps(output.get("requirements")):
        sid = req.get("source_span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    for cite in _as_list_of_maps(output.get("citations")):
        sid = cite.get("source_span_id") or cite.get("span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    for prov in _as_list_of_maps(output.get("provenance")):
        sid = prov.get("span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    return ids


def _predicted_evidence_links(output: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return (item_id, span_id) evidence claims from the output."""
    links: list[tuple[str, str]] = []
    for req in _as_list_of_maps(output.get("requirements")):
        rid = req.get("requirement_id")
        sid = req.get("source_span_id")
        if isinstance(rid, str) and isinstance(sid, str) and rid.strip() and sid.strip():
            links.append((rid.strip(), sid.strip()))
    for link in _as_list_of_maps(output.get("evidence_links")):
        item_id = link.get("item_id") or link.get("requirement_id")
        sid = link.get("span_id") or link.get("source_span_id")
        if (
            isinstance(item_id, str)
            and isinstance(sid, str)
            and item_id.strip()
            and sid.strip()
        ):
            links.append((item_id.strip(), sid.strip()))
    return links


def _gold_evidence_links(case: GoldCase) -> set[tuple[str, str]]:
    links: set[tuple[str, str]] = set()
    for req in case.requirements:
        rid = req.get("requirement_id")
        sid = req.get("source_span_id")
        if isinstance(rid, str) and isinstance(sid, str) and rid.strip() and sid.strip():
            links.add((rid.strip(), sid.strip()))
    for prov in case.provenance:
        item_id = prov.get("item_id")
        sid = prov.get("span_id")
        if (
            isinstance(item_id, str)
            and isinstance(sid, str)
            and item_id.strip()
            and sid.strip()
        ):
            links.add((item_id.strip(), sid.strip()))
    return links


def _gold_span_ids(case: GoldCase) -> set[str]:
    ids: set[str] = set()
    for req in case.requirements:
        sid = req.get("source_span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    for cite in case.citations:
        sid = cite.get("source_span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    for prov in case.provenance:
        sid = prov.get("span_id")
        if isinstance(sid, str) and sid.strip():
            ids.add(sid.strip())
    return ids


def _gold_citations(case: GoldCase) -> set[str]:
    cites: set[str] = set()
    for cite in case.citations:
        text = cite.get("text")
        if isinstance(text, str) and text.strip():
            cites.add(normalize_citation(text))
    for req in case.requirements:
        for raw in req.get("legal_citations") or []:
            if isinstance(raw, str) and raw.strip():
                cites.add(normalize_citation(raw))
    return cites


def _gold_requirement_ids(case: GoldCase) -> set[str]:
    return {
        str(r["requirement_id"]).strip()
        for r in case.requirements
        if isinstance(r.get("requirement_id"), str) and str(r["requirement_id"]).strip()
    }


def _gold_deadline_ids(case: GoldCase) -> set[str]:
    return {
        str(d["deadline_id"]).strip()
        for d in case.dates
        if isinstance(d.get("deadline_id"), str) and str(d["deadline_id"]).strip()
    }


def _provenance_complete(
    items: Sequence[Mapping[str, Any]],
    required_fields: Sequence[str],
) -> tuple[int, int, int]:
    """Return (complete, total, unknown) for provenance items."""
    complete = 0
    total = 0
    unknown = 0
    for item in items:
        total += 1
        missing = False
        for field in required_fields:
            if field not in item or item[field] is None or item[field] == "":
                missing = True
                break
        if missing:
            # Explicit unknown classification is still incomplete for completeness.
            unknown += 0
        else:
            complete += 1
    return complete, total, unknown


def perfect_output_from_case(case: GoldCase) -> dict[str, Any]:
    """Build a processor output that mirrors gold labels (ideal baseline)."""
    requirements = [dict(r) for r in case.requirements]
    citations = [dict(c) for c in case.citations]
    dates = [dict(d) for d in case.dates]
    provenance = [dict(p) for p in case.provenance]
    spans = []
    for sid in sorted(_gold_span_ids(case)):
        spans.append({"span_id": sid})
    contradictions = [dict(c) for c in case.contradictions]
    semantic_fields: dict[str, Any] = {}
    for req in case.requirements:
        rid = req.get("requirement_id")
        if isinstance(rid, str):
            semantic_fields[rid] = {
                "requirement_type": req.get("requirement_type"),
                "affected_claims": list(req.get("affected_claims") or []),
            }
    for date in case.dates:
        did = date.get("deadline_id")
        if isinstance(did, str):
            semantic_fields[did] = {
                "event_basis": date.get("event_basis"),
                "candidate_utc": date.get("candidate_utc"),
            }

    stages = [
        "ingest",
        "extract",
        "classify",
        "requirements",
        "citations",
        "deadlines",
        "provenance",
        "dossier",
    ]
    return {
        "case_id": case.case_id,
        "classification": case.classification,
        "document_classification": {
            "predicted": case.classification,
            "privacy_class": case.privacy_class,
        },
        "requirements": requirements,
        "obligations": [
            {
                "obligation_id": r.get("requirement_id"),
                "requirement_id": r.get("requirement_id"),
                "source_span_id": r.get("source_span_id"),
            }
            for r in requirements
        ],
        "citations": citations,
        "dates": dates,
        "deadlines": dates,
        "spans": spans,
        "provenance": provenance,
        "evidence_links": [
            {
                "item_id": r.get("requirement_id"),
                "span_id": r.get("source_span_id"),
            }
            for r in requirements
            if r.get("requirement_id") and r.get("source_span_id")
        ],
        "semantic_fields": semantic_fields,
        "contradictions": contradictions,
        "privacy": {
            "classification": case.classification,
            "privacy_class": case.privacy_class,
            "leaked_private": False,
            "public_sink_allowed": case.classification
            in {"public_official", "public_user"},
        },
        "determinism": {
            "run_digest": content_digest({"case_id": case.case_id, "output": "v1"}),
            "repeat_digest": content_digest({"case_id": case.case_id, "output": "v1"}),
        },
        "end_to_end": {
            "stages_expected": list(stages),
            "stages_completed": list(stages),
        },
    }


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _gate_args(thresholds: MetricThresholds, gate_id: str) -> dict[str, Any]:
    gate = thresholds.gate(gate_id)
    return {
        "operator": gate.operator,
        "threshold": gate.threshold,
        "threshold_version": thresholds.thresholds_version,
    }


def compute_requirement_recall(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold = _gold_requirement_ids(case)
    pred = _predicted_requirement_ids(output)
    tp = len(gold & pred)
    fn = len(gold - pred)
    return _ratio_metric(
        metric_id=GATE_REQUIREMENT_RECALL,
        family=MetricFamily.RECALL,
        numerator=tp,
        denominator=len(gold),
        true_positives=tp,
        false_negatives=fn,
        details={"gold_count": str(len(gold)), "predicted_count": str(len(pred))},
        **_gate_args(thresholds, GATE_REQUIREMENT_RECALL),
    )


def compute_citation_recall(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold = _gold_citations(case)
    pred = _predicted_citations(output)
    tp = len(gold & pred)
    fn = len(gold - pred)
    return _ratio_metric(
        metric_id=GATE_CITATION_RECALL,
        family=MetricFamily.RECALL,
        numerator=tp,
        denominator=len(gold),
        true_positives=tp,
        false_negatives=fn,
        details={"gold_count": str(len(gold)), "predicted_count": str(len(pred))},
        **_gate_args(thresholds, GATE_CITATION_RECALL),
    )


def compute_evidence_precision(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold_links = _gold_evidence_links(case)
    pred_links = _predicted_evidence_links(output)
    if not pred_links:
        # No claims → not applicable when gold also empty; otherwise fail-closed
        # unmeasurable-as-fail only when predictions exist. Zero predictions with
        # gold labels is N/A for precision (undefined), counted not_applicable.
        return _ratio_metric(
            metric_id=GATE_EVIDENCE_PRECISION,
            family=MetricFamily.PRECISION,
            numerator=0,
            denominator=0,
            details={"reason": "no_predicted_evidence_links"},
            **_gate_args(thresholds, GATE_EVIDENCE_PRECISION),
        )
    tp = sum(1 for link in pred_links if link in gold_links)
    fp = len(pred_links) - tp
    return _ratio_metric(
        metric_id=GATE_EVIDENCE_PRECISION,
        family=MetricFamily.PRECISION,
        numerator=tp,
        denominator=len(pred_links),
        true_positives=tp,
        false_positives=fp,
        details={"gold_link_count": str(len(gold_links))},
        **_gate_args(thresholds, GATE_EVIDENCE_PRECISION),
    )


def compute_provenance_completeness(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    matching = thresholds.matching
    required = matching.get("provenance_required_fields") if isinstance(matching, Mapping) else None
    fields = (
        tuple(str(f) for f in required)
        if isinstance(required, Sequence) and not isinstance(required, (str, bytes))
        else PROVENANCE_REQUIRED_FIELDS
    )
    # Prefer system-emitted provenance; fall back to gold when output omits it
    # only for structural completeness of *output* items. Completeness is over
    # output items that claim provenance.
    items = _as_list_of_maps(output.get("provenance"))
    if not items:
        # If the system extracted requirements/citations/dates, each needs provenance.
        # Count gold items requiring provenance as the denominator when output is empty
        # → complete=0 → fail when gold has items.
        gold_items = case.provenance
        if not gold_items:
            return _ratio_metric(
                metric_id=GATE_PROVENANCE_COMPLETENESS,
                family=MetricFamily.PROVENANCE,
                numerator=0,
                denominator=0,
                details={"reason": "no_provenance_items"},
                **_gate_args(thresholds, GATE_PROVENANCE_COMPLETENESS),
            )
        return _ratio_metric(
            metric_id=GATE_PROVENANCE_COMPLETENESS,
            family=MetricFamily.PROVENANCE,
            numerator=0,
            denominator=len(gold_items),
            false_negatives=len(gold_items),
            details={"reason": "missing_output_provenance"},
            **_gate_args(thresholds, GATE_PROVENANCE_COMPLETENESS),
        )
    complete, total, _unknown = _provenance_complete(items, fields)
    return _ratio_metric(
        metric_id=GATE_PROVENANCE_COMPLETENESS,
        family=MetricFamily.PROVENANCE,
        numerator=complete,
        denominator=total,
        true_positives=complete,
        false_negatives=total - complete,
        details={"required_fields": ",".join(fields)},
        **_gate_args(thresholds, GATE_PROVENANCE_COMPLETENESS),
    )


def compute_false_negative_budget(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold = _gold_requirement_ids(case)
    pred = _predicted_requirement_ids(output)
    fn = len(gold - pred)
    return _ratio_metric(
        metric_id=GATE_FALSE_NEGATIVE_BUDGET,
        family=MetricFamily.FALSE_NEGATIVE,
        numerator=fn,
        denominator=len(gold),
        false_negatives=fn,
        true_positives=len(gold & pred),
        details={"gold_count": str(len(gold))},
        **_gate_args(thresholds, GATE_FALSE_NEGATIVE_BUDGET),
    )


def compute_document_classification(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    expected = case.classification
    predicted = None
    doc = output.get("document_classification")
    if isinstance(doc, Mapping):
        predicted = doc.get("predicted") or doc.get("classification")
    if predicted is None:
        predicted = output.get("classification")
    if not isinstance(predicted, str) or not predicted.strip():
        return _binary_metric(
            metric_id=METRIC_DOCUMENT_CLASSIFICATION,
            family=MetricFamily.DOCUMENT_CLASSIFICATION,
            success=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=1,
            details={"reason": "missing_predicted_classification", "expected": expected},
        )
    ok = predicted.strip() == expected
    return _binary_metric(
        metric_id=METRIC_DOCUMENT_CLASSIFICATION,
        family=MetricFamily.DOCUMENT_CLASSIFICATION,
        success=ok,
        threshold_version=thresholds.thresholds_version,
        details={"expected": expected, "predicted": predicted.strip()},
    )


def compute_span_recall(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold = _gold_span_ids(case)
    pred = _predicted_span_ids(output)
    tp = len(gold & pred)
    return _ratio_metric(
        metric_id=METRIC_SPAN,
        family=MetricFamily.SPAN,
        numerator=tp,
        denominator=len(gold),
        true_positives=tp,
        false_negatives=len(gold - pred),
        operator=">=",
        threshold=0.95,
        threshold_version=thresholds.thresholds_version,
        details={"gold_count": str(len(gold)), "predicted_count": str(len(pred))},
    )


def compute_semantic_field_accuracy(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    expected: dict[str, Mapping[str, Any]] = {}
    for req in case.requirements:
        rid = req.get("requirement_id")
        if isinstance(rid, str) and rid.strip():
            expected[rid.strip()] = {
                "requirement_type": req.get("requirement_type"),
                "affected_claims": list(req.get("affected_claims") or []),
            }
    for date in case.dates:
        did = date.get("deadline_id")
        if isinstance(did, str) and did.strip():
            expected[did.strip()] = {
                "event_basis": date.get("event_basis"),
                "candidate_utc": date.get("candidate_utc"),
            }
    if not expected:
        return _ratio_metric(
            metric_id=METRIC_SEMANTIC_FIELD,
            family=MetricFamily.SEMANTIC_FIELD,
            numerator=0,
            denominator=0,
            operator=">=",
            threshold=0.90,
            threshold_version=thresholds.thresholds_version,
            details={"reason": "no_semantic_labels"},
        )

    predicted_raw = output.get("semantic_fields")
    if not isinstance(predicted_raw, Mapping):
        # Fall back to reconstructing fields from requirements/dates in output.
        predicted_raw = {}
        for req in _as_list_of_maps(output.get("requirements")):
            rid = req.get("requirement_id")
            if isinstance(rid, str) and rid.strip():
                predicted_raw[rid.strip()] = {
                    "requirement_type": req.get("requirement_type"),
                    "affected_claims": list(req.get("affected_claims") or []),
                }
        for date in _as_list_of_maps(output.get("dates")):
            did = date.get("deadline_id")
            if isinstance(did, str) and did.strip():
                predicted_raw[did.strip()] = {
                    "event_basis": date.get("event_basis"),
                    "candidate_utc": date.get("candidate_utc"),
                }

    tp = 0
    for key, exp in expected.items():
        pred = predicted_raw.get(key) if isinstance(predicted_raw, Mapping) else None
        if not isinstance(pred, Mapping):
            continue
        # Compare only keys present in expected.
        match = True
        for field, exp_val in exp.items():
            if pred.get(field) != exp_val:
                match = False
                break
        if match:
            tp += 1
    return _ratio_metric(
        metric_id=METRIC_SEMANTIC_FIELD,
        family=MetricFamily.SEMANTIC_FIELD,
        numerator=tp,
        denominator=len(expected),
        true_positives=tp,
        false_negatives=len(expected) - tp,
        operator=">=",
        threshold=0.90,
        threshold_version=thresholds.thresholds_version,
        details={"expected_fields": str(len(expected))},
    )


def compute_obligation_recall(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    # Government requirements are the obligation surface for USPTO gold.
    gold = _gold_requirement_ids(case)
    pred = _predicted_requirement_ids(output)
    tp = len(gold & pred)
    return _ratio_metric(
        metric_id=METRIC_OBLIGATION,
        family=MetricFamily.OBLIGATION,
        numerator=tp,
        denominator=len(gold),
        true_positives=tp,
        false_negatives=len(gold - pred),
        operator=">=",
        threshold=0.95,
        threshold_version=thresholds.thresholds_version,
    )


def compute_contradiction_detection(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold = case.contradictions
    pred = _as_list_of_maps(output.get("contradictions"))
    if not gold:
        # No labels: if the system also reports none → not_applicable (not a pass).
        # If the system invents contradictions without labels → unknown (unverified).
        if not pred:
            return ObservedMetric(
                metric_id=METRIC_CONTRADICTION,
                family=MetricFamily.CONTRADICTION,
                status=MetricStatus.NOT_APPLICABLE,
                value=None,
                operator=None,
                threshold=None,
                threshold_version=thresholds.thresholds_version,
                not_applicable_count=1,
                details={"reason": "no_gold_contradiction_labels"},
            )
        return ObservedMetric(
            metric_id=METRIC_CONTRADICTION,
            family=MetricFamily.CONTRADICTION,
            status=MetricStatus.UNKNOWN,
            value=None,
            operator=None,
            threshold=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=1,
            details={"reason": "predictions_without_labels"},
        )
    gold_ids = {
        str(c.get("contradiction_id") or c.get("id") or "").strip()
        for c in gold
        if (c.get("contradiction_id") or c.get("id"))
    }
    if not gold_ids:
        # Labeled but without stable ids — unmeasurable.
        return ObservedMetric(
            metric_id=METRIC_CONTRADICTION,
            family=MetricFamily.CONTRADICTION,
            status=MetricStatus.UNKNOWN,
            value=None,
            operator=None,
            threshold=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=len(gold),
            details={"reason": "gold_contradictions_lack_ids"},
        )
    pred_ids = {
        str(c.get("contradiction_id") or c.get("id") or "").strip()
        for c in pred
        if (c.get("contradiction_id") or c.get("id"))
    }
    tp = len(gold_ids & pred_ids)
    return _ratio_metric(
        metric_id=METRIC_CONTRADICTION,
        family=MetricFamily.CONTRADICTION,
        numerator=tp,
        denominator=len(gold_ids),
        true_positives=tp,
        false_negatives=len(gold_ids - pred_ids),
        operator=">=",
        threshold=0.90,
        threshold_version=thresholds.thresholds_version,
    )


def compute_deadline_recall(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    gold = _gold_deadline_ids(case)
    pred = _predicted_deadline_ids(output)
    tp = len(gold & pred)
    return _ratio_metric(
        metric_id=METRIC_DEADLINE,
        family=MetricFamily.DEADLINE,
        numerator=tp,
        denominator=len(gold),
        true_positives=tp,
        false_negatives=len(gold - pred),
        operator=">=",
        threshold=0.95,
        threshold_version=thresholds.thresholds_version,
        details={"gold_count": str(len(gold))},
    )


def compute_privacy_isolation(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    privacy = output.get("privacy")
    if not isinstance(privacy, Mapping):
        # Infer minimal privacy surface from classification.
        privacy = {
            "classification": output.get("classification"),
            "leaked_private": False,
        }
    leaked = privacy.get("leaked_private")
    if leaked is True:
        return _binary_metric(
            metric_id=METRIC_PRIVACY,
            family=MetricFamily.PRIVACY,
            success=False,
            threshold_version=thresholds.thresholds_version,
            details={"reason": "leaked_private"},
        )
    predicted_class = privacy.get("classification") or output.get("classification")
    if not isinstance(predicted_class, str) or not predicted_class.strip():
        return _binary_metric(
            metric_id=METRIC_PRIVACY,
            family=MetricFamily.PRIVACY,
            success=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=1,
            details={"reason": "missing_privacy_classification"},
        )
    # Public synthetic gold must not be reclassified into private without quarantine.
    private_classes = {
        "confidential_application",
        "privileged_work_product",
        "restricted_export_review",
        "credential_or_payment",
    }
    if case.classification in {"public_official", "public_user"}:
        if predicted_class.strip() in private_classes and privacy.get("quarantined") is not True:
            return _binary_metric(
                metric_id=METRIC_PRIVACY,
                family=MetricFamily.PRIVACY,
                success=False,
                threshold_version=thresholds.thresholds_version,
                details={
                    "reason": "public_gold_marked_private_without_quarantine",
                    "predicted": predicted_class.strip(),
                },
            )
    ok = predicted_class.strip() == case.classification and leaked is not True
    return _binary_metric(
        metric_id=METRIC_PRIVACY,
        family=MetricFamily.PRIVACY,
        success=ok,
        threshold_version=thresholds.thresholds_version,
        details={
            "expected": case.classification,
            "predicted": predicted_class.strip(),
        },
    )


def compute_determinism(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    det = output.get("determinism")
    if not isinstance(det, Mapping):
        return _binary_metric(
            metric_id=METRIC_DETERMINISM,
            family=MetricFamily.DETERMINISM,
            success=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=1,
            details={"reason": "missing_determinism_block"},
        )
    run = det.get("run_digest")
    repeat = det.get("repeat_digest")
    if not isinstance(run, str) or not isinstance(repeat, str):
        return _binary_metric(
            metric_id=METRIC_DETERMINISM,
            family=MetricFamily.DETERMINISM,
            success=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=1,
            details={"reason": "incomplete_determinism_digests"},
        )
    ok = run.strip() == repeat.strip() and bool(run.strip())
    return _binary_metric(
        metric_id=METRIC_DETERMINISM,
        family=MetricFamily.DETERMINISM,
        success=ok,
        threshold_version=thresholds.thresholds_version,
        details={"run_digest": run.strip()[:64], "repeat_digest": repeat.strip()[:64]},
    )


def compute_end_to_end_completeness(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> ObservedMetric:
    e2e = output.get("end_to_end")
    if not isinstance(e2e, Mapping):
        return _binary_metric(
            metric_id=METRIC_E2E_COMPLETENESS,
            family=MetricFamily.END_TO_END_COMPLETENESS,
            success=None,
            threshold_version=thresholds.thresholds_version,
            unknown_count=1,
            details={"reason": "missing_end_to_end_block"},
        )
    expected = e2e.get("stages_expected")
    completed = e2e.get("stages_completed")
    if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes)):
        return _binary_metric(
            metric_id=METRIC_E2E_COMPLETENESS,
            family=MetricFamily.END_TO_END_COMPLETENESS,
            success=None,
            threshold_version=thresholds.thresholds_version,
            not_applicable_count=1,
            details={"reason": "no_stages_expected"},
        )
    if not expected:
        return _binary_metric(
            metric_id=METRIC_E2E_COMPLETENESS,
            family=MetricFamily.END_TO_END_COMPLETENESS,
            success=None,
            threshold_version=thresholds.thresholds_version,
            not_applicable_count=1,
            details={"reason": "empty_stages_expected"},
        )
    if not isinstance(completed, Sequence) or isinstance(completed, (str, bytes)):
        return _binary_metric(
            metric_id=METRIC_E2E_COMPLETENESS,
            family=MetricFamily.END_TO_END_COMPLETENESS,
            success=False,
            threshold_version=thresholds.thresholds_version,
            details={"reason": "missing_stages_completed"},
        )
    exp_set = {str(s).strip() for s in expected if str(s).strip()}
    done_set = {str(s).strip() for s in completed if str(s).strip()}
    tp = len(exp_set & done_set)
    return _ratio_metric(
        metric_id=METRIC_E2E_COMPLETENESS,
        family=MetricFamily.END_TO_END_COMPLETENESS,
        numerator=tp,
        denominator=len(exp_set),
        true_positives=tp,
        false_negatives=len(exp_set - done_set),
        operator=">=",
        threshold=1.0,
        threshold_version=thresholds.thresholds_version,
        details={"expected": str(len(exp_set)), "completed": str(len(done_set))},
    )


def evaluate_case_metrics(
    case: GoldCase,
    output: Mapping[str, Any],
    thresholds: MetricThresholds,
) -> tuple[ObservedMetric, ...]:
    """Compute the full metric suite for one gold case vs processor output."""
    return (
        compute_requirement_recall(case, output, thresholds),
        compute_citation_recall(case, output, thresholds),
        compute_evidence_precision(case, output, thresholds),
        compute_provenance_completeness(case, output, thresholds),
        compute_false_negative_budget(case, output, thresholds),
        compute_document_classification(case, output, thresholds),
        compute_span_recall(case, output, thresholds),
        compute_semantic_field_accuracy(case, output, thresholds),
        compute_obligation_recall(case, output, thresholds),
        compute_contradiction_detection(case, output, thresholds),
        compute_deadline_recall(case, output, thresholds),
        compute_privacy_isolation(case, output, thresholds),
        compute_determinism(case, output, thresholds),
        compute_end_to_end_completeness(case, output, thresholds),
    )


def aggregate_metrics(
    per_case: Sequence[Sequence[ObservedMetric]],
) -> tuple[ObservedMetric, ...]:
    """Micro-aggregate same metric_id observations across cases.

    Status rules:
    * If any case FAILs a measurable gate → FAIL.
    * Else if any PASS and all measurable pass → PASS.
    * Pure unknown / not_applicable aggregates preserve those statuses and
      sum their counts (never promote to PASS).
    """
    by_id: dict[str, list[ObservedMetric]] = {}
    for metrics in per_case:
        for metric in metrics:
            by_id.setdefault(metric.metric_id, []).append(metric)

    aggregated: list[ObservedMetric] = []
    for metric_id, items in sorted(by_id.items()):
        family = items[0].family
        operator = items[0].operator
        threshold = items[0].threshold
        threshold_version = items[0].threshold_version
        tp = sum(m.true_positives for m in items)
        fp = sum(m.false_positives for m in items)
        fn = sum(m.false_negatives for m in items)
        unknown = sum(m.unknown_count for m in items)
        na = sum(m.not_applicable_count for m in items)
        # Prefer summing numerators/denominators when present.
        num_parts = [m.numerator for m in items if m.numerator is not None]
        den_parts = [m.denominator for m in items if m.denominator is not None]
        numerator = sum(num_parts) if num_parts else None
        denominator = sum(den_parts) if den_parts else None

        statuses = {m.status for m in items}
        if MetricStatus.FAIL in statuses:
            status = MetricStatus.FAIL
        elif statuses <= {MetricStatus.NOT_APPLICABLE}:
            status = MetricStatus.NOT_APPLICABLE
        elif statuses <= {MetricStatus.UNKNOWN, MetricStatus.NOT_APPLICABLE}:
            status = MetricStatus.UNKNOWN
        elif MetricStatus.PASS in statuses and MetricStatus.FAIL not in statuses:
            # Mixed pass + unknown/n/a: keep pass only if every measurable item passed.
            measurable = [m for m in items if m.is_measurable]
            if measurable and all(m.status is MetricStatus.PASS for m in measurable):
                status = MetricStatus.PASS
            elif not measurable:
                status = MetricStatus.UNKNOWN
            else:
                status = MetricStatus.UNKNOWN
        else:
            status = MetricStatus.UNKNOWN

        value: float | None
        if denominator is not None and denominator > 0 and numerator is not None:
            value = float(numerator) / float(denominator)
            # Re-evaluate threshold on aggregate when status is measurable.
            if (
                status in {MetricStatus.PASS, MetricStatus.FAIL}
                and operator is not None
                and threshold is not None
            ):
                status = (
                    MetricStatus.PASS
                    if compare_threshold(value, operator=operator, threshold=threshold)
                    else MetricStatus.FAIL
                )
        elif status is MetricStatus.PASS:
            value = 1.0
        elif status is MetricStatus.FAIL:
            value = 0.0
        else:
            value = None

        aggregated.append(
            ObservedMetric(
                metric_id=metric_id,
                family=family,
                status=status,
                value=value,
                operator=operator,
                threshold=threshold,
                threshold_version=threshold_version,
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                unknown_count=unknown,
                not_applicable_count=na,
                numerator=numerator,
                denominator=denominator,
                details={"case_count": str(len(items))},
            )
        )
    return tuple(aggregated)


def assert_thresholds(
    metrics: Sequence[ObservedMetric],
    *,
    required_ids: Iterable[str] | None = None,
) -> tuple[ObservedMetric, ...]:
    """Raise :class:`MetricThresholdError` if any required measurable metric fails.

    Unknown / not_applicable metrics do **not** count as passes and do **not**
    raise unless they are required *and* fail_closed measurable gates with a
    FAIL status. Required metrics that are unknown still raise when
    ``required_ids`` includes them and status is FAIL only — unknown is
    reported but does not raise by default (callers inspect counts).
    """
    required = frozenset(required_ids) if required_ids is not None else REQUIRED_GATE_IDS
    failures = [
        m
        for m in metrics
        if m.metric_id in required and m.status is MetricStatus.FAIL
    ]
    if failures:
        detail = ", ".join(
            f"{m.metric_id}={m.value!r} {m.operator} {m.threshold}" for m in failures
        )
        raise MetricThresholdError(f"metric threshold regression: {detail}")
    return tuple(metrics)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    """Per-case metric bundle."""

    case_id: str
    metrics: tuple[ObservedMetric, ...]
    output_digest: str
    annotation_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_digest": self.annotation_digest,
            "case_id": self.case_id,
            "metrics": [m.to_dict() for m in self.metrics],
            "output_digest": self.output_digest,
        }


class USPTOGoldEvaluator:
    """Execute gold-corpus metrics and emit content-addressed receipts."""

    def __init__(
        self,
        *,
        thresholds: MetricThresholds | None = None,
        gold_root: Path | str | None = None,
        identity: EvaluationIdentity | None = None,
        fail_loudly: bool = True,
    ) -> None:
        self._gold_root = Path(gold_root) if gold_root is not None else default_gold_root()
        self._thresholds = thresholds if thresholds is not None else load_metric_gates(
            self._gold_root / "metrics" / "metric_gates.json"
        )
        self._identity = identity
        self._fail_loudly = fail_loudly

    @property
    def thresholds(self) -> MetricThresholds:
        return self._thresholds

    @property
    def gold_root(self) -> Path:
        return self._gold_root

    def resolve_identity(
        self,
        *,
        identity: EvaluationIdentity | None = None,
        corpus_id: str | None = None,
        parser_id: str = "uspto.parser.fixture",
        parser_digest: str | None = None,
        ruleset_id: str = "uspto.ruleset.fixture",
        ruleset_digest: str | None = None,
        model_id: str = "uspto.model.none",
        model_digest: str | None = None,
        config_id: str = "uspto.config.fixture",
        config_digest: str | None = None,
    ) -> EvaluationIdentity:
        if identity is not None:
            return identity
        if self._identity is not None:
            return self._identity
        try:
            manifest = load_corpus_manifest(fixture_root=self._gold_root.parent)
            corpus_digest = corpus_digest_from_manifest(manifest)
            resolved_corpus_id = corpus_id or str(
                manifest.get("corpus_id") or DEFAULT_CORPUS_ID
            )
        except (OSError, EvaluationError, json.JSONDecodeError):
            resolved_corpus_id = corpus_id or DEFAULT_CORPUS_ID
            corpus_digest = digest_uri(
                content_digest({"corpus_id": resolved_corpus_id, "gold_root": str(self._gold_root)})
            )
        empty = content_digest({})
        return EvaluationIdentity(
            corpus_id=resolved_corpus_id,
            corpus_digest=corpus_digest,
            parser_id=parser_id,
            parser_digest=parser_digest or digest_uri(empty),
            ruleset_id=ruleset_id,
            ruleset_digest=ruleset_digest or digest_uri(empty),
            model_id=model_id,
            model_digest=model_digest or digest_uri(empty),
            config_id=config_id,
            config_digest=config_digest or digest_uri(empty),
            thresholds_version=self._thresholds.thresholds_version,
            thresholds_digest=self._thresholds.thresholds_digest,
        )

    def evaluate_case(
        self,
        case: GoldCase | str,
        output: Mapping[str, Any],
    ) -> CaseEvaluation:
        if isinstance(case, str):
            gold = load_gold_case(case, gold_root=self._gold_root)
        else:
            gold = case
        if not isinstance(output, Mapping):
            raise EvaluationError("output must be a mapping")
        metrics = evaluate_case_metrics(gold, output, self._thresholds)
        return CaseEvaluation(
            case_id=gold.case_id,
            metrics=metrics,
            output_digest=digest_uri(content_digest(dict(output))),
            annotation_digest=gold.annotation_digest(),
        )

    def evaluate_corpus(
        self,
        outputs: Mapping[str, Mapping[str, Any]],
        *,
        identity: EvaluationIdentity | None = None,
        receipt_id: str = "receipt:gold-eval",
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
        case_ids: Sequence[str] | None = None,
    ) -> GoldEvaluationReceipt:
        """Evaluate many case outputs and emit a bound receipt.

        *outputs* maps ``case_id`` → processor output mapping.
        """
        if not isinstance(outputs, Mapping) or not outputs:
            raise EvaluationError("outputs must be a non-empty mapping of case_id→output")

        selected = (
            tuple(case_ids)
            if case_ids is not None
            else tuple(sorted(outputs.keys()))
        )
        case_evals: list[CaseEvaluation] = []
        for case_id in selected:
            if case_id not in outputs:
                raise EvaluationError(f"missing output for case_id {case_id!r}")
            case_evals.append(self.evaluate_case(case_id, outputs[case_id]))

        aggregated = aggregate_metrics([ce.metrics for ce in case_evals])
        if self._fail_loudly:
            # Loud only for required release gates that hard-fail.
            assert_thresholds(aggregated, required_ids=REQUIRED_GATE_IDS)

        bound = self.resolve_identity(identity=identity)
        annotations_digest = digest_uri(
            content_digest(
                {
                    ce.case_id: ce.annotation_digest
                    for ce in sorted(case_evals, key=lambda c: c.case_id)
                }
            )
        )
        outputs_digest = digest_uri(
            content_digest(
                {
                    ce.case_id: ce.output_digest
                    for ce in sorted(case_evals, key=lambda c: c.case_id)
                }
            )
        )

        pass_count = sum(1 for m in aggregated if m.status is MetricStatus.PASS)
        fail_count = sum(1 for m in aggregated if m.status is MetricStatus.FAIL)
        unknown_count = sum(m.unknown_count for m in aggregated)
        not_applicable_count = sum(m.not_applicable_count for m in aggregated)

        # Overall pass: every required gate that is measurable must PASS;
        # any FAIL fails the receipt. Unknown/N/A required gates do not
        # invent a pass — overall stays False when any required gate is not PASS.
        required_metrics = {
            m.metric_id: m for m in aggregated if m.metric_id in REQUIRED_GATE_IDS
        }
        overall = True
        for gate_id in REQUIRED_GATE_IDS:
            metric = required_metrics.get(gate_id)
            if metric is None or metric.status is not MetricStatus.PASS:
                overall = False
                break
        if fail_count > 0:
            overall = False

        provisional = {
            "annotations_digest": annotations_digest,
            "case_ids": list(selected),
            "contracts_schema_version": CONTRACTS_SCHEMA_VERSION,
            "evaluated_at_utc": evaluated_at_utc,
            "fail_count": fail_count,
            "identity": bound.to_dict(),
            "metadata": dict(metadata or {}),
            "metrics": [m.to_dict() for m in aggregated],
            "not_applicable_count": not_applicable_count,
            "observed_metrics_schema": OBSERVED_METRICS_SCHEMA,
            "outputs_digest": outputs_digest,
            "pass_count": pass_count,
            "passed": overall,
            "receipt_id": receipt_id,
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "unknown_count": unknown_count,
        }
        receipt_digest = build_receipt_digest(provisional)
        return GoldEvaluationReceipt(
            schema_version=EVALUATION_SCHEMA_VERSION,
            observed_metrics_schema=OBSERVED_METRICS_SCHEMA,
            receipt_id=receipt_id,
            receipt_digest=receipt_digest,
            identity=bound,
            metrics=aggregated,
            case_ids=tuple(selected),
            annotations_digest=annotations_digest,
            outputs_digest=outputs_digest,
            contracts_schema_version=CONTRACTS_SCHEMA_VERSION,
            evaluated_at_utc=evaluated_at_utc,
            pass_count=pass_count,
            fail_count=fail_count,
            unknown_count=unknown_count,
            not_applicable_count=not_applicable_count,
            passed=overall,
            metadata=metadata or {},
        )


def observed_metrics_document(
    metrics: Sequence[ObservedMetric],
    *,
    thresholds: MetricThresholds,
    case_ids: Sequence[str],
) -> dict[str, Any]:
    """Serialize observed metrics into the versioned schema document shape."""
    return {
        "schema": OBSERVED_METRICS_SCHEMA,
        "schema_version": OBSERVED_METRICS_SCHEMA_VERSION,
        "thresholds_version": thresholds.thresholds_version,
        "thresholds_digest": thresholds.thresholds_digest,
        "case_ids": list(case_ids),
        "metrics": [m.to_dict() for m in metrics],
        "summary": {
            "pass_count": sum(1 for m in metrics if m.status is MetricStatus.PASS),
            "fail_count": sum(1 for m in metrics if m.status is MetricStatus.FAIL),
            "unknown_count": sum(m.unknown_count for m in metrics),
            "not_applicable_count": sum(m.not_applicable_count for m in metrics),
        },
    }


__all__ = [
    "ANNOTATION_SCHEMA",
    "CASE_SCHEMA",
    "CONTRACTS_SCHEMA_VERSION",
    "DEFAULT_CORPUS_ID",
    "DEFAULT_THRESHOLDS_VERSION",
    "EVALUATION_INTERFACE",
    "EVALUATION_SCHEMA_VERSION",
    "GATES_SCHEMA",
    "GATE_CITATION_RECALL",
    "GATE_EVIDENCE_PRECISION",
    "GATE_FALSE_NEGATIVE_BUDGET",
    "GATE_PROVENANCE_COMPLETENESS",
    "GATE_REQUIREMENT_RECALL",
    "CaseEvaluation",
    "EvaluationError",
    "EvaluationIdentity",
    "GoldCase",
    "GoldEvaluationReceipt",
    "GateSpec",
    "MANIFEST_SCHEMA",
    "METRIC_CITATION",
    "METRIC_CONTRADICTION",
    "METRIC_DEADLINE",
    "METRIC_DETERMINISM",
    "METRIC_DOCUMENT_CLASSIFICATION",
    "METRIC_E2E_COMPLETENESS",
    "METRIC_OBLIGATION",
    "METRIC_PRIVACY",
    "METRIC_SEMANTIC_FIELD",
    "METRIC_SPAN",
    "MetricFamily",
    "MetricStatus",
    "MetricThresholdError",
    "MetricThresholds",
    "OBSERVED_METRICS_SCHEMA",
    "OBSERVED_METRICS_SCHEMA_VERSION",
    "ObservedMetric",
    "PROVENANCE_REQUIRED_FIELDS",
    "REQUIRED_EXTENDED_METRIC_IDS",
    "REQUIRED_GATE_IDS",
    "REQUIRED_RECEIPT_METRIC_IDS",
    "SCHEMA_VERSION",
    "USPTOGoldEvaluator",
    "aggregate_metrics",
    "assert_thresholds",
    "build_receipt_digest",
    "canonical_json",
    "compare_threshold",
    "content_digest",
    "corpus_digest_from_manifest",
    "default_gold_root",
    "default_uspto_fixture_root",
    "digest_uri",
    "evaluate_case_metrics",
    "list_gold_case_ids",
    "load_corpus_manifest",
    "load_gold_case",
    "load_gold_corpus",
    "load_metric_gates",
    "normalize_citation",
    "observed_metrics_document",
    "perfect_output_from_case",
    "sha256_hex",
]
