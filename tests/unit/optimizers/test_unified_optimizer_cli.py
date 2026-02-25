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


def test_unified_cli_redacts_sensitive_error_text(monkeypatch, capsys) -> None:
    cli = UnifiedOptimizerCLI()

    monkeypatch.setattr(
        cli,
        "_run_agentic",
        lambda args, verbose: (_ for _ in ()).throw(RuntimeError("api_key=sk-1234567890abcdef password=hunter2")),
    )

    code = cli.run(["--type", "agentic"])
    assert code == 1

    out = capsys.readouterr().out
    assert "***REDACTED***" in out
    assert "sk-1234567890abcdef" not in out
    assert "hunter2" not in out
