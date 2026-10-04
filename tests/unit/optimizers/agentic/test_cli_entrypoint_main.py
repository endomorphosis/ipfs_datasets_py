"""Test that the agentic CLI module entrypoint works.

The module includes a test-facing compatibility shim class named `OptimizerCLI`.
Historically that shim overwrote the real argparse-based CLI class, causing
`python -m ipfs_datasets_py.optimizers.agentic.cli ...` to break.

This test guards the entrypoint by calling `main()` with valid args.
"""

from pathlib import Path


def test_agentic_cli_main_optimize_dry_run(tmp_path: Path) -> None:
    from ipfs_datasets_py.optimizers.agentic import cli as agentic_cli

    target = tmp_path / "target.py"
    target.write_text("def f():\n    return 1\n")

    exit_code = agentic_cli.main(
        [
            "optimize",
            "--method",
            "test_driven",
            "--target",
            str(target),
            "--description",
            "test",
            "--dry-run",
        ]
    )

    assert exit_code == 0
