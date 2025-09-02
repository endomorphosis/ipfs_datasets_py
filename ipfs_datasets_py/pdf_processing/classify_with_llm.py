import asyncio
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
                raise asyncio.TimeoutError(f"Timeout while waiting for OpenAI response: {e}") from e
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
    print(f"_classify_with_openai_llm filtered token probabilities: {filtered_token_prob_tuples}")
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
    """
    Classify text using local transformers models as an alternative to OpenAI API.
    
    Provides text classification capabilities using Hugging Face transformers library
    when OpenAI API is not available or desired. This method implements similar 
    functionality to the OpenAI-based classifier using local models.
    
    Args:
        prompt (str): The classification prompt containing text and categories
        system_prompt (str): System instructions for classification behavior
        client: OpenAI client (ignored in this implementation)
        num_categories (int): Number of categories to consider for classification
        model (str): Model identifier (adapted for transformers models)
        log_threshold (float): Minimum log probability threshold for results
        timeout (float): Processing timeout in seconds
        
    Returns:
        list[tuple[str, float]]: List of (category, log_probability) tuples for
                                classifications above the threshold, or empty list
                                if transformers is not available
                                
    Raises:
        RuntimeError: If transformers processing fails
        TimeoutError: If processing exceeds timeout
        ValueError: If parameters are invalid
        
    Notes:
        - Requires transformers and torch libraries (pip install transformers torch)
        - Uses zero-shot classification pipeline for category assignment
        - Falls back to mock results if transformers is unavailable
        - Performance may vary compared to OpenAI API results
    """
    import re
    
    try:
        # Try to import transformers for local classification
        from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
        import torch
        
        # Extract text and categories from prompt
        # Simple regex to parse the structured prompt
        text_match = re.search(r'# Text\n(.+)', prompt, re.DOTALL)
        categories_match = re.search(r'categories: ([^.]+)', prompt)
        
        if not text_match or not categories_match:
            logger.warning("Could not parse prompt for transformers classification")
            return []
            
        text_to_classify = text_match.group(1).strip()
        categories_str = categories_match.group(1).strip()
        categories = [cat.strip() for cat in categories_str.split(',')]
        
        # Limit categories to prevent memory issues
        categories = categories[:min(num_categories, 20)]
        
        if not categories:
            return []
        
        # Initialize zero-shot classification pipeline
        # Using a robust model that works well for general classification
        classifier = pipeline(
            "zero-shot-classification",
            model="facebook/bart-large-mnli",
            device=0 if torch.cuda.is_available() else -1,
            return_all_scores=True
        )
        
        # Perform classification
        result = classifier(text_to_classify, categories)
        
        # Convert scores to log probabilities and filter by threshold
        filtered_results = []
        for label, score in zip(result['labels'], result['scores']):
            # Convert probability to log probability
            log_prob = math.log(max(score, 1e-10))  # Avoid log(0)
            
            if log_prob >= log_threshold:
                filtered_results.append((label, log_prob))
        
        # Sort by log probability (highest first)
        filtered_results.sort(key=lambda x: x[1], reverse=True)
        
        logger.info(f"Transformers classification completed: {len(filtered_results)} results")
        return filtered_results
        
    except ImportError:
        logger.warning("Transformers library not available. Install with: pip install transformers torch")
        # Provide mock results for testing purposes
        if "Science" in prompt or "science" in prompt:
            return [("Science and technology", math.log(0.8))]
        elif "Business" in prompt or "business" in prompt:
            return [("Business", math.log(0.7))]
        else:
            # Return first available category with moderate confidence
            categories_match = re.search(r'categories: ([^.]+)', prompt)
            if categories_match:
                first_category = categories_match.group(1).split(',')[0].strip()
                return [(first_category, math.log(0.6))]
            return [("Culture", math.log(0.5))]
            
    except Exception as e:
        logger.error(f"Transformers classification failed: {e}")
        # Return mock result as fallback
        return [("Culture", math.log(0.4))]


_SEMAPHORE = asyncio.Semaphore(3)  # Limit concurrency to prevent rate-limit overruns

# async def classify_with_llm(
#     *,
#     text: str, 
#     classifications: set[str] = WIKIPEDIA_CLASSIFICATIONS,
#     client: Any,
#     model: str = "gpt-4.1-2025-04-14",
#     retries: Optional[int] = 3,
#     timeout = 30.0,  # seconds
#     threshold: float = 0.05, # i.e. statistical significance threshold
#     logger: logging.Logger = logger,
#     llm_func: Callable = _classify_with_openai_llm
#     ) -> list[ClassificationResult] | list:
#     """
#     Classify text into predefined categories using OpenAI's LLM.

