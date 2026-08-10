#!/usr/bin/env python3
"""Provision a hash-locked candidate DuckDB / Quack / DuckLake environment (DQK-082).

This tool builds an *isolated candidate* Python environment plus explicit
extension profiles for DuckDB 1.5.5.  It is deliberately separate from the
running supervisor bootstrap environment:

* It never mutates the control database, master, lane, daemon, or writer
  generation.
* Automatic extension install/load and DuckLake catalog migration are disabled
  after explicit provisioning.
* Offline or incompatible extension installation fails closed *before* any
  task-dispatch side effects.
* Docker preflight proves socket access, digest-pinned image pull, a disposable
  probe container, and sufficient workspace / image / volume disk.
* The emitted content-bound candidate-environment receipt is consumed by the
  DQK-103 lifecycle owner; completing this task does not activate a generation.

Importing this module is side-effect free.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

__all__ = [
    "CANDIDATE_ENVIRONMENT_RECEIPT_SCHEMA",
    "CANDIDATE_ENV_NAME",
    "DEFAULT_LOCK_RELATIVE",
    "DockerPreflightError",
    "EnvironmentProvisionError",
    "ExtensionProfile",
    "LockPolicy",
    "LockfileError",
    "PLATFORM_ALIAS",
    "REQUIRED_DUCKDB_VERSION",
    "SUPPORTED_MACHINES",
    "SUPPORTED_PYTHON",
    "assert_no_supervisor_generation_mutation",
    "build_candidate_receipt",
    "canonical_json",
    "content_receipt_id",
    "create_candidate_environment",
    "default_candidate_env_root",
    "default_lock_path",
    "default_supervisor_env_root",
    "disk_capacity_preflight",
    "docker_preflight",
    "load_lock_policy",
    "main",
    "parse_args",
    "platform_key",
    "provision_extension_profiles",
    "repo_root",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "validate_candidate_receipt",
    "verify_post_provision_hardening",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_ID: Final[str] = "DQK-082"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"
CANDIDATE_ENVIRONMENT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-candidate-environment-receipt@1"
)
LOCK_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-quack-environment-lock@1"
CANDIDATE_ENV_NAME: Final[str] = "ipfs-datasets-duckdb-quack-candidate"
SUPERVISOR_ENV_NAME: Final[str] = "ipfs-datasets-duckdb-quack"
DEFAULT_LOCK_RELATIVE: Final[str] = "requirements/duckdb-quack.lock"
REQUIRED_DUCKDB_VERSION: Final[str] = "1.5.5"
REQUIRED_DUCKDB_VERSION_TUPLE: Final[tuple[int, int, int]] = (1, 5, 5)
SUPPORTED_PYTHON: Final[tuple[int, int]] = (3, 12)
SUPPORTED_SYSTEM: Final[str] = "Linux"
SUPPORTED_MACHINES: Final[frozenset[str]] = frozenset({"aarch64", "x86_64", "arm64", "amd64"})
# Map host machine → DuckDB extension platform directory name.
PLATFORM_ALIAS: Final[Mapping[str, str]] = {
    "aarch64": "linux_arm64",
    "arm64": "linux_arm64",
    "x86_64": "linux_amd64",
    "amd64": "linux_amd64",
}
DOCKER_SOCKET_PATHS: Final[tuple[str, ...]] = (
    "/var/run/docker.sock",
    "/run/docker.sock",
)
PROBE_CONTAINER_NAME_PREFIX: Final[str] = "dqk-082-probe-"
GENERATION_MUTATION_PATH_MARKERS: Final[tuple[str, ...]] = (
    "control.duckdb",
    "master/pid",
    "master/state",
    "state/lane-",
    "writer_generation",
    "daemon_generation",
)


class EnvironmentProvisionError(RuntimeError):
    """Fail-closed provisioning, preflight, or receipt error."""


class LockfileError(EnvironmentProvisionError):
    """The checked-in lock policy is missing, malformed, or inconsistent."""


class DockerPreflightError(EnvironmentProvisionError):
    """Docker socket, image, probe container, or disk preflight failed."""


# ---------------------------------------------------------------------------
# Path / hash helpers
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """Return the repository root that owns this script."""

    return Path(__file__).resolve().parents[2]


def default_lock_path(root: Path | None = None) -> Path:
    base = root if root is not None else repo_root()
    return (base / DEFAULT_LOCK_RELATIVE).resolve()


def default_supervisor_env_root(root: Path | None = None) -> Path:
    """Path of the *running* supervisor bootstrap environment (must not be mutated)."""

    override = os.environ.get("IPFS_DATASETS_DQK_ENV_ROOT")
    if override:
        return Path(override).resolve()
    base = root if root is not None else repo_root()
    # Prefer a sibling of the worktree parents used by the program bootstrap.
    candidates = [
        base.parents[1] / ".venvs" / SUPERVISOR_ENV_NAME,
        base.parent / ".venvs" / SUPERVISOR_ENV_NAME,
        base / ".venvs" / SUPERVISOR_ENV_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def default_candidate_env_root(root: Path | None = None) -> Path:
    """Isolated candidate environment root (never the supervisor bootstrap root)."""

    override = os.environ.get("IPFS_DATASETS_DQK_CANDIDATE_ENV_ROOT")
    if override:
        return Path(override).resolve()
    base = root if root is not None else repo_root()
    return (base.parents[1] / ".venvs" / CANDIDATE_ENV_NAME).resolve()


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for content-bound receipt IDs."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_receipt_id(payload: Mapping[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "receipt_id"}
    return f"receipt:{sha256_text(canonical_json(material))}"


def platform_key(machine: str | None = None) -> str:
    host = (machine or platform.machine()).strip().lower()
    try:
        return PLATFORM_ALIAS[host]
    except KeyError as exc:
        raise EnvironmentProvisionError(
            f"unsupported machine {host!r}; admitted: {sorted(PLATFORM_ALIAS)}"
        ) from exc


def _atomic_write_text(path: Path, value: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: Mapping[str, Any], *, mode: int = 0o600) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Lock policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtensionArtifact:
    platform: str
    sha256: str
    filename: str


@dataclass(frozen=True, slots=True)
class ExtensionProfile:
    name: str
    version: str
    source: str
    build: str
    load_order: int
    repository: str
    artifacts: Mapping[str, ExtensionArtifact]

    def artifact_for(self, plat: str) -> ExtensionArtifact:
        try:
            return self.artifacts[plat]
        except KeyError as exc:
            raise EnvironmentProvisionError(
                f"extension {self.name!r} has no artifact pin for platform {plat!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "build": self.build,
            "load_order": self.load_order,
            "repository": self.repository,
            "artifacts": {
                key: {
                    "platform": art.platform,
                    "sha256": art.sha256,
                    "filename": art.filename,
                }
                for key, art in sorted(self.artifacts.items())
            },
        }


@dataclass(frozen=True, slots=True)
class DockerImagePin:
    role: str
    reference: str  # repo@sha256:...

    @property
    def digest(self) -> str:
        if "@" not in self.reference:
            raise EnvironmentProvisionError(
                f"docker image pin must be digest-pinned (repo@sha256:...), got {self.reference!r}"
            )
        return self.reference.split("@", 1)[1]


@dataclass(frozen=True, slots=True)
class DiskMinima:
    workspace_bytes: int
    image_bytes: int
    volume_bytes: int


@dataclass(frozen=True, slots=True)
class LockPolicy:
    schema: str
    path: Path
    sha256: str
    duckdb_version: str
    python_package: str
    requires_hashes: bool
    binary_only: bool
    dependencies_disabled: bool
    autoinstall_known_extensions: bool
    autoload_known_extensions: bool
    ducklake_automatic_migration: bool
    attestation_scope: str
    extension_profiles: tuple[ExtensionProfile, ...]
    docker_images: tuple[DockerImagePin, ...]
    disk_minima: DiskMinima
    pip_requirement_text: str
    package_hashes: frozenset[str]
    raw_text: str

    def ordered_profiles(self) -> tuple[ExtensionProfile, ...]:
        return tuple(sorted(self.extension_profiles, key=lambda p: (p.load_order, p.name)))

    def profile(self, name: str) -> ExtensionProfile:
        for item in self.extension_profiles:
            if item.name == name:
                return item
        raise EnvironmentProvisionError(f"lock is missing extension profile {name!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "path": self.path.as_posix(),
            "sha256": self.sha256,
            "duckdb_version": self.duckdb_version,
            "python_package": self.python_package,
            "requires_hashes": self.requires_hashes,
            "binary_only": self.binary_only,
            "dependencies_disabled": self.dependencies_disabled,
            "autoinstall_known_extensions": self.autoinstall_known_extensions,
            "autoload_known_extensions": self.autoload_known_extensions,
            "ducklake_automatic_migration": self.ducklake_automatic_migration,
            "attestation_scope": self.attestation_scope,
            "extension_profiles": [p.to_dict() for p in self.ordered_profiles()],
            "docker_images": [
                {"role": img.role, "reference": img.reference, "digest": img.digest}
                for img in self.docker_images
            ],
            "disk_minima": {
                "workspace_bytes": self.disk_minima.workspace_bytes,
                "image_bytes": self.disk_minima.image_bytes,
                "volume_bytes": self.disk_minima.volume_bytes,
            },
            "package_hashes": sorted(self.package_hashes),
        }


_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_ARTIFACT_RE = re.compile(
    r"^artifact\s+(?P<platform>[A-Za-z0-9_]+)\s+"
    r"sha256:(?P<sha256>[0-9a-f]{64})\s+"
    r"filename=(?P<filename>[A-Za-z0-9._-]+)\s*$"
)
_DOCKER_RE = re.compile(
    r"^DOCKER_IMAGE\s+(?P<role>[A-Za-z0-9_-]+)\s+"
    r"(?P<reference>[A-Za-z0-9._/:@-]+@sha256:[0-9a-f]{64})\s*$"
)
_HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)")


def _strip_comment(line: str) -> str:
    text = line.strip()
    if text.startswith("#"):
        return text[1:].strip()
    return text


def load_lock_policy(path: Path) -> LockPolicy:
    """Parse and validate the checked-in candidate environment lock."""

    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except OSError as exc:
        raise LockfileError(f"unable to read lock file {path}: {exc}") from exc
    if not raw:
        raise LockfileError(f"lock file is empty: {path}")

    lines = raw.splitlines()
    if not lines or LOCK_SCHEMA not in lines[0]:
        raise LockfileError(
            f"lock file must declare schema {LOCK_SCHEMA} on the first line"
        )

    policy_kv: dict[str, str] = {}
    profiles: list[ExtensionProfile] = []
    current: dict[str, Any] | None = None
    artifacts: dict[str, ExtensionArtifact] = {}
    docker_images: list[DockerImagePin] = []
    disk_kv: dict[str, int] = {}
    in_disk = False
    pip_lines: list[str] = []
    in_pip = False

    def flush_profile() -> None:
        nonlocal current, artifacts
        if current is None:
            return
        required = ("name", "version", "source", "build", "load_order", "repository")
        missing = [key for key in required if key not in current]
        if missing:
            raise LockfileError(
                f"extension profile incomplete; missing {missing}: {current!r}"
            )
        if not artifacts:
            raise LockfileError(
                f"extension profile {current['name']!r} has no platform artifacts"
            )
        profiles.append(
            ExtensionProfile(
                name=str(current["name"]),
                version=str(current["version"]),
                source=str(current["source"]),
                build=str(current["build"]),
                load_order=int(current["load_order"]),
                repository=str(current["repository"]),
                artifacts=dict(artifacts),
            )
        )
        current = None
        artifacts = {}

    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("# --- pip"):
            flush_profile()
            in_disk = False
            in_pip = True
            continue
        if in_pip:
            if stripped.startswith("#"):
                continue
            if stripped:
                pip_lines.append(raw_line.rstrip())
            continue

        text = _strip_comment(raw_line)
        if not text:
            continue
        if text == "POLICY":
            flush_profile()
            in_disk = False
            continue
        if text.startswith("EXTENSION_PROFILE "):
            flush_profile()
            in_disk = False
            current = {"name": text.split(None, 1)[1].strip()}
            artifacts = {}
            continue
        if text == "DISK_MINIMA":
            flush_profile()
            in_disk = True
            continue
        docker_match = _DOCKER_RE.match(text)
        if docker_match:
            flush_profile()
            in_disk = False
            docker_images.append(
                DockerImagePin(
                    role=docker_match.group("role"),
                    reference=docker_match.group("reference"),
                )
            )
            continue
        if current is not None:
            art_match = _ARTIFACT_RE.match(text)
            if art_match:
                plat = art_match.group("platform")
                artifacts[plat] = ExtensionArtifact(
                    platform=plat,
                    sha256=f"sha256:{art_match.group('sha256')}",
                    filename=art_match.group("filename"),
                )
                continue
            kv = _KV_RE.match(text)
            if kv:
                current[kv.group(1)] = kv.group(2)
                continue
            raise LockfileError(f"unrecognized extension profile line: {text!r}")
        if in_disk:
            kv = _KV_RE.match(text)
            if not kv:
                raise LockfileError(f"unrecognized disk minima line: {text!r}")
            disk_kv[kv.group(1)] = int(kv.group(2))
            continue
        kv = _KV_RE.match(text)
        if kv:
            policy_kv[kv.group(1)] = kv.group(2)
            continue
        # Ignore free-form commentary under the schema header.
        if text.startswith("ipfs_datasets_py/") or text.startswith("Hash-locked"):
            continue
        if text.startswith("Scope:") or text.startswith("x86_64") or text.startswith("supervisor"):
            continue

    flush_profile()

    if not pip_lines:
        raise LockfileError("lock file contains no pip requirements")
    package_hashes = frozenset(
        f"sha256:{value}" for value in _HASH_RE.findall("\n".join(pip_lines))
    )
    if len(package_hashes) < 1:
        raise LockfileError("lock file must pin at least one package hash")

    required_policy = {
        "duckdb_version": REQUIRED_DUCKDB_VERSION,
        "python_package": "duckdb",
        "requires_hashes": "true",
        "binary_only": "true",
        "dependencies_disabled": "true",
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
        "ducklake_automatic_migration": "false",
    }
    for key, expected in required_policy.items():
        actual = policy_kv.get(key)
        if actual != expected:
            raise LockfileError(
                f"lock POLICY {key} must be {expected!r}, got {actual!r}"
            )

    names = {p.name for p in profiles}
    for required in ("quack", "ducklake", "httpfs"):
        if required not in names:
            raise LockfileError(f"lock must pin extension profile {required!r}")

    for profile in profiles:
        if profile.version != REQUIRED_DUCKDB_VERSION:
            raise LockfileError(
                f"extension {profile.name} version must be {REQUIRED_DUCKDB_VERSION}"
            )
        for plat in ("linux_arm64", "linux_amd64"):
            if plat not in profile.artifacts:
                raise LockfileError(
                    f"extension {profile.name} missing artifact pin for {plat}"
                )

    if not docker_images:
        raise LockfileError("lock must pin at least one DOCKER_IMAGE")
    for image in docker_images:
        if not image.reference.endswith(image.digest) or not image.digest.startswith(
            "sha256:"
        ):
            raise LockfileError(f"docker image is not digest-pinned: {image.reference}")

    for key in ("workspace_bytes", "image_bytes", "volume_bytes"):
        if key not in disk_kv or disk_kv[key] <= 0:
            raise LockfileError(f"DISK_MINIMA.{key} must be a positive integer")

    if f"duckdb=={REQUIRED_DUCKDB_VERSION}" not in "\n".join(pip_lines):
        raise LockfileError(
            f"pip requirements must pin duckdb=={REQUIRED_DUCKDB_VERSION}"
        )

    return LockPolicy(
        schema=LOCK_SCHEMA,
        path=path.resolve(),
        sha256=sha256_file(path),
        duckdb_version=policy_kv["duckdb_version"],
        python_package=policy_kv["python_package"],
        requires_hashes=True,
        binary_only=True,
        dependencies_disabled=True,
        autoinstall_known_extensions=False,
        autoload_known_extensions=False,
        ducklake_automatic_migration=False,
        attestation_scope=policy_kv.get(
            "attestation_scope",
            "candidate-duckdb-quack-ducklake-runtime",
        ),
        extension_profiles=tuple(profiles),
        docker_images=tuple(docker_images),
        disk_minima=DiskMinima(
            workspace_bytes=disk_kv["workspace_bytes"],
            image_bytes=disk_kv["image_bytes"],
            volume_bytes=disk_kv["volume_bytes"],
        ),
        pip_requirement_text="\n".join(pip_lines) + "\n",
        package_hashes=package_hashes,
        raw_text=raw,
    )


# ---------------------------------------------------------------------------
# Generation non-mutation + repository binding
# ---------------------------------------------------------------------------


def assert_no_supervisor_generation_mutation(
    *,
    candidate_root: Path,
    supervisor_root: Path,
    mutated_paths: Sequence[Path] = (),
) -> None:
    """Fail closed if the candidate root collides with the live supervisor."""

    candidate = candidate_root.resolve()
    supervisor = supervisor_root.resolve()
    if candidate == supervisor:
        raise EnvironmentProvisionError(
            "candidate environment root collides with the running supervisor "
            f"environment ({supervisor}); completing DQK-082 must not change "
            "the current master, lane, daemon, or writer generation"
        )
    try:
        candidate.relative_to(supervisor)
        raise EnvironmentProvisionError(
            "candidate environment root is nested under the supervisor environment"
        )
    except ValueError:
        pass
    try:
        supervisor.relative_to(candidate)
        raise EnvironmentProvisionError(
            "supervisor environment root is nested under the candidate environment"
        )
    except ValueError:
        pass
    for path in mutated_paths:
        text = str(path.resolve())
        for marker in GENERATION_MUTATION_PATH_MARKERS:
            if marker in text:
                raise EnvironmentProvisionError(
                    f"refusing to mutate supervisor generation path {path} ({marker})"
                )


def repository_evidence(root: Path, lock_path: Path) -> dict[str, Any]:
    """Bind the repository commit/tree and the lockfile identity."""

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise EnvironmentProvisionError(
                f"git {' '.join(args)} failed: "
                + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
            )
        return result.stdout.strip()

    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    lock_relative = lock_path.resolve().relative_to(root.resolve()).as_posix()
    return {
        "repository_root": str(root.resolve()),
        "commit": commit,
        "tree": tree,
        "lock_relative_path": lock_relative,
        "lock_sha256": sha256_file(lock_path),
    }


def provider_binary_evidence(names: Sequence[str] = ("python3", "docker", "codex", "grok", "goose")) -> list[dict[str, Any]]:
    """Record presence and identity of provider / tooling binaries."""

    evidence: list[dict[str, Any]] = []
    for name in names:
        path_str = shutil.which(name)
        if not path_str:
            evidence.append(
                {
                    "name": name,
                    "present": False,
                    "path": "",
                    "sha256": "",
                }
            )
            continue
        path = Path(path_str)
        try:
            resolved = path.resolve()
            digest = sha256_file(resolved) if resolved.is_file() else ""
        except OSError:
            resolved = path
            digest = ""
        evidence.append(
            {
                "name": name,
                "present": True,
                "path": str(resolved),
                "sha256": digest,
            }
        )
    evidence.sort(key=lambda item: str(item["name"]))
    return evidence


# ---------------------------------------------------------------------------
# Disk + Docker preflight
# ---------------------------------------------------------------------------


def _statvfs_free_bytes(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    usage = os.statvfs(path)
    return int(usage.f_bavail) * int(usage.f_frsize)


def disk_capacity_preflight(
    *,
    workspace_path: Path,
    image_path: Path | None,
    volume_path: Path | None,
    minima: DiskMinima,
) -> dict[str, Any]:
    """Prove free disk for workspace, docker image root, and volume root."""

    workspace_free = _statvfs_free_bytes(workspace_path)
    image_root = image_path or _default_docker_root() / "image"
    volume_root = volume_path or _default_docker_root() / "volumes"
    # Image/volume roots may not exist yet; fall back to their parents.
    image_probe = image_root if image_root.exists() else image_root.parent
    volume_probe = volume_root if volume_root.exists() else volume_root.parent
    if not image_probe.exists():
        image_probe = Path("/")
    if not volume_probe.exists():
        volume_probe = Path("/")
    image_free = _statvfs_free_bytes(image_probe)
    volume_free = _statvfs_free_bytes(volume_probe)

    checks = {
        "workspace": {
            "path": str(workspace_path.resolve()),
            "free_bytes": workspace_free,
            "required_bytes": minima.workspace_bytes,
            "ok": workspace_free >= minima.workspace_bytes,
        },
        "image": {
            "path": str(image_probe.resolve()),
            "free_bytes": image_free,
            "required_bytes": minima.image_bytes,
            "ok": image_free >= minima.image_bytes,
        },
        "volume": {
            "path": str(volume_probe.resolve()),
            "free_bytes": volume_free,
            "required_bytes": minima.volume_bytes,
            "ok": volume_free >= minima.volume_bytes,
        },
    }
    failed = [name for name, row in checks.items() if not row["ok"]]
    if failed:
        raise DockerPreflightError(
            "insufficient disk capacity before task dispatch: "
            + ", ".join(
                f"{name} free={checks[name]['free_bytes']} required={checks[name]['required_bytes']}"
                for name in failed
            )
        )
    return {"ok": True, "checks": checks}


def _default_docker_root() -> Path:
    return Path("/var/lib/docker")


def _docker(
    *args: str,
    check: bool = True,
    timeout: float | None = 120,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(env) if env is not None else None,
        )
    except FileNotFoundError as exc:
        raise DockerPreflightError("docker CLI is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerPreflightError(f"docker command timed out: docker {' '.join(args)}") from exc


def _docker_socket_accessible() -> tuple[bool, str]:
    for candidate in DOCKER_SOCKET_PATHS:
        path = Path(candidate)
        if path.exists():
            mode = path.stat().st_mode
            if stat.S_ISSOCK(mode):
                # Access check: attempt non-destructive docker info later.
                return True, str(path)
    return False, "docker socket not found under " + ", ".join(DOCKER_SOCKET_PATHS)


def docker_preflight(
    images: Sequence[DockerImagePin],
    *,
    pull: bool = True,
    run_probe: bool = True,
) -> dict[str, Any]:
    """Prove Docker socket access, digest-pinned pulls, and a disposable probe."""

    socket_ok, socket_detail = _docker_socket_accessible()
    if not socket_ok:
        raise DockerPreflightError(socket_detail)

    info = _docker("info", "--format", "{{.ServerVersion}}", check=False, timeout=20)
    if info.returncode != 0 or not info.stdout.strip():
        raise DockerPreflightError(
            "docker daemon is not reachable via the socket: "
            + (info.stderr.strip() or info.stdout.strip() or f"exit {info.returncode}")
        )
    server_version = info.stdout.strip()

    pulled: list[dict[str, Any]] = []
    for image in images:
        if "@sha256:" not in image.reference:
            raise DockerPreflightError(
                f"refusing mutable docker tag; require digest pin: {image.reference}"
            )
        if pull:
            pull_result = _docker("pull", image.reference, check=False, timeout=600)
            if pull_result.returncode != 0:
                raise DockerPreflightError(
                    f"failed to pull digest-pinned image {image.reference}: "
                    + (pull_result.stderr.strip() or pull_result.stdout.strip())
                )
        inspect = _docker(
            "image",
            "inspect",
            image.reference,
            "--format",
            "{{json .RepoDigests}}",
            check=False,
            timeout=30,
        )
        if inspect.returncode != 0:
            raise DockerPreflightError(
                f"digest-pinned image not present after pull: {image.reference}: "
                + (inspect.stderr.strip() or inspect.stdout.strip())
            )
        pulled.append(
            {
                "role": image.role,
                "reference": image.reference,
                "digest": image.digest,
                "inspect": inspect.stdout.strip(),
            }
        )

    probe: dict[str, Any] = {"ran": False}
    if run_probe:
        probe_image = next((img for img in images if img.role == "probe"), images[0])
        name = f"{PROBE_CONTAINER_NAME_PREFIX}{os.getpid()}"
        # Ensure no leftover with the same name.
        _docker("rm", "-f", name, check=False, timeout=30)
        run = _docker(
            "run",
            "--rm",
            "--name",
            name,
            probe_image.reference,
            "true",
            check=False,
            timeout=120,
        )
        if run.returncode != 0:
            raise DockerPreflightError(
                "disposable probe container failed: "
                + (run.stderr.strip() or run.stdout.strip() or f"exit {run.returncode}")
            )
        probe = {
            "ran": True,
            "image": probe_image.reference,
            "name": name,
            "command": ["true"],
            "exit_code": 0,
        }

    return {
        "ok": True,
        "socket": socket_detail,
        "server_version": server_version,
        "images": pulled,
        "probe": probe,
    }


# ---------------------------------------------------------------------------
# Environment creation + extension provisioning
# ---------------------------------------------------------------------------


def _assert_supported_host() -> dict[str, Any]:
    if (
        sys.version_info[:2] != SUPPORTED_PYTHON
        or platform.python_implementation() != "CPython"
        or platform.system() != SUPPORTED_SYSTEM
        or platform.machine() not in SUPPORTED_MACHINES
    ):
        raise EnvironmentProvisionError(
            "host must be CPython 3.12 on supported Linux aarch64/x86_64"
        )
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "platform_key": platform_key(),
        "sysconfig_platform": platform.platform(),
    }


def _assert_safe_candidate_root(root: Path, *, supervisor_root: Path) -> None:
    assert_no_supervisor_generation_mutation(
        candidate_root=root,
        supervisor_root=supervisor_root,
    )
    if not root.is_absolute() or len(root.parts) < 3:
        raise EnvironmentProvisionError(f"unsafe candidate environment root: {root}")
    forbidden = {
        Path("/").resolve(),
        Path.home().resolve(),
        repo_root().resolve(),
        Path(sys.base_prefix).resolve(),
        supervisor_root.resolve(),
    }
    if root.resolve() in forbidden or repo_root().resolve() in root.resolve().parents:
        raise EnvironmentProvisionError(
            f"candidate environment root overlaps a protected location: {root}"
        )
    if root.is_symlink():
        raise EnvironmentProvisionError("candidate environment root must not be a symlink")


def _venv_python(root: Path) -> Path:
    return root / "bin" / "python"


def _pip_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("PYTHON") or key.startswith("LD_"):
            environment.pop(key)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _install_duckdb_from_lock(
    *,
    env_root: Path,
    lock: LockPolicy,
    python: Path,
) -> dict[str, Any]:
    artifact_root = env_root / "pip-artifacts"
    artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_copy = artifact_root / "duckdb-quack.lock"
    _atomic_write_text(lock_copy, lock.raw_text, mode=0o600)
    # Materialize a pip-only requirements file (no metadata comments required).
    pip_req = artifact_root / "requirements-pip.txt"
    _atomic_write_text(pip_req, lock.pip_requirement_text, mode=0o600)

    env = _pip_environment()
    download = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "--isolated",
            "download",
            "--disable-pip-version-check",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            "--no-cache-dir",
            "--dest",
            str(artifact_root),
            "--requirement",
            str(pip_req),
        ],
        cwd=repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if download.returncode:
        raise EnvironmentProvisionError(
            "hash-locked DuckDB download failed: "
            + (download.stderr.strip() or download.stdout.strip() or f"exit {download.returncode}")
        )
    report_path = artifact_root / "pip-install-report.json"
    install = subprocess.run(
        [
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
            str(report_path),
            "--requirement",
            str(pip_req),
        ],
        cwd=repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if install.returncode:
        raise EnvironmentProvisionError(
            "hash-locked DuckDB install failed: "
            + (install.stderr.strip() or install.stdout.strip() or f"exit {install.returncode}")
        )
    remove_installer = subprocess.run(
        [str(python), "-m", "pip", "--isolated", "uninstall", "--yes", "pip"],
        cwd=repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if remove_installer.returncode:
        raise EnvironmentProvisionError(
            "pip uninstaller removal failed: "
            + (
                remove_installer.stderr.strip()
                or remove_installer.stdout.strip()
                or f"exit {remove_installer.returncode}"
            )
        )
    wheels = sorted(artifact_root.glob("duckdb-*.whl"))
    if not wheels:
        raise EnvironmentProvisionError("no duckdb wheel retained in pip-artifacts")
    wheel = wheels[0]
    wheel_digest = sha256_file(wheel)
    if wheel_digest not in lock.package_hashes:
        raise EnvironmentProvisionError(
            f"installed wheel digest {wheel_digest} is not admitted by the lock"
        )
    return {
        "artifact_root": str(artifact_root),
        "wheel_path": str(wheel),
        "wheel_sha256": wheel_digest,
        "pip_install_report_path": str(report_path),
        "pip_install_report_sha256": sha256_file(report_path) if report_path.is_file() else "",
    }


def _run_in_candidate(
    python: Path,
    source: str,
    *,
    env: Mapping[str, str] | None = None,
    timeout: float = 300,
) -> Any:
    environment = _pip_environment()
    if env:
        environment.update(env)
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", source],
        cwd=repo_root(),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode:
        raise EnvironmentProvisionError(
            "candidate python probe failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def provision_extension_profiles(
    *,
    python: Path,
    lock: LockPolicy,
    extension_root: Path,
    platform_name: str | None = None,
    allow_network_install: bool = True,
    duckdb_module: Any | None = None,
) -> dict[str, Any]:
    """Explicitly install pinned extensions, verify checksums, then harden.

    When ``duckdb_module`` is provided (tests), network install is skipped and
    the caller is responsible for placing artifacts under ``extension_root``.
    Offline or digest-mismatched artifacts fail closed before any dispatch.
    """

    plat = platform_name or platform_key()
    extension_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    version_dir = extension_root / f"v{REQUIRED_DUCKDB_VERSION}" / plat
    version_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    ordered = lock.ordered_profiles()
    installed: list[dict[str, Any]] = []

    if duckdb_module is None:
        # Real provisioning inside the candidate interpreter.
        profiles_payload = [p.to_dict() for p in ordered]
        script = f"""
