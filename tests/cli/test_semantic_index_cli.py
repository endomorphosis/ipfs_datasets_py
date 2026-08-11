"""Subprocess coverage for the dedicated semantic-index entry module."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(project_root) + os.pathsep + environment.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ipfs_datasets_py.cli.semantic_index_cli", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )


def test_all_commands_use_local_store_and_json_state_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "example.py"
    source.write_text("def target():\n    return 1\n\ndef caller():\n    return target()\n", encoding="utf-8")
    state_file = tmp_path / "state.json"

    assert _run("--help", cwd=tmp_path).returncode == 0
    scan = _run("scan", str(repo), "--output", str(state_file), cwd=tmp_path)
    assert scan.returncode == 0, scan.stderr
    state = json.loads(scan.stdout)
    assert state_file.is_file()
    assert state["state_cid"]

    root = _run("state-root", str(repo), cwd=tmp_path)
    assert root.returncode == 0, root.stderr
    assert json.loads(root.stdout)["state_cid"] == state["state_cid"]

    diff = _run("diff", str(state_file), str(state_file), cwd=tmp_path)
    assert diff.returncode == 0, diff.stderr
    assert json.loads(diff.stdout)["previous_state_cid"] == state["state_cid"]
    cid_diff = _run("diff", state["state_cid"], state["state_cid"], "--store", str(repo / ".semantic_index"), cwd=tmp_path)
    assert cid_diff.returncode == 0, cid_diff.stderr

    symbol = next(item["stable_id"] for item in state["symbols"] if item["qualified_name"] == "example.target")
    assert _run("explain", str(repo), symbol, cwd=tmp_path).returncode == 0
    assert _run("impact", str(repo), "example.py", cwd=tmp_path).returncode == 0
    assert _run("watch", str(repo), "--once", cwd=tmp_path).returncode == 0


def test_bad_state_input_has_no_traceback(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json", encoding="utf-8")
    result = _run("diff", str(corrupt), str(corrupt), cwd=tmp_path)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert result.stderr.startswith("semantic-index: error:")
