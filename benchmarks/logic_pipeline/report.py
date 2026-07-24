"""Strict logic-pipeline report CLI and proof-overlap implementation.

This module implements the Hammer/Leanstral proof report and dispatches the
spaCy/SyMAI front-end report implemented in :mod:`frontend_report`.  Both are
trust boundaries, not presentation-only summaries.  The proof path requires
the complete paired pilot matrix, derives every aggregate from case-level
observations, keeps cold and warm cache modes separate, and admits a verified
outcome only when a native-kernel receipt is present.  Legacy S1 model claims
are retained as a safety diagnostic and never enter candidate metrics.

The checked-in artifact records a capability-preflight execution because the
requested Leanstral service was unavailable in the capture environment.  This
is intentional missingness: validation proves that the analysis/reporting
contract is complete without manufacturing efficacy measurements.
"""

from __future__ import annotations

if __package__ in {None, ""}:  # Support ``python benchmarks/.../report.py``.
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Final, Mapping, Sequence

from benchmarks.logic_pipeline import BENCHMARK_ID
from benchmarks.logic_pipeline.cases import (
    FROZEN_SPLIT_SHA256,
    load_reviewed_corpus,
)
from benchmarks.logic_pipeline.contracts import (
    CaseResultRecord,
    DEFAULT_PROTOCOL_SHA256,
    OutcomeStatus,
    ProtocolContractError,
    Split,
    VerificationAuthority,
    canonical_json,
)
from benchmarks.logic_pipeline.metrics import validate_kernel_bound_result
from benchmarks.logic_pipeline.variants import (
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
)