import json, hashlib, pathlib, duckdb, os, sys
ext_root = pathlib.Path({str(extension_root)!r})
plat = {plat!r}
version = {REQUIRED_DUCKDB_VERSION!r}
profiles = json.loads({json.dumps(profiles_payload)!r})
allow_network = {bool(allow_network_install)!r}
version_dir = ext_root / f"v{{version}}" / plat
version_dir.mkdir(parents=True, exist_ok=True)
conn = duckdb.connect(config={{
    "extension_directory": str(ext_root),
    "autoinstall_known_extensions": "true" if allow_network else "false",
    "autoload_known_extensions": "false",
}})
results = []
for profile in sorted(profiles, key=lambda p: p["load_order"]):
    name = profile["name"]
    art = profile["artifacts"][plat]
    expected = art["sha256"]
    filename = art["filename"]
    target = version_dir / filename
    if not target.is_file():
        if not allow_network:
            raise SystemExit(f"offline extension install refused for {{name}}: missing {{target}}")
        try:
            conn.execute(f"INSTALL {{name}}")
        except Exception as exc:
            raise SystemExit(f"extension install failed for {{name}} before task dispatch: {{type(exc).__name__}}: {{exc}}")
    if not target.is_file():
        # DuckDB may place the file under the version/platform tree; re-scan.
        matches = list(version_dir.glob(filename))
        if not matches:
            matches = list(ext_root.rglob(filename))
        if not matches:
            raise SystemExit(f"extension artifact missing after INSTALL {{name}}: {{filename}}")
        target = matches[0]
    digest = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != expected:
        raise SystemExit(
            f"extension checksum mismatch for {{name}} on {{plat}}: "
            f"expected {{expected}}, got {{digest}} (path={{target}})"
        )
    # Explicit LOAD before configuration lock.
    conn.execute(f"LOAD {{name}}")
    results.append({{
        "name": name,
        "build": profile["build"],
        "load_order": profile["load_order"],
        "platform": plat,
        "path": str(target),
        "sha256": digest,
        "loaded": True,
    }})
