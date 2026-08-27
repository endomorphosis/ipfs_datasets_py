"""Host-local worker for retained state-law replay.

Retained replay must reuse the existing on-disk evidence and caches under
``$HOME/.ipfs_datasets`` (state-law ledgers and the page cache).  It must
not Docker-copy those trees.  Seeds hardlink content objects
(``copied_file_count=0``); the process-wide network guard plus
``--retained-replay-only`` fail closed on a ledger miss before cache or
network.

Pennsylvania v7 is the sealed host-replay canary.  Remaining-state work
must not republish it, reuse fenced PA v2–v6 roots as current, or copy
PA evidence into a container.

A Docker ``--network none`` helper remains in this module as a non-default
diagnostic.  Production remaining-state work uses the host runner.
"""

from __future__ import annotations

import argparse
import errno
import os
import re
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from ...legal_data.state_laws_multifetch_acquisition import (
    StateLawRetainedReplayOnlyError,
)


DEFAULT_ISOLATED_WORKER_IMAGE = "python:3.12-slim"
_HOST_USR = Path("/usr")
_DOCKER_INFO_ROOTLESS_MARKERS = ("rootless",)
EVIDENCE_ROOT_ENV: Final = "STATE_LAWS_MULTIFETCH_EVIDENCE_ROOT"
PAGE_CACHE_DIR_ENV: Final = "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR"
FETCH_CACHE_DIR_ENV: Final = "LEGAL_SCRAPER_FETCH_CACHE_DIR"
PENNSYLVANIA_CANARY_JURISDICTION: Final = "PA"
PENNSYLVANIA_CANARY_GENERATION: Final = 7
PENNSYLVANIA_FENCED_GENERATIONS: Final = frozenset(range(2, 7))
_PA_GENERATION_RE = re.compile(
    r"(?:^|[-_/])pa-v(?P<generation>\d+)(?:[-_/]|$)",
    re.IGNORECASE,
)
_FORBIDDEN_HOST_ARGV_FLAGS: Final = frozenset(
    {
        "--network",
        "--pid",
        "--privileged",
        "--publish-to-hf",
    }
)


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


def _resolved_home(home: Path | str | None = None) -> Path:
    candidate = Path(home) if home is not None else Path.home()
    unresolved = candidate.expanduser()
    if unresolved.is_symlink():
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay HOME must not be a symlink"
        )
    resolved = unresolved.resolve()
    if not resolved.is_dir():
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay HOME must be a regular directory"
        )
    return resolved


def local_ipfs_datasets_root(home: Path | str | None = None) -> Path:
    """Return the host ``~/.ipfs_datasets`` tree remaining-state work reuses."""

    return _resolved_home(home) / ".ipfs_datasets"


def local_state_laws_root(home: Path | str | None = None) -> Path:
    """Return the host evidence root that remaining-state work must reuse."""

    return local_ipfs_datasets_root(home) / "state_laws"


def local_legal_page_cache_root(home: Path | str | None = None) -> Path:
    """Return the host page-cache root that remaining-state work must reuse."""

    return local_ipfs_datasets_root(home) / "legal_page_cache"


def local_legal_fetch_cache_root(home: Path | str | None = None) -> Path:
    """Return the host fetch-cache root that remaining-state work must reuse."""

    return local_ipfs_datasets_root(home) / "legal_fetch_cache"


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _regular_directory(path: Path, *, label: str) -> Path:
    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise IsolatedRetainedReplayWorkerError(
            f"{label} must be a regular directory, not a symlink copy"
        )
    resolved = unresolved.resolve()
    if not resolved.is_dir():
        raise IsolatedRetainedReplayWorkerError(
            f"{label} must be a regular directory"
        )
    return resolved


def _report_field(report: Any, name: str) -> Any:
    if isinstance(report, Mapping):
        return report.get(name)
    return getattr(report, name, None)


def _report_int(report: Any, name: str) -> int:
    value = _report_field(report, name)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise IsolatedRetainedReplayWorkerError(
            f"host retained-replay seed report {name} must be an integer"
        ) from None


def pennsylvania_generation_from_path(path: Path | str) -> int | None:
    """Return a Pennsylvania generation number encoded in ``path``, if any."""

    match = _PA_GENERATION_RE.search(str(path))
    if match is None:
        return None
    return int(match.group("generation"))


