"""Opt-in lazy installer for external theorem prover dependencies.

The prover bridges import cleanly without installing anything.  When a bridge
is explicitly requested and its dependency is missing, this module can perform
a single best-effort install attempt when enabled by environment variables.

Environment variables:
- IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 enables requested-prover installs.
- IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>=0/1 overrides a prover.
- IPFS_DATASETS_PY_LAZY_INSTALL_STRICT=1 raises on installer failure.
- IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS=1 permits interactive sudo for Coq.
- IPFS_DATASETS_PY_ERGOAI_GIT_URL overrides the ErgoAI/ErgoEngine source repo.
- IPFS_DATASETS_PY_ERGOAI_RELEASE_URL overrides the official ErgoAI .run URL.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR sets the user-local ErgoAI install dir.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND runs a custom ErgoAI installer command.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
from pathlib import Path

from ipfs_datasets_py.logic.common.feature_detection import (
    clear_feature_detection_cache,
    minimal_imports_enabled,
)

logger = logging.getLogger(__name__)

_ATTEMPTED: set[str] = set()

_ALIASES = {
    "z3": "z3",
    "cvc5": "cvc5",
    "lean": "lean",
    "lake": "lean",
    "coq": "coq",
    "coqc": "coq",
    "coqtop": "coq",
    "symbolicai": "symbolicai",
    "symbolic_ai": "symbolicai",
    "symai": "symbolicai",
    "ergo": "ergoai",
    "ergoai": "ergoai",
    "ergo_ai": "ergoai",
    "ergoengine": "ergoai",
    "ergo_engine": "ergoai",
    "runergo": "ergoai",
    "runergo.sh": "ergoai",
}

_ENV_NAMES = {
    "z3": "Z3",
    "cvc5": "CVC5",
    "lean": "LEAN",
    "coq": "COQ",
    "symbolicai": "SYMBOLICAI",
    "ergoai": "ERGOAI",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_prover_name(prover_name: str) -> str:
    """Return the canonical lazy-installer name for a prover."""

    normalized = str(prover_name or "").strip().lower().replace("-", "_")
    return _ALIASES.get(normalized, normalized)


def _common_bin_dirs() -> list[Path]:
    try:
        home = Path.home()
    except (OSError, RuntimeError):
        return []
    return [
        home / ".local" / "bin",
        home / ".elan" / "bin",
        home / ".opam" / "default" / "bin",
    ]


def find_executable(command: str) -> str | None:
    """Find a prover executable on PATH or in common user-local install dirs."""

    found = shutil.which(command)
    if found:
        return found

    for directory in _common_bin_dirs():
        candidate = directory / command
        try:
            if candidate.exists() and os.access(str(candidate), os.X_OK):
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

    # Keep Coq conservative by default; it usually needs a system package
    # manager or a lengthy opam build.  The installer itself still refuses
    # interactive sudo unless the caller opts in.
    if prover == "coq":
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
) -> bool:
    """Try to install a prover dependency once, if lazy installs are enabled."""

    prover = normalize_prover_name(prover_name)
    if not prover_lazy_install_enabled(prover):
        return False

    if prover in _ATTEMPTED and not force:
        return False

    _ATTEMPTED.add(prover)
    strict = lazy_install_strict() if strict is None else strict

    try:
        from ipfs_datasets_py.logic.integration.bridges import prover_installer

        ensure = getattr(prover_installer, f"ensure_{prover}", None)
        if ensure is None:
            logger.debug("No lazy installer is registered for prover %s", prover)
            return False

        kwargs = {"yes": True, "strict": strict}
        if prover == "coq":
            kwargs["allow_sudo"] = _truthy(
                os.environ.get("IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS")
            )

        logger.info(
            "Attempting lazy install for %s%s",
            prover,
            f" ({reason})" if reason else "",
        )
        ok = bool(ensure(**kwargs))
        importlib.invalidate_caches()
        clear_feature_detection_cache()
        return ok
    except Exception:
        logger.exception("Lazy install failed for prover %s", prover)
        if strict:
            raise
        return False


def reset_lazy_install_attempts() -> None:
    """Clear the per-process lazy-install attempt cache."""

    _ATTEMPTED.clear()


__all__ = [
    "find_executable",
    "lazy_install_prover",
    "lazy_install_strict",
    "lazy_installs_enabled",
    "normalize_prover_name",
    "prover_lazy_install_enabled",
    "reset_lazy_install_attempts",
]
