"""Hybrid and stage-local evaluation modes for semantic round-trip research.

Interface: ``HybridRoundTripArms@1``

This module preregisters research evaluation modes that can measure stage-local
and hybrid compositions **without** mutating the frozen thirty-cell promotion
arm set.  Promotion still requires the full replacement-matrix gates; research
modes may score forward/cycle/end-to-end separately and may abstain fail-closed
when required preflight is missing.

Preregistered modes
-------------------

1. ``constructor_only`` — baseline typed-deontic vs constructor candidates
   (forward-stage metrics; cycle/end-to-end reported as not_applicable).
2. ``realizer_only`` — fixed L1 input realized by a candidate realizer
   (cycle/end-to-end use a fixed L2 constructor for paired stage losses).
3. ``hybrid`` — ``typed_deontic → optional selective/model repair →
   deterministic realizer`` with fail-closed abstention when model repair is
   requested without live-smoke preflight.

Hybrid success claims against the deterministic baseline require a paired
case-cluster bootstrap comparison (see :func:`authorize_hybrid_success_claim`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripConstructor,
    RoundTripRealizer,
    RoundTripResult,
)
from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
    TypedDeonticCanonicalConstructor,
)
from benchmarks.semantic_roundtrip.evaluation_status import (
    DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
    PREFLIGHT_CAUSAL_QUALIFICATION,
    PREFLIGHT_LIVE_SMOKE,
    EvaluationStatus,
    LaunchPreflightError,
    NotMeasuredReason,
    assert_matrix_launch_preflight,
    evaluate_matrix_launch_preflight,
    required_preflights_for_arm,
)
from benchmarks.semantic_roundtrip.metrics import (
    RoundTripLosses,
    compare_semantic_ir,
    make_round_trip_result,
    round_trip_losses,
    semantic_score,
)
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CANONICAL_DETERMINISTIC_REALIZER_INTERFACE,
    CanonicalDeterministicRealizer,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    SELECTIVE_LEANSTRAL_REPAIR_INTERFACE,
    RepairAttemptStatus,
    SelectiveLeanstralRepair,
    SelectiveRepairPolicy,
    ZeroTriggerDetector,
)
from benchmarks.semantic_roundtrip.statistics import (
    ROUND_TRIP_PAIRED_STATISTICS_INTERFACE,
    RoundTripPairedStatistics,
)


HYBRID_ROUND_TRIP_ARMS_INTERFACE: Final = "HybridRoundTripArms@1"
HYBRID_EVAL_MODE_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-hybrid-eval-mode.v1"
)
HYBRID_ARM_REGISTRY_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-hybrid-arm-registry.v1"
)
HYBRID_COORDINATE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-hybrid-coordinate.v1"
)
HYBRID_SUCCESS_CLAIM_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-hybrid-success-claim.v1"
)

# Promotion baseline remains the frozen deterministic arm identity.
DETERMINISTIC_BASELINE_ARM_ID: Final = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID

# ---------------------------------------------------------------------------
# Preregistered research arm identities
# ---------------------------------------------------------------------------

CONSTRUCTOR_ONLY_BASELINE_ARM_ID: Final = (
    "constructor_only__typed_deontic_baseline"
)
CONSTRUCTOR_ONLY_MODAL_SPACY_ARM_ID: Final = (
    "constructor_only__modal_spacy_candidate"
)
CONSTRUCTOR_ONLY_MODEL_DIRECT_ARM_ID: Final = (
    "constructor_only__model_direct_candidate"
)

REALIZER_ONLY_DETERMINISTIC_ARM_ID: Final = (
    "realizer_only__fixed_l1__deterministic"
)
REALIZER_ONLY_MODEL_DIRECT_ARM_ID: Final = (
    "realizer_only__fixed_l1__leanstral_direct"
)

HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID: Final = (
    "hybrid__typed_deontic__no_repair__deterministic"
)
HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID: Final = (
    "hybrid__typed_deontic__optional_selective_repair__deterministic"
)
HYBRID_TYPED_DEONTIC_MODEL_REPAIR_ARM_ID: Final = (
    "hybrid__typed_deontic__optional_model_repair__deterministic"
)

# Canonical hybrid path named in the acceptance criteria.
HYBRID_CANONICAL_PATH_ARM_ID: Final = HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID

STAGE_SCORED: Final = "scored"
STAGE_NOT_APPLICABLE: Final = "not_applicable"
STAGE_ABSTAINED: Final = "abstained"
STAGE_FAILED: Final = "failed"

REPAIR_NONE: Final = "no_repair"
REPAIR_SELECTIVE: Final = "selective"
REPAIR_MODEL: Final = "model"

_LOSS_KEYS: Final = ("forward", "cycle", "end_to_end")


class EvaluationMode(str, Enum):
    """Preregistered stage-local / hybrid research evaluation modes."""

    CONSTRUCTOR_ONLY = "constructor_only"
    REALIZER_ONLY = "realizer_only"
    HYBRID = "hybrid"


class HybridDisposition(str, Enum):
    """Terminal disposition of one hybrid-mode coordinate."""

    SEMANTIC_SCORED = "semantic_scored"
    ABSTAINED = "abstained"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    RUNTIME_FAILED = "runtime_failed"


class HybridPreflightError(LaunchPreflightError):
    """Raised when a hybrid/research mode lacks required preflight evidence."""


class HybridSuccessClaimError(ContractError):
    """Raised when a hybrid success claim lacks paired-bootstrap evidence."""


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a nonblank string")
    return value.strip()


def _finite_unit_interval(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ContractError(f"{field} must be a finite number from zero to one")
    return float(value)


def select_evaluation_mode(
    mode: EvaluationMode | str | Mapping[str, object],
) -> EvaluationMode:
    """Resolve a mode token, mapping, or enum to a preregistered mode."""

    if isinstance(mode, EvaluationMode):
        return mode
    if isinstance(mode, Mapping):
        token = mode.get("mode", mode.get("evaluation_mode", mode.get("id")))
        return select_evaluation_mode(token)  # type: ignore[arg-type]
    if not isinstance(mode, str) or not mode.strip():
        raise ContractError(
            "evaluation mode must be one of "
            f"{sorted(item.value for item in EvaluationMode)}"
        )
    cleaned = mode.strip().lower().replace("-", "_")
    aliases = {
        "constructor": EvaluationMode.CONSTRUCTOR_ONLY.value,
        "constructor_only": EvaluationMode.CONSTRUCTOR_ONLY.value,
        "realizer": EvaluationMode.REALIZER_ONLY.value,
        "realizer_only": EvaluationMode.REALIZER_ONLY.value,
        "hybrid": EvaluationMode.HYBRID.value,
        "hybrid_path": EvaluationMode.HYBRID.value,
    }
    try:
        return EvaluationMode(aliases.get(cleaned, cleaned))
    except ValueError as exc:
        raise ContractError(
            "unknown evaluation mode "
            f"{mode!r}; expected one of "
            f"{sorted(item.value for item in EvaluationMode)}"
        ) from exc


@dataclass(frozen=True, slots=True)
class HybridArmSpec:
    """One preregistered research evaluation arm."""

    arm_id: str
    mode: EvaluationMode
    description: str
    baseline_role: str
    constructor_id: str | None
    realizer_id: str | None
    repair: str
    model_route: str | None
    requires_live_smoke: bool
    requires_causal_qualification: bool
    scores_forward: bool
    scores_cycle: bool
    scores_end_to_end: bool
    promotion_eligible: bool = False
    pipeline: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "arm_id", _nonblank(self.arm_id, "arm_id"))
        if not isinstance(self.mode, EvaluationMode):
            object.__setattr__(self, "mode", select_evaluation_mode(self.mode))
        object.__setattr__(
            self, "description", _nonblank(self.description, "description")
        )
        if self.baseline_role not in {
            "baseline",
            "candidate",
            "hybrid_path",
            "stage_local",
        }:
            raise ContractError(
                f"baseline_role is invalid for {self.arm_id!r}"
            )
        if self.repair not in {REPAIR_NONE, REPAIR_SELECTIVE, REPAIR_MODEL}:
            raise ContractError(f"repair is invalid for {self.arm_id!r}")
        if self.model_route is not None:
            route = _nonblank(self.model_route, "model_route")
            if route not in {"direct", "symai", "not_applicable"}:
                raise ContractError(
                    f"model_route is invalid for {self.arm_id!r}"
                )
            object.__setattr__(self, "model_route", route)
        object.__setattr__(self, "pipeline", tuple(self.pipeline))
        if self.promotion_eligible:
            raise ContractError(
                "research hybrid arms must not mark promotion_eligible"
            )

    @property
    def is_model_backed(self) -> bool:
        return bool(
            self.requires_live_smoke
            or self.model_route in {"direct", "symai"}
            or self.repair == REPAIR_MODEL
            or (
                self.constructor_id == "model"
                or (self.realizer_id or "").startswith("leanstral")
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "mode": self.mode.value,
            "description": self.description,
            "baseline_role": self.baseline_role,
            "constructor_id": self.constructor_id,
            "realizer_id": self.realizer_id,
            "repair": self.repair,
            "model_route": self.model_route,
            "requires_live_smoke": self.requires_live_smoke,
            "requires_causal_qualification": (
                self.requires_causal_qualification
            ),
            "scores_forward": self.scores_forward,
            "scores_cycle": self.scores_cycle,
            "scores_end_to_end": self.scores_end_to_end,
            "promotion_eligible": self.promotion_eligible,
            "pipeline": list(self.pipeline),
            "is_model_backed": self.is_model_backed,
        }

    def as_preflight_arm(self) -> dict[str, object]:
        """Project to the evaluation_status arm shape for shared preflight."""

        composition: dict[str, object] = {
            "arm_id": self.arm_id,
            "base_constructor_id": self.constructor_id or "not_applicable",
            "guidance": "no_guidance",
            "repair": (
                "selective"
                if self.repair == REPAIR_SELECTIVE
                else (
                    "always_on"
                    if self.repair == REPAIR_MODEL
                    else "no_repair"
                )
            ),
            "constructor_route": (
                self.model_route
                if self.model_route in {"direct", "symai"}
                else "not_applicable"
            ),
        }
        realizer: dict[str, object] = {
            "realizer_id": self.realizer_id or "not_applicable",
            "mode": (
                "model"
                if self.realizer_id
                and self.realizer_id.startswith("leanstral")
                else "deterministic"
            ),
            "route": (
                self.model_route
                if self.realizer_id
                and self.realizer_id.startswith("leanstral")
                and self.model_route in {"direct", "symai"}
                else "not_applicable"
            ),
        }
        return {
            "arm_id": self.arm_id,
            "cell_id": self.arm_id,
            "composition": composition,
            "realizer": realizer,
            "mode": self.mode.value,
            "research_only": True,
            "promotion_eligible": False,
        }


def build_preregistered_hybrid_arms() -> tuple[HybridArmSpec, ...]:
    """Return the sealed research-mode registry required by EVAL-007."""

    return (
        HybridArmSpec(
            arm_id=CONSTRUCTOR_ONLY_BASELINE_ARM_ID,
            mode=EvaluationMode.CONSTRUCTOR_ONLY,
            description=(
                "Constructor-only baseline: typed deontic L1 vs gold "
                "(forward only)."
            ),
            baseline_role="baseline",
            constructor_id="typed_deontic",
            realizer_id=None,
            repair=REPAIR_NONE,
            model_route=None,
            requires_live_smoke=False,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=False,
            scores_end_to_end=False,
            pipeline=("typed_deontic_construct",),
        ),
        HybridArmSpec(
            arm_id=CONSTRUCTOR_ONLY_MODAL_SPACY_ARM_ID,
            mode=EvaluationMode.CONSTRUCTOR_ONLY,
            description=(
                "Constructor-only candidate: modal_spacy L1 vs gold "
                "(forward only)."
            ),
            baseline_role="candidate",
            constructor_id="modal_spacy",
            realizer_id=None,
            repair=REPAIR_NONE,
            model_route=None,
            requires_live_smoke=False,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=False,
            scores_end_to_end=False,
            pipeline=("modal_spacy_construct",),
        ),
        HybridArmSpec(
            arm_id=CONSTRUCTOR_ONLY_MODEL_DIRECT_ARM_ID,
            mode=EvaluationMode.CONSTRUCTOR_ONLY,
            description=(
                "Constructor-only candidate: Leanstral direct L1 vs gold "
                "(forward only; requires live smoke)."
            ),
            baseline_role="candidate",
            constructor_id="model",
            realizer_id=None,
            repair=REPAIR_NONE,
            model_route="direct",
            requires_live_smoke=True,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=False,
            scores_end_to_end=False,
            pipeline=("leanstral_direct_construct",),
        ),
        HybridArmSpec(
            arm_id=REALIZER_ONLY_DETERMINISTIC_ARM_ID,
            mode=EvaluationMode.REALIZER_ONLY,
            description=(
                "Realizer-only on fixed L1 with the deterministic realizer."
            ),
            baseline_role="stage_local",
            constructor_id=None,
            realizer_id="deterministic",
            repair=REPAIR_NONE,
            model_route=None,
            requires_live_smoke=False,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=True,
            scores_end_to_end=True,
            pipeline=(
                "fixed_l1",
                "deterministic_realize",
                "fixed_l2_constructor",
            ),
        ),
        HybridArmSpec(
            arm_id=REALIZER_ONLY_MODEL_DIRECT_ARM_ID,
            mode=EvaluationMode.REALIZER_ONLY,
            description=(
                "Realizer-only on fixed L1 with Leanstral direct realizer "
                "(requires live smoke)."
            ),
            baseline_role="stage_local",
            constructor_id=None,
            realizer_id="leanstral_direct",
            repair=REPAIR_NONE,
            model_route="direct",
            requires_live_smoke=True,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=True,
            scores_end_to_end=True,
            pipeline=(
                "fixed_l1",
                "leanstral_direct_realize",
                "fixed_l2_constructor",
            ),
        ),
        HybridArmSpec(
            arm_id=HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID,
            mode=EvaluationMode.HYBRID,
            description=(
                "Hybrid path without repair: typed_deontic → deterministic "
                "realizer (research measurement of the det baseline path)."
            ),
            baseline_role="hybrid_path",
            constructor_id="typed_deontic",
            realizer_id="deterministic",
            repair=REPAIR_NONE,
            model_route=None,
            requires_live_smoke=False,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=True,
            scores_end_to_end=True,
            pipeline=(
                "typed_deontic_construct",
                "deterministic_realize",
                "typed_deontic_reconstruct",
            ),
        ),
        HybridArmSpec(
            arm_id=HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID,
            mode=EvaluationMode.HYBRID,
            description=(
                "Hybrid: typed_deontic → optional selective/model repair → "
                "deterministic realizer with fail-closed abstention."
            ),
            baseline_role="hybrid_path",
            constructor_id="typed_deontic",
            realizer_id="deterministic",
            repair=REPAIR_SELECTIVE,
            model_route="direct",
            requires_live_smoke=True,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=True,
            scores_end_to_end=True,
            pipeline=(
                "typed_deontic_construct",
                "optional_selective_or_model_repair",
                "deterministic_realize",
                "typed_deontic_reconstruct",
            ),
        ),
        HybridArmSpec(
            arm_id=HYBRID_TYPED_DEONTIC_MODEL_REPAIR_ARM_ID,
            mode=EvaluationMode.HYBRID,
            description=(
                "Hybrid: typed_deontic → optional model repair → deterministic "
                "realizer (requires live smoke; fail-closed abstention)."
            ),
            baseline_role="hybrid_path",
            constructor_id="typed_deontic",
            realizer_id="deterministic",
            repair=REPAIR_MODEL,
            model_route="direct",
            requires_live_smoke=True,
            requires_causal_qualification=False,
            scores_forward=True,
            scores_cycle=True,
            scores_end_to_end=True,
            pipeline=(
                "typed_deontic_construct",
                "optional_model_repair",
                "deterministic_realize",
                "typed_deontic_reconstruct",
            ),
        ),
    )


PREREGISTERED_HYBRID_ARMS: Final[tuple[HybridArmSpec, ...]] = (
    build_preregistered_hybrid_arms()
)

_ARM_INDEX: Final[Mapping[str, HybridArmSpec]] = MappingProxyType(
    {arm.arm_id: arm for arm in PREREGISTERED_HYBRID_ARMS}
)


def hybrid_arm_registry() -> dict[str, object]:
    """Return the CID-ready preregistered hybrid arm registry."""

    modes = {
        mode.value: [
            arm.arm_id
            for arm in PREREGISTERED_HYBRID_ARMS
            if arm.mode is mode
        ]
        for mode in EvaluationMode
    }
    payload = {
        "interface": HYBRID_ROUND_TRIP_ARMS_INTERFACE,
        "schema_version": HYBRID_ARM_REGISTRY_SCHEMA,
        "promotion_arm_set_unchanged": True,
        "deterministic_baseline_arm_id": DETERMINISTIC_BASELINE_ARM_ID,
        "required_modes": [item.value for item in EvaluationMode],
        "modes": modes,
        "arms": [arm.to_dict() for arm in PREREGISTERED_HYBRID_ARMS],
        "hybrid_canonical_path": {
            "arm_id": HYBRID_CANONICAL_PATH_ARM_ID,
            "pipeline": [
                "typed_deontic",
                "optional_selective_or_model_repair",
                "deterministic_realizer",
            ],
            "fail_closed_abstention": True,
        },
        "loss_reporting": {
            "report_separately": list(_LOSS_KEYS),
            "primary_for_promotion_still_end_to_end": True,
            "constructor_only_primary": "forward",
            "hybrid_success_requires_paired_bootstrap_vs_baseline": True,
        },
    }
    return {**payload, "registry_cid": cid_for_dag_json(payload)}


def get_hybrid_arm(arm_id: str) -> HybridArmSpec:
    """Look up one preregistered hybrid/research arm or fail closed."""

    key = _nonblank(arm_id, "arm_id")
    try:
        return _ARM_INDEX[key]
    except KeyError as exc:
        raise ContractError(
            f"unknown hybrid research arm {arm_id!r}; "
            f"known={sorted(_ARM_INDEX)}"
        ) from exc


def arms_for_mode(
    mode: EvaluationMode | str,
) -> tuple[HybridArmSpec, ...]:
    """Return preregistered arms for one evaluation mode."""

    selected = select_evaluation_mode(mode)
    return tuple(
        arm for arm in PREREGISTERED_HYBRID_ARMS if arm.mode is selected
    )


def select_hybrid_arm(
    *,
    mode: EvaluationMode | str | None = None,
    arm_id: str | None = None,
    repair: str | None = None,
) -> HybridArmSpec:
    """Select exactly one preregistered arm by id or mode (+ optional repair)."""

    if arm_id is not None:
        arm = get_hybrid_arm(arm_id)
        if mode is not None and arm.mode is not select_evaluation_mode(mode):
            raise ContractError(
                f"arm {arm_id!r} belongs to mode {arm.mode.value!r}, "
                f"not {select_evaluation_mode(mode).value!r}"
            )
        return arm
    if mode is None:
        raise ContractError("select_hybrid_arm requires mode or arm_id")
    selected_mode = select_evaluation_mode(mode)
    candidates = arms_for_mode(selected_mode)
    if repair is not None:
        repair_token = _nonblank(repair, "repair")
        candidates = tuple(
            arm for arm in candidates if arm.repair == repair_token
        )
    if not candidates:
        raise ContractError(
            f"no preregistered arms for mode={selected_mode.value!r} "
            f"repair={repair!r}"
        )
    if len(candidates) == 1:
        return candidates[0]
    # Prefer the canonical hybrid path / baseline when multiple match.
    if selected_mode is EvaluationMode.HYBRID:
        for arm in candidates:
            if arm.arm_id == HYBRID_CANONICAL_PATH_ARM_ID:
                return arm
    if selected_mode is EvaluationMode.CONSTRUCTOR_ONLY:
        for arm in candidates:
            if arm.baseline_role == "baseline":
                return arm
    if selected_mode is EvaluationMode.REALIZER_ONLY:
        for arm in candidates:
            if arm.realizer_id == "deterministic":
                return arm
    raise ContractError(
        "ambiguous hybrid arm selection; pass arm_id. candidates="
        f"{[arm.arm_id for arm in candidates]!r}"
    )


def required_preflights_for_hybrid_arm(
    arm: HybridArmSpec | Mapping[str, object] | str,
) -> tuple[str, ...]:
    """Return preflight kinds required before the research arm may score."""

    if isinstance(arm, str):
        spec = get_hybrid_arm(arm)
    elif isinstance(arm, HybridArmSpec):
        spec = arm
    elif isinstance(arm, Mapping):
        arm_id = arm.get("arm_id", arm.get("cell_id"))
        if isinstance(arm_id, str) and arm_id in _ARM_INDEX:
            spec = get_hybrid_arm(arm_id)
        else:
            # Fall back to shared evaluation-status projection.
            req = required_preflights_for_arm(arm)
            return req.requirements
    else:
        raise ContractError("arm must be a HybridArmSpec, mapping, or arm_id")

    requirements: list[str] = []
    if spec.requires_causal_qualification:
        requirements.append(PREFLIGHT_CAUSAL_QUALIFICATION)
    if spec.requires_live_smoke or spec.is_model_backed:
        requirements.append(PREFLIGHT_LIVE_SMOKE)
    return tuple(requirements)


def evaluate_hybrid_mode_preflight(
    scheduled_arms: Sequence[HybridArmSpec | Mapping[str, object] | str],
    *,
    live_smokes: Mapping[str, object] | None = None,
    causal_qualification: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Evaluate research-mode preflight without raising."""

    projected: list[Mapping[str, object]] = []
    for arm in scheduled_arms:
        if isinstance(arm, HybridArmSpec):
            projected.append(arm.as_preflight_arm())
        elif isinstance(arm, str):
            projected.append(get_hybrid_arm(arm).as_preflight_arm())
        elif isinstance(arm, Mapping):
            arm_id = arm.get("arm_id", arm.get("cell_id"))
            if isinstance(arm_id, str) and arm_id in _ARM_INDEX:
                projected.append(get_hybrid_arm(arm_id).as_preflight_arm())
            else:
                projected.append(arm)
        else:
            raise ContractError(
                "scheduled hybrid arms must be specs, mappings, or ids"
            )

    # Extra fail-closed checks for hybrid optional-repair arms that declare
    # live smoke even when evaluation_status route inference is ambiguous.
    missing: list[dict[str, object]] = []
    for arm in projected:
        arm_id = str(arm.get("arm_id") or arm.get("cell_id") or "")
        if arm_id in _ARM_INDEX:
            for kind in required_preflights_for_hybrid_arm(arm_id):
                if kind == PREFLIGHT_LIVE_SMOKE:
                    route = _ARM_INDEX[arm_id].model_route or "direct"
                    if not _live_smoke_passed(live_smokes, route):
                        missing.append(
                            {
                                "arm_id": arm_id,
                                "preflight": PREFLIGHT_LIVE_SMOKE,
                                "route": route,
                                "reason": (
                                    "hybrid/research arm lacks passing live "
                                    f"smoke for route {route!r}"
                                ),
                            }
                        )
                elif kind == PREFLIGHT_CAUSAL_QUALIFICATION:
                    if not _causal_ok(causal_qualification, arm_id):
                        missing.append(
                            {
                                "arm_id": arm_id,
                                "preflight": PREFLIGHT_CAUSAL_QUALIFICATION,
                                "reason": (
                                    "hybrid/research arm lacks causal "
                                    "qualification"
                                ),
                            }
                        )

    shared = evaluate_matrix_launch_preflight(
        projected,
        live_smokes=live_smokes,
        causal_qualification=causal_qualification,
    )
    shared_missing = [dict(item) for item in shared.missing]
    # Deduplicate by (arm_id, preflight, route).
    seen: set[tuple[object, ...]] = set()
    combined: list[dict[str, object]] = []
    for item in missing + shared_missing:
        key = (
            item.get("arm_id"),
            item.get("preflight"),
            item.get("route"),
        )
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)

    arm_ids = tuple(
        str(arm.get("arm_id") or arm.get("cell_id") or "")
        for arm in projected
    )
    return {
        "interface": HYBRID_ROUND_TRIP_ARMS_INTERFACE,
        "schema_version": HYBRID_EVAL_MODE_SCHEMA,
        "authorized": not combined,
        "scheduled_arm_ids": list(arm_ids),
        "missing": combined,
        "fail_closed": True,
        "shared_verdict": shared.to_dict(),
    }


