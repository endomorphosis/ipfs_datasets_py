"""Smoke tests for OptimizerArgparseCLI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.agentic.cli import OptimizerArgparseCLI


def test_argparse_cli_optimize_dry_run(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("print('ok')\n")

    cli = OptimizerArgparseCLI()
    code = cli.run(
        [
            "optimize",
            "--method",
            "test_driven",
            "--target",
            str(target),
            "--description",
            "Smoke test",
            "--dry-run",
        ]
    )

    assert code == 0


def test_argparse_cli_validate_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"

    cli = OptimizerArgparseCLI()
    code = cli.run([
        "validate",
        str(missing),
        "--level",
        "basic",
    ])

    assert code == 1


def test_argparse_cli_config_show_masks_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / ".optimizer-config.json"
    config_path.write_text(
        json.dumps(
            {
                "github_token": "secret-token",
                "github_repo": "example/repo",
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    cli = OptimizerArgparseCLI()
    args = SimpleNamespace(action="show", key=None, value=None, force=False)

    captured = []

    def _capture(*values, **_kwargs):
        captured.append(" ".join(str(value) for value in values))

    monkeypatch.setattr("builtins.print", _capture)
    code = cli.cmd_config(args)

    assert code == 0
    assert any("github_token: ***" in line for line in captured)


def test_argparse_cli_run_handles_typed_command_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "sample.py"
    target.write_text("print('ok')\n")
    cli = OptimizerArgparseCLI()

    def _raise_value_error(_args):
        raise ValueError("bad input")

    monkeypatch.setattr(cli, "cmd_optimize", _raise_value_error)
    code = cli.run(
        [
            "optimize",
            "--method",
            "test_driven",
            "--target",
            str(target),
            "--description",
            "Smoke test",
            "--dry-run",
        ]
    )
    assert code == 1


def test_argparse_cli_run_propagates_non_keyboard_base_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "sample.py"
    target.write_text("print('ok')\n")
    cli = OptimizerArgparseCLI()

    def _raise_system_exit(_args):
        raise SystemExit(2)

    monkeypatch.setattr(cli, "cmd_optimize", _raise_system_exit)
    with pytest.raises(SystemExit):
        cli.run(
            [
                "optimize",
                "--method",
                "test_driven",
                "--target",
                str(target),
                "--description",
                "Smoke test",
                "--dry-run",
            ]
        )
