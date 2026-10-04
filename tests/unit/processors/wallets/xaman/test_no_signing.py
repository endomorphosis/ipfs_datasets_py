"""Xaman package must not expose approve, sign, or submit authority."""

from __future__ import annotations

import inspect

from ipfs_datasets_py.processors.wallets import xaman as pkg
from ipfs_datasets_py.processors.wallets.xaman import (
    MappingPayloadBackend,
    XamanPayloadProvider,
    XamanWalletProcessor,
)
from ipfs_datasets_py.processors.wallets.xrpl.networks import XRPLNetwork


PROHIBITED = frozenset(
    {
        "approve",
        "approve_payload",
        "sign",
        "sign_transaction",
        "sign_payload",
        "submit",
        "submit_transaction",
        "submit_payload",
        "broadcast",
        "broadcast_transaction",
        "send",
        "transfer_funds",
        "create_payment",
    }
)


def _public_callables(obj: object) -> set[str]:
    names: set[str] = set()
    for name, value in inspect.getmembers(obj):
        if name.startswith("_"):
            continue
        if inspect.isroutine(value) or inspect.ismethoddescriptor(value):
            names.add(name)
    return names


def test_package_exports_forbid_signing_surface() -> None:
    exported = set(pkg.__all__)
    lowered = {name.lower() for name in exported}
    assert lowered.isdisjoint(PROHIBITED)
    for name in exported:
        lower = name.lower()
        assert "sign" not in lower
        assert "submit" not in lower
        assert "approve" not in lower
        assert "broadcast" not in lower


def test_provider_and_processor_have_no_prohibited_methods() -> None:
    backend = MappingPayloadBackend(payloads={})
    provider = XamanPayloadProvider(
        network=XRPLNetwork.TESTNET, backend=backend
    )
    processor = XamanWalletProcessor(
        network=XRPLNetwork.TESTNET, payload_provider=provider
    )
    processor.assert_read_only_surface()

    for obj in (provider, processor, type(provider), type(processor)):
        methods = {name.lower() for name in _public_callables(obj)}
        overlap = methods & PROHIBITED
        assert not overlap, f"prohibited methods present: {sorted(overlap)}"

    assert provider.capabilities.metadata.get("supports_sign") is False
    assert provider.capabilities.metadata.get("supports_submit") is False
    assert provider.capabilities.metadata.get("supports_approve") is False
    assert provider.capabilities.metadata.get("api_success_is_settlement") is False
    assert processor.capabilities.metadata.get("supports_sign") is False
    assert processor.capabilities.metadata.get("supports_submit") is False
    assert processor.capabilities.metadata.get("supports_approve") is False
    assert processor.capabilities.metadata.get("api_success_is_settlement") is False
