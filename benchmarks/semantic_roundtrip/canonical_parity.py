"""Build and score the source-withheld SRT-018 parity report.

This module is the scored admission boundary for the production
``CanonicalSemanticRoundTrip`` orchestrator.  Orchestrator ``SUCCESS`` only
means the L1→T1→L2 pipeline completed with a sealed evidence chain.  The
parity report recomputes end-to-end losses, eligibility gates, and the frozen
SRT-015 upper-confidence-bound noninferiority decision against the selected
replacement arm.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.semantic_roundtrip.canonical_decision import (
    CANONICAL_ARTIFACT_PATHS,
    PARITY_REPORT_INTERFACE,
    PARITY_REPORT_SCHEMA,
)
from benchmarks.semantic_roundtrip.contracts import CanonicalRuleIR
from benchmarks.semantic_roundtrip.matrix import (
    load_matrix_cases,
    polarity_diagnostics,
    source_copy_diagnostics,
)
from benchmarks.semantic_roundtrip.metrics import round_trip_losses
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    CanonicalAtomVocabulary,
    OperationStatus,
    load_parity_policy,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
    CanonicalSemanticRoundTrip,
    CanonicalSemanticRoundTripResult,
    measured_parity_compiler_request,
)


DEFAULT_PILOT_CASES: Final = Path(
    "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)
DEFAULT_REPLACEMENT_REPORT: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-27_semantic_roundtrip_composition_replacement.json"
)
DEFAULT_PARITY_REPORT: Final = Path(CANONICAL_ARTIFACT_PATHS["parity_report"])


class CanonicalParityError(ValueError):
    """Raised when a scored parity run cannot be completed fail-closed."""


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise CanonicalParityError("bootstrap mean requires at least one value")
    return math.fsum(values) / len(values)


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise CanonicalParityError("quantile requires samples")
    if not 0.0 <= probability <= 1.0:
        raise CanonicalParityError("quantile probability must be in [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = probability * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _bootstrap_bounds(
    deltas: Sequence[float],
    *,
    seed: int,
    bootstrap_samples: int,
    confidence_level: float,
) -> tuple[float, float]:
    if not deltas:
        raise CanonicalParityError("paired bootstrap requires case deltas")
    rng = random.Random(seed)
    sample_count = len(deltas)
    draws = [
        _mean([deltas[rng.randrange(sample_count)] for _ in deltas])
        for _ in range(bootstrap_samples)
    ]
    tail = (1.0 - confidence_level) / 2.0
    return _quantile(draws, tail), _quantile(draws, 1.0 - tail)


def _to_benchmark_ir(value: object) -> CanonicalRuleIR:
    if value is None:
        raise CanonicalParityError("canonical IR is missing")
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    if not isinstance(payload, Mapping):
        raise CanonicalParityError("canonical IR must be an object")
    return CanonicalRuleIR.from_dict(payload)


def _vocabulary_from_case(case: object) -> CanonicalAtomVocabulary:
    allowed = case.allowed_atom_vocabulary
    return CanonicalAtomVocabulary(
        actors=list(allowed.actors),
        actions=list(allowed.actions),
        objects=list(allowed.objects),
        qualifiers=list(allowed.qualifiers),
    )


def load_selected_arm_losses(
    report_path: str | Path,
    *,
    arm_id: str = IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
) -> tuple[str, tuple[str, ...], dict[str, float]]:
    """Load frozen selected-arm end-to-end losses from a composition report."""

    path = Path(report_path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalParityError(
            f"cannot load composition report {path}: {exc}"
        ) from exc
    if not isinstance(document, Mapping):
        raise CanonicalParityError("composition report must be an object")
    report_cid = document.get("report_cid")
    if not isinstance(report_cid, str) or not report_cid:
        raise CanonicalParityError("composition report_cid is missing")
    records = (
        document.get("execution", {})
        .get("deterministic", {})
        .get("records", [])
    )
    if not isinstance(records, list):
        raise CanonicalParityError(
            "composition report deterministic records are missing"
        )
    losses: dict[str, float] = {}
    order: list[str] = []
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("arm_id") != arm_id:
            continue
        case_id = raw.get("case_id")
        case_losses = raw.get("losses")
        if not isinstance(case_id, str) or not isinstance(case_losses, Mapping):
            raise CanonicalParityError(
                "selected arm record is missing case_id or losses"
            )
        end_to_end = case_losses.get("end_to_end")
        if (
            not isinstance(end_to_end, (int, float))
            or isinstance(end_to_end, bool)
            or not math.isfinite(float(end_to_end))
        ):
            raise CanonicalParityError(
                f"selected arm end_to_end loss is invalid for {case_id}"
            )
        if case_id in losses:
            raise CanonicalParityError(
                f"duplicate selected arm case {case_id!r}"
            )
        losses[case_id] = float(end_to_end)
        order.append(case_id)
    if not order:
        raise CanonicalParityError(
            f"no deterministic records for selected arm {arm_id!r}"
        )
    return report_cid, tuple(order), losses


def score_roundtrip_case(
    case: object,
    result: CanonicalSemanticRoundTripResult,
    *,
    selected_end_to_end_loss: float,
) -> dict[str, Any]:
    """Score one sealed orchestrator result against gold and selected loss."""

    if not isinstance(result, CanonicalSemanticRoundTripResult):
        raise CanonicalParityError(
            "result must be CanonicalSemanticRoundTripResult"
        )
    if result.status is not OperationStatus.SUCCESS:
        raise CanonicalParityError(
            f"case {getattr(case, 'case_id', '?')!r} did not complete: "
            f"{result.status.value} at {result.terminal_stage}"
        )
    assert result.l1_result is not None
    assert result.t1_result is not None
    assert result.l2_result is not None
    if (
        result.l1_result.canonical_ir is None
        or result.l2_result.canonical_ir is None
        or result.t1_result.text is None
        or result.t1_result.text_cid is None
    ):
        raise CanonicalParityError(
            f"case {case.case_id!r} is missing sealed stage artifacts"
        )

    l1 = _to_benchmark_ir(result.l1_result.canonical_ir)
    l2 = _to_benchmark_ir(result.l2_result.canonical_ir)
    reconstruction = result.t1_result.text
    losses = round_trip_losses(case.gold_ir, l1, reconstruction, l2)
    copy = source_copy_diagnostics(case.source_text, reconstruction)
    polarity = polarity_diagnostics(case.gold_ir, l2)
    full_coverage = bool(l1.rules) and bool(l2.rules) and bool(
        reconstruction.strip()
    )
    source_copy_violation = not bool(copy.get("gate_passed"))
    polarity_hard_failure = not bool(polarity.get("gate_passed"))
    if not full_coverage:
        raise CanonicalParityError(
            f"case {case.case_id!r} failed full nonempty coverage"
        )
    if polarity_hard_failure:
        raise CanonicalParityError(
            f"case {case.case_id!r} failed polarity preservation"
        )
    if source_copy_violation:
        raise CanonicalParityError(
            f"case {case.case_id!r} failed source-copy exclusion"
        )

    delta = float(losses.end_to_end) - float(selected_end_to_end_loss)
    return {
        "case_id": case.case_id,
        "status": "success",
        "canonical_l1_cid": result.l1_result.canonical_ir.ir_cid,
        "realized_text_cid": result.t1_result.text_cid,
        "canonical_l2_cid": result.l2_result.canonical_ir.ir_cid,
        "orchestrator_result_cid": result.result_cid,
        "end_to_end_loss": float(losses.end_to_end),
        "selected_arm_end_to_end_loss": float(selected_end_to_end_loss),
        "canonical_minus_selected": delta,
        "full_nonempty_coverage": True,
        "polarity_hard_failure": False,
        "source_copy_violation": False,
        "forward_loss": float(losses.forward),
        "cycle_loss": float(losses.cycle),
    }


def implementation_raw_cids(repo_root: str | Path) -> dict[str, str]:
    """Content-address the four SRT-018 implementation artifacts."""

    root = Path(repo_root)
    cids: dict[str, str] = {}
    for name in ("ir_schema", "compiler", "decompiler", "roundtrip"):
        relative = CANONICAL_ARTIFACT_PATHS[name]
        path = root / relative
        if not path.is_file():
            raise CanonicalParityError(f"missing implementation file: {relative}")
        cids[name] = cid_for_bytes(path.read_bytes())
    return cids


def build_parity_report(
    case_scores: Sequence[Mapping[str, Any]],
    *,
    composition_report_cid: str,
    selected_arm_id: str = IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    case_ids: Sequence[str],
    repo_root: str | Path,
    structural_checks: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a self-validating SRT-018 parity report document."""

    if tuple(score["case_id"] for score in case_scores) != tuple(case_ids):
        raise CanonicalParityError(
            "case_scores must preserve the frozen case order exactly"
        )
    policy = load_parity_policy().to_dict()
    if policy["policy_cid"] != CANONICAL_PARITY_POLICY_CID:
        raise CanonicalParityError("loaded parity policy CID changed")

    deltas = {
        str(score["case_id"]): float(score["canonical_minus_selected"])
        for score in case_scores
    }
    ordered_deltas = [deltas[case_id] for case_id in case_ids]
    estimate = _mean(ordered_deltas)
    seed = int(policy["bootstrap_seed"])
    samples = int(policy["bootstrap_samples"])
    confidence = float(policy["confidence_level"])
    margin = float(policy["noninferiority_margin"])
    low, high = _bootstrap_bounds(
        ordered_deltas,
        seed=seed,
        bootstrap_samples=samples,
        confidence_level=confidence,
    )
    within_tolerance = high <= margin

    if structural_checks is None:
        structural_checks = {
            "hammer": {
                "applicable": False,
                "status": "not_applicable",
                "reason": (
                    "selected deterministic composition has no Hammer proof "
                    "obligation in SRT-018"
                ),
            },
            "cvc5": {
                "applicable": False,
                "status": "not_applicable",
                "reason": (
                    "selected deterministic composition has no cvc5 proof "
                    "obligation in SRT-018"
                ),
            },
            "lean": {
                "applicable": False,
                "status": "not_applicable",
                "reason": "no Lean obligation for the selected deterministic arm",
            },
        }

    public_case_results = [
        {
            "case_id": score["case_id"],
            "status": score["status"],
            "canonical_l1_cid": score["canonical_l1_cid"],
            "realized_text_cid": score["realized_text_cid"],
            "canonical_l2_cid": score["canonical_l2_cid"],
            "end_to_end_loss": score["end_to_end_loss"],
            "selected_arm_end_to_end_loss": score[
                "selected_arm_end_to_end_loss"
            ],
            "canonical_minus_selected": score["canonical_minus_selected"],
            "full_nonempty_coverage": score["full_nonempty_coverage"],
            "polarity_hard_failure": score["polarity_hard_failure"],
            "source_copy_violation": score["source_copy_violation"],
        }
        for score in case_scores
    ]

    report: dict[str, Any] = {
        "interface": PARITY_REPORT_INTERFACE,
        "schema_version": PARITY_REPORT_SCHEMA,
        "status": "complete",
        "composition_report_cid": composition_report_cid,
        "parity_policy_cid": CANONICAL_PARITY_POLICY_CID,
        "selected_arm_id": selected_arm_id,
        "execution": {
            "case_count": len(case_ids),
            "observed_terminal_case_count": len(case_ids),
            "missing_case_count": 0,
            "case_results": public_case_results,
        },
        "comparison": {
            "metric": "end_to_end_loss",
            "direction": "canonical_minus_selected",
            "case_deltas": {
                case_id: deltas[case_id] for case_id in case_ids
            },
            "estimate": estimate,
            "uncertainty": {
                "method": "seeded_percentile_case_cluster_bootstrap",
                "confidence_level": confidence,
                "bootstrap_samples": samples,
                "resampling_unit": (
                    "case_after_within_case_repeat_aggregation"
                ),
                "low": low,
                "high": high,
            },
            "noninferiority_margin": margin,
            "within_tolerance": within_tolerance,
        },
        "structural_checks": dict(structural_checks),
        "lineage": {
            "configuration_cids": [CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID],
            "model_cids": [],
            "implementation_raw_cids": implementation_raw_cids(repo_root),
        },
    }
    report["report_cid"] = cid_for_dag_json(
        {key: value for key, value in report.items() if key != "report_cid"}
    )
    return report


