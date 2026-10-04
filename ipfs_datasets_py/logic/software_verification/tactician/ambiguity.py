"""Goal ambiguity exposure and material interpretation selection (FVT-G023).

``GoalInterpretationSet@1`` and ``GoalAmbiguityGate@1`` own the deterministic
path that turns an end-goal request (or a formalized ``EndGoalSpec``) into a
bounded set of *materially different* interpretations, each with:

* a controlled-English rendering;
* a semantic diff against peer candidates;
* unresolved fields; and
* explicit confirmation requirements.

Program invariants:

* existential reachability, universal reachability, eventual inevitability,
  invariance, termination, and refinement **cannot collapse** into one
  content identity or one semantic-diff fingerprint;
* ambiguous corpus prompts return **at least two** visibly different
  candidates;
* **no material ambiguity is silently selected** — the gate never admits or
  confirms an interpretation without an explicit caller selection when more
  than one material candidate remains; and
* interpretation comparison is pure and local (conflict policy: do not call
  external provers or models during deterministic semantic diff).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AmbiguityStatus,
    AuthorityCeiling,
    EndGoalInterpretation,
    EndGoalSpec,
    PropertyClass,
    QuantifierKind,
    SourceSpanBinding,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

GOAL_INTERPRETATION_SET_INTERFACE: Final = "GoalInterpretationSet@1"
GOAL_AMBIGUITY_GATE_INTERFACE: Final = "GoalAmbiguityGate@1"
GOAL_INTERPRETATION_SET_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/goal-interpretation-set@1"
)
GOAL_AMBIGUITY_REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/goal-ambiguity-report@1"
)
SEMANTIC_DIFF_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/interpretation-semantic-diff@1"
)
CONFIRMATION_REQUIREMENT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/confirmation-requirement@1"
)
AMBIGUITY_ALGORITHM_VERSION: Final = "goal-ambiguity-gate/1.0.0"

# Property classes that must remain pairwise distinguishable (acceptance).
NON_COLLAPSIBLE_PROPERTY_CLASSES: Final[tuple[PropertyClass, ...]] = (
    PropertyClass.EXISTENTIAL_REACHABILITY,
    PropertyClass.UNIVERSAL_REACHABILITY,
    PropertyClass.INEVITABILITY,
    PropertyClass.INVARIANCE,
    PropertyClass.TERMINATION,
    PropertyClass.REFINEMENT,
)

# Canonical quantifier bundles for each non-collapsible class.
_CLASS_QUANTIFIERS: Final[Mapping[PropertyClass, tuple[QuantifierKind, ...]]] = {
    PropertyClass.EXISTENTIAL_REACHABILITY: (
        QuantifierKind.EXISTS,
        QuantifierKind.EVENTUALLY,
    ),
    PropertyClass.UNIVERSAL_REACHABILITY: (
        QuantifierKind.FORALL,
        QuantifierKind.EVENTUALLY,
    ),
    PropertyClass.INEVITABILITY: (QuantifierKind.EVENTUALLY,),
    PropertyClass.INVARIANCE: (QuantifierKind.ALWAYS,),
    PropertyClass.TERMINATION: (QuantifierKind.EVENTUALLY,),
    PropertyClass.REFINEMENT: (QuantifierKind.NONE,),
    PropertyClass.LIVENESS: (QuantifierKind.EVENTUALLY,),
    PropertyClass.SAFETY: (QuantifierKind.ALWAYS,),
}

# Controlled-English templates keyed by property class (deterministic).
_CONTROLLED_ENGLISH: Final[Mapping[PropertyClass, str]] = {
    PropertyClass.EXISTENTIAL_REACHABILITY: (
        "Some execution path can reach the target state (existential reachability)."
    ),
    PropertyClass.UNIVERSAL_REACHABILITY: (
        "Every execution path eventually reaches the target state "
        "(universal reachability)."
    ),
    PropertyClass.INEVITABILITY: (
        "The target state is eventually inevitable under the modeled environment."
    ),
    PropertyClass.INVARIANCE: (
        "The target property holds as an invariant on every reachable state."
    ),
    PropertyClass.TERMINATION: (
        "Every execution eventually terminates (termination)."
    ),
    PropertyClass.REFINEMENT: (
        "The implementation refines the abstract specification (refinement)."
    ),
    PropertyClass.LIVENESS: (
        "Some progress property eventually holds (liveness)."
    ),
    PropertyClass.SAFETY: (
        "Bad states are never reached (safety)."
    ),
}

# Fields that, when they differ, count as *material* semantic divergence.
_MATERIAL_DIFF_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "property_class",
        "quantifiers",
        "current_state",
        "target_state",
        "environment",
        "controlled_english",
    }
)

# Corpus-style ambiguous prompts that must expand to ≥2 candidates.
_AMBIGUOUS_PROMPT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:the\s+)?system\s+reaches?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\breaches?\s+(?:the\s+)?(?:ready|done|final|end)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bends?\s+(?:in|at|up\s+in)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:gets?|becomes?)\s+(?:ready|done|complete)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfair(?:ness)?\b.*\b(?:eventually|liveness|progress)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:eventually|liveness|progress)\b.*\bfair(?:ness)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bworks?\s+correctly\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bis\s+(?:safe|correct|sound)\b",
        re.IGNORECASE,
    ),
)

# Which material classes an ambiguous prompt family expands into.
_AMBIGUOUS_EXPANSIONS: Final[tuple[PropertyClass, ...]] = (
    PropertyClass.EXISTENTIAL_REACHABILITY,
    PropertyClass.UNIVERSAL_REACHABILITY,
    PropertyClass.INEVITABILITY,
    PropertyClass.INVARIANCE,
)

# Fairness-flavored expansions (liveness vs inevitability under fairness).
_FAIRNESS_EXPANSIONS: Final[tuple[PropertyClass, ...]] = (
    PropertyClass.UNIVERSAL_REACHABILITY,
    PropertyClass.INEVITABILITY,
    PropertyClass.LIVENESS,
)

# Safety / correctness underspecification expansions.
_CORRECTNESS_EXPANSIONS: Final[tuple[PropertyClass, ...]] = (
    PropertyClass.SAFETY,
    PropertyClass.INVARIANCE,
    PropertyClass.REFINEMENT,
    PropertyClass.TERMINATION,
)

# Forbidden silent-admission keys on any gate result.
_FORBIDDEN_ADMISSION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "admitted",
        "admission_claimed",
        "proof_claimed",
        "proved",
        "complete",
        "completion_claimed",
        "implementation_conformance_claimed",
        "implementation_conformant",
        "attested",
        "kernel_verified",
        "silently_selected",
        "auto_selected",
    }
)


# ---------------------------------------------------------------------------
# Errors and enumerations
# ---------------------------------------------------------------------------


class GoalAmbiguityError(TacticianContractError):
    """Raised when ambiguity analysis or selection fails closed."""


class GateStatus(StrEnum):
    """Outcome of a goal-ambiguity gate evaluation (never proof admission)."""

    UNAMBIGUOUS = "unambiguous"
    CANDIDATES_PRESENT = "candidates_present"
    REQUIRES_SELECTION = "requires_selection"
    RESOLVED = "resolved"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"


class ConfirmationKind(StrEnum):
    """What the caller must supply to pass the gate."""

    NONE = "none"
    SELECT_INTERPRETATION = "select_interpretation"
    CLARIFY_UNRESOLVED = "clarify_unresolved"
    REJECT_UNSUPPORTED = "reject_unsupported"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 16384,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise GoalAmbiguityError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise GoalAmbiguityError(f"{label} must not contain NUL")
    if not optional and not text:
        raise GoalAmbiguityError(f"{label} is required")
    if len(text) > maximum:
        raise GoalAmbiguityError(f"{label} exceeds maximum length of {maximum}")
    return text


def _string_tuple(
    value: object,
    label: str,
    *,
    preserve_order: bool = False,
    maximum_item: int = 512,
) -> tuple[str, ...]:
    if value is None:
        items: Iterable[Any] = ()
    elif isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        items = value
    else:
        raise GoalAmbiguityError(f"{label} must be a sequence of strings")
    result: list[str] = []
    for raw in items:
        item = _text(raw, label, maximum=maximum_item)
        if item and item not in result:
            result.append(item)
    return tuple(result if preserve_order else sorted(result))


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise GoalAmbiguityError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise GoalAmbiguityError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise GoalAmbiguityError(f"{label} keys must be strings")
    return {str(k): value[k] for k in sorted(value)}


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    raw = getattr(value, "value", value)
    try:
        return enum_type(str(raw).strip().lower())
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise GoalAmbiguityError(f"{label} must be one of: {allowed}") from exc


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _reject_forbidden_meta(meta: Mapping[str, Any], label: str) -> None:
    for key in _FORBIDDEN_ADMISSION_KEYS:
        if key in meta and meta[key] is True:
            raise GoalAmbiguityError(
                f"{label} cannot claim forbidden admission key {key!r}"
            )


def _property_class(value: object) -> PropertyClass:
    return _enum(value, PropertyClass, "property_class")


def _quantifiers(value: object) -> tuple[QuantifierKind, ...]:
    if value is None:
        return ()
    if isinstance(value, QuantifierKind):
        return (value,)
    if isinstance(value, str):
        return (_enum(value, QuantifierKind, "quantifiers"),)
    if not isinstance(value, Sequence) or isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        raise GoalAmbiguityError("quantifiers must be a sequence")
    return tuple(_enum(item, QuantifierKind, "quantifiers") for item in value)


def _interpretation_payload(item: EndGoalInterpretation) -> dict[str, Any]:
    return {
        "interpretation_id": item.interpretation_id,
        "controlled_english": item.controlled_english,
        "property_class": item.property_class.value,
        "quantifiers": [q.value for q in item.quantifiers],
        "current_state": dict(item.current_state),
        "target_state": dict(item.target_state),
        "environment": dict(item.environment),
        "unresolved_fields": list(item.unresolved_fields),
        "selected": item.selected,
    }


def quantifiers_for_property_class(
    property_class: PropertyClass | str,
) -> tuple[QuantifierKind, ...]:
    """Return the canonical quantifier bundle for a property class."""

    resolved = _property_class(property_class)
    return _CLASS_QUANTIFIERS.get(resolved, (QuantifierKind.NONE,))


def controlled_english_for(
    property_class: PropertyClass | str,
    *,
    target_state: Mapping[str, Any] | None = None,
    current_state: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
) -> str:
    """Render a deterministic controlled-English sentence for a class."""

    resolved = _property_class(property_class)
    base = _CONTROLLED_ENGLISH.get(
        resolved,
        f"Property class is {resolved.value.replace('_', ' ')}.",
    )
    parts = [base]
    if current_state:
        state = ", ".join(f"{k}={v}" for k, v in sorted(current_state.items()))
        parts.append(f"Current state: {state}.")
    if target_state:
        state = ", ".join(f"{k}={v}" for k, v in sorted(target_state.items()))
        parts.append(f"Target state: {state}.")
    if environment:
        env = ", ".join(f"{k}={v}" for k, v in sorted(environment.items()))
        parts.append(f"Environment: {env}.")
    quant = ", ".join(q.value for q in quantifiers_for_property_class(resolved))
    parts.append(f"Quantifiers: [{quant}].")
    return " ".join(parts)


def material_identity(interpretation: EndGoalInterpretation | Mapping[str, Any]) -> str:
    """Content identity over material semantic bindings only.

    Two interpretations collapse only when this identity matches.  The six
    non-collapsible property classes never share an identity under the same
    target/environment binding.
    """

    if isinstance(interpretation, EndGoalInterpretation):
        payload = {
            "property_class": interpretation.property_class.value,
            "quantifiers": [q.value for q in interpretation.quantifiers],
            "current_state": dict(interpretation.current_state),
            "target_state": dict(interpretation.target_state),
            "environment": dict(interpretation.environment),
            "controlled_english": interpretation.controlled_english,
        }
    elif isinstance(interpretation, Mapping):
        payload = {
            "property_class": str(
                getattr(
                    interpretation.get("property_class"),
                    "value",
                    interpretation.get("property_class", ""),
                )
            ),
            "quantifiers": list(interpretation.get("quantifiers") or ()),
            "current_state": dict(interpretation.get("current_state") or {}),
            "target_state": dict(interpretation.get("target_state") or {}),
            "environment": dict(interpretation.get("environment") or {}),
            "controlled_english": str(
                interpretation.get("controlled_english") or ""
            ),
        }
    else:
        raise GoalAmbiguityError(
            "interpretation must be an EndGoalInterpretation or mapping"
        )
    return content_identity(payload)


# ---------------------------------------------------------------------------
# Semantic diff (deterministic; no provers / models)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    """Pairwise semantic difference between two interpretations.

    Diffs are pure structural comparisons.  They never invoke solvers or
    language models (conflict policy for FVT-G023).
    """

    SCHEMA: ClassVar[str] = SEMANTIC_DIFF_SCHEMA

    left_id: str
    right_id: str
    changed_fields: tuple[str, ...] = ()
    field_deltas: Mapping[str, Any] = field(default_factory=dict)
    material: bool = False
    left_identity: str = ""
    right_identity: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "left_id", _text(self.left_id, "left_id", maximum=256)
        )
        object.__setattr__(
            self, "right_id", _text(self.right_id, "right_id", maximum=256)
        )
        object.__setattr__(
            self,
            "changed_fields",
            _string_tuple(self.changed_fields, "changed_fields", preserve_order=True),
        )
        object.__setattr__(
            self, "field_deltas", _mapping(self.field_deltas, "field_deltas")
        )
        object.__setattr__(self, "material", _bool(self.material, "material"))
        object.__setattr__(
            self,
            "left_identity",
            _text(self.left_identity, "left_identity", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "right_identity",
            _text(self.right_identity, "right_identity", optional=True, maximum=128),
        )
        if not self.fingerprint:
            object.__setattr__(
                self,
                "fingerprint",
                _digest(
                    {
                        "left_id": self.left_id,
                        "right_id": self.right_id,
                        "changed_fields": list(self.changed_fields),
                        "field_deltas": dict(self.field_deltas),
                        "material": self.material,
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "fingerprint",
                _text(self.fingerprint, "fingerprint", maximum=128),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "left_id": self.left_id,
            "right_id": self.right_id,
            "changed_fields": list(self.changed_fields),
            "field_deltas": dict(self.field_deltas),
            "material": self.material,
            "left_identity": self.left_identity,
            "right_identity": self.right_identity,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticDiff":
        if not isinstance(payload, Mapping):
            raise GoalAmbiguityError("semantic diff payload must be an object")
        return cls(
            left_id=payload.get("left_id", ""),
            right_id=payload.get("right_id", ""),
            changed_fields=tuple(payload.get("changed_fields") or ()),
            field_deltas=payload.get("field_deltas") or {},
            material=bool(payload.get("material", False)),
            left_identity=str(payload.get("left_identity") or ""),
            right_identity=str(payload.get("right_identity") or ""),
            fingerprint=str(payload.get("fingerprint") or ""),
        )


def compare_interpretations(
    left: EndGoalInterpretation,
    right: EndGoalInterpretation,
) -> SemanticDiff:
    """Compute a deterministic semantic diff between two interpretations.

    Never calls external provers or models.  A diff is *material* when any
    field in ``_MATERIAL_DIFF_FIELDS`` differs (including property class).
    """

    if not isinstance(left, EndGoalInterpretation):
        raise GoalAmbiguityError("left must be an EndGoalInterpretation")
    if not isinstance(right, EndGoalInterpretation):
        raise GoalAmbiguityError("right must be an EndGoalInterpretation")

    left_payload = _interpretation_payload(left)
    right_payload = _interpretation_payload(right)
    changed: list[str] = []
    deltas: dict[str, Any] = {}
    comparable = (
        "property_class",
        "quantifiers",
        "current_state",
        "target_state",
        "environment",
        "controlled_english",
        "unresolved_fields",
    )
    for key in comparable:
        lv = left_payload.get(key)
        rv = right_payload.get(key)
        if lv != rv:
            changed.append(key)
            deltas[key] = {"left": lv, "right": rv}

    material = any(field_name in _MATERIAL_DIFF_FIELDS for field_name in changed)
    left_id = material_identity(left)
    right_id = material_identity(right)
    if left_id != right_id:
        material = True
        if "material_identity" not in changed:
            changed.append("material_identity")
            deltas["material_identity"] = {"left": left_id, "right": right_id}

    return SemanticDiff(
        left_id=left.interpretation_id,
        right_id=right.interpretation_id,
        changed_fields=tuple(changed),
        field_deltas=deltas,
        material=material,
        left_identity=left_id,
        right_identity=right_id,
    )


def property_classes_cannot_collapse(
    classes: Sequence[PropertyClass | str] | None = None,
    *,
    target_state: Mapping[str, Any] | None = None,
    current_state: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return material identities for each class; asserts pairwise uniqueness.

    Raises :class:`GoalAmbiguityError` if any two classes collapse.
    """

    resolved = [
        _property_class(item)
        for item in (classes if classes is not None else NON_COLLAPSIBLE_PROPERTY_CLASSES)
    ]
    target = dict(target_state or {"phase": "ready"})
    current = dict(current_state or {"phase": "init"})
    env = dict(environment or {})
    identities: dict[str, str] = {}
    seen: dict[str, str] = {}
    for index, prop in enumerate(resolved):
        # Disambiguate duplicate class entries so collapse detection still fires.
        label = prop.value if prop.value not in identities else f"{prop.value}#{index}"
        interp = EndGoalInterpretation(
            interpretation_id=f"collapse-check:{label}",
            controlled_english=controlled_english_for(
                prop,
                target_state=target,
                current_state=current,
                environment=env,
            ),
            property_class=prop,
            quantifiers=quantifiers_for_property_class(prop),
            current_state=current,
            target_state=target,
            environment=env,
            semantic_diff={},
            unresolved_fields=(),
            selected=False,
        )
        identity = material_identity(interp)
        if identity in seen:
            raise GoalAmbiguityError(
                f"property classes collapse: {seen[identity]!r} and {label!r} "
                f"share material identity {identity}"
            )
        seen[identity] = label
        identities[label] = identity
    return identities


