# """
# LLM integration module for American Law database with OpenAI API integration.
# Provides RAG components and embeddings functionality.
# """
# from .async_interface import AsyncLLMInterface
# from .embeddings import EmbeddingsInterface
# from .dependencies.async_openai_client import AsyncOpenAIClient

# __all__ = [
#     "AsyncLLMInterface",
#     "EmbeddingsInterface",
#     "AsyncOpenAIClient"
# ]
from .factory import make_llm_components

__all__ = [
    "make_llm_components",
]