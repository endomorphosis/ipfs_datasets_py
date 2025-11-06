#!/usr/bin/env python3
import pytest

from ipfs_datasets_py.web_archive import WebArchive

@pytest.fixture
def valid_kwargs():
    return {
        "valid_path": "/data/archives",
        "empty_path": "",
        "none_path": None,
    }

@pytest.mark.parametrize("scenario", ["valid_path", "empty_path", "none_path"])
class TestWebArchiveInitialization:
    """Test WebArchive initialization and configuration."""

    def test_init_creates_instance(self, scenario, valid_kwargs):
        """Given valid arguments, when initialized, then an instance is created."""
        kwarg = valid_kwargs[scenario]
        archive = WebArchive(storage_path=kwarg)
        assert isinstance(archive, WebArchive), f"Expected WebArchive instance but got {type(archive).__name__}"

    def test_init_with_storage_path_sets_storage_path_attribute(self, scenario, valid_kwargs):
        """Given valid storage_path, when initialized, then storage_path set."""
        kwarg = valid_kwargs[scenario]
        archive = WebArchive(storage_path=kwarg)

        assert archive.storage_path == kwarg, f"Expected {kwarg} but got {archive.storage_path}"

    def test_init_without_storage_path_initializes_archived_items(self, scenario, valid_kwargs):
        """Given no storage_path, when initialized, then archived_items empty dict."""
        kwarg = valid_kwargs[scenario]
        archive = WebArchive(storage_path=kwarg)
        
        assert archive.archived_items == {}, f"Expected empty dict but got {archive.archived_items}"

    def test_archived_items_attribute_is_dictionary(self, scenario, valid_kwargs):
        """Given WebArchive instance, when checking attribute, then archived_items is dict."""
        kwarg = valid_kwargs[scenario]
        archive = WebArchive(storage_path=kwarg)

        assert isinstance(archive.archived_items, dict), \
            f"Expected dict but got {type(archive.archived_items).__name__}"


@pytest.mark.parametrize("scenario,expected_value", 
    [("valid_path", "persistent"), ("empty_path", "memory_only"), ("none_path", "memory_only")]
)
def test_init_without_storage_path_sets_memory_only_mode(scenario, expected_value, valid_kwargs):
    """Given no storage_path, when initialized, then persistence_mode memory_only."""
    kwarg = valid_kwargs[scenario]
    archive = WebArchive(storage_path=kwarg)
    
    assert archive.persistence_mode == expected_value, f"Expected {expected_value} but got {archive.persistence_mode}"

@pytest.mark.parametrize("attribute_name", ["archived_items", "storage_path"])
def test_attributes_exist(attribute_name):
    """Given WebArchive instance, when checking attributes, then expected attributes exist."""
    archive = WebArchive()
    
    assert hasattr(archive, attribute_name), f"Expected {attribute_name} attribute but it does not exist"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
