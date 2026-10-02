"""Content-addressed, fail-closed receipts for cross-logic translation.

``LogicTranslationReceipt@1`` binds the concrete source and target artifacts,
logic-family revisions, compiler chain, assumptions, bounds, unsupported
constructs, preservation claim, witnesses, semantic mutations, and evidence
authority ceiling.  A receipt is descriptive evidence: it does not itself
prove the translated property.

Consumers must validate a receipt against a
:class:`TranslationReceiptExpectation` at the point of use.  Missing receipts
and mismatches are represented with an effective authority of ``none``;
:func:`require_current_translation_receipt` turns either case into an
exception for authority-bearing paths.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity

from .translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    SemanticMutation,
    TranslationBound,
    TranslationValidationError,
    TranslationWitness,
    UnsupportedConstruct,
    UnsupportedHandling,
    authority_at_most,
)

LOGIC_TRANSLATION_RECEIPT_INTERFACE: Final = "LogicTranslationReceipt@1"
LOGIC_TRANSLATION_RECEIPT_SCHEMA_VERSION: Final = "logic-translation-receipt/v1"
LOGIC_TRANSLATION_RECEIPT_IDENTITY_DOMAIN: Final = "logic.translation.receipt"
TRANSLATION_RECEIPT_VALIDATION_SCHEMA_VERSION: Final = "logic-translation-receipt-validation/v1"


class TranslationReceiptError(TranslationValidationError):
    """Base error for a missing, stale, or malformed translation receipt."""


class MissingTranslationReceiptError(TranslationReceiptError):
    """Raised when an authority-bearing path has no translation receipt."""


class StaleTranslationReceiptError(TranslationReceiptError):
    """Raised when a receipt does not match the current translation inputs."""


class ReceiptIssueCode(StrEnum):
    """Stable reasons a receipt cannot carry authority."""

    MISSING_RECEIPT = "missing_receipt"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    TARGET_IDENTITY_MISMATCH = "target_identity_mismatch"
    SOURCE_FAMILY_MISMATCH = "source_family_mismatch"
    SOURCE_FAMILY_VERSION_MISMATCH = "source_family_version_mismatch"
    TARGET_FAMILY_MISMATCH = "target_family_mismatch"
    TARGET_FAMILY_VERSION_MISMATCH = "target_family_version_mismatch"
    COMPILER_CHAIN_MISMATCH = "compiler_chain_mismatch"
    ASSUMPTION_MISMATCH = "assumption_mismatch"
    BOUND_MISMATCH = "bound_mismatch"


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        qualifier = "an empty or " if optional else "a "
        raise TranslationReceiptError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _version(value: object, label: str) -> str:
    result = _text(value, label)
    if any(character.isspace() for character in result):
        raise TranslationReceiptError(f"{label} must not contain whitespace")
    return result


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise TranslationReceiptError(f"{label} must be one of {choices}") from error


def _strings(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationReceiptError(f"{label} must be a sequence of strings")
    result = tuple(_text(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise TranslationReceiptError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _records(
    values: Sequence[Any] | object,
    record_type: type[Any],
    label: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationReceiptError(f"{label} must be a sequence")
    result: list[Any] = []
    for item in values:
        if isinstance(item, record_type):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(record_type.from_dict(item))
        else:
            raise TranslationReceiptError(f"{label} items must be {record_type.__name__} values")
    return tuple(result)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationReceiptError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise TranslationReceiptError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TranslationReceiptError(f"unknown {label} field(s): {', '.join(unknown)}")


def _unique_by(values: Sequence[Any], attribute: str, label: str) -> tuple[Any, ...]:
    identities = [getattr(item, attribute) for item in values]
    if len(identities) != len(set(identities)):
        raise TranslationReceiptError(f"{label} must not contain duplicates")
    return tuple(sorted(values, key=lambda item: getattr(item, attribute)))


def _compiler_ids(values: Sequence[CompilerBinding]) -> tuple[str, ...]:
    # Chain order is semantically relevant, so retain it.
    return tuple(item.binding_id for item in values)


def _bound_payloads(values: Sequence[TranslationBound]) -> tuple[bytes, ...]:
    return tuple(canonical_json_bytes(item.to_dict()) for item in values)


@dataclass(frozen=True, slots=True)
class LogicTranslationReceipt:
    """One immutable, content-addressed cross-logic translation receipt."""

    source_identity: str
    target_identity: str
    source_family_id: str
    source_family_version: str
    target_family_id: str
    target_family_version: str
    compilers: tuple[CompilerBinding, ...]
    preservation_claim: PreservationClaim
    authority_ceiling: EvidenceAuthority
    assumptions: tuple[str, ...] = ()
    bounds: tuple[TranslationBound, ...] = ()
    unsupported_constructs: tuple[UnsupportedConstruct, ...] = ()
    witnesses: tuple[TranslationWitness, ...] = ()
    semantic_mutations: tuple[SemanticMutation, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    receipt_id: str = ""
    schema_version: str = LOGIC_TRANSLATION_RECEIPT_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = LOGIC_TRANSLATION_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        for name in ("source_identity", "target_identity"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_identity == self.target_identity:
            raise TranslationReceiptError("source_identity and target_identity must differ")
        for name in ("source_family_id", "target_family_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("source_family_version", "target_family_version"):
            object.__setattr__(self, name, _version(getattr(self, name), name))
        if self.source_family_id == self.target_family_id:
            raise TranslationReceiptError("cross-logic translation must change logic family")

        compilers = _records(self.compilers, CompilerBinding, "compilers")
        if not compilers:
            raise TranslationReceiptError(
                "translation receipts require at least one pinned compiler"
            )
        compiler_ids = _compiler_ids(compilers)
        if len(compiler_ids) != len(set(compiler_ids)):
            raise TranslationReceiptError("compilers must not contain duplicates")
        object.__setattr__(self, "compilers", compilers)

        claim = self.preservation_claim
        if isinstance(claim, Mapping):
            claim = PreservationClaim.from_dict(claim)
        if not isinstance(claim, PreservationClaim):
            raise TranslationReceiptError("preservation_claim must be a PreservationClaim")
        object.__setattr__(self, "preservation_claim", claim)
        authority = _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling")
        object.__setattr__(self, "authority_ceiling", authority)
        if not claim.permits_authority(authority):
            raise TranslationReceiptError(
                f"{claim.kind.value} preservation cannot carry {authority.value} authority"
            )

        object.__setattr__(self, "assumptions", _strings(self.assumptions, "assumptions"))
        bounds = _unique_by(
            _records(self.bounds, TranslationBound, "bounds"),
            "bound_id",
            "bounds",
        )
        unsupported = _unique_by(
            _records(
                self.unsupported_constructs,
                UnsupportedConstruct,
                "unsupported_constructs",
            ),
            "construct_id",
            "unsupported_constructs",
        )
        witnesses = _unique_by(
            _records(self.witnesses, TranslationWitness, "witnesses"),
            "witness_id",
            "witnesses",
        )
        mutations = _unique_by(
            _records(
                self.semantic_mutations,
                SemanticMutation,
                "semantic_mutations",
            ),
            "mutation_id",
            "semantic_mutations",
        )
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(self, "unsupported_constructs", unsupported)
        object.__setattr__(self, "witnesses", witnesses)
        object.__setattr__(self, "semantic_mutations", mutations)
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))

        if self.schema_version != LOGIC_TRANSLATION_RECEIPT_SCHEMA_VERSION:
            raise TranslationReceiptError(
                f"unsupported translation receipt schema {self.schema_version!r}"
            )
        self._validate_semantics()
        computed = self._compute_identity()
        if self.receipt_id and self.receipt_id != computed.cid:
            raise TranslationReceiptError("receipt_id does not match canonical receipt content")
        object.__setattr__(self, "receipt_id", computed.cid)

    def _validate_semantics(self) -> None:
        claim = self.preservation_claim
        if claim.kind is PreservationKind.EXACT:
            if self.bounds:
                raise TranslationReceiptError("exact translations cannot introduce semantic bounds")
            if self.unsupported_constructs:
                raise TranslationReceiptError(
                    "exact translations cannot contain unsupported constructs"
                )
            if self.semantic_mutations:
                raise TranslationReceiptError(
                    "exact translations cannot contain semantic mutations"
                )
        if claim.kind is PreservationKind.BOUNDED and not self.bounds:
            raise TranslationReceiptError(
                "bounded translations require at least one explicit bound"
            )
        if self.bounds and claim.kind not in {
            PreservationKind.BOUNDED,
            PreservationKind.APPROXIMATE,
            PreservationKind.HEURISTIC,
            PreservationKind.CONSERVATIVE,
        }:
            raise TranslationReceiptError(
                f"{claim.kind.value} translations cannot introduce bounds"
            )

        known_assumptions = set(self.assumptions)
        known_bounds = {item.bound_id for item in self.bounds}
        for mutation in self.semantic_mutations:
            missing_assumptions = sorted(set(mutation.assumption_ids) - known_assumptions)
            if missing_assumptions:
                raise TranslationReceiptError(
                    f"mutation {mutation.mutation_id} references unknown "
                    f"assumptions {missing_assumptions}"
                )
            missing_bounds = sorted(set(mutation.bound_ids) - known_bounds)
            if missing_bounds:
                raise TranslationReceiptError(
                    f"mutation {mutation.mutation_id} references unknown bounds {missing_bounds}"
                )

        # A rejected/omitted construct means there is no semantics-bearing
        # translation for the complete source.  Approximation/abstraction is
        # allowed only at an advisory ceiling.
        incomplete = any(
            item.handling in {UnsupportedHandling.REJECTED, UnsupportedHandling.OMITTED}
            for item in self.unsupported_constructs
        )
        approximated = bool(self.unsupported_constructs)
        if incomplete and self.authority_ceiling is not EvidenceAuthority.NONE:
            raise TranslationReceiptError(
                "rejected or omitted constructs require authority_ceiling=none"
            )
        if approximated and not authority_at_most(
            self.authority_ceiling, EvidenceAuthority.ADVISORY
        ):
            raise TranslationReceiptError(
                "unsupported constructs cap translation authority at advisory"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.receipt_id

    @property
    def translation_id(self) -> str:
        """Compatibility alias for callers that index translations."""

        return self.receipt_id

    @property
    def source_family(self) -> str:
        return self.source_family_id

    @property
    def target_family(self) -> str:
        return self.target_family_id

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=LOGIC_TRANSLATION_RECEIPT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Return the complete canonical identity preimage."""

        return {
            "assumptions": list(self.assumptions),
            "authority_ceiling": self.authority_ceiling.value,
            "bounds": [item.to_dict() for item in self.bounds],
            "compilers": [item.to_dict() for item in self.compilers],
            "interface": self.INTERFACE,
            "metadata": self.metadata.to_dict(),
            "preservation_claim": self.preservation_claim.to_dict(),
            "schema_version": self.schema_version,
            "semantic_mutations": [item.to_dict() for item in self.semantic_mutations],
            "source_family_id": self.source_family_id,
            "source_family_version": self.source_family_version,
            "source_identity": self.source_identity,
            "target_family_id": self.target_family_id,
            "target_family_version": self.target_family_version,
            "target_identity": self.target_identity,
            "unsupported_constructs": [item.to_dict() for item in self.unsupported_constructs],
            "witnesses": [item.to_dict() for item in self.witnesses],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["receipt_id"] = self.receipt_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    def validate_current(
        self, expectation: TranslationReceiptExpectation
    ) -> TranslationReceiptValidation:
        return validate_translation_receipt(self, expectation)

    def require_current(
        self, expectation: TranslationReceiptExpectation
    ) -> LogicTranslationReceipt:
        return require_current_translation_receipt(self, expectation)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicTranslationReceipt:
        value = _mapping(value, "translation receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "authority_ceiling",
                    "bounds",
                    "compilers",
                    "interface",
                    "metadata",
                    "preservation_claim",
                    "receipt_id",
                    "schema_version",
                    "semantic_mutations",
                    "source_family_id",
                    "source_family_version",
                    "source_identity",
                    "target_family_id",
                    "target_family_version",
                    "target_identity",
                    "unsupported_constructs",
                    "witnesses",
                }
            ),
            "translation receipt",
        )
        interface = value.get("interface", LOGIC_TRANSLATION_RECEIPT_INTERFACE)
        if interface != LOGIC_TRANSLATION_RECEIPT_INTERFACE:
            raise TranslationReceiptError(
                f"unsupported translation receipt interface {interface!r}"
            )
        return cls(
            source_identity=value.get("source_identity", ""),
            target_identity=value.get("target_identity", ""),
            source_family_id=value.get("source_family_id", ""),
            source_family_version=value.get("source_family_version", ""),
            target_family_id=value.get("target_family_id", ""),
            target_family_version=value.get("target_family_version", ""),
            compilers=tuple(value.get("compilers", ())),
            preservation_claim=value.get("preservation_claim", {}),  # type: ignore[arg-type]
            authority_ceiling=value.get("authority_ceiling", EvidenceAuthority.NONE.value),
            assumptions=tuple(value.get("assumptions", ())),
            bounds=tuple(value.get("bounds", ())),
            unsupported_constructs=tuple(value.get("unsupported_constructs", ())),
            witnesses=tuple(value.get("witnesses", ())),
            semantic_mutations=tuple(value.get("semantic_mutations", ())),
            metadata=_frozen(value.get("metadata", {}), "metadata"),
            receipt_id=value.get("receipt_id", ""),
            schema_version=value.get("schema_version", LOGIC_TRANSLATION_RECEIPT_SCHEMA_VERSION),
        )


