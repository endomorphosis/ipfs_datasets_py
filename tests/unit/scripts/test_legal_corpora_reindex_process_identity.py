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

VALIDATION_PYTHONPATH = (
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
PLAYWRIGHT_BROWSERS_PATH = (
    "/opt/ipfs-accelerate-legal-playwright-3c176393527b"
)
VALIDATION_MODULES = (
    "aiohttp",
    "anyio",
    "bs4",
    "cachetools",
    "cryptography",
    "datasets",
    "duckdb",
    "faiss",
    "fsspec",
    "httpx",
    "huggingface_hub",
    "hypothesis",
    "jsonschema",
    "multiformats",
    "networkx",
    "numpy",
    "pandas",
    "playwright",
    "pyarrow",
    "pydantic",
    "pydantic_settings",
    "pypdf",
    "PyPDF2",
    "pytest",
    "pytest_asyncio",
    "pytest_benchmark",
    "pytest_cov",
    "pytest_mock",
    "pytest_parallel",
    "pytest_timeout",
    "xdist",
    "yaml",
    "rdflib",
    "requests",
    "sklearn",
    "scipy",
    "sentence_transformers",
    "torch",
    "tqdm",
    "transformers",
    "trio",
    "urllib3",
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


def test_configured_board_launch_environment_is_exact_and_clears_hostile_values() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    accelerator_root = (repo_root.parent / "ipfs_accelerate_py").resolve()
    source = r"""
import json
import sys
from pathlib import Path

dataset_root, accelerator_root = sys.argv[1:]
sys.path[:0] = [dataset_root, accelerator_root]
from ipfs_accelerate_py.agent_supervisor.runtime.configured_board_scheduler import (
    SCHEDULER_CONTROLLED_ENV_NAMES,
    configured_board_launch_environment,
    configured_board_launch_plan,
    load_configured_board,
)

board = load_configured_board(
    Path(dataset_root)
    / "config/agent_supervisor_legal_corpora_reindex_scheduler.json",
    repo_root=dataset_root,
)
plan = configured_board_launch_plan(
    board,
    implement=True,
    detach=True,
    stamp="TEST",
)
hostile = {name: f"hostile-{index}" for index, name in enumerate(SCHEDULER_CONTROLLED_ENV_NAMES)}
hostile["UNCONTROLLED_SENTINEL"] = "preserved"
effective = configured_board_launch_environment(
    plan["environment"],
    inherited_environment=hostile,
)
cleared = configured_board_launch_environment(
    {},
    inherited_environment=hostile,
)
print(
    json.dumps(
        {
            "schema": plan["schema"],
            "plan_environment": plan["environment"],
            "effective_controlled": {
                name: effective.get(name) for name in SCHEDULER_CONTROLLED_ENV_NAMES
            },
            "cleared_controlled": {
                name: cleared.get(name) for name in SCHEDULER_CONTROLLED_ENV_NAMES
            },
            "effective_sentinel": effective.get("UNCONTROLLED_SENTINEL"),
            "cleared_sentinel": cleared.get("UNCONTROLLED_SENTINEL"),
        },
        sort_keys=True,
    )
)
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
    expected_environment = {
        "IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER": "grok_cli",
        "IPFS_ACCELERATE_AGENT_IMPLEMENTATION_FALLBACK_PROVIDER": "codex",
        "IPFS_ACCELERATE_AGENT_IMPLEMENTATION_FALLBACK_TRIGGER": (
            "primary_quota_exhausted"
        ),
        "IPFS_ACCELERATE_AGENT_GROK_MODEL": "grok-4.5",
        "IPFS_ACCELERATE_AGENT_CODEX_MODEL": "gpt-5.6-terra",
        "IPFS_ACCELERATE_AGENT_CODEX_REASONING_EFFORT": "medium",
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON": "/usr/bin/python3.12",
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHONPATH": VALIDATION_PYTHONPATH,
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON_MODULES": ",".join(
            VALIDATION_MODULES
        ),
        "IPFS_ACCELERATE_AGENT_VALIDATION_PLAYWRIGHT_BROWSERS_PATH": (
            PLAYWRIGHT_BROWSERS_PATH
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    assert payload["schema"] == (
        "ipfs_accelerate_py/agent-supervisor/configured-board-launch-plan@1"
    )
    assert payload["plan_environment"] == expected_environment
    assert payload["effective_controlled"] == expected_environment
    assert set(payload["cleared_controlled"].values()) == {None}
    assert payload["effective_sentinel"] == "preserved"
    assert payload["cleared_sentinel"] == "preserved"
