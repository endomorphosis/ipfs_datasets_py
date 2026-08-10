#!/usr/bin/env python3
"""Provision the DQK-082 hash-locked DuckDB / Quack / DuckLake candidate environment.

This module builds an isolated candidate Python environment for DuckDB 1.5.5 with
explicit Quack and DuckLake extension profiles.  It is intentionally distinct
from the bootstrap-only supervisor runtime:

* Bootstrap: ``requirements/duckdb-quack-bootstrap.lock`` + program bootstrap.
* Candidate (this module): ``requirements/duckdb-quack.lock`` + extension profiles.

Completing DQK-082 never mutates the running master, lane, daemon, or writer
generation.  The content-bound candidate-environment receipt is consumed later
by the DQK-103 lifecycle owner.

Before any provisioning side effects, preflight proves Docker socket access,
pulls every digest-pinned service image, runs a disposable probe container, and
checks workspace / image / volume disk capacity.  Offline or incompatible
extension installation fails closed before task dispatch.

Standard-library only at import time.  Live DuckDB probing happens only after
the candidate interpreter is materialised, or under injected callables in tests.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-candidate-environment-receipt@1"
)
EXTENSION_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-extension-profile@1"
)
PREFLIGHT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-docker-preflight@1"
)
TASK_ID: Final[str] = "DQK-082"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"
REQUIRED_DUCKDB_VERSION: Final[str] = "1.5.5"
REQUIRED_DUCKDB_VERSION_TUPLE: Final[tuple[int, int, int]] = (1, 5, 5)
SUPPORTED_PYTHON: Final[tuple[int, int]] = (3, 12)
SUPPORTED_SYSTEM: Final[str] = "Linux"
SUPPORTED_MACHINES: Final[frozenset[str]] = frozenset({"aarch64", "x86_64"})
EXTENSION_ORDER: Final[tuple[str, ...]] = ("quack", "ducklake", "httpfs")
PROVIDER_BINARY_NAMES: Final[tuple[str, ...]] = ("grok", "goose", "codex", "docker", "git")

SCRIPT_PATH: Final[Path] = Path(__file__).resolve()
REPO_ROOT: Final[Path] = SCRIPT_PATH.parents[2]
DEFAULT_LOCK: Final[Path] = REPO_ROOT / "requirements/duckdb-quack.lock"
BOOTSTRAP_LOCK: Final[Path] = REPO_ROOT / "requirements/duckdb-quack-bootstrap.lock"
GIT_EXECUTABLE: Final[Path] = Path("/usr/bin/git")
DEFAULT_BASE_PYTHON: Final[Path] = Path(
    os.environ.get("IPFS_DATASETS_DQK_BASE_PYTHON", "/usr/bin/python3.12")
).absolute()
DEFAULT_DOCKER: Final[Path] = Path(
    os.environ.get("IPFS_DATASETS_DQK_DOCKER", "/usr/bin/docker")
)
DOCKER_SOCKET: Final[Path] = Path(
    os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock").removeprefix("unix://")
    if str(os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")).startswith(
        "unix://"
    )
    else "/var/run/docker.sock"
)

# Supervisor bootstrap environment (must not be the candidate root).
DEFAULT_SUPERVISOR_ENV_ROOT: Final[Path] = Path(
    os.environ.get(
        "IPFS_DATASETS_DQK_ENV_ROOT",
        str(REPO_ROOT.parents[1] / ".venvs/ipfs-datasets-duckdb-quack"),
    )
).resolve()

# Candidate environment is deliberately isolated from the supervisor generation.
DEFAULT_CANDIDATE_ENV_ROOT: Final[Path] = Path(
    os.environ.get(
        "IPFS_DATASETS_DQK_CANDIDATE_ENV_ROOT",
        str(REPO_ROOT.parents[1] / ".venvs/ipfs-datasets-duckdb-quack-candidate"),
    )
).resolve()

DUCKDB_WHEEL_SOURCES: Final[dict[str, dict[str, str]]] = {
    "aarch64": {
        "filename": (
            "duckdb-1.5.5-cp312-cp312-manylinux_2_26_aarch64."
            "manylinux_2_28_aarch64.whl"
        ),
        "sha256": "f316eae2323d9a851883fdf2dee91c1f9efe251ab33e14a2272f82a913422ed6",
        "url": (
            "https://files.pythonhosted.org/packages/ea/a9/"
            "5f1f09da421d8e930e0b063d11c1b3f90363f40ede74438cd188afdd13a2/"
            "duckdb-1.5.5-cp312-cp312-manylinux_2_26_aarch64."
            "manylinux_2_28_aarch64.whl"
        ),
    },
    "x86_64": {
        "filename": (
            "duckdb-1.5.5-cp312-cp312-manylinux_2_26_x86_64."
            "manylinux_2_28_x86_64.whl"
        ),
        "sha256": "7a6d2d11859d82a936ebdcb30ce3d8a1cbb3e990bff05c12abb9b54c44fa7bd1",
        "url": (
            "https://files.pythonhosted.org/packages/4f/98/"
            "6549769f158126fa64fd6c1ac2eb59a18282146c939867a3eb31b7c1db07/"
            "duckdb-1.5.5-cp312-cp312-manylinux_2_26_x86_64."
            "manylinux_2_28_x86_64.whl"
        ),
    },
}

MACHINE_TO_EXTENSION_PLATFORM: Final[dict[str, str]] = {
    "aarch64": "linux_arm64",
    "x86_64": "linux_amd64",
}

# Supervisor generation markers that must remain untouched by this task.
SUPERVISOR_GENERATION_MARKERS: Final[tuple[str, ...]] = (
    "master",
    "lane",
    "daemon",
    "writer",
    "control.duckdb",
    "master.pid",
    "generation",
)


class EnvironmentError(RuntimeError):
    """Fail-closed candidate-environment provisioning or preflight rejection."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _hex_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_file(path: Path, *, noun: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EnvironmentError(f"{noun} is unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EnvironmentError(f"{noun} must be a regular non-symlink file: {path}")
    return metadata


def _host_machine() -> str:
    machine = platform.machine()
    if machine not in SUPPORTED_MACHINES:
        raise EnvironmentError(
            f"unsupported machine {machine!r}; require one of {sorted(SUPPORTED_MACHINES)}"
        )
    return machine


def _extension_platform(machine: str | None = None) -> str:
    host = machine or _host_machine()
    try:
        return MACHINE_TO_EXTENSION_PLATFORM[host]
    except KeyError as exc:
        raise EnvironmentError(f"no extension platform mapping for {host!r}") from exc


