"""Deterministic, evidence-aware capacity control for sparse autoencoder state.

The accepted v2 checkpoint is intentionally conservative: it keeps the
previously accepted rows and admits no legacy tail.  This module preserves that
behaviour as :data:`ACCEPTED_STATE_V2_POLICY` while providing a separately
enabled evidence-aware policy.

Capacity is expressed by *family* rather than one uniform limit.  A capacity
decision is made for a coupled semantic key, so every parameter row sharing
that key is retained or evicted atomically.  Candidate scores combine bounded
activation, recency, held-out loss contribution, trusted proof/reconstruction
impact, and migration confidence.  Source-text memory, rejected proof output,
and unsigned guidance are rejected before scoring and can never win unused
capacity.

Reports contain counts and stable key digests, never raw feature keys or tensor
payloads.  This is important because a rejected key may itself contain source
text.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence

from .modal_autoencoder import (
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS,
    ModalAutoencoderTrainingState,
)


MODAL_AUTOENCODER_FEATURE_CAPACITY_SCHEMA_VERSION = (
    "modal-autoencoder-feature-capacity-v1"
)
MODAL_AUTOENCODER_FEATURE_EVIDENCE_SCHEMA_VERSION = (
    "modal-autoencoder-feature-capacity-evidence-v1"
)
MODAL_AUTOENCODER_FEATURE_CAPACITY_POLICY_VERSION = (
    "modal-autoencoder-feature-capacity-policy-v1"
)

ACCEPTED_STATE_V2 = "accepted_state_v2"
EVIDENCE_AWARE_SPARSE_TAIL_V1 = "evidence_aware_sparse_tail_v1"
SUPPORTED_CAPACITY_MODES = frozenset(
    {ACCEPTED_STATE_V2, EVIDENCE_AWARE_SPARSE_TAIL_V1}
)


class FeatureCapacityError(ValueError):
    """Raised when capacity inputs are incomplete or unsafe."""


class UnknownCapacityGroupError(FeatureCapacityError):
    """Raised when a caller presents a group outside the closed schema."""


class UnsafeCapacityEvidenceError(FeatureCapacityError):
    """Raised when an evidence packet cannot be interpreted safely."""


class FeatureCapacityFamily(str, Enum):
    """Closed capacity namespaces required by the sparse-state contract."""

    EMBEDDINGS = "embeddings"
    GLOBAL_LOGITS = "global_logits"
    PER_VIEW_LOGITS = "per_view_logits"
    RELATION_ENTITY_HEADS = "relation_entity_heads"
    PROJECTION_FACTORS = "projection_factors"
    PROOF_FEEDBACK = "proof_feedback"
    COMPILER_GUIDANCE = "compiler_guidance"
    CALIBRATION_STATE = "calibration_state"


def _capacity_group_name(value: str | FeatureCapacityFamily) -> str:
    return value.value if isinstance(value, FeatureCapacityFamily) else str(value)


DEFAULT_FEATURE_CAPACITY_BUDGETS: Mapping[str, int] = {
    FeatureCapacityFamily.EMBEDDINGS.value: 32_768,
    FeatureCapacityFamily.GLOBAL_LOGITS.value: 512,
    FeatureCapacityFamily.PER_VIEW_LOGITS.value: 16_384,
    FeatureCapacityFamily.RELATION_ENTITY_HEADS.value: 16_384,
    FeatureCapacityFamily.PROJECTION_FACTORS.value: 4_096,
    FeatureCapacityFamily.PROOF_FEEDBACK.value: 4_096,
    FeatureCapacityFamily.COMPILER_GUIDANCE.value: 8_192,
    FeatureCapacityFamily.CALIBRATION_STATE.value: 2_048,
}

# The legacy state still presents semantic groups.  This closed routing table
# gives each one a capacity family while preserving its coupled-key boundary.
MODAL_AUTOENCODER_CAPACITY_GROUP_FAMILIES: Mapping[str, str] = {
    "compiler_quality": FeatureCapacityFamily.COMPILER_GUIDANCE.value,
    "logic_signature": FeatureCapacityFamily.COMPILER_GUIDANCE.value,
    "round_trip_signal": FeatureCapacityFamily.CALIBRATION_STATE.value,
    "decompiler_plan": FeatureCapacityFamily.RELATION_ENTITY_HEADS.value,
    "predicate_argument": FeatureCapacityFamily.RELATION_ENTITY_HEADS.value,
    "feature": FeatureCapacityFamily.EMBEDDINGS.value,
    "family": FeatureCapacityFamily.EMBEDDINGS.value,
    "family_semantic_slot": FeatureCapacityFamily.PROJECTION_FACTORS.value,
    "family_semantic_slot_legal_ir_view": (
        FeatureCapacityFamily.PROJECTION_FACTORS.value
    ),
    "family_legal_ir_view": FeatureCapacityFamily.PER_VIEW_LOGITS.value,
    "semantic_slot": FeatureCapacityFamily.RELATION_ENTITY_HEADS.value,
    "legal_ir_view": FeatureCapacityFamily.GLOBAL_LOGITS.value,
    "semantic_slot_legal_ir_view": FeatureCapacityFamily.PER_VIEW_LOGITS.value,
}

if set(MODAL_AUTOENCODER_CAPACITY_GROUP_FAMILIES) != set(
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS
):
    raise RuntimeError("capacity family routing does not match autoencoder groups")

KNOWN_CAPACITY_GROUPS = frozenset(
    {
        *(family.value for family in FeatureCapacityFamily),
        *MODAL_AUTOENCODER_CAPACITY_GROUP_FAMILIES,
    }
)

DEFAULT_EVIDENCE_WEIGHTS: Mapping[str, float] = {
    "activation_frequency": 0.20,
    "recency": 0.15,
    "held_out_loss_contribution": 0.25,
    "trusted_impact": 0.20,
    "migration_confidence": 0.20,
}

_SOURCE_PREFIX = re.compile(
    r"^(?:raw[-_: ]?(?:source|text)|source[-_: ]?(?:span|text)|"
    r"(?:sample|example)[-_:#]|document[-_:#]?id[-_:#])",
    re.IGNORECASE,
)
_REPORT_FAMILY = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _stable_digest(value: Any) -> str:
    """Hash an arbitrary key without placing its text in a report."""

    try:
        encoded = _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise FeatureCapacityError(
            "capacity keys must have a canonical JSON encoding"
        ) from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bounded(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise UnsafeCapacityEvidenceError("evidence values must be finite")
    return min(1.0, max(0.0, number))


def _copy_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_copy_value(item) for item in value]
    return value


def _key_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _key_is_source_like(value: Any) -> bool:
    text = _key_text(value).strip()
    if _SOURCE_PREFIX.search(text):
        return True
    words = text.split()
    return (
        len(text.encode("utf-8")) > 2_048
        or len(words) >= 4
        or (len(words) >= 3 and text.endswith((".", ";", "?", "!")))
    )


def _key_is_protected(value: Any) -> bool:
    text = _key_text(value).strip().lower()
    return (
        text in {"__global__", "global", "bias"}
        or text.endswith(":bias")
        or text.endswith("|bias")
    )


@dataclass(frozen=True, slots=True)
class FeatureCapacityEvidence:
    """Bounded promotion evidence for one coupled sparse key.

    ``guidance_signed`` is tri-state.  ``None`` means the row is not compiler
    guidance, ``True`` means its signature was verified, and ``False`` marks
    unsigned guidance and makes the row ineligible.
    """

    activation_frequency: float = 0.0
    recency: float = 0.0
    held_out_loss_contribution: float = 0.0
    trusted_proof_impact: float = 0.0
    trusted_reconstruction_impact: float = 0.0
    migration_confidence: float = 0.0
    contains_source_text: bool = False
    source_text_memorization: bool = False
    proof_rejected: bool = False
    rejected_proof_output: bool = False
    guidance_signed: bool | None = None
    unsigned_guidance: bool = False
    evidence_id: str = ""
    semantic_family: str = ""

    def __post_init__(self) -> None:
        for name in (
            "activation_frequency",
            "recency",
            "held_out_loss_contribution",
            "trusted_proof_impact",
            "trusted_reconstruction_impact",
            "migration_confidence",
        ):
            raw_value = getattr(self, name)
            if isinstance(raw_value, bool):
                raise UnsafeCapacityEvidenceError(
                    f"{name} must be numeric, not boolean"
                )
            value = float(raw_value)
            if not math.isfinite(value):
                raise UnsafeCapacityEvidenceError(
                    f"{name} must be finite"
                )
        for name in (
            "contains_source_text",
            "source_text_memorization",
            "proof_rejected",
            "rejected_proof_output",
            "unsigned_guidance",
        ):
            if not isinstance(getattr(self, name), bool):
                raise UnsafeCapacityEvidenceError(
                    f"{name} must be boolean"
                )
        if self.guidance_signed is not None and not isinstance(
            self.guidance_signed, bool
        ):
            raise UnsafeCapacityEvidenceError(
                "guidance_signed must be true, false, or null"
            )
        if self.evidence_id and not str(self.evidence_id).strip():
            raise UnsafeCapacityEvidenceError(
                "evidence_id must be empty or non-blank"
            )
        if self.semantic_family and not _REPORT_FAMILY.fullmatch(
            str(self.semantic_family)
        ):
            raise UnsafeCapacityEvidenceError(
                "semantic_family must be a bounded identifier"
            )

    @property
    def exclusion_reason(self) -> str:
        if self.contains_source_text or self.source_text_memorization:
            return "source_text_memorization"
        if self.proof_rejected or self.rejected_proof_output:
            return "rejected_proof_output"
        if self.guidance_signed is False or self.unsigned_guidance:
            return "unsigned_guidance"
        return ""

    @property
    def eligible(self) -> bool:
        return not self.exclusion_reason

    def components(self) -> Dict[str, float]:
        proof = _bounded(self.trusted_proof_impact)
        reconstruction = _bounded(self.trusted_reconstruction_impact)
        return {
            "activation_frequency": _bounded(self.activation_frequency),
            "held_out_loss_contribution": _bounded(
                self.held_out_loss_contribution
            ),
            "migration_confidence": _bounded(self.migration_confidence),
            "recency": _bounded(self.recency),
            # Proof and reconstruction are complementary trusted pathways.
            # Taking their maximum avoids double-counting a single outcome.
            "trusted_impact": max(proof, reconstruction),
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "FeatureCapacityEvidence":
        """Parse a strict JSON-compatible evidence packet."""

        aliases = {
            "activation_rate": "activation_frequency",
            "heldout_loss_contribution": "held_out_loss_contribution",
            "held_out_contribution": "held_out_loss_contribution",
            "proof_impact": "trusted_proof_impact",
            "reconstruction_impact": "trusted_reconstruction_impact",
            "migration_confidence_score": "migration_confidence",
            "contains_source_sample": "contains_source_text",
            "proof_output_rejected": "rejected_proof_output",
            "signed_guidance": "guidance_signed",
            "family": "semantic_family",
        }
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        normalized: Dict[str, Any] = {}
        for raw_name, item in value.items():
            if str(raw_name) == "schema_version":
                if item != MODAL_AUTOENCODER_FEATURE_EVIDENCE_SCHEMA_VERSION:
                    raise UnsafeCapacityEvidenceError(
                        "unsupported capacity evidence schema"
                    )
                continue
            name = aliases.get(str(raw_name), str(raw_name))
            if name not in allowed:
                raise UnsafeCapacityEvidenceError(
                    f"unknown evidence field: {raw_name}"
                )
            if name in normalized:
                raise UnsafeCapacityEvidenceError(
                    f"duplicate evidence field: {name}"
                )
            normalized[name] = item
        return cls(**normalized)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activation_frequency": float(self.activation_frequency),
            "contains_source_text": bool(self.contains_source_text),
            "evidence_id": str(self.evidence_id),
            "guidance_signed": self.guidance_signed,
            "held_out_loss_contribution": float(
                self.held_out_loss_contribution
            ),
            "migration_confidence": float(self.migration_confidence),
            "proof_rejected": bool(self.proof_rejected),
            "recency": float(self.recency),
            "rejected_proof_output": bool(self.rejected_proof_output),
            "schema_version": MODAL_AUTOENCODER_FEATURE_EVIDENCE_SCHEMA_VERSION,
            "semantic_family": str(self.semantic_family),
            "source_text_memorization": bool(
                self.source_text_memorization
            ),
            "trusted_proof_impact": float(self.trusted_proof_impact),
            "trusted_reconstruction_impact": float(
                self.trusted_reconstruction_impact
            ),
            "unsigned_guidance": bool(self.unsigned_guidance),
        }


# Names used in design notes and early callers.
CapacityEvidence = FeatureCapacityEvidence
SparseFeatureEvidence = FeatureCapacityEvidence


def _normalized_budgets(
    overrides: Mapping[str, int] | None,
) -> Dict[str, int]:
    budgets = dict(DEFAULT_FEATURE_CAPACITY_BUDGETS)
    for raw_group, raw_budget in (overrides or {}).items():
        group = _capacity_group_name(raw_group)
        if group not in KNOWN_CAPACITY_GROUPS:
            raise UnknownCapacityGroupError(
                f"unknown capacity group: {group!r}"
            )
        budget = int(raw_budget)
        if budget < 0:
            raise FeatureCapacityError(
                f"capacity for {group!r} must be non-negative"
            )
        budgets[group] = budget
    return budgets


@dataclass(frozen=True, slots=True)
class FeatureCapacityPolicy:
    """Selection mode, per-family budgets, and bounded score weights."""

    mode: str = EVIDENCE_AWARE_SPARSE_TAIL_V1
    group_budgets: Mapping[str, int] = field(
        default_factory=lambda: dict(DEFAULT_FEATURE_CAPACITY_BUDGETS)
    )
    evidence_weights: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_EVIDENCE_WEIGHTS)
    )
    require_positive_evidence: bool = True
    preserve_accepted_keys: bool = False

    def __post_init__(self) -> None:
        if self.mode not in SUPPORTED_CAPACITY_MODES:
            raise FeatureCapacityError(
                f"unsupported capacity mode: {self.mode!r}"
            )
        budgets = _normalized_budgets(self.group_budgets)
        object.__setattr__(self, "group_budgets", budgets)
        unknown_weights = set(self.evidence_weights) - set(
            DEFAULT_EVIDENCE_WEIGHTS
        )
        if unknown_weights:
            raise FeatureCapacityError(
                "unknown evidence weights: "
                + ", ".join(sorted(unknown_weights))
            )
        weights = dict(DEFAULT_EVIDENCE_WEIGHTS)
        weights.update(
            {
                str(name): float(value)
                for name, value in self.evidence_weights.items()
            }
        )
        if any(
            not math.isfinite(value) or value < 0.0
            for value in weights.values()
        ):
            raise FeatureCapacityError(
                "evidence weights must be finite and non-negative"
            )
        if sum(weights.values()) <= 0.0:
            raise FeatureCapacityError(
                "at least one evidence weight must be positive"
            )
        object.__setattr__(self, "evidence_weights", weights)
        if self.mode == ACCEPTED_STATE_V2 and not self.preserve_accepted_keys:
            object.__setattr__(self, "preserve_accepted_keys", True)

    @classmethod
    def accepted_state_v2(cls) -> "FeatureCapacityPolicy":
        return cls(
            mode=ACCEPTED_STATE_V2,
            preserve_accepted_keys=True,
        )

    @classmethod
    def evidence_aware(
        cls,
        *,
        group_budgets: Mapping[str, int] | None = None,
        evidence_weights: Mapping[str, float] | None = None,
        require_positive_evidence: bool = True,
        preserve_accepted_keys: bool = False,
    ) -> "FeatureCapacityPolicy":
        return cls(
            mode=EVIDENCE_AWARE_SPARSE_TAIL_V1,
            group_budgets=(
                dict(DEFAULT_FEATURE_CAPACITY_BUDGETS)
                if group_budgets is None
                else group_budgets
            ),
            evidence_weights=(
                dict(DEFAULT_EVIDENCE_WEIGHTS)
                if evidence_weights is None
                else evidence_weights
            ),
            require_positive_evidence=require_positive_evidence,
            preserve_accepted_keys=preserve_accepted_keys,
        )

    def capacity_family_for(
        self, group: str | FeatureCapacityFamily
    ) -> str:
        name = _capacity_group_name(group)
        if name in (family.value for family in FeatureCapacityFamily):
            return name
        try:
            return MODAL_AUTOENCODER_CAPACITY_GROUP_FAMILIES[name]
        except KeyError as exc:
            raise UnknownCapacityGroupError(
                f"unknown capacity group: {name!r}"
            ) from exc

    def budget_for(self, group: str | FeatureCapacityFamily) -> int:
        family = self.capacity_family_for(group)
        # A semantic-group override takes precedence over its family default.
        return int(
            self.group_budgets.get(
                _capacity_group_name(group),
                self.group_budgets[family],
            )
        )

    def score(
        self, evidence: FeatureCapacityEvidence
    ) -> tuple[float, Dict[str, float]]:
        components = evidence.components()
        denominator = sum(self.evidence_weights.values())
        score = sum(
            components[name] * self.evidence_weights[name]
            for name in sorted(components)
        ) / denominator
        return score, components

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_weights": {
                name: float(value)
                for name, value in sorted(self.evidence_weights.items())
            },
            "group_budgets": {
                name: int(value)
                for name, value in sorted(self.group_budgets.items())
            },
            "mode": self.mode,
            "preserve_accepted_keys": bool(self.preserve_accepted_keys),
            "require_positive_evidence": bool(
                self.require_positive_evidence
            ),
            "schema_version": (
                MODAL_AUTOENCODER_FEATURE_CAPACITY_POLICY_VERSION
            ),
        }


PerGroupCapacityPolicy = FeatureCapacityPolicy
SparseCapacityPolicy = FeatureCapacityPolicy
ACCEPTED_STATE_V2_POLICY = FeatureCapacityPolicy.accepted_state_v2()
DEFAULT_EVIDENCE_AWARE_CAPACITY_POLICY = FeatureCapacityPolicy.evidence_aware()


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    """Retained keys and a privacy-preserving report for one group."""

    group: str
    family: str
    retained_keys: tuple[Any, ...]
    evicted_keys: tuple[Any, ...]
    report: Mapping[str, Any]

    @property
    def retained(self) -> tuple[Any, ...]:
        return self.retained_keys

    @property
    def evicted(self) -> tuple[Any, ...]:
        return self.evicted_keys


def _coerce_evidence(value: Any) -> FeatureCapacityEvidence:
    if isinstance(value, FeatureCapacityEvidence):
        return value
    if isinstance(value, Mapping):
        return FeatureCapacityEvidence.from_mapping(value)
    raise UnsafeCapacityEvidenceError(
        "capacity evidence must be FeatureCapacityEvidence or a mapping"
    )


def _evidence_for(
    key: Any,
    evidence: Mapping[Any, FeatureCapacityEvidence | Mapping[str, Any]],
    *,
    accepted: bool,
) -> FeatureCapacityEvidence:
    value = evidence.get(key)
    if value is not None:
        return _coerce_evidence(value)
    # Existing accepted rows have maximal migration confidence; legacy-only
    # rows with no evidence remain zero-score and cannot consume tail capacity.
    return FeatureCapacityEvidence(
        migration_confidence=1.0 if accepted else 0.0,
        evidence_id="accepted-state-v2" if accepted else "",
    )


def select_sparse_tail(
    group: str | FeatureCapacityFamily,
    candidate_keys: Iterable[Any],
    *,
    evidence: Mapping[
        Any, FeatureCapacityEvidence | Mapping[str, Any]
    ] | None = None,
    accepted_keys: Iterable[Any] = (),
    policy: FeatureCapacityPolicy | None = None,
) -> CapacityDecision:
    """Select one capacity group's keys deterministically.

    Selection is atomic at the key level.  Callers apply the returned key set
    to every coupled parameter map in the group.
    """

    effective_policy = policy or DEFAULT_EVIDENCE_AWARE_CAPACITY_POLICY
    group_name = _capacity_group_name(group)
    family = effective_policy.capacity_family_for(group_name)
    budget = effective_policy.budget_for(group_name)
    candidates = set(candidate_keys)
    accepted = set(accepted_keys)
    # Validate canonicalizability before sorting or reporting.  Falling back to
    # object repr would make tie breaks/process reports dependent on addresses.
    for key in candidates:
        _stable_digest(key)
    if not accepted <= candidates:
        raise FeatureCapacityError(
            "accepted keys must be a subset of candidate keys"
        )
    evidence_map = dict(evidence or {})
    unknown_evidence_keys = set(evidence_map) - candidates
    if unknown_evidence_keys:
        raise FeatureCapacityError(
            "evidence contains keys outside the candidate set"
        )

    if effective_policy.mode == ACCEPTED_STATE_V2:
        retained = set(accepted)
        evicted = candidates - retained
        ordered_retained = tuple(sorted(retained, key=_key_text))
        ordered_evicted = tuple(sorted(evicted, key=_key_text))
        return CapacityDecision(
            group=group_name,
            family=family,
            retained_keys=ordered_retained,
            evicted_keys=ordered_evicted,
            report={
                "accepted_key_count": len(accepted),
                "budget": budget,
                "budget_enforced": False,
                "candidate_count": len(candidates),
                "evicted_count": len(evicted),
                "evicted_key_digests": [
                    _stable_digest(key) for key in ordered_evicted
                ],
                "exclusions": {},
                "family": family,
                "group": group_name,
                "mode": effective_policy.mode,
                "retained_count": len(retained),
                "retained_key_digests": [
                    _stable_digest(key) for key in ordered_retained
                ],
                "schema_version": (
                    MODAL_AUTOENCODER_FEATURE_CAPACITY_SCHEMA_VERSION
                ),
                "tie_break": "canonical_key_lexical_v1",
                "tie_break_count": 0,
                "zero_risk_baseline": True,
            },
        )

    rows: list[tuple[Any, float, Dict[str, float], bool, str]] = []
    exclusions: Dict[str, int] = {}
    semantic_families: Dict[str, Dict[str, int]] = {}
    for key in candidates:
        is_accepted = key in accepted
        item = _evidence_for(
            key,
            evidence_map,
            accepted=is_accepted,
        )
        reason = item.exclusion_reason
        if not reason and _key_is_source_like(key) and not is_accepted:
            reason = "source_text_memorization"
        score, components = effective_policy.score(item)
        if (
            not reason
            and effective_policy.require_positive_evidence
            and not is_accepted
            and score <= 0.0
        ):
            reason = "missing_positive_evidence"
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
        report_family = str(item.semantic_family).strip() or family
        semantic_families.setdefault(
            report_family,
            {"candidate_count": 0, "evicted_count": 0, "retained_count": 0},
        )["candidate_count"] += 1
        rows.append((key, score, components, is_accepted, reason))

    eligible = [row for row in rows if not row[4]]
    pinned = [
        row
        for row in eligible
        if row[3] and effective_policy.preserve_accepted_keys
    ]
    if len(pinned) > budget:
        raise FeatureCapacityError(
            f"capacity group {group_name!r} has {len(pinned)} pinned accepted "
            f"keys but budget {budget}"
        )

    ordered_pinned = sorted(pinned, key=lambda row: _key_text(row[0]))
    pinned_keys = {row[0] for row in ordered_pinned}
    ordinary = [row for row in eligible if row[0] not in pinned_keys]
    ordinary.sort(
        key=lambda row: (
            0 if row[3] and _key_is_protected(row[0]) else 1,
            -row[1],
            _key_text(row[0]),
        )
    )
    retained_rows = ordered_pinned + ordinary[: max(0, budget - len(pinned))]
    retained = {row[0] for row in retained_rows}
    evicted = candidates - retained

    row_by_key = {row[0]: row for row in rows}
    for key in retained:
        report_family = (
            str(
                _evidence_for(
                    key, evidence_map, accepted=key in accepted
                ).semantic_family
            ).strip()
            or family
        )
        semantic_families[report_family]["retained_count"] += 1
    for key in evicted:
        report_family = (
            str(
                _evidence_for(
                    key, evidence_map, accepted=key in accepted
                ).semantic_family
            ).strip()
            or family
        )
        semantic_families[report_family]["evicted_count"] += 1

    score_counts: Dict[float, int] = {}
    for row in eligible:
        score_counts[row[1]] = score_counts.get(row[1], 0) + 1
    tie_break_count = sum(count - 1 for count in score_counts.values())
    boundary_tie = False
    ranked_unpinned = ordinary
    available = max(0, budget - len(pinned))
    if 0 < available < len(ranked_unpinned):
        boundary_tie = (
            ranked_unpinned[available - 1][1]
            == ranked_unpinned[available][1]
        )

    ordered_retained = tuple(sorted(retained, key=_key_text))
    ordered_evicted = tuple(sorted(evicted, key=_key_text))
    retained_component_totals = {
        component: round(
            math.fsum(
                row_by_key[key][2][component]
                for key in sorted(retained, key=_key_text)
            ),
            15,
        )
        for component in sorted(DEFAULT_EVIDENCE_WEIGHTS)
    }
    return CapacityDecision(
        group=group_name,
        family=family,
        retained_keys=ordered_retained,
        evicted_keys=ordered_evicted,
        report={
            "accepted_key_count": len(accepted),
            "boundary_tie": boundary_tie,
            "budget": budget,
            "budget_enforced": True,
            "candidate_count": len(candidates),
            "evicted_count": len(evicted),
            "evicted_key_digests": [
                _stable_digest(key) for key in ordered_evicted
            ],
            "exclusions": dict(sorted(exclusions.items())),
            "family": family,
            "family_reports": {
                name: dict(sorted(values.items()))
                for name, values in sorted(semantic_families.items())
            },
            "group": group_name,
            "mode": effective_policy.mode,
            "pinned_accepted_count": len(pinned),
            "retained_component_totals": retained_component_totals,
            "retained_count": len(retained),
            "retained_key_digests": [
                _stable_digest(key) for key in ordered_retained
            ],
            "schema_version": (
                MODAL_AUTOENCODER_FEATURE_CAPACITY_SCHEMA_VERSION
            ),
            "tie_break": "accepted_global_then_score_then_canonical_key_v1",
            "tie_break_count": tie_break_count,
            "zero_risk_baseline": False,
        },
    )


select_evidence_aware_sparse_tail = select_sparse_tail


@dataclass(frozen=True, slots=True)
class FeatureCapacityResult:
    """A capacity-controlled state plus its reproducible decision report."""

    state: ModalAutoencoderTrainingState
    report: Mapping[str, Any]

    @property
    def compacted(self) -> bool:
        return bool(self.report.get("compacted"))


CapacitySelectionResult = FeatureCapacityResult


def _state_group_keys(
    state: ModalAutoencoderTrainingState, fields: Sequence[str]
) -> set[Any]:
    keys: set[Any] = set()
    for field_name in fields:
        keys.update(getattr(state, field_name))
    return keys


def apply_modal_autoencoder_feature_capacity(
    state: ModalAutoencoderTrainingState,
    *,
    policy: FeatureCapacityPolicy | None = None,
    evidence_by_group: Mapping[
        str,
        Mapping[Any, FeatureCapacityEvidence | Mapping[str, Any]],
    ] | None = None,
    accepted_state: ModalAutoencoderTrainingState | None = None,
    inplace: bool = False,
) -> FeatureCapacityResult:
    """Apply per-group selection to all coupled legacy state maps.

    The generic :func:`select_sparse_tail` also supports proof feedback,
    compiler guidance, projection-factor, and calibration records supplied by
    newer packed-state callers.  This adapter handles the dictionary fields in
    :class:`ModalAutoencoderTrainingState`.
    """

    effective_policy = policy or DEFAULT_EVIDENCE_AWARE_CAPACITY_POLICY
    evidence_groups = dict(evidence_by_group or {})
    unknown_groups = set(evidence_groups) - set(
        MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS
    )
    if unknown_groups:
        raise UnknownCapacityGroupError(
            "unknown capacity evidence groups: "
            + ", ".join(sorted(unknown_groups))
        )
    output = state if inplace else state.copy()
    baseline = accepted_state or state
    group_reports: Dict[str, Any] = {}
    family_reports: Dict[str, Dict[str, int]] = {}
    compacted_fields: set[str] = set()
    before_entry_count = output.generalizable_entry_count()

    for group, fields in sorted(
        MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.items()
    ):
        candidates = _state_group_keys(output, fields)
        accepted = _state_group_keys(baseline, fields) & candidates
        decision = select_sparse_tail(
            group,
            candidates,
            evidence=evidence_groups.get(group, {}),
            accepted_keys=accepted,
            policy=effective_policy,
        )
        retained = set(decision.retained_keys)
        for field_name in fields:
            mapping = getattr(output, field_name)
            if any(key not in retained for key in mapping):
                setattr(
                    output,
                    field_name,
                    {
                        key: _copy_value(mapping[key])
                        for key in sorted(mapping, key=_key_text)
                        if key in retained
                    },
                )
                compacted_fields.add(field_name)
        group_reports[group] = dict(decision.report)
        aggregate = family_reports.setdefault(
            decision.family,
            {
                "candidate_count": 0,
                "evicted_count": 0,
                "group_count": 0,
                "retained_count": 0,
            },
        )
        aggregate["candidate_count"] += len(candidates)
        aggregate["evicted_count"] += len(decision.evicted_keys)
        aggregate["group_count"] += 1
        aggregate["retained_count"] += len(decision.retained_keys)

    after_entry_count = output.generalizable_entry_count()
    report = {
        "after_entry_count": after_entry_count,
        "before_entry_count": before_entry_count,
        "compacted": bool(compacted_fields),
        "compacted_fields": sorted(compacted_fields),
        "dropped_entry_count": before_entry_count - after_entry_count,
        "family_reports": {
            name: dict(sorted(values.items()))
            for name, values in sorted(family_reports.items())
        },
        "groups": group_reports,
        "policy": effective_policy.to_dict(),
        "schema_version": MODAL_AUTOENCODER_FEATURE_CAPACITY_SCHEMA_VERSION,
    }
    return FeatureCapacityResult(state=output, report=report)


compact_modal_autoencoder_feature_capacity = (
    apply_modal_autoencoder_feature_capacity
)
select_feature_capacity = apply_modal_autoencoder_feature_capacity


def validate_capacity_groups(
    groups: Iterable[str | FeatureCapacityFamily],
) -> tuple[str, ...]:
    """Validate and return a canonical group sequence."""

    values = tuple(sorted({_capacity_group_name(group) for group in groups}))
    unknown = set(values) - KNOWN_CAPACITY_GROUPS
    if unknown:
        raise UnknownCapacityGroupError(
            "unknown capacity groups: " + ", ".join(sorted(unknown))
        )
    return values


__all__ = [
    "ACCEPTED_STATE_V2",
    "ACCEPTED_STATE_V2_POLICY",
    "CapacityDecision",
    "CapacityEvidence",
    "CapacitySelectionResult",
    "DEFAULT_EVIDENCE_AWARE_CAPACITY_POLICY",
    "DEFAULT_EVIDENCE_WEIGHTS",
    "DEFAULT_FEATURE_CAPACITY_BUDGETS",
    "EVIDENCE_AWARE_SPARSE_TAIL_V1",
    "FeatureCapacityError",
    "FeatureCapacityEvidence",
    "FeatureCapacityFamily",
    "FeatureCapacityPolicy",
    "FeatureCapacityResult",
    "KNOWN_CAPACITY_GROUPS",
    "MODAL_AUTOENCODER_CAPACITY_GROUP_FAMILIES",
    "MODAL_AUTOENCODER_FEATURE_CAPACITY_POLICY_VERSION",
    "MODAL_AUTOENCODER_FEATURE_CAPACITY_SCHEMA_VERSION",
    "MODAL_AUTOENCODER_FEATURE_EVIDENCE_SCHEMA_VERSION",
    "PerGroupCapacityPolicy",
    "SparseCapacityPolicy",
    "SparseFeatureEvidence",
    "UnknownCapacityGroupError",
    "UnsafeCapacityEvidenceError",
    "apply_modal_autoencoder_feature_capacity",
    "compact_modal_autoencoder_feature_capacity",
    "select_evidence_aware_sparse_tail",
    "select_feature_capacity",
    "select_sparse_tail",
    "validate_capacity_groups",
]
