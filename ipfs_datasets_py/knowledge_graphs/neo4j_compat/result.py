"""
Query Result Types for Neo4j Compatibility

This module provides Result and Record types that are compatible with
Neo4j's Python driver, enabling seamless migration to IPFS-backed storage.
"""

from typing import Any, Dict, Iterator, List, Optional, Sequence

from .types import Node, Relationship, Path, GraphObject


class Record:
    """
    Represents a single record (row) in a query result.
    
    Compatible with neo4j.Record.
    
    Provides both dictionary-style and attribute-style access to fields.
    """
    
    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        """
        Initialize a Record.
        
        Args:
            keys: Field names
            values: Field values
        """
        if len(keys) != len(values):
            raise ValueError(f"Keys and values must have same length: {len(keys)} vs {len(values)}")
        
        self._keys = tuple(keys)
        self._values = tuple(values)
        self._data = dict(zip(keys, values))
    
    def keys(self) -> List[str]:
        """Get the field names."""
        return list(self._keys)
    
    def values(self) -> List[Any]:
        """Get the field values."""
        return list(self._values)
    
    def items(self) -> List[tuple]:
        """Get (key, value) pairs."""
        return list(self._data.items())
    
    def data(self) -> Dict[str, Any]:
        """Get the record as a dictionary."""
        return self._data.copy()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a field value.
        
        Args:
            key: Field name
            default: Default value if not found
            
        Returns:
            Field value or default
        """
        return self._data.get(key, default)
    
    def __getitem__(self, key: Any) -> Any:
        """
        Get a field value by key or index.
        
        Args:
            key: Field name (str) or index (int)
            
        Returns:
            Field value
        """
        if isinstance(key, int):
            return self._values[key]
        return self._data[key]
    
    def __contains__(self, key: str) -> bool:
        """Check if field exists."""
        return key in self._data
    
    def __len__(self) -> int:
        """Get the number of fields."""
        return len(self._keys)
    
    def __iter__(self) -> Iterator[Any]:
        """Iterate over field values."""
        return iter(self._values)
    
    def __repr__(self) -> str:
        """String representation."""
        items_str = ", ".join(f"{k}={v!r}" for k, v in self._data.items())
        return f"Record({items_str})"


class Result:
    """
    Represents the result of a query.
    
    Compatible with neo4j.Result.
    
    Provides iteration, single record access, and batch data retrieval.
    """
    
    def __init__(self, records: List[Record], summary: Optional[Dict[str, Any]] = None):
        """
        Initialize a Result.
        
        Args:
            records: List of Record objects
            summary: Optional query summary information
        """
        self._records = list(records)
        self._index = 0
        self._summary = summary or {}
        self._consumed = False
    
    def keys(self) -> List[str]:
        """
        Get the field names from the first record.
        
        Returns:
            List of field names, or empty list if no records
        """
        if not self._records:
            return []
        return self._records[0].keys()
    
    def single(self, strict: bool = False) -> Optional[Record]:
        """
        Get a single record from the result.
        
        Args:
            strict: If True, raise error if not exactly one record
            
        Returns:
            The single record, or None if no records
            
        Raises:
            ValueError: If strict=True and not exactly one record
        """
        if not self._records:
            if strict:
                raise ValueError("Expected exactly one record, got zero")
            return None
        
        if len(self._records) > 1 and strict:
            raise ValueError(f"Expected exactly one record, got {len(self._records)}")
        
        self._consumed = True
        return self._records[0]
    
    def data(self) -> List[Dict[str, Any]]:
        """
        Get all records as a list of dictionaries.
        
        Returns:
            List of record dictionaries
        """
        self._consumed = True
        return [record.data() for record in self._records]
    
    def value(self, key: Optional[str] = None, default: Any = None) -> List[Any]:
        """
        Get a single field from all records.
        
        Args:
            key: Field name (uses first field if None)
            default: Default value for missing fields
            
        Returns:
            List of field values
        """
        self._consumed = True
        if not self._records:
            return []
        
        if key is None:
            # Use first field
            keys = self._records[0].keys()
            if not keys:
                return []
            key = keys[0]
        
        return [record.get(key, default) for record in self._records]
    
    def values(self) -> List[List[Any]]:
        """
        Get all records as lists of values.
        
        Returns:
            List of value lists
        """
        self._consumed = True
        return [record.values() for record in self._records]
    
    def graph(self) -> Dict[str, List[GraphObject]]:
        """
        Get graph objects (nodes, relationships, paths) from the result.
        
        Returns:
            Dictionary with 'nodes', 'relationships', and 'paths' lists
        """
        self._consumed = True
        
        nodes = []
        relationships = []
        paths = []
        
        for record in self._records:
            for value in record.values():
                if isinstance(value, Node):
                    if value not in nodes:
                        nodes.append(value)
                elif isinstance(value, Relationship):
                    if value not in relationships:
                        relationships.append(value)
                elif isinstance(value, Path):
                    paths.append(value)
                    # Extract nodes and relationships from path
                    for node in value.nodes:
                        if node not in nodes:
                            nodes.append(node)
                    for rel in value.relationships:
                        if rel not in relationships:
                            relationships.append(rel)
        
        return {
            "nodes": nodes,
            "relationships": relationships,
            "paths": paths
        }
    
    def peek(self) -> Optional[Record]:
        """
        Peek at the next record without consuming it.
        
        Returns:
            Next record, or None if no more records
        """
        if self._index >= len(self._records):
            return None
        return self._records[self._index]
    
    def consume(self) -> Dict[str, Any]:
        """
        Consume the entire result and return summary.
        
        Returns:
            Query summary information
        """
        # Iterate through all records to mark as consumed
        list(self)
        self._consumed = True
        return self._summary
    
    def __iter__(self) -> Iterator[Record]:
        """Iterate over records."""
        for record in self._records[self._index:]:
            self._index += 1
            yield record
        self._consumed = True
    
    def __len__(self) -> int:
        """Get the number of records."""
        return len(self._records)
    
    def __bool__(self) -> bool:
        """Check if result has any records."""
        return len(self._records) > 0
    
    def __repr__(self) -> str:
        """String representation."""
        return f"Result(records={len(self._records)}, consumed={self._consumed})"
