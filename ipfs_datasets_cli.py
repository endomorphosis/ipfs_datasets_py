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
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import traceback


def setup_sys_path():
    """Add the package to sys.path if needed."""
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))


def print_result(result: Dict[str, Any], format_type: str = "pretty") -> None:
    """Print results in a user-friendly format."""
    if format_type == "json":
        print(json.dumps(result, indent=2))
        return
    
    if result.get("status") == "success":
        print("✅ Success!")
        if "message" in result:
            print(f"Message: {result['message']}")
        if "dataset_id" in result:
            print(f"Dataset ID: {result['dataset_id']}")
        if "summary" in result:
            summary = result["summary"]
            print(f"Summary: {summary}")
        if "result" in result and result["result"] != result.get("message"):
            print(f"Result: {result['result']}")
    else:
        print("❌ Error!")
        if "error" in result:
            print(f"Error: {result['error']}")
        if "message" in result:
            print(f"Message: {result['message']}")


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
            
            # Try to get MCP tools status
            tool_categories = []
            tools_dir = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
            if tools_dir.exists():
                for item in tools_dir.iterdir():
                    if item.is_dir() and not item.name.startswith('_'):
                        tool_categories.append(item.name)
            
            return {
                "status": "success",
                "system": {
                    "platform": platform.platform(),
                    "python_version": sys.version,
                    "ipfs_datasets_py_path": str(Path(__file__).parent)
                },
                "mcp_tools": {
                    "tool_categories": sorted(tool_categories),
                    "total_categories": len(tool_categories)
                },
                "message": "IPFS Datasets CLI is operational"
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to get status: {e}"}
    
    @staticmethod
    async def list_tools() -> Dict[str, Any]:
        """List all available tool categories and their functions."""
        setup_sys_path()
        try:
            from pathlib import Path
            
            tools_info = {}
            tools_dir = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
            
            if not tools_dir.exists():
                return {"status": "error", "error": "MCP tools directory not found"}
            
            for category_dir in sorted(tools_dir.iterdir()):
                if category_dir.is_dir() and not category_dir.name.startswith('_'):
                    category_name = category_dir.name
                    tools = []
                    
                    # Look for Python files that might be tools
                    for tool_file in category_dir.glob("*.py"):
                        if not tool_file.name.startswith('_') and tool_file.name != "__init__.py":
                            tool_name = tool_file.stem
                            tools.append(tool_name)
                    
                    if tools:
                        tools_info[category_name] = sorted(tools)
            
            return {
                "status": "success",
                "tool_categories": tools_info,
                "total_categories": len(tools_info),
                "message": f"Found {len(tools_info)} tool categories"
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to list tools: {e}"}


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
    
    # Info commands
    info_parser = subparsers.add_parser("info", help="Information and status")
    info_subparsers = info_parser.add_subparsers(dest="info_action")
    
    # Info status
    info_subparsers.add_parser("status", help="Show system status")
    
    # Info list-tools
    info_subparsers.add_parser("list-tools", help="List all available tools")
    
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
        
        if args.command == "info":
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