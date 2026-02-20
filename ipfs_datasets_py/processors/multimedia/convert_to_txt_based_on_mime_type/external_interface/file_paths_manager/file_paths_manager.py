from abc import ABC, abstractmethod
import anyio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime
from enum import Enum
from functools import cached_property
import hashlib
import logging
import os
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, Callable, ClassVar, Generator, Iterator, Optional, Self


from pydantic import AfterValidator, BaseModel, computed_field, Field, field_validator, ValidationError


from external_interface.file_paths_manager.supported_mime_types import (
    SupportedMimeTypes,
    SupportedApplicationTypes,
    SupportedAudioTypes,
    SupportedImageTypes,
    SupportedTextTypes,
    SupportedVideoTypes
)

from pydantic_models.configs import Configs
from pydantic_models.default_paths import DefaultPaths
from pydantic_models.file_paths_manager.file_path import FilePath
from pydantic_models.file_paths_manager.file_path_and_metadata import FilePathAndMetadata
from pydantic_models.types.valid_path import ValidPath

from utils.common.get_cid import get_cid
from utils.common.anyio_queues import AnyioQueue

class FilePathsManager:
    """Manages file paths and their metadata for batch processing operations.

    Purpose:
        Handles discovery, validation, and metadata extraction for files in a given
        input directory, comparing them against an output directory and providing
        filtered results based on configurable comparison rules.

    Implementation Strategy:
        - Uses a pipeline of comparison functions for flexible filtering
        - Implements RAII pattern for resource management
        - Provides cross-platform path handling via pathlib
        - Supports concurrent processing with proper resource cleanup
        - Uses context manager protocol for safe resource handling

    Inputs:
        - Input directory path
        - Output directory path
        - List of comparison functions
        - Configuration options for filtering and logging

    Outputs:
        - Iterator of FileAndMetadata objects
        - Logging of invalid/inaccessible paths

    Attributes:
        input_dir (Path): Root directory for input files
        output_dir (Path): Directory containing processed files
        comparison_pipeline (List[ComparisonFunction]): Ordered list of comparison functions
        logger (logging.Logger): Logger instance
        _executor (ThreadPoolExecutor): Thread pool for concurrent operations
    
    Methods:
        __init__: Initialize the manager with paths and configuration
        __aenter__: Async Context manager entry
        __aexit__: Async Context manager exit and cleanup
        get_inputs: Main method to traverse and process files
        extract_metadata: Extract metadata for a given file
        requires_processing: Check if a file needs processing
        cleanup: Perform resource cleanup


    Example:
        >>> async with FilePathsManager(configs) as fpm:
        ...     async for file in fpm.get_inputs():
        ...         needs_processing = fpm.requires_processing(file)
        ...         if needs_processing:
        ...             fpm.extract_metadata_queue.put(file)
        ... 
        ...      async for file_path_and_metadata in extract_metadata():
        ...         fpm.output_queue.put(file_path_and_metadata)
        ... 
        ...      async for batch in fpm.output_queue:
                    fpm.send_to_external_file_manager(batch)
    """

    def __init__(self, configs: Configs) -> None:
        """Initialize the FilePathsManager.
        
        Args:
            configs: A configuration object
            input_dir: Root directory to search for files
            output_dir: Directory containing processed files
            comparison_functions: List of functions for file comparison pipeline
            log_level: Logging level for operations
            max_workers: Maximum number of concurrent workers

        Example:
            >>> fpm = FilePathsManager(configs)
        """
        self.configs = configs

        self._input_folder: Path = Path(configs.input_folder) or DefaultPaths.INPUT_DIR
        self._output_folder: Path = Path(configs.output_folder) or DefaultPaths.OUTPUT_DIR
        self._max_queue_size = configs.max_queue_size or 1024
        self._max_program_memory = configs.max_program_memory
        self._batch_size = configs.batch_size or 1024
        self.get_inputs_queue: AnyioQueue = AnyioQueue(maxsize=self._max_queue_size)
        self.extract_metadata_queue: AnyioQueue = AnyioQueue(maxsize=self._max_queue_size)
        self.processing_queue: AnyioQueue = AnyioQueue(maxsize=self._max_queue_size)
        self.output_queue: AnyioQueue = AnyioQueue(maxsize=self._batch_size)
        self._duck_db = None

        self._duck_db_path = DefaultPaths.FILE_PATH_MANAGER_DUCK_DB_PATH

        self._logger = configs.make_logger(self.__class__.__name__)
        # self._duck_db = configs.make_duck_db(self._duck_db_path)

        # saved_input_paths = self._duck_db.execute(
        #     "SELECT input_path FROM file_paths"
        # ).fetchall()
        # if not saved_input_paths:
        #     pass
        print("FilePathsManager initialized")


    async def __aenter__(self) -> 'FilePathsManager':
        """Enter context manager, initializing resources.

        Returns:
            Self for context manager protocol

        Example:
            >>> async with FilePathsManager(configs) as fpm:
            ...     for file in fpm.get_inputs():
            ...         process_file(file)
        """
        return await self


    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager, ensuring cleanup.

        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception value if an error occurred
            exc_tb: Exception traceback if an error occurred

        Example:
            >>> # Resources automatically cleaned up after context exit
            >>> async with FilePathsManager(configs) as fpm:
            ...     fpm.get_inputs()
        """
        return await self.cleanup()


    def scan_for_files(self) -> Generator[Path, None, None]:
        """
        Scan the input directory for files.
        This includes sub-directories and hidden files, but not objects like symlinks and shortcuts.

        Yields:
            Path: A Path object for a file in the input directory.
        """
        for path in self._input_folder.rglob('*'):
            try:
                # Only yield files, not directories or symlinks
                if path.is_file() and not path.is_symlink():
                    yield path
            except Exception as e:
                self._logger.error(f"Error scanning input directory: {e}")
                raise e


    async def get_inputs(self) -> None:
        """Validate paths coming in from the input directory
            by encasing them in the Pydantic class 'FilePath'
                If they're valid, put them in the get_inputs_queue.
                If they're not log it and skip them.

        Returns:
            None: The result is that the file_path is put in the extract_metadata_queue

        Example:
            >>> async with FilePathsManager(configs) as fpm:
            ...     await fpm.get_inputs()
            ...     while not fpm.extract_metadata_queue.empty():
            ...         file_path = await fpm.extract_metadata_queue.get()
            ...         print(f"Valid file path: {file_path}")
            ...         fpm.extract_metadata_queue.task_done()
        """
        for file_path in self.scan_for_files():
            try: 
                validated_path = FilePath(file_path=file_path)
                await self.extract_metadata_queue.put(validated_path)
                print(f"Valid file path: {validated_path}")
            except ValidationError as e:
                self._logger.error(f"Invalid file path: {e}")


    async def extract_metadata(self) -> None:
        """Extract both basic and content-based metadata from a file.
        
        Returns:
            None: The result is that the file_path is put in the processing_queue.
        
        Example Output:
            >>> async with FilePathsManager(configs) as fpm:
            ...     async for path in fpm.get_inputs():
            ...         fpm.metadata_generation_queue.put(path)
            ...         async for path_with_metadata in fpm.extract_metadata():
            ...             fpm.output_queue.add(path_with_metadata)
        """
        await self.get_inputs()
        while not self.extract_metadata_queue.empty():
            file_path: FilePath = await self.extract_metadata_queue.get()
            try:
                file_path_and_metadata = FilePathAndMetadata(
                    max_program_memory=self._max_program_memory,
                    file_path=file_path
                )
                await self.processing_queue.put(file_path_and_metadata)
                self.extract_metadata_queue.task_done()
            except ValidationError as e:
                self._logger.error(f"Could not create FilePathAndMetadata object for '{file_path.file_path}': {e}")


    def requires_processing(self, input_path: FilePathAndMetadata) -> bool:
        """Determine if a file requires processing based on whether
            or not its already in the output folder.

        Args:
            input_path: FilePathAndMetadata object containing the input file path and metadata

        Returns:
            True if file needs processing, False otherwise.

        Example:
            >>> async with FilePathsManager(configs) as fpm:
            ...     async for file_path_and_metadata in fpm.extract_metadata():
            ...         needs_processing = await fpm.requires_processing(file_path_and_metadata)
            ...         if needs_processing:
            ...             await fpm.processing_queue.put(file_path_and_metadata)
        """
        # Ignore invalid inputs. NO BREAKS.
        if not isinstance(input_path, FilePathAndMetadata):
            self._logger.error(f"Invalid input_path: {input_path}. Ignoring...")
            return False

        # Construct the expected output path based on the filename
        # NOTE This assumes the output folder has no subdirectories.
        expected_output_path = self._output_folder / f"{input_path.file_name}.txt"
        self._logger.debug(f"expected_output_path: {expected_output_path}")

        # Check if the file exists in the output folder
        if expected_output_path.exists():
            # If it exists, compare timestamps
            input_timestamp = input_path.modified_timestamp
            output_timestamp = datetime.fromtimestamp(expected_output_path.stat().st_mtime)

            # If input file is newer, it needs processing
            if input_timestamp > output_timestamp:
                self._logger.debug(f"input_timestamp is newer than the output_timestamp, file needs processing")
                return True
            else:
                self._logger.debug(f"input_timestamp is older than the output timestamp, file does not need processing")
                return False
        else:
            self._logger.debug(f"Output file does not exist, file needs processing")
            # If the file doesn't exist in the output folder, it needs processing
            return True


    async def make_batch(self) -> None:
        """
        Package the file paths currently in the processing_queue into batches, 
            and then put them into the output_queue.

        Example:
            >>> async with FilePathsManager(configs) as fpm:
            ...     needs_processing = fpm.requires_processing(
            ...         input_path,
            ...         output_path
            ...     )
            ...    
        """
        # TODO Might have to move these back inside the loop.
        # We *want* this to loop endlessly, we just need to make sure that we don't 
        await self.get_inputs()
        await self.extract_metadata()

        batch = []
        while not self.processing_queue.empty():

            input_path = await self.processing_queue.get()

            if self.requires_processing(input_path):
                batch.append(input_path)

            if len(batch) >= self._batch_size:
                await self.output_queue.put(batch)
                batch = []

        if batch:
            await self.output_queue.put(batch)


    def __aiter__(self) -> 'FilePathsManager':
        return self


    async def __anext__(self) -> list[FilePathAndMetadata]:
        """
        Iterate over the batches of file paths in the get_outputs queue.
        """
        while not self.output_queue.empty():
            return await self.output_queue.get()
        else:
            raise StopAsyncIteration


    async def cleanup(self) -> None:
        """Clean up resources, ensuring proper release of system resources.

        This should:
            Save everything in the processing_queue to the duckdb database.
            Close the connection to the duckdb database.

        Example:
            >>> fpm = FilePathsManager(input_dir, output_dir, comparators)
            >>> try:
            ...     fpm.get_inputs()
            ... finally:
            ...     fpm.cleanup()
        """
        if self._duck_db:
            for input_path in self.processing_queue:
                self._duck_db.execute("INSERT INTO file_paths (input_path) VALUES (?)", (input_path,))
                self._duck_db.close()
