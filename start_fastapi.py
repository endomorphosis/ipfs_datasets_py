#!/usr/bin/env python3
"""
FastAPI Service Startup Script

This script starts the IPFS Datasets FastAPI service with proper configuration
and environment setup.
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def setup_environment():
    """Setup environment variables if not already set."""
    # Set default environment variables
    env_defaults = {
        "DEBUG": "true",
        "ENVIRONMENT": "development",
        "HOST": "0.0.0.0",
        "PORT": "8000",
        "SECRET_KEY": "dev-secret-key-change-in-production",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
        "RATE_LIMIT_ENABLED": "true",
        "DEFAULT_EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2"
    }
    
    for key, value in env_defaults.items():
        if key not in os.environ:
            os.environ[key] = value

def main():
    """Main startup function."""
    parser = argparse.ArgumentParser(description="Start IPFS Datasets FastAPI Service")
    parser.add_argument("--env", choices=["development", "production"], default="development",
                       help="Environment mode (default: development)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    
    # Setup environment
    setup_environment()
    
    # Override with command line arguments
    os.environ["ENVIRONMENT"] = args.env
    os.environ["HOST"] = args.host
    os.environ["PORT"] = str(args.port)
    
    if args.debug:
        os.environ["DEBUG"] = "true"
    if args.reload:
        os.environ["RELOAD"] = "true"
    
    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"🚀 Starting IPFS Datasets FastAPI Service")
    logger.info(f"Environment: {args.env}")
    logger.info(f"Host: {args.host}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Debug: {args.debug}")
    logger.info(f"Reload: {args.reload}")
    
    try:
        # Import and start the service
        from ipfs_datasets_py.fastapi_service import run_development_server, run_production_server
        
        if args.env == "production":
            run_production_server()
        else:
            run_development_server()
            
    except KeyboardInterrupt:
        logger.info("🛑 Service stopped by user")
    except Exception as e:
        logger.error(f"❌ Failed to start service: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
