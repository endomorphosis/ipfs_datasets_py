"""Plateau residual forensics catalog (case × facet).

``PlateauResidualCatalog@1`` is the machine-readable bridge between the sealed
typed_deontic deterministic baseline L1 and downstream selective-repair
triggers / Codex packets.  Residuals are computed with the same weighted exact-
assignment score used by the composition protocol (see
:mod:`benchmarks.semantic_roundtrip.metrics`).

Each residual names:

* a canonical field path (``rules[i].field`` or a whole missing/extra rule),
* estimated forward loss contribution under protocol weights, and
* a suggested ``RepairTriggerKind`` value (missing / contradictory /
  low_confidence).

``exception_with_window`` is recorded as the zero-residual control case on the
**pilot** population.  Explicitly typed populations are accepted via
:func:`build_plateau_residual_catalog`:

* ``pilot`` — sealed five-case historical receipt layout
* ``repair_development`` — visible residuals for packets / det. edits
* ``authorized_blind_evaluation`` — post-freeze evaluator-only (fail-closed)
* legacy ``holdout`` / ``custom`` — still accepted for historical receipts

Pilot-only seal validation remains in :func:`parse_plateau_residual_catalog`.
Normal supervisor/packet access modes reject blind sources, gold bindings,
blind residuals, and unauthorized evaluator mode.

Optional spaCy and autoencoder cue slots are placeholders for teacher
pipelines (PLAT-050 / PLAT-060); they never authorize production composition.
``unsupported`` / ``not_measured`` / ``runtime_failed`` case statuses never
enter semantic score aggregates.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import (
    LIST_FIELDS,
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ConstructorRequest,
    ContractError,
)
from benchmarks.semantic_roundtrip.matrix import MatrixCase
from benchmarks.semantic_roundtrip.metrics import (
    RULE_WEIGHTS,
    compare_semantic_ir,
    maximum_weight_assignment,
    rule_similarity,
)
from benchmarks.semantic_roundtrip.selective_repair import RepairTriggerKind


PLATEAU_RESIDUAL_CATALOG_INTERFACE: Final = "PlateauResidualCatalog@1"
PLATEAU_RESIDUAL_CATALOG_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau-residual-catalog.v1"
)
CATALOG_CID_SCOPE: Final = "payload_without_catalog_cid"
CATALOG_CID_CODEC: Final = "dag-json"

DEFAULT_CATALOG_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "plateau_residual_catalog.json"
)
DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "holdout_residual_catalog.json"
)
DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_residual_catalog.json"
)
PILOT_CASES_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)
HOLDOUT_CASES_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/holdout_cases.json"
)
REPAIR_DEV_CASES_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/repair_dev_cases.json"
)

POPULATION_KIND_PILOT: Final = "pilot"
POPULATION_KIND_HOLDOUT: Final = "holdout"
POPULATION_KIND_CUSTOM: Final = "custom"
POPULATION_KIND_REPAIR_DEVELOPMENT: Final = "repair_development"
POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION: Final = (
    "authorized_blind_evaluation"
)
POPULATION_KINDS: Final = frozenset(
    {
        POPULATION_KIND_PILOT,
        POPULATION_KIND_HOLDOUT,
        POPULATION_KIND_CUSTOM,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
        POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
    }
)
# Populations that may carry blind source/gold/residuals.  Normal
# supervisor/packet paths must reject these without post-freeze authorization.
BLIND_POPULATION_KINDS: Final = frozenset(
    {POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION}
)
# Visible non-pilot populations used for repair loops (not blind).
VISIBLE_NON_PILOT_POPULATION_KINDS: Final = frozenset(
    {
        POPULATION_KIND_HOLDOUT,
        POPULATION_KIND_CUSTOM,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
    }
)

ACCESS_MODE_SUPERVISOR: Final = "supervisor"
ACCESS_MODE_PACKET: Final = "packet"
ACCESS_MODE_AUTHORIZED_EVALUATOR: Final = "authorized_evaluator"
ACCESS_MODES: Final = frozenset(
    {
        ACCESS_MODE_SUPERVISOR,
        ACCESS_MODE_PACKET,
        ACCESS_MODE_AUTHORIZED_EVALUATOR,
    }
)
NORMAL_ACCESS_MODES: Final = frozenset(
    {ACCESS_MODE_SUPERVISOR, ACCESS_MODE_PACKET}
)

# Case / catalog evaluation status — mutually exclusive with semantic scores.
CATALOG_STATUS_SEMANTIC_SCORED: Final = "semantic_scored"
CATALOG_STATUS_NOT_MEASURED: Final = "not_measured"
CATALOG_STATUS_RUNTIME_FAILED: Final = "runtime_failed"
CATALOG_STATUS_UNSUPPORTED: Final = "unsupported"
CATALOG_EVALUATION_STATUSES: Final = frozenset(
    {
        CATALOG_STATUS_SEMANTIC_SCORED,
        CATALOG_STATUS_NOT_MEASURED,
        CATALOG_STATUS_RUNTIME_FAILED,
        CATALOG_STATUS_UNSUPPORTED,
    }
)
NON_SEMANTIC_CATALOG_STATUSES: Final = frozenset(
    {
        CATALOG_STATUS_NOT_MEASURED,
        CATALOG_STATUS_RUNTIME_FAILED,
        CATALOG_STATUS_UNSUPPORTED,
    }
)

BASELINE_ARM_ID: Final = (
    "typed_deontic__no_guidance__no_repair__not_applicable__deterministic"
)
BASELINE_CONSTRUCTOR_IDENTITY: Final = (
    "TypedDeonticCanonicalConstructor@1"
)
BASELINE_E2E_MEAN: Final = 0.088333333
BASELINE_REPORT_CID: Final = (
    "baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza"
)
# Post-pilot production baseline for holdout / repair-dev residual catalogs.
HOLDOUT_BASELINE_E2E_MEAN: Final = 0.0
HOLDOUT_BASELINE_REPORT_CID: Final = (
    "baguqeerag7kwogvfkjciwoovp6cvpl5pueaoweucfqzjhbl4j6vhq5n5xn7q"
)
REPAIR_DEV_BASELINE_E2E_MEAN: Final = HOLDOUT_BASELINE_E2E_MEAN
REPAIR_DEV_BASELINE_REPORT_CID: Final = HOLDOUT_BASELINE_REPORT_CID

DEFAULT_REPAIR_DEV_ASSUMPTIONS: Final = (
    "production remains typed_deontic → IR → deterministic realizer",
    "residuals are structural gold vs baseline L1 field-path forensics only",
    "unsupported/not_measured/runtime_failed never enter semantic score aggregates",
    "blind sources/gold/residuals inaccessible without post-freeze evaluator authorization",
    "Hammer/cvc5/Lean have semantic_authority false",
)

PILOT_CASE_IDS: Final = (
    "exception_with_window",
    "exec_order_1",
    "corp_policy_1",
    "legal_doc_1",
    "construction_contract",
)
NONZERO_PILOT_CASE_IDS: Final = (
    "exec_order_1",
    "corp_policy_1",
    "legal_doc_1",
    "construction_contract",
)
ZERO_RESIDUAL_CONTROL_CASE_ID: Final = "exception_with_window"

RESIDUAL_KIND_FIELD_MISMATCH: Final = "field_mismatch"
RESIDUAL_KIND_MISSING_RULE: Final = "missing_rule"
RESIDUAL_KIND_EXTRA_RULE: Final = "extra_rule"
RESIDUAL_KINDS: Final = frozenset(
    {
        RESIDUAL_KIND_FIELD_MISMATCH,
        RESIDUAL_KIND_MISSING_RULE,
        RESIDUAL_KIND_EXTRA_RULE,
    }
)

SUGGESTED_TRIGGER_KINDS: Final = frozenset(
    kind.value for kind in RepairTriggerKind
)

_LOSS_EPS: Final = 1e-8


class ResidualCatalogError(ContractError):
    """Raised when a residual catalog cannot be built or validated."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ResidualCatalogError(message)