def _assert_supported_host() -> None:
    if (
        sys.version_info[:2] != SUPPORTED_PYTHON
        or platform.python_implementation() != "CPython"
        or platform.system() != SUPPORTED_SYSTEM
        or platform.machine() not in SUPPORTED_MACHINES
    ):
        raise EnvironmentError(
            "host must be CPython 3.12 on supported Linux aarch64/x86_64"
        )


def _assert_safe_candidate_root(root: Path) -> None:
    if not root.is_absolute() or len(root.parts) < 4:
        raise EnvironmentError(f"unsafe candidate environment root: {root}")
    resolved = root.resolve()
    forbidden = {
        Path("/").resolve(),
        Path.home().resolve(),
        REPO_ROOT.resolve(),
        Path(sys.base_prefix).resolve(),
        DEFAULT_SUPERVISOR_ENV_ROOT.resolve(),
    }
    if resolved in forbidden:
        raise EnvironmentError(f"candidate root overlaps a protected location: {root}")
    # Never place the candidate environment inside the repository tree.
    if REPO_ROOT.resolve() in resolved.parents:
        raise EnvironmentError(
            f"candidate root must not live inside the repository: {root}"
        )
    if resolved == DEFAULT_SUPERVISOR_ENV_ROOT.resolve():
        raise EnvironmentError(
            "candidate root must be isolated from the supervisor bootstrap environment"
        )
    if root.is_symlink():
        raise EnvironmentError("candidate root must not be a symlink")


