"""
LLM integration module for Omni Converter with OpenAI API integration.
Provides text generation, embeddings functionality, and utility methods for document processing.
"""
from ._async_interface import AsyncLLMInterface
from ._embeddings import EmbeddingsInterface
from .refactored_prompt_loader import PromptTemplate, load_prompt_by_name
from .factory import (
    make_llm_interface,
    make_embeddings_manager_instance,
    initialize_llm_components
)

__all__ = [
    "AsyncLLMInterface",
    "EmbeddingsInterface",
    "PromptTemplate",
    "load_prompt_by_name",
    "make_llm_interface",
    "make_embeddings_manager_instance",
    "initialize_llm_components"
]