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

``exception_with_window`` is recorded as the zero-residual control case.
Optional spaCy and autoencoder cue slots are placeholders for teacher
pipelines (PLAT-050 / PLAT-060); they never authorize production composition.
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
PILOT_CASES_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/pilot_cases.json"
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
    """All residual facets for one pilot case against baseline L1."""

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _nonblank(self.case_id, "case_id"))
        object.__setattr__(
            self, "forward_loss", _finite_unit(self.forward_loss, "forward_loss")
        )
        residuals = tuple(self.residuals)
        object.__setattr__(self, "residuals", residuals)
        for facet in residuals:
            if facet.case_id != self.case_id:
                raise ResidualCatalogError(
                    "residual case_id must match CaseResidualRecord.case_id"
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
            if self.forward_loss != 0.0 or residuals:
                raise ResidualCatalogError(
                    "zero-residual control must have empty residuals "
                    "and forward_loss 0"
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

    def to_dict(self) -> dict[str, object]:
        return {
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

    @classmethod
    def from_dict(cls, value: object) -> "CaseResidualRecord":
        data = _mapping(value, "case residual")
        residuals = tuple(
            ResidualFacet.from_dict(item)
            for item in _array(data.get("residuals"), "residuals")
        )
        return cls(
            case_id=_nonblank(data.get("case_id"), "case_id"),
            forward_loss=_finite_unit(
                data.get("forward_loss"), "forward_loss"
            ),
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
    """Aggregate case×facet residuals for triggers and edit prioritization."""

    cases = tuple(cases)
    by_case: dict[str, dict[str, object]] = {}
    by_field: Counter[str] = Counter()
    by_field_contrib: dict[str, float] = {}
    by_trigger: Counter[str] = Counter()
    by_trigger_contrib: dict[str, float] = {}
    by_kind: Counter[str] = Counter()
    total_residual_count = 0
    sum_forward = 0.0
    field_paths: list[str] = []

    for record in cases:
        contrib = record.loss_contribution_sum
        by_case[record.case_id] = {
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
        if not record.is_zero_residual_control and record.forward_loss > 0.0
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
            round(sum_forward / case_count, 9) if case_count else 0.0
        ),
        "nonzero_case_count": len(nonzero),
        "nonzero_case_ids": nonzero,
        "sum_forward_loss": round(sum_forward, 9),
        "total_residual_count": total_residual_count,
        "zero_control_case_ids": zero_controls,
        "zero_control_residual_count": sum(
            by_case[case_id]["residual_count"]  # type: ignore[index]
            for case_id in zero_controls
        ),
    }


def load_pilot_matrix_cases(
    repo_root: Path | None = None,
    *,
    path: Path | None = None,
) -> tuple[MatrixCase, ...]:
    """Load the frozen five-case pilot fixture as MatrixCase records."""

    root = repo_root if repo_root is not None else _repo_root()
    fixture_path = path if path is not None else root / PILOT_CASES_RELATIVE_PATH
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ResidualCatalogError("pilot_cases.json must be an array")
    cases = tuple(MatrixCase.from_dict(item) for item in payload)
    observed = tuple(case.case_id for case in cases)
    _require(
        set(observed) == set(PILOT_CASE_IDS) and len(observed) == len(PILOT_CASE_IDS),
        f"pilot fixture case ids changed: {observed}",
    )
    return cases


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


def build_plateau_residual_catalog(
    repo_root: Path | None = None,
    *,
    cases: Sequence[MatrixCase] | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
    baseline_arm_id: str = BASELINE_ARM_ID,
    constructor_identity: str = BASELINE_CONSTRUCTOR_IDENTITY,
    baseline_e2e_mean: float = BASELINE_E2E_MEAN,
    baseline_report_cid: str = BASELINE_REPORT_CID,
    cycle_loss_by_case: Mapping[str, float] | None = None,
    end_to_end_loss_by_case: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Build the CID-bindable plateau residual catalog for pilot cases."""

    root = repo_root if repo_root is not None else _repo_root()
    matrix_cases = (
        tuple(cases)
        if cases is not None
        else load_pilot_matrix_cases(root)
    )
    cycle_loss_by_case = dict(cycle_loss_by_case or {})
    end_to_end_loss_by_case = dict(end_to_end_loss_by_case or {})
    records: list[CaseResidualRecord] = []
    for case in matrix_cases:
        if l1_by_case is not None and case.case_id in l1_by_case:
            l1_value = l1_by_case[case.case_id]
            l1 = (
                l1_value
                if isinstance(l1_value, CanonicalRuleIR)
                else CanonicalRuleIR.from_dict(l1_value)
            )
        else:
            l1 = construct_baseline_l1(case, constructor=constructor)
        records.append(
            build_case_residual(
                case.case_id,
                case.gold_ir,
                l1,
                is_zero_residual_control=(
                    case.case_id == ZERO_RESIDUAL_CONTROL_CASE_ID
                ),
                case_cid=case.case_cid,
                gold_ir_cid=case.gold_ir_cid,
                cycle_loss=cycle_loss_by_case.get(case.case_id),
                end_to_end_loss=end_to_end_loss_by_case.get(case.case_id),
            )
        )

    # Stable pilot order for CID binding.
    order = {case_id: index for index, case_id in enumerate(PILOT_CASE_IDS)}
    records.sort(key=lambda record: order.get(record.case_id, 10_000))

    aggregates = aggregate_residuals(records)
    case_payloads = [record.to_dict() for record in records]
    residual_rows = [
        facet.to_dict()
        for record in records
        for facet in record.residuals
    ]

    payload: dict[str, object] = {
        "aggregates": aggregates,
        "baseline": {
            "arm_id": baseline_arm_id,
            "constructor_identity": constructor_identity,
            "e2e_mean": baseline_e2e_mean,
            "report_cid": baseline_report_cid,
        },
        "cases": case_payloads,
        "interface": PLATEAU_RESIDUAL_CATALOG_INTERFACE,
        "nonzero_pilot_case_ids": list(NONZERO_PILOT_CASE_IDS),
        "pilot_case_ids": list(PILOT_CASE_IDS),
        "residuals": residual_rows,
        "schema_version": PLATEAU_RESIDUAL_CATALOG_SCHEMA,
        "zero_residual_control_case_id": ZERO_RESIDUAL_CONTROL_CASE_ID,
    }
    payload["catalog_cid"] = cid_for_dag_json(
        {key: value for key, value in payload.items() if key != "catalog_cid"}
    )
    payload["catalog_cid_codec"] = CATALOG_CID_CODEC
    payload["catalog_cid_scope"] = CATALOG_CID_SCOPE
    # Re-bind CID over full payload excluding only catalog_cid itself.
    # Codec/scope are part of the bound content for fail-closed verification.
    payload["catalog_cid"] = cid_for_dag_json(
        {key: value for key, value in payload.items() if key != "catalog_cid"}
    )
    return payload


def parse_plateau_residual_catalog(
    value: object,
) -> dict[str, object]:
    """Parse and structurally validate a catalog object without CID rebuild."""

    data = dict(_mapping(value, "plateau residual catalog"))
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
    parsed_rows = [ResidualFacet.from_dict(item) for item in residual_rows]
    expected_rows = [
        facet
        for record in cases
        for facet in record.residuals
    ]
    _require(
        len(parsed_rows) == len(expected_rows),
        "flat residuals length must match nested case residuals",
    )
    aggregates = _mapping(data.get("aggregates"), "aggregates")
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
    return data


def validate_plateau_residual_catalog(
    value: object,
    *,
    repo_root: Path | None = None,
    expect_regenerated: bool = False,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
) -> dict[str, object]:
    """Validate catalog structure and optional exact regeneration."""

    parsed = parse_plateau_residual_catalog(value)
    if expect_regenerated:
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
    """Load and parse the checked-in CID-bound catalog receipt."""

    root = repo_root if repo_root is not None else _repo_root()
    catalog_path = (
        path
        if path is not None
        else root / DEFAULT_CATALOG_RELATIVE_PATH
    )
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    return parse_plateau_residual_catalog(payload)


def write_plateau_residual_catalog(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
    catalog: Mapping[str, object] | None = None,
    l1_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
    constructor: object | None = None,
) -> dict[str, object]:
    """Atomically write the plateau residual catalog JSON receipt."""

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
            l1_by_case=l1_by_case,
            constructor=constructor,
        )
    )
    parse_plateau_residual_catalog(payload)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
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
        prefix=".plateau_residual_catalog.",
        suffix=".json.tmp",
        dir=str(catalog_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, catalog_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
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
    path = args.output or (root / DEFAULT_CATALOG_RELATIVE_PATH)
    if args.validate_only:
        catalog = load_plateau_residual_catalog(path, repo_root=root)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "catalog_cid": catalog["catalog_cid"],
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
        payload = write_plateau_residual_catalog(path, repo_root=root)
        print(
            json.dumps(
                {
                    "status": "written",
                    "path": str(path),
                    "catalog_cid": payload["catalog_cid"],
                    "total_residual_count": payload["aggregates"][
                        "total_residual_count"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    payload = build_plateau_residual_catalog(root)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BASELINE_ARM_ID",
    "BASELINE_CONSTRUCTOR_IDENTITY",
    "BASELINE_E2E_MEAN",
    "BASELINE_REPORT_CID",
    "CATALOG_CID_CODEC",
    "CATALOG_CID_SCOPE",
    "DEFAULT_CATALOG_RELATIVE_PATH",
    "NONZERO_PILOT_CASE_IDS",
    "PILOT_CASE_IDS",
    "PILOT_CASES_RELATIVE_PATH",
    "PLATEAU_RESIDUAL_CATALOG_INTERFACE",
    "PLATEAU_RESIDUAL_CATALOG_SCHEMA",
    "RESIDUAL_KIND_EXTRA_RULE",
    "RESIDUAL_KIND_FIELD_MISMATCH",
    "RESIDUAL_KIND_MISSING_RULE",
    "ZERO_RESIDUAL_CONTROL_CASE_ID",
    "CaseResidualRecord",
    "ResidualCatalogError",
    "ResidualFacet",
    "aggregate_residuals",
    "build_case_residual",
    "build_plateau_residual_catalog",
    "compute_facet_residuals",
    "construct_baseline_l1",
    "load_pilot_matrix_cases",
    "load_plateau_residual_catalog",
    "parse_plateau_residual_catalog",
    "suggest_trigger_kind",
    "validate_plateau_residual_catalog",
    "write_plateau_residual_catalog",
]
