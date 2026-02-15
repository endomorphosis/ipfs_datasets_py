# from types_ import Any, Callable, Configs, Logger, Protocol
import logging
from typing import Protocol, Callable, Any, Dict, TypeVar

Configs = TypeVar('Configs')


class Processor(Protocol):

    def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
        """
        Initialize the processor with resources and configurations.
        """
        self.resources = resources
        self.configs = configs

        self._supported_formats: set[str] = self.resources["supported_formats"]
        self._processor_available: bool = self.resources["processor_available"]
        self._processor_name: str = self.resources["processor_name"]

        self._get_version: Callable = self.resources["get_version"]
        self._extract_structure: Callable = self.resources["extract_structure"]
        self._extract_text: Callable = self.resources["extract_text"]
        self._extract_metadata: Callable = self.resources["extract_metadata"]
        self._open_file: Callable = self.resources["open_file"]
        self._process: Callable = self.resources["process"]

        self._logger: logging.Logger = self.resources["logger"]


    def __call__(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """
        Process the given data and return a tuple of (text content, metadata, sections).
        """
        ...

    def process(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """
        Process the content and return it unchanged.
        """
        ...

    def extract_text(self, data: bytes | str, options: dict[str, Any]) -> str:
        """
        Extract text from the given data.
        """
        ...

    def extract_metadata(self, data: bytes | str, options: dict[str, Any]) -> dict[str, Any]:
        """
        Extract metadata from the given data.
        """
        ...

    def extract_structure(self, data: bytes | str, options: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract structure from the given data.
        """
        ...

    def get_version(self) -> str:
        """
        Get the version of the processor.
        
        Returns:
            The version of the processor.
        """
        ...

def apply_processor_protocol_to_files_in_this_dir():
    """
    Dynamically apply the Processor protocol to all modules in the current directory.
    
    NOTE: As dependencies may vary widely in functionality, some dependencies may implement only stubs for the protocol methods.
    Alternatively, some processors may implement additional methods that are not part of the protocol. 
    Anything defined outside the class should be a private method to avoid conflicts with the protocol.
    
    """
    from pathlib import Path
    import importlib
    import pkgutil
    this_dir = Path(__file__).parent.name

    for module_info in pkgutil.iter_modules([Path(__file__).parent]):
        module_name = f"{this_dir}.{module_info.name}"
        module = importlib.import_module(module_name)
        for attr in dir(module):
            if attr.startswith('_'):
                continue
            else:
                assert isinstance(module, Processor), f"Mime-type processor '{module_name}' does not implement Processor protocol"

if __name__ == "__main__":
    apply_processor_protocol_to_files_in_this_dir()
    print("All mime-type processors in this directory implement the Processor protocol.")