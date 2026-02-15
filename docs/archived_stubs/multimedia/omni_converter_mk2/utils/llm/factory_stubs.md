# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/llm/factory.py'

Files last updated: 1749939288.8335652

Stub file last updated: 2025-07-17 05:33:54

## _determine_backend_base_on_dependencies

```python
def _determine_backend_base_on_dependencies(configs: Configs) -> Optional[str]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_async_llm_interface

```python
def create_async_llm_interface(resources: dict[str, Any], configs: Optional[dict[str, Any]] = None) -> AsyncLLMInterface:
    """
    Factory function to create an AsyncLLMInterface instance.

Args:
    resources: Dictionary of resources for dependency injection
    configs: Configuration parameters
    
Returns:
    Configured AsyncLLMInterface instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_llm_resources

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_embeddings_manager

```python
def make_embeddings_manager(configs: Optional[dict[str, Any]] = None, api_key: Optional[str] = None) -> Optional[EmbeddingsInterface]:
    """
    Create a configured EmbeddingsInterface instance.

Args:
    configs: Configuration parameters
    api_key: OpenAI API key (uses environment variable if not provided)
    
Returns:
    Configured EmbeddingsInterface instance or None if creation failed
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_embeddings_manager

```python
def make_embeddings_manager(resources: dict[str, Any], configs: Optional[dict[str, Any]] = None) -> EmbeddingsInterface:
    """
    Factory function to create an EmbeddingsInterface instance.

Args:
    resources: Dictionary of resources for dependency injection
    configs: Configuration parameters
    
Returns:
    Configured EmbeddingsInterface instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_llm_components

```python
def make_llm_components() -> dict[str, Any]:
    """
    Initialize and return all LLM components.

Args:
    configs: Configuration parameters
    api_key: OpenAI API key (uses environment variable if not provided)
    
Returns:
    Dictionary with initialized LLM components
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_llm_interface

```python
def make_llm_interface(configs: Optional[dict[str, Any]] = None, api_key: Optional[str] = None) -> Optional[AsyncLLMInterface]:
    """
    Create a configured AsyncLLMInterface instance.

Args:
    configs: Configuration parameters
    api_key: OpenAI API key (uses environment variable if not provided)
    
Returns:
    Configured AsyncLLMInterface instance or None if creation failed
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
