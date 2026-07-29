"""XRPL package must not expose sign, submit, or broadcast authority."""

from __future__ import annotations

import inspect

from ipfs_datasets_py.processors.wallets import xrpl as pkg
from ipfs_datasets_py.processors.wallets.xrpl import (
    MappingResponseBackend,
    XRPLLedgerProvider,
    XRPLWalletProcessor,
)


PROHIBITED = frozenset(
    {
        "sign",
        "sign_transaction",
        "submit",
        "submit_transaction",
        "broadcast",
        "broadcast_transaction",
        "send",
        "transfer_funds",
        "create_payment",
        "approve_payload",
        "xaman_payload",
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
        assert "sign" not in name.lower()
        assert "submit" not in name.lower()
        assert "xaman" not in name.lower()


def test_provider_and_processor_have_no_prohibited_methods() -> None:
    backend = MappingResponseBackend(responses={})
    provider = XRPLLedgerProvider(backend=backend)
    processor = XRPLWalletProcessor(provider=provider)

    for obj in (provider, processor, type(provider), type(processor)):
        methods = {name.lower() for name in _public_callables(obj)}
        overlap = methods & PROHIBITED
        assert not overlap, f"prohibited methods present: {sorted(overlap)}"

    assert provider.capabilities.metadata.get("supports_sign") is False
    assert provider.capabilities.metadata.get("supports_submit") is False
    assert provider.capabilities.metadata.get("supports_broadcast") is False
    assert provider.capabilities.metadata.get("xaman_payloads") is False
    assert processor.capabilities.metadata.get("supports_sign") is False
    assert processor.capabilities.metadata.get("xaman_payloads") is False
