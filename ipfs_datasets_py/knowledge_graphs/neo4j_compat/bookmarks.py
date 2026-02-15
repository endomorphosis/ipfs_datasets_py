"""
Bookmarks for Causal Consistency

Provides bookmark support for ensuring causal consistency across sessions,
compatible with Neo4j's bookmark system.

Bookmarks track the point in the transaction log and ensure that subsequent
queries see at least the data that was visible at the time the bookmark was created.

Features:
- Bookmark creation and tracking
- Causal consistency across sessions
- Bookmark serialization/deserialization
- Bookmark chaining for multiple transactions
"""

import logging
from typing import List, Optional, Set, Union
from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)


@dataclass
class Bookmark:
    """
    Represents a bookmark for causal consistency.
    
    A bookmark contains a transaction ID that marks a point in the
    transaction log. Subsequent queries can use this bookmark to ensure
    they see at least the data visible at that point.
    """
    
    transaction_id: str
    timestamp: float = field(default_factory=time.time)
    database: str = "default"
    
    def __str__(self) -> str:
        """String representation of bookmark."""
        return f"bookmark:v1:{self.database}:{self.transaction_id}"
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"Bookmark(tx={self.transaction_id}, db={self.database}, ts={self.timestamp})"
    
    def __hash__(self) -> int:
        """Hash for set operations."""
        return hash((self.transaction_id, self.database))
    
    def __eq__(self, other) -> bool:
        """Equality comparison."""
        if not isinstance(other, Bookmark):
            return False
        return (self.transaction_id == other.transaction_id and
                self.database == other.database)
    
    @classmethod
    def parse(cls, bookmark_str: str) -> Optional['Bookmark']:
        """
        Parse a bookmark string into a Bookmark object.
        
        Format: bookmark:v1:database:transaction_id
        
        Args:
            bookmark_str: String representation of bookmark
            
        Returns:
            Bookmark object or None if invalid
        """
        if not bookmark_str or not isinstance(bookmark_str, str):
            return None
        
        parts = bookmark_str.split(':')
        if len(parts) != 4 or parts[0] != 'bookmark' or parts[1] != 'v1':
            logger.warning("Invalid bookmark format: %s", bookmark_str)
            return None
        
        return cls(
            transaction_id=parts[3],
            database=parts[2]
        )
    
    def is_newer_than(self, other: 'Bookmark') -> bool:
        """
        Check if this bookmark is newer than another.
        
        Args:
            other: Other bookmark to compare
            
        Returns:
            True if this bookmark is newer
        """
        if self.database != other.database:
            return False
        
        # Simple comparison - in production would compare actual transaction sequence
        return self.timestamp > other.timestamp


class Bookmarks:
    """
    Collection of bookmarks for causal consistency.
    
    Manages multiple bookmarks and provides Neo4j-compatible API.
    """
    
    def __init__(self, bookmarks: Optional[Union[str, List[str], Set[str]]] = None):
        """
        Initialize bookmarks collection.
        
        Args:
            bookmarks: Single bookmark string, list of strings, or set of strings
        """
        self._bookmarks: Set[Bookmark] = set()
        
        if bookmarks:
            self.add(bookmarks)
    
    def add(self, bookmarks: Union[str, List[str], Set[str], Bookmark, 'Bookmarks']) -> None:
        """
        Add one or more bookmarks to the collection.
        
        Args:
            bookmarks: Bookmark(s) to add
        """
        if isinstance(bookmarks, str):
            bookmark = Bookmark.parse(bookmarks)
            if bookmark:
                self._bookmarks.add(bookmark)
        
        elif isinstance(bookmarks, Bookmark):
            self._bookmarks.add(bookmarks)
        
        elif isinstance(bookmarks, Bookmarks):
            self._bookmarks.update(bookmarks._bookmarks)
        
        elif isinstance(bookmarks, (list, set)):
            for bm in bookmarks:
                if isinstance(bm, str):
                    bookmark = Bookmark.parse(bm)
                    if bookmark:
                        self._bookmarks.add(bookmark)
                elif isinstance(bm, Bookmark):
                    self._bookmarks.add(bm)
    
    def get_all(self) -> List[str]:
        """
        Get all bookmarks as strings.
        
        Returns:
            List of bookmark strings
        """
        return [str(bm) for bm in self._bookmarks]
    
    def get_latest_by_database(self, database: str = "default") -> Optional[Bookmark]:
        """
        Get the latest bookmark for a specific database.
        
        Args:
            database: Database name
            
        Returns:
            Latest bookmark for the database or None
        """
        db_bookmarks = [bm for bm in self._bookmarks if bm.database == database]
        if not db_bookmarks:
            return None
        
        return max(db_bookmarks, key=lambda bm: bm.timestamp)
    
    def merge(self, other: 'Bookmarks') -> 'Bookmarks':
        """
        Merge with another Bookmarks collection.
        
        Args:
            other: Other bookmarks to merge
            
        Returns:
            New Bookmarks with merged bookmarks
        """
        merged = Bookmarks()
        merged._bookmarks = self._bookmarks.copy()
        merged._bookmarks.update(other._bookmarks)
        return merged
    
    def clear(self) -> None:
        """Clear all bookmarks."""
        self._bookmarks.clear()
    
    def is_empty(self) -> bool:
        """Check if bookmarks collection is empty."""
        return len(self._bookmarks) == 0
    
    def __len__(self) -> int:
        """Get number of bookmarks."""
        return len(self._bookmarks)
    
    def __bool__(self) -> bool:
        """Check if collection has any bookmarks."""
        return len(self._bookmarks) > 0
    
    def __str__(self) -> str:
        """String representation."""
        return f"Bookmarks({len(self._bookmarks)} bookmarks)"
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        bookmarks_str = ", ".join(str(bm) for bm in sorted(self._bookmarks, key=lambda bm: bm.timestamp))
        return f"Bookmarks([{bookmarks_str}])"
    
    def __iter__(self):
        """Iterate over bookmarks."""
        return iter(self._bookmarks)


def create_bookmark(transaction_id: str, database: str = "default") -> Bookmark:
    """
    Create a new bookmark.
    
    Args:
        transaction_id: Transaction ID
        database: Database name
        
    Returns:
        New Bookmark object
    """
    return Bookmark(
        transaction_id=transaction_id,
        database=database
    )


def create_bookmarks(bookmarks: Optional[Union[str, List[str], Set[str]]] = None) -> Bookmarks:
    """
    Create a Bookmarks collection.
    
    Args:
        bookmarks: Initial bookmark(s)
        
    Returns:
        New Bookmarks collection
    """
    return Bookmarks(bookmarks)
