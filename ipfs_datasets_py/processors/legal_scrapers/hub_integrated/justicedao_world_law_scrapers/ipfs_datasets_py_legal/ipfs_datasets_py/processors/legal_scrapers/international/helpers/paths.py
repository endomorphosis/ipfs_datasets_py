"""Configurable roots for harvested official-gazette collectors."""

from __future__ import annotations

import os
from pathlib import Path

CORPORA_ROOT_ENV = "IPFS_DATASETS_LEGAL_CORPORA_ROOT"
COLLECTORS_ROOT_ENV = "IPFS_DATASETS_LEGAL_COLLECTORS_ROOT"
HF_TOKEN_PATH_ENV = "HF_TOKEN_PATH"
HF_TOKEN_ENV = "HF_TOKEN"


def default_data_root() -> Path:
    return (Path.home() / ".ipfs_datasets").resolve()


def corpora_root(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = str(os.environ.get(CORPORA_ROOT_ENV) or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (default_data_root() / "legal_corpora").resolve()


def collectors_root(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = str(os.environ.get(COLLECTORS_ROOT_ENV) or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (default_data_root() / "legal_collectors").resolve()


def huggingface_token_path() -> Path:
    env = str(os.environ.get(HF_TOKEN_PATH_ENV) or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".cache" / "huggingface" / "token").resolve()


def huggingface_token() -> str:
    env = str(os.environ.get(HF_TOKEN_ENV) or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if env:
        return env
    path = huggingface_token_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


__all__ = [
    "COLLECTORS_ROOT_ENV",
    "CORPORA_ROOT_ENV",
    "HF_TOKEN_ENV",
    "HF_TOKEN_PATH_ENV",
    "collectors_root",
    "corpora_root",
    "default_data_root",
    "huggingface_token",
    "huggingface_token_path",
]
