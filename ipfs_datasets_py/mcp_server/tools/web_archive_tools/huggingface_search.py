"""HuggingFace Hub API search tools — thin MCP wrapper.

All domain logic lives at:
  ipfs_datasets_py.web_archiving.huggingface_search_engine
"""
from ipfs_datasets_py.web_archiving.huggingface_search_engine import (  # noqa: F401
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
