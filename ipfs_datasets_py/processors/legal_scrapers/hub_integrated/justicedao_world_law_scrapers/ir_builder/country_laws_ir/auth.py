"""Public Hugging Face reads only. This pipeline never loads, stores, or uses a token."""

from __future__ import annotations

import os


def configure_hf() -> None:
    """Force anonymous public Hub access. Tokens are ignored, never printed, never stored."""
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    # Do not read HF_TOKEN / HUGGING_FACE_HUB_TOKEN. Public datasets need no auth.


def public_token() -> bool:
    """huggingface_hub `token=False` means anonymous (do not pick up env tokens)."""
    return False
