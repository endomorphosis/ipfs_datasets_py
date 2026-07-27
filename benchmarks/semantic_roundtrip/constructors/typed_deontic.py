"""Typed-deontic adapter for the canonical semantic round-trip boundary.

The production deontic converter deliberately remains unchanged.  This module
only projects its ``LegalNormIR`` records into the closed, scored
``CanonicalRuleIR`` schema used by the composition benchmark.

Diagnostics and repair-trigger emission are out-of-band: the no-repair
baseline ``construct`` path remains a pure ``ConstructorResult`` and never
invokes selective repair.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)


TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE: Final = (
    "TypedDeonticCanonicalConstructor@1"
)
TYPED_DEONTIC_DIAGNOSTICS_INTERFACE: Final = (
    "TypedDeonticConstructorDiagnostics@1"
)
TYPED_DEONTIC_TRIGGER_DETECTOR_INTERFACE: Final = (
    "TypedDeonticDiagnosticTriggerDetector@1"
)

# Conservative default aligned with SelectiveRepairPolicy.
DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD: Final = 0.65
_ATOM_MATCH_THRESHOLD: Final = 0.12

_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
_TEMPORAL_CUE_RE: Final = re.compile(
    r"\b("
    r"after|before|within|until|by|during|following|"
    r"\d+\s*(?:day|days|hour|hours|week|weeks|month|months|year|years)|"
    r"calendar\s+day|business\s+day"
    r")\b",
    re.IGNORECASE,
)
_OBLIGATION_CUE_RE: Final = re.compile(
    r"\b(must|shall|required|obligation|obliged)\b",
    re.IGNORECASE,
)
_PROHIBITION_CUE_RE: Final = re.compile(
    r"\b(must\s+not|shall\s+not|prohibit|forbidden|may\s+not)\b",
    re.IGNORECASE,
)
_PERMISSION_CUE_RE: Final = re.compile(
    r"\b(may|permission|permitted|allowed)\b",
    re.IGNORECASE,
)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _tokens(value: object) -> tuple[str, ...]:
    words = _TOKEN_RE.findall(_clean_text(value).lower().replace("_", " "))
    normalized: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        normalized.append(word)
    return tuple(normalized)


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(item))
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        result = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    if value is None:
        return []
    return [str(value)]


def _jaccard(left: object, right: object) -> float:
    left_tokens, right_tokens = set(_tokens(left)), set(_tokens(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _best_atom_scored(
    value: object,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = _ATOM_MATCH_THRESHOLD,
) -> tuple[str, float | None]:
    """Return ``(atom, confidence)`` using the pilot matching rule."""

    pieces = _flatten_strings(value)
    text = " ".join(pieces)
    if not _clean_text(text):
        return ("", None) if allow_empty else ("", None)
    if not candidates:
        return "", None
    scored = sorted(
        (
            (
                max(
                    [_jaccard(text, candidate)]
                    + [_jaccard(piece, candidate) for piece in pieces]
                ),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if not scored or scored[0][0] < threshold:
        return "", float(scored[0][0]) if scored else 0.0
    return scored[0][1], float(scored[0][0])


def _best_atom(
    value: object,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = _ATOM_MATCH_THRESHOLD,
) -> str:
    """Return the same deterministic closed-vocabulary match as the pilot."""

    atom, _confidence = _best_atom_scored(
        value,
        candidates,
        allow_empty=allow_empty,
        threshold=threshold,
    )
    return atom


def _map_many(value: object, candidates: Sequence[str]) -> tuple[str, ...]:
    values: list[object]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value is None or value == "" or value == []:
        values = []
    else:
        values = [value]
    return tuple(
        sorted(
            {
                atom
                for item in values
                if (atom := _best_atom(item, candidates))
            }
        )
    )


def _map_many_scored(
    value: object, candidates: Sequence[str]
) -> tuple[tuple[str, ...], float | None]:
    """Map multi-valued facets and retain the minimum matched confidence."""

    values: list[object]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value is None or value == "" or value == []:
        values = []
    else:
        values = [value]
    atoms: set[str] = set()
    confidences: list[float] = []
    for item in values:
        atom, confidence = _best_atom_scored(item, candidates)
        if atom:
            atoms.add(atom)
            if confidence is not None:
                confidences.append(confidence)
    if not values:
        return (), None
    if not atoms:
        return (), min(confidences) if confidences else 0.0
    return tuple(sorted(atoms)), min(confidences) if confidences else None


def _modality_from_text(value: object) -> str:
    text = _clean_text(value).lower()
    if (
        text in {"f", "prohibition", "forbidden"}
        or "prohibit" in text
        or "shall not" in text
        or "must not" in text
    ):
        return "F"
    if text in {"p", "permission", "permitted"} or "permission" in text:
        return "P"
    return "O"


def _modality_conflict(value: object, source_text: str = "") -> bool:
    """True when obligation and prohibition (or permission) cues co-occur."""

    text = " ".join(
        filter(
            None,
            [
                _clean_text(value),
                _clean_text(source_text),
            ],
        )
    )
    if not text:
        return False
    has_obligation = bool(_OBLIGATION_CUE_RE.search(text))
    has_prohibition = bool(_PROHIBITION_CUE_RE.search(text))
    has_permission = bool(_PERMISSION_CUE_RE.search(text))
    modality_labels = {
        label
        for label in re.findall(
            r"\b(obligation|prohibition|permission|forbidden|permitted)\b",
            text,
            flags=re.IGNORECASE,
        )
    }
    label_conflict = len(
        {
            "obligation" if item.lower() in {"obligation"} else item.lower()
            for item in modality_labels
        }
        & {"obligation", "prohibition", "permission", "forbidden", "permitted"}
    ) > 1
    return bool(
        (has_obligation and has_prohibition)
        or (has_obligation and has_permission and has_prohibition)
        or label_conflict
        or (
            "obligation" in text.lower()
            and "prohibition" in text.lower()
        )
    )


def _source_has_temporal_cue(source_text: str) -> bool:
    return bool(_TEMPORAL_CUE_RE.search(source_text or ""))


@dataclass(frozen=True, slots=True)
class TypedDeonticSlotDiagnostic:
    """Field-local projection evidence used to open repair slots."""

    rule_index: int
    canonical_field: str
    kind: str
    confidence: float | None = None
    evidence: str | None = None
    value: object = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.rule_index, bool)
            or not isinstance(self.rule_index, int)
            or self.rule_index < 0
        ):
            raise ContractError("slot diagnostic rule_index must be nonnegative")
        if self.canonical_field not in RULE_FIELDS:
            raise ContractError(
                f"unknown slot diagnostic field: {self.canonical_field!r}"
            )
        kind = str(self.kind or "").strip().lower()
        if kind not in {"missing", "low_confidence", "contradictory"}:
            raise ContractError(
                "slot diagnostic kind must be missing, low_confidence, "
                "or contradictory"
            )
        object.__setattr__(self, "kind", kind)
        if self.confidence is not None:
            if (
                isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or not 0.0 <= float(self.confidence) <= 1.0
            ):
                raise ContractError(
                    "slot diagnostic confidence must be from zero to one"
                )
            object.__setattr__(self, "confidence", float(self.confidence))
        if self.evidence is not None:
            cleaned = " ".join(str(self.evidence).split())
            if not cleaned:
                raise ContractError("slot diagnostic evidence must be nonblank")
            object.__setattr__(self, "evidence", cleaned[:1000])

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_field": self.canonical_field,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "kind": self.kind,
            "rule_index": self.rule_index,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class TypedDeonticConstructorDiagnostics:
    """Out-of-band diagnostics for the typed-deontic constructor."""

    slots: tuple[TypedDeonticSlotDiagnostic, ...] = ()
    detail: str | None = None
    source_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", tuple(self.slots))
        if not all(
            isinstance(item, TypedDeonticSlotDiagnostic) for item in self.slots
        ):
            raise ContractError("diagnostics slots are invalid")
        if self.detail is not None and not str(self.detail).strip():
            raise ContractError("diagnostics detail must be nonblank")
        object.__setattr__(self, "source_text", str(self.source_text or ""))

    def to_dict(self) -> dict[str, object]:
        return {
            "detail": self.detail,
            "interface": TYPED_DEONTIC_DIAGNOSTICS_INTERFACE,
            "slots": [item.to_dict() for item in self.slots],
            "source_text": self.source_text,
        }

    def repair_triggers(
        self,
        *,
        low_confidence_threshold: float = (
            DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
        ),
    ) -> tuple[object, ...]:
        """Project slot diagnostics into selective-repair ``RepairTrigger``s.

        Imported lazily so the no-repair baseline arm never depends on the
        selective-repair package at import time.
        """

        from benchmarks.semantic_roundtrip.selective_repair import (
            RepairTrigger,
            RepairTriggerKind,
        )

        triggers: list[RepairTrigger] = []
        seen: set[str] = set()
        for slot in self.slots:
            path = f"rules[{slot.rule_index}].{slot.canonical_field}"
            if path in seen:
                continue
            kind = RepairTriggerKind(slot.kind)
            if kind is RepairTriggerKind.LOW_CONFIDENCE:
                if slot.confidence is None:
                    continue
                if slot.confidence >= float(low_confidence_threshold):
                    continue
            triggers.append(
                RepairTrigger(
                    rule_index=slot.rule_index,
                    canonical_field=slot.canonical_field,
                    kind=kind,
                    confidence=slot.confidence,
                    evidence=slot.evidence,
                )
            )
            seen.add(path)
        return tuple(triggers)


@dataclass(frozen=True, slots=True)
class TypedDeonticConstruction:
    """Constructor result paired with optional out-of-band diagnostics."""

    result: ConstructorResult
    diagnostics: TypedDeonticConstructorDiagnostics

    def __post_init__(self) -> None:
        if not isinstance(self.result, ConstructorResult):
            raise ContractError("result must be a ConstructorResult")
        if not isinstance(
            self.diagnostics, TypedDeonticConstructorDiagnostics
        ):
            raise ContractError(
                "diagnostics must be TypedDeonticConstructorDiagnostics"
            )


def derive_slot_diagnostics(
    canonical_ir: CanonicalRuleIR,
    *,
    source_text: str = "",
    field_confidences: Mapping[tuple[int, str], float | None] | None = None,
    low_confidence_threshold: float = (
        DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
    ),
    modality_raw: Mapping[int, object] | None = None,
) -> tuple[TypedDeonticSlotDiagnostic, ...]:
    """Derive missing / low-confidence / contradictory slot diagnostics.

    Purely diagnostic: does not mutate the scored IR used by the no-repair
    baseline arm.
    """

    if not isinstance(canonical_ir, CanonicalRuleIR):
        raise ContractError("canonical_ir must be CanonicalRuleIR")
    confidences = dict(field_confidences or {})
    modality_raw = dict(modality_raw or {})
    slots: list[TypedDeonticSlotDiagnostic] = []
    source = _clean_text(source_text)
    temporal_cue = _source_has_temporal_cue(source)

    for index, rule in enumerate(canonical_ir.rules):
        for field in RULE_FIELDS:
            value = getattr(rule, field)
            empty = value in ("", ())
            confidence = confidences.get((index, field))

            if field == "temporal" and empty and temporal_cue:
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="missing",
                        confidence=confidence,
                        evidence=(
                            "source contains temporal cue but temporal "
                            "slot is empty"
                        ),
                        value=value,
                    )
                )
                continue

            if field in {"actor", "action"} and empty:
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="missing",
                        confidence=confidence,
                        evidence=f"required scalar slot {field} is empty",
                        value=value,
                    )
                )
                continue

            if (
                confidence is not None
                and confidence < float(low_confidence_threshold)
                and not empty
            ):
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="low_confidence",
                        confidence=confidence,
                        evidence=(
                            f"{field} matched below the diagnostic "
                            f"threshold {low_confidence_threshold}"
                        ),
                        value=value,
                    )
                )
                continue

        raw_modality = modality_raw.get(index, source)
        if _modality_conflict(raw_modality, source):
            slots.append(
                TypedDeonticSlotDiagnostic(
                    rule_index=index,
                    canonical_field="modality",
                    kind="contradictory",
                    confidence=confidences.get((index, "modality")),
                    evidence=(
                        "obligation and prohibition cues co-occur in "
                        "compiler or source evidence"
                    ),
                    value=rule.modality,
                )
            )

    # Stable order: rule index, field order, kind.
    kind_order = {"missing": 0, "low_confidence": 1, "contradictory": 2}
    slots.sort(
        key=lambda item: (
            item.rule_index,
            RULE_FIELDS.index(item.canonical_field),
            kind_order.get(item.kind, 9),
        )
    )
    # One trigger path per field (prefer missing over low-confidence).
    deduped: list[TypedDeonticSlotDiagnostic] = []
    seen_paths: set[str] = set()
    for slot in slots:
        path = f"rules[{slot.rule_index}].{slot.canonical_field}"
        if path in seen_paths:
            continue
        seen_paths.add(path)
        deduped.append(slot)
    return tuple(deduped)


def project_legal_norms_with_diagnostics(
    norms: Sequence[object],
    vocabulary: AllowedAtomVocabulary,
    *,
    source_text: str = "",
    low_confidence_threshold: float = (
        DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
    ),
) -> tuple[CanonicalRuleIR, TypedDeonticConstructorDiagnostics]:
    """Project norms and retain field-level diagnostic evidence."""

    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")

    rules: list[CanonicalRule] = []
    confidences: dict[tuple[int, str], float | None] = {}
    modality_raw: dict[int, object] = {}
    rule_index = 0
    for norm in norms:
        to_dict = getattr(norm, "to_dict", None)
        if not callable(to_dict):
            raise ContractError("typed deontic norm must provide to_dict()")
        data = to_dict()
        if not isinstance(data, Mapping):
            raise ContractError(
                "typed deontic norm to_dict() must return an object"
            )

        actor, actor_conf = _best_atom_scored(
            data.get("actor"), vocabulary.actors
        )
        action, action_conf = _best_atom_scored(
            [data.get("action"), data.get("action_verb")],
            vocabulary.actions,
        )
        object_atom, object_conf = _best_atom_scored(
            data.get("action_object"),
            vocabulary.objects,
            allow_empty=True,
        )
        if not actor or not action:
            continue

        conditions, conditions_conf = _map_many_scored(
            data.get("conditions") or (), vocabulary.qualifiers
        )
        exceptions, exceptions_conf = _map_many_scored(
            data.get("exceptions") or (), vocabulary.qualifiers
        )
        temporal, temporal_conf = _map_many_scored(
            data.get("temporal_constraints") or (),
            vocabulary.qualifiers,
        )
        modality_value = [data.get("modality"), data.get("norm_type")]
        modality = _modality_from_text(modality_value)
        modality_raw[rule_index] = modality_value

        confidences[(rule_index, "actor")] = actor_conf
        confidences[(rule_index, "action")] = action_conf
        confidences[(rule_index, "object")] = object_conf
        confidences[(rule_index, "conditions")] = conditions_conf
        confidences[(rule_index, "exceptions")] = exceptions_conf
        confidences[(rule_index, "temporal")] = temporal_conf
        # Modality is rule-derived from cues; high confidence unless conflicted.
        confidences[(rule_index, "modality")] = (
            0.4 if _modality_conflict(modality_value, source_text) else 0.95
        )

        rules.append(
            CanonicalRule(
                modality=modality,
                actor=actor,
                action=action,
                object=object_atom,
                conditions=conditions,
                exceptions=exceptions,
                temporal=temporal,
            )
        )
        rule_index += 1

    canonical_ir = CanonicalRuleIR(tuple(rules))
    canonical_ir.validate_vocabulary(vocabulary)
    slots = derive_slot_diagnostics(
        canonical_ir,
        source_text=source_text,
        field_confidences=confidences,
        low_confidence_threshold=low_confidence_threshold,
        modality_raw=modality_raw,
    )
    return canonical_ir, TypedDeonticConstructorDiagnostics(
        slots=slots,
        source_text=_clean_text(source_text),
    )


def project_legal_norms(
    norms: Sequence[object],
    vocabulary: AllowedAtomVocabulary,
) -> CanonicalRuleIR:
    """Project supported ``LegalNormIR`` records into exact canonical fields.

    As in the reviewed pilot, a record is supported when its actor and action
    both map into the closed case vocabulary.  An absent or unmatched object
    is represented explicitly by ``""`` and absent qualifier facets by empty
    tuples.  No source spans, native IR, metadata, or decoder records cross the
    canonical boundary.
    """

    canonical_ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary
    )
    return canonical_ir


def derive_repair_triggers_from_ir_and_source(
    request: ConstructorRequest,
    baseline_ir: CanonicalRuleIR,
    *,
    low_confidence_threshold: float = (
        DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
    ),
    field_confidences: Mapping[tuple[int, str], float | None] | None = None,
) -> tuple[object, ...]:
    """Emit repair triggers from IR + source diagnostics (no IR mutation)."""

    if not isinstance(request, ConstructorRequest):
        raise ContractError("request must be ConstructorRequest")
    diagnostics = TypedDeonticConstructorDiagnostics(
        slots=derive_slot_diagnostics(
            baseline_ir,
            source_text=request.source_text,
            field_confidences=field_confidences,
            low_confidence_threshold=low_confidence_threshold,
        ),
        source_text=request.source_text,
    )
    return diagnostics.repair_triggers(
        low_confidence_threshold=low_confidence_threshold
    )


def _failure(
    reason: FailureReason,
    detail: str,
) -> ConstructorResult:
    return ConstructorResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail,
    )


class TypedDeonticCanonicalConstructor:
    """Adapt the deterministic typed deontic converter to canonical rule IR."""

    @property
    def identity(self) -> str:
        return TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE

    def construct_with_diagnostics(
        self, request: ConstructorRequest
    ) -> TypedDeonticConstruction:
        """Construct IR and retain trigger-ready diagnostics out of band.

        The scored no-repair baseline continues to use :meth:`construct`, which
        returns only ``ConstructorResult`` and never mutates or repairs.
        """

        empty = TypedDeonticConstructorDiagnostics()
        if not isinstance(request, ConstructorRequest):
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.INVALID_OUTPUT,
                    "request must be ConstructorRequest",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="request must be ConstructorRequest"
                ),
            )

        try:
            from ipfs_datasets_py.logic.deontic.converter import (
                DeonticConverter,
            )
            from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
        except ImportError:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.CAPABILITY_UNAVAILABLE,
                    "typed deontic converter capability is unavailable",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="typed deontic converter capability is unavailable",
                    source_text=request.source_text,
                ),
            )

        try:
            converter = DeonticConverter(
                use_cache=False,
                use_ipfs=False,
                use_ml=False,
                enable_monitoring=False,
                document_type="general",
            )
            converted = converter.convert(request.source_text, use_cache=False)
        except Exception as exc:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EXCEPTION,
                    f"typed deontic conversion raised {type(exc).__name__}",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail=(
                        f"typed deontic conversion raised {type(exc).__name__}"
                    ),
                    source_text=request.source_text,
                ),
            )

        output = getattr(converted, "output", None)
        if output is None:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.MISSING_OUTPUT,
                    "typed deontic converter returned no output",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="typed deontic converter returned no output",
                    source_text=request.source_text,
                ),
            )

        elements = list(getattr(output, "parser_elements", ()) or ())
        if not elements:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EMPTY_L1,
                    "typed deontic converter returned no parser elements",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="typed deontic converter returned no parser elements",
                    source_text=request.source_text,
                ),
            )

        try:
            norms = [
                LegalNormIR.from_parser_element(element)
                for element in elements
            ]
            canonical_ir, diagnostics = project_legal_norms_with_diagnostics(
                norms,
                request.allowed_atom_vocabulary,
                source_text=request.source_text,
            )
        except ContractError as exc:
            return TypedDeonticConstruction(
                _failure(FailureReason.INVALID_OUTPUT, str(exc)),
                TypedDeonticConstructorDiagnostics(
                    detail=str(exc),
                    source_text=request.source_text,
                ),
            )
        except Exception as exc:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EXCEPTION,
                    f"typed deontic projection raised {type(exc).__name__}",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail=(
                        f"typed deontic projection raised {type(exc).__name__}"
                    ),
                    source_text=request.source_text,
                ),
            )

        if canonical_ir.is_empty:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EMPTY_L1,
                    "typed deontic records did not map to supported "
                    "canonical rules",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail=(
                        "typed deontic records did not map to supported "
                        "canonical rules"
                    ),
                    source_text=request.source_text,
                ),
            )
        return TypedDeonticConstruction(
            ConstructorResult(
                status=ComponentStatus.SUCCESS,
                canonical_ir=canonical_ir,
            ),
            diagnostics,
        )

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """No-repair baseline path: pure ConstructorResult, no repair side effects."""

        # Keep the baseline arm identical in disposition to diagnostics path
        # results without exposing diagnostic payloads on the scored surface.
        return self.construct_with_diagnostics(request).result


class TypedDeonticDiagnosticTriggerDetector:
    """RepairTriggerDetector backed by typed-deontic slot diagnostics."""

    identity: Final = TYPED_DEONTIC_TRIGGER_DETECTOR_INTERFACE

    def __init__(
        self,
        *,
        low_confidence_threshold: float = (
            DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
        ),
        field_confidences: (
            Mapping[tuple[int, str], float | None] | None
        ) = None,
    ) -> None:
        if (
            isinstance(low_confidence_threshold, bool)
            or not isinstance(low_confidence_threshold, (int, float))
            or not 0.0 <= float(low_confidence_threshold) <= 1.0
        ):
            raise ContractError(
                "low_confidence_threshold must be from zero to one"
            )
        self._low_confidence_threshold = float(low_confidence_threshold)
        self._field_confidences = dict(field_confidences or {})

    def detect(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
    ) -> Sequence[object]:
        return derive_repair_triggers_from_ir_and_source(
            request,
            baseline_ir,
            low_confidence_threshold=self._low_confidence_threshold,
            field_confidences=self._field_confidences,
        )


assert isinstance(TypedDeonticCanonicalConstructor(), RoundTripConstructor)


__all__ = [
    "TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE",
    "TYPED_DEONTIC_DIAGNOSTICS_INTERFACE",
    "TYPED_DEONTIC_TRIGGER_DETECTOR_INTERFACE",
    "DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD",
    "TypedDeonticSlotDiagnostic",
    "TypedDeonticConstructorDiagnostics",
    "TypedDeonticConstruction",
    "TypedDeonticCanonicalConstructor",
    "TypedDeonticDiagnosticTriggerDetector",
    "derive_slot_diagnostics",
    "derive_repair_triggers_from_ir_and_source",
    "project_legal_norms",
    "project_legal_norms_with_diagnostics",
]
