"""Chain-neutral asset and storage effect records.

CRYPTOIR-G300 / CRYPTOIR-014 owns shared *effect* primitives: exact asset
mutations, ordered effect sequences, and storage/account-data side effects.

Effects share concepts (transfer, mint, burn, allowance, freeze) without
claiming that an ERC-20 transfer, an SPL token transfer, a Bitcoin UTXO spend,
and an XRPL Payment are the same machine.  Adapters set ``EffectKind`` and
chain-local attributes; security rules demand exact assets and amounts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ..ir_core.canonical import CollectionSchema, CollectionSemantics, canonical_json_bytes
from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, thaw_json
from .identity import crypto_ir_identity
from .model import (
    AccountIdentity,
    AssetIdentity,
    CryptoIRValidationError,
    ExactAmount,
)
from .provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION


CRYPTO_IR_EFFECTS_DOMAIN: Final[str] = "crypto-ir.contract-effects"
CRYPTO_IR_EFFECTS_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class EffectKind(str, Enum):
    """Closed vocabulary of chain-neutral effect categories.

    These labels are shared concepts for obligation routing.  They are **not**
    a claim that every ledger implements the same opcode.  ``SPEND`` is for
    UTXO-style consumption; ``TRANSFER`` is for balance-model movement;
    ``NATIVE_TRANSITION`` covers ledger object mutations without a VM call.
    """

    TRANSFER = "transfer"
    MINT = "mint"
    BURN = "burn"
    APPROVE = "approve"
    ALLOWANCE_SPEND = "allowance_spend"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    CLAWBACK = "clawback"
    SPEND = "spend"
    CREATE_OUTPUT = "create_output"
    STORAGE_WRITE = "storage_write"
    ACCOUNT_DATA_WRITE = "account_data_write"
    NATIVE_TRANSITION = "native_transition"
    FEE = "fee"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Validation helpers
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


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise CryptoIRValidationError(f"{name} must be an integer")
    if value < 0:
        raise CryptoIRValidationError(f"{name} must be non-negative")
    return value


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRValidationError(f"{name} values must be unique")
    return result


def _optional_account(value: Any, name: str) -> AccountIdentity | None:
    if value is None:
        return None
    if isinstance(value, AccountIdentity):
        return value
    return AccountIdentity.from_dict(_as_mapping(value, name))


def _optional_asset(value: Any, name: str) -> AssetIdentity | None:
    if value is None:
        return None
    if isinstance(value, AssetIdentity):
        return value
    return AssetIdentity.from_dict(_as_mapping(value, name))


def _optional_amount(value: Any, name: str) -> ExactAmount | None:
    if value is None:
        return None
    if isinstance(value, ExactAmount):
        return value
    if isinstance(value, float):
        raise CryptoIRValidationError(f"{name} rejects binary floats")
    return ExactAmount.from_dict(_as_mapping(value, name))


# ---------------------------------------------------------------------------
# Asset effects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetEffect:
    """One exact asset or storage side-effect in model order.

    Order is semantic: ``order_index`` preserves emission order within a
    semantic model.  Monetary kinds require an :class:`ExactAmount` and an
    :class:`AssetIdentity`; pure storage/account-data writes may omit them.

    ``fact_id`` participates in coverage frontiers and proof-obligation
    dependency checks.
    """

    effect_id: str
    kind: EffectKind
    order_index: int
    fact_id: str = ""
    asset: AssetIdentity | None = None
    amount: ExactAmount | None = None
    from_account: AccountIdentity | None = None
    to_account: AccountIdentity | None = None
    principal_id: str = ""
    control_edge_id: str = ""
    state_epoch_id: str = ""
    summary: str = ""
    assumption_ids: tuple[str, ...] = ()
    source_provenance_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_EFFECTS_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    # Kinds that require exact asset + amount (no float, no omission).
    _MONETARY_KINDS: ClassVar[frozenset[EffectKind]] = frozenset(
        {
            EffectKind.TRANSFER,
            EffectKind.MINT,
            EffectKind.BURN,
            EffectKind.APPROVE,
            EffectKind.ALLOWANCE_SPEND,
            EffectKind.CLAWBACK,
            EffectKind.SPEND,
            EffectKind.CREATE_OUTPUT,
            EffectKind.FEE,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _identifier(self.effect_id, "effect_id"))
        object.__setattr__(self, "kind", _enum(EffectKind, self.kind, "kind"))
        object.__setattr__(
            self, "order_index", _non_negative_int(self.order_index, "order_index")
        )
        fact = self.fact_id or f"effect:{self.effect_id}"
        object.__setattr__(self, "fact_id", _identifier(fact, "fact_id"))
        object.__setattr__(self, "asset", _optional_asset(self.asset, "asset"))
        object.__setattr__(self, "amount", _optional_amount(self.amount, "amount"))
        object.__setattr__(
            self, "from_account", _optional_account(self.from_account, "from_account")
        )
        object.__setattr__(
            self, "to_account", _optional_account(self.to_account, "to_account")
        )
        object.__setattr__(
            self,
            "principal_id",
            _text(self.principal_id, "principal_id", allow_empty=True),
        )
        if self.principal_id and not _ID_RE.fullmatch(self.principal_id):
            raise CryptoIRValidationError("principal_id is not a stable identifier")
        object.__setattr__(
            self,
            "control_edge_id",
            _text(self.control_edge_id, "control_edge_id", allow_empty=True),
        )
        if self.control_edge_id and not _ID_RE.fullmatch(self.control_edge_id):
            raise CryptoIRValidationError("control_edge_id is not a stable identifier")
        object.__setattr__(
            self,
            "state_epoch_id",
            _text(self.state_epoch_id, "state_epoch_id", allow_empty=True),
        )
        if self.state_epoch_id and not _ID_RE.fullmatch(self.state_epoch_id):
            raise CryptoIRValidationError("state_epoch_id is not a stable identifier")
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
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
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

        kind = self.kind if isinstance(self.kind, EffectKind) else EffectKind(self.kind)
        if kind in self._MONETARY_KINDS:
            if self.asset is None:
                raise CryptoIRValidationError(
                    f"monetary effect kind {kind.value!r} requires an exact asset"
                )
            if self.amount is None:
                raise CryptoIRValidationError(
                    f"monetary effect kind {kind.value!r} requires an exact amount"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": None if self.amount is None else self.amount.to_dict(),
            "assumption_ids": list(self.assumption_ids),
            "asset": None if self.asset is None else self.asset.to_dict(),
            "attributes": thaw_json(self.attributes),
            "control_edge_id": self.control_edge_id,
            "effect_id": self.effect_id,
            "fact_id": self.fact_id,
            "from_account": (
                None if self.from_account is None else self.from_account.to_dict()
            ),
            "kind": self.kind.value if isinstance(self.kind, EffectKind) else self.kind,
            "order_index": self.order_index,
            "principal_id": self.principal_id,
            "schema_version": self.schema_version,
            "source_provenance_ids": list(self.source_provenance_ids),
            "state_epoch_id": self.state_epoch_id,
            "summary": self.summary,
            "to_account": None if self.to_account is None else self.to_account.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssetEffect":
        value = _as_mapping(value, "AssetEffect")
        _known_fields(
            value,
            frozenset(
                {
                    "effect_id",
                    "kind",
                    "order_index",
                    "fact_id",
                    "asset",
                    "amount",
                    "from_account",
                    "to_account",
                    "principal_id",
                    "control_edge_id",
                    "state_epoch_id",
                    "summary",
                    "assumption_ids",
                    "source_provenance_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "AssetEffect",
        )
        asset_raw = value.get("asset")
        amount_raw = value.get("amount")
        from_raw = value.get("from_account")
        to_raw = value.get("to_account")
        return cls(
            effect_id=value.get("effect_id", ""),
            kind=value.get("kind", EffectKind.OTHER),
            order_index=value.get("order_index", 0),
            fact_id=value.get("fact_id", ""),
            asset=(
                None
                if asset_raw is None
                else AssetIdentity.from_dict(_as_mapping(asset_raw, "asset"))
            ),
            amount=(
                None
                if amount_raw is None
                else ExactAmount.from_dict(_as_mapping(amount_raw, "amount"))
            ),
            from_account=(
                None
                if from_raw is None
                else AccountIdentity.from_dict(_as_mapping(from_raw, "from_account"))
            ),
            to_account=(
                None
                if to_raw is None
                else AccountIdentity.from_dict(_as_mapping(to_raw, "to_account"))
            ),
            principal_id=value.get("principal_id", ""),
            control_edge_id=value.get("control_edge_id", ""),
            state_epoch_id=value.get("state_epoch_id", ""),
            summary=value.get("summary", ""),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            source_provenance_ids=tuple(value.get("source_provenance_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_EFFECTS_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_EFFECTS_DOMAIN}.asset-effect",
        )


def ordered_effects(effects: Sequence[AssetEffect]) -> tuple[AssetEffect, ...]:
    """Return effects sorted by ``order_index``, failing on collisions."""

    if isinstance(effects, (str, bytes, bytearray)) or not isinstance(effects, Sequence):
        raise CryptoIRValidationError("effects must be a sequence")
    items = list(effects)
    indices = [item.order_index for item in items]
    if len(indices) != len(set(indices)):
        raise CryptoIRValidationError("effect order_index values must be unique")
    return tuple(sorted(items, key=lambda item: item.order_index))


ASSET_EFFECT_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/assumption_ids": CollectionSemantics.SET_LIKE,
        "/source_provenance_ids": CollectionSemantics.SET_LIKE,
    }
)


__all__ = [
    "ASSET_EFFECT_COLLECTION_SCHEMA",
    "CRYPTO_IR_EFFECTS_DOMAIN",
    "CRYPTO_IR_EFFECTS_SCHEMA_VERSION",
    "AssetEffect",
    "EffectKind",
    "ordered_effects",
]
