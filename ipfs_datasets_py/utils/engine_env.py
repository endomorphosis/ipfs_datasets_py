"""Helpers for engine environment configuration.

This project integrates several optional "engine" backends (SymbolicAI neuro-symbolic
engine, embedding engine, search engine, etc.). Some upstream libraries (notably
SymbolicAI / `symai`) may emit warnings or even raise `SystemExit` if mandatory
environment variables are missing.

We do **not** prompt for secrets or hard-code API keys. Instead, we:

- Fill missing engine vars from existing well-known env vars (e.g. OPENAI_API_KEY).
- Optionally read from OS keyring if available.

This keeps installs reproducible while letting developers rely on existing auth
setups.
"""

from __future__ import annotations

import os
import pathlib
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional


def _get_from_keyring(service: str, name: str) -> Optional[str]:
    try:
        import keyring  # type: ignore
    except Exception:
        return None

    try:
        value = keyring.get_password(service, name)
    except Exception:
        return None

    if not value:
        return None
    return value


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _read_text_file(path: pathlib.Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return text or None


_OPENAI_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,})\b")


def _extract_openai_key(text: str) -> Optional[str]:
    if not text:
        return None
    # Fast path: exact key-like string.
    stripped = text.strip().strip('"\'')
    if stripped.startswith("sk-") and len(stripped) >= 24:
        return stripped

    match = _OPENAI_KEY_RE.search(text)
    if match:
        return match.group(1)
    return None


def _secret_from_file_env(*names: str) -> Optional[str]:
    """Reads a secret from a file path specified in one of the given env vars."""
    for name in names:
        file_path = os.environ.get(name)
        if not file_path:
            continue
        path = pathlib.Path(os.path.expanduser(file_path))
        if not path.is_file():
            continue
        text = _read_text_file(path)
        if text:
            return text
    return None


def _openai_key_from_common_files() -> Optional[str]:
    """Best-effort discovery of an OpenAI API key from common local config files.

    This is intentionally conservative: it only extracts an OpenAI-looking key token
    and never throws.
    """

    home = pathlib.Path.home()
    xdg_config = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))

    openai_dir = xdg_config / "openai"
    codex_dir = xdg_config / "codex"
    # npm scoped package configs sometimes land under '@openai/codex'
    codex_scoped_dir = xdg_config / "@openai" / "codex"

    candidates: Iterable[pathlib.Path] = (
        # Explicit common patterns
        home / ".openai_api_key",
        home / ".openai" / "auth.json",
        home / ".codex" / "auth.json",
        home / ".codex" / "config.json",
        home / ".codex" / "config.toml",
        # OpenAI CLI / SDK configs (best-effort)
        openai_dir / "api_key",
        openai_dir / "apikey",
        openai_dir / "auth.json",
        openai_dir / "credentials",
        openai_dir / "credentials.json",
        openai_dir / "config.json",
        openai_dir / ".env",
        # Codex CLI (npm @openai/codex) best-effort
        codex_dir / "auth.json",
        codex_dir / "config.json",
        codex_dir / "config.toml",
        codex_scoped_dir / "auth.json",
        codex_scoped_dir / "config.json",
        codex_scoped_dir / "config.toml",
    )

    for path in candidates:
        if not path.is_file():
            continue
        text = _read_text_file(path)
        if not text:
            continue
        key = _extract_openai_key(text)
        if key:
            return key

    return None


@dataclass(frozen=True)
class EngineEnvDefaults:
    neurosymbolic_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    search_model: str = "sonar"
    tts_model: str = "tts-1"
    drawing_model: str = "dall-e-3"
    vision_model: str = "openai/clip-vit-base-patch32"
    speech_to_text_model: str = "turbo"
    symbolic_engine: str = "wolframalpha"


