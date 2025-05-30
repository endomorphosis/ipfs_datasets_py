#!/usr/bin/env python3

import sys
import importlib
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

# Test specific function imports
print("Testing specific function imports...")

# Test documentation_generator
try:
    module = importlib.import_module("ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator")

    print(f"Module: {module}")
    print(f"Module __name__: {module.__name__}")

    # Check if documentation_generator exists and its properties
    if hasattr(module, 'documentation_generator'):
        func = getattr(module, 'documentation_generator')
        print(f"Function found: {func}")
        print(f"Function callable: {callable(func)}")
        print(f"Function __module__: {getattr(func, '__module__', 'NO MODULE ATTR')}")
        print(f"Function module matches: {getattr(func, '__module__', None) == module.__name__}")
    else:
        print("documentation_generator function not found in module")
        print("Available attributes:")
        for attr in dir(module):
            if not attr.startswith('_'):
                print(f"  - {attr}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
