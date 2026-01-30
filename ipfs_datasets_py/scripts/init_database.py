#!/usr/bin/env python3
"""
Database Initialization Script for GraphRAG System

This script initializes the SQLite and DuckDB databases with the required schema
for the GraphRAG website processing system.
"""

import os
import sys
import anyio
import logging
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.database_utils import (
    initialize_databases,
    check_database_health as check_db_health,
    get_database_url
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_database():
    """Initialize the GraphRAG database schema."""
    try:
        logger.info("Initializing SQLite and DuckDB databases...")
        
        # Initialize both databases
        databases = await initialize_databases()
        
        logger.info("Database initialized successfully")
        logger.info(f"SQLite database: {get_database_url('sqlite')}")
        logger.info(f"DuckDB database: {get_database_url('duckdb')}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        import traceback
        traceback.print_exc()
        return False

async def check_database_health():
    """Check if database is healthy and accessible."""
    try:
        health = await check_db_health()
        
        if health["status"] == "healthy":
            logger.info("Database health check passed")
            for db_name, db_health in health["databases"].items():
                logger.info(f"  {db_name}: {db_health}")
            return True
        else:
            logger.error("Database health check failed")
            logger.error(f"Health status: {health}")
            return False
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="GraphRAG Database Management")
    parser.add_argument("--init", action="store_true", help="Initialize database schema")
    parser.add_argument("--health-check", action="store_true", help="Check database health")
    parser.add_argument("--wait-for-db", action="store_true", help="Wait for database to be ready")
    
    args = parser.parse_args()
    
    if args.health_check:
        success = anyio.run(check_database_health())
        sys.exit(0 if success else 1)
    
    if args.wait_for_db:
        # Wait for database to be ready (useful in Docker Compose)
        import time
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                success = anyio.run(check_database_health())
                if success:
                    logger.info("Database is ready!")
                    sys.exit(0)
            except:
                pass
            
            logger.info(f"Waiting for database... ({attempt + 1}/{max_attempts})")
            time.sleep(2)
        
        logger.error("Database failed to become ready within timeout")
        sys.exit(1)
    
    if args.init:
        success = anyio.run(init_database())
        sys.exit(0 if success else 1)
    
    # Default action is to initialize
    success = anyio.run(init_database())
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()