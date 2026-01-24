import anyio
import logging
from typing import Any, Callable, Optional
import math
from functools import partial
from itertools import islice, batched


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
    # FIXME: Use retries + 1 to ensure at least one attempt even when retries=0
    max_attempts = retries + 1

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
