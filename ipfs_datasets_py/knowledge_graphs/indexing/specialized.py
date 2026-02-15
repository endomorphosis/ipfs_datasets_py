"""
Specialized Indexes

This module provides specialized index types:
- Full-text search indexes
- Spatial indexes (geospatial)  
- Vector indexes (for embeddings)
- Range indexes
"""

import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import IndexDefinition, IndexEntry, IndexStats, IndexType
from .btree import BTreeIndex

logger = logging.getLogger(__name__)


class FullTextIndex:
    """
    Full-text search index using inverted index.
    
    Tokenizes text and creates term-to-entity mappings.
    """
    
    def __init__(self, property_name: str, label: Optional[str] = None):
        """
        Initialize full-text index.
        
        Args:
            property_name: Property to index
            label: Optional label filter
        """
        self.definition = IndexDefinition(
            name=f"idx_fulltext_{property_name}",
            index_type=IndexType.FULLTEXT,
            properties=[property_name],
            label=label
        )
        self.property_name = property_name
        
        # Inverted index: term -> set of entity IDs
        self.inverted_index: Dict[str, Set[str]] = {}
        
        # Document frequencies for TF-IDF
        self.doc_frequencies: Dict[str, int] = {}
        self.total_docs = 0
    
    def insert(self, text: str, entity_id: str):
        """
        Index text for an entity.
        
        Args:
            text: Text to index
            entity_id: Entity ID
        """
        # Tokenize
        tokens = self._tokenize(text)
        
        # Add to inverted index
        for token in set(tokens):
            if token not in self.inverted_index:
                self.inverted_index[token] = set()
                self.doc_frequencies[token] = 0
            
            if entity_id not in self.inverted_index[token]:
                self.inverted_index[token].add(entity_id)
                self.doc_frequencies[token] += 1
        
        self.total_docs += 1
    
    def search(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Search for entities matching query.
        
        Args:
            query: Search query
            limit: Maximum results to return
            
        Returns:
            List of (entity_id, score) tuples, sorted by score
        """
        # Tokenize query
        query_tokens = self._tokenize(query)
        
        if not query_tokens:
            return []
        
        # Find candidate documents
        candidates: Set[str] = set()
        for token in query_tokens:
            if token in self.inverted_index:
                candidates.update(self.inverted_index[token])
        
        if not candidates:
            return []
        
        # Score candidates using TF-IDF
        scores: Dict[str, float] = {}
        for entity_id in candidates:
            score = self._calculate_score(entity_id, query_tokens)
            scores[entity_id] = score
        
        # Sort by score and return top results
        results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return results[:limit]
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into terms.
        
        Args:
            text: Text to tokenize
            
        Returns:
            List of tokens
        """
        # Simple tokenization: lowercase, split on whitespace and punctuation
        text = text.lower()
        # Remove punctuation
        for char in ".,;:!?\"'()[]{}":
            text = text.replace(char, " ")
        
        tokens = text.split()
        
        # Remove stop words (simple list)
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for"}
        tokens = [t for t in tokens if t not in stop_words and len(t) > 1]
        
        return tokens
    
    def _calculate_score(self, entity_id: str, query_tokens: List[str]) -> float:
        """
        Calculate TF-IDF score for entity.
        
        Args:
            entity_id: Entity ID
            query_tokens: Query tokens
            
        Returns:
            Score
        """
        score = 0.0
        
        for token in query_tokens:
            if token in self.inverted_index and entity_id in self.inverted_index[token]:
                # TF: term frequency (simplified - just presence)
                tf = 1.0
                
                # IDF: inverse document frequency
                df = self.doc_frequencies.get(token, 1)
                idf = math.log((self.total_docs + 1) / (df + 1))
                
                score += tf * idf
        
        return score
    
    def get_stats(self) -> IndexStats:
        """Get index statistics."""
        total_entries = sum(len(docs) for docs in self.inverted_index.values())
        return IndexStats(
            name=self.definition.name,
            entry_count=total_entries,
            unique_keys=len(self.inverted_index),
            memory_bytes=total_entries * 50  # Rough estimate
        )


class SpatialIndex:
    """
    Spatial index for geospatial queries.
    
    Uses a simple grid-based index for 2D coordinates.
    """
    
    def __init__(self, property_name: str, grid_size: float = 1.0):
        """
        Initialize spatial index.
        
        Args:
            property_name: Property containing coordinates
            grid_size: Size of grid cells
        """
        self.definition = IndexDefinition(
            name=f"idx_spatial_{property_name}",
            index_type=IndexType.SPATIAL,
            properties=[property_name],
            options={"grid_size": grid_size}
        )
        self.property_name = property_name
        self.grid_size = grid_size
        
        # Grid: (grid_x, grid_y) -> set of entity IDs
        self.grid: Dict[Tuple[int, int], Set[str]] = {}
        
        # Entity coordinates for distance calculations
        self.coordinates: Dict[str, Tuple[float, float]] = {}
    
    def insert(self, coordinates: Tuple[float, float], entity_id: str):
        """
        Index coordinates for an entity.
        
        Args:
            coordinates: (lat, lon) or (x, y) coordinates
            entity_id: Entity ID
        """
        x, y = coordinates
        grid_cell = self._get_grid_cell(x, y)
        
        if grid_cell not in self.grid:
            self.grid[grid_cell] = set()
        
        self.grid[grid_cell].add(entity_id)
        self.coordinates[entity_id] = coordinates
    
    def search_radius(
        self,
        center: Tuple[float, float],
        radius: float
    ) -> List[Tuple[str, float]]:
        """
        Find entities within radius of center point.
        
        Args:
            center: Center coordinates
            radius: Search radius
            
        Returns:
            List of (entity_id, distance) tuples
        """
        cx, cy = center
        
        # Find grid cells to search
        cells = self._get_nearby_cells(cx, cy, radius)
        
        # Collect candidates
        candidates: Set[str] = set()
        for cell in cells:
            if cell in self.grid:
                candidates.update(self.grid[cell])
        
        # Calculate distances and filter
        results = []
        for entity_id in candidates:
            ex, ey = self.coordinates[entity_id]
            distance = self._calculate_distance(cx, cy, ex, ey)
            
            if distance <= radius:
                results.append((entity_id, distance))
        
        # Sort by distance
        results.sort(key=lambda x: x[1])
        return results
    
    def _get_grid_cell(self, x: float, y: float) -> Tuple[int, int]:
        """Get grid cell for coordinates."""
        grid_x = int(x / self.grid_size)
        grid_y = int(y / self.grid_size)
        return (grid_x, grid_y)
    
    def _get_nearby_cells(
        self,
        x: float,
        y: float,
        radius: float
    ) -> List[Tuple[int, int]]:
        """Get grid cells within radius."""
        cells = []
        
        # Calculate cell range
        cell_radius = int(math.ceil(radius / self.grid_size))
        center_cell = self._get_grid_cell(x, y)
        
        for dx in range(-cell_radius, cell_radius + 1):
            for dy in range(-cell_radius, cell_radius + 1):
                cell = (center_cell[0] + dx, center_cell[1] + dy)
                cells.append(cell)
        
        return cells
    
    def _calculate_distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """Calculate Euclidean distance."""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    
    def get_stats(self) -> IndexStats:
        """Get index statistics."""
        total_entries = len(self.coordinates)
        return IndexStats(
            name=self.definition.name,
            entry_count=total_entries,
            unique_keys=len(self.grid),
            memory_bytes=total_entries * 64  # Rough estimate
        )


class VectorIndex:
    """
    Vector index for similarity search on embeddings.
    
    Uses simple cosine similarity for now (can be extended to HNSW/FAISS).
    """
    
    def __init__(self, property_name: str, dimension: int):
        """
        Initialize vector index.
        
        Args:
            property_name: Property containing vectors
            dimension: Vector dimension
        """
        self.definition = IndexDefinition(
            name=f"idx_vector_{property_name}",
            index_type=IndexType.VECTOR,
            properties=[property_name],
            options={"dimension": dimension}
        )
        self.property_name = property_name
        self.dimension = dimension
        
        # Store vectors
        self.vectors: Dict[str, List[float]] = {}
    
    def insert(self, vector: List[float], entity_id: str):
        """
        Index vector for an entity.
        
        Args:
            vector: Embedding vector
            entity_id: Entity ID
        """
        if len(vector) != self.dimension:
            raise ValueError(f"Vector dimension mismatch: expected {self.dimension}, got {len(vector)}")
        
        self.vectors[entity_id] = vector
    
    def search(self, query_vector: List[float], k: int = 10) -> List[Tuple[str, float]]:
        """
        Find k nearest neighbors.
        
        Args:
            query_vector: Query vector
            k: Number of neighbors to return
            
        Returns:
            List of (entity_id, similarity) tuples
        """
        if len(query_vector) != self.dimension:
            raise ValueError(f"Vector dimension mismatch: expected {self.dimension}, got {len(query_vector)}")
        
        # Calculate similarities
        similarities = []
        for entity_id, vector in self.vectors.items():
            sim = self._cosine_similarity(query_vector, vector)
            similarities.append((entity_id, sim))
        
        # Sort by similarity and return top k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:k]
    
    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_stats(self) -> IndexStats:
        """Get index statistics."""
        return IndexStats(
            name=self.definition.name,
            entry_count=len(self.vectors),
            unique_keys=len(self.vectors),
            memory_bytes=len(self.vectors) * self.dimension * 8  # 8 bytes per float
        )


class RangeIndex(BTreeIndex):
    """
    Range index for efficient range queries.
    
    Extends B-tree index with range-specific optimizations.
    """
    
    def __init__(self, property_name: str, label: Optional[str] = None):
        """
        Initialize range index.
        
        Args:
            property_name: Property to index
            label: Optional label filter
        """
        definition = IndexDefinition(
            name=f"idx_range_{property_name}",
            index_type=IndexType.RANGE,
            properties=[property_name],
            label=label
        )
        # Initialize with larger branching factor for better range performance
        super().__init__(definition, max_keys=8)
        self.property_name = property_name