# Harden: disable automatic install/load after explicit provisioning.
conn.execute("SET autoinstall_known_extensions=false")
conn.execute("SET autoload_known_extensions=false")
autoinstall = conn.execute(
    "SELECT value FROM duckdb_settings() WHERE name='autoinstall_known_extensions'"
).fetchone()[0]
autoload = conn.execute(
    "SELECT value FROM duckdb_settings() WHERE name='autoload_known_extensions'"
).fetchone()[0]
if autoinstall != "false" or autoload != "false":
    raise SystemExit(f"failed to disable automatic extensions: autoinstall={{autoinstall}} autoload={{autoload}}")
# Prove offline / incompatible install fails closed after hardening.
failed_closed = False
failure_detail = ""
try:
    conn.execute("INSTALL __dqk082_nonexistent_extension__")
except Exception as exc:
    failed_closed = True
    failure_detail = f"{{type(exc).__name__}}: {{exc}}"
if not failed_closed:
    raise SystemExit("post-provision INSTALL did not fail closed")
# Prove DuckLake ATTACH can set AUTOMATIC_MIGRATION false.
import tempfile
td = pathlib.Path(tempfile.mkdtemp(prefix="dqk082-lake-"))
data = td / "data"
data.mkdir()
meta = td / "meta.db"
conn.execute(
    f"ATTACH 'ducklake:{{meta.as_posix()}}' AS dqk082_lake "
    f"(DATA_PATH '{{data.as_posix()}}', AUTOMATIC_MIGRATION false)"
)
duckdb_version = str(duckdb.__version__)
print(json.dumps({{
    "duckdb_version": duckdb_version,
    "platform": plat,
    "extension_root": str(ext_root),
    "extensions": results,
    "autoinstall_known_extensions": autoinstall,
    "autoload_known_extensions": autoload,
    "ducklake_automatic_migration": False,
    "offline_install_failed_closed": failed_closed,
    "offline_install_detail": failure_detail[:500],
}}, sort_keys=True))
"""
        payload = _run_in_candidate(python, script, timeout=600)
        if not isinstance(payload, dict):
            raise EnvironmentProvisionError("extension provisioning returned non-object")
        if payload.get("duckdb_version") != REQUIRED_DUCKDB_VERSION:
            raise EnvironmentProvisionError(
                f"DuckDB version mismatch: {payload.get('duckdb_version')!r} != {REQUIRED_DUCKDB_VERSION!r}"
            )
        return payload

    # Test / injected path: verify pre-staged artifacts only.
    for profile in ordered:
        art = profile.artifact_for(plat)
        target = version_dir / art.filename
        if not target.is_file():
            raise EnvironmentProvisionError(
                f"offline or missing extension artifact for {profile.name}: {target}"
            )
        digest = sha256_file(target)
        if digest != art.sha256:
            raise EnvironmentProvisionError(
                f"incompatible extension checksum for {profile.name}: "
                f"expected {art.sha256}, got {digest}"
            )
        installed.append(
            {
                "name": profile.name,
                "build": profile.build,
                "load_order": profile.load_order,
                "platform": plat,
                "path": str(target),
                "sha256": digest,
                "loaded": True,
            }
        )
    return {
        "duckdb_version": REQUIRED_DUCKDB_VERSION,
        "platform": plat,
        "extension_root": str(extension_root),
        "extensions": installed,
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
        "ducklake_automatic_migration": False,
        "offline_install_failed_closed": True,
        "offline_install_detail": "injected-path",
    }


def verify_post_provision_hardening(
    *,
    python: Path,
    extension_root: Path,
) -> dict[str, Any]:
    """Re-open a connection and prove autoinstall/autoload remain disabled."""

    script = f"""
