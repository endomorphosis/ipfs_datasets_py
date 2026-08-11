"""Process-level tests for the pre-import paired accelerator binding."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRY_ROOT = REPO_ROOT / "scripts/ops/agent_supervisor"
CONFIG_RELATIVE = "config/agent_supervisor_legal_corpora_reindex_scheduler.json"


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def paired_layout(tmp_path: Path) -> tuple[Path, Path, str]:
    repository = tmp_path / "ipfs_datasets_py"
    entry = repository / "scripts/ops/agent_supervisor"
    entry.mkdir(parents=True)
    for name in (
        "configured_board_scheduler.py",
        "implementation_daemon_entry.py",
        "implementation_supervisor_entry.py",
        "multi_supervisor_entry.py",
        "paired_accelerator_bootstrap.py",
    ):
        shutil.copy2(ENTRY_ROOT / name, entry / name)

    paired = tmp_path / "ipfs_accelerate_py"
    paired.mkdir()
    _run_git(paired, "init", "-b", "main")
    _run_git(paired, "config", "user.name", "Paired Bootstrap Test")
    _run_git(paired, "config", "user.email", "paired@example.invalid")
    _write(paired / ".gitignore", "__pycache__/\n")
    _write(paired / "ipfs_accelerate_py/__init__.py", "")
    _write(paired / "ipfs_accelerate_py/agent_supervisor/__init__.py", "")
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/runtime/__init__.py",
        "",
    )
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/runtime/"
        "configured_board_scheduler.py",
        """
import json
import os
import sys

def configured_board_common_args(_board, *, implement):
    return ()

def main():
    print(json.dumps({
        "origin": __file__,
        "pythonpath": os.environ.get("PYTHONPATH"),
        "required": os.environ.get("IPFS_ACCELERATE_PAIRED_ATTESTATION_REQUIRED"),
        "sys_path_0": sys.path[0],
    }, sort_keys=True))
    return 0
""".lstrip(),
    )
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/runtime/"
        "multi_supervisor_runner.py",
        """
import json

def main(_argv=None):
    print(json.dumps({"origin": __file__, "role": "multi"}, sort_keys=True))
    return 0
""".lstrip(),
    )
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/todo_daemon/__init__.py",
        "",
    )
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/todo_daemon/"
        "implementation_supervisor.py",
        """
import json
import os
import sys

def main():
    print(json.dumps({
        "origin": __file__,
        "pythonpath": os.environ.get("PYTHONPATH"),
        "required": os.environ.get("IPFS_ACCELERATE_PAIRED_ATTESTATION_REQUIRED"),
        "sys_path_0": sys.path[0],
    }, sort_keys=True))
    return 0
""".lstrip(),
    )
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/todo_daemon/"
        "implementation_daemon.py",
        """
import json

def main(_argv=None):
    print(json.dumps({"origin": __file__, "role": "daemon"}, sort_keys=True))
    return 0
""".lstrip(),
    )
    _run_git(paired, "add", ".")
    _run_git(paired, "commit", "-m", "seed paired runtime")
    gitlink_target = _run_git(paired, "rev-parse", "HEAD")
    _run_git(
        paired,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{gitlink_target},ipfs_datasets_py",
    )
    _run_git(
        paired,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{gitlink_target},ipfs_accelerate_py/mcplusplus",
    )
    _run_git(paired, "commit", "-m", "seal unpopulated dataset gitlink")
    revision = _run_git(paired, "rev-parse", "HEAD")
    (paired / "ipfs_datasets_py").mkdir()
    (paired / "ipfs_accelerate_py/mcplusplus").mkdir()

    nested = repository / "ipfs_accelerate_py"
    _write(nested / "ipfs_accelerate_py/__init__.py", "")
    _write(nested / "ipfs_accelerate_py/agent_supervisor/__init__.py", "")
    _write(
        nested / "ipfs_accelerate_py/agent_supervisor/runtime/__init__.py",
        "",
    )
    _write(
        nested / "ipfs_accelerate_py/agent_supervisor/runtime/"
        "configured_board_scheduler.py",
        """
import json

def configured_board_common_args(_board, *, implement):
    return ()

def main():
    print(json.dumps({"origin": __file__, "role": "generic"}, sort_keys=True))
    return 0
""".lstrip(),
    )
    _write(
        nested / "ipfs_accelerate_py/agent_supervisor/todo_daemon/__init__.py",
        "",
    )
    _write(
        nested / "ipfs_accelerate_py/agent_supervisor/todo_daemon/"
        "implementation_supervisor.py",
        """
import json

def main():
    print(json.dumps({"origin": __file__, "role": "generic-implementation"}, sort_keys=True))
    return 0
