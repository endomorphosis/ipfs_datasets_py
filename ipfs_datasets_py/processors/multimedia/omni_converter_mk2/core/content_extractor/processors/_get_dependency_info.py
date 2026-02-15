from typing import Callable
import inspect
from unittest.mock import MagicMock


def get_dependency_info(resources: dict[str, Callable]) -> dict[str, str]:
    dependencies = {}

    # Get filenames from injected callables in resources
    for attr_name, attr_value in resources.items():
        match attr_value:
            case MagicMock():
                dependencies[attr_name] = "mock"
            # Built-in modules like os, sys, etc.
            case Callable() if attr_value.__module__ == "builtins":
                dependencies[attr_name] = "builtin"
            # Custom modules
            case Callable() if attr_value.__module__ != "builtins":
                file_name = inspect.getfile(attr_value)
                # Extract module name from path
                if "by_dependency" in file_name or "by_mime_type" in file_name:
                    # Split on either by_dependency or by_mime_type
                    parts = file_name.split("by_dependency" if "by_dependency" in file_name else "by_mime_type")
                    clean_name = parts[-1].strip("/_").replace(".py", "")
                else:
                    clean_name = file_name.split("/")[-1].replace(".py", "")
                dependencies[attr_name] = clean_name  
            case _:
                dependencies[attr_name] = "unknown"
    return dependencies