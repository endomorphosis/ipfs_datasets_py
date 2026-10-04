# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/processors/by_ability/_llm_processor.py'

Files last updated: 1749952505.1159441

Stub file last updated: 2025-07-17 05:45:32

## LLMOptions

```python
class LLMOptions(BaseModel):
    """
    Options for LLM processing.

Attributes:
    model: The model to use for generation
    summarize: Whether to generate a summary
    extract_metadata: Whether to extract metadata
    analyze_sentiment: Whether to analyze sentiment
    summary_max_length: Maximum length of summary in characters
    summary_format: Format of the summary (bullet, paragraph)
    prompt_name: Name of the prompt template to use
    custom_system_prompt: Custom system prompt to use
    custom_user_prompt: Custom user prompt to use
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMProcessor

```python
class LLMProcessor:
    """
    Processor for enhancing document processing with language models.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMResult

```python
class LLMResult(BaseModel):
    """
    Result of LLM processing.

Attributes:
    summary: Generated summary of the content
    metadata: Extracted metadata from the content
    sentiment: Sentiment analysis of the content
    raw_responses: Raw responses from the LLM
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Any] = None, configs: Configs = None):
    """
    Initialize the LLM processor with dependency injection.

Args:
    resources: Dictionary of resources including LLM interface
    configs: Configuration parameters
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMProcessor

## _analyze_sentiment

```python
async def _analyze_sentiment(self, content: str, options: LLMOptions, model: str, result: LLMResult) -> None:
    """
    Analyze sentiment of the content.

Args:
    content: Text content to analyze
    options: Processing options
    model: Model to use for generation
    result: Result object to update
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMProcessor

## _extract_metadata

```python
async def _extract_metadata(self, content: str, options: LLMOptions, model: str, result: LLMResult) -> None:
    """
    Extract metadata from the content.

Args:
    content: Text content to extract metadata from
    options: Processing options
    model: Model to use for generation
    result: Result object to update
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMProcessor

## _generate_image_description

```python
async def _generate_image_description(self, content: bytes, options: LLMOptions, model: str, result: LLMResult):
    """
    Generate a summary of an image using VLLM.

Args:
    content (bytes): Image data in bytes.
    options: Processing options
    model: Model to use for generation
    result: Result object to update
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMProcessor

## _generate_summary

```python
async def _generate_summary(self, content: str, options: LLMOptions, model: str, result: LLMResult) -> None:
    """
    Generate a summary of the content.

Args:
    content: Text content to summarize
    options: Processing options
    model: Model to use for generation
    result: Result object to update
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMProcessor

## _ocr_with_vllm

```python
async def _ocr_with_vllm(self, content: bytes, options: LLMOptions, model: str, result: LLMResult):
    """
    Extract text from an image using a VLLM.

Args:
    content: Image content to summarize
    options: Processing options
    model: Model to use for generation
    result: Result object to update
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMProcessor

## _process_content_async

```python
async def _process_content_async(self, content: str, options: LLMOptions) -> LLMResult:
    """
    Process content asynchronously using language models.

Args:
    content: Text content to process
    options: Processing options
    
Returns:
    LLMResult containing processing results
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMProcessor

## process_content

```python
def process_content(self, content: str, options: Union[dict[str, Any], LLMOptions] = None) -> LLMResult:
    """
    Process content using language models.

Args:
    content: Text content to process
    options: Processing options
    
Returns:
    LLMResult containing processing results
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMProcessor
