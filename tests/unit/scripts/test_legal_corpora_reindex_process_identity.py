"""Exact argv recognition for the legal-corpora supervisor process tree."""

import json
import os
import subprocess
from pathlib import Path

from scripts.ops.legal_corpora_reindex.status import (
    IMPLEMENTATION_DAEMON_ENTRY,
    IMPLEMENTATION_DAEMON_MODULE,
    IMPLEMENTATION_SUPERVISOR_ENTRY,
    MULTI_SUPERVISOR_ENTRY,
    MULTI_SUPERVISOR_MODULE,
    _daemon_command,
    _master_command,
    _outer_command,
)


def _paired(repo: Path, relative: str) -> list[str]:
    return [
        "/usr/bin/python3.12",
        "-I",
        "-S",
        "-B",
        str((repo / relative).resolve()),
        "--repo-root",
        str(repo),
    ]


def test_paired_process_entries_require_exact_interpreter_flags_and_path(
    tmp_path: Path,
) -> None:
    assert _master_command(_paired(tmp_path, MULTI_SUPERVISOR_ENTRY), tmp_path)
    assert _outer_command(_paired(tmp_path, IMPLEMENTATION_SUPERVISOR_ENTRY), tmp_path)
    assert _daemon_command(_paired(tmp_path, IMPLEMENTATION_DAEMON_ENTRY), tmp_path)

    for mutation in (
        ["python3", "-I", "-S", "-B"],
        ["/usr/bin/python3.12", "-I", "-B", "-S"],
        ["/usr/bin/python3.12", "-I", "-S", "-B", "extra.py"],
    ):
        command = [*mutation, str((tmp_path / MULTI_SUPERVISOR_ENTRY).resolve())]
        assert not _master_command(command, tmp_path)

    wrong_root = tmp_path / "other"
    assert not _daemon_command(
        _paired(wrong_root, IMPLEMENTATION_DAEMON_ENTRY), tmp_path
    )


def test_legacy_module_and_direct_outer_shapes_remain_recognized(
    tmp_path: Path,
) -> None:
    assert _master_command(
        ["python3", "-m", MULTI_SUPERVISOR_MODULE, "--repo-root", str(tmp_path)],
        tmp_path,
    )
    assert _daemon_command(
        [
            "python3",
            "-m",
            IMPLEMENTATION_DAEMON_MODULE,
            "--repo-root",
            str(tmp_path),
        ],
        tmp_path,
    )
    assert _outer_command(
        [
            "python3",
            str((tmp_path / IMPLEMENTATION_SUPERVISOR_ENTRY).resolve()),
        ],
        tmp_path,
    )

    assert not _daemon_command(
        ["python3", "-m", f"{IMPLEMENTATION_DAEMON_MODULE}.near"], tmp_path
    )
    assert not _master_command(
        ["python3", f"--module={MULTI_SUPERVISOR_MODULE}"], tmp_path
    )


def test_validation_probe_rejects_hostile_inherited_runtime_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    accelerator_root = (repo_root.parent / "ipfs_accelerate_py").resolve()
    source = r"""
import json
import sys

dataset_root, accelerator_root = sys.argv[1:]
sys.path[:0] = [dataset_root, accelerator_root]
from ipfs_accelerate_py.agent_supervisor.runtime.configured_board_scheduler import configured_board_launch_environment
from scripts.ops.legal_corpora_reindex.preflight import _probe_python_modules

plan = {
    "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON": "/usr/bin/python3.12",
    "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHONPATH": (
        "/opt/ipfs-accelerate-validation-python-74c4a6ff/site-packages:"
        "/opt/ipfs-accelerate-controller-duckdb-3781192a-1.5.2/site-packages"
    ),
    "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON_MODULES": (
        "huggingface_hub,numpy,pyarrow,duckdb"
    ),
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
}
effective = configured_board_launch_environment(
    plan,
    inherited_environment={"IPFS_ACCELERATE_AGENT_VALIDATION_PATH": "/tmp"},
)
imports, receipt = _probe_python_modules(
    ("huggingface_hub", "numpy", "pyarrow", "duckdb"),
    environment=effective,
)
print(json.dumps({"imports": imports, "reason": receipt.get("reason")}, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            "/usr/bin/python3.12",
            "-I",
            "-S",
            "-B",
            "-c",
            source,
            str(repo_root),
            str(accelerator_root),
        ],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "imports": {
            "huggingface_hub": False,
            "numpy": False,
            "pyarrow": False,
            "duckdb": False,
        },
        "reason": "validation_python_module_probe_unavailable",
    }
