"""Fail-closed contract for the SRT-019 canonical compiler decision.

The final handoff is not a prose-shaped JSON marker.  A selected decision
must bind the complete SRT-014 measurement, the SRT-015 frozen parity policy,
the SRT-016/017 implementations, and the source-withheld SRT-018 parity run.
The validator recomputes content identities and the parity decision from
per-case evidence.  An incomplete chain may only publish an explicit
``declined`` decision.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)


CANONICAL_DECISION_INTERFACE: Final = "CanonicalCompilerDecision@1"
CANONICAL_DECISION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-canonical-compiler-decision.v1"
)
PARITY_POLICY_INTERFACE: Final = "CanonicalRoundTripParityPolicy@1"
PARITY_POLICY_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-canonical-parity-policy.v1"
)
# Distinct from the production orchestrator result interface
# (``CanonicalSemanticRoundTrip@1`` / stage-completion receipt).
PARITY_REPORT_INTERFACE: Final = "CanonicalSemanticRoundTripParityReport@1"
PARITY_REPORT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-canonical-parity-report.v1"
)

CANONICAL_ARTIFACT_PATHS: Final = {
    # SRT-014 is preserved as no-eligible negative evidence in the policy
    # lineage.  The selectable replacement run is the composition report that
    # may authorize a selected or bounded-tie SRT-019 decision.
    "composition_report": (
        "docs/performance_snapshots/"
        "2026-07-27_semantic_roundtrip_composition_replacement.json"
    ),
    "specification": (
        "docs/architecture/semantic_roundtrip_canonical_compiler.md"
    ),
    "parity_policy": (
        "docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json"
    ),
    "ir_schema": (
        "ipfs_datasets_py/logic/legal_ir/schemas/"
        "canonical_roundtrip_ir.schema.json"
    ),
    "compiler": "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
    "decompiler": "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py",
    "roundtrip": "ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py",
    "parity_report": (
        "docs/performance_snapshots/"
        "2026-07-26_canonical_semantic_roundtrip.json"
    ),
}

REQUESTED_TOOL_IDS: Final = (
    "typed_deontic",
    "modal",
    "spacy",
    "deterministic_realizer",
    "autoencoder",
    "symai",
    "leanstral",
    "selective_repair",
    "hammer",
    "cvc5",
    "lean",
    "multiformats",
)
REPRODUCTION_PURPOSES: Final = (
    "composition_report_validation",
    "canonical_schema_tests",
    "canonical_parity_tests",
    "decision_validation",
)
SUPERVISOR_PURPOSES: Final = ("supervisor_plan", "supervisor_launch")


class CanonicalDecisionValidationError(ValueError):
    """Raised when a canonical decision is incomplete or inconsistent."""


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CanonicalDecisionValidationError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise CanonicalDecisionValidationError(f"{path} must be an array")
    return value


def _exact(
    value: Mapping[str, Any],
    fields: set[str],
    path: str,
) -> None:
    if set(value) != fields:
        raise CanonicalDecisionValidationError(
            f"{path} fields changed; expected {sorted(fields)}, "
            f"got {sorted(value)}"
        )


def _require(condition: object, message: str) -> None:
    if not condition:
        raise CanonicalDecisionValidationError(message)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalDecisionValidationError(
            f"{path} must be a nonempty string"
        )
    return value


def _number(value: object, path: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise CanonicalDecisionValidationError(
            f"{path} must be a finite number"
        )
    return float(value)


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1.0e-9)


def _canonical_cid(
    value: object,
    path: str,
    *,
    codecs: Sequence[str] = ("raw", "dag-json"),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise CanonicalDecisionValidationError(
            f"{path} is not a canonical CID: {exc}"
        ) from exc


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalDecisionValidationError(
                f"duplicate JSON key {key!r}"
            )
        result[key] = value
    return result


def _load_json(path: Path, description: str) -> tuple[object, bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise CanonicalDecisionValidationError(
            f"cannot read {description}: {path}"
        ) from exc
    try:
        return (
            json.loads(text, object_pairs_hook=_reject_duplicate_pairs),
            raw,
        )
    except (json.JSONDecodeError, CanonicalDecisionValidationError) as exc:
        raise CanonicalDecisionValidationError(
            f"{description} is not strict JSON: {exc}"
        ) from exc


def _repository_file(
    repo_root: Path,
    relative_path: str,
    path: str,
) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CanonicalDecisionValidationError(
            f"{path} must be a repository-relative path"
        )
    root = repo_root.resolve()
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise CanonicalDecisionValidationError(
            f"{path} does not identify a repository file"
        )
    return resolved


def _artifact_binding(
    value: object,
    *,
    artifact_name: str,
    repo_root: Path,
) -> tuple[Path, bytes]:
    path = f"$.artifacts.{artifact_name}"
    binding = _mapping(value, path)
    _exact(binding, {"path", "raw_cid"}, path)
    expected_path = CANONICAL_ARTIFACT_PATHS[artifact_name]
    _require(
        binding.get("path") == expected_path,
        f"{path}.path must be {expected_path}",
    )
    expected_cid = _canonical_cid(
        binding.get("raw_cid"),
        f"{path}.raw_cid",
        codecs=("raw",),
    )
    source = _repository_file(
        repo_root,
        expected_path,
        f"{path}.path",
    )
    raw = source.read_bytes()
    _require(
        cid_for_bytes(raw) == expected_cid,
        f"{path}.raw_cid does not match the repository file",
    )
    return source, raw


def _validate_self_cid(
    document: Mapping[str, Any],
    *,
    cid_field: str,
    path: str,
) -> str:
    supplied = _canonical_cid(
        document.get(cid_field),
        f"{path}.{cid_field}",
        codecs=("dag-json",),
    )
    payload = dict(document)
    del payload[cid_field]
    _require(
        cid_for_dag_json(payload) == supplied,
        f"{path}.{cid_field} does not match its canonical payload",
    )
    return supplied


def validate_parity_policy(
    value: object,
    *,
    composition_report_cid: str,
) -> dict[str, Any]:
    """Validate the machine-readable SRT-015 noninferiority policy.

    The production checked-in policy may carry additional immutable lineage
    fields (evidence, selection, bootstrap seed, gates).  Those extras are
    allowed so long as every decision-critical field is present, typed, and
    bound to the composition report CID, and the self-CID reseals.
    """

    policy = _mapping(value, "parity policy")
    required = {
        "interface",
        "schema_version",
        "metric",
        "comparison",
        "decision_rule",
        "confidence_level",
        "bootstrap_method",
        "bootstrap_samples",
        "resampling_unit",
        "noninferiority_margin",
        "frozen_from_report_cid",
        "policy_cid",
    }
    missing = sorted(required - set(policy))
    _require(
        not missing,
        "parity policy is missing required fields: " + ", ".join(missing),
    )
    _require(
        policy.get("interface") == PARITY_POLICY_INTERFACE,
        f"parity policy.interface must be {PARITY_POLICY_INTERFACE}",
    )
    _require(
        policy.get("schema_version") == PARITY_POLICY_SCHEMA,
        f"parity policy.schema_version must be {PARITY_POLICY_SCHEMA}",
    )
    _require(
        policy.get("metric") == "end_to_end_loss",
        "parity policy.metric must be end_to_end_loss",
    )
    _require(
        policy.get("comparison") == "canonical_minus_selected",
        "parity policy.comparison must be canonical_minus_selected",
    )
    _require(
        policy.get("decision_rule")
        == "upper_confidence_bound_lte_noninferiority_margin",
        "parity policy.decision_rule changed",
    )
    confidence = _number(
        policy.get("confidence_level"),
        "parity policy.confidence_level",
    )
    _require(
        0.0 < confidence < 1.0,
        "parity policy.confidence_level must be in (0, 1)",
    )
    _require(
        policy.get("bootstrap_method")
        == "seeded_percentile_case_cluster_bootstrap",
        "parity policy.bootstrap_method changed",
    )
    samples = policy.get("bootstrap_samples")
    _require(
        isinstance(samples, int)
        and not isinstance(samples, bool)
        and samples >= 10_000,
        "parity policy.bootstrap_samples must be at least 10000",
    )
    _require(
        policy.get("resampling_unit")
        == "case_after_within_case_repeat_aggregation",
        "parity policy.resampling_unit changed",
    )
    margin = _number(
        policy.get("noninferiority_margin"),
        "parity policy.noninferiority_margin",
    )
    _require(
        0.0 <= margin <= 1.0,
        "parity policy.noninferiority_margin must be in [0, 1]",
    )
    _require(
        policy.get("frozen_from_report_cid") == composition_report_cid,
        "parity policy is not frozen from the bound composition report",
    )
    # When lineage carries both original and replacement report CIDs, the
    # bound composition report must appear in that frozen set.
    frozen_from_report_cids = policy.get("frozen_from_report_cids")
    if frozen_from_report_cids is not None:
        cid_list = _array(
            frozen_from_report_cids,
            "parity policy.frozen_from_report_cids",
        )
        _require(
            composition_report_cid in cid_list,
            "composition report CID is not in frozen_from_report_cids",
        )
    policy_cid = _validate_self_cid(
        policy,
        cid_field="policy_cid",
        path="parity policy",
    )
    return {
        "policy_cid": policy_cid,
        "confidence_level": confidence,
        "bootstrap_samples": samples,
        "noninferiority_margin": margin,
        "document": dict(policy),
    }


def _validate_structural_checks(value: object) -> None:
    checks = _mapping(value, "parity report.structural_checks")
    _exact(checks, {"hammer", "cvc5", "lean"}, "parity report.structural_checks")
    for tool_id in ("hammer", "cvc5", "lean"):
        path = f"parity report.structural_checks.{tool_id}"
        check = _mapping(checks[tool_id], path)
        _exact(check, {"applicable", "status", "reason"}, path)
        applicable = check.get("applicable")
        _require(isinstance(applicable, bool), f"{path}.applicable must be boolean")
        expected_status = "passed" if applicable else "not_applicable"
        _require(
            check.get("status") == expected_status,
            f"{path}.status must be {expected_status}",
        )
        _string(check.get("reason"), f"{path}.reason")


def validate_parity_report(
    value: object,
    *,
    composition_report_cid: str,
    selected_arm_id: str,
    case_ids: Sequence[str],
    selected_per_case: Mapping[str, Any],
    parity_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and recompute the source-withheld SRT-018 parity gate."""

    report = _mapping(value, "parity report")
    _exact(
        report,
        {
            "interface",
            "schema_version",
            "report_cid",
            "status",
            "composition_report_cid",
            "parity_policy_cid",
            "selected_arm_id",
            "execution",
            "comparison",
            "structural_checks",
            "lineage",
        },
        "parity report",
    )
    _require(
        report.get("interface") == PARITY_REPORT_INTERFACE,
        f"parity report.interface must be {PARITY_REPORT_INTERFACE}",
    )
    _require(
        report.get("schema_version") == PARITY_REPORT_SCHEMA,
        f"parity report.schema_version must be {PARITY_REPORT_SCHEMA}",
    )
    _require(
        report.get("status") == "complete",
        "parity report.status must be complete",
    )
    _require(
        report.get("composition_report_cid") == composition_report_cid,
        "parity report composition_report_cid changed",
    )
    _require(
        report.get("parity_policy_cid") == parity_policy["policy_cid"],
        "parity report parity_policy_cid changed",
    )
    _require(
        report.get("selected_arm_id") == selected_arm_id,
        "parity report selected_arm_id changed",
    )
    report_cid = _validate_self_cid(
        report,
        cid_field="report_cid",
        path="parity report",
    )

    execution = _mapping(report.get("execution"), "parity report.execution")
    _exact(
        execution,
        {
            "case_count",
            "observed_terminal_case_count",
            "missing_case_count",
            "case_results",
        },
        "parity report.execution",
    )
    expected_case_ids = list(case_ids)
    _require(
        execution.get("case_count") == len(expected_case_ids),
        "parity report execution.case_count changed",
    )
    _require(
        execution.get("observed_terminal_case_count") == len(expected_case_ids),
        "parity report must contain every terminal case",
    )
    _require(
        execution.get("missing_case_count") == 0,
        "parity report execution.missing_case_count must be zero",
    )
    results = _array(
        execution.get("case_results"),
        "parity report.execution.case_results",
    )
    _require(
        len(results) == len(expected_case_ids),
        "parity report case result count is incomplete",
    )
    observed_ids: list[str] = []
    deltas: dict[str, float] = {}
    for index, raw_result in enumerate(results):
        path = f"parity report.execution.case_results[{index}]"
        result = _mapping(raw_result, path)
        _exact(
            result,
            {
                "case_id",
                "status",
                "canonical_l1_cid",
                "realized_text_cid",
                "canonical_l2_cid",
                "end_to_end_loss",
                "selected_arm_end_to_end_loss",
                "canonical_minus_selected",
                "full_nonempty_coverage",
                "polarity_hard_failure",
                "source_copy_violation",
            },
            path,
        )
        case_id = _string(result.get("case_id"), f"{path}.case_id")
        observed_ids.append(case_id)
        _require(
            result.get("status") == "success",
            f"{path}.status must be success",
        )
        for cid_field in (
            "canonical_l1_cid",
            "realized_text_cid",
            "canonical_l2_cid",
        ):
            _canonical_cid(result.get(cid_field), f"{path}.{cid_field}")
        canonical_loss = _number(
            result.get("end_to_end_loss"),
            f"{path}.end_to_end_loss",
        )
        selected_loss = _number(
            result.get("selected_arm_end_to_end_loss"),
            f"{path}.selected_arm_end_to_end_loss",
        )
        delta = _number(
            result.get("canonical_minus_selected"),
            f"{path}.canonical_minus_selected",
        )
        _require(
            0.0 <= canonical_loss <= 1.0
            and 0.0 <= selected_loss <= 1.0,
            f"{path} losses must be in [0, 1]",
        )
        expected_case = _mapping(
            selected_per_case.get(case_id),
            f"composition report selected per_case[{case_id!r}]",
        )
        expected_losses = _mapping(
            expected_case.get("losses"),
            f"composition report selected per_case[{case_id!r}].losses",
        )
        expected_selected = _number(
            expected_losses.get("end_to_end"),
            "composition report selected per-case end-to-end loss",
        )
        _require(
            _close(selected_loss, expected_selected),
            f"{path}.selected_arm_end_to_end_loss differs from SRT-014",
        )
        _require(
            _close(delta, canonical_loss - selected_loss),
            f"{path}.canonical_minus_selected is inconsistent",
        )
        _require(
            result.get("full_nonempty_coverage") is True,
            f"{path}.full_nonempty_coverage must be true",
        )
        _require(
            result.get("polarity_hard_failure") is False,
            f"{path}.polarity_hard_failure must be false",
        )
        _require(
            result.get("source_copy_violation") is False,
            f"{path}.source_copy_violation must be false",
        )
        deltas[case_id] = delta
    _require(
        observed_ids == expected_case_ids
        and len(observed_ids) == len(set(observed_ids)),
        "parity report cases must preserve the frozen SRT-014 case order",
    )

    comparison = _mapping(report.get("comparison"), "parity report.comparison")
    _exact(
        comparison,
        {
            "metric",
            "direction",
            "case_deltas",
            "estimate",
            "uncertainty",
            "noninferiority_margin",
            "within_tolerance",
        },
        "parity report.comparison",
    )
    _require(
        comparison.get("metric") == "end_to_end_loss",
        "parity report comparison.metric changed",
    )
    _require(
        comparison.get("direction") == "canonical_minus_selected",
        "parity report comparison.direction changed",
    )
    raw_case_deltas = _mapping(
        comparison.get("case_deltas"),
        "parity report.comparison.case_deltas",
    )
    # DAG-JSON canonicalization sorts object keys.  Frozen case order is
    # owned by execution.case_results, not by map key order.
    _require(
        set(raw_case_deltas) == set(expected_case_ids)
        and len(raw_case_deltas) == len(expected_case_ids),
        "parity report comparison.case_deltas cases changed",
    )
    for case_id, delta in deltas.items():
        _require(
            _close(
                _number(
                    raw_case_deltas.get(case_id),
                    f"parity report comparison.case_deltas[{case_id!r}]",
                ),
                delta,
            ),
            f"parity report comparison delta changed for {case_id}",
        )
    estimate = _number(
        comparison.get("estimate"),
        "parity report.comparison.estimate",
    )
    _require(
        _close(estimate, math.fsum(deltas.values()) / len(deltas)),
        "parity report comparison.estimate is not the case-macro mean",
    )
    uncertainty = _mapping(
        comparison.get("uncertainty"),
        "parity report.comparison.uncertainty",
    )
    _exact(
        uncertainty,
        {
            "method",
            "confidence_level",
            "bootstrap_samples",
            "resampling_unit",
            "low",
            "high",
        },
        "parity report.comparison.uncertainty",
    )
    _require(
        uncertainty.get("method")
        == parity_policy["document"]["bootstrap_method"],
        "parity report uncertainty.method differs from the frozen policy",
    )
    _require(
        _close(
            _number(
                uncertainty.get("confidence_level"),
                "parity report uncertainty.confidence_level",
            ),
            float(parity_policy["confidence_level"]),
        ),
        "parity report confidence level differs from the frozen policy",
    )
    _require(
        uncertainty.get("bootstrap_samples")
        == parity_policy["bootstrap_samples"],
        "parity report bootstrap count differs from the frozen policy",
    )
    _require(
        uncertainty.get("resampling_unit")
        == parity_policy["document"]["resampling_unit"],
        "parity report resampling unit differs from the frozen policy",
    )
    low = _number(uncertainty.get("low"), "parity report uncertainty.low")
    high = _number(uncertainty.get("high"), "parity report uncertainty.high")
    _require(low <= high, "parity report uncertainty bounds are reversed")
    margin = _number(
        comparison.get("noninferiority_margin"),
        "parity report comparison.noninferiority_margin",
    )
    _require(
        _close(margin, float(parity_policy["noninferiority_margin"])),
        "parity report margin differs from the frozen SRT-015 policy",
    )
    computed_within = high <= margin
    _require(
        comparison.get("within_tolerance") is computed_within,
        "parity report within_tolerance does not follow the frozen rule",
    )
    _validate_structural_checks(report.get("structural_checks"))

    lineage = _mapping(report.get("lineage"), "parity report.lineage")
    _exact(
        lineage,
        {
            "configuration_cids",
            "model_cids",
            "implementation_raw_cids",
        },
        "parity report.lineage",
    )
    configuration_cids = _array(
        lineage.get("configuration_cids"),
        "parity report.lineage.configuration_cids",
    )
    _require(
        bool(configuration_cids),
        "parity report must bind at least one configuration CID",
    )
    for index, value in enumerate(configuration_cids):
        _canonical_cid(
            value,
            f"parity report.lineage.configuration_cids[{index}]",
        )
    model_cids = _array(
        lineage.get("model_cids"),
        "parity report.lineage.model_cids",
    )
    for index, value in enumerate(model_cids):
        _canonical_cid(
            value,
            f"parity report.lineage.model_cids[{index}]",
        )
    implementation_raw_cids = _mapping(
        lineage.get("implementation_raw_cids"),
        "parity report.lineage.implementation_raw_cids",
    )
    _exact(
        implementation_raw_cids,
        {"ir_schema", "compiler", "decompiler", "roundtrip"},
        "parity report.lineage.implementation_raw_cids",
    )
    for name, value in implementation_raw_cids.items():
        _canonical_cid(
            value,
            f"parity report.lineage.implementation_raw_cids.{name}",
            codecs=("raw",),
        )
    return {
        "report_cid": report_cid,
        "within_tolerance": computed_within,
        "upper_bound": high,
        "margin": margin,
        "configuration_cids": list(configuration_cids),
        "model_cids": list(model_cids),
        "implementation_raw_cids": dict(implementation_raw_cids),
    }


