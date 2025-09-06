#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPFS Datasets CLI Tool

A command line interface that provides convenient access to the MCP tools
with simplified syntax. This tool allows users to interact with datasets,
IPFS, vector stores, and other features without the complexity of the full
MCP protocol.

Usage:
    ipfs-datasets-cli dataset load <source> [options]
    ipfs-datasets-cli dataset save <data> <destination> [options]
    ipfs-datasets-cli ipfs get <hash> [options]
    ipfs-datasets-cli ipfs pin <data> [options]
    ipfs-datasets-cli vector create <data> [options]
    ipfs-datasets-cli vector search <query> [options]
    ipfs-datasets-cli --help
"""

import argparse
import asyncio
import json
import sys
import subprocess
import signal
import os
import time
import importlib
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable
import traceback

# Optional imports for better process management
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def setup_sys_path():
    """Add the package to sys.path if needed."""
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))


def discover_mcp_tools() -> Dict[str, Dict[str, Any]]:
    """Discover all available MCP tools from the mcp_server.tools directory."""
    setup_sys_path()
    
    tools_by_category = {}
    base_tools_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
    
    if not base_tools_path.exists():
        return tools_by_category
    
    # Scan for tool categories (directories)
    for category_dir in base_tools_path.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith('_'):
            continue
            
        category_name = category_dir.name
        tools_by_category[category_name] = {}
        
        # Scan for Python files in the category
        for tool_file in category_dir.glob("*.py"):
            if tool_file.name.startswith('_') or tool_file.name == "__init__.py":
                continue
                
            tool_name = tool_file.stem
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category_name}.{tool_name}"
            
            try:
                # Try to import the module
                module = importlib.import_module(module_path)
                
                # Look for callable functions in the module
                functions = []
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    if not name.startswith('_') and name not in ['main', 'setup', 'test']:
                        sig = inspect.signature(obj)
                        functions.append({
                            'name': name,
                            'signature': str(sig),
                            'doc': obj.__doc__ or "No description available"
                        })
                
                if functions:
                    tools_by_category[category_name][tool_name] = {
                        'module_path': module_path,
                        'functions': functions,
                        'file_path': str(tool_file)
                    }
                    
            except Exception as e:
                # Skip modules that can't be imported
                pass
                
    return tools_by_category


def convert_cli_args_to_kwargs(args: List[str]) -> Dict[str, Any]:
    """Convert CLI arguments to keyword arguments for tool functions."""
    kwargs = {}
    i = 0
    
    while i < len(args):
        arg = args[i]
        
        if arg.startswith('--'):
            key = arg[2:]  # Remove --
            
            # Check if next arg is a value or another flag
            if i + 1 < len(args) and not args[i + 1].startswith('--'):
                value = args[i + 1]
                
                # Try to parse as JSON, number, or boolean
                try:
                    if value.lower() in ['true', 'false']:
                        kwargs[key] = value.lower() == 'true'
                    elif value.startswith('{') or value.startswith('['):
                        kwargs[key] = json.loads(value)
                    elif value.isdigit():
                        kwargs[key] = int(value)
                    elif '.' in value and value.replace('.', '').isdigit():
                        kwargs[key] = float(value)
                    else:
                        kwargs[key] = value
                except:
                    kwargs[key] = value
                    
                i += 2
            else:
                # Boolean flag without value
                kwargs[key] = True
                i += 1
        else:
            # Positional argument - use as 'data' or 'input'
            if 'data' not in kwargs and 'input' not in kwargs:
                kwargs['data'] = arg
            i += 1
    
    return kwargs


async def execute_tool(category: str, tool_name: str, function_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a specific tool function with given arguments."""
    try:
        module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        module = importlib.import_module(module_path)
        
        if not hasattr(module, function_name):
            return {
                "status": "error",
                "error": f"Function '{function_name}' not found in {tool_name}",
                "available_functions": [name for name, obj in inspect.getmembers(module, inspect.isfunction) 
                                      if not name.startswith('_')]
            }
        
        func = getattr(module, function_name)
        
        # Handle async and sync functions
        if asyncio.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            result = func(**kwargs)
            
        return {
            "status": "success",
            "tool": f"{category}.{tool_name}.{function_name}",
            "result": result
        }
        
    except Exception as e:
        return {
            "status": "error",
            "tool": f"{category}.{tool_name}.{function_name}",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def print_result(result: Dict[str, Any], format_type: str = "pretty") -> None:
    """Print results in a user-friendly format."""
    if format_type == "json":
        print(json.dumps(result, indent=2, default=str))
        return
    
    status = result.get("status", "unknown")
    
    if status == "success":
        print("✅ Success!")
        if "tool" in result:
            print(f"Tool: {result['tool']}")
        if "message" in result:
            print(f"Message: {result['message']}")
        if "dataset_id" in result:
            print(f"Dataset ID: {result['dataset_id']}")
        if "summary" in result:
            summary = result["summary"]
            print(f"Summary: {summary}")
        if "result" in result and result["result"] != result.get("message"):
            result_data = result["result"]
            if isinstance(result_data, dict):
                for key, value in result_data.items():
                    print(f"  {key}: {value}")
            else:
                print(f"Result: {result_data}")
    else:
        print("❌ Error!")
        if "tool" in result:
            print(f"Tool: {result['tool']}")
        if "error" in result:
            print(f"Error: {result['error']}")
        if "message" in result:
            print(f"Message: {result['message']}")
        if "available_functions" in result:
            print("Available functions:")
            for func in result["available_functions"]:
                print(f"  - {func}")


def print_available_categories(tools_by_category: Dict[str, Dict[str, Any]]) -> None:
    """Print all available tool categories."""
    print("Available MCP Tool Categories:")
    print("=" * 40)
    
    for category, tools in sorted(tools_by_category.items()):
        tool_count = len(tools)
        print(f"  {category:<25} ({tool_count} tools)")
    
    print(f"\nTotal: {len(tools_by_category)} categories")
    print("\nUse 'ipfs-datasets tools list <category>' to see tools in a specific category")


def print_tools_in_category(category: str, tools_by_category: Dict[str, Dict[str, Any]]) -> None:
    """Print all tools in a specific category."""
    if category not in tools_by_category:
        print(f"Error: Category '{category}' not found")
        return
        
    tools = tools_by_category[category]
    print(f"Tools in category '{category}':")
    print("=" * 50)
    
    for tool_name, tool_info in sorted(tools.items()):
        print(f"\n  {tool_name}:")
        for func_info in tool_info['functions']:
            print(f"    • {func_info['name']}{func_info['signature']}")
            if func_info['doc']:
                doc_preview = func_info['doc'].split('\n')[0][:80]
                print(f"      {doc_preview}...")


class ToolCommands:
    """Enhanced tool discovery and execution commands."""
    
    @staticmethod
    async def list_categories() -> Dict[str, Any]:
        """List all available tool categories."""
        try:
            tools_by_category = discover_mcp_tools()
            return {
                "status": "success",
                "categories": list(tools_by_category.keys()),
                "total_categories": len(tools_by_category),
                "tools_by_category": {
                    category: len(tools) for category, tools in tools_by_category.items()
                },
                "message": f"Found {len(tools_by_category)} tool categories"
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to list categories: {e}"}
    
    @staticmethod
    async def list_tools(category: Optional[str] = None) -> Dict[str, Any]:
        """List tools in a specific category or all tools."""
        try:
            tools_by_category = discover_mcp_tools()
            
            if category:
                if category not in tools_by_category:
                    return {
                        "status": "error", 
                        "error": f"Category '{category}' not found",
                        "available_categories": list(tools_by_category.keys())
                    }
                
                tools = tools_by_category[category]
                return {
                    "status": "success",
                    "category": category,
                    "tools": list(tools.keys()),
                    "total_tools": len(tools),
                    "tool_details": {
                        tool_name: [f['name'] for f in tool_info['functions']]
                        for tool_name, tool_info in tools.items()
                    },
                    "message": f"Found {len(tools)} tools in category '{category}'"
                }
            else:
                # Return all categories and their tools
                return {
                    "status": "success",
                    "all_categories": {
                        cat: list(tools.keys()) for cat, tools in tools_by_category.items()
                    },
                    "total_categories": len(tools_by_category),
                    "total_tools": sum(len(tools) for tools in tools_by_category.values()),
                    "message": "Listed all available tools"
                }
        except Exception as e:
            return {"status": "error", "error": f"Failed to list tools: {e}"}
    
    @staticmethod
    async def execute(category: str, tool: str, function: Optional[str] = None, 
                     args: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a tool with dynamic arguments."""
        try:
            tools_by_category = discover_mcp_tools()
            
            # Validate category and tool
            if category not in tools_by_category:
                return {
                    "status": "error",
                    "error": f"Category '{category}' not found",
                    "available_categories": list(tools_by_category.keys())
                }
                
            if tool not in tools_by_category[category]:
                return {
                    "status": "error",
                    "error": f"Tool '{tool}' not found in category '{category}'",
                    "available_tools": list(tools_by_category[category].keys())
                }
            
            # Determine function to call
            tool_info = tools_by_category[category][tool]
            available_functions = [f['name'] for f in tool_info['functions']]
            
            if function and function not in available_functions:
                return {
                    "status": "error",
                    "error": f"Function '{function}' not found in {tool}",
                    "available_functions": available_functions
                }
            
            function_name = function or (available_functions[0] if available_functions else None)
            if not function_name:
                return {
                    "status": "error",
                    "error": f"No callable functions found in {tool}"
                }
            
            # Convert CLI args to kwargs
            kwargs = convert_cli_args_to_kwargs(args or [])
            
            # Execute the tool
            return await execute_tool(category, tool, function_name, kwargs)
            
        except Exception as e:
            return {"status": "error", "error": f"Failed to execute tool: {e}"}


class DatasetCommands:
    """Dataset-related CLI commands."""
    
    @staticmethod
    async def load(source: str, format_type: Optional[str] = None, 
                   options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Load a dataset from a source."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools import load_dataset
            return await load_dataset(source=source, format=format_type, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import dataset tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to load dataset: {e}"}
    
    @staticmethod
    async def save(data: str, destination: str, format_type: Optional[str] = None,
                   options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Save a dataset to a destination."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools import save_dataset
            return await save_dataset(data=data, destination=destination, 
                                    format=format_type, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import dataset tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to save dataset: {e}"}
    
    @staticmethod
    async def process(source: str, operations: List[Dict[str, Any]], 
                     destination: Optional[str] = None) -> Dict[str, Any]:
        """Process a dataset with specified operations."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools import process_dataset
            return await process_dataset(source=source, operations=operations, 
                                       destination=destination)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import dataset tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to process dataset: {e}"}
    
    @staticmethod
    async def convert(source: str, target_format: str, 
                     destination: Optional[str] = None) -> Dict[str, Any]:
        """Convert a dataset to a different format."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools import convert_dataset_format
            return await convert_dataset_format(source=source, target_format=target_format,
                                              destination=destination)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import dataset tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to convert dataset: {e}"}


class IPFSCommands:
    """IPFS-related CLI commands."""
    
    @staticmethod
    async def get(hash_value: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get data from IPFS by hash."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools import get_from_ipfs
            return await get_from_ipfs(hash=hash_value, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import IPFS tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to get from IPFS: {e}"}
    
    @staticmethod
    async def pin(data: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Pin data to IPFS."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools import pin_to_ipfs
            return await pin_to_ipfs(data=data, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import IPFS tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to pin to IPFS: {e}"}


class VectorCommands:
    """Vector-related CLI commands."""
    
    @staticmethod
    async def create(data: Union[str, List[str]], index_name: Optional[str] = None,
                    options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a vector index from data."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools import create_vector_index
            return await create_vector_index(data=data, index_name=index_name, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import vector tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to create vector index: {e}"}
    
    @staticmethod
    async def search(query: str, index_name: Optional[str] = None,
                    limit: int = 10, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Search a vector index."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools import search_vector_index
            return await search_vector_index(query=query, index_name=index_name, 
                                            limit=limit, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import vector tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to search vector index: {e}"}


class GraphCommands:
    """Graph/Knowledge graph related CLI commands."""
    
    @staticmethod
    async def query(query: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Query the knowledge graph."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.graph_tools import query_knowledge_graph
            return await query_knowledge_graph(query=query, options=options)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import graph tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to query knowledge graph: {e}"}


class CLICommands:
    """CLI/Command execution related commands."""
    
    @staticmethod
    async def execute(command: str, args: Optional[List[str]] = None,
                     timeout: int = 60) -> Dict[str, Any]:
        """Execute a command through the CLI interface."""
        setup_sys_path()
        try:
            from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command
            return await execute_command(command=command, args=args, timeout_seconds=timeout)
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import CLI tools: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to execute command: {e}"}


class MCPCommands:
    """MCP server and dashboard management commands."""
    
    @staticmethod
    def _get_pid_file_path(service: str) -> Path:
        """Get the PID file path for a service."""
        return Path.home() / ".ipfs_datasets" / f"{service}.pid"
    
    @staticmethod
    def _ensure_pid_dir():
        """Ensure the PID directory exists."""
        pid_dir = Path.home() / ".ipfs_datasets"
        pid_dir.mkdir(exist_ok=True)
        return pid_dir
    
    @staticmethod
    def _is_process_running(pid: int) -> bool:
        """Check if a process with given PID is running."""
        if PSUTIL_AVAILABLE:
            try:
                return psutil.pid_exists(pid)
            except:
                pass
        
        # Fallback to os.kill for systems without psutil
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    
    @staticmethod
    def _kill_process(pid: int, service_name: str) -> bool:
        """Safely kill a process."""
        try:
            if MCPCommands._is_process_running(pid):
                os.kill(pid, signal.SIGTERM)
                
                # Wait up to 10 seconds for graceful shutdown
                for _ in range(100):
                    if not MCPCommands._is_process_running(pid):
                        return True
                    time.sleep(0.1)
                
                # Force kill if still running
                if MCPCommands._is_process_running(pid):
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.5)
                    return not MCPCommands._is_process_running(pid)
                return True
            return False
        except Exception as e:
            print(f"Error killing {service_name} process {pid}: {e}")
            return False
    
    @staticmethod
    async def start_server(host: str = "127.0.0.1", port: int = 8000, 
                          background: bool = True) -> Dict[str, Any]:
        """Start the MCP server."""
        try:
            MCPCommands._ensure_pid_dir()
            pid_file = MCPCommands._get_pid_file_path("mcp_server")
            
            # Check if already running
            if pid_file.exists():
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                if MCPCommands._is_process_running(pid):
                    return {
                        "status": "success",
                        "message": f"MCP server already running (PID: {pid})",
                        "pid": pid,
                        "endpoint": f"http://{host}:{port}"
                    }
                else:
                    # Remove stale PID file
                    pid_file.unlink()
            
            # Check dependencies first
            setup_sys_path()
            try:
                # Try basic import test
                from ipfs_datasets_py.mcp_server.simple_server import SimpleIPFSDatasetsMCPServer
            except ImportError as e:
                return {
                    "status": "error", 
                    "error": f"MCP server dependencies not available: {e}. Install required packages first."
                }
            
            # Start the server
            current_dir = Path(__file__).parent
            
            cmd = [
                sys.executable, "-m", "ipfs_datasets_py.mcp_server",
                "--host", host,
                "--port", str(port),
                "--http"
            ]
            
            if background:
                # Start in background
                env = os.environ.copy()
                env['PYTHONPATH'] = str(current_dir)
                
                process = subprocess.Popen(
                    cmd,
                    cwd=current_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True
                )
                
                # Write PID file
                with open(pid_file, 'w') as f:
                    f.write(str(process.pid))
                
                # Give it a moment to start
                time.sleep(2)
                
                if process.poll() is None:  # Still running
                    return {
                        "status": "success",
                        "message": f"MCP server started successfully",
                        "pid": process.pid,
                        "endpoint": f"http://{host}:{port}"
                    }
                else:
                    # Process died, get error output
                    stdout, stderr = process.communicate()
                    pid_file.unlink(missing_ok=True)
                    return {
                        "status": "error",
                        "error": f"MCP server failed to start: {stderr.decode()}"
                    }
            else:
                # Run in foreground (for debugging)
                return {
                    "status": "success",
                    "message": f"Starting MCP server in foreground on {host}:{port}",
                    "command": " ".join(cmd)
                }
                
        except Exception as e:
            return {"status": "error", "error": f"Failed to start MCP server: {e}"}
    
    @staticmethod
    async def start_dashboard(host: str = "0.0.0.0", port: int = 8080,
                             background: bool = True) -> Dict[str, Any]:
        """Start the MCP dashboard."""
        try:
            MCPCommands._ensure_pid_dir()
            pid_file = MCPCommands._get_pid_file_path("mcp_dashboard")
            
            # Check if already running
            if pid_file.exists():
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                if MCPCommands._is_process_running(pid):
                    return {
                        "status": "success",
                        "message": f"MCP dashboard already running (PID: {pid})",
                        "pid": pid,
                        "url": f"http://{host}:{port}/mcp"
                    }
                else:
                    # Remove stale PID file
                    pid_file.unlink()
            
            # Check dependencies first
            setup_sys_path()
            try:
                # Try basic import test
                from ipfs_datasets_py.mcp_dashboard import MCPDashboard
            except ImportError as e:
                return {
                    "status": "error", 
                    "error": f"MCP dashboard dependencies not available: {e}. Install Flask and other required packages first."
                }
            
            # Start the dashboard
            current_dir = Path(__file__).parent
            
            cmd = [
                sys.executable, "-c", 
                "from ipfs_datasets_py.mcp_dashboard import *; import os; os.environ.get('MCP_DASHBOARD_HOST', '0.0.0.0') or exec(open(__file__).read())",
                str(current_dir / "ipfs_datasets_py" / "mcp_dashboard.py")
            ]
            
            # Simpler approach: run the module directly
            cmd = [
                sys.executable, str(current_dir / "ipfs_datasets_py" / "mcp_dashboard.py")
            ]
            
            if background:
                # Start in background
                env = os.environ.copy()
                env['PYTHONPATH'] = str(current_dir)
                env['MCP_DASHBOARD_HOST'] = host
                env['MCP_DASHBOARD_PORT'] = str(port)
                
                process = subprocess.Popen(
                    cmd,
                    cwd=current_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True
                )
                
                # Write PID file
                with open(pid_file, 'w') as f:
                    f.write(str(process.pid))
                
                # Give it a moment to start
                time.sleep(3)
                
                if process.poll() is None:  # Still running
                    return {
                        "status": "success",
                        "message": f"MCP dashboard started successfully",
                        "pid": process.pid,
                        "url": f"http://{host}:{port}/mcp"
                    }
                else:
                    # Process died, get error output
                    stdout, stderr = process.communicate()
                    pid_file.unlink(missing_ok=True)
                    return {
                        "status": "error",
                        "error": f"MCP dashboard failed to start: {stderr.decode()}"
                    }
            else:
                # Run in foreground (for debugging)
                return {
                    "status": "success",
                    "message": f"Starting MCP dashboard in foreground on {host}:{port}",
                    "command": " ".join(cmd)
                }
                
        except Exception as e:
            return {"status": "error", "error": f"Failed to start MCP dashboard: {e}"}
    
    @staticmethod
    async def stop_server() -> Dict[str, Any]:
        """Stop the MCP server."""
        try:
            pid_file = MCPCommands._get_pid_file_path("mcp_server")
            
            if not pid_file.exists():
                return {
                    "status": "success",
                    "message": "MCP server is not running"
                }
            
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            if MCPCommands._kill_process(pid, "MCP server"):
                pid_file.unlink()
                return {
                    "status": "success",
                    "message": f"MCP server stopped (PID: {pid})"
                }
            else:
                return {
                    "status": "error",
                    "error": f"Failed to stop MCP server (PID: {pid})"
                }
                
        except Exception as e:
            return {"status": "error", "error": f"Failed to stop MCP server: {e}"}
    
    @staticmethod
    async def stop_dashboard() -> Dict[str, Any]:
        """Stop the MCP dashboard."""
        try:
            pid_file = MCPCommands._get_pid_file_path("mcp_dashboard")
            
            if not pid_file.exists():
                return {
                    "status": "success",
                    "message": "MCP dashboard is not running"
                }
            
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            if MCPCommands._kill_process(pid, "MCP dashboard"):
                pid_file.unlink()
                return {
                    "status": "success",
                    "message": f"MCP dashboard stopped (PID: {pid})"
                }
            else:
                return {
                    "status": "error",
                    "error": f"Failed to stop MCP dashboard (PID: {pid})"
                }
                
        except Exception as e:
            return {"status": "error", "error": f"Failed to stop MCP dashboard: {e}"}
    
    @staticmethod
    async def status() -> Dict[str, Any]:
        """Get MCP services status."""
        try:
            MCPCommands._ensure_pid_dir()
            
            services = {}
            
            # Check server status
            server_pid_file = MCPCommands._get_pid_file_path("mcp_server")
            if server_pid_file.exists():
                with open(server_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                if MCPCommands._is_process_running(pid):
                    services["mcp_server"] = {
                        "status": "running",
                        "pid": pid,
                        "endpoint": "http://127.0.0.1:8000"
                    }
                else:
                    services["mcp_server"] = {"status": "stopped (stale PID file)"}
                    server_pid_file.unlink()
            else:
                services["mcp_server"] = {"status": "stopped"}
            
            # Check dashboard status
            dashboard_pid_file = MCPCommands._get_pid_file_path("mcp_dashboard")
            if dashboard_pid_file.exists():
                with open(dashboard_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                if MCPCommands._is_process_running(pid):
                    services["mcp_dashboard"] = {
                        "status": "running",
                        "pid": pid,
                        "url": "http://0.0.0.0:8080/mcp"
                    }
                else:
                    services["mcp_dashboard"] = {"status": "stopped (stale PID file)"}
                    dashboard_pid_file.unlink()
            else:
                services["mcp_dashboard"] = {"status": "stopped"}
            
            return {
                "status": "success",
                "services": services,
                "message": "MCP services status retrieved"
            }
            
        except Exception as e:
            return {"status": "error", "error": f"Failed to get MCP status: {e}"}
    
    @staticmethod
    async def start(server_host: str = "127.0.0.1", server_port: int = 8000,
                   dashboard_host: str = "0.0.0.0", dashboard_port: int = 8080) -> Dict[str, Any]:
        """Start both MCP server and dashboard."""
        results = {}
        
        # Start server first
        server_result = await MCPCommands.start_server(server_host, server_port)
        results["server"] = server_result
        
        # Start dashboard
        dashboard_result = await MCPCommands.start_dashboard(dashboard_host, dashboard_port)
        results["dashboard"] = dashboard_result
        
        # Overall success if both succeed
        success = (server_result.get("status") == "success" and 
                  dashboard_result.get("status") == "success")
        
        return {
            "status": "success" if success else "partial",
            "results": results,
            "message": "MCP services started" if success else "Some MCP services failed to start"
        }
    
    @staticmethod
    async def stop() -> Dict[str, Any]:
        """Stop both MCP server and dashboard."""
        results = {}
        
        # Stop dashboard first
        dashboard_result = await MCPCommands.stop_dashboard()
        results["dashboard"] = dashboard_result
        
        # Stop server
        server_result = await MCPCommands.stop_server()
        results["server"] = server_result
        
        return {
            "status": "success",
            "results": results,
            "message": "MCP services stopped"
        }


class InfoCommands:
    """Information and status commands."""
    
    @staticmethod
    async def status() -> Dict[str, Any]:
        """Get system status and available tools."""
        setup_sys_path()
        try:
            # Basic system info
            import platform
            import sys
            from pathlib import Path
            
            # Get MCP tools status using enhanced discovery
            tools_by_category = discover_mcp_tools()
            total_tools = sum(len(tools) for tools in tools_by_category.values())
            
            # Get MCP services status
            mcp_status = await MCPCommands.status()
            
            return {
                "status": "success",
                "system": {
                    "platform": platform.platform(),
                    "python_version": sys.version,
                    "ipfs_datasets_py_path": str(Path(__file__).parent)
                },
                "mcp_tools": {
                    "tool_categories": sorted(tools_by_category.keys()),
                    "total_categories": len(tools_by_category),
                    "total_tools": total_tools,
                    "tools_by_category": {
                        category: len(tools) for category, tools in tools_by_category.items()
                    }
                },
                "mcp_services": mcp_status.get("services", {}),
                "message": f"IPFS Datasets CLI is operational with {len(tools_by_category)} tool categories and {total_tools} tools"
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to get status: {e}"}
    
    @staticmethod
    async def list_tools() -> Dict[str, Any]:
        """List all available tool categories and their functions."""
        return await ToolCommands.list_tools()


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets-cli",
        description="Command line interface for IPFS Datasets Python tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # System information
  ipfs-datasets-cli info status
  ipfs-datasets-cli info list-tools
  
  # Enhanced tool discovery and execution
  ipfs-datasets-cli tools categories
  ipfs-datasets-cli tools list dataset_tools
  ipfs-datasets-cli tools execute dataset_tools load_dataset --source "test" --format json
  ipfs-datasets-cli tools execute vector_tools create_vector_index --dimension 768 --metric cosine
  
  # MCP server and dashboard management
  ipfs-datasets-cli mcp start
  ipfs-datasets-cli mcp stop
  ipfs-datasets-cli mcp status
  ipfs-datasets-cli mcp start-server --host 127.0.0.1 --port 8000
  ipfs-datasets-cli mcp start-dashboard --host 0.0.0.0 --port 8080
  ipfs-datasets-cli mcp stop-server
  ipfs-datasets-cli mcp stop-dashboard
  
  # CLI operations
  ipfs-datasets-cli cli execute echo "Hello World"
  
  # Dataset operations
  ipfs-datasets-cli dataset load squad
  ipfs-datasets-cli dataset load /path/to/data.json --format json
  ipfs-datasets-cli dataset save my_data /path/to/output.csv --format csv
  ipfs-datasets-cli dataset convert /path/to/data.json csv /path/to/output.csv
  
  # IPFS operations  
  ipfs-datasets-cli ipfs get QmHash123...
  ipfs-datasets-cli ipfs pin "Hello, World!"
  
  # Vector operations
  ipfs-datasets-cli vector create /path/to/documents.txt --index-name my_index
  ipfs-datasets-cli vector search "search query" --index-name my_index --limit 5
  
  # Graph operations
  ipfs-datasets-cli graph query "SPARQL query here"
        """
    )
    
    parser.add_argument("--format", choices=["pretty", "json"], default="pretty",
                       help="Output format (default: pretty)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose output")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Enhanced Tools commands
    tools_parser = subparsers.add_parser("tools", help="Enhanced tool discovery and execution")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_action")
    
    # Tools categories
    tools_subparsers.add_parser("categories", help="List all available tool categories")
    
    # Tools list
    list_tools_parser = tools_subparsers.add_parser("list", help="List tools in a category")
    list_tools_parser.add_argument("category", nargs="?", help="Category to list tools for")
    
    # Tools execute
    execute_tools_parser = tools_subparsers.add_parser("execute", help="Execute a tool dynamically")
    execute_tools_parser.add_argument("category", help="Tool category")
    execute_tools_parser.add_argument("tool", help="Tool name")
    execute_tools_parser.add_argument("function", nargs="?", help="Function name (optional)")
    execute_tools_parser.add_argument("args", nargs="*", help="Tool arguments (--key value format)")
    
    # Info commands
    info_parser = subparsers.add_parser("info", help="Information and status")
    info_subparsers = info_parser.add_subparsers(dest="info_action")
    
    # Info status
    info_subparsers.add_parser("status", help="Show system status")
    
    # Info list-tools
    info_subparsers.add_parser("list-tools", help="List all available tools")
    
    # MCP commands
    mcp_parser = subparsers.add_parser("mcp", help="MCP server and dashboard management")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_action")
    
    # MCP start
    start_parser = mcp_subparsers.add_parser("start", help="Start MCP server and dashboard")
    start_parser.add_argument("--server-host", default="127.0.0.1", help="MCP server host (default: 127.0.0.1)")
    start_parser.add_argument("--server-port", type=int, default=8000, help="MCP server port (default: 8000)")
    start_parser.add_argument("--dashboard-host", default="0.0.0.0", help="Dashboard host (default: 0.0.0.0)")
    start_parser.add_argument("--dashboard-port", type=int, default=8080, help="Dashboard port (default: 8080)")
    
    # MCP stop
    mcp_subparsers.add_parser("stop", help="Stop MCP server and dashboard")
    
    # MCP status
    mcp_subparsers.add_parser("status", help="Show MCP services status")
    
    # MCP start-server
    start_server_parser = mcp_subparsers.add_parser("start-server", help="Start MCP server only")
    start_server_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    start_server_parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    start_server_parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    
    # MCP start-dashboard
    start_dashboard_parser = mcp_subparsers.add_parser("start-dashboard", help="Start MCP dashboard only")
    start_dashboard_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    start_dashboard_parser.add_argument("--port", type=int, default=8080, help="Port to bind to (default: 8080)")
    start_dashboard_parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    
    # MCP stop-server
    mcp_subparsers.add_parser("stop-server", help="Stop MCP server only")
    
    # MCP stop-dashboard
    mcp_subparsers.add_parser("stop-dashboard", help="Stop MCP dashboard only")
    
    # CLI commands
    cli_parser = subparsers.add_parser("cli", help="Command execution")
    cli_subparsers = cli_parser.add_subparsers(dest="cli_action")
    
    # CLI execute
    execute_parser = cli_subparsers.add_parser("execute", help="Execute a command")
    execute_parser.add_argument("exec_command", help="Command to execute")
    execute_parser.add_argument("exec_args", nargs="*", help="Command arguments")
    execute_parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    
    # Dataset commands
    dataset_parser = subparsers.add_parser("dataset", help="Dataset operations")
    dataset_subparsers = dataset_parser.add_subparsers(dest="dataset_action")
    
    # Dataset load
    load_parser = dataset_subparsers.add_parser("load", help="Load a dataset")
    load_parser.add_argument("source", help="Dataset source (HF name, file path, or URL)")
    load_parser.add_argument("--format", help="Dataset format (json, csv, parquet, etc.)")
    load_parser.add_argument("--split", help="Dataset split to load")
    load_parser.add_argument("--streaming", action="store_true", help="Enable streaming mode")
    
    # Dataset save
    save_parser = dataset_subparsers.add_parser("save", help="Save a dataset")
    save_parser.add_argument("data", help="Data to save (file path or dataset ID)")
    save_parser.add_argument("destination", help="Destination path")
    save_parser.add_argument("--format", help="Output format")
    
    # Dataset convert
    convert_parser = dataset_subparsers.add_parser("convert", help="Convert dataset format")
    convert_parser.add_argument("source", help="Source dataset path")
    convert_parser.add_argument("target_format", help="Target format (json, csv, parquet)")
    convert_parser.add_argument("destination", nargs="?", help="Destination path")
    
    # IPFS commands
    ipfs_parser = subparsers.add_parser("ipfs", help="IPFS operations")
    ipfs_subparsers = ipfs_parser.add_subparsers(dest="ipfs_action")
    
    # IPFS get
    get_parser = ipfs_subparsers.add_parser("get", help="Get data from IPFS")
    get_parser.add_argument("hash", help="IPFS hash to retrieve")
    get_parser.add_argument("--output", "-o", help="Output file path")
    
    # IPFS pin
    pin_parser = ipfs_subparsers.add_parser("pin", help="Pin data to IPFS")
    pin_parser.add_argument("data", help="Data to pin (file path or string)")
    pin_parser.add_argument("--recursive", action="store_true", help="Pin recursively")
    
    # Vector commands
    vector_parser = subparsers.add_parser("vector", help="Vector operations")
    vector_subparsers = vector_parser.add_subparsers(dest="vector_action")
    
    # Vector create
    create_vector_parser = vector_subparsers.add_parser("create", help="Create vector index")
    create_vector_parser.add_argument("data", help="Data to index (file path or dataset ID)")
    create_vector_parser.add_argument("--index-name", help="Name for the vector index")
    create_vector_parser.add_argument("--embedding-model", help="Embedding model to use")
    
    # Vector search
    search_parser = vector_subparsers.add_parser("search", help="Search vector index")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--index-name", help="Vector index to search")
    search_parser.add_argument("--limit", type=int, default=10, help="Number of results")
    
    # Graph commands
    graph_parser = subparsers.add_parser("graph", help="Knowledge graph operations")
    graph_subparsers = graph_parser.add_subparsers(dest="graph_action")
    
    # Graph query
    query_parser = graph_subparsers.add_parser("query", help="Query knowledge graph")
    query_parser.add_argument("query", help="SPARQL or natural language query")
    query_parser.add_argument("--format", help="Query format (sparql, natural)")
    
    return parser


async def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if hasattr(args, 'verbose') and args.verbose:
        print(f"Running command: {' '.join(sys.argv[1:])}")
    
    try:
        result = None
        
        if args.command == "tools":
            if args.tools_action == "categories":
                result = await ToolCommands.list_categories()
                # Use pretty printing for categories
                if result.get("status") == "success" and args.format == "pretty":
                    tools_by_category = discover_mcp_tools()
                    print_available_categories(tools_by_category)
                    return
                    
            elif args.tools_action == "list":
                result = await ToolCommands.list_tools(args.category)
                # Use pretty printing for tools list
                if result.get("status") == "success" and args.format == "pretty" and args.category:
                    tools_by_category = discover_mcp_tools()
                    print_tools_in_category(args.category, tools_by_category)
                    return
                    
            elif args.tools_action == "execute":
                result = await ToolCommands.execute(
                    args.category, args.tool, args.function, args.args
                )
            else:
                parser.error("Invalid tools action")
        
        elif args.command == "info":
            if args.info_action == "status":
                result = await InfoCommands.status()
            elif args.info_action == "list-tools":
                result = await InfoCommands.list_tools()
            else:
                parser.error("Invalid info action")
        
        elif args.command == "cli":
            if args.cli_action == "execute":
                result = await CLICommands.execute(args.exec_command, args.exec_args, args.timeout)
            else:
                parser.error("Invalid CLI action")
        
        elif args.command == "mcp":
            if args.mcp_action == "start":
                result = await MCPCommands.start(
                    args.server_host, args.server_port,
                    args.dashboard_host, args.dashboard_port
                )
            elif args.mcp_action == "stop":
                result = await MCPCommands.stop()
            elif args.mcp_action == "status":
                result = await MCPCommands.status()
            elif args.mcp_action == "start-server":
                result = await MCPCommands.start_server(
                    args.host, args.port, not args.foreground
                )
            elif args.mcp_action == "start-dashboard":
                result = await MCPCommands.start_dashboard(
                    args.host, args.port, not args.foreground
                )
            elif args.mcp_action == "stop-server":
                result = await MCPCommands.stop_server()
            elif args.mcp_action == "stop-dashboard":
                result = await MCPCommands.stop_dashboard()
            else:
                parser.error("Invalid MCP action")
        
        elif args.command == "dataset":
            if args.dataset_action == "load":
                options = {}
                if args.split:
                    options["split"] = args.split
                if args.streaming:
                    options["streaming"] = True
                result = await DatasetCommands.load(args.source, args.format, options)
            
            elif args.dataset_action == "save":
                result = await DatasetCommands.save(args.data, args.destination, args.format)
            
            elif args.dataset_action == "convert":
                result = await DatasetCommands.convert(args.source, args.target_format, args.destination)
            
            else:
                parser.error("Invalid dataset action")
        
        elif args.command == "ipfs":
            if args.ipfs_action == "get":
                options = {}
                if args.output:
                    options["output"] = args.output
                result = await IPFSCommands.get(args.hash, options)
            
            elif args.ipfs_action == "pin":
                options = {}
                if args.recursive:
                    options["recursive"] = True
                result = await IPFSCommands.pin(args.data, options)
            
            else:
                parser.error("Invalid IPFS action")
        
        elif args.command == "vector":
            if args.vector_action == "create":
                options = {}
                if args.embedding_model:
                    options["embedding_model"] = args.embedding_model
                result = await VectorCommands.create(args.data, args.index_name, options)
            
            elif args.vector_action == "search":
                options = {}
                result = await VectorCommands.search(args.query, args.index_name, args.limit, options)
            
            else:
                parser.error("Invalid vector action")
        
        elif args.command == "graph":
            if args.graph_action == "query":
                options = {}
                if args.format:
                    options["format"] = args.format
                result = await GraphCommands.query(args.query, options)
            
            else:
                parser.error("Invalid graph action")
        
        else:
            parser.print_help()
            return
        
        if result:
            print_result(result, args.format)
        
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        if args.verbose:
            traceback.print_exc()
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())