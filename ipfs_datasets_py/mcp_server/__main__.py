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
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to (HTTP mode only)')
    parser.add_argument('--config', help='Path to configuration file')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--stdio', action='store_true', help='Run in stdio mode (default for VS Code)')
    parser.add_argument('--http', action='store_true', help='Run in HTTP mode (legacy)')

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
            # HTTP mode is legacy; warn and prefer stdio
            import warnings
            warnings.warn(
                "--http mode is deprecated.  The preferred access methods are: "
                "(1) MCP stdio: `python -m ipfs_datasets_py.mcp_server`, "
                "(2) CLI: `ipfs-datasets <command>`, "
                "(3) Python imports: `from ipfs_datasets_py import ...`. "
                "Flask-based HTTP servers have been removed from this project.",
                DeprecationWarning,
                stacklevel=1,
            )
            try:
                start_server(
                    host=args.host,
                    port=args.port
                )
            except (ImportError, TypeError) as e:
                print(
                    f"HTTP server failed to start: {e}\n"
                    "Use `python -m ipfs_datasets_py.mcp_server` instead."
                )
                raise

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
