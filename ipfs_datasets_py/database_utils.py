#!/usr/bin/env python3
"""
Database Utilities for IPFS Datasets Python

This module provides unified database utilities for SQLite (metadata/auth) 
and DuckDB (analytics/parquet operations) to replace PostgreSQL dependencies.

SQLite is used for:
- User authentication and authorization
- Job metadata and status tracking
- Activity logs

DuckDB is used for:
- Analytics queries
- Parquet file operations
- Large-scale data processing
- Time-series metrics
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
import anyio

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

try:
    import duckdb
except ImportError:
    duckdb = None

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Database configuration manager"""
    
    def __init__(self):
        self.data_dir = Path(os.getenv("DATABASE_DIR", "./data/databases"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # SQLite database for metadata and auth
        self.sqlite_path = self.data_dir / "metadata.db"
        
        # DuckDB database for analytics and parquet operations
        self.duckdb_path = self.data_dir / "analytics.db"
    
    def get_sqlite_url(self) -> str:
        """Get SQLite database URL"""
        return f"sqlite:///{self.sqlite_path}"
    
    def get_duckdb_path(self) -> Path:
        """Get DuckDB database path"""
        return self.duckdb_path


# Global configuration instance
_db_config = DatabaseConfig()


def get_database_url(db_type: str = "sqlite") -> str:
    """
    Get database URL for the specified database type.
    
    Args:
        db_type: Type of database ("sqlite" or "duckdb")
        
    Returns:
        Database connection string or path
        
    Note:
        This replaces the old get_database_url that returned PostgreSQL URLs.
    """
    if db_type == "sqlite":
        return str(_db_config.sqlite_path)
    elif db_type == "duckdb":
        return str(_db_config.duckdb_path)
    else:
        raise ValueError(f"Unknown database type: {db_type}")


class SQLiteManager:
    """
    SQLite database manager for metadata and authentication.
    
    Handles:
    - User authentication
    - Job metadata
    - Activity logging
    - System configuration
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        if aiosqlite is None:
            raise ImportError("aiosqlite is required. Install with: pip install aiosqlite")
        
        self.db_path = db_path or _db_config.sqlite_path
        self._conn = None
    
    @asynccontextmanager
    async def get_connection(self):
        """Get async database connection"""
        conn = await aiosqlite.connect(str(self.db_path))
        try:
            # Enable foreign keys
            await conn.execute("PRAGMA foreign_keys = ON")
            # Set reasonable timeout
            await conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
        finally:
            await conn.close()
    
    async def initialize_schema(self):
        """Initialize SQLite database schema"""
        async with self.get_connection() as conn:
            # Users table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user' CHECK (role IN ('user', 'admin', 'analyst')),
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_login TEXT
                )
            """)
            
            # Processing jobs table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    url TEXT NOT NULL,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
                    processing_mode TEXT DEFAULT 'balanced',
                    include_media INTEGER DEFAULT 1,
                    archive_services TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT,
                    progress REAL DEFAULT 0.0,
                    entities_extracted INTEGER DEFAULT 0,
                    relationships_found INTEGER DEFAULT 0,
                    content_pieces_processed INTEGER DEFAULT 0,
                    media_files_processed INTEGER DEFAULT 0,
                    quality_score REAL,
                    processing_time_seconds INTEGER,
                    memory_peak_mb INTEGER,
                    storage_used_mb INTEGER
                )
            """)
            
            # Website content metadata
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS website_content (
                    id TEXT PRIMARY KEY,
                    job_id TEXT REFERENCES processing_jobs(id),
                    url TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    title TEXT,
                    content_length INTEGER,
                    language TEXT,
                    extracted_text TEXT,
                    entities TEXT,
                    relationships TEXT,
                    embeddings_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Knowledge graph entities
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_entities (
                    id TEXT PRIMARY KEY,
                    job_id TEXT REFERENCES processing_jobs(id),
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    description TEXT,
                    confidence_score REAL,
                    source_url TEXT,
                    source_content_id TEXT REFERENCES website_content(id),
                    properties TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Knowledge graph relationships
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_relationships (
                    id TEXT PRIMARY KEY,
                    job_id TEXT REFERENCES processing_jobs(id),
                    source_entity_id TEXT REFERENCES kg_entities(id),
                    target_entity_id TEXT REFERENCES kg_entities(id),
                    relationship_type TEXT NOT NULL,
                    confidence_score REAL,
                    evidence TEXT,
                    properties TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # User activity logs
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Search queries
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS search_queries (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    job_id TEXT REFERENCES processing_jobs(id),
                    query TEXT NOT NULL,
                    query_type TEXT DEFAULT 'semantic',
                    results_count INTEGER,
                    response_time_ms INTEGER,
                    satisfaction_score REAL,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Archive metadata
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS archive_metadata (
                    id TEXT PRIMARY KEY,
                    job_id TEXT REFERENCES processing_jobs(id),
                    original_url TEXT NOT NULL,
                    archive_service TEXT NOT NULL,
                    archive_url TEXT,
                    archive_timestamp TEXT,
                    content_hash TEXT,
                    file_size_bytes INTEGER,
                    status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            await conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON processing_jobs(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON processing_jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_content_job ON website_content(job_id);
                CREATE INDEX IF NOT EXISTS idx_content_type ON website_content(content_type);
                CREATE INDEX IF NOT EXISTS idx_entities_job ON kg_entities(job_id);
                CREATE INDEX IF NOT EXISTS idx_entities_type ON kg_entities(entity_type);
                CREATE INDEX IF NOT EXISTS idx_relationships_job ON kg_relationships(job_id);
                CREATE INDEX IF NOT EXISTS idx_archive_job ON archive_metadata(job_id);
                CREATE INDEX IF NOT EXISTS idx_activity_user ON user_activity(user_id);
                CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON user_activity(created_at);
                CREATE INDEX IF NOT EXISTS idx_queries_user ON search_queries(user_id);
                CREATE INDEX IF NOT EXISTS idx_queries_job ON search_queries(job_id);
                CREATE INDEX IF NOT EXISTS idx_queries_timestamp ON search_queries(created_at);
            """)
            
            await conn.commit()
            
            # Insert default users
            await self._create_default_users(conn)
    
    async def _create_default_users(self, conn):
        """Create default admin and demo users"""
        import uuid
        
        # Check if users already exist
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            # Admin user (password: admin)
            await conn.execute("""
                INSERT INTO users (id, username, email, password_hash, role)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                'admin',
                'admin@example.com',
                '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj78.1tIJHfS',
                'admin'
            ))
            
            # Demo user (password: demo)
            await conn.execute("""
                INSERT INTO users (id, username, email, password_hash, role)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                'demo',
                'demo@example.com',
                '$2b$12$92hKmITPNSPkY8Z1fWp1C.2BzGQN/kQOKCz7OLx2yDqzZJNZWBtoW',
                'user'
            ))
            
            await conn.commit()
    
    async def check_health(self) -> Dict[str, Any]:
        """Check database health"""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute("SELECT COUNT(*) FROM users")
                user_count = (await cursor.fetchone())[0]
                
                cursor = await conn.execute("SELECT COUNT(*) FROM processing_jobs")
                job_count = (await cursor.fetchone())[0]
                
                return {
                    "status": "healthy",
                    "database": "sqlite",
                    "users": user_count,
                    "jobs": job_count,
                    "path": str(self.db_path)
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "sqlite",
                "error": str(e)
            }


