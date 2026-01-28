import anyio
import logging
from typing import Any, Callable, Optional
import math
from functools import partial
from itertools import islice, batched
from dataclasses import dataclass
import os
import shutil


try:
    from pydantic import BaseModel, Field, NonNegativeFloat
    HAVE_PYDANTIC = True
except ImportError:
    BaseModel = object
    Field = lambda **kwargs: None
    NonNegativeFloat = float
    HAVE_PYDANTIC = False

try:
    import openai
    HAVE_OPENAI = True
except ImportError:
    openai = None
    HAVE_OPENAI = False

# Try to import accelerate integration for distributed LLM inference
try:
    from ipfs_datasets_py.accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False}

if not HAVE_PYDANTIC or not HAVE_OPENAI:
    print(f"Info: LLM classification using mock implementation (missing: {'pydantic ' if not HAVE_PYDANTIC else ''}{'openai' if not HAVE_OPENAI else ''})")


logger = logging.getLogger(__name__)


# NOTE: From https://huggingface.co/datasets/KnutJaegersberg/wikipedia_categories, 7/25/2025
WIKIPEDIA_CLASSIFICATIONS = {
    "Academic Disciplines",
    "Business",
    "Concepts",
    "Culture",
    "Economy",
    "Education",
    "Energy",
    "Engineering",
    "Entertainment",
    "Ethics",
    "Events",
    "Food and drink",
    "Geography",
    "Government",
    "Health",
    "History",
    "Humanities",
    "Industry",
    "Knowledge",
    "Language",
    "Law",
    "Life",
    "Mass media",
    "Mathematics",
    "Military",
    "Music",
    "Nature",
    "Organizations",
    "People",
    "Philosophy",
    "Policy",
    "Politics",
    "Religion",
    "Science and technology",
    "Society",
    "Sports",
    "World"
}


class ClassificationResult(BaseModel):
    """Result of entity classification."""
    entity: str
    category: str
    confidence: NonNegativeFloat = Field(le=1.0)


async def _classify_with_openai_llm(
        prompt: str, 
        system_prompt: str, 
        client, # openai.AsyncOpenAI when available
        num_categories: int, 
        model: str = "gpt-4.1-2025-04-14",
        log_threshold: float = 0.05,
        timeout: float = 30.0,
    ):

    temperature = 0.0 
    logprobs = True
    max_tokens = 1  # We only want the next token, not a full response
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await client.chat.completions.create(
            logprobs=logprobs, 
            top_logprobs=num_categories, 
            model=model, 
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout
        )
    except Exception as e:
        # Handle OpenAI-specific exceptions if available
        if HAVE_OPENAI:
            if isinstance(e, openai.RateLimitError):
                raise RuntimeError(f"Rate limit exceeded: {e}") from e
            elif isinstance(e, openai.APITimeoutError):
                raise TimeoutError(f"Timeout while waiting for OpenAI response: {e}") from e
            elif isinstance(e, openai.OpenAIError):
                raise ConnectionError(f"OpenAI API error during classification: {e}") from e
        # Generic handling for when openai is not available or other exceptions
        raise e

    # Filter out probabilities that are below the threshold.
    filtered_token_prob_tuples: list[tuple[str, float]] = [
        (top_logprob.token, top_logprob.logprob)
        for top_logprob in response.choices[0].logprobs.content[0].top_logprobs
        if top_logprob.logprob > log_threshold
    ]
    #print(f"_classify_with_openai_llm filtered token probabilities: {filtered_token_prob_tuples}")
    return filtered_token_prob_tuples


@dataclass(frozen=True, slots=True)
class CodexExecClient:
    """Configuration wrapper for using the Codex CLI (npm `@openai/codex`) as an LLM backend.

    This is intentionally lightweight: the Codex CLI is executed as a subprocess.
    The client is used as a marker/type so `classify_with_llm` can auto-select the
    correct backend.

    Notes:
        - Requires the `codex` executable to be on PATH (e.g. `npm i -g @openai/codex`).
        - Auth can be via `codex login ...` or `CODEX_API_KEY` for `codex exec` runs.
    """

    codex_bin: str = "codex"
    api_key: Optional[str] = None  # forwarded as CODEX_API_KEY for this run


