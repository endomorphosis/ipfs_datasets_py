import asyncio
from functools import wraps
import logging
from typing import Any, AsyncGenerator, Coroutine, Generator, Optional, TypeVar

from utils.common.monads.async_ import Async
from utils.common.asyncio_coroutine import asyncio_coroutine
from logger.logger import Logger

# Prevent circular imports
Resource = TypeVar('Resource')

logger = Logger(__name__)

@asyncio_coroutine
def log_errors(resource: Resource) -> Optional[Resource]:
    # NOTE This passes through errors as None.
    if isinstance(resource, Exception):
        logger.error(f"Error in Pipeline: {resource}")
        return None
    return resource 

# Start the pipeline by just returning the object itself.
# Equivalent to Just monad
async def start_pipeline(resource: Resource) -> Resource:
    logger.info(f"Starting conversion pipeline for file {resource.file_name}")
    return resource

async def load(resource: Optional[Resource]) -> Optional[Resource]:
    return await resource.load(resource)

async def convert(resource: Optional[Resource]) -> Optional[Resource]:
    return await resource.convert(resource)

async def save(resource: Optional[Resource]) -> Optional[Resource]:
    return await resource.save(resource)

@asyncio_coroutine
async def catch_exceptions(resource: Any) -> Optional[Resource]:
    return lambda x: None if isinstance(x, Exception) else resource

@asyncio_coroutine
def raise_exceptions(resource: Any) -> Optional[Resource]:
    if isinstance(resource, Exception):
        raise resource
    return resource

@asyncio_coroutine
def filter_exceptions(resource: Any) -> Optional[Resource]:
    return lambda x: filter(lambda: not isinstance(x, Exception), resource)

@asyncio_coroutine
def gather(l: Any) -> Generator[Optional[Any], None, None]:
    return (yield from asyncio.gather(*l, return_exceptions=True))

@asyncio_coroutine
async def success_or_failure(resource: Optional[Resource]) -> None:
    return lambda: (
        logger.info("Conversion succeeded."), resource
    ) if resource else (
        logger.error("Conversion failed."), None
    )

class Pipeline(object):

    def __init__(self, resource: Resource):
        self.gather = gather
        self.log_errors = log_errors
        self.load = resource.load

    def run(self, resource: Resource):
        pipeline = Async(
            start_pipeline(resource)
            ) >> self.gather >> log_errors >> (
                lambda resource: load(resource)
            ) >> gather >> log_errors >> (
                lambda resource: convert(resource)
            ) >> gather >> log_errors >> (
                lambda resource: save(resource)
            ) >> gather >> log_errors >> success_or_failure
        return pipeline.future