# Concise compatibility alias for code that already imports TranslationReceipt.
TranslationReceipt = LogicTranslationReceipt


@dataclass(frozen=True, slots=True)
class TranslationReceiptExpectation:
    """Current semantic inputs against which a receipt must be checked."""

    source_identity: str
    target_identity: str
    source_family_id: str
    source_family_version: str
    target_family_id: str
    target_family_version: str
    compilers: tuple[CompilerBinding, ...]
    assumptions: tuple[str, ...] = ()
    bounds: tuple[TranslationBound, ...] = ()

    def __post_init__(self) -> None:
        for name in ("source_identity", "target_identity"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("source_family_id", "target_family_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("source_family_version", "target_family_version"):
            object.__setattr__(self, name, _version(getattr(self, name), name))
        compilers = _records(self.compilers, CompilerBinding, "compilers")
        if not compilers:
            raise TranslationReceiptError("receipt expectations require the current compiler chain")
        object.__setattr__(self, "compilers", compilers)
        object.__setattr__(self, "assumptions", _strings(self.assumptions, "assumptions"))
        object.__setattr__(
            self,
            "bounds",
            _unique_by(
                _records(self.bounds, TranslationBound, "bounds"),
                "bound_id",
                "bounds",
            ),
        )

    @classmethod
    def from_receipt(cls, receipt: LogicTranslationReceipt) -> TranslationReceiptExpectation:
        """Build an expectation for the receipt's currently pinned inputs."""

        if not isinstance(receipt, LogicTranslationReceipt):
            raise TranslationReceiptError("receipt must be a LogicTranslationReceipt")
        return cls(
            source_identity=receipt.source_identity,
            target_identity=receipt.target_identity,
            source_family_id=receipt.source_family_id,
            source_family_version=receipt.source_family_version,
            target_family_id=receipt.target_family_id,
            target_family_version=receipt.target_family_version,
            compilers=receipt.compilers,
            assumptions=receipt.assumptions,
            bounds=receipt.bounds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "bounds": [item.to_dict() for item in self.bounds],
            "compilers": [item.to_dict() for item in self.compilers],
            "source_family_id": self.source_family_id,
            "source_family_version": self.source_family_version,
            "source_identity": self.source_identity,
            "target_family_id": self.target_family_id,
            "target_family_version": self.target_family_version,
            "target_identity": self.target_identity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TranslationReceiptExpectation:
        value = _mapping(value, "translation receipt expectation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "bounds",
                    "compilers",
                    "source_family_id",
                    "source_family_version",
                    "source_identity",
                    "target_family_id",
                    "target_family_version",
                    "target_identity",
                }
            ),
            "translation receipt expectation",
        )
        return cls(
            source_identity=value.get("source_identity", ""),
            target_identity=value.get("target_identity", ""),
            source_family_id=value.get("source_family_id", ""),
            source_family_version=value.get("source_family_version", ""),
            target_family_id=value.get("target_family_id", ""),
            target_family_version=value.get("target_family_version", ""),
            compilers=tuple(value.get("compilers", ())),
            assumptions=tuple(value.get("assumptions", ())),
            bounds=tuple(value.get("bounds", ())),
        )


@dataclass(frozen=True, slots=True)
class ReceiptIssue:
    """One stable receipt validation failure."""

    code: ReceiptIssueCode
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _enum(self.code, ReceiptIssueCode, "code"))
        object.__setattr__(self, "detail", _text(self.detail, "detail"))

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReceiptIssue:
        value = _mapping(value, "receipt issue")
        _reject_unknown(value, frozenset({"code", "detail"}), "receipt issue")
        return cls(code=value.get("code", ""), detail=value.get("detail", ""))


