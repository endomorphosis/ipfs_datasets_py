"""Immutable, solver-neutral claim declarations.

This module describes what is claimed, which premises are assumed, and which
properties must be checked.  It intentionally contains no solver objects,
backend state, or verification verdicts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, TypeAlias


IR_CLAIM_SCHEMA_VERSION: Final = "ir-claim/v1"
IR_ASSUMPTION_SCHEMA_VERSION: Final = "ir-assumption/v1"
IR_OBLIGATION_SCHEMA_VERSION: Final = "ir-proof-obligation/v1"

JSONScalar: TypeAlias = str | int | float | bool | None
FrozenJSON: TypeAlias = JSONScalar | tuple["FrozenJSON", ...] | Mapping[str, "FrozenJSON"]


class ClaimValidationError(ValueError):
    """Raised when a claim declaration is invalid or internally inconsistent."""


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClaimValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ClaimValidationError(f"{field_name} must not have surrounding whitespace")
    return value


class FrozenMap(Mapping[str, FrozenJSON]):
    """A recursively immutable, deterministically ordered JSON mapping."""

    __slots__ = ("_items", "_hash")

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        if values is not None and not isinstance(values, Mapping):
            raise ClaimValidationError("frozen data must be a mapping")
        self._items = tuple(
            sorted(
                (
                    _require_text(key, "mapping key"),
                    freeze_json(value),
                )
                for key, value in (values or {}).items()
            )
        )
        self._hash = hash(self._items)

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
    """Copy and recursively freeze a JSON-compatible value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ClaimValidationError("non-finite floats are not valid IR data")
        return value
    if isinstance(value, FrozenMap):
        return value
    if isinstance(value, Mapping):
        return FrozenMap(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    raise ClaimValidationError(
        f"IR data must be JSON-compatible, got {type(value).__name__}"
    )


def thaw_json(value: FrozenJSON) -> Any:
    """Return detached mutable JSON data for serialization."""

    if isinstance(value, FrozenMap):
        return value.to_dict()
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def stable_digest(value: Mapping[str, Any]) -> str:
    """Return a lowercase SHA-256 digest of canonical UTF-8 JSON."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_text_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ClaimValidationError(f"{field_name} must be a sequence of strings")
    normalized = tuple(_require_text(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ClaimValidationError(f"{field_name} values must be unique")
    return normalized


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ClaimValidationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    record_name: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ClaimValidationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class Assumption:
    """An explicit premise; declaring it does not establish that it is true."""

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
        value = _require_mapping(value, "assumption")
        _reject_unknown_fields(
            value,
            frozenset(
                {"assumption_id", "statement", "source_refs", "metadata", "schema_version"}
            ),
            "assumption",
        )
        return cls(
            assumption_id=value.get("assumption_id", ""),
            statement=value.get("statement", ""),
            source_refs=tuple(value.get("source_refs", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get("schema_version", IR_ASSUMPTION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """A theorem-shaped target with no implied verification status."""

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
        value = _require_mapping(value, "proof obligation")
        _reject_unknown_fields(
            value,
            frozenset(
                {
                    "obligation_id",
                    "statement",
                    "assumption_ids",
                    "logic_family",
                    "source_refs",
                    "metadata",
                    "schema_version",
                }
            ),
            "proof obligation",
        )
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
    """A content-addressed claim with explicit assumptions and obligations."""

    claim_id: str
    statement: str
    assumptions: tuple[Assumption, ...]
    obligations: tuple[ProofObligation, ...]
    domain: str = "shared"
    declaration_id: str = ""
    source_refs: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = IR_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _require_text(self.claim_id, "claim_id"))
        object.__setattr__(self, "statement", _require_text(self.statement, "statement"))
        object.__setattr__(self, "domain", _require_text(self.domain, "domain"))
        object.__setattr__(
            self,
            "declaration_id",
            _require_text(self.declaration_id or self.claim_id, "declaration_id"),
        )
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
        """Identity of the declaration, independent of any verification run."""

        return stable_digest(self.to_dict())

    def obligation(self, obligation_id: str) -> ProofObligation:
        for obligation in self.obligations:
            if obligation.obligation_id == obligation_id:
                return obligation
        raise KeyError(obligation_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "claim_id": self.claim_id,
            "declaration_id": self.declaration_id,
            "domain": self.domain,
            "metadata": self.metadata.to_dict(),
            "obligations": [item.to_dict() for item in self.obligations],
            "schema_version": self.schema_version,
            "source_refs": list(self.source_refs),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IRClaim":
        value = _require_mapping(value, "claim")
        _reject_unknown_fields(
            value,
            frozenset(
                {
                    "claim_id",
                    "statement",
                    "assumptions",
                    "obligations",
                    "domain",
                    "declaration_id",
                    "source_refs",
                    "metadata",
                    "schema_version",
                }
            ),
            "claim",
        )
        assumptions = value.get("assumptions", ())
        obligations = value.get("obligations", ())
        if isinstance(assumptions, (str, bytes, bytearray)) or not isinstance(
            assumptions, Sequence
        ):
            raise ClaimValidationError("assumptions must be a sequence")
        if isinstance(obligations, (str, bytes, bytearray)) or not isinstance(
            obligations, Sequence
        ):
            raise ClaimValidationError("obligations must be a sequence")
        return cls(
            claim_id=value.get("claim_id", ""),
            statement=value.get("statement", ""),
            assumptions=tuple(Assumption.from_dict(item) for item in assumptions),
            obligations=tuple(ProofObligation.from_dict(item) for item in obligations),
            domain=value.get("domain", "shared"),
            declaration_id=value.get("declaration_id", ""),
            source_refs=tuple(value.get("source_refs", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get("schema_version", IR_CLAIM_SCHEMA_VERSION),
        )


Claim = IRClaim
IRAssumption = Assumption
IRObligation = ProofObligation
Obligation = ProofObligation


__all__ = [
    "Assumption",
    "Claim",
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
