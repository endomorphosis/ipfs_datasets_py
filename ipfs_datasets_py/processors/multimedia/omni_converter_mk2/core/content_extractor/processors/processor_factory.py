"""
Processor factory for dynamically creating content processors.

This module provides functionality to create processors based on available
dependencies, with graceful fallback to mock implementations when dependencies
are unavailable.
"""
from __future__ import annotations
import functools
import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import MagicMock


from configs import Configs
from dependencies import dependencies as dependency_cache
from types_ import Any, Logger, Optional, TypedDict, Union, ModuleType
from ._get_processor_resource_configs import get_processor_resource_configs


class _ProcessorResources(TypedDict):
    """
    TypedDict defining the structure of processor resources.

    Attributes:
        supported_formats: Set of formats supported by the processor.
        processor_name: Name of the processor.
        dependencies: Dictionary mapping dependency names to their instances
        critical_resources: List of critical callables required by the processor. 
        optional_resources: List of optional callables that enhance functionality
        logger: Logger instance for logging messages
        configs: Configs instance containing configuration settings
        dependency_priority: Optional list defining priority order of dependencies
        dependency_mapping: Optional mapping of resources to required dependencies
    """
    supported_formats: set[str]
    processor_name: str
    dependencies: dict[str, Optional[Any]]
    critical_resources: list[str]
    optional_resources: list[str]
    logger: logging.Logger
    configs: Configs
    dependency_priority: Optional[list[str]]
    dependency_mapping: Optional[dict[str, list[str]]]


