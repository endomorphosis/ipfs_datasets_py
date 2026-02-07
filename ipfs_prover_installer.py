"""Lightweight, side-effect-free installer for external theorem provers (Lean/Coq).

This module intentionally does NOT import `ipfs_datasets_py` to avoid heavy import-time
side effects during installation or CLI execution.

Usage:
- `python -m ipfs_prover_installer --yes --lean`
- `python -m ipfs_prover_installer --yes --coq`

See also: setup.py env vars:
- IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS=1
- IPFS_DATASETS_PY_AUTO_INSTALL_LEAN=1
- IPFS_DATASETS_PY_AUTO_INSTALL_COQ=1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _works(exe: str, args: list[str]) -> bool:
    try:
        rc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=10)
        return rc.returncode == 0
    except Exception:
        return False


def _run(cmd: list[str], *, check: bool) -> int:
    proc = subprocess.run(cmd, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.returncode


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ipfs_prover_installer",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def _github_latest_assets(owner: str, repo: str) -> list[dict]:
    data = _http_get_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
    assets = data.get("assets") or []
    if isinstance(assets, list):
        return [a for a in assets if isinstance(a, dict)]
    return []


def _select_asset(assets: list[dict], patterns: list[str]) -> dict | None:
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    for asset in assets:
        name = str(asset.get("name") or "")
        if not name:
            continue
        if any(r.search(name) for r in compiled):
            return asset
    return None


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ipfs_prover_installer"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    dest.write_bytes(data)


def _install_executable_from_archive(
    *,
    archive_path: Path,
    executable_name: str,
    dest_path: Path,
) -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            extract_dir = Path(tmp) / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            if archive_path.suffix.lower() == ".zip":
                with zipfile.ZipFile(str(archive_path), "r") as zf:
                    zf.extractall(str(extract_dir))
            else:
                # tar.gz / tgz / tar
                with tarfile.open(str(archive_path), "r:*") as tf:
                    tf.extractall(str(extract_dir))

            candidates = []
            for p in extract_dir.rglob(executable_name):
                try:
                    if p.is_file() and os.access(str(p), os.X_OK):
                        candidates.append(p)
                except Exception:
                    continue

            if not candidates:
                # Some archives may not mark executable bit; take first file match.
                for p in extract_dir.rglob(executable_name):
                    if p.is_file():
                        candidates.append(p)
                        break

            if not candidates:
                return False

            src = candidates[0]
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(src.read_bytes())
            dest_path.chmod(0o755)
            return True
    except Exception:
        return False


def ensure_lean(*, yes: bool, strict: bool) -> bool:
    existing = _which("lean")
    if existing and _works(existing, ["--version"]):
        return True

    if not yes:
        print("Lean not found. Re-run with --yes to attempt install via elan.")
        return False

    try:
        url = "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh"
        with urllib.request.urlopen(url, timeout=30) as resp:
            script = resp.read()

        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "elan-init.sh"
            script_path.write_bytes(script)
            script_path.chmod(0o755)
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


def _user_local_bin() -> Path:
    return Path.home() / ".local" / "bin"


def ensure_z3(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure Z3 is available.

    Preference order:
    - `z3` already on PATH
    - `apt-get install z3` when running as root
    - Download a prebuilt release archive into `~/.local/bin/z3` (best-effort)
    - Install Python bindings (`z3-solver`) as fallback
    """

    existing = _which("z3")
    if existing and _works(existing, ["--version"]):
        return True

    if not yes:
        print("Z3 not found. Re-run with --yes to attempt a best-effort install.")
        return False

    try:
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if is_root and _which("apt-get"):
            print("Attempting to install Z3 via apt-get (root detected)...")
            _run(["apt-get", "update"], check=False)
            rc = _run(["apt-get", "install", "-y", "z3"], check=False)
            if rc == 0 and _which("z3"):
                print("Installed Z3 via apt-get.")
                return True

        # Best-effort user-space install from GitHub release.
        dest = _user_local_bin() / "z3"
        try:
            assets = _github_latest_assets("Z3Prover", "z3")
            asset = _select_asset(
                assets,
                [
                    r"linux.*x64.*\\.zip$",
                    r"x64.*linux.*\\.zip$",
                    r"glibc.*x64.*\\.zip$",
                    r"linux.*x64.*\\.(tar\\.gz|tgz)$",
                    r"x64.*linux.*\\.(tar\\.gz|tgz)$",
                ],
            )
            if asset and asset.get("browser_download_url"):
                url = str(asset["browser_download_url"])
                name = str(asset.get("name") or "z3-archive")
                archive_path = Path(tempfile.gettempdir()) / name
                print(f"Downloading Z3 release asset: {name}")
                _download_file(url, archive_path)
                if _install_executable_from_archive(
                    archive_path=archive_path,
                    executable_name="z3",
                    dest_path=dest,
                ):
                    rc = subprocess.run([str(dest), "--version"], capture_output=True, text=True, timeout=10)
                    if rc.returncode == 0:
                        print(f"Installed Z3 to {dest}")
                        return True
        except Exception as exc:
            if strict:
                raise
            print(f"Z3 download install failed (best-effort): {exc}")

        # Fallback: Python package
        print("Attempting to install Python package z3-solver (fallback)...")
        rc = _run([sys.executable, "-m", "pip", "install", "z3-solver"], check=False)
        if rc == 0:
            try:
                import z3  # type: ignore

                _ = z3.get_version_string()
                print("Installed z3-solver Python bindings.")
                return True
            except Exception:
                pass

        print("Unable to install Z3 automatically. Install via OS packages or z3-solver.")
        return False

    except Exception as exc:
        print(f"Failed to install Z3: {exc}")
        if strict:
            raise
        return False


