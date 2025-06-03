from dataclasses import dataclass
import importlib
import importlib.util
from typing import TypeVar

Dependency = TypeVar('Dependency', bound=importlib.util.module_from_spec)

_DEPENDENCIES_SET = {
    "duckdb",
    "jinja2",
    "pandas",
    "pyarrow"
    "pydantic",
    "yaml",
}

@dataclass
class _Dependencies:
    duckdb: 'Dependency' = None
    pandas: 'Dependency' = None
    pyarrow: 'Dependency' = None
    pydantic: 'Dependency' = None
    yaml: 'Dependency' = None

    def __post_init__(self):
        # Import dependencies dynamically and assign them to the Dependencies dataclass
        for dep in _DEPENDENCIES_SET:
            try:
                dependencies = setattr(importlib.import_module(dep), dependencies)
            except ImportError as e:
                raise ImportError(f"Failed to import {dep}. Please ensure it is installed.") from e

dependencies = _Dependencies()
