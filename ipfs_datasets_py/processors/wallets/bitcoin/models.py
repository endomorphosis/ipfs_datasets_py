"""Bitcoin-native intermediate records for UTXO processing.

These models sit between provider payloads and the chain-neutral
:mod:`..models` envelope. They are intentionally free of ownership/change
clustering and have no signing or PSBT fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from ..errors import InvalidRequestError
from .amounts import parse_sats
from .networks import BitcoinNetwork
from .scripts import ScriptDescriptor, ScriptType


class TxStatus(StrEnum):
    MEMPOOL = "mempool"
    CONFIRMED = "confirmed"
    REPLACED = "replaced"
    ORPHANED = "orphaned"


@dataclass(frozen=True, slots=True)
class OutPoint:
    """Transaction outpoint (txid, vout)."""

    txid: str
    vout: int

    def __post_init__(self) -> None:
        if not isinstance(self.txid, str) or not self.txid.strip():
            raise InvalidRequestError("txid must not be empty")
        object.__setattr__(self, "txid", self.txid.lower())
        if isinstance(self.vout, bool) or not isinstance(self.vout, int) or self.vout < 0:
            raise InvalidRequestError("vout must be a non-negative integer")

    @property
    def key(self) -> str:
        return f"{self.txid}:{self.vout}"

    def to_dict(self) -> dict[str, Any]:
        return {"txid": self.txid, "vout": self.vout}


@dataclass(frozen=True, slots=True)
class TxInput:
    """One transaction input. Coinbase inputs have ``is_coinbase=True``."""

    previous_output: OutPoint | None
    sequence: int = 0xFFFFFFFF
    script_sig_hex: str | None = None
    witness: tuple[str, ...] = ()
    is_coinbase: bool = False
    descriptor: ScriptDescriptor | None = None

    def __post_init__(self) -> None:
        if self.is_coinbase:
            if self.previous_output is not None:
                raise InvalidRequestError("coinbase input must not reference an outpoint")
        elif self.previous_output is None:
            raise InvalidRequestError("non-coinbase input requires previous_output")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
            or self.sequence > 0xFFFFFFFF
        ):
            raise InvalidRequestError("sequence must be a uint32")
        object.__setattr__(self, "witness", tuple(self.witness))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sequence": self.sequence,
            "is_coinbase": self.is_coinbase,
            "witness": list(self.witness),
        }
        if self.previous_output is not None:
            result["previous_output"] = self.previous_output.to_dict()
        if self.script_sig_hex is not None:
            result["script_sig_hex"] = self.script_sig_hex
        if self.descriptor is not None:
            result["descriptor"] = self.descriptor.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class TxOutput:
    """One transaction output valued in satoshis."""

    n: int
    value_sats: int
    descriptor: ScriptDescriptor
    spent_by: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.n, bool) or not isinstance(self.n, int) or self.n < 0:
            raise InvalidRequestError("output index n must be a non-negative integer")
        object.__setattr__(self, "value_sats", parse_sats(self.value_sats, field="value_sats"))
        if not isinstance(self.descriptor, ScriptDescriptor):
            raise InvalidRequestError("descriptor must be a ScriptDescriptor")
        if self.spent_by is not None and not str(self.spent_by).strip():
            raise InvalidRequestError("spent_by must not be empty when provided")

    @property
    def is_spent(self) -> bool:
        return self.spent_by is not None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "n": self.n,
            "value_sats": self.value_sats,
            "descriptor": self.descriptor.to_dict(),
            "is_spent": self.is_spent,
        }
        if self.spent_by is not None:
            result["spent_by"] = self.spent_by
        return result


@dataclass(frozen=True, slots=True)
class BitcoinTransaction:
    """Normalized Bitcoin transaction prior to chain-neutral projection."""

    txid: str
    inputs: tuple[TxInput, ...]
    outputs: tuple[TxOutput, ...]
    status: TxStatus
    network: BitcoinNetwork
    block_height: int | None = None
    block_hash: str | None = None
    block_time: datetime | None = None
    fee_sats: int | None = None
    weight: int | None = None
    replaces: str | None = None
    replaced_by: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.txid, str) or not self.txid.strip():
            raise InvalidRequestError("txid must not be empty")
        object.__setattr__(self, "txid", self.txid.lower())
        if not self.inputs:
            raise InvalidRequestError("transaction must have at least one input")
        if not self.outputs:
            raise InvalidRequestError("transaction must have at least one output")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        if not isinstance(self.status, TxStatus):
            raise InvalidRequestError("status must be a TxStatus")
        if not isinstance(self.network, BitcoinNetwork):
            raise InvalidRequestError("network must be a BitcoinNetwork")
        if self.block_height is not None and (
            isinstance(self.block_height, bool)
            or not isinstance(self.block_height, int)
            or self.block_height < 0
        ):
            raise InvalidRequestError("block_height must be a non-negative integer")
        if self.block_hash is not None:
            object.__setattr__(self, "block_hash", self.block_hash.lower())
        if self.fee_sats is not None:
            object.__setattr__(self, "fee_sats", parse_sats(self.fee_sats, field="fee_sats"))
        if not isinstance(self.raw, Mapping):
            raise InvalidRequestError("raw must be a mapping")
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))

    @property
    def is_coinbase(self) -> bool:
        return any(item.is_coinbase for item in self.inputs)

    @property
    def is_mempool(self) -> bool:
        return self.status is TxStatus.MEMPOOL

    def outpoint(self, n: int) -> OutPoint:
        return OutPoint(self.txid, n)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "txid": self.txid,
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "status": self.status.value,
            "network": self.network.value,
            "is_coinbase": self.is_coinbase,
        }
        if self.block_height is not None:
            result["block_height"] = self.block_height
        if self.block_hash is not None:
            result["block_hash"] = self.block_hash
        if self.block_time is not None:
            result["block_time"] = self.block_time.isoformat()
        if self.fee_sats is not None:
            result["fee_sats"] = self.fee_sats
        if self.weight is not None:
            result["weight"] = self.weight
        if self.replaces is not None:
            result["replaces"] = self.replaces
        if self.replaced_by is not None:
            result["replaced_by"] = self.replaced_by
        return result


@dataclass(frozen=True, slots=True)
class UtxoEntry:
    """One unspent or spent UTXO tracked by the in-memory set."""

    outpoint: OutPoint
    value_sats: int
    descriptor: ScriptDescriptor
    created_by: str
    created_height: int | None
    spent_by: str | None = None
    spent_height: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outpoint, OutPoint):
            raise InvalidRequestError("outpoint must be an OutPoint")
        object.__setattr__(
            self, "value_sats", parse_sats(self.value_sats, field="value_sats")
        )
        if not isinstance(self.descriptor, ScriptDescriptor):
            raise InvalidRequestError("descriptor must be a ScriptDescriptor")
        if not self.created_by.strip():
            raise InvalidRequestError("created_by must not be empty")

    @property
    def is_spent(self) -> bool:
        return self.spent_by is not None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "outpoint": self.outpoint.to_dict(),
            "value_sats": self.value_sats,
            "descriptor": self.descriptor.to_dict(),
            "created_by": self.created_by,
            "created_height": self.created_height,
            "is_spent": self.is_spent,
        }
        if self.spent_by is not None:
            result["spent_by"] = self.spent_by
        if self.spent_height is not None:
            result["spent_height"] = self.spent_height
        return result


def coinbase_input(*, script_sig_hex: str | None = None) -> TxInput:
    return TxInput(
        previous_output=None,
        is_coinbase=True,
        script_sig_hex=script_sig_hex,
        descriptor=ScriptDescriptor(script_type=ScriptType.COINBASE),
    )


__all__ = [
    "BitcoinTransaction",
    "OutPoint",
    "TxInput",
    "TxOutput",
    "TxStatus",
    "UtxoEntry",
    "coinbase_input",
]
