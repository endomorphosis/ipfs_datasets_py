
from enum import Enum
from pathlib import Path
from typing import Callable, Coroutine, Optional



from pydantic import BaseModel, Field, PrivateAttr


from pydantic_models.resource.api_connection import ApiConnection
from converter_system.core.pipeline import Pipeline


class FunctionType(Enum):
    """Enum for function types"""
    SAVE = "save"
    LOAD = "load"
    CONVERT = "convert"


class FunctionDictionary(BaseModel):
    """
    A container for a function and resources allocated to it.
    The function can be a callable or a coroutine. The resources are allocated based on the function type.
    
    Example:
        func_dict = FunctionDictionary(**data)
        func_dict.model_dump()
        {
            "func": json.dumps,
            "kwargs": {"indent": 4},
            "worker": 1,
            "gpu_mem": 0,
            "sys_mem": 1024,
            "api_connection": 0
        }
    """
    func: Callable
    kwargs: Optional[dict] = None
    worker: Optional[int] = None
    gpu_mem: Optional[int] = None
    sys_mem: Optional[int] = None
    api_connection: Optional[int] = None



from functools import partial

class Resource(BaseModel):
    """
    A container for a file path, a series of functions and the resources needed to run them

    Attributes:
        file_path: A path to a file that needs to be converted into plaintext.
        func_dict: A dictionary of functions and their allocated resources.
        api_connection: List of API connections allocated to this resource.
        total_gpu_mem: Total amount of GPU memory allocated to this resource.
        total_workers: Total number of workers allocated to this resource.
        total_sys_mem: Total amount of system memory allocated to this resource.
        total_api_uses: Total number of API calls allocated to this resource.
    
    Properties
        data: The data from the file path.
        converted_data: The data from the file path converted into plaintext, but not yet saved to a file.
    """
    file_path: Optional[Path] = None
    func_dict: Optional[dict[FunctionType, FunctionDictionary]] = Field(default=None, description="A dictionary of functions and their associated resources.")
    api_connection: Optional[list[ApiConnection]] = Field(default=None, description="List of API connections allocated to this resource.")
    total_gpu_mem: Optional[int] = Field(default=None, description="Total amount of GPU memory allocated to this resource.")
    total_workers: Optional[int] = Field(default=None, description="Total number of workers allocated to this resource.")
    total_sys_mem: Optional[int] = Field(default=None, description="Total amount of system memory allocated to this resource.")
    total_api_uses: Optional[int] = Field(default=None, description="Total number of API calls allocated to this resource.")

    data: Optional[bytes] = None
    converted_data: Optional[bytes] = None
    _pipeline: Pipeline = None

    _file_path: Optional[Path] = None

    def __init__(self, **data):
        super().__init__(**data)

    @property
    def pipeline(self) -> Pipeline:
        if not self._pipeline:
            self.make_pipeline()
        return self._pipeline

    async def make_pipeline(self):
        """
        Make a data conversion pipeline for this resource.
            Instead of using the resource itself, we use a copy of the resource.
            This way, we can run it in a separate thread/process and not interfere with the original resource.
        """
        self._pipeline = Pipeline(self.model_copy(deep=True))


    async def pipeline_func(self, resource: 'Resource', func_dict_key: str):
            kwargs = self.func_dict[FunctionType.SAVE].kwargs
            func = partial(self.func_dict[FunctionType.SAVE].func, **kwargs)
            try:
                return await func(resource) if resource is not None else None
            except Exception as e:
                return e
            finally:
                self.total_api_uses -= self.func_dict[FunctionType.SAVE].api_connection or 0
                self.total_gpu_mem -= self.func_dict[FunctionType.SAVE].gpu_mem or 0
                self.total_sys_mem -= self.func_dict[FunctionType.SAVE].sys_mem or 0
                self.total_workers -= self.func_dict[FunctionType.LOAD].worker or 0


    # NOTE These functions are meant to be passed in a pipeline
    async def load(self, resource: 'Resource') -> Optional[bytes]:
        kwargs = self.func_dict[FunctionType.LOAD].kwargs
        func = partial(self.func_dict[FunctionType.LOAD].func, **kwargs)
        try:
            return await func(resource) if resource is not None else None
        except Exception as e:
            return e
        finally:
            self.total_api_uses -= self.func_dict[FunctionType.LOAD].api_connection or 0
            self.total_gpu_mem -= self.func_dict[FunctionType.LOAD].gpu_mem or 0
            self.total_sys_mem -= self.func_dict[FunctionType.LOAD].sys_mem or 0


    async def convert(self, resource) -> Optional[bytes]:
        kwargs = self.func_dict[FunctionType.CONVERT].kwargs
        func = partial(self.func_dict[FunctionType.CONVERT].func, **kwargs)
        try:
            return await func(resource) if resource is not None else None
        except Exception as e:
            return e
        finally:
            self.total_api_uses -= self.func_dict[FunctionType.CONVERT].api_connection or 0
            self.total_gpu_mem -= self.func_dict[FunctionType.CONVERT].gpu_mem or 0
            self.total_sys_mem -= self.func_dict[FunctionType.CONVERT].sys_mem or 0


    async def save(self, resource: 'Resource') -> Optional[bytes]:
        kwargs = self.func_dict[FunctionType.SAVE].kwargs
        func = partial(self.func_dict[FunctionType.SAVE].func, **kwargs)
        try:
            return await func(resource) if resource is not None else None
        except Exception as e:
            return e
        finally:
            self.total_api_uses -= self.func_dict[FunctionType.SAVE].api_connection or 0
            self.total_gpu_mem -= self.func_dict[FunctionType.SAVE].gpu_mem or 0
            self.total_sys_mem -= self.func_dict[FunctionType.SAVE].sys_mem or 0
            self.total_workers -= self.func_dict[FunctionType.LOAD].worker or 0


