"""Thread-pool executor with optional tqdm progress bar.

Bug #17 fix: removed the erroneous ``pbar.update(1)`` call in the
``use_tqdm=False`` branch where ``pbar`` is not defined.
"""

from __future__ import annotations

import concurrent.futures as cf
import itertools
from typing import Any, Callable, Generator, Iterable

try:
    import tqdm as _tqdm_module
    _TQDM_AVAILABLE = True
except ImportError:
    _TQDM_AVAILABLE = False


def run_in_thread_pool(
    func: Callable,
    inputs: Iterable,
    *,
    max_concurrency: int = 5,
    use_tqdm: bool = True,
) -> Generator[tuple[Any, Any], None, None]:
    """Call *func* on each item in *inputs* using a bounded thread pool.

    Yields ``(input, result)`` tuples as each call completes.

    Args:
        func: Single-argument callable to apply to each input.
        inputs: Iterable of inputs.
        max_concurrency: Maximum number of simultaneous threads.
        use_tqdm: When ``True`` (and ``tqdm`` is available), display a
            progress bar.

    Yields:
        ``(original_input, func(original_input))`` pairs in completion order.
    """
    func_inputs = iter(inputs)
    # Materialise just enough to determine the total count for tqdm.
    input_list = list(func_inputs)
    total = len(input_list)
    func_inputs = iter(input_list)

    show_progress = use_tqdm and _TQDM_AVAILABLE

    def _run(executor: cf.ThreadPoolExecutor, pbar=None):
        futures: dict[cf.Future, Any] = {
            executor.submit(func, inp): inp
            for inp in itertools.islice(func_inputs, max_concurrency)
        }
        while futures:
            done, _ = cf.wait(futures, return_when=cf.FIRST_COMPLETED)
            for fut in done:
                original_input = futures.pop(fut)
                if pbar is not None:
                    pbar.update(1)
                yield original_input, fut.result()
            for inp in itertools.islice(func_inputs, len(done)):
                new_fut = executor.submit(func, inp)
                futures[new_fut] = inp

    with cf.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        if show_progress:
            with _tqdm_module.tqdm(total=total) as pbar:
                yield from _run(executor, pbar)
        else:
            # Bug #17 fix: no pbar.update() call here — pbar does not exist.
            yield from _run(executor, pbar=None)
