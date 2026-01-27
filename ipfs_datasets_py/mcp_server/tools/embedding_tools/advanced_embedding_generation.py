"""
Advanced Embedding Generation Tools with IPFS Embeddings Integration

Migrated and enhanced from endomorphosis/ipfs_embeddings_py to provide
production-ready embedding generation capabilities.
"""

from typing import List, Dict, Any, Optional, Union
import anyio
import os
import json
import logging
from pathlib import Path

# Import the core embeddings functionality
try:
    from ...embeddings.core import IPFSEmbeddings, PerformanceMetrics
    from ...embeddings.schema import EmbeddingModel, EmbeddingRequest, EmbeddingResponse
    HAVE_EMBEDDINGS = True
except ImportError as e:
    logging.warning(f"Embeddings core module not available: {e}")
    HAVE_EMBEDDINGS = False

logger = logging.getLogger(__name__)


async def generate_embedding(
    text: str,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 32,
    use_gpu: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate a single embedding for text using the integrated IPFS embeddings core.
    
    Args:
        text: Text to generate embedding for
        model_name: Name of the embedding model to use
        normalize: Whether to normalize the embedding vector
        batch_size: Batch size for processing
        use_gpu: Whether to use GPU acceleration
        **kwargs: Additional parameters for embedding generation
    
    Returns:
        Dict containing embedding results and metadata
    """
    try:
        if not HAVE_EMBEDDINGS:
            # Fallback to simple embedding for testing
            logger.warning("Using fallback embedding generation")
            return {
                "status": "success",
                "text": text,
                "embedding": [0.1, 0.2, 0.3, 0.4],  # Simple fallback
                "model": model_name,
                "dimension": 4,
                "normalized": normalize,
                "message": "Using fallback - install embeddings dependencies for full functionality"
            }
        
        # Validate input
        if not text or not isinstance(text, str):
            raise ValueError("Text must be a non-empty string")
        
        if len(text) > 10000:
            raise ValueError("Text length exceeds maximum limit of 10,000 characters")
        
        # Initialize embeddings engine
        embeddings_engine = IPFSEmbeddings(
            model=model_name,
            batch_size=batch_size,
            use_gpu=use_gpu
        )
        
        # Generate embedding
        result = await embeddings_engine.generate_embeddings([text])
        
        if not result or not result.get('embeddings'):
            raise RuntimeError("Failed to generate embedding")
        
        embedding = result['embeddings'][0]
        
        return {
            "status": "success",
            "text": text,
            "embedding": embedding.tolist() if hasattr(embedding, 'tolist') else embedding,
            "model": model_name,
            "dimension": len(embedding),
            "normalized": normalize,
            "processing_time": result.get('processing_time', 0),
            "memory_usage": result.get('memory_usage', 0)
        }
        
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "text": text,
            "model": model_name
        }


async def generate_batch_embeddings(
    texts: List[str],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 32,
    use_gpu: bool = False,
    max_texts: int = 100,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate embeddings for multiple texts in batch with optimization.
    
    Args:
        texts: List of texts to generate embeddings for
        model_name: Name of the embedding model to use
        normalize: Whether to normalize embedding vectors
        batch_size: Batch size for processing
        use_gpu: Whether to use GPU acceleration
        max_texts: Maximum number of texts to process in one call
        **kwargs: Additional parameters for embedding generation
    
    Returns:
        Dict containing batch embedding results and metadata
    """
    try:
        if not texts or not isinstance(texts, list):
            raise ValueError("Texts must be a non-empty list")
        
        if len(texts) > max_texts:
            raise ValueError(f"Number of texts ({len(texts)}) exceeds maximum limit of {max_texts}")
        
        # Validate each text
        for i, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Text at index {i} must be a non-empty string")
            if len(text) > 10000:
                raise ValueError(f"Text at index {i} exceeds maximum length of 10,000 characters")
        
        if not HAVE_EMBEDDINGS:
            # Fallback to simple embeddings for testing
            logger.warning("Using fallback batch embedding generation")
            embeddings = []
            for i, text in enumerate(texts):
                embeddings.append({
                    "text": text,
                    "embedding": [0.1 + i*0.01, 0.2 + i*0.01, 0.3 + i*0.01, 0.4 + i*0.01],
                    "index": i
                })
            return {
                "status": "success",
                "embeddings": embeddings,
                "model": model_name,
                "total_processed": len(texts),
                "count": len(texts),
                "batch_size": batch_size,
                "dimension": 4,
                "message": "Using fallback - install embeddings dependencies for full functionality"
            }
        
        # Initialize embeddings engine
        embeddings_engine = IPFSEmbeddings(
            model=model_name,
            batch_size=batch_size,
            use_gpu=use_gpu
        )
        
        # Generate batch embeddings
        result = await embeddings_engine.generate_embeddings(texts)
        
        if not result or not result.get('embeddings'):
            raise RuntimeError("Failed to generate batch embeddings")
        
        # Format results
        embeddings = []
        for i, (text, embedding) in enumerate(zip(texts, result['embeddings'])):
            embeddings.append({
                "text": text,
                "embedding": embedding.tolist() if hasattr(embedding, 'tolist') else embedding,
                "index": i
            })
        
        return {
            "status": "success",
            "embeddings": embeddings,
            "model": model_name,
            "total_processed": len(texts),
            "count": len(texts),
            "dimension": len(result['embeddings'][0]) if result['embeddings'] else 0,
            "processing_time": result.get('processing_time', 0),
            "memory_usage": result.get('memory_usage', 0),
            "batch_size": batch_size
        }
        
    except Exception as e:
        logger.error(f"Batch embedding generation failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "total_texts": len(texts) if texts else 0,
            "model": model_name
        }


async def generate_embeddings_from_file(
    file_path: str,
    output_path: Optional[str] = None,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 32,
    chunk_size: Optional[int] = None,
    max_length: Optional[int] = None,
    output_format: str = "json",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate embeddings from a text file with chunking and batch processing.
    
    Args:
        file_path: Path to input text file
        output_path: Path to save embeddings (optional)
        model_name: Name of the embedding model to use
        batch_size: Batch size for processing
        chunk_size: Size of text chunks (optional)
        max_length: Maximum text length per chunk
        output_format: Output format (json, parquet, hdf5)
        **kwargs: Additional parameters
    
    Returns:
        Dict containing file processing results and metadata
    """
    try:
        # Validate file path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")
        
        file_path = Path(file_path)
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        
        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
        
        if not content.strip():
            raise ValueError("File is empty or contains no valid text")
        
        # Process content based on format
        if file_path.suffix.lower() == '.json':
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    texts = [str(item) for item in data]
                elif isinstance(data, dict):
                    # Extract text fields from dict
                    texts = []
                    for key, value in data.items():
                        if isinstance(value, str):
                            texts.append(value)
                        elif isinstance(value, (list, dict)):
                            texts.append(json.dumps(value))
                else:
                    texts = [str(data)]
            except json.JSONDecodeError:
                # Treat as plain text
                texts = [content]
        else:
            # Split text into chunks if needed
            if chunk_size:
                texts = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
            else:
                texts = [content]
        
        # Apply max_length constraint
        if max_length:
            texts = [text[:max_length] for text in texts]
        
        # Generate embeddings
        result = await generate_batch_embeddings(
            texts, model_name, batch_size=batch_size, **kwargs
        )
        
        if result['status'] != 'success':
            return result
        
        # Save results if output path specified
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if output_format.lower() == 'json':
                with open(output_path, 'w') as f:
                    json.dump(result, f, indent=2)
            elif output_format.lower() == 'parquet':
                try:
                    import pandas as pd
                    df = pd.DataFrame(result['embeddings'])
                    df.to_parquet(output_path)
                except ImportError:
                    logger.warning("Pandas not available, saving as JSON instead")
                    with open(output_path.with_suffix('.json'), 'w') as f:
                        json.dump(result, f, indent=2)
        
        return {
            **result,
            "input_file": str(file_path),
            "output_file": str(output_path) if output_path else None,
            "output_format": output_format,
            "total_chunks": len(texts)
        }
        
    except Exception as e:
        logger.error(f"File embedding generation failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": file_path,
            "model": model_name
        }


# Export the main functions for MCP integration
__all__ = [
    'generate_embedding',
    'generate_batch_embeddings', 
    'generate_embeddings_from_file'
]
