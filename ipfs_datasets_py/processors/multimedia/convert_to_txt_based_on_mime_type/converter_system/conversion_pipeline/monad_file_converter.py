#!/usr/bin/venv python

from functools import partial
import json
from pathlib import Path
import puremagic
from typing import Any, Callable, Coroutine

import markitdown
from markitdown import MarkItDown, UnsupportedFormatException, FileConversionException
from pydantic import BaseModel, Field

from utils.converter_system.monads.helper_functions import start, stop
from utils.converter_system.monads.error import ErrorMonad
from utils.converter_system.monads.async_ import Async


from .file_unit import FileUnit


def _txt_converter(content: bytes | str):
    # Essentially a pass through function
    return content.decode('utf-8')

def _json_converter(content: bytes | str):
    return content.decode('utf-8')


_FUNCTION_DICT = {
    '.txt': MarkItDown.convert,
    '.json': MarkItDown,
    '.jsonl': MarkItDown,
    '.csv': MarkItDown,
    '.xml': MarkItDown,
    '.yaml': MarkItDown,
    '.ini': MarkItDown,
    '.log': MarkItDown,
    '.md': MarkItDown,
    '.py': MarkItDown,
    '.html': MarkItDown,
    '.css': MarkItDown,
    '.js': MarkItDown,
    '.sql': MarkItDown,
    '.tsv': MarkItDown,
    '.toml': MarkItDown,
    '.yml': MarkItDown,
    '.rst': MarkItDown,
    '.xml': MarkItDown,
    '.svg': MarkItDown,
    '.tex': MarkItDown,
}


def _print(msg):
    print(msg)
    return lambda x: x


from .define_function import define_function


def file_converter(file: FileUnit):

    file_name = file.file_path.name

    # Get the partial function for the given file type
    _converter = define_function(file, 'convert')
    del file.data # Remove the unconverted data from the file unit to save on RAM

    # Use the pipeline to convert the content.
    conversion = start(file, Async) >> _print(f"Converting {file_name}...") >> _converter

    if conversion.errored:
        logger.error(f"Error converting {file_name}: {conversion.value}")
        return ErrorMonad(conversion.value)
    else:
        logger.debug(f"Conversion successful for {file_name}.")
        file.data = conversion.value
        return Async(file)
