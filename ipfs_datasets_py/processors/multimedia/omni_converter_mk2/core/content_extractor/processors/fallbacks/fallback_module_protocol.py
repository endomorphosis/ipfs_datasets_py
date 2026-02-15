from typing import Callable, Protocol, Dict, Any, Optional, runtime_checkable
from pathlib import Path


@runtime_checkable
class FallbackModuleProtocol(Protocol):
    """Protocol defining the interface for fallback content extraction modules."""
    
    def extract_text(data: str | bytes, options: Optional[dict[str, Any]]) -> str:
        """Extract plain text content from the file.
        
        Args:
            data: Bytes or string data to extract text from
            options: Processing options. The options may be general and/or specific to the format/module.
            
        Returns:
            Extracted text content as string
        """
        ...

    def extract_metadata(text: str, options: Optional[dict[str, Any]]) -> dict[str, Any]:
        """Extract metadata from the file.
        
        Args:
            data: Bytes or string data to extract metadata from
            options: Processing options. The options may be general and/or specific to the format/module.
            
        Returns:
            Dictionary containing metadata key-value pairs
        """
        ...

    def extract_structure(self, text: str, options: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract structural information from the file.
        
        Args:
            data: Bytes or string data to extract metadata from
            options: Processing options. The options may be general and/or specific to the format/module.

        Returns:
            A list of dictionaries containing structural information.
        """
        ...

    def process(self,
            data: bytes | str, 
            options: Optional[dict[str, Any]]
            ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """Process the file and return comprehensive extraction results.
        
        Args:
            data: Bytes or string data to process
            options: Processing options. The options may be general and/or specific to the format/module.
            
        Returns:
            A tuple containing all extracted information (text, metadata, structure)
        """
        ...

def apply_fallback_module_protocol_to_files_in_this_dir():
    """Dynamically apply the FallbackModuleProtocol to all modules in the current directory."""
    import importlib
    import pkgutil
    this_dir = Path(__file__).parent.name

    for module_info in pkgutil.iter_modules([Path(__file__).parent]):
        module_name = f"{this_dir}.{module_info.name}"
        module = importlib.import_module(module_name)

        assert isinstance(module, FallbackModuleProtocol), f"Module {module_name} does not implement FallbackModuleProtocol"