class DuckDBManager:
    """
    DuckDB database manager for analytics and parquet operations.
    
    Handles:
    - Analytics queries
    - Time-series metrics
    - Parquet file operations
    - Large-scale data processing
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        if duckdb is None:
            raise ImportError("duckdb is required. Install with: pip install duckdb")
        
        self.db_path = db_path or _db_config.duckdb_path
        self._conn = None
    
    def get_connection(self):
        """Get DuckDB connection (not async)"""
        if self._conn is None:
            self._conn = duckdb.connect(str(self.db_path))
        return self._conn
    
    def initialize_schema(self):
        """Initialize DuckDB database schema for analytics"""
        conn = self.get_connection()
        
        # System metrics table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_metrics (
                id VARCHAR PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metric_type VARCHAR NOT NULL,
                metric_name VARCHAR NOT NULL,
                metric_value DECIMAL(15,4),
                metadata JSON
            )
        """)
        
        # Create indexes for performance
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_timestamp 
            ON system_metrics(timestamp)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_type_name 
            ON system_metrics(metric_type, metric_name)
        """)
        
        conn.commit()
    
    def query_parquet(self, parquet_path: str, query: str) -> List[Dict[str, Any]]:
        """
        Query parquet files directly with DuckDB.
        
        Args:
            parquet_path: Path to parquet file or directory
            query: SQL query to execute
            
        Returns:
            Query results as list of dictionaries
        """
        conn = self.get_connection()
        result = conn.execute(query).fetchdf()
        return result.to_dict('records')
    
    def load_parquet_to_table(self, table_name: str, parquet_path: str):
        """Load parquet file into DuckDB table"""
        conn = self.get_connection()
        conn.execute(f"""
            CREATE OR REPLACE TABLE {table_name} AS 
            SELECT * FROM read_parquet('{parquet_path}')
        """)
        conn.commit()
    
    def export_to_parquet(self, table_name: str, output_path: str):
        """Export DuckDB table to parquet file"""
        conn = self.get_connection()
        conn.execute(f"""
            COPY {table_name} TO '{output_path}' (FORMAT PARQUET)
        """)
    
    def check_health(self) -> Dict[str, Any]:
        """Check DuckDB health"""
        try:
            conn = self.get_connection()
            result = conn.execute("SELECT COUNT(*) FROM system_metrics").fetchone()
            metrics_count = result[0] if result else 0
            
            return {
                "status": "healthy",
                "database": "duckdb",
                "metrics_count": metrics_count,
                "path": str(self.db_path)
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "duckdb",
                "error": str(e)
            }
    
    def close(self):
        """Close DuckDB connection"""
        if self._conn:
            self._conn.close()
            self._conn = None


async def initialize_databases():
    """
    Initialize both SQLite and DuckDB databases.
    
    This function should be called during application startup.
    """
    logger.info("Initializing databases...")
    
    # Initialize SQLite
    sqlite_manager = SQLiteManager()
    await sqlite_manager.initialize_schema()
    logger.info("SQLite database initialized")
    
    # Initialize DuckDB
    duckdb_manager = DuckDBManager()
    duckdb_manager.initialize_schema()
    logger.info("DuckDB database initialized")
    
    return {
        "sqlite": sqlite_manager,
        "duckdb": duckdb_manager
    }


async def check_database_health() -> Dict[str, Any]:
    """
    Check health of all databases.
    
    Returns:
        Dictionary with health status of each database
    """
    sqlite_manager = SQLiteManager()
    duckdb_manager = DuckDBManager()
    
    sqlite_health = await sqlite_manager.check_health()
    duckdb_health = duckdb_manager.check_health()
    
    overall_healthy = (
        sqlite_health["status"] == "healthy" and 
        duckdb_health["status"] == "healthy"
    )
    
    return {
        "status": "healthy" if overall_healthy else "unhealthy",
        "databases": {
            "sqlite": sqlite_health,
            "duckdb": duckdb_health
        }
    }


if __name__ == "__main__":
    # Test database initialization
    async def main():
        import sys
        logging.basicConfig(level=logging.INFO)
        
        try:
            # Initialize databases
            databases = await initialize_databases()
            logger.info("Databases initialized successfully")
            
            # Check health
            health = await check_database_health()
            logger.info(f"Database health: {health}")
            
            sys.exit(0)
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            sys.exit(1)
    
    anyio.run(main())
