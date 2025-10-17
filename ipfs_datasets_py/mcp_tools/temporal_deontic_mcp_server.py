#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Temporal Deontic Logic MCP Server.

This module provides an MCP (Model Context Protocol) server specifically for
temporal deontic logic RAG system tools. It handles JSON-RPC requests from
the dashboard and other clients for legal document consistency checking.

The server exposes the following MCP tools:
- check_document_consistency: Legal document debugging
- query_theorems: RAG-based theorem retrieval  
- bulk_process_caselaw: Corpus processing
- add_theorem: Individual theorem addition

Usage:
    server = TemporalDeonticMCPServer()
    await server.start()
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

try:
    from mcp import types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

from .tools.temporal_deontic_logic_tools import TEMPORAL_DEONTIC_LOGIC_TOOLS
from .tools.legal_dataset_mcp_tools import LEGAL_DATASET_MCP_TOOLS

logger = logging.getLogger(__name__)


class TemporalDeonticMCPServer:
    """
    MCP Server for Temporal Deontic Logic RAG System.
    
    This server provides JSON-RPC access to temporal deontic logic tools
    for legal document consistency checking and theorem management.
    """
    
    def __init__(self, port: int = 8765):
        """
        Initialize the MCP server.
        
        Args:
            port: Port number for the server (default: 8765)
        """
        self.port = port
        self.server = None
        
        # Combine temporal deontic logic tools and legal dataset tools
        all_tools = TEMPORAL_DEONTIC_LOGIC_TOOLS + LEGAL_DATASET_MCP_TOOLS
        self.tools = {tool.name: tool for tool in all_tools}
        
        if not MCP_AVAILABLE:
            logger.warning("MCP library not available - server will not function")
    
    def setup_server(self) -> Server:
        """
        Set up the MCP server with tool handlers.
        
        Returns:
            Configured MCP Server instance
        """
        if not MCP_AVAILABLE:
            raise ImportError("MCP library not available")
        
        server = Server("temporal-deontic-logic")
        
        # Register list_tools handler
        @server.list_tools()
        async def list_tools() -> List[types.Tool]:
            """List available temporal deontic logic tools."""
            tools = []
            
            for tool_name, tool_instance in self.tools.items():
                tool_schema = tool_instance.get_schema()
                
                # Convert to MCP tool format
                mcp_tool = types.Tool(
                    name=tool_name,
                    description=tool_schema["description"],
                    inputSchema=tool_schema["input_schema"]
                )
                tools.append(mcp_tool)
            
            logger.info(f"Listed {len(tools)} temporal deontic logic tools")
            return tools
        
        # Register call_tool handler
        @server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
            """Execute temporal deontic logic tool."""
            if name not in self.tools:
                raise ValueError(f"Unknown tool: {name}")
            
            try:
                tool_instance = self.tools[name]
                result = await tool_instance.execute(arguments)
                
                # Format result as MCP TextContent
                result_text = json.dumps(result, indent=2, default=str)
                
                return [
                    types.TextContent(
                        type="text",
                        text=result_text
                    )
                ]
                
            except Exception as e:
                logger.error(f"Tool execution failed for {name}: {e}")
                error_result = {
                    "success": False,
                    "error": str(e),
                    "tool": name,
                    "error_code": "TOOL_EXECUTION_ERROR"
                }
                
                return [
                    types.TextContent(
                        type="text", 
                        text=json.dumps(error_result, indent=2)
                    )
                ]
        
        # Register get_prompt handler (optional)
        @server.list_prompts()
        async def list_prompts() -> List[types.Prompt]:
            """List available prompts for legal analysis."""
            return [
                types.Prompt(
                    name="legal_analysis_prompt",
                    description="Prompt for legal document analysis using temporal deontic logic",
                    arguments=[
                        types.PromptArgument(
                            name="document_text",
                            description="Legal document to analyze",
                            required=True
                        )
                    ]
                )
            ]
        
        @server.get_prompt()
        async def get_prompt(name: str, arguments: Dict[str, str]) -> types.GetPromptResult:
            """Get legal analysis prompt."""
            if name != "legal_analysis_prompt":
                raise ValueError(f"Unknown prompt: {name}")
            
            document_text = arguments.get("document_text", "")
            
            prompt_text = f"""
Analyze the following legal document for consistency with temporal deontic logic theorems:

Document Text:
{document_text}

Please identify:
1. Deontic logic formulas (obligations, permissions, prohibitions)
2. Potential conflicts with existing legal precedents
3. Temporal aspects and jurisdictional considerations
4. Recommendations for resolving any inconsistencies

Provide a detailed analysis similar to a legal debugger output.
"""
            
            return types.GetPromptResult(
                description="Legal document analysis prompt",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(
                            type="text",
                            text=prompt_text
                        )
                    )
                ]
            )
        
        return server
    
    async def start_stdio(self):
        """Start the MCP server using stdio transport."""
        if not MCP_AVAILABLE:
            raise ImportError("MCP library not available")
        
        server = self.setup_server()
        
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Temporal Deontic Logic MCP Server started (stdio)")
            await server.run(read_stream, write_stream, server.create_initialization_options())
    
    async def start_websocket(self, host: str = "localhost", port: int = None):
        """
        Start the MCP server using WebSocket transport.
        
        Args:
            host: Host address to bind to
            port: Port number to use (defaults to self.port)
        """
        if not MCP_AVAILABLE:
            raise ImportError("MCP library not available")
        
        if port is None:
            port = self.port
        
        # Note: WebSocket transport would require additional setup
        # For now, this is a placeholder for future implementation
        logger.info(f"WebSocket MCP server would start on {host}:{port}")
        raise NotImplementedError("WebSocket transport not yet implemented")
    
    def get_tool_schemas(self) -> Dict[str, Dict[str, Any]]:
        """
        Get JSON schemas for all available tools.
        
        Returns:
            Dictionary mapping tool names to their schemas
        """
        schemas = {}
        for tool_name, tool_instance in self.tools.items():
            schemas[tool_name] = tool_instance.get_schema()
        return schemas
    
    async def call_tool_direct(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool directly without MCP protocol wrapper.
        
        Args:
            tool_name: Name of the tool to call
            parameters: Tool parameters
            
        Returns:
            Tool execution result
        """
        if tool_name not in self.tools:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
                "error_code": "UNKNOWN_TOOL"
            }
        
        try:
            tool_instance = self.tools[tool_name]
            result = await tool_instance.execute(parameters)
            return result
        
        except Exception as e:
            logger.error(f"Direct tool call failed for {tool_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "tool": tool_name,
                "error_code": "TOOL_EXECUTION_ERROR"
            }


# Singleton instance for easy access
temporal_deontic_mcp_server = TemporalDeonticMCPServer()


async def main():
    """Main entry point for running the MCP server."""
    if not MCP_AVAILABLE:
        print("Error: MCP library not available. Please install mcp package.")
        return
    
    try:
        server = TemporalDeonticMCPServer()
        await server.start_stdio()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")


if __name__ == "__main__":
    asyncio.run(main())