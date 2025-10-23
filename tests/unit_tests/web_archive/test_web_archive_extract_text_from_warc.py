#!/usr/bin/env python3

import pytest
from ipfs_datasets_py.web_archive import WebArchiveProcessor


@pytest.fixture
def constants():
    return {
        'WARC_PATH': "/data/snapshot.warc",
        'BAD_PATH': "/nonexistent/file.warc",
        'ZERO': 0,
        'FOUR': 4,
    }


@pytest.fixture
def processor():
    return WebArchiveProcessor()


class TestWebArchiveProcessorExtractTextFromWarc:
    """Test WebArchiveProcessor.extract_text_from_warc method functionality."""

    def test_when_called_with_valid_path_then_returns_list(
        self, processor, constants):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN returns list type
        """
        path = constants['WARC_PATH']
        result = processor.extract_text_from_warc(path)
        assert isinstance(result, list), f"Expected list, got {type(result).__name__}"

    def test_when_called_with_valid_path_then_records_have_four_fields(
        self, processor, constants):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN each record has four fields
        """
        path = constants['WARC_PATH']
        result = processor.extract_text_from_warc(path)
        expected = constants['FOUR']
        actual = len(result[0])
        assert actual == expected, f"Expected {expected} fields, got {actual}"

    def test_when_called_with_valid_path_then_extracts_text_from_html(
        self, processor, constants):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN extracted text contains no HTML tags
        """
        path = constants['WARC_PATH']
        result = processor.extract_text_from_warc(path)
        text = result[0]['text']
        tag_sign = '<'
        assert tag_sign not in text, f"Found HTML tag '{tag_sign}' in {text}"

    def test_when_called_with_nonexistent_then_message_contains_not_found(
        self, processor, constants):
        """
        GIVEN WebArchiveProcessor instance and nonexistent file path
        WHEN extract_text_from_warc raises FileNotFoundError
        THEN message contains not found phrase
        """
        path = constants['BAD_PATH']
        with pytest.raises(FileNotFoundError, match=r'not found') as exc:
            processor.extract_text_from_warc(path)

    @pytest.mark.parametrize("field", ['uri','text','content_type','timestamp',])
    def test_when_called_with_valid_path_then_records_have_expected_fields(
        self, processor, constants, field):
        """
        GIVEN WebArchiveProcessor instance and valid WARC file path
        WHEN extract_text_from_warc is called with path
        THEN each record contains the expected field
        """
        path = constants['WARC_PATH']
        result = processor.extract_text_from_warc(path)
        assert field in result[0], f"Expected {field} in {result[0]}"

    def test_when_called_with_empty_file_then_returns_empty_list(
        self, processor, constants):
        """
        GIVEN WebArchiveProcessor instance and empty WARC file path
        WHEN extract_text_from_warc is called with path
        THEN returns empty list with length zero
        """
        path = constants['WARC_PATH']
        result = processor.extract_text_from_warc(path)
        expected = constants['ZERO']
        assert len(result) == expected, f"Expected {expected}, got {len(result)}"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])