"""Smoke tests for OptimizerArgparseCLI."""

from __future__ import annotations

from pathlib import Path

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
