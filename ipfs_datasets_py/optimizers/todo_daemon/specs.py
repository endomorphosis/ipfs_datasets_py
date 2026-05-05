"""Reusable env/path helpers for building managed todo-daemon specs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional


EnvMapping = Mapping[str, str]


def env_value(
    name: str,
    default: str,
    *,
    env: Optional[EnvMapping] = None,
) -> str:
    """Return an environment value, treating unset and empty as the default."""

    source = os.environ if env is None else env
    value = source.get(name)
    return default if value is None or value == "" else str(value)


def env_flag(
    name: str,
    default: str = "0",
    *,
    env: Optional[EnvMapping] = None,
) -> str:
    """Return a shell-friendly ``1``/``0`` value for a bool-ish environment variable."""

    value = env_value(name, default, env=env).strip().lower()
    return "1" if value in {"1", "true", "yes", "on"} else "0"


def repo_root_from_env(
    explicit: Optional[str] = None,
    *,
    env: Optional[EnvMapping] = None,
    cwd: Optional[Path] = None,
) -> Path:
    """Resolve a daemon repo root from an explicit arg, ``REPO_ROOT``, or cwd."""

    source = os.environ if env is None else env
    root = explicit or source.get("REPO_ROOT") or cwd or Path.cwd()
    return Path(root).resolve()


def env_path(
    name: str,
    default: str,
    *,
    env: Optional[EnvMapping] = None,
) -> Path:
    """Return an environment-backed path."""

    return Path(env_value(name, default, env=env))


def env_path_in_dir(
    name: str,
    directory: Path,
    filename: str,
    *,
    env: Optional[EnvMapping] = None,
) -> Path:
    """Return ``$name`` or ``directory / filename`` as a path."""

    return env_path(name, f"{directory.as_posix()}/{filename}", env=env)
