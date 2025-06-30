import concurrent.futures as cf
import itertools

try:
    import tqdm
except ImportError:
    raise ImportError("Please install the 'tqdm' package to use this module.")

def run_in_thread_pool(func, inputs, *, max_concurrency: int = 5, use_tqdm: bool = True):
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

    if use_tqdm:
        with tqdm.tqdm(total=len(inputs)) as pbar:
            with cf.ThreadPoolExecutor() as executor:
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
                        pbar.update(1)
                        yield original_input, fut.result()

                    for input in itertools.islice(func_inputs, len(done)):
                        fut = executor.submit(func, input)
                        futures[fut] = input
    else: # TODO Find a way to consolidate the two routes without duplicating code
        with cf.ThreadPoolExecutor() as executor:
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
                    pbar.update(1)
                    yield original_input, fut.result()

                for input in itertools.islice(func_inputs, len(done)):
                    fut = executor.submit(func, input)
                    futures[fut] = input