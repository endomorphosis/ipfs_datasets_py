# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/llm/_async_interface.py'

Files last updated: 1749801175.7957375

Stub file last updated: 2025-07-17 05:33:54

## AsyncLLMInterface

```python
class AsyncLLMInterface:
    """
    Asynchronous interface for interacting with language models.
Provides a simplified API for text generation and embeddings functionality.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Any] = None, configs: Optional[dict[str, Any]] = None):
    """
    Initialize the async LLM interface with dependency injection.

Args:
    resources: Dictionary of resources including client and processor functions
    configs: Configuration parameters for the interface
    """
```
* **Async:** False
* **Method:** True
* **Class:** AsyncLLMInterface

## extract_metadata

```python
async def extract_metadata(self, text: str, metadata_fields: Optional[list[str]] = None) -> dict[str, Any]:
    """
    Extract metadata from text using the configured language model.

Args:
    text: Text to extract metadata from
    metadata_fields: Specific fields to extract (extracts common fields if None)
    
Returns:
    Dictionary of extracted metadata
    """
```
* **Async:** True
* **Method:** True
* **Class:** AsyncLLMInterface

## generate_embedding

```python
async def generate_embedding(self, text: str, model: Optional[str] = None) -> Optional[list[float]]:
    """
    Generate an embedding vector for a text.

Args:
    text: Text to generate embedding for
    model: Embedding model to use (uses default if None)
    
Returns:
    Embedding vector or None if generation failed
    """
```
* **Async:** True
* **Method:** True
* **Class:** AsyncLLMInterface

## generate_response

```python
async def generate_response(self, prompt: str, system_prompt: Optional[str] = "You are a helpful assistant specialized in document conversion.", temperature: Optional[float] = None, max_tokens: Optional[int] = None, model: Optional[str] = None) -> dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** AsyncLLMInterface

## summarize_text

```python
async def summarize_text(self, text: str, max_length: Optional[int] = None, format_type: Optional[str] = None) -> Optional[str]:
    """
    Summarize a text using the configured language model.

Args:
    text: Text to summarize
    max_length: Maximum length of summary in characters
    format_type: Format of the summary (bullet points, paragraph, etc.)
    
Returns:
    Summarized text or None if generation failed
    """
```
* **Async:** True
* **Method:** True
* **Class:** AsyncLLMInterface
