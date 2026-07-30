"""Bitcoin package must not expose PSBT, sign, or broadcast authority."""

from __future__ import annotations

import inspect

from ipfs_datasets_py.processors.wallets import bitcoin as pkg
from ipfs_datasets_py.processors.wallets.bitcoin import (
    BitcoinLedgerProvider,
    BitcoinWalletProcessor,
    MappingResponseBackend,
)


PROHIBITED = frozenset(
    {
        "sign",
        "sign_transaction",
        "sign_psbt",
        "broadcast",
        "broadcast_transaction",
        "submit",
        "submit_transaction",
        "create_psbt",
        "finalize_psbt",
        "psbt",
        "send",
        "transfer_funds",
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
        assert "psbt" not in name.lower()
        assert "sign" not in name.lower() or name in {
            # no exceptions expected
        }


def test_provider_and_processor_have_no_prohibited_methods() -> None:
    backend = MappingResponseBackend(responses={})
    provider = BitcoinLedgerProvider(backend=backend)
    processor = BitcoinWalletProcessor(provider=provider)

    for obj in (provider, processor, type(provider), type(processor)):
        methods = {name.lower() for name in _public_callables(obj)}
        overlap = methods & PROHIBITED
        assert not overlap, f"prohibited methods present: {sorted(overlap)}"

    assert provider.capabilities.metadata.get("supports_psbt") is False
    assert provider.capabilities.metadata.get("supports_sign") is False
    assert provider.capabilities.metadata.get("supports_broadcast") is False
    assert processor.capabilities.metadata.get("supports_psbt") is False
