
from functools import partial
from typing import Callable


from .file_unit import FileUnit


def get_args_kwargs_and_func(file_unit: FileUnit, func_name: str):
    """
    Extracts function arguments, keyword arguments, and the function 
    itself from a FileUnit object.

    Args:
        file_unit: The FileUnit object containing the function dictionary and data.
        func_name: The name of the function to retrieve from the FileUnit's function dictionary.

    Returns:
        args: The positional arguments for the function, with file_unit.data as the first argument\n
        kwargs: The keyword arguments for the function\n
        func: The function object itself

    """
    assert hasattr(file_unit.function_dict, func_name), f"Function {func_name} not found in function_dict"
    for attr in ['args', 'kwargs', 'func']:
        if not hasattr(getattr(file_unit.function_dict, func_name), attr):
            raise AttributeError(f"Function {func_name} has no {attr}")

    args = tuple([file_unit.data] + list(getattr(file_unit.function_dict, func_name).args))
    kwargs = getattr(file_unit.function_dict, func_name).kwargs
    func = getattr(file_unit.function_dict, func_name).func
    return args, kwargs, func

def define_function(file_unit: FileUnit, func_name: str) -> Callable:
    """
    Define a partial function with specified arguments for conversion pipeline.

    This function retrieves args, kwargs, and the actual function based on the file_unit
    and function name, then returns a partially applied function ready to be executed.

    Args:
        file_unit (FileUnit): The file unit containing metadata and content for conversion
        func_name (str): Name of the function to be defined in the conversion pipeline

    Returns:
        Callable: A partially applied function with bound arguments ready to be called
    """
    args, kwargs, func = get_args_kwargs_and_func(file_unit, func_name)
    return partial(func, *args, **kwargs)

