#!/usr/bin/venv python
from functools import partial
import json
from pathlib import Path
from typing import Any, Callable, Coroutine, Generator, TypeVar, Type


T = TypeVar("T")
NestedDict = TypeVar("NestedDict", dict[str, Any], dict[str,dict[str, Any]])


from pydantic import BaseModel, Field
from puremagic import PureMagicWithConfidence, PureError

from utils.converter_system.monads.helper_functions import start, stop
from utils.converter_system.monads.error import ErrorMonad, start, stop
from utils.converter_system.monads.monad import Monad
from utils.converter_system.monads.async_ import Async

from .file_unit import FileUnit
from .monad_file_loader import file_loader
from .monad_file_converter import file_converter
from .monad_file_writer import file_writer
from utils.run_in_process_pool import run_in_process_pool, run_pipeline_in_process_pool

import logging
logger = logging.getLogger(__name__)







# define a semaphore with thread-safe counter
from multiprocessing import Semaphore, Value
class SafeSemaphore:

    # constructor
    def __init__(self, value=1):
        # initialize semaphore with given value
        self._semaphore = Semaphore(value)
        self._counter = Value('i', value)
    
    # acquire the semaphore
    def acquire(self, block=True, timeout=None):
        result = self._semaphore.acquire(block, timeout)
        if result:
            with self._counter.get_lock():
                self._counter.value -= 1
        return result
    
    # release the semaphore
    def release(self):
        with self._counter.get_lock():
            self._counter.value += 1
        self._semaphore.release()
    
    # get current semaphore value
    def value(self):
        with self._counter.get_lock():
            return self._counter.value
            
    # context manager support
    def __enter__(self):
        self.acquire()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

def sync(semaphore):
    with semaphore:
        return lambda x: x


##############################







#################################


def _print(msg):
    print(msg)
    return lambda x: x

def apply(func: Callable) -> FileUnit:
    return lambda x: func(x)

def emit(msg1: str, msg2: str, type: T, emit_func1: Callable, emit_func2: Callable):
    return lambda x: emit_func1(msg1) if isinstance(x, type) else emit_func2(msg2)

def log(on_success: str = "Success", on_failure: str = "Error"):
    return lambda x: log_success(x, on_success) if not isinstance(x, Exception) else log_failure(x, on_failure)


def log_success(x, msg: str):
    logger.info(msg)
    return x

def log_failure(x, msg: str):
    logger.error(msg)
    return x



FatalError = TypeVar("FatalError", 
                     PureError, ValueError,
                     TypeError, KeyError,
                    )


#################################

class Autopsy(ErrorMonad[T]):

    def __init__(self, work: Any) -> None:
        self._work = work
        self._chained = None

    @staticmethod
    def unit(value):
        return Autopsy(value)

    def bind(self, next_work: Any) -> 'Autopsy':
        if isinstance(next_work, Exception):
            return self.left(next_work) # Propagate errors

        self._chained = next_work
        return self

    def __repr__(self) -> str:
        return f"Autopsy({self._work})"

    @property
    def value(self):
        return self._work

    @property
    def errored(self):
        return isinstance(self._work, Exception)


def find_error(file_unit: FileUnit, monad: Monad) -> Monad:
    return monad(file_unit)

import statistics as stats

def create_statistics(errors: list[Exception]) -> dict[str, int]:

    # Group errors by type
    error_types = {}
    for error in errors:
        error_type = type(error).__name__
        if error_type not in error_types:
            error_types[error_type] = []
        error_types[error_type].append(error)
    
    # Generate statistics
    statistics = {}
    for error_type, type_errors in error_types.items():
        statistics[error_type] = {
            'count': len(type_errors),
            'percentage': (len(type_errors) / len(errors)) * 100 if errors else 0
        }
    
    # Overall statistics
    statistics['total'] = len(errors)
    statistics['unique_types'] = len(error_types)
    statistics['total_average'] = stats.mean([len(type_errors) for type_errors in error_types.values()]) if error_types else 0
    statistics['count_fatal_errors'] = len([error for error in errors if isinstance(error, FatalError)])


