"""Subprocess coverage for the dedicated semantic-index command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update({"IPFS_DATASETS_AUTO_INSTALL": "0", "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0"})
    return subprocess.run(
        [sys.executable, "-m", "ipfs_datasets_py.cli.semantic_index_cli", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _git_repo(path: Path, source: str = "def example(value: int) -> int:\n    return value\n") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "sample.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "semantic-index@test"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "semantic-index"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
    return path


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
    # Canonical JSON: sorted keys, compact separators, stable round-trip.
    assert root.stdout == json.dumps(json.loads(root.stdout), sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def test_bad_input_has_no_traceback(tmp_path: Path) -> None:
    result = _run("diff", str(tmp_path / "missing.json"), str(tmp_path / "missing.json"))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "semantic-index: error:" in result.stderr


def test_default_scan_excludes_store_and_keeps_second_root_stable(tmp_path: Path) -> None:
    """Default store lives under .semantic-index (excluded); second scan is stable."""
    repo = _git_repo(tmp_path / "repo")
    first = _run("scan", str(repo))
    assert first.returncode == 0, first.stderr
    state1 = json.loads(first.stdout)
    store = repo / ".semantic-index"
    assert store.is_dir()
    assert (store / ".roots.lock").exists() or any(store.rglob(".roots.lock"))
    artifact_paths = {item["path"] for item in state1["artifacts"]}
    assert not any("semantic-index" in path or path.endswith(".roots.lock") for path in artifact_paths)
    assert not any(".semantic-index" in path for path in artifact_paths)

    second = _run("scan", str(repo))
    assert second.returncode == 0, second.stderr
    state2 = json.loads(second.stdout)
    assert state2["state_cid"] == state1["state_cid"]
    root = json.loads(_run("state-root", str(repo)).stdout)
    assert root["state_cid"] == state1["state_cid"]


def test_impact_explain_watch_observe_edit_and_publish_watch_root(tmp_path: Path) -> None:
    """After a stored scan, source edits are visible to impact/explain/watch --once."""
    repo = _git_repo(tmp_path / "repo")
    scanned = _run("scan", str(repo))
    assert scanned.returncode == 0, scanned.stderr
    before = json.loads(scanned.stdout)
    symbol = next(item for item in before["symbols"] if item["qualified_name"].endswith(".example"))
    old_version = symbol["version_cid"]
    old_state = before["state_cid"]

    (repo / "sample.py").write_text(
        "def example(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )

    impact = _run("impact", str(repo), "sample.py")
    assert impact.returncode == 0, impact.stderr
    impact_payload = json.loads(impact.stdout)
    assert impact_payload["state_cid"] != old_state
    assert symbol["stable_id"] in impact_payload["changed_symbol_ids"]

    explained = _run("explain", str(repo), symbol["stable_id"])
    assert explained.returncode == 0, explained.stderr
    explain_payload = json.loads(explained.stdout)
    assert explain_payload["state_cid"] != old_state
    assert explain_payload["symbol"]["stable_id"] == symbol["stable_id"]
    assert explain_payload["symbol"]["version_cid"] != old_version

    # impact/explain must not silently republish; stored root stays pre-edit until watch/scan.
    stored_before_watch = json.loads(_run("state-root", str(repo)).stdout)
    assert stored_before_watch["state_cid"] == old_state

    watched = _run("watch", str(repo), "--once")
    assert watched.returncode == 0, watched.stderr
    watch_payload = json.loads(watched.stdout)
    assert watch_payload["state_cid"] != old_state
    assert watch_payload["state_cid"] == impact_payload["state_cid"]

    published = _run("state-root", str(repo))
    assert published.returncode == 0, published.stderr
    assert json.loads(published.stdout)["state_cid"] == watch_payload["state_cid"]


def test_missing_state_root_is_nonzero(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "sample.py").write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    result = _run("state-root", str(repo))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "no published state root" in result.stderr
    assert result.stdout == ""


def test_cli_errors_are_deterministic(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    first = _run("diff", str(missing), str(missing))
    second = _run("diff", str(missing), str(missing))
    assert first.returncode == second.returncode != 0
    assert "Traceback" not in first.stderr
    first_errors = [line for line in first.stderr.splitlines() if line.startswith("semantic-index: error:")]
    second_errors = [line for line in second.stderr.splitlines() if line.startswith("semantic-index: error:")]
    assert first_errors
    assert first_errors == second_errors
