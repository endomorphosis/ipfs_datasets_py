"""Distil learned LegalIR structure into bounded deterministic rule candidates.

The adaptive model is an evidence producer, not a compiler.  This module is a
second, deliberately narrow trust boundary after learned-guidance promotion.
It accepts only source-free, recurrent categorical patterns and projects them
onto canonical :mod:`legal_ir_view_contracts` repair lanes.  A rule candidate
is therefore declarative, content addressed, path bounded, reversible, and
accompanied by counterfactual and mutation evidence.

Rule candidates may be useful for offline review without authorising a code
change.  Codex TODOs have the stronger gate: a family-specific attribution on
an isolated held-out set must predict a positive compiler-facing improvement.
Aggregate training benefit, sample memory, and source-copy features can never
cross that gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ....optimizers.logic_theorem_optimizer.modal_autoencoder import (
    LEGAL_IR_VIEW_FAMILIES,
    legal_ir_view_family_name,
)
from .legal_ir_view_contracts import (
    LegalIRRepairLane,
    LegalIRViewContract,
    legal_ir_view_contracts,
)
from .legal_ir_premise_security import (
    LegalIRArtifactUse,
    legal_ir_artifact_allowed_for_use,
    scan_legal_ir_artifact,
)


LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION: Final = (
    "legal-ir-deterministic-rule-candidate-v1"
)
LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION: Final = "legal-ir-rule-distillation-v1"
LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION: Final = (
    "legal-ir-rule-distillation-codex-todo-v1"
)
LEGAL_IR_RULE_DISTILLATION_ROLLBACK_SCHEMA_VERSION: Final = (
    "legal-ir-rule-distillation-rollback-v1"
)
LEGAL_IR_FAMILY_ATTRIBUTION_SCHEMA_VERSION: Final = (
    "legal-ir-family-heldout-attribution-v1"
)

HARD_MAX_RULE_CANDIDATES: Final = 64
HARD_MAX_PATTERNS_PER_CANDIDATE: Final = 32
HARD_MAX_EVIDENCE_ITEMS: Final = 16
HARD_MAX_OWNED_PATHS: Final = 16
HARD_MAX_SERIALIZED_STRING_BYTES: Final = 1024

_FORBIDDEN_FEATURE_MARKERS = (
    "decoded-embedding",
    "decoded_embedding",
    "raw-source",
    "raw_source",
    "sample-id",
    "sample-memory",
    "sample_id",
    "sample_memory",
    "source-copy",
    "source-span",
    "source-text",
    "source_copy",
    "source_span",
    "source_text",
    "token:",
    "token2:",
    "token3:",
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "decoded_embedding",
        "decoded_embeddings",
        "family_logits",
        "raw_source",
        "raw_source_text",
        "sample_id",
        "sample_ids",
        "sample_memory",
        "source_copy_feature",
        "source_span",
        "source_spans",
        "source_text",
    }
)
_SAMPLE_MEMORY_FLAGS = frozenset(
    {"sample_memory_included", "sample_memory_used", "use_sample_memory"}
)
_COMPILER_METRIC_MARKERS = (
    "compiler",
    "ir_cosine",
    "ir_cross_entropy",
    "reconstruction",
    "symbolic_validity",
)
_LOWER_IS_BETTER_MARKERS = (
    "cross_entropy",
    "loss",
    "penalty",
    "error",
    "failure",
)
_SAFE_IDENTIFIER = re.compile(r"[^a-z0-9_.:/+-]+")


class _SerializableMapping(Mapping[str, Any]):
    """Provide attribute and mapping access for pipeline compatibility."""

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - protocol method
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


class LegalIRPatternKind(str, Enum):
    """Source-free learned structures that may explain a deterministic rule."""

    FAMILY = "family"
    SEMANTIC_SLOT = "semantic_slot"
    PROOF_HEAD = "proof_head"
    LEGAL_IR_VIEW = "legal_ir_view"


class LegalIRRuleTarget(str, Enum):
    """Only deterministic compiler and decompiler targets are supported."""

    COMPILER = "compiler"
    DECOMPILER = "decompiler"


@dataclass(frozen=True, slots=True)
class LegalIRRuleDistillationConfig:
    """Hard-bounded policy for a single deterministic distillation batch."""

    min_support: int = 2
    min_confidence: float = 0.65
    min_heldout_compiler_improvement: float = 1.0e-9
    max_candidates: int = 16
    max_patterns_per_candidate: int = 8
    max_counterfactuals_per_candidate: int = 8
    max_mutations_per_candidate: int = 8
    max_owned_paths_per_candidate: int = 8
    require_passing_counterfactuals: bool = True
    require_passing_mutations: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_support", max(1, int(self.min_support)))
        for name in ("min_confidence", "min_heldout_compiler_improvement"):
            value = _finite_float(getattr(self, name))
            if value is None or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, float(value))
        bounds = {
            "max_candidates": HARD_MAX_RULE_CANDIDATES,
            "max_patterns_per_candidate": HARD_MAX_PATTERNS_PER_CANDIDATE,
            "max_counterfactuals_per_candidate": HARD_MAX_EVIDENCE_ITEMS,
            "max_mutations_per_candidate": HARD_MAX_EVIDENCE_ITEMS,
            "max_owned_paths_per_candidate": HARD_MAX_OWNED_PATHS,
        }
        for name, hard_limit in bounds.items():
            object.__setattr__(
                self, name, max(1, min(int(getattr(self, name)), hard_limit))
            )

    @classmethod
    def from_value(
        cls, value: "LegalIRRuleDistillationConfig | Mapping[str, Any] | None"
    ) -> "LegalIRRuleDistillationConfig":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("distillation config must be a mapping or config object")
        names = cls.__dataclass_fields__
        return cls(**{name: value[name] for name in names if name in value})


@dataclass(frozen=True, slots=True)
class LegalIRCounterfactualEvidence(_SerializableMapping):
    """A source-free minimal intervention used to challenge a learned pattern."""

    counterfactual_id: str
    family: str
    intervention: str
    expected_outcome: str
    observed_outcome: str
    passed: bool
    held_out: bool = True
    evidence_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterfactual_id": self.counterfactual_id,
            "evidence_id": self.evidence_id,
            "expected_outcome": self.expected_outcome,
            "family": self.family,
            "held_out": self.held_out,
            "intervention": self.intervention,
            "observed_outcome": self.observed_outcome,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class LegalIRMutationEvidence(_SerializableMapping):
    """Evidence that a semantic mutation is detected by the proposed rule."""

    mutation_id: str
    family: str
    mutation: str
    expected_detection: str
    observed_detection: str
    detected: bool
    verified: bool = True
    evidence_id: str = ""

    @property
    def passed(self) -> bool:
        return self.detected and self.verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "evidence_id": self.evidence_id,
            "expected_detection": self.expected_detection,
            "family": self.family,
            "mutation": self.mutation,
            "mutation_id": self.mutation_id,
            "observed_detection": self.observed_detection,
            "passed": self.passed,
            "verified": self.verified,
        }


@dataclass(frozen=True, slots=True)
class LegalIRFamilyAttribution(_SerializableMapping):
    """Per-family held-out estimate used solely for the Codex TODO gate."""

    attribution_id: str
    family: str
    compiler_metric: str
    predicted_improvement: float
    heldout_sample_count: int
    heldout_evaluated: bool
    per_family: bool
    fixed_sample_set: bool = True
    holdout_isolated: bool = True
    source_copy_guard_passed: bool = True
    confidence: float = 1.0
    holdout_id: str = ""
    schema_version: str = LEGAL_IR_FAMILY_ATTRIBUTION_SCHEMA_VERSION

    def predicts_heldout_compiler_improvement(self, minimum: float = 0.0) -> bool:
        metric = self.compiler_metric.lower()
        return (
            self.per_family
            and self.heldout_evaluated
            and self.fixed_sample_set
            and self.holdout_isolated
            and self.source_copy_guard_passed
            and self.heldout_sample_count > 0
            and any(marker in metric for marker in _COMPILER_METRIC_MARKERS)
            and self.predicted_improvement > 0.0
            and self.predicted_improvement >= max(0.0, float(minimum))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribution_id": self.attribution_id,
            "compiler_metric": self.compiler_metric,
            "confidence": round(self.confidence, 12),
            "family": self.family,
            "fixed_sample_set": self.fixed_sample_set,
            "heldout_evaluated": self.heldout_evaluated,
            "heldout_sample_count": self.heldout_sample_count,
            "holdout_id": self.holdout_id,
            "holdout_isolated": self.holdout_isolated,
            "per_family": self.per_family,
            "predicted_improvement": round(self.predicted_improvement, 12),
            "schema_version": self.schema_version,
            "source_copy_guard_passed": self.source_copy_guard_passed,
        }


@dataclass(frozen=True, slots=True)
class LegalIRStablePattern(_SerializableMapping):
    """Normalized, source-free learned pattern retained in a candidate."""

    pattern_id: str
    pattern_kind: str
    family: str
    feature: str
    support_count: int
    support_ratio: float
    confidence: float
    contract_id: str
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.confidence, 12),
            "contract_id": self.contract_id,
            "family": self.family,
            "feature": self.feature,
            "pattern_id": self.pattern_id,
            "pattern_kind": self.pattern_kind,
            "source_id": self.source_id,
            "stable": True,
            "support_count": self.support_count,
            "support_ratio": round(self.support_ratio, 12),
        }


@dataclass(frozen=True, slots=True)
class LegalIRRuleCandidate(_SerializableMapping):
    """One reviewable declarative compiler/decompiler rule proposal."""

    candidate_id: str
    distillation_id: str
    family: str
    contract_id: str
    target_kind: str
    target_component: str
    action: str
    lane_id: str
    deterministic_rule: Mapping[str, Any]
    patterns: tuple[LegalIRStablePattern, ...]
    support_count: int
    support_ratio: float
    confidence: float
    counterfactuals: tuple[LegalIRCounterfactualEvidence, ...]
    mutation_evidence: tuple[LegalIRMutationEvidence, ...]
    owned_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    attribution: LegalIRFamilyAttribution | None
    rollback_metadata: Mapping[str, Any]
    schema_version: str = LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION

    @property
    def codex_todo_eligible(self) -> bool:
        return self.attribution is not None and bool(
            self.rollback_metadata.get("codex_todo_eligible")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed_paths": list(self.owned_paths),
            "attribution": self.attribution.to_dict() if self.attribution else None,
            "candidate_id": self.candidate_id,
            "codex_todo_eligible": self.codex_todo_eligible,
            "confidence": round(self.confidence, 12),
            "contract_id": self.contract_id,
            "counterfactuals": [item.to_dict() for item in self.counterfactuals],
            "deterministic_rule": _json_value(self.deterministic_rule),
            "distillation_id": self.distillation_id,
            "family": self.family,
            "guidance_kind": self.target_kind,
            "lane_id": self.lane_id,
            "mutation_evidence": [item.to_dict() for item in self.mutation_evidence],
            "owned_paths": list(self.owned_paths),
            "patterns": [item.to_dict() for item in self.patterns],
            "rollback_metadata": _json_value(self.rollback_metadata),
            "schema_version": self.schema_version,
            "support": {
                "count": self.support_count,
                "pattern_count": len(self.patterns),
                "ratio": round(self.support_ratio, 12),
            },
            "support_count": self.support_count,
            "support_ratio": round(self.support_ratio, 12),
            "target_component": self.target_component,
            "target_kind": self.target_kind,
            "validation_commands": list(self.validation_commands),
        }


@dataclass(frozen=True, slots=True)
class LegalIRRuleCodexTodo(_SerializableMapping):
    """A path-bounded implementation packet backed by held-out attribution."""

    todo_id: str
    candidate_id: str
    objective: str
    action: str
    family: str
    target_component: str
    owned_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    evidence: Mapping[str, Any]
    rollback_metadata: Mapping[str, Any]
    schema_version: str = LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        metadata = {
            "allowed_paths": list(self.owned_paths),
            "candidate_id": self.candidate_id,
            "evidence": _json_value(self.evidence),
            "family": self.family,
            "owned_paths": list(self.owned_paths),
            "rollback_metadata": _json_value(self.rollback_metadata),
            "source": "legal_ir_rule_distillation",
            "target_component": self.target_component,
            "validation_commands": list(self.validation_commands),
        }
        return {
            "action": self.action,
            "allowed_paths": list(self.owned_paths),
            "candidate_id": self.candidate_id,
            "evidence": _json_value(self.evidence),
            "family": self.family,
            "metadata": metadata,
            "objective": self.objective,
            "owned_paths": list(self.owned_paths),
            "rollback_metadata": _json_value(self.rollback_metadata),
            "schema_version": self.schema_version,
            "target_component": self.target_component,
            "todo_id": self.todo_id,
            "validation_commands": list(self.validation_commands),
        }


@dataclass(frozen=True, slots=True)
class LegalIRRuleDistillationResult(_SerializableMapping):
    """Auditable output of one distillation attempt, including all rejections."""

    distillation_id: str
    source_id: str
    candidates: tuple[LegalIRRuleCandidate, ...]
    codex_todos: tuple[LegalIRRuleCodexTodo, ...]
    rejected_patterns: tuple[Mapping[str, Any], ...]
    block_reasons: tuple[str, ...]
    candidate_pattern_count: int
    accepted_pattern_count: int
    rollback_metadata: Mapping[str, Any]
    config: LegalIRRuleDistillationConfig
    schema_version: str = LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION

    @property
    def status(self) -> str:
        return "distilled" if self.candidates else "blocked"

    @property
    def bounded(self) -> bool:
        return (
            len(self.candidates) <= self.config.max_candidates
            and all(
                len(item.patterns) <= self.config.max_patterns_per_candidate
                and len(item.counterfactuals)
                <= self.config.max_counterfactuals_per_candidate
                and len(item.mutation_evidence)
                <= self.config.max_mutations_per_candidate
                and len(item.owned_paths)
                <= self.config.max_owned_paths_per_candidate
                for item in self.candidates
            )
        )

    @property
    def todos(self) -> tuple[LegalIRRuleCodexTodo, ...]:
        return self.codex_todos

    @property
    def rule_candidates(self) -> tuple[LegalIRRuleCandidate, ...]:
        return self.candidates

    def to_dict(self) -> dict[str, Any]:
        candidates = [item.to_dict() for item in self.candidates]
        todos = [item.to_dict() for item in self.codex_todos]
        return {
            "accepted_pattern_count": self.accepted_pattern_count,
            "block_reasons": list(self.block_reasons),
            "bounded": self.bounded,
            "candidate_count": len(candidates),
            "candidate_pattern_count": self.candidate_pattern_count,
            "candidates": candidates,
            "codex_todo_count": len(todos),
            "codex_todos": todos,
            "config": _config_dict(self.config),
            "distillation_id": self.distillation_id,
            "rejected_pattern_count": len(self.rejected_patterns),
            "rejected_patterns": _json_value(self.rejected_patterns),
            "rollback_metadata": _json_value(self.rollback_metadata),
            "rule_candidates": candidates,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "status": self.status,
            "todos": todos,
        }


# A concise name used by callers that treat the result as an immutable receipt.
LegalIRRuleDistillation = LegalIRRuleDistillationResult
LegalIRCodexTodo = LegalIRRuleCodexTodo


class LegalIRRuleDistiller:
    """Reusable object API around :func:`distill_legal_ir_rule_candidates`."""

    def __init__(
        self,
        config: LegalIRRuleDistillationConfig | Mapping[str, Any] | None = None,
    ) -> None:
        self.config = LegalIRRuleDistillationConfig.from_value(config)

    def distill(self, learned_patterns: Any, **kwargs: Any) -> LegalIRRuleDistillationResult:
        kwargs.setdefault("config", self.config)
        return distill_legal_ir_rule_candidates(learned_patterns, **kwargs)


def distill_legal_ir_rule_candidates(
    learned_patterns: Any = None,
    *,
    family_attribution: Any = None,
    family_attributions: Any = None,
    per_family_attribution: Any = None,
    attribution_evidence: Any = None,
    stable_patterns: Any = None,
    counterfactuals: Any = None,
    counterfactual_evidence: Any = None,
    mutation_evidence: Any = None,
    mutations: Any = None,
    previous_distillation_id: str = "",
    config: LegalIRRuleDistillationConfig | Mapping[str, Any] | None = None,
    emit_codex_todos: bool = True,
) -> LegalIRRuleDistillationResult:
    """Convert stable representations into deterministic candidate rules.

    Inputs may be raw pattern mappings, a stable feature export, or a promoted
    learned-guidance receipt.  The function never mutates them and output IDs
    are invariant to input ordering.
    """

    if learned_patterns is None:
        learned_patterns = stable_patterns
    policy = LegalIRRuleDistillationConfig.from_value(config)
    container = _as_mapping(learned_patterns)
    source_id = _source_id(container, learned_patterns)
    premise_security = scan_legal_ir_artifact(
        learned_patterns,
        artifact_id=source_id,
        artifact_role="rule_distillation",
    )
    if family_attribution is None:
        family_attribution = (
            family_attributions
            or per_family_attribution
            or attribution_evidence
            or container.get("family_attribution")
            or container.get("family_attributions")
            or container.get("per_family_attribution")
        )
    if counterfactuals is None:
        counterfactuals = counterfactual_evidence
    if counterfactuals is None:
        counterfactuals = container.get("counterfactuals") or container.get(
            "counterfactual_evidence"
        )
    if mutation_evidence is None:
        mutation_evidence = mutations
    if mutation_evidence is None:
        mutation_evidence = container.get("mutation_evidence") or container.get(
            "mutations"
        )

    raw_rows = _pattern_rows(learned_patterns, source_id=source_id)
    unsafe_container = bool(container and _unsafe_payload(container))
    rejected: list[dict[str, Any]] = []
    accepted: list[tuple[LegalIRStablePattern, Mapping[str, Any], LegalIRViewContract, LegalIRRepairLane]] = []
    for index, raw in enumerate(raw_rows):
        pattern_id = str(raw.get("pattern_id") or raw.get("feature_id") or f"pattern-{index}")
        if unsafe_container or premise_security.rejected:
            rejected.append(
                {
                    "pattern_id": pattern_id,
                    "reason": (
                        "premise_security_rejected"
                        if premise_security.rejected
                        else "sample_memory_or_source_copy_feature"
                    ),
                }
            )
            continue
        normalized, contract, lane, reason = _normalize_pattern(
            raw,
            pattern_id=pattern_id,
            source_id=source_id,
            config=policy,
        )
        if reason or normalized is None or contract is None or lane is None:
            rejected.append(
                {
                    "pattern_id": pattern_id,
                    "reason": reason or "invalid_pattern",
                }
            )
            continue
        accepted.append((normalized, raw, contract, lane))

    groups: dict[
        tuple[str, str, str, str],
        list[tuple[LegalIRStablePattern, Mapping[str, Any], LegalIRViewContract, LegalIRRepairLane]],
    ] = {}
    deduped_accepted: dict[
        tuple[str, str, str, str],
        tuple[LegalIRStablePattern, Mapping[str, Any], LegalIRViewContract, LegalIRRepairLane],
    ] = {}
    for item in accepted:
        pattern, _raw, contract, lane = item
        dedupe_key = (
            contract.contract_id,
            lane.lane_id,
            pattern.pattern_kind,
            pattern.feature,
        )
        current = deduped_accepted.get(dedupe_key)
        if current is None or (
            pattern.confidence,
            pattern.support_count,
            pattern.pattern_id,
        ) > (
            current[0].confidence,
            current[0].support_count,
            current[0].pattern_id,
        ):
            deduped_accepted[dedupe_key] = item
    for item in deduped_accepted.values():
        pattern, _raw, contract, lane = item
        target_kind = (
            LegalIRRuleTarget.DECOMPILER.value
            if pattern.family == "decompiler"
            else LegalIRRuleTarget.COMPILER.value
        )
        groups.setdefault(
            (pattern.family, contract.contract_id, target_kind, lane.lane_id), []
        ).append(item)

    candidate_seeds: list[dict[str, Any]] = []
    for group_key, items in sorted(groups.items()):
        family, contract_id, target_kind, lane_id = group_key
        items = sorted(items, key=lambda item: item[0].pattern_id)
        contract = items[0][2]
        lane = items[0][3]
        patterns = tuple(item[0] for item in items[: policy.max_patterns_per_candidate])
        support_count = min(item.support_count for item in patterns)
        support_ratio = min(item.support_ratio for item in patterns)
        confidence = round(
            sum(item.confidence * max(1, item.support_count) for item in patterns)
            / sum(max(1, item.support_count) for item in patterns),
            12,
        )
        if support_count < policy.min_support:
            rejected.extend(
                _group_rejections(patterns, "insufficient_candidate_support")
            )
            continue
        if confidence < policy.min_confidence:
            rejected.extend(_group_rejections(patterns, "candidate_confidence_below_threshold"))
            continue

        nested_counterfactuals = [
            value
            for _pattern, raw, _contract, _lane in items
            for value in _evidence_values(
                raw.get("counterfactuals") or raw.get("counterfactual_evidence"),
                family=family,
                pattern_id=_pattern.pattern_id,
            )
        ]
        nested_counterfactuals.extend(
            _evidence_values(counterfactuals, family=family, pattern_id="")
        )
        counterfactual_records = _counterfactual_records(
            nested_counterfactuals,
            family=family,
            limit=policy.max_counterfactuals_per_candidate,
        )
        if not counterfactual_records:
            rejected.extend(_group_rejections(patterns, "counterfactual_evidence_missing"))
            continue
        if policy.require_passing_counterfactuals and not all(
            item.passed and item.held_out for item in counterfactual_records
        ):
            rejected.extend(_group_rejections(patterns, "counterfactual_evidence_failed"))
            continue

        nested_mutations = [
            value
            for _pattern, raw, _contract, _lane in items
            for value in _evidence_values(
                raw.get("mutation_evidence") or raw.get("mutations"),
                family=family,
                pattern_id=_pattern.pattern_id,
            )
        ]
        nested_mutations.extend(
            _evidence_values(mutation_evidence, family=family, pattern_id="")
        )
        mutation_records = _mutation_records(
            nested_mutations,
            family=family,
            limit=policy.max_mutations_per_candidate,
        )
        if not mutation_records:
            rejected.extend(_group_rejections(patterns, "mutation_evidence_missing"))
            continue
        if policy.require_passing_mutations and not all(
            item.passed for item in mutation_records
        ):
            rejected.extend(_group_rejections(patterns, "mutation_evidence_failed"))
            continue

        requested_paths = {
            path
            for _pattern, raw, _contract, _lane in items
            for path in _string_values(raw.get("owned_paths") or raw.get("allowed_paths"))
        }
        canonical_paths = tuple(dict.fromkeys(lane.allowed_paths))
        owned_paths = tuple(
            path for path in canonical_paths if not requested_paths or path in requested_paths
        )[: policy.max_owned_paths_per_candidate]
        if not owned_paths:
            rejected.extend(_group_rejections(patterns, "no_canonical_owned_paths"))
            continue

        nested_attribution = next(
            (
                raw.get("family_attribution") or raw.get("attribution")
                for _pattern, raw, _contract, _lane in items
                if raw.get("family_attribution") or raw.get("attribution")
            ),
            None,
        )
        attribution = _family_attribution(
            family_attribution if family_attribution is not None else nested_attribution,
            family=family,
        )
        attribution_passed = bool(
            attribution
            and attribution.predicts_heldout_compiler_improvement(
                policy.min_heldout_compiler_improvement
            )
        )
        rule = _deterministic_rule(
            family=family,
            contract=contract,
            lane=lane,
            patterns=patterns,
            target_kind=target_kind,
        )
        descriptor = {
            "contract_id": contract_id,
            "counterfactuals": [item.to_dict() for item in counterfactual_records],
            "family": family,
            "lane_id": lane_id,
            "mutation_evidence": [item.to_dict() for item in mutation_records],
            "patterns": [item.to_dict() for item in patterns],
            "rule": rule,
            "source_id": source_id,
            "target_kind": target_kind,
        }
        candidate_seeds.append(
            {
                "attribution": attribution,
                "attribution_passed": attribution_passed,
                "confidence": confidence,
                "contract": contract,
                "counterfactuals": tuple(counterfactual_records),
                "descriptor": descriptor,
                "lane": lane,
                "mutation_evidence": tuple(mutation_records),
                "owned_paths": owned_paths,
                "patterns": patterns,
                "rule": rule,
                "support_count": support_count,
                "support_ratio": support_ratio,
                "target_kind": target_kind,
            }
        )

    candidate_seeds.sort(
        key=lambda item: (
            -float(item["confidence"]),
            -int(item["support_count"]),
            _stable_hash(item["descriptor"]),
        )
    )
    overflow = candidate_seeds[policy.max_candidates :]
    for item in overflow:
        rejected.extend(
            _group_rejections(item["patterns"], "candidate_batch_limit_exceeded")
        )
    candidate_seeds = candidate_seeds[: policy.max_candidates]

    distillation_descriptor = {
        "candidate_descriptors": [item["descriptor"] for item in candidate_seeds],
        "config": _config_dict(policy),
        "source_id": source_id,
    }
    distillation_id = "lir-rule-distillation-" + _stable_hash(
        distillation_descriptor
    )[:24]
    candidates: list[LegalIRRuleCandidate] = []
    todos: list[LegalIRRuleCodexTodo] = []
    for seed in candidate_seeds:
        candidate_id = "lir-rule-candidate-" + _stable_hash(seed["descriptor"])[:24]
        rollback = _rollback_metadata(
            candidate_id=candidate_id,
            distillation_id=distillation_id,
            previous_distillation_id=previous_distillation_id,
            source_id=source_id,
            owned_paths=seed["owned_paths"],
            codex_todo_eligible=bool(seed["attribution_passed"]),
        )
        contract = seed["contract"]
        lane = seed["lane"]
        candidate = LegalIRRuleCandidate(
            candidate_id=candidate_id,
            distillation_id=distillation_id,
            family=seed["patterns"][0].family,
            contract_id=contract.contract_id,
            target_kind=seed["target_kind"],
            target_component=lane.target_component or contract.target_component,
            action=lane.action,
            lane_id=lane.lane_id,
            deterministic_rule=seed["rule"],
            patterns=seed["patterns"],
            support_count=seed["support_count"],
            support_ratio=seed["support_ratio"],
            confidence=seed["confidence"],
            counterfactuals=seed["counterfactuals"],
            mutation_evidence=seed["mutation_evidence"],
            owned_paths=seed["owned_paths"],
            validation_commands=tuple(dict.fromkeys(lane.validation_commands)),
            attribution=seed["attribution"],
            rollback_metadata=rollback,
        )
        candidates.append(candidate)
        if emit_codex_todos and candidate.codex_todo_eligible:
            todos.append(_codex_todo(candidate))

    block_reasons: list[str] = []
    if premise_security.rejected:
        block_reasons.append("premise_security_rejected")
        block_reasons.extend(premise_security.rejection_reasons)
    if not raw_rows:
        block_reasons.append("no_learned_patterns")
    if raw_rows and not candidates:
        block_reasons.append("no_rule_candidates_met_distillation_gates")
    if candidates and emit_codex_todos and not todos:
        block_reasons.append("no_per_family_heldout_compiler_improvement")
    rollback_metadata = {
        "candidate_ids": [item.candidate_id for item in candidates],
        "disable_action": "remove_distilled_rule_candidates_and_todos",
        "distillation_id": distillation_id,
        "previous_distillation_id": str(previous_distillation_id or ""),
        "restore_mode": "candidate_registry_snapshot",
        "premise_security": premise_security.to_dict(),
        "rollback_id": "lir-rule-distillation-rollback-"
        + _stable_hash(
            {
                "candidate_ids": [item.candidate_id for item in candidates],
                "distillation_id": distillation_id,
                "previous_distillation_id": str(previous_distillation_id or ""),
            }
        )[:24],
        "schema_version": LEGAL_IR_RULE_DISTILLATION_ROLLBACK_SCHEMA_VERSION,
        "source_id": source_id,
        "todo_ids": [item.todo_id for item in todos],
    }
    return LegalIRRuleDistillationResult(
        distillation_id=distillation_id,
        source_id=source_id,
        candidates=tuple(candidates),
        codex_todos=tuple(todos),
        rejected_patterns=tuple(_dedupe_rejections(rejected)),
        block_reasons=tuple(block_reasons),
        candidate_pattern_count=len(raw_rows),
        accepted_pattern_count=sum(len(item.patterns) for item in candidates),
        rollback_metadata=rollback_metadata,
        config=policy,
    )


def distill_stable_learned_representations(
    learned_patterns: Any, **kwargs: Any
) -> LegalIRRuleDistillationResult:
    """Compatibility alias with the wording used by the representation track."""

    return distill_legal_ir_rule_candidates(learned_patterns, **kwargs)


def distill_stable_legal_ir_patterns(
    learned_patterns: Any, **kwargs: Any
) -> LegalIRRuleDistillationResult:
    """Alias for callers that name the normalized pattern artifact directly."""

    return distill_legal_ir_rule_candidates(learned_patterns, **kwargs)


def distill_learned_legal_ir_rules(
    learned_patterns: Any, **kwargs: Any
) -> LegalIRRuleDistillationResult:
    """Compatibility alias for integration callers."""

    return distill_legal_ir_rule_candidates(learned_patterns, **kwargs)


def legal_ir_rule_distillation(learned_patterns: Any, **kwargs: Any) -> dict[str, Any]:
    """Return a JSON-ready distillation receipt."""

    return distill_legal_ir_rule_candidates(learned_patterns, **kwargs).to_dict()


def build_legal_ir_rule_candidates(
    learned_patterns: Any, **kwargs: Any
) -> list[LegalIRRuleCandidate]:
    """Return only candidates while retaining the same fail-closed gates."""

    return list(distill_legal_ir_rule_candidates(learned_patterns, **kwargs).candidates)


def project_distilled_rules_to_codex_todos(
    distillation_or_patterns: LegalIRRuleDistillationResult | Any,
    **kwargs: Any,
) -> list[LegalIRRuleCodexTodo]:
    """Return TODOs, evaluating patterns first when a receipt is not supplied."""

    if isinstance(distillation_or_patterns, LegalIRRuleDistillationResult):
        return [
            todo
            for todo in distillation_or_patterns.codex_todos
            if legal_ir_artifact_allowed_for_use(
                todo.to_dict(),
                LegalIRArtifactUse.CODEX_TODO,
            )
        ]
    return list(
        distill_legal_ir_rule_candidates(
            distillation_or_patterns, **kwargs
        ).codex_todos
    )


def _pattern_rows(value: Any, *, source_id: str) -> list[dict[str, Any]]:
    payload = _as_mapping(value)
    if payload:
        records = payload.get("records") or payload.get("guidance_records")
        if records is not None:
            rows: list[dict[str, Any]] = []
            for record_value in _sequence(records):
                record = _as_mapping(record_value)
                defaults = {
                    "allowed_paths": record.get("allowed_paths"),
                    "confidence": record.get("confidence"),
                    "contract_id": record.get("contract_id"),
                    "counterfactuals": record.get("counterfactuals"),
                    "family": record.get("view_family") or record.get("family"),
                    "mutation_evidence": record.get("mutation_evidence"),
                    "owned_paths": record.get("owned_paths"),
                    "source_id": record.get("guidance_id") or source_id,
                    "target_kind": record.get("guidance_kind"),
                }
                lane_records = _sequence(record.get("repair_lane_records"))
                if lane_records:
                    defaults.update(
                        {
                            "allowed_paths": _as_mapping(lane_records[0]).get(
                                "allowed_paths"
                            ),
                            "lane_id": _as_mapping(lane_records[0]).get("lane_id"),
                        }
                    )
                for feature_value in _sequence(record.get("stable_features")):
                    rows.append({**defaults, **_as_mapping(feature_value)})
            return rows
        categorized: list[dict[str, Any]] = []
        category_keys = {
            "family_patterns": LegalIRPatternKind.FAMILY.value,
            "stable_family_patterns": LegalIRPatternKind.FAMILY.value,
            "semantic_slot_patterns": LegalIRPatternKind.SEMANTIC_SLOT.value,
            "stable_semantic_slot_patterns": LegalIRPatternKind.SEMANTIC_SLOT.value,
            "proof_head_patterns": LegalIRPatternKind.PROOF_HEAD.value,
            "stable_proof_head_patterns": LegalIRPatternKind.PROOF_HEAD.value,
            "legal_ir_view_patterns": LegalIRPatternKind.LEGAL_IR_VIEW.value,
            "stable_legal_ir_view_patterns": LegalIRPatternKind.LEGAL_IR_VIEW.value,
        }
        for key, kind in category_keys.items():
            for item_value in _sequence(payload.get(key)):
                item = _as_mapping(item_value)
                if not item and isinstance(item_value, str):
                    item = {"feature": item_value}
                if item:
                    item.setdefault("pattern_kind", kind)
                    item.setdefault("source_id", source_id)
                    if key.startswith("stable_"):
                        item.setdefault("stable", True)
                    for inherited in (
                        "confidence",
                        "contract_id",
                        "family",
                        "support_count",
                        "support_ratio",
                    ):
                        if payload.get(inherited) is not None:
                            item.setdefault(inherited, payload[inherited])
                    categorized.append(item)
        if categorized:
            return categorized
        raw = (
            payload.get("patterns")
            or payload.get("stable_patterns")
            or payload.get("stable_features")
        )
        if raw is not None:
            family_weights = payload.get("view_family_weights")
            families = []
            if isinstance(family_weights, Mapping):
                families = [
                    (str(name), _finite_nonnegative(weight))
                    for name, weight in sorted(family_weights.items())
                    if _finite_nonnegative(weight) > 0.0
                ]
            rows = []
            for item_value in _sequence(raw):
                item = _as_mapping(item_value)
                if not item:
                    continue
                explicit_family = item.get("family") or item.get("view_family")
                expansions = [(str(explicit_family), 1.0)] if explicit_family else families
                expansions = expansions or [("", 1.0)]
                for family, family_weight in expansions:
                    row = dict(item)
                    row.setdefault("family", family)
                    row.setdefault("source_id", source_id)
                    if row.get("confidence") is None and family_weight:
                        weight = min(1.0, _finite_nonnegative(row.get("weight", 1.0)))
                        row["confidence"] = min(1.0, weight * family_weight)
                    rows.append(row)
            return rows
        if payload.get("feature") or payload.get("pattern"):
            return [dict(payload)]
        return []
    return [_as_mapping(item) for item in _sequence(value) if _as_mapping(item)]


def _normalize_pattern(
    raw: Mapping[str, Any],
    *,
    pattern_id: str,
    source_id: str,
    config: LegalIRRuleDistillationConfig,
) -> tuple[
    LegalIRStablePattern | None,
    LegalIRViewContract | None,
    LegalIRRepairLane | None,
    str,
]:
    if _unsafe_payload(raw):
        return None, None, None, "sample_memory_or_source_copy_feature"
    if raw.get("stable") is not True:
        return None, None, None, "unstable_pattern"
    feature = str(
        raw.get("feature") or raw.get("pattern") or raw.get("feature_name") or ""
    ).strip()
    if not feature or len(feature.encode("utf-8")) > HARD_MAX_SERIALIZED_STRING_BYTES:
        return None, None, None, "missing_or_oversized_feature"
    kind = _pattern_kind(raw, feature)
    if kind is None:
        return None, None, None, "unsupported_pattern_kind"
    family = _canonical_family(
        raw.get("family")
        or raw.get("view_family")
        or raw.get("legal_ir_family")
        or _family_from_feature(feature)
    )
    contract = _resolve_contract(raw, family=family, feature=feature)
    if contract is None:
        return None, None, None, "canonical_legal_ir_contract_not_resolved"
    family = _contract_family(contract)
    lane_id = str(raw.get("lane_id") or raw.get("repair_lane") or "").strip()
    try:
        lane = contract.repair_lane(lane_id) if lane_id else contract.repair_lanes[0]
    except (KeyError, IndexError):
        return None, None, None, "repair_lane_not_owned_by_contract"
    requested_paths = _string_values(raw.get("owned_paths") or raw.get("allowed_paths"))
    if requested_paths and any(path not in lane.allowed_paths for path in requested_paths):
        return None, None, None, "path_outside_canonical_ownership"
    generic_support = _finite_float(raw.get("support"))
    support_ratio = _unit_float(
        raw.get("support_ratio"),
        default=(
            generic_support
            if generic_support is not None and 0.0 <= generic_support <= 1.0
            else 1.0
        ),
    )
    explicit_support_count = raw.get("support_count") or raw.get("sample_support")
    if explicit_support_count is None and generic_support is not None and generic_support > 1.0:
        explicit_support_count = generic_support
    support_count = _positive_int(explicit_support_count)
    if support_count <= 0 and support_ratio > 0.0:
        # Promoted guidance intentionally retains only a support ratio.  Its
        # upstream stability gate already enforced recurrence, so represent
        # that lower bound without inventing a cohort size.
        support_count = config.min_support
    confidence = _unit_float(
        raw.get("confidence"),
        default=min(1.0, _finite_nonnegative(raw.get("weight", 0.0))),
    )
    if support_count < config.min_support:
        return None, None, None, "insufficient_pattern_support"
    if confidence < config.min_confidence:
        return None, None, None, "pattern_confidence_below_threshold"
    normalized_id = _identifier(pattern_id) or (
        "lir-pattern-" + _stable_hash({"family": family, "feature": feature})[:20]
    )
    return (
        LegalIRStablePattern(
            pattern_id=normalized_id,
            pattern_kind=kind.value,
            family=family,
            feature=feature,
            support_count=support_count,
            support_ratio=support_ratio,
            confidence=confidence,
            contract_id=contract.contract_id,
            source_id=str(raw.get("source_id") or source_id),
        ),
        contract,
        lane,
        "",
    )


def _pattern_kind(raw: Mapping[str, Any], feature: str) -> LegalIRPatternKind | None:
    value = str(
        raw.get("pattern_kind")
        or raw.get("kind")
        or raw.get("feature_group")
        or ""
    ).strip().lower().replace("-", "_")
    aliases = {
        "compiler_contract": LegalIRPatternKind.FAMILY,
        "contract_id": LegalIRPatternKind.FAMILY,
        "family": LegalIRPatternKind.FAMILY,
        "family_pattern": LegalIRPatternKind.FAMILY,
        "modal_family": LegalIRPatternKind.FAMILY,
        "semantic_slot": LegalIRPatternKind.SEMANTIC_SLOT,
        "slot": LegalIRPatternKind.SEMANTIC_SLOT,
        "proof_auxiliary_head": LegalIRPatternKind.PROOF_HEAD,
        "proof_head": LegalIRPatternKind.PROOF_HEAD,
        "cycle_consistency": LegalIRPatternKind.LEGAL_IR_VIEW,
        "decompiler_surface_template": LegalIRPatternKind.LEGAL_IR_VIEW,
        "legal_ir_view": LegalIRPatternKind.LEGAL_IR_VIEW,
        "logic_view": LegalIRPatternKind.LEGAL_IR_VIEW,
        "logic_view_contract": LegalIRPatternKind.LEGAL_IR_VIEW,
        "view": LegalIRPatternKind.LEGAL_IR_VIEW,
    }
    if value in aliases:
        return aliases[value]
    lowered = feature.lower()
    prefixes = (
        (("semantic-slot:", "slot:", "predicate-argument:"), LegalIRPatternKind.SEMANTIC_SLOT),
        (("proof-head:", "proof_head:", "proof-auxiliary-head:"), LegalIRPatternKind.PROOF_HEAD),
        (
            (
                "legal-ir-view:",
                "logic-view-contract:",
                "decompiler-surface:",
                "cycle-consistency:",
            ),
            LegalIRPatternKind.LEGAL_IR_VIEW,
        ),
        (("modal-family:", "compiler-contract:", "hammer:contract-id:"), LegalIRPatternKind.FAMILY),
    )
    for candidates, kind in prefixes:
        if lowered.startswith(candidates):
            return kind
    return None


def _resolve_contract(
    raw: Mapping[str, Any], *, family: str, feature: str
) -> LegalIRViewContract | None:
    contracts = legal_ir_view_contracts()
    references = (
        raw.get("contract_id"),
        raw.get("legal_ir_view"),
        raw.get("view"),
        raw.get("target_component"),
    )
    for reference in references:
        text = str(reference or "").strip().lower()
        if not text:
            continue
        for contract in contracts:
            aliases = {
                contract.contract_id.lower(),
                contract.view.value.lower(),
                contract.target_component.lower(),
                *(alias.lower() for alias in contract.aliases),
            }
            if text in aliases:
                return contract
    if family:
        for contract in contracts:
            if _contract_family(contract) == family:
                return contract
    lowered = feature.lower()
    for contract in contracts:
        if (
            contract.contract_id.lower() in lowered
            or contract.view.value.lower() in lowered
            or contract.target_component.lower() in lowered
        ):
            return contract
    return None


def _counterfactual_records(
    values: Iterable[Any], *, family: str, limit: int
) -> list[LegalIRCounterfactualEvidence]:
    records: dict[str, LegalIRCounterfactualEvidence] = {}
    for index, value in enumerate(values):
        item = _as_mapping(value)
        if not item or _unsafe_payload(item):
            continue
        item_family = _canonical_family(item.get("family") or family)
        if item_family and item_family != family:
            continue
        intervention = _bounded_text(
            item.get("intervention") or item.get("change") or item.get("mutation")
        )
        expected = _bounded_text(
            item.get("expected_outcome") or item.get("expected") or item.get("expectation")
        )
        observed = _bounded_text(
            item.get("observed_outcome") or item.get("observed") or item.get("actual")
        )
        if not intervention or not expected:
            continue
        passed = _explicit_bool(
            item.get("passed"),
            item.get("preserved"),
            item.get("outcome_preserved"),
            default=bool(observed and observed == expected),
        )
        held_out = _explicit_bool(
            item.get("held_out"), item.get("heldout"), default=True
        )
        evidence_id = _identifier(item.get("evidence_id"))
        descriptor = {
            "evidence_id": evidence_id,
            "expected": expected,
            "family": family,
            "held_out": held_out,
            "intervention": intervention,
            "observed": observed,
            "passed": passed,
        }
        counterfactual_id = _identifier(
            item.get("counterfactual_id") or item.get("case_id") or item.get("id")
        ) or "lir-counterfactual-" + _stable_hash(descriptor)[:20]
        records[counterfactual_id] = LegalIRCounterfactualEvidence(
            counterfactual_id=counterfactual_id,
            family=family,
            intervention=intervention,
            expected_outcome=expected,
            observed_outcome=observed,
            passed=passed,
            held_out=held_out,
            evidence_id=evidence_id,
        )
    return [records[key] for key in sorted(records)][:limit]


def _mutation_records(
    values: Iterable[Any], *, family: str, limit: int
) -> list[LegalIRMutationEvidence]:
    records: dict[str, LegalIRMutationEvidence] = {}
    for value in values:
        item = _as_mapping(value)
        if not item or _unsafe_payload(item):
            continue
        item_family = _canonical_family(item.get("family") or family)
        if item_family and item_family != family:
            continue
        mutation = _bounded_text(
            item.get("mutation") or item.get("mutation_case") or item.get("operator")
        )
        expected = _bounded_text(
            item.get("expected_detection") or item.get("expected") or "rule_rejects_mutation"
        )
        observed = _bounded_text(
            item.get("observed_detection") or item.get("observed") or item.get("outcome")
        )
        if not mutation:
            continue
        detected = _explicit_bool(
            item.get("detected"),
            item.get("killed"),
            item.get("passed"),
            default=False,
        )
        verified = _explicit_bool(item.get("verified"), default=True)
        evidence_id = _identifier(item.get("evidence_id"))
        descriptor = {
            "detected": detected,
            "evidence_id": evidence_id,
            "expected": expected,
            "family": family,
            "mutation": mutation,
            "observed": observed,
            "verified": verified,
        }
        mutation_id = _identifier(
            item.get("mutation_id") or item.get("case_id") or item.get("id")
        ) or "lir-mutation-" + _stable_hash(descriptor)[:20]
        records[mutation_id] = LegalIRMutationEvidence(
            mutation_id=mutation_id,
            family=family,
            mutation=mutation,
            expected_detection=expected,
            observed_detection=observed,
            detected=detected,
            verified=verified,
            evidence_id=evidence_id,
        )
    return [records[key] for key in sorted(records)][:limit]


def _family_attribution(value: Any, *, family: str) -> LegalIRFamilyAttribution | None:
    if isinstance(value, LegalIRFamilyAttribution):
        return value if _canonical_family(value.family) == family else None
    payload = _as_mapping(value)
    per_family = False
    canonical_key = next(
        (key for key in payload if _canonical_family(key) == family), None
    )
    if canonical_key is not None:
        payload = _as_mapping(payload[canonical_key])
        per_family = True
    elif any(
        key in payload and isinstance(payload[key], Mapping)
        for key in ("families", "family_attributions", "per_family")
    ):
        nested = next(
            payload[key]
            for key in ("families", "family_attributions", "per_family")
            if key in payload and isinstance(payload[key], Mapping)
        )
        nested_key = next(
            (key for key in nested if _canonical_family(key) == family), None
        )
        payload = _as_mapping(nested.get(nested_key)) if nested_key is not None else {}
        per_family = True
    elif _canonical_family(payload.get("family")) == family:
        per_family = True
    else:
        for item in _sequence(value):
            mapped = _as_mapping(item)
            if _canonical_family(mapped.get("family")) == family:
                payload = mapped
                per_family = True
                break
    if not payload or not per_family or _unsafe_payload(payload, feature_context=False):
        return None
    metric = str(
        payload.get("compiler_metric")
        or payload.get("metric")
        or payload.get("primary_metric")
        or "compiler_ir_cosine_similarity"
    ).strip()
    improvement = _first_finite(
        payload,
        (
            "predicted_compiler_improvement",
            "heldout_compiler_improvement",
            "predicted_improvement",
            "heldout_improvement",
            "frozen_holdout_mean_objective_delta",
            "improvement",
        ),
    )
    if improvement is None:
        baseline = _finite_float(payload.get("baseline_value"))
        candidate = _finite_float(payload.get("candidate_value"))
        if baseline is not None and candidate is not None:
            improvement = (
                baseline - candidate
                if any(marker in metric.lower() for marker in _LOWER_IS_BETTER_MARKERS)
                else candidate - baseline
            )
    improvement = float(improvement or 0.0)
    heldout_count = _positive_int(
        payload.get("heldout_sample_count")
        or payload.get("frozen_holdout_sample_count")
        or payload.get("holdout_count")
    )
    if heldout_count <= 0:
        heldout_ids = payload.get("heldout_sample_ids") or payload.get("holdout_sample_ids")
        heldout_count = len(_sequence(heldout_ids))
    holdout_id = _identifier(
        payload.get("holdout_id") or payload.get("fixed_canary_id") or payload.get("canary_id")
    )
    heldout_evaluated = _explicit_bool(
        payload.get("heldout_evaluated"),
        payload.get("held_out"),
        payload.get("holdout_survived"),
        default=bool(heldout_count > 0 or holdout_id),
    )
    if heldout_evaluated and heldout_count <= 0:
        # Some aggregate evaluators intentionally disclose only that at least
        # one held-out item participated, not its sample identifier.
        heldout_count = 1
    confidence = _unit_float(
        payload.get("confidence") or payload.get("attribution_confidence"),
        default=1.0,
    )
    descriptor = {
        "confidence": confidence,
        "family": family,
        "heldout_count": heldout_count,
        "holdout_id": holdout_id,
        "improvement": improvement,
        "metric": metric,
    }
    attribution_id = _identifier(payload.get("attribution_id") or payload.get("evidence_id")) or (
        "lir-family-attribution-" + _stable_hash(descriptor)[:20]
    )
    return LegalIRFamilyAttribution(
        attribution_id=attribution_id,
        family=family,
        compiler_metric=metric,
        predicted_improvement=round(improvement, 12),
        heldout_sample_count=heldout_count,
        heldout_evaluated=heldout_evaluated,
        per_family=True,
        fixed_sample_set=_explicit_bool(payload.get("fixed_sample_set"), default=True),
        holdout_isolated=_explicit_bool(payload.get("holdout_isolated"), default=True),
        source_copy_guard_passed=_explicit_bool(
            payload.get("source_copy_guard_passed"), default=True
        ),
        confidence=confidence,
        holdout_id=holdout_id,
    )


def _deterministic_rule(
    *,
    family: str,
    contract: LegalIRViewContract,
    lane: LegalIRRepairLane,
    patterns: Sequence[LegalIRStablePattern],
    target_kind: str,
) -> dict[str, Any]:
    clauses = [
        {
            "feature": item.feature,
            "operator": "categorical_equals",
            "pattern_kind": item.pattern_kind,
        }
        for item in sorted(patterns, key=lambda item: (item.pattern_kind, item.feature))
    ]
    emit = {
        "action": lane.action,
        "contract_id": contract.contract_id,
        "target_component": lane.target_component or contract.target_component,
        "target_kind": target_kind,
    }
    return {
        "deterministic": True,
        "emit": emit,
        "family": family,
        "match": {"all": clauses},
        "on_no_match": "no_op",
        "predicate": {"all": clauses},
        "then": emit,
    }


def _codex_todo(candidate: LegalIRRuleCandidate) -> LegalIRRuleCodexTodo:
    assert candidate.attribution is not None
    premise_security = scan_legal_ir_artifact(
        candidate.to_dict(),
        artifact_id=candidate.candidate_id,
        artifact_role=LegalIRArtifactUse.CODEX_TODO.value,
    )
    if premise_security.rejected:
        raise ValueError(
            "poisoned LegalIR rule candidate cannot be projected to Codex TODO: "
            + ",".join(premise_security.rejection_reasons)
        )
    descriptor = {
        "attribution": candidate.attribution.to_dict(),
        "candidate_id": candidate.candidate_id,
        "owned_paths": candidate.owned_paths,
    }
    todo_id = "lir-rule-codex-todo-" + _stable_hash(descriptor)[:24]
    rollback = {
        **dict(candidate.rollback_metadata),
        "remove_todo_id": todo_id,
    }
    evidence = {
        "attribution": candidate.attribution.to_dict(),
        "confidence": round(candidate.confidence, 12),
        "counterfactual_ids": [item.counterfactual_id for item in candidate.counterfactuals],
        "heldout_compiler_improvement_predicted": True,
        "mutation_ids": [item.mutation_id for item in candidate.mutation_evidence],
        "premise_security": premise_security.to_dict(),
        "support_count": candidate.support_count,
    }
    return LegalIRRuleCodexTodo(
        todo_id=todo_id,
        candidate_id=candidate.candidate_id,
        objective=(
            f"Implement and validate distilled {candidate.target_kind} rule "
            f"{candidate.candidate_id} for {candidate.family}"
        ),
        action=candidate.action,
        family=candidate.family,
        target_component=candidate.target_component,
        owned_paths=candidate.owned_paths,
        validation_commands=candidate.validation_commands,
        evidence=evidence,
        rollback_metadata=rollback,
    )


def _rollback_metadata(
    *,
    candidate_id: str,
    distillation_id: str,
    previous_distillation_id: str,
    source_id: str,
    owned_paths: Sequence[str],
    codex_todo_eligible: bool,
) -> dict[str, Any]:
    descriptor = {
        "candidate_id": candidate_id,
        "distillation_id": distillation_id,
        "owned_paths": sorted(set(owned_paths)),
        "previous_distillation_id": str(previous_distillation_id or ""),
        "source_id": source_id,
    }
    return {
        "activation_key": candidate_id,
        "candidate_id": candidate_id,
        "codex_todo_eligible": codex_todo_eligible,
        "disable_action": "remove_rule_candidate",
        "distillation_id": distillation_id,
        "owned_paths": sorted(set(owned_paths)),
        "previous_distillation_id": str(previous_distillation_id or ""),
        "restore_mode": "candidate_registry_snapshot",
        "rollback_id": "lir-rule-candidate-rollback-" + _stable_hash(descriptor)[:24],
        "schema_version": LEGAL_IR_RULE_DISTILLATION_ROLLBACK_SCHEMA_VERSION,
        "source_id": source_id,
    }


def _evidence_values(value: Any, *, family: str, pattern_id: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if pattern_id and pattern_id in value:
            return _evidence_values(value[pattern_id], family=family, pattern_id="")
        family_key = next(
            (key for key in value if _canonical_family(key) == family), None
        )
        if family_key is not None:
            return _evidence_values(value[family_key], family=family, pattern_id="")
        for key in ("items", "records", "evidence", "counterfactuals", "mutations"):
            if key in value:
                return _evidence_values(value[key], family=family, pattern_id=pattern_id)
        item_family = _canonical_family(value.get("family"))
        if item_family and item_family != family:
            return []
        return [value]
    return [
        item
        for item in _sequence(value)
        if not _canonical_family(_as_mapping(item).get("family"))
        or _canonical_family(_as_mapping(item).get("family")) == family
    ]


def _unsafe_payload(value: Any, *, feature_context: bool = True) -> bool:
    if not isinstance(value, Mapping):
        return False
    for key, child in value.items():
        normalized = str(key).strip().lower()
        if normalized in _SAMPLE_MEMORY_FLAGS and bool(child):
            return True
        if normalized in _FORBIDDEN_PAYLOAD_KEYS and not (
            not feature_context and normalized in {"sample_id", "sample_ids"}
        ):
            return True
        if feature_context and normalized in {
            "feature",
            "feature_name",
            "pattern",
            "rule",
            "deterministic_rule",
        } and _contains_forbidden_marker(child):
            return True
    return False


def _contains_forbidden_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_marker(key) or _contains_forbidden_marker(child)
            for key, child in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_forbidden_marker(child) for child in value)
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in _FORBIDDEN_FEATURE_MARKERS)


def _canonical_family(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    family = legal_ir_view_family_name(text)
    aliases = {
        "knowledge_graph": "kg",
        "knowledge_graphs": "kg",
        "frame": "frame_logic",
        "flogic": "frame_logic",
        "external": "external_provers",
        "prover": "external_provers",
    }
    family = aliases.get(family, aliases.get(text.lower(), family))
    return family if family in LEGAL_IR_VIEW_FAMILIES else ""


def _family_from_feature(feature: str) -> str:
    lowered = feature.lower()
    for family in LEGAL_IR_VIEW_FAMILIES:
        variants = {family, family.replace("_", "-"), family.replace("_", ".")}
        if any(
            f":{variant}:" in f":{lowered}:" or lowered.endswith(f":{variant}")
            for variant in variants
        ):
            return family
    if "knowledge_graph" in lowered or ":kg:" in f":{lowered}:":
        return "kg"
    return "decompiler" if "decompiler" in lowered else ""


def _contract_family(contract: LegalIRViewContract) -> str:
    family = _canonical_family(contract.view.value)
    if family:
        return family
    component = contract.target_component.lower()
    return "decompiler" if "decompiler" in component else ""


def _source_id(payload: Mapping[str, Any], original: Any) -> str:
    for key in (
        "source_id",
        "source_export_id",
        "export_id",
        "promotion_id",
        "guidance_id",
        "model_state_id",
    ):
        if payload.get(key):
            return _identifier(payload[key])
    if payload:
        mapped = _json_value(payload)
    else:
        mapped = sorted(
            (_json_value(item) for item in _sequence(original)),
            key=lambda item: json.dumps(
                item, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ),
        )
    return "lir-rule-source-" + _stable_hash(mapped)[:24]


def _config_dict(config: LegalIRRuleDistillationConfig) -> dict[str, Any]:
    return {
        name: getattr(config, name)
        for name in config.__dataclass_fields__
    }


def _group_rejections(
    patterns: Sequence[LegalIRStablePattern], reason: str
) -> list[dict[str, str]]:
    return [{"pattern_id": item.pattern_id, "reason": reason} for item in patterns]


def _dedupe_rejections(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped = {
        (str(item.get("pattern_id") or ""), str(item.get("reason") or "")):
        dict(item)
        for item in values
    }
    return [deduped[key] for key in sorted(deduped)]


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return dict(result) if isinstance(result, Mapping) else {}
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return list(value)
    return [value]


def _string_values(value: Any) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item).strip().replace("\\", "/")
                for item in _sequence(value)
                if str(item).strip()
            }
        )
    )


def _bounded_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text.encode("utf-8")) > HARD_MAX_SERIALIZED_STRING_BYTES:
        return ""
    return text


def _identifier(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = _SAFE_IDENTIFIER.sub("-", text).strip("-")
    return text[:160]


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _finite_nonnegative(value: Any) -> float:
    result = _finite_float(value)
    return max(0.0, result) if result is not None else 0.0


def _unit_float(value: Any, *, default: float) -> float:
    result = _finite_float(value)
    if result is None:
        result = default
    return round(min(1.0, max(0.0, result)), 12)


def _first_finite(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        result = _finite_float(payload.get(key))
        if result is not None:
            return result
    return None


def _explicit_bool(*values: Any, default: bool) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "passed", "pass", "1"}:
                return True
            if normalized in {"false", "no", "failed", "fail", "0"}:
                return False
        return bool(value)
    return bool(default)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("distillation evidence cannot contain non-finite numbers")
        return round(value, 12)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(child)
            for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child) for child in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    return str(value)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "HARD_MAX_EVIDENCE_ITEMS",
    "HARD_MAX_OWNED_PATHS",
    "HARD_MAX_PATTERNS_PER_CANDIDATE",
    "HARD_MAX_RULE_CANDIDATES",
    "LEGAL_IR_FAMILY_ATTRIBUTION_SCHEMA_VERSION",
    "LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION",
    "LEGAL_IR_RULE_DISTILLATION_ROLLBACK_SCHEMA_VERSION",
    "LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION",
    "LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION",
    "LegalIRCodexTodo",
    "LegalIRCounterfactualEvidence",
    "LegalIRFamilyAttribution",
    "LegalIRMutationEvidence",
    "LegalIRPatternKind",
    "LegalIRRuleCandidate",
    "LegalIRRuleCodexTodo",
    "LegalIRRuleDistillation",
    "LegalIRRuleDistillationConfig",
    "LegalIRRuleDistillationResult",
    "LegalIRRuleDistiller",
    "LegalIRRuleTarget",
    "LegalIRStablePattern",
    "build_legal_ir_rule_candidates",
    "distill_learned_legal_ir_rules",
    "distill_legal_ir_rule_candidates",
    "distill_stable_legal_ir_patterns",
    "distill_stable_learned_representations",
    "legal_ir_rule_distillation",
    "project_distilled_rules_to_codex_todos",
]