@dataclass(frozen=True, slots=True)
class _CompatTopLogProb:
    token: str
    logprob: float


@dataclass(frozen=True, slots=True)
class _CompatLogProbsContentItem:
    top_logprobs: list[_CompatTopLogProb]


@dataclass(frozen=True, slots=True)
class _CompatLogProbs:
    content: list[_CompatLogProbsContentItem]


@dataclass(frozen=True, slots=True)
class _CompatMessage:
    content: str


@dataclass(frozen=True, slots=True)
class _CompatChoice:
    message: _CompatMessage
    logprobs: _CompatLogProbs


@dataclass(frozen=True, slots=True)
class _CompatResponse:
    choices: list[_CompatChoice]


class _CodexChatCompletionsCompat:
    def __init__(self, client: CodexExecClient):
        self._client = client

    async def create(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 1,
        temperature: float = 0.0,
        logprobs: bool = True,
        top_logprobs: int = 1,
        timeout: float = 30.0,
        **_: Any,
    ) -> _CompatResponse:
        """OpenAI-compatible `chat.completions.create` powered by `codex exec`.

        Codex CLI does not expose logprobs; we synthesize a single-token top_logprobs
        entry with logprob 0.0 so existing filtering logic works.
        """
        del model, max_tokens, temperature, logprobs, top_logprobs

        if shutil.which(self._client.codex_bin) is None:
            raise RuntimeError(
                "Codex CLI backend selected but 'codex' was not found on PATH. "
                "Install with `npm i -g @openai/codex` (or `brew install --cask codex`)."
            )

        # Flatten messages into a single task.
        rendered = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
        task = f"{rendered}\n\nReturn ONLY the category name, with no extra text."

        env = os.environ.copy()
        if self._client.api_key:
            env["CODEX_API_KEY"] = self._client.api_key

        cmd = [self._client.codex_bin, "exec", task]
        with anyio.fail_after(timeout):
            completed = await anyio.run_process(cmd, env=env)

        output = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
        if not output:
            # Return an empty token list in logprobs; upstream will treat as no classifications.
            return _CompatResponse(
                choices=[
                    _CompatChoice(
                        message=_CompatMessage(content=""),
                        logprobs=_CompatLogProbs(content=[_CompatLogProbsContentItem(top_logprobs=[])]),
                    )
                ]
            )

        top = _CompatTopLogProb(token=output, logprob=0.0)
        return _CompatResponse(
            choices=[
                _CompatChoice(
                    message=_CompatMessage(content=output),
                    logprobs=_CompatLogProbs(content=[_CompatLogProbsContentItem(top_logprobs=[top])]),
                )
            ]
        )


class _CodexOpenAICompatClient:
    """Minimal OpenAI Async client shape: `.chat.completions.create(...)`."""

    def __init__(self, client: CodexExecClient):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _CodexChatCompletionsCompat(client)


def _coerce_openai_chat_client(client: Any) -> Any:
    """Coerce supported backends into an OpenAI-chat-completions compatible client."""
    if isinstance(client, CodexExecClient):
        return _CodexOpenAICompatClient(client)
    return client


