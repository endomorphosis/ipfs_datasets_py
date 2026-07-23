"""User-local installers for optional external theorem provers.

Important:
- Lean/Coq and the protocol/model-checking solvers are native tools, not Python
  packages.
- Z3/CVC5/SymbolicAI are imported through Python packages by the prover bridges.
- Installing them automatically during `pip install` can be surprising and may fail
  depending on OS/package manager permissions.

This module provides an installer that can be invoked:
- Manually via console script: `ipfs-datasets-install-provers`
- Or from setup.py post-install hooks when explicitly enabled via env vars.
- Or lazily by an execution path through
  ``ensure_prover_executable(...)``. Lazy execution installs are visible on
  stdout and can be forwarded to a UI progress callback.

Environment variables (all optional):
- IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS: enable running installer post-install (default: 0)
- IPFS_DATASETS_PY_AUTO_INSTALL_Z3: enable Z3 install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_CVC5: enable CVC5 install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_LEAN: enable Lean install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_COQ: enable Coq install attempts (default: 0)
- IPFS_DATASETS_PY_AUTO_INSTALL_SYMBOLICAI: enable SymbolicAI install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_ERGOAI: enable ErgoAI/ErgoEngine install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS: enable install attempts from requested prover bridges (default: 0)
- IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>: per-prover lazy install override
  (Z3/CVC5/LEAN/COQ/APALACHE/TAMARIN/MAUDE/PROVERIF/SYMBOLICAI/ERGOAI)
- IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS: allow lazy Coq install to use interactive sudo (default: 0)
- IPFS_DATASETS_PY_ERGOAI_GIT_URL: override ErgoAI/ErgoEngine source repository.
- IPFS_DATASETS_PY_ERGOAI_RELEASE_URL: override the official ErgoAI .run installer URL.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR: user-local directory for official ErgoAI release installs.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_RELEASE=0: skip the official release installer path.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND: custom command used before git clone fallback.
- ERGOAI_BINARY: explicit path to the ErgoAI executable/runErgo.sh.
- IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT: root for downloaded native solver
  artifacts (default: ~/.local/share/ipfs_datasets_py/theorem-provers).
- IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND: platform-specific custom native
  installer override for APALACHE, TAMARIN, MAUDE, PROVERIF, CVC5, or COQ.
- IPFS_DATASETS_PY_COQ_OPAM_ROOT: root of the isolated user-local Coq OPAM
  installation.

The installer is best-effort and never raises on failure unless `--strict` is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from shlex import quote as shell_quote
from shlex import split as shell_split
from typing import Callable

logger = logging.getLogger(__name__)
DEFAULT_ERGOAI_GIT_URL = "https://github.com/ErgoAI/ErgoEngine.git"
DEFAULT_ERGOAI_RELEASE_URL = (
    "https://github.com/ErgoAI/.github/releases/download/"
    "v3.0_release/ergoAI_3.0.run"
)
DEFAULT_EXTERNAL_PROVER_ROOT = (
    Path.home() / ".local" / "share" / "ipfs_datasets_py" / "theorem-provers"
)
APALACHE_VERSION = "0.58.3"
APALACHE_LINUX_X86_64_URL = (
    "https://github.com/apalache-mc/apalache/releases/download/"
    "v0.58.3/apalache-0.58.3.tgz"
)
APALACHE_LINUX_X86_64_SHA256 = (
    "ba622db9538aebf942cc7a7815f942a6b2b419012707e16dfdc25a73ff95d0a5"
)
TAMARIN_VERSION = "1.12.0"
TAMARIN_LINUX_X86_64_URL = (
    "https://github.com/tamarin-prover/tamarin-prover/releases/download/"
    "1.12.0/tamarin-prover-1.12.0-linux64-ubuntu.tar.gz"
)
TAMARIN_LINUX_X86_64_SHA256 = (
    "201be06f469e47cff554df6ca93db8366fc2c69d70c61fcbd1370a1074b469c6"
)
MAUDE_VERSION = "3.5.1"
MAUDE_LINUX_X86_64_URL = (
    "https://github.com/maude-lang/Maude/releases/download/"
    "Maude3.5.1/Maude-3.5.1-linux-x86_64.zip"
)
MAUDE_LINUX_X86_64_SHA256 = (
    "72ed1ca87e3b3d0dfc6ee1436baf154bf04c45ff97d521bec040c5e8dfc8f92c"
)
PROVERIF_VERSION = "2.05"
PROVERIF_SOURCE_URL = "https://proverif.inria.fr/proverif2.05.tar.gz"
PROVERIF_SOURCE_SHA256 = (
    "4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4"
)
ROCQ_VERSION = "9.1.1"
ROCQ_OPAM_REPOSITORY = "https://rocq-prover.org/opam/released"
LEAN_TOOLCHAIN = "v4.31.0"
CVC5_VERSION = "1.3.2"
CVC5_RELEASES: dict[tuple[str, str], tuple[str, str]] = {
    ("linux", "x86_64"): (
        "https://github.com/cvc5/cvc5/releases/download/cvc5-1.3.2/"
        "cvc5-Linux-x86_64-static.zip",
        "1060daaf507edef9d0a68e399cfc0e9038150bccb9e2d34d081d50a7687544d2",
    ),
    ("linux", "aarch64"): (
        "https://github.com/cvc5/cvc5/releases/download/cvc5-1.3.2/"
        "cvc5-Linux-arm64-static.zip",
        "21bd93916b3214ba64538cbd82bb2f6650ab441c5781f6c83afd3707d78d79da",
    ),
    ("darwin", "x86_64"): (
        "https://github.com/cvc5/cvc5/releases/download/cvc5-1.3.2/"
        "cvc5-macOS-x86_64-static.zip",
        "b4ab528a63592da89c81eb10e35167f1e6051fd2ad8969f4e6ec54e0708fe774",
    ),
    ("darwin", "arm64"): (
        "https://github.com/cvc5/cvc5/releases/download/cvc5-1.3.2/"
        "cvc5-macOS-arm64-static.zip",
        "172b6ff70662184725aedf64b0189a870cc7562aca1bad9cd0ec92f682edb3af",
    ),
}
ProgressCallback = Callable[[str, str], None]

# These are reviewed compatibility targets for the verification lanes, not a
# background "latest" channel. An operator checks or refreshes them manually
# through the installer CLI so solver evidence remains reproducible.
MANAGED_SOLVER_VERSIONS: dict[str, str] = {
    "apalache": APALACHE_VERSION,
    "tamarin": TAMARIN_VERSION,
    "maude": MAUDE_VERSION,
    "proverif": PROVERIF_VERSION,
    "cvc5": CVC5_VERSION,
    "lean": LEAN_TOOLCHAIN,
    "rocq": ROCQ_VERSION,
    "z3": ">=4.12.0,<5.0.0",
    "symbolicai": ">=1.14.0,<2.0.0",
    "ergoai": "3.0",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _run(
    cmd: list[str],
    *,
    check: bool,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> int:
    proc = subprocess.run(cmd, text=True, env=env, cwd=cwd)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.returncode


def _common_bin_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        home = Path.home()
    except (OSError, RuntimeError):
        return dirs
    dirs.extend(
        [
            home / ".local" / "bin",
            home / ".elan" / "bin",
            home / ".opam" / "default" / "bin",
            _external_prover_bin_dir(),
        ]
    )
    return dirs


def _external_prover_root() -> Path:
    configured = os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_EXTERNAL_PROVER_ROOT


def _external_prover_bin_dir() -> Path:
    return _external_prover_root() / "bin"


def _announce(message: str, on_progress: ProgressCallback | None = None, *, phase: str = "installing") -> None:
    """Emit progress before potentially long user-local installation steps."""

    print(f"[ipfs_datasets_py] {message}", flush=True)
    if on_progress is not None:
        on_progress(phase, message)


def _prepend_external_prover_bin_to_path() -> None:
    bin_dir = _external_prover_bin_dir()
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) not in path_entries:
        os.environ["PATH"] = os.pathsep.join([str(bin_dir), *path_entries])


def _which(cmd: str) -> str | None:
    found = shutil.which(cmd)
    if found:
        return found
    for directory in _common_bin_dirs():
        candidate = directory / cmd
        try:
            if candidate.exists() and os.access(str(candidate), os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


def _read_version(executable: str | None) -> str:
    """Return a compact version line without treating a probe as an install."""

    if executable is None:
        return ""
    version_pattern = re.compile(
        r"(?:^|\b(?:version|proverif|tamarin-prover|lean|rocq|coq|maude|cvc5|apalache(?:-mc)?)\s*(?:is|,)?\s*)v?\d+\.\d+",
        flags=re.IGNORECASE,
    )
    for arguments in (["--version"], ["-version"], ["version"]):
        try:
            completed = subprocess.run(
                [executable, *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        # Several otherwise usable solvers disagree on their version flag.
        # ProVerif, for example, reports an unsupported ``--version`` option
        # before printing its version, while cvc5 can print a usage line before
        # succeeding with ``-version``.  Keep searching for an informative
        # line instead of rejecting the whole probe output.
        output = "\n".join(
            value.strip() for value in (completed.stdout, completed.stderr) if value.strip()
        )
        for line in output.splitlines():
            compact = line.strip()
            lowered = compact.lower()
            if not compact or any(
                marker in lowered
                for marker in ("usage", "unknown option", "unrecognized option", "error:")
            ):
                continue
            # A few tools (notably ProVerif) return a non-zero status for an
            # unsupported flag but still print an authoritative version line.
            # Do not accept arbitrary output from those failed invocations.
            if version_pattern.search(compact):
                return compact
    return ""


def _version_matches(executable: str | None, expected: str) -> bool:
    """Return whether an executable reports the pinned release identifier."""

    observed = _read_version(executable).lstrip("v")
    return bool(observed and str(expected).lstrip("v") in observed)


def _distribution_version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return ""


def managed_solver_version_status() -> list[dict[str, str | bool | None]]:
    """Report managed-version drift without downloading or changing any solver."""

    specs = (
        ("apalache", "apalache-mc", APALACHE_VERSION, None),
        ("tamarin", "tamarin-prover", TAMARIN_VERSION, None),
        ("maude", "maude", MAUDE_VERSION, None),
        ("proverif", "proverif", PROVERIF_VERSION, None),
        ("cvc5", "cvc5", CVC5_VERSION, None),
        ("lean", "lean", os.environ.get("IPFS_DATASETS_PY_LEAN_TOOLCHAIN", LEAN_TOOLCHAIN), None),
        ("rocq", _which("rocq") or _which("coqc"), ROCQ_VERSION, None),
        ("z3", "z3", MANAGED_SOLVER_VERSIONS["z3"], "z3-solver"),
        ("symbolicai", None, MANAGED_SOLVER_VERSIONS["symbolicai"], "symbolicai"),
        ("ergoai", _find_ergoai_binary(), MANAGED_SOLVER_VERSIONS["ergoai"], None),
    )
    statuses: list[dict[str, str | bool | None]] = []
    for name, executable_name, target, distribution in specs:
        executable = (
            str(executable_name)
            if isinstance(executable_name, Path)
            else _which(executable_name) if isinstance(executable_name, str) else None
        )
        observed = _distribution_version(distribution) if distribution else _read_version(executable)
        if name == "proverif" and executable and not observed:
            try:
                launcher_contents = Path(executable).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                launcher_contents = ""
            if f"proverif{target}" in launcher_contents:
                observed = str(target)
        present = bool(observed or executable)
        # Version strings vary by solver; containment catches the reviewed
        # fixed releases while package ranges are reported for human review.
        normalized_target = str(target).lstrip("v")
        normalized_observed = observed.lstrip("v")
        matches = bool(observed and normalized_target in normalized_observed)
        if name in {"z3", "symbolicai"}:
            matches = bool(observed)
        statuses.append(
            {
                "solver": name,
                "managed_version": str(target),
                "executable": executable,
                "installed_version": observed or None,
                "present": present,
                "status": "managed" if matches else "manual_update_required" if present else "missing",
                "manual_update_required": not matches,
            }
        )
    return statuses


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_release_artifact(
    url: str,
    destination: Path,
    expected_sha256: str,
    *,
    strict: bool,
    on_progress: ProgressCallback | None,
) -> bool:
    """Download and checksum a release artifact without trusting a shell pipeline."""

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file():
            _announce(
                f"Downloading theorem-prover artifact from {url}",
                on_progress,
            )
            urllib.request.urlretrieve(url, destination)
        observed = _sha256(destination)
        if observed != expected_sha256:
            destination.unlink(missing_ok=True)
            raise RuntimeError(
                f"checksum mismatch for {destination.name}: expected {expected_sha256}, got {observed}"
            )
        return True
    except Exception as exc:
        _announce(f"Theorem-prover download failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:*") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"refusing unsafe archive member: {member.name}")
        bundle.extractall(destination, filter="data")


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"refusing unsafe archive member: {member.filename}")
        bundle.extractall(destination)


def _write_launcher(name: str, executable: Path, *, environment: dict[str, str] | None = None) -> Path:
    """Create a user-local launcher that keeps solver dependencies discoverable."""

    bin_dir = _external_prover_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / name
    exports = [
        'launcher_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
        'export PATH="$launcher_dir${PATH:+:$PATH}"',
    ]
    for key, value in sorted((environment or {}).items()):
        if not key.isidentifier():
            raise ValueError(f"invalid launcher environment key: {key}")
        exports.append(f"export {key}={shell_quote(str(value))}\"${{{key}:+:${key}}}\"")
    launcher.write_text(
        "#!/bin/sh\nset -eu\n"
        + "\n".join(exports)
        + f"\nexec {shell_quote(str(executable))} \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    _prepend_external_prover_bin_to_path()
    return launcher


def _write_ergoai_launchers(binary: Path) -> None:
    """Expose ErgoAI under common command names in the managed prover bin dir."""

    executable = binary.resolve()
    launcher_names = ("runergo", "runErgo.sh")
    for launcher_name in launcher_names:
        _write_launcher(
            launcher_name,
            executable,
            environment={"ERGOAI_BINARY": str(executable)},
        )


def _run_custom_solver_installer(
    solver: str,
    *,
    strict: bool,
    on_progress: ProgressCallback | None,
) -> bool:
    command = str(os.environ.get(f"IPFS_DATASETS_PY_{solver.upper()}_INSTALL_COMMAND") or "").strip()
    if not command:
        return False
    try:
        _announce(f"Installing {solver} with configured custom installer...", on_progress)
        return _run(shell_split(command), check=strict) == 0
    except Exception as exc:
        _announce(f"Custom {solver} installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def _linux_x86_64() -> bool:
    return platform.system().lower() == "linux" and platform.machine().lower() in {"x86_64", "amd64"}


@dataclass(frozen=True)
class PlatformInstallProfile:
    """Detected platform/package-manager state for prover dependency installs."""

    system: str
    architecture: str
    package_manager: str | None
    package_manager_path: str | None
    is_root: bool
    sudo_path: str | None
    passwordless_sudo: bool

    @property
    def can_install_system_packages(self) -> bool:
        if self.package_manager is None:
            return False
        return self.is_root or self.package_manager in {"brew", "conda", "mamba"} or bool(
            self.sudo_path
        )


def _sudo_non_interactive_ok(sudo_path: str | None = None) -> bool:
    sudo = sudo_path or _which("sudo")
    if not sudo:
        return False
    try:
        probe = subprocess.run(
            [sudo, "-n", "true"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return probe.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
        logger.debug("Could not check sudo access: %s", exc)
        return False


def detect_platform_install_profile() -> PlatformInstallProfile:
    """Detect the current OS, architecture, package manager, and sudo mode."""

    system = platform.system().lower()
    architecture = platform.machine().lower()
    manager_priority = (
        ("apt", "apt-get"),
        ("dnf", "dnf"),
        ("yum", "yum"),
        ("pacman", "pacman"),
        ("zypper", "zypper"),
        ("apk", "apk"),
        ("brew", "brew"),
        ("mamba", "mamba"),
        ("conda", "conda"),
    )
    package_manager: str | None = None
    package_manager_path: str | None = None
    for manager, executable in manager_priority:
        path = _which(executable)
        if path:
            package_manager = manager
            package_manager_path = path
            break

    is_root = bool(hasattr(os, "geteuid") and os.geteuid() == 0)
    sudo_path = _which("sudo")
    return PlatformInstallProfile(
        system=system,
        architecture=architecture,
        package_manager=package_manager,
        package_manager_path=package_manager_path,
        is_root=is_root,
        sudo_path=sudo_path,
        passwordless_sudo=_sudo_non_interactive_ok(sudo_path),
    )


_SYSTEM_PACKAGE_NAMES: dict[str, dict[str, list[str]]] = {
    "opam": {
        "apt": ["opam"],
        "dnf": ["opam"],
        "yum": ["opam"],
        "pacman": ["opam"],
        "zypper": ["opam"],
        "apk": ["opam"],
        "brew": ["opam"],
        "conda": ["opam"],
        "mamba": ["opam"],
    },
    "coq": {
        "apt": ["coq"],
        "dnf": ["coq"],
        "yum": ["coq"],
        "pacman": ["coq"],
        "zypper": ["coq"],
        "apk": ["coq"],
        "brew": ["coq"],
        "conda": ["coq"],
        "mamba": ["coq"],
    },
    "ergoai_build": {
        "apt": ["git", "make", "gcc", "g++", "unzip", "tar"],
        "dnf": ["git", "make", "gcc", "gcc-c++", "unzip", "tar"],
        "yum": ["git", "make", "gcc", "gcc-c++", "unzip", "tar"],
        "pacman": ["git", "make", "gcc", "unzip", "tar"],
        "zypper": ["git", "make", "gcc", "gcc-c++", "unzip", "tar"],
        "apk": ["git", "make", "gcc", "g++", "musl-dev", "unzip", "tar"],
        "brew": ["git", "make", "gcc", "unzip"],
        "conda": ["git", "make", "compilers", "unzip"],
        "mamba": ["git", "make", "compilers", "unzip"],
    },
}


def _package_names_for(component: str, manager: str | None) -> list[str]:
    if manager is None:
        return []
    return list(_SYSTEM_PACKAGE_NAMES.get(component, {}).get(manager, []))


def _platform_install_command(
    profile: PlatformInstallProfile,
    packages: list[str],
    *,
    allow_sudo: bool,
) -> tuple[list[str], list[str] | None, str] | None:
    """Return update/install commands plus a human-readable install mode."""

    if not packages or not profile.package_manager_path or not profile.package_manager:
        return None

    manager = profile.package_manager
    executable = profile.package_manager_path
    prefix: list[str] = []
    mode = "direct"
    if manager not in {"brew", "conda", "mamba"} and not profile.is_root:
        if allow_sudo and profile.sudo_path:
            prefix = [profile.sudo_path]
            mode = "sudo"
        elif profile.passwordless_sudo and profile.sudo_path:
            prefix = [profile.sudo_path, "-n"]
            mode = "passwordless sudo"
        else:
            return None

    update_cmd: list[str] | None = None
    if manager == "apt":
        update_cmd = prefix + [executable, "update"]
        install_cmd = prefix + [executable, "install", "-y", *packages]
    elif manager in {"dnf", "yum"}:
        install_cmd = prefix + [executable, "install", "-y", *packages]
    elif manager == "pacman":
        install_cmd = prefix + [executable, "-S", "--noconfirm", *packages]
    elif manager == "zypper":
        install_cmd = prefix + [executable, "install", "-y", *packages]
    elif manager == "apk":
        install_cmd = prefix + [executable, "add", "--no-cache", *packages]
    elif manager == "brew":
        install_cmd = [executable, "install", *packages]
        mode = "homebrew"
    elif manager in {"conda", "mamba"}:
        install_cmd = [executable, "install", "-y", "-c", "conda-forge", *packages]
        mode = manager
    else:
        return None
    return install_cmd, update_cmd, mode


def _install_system_packages(
    packages: list[str],
    *,
    reason: str,
    allow_sudo: bool,
    strict: bool,
) -> bool:
    """Install system packages using the detected package manager."""

    profile = detect_platform_install_profile()
    command_plan = _platform_install_command(
        profile,
        packages,
        allow_sudo=allow_sudo,
    )
    if command_plan is None:
        manager = profile.package_manager or "no supported package manager"
        print(
            f"Cannot auto-install {reason} packages on {profile.system}/{profile.architecture} "
            f"with {manager}. Install manually: {' '.join(packages)}"
        )
        return False

    install_cmd, update_cmd, mode = command_plan
    try:
        print(
            f"Attempting platform install for {reason} via "
            f"{profile.package_manager} ({mode}): {' '.join(packages)}"
        )
        if update_cmd is not None:
            _run(update_cmd, check=False)
        return _run(install_cmd, check=strict) == 0
    except Exception as exc:
        print(f"Failed platform install for {reason}: {exc}")
        if strict:
            raise
        return False


def _ensure_opam_binary(
    *,
    allow_sudo: bool,
    strict: bool,
    on_progress: ProgressCallback | None,
) -> str | None:
    """Resolve OPAM, installing only when the caller explicitly permits it.

    OPAM is a bootstrap dependency for the user-local Rocq and ProVerif
    toolchains.  It is intentionally not installed during package import or a
    normal proof run.  A caller using ``--allow-sudo`` receives stage messages
    for the package-manager work rather than an apparent hang.
    """

    existing = _which("opam")
    if existing is not None:
        return existing

    profile = detect_platform_install_profile()
    packages = _package_names_for("opam", profile.package_manager)
    if not packages:
        _announce(
            "OPAM is required for the user-local Rocq/ProVerif bootstrap and no "
            "supported package-manager recipe is available. Install OPAM or set a "
            "solver-specific custom installer command.",
            on_progress,
            phase="blocked",
        )
        return None
    if not allow_sudo and not profile.is_root and profile.package_manager not in {"brew", "conda", "mamba"}:
        _announce(
            "OPAM is missing. Re-run with --allow-sudo to permit a platform OPAM "
            "install, or install OPAM manually before retrying.",
            on_progress,
            phase="blocked",
        )
        return None
    if _install_system_packages(
        packages,
        reason="OPAM bootstrap",
        allow_sudo=allow_sudo,
        strict=strict,
    ):
        installed = _which("opam")
        if installed is not None:
            _announce(f"Installed OPAM bootstrap dependency at {installed}.", on_progress, phase="installed")
            return installed
    _announce("OPAM installation did not produce an executable.", on_progress, phase="failed")
    return None


def _logic_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ergoai_submodule_path() -> Path:
    return _logic_root() / "ErgoAI"


def _ergoai_release_install_root() -> Path:
    env_path = os.environ.get("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".local" / "share" / "ipfs_datasets_py" / "provers" / "ergoai"


def _ergoai_release_binary_candidates() -> list[Path]:
    root = _ergoai_release_install_root()
    candidates = [root / "Coherent" / "ERGOAI_3.0" / "ErgoAI" / "runergo"]
    try:
        candidates.extend(sorted(root.glob("Coherent/ERGOAI_*/ErgoAI/runergo")))
    except OSError:
        pass
    return candidates


def _ergoai_binary_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("ERGOAI_BINARY")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.extend(_ergoai_release_binary_candidates())

    submodule = _ergoai_submodule_path()
    candidates.extend(
        [
            submodule / "ErgoAI" / "runErgo.sh",
            submodule / "ErgoAI" / "runergo",
            submodule / "runErgo.sh",
            submodule / "runergo",
            submodule / "ergo",
            submodule / "ergoai",
        ]
    )
    for name in ("runErgo.sh", "runergo"):
        found = _which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def _ergoai_runner_requires_paths_file(path: Path) -> bool:
    return path.name.lower() in {"runergo", "runergo.sh"}


def _is_configured_ergoai_binary(path: Path) -> bool:
    if not path.is_file():
        return False
    if _ergoai_runner_requires_paths_file(path):
        return (path.parent / ".ergo_paths").is_file()
    return True


def _find_ergoai_binary() -> Path | None:
    for candidate in _ergoai_binary_candidates():
        try:
            if _is_configured_ergoai_binary(candidate):
                return candidate
        except OSError:
            continue
    return None


def _make_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o755)
    except OSError:
        pass


def _run_custom_ergoai_installer(*, strict: bool) -> bool:
    command = str(os.environ.get("IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND") or "").strip()
    if not command:
        return False
    try:
        print("Attempting ErgoAI install via IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND...")
        rc = _run(shell_split(command), check=strict)
        return rc == 0 and _find_ergoai_binary() is not None
    except Exception as exc:
        print(f"Custom ErgoAI install command failed: {exc}")
        if strict:
            raise
        return False


def _download_file(url: str, destination: Path, *, strict: bool) -> bool:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            return True
        print(f"Downloading ErgoAI release installer from {url}...")
        urllib.request.urlretrieve(url, destination)
        _make_executable(destination)
        return True
    except Exception as exc:
        print(f"Failed to download ErgoAI release installer: {exc}")
        if strict:
            raise
        return False


def _install_ergoai_release(*, strict: bool) -> bool:
    """Install the official user-local ErgoAI release when supported."""

    if os.environ.get("IPFS_DATASETS_PY_ERGOAI_INSTALL_RELEASE") == "0":
        return False
    if platform.system().lower() not in {"linux", "darwin"}:
        return False

    shell = _which("sh") or "/bin/sh"
    if not Path(shell).exists():
        print("Cannot run the ErgoAI release installer because sh was not found.")
        return False

    root = _ergoai_release_install_root()
    existing_target = root / "Coherent"
    if existing_target.exists() and _find_ergoai_binary() is None:
        print(
            f"ErgoAI release install directory exists but is not configured: {existing_target}\n"
            "Set IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR to a fresh directory, "
            "or set ERGOAI_BINARY to an existing runergo."
        )
        return False

    release_url = str(
        os.environ.get("IPFS_DATASETS_PY_ERGOAI_RELEASE_URL")
        or DEFAULT_ERGOAI_RELEASE_URL
    ).strip()
    installer_name = release_url.rstrip("/").rsplit("/", 1)[-1] or "ergoAI.run"
    installer = root / installer_name
    if not _download_file(release_url, installer, strict=strict):
        return False

    try:
        print(f"Installing ErgoAI release into {root}...")
        rc = _run(
            [shell, str(installer), "--", "noninteractive"],
            check=strict,
            env=os.environ.copy(),
            cwd=root,
        )
        if rc != 0:
            return False
        binary = _find_ergoai_binary()
        if binary is not None:
            _make_executable(binary)
            os.environ["ERGOAI_BINARY"] = str(binary)
            print(f"ErgoAI binary available: {binary}")
            return True
    except Exception as exc:
        print(f"Failed to install ErgoAI release: {exc}")
        if strict:
            raise
    return False


def _clone_or_update_ergoai(*, strict: bool) -> bool:
    git = _which("git")
    if not git:
        print("Cannot hydrate ErgoAI automatically because git is not installed.")
        return False

    destination = _ergoai_submodule_path()
    repo_url = str(
        os.environ.get("IPFS_DATASETS_PY_ERGOAI_GIT_URL") or DEFAULT_ERGOAI_GIT_URL
    ).strip()

    try:
        if (destination / ".git").exists():
            print(f"Updating existing ErgoAI checkout at {destination}...")
            _run([git, "-C", str(destination), "pull", "--ff-only"], check=False)
        else:
            non_placeholder_entries = [
                path
                for path in destination.iterdir()
                if path.name != ".gitkeep"
            ] if destination.exists() else []
            if non_placeholder_entries:
                print(
                    f"ErgoAI path exists but is not a git checkout: {destination}\n"
                    "Set ERGOAI_BINARY or IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND "
                    "to point at an existing ErgoAI installation."
                )
                return False
            destination.parent.mkdir(parents=True, exist_ok=True)
            placeholder = destination / ".gitkeep"
            if placeholder.exists():
                placeholder.unlink()
            if destination.exists():
                try:
                    destination.rmdir()
                except OSError:
                    pass
            print(f"Cloning ErgoAI/ErgoEngine into {destination}...")
            _run([git, "clone", "--depth", "1", repo_url, str(destination)], check=strict)

        binary = _find_ergoai_binary()
        if binary is not None:
            _make_executable(binary)
            os.environ["ERGOAI_BINARY"] = str(binary)
            print(f"ErgoAI binary available: {binary}")
            return True

        print(
            "ErgoAI source was hydrated, but no configured runergo/ergo binary "
            "was found. Build ErgoEngine if required, or set ERGOAI_BINARY."
        )
        return False
    except Exception as exc:
        print(f"Failed to hydrate ErgoAI/ErgoEngine: {exc}")
        if strict:
            raise
        return False


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except (Exception, SystemExit):
        return False


def _pip_install(requirement: str, *, strict: bool, upgrade: bool = False) -> bool:
    base = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        base.append("--upgrade")
    extra_args = shell_split(os.environ.get("IPFS_DATASETS_PY_PIP_INSTALL_ARGS", ""))
    commands = [base + extra_args + [requirement]]
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if not in_venv:
        commands.append(base + extra_args + ["--user", requirement])
    if _truthy(os.environ.get("IPFS_DATASETS_PY_ALLOW_BREAK_SYSTEM_PACKAGES")):
        commands.append(base + extra_args + ["--break-system-packages", requirement])

    errors: list[str] = []
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except Exception as exc:
            errors.append(f"{' '.join(cmd)}: {exc}")
            continue
        if proc.returncode == 0:
            return True
        stderr = (proc.stderr or proc.stdout or "").strip()
        errors.append(f"{' '.join(cmd)} -> {proc.returncode}: {stderr}")

    message = (
        f"Could not install Python dependency: {requirement}\n"
        + "\n".join(errors[-2:])
        + "\nUse a virtualenv, set IPFS_DATASETS_PY_PIP_INSTALL_ARGS, or set "
        "IPFS_DATASETS_PY_ALLOW_BREAK_SYSTEM_PACKAGES=1 if you accept that risk."
    )
    if strict:
        raise RuntimeError(message)
    print(message)
    return False


def ensure_z3(
    *, yes: bool, strict: bool, force: bool = False, on_progress: ProgressCallback | None = None
) -> bool:
    """Attempt to ensure the Python Z3 bindings used by Z3ProverBridge exist."""
    if _module_available("z3") and not force:
        return True

    if not yes:
        _announce("Z3 Python bindings are missing; rerun with --yes to install z3-solver.", on_progress, phase="blocked")
        return False

    try:
        _announce("Installing z3-solver Python bindings with pip; this can take several minutes.", on_progress)
        pip_kwargs = {"strict": strict}
        if force:
            pip_kwargs["upgrade"] = True
        if _pip_install("z3-solver>=4.12.0,<5.0.0", **pip_kwargs) and _module_available("z3"):
            _announce(
                "Updated z3-solver Python bindings." if force else "Installed z3-solver Python bindings.",
                on_progress,
                phase="installed",
            )
            return True
        _announce("Unable to install Z3 automatically. Install with: pip install z3-solver", on_progress, phase="failed")
        return False
    except Exception as exc:
        _announce(f"Failed to install Z3: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_cvc5(
    *, yes: bool, strict: bool, force: bool = False, on_progress: ProgressCallback | None = None
) -> bool:
    """Attempt to ensure the Python CVC5 bindings used by CVC5ProverBridge exist."""
    if _module_available("cvc5") and not force:
        return True

    if not yes:
        _announce("CVC5 Python bindings are missing; rerun with --yes to install cvc5.", on_progress, phase="blocked")
        return False

    try:
        _announce("Installing CVC5 Python bindings with pip; this can take several minutes.", on_progress)
        pip_kwargs = {"strict": strict}
        if force:
            pip_kwargs["upgrade"] = True
        if _pip_install("cvc5>=1.0.0,<2.0.0", **pip_kwargs) and _module_available("cvc5"):
            _announce(
                "Updated cvc5 Python bindings." if force else "Installed cvc5 Python bindings.",
                on_progress,
                phase="installed",
            )
            return True
        _announce("Unable to install CVC5 automatically. Install with: pip install cvc5", on_progress, phase="failed")
        return False
    except Exception as exc:
        _announce(f"Failed to install CVC5: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_symbolicai(
    *, yes: bool, strict: bool, force: bool = False, on_progress: ProgressCallback | None = None
) -> bool:
    """Attempt to ensure SymbolicAI imports safely with project config defaults."""
    try:
        from ipfs_datasets_py.utils.symai_config import ensure_symai_config_for_import

        ensure_symai_config_for_import()
        if _module_available("symai") and not force:
            return True
    except Exception:
        pass

    if not yes:
        _announce("SymbolicAI is missing; rerun with --yes to install symbolicai.", on_progress, phase="blocked")
        return False

    try:
        _announce("Installing SymbolicAI with pip; this can take several minutes.", on_progress)
        pip_kwargs = {"strict": strict}
        if force:
            pip_kwargs["upgrade"] = True
        if _pip_install("symbolicai>=1.14.0,<2.0.0", **pip_kwargs):
            from ipfs_datasets_py.utils.symai_config import ensure_symai_config_for_import

            ensure_symai_config_for_import(force=True)
            if _module_available("symai"):
                _announce(
                    "Updated SymbolicAI." if force else "Installed SymbolicAI.",
                    on_progress,
                    phase="installed",
                )
                return True
        _announce("Unable to install SymbolicAI automatically. Install with: pip install symbolicai", on_progress, phase="failed")
        return False
    except Exception as exc:
        _announce(f"Failed to install SymbolicAI: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_ergoai(
    *, yes: bool, strict: bool, force: bool = False, on_progress: ProgressCallback | None = None
) -> bool:
    """Attempt to ensure the ErgoAI/ErgoEngine executable is available.

    Strategy:
    - Respect ``ERGOAI_BINARY`` or an existing ``ergo``/``ergoai``/``runErgo.sh``.
    - Run ``IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND`` when configured.
    - Install the official user-local ErgoAI release on Linux/macOS when enabled.
    - Hydrate the vendored ``ipfs_datasets_py/logic/ErgoAI`` checkout from
      ErgoAI/ErgoEngine as a best-effort source install.

    ErgoAI may still require host-specific build/runtime dependencies.  In
    that case this function leaves a clear message and the wrapper can continue
    in simulation mode unless strict mode is enabled.
    """

    binary = _find_ergoai_binary()
    if binary is not None and not force:
        _make_executable(binary)
        os.environ["ERGOAI_BINARY"] = str(binary)
        _write_ergoai_launchers(Path(binary))
        _announce(f"ErgoAI is already available at {binary}", on_progress, phase="available")
        return True

    if not yes:
        _announce(
            "ErgoAI binary not found. Re-run with --yes to hydrate ErgoEngine, "
            "or set ERGOAI_BINARY.",
            on_progress,
            phase="blocked",
        )
        return False

    _announce("Preparing user-local ErgoAI installation; this can take several minutes.", on_progress)
    if _run_custom_ergoai_installer(strict=strict):
        binary = _find_ergoai_binary()
        if binary is not None:
            _make_executable(binary)
            os.environ["ERGOAI_BINARY"] = str(binary)
            _write_ergoai_launchers(Path(binary))
            _announce(f"Installed ErgoAI at {binary}", on_progress, phase="installed")
            return True

    if force:
        _announce(
            "ErgoAI update requested. Refreshing the configured source checkout; "
            "set IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND to select a reviewed release.",
            on_progress,
        )
        if _clone_or_update_ergoai(strict=strict):
            _announce("Updated the configured ErgoAI source checkout.", on_progress, phase="installed")
            return True

    profile = detect_platform_install_profile()
    build_packages = _package_names_for("ergoai_build", profile.package_manager)
    if build_packages:
        _install_system_packages(
            build_packages,
            reason="ErgoAI/ErgoEngine build",
            allow_sudo=_truthy(os.environ.get("IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS")),
            strict=strict,
        )

    if _install_ergoai_release(strict=strict):
        binary = _find_ergoai_binary()
        if binary is not None:
            os.environ["ERGOAI_BINARY"] = str(binary)
            _write_ergoai_launchers(Path(binary))
        _announce("Installed the configured ErgoAI release.", on_progress, phase="installed")
        return True

    if _clone_or_update_ergoai(strict=strict):
        binary = _find_ergoai_binary()
        if binary is not None:
            os.environ["ERGOAI_BINARY"] = str(binary)
            _write_ergoai_launchers(Path(binary))
        _announce("Installed ErgoAI from the configured source checkout.", on_progress, phase="installed")
        return True

    _announce(
        "Unable to install ErgoAI automatically. Install ErgoEngine manually and set:\n"
        "  export ERGOAI_BINARY=/path/to/ErgoAI/runergo\n"
        "or configure IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND for your platform.",
        on_progress,
        phase="failed",
    )
    if strict:
        raise RuntimeError("ErgoAI binary unavailable after install attempt")
    return False


def ensure_lean(
    *,
    yes: bool,
    strict: bool,
    on_progress: ProgressCallback | None = None,
    force: bool = False,
) -> bool:
    """Attempt to ensure `lean` exists.

    Strategy:
    - If `lean` already on PATH: success
    - Else install elan (in user home) via official installer script
    - Then verify `~/.elan/bin/lean` exists
    """

    if _which("lean") and not force:
        return True

    if not yes:
        _announce("Lean is missing; rerun with --yes to attempt a user-local elan install.", on_progress, phase="blocked")
        return False

    try:
        elan = _which("elan")
        if force and elan is not None:
            toolchain = os.environ.get("IPFS_DATASETS_PY_LEAN_TOOLCHAIN", LEAN_TOOLCHAIN)
            _announce("Updating elan and the reviewed Lean toolchain on operator request.", on_progress)
            _run([elan, "self", "update"], check=False)
            if _run([elan, "toolchain", "install", toolchain], check=False) != 0:
                raise RuntimeError(f"elan could not install Lean toolchain {toolchain}")
            if _run([elan, "default", toolchain], check=False) != 0:
                raise RuntimeError(f"elan could not select Lean toolchain {toolchain}")
            lean_path = _which("lean")
            if lean_path:
                _announce(f"Updated Lean through elan: {lean_path}", on_progress, phase="installed")
                return True
        _announce("Downloading the official elan bootstrapper for Lean.", on_progress)
        # Download elan installer script ourselves (avoids requiring curl).
        url = "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh"
        with urllib.request.urlopen(url, timeout=30) as resp:
            script = resp.read()

        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "elan-init.sh"
            script_path.write_bytes(script)
            script_path.chmod(0o755)

            _announce("Installing Lean through elan; this can take several minutes.", on_progress)
            # `-y` accepts defaults and avoids prompts.
            _run(["sh", str(script_path), "-y"], check=strict)

        lean_path = _which("lean")
        lean_home = Path.home() / ".elan" / "bin" / "lean"
        if lean_path or lean_home.exists():
            _announce(f"Installed Lean via elan: {lean_path or lean_home}", on_progress, phase="installed")
            print("If Lean is not on PATH, add ~/.elan/bin to PATH.")
            return True

        _announce("Attempted to install Lean via elan, but no lean binary was found afterwards.", on_progress, phase="failed")
        return False

    except Exception as exc:
        _announce(f"Failed to install Lean via elan: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def _coq_opam_root() -> Path:
    configured = os.environ.get("IPFS_DATASETS_PY_COQ_OPAM_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _external_prover_root() / "opam"


def _proverif_opam_root() -> Path:
    configured = os.environ.get("IPFS_DATASETS_PY_PROVERIF_OPAM_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _external_prover_root() / "opam"


def _install_coq_via_opam(
    *,
    strict: bool,
    on_progress: ProgressCallback | None = None,
    force: bool = False,
    allow_sudo: bool = False,
) -> bool:
    """Install Coq into an isolated OPAM root without modifying global switches."""

    opam = _ensure_opam_binary(
        allow_sudo=allow_sudo,
        strict=strict,
        on_progress=on_progress,
    )
    if opam is None:
        return False

    root = _coq_opam_root()
    switch = os.environ.get("IPFS_DATASETS_PY_COQ_OPAM_SWITCH", "ipfs-datasets-coq")
    compiler = os.environ.get(
        "IPFS_DATASETS_PY_COQ_OPAM_COMPILER", "ocaml-base-compiler.4.14.2"
    )
    switch_bin = root / switch / "bin"
    coqc = switch_bin / "coqc"
    coqtop = switch_bin / "coqtop"
    if coqc.is_file() and not force:
        _write_launcher(
            "coqc",
            coqc,
            environment={"OPAMROOT": str(root), "OPAMSWITCH": switch},
        )
        if coqtop.is_file():
            _write_launcher(
                "coqtop",
                coqtop,
                environment={"OPAMROOT": str(root), "OPAMSWITCH": switch},
            )
        _announce(f"Coq is already available in user-local OPAM switch {switch}.", on_progress, phase="available")
        return _version_matches(_which("coqc"), ROCQ_VERSION)

    root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OPAMROOT"] = str(root)
    env["OPAMYES"] = "true"
    try:
        _announce(f"Initializing isolated OPAM root for Coq at {root}.", on_progress)
        if _run(
            [opam, "init", "--bare", "--disable-sandboxing", "--no-setup", "--yes"],
            check=False,
            env=env,
        ) != 0:
            raise RuntimeError("OPAM initialization failed")
        if not (root / switch).is_dir():
            _announce(
                f"Creating OPAM switch {switch} with {compiler}; this can take several minutes.",
                on_progress,
            )
            if _run(
                [opam, "switch", "create", switch, compiler, "--yes"],
                check=False,
                env=env,
            ) != 0:
                raise RuntimeError("OPAM switch creation failed")
        _announce("Refreshing the Rocq package index for the isolated OPAM switch.", on_progress)
        _run(
            [opam, "repo", "add", "rocq-released", ROCQ_OPAM_REPOSITORY, "--switch", switch, "--yes"],
            check=False,
            env=env,
        )
        if _run([opam, "update", "--switch", switch], check=False, env=env) != 0:
            raise RuntimeError("OPAM package index update failed")
        _announce(
            f"Installing Rocq {ROCQ_VERSION} in the isolated OPAM switch; this can take several minutes.",
            on_progress,
        )
        if _run(
            [opam, "install", "rocq-prover", f"rocq-core={ROCQ_VERSION}", "--switch", switch, "--yes"],
            check=False,
            env=env,
        ) != 0:
            raise RuntimeError("OPAM Rocq installation failed")
        if not coqc.is_file():
            raise RuntimeError("OPAM completed without a coqc binary")
        _write_launcher(
            "coqc",
            coqc,
            environment={"OPAMROOT": str(root), "OPAMSWITCH": switch},
        )
        if coqtop.is_file():
            _write_launcher(
                "coqtop",
                coqtop,
                environment={"OPAMROOT": str(root), "OPAMSWITCH": switch},
            )
        _announce(f"Installed Rocq {ROCQ_VERSION} in user-local OPAM switch {switch}.", on_progress, phase="installed")
        if not _version_matches(_which("coqc"), ROCQ_VERSION):
            raise RuntimeError(f"OPAM installed Rocq but coqc does not report {ROCQ_VERSION}")
        return True
    except Exception as exc:
        _announce(f"User-local OPAM Coq installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_coq(
    *,
    yes: bool,
    strict: bool,
    allow_sudo: bool = False,
    on_progress: ProgressCallback | None = None,
    force: bool = False,
) -> bool:
    """Attempt to ensure `coqc` exists.

    Strategy:
    - If `coqc` already on PATH: success
    - Detect the platform package manager and install the right Coq package
      through apt/dnf/yum/pacman/zypper/apk/Homebrew/conda when possible.
    - Run a configured custom installer when supplied.
    - Use an isolated user-local OPAM switch as the final fallback. This can
      take several minutes, so every stage emits progress.
    """

    if _which("coqc") and not force:
        return True

    if not yes:
        print("Coq not found. Re-run with --yes to attempt a best-effort install.")
        return False

    try:
        if _run_custom_solver_installer("coq", strict=strict, on_progress=on_progress):
            return _which("coqc") is not None
        # The package-manager Coq release is often older than the reviewed
        # Rocq target. Prefer the isolated OPAM switch so a clean machine gets
        # the same 9.1.1 kernel used by the verification lanes.
        if _install_coq_via_opam(
            strict=strict,
            on_progress=on_progress,
            force=force,
            allow_sudo=allow_sudo,
        ):
            return True

        profile = detect_platform_install_profile()
        coq_packages = _package_names_for("coq", profile.package_manager)
        if coq_packages and not force:
            if _install_system_packages(
                coq_packages,
                reason="Coq fallback (version must be checked before accepting proof evidence)",
                allow_sudo=allow_sudo,
                strict=strict,
            ) and _which("coqc"):
                _announce(
                    f"Installed fallback Coq via {profile.package_manager}; run --check-updates "
                    "before accepting it as the managed Rocq kernel.",
                    on_progress,
                    phase="installed",
                )
                return True
        return False

    except Exception as exc:
        print(f"Failed to install Coq: {exc}")
        if strict:
            raise
        return False


def _proverif_build_environment(
    *,
    allow_sudo: bool,
    strict: bool,
    on_progress: ProgressCallback | None,
    force: bool,
) -> dict[str, str] | None:
    """Return an OCaml build environment for the pinned headless ProVerif.

    A global OCaml toolchain is reused when complete.  Otherwise the installer
    creates an isolated OPAM switch under the solver root.  This gives the
    source build a deterministic compiler without changing the user's default
    OPAM switch or requiring the GTK interface.
    """

    required_tools = ("ocamlopt", "ocamlyacc", "ocamllex")
    if all(_which(tool) is not None for tool in required_tools) and not force:
        return os.environ.copy()

    opam = _ensure_opam_binary(
        allow_sudo=allow_sudo,
        strict=strict,
        on_progress=on_progress,
    )
    if opam is None:
        _announce(
            "ProVerif requires OCaml. Install OPAM, re-run with --allow-sudo, or "
            "set IPFS_DATASETS_PY_PROVERIF_INSTALL_COMMAND.",
            on_progress,
            phase="blocked",
        )
        return None

    root = _proverif_opam_root()
    switch = os.environ.get("IPFS_DATASETS_PY_PROVERIF_OPAM_SWITCH", "ipfs-datasets-proverif")
    compiler = os.environ.get(
        "IPFS_DATASETS_PY_PROVERIF_OPAM_COMPILER", "ocaml-base-compiler.4.14.2"
    )
    switch_bin = root / switch / "bin"
    env = os.environ.copy()
    env.update({"OPAMROOT": str(root), "OPAMSWITCH": switch, "OPAMYES": "true"})
    try:
        root.mkdir(parents=True, exist_ok=True)
        _announce(f"Initializing isolated OPAM root for ProVerif at {root}.", on_progress)
        if _run(
            [opam, "init", "--bare", "--disable-sandboxing", "--no-setup", "--yes"],
            check=False,
            env=env,
        ) != 0:
            raise RuntimeError("OPAM initialization failed")
        if force or not switch_bin.is_dir():
            _announce(
                f"Creating or refreshing OPAM switch {switch} with {compiler}; this can take several minutes.",
                on_progress,
            )
            if not switch_bin.is_dir() and _run(
                [opam, "switch", "create", switch, compiler, "--yes"],
                check=False,
                env=env,
            ) != 0:
                raise RuntimeError("OPAM switch creation failed")
        _announce("Refreshing the OPAM package index for the ProVerif toolchain.", on_progress)
        if _run([opam, "update", "--switch", switch], check=False, env=env) != 0:
            raise RuntimeError("OPAM package index update failed")
        build_env = env.copy()
        build_env["PATH"] = str(switch_bin) + os.pathsep + env.get("PATH", "")
        missing = [tool for tool in required_tools if not (switch_bin / tool).is_file()]
        if missing:
            raise RuntimeError("OPAM switch is missing OCaml tools: " + ", ".join(missing))
        return build_env
    except Exception as exc:
        _announce(f"Unable to prepare the isolated ProVerif OCaml toolchain: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return None


def ensure_apalache(
    *, yes: bool, strict: bool, on_progress: ProgressCallback | None = None, force: bool = False
) -> bool:
    """Ensure the pinned Apalache binary is available in a user-local root."""

    existing = _which("apalache-mc") or _which("apalache")
    if existing and not force:
        _announce(f"Apalache is already available at {existing}", on_progress, phase="available")
        return True
    if not yes:
        _announce("Apalache is missing; rerun with --yes to install it user-locally.", on_progress, phase="blocked")
        return False
    if _run_custom_solver_installer("apalache", strict=strict, on_progress=on_progress):
        return _which("apalache-mc") is not None or _which("apalache") is not None
    if not _linux_x86_64():
        _announce(
            "Apalache automatic artifact installation currently supports Linux x86_64. "
            "Set IPFS_DATASETS_PY_APALACHE_INSTALL_COMMAND for this platform.",
            on_progress,
            phase="blocked",
        )
        return False
    if _which("java") is None:
        _announce(
            "Apalache requires a Java runtime. Install Java or set JAVA_HOME before retrying.",
            on_progress,
            phase="blocked",
        )
        return False

    root = _external_prover_root()
    archive = root / "downloads" / f"apalache-{APALACHE_VERSION}.tgz"
    destination = root / f"apalache-{APALACHE_VERSION}"
    try:
        if not _download_release_artifact(
            APALACHE_LINUX_X86_64_URL,
            archive,
            APALACHE_LINUX_X86_64_SHA256,
            strict=strict,
            on_progress=on_progress,
        ):
            return False
        _announce(f"Extracting Apalache {APALACHE_VERSION} into {destination}", on_progress)
        _safe_extract_tar(archive, destination)
        candidates = [path for path in destination.rglob("apalache-mc") if path.is_file()]
        if len(candidates) != 1:
            raise RuntimeError("Apalache archive did not contain exactly one apalache-mc executable")
        _write_launcher("apalache-mc", candidates[0])
        _announce(f"Installed Apalache {APALACHE_VERSION} user-locally.", on_progress, phase="installed")
        return _which("apalache-mc") is not None
    except Exception as exc:
        _announce(f"Apalache installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_maude(
    *, yes: bool, strict: bool, on_progress: ProgressCallback | None = None, force: bool = False
) -> bool:
    """Ensure the Maude runtime accepted by the pinned Tamarin release is present."""

    existing = _which("maude")
    if existing and not force:
        _announce(f"Maude is already available at {existing}", on_progress, phase="available")
        return True
    if not yes:
        _announce("Maude is missing; rerun with --yes to install it user-locally.", on_progress, phase="blocked")
        return False
    if _run_custom_solver_installer("maude", strict=strict, on_progress=on_progress):
        return _which("maude") is not None
    if not _linux_x86_64():
        _announce(
            "Maude automatic artifact installation currently supports Linux x86_64. "
            "Set IPFS_DATASETS_PY_MAUDE_INSTALL_COMMAND for this platform.",
            on_progress,
            phase="blocked",
        )
        return False

    root = _external_prover_root()
    archive = root / "downloads" / f"Maude-{MAUDE_VERSION}-linux-x86_64.zip"
    destination = root / f"maude-{MAUDE_VERSION}"
    try:
        if not _download_release_artifact(
            MAUDE_LINUX_X86_64_URL,
            archive,
            MAUDE_LINUX_X86_64_SHA256,
            strict=strict,
            on_progress=on_progress,
        ):
            return False
        _announce(f"Extracting Maude {MAUDE_VERSION} into {destination}", on_progress)
        _safe_extract_zip(archive, destination)
        executable = destination / "maude"
        if not executable.is_file():
            raise RuntimeError(f"Maude archive did not contain {executable}")
        _write_launcher("maude", executable, environment={"MAUDE_LIB": str(destination)})
        _announce(f"Installed Maude {MAUDE_VERSION} user-locally.", on_progress, phase="installed")
        return _which("maude") is not None
    except Exception as exc:
        _announce(f"Maude installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def _tamarin_accepts_maude(tamarin: str | None, maude: str | None) -> bool:
    """Check the Tamarin binary against the selected Maude runtime.

    Tamarin can be present while pointing at an incompatible Maude binary.
    A filename check is not enough for protocol evidence, so installation
    finishes with Tamarin's own runtime validation marker.
    """

    if tamarin is None or maude is None:
        return False
    try:
        completed = subprocess.run(
            [tamarin, f"--with-maude={maude}", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = "\n".join(value for value in (completed.stdout, completed.stderr) if value)
    return bool(
        completed.returncode == 0
        and TAMARIN_VERSION in output
        and MAUDE_VERSION in output
        and "checking installation: OK" in output
    )


def ensure_tamarin(
    *, yes: bool, strict: bool, on_progress: ProgressCallback | None = None, force: bool = False
) -> bool:
    """Ensure Tamarin and its Maude runtime are installed as a paired lane."""

    existing = _which("tamarin-prover")
    if existing and not force:
        if not ensure_maude(yes=yes, strict=strict, on_progress=on_progress):
            return False
        maude = _which("maude")
        if _tamarin_accepts_maude(existing, maude):
            _announce(
                f"Tamarin {TAMARIN_VERSION} accepts Maude {MAUDE_VERSION} at {maude}.",
                on_progress,
                phase="available",
            )
            return True
        _announce(
            "Tamarin or Maude is present but the pinned pair did not pass Tamarin's "
            "own runtime validation. Re-run with --update --yes --tamarin to repair it.",
            on_progress,
            phase="failed",
        )
        return False
    if not yes:
        _announce("Tamarin is missing; rerun with --yes to install it user-locally.", on_progress, phase="blocked")
        return False
    if not ensure_maude(yes=yes, strict=strict, on_progress=on_progress, force=force):
        return False
    if _run_custom_solver_installer("tamarin", strict=strict, on_progress=on_progress):
        return _which("tamarin-prover") is not None
    if not _linux_x86_64():
        _announce(
            "Tamarin automatic artifact installation currently supports Linux x86_64. "
            "Set IPFS_DATASETS_PY_TAMARIN_INSTALL_COMMAND for this platform.",
            on_progress,
            phase="blocked",
        )
        return False

    root = _external_prover_root()
    archive = root / "downloads" / f"tamarin-prover-{TAMARIN_VERSION}-linux64-ubuntu.tar.gz"
    destination = root / f"tamarin-prover-{TAMARIN_VERSION}"
    try:
        if not _download_release_artifact(
            TAMARIN_LINUX_X86_64_URL,
            archive,
            TAMARIN_LINUX_X86_64_SHA256,
            strict=strict,
            on_progress=on_progress,
        ):
            return False
        _announce(f"Extracting Tamarin {TAMARIN_VERSION} into {destination}", on_progress)
        _safe_extract_tar(archive, destination)
        candidates = [path for path in destination.rglob("tamarin-prover") if path.is_file()]
        if len(candidates) != 1:
            raise RuntimeError("Tamarin archive did not contain exactly one tamarin-prover executable")
        _write_launcher("tamarin-prover", candidates[0])
        tamarin = _which("tamarin-prover")
        maude = _which("maude")
        if not _tamarin_accepts_maude(tamarin, maude):
            raise RuntimeError("Tamarin/Maude installation did not pass Tamarin runtime validation")
        _announce(f"Installed Tamarin {TAMARIN_VERSION} with Maude {MAUDE_VERSION}.", on_progress, phase="installed")
        return True
    except Exception as exc:
        _announce(f"Tamarin installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_proverif(
    *,
    yes: bool,
    strict: bool,
    on_progress: ProgressCallback | None = None,
    force: bool = False,
    allow_sudo: bool = False,
) -> bool:
    """Build the official ProVerif source in headless mode under the user-local root."""

    existing = _which("proverif")
    if existing and not force:
        _announce(f"ProVerif is already available at {existing}", on_progress, phase="available")
        return True
    if not yes:
        _announce("ProVerif is missing; rerun with --yes to build it user-locally.", on_progress, phase="blocked")
        return False
    if _run_custom_solver_installer("proverif", strict=strict, on_progress=on_progress):
        return _which("proverif") is not None

    build_env = _proverif_build_environment(
        allow_sudo=allow_sudo,
        strict=strict,
        on_progress=on_progress,
        force=force,
    )
    if build_env is None:
        return False

    root = _external_prover_root()
    archive = root / "downloads" / f"proverif{PROVERIF_VERSION}.tar.gz"
    source_root = root / f"proverif-{PROVERIF_VERSION}"
    try:
        if not _download_release_artifact(
            PROVERIF_SOURCE_URL,
            archive,
            PROVERIF_SOURCE_SHA256,
            strict=strict,
            on_progress=on_progress,
        ):
            return False
        _announce(f"Extracting ProVerif {PROVERIF_VERSION} source into {source_root}", on_progress)
        _safe_extract_tar(archive, source_root)
        candidates = [path for path in source_root.iterdir() if path.is_dir() and path.name.startswith("proverif")]
        source_dir = candidates[0] if len(candidates) == 1 else source_root
        _announce("Building ProVerif without its optional GTK interface; this can take several minutes.", on_progress)
        if _run(
            ["sh", "build", "-nointeract"],
            check=False,
            cwd=source_dir,
            env=build_env,
        ) != 0:
            raise RuntimeError("ProVerif headless build failed")
        executable = source_dir / "proverif"
        if not executable.is_file():
            raise RuntimeError("ProVerif build completed without a proverif executable")
        _write_launcher(
            "proverif",
            executable,
            environment={
                "OPAMROOT": build_env["OPAMROOT"],
                "OPAMSWITCH": build_env["OPAMSWITCH"],
            } if "OPAMROOT" in build_env and "OPAMSWITCH" in build_env else None,
        )
        _announce(f"Installed headless ProVerif {PROVERIF_VERSION} user-locally.", on_progress, phase="installed")
        if not _version_matches(_which("proverif"), PROVERIF_VERSION):
            raise RuntimeError(f"ProVerif launcher does not report {PROVERIF_VERSION}")
        return True
    except Exception as exc:
        _announce(f"ProVerif installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def ensure_cvc5_cli(
    *, yes: bool, strict: bool, on_progress: ProgressCallback | None = None, force: bool = False
) -> bool:
    """Ensure the CVC5 command-line binary required by SMT-LIB runners exists."""

    existing = _which("cvc5")
    if existing and not force:
        _announce(f"CVC5 CLI is already available at {existing}", on_progress, phase="available")
        return True
    if not yes:
        _announce("CVC5 CLI is missing; rerun with --yes or set IPFS_DATASETS_PY_CVC5_INSTALL_COMMAND.", on_progress, phase="blocked")
        return False
    if _run_custom_solver_installer("cvc5", strict=strict, on_progress=on_progress):
        return _which("cvc5") is not None
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64" if system == "linux" else "arm64"}.get(machine, machine)
    release = CVC5_RELEASES.get((system, machine))
    if release is None:
        _announce(
            "CVC5 automatic artifact installation does not support "
            f"{system}/{machine}. Set IPFS_DATASETS_PY_CVC5_INSTALL_COMMAND for this platform.",
            on_progress,
            phase="blocked",
        )
        return False

    url, sha256 = release
    root = _external_prover_root()
    archive = root / "downloads" / f"cvc5-{CVC5_VERSION}-{system}-{machine}.zip"
    destination = root / f"cvc5-{CVC5_VERSION}-{system}-{machine}"
    try:
        if not _download_release_artifact(
            url,
            archive,
            sha256,
            strict=strict,
            on_progress=on_progress,
        ):
            return False
        _announce(f"Extracting CVC5 {CVC5_VERSION} into {destination}", on_progress)
        _safe_extract_zip(archive, destination)
        candidates = [path for path in destination.rglob("cvc5") if path.is_file()]
        if len(candidates) != 1:
            raise RuntimeError("CVC5 archive did not contain exactly one cvc5 executable")
        _write_launcher("cvc5", candidates[0])
        _announce(f"Installed CVC5 CLI {CVC5_VERSION} user-locally.", on_progress, phase="installed")
        return _which("cvc5") is not None
    except Exception as exc:
        _announce(f"CVC5 CLI installation failed: {exc}", on_progress, phase="failed")
        if strict:
            raise
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Best-effort user-local installer for theorem provers and their Python bindings"
    )
    parser.add_argument("--z3", action="store_true", help="Install/ensure Z3 Python bindings")
    parser.add_argument("--cvc5", action="store_true", help="Install/ensure CVC5 Python bindings")
    parser.add_argument("--lean", action="store_true", help="Install/ensure Lean")
    parser.add_argument("--coq", "--rocq", action="store_true", help="Install/ensure Rocq 9.1.1 (Coq-compatible CLI)")
    parser.add_argument("--apalache", action="store_true", help="Install/ensure Apalache")
    parser.add_argument("--tamarin", action="store_true", help="Install/ensure Tamarin and Maude")
    parser.add_argument("--maude", action="store_true", help="Install/ensure the Maude runtime")
    parser.add_argument("--proverif", action="store_true", help="Install/ensure headless ProVerif")
    parser.add_argument("--cvc5-cli", action="store_true", help="Install/ensure the CVC5 command-line binary")
    parser.add_argument("--symbolicai", "--symai", action="store_true", help="Install/ensure SymbolicAI")
    parser.add_argument("--ergoai", "--ergo", action="store_true", help="Install/ensure ErgoAI/ErgoEngine")
    parser.add_argument(
        "--check-updates",
        action="store_true",
        help="Report managed solver versions and drift without downloading or changing anything.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Manually refresh selected solvers to their reviewed managed versions; requires --yes.",
    )
    parser.add_argument(
        "--allow-sudo",
        action="store_true",
        help="Allow interactive sudo for system packages such as Coq.",
    )
    parser.add_argument("--yes", action="store_true", help="Non-interactive / accept defaults")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail with non-zero exit if an enabled install step fails.",
    )

    args = parser.parse_args(argv)

    if args.check_updates:
        statuses = managed_solver_version_status()
        print(json.dumps({"managed_solvers": statuses}, indent=2, sort_keys=True))
        return 1 if args.strict and any(item["manual_update_required"] for item in statuses) else 0
    if args.update and not args.yes:
        parser.error("--update requires --yes because it can download, build, or replace user-local solvers")

    want_z3 = bool(args.z3)
    want_cvc5 = bool(args.cvc5)
    want_lean = bool(args.lean)
    want_coq = bool(args.coq)
    want_apalache = bool(args.apalache)
    want_tamarin = bool(args.tamarin)
    want_maude = bool(args.maude)
    want_proverif = bool(args.proverif)
    want_cvc5_cli = bool(args.cvc5_cli)
    want_symbolicai = bool(args.symbolicai)
    want_ergoai = bool(args.ergoai)
    if not (
        want_z3 or want_cvc5 or want_lean or want_coq or want_apalache
        or want_tamarin or want_maude or want_proverif or want_cvc5_cli
        or want_symbolicai or want_ergoai
    ):
        want_z3 = True
        want_cvc5 = True
        want_lean = True
        want_coq = True
        want_apalache = True
        want_tamarin = True
        want_proverif = True
        want_cvc5_cli = True
        want_symbolicai = True
        want_ergoai = True

    update_kwargs = {"force": True} if args.update else {}

    ok = True
    if want_z3:
        ok = ensure_z3(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_cvc5:
        ok = ensure_cvc5(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_lean:
        ok = ensure_lean(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_coq:
        ok = ensure_coq(
            yes=args.yes,
            strict=args.strict,
            allow_sudo=bool(args.allow_sudo),
            **update_kwargs,
        ) and ok
    if want_apalache:
        ok = ensure_apalache(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_maude:
        ok = ensure_maude(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_tamarin:
        ok = ensure_tamarin(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_proverif:
        ok = ensure_proverif(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_cvc5_cli:
        ok = ensure_cvc5_cli(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_symbolicai:
        ok = ensure_symbolicai(yes=args.yes, strict=args.strict, **update_kwargs) and ok
    if want_ergoai:
        ok = ensure_ergoai(yes=args.yes, strict=args.strict, **update_kwargs) and ok

    if ok:
        return 0

    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
