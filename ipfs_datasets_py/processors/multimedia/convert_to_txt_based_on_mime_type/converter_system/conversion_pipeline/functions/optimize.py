import anyio
import concurrent.futures
import itertools

from functools import singledispatch
from typing import Any, AsyncGenerator, Callable, Coroutine, Generator, Iterable, overload

from pydantic import BaseModel

from pydantic_models.resource.resource import Resource
from utils.common.anyio_queues import AnyioQueue

class Pipeline(BaseModel):
    pass

# Wrapper classes for function overloading.
class ProcessInput(BaseModel):
    resource: Resource
    prefer: str = "processor"

class ThreadInput(BaseModel):
    resource: Resource
    prefer: str = "thread"


async def optimize(resources: Iterable[Resource], *, batch_size=1024, max_concurrency=5) -> AsyncGenerator:

    input_queue: AnyioQueue = AnyioQueue()

    for resource in resources:
        if getattr(resource, 'prefer', 'processor') == "thread":
            inp = ThreadInput(resource=resource)
        else:
            inp = ProcessInput(resource=resource)

        await input_queue.put(inp)

    while not input_queue.empty():
        async for inp, output in concurrently(input_queue, batch_size, max_concurrency):
            yield output

@singledispatch
async def concurrently(input_queue: AnyioQueue, batch_size: int, max_concurrency: int = 5):

    batch = []
    for _ in range(batch_size):
        inp = await input_queue.get()
        batch.append(inp)


async def concurrently_process(
        inputs: Iterable[ProcessInput] = None,
        *,
        max_concurrency: int = 5,
        ) -> AsyncGenerator:
    """
    Calls the pipeline on the values ``inputs`` using a process pool.
    Generates (input, output) tuples as the calls complete.
    """
    iter_inputs = iter(inputs)

    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(inp.resource.pipeline.run(), inp.resource): inp
            for inp in itertools.islice(iter_inputs, max_concurrency)
        }

        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )

            for future in done:
                original_input = futures.pop(future)
                yield original_input, future.result()

            for inp in itertools.islice(iter_inputs, len(done)):
                future = executor.submit(inp.pipeline, inp.resource)
                futures[future] = inp


async def concurrently_thread(
        inputs: Iterable[ThreadInput],
        *,
        max_concurrency=5,
        ) -> AsyncGenerator:
    """
    Calls the pipeline on the values ``inputs`` using a thread pool.
    Generates (input, output) tuples as the calls complete.
    """
    iter_inputs = iter(inputs)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(inp.resource.pipeline.run(), inp.resource): inp
            for inp in itertools.islice(iter_inputs, max_concurrency)
        }

        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )

            for fut in done:
                original_input = futures.pop(fut)
                yield original_input, fut.result()

            for inp in itertools.islice(iter_inputs, len(done)):
                fut = executor.submit(inp.pipeline, inp.resource)
                futures[fut] = inp


async def concurrently_handler(handler: Callable | Coroutine, inputs: Iterable, *, max_concurrency=5) -> AsyncGenerator:

    thread_handler_queue: AnyioQueue = AnyioQueue()
    process_handler_queue: AnyioQueue = AnyioQueue()

    prefer = getattr(inputs, 'prefer', 'thread')

    if prefer == "thread":
        await thread_handler_queue.put(inputs)
    elif prefer == "process":
        await process_handler_queue.put(inputs)
    else:
        raise ValueError("Invalid prefer value")

    thread_handler_inputs = [thread_handler_queue.get_nowait()]
    process_handler_inputs = [process_handler_queue.get_nowait()]

    thread_executor = concurrent.futures.ThreadPoolExecutor()
    process_pool = concurrent.futures.ProcessPoolExecutor()

    process_futures = {
        process_pool.submit(handler, inp): inp
        for inp in itertools.islice(iter(process_handler_inputs), max_concurrency)
    }

    thread_futures = {
        thread_executor.submit(handler, inp): inp
        for inp in itertools.islice(iter(thread_handler_inputs), max_concurrency)
    }

    all_futures = {**process_futures, **thread_futures}

    while all_futures:
        done, _ = concurrent.futures.wait(
            all_futures, return_when=concurrent.futures.FIRST_COMPLETED
        )

        for fut in done:
            original_input = all_futures.pop(fut)
            yield original_input, fut.result()