async def _classify_with_codex_exec_llm(
    prompt: str,
    system_prompt: str,
    client: CodexExecClient,
    num_categories: int,
    model: str = "gpt-4.1-2025-04-14",
    log_threshold: float = 0.05,
    timeout: float = 30.0,
) -> list[tuple[str, float]]:
    """Classification backend that shells out to `codex exec`.

    Codex CLI does not currently expose OpenAI-style logprobs in a stable API.
    To preserve the existing `classify_with_llm` contract, we treat Codex's final
    category selection as a single token with log-probability 0.0 (i.e. p=1.0).
    """
    del num_categories, model, log_threshold  # not used by Codex CLI

    if shutil.which(client.codex_bin) is None:
        raise RuntimeError(
            "Codex CLI backend selected but 'codex' was not found on PATH. "
            "Install with `npm i -g @openai/codex` (or `brew install --cask codex`)."
        )

    # Codex CLI runs inside a git repo by default; keep sandboxing conservative.
    # It prints progress to stderr and only the final message to stdout.
    task = (
        f"{system_prompt}\n\n"
        f"{prompt}\n\n"
        "Return ONLY the category name, with no extra text."
    )

    env = os.environ.copy()
    if client.api_key:
        env["CODEX_API_KEY"] = client.api_key

    cmd = [client.codex_bin, "exec", task]
    with anyio.fail_after(timeout):
        completed = await anyio.run_process(cmd, env=env)

    output = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    if not output:
        return []

    # Treat as a single high-confidence token.
    return [(output, 0.0)]


# Function to prevent rate-limits overruns.
async def _run_task_with_limit(task: Callable):
    async with _SEMAPHORE:
        return await task


async def _classify_with_transformers_llm(
    prompt: str, 
    system_prompt: str, 
    client, # OpenAI client when available 
    num_categories: int, 
    model: str = "gpt-4.1-2025-04-14",
    log_threshold: float = 0.05,
    timeout: float = 30.0,
    ) -> list[tuple[str, float]] | list:
    raise NotImplementedError(
        "Transformers-based classification is not yet implemented. "
        "Please use OpenAI's API for classification."
    )


_SEMAPHORE = anyio.Semaphore(3)  # Limit concurrency to prevent rate-limit overruns


import anyio


