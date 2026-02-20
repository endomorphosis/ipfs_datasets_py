import anyio
from utils.common.anyio_queues import AnyioQueue
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
import hashlib
import logging
import os
import mimetypes
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Annotated, Any, Callable, Coroutine, Generic, IO, Iterable, Never, Optional, TypeVar
from urllib.parse import urlparse
from uuid import UUID

from multiprocessing.pool import Pool, ThreadPool
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Lock


import aiohttp
import duckdb
import requests
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException
from playwright.async_api import (
    Response as PlaywrightResponse,
    async_playwright, 
    Browser,
    BrowserContext,
    Page,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    Playwright,
    PlaywrightContextManager,
)
from pydantic import BaseModel, Field, HttpUrl, EmailStr, PrivateAttr


from external_interface.api_manager.api_manager import ApiConnection, ApiManager
from pydantic_models.resource.resource import Resource
from pydantic_models.configs import Configs
from logger.logger import Logger
logger = Logger(__name__)

# DocumentConverterResult: TypeAlias = Any

"""
Route the input to the appropriate converter based on its ending.

Args:
    input (str): The filename to be routed.

Returns:
    The mime-type of the file.
"""

class DocumentConverterResult(BaseModel):
    title: Optional[str] = None
    text_content: str = ""


class MachineLearningModel:
    pass



def make_sha256_hash(data: Any) -> str:
    return hashlib.sha256(str(data).encode())

def make_hash_tree(*args: Iterable[Any]):
    hashed_objects = [
        make_sha256_hash(arg) for arg in args
    ]

from duckdb.typing import VARCHAR

from utils.main.run_with_argparse import run_with_argparse

def _program_was_started_from_command_line() -> bool:
    """Checks if the program was started from the command line."""
    return len(sys.argv) > 1

from utils.common.next_step import next_step

from deprecated.file_paths_manager_mk1 import FilePathsManager
from typing import AsyncGenerator
T = TypeVar('T')  # Generic type for pooled resources
from enum import Enum, auto

CustomClass = TypeVar("CustomClass")







class ResourceState(Enum):
    AVAILABLE = auto()
    IN_USE = auto()
    DISPOSED = auto()

class ResourceType(Enum):
    PERSISTENT = auto()  # Resources that should be kept alive (like LLMs)
    TRANSIENT = auto()   # Resources that can be destroyed and recreated (threads)
    CONSUMABLE = auto() # Resources that can be exactly once ()

import subprocess as sp
import os

import functools

import multiprocessing
from multiprocessing import Process, Queue, Pipe

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

pool = ProcessPoolExecutor()

class SystemResource(BaseModel):
    pass




class PooledResource(BaseModel):

    created_at: float = Field(default_factory=lambda: time.time())
    last_used_at: float = Field(default_factory=lambda: time.time())
    state: ResourceState = Field(default_factory=ResourceState.AVAILABLE)
    use_count: int = Field(default=0)
    resource_type: Optional[ResourceType] = None

    _resource: Optional[T] = PrivateAttr(default=None)

    @cached_property
    def resource(self) -> T:
        self.last_used_at = time.time()
        self.state = ResourceState.IN_USE
        return self._resource

    @resource.setter()
    def resource(self, value) -> None:
        self._resource = self.validate(value)

    @resource.deleter()
    def resource(self) -> None:
        if self.resource_type is ResourceType.PERSISTENT:
            self.reset(self)
        elif self.resource_type is ResourceType.TRANSIENT:
            self.destroy(self)
        else:
            raise AttributeError("Resource lacks a type")
        self.state = ResourceState.DISPOSED

    def create(self) -> T:
        """
        """
        pass

    def reset(self) -> bool:
        """
        Reset the resource to a clean state without destroying it.

        Returns:
            bool: True if reset was successful, False if resource needs to be re-created.
        """
        pass

    def validate(self, value) -> bool:
        """
        Validate if a given resource is healthy.
        Called when a resource the following happens:
            - The resource is returned to the Core Resource Manager.
            - The resource is first created by the External Resource Manager.
            - The resources has spent X amount of time in its respective pool.
            - The resources enters the Health Monitor class.

        Returns:
            bool: True if the resources is healthy, else False.
        """

    def destroy(self) -> bool:
        """
        Destroy a resource.
        
        Returns:
            bool: True if reset was successful, False if resource needs to be re-created.
        """
        pass

    def clean_up(self) -> bool:
        """
        Cleanup the resource when destroying it.
        """
        pass