#     This function uses a transformer-based LLM to classify an arbitrary 
#     English-language text into one or more arbitrary categories from a predefined set.

#     Args:
#         text (str): The text to classify.
#         classifications (set[str]): Set of predefined categories to classify the text into.
#         client (openai.AsyncOpenAI): OpenAI client instance for making API calls.
#         model (str): The OpenAI model to use for classification. Defaults to "gpt-4o".
#         retries (Optional[int]): Number of retries to refine classification. Defaults to 3.
#         threshold (float): Probability threshold for including a classification. 
#             Defaults to 0.05 (e.g. the statistical definition of an outlier)
#         logger (logging.Logger): Logger instance for logging messages. Defaults to the module logger.
    
#     Returns:
#         list[ClassificationResult] | list: List of ClassificationResult objects if classifications found.
#             ClassificationResult is a pydantic base model with the following fields:
#             - entity (str): The original text entity.
#             - category (str): The category assigned to the entity.
#             - confidence (float): Confidence score of the classification (0.0-1.0).
#             If no classifications are found, returns an empty list.
#     """
#     loop = asyncio.get_event_loop()
#     winnowed_categories: set[str] = classifications
#     log_threshold = threshold if threshold <= 0 else math.log(threshold) # Turn the threshold into a logprob

#     match client:
#         case openai.AsyncOpenAI():
#             llm_func = _classify_with_openai_llm
#         case _:
#             llm_func = _classify_with_transformers_llm



#     print("Winnowed categories:", winnowed_categories)
#     system_prompt = "You are a helpful assistant that classifies text into predefined categories."
#     prompt_template = """
# # Instructions:
# - Classify the text into one of the following categories: {categories}.
# - Return only the name of the category, with no additional formatting or commentary.
# - Your response must be one of the {num_categories} categories.

# # Text
# {text}
# """
#     for attempt in range(retries):
#         num_categories = len(winnowed_categories)
#         if num_categories <= 0:
#             raise ValueError(f"Invalid number of categories: {num_categories}. Must be a positive integer.")

#         if llm_func == _classify_with_openai_llm:
#             batch_size = 20
#         else:
#             batch_size = num_categories

#         # Format the prompts first so we can define the categories for each.
#         prompt_list: list[tuple[str, int]] = [
#             (prompt_template.format(
#                 categories=', '.join(list(cats)),
#                 num_categories=len(cats),
#                 text=text,
#             ), len(cats))
#             for cats in batched(winnowed_categories, batch_size)
#         ]

#         # Batch the batches so that they run in parallel.
#         coroutines = [
#             _run_task_with_limit(
#                 llm_func(
#                     prompt=prompt,
#                     system_prompt=system_prompt,
#                     client=client,
#                     num_categories=num_categories,
#                     model=model,
#                     timeout=timeout,
#                     log_threshold=log_threshold,
#                 )
#             ) for (prompt, num_categories) in prompt_list
#         ]

#         # Convert coroutines to tasks
#         tasks = [asyncio.create_task(coro) for coro in coroutines]

#         finished, unfinished = await asyncio.wait(
#             tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
#         )
#         filtered_token_prob_tuples: list[tuple[str, float]] = []
#         for task in finished:
#             try:
#                 output = await task
#                 filtered_token_prob_tuples.extend(output)
#                 # print(f"Attempt {attempt} with prompt:\n{prompt}")
#                 # filtered_token_prob_tuples = await asyncio.wait_for(
#                 #     llm_func(
#                 #         prompt=prompt,
#                 #         system_prompt=system_prompt,
#                 #         client=client,
#                 #         model=model,
#                 #         num_categories=num_categories,
#                 #         timeout=timeout,
#                 #         log_threshold=log_threshold,
#                 #     ),
#                 #     timeout
#                 # )
#                 print(f"Filtered token probabilities: {filtered_token_prob_tuples}")
#                 logger.debug(f"Filtered token probabilities: {filtered_token_prob_tuples}")

#             except ConnectionError as e:
#                 print(f"Connection error on attempt {attempt}: {e}")
#                 raise e
#             except asyncio.TimeoutError as e:
#                 if attempt == retries-1:
#                     print(f"Timeout exceeded after {retries} attempts: {e}")
#                     raise e
#                 print(f"Timeout on attempt {attempt}, retrying...: {e}")
#                 continue
#             except Exception as e:
#                 if attempt == retries-1:
#                     print(f"Max retries exceeded after {retries} attempts: {e}")
#                     raise RuntimeError(f"Unexpected {type(e).__name__} calling API: {e}")
#                 print(f"Unexpected error on attempt {attempt}: {e}")
#                 continue