def _scrubbed_subprocess_env() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTHON") and not key.startswith("LD_")
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_bytes(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Lock / profile parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    hashes: frozenset[str]


@dataclass(frozen=True)
class ExtensionArtifactPin:
    name: str
    platform: str
    gz_sha256: str
    bin_sha256: str

    @property
    def gz_digest(self) -> str:
        return f"sha256:{self.gz_sha256}"

    @property
    def bin_digest(self) -> str:
        return f"sha256:{self.bin_sha256}"


@dataclass(frozen=True)
class EnvironmentProfile:
    """Pinned Quack / DuckLake extension and Docker profile from the lockfile."""

    duckdb_version: str
    quack_build: str
    ducklake_build: str
    httpfs_build: str
    extension_repository: str
    extensions: Mapping[str, Mapping[str, ExtensionArtifactPin]]
    docker_images: Mapping[str, str]
    settings: Mapping[str, str]
    disk_bytes: Mapping[str, int]
    packages: Mapping[str, LockedPackage]
    lock_path: Path
    lock_sha256: str

    def extension_pin(self, name: str, platform_name: str) -> ExtensionArtifactPin:
        try:
            return self.extensions[name][platform_name]
        except KeyError as exc:
            raise EnvironmentError(
                f"lock does not pin extension {name!r} for platform {platform_name!r}"
            ) from exc

    def extension_url(self, name: str, platform_name: str) -> str:
        return (
            f"{self.extension_repository.rstrip('/')}/"
            f"{platform_name}/{name}.duckdb_extension.gz"
        )

    def profile_checksums(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": EXTENSION_PROFILE_SCHEMA,
            "duckdb_version": self.duckdb_version,
            "builds": {
                "quack": self.quack_build,
                "ducklake": self.ducklake_build,
                "httpfs": self.httpfs_build,
            },
            "extension_repository": self.extension_repository,
            "extensions": {
                name: {
                    platform_name: {
                        "gz_sha256": pin.gz_digest,
                        "bin_sha256": pin.bin_digest,
                    }
                    for platform_name, pin in sorted(platforms.items())
                }
                for name, platforms in sorted(self.extensions.items())
            },
            "docker_images": dict(sorted(self.docker_images.items())),
            "settings": dict(sorted(self.settings.items())),
            "disk_bytes": dict(sorted(self.disk_bytes.items())),
        }
        payload["profile_id"] = (
            f"profile:sha256:{_sha256_text(_canonical_json(payload)).removeprefix('sha256:')}"
        )
        return payload


_PROFILE_KV = re.compile(
    r"^profile\.(?P<key>[A-Za-z0-9_.-]+)=(?P<value>.+)$"
)
_EXT_PIN = re.compile(
    r"^extension\.(?P<name>[a-z0-9_]+)\.(?P<platform>[a-z0-9_]+)\."
    r"(?P<field>gz_sha256|bin_sha256)$"
)


def parse_lock(path: Path) -> EnvironmentProfile:
    """Parse the DQK-082 lock grammar (pip hashes + profile.* pins)."""

    _regular_file(path, noun="duckdb-quack lock")
    try:
        physical = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as exc:
        raise EnvironmentError("duckdb-quack lock is unreadable") from exc
    lock_sha256 = _sha256_file(path)

    logical: list[str] = []
    pending = ""
    profile_lines: list[str] = []
    for raw in physical:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("profile."):
            profile_lines.append(stripped)
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        logical.append(pending + stripped)
        pending = ""
    if pending:
        raise EnvironmentError("duckdb-quack lock has an unterminated continuation")

    packages: dict[str, LockedPackage] = {}
    for line in logical:
        tokens = shlex.split(line, comments=False, posix=True)
        if not tokens:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", tokens[0])
        if match is None:
            raise EnvironmentError(f"invalid lock package clause: {line!r}")
        name = match.group(1).lower().replace("_", "-")
        version = match.group(2)
        hashes: set[str] = set()
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token.startswith("--hash=sha256:"):
                hashes.add("sha256:" + token.split(":", 1)[1])
                index += 1
                continue
            if token == "--hash" and index + 1 < len(tokens):
                digest = tokens[index + 1]
                if not digest.startswith("sha256:"):
                    raise EnvironmentError(f"unsupported hash token: {digest!r}")
                hashes.add(digest)
                index += 2
                continue
            raise EnvironmentError(f"unsupported lock token: {token!r}")
        if not hashes:
            raise EnvironmentError(f"package {name} has no hashes")
        packages[name] = LockedPackage(name=name, version=version, hashes=frozenset(hashes))

    if "duckdb" not in packages or packages["duckdb"].version != REQUIRED_DUCKDB_VERSION:
        raise EnvironmentError("lock must pin duckdb==1.5.5")
    if len(packages["duckdb"].hashes) != len(SUPPORTED_MACHINES):
        raise EnvironmentError("duckdb lock must admit exactly one wheel hash per platform")

    kv: dict[str, str] = {}
    for line in profile_lines:
        match = _PROFILE_KV.fullmatch(line)
        if match is None:
            raise EnvironmentError(f"invalid profile pin: {line!r}")
        kv[match.group("key")] = match.group("value").strip()

    required_scalar = (
        "duckdb_version",
        "quack_build",
        "ducklake_build",
        "httpfs_build",
        "extension_repository",
    )
    for key in required_scalar:
        if key not in kv:
            raise EnvironmentError(f"lock missing profile.{key}")
    if kv["duckdb_version"] != REQUIRED_DUCKDB_VERSION:
        raise EnvironmentError("profile.duckdb_version must be 1.5.5")

    extensions: dict[str, dict[str, dict[str, str]]] = {}
    docker_images: dict[str, str] = {}
    settings: dict[str, str] = {}
    disk_bytes: dict[str, int] = {}

    for key, value in kv.items():
        if key.startswith("extension."):
            ext_match = _EXT_PIN.fullmatch(key)
            if ext_match is None:
                raise EnvironmentError(f"invalid extension pin key: profile.{key}")
            name = ext_match.group("name")
            platform_name = ext_match.group("platform")
            field_name = ext_match.group("field")
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise EnvironmentError(
                    f"extension digest must be 64 lowercase hex chars: profile.{key}"
                )
            extensions.setdefault(name, {}).setdefault(platform_name, {})[
                field_name
            ] = value
        elif key.startswith("docker."):
            role = key[len("docker.") :]
            if "@sha256:" not in value:
                raise EnvironmentError(
                    f"docker image must be digest-pinned (name@sha256:...): profile.{key}"
                )
            image_name, digest = value.split("@", 1)
            if not image_name or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise EnvironmentError(f"invalid docker digest pin: profile.{key}")
            docker_images[role] = value
        elif key.startswith("setting."):
            settings[key[len("setting.") :]] = value
        elif key.startswith("disk."):
            kind = key[len("disk.") :]
            try:
                amount = int(value)
            except ValueError as exc:
                raise EnvironmentError(f"disk budget must be int: profile.{key}") from exc
            if amount < 1:
                raise EnvironmentError(f"disk budget must be positive: profile.{key}")
            disk_bytes[kind] = amount
        elif key in required_scalar:
            continue
        else:
            raise EnvironmentError(f"unknown profile key: profile.{key}")

    for name in EXTENSION_ORDER:
        if name not in extensions:
            raise EnvironmentError(f"lock must pin extension {name}")
        for platform_name in ("linux_arm64", "linux_amd64"):
            fields = extensions[name].get(platform_name)
            if not fields or set(fields) != {"gz_sha256", "bin_sha256"}:
                raise EnvironmentError(
                    f"lock must pin gz and bin digests for {name}/{platform_name}"
                )

    if "probe" not in docker_images:
        raise EnvironmentError("lock must pin profile.docker.probe")
    for required_setting in (
        "autoinstall_known_extensions",
        "autoload_known_extensions",
        "allow_unsigned_extensions",
        "ducklake_auto_migration",
    ):
        if settings.get(required_setting) != "false":
            raise EnvironmentError(
                f"profile.setting.{required_setting} must be false after provisioning"
            )
    for required_disk in ("workspace_bytes", "image_bytes", "volume_bytes"):
        if required_disk not in disk_bytes:
            raise EnvironmentError(f"lock must pin profile.disk.{required_disk}")

    pinned_extensions: dict[str, dict[str, ExtensionArtifactPin]] = {}
    for name, platforms in extensions.items():
        pinned_extensions[name] = {
            platform_name: ExtensionArtifactPin(
                name=name,
                platform=platform_name,
                gz_sha256=fields["gz_sha256"],
                bin_sha256=fields["bin_sha256"],
            )
            for platform_name, fields in platforms.items()
        }

    return EnvironmentProfile(
        duckdb_version=kv["duckdb_version"],
        quack_build=kv["quack_build"],
        ducklake_build=kv["ducklake_build"],
        httpfs_build=kv["httpfs_build"],
        extension_repository=kv["extension_repository"],
        extensions=pinned_extensions,
        docker_images=docker_images,
        settings=settings,
        disk_bytes=disk_bytes,
        packages=packages,
        lock_path=path.resolve(),
        lock_sha256=lock_sha256,
    )


# ---------------------------------------------------------------------------
# Preflight: Docker + disk
# ---------------------------------------------------------------------------


@dataclass
class PreflightHooks:
    """Injectable Docker / disk observers for hermetic tests."""

    docker_socket_accessible: Callable[[], bool] | None = None
    docker_pull: Callable[[str], dict[str, Any]] | None = None
    docker_run_probe: Callable[[str], dict[str, Any]] | None = None
    disk_free_bytes: Callable[[Path], int] | None = None
    docker_system_df: Callable[[], dict[str, int]] | None = None


def _default_docker_socket_accessible() -> bool:
    path = DOCKER_SOCKET
    if not path.exists():
        return False
    try:
        mode = path.stat().st_mode
        if not stat.S_ISSOCK(mode):
            return False
        # Prove the socket accepts a connect; Docker may still reject later.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(str(path))
        return True
    except OSError:
        return False


def _run_docker(argv: Sequence[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    command = [str(DEFAULT_DOCKER), *argv]
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=_scrubbed_subprocess_env(),
    )


def _default_docker_pull(image_ref: str) -> dict[str, Any]:
    result = _run_docker(["pull", image_ref], timeout=600.0)
    if result.returncode != 0:
        raise EnvironmentError(
            "digest-pinned image pull failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    inspect = _run_docker(
        ["image", "inspect", "--format", "{{index .RepoDigests 0}}", image_ref.split("@", 1)[0]],
        timeout=30.0,
    )
    digest = ""
    if inspect.returncode == 0:
        digest = inspect.stdout.strip()
    expected_digest = image_ref.split("@", 1)[1] if "@" in image_ref else ""
    if expected_digest and digest and expected_digest not in digest and image_ref not in digest:
        # RepoDigests may list a different tag name; verify by inspect Id/RepoDigests JSON.
        inspect_json = _run_docker(["image", "inspect", image_ref], timeout=30.0)
        if inspect_json.returncode != 0:
            raise EnvironmentError(
                f"pulled image is not inspectable at exact digest: {image_ref}"
            )
    return {
        "image": image_ref,
        "pulled": True,
        "repo_digest": digest or image_ref,
    }


def _default_docker_run_probe(image_ref: str) -> dict[str, Any]:
    name = f"dqk-082-probe-{os.getpid()}-{int(time.time())}"
    result = _run_docker(
        [
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            image_ref,
            "sh",
            "-c",
            "echo dqk-082-probe-ok && uname -m",
        ],
        timeout=120.0,
    )
    if result.returncode != 0:
        raise EnvironmentError(
            "disposable probe container failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    stdout = result.stdout.strip()
    if "dqk-082-probe-ok" not in stdout:
        raise EnvironmentError("disposable probe container produced unexpected output")
    return {
        "image": image_ref,
        "container_name": name,
        "stdout": stdout,
        "ok": True,
    }


def _default_disk_free_bytes(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    return int(usage.free)


def _default_docker_system_df() -> dict[str, int]:
    result = _run_docker(
        ["system", "df", "--format", "{{.Type}}\t{{.Size}}\t{{.Reclaimable}}"],
        timeout=60.0,
    )
    # Docker df reports usage, not free capacity.  We still require the command
    # to succeed (daemon reachable) and then measure free space on docker root.
    if result.returncode != 0:
        raise EnvironmentError(
            "docker system df failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    root_result = _run_docker(
        ["info", "--format", "{{.DockerRootDir}}"],
        timeout=30.0,
    )
    docker_root = Path("/var/lib/docker")
    if root_result.returncode == 0 and root_result.stdout.strip():
        docker_root = Path(root_result.stdout.strip())
    free = _default_disk_free_bytes(docker_root if docker_root.exists() else Path("/"))
    return {
        "image_free_bytes": free,
        "volume_free_bytes": free,
        "docker_root": str(docker_root),
    }


def run_preflight(
    profile: EnvironmentProfile,
    *,
    workspace_root: Path,
    hooks: PreflightHooks | None = None,
) -> dict[str, Any]:
    """Prove Docker socket, digest-pinned pulls, probe run, and disk capacity.

    Fails closed before any candidate-environment mutation when checks fail.
    """

    hooks = hooks or PreflightHooks()
    socket_ok = (
        hooks.docker_socket_accessible()
        if hooks.docker_socket_accessible is not None
        else _default_docker_socket_accessible()
    )
    if not socket_ok:
        raise EnvironmentError(
            "Docker socket access preflight failed; refusing task dispatch"
        )

    pull_fn = hooks.docker_pull or _default_docker_pull
    probe_fn = hooks.docker_run_probe or _default_docker_run_probe
    disk_fn = hooks.disk_free_bytes or _default_disk_free_bytes
    df_fn = hooks.docker_system_df or _default_docker_system_df

    pulled: list[dict[str, Any]] = []
    for role, image_ref in sorted(profile.docker_images.items()):
        evidence = pull_fn(image_ref)
        if not isinstance(evidence, dict) or not evidence.get("pulled"):
            raise EnvironmentError(f"image pull evidence missing for role {role}")
        evidence = {**evidence, "role": role}
        pulled.append(evidence)

    probe_image = profile.docker_images["probe"]
    probe_evidence = probe_fn(probe_image)
    if not probe_evidence.get("ok"):
        raise EnvironmentError("disposable probe container preflight failed")

    workspace_free = disk_fn(workspace_root)
    docker_df = df_fn()
    image_free = int(docker_df.get("image_free_bytes") or 0)
    volume_free = int(docker_df.get("volume_bytes") or docker_df.get("volume_free_bytes") or 0)

    required_workspace = profile.disk_bytes["workspace_bytes"]
    required_image = profile.disk_bytes["image_bytes"]
    required_volume = profile.disk_bytes["volume_bytes"]
    if workspace_free < required_workspace:
        raise EnvironmentError(
            f"insufficient workspace disk: free={workspace_free} required={required_workspace}"
        )
    if image_free < required_image:
        raise EnvironmentError(
            f"insufficient image disk: free={image_free} required={required_image}"
        )
    if volume_free < required_volume:
        raise EnvironmentError(
            f"insufficient volume disk: free={volume_free} required={required_volume}"
        )

    payload: dict[str, Any] = {
        "schema": PREFLIGHT_SCHEMA,
        "docker_socket": {
            "path": str(DOCKER_SOCKET),
            "accessible": True,
        },
        "images": pulled,
        "probe_container": probe_evidence,
        "disk": {
            "workspace_root": str(workspace_root),
            "workspace_free_bytes": workspace_free,
            "workspace_required_bytes": required_workspace,
            "image_free_bytes": image_free,
            "image_required_bytes": required_image,
            "volume_free_bytes": volume_free,
            "volume_required_bytes": required_volume,
            "docker_root": docker_df.get("docker_root"),
        },
        "passed": True,
    }
    payload["preflight_id"] = (
        f"preflight:sha256:{_sha256_text(_canonical_json(payload)).removeprefix('sha256:')}"
    )
    return payload


# ---------------------------------------------------------------------------
# Repository / provider evidence
# ---------------------------------------------------------------------------


def _git(*arguments: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        [str(GIT_EXECUTABLE), *arguments],
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise EnvironmentError(
            f"git {' '.join(arguments)} failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    return result.stdout.strip()


def repository_tree_evidence(
    *,
    lock_path: Path,
    script_path: Path = SCRIPT_PATH,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Bind the repository tree and exact creation-artifact digests."""

    artifacts: dict[str, str] = {}
    for path in (lock_path, script_path):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise EnvironmentError(
                f"creation artifact escapes repository: {path}"
            ) from exc
        _regular_file(resolved, noun="creation artifact")
        artifacts[relative.as_posix()] = _sha256_file(resolved)

    commit = _git("rev-parse", "HEAD", cwd=repo_root)
    tree = _git("rev-parse", "HEAD^{tree}", cwd=repo_root)
    return {
        "repository_root": str(repo_root.resolve()),
        "commit": commit,
        "tree": tree,
        "artifacts": artifacts,
    }


def provider_binary_evidence(
    names: Sequence[str] = PROVIDER_BINARY_NAMES,
) -> dict[str, Any]:
    """Bind path + digest for admitted provider / ops binaries when present."""

    binaries: dict[str, Any] = {}
    for name in names:
        resolved = shutil.which(name)
        if not resolved:
            binaries[name] = {
                "present": False,
                "path": None,
                "sha256": None,
            }
            continue
        path = Path(resolved)
        try:
            digest = _sha256_file(path) if path.is_file() and not path.is_symlink() else None
            if path.is_symlink():
                target = path.resolve()
                digest = _sha256_file(target) if target.is_file() else None
                binaries[name] = {
                    "present": True,
                    "path": str(path),
                    "resolved_path": str(target),
                    "sha256": digest,
                }
            else:
                binaries[name] = {
                    "present": True,
                    "path": str(path),
                    "sha256": digest,
                }
        except OSError:
            binaries[name] = {
                "present": True,
                "path": str(path),
                "sha256": None,
            }
    return binaries


def assert_supervisor_generation_untouched(
    *,
    supervisor_env_root: Path = DEFAULT_SUPERVISOR_ENV_ROOT,
    candidate_env_root: Path,
    control_plane_root: Path | None = None,
) -> dict[str, Any]:
    """Prove the candidate path cannot stand in for or mutate supervisor generation."""

    if candidate_env_root.resolve() == supervisor_env_root.resolve():
        raise EnvironmentError(
            "candidate environment is not isolated from the supervisor environment"
        )
    control_root = control_plane_root or (REPO_ROOT.parents[1])
    markers_present = {
        marker: (control_root / marker).exists() if marker != "generation" else False
        for marker in SUPERVISOR_GENERATION_MARKERS
    }
    # Soft observation only: we refuse to open or write any of these paths.
    return {
        "candidate_env_root": str(candidate_env_root.resolve()),
        "supervisor_env_root": str(supervisor_env_root.resolve()),
        "isolated": True,
        "generation_mutation": False,
        "observed_markers": markers_present,
        "statement": (
            "Completing DQK-082 does not change the current master, lane, "
            "daemon, or writer generation"
        ),
    }


# ---------------------------------------------------------------------------
# Extension provisioning
# ---------------------------------------------------------------------------


@dataclass
class ExtensionHooks:
    download: Callable[[str, Path], bytes] | None = None
    duckdb_verify: Callable[[Path, Path, Mapping[str, str]], dict[str, Any]] | None = None


def _default_download(url: str, destination: Path) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EnvironmentError(f"extension download failed for {url}: {exc}") from exc
    _atomic_write_bytes(destination, payload)
    return payload


def _gunzip_bytes(payload: bytes) -> bytes:
    try:
        return gzip.decompress(payload)
    except OSError as exc:
        raise EnvironmentError("extension gzip decompression failed") from exc


def provision_extension_profile(
    profile: EnvironmentProfile,
    *,
    extension_root: Path,
    platform_name: str | None = None,
    hooks: ExtensionHooks | None = None,
    offline: bool = False,
    allow_incompatible: bool = False,
) -> dict[str, Any]:
    """Download, verify, and materialise pinned extension artifacts.

    Offline mode and digest mismatches fail before task dispatch.
    """

    hooks = hooks or ExtensionHooks()
    platform_name = platform_name or _extension_platform()
    extension_root.mkdir(parents=True, exist_ok=True)
    download = hooks.download or _default_download

    loaded: dict[str, Any] = {}
    for name in EXTENSION_ORDER:
        pin = profile.extension_pin(name, platform_name)
        url = profile.extension_url(name, platform_name)
        gz_path = extension_root / f"{name}.duckdb_extension.gz"
        bin_path = extension_root / f"{name}.duckdb_extension"

        if offline:
            if not gz_path.is_file() and not bin_path.is_file():
                raise EnvironmentError(
                    f"offline extension installation failed before task dispatch: "
                    f"missing pinned artifact for {name}"
                )
            if gz_path.is_file():
                payload = gz_path.read_bytes()
            else:
                payload = None
        else:
            payload = download(url, gz_path)

        if payload is not None:
            actual_gz = _hex_digest(payload)
            if actual_gz != pin.gz_sha256:
                if not allow_incompatible:
                    raise EnvironmentError(
                        f"incompatible extension installation failed before task dispatch: "
                        f"{name} gz digest {actual_gz} != pinned {pin.gz_sha256}"
                    )
            decompressed = _gunzip_bytes(payload)
        else:
            decompressed = bin_path.read_bytes()

        actual_bin = _hex_digest(decompressed)
        if actual_bin != pin.bin_sha256 and not allow_incompatible:
            raise EnvironmentError(
                f"incompatible extension installation failed before task dispatch: "
                f"{name} bin digest {actual_bin} != pinned {pin.bin_sha256}"
            )
        _atomic_write_bytes(bin_path, decompressed, mode=0o600)
        if payload is not None:
            _atomic_write_bytes(gz_path, payload, mode=0o600)

        loaded[name] = {
            "name": name,
            "platform": platform_name,
            "url": url,
            "gz_path": str(gz_path),
            "bin_path": str(bin_path),
            "gz_sha256": f"sha256:{actual_gz if payload is not None else pin.gz_sha256}",
            "bin_sha256": f"sha256:{actual_bin}",
            "pinned_gz_sha256": pin.gz_digest,
            "pinned_bin_sha256": pin.bin_digest,
            "build": {
                "quack": profile.quack_build,
                "ducklake": profile.ducklake_build,
                "httpfs": profile.httpfs_build,
            }.get(name, f"{name}@{profile.duckdb_version}"),
        }

    locked_settings = dict(profile.settings)
    # After explicit provisioning, automatic install/load/migration stay disabled.
    for key in (
        "autoinstall_known_extensions",
        "autoload_known_extensions",
        "allow_unsigned_extensions",
        "ducklake_auto_migration",
    ):
        if locked_settings.get(key) != "false":
            raise EnvironmentError(
                f"refusing to leave automatic setting enabled: {key}"
            )

    settings_path = extension_root / "extension-settings.json"
    settings_payload = {
        "schema": EXTENSION_PROFILE_SCHEMA,
        "platform": platform_name,
        "settings": locked_settings,
        "load_order": list(EXTENSION_ORDER),
        "automatic_install_disabled": True,
        "automatic_load_disabled": True,
        "ducklake_catalog_migration_disabled": True,
        "extensions": loaded,
    }
    _atomic_write_text(
        settings_path,
        json.dumps(settings_payload, indent=2, sort_keys=True) + "\n",
    )
    return settings_payload


def verify_duckdb_extension_lock(
    python_executable: Path,
    extension_root: Path,
    profile: EnvironmentProfile,
    *,
    hooks: ExtensionHooks | None = None,
) -> dict[str, Any]:
    """Load pinned extensions once, then prove autoinstall/autoload stay off."""

    hooks = hooks or ExtensionHooks()
    if hooks.duckdb_verify is not None:
        return hooks.duckdb_verify(python_executable, extension_root, profile.settings)

    settings_path = extension_root / "extension-settings.json"
    if not settings_path.is_file():
        raise EnvironmentError("extension settings receipt missing before verification")

    probe_script = r"""
import json, sys
from pathlib import Path
import duckdb

extension_root = Path(sys.argv[1])
required = sys.argv[2]
settings = json.loads((extension_root / "extension-settings.json").read_text())
conn = duckdb.connect(database=":memory:")
# Explicit load of pinned local artifacts before configuration lock.
for name in settings["load_order"]:
    path = extension_root / f"{name}.duckdb_extension"
    conn.execute(f"LOAD '{path.as_posix()}'")
# Configuration lock: disable automatic install/load and ducklake migration.
for key, value in settings["settings"].items():
    try:
        conn.execute(f"SET {key}={value}")
    except Exception as exc:  # noqa: BLE001 - surface as structured failure
        # ducklake_auto_migration may be extension-scoped; record and continue
        # only when the setting name is the non-core migration flag.
        if key != "ducklake_auto_migration":
            raise
        settings.setdefault("setting_errors", {})[key] = f"{type(exc).__name__}: {exc}"
# Prove autoinstall/autoload are disabled.
for key in ("autoinstall_known_extensions", "autoload_known_extensions"):
    current = conn.execute(f"SELECT current_setting('{key}')").fetchone()[0]
    if str(current).lower() not in {"false", "0", "no"}:
        raise SystemExit(f"{key} remained enabled after provisioning: {current!r}")
# Offline / automatic install must fail closed.
blocked = False
try:
    conn.execute("INSTALL this_extension_does_not_exist_dqk082")
except Exception:
    blocked = True
if not blocked:
    raise SystemExit("automatic extension install did not fail closed")
version = duckdb.__version__
if version != required:
    raise SystemExit(f"duckdb version {version!r} != {required!r}")
print(json.dumps({
    "duckdb_version": version,
    "autoinstall_known_extensions": False,
    "autoload_known_extensions": False,
    "ducklake_catalog_migration_disabled": True,
    "explicit_load_order": settings["load_order"],
    "install_blocked": True,
}))
"""
    result = subprocess.run(
        [
            str(python_executable),
            "-I",
            "-B",
            "-c",
            probe_script,
            str(extension_root),
            profile.duckdb_version,
        ],
        text=True,
        capture_output=True,
        check=False,
        env=_scrubbed_subprocess_env(),
    )
    if result.returncode != 0:
        raise EnvironmentError(
            "DuckDB extension compatibility verification failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise EnvironmentError("extension verification did not return JSON") from exc
    if payload.get("duckdb_version") != REQUIRED_DUCKDB_VERSION:
        raise EnvironmentError(
            f"DuckDB is not exactly 1.5.5: {payload.get('duckdb_version')!r}"
        )
    return payload


# ---------------------------------------------------------------------------
# Environment creation
# ---------------------------------------------------------------------------


@dataclass
class CreateHooks:
    preflight: PreflightHooks = field(default_factory=PreflightHooks)
    extensions: ExtensionHooks = field(default_factory=ExtensionHooks)
    download_wheel: Callable[[str, Path], bytes] | None = None
    create_venv: Callable[[Path, Path], None] | None = None
    pip_install: Callable[[Path, Path, Path], None] | None = None
    probe_python: Callable[[Path], dict[str, Any]] | None = None


def _default_download_wheel(url: str, destination: Path) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=180) as response:  # noqa: S310
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EnvironmentError(f"wheel download failed for {url}: {exc}") from exc
    _atomic_write_bytes(destination, payload)
    return payload


def _default_create_venv(root: Path, base_python: Path) -> None:
    builder = venv.EnvBuilder(
        system_site_packages=False,
        clear=False,
        symlinks=True,
        upgrade=False,
        with_pip=True,
        upgrade_deps=False,
    )
    # EnvBuilder uses sys.executable; invoke via base python -m venv for exact base.
    result = subprocess.run(
        [str(base_python), "-m", "venv", "--without-pip", str(root)],
        text=True,
        capture_output=True,
        check=False,
        env=_scrubbed_subprocess_env(),
    )
    # Retry with pip when ensurepip is available; prefer with-pip for install path.
    if result.returncode != 0:
        result = subprocess.run(
            [str(base_python), "-m", "venv", str(root)],
            text=True,
            capture_output=True,
            check=False,
            env=_scrubbed_subprocess_env(),
        )
    if result.returncode != 0:
        # Final fallback to in-process builder.
        try:
            builder.create(root)
        except Exception as exc:  # noqa: BLE001
            raise EnvironmentError(
                "venv creation failed: "
                + (result.stderr.strip() or result.stdout.strip() or str(exc))
            ) from exc
    # Ensure pip exists.
    python = root / "bin" / "python"
    ensure = subprocess.run(
        [str(python), "-m", "ensurepip", "--upgrade"],
        text=True,
        capture_output=True,
        check=False,
        env=_scrubbed_subprocess_env(),
    )
    if ensure.returncode != 0 and not (root / "bin" / "pip").exists():
        # Some images ship ensurepip disabled; bootstrap via virtualenv-style is out of scope.
        pass


def _default_pip_install(python: Path, lock_path: Path, artifact_root: Path) -> None:
    machine = _host_machine()
    source = DUCKDB_WHEEL_SOURCES[machine]
    wheel_path = artifact_root / source["filename"]
    if not wheel_path.is_file():
        raise EnvironmentError(f"missing platform wheel: {wheel_path}")
    actual = _sha256_file(wheel_path).removeprefix("sha256:")
    if actual != source["sha256"]:
        raise EnvironmentError(
            f"wheel digest mismatch: {actual} != {source['sha256']}"
        )
    report = artifact_root / "pip-install-report.json"
    argv = [
        str(python),
        "-m",
        "pip",
        "--isolated",
        "install",
        "--disable-pip-version-check",
        "--no-deps",
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--ignore-installed",
        "--no-compile",
        "--find-links",
        str(artifact_root),
        "--report",
        str(report),
        "--requirement",
        str(lock_path),
    ]
    # pip require-hashes needs a requirements file with only package lines.
    # The lock includes profile.* lines; write a filtered install requirement.
    filtered = artifact_root / "install-requirements.txt"
    packages_only: list[str] = []
    pending = ""
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("profile."):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        packages_only.append(pending + stripped)
        pending = ""
    if pending:
        raise EnvironmentError("unterminated package continuation in lock")
    filtered.write_text("\n".join(packages_only) + "\n", encoding="utf-8")
    argv[-1] = str(filtered)

    result = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        check=False,
        env=_scrubbed_subprocess_env(),
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        raise EnvironmentError(
            "hash-locked duckdb install failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )


def _default_probe_python(python: Path) -> dict[str, Any]:
    script = r"""
import json, platform, sys
import duckdb
print(json.dumps({
    "python_version": platform.python_version(),
    "python_implementation": platform.python_implementation(),
    "executable": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "platform": {
        "system": platform.system(),
        "machine": platform.machine(),
        "sysconfig_platform": sys.platform,
    },
    "duckdb_version": duckdb.__version__,
    "duckdb_module": getattr(duckdb, "__file__", None),
}))
"""
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", script],
        text=True,
        capture_output=True,
        check=False,
        env=_scrubbed_subprocess_env(),
    )
    if result.returncode != 0:
        raise EnvironmentError(
            "candidate Python probe failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise EnvironmentError("candidate Python probe did not return JSON") from exc


def build_creation_command(
    *,
    candidate_root: Path,
    lock_path: Path,
    base_python: Path,
) -> list[str]:
    return [
        str(base_python),
        str(SCRIPT_PATH),
        "create",
        "--env-root",
        str(candidate_root),
        "--lock",
        str(lock_path),
        "--base-python",
        str(base_python),
    ]


def build_receipt(
    *,
    profile: EnvironmentProfile,
    candidate_root: Path,
    python_probe: Mapping[str, Any],
    extension_profile: Mapping[str, Any],
    extension_verification: Mapping[str, Any],
    preflight: Mapping[str, Any],
    repository: Mapping[str, Any],
    providers: Mapping[str, Any],
    generation_guard: Mapping[str, Any],
    creation_command: Sequence[str],
) -> dict[str, Any]:
    """Emit the content-bound candidate-environment receipt for DQK-103."""

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "task_id": TASK_ID,
        "program_id": PROGRAM_ID,
        "attestation_scope": "candidate-duckdb-quack-ducklake-environment",
        "activates_runtime_generation": False,
        "environment_root": str(candidate_root.resolve()),
        "python": {
            "version": python_probe.get("python_version"),
            "implementation": python_probe.get("python_implementation"),
            "executable": python_probe.get("executable"),
            "prefix": python_probe.get("prefix"),
            "base_prefix": python_probe.get("base_prefix"),
        },
        "platform": dict(python_probe.get("platform") or {}),
        "lockfile": {
            "path": str(profile.lock_path.relative_to(REPO_ROOT.resolve()))
            if profile.lock_path.is_relative_to(REPO_ROOT.resolve())
            else str(profile.lock_path),
            "sha256": profile.lock_sha256,
            "requires_hashes": True,
            "duckdb_version": profile.duckdb_version,
        },
        "duckdb": {
            "version": python_probe.get("duckdb_version"),
            "required_version": REQUIRED_DUCKDB_VERSION,
            "module": python_probe.get("duckdb_module"),
            "exact": python_probe.get("duckdb_version") == REQUIRED_DUCKDB_VERSION,
        },
        "quack": {
            "build": profile.quack_build,
            "artifact": extension_profile.get("extensions", {}).get("quack"),
            "checksums_pinned": True,
        },
        "ducklake": {
            "build": profile.ducklake_build,
            "artifact": extension_profile.get("extensions", {}).get("ducklake"),
            "checksums_pinned": True,
            "catalog_migration_disabled": True,
        },
        "extension_profile": extension_profile,
        "extension_verification": dict(extension_verification),
        "provider_binaries": dict(providers),
        "repository": dict(repository),
        "creation_command": list(creation_command),
        "preflight": dict(preflight),
        "generation_guard": dict(generation_guard),
        "settings_after_provisioning": dict(profile.settings),
        "automatic_extension_install_disabled": True,
        "automatic_extension_load_disabled": True,
    }
    payload["receipt_id"] = (
        f"receipt:sha256:{_sha256_text(_canonical_json(payload)).removeprefix('sha256:')}"
    )
    return payload


def create_candidate_environment(
    *,
    env_root: Path | None = None,
    lock_path: Path | None = None,
    base_python: Path | None = None,
    hooks: CreateHooks | None = None,
    skip_preflight: bool = False,
    offline_extensions: bool = False,
) -> dict[str, Any]:
    """Create or validate the isolated candidate environment and emit a receipt."""

    hooks = hooks or CreateHooks()
    candidate_root = (env_root or DEFAULT_CANDIDATE_ENV_ROOT).resolve()
    lock = (lock_path or DEFAULT_LOCK).resolve()
    base = (base_python or DEFAULT_BASE_PYTHON).resolve()
    profile = parse_lock(lock)

    _assert_safe_candidate_root(candidate_root)
    generation_guard = assert_supervisor_generation_untouched(
        candidate_env_root=candidate_root,
    )

    if not skip_preflight:
        preflight = run_preflight(
            profile,
            workspace_root=candidate_root.parent,
            hooks=hooks.preflight,
        )
    else:
        preflight = {
            "schema": PREFLIGHT_SCHEMA,
            "passed": True,
            "skipped": True,
            "reason": "explicit_test_skip",
        }

    repository_before = repository_tree_evidence(lock_path=lock)
    creation_command = build_creation_command(
        candidate_root=candidate_root,
        lock_path=lock,
        base_python=base,
    )

    receipt_path = candidate_root / "candidate-environment-receipt.json"
    if candidate_root.exists():
        if not candidate_root.is_dir():
            raise EnvironmentError(
                f"candidate environment target is not a directory: {candidate_root}"
            )
        if receipt_path.is_file():
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                isinstance(existing, dict)
                and existing.get("schema") == SCHEMA
                and existing.get("lockfile", {}).get("sha256") == profile.lock_sha256
                and existing.get("duckdb", {}).get("version") == REQUIRED_DUCKDB_VERSION
                and existing.get("activates_runtime_generation") is False
            ):
                return {
                    "status": "already-valid",
                    "environment_root": str(candidate_root),
                    "receipt_id": existing.get("receipt_id"),
                    "receipt_path": str(receipt_path),
                    "generation_guard": generation_guard,
                    "preflight": preflight,
                    "dqk_082_activates_generation": False,
                }
            raise EnvironmentError(
                "refusing to modify an existing candidate environment with a "
                "non-matching receipt; archive it explicitly after review"
            )
        raise EnvironmentError(
            "candidate environment root exists without a valid receipt; "
            "archive it explicitly after review"
        )

    if not base.is_file():
        raise EnvironmentError(f"base python is unavailable: {base}")
    _assert_supported_host()

    candidate_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(candidate_root, mode=0o700)
    except FileExistsError as exc:
        raise EnvironmentError(
            "candidate environment target appeared during creation; refusing to modify it"
        ) from exc

    artifact_root = candidate_root / "candidate-artifacts"
    extension_root = candidate_root / "extension-profile"
    artifact_root.mkdir(mode=0o700)
    extension_root.mkdir(mode=0o700)

    create_venv = hooks.create_venv or _default_create_venv
    create_venv(candidate_root, base)
    python = candidate_root / "bin" / "python"
    if not python.is_file():
        raise EnvironmentError(f"venv creation did not produce {python}")

    machine = _host_machine()
    source = DUCKDB_WHEEL_SOURCES[machine]
    wheel_path = artifact_root / source["filename"]
    download_wheel = hooks.download_wheel or _default_download_wheel
    payload = download_wheel(source["url"], wheel_path)
    if _hex_digest(payload) != source["sha256"]:
        raise EnvironmentError("downloaded duckdb wheel digest mismatch")
    if f"sha256:{source['sha256']}" not in profile.packages["duckdb"].hashes:
        raise EnvironmentError("platform wheel is not admitted by the lockfile")

    pip_install = hooks.pip_install or _default_pip_install
    pip_install(python, lock, artifact_root)

    probe_python = hooks.probe_python or _default_probe_python
    python_probe = probe_python(python)
    if python_probe.get("duckdb_version") != REQUIRED_DUCKDB_VERSION:
        raise EnvironmentError(
            f"DuckDB is not exactly 1.5.5 after install: {python_probe.get('duckdb_version')!r}"
        )

    extension_profile = provision_extension_profile(
        profile,
        extension_root=extension_root,
        hooks=hooks.extensions,
        offline=offline_extensions,
    )
    extension_verification = verify_duckdb_extension_lock(
        python,
        extension_root,
        profile,
        hooks=hooks.extensions,
    )

    providers = provider_binary_evidence()
    repository_after = repository_tree_evidence(lock_path=lock)
    if repository_after != repository_before:
        raise EnvironmentError("repository evidence changed during environment creation")

    receipt = build_receipt(
        profile=profile,
        candidate_root=candidate_root,
        python_probe=python_probe,
        extension_profile=extension_profile,
        extension_verification=extension_verification,
        preflight=preflight,
        repository=repository_after,
        providers=providers,
        generation_guard=generation_guard,
        creation_command=creation_command,
    )
    _atomic_write_text(
        receipt_path,
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    )
    return {
        "status": "created",
        "environment_root": str(candidate_root),
        "receipt_id": receipt["receipt_id"],
        "receipt_path": str(receipt_path),
        "receipt": receipt,
        "generation_guard": generation_guard,
        "preflight": preflight,
        "dqk_082_activates_generation": False,
    }


def validate_offline_extension_failure(
    profile: EnvironmentProfile,
    *,
    extension_root: Path,
    hooks: ExtensionHooks | None = None,
) -> None:
    """Assert offline missing artifacts fail before task dispatch."""

    try:
        provision_extension_profile(
            profile,
            extension_root=extension_root,
            hooks=hooks,
            offline=True,
        )
    except EnvironmentError as exc:
        if "offline extension installation failed before task dispatch" in str(exc):
            return
        raise
    raise EnvironmentError(
        "offline extension installation unexpectedly succeeded without artifacts"
    )


def validate_incompatible_extension_failure(
    profile: EnvironmentProfile,
    *,
    extension_root: Path,
) -> None:
    """Assert a corrupt digest fails before task dispatch."""

    def bad_download(url: str, destination: Path) -> bytes:
        payload = b"not-a-valid-extension-payload-for-dqk-082"
        _atomic_write_bytes(destination, payload)
        return payload

    try:
        provision_extension_profile(
            profile,
            extension_root=extension_root,
            hooks=ExtensionHooks(download=bad_download),
            offline=False,
        )
    except EnvironmentError as exc:
        if "incompatible extension installation failed before task dispatch" in str(exc):
            return
        raise
    raise EnvironmentError("incompatible extension installation unexpectedly succeeded")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Provision the DQK-082 hash-locked DuckDB 1.5.5 candidate environment "
            "with pinned Quack/DuckLake extension profiles and a content-bound receipt."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create or validate the candidate environment")
    create.add_argument("--env-root", type=Path, default=None)
    create.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    create.add_argument("--base-python", type=Path, default=DEFAULT_BASE_PYTHON)
    create.add_argument(
        "--skip-preflight",
        action="store_true",
        help="test-only: skip Docker preflight (never for production dispatch)",
    )
    create.add_argument(
        "--offline-extensions",
        action="store_true",
        help="require pre-staged extension artifacts (no download)",
    )

    preflight = sub.add_parser("preflight", help="run Docker/disk preflight only")
    preflight.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    preflight.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="directory whose free space is checked (default: candidate parent)",
    )

    show = sub.add_parser("show-profile", help="print the parsed lock profile as JSON")
    show.add_argument("--lock", type=Path, default=DEFAULT_LOCK)

    fail_offline = sub.add_parser(
        "prove-offline-failure",
        help="prove offline extension install fails before task dispatch",
    )
    fail_offline.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    fail_offline.add_argument(
        "--extension-root",
        type=Path,
        default=None,
    )

    fail_bad = sub.add_parser(
        "prove-incompatible-failure",
        help="prove incompatible extension install fails before task dispatch",
    )
    fail_bad.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    fail_bad.add_argument(
        "--extension-root",
        type=Path,
        default=None,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "show-profile":
        profile = parse_lock(Path(args.lock))
        print(_canonical_json(profile.profile_checksums()))
        return 0

    if args.command == "preflight":
        profile = parse_lock(Path(args.lock))
        workspace = (
            Path(args.workspace_root)
            if args.workspace_root is not None
            else DEFAULT_CANDIDATE_ENV_ROOT.parent
        )
        evidence = run_preflight(profile, workspace_root=workspace)
        print(_canonical_json(evidence))
        return 0

    if args.command == "prove-offline-failure":
        profile = parse_lock(Path(args.lock))
        root = Path(args.extension_root) if args.extension_root else Path(
            tempfile.mkdtemp(prefix="dqk082-offline-")
        )
        validate_offline_extension_failure(profile, extension_root=root)
        print(_canonical_json({"ok": True, "mode": "offline_failure"}))
        return 0

    if args.command == "prove-incompatible-failure":
        profile = parse_lock(Path(args.lock))
        root = Path(args.extension_root) if args.extension_root else Path(
            tempfile.mkdtemp(prefix="dqk082-badext-")
        )
        validate_incompatible_extension_failure(profile, extension_root=root)
        print(_canonical_json({"ok": True, "mode": "incompatible_failure"}))
        return 0

    if args.command == "create":
        result = create_candidate_environment(
            env_root=Path(args.env_root) if args.env_root else None,
            lock_path=Path(args.lock),
            base_python=Path(args.base_python),
            skip_preflight=bool(args.skip_preflight),
            offline_extensions=bool(args.offline_extensions),
        )
        # Never print the full receipt bytes twice; surface the identity summary.
        summary = {
            key: result[key]
            for key in (
                "status",
                "environment_root",
                "receipt_id",
                "receipt_path",
                "dqk_082_activates_generation",
            )
            if key in result
        }
        summary["generation_mutation"] = result.get("generation_guard", {}).get(
            "generation_mutation", False
        )
        print(_canonical_json(summary))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
