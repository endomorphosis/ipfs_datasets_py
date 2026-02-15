"""
Lazy loading of dependencies to optimize performance and reduce initial load time.

Modules can access these dependencies via the `dependencies` object.
"""
# NOTE Make imports private to enforce singleton pattern.
from types import ModuleType as _ModuleType
from importlib import import_module as _import_module # NOTE We import this outside the class to avoid circular imports.
import threading as _threading

class _Dependencies:
    """
    Class to enable the lazy-loading of dependencies and third-party libraries.
    This optimizes performance, allows for dynamic error checking, and reduce initial load time.
    """

    _CRITICAL_DEPENDENCIES: list[str] = [
        "tqdm",  "yaml", "psutil", "pydantic", "magic"
    ]

    def __init__(self) -> None:
        self._cache: dict[str, _ModuleType | None] = {
            "anthropic": None,
            "bs4": None,  # BeautifulSoup for HTML processing
            "chardet": None,  # Character encoding detection
            "cv2": None,
            "docx": None,
            "duckdb": None,
            "llama_cpp": None, # TODO Confirm library name.
            "jinja2": None,
            "markitdown": None,  # Other multi-format-to-text conversion program. (optional)
            "multiformats": None,
            "numpy": None,
            "openai": None,
            "openpyxl": None,
            "pandas": None,
            "PIL": None,  # Pillow for image processing NOTE Capitalization is important here.
            "playsound3": None,  # Playsound for audio playback
            "psutil": None,
            "pydantic": None, # TODO FIgure out how to get types from pydantic without importing it.
            "pydub": None,
            "pymediainfo": None,
            "PyPDF2": None,
            "pytesseract": None,
            "pydocx": None, # TODO Confirm libraries existence.
            "pymediainfo": None,
            "rouge": None,
            "tiktoken": None,
            "torch": None,  # PyTorch for LLM usage.
            "tqdm": None,
            "whisper": None,
            "yaml": None,
            "xformers": None,  # Optional for memory-efficient LLMs.
            "xformers.ops": None,
            "torch_directml": None,  # Optional for DirectML support on Windows.
            "intel_extension_for_pytorch": None,  # Optional for Intel hardware acceleration.
            "torch.mps": None,  # Optional for Apple Silicon support.
            "rasterio": None,  # Optional for geospatial data processing.
            "geopandas": None,  # Optional for geospatial data processing.
            "requests": None,  # Optional for HTTP requests.
            "requests_cache": None,  # Optional for caching HTTP requests.
            "httpx": None,  # Optional for asynchronous HTTP requests.
            "httpx_cache": None,  # Optional for caching asynchronous HTTP requests.
            "aiohttp": None,  # Optional for asynchronous HTTP requests.
            "aiohttp_cache": None,  # Optional for caching asynchronous HTTP requests.
            "selenium": None,  # Optional for web scraping.
            "magic": None # python-magic
        }

    def check_critical_dependencies(self) -> None:
        """
        Check if all critical dependencies are available.
        
        Raises:
            ImportError: If any critical dependency is not available.
        """
        for dep in self._CRITICAL_DEPENDENCIES:
            try:
                self._load_module(dep)
            except Exception as e:
                raise ImportError(f"Critical dependency '{dep}' is not available. Please install it to run the application.") from e

    def load_all_modules(self) -> None:
        """
        Load all modules and cache them.
        
        This is called at the start of the program to check which dependencies are available.
        """
        for module_name in self._cache.keys():
            try:
                self._load_module(module_name)
            except Exception as e:
                print(f"✗ Dependency '{module_name}' is not available.")
                pass # Ignore errors for non-critical dependencies.
            finally:
                self.clear_module(module_name)

    def _load_module(self, module_name: str) -> _ModuleType | None:
        if self._cache[module_name] is None:
            try:
                self._cache[module_name] = _import_module(module_name)
                print(f"✓ Dependency '{module_name}' loaded successfully.")
            except ModuleNotFoundError as e:
                print(f"✗ Could not find dependency '{module_name}'.")
            except Exception as e:
                raise ImportError(f"✗ Could not import dependency '{module_name}': {e}") from e
        return self._cache[module_name]

    def __str__(self) -> str:
        return "_Dependencies"

    def startswith(self, prefix: str) -> bool: # TODO Remove this debug code later.
        import traceback
        print(f"startswith called with prefix: {prefix}")
        print("Call stack:")
        traceback.print_stack()
        return str(self).startswith(prefix)

    def __repr__(self) -> str:
        loaded_modules = [name for name, module in self._cache.items() if module is not None]
        return f"<_Dependencies loaded: {loaded_modules}>"

    def clear_cache(self) -> None:
        """
        Clear the cache of loaded modules.

        Used to save memory when large dependencies are no longer needed.
        """
        self._cache = {key: None for key in self._cache.keys()}

    def clear_module(self, module_name: str) -> None:
        """Clear a specific module from the cache.

        Args:
            module_name (str): The name of the module to clear.
        """
        if module_name in self._cache:
            self._cache[module_name] = None
        else:
            raise KeyError(f"Module '{module_name}' not found in dependencies.")

    def is_available(self, module_name: str) -> bool: # TODO Test this method.
        """
        Check if a specific module is available.

        Args:
            module_name (str): The name of the module to check.

        Returns:
            bool: True if the module is available, False otherwise.
        """
        return self._load_module(module_name) is not None

    @property
    def anthropic(self) -> _ModuleType | None:
        return self._load_module('anthropic')

    @property
    def bs4(self) -> _ModuleType | None:
        return self._load_module('bs4')

    @property
    def duckdb(self) -> _ModuleType | None:
        return self._load_module('duckdb')

    @property
    def multiformats(self) -> _ModuleType | None:
        return self._load_module('multiformats')

    @property
    def numpy(self) -> _ModuleType | None:
        return self._load_module('numpy')

    @property
    def openai(self) -> _ModuleType | None:
        return self._load_module('openai')

    @property
    def pandas(self) -> _ModuleType | None:
        return self._load_module('pandas')

    @property
    def pil(self) -> _ModuleType | None:
        return self._load_module('PIL')

    @property
    def playsound(self) -> _ModuleType | None:
        return self._load_module('playsound3')
    
    @property
    def python_docx(self) -> _ModuleType | None:
        return self._load_module('docx')

    @property
    def pydantic(self) -> _ModuleType | None:
        return self._load_module('pydantic')

    @property
    def tiktoken(self) -> _ModuleType | None:
        return self._load_module('tiktoken')

    @property
    def torch(self) -> _ModuleType | None:
        return self._load_module('torch')

    @property
    def tqdm(self) -> _ModuleType | None:
        return self._load_module('tqdm')

    @property
    def pytesseract(self) -> _ModuleType | None:
        return self._load_module('pytesseract')

    @property
    def pymediainfo(self) -> _ModuleType | None:
        return self._load_module('pymediainfo')

    @property
    def cv2(self) -> _ModuleType | None:
        """Load the cv2 module."""
        return self._load_module('cv2')

    @property
    def pydub(self) -> _ModuleType | None:
        """Load the pydub module."""
        return self._load_module('pydub')
    
    @property
    def openpyxl(self) -> _ModuleType | None:
        """Load the openpyxl module."""
        return self._load_module('openpyxl')

    @property
    def whisper(self) -> _ModuleType | None:
        """Load the whisper module."""
        return self._load_module('whisper')

    @property
    def chardet(self) -> _ModuleType | None:
        """Load the chardet module."""
        return self._load_module('chardet')
    
    @property
    def magic(self) -> _ModuleType | None:
        return self._load_module('magic')

    def keys(self) -> list[str]:
        """Get a list of all dependency names.
        
        Returns:
            A list of dependency names.
        """
        return [name for name in self._cache.keys()]

    def values(self) -> list[_ModuleType | None]:
        """Get a list of all loaded modules.
        
        Returns:
            A list of loaded modules, with None for unloaded modules.
        """
        return list(self._cache.values())

    def items(self) -> list[tuple[str, _ModuleType | None]]:
        """Get a list of all dependencies as (name, module) tuples.
        
        Returns:
            A list of tuples containing dependency names and their corresponding modules.
        """
        return [(name, module) for name, module in self._cache.items()]

    def __iter__(self):
        """Iterate over the loaded modules."""
        for name, module in self._cache.items():
            if module is not None:
                yield name, module

    def __contains__(self, item: str) -> bool:
        """Check if a specific module is loaded."""
        return item in self._cache and self._cache[item] is not None

    def __getitem__(self, item: str) -> _ModuleType | None:
        """Get a specific module by name."""
        return self._load_module(item)

