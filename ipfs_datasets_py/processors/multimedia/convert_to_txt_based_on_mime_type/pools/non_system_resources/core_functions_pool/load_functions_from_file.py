import os
import importlib.util
import inspect

def load_functions_from_files(directory_path: str):
    """
    Example
        function_dict = load_functions_from_files('/path/to/your/directory')
    """
    function_dict = {}

    # Iterate through all Python files in the directory
    for filename in os.listdir(directory_path):
        if filename.endswith('.py'):
            # Get the full file path
            file_path = os.path.join(directory_path, filename)
            
            # Create a module specification
            spec = importlib.util.spec_from_file_location(filename[:-3], file_path)
            module = importlib.util.module_from_spec(spec)

            # Load the module
            spec.loader.exec_module(module)

            # Get all functions from the module
            functions = inspect.getmembers(module, inspect.isfunction)

            # Store functions in dictionary with filename as key
            function_dict[filename] = functions

    return function_dict

