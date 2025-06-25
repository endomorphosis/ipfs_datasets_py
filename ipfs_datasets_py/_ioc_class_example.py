"""
This is an example of an Inversion of Control (IOC) class in Python.


"""
from dataclasses import dataclass
from typing import Any, Callable, AbstractSet
from types import ModuleType


from ._dependencies import dependencies

# configs.py
@dataclass
class Configs:
    name: str = "default_name"

# some_module.py
def some_function(x: int, array_func: Callable) -> Any:
    """
    This is an example function that is meant to be used as a resource in the IOC class.

    The file it is in should not import:
    - Any local modules.
    - Any third-party modules (e.g. requests, numpy, etc.).
    - Any global variables (e.g. loggers, configs, etc.).

    It should only be able to access these as arguments passed to the function.

    The function should:
    - Strive to be as pure as possible: Identical inputs should yield identical outputs, no side effects.
    - Be short, simple and straightforward.
    - Well-documented, with type hints and docstrings.

    The function should not:
    - Validate its inputs.
    - Handle exceptions.
    - Directly access external resources (e.g. files, databases, etc.) unless it is explicitly supposed to do so.


    If a function must access external resources, they must be passed in as arguments.
    """
    counter = 0
    for idx in range(5):
        counter += x ** 2
        print(f"Example function iteration {idx + 1}: counter")
    result = array_func([counter])
    return result


# ioc_class_example.py
class IocClassExample:
    """
    Example class to demonstrate the structure of an IOC class.
    This class is a toy example for educational/template purpose only.

    In this way, all callables are tightly couple to the class,
    but the class itself is not tightly couple to the callables.
    """

    def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
        self.resources = resources
        self.configs = configs

        # Set configs
        # NOTE: Must fail-fast with an AttributeError if configs is None or attribute isn't present.
        # NOTE: The config object must be a dataclass, pydantic model, or similar container.
        # It is specifically NOT a dictionary, tuple, or other built-in type.
        self.name = self.configs.name

        # Set resources
        # NOTE: Must fail-fast with a KeyError if resources is None or if the keys are not present.
        self._some_function: Callable = self.resources['some_function']
        self._numpy: ModuleType = self.resources['numpy']

    def get_name(self) -> str:
        return self.name

    def some_function(self, x: int) -> Any:
        try:
            return self._some_function(x, self._numpy.array)
        except Exception as e:
            print(f"An error occurred in some_function: {e}")



def make_ioc_class_example() -> IocClassExample:
    """
    Example factory function to create an instance of IocClassExample.
    This function can be extended to include additional logic for IOC creation.

    It should:
    - Take no arguments.
    - Return an instance of IocClassExample.
    - Import global modules, libraries, and other dependencies as needed.
    - Initialize the resources and configs as needed.
    - Use the dependencies module to access third-party libraries.
    """
    resources = {
        "some_function": some_function,
        "bs4": dependencies.bs4  # Example of a third-party dependency
    }
    configs = Configs()
    return IocClassExample(resources=resources, configs=configs)
