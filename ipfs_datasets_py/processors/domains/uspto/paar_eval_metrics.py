"""PAAR offline conflict/conformance evaluation metrics (PAAR-112).

Computes hermetic metrics over golden review fixtures and/or pre-scored
observation rows:

* **conflict_recall_proxy** — planted-overlap cases elevated to medium/high
* **false_high_rate** — clean (non-planted) cases scored high without evidence
* **fail_closed_rates** — missing authority / empty claims / unsearched corpora
  never invent ready/satisfied/low-risk success

Design rules
------------
* Offline only — no network I/O.
* Metrics JSON schema versioned; digests exclude wall-clock when possible.
* Never store claim bodies, PDF bodies, secrets, or private document text.
* Not legal advice; metrics are triage harness signals only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

PAAR_EVAL_METRICS_SCHEMA: Final = "paar.EvalMetrics@1"
PAAR_EVAL_METRICS_INTERFACE: Final = "PaarEvalMetrics@1"
PAAR_EVAL_METRICS_CODE_VERSION: Final = "1.0.0"

METRIC_CONFLICT_RECALL_PROXY: Final = "conflict_recall_proxy"
METRIC_FALSE_HIGH_RATE: Final = "false_high_rate"
METRIC_FAIL_CLOSED_AUTHORITY: Final = "fail_closed_missing_authority"
METRIC_FAIL_CLOSED_EMPTY_CLAIMS: Final = "fail_closed_empty_claims"
METRIC_FAIL_CLOSED_UNSEARCHED: Final = "fail_closed_unsearched_corpora"

REVIEW_ONLY_EVAL_DISCLAIMER: Final = (
    "PAAR offline evaluation metrics only. Heuristic triage signals for golden "
    "fixtures — not legal advice, not a patentability determination, not a "
    "novelty or obviousness conclusion. auto_file_blocked remains true."
)

_RISK_ORDER: Final[dict[str, int]] = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

_BODY_KEY_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {
        "claims_text",
        "body_excerpt",
        "document_body",
        "document_bytes",
        "extracted_text",
        "raw_body",
        "pdf_body",
        "provider_payload",
        "api_key",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
    }
)

_SECRET_TEXT_RE = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|bearer|token|password|cookie)"
    r"\s*[:=]\s*[^\s,;\"']+"
)


class PaarEvalMetricsError(ValueError):
    """Bounded metrics computation failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "paar_eval_metrics_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_hex(payload: Any) -> str:
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _risk_at_least(risk: str, minimum: str) -> bool:
    return _RISK_ORDER.get(str(risk).lower(), 0) >= _RISK_ORDER.get(
        str(minimum).lower(), 0
    )


def _is_body_key(key: Any) -> bool:
    lowered = str(key or "").strip().lower().replace("-", "_")
    if not lowered:
        return False
    if lowered in _BODY_KEY_FRAGMENTS:
        return True
    return any(frag in lowered for frag in _BODY_KEY_FRAGMENTS)


