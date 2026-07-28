"""Package import and public API smoke tests (WALPROC-G100)."""

from __future__ import annotations

import importlib
import socket


def test_worldcoin_package_import_has_no_network_io(monkeypatch) -> None:
    def fail_socket(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("package import must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    monkeypatch.setattr(socket, "create_connection", fail_socket)

    module = importlib.import_module("ipfs_datasets_py.processors.wallets.worldcoin")
    importlib.reload(module)

    assert module.WorldIdConfig is not None
    assert module.sign_world_id_request is not None
    assert module.normalize_idkit_response is not None
    assert module.verify_world_id_proof is not None
    assert "WorldIdConfig" in module.__all__
    assert "WorldChainProcessor" in module.__all__


def test_ast_query_symbols_are_exported() -> None:
    from ipfs_datasets_py.processors.wallets import worldcoin as pkg

    for name in (
        "WorldIdConfig",
        "WorldIdRpSignature",
        "sign_world_id_request",
        "normalize_idkit_response",
        "verify_world_id_proof",
        "WorldChainProcessor",
    ):
        assert hasattr(pkg, name)
