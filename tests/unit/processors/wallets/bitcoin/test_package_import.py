"""Package import and AST symbol smoke tests."""

from __future__ import annotations

import importlib
import socket


def test_bitcoin_package_import_has_no_network_io(monkeypatch) -> None:
    def fail_socket(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("package import must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    monkeypatch.setattr(socket, "create_connection", fail_socket)

    module = importlib.import_module("ipfs_datasets_py.processors.wallets.bitcoin")
    importlib.reload(module)

    assert module.BitcoinLedgerProvider is not None
    assert module.ScriptDescriptor is not None
    assert module.UtxoRecord is not None


def test_ast_query_symbols_are_exported() -> None:
    from ipfs_datasets_py.processors.wallets import bitcoin as pkg

    for name in (
        "BitcoinLedgerProvider",
        "UtxoRecord",
        "ScriptDescriptor",
        "BitcoinWalletProcessor",
        "BitcoinNormalizer",
        "UtxoSet",
    ):
        assert hasattr(pkg, name), name
        assert name in pkg.__all__ or name in {
            "UtxoRecord",
            "UTXORecord",
        }