async def classify_with_llm(
    *,
    text: str, 
    classifications: set[str] = WIKIPEDIA_CLASSIFICATIONS,
    client: Any,
    model: str = "gpt-4.1-nano-2025-04-14", # "gpt-4.1-2025-04-14",
    retries: Optional[int] = 3,
    timeout = 30.0,  # seconds
    threshold: float = 0.05, # i.e. statistical significance threshold
    logger: logging.Logger = logger,
    llm_func: Callable = _classify_with_openai_llm
    ) -> list[ClassificationResult] | list:
    """
    Classify text into predefined categories using OpenAI's LLM.

    This function uses a transformer-based LLM to classify an arbitrary 
    English-language text into one or more arbitrary categories from a predefined set.

    Args:
        text (str): The text to classify.
        classifications (set[str]): Set of predefined categories to classify the text into.
        client (openai.AsyncOpenAI): OpenAI client instance for making API calls.
        model (str): The OpenAI model to use for classification. Defaults to "gpt-4o".
        retries (Optional[int]): Number of retries to refine classification. Defaults to 3.
        threshold (float): Probability threshold for including a classification. 
            Defaults to 0.05 (e.g. the statistical definition of an outlier)
        logger (logging.Logger): Logger instance for logging messages. Defaults to the module logger.
    
    Returns:
        list[ClassificationResult] | list: List of ClassificationResult objects if classifications found.
            ClassificationResult is a pydantic base model with the following fields:
            - entity (str): The original text entity.
            - category (str): The category assigned to the entity.
            - confidence (float): Confidence score of the classification (0.0-1.0).
            If no classifications are found, returns an empty list.
    """
    client = _coerce_openai_chat_client(client)

    winnowed_categories: set[str] = classifications
    if threshold <= 0 or threshold >= 1:
        raise ValueError(f"Threshold must be a positive float between 0 and 1, got {threshold}.")
    log_threshold = math.log(threshold) if threshold > 0 else threshold

    # FIXME Support non-OpenAI clients
    # match client:
    #     case client if asyncio.iscoroutine(client):
    #         # If client is an async OpenAI client, use the async classification function
    #         llm_func = _classify_with_openai_llm
    #     case openai.AsyncOpenAI():
    #         llm_func = _classify_with_openai_llm
    #     case _:
    #         llm_func = _classify_with_transformers_llm

    system_prompt = "You are a helpful assistant that classifies text into predefined categories."
    prompt_template = """
# Instructions:
- Classify the text into one of the following categories.
- Return only the name of the category, with no additional formatting or commentary.
- Your response must be one of the categories.

# Categories
{categories}

# Text
{text}
"""
    # `retries` is treated as the maximum number of attempts.
    # Ensure we always attempt at least once when retries=0.
    if retries is None:
        max_attempts = 3
    else:
        max_attempts = max(1, retries)

    async with _SEMAPHORE:
        for attempt in range(max_attempts):
            num_categories = len(winnowed_categories)
            if num_categories <= 0:
                raise ValueError(f"Invalid number of categories: {num_categories}. Must be a positive integer.")

            num_categories = min(num_categories, 20)  # Limit to 20 categories for OpenAI API

            try:
                filtered_token_prob_tuples = await llm_func(
                    prompt=prompt_template.format(
                        categories=', '.join(list(winnowed_categories)),
                        text=text,
                    ),
                    system_prompt=system_prompt,
                    client=client,
                    num_categories=num_categories,
                    model=model,
                    timeout=timeout,
                    log_threshold=log_threshold,
                ) 

                print(f"Filtered token probabilities: {filtered_token_prob_tuples}")
                #logger.debug(f"Filtered token probabilities: {filtered_token_prob_tuples}")

            except ConnectionError as e:
                print(f"Connection error on attempt {attempt}: {e}")
                raise e
            except TimeoutError as e:
                if attempt == max_attempts - 1:
                    print(f"Timeout exceeded after {max_attempts} attempts: {e}")
                    raise e
                print(f"Timeout on attempt {attempt}, retrying...: {e}")
                continue
            except Exception as e:
                if "RateLimitError" in str(e):
                    # Throttle and try again
                    print("Got rate limit error. Throttling and trying again.")
                    max_attempts += 1
                    anyio.sleep(1)

                if attempt == max_attempts - 1:
                    print(f"Max retries exceeded after {max_attempts} attempts: {e}")
                    raise RuntimeError(f"Unexpected {type(e).__name__} calling API: {e}")
                print(f"Unexpected error on attempt {attempt}: {e}")
                continue

            if not filtered_token_prob_tuples:
                logger.warning(f"No classifications above threshold {threshold} for text: {text}")
                return []

            new_cats = set()
            potential_outputs = set()

            for cat in winnowed_categories:
                # If token string begins a classification string, add that classification to the set.
                # ex: "Tech" would match "Technology"
                for token, log_prob in filtered_token_prob_tuples:
                    if cat.lower().startswith(token.lower()):
                        if log_prob >= log_threshold:
                            new_cats.add(cat)
                            potential_outputs.add((cat, log_prob))

            match len(new_cats):
                case 0:
                    logger.warning(f"No matching categories found for text: {text}")
                    return []
                case 1:
                    # If we only have one category, return it as a single result
                    cat_log_prob_tuple = potential_outputs.pop()
                    category, log_prob = cat_log_prob_tuple
                    return [ClassificationResult(entity=text, category=category, confidence=math.exp(log_prob))]
                case _:
                    # Return multiple results if we've exhausted all attempts
                    if attempt == max_attempts - 1:
                        return sorted(
                            [
                                ClassificationResult(
                                    entity=text, 
                                    category=cat, 
                                    confidence=math.exp(log_prob)
                                ) 
                                for cat, log_prob in potential_outputs
                                if log_prob >= log_threshold
                            ],
                            key=lambda x: x.confidence,
                            reverse=True
                        )
                    else:
                        winnowed_categories = new_cats
                        continue
    
    # This should never be reached due to the loop structure, but keeping for safety
    logger.warning(f"No classifications found after {max_attempts} attempts for text: {text}")
    return []
