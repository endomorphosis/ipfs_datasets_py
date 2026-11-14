"""PATLAW-219: CLI help surfaces for pilot paths (offline)."""
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "scripts/ops/uspto/portfolio_cli.py"


def test_portfolio_cli_help_lists_pilot_commands():
    proc = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    out = proc.stdout + proc.stderr
    for cmd in ("prior-art", "audit-submission", "matter-status", "filing-assist"):
        assert cmd in out
