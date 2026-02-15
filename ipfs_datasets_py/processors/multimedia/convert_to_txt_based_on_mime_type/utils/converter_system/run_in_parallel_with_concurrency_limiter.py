import asyncio
from typing import Any, Callable, Coroutine, Optional, Type, TypeVar


from tqdm import asyncio as tqdm_asyncio


async def limiter(task, limit: asyncio.Semaphore = None):
    if not isinstance(limit, asyncio.Semaphore):
        if isinstance(limit, int):
            limit = asyncio.Semaphore(limit)
        else:
            raise ValueError(f"The limit must be an instance of asyncio.Semaphore or an integer, not {type(limit)}")
    async with limit:
        return await task


async def run_in_parallel_with_concurrency_limiter(
        func: Callable | Coroutine = None,
        input_list: list[Any] = None,
        concurrency_limit: int = 2,
        **kwargs: dict,
    ) -> None:
    """
    Runs the given function in parallel for each input, with a concurrency limit.

    Args:
        func (Callable | Coroutine): The function or coroutine to be executed in parallel.
        input_list (list[Any]): A list of input values to be processed.
        concurrency_limit (int): A semaphore to limit concurrent executions. Defaults to 2.
        **kwargs (dict): Additional keyword arguments to be passed to the function.

    Returns:
        None: This function doesn't return a value.

    Raises:
        ValueError: If the required arguments are not provided.

    Note:
        - The function uses a semaphore to limit concurrency.
        - Progress is displayed using tqdm.
        - Each function call receives its input value and any additional kwargs.
    """
    tasks = [
        func(inp, **kwargs) for inp in input_list
    ]

    limited_tasks = [
        limiter(task, limit=asyncio.Semaphore(concurrency_limit)) for task in tasks
    ]

    for future in tqdm_asyncio.tqdm.as_completed(limited_tasks):
        await future
    return