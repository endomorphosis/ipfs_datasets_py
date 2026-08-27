"""Host retained-replay worker contract: reuse local caches, never Docker-copy."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    EVIDENCE_ROOT_ENV,
    IsolatedRetainedReplayWorkerError,
    PAGE_CACHE_DIR_ENV,
    PENNSYLVANIA_CANARY_GENERATION,
    assert_kernel_network_namespace_is_closed,
    assert_workdir_does_not_contain_copied_evidence,
    authorize_hardlink_only_seed,
    authorize_host_evidence_root,
    authorize_host_retained_replay,
    authorize_pennsylvania_canary_not_republished,
    build_host_retained_replay_command,
    build_host_retained_replay_environment,
    build_isolated_retained_replay_docker_command,
    docker_is_rootless,
    local_ipfs_datasets_root,
    local_legal_page_cache_root,
    local_state_laws_root,
    run_host_retained_replay_worker,
    run_isolated_retained_replay_worker,
)


def _fake_host_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".ipfs_datasets" / "state_laws").mkdir(parents=True)
    (home / ".ipfs_datasets" / "legal_page_cache").mkdir(parents=True)
    return home


def test_host_worker_reuses_local_python_and_does_not_invoke_docker(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    command = build_host_retained_replay_command(
        argv=["-c", "print(123)"],
        workdir=workdir,
        python_executable="/usr/bin/python3",
    )

    assert Path(command[0]).resolve() == Path("/usr/bin/python3").resolve()
    assert "docker" not in command
    assert "--network" not in command
    assert local_state_laws_root() == Path.home().resolve() / ".ipfs_datasets" / "state_laws"
    assert local_legal_page_cache_root() == (
        Path.home().resolve() / ".ipfs_datasets" / "legal_page_cache"
    )
    assert local_ipfs_datasets_root() == Path.home().resolve() / ".ipfs_datasets"


def test_host_worker_rejects_docker_argv(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    with pytest.raises(IsolatedRetainedReplayWorkerError, match="must not invoke docker"):
        build_host_retained_replay_command(
            argv=["docker", "run", "--network", "none"],
            workdir=workdir,
            python_executable="/usr/bin/python3",
        )
    with pytest.raises(IsolatedRetainedReplayWorkerError, match="must not invoke docker"):
        build_host_retained_replay_command(
            argv=["/usr/bin/docker", "cp", "src", "dst"],
            workdir=workdir,
            python_executable="/usr/bin/python3",
        )


def test_host_worker_environment_pins_home_and_reuses_ipfs_datasets(
    tmp_path: Path,
) -> None:
    home = _fake_host_home(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    evidence = home / ".ipfs_datasets" / "state_laws" / "legal-corpora-reindex" / "xx"
    evidence.mkdir(parents=True)
    page_cache = home / ".ipfs_datasets" / "legal_page_cache"
    environment = build_host_retained_replay_environment(
        extra_environment={
            "HOME": str(home),
            EVIDENCE_ROOT_ENV: str(evidence),
            PAGE_CACHE_DIR_ENV: str(page_cache),
        },
        source={},
        home=home,
    )
    command, bound = authorize_host_retained_replay(
        argv=["-c", "print(123)"],
        workdir=workdir,
        extra_environment={
            "HOME": str(home),
            EVIDENCE_ROOT_ENV: str(evidence),
        },
        home=home,
        python_executable="/usr/bin/python3",
    )

    assert environment["HOME"] == str(home.resolve())
    assert environment[EVIDENCE_ROOT_ENV] == str(evidence.resolve())
    assert environment[PAGE_CACHE_DIR_ENV] == str(page_cache.resolve())
    assert "docker" not in command
    assert bound["HOME"] == str(home.resolve())
    assert bound[EVIDENCE_ROOT_ENV] == str(evidence.resolve())


def test_host_worker_rejects_copied_evidence_trees(tmp_path: Path) -> None:
    home = _fake_host_home(tmp_path)
    copied = tmp_path / "copied-evidence"
    copied.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    nested = workdir / ".ipfs_datasets"
    nested.mkdir()

    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="copied evidence trees are forbidden",
    ):
        authorize_host_evidence_root(copied, home=home)
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="copied evidence trees are forbidden",
    ):
        build_host_retained_replay_environment(
            extra_environment={EVIDENCE_ROOT_ENV: str(copied)},
            source={},
            home=home,
        )
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="copied .ipfs_datasets evidence tree",
    ):
        assert_workdir_does_not_contain_copied_evidence(workdir, home=home)
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="copied .ipfs_datasets evidence tree",
    ):
        build_host_retained_replay_command(
            argv=["-c", "print(123)"],
            workdir=workdir,
            python_executable="/usr/bin/python3",
            home=home,
        )


def test_host_worker_requires_hardlink_only_seeds(tmp_path: Path) -> None:
    home = _fake_host_home(tmp_path)
    destination = (
        home / ".ipfs_datasets" / "state_laws" / "legal-corpora-reindex" / "xx-v2"
    )
    destination.mkdir(parents=True)
    authorize_hardlink_only_seed(
        {
            "copied_file_count": 0,
            "network_io_performed": False,
            "destination_root": str(destination),
        },
        home=home,
    )
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="hardlink-only",
    ):
        authorize_hardlink_only_seed(
            {"copied_file_count": 4, "network_io_performed": False},
            home=home,
        )
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="must not perform network I/O",
    ):
        authorize_hardlink_only_seed(
            {"copied_file_count": 0, "network_io_performed": True},
            home=home,
        )


def test_host_worker_rejects_publish_and_keeps_pa_canary_sealed(
    tmp_path: Path,
) -> None:
    home = _fake_host_home(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    canary = (
        home
        / ".ipfs_datasets"
        / "state_laws"
        / "legal-corpora-reindex"
        / f"staging-pa-v{PENNSYLVANIA_CANARY_GENERATION}"
    )
    canary.mkdir(parents=True)
    fenced = (
        home
        / ".ipfs_datasets"
        / "state_laws"
        / "legal-corpora-reindex"
        / "staging-pa-v4"
    )
    fenced.mkdir(parents=True)

    authorize_pennsylvania_canary_not_republished(
        evidence_root=canary,
        jurisdiction="PA",
        publish_to_hf=False,
    )
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="sealed precedent and is not republished",
    ):
        authorize_pennsylvania_canary_not_republished(
            evidence_root=canary,
            jurisdiction="PA",
            publish_to_hf=True,
        )
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="sealed precedent",
    ):
        build_host_retained_replay_command(
            argv=["scripts/ops/legal_data/refresh_state_laws_corpus.py", "--publish-to-hf"],
            workdir=workdir,
            python_executable="/usr/bin/python3",
            home=home,
        )
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="fenced Pennsylvania v2-v6",
    ):
        authorize_pennsylvania_canary_not_republished(evidence_root=fenced)


def test_host_worker_child_sees_host_home_without_docker(
    tmp_path: Path,
) -> None:
    home = _fake_host_home(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    completed = run_host_retained_replay_worker(
        [
            "-c",
            (
                "import os, pathlib; "
                "print(os.environ['HOME']); "
                "print(pathlib.Path.home() / '.ipfs_datasets' / 'state_laws'); "
                "print(pathlib.Path.home() / '.ipfs_datasets' / 'legal_page_cache')"
            ),
        ],
        workdir=workdir,
        extra_environment={"HOME": str(home)},
        home=home,
        python_executable="/usr/bin/python3",
    )

    stdout = completed.stdout
    assert str(home.resolve()) in stdout
    assert str((home / ".ipfs_datasets" / "state_laws").resolve()) in stdout
    assert str((home / ".ipfs_datasets" / "legal_page_cache").resolve()) in stdout
    assert "docker" not in stdout.lower()


def test_docker_rootless_detection_reads_daemon_info() -> None:
    assert docker_is_rootless(docker_info="Server Version: 29\n Context: rootless\n")
    assert docker_is_rootless(docker_info="Security Options:\n  rootless\n")
    assert not docker_is_rootless(docker_info="Server Version: 29\n Context: default\n")


def test_isolated_worker_command_is_network_none_and_rootless_without_user(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    command = build_isolated_retained_replay_docker_command(
        argv=["-c", "print(123)"],
        workdir=workdir,
        home=home,
        python_executable="/usr/bin/python3",
        rootless=True,
        extra_environment={"STATE_LAWS_RETAINED_REPLAY_ONLY": "1"},
    )

    assert command[:6] == [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cap-drop",
    ]
    assert command.count("--network") == 1
    assert "--user" not in command
    assert "--privileged" not in command
    assert "--pid" not in command
    assert "host" not in command
    assert f"{home}:{home}" in command
    assert f"{workdir}:{workdir}" in command
    assert "/usr:/usr:ro" in command
    assert "STATE_LAWS_RETAINED_REPLAY_ONLY=1" in command


def test_isolated_worker_command_adds_user_only_when_not_rootless(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    command = build_isolated_retained_replay_docker_command(
        argv=["-c", "print(123)"],
        workdir=workdir,
        python_executable="/usr/bin/python3",
        rootless=False,
    )

    assert "--user" in command
    user_index = command.index("--user")
    assert command[user_index + 1] == f"{os.getuid()}:{os.getgid()}"
    assert command.count("--network") == 1
    assert command[command.index("--network") + 1] == "none"


def test_kernel_namespace_probe_fails_closed_on_successful_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _connected(_address: object, timeout: float = 0) -> socket.socket:
        return socket.socket()

    monkeypatch.setattr(socket, "create_connection", _connected)
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="network probe connected",
    ):
        assert_kernel_network_namespace_is_closed()


def test_kernel_namespace_probe_accepts_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(_address: object, timeout: float = 0) -> socket.socket:
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    assert_kernel_network_namespace_is_closed()


def test_kernel_namespace_probe_fails_closed_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _timeout(_address: object, timeout: float = 0) -> socket.socket:
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", _timeout)
    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="timed out",
    ):
        assert_kernel_network_namespace_is_closed()


@pytest.mark.skipif(
    os.environ.get("STATE_LAWS_ISOLATED_WORKER_LIVE", "").strip() not in {
        "1",
        "true",
        "yes",
        "on",
    },
    reason="live host retained-replay smoke is opt-in",
)
def test_live_host_worker_reuses_home_without_docker() -> None:
    workdir = Path(__file__).resolve().parents[3]
    completed = run_isolated_retained_replay_worker(
        [
            "-c",
            (
                "import os, pathlib; "
                "home = pathlib.Path.home(); "
                "assert os.environ['HOME'] == str(home); "
                "print(home / '.ipfs_datasets' / 'state_laws'); "
                "print('host-ok')"
            ),
        ],
        workdir=workdir,
    )
    assert "host-ok" in completed.stdout
    assert str(Path.home().resolve() / ".ipfs_datasets" / "state_laws") in (
        completed.stdout
    )
    assert "docker" not in completed.stdout.lower()
