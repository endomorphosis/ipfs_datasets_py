import anyio
from collections import Counter
import concurrent.futures as cf
import itertools
import logging
from queue import Queue
import time
import threading
from typing import Any, AsyncGenerator, AsyncIterator, AsyncIterable, Generator, Iterator, Iterable, Optional, TypeVar

from utils.common.anyio_queues import AnyioQueue

from pydantic_models.configs import Configs
from pydantic_models.resource.resource import Resource
from utils.common.monads.async_ import Async
from logger.logger import Logger

T = TypeVar('T')

logger = Logger(__name__)


class AsyncStreamProcessor:
    """Processes a stream of resources in parallel with controlled concurrency"""
    
    def __init__(self, max_workers: int, queue_size: int = 100):
        self.executor = cf.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='stream_worker'
        )
        self.queue: AnyioQueue = AnyioQueue(maxsize=queue_size)
        self.processing = set()
        self.done = anyio.Event()

    async def feed_queue(self, iterator: Iterator[T]) -> None:
        """Feed items from iterator into the async queue"""
        try:
            for item in iterator:
                await self.queue.put(item)
        finally:
            await self.queue.put(None)  # Sentinel to signal end of stream

    async def process_stream(self, 
                           source: Iterator[T],
                           processor: callable) -> AsyncGenerator[Counter, None]:
        """Process items from the stream with parallel execution"""
        results: list = []
        
        async def _feed_and_process() -> None:
            # Feed queue in background while consuming in the same task group
            async with anyio.create_task_group() as tg:
                tg.start_soon(self.feed_queue, source)
                # Consume while feeder is running
                while True:
                    item = await self.queue.get()
                    if item is None:
                        break
                    future = self.executor.submit(processor, item)
                    self.processing.add(future)
                    done, self.processing = cf.wait(
                        self.processing, timeout=0, return_when=cf.FIRST_COMPLETED
                    )
                    for fut in done:
                        try:
                            results.append(fut.result())
                        except Exception as e:
                            print(f"Error processing item: {e}")
                # Wait for remaining tasks
                if self.processing:
                    done, _ = cf.wait(self.processing)
                    for fut in done:
                        try:
                            results.append(fut.result())
                        except Exception as e:
                            print(f"Error processing item: {e}")
                self.done.set()

        await _feed_and_process()
        for r in results:
            yield r

class ResourceGenerator:
    """Simulates a source of resources being generated"""
    
    def __init__(self, total_resources: int, delay: float = 0.1):
        self.total = total_resources
        self.delay = delay
        self.queue = Queue()
        self.thread = None
        
    def generate_resources(self):
        """Generate resources in a separate thread"""
        for i in range(self.total):
            time.sleep(self.delay)  # Simulate work
            resource = Resource(thread=i)
            self.queue.put(resource)
    
    def start(self):
        """Start the resource generation thread"""
        self.thread = threading.Thread(target=self.generate_resources)
        self.thread.start()
    
    def __iter__(self):
        """Make this an iterator that yields resources as they're generated"""
        remaining = self.total
        while remaining > 0:
            resource = self.queue.get()
            yield resource
            remaining -= 1

from converter_system.file_path_queue.file_path_queue import FilePathQueue
from converter_system.core_error_manager.core_error_manager import CoreErrorManager
from converter_system.core_resource_manager.core_resource_manager import CoreResourceManager