try:
    dependencies = _Dependencies()
    dependencies.check_critical_dependencies()
except ImportError as e:
    # Prevent the application from starting if critical dependencies are missing.
    import sys
    sys.exit(1)

def _test_for_non_critical_dependencies() -> None:
    """
    Test for non-critical dependencies in a separate thread to ensure the application starts promptly and to avoid dead.

    This function creates a temporary instance of the `_Dependencies` class to load all required
    modules without causing deadlocks. Once all modules have been checked, the temporary instance is
    cleared from memory to optimize resource usage.

    Key Steps:
    1. Creates a separate `_Dependencies` instance to handle module loading.
    2. Ensures all modules are loaded using `load_all_modules`.
    3. Clears the cache and deletes the temporary instance to free up memory.
    4. Triggers garbage collection to reclaim unused memory.

    Note:
    - This function is designed to handle non-critical dependencies, allowing the application
        to start without waiting for all dependencies to be fully loaded.
    """
    import gc
    # Make a separate _Dependencies instance to avoid deadlocks.
    dependencies = _Dependencies()
    try:
        dependencies.load_all_modules()
    finally:
        # Delete and garbage collect the separate instance to free up memory.
        dependencies.clear_cache()
        del dependencies
        gc.collect()

_load_thread = _threading.Thread(target=_test_for_non_critical_dependencies, daemon=True)
_load_thread.start()
