"""
Factory functions for creating and configuring LLM components.
Provides a unified API for initializing LLM interfaces and resources.
"""
import os
from pathlib import Path
from typing import Any, Optional

from configs import configs
from logger import logger
from types_ import Configs, Content, Logger
import utils.llm.dependencies._openai_dependency as openai_
import utils.llm.dependencies._anthropic_dependency as anthropic_
import utils.llm.dependencies._torch_dependency as torch_


from ._async_interface import AsyncLLMInterface
from ._embeddings import EmbeddingsInterface
from .refactored_prompt_loader import load_prompt_by_name

from configs import configs
from dependencies import dependencies

def create_llm_resources() -> dict[str, Any]:
    """
    Create a resources dictionary with LLM components.

    Args:
        api_key: OpenAI API key (uses environment variable if not provided)
        model: Model to use for text generation
        embedding_model: Model to use for embeddings
        embedding_dimensions: Dimensions of embedding vectors
        
    Returns:
        Dictionary of LLM resources
    """
    resources = {}
    _client = None
    _generate_text = None
    _generate_embeddings = None
    _calculate_cost = None
    
    # Check if OpenAI is available
    if not openai_.check_if_available():
        # Create OpenAI async client
        _client = openai_.create_async_openai_client
        _generate_text = openai_.generate_text
        _generate_embeddings = openai_.generate_embeddings
        _calculate_cost = openai_.calculate_cost

    elif not anthropic_.check_if_available(): 
        _client = anthropic_.create_async_anthropic_client
        _generate_text = anthropic_.generate_text
        # NOTE Anthropic client does not support embedding generation,
        # so we use other library's embeddings if available
        if openai_.check_if_available():
            # Use OpenAI for embeddings if available
            _generate_embeddings = openai_.generate_embeddings
        elif torch_.check_if_available():
            # Use Torch for embeddings if available
            _generate_embeddings = torch_.generate_embeddings
        _calculate_cost = anthropic_.calculate_cost

    elif not torch_.check_if_available():
        _client = torch_.create_async_torch_client
        _generate_text = torch_.generate_text
        _generate_embeddings = torch_.generate_embeddings
        _calculate_cost = torch_.calculate_cost

    # Add resources to dictionary
    resources["async_client"] = _client
    resources["generate_text"] = _generate_text
    resources["generate_embeddings"] = _generate_embeddings
    resources["calculate_cost"] = _calculate_cost

    return resources


def make_llm_interface(
    configs: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None
) -> Optional[AsyncLLMInterface]:
    """
    Create a configured AsyncLLMInterface instance.
    
    Args:
        configs: Configuration parameters
        api_key: OpenAI API key (uses environment variable if not provided)
        
    Returns:
        Configured AsyncLLMInterface instance or None if creation failed
    """
    # Use default configs if none provided
    config_params = configs or {}
    
    # Get model configurations
    model = config_params.get("model", "gpt-3.5-turbo")
    embedding_model = config_params.get("embedding_model", "text-embedding-ada-002")
    embedding_dimensions = config_params.get("embedding_dimensions", 1536)

    # Create resources
    resources = create_llm_resources(
        api_key=api_key,
        model=model,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions
    )

    # Check if required resources are available
    if "async_client" not in resources or "generate_text" not in resources:
        logger.error("Required LLM resources not available. Cannot create interface.")
        return None

    try:
        # Create interface with resources and configs
        interface = create_async_llm_interface(
            resources=resources,
            configs=config_params
        )
        return interface
    except Exception as e:
        logger.error(f"Error creating LLM interface: {e}")
        return None


def make_embeddings_manager(
    configs: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None
) -> Optional[EmbeddingsInterface]:
    """
    Create a configured EmbeddingsInterface instance.
    
    Args:
        configs: Configuration parameters
        api_key: OpenAI API key (uses environment variable if not provided)
        
    Returns:
        Configured EmbeddingsInterface instance or None if creation failed
    """
    # Use default configs if none provided
    config_params = configs or {}
    
    # Get embedding configurations
    embedding_model = config_params.get("embedding_model", "text-embedding-ada-002")
    embedding_dimensions = config_params.get("embedding_dimensions", 1536)
    
    # Create resources
    resources = create_llm_resources(
        api_key=api_key,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions
    )
    
    try:
        # Create embeddings manager with resources and configs
        manager = make_embeddings_manager(
            resources=resources,
            configs=config_params
        )
        return manager
    except Exception as e:
        logger.error(f"Error creating embeddings manager: {e}")
        return None


def create_async_llm_interface(
    resources: dict[str, Any],
    configs: Optional[dict[str, Any]] = None
) -> AsyncLLMInterface:
    """
    Factory function to create an AsyncLLMInterface instance.
    
    Args:
        resources: Dictionary of resources for dependency injection
        configs: Configuration parameters
        
    Returns:
        Configured AsyncLLMInterface instance
    """
    return AsyncLLMInterface(resources=resources, configs=configs)


def make_embeddings_manager(
    resources: dict[str, Any],
    configs: Optional[dict[str, Any]] = None
) -> EmbeddingsInterface:
    """
    Factory function to create an EmbeddingsInterface instance.
    
    Args:
        resources: Dictionary of resources for dependency injection
        configs: Configuration parameters
        
    Returns:
        Configured EmbeddingsInterface instance
    """
    return EmbeddingsInterface(resources=resources, configs=configs)


def _determine_backend_base_on_dependencies(configs: Configs) -> Optional[str]:
    # Try to figure out which libraries are installed.
    for dep in ["openai", "anthropic", "torch"]:
        if dep in dependencies:
            try: # Try libraries first.
                service = getattr(dependencies, dep)
                if service is not None: 
                    key = configs.processing.llm_api_key
                    match key: # See if we have a key for this service.
                        case None | "" if dep == "torch":
                            return "torch"
                        case key if key.startswith("sk-ant"):
                            return "anthropic"
                        case key if key.startswith("sk-proj"):
                            return "openai"
                        case _:
                            continue
            except Exception as e:
                continue
    else:
        # If no dependencies are found, default to OpenAI.
        logger.warning("No LLM dependencies found. Defaulting to OpenAI.")
        return None


def make_llm_components() -> dict[str, Any]:
    """
    Initialize and return all LLM components.
    
    Args:
        configs: Configuration parameters
        api_key: OpenAI API key (uses environment variable if not provided)
        
    Returns:
        Dictionary with initialized LLM components
    """
    return {
        "llm_interface": make_llm_interface(),
        "embeddings_manager": make_embeddings_manager(),
        "resources": create_llm_resources()
    }