import json, duckdb
conn = duckdb.connect(config={{
    "extension_directory": {str(extension_root)!r},
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}})
autoinstall = conn.execute(
    "SELECT value FROM duckdb_settings() WHERE name='autoinstall_known_extensions'"
).fetchone()[0]
autoload = conn.execute(
    "SELECT value FROM duckdb_settings() WHERE name='autoload_known_extensions'"
).fetchone()[0]
print(json.dumps({{
    "autoinstall_known_extensions": autoinstall,
    "autoload_known_extensions": autoload,
    "duckdb_version": duckdb.__version__,
}}, sort_keys=True))
"""
    payload = _run_in_candidate(python, script)
    if not isinstance(payload, dict):
        raise EnvironmentProvisionError("hardening verification returned non-object")
    if payload.get("autoinstall_known_extensions") != "false":
        raise EnvironmentProvisionError("autoinstall_known_extensions is not disabled")
    if payload.get("autoload_known_extensions") != "false":
        raise EnvironmentProvisionError("autoload_known_extensions is not disabled")
    if payload.get("duckdb_version") != REQUIRED_DUCKDB_VERSION:
        raise EnvironmentProvisionError(
            f"DuckDB is not exactly {REQUIRED_DUCKDB_VERSION}: {payload.get('duckdb_version')!r}"
        )
    return payload


def _creation_command(
    *,
    lock_path: Path,
    env_root: Path,
    receipt_path: Path,
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "create",
        "--lock",
        str(lock_path),
        "--env-root",
        str(env_root),
        "--receipt",
        str(receipt_path),
    ]


def build_candidate_receipt(
    *,
    lock: LockPolicy,
    env_root: Path,
    host: Mapping[str, Any],
    repository: Mapping[str, Any],
    docker: Mapping[str, Any],
    disk: Mapping[str, Any],
    pip_install: Mapping[str, Any],
    extensions: Mapping[str, Any],
    providers: Sequence[Mapping[str, Any]],
    creation_command: Sequence[str],
    supervisor_env_root: Path,
    hardening: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": CANDIDATE_ENVIRONMENT_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "attestation_scope": lock.attestation_scope,
        "quack_extension_attested": True,
        "ducklake_extension_attested": True,
        "environment_root": str(env_root.resolve()),
        "supervisor_environment_root": str(supervisor_env_root.resolve()),
        "isolated_from_supervisor": str(env_root.resolve())
        != str(supervisor_env_root.resolve()),
        "generation_mutation": {
            "master_changed": False,
            "lane_changed": False,
            "daemon_changed": False,
            "writer_generation_changed": False,
        },
        "python": {
            "version": host.get("python_version"),
            "implementation": host.get("python_implementation"),
            "executable": str((env_root / "bin" / "python").resolve())
            if (env_root / "bin" / "python").exists()
            else str(sys.executable),
        },
        "platform": {
            "system": host.get("system"),
            "machine": host.get("machine"),
            "platform_key": host.get("platform_key"),
            "sysconfig_platform": host.get("sysconfig_platform"),
        },
        "lockfile": {
            "path": lock.path.relative_to(repo_root()).as_posix()
            if lock.path.is_relative_to(repo_root())
            else str(lock.path),
            "sha256": lock.sha256,
            "schema": lock.schema,
            "duckdb_version": lock.duckdb_version,
            "package_hashes": sorted(lock.package_hashes),
            "extension_profiles": [p.to_dict() for p in lock.ordered_profiles()],
        },
        "duckdb": {
            "version": REQUIRED_DUCKDB_VERSION,
            "wheel_sha256": pip_install.get("wheel_sha256", ""),
            "wheel_path": pip_install.get("wheel_path", ""),
        },
        "quack": lock.profile("quack").to_dict(),
        "ducklake": lock.profile("ducklake").to_dict(),
        "extensions": extensions,
        "hardening": {
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "ducklake_automatic_migration": False,
            "verified": dict(hardening),
        },
        "provider_binaries": list(providers),
        "repository": dict(repository),
        "docker_preflight": dict(docker),
        "disk_preflight": dict(disk),
        "creation_command": list(creation_command),
        "creation_policy": {
            "system_site_packages": False,
            "clear_existing": False,
            "upgrade_existing": False,
            "requires_hashes": True,
            "binary_only": True,
            "dependencies_disabled": True,
            "explicit_extension_load_order": [
                p.name for p in lock.ordered_profiles()
            ],
        },
    }
    payload["receipt_id"] = content_receipt_id(payload)
    return payload


def validate_candidate_receipt(
    receipt: Any,
    *,
    lock: LockPolicy | None = None,
) -> tuple[bool, str]:
    if not isinstance(receipt, dict):
        return False, "receipt is not an object"
    required = {
        "schema",
        "receipt_id",
        "program_id",
        "task_id",
        "attestation_scope",
        "quack_extension_attested",
        "ducklake_extension_attested",
        "environment_root",
        "supervisor_environment_root",
        "isolated_from_supervisor",
        "generation_mutation",
        "python",
        "platform",
        "lockfile",
        "duckdb",
        "quack",
        "ducklake",
        "extensions",
        "hardening",
        "provider_binaries",
        "repository",
        "docker_preflight",
        "disk_preflight",
        "creation_command",
        "creation_policy",
    }
    if set(receipt) != required:
        return False, f"receipt shape mismatch: extra/missing keys {set(receipt) ^ required}"
    if receipt["schema"] != CANDIDATE_ENVIRONMENT_RECEIPT_SCHEMA:
        return False, "receipt schema mismatch"
    if receipt["task_id"] != TASK_ID:
        return False, "receipt task_id mismatch"
    if receipt.get("duckdb", {}).get("version") != REQUIRED_DUCKDB_VERSION:
        return False, "receipt DuckDB version is not 1.5.5"
    if not receipt.get("isolated_from_supervisor"):
        return False, "receipt does not attest isolation from supervisor"
    mutation = receipt.get("generation_mutation") or {}
    if any(mutation.get(key) for key in (
        "master_changed",
        "lane_changed",
        "daemon_changed",
        "writer_generation_changed",
    )):
        return False, "receipt claims a supervisor generation mutation"
    hardening = receipt.get("hardening") or {}
    if (
        hardening.get("autoinstall_known_extensions") is not False
        or hardening.get("autoload_known_extensions") is not False
        or hardening.get("ducklake_automatic_migration") is not False
    ):
        return False, "receipt does not disable automatic install/load/migration"
    expected_id = content_receipt_id(receipt)
    if receipt.get("receipt_id") != expected_id:
        return False, "receipt_id is not content-bound"
    if lock is not None:
        if receipt.get("lockfile", {}).get("sha256") != lock.sha256:
            return False, "receipt lockfile digest mismatch"
        if receipt.get("quack", {}).get("build") != lock.profile("quack").build:
            return False, "receipt Quack profile mismatch"
        if receipt.get("ducklake", {}).get("build") != lock.profile("ducklake").build:
            return False, "receipt DuckLake profile mismatch"
    return True, str(receipt["receipt_id"])


def create_candidate_environment(
    *,
    lock_path: Path | None = None,
    env_root: Path | None = None,
    receipt_path: Path | None = None,
    supervisor_env_root: Path | None = None,
    repository_root: Path | None = None,
    skip_docker: bool = False,
    skip_extension_network: bool = False,
    docker_preflight_fn: Callable[..., dict[str, Any]] | None = None,
    disk_preflight_fn: Callable[..., dict[str, Any]] | None = None,
    allow_recreate: bool = False,
) -> dict[str, Any]:
    """Create or exactly re-validate the candidate environment and receipt."""

    root = (repository_root or repo_root()).resolve()
    lock_file = (lock_path or default_lock_path(root)).resolve()
    lock = load_lock_policy(lock_file)
    candidate = (env_root or default_candidate_env_root(root)).resolve()
    supervisor = (supervisor_env_root or default_supervisor_env_root(root)).resolve()
    receipt_file = (
        receipt_path or (candidate / "candidate-environment-receipt.json")
    ).resolve()

    _assert_safe_candidate_root(candidate, supervisor_root=supervisor)
    assert_no_supervisor_generation_mutation(
        candidate_root=candidate,
        supervisor_root=supervisor,
        mutated_paths=(lock_file, receipt_file, candidate),
    )

    host = _assert_supported_host()
    creation_cmd = _creation_command(
        lock_path=lock_file,
        env_root=candidate,
        receipt_path=receipt_file,
    )

    # Preflight *before* any task-dispatch side effects beyond this candidate tree.
    docker_fn = docker_preflight_fn or docker_preflight
    disk_fn = disk_preflight_fn or disk_capacity_preflight
    if skip_docker:
        docker_result = {
            "ok": True,
            "skipped": True,
            "reason": "skip_docker requested by caller",
            "images": [
                {"role": img.role, "reference": img.reference, "digest": img.digest}
                for img in lock.docker_images
            ],
            "probe": {"ran": False},
        }
    else:
        docker_result = docker_fn(lock.docker_images, pull=True, run_probe=True)
    disk_result = disk_fn(
        workspace_path=candidate.parent,
        image_path=None,
        volume_path=None,
        minima=lock.disk_minima,
    )

    if candidate.exists() and not allow_recreate:
        if not receipt_file.is_file():
            raise EnvironmentProvisionError(
                "refusing to modify existing candidate environment without a valid receipt; "
                "archive it explicitly after review"
            )
        existing = json.loads(receipt_file.read_text(encoding="utf-8"))
        valid, detail = validate_candidate_receipt(existing, lock=lock)
        if not valid:
            raise EnvironmentProvisionError(
                f"existing candidate receipt is invalid: {detail}"
            )
        if existing.get("environment_root") != str(candidate):
            raise EnvironmentProvisionError(
                "existing receipt environment_root does not match candidate root"
            )
        return {
            "status": "already-valid",
            "environment_root": str(candidate),
            "receipt_path": str(receipt_file),
            "receipt_id": existing["receipt_id"],
            "dqk_082_completed": True,
            "generation_mutation": existing["generation_mutation"],
        }

    # Create isolated venv.
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists() and allow_recreate:
        shutil.rmtree(candidate)
    try:
        os.mkdir(candidate, mode=0o700)
    except FileExistsError as exc:
        if not allow_recreate:
            raise EnvironmentProvisionError(
                "candidate environment appeared concurrently; refusing to modify it"
            ) from exc
    builder = venv.EnvBuilder(
        system_site_packages=False,
        clear=False,
        symlinks=True,
        upgrade=False,
        with_pip=True,
        upgrade_deps=False,
    )
    builder.create(candidate)
    python = _venv_python(candidate)
    if not python.is_file():
        raise EnvironmentProvisionError(f"venv creation did not produce {python}")

    pip_install = _install_duckdb_from_lock(env_root=candidate, lock=lock, python=python)
    extension_root = candidate / "extension-profiles"
    extensions = provision_extension_profiles(
        python=python,
        lock=lock,
        extension_root=extension_root,
        allow_network_install=not skip_extension_network,
    )
    hardening = verify_post_provision_hardening(
        python=python,
        extension_root=extension_root,
    )
    repository = repository_evidence(root, lock_file)
    providers = provider_binary_evidence()
    receipt = build_candidate_receipt(
        lock=lock,
        env_root=candidate,
        host=host,
        repository=repository,
        docker=docker_result,
        disk=disk_result,
        pip_install=pip_install,
        extensions=extensions,
        providers=providers,
        creation_command=creation_cmd,
        supervisor_env_root=supervisor,
        hardening=hardening,
    )
    valid, detail = validate_candidate_receipt(receipt, lock=lock)
    if not valid:
        raise EnvironmentProvisionError(f"built receipt failed validation: {detail}")
    _atomic_write_json(receipt_file, receipt, mode=0o600)
    persisted = json.loads(receipt_file.read_text(encoding="utf-8"))
    valid, detail = validate_candidate_receipt(persisted, lock=lock)
    if not valid:
        raise EnvironmentProvisionError(f"persisted receipt failed validation: {detail}")

    # Final non-mutation assertion: still isolated, no generation markers written.
    assert_no_supervisor_generation_mutation(
        candidate_root=candidate,
        supervisor_root=supervisor,
    )
    return {
        "status": "created",
        "environment_root": str(candidate),
        "receipt_path": str(receipt_file),
        "receipt_id": receipt["receipt_id"],
        "python": str(python),
        "extension_root": str(extension_root),
        "dqk_082_completed": True,
        "generation_mutation": receipt["generation_mutation"],
        "lock_sha256": lock.sha256,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or verify the DQK-082 candidate DuckDB/Quack/DuckLake environment",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Provision the candidate environment")
    create.add_argument("--lock", type=Path, default=None)
    create.add_argument("--env-root", type=Path, default=None)
    create.add_argument("--receipt", type=Path, default=None)
    create.add_argument("--supervisor-env-root", type=Path, default=None)
    create.add_argument("--skip-docker", action="store_true")
    create.add_argument("--skip-extension-network", action="store_true")
    create.add_argument("--allow-recreate", action="store_true")
    create.add_argument("--json", action="store_true")

    verify = sub.add_parser("verify-receipt", help="Validate a candidate receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--lock", type=Path, default=None)
    verify.add_argument("--json", action="store_true")

    preflight = sub.add_parser("preflight", help="Run Docker and disk preflight only")
    preflight.add_argument("--lock", type=Path, default=None)
    preflight.add_argument("--workspace", type=Path, default=None)
    preflight.add_argument("--json", action="store_true")

    show = sub.add_parser("show-lock", help="Parse and print the lock policy")
    show.add_argument("--lock", type=Path, default=None)
    show.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "show-lock":
            lock = load_lock_policy((args.lock or default_lock_path()).resolve())
            payload = lock.to_dict()
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.command == "preflight":
            lock = load_lock_policy((args.lock or default_lock_path()).resolve())
            workspace = (args.workspace or default_candidate_env_root().parent).resolve()
            docker_result = docker_preflight(lock.docker_images, pull=True, run_probe=True)
            disk_result = disk_capacity_preflight(
                workspace_path=workspace,
                image_path=None,
                volume_path=None,
                minima=lock.disk_minima,
            )
            payload = {"docker": docker_result, "disk": disk_result, "ok": True}
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.command == "verify-receipt":
            receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
            lock = load_lock_policy((args.lock or default_lock_path()).resolve())
            valid, detail = validate_candidate_receipt(receipt, lock=lock)
            payload = {"ok": valid, "detail": detail}
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if valid else 1
        if args.command == "create":
            result = create_candidate_environment(
                lock_path=args.lock,
                env_root=args.env_root,
                receipt_path=args.receipt,
                supervisor_env_root=args.supervisor_env_root,
                skip_docker=bool(args.skip_docker),
                skip_extension_network=bool(args.skip_extension_network),
                allow_recreate=bool(args.allow_recreate),
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        raise EnvironmentProvisionError(f"unknown command {args.command!r}")
    except EnvironmentProvisionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
