"""Normalize Bitcoin-native transactions into chain-neutral ledger records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from ..errors import InvalidRequestError, NormalizationError
from ..models import (
    AccountKind,
    AccountRef,
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    UTXORecord,
    VersionedExtension,
)
from ..protocols import Capabilities, Capability, OperationContext
from .amounts import exact_sats, parse_sats
from .finality import BitcoinFinalityPolicy
from .models import BitcoinTransaction, OutPoint, TxInput, TxOutput, TxStatus, coinbase_input
from .networks import (
    BitcoinNetwork,
    assert_chain_matches,
    btc_asset,
    chain_ref_for,
)
from .scripts import ScriptDescriptor, ScriptType, describe_script

EXTENSION_NAMESPACE = "bitcoin"
EXTENSION_SCHEMA = "wallet-bitcoin-tx-v1"
PROVIDER_KIND = "esplora"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_digest(payload: Mapping[str, Any]) -> RawPayloadRef:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return RawPayloadRef(
        digest=f"sha256:{digest}",
        media_type="application/json",
        byte_length=len(body.encode("utf-8")),
    )


def _account_for_descriptor(
    chain,
    descriptor: ScriptDescriptor | None,
) -> AccountRef | None:
    if descriptor is None or descriptor.address is None:
        return None
    kind = AccountKind.SCRIPT if descriptor.script_type is not ScriptType.UNKNOWN else AccountKind.ADDRESS
    if descriptor.script_type in {
        ScriptType.P2PKH,
        ScriptType.P2WPKH,
        ScriptType.P2TR,
    }:
        kind = AccountKind.ADDRESS
    return AccountRef(chain=chain, address=descriptor.address, kind=kind)


def parse_esplora_transaction(
    payload: Mapping[str, Any],
    *,
    network: BitcoinNetwork,
) -> BitcoinTransaction:
    """Parse a Blockstream/Esplora-style transaction JSON object."""

    if not isinstance(payload, Mapping):
        raise NormalizationError("transaction payload must be a mapping")
    txid = str(payload.get("txid") or "").strip().lower()
    if not txid:
        raise NormalizationError("transaction payload missing txid")

    status_obj = payload.get("status") or {}
    confirmed = bool(status_obj.get("confirmed"))
    block_height = status_obj.get("block_height")
    block_hash = status_obj.get("block_hash")
    block_time_raw = status_obj.get("block_time")
    block_time = None
    if block_time_raw is not None:
        block_time = datetime.fromtimestamp(int(block_time_raw), tz=timezone.utc)

    replaces = payload.get("replaces") or payload.get("rbf_replaces")
    replaced_by = payload.get("replaced_by")

    if replaced_by:
        status = TxStatus.REPLACED
    elif confirmed:
        status = TxStatus.CONFIRMED
    else:
        status = TxStatus.MEMPOOL

    inputs: list[TxInput] = []
    for vin in payload.get("vin") or []:
        if not isinstance(vin, Mapping):
            raise NormalizationError("vin entries must be mappings")
        is_coinbase = bool(vin.get("is_coinbase") or vin.get("coinbase"))
        if is_coinbase:
            inputs.append(
                coinbase_input(script_sig_hex=vin.get("scriptsig") or vin.get("script_sig"))
            )
            continue
        prev_txid = str(vin.get("txid") or "").strip().lower()
        vout = vin.get("vout")
        if not prev_txid or vout is None:
            raise NormalizationError(f"input missing outpoint in {txid}")
        prevout = vin.get("prevout") or {}
        address = prevout.get("scriptpubkey_address") or vin.get("address")
        script_hex = prevout.get("scriptpubkey") or vin.get("scriptpubkey")
        descriptor = None
        if address or script_hex:
            descriptor = describe_script(
                script_hex=script_hex,
                address=address,
                network=network,
            )
        witness = tuple(str(item) for item in (vin.get("witness") or ()))
        inputs.append(
            TxInput(
                previous_output=OutPoint(prev_txid, int(vout)),
                sequence=int(vin.get("sequence", 0xFFFFFFFF)),
                script_sig_hex=vin.get("scriptsig") or vin.get("script_sig"),
                witness=witness,
                descriptor=descriptor,
            )
        )

    outputs: list[TxOutput] = []
    for index, vout in enumerate(payload.get("vout") or []):
        if not isinstance(vout, Mapping):
            raise NormalizationError("vout entries must be mappings")
        n = int(vout.get("n", index))
        # Esplora uses "value" in sats.
        value = vout.get("value")
        if value is None:
            raise NormalizationError(f"output {n} missing value")
        address = vout.get("scriptpubkey_address")
        script_hex = vout.get("scriptpubkey")
        descriptor = describe_script(
            script_hex=script_hex,
            address=address,
            network=network,
        )
        spent_by = vout.get("spent_by")
        outputs.append(
            TxOutput(
                n=n,
                value_sats=parse_sats(value, field=f"vout[{n}].value"),
                descriptor=descriptor,
                spent_by=str(spent_by) if spent_by else None,
            )
        )

    fee = payload.get("fee")
    fee_sats = parse_sats(fee, field="fee") if fee is not None else None
    weight = payload.get("weight")

    return BitcoinTransaction(
        txid=txid,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        status=status,
        network=network,
        block_height=int(block_height) if block_height is not None else None,
        block_hash=str(block_hash).lower() if block_hash else None,
        block_time=block_time,
        fee_sats=fee_sats,
        weight=int(weight) if weight is not None else None,
        replaces=str(replaces).lower() if replaces else None,
        replaced_by=str(replaced_by).lower() if replaced_by else None,
        raw=dict(payload),
    )


@dataclass
class BitcoinNormalizer:
    """Pure conversion from Bitcoin-native values to versioned domain records."""

    network: BitcoinNetwork = BitcoinNetwork.MAINNET
    provider: str = "bitcoin-esplora"
    finality_policy: BitcoinFinalityPolicy | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.network, BitcoinNetwork):
            raise InvalidRequestError("network must be a BitcoinNetwork")
        self._chain = chain_ref_for(self.network)
        self._asset = btc_asset(self._chain)
        self._finality = self.finality_policy or BitcoinFinalityPolicy(network=self.network)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider=self.provider,
            chain_namespaces=frozenset({self._chain.namespace}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.BALANCES,
                    Capability.FINALITY,
                }
            ),
            metadata={
                "network": self.network.value,
                "provider_family": PROVIDER_KIND,
                "utxo_model": True,
                "ownership_clustering": False,
            },
        )

    @property
    def chain(self):
        return self._chain

    def normalize(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
        head_height: int | None = None,
        scope: str | None = None,
    ) -> Sequence[object]:
        """Normalize a bounded batch without performing I/O."""

        context.check_active()
        if len(records) > context.limits.max_items:
            raise InvalidRequestError("normalize batch exceeds max_items")
        observed = self.observed_at or _utc_now()
        request_scope = scope or context.request_id
        out: list[object] = []
        for item in records:
            tx = self._coerce_tx(item)
            out.extend(
                self._project_tx(
                    tx,
                    context=context,
                    observed_at=observed,
                    scope=request_scope,
                    head_height=head_height,
                )
            )
        return tuple(out)

    def _coerce_tx(self, item: object) -> BitcoinTransaction:
        if isinstance(item, BitcoinTransaction):
            if item.network is not self.network:
                raise NormalizationError(
                    f"transaction network {item.network.value} does not match "
                    f"normalizer network {self.network.value}"
                )
            return item
        if isinstance(item, Mapping):
            return parse_esplora_transaction(item, network=self.network)
        raise NormalizationError(
            f"unsupported Bitcoin native record type: {type(item)!r}"
        )

    def _finality_for(self, tx: BitcoinTransaction, head_height: int | None) -> Finality:
        if tx.status is TxStatus.REPLACED:
            return Finality.REVERTED
        if tx.status is TxStatus.ORPHANED:
            return Finality.ORPHANED
        if tx.status is TxStatus.MEMPOOL or tx.block_height is None:
            return Finality.PENDING
        if head_height is None:
            return Finality.OBSERVED
        confirmations = max(0, head_height - tx.block_height)
        return self._finality.finality_for_confirmations(confirmations)

    def _project_tx(
        self,
        tx: BitcoinTransaction,
        *,
        context: OperationContext,
        observed_at: datetime,
        scope: str,
        head_height: int | None,
    ) -> list[object]:
        assert_chain_matches(self._chain, self.network)
        finality = self._finality_for(tx, head_height)
        position = LedgerPosition(
            sequence=tx.block_height,
            hash=tx.block_hash,
            transaction_index=None,
        )
        raw_payload = _payload_digest(dict(tx.raw)) if tx.raw else None
        provenance = Provenance(
            provider=self.provider,
            provider_kind=PROVIDER_KIND,
            request_id=context.request_id,
            scope=scope,
            observed_at=observed_at,
            raw_payload=raw_payload,
        )
        participants: list[AccountRef] = []
        seen: set[str] = set()
        for vin in tx.inputs:
            account = _account_for_descriptor(self._chain, vin.descriptor)
            if account is not None and account.address not in seen:
                participants.append(account)
                seen.add(account.address)
        for vout in tx.outputs:
            account = _account_for_descriptor(self._chain, vout.descriptor)
            if account is not None and account.address not in seen:
                participants.append(account)
                seen.add(account.address)

        fee = exact_sats(tx.fee_sats) if tx.fee_sats is not None else None
        extension = VersionedExtension(
            schema_version=EXTENSION_SCHEMA,
            data={
                "txid": tx.txid,
                "is_coinbase": tx.is_coinbase,
                "status": tx.status.value,
                "fee_sats": tx.fee_sats,
                "weight": tx.weight,
                "replaces": tx.replaces,
                "replaced_by": tx.replaced_by,
                "input_count": len(tx.inputs),
                "output_count": len(tx.outputs),
                "ownership_clustering": False,
            },
        )

        status = (
            TransactionStatus.SUCCEEDED
            if tx.status in {TxStatus.CONFIRMED, TxStatus.MEMPOOL}
            else TransactionStatus.FAILED
        )
        records: list[object] = [
            TransactionRecord(
                chain=self._chain,
                provenance=provenance,
                ledger_position=position,
                finality=finality,
                extensions={EXTENSION_NAMESPACE: extension},
                transaction_hash=tx.txid,
                status=status,
                participants=tuple(participants),
                fee=fee,
                block_time=tx.block_time,
            )
        ]

        transfer_index = 0
        if tx.is_coinbase:
            for vout in tx.outputs:
                dest = _account_for_descriptor(self._chain, vout.descriptor)
                records.append(
                    TransferRecord(
                        chain=self._chain,
                        provenance=provenance,
                        ledger_position=position,
                        finality=finality,
                        extensions={EXTENSION_NAMESPACE: extension},
                        transaction_hash=tx.txid,
                        transfer_index=transfer_index,
                        asset=self._asset,
                        amount=exact_sats(vout.value_sats),
                        source_account=None,
                        destination_account=dest,
                        transfer_kind=TransferKind.REWARD,
                    )
                )
                transfer_index += 1
        else:
            # Emit one transfer per output. Inputs consume UTXOs; we do not
            # invent account-style debits.
            for vout in tx.outputs:
                dest = _account_for_descriptor(self._chain, vout.descriptor)
                records.append(
                    TransferRecord(
                        chain=self._chain,
                        provenance=provenance,
                        ledger_position=position,
                        finality=finality,
                        extensions={EXTENSION_NAMESPACE: extension},
                        transaction_hash=tx.txid,
                        transfer_index=transfer_index,
                        asset=self._asset,
                        amount=exact_sats(vout.value_sats),
                        source_account=None,
                        destination_account=dest,
                        transfer_kind=TransferKind.NATIVE,
                    )
                )
                transfer_index += 1
            if fee is not None and fee.base_units != "0":
                records.append(
                    TransferRecord(
                        chain=self._chain,
                        provenance=provenance,
                        ledger_position=position,
                        finality=finality,
                        extensions={EXTENSION_NAMESPACE: extension},
                        transaction_hash=tx.txid,
                        transfer_index=transfer_index,
                        asset=self._asset,
                        amount=fee,
                        source_account=None,
                        destination_account=None,
                        transfer_kind=TransferKind.FEE,
                    )
                )
                transfer_index += 1

        for vout in tx.outputs:
            owner = _account_for_descriptor(self._chain, vout.descriptor)
            records.append(
                UTXORecord(
                    chain=self._chain,
                    provenance=provenance,
                    ledger_position=position,
                    finality=finality,
                    extensions={
                        EXTENSION_NAMESPACE: VersionedExtension(
                            schema_version=EXTENSION_SCHEMA,
                            data={
                                "script": vout.descriptor.to_dict(),
                                "created_by": tx.txid,
                            },
                        )
                    },
                    transaction_hash=tx.txid,
                    output_index=vout.n,
                    asset=self._asset,
                    amount=exact_sats(vout.value_sats),
                    owner=owner,
                    spent_by_transaction_hash=vout.spent_by,
                )
            )

        # Spent-side UTXO projections for non-coinbase inputs (state driven by
        # outpoints, not account balances).
        if not tx.is_coinbase:
            for vin in tx.inputs:
                assert vin.previous_output is not None
                prev = vin.previous_output
                # Value may be unknown without prevout; skip amount-bearing spent
                # records when absent. Still emit a zero-value spent marker only
                # when prevout value is present on the descriptor payload.
                value = None
                if vin.descriptor is not None and isinstance(tx.raw, Mapping):
                    # Prefer prevout value from raw vin if present.
                    pass
                # Search raw vin for prevout value.
                for raw_vin in tx.raw.get("vin") or ():
                    if not isinstance(raw_vin, Mapping):
                        continue
                    if (
                        str(raw_vin.get("txid", "")).lower() == prev.txid
                        and int(raw_vin.get("vout", -1)) == prev.vout
                    ):
                        prevout = raw_vin.get("prevout") or {}
                        if "value" in prevout:
                            value = parse_sats(prevout["value"], field="prevout.value")
                        break
                if value is None:
                    continue
                owner = _account_for_descriptor(self._chain, vin.descriptor)
                records.append(
                    UTXORecord(
                        chain=self._chain,
                        provenance=provenance,
                        ledger_position=position,
                        finality=finality,
                        extensions={
                            EXTENSION_NAMESPACE: VersionedExtension(
                                schema_version=EXTENSION_SCHEMA,
                                data={
                                    "script": (
                                        vin.descriptor.to_dict()
                                        if vin.descriptor
                                        else None
                                    ),
                                    "spent_in": tx.txid,
                                },
                            )
                        },
                        transaction_hash=prev.txid,
                        output_index=prev.vout,
                        asset=self._asset,
                        amount=exact_sats(value),
                        owner=owner,
                        spent_by_transaction_hash=tx.txid,
                    )
                )

        return records


__all__ = [
    "EXTENSION_NAMESPACE",
    "EXTENSION_SCHEMA",
    "PROVIDER_KIND",
    "BitcoinNormalizer",
    "parse_esplora_transaction",
]
