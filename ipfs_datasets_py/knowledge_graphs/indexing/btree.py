"""
B-tree Index Implementation

This module provides B-tree indexes for fast property lookups.
"""

import bisect
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import IndexDefinition, IndexEntry, IndexStats, IndexType

logger = logging.getLogger(__name__)


class BTreeNode:
    """
    A node in the B-tree.
    
    Attributes:
        keys: Sorted list of keys
        children: Child nodes (for internal nodes)
        entries: Index entries (for leaf nodes)
        is_leaf: Whether this is a leaf node
    """
    
    def __init__(self, is_leaf: bool = True, max_keys: int = 4):
        """
        Initialize a B-tree node.
        
        Args:
            is_leaf: Whether this is a leaf node
            max_keys: Maximum number of keys per node
        """
        self.keys: List[Any] = []
        self.children: List["BTreeNode"] = []
        self.entries: Dict[Any, List[IndexEntry]] = {}
        self.is_leaf = is_leaf
        self.max_keys = max_keys
    
    def is_full(self) -> bool:
        """Check if node is full."""
        return len(self.keys) >= self.max_keys
    
    def insert_non_full(self, key: Any, entry: IndexEntry):
        """
        Insert into a non-full node.
        
        Args:
            key: Key to insert
            entry: Entry to insert
        """
        i = bisect.bisect_left(self.keys, key)
        
        if self.is_leaf:
            # Insert into leaf node
            if i < len(self.keys) and self.keys[i] == key:
                # Key exists - add to entries list
                if key not in self.entries:
                    self.entries[key] = []
                self.entries[key].append(entry)
            else:
                # New key
                self.keys.insert(i, key)
                self.entries[key] = [entry]
        else:
            # Recurse to child
            if self.children[i].is_full():
                self._split_child(i)
                if key > self.keys[i]:
                    i += 1
            self.children[i].insert_non_full(key, entry)
    
    def _split_child(self, index: int):
        """
        Split a full child node in the B-tree to maintain balance.

        When a child node reaches maximum capacity (max_keys), it must be split to
        maintain the B-tree invariant that all nodes are at most max_keys full.
        This operation promotes the middle key to the parent and creates a new sibling.

        Algorithm:
        1. Create a new sibling node with same properties (leaf/internal)
        2. Find the middle key (mid = max_keys // 2)
        3. Move second half of keys (mid+1 onwards) to new sibling
        4. If leaf node: move corresponding entries
        5. If internal node: move corresponding children pointers
        6. Promote middle key to parent at the specified index
        7. Insert new sibling as next child after promoted key

        Complexity: O(t) where t is the minimum degree of the B-tree

        Args:
            index: Position in parent's children array where the full child resides
                   (0-based index, must be valid index into self.children)

        Example:
            Consider a B-tree node with max_keys=5 and a full child at index 1:
            
            Parent: [10, 20, 30]
            Child[1]: [11, 12, 13, 14, 15]  # Full! (5 keys)
            
            After _split_child(1):
            
            Parent: [10, 13, 20, 30]  # Middle key 13 promoted
            Child[1]: [11, 12]        # First half
            Child[2]: [14, 15]        # Second half (new sibling)

        Note:
            This method assumes the parent node has space for an additional key.
            The caller (typically insert_non_full) must ensure parent is not full.
        """
        full_child = self.children[index]
        new_child = BTreeNode(is_leaf=full_child.is_leaf, max_keys=full_child.max_keys)
        
        mid = full_child.max_keys // 2
        
        # Move second half of keys to new child
        new_child.keys = full_child.keys[mid + 1:]
        full_child.keys = full_child.keys[:mid]
        
        if full_child.is_leaf:
            # Move entries
            for key in new_child.keys:
                new_child.entries[key] = full_child.entries[key]
                del full_child.entries[key]
        else:
            # Move children
            new_child.children = full_child.children[mid + 1:]
            full_child.children = full_child.children[:mid + 1]
        
        # Insert middle key into parent
        mid_key = full_child.keys[mid] if full_child.is_leaf else full_child.keys[mid]
        self.keys.insert(index, mid_key)
        self.children.insert(index + 1, new_child)
    
    def search(self, key: Any) -> List[IndexEntry]:
        """
        Search for a key in the tree.
        
        Args:
            key: Key to search for
            
        Returns:
            List of matching index entries
        """
        i = bisect.bisect_left(self.keys, key)
        
        if self.is_leaf:
            if i < len(self.keys) and self.keys[i] == key:
                return self.entries.get(key, [])
            return []
        else:
            # Recurse to child
            if i < len(self.keys) and self.keys[i] == key:
                # Found in internal node, go to right child
                return self.children[i + 1].search(key)
            else:
                return self.children[i].search(key)
    
    def range_search(self, start: Any, end: Any) -> List[IndexEntry]:
        """
        Search for keys in a range.
        
        Args:
            start: Start of range (inclusive)
            end: End of range (inclusive)
            
        Returns:
            List of matching index entries
        """
        result = []
        
        if self.is_leaf:
            for key in self.keys:
                if start <= key <= end:
                    result.extend(self.entries.get(key, []))
        else:
            for i, key in enumerate(self.keys):
                if key < start:
                    continue
                elif key > end:
                    break
                else:
                    # Key in range - check both sides
                    result.extend(self.children[i].range_search(start, end))
                    result.extend(self.children[i + 1].range_search(start, end))
                    break
            else:
                # Check last child
                if len(self.children) > 0:
                    result.extend(self.children[-1].range_search(start, end))
        
        return result