""".lstrip(),
    )

    config = {
        "schema": (
            "ipfs_accelerate_py.agent_supervisor.legal_corpora_reindex."
            "scheduler_config@1"
        ),
        "source_binding": {
            "paired_accelerator": {
                "sibling_path": "../ipfs_accelerate_py",
                "repository_name": "ipfs_accelerate_py",
                "required_revision": revision,
                "require_clean_worktree": True,
                "require_exact_revision": True,
            }
        },
    }
    _write(repository / CONFIG_RELATIVE, json.dumps(config) + "\n")
    generic_config_relative = (
        "config/agent_supervisor_uscode_sparse_graphrag_scheduler.json"
    )
    _write(
        repository / generic_config_relative,
        json.dumps({"schema": "generic-test@1"}) + "\n",
    )
    _write(
        repository / ".gitignore",
        "scripts/ops/agent_supervisor/__pycache__/\n"
        "scripts/ops/agent_supervisor/*.pyc\n"
        "scripts/ops/agent_supervisor/*.so\n",
    )
    _run_git(repository, "init", "-b", "main")
    _run_git(repository, "config", "user.name", "Dataset Bootstrap Test")
    _run_git(repository, "config", "user.email", "dataset@example.invalid")
    _run_git(
        repository,
        "add",
        ".gitignore",
        CONFIG_RELATIVE,
        generic_config_relative,
        "scripts/ops/agent_supervisor",
    )
    _run_git(repository, "commit", "-m", "seal scheduler control sources")
    return repository, paired, revision


def _hostile_environment(repository: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository)
    environment["PYTHONUSERBASE"] = str(repository / "hostile-user-base")
    environment["GIT_DIR"] = str(repository / "hostile-git-dir")
    return environment


def _run_configured(repository: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--config",
            CONFIG_RELATIVE,
            "launch",
            "--dry-run",
        ],
        cwd=repository,
        env=_hostile_environment(repository),
        text=True,
        capture_output=True,
        check=False,
    )


def test_configured_launcher_prefers_and_attests_exact_sibling_before_import(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, paired, _ = paired_layout
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--config",
            CONFIG_RELATIVE,
            "launch",
            "--dry-run",
        ],
        cwd=repository,
        env=_hostile_environment(repository),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (
        Path(payload["origin"]).resolve()
        == (
            paired / "ipfs_accelerate_py/agent_supervisor/runtime/"
            "configured_board_scheduler.py"
        ).resolve()
    )
    assert payload["pythonpath"] == str(paired.resolve())
    assert payload["required"] == "1"
    assert payload["sys_path_0"] == str(paired.resolve())


def test_configured_launcher_preserves_legacy_uscode_config_import(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, _, _ = paired_layout
    nested = repository / "ipfs_accelerate_py"
    environment = _hostile_environment(repository)
    environment["PYTHONPATH"] = str(nested)
    result = subprocess.run(
        [
            sys.executable,
            "-P",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--config",
            "config/agent_supervisor_uscode_sparse_graphrag_scheduler.json",
            "launch",
            "--implement",
            "--dry-run",
        ],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (
        Path(payload["origin"]).resolve()
        == (
            nested / "ipfs_accelerate_py/agent_supervisor/runtime/"
            "configured_board_scheduler.py"
        ).resolve()
    )
    assert payload["role"] == "generic"


def test_detached_implementation_entry_reattests_and_rejects_nested_shadow(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, paired, revision = paired_layout
    environment = _hostile_environment(repository)
    environment.update(
        {
            "IPFS_ACCELERATE_PAIRED_ATTESTATION_REQUIRED": "1",
            "IPFS_ACCELERATE_PAIRED_ROOT": str(paired),
            "IPFS_ACCELERATE_PAIRED_REVISION": revision,
            "IPFS_ACCELERATE_PAIRED_CONTROL_ROOT": str(repository),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/implementation_supervisor_entry.py"
            ),
        ],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (
        Path(payload["origin"]).resolve()
        == (
            paired / "ipfs_accelerate_py/agent_supervisor/todo_daemon/"
            "implementation_supervisor.py"
        ).resolve()
    )
    assert payload["required"] == "1"
    assert payload["sys_path_0"] == str(paired.resolve())


def test_implementation_entry_preserves_legacy_unpaired_import(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, _, _ = paired_layout
    nested = repository / "ipfs_accelerate_py"
    environment = _hostile_environment(repository)
    environment["PYTHONPATH"] = str(nested)
    environment.pop("IPFS_ACCELERATE_PAIRED_ATTESTATION_REQUIRED", None)
    result = subprocess.run(
        [
            sys.executable,
            "-P",
            str(
                repository
                / "scripts/ops/agent_supervisor/implementation_supervisor_entry.py"
            ),
        ],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (
        Path(payload["origin"]).resolve()
        == (
            nested / "ipfs_accelerate_py/agent_supervisor/todo_daemon/"
            "implementation_supervisor.py"
        ).resolve()
    )
    assert payload["role"] == "generic-implementation"


@pytest.mark.parametrize(
    ("entry_name", "expected_relative", "expected_role"),
    (
        (
            "multi_supervisor_entry.py",
            "ipfs_accelerate_py/agent_supervisor/runtime/multi_supervisor_runner.py",
            "multi",
        ),
        (
            "implementation_daemon_entry.py",
            (
                "ipfs_accelerate_py/agent_supervisor/todo_daemon/"
                "implementation_daemon.py"
            ),
            "daemon",
        ),
    ),
)
def test_detached_child_entries_reuse_the_exact_attested_checkout(
    paired_layout: tuple[Path, Path, str],
    entry_name: str,
    expected_relative: str,
    expected_role: str,
) -> None:
    repository, paired, revision = paired_layout
    environment = _hostile_environment(repository)
    environment.update(
        {
            "IPFS_ACCELERATE_PAIRED_ATTESTATION_REQUIRED": "1",
            "IPFS_ACCELERATE_PAIRED_ROOT": str(paired),
            "IPFS_ACCELERATE_PAIRED_REVISION": revision,
            "IPFS_ACCELERATE_PAIRED_CONTROL_ROOT": str(repository),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(repository / "scripts/ops/agent_supervisor" / entry_name),
        ],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["origin"]).resolve() == (paired / expected_relative).resolve()
    assert payload["role"] == expected_role


def test_bootstrap_fails_closed_on_dirty_or_wrong_revision(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, paired, _ = paired_layout
    _write(paired / "untracked.txt", "dirty\n")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--config",
            CONFIG_RELATIVE,
            "launch",
            "--dry-run",
        ],
        cwd=repository,
        env=_hostile_environment(repository),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "paired accelerator worktree is not clean" in result.stderr


def test_bootstrap_rejects_ambiguous_config_arguments_before_import(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, _, _ = paired_layout
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--config",
            CONFIG_RELATIVE,
            f"--config={CONFIG_RELATIVE}",
            "launch",
            "--dry-run",
        ],
        cwd=repository,
        env=_hostile_environment(repository),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "--config is duplicated" in result.stderr

    abbreviated = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--conf",
            CONFIG_RELATIVE,
            "launch",
            "--dry-run",
        ],
        cwd=repository,
        env=_hostile_environment(repository),
        text=True,
        capture_output=True,
        check=False,
    )
    assert abbreviated.returncode != 0
    assert "--config must not use an abbreviated option" in abbreviated.stderr


def test_bootstrap_rejects_ignored_package_payload_before_import(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, paired, _ = paired_layout
    _write(
        paired / "ipfs_accelerate_py/agent_supervisor/runtime/__pycache__/"
        "configured_board_scheduler.cpython-312.pyc",
        "forged ignored payload\n",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(
                repository
                / "scripts/ops/agent_supervisor/configured_board_scheduler.py"
            ),
            "--repo-root",
            str(repository),
            "--config",
            CONFIG_RELATIVE,
            "launch",
            "--dry-run",
        ],
        cwd=repository,
        env=_hostile_environment(repository),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "ignored executable content" in result.stderr


@pytest.mark.parametrize(
    "shadow_relative",
    (
        "scripts/ops/agent_supervisor/configured_board_scheduler.pyc",
        (
            "scripts/ops/agent_supervisor/__pycache__/"
            "configured_board_scheduler.cpython-312.pyc"
        ),
        "scripts/ops/agent_supervisor/paired_accelerator_bootstrap.abi3.so",
        (
            "scripts/ops/agent_supervisor/__pycache__/"
            "paired_accelerator_bootstrap.cpython-312.pyc"
        ),
    ),
)
def test_entry_rejects_ignored_or_untracked_local_import_shadows(
    paired_layout: tuple[Path, Path, str],
    shadow_relative: str,
) -> None:
    repository, _, _ = paired_layout
    _write(repository / shadow_relative, "forged local import shadow\n")

    result = _run_configured(repository)

    assert result.returncode != 0
    assert "ignored or untracked import shadow" in result.stderr


def test_entry_rejects_non_default_control_source_index_flags(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, _, _ = paired_layout
    helper_relative = "scripts/ops/agent_supervisor/paired_accelerator_bootstrap.py"
    _run_git(repository, "update-index", "--assume-unchanged", helper_relative)

    result = _run_configured(repository)

    assert result.returncode != 0
    assert "non-default index flags" in result.stderr


def test_bootstrap_rejects_assume_unchanged_paired_source(
    paired_layout: tuple[Path, Path, str],
) -> None:
    repository, paired, _ = paired_layout
    source_relative = (
        "ipfs_accelerate_py/agent_supervisor/runtime/configured_board_scheduler.py"
    )
    _run_git(paired, "update-index", "--assume-unchanged", source_relative)
    _write(paired / source_relative, "raise RuntimeError('forged paired source')\n")

    result = _run_configured(repository)

    assert result.returncode != 0
    assert "non-default index flags" in result.stderr


@pytest.mark.parametrize(
    "gitlink_relative",
    ("ipfs_datasets_py", "ipfs_accelerate_py/mcplusplus"),
)
def test_bootstrap_rejects_populated_paired_gitlinks(
    paired_layout: tuple[Path, Path, str],
    gitlink_relative: str,
) -> None:
    repository, paired, _ = paired_layout
    _write(paired / gitlink_relative / "hostile.py", "raise RuntimeError('shadow')\n")

    result = _run_configured(repository)

    assert result.returncode != 0
    assert "gitlink must remain unpopulated" in result.stderr
