from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.cli import UnifiedOptimizerCLI


def test_unified_cli_returns_error_code_on_typed_runtime_error(monkeypatch) -> None:
    cli = UnifiedOptimizerCLI()

    monkeypatch.setattr(cli, "_run_agentic", lambda args, verbose: (_ for _ in ()).throw(RuntimeError("boom")))

    code = cli.run(["--type", "agentic"])
    assert code == 1


def test_unified_cli_does_not_swallow_keyboard_interrupt(monkeypatch) -> None:
    cli = UnifiedOptimizerCLI()

    monkeypatch.setattr(cli, "_run_agentic", lambda args, verbose: (_ for _ in ()).throw(KeyboardInterrupt()))

    code = cli.run(["--type", "agentic"])
    assert code == 130
