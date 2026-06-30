#!/usr/bin/env python3
"""
Main entry point for running the IPFS Datasets MCP Server as a module.

Usage:
    python -m ipfs_datasets_py.mcp_server [options]

This allows VS Code and other tools to start the MCP server easily.
"""

import sys
import anyio
import argparse
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import custom exceptions
try:
    from ipfs_datasets_py.mcp_server.exceptions import (
        ServerStartupError,
        ConfigurationError,
    )
    EXCEPTIONS_AVAILABLE = True
except ImportError:
    EXCEPTIONS_AVAILABLE = False
    ServerStartupError = Exception
    ConfigurationError = Exception

# Import error reporting if available
try:
    from ipfs_datasets_py.error_reporting import install_error_handlers
    ERROR_REPORTING_AVAILABLE = True
except ImportError:
    ERROR_REPORTING_AVAILABLE = False

def main():
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(description='IPFS Datasets MCP Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to (HTTP mode only)')
    parser.add_argument('--port', type=int, default=3002, help='Port to bind to (HTTP mode only)')
    parser.add_argument('--config', help='Path to configuration file')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--stdio', action='store_true', help='Run in stdio mode (default for VS Code)')
    parser.add_argument('--http', action='store_true', help='Run in HTTP mode with Hypercorn+Trio')

    args = parser.parse_args()

    # Configure logging level
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    # Install error handlers if available
    if ERROR_REPORTING_AVAILABLE:
        install_error_handlers()

    # Determine mode: default to stdio unless --http is specified
    use_stdio = not args.http or args.stdio

    try:
        # Import the server modules
        from ipfs_datasets_py.mcp_server import start_stdio_server, start_server, configs

        if use_stdio:
            # Use stdio mode for VS Code integration
            try:
                start_stdio_server()
            except (ImportError, TypeError) as e:
                print(f"Error with stdio server: {e}")
                raise
        else:
            # HTTP mode via Hypercorn+Trio
            import trio
            try:
                from hypercorn.config import Config as HypercornConfig
                from hypercorn.trio import serve as hypercorn_serve
                from ipfs_datasets_py.mcp_server.fastapi_service import app as fastapi_app

                hconfig = HypercornConfig()
                hconfig.bind = [f"{args.host}:{args.port}"]
                hconfig.worker_class = "trio"
                hconfig.loglevel = "DEBUG" if args.debug else "INFO"
                hconfig.accesslog = "-"
                print(f"🚀 Starting IPFS Datasets MCP++ on {args.host}:{args.port} (Hypercorn+Trio)")
                trio.run(hypercorn_serve, fastapi_app, hconfig)
            except ImportError as e:
                print(f"Hypercorn not available ({e}). Install with: pip install hypercorn[trio]")
                sys.exit(1)

    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except ServerStartupError as e:
        print(f"Server startup error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except ConfigurationError as e:
        print(f"Configuration error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except (ImportError, ModuleNotFoundError) as e:
        print(f"Required module not available: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"Error starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
