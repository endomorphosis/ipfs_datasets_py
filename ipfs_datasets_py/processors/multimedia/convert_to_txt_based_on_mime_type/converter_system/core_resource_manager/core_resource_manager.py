

from functools import partial
from typing import Any, Callable, Coroutine, Generator, Optional


import duckdb


from pydantic_models.configs import Configs
from pydantic_models.resource.resource import Resource
from utils.errors.error_on_wrong_value import error_on_wrong_value
from utils.common.asyncio_coroutine import asyncio_coroutine
from utils.common.monads.async_ import Async


class CoreResourceManager:

    def __init__(self, configs: Configs):
        self.logger = configs.make_logger(self.__class__.__qualname__)
        self.free_sys_mem: int = None
        self.free_workers: int = None
        self.free_gpu_mem: int = None
        self.free_disk_space: int = None

    async def allocate_current_resources_to_queue(self):
        """

        """
        pass

    async def request_resources_from_pool(self):
        """
        
        """
        pass

    async def receive_free_resources_from_core(self, resource: Resource, success: bool):
        """

        """
        self.free_sys_mem += resource.total_sys_mem
        self.free_workers += resource.workers
        self.free_gpu_memory += resource.gpu_memory
        if success:
            self.free_disk_space -= resource.disk_space

