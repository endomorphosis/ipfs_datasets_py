#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrated IPFS Datasets CLI with Full MCP and Package Integration

This CLI connects to the same common code that the MCP server uses, enabling:
- MCP server management (start, stop, status)
- Direct MCP tool execution via CLI
- Full access to ipfs_datasets_py package features
- Shared codebase with the dashboard and MCP server

Features:
- Lightweight startup for basic commands (help/version)  
- Full integration with MCP tools and ipfs_datasets_py package
- Common configuration and initialization
- Unified tool execution across CLI and MCP server
"""
import sys
from pathlib import Path


def show_help():
    """Show CLI help without importing anything heavy."""
    help_text = """
IPFS Datasets CLI Tool - Integrated with MCP Server

Usage:
    ipfs-datasets [command] [subcommand] [options]
    ipfs-datasets --help
    ipfs-datasets --version

Core Commands:
    info         System information and status
      status     Show system status and health
      version    Show version information
      config     Show configuration details
      
    mcp          MCP server management (integrated)
      start      Start MCP server with full integration
      stop       Stop MCP server
      status     Show MCP server status
      tools      List available MCP tools
      
    tools        Execute MCP tools directly
      list       List all available tools
      categories List tool categories  
      execute    Execute MCP tool: ipfs-datasets tools execute <category> <tool> [args]
      
    dataset      Dataset operations (ipfs_datasets_py package)
      load       Load and process dataset
      convert    Convert dataset formats
      analyze    Analyze dataset statistics
      
    deontic      Temporal deontic logic RAG system
      check      Check document consistency
      query      Query legal theorems
      bulk       Bulk process caselaw
      
    ipfs         IPFS operations
      pin        Pin data to IPFS
      get        Get data from IPFS
      status     Show IPFS node status
      
    vector       Vector operations  
      create     Create embeddings
      search     Search vectors
      index      Manage vector indexes

Examples:
    # Basic system info
    ipfs-datasets info status
    
    # Start integrated MCP server
    ipfs-datasets mcp start
    
    # Execute temporal deontic logic tools
    ipfs-datasets tools execute temporal_deontic_logic check_document_consistency --document_text "..."
    
    # Load and analyze dataset
    ipfs-datasets dataset load /path/to/data.json
    
    # Check legal document consistency
    ipfs-datasets deontic check --document "Employee may share confidential info" --jurisdiction Federal

Options:
    --help, -h   Show this help message
    --version    Show version information
    --json       Output in JSON format
    --verbose    Enable verbose logging
    --config     Specify config file path
