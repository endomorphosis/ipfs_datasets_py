from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.wallets.errors import ResourceLimitError
from ipfs_datasets_py.processors.wallets.models import (
    AssetKind,
    ContractEventRecord,
    Finality,
    TokenAccountRecord,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.solana import (
    Commitment,
    SOLANA_MAINNET,
    SolanaFinalityPolicy,
    SolanaNormalizer,
    SolanaTransactionBundle,
    TokenMetadata,
)


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _context(max_items: int = 100) -> OperationContext:
    return OperationContext(
        "solana-normalizer",
        limits=RequestLimits(max_items=max_items),
    )


def _bundle(
    rpc_session: dict,
    signature_name: str,
    *,
    commitment: Commitment = Commitment.FINALIZED,
) -> SolanaTransactionBundle:
    signature = rpc_session["signatures"][signature_name]
    native = rpc_session["transactions"][signature]
    slot = native["slot"]
    return SolanaTransactionBundle(
        transaction={
            "transaction": deepcopy(native["transaction"]),
            "meta": deepcopy(native["meta"]),
            "version": native["version"],
        },
        slot=slot,
        blockhash=rpc_session["blocks"][str(slot)]["blockhash"],
        block_time=native["blockTime"],
        commitment=commitment,
    )


def _normalizer(**kwargs: object) -> SolanaNormalizer:
    return SolanaNormalizer(
        SOLANA_MAINNET,
        clock=lambda: NOW,
        **kwargs,
    )


def test_versioned_tx_inner_outer_lamport_spl_and_token_balances(
    rpc_session: dict,
) -> None:
    records = _normalizer().normalize(
        (_bundle(rpc_session, "versioned"),), context=_context()
    )
    transaction = next(item for item in records if isinstance(item, TransactionRecord))
    assert transaction.status is TransactionStatus.SUCCEEDED
    assert transaction.finality is Finality.FINALIZED
    assert transaction.extensions["solana"].data["version"] == 0
    assert len(transaction.extensions["solana"].data["address_lookup_tables"]) == 1
    assert transaction.extensions["solana"].data["program_log_count"] == 5
    assert "program_logs" not in transaction.extensions["solana"].data

    events = [item for item in records if isinstance(item, ContractEventRecord)]
    assert [item.event_index for item in events] == [0, 1, 2]
    coordinates = [
        (
            item.extensions["solana"].data["outer_index"],
            item.extensions["solana"].data["inner_index"],
        )
        for item in events
    ]
    assert coordinates == [(0, None), (0, 0), (1, None)]
    assert len({item.record_id for item in events}) == 3

    transfers = [item for item in records if isinstance(item, TransferRecord)]
    assert [
        (item.transfer_kind, item.amount.base_units, item.amount.decimals)
        for item in transfers
    ] == [
        (TransferKind.NATIVE, "18446744073709551615", 9),
        (TransferKind.NATIVE, "42", 9),
        (TransferKind.TOKEN, "900719925474099312345", 6),
    ]
    token_accounts = [
        item for item in records if isinstance(item, TokenAccountRecord)
    ]
    assert [item.amount.base_units for item in token_accounts] == [
        "0",
        "900719925474099312345",
    ]
    assert all(
        item.asset.kind is AssetKind.FUNGIBLE_TOKEN for item in token_accounts
    )
    assert all(record.to_dict()["record_id"] == record.record_id for record in records)


def test_failed_transaction_is_visible_but_rolled_back_transfer_is_not_emitted(
    rpc_session: dict,
) -> None:
    records = _normalizer().normalize(
        (_bundle(rpc_session, "failed_legacy"),), context=_context()
    )
    transaction = next(item for item in records if isinstance(item, TransactionRecord))
    assert transaction.status is TransactionStatus.FAILED
    assert transaction.finality is Finality.FINALIZED
    assert transaction.extensions["solana"].data["failed"] is True
    assert any(isinstance(item, ContractEventRecord) for item in records)
    assert not any(isinstance(item, TransferRecord) for item in records)


@pytest.mark.parametrize(
    ("commitment", "expected"),
    [
        (Commitment.PROCESSED, Finality.OBSERVED),
        (Commitment.CONFIRMED, Finality.CONFIRMED),
        (Commitment.FINALIZED, Finality.FINALIZED),
    ],
)
def test_commitment_states_remain_distinct(
    rpc_session: dict,
    commitment: Commitment,
    expected: Finality,
) -> None:
    records = _normalizer().normalize(
        (_bundle(rpc_session, "failed_legacy", commitment=commitment),),
        context=_context(),
    )
    transaction = next(item for item in records if isinstance(item, TransactionRecord))
    assert transaction.finality is expected
    assert SolanaFinalityPolicy.state_for(commitment) is expected


def test_program_logs_are_opt_in_and_bounded(rpc_session: dict) -> None:
    included = _normalizer(include_program_logs=True).normalize(
        (_bundle(rpc_session, "failed_legacy"),), context=_context()
    )
    transaction = next(item for item in included if isinstance(item, TransactionRecord))
    assert len(transaction.extensions["solana"].data["program_logs"]) == 2

    with pytest.raises(ResourceLimitError, match="max_program_logs"):
        _normalizer(max_program_logs=1).normalize(
            (_bundle(rpc_session, "failed_legacy"),), context=_context()
        )


def test_nft_enrichment_is_optional_projection_over_token_records(
    rpc_session: dict,
) -> None:
    mint = rpc_session["addresses"]["mint"]
    core = _normalizer().normalize(
        (_bundle(rpc_session, "versioned"),), context=_context()
    )
    assert all(
        item.asset.kind is AssetKind.FUNGIBLE_TOKEN
        for item in core
        if isinstance(item, TokenAccountRecord)
    )
    enriched = _normalizer(
        token_metadata={
            mint: TokenMetadata(
                decimals=6,
                symbol="OPTIONAL-NFT",
                kind=AssetKind.NON_FUNGIBLE_TOKEN,
            )
        }
    ).normalize((_bundle(rpc_session, "versioned"),), context=_context())
    assert all(
        item.asset.kind is AssetKind.NON_FUNGIBLE_TOKEN
        for item in enriched
        if isinstance(item, TokenAccountRecord)
    )
    assert all(
        item.extensions["solana"].data["nft_enrichment_applied"] is True
        for item in enriched
        if isinstance(item, TokenAccountRecord)
    )


def test_normalized_output_obeys_item_budget(rpc_session: dict) -> None:
    with pytest.raises(ResourceLimitError, match="max_items"):
        _normalizer().normalize(
            (_bundle(rpc_session, "versioned"),), context=_context(max_items=5)
        )
