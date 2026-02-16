"""
Unit tests for Bookmarks

Tests the bookmark implementation for causal consistency including:
- Bookmark creation and parsing
- Bookmarks collection management
- Bookmark comparison and merging
- Integration with sessions
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

import time
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.bookmarks import (
    Bookmark, Bookmarks, create_bookmark, create_bookmarks
)
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase


class TestBookmark:
    """Test Bookmark class."""
    
    def test_bookmark_creation(self):
        """Test bookmark can be created."""
        bookmark = Bookmark(
            transaction_id="tx_12345",
            database="default"
        )
        assert bookmark.transaction_id == "tx_12345"
        assert bookmark.database == "default"
        assert bookmark.timestamp > 0
    
    def test_bookmark_str_representation(self):
        """Test bookmark string representation."""
        bookmark = Bookmark(
            transaction_id="tx_12345",
            database="testdb"
        )
        bookmark_str = str(bookmark)
        assert bookmark_str == "bookmark:v1:testdb:tx_12345"
    
    def test_bookmark_parsing(self):
        """Test bookmark can be parsed from string."""
        bookmark_str = "bookmark:v1:mydb:tx_67890"
        bookmark = Bookmark.parse(bookmark_str)
        
        assert bookmark is not None
        assert bookmark.transaction_id == "tx_67890"
        assert bookmark.database == "mydb"
    
    def test_bookmark_parsing_invalid(self):
        """Test invalid bookmark string returns None."""
        assert Bookmark.parse("invalid") is None
        assert Bookmark.parse("bookmark:v2:db:tx") is None  # Wrong version
        assert Bookmark.parse("") is None
        assert Bookmark.parse(None) is None
    
    def test_bookmark_equality(self):
        """Test bookmark equality comparison."""
        bm1 = Bookmark("tx_1", database="db1")
        bm2 = Bookmark("tx_1", database="db1")
        bm3 = Bookmark("tx_2", database="db1")
        
        assert bm1 == bm2
        assert bm1 != bm3
    
    def test_bookmark_hash(self):
        """Test bookmark can be hashed for sets."""
        bm1 = Bookmark("tx_1", database="db1")
        bm2 = Bookmark("tx_1", database="db1")
        bm3 = Bookmark("tx_2", database="db1")
        
        bookmark_set = {bm1, bm2, bm3}
        assert len(bookmark_set) == 2  # bm1 and bm2 are same
    
    def test_bookmark_comparison(self):
        """Test bookmark timestamp comparison."""
        bm1 = Bookmark("tx_1", database="db1")
        time.sleep(0.01)
        bm2 = Bookmark("tx_2", database="db1")
        
        assert bm2.is_newer_than(bm1)
        assert not bm1.is_newer_than(bm2)


class TestBookmarks:
    """Test Bookmarks collection class."""
    
    def test_bookmarks_creation_empty(self):
        """Test empty bookmarks collection."""
        bookmarks = Bookmarks()
        assert len(bookmarks) == 0
        assert bookmarks.is_empty()
        assert not bookmarks
    
    def test_bookmarks_creation_with_string(self):
        """Test bookmarks creation with single string."""
        bookmarks = Bookmarks("bookmark:v1:db:tx_123")
        assert len(bookmarks) == 1
        assert not bookmarks.is_empty()
        assert bookmarks
    
    def test_bookmarks_creation_with_list(self):
        """Test bookmarks creation with list of strings."""
        bookmarks = Bookmarks([
            "bookmark:v1:db:tx_123",
            "bookmark:v1:db:tx_456"
        ])
        assert len(bookmarks) == 2
    
    def test_bookmarks_add_string(self):
        """Test adding bookmark as string."""
        bookmarks = Bookmarks()
        bookmarks.add("bookmark:v1:db:tx_123")
        assert len(bookmarks) == 1
    
    def test_bookmarks_add_bookmark_object(self):
        """Test adding Bookmark object."""
        bookmarks = Bookmarks()
        bookmark = Bookmark("tx_123", database="db1")
        bookmarks.add(bookmark)
        assert len(bookmarks) == 1
    
    def test_bookmarks_add_list(self):
        """Test adding list of bookmarks."""
        bookmarks = Bookmarks()
        bookmarks.add([
            "bookmark:v1:db:tx_1",
            "bookmark:v1:db:tx_2",
            "bookmark:v1:db:tx_3"
        ])
        assert len(bookmarks) == 3
    
    def test_bookmarks_get_all(self):
        """Test getting all bookmarks as strings."""
        bookmarks = Bookmarks([
            "bookmark:v1:db:tx_1",
            "bookmark:v1:db:tx_2"
        ])
        all_bookmarks = bookmarks.get_all()
        assert len(all_bookmarks) == 2
        assert all(isinstance(b, str) for b in all_bookmarks)
    
    def test_bookmarks_get_latest_by_database(self):
        """Test getting latest bookmark for database."""
        bookmarks = Bookmarks()
        
        bm1 = Bookmark("tx_1", database="db1")
        time.sleep(0.01)
        bm2 = Bookmark("tx_2", database="db1")
        time.sleep(0.01)
        bm3 = Bookmark("tx_3", database="db2")
        
        bookmarks.add(bm1)
        bookmarks.add(bm2)
        bookmarks.add(bm3)
        
        latest_db1 = bookmarks.get_latest_by_database("db1")
        assert latest_db1 is not None
        assert latest_db1.transaction_id == "tx_2"
        
        latest_db2 = bookmarks.get_latest_by_database("db2")
        assert latest_db2 is not None
        assert latest_db2.transaction_id == "tx_3"
    
    def test_bookmarks_merge(self):
        """Test merging bookmark collections."""
        bm1 = Bookmarks(["bookmark:v1:db:tx_1", "bookmark:v1:db:tx_2"])
        bm2 = Bookmarks(["bookmark:v1:db:tx_3", "bookmark:v1:db:tx_4"])
        
        merged = bm1.merge(bm2)
        assert len(merged) == 4
        # Original collections unchanged
        assert len(bm1) == 2
        assert len(bm2) == 2
    
    def test_bookmarks_clear(self):
        """Test clearing bookmarks."""
        bookmarks = Bookmarks(["bookmark:v1:db:tx_1", "bookmark:v1:db:tx_2"])
        assert len(bookmarks) == 2
        
        bookmarks.clear()
        assert len(bookmarks) == 0
        assert bookmarks.is_empty()
    
    def test_bookmarks_iteration(self):
        """Test iterating over bookmarks."""
        bookmarks = Bookmarks([
            "bookmark:v1:db:tx_1",
            "bookmark:v1:db:tx_2"
        ])
        
        count = 0
        for bm in bookmarks:
            assert isinstance(bm, Bookmark)
            count += 1
        
        assert count == 2
    
    def test_bookmarks_duplicate_handling(self):
        """Test duplicate bookmarks are not added twice."""
        bookmarks = Bookmarks()
        bookmarks.add("bookmark:v1:db:tx_123")
        bookmarks.add("bookmark:v1:db:tx_123")  # Duplicate
        
        assert len(bookmarks) == 1


class TestBookmarksHelpers:
    """Test helper functions."""
    
    def test_create_bookmark_helper(self):
        """Test create_bookmark helper."""
        bookmark = create_bookmark("tx_123", database="testdb")
        assert isinstance(bookmark, Bookmark)
        assert bookmark.transaction_id == "tx_123"
        assert bookmark.database == "testdb"
    
    def test_create_bookmarks_helper_empty(self):
        """Test create_bookmarks helper with no args."""
        bookmarks = create_bookmarks()
        assert isinstance(bookmarks, Bookmarks)
        assert len(bookmarks) == 0
    
    def test_create_bookmarks_helper_with_list(self):
        """Test create_bookmarks helper with list."""
        bookmarks = create_bookmarks([
            "bookmark:v1:db:tx_1",
            "bookmark:v1:db:tx_2"
        ])
        assert isinstance(bookmarks, Bookmarks)
        assert len(bookmarks) == 2


class TestBookmarksIntegration:
    """Test bookmarks integration with driver and session."""
    
    def test_session_bookmarks_initialization(self):
        """Test session can be created with bookmarks."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        
        # Create session with bookmarks
        bookmarks = ["bookmark:v1:default:tx_123"]
        session = driver.session(bookmarks=bookmarks)
        
        assert session is not None
        assert len(session._bookmarks) == 1
        
        session.close()
        driver.close()
    
    def test_session_last_bookmark(self):
        """Test session tracks last bookmark."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        session = driver.session()
        
        # Initially no bookmark
        assert session.last_bookmark() is None
        
        # Update bookmark (simulating transaction)
        session._update_bookmark("tx_456")
        
        # Should have last bookmark
        last_bm = session.last_bookmark()
        assert last_bm is not None
        assert "tx_456" in last_bm
        
        session.close()
        driver.close()
    
    def test_session_last_bookmarks(self):
        """Test session returns all bookmarks."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        
        initial_bookmarks = ["bookmark:v1:default:tx_100"]
        session = driver.session(bookmarks=initial_bookmarks)
        
        # Update with new bookmark
        session._update_bookmark("tx_200")
        
        all_bookmarks = session.last_bookmarks()
        assert len(all_bookmarks) >= 2  # At least initial + new
        
        session.close()
        driver.close()
    
    def test_bookmark_causal_chain(self):
        """Test bookmarks can be chained across sessions."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        
        # Session 1: Create some data
        session1 = driver.session()
        session1._update_bookmark("tx_1")
        bookmark1 = session1.last_bookmark()
        session1.close()
        
        # Session 2: Use bookmark from session 1
        session2 = driver.session(bookmarks=[bookmark1])
        session2._update_bookmark("tx_2")
        bookmark2 = session2.last_bookmark()
        session2.close()
        
        # Session 3: Use bookmark from session 2
        session3 = driver.session(bookmarks=[bookmark2])
        bookmarks = session3.last_bookmarks()
        
        # Should have at least the latest bookmark
        # Note: We keep only the latest bookmark per database for efficiency
        assert len(bookmarks) >= 1
        assert "tx_2" in bookmarks[0]  # Latest bookmark should be from tx_2
        
        session3.close()
        driver.close()


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
