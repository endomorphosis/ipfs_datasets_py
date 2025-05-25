import importlib
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

tool_category = "cli"
tool_name = "execute_command"
import_path = f"ipfs_datasets_py.mcp_server.tools.{tool_category}.{tool_name}"

try:
    module = importlib.import_module(import_path)
    print(f"Successfully imported {import_path}")
    if hasattr(module, tool_name):
        print(f"Tool function '{tool_name}' found in module.")
    else:
        print(f"Tool function '{tool_name}' not found in module.")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
