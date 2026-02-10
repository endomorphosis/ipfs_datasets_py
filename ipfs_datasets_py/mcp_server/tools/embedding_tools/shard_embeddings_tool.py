
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.embeddings.shard_embeddings_tools_api import (
	merge_shards_from_parameters,
	shard_embeddings_from_parameters,
	shard_info_from_parameters,
)


async def shard_embeddings_tool(
	embeddings: List[Any],
	shard_count: int = 4,
	strategy: str = "balanced",
	**kwargs: Any,
) -> Dict[str, Any]:
	"""Shard an in-memory list of embeddings into N shards."""

	return await shard_embeddings_from_parameters(
		embeddings=embeddings,
		shard_count=shard_count,
		strategy=strategy,
		**kwargs,
	)


async def merge_shards_tool(
	manifest_file: str,
	output_file: str,
	merge_strategy: str = "sequential",
	**kwargs: Any,
) -> Dict[str, Any]:
	"""Merge shards based on an on-disk sharding manifest."""

	return await merge_shards_from_parameters(
		manifest_file=manifest_file,
		output_file=output_file,
		merge_strategy=merge_strategy,
		**kwargs,
	)


async def shard_info_tool(
	shards: Optional[List[Dict[str, Any]]] = None,
	manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
	"""Return summary info for shards or a manifest."""

	return await shard_info_from_parameters(shards=shards, manifest=manifest)

