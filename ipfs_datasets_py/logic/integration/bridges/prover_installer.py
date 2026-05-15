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

The installer is best-effort and never raises on failure unless `--strict` is used.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _run(cmd: list[str], *, check: bool, env: dict[str, str] | None = None) -> int:
    proc = subprocess.run(cmd, text=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.returncode


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _pip_install(requirement: str, *, strict: bool) -> bool:
    rc = _run([sys.executable, "-m", "pip", "install", requirement], check=False)
    if rc != 0 and strict:
        raise RuntimeError(f"Could not install Python dependency: {requirement}")
    return rc == 0


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

        lean_home = Path.home() / ".elan" / "bin" / "lean"
        if lean_home.exists():
            print(f"Installed Lean via elan: {lean_home}")
            return True

        print("Attempted to install Lean via elan, but lean binary was not found afterwards.")
        return False

    except Exception as exc:
        print(f"Failed to install Lean via elan: {exc}")
        if strict:
            raise
        return False


def ensure_coq(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure `coqc` exists.

    Strategy:
    - If `coqc` already on PATH: success
    - If running as root and apt-get exists: try install via apt
    - If opam exists: print guidance (opam-based install can be long)

    We intentionally keep Coq auto-install conservative; building from source via
    opam can take significant time and requires a full OCaml toolchain.
    """

    if _which("coqc"):
        return True

    if not yes:
        print("Coq not found. Re-run with --yes to attempt a best-effort install.")
        return False

    try:
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        have_apt = bool(_which("apt-get"))
        have_sudo = bool(_which("sudo"))

        def _sudo_non_interactive_ok() -> bool:
            if not have_sudo:
                return False
            try:
                probe = subprocess.run(
                    ["sudo", "-n", "true"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return probe.returncode == 0
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
                logger.debug(f"Could not check sudo access: {e}")
                return False

        if have_apt:
            if is_root:
                print("Attempting to install Coq via apt-get (root detected)...")
                _run(["apt-get", "update"], check=False)
                rc = _run(["apt-get", "install", "-y", "coq"], check=False)
                if rc == 0 and _which("coqc"):
                    print("Installed Coq via apt-get.")
                    return True
            elif _sudo_non_interactive_ok():
                print("Attempting to install Coq via sudo apt-get (passwordless sudo detected)...")
                _run(["sudo", "-n", "apt-get", "update"], check=False)
                rc = _run(["sudo", "-n", "apt-get", "install", "-y", "coq"], check=False)
                if rc == 0 and _which("coqc"):
                    print("Installed Coq via sudo apt-get.")
                    return True
            else:
                pass

        if have_apt and not is_root and have_sudo and not _sudo_non_interactive_ok():
            print(
                "Coq not found. Auto-install via apt-get requires root or passwordless sudo.\n"
                "You can install manually with:\n"
                "  sudo apt-get update && sudo apt-get install -y coq\n"
            )
            return False

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
            )

        return False

    except Exception as exc:
        print(f"Failed to install Coq: {exc}")
        if strict:
            raise
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best-effort installer for Z3/CVC5/Lean/Coq/SymbolicAI")
    parser.add_argument("--z3", action="store_true", help="Install/ensure Z3 Python bindings")
    parser.add_argument("--cvc5", action="store_true", help="Install/ensure CVC5 Python bindings")
    parser.add_argument("--lean", action="store_true", help="Install/ensure Lean")
    parser.add_argument("--coq", action="store_true", help="Install/ensure Coq")
    parser.add_argument("--symbolicai", "--symai", action="store_true", help="Install/ensure SymbolicAI")
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
    if not (want_z3 or want_cvc5 or want_lean or want_coq or want_symbolicai):
        want_z3 = True
        want_cvc5 = True
        want_lean = True
        want_coq = True
        want_symbolicai = True

    ok = True
    if want_z3:
        ok = ensure_z3(yes=args.yes, strict=args.strict) and ok
    if want_cvc5:
        ok = ensure_cvc5(yes=args.yes, strict=args.strict) and ok
    if want_lean:
        ok = ensure_lean(yes=args.yes, strict=args.strict) and ok
    if want_coq:
        ok = ensure_coq(yes=args.yes, strict=args.strict) and ok
    if want_symbolicai:
        ok = ensure_symbolicai(yes=args.yes, strict=args.strict) and ok

    if ok:
        return 0

    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