@dataclass(frozen=True, slots=True)
class TranslationReceiptValidation:
    """Fail-closed current-revision decision for one receipt."""

    receipt_id: str
    current: bool
    issues: tuple[ReceiptIssue, ...]
    effective_authority_ceiling: EvidenceAuthority
    schema_version: str = TRANSLATION_RECEIPT_VALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id", optional=True))
        if not isinstance(self.current, bool):
            raise TranslationReceiptError("current must be a bool")
        issues = _records(self.issues, ReceiptIssue, "issues")
        object.__setattr__(self, "issues", issues)
        if self.current != (not issues):
            raise TranslationReceiptError("current must be true exactly when issues are empty")
        ceiling = _enum(
            self.effective_authority_ceiling,
            EvidenceAuthority,
            "effective_authority_ceiling",
        )
        object.__setattr__(self, "effective_authority_ceiling", ceiling)
        if issues and ceiling is not EvidenceAuthority.NONE:
            raise TranslationReceiptError("invalid receipts must have effective authority none")
        if self.schema_version != TRANSLATION_RECEIPT_VALIDATION_SCHEMA_VERSION:
            raise TranslationReceiptError(
                f"unsupported receipt validation schema {self.schema_version!r}"
            )

    @property
    def valid(self) -> bool:
        return self.current

    @property
    def stale(self) -> bool:
        return bool(self.receipt_id) and not self.current

    @property
    def promotion_allowed(self) -> bool:
        return self.current and self.effective_authority_ceiling is not EvidenceAuthority.NONE

    def permits(self, authority: EvidenceAuthority | str) -> bool:
        return self.current and authority_at_most(authority, self.effective_authority_ceiling)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "effective_authority_ceiling": self.effective_authority_ceiling.value,
            "issues": [item.to_dict() for item in self.issues],
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TranslationReceiptValidation:
        value = _mapping(value, "translation receipt validation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "current",
                    "effective_authority_ceiling",
                    "issues",
                    "receipt_id",
                    "schema_version",
                }
            ),
            "translation receipt validation",
        )
        return cls(
            receipt_id=value.get("receipt_id", ""),
            current=value.get("current", False),
            issues=tuple(value.get("issues", ())),
            effective_authority_ceiling=value.get(
                "effective_authority_ceiling", EvidenceAuthority.NONE.value
            ),
            schema_version=value.get(
                "schema_version", TRANSLATION_RECEIPT_VALIDATION_SCHEMA_VERSION
            ),
        )


