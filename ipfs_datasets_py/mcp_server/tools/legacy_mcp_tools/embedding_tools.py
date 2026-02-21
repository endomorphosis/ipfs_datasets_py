# src/mcp_server/tools/embedding_tools.py
# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.embedding_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.embedding_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.embedding_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (  # noqa: F401, E402
    generate_embedding,
    generate_batch_embeddings,
    generate_embeddings_from_file,
    EmbeddingGenerationTool,
    BatchEmbeddingTool,
    get_available_tools,
)

__all__ = [
    "generate_embedding",
    "generate_batch_embeddings",
    "generate_embeddings_from_file",
    "EmbeddingGenerationTool",
    "BatchEmbeddingTool",
    "get_available_tools",
]
