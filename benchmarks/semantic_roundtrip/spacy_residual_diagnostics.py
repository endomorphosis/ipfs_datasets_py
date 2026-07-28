"""spaCy residual diagnostics teacher (PLAT-050).

Exports non-authoritative **polarity**, **source-span**, and **missing-slot**
diagnostic signals for pilot residual catalog / Codex packet rows.

This module is a **teacher sensor** only:

* it reuses :class:`~benchmarks.semantic_roundtrip.constructors.modal_spacy.ModalSpacyCanonicalConstructor`
  and :func:`~benchmarks.semantic_roundtrip.constructors.modal_spacy.polarity_preflight`
  without promoting ``modal_spacy`` to the production constructor;
* every cue and receipt carries ``semantic_authority=false``;
* polarity preflight remains **fail-closed** (inversions, missing candidate,
  or unassigned nonempty gold never pass the gate);
* production composition remains the typed_deontic no-repair baseline arm.

Optional spaCy cue slots on :class:`~benchmarks.semantic_roundtrip.residual_catalog.ResidualFacet`
are filled by this teacher; structural forensics still owns residual kinds and
loss contributions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from benchmarks.semantic_roundtrip.contracts import (
    LIST_FIELDS,
    RULE_FIELDS,
    CanonicalRuleIR,
    ConstructorRequest,
    ContractError,
)
from benchmarks.semantic_roundtrip.constructors.modal_spacy import (
    MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE,
    POLARITY_PREFLIGHT_INTERFACE,
    RESIDUAL_POLARITY_INVERSION_CASE_IDS,
    ModalSpacyCanonicalConstructor,
    ModalSpacyConstruction,
    ModalSpacyConstructorDiagnostics,
    ModalSpacyFrontendStatus,
    SourceSpanDiagnostic,
    polarity_preflight,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    BASELINE_CONSTRUCTOR_IDENTITY,
    CaseResidualRecord,
    NONZERO_PILOT_CASE_IDS,
    PILOT_CASE_IDS,
    ResidualFacet,
    ZERO_RESIDUAL_CONTROL_CASE_ID,
    load_pilot_matrix_cases,
    load_plateau_residual_catalog,
)
from benchmarks.semantic_roundtrip.matrix import MatrixCase


SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE: Final = "SpacyResidualDiagnostics@1"
SPACY_RESIDUAL_CUE_INTERFACE: Final = "SpacyResidualCue@1"
SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE: Final = "SpacyPilotDiagnosticsMap@1"
SPACY_DIAGNOSTIC_RECEIPT_INTERFACE: Final = "SpacyDiagnosticReceipt@1"
SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-spacy-residual-diagnostics.v1"
)

SIGNAL_KIND_POLARITY: Final = "polarity"
SIGNAL_KIND_SPAN: Final = "span"
SIGNAL_KIND_MISSING_SLOT: Final = "missing_slot"
SIGNAL_KINDS: Final = frozenset(
    {
        SIGNAL_KIND_POLARITY,
        SIGNAL_KIND_SPAN,
        SIGNAL_KIND_MISSING_SLOT,
    }
)

TEACHER_IDENTITY: Final = MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE
TEACHER_ROLE: Final = "teacher_residual_only"
PRODUCTION_CONSTRUCTOR_IDENTITY: Final = BASELINE_CONSTRUCTOR_IDENTITY
PRODUCTION_ARM_ID: Final = BASELINE_ARM_ID
PLATEAU_BREAK_TASK_ID: Final = "PLAT-050"
PLATEAU_BREAK_BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-break-v1"

SEMANTIC_AUTHORITY: Final = False
PROMOTION_REQUIRES_FULL_GATES: Final = True
PRODUCTION_DEFAULT_CHANGED: Final = False


class SpacyResidualDiagnosticsError(ContractError):
    """Raised when spaCy residual diagnostics cannot be built or validated."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise SpacyResidualDiagnosticsError(message)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpacyResidualDiagnosticsError(f"{path} must be a nonblank string")
    return value


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SpacyResidualDiagnosticsError(f"{path} must be an object")
    return value


def _coerce_ir(
    value: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    field_name: str,
    allow_none: bool = False,
) -> CanonicalRuleIR | None:
    if value is None:
        if allow_none:
            return None
        raise SpacyResidualDiagnosticsError(f"{field_name} is required")
    if isinstance(value, CanonicalRuleIR):
        return value
    if isinstance(value, Mapping):
        return CanonicalRuleIR.from_dict(value)
    raise SpacyResidualDiagnosticsError(
        f"{field_name} must be CanonicalRuleIR or object"
    )


def _is_empty_field_value(field_name: str, value: object) -> bool:
    if field_name in LIST_FIELDS:
        return not value
    return value in ("", None)


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def production_path_is_typed_deontic_no_repair(
    arm_id: str = PRODUCTION_ARM_ID,
) -> bool:
    """True when the production composition arm remains the sealed baseline."""

    return (
        arm_id == PRODUCTION_ARM_ID
        and "typed_deontic" in arm_id
        and "no_repair" in arm_id
        and PRODUCTION_DEFAULT_CHANGED is False
        and PRODUCTION_CONSTRUCTOR_IDENTITY
        == "TypedDeonticCanonicalConstructor@1"
    )


def assert_production_default_unchanged() -> None:
    """Fail closed if this teacher ever claims production constructor status."""

    _require(
        PRODUCTION_DEFAULT_CHANGED is False,
        "spaCy residual diagnostics must not change production defaults",
    )
    _require(
        production_path_is_typed_deontic_no_repair(),
        "production path must remain typed_deontic no-repair baseline",
    )
    _require(
        TEACHER_IDENTITY != PRODUCTION_CONSTRUCTOR_IDENTITY,
        "modal_spacy teacher must not equal production constructor identity",
    )
    _require(
        SEMANTIC_AUTHORITY is False,
        "spaCy residual diagnostics must not claim semantic_authority",
    )


