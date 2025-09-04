#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Investigation MCP Client for Dashboard Communication

This client handles JSON-RPC communication with the MCP server
specifically for investigation and analysis operations.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)


class InvestigationMCPClientError(Exception):
    """Custom exception for Investigation MCP client errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()


class InvestigationMCPClient:
    """
    Client for communicating with the MCP server for investigation operations.
    
    This client handles all communication with the MCP server for
    investigation and analysis operations using JSON-RPC protocol.
    """
    
    def __init__(
        self, 
        base_url: str = "http://localhost:8080",
        endpoint: str = "/mcp/call-tool",
        timeout: int = 60
    ):
        """Initialize the Investigation MCP client."""
        self.base_url = base_url.rstrip('/')
        self.endpoint = endpoint
        self.timeout = timeout
        self.session = None
        self.request_id = 0
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
    
    async def connect(self):
        """Create HTTP session for MCP communication."""
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
    
    async def disconnect(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool with the given arguments.
        
        Args:
            tool_name: Name of the MCP tool to call
            arguments: Arguments to pass to the tool
            
        Returns:
            Tool execution result
            
        Raises:
            InvestigationMCPClientError: If tool execution fails
        """
        if not self.session:
            await self.connect()
        
        # Prepare JSON-RPC request
        self.request_id += 1
        payload = {
            "name": tool_name,
            "arguments": arguments
        }
        
        url = f"{self.base_url}{self.endpoint}"
        
        try:
            async with self.session.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Request-ID": str(self.request_id)
                }
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    raise InvestigationMCPClientError(
                        f"HTTP {response.status}: {error_text}",
                        {"status_code": response.status, "url": url}
                    )
                
                result = await response.json()
                
                # Check if the MCP tool returned an error
                if result.get('isError', False):
                    error_content = result.get('content', [{}])[0]
                    error_message = error_content.get('text', 'Unknown MCP tool error')
                    raise InvestigationMCPClientError(
                        f"MCP tool '{tool_name}' failed: {error_message}",
                        {"tool_name": tool_name, "arguments": arguments, "result": result}
                    )
                
                return result
                
        except aiohttp.ClientError as e:
            raise InvestigationMCPClientError(
                f"Network error calling MCP tool '{tool_name}': {str(e)}",
                {"tool_name": tool_name, "arguments": arguments, "error_type": type(e).__name__}
            )
        except asyncio.TimeoutError:
            raise InvestigationMCPClientError(
                f"Timeout calling MCP tool '{tool_name}' (timeout: {self.timeout}s)",
                {"tool_name": tool_name, "arguments": arguments, "timeout": self.timeout}
            )
        except json.JSONDecodeError as e:
            raise InvestigationMCPClientError(
                f"Invalid JSON response from MCP tool '{tool_name}': {str(e)}",
                {"tool_name": tool_name, "arguments": arguments}
            )
        except Exception as e:
            raise InvestigationMCPClientError(
                f"Unexpected error calling MCP tool '{tool_name}': {str(e)}",
                {"tool_name": tool_name, "arguments": arguments, "error_type": type(e).__name__}
            )


# Factory function for easy client creation
def create_investigation_mcp_client(
    base_url: str = "http://localhost:8080",
    endpoint: str = "/mcp/call-tool",
    timeout: int = 60
) -> InvestigationMCPClient:
    """Create an Investigation MCP client with the given configuration."""
    return InvestigationMCPClient(base_url=base_url, endpoint=endpoint, timeout=timeout)