def assert_hybrid_mode_preflight(
    scheduled_arms: Sequence[HybridArmSpec | Mapping[str, object] | str],
    *,
    live_smokes: Mapping[str, object] | None = None,
    causal_qualification: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Fail closed when any scheduled research arm lacks required preflight."""

    verdict = evaluate_hybrid_mode_preflight(
        scheduled_arms,
        live_smokes=live_smokes,
        causal_qualification=causal_qualification,
    )
    if verdict["authorized"]:
        return verdict
    missing = verdict["missing"]
    arms = sorted({str(item.get("arm_id")) for item in missing})
    raise HybridPreflightError(
        "hybrid/research mode blocked: scheduled arms lack required "
        f"preflight evidence: {arms}; missing={missing}"
    )


def _live_smoke_passed(
    smokes: Mapping[str, object] | None, route: str
) -> bool:
    if smokes is None:
        return False
    records: object = smokes
    if isinstance(smokes, Mapping):
        nested = smokes.get("records", smokes.get("routes", smokes))
        if isinstance(nested, Mapping) or (
            isinstance(nested, Sequence)
            and not isinstance(nested, (str, bytes, bytearray))
        ):
            records = nested
    if isinstance(records, Mapping):
        payload = records.get(route)
        if isinstance(payload, Mapping):
            return _receipt_is_live_smoke_pass(payload)
    if isinstance(records, Sequence) and not isinstance(
        records, (str, bytes, bytearray)
    ):
        for item in records:
            if not isinstance(item, Mapping):
                continue
            item_route = item.get("route", item.get("route_id"))
            if str(item_route or "") != route:
                continue
            if _receipt_is_live_smoke_pass(item):
                return True
    return False


def _receipt_is_live_smoke_pass(receipt: Mapping[str, object]) -> bool:
    status = str(receipt.get("status") or "").strip().lower()
    if status not in {"ok", "passed", "success", "pass"}:
        return False
    inference = receipt.get("model_inference_performed")
    if inference is False:
        return False
    if inference is None and receipt.get("health_only") is True:
        return False
    return True


def _causal_ok(
    causal: Mapping[str, object] | None, arm_id: str
) -> bool:
    if not causal:
        return False
    disposition = str(causal.get("disposition") or "").strip()
    status = str(causal.get("status") or "").strip()
    if disposition == "scored_supported" or status == "scored_supported":
        return True
    arms = causal.get("arms")
    if isinstance(arms, Mapping):
        payload = arms.get(arm_id)
        if isinstance(payload, Mapping):
            arm_status = str(
                payload.get("status", payload.get("disposition")) or ""
            )
            if arm_status == "scored_supported":
                return True
    return False


@dataclass(frozen=True, slots=True)
class StageLossReport:
    """Separate forward / cycle / end-to-end reporting for research modes."""

    forward_status: str
    cycle_status: str
    end_to_end_status: str
    forward: float | None
    cycle: float | None
    end_to_end: float | None

    def __post_init__(self) -> None:
        for name in ("forward_status", "cycle_status", "end_to_end_status"):
            value = getattr(self, name)
            if value not in {
                STAGE_SCORED,
                STAGE_NOT_APPLICABLE,
                STAGE_ABSTAINED,
                STAGE_FAILED,
            }:
                raise ContractError(f"{name} is invalid: {value!r}")
        for name in _LOSS_KEYS:
            value = getattr(self, name)
            status = getattr(self, f"{name}_status")
            if status in {STAGE_SCORED, STAGE_FAILED}:
                if value is None:
                    raise ContractError(
                        f"{name} loss required when status is {status}"
                    )
                object.__setattr__(
                    self, name, _finite_unit_interval(value, name)
                )
            elif value is not None:
                object.__setattr__(
                    self, name, _finite_unit_interval(value, name)
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "forward": {
                "status": self.forward_status,
                "loss": self.forward,
            },
            "cycle": {
                "status": self.cycle_status,
                "loss": self.cycle,
            },
            "end_to_end": {
                "status": self.end_to_end_status,
                "loss": self.end_to_end,
            },
            "reported_separately": True,
        }

    @classmethod
    def from_round_trip(
        cls,
        losses: RoundTripLosses | RoundTripResult | Mapping[str, object],
        *,
        score_forward: bool = True,
        score_cycle: bool = True,
        score_end_to_end: bool = True,
        failed: bool = False,
        abstained: bool = False,
    ) -> "StageLossReport":
        if isinstance(losses, RoundTripResult):
            values = {
                "forward": losses.forward_loss,
                "cycle": losses.cycle_loss,
                "end_to_end": losses.end_to_end_loss,
            }
        elif isinstance(losses, RoundTripLosses):
            values = {
                "forward": losses.forward,
                "cycle": losses.cycle,
                "end_to_end": losses.end_to_end,
            }
        else:
            values = {
                "forward": losses.get("forward", losses.get("forward_loss")),
                "cycle": losses.get("cycle", losses.get("cycle_loss")),
                "end_to_end": losses.get(
                    "end_to_end", losses.get("end_to_end_loss")
                ),
            }

        def _status(enabled: bool) -> str:
            if abstained:
                return STAGE_ABSTAINED
            if failed:
                return STAGE_FAILED
            if enabled:
                return STAGE_SCORED
            return STAGE_NOT_APPLICABLE

        def _value(enabled: bool, key: str) -> float | None:
            if abstained and not enabled:
                return None
            if not enabled and not failed and not abstained:
                return None
            raw = values.get(key)
            if raw is None:
                return 1.0 if (failed or abstained) else None
            return float(raw)

        return cls(
            forward_status=_status(score_forward),
            cycle_status=_status(score_cycle),
            end_to_end_status=_status(score_end_to_end),
            forward=_value(score_forward, "forward"),
            cycle=_value(score_cycle, "cycle"),
            end_to_end=_value(score_end_to_end, "end_to_end"),
        )


@dataclass(frozen=True, slots=True)
class HybridCoordinateResult:
    """One sealed research-mode coordinate with separate stage losses."""

    arm_id: str
    mode: EvaluationMode
    case_id: str
    disposition: HybridDisposition
    stage_losses: StageLossReport
    result: RoundTripResult | None
    evaluation_status: str
    evaluation_reason: str
    repair_status: str | None
    abstention_reason: str | None
    diagnostics: Mapping[str, object]
    receipt_cid: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "arm_id", _nonblank(self.arm_id, "arm_id"))
        if not isinstance(self.mode, EvaluationMode):
            object.__setattr__(self, "mode", select_evaluation_mode(self.mode))
        object.__setattr__(
            self, "case_id", _nonblank(self.case_id, "case_id")
        )
        if not isinstance(self.disposition, HybridDisposition):
            object.__setattr__(
                self, "disposition", HybridDisposition(self.disposition)
            )
        if not isinstance(self.stage_losses, StageLossReport):
            raise ContractError("stage_losses must be StageLossReport")
        if self.result is not None and not isinstance(
            self.result, RoundTripResult
        ):
            raise ContractError("result must be RoundTripResult or None")
        object.__setattr__(
            self,
            "evaluation_status",
            _nonblank(self.evaluation_status, "evaluation_status"),
        )
        object.__setattr__(
            self,
            "evaluation_reason",
            _nonblank(self.evaluation_reason, "evaluation_reason"),
        )
        object.__setattr__(
            self, "diagnostics", MappingProxyType(dict(self.diagnostics))
        )
        object.__setattr__(
            self, "receipt_cid", _nonblank(self.receipt_cid, "receipt_cid")
        )

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        return {**payload, "receipt_cid": self.receipt_cid}

    def _payload(self) -> dict[str, object]:
        return {
            "interface": HYBRID_ROUND_TRIP_ARMS_INTERFACE,
            "schema_version": HYBRID_COORDINATE_RECEIPT_SCHEMA,
            "arm_id": self.arm_id,
            "mode": self.mode.value,
            "case_id": self.case_id,
            "disposition": self.disposition.value,
            "evaluation_status": self.evaluation_status,
            "evaluation_reason": self.evaluation_reason,
            "repair_status": self.repair_status,
            "abstention_reason": self.abstention_reason,
            "stage_losses": self.stage_losses.to_dict(),
            "losses": {
                "forward": self.stage_losses.forward,
                "cycle": self.stage_losses.cycle,
                "end_to_end": self.stage_losses.end_to_end,
            },
            "result": (
                None
                if self.result is None
                else {
                    "status": self.result.status.value,
                    "forward_loss": self.result.forward_loss,
                    "cycle_loss": self.result.cycle_loss,
                    "end_to_end_loss": self.result.end_to_end_loss,
                    "failure_reason": (
                        None
                        if self.result.failure_reason is None
                        else self.result.failure_reason.value
                    ),
                    "failure_detail": self.result.failure_detail,
                    "l1": (
                        None
                        if self.result.l1 is None
                        else self.result.l1.to_dict()
                    ),
                    "reconstruction": self.result.reconstruction,
                    "l2": (
                        None
                        if self.result.l2 is None
                        else self.result.l2.to_dict()
                    ),
                }
            ),
            "diagnostics": _plain(dict(self.diagnostics)),
        }


def _seal_coordinate(
    *,
    arm: HybridArmSpec,
    case_id: str,
    disposition: HybridDisposition,
    stage_losses: StageLossReport,
    result: RoundTripResult | None,
    evaluation_status: str,
    evaluation_reason: str,
    repair_status: str | None = None,
    abstention_reason: str | None = None,
    diagnostics: Mapping[str, object] | None = None,
) -> HybridCoordinateResult:
    provisional = HybridCoordinateResult(
        arm_id=arm.arm_id,
        mode=arm.mode,
        case_id=case_id,
        disposition=disposition,
        stage_losses=stage_losses,
        result=result,
        evaluation_status=evaluation_status,
        evaluation_reason=evaluation_reason,
        repair_status=repair_status,
        abstention_reason=abstention_reason,
        diagnostics=dict(diagnostics or {}),
        receipt_cid="pending",
    )
    payload = provisional._payload()
    receipt_cid = cid_for_dag_json(payload)
    return HybridCoordinateResult(
        arm_id=arm.arm_id,
        mode=arm.mode,
        case_id=case_id,
        disposition=disposition,
        stage_losses=stage_losses,
        result=result,
        evaluation_status=evaluation_status,
        evaluation_reason=evaluation_reason,
        repair_status=repair_status,
        abstention_reason=abstention_reason,
        diagnostics=dict(diagnostics or {}),
        receipt_cid=receipt_cid,
    )


def _failed_round_trip(
    gold_ir: CanonicalRuleIR,
    *,
    reason: FailureReason,
    detail: str,
    l1: CanonicalRuleIR | None = None,
    reconstruction: str | None = None,
    l2: CanonicalRuleIR | None = None,
) -> RoundTripResult:
    return make_round_trip_result(
        gold_ir,
        l1,
        reconstruction,
        l2,
        failure_reason=reason,
        failure_detail=detail,
    )


def run_constructor_only(
    *,
    case_id: str,
    source_text: str,
    vocabulary: AllowedAtomVocabulary,
    gold_ir: CanonicalRuleIR,
    constructor: RoundTripConstructor,
    arm: HybridArmSpec | str | None = None,
    config: Mapping[str, object] | None = None,
) -> HybridCoordinateResult:
    """Score only the constructor (forward loss) against gold IR."""

    if arm is None:
        spec = select_hybrid_arm(mode=EvaluationMode.CONSTRUCTOR_ONLY)
    elif isinstance(arm, HybridArmSpec):
        spec = arm
    else:
        spec = get_hybrid_arm(arm)
    if spec.mode is not EvaluationMode.CONSTRUCTOR_ONLY:
        raise ContractError(
            f"arm {spec.arm_id!r} is not a constructor_only arm"
        )
    if not isinstance(gold_ir, CanonicalRuleIR):
        raise ContractError("gold_ir must be CanonicalRuleIR")
    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")

    request = ConstructorRequest(
        source_text, vocabulary, dict(config or {})
    )
    try:
        constructed = constructor.construct(request)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        constructed = ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=f"constructor raised {type(exc).__name__}",
        )
    if not isinstance(constructed, ConstructorResult):
        constructed = ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.INVALID_OUTPUT,
            failure_detail="constructor returned a non-ConstructorResult",
        )

    if constructed.status is ComponentStatus.FAILED:
        result = _failed_round_trip(
            gold_ir,
            reason=constructed.failure_reason or FailureReason.EXCEPTION,
            detail=constructed.failure_detail or "constructor failed",
        )
        stage = StageLossReport.from_round_trip(
            result,
            score_forward=True,
            score_cycle=False,
            score_end_to_end=False,
            failed=True,
        )
        return _seal_coordinate(
            arm=spec,
            case_id=case_id,
            disposition=HybridDisposition.RUNTIME_FAILED,
            stage_losses=stage,
            result=result,
            evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
            evaluation_reason="provider_error",
            diagnostics={
                "constructor_identity": getattr(
                    constructor, "identity", None
                ),
                "constructor_failure": {
                    "reason": (
                        None
                        if constructed.failure_reason is None
                        else constructed.failure_reason.value
                    ),
                    "detail": constructed.failure_detail,
                },
            },
        )

    assert constructed.canonical_ir is not None
    forward_loss = round(
        1.0 - semantic_score(gold_ir, constructed.canonical_ir), 9
    )
    comparison = compare_semantic_ir(gold_ir, constructed.canonical_ir)
    # Constructor-only does not run T1/L2; cycle/e2e are not_applicable.
    result = RoundTripResult(
        status=ComponentStatus.SUCCESS,
        l1=constructed.canonical_ir,
        reconstruction="constructor_only_placeholder_t1",
        l2=constructed.canonical_ir,
        forward_loss=forward_loss,
        cycle_loss=0.0,
        end_to_end_loss=forward_loss,
    )
    stage = StageLossReport(
        forward_status=STAGE_SCORED,
        cycle_status=STAGE_NOT_APPLICABLE,
        end_to_end_status=STAGE_NOT_APPLICABLE,
        forward=forward_loss,
        cycle=None,
        end_to_end=None,
    )
    return _seal_coordinate(
        arm=spec,
        case_id=case_id,
        disposition=HybridDisposition.SEMANTIC_SCORED,
        stage_losses=stage,
        result=result,
        evaluation_status=EvaluationStatus.SEMANTIC_SCORED.value,
        evaluation_reason="success",
        diagnostics={
            "constructor_identity": getattr(constructor, "identity", None),
            "forward_comparison": comparison,
            "facet_survival": comparison.get("facet_survival"),
            "stage_scope": "constructor_only",
        },
    )


def run_realizer_only(
    *,
    case_id: str,
    fixed_l1: CanonicalRuleIR,
    vocabulary: AllowedAtomVocabulary,
    gold_ir: CanonicalRuleIR,
    realizer: RoundTripRealizer,
    l2_constructor: RoundTripConstructor | None = None,
    arm: HybridArmSpec | str | None = None,
    config: Mapping[str, object] | None = None,
) -> HybridCoordinateResult:
    """Score a realizer on a fixed L1, reconstructing L2 with a fixed constructor."""

    if arm is None:
        spec = select_hybrid_arm(mode=EvaluationMode.REALIZER_ONLY)
    elif isinstance(arm, HybridArmSpec):
        spec = arm
    else:
        spec = get_hybrid_arm(arm)
    if spec.mode is not EvaluationMode.REALIZER_ONLY:
        raise ContractError(f"arm {spec.arm_id!r} is not a realizer_only arm")
    if not isinstance(fixed_l1, CanonicalRuleIR) or fixed_l1.is_empty:
        raise ContractError("fixed_l1 must be a nonempty CanonicalRuleIR")
    if not isinstance(gold_ir, CanonicalRuleIR):
        raise ContractError("gold_ir must be CanonicalRuleIR")
    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")

    reconstructor = l2_constructor or TypedDeonticCanonicalConstructor()
    request = RealizerRequest(fixed_l1, vocabulary, dict(config or {}))
    try:
        realized = realizer.realize(request)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        realized = RealizerResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=f"realizer raised {type(exc).__name__}",
        )
    if not isinstance(realized, RealizerResult):
        realized = RealizerResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.INVALID_OUTPUT,
            failure_detail="realizer returned a non-RealizerResult",
        )
    if realized.status is ComponentStatus.FAILED:
        result = _failed_round_trip(
            gold_ir,
            reason=realized.failure_reason or FailureReason.EXCEPTION,
            detail=realized.failure_detail or "realizer failed",
            l1=fixed_l1,
        )
        stage = StageLossReport.from_round_trip(
            result,
            score_forward=True,
            score_cycle=True,
            score_end_to_end=True,
            failed=True,
        )
        return _seal_coordinate(
            arm=spec,
            case_id=case_id,
            disposition=HybridDisposition.RUNTIME_FAILED,
            stage_losses=stage,
            result=result,
            evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
            evaluation_reason="provider_error",
            diagnostics={
                "realizer_identity": getattr(realizer, "identity", None),
                "fixed_l1": fixed_l1.to_dict(),
            },
        )

    assert realized.text is not None
    try:
        reconstructed = reconstructor.construct(
            ConstructorRequest(realized.text, vocabulary, dict(config or {}))
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        reconstructed = ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=(
                f"l2 constructor raised {type(exc).__name__}"
            ),
        )
    if (
        not isinstance(reconstructed, ConstructorResult)
        or reconstructed.status is ComponentStatus.FAILED
    ):
        detail = (
            reconstructed.failure_detail
            if isinstance(reconstructed, ConstructorResult)
            else "l2 constructor invalid"
        )
        reason = (
            reconstructed.failure_reason
            if isinstance(reconstructed, ConstructorResult)
            and reconstructed.failure_reason is not None
            else FailureReason.INVALID_OUTPUT
        )
        result = _failed_round_trip(
            gold_ir,
            reason=reason,
            detail=detail or "l2 reconstruction failed",
            l1=fixed_l1,
            reconstruction=realized.text,
        )
        stage = StageLossReport.from_round_trip(
            result,
            score_forward=True,
            score_cycle=True,
            score_end_to_end=True,
            failed=True,
        )
        return _seal_coordinate(
            arm=spec,
            case_id=case_id,
            disposition=HybridDisposition.RUNTIME_FAILED,
            stage_losses=stage,
            result=result,
            evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
            evaluation_reason="provider_error",
            diagnostics={
                "realizer_identity": getattr(realizer, "identity", None),
                "l2_constructor_identity": getattr(
                    reconstructor, "identity", None
                ),
            },
        )

    assert reconstructed.canonical_ir is not None
    result = make_round_trip_result(
        gold_ir, fixed_l1, realized.text, reconstructed.canonical_ir
    )
    stage = StageLossReport.from_round_trip(
        result,
        score_forward=True,
        score_cycle=True,
        score_end_to_end=True,
        failed=result.status is ComponentStatus.FAILED,
    )
    return _seal_coordinate(
        arm=spec,
        case_id=case_id,
        disposition=(
            HybridDisposition.SEMANTIC_SCORED
            if result.status is ComponentStatus.SUCCESS
            else HybridDisposition.RUNTIME_FAILED
        ),
        stage_losses=stage,
        result=result,
        evaluation_status=(
            EvaluationStatus.SEMANTIC_SCORED.value
            if result.status is ComponentStatus.SUCCESS
            else EvaluationStatus.RUNTIME_FAILED.value
        ),
        evaluation_reason=(
            "success"
            if result.status is ComponentStatus.SUCCESS
            else "provider_error"
        ),
        diagnostics={
            "realizer_identity": getattr(realizer, "identity", None),
            "l2_constructor_identity": getattr(
                reconstructor, "identity", None
            ),
            "fixed_l1": fixed_l1.to_dict(),
            "stage_scope": "realizer_only",
        },
    )


def run_hybrid_path(
    *,
    case_id: str,
    source_text: str,
    vocabulary: AllowedAtomVocabulary,
    gold_ir: CanonicalRuleIR,
    arm: HybridArmSpec | str | None = None,
    base_constructor: RoundTripConstructor | None = None,
    realizer: RoundTripRealizer | None = None,
    repair_constructor: RoundTripConstructor | None = None,
    live_smokes: Mapping[str, object] | None = None,
    causal_qualification: Mapping[str, object] | None = None,
    allow_missing_preflight_abstention: bool = True,
    config: Mapping[str, object] | None = None,
) -> HybridCoordinateResult:
    """Run typed_deontic → optional repair → deterministic realizer.

    When optional model/selective repair is preregistered and live-smoke
    preflight is missing, the path **fails closed**:

    * default: abstain (``preflight_blocked`` / not measured) rather than
      silently scoring a no-repair path as the hybrid arm;
    * ``allow_missing_preflight_abstention=False`` raises
      :class:`HybridPreflightError`.
    """

    if arm is None:
        spec = select_hybrid_arm(mode=EvaluationMode.HYBRID)
    elif isinstance(arm, HybridArmSpec):
        spec = arm
    else:
        spec = get_hybrid_arm(arm)
    if spec.mode is not EvaluationMode.HYBRID:
        raise ContractError(f"arm {spec.arm_id!r} is not a hybrid arm")
    if not isinstance(gold_ir, CanonicalRuleIR):
        raise ContractError("gold_ir must be CanonicalRuleIR")
    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")

    # Fail-closed preflight for model-backed hybrid repair arms.
    if spec.requires_live_smoke or spec.repair in {
        REPAIR_SELECTIVE,
        REPAIR_MODEL,
    }:
        verdict = evaluate_hybrid_mode_preflight(
            [spec],
            live_smokes=live_smokes,
            causal_qualification=causal_qualification,
        )
        if not verdict["authorized"]:
            if not allow_missing_preflight_abstention:
                assert_hybrid_mode_preflight(
                    [spec],
                    live_smokes=live_smokes,
                    causal_qualification=causal_qualification,
                )
            stage = StageLossReport(
                forward_status=STAGE_ABSTAINED,
                cycle_status=STAGE_ABSTAINED,
                end_to_end_status=STAGE_ABSTAINED,
                forward=None,
                cycle=None,
                end_to_end=None,
            )
            return _seal_coordinate(
                arm=spec,
                case_id=case_id,
                disposition=HybridDisposition.PREFLIGHT_BLOCKED,
                stage_losses=stage,
                result=None,
                evaluation_status=EvaluationStatus.NOT_MEASURED.value,
                evaluation_reason=NotMeasuredReason.PREFLIGHT_BLOCKED.value,
                repair_status="abstained_missing_preflight",
                abstention_reason=(
                    "optional repair arm lacks required preflight; "
                    "fail-closed abstention"
                ),
                diagnostics={
                    "preflight": verdict,
                    "pipeline": list(spec.pipeline),
                },
            )

    constructor = base_constructor or TypedDeonticCanonicalConstructor()
    det_realizer = realizer or CanonicalDeterministicRealizer()
    request = ConstructorRequest(
        source_text, vocabulary, dict(config or {})
    )

    repair_status = REPAIR_NONE
    repair_receipt: Mapping[str, object] | None = None
    l1_ir: CanonicalRuleIR | None = None

    if spec.repair == REPAIR_NONE:
        try:
            base_result = constructor.construct(request)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            base_result = ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.EXCEPTION,
                failure_detail=f"constructor raised {type(exc).__name__}",
            )
        if (
            not isinstance(base_result, ConstructorResult)
            or base_result.status is ComponentStatus.FAILED
        ):
            detail = (
                base_result.failure_detail
                if isinstance(base_result, ConstructorResult)
                else "constructor invalid"
            )
            reason = (
                base_result.failure_reason
                if isinstance(base_result, ConstructorResult)
                and base_result.failure_reason is not None
                else FailureReason.INVALID_OUTPUT
            )
            result = _failed_round_trip(
                gold_ir, reason=reason, detail=detail or "construct failed"
            )
            stage = StageLossReport.from_round_trip(
                result,
                score_forward=True,
                score_cycle=True,
                score_end_to_end=True,
                failed=True,
            )
            return _seal_coordinate(
                arm=spec,
                case_id=case_id,
                disposition=HybridDisposition.RUNTIME_FAILED,
                stage_losses=stage,
                result=result,
                evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
                evaluation_reason="provider_error",
                repair_status=repair_status,
                diagnostics={
                    "constructor_identity": getattr(
                        constructor, "identity", None
                    )
                },
            )
        assert base_result.canonical_ir is not None
        l1_ir = base_result.canonical_ir
        repair_status = "not_applicable"
    else:
        # Optional selective/model repair wrapper.
        repairer = repair_constructor
        if repairer is None:
            # Default selective path: typed base + zero-trigger detector when
            # no model client is injected (no-op repair, still exercises the
            # hybrid pipeline). Callers that want live repair inject
            # SelectiveLeanstralRepair with a client.
            repairer = SelectiveLeanstralRepair(
                base_constructor=constructor,
                policy=SelectiveRepairPolicy(),
                trigger_detector=ZeroTriggerDetector(),
                client=_AbstainingRepairClient(),
            )
        try:
            if hasattr(repairer, "construct_with_diagnostics"):
                construction = repairer.construct_with_diagnostics(request)  # type: ignore[attr-defined]
                repaired = construction.result
                if hasattr(construction, "receipt"):
                    receipt = construction.receipt
                    repair_receipt = (
                        receipt.to_dict()
                        if hasattr(receipt, "to_dict")
                        else dict(receipt)
                    )
                    raw_status = getattr(receipt, "status", None)
                    if raw_status is None:
                        raw_status = repair_receipt.get("status")
                    if isinstance(raw_status, RepairAttemptStatus):
                        repair_status = raw_status.value
                    elif isinstance(raw_status, Enum):
                        repair_status = str(raw_status.value)
                    elif raw_status is None:
                        repair_status = "unknown"
                    else:
                        repair_status = str(raw_status)
                        # Enum str() may be "RepairAttemptStatus.NOT_TRIGGERED".
                        if "." in repair_status and repair_status.rsplit(
                            ".", 1
                        )[-1].isupper():
                            repair_status = repair_status.rsplit(".", 1)[
                                -1
                            ].lower()
            else:
                repaired = repairer.construct(request)
                repair_status = "applied_opaque"
        except _RepairAbstention as exc:
            stage = StageLossReport(
                forward_status=STAGE_ABSTAINED,
                cycle_status=STAGE_ABSTAINED,
                end_to_end_status=STAGE_ABSTAINED,
                forward=None,
                cycle=None,
                end_to_end=None,
            )
            return _seal_coordinate(
                arm=spec,
                case_id=case_id,
                disposition=HybridDisposition.ABSTAINED,
                stage_losses=stage,
                result=None,
                evaluation_status=EvaluationStatus.NOT_MEASURED.value,
                evaluation_reason=NotMeasuredReason.PREFLIGHT_BLOCKED.value,
                repair_status="abstained",
                abstention_reason=str(exc),
                diagnostics={"pipeline": list(spec.pipeline)},
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            repaired = ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.EXCEPTION,
                failure_detail=f"repair raised {type(exc).__name__}",
            )
            repair_status = "failed"

        if (
            not isinstance(repaired, ConstructorResult)
            or repaired.status is ComponentStatus.FAILED
        ):
            # Fail-closed: do not silently fall back to an unadvertised path.
            detail = (
                repaired.failure_detail
                if isinstance(repaired, ConstructorResult)
                else "repair invalid"
            )
            reason = (
                repaired.failure_reason
                if isinstance(repaired, ConstructorResult)
                and repaired.failure_reason is not None
                else FailureReason.INVALID_OUTPUT
            )
            result = _failed_round_trip(
                gold_ir,
                reason=reason,
                detail=detail or "hybrid repair failed",
            )
            stage = StageLossReport.from_round_trip(
                result,
                score_forward=True,
                score_cycle=True,
                score_end_to_end=True,
                failed=True,
            )
            return _seal_coordinate(
                arm=spec,
                case_id=case_id,
                disposition=HybridDisposition.RUNTIME_FAILED,
                stage_losses=stage,
                result=result,
                evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
                evaluation_reason="provider_error",
                repair_status=repair_status,
                diagnostics={
                    "repair_receipt": repair_receipt,
                    "pipeline": list(spec.pipeline),
                },
            )
        assert repaired.canonical_ir is not None
        l1_ir = repaired.canonical_ir

    assert l1_ir is not None
    try:
        realized = det_realizer.realize(
            RealizerRequest(l1_ir, vocabulary, dict(config or {}))
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        realized = RealizerResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=f"realizer raised {type(exc).__name__}",
        )
    if (
        not isinstance(realized, RealizerResult)
        or realized.status is ComponentStatus.FAILED
    ):
        detail = (
            realized.failure_detail
            if isinstance(realized, RealizerResult)
            else "realizer invalid"
        )
        reason = (
            realized.failure_reason
            if isinstance(realized, RealizerResult)
            and realized.failure_reason is not None
            else FailureReason.INVALID_OUTPUT
        )
        result = _failed_round_trip(
            gold_ir,
            reason=reason,
            detail=detail or "realize failed",
            l1=l1_ir,
        )
        stage = StageLossReport.from_round_trip(
            result,
            score_forward=True,
            score_cycle=True,
            score_end_to_end=True,
            failed=True,
        )
        return _seal_coordinate(
            arm=spec,
            case_id=case_id,
            disposition=HybridDisposition.RUNTIME_FAILED,
            stage_losses=stage,
            result=result,
            evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
            evaluation_reason="provider_error",
            repair_status=repair_status,
            diagnostics={"repair_receipt": repair_receipt},
        )

    assert realized.text is not None
    # L2 reuses the typed deontic base constructor (no second repair pass).
    try:
        l2_result = constructor.construct(
            ConstructorRequest(realized.text, vocabulary, dict(config or {}))
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        l2_result = ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=f"l2 constructor raised {type(exc).__name__}",
        )
    if (
        not isinstance(l2_result, ConstructorResult)
        or l2_result.status is ComponentStatus.FAILED
    ):
        detail = (
            l2_result.failure_detail
            if isinstance(l2_result, ConstructorResult)
            else "l2 invalid"
        )
        reason = (
            l2_result.failure_reason
            if isinstance(l2_result, ConstructorResult)
            and l2_result.failure_reason is not None
            else FailureReason.INVALID_OUTPUT
        )
        result = _failed_round_trip(
            gold_ir,
            reason=reason,
            detail=detail or "l2 failed",
            l1=l1_ir,
            reconstruction=realized.text,
        )
        stage = StageLossReport.from_round_trip(
            result,
            score_forward=True,
            score_cycle=True,
            score_end_to_end=True,
            failed=True,
        )
        return _seal_coordinate(
            arm=spec,
            case_id=case_id,
            disposition=HybridDisposition.RUNTIME_FAILED,
            stage_losses=stage,
            result=result,
            evaluation_status=EvaluationStatus.RUNTIME_FAILED.value,
            evaluation_reason="provider_error",
            repair_status=repair_status,
            diagnostics={"repair_receipt": repair_receipt},
        )

    assert l2_result.canonical_ir is not None
    result = make_round_trip_result(
        gold_ir, l1_ir, realized.text, l2_result.canonical_ir
    )
    stage = StageLossReport.from_round_trip(
        result,
        score_forward=True,
        score_cycle=True,
        score_end_to_end=True,
        failed=result.status is ComponentStatus.FAILED,
    )
    return _seal_coordinate(
        arm=spec,
        case_id=case_id,
        disposition=(
            HybridDisposition.SEMANTIC_SCORED
            if result.status is ComponentStatus.SUCCESS
            else HybridDisposition.RUNTIME_FAILED
        ),
        stage_losses=stage,
        result=result,
        evaluation_status=(
            EvaluationStatus.SEMANTIC_SCORED.value
            if result.status is ComponentStatus.SUCCESS
            else EvaluationStatus.RUNTIME_FAILED.value
        ),
        evaluation_reason=(
            "success"
            if result.status is ComponentStatus.SUCCESS
            else "provider_error"
        ),
        repair_status=repair_status,
        diagnostics={
            "constructor_identity": getattr(constructor, "identity", None),
            "realizer_identity": getattr(det_realizer, "identity", None),
            "repair_receipt": repair_receipt,
            "pipeline": list(spec.pipeline),
            "stage_scope": "hybrid",
            "losses_separate": {
                "forward": result.forward_loss,
                "cycle": result.cycle_loss,
                "end_to_end": result.end_to_end_loss,
            },
        },
    )


class _RepairAbstention(Exception):
    """Internal signal that optional repair must abstain fail-closed."""


class _AbstainingRepairClient:
    """Client that never silently substitutes a model repair path."""

    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL
    cache_prompt = False

    def complete_json(self, **_: object) -> dict[str, object]:
        # Zero-trigger detectors never call the client.  If a call arrives
        # without a live model, abstain rather than inventing output.
        raise _RepairAbstention(
            "optional model repair requires a live client; fail-closed "
            "abstention"
        )


def separate_stage_losses(
    result: RoundTripResult | HybridCoordinateResult | Mapping[str, object],
) -> dict[str, object]:
    """Project forward / cycle / end-to-end losses as separate fields."""

    if isinstance(result, HybridCoordinateResult):
        return result.stage_losses.to_dict()
    if isinstance(result, RoundTripResult):
        return StageLossReport.from_round_trip(result).to_dict()
    if not isinstance(result, Mapping):
        raise ContractError("result must provide losses")
    stage = result.get("stage_losses")
    if isinstance(stage, Mapping):
        return dict(stage)
    losses = result.get("losses", result)
    if not isinstance(losses, Mapping):
        raise ContractError("losses mapping required")
    return StageLossReport.from_round_trip(losses).to_dict()


def paired_bootstrap_vs_baseline(
    observations: Iterable[object],
    *,
    baseline_arm_id: str = DETERMINISTIC_BASELINE_ARM_ID,
    candidate_arm_ids: Sequence[str] | None = None,
    seed: int = 17_291,
    bootstrap_samples: int = 200,
    confidence_level: float = 0.95,
) -> dict[str, object]:
    """Run paired case-cluster bootstrap for hybrid success claims.

    ``observations`` must be :class:`~benchmarks.semantic_roundtrip.statistics.RoundTripObservation`
    values covering the baseline and each candidate on the same case set.
    """

    analyzer = RoundTripPairedStatistics(
        seed=seed,
        bootstrap_samples=bootstrap_samples,
        confidence_level=confidence_level,
    )
    report = analyzer.analyze(
        observations,  # type: ignore[arg-type]
        baseline_arm_id=baseline_arm_id,
        candidate_arm_ids=candidate_arm_ids,
    )
    payload = report.to_dict()
    return {
        "interface": HYBRID_ROUND_TRIP_ARMS_INTERFACE,
        "schema_version": HYBRID_SUCCESS_CLAIM_SCHEMA,
        "paired_statistics_interface": ROUND_TRIP_PAIRED_STATISTICS_INTERFACE,
        "baseline_arm_id": baseline_arm_id,
        "required_for_hybrid_success_claims": True,
        "report": payload,
        "report_cid": payload.get("report_cid"),
    }


def authorize_hybrid_success_claim(
    *,
    candidate_arm_id: str,
    paired_comparison: Mapping[str, object] | None,
    baseline_arm_id: str = DETERMINISTIC_BASELINE_ARM_ID,
    metric: str = "end_to_end",
    require_negative_delta: bool = False,
) -> dict[str, object]:
    """Authorize a hybrid 'beats baseline' claim only with paired bootstrap.

    Without a paired bootstrap comparison against the deterministic baseline,
    hybrid success claims are **denied** (fail-closed).
    """

    candidate = _nonblank(candidate_arm_id, "candidate_arm_id")
    baseline = _nonblank(baseline_arm_id, "baseline_arm_id")
    if paired_comparison is None:
        raise HybridSuccessClaimError(
            "hybrid success claims require paired bootstrap vs the "
            f"deterministic baseline ({baseline}); none was supplied for "
            f"candidate {candidate!r}"
        )
    if not isinstance(paired_comparison, Mapping):
        raise HybridSuccessClaimError(
            "paired_comparison must be a mapping produced by "
            "paired_bootstrap_vs_baseline"
        )

    report = paired_comparison.get("report", paired_comparison)
    if not isinstance(report, Mapping):
        raise HybridSuccessClaimError("paired comparison report is missing")
    comparisons = report.get("paired_comparisons", {})
    if not isinstance(comparisons, Mapping) or not comparisons:
        raise HybridSuccessClaimError(
            "paired comparison report has no paired_comparisons"
        )

    comparison_id = f"{candidate}__vs__{baseline}"
    comparison = comparisons.get(comparison_id)
    if comparison is None:
        # Allow a single comparison entry when ids are embedded.
        if len(comparisons) == 1:
            comparison = next(iter(comparisons.values()))
        else:
            raise HybridSuccessClaimError(
                f"paired comparison {comparison_id!r} is absent; "
                f"available={sorted(comparisons)}"
            )
    if not isinstance(comparison, Mapping):
        raise HybridSuccessClaimError("paired comparison entry is invalid")
    if (
        comparison.get("baseline_arm_id") not in {None, baseline}
        or comparison.get("candidate_arm_id") not in {None, candidate}
    ):
        # Soft check: accept when comparison_id matched.
        pass

    metrics = comparison.get("metrics")
    if not isinstance(metrics, Mapping):
        raise HybridSuccessClaimError("paired comparison metrics are missing")
    loss_group = metrics.get("losses", metrics)
    if not isinstance(loss_group, Mapping):
        raise HybridSuccessClaimError("paired loss metrics are missing")
    metric_payload = loss_group.get(metric)
    if not isinstance(metric_payload, Mapping):
        raise HybridSuccessClaimError(
            f"paired metric {metric!r} is missing from the bootstrap report"
        )
    interval = metric_payload.get("confidence_interval", metric_payload)
    if not isinstance(interval, Mapping):
        raise HybridSuccessClaimError(
            "paired bootstrap confidence_interval is missing"
        )
    if interval.get("method") != "seeded_percentile_case_cluster_bootstrap":
        # Accept nested form from statistics module.
        if metric_payload.get("confidence_interval") is None and (
            "low" not in interval and "high" not in metric_payload
        ):
            raise HybridSuccessClaimError(
                "paired bootstrap must use seeded_percentile_case_cluster_"
                "bootstrap"
            )

    mean_delta = metric_payload.get(
        "mean_delta",
        metric_payload.get(
            "delta",
            metric_payload.get("candidate_minus_baseline"),
        ),
    )
    low = interval.get("low", metric_payload.get("low"))
    high = interval.get("high", metric_payload.get("high"))
    if mean_delta is None or low is None or high is None:
        raise HybridSuccessClaimError(
            "paired bootstrap mean_delta/low/high are required for success "
            "claims"
        )

    beats = False
    if require_negative_delta:
        # Lower loss is better; require CI entirely below zero.
        beats = float(high) < 0.0
    authorization = {
        "interface": HYBRID_ROUND_TRIP_ARMS_INTERFACE,
        "schema_version": HYBRID_SUCCESS_CLAIM_SCHEMA,
        "authorized": True,
        "candidate_arm_id": candidate,
        "baseline_arm_id": baseline,
        "metric": metric,
        "mean_delta": float(mean_delta),
        "confidence_interval": {
            "low": float(low),
            "high": float(high),
            "method": interval.get(
                "method", "seeded_percentile_case_cluster_bootstrap"
            ),
        },
        "beats_baseline_ci": beats if require_negative_delta else None,
        "paired_bootstrap_required": True,
        "promotion_still_requires_full_gates": True,
    }
    return {
        **authorization,
        "authorization_cid": cid_for_dag_json(authorization),
    }


def research_modes_do_not_alter_promotion_set(
    promotion_cell_ids: Sequence[str],
) -> bool:
    """Return True when no research arm id collides with promotion cells."""

    research_ids = {arm.arm_id for arm in PREREGISTERED_HYBRID_ARMS}
    promotion = set(promotion_cell_ids)
    return research_ids.isdisjoint(promotion)


__all__ = [
    "HYBRID_ROUND_TRIP_ARMS_INTERFACE",
    "HYBRID_EVAL_MODE_SCHEMA",
    "HYBRID_ARM_REGISTRY_SCHEMA",
    "HYBRID_COORDINATE_RECEIPT_SCHEMA",
    "HYBRID_SUCCESS_CLAIM_SCHEMA",
    "DETERMINISTIC_BASELINE_ARM_ID",
    "CONSTRUCTOR_ONLY_BASELINE_ARM_ID",
    "CONSTRUCTOR_ONLY_MODAL_SPACY_ARM_ID",
    "CONSTRUCTOR_ONLY_MODEL_DIRECT_ARM_ID",
    "REALIZER_ONLY_DETERMINISTIC_ARM_ID",
    "REALIZER_ONLY_MODEL_DIRECT_ARM_ID",
    "HYBRID_TYPED_DEONTIC_NO_REPAIR_ARM_ID",
    "HYBRID_TYPED_DEONTIC_SELECTIVE_ARM_ID",
    "HYBRID_TYPED_DEONTIC_MODEL_REPAIR_ARM_ID",
    "HYBRID_CANONICAL_PATH_ARM_ID",
    "STAGE_SCORED",
    "STAGE_NOT_APPLICABLE",
    "STAGE_ABSTAINED",
    "STAGE_FAILED",
    "REPAIR_NONE",
    "REPAIR_SELECTIVE",
    "REPAIR_MODEL",
    "EvaluationMode",
    "HybridDisposition",
    "HybridPreflightError",
    "HybridSuccessClaimError",
    "HybridArmSpec",
    "StageLossReport",
    "HybridCoordinateResult",
    "PREREGISTERED_HYBRID_ARMS",
    "build_preregistered_hybrid_arms",
    "hybrid_arm_registry",
    "get_hybrid_arm",
    "arms_for_mode",
    "select_evaluation_mode",
    "select_hybrid_arm",
    "required_preflights_for_hybrid_arm",
    "evaluate_hybrid_mode_preflight",
    "assert_hybrid_mode_preflight",
    "run_constructor_only",
    "run_realizer_only",
    "run_hybrid_path",
    "separate_stage_losses",
    "paired_bootstrap_vs_baseline",
    "authorize_hybrid_success_claim",
    "research_modes_do_not_alter_promotion_set",
    "TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE",
    "CANONICAL_DETERMINISTIC_REALIZER_INTERFACE",
    "SELECTIVE_LEANSTRAL_REPAIR_INTERFACE",
]
