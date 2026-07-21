"""Promote stable autoencoder representations into deterministic LegalIR guidance.

The adaptive autoencoder is an advisor, never a source of canonical legal
semantics.  This module is the explicit promotion boundary: it accepts only a
source-free stable-feature export, resolves it against canonical view
contracts, and requires paired fixed-canary evidence before emitting guidance
records.  Every emitted record is content addressed and carries a deterministic
rollback recipe.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ....optimizers.logic_theorem_optimizer.modal_autoencoder import (
    LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
    LEGAL_IR_VIEW_FAMILIES,
    LEGAL_IR_VIEW_FAMILY_METRIC_NAMES,
    StableLegalIRFeatureExport,
    legal_ir_view_family_name,
)
from .legal_ir_view_contracts import LegalIRViewContract, legal_ir_view_contracts


LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION: Final = "legal-ir-learned-guidance-v1"
LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION: Final = (
    "legal-ir-learned-guidance-promotion-v1"
)
LEGAL_IR_LEARNED_GUIDANCE_CANARY_SCHEMA_VERSION: Final = (
    "legal-ir-learned-guidance-fixed-canary-v1"
)
LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION: Final = (
    "legal-ir-learned-guidance-rollback-v1"
)
TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION: Final = (
    "legal-ir-trusted-feedback-ablation-v1"
)

_LOWER_IS_BETTER_METRICS = frozenset(
    {
        "autoencoder_cross_entropy_loss",
        "ir_cross_entropy_loss",
        "source_copy_penalty",
    }
)
_HARD_GUARDRAIL_METRICS = (
    "source_copy_penalty",
    "symbolic_validity_success_rate",
)
_FEATURE_GROUPS = frozenset(
    {
        "compiler_contract",
        "contract_id",
        "cycle_consistency",
        "decompiler_surface_template",
        "logic_view_contract",
        "repair_lane",
        "semantic_slot",
    }
)
_FORBIDDEN_FEATURE_MARKERS = (
    "raw-source",
    "raw_source",
    "sample-memory",
    "sample_memory",
    "source-copy",
    "source-text",
    "source-span",
    "source_copy",
    "source_text",
    "source_span",
    "token:",
    "token2:",
    "token3:",
)


class _SerializableMapping(Mapping[str, Any]):
    """Small compatibility layer for both attribute and dictionary callers."""

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract protocol
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class LegalIRFixedCanaryEvidence(_SerializableMapping):
    """Paired per-family metric evidence for one immutable canary corpus."""

    canary_id: str
    evidence_id: str
    family_metrics: Mapping[str, Mapping[str, Any]]
    metric_tolerance: float
    missing_guardrail_evidence: tuple[str, ...] = ()
    metric_regressions: tuple[str, ...] = ()
    source_copy_regressions: tuple[str, ...] = ()
    symbolic_validity_regressions: tuple[str, ...] = ()
    fixed_sample_set: bool = True
    schema_version: str = LEGAL_IR_LEARNED_GUIDANCE_CANARY_SCHEMA_VERSION

    @property
    def guardrails_passed(self) -> bool:
        return not (
            self.missing_guardrail_evidence
            or self.metric_regressions
            or self.source_copy_regressions
            or self.symbolic_validity_regressions
            or not self.fixed_sample_set
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_id": self.canary_id,
            "evidence_id": self.evidence_id,
            "family_metrics": _canonical_json_value(self.family_metrics),
            "fixed_sample_set": self.fixed_sample_set,
            "guardrails_passed": self.guardrails_passed,
            "metric_regressions": list(self.metric_regressions),
            "metric_tolerance": self.metric_tolerance,
            "missing_guardrail_evidence": list(self.missing_guardrail_evidence),
            "schema_version": self.schema_version,
            "source_copy_regressions": list(self.source_copy_regressions),
            "symbolic_validity_regressions": list(
                self.symbolic_validity_regressions
            ),
        }


@dataclass(frozen=True)
class LegalIRLearnedGuidanceRecord(_SerializableMapping):
    """One promoted compiler/decompiler guidance record."""

    guidance_id: str
    promotion_id: str
    contract_id: str
    view_family: str
    target_component: str
    guidance_kind: str
    view_family_weight: float
    confidence: float
    stable_features: tuple[Mapping[str, Any], ...]
    repair_lane_suggestions: tuple[str, ...]
    repair_lane_records: tuple[Mapping[str, Any], ...]
    canary_metric_evidence: Mapping[str, Any]
    rollback_metadata: Mapping[str, Any]
    source_export_id: str
    schema_version: str = LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_metric_evidence": _canonical_json_value(
                self.canary_metric_evidence
            ),
            "confidence": round(self.confidence, 12),
            "contract_id": self.contract_id,
            "guidance_id": self.guidance_id,
            "guidance_kind": self.guidance_kind,
            "promotion_id": self.promotion_id,
            "repair_lane_records": _canonical_json_value(self.repair_lane_records),
            "repair_lane_suggestions": list(self.repair_lane_suggestions),
            "rollback_metadata": _canonical_json_value(self.rollback_metadata),
            "schema_version": self.schema_version,
            "source": "stable_autoencoder_feature_promotion",
            "source_export_id": self.source_export_id,
            "stable_features": _canonical_json_value(self.stable_features),
            "target_component": self.target_component,
            "view_family": self.view_family,
            "view_family_weight": round(self.view_family_weight, 12),
            "view_family_weights": {
                self.view_family: round(self.view_family_weight, 12)
            },
        }


@dataclass(frozen=True)
class LegalIRLearnedGuidancePromotion(_SerializableMapping):
    """Auditable result of one learned-guidance promotion attempt."""

    promotion_id: str
    source_export_id: str
    promoted: bool
    records: tuple[LegalIRLearnedGuidanceRecord, ...]
    block_reasons: tuple[str, ...]
    canary_evidence: LegalIRFixedCanaryEvidence
    rollback_metadata: Mapping[str, Any]
    learned_export: Mapping[str, Any] = field(default_factory=dict)
    compiler_commit: str = ""
    proof_receipts: tuple[Mapping[str, Any], ...] = ()
    causal_evidence: Mapping[str, Any] = field(default_factory=dict)
    source_copy_checks: Mapping[str, Any] = field(default_factory=dict)
    activation_state: Mapping[str, Any] = field(default_factory=dict)
    fixed_canary_binding: Mapping[str, Any] = field(default_factory=dict)
    eligible_snapshot_id: str = ""
    report_artifact_path: str = ""
    candidate_record_count: int = 0
    schema_version: str = LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION

    @property
    def promotion_allowed(self) -> bool:
        return self.promoted

    @property
    def report_outcome(self) -> str:
        if self.promoted:
            return "success"
        no_candidate_reasons = {
            "missing_view_family_weights",
            "no_canonical_contracts_resolved",
            "no_guidance_records_met_promotion_threshold",
            "no_stable_learned_features",
        }
        if self.candidate_record_count <= 0 and any(
            reason in no_candidate_reasons for reason in self.block_reasons
        ):
            return "no_candidate"
        return "rejection"

    @property
    def status(self) -> str:
        if self.promoted:
            return "promoted"
        return self.report_outcome

    def to_dict(self) -> dict[str, Any]:
        records = [record.to_dict() for record in self.records]
        proof_receipts = _canonical_json_value(self.proof_receipts)
        return {
            "activation_state": _canonical_json_value(self.activation_state),
            "block_reasons": list(self.block_reasons),
            "canary_evidence": self.canary_evidence.to_dict(),
            "candidate_record_count": self.candidate_record_count,
            "causal_evidence": _canonical_json_value(self.causal_evidence),
            "compiler_commit": self.compiler_commit,
            "eligible_snapshot_id": self.eligible_snapshot_id,
            "fixed_canary_binding": _canonical_json_value(
                self.fixed_canary_binding
            ),
            "guidance_records": records,
            "learned_export": _canonical_json_value(self.learned_export),
            "learned_export_id": self.source_export_id,
            "learned_export_sha256": str(
                self.learned_export.get("sha256")
                or self.learned_export.get("export_sha256")
                or ""
            ),
            "proof_receipt_ids": [
                str(receipt.get("receipt_id") or receipt.get("id") or "")
                for receipt in proof_receipts
                if isinstance(receipt, Mapping)
                and str(receipt.get("receipt_id") or receipt.get("id") or "")
            ],
            "proof_receipts": proof_receipts,
            "promoted": self.promoted,
            "promotion_allowed": self.promotion_allowed,
            "promotion_id": self.promotion_id,
            "promotion_report_outcome": self.report_outcome,
            "report_artifact_path": self.report_artifact_path,
            "report_outcome": self.report_outcome,
            "records": records,
            "rollback_metadata": _canonical_json_value(self.rollback_metadata),
            "schema_version": self.schema_version,
            "source_copy_checks": _canonical_json_value(self.source_copy_checks),
            "source_export_id": self.source_export_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class TrustedFeedbackAblationEvidence(_SerializableMapping):
    """Immutable held-out evidence authorizing trusted-feedback writes.

    A feedback label being trusted is necessary but not sufficient for changing
    production weights.  This receipt records a paired evaluation on one fixed
    holdout, verifies that none of the training samples leaked into it, and
    requires both a positive primary-objective delta and intact source-copy and
    symbolic-validity guardrails.
    """

    ablation_id: str
    holdout_id: str
    primary_metric: str
    baseline_primary_value: float
    candidate_primary_value: float
    heldout_improvement: float
    minimum_improvement: float
    training_sample_ids: tuple[str, ...]
    heldout_sample_ids: tuple[str, ...]
    fixed_sample_set: bool
    holdout_isolated: bool
    source_copy_guard_passed: bool
    symbolic_validity_guard_passed: bool
    metric_guardrails_passed: bool
    block_reasons: tuple[str, ...] = ()
    metric_deltas: Mapping[str, float] = field(default_factory=dict)
    schema_version: str = TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION

    @property
    def heldout_benefit(self) -> bool:
        return (
            self.heldout_improvement > 0.0
            and self.heldout_improvement >= self.minimum_improvement
        )

    @property
    def production_writes_allowed(self) -> bool:
        return (
            bool(self.holdout_id)
            and bool(self.heldout_sample_ids)
            and self.fixed_sample_set
            and self.holdout_isolated
            and self.heldout_benefit
            and self.source_copy_guard_passed
            and self.symbolic_validity_guard_passed
            and self.metric_guardrails_passed
            and not self.block_reasons
        )

    @property
    def status(self) -> str:
        return "passed" if self.production_writes_allowed else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ablation_id": self.ablation_id,
            "baseline_primary_value": round(self.baseline_primary_value, 12),
            "block_reasons": list(self.block_reasons),
            "candidate_primary_value": round(self.candidate_primary_value, 12),
            "fixed_sample_set": self.fixed_sample_set,
            "heldout_benefit": self.heldout_benefit,
            "heldout_improvement": round(self.heldout_improvement, 12),
            "heldout_sample_ids": list(self.heldout_sample_ids),
            "holdout_id": self.holdout_id,
            "holdout_isolated": self.holdout_isolated,
            "metric_deltas": {
                str(key): round(float(value), 12)
                for key, value in sorted(self.metric_deltas.items())
            },
            "metric_guardrails_passed": self.metric_guardrails_passed,
            "minimum_improvement": round(self.minimum_improvement, 12),
            "primary_metric": self.primary_metric,
            "production_writes_allowed": self.production_writes_allowed,
            "schema_version": self.schema_version,
            "source_copy_guard_passed": self.source_copy_guard_passed,
            "status": self.status,
            "symbolic_validity_guard_passed": (
                self.symbolic_validity_guard_passed
            ),
            "training_sample_ids": list(self.training_sample_ids),
        }


_TRUSTED_FEEDBACK_LOWER_IS_BETTER = frozenset(
    {
        "autoencoder_cross_entropy_loss",
        "compiler_ir_cross_entropy_loss",
        "ir_cross_entropy_loss",
        "legal_ir_view_cross_entropy_loss",
        "objective_loss",
        "reconstruction_loss",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
    }
)
_TRUSTED_FEEDBACK_PRIMARY_METRICS = (
    "legal_ir_view_cross_entropy_loss",
    "compiler_ir_cross_entropy_loss",
    "autoencoder_cross_entropy_loss",
    "ir_cross_entropy_loss",
    "objective_loss",
)


def evaluate_trusted_feedback_ablation(
    baseline_metrics: Mapping[str, Any] | Any,
    candidate_metrics: Mapping[str, Any] | Any,
    *,
    heldout_sample_ids: Sequence[str],
    training_sample_ids: Sequence[str] = (),
    holdout_id: str = "",
    baseline_holdout_id: str = "",
    candidate_holdout_id: str = "",
    primary_metric: str = "",
    minimum_improvement: float = 1.0e-9,
    metric_tolerance: float = 0.0,
) -> TrustedFeedbackAblationEvidence:
    """Build the fail-closed ablation receipt required for production writes.

    Metric payloads may be flat or contain per-family metric mappings.  Values
    are averaged across families, so a caller cannot obtain a pass by relying
    on mapping order.  The source-copy and symbolic-validity guards are always
    checked when present and missing hard-guard evidence blocks the receipt.
    """

    baseline = _flatten_ablation_metrics(_as_mapping(baseline_metrics))
    candidate = _flatten_ablation_metrics(_as_mapping(candidate_metrics))
    baseline_id = str(
        baseline_holdout_id
        or _as_mapping(baseline_metrics).get("holdout_id")
        or _as_mapping(baseline_metrics).get("canary_id")
        or holdout_id
        or ""
    )
    candidate_id = str(
        candidate_holdout_id
        or _as_mapping(candidate_metrics).get("holdout_id")
        or _as_mapping(candidate_metrics).get("canary_id")
        or holdout_id
        or ""
    )
    resolved_holdout_id = str(holdout_id or baseline_id or candidate_id)
    fixed = bool(resolved_holdout_id) and baseline_id == candidate_id == resolved_holdout_id
    train_ids = tuple(sorted({str(value) for value in training_sample_ids if str(value)}))
    heldout_ids = tuple(sorted({str(value) for value in heldout_sample_ids if str(value)}))
    isolated = bool(heldout_ids) and not set(train_ids).intersection(heldout_ids)
    metric = str(primary_metric or "")
    if not metric:
        metric = next(
            (
                name
                for name in _TRUSTED_FEEDBACK_PRIMARY_METRICS
                if name in baseline and name in candidate
            ),
            "",
        )
    before = _finite_float(baseline.get(metric)) if metric else None
    after = _finite_float(candidate.get(metric)) if metric else None
    raw_minimum = float(minimum_improvement)
    raw_tolerance = float(metric_tolerance)
    if not math.isfinite(raw_minimum) or raw_minimum < 0.0:
        raise ValueError("minimum_improvement must be finite and non-negative")
    if not math.isfinite(raw_tolerance) or raw_tolerance < 0.0:
        raise ValueError("metric_tolerance must be finite and non-negative")
    minimum = raw_minimum
    tolerance = raw_tolerance
    deltas: dict[str, float] = {}
    regressions: list[str] = []
    for name in sorted(set(baseline).intersection(candidate)):
        before_value = _finite_float(baseline[name])
        after_value = _finite_float(candidate[name])
        if before_value is None or after_value is None:
            continue
        improvement = (
            before_value - after_value
            if name in _TRUSTED_FEEDBACK_LOWER_IS_BETTER
            else after_value - before_value
        )
        deltas[name] = round(improvement, 12)
        if improvement < -tolerance:
            regressions.append(name)

    copy_names = (
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
    )
    symbolic_name = "symbolic_validity_success_rate"
    copy_present = any(name in baseline and name in candidate for name in copy_names)
    symbolic_present = symbolic_name in baseline and symbolic_name in candidate
    copy_passed = copy_present and all(
        deltas.get(name, -math.inf) >= -tolerance
        for name in copy_names
        if name in baseline and name in candidate
    )
    symbolic_passed = symbolic_present and deltas.get(symbolic_name, -math.inf) >= -tolerance
    improvement = (
        (
            float(before) - float(after)
            if metric in _TRUSTED_FEEDBACK_LOWER_IS_BETTER
            else float(after) - float(before)
        )
        if before is not None and after is not None
        else -math.inf
    )
    reasons: list[str] = []
    if not fixed:
        reasons.append("fixed_holdout_identity_missing_or_mismatched")
    if not heldout_ids:
        reasons.append("heldout_samples_missing")
    if not isolated:
        reasons.append("train_holdout_overlap")
    if not metric or before is None or after is None:
        reasons.append("primary_metric_missing")
    elif improvement <= 0.0 or improvement < minimum:
        reasons.append("heldout_benefit_not_demonstrated")
    if not copy_present:
        reasons.append("source_copy_guardrail_evidence_missing")
    elif not copy_passed:
        reasons.append("source_copy_guardrail_regression")
    if not symbolic_present:
        reasons.append("symbolic_validity_guardrail_evidence_missing")
    elif not symbolic_passed:
        reasons.append("symbolic_validity_guardrail_regression")
    non_hard_regressions = sorted(
        set(regressions) - set(copy_names) - {symbolic_name}
    )
    if non_hard_regressions:
        reasons.append("heldout_metric_regression")
    descriptor = {
        "baseline": baseline,
        "candidate": candidate,
        "heldout_sample_ids": heldout_ids,
        "holdout_id": resolved_holdout_id,
        "minimum_improvement": minimum,
        "primary_metric": metric,
        "training_sample_ids": train_ids,
    }
    return TrustedFeedbackAblationEvidence(
        ablation_id="lir-trusted-feedback-ablation-" + _stable_hash(descriptor)[:24],
        holdout_id=resolved_holdout_id,
        primary_metric=metric,
        baseline_primary_value=float(before) if before is not None else 0.0,
        candidate_primary_value=float(after) if after is not None else 0.0,
        heldout_improvement=(
            float(improvement) if math.isfinite(improvement) else 0.0
        ),
        minimum_improvement=minimum,
        training_sample_ids=train_ids,
        heldout_sample_ids=heldout_ids,
        fixed_sample_set=fixed,
        holdout_isolated=isolated,
        source_copy_guard_passed=copy_passed,
        symbolic_validity_guard_passed=symbolic_passed,
        metric_guardrails_passed=not non_hard_regressions,
        block_reasons=tuple(reasons),
        metric_deltas=deltas,
    )


def evaluate_trusted_feedback_weight_ablation(
    *args: Any, **kwargs: Any
) -> TrustedFeedbackAblationEvidence:
    """Compatibility alias with the weight-update terminology."""

    return evaluate_trusted_feedback_ablation(*args, **kwargs)


def evaluate_fixed_canary_evidence(
    baseline_metrics: Mapping[str, Any] | Any,
    candidate_metrics: Mapping[str, Any] | Any,
    *,
    fixed_canary_id: str = "",
    required_families: Sequence[str] = (),
    metric_tolerance: float = 0.0,
) -> LegalIRFixedCanaryEvidence:
    """Compare paired canary metrics and identify all promotion regressions."""

    baseline = _as_mapping(baseline_metrics)
    candidate = _as_mapping(candidate_metrics)
    canary_id, fixed_sample_set = _resolve_fixed_canary_id(
        baseline, candidate, fixed_canary_id
    )
    before_by_family = _family_metric_mapping(baseline)
    after_by_family = _family_metric_mapping(candidate)
    families = tuple(
        family
        for family in LEGAL_IR_VIEW_FAMILIES
        if family in set(required_families)
        or (not required_families and family in before_by_family)
        or (not required_families and family in after_by_family)
    )
    tolerance = max(0.0, float(metric_tolerance))
    evidence: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    regressions: list[str] = []
    copy_regressions: list[str] = []
    symbolic_regressions: list[str] = []
    for family in families:
        before = before_by_family.get(family, {})
        after = after_by_family.get(family, {})
        deltas: dict[str, float] = {}
        family_regressions: list[str] = []
        for metric_name in LEGAL_IR_VIEW_FAMILY_METRIC_NAMES:
            if metric_name not in before or metric_name not in after:
                continue
            before_value = float(before[metric_name])
            after_value = float(after[metric_name])
            improvement = (
                before_value - after_value
                if metric_name in _LOWER_IS_BETTER_METRICS
                else after_value - before_value
            )
            deltas[metric_name] = round(improvement, 12)
            if improvement < -tolerance:
                marker = f"{family}:{metric_name}"
                family_regressions.append(metric_name)
                regressions.append(marker)
                if metric_name == "source_copy_penalty":
                    copy_regressions.append(family)
                elif metric_name == "symbolic_validity_success_rate":
                    symbolic_regressions.append(family)
        for guardrail in _HARD_GUARDRAIL_METRICS:
            if guardrail not in before or guardrail not in after:
                missing.append(f"{family}:{guardrail}")
        evidence[family] = {
            "baseline": {
                key: round(float(value), 12) for key, value in sorted(before.items())
            },
            "candidate": {
                key: round(float(value), 12) for key, value in sorted(after.items())
            },
            "deltas": dict(sorted(deltas.items())),
            "guardrails_passed": not family_regressions
            and not any(item.startswith(f"{family}:") for item in missing),
            "regressions": sorted(family_regressions),
        }
    payload = {
        "canary_id": canary_id,
        "family_metrics": evidence,
        "fixed_sample_set": fixed_sample_set,
        "metric_tolerance": tolerance,
        "missing": sorted(set(missing)),
        "regressions": sorted(set(regressions)),
    }
    return LegalIRFixedCanaryEvidence(
        canary_id=canary_id,
        evidence_id="lir-canary-evidence-" + _stable_hash(payload)[:24],
        family_metrics=evidence,
        metric_tolerance=tolerance,
        missing_guardrail_evidence=tuple(sorted(set(missing))),
        metric_regressions=tuple(sorted(set(regressions))),
        source_copy_regressions=tuple(sorted(set(copy_regressions))),
        symbolic_validity_regressions=tuple(sorted(set(symbolic_regressions))),
        fixed_sample_set=fixed_sample_set,
    )


def promote_learned_autoencoder_guidance(
    autoencoder_or_export: Any,
    samples: Iterable[Any] = (),
    *,
    baseline_canary_metrics: Mapping[str, Any] | Any = None,
    candidate_canary_metrics: Mapping[str, Any] | Any = None,
    fixed_canary_id: str = "",
    compiler_commit: str = "",
    proof_receipts: Sequence[Mapping[str, Any]] | None = None,
    causal_evidence: Mapping[str, Any] | None = None,
    source_copy_checks: Mapping[str, Any] | None = None,
    activation_state: Mapping[str, Any] | None = None,
    eligible_snapshot_id: str = "",
    report_artifact_path: str = "",
    metric_tolerance: float = 0.0,
    min_confidence: float = 0.0,
    previous_promotion_id: str = "",
    max_features_per_record: int = 12,
    min_sample_support: int = 1,
) -> LegalIRLearnedGuidancePromotion:
    """Promote stable autoencoder features when fixed-canary guardrails pass.

    ``autoencoder_or_export`` may be an adaptive autoencoder, a
    :class:`StableLegalIRFeatureExport`, or its serialized mapping.  Supporting
    all three keeps training, offline review, and deployment paths identical.
    """

    export = _stable_export_mapping(
        autoencoder_or_export,
        samples,
        min_sample_support=min_sample_support,
    )
    export_id = str(export.get("export_id") or "")
    export_binding = _learned_export_binding(export)
    stable_features, unsafe_feature_count = _stable_features(export)
    family_weights = _view_family_weights(export)
    contracts = _selected_contracts(export, family_weights)
    required_families = tuple(
        family
        for family in LEGAL_IR_VIEW_FAMILIES
        if family in family_weights
        and any(_contract_family(contract) == family for contract in contracts)
    )
    canary = evaluate_fixed_canary_evidence(
        baseline_canary_metrics,
        candidate_canary_metrics,
        fixed_canary_id=fixed_canary_id,
        required_families=required_families,
        metric_tolerance=metric_tolerance,
    )
    normalized_receipts = _proof_receipts(export, proof_receipts)
    resolved_compiler_commit = str(
        compiler_commit
        or export.get("compiler_commit")
        or _as_mapping(baseline_canary_metrics).get("compiler_commit")
        or _as_mapping(candidate_canary_metrics).get("compiler_commit")
        or ""
    ).strip()

    block_reasons: list[str] = []
    if str(export.get("schema_version") or "") != (
        LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION
    ):
        block_reasons.append("unsupported_stable_feature_export_schema")
    if not export_id:
        block_reasons.append("learned_export_id_missing")
    if not resolved_compiler_commit:
        block_reasons.append("compiler_commit_missing")
    if not normalized_receipts:
        block_reasons.append("proof_receipts_missing")
    if bool(export.get("sample_memory_included")):
        block_reasons.append("sample_memory_features_present")
    if unsafe_feature_count:
        block_reasons.append("unsafe_or_unstable_features_present")
    if not stable_features:
        block_reasons.append("no_stable_learned_features")
    if not family_weights:
        block_reasons.append("missing_view_family_weights")
    if not contracts:
        block_reasons.append("no_canonical_contracts_resolved")
    if not canary.canary_id or not canary.fixed_sample_set:
        block_reasons.append("fixed_canary_identity_missing_or_mismatched")
    if canary.missing_guardrail_evidence:
        block_reasons.append("fixed_canary_guardrail_evidence_incomplete")
    if canary.source_copy_regressions:
        block_reasons.append("source_copy_guardrail_regression")
    if canary.symbolic_validity_regressions:
        block_reasons.append("symbolic_validity_guardrail_regression")
    if canary.metric_regressions and not (
        canary.source_copy_regressions or canary.symbolic_validity_regressions
    ):
        block_reasons.append("view_family_metric_regression")

    candidate_descriptor = {
        "canary_evidence_id": canary.evidence_id,
        "compiler_commit": resolved_compiler_commit,
        "contract_ids": [contract.contract_id for contract in contracts],
        "export_id": export_id,
        "export_sha256": export_binding.get("sha256", ""),
        "family_weights": family_weights,
        "features": stable_features,
        "proof_receipt_ids": [
            str(receipt.get("receipt_id") or receipt.get("id") or "")
            for receipt in normalized_receipts
        ],
    }
    promotion_id = "lir-guidance-promotion-" + _stable_hash(candidate_descriptor)[:24]
    rollback_metadata = _rollback_metadata(
        promotion_id=promotion_id,
        previous_promotion_id=previous_promotion_id,
        source_export_id=export_id,
        canary_evidence_id=canary.evidence_id,
        contract_ids=[contract.contract_id for contract in contracts],
    )

    candidate_records: list[LegalIRLearnedGuidanceRecord] = []
    for contract in contracts:
        family = _contract_family(contract)
        weight = family_weights.get(family, 0.0)
        if weight <= 0.0:
            continue
        record_features = _features_for_contract(
            stable_features,
            contract,
            limit=max_features_per_record,
        )
        if not record_features:
            continue
        lane_records = _repair_lane_records(export, contract)
        confidence = _guidance_confidence(
            record_features,
            weight,
            canary.family_metrics.get(family, {}),
        )
        if confidence < max(0.0, float(min_confidence)):
            continue
        record_descriptor = {
            "contract_id": contract.contract_id,
            "features": record_features,
            "promotion_id": promotion_id,
            "repair_lanes": [lane["lane_id"] for lane in lane_records],
            "view_family_weight": weight,
        }
        record_rollback = {
            **rollback_metadata,
            "remove_guidance_id": "lir-guidance-" + _stable_hash(record_descriptor)[:24],
        }
        candidate_records.append(
            LegalIRLearnedGuidanceRecord(
                guidance_id=str(record_rollback["remove_guidance_id"]),
                promotion_id=promotion_id,
                contract_id=contract.contract_id,
                view_family=family,
                target_component=contract.target_component,
                guidance_kind=(
                    "decompiler" if family == "decompiler" else "compiler"
                ),
                view_family_weight=weight,
                confidence=confidence,
                stable_features=tuple(record_features),
                repair_lane_suggestions=tuple(
                    str(lane["lane_id"]) for lane in lane_records
                ),
                repair_lane_records=tuple(lane_records),
                canary_metric_evidence={
                    "canary_id": canary.canary_id,
                    "evidence_id": canary.evidence_id,
                    **dict(canary.family_metrics.get(family, {})),
                },
                rollback_metadata=record_rollback,
                source_export_id=export_id,
            )
        )
    if not candidate_records:
        block_reasons.append("no_guidance_records_met_promotion_threshold")
    block_reasons = list(dict.fromkeys(block_reasons))
    promoted = not block_reasons
    fixed_canary_binding = {
        "canary_id": canary.canary_id,
        "evidence_id": canary.evidence_id,
        "fixed_sample_set": canary.fixed_sample_set,
        "guardrails_passed": canary.guardrails_passed,
        "metric_tolerance": canary.metric_tolerance,
        "schema_version": canary.schema_version,
    }
    resolved_source_copy_checks = _source_copy_check_report(
        export,
        stable_features=stable_features,
        unsafe_feature_count=unsafe_feature_count,
        canary=canary,
        overrides=source_copy_checks,
    )
    resolved_causal_evidence = _causal_evidence_report(
        canary=canary,
        family_weights=family_weights,
        compiler_commit=resolved_compiler_commit,
        proof_receipts=normalized_receipts,
        overrides=causal_evidence,
    )
    resolved_activation_state = _activation_state_report(
        promoted=promoted,
        promotion_id=promotion_id,
        block_reasons=block_reasons,
        overrides=activation_state,
    )
    return LegalIRLearnedGuidancePromotion(
        promotion_id=promotion_id,
        source_export_id=export_id,
        promoted=promoted,
        records=tuple(candidate_records) if promoted else (),
        block_reasons=tuple(block_reasons),
        canary_evidence=canary,
        rollback_metadata={
            **rollback_metadata,
            "activation_allowed": promoted,
            "block_reasons": block_reasons,
        },
        learned_export=export_binding,
        compiler_commit=resolved_compiler_commit,
        proof_receipts=tuple(normalized_receipts),
        causal_evidence=resolved_causal_evidence,
        source_copy_checks=resolved_source_copy_checks,
        activation_state=resolved_activation_state,
        fixed_canary_binding=fixed_canary_binding,
        eligible_snapshot_id=str(eligible_snapshot_id or "").strip(),
        report_artifact_path=str(report_artifact_path or "").strip(),
        candidate_record_count=len(candidate_records),
    )


def promote_legal_ir_learned_guidance(
    *args: Any, **kwargs: Any
) -> LegalIRLearnedGuidancePromotion:
    """Alias for the canonical autoencoder promotion entry point."""

    return promote_learned_autoencoder_guidance(*args, **kwargs)


def legal_ir_learned_guidance_promotion(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return a JSON-ready promotion result for pipeline callers."""

    return promote_learned_autoencoder_guidance(*args, **kwargs).to_dict()


