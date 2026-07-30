from __future__ import annotations

import importlib
import sys


def test_package_import_needs_no_optional_solana_sdk(monkeypatch) -> None:
    for name in ("solana", "solders"):
        monkeypatch.setitem(sys.modules, name, None)
    module = importlib.import_module("ipfs_datasets_py.processors.wallets.solana")
    assert module.SolanaLedgerProvider is not None
    assert module.SolanaNormalizer is not None
    assert module.TokenAccountRecord is not None