def authorize_hardlink_only_seed(
    report: Any,
    *,
    home: Path | str | None = None,
) -> None:
    """Fail closed unless a seed reused host objects without copying bytes."""

    copied = _report_int(report, "copied_file_count")
    if copied != 0:
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay seeds must be hardlink-only "
            f"(copied_file_count={copied})"
        )
    if _report_field(report, "network_io_performed") is True:
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay seeds must not perform network I/O"
        )
    destination = _report_field(report, "destination_root")
    if destination:
        authorize_host_evidence_root(Path(str(destination)), home=home)


def authorize_host_evidence_root(
    evidence_root: Path | str,
    *,
    home: Path | str | None = None,
) -> Path:
    """Require evidence to live under the host ``~/.ipfs_datasets/state_laws`` tree."""

    unresolved = Path(evidence_root).expanduser()
    if unresolved.is_symlink():
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay evidence root must not be a symlink copy"
        )
    resolved = unresolved.resolve()
    host_root = local_state_laws_root(home)
    if not _is_under(resolved, host_root):
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay evidence must live under "
            f"{host_root}; copied evidence trees are forbidden"
        )
    return resolved


def authorize_host_cache_path(
    cache_path: Path | str,
    *,
    home: Path | str | None = None,
    label: str = "cache",
) -> Path:
    """Require a cache directory to live under the host ``~/.ipfs_datasets`` tree."""

    unresolved = Path(cache_path).expanduser()
    if unresolved.is_symlink():
        raise IsolatedRetainedReplayWorkerError(
            f"host retained-replay {label} must not be a symlink copy"
        )
    resolved = unresolved.resolve()
    host_root = local_ipfs_datasets_root(home)
    if not _is_under(resolved, host_root):
        raise IsolatedRetainedReplayWorkerError(
            f"host retained-replay {label} must live under {host_root}; "
            "copied evidence trees are forbidden"
        )
    return resolved


def assert_workdir_does_not_contain_copied_evidence(
    workdir: Path | str,
    *,
    home: Path | str | None = None,
) -> None:
    """Reject a worktree-local copy of ``~/.ipfs_datasets``."""

    resolved_workdir = Path(workdir).expanduser().resolve()
    nested = resolved_workdir / ".ipfs_datasets"
    if not nested.exists() and not nested.is_symlink():
        return
    host_root = local_ipfs_datasets_root(home)
    if nested.resolve() != host_root:
        raise IsolatedRetainedReplayWorkerError(
            "workdir must not contain a copied .ipfs_datasets evidence tree"
        )


def authorize_pennsylvania_canary_not_republished(
    *,
    argv: Sequence[str] | None = None,
    evidence_root: Path | str | None = None,
    jurisdiction: str | None = None,
    publish_to_hf: bool = False,
) -> None:
    """Keep the sealed PA v7 canary unpublished and fenced PA roots unused."""

    command = [str(part) for part in (argv or ())]
    normalized_jurisdiction = str(jurisdiction or "").strip().upper()
    generation = (
        pennsylvania_generation_from_path(evidence_root)
        if evidence_root is not None
        else None
    )
    pa_involved = (
        normalized_jurisdiction == PENNSYLVANIA_CANARY_JURISDICTION
        or generation is not None
        or any(
            str(part).strip().upper() == PENNSYLVANIA_CANARY_JURISDICTION
            for part in command
        )
    )
    if "--publish-to-hf" in command or publish_to_hf:
        if pa_involved:
            raise IsolatedRetainedReplayWorkerError(
                "PA canary remains the sealed precedent and is not republished"
            )
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay must not republish; "
            "PA canary remains the sealed precedent"
        )
    if generation in PENNSYLVANIA_FENCED_GENERATIONS:
        raise IsolatedRetainedReplayWorkerError(
            "fenced Pennsylvania v2-v6 roots cannot be reused as current; "
            "PA v7 remains the sealed host-replay canary"
        )