def _validate_stage_accounting(
    value: object,
    *,
    optional: bool,
) -> list[Mapping[str, Any]]:
    label = "optional_learned_stages" if optional else "deterministic_stages"
    stages = _array(value, f"$.selected_composition.{label}")
    if not optional:
        _require(bool(stages), "selected composition needs a deterministic stage")
    seen: set[str] = set()
    validated: list[Mapping[str, Any]] = []
    expected = {"stage_id", "component", "role"}
    if optional:
        expected |= {"bounded", "failure_behavior"}
    for index, raw_stage in enumerate(stages):
        path = f"$.selected_composition.{label}[{index}]"
        stage = _mapping(raw_stage, path)
        _exact(stage, expected, path)
        stage_id = _string(stage.get("stage_id"), f"{path}.stage_id")
        _require(stage_id not in seen, f"duplicate selected stage {stage_id!r}")
        seen.add(stage_id)
        _require(
            stage.get("component") in REQUESTED_TOOL_IDS,
            f"{path}.component is not a requested tool",
        )
        _require(
            stage.get("role")
            in {"constructor", "realizer", "validator", "advisor"},
            f"{path}.role is unsupported",
        )
        if optional:
            _require(stage.get("bounded") is True, f"{path}.bounded must be true")
            _require(
                stage.get("failure_behavior") in {"abstain", "hard_failure"},
                f"{path}.failure_behavior must reject silent fallback",
            )
        validated.append(stage)
    return validated


