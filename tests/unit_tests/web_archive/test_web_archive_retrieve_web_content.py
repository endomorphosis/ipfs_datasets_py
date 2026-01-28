#!/usr/bin/env python3
import pytest

from ipfs_datasets_py.web_archiving.web_archive import archive_web_content, retrieve_web_content


SUCCESS_STATUS = "success"
ERROR_STATUS = "error"
NONEXISTENT_ID = "archive_999"
EXAMPLE_URL = "https://example.com"
EXAMPLE_TITLE = "Example Page"
NOT_FOUND_MSG = "not found"
STATUS_ARCHIVED = "archived"


@pytest.fixture
def archived_id():
    """Create archived content and return its id for retrieval tests."""
    result = archive_web_content(EXAMPLE_URL, metadata={"title": EXAMPLE_TITLE})
    assert result["status"] == SUCCESS_STATUS
    return result["archive_id"]


@pytest.fixture
def success_mock_data_minimal():
    """Mock data for successful web content retrieval with minimal data."""
    return {"status": SUCCESS_STATUS, "data": {}}


@pytest.fixture
def success_mock_data_with_id():
    """Mock data for successful web content retrieval with ID."""
    return {"status": SUCCESS_STATUS, "data": {"id": ARCHIVE_ID}}


@pytest.fixture
def success_mock_data_with_url():
    """Mock data for successful web content retrieval with URL."""
    return {"status": SUCCESS_STATUS, "data": {"url": EXAMPLE_URL}}


@pytest.fixture
def success_mock_data_with_timestamp():
    """Mock data for successful web content retrieval with timestamp."""
    return {"status": SUCCESS_STATUS, "data": {"timestamp": EXAMPLE_TIMESTAMP}}


@pytest.fixture
def success_mock_data_with_metadata():
    """Mock data for successful web content retrieval with metadata."""
    return {"status": SUCCESS_STATUS, "data": {"metadata": {"title": EXAMPLE_TITLE}}}


@pytest.fixture
def success_mock_data_archived():
    """Mock data for successful web content retrieval with archived status."""
    return {"status": SUCCESS_STATUS, "data": {"status": "archived"}}


@pytest.fixture
def success_mock_data_complete():
    """Mock data for successful web content retrieval with all fields."""
    return {
        "status": SUCCESS_STATUS,
        "data": {
            "id": ARCHIVE_ID,
            "url": EXAMPLE_URL,
            "timestamp": EXAMPLE_TIMESTAMP,
            "metadata": {},
            "status": "archived"
        }
    }


class TestRetrieveWebContent:
    """Test retrieve_web_content function functionality."""

    def test_when_called_then_returns_dict(self):
        """
        GIVEN any archive_id
        WHEN retrieve_web_content is called
        THEN returns dict result
        """
        archive_result = archive_web_content(EXAMPLE_URL)
        result = retrieve_web_content(archive_result["archive_id"])
        assert isinstance(result, dict), f"Expected dict result, got {type(result)}"

    def test_when_valid_archive_then_success_status(self, archived_id):
        """
        GIVEN valid archive_id from previously archived content
        WHEN retrieve_web_content is called
        THEN return dict with status="success"
        """
        result = retrieve_web_content(archived_id)
        assert result["status"] == SUCCESS_STATUS, f"Expected status {SUCCESS_STATUS}, got {result['status']}"

    def test_when_nonexistent_id_then_error_status(self):
        """
        GIVEN nonexistent archive_id
        WHEN retrieve_web_content is called
        THEN return dict with status="error"
        """
        result = retrieve_web_content(NONEXISTENT_ID)
        assert result["status"] == ERROR_STATUS, f"Expected status {ERROR_STATUS}, got {result['status']}"

    @pytest.mark.parametrize("field", ["status", "data"])
    def test_when_success_then_contains_data(self, field):
        """
        GIVEN existing archived content
        WHEN retrieve_web_content succeeds
        THEN data dict contains required fields
        """
        archive_result = archive_web_content(EXAMPLE_URL)
        result = retrieve_web_content(archive_result["archive_id"])
        assert field in result, f"Expected 'data' key in result, got keys: {result.keys()}"

    @pytest.mark.parametrize("field", ["id", "url", "timestamp", "content", "metadata", "status"])
    def test_when_valid_archive_then_data_contains_required_fields(self, archived_id, field):
        """
        GIVEN valid archive_id from previously archived content
        WHEN retrieve_web_content is called
        THEN dict contains status, data keys
        """
        result = retrieve_web_content(archived_id)
        assert field in result["data"], f"Expected '{field}' key in result['data'], got keys: {result['data'].keys()}"

    def test_when_nonexistent_id_then_contains_message(self):
        """
        GIVEN nonexistent archive_id
        WHEN retrieve_web_content is called
        THEN return dict contains message about not found
        """
        result = retrieve_web_content(NONEXISTENT_ID)
        assert NOT_FOUND_MSG in result["message"].lower(), f"Expected '{NOT_FOUND_MSG}' in message, got {result['message']}"

    def test_when_nonexistent_id_then_no_data(self):
        """
        GIVEN nonexistent archive_id
        WHEN retrieve_web_content is called
        THEN no data key in return dict
        """
        result = retrieve_web_content(NONEXISTENT_ID)
        assert "data" not in result, f"Expected no 'data' key in error result, got keys: {result.keys()}"

    def test_when_success_then_no_message(self, archived_id):
        """
        GIVEN existing archived content
        WHEN retrieve_web_content succeeds
        THEN does not contain message key
        """
        result = retrieve_web_content(archived_id)
        assert "message" not in result, f"Expected no 'message' key in success result, got keys: {result.keys()}"


    def test_when_error_then_contains_message(self):
        """
        GIVEN nonexistent archive_id
        WHEN retrieve_web_content fails
        THEN message string describes error
        """
        result = retrieve_web_content(NONEXISTENT_ID)
        assert "message" in result, f"Expected 'message' key in error result, got keys: {result.keys()}"


    def test_when_success_then_data_contains_correct_values(self, archived_id):
        """Given archived content, retrieval echoes key fields."""
        result = retrieve_web_content(archived_id)
        assert result["data"]["id"] == archived_id
        assert result["data"]["url"] == EXAMPLE_URL
        assert result["data"]["status"] == STATUS_ARCHIVED

    def test_when_success_then_contains_metadata(self, archived_id):
        """
        GIVEN existing archived content with metadata
        WHEN retrieve_web_content is called
        THEN metadata is original metadata dict
        """
        expected_metadata = {"title": EXAMPLE_TITLE}
        result = retrieve_web_content(archived_id)
        assert result["data"]["metadata"] == expected_metadata, f"Expected metadata {expected_metadata}, got {result['data']['metadata']}"


if __name__ == "__main__":
    pytest.main([__file__])
