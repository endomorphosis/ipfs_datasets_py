"""Subprocess wrapper for the ProveKit CLI.

This module owns process-boundary concerns for ProveKit:

- binary discovery from explicit environment variables or packaged paths,
- deterministic command construction for ``prepare``, ``prove``, and ``verify``,
- timeout handling and structured command results,
- redaction of witness input paths or caller-provided sensitive values.

It intentionally does not build Rust code, prepare circuits at import time, or
parse private witness files.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .. import ZKPError


PROVEKIT_CLI_BINARY_ENV_VARS = (
    "IPFS_DATASETS_PROVEKIT_CLI",
    "IPFS_DATASETS_PROVEKIT_BIN",
    "PROVEKIT_CLI",
    "PROVEKIT_BIN",
)
PROVEKIT_HOME_ENV_VARS = (
    "IPFS_DATASETS_PROVEKIT_HOME",
    "PROVEKIT_HOME",
)
PROVEKIT_CLI_EXECUTABLE = "provekit-cli.exe" if os.name == "nt" else "provekit-cli"
DEFAULT_PROVEKIT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_CAPTURE_CHARS = 16_384
SENSITIVE_REDACTION = "<redacted:provekit-sensitive>"


Pathish = str | os.PathLike[str]
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ProveKitCommand:
    """A ProveKit command plus values that must be redacted in diagnostics."""

    argv: tuple[str, ...]
    sensitive_values: tuple[str, ...] = ()

    def redacted_argv(self) -> tuple[str, ...]:
        """Return argv with sensitive values removed for logs/errors."""

        return tuple(_sanitize_text(arg, self.sensitive_values) for arg in self.argv)

    def as_log_string(self) -> str:
        """Return a shell-like command string suitable for diagnostics."""

        return " ".join(self.redacted_argv())


@dataclass(frozen=True)
class ProveKitCommandResult:
    """Structured result for a ProveKit subprocess invocation."""

    command: tuple[str, ...]
    cwd: Optional[str]
    returncode: Optional[int]
    stdout: str
    stderr: str
    elapsed_seconds: float
    timeout_seconds: float
    timed_out: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        """Return True when the command completed successfully."""

        return self.returncode == 0 and not self.timed_out and not self.error

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable diagnostic record."""

        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_seconds": self.elapsed_seconds,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "error": self.error,
            "ok": self.ok,
        }

    def raise_for_failure(self) -> None:
        """Raise ``ZKPError`` if this result is not successful."""

        if self.ok:
            return
        detail = self.error or self.stderr or self.stdout or "unknown ProveKit failure"
        raise ZKPError(
            "ProveKit command failed "
            f"(returncode={self.returncode}, timed_out={self.timed_out}): {detail}"
        )


def discover_provekit_binary(
    *,
    env: Optional[Mapping[str, str]] = None,
    package_dir: Optional[Pathish] = None,
    search_path: bool = True,
) -> Optional[Path]:
    """Discover a ProveKit CLI binary without building or importing Rust code.

    Discovery order:

    1. explicit binary env vars such as ``IPFS_DATASETS_PROVEKIT_CLI``,
    2. explicit home env vars such as ``IPFS_DATASETS_PROVEKIT_HOME``,
    3. packaged candidate paths under ``logic/zkp/provekit``,
    4. ``PATH`` lookup for ``provekit-cli``.

    Invalid explicit environment paths raise ``ZKPError`` so misconfiguration
    fails closed. Missing packaged/PATH candidates return ``None``.
    """

    env_map = os.environ if env is None else env

    for var_name in PROVEKIT_CLI_BINARY_ENV_VARS:
        raw = str(env_map.get(var_name) or "").strip()
        if raw:
            return _require_executable(Path(raw), source=var_name)

    for var_name in PROVEKIT_HOME_ENV_VARS:
        raw = str(env_map.get(var_name) or "").strip()
        if not raw:
            continue
        root = Path(raw)
        candidates = (
            root / "bin" / PROVEKIT_CLI_EXECUTABLE,
            root / "target" / "release" / PROVEKIT_CLI_EXECUTABLE,
            root / PROVEKIT_CLI_EXECUTABLE,
        )
        for candidate in candidates:
            if _is_executable(candidate):
                return candidate
        tried = ", ".join(str(path) for path in candidates)
        raise ZKPError(
            f"{var_name} is set, but no executable ProveKit CLI was found. "
            f"Tried: {tried}"
        )

    package_root = Path(package_dir) if package_dir is not None else Path(__file__).resolve().parent
    for candidate in (
        package_root / "bin" / PROVEKIT_CLI_EXECUTABLE,
        package_root / PROVEKIT_CLI_EXECUTABLE,
        package_root / "target" / "release" / PROVEKIT_CLI_EXECUTABLE,
    ):
        if _is_executable(candidate):
            return candidate

    if search_path:
        found = shutil.which(PROVEKIT_CLI_EXECUTABLE)
        if found:
            return Path(found)

    return None