def _download_to(path: Path, url: str, *, strict: bool) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        path.write_bytes(data)
        path.chmod(0o755)
        return True
    except Exception as exc:
        if strict:
            raise RuntimeError(f"Failed download {url}: {exc}")
        return False


def ensure_cvc5(*, yes: bool, strict: bool) -> bool:
    """Attempt to ensure CVC5 is available.

    Preference order:
    - `cvc5` already on PATH
    - `apt-get install cvc5` when running as root
    - Download a prebuilt Linux binary into `~/.local/bin/cvc5` (best-effort)
    """

    existing = _which("cvc5")
    if existing:
        if _works(existing, ["--version"]):
            return True
        # Broken binary (e.g., wrong arch) — try to clean up user-local install.
        try:
            p = Path(existing).resolve()
            if str(p).startswith(str(_user_local_bin().resolve())):
                p.unlink(missing_ok=True)
        except Exception:
            pass

    if not yes:
        print("cvc5 not found. Re-run with --yes to attempt a best-effort install.")
        return False

    try:
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if is_root and _which("apt-get"):
            print("Attempting to install cvc5 via apt-get (root detected)...")
            _run(["apt-get", "update"], check=False)
            rc = _run(["apt-get", "install", "-y", "cvc5"], check=False)
            if rc == 0 and _which("cvc5"):
                print("Installed cvc5 via apt-get.")
                return True

        # Best-effort download for Linux x86_64.
        dest = _user_local_bin() / "cvc5"
        print(f"Attempting to download cvc5 into {dest} (best-effort)...")

        try:
            assets = _github_latest_assets("cvc5", "cvc5")
            # Prefer actual solver bundles for Linux x86_64, and avoid java API jars.
            preferred = []
            for a in assets:
                name = str(a.get("name") or "")
                if not name:
                    continue
                if name.lower().endswith(".jar"):
                    continue
                if "Linux-x86_64" not in name:
                    continue
                preferred.append(a)

            # Priority: static zip -> shared zip -> anything else x86_64 zip.
            patterns = [
                r"cvc5-Linux-x86_64-static(-gpl)?\\.zip$",
                r"cvc5-Linux-x86_64-shared(-gpl)?\\.zip$",
                r"cvc5-Linux-x86_64.*\\.zip$",
            ]

            # Build a prioritized list of assets to try.
            to_try: list[dict] = []
            for pat in patterns:
                a = _select_asset(preferred, [pat])
                if a and a not in to_try:
                    to_try.append(a)
            for a in preferred:
                if a not in to_try:
                    to_try.append(a)

            for asset in to_try:
                if not asset.get("browser_download_url"):
                    continue
                url = str(asset["browser_download_url"])
                name = str(asset.get("name") or "cvc5")
                print(f"Downloading cvc5 release asset: {name}")
                tmp_path = Path(tempfile.gettempdir()) / name

                try:
                    _download_file(url, tmp_path)
                except Exception:
                    continue

                installed = False
                if name.lower().endswith((".zip", ".tar.gz", ".tgz", ".tar")):
                    installed = _install_executable_from_archive(
                        archive_path=tmp_path,
                        executable_name="cvc5",
                        dest_path=dest,
                    )
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(tmp_path.read_bytes())
                    dest.chmod(0o755)
                    installed = True

                if not installed:
                    continue

                # Basic ELF check to avoid leaving a broken file.
                try:
                    magic = dest.read_bytes()[:4]
                    if magic != b"\x7fELF":
                        raise RuntimeError("not an ELF binary")
                except Exception:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue

                rc = subprocess.run([str(dest), "--version"], capture_output=True, text=True, timeout=10)
                if rc.returncode == 0:
                    print(f"Installed cvc5 to {dest}")
                    return True

                # Clean up bad install.
                try:
                    dest.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as exc:
            if strict:
                raise
            print(f"cvc5 download install failed (best-effort): {exc}")

        print(
            "Unable to install cvc5 automatically. Install via your OS package manager or build from source."
        )
        return False

    except Exception as exc:
        print(f"Failed to install cvc5: {exc}")
        if strict:
            raise
        return False


