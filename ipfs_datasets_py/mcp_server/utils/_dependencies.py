"""
Lazy loading of dependencies to optimize performance and reduce initial load time.

Tools can access these dependencies via the `dependencies` object.
"""
from importlib import import_module as _import_module # NOTE We call this outside of the class to avoid circular imports.

class _Dependencies:

    def __init__(self):
        self._cache = {
            "playsound3": None,
            "openai": None,
            "duckdb": None,
            "pandas": None,
            "pydantic": None, # TODO FIgure out how to get types from pydantic without importing it.
            "numpy": None,
            "tiktoken": None,
            "multiformats": None,
        }

    def _load_module(self, module_name: str):
        if self._cache[module_name] is None:
            try:
                self._cache[module_name] = _import_module(module_name)
            except ModuleNotFoundError as e:
                raise ModuleNotFoundError(f"Module '{module_name}' is not installed. Please install it to use this tool.")
            except Exception as e:
                raise ImportError(f"Could not import third-party module '{module_name}': {e}") from e
        return self._cache[module_name]

    def __str__(self):
        return "_Dependencies"

    def startswith(self, prefix: str) -> bool: # TODO Remove this debug code later.
        import traceback
        print(f"startswith called with prefix: {prefix}")
        print("Call stack:")
        traceback.print_stack()
        return str(self).startswith(prefix)

    def __repr__(self):
        loaded_modules = [name for name, module in self._cache.items() if module is not None]
        return f"<_Dependencies loaded: {loaded_modules}>"

    @property
    def duckdb(self):
        return self._load_module('duckdb')

    @property
    def multiformats(self):
        return self._load_module('multiformats')

    @property
    def numpy(self):
        return self._load_module('numpy')

    @property
    def openai(self):
        return self._load_module('openai')

    @property
    def pandas(self):
        return self._load_module('pandas')

    @property
    def playsound(self):
        return self._load_module('playsound3')
    
    @property
    def pydantic(self):
        return self._load_module('pydantic')

    @property
    def tiktoken(self):
        return self._load_module('tiktoken')


dependencies = _Dependencies()