def _validate_tool_accounting(value: object) -> None:
    accounting = _mapping(value, "$.tool_accounting")
    _exact(
        accounting,
        {"requested_tool_ids", "scored_tool_ids", "unavailable", "unscored"},
        "$.tool_accounting",
    )
    requested = _array(
        accounting.get("requested_tool_ids"),
        "$.tool_accounting.requested_tool_ids",
    )
    _require(
        tuple(requested) == REQUESTED_TOOL_IDS,
        "$.tool_accounting.requested_tool_ids changed",
    )
    scored = _array(
        accounting.get("scored_tool_ids"),
        "$.tool_accounting.scored_tool_ids",
    )
    _require(
        all(isinstance(item, str) for item in scored)
        and len(scored) == len(set(scored)),
        "$.tool_accounting.scored_tool_ids must be unique strings",
    )
    classified: list[str] = list(scored)
    for category in ("unavailable", "unscored"):
        rows = _array(accounting.get(category), f"$.tool_accounting.{category}")
        for index, raw_row in enumerate(rows):
            path = f"$.tool_accounting.{category}[{index}]"
            row = _mapping(raw_row, path)
            _exact(row, {"tool_id", "reason"}, path)
            classified.append(_string(row.get("tool_id"), f"{path}.tool_id"))
            _string(row.get("reason"), f"{path}.reason")
    _require(
        set(classified) == set(REQUESTED_TOOL_IDS)
        and len(classified) == len(set(classified)),
        "every requested tool must be classified exactly once as scored, "
        "unavailable, or unscored",
    )


