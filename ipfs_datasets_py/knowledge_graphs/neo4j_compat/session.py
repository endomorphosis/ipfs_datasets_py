"""
Session Management for Neo4j Compatibility

This module provides session and transaction management compatible with
Neo4j's Python driver, backed by IPFS/IPLD storage.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Union
from contextlib import contextmanager

from .result import Result, Record
from .types import Node, Relationship, Path

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
_query_executor = None

def _get_query_executor():
    """Get QueryExecutor (lazy import)."""
    global _query_executor
    if _query_executor is None:
        from ..core.query_executor import QueryExecutor
        _query_executor = QueryExecutor
    return _query_executor


class IPFSTransaction:
    """
    Represents an explicit transaction.
    
    Compatible with neo4j.Transaction (Phase 3 will add full ACID support).
    
    Phase 1: Basic structure and auto-commit
    Phase 3: WAL-based ACID transactions with rollback
    """
    
    def __init__(self, session: 'IPFSSession'):
        """
        Initialize a transaction.
        
        Args:
            session: Parent session
        """
        self._session = session
        self._closed = False
        self._committed = False
        logger.debug("Transaction created")
    
    def run(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Result:
        """
        Execute a query within this transaction.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            **kwargs: Additional query options
            
        Returns:
            Query result
        """
        if self._closed:
            raise RuntimeError("Transaction is closed")
        
        # Phase 1: Delegate to session (auto-commit mode)
        # Phase 3 will buffer operations for atomic commit
        return self._session.run(query, parameters, **kwargs)
    
    def commit(self) -> None:
        """
        Commit the transaction.
        
        Phase 1: No-op (auto-commit)
        Phase 3: Apply buffered operations atomically
        """
        if self._closed:
            raise RuntimeError("Transaction is already closed")
        
        self._committed = True
        self._closed = True
        logger.debug("Transaction committed (auto-commit mode)")
    
    def rollback(self) -> None:
        """
        Rollback the transaction.
        
        Phase 1: No-op
        Phase 3: Discard buffered operations
        """
        if self._closed:
            raise RuntimeError("Transaction is already closed")
        
        self._closed = True
        logger.debug("Transaction rolled back (no-op in Phase 1)")
    
    def close(self) -> None:
        """Close the transaction without committing."""
        if not self._closed:
            self.rollback()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None:
            if not self._committed:
                self.commit()
        else:
            self.rollback()
        return False


class IPFSSession:
    """
    Represents a session for executing queries.
    
    Compatible with neo4j.Session.
    
    Provides query execution, transaction management, and resource cleanup.
    """
    
    def __init__(
        self,
        driver: 'IPFSDriver',
        database: Optional[str] = None,
        default_access_mode: str = "WRITE"
    ):
        """
        Initialize a session.
        
        Args:
            driver: Parent driver
            database: Database name (optional, for multi-database support)
            default_access_mode: "READ" or "WRITE"
        """
        self._driver = driver
        self._database = database
        self._default_access_mode = default_access_mode
        self._closed = False
        self._transaction = None
        
        # Create query executor
        QueryExecutorClass = _get_query_executor()
        self._query_executor = QueryExecutorClass()
        
        logger.debug("Session created (database=%s, mode=%s)", database, default_access_mode)
    
    def run(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Result:
        """
        Execute a query in auto-commit mode.
        
        Args:
            query: Cypher query string (Phase 2 will parse this)
            parameters: Query parameters
            **kwargs: Additional query options
            
        Returns:
            Query result
            
        Example:
            result = session.run("MATCH (n) RETURN n LIMIT 10")
            for record in result:
                print(record["n"])
        """
        if self._closed:
            raise RuntimeError("Session is closed")
        
        logger.debug("Executing query: %s", query[:100])
        
        # Phase 1: Use QueryExecutor to route query
        # Phase 2: QueryExecutor will parse Cypher and execute
        # Phase 3: Wrap in transaction
        
        try:
            return self._query_executor.execute(query, parameters, **kwargs)
        except NotImplementedError as e:
            # Cypher not yet implemented - return helpful error
            logger.warning("Query execution not implemented: %s", str(e))
            raise
    
    def begin_transaction(self, **kwargs) -> IPFSTransaction:
        """
        Begin an explicit transaction.
        
        Args:
            **kwargs: Transaction options (e.g., metadata, timeout)
            
        Returns:
            Transaction object
            
        Example:
            with session.begin_transaction() as tx:
                tx.run("CREATE (n:Person {name: $name})", name="Alice")
                tx.commit()
        """
        if self._closed:
            raise RuntimeError("Session is closed")
        
        if self._transaction and not self._transaction._closed:
            raise RuntimeError("Transaction already in progress")
        
        self._transaction = IPFSTransaction(self)
        return self._transaction
    
    def read_transaction(
        self,
        transaction_function: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute a function in a read transaction with retry logic.
        
        Args:
            transaction_function: Function that takes a transaction
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function
            
        Returns:
            Function result
            
        Example:
            def find_person(tx, name):
                result = tx.run("MATCH (p:Person {name: $name}) RETURN p", name=name)
                return result.single()
            
            person = session.read_transaction(find_person, "Alice")
        """
        if self._closed:
            raise RuntimeError("Session is closed")
        
        max_retries = kwargs.pop('max_retries', 3)
        
        for attempt in range(max_retries):
            try:
                with self.begin_transaction() as tx:
                    result = transaction_function(tx, *args, **kwargs)
                    tx.commit()
                    return result
            except Exception as e:
                logger.warning("Read transaction attempt %d failed: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise
        
        return None
    
    def write_transaction(
        self,
        transaction_function: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute a function in a write transaction with retry logic.
        
        Args:
            transaction_function: Function that takes a transaction
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function
            
        Returns:
            Function result
            
        Example:
            def create_person(tx, name, age):
                result = tx.run(
                    "CREATE (p:Person {name: $name, age: $age}) RETURN p",
                    name=name, age=age
                )
                return result.single()
            
            person = session.write_transaction(create_person, "Alice", 30)
        """
        if self._closed:
            raise RuntimeError("Session is closed")
        
        max_retries = kwargs.pop('max_retries', 3)
        
        for attempt in range(max_retries):
            try:
                with self.begin_transaction() as tx:
                    result = transaction_function(tx, *args, **kwargs)
                    tx.commit()
                    return result
            except Exception as e:
                logger.warning("Write transaction attempt %d failed: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise
        
        return None
    
    def close(self) -> None:
        """Close the session and release resources."""
        if not self._closed:
            if self._transaction and not self._transaction._closed:
                self._transaction.close()
            self._closed = True
            logger.debug("Session closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    @property
    def closed(self) -> bool:
        """Check if session is closed."""
        return self._closed
