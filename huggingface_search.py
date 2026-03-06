"""Compatibility shim for legacy top-level ``huggingface_search`` imports."""

from ipfs_datasets_py.processors.web_archiving.huggingface_search_engine import (
    batch_search_huggingface,
    get_huggingface_model_info,
    search_huggingface_datasets,
    search_huggingface_models,
    search_huggingface_spaces,
)

__all__ = [
    "search_huggingface_models",
    "search_huggingface_datasets",
    "search_huggingface_spaces",
    "get_huggingface_model_info",
    "batch_search_huggingface",
]
