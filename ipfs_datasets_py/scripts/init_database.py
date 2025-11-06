#!/usr/bin/env python3
"""
Database Initialization Script for GraphRAG System

This script initializes the PostgreSQL database with the required schema
for the GraphRAG website processing system.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from ipfs_datasets_py.enterprise_api import get_database_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_database():
    """Initialize the GraphRAG database schema."""
    try:
        # Get database URL from environment
        db_url = get_database_url()
        logger.info(f"Connecting to database...")
        
        # Connect to database
        conn = await asyncpg.connect(db_url)
        logger.info("Connected to database successfully")
        
        # Read the SQL initialization file
        sql_file = Path(__file__).parent.parent.parent / "deployments" / "sql" / "init.sql"
        if not sql_file.exists():
            logger.error(f"SQL initialization file not found: {sql_file}")
            return False
        
        with open(sql_file, 'r') as f:
            sql_content = f.read()
        
        # Execute the SQL
        logger.info("Executing database initialization SQL...")
        await conn.execute(sql_content)
        logger.info("Database initialized successfully")
        
        # Close connection
        await conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return False

async def check_database_health():
    """Check if database is healthy and accessible."""
    try:
        db_url = get_database_url()
        conn = await asyncpg.connect(db_url)
        
        # Run a simple query
        result = await conn.fetchval("SELECT COUNT(*) FROM users")
        logger.info(f"Database health check passed. Users table has {result} records.")
        
        await conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
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
        success = asyncio.run(check_database_health())
        sys.exit(0 if success else 1)
    
    if args.wait_for_db:
        # Wait for database to be ready (useful in Docker Compose)
        import time
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                success = asyncio.run(check_database_health())
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
        success = asyncio.run(init_database())
        sys.exit(0 if success else 1)
    
    # Default action is to initialize
    success = asyncio.run(init_database())
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()