def build_legal_ir_learned_guidance_records(
    *args: Any, **kwargs: Any
) -> list[LegalIRLearnedGuidanceRecord]:
    """Return promoted records, or an empty list when any guardrail blocks."""

    return list(promote_learned_autoencoder_guidance(*args, **kwargs).records)


def _stable_export_mapping(
    value: Any,
    samples: Iterable[Any],
    *,
    min_sample_support: int,
) -> dict[str, Any]:
    if isinstance(value, StableLegalIRFeatureExport):
        return value.to_dict()
    if hasattr(value, "export_stable_legal_ir_features"):
        exported = value.export_stable_legal_ir_features(
            samples,
            min_sample_support=min_sample_support,
        )
        return _as_mapping(exported)
    return _as_mapping(value)


def _stable_features(export: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    raw_features = export.get("stable_features")
    if not isinstance(raw_features, Sequence) or isinstance(
        raw_features, (str, bytes)
    ):
        return [], 0
    safe: list[dict[str, Any]] = []
    unsafe_count = 0
    for raw in raw_features:
        item = _as_mapping(raw)
        feature = str(item.get("feature") or "").strip()
        group = str(item.get("feature_group") or "").strip()
        weight = _finite_nonnegative(item.get("weight"))
        is_safe = (
            bool(feature)
            and len(feature.encode("utf-8")) <= 512
            and group in _FEATURE_GROUPS
            and item.get("stable") is True
            and weight > 0.0
            and not any(
                marker in feature.lower() for marker in _FORBIDDEN_FEATURE_MARKERS
            )
        )
        if not is_safe:
            unsafe_count += 1
            continue
        safe.append(
            {
                "feature": feature,
                "feature_group": group,
                "feature_id": "lir-feature-" + _stable_hash(feature)[:20],
                "support_ratio": round(
                    min(
                        1.0,
                        _finite_nonnegative(item.get("support_ratio", 1.0)),
                    ),
                    12,
                ),
                "weight": round(weight, 12),
            }
        )
    deduped = {str(item["feature"]): item for item in safe}
    return sorted(
        deduped.values(),
        key=lambda item: (-float(item["weight"]), str(item["feature"])),
    ), unsafe_count


def _view_family_weights(export: Mapping[str, Any]) -> dict[str, float]:
    raw = export.get("view_family_weights")
    if not isinstance(raw, Mapping):
        return {}
    weights: dict[str, float] = {}
    for name, value in raw.items():
        family = legal_ir_view_family_name(str(name))
        if (
            family not in LEGAL_IR_VIEW_FAMILIES
            and str(name) in LEGAL_IR_VIEW_FAMILIES
        ):
            family = str(name)
        weight = _finite_nonnegative(value)
        if family in LEGAL_IR_VIEW_FAMILIES and weight > 0.0:
            weights[family] = weights.get(family, 0.0) + weight
    total = sum(weights.values())
    return {
        family: round(weights[family] / total, 12)
        for family in LEGAL_IR_VIEW_FAMILIES
        if total > 0.0 and weights.get(family, 0.0) > 0.0
    }


def _selected_contracts(
    export: Mapping[str, Any], family_weights: Mapping[str, float]
) -> list[LegalIRViewContract]:
    contracts = list(legal_ir_view_contracts())
    raw_atoms = export.get("contract_feature_atoms")
    has_declared_contracts = isinstance(raw_atoms, Sequence) and not isinstance(
        raw_atoms, (str, bytes)
    ) and bool(raw_atoms)
    atoms = (
        {_identifier_atom(value) for value in raw_atoms}
        if has_declared_contracts
        else set()
    )
    explicitly_selected = [
        contract
        for contract in contracts
        if _identifier_atom(contract.contract_id) in atoms
        or _identifier_atom(contract.view.value) in atoms
        or _identifier_atom(contract.target_component) in atoms
    ]
    candidates = explicitly_selected if has_declared_contracts else contracts
    return [
        contract
        for contract in candidates
        if family_weights.get(_contract_family(contract), 0.0) > 0.0
    ]


def _features_for_contract(
    features: Sequence[Mapping[str, Any]],
    contract: LegalIRViewContract,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    decompiler = _contract_family(contract) == "decompiler"
    preferred_groups = (
        {
            "contract_id",
            "cycle_consistency",
            "decompiler_surface_template",
            "logic_view_contract",
            "repair_lane",
        }
        if decompiler
        else {
            "compiler_contract",
            "contract_id",
            "cycle_consistency",
            "logic_view_contract",
            "repair_lane",
            "semantic_slot",
        }
    )
    preferred = [
        dict(item)
        for item in features
        if item.get("feature_group") in preferred_groups
    ]
    return preferred[: max(0, int(limit))]


def _repair_lane_records(
    export: Mapping[str, Any], contract: LegalIRViewContract
) -> list[dict[str, Any]]:
    raw_atoms = export.get("repair_lane_feature_atoms")
    atoms = (
        tuple(_identifier_atom(value) for value in raw_atoms)
        if isinstance(raw_atoms, Sequence)
        and not isinstance(raw_atoms, (str, bytes))
        else ()
    )
    matched = [
        lane
        for lane in contract.repair_lanes
        if any(
            _identifier_atom(lane.lane_id) in atom
            or _identifier_atom(lane.action) in atom
            for atom in atoms
        )
    ]
    lanes = matched or list(contract.repair_lanes[:1])
    return [
        {
            "action": lane.action,
            "allowed_paths": list(lane.allowed_paths),
            "lane_id": lane.lane_id,
            "target_component": lane.target_component,
            "validation_commands": list(lane.validation_commands),
        }
        for lane in lanes[:3]
    ]


def _guidance_confidence(
    features: Sequence[Mapping[str, Any]],
    family_weight: float,
    family_evidence: Mapping[str, Any],
) -> float:
    weighted_support = sum(
        min(1.0, _finite_nonnegative(item.get("weight")))
        * min(1.0, _finite_nonnegative(item.get("support_ratio", 1.0)))
        for item in features
    ) / max(1, len(features))
    evidence_factor = 1.0 if family_evidence.get("guardrails_passed") else 0.0
    confidence = (
        0.50 * min(1.0, max(0.0, float(family_weight)))
        + 0.35 * weighted_support
        + 0.15 * evidence_factor
    )
    return round(min(1.0, max(0.0, confidence)), 12)


def _rollback_metadata(
    *,
    promotion_id: str,
    previous_promotion_id: str,
    source_export_id: str,
    canary_evidence_id: str,
    contract_ids: Sequence[str],
) -> dict[str, Any]:
    descriptor = {
        "canary_evidence_id": canary_evidence_id,
        "contract_ids": sorted(set(contract_ids)),
        "previous_promotion_id": str(previous_promotion_id or ""),
        "promotion_id": promotion_id,
        "source_export_id": source_export_id,
    }
    return {
        "activation_key": promotion_id,
        "canary_evidence_id": canary_evidence_id,
        "disable_action": "remove_promoted_guidance_records",
        "previous_promotion_id": str(previous_promotion_id or ""),
        "restore_mode": "canary_only",
        "rollback_id": "lir-guidance-rollback-" + _stable_hash(descriptor)[:24],
        "schema_version": LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION,
        "source_export_id": source_export_id,
    }


def _learned_export_binding(export: Mapping[str, Any]) -> dict[str, Any]:
    payload = _canonical_export_payload(export)
    export_id = str(export.get("export_id") or "")
    artifact_path = str(
        export.get("artifact_path")
        or export.get("export_path")
        or export.get("path")
        or ""
    ).strip()
    stable_features = export.get("stable_features")
    feature_count = (
        len(stable_features)
        if isinstance(stable_features, Sequence)
        and not isinstance(stable_features, (str, bytes, bytearray))
        else int(_finite_nonnegative(export.get("feature_count")))
    )
    return {
        "artifact_path": artifact_path,
        "export_id": export_id,
        "feature_count": feature_count,
        "model_state_id": str(export.get("model_state_id") or ""),
        "sample_count": int(_finite_nonnegative(export.get("sample_count"))),
        "sample_memory_included": bool(export.get("sample_memory_included")),
        "schema_version": str(export.get("schema_version") or ""),
        "sha256": _stable_hash(payload),
    }


def _canonical_export_payload(export: Mapping[str, Any]) -> dict[str, Any]:
    payload = _canonical_json_value(export)
    if isinstance(payload, dict):
        for key in (
            "stable_features",
            "contract_feature_atoms",
            "repair_lane_feature_atoms",
            "proof_receipts",
            "reconstruction_receipts",
            "hammer_receipts",
            "trusted_proof_receipts",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                payload[key] = sorted(
                    value,
                    key=lambda item: json.dumps(
                        item,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ),
                )
    return payload if isinstance(payload, dict) else {}


def _proof_receipts(
    export: Mapping[str, Any],
    explicit: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    raw: Any = explicit
    if raw is None:
        for key in (
            "proof_receipts",
            "reconstruction_receipts",
            "hammer_receipts",
            "trusted_proof_receipts",
        ):
            value = export.get(key)
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                raw = value
                break
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    receipts: list[dict[str, Any]] = []
    for index, receipt in enumerate(raw):
        item = _as_mapping(receipt)
        receipt_id = str(
            item.get("receipt_id")
            or item.get("id")
            or item.get("proof_id")
            or item.get("reconstruction_receipt_id")
            or ""
        ).strip()
        canonical = _canonical_json_value(item)
        if not receipt_id:
            receipt_id = "lir-proof-receipt-" + _stable_hash(
                {"index": index, "receipt": canonical}
            )[:24]
        receipts.append(
            {
                **canonical,
                "receipt_id": receipt_id,
                "trusted": item.get("trusted") is not False,
            }
        )
    deduped = {str(item["receipt_id"]): item for item in receipts}
    return [deduped[key] for key in sorted(deduped)]


def _source_copy_check_report(
    export: Mapping[str, Any],
    *,
    stable_features: Sequence[Mapping[str, Any]],
    unsafe_feature_count: int,
    canary: LegalIRFixedCanaryEvidence,
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    checked_paths = [
        path
        for path in (
            str(export.get("artifact_path") or export.get("export_path") or ""),
            str(export.get("source_copy_audit_path") or ""),
        )
        if path
    ]
    report = {
        "checked_paths": checked_paths,
        "forbidden_feature_marker_count": int(unsafe_feature_count),
        "guardrails_passed": (
            int(unsafe_feature_count) == 0
            and not bool(export.get("sample_memory_included"))
            and not canary.source_copy_regressions
        ),
        "sample_memory_included": bool(export.get("sample_memory_included")),
        "source_copy_policy": "hash_only",
        "source_copy_regressions": list(canary.source_copy_regressions),
        "stable_feature_count": len(stable_features),
        "unsafe_feature_count": int(unsafe_feature_count),
    }
    if overrides:
        report.update(_canonical_json_value(overrides))
    return report


def _causal_evidence_report(
    *,
    canary: LegalIRFixedCanaryEvidence,
    family_weights: Mapping[str, float],
    compiler_commit: str,
    proof_receipts: Sequence[Mapping[str, Any]],
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    deltas = {
        family: dict(values.get("deltas", {}))
        for family, values in canary.family_metrics.items()
        if isinstance(values, Mapping)
    }
    report = {
        "compiler_commit_bound": bool(compiler_commit),
        "fixed_canary_evidence_id": canary.evidence_id,
        "family_metric_deltas": _canonical_json_value(deltas),
        "learned_path_responsive": bool(deltas),
        "metric_lineage_complete": bool(deltas) and canary.fixed_sample_set,
        "proof_receipt_count": len(proof_receipts),
        "view_family_weights": {
            str(key): round(float(value), 12)
            for key, value in sorted(family_weights.items())
        },
    }
    if overrides:
        report.update(_canonical_json_value(overrides))
    return report


def _activation_state_report(
    *,
    promoted: bool,
    promotion_id: str,
    block_reasons: Sequence[str],
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    state = {
        "activation_allowed": promoted,
        "active": promoted,
        "active_promotion_id": promotion_id if promoted else "",
        "block_reasons": list(block_reasons),
        "state": "activated" if promoted else "blocked",
    }
    if overrides:
        state.update(_canonical_json_value(overrides))
    return state


def _family_metric_mapping(payload: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    nested: Any = payload.get("view_family_metrics")
    if not isinstance(nested, Mapping):
        nested = payload.get("legal_ir_view_family_metrics")
    if not isinstance(nested, Mapping):
        nested = payload
    result: dict[str, dict[str, float]] = {}
    for raw_family, raw_metrics in nested.items():
        if not isinstance(raw_metrics, Mapping):
            continue
        family = legal_ir_view_family_name(str(raw_family))
        if (
            family not in LEGAL_IR_VIEW_FAMILIES
            and str(raw_family) in LEGAL_IR_VIEW_FAMILIES
        ):
            family = str(raw_family)
        if family not in LEGAL_IR_VIEW_FAMILIES:
            continue
        metrics: dict[str, float] = {}
        aliases = {
            "source_copy_loss": "source_copy_penalty",
            "source_copy_reward_hack_penalty": "source_copy_penalty",
            "symbolic_validity": "symbolic_validity_success_rate",
        }
        for raw_name, raw_value in raw_metrics.items():
            name = aliases.get(str(raw_name), str(raw_name))
            if name not in LEGAL_IR_VIEW_FAMILY_METRIC_NAMES:
                continue
            value = _finite_float(raw_value)
            if value is not None:
                metrics[name] = value
        result[family] = metrics
    return result


def _flatten_ablation_metrics(payload: Mapping[str, Any]) -> dict[str, float]:
    """Return deterministic mean metrics from flat or per-family evidence."""

    candidates: list[Mapping[str, Any]] = []
    for key in (
        "view_family_metrics",
        "legal_ir_view_family_metrics",
        "family_metrics",
        "metrics",
    ):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            if all(isinstance(value, Mapping) for value in nested.values()):
                candidates.extend(
                    value for value in nested.values() if isinstance(value, Mapping)
                )
            else:
                candidates.append(nested)
            break
    if not candidates:
        candidates = [payload]
    values: dict[str, list[float]] = {}
    aliases = {
        "source_copy_loss": "source_copy_penalty",
        "symbolic_validity": "symbolic_validity_success_rate",
    }
    for metrics in candidates:
        for raw_name, raw_value in metrics.items():
            name = aliases.get(str(raw_name), str(raw_name))
            number = _finite_float(raw_value)
            if number is not None:
                values.setdefault(name, []).append(number)
    return {
        name: sum(items) / len(items)
        for name, items in sorted(values.items())
        if items
    }


def _resolve_fixed_canary_id(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    explicit: str,
) -> tuple[str, bool]:
    before_id = str(
        baseline.get("fixed_canary_id") or baseline.get("canary_id") or ""
    )
    after_id = str(
        candidate.get("fixed_canary_id") or candidate.get("canary_id") or ""
    )
    canary_id = str(explicit or before_id or after_id)
    identity_matches = bool(canary_id) and all(
        not value or value == canary_id for value in (before_id, after_id)
    )
    before_samples = baseline.get("canary_sample_ids", baseline.get("sample_ids"))
    after_samples = candidate.get("canary_sample_ids", candidate.get("sample_ids"))
    if before_samples is not None or after_samples is not None:
        identity_matches = identity_matches and _canonical_json_value(
            before_samples
        ) == _canonical_json_value(after_samples)
    return canary_id, identity_matches


def _contract_family(contract: LegalIRViewContract) -> str:
    family = legal_ir_view_family_name(contract.target_component)
    if family == "other" and contract.view.value == "knowledge_graphs":
        return "kg"
    return family


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): child for key, child in value.items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        converted = value.to_dict()
        return _as_mapping(converted)
    return {}


def _identifier_atom(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _finite_nonnegative(value: Any) -> float:
    numeric = _finite_float(value)
    return max(0.0, numeric) if numeric is not None else 0.0


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_json_value(child) for child in value]
    if isinstance(value, float):
        return round(value, 12) if math.isfinite(value) else 0.0
    return value


def _stable_hash(value: Any) -> str:
    payload = _canonical_json_value(value)
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "LEGAL_IR_LEARNED_GUIDANCE_CANARY_SCHEMA_VERSION",
    "LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION",
    "LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION",
    "LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION",
    "LegalIRFixedCanaryEvidence",
    "LegalIRLearnedGuidancePromotion",
    "LegalIRLearnedGuidanceRecord",
    "build_legal_ir_learned_guidance_records",
    "evaluate_fixed_canary_evidence",
    "legal_ir_learned_guidance_promotion",
    "promote_learned_autoencoder_guidance",
    "promote_legal_ir_learned_guidance",
]
