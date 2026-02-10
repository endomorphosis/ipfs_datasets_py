"""
MCP Server Tool: Generate Embeddings

Generate vector embeddings from a file using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter.exports import generate_embeddings_sync


async def generate_embeddings_tool(
    input_path: str,
    embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2',
    vector_store: str = 'faiss',
    enable_ipfs: bool = False,
    enable_acceleration: bool = False
) -> dict:
    """
    Generate vector embeddings from a file or URL.
    
    Args:
        input_path: Path to file or URL
        embedding_model: Embedding model to use
        vector_store: Vector store type ('faiss', 'qdrant', 'elasticsearch')
        enable_ipfs: Whether to store results on IPFS
        enable_acceleration: Whether to use ML acceleration (GPU/TPU)
    
    Returns:
        Dict with embedding_count, vector_store_ids, and success status
    
    Example:
        result = await generate_embeddings_tool('document.pdf')
        result = await generate_embeddings_tool('corpus.zip', vector_store='qdrant', enable_ipfs=True)
    """
    return generate_embeddings_sync(input_path, embedding_model, vector_store, enable_ipfs, enable_acceleration)


# Tool metadata for MCP server
TOOL_NAME = "generate_embeddings"
TOOL_DESCRIPTION = "Generate vector embeddings from a file or URL"
TOOL_CATEGORY = "file_converter_tools"
