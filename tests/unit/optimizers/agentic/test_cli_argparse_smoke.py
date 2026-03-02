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


def test_argparse_cli_validate_rejects_unsafe_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "sample.py"
    target.write_text("print('ok')\n")

    cli = OptimizerArgparseCLI()
    monkeypatch.setattr(cli._sanitizer, "validate_file_path", lambda _path: False)

    code = cli.run([
        "validate",
        str(target),
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
        raise ValueError("bad input api_key=sk-secret123")

    monkeypatch.setattr(cli, "cmd_optimize", _raise_value_error)
    captured = []

    def _capture(*values, **_kwargs):
        captured.append(" ".join(str(value) for value in values))

    monkeypatch.setattr("builtins.print", _capture)
    monkeypatch.setattr("traceback.print_exc", lambda: None)
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
    assert any("api_key=***REDACTED***" in line for line in captured)
    assert not any("sk-secret123" in line for line in captured)


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


def test_argparse_cli_state_laws_optimize_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = OptimizerArgparseCLI()
    captured = {}

    def _fake_cmd(args):
        captured["states"] = args.states
        captured["max_rounds"] = args.max_rounds
        captured["target_score"] = args.target_score
        captured["emit_patch_plan"] = bool(args.emit_patch_plan)
        captured["apply_patch_plan"] = bool(args.apply_patch_plan)
        captured["patch_plan_limit"] = int(args.patch_plan_limit)
        captured["execute_apply_plan"] = bool(args.execute_apply_plan)
        captured["apply_plan_file"] = args.apply_plan_file
        captured["execution_max_tasks"] = int(args.execution_max_tasks)
        captured["auto_patch"] = bool(args.auto_patch)
        captured["auto_patch_max_tasks"] = int(args.auto_patch_max_tasks)
        captured["auto_patch_no_dry_run"] = bool(args.auto_patch_no_dry_run)
        return 0

    monkeypatch.setattr(cli, "cmd_state_laws_optimize", _fake_cmd)

    code = cli.run(
        [
            "state-laws-optimize",
            "--states",
            "OK,IN,LA",
            "--max-rounds",
            "3",
            "--target-score",
            "0.9",
            "--emit-patch-plan",
            "--apply-patch-plan",
            "--patch-plan-limit",
            "7",
            "--execute-apply-plan",
            "--apply-plan-file",
            "tmp/tasks.jsonl",
            "--execution-max-tasks",
            "4",
            "--auto-patch",
            "--auto-patch-max-tasks",
            "2",
            "--auto-patch-no-dry-run",
        ]
    )

    assert code == 0
    assert captured["states"] == "OK,IN,LA"
    assert captured["max_rounds"] == 3
    assert captured["target_score"] == 0.9
    assert captured["emit_patch_plan"] is True
    assert captured["apply_patch_plan"] is True
    assert captured["patch_plan_limit"] == 7
    assert captured["execute_apply_plan"] is True
    assert captured["apply_plan_file"] == "tmp/tasks.jsonl"
    assert captured["execution_max_tasks"] == 4
    assert captured["auto_patch"] is True
    assert captured["auto_patch_max_tasks"] == 2
    assert captured["auto_patch_no_dry_run"] is True
