"""OS-isolated worker for retained state-law replay.

A Python audit hook cannot prove zero network against pre-import sockets,
inherited descriptors, AF_UNIX delegation, or mutated runtime constants.
Authorization for retained replay therefore requires a fresh worker whose
network namespace is closed by the kernel.

On this host that isolation is Docker ``--network none``.  Rootless Docker
maps container uid 0 to the invoking user, so the worker must not pass
``--user``; that flag remaps away from the host uid and cannot read
``$HOME``.  ``unshare --net`` and ``bwrap --unshare-net`` are unavailable
here without additional privileges.
"""

from __future__ import annotations

import argparse
import errno
import os
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from ...legal_data.state_laws_multifetch_acquisition import (
    StateLawRetainedReplayOnlyError,
)


DEFAULT_ISOLATED_WORKER_IMAGE = "python:3.12-slim"
_HOST_USR = Path("/usr")
_DOCKER_INFO_ROOTLESS_MARKERS = ("rootless",)


class IsolatedRetainedReplayWorkerError(StateLawRetainedReplayOnlyError):
    """The OS-isolated retained-replay worker cannot be authorized."""


def docker_is_rootless(
    docker_info: str | None = None,
) -> bool:
    """Return whether the local Docker daemon is rootless."""

    text = docker_info
    if text is None:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if completed.returncode != 0:
            raise IsolatedRetainedReplayWorkerError(
                "docker info failed; cannot determine rootless isolation"
            )
    lowered = text.lower()
    return any(marker in lowered for marker in _DOCKER_INFO_ROOTLESS_MARKERS)


def assert_kernel_network_namespace_is_closed() -> None:
    """Fail closed unless this process has no IPv4 route to the Internet."""

    try:
        socket.create_connection(("1.1.1.1", 53), timeout=0.25)
    except OSError as exc:
        timeout = isinstance(exc, TimeoutError) or getattr(exc, "errno", None) in {
            errno.ETIMEDOUT,
            getattr(errno, "ETIME", errno.ETIMEDOUT),
        }
        if timeout:
            raise IsolatedRetainedReplayWorkerError(
                "network probe timed out; network namespace is not closed"
            ) from exc
        return
    raise IsolatedRetainedReplayWorkerError(
        "network probe connected; network namespace is not closed"
    )


def build_isolated_retained_replay_docker_command(
    *,
    argv: Sequence[str],
    workdir: Path,
    home: Path | None = None,
    python_executable: str | None = None,
    image: str = DEFAULT_ISOLATED_WORKER_IMAGE,
    rootless: bool | None = None,
    extra_environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Return a ``docker run --network none`` argv for one retained worker."""

    if not argv:
        raise IsolatedRetainedReplayWorkerError(
            "isolated retained-replay worker requires a command"
        )
    workdir = Path(workdir).expanduser().resolve()
    if workdir.is_symlink() or not workdir.is_dir():
        raise IsolatedRetainedReplayWorkerError(
            "isolated retained-replay workdir must be a regular directory"
        )
    home_path = Path(home or Path.home()).expanduser().resolve()
    python_path = Path(python_executable or sys.executable).resolve()
    site_packages = home_path / ".local" / "lib" / "python3.12" / "site-packages"
    pythonpath = os.pathsep.join(
        (
            str(workdir),
            str(site_packages),
        )
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--entrypoint",
        str(python_path),
        "-e",
        f"HOME={home_path}",
        "-e",
        f"PYTHONPATH={pythonpath}",
        "-v",
        f"{_HOST_USR}:{_HOST_USR}:ro",
        "-v",
        f"{home_path}:{home_path}",
        "-v",
        f"{workdir}:{workdir}",
        "-v",
        "/tmp:/tmp",
        "-w",
        str(workdir),
    ]
    if rootless is None:
        rootless = docker_is_rootless()
    if not rootless:
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    for key, value in sorted((extra_environment or {}).items()):
        if key in {"HOME", "PYTHONPATH"}:
            continue
        command.extend(["-e", f"{key}={value}"])
    command.append(image)
    command.extend(str(part) for part in argv)
    if "--network" in command[4:]:
        # The constructed argv must have exactly the leading ``--network none``.
        # Guard against callers splicing host networking back in.
        network_flags = [
            command[index + 1]
            for index, part in enumerate(command)
            if part == "--network" and index + 1 < len(command)
        ]
        if network_flags != ["none"]:
            raise IsolatedRetainedReplayWorkerError(
                "isolated retained-replay worker must use --network none only"
            )
    if "--privileged" in command or "--pid" in command:
        raise IsolatedRetainedReplayWorkerError(
            "isolated retained-replay worker must not share host privileges"
        )
    return command


def run_isolated_retained_replay_worker(
    argv: Sequence[str],
    *,
    workdir: Path,
    extra_environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Launch ``argv`` inside a closed network namespace and return the result."""

    command = build_isolated_retained_replay_docker_command(
        argv=argv,
        workdir=workdir,
        extra_environment=extra_environment,
    )
    completed = subprocess.run(
        command,
        cwd=str(workdir),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise IsolatedRetainedReplayWorkerError(
            "isolated retained-replay worker exited "
            f"{completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}"
        )
    return completed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a retained-replay command in Docker --network none.",
    )
    parser.add_argument(
        "--workdir",
        default=os.getcwd(),
        help="Repository workdir mounted into the isolated worker",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Python arguments after the interpreter (use -- to separate)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _forwarded_worker_environment(
    source: Mapping[str, str],
) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in source.items():
        if key.startswith(("STATE_LAWS_", "LEGAL_", "LEGAL_SCRAPER_", "PYTHON")):
            forwarded[key] = value
    return forwarded


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    command = [part for part in args.command if part != "--"]
    if not command:
        raise IsolatedRetainedReplayWorkerError(
            "usage: retained_replay_isolated_worker.py -- <python-args>"
        )
    completed = run_isolated_retained_replay_worker(
        command,
        workdir=Path(args.workdir),
        extra_environment=_forwarded_worker_environment(os.environ),
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