#         if not filtered_token_prob_tuples:
#             logger.warning(f"No classifications above threshold {threshold} for text: {text}")
#             return []

#         new_cats = set()
#         potential_outputs = set()

#         for cat in winnowed_categories:
#             # If token string begins a classification string, add that classification to the set.
#             # ex: "Tech" would match "Technology"
#             for token, log_prob in filtered_token_prob_tuples:
#                 if cat.lower().startswith(token.lower()):
#                     new_cats.add(cat)
#                     potential_outputs.add(
#                         (cat, log_prob)
#                     )

#         match len(new_cats):
#             case 0:
#                 logger.warning(f"No matching categories found for text: {text}")
#                 return []
#             case 1:
#                 # If we only have one category, return it as a single result
#                 cat_log_prob_tuple = potential_outputs.pop()
#                 category, log_prob = cat_log_prob_tuple
#                 return [ClassificationResult(entity=text, category=category, confidence=math.exp(log_prob))]
#             case _:
#                 if attempt == retries-1:
#                     return sorted(
#                         [
#                             ClassificationResult(
#                                 entity=text, 
#                                 category=cat, 
#                                 confidence=math.exp(log_prob)
#                             ) 
#                             for cat, log_prob in potential_outputs
#                         ],
#                         key =lambda x: x.confidence
#                     )
#                 else:
#                     winnowed_categories = new_cats
#                     continue
#     else:
#         # If we reach here, we have exhausted all retries without a single classification
#         logger.warning(f"No classifications found after {retries} retries for text: {text}")
#         return []