def _finite_unit(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ResidualCatalogError(
            f"{path} must be a finite number from zero to one"
        )
    return float(value)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResidualCatalogError(f"{path} must be a nonblank string")
    return value


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ResidualCatalogError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ResidualCatalogError(f"{path} must be an array")
    return value


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _set_score(left: Sequence[str], right: Sequence[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _json_atom(value: object) -> object:
    if isinstance(value, tuple):
        return list(value)
    return value


def _is_empty_field_value(field: str, value: object) -> bool:
    if field in LIST_FIELDS:
        return not value
    return value in ("", None)


def suggest_trigger_kind(
    *,
    residual_kind: str,
    field: str | None,
    gold_value: object,
    candidate_value: object,
) -> str:
    """Map a residual facet to a selective-repair trigger kind.

    Whole missing rules and empty candidate slots are ``missing``.  Present
    but incorrect values are ``contradictory``.  ``low_confidence`` is reserved
    for teacher/confidence overlays and is not emitted by structural forensics.
    """

    if residual_kind == RESIDUAL_KIND_MISSING_RULE:
        return RepairTriggerKind.MISSING.value
    if residual_kind == RESIDUAL_KIND_EXTRA_RULE:
        return RepairTriggerKind.CONTRADICTORY.value
    if field is None:
        return RepairTriggerKind.CONTRADICTORY.value
    gold_empty = _is_empty_field_value(field, gold_value)
    cand_empty = _is_empty_field_value(field, candidate_value)
    if not gold_empty and cand_empty:
        return RepairTriggerKind.MISSING.value
    return RepairTriggerKind.CONTRADICTORY.value


@dataclass(frozen=True, slots=True)
class ResidualFacet:
    """One case × field residual with estimated forward loss contribution."""

    case_id: str
    field_path: str
    residual_kind: str
    loss_contribution: float
    similarity: float
    suggested_trigger_kind: str
    canonical_field: str | None = None
    gold_rule_index: int | None = None
    candidate_rule_index: int | None = None
    gold_value: object = None
    candidate_value: object = None
    rule_match_score: float | None = None
    spacy_cue: Mapping[str, object] | None = None
    ae_cue: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _nonblank(self.case_id, "case_id"))
        object.__setattr__(
            self, "field_path", _nonblank(self.field_path, "field_path")
        )
        if self.residual_kind not in RESIDUAL_KINDS:
            raise ResidualCatalogError(
                f"unknown residual_kind: {self.residual_kind!r}"
            )
        object.__setattr__(
            self,
            "loss_contribution",
            _finite_unit(self.loss_contribution, "loss_contribution"),
        )
        object.__setattr__(
            self, "similarity", _finite_unit(self.similarity, "similarity")
        )
        if self.suggested_trigger_kind not in SUGGESTED_TRIGGER_KINDS:
            raise ResidualCatalogError(
                "suggested_trigger_kind must be a RepairTriggerKind value"
            )
        if self.canonical_field is not None:
            if self.canonical_field not in RULE_FIELDS:
                raise ResidualCatalogError(
                    f"unknown canonical_field: {self.canonical_field!r}"
                )
        for name in ("gold_rule_index", "candidate_rule_index"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ResidualCatalogError(
                    f"{name} must be a nonnegative integer or null"
                )
        if self.rule_match_score is not None:
            object.__setattr__(
                self,
                "rule_match_score",
                _finite_unit(self.rule_match_score, "rule_match_score"),
            )
        if self.spacy_cue is not None and not isinstance(
            self.spacy_cue, Mapping
        ):
            raise ResidualCatalogError("spacy_cue must be an object or null")
        if self.ae_cue is not None and not isinstance(self.ae_cue, Mapping):
            raise ResidualCatalogError("ae_cue must be an object or null")
        if self.spacy_cue is not None:
            object.__setattr__(
                self, "spacy_cue", MappingProxyType(dict(self.spacy_cue))
            )
        if self.ae_cue is not None:
            object.__setattr__(
                self, "ae_cue", MappingProxyType(dict(self.ae_cue))
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "ae_cue": (
                None if self.ae_cue is None else dict(self.ae_cue)
            ),
            "candidate_rule_index": self.candidate_rule_index,
            "candidate_value": _plain_json(self.candidate_value),
            "canonical_field": self.canonical_field,
            "case_id": self.case_id,
            "field_path": self.field_path,
            "gold_rule_index": self.gold_rule_index,
            "gold_value": _plain_json(self.gold_value),
            "loss_contribution": self.loss_contribution,
            "residual_kind": self.residual_kind,
            "rule_match_score": self.rule_match_score,
            "similarity": self.similarity,
            "spacy_cue": (
                None if self.spacy_cue is None else dict(self.spacy_cue)
            ),
            "suggested_trigger_kind": self.suggested_trigger_kind,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResidualFacet":
        data = _mapping(value, "residual facet")
        return cls(
            case_id=_nonblank(data.get("case_id"), "case_id"),
            field_path=_nonblank(data.get("field_path"), "field_path"),
            residual_kind=_nonblank(
                data.get("residual_kind"), "residual_kind"
            ),
            loss_contribution=_finite_unit(
                data.get("loss_contribution"), "loss_contribution"
            ),
            similarity=_finite_unit(data.get("similarity"), "similarity"),
            suggested_trigger_kind=_nonblank(
                data.get("suggested_trigger_kind"),
                "suggested_trigger_kind",
            ),
            canonical_field=data.get("canonical_field"),
            gold_rule_index=data.get("gold_rule_index"),
            candidate_rule_index=data.get("candidate_rule_index"),
            gold_value=data.get("gold_value"),
            candidate_value=data.get("candidate_value"),
            rule_match_score=data.get("rule_match_score"),
            spacy_cue=data.get("spacy_cue"),
            ae_cue=data.get("ae_cue"),
        )


@dataclass(frozen=True, slots=True)
class CaseResidualRecord:
    """All residual facets for one case against baseline L1.

    ``evaluation_status`` defaults to ``semantic_scored``.  Non-semantic
    statuses (``unsupported``, ``not_measured``, ``runtime_failed``) must carry
    empty residuals and are excluded from semantic score aggregates.
    """

    case_id: str
    forward_loss: float
    residuals: tuple[ResidualFacet, ...]
    is_zero_residual_control: bool
    case_cid: str | None = None
    gold_ir_cid: str | None = None
    l1_cid: str | None = None
    gold_rule_count: int | None = None
    l1_rule_count: int | None = None
    cycle_loss: float | None = None
    end_to_end_loss: float | None = None
    evaluation_status: str = CATALOG_STATUS_SEMANTIC_SCORED
    evaluation_status_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _nonblank(self.case_id, "case_id"))
        status = str(self.evaluation_status or CATALOG_STATUS_SEMANTIC_SCORED)
        if status not in CATALOG_EVALUATION_STATUSES:
            raise ResidualCatalogError(
                f"unknown evaluation_status: {self.evaluation_status!r}"
            )
        object.__setattr__(self, "evaluation_status", status)
        if self.evaluation_status_reason is not None:
            object.__setattr__(
                self,
                "evaluation_status_reason",
                _nonblank(
                    self.evaluation_status_reason,
                    "evaluation_status_reason",
                ),
            )
        residuals = tuple(self.residuals)
        object.__setattr__(self, "residuals", residuals)
        for facet in residuals:
            if facet.case_id != self.case_id:
                raise ResidualCatalogError(
                    "residual case_id must match CaseResidualRecord.case_id"
                )
        if status in NON_SEMANTIC_CATALOG_STATUSES:
            # Non-semantic outcomes must not masquerade as scored residuals.
            if residuals:
                raise ResidualCatalogError(
                    f"{self.case_id}: {status} cases must not carry residual "
                    "facets (distinct from semantic scores)"
                )
            object.__setattr__(self, "forward_loss", 0.0)
            if self.cycle_loss is not None or self.end_to_end_loss is not None:
                raise ResidualCatalogError(
                    f"{self.case_id}: non-semantic status cannot carry "
                    "cycle_loss or end_to_end_loss scores"
                )
        else:
            object.__setattr__(
                self,
                "forward_loss",
                _finite_unit(self.forward_loss, "forward_loss"),
            )
            contribution_sum = round(
                sum(facet.loss_contribution for facet in residuals), 9
            )
            if abs(contribution_sum - self.forward_loss) > 1e-6:
                raise ResidualCatalogError(
                    f"{self.case_id}: residual contributions "
                    f"{contribution_sum} do not match forward_loss "
                    f"{self.forward_loss}"
                )
        if self.is_zero_residual_control:
            if (
                self.evaluation_status != CATALOG_STATUS_SEMANTIC_SCORED
                or self.forward_loss != 0.0
                or residuals
            ):
                raise ResidualCatalogError(
                    "zero-residual control must be semantic_scored with empty "
                    "residuals and forward_loss 0"
                )
        for name in ("cycle_loss", "end_to_end_loss"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self, name, _finite_unit(value, name)
                )
        for name in ("case_cid", "gold_ir_cid", "l1_cid"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _nonblank(value, name))
        for name in ("gold_rule_count", "l1_rule_count"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ResidualCatalogError(
                    f"{name} must be a nonnegative integer or null"
                )

    @property
    def residual_count(self) -> int:
        return len(self.residuals)

    @property
    def loss_contribution_sum(self) -> float:
        return round(
            sum(facet.loss_contribution for facet in self.residuals), 9
        )

    @property
    def field_paths(self) -> tuple[str, ...]:
        return tuple(facet.field_path for facet in self.residuals)

    @property
    def semantic_score_eligible(self) -> bool:
        return self.evaluation_status == CATALOG_STATUS_SEMANTIC_SCORED

    def to_dict(self) -> dict[str, object]:
        # Keep pilot seal CID-stable: omit default semantic_scored fields.
        payload: dict[str, object] = {
            "case_cid": self.case_cid,
            "case_id": self.case_id,
            "cycle_loss": self.cycle_loss,
            "end_to_end_loss": self.end_to_end_loss,
            "field_paths": list(self.field_paths),
            "forward_loss": self.forward_loss,
            "gold_ir_cid": self.gold_ir_cid,
            "gold_rule_count": self.gold_rule_count,
            "is_zero_residual_control": self.is_zero_residual_control,
            "l1_cid": self.l1_cid,
            "l1_rule_count": self.l1_rule_count,
            "loss_contribution_sum": self.loss_contribution_sum,
            "residual_count": self.residual_count,
            "residuals": [facet.to_dict() for facet in self.residuals],
        }
        if (
            self.evaluation_status != CATALOG_STATUS_SEMANTIC_SCORED
            or self.evaluation_status_reason is not None
        ):
            payload["evaluation_status"] = self.evaluation_status
            payload["evaluation_status_reason"] = self.evaluation_status_reason
            payload["semantic_score_eligible"] = self.semantic_score_eligible
        return payload

    @classmethod
    def from_dict(cls, value: object) -> "CaseResidualRecord":
        data = _mapping(value, "case residual")
        residuals = tuple(
            ResidualFacet.from_dict(item)
            for item in _array(data.get("residuals"), "residuals")
        )
        status = data.get("evaluation_status")
        if status is None:
            status = CATALOG_STATUS_SEMANTIC_SCORED
        return cls(
            case_id=_nonblank(data.get("case_id"), "case_id"),
            forward_loss=_finite_unit(
                data.get("forward_loss"), "forward_loss"
            )
            if status == CATALOG_STATUS_SEMANTIC_SCORED
            or data.get("forward_loss") is not None
            else 0.0,
            residuals=residuals,
            is_zero_residual_control=bool(
                data.get("is_zero_residual_control")
            ),
            case_cid=data.get("case_cid"),
            gold_ir_cid=data.get("gold_ir_cid"),
            l1_cid=data.get("l1_cid"),
            gold_rule_count=data.get("gold_rule_count"),
            l1_rule_count=data.get("l1_rule_count"),
            cycle_loss=data.get("cycle_loss"),
            end_to_end_loss=data.get("end_to_end_loss"),
            evaluation_status=str(status),
            evaluation_status_reason=data.get("evaluation_status_reason"),  # type: ignore[arg-type]
        )


def compute_facet_residuals(
    case_id: str,
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    candidate_ir: CanonicalRuleIR | Mapping[str, object],
    *,
    spacy_cues: Mapping[str, Mapping[str, object]] | None = None,
    ae_cues: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[ResidualFacet, ...]:
    """Decompose forward structural loss into per-field residual facets.

    Contributions sum (within floating-point tolerance) to the protocol
    forward loss ``1 - semantic_score(gold, candidate)``.
    """

    case_id = _nonblank(case_id, "case_id")
    gold = (
        gold_ir
        if isinstance(gold_ir, CanonicalRuleIR)
        else CanonicalRuleIR.from_dict(gold_ir)
    )
    candidate = (
        candidate_ir
        if isinstance(candidate_ir, CanonicalRuleIR)
        else CanonicalRuleIR.from_dict(candidate_ir)
    )
    left = list(gold.rules)
    right = list(candidate.rules)
    weights = [
        [rule_similarity(left_rule, right_rule) for right_rule in right]
        for left_rule in left
    ]
    pairs = maximum_weight_assignment(weights) if left and right else []
    matched_left = {left_index for left_index, _ in pairs}
    matched_right = {right_index for _, right_index in pairs}
    denominator = max(len(left), len(right), 1)
    spacy_cues = spacy_cues or {}
    ae_cues = ae_cues or {}
    facets: list[ResidualFacet] = []

    for left_index, right_index in pairs:
        left_rule = left[left_index]
        right_rule = right[right_index]
        match_score = float(weights[left_index][right_index])
        for field, weight in RULE_WEIGHTS.items():
            gold_value = getattr(left_rule, field)
            cand_value = getattr(right_rule, field)
            if field in LIST_FIELDS:
                similarity = _set_score(gold_value, cand_value)
            else:
                similarity = 1.0 if gold_value == cand_value else 0.0
            if similarity >= 1.0 - _LOSS_EPS:
                continue
            field_path = f"rules[{left_index}].{field}"
            contribution = round(
                (1.0 - similarity) * float(weight) / denominator, 9
            )
            residual_kind = RESIDUAL_KIND_FIELD_MISMATCH
            trigger = suggest_trigger_kind(
                residual_kind=residual_kind,
                field=field,
                gold_value=gold_value,
                candidate_value=cand_value,
            )
            facets.append(
                ResidualFacet(
                    case_id=case_id,
                    field_path=field_path,
                    residual_kind=residual_kind,
                    loss_contribution=contribution,
                    similarity=round(similarity, 9),
                    suggested_trigger_kind=trigger,
                    canonical_field=field,
                    gold_rule_index=left_index,
                    candidate_rule_index=right_index,
                    gold_value=_json_atom(gold_value),
                    candidate_value=_json_atom(cand_value),
                    rule_match_score=round(match_score, 9),
                    spacy_cue=spacy_cues.get(field_path),
                    ae_cue=ae_cues.get(field_path),
                )
            )

    for left_index, left_rule in enumerate(left):
        if left_index in matched_left:
            continue
        field_path = f"rules[{left_index}]"
        contribution = round(1.0 / denominator, 9)
        facets.append(
            ResidualFacet(
                case_id=case_id,
                field_path=field_path,
                residual_kind=RESIDUAL_KIND_MISSING_RULE,
                loss_contribution=contribution,
                similarity=0.0,
                suggested_trigger_kind=RepairTriggerKind.MISSING.value,
                canonical_field=None,
                gold_rule_index=left_index,
                candidate_rule_index=None,
                gold_value=left_rule.to_dict(),
                candidate_value=None,
                rule_match_score=None,
                spacy_cue=spacy_cues.get(field_path),
                ae_cue=ae_cues.get(field_path),
            )
        )

    for right_index, right_rule in enumerate(right):
        if right_index in matched_right:
            continue
        field_path = f"l1.rules[{right_index}]"
        contribution = round(1.0 / denominator, 9)
        facets.append(
            ResidualFacet(
                case_id=case_id,
                field_path=field_path,
                residual_kind=RESIDUAL_KIND_EXTRA_RULE,
                loss_contribution=contribution,
                similarity=0.0,
                suggested_trigger_kind=RepairTriggerKind.CONTRADICTORY.value,
                canonical_field=None,
                gold_rule_index=None,
                candidate_rule_index=right_index,
                gold_value=None,
                candidate_value=right_rule.to_dict(),
                rule_match_score=None,
                spacy_cue=spacy_cues.get(field_path),
                ae_cue=ae_cues.get(field_path),
            )
        )

    facets.sort(
        key=lambda facet: (
            -facet.loss_contribution,
            facet.field_path,
            facet.residual_kind,
        )
    )
    return tuple(facets)


def build_case_residual(
    case_id: str,
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    candidate_ir: CanonicalRuleIR | Mapping[str, object],
    *,
    is_zero_residual_control: bool | None = None,
    case_cid: str | None = None,
    gold_ir_cid: str | None = None,
    l1_cid: str | None = None,
    cycle_loss: float | None = None,
    end_to_end_loss: float | None = None,
    spacy_cues: Mapping[str, Mapping[str, object]] | None = None,
    ae_cues: Mapping[str, Mapping[str, object]] | None = None,
) -> CaseResidualRecord:
    """Build one case residual record from gold vs baseline L1."""

    gold = (
        gold_ir
        if isinstance(gold_ir, CanonicalRuleIR)
        else CanonicalRuleIR.from_dict(gold_ir)
    )
    candidate = (
        candidate_ir
        if isinstance(candidate_ir, CanonicalRuleIR)
        else CanonicalRuleIR.from_dict(candidate_ir)
    )
    comparison = compare_semantic_ir(gold, candidate)
    forward_loss = float(comparison["semantic_loss"])
    residuals = compute_facet_residuals(
        case_id,
        gold,
        candidate,
        spacy_cues=spacy_cues,
        ae_cues=ae_cues,
    )
    contribution_sum = round(
        sum(facet.loss_contribution for facet in residuals), 9
    )
    # Align stored forward_loss to the contribution sum when they match the
    # protocol comparison within 1e-8 (float/rounding noise only).
    if abs(contribution_sum - forward_loss) <= 1e-8:
        forward_loss = contribution_sum
    if is_zero_residual_control is None:
        is_zero_residual_control = (
            case_id == ZERO_RESIDUAL_CONTROL_CASE_ID
        )
    if gold_ir_cid is None:
        gold_ir_cid = cid_for_dag_json(gold.to_dict())
    if l1_cid is None:
        l1_cid = cid_for_dag_json(candidate.to_dict())
    return CaseResidualRecord(
        case_id=case_id,
        forward_loss=forward_loss,
        residuals=residuals,
        is_zero_residual_control=bool(is_zero_residual_control),
        case_cid=case_cid,
        gold_ir_cid=gold_ir_cid,
        l1_cid=l1_cid,
        gold_rule_count=len(gold.rules),
        l1_rule_count=len(candidate.rules),
        cycle_loss=cycle_loss,
        end_to_end_loss=end_to_end_loss,
    )


def aggregate_residuals(
    cases: Sequence[CaseResidualRecord],
) -> dict[str, object]:
    """Aggregate case×facet residuals for triggers and edit prioritization.

    Only ``semantic_scored`` cases contribute to semantic loss sums.  Non-
    semantic statuses remain visible in ``by_evaluation_status`` counts.
    """

    cases = tuple(cases)
    by_case: dict[str, dict[str, object]] = {}
    by_field: Counter[str] = Counter()
    by_field_contrib: dict[str, float] = {}
    by_trigger: Counter[str] = Counter()
    by_trigger_contrib: dict[str, float] = {}
    by_kind: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    total_residual_count = 0
    sum_forward = 0.0
    scored_case_count = 0
    field_paths: list[str] = []

    for record in cases:
        by_status[record.evaluation_status] += 1
        contrib = record.loss_contribution_sum
        case_entry: dict[str, object] = {
            "forward_loss": record.forward_loss,
            "is_zero_residual_control": record.is_zero_residual_control,
            "loss_contribution_sum": contrib,
            "residual_count": record.residual_count,
            "field_paths": list(record.field_paths),
            "suggested_trigger_kinds": sorted(
                {
                    facet.suggested_trigger_kind
                    for facet in record.residuals
                }
            ),
        }
        if (
            record.evaluation_status != CATALOG_STATUS_SEMANTIC_SCORED
            or record.evaluation_status_reason is not None
        ):
            case_entry["evaluation_status"] = record.evaluation_status
            case_entry["semantic_score_eligible"] = (
                record.semantic_score_eligible
            )
        by_case[record.case_id] = case_entry
        if not record.semantic_score_eligible:
            # Distinct from semantic scores: do not accumulate loss/residuals.
            continue
        scored_case_count += 1
        sum_forward += record.forward_loss
        total_residual_count += record.residual_count
        field_paths.extend(record.field_paths)
        for facet in record.residuals:
            field_key = facet.canonical_field or facet.residual_kind
            by_field[field_key] += 1
            by_field_contrib[field_key] = round(
                by_field_contrib.get(field_key, 0.0)
                + facet.loss_contribution,
                9,
            )
            by_trigger[facet.suggested_trigger_kind] += 1
            by_trigger_contrib[facet.suggested_trigger_kind] = round(
                by_trigger_contrib.get(facet.suggested_trigger_kind, 0.0)
                + facet.loss_contribution,
                9,
            )
            by_kind[facet.residual_kind] += 1

    nonzero = [
        record.case_id
        for record in cases
        if record.semantic_score_eligible
        and not record.is_zero_residual_control
        and record.forward_loss > 0.0
    ]
    zero_controls = [
        record.case_id
        for record in cases
        if record.is_zero_residual_control
    ]
    case_count = len(cases)
    return {
        "by_canonical_field": {
            key: {
                "loss_contribution_sum": by_field_contrib[key],
                "residual_count": by_field[key],
            }
            for key in sorted(by_field)
        },
        "by_case": by_case,
        "by_evaluation_status": dict(sorted(by_status.items())),
        "by_residual_kind": dict(sorted(by_kind.items())),
        "by_suggested_trigger_kind": {
            key: {
                "loss_contribution_sum": by_trigger_contrib[key],
                "residual_count": by_trigger[key],
            }
            for key in sorted(by_trigger)
        },
        "case_count": case_count,
        "field_paths": sorted(set(field_paths)),
        "mean_forward_loss": (
            round(sum_forward / scored_case_count, 9)
            if scored_case_count
            else 0.0
        ),
        "nonzero_case_count": len(nonzero),
        "nonzero_case_ids": nonzero,
        "semantic_scored_case_count": scored_case_count,
        "sum_forward_loss": round(sum_forward, 9),
        "total_residual_count": total_residual_count,
        "zero_control_case_ids": zero_controls,
        "zero_control_residual_count": sum(
            by_case[case_id]["residual_count"]  # type: ignore[index]
            for case_id in zero_controls
        ),
    }


def is_blind_population_kind(kind: object) -> bool:
    """Return True when *kind* is an authorized-blind evaluation population."""

    return str(kind or "") in BLIND_POPULATION_KINDS


def is_normal_access_mode(access_mode: object) -> bool:
    """Return True for supervisor/packet paths (not authorized evaluator)."""

    return str(access_mode or ACCESS_MODE_SUPERVISOR) in NORMAL_ACCESS_MODES


def _normalize_access_mode(access_mode: object) -> str:
    mode = str(access_mode or ACCESS_MODE_SUPERVISOR).strip()
    if mode not in ACCESS_MODES:
        raise ResidualCatalogError(
            f"unknown access_mode: {access_mode!r}; "
            f"expected one of {sorted(ACCESS_MODES)}"
        )
    return mode


def validate_evaluator_authorization(
    authorization: object,
    *,
    require_post_freeze: bool = True,
) -> dict[str, object]:
    """Validate a post-freeze blind-evaluation authorization record.

    Minimum fields: ``authorization_cid`` (or bindable payload),
    ``candidate_freeze_cid``, and ``evaluator_mode`` true.  Premature
    (pre-freeze) authorizations fail closed.
    """

    data = dict(_mapping(authorization, "evaluator_authorization"))
    if data.get("evaluator_mode") is not True:
        raise ResidualCatalogError(
            "evaluator authorization requires evaluator_mode=true"
        )
    freeze_cid = data.get("candidate_freeze_cid")
    _nonblank(freeze_cid, "evaluator_authorization.candidate_freeze_cid")
    if require_post_freeze:
        post_freeze = data.get("post_freeze")
        freeze_authorized = data.get("freeze_authorized")
        if post_freeze is True or freeze_authorized is True:
            pass
        elif post_freeze is False or freeze_authorized is False:
            raise ResidualCatalogError(
                "premature blind access rejected: authorization is not "
                "post-freeze (candidate freeze required)"
            )
        else:
            raise ResidualCatalogError(
                "premature blind access rejected: authorization missing "
                "post_freeze/freeze_authorized marker"
            )
    auth_cid = data.get("authorization_cid")
    if auth_cid is None:
        bindable = {
            key: value
            for key, value in data.items()
            if key != "authorization_cid"
        }
        auth_cid = cid_for_dag_json(bindable)
        data["authorization_cid"] = auth_cid
    else:
        try:
            validate_cid(auth_cid, codecs=(CATALOG_CID_CODEC,))
        except (TypeError, ValueError) as exc:
            raise ResidualCatalogError(
                "evaluator_authorization.authorization_cid must be a "
                "canonical dag-json CID"
            ) from exc
    return data


def assert_access_allows_population(
    population_kind: object,
    *,
    access_mode: object = ACCESS_MODE_SUPERVISOR,
    evaluator_authorization: Mapping[str, object] | None = None,
) -> None:
    """Fail closed when a path attempts premature blind residual access."""

    kind = str(population_kind or "").strip()
    mode = _normalize_access_mode(access_mode)
    if kind not in POPULATION_KINDS and kind:
        raise ResidualCatalogError(
            f"unknown population_kind: {population_kind!r}; "
            f"expected one of {sorted(POPULATION_KINDS)}"
        )
    if not is_blind_population_kind(kind):
        if mode == ACCESS_MODE_AUTHORIZED_EVALUATOR and evaluator_authorization:
            # Authorized evaluator mode is reserved for blind evaluation.
            raise ResidualCatalogError(
                "authorized_evaluator mode is only valid for "
                f"{POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION}"
            )
        return
    if mode in NORMAL_ACCESS_MODES:
        raise ResidualCatalogError(
            "premature blind access rejected: "
            f"{mode} path cannot use population_kind={kind!r}"
        )
    if mode != ACCESS_MODE_AUTHORIZED_EVALUATOR:
        raise ResidualCatalogError(
            "blind residual access requires access_mode="
            f"{ACCESS_MODE_AUTHORIZED_EVALUATOR!r}"
        )
    if evaluator_authorization is None:
        raise ResidualCatalogError(
            "premature blind access rejected: missing evaluator authorization"
        )
    validate_evaluator_authorization(evaluator_authorization)


def reject_blind_material_on_normal_path(
    value: object,
    *,
    access_mode: object = ACCESS_MODE_SUPERVISOR,
    path: str = "payload",
) -> None:
    """Reject blind sources, gold bindings, residuals, and unauthorized mode.

    Used by normal supervisor/packet consumption paths.  Authorized evaluator
    mode is not validated here (use :func:`assert_access_allows_population`).
    """

    mode = _normalize_access_mode(access_mode)
    if mode not in NORMAL_ACCESS_MODES:
        return
    data = _mapping(value, path)
    kind = data.get("population_kind")
    if is_blind_population_kind(kind):
        raise ResidualCatalogError(
            f"{mode} path rejects blind residual catalogs "
            f"(population_kind={kind!r})"
        )
    if data.get("contains_blind_residuals") is True:
        raise ResidualCatalogError(
            f"{mode} path rejects payloads marked contains_blind_residuals"
        )
    if data.get("evaluator_mode") is True:
        raise ResidualCatalogError(
            f"{mode} path rejects unauthorized evaluator mode"
        )
    if data.get("blind_source") or data.get("source_visibility") == "blind":
        raise ResidualCatalogError(
            f"{mode} path rejects blind sources"
        )
    if (
        data.get("blind_gold")
        or data.get("gold_binding") == "blind"
        or data.get("gold_visibility") == "blind"
    ):
        raise ResidualCatalogError(
            f"{mode} path rejects blind gold bindings"
        )
    cases = data.get("cases")
    if isinstance(cases, list):
        for index, case in enumerate(cases):
            if not isinstance(case, Mapping):
                continue
            case_path = f"{path}.cases[{index}]"
            if case.get("blind_source") or case.get("source_visibility") == "blind":
                raise ResidualCatalogError(
                    f"{mode} path rejects blind sources at {case_path}"
                )
            if (
                case.get("blind_gold")
                or case.get("gold_binding") == "blind"
                or case.get("gold_visibility") == "blind"
            ):
                raise ResidualCatalogError(
                    f"{mode} path rejects blind gold bindings at {case_path}"
                )
            if case.get("blind_residual") or case.get("residual_visibility") == "blind":
                raise ResidualCatalogError(
                    f"{mode} path rejects blind residuals at {case_path}"
                )
    residuals = data.get("residuals")
    if isinstance(residuals, list):
        for index, row in enumerate(residuals):
            if not isinstance(row, Mapping):
                continue
            if row.get("blind_residual") or row.get("visibility") == "blind":
                raise ResidualCatalogError(
                    f"{mode} path rejects blind residuals at "
                    f"{path}.residuals[{index}]"
                )


def assert_catalog_usable_on_supervisor_path(
    value: object,
    *,
    access_mode: object = ACCESS_MODE_SUPERVISOR,
) -> dict[str, object]:
    """Parse-agnostic guard for supervisor/packet residual catalog consumers."""

    data = dict(_mapping(value, "residual catalog"))
    reject_blind_material_on_normal_path(data, access_mode=access_mode)
    kind = data.get("population_kind")
    if kind is not None:
        assert_access_allows_population(kind, access_mode=access_mode)
    return data


def load_population_matrix_cases(
    path: str | Path,
    *,
    expected_case_ids: Sequence[str] | None = None,
    require_nonempty: bool = True,
) -> tuple[MatrixCase, ...]:
    """Load a preregistered case population JSON array as MatrixCase records.

    Accepts either ``id`` or ``case_id`` keys (same contract as
    :func:`benchmarks.semantic_roundtrip.matrix.load_matrix_cases`).
    """

    fixture_path = Path(path)
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResidualCatalogError(
            f"cannot read case population path: {fixture_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ResidualCatalogError(
            f"case population path is not valid JSON: {fixture_path}"
        ) from exc
    if not isinstance(payload, list):
        raise ResidualCatalogError(
            f"case population at {fixture_path} must be a JSON array"
        )
    if require_nonempty and not payload:
        raise ResidualCatalogError(
            f"case population at {fixture_path} must be nonempty"
        )
    cases = tuple(MatrixCase.from_dict(item) for item in payload)
    observed = tuple(case.case_id for case in cases)
    if len(set(observed)) != len(observed):
        raise ResidualCatalogError(
            f"case population has duplicate case_ids: {observed}"
        )
    if expected_case_ids is not None:
        expected = tuple(expected_case_ids)
        _require(
            observed == expected,
            f"case population ids {observed} do not match expected {expected}",
        )
    return cases


def load_pilot_matrix_cases(
    repo_root: Path | None = None,
    *,
    path: Path | None = None,
) -> tuple[MatrixCase, ...]:
    """Load the frozen five-case pilot fixture as MatrixCase records."""

    root = repo_root if repo_root is not None else _repo_root()
    fixture_path = path if path is not None else root / PILOT_CASES_RELATIVE_PATH
    cases = load_population_matrix_cases(
        fixture_path,
        expected_case_ids=None,
        require_nonempty=True,
    )
    observed = tuple(case.case_id for case in cases)
    _require(
        set(observed) == set(PILOT_CASE_IDS)
        and len(observed) == len(PILOT_CASE_IDS),
        f"pilot fixture case ids changed: {observed}",
    )
    # Stable pilot order for CID-bound receipts.
    by_id = {case.case_id: case for case in cases}
    return tuple(by_id[case_id] for case_id in PILOT_CASE_IDS)


def preregistered_holdout_matrix_cases() -> tuple[MatrixCase, ...]:
    """Provisional holdout population from selective-repair activation fixtures.

    Used when ``holdout_cases.json`` is not yet frozen (PLAT2-020).  Gold IR is
    the repaired target; L1 is still constructed by the typed_deontic baseline
    so residuals reflect the real det. production path.
    """

    from benchmarks.semantic_roundtrip.selective_repair import (
        activation_fixture_pack,
    )

    cases: list[MatrixCase] = []
    for fixture in activation_fixture_pack():
        cases.append(
            MatrixCase(
                case_id=fixture.case_id,
                source_text=fixture.source_text,
                allowed_atom_vocabulary=fixture.vocabulary,
                gold_ir=fixture.repaired_ir,
            )
        )
    _require(bool(cases), "activation fixture pack must be nonempty")
    return tuple(cases)


def load_holdout_matrix_cases(
    repo_root: Path | None = None,
    *,
    path: Path | None = None,
    allow_activation_fallback: bool = True,
) -> tuple[MatrixCase, ...]:
    """Load the preregistered holdout case population.

    Prefers ``tests/fixtures/semantic_roundtrip/holdout_cases.json`` when
    present.  Until PLAT2-020 freezes that fixture, falls back to the
    selective-repair activation pack (missing_temporal, low_confidence_object,
    contradictory_modality).
    """

    root = repo_root if repo_root is not None else _repo_root()
    fixture_path = (
        Path(path) if path is not None else root / HOLDOUT_CASES_RELATIVE_PATH
    )
    if fixture_path.is_file():
        return load_population_matrix_cases(fixture_path, require_nonempty=True)
    if not allow_activation_fallback:
        raise ResidualCatalogError(
            f"holdout case population not found: {fixture_path}"
        )
    return preregistered_holdout_matrix_cases()


def load_repair_dev_matrix_cases(
    repo_root: Path | None = None,
    *,
    path: Path | None = None,
    allow_holdout_fallback: bool = True,
    allow_activation_fallback: bool = True,
) -> tuple[MatrixCase, ...]:
    """Load the visible repair-development case population.

    Resolution order:

    1. Explicit *path* when provided and present.
    2. ``tests/fixtures/semantic_roundtrip/repair_dev_cases.json`` (PLAT2-020).
    3. Holdout fixture as provisional repair-dev population when allowed.
    4. Selective-repair activation pack when allowed.
    """

    root = repo_root if repo_root is not None else _repo_root()
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path) if Path(path).is_absolute() else root / path)
    candidates.append(root / REPAIR_DEV_CASES_RELATIVE_PATH)
    if allow_holdout_fallback:
        candidates.append(root / HOLDOUT_CASES_RELATIVE_PATH)
    for fixture_path in candidates:
        if fixture_path.is_file():
            return load_population_matrix_cases(
                fixture_path, require_nonempty=True
            )
    if allow_activation_fallback:
        return preregistered_holdout_matrix_cases()
    raise ResidualCatalogError(
        "repair-development case population not found; expected "
        f"{REPAIR_DEV_CASES_RELATIVE_PATH} or holdout fallback"
    )


def _resolve_population_path(
    path: str | Path | None,
    *,
    repo_root: Path,
) -> Path | None:
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = repo_root / resolved
    return resolved


def _population_path_label(
    path: str | Path | None,
    *,
    default: Path | None = None,
) -> str | None:
    if path is not None:
        return str(Path(path)).replace("\\", "/")
    if default is not None:
        return str(default).replace("\\", "/")
    return None


def _infer_population_kind(
    case_ids: Sequence[str],
    *,
    explicit: str | None,
    cases_path: str | Path | None,
) -> str:
    if explicit is not None:
        kind = str(explicit).strip()
        if kind not in POPULATION_KINDS:
            raise ResidualCatalogError(
                f"unknown population_kind: {explicit!r}; "
                f"expected one of {sorted(POPULATION_KINDS)}"
            )
        return kind
    if cases_path is not None:
        label = str(Path(cases_path)).replace("\\", "/")
        if label.endswith(str(PILOT_CASES_RELATIVE_PATH).replace("\\", "/")):
            return POPULATION_KIND_PILOT
        if label.endswith(
            str(REPAIR_DEV_CASES_RELATIVE_PATH).replace("\\", "/")
        ):
            return POPULATION_KIND_REPAIR_DEVELOPMENT
        if label.endswith(str(HOLDOUT_CASES_RELATIVE_PATH).replace("\\", "/")):
            return POPULATION_KIND_HOLDOUT
    if tuple(case_ids) == PILOT_CASE_IDS or set(case_ids) == set(PILOT_CASE_IDS):
        return POPULATION_KIND_PILOT
    return POPULATION_KIND_CUSTOM


def _default_tree_cid(
    *,
    population_kind: str,
    baseline_report_cid: str,
    explicit: str | None = None,
) -> str:
    if explicit is not None:
        try:
            validate_cid(explicit, codecs=(CATALOG_CID_CODEC,))
        except (TypeError, ValueError) as exc:
            raise ResidualCatalogError(
                "tree_cid must be a canonical dag-json CID"
            ) from exc
        return explicit
    return cid_for_dag_json(
        {
            "baseline_report_cid": baseline_report_cid,
            "binding_kind": "post_pilot_source_tree",
            "population_kind": population_kind,
            "scope": "semantic_roundtrip_residual_catalog_tree",
        }
    )


def _population_cid_for_cases(
    *,
    population_kind: str,
    population_path: str | None,
    matrix_cases: Sequence[MatrixCase],
    explicit: str | None = None,
) -> str:
    if explicit is not None:
        try:
            validate_cid(explicit, codecs=(CATALOG_CID_CODEC,))
        except (TypeError, ValueError) as exc:
            raise ResidualCatalogError(
                "population_cid must be a canonical dag-json CID"
            ) from exc
        return explicit
    return cid_for_dag_json(
        {
            "case_cids": [case.case_cid for case in matrix_cases],
            "case_ids": [case.case_id for case in matrix_cases],
            "population_kind": population_kind,
            "population_path": population_path,
        }
    )


def _build_status_block(
    records: Sequence[CaseResidualRecord],
) -> dict[str, object]:
    by_case: dict[str, dict[str, object]] = {}
    counts: Counter[str] = Counter()
    for record in records:
        counts[record.evaluation_status] += 1
        by_case[record.case_id] = {
            "evaluation_status": record.evaluation_status,
            "reason": record.evaluation_status_reason or (
                "success"
                if record.semantic_score_eligible
                else record.evaluation_status
            ),
            "semantic_score_eligible": record.semantic_score_eligible,
        }
    return {
        "by_case": by_case,
        "catalog_evaluation_mode": "case_facet_residuals",
        "counts": {
            status: int(counts.get(status, 0))
            for status in sorted(CATALOG_EVALUATION_STATUSES)
        },
        "non_semantic_excluded_from_score_aggregates": True,
        "non_semantic_statuses": sorted(NON_SEMANTIC_CATALOG_STATUSES),
        "semantic_score_statuses": [CATALOG_STATUS_SEMANTIC_SCORED],
    }


def _build_provenance_block(
    *,
    population_kind: str,
    population_path: str | None,
    access_mode: str,
    constructor_identity: str,
    baseline_arm_id: str,
    tree_cid: str,
    population_cid: str,
    l1_source: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "access_mode": access_mode,
        "baseline_arm_id": baseline_arm_id,
        "builder": (
            "benchmarks.semantic_roundtrip.residual_catalog"
            ".build_plateau_residual_catalog"
        ),
        "constructor_identity": constructor_identity,
        "interface": PLATEAU_RESIDUAL_CATALOG_INTERFACE,
        "l1_source": l1_source,
        "population_cid": population_cid,
        "population_kind": population_kind,
        "population_path": population_path,
        "schema_version": PLATEAU_RESIDUAL_CATALOG_SCHEMA,
        "tree_cid": tree_cid,
    }
    if extra:
        for key, value in extra.items():
            if key not in payload:
                payload[str(key)] = _plain_json(value)
    return payload


def construct_baseline_l1(
    case: MatrixCase,
    *,
    constructor: object | None = None,
) -> CanonicalRuleIR:
    """Construct the typed_deontic baseline L1 for one pilot case."""

    if constructor is None:
        from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
            TypedDeonticCanonicalConstructor,
        )

        constructor = TypedDeonticCanonicalConstructor()
    construct = getattr(constructor, "construct", None)
    if not callable(construct):
        raise ResidualCatalogError("constructor must provide construct()")
    request = ConstructorRequest(
        case.source_text,
        case.allowed_atom_vocabulary,
        {},
    )
    result = construct(request)
    status = getattr(result, "status", None)
    canonical_ir = getattr(result, "canonical_ir", None)
    if status is None or getattr(status, "value", status) != "success":
        detail = getattr(result, "failure_detail", None) or getattr(
            result, "failure_reason", "constructor failed"
        )
        raise ResidualCatalogError(
            f"baseline L1 construction failed for {case.case_id}: {detail}"
        )
    if not isinstance(canonical_ir, CanonicalRuleIR) or canonical_ir.is_empty:
        raise ResidualCatalogError(
            f"baseline L1 for {case.case_id} is missing or empty"
        )
    return canonical_ir


def _bind_catalog_cid(payload: dict[str, object]) -> dict[str, object]:
    """Attach codec/scope and CID-bind the catalog payload in place."""

    payload["catalog_cid_codec"] = CATALOG_CID_CODEC
    payload["catalog_cid_scope"] = CATALOG_CID_SCOPE
    # Codec/scope are part of the bound content for fail-closed verification.
    payload["catalog_cid"] = cid_for_dag_json(
        {key: value for key, value in payload.items() if key != "catalog_cid"}
    )
    return payload


def build_plateau_residual_catalog(
    repo_root: Path | None = None,
    *,
    cases: Sequence[MatrixCase] | None = None,
    cases_path: str | Path | None = None,
    population_kind: str | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
    baseline_arm_id: str = BASELINE_ARM_ID,
    constructor_identity: str = BASELINE_CONSTRUCTOR_IDENTITY,
    baseline_e2e_mean: float | None = None,
    baseline_report_cid: str | None = None,
    cycle_loss_by_case: Mapping[str, float] | None = None,
    end_to_end_loss_by_case: Mapping[str, float] | None = None,
    zero_residual_control_case_id: str | None = None,
    access_mode: str = ACCESS_MODE_SUPERVISOR,
    evaluator_authorization: Mapping[str, object] | None = None,
    tree_cid: str | None = None,
    population_cid: str | None = None,
    assumptions: Sequence[str] | None = None,
    provenance: Mapping[str, object] | None = None,
    case_status_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build a CID-bindable plateau residual catalog for a case population.

    Explicitly typed populations:

    * ``pilot`` — sealed five-case historical receipt layout
    * ``repair_development`` — visible residuals + tree/population CIDs,
      status, assumptions, and provenance
    * ``authorized_blind_evaluation`` — requires
      ``access_mode=authorized_evaluator`` and post-freeze authorization
    * legacy ``holdout`` / ``custom`` — population layout without the
      repair-development binding block (historical receipts)

    Population resolution order:

    1. Explicit ``cases`` sequence when provided.
    2. Preregistered ``cases_path`` JSON array (relative to repo root or absolute).
    3. Repair-dev fixture / holdout fallback when kind is ``repair_development``.
    4. Holdout fixture / activation fallback when kind is ``holdout``.
    5. Default pilot fixture when ``population_kind`` is ``pilot`` or omitted.

    Pilot catalogs keep the sealed pilot field layout (``pilot_case_ids``,
    ``nonzero_pilot_case_ids``) so historical CID receipts remain valid.

    ``case_status_overrides`` may mark individual cases as ``unsupported``,
    ``not_measured``, or ``runtime_failed``; those cases never contribute
    residual facets or semantic loss aggregates.
    """

    root = repo_root if repo_root is not None else _repo_root()
    mode = _normalize_access_mode(access_mode)
    resolved_path = _resolve_population_path(cases_path, repo_root=root)
    path_label = _population_path_label(cases_path)

    # Infer kind early when explicit so population loaders select correctly.
    early_kind = (
        str(population_kind).strip() if population_kind is not None else None
    )
    if early_kind is not None and early_kind not in POPULATION_KINDS:
        raise ResidualCatalogError(
            f"unknown population_kind: {population_kind!r}; "
            f"expected one of {sorted(POPULATION_KINDS)}"
        )

    if cases is not None:
        matrix_cases = tuple(cases)
    elif resolved_path is not None:
        matrix_cases = load_population_matrix_cases(
            resolved_path, require_nonempty=True
        )
        if path_label is None:
            path_label = str(resolved_path).replace("\\", "/")
    elif early_kind == POPULATION_KIND_HOLDOUT:
        matrix_cases = load_holdout_matrix_cases(root)
        path_label = _population_path_label(
            cases_path, default=HOLDOUT_CASES_RELATIVE_PATH
        )
    elif early_kind == POPULATION_KIND_REPAIR_DEVELOPMENT:
        # Prefer frozen repair-dev fixture; fall back to holdout / activation.
        if (root / REPAIR_DEV_CASES_RELATIVE_PATH).is_file():
            path_label = _population_path_label(
                cases_path, default=REPAIR_DEV_CASES_RELATIVE_PATH
            )
            matrix_cases = load_repair_dev_matrix_cases(
                root, path=root / REPAIR_DEV_CASES_RELATIVE_PATH
            )
        elif (root / HOLDOUT_CASES_RELATIVE_PATH).is_file():
            path_label = _population_path_label(
                cases_path, default=HOLDOUT_CASES_RELATIVE_PATH
            )
            matrix_cases = load_repair_dev_matrix_cases(
                root, path=root / HOLDOUT_CASES_RELATIVE_PATH
            )
        else:
            path_label = _population_path_label(
                cases_path, default=HOLDOUT_CASES_RELATIVE_PATH
            )
            matrix_cases = load_repair_dev_matrix_cases(root)
    elif early_kind == POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION:
        # Blind evaluation never invents cases; caller must supply cases or path.
        raise ResidualCatalogError(
            "authorized_blind_evaluation requires explicit cases or cases_path "
            "(blind corpus is custodian-held and never default-loaded)"
        )
    else:
        # Default and explicit pilot populations use the sealed fixture.
        matrix_cases = load_pilot_matrix_cases(root)
        path_label = _population_path_label(
            cases_path, default=PILOT_CASES_RELATIVE_PATH
        )

    _require(bool(matrix_cases), "case population must be nonempty")
    case_ids = tuple(case.case_id for case in matrix_cases)
    kind = _infer_population_kind(
        case_ids, explicit=population_kind, cases_path=cases_path or path_label
    )
    assert_access_allows_population(
        kind,
        access_mode=mode,
        evaluator_authorization=evaluator_authorization,
    )
    if kind == POPULATION_KIND_PILOT:
        _require(
            set(case_ids) == set(PILOT_CASE_IDS)
            and len(case_ids) == len(PILOT_CASE_IDS),
            f"pilot population case ids must match sealed pilots; got {case_ids}",
        )

    post_pilot_baseline_kinds = {
        POPULATION_KIND_HOLDOUT,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
        POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
    }
    if baseline_e2e_mean is None:
        baseline_e2e_mean = (
            HOLDOUT_BASELINE_E2E_MEAN
            if kind in post_pilot_baseline_kinds
            else BASELINE_E2E_MEAN
        )
    if baseline_report_cid is None:
        baseline_report_cid = (
            HOLDOUT_BASELINE_REPORT_CID
            if kind in post_pilot_baseline_kinds
            else BASELINE_REPORT_CID
        )

    if zero_residual_control_case_id is None and kind == POPULATION_KIND_PILOT:
        zero_residual_control_case_id = ZERO_RESIDUAL_CONTROL_CASE_ID

    cycle_loss_by_case = dict(cycle_loss_by_case or {})
    end_to_end_loss_by_case = dict(end_to_end_loss_by_case or {})
    status_overrides = {
        str(key): dict(value)
        for key, value in dict(case_status_overrides or {}).items()
    }
    records: list[CaseResidualRecord] = []
    l1_source = (
        "provided_l1_by_case" if l1_by_case is not None else "typed_deontic_baseline_construct"
    )
    for case in matrix_cases:
        override = status_overrides.get(case.case_id)
        if override is not None:
            status = str(
                override.get("evaluation_status")
                or override.get("status")
                or CATALOG_STATUS_SEMANTIC_SCORED
            )
            reason = override.get("reason") or override.get(
                "evaluation_status_reason"
            )
            if status in NON_SEMANTIC_CATALOG_STATUSES:
                records.append(
                    CaseResidualRecord(
                        case_id=case.case_id,
                        forward_loss=0.0,
                        residuals=(),
                        is_zero_residual_control=False,
                        case_cid=case.case_cid,
                        gold_ir_cid=case.gold_ir_cid,
                        evaluation_status=status,
                        evaluation_status_reason=(
                            None if reason is None else str(reason)
                        ),
                    )
                )
                continue
        if l1_by_case is not None and case.case_id in l1_by_case:
            l1_value = l1_by_case[case.case_id]
            l1 = (
                l1_value
                if isinstance(l1_value, CanonicalRuleIR)
                else CanonicalRuleIR.from_dict(l1_value)
            )
        else:
            l1 = construct_baseline_l1(case, constructor=constructor)
        is_control = (
            zero_residual_control_case_id is not None
            and case.case_id == zero_residual_control_case_id
        )
        records.append(
            build_case_residual(
                case.case_id,
                case.gold_ir,
                l1,
                is_zero_residual_control=is_control,
                case_cid=case.case_cid,
                gold_ir_cid=case.gold_ir_cid,
                cycle_loss=cycle_loss_by_case.get(case.case_id),
                end_to_end_loss=end_to_end_loss_by_case.get(case.case_id),
            )
        )

    # Preserve input / sealed pilot order for CID binding.
    if kind == POPULATION_KIND_PILOT:
        order = {
            case_id: index for index, case_id in enumerate(PILOT_CASE_IDS)
        }
    else:
        order = {
            case_id: index for index, case_id in enumerate(case_ids)
        }
    records.sort(key=lambda record: order.get(record.case_id, 10_000))
    ordered_case_ids = tuple(record.case_id for record in records)

    aggregates = aggregate_residuals(records)
    case_payloads = [record.to_dict() for record in records]
    residual_rows = [
        facet.to_dict()
        for record in records
        for facet in record.residuals
        if record.semantic_score_eligible
    ]
    nonzero_case_ids = [
        record.case_id
        for record in records
        if record.semantic_score_eligible
        and not record.is_zero_residual_control
        and record.forward_loss > 0.0
    ]

    baseline = {
        "arm_id": baseline_arm_id,
        "constructor_identity": constructor_identity,
        "e2e_mean": baseline_e2e_mean,
        "report_cid": baseline_report_cid,
    }

    if kind == POPULATION_KIND_PILOT:
        # Sealed pilot layout — do not add population_* keys (CID stability).
        payload: dict[str, object] = {
            "aggregates": aggregates,
            "baseline": baseline,
            "cases": case_payloads,
            "interface": PLATEAU_RESIDUAL_CATALOG_INTERFACE,
            "nonzero_pilot_case_ids": list(NONZERO_PILOT_CASE_IDS),
            "pilot_case_ids": list(PILOT_CASE_IDS),
            "residuals": residual_rows,
            "schema_version": PLATEAU_RESIDUAL_CATALOG_SCHEMA,
            "zero_residual_control_case_id": (
                zero_residual_control_case_id
                or ZERO_RESIDUAL_CONTROL_CASE_ID
            ),
        }
    else:
        resolved_population_path = path_label or str(
            HOLDOUT_CASES_RELATIVE_PATH
        ).replace("\\", "/")
        payload = {
            "aggregates": aggregates,
            "baseline": baseline,
            "case_ids": list(ordered_case_ids),
            "cases": case_payloads,
            "interface": PLATEAU_RESIDUAL_CATALOG_INTERFACE,
            "nonzero_case_ids": nonzero_case_ids,
            "population_kind": kind,
            "population_path": resolved_population_path,
            "residuals": residual_rows,
            "schema_version": PLATEAU_RESIDUAL_CATALOG_SCHEMA,
            "zero_residual_control_case_id": zero_residual_control_case_id,
        }
        # Extended binding block for typed repair-dev / authorized blind.
        if kind in {
            POPULATION_KIND_REPAIR_DEVELOPMENT,
            POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
        }:
            bound_tree_cid = _default_tree_cid(
                population_kind=kind,
                baseline_report_cid=str(baseline_report_cid),
                explicit=tree_cid,
            )
            bound_population_cid = _population_cid_for_cases(
                population_kind=kind,
                population_path=resolved_population_path,
                matrix_cases=matrix_cases,
                explicit=population_cid,
            )
            bound_assumptions = list(
                assumptions
                if assumptions is not None
                else DEFAULT_REPAIR_DEV_ASSUMPTIONS
            )
            for index, item in enumerate(bound_assumptions):
                _nonblank(item, f"assumptions[{index}]")
            bound_provenance = _build_provenance_block(
                population_kind=kind,
                population_path=resolved_population_path,
                access_mode=mode,
                constructor_identity=constructor_identity,
                baseline_arm_id=baseline_arm_id,
                tree_cid=bound_tree_cid,
                population_cid=bound_population_cid,
                l1_source=l1_source,
                extra=provenance,
            )
            if kind == POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION:
                assert evaluator_authorization is not None
                auth = validate_evaluator_authorization(
                    evaluator_authorization
                )
                bound_provenance["evaluator_authorization_cid"] = auth[
                    "authorization_cid"
                ]
                payload["evaluator_authorization_cid"] = auth[
                    "authorization_cid"
                ]
                payload["evaluator_mode"] = True
                payload["contains_blind_residuals"] = True
            payload["assumptions"] = bound_assumptions
            payload["population_cid"] = bound_population_cid
            payload["provenance"] = bound_provenance
            payload["status"] = _build_status_block(records)
            payload["tree_cid"] = bound_tree_cid
    if kind != POPULATION_KIND_PILOT and mode in NORMAL_ACCESS_MODES:
        reject_blind_material_on_normal_path(payload, access_mode=mode)
    return _bind_catalog_cid(payload)


def build_holdout_residual_catalog(
    repo_root: Path | None = None,
    *,
    cases: Sequence[MatrixCase] | None = None,
    cases_path: str | Path | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
    baseline_arm_id: str = BASELINE_ARM_ID,
    constructor_identity: str = BASELINE_CONSTRUCTOR_IDENTITY,
    baseline_e2e_mean: float = HOLDOUT_BASELINE_E2E_MEAN,
    baseline_report_cid: str = HOLDOUT_BASELINE_REPORT_CID,
    cycle_loss_by_case: Mapping[str, float] | None = None,
    end_to_end_loss_by_case: Mapping[str, float] | None = None,
    zero_residual_control_case_id: str | None = None,
) -> dict[str, object]:
    """Build the holdout-population residual catalog (case × facet)."""

    return build_plateau_residual_catalog(
        repo_root,
        cases=cases,
        cases_path=cases_path,
        population_kind=POPULATION_KIND_HOLDOUT,
        l1_by_case=l1_by_case,
        constructor=constructor,
        baseline_arm_id=baseline_arm_id,
        constructor_identity=constructor_identity,
        baseline_e2e_mean=baseline_e2e_mean,
        baseline_report_cid=baseline_report_cid,
        cycle_loss_by_case=cycle_loss_by_case,
        end_to_end_loss_by_case=end_to_end_loss_by_case,
        zero_residual_control_case_id=zero_residual_control_case_id,
        access_mode=ACCESS_MODE_SUPERVISOR,
    )


def build_repair_dev_residual_catalog(
    repo_root: Path | None = None,
    *,
    cases: Sequence[MatrixCase] | None = None,
    cases_path: str | Path | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
    baseline_arm_id: str = BASELINE_ARM_ID,
    constructor_identity: str = BASELINE_CONSTRUCTOR_IDENTITY,
    baseline_e2e_mean: float = REPAIR_DEV_BASELINE_E2E_MEAN,
    baseline_report_cid: str = REPAIR_DEV_BASELINE_REPORT_CID,
    cycle_loss_by_case: Mapping[str, float] | None = None,
    end_to_end_loss_by_case: Mapping[str, float] | None = None,
    zero_residual_control_case_id: str | None = None,
    tree_cid: str | None = None,
    population_cid: str | None = None,
    assumptions: Sequence[str] | None = None,
    provenance: Mapping[str, object] | None = None,
    case_status_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build the repair-development residual catalog (case × facet + bindings)."""

    return build_plateau_residual_catalog(
        repo_root,
        cases=cases,
        cases_path=cases_path,
        population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
        l1_by_case=l1_by_case,
        constructor=constructor,
        baseline_arm_id=baseline_arm_id,
        constructor_identity=constructor_identity,
        baseline_e2e_mean=baseline_e2e_mean,
        baseline_report_cid=baseline_report_cid,
        cycle_loss_by_case=cycle_loss_by_case,
        end_to_end_loss_by_case=end_to_end_loss_by_case,
        zero_residual_control_case_id=zero_residual_control_case_id,
        access_mode=ACCESS_MODE_SUPERVISOR,
        tree_cid=tree_cid,
        population_cid=population_cid,
        assumptions=assumptions,
        provenance=provenance,
        case_status_overrides=case_status_overrides,
    )


def _validate_catalog_cid_binding(data: Mapping[str, Any]) -> None:
    catalog_cid = data.get("catalog_cid")
    try:
        validate_cid(catalog_cid, codecs=(CATALOG_CID_CODEC,))
    except (TypeError, ValueError) as exc:
        raise ResidualCatalogError(
            "catalog_cid must be a canonical dag-json CID"
        ) from exc
    cid_payload = {
        key: value for key, value in data.items() if key != "catalog_cid"
    }
    if cid_for_dag_json(cid_payload) != catalog_cid:
        raise ResidualCatalogError(
            "catalog_cid does not match the CID-bound payload"
        )
    if data.get("catalog_cid_codec") != CATALOG_CID_CODEC:
        raise ResidualCatalogError("catalog_cid_codec must be dag-json")
    if data.get("catalog_cid_scope") != CATALOG_CID_SCOPE:
        raise ResidualCatalogError(
            "catalog_cid_scope must be payload_without_catalog_cid"
        )


def _validate_case_residual_rows(
    cases: Sequence[CaseResidualRecord],
    residual_rows: Sequence[object],
) -> None:
    parsed_rows = [ResidualFacet.from_dict(item) for item in residual_rows]
    expected_rows = [
        facet for record in cases for facet in record.residuals
    ]
    _require(
        len(parsed_rows) == len(expected_rows),
        "flat residuals length must match nested case residuals",
    )
    for facet in expected_rows:
        _require(
            facet.loss_contribution > 0.0,
            f"{facet.case_id} residual loss_contribution must be positive",
        )


def _validate_aggregates(
    cases: Sequence[CaseResidualRecord],
    aggregates: Mapping[str, Any],
) -> None:
    recomputed = aggregate_residuals(cases)
    for key in (
        "case_count",
        "nonzero_case_count",
        "total_residual_count",
        "zero_control_residual_count",
        "sum_forward_loss",
        "mean_forward_loss",
    ):
        _require(
            aggregates.get(key) == recomputed[key],
            f"aggregates.{key} does not match recomputation",
        )


def _validate_extended_population_bindings(
    data: Mapping[str, Any],
    *,
    kind: str,
    cases: Sequence[CaseResidualRecord],
) -> None:
    """Validate tree/population CIDs, status, assumptions, and provenance."""

    tree_cid = data.get("tree_cid")
    population_cid = data.get("population_cid")
    try:
        validate_cid(tree_cid, codecs=(CATALOG_CID_CODEC,))
    except (TypeError, ValueError) as exc:
        raise ResidualCatalogError(
            "tree_cid must be a canonical dag-json CID"
        ) from exc
    try:
        validate_cid(population_cid, codecs=(CATALOG_CID_CODEC,))
    except (TypeError, ValueError) as exc:
        raise ResidualCatalogError(
            "population_cid must be a canonical dag-json CID"
        ) from exc

    assumptions = _array(data.get("assumptions"), "assumptions")
    _require(bool(assumptions), "assumptions must be a nonempty array")
    for index, item in enumerate(assumptions):
        _nonblank(item, f"assumptions[{index}]")

    provenance = _mapping(data.get("provenance"), "provenance")
    _require(
        provenance.get("population_kind") == kind,
        "provenance.population_kind must match catalog population_kind",
    )
    _nonblank(provenance.get("tree_cid"), "provenance.tree_cid")
    _nonblank(provenance.get("population_cid"), "provenance.population_cid")
    _require(
        provenance.get("tree_cid") == tree_cid,
        "provenance.tree_cid must match catalog tree_cid",
    )
    _require(
        provenance.get("population_cid") == population_cid,
        "provenance.population_cid must match catalog population_cid",
    )

    status = _mapping(data.get("status"), "status")
    _require(
        status.get("non_semantic_excluded_from_score_aggregates") is True,
        "status.non_semantic_excluded_from_score_aggregates must be true",
    )
    non_semantic = _array(
        status.get("non_semantic_statuses"), "status.non_semantic_statuses"
    )
    _require(
        set(non_semantic) == set(NON_SEMANTIC_CATALOG_STATUSES),
        "status.non_semantic_statuses must list unsupported/not_measured/"
        "runtime_failed",
    )
    by_case = _mapping(status.get("by_case"), "status.by_case")
    for record in cases:
        entry = _mapping(
            by_case.get(record.case_id), f"status.by_case.{record.case_id}"
        )
        _require(
            entry.get("evaluation_status") == record.evaluation_status,
            f"status.by_case.{record.case_id}.evaluation_status mismatch",
        )
        _require(
            entry.get("semantic_score_eligible")
            is record.semantic_score_eligible,
            f"status.by_case.{record.case_id}.semantic_score_eligible mismatch",
        )
    if kind == POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION:
        _require(
            data.get("evaluator_mode") is True,
            "authorized_blind_evaluation catalog requires evaluator_mode=true",
        )
        _nonblank(
            data.get("evaluator_authorization_cid"),
            "evaluator_authorization_cid",
        )


def parse_population_residual_catalog(
    value: object,
    *,
    require_holdout_kind: bool = False,
    require_repair_development_kind: bool = False,
    access_mode: str = ACCESS_MODE_SUPERVISOR,
    evaluator_authorization: Mapping[str, object] | None = None,
    allow_blind: bool = False,
) -> dict[str, object]:
    """Parse a population residual catalog (non-pilot).

    Does **not** enforce the sealed pilot case set.  Pilot receipts must use
    :func:`parse_plateau_residual_catalog` so historical seals stay fail-closed.

    Normal supervisor/packet *access_mode* values reject blind populations and
    blind material unless *allow_blind* is True **and** authorization is
    supplied for ``authorized_blind_evaluation``.
    """

    data = dict(_mapping(value, "population residual catalog"))
    mode = _normalize_access_mode(access_mode)
    _require(
        data.get("interface") == PLATEAU_RESIDUAL_CATALOG_INTERFACE,
        "catalog interface mismatch",
    )
    _require(
        data.get("schema_version") == PLATEAU_RESIDUAL_CATALOG_SCHEMA,
        "catalog schema_version mismatch",
    )
    kind = data.get("population_kind")
    if kind is not None:
        _require(
            kind in POPULATION_KINDS and kind != POPULATION_KIND_PILOT,
            "population residual catalog population_kind must be a non-pilot "
            f"kind; got {kind!r}",
        )
    if require_holdout_kind:
        _require(
            kind == POPULATION_KIND_HOLDOUT,
            "holdout residual catalog population_kind must be holdout",
        )
    if require_repair_development_kind:
        _require(
            kind == POPULATION_KIND_REPAIR_DEVELOPMENT,
            "repair-development residual catalog population_kind must be "
            "repair_development",
        )

    if is_blind_population_kind(kind):
        if not allow_blind and mode in NORMAL_ACCESS_MODES:
            raise ResidualCatalogError(
                "premature blind access rejected: parse on "
                f"{mode} path cannot load population_kind={kind!r}"
            )
        assert_access_allows_population(
            kind,
            access_mode=(
                ACCESS_MODE_AUTHORIZED_EVALUATOR
                if allow_blind
                else mode
            ),
            evaluator_authorization=evaluator_authorization,
        )
    else:
        reject_blind_material_on_normal_path(data, access_mode=mode)

    population_path = data.get("population_path")
    _require(
        isinstance(population_path, str) and population_path.strip(),
        "population_path must be a nonblank string",
    )
    case_ids = _array(data.get("case_ids"), "case_ids")
    _require(bool(case_ids), "case_ids must be a nonempty array")
    for index, case_id in enumerate(case_ids):
        _nonblank(case_id, f"case_ids[{index}]")
    _require(
        len(set(case_ids)) == len(case_ids),
        "case_ids must be unique",
    )

    baseline = _mapping(data.get("baseline"), "baseline")
    _require(
        baseline.get("arm_id") == BASELINE_ARM_ID,
        "baseline arm_id must be the sealed deterministic production arm",
    )
    _nonblank(
        baseline.get("constructor_identity"),
        "baseline.constructor_identity",
    )
    _finite_unit(baseline.get("e2e_mean"), "baseline.e2e_mean")
    _nonblank(baseline.get("report_cid"), "baseline.report_cid")

    cases = [
        CaseResidualRecord.from_dict(item)
        for item in _array(data.get("cases"), "cases")
    ]
    observed_ids = [record.case_id for record in cases]
    _require(
        observed_ids == case_ids,
        f"catalog cases must match case_ids order; got {observed_ids}",
    )
    _require(bool(cases), "catalog cases must be nonempty")

    control_id = data.get("zero_residual_control_case_id")
    if control_id is not None:
        control_id = _nonblank(
            control_id, "zero_residual_control_case_id"
        )
        control = next(
            (record for record in cases if record.case_id == control_id),
            None,
        )
        _require(
            control is not None,
            "zero_residual_control_case_id must appear in cases",
        )
        assert control is not None
        _require(
            control.is_zero_residual_control
            and control.forward_loss == 0.0
            and control.residual_count == 0,
            f"{control_id} must be a zero-residual control",
        )

    residual_rows = _array(data.get("residuals"), "residuals")
    scored_cases = [record for record in cases if record.semantic_score_eligible]
    _validate_case_residual_rows(scored_cases, residual_rows)

    nonzero_declared = _array(
        data.get("nonzero_case_ids"), "nonzero_case_ids"
    )
    expected_nonzero = [
        record.case_id
        for record in cases
        if record.semantic_score_eligible
        and not record.is_zero_residual_control
        and record.forward_loss > 0.0
    ]
    _require(
        nonzero_declared == expected_nonzero,
        "nonzero_case_ids must match semantic_scored cases with positive "
        "forward_loss",
    )
    for case_id in expected_nonzero:
        record = next(item for item in cases if item.case_id == case_id)
        _require(
            record.residual_count > 0 and bool(record.field_paths),
            f"{case_id} must expose field-path residuals",
        )
    for record in cases:
        if record.evaluation_status in NON_SEMANTIC_CATALOG_STATUSES:
            _require(
                record.residual_count == 0,
                f"{record.case_id}: {record.evaluation_status} must not carry "
                "semantic residual facets",
            )

    aggregates = _mapping(data.get("aggregates"), "aggregates")
    _validate_aggregates(cases, aggregates)

    if kind in {
        POPULATION_KIND_REPAIR_DEVELOPMENT,
        POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
    }:
        _validate_extended_population_bindings(
            data, kind=str(kind), cases=cases
        )

    _validate_catalog_cid_binding(data)
    return data


def parse_plateau_residual_catalog(
    value: object,
) -> dict[str, object]:
    """Parse and validate a **pilot-sealed** catalog (historical receipts).

    Non-pilot populations (holdout, repair_development, custom,
    authorized_blind_evaluation) must use
    :func:`parse_population_residual_catalog` instead.
    """

    data = dict(_mapping(value, "plateau residual catalog"))
    kind = data.get("population_kind")
    if kind in POPULATION_KINDS and kind != POPULATION_KIND_PILOT:
        raise ResidualCatalogError(
            "pilot seal parser rejects population residual catalogs; "
            "use parse_population_residual_catalog"
        )
    _require(
        data.get("interface") == PLATEAU_RESIDUAL_CATALOG_INTERFACE,
        "catalog interface mismatch",
    )
    _require(
        data.get("schema_version") == PLATEAU_RESIDUAL_CATALOG_SCHEMA,
        "catalog schema_version mismatch",
    )
    pilot_ids = _array(data.get("pilot_case_ids"), "pilot_case_ids")
    _require(
        pilot_ids == list(PILOT_CASE_IDS),
        "pilot_case_ids must match the sealed pilot population",
    )
    nonzero = _array(
        data.get("nonzero_pilot_case_ids"), "nonzero_pilot_case_ids"
    )
    _require(
        nonzero == list(NONZERO_PILOT_CASE_IDS),
        "nonzero_pilot_case_ids must match sealed non-zero pilots",
    )
    _require(
        data.get("zero_residual_control_case_id")
        == ZERO_RESIDUAL_CONTROL_CASE_ID,
        "zero_residual_control_case_id must be exception_with_window",
    )
    baseline = _mapping(data.get("baseline"), "baseline")
    _require(
        baseline.get("arm_id") == BASELINE_ARM_ID,
        "baseline arm_id must be the sealed deterministic production arm",
    )
    cases = [
        CaseResidualRecord.from_dict(item)
        for item in _array(data.get("cases"), "cases")
    ]
    observed_ids = [record.case_id for record in cases]
    _require(
        observed_ids == list(PILOT_CASE_IDS),
        f"catalog cases must cover pilots in order; got {observed_ids}",
    )
    control = next(
        record
        for record in cases
        if record.case_id == ZERO_RESIDUAL_CONTROL_CASE_ID
    )
    _require(
        control.is_zero_residual_control
        and control.forward_loss == 0.0
        and control.residual_count == 0,
        "exception_with_window must be a zero-residual control",
    )
    for case_id in NONZERO_PILOT_CASE_IDS:
        record = next(item for item in cases if item.case_id == case_id)
        _require(
            record.forward_loss > 0.0 and record.residual_count > 0,
            f"{case_id} must contribute field-path residuals",
        )
        _require(
            bool(record.field_paths),
            f"{case_id} must expose field_paths",
        )
        for facet in record.residuals:
            _require(
                facet.loss_contribution > 0.0,
                f"{case_id} residual loss_contribution must be positive",
            )

    residual_rows = _array(data.get("residuals"), "residuals")
    _validate_case_residual_rows(cases, residual_rows)
    aggregates = _mapping(data.get("aggregates"), "aggregates")
    _validate_aggregates(cases, aggregates)
    _validate_catalog_cid_binding(data)
    return data


def parse_residual_catalog_document(
    value: object,
    *,
    access_mode: str = ACCESS_MODE_SUPERVISOR,
    evaluator_authorization: Mapping[str, object] | None = None,
    allow_blind: bool = False,
) -> dict[str, object]:
    """Dispatch to pilot seal or population parser based on payload shape."""

    data = _mapping(value, "residual catalog")
    kind = data.get("population_kind")
    if kind in POPULATION_KINDS and kind != POPULATION_KIND_PILOT:
        return parse_population_residual_catalog(
            data,
            access_mode=access_mode,
            evaluator_authorization=evaluator_authorization,
            allow_blind=allow_blind,
        )
    if "pilot_case_ids" in data:
        return parse_plateau_residual_catalog(data)
    if "case_ids" in data:
        return parse_population_residual_catalog(
            data,
            access_mode=access_mode,
            evaluator_authorization=evaluator_authorization,
            allow_blind=allow_blind,
        )
    return parse_plateau_residual_catalog(data)


def validate_plateau_residual_catalog(
    value: object,
    *,
    repo_root: Path | None = None,
    expect_regenerated: bool = False,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
    access_mode: str = ACCESS_MODE_SUPERVISOR,
    evaluator_authorization: Mapping[str, object] | None = None,
    allow_blind: bool = False,
) -> dict[str, object]:
    """Validate catalog structure and optional exact regeneration."""

    parsed = parse_residual_catalog_document(
        value,
        access_mode=access_mode,
        evaluator_authorization=evaluator_authorization,
        allow_blind=allow_blind,
    )
    if expect_regenerated:
        kind = parsed.get("population_kind")
        if kind in POPULATION_KINDS and kind != POPULATION_KIND_PILOT:
            expected = build_plateau_residual_catalog(
                repo_root,
                cases_path=parsed.get("population_path"),  # type: ignore[arg-type]
                population_kind=str(kind),
                l1_by_case=l1_by_case,
                constructor=constructor,
                access_mode=access_mode,
                evaluator_authorization=evaluator_authorization,
                tree_cid=parsed.get("tree_cid")  # type: ignore[arg-type]
                if "tree_cid" in parsed
                else None,
                population_cid=parsed.get("population_cid")  # type: ignore[arg-type]
                if "population_cid" in parsed
                else None,
                assumptions=parsed.get("assumptions")  # type: ignore[arg-type]
                if "assumptions" in parsed
                else None,
            )
        else:
            expected = build_plateau_residual_catalog(
                repo_root,
                l1_by_case=l1_by_case,
                constructor=constructor,
            )
        if parsed != expected:
            raise ResidualCatalogError(
                "catalog does not match regenerated plateau residual catalog"
            )
    return parsed


def load_plateau_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, object]:
    """Load and parse the checked-in CID-bound **pilot** catalog receipt."""

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_CATALOG_RELATIVE_PATH
    )
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    return parse_plateau_residual_catalog(payload)


def load_holdout_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, object]:
    """Load and parse the checked-in CID-bound **holdout** catalog receipt."""

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH
    )
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    return parse_population_residual_catalog(
        payload,
        require_holdout_kind=True,
        access_mode=ACCESS_MODE_SUPERVISOR,
    )


