from __future__ import annotations

import sys
import types


def test_logic_cli_interactive_routes_to_logic_repl_main(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI

    called = {"count": 0}

    def _fake_main():
        called["count"] += 1
        return 0

    monkeypatch.setitem(
        sys.modules,
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_repl",
        types.SimpleNamespace(main=_fake_main),
    )

    cli = LogicOptimizerCLI()
    code = cli.run(["interactive"])

    assert code == 0
    assert called["count"] == 1


def test_logic_cli_interactive_handles_repl_error(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI

    def _failing_main():
        raise RuntimeError("repl failed")

    monkeypatch.setitem(
        sys.modules,
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_repl",
        types.SimpleNamespace(main=_failing_main),
    )

    cli = LogicOptimizerCLI()
    code = cli.run(["interactive"])

    out = capsys.readouterr().out
    assert code == 1
    assert "Error" in out
