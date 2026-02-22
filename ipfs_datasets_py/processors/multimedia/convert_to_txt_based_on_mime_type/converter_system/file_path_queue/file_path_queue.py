
import anyio
import concurrent.futures
import itertools
from functools import singledispatch
from typing import Any, AsyncGenerator, Optional
from pydantic import BaseModel
from utils.common.anyio_queues import AnyioQueue


from pydantic_models.resource.resource import Resource
from pydantic_models.configs import Configs


class Resource(BaseModel):
    pipeline: Any
    prefer: str = "processor"

class ProcessInput(BaseModel):
    resource: Resource
    prefer: str = "processor"

class ThreadInput(BaseModel):
    resource: Resource
    prefer: str = "thread"


class FilePathQueue:

    def __init__(self, configs: Configs):
        self.batch_size = configs.batch_size
        self.process_queue: 'AnyioQueue[ProcessInput]' = AnyioQueue(maxsize=configs.max_queue_size)
        self.thread_queue: 'AnyioQueue[ThreadInput]' = AnyioQueue(maxsize=configs.max_queue_size)
        
    async def core_resource_manager_interface(self, resource: Optional[Resource]):
        """
        Get a steady stream of resources from the Core Resource Manager.
        
        """
        while True:
            if resource:
                item_count = sum(self.process_queue.qsize(), self.thread_queue.qsize())
                if item_count < self.batch_size:
                    self.add_resource(resource)

    async def add_resource(self, resource: Resource):
        """
        Add resources to the respective queues.

            Depending on their type, they will be added to the process queue or the thread queue.
            The process queue is for resources that will be run in a Process Pool, since they may be computationally heavy.
            The thread queue is for resources that will be run in a Thread Pool, since they may be I/O bound due to API calls.
        """
        if resource.prefer == "thread":
            await self.thread_queue.get(
                ThreadInput(resource=resource)
            )
        else:
            await self.process_queue.get(
                ProcessInput(resource=resource)
            )

    def get_queues(self) -> tuple['AnyioQueue[ProcessInput]', 'AnyioQueue[ThreadInput]']:
        return self.process_queue, self.thread_queue


    def send_to_the_core(self) -> AsyncGenerator[Resource, None]:
        """
        Send resources in the queues to the Core Converter System.
        """
        pass