from typing import Awaitable, Coroutine

from dataclasses import dataclass
from typing import Generic, TypeVar, Optional, Callable, Awaitable, Protocol
from contextlib import AbstractContextManager
import anyio
from abc import ABC, abstractmethod

class Disposable(Protocol):
    async def dispose(self) -> None: ...


class ManagedResource(Generic[T]):
    """
    Wrapper for resources that need managed cleanup.
    """
    def __init__(self, value: T, cleanup: Optional[Callable[[], Awaitable[None]]] = None):
        self.value = value
        self._cleanup = cleanup

    async def dispose(self) -> None:
        if self._cleanup:
            await self._cleanup()



class Converter:

    def __init__(self, resource: Resource, configs: Configs):
        self.configs = configs
        #self.markitdown = MarkItDownAsync()

    async def source(self) -> str:
        pass

    async def sink(self) -> str:
        pass

    async def convert(self, resource: str) -> DocumentConverterResult:
        """
        Convert a document from one format to plaintext.
        The format of the plaintext is Markdown.
        
        
        """
        pass


from pools.non_system_resources.api_connection_pool.api_connections_pool import ApiConnectionPool



class Pool():

    def __init__(self, resource: Resource, configs: Configs):
        self.configs = configs

        self.pool_name: str = None

        self.max_allowed_gpu_usage_in_bytes: int = None
        self.current_gpu_mem_in_bytes: int = None
        self.available_sys_mem_in_bytes: int = None
        self.max_allowed_sys_mem_in_bytes: int = None
        self.max_allowed_api_connections: int = None 
        self.available_api_connections: int = None
        self.func: dict[str, int] = None
        self.max_allowed_file_paths: list[str]
        self.available_file_paths: set[str]

        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """
        Start up the pool with the initial resources.
            For pools involving system resource, this involves setting their counters to the maximum allowed.
            For the file path pool, this involves getting the CIDs in the current batch and storing them in the pool.
            For the API connection pool, this involves taking the Connection objects and storing them in a Queue with a lock.
                It should be based on the Pool system 
        Args:
            None

        Returns:
            None
        """
        pass

    def put(self, resource: Resource):
        """
        Put a Resource back into the pool.
            For pools involving system resource, this involves incrementing their counters.
            For the file path pool, this involves adding the CID back to the pool.
            For the API connection pool, this involves putting the Connection object back into the Queue.
        
        """
        pass

    def dispense(self) -> Generator[Resource]:
        """
        Dispense a resource from the pool.
        It does so by creating a Resource on-the-fly and yielding it.

        """
        pass

    @property
    def is_not_full(self) -> bool:
        pass

    @property
    def is_empty(self) -> bool:
        pass


from types import TracebackType
import queue
import random
import re
import threading

from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, NoReturn, Optional, Tuple, Type, Union
from uuid import uuid4


API_CONNECTION_POOL_LOCK = threading.RLock()
CNX_POOL_MAXSIZE = 32
CNX_POOL_MAXNAMESIZE = 64
CNX_POOL_NAMEREGEX = re.compile(r"[^a-zA-Z0-9._:\-*$#]")
ERROR_NO_CEXT = "MySQL Connector/Python C Extension not available"
# MYSQL_CNX_CLASS: Union[type, Tuple[type, ...]] = (
#     MySQLConnection if CMySQLConnection is None else (MySQLConnection, CMySQLConnection)
# )

_CONNECTION_POOLS: Dict[str, ApiConnectionPool] = {}


class Processor():
    pass


