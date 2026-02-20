import anyio
from anyio import Semaphore
from typing import Any, Callable, Coroutine, Optional, Type, TypeVar


async def limiter(task, limit: Semaphore = None):
    if not isinstance(limit, Semaphore):
        if isinstance(limit, int):
            limit = anyio.Semaphore(limit)
        else:
            raise ValueError(f"The limit must be an instance of anyio.Semaphore or an integer, not {type(limit)}")
    async with limit:
        return await task


async def run_in_parallel_with_concurrency_limiter(
        func: Callable | Coroutine = None,
        input_list: list[Any] = None,
        concurrency_limit: int = 2,
        **kwargs: dict,
    ) -> list[Any]:
    """
    Runs the given function in parallel for each input, with a concurrency limit.

    Args:
        func (Callable | Coroutine): The function or coroutine to be executed in parallel.
        input_list (list[Any]): A list of input values to be processed.
        concurrency_limit (int): Maximum number of concurrent executions. Defaults to 2.
        **kwargs (dict): Additional keyword arguments to be passed to the function.

    Returns:
        list[Any]: Results from all function invocations in the same order as ``input_list``.
    """
    results: list[Any] = [None] * len(input_list)
    sem = anyio.Semaphore(concurrency_limit)

    async def _run_one(idx: int, inp: Any) -> None:
        async with sem:
            results[idx] = await func(inp, **kwargs)

    async with anyio.create_task_group() as tg:
        for idx, inp in enumerate(input_list):
            tg.start_soon(_run_one, idx, inp)

    return results