def _validate_commands(value: object) -> None:
    reproduction = _mapping(value, "$.reproduction")
    _exact(reproduction, {"commands", "supervisor_commands"}, "$.reproduction")
    requirements = (
        ("commands", REPRODUCTION_PURPOSES),
        ("supervisor_commands", SUPERVISOR_PURPOSES),
    )
    commands_by_purpose: dict[str, str] = {}
    for field, required_purposes in requirements:
        rows = _array(
            reproduction.get(field),
            f"$.reproduction.{field}",
        )
        purposes: list[str] = []
        for index, raw_row in enumerate(rows):
            path = f"$.reproduction.{field}[{index}]"
            row = _mapping(raw_row, path)
            _exact(row, {"purpose", "command"}, path)
            purpose = _string(row.get("purpose"), f"{path}.purpose")
            command = _string(row.get("command"), f"{path}.command")
            purposes.append(purpose)
            commands_by_purpose[purpose] = command
        _require(
            tuple(purposes) == required_purposes,
            f"$.reproduction.{field} purposes changed",
        )
    required_fragments = {
        "composition_report_validation": "--validate-report",
        "canonical_schema_tests": "test_canonical_roundtrip_schema.py",
        "canonical_parity_tests": "test_canonical_semantic_roundtrip.py",
        "decision_validation": "--validate-canonical-decision",
        "supervisor_plan": "semantic_roundtrip_scheduler.py plan",
        "supervisor_launch": "semantic_roundtrip_scheduler.py launch",
    }
    for purpose, fragment in required_fragments.items():
        _require(
            fragment in commands_by_purpose[purpose],
            f"reproduction command {purpose!r} omits {fragment!r}",
        )


