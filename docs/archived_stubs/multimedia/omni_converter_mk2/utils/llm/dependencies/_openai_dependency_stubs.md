# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/llm/dependencies/_openai_dependency.py'

Files last updated: 1749801377.479963

Stub file last updated: 2025-07-17 05:33:29

## calculate_cost

```python
def calculate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """
    Calculate the cost for OpenAI API usage.

This function computes the total cost for an OpenAI API request based on the
model used and the number of input and output tokens processed. It uses
current OpenAI pricing information to provide accurate cost estimates for
budgeting and usage tracking purposes.

Args:
    model (str): The OpenAI model name used for the API request (e.g.,
        "gpt-3.5-turbo", "gpt-4", "text-embedding-ada-002"). The model
        determines the per-token pricing rates.
    input_tokens (int): The number of tokens in the input/prompt sent to
        the API. This includes the original prompt and any context or
        system messages.
    output_tokens (int, optional): The number of tokens in the generated
        response from the API. Defaults to 0 for cases like embeddings
        where there's no text output. Some models charge differently
        for input vs output tokens.

Returns:
    float: The total cost in USD for the API request, calculated based on
        current OpenAI pricing rates. The cost includes both input and
        output token charges where applicable.

Raises:
    ValueError: If the model name is not recognized or if token counts
        are negative values.
    EnvironmentError: If pricing information is not available for the specified model.

Example:
    >>> cost = calculate_cost("gpt-3.5-turbo", input_tokens=100, output_tokens=50)
    >>> print(f"Request cost: ${cost:.4f}")
    Request cost: $0.0002

Note:
    Pricing rates are subject to change by OpenAI. This function should
    be updated periodically to reflect current pricing structures.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## check_if_available

```python
def check_if_available() -> bool:
    """
    Check if OpenAI is available and properly configured.

This function verifies that the OpenAI Python client is installed and that
the necessary API credentials are properly configured in the environment.
It performs basic validation to ensure the OpenAI service can be accessed
before attempting to make API calls.

Returns:
    bool: True if OpenAI is available and properly configured with valid
        API credentials, False otherwise. This includes checking for the
        presence of the OpenAI library, valid API key configuration, and
        basic connectivity to OpenAI services.

Raises:
    EnvironmentError: If required environment variables (such as OPENAI_API_KEY)
        are not properly set or configured.
    ConnectionError: If there are network connectivity issues preventing
        communication with OpenAI services during validation checks.

Example:
    >>> if check_openai_available():
    ...     print("OpenAI is ready to use")
    ... else:
    ...     print("OpenAI configuration issue")

Note:
    This function should be called before attempting to use other OpenAI
    functionality to avoid runtime errors due to missing dependencies
    or configuration issues.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_async_openai_client

```python
def create_async_openai_client():
    """
    Create an async OpenAI client instance.

This function initializes and returns an asynchronous OpenAI client that can be
used for making non-blocking API calls to OpenAI services. The client is
configured with appropriate settings including API key authentication,
timeout configurations, and retry policies.

Returns:
    AsyncOpenAI: An initialized asynchronous OpenAI client instance ready
        for making API calls. The client supports all OpenAI API endpoints
        including chat completions, embeddings, and other services.

Raises:
    EnvironmentError: If the API key is missing, invalid, or improperly
        configured in the environment variables.
    ValueError: If there are issues with client configuration
        parameters or network settings.

Note:
    The client uses environment variables for configuration. Ensure
    OPENAI_API_KEY is properly set before calling this function.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_embeddings

```python
async def generate_embeddings(text: str, model: str = "text-embedding-ada-002") -> list[float]:
    """
    Generate text embeddings using OpenAI's embeddings API.

This function asynchronously generates vector embeddings for the provided text using
OpenAI's embedding models. Embeddings are numerical representations of text that
capture semantic meaning and can be used for similarity comparisons, clustering,
classification, and other machine learning tasks.

Args:
    text (str): The input text to generate embeddings for. Should be a non-empty
        string containing the content to be embedded. The text will be processed
        by the specified OpenAI embedding model.
    model (str, optional): The OpenAI embedding model to use for generating
        embeddings. Defaults to "text-embedding-ada-002", which is OpenAI's
        most capable and cost-effective embedding model. Other options may
        include newer models like "text-embedding-3-small" or "text-embedding-3-large".

Returns:
    list[float]: A list of floating-point numbers representing the embedding
        vector for the input text. The dimensionality of the vector depends
        on the chosen model (e.g., text-embedding-ada-002 returns 1536 dimensions).
        These embeddings can be used for semantic similarity calculations,
        vector database storage, or as input features for machine learning models.

Raises:
    OpenAIError: If there's an error communicating with the OpenAI API, such as
        authentication failures, rate limiting, or service unavailability.
    ValueError: If the input text is empty or invalid, or if an unsupported
        model name is provided.
    ConnectionError: If there are network connectivity issues preventing
        communication with the OpenAI API endpoints.

Example:
    >>> embeddings = await generate_embeddings("Hello, world!")
    >>> len(embeddings)
    1536
    >>> isinstance(embeddings[0], float)
    True

Note:
    This function requires valid OpenAI API credentials to be configured in the
    environment. The API usage will be billed according to OpenAI's pricing
    structure based on the number of tokens processed.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_text

```python
async def generate_text(prompt: str, model: str = "gpt-3.5-turbo", **kwargs) -> str:
    """
    Generate text using OpenAI's chat completion API.

This function asynchronously generates text responses using OpenAI's chat
completion models. It sends a prompt to the specified model and returns
the generated text response. The function supports various model parameters
and configuration options through keyword arguments.

Args:
    prompt (str): The input prompt or message to send to the model. This
        should be a clear, well-formatted string that describes what you
        want the model to generate or respond to.
    model (str, optional): The OpenAI chat model to use for text generation.
        Defaults to "gpt-3.5-turbo". Other options include "gpt-4",
        "gpt-4-turbo", or other available chat completion models.
    **kwargs: Additional keyword arguments to pass to the OpenAI API,
        such as temperature (creativity), max_tokens (response length),
        top_p (nucleus sampling), frequency_penalty, presence_penalty,
        and other model-specific parameters.

Returns:
    str: The generated text response from the OpenAI model. This contains
        the model's completion or response to the provided prompt.

Raises:
    OpenAIError: If there's an error communicating with the OpenAI API,
        including authentication failures, rate limiting, or service issues.
    ValueError: If the prompt is empty or if invalid parameters are provided
        in the kwargs.
    ConnectionError: If there are network connectivity issues preventing
        communication with OpenAI services.

Example:
    >>> response = await generate_text("Write a haiku about programming")
    >>> print(response)
    Code flows like water,
    Logic branching through the mind,
    Bugs hiding in wait.

Note:
    This function requires valid OpenAI API credentials and will consume
    API tokens based on both the input prompt and generated response length.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
