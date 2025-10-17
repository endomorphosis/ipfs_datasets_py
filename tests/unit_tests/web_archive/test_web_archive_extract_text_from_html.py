#!/usr/bin/env python3
"""Test suite for WebArchiveProcessor.extract_text_from_html method."""

import pytest
from ipfs_datasets_py.web_archive import WebArchiveProcessor

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
KEY_STATUS = "status"
KEY_TEXT = "text"
KEY_LENGTH = "length"
KEY_MESSAGE = "message"
EMPTY_STRING = ""
ZERO = 0


@pytest.fixture
def unwanted_content_test_cases():
    """Provides test cases for unwanted content removal."""
    return {
        "markup_tags_removed": {
            "html_input": '<html><body><h1>Hello</h1><p><b>bold</b></p></body></html>',
            "unwanted_substring": "<b>",
        },
        "script_content_removed": {
            "html_input": "<html><body><script>alert('x');</script><p>Visible</p></body></html>",
            "unwanted_substring": "alert",
        },
        "script_variables_removed": {
            "html_input": "<html><body><script>var x='test';</script><p>Text</p></body></html>",
            "unwanted_substring": "var x",
        },
        "script_functions_removed": {
            "html_input": "<html><body><script>function f(){}</script><p>Content</p></body></html>",
            "unwanted_substring": "function",
        },
        "excess_spaces_collapsed": {
            "html_input": "<html><body><p>Multiple    spaces</p></body></html>",
            "unwanted_substring": "    ",
        },
        "excess_newlines_normalized": {
            "html_input": "<html><body><p>Text\n\n\nwith\tlines</p></body></html>",
            "unwanted_substring": "\n\n\n",
        },
    }


@pytest.fixture
def processor():
    """Set up test fixtures."""
    return WebArchiveProcessor()


class TestWebArchiveProcessorExtractTextFromHtml:
    """Test WebArchiveProcessor.extract_text_from_html method functionality."""

    def test_when_extracting_from_valid_html_then_status_is_success(self, processor):
        """Given valid HTML, when extracting text, then status is success."""
        html = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert result[KEY_STATUS] == STATUS_SUCCESS, f"Expected status {STATUS_SUCCESS}, got {result.get(KEY_STATUS)}"

    @pytest.mark.parametrize(
        "test_id",
        ["markup_tags_removed", "script_content_removed", "script_variables_removed",
         "script_functions_removed", "excess_spaces_collapsed", "excess_newlines_normalized"],
    )
    def test_when_extracting_from_html_then_unwanted_content_is_removed(
        self, processor, unwanted_content_test_cases, test_id
    ):
        """
        Given various HTML inputs, when extracting text, then unwanted content is removed.
        """
        html_input, unwanted_substring = unwanted_content_test_cases[test_id].values()

        result = processor.extract_text_from_html(html_input)

        assert unwanted_substring not in result[KEY_TEXT], \
            f"Test '{test_id}': Unwanted content '{unwanted_substring}' found in: {result[KEY_TEXT]}"


    def test_when_extracting_from_html_with_scripts_then_only_visible_text_remains(
        self, processor
    ):
        """Given HTML with scripts, when extracting, then only visible text remains."""
        html = "<html><body><script>hidden</script><p>visible</p></body></html>"
        result = processor.extract_text_from_html(html)
        assert "visible" in result[KEY_TEXT], f"Expected visible text, got: {result[KEY_TEXT]}"


    def test_when_extracting_from_valid_html_then_length_is_provided(self, processor):
        """Given valid HTML, when extracting text, then length is provided."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)
        assert KEY_LENGTH in result, f"Expected {KEY_LENGTH} key in result: {result.keys()}"

    def test_when_extracting_from_html_with_messy_whitespace_then_output_is_clean(
        self, processor
    ):
        """Given HTML with messy whitespace, when extracting, then output is clean."""
        html = "<html><body><p>  Leading and trailing  </p></body></html>"
        result = processor.extract_text_from_html(html)
        assert result[KEY_TEXT].strip() == result[KEY_TEXT], f"Expected trimmed text: '{result[KEY_TEXT]}'"

    @pytest.mark.parametrize(
        "key,expected_value", [(KEY_STATUS, STATUS_SUCCESS),(KEY_TEXT, EMPTY_STRING),(KEY_LENGTH, ZERO),],
    )
    def test_when_extracting_from_empty_string_then_result_is_correct(
        self, processor, key, expected_value
    ):
        """Given an empty string, when extracting, then the result has the correct properties."""
        result = processor.extract_text_from_html(EMPTY_STRING)
        
        assert result[key] == expected_value, f"For key '{key}', expected '{expected_value}', got '{result.get(key)}'"

    @pytest.mark.parametrize("expected_key", [KEY_STATUS, KEY_TEXT, KEY_LENGTH, KEY_MESSAGE],)
    def test_when_extraction_succeeds_then_result_contains_expected_keys(self, processor, expected_key):
        """Given valid HTML, when extraction succeeds, then result contains expected keys."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)

        assert expected_key in result, f"Expected {expected_key} key in result: {result.keys()}"

    def test_when_extraction_fails_then_message_is_provided(self, processor):
        """Given malformed HTML, when extraction fails, then message is provided."""
        result = processor.extract_text_from_html(None)

        assert KEY_MESSAGE in result, f"Expected {KEY_MESSAGE} key in error result: {result.keys()}"

    def test_when_extraction_fails_then_no_text_or_length_keys(self, processor):
        """Given malformed HTML, when extraction fails, then no text or length keys."""
        result = processor.extract_text_from_html(None)

        assert KEY_TEXT not in result, f"Expected no {KEY_TEXT} in error result: {result.keys()}"

    def test_when_extraction_fails_then_status_is_error(self, processor):
        """Given malformed HTML, when extraction fails, then status is error."""
        result = processor.extract_text_from_html(None)

        assert result[KEY_STATUS] == STATUS_ERROR, f"Expected error status, got: {result.get(KEY_STATUS)}"





if __name__ == "__main__":
    pytest.main([__file__, "-v"])