"""OS isolation contract for retained-replay workers."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    assert_kernel_network_namespace_is_closed,
    build_isolated_retained_replay_docker_command,
    docker_is_rootless,
    run_isolated_retained_replay_worker,
)


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
    reason="live Docker isolation smoke is opt-in",
)
def test_live_docker_network_none_closes_inet_routing() -> None:
    workdir = Path(__file__).resolve().parents[3]
    completed = run_isolated_retained_replay_worker(
        [
            "-c",
            (
                "from ipfs_datasets_py.processors.legal_scrapers.state_scrapers"
                ".retained_replay_isolated_worker import "
                "assert_kernel_network_namespace_is_closed; "
                "assert_kernel_network_namespace_is_closed(); "
                "print('isolated-ok')"
            ),
        ],
        workdir=workdir,
    )
    assert "isolated-ok" in completed.stdout