def _forbidden_host_argv_reason(command: Sequence[str]) -> str | None:
    names = [Path(str(part)).name for part in command]
    tokens = [str(part) for part in command]
    if "docker" in names or "docker" in tokens:
        return "host retained-replay worker must not invoke docker"
    for flag in _FORBIDDEN_HOST_ARGV_FLAGS:
        if flag in tokens:
            if flag == "--publish-to-hf":
                return (
                    "host retained-replay must not republish; "
                    "PA canary remains the sealed precedent"
                )
            if flag == "--network":
                return (
                    "host retained-replay worker must not change network "
                    "namespaces"
                )
            return (
                "host retained-replay worker must not share host privileges"
            )
    for index, token in enumerate(tokens[:-1]):
        if Path(token).name == "docker" and tokens[index + 1] == "cp":
            return "host retained-replay worker must not copy evidence trees"
    return None


def build_host_retained_replay_command(
    *,
    argv: Sequence[str],
    workdir: Path,
    python_executable: str | None = None,
    home: Path | str | None = None,
) -> list[str]:
    """Return a host Python argv that does not copy local evidence or caches."""

    if not argv:
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay worker requires a command"
        )
    resolved_workdir = _regular_directory(Path(workdir), label="host retained-replay workdir")
    assert_workdir_does_not_contain_copied_evidence(resolved_workdir, home=home)
    python_path = Path(python_executable or sys.executable).resolve()
    command = [str(python_path), *[str(part) for part in argv]]
    reason = _forbidden_host_argv_reason(command)
    if reason is not None:
        raise IsolatedRetainedReplayWorkerError(reason)
    return command


def _bind_host_tree_path(
    raw: str,
    *,
    required: bool,
    root: Path,
    label: str,
) -> str | None:
    """Keep a path only when it already lives under the host tree.

    Explicit worker selectors fail closed on a copied tree.  Inherited
    ambient selectors from another HOME are dropped so the child falls back
    to the HOME-local ``~/.ipfs_datasets`` default instead of following a
    foreign copy.
    """

    value = str(raw or "").strip()
    if not value:
        return None
    unresolved = Path(value).expanduser()
    if unresolved.is_symlink():
        if required:
            raise IsolatedRetainedReplayWorkerError(
                f"host retained-replay {label} must not be a symlink copy"
            )
        return None
    resolved = unresolved.resolve()
    if _is_under(resolved, root):
        return str(resolved)
    if required:
        raise IsolatedRetainedReplayWorkerError(
            f"host retained-replay {label} must live under {root}; "
            "copied evidence trees are forbidden"
        )
    return None


