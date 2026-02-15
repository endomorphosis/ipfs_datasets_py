from typing import Callable, Protocol, Dict, Any, Optional, runtime_checkable
from pathlib import Path


@runtime_checkable
class DependencyModuleProtocol(Protocol):
    """Protocol defining the interface for dependency content extraction modules."""
    
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
    """
    Dynamically apply the DependencyModuleProtocol to all modules in the current directory.
    
    NOTE: As dependencies may vary widely in functionality, some dependencies may implement only stubs for the protocol methods.
    This check does also not guarantee that the callables are implemented correctly/run without erroring.
    
    """
    import importlib
    import pkgutil
    import inspect
    this_dir = Path(__file__).parent.name

    # Always assume that the files *don't* follow the protocol.
    # Better safe than sorry.
    all_files_follow_the_protocol = False
    failed_files = {}

    for module_info in pkgutil.iter_modules([Path(__file__).parent]):
        module_name = f"{this_dir}.{module_info.name}"
        module = importlib.import_module(module_name)

        failed_files[module_name] = []

        protocol_methods = [
            'extract_text',
            'extract_metadata',
            'extract_structure',
            'process'
        ]
        for method in protocol_methods:
            try:
                func = getattr(module, method)  # Check if the method exists
            except Exception as e:
                msg = f"Module {module_name} does not implement protocol method {method}: {e}"
                print(msg)
                failed_files[module_name].append(msg)
                continue
        
            # Type-check the function signature against the protocol
            # - Is it a callable?
            # - Does it have type hints for its arguments and return type?
            # - Does it accept the correct arguments?
            # - Does it return the expected type?
            if not isinstance(func, Callable):
                msg = f"Module {module_name} does not implement protocol method {method} as a callable."
                print(msg)
                failed_files[module_name].append(msg)
                continue
            
            # Check if function has type annotations
            sig = inspect.signature(func)
            
            # Define expected signatures for each protocol method
            expected_signatures = {
                'extract_text': {
                    'params': ['data', 'options'],
                    'param_types': [str | bytes, Optional[dict[str, Any]]],
                    'return_type': str
                },
                'extract_metadata': {
                    'params': ['text', 'options'],
                    'param_types': [str, Optional[dict[str, Any]]],
                    'return_type': dict[str, Any]
                },
                'extract_structure': {
                    'params': ['self', 'text', 'options'],
                    'param_types': [Any, str, Optional[dict[str, Any]]],
                    'return_type': list[dict[str, Any]]
                },
                'process': {
                    'params': ['self', 'data', 'options'],
                    'param_types': [Any, bytes | str, Optional[dict[str, Any]]],
                    'return_type': tuple[str, dict[str, Any], list[dict[str, Any]]]
                }
            }
            
            expected = expected_signatures.get(method)
            if expected:
                # Check parameter names and count
                param_names = list(sig.parameters.keys())
                if param_names != expected['params']:
                    msg = f"Module {module_name} method {method} has incorrect parameters. Expected: {expected['params']}, Got: {param_names}"
                    print(msg)
                    failed_files[module_name].append(msg)
                    continue
                
                # Check return type annotation if present
                if sig.return_annotation != inspect.Signature.empty:
                    if sig.return_annotation != expected['return_type']:
                        msg = f"Module {module_name} method {method} has incorrect return type annotation. Expected: {expected['return_type']}, Got: {sig.return_annotation}"
                        print(msg)
                        failed_files[module_name].append(msg)
                        continue



    if not failed_files:
        all_files_follow_the_protocol = True
    assert all_files_follow_the_protocol, f"Dependency {module_name} does not implement DependencyModuleProtocol"

if __name__ == "__main__":
    try:
        apply_fallback_module_protocol_to_files_in_this_dir()
    except Exception as e:
        print(f"Unexpected Error applying DependencyModuleProtocol: {e}")