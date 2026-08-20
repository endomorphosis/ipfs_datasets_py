"""Claim extraction and mutation-target selection (AAE-021).

Interface surface:

* ``identify_asserted_properties`` — extract closed property claims bound to
  symbols and/or artifact CIDs.
* ``select_mutation_targets`` — risk-weight and boundedly sample
  ``MutationTarget@1`` records from asserted properties.

Selection always binds claims to symbols/artifacts (fail-closed when unbound)
and prioritizes security, durability, distributed/proof trust, fan-out, recent
change, uncertainty, defects, frequency, and failure cost under an explicit
``SamplingBudget``.

This module is pure and deterministic. It does not open a store, mutate
worktrees, or change production policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import blake2b
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_CID_LIST,
    MAX_ID_LIST,
    MAX_PATH_CHARS,
    MAX_PREREQUISITES,
    MAX_PROPERTY_CLASSES,
    MAX_TARGETS,
    MAX_TEXT_CHARS,
    MAX_TOKEN_LIST,
    MutationRiskClass,
    MutationTarget,
    PropertyClass,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.risk import (
    RiskCandidate,
    RiskScore,
    RiskSignals,
    SamplingBudget,
    TargetRiskError,
    highest_risk_class,
    rank_mutation_risk,
    risk_class_for_property_class,
    selected_risk_scores,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

IDENTIFY_ASSERTED_PROPERTIES_INTERFACE: Final[str] = "identify_asserted_properties@1"
SELECT_MUTATION_TARGETS_INTERFACE: Final[str] = "select_mutation_targets@1"
ASSERTED_PROPERTY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-asserted-property@1"
)
CLAIM_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-claim-record@1"
)
TARGET_SELECTION_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-target-selection@1"
)

MAX_CLAIMS: Final[int] = 4_096
MAX_STATEMENT_CHARS: Final[int] = MAX_TEXT_CHARS

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)


class TargetSelectionError(AssuranceBaseError):
    """Raised when claim extraction or target selection fails closed."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise TargetSelectionError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise TargetSelectionError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise TargetSelectionError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise TargetSelectionError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise TargetSelectionError(f"{name} must be a valid CID") from exc


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise TargetSelectionError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise TargetSelectionError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise TargetSelectionError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _optional_repo_path(value: Any, name: str) -> str | None:
    if value is None:
        return None
    text = _text(value, name)
    if len(text) > MAX_PATH_CHARS:
        raise TargetSelectionError(f"{name} exceeds maximum path length")
    if text.startswith("/") or text.startswith("\\"):
        raise TargetSelectionError(f"{name} rejects absolute paths")
    if ".." in text.split("/"):
        raise TargetSelectionError(f"{name} rejects parent-directory traversal")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise TargetSelectionError(f"{name} must be a relative repository path")
    return text


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TargetSelectionError(f"{name} must be a boolean")
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise TargetSelectionError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise TargetSelectionError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TargetSelectionError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TargetSelectionError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise TargetSelectionError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_symbol_ids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise TargetSelectionError(f"{name} must be a list")
    ordered = tuple(sorted(_symbol_id(value, name) for value in values))
    if len(ordered) > MAX_ID_LIST:
        raise TargetSelectionError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise TargetSelectionError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise TargetSelectionError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise TargetSelectionError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise TargetSelectionError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise TargetSelectionError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > maximum:
        raise TargetSelectionError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise TargetSelectionError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_property_classes(
    values: Iterable[Any], name: str
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise TargetSelectionError(f"{name} must be a list")
    ordered = tuple(
        sorted(_enum(value, PropertyClass, name) for value in values)
    )
    if len(ordered) > MAX_PROPERTY_CLASSES:
        raise TargetSelectionError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise TargetSelectionError(f"{name} must not contain duplicates")
    if not ordered:
        raise TargetSelectionError(f"{name} must not be empty")
    return ordered


# ---------------------------------------------------------------------------
# Claim / asserted-property records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """Input claim declaring properties over symbols and/or artifacts.

    At least one of ``symbol_ids`` or ``artifact_cids`` is required. Property
    classes must be drawn from the closed ``PropertyClass`` vocabulary.
    """

    claim_id: str
    property_classes: Sequence[PropertyClass | str]
    statement: str
    symbol_ids: Sequence[str] = ()
    artifact_cids: Sequence[str] = ()
    source_path: str | None = None
    language: str = "python"
    artifact_type: str = "source_module"
    prerequisites: Sequence[str] = ()
    capsule_cids: Sequence[str] = ()
    proof_unit_cids: Sequence[str] = ()
    risk_class: MutationRiskClass | str | None = None
    signals: RiskSignals | Mapping[str, Any] | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "claim_id",
            "property_classes",
            "statement",
            "symbol_ids",
            "artifact_cids",
            "source_path",
            "language",
            "artifact_type",
            "prerequisites",
            "capsule_cids",
            "proof_unit_cids",
            "risk_class",
            "signals",
            "notes",
            "metadata",
            "claim_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _token(self.claim_id, "claim_id"))
        object.__setattr__(
            self,
            "property_classes",
            _unique_sorted_property_classes(
                list(self.property_classes), "property_classes"
            ),
        )
        statement = _text(self.statement, "statement")
        if len(statement) > MAX_STATEMENT_CHARS:
            raise TargetSelectionError("statement exceeds maximum length")
        object.__setattr__(self, "statement", statement)
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        artifacts = _unique_sorted_cids(list(self.artifact_cids), "artifact_cids")
        if not symbols and not artifacts:
            raise TargetSelectionError(
                "ClaimRecord requires at least one symbol_id or artifact_cid"
            )
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(self, "artifact_cids", artifacts)
        object.__setattr__(
            self, "source_path", _optional_repo_path(self.source_path, "source_path")
        )
        object.__setattr__(self, "language", _token(self.language, "language"))
        object.__setattr__(
            self, "artifact_type", _token(self.artifact_type, "artifact_type")
        )
        object.__setattr__(
            self,
            "prerequisites",
            _unique_sorted_tokens(
                list(self.prerequisites),
                "prerequisites",
                maximum=MAX_PREREQUISITES,
            ),
        )
        object.__setattr__(
            self,
            "capsule_cids",
            _unique_sorted_cids(list(self.capsule_cids), "capsule_cids"),
        )
        object.__setattr__(
            self,
            "proof_unit_cids",
            _unique_sorted_cids(list(self.proof_unit_cids), "proof_unit_cids"),
        )
        if self.risk_class is None:
            inferred = highest_risk_class(
                risk_class_for_property_class(item)
                for item in self.property_classes
            )
            object.__setattr__(self, "risk_class", inferred)
        else:
            declared = _enum(self.risk_class, MutationRiskClass, "risk_class")
            inferred = highest_risk_class(
                risk_class_for_property_class(item)
                for item in self.property_classes
            )
            object.__setattr__(
                self, "risk_class", highest_risk_class((declared, inferred))
            )
        try:
            object.__setattr__(
                self, "signals", RiskSignals.normalize(self.signals)
            )
        except TargetRiskError as exc:
            raise TargetSelectionError(str(exc)) from exc
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CLAIM_RECORD_SCHEMA,
            "claim_id": self.claim_id,
            "property_classes": list(self.property_classes),
            "statement": self.statement,
            "symbol_ids": list(self.symbol_ids),
            "artifact_cids": list(self.artifact_cids),
            "source_path": self.source_path,
            "language": self.language,
            "artifact_type": self.artifact_type,
            "prerequisites": list(self.prerequisites),
            "capsule_cids": list(self.capsule_cids),
            "proof_unit_cids": list(self.proof_unit_cids),
            "risk_class": self.risk_class,
            "signals": self.signals.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def claim_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["signals"] = self.signals.to_dict()
        payload["claim_cid"] = self.claim_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClaimRecord":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("claim_cid")
        if payload.pop("schema") != CLAIM_RECORD_SCHEMA:
            raise TargetSelectionError("unsupported ClaimRecord schema version")
        result = cls(
            claim_id=payload["claim_id"],
            property_classes=payload["property_classes"],
            statement=payload["statement"],
            symbol_ids=payload["symbol_ids"],
            artifact_cids=payload["artifact_cids"],
            source_path=payload["source_path"],
            language=payload["language"],
            artifact_type=payload["artifact_type"],
            prerequisites=payload["prerequisites"],
            capsule_cids=payload["capsule_cids"],
            proof_unit_cids=payload["proof_unit_cids"],
            risk_class=payload["risk_class"],
            signals=payload["signals"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.claim_cid:
            raise TargetSelectionError("ClaimRecord claim_cid identity mismatch")
        return result

    @classmethod
    def normalize(cls, value: "ClaimRecord | Mapping[str, Any]") -> "ClaimRecord":
        if isinstance(value, ClaimRecord):
            return value
        if not isinstance(value, Mapping):
            raise TargetSelectionError("claim must be ClaimRecord or a mapping")
        if "schema" in value or "claim_cid" in value:
            return cls.from_dict(value)
        required = {"claim_id", "property_classes", "statement"}
        missing = required - set(value)
        if missing:
            raise TargetSelectionError(
                f"ClaimRecord missing required fields: {', '.join(sorted(missing))}"
            )
        allowed = {
            "claim_id",
            "property_classes",
            "statement",
            "symbol_ids",
            "artifact_cids",
            "source_path",
            "language",
            "artifact_type",
            "prerequisites",
            "capsule_cids",
            "proof_unit_cids",
            "risk_class",
            "signals",
            "notes",
            "metadata",
        }
        unknown = set(value) - allowed
        if unknown:
            raise TargetSelectionError(
                f"ClaimRecord contains unknown fields: {', '.join(sorted(unknown))}"
            )
        return cls(
            claim_id=value["claim_id"],
            property_classes=value["property_classes"],
            statement=value["statement"],
            symbol_ids=value.get("symbol_ids", ()),
            artifact_cids=value.get("artifact_cids", ()),
            source_path=value.get("source_path"),
            language=value.get("language", "python"),
            artifact_type=value.get("artifact_type", "source_module"),
            prerequisites=value.get("prerequisites", ()),
            capsule_cids=value.get("capsule_cids", ()),
            proof_unit_cids=value.get("proof_unit_cids", ()),
            risk_class=value.get("risk_class"),
            signals=value.get("signals"),
            notes=value.get("notes"),
            metadata=value.get("metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class AssertedProperty:
    """One asserted property extracted from a claim, bound to symbols/artifacts."""

    property_id: str
    claim_id: str
    property_class: PropertyClass | str
    statement: str
    symbol_ids: Sequence[str]
    artifact_cids: Sequence[str]
    risk_class: MutationRiskClass | str
    source_path: str | None = None
    language: str = "python"
    artifact_type: str = "source_module"
    prerequisites: Sequence[str] = ()
    capsule_cids: Sequence[str] = ()
    proof_unit_cids: Sequence[str] = ()
    signals: RiskSignals | Mapping[str, Any] | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "property_id",
            "claim_id",
            "property_class",
            "statement",
            "symbol_ids",
            "artifact_cids",
            "risk_class",
            "source_path",
            "language",
            "artifact_type",
            "prerequisites",
            "capsule_cids",
            "proof_unit_cids",
            "signals",
            "notes",
            "metadata",
            "property_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "property_id", _token(self.property_id, "property_id")
        )
        object.__setattr__(self, "claim_id", _token(self.claim_id, "claim_id"))
        object.__setattr__(
            self,
            "property_class",
            _enum(self.property_class, PropertyClass, "property_class"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        artifacts = _unique_sorted_cids(list(self.artifact_cids), "artifact_cids")
        if not symbols and not artifacts:
            raise TargetSelectionError(
                "AssertedProperty requires at least one symbol_id or artifact_cid"
            )
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(self, "artifact_cids", artifacts)
        declared = _enum(self.risk_class, MutationRiskClass, "risk_class")
        inferred = risk_class_for_property_class(self.property_class)
        object.__setattr__(
            self, "risk_class", highest_risk_class((declared, inferred))
        )
        object.__setattr__(
            self, "source_path", _optional_repo_path(self.source_path, "source_path")
        )
        object.__setattr__(self, "language", _token(self.language, "language"))
        object.__setattr__(
            self, "artifact_type", _token(self.artifact_type, "artifact_type")
        )
        object.__setattr__(
            self,
            "prerequisites",
            _unique_sorted_tokens(
                list(self.prerequisites),
                "prerequisites",
                maximum=MAX_PREREQUISITES,
            ),
        )
        object.__setattr__(
            self,
            "capsule_cids",
            _unique_sorted_cids(list(self.capsule_cids), "capsule_cids"),
        )
        object.__setattr__(
            self,
            "proof_unit_cids",
            _unique_sorted_cids(list(self.proof_unit_cids), "proof_unit_cids"),
        )
        try:
            object.__setattr__(
                self, "signals", RiskSignals.normalize(self.signals)
            )
        except TargetRiskError as exc:
            raise TargetSelectionError(str(exc)) from exc
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ASSERTED_PROPERTY_SCHEMA,
            "interface_id": IDENTIFY_ASSERTED_PROPERTIES_INTERFACE,
            "property_id": self.property_id,
            "claim_id": self.claim_id,
            "property_class": self.property_class,
            "statement": self.statement,
            "symbol_ids": list(self.symbol_ids),
            "artifact_cids": list(self.artifact_cids),
            "risk_class": self.risk_class,
            "source_path": self.source_path,
            "language": self.language,
            "artifact_type": self.artifact_type,
            "prerequisites": list(self.prerequisites),
            "capsule_cids": list(self.capsule_cids),
            "proof_unit_cids": list(self.proof_unit_cids),
            "signals": self.signals.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def property_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["signals"] = self.signals.to_dict()
        payload["property_cid"] = self.property_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssertedProperty":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("property_cid")
        if payload.pop("schema") != ASSERTED_PROPERTY_SCHEMA:
            raise TargetSelectionError(
                "unsupported AssertedProperty schema version"
            )
        if payload.pop("interface_id") != IDENTIFY_ASSERTED_PROPERTIES_INTERFACE:
            raise TargetSelectionError(
                "unsupported AssertedProperty interface_id"
            )
        result = cls(
            property_id=payload["property_id"],
            claim_id=payload["claim_id"],
            property_class=payload["property_class"],
            statement=payload["statement"],
            symbol_ids=payload["symbol_ids"],
            artifact_cids=payload["artifact_cids"],
            risk_class=payload["risk_class"],
            source_path=payload["source_path"],
            language=payload["language"],
            artifact_type=payload["artifact_type"],
            prerequisites=payload["prerequisites"],
            capsule_cids=payload["capsule_cids"],
            proof_unit_cids=payload["proof_unit_cids"],
            signals=payload["signals"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.property_cid:
            raise TargetSelectionError(
                "AssertedProperty property_cid identity mismatch"
            )
        return result

    def binding_key(self) -> tuple[Any, ...]:
        """Stable key grouping properties into one mutation target."""

        return (
            self.language,
            self.artifact_type,
            self.symbol_ids,
            self.artifact_cids,
            self.source_path,
        )


def identify_asserted_properties(
    claims: Sequence[ClaimRecord | Mapping[str, Any]],
) -> tuple[AssertedProperty, ...]:
    """Extract asserted properties from claims, binding each to symbols/artifacts.

    One claim with *n* property classes yields *n* asserted properties, each
    inheriting the claim's symbol/artifact bindings and risk signals. Claims
    without bindings, empty property classes, or duplicate claim IDs fail
    closed. Output order is deterministic: sorted by ``(claim_id, property_class)``.
    """

    if not isinstance(claims, (list, tuple)):
        raise TargetSelectionError("claims must be a sequence")
    if len(claims) > MAX_CLAIMS:
        raise TargetSelectionError("claims exceeds maximum length")

    normalized: list[ClaimRecord] = []
    seen_claim_ids: set[str] = set()
    for item in claims:
        claim = ClaimRecord.normalize(item)
        if claim.claim_id in seen_claim_ids:
            raise TargetSelectionError(
                f"duplicate claim_id {claim.claim_id!r}"
            )
        seen_claim_ids.add(claim.claim_id)
        normalized.append(claim)

    properties: list[AssertedProperty] = []
    for claim in normalized:
        for property_class in claim.property_classes:
            property_id = _stable_property_id(claim.claim_id, property_class)
            properties.append(
                AssertedProperty(
                    property_id=property_id,
                    claim_id=claim.claim_id,
                    property_class=property_class,
                    statement=claim.statement,
                    symbol_ids=claim.symbol_ids,
                    artifact_cids=claim.artifact_cids,
                    risk_class=claim.risk_class,
                    source_path=claim.source_path,
                    language=claim.language,
                    artifact_type=claim.artifact_type,
                    prerequisites=claim.prerequisites,
                    capsule_cids=claim.capsule_cids,
                    proof_unit_cids=claim.proof_unit_cids,
                    signals=claim.signals,
                    notes=claim.notes,
                    metadata={
                        **_thaw_structured(claim.metadata),
                        "claim_cid": claim.claim_cid,
                    },
                )
            )

    return tuple(
        sorted(properties, key=lambda item: (item.claim_id, item.property_class))
    )


def _stable_property_id(claim_id: str, property_class: str) -> str:
    digest = blake2b(
        f"{claim_id}\0{property_class}".encode("utf-8"), digest_size=8
    ).hexdigest()
    return f"prop_{digest}"


def _stable_target_id(binding_key: tuple[Any, ...]) -> str:
    material = "\0".join(
        [
            str(binding_key[0]),
            str(binding_key[1]),
            ",".join(binding_key[2]),
            ",".join(binding_key[3]),
            str(binding_key[4] or ""),
        ]
    )
    digest = blake2b(material.encode("utf-8"), digest_size=8).hexdigest()
    return f"tgt_{digest}"


def _merge_signals(items: Sequence[RiskSignals]) -> RiskSignals:
    if not items:
        return RiskSignals()
    return RiskSignals(
        fan_out=max(item.fan_out for item in items),
        recent_change_bp=max(item.recent_change_bp for item in items),
        uncertainty_bp=max(item.uncertainty_bp for item in items),
        defect_count=max(item.defect_count for item in items),
        frequency_bp=max(item.frequency_bp for item in items),
        failure_cost_bp=max(item.failure_cost_bp for item in items),
        missing_tests=any(item.missing_tests for item in items),
        is_formatting=all(item.is_formatting for item in items),
        is_generated_proven=all(item.is_generated_proven for item in items),
        is_immutable_dependency=all(
            item.is_immutable_dependency for item in items
        ),
        is_boilerplate=all(item.is_boilerplate for item in items),
    )


@dataclass(frozen=True, slots=True)
class TargetSelectionResult:
    """Result of risk-weighted, bounded mutation-target selection."""

    targets: tuple[MutationTarget, ...]
    ranking: tuple[RiskScore, ...]
    asserted_properties: tuple[AssertedProperty, ...]
    budget: SamplingBudget
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.targets, tuple):
            object.__setattr__(self, "targets", tuple(self.targets))
        if not isinstance(self.ranking, tuple):
            object.__setattr__(self, "ranking", tuple(self.ranking))
        if not isinstance(self.asserted_properties, tuple):
            object.__setattr__(
                self, "asserted_properties", tuple(self.asserted_properties)
            )
        if not isinstance(self.budget, SamplingBudget):
            object.__setattr__(
                self, "budget", SamplingBudget.normalize(self.budget)
            )
        if len(self.targets) > self.budget.max_targets:
            raise TargetSelectionError(
                "selected targets exceed sampling budget max_targets"
            )
        for target in self.targets:
            if not isinstance(target, MutationTarget):
                raise TargetSelectionError(
                    "targets must contain MutationTarget values"
                )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TARGET_SELECTION_RESULT_SCHEMA,
            "interface_id": SELECT_MUTATION_TARGETS_INTERFACE,
            "targets": [target.to_dict() for target in self.targets],
            "ranking": [score.to_dict() for score in self.ranking],
            "asserted_properties": [
                prop.to_dict() for prop in self.asserted_properties
            ],
            "budget": self.budget.to_dict(),
            "notes": self.notes,
            "target_count": len(self.targets),
            "candidate_count": len(self.ranking),
        }


def select_mutation_targets(
    properties: Sequence[AssertedProperty | Mapping[str, Any] | ClaimRecord],
    *,
    repository_id: str,
    repository_state_cid: str,
    budget: SamplingBudget | Mapping[str, Any] | None = None,
    default_prerequisites: Sequence[str] = ("parsed_ast", "symbol_table"),
    return_result: bool = False,
) -> tuple[MutationTarget, ...] | TargetSelectionResult:
    """Bind asserted properties into risk-ranked ``MutationTarget`` records.

    Properties that share language, artifact type, symbols, artifacts, and
    source path collapse into one target. Risk class is the highest among
    bound properties; risk weight comes from ``rank_mutation_risk`` under the
    supplied ``SamplingBudget``.

    Accepts ``AssertedProperty`` values, claim mappings (auto-extracted), or
    ``ClaimRecord`` instances. Fail-closed on unbound subjects and invalid
    repository identity fields.
    """

    repo_id = _repository_id(repository_id, "repository_id")
    state_cid = _cid(repository_state_cid, "repository_state_cid")
    try:
        budget_n = SamplingBudget.normalize(budget)
    except TargetRiskError as exc:
        raise TargetSelectionError(str(exc)) from exc

    if not isinstance(properties, (list, tuple)):
        raise TargetSelectionError("properties must be a sequence")
    if len(properties) > MAX_CLAIMS * MAX_PROPERTY_CLASSES:
        raise TargetSelectionError("properties exceeds maximum length")

    asserted: list[AssertedProperty] = []
    claim_buffer: list[ClaimRecord | Mapping[str, Any]] = []
    for item in properties:
        if isinstance(item, AssertedProperty):
            if claim_buffer:
                asserted.extend(identify_asserted_properties(claim_buffer))
                claim_buffer = []
            asserted.append(item)
        elif isinstance(item, ClaimRecord) or isinstance(item, Mapping):
            # Mapping may be ClaimRecord or AssertedProperty; prefer claim path
            # when property_id is absent.
            if isinstance(item, Mapping) and "property_id" in item:
                if claim_buffer:
                    asserted.extend(identify_asserted_properties(claim_buffer))
                    claim_buffer = []
                asserted.append(AssertedProperty.from_dict(item) if "schema" in item else AssertedProperty(
                    property_id=item["property_id"],
                    claim_id=item["claim_id"],
                    property_class=item["property_class"],
                    statement=item["statement"],
                    symbol_ids=item.get("symbol_ids", ()),
                    artifact_cids=item.get("artifact_cids", ()),
                    risk_class=item.get(
                        "risk_class", MutationRiskClass.LOW.value
                    ),
                    source_path=item.get("source_path"),
                    language=item.get("language", "python"),
                    artifact_type=item.get("artifact_type", "source_module"),
                    prerequisites=item.get("prerequisites", ()),
                    capsule_cids=item.get("capsule_cids", ()),
                    proof_unit_cids=item.get("proof_unit_cids", ()),
                    signals=item.get("signals"),
                    notes=item.get("notes"),
                    metadata=item.get("metadata", {}),
                ))
            else:
                claim_buffer.append(item)
        else:
            raise TargetSelectionError(
                "properties items must be AssertedProperty, ClaimRecord, or mappings"
            )
    if claim_buffer:
        asserted.extend(identify_asserted_properties(claim_buffer))

    if not asserted:
        empty = TargetSelectionResult(
            targets=(),
            ranking=(),
            asserted_properties=(),
            budget=budget_n,
        )
        return empty if return_result else empty.targets

    # Group by binding key.
    groups: dict[tuple[Any, ...], list[AssertedProperty]] = {}
    for prop in asserted:
        groups.setdefault(prop.binding_key(), []).append(prop)

    candidates: list[RiskCandidate] = []
    group_by_subject: dict[str, list[AssertedProperty]] = {}
    for key, group in groups.items():
        target_id = _stable_target_id(key)
        risk_class = highest_risk_class(item.risk_class for item in group)
        signals = _merge_signals([item.signals for item in group])
        property_classes = sorted({item.property_class for item in group})
        candidates.append(
            RiskCandidate(
                subject_id=target_id,
                risk_class=risk_class,
                signals=signals,
                property_classes=property_classes,
                metadata={
                    "claim_ids": sorted({item.claim_id for item in group}),
                    "property_ids": sorted(
                        {item.property_id for item in group}
                    ),
                },
            )
        )
        group_by_subject[target_id] = group

    try:
        ranking = rank_mutation_risk(candidates, budget=budget_n, apply_sampling=True)
    except TargetRiskError as exc:
        raise TargetSelectionError(str(exc)) from exc

    prerequisites_default = _unique_sorted_tokens(
        list(default_prerequisites),
        "default_prerequisites",
        maximum=MAX_PREREQUISITES,
    )

    targets: list[MutationTarget] = []
    for score in selected_risk_scores(ranking):
        group = group_by_subject[score.subject_id]
        head = group[0]
        prerequisites = sorted(
            {
                *prerequisites_default,
                *(item for prop in group for item in prop.prerequisites),
            }
        )
        capsule_cids = sorted(
            {cid for prop in group for cid in prop.capsule_cids}
        )
        proof_unit_cids = sorted(
            {cid for prop in group for cid in prop.proof_unit_cids}
        )
        claim_ids = sorted({prop.claim_id for prop in group})
        property_ids = sorted({prop.property_id for prop in group})
        property_classes = sorted({prop.property_class for prop in group})
        targets.append(
            MutationTarget(
                target_id=score.subject_id,
                repository_id=repo_id,
                repository_state_cid=state_cid,
                symbol_ids=head.symbol_ids,
                artifact_cids=head.artifact_cids,
                language=head.language,
                artifact_type=head.artifact_type,
                prerequisites=prerequisites,
                risk_class=score.risk_class,
                risk_weight_bp=score.risk_weight_bp,
                capsule_cids=capsule_cids,
                proof_unit_cids=proof_unit_cids,
                source_path=head.source_path,
                notes=None,
                metadata={
                    "claim_ids": claim_ids,
                    "property_ids": property_ids,
                    "property_classes": property_classes,
                    "selection_reason": score.selection_reason,
                    "rank": score.rank,
                    "contributions": dict(score.contributions),
                },
            )
        )

    # Preserve rank order from selected_risk_scores.
    if len(targets) > MAX_TARGETS:
        raise TargetSelectionError("selected targets exceed global MAX_TARGETS")

    result = TargetSelectionResult(
        targets=tuple(targets),
        ranking=ranking,
        asserted_properties=tuple(
            sorted(asserted, key=lambda item: (item.claim_id, item.property_class))
        ),
        budget=budget_n,
    )
    return result if return_result else result.targets


__all__ = [
    "ASSERTED_PROPERTY_SCHEMA",
    "CLAIM_RECORD_SCHEMA",
    "IDENTIFY_ASSERTED_PROPERTIES_INTERFACE",
    "MAX_CLAIMS",
    "MAX_STATEMENT_CHARS",
    "SELECT_MUTATION_TARGETS_INTERFACE",
    "TARGET_SELECTION_RESULT_SCHEMA",
    "AssertedProperty",
    "ClaimRecord",
    "TargetSelectionError",
    "TargetSelectionResult",
    "identify_asserted_properties",
    "select_mutation_targets",
]
