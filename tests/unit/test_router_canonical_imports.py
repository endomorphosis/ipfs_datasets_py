"""Architecture contracts for router ownership.

The historical ``ipfs_datasets_py`` paths must expose the exact canonical
``ipfs_accelerate_py`` module objects so provider registries, caches, traces,
and monkeypatches cannot diverge between packages.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("datasets_name", "accelerator_name"),
    [
        ("llm_router", "llm_router"),
        ("embeddings_router", "embeddings_router"),
        ("embedding_router", "embeddings_router"),
        ("multimodal_router", "multimodal_router"),
        ("voice_router", "voice_router"),
    ],
)
def test_datasets_router_is_canonical_accelerator_module(
    datasets_name: str,
    accelerator_name: str,
) -> None:
    datasets_router = importlib.import_module(
        f"ipfs_datasets_py.{datasets_name}"
    )
    accelerator_router = importlib.import_module(
        f"ipfs_accelerate_py.{accelerator_name}"
    )

    assert datasets_router is accelerator_router


def test_singular_accelerator_embedding_import_is_plural_canonical_module() -> None:
    singular = importlib.import_module("ipfs_accelerate_py.embedding_router")
    plural = importlib.import_module("ipfs_accelerate_py.embeddings_router")

    assert singular is plural
