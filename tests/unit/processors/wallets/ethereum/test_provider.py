from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    NormalizationError,
    ResourceLimitError,
    UnsupportedCapabilityError,
)
from ipfs_datasets_py.processors.wallets.ethereum import (
    ETHEREUM_MAINNET,
    EthereumIdentityError,
    EthereumLedgerProvider,
    EvmNetwork,
    normalize_address,
    parse_quantity,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    Capability,
    OperationContext,
    RequestLimits,
)

from ._helpers import FixtureJsonRpc


def _context(
    *,
    max_requests: int = 20,
    max_pages: int = 10,
    max_items: int = 100,
) -> OperationContext:
    return OperationContext(
        "ethereum-unit",
        limits=RequestLimits(
            max_requests=max_requests,
            max_pages=max_pages,
            max_items=max_items,
            max_response_bytes=2_000_000,
        ),
    )


def _provider(transport: FixtureJsonRpc, *, traces: bool = False) -> EthereumLedgerProvider:
    return EthereumLedgerProvider(
        transport,
        endpoint="https://fixture.invalid",
        network=ETHEREUM_MAINNET,
        include_traces=traces,
    )


def test_chain_id_and_genesis_bind_provider_identity(
    fixture_rpc: FixtureJsonRpc,
) -> None:
    provider = _provider(fixture_rpc)
    chain = asyncio.run(provider.validate_identity(context=_context()))
    assert chain.namespace == "eip155"
    assert chain.chain_id == "1"
    assert chain.genesis_hash == ETHEREUM_MAINNET.genesis_hash
    assert [call[0] for call in fixture_rpc.calls] == [
        "eth_chainId",
        "eth_getBlockByNumber",
    ]


def test_identity_rejects_chain_or_genesis_mismatch(
    rpc_session: Mapping[str, object],
) -> None:
    wrong_chain = EvmNetwork(
        chain_id=10,
        network="wrong",
        genesis_hash=ETHEREUM_MAINNET.genesis_hash,
    )
    with pytest.raises(EthereumIdentityError, match="chain id"):
        asyncio.run(
            EthereumLedgerProvider(
                FixtureJsonRpc(rpc_session),
                endpoint="https://fixture.invalid",
                network=wrong_chain,
            ).validate_identity(context=_context())
        )

    wrong_genesis = EvmNetwork(
        chain_id=1,
        network="wrong",
        genesis_hash="0x" + "99" * 32,
    )
    with pytest.raises(EthereumIdentityError, match="genesis"):
        asyncio.run(
            EthereumLedgerProvider(
                FixtureJsonRpc(rpc_session),
                endpoint="https://fixture.invalid",
                network=wrong_genesis,
            ).validate_identity(context=_context())
        )


def test_account_balance_and_address_rules_are_exact(
    fixture_rpc: FixtureJsonRpc,
) -> None:
    provider = _provider(fixture_rpc)
    balance = asyncio.run(
        provider.get_balance(
            "0x1111111111111111111111111111111111111111",
            context=_context(),
        )
    )
    assert balance == 10**18
    assert isinstance(balance, int)
    assert normalize_address("0x" + "AB" * 20) == "0x" + "ab" * 20
    assert parse_quantity("0x0") == 0
    with pytest.raises(NormalizationError):
        parse_quantity("0x00")
    with pytest.raises(NormalizationError):
        normalize_address("0x1234")


def test_ledger_ingestion_fetches_blocks_receipts_and_optional_traces(
    fixture_rpc: FixtureJsonRpc,
) -> None:
    provider = _provider(fixture_rpc, traces=True)

    async def collect() -> list[object]:
        request = BoundedRequest(
            scope="ledger",
            context=_context(),
            start_position=16,
            end_position=16,
        )
        return [batch async for batch in provider.ingest_ledger(request)]

    batches = asyncio.run(collect())
    assert len(batches) == 1
    bundle = batches[0].records[0]
    assert len(bundle.receipts) == 3
    first_hash = rpc_session_hash = (
        "0x" + "01" * 32
    )
    assert bundle.traces[first_hash][0]["action"]["value"] == "0x2a"
    assert Capability.INTERNAL_TRANSFERS in provider.capabilities.features
    assert provider.capabilities.metadata["read_only"] is True
    assert rpc_session_hash in bundle.traces


def test_trace_failure_is_labeled_incomplete_and_never_blocks_bundle(
    rpc_session: Mapping[str, object],
) -> None:
    transport = FixtureJsonRpc(rpc_session, traces=False)
    provider = _provider(transport, traces=True)

    async def collect() -> list[object]:
        request = BoundedRequest(
            scope="ledger",
            context=_context(),
            start_position=16,
            end_position=16,
        )
        return [batch async for batch in provider.ingest_ledger(request)]

    bundle = asyncio.run(collect())[0].records[0]
    assert bundle.trace_capability is True
    assert all(value is None for value in bundle.traces.values())


def test_safe_and_finalized_tags_are_preferred_with_explicit_fallback(
    rpc_session: Mapping[str, object],
) -> None:
    tagged = _provider(FixtureJsonRpc(rpc_session, explicit_tags=True))
    tagged_head = asyncio.run(tagged.ledger_head(context=_context()))
    assert tagged_head.explicit_tags_supported is True
    assert tagged_head.safe["number"] == "0x1f"
    assert tagged_head.finalized["number"] == "0x1e"

    fallback = _provider(FixtureJsonRpc(rpc_session, explicit_tags=False))
    fallback_head = asyncio.run(fallback.ledger_head(context=_context()))
    assert fallback_head.explicit_tags_supported is False
    assert fallback_head.safe is None
    assert fallback_head.finalized is None


def test_ranges_and_request_counts_are_bounded(
    fixture_rpc: FixtureJsonRpc,
) -> None:
    provider = _provider(fixture_rpc)

    async def over_pages() -> None:
        request = BoundedRequest(
            scope="ledger",
            context=_context(max_pages=1),
            start_position=16,
            end_position=17,
        )
        async for _ in provider.ingest_ledger(request):
            pass

    with pytest.raises(ResourceLimitError, match="max_pages"):
        asyncio.run(over_pages())

    async def over_requests() -> None:
        request = BoundedRequest(
            scope="ledger",
            context=_context(max_requests=2),
            start_position=16,
            end_position=16,
        )
        async for _ in provider.ingest_ledger(request):
            pass

    with pytest.raises(ResourceLimitError, match="request budget"):
        asyncio.run(over_requests())


def test_wallet_history_scan_is_finite_and_filtered(
    fixture_rpc: FixtureJsonRpc,
) -> None:
    provider = _provider(fixture_rpc)

    async def collect(scope: str) -> list[object]:
        request = BoundedRequest(
            scope=scope,
            context=_context(),
            start_position=16,
            end_position=16,
        )
        return [batch async for batch in provider.ingest_wallet(request)]

    assert len(asyncio.run(collect("0x" + "11" * 20))) == 1
    assert asyncio.run(collect("0x" + "99" * 20)) == []
    with pytest.raises(UnsupportedCapabilityError):
        asyncio.run(
            provider.trace_transaction("0x" + "01" * 32, context=_context())
        )


def test_public_surface_is_read_only_and_endpoint_repr_is_redacted(
    fixture_rpc: FixtureJsonRpc,
) -> None:
    provider = _provider(fixture_rpc)
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
    assert "fixture.invalid" not in repr(provider)