def autoconfigure_engine_env(
    *,
    defaults: EngineEnvDefaults | None = None,
    keyring_service: str = "ipfs_datasets_py",
    allow_keyring: bool = True,
) -> Dict[str, str]:
    """Populate missing engine env vars from existing auth sources.

    Returns a dict of env vars that were set/modified.

    Precedence for values:
    1) Existing target env var (never overwritten)
    2) Related "common" env var (e.g. OPENAI_API_KEY)
    3) OS keyring value (if enabled)
    4) Default model names (for model vars only)
    """

    d = defaults or EngineEnvDefaults()
    changed: Dict[str, str] = {}

    def set_if_missing(name: str, value: Optional[str]) -> None:
        if os.environ.get(name):
            return
        if not value:
            return
        os.environ[name] = value
        # Avoid returning secrets in the changed dict; many callers log/print it.
        upper = name.upper()
        if any(marker in upper for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            changed[name] = "<set>"
        else:
            changed[name] = value

    def keyring_or_none(name: str) -> Optional[str]:
        if not allow_keyring:
            return None
        return _get_from_keyring(keyring_service, name)

    # Keys
    discovered_openai_key = (
        _first_env("OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_TOKEN")
        or _secret_from_file_env("OPENAI_API_KEY_FILE", "OPENAI_KEY_FILE")
        or keyring_or_none("OPENAI_API_KEY")
        or _openai_key_from_common_files()
    )

    # If we discover a common OpenAI key, expose it for other libraries too.
    set_if_missing("OPENAI_API_KEY", discovered_openai_key)
    openai_key = _first_env("OPENAI_API_KEY", "OPENAI_KEY")

    wolfram_key = _first_env("WOLFRAMALPHA_API_KEY")
    perplexity_key = _first_env("PERPLEXITY_API_KEY")
    pinecone_key = _first_env("PINECONE_API_KEY")
    apilayer_key = _first_env("APILAYER_API_KEY")

    set_if_missing(
        "NEUROSYMBOLIC_ENGINE_API_KEY",
        _first_env("NEUROSYMBOLIC_ENGINE_API_KEY")
        or _secret_from_file_env("NEUROSYMBOLIC_ENGINE_API_KEY_FILE")
        or openai_key
        or keyring_or_none("NEUROSYMBOLIC_ENGINE_API_KEY"),
    )
    set_if_missing(
        "EMBEDDING_ENGINE_API_KEY",
        _first_env("EMBEDDING_ENGINE_API_KEY")
        or _secret_from_file_env("EMBEDDING_ENGINE_API_KEY_FILE")
        or openai_key
        or keyring_or_none("EMBEDDING_ENGINE_API_KEY"),
    )
    set_if_missing(
        "TEXT_TO_SPEECH_ENGINE_API_KEY",
        _first_env("TEXT_TO_SPEECH_ENGINE_API_KEY")
        or _secret_from_file_env("TEXT_TO_SPEECH_ENGINE_API_KEY_FILE")
        or openai_key
        or keyring_or_none("TEXT_TO_SPEECH_ENGINE_API_KEY"),
    )
    set_if_missing(
        "DRAWING_ENGINE_API_KEY",
        _first_env("DRAWING_ENGINE_API_KEY")
        or _secret_from_file_env("DRAWING_ENGINE_API_KEY_FILE")
        or openai_key
        or keyring_or_none("DRAWING_ENGINE_API_KEY"),
    )
    set_if_missing(
        "SPEECH_TO_TEXT_API_KEY",
        _first_env("SPEECH_TO_TEXT_API_KEY")
        or _secret_from_file_env("SPEECH_TO_TEXT_API_KEY_FILE")
        or openai_key
        or keyring_or_none("SPEECH_TO_TEXT_API_KEY"),
    )

    set_if_missing(
        "SYMBOLIC_ENGINE_API_KEY",
        _first_env("SYMBOLIC_ENGINE_API_KEY")
        or _secret_from_file_env("SYMBOLIC_ENGINE_API_KEY_FILE")
        or wolfram_key
        or keyring_or_none("SYMBOLIC_ENGINE_API_KEY"),
    )
    set_if_missing(
        "SEARCH_ENGINE_API_KEY",
        _first_env("SEARCH_ENGINE_API_KEY")
        or _secret_from_file_env("SEARCH_ENGINE_API_KEY_FILE")
        or perplexity_key
        or keyring_or_none("SEARCH_ENGINE_API_KEY"),
    )
    set_if_missing(
        "INDEXING_ENGINE_API_KEY",
        _first_env("INDEXING_ENGINE_API_KEY")
        or _secret_from_file_env("INDEXING_ENGINE_API_KEY_FILE")
        or pinecone_key
        or keyring_or_none("INDEXING_ENGINE_API_KEY"),
    )
    set_if_missing(
        "OCR_ENGINE_API_KEY",
        _first_env("OCR_ENGINE_API_KEY")
        or _secret_from_file_env("OCR_ENGINE_API_KEY_FILE")
        or apilayer_key
        or keyring_or_none("OCR_ENGINE_API_KEY"),
    )

    # Models / engine selectors (safe defaults)
    set_if_missing(
        "NEUROSYMBOLIC_ENGINE_MODEL",
        _first_env("NEUROSYMBOLIC_ENGINE_MODEL", "OPENAI_MODEL")
        or keyring_or_none("NEUROSYMBOLIC_ENGINE_MODEL")
        or d.neurosymbolic_model,
    )
    set_if_missing(
        "EMBEDDING_ENGINE_MODEL",
        _first_env("EMBEDDING_ENGINE_MODEL")
        or keyring_or_none("EMBEDDING_ENGINE_MODEL")
        or d.embedding_model,
    )
    set_if_missing(
        "SEARCH_ENGINE_MODEL",
        _first_env("SEARCH_ENGINE_MODEL")
        or keyring_or_none("SEARCH_ENGINE_MODEL")
        or d.search_model,
    )
    set_if_missing(
        "TEXT_TO_SPEECH_ENGINE_MODEL",
        _first_env("TEXT_TO_SPEECH_ENGINE_MODEL")
        or keyring_or_none("TEXT_TO_SPEECH_ENGINE_MODEL")
        or d.tts_model,
    )
    set_if_missing(
        "DRAWING_ENGINE_MODEL",
        _first_env("DRAWING_ENGINE_MODEL")
        or keyring_or_none("DRAWING_ENGINE_MODEL")
        or d.drawing_model,
    )
    set_if_missing(
        "VISION_ENGINE_MODEL",
        _first_env("VISION_ENGINE_MODEL")
        or keyring_or_none("VISION_ENGINE_MODEL")
        or d.vision_model,
    )
    set_if_missing(
        "SPEECH_TO_TEXT_ENGINE_MODEL",
        _first_env("SPEECH_TO_TEXT_ENGINE_MODEL")
        or keyring_or_none("SPEECH_TO_TEXT_ENGINE_MODEL")
        or d.speech_to_text_model,
    )

    set_if_missing(
        "SYMBOLIC_ENGINE",
        _first_env("SYMBOLIC_ENGINE") or keyring_or_none("SYMBOLIC_ENGINE") or d.symbolic_engine,
    )

    # Pinecone environment is sometimes stored separately.
    set_if_missing(
        "INDEXING_ENGINE_ENVIRONMENT",
        _first_env("INDEXING_ENGINE_ENVIRONMENT", "PINECONE_ENVIRONMENT")
        or keyring_or_none("INDEXING_ENGINE_ENVIRONMENT"),
    )

    return changed