PROOF_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.proof-overlap-report.v1"
)
PROOF_OBSERVATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.proof-observation.v1"
)
PROOF_ANALYSIS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.proof-overlap-analysis.v1"
)
DEFAULT_PROOF_REPORT_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "proof-overlap-ordering-v1.json"
)
PRIMARY_VARIANT_IDS: Final = (
    "A2",
    "A3",
    "A4",
    "A6",
    "A7",
    "A8",
    "A9",
    "A10",
    "A11",
    "A12",
)
DIAGNOSTIC_VARIANT_IDS: Final = ("S1",)
CACHE_MODES: Final = ("cold", "warm")
ELIGIBLE_CASE_IDS: Final = (
    "pilot-p01",
    "pilot-p02",
    "pilot-p03",
    "pilot-p04",
    "pilot-p07",
    "pilot-p08",
    "pilot-p09",
)
EXCLUDED_CASE_IDS: Final = ("pilot-p05", "pilot-p06", "pilot-p10")
STATUS_VALUES: Final = frozenset(
    {
        "verified",
        "not_verified",
        "rejected",
        "unavailable",
        "excluded",
        "infrastructure_failure",
    }
)
SOURCE_VALUES: Final = frozenset({"hammer", "leanstral", "both", "none"})
CAPABILITY_STATUS_VALUES: Final = frozenset(
    {"available", "unavailable", "degraded"}
)
CAPABILITY_KEYS: Final = (
    "spacy",
    "symai",
    "llm_router",
    "hammer",
    "leanstral",
    "lean_kernel",
)
PAIRWISE_COMPARISONS: Final = (
    ("A2", "A3", "hammer_only_vs_fallback"),
    ("A3", "A6", "hammer_first_vs_leanstral_first"),
    ("A4", "A6", "conditional_hammer_first_vs_leanstral_first"),
    ("A4", "A9", "hammer_first_vs_no_hammer"),
    ("A4", "A10", "deterministic_vs_learned_selector"),
    ("A4", "A11", "deterministic_vs_llm_ranking"),
    ("A4", "A12", "conditional_vs_duplicated_work"),
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ProofReportError(ValueError):
    """Raised when proof evidence cannot support a report."""


def HSSLEV0526A41() -> str:
    """Return AST-verifiable evidence for proof overlap and ordering."""

    return (
        "kernel-bound Hammer and Leanstral proof overlap, ordering, "
        "and missingness report"
    )


def HSSLEV0519C80() -> str:
    """Return AST-verifiable evidence for front-end overlap measurement."""

    from benchmarks.logic_pipeline.frontend_report import (
        HSSLEV0519C80 as frontend_evidence,
    )

    return frontend_evidence()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ProofReportError(f"{field} must be an object with string keys")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    raise ProofReportError(
        f"{field} keys changed; missing={missing}, unknown={unknown}"
    )


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ProofReportError(f"{field} must be an array")
    return value


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ProofReportError(f"{field} must be a nonempty string")
    return value


def _safe_id(value: object, field: str) -> str:
    result = _string(value, field)
    if not _SAFE_ID.fullmatch(result) or result in {".", ".."}:
        raise ProofReportError(f"{field} must be a safe identifier")
    return result


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProofReportError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProofReportError(f"{field} must be boolean")
    return value


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofReportError(f"{field} must be a nonnegative integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofReportError(f"{field} must be a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ProofReportError(f"{field} must be a finite nonnegative number")
    return result


def _nullable_digest(value: object, field: str) -> str | None:
    return None if value is None else _digest(value, field)


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProofReportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _artifact_digest(value: Mapping[str, object]) -> str:
    body = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _proof_order(variant_id: str) -> list[str]:
    return [
        stage.value
        for stage in VARIANT_REGISTRY[variant_id].proof_order
    ]


def _validate_capabilities(value: object) -> dict[str, dict[str, str]]:
    data = _mapping(value, "capabilities")
    _exact(data, set(CAPABILITY_KEYS), "capabilities")
    result: dict[str, dict[str, str]] = {}
    for name in CAPABILITY_KEYS:
        record = _mapping(data[name], f"capabilities.{name}")
        _exact(record, {"status", "reason"}, f"capabilities.{name}")
        status = _string(record["status"], f"capabilities.{name}.status")
        if status not in CAPABILITY_STATUS_VALUES:
            raise ProofReportError(
                f"unsupported capabilities.{name}.status: {status!r}"
            )
        reason = _string(
            record["reason"],
            f"capabilities.{name}.reason",
            allow_empty=status == "available",
        )
        result[name] = {"status": status, "reason": reason}
    return result


def _validate_observation(value: object) -> dict[str, object]:
    data = _mapping(value, "observation")
    fields = {
        "schema",
        "case_id",
        "cache_mode",
        "variant_id",
        "status",
        "source_receipt_sha256",
        "case_result",
        "verification_authority",
        "kernel_accepted",
        "kernel_receipt_sha256",
        "verified_source",
        "proof_order",
        "model_claimed_verified",
        "hammer",
        "leanstral",
        "total_wall_time_ms",
        "model_calls",
        "missing_reason",
    }
    _exact(data, fields, "observation")
    if data["schema"] != PROOF_OBSERVATION_SCHEMA:
        raise ProofReportError("unsupported observation schema")
    case_id = _safe_id(data["case_id"], "observation.case_id")
    if case_id not in ELIGIBLE_CASE_IDS:
        raise ProofReportError(f"ineligible proof case: {case_id}")
    cache_mode = _string(data["cache_mode"], "observation.cache_mode")
    if cache_mode not in CACHE_MODES:
        raise ProofReportError(f"unsupported cache mode: {cache_mode!r}")
    variant_id = _safe_id(data["variant_id"], "observation.variant_id")
    if variant_id not in {*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS}:
        raise ProofReportError(f"unsupported proof variant: {variant_id!r}")
    status = _string(data["status"], "observation.status")
    if status not in STATUS_VALUES:
        raise ProofReportError(f"unsupported observation status: {status!r}")
    _digest(data["source_receipt_sha256"], "observation.source_receipt_sha256")
    if data["case_result"] is not None and not isinstance(
        data["case_result"], Mapping
    ):
        raise ProofReportError("observation.case_result must be an object or null")
    authority = data["verification_authority"]
    if authority not in {None, "native_kernel"}:
        raise ProofReportError("verification authority must be native_kernel or null")
    accepted = _boolean(data["kernel_accepted"], "observation.kernel_accepted")
    receipt = _nullable_digest(
        data["kernel_receipt_sha256"], "observation.kernel_receipt_sha256"
    )
    source = _string(data["verified_source"], "observation.verified_source")
    if source not in SOURCE_VALUES:
        raise ProofReportError(f"unsupported verified_source: {source!r}")
    order = _array(data["proof_order"], "observation.proof_order")
    if order != _proof_order(variant_id):
        raise ProofReportError(
            f"observation proof order differs from frozen {variant_id} policy"
        )
    model_claim = _boolean(
        data["model_claimed_verified"], "observation.model_claimed_verified"
    )

    hammer = _mapping(data["hammer"], "observation.hammer")
    _exact(
        hammer,
        {
            "invoked",
            "candidate_created",
            "premise_recall_numerator",
            "premise_recall_denominator",
            "premise_recall_missing_reason",
            "reconstruction_attempted",
            "reconstruction_succeeded",
            "wall_time_ms",
        },
        "observation.hammer",
    )
    hammer_invoked = _boolean(hammer["invoked"], "observation.hammer.invoked")
    hammer_candidate = _boolean(
        hammer["candidate_created"], "observation.hammer.candidate_created"
    )
    recall_numerator = hammer["premise_recall_numerator"]
    recall_denominator = hammer["premise_recall_denominator"]
    recall_reason = hammer["premise_recall_missing_reason"]
    if (recall_numerator is None) != (recall_denominator is None):
        raise ProofReportError("premise recall numerator and denominator pair")
    if recall_denominator is None:
        if not isinstance(recall_reason, str) or not recall_reason.strip():
            raise ProofReportError("unmeasured premise recall requires a reason")
    else:
        numerator = _count(recall_numerator, "premise recall numerator")
        denominator = _count(recall_denominator, "premise recall denominator")
        if denominator == 0 or numerator > denominator or recall_reason is not None:
            raise ProofReportError("invalid measured premise recall")
    reconstruction_attempted = _boolean(
        hammer["reconstruction_attempted"],
        "observation.hammer.reconstruction_attempted",
    )
    reconstruction_succeeded = _boolean(
        hammer["reconstruction_succeeded"],
        "observation.hammer.reconstruction_succeeded",
    )
    _number(hammer["wall_time_ms"], "observation.hammer.wall_time_ms")
    if hammer_candidate and not hammer_invoked:
        raise ProofReportError("Hammer candidate requires invocation")
    if reconstruction_attempted and not hammer_candidate:
        raise ProofReportError("Hammer reconstruction requires a candidate")
    if reconstruction_succeeded and not reconstruction_attempted:
        raise ProofReportError("Hammer reconstruction success requires an attempt")

    leanstral = _mapping(data["leanstral"], "observation.leanstral")
    _exact(
        leanstral,
        {
            "invoked",
            "candidate_created",
            "repair_attempted",
            "repair_succeeded",
            "wall_time_ms",
        },
        "observation.leanstral",
    )
    lean_invoked = _boolean(
        leanstral["invoked"], "observation.leanstral.invoked"
    )
    lean_candidate = _boolean(
        leanstral["candidate_created"],
        "observation.leanstral.candidate_created",
    )
    repair_attempted = _boolean(
        leanstral["repair_attempted"], "observation.leanstral.repair_attempted"
    )
    repair_succeeded = _boolean(
        leanstral["repair_succeeded"], "observation.leanstral.repair_succeeded"
    )
    _number(leanstral["wall_time_ms"], "observation.leanstral.wall_time_ms")
    if lean_candidate and not lean_invoked:
        raise ProofReportError("Leanstral candidate requires invocation")
    if repair_attempted and not lean_invoked:
        raise ProofReportError("Leanstral repair requires invocation")
    if repair_succeeded and not repair_attempted:
        raise ProofReportError("Leanstral repair success requires an attempt")

    _number(data["total_wall_time_ms"], "observation.total_wall_time_ms")
    _count(data["model_calls"], "observation.model_calls")
    missing_reason = data["missing_reason"]
    if status in {"unavailable", "excluded", "infrastructure_failure"}:
        _string(missing_reason, "observation.missing_reason")
    elif missing_reason is not None:
        raise ProofReportError("completed observations cannot have missing_reason")

    verified = status == "verified"
    if verified != (authority == "native_kernel" and accepted and receipt is not None):
        raise ProofReportError(
            "verified status requires native-kernel acceptance and receipt"
        )
    if not verified and (authority is not None or accepted or receipt is not None):
        raise ProofReportError("nonverified observation has proof authority")
    if source != "none" and not verified:
        raise ProofReportError("verified_source requires a verified observation")
    if source in {"hammer", "both"} and not reconstruction_succeeded:
        raise ProofReportError("Hammer verified source requires reconstruction")
    if source in {"leanstral", "both"} and not lean_candidate:
        raise ProofReportError("Leanstral verified source requires a draft")
    if variant_id == "S1":
        if verified or source != "none" or authority is not None:
            raise ProofReportError("S1 is non-authoritative safety evidence")
        if hammer_invoked or lean_invoked:
            raise ProofReportError("S1 cannot invoke Hammer or Leanstral")
    elif model_claim and verified and source == "none":
        raise ProofReportError("verified model claim has no proof source")
    return dict(data)


def _validate_measured_source(row: Mapping[str, object]) -> None:
    """Revalidate the complete durable result behind one measured row."""

    try:
        result = CaseResultRecord.from_dict(row["case_result"])
        validate_kernel_bound_result(result)
    except (ProtocolContractError, TypeError, ValueError) as exc:
        raise ProofReportError(
            "measured observations require a valid complete CaseResultRecord"
        ) from exc
    expected_identity = (
        row["case_id"],
        row["variant_id"],
        row["cache_mode"],
    )
    actual_identity = (
        result.case_id,
        result.variant_id,
        result.cache_mode.value,
    )
    if actual_identity != expected_identity:
        raise ProofReportError("measured case-result identity changed")
    if result.digest != row["source_receipt_sha256"]:
        raise ProofReportError("measured case-result digest changed")
    expected_status = {
        OutcomeStatus.VERIFIED: "verified",
        OutcomeStatus.NOT_VERIFIED: "not_verified",
        OutcomeStatus.REJECTED: "rejected",
        OutcomeStatus.UNAVAILABLE: "unavailable",
        OutcomeStatus.EXCLUDED: "excluded",
        OutcomeStatus.INFRASTRUCTURE_FAILURE: "infrastructure_failure",
    }[result.status]
    if row["status"] != expected_status:
        raise ProofReportError("measured case-result status changed")
    expected_authority = (
        "native_kernel"
        if result.verification_authority is VerificationAuthority.NATIVE_KERNEL
        else None
    )
    if (
        row["verification_authority"] != expected_authority
        or row["kernel_accepted"] != result.kernel_accepted
        or row["kernel_receipt_sha256"] != result.kernel_receipt_sha256
    ):
        raise ProofReportError("measured kernel authority projection changed")


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _variant_metric(
    variant_id: str,
    cache_mode: str,
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows = [
        row
        for row in observations
        if row["variant_id"] == variant_id and row["cache_mode"] == cache_mode
    ]
    status_counts = {
        status: sum(row["status"] == status for row in rows)
        for status in sorted(STATUS_VALUES)
    }
    eligible = (
        status_counts["verified"]
        + status_counts["not_verified"]
        + status_counts["rejected"]
    )
    hammer = [_mapping(row["hammer"], "hammer") for row in rows]
    lean = [_mapping(row["leanstral"], "leanstral") for row in rows]
    recall_rows = [
        row
        for row in hammer
        if row["premise_recall_denominator"] is not None
    ]
    recall_numerator = sum(int(row["premise_recall_numerator"]) for row in recall_rows)
    recall_denominator = sum(int(row["premise_recall_denominator"]) for row in recall_rows)
    hammer_candidates = sum(bool(row["candidate_created"]) for row in hammer)
    lean_candidates = sum(bool(row["candidate_created"]) for row in lean)
    reconstructions = sum(bool(row["reconstruction_attempted"]) for row in hammer)
    reconstruction_successes = sum(
        bool(row["reconstruction_succeeded"]) for row in hammer
    )
    repairs = sum(bool(row["repair_attempted"]) for row in lean)
    repair_successes = sum(bool(row["repair_succeeded"]) for row in lean)
    total_latency = sum(float(row["total_wall_time_ms"]) for row in rows)
    return {
        "variant_id": variant_id,
        "cache_mode": cache_mode,
        "attempt_count": len(rows),
        "status_counts": status_counts,
        "kernel_verified_count": status_counts["verified"],
        "kernel_verified_rate": _rate(status_counts["verified"], eligible),
        "premise_recall_numerator": (
            recall_numerator if recall_denominator else None
        ),
        "premise_recall_denominator": (
            recall_denominator if recall_denominator else None
        ),
        "premise_recall_at_budget": _rate(
            recall_numerator, recall_denominator
        ),
        "premise_recall_missing_reason": (
            None if recall_denominator else "gold_premise_set_unavailable"
        ),
        "hammer_candidate_count": hammer_candidates,
        "leanstral_candidate_count": lean_candidates,
        "candidate_overlap_count": sum(
            bool(h["candidate_created"]) and bool(l["candidate_created"])
            for h, l in zip(hammer, lean, strict=True)
        ),
        "reconstruction_attempt_count": reconstructions,
        "reconstruction_success_count": reconstruction_successes,
        "reconstruction_success_rate": _rate(
            reconstruction_successes, reconstructions
        ),
        "repair_attempt_count": repairs,
        "repair_success_count": repair_successes,
        "repair_success_rate": _rate(repair_successes, repairs),
        "hammer_unique_verified_count": sum(
            row["verified_source"] == "hammer" for row in rows
        ),
        "leanstral_unique_verified_count": sum(
            row["verified_source"] == "leanstral" for row in rows
        ),
        "both_source_verified_count": sum(
            row["verified_source"] == "both" for row in rows
        ),
        "total_wall_time_ms": total_latency,
        "mean_wall_time_ms": total_latency / len(rows),
        "model_calls": sum(int(row["model_calls"]) for row in rows),
    }


def _pairwise(
    left: str,
    right: str,
    label: str,
    cache_mode: str,
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    keyed = {
        (str(row["case_id"]), str(row["variant_id"])): row
        for row in observations
        if row["cache_mode"] == cache_mode
    }
    left_only: list[str] = []
    right_only: list[str] = []
    both: list[str] = []
    neither: list[str] = []
    latency_deltas: list[float] = []
    for case_id in ELIGIBLE_CASE_IDS:
        left_row = keyed[(case_id, left)]
        right_row = keyed[(case_id, right)]
        left_verified = left_row["status"] == "verified"
        right_verified = right_row["status"] == "verified"
        if left_verified and right_verified:
            both.append(case_id)
        elif left_verified:
            left_only.append(case_id)
        elif right_verified:
            right_only.append(case_id)
        else:
            neither.append(case_id)
        latency_deltas.append(
            float(right_row["total_wall_time_ms"])
            - float(left_row["total_wall_time_ms"])
        )
    return {
        "label": label,
        "cache_mode": cache_mode,
        "left_variant_id": left,
        "right_variant_id": right,
        "left_only_verified_case_ids": left_only,
        "right_only_verified_case_ids": right_only,
        "both_verified_case_ids": both,
        "neither_verified_case_ids": neither,
        "right_minus_left_total_wall_time_ms": sum(latency_deltas),
    }


def derive_proof_analysis(
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Derive all report metrics from validated case-level observations."""

    primary_metrics = [
        _variant_metric(variant, mode, observations)
        for mode in CACHE_MODES
        for variant in PRIMARY_VARIANT_IDS
    ]
    comparisons = [
        _pairwise(left, right, label, mode, observations)
        for mode in CACHE_MODES
        for left, right, label in PAIRWISE_COMPARISONS
    ]
    diagnostic_rows = [
        row for row in observations if row["variant_id"] == "S1"
    ]
    return {
        "schema": PROOF_ANALYSIS_SCHEMA,
        "coverage": {
            "expected_observation_count": (
                len(ELIGIBLE_CASE_IDS)
                * len(CACHE_MODES)
                * (len(PRIMARY_VARIANT_IDS) + len(DIAGNOSTIC_VARIANT_IDS))
            ),
            "observed_observation_count": len(observations),
            "eligible_case_count": len(ELIGIBLE_CASE_IDS),
            "primary_variant_count": len(PRIMARY_VARIANT_IDS),
            "diagnostic_variant_count": len(DIAGNOSTIC_VARIANT_IDS),
            "cache_mode_count": len(CACHE_MODES),
        },
        "primary_metrics": primary_metrics,
        "pairwise_comparisons": comparisons,
        "s1_diagnostic": {
            "attempt_count": len(diagnostic_rows),
            "model_verified_claim_count": sum(
                bool(row["model_claimed_verified"]) for row in diagnostic_rows
            ),
            "native_kernel_verified_count": 0,
            "included_in_primary_metrics": False,
        },
    }


def validate_proof_report(value: object) -> dict[str, object]:
    """Validate a complete report and recompute every serialized aggregate."""

    data = _mapping(value, "proof_report")
    fields = {
        "schema",
        "evidence",
        "benchmark_id",
        "run_id",
        "execution_mode",
        "protocol_sha256",
        "registry_sha256",
        "corpus_manifest_sha256",
        "pilot_split_sha256",
        "split",
        "eligible_case_ids",
        "excluded_case_ids",
        "cache_modes",
        "primary_variant_ids",
        "diagnostic_variant_ids",
        "capability_inventory_sha256",
        "capabilities",
        "observations",
        "analysis",
        "artifact_sha256",
    }
    _exact(data, fields, "proof_report")
    if data["schema"] != PROOF_REPORT_SCHEMA:
        raise ProofReportError("unsupported proof report schema")
    if data["evidence"] != HSSLEV0526A41():
        raise ProofReportError("proof report evidence marker changed")
    if data["benchmark_id"] != BENCHMARK_ID:
        raise ProofReportError("benchmark_id changed")
    _safe_id(data["run_id"], "run_id")
    execution_mode = _string(data["execution_mode"], "execution_mode")
    if execution_mode not in {"measured", "capability_preflight"}:
        raise ProofReportError("unsupported execution_mode")
    if data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256:
        raise ProofReportError("protocol digest changed")
    if data["registry_sha256"] != VARIANT_REGISTRY_SHA256:
        raise ProofReportError("variant registry digest changed")
    corpus = load_reviewed_corpus()
    if data["corpus_manifest_sha256"] != corpus.manifest_sha256:
        raise ProofReportError("corpus manifest digest changed")
    if data["pilot_split_sha256"] != FROZEN_SPLIT_SHA256[Split.PILOT]:
        raise ProofReportError("pilot split digest changed")
    if data["split"] != "pilot":
        raise ProofReportError("proof report must use pilot split")
    fixed_arrays = (
        ("eligible_case_ids", ELIGIBLE_CASE_IDS),
        ("excluded_case_ids", EXCLUDED_CASE_IDS),
        ("cache_modes", CACHE_MODES),
        ("primary_variant_ids", PRIMARY_VARIANT_IDS),
        ("diagnostic_variant_ids", DIAGNOSTIC_VARIANT_IDS),
    )
    for field, expected in fixed_arrays:
        if _array(data[field], field) != list(expected):
            raise ProofReportError(f"{field} differs from frozen proof scope")
    capabilities = _validate_capabilities(data["capabilities"])
    capability_digest = hashlib.sha256(
        canonical_json(capabilities).encode("utf-8")
    ).hexdigest()
    if data["capability_inventory_sha256"] != capability_digest:
        raise ProofReportError("capability inventory digest changed")

    raw_observations = _array(data["observations"], "observations")
    observations = [_validate_observation(item) for item in raw_observations]
    coordinates = [
        (
            str(row["case_id"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
        )
        for row in observations
    ]
    expected_coordinates = {
        (case_id, mode, variant)
        for case_id in ELIGIBLE_CASE_IDS
        for mode in CACHE_MODES
        for variant in (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS)
    }
    if len(coordinates) != len(set(coordinates)):
        raise ProofReportError("proof report contains duplicate observations")
    if set(coordinates) != expected_coordinates:
        missing = sorted(expected_coordinates - set(coordinates))
        extra = sorted(set(coordinates) - expected_coordinates)
        raise ProofReportError(
            f"proof observation matrix is incomplete; missing={missing}, extra={extra}"
        )
    expected_order = sorted(
        coordinates,
        key=lambda item: (
            CACHE_MODES.index(item[1]),
            (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS).index(item[2]),
            ELIGIBLE_CASE_IDS.index(item[0]),
        ),
    )
    if coordinates != expected_order:
        raise ProofReportError("proof observations are not in canonical order")

    if execution_mode == "capability_preflight":
        if not any(
            capabilities[name]["status"] != "available"
            for name in CAPABILITY_KEYS
        ):
            raise ProofReportError("preflight missingness requires a capability gap")
        if any(row["status"] != "unavailable" for row in observations):
            raise ProofReportError(
                "capability-preflight observations must remain unavailable"
            )
        if any(row["case_result"] is not None for row in observations):
            raise ProofReportError(
                "capability preflight cannot embed fabricated case results"
            )
    else:
        for row in observations:
            if row["case_result"] is None:
                raise ProofReportError(
                    "measured observations require full case-result evidence"
                )
            _validate_measured_source(row)
    derived = derive_proof_analysis(observations)
    if data["analysis"] != derived:
        raise ProofReportError("serialized proof analysis differs from observations")
    expected_digest = _artifact_digest(data)
    if data["artifact_sha256"] != expected_digest:
        raise ProofReportError("proof report artifact digest changed")
    return dict(data)


def load_proof_report(path: str | Path = DEFAULT_PROOF_REPORT_PATH) -> dict[str, object]:
    """Load canonical newline JSON and validate the full proof report."""

    report_path = Path(path)
    try:
        text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProofReportError(f"cannot read proof report: {report_path}") from exc
    if not text.endswith("\n"):
        raise ProofReportError("proof report is not canonical newline JSON")
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ProofReportError) as exc:
        raise ProofReportError("proof report is not strict JSON") from exc
    if canonical_json(value) + "\n" != text:
        raise ProofReportError("proof report is not canonical JSON")
    return validate_proof_report(value)


def create_capability_preflight_report() -> dict[str, object]:
    """Create the canonical checked-in missingness evidence.

    The capture reflects the repository preflight on 2026-07-24.  Receipt
    digests bind each scheduled coordinate to the immutable inventory digest;
    they are not kernel receipts and can never enter the verified numerator.
    """

    capabilities = {
        "spacy": {
            "status": "unavailable",
            "reason": "requested en_core_web_sm pipeline is not installed",
        },
        "symai": {
            "status": "degraded",
            "reason": "provider and model identity are incomplete",
        },
        "llm_router": {
            "status": "degraded",
            "reason": "provider and model identity are incomplete",
        },
        "hammer": {
            "status": "available",
            "reason": "",
        },
        "leanstral": {
            "status": "unavailable",
            "reason": "endpoint and model identity are not configured",
        },
        "lean_kernel": {
            "status": "available",
            "reason": "",
        },
    }
    capability_inventory_sha256 = hashlib.sha256(
        canonical_json(capabilities).encode("utf-8")
    ).hexdigest()
    observations: list[dict[str, object]] = []
    for mode in CACHE_MODES:
        for variant in (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS):
            definition = VARIANT_REGISTRY[variant]
            missing = []
            if variant != "S1" and capabilities["spacy"]["status"] != "available":
                missing.append("spacy")
            if any(stage.value == "symai" for stage in definition.stages):
                if capabilities["symai"]["status"] != "available":
                    missing.append("symai")
                if capabilities["llm_router"]["status"] != "available":
                    missing.append("llm_router")
            if any(stage.value == "leanstral" for stage in definition.stages):
                if capabilities["leanstral"]["status"] != "available":
                    missing.append("leanstral")
            missing_reason = "capability unavailable or degraded: " + ", ".join(
                dict.fromkeys(missing)
            )
            for case_id in ELIGIBLE_CASE_IDS:
                coordinate = {
                    "capability_inventory_sha256": capability_inventory_sha256,
                    "case_id": case_id,
                    "cache_mode": mode,
                    "variant_id": variant,
                    "missing_reason": missing_reason,
                }
                observations.append(
                    {
                        "schema": PROOF_OBSERVATION_SCHEMA,
                        "case_id": case_id,
                        "cache_mode": mode,
                        "variant_id": variant,
                        "status": "unavailable",
                        "source_receipt_sha256": hashlib.sha256(
                            canonical_json(coordinate).encode("utf-8")
                        ).hexdigest(),
                        "case_result": None,
                        "verification_authority": None,
                        "kernel_accepted": False,
                        "kernel_receipt_sha256": None,
                        "verified_source": "none",
                        "proof_order": _proof_order(variant),
                        "model_claimed_verified": False,
                        "hammer": {
                            "invoked": False,
                            "candidate_created": False,
                            "premise_recall_numerator": None,
                            "premise_recall_denominator": None,
                            "premise_recall_missing_reason": (
                                "gold_premise_set_unavailable"
                            ),
                            "reconstruction_attempted": False,
                            "reconstruction_succeeded": False,
                            "wall_time_ms": 0.0,
                        },
                        "leanstral": {
                            "invoked": False,
                            "candidate_created": False,
                            "repair_attempted": False,
                            "repair_succeeded": False,
                            "wall_time_ms": 0.0,
                        },
                        "total_wall_time_ms": 0.0,
                        "model_calls": 0,
                        "missing_reason": missing_reason,
                    }
                )
    report: dict[str, object] = {
        "schema": PROOF_REPORT_SCHEMA,
        "evidence": HSSLEV0526A41(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": "proof-overlap-ordering-v1",
        "execution_mode": "capability_preflight",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": load_reviewed_corpus().manifest_sha256,
        "pilot_split_sha256": FROZEN_SPLIT_SHA256[Split.PILOT],
        "split": "pilot",
        "eligible_case_ids": list(ELIGIBLE_CASE_IDS),
        "excluded_case_ids": list(EXCLUDED_CASE_IDS),
        "cache_modes": list(CACHE_MODES),
        "primary_variant_ids": list(PRIMARY_VARIANT_IDS),
        "diagnostic_variant_ids": list(DIAGNOSTIC_VARIANT_IDS),
        "capability_inventory_sha256": capability_inventory_sha256,
        "capabilities": capabilities,
        "observations": observations,
        "analysis": derive_proof_analysis(observations),
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _artifact_digest(report)
    return validate_proof_report(report)


def _summary(report: Mapping[str, object]) -> dict[str, object]:
    analysis = _mapping(report["analysis"], "analysis")
    coverage = _mapping(analysis["coverage"], "coverage")
    metrics = _array(analysis["primary_metrics"], "primary_metrics")
    return {
        "section": "proof",
        "status": "valid",
        "execution_mode": report["execution_mode"],
        "artifact_sha256": report["artifact_sha256"],
        "observation_count": coverage["observed_observation_count"],
        "kernel_verified_count": sum(
            int(_mapping(item, "metric")["kernel_verified_count"])
            for item in metrics
        ),
        "missingness_retained": any(
            _mapping(item, "metric")["kernel_verified_rate"] is None
            for item in metrics
        ),
        "s1_included_in_primary_metrics": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate logic-pipeline benchmark reports"
    )
    parser.add_argument(
        "--section",
        choices=("frontend", "proof"),
        required=True,
    )
    parser.add_argument("--validate", action="store_true", required=True)
    parser.add_argument(
        "--results-path",
        type=Path,
        default=None,
        help="override the selected section's canonical report JSON path",
    )
    args = parser.parse_args(argv)
    if args.section == "frontend":
        from benchmarks.logic_pipeline.frontend_report import (
            DEFAULT_FRONTEND_REPORT_PATH,
            FrontendReportError,
            frontend_summary,
            load_frontend_report,
        )

        try:
            report = load_frontend_report(
                args.results_path or DEFAULT_FRONTEND_REPORT_PATH
            )
        except FrontendReportError as exc:
            parser.error(str(exc))
        summary = frontend_summary(report)
    else:
        try:
            report = load_proof_report(
                args.results_path or DEFAULT_PROOF_REPORT_PATH
            )
        except ProofReportError as exc:
            parser.error(str(exc))
        summary = _summary(report)
    sys.stdout.write(canonical_json(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CACHE_MODES",
    "DEFAULT_PROOF_REPORT_PATH",
    "DIAGNOSTIC_VARIANT_IDS",
    "ELIGIBLE_CASE_IDS",
    "EXCLUDED_CASE_IDS",
    "HSSLEV0519C80",
    "HSSLEV0526A41",
    "PRIMARY_VARIANT_IDS",
    "PROOF_ANALYSIS_SCHEMA",
    "PROOF_OBSERVATION_SCHEMA",
    "PROOF_REPORT_SCHEMA",
    "ProofReportError",
    "create_capability_preflight_report",
    "derive_proof_analysis",
    "load_proof_report",
    "validate_proof_report",
]