def load_repair_dev_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, object]:
    """Load and parse the checked-in **repair-development** catalog receipt."""

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH
    )
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    return parse_population_residual_catalog(
        payload,
        require_repair_development_kind=True,
        access_mode=ACCESS_MODE_SUPERVISOR,
    )


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )
    if not encoded.endswith("\n"):
        encoded += "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def write_plateau_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
    catalog: Mapping[str, object] | None = None,
    cases_path: str | Path | None = None,
    population_kind: str | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
) -> dict[str, object]:
    """Atomically write a residual catalog JSON receipt.

    Validates with the pilot seal parser when the payload is a pilot catalog,
    otherwise with the population parser.
    """

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_CATALOG_RELATIVE_PATH
    )
    payload = (
        dict(catalog)
        if catalog is not None
        else build_plateau_residual_catalog(
            root,
            cases_path=cases_path,
            population_kind=population_kind,
            l1_by_case=l1_by_case,
            constructor=constructor,
        )
    )
    parse_residual_catalog_document(payload)
    _atomic_write_json(catalog_path, payload)
    return payload


def write_holdout_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
    catalog: Mapping[str, object] | None = None,
    cases: Sequence[MatrixCase] | None = None,
    cases_path: str | Path | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
) -> dict[str, object]:
    """Atomically write the holdout residual catalog JSON receipt."""

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH
    )
    payload = (
        dict(catalog)
        if catalog is not None
        else build_holdout_residual_catalog(
            root,
            cases=cases,
            cases_path=cases_path,
            l1_by_case=l1_by_case,
            constructor=constructor,
        )
    )
    parse_population_residual_catalog(
        payload,
        require_holdout_kind=True,
        access_mode=ACCESS_MODE_SUPERVISOR,
    )
    _atomic_write_json(catalog_path, payload)
    return payload


