# import importlib
# import importlib.util
# import sys
# import os

# # Add the module path to sys.path and import the main module
# VALIDATOR_MODULE_DIR = os.path.expanduser('~/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator')

# def load_validator_module(name: str):
#     """Load the municipal bluebook citation validator module dynamically."""
#     # Construct the full file path
#     module_file_path = os.path.join(VALIDATOR_MODULE_DIR, f"{name}.py")
    
#     # Check if the file exists
#     if not os.path.exists(module_file_path):
#         raise FileNotFoundError(f"Module file not found: {module_file_path}")
    
#     # Add the directory to sys.path if not already there
#     if VALIDATOR_MODULE_DIR not in sys.path:
#         sys.path.insert(0, VALIDATOR_MODULE_DIR)
    
#     # Load the module
#     spec = importlib.util.spec_from_file_location(name, module_file_path)
    
#     if spec is None:
#         raise ImportError(f"Could not load spec for module: {name} from {module_file_path}")
    
#     if spec.loader is None:
#         raise ImportError(f"No loader available for module: {name}")
    
#     module = importlib.util.module_from_spec(spec)
#     spec.loader.exec_module(module)
#     return module

# # Load the validator module
# bluebook_validator = load_validator_module("main")
