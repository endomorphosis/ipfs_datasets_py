"""
Index Manager

This module manages all indexes for the knowledge graph.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from .types import IndexDefinition, IndexStats, IndexType
from .btree import BTreeIndex, PropertyIndex, LabelIndex, CompositeIndex
from .specialized import FullTextIndex, SpatialIndex, VectorIndex, RangeIndex

logger = logging.getLogger(__name__)


class IndexManager:
    """
    Manages all indexes for a knowledge graph.
    
    Provides:
    - Index creation and deletion
    - Query routing to appropriate indexes
    - Index statistics
    """
    
    def __init__(self):
        """Initialize the index manager."""
        self.indexes: Dict[str, Any] = {}
        
        # Create default label index
        self.label_index = LabelIndex()
        self.indexes["idx_labels"] = self.label_index
    
    def create_property_index(
        self,
        property_name: str,
        label: Optional[str] = None
    ) -> str:
        """
        Create index on a property.
        
        Args:
            property_name: Property to index
            label: Optional label filter
            
        Returns:
            Index name
        """
        index = PropertyIndex(property_name, label)
        self.indexes[index.definition.name] = index
        logger.info(f"Created property index: {index.definition.name}")
        return index.definition.name
    
    def create_composite_index(
        self,
        property_names: List[str],
        label: Optional[str] = None
    ) -> str:
        """
        Create composite index on multiple properties.
        
        Args:
            property_names: Properties to index
            label: Optional label filter
            
        Returns:
            Index name
        """
        index = CompositeIndex(property_names, label)
        self.indexes[index.definition.name] = index
        logger.info(f"Created composite index: {index.definition.name}")
        return index.definition.name
    
    def create_fulltext_index(
        self,
        property_name: str,
        label: Optional[str] = None
    ) -> str:
        """
        Create full-text search index.
        
        Args:
            property_name: Property to index
            label: Optional label filter
            
        Returns:
            Index name
        """
        index = FullTextIndex(property_name, label)
        self.indexes[index.definition.name] = index
        logger.info(f"Created full-text index: {index.definition.name}")
        return index.definition.name
    
    def create_spatial_index(
        self,
        property_name: str,
        grid_size: float = 1.0
    ) -> str:
        """
        Create spatial index.
        
        Args:
            property_name: Property containing coordinates
            grid_size: Grid cell size
            
        Returns:
            Index name
        """
        index = SpatialIndex(property_name, grid_size)
        self.indexes[index.definition.name] = index
        logger.info(f"Created spatial index: {index.definition.name}")
        return index.definition.name
    
    def create_vector_index(
        self,
        property_name: str,
        dimension: int
    ) -> str:
        """
        Create vector similarity index.
        
        Args:
            property_name: Property containing vectors
            dimension: Vector dimension
            
        Returns:
            Index name
        """
        index = VectorIndex(property_name, dimension)
        self.indexes[index.definition.name] = index
        logger.info(f"Created vector index: {index.definition.name}")
        return index.definition.name
    
    def create_range_index(
        self,
        property_name: str,
        label: Optional[str] = None
    ) -> str:
        """
        Create range index.
        
        Args:
            property_name: Property to index
            label: Optional label filter
            
        Returns:
            Index name
        """
        index = RangeIndex(property_name, label)
        self.indexes[index.definition.name] = index
        logger.info(f"Created range index: {index.definition.name}")
        return index.definition.name
    
    def drop_index(self, name: str) -> bool:
        """
        Drop an index.
        
        Args:
            name: Index name
            
        Returns:
            True if dropped, False if not found
        """
        if name == "idx_labels":
            logger.warning("Cannot drop label index")
            return False
        
        if name in self.indexes:
            del self.indexes[name]
            logger.info(f"Dropped index: {name}")
            return True
        
        return False
    
    def get_index(self, name: str) -> Optional[Any]:
        """
        Get an index by name.
        
        Args:
            name: Index name
            
        Returns:
            Index or None if not found
        """
        return self.indexes.get(name)
    
    def list_indexes(self) -> List[IndexDefinition]:
        """
        List all indexes.
        
        Returns:
            List of index definitions
        """
        return [index.definition for index in self.indexes.values()]
    
    def get_stats(self, name: Optional[str] = None) -> Dict[str, IndexStats]:
        """
        Get statistics for indexes.
        
        Args:
            name: Optional index name (if None, return all)
            
        Returns:
            Dictionary of index stats
        """
        if name:
            index = self.indexes.get(name)
            if index:
                return {name: index.get_stats()}
            return {}
        
        return {
            name: index.get_stats()
            for name, index in self.indexes.items()
        }
    
    def insert_entity(self, entity: Dict[str, Any]):
        """
        Insert entity into all applicable indexes.
        
        Args:
            entity: Entity dictionary with id, type, and properties
        """
        entity_id = entity["id"]
        entity_type = entity.get("type", "Thing")
        properties = entity.get("properties", {})
        
        # Insert into label index
        self.label_index.insert(entity_type, entity_id)
        
        # Insert into property indexes
        for name, index in self.indexes.items():
            if name == "idx_labels":
                continue
            
            # Check if entity matches index label filter
            if index.definition.label and index.definition.label != entity_type:
                continue
            
            if isinstance(index, PropertyIndex):
                # Single property index
                prop_name = index.property_name
                if prop_name in properties:
                    value = properties[prop_name]
                    index.insert(value, entity_id)
            
            elif isinstance(index, CompositeIndex):
                # Composite index
                values = []
                for prop_name in index.property_names:
                    if prop_name not in properties:
                        break
                    values.append(properties[prop_name])
                else:
                    # All properties present
                    index.insert_composite(values, entity_id)
            
            elif isinstance(index, FullTextIndex):
                # Full-text index
                prop_name = index.property_name
                if prop_name in properties:
                    text = str(properties[prop_name])
                    index.insert(text, entity_id)
            
            elif isinstance(index, SpatialIndex):
                # Spatial index
                prop_name = index.property_name
                if prop_name in properties:
                    coords = properties[prop_name]
                    if isinstance(coords, (list, tuple)) and len(coords) == 2:
                        index.insert(tuple(coords), entity_id)
            
            elif isinstance(index, VectorIndex):
                # Vector index
                prop_name = index.property_name
                if prop_name in properties:
                    vector = properties[prop_name]
                    if isinstance(vector, list):
                        index.insert(vector, entity_id)
            
            elif isinstance(index, (RangeIndex, BTreeIndex)):
                # Range or B-tree index
                for prop_name in index.definition.properties:
                    if prop_name in properties:
                        value = properties[prop_name]
                        index.insert(value, entity_id)
