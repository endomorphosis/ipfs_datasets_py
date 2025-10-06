import pytest

from ipfs_datasets_py.web_archive import WebArchive


class TestWebArchiveInitialization:
    """Test WebArchive initialization and configuration."""

    def test_init_with_storage_path_creates_instance(self):
        """
        GIVEN valid storage_path string "/data/archives"
        WHEN WebArchive is initialized
        THEN expect:
            - Instance created successfully
        """
        # GIVEN
        storage_path = "/data/archives"
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert archive is not None
        assert isinstance(archive, WebArchive)

    def test_init_with_storage_path_sets_storage_path_attribute(self):
        """
        GIVEN valid storage_path string "/data/archives"
        WHEN WebArchive is initialized
        THEN expect:
            - storage_path attribute is set to "/data/archives"
        """
        # GIVEN
        storage_path = "/data/archives"
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert archive.storage_path == storage_path

    def test_init_with_storage_path_initializes_archived_items(self):
        """
        GIVEN valid storage_path string "/data/archives"
        WHEN WebArchive is initialized
        THEN expect:
            - archived_items attribute is initialized as empty dict
        """
        # GIVEN
        storage_path = "/data/archives"
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert hasattr(archive, 'archived_items')
        assert archive.archived_items == {}
        assert isinstance(archive.archived_items, dict)

    def test_init_with_storage_path_sets_persistent_mode(self):
        """
        GIVEN valid storage_path string "/data/archives"
        WHEN WebArchive is initialized
        THEN expect:
            - persistence_mode is "persistent"
        """
        # GIVEN
        storage_path = "/data/archives"
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert hasattr(archive, 'persistence_mode')
        assert archive.persistence_mode == "persistent"

    def test_init_without_storage_path_creates_instance(self):
        """
        GIVEN storage_path is None (default)
        WHEN WebArchive is initialized
        THEN expect:
            - Instance created successfully
        """
        # GIVEN - use default None storage_path
        
        # WHEN
        archive = WebArchive()
        
        # THEN
        assert archive is not None
        assert isinstance(archive, WebArchive)

    def test_init_without_storage_path_sets_storage_path_none(self):
        """
        GIVEN storage_path is None (default)
        WHEN WebArchive is initialized
        THEN expect:
            - storage_path attribute is None
        """
        # GIVEN - use default None storage_path
        
        # WHEN
        archive = WebArchive()
        
        # THEN
        assert archive.storage_path is None

    def test_init_without_storage_path_initializes_archived_items(self):
        """
        GIVEN storage_path is None (default)
        WHEN WebArchive is initialized
        THEN expect:
            - archived_items attribute is initialized as empty dict
        """
        # GIVEN - use default None storage_path
        
        # WHEN
        archive = WebArchive()
        
        # THEN
        assert hasattr(archive, 'archived_items')
        assert archive.archived_items == {}
        assert isinstance(archive.archived_items, dict)

    def test_init_without_storage_path_sets_memory_only_mode(self):
        """
        GIVEN storage_path is None (default)
        WHEN WebArchive is initialized
        THEN expect:
            - persistence_mode is "memory_only"
        """
        # GIVEN - use default None storage_path
        
        # WHEN
        archive = WebArchive()
        
        # THEN
        assert hasattr(archive, 'persistence_mode')
        assert archive.persistence_mode == "memory_only"

    def test_init_with_empty_string_storage_path_creates_instance(self):
        """
        GIVEN storage_path is empty string ""
        WHEN WebArchive is initialized
        THEN expect:
            - Instance created successfully
        """
        # GIVEN
        storage_path = ""
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert archive is not None
        assert isinstance(archive, WebArchive)

    def test_init_with_empty_string_storage_path_sets_attribute(self):
        """
        GIVEN storage_path is empty string ""
        WHEN WebArchive is initialized
        THEN expect:
            - storage_path attribute is set to ""
        """
        # GIVEN
        storage_path = ""
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert archive.storage_path == ""

    def test_init_with_empty_string_storage_path_initializes_archived_items(self):
        """
        GIVEN storage_path is empty string ""
        WHEN WebArchive is initialized
        THEN expect:
            - archived_items attribute is initialized as empty dict
        """
        # GIVEN
        storage_path = ""
        
        # WHEN
        archive = WebArchive(storage_path=storage_path)
        
        # THEN
        assert hasattr(archive, 'archived_items')
        assert archive.archived_items == {}
        assert isinstance(archive.archived_items, dict)

    def test_archived_items_attribute_exists(self):
        """
        GIVEN WebArchive instance
        WHEN checking for archived_items attribute
        THEN expect:
            - archived_items attribute exists
        """
        # GIVEN
        archive = WebArchive()
        
        # WHEN & THEN
        assert hasattr(archive, 'archived_items')

    def test_archived_items_attribute_is_dictionary(self):
        """
        GIVEN WebArchive instance
        WHEN checking for archived_items attribute
        THEN expect:
            - archived_items is a dictionary
        """
        # GIVEN
        archive = WebArchive()
        
        # WHEN & THEN
        assert isinstance(archive.archived_items, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])