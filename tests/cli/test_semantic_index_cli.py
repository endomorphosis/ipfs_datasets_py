"""Subprocess coverage for the dedicated semantic-index command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update({"IPFS_DATASETS_AUTO_INSTALL": "0", "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0"})
    return subprocess.run([sys.executable, "-m", "ipfs_datasets_py.cli.semantic_index_cli", *args], cwd=ROOT, env=env, text=True, capture_output=True, check=False)


def test_help_and_all_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("def example(value: int) -> int:\n    return value\n", encoding="utf-8")
    help_result = _run("--help")
    assert help_result.returncode == 0
    assert all(name in help_result.stdout for name in ("scan", "diff", "impact", "explain", "watch", "state-root"))

    scanned = _run("scan", str(repo))
    assert scanned.returncode == 0, scanned.stderr
    state = json.loads(scanned.stdout)
    state_file = tmp_path / "state.json"
    state_file.write_text(scanned.stdout, encoding="utf-8")
    assert _run("diff", str(state_file), str(state_file)).returncode == 0
    symbol = next(item["stable_id"] for item in state["symbols"] if item["qualified_name"].endswith(".example"))
    assert _run("impact", str(repo), "sample.py").returncode == 0
    assert _run("explain", str(repo), symbol).returncode == 0
    assert _run("watch", str(repo), "--once").returncode == 0
    root = _run("state-root", str(repo))
    assert root.returncode == 0
    assert json.loads(root.stdout)["state_cid"] == state["state_cid"]


def test_bad_input_has_no_traceback(tmp_path: Path) -> None:
    result = _run("diff", str(tmp_path / "missing.json"), str(tmp_path / "missing.json"))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
