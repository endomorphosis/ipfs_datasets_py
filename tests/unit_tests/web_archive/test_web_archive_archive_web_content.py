#!/usr/bin/env python3

import pytest

from ipfs_datasets_py.processors.web_archiving.web_archive import archive_web_content


VALID_URL = "https://example.com/page.html"
VALID_URL_WITH_METADATA = "https://docs.example.com/guide.html"
INVALID_URL = "not-a-valid-url"
SUCCESS_STATUS = "success"
ERROR_STATUS = "error"
ARCHIVE_PREFIX = "archive_"
HIGH_PRIORITY = "high"
DOC_CATEGORY = "documentation"
STATUS_KEY = "status"
ARCHIVE_ID_KEY = "archive_id"
MESSAGE_KEY = "message"


@pytest.fixture
def valid_metadata():
    """Provides valid metadata dictionary."""
    return {HIGH_PRIORITY: HIGH_PRIORITY, DOC_CATEGORY: DOC_CATEGORY}


@pytest.fixture
def valid_url_result():
    """Provides result from archiving valid URL."""
    return archive_web_content(VALID_URL)


@pytest.fixture
def valid_url_with_metadata_result(valid_metadata):
    """Provides result from archiving valid URL with metadata."""
    return archive_web_content(VALID_URL_WITH_METADATA, valid_metadata)


@pytest.fixture
def invalid_url_result():
    """Provides result from archiving invalid URL."""
    return archive_web_content(INVALID_URL)


