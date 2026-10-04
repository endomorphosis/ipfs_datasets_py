# Function and Class stubs from 'ipfs_datasets_py/llm/llm_interface.py'

Files last updated: 1751428728.5398443

Stub file last updated: 2025-07-07 02:15:51

## AdaptivePrompting

```python
class AdaptivePrompting:
    """
    Module for dynamically adjusting prompts based on context.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CROSS_DOCUMENT_REASONING

```python
def CROSS_DOCUMENT_REASONING(self) -> PromptTemplate:
    """
    Get cross-document reasoning template.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## DEEP_INFERENCE

```python
def DEEP_INFERENCE(self) -> PromptTemplate:
    """
    Get deep inference template.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## EVIDENCE_CHAIN_ANALYSIS

```python
def EVIDENCE_CHAIN_ANALYSIS(self) -> PromptTemplate:
    """
    Get evidence chain analysis template.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## GraphRAGPromptTemplates

```python
class GraphRAGPromptTemplates:
    """
    Pre-defined prompt templates for GraphRAG reasoning tasks.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## KNOWLEDGE_GAP_IDENTIFICATION

```python
def KNOWLEDGE_GAP_IDENTIFICATION(self) -> PromptTemplate:
    """
    Get knowledge gap identification template.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## LLMConfig

```python
class LLMConfig:
    """
    Configuration for LLM interactions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMInterface

```python
class LLMInterface:
    """
    Abstract base class for LLM interactions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMInterfaceFactory

```python
class LLMInterfaceFactory:
    """
    Factory for creating LLM interfaces.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockLLMInterface

```python
class MockLLMInterface(LLMInterface):
    """
    Mock implementation of LLM interface for development.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PromptLibrary

```python
class PromptLibrary:
    """
    Manager for maintaining and versioning prompt templates.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PromptMetadata

```python
class PromptMetadata:
    """
    Metadata for prompt templates.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PromptTemplate

```python
class PromptTemplate:
    """
    Template for structured prompts to LLMs.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TRANSITIVE_ANALYSIS

```python
def TRANSITIVE_ANALYSIS(self) -> PromptTemplate:
    """
    Get transitive analysis template.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## TemplateVersion

```python
class TemplateVersion:
    """
    Version information for a prompt template.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, model_name: str = "mock-llm", temperature: float = 0.7, max_tokens: int = 1024, top_p: float = 0.9, context_window: int = 4096, supports_function_calling: bool = False, supports_vision: bool = False, supports_tools: bool = False, embedding_dimensions: int = 768):
    """
    Initialize LLM configuration.

Args:
    model_name: Name of the LLM model
    temperature: Sampling temperature (0-1)
    max_tokens: Maximum tokens to generate
    top_p: Nucleus sampling parameter
    context_window: Maximum context window size
    supports_function_calling: Whether the model supports function calling
    supports_vision: Whether the model supports vision inputs
    supports_tools: Whether the model supports tool use
    embedding_dimensions: Dimensions of the embedding vectors
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMConfig

## __init__

```python
def __init__(self, template: str, input_variables: List[str] = None, partial_variables: Dict[str, str] = None):
    """
    Initialize prompt template.

Args:
    template: String template with placeholders {variable_name}
    input_variables: List of variable names in the template
    partial_variables: Dictionary of variables with fixed values
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptTemplate

## __init__

```python
def __init__(self, config: LLMConfig):
    """
    Initialize LLM interface.

Args:
    config: LLM configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## __init__

```python
def __init__(self, config: Optional[LLMConfig] = None):
    """
    Initialize mock LLM interface.

Args:
    config: LLM configuration (uses default if None)
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## __init__

```python
def __init__(self, name: str, version: str = "1.0.0", description: str = "", author: str = "system", created_at: Optional[datetime] = None, tags: Optional[List[str]] = None, model_requirements: Optional[Dict[str, Any]] = None):
    """
    Initialize prompt metadata.

Args:
    name: Name of the prompt template
    version: Semantic version of the prompt template
    description: Description of the prompt template
    author: Author of the prompt template
    created_at: Creation timestamp
    tags: List of tags for categorization
    model_requirements: Requirements for models to use this prompt
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptMetadata

## __init__

```python
def __init__(self, template: PromptTemplate, metadata: PromptMetadata, performance_metrics: Optional[Dict[str, Any]] = None):
    """
    Initialize template version.

Args:
    template: The prompt template
    metadata: Metadata for the template
    performance_metrics: Metrics for template performance
    """
```
* **Async:** False
* **Method:** True
* **Class:** TemplateVersion

