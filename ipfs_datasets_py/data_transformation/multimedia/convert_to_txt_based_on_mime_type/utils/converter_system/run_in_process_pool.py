

import concurrent.futures as cf
import itertools
from typing import Callable, Generator, Iterable


def run_pipeline_in_process_pool(inputs: Iterable[tuple], max_concurrency: int = 5) -> Generator[tuple, None, None]:
    """
    Runs a pipeline of functions in a process pool.
    
    Args:
        inputs (Iterable[tuple]): An iterable of tuples. 
            The first tuple element is a function, and the second is its input.
        max_concurrency (int): The maximum number of concurrent processes.

    Yields:
        tuple: A tuple of the original input and the result of the function call.
    """
    func_inputs = iter(inputs)

    with cf.ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(input[0], input[1]): input
            for input in itertools.islice(func_inputs, max_concurrency)
            if isinstance(input[0], Callable) # Filter out non-callable objects
        }

        while futures:
            done, _ = cf.wait(
                futures, return_when=cf.FIRST_COMPLETED
            )

            for fut in done:
                original_input = futures.pop(fut)
                yield original_input, fut.result()

            for input in itertools.islice(func_inputs, len(done)):
                fut = executor.submit(input[0], input[1])
                futures[fut] = input


def run_in_process_pool(func, inputs, *, max_concurrency=5):
    """
    Calls the function ``func`` on the values ``inputs``.

    ``func`` should be a function that takes a single input, which is the
    individual values in the iterable ``inputs``.

    Generates (input, output) tuples as the calls to ``func`` complete.

    See https://alexwlchan.net/2019/10/adventures-with-concurrent-futures/ for an explanation
    of how this function works.

    """
    # Make sure we get a consistent iterator throughout, rather than
    # getting the first element repeatedly.
    func_inputs = iter(inputs)

    with cf.ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(func, input): input
            for input in itertools.islice(func_inputs, max_concurrency)
        }

        while futures:
            done, _ = cf.wait(
                futures, return_when=cf.FIRST_COMPLETED
            )

            for fut in done:
                original_input = futures.pop(fut)
                yield original_input, fut.result()

            for input in itertools.islice(func_inputs, len(done)):
                fut = executor.submit(func, input)
                futures[fut] = input

