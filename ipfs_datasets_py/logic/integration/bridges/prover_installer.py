"""Best-effort installer for external theorem provers.

Important:
- Lean/Coq are *system tools*, not Python packages.
- Z3/CVC5/SymbolicAI are imported through Python packages by the prover bridges.
- Installing them automatically during `pip install` can be surprising and may fail
  depending on OS/package manager permissions.

This module provides an *opt-in* installer that can be invoked:
- Manually via console script: `ipfs-datasets-install-provers`
- Or from setup.py post-install hooks when explicitly enabled via env vars.

Environment variables (all optional):
- IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS: enable running installer post-install (default: 0)
- IPFS_DATASETS_PY_AUTO_INSTALL_Z3: enable Z3 install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_CVC5: enable CVC5 install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_LEAN: enable Lean install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_COQ: enable Coq install attempts (default: 0)
- IPFS_DATASETS_PY_AUTO_INSTALL_SYMBOLICAI: enable SymbolicAI install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_AUTO_INSTALL_ERGOAI: enable ErgoAI/ErgoEngine install attempts (default: 1 when AUTO_INSTALL_PROVERS=1)
- IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS: enable install attempts from requested prover bridges (default: 0)
- IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>: per-prover lazy install override (Z3/CVC5/LEAN/COQ/SYMBOLICAI/ERGOAI)
- IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS: allow lazy Coq install to use interactive sudo (default: 0)
- IPFS_DATASETS_PY_ERGOAI_GIT_URL: override ErgoAI/ErgoEngine source repository.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND: custom command used before git clone fallback.
- ERGOAI_BINARY: explicit path to the ErgoAI executable/runErgo.sh.

The installer is best-effort and never raises on failure unless `--strict` is used.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from shlex import split as shell_split

logger = logging.getLogger(__name__)
DEFAULT_ERGOAI_GIT_URL = "https://github.com/ErgoAI/ErgoEngine.git"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _run(cmd: list[str], *, check: bool, env: dict[str, str] | None = None) -> int:
    proc = subprocess.run(cmd, text=True, env=env)
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
        ]
    )
    return dirs


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


def _logic_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ergoai_submodule_path() -> Path:
    return _logic_root() / "ErgoAI"


def _ergoai_binary_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("ERGOAI_BINARY")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    submodule = _ergoai_submodule_path()
    candidates.extend(
        [
            submodule / "ErgoAI" / "runErgo.sh",
            submodule / "runErgo.sh",
            submodule / "ergo",
            submodule / "ergoai",
        ]
    )
    for name in ("ergo", "ergoai", "runErgo.sh"):
        found = _which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def _find_ergoai_binary() -> Path | None:
    for candidate in _ergoai_binary_candidates():
        try:
            if candidate.is_file():
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
            "ErgoAI source was hydrated, but no runErgo.sh/ergo binary was found. "
            "Build ErgoEngine if required, or set ERGOAI_BINARY."
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


def _pip_install(requirement: str, *, strict: bool) -> bool:
    base = [sys.executable, "-m", "pip", "install"]
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


def ensure_z3(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure the Python Z3 bindings used by Z3ProverBridge exist."""
    if _module_available("z3"):
        return True

    if not yes:
        print("Z3 Python bindings not found. Re-run with --yes to install z3-solver.")
        return False

    try:
        if _pip_install("z3-solver>=4.12.0,<5.0.0", strict=strict) and _module_available("z3"):
            print("Installed z3-solver Python bindings.")
            return True
        print("Unable to install Z3 automatically. Install with: pip install z3-solver")
        return False
    except Exception as exc:
        print(f"Failed to install Z3: {exc}")
        if strict:
            raise
        return False


