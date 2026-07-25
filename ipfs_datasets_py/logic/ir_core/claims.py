"""Immutable, solver-neutral claim declarations.

The objects in this module describe *what* is claimed.  They deliberately do
not contain solver expressions, execution state, or verification verdicts.
Those belong to backend adapters and the result protocol in
``ir_core.protocols``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, TypeAlias


IR_CLAIM_SCHEMA_VERSION: Final = "ir-claim/v1"
IR_ASSUMPTION_SCHEMA_VERSION: Final = "ir-assumption/v1"
IR_OBLIGATION_SCHEMA_VERSION: Final = "ir-obligation/v1"

JSONScalar: TypeAlias = str | int | float | bool | None
FrozenJSON: TypeAlias = (
    JSONScalar | tuple["FrozenJSON", ...] | Mapping[str, "FrozenJSON"]
)


class ClaimValidationError(ValueError):
    """Raised when a claim declaration is incomplete or internally inconsistent."""


class FrozenMap(Mapping[str, FrozenJSON]):
    """A small, recursively immutable mapping with deterministic ordering.

    ``dataclass(frozen=True)`` alone does not make nested dictionaries or lists
    immutable.  Claim metadata is therefore normalized into ``FrozenMap`` and
    tuples at the declaration boundary.
    """

    __slots__ = ("_items", "_hash")

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        normalized = tuple(
            sorted(
                (
                    _require_text(key, "metadata key"),
                    freeze_json(value),
                )
                for key, value in (values or {}).items()
            )
        )
        keys = tuple(key for key, _ in normalized)
        if len(keys) != len(set(keys)):
            raise ClaimValidationError("metadata keys must be unique")
        self._items = normalized
        self._hash = hash(normalized)

    def __getitem__(self, key: str) -> FrozenJSON:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return f"FrozenMap({dict(self._items)!r})"

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy."""

        return {key: thaw_json(value) for key, value in self._items}


