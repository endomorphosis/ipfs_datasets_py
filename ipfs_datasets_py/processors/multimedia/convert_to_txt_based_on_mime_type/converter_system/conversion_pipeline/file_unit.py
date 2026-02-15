"""


"""
from __future__ import annotations


from functools import partial
from pathlib import Path
from typing import Any, Callable, Coroutine, Generator, TypeVar, Type


T = TypeVar("T")
NestedDict = TypeVar("NestedDict", dict[str, Any], dict[str,dict[str, Any]])


from pydantic import BaseModel, Field 


import logging
logger = logging.getLogger(__name__)


class AllocatedSystemResources(BaseModel):
    ram: int
    cpu: int
    vram: int
    api_uses: int
    cid: str = None # Only used as an ID

def get_total_resources_assigned_to_file(data: NestedDict) -> AllocatedSystemResources:
    for func in data.items():
        output_dict = {
            type: value for type, value in func['allocated_system_resources'].items()
        }
    return AllocatedSystemResources(**output_dict)

class FunctionArgsKwargs(BaseModel):
    name: str
    func: Callable | Coroutine
    args: tuple = None
    kwargs: dict = None
    allocated_system_resources: AllocatedSystemResources

class FunctionDict(BaseModel):
    load: FunctionArgsKwargs = Field(..., alias="load")
    convert: FunctionArgsKwargs = Field(..., alias="convert")
    write: FunctionArgsKwargs = Field(..., alias="write")

class FileUnit(BaseModel):
    cid: str
    mime_type: str
    file_path: Path
    function_dict: FunctionDict
    data: str | bytes = None
    total_resources: AllocatedSystemResources = None
    error_data: dict = None

    def __init__(self, **data):
        self.function_dict = FunctionDict(**data.pop('function_dict'))
        self.total_resources = get_total_resources_assigned_to_file(self.function_dict)
        super().__init__(**data)


