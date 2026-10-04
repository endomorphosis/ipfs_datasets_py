"""UTXO-set state machine: create, spend, replace, and reorg reverse.

Balances are derived exclusively from unspent outputs. Account-style debits
are never used. Ownership/change clustering across addresses is not asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..errors import InvalidRequestError, NormalizationError
from .models import BitcoinTransaction, OutPoint, TxStatus, UtxoEntry
from .scripts import ScriptDescriptor


@dataclass
class UtxoApplyResult:
    created: tuple[OutPoint, ...]
    spent: tuple[OutPoint, ...]
    already_spent: tuple[OutPoint, ...] = ()
    missing_inputs: tuple[OutPoint, ...] = ()
    replaced: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": [o.to_dict() for o in self.created],
            "spent": [o.to_dict() for o in self.spent],
            "already_spent": [o.to_dict() for o in self.already_spent],
            "missing_inputs": [o.to_dict() for o in self.missing_inputs],
            "replaced": self.replaced,
        }


class UtxoSet:
    """In-memory UTXO set for fixture-driven and offline ingestion paths."""

    def __init__(self) -> None:
        self._entries: dict[str, UtxoEntry] = {}
        self._applied: dict[str, BitcoinTransaction] = {}
        self._height_index: dict[int, list[str]] = {}

    def __len__(self) -> int:
        return sum(1 for entry in self._entries.values() if not entry.is_spent)

    def get(self, outpoint: OutPoint | str) -> UtxoEntry | None:
        key = outpoint if isinstance(outpoint, str) else outpoint.key
        return self._entries.get(key)

    def unspent(self) -> tuple[UtxoEntry, ...]:
        return tuple(e for e in self._entries.values() if not e.is_spent)

    def unspent_for_address(self, address: str) -> tuple[UtxoEntry, ...]:
        if not address.strip():
            raise InvalidRequestError("address must not be empty")
        return tuple(
            e
            for e in self.unspent()
            if e.descriptor.address is not None and e.descriptor.address == address
        )

    def balance_sats(self, address: str | None = None) -> int:
        """Sum unspent satoshis. Optional address filter is exact-match only."""

        entries: Iterable[UtxoEntry]
        if address is None:
            entries = self.unspent()
        else:
            entries = self.unspent_for_address(address)
        return sum(entry.value_sats for entry in entries)

    def balances_by_address(self) -> Mapping[str, int]:
        """Exact per-address balances. No clustering of related addresses."""

        totals: dict[str, int] = {}
        for entry in self.unspent():
            address = entry.descriptor.address
            if address is None:
                continue
            totals[address] = totals.get(address, 0) + entry.value_sats
        return dict(sorted(totals.items()))

    def apply_transaction(
        self,
        tx: BitcoinTransaction,
        *,
        allow_missing_inputs: bool = False,
        mark_replaced: str | None = None,
    ) -> UtxoApplyResult:
        """Create outputs and spend inputs for *tx*.

        When *tx* replaces another mempool transaction, pass ``mark_replaced``
        with the previous txid so its created outputs are dropped and its
        spends are restored.
        """

        if not isinstance(tx, BitcoinTransaction):
            raise InvalidRequestError("tx must be a BitcoinTransaction")
        if tx.txid in self._applied and self._applied[tx.txid].status is not TxStatus.REPLACED:
            raise NormalizationError(f"transaction already applied: {tx.txid}")

        replaced: str | None = None
        if mark_replaced or tx.replaces:
            victim = mark_replaced or tx.replaces
            assert victim is not None
            self._replace_mempool_tx(victim, replacement=tx.txid)
            replaced = victim

        missing: list[OutPoint] = []
        already_spent: list[OutPoint] = []
        spent: list[OutPoint] = []

        if not tx.is_coinbase:
            for vin in tx.inputs:
                assert vin.previous_output is not None
                entry = self._entries.get(vin.previous_output.key)
                if entry is None:
                    missing.append(vin.previous_output)
                    continue
                if entry.is_spent:
                    already_spent.append(vin.previous_output)
                    continue
                self._entries[vin.previous_output.key] = UtxoEntry(
                    outpoint=entry.outpoint,
                    value_sats=entry.value_sats,
                    descriptor=entry.descriptor,
                    created_by=entry.created_by,
                    created_height=entry.created_height,
                    spent_by=tx.txid,
                    spent_height=tx.block_height,
                )
                spent.append(vin.previous_output)

        if missing and not allow_missing_inputs:
            raise NormalizationError(
                f"missing inputs for {tx.txid}: "
                + ", ".join(item.key for item in missing)
            )

        created: list[OutPoint] = []
        for vout in tx.outputs:
            outpoint = OutPoint(tx.txid, vout.n)
            self._entries[outpoint.key] = UtxoEntry(
                outpoint=outpoint,
                value_sats=vout.value_sats,
                descriptor=vout.descriptor,
                created_by=tx.txid,
                created_height=tx.block_height,
                spent_by=vout.spent_by,
                spent_height=None,
            )
            created.append(outpoint)

        self._applied[tx.txid] = tx
        if tx.block_height is not None:
            self._height_index.setdefault(tx.block_height, []).append(tx.txid)

        return UtxoApplyResult(
            created=tuple(created),
            spent=tuple(spent),
            already_spent=tuple(already_spent),
            missing_inputs=tuple(missing),
            replaced=replaced,
        )

    def reverse_transaction(self, txid: str) -> UtxoApplyResult:
        """Undo a previously applied transaction (reorg path)."""

        tx = self._applied.get(txid)
        if tx is None:
            raise NormalizationError(f"cannot reverse unknown transaction: {txid}")

        # Remove created outputs (must be unspent or spent only by later txs we
        # expect the caller to reverse first in descending height order).
        removed: list[OutPoint] = []
        for vout in tx.outputs:
            outpoint = OutPoint(tx.txid, vout.n)
            entry = self._entries.get(outpoint.key)
            if entry is None:
                continue
            if entry.is_spent:
                raise NormalizationError(
                    f"cannot reverse {txid}: output {outpoint.key} still spent by "
                    f"{entry.spent_by}"
                )
            del self._entries[outpoint.key]
            removed.append(outpoint)

        restored: list[OutPoint] = []
        if not tx.is_coinbase:
            for vin in tx.inputs:
                assert vin.previous_output is not None
                entry = self._entries.get(vin.previous_output.key)
                if entry is None:
                    continue
                if entry.spent_by != txid:
                    continue
                self._entries[vin.previous_output.key] = UtxoEntry(
                    outpoint=entry.outpoint,
                    value_sats=entry.value_sats,
                    descriptor=entry.descriptor,
                    created_by=entry.created_by,
                    created_height=entry.created_height,
                    spent_by=None,
                    spent_height=None,
                )
                restored.append(vin.previous_output)

        del self._applied[txid]
        if tx.block_height is not None:
            bucket = self._height_index.get(tx.block_height, [])
            self._height_index[tx.block_height] = [t for t in bucket if t != txid]

        return UtxoApplyResult(created=tuple(removed), spent=tuple(restored))

    def reverse_from_height(self, height: int) -> tuple[str, ...]:
        """Reverse all applied transactions at height >= *height* (descending)."""

        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise InvalidRequestError("height must be a non-negative integer")
        heights = sorted(
            (h for h in self._height_index if h >= height),
            reverse=True,
        )
        reversed_txids: list[str] = []
        for h in heights:
            for txid in list(reversed(self._height_index.get(h, ()))):
                self.reverse_transaction(txid)
                reversed_txids.append(txid)
        return tuple(reversed_txids)

    def _replace_mempool_tx(self, txid: str, *, replacement: str) -> None:
        tx = self._applied.get(txid)
        if tx is None:
            return
        if tx.status is TxStatus.CONFIRMED:
            raise NormalizationError("cannot replace a confirmed transaction")
        # Undo effects of the replaced mempool tx.
        self.reverse_transaction(txid)
        # Record replaced stub so scanners can observe replacement.
        self._applied[txid] = BitcoinTransaction(
            txid=tx.txid,
            inputs=tx.inputs,
            outputs=tx.outputs,
            status=TxStatus.REPLACED,
            network=tx.network,
            block_height=None,
            block_hash=None,
            fee_sats=tx.fee_sats,
            replaces=tx.replaces,
            replaced_by=replacement,
            raw=dict(tx.raw),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "unspent": [e.to_dict() for e in self.unspent()],
            "balances_by_address": self.balances_by_address(),
            "applied_txids": sorted(self._applied),
        }


def seed_utxo(
    utxo_set: UtxoSet,
    *,
    txid: str,
    vout: int,
    value_sats: int,
    descriptor: ScriptDescriptor,
    height: int | None = None,
) -> OutPoint:
    """Insert a pre-existing unspent output (for fixture bootstrap)."""

    outpoint = OutPoint(txid, vout)
    utxo_set._entries[outpoint.key] = UtxoEntry(  # noqa: SLF001 - test/fixture helper
        outpoint=outpoint,
        value_sats=value_sats,
        descriptor=descriptor,
        created_by=txid,
        created_height=height,
    )
    return outpoint


__all__ = [
    "UtxoApplyResult",
    "UtxoSet",
    "seed_utxo",
]
