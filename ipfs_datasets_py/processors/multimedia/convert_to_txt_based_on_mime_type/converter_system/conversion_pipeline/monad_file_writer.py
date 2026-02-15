

from pathlib import Path
from functools import partial
import logging
import json
from typing import Any


import yaml

from utils.converter_system.monads.helper_functions import start, stop
from .file_unit import FileUnit
from utils.converter_system.monads.error import ErrorMonad
from utils.common.logger import get_logger

logger = get_logger(__name__)

def _json(file_path: str | Path, content: Any, encoding: str = 'utf-8'):
    with open(file_path, 'w',encoding=encoding) as file:
        json.dump(content, file)

def _txt(file_path: str | Path, content: str, encoding: str = 'utf-8'):
    with open(file_path, 'w', encoding=encoding) as file:
        file.write(content)

def _yaml(file_path: str | Path, content: Any, encoding: str = 'utf-8'):
    with open(file_path, 'w', encoding=encoding) as file:
        yaml.dump(content, file)

def _print(msg):
    print(msg)
    return lambda x: x

def _txt_to_sql_db():
    """
    Save a text file to a SQL database
    """
    pass


from .file_unit import FileUnit

from define_function import define_function



def check_if_errored(x, success_msg=None, failure_msg=None):
    if not x.errored:
        _log_success(success_msg)
    else:
        _log_error(failure_msg)
    return x

def _log_error(msg):
    logger.error(msg)

def _log_success(msg):
    logger.info(msg)


def file_writer(file_unit: FileUnit):
    """
    Write content to a file using the appropriate function based on the file extension.

    Args:
        file_path (str | Path): The path to the file to be written.
        content (Any): The content to be written to the file.
        encoding (str): The encoding to use when writing the file. Defaults to 'utf-8'.
        ignore_errors (bool): If True, errors during file writing will be printed but not raised. Defaults to False.

    Raises:
        Exception: If an error occurs during file writing and ignore_errors is False.
    """
    file_name = file_unit.file_path.stem
    error_msg = f"Error saving {file_name}: {saving.value}"
    success_msg = f"{file_name} saved successfully."

    # Get the partial function for the given file type
    _save = define_function(file_unit, 'save')

    # Use the monadic pipeline to save the content.
    saving = start(file_unit, ErrorMonad
        ) >> _print(f"Saving {file_name}..."
        ) >> _save >> check_if_errored(success_msg, error_msg
        ) >> stop

    if saving.errored:
        pass
    else:
        print("Save successful.")
    file_unit.data = saving.value
    return file_unit