@dataclass
class ProveKitCLI:
    """Thin subprocess facade for the ProveKit CLI."""

    binary_path: Optional[Pathish] = None
    timeout_seconds: float = DEFAULT_PROVEKIT_TIMEOUT_SECONDS
    max_capture_chars: int = DEFAULT_MAX_CAPTURE_CHARS
    runner: Runner = subprocess.run

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_capture_chars <= 0:
            raise ValueError("max_capture_chars must be positive")

        if self.binary_path is None:
            discovered = discover_provekit_binary()
            if discovered is None:
                raise ZKPError(
                    "ProveKit CLI binary not found. Set IPFS_DATASETS_PROVEKIT_CLI "
                    "or IPFS_DATASETS_PROVEKIT_HOME, or install a packaged "
                    f"{PROVEKIT_CLI_EXECUTABLE} binary."
                )
            self.binary_path = discovered
        else:
            self.binary_path = _require_executable(
                Path(self.binary_path),
                source="binary_path",
            )

    def build_prepare_command(
        self,
        *,
        program_dir: Optional[Pathish] = None,
        package: Optional[str] = None,
        workspace: bool = False,
        target_dir: Optional[Pathish] = None,
        prover_key_path: Optional[Pathish] = None,
        verifier_key_path: Optional[Pathish] = None,
        force: bool = False,
        extra_args: Sequence[str] = (),
    ) -> ProveKitCommand:
        """Build ``provekit-cli prepare`` with explicit artifact paths."""

        argv: list[str] = [str(self.binary_path), "prepare"]
        if package:
            argv.extend(["--package", str(package)])
        if workspace:
            argv.append("--workspace")
        if target_dir is not None:
            argv.extend(["--target-dir", _path_str(target_dir)])
        if force:
            argv.append("--force")
        if prover_key_path is not None:
            argv.extend(["--pkp", _path_str(prover_key_path)])
        if verifier_key_path is not None:
            argv.extend(["--pkv", _path_str(verifier_key_path)])
        argv.extend(str(arg) for arg in extra_args)
        if program_dir is not None:
            argv.append(_path_str(program_dir))
        return ProveKitCommand(tuple(argv))

    def build_prove_command(
        self,
        *,
        prover_key_path: Pathish,
        input_path: Pathish,
        proof_path: Pathish,
        extra_args: Sequence[str] = (),
    ) -> ProveKitCommand:
        """Build ``provekit-cli prove`` and mark the witness input path private."""

        input_text = _path_str(input_path)
        argv = (
            str(self.binary_path),
            "prove",
            "--prover",
            _path_str(prover_key_path),
            "--input",
            input_text,
            "--out",
            _path_str(proof_path),
            *tuple(str(arg) for arg in extra_args),
        )
        return ProveKitCommand(argv, sensitive_values=(input_text,))

    def build_verify_command(
        self,
        *,
        verifier_key_path: Pathish,
        proof_path: Pathish,
        extra_args: Sequence[str] = (),
    ) -> ProveKitCommand:
        """Build ``provekit-cli verify``."""

        argv = (
            str(self.binary_path),
            "verify",
            "--verifier",
            _path_str(verifier_key_path),
            "--proof",
            _path_str(proof_path),
            *tuple(str(arg) for arg in extra_args),
        )
        return ProveKitCommand(argv)

    def run_command(
        self,
        command: ProveKitCommand,
        *,
        cwd: Optional[Pathish] = None,
        timeout_seconds: Optional[float] = None,
        extra_sensitive_values: Iterable[str] = (),
    ) -> ProveKitCommandResult:
        """Run a command and return a redacted structured result."""

        timeout = float(timeout_seconds or self.timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")

        sensitive_values = tuple(command.sensitive_values) + tuple(
            str(value) for value in extra_sensitive_values if str(value)
        )
        cwd_text = _path_str(cwd) if cwd is not None else None
        start = time.monotonic()
        try:
            completed = self.runner(
                list(command.argv),
                cwd=cwd_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            elapsed = time.monotonic() - start
            return self._result(
                command=command,
                cwd=cwd_text,
                returncode=int(completed.returncode),
                stdout=_text(completed.stdout),
                stderr=_text(completed.stderr),
                elapsed_seconds=elapsed,
                timeout_seconds=timeout,
                sensitive_values=sensitive_values,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - start
            return self._result(
                command=command,
                cwd=cwd_text,
                returncode=None,
                stdout=_text(exc.output),
                stderr=_text(exc.stderr),
                elapsed_seconds=elapsed,
                timeout_seconds=timeout,
                sensitive_values=sensitive_values,
                timed_out=True,
                error=f"ProveKit command timed out after {timeout:g} seconds",
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
            elapsed = time.monotonic() - start
            return self._result(
                command=command,
                cwd=cwd_text,
                returncode=None,
                stdout="",
                stderr="",
                elapsed_seconds=elapsed,
                timeout_seconds=timeout,
                sensitive_values=sensitive_values,
                error=f"ProveKit command execution failed: {exc}",
            )

    def prepare(self, **kwargs: Any) -> ProveKitCommandResult:
        """Build and run ``prepare``."""

        cwd = kwargs.pop("cwd", None)
        command = self.build_prepare_command(**kwargs)
        return self.run_command(command, cwd=cwd)

    def prove(self, **kwargs: Any) -> ProveKitCommandResult:
        """Build and run ``prove``."""

        cwd = kwargs.pop("cwd", None)
        extra_sensitive_values = tuple(kwargs.pop("extra_sensitive_values", ()))
        command = self.build_prove_command(**kwargs)
        return self.run_command(
            command,
            cwd=cwd,
            extra_sensitive_values=extra_sensitive_values,
        )

    def verify(self, **kwargs: Any) -> ProveKitCommandResult:
        """Build and run ``verify``."""

        cwd = kwargs.pop("cwd", None)
        command = self.build_verify_command(**kwargs)
        return self.run_command(command, cwd=cwd)

    def _result(
        self,
        *,
        command: ProveKitCommand,
        cwd: Optional[str],
        returncode: Optional[int],
        stdout: str,
        stderr: str,
        elapsed_seconds: float,
        timeout_seconds: float,
        sensitive_values: tuple[str, ...],
        timed_out: bool = False,
        error: str = "",
    ) -> ProveKitCommandResult:
        redaction_values = sensitive_values
        return ProveKitCommandResult(
            command=tuple(_sanitize_text(arg, redaction_values) for arg in command.argv),
            cwd=_sanitize_text(cwd, redaction_values) if cwd is not None else None,
            returncode=returncode,
            stdout=_truncate(_sanitize_text(stdout, redaction_values), self.max_capture_chars),
            stderr=_truncate(_sanitize_text(stderr, redaction_values), self.max_capture_chars),
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=timeout_seconds,
            timed_out=timed_out,
            error=_truncate(_sanitize_text(error, redaction_values), self.max_capture_chars),
        )


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _require_executable(path: Path, *, source: str) -> Path:
    if _is_executable(path):
        return path
    raise ZKPError(
        f"Configured ProveKit CLI from {source} is not executable or does not exist: {path}"
    )


def _path_str(path: Pathish | None) -> str:
    if path is None:
        return ""
    return str(Path(path))


def _sanitize_text(value: str | None, sensitive_values: Iterable[str]) -> str:
    if value is None:
        return ""
    sanitized = str(value)
    for sensitive in sorted({str(v) for v in sensitive_values if str(v)}, key=len, reverse=True):
        sanitized = sanitized.replace(sensitive, SENSITIVE_REDACTION)
    return sanitized


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n...[truncated {omitted} chars]"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

