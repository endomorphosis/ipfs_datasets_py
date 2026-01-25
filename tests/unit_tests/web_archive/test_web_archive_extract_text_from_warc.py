#!/usr/bin/env python3

import pytest

from ipfs_datasets_py.web_archive import WebArchiveProcessor


@pytest.fixture
def processor():
    return WebArchiveProcessor()


@pytest.fixture
def warc_path(tmp_path):
    """Create a small WARC-like file with a single HTML record."""
    path = tmp_path / "snapshot.warc"
    path.write_text(
        """WARC/1.0\r\n"
        "WARC-Type: response\r\n"
        "WARC-Target-URI: http://example.com\r\n"
        "Content-Type: text/html\r\n"
        "WARC-Date: 2023-01-01T00:00:00Z\r\n"
        "\r\n"
        "<html><body><p>Test content</p></body></html>\r\n""",
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def empty_warc_path(tmp_path):
    path = tmp_path / "empty.warc"
    path.write_text("", encoding="utf-8")
    return str(path)


@pytest.fixture
def nonexistent_warc_path(tmp_path):
    return str(tmp_path / "does_not_exist.warc")


class TestWebArchiveProcessorExtractTextFromWarc:
    """Test WebArchiveProcessor.extract_text_from_warc method functionality."""

    def test_when_called_with_valid_path_then_returns_list(
        self, processor, warc_path):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN returns list type
        """
        result = processor.extract_text_from_warc(warc_path)
        assert isinstance(result, list), f"Expected list, got {type(result).__name__}"

    def test_when_called_with_valid_path_then_records_have_four_fields(
        self, processor, warc_path):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN each record has four fields
        """
        result = processor.extract_text_from_warc(warc_path)
        expected = 4
        actual = len(result[0])
        assert actual == expected, f"Expected {expected} fields, got {actual}"

    def test_when_called_with_valid_path_then_extracts_text_from_html(
        self, processor, warc_path):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN extracted text contains no HTML tags
        """
        result = processor.extract_text_from_warc(warc_path)
        text = result[0]['text']
        tag_sign = '<'
        assert tag_sign not in text, f"Found HTML tag '{tag_sign}' in {text}"

    def test_when_called_with_nonexistent_then_message_contains_not_found(
        self, processor, nonexistent_warc_path):
        """
        GIVEN WebArchiveProcessor instance and nonexistent file path
        WHEN extract_text_from_warc raises FileNotFoundError
        THEN message contains not found phrase
        """
        with pytest.raises(FileNotFoundError, match=r"not found"):
            processor.extract_text_from_warc(nonexistent_warc_path)

    @pytest.mark.parametrize("field", ['uri','text','content_type','timestamp',])
    def test_when_called_with_valid_path_then_records_have_expected_fields(
        self, processor, warc_path, field):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN each record contains the expected field
        """
        result = processor.extract_text_from_warc(warc_path)
        assert field in result[0], f"Expected {field} in {result[0]}"

    def test_when_called_with_empty_file_then_returns_empty_list(
        self, processor, empty_warc_path):
        """
        GIVEN WebArchiveProcessor instance and empty WARC file path
        WHEN extract_text_from_warc is called with path
        THEN returns empty list with length zero
        """
        result = processor.extract_text_from_warc(empty_warc_path)
        assert len(result) == 0, f"Expected 0, got {len(result)}"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])