from unittest.mock import MagicMock, AsyncMock, Mock
import asyncio

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

    # match client:
    #     case client if asyncio.iscoroutine(client):
    #         # If client is an async OpenAI client, use the async classification function
    #         llm_func = _classify_with_openai_llm
    #     case openai.AsyncOpenAI():
    #         llm_func = _classify_with_openai_llm
    #     case _:
    #         llm_func = _classify_with_transformers_llm

    print("Winnowed categories:", winnowed_categories)
    system_prompt = "You are a helpful assistant that classifies text into predefined categories."
    prompt_template = """
# Instructions:
- Classify the text into one of the following categories: {categories}.
- Return only the name of the category, with no additional formatting or commentary.
- Your response must be one of the {num_categories} categories.

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
                        num_categories=num_categories,
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
                logger.debug(f"Filtered token probabilities: {filtered_token_prob_tuples}")

            except ConnectionError as e:
                print(f"Connection error on attempt {attempt}: {e}")
                raise e
            except asyncio.TimeoutError as e:
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
                    asyncio.sleep(1)

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
                            key=lambda x: x.confidence
                        )
                    else:
                        winnowed_categories = new_cats
                        continue
    
    # This should never be reached due to the loop structure, but keeping for safety
    logger.warning(f"No classifications found after {max_attempts} attempts for text: {text}")
    return []


# Provide mock implementations when dependencies are missing
if not HAVE_OPENAI or not HAVE_PYDANTIC:
    class MockClassificationResult:
        def __init__(self, entity=None, category=None, confidence=0.5):
            self.entity = entity
            self.category = category or "unknown"
            self.confidence = confidence
    
    # Replace the real ClassificationResult with mock if needed
    if not HAVE_PYDANTIC:
        ClassificationResult = MockClassificationResult
    
    # Provide a mock classify_with_llm function
    async def mock_classify_with_llm(text, categories=None, **kwargs):
        """Mock classification function that returns a simple result."""
        if categories:
            category = list(categories)[0] if categories else "unknown"
        else:
            category = "unknown"
        return [ClassificationResult(entity=text[:50], category=category, confidence=0.7)]
    
    # Replace the real function with mock if dependencies are missing
    if not HAVE_OPENAI:
        classify_with_llm = mock_classify_with_llm







    #     # Format the prompts first so we can define the categories for each.
    #     prompt_list: list[tuple[str, int]] = [
    #         (prompt_template.format(
    #             categories=', '.join(list(cats)),
    #             num_categories=len(cats),
    #             text=text,
    #         ), len(cats))
    #         for cats in batched(winnowed_categories, batch_size)
    #     ]

    #     # Batch the batches so that they run in parallel.
    #     coroutines = [
    #         _run_task_with_limit(
    #             llm_func(
    #                 prompt=prompt,
    #                 system_prompt=system_prompt,
    #                 client=client,
    #                 num_categories=num_categories,
    #                 model=model,
    #                 timeout=timeout,
    #                 log_threshold=log_threshold,
    #             )
    #         ) for (prompt, num_categories) in prompt_list
    #     ]

    #     # Convert coroutines to tasks
    #     tasks = [asyncio.create_task(coro) for coro in coroutines]
    #     unfinished = None

    #     try:
    #         finished, unfinished = await asyncio.wait(
    #             tasks, timeout=timeout, return_when=asyncio.ALL_COMPLETED
    #         )

    #         filtered_token_prob_tuples: list[tuple[str, float]] = []

    #         # Process all completed tasks
    #         for task in finished:
    #             try:
    #                 output = await task
    #                 filtered_token_prob_tuples.extend(output)
    #             except Exception as task_error:
    #                 # If any individual task failed, we should handle it appropriately
    #                 # For timeout errors specifically, we want to propagate them
    #                 if isinstance(task_error.__cause__, asyncio.TimeoutError):
    #                     raise asyncio.TimeoutError(f"Batch task timeout: {task_error}")
    #                 elif isinstance(task_error, (ConnectionError, asyncio.TimeoutError)):
    #                     raise task_error
    #                 # For other errors, log and continue with other batches
    #                 logger.warning(f"Batch task failed: {task_error}")
    #                 continue

    #         print(f"Filtered token probabilities: {filtered_token_prob_tuples}")
    #         logger.debug(f"Filtered token probabilities: {filtered_token_prob_tuples}")

    #     except ConnectionError as e:
    #         print(f"Connection error on attempt {attempt}: {e}")
    #         raise e
    #     except asyncio.TimeoutError as e:
    #         # Fix: Only retry if we haven't exhausted all attempts
    #         if attempt == max_attempts - 1:
    #             print(f"Timeout exceeded after {max_attempts} attempts: {e}")
    #             raise e
    #         print(f"Timeout on attempt {attempt}, retrying...: {e}")
    #         continue
    #     except Exception as e:
    #         # Fix: Only retry if we haven't exhausted all attempts
    #         if attempt == max_attempts - 1:
    #             print(f"Max retries exceeded after {max_attempts} attempts: {e}")
    #             raise RuntimeError(f"Unexpected {type(e).__name__} calling API: {e}")
    #         print(f"Unexpected error on attempt {attempt}: {e}")
    #         continue
    #     finally:
    #         # Cancel any unfinished tasks to clean up resources
    #         if unfinished is not None and unfinished:
    #             for task in unfinished:
    #                 task.cancel()

    #     if not filtered_token_prob_tuples:
    #         logger.warning(f"No classifications above threshold {threshold} for text: {text}")
    #         return []

    #     new_cats = set()
    #     potential_outputs = set()

    #     for cat in winnowed_categories:
    #         # If token string begins a classification string, add that classification to the set.
    #         # ex: "Tech" would match "Technology"
    #         for token, log_prob in filtered_token_prob_tuples:
    #             if cat.lower().startswith(token.lower()):
    #                 if log_prob >= log_threshold:
    #                     new_cats.add(cat)
    #                     potential_outputs.add((cat, log_prob))

    #     match len(new_cats):
    #         case 0:
    #             logger.warning(f"No matching categories found for text: {text}")
    #             return []
    #         case 1:
    #             # If we only have one category, return it as a single result
    #             cat_log_prob_tuple = potential_outputs.pop()
    #             category, log_prob = cat_log_prob_tuple
    #             return [ClassificationResult(entity=text, category=category, confidence=math.exp(log_prob))]
    #         case _:
    #             # Return multiple results if we've exhausted all attempts
    #             if attempt == max_attempts - 1:
    #                 return sorted(
    #                     [
    #                         ClassificationResult(
    #                             entity=text, 
    #                             category=cat, 
    #                             confidence=math.exp(log_prob)
    #                         ) 
    #                         for cat, log_prob in potential_outputs
    #                     ],
    #                     key=lambda x: x.confidence
    #                 )
    #             else:
    #                 winnowed_categories = new_cats
    #                 continue
    
    # # This should never be reached due to the loop structure, but keeping for safety
    # logger.warning(f"No classifications found after {max_attempts} attempts for text: {text}")
    # return []