def run_canonical_parity(
    *,
    repo_root: str | Path,
    pilot_cases_path: str | Path | None = None,
    composition_report_path: str | Path | None = None,
    arm_id: str = IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
) -> dict[str, Any]:
    """Execute the production round trip on every pilot case and score it."""

    root = Path(repo_root)
    cases_path = (
        root / DEFAULT_PILOT_CASES
        if pilot_cases_path is None
        else Path(pilot_cases_path)
    )
    report_path = (
        root / DEFAULT_REPLACEMENT_REPORT
        if composition_report_path is None
        else Path(composition_report_path)
    )
    composition_cid, case_order, selected_losses = load_selected_arm_losses(
        report_path,
        arm_id=arm_id,
    )
    cases = load_matrix_cases(cases_path)
    by_id = {case.case_id: case for case in cases}
    if set(by_id) != set(case_order):
        raise CanonicalParityError(
            "pilot fixture case set does not match the selected arm report"
        )
    ordered_cases = [by_id[case_id] for case_id in case_order]

    orchestrator = CanonicalSemanticRoundTrip()
    scores: list[dict[str, Any]] = []
    for case in ordered_cases:
        request = measured_parity_compiler_request(
            case.source_text,
            request_id=f"srt018:{case.case_id}",
            atom_vocabulary=_vocabulary_from_case(case),
        )
        result = orchestrator.run(request)
        scores.append(
            score_roundtrip_case(
                case,
                result,
                selected_end_to_end_loss=selected_losses[case.case_id],
            )
        )
    return build_parity_report(
        scores,
        composition_report_cid=composition_cid,
        selected_arm_id=arm_id,
        case_ids=case_order,
        repo_root=root,
    )


def write_parity_report(
    report: Mapping[str, Any],
    *,
    repo_root: str | Path,
    relative_path: str | Path | None = None,
) -> Path:
    """Persist a canonical DAG-JSON parity report and return its path."""

    root = Path(repo_root)
    target = root / (
        DEFAULT_PARITY_REPORT if relative_path is None else Path(relative_path)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(report)
    # Re-seal in case callers mutated the dict after construction.
    payload.pop("report_cid", None)
    payload["report_cid"] = cid_for_dag_json(payload)
    target.write_bytes(canonical_dag_json_bytes(payload) + b"\n")
    return target


__all__ = [
    "DEFAULT_PARITY_REPORT",
    "DEFAULT_PILOT_CASES",
    "DEFAULT_REPLACEMENT_REPORT",
    "CanonicalParityError",
    "build_parity_report",
    "implementation_raw_cids",
    "load_selected_arm_losses",
    "run_canonical_parity",
    "score_roundtrip_case",
    "write_parity_report",
]
