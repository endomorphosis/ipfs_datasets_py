"""Offline payload provider ingest tests."""

from __future__ import annotations

import asyncio

from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.xaman import (
    PayloadPrivacyPolicy,
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


def test_provider_redacts_content_by_default_and_retains_only_with_opt_in() -> None:
    payload_uuid = "55555555-5555-4555-8555-555555555501"
    instruction = "Send after reviewing the private invoice"
    raw = {
        "meta": {
            "uuid": payload_uuid,
            "network": "testnet",
            "created": True,
        },
        "payload": {
            "custom_instruction": instruction,
            "txjson": {
                "TransactionType": "Payment",
                "Account": "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
                "Destination": "r3bmF74WayREhyVYaqbu7GqLKvqZvUF3k6",
                "Amount": "1",
                "InvoiceNote": "free-form request content",
            },
        },
    }
    context = OperationContext(request_id="privacy")

    async def _fetch(privacy=None):
        provider = XamanPayloadProvider(
            network=XRPLNetwork.TESTNET,
            backend=fixture_backend_from_payloads([raw]),
            privacy=privacy,
        )
        return await provider.fetch_payload(payload_uuid, context=context)

    redacted = asyncio.run(_fetch())
    assert redacted.custom_instruction is None
    assert redacted.custom_instruction_redacted is True
    assert redacted.original_instruction_bytes == len(instruction.encode("utf-8"))
    assert redacted.request_summary == {"_redacted": True, "key_count": 5}
    assert redacted.content_digest.startswith("sha256:")
    assert instruction not in str(redacted.to_dict())
    assert "free-form request content" not in str(redacted.to_dict())

    retained = asyncio.run(
        _fetch(
            PayloadPrivacyPolicy(
                redact_instruction=False,
                redact_request_body=False,
                max_instruction_bytes=64,
                max_string_field_bytes=64,
            )
        )
    )
    assert retained.custom_instruction == instruction
    assert retained.custom_instruction_redacted is False
    assert retained.request_summary["InvoiceNote"] == "free-form request content"
    # Retention policy changes representation, never payload identity.
    assert retained.content_digest == redacted.content_digest
    assert retained.status is redacted.status
    assert retained.settlement is redacted.settlement