def build_host_retained_replay_environment(
    *,
    extra_environment: Mapping[str, str] | None = None,
    source: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> dict[str, str]:
    """Pin HOME and reuse existing ``~/.ipfs_datasets`` caches without copying."""

    extra = dict(extra_environment or {})
    environment = dict(source if source is not None else os.environ)
    if home is not None:
        home_path = _resolved_home(home)
    elif extra.get("HOME"):
        home_path = _resolved_home(extra["HOME"])
    elif environment.get("HOME"):
        home_path = _resolved_home(environment["HOME"])
    else:
        home_path = _resolved_home(None)
    environment["HOME"] = str(home_path)
    ipfs_root = local_ipfs_datasets_root(home_path)
    state_laws_root = local_state_laws_root(home_path)
    for key, root, label in (
        (PAGE_CACHE_DIR_ENV, ipfs_root, "page cache"),
        (FETCH_CACHE_DIR_ENV, ipfs_root, "fetch cache"),
        (EVIDENCE_ROOT_ENV, state_laws_root, "evidence root"),
    ):
        bound = _bind_host_tree_path(
            extra.get(key, environment.get(key, "")),
            required=key in extra,
            root=root,
            label=label,
        )
        if bound is None:
            environment.pop(key, None)
        else:
            environment[key] = bound
    environment.update(
        {
            key: value
            for key, value in extra.items()
            if key
            not in {PAGE_CACHE_DIR_ENV, FETCH_CACHE_DIR_ENV, EVIDENCE_ROOT_ENV, "HOME"}
        }
    )
    evidence = environment.get(EVIDENCE_ROOT_ENV)
    if evidence:
        authorize_pennsylvania_canary_not_republished(
            evidence_root=evidence,
            jurisdiction=str(extra.get("STATE_LAWS_JURISDICTION") or "").strip(),
            publish_to_hf=str(
                extra.get("STATE_LAWS_PUBLISH_TO_HF") or ""
            ).strip().lower()
            in {"1", "true", "yes", "on"},
        )
    return environment


def authorize_host_retained_replay(
    *,
    argv: Sequence[str],
    workdir: Path,
    extra_environment: Mapping[str, str] | None = None,
    home: Path | str | None = None,
    python_executable: str | None = None,
    seed_report: Any | None = None,
    evidence_root: Path | str | None = None,
    jurisdiction: str | None = None,
    publish_to_hf: bool = False,
) -> tuple[list[str], dict[str, str]]:
    """Return authorized host argv and environment for remaining-state replay."""

    extra = dict(extra_environment or {})
    effective_home = home or extra.get("HOME")
    command = build_host_retained_replay_command(
        argv=argv,
        workdir=workdir,
        python_executable=python_executable,
        home=effective_home,
    )
    environment = build_host_retained_replay_environment(
        extra_environment=extra_environment,
        home=effective_home,
    )
    bound_home = environment["HOME"]
    if seed_report is not None:
        authorize_hardlink_only_seed(seed_report, home=bound_home)
    resolved_evidence = evidence_root or environment.get(EVIDENCE_ROOT_ENV)
    if resolved_evidence:
        authorize_host_evidence_root(resolved_evidence, home=bound_home)
    authorize_pennsylvania_canary_not_republished(
        argv=command,
        evidence_root=resolved_evidence,
        jurisdiction=jurisdiction,
        publish_to_hf=publish_to_hf,
    )
    return command, environment


def run_host_retained_replay_worker(
    argv: Sequence[str],
    *,
    workdir: Path,
    extra_environment: Mapping[str, str] | None = None,
    home: Path | str | None = None,
    python_executable: str | None = None,
    seed_report: Any | None = None,
    evidence_root: Path | str | None = None,
    jurisdiction: str | None = None,
    publish_to_hf: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` on the host, inheriting HOME and existing cache directories."""

    command, environment = authorize_host_retained_replay(
        argv=argv,
        workdir=workdir,
        extra_environment=extra_environment,
        home=home,
        python_executable=python_executable,
        seed_report=seed_report,
        evidence_root=evidence_root,
        jurisdiction=jurisdiction,
        publish_to_hf=publish_to_hf,
    )
    completed = subprocess.run(
        command,
        cwd=str(_regular_directory(Path(workdir), label="host retained-replay workdir")),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise IsolatedRetainedReplayWorkerError(
            "host retained-replay worker exited "
            f"{completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}"
        )
    return completed


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
    home: Path | str | None = None,
    python_executable: str | None = None,
    seed_report: Any | None = None,
    evidence_root: Path | str | None = None,
    jurisdiction: str | None = None,
    publish_to_hf: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Launch ``argv`` on the host so local evidence and caches are reused."""

    return run_host_retained_replay_worker(
        argv,
        workdir=workdir,
        extra_environment=extra_environment,
        home=home,
        python_executable=python_executable,
        seed_report=seed_report,
        evidence_root=evidence_root,
        jurisdiction=jurisdiction,
        publish_to_hf=publish_to_hf,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a retained-replay command on the host using existing caches.",
    )
    parser.add_argument(
        "--workdir",
        default=os.getcwd(),
        help="Repository workdir for the host worker",
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


__all__ = [
    "EVIDENCE_ROOT_ENV",
    "FETCH_CACHE_DIR_ENV",
    "IsolatedRetainedReplayWorkerError",
    "PAGE_CACHE_DIR_ENV",
    "PENNSYLVANIA_CANARY_GENERATION",
    "PENNSYLVANIA_CANARY_JURISDICTION",
    "PENNSYLVANIA_FENCED_GENERATIONS",
    "assert_kernel_network_namespace_is_closed",
    "assert_workdir_does_not_contain_copied_evidence",
    "authorize_hardlink_only_seed",
    "authorize_host_cache_path",
    "authorize_host_evidence_root",
    "authorize_host_retained_replay",
    "authorize_pennsylvania_canary_not_republished",
    "build_host_retained_replay_command",
    "build_host_retained_replay_environment",
    "build_isolated_retained_replay_docker_command",
    "docker_is_rootless",
    "local_ipfs_datasets_root",
    "local_legal_fetch_cache_root",
    "local_legal_page_cache_root",
    "local_state_laws_root",
    "pennsylvania_generation_from_path",
    "run_host_retained_replay_worker",
    "run_isolated_retained_replay_worker",
]