def write_repair_dev_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
    catalog: Mapping[str, object] | None = None,
    cases: Sequence[MatrixCase] | None = None,
    cases_path: str | Path | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
    tree_cid: str | None = None,
    population_cid: str | None = None,
    assumptions: Sequence[str] | None = None,
    provenance: Mapping[str, object] | None = None,
    case_status_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Atomically write the repair-development residual catalog JSON receipt."""

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH
    )
    payload = (
        dict(catalog)
        if catalog is not None
        else build_repair_dev_residual_catalog(
            root,
            cases=cases,
            cases_path=cases_path,
            l1_by_case=l1_by_case,
            constructor=constructor,
            tree_cid=tree_cid,
            population_cid=population_cid,
            assumptions=assumptions,
            provenance=provenance,
            case_status_overrides=case_status_overrides,
        )
    )
    parse_population_residual_catalog(
        payload,
        require_repair_development_kind=True,
        access_mode=ACCESS_MODE_SUPERVISOR,
    )
    _atomic_write_json(catalog_path, payload)
    return payload


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or validate PlateauResidualCatalog@1"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Catalog JSON path",
    )
    parser.add_argument(
        "--cases-path",
        type=Path,
        default=None,
        help="Preregistered case population JSON path",
    )
    parser.add_argument(
        "--population-kind",
        choices=sorted(POPULATION_KINDS),
        default=None,
        help=(
            "Population kind (pilot, repair_development, "
            "authorized_blind_evaluation, holdout, custom)"
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the checked-in catalog without rebuilding L1",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rebuild from typed_deontic baseline L1 and write the receipt",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repo_root or _repo_root()
    kind = args.population_kind
    if kind == POPULATION_KIND_HOLDOUT:
        default_out = root / DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH
    elif kind == POPULATION_KIND_REPAIR_DEVELOPMENT:
        default_out = root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH
    else:
        default_out = root / DEFAULT_CATALOG_RELATIVE_PATH
    path = args.output or default_out
    if args.validate_only:
        raw = json.loads(path.read_text(encoding="utf-8"))
        catalog = parse_residual_catalog_document(raw)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "catalog_cid": catalog["catalog_cid"],
                    "population_kind": catalog.get(
                        "population_kind", POPULATION_KIND_PILOT
                    ),
                    "total_residual_count": catalog["aggregates"][
                        "total_residual_count"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.write:
        if kind == POPULATION_KIND_HOLDOUT:
            payload = write_holdout_residual_catalog(
                path,
                repo_root=root,
                cases_path=args.cases_path,
            )
        elif kind == POPULATION_KIND_REPAIR_DEVELOPMENT:
            payload = write_repair_dev_residual_catalog(
                path,
                repo_root=root,
                cases_path=args.cases_path,
            )
        else:
            payload = write_plateau_residual_catalog(
                path,
                repo_root=root,
                cases_path=args.cases_path,
                population_kind=kind,
            )
        print(
            json.dumps(
                {
                    "status": "written",
                    "path": str(path),
                    "catalog_cid": payload["catalog_cid"],
                    "population_kind": payload.get(
                        "population_kind", POPULATION_KIND_PILOT
                    ),
                    "total_residual_count": payload["aggregates"][
                        "total_residual_count"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    payload = build_plateau_residual_catalog(
        root,
        cases_path=args.cases_path,
        population_kind=kind,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ACCESS_MODES",
    "ACCESS_MODE_AUTHORIZED_EVALUATOR",
    "ACCESS_MODE_PACKET",
    "ACCESS_MODE_SUPERVISOR",
    "BASELINE_ARM_ID",
    "BASELINE_CONSTRUCTOR_IDENTITY",
    "BASELINE_E2E_MEAN",
    "BASELINE_REPORT_CID",
    "BLIND_POPULATION_KINDS",
    "CATALOG_CID_CODEC",
    "CATALOG_CID_SCOPE",
    "CATALOG_EVALUATION_STATUSES",
    "CATALOG_STATUS_NOT_MEASURED",
    "CATALOG_STATUS_RUNTIME_FAILED",
    "CATALOG_STATUS_SEMANTIC_SCORED",
    "CATALOG_STATUS_UNSUPPORTED",
    "DEFAULT_CATALOG_RELATIVE_PATH",
    "DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH",
    "DEFAULT_REPAIR_DEV_ASSUMPTIONS",
    "DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH",
    "HOLDOUT_BASELINE_E2E_MEAN",
    "HOLDOUT_BASELINE_REPORT_CID",
    "HOLDOUT_CASES_RELATIVE_PATH",
    "NONZERO_PILOT_CASE_IDS",
    "NON_SEMANTIC_CATALOG_STATUSES",
    "NORMAL_ACCESS_MODES",
    "PILOT_CASE_IDS",
    "PILOT_CASES_RELATIVE_PATH",
    "PLATEAU_RESIDUAL_CATALOG_INTERFACE",
    "PLATEAU_RESIDUAL_CATALOG_SCHEMA",
    "POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION",
    "POPULATION_KIND_CUSTOM",
    "POPULATION_KIND_HOLDOUT",
    "POPULATION_KIND_PILOT",
    "POPULATION_KIND_REPAIR_DEVELOPMENT",
    "POPULATION_KINDS",
    "REPAIR_DEV_BASELINE_E2E_MEAN",
    "REPAIR_DEV_BASELINE_REPORT_CID",
    "REPAIR_DEV_CASES_RELATIVE_PATH",
    "RESIDUAL_KIND_EXTRA_RULE",
    "RESIDUAL_KIND_FIELD_MISMATCH",
    "RESIDUAL_KIND_MISSING_RULE",
    "VISIBLE_NON_PILOT_POPULATION_KINDS",
    "ZERO_RESIDUAL_CONTROL_CASE_ID",
    "CaseResidualRecord",
    "ResidualCatalogError",
    "ResidualFacet",
    "aggregate_residuals",
    "assert_access_allows_population",
    "assert_catalog_usable_on_supervisor_path",
    "build_case_residual",
    "build_holdout_residual_catalog",
    "build_plateau_residual_catalog",
    "build_repair_dev_residual_catalog",
    "compute_facet_residuals",
    "construct_baseline_l1",
    "is_blind_population_kind",
    "is_normal_access_mode",
    "load_holdout_matrix_cases",
    "load_holdout_residual_catalog",
    "load_pilot_matrix_cases",
    "load_plateau_residual_catalog",
    "load_population_matrix_cases",
    "load_repair_dev_matrix_cases",
    "load_repair_dev_residual_catalog",
    "parse_plateau_residual_catalog",
    "parse_population_residual_catalog",
    "parse_residual_catalog_document",
    "preregistered_holdout_matrix_cases",
    "reject_blind_material_on_normal_path",
    "suggest_trigger_kind",
    "validate_evaluator_authorization",
    "validate_plateau_residual_catalog",
    "write_holdout_residual_catalog",
    "write_plateau_residual_catalog",
    "write_repair_dev_residual_catalog",
]
