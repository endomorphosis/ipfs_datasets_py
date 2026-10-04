"""XRPL-native intermediate records for ledger processing.

These models sit between provider payloads and the chain-neutral
:mod:`..models` envelope. They carry delivered amounts, destination tags,
memos (under privacy policy), sequence, and validation state. No signing or
submission fields exist. Xaman payload lifecycle is intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from ..errors import InvalidRequestError
from .networks import XRPLNetwork


class TxOutcome(StrEnum):
    """Distinct transaction outcomes; do not collapse failed/unvalidated/unknown."""

    VALIDATED_SUCCESS = "validated_success"
    VALIDATED_FAILED = "validated_failed"
    UNVALIDATED = "unvalidated"
    UNKNOWN = "unknown"


class AmountKind(StrEnum):
    XRP = "xrp"
    ISSUED = "issued"


@dataclass(frozen=True, slots=True)
class XRPLAmount:
    """Native or issued amount prior to ExactAmount projection."""

    kind: AmountKind
    # XRP: integer drops. Issued: decimal value string.
    value: str
    currency: str | None = None
    issuer: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AmountKind):
            raise InvalidRequestError("kind must be AmountKind")
        if not isinstance(self.value, str) or not self.value.strip():
            raise InvalidRequestError("amount value must not be empty")
        object.__setattr__(self, "value", self.value.strip())
        if self.kind is AmountKind.XRP:
            if self.currency is not None or self.issuer is not None:
                raise InvalidRequestError("XRP amount must not carry currency/issuer")
        else:
            if not self.currency or not self.issuer:
                raise InvalidRequestError(
                    "issued amount requires currency and issuer identity"
                )
            object.__setattr__(self, "currency", self.currency.strip())
            object.__setattr__(self, "issuer", self.issuer.strip())

    def to_dict(self) -> dict[str, Any]:
        if self.kind is AmountKind.XRP:
            return {"kind": self.kind.value, "value_drops": self.value}
        return {
            "kind": self.kind.value,
            "currency": self.currency,
            "issuer": self.issuer,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class MemoRecord:
    """One memo after privacy policy (data may be redacted or truncated)."""

    memo_type: str | None = None
    memo_format: str | None = None
    memo_data: str | None = None
    data_redacted: bool = False
    data_truncated: bool = False
    original_data_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "memo_type": self.memo_type,
            "memo_format": self.memo_format,
            "memo_data": self.memo_data,
            "data_redacted": self.data_redacted,
            "data_truncated": self.data_truncated,
            "original_data_bytes": self.original_data_bytes,
        }


@dataclass(frozen=True, slots=True)
class XRPLTransaction:
    """Normalized XRPL transaction prior to chain-neutral projection."""

    hash: str
    account: str
    transaction_type: str
    sequence: int
    outcome: TxOutcome
    network: XRPLNetwork
    fee_drops: str | None = None
    destination: str | None = None
    destination_tag: int | None = None
    source_tag: int | None = None
    amount: XRPLAmount | None = None
    delivered_amount: XRPLAmount | None = None
    send_max: XRPLAmount | None = None
    partial_payment: bool = False
    memos: tuple[MemoRecord, ...] = ()
    ledger_index: int | None = None
    ledger_hash: str | None = None
    transaction_index: int | None = None
    close_time_iso: datetime | None = None
    transaction_result: str | None = None
    validated: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.hash, str) or not self.hash.strip():
            raise InvalidRequestError("hash must not be empty")
        object.__setattr__(self, "hash", self.hash.upper())
        if not isinstance(self.account, str) or not self.account.strip():
            raise InvalidRequestError("account must not be empty")
        if not isinstance(self.transaction_type, str) or not self.transaction_type.strip():
            raise InvalidRequestError("transaction_type must not be empty")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise InvalidRequestError("sequence must be a non-negative integer")
        if not isinstance(self.outcome, TxOutcome):
            raise InvalidRequestError("outcome must be TxOutcome")
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be XRPLNetwork")
        if self.destination_tag is not None and (
            isinstance(self.destination_tag, bool)
            or not isinstance(self.destination_tag, int)
            or self.destination_tag < 0
            or self.destination_tag > 0xFFFFFFFF
        ):
            raise InvalidRequestError("destination_tag must be a uint32")
        if self.source_tag is not None and (
            isinstance(self.source_tag, bool)
            or not isinstance(self.source_tag, int)
            or self.source_tag < 0
            or self.source_tag > 0xFFFFFFFF
        ):
            raise InvalidRequestError("source_tag must be a uint32")
        object.__setattr__(self, "memos", tuple(self.memos))
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))
        if self.ledger_hash is not None:
            object.__setattr__(self, "ledger_hash", self.ledger_hash.upper())

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "hash": self.hash,
            "account": self.account,
            "transaction_type": self.transaction_type,
            "sequence": self.sequence,
            "outcome": self.outcome.value,
            "network": self.network.value,
            "validated": self.validated,
            "partial_payment": self.partial_payment,
            "memos": [m.to_dict() for m in self.memos],
        }
        if self.fee_drops is not None:
            result["fee_drops"] = self.fee_drops
        if self.destination is not None:
            result["destination"] = self.destination
        if self.destination_tag is not None:
            result["destination_tag"] = self.destination_tag
        if self.source_tag is not None:
            result["source_tag"] = self.source_tag
        if self.amount is not None:
            result["amount"] = self.amount.to_dict()
        if self.delivered_amount is not None:
            result["delivered_amount"] = self.delivered_amount.to_dict()
        if self.send_max is not None:
            result["send_max"] = self.send_max.to_dict()
        if self.ledger_index is not None:
            result["ledger_index"] = self.ledger_index
        if self.ledger_hash is not None:
            result["ledger_hash"] = self.ledger_hash
        if self.transaction_index is not None:
            result["transaction_index"] = self.transaction_index
        if self.transaction_result is not None:
            result["transaction_result"] = self.transaction_result
        return result


__all__ = [
    "AmountKind",
    "MemoRecord",
    "TxOutcome",
    "XRPLAmount",
    "XRPLTransaction",
]
