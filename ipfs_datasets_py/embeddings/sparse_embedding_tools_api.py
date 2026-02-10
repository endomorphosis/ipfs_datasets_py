"""Sparse embedding tool APIs (package-level).

Reusable core logic behind MCP-facing sparse embedding tools.
MCP wrappers should stay thin delegates that validate/dispatch/format.

Implementation note: This currently delegates to the existing implementation in
`ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
    generate_sparse_embedding as _generate_sparse_embedding,
    index_sparse_collection as _index_sparse_collection,
    manage_sparse_models as _manage_sparse_models,
    sparse_search as _sparse_search,
)


async def generate_sparse_embedding_from_parameters(
    *,
    text: str,
    model: str = "splade",
    top_k: int = 100,
    normalize: bool = True,
    return_dense: bool = False,
) -> Dict[str, Any]:
    return await _generate_sparse_embedding(
        text=text,
        model=model,
        top_k=top_k,
        normalize=normalize,
        return_dense=return_dense,
    )


async def index_sparse_collection_from_parameters(
    *,
    collection_name: str,
    dataset: str,
    split: str = "train",
    column: str = "text",
    models: Optional[List[str]] = None,
    batch_size: int = 100,
    index_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return await _index_sparse_collection(
        collection_name=collection_name,
        dataset=dataset,
        split=split,
        column=column,
        models=models or ["splade"],
        batch_size=batch_size,
        index_config=index_config,
    )


async def sparse_search_from_parameters(
    *,
    query: str,
    collection_name: str,
    model: str = "splade",
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    search_config: Optional[Dict[str, Any]] = None,
    explain_scores: bool = False,
) -> Dict[str, Any]:
    return await _sparse_search(
        query=query,
        collection_name=collection_name,
        model=model,
        top_k=top_k,
        filters=filters,
        search_config=search_config,
        explain_scores=explain_scores,
    )


async def manage_sparse_models_from_parameters(
    *,
    action: str,
    model_name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return await _manage_sparse_models(action=action, model_name=model_name, config=config)
