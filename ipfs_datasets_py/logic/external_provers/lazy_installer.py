"""Lazy installer for optional external theorem prover dependencies.

The prover bridges import cleanly without installing anything.  When a bridge
is explicitly requested and its dependency is missing, this module can perform
a single best-effort install attempt. Normal bridge imports remain opt-in;
native execution paths can request automatic installation and always emit
progress events so a first-use download or build is not silent.

Environment variables:
- IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 enables requested-prover installs.
- IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>=0/1 overrides a prover.
- IPFS_DATASETS_PY_LAZY_INSTALL_STRICT=1 raises on installer failure.
- IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS=1 permits interactive sudo for Coq.
- IPFS_DATASETS_PY_ERGOAI_GIT_URL overrides the ErgoAI/ErgoEngine source repo.
- IPFS_DATASETS_PY_ERGOAI_RELEASE_URL overrides the official ErgoAI .run URL.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR sets the user-local ErgoAI install dir.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND runs a custom ErgoAI installer command.
- IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT controls user-local native solver
  artifacts (default: ~/.local/share/ipfs_datasets_py/theorem-provers).
- IPFS_DATASETS_PY_<PROVER>_EXECUTABLE selects an explicit native executable
  or a launcher for a portable runtime such as a Node-hosted WebAssembly build.
- IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND overrides a native solver install
  on platforms without a packaged release artifact.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ipfs_datasets_py.logic.common.feature_detection import (
    clear_feature_detection_cache,
    minimal_imports_enabled,
)

logger = logging.getLogger(__name__)

_ATTEMPTED: set[str] = set()

_ALIASES = {
    "z3": "z3",
    "z3_solver": "z3",
    "z3prover": "z3",
    "cvc5": "cvc5",
    "cvc5_prover": "cvc5",
    "vampire": "vampire",
    "vampire_prover": "vampire",
    "e": "eprover",
    "e_prover": "eprover",
    "eprover": "eprover",
    "lean": "lean",
    "lean_prover": "lean",
    "lake": "lean",
    "coq": "coq",
    "coq_prover": "coq",
    "coqc": "coq",
    "coqtop": "coq",
    "rocq": "coq",
    "rocq_prover": "coq",
    "rocq-prover": "coq",
    "isabelle": "isabelle",
    "isabelle_prover": "isabelle",
    "apalache": "apalache",
    "apalache_mc": "apalache",
    "apalache-mc": "apalache",
    "tamarin": "tamarin",
    "tamarin_prover": "tamarin",
    "tamarin-prover": "tamarin",
    "maude": "maude",
    "proverif": "proverif",
    "symbolicai": "symbolicai",
    "symbolic_ai": "symbolicai",
    "symbolicai_prover": "symbolicai",
    "symbolic_ai_prover": "symbolicai",
    "symai": "symbolicai",
    "ergo": "ergoai",
    "ergoai": "ergoai",
    "ergo_ai": "ergoai",
    "ergoengine": "ergoai",
    "ergo_engine": "ergoai",
    "runergo": "ergoai",
    "runergo.sh": "ergoai",
    "runergo_sh": "ergoai",
}

_ENV_NAMES = {
    "z3": "Z3",
    "cvc5": "CVC5",
    "vampire": "VAMPIRE",
    "eprover": "EPROVER",
    "lean": "LEAN",
    "coq": "COQ",
    "isabelle": "ISABELLE",
    "apalache": "APALACHE",
    "tamarin": "TAMARIN",
    "maude": "MAUDE",
    "proverif": "PROVERIF",
    "symbolicai": "SYMBOLICAI",
    "ergoai": "ERGOAI",
}

_PROVER_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "apalache": ("apalache-mc", "apalache"),
    "tamarin": ("tamarin-prover",),
    "maude": ("maude",),
    "proverif": ("proverif",),
    "lean": ("lean",),
    "coq": ("coqc",),
    "isabelle": ("isabelle",),
    "cvc5": ("cvc5",),
    "vampire": ("vampire",),
    "eprover": ("eprover",),
    "ergoai": ("ergoai", "ergo", "runErgo.sh", "runergo"),
}


@dataclass(frozen=True)
class ProverInstallEvent:
    """A user-facing lazy-installer state transition.

    Callers can send these events to a progress bar, a desktop notification,
    or a log pane. The default reporter writes the same transition to stdout so
    a synchronous first-run install is visibly active rather than silent.
    """

    prover: str
    phase: Literal[
        "checking",
        "available",
        "installing",
        "installed",
        "disabled",
        "blocked",
        "failed",
    ]
    message: str


ProgressCallback = Callable[[ProverInstallEvent], None]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_prover_name(prover_name: str) -> str:
    """Return the canonical lazy-installer name for a prover."""

    normalized = (
        str(prover_name or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
    )
    return _ALIASES.get(normalized, normalized)


def _common_bin_dirs() -> list[Path]:
    try:
        home = Path.home()
    except (OSError, RuntimeError):
        return []
    configured_root = os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT")
    prover_root = (
        Path(configured_root).expanduser()
        if configured_root
        else home / ".local" / "share" / "ipfs_datasets_py" / "theorem-provers"
    )
    return [
        home / ".local" / "bin",
        home / ".elan" / "bin",
        home / ".opam" / "default" / "bin",
        prover_root / "bin",
    ]


def find_executable(command: str) -> str | None:
    """Find a usable prover executable, preferring managed and explicit paths."""

    command = str(command or "").strip()
    if not command:
        return None
    path = Path(command).expanduser()
    env_name = normalize_prover_name(path.name).upper()
    explicit = os.environ.get(f"IPFS_DATASETS_PY_{env_name}_EXECUTABLE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if path.parent != Path("."):
        candidates.append(path)
    else:
        directories = _common_bin_dirs()
        # The managed launcher is pinned and checksummed; it must outrank PATH,
        # which can contain a stale binary for another CPU architecture.
        if directories:
            candidates.append(directories[-1] / command)
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
        candidates.extend(directory / command for directory in directories[:-1])

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            if not candidate.is_file() or not os.access(str(candidate), os.X_OK):
                continue
            if normalize_prover_name(path.name) == "cvc5":
                try:
                    probe = subprocess.run(
                        [str(candidate), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except (OSError, subprocess.SubprocessError):
                    continue
                if probe.returncode != 0 or "cvc5" not in (
                    f"{probe.stdout}\n{probe.stderr}".lower()
                ):
                    continue
            return str(candidate)
        except OSError:
            continue
    return None


def lazy_installs_enabled() -> bool:
    """Return True when lazy prover installs are globally enabled."""

    if minimal_imports_enabled():
        return False

    explicit = os.environ.get("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS")
    if explicit is not None:
        return _truthy(explicit)

    return _truthy(os.environ.get("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"))


def _explicitly_disabled() -> bool:
    """Return whether the caller explicitly opted out of lazy installation."""

    for name in (
        "IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS",
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS",
    ):
        value = os.environ.get(name)
        if value is not None and not _truthy(value):
            return True
    return False


def _emit(event: ProverInstallEvent, progress: ProgressCallback | None) -> None:
    logger.info("%s: %s", event.prover, event.message)
    print(f"[ipfs_datasets_py] {event.prover}: {event.message}", flush=True)
    if progress is not None:
        progress(event)


def prover_lazy_install_enabled(prover_name: str) -> bool:
    """Return True when lazy installation is enabled for a specific prover."""

    prover = normalize_prover_name(prover_name)
    if not lazy_installs_enabled():
        return False

    env_name = _ENV_NAMES.get(prover, prover.upper())
    explicit = os.environ.get(f"IPFS_DATASETS_PY_LAZY_INSTALL_{env_name}")
    if explicit is not None:
        return _truthy(explicit)

    auto_install = os.environ.get(f"IPFS_DATASETS_PY_AUTO_INSTALL_{env_name}")
    if auto_install is not None:
        return _truthy(auto_install)

    # Reconstruction kernels are large/slow, so ordinary optional bridge use
    # stays opt-in. An execution path that explicitly requests the kernel uses
    # allow_automatic=True and still receives visible progress.
    if prover in {"coq", "isabelle"}:
        return False

    return True


def lazy_install_strict() -> bool:
    """Return True when lazy installer failures should raise."""

    return _truthy(os.environ.get("IPFS_DATASETS_PY_LAZY_INSTALL_STRICT")) or _truthy(
        os.environ.get("IPFS_DATASETS_PY_PROVER_INSTALL_STRICT")
    )


def lazy_install_prover(
    prover_name: str,
    *,
    force: bool = False,
    strict: bool | None = None,
    reason: str | None = None,
    progress: ProgressCallback | None = None,
    allow_automatic: bool = False,
) -> bool:
    """Try to install a prover dependency once and emit visible progress.

    Normal bridge use remains opt-in through the lazy-install environment
    variables. Execution paths that are explicitly asking for a native solver
    can pass ``allow_automatic=True``; that still respects a caller's explicit
    ``...LAZY_INSTALL_PROVERS=0`` opt-out.
    """

    prover = normalize_prover_name(prover_name)
    if not prover_lazy_install_enabled(prover) and not (
        allow_automatic and not _explicitly_disabled() and not minimal_imports_enabled()
    ):
        _emit(
            ProverInstallEvent(
                prover,
                "disabled",
                "lazy installation is disabled; set IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 to enable it",
            ),
            progress,
        )
        return False

    if prover in _ATTEMPTED and not force:
        return False

    _ATTEMPTED.add(prover)
    strict = lazy_install_strict() if strict is None else strict
    _emit(
        ProverInstallEvent(prover, "checking", f"checking whether {prover} is already available"),
        progress,
    )

    try:
        from ipfs_datasets_py.logic.integration.bridges import prover_installer

        ensure_name = "ensure_cvc5_cli" if prover == "cvc5" and allow_automatic else f"ensure_{prover}"
        ensure = getattr(prover_installer, ensure_name, None)
        if ensure is None:
            logger.debug("No lazy installer is registered for prover %s", prover)
            _emit(
                ProverInstallEvent(prover, "failed", "no installer is registered for this prover"),
                progress,
            )
            return False

        kwargs = {"yes": True, "strict": strict}
        if prover == "coq":
            kwargs["allow_sudo"] = _truthy(
                os.environ.get("IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS")
            )

        if progress is not None and prover in {
            "z3", "cvc5", "vampire", "eprover", "lean", "coq", "isabelle", "apalache", "tamarin", "maude", "proverif", "symbolicai", "ergoai"
        }:
            def forward_progress(phase: str, message: str) -> None:
                normalized_phase = phase if phase in {
                    "checking", "available", "installing", "installed", "blocked", "failed"
                } else "installing"
                event = ProverInstallEvent(prover, normalized_phase, message)
                logger.info("%s: %s", prover, message)
                if progress is not None:
                    progress(event)

            kwargs["on_progress"] = forward_progress

        _emit(
            ProverInstallEvent(
                prover,
                "installing",
                "installation started" + (f" because {reason}" if reason else ""),
            ),
            progress,
        )
        ok = bool(ensure(**kwargs))
        importlib.invalidate_caches()
        clear_feature_detection_cache()
        _emit(
            ProverInstallEvent(
                prover,
                "installed" if ok else "failed",
                "installation completed" if ok else "installation did not make the prover available",
            ),
            progress,
        )
        return ok
    except Exception as exc:
        logger.exception("Lazy install failed for prover %s", prover)
        _emit(ProverInstallEvent(prover, "failed", f"installation failed: {exc}"), progress)
        if strict:
            raise
        return False


def ensure_prover_executable(
    prover_name: str,
    *,
    reason: str,
    progress: ProgressCallback | None = None,
    strict: bool | None = None,
) -> str | None:
    """Return a required executable, installing it lazily when explicitly used.

    This function is the integration point for real execution paths. It does
    not run at import time, but it does make first use visibly install the
    selected optional native solver unless the caller explicitly opted out
    through ``IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0``. This is deliberately
    separate from normal bridge imports, which never trigger a download or
    build.
    """

    prover = normalize_prover_name(prover_name)
    candidates = _PROVER_EXECUTABLES.get(prover, (prover,))
    explicit_ergoai = os.environ.get("ERGOAI_BINARY") if prover == "ergoai" else None
    if explicit_ergoai:
        path = Path(explicit_ergoai).expanduser()
        if path.is_file() and os.access(str(path), os.X_OK):
            _emit(ProverInstallEvent(prover, "available", f"using {path}"), progress)
            return str(path)
    _emit(
        ProverInstallEvent(prover, "checking", f"resolving executable for {reason}"),
        progress,
    )
    for candidate in candidates:
        executable = find_executable(candidate)
        if executable:
            _emit(ProverInstallEvent(prover, "available", f"using {executable}"), progress)
            return executable

    lazy_install_prover(
        prover,
        strict=strict,
        reason=reason,
        progress=progress,
        allow_automatic=True,
    )
    if prover == "ergoai":
        explicit_ergoai = os.environ.get("ERGOAI_BINARY")
        if explicit_ergoai:
            path = Path(explicit_ergoai).expanduser()
            if path.is_file() and os.access(str(path), os.X_OK):
                _emit(ProverInstallEvent(prover, "installed", f"using installed executable {path}"), progress)
                return str(path)
    for candidate in candidates:
        executable = find_executable(candidate)
        if executable:
            _emit(ProverInstallEvent(prover, "installed", f"using installed executable {executable}"), progress)
            return executable
    return None


def reset_lazy_install_attempts() -> None:
    """Clear the per-process lazy-install attempt cache."""

    _ATTEMPTED.clear()


__all__ = [
    "find_executable",
    "ensure_prover_executable",
    "lazy_install_prover",
    "lazy_install_strict",
    "lazy_installs_enabled",
    "normalize_prover_name",
    "prover_lazy_install_enabled",
    "reset_lazy_install_attempts",
    "ProverInstallEvent",
    "ProgressCallback",
]