"""
    print(help_text.strip())


def show_version():
    """Show version without importing anything heavy."""
    print("ipfs-datasets CLI v1.2.0")
    print("Integrated with MCP Server and ipfs_datasets_py package")


def main():
    """Main CLI entry point with integrated MCP and package functionality."""
    args = sys.argv[1:]
    
    # Handle basic commands immediately without heavy imports
    if not args or args[0] in ['-h', '--help', 'help']:
        show_help()
        return
        
    if args[0] in ['--version', 'version']:
        show_version()
        return
    
    # For all other commands, use integrated functionality
    execute_integrated_command(args)


def execute_integrated_command(args):
    """Execute commands using integrated MCP server and ipfs_datasets_py functionality."""
    try:
        # Import required modules for integrated functionality
        import anyio
        import json
        import logging
        import os
        import importlib
        from datetime import datetime
        from pathlib import Path
        
        # Configure logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        
        # Import MCP and package components
        from ipfs_datasets_py.mcp_server.simple_server import SimpleIPFSDatasetsMCPServer
        from ipfs_datasets_py.mcp_tools.tool_registry import ToolRegistry
        from ipfs_datasets_py.mcp_dashboard import MCPDashboard
        
        # Initialize integrated CLI handler
        cli_handler = IntegratedCLIHandler()
        
        # Parse and execute command
        result = anyio.run(cli_handler.execute_command(args))
        
        # Output result
        if isinstance(result, dict) and '--json' in args:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, dict):
                print_pretty_result(result)
            else:
                print(result)
                
    except ImportError as e:
        print(f"Error: Missing dependencies for advanced functionality: {e}")
        print("Try: pip install -e . to install full dependencies")
        sys.exit(1)
    except Exception as e:
        print(f"Error executing command: {e}")
        if '--verbose' in args:
            import traceback
            traceback.print_exc()
        sys.exit(1)


class IntegratedCLIHandler:
    """Handler for integrated CLI functionality with MCP server and ipfs_datasets_py package."""
    
    def __init__(self):
        self.mcp_server = None
        self.tool_registry = None
        self.dashboard = None
        
    async def execute_command(self, args):
        """Execute command with full integration."""
        command = args[0] if args else 'help'
        subcommand = args[1] if len(args) > 1 else None
        
        if command == 'info':
            return await self.handle_info_command(subcommand, args[2:] if len(args) > 2 else [])
        elif command == 'mcp':
            return await self.handle_mcp_command(subcommand, args[2:] if len(args) > 2 else [])
        elif command == 'tools':
            return await self.handle_tools_command(subcommand, args[2:] if len(args) > 2 else [])
        elif command == 'deontic':
            return await self.handle_deontic_command(subcommand, args[2:] if len(args) > 2 else [])
        elif command == 'dataset':
            return await self.handle_dataset_command(subcommand, args[2:] if len(args) > 2 else [])
        elif command == 'ipfs':
            return await self.handle_ipfs_command(subcommand, args[2:] if len(args) > 2 else [])
        elif command == 'vector':
            return await self.handle_vector_command(subcommand, args[2:] if len(args) > 2 else [])
        else:
            return f"Unknown command: {command}. Use --help for available commands."
    
    async def handle_info_command(self, subcommand, args):
        """Handle info commands."""
        if subcommand == 'status':
            return await self.get_system_status()
        elif subcommand == 'config':
            return await self.get_config_info()
        else:
            return "Available info commands: status, config"
    
    async def handle_mcp_command(self, subcommand, args):
        """Handle MCP server commands with full integration."""
        if subcommand == 'start':
            return await self.start_mcp_server()
        elif subcommand == 'stop':
            return await self.stop_mcp_server()
        elif subcommand == 'status':
            return await self.get_mcp_status()
        elif subcommand == 'tools':
            return await self.list_mcp_tools()
        else:
            return "Available MCP commands: start, stop, status, tools"
    
    async def handle_tools_command(self, subcommand, args):
        """Handle direct MCP tool execution."""
        if subcommand == 'list':
            return await self.list_all_tools()
        elif subcommand == 'categories':
            return await self.list_tool_categories()
        elif subcommand == 'execute':
            if len(args) < 2:
                return "Usage: ipfs-datasets tools execute <category> <tool> [parameters]"
            category = args[0]
            tool_name = args[1]
            parameters = self.parse_tool_parameters(args[2:])
            return await self.execute_mcp_tool(category, tool_name, parameters)
        else:
            return "Available tool commands: list, categories, execute"
    
    async def handle_deontic_command(self, subcommand, args):
        """Handle temporal deontic logic RAG system commands."""
        if subcommand == 'check':
            return await self.check_document_consistency(args)
        elif subcommand == 'query':
            return await self.query_theorems(args)
        elif subcommand == 'bulk':
            return await self.bulk_process_caselaw(args)
        else:
            return "Available deontic commands: check, query, bulk"
    
    async def handle_dataset_command(self, subcommand, args):
        """Handle dataset operations using ipfs_datasets_py package."""
        if subcommand == 'load':
            return await self.load_dataset(args)
        elif subcommand == 'convert':
            return await self.convert_dataset(args)
        elif subcommand == 'analyze':
            return await self.analyze_dataset(args)
        else:
            return "Available dataset commands: load, convert, analyze"
    
    async def handle_ipfs_command(self, subcommand, args):
        """Handle IPFS operations."""
        if subcommand == 'pin':
            return await self.pin_to_ipfs(args)
        elif subcommand == 'get':
            return await self.get_from_ipfs(args)
        elif subcommand == 'status':
            return await self.get_ipfs_status()
        else:
            return "Available IPFS commands: pin, get, status"
    
    async def handle_vector_command(self, subcommand, args):
        """Handle vector operations."""
        if subcommand == 'create':
            return await self.create_embeddings(args)
        elif subcommand == 'search':
            return await self.search_vectors(args)
        elif subcommand == 'index':
            return await self.manage_vector_index(args)
        else:
            return "Available vector commands: create, search, index"
    
    async def get_system_status(self):
        """Get comprehensive system status."""
        try:
            from ipfs_datasets_py import __version__ as pkg_version
        except:
            pkg_version = "unknown"
            
        status = {
            "cli_version": "1.2.0",
            "package_version": pkg_version,
            "timestamp": datetime.now().isoformat(),
            "python_version": sys.version,
            "mcp_server_running": await self.is_mcp_server_running(),
            "available_tools": await self.count_available_tools(),
            "system_health": "operational"
        }
        return status
    
    async def start_mcp_server(self):
        """Start integrated MCP server."""
        try:
            if self.mcp_server is None:
                from ipfs_datasets_py.mcp_server.simple_server import SimpleIPFSDatasetsMCPServer
                self.mcp_server = SimpleIPFSDatasetsMCPServer()
            
            # Start server in background
            await self.mcp_server.start()
            return {
                "status": "started",
                "message": "MCP server started successfully",
                "tools_available": len(await self.get_available_tools()),
                "endpoints": ["JSON-RPC", "HTTP"]
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to start MCP server: {e}"}
    
    async def execute_mcp_tool(self, category, tool_name, parameters):
        """Execute MCP tool directly."""
        try:
            # Import temporal deontic logic tools for direct execution
            if category == "temporal_deontic_logic":
                return await self.execute_temporal_deontic_tool(tool_name, parameters)
            else:
                # Use tool registry for other tools
                if self.tool_registry is None:
                    from ipfs_datasets_py.mcp_tools.tool_registry import ToolRegistry
                    self.tool_registry = ToolRegistry()
                
                tool = await self.tool_registry.get_tool(category, tool_name)
                if tool:
                    return await tool.execute(parameters)
                else:
                    return {"error": f"Tool not found: {category}/{tool_name}"}
        except Exception as e:
            return {"error": f"Tool execution failed: {e}"}
    
    async def execute_temporal_deontic_tool(self, tool_name, parameters):
        """Execute temporal deontic logic tools directly."""
        try:
            if tool_name == "check_document_consistency":
                from ipfs_datasets_py.logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from ipfs_datasets_py.logic_integration.document_consistency_checker import DocumentConsistencyChecker
                
                # Initialize components
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                # Execute consistency check
                result = await checker.check_document(
                    document_text=parameters.get('document_text', ''),
                    document_id=parameters.get('document_id', f'cli_{int(asyncio.get_event_loop().time())}')
                )
                return result
            else:
                return {"error": f"Unknown temporal deontic tool: {tool_name}"}
        except Exception as e:
            return {"error": f"Temporal deontic tool execution failed: {e}"}
    
    async def check_document_consistency(self, args):
        """Check document consistency via deontic command."""
        # Parse arguments
        document_text = None
        jurisdiction = "Federal"
        
        for i, arg in enumerate(args):
            if arg == '--document' and i + 1 < len(args):
                document_text = args[i + 1]
            elif arg == '--jurisdiction' and i + 1 < len(args):
                jurisdiction = args[i + 1]
        
        if not document_text:
            return "Error: --document parameter required"
        
        # Execute via MCP tool
        return await self.execute_temporal_deontic_tool(
            "check_document_consistency",
            {"document_text": document_text, "jurisdiction": jurisdiction}
        )
    
    def parse_tool_parameters(self, args):
        """Parse tool parameters from command line arguments."""
        parameters = {}
        i = 0
        while i < len(args):
            if args[i].startswith('--'):
                key = args[i][2:]  # Remove --
                if i + 1 < len(args) and not args[i + 1].startswith('--'):
                    parameters[key] = args[i + 1]
                    i += 2
                else:
                    parameters[key] = True
                    i += 1
            else:
                i += 1
        return parameters
    
    async def get_available_tools(self):
        """Get list of available MCP tools."""
        tools = []
        try:
            # Add temporal deontic logic tools
            tools.extend([
                {"category": "temporal_deontic_logic", "name": "check_document_consistency"},
                {"category": "temporal_deontic_logic", "name": "query_theorems"},
                {"category": "temporal_deontic_logic", "name": "bulk_process_caselaw"},
            ])
            
            # Add other available tools from registry
            if self.tool_registry is None:
                from ipfs_datasets_py.mcp_tools.tool_registry import ToolRegistry
                self.tool_registry = ToolRegistry()
            
            registry_tools = await self.tool_registry.list_all_tools()
            tools.extend(registry_tools)
            
        except Exception as e:
            pass  # Continue with partial tool list
            
        return tools
    
    async def is_mcp_server_running(self):
        """Check if MCP server is running."""
        return self.mcp_server is not None and hasattr(self.mcp_server, 'is_running') and self.mcp_server.is_running
    
    async def count_available_tools(self):
        """Count available tools."""
        tools = await self.get_available_tools()
        return len(tools)
    
    async def list_all_tools(self):
        """List all available tools."""
        tools = await self.get_available_tools()
        return {"available_tools": tools, "count": len(tools)}
    
    async def list_tool_categories(self):
        """List tool categories."""
        tools = await self.get_available_tools()
        categories = set(tool["category"] for tool in tools)
        return {"categories": list(categories)}
    
    # Placeholder implementations for other commands
    async def get_config_info(self):
        return {"config": "Configuration info not yet implemented"}
    
    async def stop_mcp_server(self):
        return {"status": "stopped", "message": "MCP server stop not yet implemented"}
    
    async def get_mcp_status(self):
        return {"status": "running" if await self.is_mcp_server_running() else "stopped"}
    
    async def list_mcp_tools(self):
        return await self.list_all_tools()
    
    async def query_theorems(self, args):
        return {"message": "Query theorems not yet implemented"}
    
    async def bulk_process_caselaw(self, args):
        return {"message": "Bulk process caselaw not yet implemented"}
    
    async def load_dataset(self, args):
        return {"message": "Load dataset not yet implemented"}
    
    async def convert_dataset(self, args):
        return {"message": "Convert dataset not yet implemented"}
    
    async def analyze_dataset(self, args):
        return {"message": "Analyze dataset not yet implemented"}
    
    async def pin_to_ipfs(self, args):
        return {"message": "Pin to IPFS not yet implemented"}
    
    async def get_from_ipfs(self, args):
        return {"message": "Get from IPFS not yet implemented"}
    
    async def get_ipfs_status(self):
        return {"message": "IPFS status not yet implemented"}
    
    async def create_embeddings(self, args):
        return {"message": "Create embeddings not yet implemented"}
    
    async def search_vectors(self, args):
        return {"message": "Search vectors not yet implemented"}
    
    async def manage_vector_index(self, args):
        return {"message": "Manage vector index not yet implemented"}


def print_pretty_result(result):
    """Print result in a pretty format."""
    if isinstance(result, dict):
        if "status" in result:
            status = result["status"]
            print(f"Status: {status}")
            if "message" in result:
                print(f"Message: {result['message']}")
            if "tools_available" in result:
                print(f"Tools Available: {result['tools_available']}")
        elif "available_tools" in result:
            print(f"Available Tools ({result.get('count', 0)}):")
            for tool in result["available_tools"]:
                print(f"  - {tool['category']}/{tool['name']}")
        elif "categories" in result:
            print(f"Tool Categories:")
            for category in result["categories"]:
                print(f"  - {category}")
        else:
            for key, value in result.items():
                print(f"{key}: {value}")
    else:
        print(result)


def cli_main():
    """Entry point wrapper for console scripts."""
    main()


if __name__ == "__main__":
    cli_main()