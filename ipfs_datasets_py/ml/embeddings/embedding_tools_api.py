"""Embedding tool APIs (package-level).

This module contains reusable core logic behind MCP-facing embedding tools.
MCP wrappers should stay thin delegates that validate/dispatch/format.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ipfs_datasets_py.mcp_server.validators import validator


async def generate_embedding_from_parameters(
    *,
    embedding_service: Any,
    text: str,
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
) -> Dict[str, Any]:
    if not text:
        raise ValueError("Text parameter is required")

    validated_text = validator.validate_text_input(text)
    validated_model = validator.validate_model_name(model)

    embedding = await embedding_service.generate_embedding(
        validated_text,
        validated_model,
        normalize,
    )

    return {
        "text": validated_text,
        "model": validated_model,
        "embedding": embedding,
        "dimension": len(embedding),
        "normalized": normalize,
    }


async def generate_batch_embeddings_from_parameters(
    *,
    embedding_service: Any,
    texts: List[str],
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 10,
) -> Dict[str, Any]:
    if not texts:
        raise ValueError("Texts parameter is required")
    if not isinstance(texts, list):
        raise ValueError("texts must be a list")

    validated_texts = [validator.validate_text_input(text) for text in texts]
    validated_model = validator.validate_model_name(model)
    validated_batch_size = validator.validate_batch_size(batch_size)

    embeddings = await embedding_service.generate_batch_embeddings(
        validated_texts,
        validated_model,
        normalize,
        validated_batch_size,
    )

    return {
        "texts": validated_texts,
        "model": validated_model,
        "embeddings": embeddings,
        "count": len(embeddings),
        "dimension": len(embeddings[0]) if embeddings else 0,
        "normalized": normalize,
        "batch_size": validated_batch_size,
    }


async def generate_multimodal_embedding_from_parameters(
    *,
    embedding_service: Any,
    content: Dict[str, Any],
    model: str = "clip-vit-base-patch32",
    fusion_strategy: str = "concatenate",
    normalize: bool = True,
) -> Dict[str, Any]:
    if not content:
        raise ValueError("Content parameter is required")
    if not isinstance(content, dict):
        raise ValueError("content must be a dictionary")

    validated_content: Dict[str, Any] = {}
    if "text" in content:
        validated_content["text"] = validator.validate_text_input(content["text"])

    if "image_url" in content:
        validated_content["image_url"] = validator.validate_url(content["image_url"])

    if "audio_url" in content:
        validated_content["audio_url"] = validator.validate_url(content["audio_url"])

    validated_model = validator.validate_model_name(model)
    validated_fusion_strategy = validator.validate_algorithm_choice(
        fusion_strategy,
        ["concatenate", "average", "weighted", "attention"],
    )

    embedding = await embedding_service.generate_multimodal_embedding(
        validated_content,
        validated_model,
        validated_fusion_strategy,
        normalize,
    )

    return {
        "content": validated_content,
        "model": validated_model,
        "embedding": embedding,
        "dimension": len(embedding),
        "fusion_strategy": validated_fusion_strategy,
        "normalized": normalize,
        "modalities": list(validated_content.keys()),
    }
