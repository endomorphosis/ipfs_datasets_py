

from utils.common.anyio_queues import AnyioPriorityQueue
import logging

import duckdb

from pydantic_models.configs import Configs
from pydantic_models.resource.resource import Resource

class FilePathPool():
    """
    A manager for file paths that tracks the current files in the Pool.


    """
    def __init__(self, configs: Configs):
        self.file_path_queue = AnyioPriorityQueue(maxsize=configs.BATCH_SIZE)
        self.logger = configs.make_logger(__name__)

    def receive(self, resource: Resource) -> Resource:
        pass

    def acquire(self):
        pass

    def load_current_file_pool_from_disk():
        pass

    def save_current_file_pool_to_disk():
        pass
