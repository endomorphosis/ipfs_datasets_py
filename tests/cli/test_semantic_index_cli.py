"""Subprocess contracts for the dedicated semantic-index CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


MODULE = "ipfs_datasets_py.cli.semantic_index_cli"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", MODULE, *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_help_and_all_commands_use_the_hermetic_local_store(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "module.py").write_text("def value() -> int:\n    return 1\n", encoding="utf-8")

    help_result = _run("--help")
    assert help_result.returncode == 0
    assert all(command in help_result.stdout for command in ("scan", "diff", "impact", "explain", "watch", "state-root"))

    scan = _payload(_run("scan", str(repository)))
    state = scan["state"]
    assert isinstance(state, dict)
    state_cid = scan["state_cid"]
    assert isinstance(state_cid, str)
    stable_id = next(item["stable_id"] for item in state["symbols"] if item["qualified_name"] == "module.value")
    assert isinstance(stable_id, str)

    root = _payload(_run("state-root", str(repository)))
    assert root["state_cid"] == state_cid
    diff = _payload(_run("diff", state_cid, state_cid, "--store", str(repository / ".semantic-index")))
    assert diff["delta"]["previous_state_cid"] == state_cid
    impact = _payload(_run("impact", str(repository), "module.py"))
    assert stable_id in impact["impact"]["changed_symbol_ids"]
    explanation = _payload(_run("explain", str(repository), stable_id))
    assert explanation["explanation"]["symbol_id"] == stable_id
    watched = _payload(_run("watch", str(repository), "--once"))
    assert watched["event"] == "baseline"


def test_state_files_and_invalid_inputs_have_stable_errors(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "module.py").write_text("value = 1\n", encoding="utf-8")
    scan = _payload(_run("scan", str(repository)))
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(scan["state"]), encoding="utf-8")
    assert _payload(_run("diff", str(state_file), str(state_file)))["command"] == "diff"

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    result = _run("diff", str(broken), str(broken))
    assert result.returncode != 0
    assert result.stderr == "semantic-index: error: state file is malformed or corrupt\n"
    assert "Traceback" not in result.stderr
    missing = _run("diff", "not-a-state-cid", "not-a-state-cid")
    assert missing.returncode != 0
    assert missing.stderr == "semantic-index: error: state CID requires --store\n"