def validate_translation_receipt(
    receipt: LogicTranslationReceipt | None,
    expectation: TranslationReceiptExpectation,
) -> TranslationReceiptValidation:
    """Validate a receipt against all current semantic inputs.

    This function never treats absence or staleness as success.  It returns a
    typed result with effective authority ``none`` so diagnostic/reporting
    callers can retain the failure evidence without catching an exception.
    """

    if not isinstance(expectation, TranslationReceiptExpectation):
        raise TranslationReceiptError("expectation must be a TranslationReceiptExpectation")
    if receipt is None:
        return TranslationReceiptValidation(
            receipt_id="",
            current=False,
            issues=(
                ReceiptIssue(
                    ReceiptIssueCode.MISSING_RECEIPT,
                    "translation receipt is required",
                ),
            ),
            effective_authority_ceiling=EvidenceAuthority.NONE,
        )
    if not isinstance(receipt, LogicTranslationReceipt):
        raise TranslationReceiptError("receipt must be a LogicTranslationReceipt or None")

    issues: list[ReceiptIssue] = []

    def compare(
        actual: object,
        expected: object,
        code: ReceiptIssueCode,
        label: str,
    ) -> None:
        if actual != expected:
            issues.append(ReceiptIssue(code, f"receipt {label} does not match current input"))

    compare(
        receipt.source_identity,
        expectation.source_identity,
        ReceiptIssueCode.SOURCE_IDENTITY_MISMATCH,
        "source identity",
    )
    compare(
        receipt.target_identity,
        expectation.target_identity,
        ReceiptIssueCode.TARGET_IDENTITY_MISMATCH,
        "target identity",
    )
    compare(
        receipt.source_family_id,
        expectation.source_family_id,
        ReceiptIssueCode.SOURCE_FAMILY_MISMATCH,
        "source family",
    )
    compare(
        receipt.source_family_version,
        expectation.source_family_version,
        ReceiptIssueCode.SOURCE_FAMILY_VERSION_MISMATCH,
        "source family version",
    )
    compare(
        receipt.target_family_id,
        expectation.target_family_id,
        ReceiptIssueCode.TARGET_FAMILY_MISMATCH,
        "target family",
    )
    compare(
        receipt.target_family_version,
        expectation.target_family_version,
        ReceiptIssueCode.TARGET_FAMILY_VERSION_MISMATCH,
        "target family version",
    )
    compare(
        _compiler_ids(receipt.compilers),
        _compiler_ids(expectation.compilers),
        ReceiptIssueCode.COMPILER_CHAIN_MISMATCH,
        "compiler chain",
    )
    compare(
        receipt.assumptions,
        expectation.assumptions,
        ReceiptIssueCode.ASSUMPTION_MISMATCH,
        "assumptions",
    )
    compare(
        _bound_payloads(receipt.bounds),
        _bound_payloads(expectation.bounds),
        ReceiptIssueCode.BOUND_MISMATCH,
        "bounds",
    )

    return TranslationReceiptValidation(
        receipt_id=receipt.receipt_id,
        current=not issues,
        issues=tuple(issues),
        effective_authority_ceiling=(
            receipt.authority_ceiling if not issues else EvidenceAuthority.NONE
        ),
    )


def require_current_translation_receipt(
    receipt: LogicTranslationReceipt | None,
    expectation: TranslationReceiptExpectation,
) -> LogicTranslationReceipt:
    """Return a current receipt, raising for absence or any stale binding."""

    validation = validate_translation_receipt(receipt, expectation)
    if receipt is None:
        raise MissingTranslationReceiptError("translation receipt is required")
    if not validation.current:
        codes = ", ".join(issue.code.value for issue in validation.issues)
        raise StaleTranslationReceiptError(f"translation receipt is stale: {codes}")
    return receipt


__all__ = [
    "LOGIC_TRANSLATION_RECEIPT_INTERFACE",
    "LOGIC_TRANSLATION_RECEIPT_SCHEMA_VERSION",
    "LogicTranslationReceipt",
    "MissingTranslationReceiptError",
    "ReceiptIssue",
    "ReceiptIssueCode",
    "StaleTranslationReceiptError",
    "TranslationReceipt",
    "TranslationReceiptError",
    "TranslationReceiptExpectation",
    "TranslationReceiptValidation",
    "require_current_translation_receipt",
    "validate_translation_receipt",
]