def ensure_cvc5(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure the Python CVC5 bindings used by CVC5ProverBridge exist."""
    if _module_available("cvc5"):
        return True

    if not yes:
        print("CVC5 Python bindings not found. Re-run with --yes to install cvc5.")
        return False

    try:
        if _pip_install("cvc5>=1.0.0,<2.0.0", strict=strict) and _module_available("cvc5"):
            print("Installed cvc5 Python bindings.")
            return True
        print("Unable to install CVC5 automatically. Install with: pip install cvc5")
        return False
    except Exception as exc:
        print(f"Failed to install CVC5: {exc}")
        if strict:
            raise
        return False


def ensure_symbolicai(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure SymbolicAI imports safely with project config defaults."""
    try:
        from ipfs_datasets_py.utils.symai_config import ensure_symai_config_for_import

        ensure_symai_config_for_import()
        if _module_available("symai"):
            return True
    except Exception:
        pass

    if not yes:
        print("SymbolicAI not found or not importable. Re-run with --yes to install symbolicai.")
        return False

    try:
        if _pip_install("symbolicai>=1.14.0,<2.0.0", strict=strict):
            from ipfs_datasets_py.utils.symai_config import ensure_symai_config_for_import

            ensure_symai_config_for_import(force=True)
            if _module_available("symai"):
                print("Installed SymbolicAI.")
                return True
        print("Unable to install SymbolicAI automatically. Install with: pip install symbolicai")
        return False
    except Exception as exc:
        print(f"Failed to install SymbolicAI: {exc}")
        if strict:
            raise
        return False


def ensure_ergoai(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure the ErgoAI/ErgoEngine executable is available.

    Strategy:
    - Respect ``ERGOAI_BINARY`` or an existing ``ergo``/``ergoai``/``runErgo.sh``.
    - Run ``IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND`` when configured.
    - Hydrate the vendored ``ipfs_datasets_py/logic/ErgoAI`` checkout from
      ErgoAI/ErgoEngine as a best-effort source install.

    ErgoAI may still require host-specific build/runtime dependencies.  In
    that case this function leaves a clear message and the wrapper can continue
    in simulation mode unless strict mode is enabled.
    """

    binary = _find_ergoai_binary()
    if binary is not None:
        _make_executable(binary)
        os.environ["ERGOAI_BINARY"] = str(binary)
        return True

    if not yes:
        print(
            "ErgoAI binary not found. Re-run with --yes to hydrate ErgoEngine, "
            "or set ERGOAI_BINARY."
        )
        return False

    if _run_custom_ergoai_installer(strict=strict):
        binary = _find_ergoai_binary()
        if binary is not None:
            _make_executable(binary)
            os.environ["ERGOAI_BINARY"] = str(binary)
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

    if _clone_or_update_ergoai(strict=strict):
        return True

    print(
        "Unable to install ErgoAI automatically. Install ErgoEngine manually and set:\n"
        "  export ERGOAI_BINARY=/path/to/ErgoAI/runErgo.sh\n"
        "or configure IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND for your platform."
    )
    if strict:
        raise RuntimeError("ErgoAI binary unavailable after install attempt")
    return False


def ensure_lean(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure `lean` exists.

    Strategy:
    - If `lean` already on PATH: success
    - Else install elan (in user home) via official installer script
    - Then verify `~/.elan/bin/lean` exists
    """

    if _which("lean"):
        return True

    if not yes:
        print("Lean not found. Re-run with --yes to attempt install via elan.")
        return False

    try:
        # Download elan installer script ourselves (avoids requiring curl).
        url = "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh"
        with urllib.request.urlopen(url, timeout=30) as resp:
            script = resp.read()

        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "elan-init.sh"
            script_path.write_bytes(script)
            script_path.chmod(0o755)

            # `-y` accepts defaults and avoids prompts.
            _run(["sh", str(script_path), "-y"], check=strict)

        lean_path = _which("lean")
        lean_home = Path.home() / ".elan" / "bin" / "lean"
        if lean_path or lean_home.exists():
            print(f"Installed Lean via elan: {lean_path or lean_home}")
            print("If Lean is not on PATH, add ~/.elan/bin to PATH.")
            return True

        print("Attempted to install Lean via elan, but lean binary was not found afterwards.")
        return False

    except Exception as exc:
        print(f"Failed to install Lean via elan: {exc}")
        if strict:
            raise
        return False


def ensure_coq(*, yes: bool, strict: bool, allow_sudo: bool = False) -> bool:
    """Attempt to ensure `coqc` exists.

    Strategy:
    - If `coqc` already on PATH: success
    - Detect the platform package manager and install the right Coq package
      through apt/dnf/yum/pacman/zypper/apk/Homebrew/conda when possible.
    - If opam exists: print guidance (opam-based install can be long).

    We intentionally keep Coq auto-install conservative; building from source via
    opam can take significant time and requires a full OCaml toolchain.
    """

    if _which("coqc"):
        return True

    if not yes:
        print("Coq not found. Re-run with --yes to attempt a best-effort install.")
        return False

    try:
        profile = detect_platform_install_profile()
        coq_packages = _package_names_for("coq", profile.package_manager)
        if coq_packages:
            if _install_system_packages(
                coq_packages,
                reason="Coq",
                allow_sudo=allow_sudo,
                strict=strict,
            ) and _which("coqc"):
                print(f"Installed Coq via {profile.package_manager}.")
                return True

        if _which("opam"):
            print(
                "Coq not found. opam is available; you can install Coq via:\n"
                "  opam init -y\n"
                "  opam install -y coq\n"
            )
        else:
            print(
                "Coq not found. Please install via your OS package manager (preferred) or opam.\n"
                "Examples:\n"
                "  Ubuntu/Debian: sudo apt-get install -y coq\n"
                "  Fedora: sudo dnf install -y coq\n"
                "  Arch: sudo pacman -S coq\n"
                "  macOS: brew install coq\n"
            )

        return False

    except Exception as exc:
        print(f"Failed to install Coq: {exc}")
        if strict:
            raise
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best-effort installer for Z3/CVC5/Lean/Coq/SymbolicAI/ErgoAI")
    parser.add_argument("--z3", action="store_true", help="Install/ensure Z3 Python bindings")
    parser.add_argument("--cvc5", action="store_true", help="Install/ensure CVC5 Python bindings")
    parser.add_argument("--lean", action="store_true", help="Install/ensure Lean")
    parser.add_argument("--coq", action="store_true", help="Install/ensure Coq")
    parser.add_argument("--symbolicai", "--symai", action="store_true", help="Install/ensure SymbolicAI")
    parser.add_argument("--ergoai", "--ergo", action="store_true", help="Install/ensure ErgoAI/ErgoEngine")
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

    want_z3 = bool(args.z3)
    want_cvc5 = bool(args.cvc5)
    want_lean = bool(args.lean)
    want_coq = bool(args.coq)
    want_symbolicai = bool(args.symbolicai)
    want_ergoai = bool(args.ergoai)
    if not (want_z3 or want_cvc5 or want_lean or want_coq or want_symbolicai or want_ergoai):
        want_z3 = True
        want_cvc5 = True
        want_lean = True
        want_coq = True
        want_symbolicai = True
        want_ergoai = True

    ok = True
    if want_z3:
        ok = ensure_z3(yes=args.yes, strict=args.strict) and ok
    if want_cvc5:
        ok = ensure_cvc5(yes=args.yes, strict=args.strict) and ok
    if want_lean:
        ok = ensure_lean(yes=args.yes, strict=args.strict) and ok
    if want_coq:
        ok = ensure_coq(yes=args.yes, strict=args.strict, allow_sudo=bool(args.allow_sudo)) and ok
    if want_symbolicai:
        ok = ensure_symbolicai(yes=args.yes, strict=args.strict) and ok
    if want_ergoai:
        ok = ensure_ergoai(yes=args.yes, strict=args.strict) and ok

    if ok:
        return 0

    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
