# """
# OpenAI integration module for text generation and embeddings.
# Provides isolated interface for OpenAI API interactions.
# """
# import os
# from typing import Any, Callable, Optional, Union


# from dependencies import dependencies

# # TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
# try:
#     import openai # TODO This should be checked in constants.py.
#     from openai import OpenAI, AsyncOpenAI
#     OPENAI_AVAILABLE = True
# except ImportError:
#     OPENAI_AVAILABLE = False

# try:
#     import tiktoken # TODO This should be checked in constants.py.
#     TIKTOKEN_AVAILABLE = True
# except ImportError:
#     TIKTOKEN_AVAILABLE = False

# from logger import logger
# from constants import MODEL_USAGE_COSTS_USD_PER_MILLION_TOKENS # TODO Import does not work currently. This should be fixed.


# def check_openai_available() -> bool:
#     """
#     Check if OpenAI library is available.
    
#     Returns:
#         bool: True if OpenAI is available, False otherwise
#     """
#     return OPENAI_AVAILABLE


# def check_tiktoken_available() -> bool:
#     """
#     Check if tiktoken library is available for token counting.
    
#     Returns:
#         bool: True if tiktoken is available, False otherwise
#     """
#     return TIKTOKEN_AVAILABLE


# def create_llm_client(api_key: Optional[str] = None) -> Optional[OpenAI]:
#     """
#     Create a synchronous OpenAI client.
    
#     Args:
#         api_key: OpenAI API key (uses environment variable if not provided)
        
#     Returns:
#         OpenAI client or None if library not available
#     """
#     if not OPENAI_AVAILABLE:
#         logger.error("OpenAI library not available. Please install with 'pip install openai'")
#         return None
    
#     try:
#         # Use provided API key or get from environment
#         key = api_key or os.environ.get("OPENAI_API_KEY")
#         if not key:
#             logger.error("OpenAI API key not provided and not found in environment")
#             return None
            
#         return OpenAI(api_key=key)
#     except Exception as e:
#         logger.error(f"Error creating OpenAI client: {e}")
#         return None


# def create_async_llm_client(api_key: Optional[str] = None) -> Optional[AsyncOpenAI]:
#     """
#     Create an asynchronous OpenAI client.
    
#     Args:
#         api_key: OpenAI API key (uses environment variable if not provided)
        
#     Returns:
#         AsyncOpenAI client or None if library not available
#     """
#     if not OPENAI_AVAILABLE:
#         logger.error("OpenAI library not available. Please install with 'pip install openai'")
#         return None

#     try:
#         # Use provided API key or get from environment
#         key = api_key or os.environ.get("OPENAI_API_KEY") # TODO This should be moved to constants.py.
#         if not key:
#             logger.error("OpenAI API key not provided and not found in environment")
#             return None
            
#         return AsyncOpenAI(api_key=key)
#     except Exception as e:
#         logger.error(f"Error creating AsyncOpenAI client: {e}")
#         return None


# def calculate_token_count(text: str, model: str = "gpt-3.5-turbo") -> Optional[int]: 
#     """
#     Calculate the number of tokens in a text string.
    
#     Args:
#         text: Text to calculate tokens for
#         model: Model to use for token calculation
        
#     Returns:
#         Number of tokens or None if tokenizer not available
#     """
#     if not TIKTOKEN_AVAILABLE:
#         logger.warning("Tiktoken library not available. Cannot calculate token count.")
#         return None
    
#     try:
#         encoding = tiktoken.encoding_for_model(model)
#         return len(encoding.encode(text))
#     except Exception as e:
#         logger.error(f"Error calculating token count: {e}")
#         return None


# def calculate_cost(
#     prompt: str, 
#     completion: str, 
#     model: str = "gpt-3.5-turbo"
# ) -> Optional[float]:
#     """
#     Calculate the cost of a prompt and completion.
    
#     Args:
#         prompt: Prompt text
#         completion: Completion text
#         model: Model used for generation
        
#     Returns:
#         Cost in USD or None if calculation failed
#     """
#     if not TIKTOKEN_AVAILABLE:
#         logger.warning("Tiktoken library not available. Cannot calculate cost.")
#         return None
    
#     if model not in MODEL_USAGE_COSTS_USD_PER_MILLION_TOKENS: # TODO This should be defined in constants.py. Also, this isn't imported currently.
#         logger.error(f"Model {model} not found in usage costs.")
#         return None
    
#     try:
#         # Get token counts
#         prompt_tokens = calculate_token_count(prompt, model)
#         completion_tokens = calculate_token_count(completion, model)
        
#         if prompt_tokens is None or completion_tokens is None:
#             return None
        
#         # Get costs per million tokens
#         prompt_cost = MODEL_USAGE_COSTS_USD_PER_MILLION_TOKENS[model]["input"]
#         completion_cost = MODEL_USAGE_COSTS_USD_PER_MILLION_TOKENS[model]["output"]
        
#         if completion_cost is None:
#             completion_cost = 0.0
        
#         # Calculate total cost
#         total_cost = (prompt_tokens / 1_000_000) * prompt_cost + (completion_tokens / 1_000_000) * completion_cost
#         return total_cost
#     except Exception as e:
#         logger.error(f"Error calculating cost: {e}")
#         return None


# async def generate_text(
#     client: AsyncOpenAI,
#     prompt: str,
#     system_prompt: str = "You are a helpful assistant.",
#     model: str = "gpt-3.5-turbo", # TODO This should be a positional argument. This will become outdated and burying it in the middle of the function signature is not a good idea.
#     temperature: float = 0.7,
#     max_tokens: int = 1000
# ) -> Optional[str]:
#     """
#     Generate text using OpenAI API.
    
#     Args:
#         client: AsyncOpenAI client
#         prompt: User prompt text
#         system_prompt: System prompt text
#         model: Model to use for generation
#         temperature: Temperature for generation
#         max_tokens: Maximum tokens to generate
        
#     Returns:
#         Generated text or None if generation failed
#     """
#     if not client:
#         logger.error("AsyncOpenAI client not provided")
#         return None
    
#     try:
#         response = await client.chat.completions.create(
#             model=model,
#             temperature=temperature,
#             max_tokens=max_tokens,
#             messages=[
#                 {"role": "system", "content": system_prompt},
#                 {"role": "user", "content": prompt}
#             ]
#         )
        
#         return response.choices[0].message.content
#     except Exception as e:
#         logger.error(f"Error generating text: {e}")
#         return None


# async def generate_embeddings(
#     client: AsyncOpenAI,
#     texts: Union[str, list[str]],
#     model: str = "text-embedding-ada-002" # TODO This should be a positional argument. This will become outdated and burying it in the middle of the function signature is not a good idea.
# ) -> Optional[list[list[float]]]:
#     """
#     Generate embeddings for text using OpenAI API.
    
#     Args:
#         client: AsyncOpenAI client
#         texts: Text or list of texts to generate embeddings for
#         model: Embedding model to use
        
#     Returns:
#         List of embedding vectors or None if generation failed
#     """
#     if not client:
#         logger.error("AsyncOpenAI client not provided")
#         return None
    
#     if isinstance(texts, str):
#         texts = [texts]
    
#     try:
#         # Clean and prepare texts
#         processed_texts = [text.strip() if text.strip() else " " for text in texts]
        
#         response = await client.embeddings.create(
#             input=processed_texts,
#             model=model
#         )

#         return [data.embedding for data in response.data]
#     except Exception as e:
#         logger.error(f"Error generating embeddings: {e}")
#         return None