## __init__

```python
def __init__(self, storage_path: Optional[str] = None):
    """
    Initialize prompt library.

Args:
    storage_path: Path for persistent storage of templates
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## __init__

```python
def __init__(self, library: PromptLibrary, metrics_tracker: Optional[Dict[str, Any]] = None):
    """
    Initialize adaptive prompting module.

Args:
    library: Prompt library
    metrics_tracker: Tracker for monitoring prompt performance
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptivePrompting

## __init__

```python
def __init__(self, library: Optional[PromptLibrary] = None):
    """
    Initialize GraphRAG prompt templates.

Args:
    library: Optional prompt library to store templates
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## _aggregate_metrics

```python
def _aggregate_metrics(self, key: str) -> Dict[str, Any]:
    """
    Aggregate metrics for a template.

Args:
    key: Template key

Returns:
    Aggregated metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptivePrompting

## _compute_hash

```python
def _compute_hash(self) -> str:
    """
    Compute a hash of the template content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TemplateVersion

## _extract_topics

```python
def _extract_topics(self, text: str) -> List[str]:
    """
    Extract potential topics from text.

Args:
    text: Input text

Returns:
    List of potential topics
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## _generate_mock_data_for_schema

```python
def _generate_mock_data_for_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate mock data matching a JSON schema.

Args:
    schema: JSON schema

Returns:
    Dictionary matching the schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## _generate_response_for_prompt

```python
def _generate_response_for_prompt(self, prompt: str, max_tokens: int) -> str:
    """
    Generate deterministic but variable response based on prompt.

Args:
    prompt: Input prompt
    max_tokens: Maximum tokens to generate

Returns:
    Generated response
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## _initialize_templates

```python
def _initialize_templates(self):
    """
    Initialize predefined templates and add them to the library.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPromptTemplates

## _load_from_storage

```python
def _load_from_storage(self) -> None:
    """
    Load templates from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## _save_to_storage

```python
def _save_to_storage(self) -> None:
    """
    Save templates to storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## add_rule

```python
def add_rule(self, name: str, condition: Callable[[Dict[str, Any]], bool], template_selector: Callable[[Dict[str, Any]], Tuple[str, Optional[str]]], priority: int = 0) -> None:
    """
    Add a rule for prompt selection.

Args:
    name: Name of the rule
    condition: Function that checks if rule applies
    template_selector: Function that selects template and version
    priority: Priority of the rule (higher = more important)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptivePrompting

## add_template

```python
def add_template(self, name: str, template: str, input_variables: Optional[List[str]] = None, partial_variables: Optional[Dict[str, str]] = None, version: str = "1.0.0", description: str = "", author: str = "system", tags: Optional[List[str]] = None) -> str:
    """
    Add a new template to the library.

Args:
    name: Name of the template
    template: The template string
    input_variables: List of input variables
    partial_variables: Dictionary of partial variables
    version: Version string
    description: Description of the template
    author: Author of the template
    tags: List of tags

Returns:
    Template identifier
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## count_tokens

```python
def count_tokens(self, text: str) -> int:
    """
    Count number of tokens in text.

Args:
    text: Input text

Returns:
    Number of tokens

Raises:
    NotImplementedError: Must be implemented by subclass
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## count_tokens

```python
def count_tokens(self, text: str) -> int:
    """
    Count number of tokens in text.

Args:
    text: Input text

Returns:
    Approximate number of tokens
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## create

```python
@staticmethod
def create(model_name: str = "mock-llm", **kwargs) -> LLMInterface:
    """
    Create an LLM interface instance.

Args:
    model_name: Name of the LLM model
    **kwargs: Additional configuration parameters

Returns:
    LLM interface instance

Raises:
    ValueError: If model is not supported
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterfaceFactory

## embed_batch

```python
def embed_batch(self, texts: List[str]) -> np.ndarray:
    """
    Generate embedding vectors for a batch of texts.

Args:
    texts: List of input texts

Returns:
    Array of embedding vectors

Raises:
    NotImplementedError: Must be implemented by subclass
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## embed_batch

```python
def embed_batch(self, texts: List[str]) -> np.ndarray:
    """
    Generate mock embedding vectors for a batch of texts.

Args:
    texts: List of input texts