class _GenericProcessor:

    def __init__(self, resources: _ProcessorResources = None, configs: Configs = None):
        self.resources = resources
        self.configs = configs

        self._logger = resources["logger"]
        self._process = resources["process"]
        self._extract_text = resources["extract_text"]
        self._extract_metadata = resources["extract_metadata"]
        self._extract_structure = resources["extract_structure"]
        self._can_handle = resources["can_handle"]

        self.supported_formats = resources["supported_formats"]
        self.format_extensions = resources["format_extensions"]
        self.processor_info = {
            "processor_name": resources["processor_name"],
            "capabilities": {},
            "supported_formats": resources["supported_formats"],
            "implementation_used": "native",
            "dependencies": list(resources["dependencies"].keys())
        }
        for resources in resources["critical_resources"] + resources.get("optional_resources", []):
            if hasattr(self, resources):
                self.processor_info["capabilities"][resources] = {
                    "available": True,
                    "implementation": "native"
                }
            else:
                self.processor_info["capabilities"][resources] = {
                    "available": False,
                    "implementation": "mock"
                }

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return the capabilities of the processor."""
        return self.processor_info.get("capabilities", {})

    def extract_structure(self, data: str | bytes, options: Optional[dict[str, Any]]):
        return self._extract_structure(data, options)

    def extract_metadata(self, data: str | bytes, options: Optional[dict[str, Any]]):
        return self._extract_metadata(data, options)

    def extract_text(self, data: str | bytes, options: Optional[dict[str, Any]]):
        """Extract text content from the provided data."""
        return self._extract_text(data, options)

    def process(self, data: str | bytes, options: Optional[dict[str, Any]]):
        """Process the provided data and return text, metadata, and sections."""
        return self._process(data, options)

    def processor_available(self) -> bool:
        """Check if the processor is available."""
        return True

    def can_process(self, file_path: str) -> bool:
        """Check if the processor can handle the given file format."""
        return self._can_handle(self.supported_formats, self.format_extensions, file_path)

    def __call__(self, data, options):
        # Call the processor with the provided arguments
        return self.process(data, options)

    def __str__(self):
        return f"<{self.__class__.__name__} processor_name={self.processor_info['processor_name']}>"

    def __repr__(self):
        return f"<{self.__class__.__name__} processor_name={self.processor_info['processor_name']}>"


def _get_supported_formats_from_resource_config(resource_config) -> set[str]:
    value = resource_config["supported_formats"]
    match value:
        case str():
            return {value}
        case list() | tuple() | set():
            return set(value)
        case dict():
            # Assume dict values are the formats
            return set(value.values()) if value else set()
        case _:
            # Fallback for any other type, try to convert to set
            try:
                return set(value) if value else set()
            except (TypeError, ValueError):
                return set()


def _apply_cross_processor_dependencies(
    processors: dict[str, Any],
    dependencies: list[tuple[str, str, str, str]]
) -> dict[str, Any]:
    """
    Apply cross-processor dependencies by enhancing methods with other processors.
    
    This utility function allows one processor to use capabilities from another processor
    by wrapping the original method with enhanced functionality. The original method
    is called first, then each result is processed by the target processor's method.
    
    Args:
        processors (dict[str, Any]): Dictionary mapping processor names to processor instances.
        dependencies (list[tuple[str, str, str, str]]): list of dependency tuples, where each tuple contains:
        - source_proc_name (str): Name of the processor to enhance
        - source_method_name (str): Name of the method to enhance
        - target_proc_name (str): Name of the processor that provides enhancement
        - target_method_name (str): Name of the method that provides enhancement
    
    Returns:
        dict[str, Any]: The processors dictionary with enhanced methods applied.
    
    Raises:
        TypeError: If processors is not a dictionary or dependencies is not a list.
    
    Example:
        >>> processors = {
        ...     "xlsx_processor": xlsx_proc,
        ...     "image_processor": image_proc
        ... }
        >>> dependencies = [
        ...     ("xlsx_processor", "extract_images", "image_processor", "process_image")
        ... ]
        >>> enhanced_processors = _apply_cross_processor_dependencies(processors, dependencies)
        >>> # Now xlsx_processor.extract_images() will use image_processor.process_image()
        >>> # to enhance each extracted image
    """
    from logger import logger

    # Validate input types
    if not isinstance(processors, dict):
        raise TypeError("processors must be a dictionary")
    if not isinstance(dependencies, list):
        raise TypeError("dependencies must be a list")

    # Handle empty dependencies list
    if not dependencies:
        return processors
    
    temp_dict = {}
    # Process each dependency
    for dependency in dependencies:
        try:
            # Validate dependency format
            if not isinstance(dependency, tuple) or len(dependency) != 4:
                logger.warning(f"Invalid dependency format: {dependency}. Skipping.")
                continue
            else:
                logger.debug(f"Processing dependency: {dependency}")

            source_proc_name, source_method_name, target_proc_name, target_method_name = dependency
            # logger.debug(f"Source processor: {source_proc_name}, Source method: {source_method_name}, "
            #              f"Target processor: {target_proc_name}, Target method: {target_method_name}")

            # Check if processors exist
            if source_proc_name not in processors:
                logger.warning(f"Source processor '{source_proc_name}' not found. Skipping.")
                continue
            if target_proc_name not in processors:
                logger.warning(f"Target processor '{target_proc_name}' not found. Skipping.")
                continue
    
            source_processor = processors[source_proc_name]
            target_processor = processors[target_proc_name]
            
            # Check if methods exist
            try:
                original_method = getattr(source_processor, source_method_name)
            except AttributeError:
                logger.warning(f"Source processor '{source_proc_name}' does not have method '{source_method_name}'. Skipping...")
                continue
            try:
                target_method = getattr(target_processor, target_method_name)
            except AttributeError:
                logger.warning(f"Target processor '{target_proc_name}' does not have method '{target_method_name}'. Skipping...")
                continue
            
            # Create enhanced method
            def create_enhanced_method(orig_method: Callable, enhance_method: Callable) -> Callable:
                @functools.wraps(orig_method)
                def enhanced_method(*args, **kwargs):
                    # Call original method first
                    orig_result = orig_method(*args, **kwargs)
                    
                    # If original result is a list/iterable, enhance each item
                    try:
                        if isinstance(orig_result, (list, tuple)):
                            enhanced_results = []
                            for item in orig_result:
                                try:
                                    enhanced_item = enhance_method(item)
                                    enhanced_results.append(enhanced_item)
                                except Exception:
                                    # If enhancement fails, keep original item
                                    enhanced_results.append(item)
                            return type(orig_result)(enhanced_results)
                        else:
                            # Single item enhancement
                            return enhance_method(orig_result)
                    except Exception:
                        # If any enhancement fails, return original result
                        return orig_result
                
                return enhanced_method
            
            # Replace the original method with the enhanced one
            enhanced_method = create_enhanced_method(original_method, target_method)
            setattr(source_processor, source_method_name, enhanced_method)
            
            # Update processor_info dependencies if it exists
            if hasattr(source_processor, 'processor_info'):
                if 'dependencies' not in source_processor.processor_info:
                    source_processor.processor_info['dependencies'] = []
                if target_proc_name not in source_processor.processor_info['dependencies']:
                    source_processor.processor_info['dependencies'].append(target_proc_name)
            else:
                # Create processor_info if it doesn't exist
                source_processor.processor_info = {'dependencies': [target_proc_name]}

            temp_dict[source_proc_name] = source_processor
    
        except Exception as e:
            logger.exception(f"Error processing dependency {dependency}: {e}")
            continue
    
    # Update the processors dictionary with enhanced methods
    if temp_dict:
        processors.update(temp_dict)

    return processors


class _MakeProcessor:

    def __init__(self, resources: _ProcessorResources):
        self.resources = resources

        self._supported_formats  = resources["supported_formats"]
        self._crit_resources     = resources["critical_resources"]
        self._optional_resources = resources.get("optional_resources", [])
        self._dependencies       = resources["dependencies"]
        self._logger             = resources["logger"]
        self._configs            = resources["configs"]
        self._name               = resources["processor_name"]

        self._base_path      = Path(__file__).parent
        self._ProcessorClass = _GenericProcessor

        self._dep_paths:       dict[str, Path] = self._get_python_files_from_directory(self._base_path / "by_dependency")
        self._mime_type_paths: dict[str, Path] = self._get_python_files_from_directory(self._base_path / "by_mime_type")
        self._fallback_paths:  dict[str, Path] = self._get_python_files_from_directory(self._base_path / "fallbacks")

        if self._name == "text_processor":
            self._logger.setLevel(logging.DEBUG)
        else:
            self._logger.setLevel(logging.INFO)

        self._debugging = False #self._logger.isEnabledFor(logging.DEBUG)

        if self._debugging:
            self._logger.debug(f"_make_processor called for {self._name}")
            self._logger.debug(f"base_path: {self._base_path}")
            self._logger.debug(f"supported_formats: {self._supported_formats}")
            self._logger.debug(f"dependencies: {self._dependencies}")

    @staticmethod
    def _get_python_files_from_directory(directory: Path) -> dict[str, Path]:
        """Get all Python files in a directory."""
        return {file.stem: file for file in directory.iterdir() if file.is_file() and file.suffix == '.py'}

    @staticmethod
    def _convert_to_pascal_case(string: str) -> str:
        """Convert a string to PascalCase."""
        return ''.join(word.capitalize() for word in string.split('_'))

    def _load_module_from_path(self, path: Path, proc_name: str = None) -> ModuleType:
        #self._logger.debug(f"Trying spec for '{self._name}' from '{path.parent.name}/{path.name}'")
        spec_name = proc_name or self._name
        if spec_name not in path.stem:
            raise ImportError(f"Module name '{spec_name}' does not match file name '{path.stem}'")
        spec = importlib.util.spec_from_file_location(spec_name, path)
        if spec and spec.loader:
            if self._debugging:
                self._logger.debug(f"Successfully created spec from '{path.parent.name}/{path.stem}', loading module")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        else:
            raise ImportError(f"Could not load module '{self._name}' from path '{path}'")

    def _get_callables_from_module(self, module: ModuleType) -> Optional[dict[str, Callable]]:
        module_name = module.__name__
        if self._debugging:
            self._logger.debug(f"Module {module_name} loaded, scanning for callables")

        # Get all the callables from the module
        attr_dict = {attr: getattr(module, attr) for attr in dir(module)}
        temp_dict = {}
        for attr, func in attr_dict.items(): # Skip private callables, non-callables, or those not defined in this module
            if not callable(func) or attr.startswith("_") or func.__module__ != module_name:
                temp_dict[attr] = func
        func_dict = {attr: func for attr, func in attr_dict.items() if attr not in temp_dict}

        #self._logger.debug(f"func_dict: {func_dict}")
        return func_dict

    def _load_functions_from_file(self, paths: dict[str, Path], callables_dict: dict = {}):
        if self._debugging: 
            self._logger.debug(f"load_functions_from_file called with paths: {paths}")
            self._logger.debug(f"name: {self._name}")
            self._logger.debug(f"critical_resources: {self._crit_resources}")

        for path in paths.values():
            # Skip __init__ files and non-Python files
            if path.name.startswith("__init__") or not path.suffix == ".py":
                if self._debugging:
                    self._logger.debug(f"Skipping file: {path}")
                #self._logger.debug(f"Skipping file: {path}")
                continue
            if self._debugging:
                self._logger.debug(f"Checking path: {path}")
            try:
                try:
                    module = self._load_module_from_path(path)
                except ImportError as e:
                    #self._logger.debug(f"Failed to load module from path {path}: {e}")
                    continue

                func_dict = self._get_callables_from_module(module)
                if func_dict is None or not func_dict:
                    #self._logger.debug(f"No callables found in {path}, skipping.")
                    continue
                else:
                    missing = [func for func in self._crit_resources if func not in func_dict.keys()]
                    if not missing:
                        #self._logger.debug(f"All critical resources found in {path}, updating callables_dict with {func_dict}")
                        callables_dict.update(func_dict)
                        break
                    #self._logger.debug(f"Missing critical resources, continuing to next path.\nMissing: {missing}")

            except Exception as e:
                self._logger.exception(f"Exception loading {path}: {e}")
                continue # Skip this file if it fails to load.

        #self._logger.debug(f"Returning callables_dict: {callables_dict}")

        return callables_dict

    def _get_processor_class_for_specific_mime_type(self) -> Any:

        ProcessorClass = _GenericProcessor
        is_generic = lambda proc: isinstance(proc, _GenericProcessor)

        for format in self._supported_formats:
            # Check for a specific mime-type processor
            proc_name = f"_{format.lower()}_processor"
            if proc_name in self._mime_type_paths.keys():
                path = self._mime_type_paths[proc_name]
            else:
                continue
            #self._logger.debug(f"Found mime-type processor at {path}")

            try: # If the path exists, try to load the module.
                module = self._load_module_from_path(path, proc_name)
            except ImportError as e:
                #self._logger.debug(f"Failed to load module from path {path}: {e}")
                continue

            # Import the processor class from the module
            pascal_case_name = self._convert_to_pascal_case(self._name)
            #self._logger.debug(f"pascal_case_name: {pascal_case_name}")
            callable_dict = self._get_callables_from_module(module)
            if pascal_case_name in callable_dict:
                ProcessorClass = getattr(module, pascal_case_name , _GenericProcessor)
                if not is_generic(ProcessorClass):
                    #self._logger.debug(f"Loaded ProcessorClass: '{ProcessorClass}'")
                    break

        #self._logger.debug(f"Using '{ProcessorClass}' for '{self._name}'")
        return ProcessorClass


    def _mock_processor(self, 
                        methods: dict[Union[str, tuple[str, Any]], str], 
                        supported_formats: set[str],
                        processor_name: str
                        ) -> MagicMock:
        """
        Create a mock processor with specified methods.
        
        Args:
            methods: Dictionary mapping method names to their categories
            supported_formats: Set of formats supported by the processor
            processor_name: Name of the processor being mocked
            
        Returns:
            MagicMock: Mock processor with all specified methods
        """
        mock = MagicMock(spec=list(methods.keys()))

        # Define mock return values based on method names
        mock_map = {
            "extract_text": "Mocked text content",
            "extract_metadata": {"mocked": "metadata"},
            "extract_structure": {"mocked": "structure"},
            "extract_images": [],
            "can_process": False,
            "process": True,
            "process_document": True,
            "open_file": True,
            "validate_format": True,
        }

        # Configure mock methods
        for method_spec, _ in methods.items():
            # Handle tuple specifications
            if isinstance(method_spec, tuple):
                method_name = method_spec[0]
            else:
                method_name = method_spec

            # Create mock method
            if method_name in mock_map:
                setattr(mock, method_name, MagicMock(return_value=mock_map[method_name]))
            else:
                _return_value = None
                # Heuristic for unknown methods
                if "extract" in method_name:
                    _return_value = {}
                elif "process" in method_name:
                    _return_value = True
                elif "open" in method_name:
                    _return_value = True
                elif "validate" in method_name:
                    _return_value = True
                else:
                    _return_value="Mocked"
                setattr(mock, method_name, MagicMock(return_value=_return_value))

        # Add processor_info property
        mock.processor_info = {
            "processor_name": processor_name,
            "capabilities": {},
            "supported_formats": set(),
            "implementation_used": "mock",
            "dependencies": []
        }
        mock.format_extensions = supported_formats
        
        # Mark all capabilities as mocked
        for method_spec in methods:
            method_name = method_spec[0] if isinstance(method_spec, tuple) else method_spec
            mock.processor_info["capabilities"][method_name] = {
                "available": False,
                "implementation": "mock"
            }

        return mock

    def _make_mock(self) -> MagicMock:
        # Create methods dict for mock
        methods = {}
        for resource in self._crit_resources + self._optional_resources:
            methods[resource] = "resource"
        methods["can_process"] = "validation"
        methods["process"] = "processing"
        methods["supported_formats"] = "property"
        methods["processor_info"] = "property"
        methods["logger"] = "property"
        methods["configs"] = "property"

        mock = self._mock_processor(methods, self._supported_formats, self._name)
        mock.supported_formats = self._supported_formats
        mock.processor_name = self._name
        mock.processor_info = {
            "processor_name": self._name,
            "capabilities": {},
            "supported_formats": self._supported_formats,
            "implementation_used": "mock",
            "dependencies": []
        }
        mock.logger = MagicMock(spec=Logger)
        mock.configs = MagicMock(spec=Configs)
        return mock

    def processor(self) -> Optional[Any]:
        if self._debugging:
            self._logger.debug(f"=== PROCESSOR CREATION DEBUG for {self._name} ===")
            self._logger.debug(f"ProcessorClass: {str(self._ProcessorClass)}")
            self._logger.debug(f"Critical resources needed: {self._crit_resources}")

        # Check if there's a processor for this specific mime-type.
        self._ProcessorClass: Any | _GenericProcessor = self._get_processor_class_for_specific_mime_type()
        callables_dict = {}

        # Check for dedicated dependencies first.
        if any(dep in path.stem for dep in self._dependencies.keys() for path in self._dep_paths.values()):
            #self._logger.debug("Checking dependency paths...")
            callables_dict = self._load_functions_from_file(self._dep_paths, callables_dict=callables_dict)
            #self._logger.debug(f"After dependency loading: {list(callables_dict.keys()) if callables_dict else 'None'}")

        if not callables_dict:
            #self._logger.debug("No dependency callables found, trying fallback paths...")
            # If no callables found, try to load the functions from the fallback folder.
            callables_dict = self._load_functions_from_file(self._fallback_paths, callables_dict=callables_dict)
            #self._logger.debug(f"After fallback loading: {list(callables_dict.keys()) if callables_dict else 'None'}")

        # Can't find any callables, return a mock processor.
        if not callables_dict:
            #self._logger.debug("No callables found anywhere, returning MagicMock.")
            return self._make_mock()
        else:
            #self._logger.debug(f"Successfully found callables: {list(callables_dict.keys())}")
            
            # Build resources
            resources = {func_name: func for func_name, func in self.resources.items()}
            #self._logger.debug(f"Initial resources keys: {list(resources.keys())}")
            
            resources.update(callables_dict)
            #self._logger.debug(f"After adding callables: {list(resources.keys())}")
            
            resources["supported_formats"] = self._supported_formats
            resources["format_extensions"] = self._supported_formats
            #self._logger.debug(f"Final resources keys: {list(resources.keys())}")

            # Log critical resources when debugging.
            if self._debugging:
                for crit_res in self._crit_resources:
                    if crit_res in resources:
                        self._logger.debug(f"✓ Critical resource '{crit_res}' found.")
                    else:
                        self._logger.error(f"✗ Critical resource '{crit_res}' MISSING!")

            try:
                #self._logger.debug(f"Attempting to create {self._ProcessorClass.__name__} instance...")
                processor = self._ProcessorClass(resources=resources, configs=resources["configs"])
                #self._logger.debug(f"Successfully created {self._ProcessorClass.__name__}")
                return processor
            except KeyError as e:
                self._logger.error(f"KeyError during instantiation: {e}")
                self._logger.error(f"Available resources: {list(resources.keys())}")
                return self._make_mock()
            except Exception as e:
                self._logger.error(f"Unexpected error during instantiation: {e}")
                return self._make_mock()


def _make_processor(resources: _ProcessorResources) -> Any:
    """Create a processor instance based on the provided resources.

    Args:
        resources: Dictionary containing processor resources and configurations.

    Returns:
        Processor instance with proper processor_info structure.
    """
    # Create a processor instance using the resources
    make = _MakeProcessor(resources)
    processor = make.processor()
    
    # Ensure proper processor_info structure for both real processors and mocks
    if processor:
        processor_name = resources["processor_name"]
        critical_resources = resources["critical_resources"]
        optional_resources = resources.get("optional_resources", [])
        all_resources = critical_resources + optional_resources
        
        # Initialize or update processor_info
        if not hasattr(processor, "processor_info"):
            processor.processor_info = {}
            
        # Ensure basic structure
        processor.processor_info.update({
            "processor_name": processor_name,
            "supported_formats": resources["supported_formats"],
            "dependencies": list(resources["dependencies"].keys())
        })
        
        # Build capabilities info
        capabilities = {}
        is_mock_processor = isinstance(processor, MagicMock)
        
        for resource_name in all_resources:
            if hasattr(processor, resource_name) and callable(getattr(processor, resource_name)):
                if is_mock_processor:
                    # For mock processors, mark all as unavailable/mock
                    capabilities[resource_name] = {
                        "available": False,
                        "implementation": "mock"
                    }
                else:
                    # For real processors, mark as available
                    capabilities[resource_name] = {
                        "available": True,
                        "implementation": "native"
                    }
            else:
                # Missing capabilities are marked as mock
                capabilities[resource_name] = {
                    "available": False,
                    "implementation": "mock"
                }
        
        processor.processor_info["capabilities"] = capabilities
        
        # Set implementation_used
        if is_mock_processor:
            processor.processor_info["implementation_used"] = "mock"
        else:
            # Check if we used a specific dependency
            available_deps = [dep for dep, val in resources["dependencies"].items() if val is not None]
            if available_deps:
                processor.processor_info["implementation_used"] = available_deps[0]
            else:
                processor.processor_info["implementation_used"] = "native"
    
    return processor


class _MakeProcessorCache:
    """Cache for processors to avoid recreating them on every call."""

    def __init__(self):
        self._processor_cache = None

    def __call__(self) -> dict[str, Any]:
        """Get processors, creating them if not already cached."""
        if self._processor_cache is None:
            self._processor_cache = self.make_processors()
        return self._processor_cache

    def clear_cache(self):
        """Clear the processor cache, forcing recreation on next call."""
        self._processor_cache = None

    def is_cached(self) -> bool:
        """Check if processors are currently cached."""
        return self._processor_cache is not None

    @staticmethod
    def make_processors() -> dict[str, Any]:
        """Create all processor instances.

        Returns:
            dict mapping processor names to processor instances
        """
        from configs import configs
        from logger import logger
        from __version__ import __version__
        from utils.handlers._can_handle import can_handle
        from dependencies import dependencies as dependency_cache

        processors = {}
        frozenset_dict = {}

        # Create processors from get_processor_resource_configs
        for resource_config in get_processor_resource_configs():
            # Add logger and configs to resources
            resource_config["supported_formats"] = _get_supported_formats_from_resource_config(resource_config)
            proc_name = resource_config["processor_name"]
            if proc_name in processors.keys():
                logger.warning(f"Processor {proc_name} already exists, skipping duplicate.")
                continue

            frozenset_dict.update({
                proc_name: resource_config["supported_formats"]
            })

            resources = {
                **resource_config,
                "logger": logger,
                "configs": configs,
                "get_version": lambda: __version__,
                "can_handle": can_handle, 
                "dependencies": dependency_cache,  # Use the global dependencies cache
                "processor_available": True,  # Assume all processors are available by default
            }
            try:
                #logger.debug(f"Creating processor {resource_config['processor_name']} with resources: {resources}")
                processor = _make_processor(resources)
                processors[proc_name] = processor
            except Exception as e:
                logger.exception(f"Failed to create processor {resource_config['processor_name']}: {e}")
                continue # Skip processors that fail to initialize. NOTE This should be logged, but only when in production mode.

        # Add cross-processor dependencies
        processors: dict[str, Any] = _apply_cross_processor_dependencies(
            processors=processors, 
            dependencies=[ # TODO This really should be dynamic based on what's in the processors dictionary.
                ("xlsx_processor", "extract_images", "image_processor", "process"),
                ("pdf_processor", "extract_images", "image_processor", "process"),
                ("docx_processor", "extract_images", "image_processor", "process"),
            ])

        # Make the keys of frozenset_dict into the keys of processors
        temp_dict = {}
        for proc_name, set_ in frozenset_dict.items():
            #logger.debug(f"Adding supported formats to processor {proc_name}: {set_}")
            processor = processors[proc_name]
            assert processor is not None, f"Processor {proc_name} is None, cannot add supported formats."
            proc_tuple = (proc_name, processor, set_)
            # if proc_name == "text_processor":
            #     logger.debug(f"{(proc_name, processor, set_)}")
            temp_dict[proc_name] = proc_tuple

        processors = temp_dict

        for proc in processors.values():
            assert isinstance(proc, tuple), f"Processor {proc} is not a tuple, but a {type(proc)}."

        #print(processors)

        return processors

# Create a singleton instance
_processor_cache = _MakeProcessorCache()
import threading
_processor_cache_lock = threading.RLock()

def make_processors():
    """Create all processor instances.

    Returns:
        dict mapping processor names to processor instances
    """
    with _processor_cache_lock:
        return _processor_cache()