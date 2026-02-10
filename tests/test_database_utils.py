"""
Tests for database utilities (SQLite and DuckDB).

This module tests the database utilities that replace PostgreSQL with
SQLite (for metadata/auth) and DuckDB (for analytics).
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from ipfs_datasets_py.database_utils import (
    SQLiteManager,
    DuckDBManager,
    initialize_databases,
    check_database_health,
    get_database_url
)
import ipfs_datasets_py.database_utils as db_utils


class TestSQLiteManager:
    """Test SQLite database manager."""
    
    @pytest.fixture
    async def temp_db(self):
        """Create temporary SQLite database."""
        if db_utils.aiosqlite is None:
            pytest.skip("aiosqlite not installed")
        temp_dir = Path(tempfile.mkdtemp())
        db_path = temp_dir / "test.db"
        manager = SQLiteManager(db_path)
        await manager.initialize_schema(create_default_users=True)
        yield manager
        # Cleanup
        shutil.rmtree(temp_dir)
    
    async def test_initialize_schema(self, temp_db):
        """Test that schema is initialized correctly."""
        # GIVEN: A fresh SQLite manager
        manager = temp_db
        
        # WHEN: Checking the database health
        health = await manager.check_health()
        
        # THEN: Database should be healthy
        assert health["status"] == "healthy"
        assert health["database"] == "sqlite"
        assert health["users"] == 2  # admin and demo users
        assert health["jobs"] == 0
    
    async def test_connection(self, temp_db):
        """Test database connection."""
        # GIVEN: An initialized SQLite manager
        manager = temp_db
        
        # WHEN: Getting a connection
        async with manager.get_connection() as conn:
            # THEN: Should be able to query
            cursor = await conn.execute("SELECT COUNT(*) FROM users")
            count = (await cursor.fetchone())[0]
            assert count == 2


class TestDuckDBManager:
    """Test DuckDB database manager."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary DuckDB database."""
        if db_utils.duckdb is None:
            pytest.skip("duckdb not installed")
        temp_dir = Path(tempfile.mkdtemp())
        db_path = temp_dir / "test.duckdb"
        manager = DuckDBManager(db_path)
        manager.initialize_schema()
        yield manager
        manager.close()
        # Cleanup
        shutil.rmtree(temp_dir)
    
    def test_initialize_schema(self, temp_db):
        """Test that schema is initialized correctly."""
        # GIVEN: A fresh DuckDB manager
        manager = temp_db
        
        # WHEN: Checking the database health
        health = manager.check_health()
        
        # THEN: Database should be healthy
        assert health["status"] == "healthy"
        assert health["database"] == "duckdb"
        assert health["metrics_count"] == 0
    
    def test_query_execution(self, temp_db):
        """Test executing queries."""
        # GIVEN: An initialized DuckDB manager
        manager = temp_db
        
        # WHEN: Inserting and querying data
        conn = manager.get_connection()
        import uuid
        test_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO system_metrics (id, metric_type, metric_name, metric_value)
            VALUES (?, ?, ?, ?)
        """, (test_id, "test", "test_metric", 42.0))
        conn.commit()
        
        # THEN: Should be able to query the data
        result = conn.execute("""
            SELECT metric_value FROM system_metrics 
            WHERE metric_type = 'test' AND metric_name = 'test_metric'
        """).fetchone()
        
        assert result[0] == 42.0


class TestDatabaseIntegration:
    """Test database initialization and health checks."""
    
    @pytest.fixture
    async def temp_databases(self):
        """Create temporary databases."""
        if db_utils.aiosqlite is None or db_utils.duckdb is None:
            pytest.skip("aiosqlite and duckdb must be installed for database integration tests")
        # Create temporary directory
        temp_dir = Path(tempfile.mkdtemp())
        
        # Save original config values
        original_data_dir = db_utils._db_config.data_dir
        original_sqlite_path = db_utils._db_config.sqlite_path
        original_duckdb_path = db_utils._db_config.duckdb_path
        
        # Override database paths
        db_utils._db_config.data_dir = temp_dir
        db_utils._db_config.sqlite_path = temp_dir / "metadata.db"
        db_utils._db_config.duckdb_path = temp_dir / "analytics.db"
        
        yield temp_dir
        
        # Restore original config values
        db_utils._db_config.data_dir = original_data_dir
        db_utils._db_config.sqlite_path = original_sqlite_path
        db_utils._db_config.duckdb_path = original_duckdb_path
        
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    async def test_initialize_databases(self, temp_databases):
        """Test initializing both databases."""
        # GIVEN: Temporary database directory
        temp_dir = temp_databases
        
        # WHEN: Initializing databases with default users for testing
        databases = await initialize_databases(create_default_users=True)
        
        # THEN: Both databases should be initialized
        assert "sqlite" in databases
        assert "duckdb" in databases
        
        # Check that files were created
        assert (temp_dir / "metadata.db").exists()
        assert (temp_dir / "analytics.db").exists()
        
        # Clean up DuckDB connection
        databases['duckdb'].close()
    
    async def test_check_database_health(self, temp_databases):
        """Test checking database health."""
        # GIVEN: Initialized databases
        await initialize_databases(create_default_users=True)
        
        # WHEN: Checking health
        health = await check_database_health()
        
        # THEN: Should report healthy
        assert health["status"] == "healthy"
        assert "databases" in health
        assert "sqlite" in health["databases"]
        assert "duckdb" in health["databases"]
        assert health["databases"]["sqlite"]["status"] == "healthy"
        assert health["databases"]["duckdb"]["status"] == "healthy"
    
    async def test_get_database_url(self, temp_databases):
        """Test getting database URLs."""
        # GIVEN: Temporary database configuration
        temp_dir = temp_databases
        
        # WHEN: Getting database URLs
        sqlite_url = get_database_url("sqlite")
        duckdb_url = get_database_url("duckdb")
        
        # THEN: URLs should point to temporary directory
        assert str(temp_dir) in sqlite_url
        assert str(temp_dir) in duckdb_url
        assert "metadata.db" in sqlite_url
        assert "analytics.db" in duckdb_url
    
    def test_get_database_url_invalid_type(self):
        """Test getting database URL with invalid type."""
        # GIVEN: Invalid database type
        # WHEN: Getting database URL
        # THEN: Should raise ValueError
        with pytest.raises(ValueError, match="Unknown database type"):
            get_database_url("invalid_type")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
