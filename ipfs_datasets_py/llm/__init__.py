"""LLM package.

This package contains GraphRAG-oriented LLM utilities (prompt libraries,
semantic validation, reasoning tracing) and bridges to runtime LLM backends.

The primary integration point is `LLMInterfaceFactory.create()`, which will
produce a mock implementation by default, or a router-backed implementation
when a real provider/model is configured (see env vars in `ipfs_datasets_py.llm_router`).
"""

from .llm_interface import (
	LLMConfig,
	LLMInterface,
	LLMInterfaceFactory,
	MockLLMInterface,
	PromptTemplate,
	PromptLibrary,
	AdaptivePrompting,
	GraphRAGPromptTemplates,
)

from .llm_router_interface import RoutedLLMInterface

