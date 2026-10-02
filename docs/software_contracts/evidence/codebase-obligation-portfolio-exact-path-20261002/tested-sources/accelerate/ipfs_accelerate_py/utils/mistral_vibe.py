"""Install and discover the optional Mistral Vibe CLI.

The LLM router uses this helper only when the ``mistral_vibe`` provider is
requested explicitly.  Generic provider discovery remains side-effect free.
Authentication is deliberately outside the installer: callers must still run
``vibe --setup`` or provide a Mistral API key.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple


MISTRAL_VIBE_PACKAGE = "mistral-vibe"
MISTRAL_VIBE_EXECUTABLE = "vibe"
MINIMUM_MISTRAL_VIBE_PYTHON = (3, 12)

_AUTO_INSTALL_ENV_NAMES = (
    "IPFS_ACCELERATE_MISTRAL_VIBE_AUTO_INSTALL",
    "IPFS_ACCELERATE_PY_MISTRAL_VIBE_AUTO_INSTALL",
    "ipfs_accelerate_py_MISTRAL_VIBE_AUTO_INSTALL",
)
_INSTALL_LOCK = threading.Lock()
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})

RunFn = Callable[..., subprocess.CompletedProcess[str]]
WhichFn = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class MistralVibeInstallResult:
    """Outcome of one idempotent Vibe discovery or installation attempt."""

    available: bool
    installed: bool = False
    executable: str = ""
    method: str = ""
    reason: str = ""
    command: Sequence[str] = ()
    returncode: Optional[int] = None
    output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        return payload


def mistral_vibe_auto_install_enabled(
    explicit: Optional[bool] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return whether an explicit Vibe request may install the CLI."""

    if explicit is not None:
        return bool(explicit)
    env = os.environ if environ is None else environ
    for name in _AUTO_INSTALL_ENV_NAMES:
        raw = env.get(name)
        if raw is not None:
            return str(raw).strip().lower() not in _FALSE_VALUES
    # Explicit provider resolution opts in by calling this helper.  Automatic
    # LLM provider discovery never calls it.
    return True


def mistral_vibe_auth_available(
    *,
    environ: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> bool:
    """Return whether Vibe has a non-empty Mistral authentication marker."""

    env = os.environ if environ is None else environ
    for name in (
        "MISTRAL_API_KEY",
        "IPFS_ACCELERATE_MISTRAL_API_KEY",
        "IPFS_ACCELERATE_PY_MISTRAL_API_KEY",
        "ipfs_accelerate_py_MISTRAL_API_KEY",
    ):
        if str(env.get(name) or "").strip():
            return True

    root = Path.home() if home is None else Path(home)
    env_path = root / ".vibe" / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "MISTRAL_API_KEY" and value.strip():
                return True
    except OSError:
        return False
    return False


def ensure_mistral_vibe(
    *,
    auto_install: Optional[bool] = None,
    timeout_seconds: float = 600.0,
    environ: Optional[Mapping[str, str]] = None,
    which: Optional[WhichFn] = None,
    run: Optional[RunFn] = None,
) -> MistralVibeInstallResult:
    """Return an available Vibe executable, installing it when allowed.

    Installation follows Mistral's supported CLI path: ``uv tool install
    mistral-vibe`` when ``uv`` is available, otherwise ``python -m pip install
    --user mistral-vibe`` outside virtual environments.  The operation is
    serialized across threads and, on POSIX, across processes.
    """

    env = dict(os.environ if environ is None else environ)
    which_fn = shutil.which if which is None else which
    run_fn = subprocess.run if run is None else run

    executable = _find_vibe_executable(which_fn, env)
    if executable:
        return MistralVibeInstallResult(
            available=True,
            executable=executable,
            method="existing",
            reason="already_installed",
        )
    if not mistral_vibe_auto_install_enabled(auto_install, environ=env):
        return MistralVibeInstallResult(
            available=False,
            method="disabled",
            reason="auto_install_disabled",
        )
    if sys.version_info[:2] < MINIMUM_MISTRAL_VIBE_PYTHON:
        required = ".".join(str(value) for value in MINIMUM_MISTRAL_VIBE_PYTHON)
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        return MistralVibeInstallResult(
            available=False,
            method="unsupported_python",
            reason=f"mistral-vibe requires Python {required}+; current Python is {current}",
        )

    with _INSTALL_LOCK, _process_install_lock():
        executable = _find_vibe_executable(which_fn, env)
        if executable:
            return MistralVibeInstallResult(
                available=True,
                executable=executable,
                method="existing",
                reason="installed_by_peer",
            )

        command, method = _installer_command(which_fn, env)
        if not command:
            return MistralVibeInstallResult(
                available=False,
                method="unavailable",
                reason="neither uv nor pip installation is available",
            )
        try:
            completed = run_fn(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_seconds)),
                env=env,
            )
        except subprocess.TimeoutExpired:
            return MistralVibeInstallResult(
                available=False,
                method=method,
                reason="install_timeout",
                command=tuple(command),
            )
        except OSError as exc:
            return MistralVibeInstallResult(
                available=False,
                method=method,
                reason=f"install_failed:{exc}",
                command=tuple(command),
            )

        output = _compact_output(completed.stdout, completed.stderr)
        executable = _find_vibe_executable(which_fn, env)
        if completed.returncode == 0 and executable:
            return MistralVibeInstallResult(
                available=True,
                installed=True,
                executable=executable,
                method=method,
                reason="installed",
                command=tuple(command),
                returncode=int(completed.returncode),
                output=output,
            )
        reason = (
            "executable_not_found_after_install" if completed.returncode == 0 else "install_failed"
        )
        return MistralVibeInstallResult(
            available=False,
            installed=False,
            method=method,
            reason=reason,
            command=tuple(command),
            returncode=int(completed.returncode),
            output=output,
        )


def _installer_command(which: WhichFn, environ: Mapping[str, str]) -> Tuple[Sequence[str], str]:
    uv = which("uv")
    if uv:
        return (uv, "tool", "install", MISTRAL_VIBE_PACKAGE), "uv_tool"
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    command = [sys.executable, "-m", "pip", "install"]
    if not in_venv:
        command.append("--user")
    if str(environ.get("PIP_BREAK_SYSTEM_PACKAGES") or "").strip() == "1":
        command.append("--break-system-packages")
    command.append(MISTRAL_VIBE_PACKAGE)
    return tuple(command), "pip"


def _find_vibe_executable(which: WhichFn, environ: Mapping[str, str]) -> str:
    discovered = which(MISTRAL_VIBE_EXECUTABLE)
    if discovered:
        return str(Path(discovered).expanduser())
    home = Path(str(environ.get("HOME") or Path.home())).expanduser()
    candidates = (
        home / ".local" / "bin" / MISTRAL_VIBE_EXECUTABLE,
        Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin") / MISTRAL_VIBE_EXECUTABLE,
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


@contextmanager
def _process_install_lock() -> Iterator[None]:
    path = Path(tempfile.gettempdir()) / "ipfs-accelerate-mistral-vibe-install.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def _compact_output(stdout: object, stderr: object, *, limit: int = 2000) -> str:
    text = "\n".join(
        part.strip() for part in (str(stdout or ""), str(stderr or "")) if part
    ).strip()
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


__all__ = [
    "MINIMUM_MISTRAL_VIBE_PYTHON",
    "MISTRAL_VIBE_EXECUTABLE",
    "MISTRAL_VIBE_PACKAGE",
    "MistralVibeInstallResult",
    "ensure_mistral_vibe",
    "mistral_vibe_auth_available",
    "mistral_vibe_auto_install_enabled",
]