class Pools():

    def __init__(self, configs: Configs, health_monitor: 'PoolHealthMonitor'):
        self.configs = configs

        # Special pool for API connections.
        self.api_pool: ApiConnectionPool = self.create_api_pool(configs)

        self.func_pool: Pool = self.create_pool(configs)
        self.gpu_mem_pool: Pool = self.create_pool(configs)
        self.thread_pool: Pool = self.create_pool(configs)
        self.sys_mem_pool: Pool = self.create_pool(configs)
        self.file_path_pool: Pool = self.create_pool(configs)

    def create_pool(self, configs: Configs) -> Pool:
        """
        Instantiate a pool with the given configuration.
        Save for File Paths and API connections, each pool consists of a series of counters. 
           Each counter's upper bound is determined by the maximum values specified in the Configs object. 
           or whatever resources the system has available, whichever is smaller.
           For instance, if the config specifies that the maximum available memory is 1024 MBs, 
           but the system only has 512 MB, then the pool's maximum will only be 512 MBs.
    
        When a Resource object is created, the counter is decremented by the amount of resources 
            that are allocated to the resource.

        When a Resource is consumed by a function, the Pool counter is *not* automatically incremented.
            Instead, the freed resource goes to the Core Resource Manager to be re-allocated to another 
            file in the File Path Queue. If no files in the Queue need that resource, then the resource 
            is returned to the pool, and the Pool's counter is incremented.
            For instance, if the Queue is filled with files that don't require an API connection to convert,
            the connection is returned to the pool and its counter is incremented.

        When a given Pool's counter is at zero, the creation of that Resource will be blocked until resources 
            are returned to the pool, or new Resources are provided by the External Resource Manager, 
            which ever happens sooner. This will have the side-effect of dynamically limiting 
            the number of files that can be processed at any one time.
        
        When a given Pool's counter is at its maximum, returned Resources will be 'thrown away' and the counter 
           remains the same amount. For connections, this means that the connection will be closed (???).

        For API connections, the pool is a traditional connection pool a la MySQL. 
            When a Resource object is created, a Connection is allocated to the Resource.
            When the Resource object is consumed, the connection is returned to the pool.
            If the pool is empty, a new connection is requested from the External Resource Manager 
            and added to the pool.

        API connections are refreshed periodically to ensure that they are still valid.
            This is especially important for loaded models like LLMs.

        Args:
            configs (Configs): The configuration for the pool.

        Returns:
           Pool: The instantiated pool.
        """
        return Pool(configs)

    def create_api_pool(self) -> 'Pool':
        """
        """

    def check_what_resources_the_core_manager_needs(self) -> bool:
        """
        Query the Core Manager to see if it needs any Resources.

        Returns:
            bool: True if any pool is not full or empty, and False if all pools are full.
        """
        pass

    def make_a_resource() -> Generator['Resource', None, None]:
        """
        Construct a Resource by taking items from the pools, then yield it.
        When a resource is yielded, it is removed from the pools, and the pool states are updated to reflect
        that the resources have been allocated.

        NOTE: As a guideline, we should over-allocate resources rather than under-allocate.
            Over-allocating is less efficient, but more robust, since a process is less likely to fail
            due to a lack of resources. 

        Returns:
            resource (Resource): A Resource to be taken from the pools.
            Resource is a pydantic base model that can contain any combination of the following:
            - A FilePath pydantic model pointing to an input file. 
                This consists of a path, a CID, and other attributes that are calculated on the fly.
            - References to a series of functions to be executed in order to convert a file.
            - An API connection that is needed by one or more of the functions in order to convert a file.
                As functions are sequential, the API connection is only released after the last function 
                that uses an API connection has been executed.
            - Total system memory (in bytes) necessary to execute the conversion functions.
            - GPU memory (in bytes) necessary to execute the conversion functions. This is primarily
                for conversion functions that rely on local ML models such as Whisper, or a V-LLM.
            - Number of CPU threads necessary to execute the conversion functions.

        Example Return:
            >>> resource = acquire()
            print(resource.model_dump)
            >>> {
                    'path': FilePath('path/to/file'),
                    'api_connection': 1,
                    'threads': 1,
                    'func': [{
                                'step': 1
                                'name': 'open_json',
                                'sys_mem': 512
                            },
                            {
                                'step': 2
                                'name': 'convert_json',
                                'sys_mem': 512,
                                'api_connection': 1,
                                'gpu_mem': 1024
                            },
                            {
                                'step': 3
                                'name': 'save_json',
                                'sys_mem': 256
                            }], 
                    'gpu_mem': 1024, 
                    'sys_mem': 1280
                }
        """
        pass

    def release() -> None:
        pass

    def receive(self, resource: Resource) -> None:
        """
        Receive a resource and put it back into the appropriate pool.

        Args:
            resource (Resource): Resources to be returned to the pool.
            A resource is a pydantic base model that can contain a combination of the following:
            - An API connection
            - References to a Function
            - Available GPU memory (in bytes)
            - CPU Threads
            - Available System memory (in bytes)
        """
        if resource.api_connection:
            self.api_pool.put(resource)
        if resource.func:
            self.func_pool.put(resource)
        if resource.gpu_mem:
            self.gpu_mem_pool.put(resource)
        if resource.thread:
            self.thread_pool.put(resource)
        if resource.sys_mem:
            self.sys_mem_pool.put(resource)

    def send_to_core_manager(self) -> Resource:
        """
        Send a Resource to the Core Manager.
        
        """
        pass

    def need_a_resource(self):
        """
        
        """
        pass



