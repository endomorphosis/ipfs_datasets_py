"""Strict spaCy/SyMAI front-end overlap reports.

The report is an evidence boundary rather than a presentation-only summary.
It freezes the complete pilot and development comparison matrix, validates
case-level provenance, recomputes every aggregate, and keeps capability
missingness distinct from semantic failure.  A measured replay must embed the
full :class:`CaseResultRecord` that produced each observation.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Final, Mapping, Sequence

from benchmarks.logic_pipeline import BENCHMARK_ID
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    load_unsealed_pilot_development,
)
from benchmarks.logic_pipeline.contracts import (
    CaseResultRecord,
    DEFAULT_PROTOCOL_SHA256,
    OutcomeStatus,
    ProtocolContractError,
    Split,
    StageName,
    canonical_json,
)
from benchmarks.logic_pipeline.metrics import (
    MetricsContractError,
    validate_kernel_bound_result,
)
from benchmarks.logic_pipeline.variants import (
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
)


FRONTEND_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.frontend-overlap-report.v1"
)
FRONTEND_OBSERVATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.frontend-observation.v1"
)
FRONTEND_ANALYSIS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.frontend-overlap-analysis.v1"
)
DEFAULT_FRONTEND_REPORT_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "frontend-overlap-v1.json"
)
FRONTEND_VARIANT_IDS: Final = ("A0", "A1", "A4", "A5", "A7", "A8")
CACHE_MODES: Final = ("cold", "warm")
SPLITS: Final = ("pilot", "development")
CAPABILITY_KEYS: Final = (
    "current_modal_codec",
    "spacy_full_model",
    "regex_legal_parser",
    "spacy_blank_model",
    "symai",
    "llm_router",
)
REQUIRED_CAPABILITIES: Final = {
    "A0": ("current_modal_codec",),
    "A1": ("spacy_full_model",),
    "A4": ("spacy_full_model", "symai", "llm_router"),
    "A5": ("spacy_full_model", "symai", "llm_router"),
    "A7": ("regex_legal_parser", "symai", "llm_router"),
    "A8": ("spacy_blank_model", "symai", "llm_router"),
}
STATUS_VALUES: Final = frozenset(
    {
        "semantically_correct",
        "semantically_incorrect",
        "unavailable",
        "infrastructure_failure",
    }
)
CAPABILITY_STATUS_VALUES: Final = frozenset(
    {"available", "unavailable", "degraded"}
)
EXPECTED_CLASSES: Final = frozenset(
    {"proved", "disproved", "ambiguous", "unsupported"}
)
PAIRWISE_COMPARISONS: Final = (
    ("A0", "A1", "current_route_vs_full_spacy"),
    ("A1", "A4", "symai_off_vs_ambiguity_gated"),
    ("A4", "A5", "ambiguity_gated_vs_always_symai"),
    ("A4", "A7", "full_spacy_vs_regex_legal"),
    ("A4", "A8", "full_spacy_vs_blank_model"),
    ("A7", "A8", "regex_legal_vs_blank_model"),
)
SYMAI_COMPARATORS: Final = {
    "A4": "A1",
    "A5": "A4",
    "A7": "A1",
    "A8": "A1",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class FrontendReportError(ValueError):
    """Raised when front-end evidence cannot support the frozen report."""


def HSSLEV0519C80() -> str:
    """Return AST-verifiable evidence for spaCy/SyMAI overlap measurement."""

    return (
        "paired spaCy and SyMAI front-end overlap, unique-win, "
        "unnecessary-call, and capability-missingness report"
    )


def HSSLEV1159F06() -> str:
    """Return objective evidence for receipt-driven measured front-end reports."""

    return (
        "complete source-bound case receipts produce measured front-end "
        "quality, latency, routing, and missingness evidence"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise FrontendReportError(f"{field} must be an object with string keys")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise FrontendReportError(
            f"{field} keys changed; "
            f"missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise FrontendReportError(f"{field} must be an array")
    return value


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise FrontendReportError(f"{field} must be a nonempty string")
    return value


def _safe_id(value: object, field: str) -> str:
    result = _string(value, field)
    if not _SAFE_ID.fullmatch(result) or result in {".", ".."}:
        raise FrontendReportError(f"{field} must be a safe identifier")
    return result


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise FrontendReportError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _nullable_digest(value: object, field: str) -> str | None:
    return None if value is None else _digest(value, field)


def _nullable_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise FrontendReportError(f"{field} must be boolean or null")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise FrontendReportError(f"{field} must be boolean")
    return value


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FrontendReportError(f"{field} must be a nonnegative integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrontendReportError(f"{field} must be a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise FrontendReportError(f"{field} must be a finite nonnegative number")
    return result


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FrontendReportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _artifact_digest(value: Mapping[str, object]) -> str:
    body = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _case_catalog() -> tuple[
    dict[str, dict[str, object]], dict[str, list[str]]
]:
    _manifest, cases = load_unsealed_pilot_development()
    catalog: dict[str, dict[str, object]] = {}
    by_split = {split: [] for split in SPLITS}
    for case in cases:
        split = case.split.value
        if split not in SPLITS:
            continue
        row = {
            "split": split,
            "stratum": case.stratum,
            "expected_class": case.expected_class.value,
            "expected_ir": dict(case.expected_ir),
            "source_sha256": case.source_sha256,
        }
        catalog[case.case_id] = row
        by_split[split].append(case.case_id)
    for split in SPLITS:
        if len(by_split[split]) != 10:
            raise FrontendReportError(
                f"frozen {split} scope must contain exactly ten reviewed cases"
            )
    return catalog, by_split


def _variant_identity(variant_id: str) -> tuple[str, str]:
    definition = VARIANT_REGISTRY[variant_id]
    return definition.spacy_mode.value, definition.symai_policy.value


def _validate_capabilities(value: object) -> dict[str, dict[str, str]]:
    data = _mapping(value, "capabilities")
    _exact(data, set(CAPABILITY_KEYS), "capabilities")
    result: dict[str, dict[str, str]] = {}
    for name in CAPABILITY_KEYS:
        record = _mapping(data[name], f"capabilities.{name}")
        _exact(record, {"status", "reason"}, f"capabilities.{name}")
        status = _string(record["status"], f"capabilities.{name}.status")
        if status not in CAPABILITY_STATUS_VALUES:
            raise FrontendReportError(
                f"unsupported capabilities.{name}.status: {status!r}"
            )
        reason = _string(
            record["reason"],
            f"capabilities.{name}.reason",
            allow_empty=status == "available",
        )
        result[name] = {"status": status, "reason": reason}
    return result


def _semantic_success(row: Mapping[str, object]) -> bool | None:
    if row["status"] in {"unavailable", "infrastructure_failure"}:
        return None
    return bool(
        row["normalized_ir_exact_match"]
        or row["deterministic_semantic_equivalence"]
    )


def _validate_measured_source(
    row: Mapping[str, object], *, expected_run_id: str | None = None
) -> None:
    raw = row["case_result"]
    if raw is None:
        raise FrontendReportError(
            "measured observations require full case-result evidence"
        )
    try:
        result = CaseResultRecord.from_dict(raw)
        validate_kernel_bound_result(result)
    except (
        MetricsContractError,
        ProtocolContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise FrontendReportError("case_result failed strict validation") from exc
    if expected_run_id is not None and result.run_id != expected_run_id:
        raise FrontendReportError(
            "case_result run id differs from the front-end report"
        )
    for field in ("case_id", "variant_id"):
        if getattr(result, field) != row[field]:
            raise FrontendReportError(
                f"case_result {field} differs from the observation"
            )
    if result.split.value != row["split"]:
        raise FrontendReportError("case_result split differs from the observation")
    if result.cache_mode.value != row["cache_mode"]:
        raise FrontendReportError(
            "case_result cache mode differs from the observation"
        )
    if result.digest != row["source_receipt_sha256"]:
        raise FrontendReportError("source receipt does not match case_result")
    definition = VARIANT_REGISTRY[str(row["variant_id"])]
    expected_stages = tuple(definition.stages)
    actual_stages = tuple(item.stage for item in result.stages)
    terminal_missing = result.status in {
        OutcomeStatus.UNAVAILABLE,
        OutcomeStatus.INFRASTRUCTURE_FAILURE,
    }
    route_matches = (
        actual_stages == expected_stages[: len(actual_stages)]
        if terminal_missing
        else actual_stages == expected_stages
    )
    if not route_matches:
        raise FrontendReportError("case_result stages differ from requested route")
    by_stage = {item.stage: item for item in result.stages}

    def graph_invoked(stage_name: StageName) -> bool:
        stage = by_stage.get(stage_name)
        if stage is None:
            return False
        invoked = stage.provenance.effective_identity.get("graph_invoked")
        if type(invoked) is not bool:
            raise FrontendReportError(
                f"{stage_name.value} stage lacks an explicit graph_invoked receipt"
            )
        return invoked

    spacy_invoked = graph_invoked(StageName.SPACY)
    symai_invoked = graph_invoked(StageName.SYMAI)
    if row["spacy_invoked"] is not spacy_invoked:
        raise FrontendReportError(
            "spacy_invoked differs from the case_result graph receipt"
        )
    if row["symai_invoked"] is not symai_invoked:
        raise FrontendReportError(
            "symai_invoked differs from the case_result graph receipt"
        )
    total_calls = sum(item.telemetry.model_calls for item in result.stages)
    symai_calls = sum(
        item.telemetry.model_calls
        for item in result.stages
        if item.stage is StageName.SYMAI
    )
    total_time = round(
        sum(item.telemetry.wall_time_ms for item in result.stages), 6
    )
    if row["model_calls"] != total_calls or row["symai_model_calls"] != symai_calls:
        raise FrontendReportError("model-call telemetry differs from case_result")
    if not math.isclose(
        float(row["total_wall_time_ms"]), total_time, abs_tol=1e-6
    ):
        raise FrontendReportError("latency telemetry differs from case_result")

    expected_missing_status = {
        OutcomeStatus.UNAVAILABLE: "unavailable",
        OutcomeStatus.INFRASTRUCTURE_FAILURE: "infrastructure_failure",
    }.get(result.status)
    if expected_missing_status is not None:
        if row["status"] != expected_missing_status:
            raise FrontendReportError(
                "case_result missingness differs from the observation"
            )
        return
    if result.status is OutcomeStatus.EXCLUDED:
        raise FrontendReportError(
            "measured front-end scope cannot contain excluded case results"
        )
    if row["status"] in {"unavailable", "infrastructure_failure"}:
        raise FrontendReportError(
            "front-end missingness is not supported by the case result"
        )

    signature = row["semantic_signature_sha256"]
    if signature is None:
        raise FrontendReportError(
            "measured observations require a semantic signature"
        )
    source_digest: str | None = None
    for stage in reversed(result.stages):
        stage_data = stage.to_dict()["data"]
        if not isinstance(stage_data, Mapping):  # pragma: no cover - contract
            continue
        if stage.stage is StageName.SYMAI:
            candidate = stage_data.get("candidate_ir")
            if candidate is not None:
                source_digest = hashlib.sha256(
                    canonical_json(candidate).encode("utf-8")
                ).hexdigest()
                break
        if stage.stage is StageName.SPACY:
            modal_ir = stage_data.get("modal_ir")
            if modal_ir is not None:
                source_digest = hashlib.sha256(
                    canonical_json(modal_ir).encode("utf-8")
                ).hexdigest()
                break
        if stage.stage is StageName.COMPILER:
            candidate_digest = stage_data.get("modal_ir_sha256")
            if isinstance(candidate_digest, str) and _SHA256.fullmatch(
                candidate_digest
            ):
                source_digest = candidate_digest
                break
    if source_digest is None or signature != source_digest:
        raise FrontendReportError(
            "semantic signature is not bound to a front-end stage payload"
        )


def _validate_observation(
    value: object, catalog: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    data = _mapping(value, "observation")
    fields = {
        "schema",
        "case_id",
        "split",
        "stratum",
        "expected_class",
        "cache_mode",
        "variant_id",
        "spacy_mode",
        "symai_policy",
        "status",
        "source_receipt_sha256",
        "case_result",
        "semantic_signature_sha256",
        "normalized_ir_exact_match",
        "deterministic_semantic_equivalence",
        "semantic_validator_receipt_sha256",
        "predicted_class",
        "ambiguity_classification_correct",
        "fail_closed_classification_correct",
        "spacy_invoked",
        "symai_invoked",
        "symai_model_calls",
        "total_wall_time_ms",
        "model_calls",
        "missing_reason",
    }
    _exact(data, fields, "observation")
    if data["schema"] != FRONTEND_OBSERVATION_SCHEMA:
        raise FrontendReportError("unsupported observation schema")
    case_id = _safe_id(data["case_id"], "observation.case_id")
    if case_id not in catalog:
        raise FrontendReportError(f"case is outside frozen front-end scope: {case_id}")
    case = catalog[case_id]
    split = _string(data["split"], "observation.split")
    stratum = _safe_id(data["stratum"], "observation.stratum")
    expected_class = _string(
        data["expected_class"], "observation.expected_class"
    )
    if (
        split != case["split"]
        or stratum != case["stratum"]
        or expected_class != case["expected_class"]
    ):
        raise FrontendReportError(
            "observation case split/stratum/class differs from reviewed corpus"
        )
    cache_mode = _string(data["cache_mode"], "observation.cache_mode")
    if cache_mode not in CACHE_MODES:
        raise FrontendReportError(f"unsupported cache mode: {cache_mode!r}")
    variant_id = _safe_id(data["variant_id"], "observation.variant_id")
    if variant_id not in FRONTEND_VARIANT_IDS:
        raise FrontendReportError(f"unsupported front-end arm: {variant_id}")
    spacy_mode, symai_policy = _variant_identity(variant_id)
    if data["spacy_mode"] != spacy_mode or data["symai_policy"] != symai_policy:
        raise FrontendReportError(
            "observation front-end policy differs from frozen variant registry"
        )
    status = _string(data["status"], "observation.status")
    if status not in STATUS_VALUES:
        raise FrontendReportError(f"unsupported observation status: {status!r}")
    _digest(data["source_receipt_sha256"], "observation.source_receipt_sha256")
    semantic_signature = _nullable_digest(
        data["semantic_signature_sha256"],
        "observation.semantic_signature_sha256",
    )
    exact_match = _nullable_bool(
        data["normalized_ir_exact_match"],
        "observation.normalized_ir_exact_match",
    )
    equivalence = _nullable_bool(
        data["deterministic_semantic_equivalence"],
        "observation.deterministic_semantic_equivalence",
    )
    validator_receipt = _nullable_digest(
        data["semantic_validator_receipt_sha256"],
        "observation.semantic_validator_receipt_sha256",
    )
    predicted = data["predicted_class"]
    if predicted is not None:
        predicted = _string(predicted, "observation.predicted_class")
        if predicted not in EXPECTED_CLASSES:
            raise FrontendReportError(
                f"unsupported predicted class: {predicted!r}"
            )
    ambiguity_correct = _nullable_bool(
        data["ambiguity_classification_correct"],
        "observation.ambiguity_classification_correct",
    )
    fail_closed = _nullable_bool(
        data["fail_closed_classification_correct"],
        "observation.fail_closed_classification_correct",
    )
    spacy_invoked = _boolean(
        data["spacy_invoked"], "observation.spacy_invoked"
    )
    symai_invoked = _boolean(
        data["symai_invoked"], "observation.symai_invoked"
    )
    symai_calls = _count(
        data["symai_model_calls"], "observation.symai_model_calls"
    )
    model_calls = _count(data["model_calls"], "observation.model_calls")
    _number(data["total_wall_time_ms"], "observation.total_wall_time_ms")
    if symai_calls > model_calls:
        raise FrontendReportError("SyMAI calls cannot exceed total model calls")
    if symai_calls and not symai_invoked:
        raise FrontendReportError("SyMAI calls require an invoked SyMAI stage")
    missing_reason = data["missing_reason"]
    if missing_reason is not None:
        _string(missing_reason, "observation.missing_reason")

    unavailable = status in {"unavailable", "infrastructure_failure"}
    metric_values = (
        exact_match,
        equivalence,
        predicted,
        ambiguity_correct,
        fail_closed,
    )
    if unavailable:
        if any(item is not None for item in metric_values):
            raise FrontendReportError(
                "unavailable observations cannot carry semantic scores"
            )
        if data["semantic_signature_sha256"] is not None:
            raise FrontendReportError(
                "unavailable observations cannot carry semantic output"
            )
        if missing_reason is None:
            raise FrontendReportError(
                "unavailable observations require a missing reason"
            )
    else:
        if any(item is None for item in (exact_match, equivalence, predicted)):
            raise FrontendReportError(
                "measured semantic observations require quality metrics"
            )
        if semantic_signature is None:
            raise FrontendReportError(
                "measured semantic observations require a semantic signature"
            )
        expected_ir_sha256 = hashlib.sha256(
            canonical_json(case["expected_ir"]).encode("utf-8")
        ).hexdigest()
        if exact_match is not (semantic_signature == expected_ir_sha256):
            raise FrontendReportError(
                "normalized-IR exact-match score differs from reviewed target"
            )
        if validator_receipt is None:
            raise FrontendReportError(
                "measured semantic observations require a validator receipt"
            )
        expected_ambiguous = expected_class == "ambiguous"
        if expected_ambiguous and ambiguity_correct is None:
            raise FrontendReportError(
                "ambiguous cases require classification evidence"
            )
        if expected_ambiguous and ambiguity_correct is not (
            predicted == expected_class
        ):
            raise FrontendReportError(
                "ambiguity score differs from the reviewed class"
            )
        expected_fail_closed = expected_class in {"disproved", "unsupported"}
        if expected_fail_closed and fail_closed is None:
            raise FrontendReportError(
                "negative cases require fail-closed classification evidence"
            )
        if expected_fail_closed and fail_closed is not (
            predicted == expected_class
        ):
            raise FrontendReportError(
                "fail-closed score differs from the reviewed class"
            )
        if status == "semantically_correct" and not (exact_match or equivalence):
            raise FrontendReportError(
                "semantically correct status requires exact or equivalent IR"
            )
        if status == "semantically_incorrect" and (exact_match or equivalence):
            raise FrontendReportError(
                "semantically incorrect status conflicts with semantic scores"
            )
        if missing_reason is not None:
            raise FrontendReportError(
                "measured semantic observations cannot carry missingness"
            )
    return dict(data)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(percentile * len(ordered)) - 1
    return round(ordered[max(0, min(rank, len(ordered) - 1))], 6)


def _metric_record(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    measured = [row for row in rows if _semantic_success(row) is not None]
    correct = [row for row in measured if _semantic_success(row)]
    ambiguous = [
        row for row in measured if row["expected_class"] == "ambiguous"
    ]
    fail_closed = [
        row
        for row in measured
        if row["expected_class"] in {"disproved", "unsupported"}
    ]
    latencies = [float(row["total_wall_time_ms"]) for row in measured]
    return {
        "scheduled_count": len(rows),
        "measured_count": len(measured),
        "unavailable_count": sum(
            row["status"] == "unavailable" for row in rows
        ),
        "infrastructure_failure_count": sum(
            row["status"] == "infrastructure_failure" for row in rows
        ),
        "semantic_quality_rate": _rate(len(correct), len(measured)),
        "normalized_ir_exact_match_rate": _rate(
            sum(bool(row["normalized_ir_exact_match"]) for row in measured),
            len(measured),
        ),
        "deterministic_semantic_equivalence_rate": _rate(
            sum(
                bool(row["deterministic_semantic_equivalence"])
                for row in measured
            ),
            len(measured),
        ),
        "ambiguity_classification_accuracy": _rate(
            sum(
                bool(row["ambiguity_classification_correct"])
                for row in ambiguous
            ),
            len(ambiguous),
        ),
        "unsupported_fail_closed_accuracy": _rate(
            sum(
                bool(row["fail_closed_classification_correct"])
                for row in fail_closed
            ),
            len(fail_closed),
        ),
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "model_calls": sum(int(row["model_calls"]) for row in measured),
        "symai_model_calls": sum(
            int(row["symai_model_calls"]) for row in measured
        ),
    }


def derive_frontend_analysis(
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Derive all paired quality, overlap, regression, and call metrics."""

    rows = list(observations)
    by_coordinate = {
        (
            str(row["split"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
            str(row["case_id"]),
        ): row
        for row in rows
    }
    variant_metrics: list[dict[str, object]] = []
    for split in SPLITS:
        strata = sorted(
            {str(row["stratum"]) for row in rows if row["split"] == split}
        )
        for mode in CACHE_MODES:
            for variant in FRONTEND_VARIANT_IDS:
                selected = [
                    row
                    for row in rows
                    if row["split"] == split
                    and row["cache_mode"] == mode
                    and row["variant_id"] == variant
                ]
                variant_metrics.append(
                    {
                        "split": split,
                        "cache_mode": mode,
                        "variant_id": variant,
                        "metrics": _metric_record(selected),
                        "by_stratum": [
                            {
                                "stratum": stratum,
                                "metrics": _metric_record(
                                    [
                                        row
                                        for row in selected
                                        if row["stratum"] == stratum
                                    ]
                                ),
                            }
                            for stratum in strata
                        ],
                    }
                )

    pairwise: list[dict[str, object]] = []
    regressions: list[dict[str, object]] = []
    unique_wins: list[dict[str, object]] = []
    unnecessary_calls: list[dict[str, object]] = []
    catalog, by_split = _case_catalog()
    del catalog
    for split in SPLITS:
        for mode in CACHE_MODES:
            for left, right, label in PAIRWISE_COMPARISONS:
                left_only: list[str] = []
                right_only: list[str] = []
                both: list[str] = []
                neither: list[str] = []
                unavailable: list[str] = []
                disagreements: list[dict[str, object]] = []
                for case_id in by_split[split]:
                    left_row = by_coordinate[(split, mode, left, case_id)]
                    right_row = by_coordinate[(split, mode, right, case_id)]
                    left_ok = _semantic_success(left_row)
                    right_ok = _semantic_success(right_row)
                    if left_ok is None or right_ok is None:
                        unavailable.append(case_id)
                        continue
                    if left_ok and not right_ok:
                        left_only.append(case_id)
                    elif right_ok and not left_ok:
                        right_only.append(case_id)
                    elif left_ok and right_ok:
                        both.append(case_id)
                    else:
                        neither.append(case_id)
                    if (
                        left_row["semantic_signature_sha256"]
                        != right_row["semantic_signature_sha256"]
                    ):
                        disagreements.append(
                            {
                                "case_id": case_id,
                                "stratum": left_row["stratum"],
                                "left_semantic_signature_sha256": left_row[
                                    "semantic_signature_sha256"
                                ],
                                "right_semantic_signature_sha256": right_row[
                                    "semantic_signature_sha256"
                                ],
                                "left_semantically_correct": left_ok,
                                "right_semantically_correct": right_ok,
                            }
                        )
                record = {
                    "split": split,
                    "cache_mode": mode,
                    "label": label,
                    "left_variant_id": left,
                    "right_variant_id": right,
                    "left_only_semantic_win_case_ids": left_only,
                    "right_only_semantic_win_case_ids": right_only,
                    "both_correct_case_ids": both,
                    "neither_correct_case_ids": neither,
                    "unavailable_pair_case_ids": unavailable,
                    "disagreements": disagreements,
                    "disagreement_rate": _rate(
                        len(disagreements),
                        len(by_split[split]) - len(unavailable),
                    ),
                }
                pairwise.append(record)
                unique_wins.append(
                    {
                        "split": split,
                        "cache_mode": mode,
                        "comparison": label,
                        "left_component": left,
                        "left_unique_win_case_ids": left_only,
                        "right_component": right,
                        "right_unique_win_case_ids": right_only,
                    }
                )

            for variant in FRONTEND_VARIANT_IDS[1:]:
                regressed: list[str] = []
                improved: list[str] = []
                unavailable: list[str] = []
                for case_id in by_split[split]:
                    baseline = by_coordinate[(split, mode, "A0", case_id)]
                    candidate = by_coordinate[(split, mode, variant, case_id)]
                    baseline_ok = _semantic_success(baseline)
                    candidate_ok = _semantic_success(candidate)
                    if baseline_ok is None or candidate_ok is None:
                        unavailable.append(case_id)
                    elif baseline_ok and not candidate_ok:
                        regressed.append(case_id)
                    elif candidate_ok and not baseline_ok:
                        improved.append(case_id)
                regressions.append(
                    {
                        "split": split,
                        "cache_mode": mode,
                        "variant_id": variant,
                        "baseline_variant_id": "A0",
                        "regression_case_ids": regressed,
                        "unique_improvement_case_ids": improved,
                        "unavailable_pair_case_ids": unavailable,
                        "regression_rate": _rate(
                            len(regressed),
                            len(by_split[split]) - len(unavailable),
                        ),
                    }
                )

            for variant, comparator in SYMAI_COMPARATORS.items():
                invoked = 0
                unnecessary = 0
                unique = 0
                unavailable: list[str] = []
                for case_id in by_split[split]:
                    candidate = by_coordinate[(split, mode, variant, case_id)]
                    baseline = by_coordinate[(split, mode, comparator, case_id)]
                    candidate_ok = _semantic_success(candidate)
                    baseline_ok = _semantic_success(baseline)
                    if candidate_ok is None or baseline_ok is None:
                        unavailable.append(case_id)
                        continue
                    calls = int(candidate["symai_model_calls"])
                    if calls == 0:
                        continue
                    invoked += calls
                    if candidate_ok and not baseline_ok:
                        unique += calls
                    else:
                        unnecessary += calls
                unnecessary_calls.append(
                    {
                        "split": split,
                        "cache_mode": mode,
                        "variant_id": variant,
                        "comparator_variant_id": comparator,
                        "symai_model_calls": invoked,
                        "unique_win_calls": unique,
                        "unnecessary_calls": unnecessary,
                        "unnecessary_call_rate": _rate(unnecessary, invoked),
                        "unavailable_pair_case_ids": unavailable,
                        "causal_interpretation": (
                            "gate_efficiency_control"
                            if variant == "A5"
                            else "descriptive_overlap_only"
                        ),
                    }
                )

    return {
        "schema": FRONTEND_ANALYSIS_SCHEMA,
        "coverage": {
            "split_count": len(SPLITS),
            "case_count": len({str(row["case_id"]) for row in rows}),
            "stratum_count": len({str(row["stratum"]) for row in rows}),
            "variant_count": len(FRONTEND_VARIANT_IDS),
            "cache_mode_count": len(CACHE_MODES),
            "expected_observation_count": 240,
            "observed_observation_count": len(rows),
        },
        "variant_metrics": variant_metrics,
        "pairwise_comparisons": pairwise,
        "component_unique_wins": unique_wins,
        "a0_regressions": regressions,
        "symai_unnecessary_calls": unnecessary_calls,
    }


def validate_frontend_report(value: object) -> dict[str, object]:
    """Validate identities, matrix completeness, source evidence, and analysis."""

    data = _mapping(value, "report")
    fields = {
        "schema",
        "evidence",
        "benchmark_id",
        "run_id",
        "execution_mode",
        "protocol_sha256",
        "registry_sha256",
        "corpus_manifest_sha256",
        "split_sha256",
        "case_ids_by_split",
        "stratum_by_case",
        "variant_ids",
        "cache_modes",
        "development_selection",
        "capability_inventory_sha256",
        "capabilities",
        "observations",
        "analysis",
        "artifact_sha256",
    }
    _exact(data, fields, "report")
    if data["schema"] != FRONTEND_REPORT_SCHEMA:
        raise FrontendReportError("unsupported front-end report schema")
    if data["evidence"] != HSSLEV0519C80():
        raise FrontendReportError("front-end evidence marker changed")
    if data["benchmark_id"] != BENCHMARK_ID:
        raise FrontendReportError("benchmark identity changed")
    _safe_id(data["run_id"], "run_id")
    execution_mode = _string(data["execution_mode"], "execution_mode")
    if execution_mode not in {"measured", "capability_preflight"}:
        raise FrontendReportError("unsupported execution mode")
    if data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256:
        raise FrontendReportError("protocol identity changed")
    if data["registry_sha256"] != VARIANT_REGISTRY_SHA256:
        raise FrontendReportError("variant registry identity changed")

    if data["corpus_manifest_sha256"] != FROZEN_CORPUS_MANIFEST_SHA256:
        raise FrontendReportError("reviewed corpus identity changed")
    catalog, by_split = _case_catalog()
    split_sha = _mapping(data["split_sha256"], "split_sha256")
    _exact(split_sha, set(SPLITS), "split_sha256")
    for split in SPLITS:
        if split_sha[split] != FROZEN_SPLIT_SHA256[Split(split)]:
            raise FrontendReportError(f"{split} split identity changed")
    raw_case_ids = _mapping(data["case_ids_by_split"], "case_ids_by_split")
    _exact(raw_case_ids, set(SPLITS), "case_ids_by_split")
    if any(raw_case_ids[split] != by_split[split] for split in SPLITS):
        raise FrontendReportError("front-end case membership/order changed")
    expected_strata = {
        case_id: item["stratum"] for case_id, item in catalog.items()
    }
    if data["stratum_by_case"] != expected_strata:
        raise FrontendReportError("case-to-stratum pairing changed")
    if data["variant_ids"] != list(FRONTEND_VARIANT_IDS):
        raise FrontendReportError("front-end variant scope changed")
    if data["cache_modes"] != list(CACHE_MODES):
        raise FrontendReportError("cache mode scope changed")
    selection = _mapping(data["development_selection"], "development_selection")
    _exact(
        selection,
        {"status", "case_ids", "selection_basis", "outcomes_inspected"},
        "development_selection",
    )
    if (
        selection["status"] != "preregistered_full_split"
        or selection["case_ids"] != by_split["development"]
        or selection["selection_basis"]
        != "all reviewed development cases; no outcome-derived case shortlist"
        or selection["outcomes_inspected"] is not False
    ):
        raise FrontendReportError("development selection contract changed")

    capabilities = _validate_capabilities(data["capabilities"])
    capability_digest = hashlib.sha256(
        canonical_json(capabilities).encode("utf-8")
    ).hexdigest()
    if data["capability_inventory_sha256"] != capability_digest:
        raise FrontendReportError("capability inventory digest changed")

    raw_observations = _array(data["observations"], "observations")
    observations = [
        _validate_observation(item, catalog) for item in raw_observations
    ]
    coordinates = [
        (
            str(row["split"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
            str(row["case_id"]),
        )
        for row in observations
    ]
    expected_coordinates = {
        (split, mode, variant, case_id)
        for split in SPLITS
        for mode in CACHE_MODES
        for variant in FRONTEND_VARIANT_IDS
        for case_id in by_split[split]
    }
    if len(coordinates) != len(set(coordinates)):
        raise FrontendReportError(
            "front-end report contains duplicate observations"
        )
    if set(coordinates) != expected_coordinates:
        raise FrontendReportError(
            "front-end observation matrix is incomplete; "
            f"missing={sorted(expected_coordinates - set(coordinates))}, "
            f"extra={sorted(set(coordinates) - expected_coordinates)}"
        )
    expected_order = [
        (split, mode, variant, case_id)
        for split in SPLITS
        for mode in CACHE_MODES
        for variant in FRONTEND_VARIANT_IDS
        for case_id in by_split[split]
    ]
    if coordinates != expected_order:
        raise FrontendReportError(
            "front-end observations are not in canonical order"
        )
    if execution_mode == "capability_preflight":
        if not any(
            item["status"] != "available" for item in capabilities.values()
        ):
            raise FrontendReportError(
                "capability preflight requires a recorded capability gap"
            )
        if any(row["status"] != "unavailable" for row in observations):
            raise FrontendReportError(
                "capability-preflight observations must remain unavailable"
            )
        if any(row["case_result"] is not None for row in observations):
            raise FrontendReportError(
                "capability preflight cannot embed fabricated case results"
            )
    else:
        for row in observations:
            _validate_measured_source(
                row, expected_run_id=str(data["run_id"])
            )
            if row["status"] not in {
                "unavailable",
                "infrastructure_failure",
            }:
                missing = [
                    name
                    for name in REQUIRED_CAPABILITIES[str(row["variant_id"])]
                    if capabilities[name]["status"] != "available"
                ]
                if missing:
                    raise FrontendReportError(
                        "measured front-end success conflicts with unavailable "
                        f"capabilities: {', '.join(missing)}"
                    )

    derived = derive_frontend_analysis(observations)
    if data["analysis"] != derived:
        raise FrontendReportError(
            "serialized front-end analysis differs from observations"
        )
    if data["artifact_sha256"] != _artifact_digest(data):
        raise FrontendReportError("front-end report artifact digest changed")
    return dict(data)


def load_frontend_report(
    path: str | Path = DEFAULT_FRONTEND_REPORT_PATH,
) -> dict[str, object]:
    """Load canonical newline JSON and validate the full front-end report."""

    report_path = Path(path)
    try:
        text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FrontendReportError(
            f"cannot read front-end report: {report_path}"
        ) from exc
    if not text.endswith("\n"):
        raise FrontendReportError(
            "front-end report is not canonical newline JSON"
        )
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, FrontendReportError) as exc:
        raise FrontendReportError(
            "front-end report is not strict JSON"
        ) from exc
    if canonical_json(value) + "\n" != text:
        raise FrontendReportError("front-end report is not canonical JSON")
    return validate_frontend_report(value)


def create_capability_preflight_report() -> dict[str, object]:
    """Create the canonical 2026-07-24 missingness capture."""

    catalog, by_split = _case_catalog()
    capabilities = {
        "current_modal_codec": {"status": "available", "reason": ""},
        "spacy_full_model": {
            "status": "unavailable",
            "reason": "requested en_core_web_sm pipeline is not installed",
        },
        "regex_legal_parser": {"status": "available", "reason": ""},
        "spacy_blank_model": {"status": "available", "reason": ""},
        "symai": {
            "status": "degraded",
            "reason": "provider and model identity are incomplete",
        },
        "llm_router": {
            "status": "degraded",
            "reason": "provider and model identity are incomplete",
        },
    }
    capability_inventory_sha256 = hashlib.sha256(
        canonical_json(capabilities).encode("utf-8")
    ).hexdigest()
    observations: list[dict[str, object]] = []
    for split in SPLITS:
        for mode in CACHE_MODES:
            for variant in FRONTEND_VARIANT_IDS:
                spacy_mode, symai_policy = _variant_identity(variant)
                missing = [
                    name
                    for name in REQUIRED_CAPABILITIES[variant]
                    if capabilities[name]["status"] != "available"
                ]
                if missing:
                    reason = (
                        "capability unavailable or degraded: "
                        + ", ".join(missing)
                    )
                else:
                    reason = (
                        "comparative execution withheld because required paired "
                        "arms are capability-ineligible"
                    )
                for case_id in by_split[split]:
                    case = catalog[case_id]
                    coordinate = {
                        "capability_inventory_sha256": (
                            capability_inventory_sha256
                        ),
                        "case_id": case_id,
                        "split": split,
                        "cache_mode": mode,
                        "variant_id": variant,
                        "missing_reason": reason,
                    }
                    observations.append(
                        {
                            "schema": FRONTEND_OBSERVATION_SCHEMA,
                            "case_id": case_id,
                            "split": split,
                            "stratum": case["stratum"],
                            "expected_class": case["expected_class"],
                            "cache_mode": mode,
                            "variant_id": variant,
                            "spacy_mode": spacy_mode,
                            "symai_policy": symai_policy,
                            "status": "unavailable",
                            "source_receipt_sha256": hashlib.sha256(
                                canonical_json(coordinate).encode("utf-8")
                            ).hexdigest(),
                            "case_result": None,
                            "semantic_signature_sha256": None,
                            "normalized_ir_exact_match": None,
                            "deterministic_semantic_equivalence": None,
                            "semantic_validator_receipt_sha256": None,
                            "predicted_class": None,
                            "ambiguity_classification_correct": None,
                            "fail_closed_classification_correct": None,
                            "spacy_invoked": False,
                            "symai_invoked": False,
                            "symai_model_calls": 0,
                            "total_wall_time_ms": 0.0,
                            "model_calls": 0,
                            "missing_reason": reason,
                        }
                    )
    report: dict[str, object] = {
        "schema": FRONTEND_REPORT_SCHEMA,
        "evidence": HSSLEV0519C80(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": "frontend-overlap-v1",
        "execution_mode": "capability_preflight",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "split_sha256": {
            split: FROZEN_SPLIT_SHA256[Split(split)] for split in SPLITS
        },
        "case_ids_by_split": by_split,
        "stratum_by_case": {
            case_id: item["stratum"] for case_id, item in catalog.items()
        },
        "variant_ids": list(FRONTEND_VARIANT_IDS),
        "cache_modes": list(CACHE_MODES),
        "development_selection": {
            "status": "preregistered_full_split",
            "case_ids": by_split["development"],
            "selection_basis": (
                "all reviewed development cases; "
                "no outcome-derived case shortlist"
            ),
            "outcomes_inspected": False,
        },
        "capability_inventory_sha256": capability_inventory_sha256,
        "capabilities": capabilities,
        "observations": observations,
        "analysis": derive_frontend_analysis(observations),
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _artifact_digest(report)
    return validate_frontend_report(report)


def build_frontend_report(
    run_id: str,
    capabilities: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build a canonical measured report from receipt-bearing observations.

    The caller supplies case-level semantic validation results, never aggregate
    metrics.  Each observation must embed its complete ``CaseResultRecord``;
    this builder fixes canonical matrix order, derives every aggregate, binds
    the capability inventory, and then executes the same strict validation
    used for a report loaded from disk.
    """

    safe_run_id = _safe_id(run_id, "run_id")
    capability_records = _validate_capabilities(capabilities)
    catalog, by_split = _case_catalog()
    if isinstance(observations, (str, bytes, Mapping)):
        raise FrontendReportError(
            "observations must be a sequence of observation mappings"
        )
    try:
        rows = [
            _validate_observation(item, catalog) for item in observations
        ]
    except TypeError as exc:
        raise FrontendReportError(
            "observations must be a sequence of observation mappings"
        ) from exc
    for row in rows:
        _validate_measured_source(row, expected_run_id=safe_run_id)

    order = {
        (split, mode, variant, case_id): index
        for index, (split, mode, variant, case_id) in enumerate(
            (
                (split, mode, variant, case_id)
                for split in SPLITS
                for mode in CACHE_MODES
                for variant in FRONTEND_VARIANT_IDS
                for case_id in by_split[split]
            )
        )
    }
    coordinates = [
        (
            str(row["split"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
            str(row["case_id"]),
        )
        for row in rows
    ]
    if len(coordinates) != len(set(coordinates)):
        raise FrontendReportError(
            "front-end report contains duplicate observations"
        )
    if set(coordinates) != set(order):
        raise FrontendReportError(
            "front-end observation matrix is incomplete; "
            f"missing={sorted(set(order) - set(coordinates))}, "
            f"extra={sorted(set(coordinates) - set(order))}"
        )
    rows.sort(
        key=lambda row: order[
            (
                str(row["split"]),
                str(row["cache_mode"]),
                str(row["variant_id"]),
                str(row["case_id"]),
            )
        ]
    )
    capability_inventory_sha256 = hashlib.sha256(
        canonical_json(capability_records).encode("utf-8")
    ).hexdigest()
    value: dict[str, object] = {
        "schema": FRONTEND_REPORT_SCHEMA,
        "evidence": HSSLEV0519C80(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": safe_run_id,
        "execution_mode": "measured",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "split_sha256": {
            split: FROZEN_SPLIT_SHA256[Split(split)] for split in SPLITS
        },
        "case_ids_by_split": by_split,
        "stratum_by_case": {
            case_id: item["stratum"] for case_id, item in catalog.items()
        },
        "variant_ids": list(FRONTEND_VARIANT_IDS),
        "cache_modes": list(CACHE_MODES),
        "development_selection": {
            "status": "preregistered_full_split",
            "case_ids": by_split["development"],
            "selection_basis": (
                "all reviewed development cases; "
                "no outcome-derived case shortlist"
            ),
            "outcomes_inspected": False,
        },
        "capability_inventory_sha256": capability_inventory_sha256,
        "capabilities": capability_records,
        "observations": rows,
        "analysis": derive_frontend_analysis(rows),
        "artifact_sha256": "",
    }
    value["artifact_sha256"] = _artifact_digest(value)
    return validate_frontend_report(value)


def frontend_summary(report: Mapping[str, object]) -> dict[str, object]:
    """Return a stable concise CLI validation receipt."""

    analysis = _mapping(report["analysis"], "analysis")
    coverage = _mapping(analysis["coverage"], "analysis.coverage")
    metrics = _array(
        analysis["variant_metrics"], "analysis.variant_metrics"
    )
    return {
        "section": "frontend",
        "status": "valid",
        "execution_mode": report["execution_mode"],
        "artifact_sha256": report["artifact_sha256"],
        "observation_count": coverage["observed_observation_count"],
        "split_count": coverage["split_count"],
        "stratum_count": coverage["stratum_count"],
        "semantic_measurement_count": sum(
            int(_mapping(item, "variant_metric")["metrics"]["measured_count"])
            for item in metrics
        ),
        "missingness_retained": any(
            _mapping(item, "variant_metric")["metrics"][
                "semantic_quality_rate"
            ]
            is None
            for item in metrics
        ),
    }


__all__ = [
    "CACHE_MODES",
    "DEFAULT_FRONTEND_REPORT_PATH",
    "FRONTEND_ANALYSIS_SCHEMA",
    "FRONTEND_OBSERVATION_SCHEMA",
    "FRONTEND_REPORT_SCHEMA",
    "FRONTEND_VARIANT_IDS",
    "FrontendReportError",
    "HSSLEV0519C80",
    "HSSLEV1159F06",
    "SPLITS",
    "build_frontend_report",
    "create_capability_preflight_report",
    "derive_frontend_analysis",
    "frontend_summary",
    "load_frontend_report",
    "validate_frontend_report",
]
