"""
Protocols for various 
"""
from pathlib import Path
from configs import configs
from logger import logger
from typing import Any, Callable, Protocol, runtime_checkable

try:
    from pydantic import BaseModel
except ImportError:
    raise ImportError("Pydantic is required for this module. Please install it with 'pip install pydantic'.")


import importlib.util

@runtime_checkable
class ProcessorModuleProtocol(Protocol):
    def __init__(self, *, resources: dict[str, Callable], configs: BaseModel) -> None:...
    def extract_structure(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]: ...
    def extract_metadata(self, data: str, options: dict | None = None) -> dict: ...
    def extract_text(self, data: str, options: dict | None = None) -> str: ...
    def process(self, data: Any, options: dict) -> tuple[str, dict, list]: ...



class ModuleWrapper:
    def __init__(self, module):
        self.__dict__.update(module.__dict__)

# # Load and wrap module
# spec = importlib.util.spec_from_file_location("processor", "path/to/processor.py")
# module = importlib.util.module_from_spec(spec)
# spec.loader.exec_module(module)
# wrapped = ModuleWrapper(module)

# # Now you can type check
# assert isinstance(wrapped, ProcessorModuleProtocol)


@runtime_checkable
class NormalizerFunction(Protocol):
    """Protocol for normalizer functions."""

    def __call__(self, text: str) -> str:
        """Normalize text.

        Args:
            text (str): The text to normalize.

        Returns:
            str: The normalized text.
        """
        ...


class ProcessFunction(Protocol):
    """Protocol for processor functions."""

    def __call__(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """Process data.

        Args:
            data (bytes | str): The file content to process.
            options (dict[str, Any]): Processing options.
            
        Returns:
            Tuple of (text content, metadata, sections).
        """
        ...

class ExtractTextFunction(Protocol):
    """Protocol for text extraction functions."""

    def __call__(self, data: bytes | str, options: dict[str, Any]) -> str:
        """Extract text from data."""
        ...

class ExtractMetadataFunction(Protocol):
    """Protocol for metadata extraction functions."""

    def __call__(self, data: bytes | str, options: dict[str, Any]) -> dict[str, Any]:
        """Extract metadata from data."""
        ...

class ExtractSectionsFunction(Protocol):
    """Protocol for section extraction functions."""

    def __call__(self, data: bytes | str, options: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract sections from data."""
        ...

class ProcessorByAbility(Protocol):
    """Protocol for validator functions."""

    def __call__(self, data: Any) -> None:
        """Validate data, raise exception if invalid."""
        ...

class ProcessorByFormat(Protocol):
    """Protocol for processor functions."""

    def __init__(self, resources: dict[str, Callable], configs: BaseModel) -> None:
        """Process data and return (text, metadata, sections)."""
        ...

class Processor(Protocol):
    """Protocol for processor classes."""

    def __init__(self, resources: dict[str, Callable], configs: BaseModel) -> None:
        """Process data and return (text, metadata, sections)."""
        ...

    def can_process(self, format_name: str) -> bool:
        """Check if this processor can handle the given format."""
        ...

    @property
    def supported_formats(self) -> list[str]:
        """Get the list of formats supported by this processor."""
        ...

    def get_processor_info(self) -> dict[str, Any]:
        """Get information about this processor."""
        ...

    def extract_text(self, data: bytes | str, options: dict[str, Any]) -> str:
        """Extract text from data."""
        ...

    def extract_metadata(self, data: bytes | str, options: dict[str, Any]) -> dict[str, Any]:
        """Extract metadata from data."""
        ...

    def extract_structure(self, data: bytes | str, options: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract sections from data."""
        ...