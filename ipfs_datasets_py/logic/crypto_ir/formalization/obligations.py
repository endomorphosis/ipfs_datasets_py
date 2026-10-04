"""Named formal obligations prepared for sound lowering (CRYPTOIR-G320).

This module binds security :class:`~..security_rules.ProofObligation` records
to an exact model digest and a payload kind.  It never claims proof and never
submits work to a solver.  Opaque ``security_verification_condition`` JSON and
prose remain explicitly non-executable payload kinds.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity
from ...ir_core.provenance import ProvenanceValidationError, thaw_json
from ..identity import crypto_ir_identity
from ..model import CryptoIRValidationError
from ..provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from ..schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ..security_rules import (
    FormalTargetKind,
    ObligationCategory,
    ProofObligation,
    ViolationWitness,
    assert_not_universal_secure,
)


CRYPTO_IR_FORMALIZATION_DOMAIN: Final[str] = "crypto-ir.formalization"
CRYPTO_IR_FORMALIZATION_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION
FORMAL_OBLIGATION_SCHEMA_VERSION: Final[str] = "crypto-ir.formal-obligation@1.0.0"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DIGEST_RE = re.compile(r"^[A-Fa-f0-9]{16,128}$|^$")

# Historical opaque payload family that existing solver compilers do not execute.
OPAQUE_SECURITY_VERIFICATION_CONDITION: Final[str] = "security_verification_condition"


class FormalizationError(CryptoIRValidationError):
    """Raised when a formalization obligation or payload is malformed."""


class LogicFamily(str, Enum):
    """Logic families a reviewed lowering may target.

    A family is only executable when a backend declares it and the compiler
    produces a *compiled* payload for that family.  Opaque and prose never
    become executable families.
    """

    SMT_LIB = "smt_lib"
    PROPOSITIONAL = "propositional"
    FOL = "fol"
    DATALOG = "datalog"
    TEMPORAL = "temporal"
    OPAQUE = "opaque"
    PROSE = "prose"
    UNSUPPORTED = "unsupported"


class ObligationPayloadKind(str, Enum):
    """How the obligation body is represented before / after lowering."""

    COMPILED_SMT_LIB = "compiled_smt_lib"
    PROPOSITIONAL_FORMULA = "propositional_formula"
    FOL_FORMULA = "fol_formula"
    DATALOG_RULES = "datalog_rules"
    TEMPORAL_FORMULA = "temporal_formula"
    SECURITY_VERIFICATION_CONDITION = "security_verification_condition"
    PROSE = "prose"
    UNSUPPORTED = "unsupported"
    EMPTY = "empty"


# Payload kinds that must never be submitted to a solver backend.
NON_EXECUTABLE_PAYLOAD_KINDS: Final[frozenset[ObligationPayloadKind]] = frozenset(
    {
        ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION,
        ObligationPayloadKind.PROSE,
        ObligationPayloadKind.UNSUPPORTED,
        ObligationPayloadKind.EMPTY,
    }
)

# Logic families that never receive backend submission.
NON_EXECUTABLE_LOGIC_FAMILIES: Final[frozenset[LogicFamily]] = frozenset(
    {
        LogicFamily.OPAQUE,
        LogicFamily.PROSE,
        LogicFamily.UNSUPPORTED,
    }
)

_FORMAL_TARGET_TO_LOGIC: Final[Mapping[FormalTargetKind, LogicFamily]] = {
    FormalTargetKind.SMT_LIB: LogicFamily.SMT_LIB,
    FormalTargetKind.FOL: LogicFamily.FOL,
    FormalTargetKind.DATALOG: LogicFamily.DATALOG,
    FormalTargetKind.TEMPORAL: LogicFamily.TEMPORAL,
    FormalTargetKind.PROPOSITIONAL: LogicFamily.PROPOSITIONAL,
    FormalTargetKind.MONITOR: LogicFamily.UNSUPPORTED,
    FormalTargetKind.DETERMINISTIC: LogicFamily.PROPOSITIONAL,
}


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise FormalizationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise FormalizationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise FormalizationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise FormalizationError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FormalizationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FormalizationError(f"unknown {name} field(s): {', '.join(unknown)}")


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (
        ProvenanceValidationError,
        CryptoIRProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise FormalizationError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise FormalizationError(f"unsupported {name}: {value!r}") from exc


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise FormalizationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise FormalizationError(f"{name} values must be unique")
    return result


def _model_digest(value: Any) -> str:
    text = _text(value, "model_digest", allow_empty=True)
    if text and not _DIGEST_RE.fullmatch(text):
        raise FormalizationError("model_digest must be a hex digest or empty")
    return text


def logic_family_for_formal_target(kind: FormalTargetKind | str) -> LogicFamily:
    """Map a security-rule formal target kind to a logic family."""

    target = _enum(FormalTargetKind, kind, "formal_target_kind")
    return _FORMAL_TARGET_TO_LOGIC.get(target, LogicFamily.UNSUPPORTED)  # type: ignore[arg-type]


def detect_payload_kind(
    payload: Any,
    *,
    formal_target_kind: FormalTargetKind | str | None = None,
    declared_kind: ObligationPayloadKind | str | None = None,
) -> ObligationPayloadKind:
    """Classify an obligation body; never promotes opaque JSON to compiled.

    Detection rules (first match wins when *declared_kind* is absent):

    * empty / ``None`` → :attr:`ObligationPayloadKind.EMPTY`
    * mapping with family ``security_verification_condition`` → opaque SVC
    * non-empty prose string without SMT-LIB markers → :attr:`ObligationPayloadKind.PROSE`
    * SMT-LIB text → :attr:`ObligationPayloadKind.COMPILED_SMT_LIB`
    * otherwise use *formal_target_kind* or :attr:`ObligationPayloadKind.UNSUPPORTED`
    """

    if declared_kind is not None:
        return _enum(  # type: ignore[return-value]
            ObligationPayloadKind, declared_kind, "declared_kind"
        )

    if payload is None:
        return ObligationPayloadKind.EMPTY

    if isinstance(payload, Mapping):
        family = str(payload.get("family") or payload.get("kind") or "").strip()
        if family == OPAQUE_SECURITY_VERIFICATION_CONDITION:
            return ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION
        if "security_verification_condition" in payload:
            return ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION
        # Generic JSON without a reviewed compiled form remains opaque.
        return ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION

    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return ObligationPayloadKind.EMPTY
        lowered = text.lower()
        if "(assert" in lowered or "(check-sat" in lowered or "(declare-" in lowered:
            return ObligationPayloadKind.COMPILED_SMT_LIB
        if formal_target_kind is not None:
            target = _enum(FormalTargetKind, formal_target_kind, "formal_target_kind")
            if target is FormalTargetKind.PROPOSITIONAL:
                return ObligationPayloadKind.PROPOSITIONAL_FORMULA
            if target is FormalTargetKind.FOL:
                return ObligationPayloadKind.FOL_FORMULA
            if target is FormalTargetKind.DATALOG:
                return ObligationPayloadKind.DATALOG_RULES
            if target is FormalTargetKind.TEMPORAL:
                return ObligationPayloadKind.TEMPORAL_FORMULA
            if target is FormalTargetKind.SMT_LIB:
                return ObligationPayloadKind.COMPILED_SMT_LIB
            if target is FormalTargetKind.DETERMINISTIC:
                return ObligationPayloadKind.PROPOSITIONAL_FORMULA
        # Free-form prose / narrative claim text.
        return ObligationPayloadKind.PROSE

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        if formal_target_kind is not None:
            target = _enum(FormalTargetKind, formal_target_kind, "formal_target_kind")
            if target is FormalTargetKind.DATALOG:
                return ObligationPayloadKind.DATALOG_RULES
        return ObligationPayloadKind.UNSUPPORTED

    return ObligationPayloadKind.UNSUPPORTED


def is_executable_payload(kind: ObligationPayloadKind | str) -> bool:
    """Return True when *kind* may be submitted to a compiling backend."""

    value = _enum(ObligationPayloadKind, kind, "kind")
    return value not in NON_EXECUTABLE_PAYLOAD_KINDS


@dataclass(frozen=True, slots=True)
class FormalObligation:
    """A named security obligation bound to an exact model for formalization.

    The obligation may carry a pre-compiled body or a source claim that still
    needs lowering.  Construction never executes a prover.
    """

    obligation_id: str
    category: ObligationCategory
    statement: str
    formal_target: str
    formal_target_kind: FormalTargetKind
    model_digest: str
    required_fact_ids: tuple[str, ...]
    required_semantic_dimensions: tuple[str, ...]
    payload: Any = ""
    payload_kind: ObligationPayloadKind = ObligationPayloadKind.EMPTY
    trusted_assumption_ids: tuple[str, ...] = ()
    policy_id: str = ""
    policy_revision: str = ""
    capability_ids: tuple[str, ...] = ()
    code_epoch: str = ""
    violation_witness: ViolationWitness | None = None
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FORMAL_OBLIGATION_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "category", _enum(ObligationCategory, self.category, "category")
        )
        object.__setattr__(
            self, "statement", assert_not_universal_secure(self.statement)
        )
        object.__setattr__(
            self, "formal_target", _text(self.formal_target, "formal_target")
        )
        object.__setattr__(
            self,
            "formal_target_kind",
            _enum(FormalTargetKind, self.formal_target_kind, "formal_target_kind"),
        )
        object.__setattr__(self, "model_digest", _model_digest(self.model_digest))
        object.__setattr__(
            self,
            "required_fact_ids",
            _unique_ids(self.required_fact_ids, "required_fact_ids"),
        )
        if not self.required_fact_ids:
            raise FormalizationError(
                "formal obligation must declare at least one required fact"
            )
        object.__setattr__(
            self,
            "required_semantic_dimensions",
            _unique_ids(
                self.required_semantic_dimensions, "required_semantic_dimensions"
            ),
        )
        if not self.required_semantic_dimensions:
            raise FormalizationError(
                "formal obligation must declare at least one semantic dimension"
            )
        kind = _enum(ObligationPayloadKind, self.payload_kind, "payload_kind")
        if kind is ObligationPayloadKind.EMPTY:
            kind = detect_payload_kind(
                self.payload, formal_target_kind=self.formal_target_kind
            )
        object.__setattr__(self, "payload_kind", kind)
        object.__setattr__(
            self,
            "trusted_assumption_ids",
            _unique_ids(self.trusted_assumption_ids, "trusted_assumption_ids"),
        )
        object.__setattr__(
            self, "policy_id", _text(self.policy_id, "policy_id", allow_empty=True)
        )
        object.__setattr__(
            self,
            "policy_revision",
            _text(self.policy_revision, "policy_revision", allow_empty=True),
        )
        object.__setattr__(
            self, "capability_ids", _unique_ids(self.capability_ids, "capability_ids")
        )
        object.__setattr__(
            self, "code_epoch", _text(self.code_epoch, "code_epoch", allow_empty=True)
        )
        if self.violation_witness is not None and not isinstance(
            self.violation_witness, ViolationWitness
        ):
            if isinstance(self.violation_witness, Mapping):
                object.__setattr__(
                    self,
                    "violation_witness",
                    ViolationWitness.from_dict(self.violation_witness),
                )
            else:
                raise FormalizationError(
                    "violation_witness must be ViolationWitness or mapping"
                )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        if self.summary:
            assert_not_universal_secure(self.summary, field="summary")
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @classmethod
    def from_proof_obligation(
        cls,
        obligation: ProofObligation,
        *,
        model_digest: str,
        payload: Any = "",
        payload_kind: ObligationPayloadKind | str | None = None,
        policy_id: str = "",
        policy_revision: str = "",
        capability_ids: Sequence[str] = (),
        code_epoch: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> "FormalObligation":
        """Lift a security-rules :class:`ProofObligation` into formalization."""

        if not isinstance(obligation, ProofObligation):
            raise FormalizationError("obligation must be a ProofObligation")
        kind = (
            ObligationPayloadKind.EMPTY
            if payload_kind is None
            else _enum(ObligationPayloadKind, payload_kind, "payload_kind")
        )
        return cls(
            obligation_id=obligation.obligation_id,
            category=obligation.category,
            statement=obligation.statement,
            formal_target=obligation.formal_target,
            formal_target_kind=obligation.formal_target_kind,
            model_digest=model_digest,
            required_fact_ids=obligation.required_fact_ids,
            required_semantic_dimensions=obligation.required_semantic_dimensions,
            payload=payload if payload != "" else obligation.formal_target,
            payload_kind=kind,
            trusted_assumption_ids=obligation.trusted_assumption_ids,
            policy_id=policy_id,
            policy_revision=policy_revision,
            capability_ids=tuple(capability_ids),
            code_epoch=code_epoch,
            violation_witness=obligation.violation_witness,
            summary=obligation.summary,
            attributes=attributes or dict(obligation.attributes),
        )

    @property
    def requested_logic_family(self) -> LogicFamily:
        return logic_family_for_formal_target(self.formal_target_kind)

    @property
    def is_opaque(self) -> bool:
        return self.payload_kind in NON_EXECUTABLE_PAYLOAD_KINDS

    @property
    def may_submit_to_backend(self) -> bool:
        return is_executable_payload(self.payload_kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "capability_ids": list(self.capability_ids),
            "category": (
                self.category.value
                if isinstance(self.category, ObligationCategory)
                else self.category
            ),
            "code_epoch": self.code_epoch,
            "formal_target": self.formal_target,
            "formal_target_kind": (
                self.formal_target_kind.value
                if isinstance(self.formal_target_kind, FormalTargetKind)
                else self.formal_target_kind
            ),
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "payload": thaw_json(self.payload)
            if not isinstance(self.payload, str)
            else self.payload,
            "payload_kind": (
                self.payload_kind.value
                if isinstance(self.payload_kind, ObligationPayloadKind)
                else self.payload_kind
            ),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "required_fact_ids": list(self.required_fact_ids),
            "required_semantic_dimensions": list(self.required_semantic_dimensions),
            "schema_version": self.schema_version,
            "statement": self.statement,
            "summary": self.summary,
            "trusted_assumption_ids": list(self.trusted_assumption_ids),
            "violation_witness": (
                self.violation_witness.to_dict()
                if self.violation_witness is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalObligation":
        value = _as_mapping(value, "FormalObligation")
        _known_fields(
            value,
            frozenset(
                {
                    "obligation_id",
                    "category",
                    "statement",
                    "formal_target",
                    "formal_target_kind",
                    "model_digest",
                    "required_fact_ids",
                    "required_semantic_dimensions",
                    "payload",
                    "payload_kind",
                    "trusted_assumption_ids",
                    "policy_id",
                    "policy_revision",
                    "capability_ids",
                    "code_epoch",
                    "violation_witness",
                    "summary",
                    "attributes",
                    "schema_version",
                }
            ),
            "FormalObligation",
        )
        return cls(
            obligation_id=value.get("obligation_id", ""),
            category=value.get("category", ObligationCategory.AUTHORIZATION),
            statement=value.get("statement", ""),
            formal_target=value.get("formal_target", ""),
            formal_target_kind=value.get(
                "formal_target_kind", FormalTargetKind.DETERMINISTIC
            ),
            model_digest=value.get("model_digest", ""),
            required_fact_ids=tuple(value.get("required_fact_ids", ())),
            required_semantic_dimensions=tuple(
                value.get("required_semantic_dimensions", ())
            ),
            payload=value.get("payload", ""),
            payload_kind=value.get("payload_kind", ObligationPayloadKind.EMPTY),
            trusted_assumption_ids=tuple(value.get("trusted_assumption_ids", ())),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            capability_ids=tuple(value.get("capability_ids", ())),
            code_epoch=value.get("code_epoch", ""),
            violation_witness=value.get("violation_witness"),
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", FORMAL_OBLIGATION_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_FORMALIZATION_DOMAIN}.obligation",
        )


__all__ = [
    "CRYPTO_IR_FORMALIZATION_DOMAIN",
    "CRYPTO_IR_FORMALIZATION_SCHEMA_VERSION",
    "FORMAL_OBLIGATION_SCHEMA_VERSION",
    "NON_EXECUTABLE_LOGIC_FAMILIES",
    "NON_EXECUTABLE_PAYLOAD_KINDS",
    "OPAQUE_SECURITY_VERIFICATION_CONDITION",
    "FormalObligation",
    "FormalizationError",
    "LogicFamily",
    "ObligationPayloadKind",
    "detect_payload_kind",
    "is_executable_payload",
    "logic_family_for_formal_target",
]
