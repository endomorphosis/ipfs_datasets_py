"""Chain-neutral contract state epochs, principals, and privileges.

CRYPTOIR-G300 / CRYPTOIR-014 owns the shared *state* half of contract
semantics: code/state epochs, principals, privilege sets, and invariants.

These types share *concepts* (who may act, what code is live, what is assumed
invariant) without equating chain-specific mechanisms.  An EVM storage slot,
a Solana account data blob, a Bitcoin UTXO, and an XRPL ledger object are not
the same state model; adapters bind them through epochs and digests rather than
false equivalences.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ..ir_core.canonical import CollectionSchema, CollectionSemantics, canonical_json_bytes
from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, freeze_json, thaw_json
from .identity import crypto_ir_identity
from .model import (
    ChainIdentity,
    CryptoIRValidationError,
    LedgerCoordinate,
    TimeBoundedEpoch,
    ValidityWindow,
)
from .provenance import (
    AuthorityKind,
    CryptoIRProvenanceError,
    freeze_json_mapping,
)
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION


CRYPTO_IR_STATE_DOMAIN: Final[str] = "crypto-ir.contract-state"
CRYPTO_IR_STATE_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_TAGGED = re.compile(r"^[a-z0-9]+:[0-9a-f]+$")


class StateEpochKind(str, Enum):
    """What a :class:`ContractStateEpoch` freezes.

    Kinds are closed and non-interchangeable.  ``CODE`` is live executable
    bytes; ``PROGRAM_DATA`` is Solana program-data; ``STORAGE`` is contract
    storage / account data; ``LEDGER_OBJECT`` is a native ledger object;
    ``SCRIPT`` / ``TAPLEAF`` describe Bitcoin spending programs; ``PROXY`` and
    ``UPGRADE_AUTHORITY`` bind mutable control planes as epochs.
    """

    CODE = "code"
    PROGRAM_DATA = "program_data"
    STORAGE = "storage"
    LEDGER_OBJECT = "ledger_object"
    SCRIPT = "script"
    TAPLEAF = "tapleaf"
    PROXY = "proxy"
    UPGRADE_AUTHORITY = "upgrade_authority"
    CONFIG = "config"
    OTHER = "other"


class PrivilegeFlag(str, Enum):
    """Named privilege bits that frontends may assert on principals.

    Flags are shared vocabulary, not proof that one chain's ``signer`` equals
    another's.  Adapters set only flags they can ground; security rules must
    require the exact flag set their chain model needs.
    """

    SIGNER = "signer"
    WRITABLE = "writable"
    OWNER = "owner"
    CALLER = "caller"
    CALLEE = "callee"
    DELEGATE = "delegate"
    UPGRADE_AUTHORITY = "upgrade_authority"
    FEE_PAYER = "fee_payer"
    MINTER = "minter"
    BURNER = "burner"
    FREEZER = "freezer"
    CLAWBACK = "clawback"
    ISSUER = "issuer"
    SPENDER = "spender"
    APPROVER = "approver"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Validation helpers (mirror model.py; kept local so this module stays leaf)
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRValidationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise CryptoIRValidationError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRValidationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (ProvenanceValidationError, CryptoIRProvenanceError, TypeError, ValueError) as exc:
        raise CryptoIRValidationError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRValidationError(f"unsupported {name}: {value!r}") from exc


def _digest(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = _text(value, name, allow_empty=allow_empty)
    if not text:
        return text
    if _SHA256_HEX.fullmatch(text):
        return f"sha256:{text}"
    if not _DIGEST_TAGGED.fullmatch(text):
        raise CryptoIRValidationError(
            f"{name} must be a tagged digest (algorithm:hex) or bare sha256 hex"
        )
    return text


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRValidationError(f"{name} values must be unique")
    return result


def _sequence_of(
    values: Any,
    item_type: type[Any],
    name: str,
    *,
    from_dict: Any | None = None,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    converted: list[Any] = []
    for item in values:
        if isinstance(item, item_type):
            converted.append(item)
        elif from_dict is not None and isinstance(item, Mapping):
            converted.append(from_dict(item))
        else:
            raise CryptoIRValidationError(
                f"{name} items must be {item_type.__name__} or mappings"
            )
    return tuple(converted)


def _privilege_flags(values: Any) -> frozenset[PrivilegeFlag]:
    if values is None:
        return frozenset()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError("privileges must be a sequence")
    flags = frozenset(_enum(PrivilegeFlag, item, "privilege") for item in values)
    return flags


# ---------------------------------------------------------------------------
# Principals and privileges
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrivilegeSet:
    """Closed privilege set; order is non-semantic, membership is exact."""

    flags: frozenset[PrivilegeFlag] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if isinstance(self.flags, PrivilegeSet):
            object.__setattr__(self, "flags", self.flags.flags)
        elif not isinstance(self.flags, frozenset):
            object.__setattr__(self, "flags", _privilege_flags(self.flags))
        else:
            # Ensure members are PrivilegeFlag even when caller passed frozenset[str].
            normalized = frozenset(
                _enum(PrivilegeFlag, item, "privilege") for item in self.flags
            )
            object.__setattr__(self, "flags", normalized)

    def has(self, flag: PrivilegeFlag | str) -> bool:
        return _enum(PrivilegeFlag, flag, "privilege") in self.flags  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        return {"flags": sorted(flag.value for flag in self.flags)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Sequence[Any]) -> "PrivilegeSet":
        if isinstance(value, Mapping):
            _known_fields(value, frozenset({"flags"}), "PrivilegeSet")
            return cls(flags=value.get("flags", ()))
        return cls(flags=value)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, PrivilegeFlag):
            return item in self.flags
        if isinstance(item, str):
            try:
                return PrivilegeFlag(item) in self.flags
            except ValueError:
                return False
        return False


@dataclass(frozen=True, slots=True)
class PrincipalRef:
    """A principal participating in contract control or effects.

    ``principal_id`` is stable within a semantic model.  ``account_id`` may
    bind to an :class:`~.model.AccountIdentity` when the principal is an
    on-chain account; scripts, PDAs, and abstract roles may leave it empty.
    """

    principal_id: str
    kind: str = "account"
    account_id: str = ""
    privileges: PrivilegeSet = field(default_factory=PrivilegeSet)
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "principal_id", _identifier(self.principal_id, "principal_id")
        )
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        object.__setattr__(
            self, "account_id", _text(self.account_id, "account_id", allow_empty=True)
        )
        if self.account_id and not _ID_RE.fullmatch(self.account_id):
            raise CryptoIRValidationError("account_id is not a stable identifier")
        if not isinstance(self.privileges, PrivilegeSet):
            if isinstance(self.privileges, Mapping):
                object.__setattr__(
                    self, "privileges", PrivilegeSet.from_dict(self.privileges)
                )
            else:
                object.__setattr__(
                    self, "privileges", PrivilegeSet(flags=self.privileges)
                )
        object.__setattr__(self, "label", _text(self.label, "label", allow_empty=True))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "attributes": thaw_json(self.attributes),
            "kind": self.kind,
            "label": self.label,
            "principal_id": self.principal_id,
            "privileges": self.privileges.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PrincipalRef":
        value = _as_mapping(value, "PrincipalRef")
        _known_fields(
            value,
            frozenset(
                {
                    "principal_id",
                    "kind",
                    "account_id",
                    "privileges",
                    "label",
                    "attributes",
                }
            ),
            "PrincipalRef",
        )
        privileges = value.get("privileges", ())
        return cls(
            principal_id=value.get("principal_id", ""),
            kind=value.get("kind", "account"),
            account_id=value.get("account_id", ""),
            privileges=(
                PrivilegeSet.from_dict(privileges)
                if isinstance(privileges, Mapping)
                else PrivilegeSet(flags=privileges)
            ),
            label=value.get("label", ""),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# State / code epochs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContractStateEpoch:
    """Time-bounded contract code or state epoch.

    Mutable control planes (proxy implementation, upgrade authority, program
    data) and live code are epochs: changing the epoch invalidates dependent
    analysis.  The epoch does **not** invent a universal VM state; it binds a
    content digest, chain identity, optional ledger coordinate, and validity
    window.

    ``fact_id`` is the stable identifier used by coverage, unsupported
    declarations, and proof-obligation dependency sets.
    """

    epoch_id: str
    chain: ChainIdentity
    subject_id: str
    kind: StateEpochKind
    value_digest: str
    fact_id: str = ""
    code_digest: str = ""
    storage_digest: str = ""
    validity: ValidityWindow = field(default_factory=ValidityWindow)
    observed_at: LedgerCoordinate = field(default_factory=LedgerCoordinate)
    source_provenance_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_STATE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        if not isinstance(self.chain, ChainIdentity):
            object.__setattr__(
                self, "chain", ChainIdentity.from_dict(_as_mapping(self.chain, "chain"))
            )
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(self, "kind", _enum(StateEpochKind, self.kind, "kind"))
        object.__setattr__(
            self, "value_digest", _digest(self.value_digest, "value_digest")
        )
        fact = self.fact_id or f"epoch:{self.epoch_id}"
        object.__setattr__(self, "fact_id", _identifier(fact, "fact_id"))
        object.__setattr__(
            self, "code_digest", _digest(self.code_digest, "code_digest", allow_empty=True)
        )
        object.__setattr__(
            self,
            "storage_digest",
            _digest(self.storage_digest, "storage_digest", allow_empty=True),
        )
        if not isinstance(self.validity, ValidityWindow):
            object.__setattr__(
                self,
                "validity",
                ValidityWindow.from_dict(_as_mapping(self.validity, "validity")),
            )
        if not isinstance(self.observed_at, LedgerCoordinate):
            object.__setattr__(
                self,
                "observed_at",
                LedgerCoordinate.from_dict(
                    _as_mapping(self.observed_at, "observed_at")
                ),
            )
        object.__setattr__(
            self,
            "source_provenance_ids",
            _unique_ids(self.source_provenance_ids, "source_provenance_ids"),
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_time_bounded_epoch(self) -> TimeBoundedEpoch:
        """Project to the kernel :class:`TimeBoundedEpoch` record."""

        return TimeBoundedEpoch(
            epoch_id=self.epoch_id,
            kind=self.kind.value if isinstance(self.kind, StateEpochKind) else str(self.kind),
            subject_id=self.subject_id,
            value_digest=self.value_digest,
            validity=self.validity,
            attributes={
                "fact_id": self.fact_id,
                "code_digest": self.code_digest,
                "storage_digest": self.storage_digest,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "chain": self.chain.to_dict(),
            "code_digest": self.code_digest,
            "epoch_id": self.epoch_id,
            "fact_id": self.fact_id,
            "kind": self.kind.value if isinstance(self.kind, StateEpochKind) else self.kind,
            "observed_at": self.observed_at.to_dict(),
            "schema_version": self.schema_version,
            "source_provenance_ids": list(self.source_provenance_ids),
            "storage_digest": self.storage_digest,
            "subject_id": self.subject_id,
            "validity": self.validity.to_dict(),
            "value_digest": self.value_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractStateEpoch":
        value = _as_mapping(value, "ContractStateEpoch")
        _known_fields(
            value,
            frozenset(
                {
                    "epoch_id",
                    "chain",
                    "subject_id",
                    "kind",
                    "value_digest",
                    "fact_id",
                    "code_digest",
                    "storage_digest",
                    "validity",
                    "observed_at",
                    "source_provenance_ids",
                    "assumption_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "ContractStateEpoch",
        )
        return cls(
            epoch_id=value.get("epoch_id", ""),
            chain=ChainIdentity.from_dict(_as_mapping(value.get("chain", {}), "chain")),
            subject_id=value.get("subject_id", ""),
            kind=value.get("kind", StateEpochKind.OTHER),
            value_digest=value.get("value_digest", ""),
            fact_id=value.get("fact_id", ""),
            code_digest=value.get("code_digest", ""),
            storage_digest=value.get("storage_digest", ""),
            validity=ValidityWindow.from_dict(
                _as_mapping(value.get("validity", {}), "validity")
            ),
            observed_at=LedgerCoordinate.from_dict(
                _as_mapping(value.get("observed_at", {}), "observed_at")
            ),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_STATE_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_STATE_DOMAIN}.epoch",
        )


@dataclass(frozen=True, slots=True)
class StateInvariant:
    """Declared invariant over contract state; not a proof of truth."""

    invariant_id: str
    statement: str
    fact_id: str = ""
    subject_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    source_provenance_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.ASSUMPTION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invariant_id", _identifier(self.invariant_id, "invariant_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        fact = self.fact_id or f"invariant:{self.invariant_id}"
        object.__setattr__(self, "fact_id", _identifier(fact, "fact_id"))
        object.__setattr__(
            self, "subject_ids", _unique_ids(self.subject_ids, "subject_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self,
            "source_provenance_ids",
            _unique_ids(self.source_provenance_ids, "source_provenance_ids"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "fact_id": self.fact_id,
            "invariant_id": self.invariant_id,
            "source_provenance_ids": list(self.source_provenance_ids),
            "statement": self.statement,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateInvariant":
        value = _as_mapping(value, "StateInvariant")
        _known_fields(
            value,
            frozenset(
                {
                    "invariant_id",
                    "statement",
                    "fact_id",
                    "subject_ids",
                    "assumption_ids",
                    "source_provenance_ids",
                    "attributes",
                }
            ),
            "StateInvariant",
        )
        return cls(
            invariant_id=value.get("invariant_id", ""),
            statement=value.get("statement", ""),
            fact_id=value.get("fact_id", ""),
            subject_ids=tuple(value.get("subject_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            attributes=value.get("attributes", {}),
        )


CONTRACT_STATE_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/source_provenance_ids": CollectionSemantics.SET_LIKE,
        "/assumption_ids": CollectionSemantics.SET_LIKE,
        "/subject_ids": CollectionSemantics.SET_LIKE,
        "/privileges/flags": CollectionSemantics.SET_LIKE,
    }
)


__all__ = [
    "CONTRACT_STATE_COLLECTION_SCHEMA",
    "CRYPTO_IR_STATE_DOMAIN",
    "CRYPTO_IR_STATE_SCHEMA_VERSION",
    "ContractStateEpoch",
    "PrincipalRef",
    "PrivilegeFlag",
    "PrivilegeSet",
    "StateEpochKind",
    "StateInvariant",
]