class PoolHealthMonitor:

    def __init__(self, configs: Configs):
        self.configs = configs

    def check_pool_health(configs) -> None:
        pass

class ExternalResourcesManager():

    def __init__(self, configs: Configs, utility_classes: dict[str, CustomClass]):
        self.configs = configs
        self._resource_holder = []
        self.file_path_manager = utility_classes.pop("file_path_manager")
        self.api_connections = utility_classes.pop("api_connections")
        self.system_resources = utility_classes.pop("system_resources")

    def create_resource(self, paths, system_resources, api_connections) -> AsyncGenerator[None, None, Resource]:
        """
        Create a Resource from the available paths, system resources, and API connections.
        
        """
        pass


    def gets_back(self, resource: Resource) -> None:
        """
        
        """
        self._resource_holder.append(resource)


    async def out(self) -> Resource:
        """
        
        """
        pass


    def has_resources(self) -> bool:
        """
        
        """
        pass


    @property
    async def resources(self) -> AsyncGenerator[Resource, None]:
        async for resource in self.create_resource():
            resource: Resource
            yield resource


class CoreResourceManager():

    def __init__(self, configs: Configs):
        self.configs = configs
        self.available_resources: dict[str, Resource] = None
        self.outputs = None

    def request_a_resource_from_the_pool(self) -> Resource: #Empty resource
        """
        Given the files currently in the FilePathQueue, request a resource from the pool
        
        """
        pass

    def receives(self, resource: Resource) -> None:
        """
        Receive a resource and put it in their respective available resource queue.

        Args:

        """
        pass

    def send_a_resource_back_to_the_pool(self) -> Resource:
        """
        """
        pass

    def send_a_path_to_the_file_queue(self) -> Resource:
        """
        """
        pass

    def send_to_the_converter(self) -> Resource:
        """
        """
        pass

    def returns_that_resource(self, resource: Resource) -> None|Resource:
        """
        """
        pass

    def doesnt_need_a_resource_anymore(self) -> bool:
        """
        Given the files currently in the File Queue, tell the Resource Manager if 
            it doesn't need a resource anymore.

        If the 
        
        """
        pass


def instantiate(this_class: type[CustomClass] = None, with_these = None, and_these = None):
    if this_class is None:
        raise ValueError("You must provide a class to instantiate.")
    if with_these is None:
        raise ValueError("You must provide configs for the class to instantiate.")

    if and_these is None:
        the_instantiated_class = this_class(with_these)
    else:
        the_instantiated_class = this_class(with_these, and_these)

    return the_instantiated_class



class FilePathQueue:

    def __init__(self, configs: Configs):
        self.configs = configs
        self.items = []
        self.lock = anyio.Lock()
        self.queue = AnyioQueue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.queue:
            return await self.queue.get()
        raise StopIteration

    async def add_this(self, item) -> None:
        async with self.lock:
            self.items.append(item)

    async def get_this(self) -> Optional[str]:
        async with self.lock:
            if self.items:
                return self.items.pop(0)
            return None

    async def is_empty(self) -> bool:
        async with self.lock:
            return len(self.items) == 0
        
    async def is_not_full(self) -> bool:
        async with self.lock:
            return len(self.items) <= self.configs.max_queue_size
        
    async def has_enough_resources_to_convert_a_file(self) -> bool:
        pass


from typing import Generator



def figure_out_what_resources_we_need_for_this(file):
    pass


import threading

from external_interface.config_parser.config_parser import ConfigParser