def _composition_evidence(
    document: object,
    *,
    composition_validator: Callable[[object], Mapping[str, object]],
) -> dict[str, Any]:
    composition_validator(document)
    report = _mapping(document, "composition report")
    report_cid = _canonical_cid(
        report.get("report_cid"),
        "composition report.report_cid",
        codecs=("dag-json",),
    )
    selection = _mapping(report.get("selection"), "composition report.selection")
    statistics = _mapping(
        report.get("statistics"),
        "composition report.statistics",
    )
    summaries = _mapping(
        statistics.get("arm_summaries"),
        "composition report.statistics.arm_summaries",
    )
    inputs = _mapping(report.get("inputs"), "composition report.inputs")
    fixture = _mapping(inputs.get("fixture"), "composition report.inputs.fixture")
    case_ids = _array(
        fixture.get("case_ids"),
        "composition report.inputs.fixture.case_ids",
    )
    outcome = selection.get("outcome")
    winner = selection.get("winner")
    selectable_ids: list[str] = []
    default_arm: str | None = None
    if outcome == "selected":
        winner_map = _mapping(winner, "composition report.selection.winner")
        default_arm = _string(
            winner_map.get("arm_id"),
            "composition report.selection.winner.arm_id",
        )
        selectable_ids = [default_arm]
    elif outcome == "exact_tie":
        selectable_ids = [
            _string(item, "composition report.selection.co_winner_arm_ids item")
            for item in _array(
                selection.get("co_winner_arm_ids"),
                "composition report.selection.co_winner_arm_ids",
            )
        ]
    return {
        "report": report,
        "report_cid": report_cid,
        "selection_outcome": outcome,
        "default_arm": default_arm,
        "selectable_ids": selectable_ids,
        "summaries": summaries,
        "case_ids": case_ids,
    }