def freeze_json(value: Any) -> FrozenJSON:
    """Recursively freeze a JSON-compatible value.

    Rejecting opaque Python objects keeps identity stable and prevents backend
    handles or mutable domain objects from leaking into the shared claim model.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ClaimValidationError("non-finite floats are not valid claim data")
        return value
    if isinstance(value, FrozenMap):
        return value
    if isinstance(value, Mapping):
        return FrozenMap(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    raise ClaimValidationError(
        f"claim data must be JSON-compatible, got {type(value).__name__}"
    )


def thaw_json(value: FrozenJSON) -> Any:
    """Return a detached JSON-compatible representation of frozen data."""

    if isinstance(value, FrozenMap):
        return value.to_dict()
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def stable_digest(value: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of a canonical JSON mapping."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClaimValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ClaimValidationError(f"{field_name} must not have surrounding whitespace")
    return value


def _unique_text_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_require_text(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ClaimValidationError(f"{field_name} values must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class Assumption:
    """An explicit premise on which one or more obligations depend."""

    assumption_id: str
    statement: str
    source_refs: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = IR_ASSUMPTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assumption_id", _require_text(self.assumption_id, "assumption_id")
        )
        object.__setattr__(self, "statement", _require_text(self.statement, "statement"))
        object.__setattr__(
            self, "source_refs", _unique_text_tuple(self.source_refs, "source_ref")
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata if isinstance(self.metadata, FrozenMap) else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema_version")
        )
        if self.schema_version != IR_ASSUMPTION_SCHEMA_VERSION:
            raise ClaimValidationError(
                f"unsupported assumption schema version: {self.schema_version}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "source_refs": list(self.source_refs),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Assumption":
        return cls(
            assumption_id=value.get("assumption_id", ""),
            statement=value.get("statement", ""),
            source_refs=tuple(value.get("source_refs", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get("schema_version", IR_ASSUMPTION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """A theorem-shaped target without any assertion that it has been proved."""

    obligation_id: str
    statement: str
    assumption_ids: tuple[str, ...] = ()
    logic_family: str = "unspecified"
    source_refs: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = IR_OBLIGATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _require_text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(self, "statement", _require_text(self.statement, "statement"))
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_text_tuple(self.assumption_ids, "assumption_id"),
        )
        object.__setattr__(
            self, "logic_family", _require_text(self.logic_family, "logic_family")
        )
        object.__setattr__(
            self, "source_refs", _unique_text_tuple(self.source_refs, "source_ref")
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata if isinstance(self.metadata, FrozenMap) else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema_version")
        )
        if self.schema_version != IR_OBLIGATION_SCHEMA_VERSION:
            raise ClaimValidationError(
                f"unsupported obligation schema version: {self.schema_version}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "obligation_id": self.obligation_id,
            "schema_version": self.schema_version,
            "source_refs": list(self.source_refs),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofObligation":
        return cls(
            obligation_id=value.get("obligation_id", ""),
            statement=value.get("statement", ""),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            logic_family=value.get("logic_family", "unspecified"),
            source_refs=tuple(value.get("source_refs", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get("schema_version", IR_OBLIGATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class IRClaim:
    """A content-addressed collection of assumptions and proof obligations."""

    claim_id: str
    statement: str
    assumptions: tuple[Assumption, ...]
    obligations: tuple[ProofObligation, ...]
    domain: str = "shared"
    source_refs: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = IR_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _require_text(self.claim_id, "claim_id"))
        object.__setattr__(self, "statement", _require_text(self.statement, "statement"))
        object.__setattr__(self, "domain", _require_text(self.domain, "domain"))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "obligations", tuple(self.obligations))
        object.__setattr__(
            self, "source_refs", _unique_text_tuple(self.source_refs, "source_ref")
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata if isinstance(self.metadata, FrozenMap) else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema_version")
        )
        if self.schema_version != IR_CLAIM_SCHEMA_VERSION:
            raise ClaimValidationError(f"unsupported claim schema version: {self.schema_version}")
        if not self.obligations:
            raise ClaimValidationError("a claim must contain at least one obligation")
        if not all(isinstance(item, Assumption) for item in self.assumptions):
            raise ClaimValidationError("assumptions must contain Assumption values")
        if not all(isinstance(item, ProofObligation) for item in self.obligations):
            raise ClaimValidationError("obligations must contain ProofObligation values")

        assumption_ids = tuple(item.assumption_id for item in self.assumptions)
        obligation_ids = tuple(item.obligation_id for item in self.obligations)
        if len(assumption_ids) != len(set(assumption_ids)):
            raise ClaimValidationError("assumption IDs must be unique within a claim")
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ClaimValidationError("obligation IDs must be unique within a claim")
        known_assumptions = set(assumption_ids)
        for obligation in self.obligations:
            unknown = set(obligation.assumption_ids) - known_assumptions
            if unknown:
                raise ClaimValidationError(
                    f"obligation {obligation.obligation_id} references unknown assumptions: "
                    f"{', '.join(sorted(unknown))}"
                )

    @property
    def digest(self) -> str:
        """Content identity, independent of runtime/backend activity."""

        return stable_digest(self.to_dict())

    def obligation(self, obligation_id: str) -> ProofObligation:
        """Return an obligation by ID or fail closed."""

        for obligation in self.obligations:
            if obligation.obligation_id == obligation_id:
                return obligation
        raise KeyError(obligation_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "claim_id": self.claim_id,
            "domain": self.domain,
            "metadata": self.metadata.to_dict(),
            "obligations": [item.to_dict() for item in self.obligations],
            "schema_version": self.schema_version,
            "source_refs": list(self.source_refs),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IRClaim":
        return cls(
            claim_id=value.get("claim_id", ""),
            statement=value.get("statement", ""),
            assumptions=tuple(
                Assumption.from_dict(item) for item in value.get("assumptions", ())
            ),
            obligations=tuple(
                ProofObligation.from_dict(item) for item in value.get("obligations", ())
            ),
            domain=value.get("domain", "shared"),
            source_refs=tuple(value.get("source_refs", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get("schema_version", IR_CLAIM_SCHEMA_VERSION),
        )


# Descriptive aliases retained in the leaf module without editing shared exports.
IRAssumption = Assumption
IRObligation = ProofObligation
Obligation = ProofObligation


__all__ = [
    "Assumption",
    "ClaimValidationError",
    "FrozenMap",
    "IRAssumption",
    "IRClaim",
    "IRObligation",
    "Obligation",
    "ProofObligation",
    "IR_ASSUMPTION_SCHEMA_VERSION",
    "IR_CLAIM_SCHEMA_VERSION",
    "IR_OBLIGATION_SCHEMA_VERSION",
    "freeze_json",
    "stable_digest",
    "thaw_json",
]
