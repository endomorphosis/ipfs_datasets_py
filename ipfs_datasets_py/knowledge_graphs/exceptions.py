"""
Custom exception hierarchy for knowledge graphs module.

This module provides specific exception classes for different types of errors
that can occur during knowledge graph operations, making error handling more
precise and debugging easier.

Exception Hierarchy:
    KnowledgeGraphError (base)
    ├── ExtractionError
    │   ├── EntityExtractionError
    │   ├── RelationshipExtractionError
    │   └── ValidationError
    ├── QueryError
    │   ├── QueryParseError
    │   ├── QueryExecutionError
    │   └── QueryTimeoutError
    ├── StorageError
    │   ├── IPLDStorageError
    │   ├── SerializationError
    │   └── DeserializationError
    ├── GraphError
    │   ├── EntityNotFoundError
    │   ├── RelationshipNotFoundError
    │   └── GraphIntegrityError
    └── TransactionError
        ├── TransactionConflictError
        ├── TransactionAbortedError
        └── TransactionTimeoutError

Usage:
    from ipfs_datasets_py.knowledge_graphs.exceptions import (
        ExtractionError,
        QueryError,
        EntityNotFoundError
    )
    
    # Raise specific exception
    if entity_id not in graph.entities:
        raise EntityNotFoundError(f"Entity {entity_id} not found in graph")
    
    # Catch specific exception
    try:
        result = extractor.extract_entities(text)
    except EntityExtractionError as e:
        logger.error(f"Entity extraction failed: {e}")
        # Handle gracefully
"""

from typing import Optional, Any, Dict


class KnowledgeGraphError(Exception):
    """Base exception for all knowledge graph operations.
    
    All custom exceptions in the knowledge graphs module inherit from this class,
    allowing for broad exception catching when needed while still enabling
    specific error handling.
    
    Attributes:
        message: Human-readable error description
        details: Optional dictionary with additional error context
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Initialize knowledge graph error.
        
        Args:
            message: Human-readable error description
            details: Optional dictionary with additional context (e.g., entity_id, query_text)
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
    
    def __str__(self) -> str:
        """Return string representation with details if available."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


# Extraction Errors
# =================

class ExtractionError(KnowledgeGraphError):
    """Base exception for entity/relationship extraction failures.
    
    Raised when the extraction process encounters errors that prevent
    successful entity or relationship identification.
    """
    pass


class EntityExtractionError(ExtractionError):
    """Exception raised when entity extraction fails.
    
    This can occur due to:
    - NER model failures
    - Invalid input text
    - Missing required dependencies (spaCy, transformers)
    """
    pass


class RelationshipExtractionError(ExtractionError):
    """Exception raised when relationship extraction fails.
    
    This can occur due to:
    - Pattern matching failures
    - Invalid entity references
    - Malformed relationship patterns
    """
    pass


class ValidationError(ExtractionError):
    """Exception raised when validation fails.
    
    This can occur during:
    - SPARQL validation against Wikidata
    - Entity type validation
    - Relationship constraint validation
    """
    pass


# Query Errors
# ============

class QueryError(KnowledgeGraphError):
    """Base exception for query-related failures."""
    pass


class QueryParseError(QueryError):
    """Exception raised when query parsing fails.
    
    This can occur due to:
    - Invalid Cypher syntax
    - Malformed query structure
    - Unsupported query features
    """
    pass


class QueryExecutionError(QueryError):
    """Exception raised when query execution fails.
    
    This can occur due to:
    - Missing entities or relationships
    - Invalid query constraints
    - Backend execution errors
    """
    pass


class QueryTimeoutError(QueryError):
    """Exception raised when query execution times out.
    
    Occurs when a query takes longer than the configured timeout period.
    """
    pass


# Storage Errors
# ==============

class StorageError(KnowledgeGraphError):
    """Base exception for storage-related failures."""
    pass


class IPLDStorageError(StorageError):
    """Exception raised when IPLD storage operations fail.
    
    This can occur due to:
    - IPFS connectivity issues
    - Content addressing failures
    - Missing IPLD backend
    """
    pass


class SerializationError(StorageError):
    """Exception raised when graph serialization fails.
    
    This can occur when converting graph to JSON-LD, IPLD, or other formats.
    """
    pass


class DeserializationError(StorageError):
    """Exception raised when graph deserialization fails.
    
    This can occur when loading graph from JSON-LD, IPLD, or other formats.
    """
    pass


# Graph Errors
# ============

class GraphError(KnowledgeGraphError):
    """Base exception for graph structure errors."""
    pass


class EntityNotFoundError(GraphError):
    """Exception raised when a referenced entity is not found.
    
    Occurs when attempting to access or reference an entity that doesn't exist
    in the knowledge graph.
    """
    pass


class RelationshipNotFoundError(GraphError):
    """Exception raised when a referenced relationship is not found.
    
    Occurs when attempting to access or reference a relationship that doesn't
    exist in the knowledge graph.
    """
    pass


class GraphIntegrityError(GraphError):
    """Exception raised when graph integrity constraints are violated.
    
    This can occur due to:
    - Dangling relationships (referencing non-existent entities)
    - Constraint violations
    - Inconsistent graph state
    """
    pass


# Transaction Errors
# ==================

class TransactionError(KnowledgeGraphError):
    """Base exception for transaction-related failures."""
    pass


class TransactionConflictError(TransactionError):
    """Exception raised when transaction conflicts are detected.
    
    Occurs when concurrent transactions attempt to modify the same entities
    or relationships.
    """
    pass


class TransactionAbortedError(TransactionError):
    """Exception raised when a transaction is aborted.
    
    This can occur due to:
    - Explicit rollback
    - Integrity constraint violations
    - System errors during commit
    """
    pass


class TransactionTimeoutError(TransactionError):
    """Exception raised when a transaction times out.
    
    Occurs when a transaction takes longer than the configured timeout period.
    """
    pass


# Migration/Compatibility Errors
# ===============================

class MigrationError(KnowledgeGraphError):
    """Base exception for data migration failures."""
    pass


class SchemaCompatibilityError(MigrationError):
    """Exception raised when schema compatibility checks fail.
    
    Occurs during Neo4j to IPFS migration when schemas are incompatible.
    """
    pass


class IntegrityVerificationError(MigrationError):
    """Exception raised when data integrity verification fails.
    
    Occurs during migration when source and target data don't match.
    """
    pass


# Convenience exports
__all__ = [
    # Base
    'KnowledgeGraphError',
    
    # Extraction
    'ExtractionError',
    'EntityExtractionError',
    'RelationshipExtractionError',
    'ValidationError',
    
    # Query
    'QueryError',
    'QueryParseError',
    'QueryExecutionError',
    'QueryTimeoutError',
    
    # Storage
    'StorageError',
    'IPLDStorageError',
    'SerializationError',
    'DeserializationError',
    
    # Graph
    'GraphError',
    'EntityNotFoundError',
    'RelationshipNotFoundError',
    'GraphIntegrityError',
    
    # Transaction
    'TransactionError',
    'TransactionConflictError',
    'TransactionAbortedError',
    'TransactionTimeoutError',
    
    # Migration
    'MigrationError',
    'SchemaCompatibilityError',
    'IntegrityVerificationError',
]