def validate_canonical_decision(
    value: object,
    *,
    repo_root: Path,
    composition_validator: Callable[[object], Mapping[str, object]],
) -> dict[str, object]:
    """Validate one source-bound SRT-019 selection or abstention."""

    decision_document = _mapping(value, "$")
    _exact(
        decision_document,
        {
            "interface",
            "schema_version",
            "decision_cid",
            "decision",
            "artifacts",
            "selected_composition",
            "parity",
            "tool_accounting",
            "lineage",
            "reproduction",
        },
        "$",
    )
    _require(
        decision_document.get("interface") == CANONICAL_DECISION_INTERFACE,
        f"$.interface must be {CANONICAL_DECISION_INTERFACE}",
    )
    _require(
        decision_document.get("schema_version") == CANONICAL_DECISION_SCHEMA,
        f"$.schema_version must be {CANONICAL_DECISION_SCHEMA}",
    )
    decision_cid = _validate_self_cid(
        decision_document,
        cid_field="decision_cid",
        path="$",
    )
    decision = _mapping(decision_document.get("decision"), "$.decision")
    _exact(
        decision,
        {
            "status",
            "selected_arm_id",
            "evidence_complete",
            "parity_passed",
            "reason_codes",
        },
        "$.decision",
    )
    status = decision.get("status")
    _require(
        status in {"selected", "declined"},
        "$.decision.status must be selected or declined",
    )
    _require(
        isinstance(decision.get("evidence_complete"), bool),
        "$.decision.evidence_complete must be boolean",
    )
    _require(
        isinstance(decision.get("parity_passed"), bool),
        "$.decision.parity_passed must be boolean",
    )
    reason_codes = _array(decision.get("reason_codes"), "$.decision.reason_codes")
    _require(
        all(isinstance(item, str) and item for item in reason_codes)
        and len(reason_codes) == len(set(reason_codes)),
        "$.decision.reason_codes must be unique nonempty strings",
    )

    artifacts = _mapping(decision_document.get("artifacts"), "$.artifacts")
    _exact(artifacts, set(CANONICAL_ARTIFACT_PATHS), "$.artifacts")
    bound: dict[str, tuple[Path, bytes]] = {}
    binding_errors: dict[str, str] = {}
    for name in CANONICAL_ARTIFACT_PATHS:
        raw_binding = artifacts.get(name)
        if raw_binding is None:
            continue
        try:
            bound[name] = _artifact_binding(
                raw_binding,
                artifact_name=name,
                repo_root=repo_root,
            )
        except CanonicalDecisionValidationError as exc:
            binding_errors[name] = str(exc)
    _require(
        not binding_errors,
        "artifact bindings are invalid: "
        + "; ".join(
            f"{name}: {error}" for name, error in sorted(binding_errors.items())
        ),
    )

    composition: dict[str, Any] | None = None
    composition_error = ""
    if "composition_report" in bound:
        try:
            composition_value, _ = _load_json(
                bound["composition_report"][0],
                "composition report",
            )
            composition = _composition_evidence(
                composition_value,
                composition_validator=composition_validator,
            )
        except (CanonicalDecisionValidationError, ValueError) as exc:
            composition_error = str(exc)
    else:
        composition_error = "composition report is not bound"

    selected_arm_id = decision.get("selected_arm_id")
    selected_composition = decision_document.get("selected_composition")
    selected_summary: Mapping[str, Any] | None = None
    selection_basis = ""
    if selected_composition is not None:
        selected = _mapping(selected_composition, "$.selected_composition")
        _exact(
            selected,
            {
                "arm_id",
                "selection_basis",
                "reconstruction_loss",
                "deterministic_stages",
                "optional_learned_stages",
            },
            "$.selected_composition",
        )
        arm_id = _string(selected.get("arm_id"), "$.selected_composition.arm_id")
        _require(
            selected_arm_id == arm_id,
            "$.decision.selected_arm_id and selected composition differ",
        )
        selection_basis = _string(
            selected.get("selection_basis"),
            "$.selected_composition.selection_basis",
        )
        _require(
            selection_basis in {
                "srt014_unique_winner",
                "srt015_bounded_tie_policy",
            },
            "$.selected_composition.selection_basis is unsupported",
        )
        _validate_stage_accounting(
            selected.get("deterministic_stages"),
            optional=False,
        )
        optional_stages = _validate_stage_accounting(
            selected.get("optional_learned_stages"),
            optional=True,
        )
        if composition is not None:
            _require(
                arm_id in composition["selectable_ids"],
                "selected arm is not an SRT-014 winner or bounded co-winner",
            )
            expected_basis = (
                "srt014_unique_winner"
                if composition["selection_outcome"] == "selected"
                else "srt015_bounded_tie_policy"
            )
            _require(
                selection_basis == expected_basis,
                "selection basis disagrees with the SRT-014 outcome",
            )
            selected_summary = _mapping(
                composition["summaries"].get(arm_id),
                f"composition report arm_summaries[{arm_id!r}]",
            )
            loss = _mapping(
                selected.get("reconstruction_loss"),
                "$.selected_composition.reconstruction_loss",
            )
            _exact(
                loss,
                {"metric", "aggregation", "mean", "uncertainty"},
                "$.selected_composition.reconstruction_loss",
            )
            _require(
                loss.get("metric") == "end_to_end_loss",
                "selected reconstruction metric changed",
            )
            _require(
                loss.get("aggregation")
                == "per_case_first_macro_mean",
                "selected reconstruction aggregation changed",
            )
            aggregate = _mapping(
                selected_summary.get("aggregate"),
                "selected arm aggregate",
            )
            expected_end = _mapping(
                aggregate.get("end_to_end"),
                "selected arm aggregate.end_to_end",
            )
            _require(
                _close(
                    _number(
                        loss.get("mean"),
                        "$.selected_composition.reconstruction_loss.mean",
                    ),
                    _number(
                        expected_end.get("mean"),
                        "selected arm aggregate.end_to_end.mean",
                    ),
                ),
                "selected reconstruction mean differs from SRT-014",
            )
            _require(
                loss.get("uncertainty") == expected_end.get("uncertainty"),
                "selected reconstruction uncertainty differs from SRT-014",
            )
            if optional_stages:
                lineage_preview = _mapping(
                    decision_document.get("lineage"),
                    "$.lineage",
                )
                _require(
                    bool(lineage_preview.get("model_cids")),
                    "learned selected stages require model CIDs",
                )
    else:
        _require(
            selected_arm_id is None,
            "$.selected_composition may be null only with no selected arm",
        )

    policy: dict[str, Any] | None = None
    policy_error = ""
    if composition is not None and "parity_policy" in bound:
        try:
            policy_value, _ = _load_json(
                bound["parity_policy"][0],
                "parity policy",
            )
            policy = validate_parity_policy(
                policy_value,
                composition_report_cid=composition["report_cid"],
            )
        except CanonicalDecisionValidationError as exc:
            policy_error = str(exc)
    else:
        policy_error = "composition evidence or parity policy is missing"

    parity_result: dict[str, Any] | None = None
    parity_error = ""
    if (
        composition is not None
        and policy is not None
        and isinstance(selected_arm_id, str)
        and selected_summary is not None
        and "parity_report" in bound
    ):
        try:
            parity_value, _ = _load_json(
                bound["parity_report"][0],
                "parity report",
            )
            parity_result = validate_parity_report(
                parity_value,
                composition_report_cid=composition["report_cid"],
                selected_arm_id=selected_arm_id,
                case_ids=composition["case_ids"],
                selected_per_case=_mapping(
                    selected_summary.get("per_case"),
                    "selected arm per_case",
                ),
                parity_policy=policy,
            )
        except CanonicalDecisionValidationError as exc:
            parity_error = str(exc)
    else:
        parity_error = "selection evidence or parity report is missing"

    required_selected_bindings = set(CANONICAL_ARTIFACT_PATHS)
    evidence_complete = (
        composition is not None
        and composition["selection_outcome"] in {"selected", "exact_tie"}
        and bool(composition["selectable_ids"])
        and policy is not None
        and required_selected_bindings <= set(bound)
        and selected_summary is not None
    )
    parity_passed = bool(
        parity_result is not None and parity_result["within_tolerance"]
    )
    if status == "selected":
        if composition_error:
            raise CanonicalDecisionValidationError(
                "selected decision composition evidence is invalid: "
                + composition_error
            )
        if policy_error:
            raise CanonicalDecisionValidationError(
                "selected decision parity policy is invalid: " + policy_error
            )
        if parity_error:
            raise CanonicalDecisionValidationError(
                "selected decision parity evidence is invalid: " + parity_error
            )
    _require(
        decision.get("evidence_complete") is evidence_complete,
        "$.decision.evidence_complete does not reflect bound source evidence",
    )
    _require(
        decision.get("parity_passed") is parity_passed,
        "$.decision.parity_passed does not reflect recomputed parity",
    )

    parity_summary = _mapping(decision_document.get("parity"), "$.parity")
    _exact(
        parity_summary,
        {
            "status",
            "policy_cid",
            "report_cid",
            "observed_upper_bound",
            "noninferiority_margin",
            "within_tolerance",
        },
        "$.parity",
    )
    if parity_result is not None and policy is not None:
        _require(
            parity_summary.get("status")
            == ("passed" if parity_passed else "failed"),
            "$.parity.status is inconsistent",
        )
        _require(
            parity_summary.get("policy_cid") == policy["policy_cid"],
            "$.parity.policy_cid changed",
        )
        _require(
            parity_summary.get("report_cid") == parity_result["report_cid"],
            "$.parity.report_cid changed",
        )
        _require(
            _close(
                _number(
                    parity_summary.get("observed_upper_bound"),
                    "$.parity.observed_upper_bound",
                ),
                float(parity_result["upper_bound"]),
            ),
            "$.parity.observed_upper_bound changed",
        )
        _require(
            _close(
                _number(
                    parity_summary.get("noninferiority_margin"),
                    "$.parity.noninferiority_margin",
                ),
                float(policy["noninferiority_margin"]),
            ),
            "$.parity.noninferiority_margin changed",
        )
        _require(
            parity_summary.get("within_tolerance") is parity_passed,
            "$.parity.within_tolerance changed",
        )
    else:
        _require(
            parity_summary.get("status") in {"incomplete", "failed"}
            and parity_summary.get("within_tolerance") is False,
            "missing parity evidence must be reported as incomplete or failed",
        )
        _require(
            parity_summary.get("policy_cid")
            == (policy["policy_cid"] if policy is not None else None),
            "$.parity.policy_cid must identify the validated policy or be null",
        )
        _require(
            parity_summary.get("report_cid") is None
            and parity_summary.get("observed_upper_bound") is None,
            "unvalidated parity evidence cannot publish a report CID or bound",
        )
        expected_margin = (
            policy["noninferiority_margin"] if policy is not None else None
        )
        supplied_margin = parity_summary.get("noninferiority_margin")
        _require(
            (
                supplied_margin is None
                if expected_margin is None
                else _close(
                    _number(
                        supplied_margin,
                        "$.parity.noninferiority_margin",
                    ),
                    float(expected_margin),
                )
            ),
            "$.parity.noninferiority_margin must match the validated policy "
            "or be null",
        )

    _validate_tool_accounting(decision_document.get("tool_accounting"))
    lineage = _mapping(decision_document.get("lineage"), "$.lineage")
    _exact(lineage, {"configuration_cids", "model_cids"}, "$.lineage")
    for field in ("configuration_cids", "model_cids"):
        values = _array(lineage.get(field), f"$.lineage.{field}")
        for index, cid in enumerate(values):
            _canonical_cid(cid, f"$.lineage.{field}[{index}]")
    if parity_result is not None:
        _require(
            lineage.get("configuration_cids")
            == parity_result["configuration_cids"],
            "$.lineage.configuration_cids differ from SRT-018",
        )
        _require(
            lineage.get("model_cids") == parity_result["model_cids"],
            "$.lineage.model_cids differ from SRT-018",
        )
        expected_implementation_cids = {
            name: _mapping(
                artifacts[name],
                f"$.artifacts.{name}",
            )["raw_cid"]
            for name in ("ir_schema", "compiler", "decompiler", "roundtrip")
        }
        _require(
            parity_result["implementation_raw_cids"]
            == expected_implementation_cids,
            "SRT-018 implementation CIDs differ from the SRT-019 bindings",
        )
    _validate_commands(decision_document.get("reproduction"))

    if status == "selected":
        _require(
            evidence_complete and parity_passed,
            "selected decision requires complete evidence and passing parity",
        )
        _require(
            selected_composition is not None
            and isinstance(selected_arm_id, str),
            "selected decision requires a selected composition",
        )
        _require(
            not reason_codes,
            "selected decision reason_codes must be empty",
        )
    else:
        _require(
            selected_composition is None and selected_arm_id is None,
            "declined decision must not identify a selected composition",
        )
        _require(
            not evidence_complete or not parity_passed,
            "declined decision requires incomplete evidence or failed parity",
        )
        _require(
            bool(reason_codes),
            "declined decision requires explicit reason_codes",
        )

    return {
        "status": "valid",
        "decision_status": status,
        "decision_cid": decision_cid,
        "selected_arm_id": selected_arm_id,
        "evidence_complete": evidence_complete,
        "parity_passed": parity_passed,
        "composition_error": composition_error or None,
        "policy_error": policy_error or None,
        "parity_error": parity_error or None,
    }


