from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.wallets.errors import NormalizationError
from ipfs_datasets_py.processors.wallets.ethereum import (
    ETHEREUM_MAINNET,
    EthereumNormalizer,
    EvmBlockBundle,
    TokenMetadata,
    decode_transfer_log,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    ContractEventRecord,
    Finality,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RequestLimits,
)


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _context() -> OperationContext:
    return OperationContext(
        "normalize-ethereum",
        limits=RequestLimits(max_items=100, max_response_bytes=2_000_000),
    )


def _bundle(session: Mapping[str, object], *, traces: bool = False) -> EvmBlockBundle:
    receipts = session["receipts"]
    assert isinstance(receipts, Mapping)
    trace_map = session["traces"] if traces else {}
    assert isinstance(trace_map, Mapping)
    return EvmBlockBundle(
        block=session["block"],  # type: ignore[arg-type]
        receipts=tuple(receipts.values()),  # type: ignore[arg-type]
        traces={
            str(tx_hash): tuple(value)  # type: ignore[arg-type]
            for tx_hash, value in trace_map.items()
        },
        trace_capability=traces,
    )


def _normalizer(
    metadata: Mapping[str, TokenMetadata] | None = None,
) -> EthereumNormalizer:
    return EthereumNormalizer(
        ETHEREUM_MAINNET,
        token_metadata=metadata,
        clock=lambda: NOW,
    )


def test_legacy_eip1559_receipts_reverts_and_contract_creation_are_preserved(
    rpc_session: Mapping[str, object],
) -> None:
    records = _normalizer().normalize((_bundle(rpc_session),), context=_context())
    transactions = [
        record for record in records if isinstance(record, TransactionRecord)
    ]
    assert len(transactions) == 3
    legacy, reverted, creation = transactions
    assert legacy.status is TransactionStatus.SUCCEEDED
    assert legacy.fee.base_units == str(21_000 * 20_000_000_000)
    assert legacy.extensions["ethereum"].data["transaction_type"] == 0
    assert reverted.status is TransactionStatus.FAILED
    assert reverted.finality is Finality.REVERTED
    assert reverted.fee.base_units == str(25_000 * 1_500_000_000)
    assert reverted.extensions["ethereum"].data["max_fee_per_gas"] == "2000000000"
    assert creation.participants[-1].kind is AccountKind.CONTRACT
    assert (
        creation.extensions["ethereum"].data["contract_address"]
        == "0x" + "dd" * 20
    )


def test_native_values_are_exact_and_failed_value_is_not_hidden(
    rpc_session: Mapping[str, object],
) -> None:
    records = _normalizer().normalize((_bundle(rpc_session),), context=_context())
    native = [
        record
        for record in records
        if isinstance(record, TransferRecord)
        and record.asset.asset_namespace == "slip44"
        and not record.extensions["ethereum"].data.get("internal")
    ]
    assert [record.amount.base_units for record in native] == [
        str(10**18),
        str(2 * 10**18),
    ]
    assert native[0].finality is Finality.OBSERVED
    assert native[1].finality is Finality.REVERTED
    assert all(not isinstance(record.amount.base_units, float) for record in native)


def test_erc20_erc721_and_erc1155_logs_decode_without_metadata(
    rpc_session: Mapping[str, object],
) -> None:
    records = _normalizer().normalize((_bundle(rpc_session),), context=_context())
    tokens = [
        record
        for record in records
        if isinstance(record, TransferRecord)
        and record.asset.asset_namespace in {"erc20", "erc721", "erc1155"}
    ]
    assert [record.asset.asset_namespace for record in tokens] == [
        "erc20",
        "erc721",
        "erc1155",
        "erc1155",
        "erc1155",
    ]
    assert [record.amount.base_units for record in tokens] == [
        "1000",
        "1",
        "3",
        "5",
        "6",
    ]
    erc20 = tokens[0]
    assert erc20.asset.decimals == 0
    assert (
        erc20.extensions["ethereum"].data["token_metadata_complete"] is False
    )
    assert erc20.extensions["ethereum"].data["base_units_exact"] is True
    erc721 = tokens[1]
    assert erc721.transfer_kind is TransferKind.MINT
    assert erc721.source_account is None
    assert erc721.asset.asset_reference.endswith("/token/42")


def test_optional_token_metadata_changes_display_precision_not_ingestion(
    rpc_session: Mapping[str, object],
) -> None:
    erc20_address = "0x" + "aa" * 20
    metadata = {erc20_address: TokenMetadata(decimals=6, symbol="SYN")}
    records = _normalizer(metadata).normalize(
        (_bundle(rpc_session),), context=_context()
    )
    erc20 = next(
        record
        for record in records
        if isinstance(record, TransferRecord)
        and record.asset.asset_namespace == "erc20"
    )
    assert erc20.amount.base_units == "1000"
    assert erc20.amount.decimals == 6
    assert erc20.asset.symbol == "SYN"
    assert erc20.extensions["ethereum"].data["token_metadata_complete"] is True


def test_removed_logs_and_event_ids_are_preserved_and_stable(
    rpc_session: Mapping[str, object],
) -> None:
    normalizer = _normalizer()
    first = normalizer.normalize((_bundle(rpc_session),), context=_context())
    second = normalizer.normalize((_bundle(rpc_session),), context=_context())
    first_events = [
        record for record in first if isinstance(record, ContractEventRecord)
    ]
    second_events = [
        record for record in second if isinstance(record, ContractEventRecord)
    ]
    assert [record.record_id for record in first_events] == [
        record.record_id for record in second_events
    ]
    assert len(set(record.record_id for record in first_events)) == 4
    removed = next(record for record in first_events if record.event_index == 3)
    assert removed.finality is Finality.ORPHANED
    assert removed.extensions["ethereum"].data["removed"] is True
    removed_transfers = [
        record
        for record in first
        if isinstance(record, TransferRecord)
        and record.extensions["ethereum"].data.get("removed") is True
    ]
    assert len(removed_transfers) == 2
    assert all(record.finality is Finality.ORPHANED for record in removed_transfers)


def test_trace_capability_emits_internal_value_or_labels_incomplete(
    rpc_session: Mapping[str, object],
) -> None:
    absent = _normalizer().normalize((_bundle(rpc_session),), context=_context())
    absent_tx = next(
        record for record in absent if isinstance(record, TransactionRecord)
    )
    assert absent_tx.extensions["ethereum"].data["trace_capability"] is False
    assert absent_tx.extensions["ethereum"].data["internal_value_complete"] is False

    traced = _normalizer().normalize(
        (_bundle(rpc_session, traces=True),), context=_context()
    )
    internal = [
        record
        for record in traced
        if isinstance(record, TransferRecord)
        and record.extensions["ethereum"].data.get("internal") is True
    ]
    assert len(internal) == 1
    assert internal[0].amount.base_units == "42"
    assert internal[0].transfer_index % 3 == 2


def test_recognized_malformed_token_log_fails_closed(
    rpc_session: Mapping[str, object],
) -> None:
    receipts = rpc_session["receipts"]
    assert isinstance(receipts, Mapping)
    receipt = next(iter(receipts.values()))
    log = receipt["logs"][0]  # type: ignore[index]
    malformed = {**log, "data": "0x01"}  # type: ignore[arg-type]
    with pytest.raises(NormalizationError, match="ABI word"):
        decode_transfer_log(malformed)