class Core:

    def __init__(self, configs: Configs):

        self.file_path_queue = FilePathQueue(configs)
        self.core_error_manager = CoreErrorManager(configs)
        self.core_resource_manager = CoreResourceManager(configs)

        self.semaphore = anyio.Semaphore(configs.concurrency_limit)

        self.stream_processor = AsyncStreamProcessor(
            max_workers=configs.concurrency_limit # TODO
        )

    async def run_pipelines_in_parallel(self, resource_stream: AsyncIterable[Resource]):
        """
        Run a stream of pipelines in parallel using both process and thread pools with just-in-time scheduling.
        
        Args:
            resource_stream: AsyncGenerator yielding resources to process
            process_concurrency: Max number of concurrent processes
            thread_concurrency: Max number of concurrent threads
        
        Yields:
            Tuples of (input, output) as processing completes
        """
        pass

    async def run_pipeline_in_process_pool(self, resource_stream: AsyncIterable[Resource]):
        """
        Run a pipeline in a process pool.

        ``handler`` should be a function that takes a single input, which is the
        individual values in the iterable ``inputs``.

        Generates (input, output) tuples as the calls to ``handler`` complete.

        See https://alexwlchan.net/2019/10/adventures-with-concurrent-futures/ for an explanation
        of how this function works.
        """
        # Make sure we get a consistent iterator throughout, rather than
        # getting the first element repeatedly.
        iter_inputs = iter(resource_stream)

        with cf.ProcessPoolExecutor() as executor:

            # Schedule the first N futures.  We don't want to schedule them all
            # at once, to avoid consuming excessive amounts of memory.
            futures = {
                executor.submit(
                    input.resource.pipeline.run(), 
                    input.resource
                ): input
                for input in itertools.islice(iter_inputs, self.core_resource_manager.free_workers)
            }

            # Wait for the next future to complete. 
            while futures:
                done, pending = cf.wait(
                    futures, return_when=cf.FIRST_COMPLETED
                )

                for future in done:
                    original_input = futures.pop(future)
                    yield original_input, future.result()

                # Schedule the next set of futures.  We don't want more than N futures
                # in the pool at a time, to keep memory consumption down.
                for input in itertools.islice(iter_inputs, len(done)):
                    future = executor.submit(
                        input.resource.pipeline.run(), 
                        input.resource
                    )
                    futures[future] = input


    async def run_pipeline_in_thread_pool(self, 
                resource_stream: AsyncIterable[Resource], 
                loop: AbstractEventLoop
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
        iter_inputs = iter(resource_stream)

        with cf.ThreadPoolExecutor() as executor:
            futures = {
                loop.run_in_executor(
                    executor, 
                    input.resource.pipeline.run(), 
                    input.resource
                ): input
                for input in itertools.islice(iter_inputs, self.core_resource_manager.free_workers)
            }

            while futures:
                done, _ = cf.wait(
                    futures, return_when=cf.FIRST_COMPLETED
                )

                for fut in done:
                    original_input = futures.pop(fut)
                    yield original_input, fut.result()

                for input in itertools.islice(iter_inputs, len(done)):
                    fut = loop.run_in_executor(
                        executor, input.resource.pipeline.run(), 
                        self.core_resource_manager.free_workers
                    )
                    futures[fut] = input



    async def process_stream(self, resource_stream: Iterator[Resource]) -> AsyncIterator[Counter]:
        """
        Process a stream of resources in parallel
        """
        async for result in self.stream_processor.process_stream(
            resource_stream,
            lambda r: self.loop.run_until_complete(self.process_resource(r))
        ):
            yield result


    async def optimize(resources: Iterable[Resource], *, batch_size=1024) -> AsyncGenerator:

        input_queue: AnyioQueue = AnyioQueue()

        for resource in resources:
            if resource.prefer == "thread":
                input = ThreadInput(resource=resource)
            else:
                input = ProcessInput(resource=resource)

            await input_queue.put(input)

        while not input_queue.empty():
            for input, output in concurrently(input_queue, batch_size, max_concurrency):
                yield output







# Usage example:
if __name__ == "__main__":
    configs = Configs(concurrency_limit=10)
    core = Core(configs)
    
    # Create resource generator
    generator = ResourceGenerator(total_resources=100)
    generator.start()
    
    async def main():
        results = []
        async for result in core.process_stream(generator):
            results.append(result)
            print(f"Processed resource, total complete: {len(results)}")

    # Run the pipeline
    core.loop.run_until_complete(main())