def ensure_coq(*, yes: bool, strict: bool, allow_sudo: bool = False) -> bool:
    existing = _which("coqc")
    if existing and _works(existing, ["--version"]):
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
            except Exception:
                return False

        if have_apt:
            if is_root:
                print("Attempting to install Coq via apt-get (root detected)...")
                _run(["apt-get", "update"], check=False)
                rc = _run(["apt-get", "install", "-y", "coq"], check=False)
                if rc == 0 and _which("coqc"):
                    print("Installed Coq via apt-get.")
                    return True
            elif have_sudo:
                if allow_sudo:
                    print("Attempting to install Coq via sudo apt-get (may prompt for password)...")
                    _run(["sudo", "apt-get", "update"], check=False)
                    rc = _run(["sudo", "apt-get", "install", "-y", "coq"], check=False)
                    if rc == 0 and _which("coqc"):
                        print("Installed Coq via sudo apt-get.")
                        return True
                elif _sudo_non_interactive_ok():
                    print("Attempting to install Coq via sudo apt-get (passwordless sudo detected)...")
                    _run(["sudo", "-n", "apt-get", "update"], check=False)
                    rc = _run(["sudo", "-n", "apt-get", "install", "-y", "coq"], check=False)
                    if rc == 0 and _which("coqc"):
                        print("Installed Coq via sudo apt-get.")
                        return True
            else:
                # Don't block on an interactive sudo prompt; this installer is used in non-interactive contexts.
                pass

        if have_apt and not is_root and have_sudo and (not allow_sudo) and not _sudo_non_interactive_ok():
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
    parser = argparse.ArgumentParser(description="Best-effort installer for Z3/CVC5/Lean/Coq")
    parser.add_argument("--z3", action="store_true", help="Install/ensure Z3")
    parser.add_argument("--cvc5", action="store_true", help="Install/ensure CVC5")
    parser.add_argument("--lean", action="store_true", help="Install/ensure Lean 4")
    parser.add_argument("--coq", action="store_true", help="Install/ensure Coq")
    parser.add_argument("--yes", action="store_true", help="Non-interactive / accept defaults")
    parser.add_argument(
        "--allow-sudo",
        action="store_true",
        help="Allow running interactive sudo (may prompt for password).",
    )
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
    if not (want_z3 or want_cvc5 or want_lean or want_coq):
        want_z3 = True
        want_cvc5 = True
        want_lean = True
        want_coq = True

    ok = True
    if want_z3:
        ok = ensure_z3(yes=args.yes, strict=args.strict) and ok
    if want_cvc5:
        ok = ensure_cvc5(yes=args.yes, strict=args.strict) and ok
    if want_lean:
        ok = ensure_lean(yes=args.yes, strict=args.strict) and ok
    if want_coq:
        ok = ensure_coq(yes=args.yes, strict=args.strict, allow_sudo=bool(args.allow_sudo)) and ok

    if ok:
        return 0

    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