class BTreeIndex:
    """
    B-tree index for fast property lookups.
    
    Supports:
    - Point lookups (exact match)
    - Range queries
    - Multiple values per key
    """
    
    def __init__(self, definition: IndexDefinition, max_keys: int = 4):
        """
        Initialize B-tree index.
        
        Args:
            definition: Index definition
            max_keys: Maximum keys per node (branching factor)
        """
        self.definition = definition
        self.max_keys = max_keys
        self.root = BTreeNode(is_leaf=True, max_keys=max_keys)
        self._entry_count = 0
        self._unique_keys: Set[Any] = set()
    
    def insert(self, key: Any, entity_id: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Insert an entry into the index.
        
        Args:
            key: Key value
            entity_id: Entity ID
            metadata: Optional metadata
        """
        entry = IndexEntry(key=key, entity_id=entity_id, metadata=metadata or {})
        
        if self.root.is_full():
            # Create new root
            old_root = self.root
            self.root = BTreeNode(is_leaf=False, max_keys=self.max_keys)
            self.root.children.append(old_root)
            self.root._split_child(0)
        
        self.root.insert_non_full(key, entry)
        self._entry_count += 1
        self._unique_keys.add(key)
    
    def search(self, key: Any) -> List[str]:
        """
        Search for entities with the given key.
        
        Args:
            key: Key to search for
            
        Returns:
            List of entity IDs
        """
        entries = self.root.search(key)
        return [entry.entity_id for entry in entries]
    
    def range_search(self, start: Any, end: Any) -> List[str]:
        """
        Search for entities with keys in range.
        
        Args:
            start: Start of range (inclusive)
            end: End of range (inclusive)
            
        Returns:
            List of entity IDs
        """
        entries = self.root.range_search(start, end)
        return list(set(entry.entity_id for entry in entries))
    
    def get_stats(self) -> IndexStats:
        """
        Get index statistics.
        
        Returns:
            Index statistics
        """
        return IndexStats(
            name=self.definition.name,
            entry_count=self._entry_count,
            unique_keys=len(self._unique_keys),
            memory_bytes=self._estimate_memory()
        )
    
    def _estimate_memory(self) -> int:
        """Estimate memory usage in bytes."""
        # Rough estimate: 100 bytes per entry
        return self._entry_count * 100


class PropertyIndex(BTreeIndex):
    """Index on a single property."""
    
    def __init__(self, property_name: str, label: Optional[str] = None):
        """
        Initialize property index.
        
        Args:
            property_name: Name of property to index
            label: Optional label filter
        """
        definition = IndexDefinition(
            name=f"idx_{property_name}",
            index_type=IndexType.PROPERTY,
            properties=[property_name],
            label=label
        )
        super().__init__(definition)
        self.property_name = property_name


class LabelIndex(BTreeIndex):
    """Index on entity labels/types."""
    
    def __init__(self):
        """Initialize label index."""
        definition = IndexDefinition(
            name="idx_labels",
            index_type=IndexType.LABEL,
            properties=["@type"]
        )
        super().__init__(definition)


class CompositeIndex(BTreeIndex):
    """Index on multiple properties."""
    
    def __init__(self, property_names: List[str], label: Optional[str] = None):
        """
        Initialize composite index.
        
        Args:
            property_names: Names of properties to index
            label: Optional label filter
        """
        definition = IndexDefinition(
            name=f"idx_composite_{'_'.join(property_names)}",
            index_type=IndexType.COMPOSITE,
            properties=property_names,
            label=label
        )
        super().__init__(definition)
        self.property_names = property_names
    
    def insert_composite(self, values: List[Any], entity_id: str):
        """
        Insert with composite key.
        
        Args:
            values: List of property values (in same order as property_names)
            entity_id: Entity ID
        """
        # Create composite key as tuple
        composite_key = tuple(values)
        self.insert(composite_key, entity_id)
    
    def search_composite(self, values: List[Any]) -> List[str]:
        """
        Search with composite key.
        
        Args:
            values: List of property values
            
        Returns:
            List of entity IDs
        """
        composite_key = tuple(values)
        return self.search(composite_key)