def strip_private_bodies(value: Any, *, depth: int = 0) -> Any:
    """Drop secret/body-bearing keys and scrub credential-like strings.

    Metrics artifacts must never carry claim/PDF/secret content.
    """
    if depth > 10:
        return "<redacted:max-depth>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _is_body_key(k):
                continue
            out[str(k)] = strip_private_bodies(v, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [strip_private_bodies(v, depth=depth + 1) for v in list(value)[:200]]
    if isinstance(value, (bytes, bytearray)):
        return f"<redacted:bytes:{len(value)}>"
    if isinstance(value, str):
        text = value
        if text.lstrip().startswith("%PDF") or text.lstrip().startswith("%" + "PDF"):
            return "<redacted:pdf>"
        text = _SECRET_TEXT_RE.sub(r"\1=<redacted>", text)
        if len(text) > 400:
            return text[:397] + "..."
        return text
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


# ---------------------------------------------------------------------------
# Case observation model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvalCaseObservation:
    """One fixture/run observation for offline metrics (content-free)."""

    case_id: str
    variant: str
    planted_overlap: bool
    matter_risk: str
    disposition: str
    conformance_status: str
    authority_corpus_present: bool
    claims_empty: bool
    unsearched_required_corpora: tuple[str, ...] = ()
    auto_file_blocked: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "variant": self.variant,
            "planted_overlap": bool(self.planted_overlap),
            "matter_risk": str(self.matter_risk),
            "disposition": str(self.disposition),
            "conformance_status": str(self.conformance_status),
            "authority_corpus_present": bool(self.authority_corpus_present),
            "claims_empty": bool(self.claims_empty),
            "unsearched_required_corpora": list(self.unsearched_required_corpora),
            "auto_file_blocked": True,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvalCaseObservation":
        unsearched = value.get("unsearched_required_corpora") or ()
        return cls(
            case_id=str(value.get("case_id") or value.get("fixture_id") or ""),
            variant=str(value.get("variant") or ""),
            planted_overlap=bool(value.get("planted_overlap")),
            matter_risk=str(value.get("matter_risk") or "unknown").lower(),
            disposition=str(value.get("disposition") or "not_ready").lower(),
            conformance_status=str(
                value.get("conformance_status") or "unknown"
            ).lower(),
            authority_corpus_present=bool(value.get("authority_corpus_present")),
            claims_empty=bool(value.get("claims_empty")),
            unsearched_required_corpora=tuple(str(x) for x in unsearched),
            auto_file_blocked=True,
            metadata={
                str(k): str(v)
                for k, v in dict(value.get("metadata") or {}).items()
            },
        )


def observation_from_unified_review(
    report: Any,
    *,
    case_id: str = "",
    variant: str = "",
    planted_overlap: bool | None = None,
) -> EvalCaseObservation:
    """Project a UnifiedApplicationReview-like object to a content-free observation."""
    if hasattr(report, "to_dict"):
        payload = report.to_dict()
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        raise PaarEvalMetricsError(
            "report must be Mapping or expose to_dict()",
            code="invalid_report",
        )

    conflict = payload.get("conflict_risk_ref") or {}
    conf = payload.get("conformance_ref") or {}
    claim = payload.get("claim_model_ref") or {}
    gaps = payload.get("coverage_gaps") or ()

    unsearched: list[str] = []
    for g in gaps:
        if not isinstance(g, Mapping):
            continue
        status = str(g.get("status") or "").lower()
        if status in {"unsearched", "unknown", "failed"}:
            corpus = str(g.get("corpus") or g.get("kind") or "")
            if corpus:
                unsearched.append(corpus)

    if planted_overlap is None:
        planted_overlap = str(variant).lower() in {
            "planted_conflict",
            "planted",
            "conflict",
        }

    claim_count = claim.get("claim_count")
    claims_empty = bool(claim.get("empty")) or (
        claim_count is not None and int(claim_count) == 0
    )

    authority = conf.get("authority_corpus_present")
    if authority is None:
        authority = claim.get("authority_mode") not in {
            None,
            "unknown",
            "missing",
            "unbound",
        }

    return EvalCaseObservation(
        case_id=case_id
        or str(payload.get("review_id") or payload.get("application_number") or ""),
        variant=variant or str((payload.get("metadata") or {}).get("variant") or ""),
        planted_overlap=bool(planted_overlap),
        matter_risk=str(conflict.get("matter_risk") or "unknown").lower(),
        disposition=str(payload.get("disposition") or "not_ready").lower(),
        conformance_status=str(conf.get("overall_status") or "unknown").lower(),
        authority_corpus_present=bool(authority),
        claims_empty=claims_empty,
        unsearched_required_corpora=tuple(unsearched),
        auto_file_blocked=bool(payload.get("auto_file_blocked", True)),
        metadata={
            "application_number": str(payload.get("application_number") or ""),
            "content_digest": str(payload.get("content_digest") or "")[:64],
        },
    )


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One named metric with rate / counts / status."""

    metric_id: str
    status: str  # pass | fail | unknown | not_applicable
    rate: float | None
    numerator: int
    denominator: int
    threshold: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "status": self.status,
            "rate": self.rate,
            "numerator": int(self.numerator),
            "denominator": int(self.denominator),
            "threshold": self.threshold,
            "notes": self.notes,
        }


def compute_conflict_recall_proxy(
    cases: Sequence[EvalCaseObservation],
    *,
    min_risk: str = "medium",
    threshold: float = 1.0,
) -> MetricObservation:
    """Recall proxy: planted-overlap cases with matter_risk >= min_risk."""
    planted = [c for c in cases if c.planted_overlap]
    if not planted:
        return MetricObservation(
            metric_id=METRIC_CONFLICT_RECALL_PROXY,
            status="not_applicable",
            rate=None,
            numerator=0,
            denominator=0,
            threshold=threshold,
            notes="No planted-overlap cases in observation set.",
        )
    hits = sum(1 for c in planted if _risk_at_least(c.matter_risk, min_risk))
    rate = _safe_rate(hits, len(planted))
    status = "pass" if rate is not None and rate >= threshold else "fail"
    if rate is None:
        status = "unknown"
    return MetricObservation(
        metric_id=METRIC_CONFLICT_RECALL_PROXY,
        status=status,
        rate=rate,
        numerator=hits,
        denominator=len(planted),
        threshold=threshold,
        notes=f"Planted cases with matter_risk >= {min_risk}.",
    )


def compute_false_high_rate(
    cases: Sequence[EvalCaseObservation],
    *,
    threshold: float = 0.0,
) -> MetricObservation:
    """False-high: non-planted cases scored high (expect near-zero)."""
    clean = [c for c in cases if not c.planted_overlap]
    if not clean:
        return MetricObservation(
            metric_id=METRIC_FALSE_HIGH_RATE,
            status="not_applicable",
            rate=None,
            numerator=0,
            denominator=0,
            threshold=threshold,
            notes="No clean (non-planted) cases in observation set.",
        )
    false_high = sum(1 for c in clean if str(c.matter_risk).lower() == "high")
    rate = _safe_rate(false_high, len(clean))
    # Lower is better; pass when rate <= threshold
    status = "pass" if rate is not None and rate <= threshold else "fail"
    if rate is None:
        status = "unknown"
    return MetricObservation(
        metric_id=METRIC_FALSE_HIGH_RATE,
        status=status,
        rate=rate,
        numerator=false_high,
        denominator=len(clean),
        threshold=threshold,
        notes="Non-planted cases with matter_risk=high (false-high).",
    )


def compute_fail_closed_missing_authority(
    cases: Sequence[EvalCaseObservation],
    *,
    threshold: float = 1.0,
) -> MetricObservation:
    """Missing authority must not yield ready + satisfied."""
    candidates = [
        c
        for c in cases
        if not c.authority_corpus_present
        or c.variant in {"missing_authority", "unbound_authority"}
    ]
    if not candidates:
        return MetricObservation(
            metric_id=METRIC_FAIL_CLOSED_AUTHORITY,
            status="not_applicable",
            rate=None,
            numerator=0,
            denominator=0,
            threshold=threshold,
            notes="No missing-authority cases.",
        )
    closed = sum(
        1
        for c in candidates
        if str(c.disposition).lower() != "ready"
        and str(c.conformance_status).lower() != "satisfied"
    )
    rate = _safe_rate(closed, len(candidates))
    status = "pass" if rate is not None and rate >= threshold else "fail"
    if rate is None:
        status = "unknown"
    return MetricObservation(
        metric_id=METRIC_FAIL_CLOSED_AUTHORITY,
        status=status,
        rate=rate,
        numerator=closed,
        denominator=len(candidates),
        threshold=threshold,
        notes="Missing authority never ready/satisfied.",
    )


def compute_fail_closed_empty_claims(
    cases: Sequence[EvalCaseObservation],
    *,
    threshold: float = 1.0,
) -> MetricObservation:
    """Empty claims must not yield ready."""
    candidates = [c for c in cases if c.claims_empty]
    if not candidates:
        return MetricObservation(
            metric_id=METRIC_FAIL_CLOSED_EMPTY_CLAIMS,
            status="not_applicable",
            rate=None,
            numerator=0,
            denominator=0,
            threshold=threshold,
            notes="No empty-claims cases.",
        )
    closed = sum(1 for c in candidates if str(c.disposition).lower() != "ready")
    rate = _safe_rate(closed, len(candidates))
    status = "pass" if rate is not None and rate >= threshold else "fail"
    if rate is None:
        status = "unknown"
    return MetricObservation(
        metric_id=METRIC_FAIL_CLOSED_EMPTY_CLAIMS,
        status=status,
        rate=rate,
        numerator=closed,
        denominator=len(candidates),
        threshold=threshold,
        notes="Empty claims never ready.",
    )


def compute_fail_closed_unsearched(
    cases: Sequence[EvalCaseObservation],
    *,
    threshold: float = 1.0,
) -> MetricObservation:
    """Unsearched required corpora must not invent low risk without acceptance.

    Fail-closed: when unsearched gaps exist, disposition must not be ready
    *or* matter_risk must not be low (coverage penalty / residual visibility).
    """
    candidates = [c for c in cases if c.unsearched_required_corpora]
    if not candidates:
        return MetricObservation(
            metric_id=METRIC_FAIL_CLOSED_UNSEARCHED,
            status="not_applicable",
            rate=None,
            numerator=0,
            denominator=0,
            threshold=threshold,
            notes="No cases with unsearched required corpora.",
        )
    closed = sum(
        1
        for c in candidates
        if str(c.disposition).lower() != "ready"
        or str(c.matter_risk).lower() != "low"
    )
    rate = _safe_rate(closed, len(candidates))
    status = "pass" if rate is not None and rate >= threshold else "fail"
    if rate is None:
        status = "unknown"
    return MetricObservation(
        metric_id=METRIC_FAIL_CLOSED_UNSEARCHED,
        status=status,
        rate=rate,
        numerator=closed,
        denominator=len(candidates),
        threshold=threshold,
        notes="Unsearched corpora never ready+low without residual handling.",
    )


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PaarEvalMetricsReport:
    """Versioned offline metrics bundle (no private bodies)."""

    report_id: str
    content_digest: str
    metrics: tuple[MetricObservation, ...]
    case_count: int
    overall_status: str
    schema: str = PAAR_EVAL_METRICS_SCHEMA
    disclaimer: str = REVIEW_ONLY_EVAL_DISCLAIMER
    auto_file_blocked: bool = True
    case_summaries: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "interface": PAAR_EVAL_METRICS_INTERFACE,
            "code_version": PAAR_EVAL_METRICS_CODE_VERSION,
            "report_id": self.report_id,
            "content_digest": self.content_digest,
            "case_count": int(self.case_count),
            "overall_status": self.overall_status,
            "metrics": [m.to_dict() for m in self.metrics],
            "case_summaries": [dict(c) for c in self.case_summaries],
            "auto_file_blocked": True,
            "disclaimer": self.disclaimer,
            "metadata": dict(self.metadata),
        }
        return strip_private_bodies(payload)

    def write_json(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return out


def compute_paar_eval_metrics(
    cases: Sequence[EvalCaseObservation | Mapping[str, Any]],
    *,
    report_id: str | None = None,
    conflict_recall_threshold: float = 1.0,
    false_high_threshold: float = 0.0,
    fail_closed_threshold: float = 1.0,
    min_planted_risk: str = "medium",
    metadata: Mapping[str, str] | None = None,
) -> PaarEvalMetricsReport:
    """Compute offline PAAR metrics over observation cases.

    Parameters
    ----------
    cases:
        :class:`EvalCaseObservation` rows or plain mappings (content-free).
    conflict_recall_threshold:
        Minimum recall rate for planted cases (default 1.0 = all planted).
    false_high_threshold:
        Maximum allowed false-high rate on clean cases (default 0.0).
    fail_closed_threshold:
        Minimum rate of fail-closed outcomes on constrained cases.
    """
    normalized: list[EvalCaseObservation] = []
    for row in cases:
        if isinstance(row, EvalCaseObservation):
            normalized.append(row)
        elif isinstance(row, Mapping):
            normalized.append(EvalCaseObservation.from_dict(row))
        else:
            raise PaarEvalMetricsError(
                f"unsupported case type: {type(row)!r}",
                code="invalid_case",
            )

    metrics = (
        compute_conflict_recall_proxy(
            normalized,
            min_risk=min_planted_risk,
            threshold=conflict_recall_threshold,
        ),
        compute_false_high_rate(normalized, threshold=false_high_threshold),
        compute_fail_closed_missing_authority(
            normalized, threshold=fail_closed_threshold
        ),
        compute_fail_closed_empty_claims(
            normalized, threshold=fail_closed_threshold
        ),
        compute_fail_closed_unsearched(
            normalized, threshold=fail_closed_threshold
        ),
    )

    measurable = [m for m in metrics if m.status in {"pass", "fail"}]
    if not measurable:
        overall = "not_applicable"
    elif any(m.status == "fail" for m in measurable):
        overall = "fail"
    else:
        overall = "pass"

    case_summaries = tuple(
        strip_private_bodies(
            {
                "case_id": c.case_id,
                "variant": c.variant,
                "planted_overlap": c.planted_overlap,
                "matter_risk": c.matter_risk,
                "disposition": c.disposition,
                "conformance_status": c.conformance_status,
                "authority_corpus_present": c.authority_corpus_present,
                "claims_empty": c.claims_empty,
                "unsearched_required_corpora": list(c.unsearched_required_corpora),
            }
        )
        for c in normalized
    )

    digest_payload = {
        "schema": PAAR_EVAL_METRICS_SCHEMA,
        "metrics": [m.to_dict() for m in metrics],
        "case_summaries": list(case_summaries),
        "case_count": len(normalized),
        "overall_status": overall,
        "code_version": PAAR_EVAL_METRICS_CODE_VERSION,
    }
    digest = _sha256_hex(digest_payload)
    rid = report_id or f"paar-eval:{digest[:12]}"

    return PaarEvalMetricsReport(
        report_id=rid,
        content_digest=digest,
        metrics=metrics,
        case_count=len(normalized),
        overall_status=overall,
        case_summaries=case_summaries,
        metadata=dict(metadata or {}),
    )


def evaluate_fixture_bundle_dir(
    fixture_root: str | Path,
    *,
    run_reviews: bool = True,
    state_root: str | Path | None = None,
    generated_at_utc: str = "2026-08-06T00:00:00Z",
) -> PaarEvalMetricsReport:
    """Load PAAR fixture variants and optionally run unified review offline.

    When *run_reviews* is True, uses ``run_unified_application_review`` on each
    known variant under *fixture_root*. Falls back to manifest-only stubs when
    the orchestrator cannot run a variant.
    """
    root = Path(fixture_root)
    if not root.is_dir():
        raise PaarEvalMetricsError(
            f"fixture root missing: {root}", code="fixture_root_missing"
        )

    variants = ("planted_conflict", "clean_package", "missing_authority")
    observations: list[EvalCaseObservation] = []

    for variant in variants:
        vdir = root / variant
        if not vdir.is_dir():
            continue
        manifest_path = vdir / "manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}

        planted = variant == "planted_conflict"
        case_id = str(manifest.get("fixture_id") or f"paar-{variant}")

        if run_reviews:
            try:
                from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (
                    run_unified_application_review,
                )

                report = run_unified_application_review(
                    fixture_dir=vdir,
                    state_root=state_root,
                    persist=False,
                    include_diligence=False,
                    include_search=False,
                    generated_at_utc=generated_at_utc,
                )
                observations.append(
                    observation_from_unified_review(
                        report,
                        case_id=case_id,
                        variant=variant,
                        planted_overlap=planted,
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001 — fall through to stub
                _ = exc

        # Manifest-only stub observation (content-free, explicit unknown risk)
        expected = manifest.get("expected") or {}
        risk = "unknown"
        if planted:
            risk = str(expected.get("matter_risk_min") or "medium")
        observations.append(
            EvalCaseObservation(
                case_id=case_id,
                variant=variant,
                planted_overlap=planted,
                matter_risk=risk,
                disposition="not_ready"
                if variant == "missing_authority"
                else "review_required",
                conformance_status=(
                    "unknown" if variant == "missing_authority" else "unknown"
                ),
                authority_corpus_present=variant != "missing_authority",
                claims_empty=False,
                unsearched_required_corpora=(
                    ("foreign_patent", "npl")
                    if variant == "clean_package"
                    else ()
                ),
                metadata={"source": "manifest_stub"},
            )
        )

    return compute_paar_eval_metrics(
        observations,
        metadata={"fixture_root": str(root), "mode": "fixture_bundle"},
    )


__all__ = [
    "PAAR_EVAL_METRICS_SCHEMA",
    "PAAR_EVAL_METRICS_INTERFACE",
    "PAAR_EVAL_METRICS_CODE_VERSION",
    "METRIC_CONFLICT_RECALL_PROXY",
    "METRIC_FALSE_HIGH_RATE",
    "METRIC_FAIL_CLOSED_AUTHORITY",
    "METRIC_FAIL_CLOSED_EMPTY_CLAIMS",
    "METRIC_FAIL_CLOSED_UNSEARCHED",
    "REVIEW_ONLY_EVAL_DISCLAIMER",
    "PaarEvalMetricsError",
    "EvalCaseObservation",
    "MetricObservation",
    "PaarEvalMetricsReport",
    "strip_private_bodies",
    "observation_from_unified_review",
    "compute_conflict_recall_proxy",
    "compute_false_high_rate",
    "compute_fail_closed_missing_authority",
    "compute_fail_closed_empty_claims",
    "compute_fail_closed_unsearched",
    "compute_paar_eval_metrics",
    "evaluate_fixture_bundle_dir",
]
