"""
Asynchronous LLM interface for text generation and embeddings.
Provides a unified API for interacting with language models through dependency injection.
"""
import os
from pathlib import Path
from typing import Any, Callable, Optional, Union

try:
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError(
        "Pydantic is required for this module. Please install it with 'pip install pydantic'."
    )

from logger import logger


class AsyncLLMInterface:
    """
    Asynchronous interface for interacting with language models.
    Provides a simplified API for text generation and embeddings functionality.
    """

    def __init__(
        self,
        resources: dict[str, Any] = None,
        configs: Optional[dict[str, Any]] = None
    ):
        """
        Initialize the async LLM interface with dependency injection.
        
        Args:
            resources: Dictionary of resources including client and processor functions
            configs: Configuration parameters for the interface
        """
        self.resources = resources
        self.configs = configs

        self.model = self.configs["model"]
        self.embedding_model = self.configs["embedding_model"]
        self.temperature = self.configs["temperature"]
        self.max_tokens = self.configs["max_tokens"]
        self.prompts_dir = self.configs["prompts_dir"]

        self._async_client = self.resources["async_client"]
        self._generate_text = self.resources["generate_text"]
        self._generate_embeddings = self.resources["generate_embeddings"]
        self._calculate_cost = self.resources["calculate_cost"]

        # Track API usage
        self._total_tokens = 0
        self._total_cost = 0.0

        logger.info(f"Initialized AsyncLLMInterface with model: {self.model}")

    async def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = "You are a helpful assistant specialized in document conversion.",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Generate a response using the configured language model.
        
        Args:
            prompt: User prompt text
            system_prompt: System prompt text (uses default if None)
            temperature: Temperature for generation (uses default if None)
            max_tokens: Maximum tokens to generate (uses default if None)
            model: Model to use for generation (uses default if None)
            
        Returns:
            Dictionary with the generated response and metadata
        """
        # Use defaults if parameters not provided
        sys_prompt = system_prompt 
        temp = temperature or self.temperature
        tokens = max_tokens or self.max_tokens
        model_name = model or self.model

        logger.info(f"Generating response for prompt: {prompt[:50]}...")

        try:
            # Generate text using injected function
            response_text = await self._generate_text(
                client=self._async_client,
                prompt=prompt,
                system_prompt=sys_prompt,
                model=model_name,
                temperature=temp,
                max_tokens=tokens
            )
            
            # Calculate cost if function available
            cost = None
            cost = self._calculate_cost(
                prompt=prompt, 
                completion=response_text or "", 
                model=model_name
            )
            if cost is not None:
                self.total_cost += cost
            
            # Build response dictionary
            result = {
                "prompt": prompt,
                "response": response_text,
                "model": model_name,
                "cost": cost
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return {
                "prompt": prompt,
                "response": None,
                "model": model_name,
                "error": str(e)
            }
    
    async def generate_embedding(
        self,
        text: str,
        model: Optional[str] = None
    ) -> Optional[list[float]]:
        """
        Generate an embedding vector for a text.
        
        Args:
            text: Text to generate embedding for
            model: Embedding model to use (uses default if None)
            
        Returns:
            Embedding vector or None if generation failed
        """
        if not self._generate_embeddings:
            logger.error("Embedding generation not available - missing resource")
            return None
        
        model_name = model or self.embedding_model
        
        try:
            embeddings = await self._generate_embeddings(
                client=self._async_client,
                texts=text,
                model=model_name
            )
            
            if embeddings and len(embeddings) > 0:
                return embeddings[0]
            return None
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    async def summarize_text(
        self,
        text: str,
        max_length: Optional[int] = None,
        format_type: Optional[str] = None
    ) -> Optional[str]:
        """
        Summarize a text using the configured language model.
        
        Args:
            text: Text to summarize
            max_length: Maximum length of summary in characters
            format_type: Format of the summary (bullet points, paragraph, etc.)
            
        Returns:
            Summarized text or None if generation failed
        """
        # Prepare prompt based on format type
        format_instruction = ""
        match format_type:
            case "bullet":
                format_instruction = "Format the summary as bullet points."
            case "paragraph":
                format_instruction = "Format the summary as a single paragraph."
            case _:
                pass

        # Prepare max length instruction
        length_instruction = ""
        if max_length:
            length_instruction = f"Keep the summary under {max_length} characters."
        
        # Create system prompt
        system_prompt = (
            "You are a document summarization assistant. "
            "Create a concise summary that captures the key information. "
            f"{format_instruction} {length_instruction}"
        ).strip()
        
        # Create user prompt
        prompt = f"Summarize the following text:\n\n{text}"
        
        # Generate summary
        result = await self.generate_response(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3,  # Lower temperature for more focused summary
            max_tokens=self.max_tokens
        )
        
        return result.get("response")
    
    async def extract_metadata(
        self,
        text: str,
        metadata_fields: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """
        Extract metadata from text using the configured language model.
        
        Args:
            text: Text to extract metadata from
            metadata_fields: Specific fields to extract (extracts common fields if None)
            
        Returns:
            Dictionary of extracted metadata
        """
        # Default fields if none provided
        fields = metadata_fields or [
            "title", "author", "date", "subject", "keywords", 
            "language", "source", "document_type"
        ]
        
        # Create field list for prompt
        field_list = "\n".join([f"- {field}" for field in fields])
        
        # Create system prompt
        system_prompt = (
            "You are a metadata extraction assistant. Extract the requested metadata "
            "fields from the provided text. Return ONLY the extracted information in "
            "a clear key: value format. If a field cannot be determined, use 'Unknown' "
            "as the value."
        )
        
        # Create user prompt
        prompt = f"Extract the following metadata fields from the text:\n{field_list}\n\nText:\n{text[:2000]}..."
        
        # Generate extraction
        result = await self.generate_response(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.1,  # Very low temperature for consistent formatting
            max_tokens=500  # Metadata should be concise
        )
        
        # Process the response into a dictionary
        metadata = {}
        if result.get("response"):
            lines = result["response"].strip().split("\n")
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip().lower()] = value.strip()
        
        return metadata