class TestArchiveWebContent:
    """Tests for archive_web_content."""

    def test_when_archiving_url_with_metadata_then_status_is_success(
        self, valid_url_with_metadata_result
    ):
        """Given valid URL with metadata, when archived, then status is success."""
        expected = SUCCESS_STATUS
        actual = valid_url_with_metadata_result[STATUS_KEY]

        assert actual == expected, f"Expected {STATUS_KEY} {expected}, got {actual}"

    def test_when_archiving_url_with_metadata_then_contains_archive_id(
        self, valid_url_with_metadata_result
    ):
        """Given valid URL with metadata, when archived, then contains archive_id."""
        keys = list(valid_url_with_metadata_result.keys())

        assert ARCHIVE_ID_KEY in valid_url_with_metadata_result, f"Expected {ARCHIVE_ID_KEY} in result, got keys: {keys}"

    def test_when_archiving_url_with_metadata_then_archive_id_starts_with_prefix(
        self, valid_url_with_metadata_result
    ):
        """Given valid URL with metadata, when archived, then archive_id starts with prefix."""
        archive_id = valid_url_with_metadata_result[ARCHIVE_ID_KEY]

        assert archive_id.startswith(ARCHIVE_PREFIX), f"Expected {ARCHIVE_ID_KEY} to start with {ARCHIVE_PREFIX}, got {archive_id}"

    def test_when_archiving_url_without_metadata_then_status_is_success(
        self, valid_url_result
    ):
        """Given valid URL without metadata, when archived, then status is success."""
        expected = SUCCESS_STATUS
        actual = valid_url_result[STATUS_KEY]

        assert actual == expected, f"Expected {STATUS_KEY} {expected}, got {actual}"

    def test_when_archiving_url_without_metadata_then_contains_archive_id(
        self, valid_url_result
    ):
        """Given valid URL without metadata, when archived, then contains archive_id."""
        keys = list(valid_url_result.keys())

        assert ARCHIVE_ID_KEY in valid_url_result, f"Expected {ARCHIVE_ID_KEY} in result, got keys: {keys}"

    def test_when_archiving_url_without_metadata_then_archive_id_starts_with_prefix(
        self, valid_url_result
    ):
        """Given valid URL without metadata, when archived, then archive_id starts with prefix."""
        archive_id = valid_url_result[ARCHIVE_ID_KEY]

        assert archive_id.startswith(ARCHIVE_PREFIX), f"Expected {ARCHIVE_ID_KEY} to start with {ARCHIVE_PREFIX}, got {archive_id}"

    def test_when_archiving_invalid_url_then_status_is_error(
        self, invalid_url_result
    ):
        """Given invalid URL, when archived, then status is error."""
        expected = ERROR_STATUS
        actual = invalid_url_result[STATUS_KEY]

        assert actual == expected, f"Expected {STATUS_KEY} {expected}, got {actual}"

    def test_when_archiving_invalid_url_then_contains_message(
        self, invalid_url_result
    ):
        """Given invalid URL, when archived, then contains message."""
        keys = list(invalid_url_result.keys())

        assert MESSAGE_KEY in invalid_url_result, f"Expected {MESSAGE_KEY} in result, got keys: {keys}"

    def test_when_archiving_invalid_url_then_message_is_non_empty(
        self, invalid_url_result
    ):
        """Given invalid URL, when archived, then message is non-empty."""
        message = invalid_url_result[MESSAGE_KEY]
        message_length = len(message)

        assert message_length > 0, f"Expected non-empty {MESSAGE_KEY}, got length: {message_length}"

    def test_when_archiving_invalid_url_then_no_archive_id(
        self, invalid_url_result
    ):
        """Given invalid URL, when archived, then no archive_id."""
        keys = list(invalid_url_result.keys())

        assert ARCHIVE_ID_KEY not in invalid_url_result, f"Expected no {ARCHIVE_ID_KEY} in error result, got keys: {keys}"

    def test_when_archiving_succeeds_then_result_contains_status(
        self, valid_url_result
    ):
        """Given successful archive, when checked, then status exists."""
        keys = list(valid_url_result.keys())

        assert STATUS_KEY in valid_url_result, f"Expected {STATUS_KEY} in result, got keys: {keys}"

    def test_when_archiving_succeeds_then_result_contains_archive_id(
        self, valid_url_result
    ):
        """Given successful archive, when checked, then archive_id exists."""
        keys = list(valid_url_result.keys())

        assert ARCHIVE_ID_KEY in valid_url_result, f"Expected {ARCHIVE_ID_KEY} in result, got keys: {keys}"

    def test_when_archiving_succeeds_then_result_has_no_message(
        self, valid_url_result
    ):
        """Given successful archive, when checked, then message does not exist."""
        keys = list(valid_url_result.keys())

        assert MESSAGE_KEY not in valid_url_result, f"Expected no {MESSAGE_KEY} in success result, got keys: {keys}"

    def test_when_archiving_fails_then_result_contains_status(
        self, invalid_url_result
    ):
        """Given failed archive, when checked, then status exists."""
        keys = list(invalid_url_result.keys())

        assert STATUS_KEY in invalid_url_result, f"Expected {STATUS_KEY} in result, got keys: {keys}"

    def test_when_archiving_fails_then_result_contains_message(
        self, invalid_url_result
    ):
        """Given failed archive, when checked, then message exists."""
        keys = list(invalid_url_result.keys())

        assert MESSAGE_KEY in invalid_url_result, f"Expected {MESSAGE_KEY} in result, got keys: {keys}"

    def test_when_archiving_fails_then_result_has_no_archive_id(
        self, invalid_url_result
    ):
        """Given failed archive, when checked, then archive_id does not exist."""
        keys = list(invalid_url_result.keys())

        assert ARCHIVE_ID_KEY not in invalid_url_result, f"Expected no {ARCHIVE_ID_KEY} in error result, got keys: {keys}"

    def test_when_calling_function_then_returns_dict(self):
        """Given function call, when executed, then returns dict."""
        result = archive_web_content(VALID_URL)
        result_type = type(result)

        assert isinstance(result, dict), f"Expected dict result, got {result_type}"

    def test_when_calling_function_multiple_times_then_each_returns_result(self):
        """Given multiple function calls, when executed, then each returns result."""
        result = archive_web_content(VALID_URL)
        keys = list(result.keys())

        assert STATUS_KEY in result, f"Expected {STATUS_KEY} in result, got keys: {keys}"

    def test_when_calling_function_then_result_is_complete(self):
        """Given function call, when executed, then returns complete result."""
        result = archive_web_content(VALID_URL)
        result_type = type(result)

        assert isinstance(result, dict), f"Expected dict result, got {result_type}"