from __future__ import annotations

import sys
import types
import pytest


def test_cli_interactive_routes_to_graphrag_repl_main(monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    if not isinstance(GraphRAGOptimizerCLI, type):
        pytest.skip("cli_wrapper is mocked by another test module")

    called = {"count": 0}

    def _fake_main():
        called["count"] += 1
        return 0

    monkeypatch.setitem(
        sys.modules,
        "ipfs_datasets_py.optimizers.graphrag_repl",
        types.SimpleNamespace(main=_fake_main),
    )

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["interactive"])

    assert code == 0
    assert called["count"] == 1


def test_cli_interactive_handles_repl_error(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    if not isinstance(GraphRAGOptimizerCLI, type):
        pytest.skip("cli_wrapper is mocked by another test module")

    def _failing_main():
        raise RuntimeError("repl failed")

    monkeypatch.setitem(
        sys.modules,
        "ipfs_datasets_py.optimizers.graphrag_repl",
        types.SimpleNamespace(main=_failing_main),
    )

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["interactive"])

    out = capsys.readouterr().out
    assert code == 1
    assert "Error" in out
