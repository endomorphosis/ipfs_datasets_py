"""
Multi-Model Embedding Generator for GraphRAG.

This module provides a comprehensive embedding generator that supports multiple
embedding models, model fusion, and IPFS integration for persistent storage.
It enables the generation of diverse vector representations for text data,
optimized for use in GraphRAG systems.

Key components:
- MultiModelEmbeddingGenerator: Generates embeddings using multiple models
- Integrated chunking strategies for processing long documents
- IPFS/IPLD integration for persistent storage of embeddings
- Model fusion capabilities for improved retrieval
- Accelerate integration for distributed inference
"""

import os
import json
import time
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple, Set, Type
from collections import defaultdict

import numpy as np

try:
    import torch
    from transformers import AutoTokenizer, AutoModel
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

# Try to import accelerate integration for distributed inference
try:
    from ..accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False}


class MultiModelEmbeddingGenerator:
    """
    Generates embeddings using multiple models for comprehensive representation.

    This class manages multiple embedding models to generate diverse vector
    representations of text, supporting different models for different types
    of embeddings (e.g., sentence, document, query-specific).

    Key features:
    - Support for multiple embedding models with different characteristics
    - Efficient chunking strategies for long documents
    - IPFS/IPLD integration for persistent storage of embeddings
    - Batched processing for efficiency
    - Model fusion capabilities
    """

    def __init__(
        self,
        model_configs: Optional[List[Dict[str, Any]]] = None,
        device: str = "cpu",
        cache_dir: Optional[str] = None,
        enable_model_fusion: bool = False,
        use_accelerate: bool = True
    ):
        """
        Initialize the embedding generator with multiple models.

        Args:
            model_configs: List of model configurations with format:
                [{"name": "model_name", "dimension": dim, "type": "model_type"}, ...]
                Default models will be used if not provided
            device: Device to run models on ("cpu", "cuda", "mps")
            cache_dir: Directory to cache models and tokenizers
            enable_model_fusion: Whether to enable model fusion for improved embeddings
            use_accelerate: Whether to use ipfs_accelerate_py for distributed inference
        """
        self.models = {}
        self.tokenizers = {}
        self.model_configs = model_configs or [
            {"name": "sentence-transformers/all-MiniLM-L6-v2", "dimension": 384, "type": "sentence"},
            {"name": "sentence-transformers/multi-qa-mpnet-base-dot-v1", "dimension": 768, "type": "qa"}
        ]
        self.device = device
        self.cache_dir = cache_dir
        self.enable_model_fusion = enable_model_fusion

        # Model loading and initialization statistics
        self.stats = {
            "models_loaded": 0,
            "embedding_requests": 0,
            "total_chunks_processed": 0,
            "average_embedding_time": 0.0,
            "total_embedding_time": 0.0,
            "embedding_errors": 0
        }

        # Initialize accelerate manager if available and enabled
        self.accelerate_manager = None
        self.use_accelerate = use_accelerate
        if HAVE_ACCELERATE and use_accelerate and is_accelerate_available():
            try:
                self.accelerate_manager = AccelerateManager(
                    resources={"device": device, "cache_dir": cache_dir},
                    enable_distributed=True
                )
                logging.info("✓ Accelerate integration enabled for distributed embedding generation")
            except Exception as e:
                logging.warning(f"⚠ Failed to initialize accelerate manager: {e}")
                self.accelerate_manager = None
        elif not HAVE_ACCELERATE or not is_accelerate_available():
            logging.info("⚠ Accelerate integration not available, using local inference only")

        # Load models if transformers is available
        if HAS_TRANSFORMERS:
            self._load_models()
        else:
            logging.warning("Transformers library not available. MultiModelEmbeddingGenerator will use fallback methods.")

    def _load_models(self):
        """Load the specified models and tokenizers."""
        for config in self.model_configs:
            model_name = config["name"]
            try:
                # Load tokenizer
                self.tokenizers[model_name] = AutoTokenizer.from_pretrained(
                    model_name,
                    cache_dir=self.cache_dir
                )

                # Load model
                self.models[model_name] = AutoModel.from_pretrained(
                    model_name,
                    cache_dir=self.cache_dir
                ).to(self.device)

                # Update stats
                self.stats["models_loaded"] += 1
                logging.info(f"Loaded model: {model_name}")

            except Exception as e:
                logging.error(f"Error loading model {model_name}: {str(e)}")
                self.stats["embedding_errors"] += 1

    def generate_embeddings(
        self,
        text: Union[str, List[str]],
        model_names: Optional[List[str]] = None,
        chunk_size: int = 512,
        overlap: int = 50,
        batch_size: int = 8,
        normalize: bool = True
    ) -> Dict[str, List[np.ndarray]]:
        """
        Generate embeddings for text using all configured models or specified models.

        Args:
            text: Text or list of texts to generate embeddings for
            model_names: List of model names to use; uses all if None
            chunk_size: Size of text chunks for processing
            overlap: Overlap between chunks
            batch_size: Batch size for processing
            normalize: Whether to normalize the embeddings to unit length

        Returns:
            Dictionary mapping model names to lists of embeddings
        """
        start_time = time.time()
        self.stats["embedding_requests"] += 1

        # Convert single text to list
        texts = [text] if isinstance(text, str) else text

        # Determine which models to use
        models_to_use = model_names or list(self.models.keys())
        models_to_use = [m for m in models_to_use if m in self.models]

        # Chunk texts
        all_chunks = []
        for text_item in texts:
            text_chunks = self._chunk_text(text_item, chunk_size, overlap)
            all_chunks.extend(text_chunks)

        self.stats["total_chunks_processed"] += len(all_chunks)

        # Generate embeddings for each model
        result = {}
        for model_name in models_to_use:
            try:
                embeddings = self._batch_encode(
                    model_name=model_name,
                    chunks=all_chunks,
                    batch_size=batch_size,
                    normalize=normalize
                )

                # Split embeddings for multiple texts if needed
                if len(texts) > 1:
                    result[model_name] = self._split_embeddings(embeddings, all_chunks, texts)
                else:
                    result[model_name] = embeddings

            except Exception as e:
                logging.error(f"Error generating embeddings with model {model_name}: {str(e)}")
                self.stats["embedding_errors"] += 1
                continue

        # Apply model fusion if enabled and multiple models used
        if self.enable_model_fusion and len(models_to_use) > 1:
            try:
                fused_embeddings = self._fuse_embeddings(result)
                result["fused"] = fused_embeddings
            except Exception as e:
                logging.error(f"Error during model fusion: {str(e)}")

        # Update timing stats
        embedding_time = time.time() - start_time
        self.stats["total_embedding_time"] += embedding_time
        embedding_count = self.stats["embedding_requests"]
        self.stats["average_embedding_time"] = self.stats["total_embedding_time"] / embedding_count

        return result

    def _chunk_text(
        self,
        text: str,
        chunk_size: int,
        overlap: int
    ) -> List[str]:
        """
        Split text into chunks with overlap.

        Args:
            text: Text to split
            chunk_size: Size of each chunk
            overlap: Overlap between chunks

        Returns:
            List of text chunks
        """
        # Split text into sentences or paragraphs
        if '\n\n' in text:
            segments = text.split('\n\n')
        else:
            # Simple sentence splitting - in production would use a more robust method
            segments = text.replace('. ', '.\n').split('\n')

        chunks = []
        current_chunk = ""

        for segment in segments:
            # If adding this segment exceeds chunk size, store current chunk and start a new one
            if len(current_chunk) + len(segment) > chunk_size:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # If segment is larger than chunk size, split it further
                if len(segment) > chunk_size:
                    words = segment.split()
                    temp_chunk = ""

                    for word in words:
                        if len(temp_chunk) + len(word) + 1 > chunk_size:
                            chunks.append(temp_chunk.strip())
                            # Include overlap from previous chunk
                            prev_words = temp_chunk.split()[-overlap:] if overlap > 0 else []
                            temp_chunk = " ".join(prev_words + [word])
                        else:
                            if temp_chunk:
                                temp_chunk += " "
                            temp_chunk += word

                    if temp_chunk:
                        current_chunk = temp_chunk
                else:
                    # Include overlap from previous chunk
                    if overlap > 0 and chunks:
                        prev_chunk = chunks[-1]
                        words = prev_chunk.split()[-overlap:]
                        current_chunk = " ".join(words) + " " + segment
                    else:
                        current_chunk = segment
            else:
                if current_chunk:
                    current_chunk += " "
                current_chunk += segment

        # Add the last chunk if not empty
        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _batch_encode(
        self,
        model_name: str,
        chunks: List[str],
        batch_size: int,
        normalize: bool
    ) -> List[np.ndarray]:
        """
        Encode text chunks in batches.

        Args:
            model_name: Name of model to use
            chunks: List of text chunks
            batch_size: Batch size for processing
            normalize: Whether to normalize embeddings

        Returns:
            List of embedding vectors
        """
        if not HAS_TRANSFORMERS:
            # Return random embeddings as fallback
            dimension = next(
                (config["dimension"] for config in self.model_configs if config["name"] == model_name),
                768  # Default dimension
            )
            return [np.random.rand(dimension) for _ in chunks]

        model = self.models[model_name]
        tokenizer = self.tokenizers[model_name]

        all_embeddings = []

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]

            # Tokenize
            inputs = tokenizer(
                batch_chunks,
                padding=True,
                truncation=True,
                return_tensors="pt"
            ).to(self.device)

            # Generate embeddings
            with torch.no_grad():
                outputs = model(**inputs)

            # Mean pooling
            attention_mask = inputs['attention_mask']
            embeddings = self._mean_pooling(outputs, attention_mask)

            # Normalize if requested
            if normalize:
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

            # Convert to numpy and add to results
            for embedding in embeddings:
                all_embeddings.append(embedding.cpu().numpy())

        return all_embeddings

    def _mean_pooling(self, model_output, attention_mask):
        """
        Perform mean pooling on token embeddings.

        Args:
            model_output: Output from the transformer model
            attention_mask: Attention mask from tokenizer

        Returns:
            Pooled embeddings
        """
        # Get token embeddings from the first (or last) hidden state
        token_embeddings = model_output[0]

        # Expand mask to match embedding dimensions
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()

        # Sum all token embeddings, weighted by attention mask
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)

        # Sum attention mask to get actual token count for each input
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)

        # Average embeddings by dividing by token count
        return sum_embeddings / sum_mask

    def _split_embeddings(
        self,
        embeddings: List[np.ndarray],
        chunks: List[str],
        texts: List[str]
    ) -> List[List[np.ndarray]]:
        """
        Split embeddings back to correspond to original texts.

        Args:
            embeddings: List of chunk embeddings
            chunks: List of all text chunks
            texts: Original list of texts

        Returns:
            List of embeddings lists, one per original text
        """
        # Count chunks per text
        text_to_chunks = {}
        current_index = 0

        for i, text in enumerate(texts):
            text_chunks = self._chunk_text(text, chunk_size=512, overlap=50)
            text_to_chunks[i] = len(text_chunks)
            current_index += len(text_chunks)

        # Split embeddings based on chunk counts
        result = []
        current_index = 0

        for i in range(len(texts)):
            chunk_count = text_to_chunks[i]
            text_embeddings = embeddings[current_index:current_index + chunk_count]
            result.append(text_embeddings)
            current_index += chunk_count

        return result

    def _fuse_embeddings(
        self,
        model_embeddings: Dict[str, List[np.ndarray]]
    ) -> List[np.ndarray]:
        """
        Fuse embeddings from multiple models.

        Args:
            model_embeddings: Dictionary of model name to embeddings

        Returns:
            List of fused embeddings
        """
        # Simple concatenation strategy - for text with multiple chunks, we fuse each chunk
        num_chunks = len(next(iter(model_embeddings.values())))
        fused = []

        for i in range(num_chunks):
            # Get embeddings for this chunk from all models
            chunk_embeddings = [
                embeddings[i] for model_name, embeddings in model_embeddings.items()
            ]

            # Normalize each embedding to have the same effect on the fusion
            normalized = [
                emb / np.linalg.norm(emb) for emb in chunk_embeddings if np.linalg.norm(emb) > 0
            ]

            # Concatenate for simple fusion
            if normalized:
                fused_vector = np.concatenate(normalized)

                # Normalize again
                norm = np.linalg.norm(fused_vector)
                if norm > 0:
                    fused_vector = fused_vector / norm

                fused.append(fused_vector)
            else:
                # Fallback if normalization fails
                fused.append(np.zeros(sum(emb.shape[0] for emb in chunk_embeddings)))

        return fused

    def store_on_ipfs(
        self,
        embeddings: Dict[str, List[np.ndarray]],
        metadata: Optional[Dict[str, Any]] = None,
        ipfs_client = None
    ) -> Dict[str, str]:
        """
        Store embeddings on IPFS using IPLD.

        Args:
            embeddings: Dictionary of model name to embeddings
            metadata: Additional metadata to store
            ipfs_client: Optional IPFS client instance

        Returns:
            Dictionary mapping model names to CIDs
        """
        if ipfs_client is None:
            logging.warning("IPFS client not provided. Generating CIDs locally.")
            # Generate local IDs as a mock
            return {
                model_name: f"bafy..{uuid.uuid4().hex[:16]}"
                for model_name in embeddings
            }

        result = {}
        metadata = metadata or {}

        for model_name, model_embeddings in embeddings.items():
            try:
                # Create IPLD block for each model's embeddings
                model_data = {
                    "model": model_name,
                    "dimension": len(model_embeddings[0]) if model_embeddings else 0,
                    "count": len(model_embeddings),
                    "embeddings": [emb.tolist() for emb in model_embeddings],
                    "metadata": metadata
                }

                # Add model-specific metadata
                for config in self.model_configs:
                    if config["name"] == model_name:
                        model_data["model_type"] = config.get("type", "unknown")
                        model_data["model_dimension"] = config.get("dimension", 0)
                        break

                # Store on IPFS
                block_data = json.dumps(model_data).encode()
                cid = ipfs_client.add_bytes(block_data)
                result[model_name] = cid

            except Exception as e:
                logging.error(f"Error storing embeddings for {model_name} on IPFS: {str(e)}")
                result[model_name] = f"error:{str(e)}"

        return result

    def load_from_ipfs(
        self,
        cids: Dict[str, str],
        ipfs_client = None
    ) -> Dict[str, List[np.ndarray]]:
        """
        Load embeddings from IPFS.

        Args:
            cids: Dictionary mapping model names to CIDs
            ipfs_client: Optional IPFS client instance

        Returns:
            Dictionary mapping model names to lists of embeddings
        """
        if ipfs_client is None:
            logging.error("IPFS client required to load embeddings from IPFS")
            return {}

        result = {}

        for model_name, cid in cids.items():
            try:
                # Get data from IPFS
                block_data = ipfs_client.get_bytes(cid)
                model_data = json.loads(block_data.decode())

                # Convert to numpy arrays
                embeddings = [np.array(emb) for emb in model_data["embeddings"]]
                result[model_name] = embeddings

            except Exception as e:
                logging.error(f"Error loading embeddings for {model_name} from IPFS: {str(e)}")

        return result

    def get_model_dimensions(self) -> Dict[str, int]:
        """
        Get dimensions for each model.

        Returns:
            Dictionary mapping model names to dimensions
        """
        return {
            config["name"]: config["dimension"]
            for config in self.model_configs
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the embedding generator.

        Returns:
            Dictionary of statistics
        """
        return self.stats

    @classmethod
    def from_config(cls, config_path: str) -> 'MultiModelEmbeddingGenerator':
        """
        Create a MultiModelEmbeddingGenerator from a configuration file.

        Args:
            config_path: Path to configuration file

        Returns:
            Configured MultiModelEmbeddingGenerator instance
        """
        with open(config_path, 'r') as f:
            config = json.load(f)

        return cls(
            model_configs=config.get("models", None),
            device=config.get("device", "cpu"),
            cache_dir=config.get("cache_dir", None),
            enable_model_fusion=config.get("enable_model_fusion", False)
        )
