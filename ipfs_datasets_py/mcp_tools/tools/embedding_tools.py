# src/mcp_server/tools/embedding_tools.py

import logging
from typing import Dict, Any, List, Optional, Union
from ipfs_datasets_py.mcp_tools.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.mcp_tools.validators import validator

logger = logging.getLogger(__name__)

class EmbeddingGenerationTool(ClaudeMCPTool):
    """
    Tool for generating embeddings from text using various models.
    """
    
    def __init__(self, embedding_service):
        super().__init__()
        if embedding_service is None:
            raise ValueError("Embedding service cannot be None")
        
        self.name = "generate_embedding"
        self.description = "Generates an embedding vector for a given text using specified model."
        self.input_schema = {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to generate an embedding for.",
                    "minLength": 1,
                    "maxLength": 10000
                },
                "model": {
                    "type": "string", 
                    "description": "The model to use for embedding generation.",
                    "default": "sentence-transformers/all-MiniLM-L6-v2"
                },
                "normalize": {
                    "type": "boolean",
                    "description": "Whether to normalize the embedding vector.",
                    "default": True
                }
            },
            "required": ["text"]
        }
        self.embedding_service = embedding_service
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute embedding generation."""
        try:
            # Extract parameters
            text = parameters.get("text")
            model = parameters.get("model", "sentence-transformers/all-MiniLM-L6-v2")
            normalize = parameters.get("normalize", True)
            
            # Validate inputs
            if not text:
                raise ValueError("Text parameter is required")
            text = validator.validate_text_input(text)
            model = validator.validate_model_name(model)
            
            # Call the embedding service
            embedding = await self.embedding_service.generate_embedding(text, model, normalize)
            
            return {
                "text": text,
                "model": model,
                "embedding": embedding,
                "dimension": len(embedding),
                "normalized": normalize
            }
            
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise

class BatchEmbeddingTool(ClaudeMCPTool):
    """
    Tool for generating embeddings for multiple texts in batch.
    """
    
    def __init__(self, embedding_service):
        super().__init__()
        if embedding_service is None:
            raise ValueError("Embedding service cannot be None")
            
        self.name = "generate_batch_embeddings"
        self.description = "Generates embeddings for multiple texts in an efficient batch operation."
        self.input_schema = {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 10000
                    },
                    "description": "List of texts to generate embeddings for.",
                    "minItems": 1,
                    "maxItems": 100
                },
                "model": {
                    "type": "string",
                    "description": "The model to use for embedding generation.",
                    "default": "sentence-transformers/all-MiniLM-L6-v2"
                },
                "normalize": {
                    "type": "boolean",
                    "description": "Whether to normalize the embedding vectors.",
                    "default": True
                },
                "batch_size": {
                    "type": "integer",
                    "description": "Number of texts to process in each batch.",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                }
            },
            "required": ["texts"]
        }
        self.embedding_service = embedding_service
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute batch embedding generation."""
        try:
            # Extract parameters
            texts = parameters.get("texts")
            model = parameters.get("model", "sentence-transformers/all-MiniLM-L6-v2")
            normalize = parameters.get("normalize", True)
            batch_size = parameters.get("batch_size", 10)
            
            # Validate inputs
            if not texts:
                raise ValueError("Texts parameter is required")
            if not isinstance(texts, list):
                raise ValueError("texts must be a list")
            
            validated_texts = [validator.validate_text_input(text) for text in texts]
            model = validator.validate_model_name(model)
            batch_size = validator.validate_batch_size(batch_size)
            
            # Call the embedding service
            embeddings = await self.embedding_service.generate_batch_embeddings(
                validated_texts, model, normalize, batch_size
            )
            
            return {
                "texts": validated_texts,
                "model": model,
                "embeddings": embeddings,
                "count": len(embeddings),
                "dimension": len(embeddings[0]) if embeddings else 0,
                "normalized": normalize,
                "batch_size": batch_size
            }
            
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            raise

class MultimodalEmbeddingTool(ClaudeMCPTool):
    """
    Tool for generating embeddings from multimodal content (text, images, audio).
    """
    
    def __init__(self, embedding_service):
        super().__init__()
        if embedding_service is None:
            raise ValueError("Embedding service cannot be None")
            
        self.name = "generate_multimodal_embedding"
        self.description = "Generates embeddings from multimodal content including text, images, and audio."
        self.input_schema = {
            "type": "object",
            "properties": {
                "content": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text content to embed."
                        },
                        "image_url": {
                            "type": "string",
                            "description": "URL or file path to image content."
                        },
                        "audio_url": {
                            "type": "string", 
                            "description": "URL or file path to audio content."
                        }
                    },
                    "description": "Multimodal content to generate embeddings for.",
                    "minProperties": 1
                },
                "model": {
                    "type": "string",
                    "description": "The multimodal model to use.",
                    "default": "clip-vit-base-patch32"
                },
                "fusion_strategy": {
                    "type": "string",
                    "enum": ["concatenate", "average", "weighted", "attention"],
                    "description": "Strategy for fusing multimodal embeddings.",
                    "default": "concatenate"
                },
                "normalize": {
                    "type": "boolean",
                    "description": "Whether to normalize the final embedding.",
                    "default": True
                }
            },
            "required": ["content"]
        }
        self.embedding_service = embedding_service
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute multimodal embedding generation."""
        try:
            # Extract parameters
            content = parameters.get("content")
            model = parameters.get("model", "clip-vit-base-patch32")
            fusion_strategy = parameters.get("fusion_strategy", "concatenate")
            normalize = parameters.get("normalize", True)
            
            # Validate inputs
            if not content:
                raise ValueError("Content parameter is required")
            if not isinstance(content, dict):
                raise ValueError("content must be a dictionary")
            
            if not content:
                raise ValueError("content cannot be empty")
            
            # Validate content fields
            validated_content = {}
            if "text" in content:
                validated_content["text"] = validator.validate_text_input(content["text"])
            
            if "image_url" in content:
                validated_content["image_url"] = validator.validate_url(content["image_url"])
            
            if "audio_url" in content:
                validated_content["audio_url"] = validator.validate_url(content["audio_url"])
            
            model = validator.validate_model_name(model)
            fusion_strategy = validator.validate_algorithm_choice(
                fusion_strategy, ["concatenate", "average", "weighted", "attention"]
            )
            
            # Call the multimodal embedding service
            embedding = await self.embedding_service.generate_multimodal_embedding(
                validated_content, model, fusion_strategy, normalize
            )
            
            return {
                "content": validated_content,
                "model": model,
                "embedding": embedding,
                "dimension": len(embedding),
                "fusion_strategy": fusion_strategy,
                "normalized": normalize,
                "modalities": list(validated_content.keys())
            }
            
        except Exception as e:
            logger.error(f"Multimodal embedding generation failed: {e}")
            raise