Returns:
    Array of mock embedding vectors
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## embed_text

```python
def embed_text(self, text: str) -> np.ndarray:
    """
    Generate embedding vector for text.

Args:
    text: Input text

Returns:
    Embedding vector

Raises:
    NotImplementedError: Must be implemented by subclass
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## embed_text

```python
def embed_text(self, text: str) -> np.ndarray:
    """
    Generate mock embedding vector for text.

Args:
    text: Input text

Returns:
    Mock embedding vector
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## find_templates_by_tag

```python
def find_templates_by_tag(self, tag: str) -> List[Dict[str, Any]]:
    """
    Find templates by tag.

Args:
    tag: Tag to search for

Returns:
    List of template metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## format

```python
def format(self, **kwargs) -> str:
    """
    Format the template with provided variables.

Args:
    **kwargs: Variable values to fill template

Returns:
    Formatted string

Raises:
    ValueError: If required variables are missing
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptTemplate

## from_dict

```python
@classmethod
def from_dict(cls, config_dict: Dict[str, Any]) -> "LLMConfig":
    """
    Create config from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMConfig

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "PromptMetadata":
    """
    Create metadata from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptMetadata

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "TemplateVersion":
    """
    Create version from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TemplateVersion

## generate

```python
def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
    """
    Generate text from prompt.

Args:
    prompt: Input prompt
    **kwargs: Additional parameters

Returns:
    Response dictionary with text and metadata

Raises:
    NotImplementedError: Must be implemented by subclass
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## generate

```python
def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
    """
    Generate mock text response from prompt.

Args:
    prompt: Input prompt
    **kwargs: Additional parameters

Returns:
    Response dictionary with text and metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## generate_with_structured_output

```python
def generate_with_structured_output(self, prompt: str, output_schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    Generate structured output from prompt.

Args:
    prompt: Input prompt
    output_schema: JSON schema for output
    **kwargs: Additional parameters

Returns:
    Dictionary matching the output schema

Raises:
    NotImplementedError: Must be implemented by subclass
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## generate_with_structured_output

```python
def generate_with_structured_output(self, prompt: str, output_schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    Generate mock structured output from prompt.

Args:
    prompt: Input prompt
    output_schema: JSON schema for output
    **kwargs: Additional parameters

Returns:
    Dictionary matching the output schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## get_all_templates

```python
def get_all_templates(self) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get all templates in the library.

Returns:
    Dictionary of template metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## get_template

```python
def get_template(self, name: str, version: Optional[str] = None) -> PromptTemplate:
    """
    Get a template by name and version.

Args:
    name: Name of the template
    version: Version of the template (uses latest if None)

Returns:
    The prompt template

Raises:
    ValueError: If template is not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary

## select_prompt

```python
def select_prompt(self, task: str, default_template: str, default_version: Optional[str] = None) -> PromptTemplate:
    """
    Select a prompt template based on context and rules.

Args:
    task: The task for which to select a template
    default_template: Default template name
    default_version: Default template version

Returns:
    The selected prompt template
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptivePrompting

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert config to dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMConfig

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert metadata to dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptMetadata

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert version to dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TemplateVersion

## tokenize

```python
def tokenize(self, text: str) -> List[int]:
    """
    Tokenize text into token IDs.

Args:
    text: Input text

Returns:
    List of token IDs

Raises:
    NotImplementedError: Must be implemented by subclass
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMInterface

## tokenize

```python
def tokenize(self, text: str) -> List[int]:
    """
    Tokenize text into mock token IDs.

Args:
    text: Input text

Returns:
    List of mock token IDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLLMInterface

## track_performance

```python
def track_performance(self, template_name: str, template_version: str, metrics: Dict[str, Any]) -> None:
    """
    Track performance of a template.

Args:
    template_name: Name of the template
    template_version: Version of the template
    metrics: Performance metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptivePrompting

## update_context

```python
def update_context(self, features: Dict[str, Any]) -> None:
    """
    Update context features for prompt selection.

Args:
    features: Dictionary of context features
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptivePrompting

## update_performance_metrics

```python
def update_performance_metrics(self, name: str, version: str, metrics: Dict[str, Any]) -> None:
    """
    Update performance metrics for a template.

Args:
    name: Name of the template
    version: Version of the template
    metrics: Performance metrics

Raises:
    ValueError: If template is not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptLibrary
