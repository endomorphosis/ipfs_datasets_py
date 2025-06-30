from dataclasses import dataclass
import importlib
import importlib.util
from typing import TypeVar

Dependency = TypeVar('Dependency', bound=importlib.util.module_from_spec)

_DEPENDENCIES_SET = {
    "bs4",  # beautifulsoup4
    "duckdb",
    "jinja2",
    "pandas",
    "pyarrow",
    "pydantic",
    "tqdm",
    "yaml",  # pyyaml
}

@dataclass
class _Dependencies:
    bs4: 'Dependency' = None
    duckdb: 'Dependency' = None
    jinja2: 'Dependency' = None
    pandas: 'Dependency' = None
    pydantic: 'Dependency' = None
    pyarrow: 'Dependency' = None
    tqdm: 'Dependency' = None
    yaml: 'Dependency' = None

    def __post_init__(self):
        # Import dependencies dynamically and assign them to the Dependencies dataclass
        for dep in _DEPENDENCIES_SET:
            try:
                dependencies = setattr(importlib.import_module(dep), dependencies)
            except ImportError as e:
                raise ImportError(f"Failed to import '{dep}'. Please ensure it is installed.\n\n{e}") from e

         # Validate that all dependencies are imported
        for dep in _DEPENDENCIES_SET:
            if getattr(self, dep) is None:
                raise ImportError(f"Critical dependency '{dep}' was not imported correctly. Please check your installation.")

dependencies = _Dependencies()
