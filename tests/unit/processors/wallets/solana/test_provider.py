from __future__ import annotations

import asyncio

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    ResourceLimitError,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.solana import (
    Commitment,
    MissingSolanaSlotError,
    SOLANA_MAINNET,
    SolanaIdentityError,
    SolanaLedgerProvider,
    SolanaNetwork,
)

from ._helpers import FixtureSolanaRpc


def _context(
    *,
    max_items: int = 100,
    max_pages: int = 10,
    max_requests: int = 30,
) -> OperationContext:
    return OperationContext(
        "solana-unit",
        limits=RequestLimits(
            max_items=max_items,
            max_pages=max_pages,
            max_requests=max_requests,
            max_response_bytes=2_000_000,
        ),
    )


def _provider(rpc_session: dict) -> tuple[SolanaLedgerProvider, FixtureSolanaRpc]:
    transport = FixtureSolanaRpc(rpc_session)
    return (
        SolanaLedgerProvider(
            transport,
            endpoint="https://fixture.invalid/private-key-in-url",
            network=SOLANA_MAINNET,
        ),
        transport,
    )


def test_genesis_binds_provider_to_cluster(rpc_session: dict) -> None:
    provider, transport = _provider(rpc_session)
    chain = asyncio.run(provider.validate_identity(context=_context()))
    assert chain == SOLANA_MAINNET.to_chain_ref()
    assert [call[0] for call in transport.calls] == ["getGenesisHash"]

    wrong = SolanaNetwork(
        network="wrong",
        chain_id="wrong",
        genesis_hash="foreign-genesis",
    )
    with pytest.raises(SolanaIdentityError, match="genesis"):
        asyncio.run(
            SolanaLedgerProvider(
                FixtureSolanaRpc(rpc_session),
                endpoint="https://fixture.invalid",
                network=wrong,
            ).validate_identity(context=_context())
        )


def test_signature_pagination_has_no_duplicates_and_keeps_failed_tx(
    rpc_session: dict,
) -> None:
    provider, _transport = _provider(rpc_session)

    async def collect() -> list:
        request = BoundedRequest(
            scope=rpc_session["addresses"]["alice"],
            context=_context(),
            options={"page_size": 2, "commitment": "finalized"},
        )
        return [batch async for batch in provider.ingest_wallet(request)]

    batches = asyncio.run(collect())
    assert len(batches) == 1
    bundles = batches[0].records
    signatures = [
        bundle.transaction["transaction"]["signatures"][0] for bundle in bundles
    ]
    assert signatures == [
        rpc_session["signatures"]["versioned"],
        rpc_session["signatures"]["failed_legacy"],
    ]
    assert len(signatures) == len(set(signatures))
    assert bundles[1].transaction["meta"]["err"] is not None
    # Wallet records are anchored to their containing block, not recentBlockhash.
    assert bundles[0].blockhash == rpc_session["blocks"]["100"]["blockhash"]
    assert bundles[1].blockhash == rpc_session["blocks"]["99"]["blockhash"]


def test_commitment_heads_and_finalized_checkpoint_have_hash_anchor(
    rpc_session: dict,
) -> None:
    provider, _transport = _provider(rpc_session)
    head = asyncio.run(provider.ledger_head(context=_context()))
    assert (
        head.processed_slot,
        head.confirmed_slot,
        head.finalized_slot,
    ) == (105, 103, 100)
    assert head.finalized_blockhash == rpc_session["blocks"]["100"]["blockhash"]
    checkpoint = asyncio.run(
        provider.finalized_checkpoint(
            f"wallet:{rpc_session['addresses']['alice']}",
            context=_context(),
            continuation_token=rpc_session["signatures"]["failed_legacy"],
        )
    )
    assert checkpoint.anchor.sequence == 100
    assert checkpoint.anchor.block_hash == rpc_session["blocks"]["100"]["blockhash"]
    assert checkpoint.metadata["commitment"] == "finalized"
    assert checkpoint.continuation_token != checkpoint.anchor.block_hash


def test_skipped_slot_never_yields_or_advances(rpc_session: dict) -> None:
    provider, _transport = _provider(rpc_session)

    async def collect() -> list:
        request = BoundedRequest(
            scope="ledger",
            context=_context(),
            start_position=101,
            end_position=101,
        )
        return [batch async for batch in provider.ingest_ledger(request)]

    with pytest.raises(MissingSolanaSlotError, match="checkpoint was not advanced"):
        asyncio.run(collect())


def test_ranges_requests_and_history_items_are_bounded(rpc_session: dict) -> None:
    provider, _transport = _provider(rpc_session)

    async def over_range() -> None:
        request = BoundedRequest(
            scope="ledger",
            context=_context(max_pages=1),
            start_position=99,
            end_position=100,
        )
        async for _ in provider.ingest_ledger(request):
            pass

    with pytest.raises(ResourceLimitError, match="max_pages"):
        asyncio.run(over_range())

    provider, _transport = _provider(rpc_session)

    async def over_requests() -> None:
        request = BoundedRequest(
            scope=rpc_session["addresses"]["alice"],
            context=_context(max_requests=2),
            options={"page_size": 2},
        )
        async for _ in provider.ingest_wallet(request):
            pass

    with pytest.raises(ResourceLimitError, match="request budget"):
        asyncio.run(over_requests())

    provider, _transport = _provider(rpc_session)

    async def over_items() -> None:
        request = BoundedRequest(
            scope=rpc_session["addresses"]["alice"],
            context=_context(max_items=1),
            options={"page_size": 2},
        )
        async for _ in provider.ingest_wallet(request):
            pass

    with pytest.raises(ResourceLimitError, match="max_items"):
        asyncio.run(over_items())


def test_balance_is_exact_and_public_surface_is_read_only(rpc_session: dict) -> None:
    provider, _transport = _provider(rpc_session)
    balance = asyncio.run(
        provider.get_balance(
            rpc_session["addresses"]["alice"],
            commitment=Commitment.FINALIZED,
            context=_context(),
        )
    )
    assert balance == 18446744073709551615
    assert isinstance(balance, int)
    forbidden = {
        "sign",
        "sign_transaction",
        "send",
        "send_transaction",
        "broadcast",
        "submit",
        "private_key",
    }
    assert forbidden.isdisjoint(dir(provider))
    assert provider.capabilities.metadata["read_only"] is True
    assert provider.capabilities.metadata["supports_sign"] is False
    assert "fixture.invalid" not in repr(provider)
    assert "private-key-in-url" not in repr(provider)
