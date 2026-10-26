"""Hugging Face auth helpers.

Default reads stay anonymous. Gap scans and JusticeDAO uploads may use the
operator token from the Hugging Face cache file or the environment. The token
is never logged.
"""

from __future__ import annotations

import os
from pathlib import Path


def configure_hf() -> None:
    """Do not implicitly pick up ambient tokens for anonymous public reads."""
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")


def public_token() -> bool:
    """huggingface_hub `token=False` means anonymous (do not pick up env tokens)."""
    return False


def operator_token() -> str | bool:
    """Return a token for authenticated Hub reads/writes, or False if none."""
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    path = Path.home() / ".cache" / "huggingface" / "token"
    if path.is_file():
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if value:
            return value
    return False
