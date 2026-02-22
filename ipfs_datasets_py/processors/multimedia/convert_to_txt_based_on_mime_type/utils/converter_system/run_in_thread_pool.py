import concurrent.futures as cf
import itertools
from typing import Callable, Iterable, Generator


def run_pipeline_in_thread_pool(inputs: Iterable[tuple], max_concurrency=5) -> Generator[tuple, None, None]:
    """
    Runs a pipeline of functions in a thread pool.

    Args:
        inputs (Iterable[tuple]): An iterable of tuples.
            The first tuple element is a function, and the second is its input.
    """
    func_inputs = iter(inputs)

    with cf.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(input[0], input[1]): input
            for input in itertools.islice(func_inputs, max_concurrency)
            if callable(input[0])
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


def run_in_thread_pool(handler, inputs, *, max_concurrency=5):
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
    handler_inputs = iter(inputs)

    with cf.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(handler, input): input
            for input in itertools.islice(handler_inputs, max_concurrency)
        }

        while futures:
            done, _ = cf.wait(
                futures, return_when=cf.FIRST_COMPLETED
            )

            for fut in done:
                original_input = futures.pop(fut)
                yield original_input, fut.result()

            for input in itertools.islice(handler_inputs, len(done)):
                fut = executor.submit(handler, input)
                futures[fut] = input