def what_type_of(error: Exception):
    """Determine the type of error that occurred."""
    return lambda x: x.update(which=type(error))

def where(error: Exception):
    """Determine in what file the error occurred."""
    where = error.__traceback__.tb_frame.f_code.co_filename
    return lambda x: x.update(where=where)

def when(error: Exception):
    """Determine when the error occurred."""
    return lambda x: x.update(when=error.__traceback__.tb_lineno)

def what(error: Exception):
    """Determine what the error was."""
    return lambda x: x.update(what=error.args[0])

def why(error: Exception):
    """Determine why the error occurred."""
    return lambda x: x.update(why=error.__cause__)

def determine_if_fatal(error: Exception):
    """Determine if the error is something that can be recovered from."""
    return lambda x: x.update(fatal=isinstance(error, FatalError))

def end(x):
    return x

from queue import Queue
from datetime import datetime


def error_pipeline(file_unit: FileUnit) -> dict[str, Any]:
    """
    Setup a pipeline to unpack error data within the file unit.
    """
    error = file_unit.error_data
    pipeline = start({'file_unit': file_unit,}, ErrorMonad
    ) >> what(error
    ) >> what_type_of(error
    ) >> where(error
    ) >> why(error
    ) >> determine_if_fatal(error
    ) >> end
    return pipeline()


def document_errors(errored_units: list[FileUnit]) -> Generator:
    """
    Create a dictionary of error statistics.

    Args:
        errors (list[Exception]): A list of exceptions.

    Returns:
        dict[str, int]: A dictionary where the keys are the exception types and the values are the counts.
    """
    # Create pipeline functions for each file unit
    results_dicts = list(map(error_pipeline, errored_units))

    # Create statistics from the results
    statistics = create_statistics([dict['file_unit'].error_data for dict in results_dicts])

    # Save statistics to a file
    with open(f'error_statistics_{datetime.now()}.json', 'w') as f:
        json.dump(statistics, f, indent=4)

    for dict_ in results_dicts:
        if not dict_['fatal']:
            yield dict_['file_unit']
        





def monad_file_conversion_pipeline(
        file_batch: list[FileUnit], 
        configs: dict[str, Any] | BaseModel, 
        ) -> Generator:
    """
    Write data to a file using the appropriate function based on the file extension.

    Args:
        file_path (str | Path): The path to the file to be written.
        data (Any): The data to be written to the file.
        encoding (str): The encoding to use when writing the file. Defaults to 'utf-8'.
        ignore_errors (bool): If True, errors during file writing will be printed but not raised. Defaults to False.

    Raises:
        Exception: If an error occurs during file writing and ignore_errors is False.
    """

    def conversion_pipeline(file_unit: FileUnit) -> Callable:
        """
        Setup a pipeline to load, convert, and write the data.
        """
        this_file = file_unit.file_path.stem

        return start(file_unit, Async
        ) >> _print(
            f"Begin processing of {this_file}"
        ) >> file_loader >> _print(
            f"Begin conversion of {this_file}"
        ) >> file_converter >> _print(
            f"Begin writing {this_file} to disk."
        ) >> file_writer

    pipeline_batch = [(conversion_pipeline, file,) for file in file_batch]

    # Run the pipeline in a process pool
    for input, output in run_pipeline_in_process_pool(pipeline_batch, max_workers=configs.max_workers):
        if isinstance(output, Exception):
            log_failure(output, f"Error with {input.file_path.name}: ")
        else:
            log_success(f"Step {input.file_path.stem} successful:")
        yield input, output

if __name__ == '__main__':
    # Define the file paths and configurations
    file_paths = [
        'path/to/file1.txt',
        'path/to/file2.json',
        'path/to/file3.csv',
    ]
    configs = {
        'max_workers': 4,
    }

    def send_to_error_analyzer():
        pass

    # Create a list of FileUnit objects
    file_units = [FileUnit(file_path) for file_path in file_paths]

    # Run the pipeline
    for result in monad_file_conversion_pipeline(file_units, configs):
        if isinstance(result, Exception):
            send_to_error_analyzer(result)
        else:
            print(f"File processed successfully: {result.file_path}")