# ---------------------------------------------------------------------------
# Confirmation requirements
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfirmationRequirement:
    """What the caller must provide before the gate admits a selection."""

    SCHEMA: ClassVar[str] = CONFIRMATION_REQUIREMENT_SCHEMA

    kind: ConfirmationKind
    message: str
    candidate_ids: tuple[str, ...] = ()
    unresolved_fields: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, ConfirmationKind, "kind")
        )
        object.__setattr__(
            self, "message", _text(self.message, "message", maximum=4096)
        )
        object.__setattr__(
            self,
            "candidate_ids",
            _string_tuple(self.candidate_ids, "candidate_ids", preserve_order=True),
        )
        object.__setattr__(
            self,
            "unresolved_fields",
            _string_tuple(self.unresolved_fields, "unresolved_fields"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "kind": self.kind.value,
            "message": self.message,
            "candidate_ids": list(self.candidate_ids),
            "unresolved_fields": list(self.unresolved_fields),
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConfirmationRequirement":
        if not isinstance(payload, Mapping):
            raise GoalAmbiguityError("confirmation requirement must be an object")
        return cls(
            kind=payload.get("kind", ConfirmationKind.NONE),
            message=payload.get("message", ""),
            candidate_ids=tuple(payload.get("candidate_ids") or ()),
            unresolved_fields=tuple(payload.get("unresolved_fields") or ()),
            required=bool(payload.get("required", True)),
        )


# ---------------------------------------------------------------------------
# GoalInterpretationSet@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoalInterpretationSet:
    """Bounded set of alternative end-goal interpretations (``GoalInterpretationSet@1``).

    The set is proposal-only: it never claims proof, completion, or silent
    admission.  When more than one material interpretation is present,
    ``ambiguity_status`` is ``requires_selection`` and ``selected_id`` stays
    empty until the gate receives an explicit selection.
    """

    SCHEMA: ClassVar[str] = GOAL_INTERPRETATION_SET_SCHEMA
    INTERFACE: ClassVar[str] = GOAL_INTERPRETATION_SET_INTERFACE

    set_id: str
    goal_id: str
    caller_text: str
    interpretations: tuple[EndGoalInterpretation, ...]
    pairwise_diffs: tuple[SemanticDiff, ...] = ()
    confirmation_requirements: tuple[ConfirmationRequirement, ...] = ()
    ambiguity_status: AmbiguityStatus = AmbiguityStatus.NONE
    selected_id: str = ""
    unresolved_fields: tuple[str, ...] = ()
    material_candidate_ids: tuple[str, ...] = ()
    algorithm_version: str = AMBIGUITY_ALGORITHM_VERSION
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "set_id", _text(self.set_id, "set_id", maximum=256)
        )
        object.__setattr__(
            self, "goal_id", _text(self.goal_id, "goal_id", maximum=256)
        )
        object.__setattr__(
            self,
            "caller_text",
            _text(self.caller_text, "caller_text", maximum=16384),
        )
        interpretations: list[EndGoalInterpretation] = []
        for item in self.interpretations or ():
            if isinstance(item, EndGoalInterpretation):
                interpretations.append(item)
            elif isinstance(item, Mapping):
                interpretations.append(EndGoalInterpretation.from_dict(item))
            else:
                raise GoalAmbiguityError(
                    "interpretations must contain EndGoalInterpretation values"
                )
        if not interpretations:
            raise GoalAmbiguityError(
                "GoalInterpretationSet requires at least one interpretation"
            )
        ids = [item.interpretation_id for item in interpretations]
        if len(ids) != len(set(ids)):
            raise GoalAmbiguityError("interpretation ids must be unique")
        object.__setattr__(self, "interpretations", tuple(interpretations))

        diffs: list[SemanticDiff] = []
        for item in self.pairwise_diffs or ():
            if isinstance(item, SemanticDiff):
                diffs.append(item)
            elif isinstance(item, Mapping):
                diffs.append(SemanticDiff.from_dict(item))
            else:
                raise GoalAmbiguityError(
                    "pairwise_diffs must contain SemanticDiff values"
                )
        object.__setattr__(self, "pairwise_diffs", tuple(diffs))

        requirements: list[ConfirmationRequirement] = []
        for item in self.confirmation_requirements or ():
            if isinstance(item, ConfirmationRequirement):
                requirements.append(item)
            elif isinstance(item, Mapping):
                requirements.append(ConfirmationRequirement.from_dict(item))
            else:
                raise GoalAmbiguityError(
                    "confirmation_requirements must contain "
                    "ConfirmationRequirement values"
                )
        object.__setattr__(
            self, "confirmation_requirements", tuple(requirements)
        )

        status = _enum(self.ambiguity_status, AmbiguityStatus, "ambiguity_status")
        object.__setattr__(self, "ambiguity_status", status)
        object.__setattr__(
            self,
            "selected_id",
            _text(self.selected_id, "selected_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "unresolved_fields",
            _string_tuple(self.unresolved_fields, "unresolved_fields"),
        )
        object.__setattr__(
            self,
            "material_candidate_ids",
            _string_tuple(
                self.material_candidate_ids,
                "material_candidate_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(self.algorithm_version, "algorithm_version", maximum=128),
        )
        meta = _mapping(self.meta, "meta")
        _reject_forbidden_meta(meta, "meta")
        object.__setattr__(self, "meta", meta)

        # Fail closed: never allow a selected flag when selection is required.
        selected_flags = [item for item in interpretations if item.selected]
        if status is AmbiguityStatus.REQUIRES_SELECTION:
            if self.selected_id:
                raise GoalAmbiguityError(
                    "selected_id must be empty while ambiguity requires selection"
                )
            if selected_flags:
                raise GoalAmbiguityError(
                    "no interpretation may be selected while material ambiguity "
                    "requires selection"
                )
        if status is AmbiguityStatus.RESOLVED:
            if not self.selected_id:
                raise GoalAmbiguityError(
                    "resolved interpretation sets require selected_id"
                )
            known = {item.interpretation_id for item in interpretations}
            if self.selected_id not in known:
                raise GoalAmbiguityError(
                    "selected_id must reference an interpretation in the set"
                )
            if len(selected_flags) != 1:
                raise GoalAmbiguityError(
                    "resolved set must mark exactly one interpretation selected"
                )
            if selected_flags[0].interpretation_id != self.selected_id:
                raise GoalAmbiguityError(
                    "selected flag must match selected_id"
                )

        # Reject silent multi-select.
        if len(selected_flags) > 1:
            raise GoalAmbiguityError(
                "at most one interpretation may be selected"
            )

    @property
    def material_count(self) -> int:
        """Number of pairwise-distinct material candidates."""

        if self.material_candidate_ids:
            return len(self.material_candidate_ids)
        identities = {material_identity(item) for item in self.interpretations}
        return len(identities)

    @property
    def requires_selection(self) -> bool:
        return self.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION

    def get(self, interpretation_id: str) -> EndGoalInterpretation:
        for item in self.interpretations:
            if item.interpretation_id == interpretation_id:
                return item
        raise GoalAmbiguityError(
            f"unknown interpretation_id: {interpretation_id!r}"
        )

    def visible_differences(self) -> tuple[str, ...]:
        """Controlled-English strings that differ across candidates."""

        texts = [item.controlled_english for item in self.interpretations]
        unique = list(dict.fromkeys(texts))
        return tuple(unique)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "set_id": self.set_id,
            "goal_id": self.goal_id,
            "caller_text": self.caller_text,
            "interpretations": [item.to_dict() for item in self.interpretations],
            "pairwise_diffs": [item.to_dict() for item in self.pairwise_diffs],
            "confirmation_requirements": [
                item.to_dict() for item in self.confirmation_requirements
            ],
            "ambiguity_status": self.ambiguity_status.value,
            "selected_id": self.selected_id,
            "unresolved_fields": list(self.unresolved_fields),
            "material_candidate_ids": list(self.material_candidate_ids),
            "algorithm_version": self.algorithm_version,
            "meta": dict(self.meta),
            "material_count": self.material_count,
            "requires_selection": self.requires_selection,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalInterpretationSet":
        if not isinstance(payload, Mapping):
            raise GoalAmbiguityError("interpretation set payload must be an object")
        return cls(
            set_id=payload.get("set_id", ""),
            goal_id=payload.get("goal_id", ""),
            caller_text=payload.get("caller_text", ""),
            interpretations=tuple(payload.get("interpretations") or ()),
            pairwise_diffs=tuple(payload.get("pairwise_diffs") or ()),
            confirmation_requirements=tuple(
                payload.get("confirmation_requirements") or ()
            ),
            ambiguity_status=payload.get(
                "ambiguity_status", AmbiguityStatus.NONE
            ),
            selected_id=str(payload.get("selected_id") or ""),
            unresolved_fields=tuple(payload.get("unresolved_fields") or ()),
            material_candidate_ids=tuple(
                payload.get("material_candidate_ids") or ()
            ),
            algorithm_version=str(
                payload.get("algorithm_version") or AMBIGUITY_ALGORITHM_VERSION
            ),
            meta=payload.get("meta") or {},
        )


# ---------------------------------------------------------------------------
# Ambiguity report (gate output envelope)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoalAmbiguityReport:
    """Gate result for an end-goal ambiguity analysis."""

    SCHEMA: ClassVar[str] = GOAL_AMBIGUITY_REPORT_SCHEMA

    status: GateStatus
    interpretation_set: GoalInterpretationSet
    request_digest: str = ""
    admitted: bool = False
    selected_interpretation_id: str = ""
    rejection_reasons: tuple[str, ...] = ()
    algorithm_version: str = AMBIGUITY_ALGORITHM_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, GateStatus, "status")
        )
        if not isinstance(self.interpretation_set, GoalInterpretationSet):
            if isinstance(self.interpretation_set, Mapping):
                object.__setattr__(
                    self,
                    "interpretation_set",
                    GoalInterpretationSet.from_dict(self.interpretation_set),
                )
            else:
                raise GoalAmbiguityError(
                    "interpretation_set must be a GoalInterpretationSet"
                )
        object.__setattr__(
            self,
            "request_digest",
            _text(
                self.request_digest, "request_digest", optional=True, maximum=128
            ),
        )
        object.__setattr__(self, "admitted", _bool(self.admitted, "admitted"))
        if self.admitted:
            raise GoalAmbiguityError(
                "GoalAmbiguityReport cannot admit interpretations "
                "(selection is not admission)"
            )
        object.__setattr__(
            self,
            "selected_interpretation_id",
            _text(
                self.selected_interpretation_id,
                "selected_interpretation_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "rejection_reasons",
            _string_tuple(self.rejection_reasons, "rejection_reasons"),
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(self.algorithm_version, "algorithm_version", maximum=128),
        )
        # Gate status must agree with set status for the selection path.
        if (
            self.status is GateStatus.REQUIRES_SELECTION
            and self.selected_interpretation_id
        ):
            raise GoalAmbiguityError(
                "cannot report a selected interpretation while selection "
                "is still required"
            )
        if self.status is GateStatus.RESOLVED:
            if not self.selected_interpretation_id:
                raise GoalAmbiguityError(
                    "resolved reports require selected_interpretation_id"
                )
            if (
                self.interpretation_set.ambiguity_status
                is not AmbiguityStatus.RESOLVED
            ):
                raise GoalAmbiguityError(
                    "resolved report requires a resolved interpretation set"
                )

    @property
    def requires_selection(self) -> bool:
        return self.status is GateStatus.REQUIRES_SELECTION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": GOAL_AMBIGUITY_GATE_INTERFACE,
            "status": self.status.value,
            "interpretation_set": self.interpretation_set.to_dict(),
            "request_digest": self.request_digest,
            "admitted": False,
            "selected_interpretation_id": self.selected_interpretation_id,
            "rejection_reasons": list(self.rejection_reasons),
            "algorithm_version": self.algorithm_version,
            "requires_selection": self.requires_selection,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalAmbiguityReport":
        if not isinstance(payload, Mapping):
            raise GoalAmbiguityError("ambiguity report payload must be an object")
        if payload.get("admitted") is True:
            raise GoalAmbiguityError("GoalAmbiguityReport cannot admit")
        return cls(
            status=payload.get("status", GateStatus.REJECTED),
            interpretation_set=payload.get("interpretation_set") or {},
            request_digest=str(payload.get("request_digest") or ""),
            admitted=False,
            selected_interpretation_id=str(
                payload.get("selected_interpretation_id") or ""
            ),
            rejection_reasons=tuple(payload.get("rejection_reasons") or ()),
            algorithm_version=str(
                payload.get("algorithm_version") or AMBIGUITY_ALGORITHM_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Prompt classification / expansion
# ---------------------------------------------------------------------------


def is_ambiguous_prompt(text: str) -> bool:
    """Return True when the caller text matches a known ambiguous corpus family."""

    cleaned = _text(text, "caller_text")
    return any(pattern.search(cleaned) for pattern in _AMBIGUOUS_PROMPT_PATTERNS)


def _expansion_classes_for_prompt(text: str) -> tuple[PropertyClass, ...]:
    cleaned = text.strip()
    lower = cleaned.lower()
    if re.search(r"\bfair(?:ness)?\b", lower) and re.search(
        r"\b(?:eventually|liveness|progress|reaches?)\b", lower
    ):
        return _FAIRNESS_EXPANSIONS
    if re.search(r"\bworks?\s+correctly\b", lower) or re.search(
        r"\bis\s+(?:safe|correct|sound)\b", lower
    ):
        return _CORRECTNESS_EXPANSIONS
    if is_ambiguous_prompt(cleaned):
        return _AMBIGUOUS_EXPANSIONS
    return ()


def _extract_target_hints(text: str) -> dict[str, str]:
    """Best-effort target-state hints from free prose (deterministic)."""

    target: dict[str, str] = {}
    match = re.search(
        r"\breaches?\s+(?:the\s+)?(?P<state>[A-Za-z_][A-Za-z0-9_\-]*)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        target["phase"] = match.group("state").lower()
    elif re.search(r"\bready\b", text, re.IGNORECASE):
        target["phase"] = "ready"
    return target


def _extract_current_hints(text: str) -> dict[str, str]:
    match = re.search(
        r"\bfrom\s+(?P<state>[A-Za-z_][A-Za-z0-9_\-]*)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return {"phase": match.group("state").lower()}
    return {"phase": "init"}


def _stable_interp_id(
    goal_id: str, property_class: PropertyClass, ordinal: int
) -> str:
    digest = hashlib.sha256(
        f"{goal_id}|{property_class.value}|{ordinal}".encode("utf-8")
    ).hexdigest()[:12]
    return f"interp:{property_class.value}:{digest}"


def _build_interpretation(
    *,
    interpretation_id: str,
    property_class: PropertyClass,
    current_state: Mapping[str, Any],
    target_state: Mapping[str, Any],
    environment: Mapping[str, Any],
    unresolved_fields: Sequence[str] = (),
    selected: bool = False,
    peer_summary: str = "",
) -> EndGoalInterpretation:
    if selected:
        raise GoalAmbiguityError(
            "interpretations cannot be pre-selected during expansion"
        )
    english = controlled_english_for(
        property_class,
        target_state=target_state,
        current_state=current_state,
        environment=environment,
    )
    semantic_diff: dict[str, Any] = {
        "property_class": property_class.value,
        "quantifiers": [
            q.value for q in quantifiers_for_property_class(property_class)
        ],
    }
    if peer_summary:
        semantic_diff["vs_peers"] = peer_summary
    return EndGoalInterpretation(
        interpretation_id=interpretation_id,
        controlled_english=english,
        property_class=property_class,
        quantifiers=quantifiers_for_property_class(property_class),
        current_state=dict(current_state),
        target_state=dict(target_state),
        environment=dict(environment),
        semantic_diff=semantic_diff,
        unresolved_fields=tuple(sorted(set(unresolved_fields))),
        selected=False,
    )


def _pairwise_material_diffs(
    interpretations: Sequence[EndGoalInterpretation],
) -> tuple[SemanticDiff, ...]:
    diffs: list[SemanticDiff] = []
    for index, left in enumerate(interpretations):
        for right in interpretations[index + 1 :]:
            diff = compare_interpretations(left, right)
            diffs.append(diff)
    return tuple(diffs)


def _material_candidate_ids(
    interpretations: Sequence[EndGoalInterpretation],
    diffs: Sequence[SemanticDiff],
) -> tuple[str, ...]:
    """Ids of interpretations that participate in at least one material diff,
    or all unique material-identity representatives when only one exists.
    """

    if len(interpretations) == 1:
        return (interpretations[0].interpretation_id,)

    # Prefer ids that differ by material pairwise comparison.
    material_ids: list[str] = []
    for diff in diffs:
        if diff.material:
            if diff.left_id not in material_ids:
                material_ids.append(diff.left_id)
            if diff.right_id not in material_ids:
                material_ids.append(diff.right_id)

    if material_ids:
        return tuple(material_ids)

    # Fall back to unique material identities (dedupe syntactic clones).
    seen: dict[str, str] = {}
    for item in interpretations:
        identity = material_identity(item)
        if identity not in seen:
            seen[identity] = item.interpretation_id
    return tuple(seen.values())


def _status_for_candidates(
    material_ids: Sequence[str],
    *,
    unsupported: bool = False,
) -> AmbiguityStatus:
    if unsupported:
        return AmbiguityStatus.UNSUPPORTED
    if len(material_ids) > 1:
        return AmbiguityStatus.REQUIRES_SELECTION
    if len(material_ids) == 1:
        return AmbiguityStatus.CANDIDATES_PRESENT
    return AmbiguityStatus.NONE


def _confirmation_for(
    status: AmbiguityStatus,
    material_ids: Sequence[str],
    unresolved: Sequence[str],
) -> tuple[ConfirmationRequirement, ...]:
    requirements: list[ConfirmationRequirement] = []
    if status is AmbiguityStatus.REQUIRES_SELECTION:
        requirements.append(
            ConfirmationRequirement(
                kind=ConfirmationKind.SELECT_INTERPRETATION,
                message=(
                    "Material ambiguity remains: select exactly one "
                    "interpretation_id before confirmation. Silent selection "
                    "is forbidden."
                ),
                candidate_ids=tuple(material_ids),
                unresolved_fields=tuple(sorted(set(unresolved))),
                required=True,
            )
        )
    if unresolved and status is not AmbiguityStatus.RESOLVED:
        requirements.append(
            ConfirmationRequirement(
                kind=ConfirmationKind.CLARIFY_UNRESOLVED,
                message=(
                    "Unresolved fields remain and must be clarified or "
                    "explicitly accepted as open: "
                    + ", ".join(sorted(set(unresolved)))
                ),
                candidate_ids=tuple(material_ids),
                unresolved_fields=tuple(sorted(set(unresolved))),
                required=status is AmbiguityStatus.REQUIRES_SELECTION,
            )
        )
    if status is AmbiguityStatus.UNSUPPORTED:
        requirements.append(
            ConfirmationRequirement(
                kind=ConfirmationKind.REJECT_UNSUPPORTED,
                message="Unsupported semantics block confirmation.",
                candidate_ids=tuple(material_ids),
                unresolved_fields=tuple(sorted(set(unresolved))),
                required=True,
            )
        )
    if not requirements:
        requirements.append(
            ConfirmationRequirement(
                kind=ConfirmationKind.NONE,
                message="No material ambiguity requires confirmation.",
                candidate_ids=tuple(material_ids),
                unresolved_fields=(),
                required=False,
            )
        )
    return tuple(requirements)


def build_interpretation_set(
    *,
    goal_id: str,
    caller_text: str,
    interpretations: Sequence[EndGoalInterpretation],
    set_id: str = "",
    unresolved_fields: Sequence[str] = (),
    meta: Mapping[str, Any] | None = None,
) -> GoalInterpretationSet:
    """Assemble a ``GoalInterpretationSet`` with diffs and confirmation policy."""

    items = tuple(interpretations)
    if not items:
        raise GoalAmbiguityError("at least one interpretation is required")
    diffs = _pairwise_material_diffs(items)
    material_ids = _material_candidate_ids(items, diffs)
    unresolved = _string_tuple(unresolved_fields, "unresolved_fields")
    # Aggregate unresolved from members.
    for item in items:
        for field_name in item.unresolved_fields:
            if field_name not in unresolved:
                unresolved = unresolved + (field_name,)
    status = _status_for_candidates(material_ids)
    # Multiple material candidates always require selection (never silent).
    if len(material_ids) > 1:
        status = AmbiguityStatus.REQUIRES_SELECTION
    requirements = _confirmation_for(status, material_ids, unresolved)
    digest_seed = {
        "goal_id": goal_id,
        "caller_text": caller_text,
        "ids": [item.interpretation_id for item in items],
        "material_ids": list(material_ids),
    }
    resolved_set_id = set_id or f"iset:{_digest(digest_seed)[7:23]}"
    return GoalInterpretationSet(
        set_id=resolved_set_id,
        goal_id=goal_id,
        caller_text=caller_text,
        interpretations=items,
        pairwise_diffs=diffs,
        confirmation_requirements=requirements,
        ambiguity_status=status,
        selected_id="",
        unresolved_fields=unresolved,
        material_candidate_ids=material_ids,
        algorithm_version=AMBIGUITY_ALGORITHM_VERSION,
        meta=dict(meta or {}),
    )


def expand_ambiguous_prompt(
    caller_text: str,
    *,
    goal_id: str = "goal:ambiguous",
    current_state: Mapping[str, Any] | None = None,
    target_state: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    max_candidates: int = 8,
) -> GoalInterpretationSet:
    """Expand a known-ambiguous prompt into material interpretation candidates.

    Ambiguous corpus prompts always return at least two visibly different
    candidates.  Unrecognized prompts still produce a single underspecified
    candidate that does not auto-confirm.
    """

    text = _text(caller_text, "caller_text")
    if max_candidates < 1:
        raise GoalAmbiguityError("max_candidates must be >= 1")
    expansions = _expansion_classes_for_prompt(text)
    current = dict(current_state or _extract_current_hints(text))
    target = dict(target_state or _extract_target_hints(text) or {"phase": "ready"})
    env = dict(environment or {})

    if not expansions:
        # Single candidate — still never selected.
        unresolved = ["property_class"]
        if not target:
            unresolved.append("target_state")
        single = _build_interpretation(
            interpretation_id=_stable_interp_id(
                goal_id, PropertyClass.UNSPECIFIED, 0
            ),
            property_class=PropertyClass.UNSPECIFIED,
            current_state=current,
            target_state=target,
            environment=env,
            unresolved_fields=unresolved,
            peer_summary="single underspecified candidate",
        )
        return build_interpretation_set(
            goal_id=goal_id,
            caller_text=text,
            interpretations=(single,),
            unresolved_fields=unresolved,
            meta={"expansion": "underspecified"},
        )

    classes = expansions[:max_candidates]
    peer_summary = (
        "material alternatives: "
        + ", ".join(item.value for item in classes)
    )
    built: list[EndGoalInterpretation] = []
    for ordinal, prop in enumerate(classes):
        built.append(
            _build_interpretation(
                interpretation_id=_stable_interp_id(goal_id, prop, ordinal),
                property_class=prop,
                current_state=current,
                target_state=target,
                environment=env,
                unresolved_fields=(),
                peer_summary=peer_summary,
            )
        )

    interpretation_set = build_interpretation_set(
        goal_id=goal_id,
        caller_text=text,
        interpretations=tuple(built),
        meta={
            "expansion": "ambiguous_prompt",
            "expansion_classes": [item.value for item in classes],
        },
    )
    # Acceptance: ambiguous prompts yield ≥2 visibly different candidates.
    if is_ambiguous_prompt(text) and interpretation_set.material_count < 2:
        raise GoalAmbiguityError(
            "ambiguous corpus prompt produced fewer than two material candidates"
        )
    if is_ambiguous_prompt(text) and len(interpretation_set.visible_differences()) < 2:
        raise GoalAmbiguityError(
            "ambiguous corpus prompt candidates are not visibly different"
        )
    return interpretation_set


def expand_from_end_goal(
    end_goal: EndGoalSpec,
    *,
    force_expand_ambiguous: bool = True,
    max_candidates: int = 8,
) -> GoalInterpretationSet:
    """Build an interpretation set from an existing ``EndGoalSpec``.

    When the spec already carries multiple interpretations, those are used.
    When the caller text is an ambiguous corpus prompt and only one (or zero)
    interpretation is present, the gate expands material alternatives so that
    selection cannot be skipped.
    """

    if not isinstance(end_goal, EndGoalSpec):
        raise GoalAmbiguityError("end_goal must be an EndGoalSpec")

    existing = list(end_goal.interpretations)
    if len(existing) >= 2:
        # Ensure none are silently selected unless status is resolved.
        cleaned: list[EndGoalInterpretation] = []
        for item in existing:
            if item.selected and end_goal.ambiguity_status is not AmbiguityStatus.RESOLVED:
                cleaned.append(
                    EndGoalInterpretation(
                        interpretation_id=item.interpretation_id,
                        controlled_english=item.controlled_english,
                        property_class=item.property_class,
                        quantifiers=item.quantifiers,
                        current_state=item.current_state,
                        target_state=item.target_state,
                        environment=item.environment,
                        semantic_diff=item.semantic_diff,
                        unresolved_fields=item.unresolved_fields,
                        selected=False,
                    )
                )
            else:
                cleaned.append(item)
        return build_interpretation_set(
            goal_id=end_goal.goal_id,
            caller_text=end_goal.caller_text,
            interpretations=tuple(cleaned),
            unresolved_fields=(),
            meta={"source": "end_goal_interpretations"},
        )

    if force_expand_ambiguous and is_ambiguous_prompt(end_goal.caller_text):
        return expand_ambiguous_prompt(
            end_goal.caller_text,
            goal_id=end_goal.goal_id,
            current_state=end_goal.current_state or None,
            target_state=end_goal.target_state or None,
            environment=end_goal.environment or None,
            max_candidates=max_candidates,
        )

    if existing:
        return build_interpretation_set(
            goal_id=end_goal.goal_id,
            caller_text=end_goal.caller_text,
            interpretations=tuple(existing),
            meta={"source": "end_goal_single"},
        )

    # Synthesize one interpretation from the end-goal bindings.
    prop = end_goal.property_class
    unresolved: list[str] = []
    if prop is PropertyClass.UNSPECIFIED:
        unresolved.append("property_class")
    synthetic = _build_interpretation(
        interpretation_id=_stable_interp_id(end_goal.goal_id, prop, 0),
        property_class=prop,
        current_state=end_goal.current_state,
        target_state=end_goal.target_state,
        environment=end_goal.environment,
        unresolved_fields=unresolved,
        peer_summary="synthesized from EndGoalSpec bindings",
    )
    return build_interpretation_set(
        goal_id=end_goal.goal_id,
        caller_text=end_goal.caller_text,
        interpretations=(synthetic,),
        unresolved_fields=tuple(unresolved),
        meta={"source": "end_goal_synthesized"},
    )


# ---------------------------------------------------------------------------
# GoalAmbiguityGate@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoalAmbiguityGate:
    """Fail-closed gate that exposes ambiguity and requires material selection.

    Interface: ``GoalAmbiguityGate@1``.

    The gate:

    1. expands or accepts candidate interpretations;
    2. computes deterministic pairwise semantic diffs;
    3. marks ``requires_selection`` when ≥2 material candidates remain; and
    4. only resolves after an **explicit** ``select`` call — never by defaulting
       to the first candidate.
    """

    INTERFACE: ClassVar[str] = GOAL_AMBIGUITY_GATE_INTERFACE

    max_candidates: int = 8
    force_expand_ambiguous: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.max_candidates, int) or self.max_candidates < 1:
            raise GoalAmbiguityError("max_candidates must be a positive integer")
        if self.max_candidates > 64:
            raise GoalAmbiguityError("max_candidates cannot exceed 64")
        object.__setattr__(
            self,
            "force_expand_ambiguous",
            _bool(self.force_expand_ambiguous, "force_expand_ambiguous"),
        )

    def analyze_prompt(
        self,
        caller_text: str,
        *,
        goal_id: str = "goal:ambiguous",
        current_state: Mapping[str, Any] | None = None,
        target_state: Mapping[str, Any] | None = None,
        environment: Mapping[str, Any] | None = None,
    ) -> GoalAmbiguityReport:
        """Analyze free-prose / corpus caller text for material ambiguity."""

        interpretation_set = expand_ambiguous_prompt(
            caller_text,
            goal_id=goal_id,
            current_state=current_state,
            target_state=target_state,
            environment=environment,
            max_candidates=self.max_candidates,
        )
        return self._report_from_set(interpretation_set)

    def analyze_end_goal(self, end_goal: EndGoalSpec) -> GoalAmbiguityReport:
        """Analyze a formalized end goal for material ambiguity."""

        interpretation_set = expand_from_end_goal(
            end_goal,
            force_expand_ambiguous=self.force_expand_ambiguous,
            max_candidates=self.max_candidates,
        )
        return self._report_from_set(
            interpretation_set,
            request_digest=getattr(end_goal, "content_id", "")
            if hasattr(end_goal, "content_id")
            else content_identity(end_goal.to_dict()),
        )

    def analyze(
        self,
        source: EndGoalSpec | str | GoalInterpretationSet,
        *,
        goal_id: str = "goal:ambiguous",
    ) -> GoalAmbiguityReport:
        """Dispatch analysis over an end goal, prompt string, or existing set."""

        if isinstance(source, GoalInterpretationSet):
            return self._report_from_set(source)
        if isinstance(source, EndGoalSpec):
            return self.analyze_end_goal(source)
        if isinstance(source, str):
            return self.analyze_prompt(source, goal_id=goal_id)
        raise GoalAmbiguityError(
            "source must be an EndGoalSpec, caller text string, "
            "or GoalInterpretationSet"
        )

    def compare_goal_interpretations(
        self,
        left: EndGoalInterpretation,
        right: EndGoalInterpretation,
    ) -> SemanticDiff:
        """Public pairwise comparison (stable API surface name)."""

        return compare_interpretations(left, right)

    def select(
        self,
        interpretation_set: GoalInterpretationSet,
        interpretation_id: str,
        *,
        allow_when_unambiguous: bool = True,
    ) -> GoalAmbiguityReport:
        """Explicitly select one interpretation; never silent.

        Raises if:

        * the id is unknown;
        * material ambiguity remains and ``interpretation_id`` is empty; or
        * a caller attempts to mark selection without naming an id.
        """

        if not isinstance(interpretation_set, GoalInterpretationSet):
            raise GoalAmbiguityError(
                "interpretation_set must be a GoalInterpretationSet"
            )
        selected_id = _text(interpretation_id, "interpretation_id", maximum=256)
        chosen = interpretation_set.get(selected_id)

        if (
            interpretation_set.ambiguity_status
            is AmbiguityStatus.REQUIRES_SELECTION
            and not selected_id
        ):
            raise GoalAmbiguityError(
                "material ambiguity requires an explicit interpretation_id; "
                "silent selection is forbidden"
            )

        if (
            interpretation_set.material_count > 1
            and selected_id
            not in interpretation_set.material_candidate_ids
            and selected_id
            not in {item.interpretation_id for item in interpretation_set.interpretations}
        ):
            raise GoalAmbiguityError(
                "selected interpretation_id is not a material candidate"
            )

        if (
            not allow_when_unambiguous
            and interpretation_set.ambiguity_status is AmbiguityStatus.NONE
        ):
            raise GoalAmbiguityError("nothing to select for an empty ambiguity set")

        # Rebuild interpretations with exactly one selected flag.
        rebuilt: list[EndGoalInterpretation] = []
        for item in interpretation_set.interpretations:
            rebuilt.append(
                EndGoalInterpretation(
                    interpretation_id=item.interpretation_id,
                    controlled_english=item.controlled_english,
                    property_class=item.property_class,
                    quantifiers=item.quantifiers,
                    current_state=item.current_state,
                    target_state=item.target_state,
                    environment=item.environment,
                    semantic_diff=item.semantic_diff,
                    unresolved_fields=item.unresolved_fields,
                    selected=(item.interpretation_id == selected_id),
                )
            )

        resolved = GoalInterpretationSet(
            set_id=interpretation_set.set_id,
            goal_id=interpretation_set.goal_id,
            caller_text=interpretation_set.caller_text,
            interpretations=tuple(rebuilt),
            pairwise_diffs=interpretation_set.pairwise_diffs,
            confirmation_requirements=(
                ConfirmationRequirement(
                    kind=ConfirmationKind.NONE,
                    message=(
                        f"Interpretation {selected_id!r} explicitly selected; "
                        f"ambiguity resolved."
                    ),
                    candidate_ids=(selected_id,),
                    unresolved_fields=(),
                    required=False,
                ),
            ),
            ambiguity_status=AmbiguityStatus.RESOLVED,
            selected_id=selected_id,
            unresolved_fields=(),
            material_candidate_ids=interpretation_set.material_candidate_ids
            or (selected_id,),
            algorithm_version=interpretation_set.algorithm_version,
            meta={
                **dict(interpretation_set.meta),
                "selection": "explicit",
                "selected_property_class": chosen.property_class.value,
            },
        )
        return GoalAmbiguityReport(
            status=GateStatus.RESOLVED,
            interpretation_set=resolved,
            request_digest="",
            admitted=False,
            selected_interpretation_id=selected_id,
            rejection_reasons=(),
            algorithm_version=AMBIGUITY_ALGORITHM_VERSION,
        )

    def require_selection_or_raise(
        self, report: GoalAmbiguityReport
    ) -> None:
        """Raise if material ambiguity remains unresolved (fail closed)."""

        if report.requires_selection:
            raise GoalAmbiguityError(
                "material ambiguity requires interpretation selection; "
                "cannot proceed silently"
            )
        if report.interpretation_set.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION:
            raise GoalAmbiguityError(
                "interpretation set still requires selection"
            )

    def apply_to_end_goal(
        self,
        end_goal: EndGoalSpec,
        report: GoalAmbiguityReport,
    ) -> EndGoalSpec:
        """Return a new ``EndGoalSpec`` bound to the gate report's interpretations.

        Never silently flips ``ambiguity_status`` to ``resolved`` without an
        explicit selection on the report.  Never sets proof/completion claims.
        """

        if not isinstance(end_goal, EndGoalSpec):
            raise GoalAmbiguityError("end_goal must be an EndGoalSpec")
        if not isinstance(report, GoalAmbiguityReport):
            raise GoalAmbiguityError("report must be a GoalAmbiguityReport")

        interpretation_set = report.interpretation_set
        status = interpretation_set.ambiguity_status
        if (
            status is AmbiguityStatus.REQUIRES_SELECTION
            and report.selected_interpretation_id
        ):
            raise GoalAmbiguityError(
                "inconsistent report: selection present while status requires "
                "selection"
            )

        # If resolved, pin property_class / quantifiers to the selected interp.
        property_class = end_goal.property_class
        quantifiers = end_goal.quantifiers
        if (
            status is AmbiguityStatus.RESOLVED
            and report.selected_interpretation_id
        ):
            chosen = interpretation_set.get(report.selected_interpretation_id)
            property_class = chosen.property_class
            quantifiers = chosen.quantifiers

        return EndGoalSpec(
            goal_id=end_goal.goal_id,
            root_goal_id=end_goal.root_goal_id or end_goal.goal_id,
            caller_text=end_goal.caller_text,
            source=end_goal.source,
            property_class=property_class,
            quantifiers=quantifiers,
            actors=end_goal.actors,
            state_variables=end_goal.state_variables,
            current_state=end_goal.current_state,
            target_state=end_goal.target_state,
            transitions=end_goal.transitions,
            environment=end_goal.environment,
            interference=end_goal.interference,
            assumptions=end_goal.assumptions,
            logic_family=end_goal.logic_family,
            provider_ids=end_goal.provider_ids,
            assurance_target=end_goal.assurance_target,
            bounds=end_goal.bounds,
            provenance=end_goal.provenance,
            interpretations=interpretation_set.interpretations,
            ambiguity_status=status,
            unsupported_semantics=end_goal.unsupported_semantics,
            translation_loss=end_goal.translation_loss,
            acceptance_evidence=end_goal.acceptance_evidence,
            expected_receipt_classes=end_goal.expected_receipt_classes,
            status=end_goal.status,
            authority=end_goal.authority
            if end_goal.authority is not AuthorityCeiling.NONE
            else AuthorityCeiling.ADVISORY,
            proof_claimed=False,
            completion_claimed=False,
        )

    def _report_from_set(
        self,
        interpretation_set: GoalInterpretationSet,
        *,
        request_digest: str = "",
    ) -> GoalAmbiguityReport:
        status_map = {
            AmbiguityStatus.NONE: GateStatus.UNAMBIGUOUS,
            AmbiguityStatus.CANDIDATES_PRESENT: GateStatus.CANDIDATES_PRESENT,
            AmbiguityStatus.REQUIRES_SELECTION: GateStatus.REQUIRES_SELECTION,
            AmbiguityStatus.RESOLVED: GateStatus.RESOLVED,
            AmbiguityStatus.UNSUPPORTED: GateStatus.UNSUPPORTED,
        }
        gate_status = status_map.get(
            interpretation_set.ambiguity_status, GateStatus.REJECTED
        )
        # Hard invariant: multi material → requires selection, never auto resolve.
        if interpretation_set.material_count > 1:
            if interpretation_set.ambiguity_status is AmbiguityStatus.RESOLVED:
                if not interpretation_set.selected_id:
                    raise GoalAmbiguityError(
                        "multi-candidate set cannot be resolved without "
                        "selected_id"
                    )
            elif interpretation_set.selected_id:
                raise GoalAmbiguityError(
                    "selected_id set without resolved status (silent selection)"
                )
            else:
                gate_status = GateStatus.REQUIRES_SELECTION

        selected = (
            interpretation_set.selected_id
            if gate_status is GateStatus.RESOLVED
            else ""
        )
        return GoalAmbiguityReport(
            status=gate_status,
            interpretation_set=interpretation_set,
            request_digest=request_digest,
            admitted=False,
            selected_interpretation_id=selected,
            rejection_reasons=(),
            algorithm_version=AMBIGUITY_ALGORITHM_VERSION,
        )


# ---------------------------------------------------------------------------
# Module convenience API
# ---------------------------------------------------------------------------


def compare_goal_interpretations(
    left: EndGoalInterpretation,
    right: EndGoalInterpretation,
) -> SemanticDiff:
    """Module-level alias for the public ``compare_goal_interpretations`` op."""

    return compare_interpretations(left, right)


def expose_ambiguity(
    source: EndGoalSpec | str,
    *,
    goal_id: str = "goal:ambiguous",
    max_candidates: int = 8,
) -> GoalAmbiguityReport:
    """One-shot analysis entry point used by higher-level tactician surfaces."""

    gate = GoalAmbiguityGate(max_candidates=max_candidates)
    return gate.analyze(source, goal_id=goal_id)


__all__ = [
    "GOAL_INTERPRETATION_SET_INTERFACE",
    "GOAL_AMBIGUITY_GATE_INTERFACE",
    "GOAL_INTERPRETATION_SET_SCHEMA",
    "GOAL_AMBIGUITY_REPORT_SCHEMA",
    "SEMANTIC_DIFF_SCHEMA",
    "CONFIRMATION_REQUIREMENT_SCHEMA",
    "AMBIGUITY_ALGORITHM_VERSION",
    "NON_COLLAPSIBLE_PROPERTY_CLASSES",
    "GoalAmbiguityError",
    "GateStatus",
    "ConfirmationKind",
    "SemanticDiff",
    "ConfirmationRequirement",
    "GoalInterpretationSet",
    "GoalAmbiguityReport",
    "GoalAmbiguityGate",
    "quantifiers_for_property_class",
    "controlled_english_for",
    "material_identity",
    "compare_interpretations",
    "compare_goal_interpretations",
    "property_classes_cannot_collapse",
    "is_ambiguous_prompt",
    "build_interpretation_set",
    "expand_ambiguous_prompt",
    "expand_from_end_goal",
    "expose_ambiguity",
]
