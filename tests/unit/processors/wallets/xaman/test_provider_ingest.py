"""Offline payload provider ingest tests."""

from __future__ import annotations

import asyncio

from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.xaman import (
    XamanWalletProcessor,
    fixture_backend_from_payloads,
    XamanPayloadProvider,
)
from ipfs_datasets_py.processors.wallets.xrpl.networks import XRPLNetwork


def test_fixture_provider_fetch_and_ingest(load_xaman_fixture) -> None:
    data = load_xaman_fixture("payload_lifecycle_states.json")
    docs = [c["document"] for c in data["payloads"]]
    backend = fixture_backend_from_payloads(docs)
    provider = XamanPayloadProvider(network=XRPLNetwork.TESTNET, backend=backend)
    processor = XamanWalletProcessor(
        network=XRPLNetwork.TESTNET, payload_provider=provider
    )
    context = OperationContext(
        request_id="ingest",
        limits=RequestLimits(max_items=50, max_pages=5, max_requests=10),
    )

    async def _run():
        one = await provider.fetch_payload(
            "11111111-1111-4111-8111-111111111101", context=context
        )
        assert one.payload_uuid == "11111111-1111-4111-8111-111111111101"
        batches = []
        request = BoundedRequest(scope="payloads", context=context)
        async for batch in processor.ingest_payloads(request):
            batches.append(batch)
        return one, batches

    one, batches = asyncio.run(_run())
    assert one.status.value == "created"
    total = sum(len(b.records) for b in batches)
    assert total == len(docs)
    # Ingest without XRPL evidence marks API successes as api_success_only.
    signed = [
        r
        for b in batches
        for r in b.records
        if getattr(r, "status", None) and r.status.value == "signed"
    ]
    assert signed
    assert signed[0].settlement.value == "api_success_only"
    assert signed[0].is_ledger_settled is False
