#!/usr/bin/env python3
"""
MCP Server for Legal Scrapers

Standalone MCP server that exposes legal scraper tools.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)

# Try to import MCP library
try:
    import mcp
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False
    logger.error("MCP library not available - install with: pip install mcp")

from legal_scrapers.mcp.tool_registry import register_all_legal_scraper_tools


class LegalScraperMCPServer:
    """MCP server for legal data scrapers."""
    
    def __init__(self, name: str = "legal-scrapers"):
        """
        Initialize MCP server.
        
        Args:
            name: Server name
        """
        self.name = name
        self.server = None
        
        if not HAVE_MCP:
            raise ImportError("MCP library not available")
        
        # Create MCP server
        self.server = Server(name)
        
        # Register all tools
        register_all_legal_scraper_tools(self.server)
        
        logger.info(f"Legal scraper MCP server '{name}' initialized")
    
    async def run(self):
        """Run the MCP server."""
        if not self.server:
            raise RuntimeError("Server not initialized")
        
        logger.info(f"Starting MCP server: {self.name}")
        
        # Run server with stdio transport
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Main entry point for MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if not HAVE_MCP:
        print("Error: MCP library not available", file=sys.stderr)
        print("Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Create and run server
        server = LegalScraperMCPServer(name="legal-scrapers")
        asyncio.run(server.run())
    
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
