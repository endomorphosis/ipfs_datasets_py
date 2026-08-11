"""Subprocess coverage for the standalone semantic-index command surface."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]


def _run(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run(
        [sys.executable, "-m", "ipfs_datasets_py.cli.semantic_index_cli", *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_help_and_all_commands_use_local_store(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "module.py"
    source.write_text("def first():\n    return 1\n", encoding="utf-8")
    store = tmp_path / "store"

    assert _run("--help", cwd=tmp_path).returncode == 0
    first = _run("scan", str(repo), "--store", str(store), cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    old = json.loads(first.stdout)
    source.write_text("def first():\n    return 2\n", encoding="utf-8")
    second = _run("scan", str(repo), "--store", str(store), cwd=tmp_path)
    assert second.returncode == 0, second.stderr
    new = json.loads(second.stdout)

    changed = _run("diff", old["state_cid"], new["state_cid"], "--store", str(store), cwd=tmp_path)
    assert changed.returncode == 0, changed.stderr
    assert json.loads(changed.stdout)["previous_state_cid"] == old["state_cid"]
    symbol = new["symbols"][0]["stable_id"]
    assert _run("impact", str(repo), symbol, "--store", str(store), cwd=tmp_path).returncode == 0
    assert _run("explain", str(repo), symbol, "--store", str(store), cwd=tmp_path).returncode == 0
    assert json.loads(_run("state-root", str(repo), "--store", str(store), cwd=tmp_path).stdout)["state_cid"] == new["state_cid"]
    assert _run("watch", str(repo), "--store", str(store), "--once", cwd=tmp_path).returncode == 0


def test_state_file_and_failures_are_stable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def item():\n    pass\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    scanned = _run("scan", str(repo), "--output", str(state_file), cwd=tmp_path)
    assert scanned.returncode == 0
    assert _run("diff", str(state_file), str(state_file), cwd=tmp_path).returncode == 0
    state_file.write_text("{broken", encoding="utf-8")
    failure = _run("diff", str(state_file), str(state_file), cwd=tmp_path)
    assert failure.returncode != 0
    assert "Traceback" not in failure.stderr