async def main():

    logger.info("Begin __main__")

    next_step("Step 1: Load in the configs.")
    if _program_was_started_from_command_line():
        configs = run_with_argparse()
    else:
        parser = ConfigParser()
        configs = parser.load_and_parse_configs_file()

    next_step("Step 2: Create and start the File Paths Manager")
    file_paths_manager = FilePathsManager(configs)

    next_step("Step 3: Create and start the API Manager.")
    llm_api_manager = ApiManager(configs)

    next_step("Step 4: Create and start the System Resources Manager.")
    system_resources_manager = SystemResourcesManager(configs)

    next_step("Step 5: Create and start the External Resource Manager.")
    external_interface_classes = {
        'file_paths_manager': file_paths_manager, 
        'llm_api_manager': llm_api_manager, 
        'system_resources_manager': system_resources_manager
    }

    # NOTE This should run in its own thread.
    the_erm = ExternalResourcesManager(configs, external_interface_classes)

    next_step("Step 6: Create and start the Core Resource Manager.")
    # NOTE This should run in its own thread.
    the_core_manager = CoreResourceManager(configs)

    next_step("Step 7: Create and start the Pool Health Monitor.")
    # NOTE Should be instantiated inside the pools
    pool_health_monitor = PoolHealthMonitor(configs)


    next_step("Step 8: Create and start the Pools.")
    # NOTE This should run in its own thread.
    the_pools = Pools(configs, pool_health_monitor)


    next_step("Step 9: Instantiate a queue of files and fill it up.")
    the_queue = FilePathQueue(configs)


    next_step("Step 10: Start the main loop.")
    while True:

        next_step("Step 11: Generate a resource.")
        async for this_resource in the_erm.resources:

            next_step("Step 11: Check if the pool needs a resource.")
            if the_pools.need_a_resource():
                next_step("Step 12a: Send a resource to the Pools if the Pool need it.")
                the_pools.receive(this_resource)
            else:
                next_step("Step 12b: Return a resource to the ExternalResourcesManager if the Pools don't need it.")
                the_erm.gets_back(this_resource)

            next_step("Step 13: Send a resource to the CoreResourceManager if the CoreResourceManager needs it.")
            if the_core_manager.needs_a_resource():
                the_pools_resource = the_pools.make_a_resource()
                the_core_manager.receives(the_pools_resource)

            next_step("Step 14: Return a resource to the ExternalResourcesManager if the CoreResourceManager doesn't need it.")
            if the_core_manager.doesnt_need_a_resource_anymore():
                that_resource = the_core_manager.returns_that_resource()
                the_erm.gets_back(that_resource)

        # NOTE: We can run sync functions in an async loop, but not vice-versa.
        for file, resources in the_core_manager:

            if await the_queue.is_not_full():
                await the_queue.add_this(file)

            async for file in the_queue:
                next_step("Step 16: Figure out what resources we need, then allocate them.")
                what_we_need = figure_out_what_resources_we_need_for_this(file)
                allocated_resources = the_core_manager.gives_us(what_we_need, from_these=resources)

                next_step("Step 17: Actually convert the file.")
                # NOTE This should run in its own thread.
                this_specific_processor = Processor(file, configs, allocated_resources)
                try:
                    next_step("Step 18: As we run through the conversion steps, give resources back to the Core Resource Manager.")
                    async for this_used_resource in this_specific_processor:
                        the_core_manager.receives(this_used_resource)
                except:
                    ("Step 18b: Return remaining resources to the pool on failure.")
                    # NOTE: We don't care why it failed, we just want to make sure we get our resources back.
                    # It's all about keeping everything going!
                    the_leftover_resources = await this_specific_processor.returns_leftover_resources()
                    the_core_manager.receives(the_leftover_resources)
                finally:
                    next_step("Step 19: Return all the left over resources to the pool.")
                    the_leftover_resources = await this_specific_processor.returns_leftover_resources()
                    the_core_manager.receives(the_leftover_resources)
                    the_queue.removes_this(file)


    # # Load in the config file.
    # configs = Configs()

    # # Get the files/URLs to process and put the paths to them into a duckdb database
    # configs.input_db = duckdb.connect('input.db')
    # configs.output_db = duckdb.connect('output.db')

    # configs.input_db.create_function(
    #     'make_sha256_hash', make_sha256_hash, 'data', return_type=VARCHAR
    # )

    # configs.input_db.execute(
    #     "CREATE TABLE IF NOT EXISTS input (file_path VARCHAR, uuid VARCHAR)"
    # )
    # file_paths = [
    #     str(path) for path in configs.paths.INPUT_DIR.glob("**/*") 
    #     if path.is_file()
    # ]

    # # Split the file_paths into chunks based on the number of workers
    # for file_path in file_paths:
    #     configs.input_db.execute(
    #         "INSERT file_path, uuid INTO input VALUES (?), (make_sha256_hash(?)", [file_path, file_path]
    #     )

    # # Divide the data based on their mime-type

    # Assign the data 


    #mimetypes.guess_type(url)

    #logger.info("Insert program logic here...")
    #logger.info("End __main__")

    sys.exit(0)


if __name__ == "__main__":

    import os
    base_name = os.path.basename(__file__) 
    program_name = os.path.split(os.path.split(__file__)[0])[1] if base_name != "main.py" else os.path.splitext(base_name)[0] 
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        print(f"'{program_name}' program stopped.")
