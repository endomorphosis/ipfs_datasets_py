# plugin_discovery.py
import os
import importlib.util
import inspect
from pathlib import Path
from typing import Callable

from dependencies import dependencies
from external_programs import ExternalPrograms

def _discover(base_path: Path) -> dict[str, Callable]:
    """Discover all processor functions without modifying files."""
    output = {}
    
    # Scan for processor modules
    for file_path in base_path.glob("*_processor.py"):
        module_name = file_path.stem
        
        # Load module dynamically
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Look for any public functions
        for attr_name in dir(module):
            if not attr_name.startswith("_"):
                func = getattr(module, attr_name)
                if callable(func):
                    output[attr_name] = func

    return output

def get_processors_by_ability(base_path: Path) -> dict[str, Callable]:
    public_classes = {}
    resources = _discover(base_path)




def get_classes(): ...

def get_processors(): ...

# In factory, instead of manual imports:
def make_all_processors():
    return _discover(Path("processors/dependency_modules/"))
