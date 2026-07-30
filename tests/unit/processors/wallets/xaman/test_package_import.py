"""Package import and AST symbol smoke tests."""

from __future__ import annotations

import importlib
import socket


def test_xaman_package_import_has_no_network_io(monkeypatch) -> None:
    def fail_socket(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("package import must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    monkeypatch.setattr(socket, "create_connection", fail_socket)

    module = importlib.import_module("ipfs_datasets_py.processors.wallets.xaman")
    importlib.reload(module)

    assert module.XamanWalletProcessor is not None
    assert module.XamanPayload is not None
    assert module.PayloadStatus is not None


def test_ast_query_symbols_are_exported() -> None:
    from ipfs_datasets_py.processors.wallets import xaman as pkg

    for name in (
        "XamanWalletProcessor",
        "XamanPayload",
        "PayloadStatus",
        "SettlementVerdict",
        "parse_xaman_payload",
        "verify_settlement_against_xrpl",
        "XamanPayloadProvider",
    ):
        assert hasattr(pkg, name), name
        assert name in pkg.__all__


def test_xaman_is_separate_public_module_from_xrpl() -> None:
    import ipfs_datasets_py.processors.wallets.xaman as xaman
    import ipfs_datasets_py.processors.wallets.xrpl as xrpl

    assert xaman.__name__ != xrpl.__name__
    assert "XamanWalletProcessor" in xaman.__all__
    assert "XamanWalletProcessor" not in xrpl.__all__
    assert "XRPLWalletProcessor" in xrpl.__all__
    assert "XRPLWalletProcessor" not in xaman.__all__


def test_runtime_does_not_import_formal_assurance() -> None:
    import ipfs_datasets_py.processors.wallets.xaman as xaman

    module_file = xaman.__file__
    assert module_file is not None
    # Package modules must not hard-depend on formal IR packages.
    import ipfs_datasets_py.processors.wallets.xaman.processor as processor_mod
    import ipfs_datasets_py.processors.wallets.xaman.models as models_mod
    import ipfs_datasets_py.processors.wallets.xaman.normalizer as normalizer_mod
    import ipfs_datasets_py.processors.wallets.xaman.provider as provider_mod
    import ipfs_datasets_py.processors.wallets.xaman.settlement as settlement_mod

    for mod in (
        processor_mod,
        models_mod,
        normalizer_mod,
        provider_mod,
        settlement_mod,
    ):
        for name, value in vars(mod).items():
            if name.startswith("__"):
                continue
            text = str(getattr(value, "__module__", "") or "")
            assert "security_ir" not in text
            assert "security_models.crypto_exchange.reports" not in text