def validate_canonical_decision_file(
    decision_path: Path,
    *,
    repo_root: Path,
    composition_validator: Callable[[object], Mapping[str, object]],
) -> dict[str, object]:
    """Load strict canonical newline JSON and validate all source bindings."""

    value, raw = _load_json(decision_path, "canonical decision")
    try:
        canonical = canonical_dag_json_bytes(value) + b"\n"
    except (TypeError, ValueError) as exc:
        raise CanonicalDecisionValidationError(
            f"canonical decision is not finite DAG-JSON: {exc}"
        ) from exc
    _require(
        raw == canonical,
        "canonical decision must use canonical DAG-JSON bytes plus one newline",
    )
    return validate_canonical_decision(
        value,
        repo_root=repo_root,
        composition_validator=composition_validator,
    )


__all__ = [
    "CANONICAL_ARTIFACT_PATHS",
    "CANONICAL_DECISION_INTERFACE",
    "CANONICAL_DECISION_SCHEMA",
    "CanonicalDecisionValidationError",
    "PARITY_POLICY_INTERFACE",
    "PARITY_POLICY_SCHEMA",
    "PARITY_REPORT_INTERFACE",
    "PARITY_REPORT_SCHEMA",
    "REQUESTED_TOOL_IDS",
    "REPRODUCTION_PURPOSES",
    "SUPERVISOR_PURPOSES",
    "validate_canonical_decision",
    "validate_canonical_decision_file",
    "validate_parity_policy",
    "validate_parity_report",
]
