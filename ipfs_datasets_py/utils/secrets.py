"""Lightweight secret resolution helpers.

This module intentionally returns only secret values requested by name. Callers
should avoid logging returned values; use :func:`has_secret` for diagnostics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


def _normalized_name(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _candidate_secret_files() -> list[Path]:
    paths: list[Path] = []
    for env_name in ("IPFS_DATASETS_PY_SECRETS_FILE", "IPFS_DATASETS_SECRETS_FILE"):
        value = str(os.getenv(env_name) or "").strip()
        if value:
            paths.append(Path(value).expanduser())

    xdg_config_home = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config").expanduser()
    paths.extend(
        [
            xdg_config_home / "ipfs_datasets_py" / "secrets.json",
            xdg_config_home / "ipfs_datasets" / "secrets.json",
            xdg_config_home / "secrets.json",
        ]
    )

    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _iter_json_values(payload: Any, *, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            joined = f"{prefix}.{key_text}" if prefix else key_text
            yield joined, value
            yield from _iter_json_values(value, prefix=joined)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _iter_json_values(value, prefix=f"{prefix}[{index}]")


def _value_from_json_file(path: Path, names: tuple[str, ...]) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    values = [
        (key, value)
        for key, value in _iter_json_values(payload)
        if not isinstance(value, (Mapping, list)) and value is not None
    ]
    for name in (str(item) for item in names if str(item or "").strip()):
        normalized_name = _normalized_name(name)
        for key, value in values:
            key_leaf = str(key).rsplit(".", 1)[-1]
            if key != name and key_leaf != name:
                if _normalized_name(key) != normalized_name and _normalized_name(key_leaf) != normalized_name:
                    continue
            text = str(value).strip()
            if text:
                return text
    return ""


def _value_from_config_files(names: tuple[str, ...]) -> str:
    for path in _candidate_secret_files():
        if not path.exists() or not path.is_file():
            continue
        value = _value_from_json_file(path, names)
        if value:
            return value
    return ""


def _value_from_vault(names: tuple[str, ...]) -> str:
    try:
        from ipfs_datasets_py.mcp_server.secrets_vault import get_secrets_vault

        vault = get_secrets_vault()
        for name in names:
            value = str(vault.get(name) or "").strip()
            if value:
                return value
    except Exception:
        return ""
    return ""


def _value_from_keyring(names: tuple[str, ...]) -> str:
    try:
        import keyring  # type: ignore
    except Exception:
        return ""

    service_names = ("ipfs_datasets_py", "ipfs-datasets-py", "ipfs_datasets")
    for service_name in service_names:
        for name in names:
            try:
                value = str(keyring.get_password(service_name, name) or "").strip()
            except Exception:
                continue
            if value:
                return value
    return ""


def resolve_secret(*names: str, explicit: Optional[str] = None) -> str:
    """Resolve a secret by name from explicit value, env, config, vault, or keyring.

    Search order is intentionally predictable: explicit argument, environment
    variables, ``~/.config/ipfs_datasets_py/secrets.json`` (plus overrides),
    the encrypted project vault, and finally the OS/Python keyring.
    """
    explicit_value = str(explicit or "").strip()
    if explicit_value:
        return explicit_value

    requested = tuple(str(name).strip() for name in names if str(name or "").strip())
    for name in requested:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value

    for resolver in (_value_from_config_files, _value_from_vault, _value_from_keyring):
        value = resolver(requested)
        if value:
            return value
    return ""


def has_secret(*names: str, explicit: Optional[str] = None) -> bool:
    """Return whether a secret can be resolved without exposing its value."""
    return bool(resolve_secret(*names, explicit=explicit))
