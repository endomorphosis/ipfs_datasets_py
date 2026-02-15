import asyncio
from asyncio import AbstractEventLoop
import concurrent.futures
import itertools

from functools import singledispatch
from typing import Any, AsyncGenerator, Callable, Coroutine, Generator, Iterable, overload


from pydantic import BaseModel


from pydantic_models.resource.resource import Resource

class Pipeline(BaseModel):
    pass

# Wrapper classes for function overloading.
class ProcessInput(BaseModel):
    resource: Resource
    prefer: str = "processor"

class ThreadInput(BaseModel):
    resource: Resource
    prefer: str = "thread"


async def optimize(resources: Iterable[Resource], *, batch_size=1024) -> AsyncGenerator:

    input_queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    for resource in resources:
        if resource.prefer == "thread":
            input = ThreadInput(resource=resource)
        else:
            input = ProcessInput(resource=resource)

        await input_queue.put(input)

    while input_queue:
        for input, output in concurrently(input_queue, batch_size, max_concurrency, loop):
            yield output

@singledispatch
async def concurrently(input_queue: asyncio.Queue, batch_size: int, max_concurrency: int = 5):

    batch = []
    for _ in range(batch_size):
        input = await input_queue.get()
        batch.append(input)


async def concurrently(
        inputs: Iterable[ProcessInput] = None, 
        *, 
        max_concurrency: int = 5,
        loop: AbstractEventLoop = None
        ) -> AsyncGenerator:
    """
    Calls the function ``handler`` on the values ``inputs``.

    ``handler`` should be a function that takes a single input, which is the
    individual values in the iterable ``inputs``.

    Generates (input, output) tuples as the calls to ``handler`` complete.

    See https://alexwlchan.net/2019/10/adventures-with-concurrent-futures/ for an explanation
    of how this function works.
    """
    # Make sure we get a consistent iterator throughout, rather than
    # getting the first element repeatedly.
    iter_inputs = iter(inputs)

    with concurrent.futures.ProcessPoolExecutor() as executor:

        # Schedule the first N futures.  We don't want to schedule them all
        # at once, to avoid consuming excessive amounts of memory.
        futures = {
            executor.submit(input.resource.pipeline.run(), input.resource): input
            for input in itertools.islice(iter_inputs, max_concurrency)
        }

        # Wait for the next future to complete.
        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )

            for future in done:
                original_input = futures.pop(future)
                yield original_input, future.result()

            # Schedule the next set of futures.  We don't want more than N futures
            # in the pool at a time, to keep memory consumption down.
            for input in itertools.islice(iter_inputs, len(done)):
                future = executor.submit(input.pipeline, input.resource)
                futures[future] = input

@overload
async def concurrently(
        inputs: Iterable[ThreadInput], 
        *, 
        max_concurrency=5, 
        loop: AbstractEventLoop = None
        ):
    """
    Calls the function ``handler`` on the values ``inputs``.

    ``handler`` should be a function that takes a single input, which is the
    individual values in the iterable ``inputs``.

    Generates (input, output) tuples as the calls to ``handler`` complete.

    See https://alexwlchan.net/2019/10/adventures-with-concurrent-futures/ for an explanation
    of how this function works.

    """
    # Make sure we get a consistent iterator throughout, rather than
    # getting the first element repeatedly.
    iter_inputs = iter(inputs)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            loop.run_in_executor(executor, input.resource.pipeline.run(), input.resource): input
            for input in itertools.islice(iter_inputs, max_concurrency)
        }

        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )

            for fut in done:
                original_input = futures.pop(fut)
                yield original_input, fut.result()

            for input in itertools.islice(iter_inputs, len(done)):
                fut = loop.run_in_executor(
                    executor, input.pipeline, input.resource
                )
                futures[fut] = input















@overload
async def concurrently(handler: Callable | Coroutine, inputs: Iterable, *, max_concurrency=5) -> AsyncGenerator:

    # Wrap the input in a Input class, it isn't already.
    # This is likely being pulled from a generator.
    thread_handler_queue = asyncio.Queue()
    process_handler_queue = asyncio.Queue()

    inputs = Input(input=inputs, pipeline=handler, prefer="thread")
    loop = asyncio.get_running_loop()

    # Sort the that they inputs so that it
    if inputs.prefer == "thread":
        await thread_handler_queue.put(inputs.input)
    elif inputs.prefer == "process":
        await process_handler_queue.put(inputs.input)
    else:
        raise ValueError("Invalid prefer value")

    # Make sure we get a consistent iterator throughout, rather than
    # getting the first element repeatedly.
    thread_handler_inputs = iter(thread_handler_queue.get_nowait(), None)
    process_handler_inputs = iter(process_handler_queue.get_nowait(), None)

    thread_executor = concurrent.futures.ThreadPoolExecutor()
    process_pool = concurrent.futures.ProcessPoolExecutor()

    process_futures = {
        process_pool.submit(handler, input): input
        for input in itertools.islice(process_handler_inputs, max_concurrency)
    }

    thread_futures = {
        loop.run_in_executor(thread_executor, handler, input): input
        for input in itertools.islice(thread_handler_inputs, max_concurrency)
    }

    while process_futures and thread_futures:
        done, _ = concurrent.futures.wait(
            futures, return_when=concurrent.futures.FIRST_COMPLETED
        )

        for fut in done:
            original_input = futures.pop(fut)
            yield original_input, fut.result()

        for input in itertools.islice(iter_inputs, len(done)):
            fut = executor.submit(handler, input)
            futures[fut] = input