@dataclass(frozen=True, slots=True)
class PolaritySignal:
    """One assigned-rule polarity / modality preservation diagnostic."""

    field_path: str
    signal_kind: str = SIGNAL_KIND_POLARITY
    reference_index: int | None = None
    candidate_index: int | None = None
    gold_modality: str | None = None
    candidate_modality: str | None = None
    modality_preserved: bool = False
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "field_path", _nonblank(self.field_path, "field_path")
        )
        if self.signal_kind != SIGNAL_KIND_POLARITY:
            raise SpacyResidualDiagnosticsError(
                "PolaritySignal.signal_kind must be 'polarity'"
            )
        for name in ("reference_index", "candidate_index"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise SpacyResidualDiagnosticsError(
                    f"{name} must be a nonnegative integer or null"
                )
        if not isinstance(self.modality_preserved, bool):
            raise SpacyResidualDiagnosticsError(
                "modality_preserved must be a boolean"
            )
        for name in ("gold_modality", "candidate_modality", "detail"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise SpacyResidualDiagnosticsError(
                    f"{name} must be a nonblank string or null"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_index": self.candidate_index,
            "candidate_modality": self.candidate_modality,
            "detail": self.detail,
            "field_path": self.field_path,
            "gold_modality": self.gold_modality,
            "modality_preserved": self.modality_preserved,
            "reference_index": self.reference_index,
            "signal_kind": self.signal_kind,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PolaritySignal":
        data = _mapping(value, "polarity signal")
        return cls(
            field_path=_nonblank(data.get("field_path"), "field_path"),
            signal_kind=str(
                data.get("signal_kind") or SIGNAL_KIND_POLARITY
            ),
            reference_index=data.get("reference_index"),
            candidate_index=data.get("candidate_index"),
            gold_modality=data.get("gold_modality"),
            candidate_modality=data.get("candidate_modality"),
            modality_preserved=bool(data.get("modality_preserved")),
            detail=data.get("detail"),
        )


@dataclass(frozen=True, slots=True)
class SpanSignal:
    """Hash-bound source-span evidence retained outside the realizer path."""

    field_path: str
    formula_id: str
    source_id: str
    start_char: int
    end_char: int
    source_span_sha256: str
    structural_signature: str = ""
    signal_kind: str = SIGNAL_KIND_SPAN
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "field_path", _nonblank(self.field_path, "field_path")
        )
        object.__setattr__(
            self, "formula_id", _nonblank(self.formula_id, "formula_id")
        )
        if not isinstance(self.source_id, str):
            raise SpacyResidualDiagnosticsError("source_id must be a string")
        if self.signal_kind != SIGNAL_KIND_SPAN:
            raise SpacyResidualDiagnosticsError(
                "SpanSignal.signal_kind must be 'span'"
            )
        if (
            isinstance(self.start_char, bool)
            or not isinstance(self.start_char, int)
            or self.start_char < 0
            or isinstance(self.end_char, bool)
            or not isinstance(self.end_char, int)
            or self.end_char < self.start_char
        ):
            raise SpacyResidualDiagnosticsError(
                "source-span offsets are invalid"
            )
        if not isinstance(self.source_span_sha256, str):
            raise SpacyResidualDiagnosticsError(
                "source_span_sha256 must be a string"
            )
        if not isinstance(self.structural_signature, str):
            raise SpacyResidualDiagnosticsError(
                "structural_signature must be a string"
            )
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise SpacyResidualDiagnosticsError(
                "detail must be a nonblank string or null"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "detail": self.detail,
            "end_char": self.end_char,
            "field_path": self.field_path,
            "formula_id": self.formula_id,
            "signal_kind": self.signal_kind,
            "source_id": self.source_id,
            "source_span_sha256": self.source_span_sha256,
            "start_char": self.start_char,
            "structural_signature": self.structural_signature,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SpanSignal":
        data = _mapping(value, "span signal")
        return cls(
            field_path=_nonblank(data.get("field_path"), "field_path"),
            formula_id=_nonblank(data.get("formula_id"), "formula_id"),
            source_id=str(data.get("source_id") or ""),
            start_char=int(data.get("start_char", 0)),
            end_char=int(data.get("end_char", 0)),
            source_span_sha256=str(data.get("source_span_sha256") or ""),
            structural_signature=str(
                data.get("structural_signature") or ""
            ),
            signal_kind=str(data.get("signal_kind") or SIGNAL_KIND_SPAN),
            detail=data.get("detail"),
        )

    @classmethod
    def from_source_span(
        cls,
        span: SourceSpanDiagnostic,
        *,
        field_path: str | None = None,
        rule_index: int | None = None,
    ) -> "SpanSignal":
        if not isinstance(span, SourceSpanDiagnostic):
            raise SpacyResidualDiagnosticsError(
                "span must be SourceSpanDiagnostic"
            )
        if field_path is None:
            if rule_index is not None:
                field_path = f"rules[{rule_index}]"
            else:
                field_path = f"formulas[{span.formula_id}]"
        return cls(
            field_path=field_path,
            formula_id=span.formula_id,
            source_id=span.source_id,
            start_char=span.start_char,
            end_char=span.end_char,
            source_span_sha256=span.source_span_sha256,
            structural_signature=span.structural_signature,
        )


@dataclass(frozen=True, slots=True)
class MissingSlotSignal:
    """Gold-filled slot that is empty (or absent) on the candidate IR."""

    field_path: str
    canonical_field: str | None
    gold_value: object
    candidate_value: object = None
    reference_index: int | None = None
    candidate_index: int | None = None
    residual_kind: str = "field_mismatch"
    signal_kind: str = SIGNAL_KIND_MISSING_SLOT
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "field_path", _nonblank(self.field_path, "field_path")
        )
        if self.signal_kind != SIGNAL_KIND_MISSING_SLOT:
            raise SpacyResidualDiagnosticsError(
                "MissingSlotSignal.signal_kind must be 'missing_slot'"
            )
        if self.canonical_field is not None and (
            self.canonical_field not in RULE_FIELDS
        ):
            raise SpacyResidualDiagnosticsError(
                f"unknown canonical_field: {self.canonical_field!r}"
            )
        for name in ("reference_index", "candidate_index"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise SpacyResidualDiagnosticsError(
                    f"{name} must be a nonnegative integer or null"
                )
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise SpacyResidualDiagnosticsError(
                "detail must be a nonblank string or null"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_index": self.candidate_index,
            "candidate_value": _plain_json(self.candidate_value),
            "canonical_field": self.canonical_field,
            "detail": self.detail,
            "field_path": self.field_path,
            "gold_value": _plain_json(self.gold_value),
            "reference_index": self.reference_index,
            "residual_kind": self.residual_kind,
            "signal_kind": self.signal_kind,
        }

    @classmethod
    def from_dict(cls, value: object) -> "MissingSlotSignal":
        data = _mapping(value, "missing-slot signal")
        return cls(
            field_path=_nonblank(data.get("field_path"), "field_path"),
            canonical_field=data.get("canonical_field"),
            gold_value=data.get("gold_value"),
            candidate_value=data.get("candidate_value"),
            reference_index=data.get("reference_index"),
            candidate_index=data.get("candidate_index"),
            residual_kind=str(
                data.get("residual_kind") or "field_mismatch"
            ),
            signal_kind=str(
                data.get("signal_kind") or SIGNAL_KIND_MISSING_SLOT
            ),
            detail=data.get("detail"),
        )


@dataclass(frozen=True, slots=True)
class CaseSpacyDiagnostics:
    """Polarity / span / missing-slot signals for one pilot (or research) case."""

    case_id: str
    polarity_signals: tuple[PolaritySignal, ...]
    span_signals: tuple[SpanSignal, ...]
    missing_slot_signals: tuple[MissingSlotSignal, ...]
    polarity_preflight: Mapping[str, object]
    polarity_gate_passed: bool
    evaluated: bool
    frontend_status: str | None = None
    residual_polarity_inversion_documented: bool = False
    semantic_authority: bool = False
    promotion_requires_full_gates: bool = True
    teacher_identity: str = TEACHER_IDENTITY
    teacher_role: str = TEACHER_ROLE
    production_arm_id: str = PRODUCTION_ARM_ID
    interface: str = SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _nonblank(self.case_id, "case_id"))
        object.__setattr__(
            self, "polarity_signals", tuple(self.polarity_signals)
        )
        object.__setattr__(self, "span_signals", tuple(self.span_signals))
        object.__setattr__(
            self, "missing_slot_signals", tuple(self.missing_slot_signals)
        )
        if not all(
            isinstance(item, PolaritySignal) for item in self.polarity_signals
        ):
            raise SpacyResidualDiagnosticsError(
                "polarity_signals must contain PolaritySignal values"
            )
        if not all(isinstance(item, SpanSignal) for item in self.span_signals):
            raise SpacyResidualDiagnosticsError(
                "span_signals must contain SpanSignal values"
            )
        if not all(
            isinstance(item, MissingSlotSignal)
            for item in self.missing_slot_signals
        ):
            raise SpacyResidualDiagnosticsError(
                "missing_slot_signals must contain MissingSlotSignal values"
            )
        preflight = dict(_mapping(self.polarity_preflight, "polarity_preflight"))
        object.__setattr__(
            self, "polarity_preflight", MappingProxyType(preflight)
        )
        if not isinstance(self.polarity_gate_passed, bool):
            raise SpacyResidualDiagnosticsError(
                "polarity_gate_passed must be a boolean"
            )
        if not isinstance(self.evaluated, bool):
            raise SpacyResidualDiagnosticsError("evaluated must be a boolean")
        # Fail-closed alignment with ModalSpacyPolarityPreflight@1.
        preflight_passed = bool(preflight.get("gate_passed"))
        if preflight_passed != self.polarity_gate_passed:
            raise SpacyResidualDiagnosticsError(
                "polarity_gate_passed must match polarity_preflight.gate_passed"
            )
        if preflight.get("interface") not in {
            None,
            POLARITY_PREFLIGHT_INTERFACE,
        }:
            raise SpacyResidualDiagnosticsError(
                "polarity_preflight.interface mismatch"
            )
        if self.semantic_authority is not False:
            raise SpacyResidualDiagnosticsError(
                "spaCy diagnostics must not claim semantic_authority"
            )
        if self.promotion_requires_full_gates is not True:
            raise SpacyResidualDiagnosticsError(
                "promotion_requires_full_gates must remain True"
            )
        object.__setattr__(
            self,
            "teacher_identity",
            _nonblank(self.teacher_identity, "teacher_identity"),
        )
        object.__setattr__(
            self, "teacher_role", _nonblank(self.teacher_role, "teacher_role")
        )
        object.__setattr__(
            self,
            "production_arm_id",
            _nonblank(self.production_arm_id, "production_arm_id"),
        )
        object.__setattr__(
            self, "interface", _nonblank(self.interface, "interface")
        )
        if self.frontend_status is not None:
            object.__setattr__(
                self,
                "frontend_status",
                _nonblank(self.frontend_status, "frontend_status"),
            )
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise SpacyResidualDiagnosticsError(
                "detail must be a nonblank string or null"
            )

    @property
    def signal_kinds_present(self) -> tuple[str, ...]:
        kinds: list[str] = []
        if self.polarity_signals:
            kinds.append(SIGNAL_KIND_POLARITY)
        if self.span_signals:
            kinds.append(SIGNAL_KIND_SPAN)
        if self.missing_slot_signals:
            kinds.append(SIGNAL_KIND_MISSING_SLOT)
        return tuple(kinds)

    @property
    def polarity_signal_count(self) -> int:
        return len(self.polarity_signals)

    @property
    def span_signal_count(self) -> int:
        return len(self.span_signals)

    @property
    def missing_slot_signal_count(self) -> int:
        return len(self.missing_slot_signals)

    @property
    def has_polarity_inversion(self) -> bool:
        return any(not item.modality_preserved for item in self.polarity_signals)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "detail": self.detail,
            "evaluated": self.evaluated,
            "frontend_status": self.frontend_status,
            "has_polarity_inversion": self.has_polarity_inversion,
            "interface": self.interface,
            "missing_slot_signal_count": self.missing_slot_signal_count,
            "missing_slot_signals": [
                item.to_dict() for item in self.missing_slot_signals
            ],
            "polarity_gate_passed": self.polarity_gate_passed,
            "polarity_preflight": dict(self.polarity_preflight),
            "polarity_signal_count": self.polarity_signal_count,
            "polarity_signals": [
                item.to_dict() for item in self.polarity_signals
            ],
            "production_arm_id": self.production_arm_id,
            "promotion_requires_full_gates": self.promotion_requires_full_gates,
            "residual_polarity_inversion_documented": (
                self.residual_polarity_inversion_documented
            ),
            "semantic_authority": False,
            "signal_kinds_present": list(self.signal_kinds_present),
            "span_signal_count": self.span_signal_count,
            "span_signals": [item.to_dict() for item in self.span_signals],
            "teacher_identity": self.teacher_identity,
            "teacher_role": self.teacher_role,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CaseSpacyDiagnostics":
        data = _mapping(value, "case spaCy diagnostics")
        return cls(
            case_id=_nonblank(data.get("case_id"), "case_id"),
            polarity_signals=tuple(
                item
                if isinstance(item, PolaritySignal)
                else PolaritySignal.from_dict(item)
                for item in data.get("polarity_signals", ())
            ),
            span_signals=tuple(
                item
                if isinstance(item, SpanSignal)
                else SpanSignal.from_dict(item)
                for item in data.get("span_signals", ())
            ),
            missing_slot_signals=tuple(
                item
                if isinstance(item, MissingSlotSignal)
                else MissingSlotSignal.from_dict(item)
                for item in data.get("missing_slot_signals", ())
            ),
            polarity_preflight=_mapping(
                data.get("polarity_preflight") or {},
                "polarity_preflight",
            ),
            polarity_gate_passed=bool(data.get("polarity_gate_passed")),
            evaluated=bool(data.get("evaluated")),
            frontend_status=data.get("frontend_status"),
            residual_polarity_inversion_documented=bool(
                data.get("residual_polarity_inversion_documented")
            ),
            semantic_authority=bool(data.get("semantic_authority", False)),
            promotion_requires_full_gates=bool(
                data.get("promotion_requires_full_gates", True)
            ),
            teacher_identity=str(
                data.get("teacher_identity") or TEACHER_IDENTITY
            ),
            teacher_role=str(data.get("teacher_role") or TEACHER_ROLE),
            production_arm_id=str(
                data.get("production_arm_id") or PRODUCTION_ARM_ID
            ),
            interface=str(
                data.get("interface") or SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE
            ),
            detail=data.get("detail"),
        )


def compute_polarity_signals(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    candidate_ir: CanonicalRuleIR | Mapping[str, object] | None,
) -> tuple[PolaritySignal, ...]:
    """Emit polarity signals for every gold rule on the optimal assignment."""

    gold = _coerce_ir(gold_ir, field_name="gold_ir")
    assert gold is not None
    candidate = _coerce_ir(
        candidate_ir, field_name="candidate_ir", allow_none=True
    )
    if candidate is None:
        return (
            PolaritySignal(
                field_path="rules",
                reference_index=None,
                candidate_index=None,
                modality_preserved=False,
                detail="candidate IR is missing",
            ),
        )
    comparison = compare_semantic_ir(gold, candidate)
    matches = comparison["matches"]
    assert isinstance(matches, list)
    matched_left = {
        int(match["reference_index"])
        for match in matches
        if match.get("reference_index") is not None
    }
    signals: list[PolaritySignal] = []
    for match in matches:
        ref_index = int(match["reference_index"])
        cand_index = int(match["candidate_index"])
        preserved = bool(match["modality_preserved"])
        gold_mod = gold.rules[ref_index].modality
        cand_mod = candidate.rules[cand_index].modality
        signals.append(
            PolaritySignal(
                field_path=f"rules[{ref_index}].modality",
                reference_index=ref_index,
                candidate_index=cand_index,
                gold_modality=gold_mod,
                candidate_modality=cand_mod,
                modality_preserved=preserved,
                detail=(
                    None
                    if preserved
                    else "modality not preserved on optimal assignment"
                ),
            )
        )
    for ref_index, rule in enumerate(gold.rules):
        if ref_index in matched_left:
            continue
        signals.append(
            PolaritySignal(
                field_path=f"rules[{ref_index}].modality",
                reference_index=ref_index,
                candidate_index=None,
                gold_modality=rule.modality,
                candidate_modality=None,
                modality_preserved=False,
                detail="gold rule unassigned; polarity fail-closed",
            )
        )
    signals.sort(
        key=lambda item: (
            item.reference_index is None,
            item.reference_index if item.reference_index is not None else -1,
            item.field_path,
        )
    )
    return tuple(signals)


def compute_missing_slot_signals(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    candidate_ir: CanonicalRuleIR | Mapping[str, object] | None,
) -> tuple[MissingSlotSignal, ...]:
    """Emit missing-slot signals for empty candidate fields / missing rules."""

    gold = _coerce_ir(gold_ir, field_name="gold_ir")
    assert gold is not None
    candidate = _coerce_ir(
        candidate_ir, field_name="candidate_ir", allow_none=True
    )
    if candidate is None:
        return tuple(
            MissingSlotSignal(
                field_path=f"rules[{index}]",
                canonical_field=None,
                gold_value=rule.to_dict(),
                candidate_value=None,
                reference_index=index,
                residual_kind="missing_rule",
                detail="candidate IR is missing",
            )
            for index, rule in enumerate(gold.rules)
        )
    comparison = compare_semantic_ir(gold, candidate)
    matches = comparison["matches"]
    assert isinstance(matches, list)
    matched_left = {
        int(match["reference_index"])
        for match in matches
        if match.get("reference_index") is not None
    }
    signals: list[MissingSlotSignal] = []
    for match in matches:
        ref_index = int(match["reference_index"])
        cand_index = int(match["candidate_index"])
        left_rule = gold.rules[ref_index]
        right_rule = candidate.rules[cand_index]
        for field_name in RULE_FIELDS:
            gold_value = getattr(left_rule, field_name)
            cand_value = getattr(right_rule, field_name)
            if _is_empty_field_value(field_name, gold_value):
                continue
            if not _is_empty_field_value(field_name, cand_value):
                continue
            signals.append(
                MissingSlotSignal(
                    field_path=f"rules[{ref_index}].{field_name}",
                    canonical_field=field_name,
                    gold_value=(
                        list(gold_value)
                        if isinstance(gold_value, tuple)
                        else gold_value
                    ),
                    candidate_value=(
                        list(cand_value)
                        if isinstance(cand_value, tuple)
                        else cand_value
                    ),
                    reference_index=ref_index,
                    candidate_index=cand_index,
                    residual_kind="field_mismatch",
                    detail=f"candidate slot {field_name!r} is empty",
                )
            )
    for ref_index, rule in enumerate(gold.rules):
        if ref_index in matched_left:
            continue
        signals.append(
            MissingSlotSignal(
                field_path=f"rules[{ref_index}]",
                canonical_field=None,
                gold_value=rule.to_dict(),
                candidate_value=None,
                reference_index=ref_index,
                residual_kind="missing_rule",
                detail="gold rule missing from candidate assignment",
            )
        )
    signals.sort(
        key=lambda item: (
            item.reference_index is None,
            item.reference_index if item.reference_index is not None else -1,
            item.field_path,
        )
    )
    return tuple(signals)


def compute_span_signals(
    source_spans: Sequence[SourceSpanDiagnostic | Mapping[str, object]] = (),
    *,
    candidate_ir: CanonicalRuleIR | Mapping[str, object] | None = None,
) -> tuple[SpanSignal, ...]:
    """Project constructor-private source spans into residual-row span signals."""

    candidate = _coerce_ir(
        candidate_ir, field_name="candidate_ir", allow_none=True
    )
    signals: list[SpanSignal] = []
    for index, raw in enumerate(source_spans):
        if isinstance(raw, SourceSpanDiagnostic):
            span = raw
        elif isinstance(raw, Mapping):
            span = SourceSpanDiagnostic(
                formula_id=str(raw.get("formula_id") or f"formula-{index}"),
                source_id=str(raw.get("source_id") or ""),
                start_char=int(raw.get("start_char") or 0),
                end_char=int(raw.get("end_char") or 0),
                source_span_sha256=str(raw.get("source_span_sha256") or ""),
                structural_signature=str(
                    raw.get("structural_signature") or ""
                ),
            )
        else:
            raise SpacyResidualDiagnosticsError(
                "source_spans must be SourceSpanDiagnostic or objects"
            )
        rule_index = index if candidate is not None and index < len(
            candidate.rules
        ) else None
        signals.append(
            SpanSignal.from_source_span(span, rule_index=rule_index)
        )
    signals.sort(
        key=lambda item: (item.start_char, item.end_char, item.formula_id)
    )
    return tuple(signals)


def diagnose_ir_pair(
    case_id: str,
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    candidate_ir: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    source_spans: Sequence[SourceSpanDiagnostic | Mapping[str, object]] = (),
    frontend_status: str | ModalSpacyFrontendStatus | None = None,
    detail: str | None = None,
) -> CaseSpacyDiagnostics:
    """Build polarity / span / missing-slot diagnostics for one IR pair.

    Polarity preflight is always applied fail-closed: a missing candidate,
    empty assignment against nonempty gold, or modality inversion yields
    ``polarity_gate_passed=False``.
    """

    assert_production_default_unchanged()
    case_id = _nonblank(case_id, "case_id")
    gold = _coerce_ir(gold_ir, field_name="gold_ir")
    assert gold is not None
    candidate = _coerce_ir(
        candidate_ir, field_name="candidate_ir", allow_none=True
    )
    preflight = polarity_preflight(gold, candidate)
    # Teacher must never widen a closed gate.
    gate_passed = bool(preflight.get("gate_passed"))
    if not gate_passed:
        preflight = dict(preflight)
        preflight["gate_passed"] = False
        preflight["all_assigned_preserved"] = False
    polarity = compute_polarity_signals(gold, candidate)
    missing = compute_missing_slot_signals(gold, candidate)
    spans = compute_span_signals(source_spans, candidate_ir=candidate)
    residual_documented = case_id in RESIDUAL_POLARITY_INVERSION_CASE_IDS
    status_value: str | None
    if frontend_status is None:
        status_value = None
    elif isinstance(frontend_status, ModalSpacyFrontendStatus):
        status_value = frontend_status.value
    else:
        status_value = _nonblank(frontend_status, "frontend_status")
    return CaseSpacyDiagnostics(
        case_id=case_id,
        polarity_signals=polarity,
        span_signals=spans,
        missing_slot_signals=missing,
        polarity_preflight=preflight,
        polarity_gate_passed=gate_passed,
        evaluated=bool(preflight.get("evaluated")),
        frontend_status=status_value,
        residual_polarity_inversion_documented=residual_documented,
        detail=detail,
    )


def diagnose_modal_spacy_construction(
    case_id: str,
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    construction: ModalSpacyConstruction,
) -> CaseSpacyDiagnostics:
    """Diagnose one modal_spacy construction against gold (teacher path only)."""

    if not isinstance(construction, ModalSpacyConstruction):
        raise SpacyResidualDiagnosticsError(
            "construction must be ModalSpacyConstruction"
        )
    diagnostics = construction.diagnostics
    if not isinstance(diagnostics, ModalSpacyConstructorDiagnostics):
        raise SpacyResidualDiagnosticsError(
            "construction.diagnostics must be ModalSpacyConstructorDiagnostics"
        )
    result = construction.result
    candidate = result.canonical_ir
    detail = diagnostics.detail or result.failure_detail
    if result.canonical_ir is None and result.failure_detail:
        detail = result.failure_detail
    return diagnose_ir_pair(
        case_id,
        gold_ir,
        candidate,
        source_spans=diagnostics.source_spans,
        frontend_status=diagnostics.frontend_status,
        detail=detail,
    )


def diagnose_matrix_case(
    case: MatrixCase,
    *,
    constructor: ModalSpacyCanonicalConstructor | None = None,
    candidate_ir: CanonicalRuleIR | Mapping[str, object] | None = None,
    source_spans: Sequence[SourceSpanDiagnostic | Mapping[str, object]] = (),
    construct: bool = True,
) -> CaseSpacyDiagnostics:
    """Diagnose one sealed pilot matrix case.

    When ``construct`` is true (default) and no candidate is supplied, the
    modal_spacy constructor is invoked as a **teacher** only.  Failures and
    unavailable frontends fail closed on polarity without changing production
    defaults.
    """

    if not isinstance(case, MatrixCase):
        raise SpacyResidualDiagnosticsError("case must be MatrixCase")
    if candidate_ir is not None:
        return diagnose_ir_pair(
            case.case_id,
            case.gold_ir,
            candidate_ir,
            source_spans=source_spans,
        )
    if not construct:
        return diagnose_ir_pair(
            case.case_id,
            case.gold_ir,
            None,
            source_spans=source_spans,
            detail="candidate IR withheld; polarity fail-closed",
        )
    if constructor is None:
        constructor = ModalSpacyCanonicalConstructor()
    construction = constructor.construct_with_diagnostics(
        ConstructorRequest(
            case.source_text,
            case.allowed_atom_vocabulary,
            {},
        )
    )
    return diagnose_modal_spacy_construction(
        case.case_id, case.gold_ir, construction
    )


def spacy_cue_from_signals(
    *,
    polarity: PolaritySignal | None = None,
    span: SpanSignal | None = None,
    missing_slot: MissingSlotSignal | None = None,
    polarity_preflight_gate_passed: bool | None = None,
    case_id: str | None = None,
) -> dict[str, object]:
    """Build one non-authoritative ResidualFacet.spacy_cue object."""

    assert_production_default_unchanged()
    kinds: list[str] = []
    if polarity is not None:
        kinds.append(SIGNAL_KIND_POLARITY)
    if span is not None:
        kinds.append(SIGNAL_KIND_SPAN)
    if missing_slot is not None:
        kinds.append(SIGNAL_KIND_MISSING_SLOT)
    if not kinds:
        raise SpacyResidualDiagnosticsError(
            "spacy cue requires at least one signal"
        )
    cue: dict[str, object] = {
        "interface": SPACY_RESIDUAL_CUE_INTERFACE,
        "semantic_authority": False,
        "teacher_identity": TEACHER_IDENTITY,
        "teacher_role": TEACHER_ROLE,
        "promotion_requires_full_gates": True,
        "production_default_changed": False,
        "signal_kinds": kinds,
        "polarity": None if polarity is None else polarity.to_dict(),
        "span": None if span is None else span.to_dict(),
        "missing_slot": (
            None if missing_slot is None else missing_slot.to_dict()
        ),
    }
    if polarity_preflight_gate_passed is not None:
        cue["polarity_preflight_gate_passed"] = bool(
            polarity_preflight_gate_passed
        )
    if case_id is not None:
        cue["case_id"] = _nonblank(case_id, "case_id")
    return cue


def spacy_cues_by_field_path(
    diagnostics: CaseSpacyDiagnostics,
) -> dict[str, dict[str, object]]:
    """Project case diagnostics into field_path → spacy_cue for residual attach."""

    if not isinstance(diagnostics, CaseSpacyDiagnostics):
        raise SpacyResidualDiagnosticsError(
            "diagnostics must be CaseSpacyDiagnostics"
        )
    by_path: dict[str, dict[str, object]] = {}
    polarity_by_path = {
        item.field_path: item for item in diagnostics.polarity_signals
    }
    span_by_path = {item.field_path: item for item in diagnostics.span_signals}
    missing_by_path = {
        item.field_path: item for item in diagnostics.missing_slot_signals
    }
    field_paths = sorted(
        set(polarity_by_path) | set(span_by_path) | set(missing_by_path)
    )
    for path in field_paths:
        by_path[path] = spacy_cue_from_signals(
            polarity=polarity_by_path.get(path),
            span=span_by_path.get(path),
            missing_slot=missing_by_path.get(path),
            polarity_preflight_gate_passed=diagnostics.polarity_gate_passed,
            case_id=diagnostics.case_id,
        )
    return by_path


def attach_spacy_cues_to_facets(
    facets: Sequence[ResidualFacet],
    cues_by_field_path: Mapping[str, Mapping[str, object]],
) -> tuple[ResidualFacet, ...]:
    """Return residual facets with non-authoritative spaCy cues attached.

    Existing structural fields are preserved.  Facets without a matching cue
    keep ``spacy_cue=None``.  Cues never alter loss contributions.
    """

    attached: list[ResidualFacet] = []
    for facet in facets:
        if not isinstance(facet, ResidualFacet):
            raise SpacyResidualDiagnosticsError(
                "facets must be ResidualFacet values"
            )
        cue = cues_by_field_path.get(facet.field_path)
        if cue is None:
            # Also try parent rule path for whole-rule span / missing-rule cues.
            parent = None
            if "." in facet.field_path:
                parent = facet.field_path.rsplit(".", 1)[0]
            if parent is not None:
                cue = cues_by_field_path.get(parent)
        if cue is None:
            attached.append(facet)
            continue
        payload = dict(cue)
        if payload.get("semantic_authority") is not False:
            raise SpacyResidualDiagnosticsError(
                "attached spaCy cue must set semantic_authority=false"
            )
        attached.append(
            ResidualFacet(
                case_id=facet.case_id,
                field_path=facet.field_path,
                residual_kind=facet.residual_kind,
                loss_contribution=facet.loss_contribution,
                similarity=facet.similarity,
                suggested_trigger_kind=facet.suggested_trigger_kind,
                canonical_field=facet.canonical_field,
                gold_rule_index=facet.gold_rule_index,
                candidate_rule_index=facet.candidate_rule_index,
                gold_value=facet.gold_value,
                candidate_value=facet.candidate_value,
                rule_match_score=facet.rule_match_score,
                spacy_cue=payload,
                ae_cue=None if facet.ae_cue is None else dict(facet.ae_cue),
            )
        )
    return tuple(attached)


def attach_spacy_diagnostics_to_case_residual(
    case: CaseResidualRecord,
    diagnostics: CaseSpacyDiagnostics,
) -> CaseResidualRecord:
    """Attach spaCy cues onto one case residual record's facets."""

    if not isinstance(case, CaseResidualRecord):
        raise SpacyResidualDiagnosticsError(
            "case must be CaseResidualRecord"
        )
    if diagnostics.case_id != case.case_id:
        raise SpacyResidualDiagnosticsError(
            "diagnostics.case_id must match residual case_id"
        )
    cues = spacy_cues_by_field_path(diagnostics)
    return CaseResidualRecord(
        case_id=case.case_id,
        forward_loss=case.forward_loss,
        residuals=attach_spacy_cues_to_facets(case.residuals, cues),
        is_zero_residual_control=case.is_zero_residual_control,
        case_cid=case.case_cid,
        gold_ir_cid=case.gold_ir_cid,
        l1_cid=case.l1_cid,
        gold_rule_count=case.gold_rule_count,
        l1_rule_count=case.l1_rule_count,
        cycle_loss=case.cycle_loss,
        end_to_end_loss=case.end_to_end_loss,
    )


@dataclass(frozen=True, slots=True)
class SpacyPilotDiagnosticsMap:
    """Full pilot set of spaCy residual diagnostics (teacher receipt body)."""

    cases: tuple[CaseSpacyDiagnostics, ...]
    catalog_cid: str | None = None
    production_arm_id: str = PRODUCTION_ARM_ID
    production_constructor_identity: str = PRODUCTION_CONSTRUCTOR_IDENTITY
    production_default_changed: bool = False
    semantic_authority: bool = False
    interface: str = SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE
    schema_version: str = SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA
    task_id: str = PLATEAU_BREAK_TASK_ID
    board_namespace: str = PLATEAU_BREAK_BOARD_NAMESPACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        if not self.cases:
            raise SpacyResidualDiagnosticsError(
                "pilot diagnostics map requires case records"
            )
        if not all(
            isinstance(item, CaseSpacyDiagnostics) for item in self.cases
        ):
            raise SpacyResidualDiagnosticsError(
                "cases must be CaseSpacyDiagnostics records"
            )
        observed = tuple(item.case_id for item in self.cases)
        if len(set(observed)) != len(observed):
            raise SpacyResidualDiagnosticsError(
                "pilot diagnostics map case_ids must be unique"
            )
        if self.semantic_authority is not False:
            raise SpacyResidualDiagnosticsError(
                "pilot diagnostics map must not claim semantic_authority"
            )
        if self.production_default_changed is not False:
            raise SpacyResidualDiagnosticsError(
                "production_default_changed must remain false"
            )
        object.__setattr__(
            self,
            "production_arm_id",
            _nonblank(self.production_arm_id, "production_arm_id"),
        )
        object.__setattr__(
            self,
            "production_constructor_identity",
            _nonblank(
                self.production_constructor_identity,
                "production_constructor_identity",
            ),
        )
        object.__setattr__(
            self, "interface", _nonblank(self.interface, "interface")
        )
        object.__setattr__(
            self,
            "schema_version",
            _nonblank(self.schema_version, "schema_version"),
        )
        if self.catalog_cid is not None:
            object.__setattr__(
                self, "catalog_cid", _nonblank(self.catalog_cid, "catalog_cid")
            )

    def by_case_id(self) -> Mapping[str, CaseSpacyDiagnostics]:
        return MappingProxyType({item.case_id: item for item in self.cases})

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.cases)

    @property
    def polarity_gate_passed_case_ids(self) -> tuple[str, ...]:
        return tuple(
            item.case_id for item in self.cases if item.polarity_gate_passed
        )

    @property
    def polarity_gate_failed_case_ids(self) -> tuple[str, ...]:
        return tuple(
            item.case_id for item in self.cases if not item.polarity_gate_passed
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "board_namespace": self.board_namespace,
            "cases": [item.to_dict() for item in self.cases],
            "catalog_cid": self.catalog_cid,
            "interface": self.interface,
            "pilot_case_ids": list(self.case_ids),
            "polarity_gate_failed_case_ids": list(
                self.polarity_gate_failed_case_ids
            ),
            "polarity_gate_passed_case_ids": list(
                self.polarity_gate_passed_case_ids
            ),
            "production_arm_id": self.production_arm_id,
            "production_constructor_identity": (
                self.production_constructor_identity
            ),
            "production_default_changed": False,
            "schema_version": self.schema_version,
            "semantic_authority": False,
            "task_id": self.task_id,
            "teacher_identity": TEACHER_IDENTITY,
            "teacher_role": TEACHER_ROLE,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SpacyPilotDiagnosticsMap":
        data = _mapping(value, "spaCy pilot diagnostics map")
        cases = tuple(
            item
            if isinstance(item, CaseSpacyDiagnostics)
            else CaseSpacyDiagnostics.from_dict(item)
            for item in data.get("cases", ())
        )
        return cls(
            cases=cases,
            catalog_cid=data.get("catalog_cid"),
            production_arm_id=str(
                data.get("production_arm_id") or PRODUCTION_ARM_ID
            ),
            production_constructor_identity=str(
                data.get("production_constructor_identity")
                or PRODUCTION_CONSTRUCTOR_IDENTITY
            ),
            production_default_changed=bool(
                data.get("production_default_changed", False)
            ),
            semantic_authority=bool(data.get("semantic_authority", False)),
            interface=str(
                data.get("interface") or SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE
            ),
            schema_version=str(
                data.get("schema_version") or SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA
            ),
            task_id=str(data.get("task_id") or PLATEAU_BREAK_TASK_ID),
            board_namespace=str(
                data.get("board_namespace") or PLATEAU_BREAK_BOARD_NAMESPACE
            ),
        )


def diagnose_pilot_cases(
    *,
    cases: Sequence[MatrixCase] | None = None,
    constructor: ModalSpacyCanonicalConstructor | None = None,
    candidate_ir_by_case: Mapping[
        str, CanonicalRuleIR | Mapping[str, object] | None
    ]
    | None = None,
    source_spans_by_case: Mapping[
        str, Sequence[SourceSpanDiagnostic | Mapping[str, object]]
    ]
    | None = None,
    construct: bool = True,
    catalog_cid: str | None = None,
) -> SpacyPilotDiagnosticsMap:
    """Return polarity/span/missing-slot diagnostics for every sealed pilot case.

    Offline unit paths may pass ``candidate_ir_by_case`` (and optional spans)
    without invoking the live spaCy frontend.  Live teacher paths omit the map
    and set ``construct=True``.
    """

    assert_production_default_unchanged()
    matrix_cases = (
        tuple(cases) if cases is not None else load_pilot_matrix_cases()
    )
    order = {case_id: index for index, case_id in enumerate(PILOT_CASE_IDS)}
    candidate_ir_by_case = dict(candidate_ir_by_case or {})
    source_spans_by_case = dict(source_spans_by_case or {})
    records: list[CaseSpacyDiagnostics] = []
    for case in matrix_cases:
        if case.case_id in candidate_ir_by_case:
            records.append(
                diagnose_ir_pair(
                    case.case_id,
                    case.gold_ir,
                    candidate_ir_by_case[case.case_id],
                    source_spans=source_spans_by_case.get(case.case_id, ()),
                )
            )
            continue
        records.append(
            diagnose_matrix_case(
                case,
                constructor=constructor,
                source_spans=source_spans_by_case.get(case.case_id, ()),
                construct=construct,
            )
        )
    records.sort(key=lambda item: order.get(item.case_id, 10_000))
    if catalog_cid is None:
        try:
            catalog = load_plateau_residual_catalog()
            catalog_cid = (
                str(catalog.get("catalog_cid"))
                if catalog.get("catalog_cid")
                else None
            )
        except Exception:
            catalog_cid = None
    return SpacyPilotDiagnosticsMap(
        cases=tuple(records),
        catalog_cid=catalog_cid,
    )


def attach_spacy_diagnostics_to_catalog_cases(
    catalog: Mapping[str, object],
    diagnostics_map: SpacyPilotDiagnosticsMap,
) -> dict[str, object]:
    """Return a catalog copy with ``spacy_cue`` filled from teacher diagnostics.

    The sealed on-disk residual catalog is not rewritten.  Callers that need a
    CID-bound receipt should re-bind after attachment.  Structural residual
    kinds, losses, and production arm metadata are preserved.
    """

    data = dict(_mapping(catalog, "plateau residual catalog"))
    by_case = diagnostics_map.by_case_id()
    cases_out: list[dict[str, object]] = []
    residual_rows: list[dict[str, object]] = []
    for raw_case in data.get("cases") or ():
        case_map = dict(_mapping(raw_case, "catalog case"))
        case_id = _nonblank(case_map.get("case_id"), "case_id")
        diagnostics = by_case.get(case_id)
        if diagnostics is None:
            cases_out.append(case_map)
            residual_rows.extend(
                dict(item)
                for item in case_map.get("residuals") or ()
                if isinstance(item, Mapping)
            )
            continue
        cues = spacy_cues_by_field_path(diagnostics)
        residual_out: list[dict[str, object]] = []
        for raw_facet in case_map.get("residuals") or ():
            facet = ResidualFacet.from_dict(raw_facet)
            attached = attach_spacy_cues_to_facets((facet,), cues)[0]
            residual_out.append(attached.to_dict())
        case_map["residuals"] = residual_out
        case_map["spacy_diagnostics"] = {
            "interface": SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE,
            "polarity_gate_passed": diagnostics.polarity_gate_passed,
            "signal_kinds_present": list(diagnostics.signal_kinds_present),
            "polarity_signal_count": diagnostics.polarity_signal_count,
            "span_signal_count": diagnostics.span_signal_count,
            "missing_slot_signal_count": diagnostics.missing_slot_signal_count,
            "semantic_authority": False,
            "promotion_requires_full_gates": True,
        }
        cases_out.append(case_map)
        residual_rows.extend(residual_out)
    data["cases"] = cases_out
    data["residuals"] = residual_rows
    data["spacy_teacher"] = {
        "interface": SPACY_DIAGNOSTIC_RECEIPT_INTERFACE,
        "task_id": PLATEAU_BREAK_TASK_ID,
        "teacher_identity": TEACHER_IDENTITY,
        "teacher_role": TEACHER_ROLE,
        "semantic_authority": False,
        "production_default_changed": False,
        "production_arm_id": PRODUCTION_ARM_ID,
        "production_constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
    }
    return data


@dataclass(frozen=True, slots=True)
class SpacyDiagnosticReceipt:
    """Evidence receipt for the spaCy residual diagnostics teacher."""

    diagnostics_map: SpacyPilotDiagnosticsMap
    nonzero_pilot_case_ids: tuple[str, ...] = field(
        default_factory=lambda: NONZERO_PILOT_CASE_IDS
    )
    zero_residual_control_case_id: str = ZERO_RESIDUAL_CONTROL_CASE_ID
    residual_polarity_inversion_case_ids: tuple[str, ...] = field(
        default_factory=lambda: RESIDUAL_POLARITY_INVERSION_CASE_IDS
    )
    interface: str = SPACY_DIAGNOSTIC_RECEIPT_INTERFACE
    schema_version: str = SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.diagnostics_map, SpacyPilotDiagnosticsMap):
            raise SpacyResidualDiagnosticsError(
                "diagnostics_map must be SpacyPilotDiagnosticsMap"
            )
        object.__setattr__(
            self,
            "nonzero_pilot_case_ids",
            tuple(self.nonzero_pilot_case_ids),
        )
        object.__setattr__(
            self,
            "residual_polarity_inversion_case_ids",
            tuple(self.residual_polarity_inversion_case_ids),
        )
        object.__setattr__(
            self,
            "zero_residual_control_case_id",
            _nonblank(
                self.zero_residual_control_case_id,
                "zero_residual_control_case_id",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        body = self.diagnostics_map.to_dict()
        body.update(
            {
                "interface": self.interface,
                "schema_version": self.schema_version,
                "nonzero_pilot_case_ids": list(self.nonzero_pilot_case_ids),
                "zero_residual_control_case_id": (
                    self.zero_residual_control_case_id
                ),
                "residual_polarity_inversion_case_ids": list(
                    self.residual_polarity_inversion_case_ids
                ),
                "evidence_subset": "spacy-diagnostic receipt",
                "semantic_authority": False,
                "production_default_changed": False,
            }
        )
        return body


def build_spacy_diagnostic_receipt(
    diagnostics_map: SpacyPilotDiagnosticsMap | None = None,
    **diagnose_kwargs: Any,
) -> SpacyDiagnosticReceipt:
    """Build the PLAT-050 teacher receipt (optionally diagnosing pilots)."""

    if diagnostics_map is None:
        diagnostics_map = diagnose_pilot_cases(**diagnose_kwargs)
    return SpacyDiagnosticReceipt(diagnostics_map=diagnostics_map)


def polarity_preflight_is_fail_closed(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    candidate_ir: CanonicalRuleIR | Mapping[str, object] | None,
) -> bool:
    """Return True when polarity preflight correctly fails closed on defects.

    Used by unit tests and callers to assert that diagnostics never widen a
    closed polarity gate.  A clean, polarity-preserving candidate returns
    False (gate open / passed) only when preflight itself passes.
    """

    preflight = polarity_preflight(gold_ir, candidate_ir)
    diagnostics = diagnose_ir_pair(
        "preflight-probe", gold_ir, candidate_ir
    )
    if bool(preflight.get("gate_passed")):
        return diagnostics.polarity_gate_passed is True and not (
            diagnostics.has_polarity_inversion
        )
    # Fail-closed: diagnostics must mirror the closed gate and never claim pass.
    return (
        diagnostics.polarity_gate_passed is False
        and bool(diagnostics.polarity_preflight.get("gate_passed")) is False
    )


__all__ = [
    "PLATEAU_BREAK_BOARD_NAMESPACE",
    "PLATEAU_BREAK_TASK_ID",
    "PRODUCTION_ARM_ID",
    "PRODUCTION_CONSTRUCTOR_IDENTITY",
    "PRODUCTION_DEFAULT_CHANGED",
    "PROMOTION_REQUIRES_FULL_GATES",
    "SEMANTIC_AUTHORITY",
    "SIGNAL_KIND_MISSING_SLOT",
    "SIGNAL_KIND_POLARITY",
    "SIGNAL_KIND_SPAN",
    "SIGNAL_KINDS",
    "SPACY_DIAGNOSTIC_RECEIPT_INTERFACE",
    "SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE",
    "SPACY_RESIDUAL_CUE_INTERFACE",
    "SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE",
    "SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA",
    "TEACHER_IDENTITY",
    "TEACHER_ROLE",
    "CaseSpacyDiagnostics",
    "MissingSlotSignal",
    "PolaritySignal",
    "SpanSignal",
    "SpacyDiagnosticReceipt",
    "SpacyPilotDiagnosticsMap",
    "SpacyResidualDiagnosticsError",
    "assert_production_default_unchanged",
    "attach_spacy_cues_to_facets",
    "attach_spacy_diagnostics_to_case_residual",
    "attach_spacy_diagnostics_to_catalog_cases",
    "build_spacy_diagnostic_receipt",
    "compute_missing_slot_signals",
    "compute_polarity_signals",
    "compute_span_signals",
    "diagnose_ir_pair",
    "diagnose_matrix_case",
    "diagnose_modal_spacy_construction",
    "diagnose_pilot_cases",
    "polarity_preflight_is_fail_closed",
    "production_path_is_typed_deontic_no_repair",
    "spacy_cue_from_signals",
    "spacy_cues_by_field_path",
]
