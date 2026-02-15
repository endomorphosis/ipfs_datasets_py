


from pathlib import Path
from functools import partial
import json
from typing import Any


import yaml


from experiments.fun_with_monads.error import ErrorMonad, start, stop
from experiments.fun_with_monads.monad import Monad
from experiments.fun_with_monads.async_ import Async
from .file_unit import FileUnit
from utils.common.logger import get_logger

logger = get_logger(__name__)

def _json_load(file_path: str | Path, content: Any, encoding: str = 'utf-8'):
    with open(file_path, 'r',encoding=encoding) as file:
        json.load(content, file)

def _json_str_load(file_path: str | Path, content: Any, encoding: str = 'utf-8'):
    with open(file_path, 'r',encoding=encoding) as file:
        json.loads(content, file)

def _txt_load(file_path: str | Path, content: str, encoding: str = 'utf-8'):
    with open(file_path, 'r', encoding=encoding) as file:
        file.read(content)

def _yaml_load(file_path: str | Path, content: Any, encoding: str = 'utf-8'):
    with open(file_path, 'r', encoding=encoding) as file:
        yaml.load(content, file)

def _print(msg):
    print(msg)
    return lambda x: x

_FUNCTION_DICT = {
    '.txt': _txt_load,
    '.json': _json_load,
    '.jsonl': _json_str_load,
    '.csv': _txt_load,
    '.xml': _txt_load,
    '.yaml': _yaml_load,
    '.ini': _txt_load,
    '.log': _txt_load,
    '.md': _txt_load,
    '.py': _txt_load,
    '.html': _txt_load,
    '.css': _txt_load,
    '.js': _txt_load,
    '.sql': _txt_load,
    '.tsv': _txt_load,
    '.toml': _txt_load,
    '.yml': _yaml_load,
    '.rst': _txt_load,
    '.xml': _txt_load,
    '.svg': _txt_load,
    '.tex': _txt_load,

}



# def file_converter(file: FileUnit):

#     # Get the partial function for the given file type
#     #  _converter = partial(file.func_dict.convert, *args, **kwargs)
#     args = tuple([file.content] + list(file.function_dict.convert.args))
#     kwargs = file.function_dict.convert.kwargs
#     _converter = partial(_FUNCTION_DICT[file.mime_type], *args, **kwargs)
#     del file.content # Remove the unconverted data from the file unit

#     # Use the monadic pipeline to load the content.
#     pipeline = start(file, Async) >> _print(f"Converting {file.file_path}...") >> _converter

#     if pipeline.errored:
#         logger.error(f"Error converting {file.file_path}: {pipeline.value}")
#         return ErrorMonad(pipeline.value)
#     else:
#         print("Conversion successful.")
#         return file

from .define_function import define_function

def file_loader(file_unit: FileUnit):
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
    file_name = file_unit.file_path.name

    # Get the partial function for the given file type
    _load = define_function(file_unit, 'load')
    
    # Use the monadic pipeline to load the content.
    loading = start(file_unit, Async) >> _print(f"Loading {file_name}...") >> _load

    if loading.errored:
        logger.error(f"Error saving {file_name}: {loading.value}")
        return ErrorMonad(loading.value)
    else:
        file_unit.data = loading.value
        print("Loading successful.")
        return Async(file_unit) # Return the File object as an Async monad


