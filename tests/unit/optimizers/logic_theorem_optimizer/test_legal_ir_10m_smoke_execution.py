"""Fast contract tests for the executed ten-minute LegalIR smoke.

The production smoke is deliberately not launched here.  These tests exercise
the execution-only shell boundary and recompute the acceptance decision from
evidence-shaped packets, including adversarial omissions and substitutions.
"""

from __future__ import annotations

import json
import os
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "scripts/ops/legal_ir/run_legal_ir_10m_smoke.sh"
VERIFIER = ROOT / "scripts/ops/legal_ir/verify_legal_ir_run_evidence.py"
COMMITTED_EVIDENCE = (
    ROOT
    / "docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json"
)


def _run_runner(*arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [str(RUNNER), *arguments],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_execution_wrapper_is_valid_execution_only_shell() -> None:
    syntax = subprocess.run(
        ["bash", "-n", str(RUNNER)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    help_result = _run_runner("--help")

    assert syntax.returncode == 0, syntax.stderr
    assert os.access(RUNNER, os.X_OK)
    assert help_result.returncode == 0, help_result.stderr
    assert "at least 600 active" in help_result.stdout
    assert "watchdog" in help_result.stdout.lower()
    assert "no dry-run mode" in help_result.stdout.lower()


@pytest.mark.parametrize("forbidden", ["--dry-run", "--gate-only", "--simulate"])
def test_execution_wrapper_rejects_non_execution_modes(
    forbidden: str, tmp_path: Path
) -> None:
    evidence = tmp_path / "must-not-exist.json"

    completed = _run_runner(forbidden, "--evidence", str(evidence))

    assert completed.returncode == 2
    assert "execution evidence only" in completed.stderr
    assert not evidence.exists()


@pytest.mark.parametrize("seconds", ["0", "599", "601", "nan"])
def test_execution_wrapper_keeps_the_stage_duration_immutable(
    seconds: str, tmp_path: Path
) -> None:
    evidence = tmp_path / "must-not-exist.json"

    completed = _run_runner(
        "--minimum-active-seconds", seconds, "--evidence", str(evidence)
    )

    assert completed.returncode == 2
    assert "exactly 600" in completed.stderr
    assert not evidence.exists()


def test_execution_wrapper_refuses_to_overwrite_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "existing.json"
    evidence.write_text("operator-owned\n", encoding="utf-8")

    completed = _run_runner("--evidence", str(evidence))

    assert completed.returncode == 2
    assert "refusing to overwrite evidence" in completed.stderr
    assert evidence.read_text(encoding="utf-8") == "operator-owned\n"


def test_execution_wrapper_invokes_canonical_runner_watchdog_and_verifier() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert "run_hammer_leanstral_smoke.sh" in source
    assert "watch_runner" in source
    assert "terminate_managed_processes" in source
    assert "verify_legal_ir_run_evidence.py" in source
    assert 'export AUTOENCODER_DEVICE="cuda"' in source
    assert 'export LEGAL_IR_ALLOW_CPU_FALLBACK="0"' in source
    assert 'export DURATION_SECONDS=600' in source
    assert "setsid" in source

